"""Pluggable OCR runtime: in-thread (default) or isolated process (opt-in).

The process runtime gives a hard timeout: a stuck ONNX inference can be killed
and restarted, while the default thread runtime keeps the cheap in-process path.
Select with ``TIDYINVOICE_OCR_RUNTIME=thread|process``.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
from typing import Any, Callable


class OcrTimeout(RuntimeError):
    """The OCR call exceeded its deadline."""


class OcrRuntimeError(RuntimeError):
    """The OCR runtime could not start or communicate."""


def _load_default_engine() -> Any:
    from local_recognition import _load_ocr_engine

    return _load_ocr_engine()


class _SleepEngine:
    """Test double used by the process-runtime timeout test."""

    def __init__(self, seconds: float) -> None:
        self._seconds = float(seconds)

    def __call__(self, _image_bytes: bytes):
        time.sleep(self._seconds)
        return [], []


def _default_engine_factory() -> Any:
    if os.getenv("TIDYINVOICE_OCR_TEST_SLEEP"):
        return _SleepEngine(float(os.getenv("TIDYINVOICE_OCR_TEST_SLEEP", "0")))
    return _load_default_engine()


class ThreadOcrRuntime:
    mode = "thread"

    def __init__(self, engine_factory: Callable[[], Any] | None = None) -> None:
        self._factory = engine_factory or _default_engine_factory
        self._engine: Any = None
        self._engine_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    def _ensure_engine(self, engine: Any = None) -> Any:
        if engine is not None:
            return engine
        with self._engine_lock:
            if self._engine is None:
                self._engine = self._factory()
            return self._engine

    def infer(
        self,
        image_bytes: bytes,
        *,
        timeout: float,
        engine: Any = None,
    ) -> Any:
        target = self._ensure_engine(engine)
        done = threading.Event()
        outcome: dict[str, Any] = {}

        def runner() -> None:
            try:
                with self._inference_lock:
                    outcome["value"] = target(image_bytes)
            except BaseException as exc:  # propagated to the waiting caller
                outcome["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=runner, name="LocalOCR", daemon=True)
        thread.start()
        if not done.wait(max(0.01, float(timeout))):
            raise OcrTimeout(f"local OCR exceeded {timeout:.1f}s")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def close(self) -> None:
        self._engine = None


def _process_worker(connection: Any, factory: Callable[[], Any]) -> None:
    try:
        engine = factory()
    except BaseException as exc:  # pragma: no cover - depends on the child env
        connection.send(("init_error", str(exc)))
        return
    connection.send(("ready", None))
    while True:
        try:
            image_bytes = connection.recv()
        except EOFError:
            return
        if image_bytes is None:
            return
        try:
            connection.send(("ok", engine(image_bytes)))
        except BaseException as exc:  # pragma: no cover - engine failure
            connection.send(("error", str(exc)))


class ProcessOcrRuntime:
    mode = "process"

    def __init__(
        self,
        engine_factory: Callable[[], Any] | None = None,
        *,
        startup_timeout: float = 30.0,
    ) -> None:
        self._factory = engine_factory or _default_engine_factory
        self._startup_timeout = max(1.0, float(startup_timeout))
        self._process: Any = None
        self._connection: Any = None
        self._lock = threading.Lock()

    def _start_locked(self) -> None:
        context = mp.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(
            target=_process_worker,
            args=(child, self._factory),
            daemon=True,
        )
        process.start()
        child.close()
        if not parent.poll(self._startup_timeout):
            process.terminate()
            process.join(2)
            raise OcrRuntimeError("ocr process initialization timed out")
        status, payload = parent.recv()
        if status != "ready":
            process.terminate()
            process.join(2)
            raise OcrRuntimeError(f"ocr process initialization failed: {payload}")
        self._process = process
        self._connection = parent

    def _stop_locked(self) -> None:
        connection, process = self._connection, self._process
        self._connection = None
        self._process = None
        if connection is not None:
            try:
                connection.send(None)
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass
        if process is not None:
            process.join(2)
            if process.is_alive():
                process.terminate()
                process.join(2)

    def infer(
        self,
        image_bytes: bytes,
        *,
        timeout: float,
        engine: Any = None,
    ) -> Any:
        if engine is not None:
            raise OcrRuntimeError("process OCR runtime cannot use an injected engine")
        with self._lock:
            if self._process is None or not self._process.is_alive():
                self._stop_locked()
                self._start_locked()
            connection = self._connection
            try:
                connection.send(image_bytes)
            except (BrokenPipeError, OSError) as exc:
                self._stop_locked()
                raise OcrRuntimeError("ocr process send failed") from exc
            if not connection.poll(max(0.05, float(timeout))):
                self._stop_locked()
                raise OcrTimeout(f"ocr process exceeded {timeout:.1f}s")
            try:
                status, payload = connection.recv()
            except EOFError as exc:
                self._stop_locked()
                raise OcrRuntimeError("ocr process exited") from exc
        if status == "ok":
            return payload
        raise OcrRuntimeError(f"ocr process failed: {payload}")

    def close(self) -> None:
        with self._lock:
            self._stop_locked()

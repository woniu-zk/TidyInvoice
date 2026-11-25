#!/usr/bin/env python3
"""Real-OCR benchmark: thread runtime vs isolated process runtime.

Generates a synthetic Chinese invoice PDF, renders it at 200 DPI and measures
cold/warm OCR latency, two-worker concurrency, timeout kill/restart behaviour
and parent RSS. Requires the real RapidOCR engine (no fake engine here).

Usage:
    python tools/bench_ocr.py --mode both --pages 2 --iterations 10
    python tools/bench_ocr.py --mode process --json-out tmp/ocr-perf.json
"""

from __future__ import annotations

import argparse
import ctypes
import json
import multiprocessing
import os
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE_LINES = [
    "电子发票（普通发票）",
    "发票号码：26112000000012345678",
    "开票日期：2026年03月15日",
    "购买方信息",
    "名称：北京示例科技有限公司",
    "销售方信息",
    "名称：上海滴滴出行科技有限公司",
    "项目名称 规格型号 单位 数量 单价 金额 税率/征收率 税额",
    "*运输服务*客运服务费 1 100.00 100.00 3% 3.00",
    "合计 ¥100.00 ¥3.00",
    "价税合计（大写）壹佰零叁元整 （小写）¥103.00",
]


def _write_pdf(path: Path, pages: int = 2) -> Path:
    import fitz

    document = fitz.open()
    for _page_index in range(max(1, int(pages))):
        page = document.new_page()
        for index, line in enumerate(SAMPLE_LINES):
            page.insert_text(
                (72.0, 90.0 + index * 26.0), line, fontname="china-s", fontsize=10
            )
    document.save(str(path))
    document.close()
    return path


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "max": 0.0, "total": 0.0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "p50": round(statistics.median(values), 3),
        "p95": round(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))], 3),
        "max": round(max(values), 3),
        "total": round(sum(values), 3),
    }


def _current_rss_mb() -> float:
    try:
        if os.name == "nt":
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            handle = kernel32.GetCurrentProcess()
            getter = getattr(kernel32, "K32GetProcessMemoryInfo", None) or getattr(
                ctypes.windll.psapi, "GetProcessMemoryInfo", None
            )
            if getter is not None:
                getter.argtypes = [
                    ctypes.c_void_p,
                    ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                    ctypes.c_ulong,
                ]
                getter.restype = ctypes.c_bool
            if getter is not None and getter(
                handle, ctypes.byref(counters), counters.cb
            ):
                return round(counters.WorkingSetSize / (1024 * 1024), 1)
        else:
            import resource

            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return round(value / 1024, 1)
    except Exception:
        return 0.0
    return 0.0


def _run_thread_mode(pdf: Path, image: Path, iterations: int) -> dict:
    import local_recognition as lr

    lr.configure_ocr_runtime("thread")
    started = time.perf_counter()
    first_text = lr.read_pdf_ocr_text(pdf)
    cold_seconds = round(time.perf_counter() - started, 3)

    warm = []
    for _ in range(iterations):
        started = time.perf_counter()
        lr.read_image_ocr_text(image)
        warm.append(round(time.perf_counter() - started, 3))

    concurrent_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _index: lr.read_image_ocr_text(image), range(2)))
    concurrent_seconds = round(time.perf_counter() - concurrent_started, 3)

    return {
        "cold_pdf_seconds": cold_seconds,
        "cold_chars": len(first_text),
        "warm_image_seconds": _summary(warm),
        "two_worker_seconds": concurrent_seconds,
        "rss_mb": _current_rss_mb(),
        "leaked_children": len(multiprocessing.active_children()),
    }


def _run_process_mode(pdf: Path, image: Path, iterations: int, monkeypatch_env) -> dict:
    import local_recognition as lr

    monkeypatch_env("TIDYINVOICE_OCR_RUNTIME", None)
    lr.configure_ocr_runtime("process")
    started = time.perf_counter()
    first_text = lr.read_pdf_ocr_text(pdf)
    cold_seconds = round(time.perf_counter() - started, 3)

    warm = []
    for _ in range(iterations):
        started = time.perf_counter()
        lr.read_image_ocr_text(image)
        warm.append(round(time.perf_counter() - started, 3))

    concurrent_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _index: lr.read_image_ocr_text(image), range(2)))
    concurrent_seconds = round(time.perf_counter() - concurrent_started, 3)

    # Hard-timeout path: a sleeping child must be killed and the next call must
    # restart it without leaving an orphan process behind.
    monkeypatch_env("TIDYINVOICE_OCR_TEST_SLEEP", "2")
    # Force a fresh child so the injected sleep engine is actually used, and
    # start it eagerly so the timeout measurement excludes cold-start cost.
    lr.configure_ocr_runtime("thread")
    lr.configure_ocr_runtime("process")
    runtime = lr._get_ocr_runtime()
    startup_started = time.perf_counter()
    runtime.start()
    timeout_startup_seconds = round(time.perf_counter() - startup_started, 3)
    timeout_started = time.perf_counter()
    timeout_reason = ""
    try:
        lr._ocr_blocks_from_bytes(None, b"not-an-image", deadline=time.monotonic() + 0.5)
    except lr.LocalRecognitionUnavailable as exc:
        timeout_reason = str(getattr(exc, "reason_code", ""))
    timeout_seconds = round(time.perf_counter() - timeout_started, 3)
    monkeypatch_env("TIDYINVOICE_OCR_TEST_SLEEP", "0")
    lr.configure_ocr_runtime("thread")
    lr.configure_ocr_runtime("process")
    restart_started = time.perf_counter()
    lr.read_image_ocr_text(image)
    restart_seconds = round(time.perf_counter() - restart_started, 3)
    children_after_restart = len(multiprocessing.active_children())

    lr.configure_ocr_runtime("thread")
    return {
        "cold_pdf_seconds": cold_seconds,
        "cold_chars": len(first_text),
        "warm_image_seconds": _summary(warm),
        "two_worker_seconds": concurrent_seconds,
        "timeout_startup_seconds": timeout_startup_seconds,
        "timeout_seconds": timeout_seconds,
        "timeout_reason": timeout_reason,
        "restart_seconds": restart_seconds,
        "rss_mb": _current_rss_mb(),
        "children_after_restart": children_after_restart,
        "leaked_children_after_close": len(multiprocessing.active_children()),
    }


def main(argv=None) -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["thread", "process", "both"], default="both")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)
    iterations = max(1, min(int(args.iterations), 100))

    report: dict[str, object] = {
        "pages": args.pages,
        "iterations": iterations,
        "engine": "rapidocr_onnxruntime",
    }
    with tempfile.TemporaryDirectory(prefix="ocr-bench-") as temp_dir:
        temp = Path(temp_dir)
        pdf = _write_pdf(temp / "invoice.pdf", pages=args.pages)
        image = temp / "invoice.png"
        import fitz

        with fitz.open(str(pdf)) as document:
            pixmap = document.load_page(0).get_pixmap(dpi=200, alpha=False)
            image.write_bytes(pixmap.tobytes("png"))

        env_backup: dict[str, str | None] = {}

        def set_env(name: str, value: str | None) -> None:
            if name not in env_backup:
                env_backup[name] = os.environ.get(name)
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

        try:
            if args.mode in {"thread", "both"}:
                report["thread"] = _run_thread_mode(pdf, image, iterations)
            if args.mode in {"process", "both"}:
                report["process"] = _run_process_mode(pdf, image, iterations, set_env)
        finally:
            for name, value in env_backup.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

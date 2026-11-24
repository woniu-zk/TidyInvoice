"""Runtime selection tests for the optional isolated OCR process."""

from __future__ import annotations

import time

import pytest

from ocr_runtime import OcrTimeout, ProcessOcrRuntime, ThreadOcrRuntime


def test_thread_runtime_returns_engine_value():
    runtime = ThreadOcrRuntime(lambda: lambda _image: ([], []))

    assert runtime.infer(b"image", timeout=1.0) == ([], [])


def test_thread_runtime_times_out_without_killing_the_process():
    def slow(_image):
        time.sleep(0.5)
        return [], []

    runtime = ThreadOcrRuntime(lambda: slow)

    with pytest.raises(OcrTimeout):
        runtime.infer(b"image", timeout=0.05)


def test_process_runtime_kills_a_stuck_child_and_restarts(monkeypatch):
    monkeypatch.setenv("TIDYINVOICE_OCR_TEST_SLEEP", "2")
    runtime = ProcessOcrRuntime(startup_timeout=30)
    try:
        with pytest.raises(OcrTimeout):
            runtime.infer(b"image", timeout=0.3)

        monkeypatch.setenv("TIDYINVOICE_OCR_TEST_SLEEP", "0")
        assert runtime.infer(b"image", timeout=20) == ([], [])
    finally:
        runtime.close()


def test_local_recognition_switches_to_process_runtime(monkeypatch):
    import local_recognition as lr

    monkeypatch.setenv("TIDYINVOICE_OCR_TEST_SLEEP", "0")
    try:
        assert lr.configure_ocr_runtime("process") == "process"
        assert (
            lr._ocr_blocks_from_bytes(
                None, b"not-a-real-image", deadline=time.monotonic() + 20
            )
            == []
        )
    finally:
        lr.configure_ocr_runtime("thread")

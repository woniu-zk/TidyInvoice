#!/usr/bin/env python3
"""Offline micro-benchmark for the local invoice pipeline.

Generates synthetic fixtures, measures the deterministic fast path, the
content-digest throughput and the run-state sink cost, then prints a JSON
report. It never touches the network and uses a deterministic fake OCR engine so
results stay comparable across machines.

Usage:
    python tools/bench_pipeline.py --count 50
    python tools/bench_pipeline.py --count 50 --json-out tmp/perf.json
    python tools/bench_pipeline.py --count 50 --assert-budget
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE_TEXT = """电子发票（普通发票）
发票号码：26112000000012345678
开票日期：2026年03月15日
购买方信息
名称：北京示例科技有限公司
销售方信息
名称：上海滴滴出行科技有限公司
项目名称 规格型号 单位 数量 单价 金额 税率/征收率 税额
*运输服务*客运服务费 1 100.00 100.00 3% 3.00
合计 ¥100.00 ¥3.00
价税合计（大写）壹佰零叁元整 （小写）¥103.00
"""

# Loose budgets: the tool is a regression signal, not a machine benchmark.
BUDGETS = {
    "probe_p95_ms": 250.0,
    "recognize_p95_ms": 500.0,
    "ocr_recognize_p95_ms": 1000.0,
    "state_update_1000_ms": 500.0,
    "digest_mb_per_s_min": 50.0,
}


class FakeOcrEngine:
    """Deterministic OCR double so the benchmark does not depend on ONNX."""

    def __init__(self, text: str = SAMPLE_TEXT) -> None:
        self._lines = [line for line in text.splitlines() if line.strip()]

    def __call__(self, _image_bytes):
        blocks = []
        for index, text in enumerate(self._lines):
            y = float(index * 30)
            blocks.append(
                [[[0.0, y], [200.0, y], [200.0, y + 20.0], [0.0, y + 20.0]], text, 0.99]
            )
        return blocks, [0.01]


def _write_pdf(path: Path, text: str = SAMPLE_TEXT) -> Path:
    import fitz

    document = fitz.open()
    page = document.new_page()
    for index, line in enumerate(text.splitlines()):
        page.insert_text((72.0, 90.0 + index * 26.0), line, fontname="china-s", fontsize=10)
    document.save(str(path))
    document.close()
    return path


def _write_blank_pdf(path: Path) -> Path:
    import fitz

    document = fitz.open()
    document.new_page()
    document.save(str(path))
    document.close()
    return path


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "count": len(values),
        "p50": round(statistics.median(values), 3) if values else 0.0,
        "p95": round(_percentile(values, 0.95), 3),
        "max": round(max(values), 3) if values else 0.0,
    }


def run(count: int) -> dict:
    from candidate_pipeline import _stream_sha256
    from invoice_extractor import InvoiceExtractor
    from local_recognition import recognize_document
    from run_state_store import RunStateStore

    probe_ms: list[float] = []
    recognize_ms: list[float] = []
    ocr_recognize_ms: list[float] = []
    digest_mb_per_s: list[float] = []

    with tempfile.TemporaryDirectory(prefix="pipeline-bench-") as temp_dir:
        temp = Path(temp_dir)
        pdf = _write_pdf(temp / "invoice.pdf")
        blank_pdf = _write_blank_pdf(temp / "scanned.pdf")
        engine = FakeOcrEngine()

        for _ in range(count):
            # One extractor per document mirrors the production worker factory,
            # so the measurement includes the per-document setup cost.
            extractor = InvoiceExtractor(api_key="", output_dir=str(temp / "extracted"))
            started = time.perf_counter()
            extractor.probe_local_only(str(pdf))
            probe_ms.append((time.perf_counter() - started) * 1000.0)

        for _ in range(count):
            started = time.perf_counter()
            recognize_document(pdf)
            recognize_ms.append((time.perf_counter() - started) * 1000.0)

        for _ in range(count):
            started = time.perf_counter()
            recognize_document(blank_pdf, ocr_engine=engine)
            ocr_recognize_ms.append((time.perf_counter() - started) * 1000.0)

        payload = (temp / "digest.bin")
        payload.write_bytes(b"x" * (4 * 1024 * 1024))
        for _ in range(max(1, min(count, 10))):
            started = time.perf_counter()
            _stream_sha256(str(payload))
            elapsed = max(time.perf_counter() - started, 1e-9)
            digest_mb_per_s.append(4.0 / elapsed)

    state_ms: list[float] = []
    for _ in range(3):
        store = RunStateStore(state_sink=lambda _snapshot: None)
        store.reset("bench")
        started = time.perf_counter()
        for index in range(1000):
            store.add_processed({"path": f"/tmp/{index}.pdf", "amount": "1.00"})
        state_ms.append((time.perf_counter() - started) * 1000.0)

    tracemalloc.start()
    store = RunStateStore(state_sink=lambda _snapshot: None)
    store.reset("memory")
    for index in range(1000):
        store.add_processed({"path": f"/tmp/{index}.pdf"})
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    report = {
        "probe_ms": _summary(probe_ms),
        "recognize_ms": _summary(recognize_ms),
        "ocr_recognize_ms": _summary(ocr_recognize_ms),
        "state_update_1000_ms": round(statistics.median(state_ms), 3),
        "digest_mb_per_s": round(statistics.median(digest_mb_per_s), 3),
        "state_peak_mb": round(peak / (1024 * 1024), 3),
        "budgets": BUDGETS,
    }
    report["within_budget"] = {
        "probe_p95_ms": report["probe_ms"]["p95"] <= BUDGETS["probe_p95_ms"],
        "recognize_p95_ms": report["recognize_ms"]["p95"] <= BUDGETS["recognize_p95_ms"],
        "ocr_recognize_p95_ms": report["ocr_recognize_ms"]["p95"]
        <= BUDGETS["ocr_recognize_p95_ms"],
        "state_update_1000_ms": report["state_update_1000_ms"]
        <= BUDGETS["state_update_1000_ms"],
        "digest_mb_per_s": report["digest_mb_per_s"] >= BUDGETS["digest_mb_per_s_min"],
    }
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=20, help="iterations per measurement")
    parser.add_argument("--json-out", default="", help="write the JSON report to this path")
    parser.add_argument(
        "--assert-budget",
        action="store_true",
        help="exit non-zero when a budget is exceeded",
    )
    args = parser.parse_args(argv)
    count = max(1, min(int(args.count), 1000))

    report = run(count)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    if args.assert_budget and not all(report["within_budget"].values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

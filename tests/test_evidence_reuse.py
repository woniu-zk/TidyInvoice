"""Inventory stat-reuse tests for controlled-run evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import run_evidence as module
from run_evidence import RunEvidenceWriter, _CapturedRun


def _fixture(tmp_path: Path, *, mtime_offset: int = 0, digest: str | None = None):
    output = tmp_path / "output"
    target = output / "餐饮" / "invoice.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"invoice-bytes")
    stat = target.stat()
    expected = digest or hashlib.sha256(b"invoice-bytes").hexdigest()

    writer = RunEvidenceWriter(
        revision_resolver=lambda: "b" * 40,
        version_resolver=lambda: "2026.07.12",
        hardware_resolver=lambda: ("windows-desktop-standard", "fixture-host"),
        monotonic=lambda: 10.0,
        utc_clock=lambda: module.dt.datetime(2026, 6, 10, tzinfo=module.UTC),
    )
    captured = _CapturedRun(
        run_id="run-1",
        run_root=tmp_path / "run",
        output_root=output,
        scope={
            "hardware_mode": "windows-desktop-standard",
            "hardware_fingerprint": "fixture-host",
            "account_id": "account-hash",
            "account_channel": "qq",
            "mailbox": "INBOX",
            "target_identifier": "目标公司",
            "run_mode": "clean-mailbox",
        },
        candidate_revision="b" * 40,
        candidate_version="2026.07.12",
        hardware_mode="windows-desktop-standard",
        hardware_fingerprint="fixture-host",
        started_monotonic_seconds="1.0",
        started_at_utc="2026-06-10T00:00:00+00:00",
        lineage=[],
        output_stats={
            "餐饮/invoice.pdf": (
                stat.st_size,
                stat.st_mtime_ns + mtime_offset,
                expected,
            )
        },
    )
    writer._captured["run-1"] = captured
    context = SimpleNamespace(
        run_id="run-1",
        request=SimpleNamespace(validation_required=False, manifest_included_count=0),
    )
    return writer, context, target, expected


def test_finalize_reuses_unchanged_inventory_digest(tmp_path: Path, monkeypatch):
    writer, context, _target, expected = _fixture(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unchanged output must reuse its capture digest")

    monkeypatch.setattr(module, "_sha256_file", forbidden)
    evidence_path = writer.finalize(context, None)

    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    assert writer.last_inventory_reused == 1
    assert evidence["output_inventory"] == [
        {"relative_path": "餐饮/invoice.pdf", "size": 13, "sha256": expected}
    ]


def test_finalize_rehashes_when_stat_changes(tmp_path: Path, monkeypatch):
    writer, context, _target, _expected = _fixture(tmp_path, mtime_offset=1)
    calls = []
    real_hash = module._sha256_file

    def counting_hash(path):
        calls.append(str(path))
        return real_hash(path)

    monkeypatch.setattr(module, "_sha256_file", counting_hash)
    writer.finalize(context, None)

    assert writer.last_inventory_reused == 0
    assert len(calls) == 1

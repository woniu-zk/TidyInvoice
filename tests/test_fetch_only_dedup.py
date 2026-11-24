"""Regression tests for fetch-only inbox deduplication accounting."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fetch_handoff
from fetch_only import save_fetch_rows


def _rows(path: Path, **extra):
    row = {
        "filepath": str(path),
        "original_filename": path.name,
        "is_url": False,
        "email_id": "1",
        "mailbox": "INBOX",
        "received_at": "2026-03-15T10:00:00+08:00",
    }
    row.update(extra)
    return [row]


def test_save_fetch_rows_records_digest_and_counts_duplicates(tmp_path: Path):
    source = tmp_path / "source" / "invoice.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-1.4 duplicate fixture")

    first = save_fetch_rows(str(tmp_path / "library"), _rows(source))
    second = save_fetch_rows(str(tmp_path / "library"), _rows(source))

    assert first.saved_count == 1
    assert first.duplicate_count == 0
    assert second.saved_count == 0
    assert second.duplicate_count == 1

    entries, warnings = fetch_handoff.read_manifest(first.manifest_path)
    assert warnings == []
    assert len(entries) == 1
    assert entries[0].sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


def test_save_fetch_rows_reuses_row_digest_without_rehashing(tmp_path: Path, monkeypatch):
    source = tmp_path / "source" / "invoice.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-1.4 digest fixture")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("row digest must be reused")

    monkeypatch.setattr("fetch_only.fetch_handoff.sha256_file", forbidden)
    summary = save_fetch_rows(str(tmp_path / "library"), _rows(source, sha256=digest))

    assert summary.saved_count == 1
    assert summary.duplicate_count == 0
    entries, _ = fetch_handoff.read_manifest(summary.manifest_path)
    assert entries[0].sha256 == digest


def test_candidate_compatibility_key_reuses_ingest_digest(tmp_path: Path, monkeypatch):
    from candidate_pipeline import build_compatibility_history_key

    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"digest fixture")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("candidate must reuse the ingest digest")

    monkeypatch.setattr("candidate_pipeline._stream_sha256", forbidden)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    key = build_compatibility_history_key({"sha256": digest}, source.name, str(source))

    assert key == f"att:{digest}"

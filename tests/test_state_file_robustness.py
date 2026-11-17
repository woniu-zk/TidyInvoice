"""State-file robustness: BOM tolerance and corrupt-ledger recovery."""

from __future__ import annotations

import json
from pathlib import Path

import app_api
from app_api import InvoiceAppAPI
from invoice_extractor import InvoiceExtractor


def _api_with_state(tmp_path: Path, monkeypatch) -> tuple[InvoiceAppAPI, Path, Path]:
    api = InvoiceAppAPI()
    output = tmp_path / "output"
    output.mkdir()
    state = tmp_path / "state"
    monkeypatch.setattr(api, "_output_state_dir", lambda _path: str(state))
    monkeypatch.setattr(api, "_mark_output_run_state", lambda *args, **kwargs: None)
    return api, output, state


def test_read_json_file_tolerates_utf8_bom(tmp_path: Path):
    api = InvoiceAppAPI()
    path = tmp_path / "payload.json"
    path.write_text('{"history": ["a"], "business_records": {}}', encoding="utf-8-sig")

    assert api._read_json_file(str(path), None) == {
        "history": ["a"],
        "business_records": {},
    }


def test_bom_committed_state_is_loaded_without_failing_the_run(tmp_path: Path, monkeypatch):
    api, output, state = _api_with_state(tmp_path, monkeypatch)
    (output / "invoice.pdf").write_bytes(b"%PDF-1.4\nsynthetic")
    records = {"_111::invoice": {"file": "invoice.pdf"}}
    state.mkdir()
    (state / "committed_state.json").write_text(
        json.dumps({"history": ["history-a"], "business_records": records}),
        encoding="utf-8-sig",
    )
    (state / ".antigravity_history.json").write_text(
        json.dumps(["history-a"]), encoding="utf-8-sig"
    )

    extractor = InvoiceExtractor(api_key="", output_dir=str(output))
    session = api._create_processing_pipeline_session(
        [], "", str(output), _extractor=extractor, _prepare_remote_images=False
    )
    try:
        assert session._business_records == records
        assert session._working_history == {"history-a"}
    finally:
        session.close()

    assert not list(state.glob("committed_state.json.corrupt-*"))


def test_corrupt_committed_state_is_backed_up_and_run_continues(tmp_path: Path, monkeypatch):
    api, output, state = _api_with_state(tmp_path, monkeypatch)
    state.mkdir()
    (state / "committed_state.json").write_text("{truncated", encoding="utf-8")
    (state / ".antigravity_history.json").write_text('["old-history"]', encoding="utf-8")
    (state / "processed_records.json").write_text(
        '{"_999::invoice": {"file": "gone.pdf"}}', encoding="utf-8"
    )

    extractor = InvoiceExtractor(api_key="", output_dir=str(output))
    session = api._create_processing_pipeline_session(
        [], "", str(output), _extractor=extractor, _prepare_remote_images=False
    )
    try:
        assert session._business_records == {}
        assert session._working_history == set()
    finally:
        session.close()

    assert list(state.glob("committed_state.json.corrupt-*"))
    assert list(state.glob(".antigravity_history.json.corrupt-*"))
    assert list(state.glob("processed_records.json.corrupt-*"))


def test_bom_legacy_processed_records_are_readable(tmp_path: Path):
    api = InvoiceAppAPI()
    output = tmp_path / "output"
    output.mkdir()
    legacy = {"legacy-key": {"file": "old.pdf"}}
    (output / "processed_records.json").write_text(
        json.dumps(legacy), encoding="utf-8-sig"
    )

    records = api._load_business_records(str(output), str(tmp_path / "state"))

    assert records == legacy


def test_maintenance_helpers_exist():
    assert hasattr(app_api.InvoiceAppAPI, "_quarantine_unreadable_state")

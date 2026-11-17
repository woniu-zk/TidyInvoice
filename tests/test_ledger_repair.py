"""Ledger self-heal: archived files that disappeared must not block re-processing."""

from __future__ import annotations

import json
from pathlib import Path

import app_api
from app_api import InvoiceAppAPI
from invoice_extractor import InvoiceExtractor


def _write_committed_state(output_state_dir: Path, records: dict, history: list[str]) -> None:
    output_state_dir.mkdir(parents=True, exist_ok=True)
    (output_state_dir / "committed_state.json").write_text(
        json.dumps({"history": history, "business_records": records}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_state_dir / "processed_records.json").write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8"
    )
    (output_state_dir / ".antigravity_history.json").write_text(
        json.dumps(history, ensure_ascii=False), encoding="utf-8"
    )


def test_repair_drops_missing_files_and_clears_history(tmp_path: Path):
    api = InvoiceAppAPI()
    save_path = tmp_path / "output"
    (save_path / "餐饮").mkdir(parents=True)
    (save_path / "餐饮" / "existing.pdf").write_bytes(b"pdf")
    state_dir = tmp_path / "state"
    records = {
        "_111::invoice": {"file": "existing.pdf", "date": "20261018", "amount": "10.00"},
        "_222::invoice": {"file": "missing.pdf", "date": "20261019", "amount": "20.00"},
    }

    repaired_records, repaired_history = api._repair_stale_archive_ledger(
        str(save_path), str(state_dir), records, {"history-a", "history-b"}
    )

    assert set(repaired_records) == {"_111::invoice"}
    assert repaired_history == set()
    committed = json.loads((state_dir / "committed_state.json").read_text(encoding="utf-8"))
    assert committed["history"] == []
    assert committed["business_records"] == records_expected()
    backups = list(state_dir.glob("ledger-repair-*.json"))
    assert len(backups) == 1
    backup = json.loads(backups[0].read_text(encoding="utf-8"))
    assert backup["reason"] == "ARCHIVED_FILES_MISSING"
    assert set(backup["stale_records"]) == {"_222::invoice"}
    assert backup["history"] == ["history-a", "history-b"]


def records_expected() -> dict:
    return {
        "_111::invoice": {"file": "existing.pdf", "date": "20261018", "amount": "10.00"},
    }


def test_repair_is_noop_when_all_files_exist(tmp_path: Path):
    api = InvoiceAppAPI()
    save_path = tmp_path / "output"
    (save_path / "餐饮").mkdir(parents=True)
    (save_path / "餐饮" / "existing.pdf").write_bytes(b"pdf")
    state_dir = tmp_path / "state"
    records = {"_111::invoice": {"file": "existing.pdf"}}

    repaired_records, repaired_history = api._repair_stale_archive_ledger(
        str(save_path), str(state_dir), records, {"history-a"}
    )

    assert repaired_records == records
    assert repaired_history == {"history-a"}
    assert not list(state_dir.glob("ledger-repair-*.json"))


def test_audit_retention_evidence_does_not_count_as_archived_invoice(tmp_path: Path):
    api = InvoiceAppAPI()
    save_path = tmp_path / "output"
    retention = save_path / "_audit_retention" / "pipeline_retained"
    retention.mkdir(parents=True)
    (retention / "missing.pdf").write_bytes(b"evidence")
    state_dir = tmp_path / "state"
    records = {"_222::invoice": {"file": "missing.pdf"}}

    repaired_records, repaired_history = api._repair_stale_archive_ledger(
        str(save_path), str(state_dir), records, {"history-a"}
    )

    assert repaired_records == {}
    assert repaired_history == set()


def test_missing_save_root_marks_every_record_stale(tmp_path: Path):
    api = InvoiceAppAPI()
    records = {"_111::invoice": {"file": "a.pdf"}, "_222::invoice": {"file": "b.pdf"}}

    repaired_records, repaired_history = api._repair_stale_archive_ledger(
        str(tmp_path / "does-not-exist"), str(tmp_path / "state"), records, {"history-a"}
    )

    assert repaired_records == {}
    assert repaired_history == set()


def test_session_creation_rebuilds_stale_ledger(tmp_path: Path, monkeypatch):
    api = InvoiceAppAPI()
    save_path = tmp_path / "output"
    (save_path / "餐饮").mkdir(parents=True)
    (save_path / "餐饮" / "existing.pdf").write_bytes(b"pdf")
    output_state_dir = Path(api._output_state_dir(str(save_path)))
    _write_committed_state(
        output_state_dir,
        {
            "_111::invoice": {"file": "existing.pdf"},
            "_222::invoice": {"file": "gone.pdf"},
        },
        ["history-a", "history-b"],
    )
    monkeypatch.setattr(api, "_mark_output_run_state", lambda *args, **kwargs: None)

    extractor = InvoiceExtractor(api_key="", output_dir=str(tmp_path / "extract"))
    session = api._create_processing_pipeline_session(
        [], "", str(save_path), _extractor=extractor, _prepare_remote_images=False
    )
    try:
        assert "_222::invoice" not in session._business_records
        assert "_111::invoice" in session._business_records
        assert session._working_history == set()
    finally:
        session.close()

    committed = json.loads((output_state_dir / "committed_state.json").read_text(encoding="utf-8"))
    assert committed["history"] == []
    assert set(committed["business_records"]) == {"_111::invoice"}


def test_repair_logs_visible_maintenance_message(tmp_path: Path):
    api = InvoiceAppAPI()
    save_path = tmp_path / "output"
    save_path.mkdir()
    messages = []
    original_append = api.logs.append

    class CapturingLogs(list):
        def append(self, entry):
            messages.append(entry)
            return original_append(entry)

    api.logs = CapturingLogs()
    api._repair_stale_archive_ledger(
        str(save_path), str(tmp_path / "state"), {"_222::invoice": {"file": "gone.pdf"}}, {"h"}
    )

    assert any("重建去重台账" in str(entry.get("msg", "")) for entry in messages)


def test_module_exports_repair_helper():
    assert hasattr(app_api.InvoiceAppAPI, "_repair_stale_archive_ledger")
    assert hasattr(app_api.InvoiceAppAPI, "_archived_filename_index")

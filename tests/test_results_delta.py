"""Incremental results cursor and legacy-sync short-circuit tests."""

from __future__ import annotations

import json

import pytest

from app_api import InvoiceAppAPI
from run_state_store import RunStateStore


def _rows(count: int, prefix: str = "/tmp", start: int = 0):
    return [
        {
            "path": f"{prefix}/{index}.pdf",
            "date": "2026-06-10",
            "amount": "12.34",
            "merchant": "商户名称",
            "category": "餐饮",
        }
        for index in range(start, start + count)
    ]


def test_state_store_slice_and_counts():
    store = RunStateStore()
    store.reset("run-1")
    for path in ("/a", "/b", "/c"):
        store.add_processed({"path": path})
    store.add_error({"path": "/error"})

    assert store.sequence_counts() == {
        "processed_invoices": 3,
        "error_invoices": 1,
    }
    assert store.slice("processed_invoices", 1) == [
        {"path": "/b"},
        {"path": "/c"},
    ]
    with pytest.raises(ValueError):
        store.slice("logs", 0)


def test_get_results_delta_returns_only_new_rows_and_cursor():
    api = InvoiceAppAPI()
    api._run_state_store.reset("run-1")
    api.processed_invoices = _rows(3)
    api.error_invoices = []
    api._legacy_sync_signature = None

    first = api.get_results_delta(0, 0)
    assert first["run_id"] == "run-1"
    assert first["reset"] is False
    assert len(first["successInvoices"]) == 3
    assert first["cursor"] == {"success": 3, "error": 0}

    api.processed_invoices = api.processed_invoices + _rows(1, start=3)
    second = api.get_results_delta(3, 0)

    assert [row["path"] for row in second["successInvoices"]] == ["/tmp/3.pdf"]
    assert second["cursor"] == {"success": 4, "error": 0}


def test_get_results_delta_resets_when_run_changes_or_cursor_goes_backwards():
    api = InvoiceAppAPI()
    api._run_state_store.reset("run-1")
    api.processed_invoices = _rows(2)
    api.error_invoices = []
    api._legacy_sync_signature = None
    api.get_results_delta(0, 0)

    api._run_state_store.reset("run-2")
    api.processed_invoices = []
    api._legacy_sync_signature = None
    reset = api.get_results_delta(2, 0)

    assert reset["run_id"] == "run-2"
    assert reset["reset"] is True
    assert reset["successInvoices"] == []
    assert reset["cursor"] == {"success": 0, "error": 0}


def test_legacy_sync_short_circuits_when_nothing_changed():
    api = InvoiceAppAPI()
    calls = []

    class SpyStore:
        def update(self, **kwargs):
            calls.append(kwargs)

    api._run_state_store = SpyStore()
    api._legacy_sync_signature = None

    api._sync_run_state_store_from_legacy()
    api._sync_run_state_store_from_legacy()

    assert len(calls) == 1


def test_steady_state_delta_payload_stays_small():
    api = InvoiceAppAPI()
    api._run_state_store.reset("run-1")
    api.processed_invoices = _rows(300)
    api.error_invoices = []
    api._legacy_sync_signature = None
    api.get_results_delta(0, 0)

    delta = api.get_results_delta(300, 0)
    payload = json.dumps(delta, ensure_ascii=False).encode("utf-8")

    assert delta["successInvoices"] == []
    assert len(payload) < 10_000

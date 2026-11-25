"""Copy-on-write snapshot tests for RunStateStore."""

from __future__ import annotations

import copy

import run_state_store
from run_state_store import RunStateStore


def test_state_sink_snapshots_stay_stable_after_later_appends():
    snapshots = []
    store = RunStateStore(state_sink=snapshots.append)
    store.reset("run-1")

    store.add_processed({"id": 1})
    store.add_error({"id": "e1"})
    store.append_log("信息", "first")

    first = snapshots[-1]
    assert len(first["processed_invoices"]) == 1
    assert len(first["error_invoices"]) == 1
    assert len(first["logs"]) == 1

    store.add_processed({"id": 2})
    store.add_error({"id": "e2"})
    store.append_log("信息", "second")

    # Previously delivered views must not observe later writes.
    assert len(first["processed_invoices"]) == 1
    assert len(first["error_invoices"]) == 1
    assert len(first["logs"]) == 1

    latest = snapshots[-1]
    assert len(latest["processed_invoices"]) == 2
    assert len(latest["error_invoices"]) == 2
    assert len(latest["logs"]) == 2


def test_add_processed_does_not_deepcopy_the_existing_invoice_list(monkeypatch):
    store = RunStateStore(state_sink=lambda _snapshot: None)
    store.reset("run-1")
    for index in range(500):
        store.add_processed({"id": index})

    real_deepcopy = copy.deepcopy
    calls = {"count": 0}

    def counting_deepcopy(value, *args, **kwargs):
        calls["count"] += 1
        return real_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr(run_state_store.copy, "deepcopy", counting_deepcopy)
    store.add_processed({"id": 500, "meta": {"tags": ["a"]}})

    # Only the incoming item is copied once; the 500 existing invoices are not.
    assert calls["count"] <= 2
    assert len(store.snapshot()["processed_invoices"]) == 501


def test_snapshot_remains_isolated_from_the_store():
    store = RunStateStore(state_sink=lambda _snapshot: None)
    store.reset("run-1")
    store.add_processed({"id": 1, "meta": {"tags": ["a"]}})

    snapshot = store.snapshot()
    snapshot["processed_invoices"][0]["meta"]["tags"].append("mutated")
    snapshot["processed_invoices"].append({"id": 2})

    assert store.snapshot()["processed_invoices"] == [
        {"id": 1, "meta": {"tags": ["a"]}}
    ]

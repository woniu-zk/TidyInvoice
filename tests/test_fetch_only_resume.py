"""Resume/checkpoint tests for the fetch-only runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fetch_handoff
from fetch_only import FetchOnlyRequest, FetchOnlyRunner


class FakeFetcher:
    def __init__(
        self,
        uids,
        sources: dict[int, Path],
        *,
        uidvalidity: str = "uv-1",
        unresolved_batches: set[int] | None = None,
        fail_after_batch: int | None = None,
    ):
        self.uids = list(uids)
        self.sources = sources
        self.uidvalidity = uidvalidity
        self.unresolved_batches = set(unresolved_batches or ())
        self.fail_after_batch = fail_after_batch
        self.extract_received: list[object] = []

    def connect(self):
        return True

    def disconnect(self):
        return None

    def fetch_emails_by_date(self, since_date, before_date, mailbox="INBOX"):
        return list(self.uids)

    def extract_attachments(self, email_ids, mailbox="INBOX", *, batch_callback=None):
        self.extract_received = list(email_ids)
        rows = []
        batch_size = 2
        for index in range(0, len(email_ids), batch_size):
            batch_number = index // batch_size + 1
            batch_uids = list(email_ids[index : index + batch_size])
            batch_rows = []
            for uid in batch_uids:
                value = int(uid)
                row = {
                    "filepath": str(self.sources[value]),
                    "original_filename": f"{value}.pdf",
                    "is_url": False,
                    "email_id": str(value),
                    "received_at": "2026-06-10T10:00:00+08:00",
                }
                rows.append(row)
                batch_rows.append(row)
            if batch_callback is not None:
                unresolved = (
                    batch_uids if batch_number in self.unresolved_batches else []
                )
                batch_callback(batch_rows, batch_uids, unresolved)
            if self.fail_after_batch and batch_number >= self.fail_after_batch:
                raise RuntimeError("simulated fetch failure")
        return rows


def _sources(tmp_path: Path, count: int = 6) -> dict[int, Path]:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    sources = {}
    for value in range(1, count + 1):
        path = source_dir / f"{value}.pdf"
        path.write_bytes(f"invoice-{value}".encode())
        sources[value] = path
    return sources


def _run(tmp_path: Path, fetcher: FakeFetcher):
    return FetchOnlyRunner(
        fetcher_factory=lambda *_args, **_kwargs: fetcher
    ).run(
        FetchOnlyRequest(
            email_address="user@example.com",
            auth_code="auth",
            output_dir=str(tmp_path / "library"),
        )
    )


def _state(tmp_path: Path) -> dict:
    path = tmp_path / "library" / "inbox" / fetch_handoff.FETCH_STATE_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def test_second_run_skips_uids_at_or_below_checkpoint(tmp_path: Path):
    sources = _sources(tmp_path)
    first = FakeFetcher([b"1", b"2", b"3", b"4"], sources, uidvalidity="uv-1")
    result = _run(tmp_path, first)

    assert result.ok is True
    assert result.saved_count == 4
    assert result.skipped_count == 0
    state = _state(tmp_path)
    assert state["version"] == 2
    assert state["uidvalidity"] == "uv-1"
    assert state["last_uid"] == 4

    second = FakeFetcher([b"1", b"2", b"3", b"4"], sources, uidvalidity="uv-1")
    resumed = _run(tmp_path, second)

    assert second.extract_received == []
    assert resumed.saved_count == 0
    assert resumed.skipped_count == 4


def test_uidvalidity_change_forces_full_refetch(tmp_path: Path):
    sources = _sources(tmp_path, count=2)
    _run(
        tmp_path,
        FakeFetcher([b"1", b"2"], sources, uidvalidity="uv-1"),
    )

    changed = FakeFetcher([b"1", b"2"], sources, uidvalidity="uv-2")
    result = _run(tmp_path, changed)

    assert changed.extract_received == [b"1", b"2"]
    assert result.skipped_count == 0
    assert result.duplicate_count == 2


def test_checkpoint_stops_at_first_unresolved_batch(tmp_path: Path):
    sources = _sources(tmp_path, count=6)
    fetcher = FakeFetcher(
        [b"1", b"2", b"3", b"4", b"5", b"6"],
        sources,
        unresolved_batches={2},
    )
    result = _run(tmp_path, fetcher)

    assert result.saved_count == 6
    assert _state(tmp_path)["last_uid"] == 2


def test_failure_after_first_batch_keeps_checkpoint_and_resumes(tmp_path: Path):
    sources = _sources(tmp_path, count=4)
    failing = FakeFetcher(
        [b"1", b"2", b"3", b"4"],
        sources,
        fail_after_batch=1,
    )

    with pytest.raises(RuntimeError, match="simulated fetch failure"):
        _run(tmp_path, failing)

    assert _state(tmp_path)["last_uid"] == 2
    inbox = tmp_path / "library" / "inbox"
    saved = [path for path in inbox.rglob("*.pdf")]
    assert len(saved) == 2

    resumed = FakeFetcher([b"1", b"2", b"3", b"4"], sources)
    result = _run(tmp_path, resumed)

    assert resumed.extract_received == [b"3", b"4"]
    assert result.saved_count == 2
    assert _state(tmp_path)["last_uid"] == 4

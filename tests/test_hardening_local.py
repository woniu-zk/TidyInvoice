"""Regression tests for the backend hardening pass (task-5).

Covers three audited defects:

1. Windows release builds have no ``tzdata`` package, so ``ZoneInfo(
   "Asia/Shanghai")`` at import time crashed the packaged app. The fixed
   +08:00 offset must let the release modules import with no site-packages /
   with ``tzdata`` blocked.
2. ZIP/RFC822 decompression-bomb DoS: hostile archives and oversized raw
   messages must be rejected through declared-size/count/depth caps *before*
   an oversized read, with skip reasons surfaced through diagnostics.
3. ``RunStateStore`` deep-copied the whole state on every 1 s/3 s poll. The
   optimized store must stay semantically equivalent to the pre-hardening
   implementation while copying only what changed.
"""

from __future__ import annotations

import copy
import functools
import io
import subprocess
import sys
import time
import tracemalloc
import zipfile
from email.message import EmailMessage
from pathlib import Path

import email_fetcher
import run_state_store
from run_state_store import RunStateStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.is_file():  # pragma: no cover - non-Windows/edge checkout
    VENV_PYTHON = Path(sys.executable)


# ==========================================================================
# 1) tzdata-free import regression
# ==========================================================================
def test_domain_modules_import_without_site_packages():
    """``-S`` removes site-packages (and therefore tzdata) entirely."""

    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        "import invoice_domain\n"
        "import mailbox_scanner\n"
        "from datetime import timedelta\n"
        "assert invoice_domain._SHANGHAI.utcoffset(None) == timedelta(hours=8)\n"
        "assert mailbox_scanner.SHANGHAI_TZ.utcoffset(None) == timedelta(hours=8)\n"
        "assert 'zoneinfo' not in sys.modules\n"
        "print('IMPORT_OK')\n"
    )
    completed = subprocess.run(
        [str(VENV_PYTHON), "-S", "-c", script],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stderr
    assert "IMPORT_OK" in completed.stdout


def test_email_modules_import_with_tzdata_blocked():
    """Import the runtime/IMAP modules with the tzdata package made unimportable."""

    script = f"""
import sys
sys.path.insert(0, {str(PROJECT_ROOT)!r})

class _BlockTzdata:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tzdata" or fullname.startswith("tzdata."):
            raise ModuleNotFoundError("No module named %r" % fullname)
        return None

sys.meta_path.insert(0, _BlockTzdata())
for _name in [m for m in sys.modules if m == "tzdata" or m.startswith("tzdata.")]:
    del sys.modules[_name]

import zoneinfo
zoneinfo.reset_tzpath(to=[])
try:
    zoneinfo.ZoneInfo("Asia/Shanghai")
except Exception as exc:
    print("ZONEINFO_BLOCKED:" + type(exc).__name__)
else:
    raise SystemExit("tzdata blocker ineffective: ZoneInfo still resolvable")

import invoice_domain
import mailbox_scanner
import email_fetcher
import build_truth_dataset
print("IMPORT_OK")
"""
    completed = subprocess.run(
        [str(VENV_PYTHON), "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ZONEINFO_BLOCKED" in completed.stdout
    assert "IMPORT_OK" in completed.stdout


def test_fixed_offset_matches_asia_shanghai_for_modern_dates():
    """Behavior parity proof: fixed +08:00 == tzdata Asia/Shanghai post-1991."""

    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    import invoice_domain
    from mailbox_scanner import SHANGHAI_TZ, MailboxScanner

    fixed = timezone(timedelta(hours=8))
    shanghai = ZoneInfo("Asia/Shanghai")
    samples = [
        datetime(2026, 6, 1, 16, 30, tzinfo=timezone.utc),
        datetime(2026, 2, 4, 14, 32, 39, tzinfo=timezone(timedelta(hours=-5))),
        datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    ]
    for value in samples:
        fixed_value = value.astimezone(fixed)
        zoneinfo_value = value.astimezone(shanghai)
        assert fixed_value == zoneinfo_value
        assert fixed_value.utcoffset() == zoneinfo_value.utcoffset() == timedelta(hours=8)
        assert fixed_value.isoformat() == zoneinfo_value.isoformat()
        assert invoice_domain.parse_local_date(value) == invoice_domain.parse_local_date(
            zoneinfo_value
        )

    naive = datetime(2026, 6, 1, 8, 30)
    assert (
        MailboxScanner._to_shanghai(naive).isoformat()
        == naive.replace(tzinfo=shanghai).isoformat()
    )
    assert SHANGHAI_TZ.utcoffset(None) == timedelta(hours=8)


# ==========================================================================
# 2) ZIP / RFC822 decompression-bomb limits
# ==========================================================================
def _zip_bytes(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


@functools.lru_cache(maxsize=1)
def _hostile_bomb_zip():
    """~65 KB archive whose single member declares 64 MiB uncompressed."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        archive.writestr("invoice.pdf", b"\0" * (64 * 1024 * 1024))
    payload = buffer.getvalue()
    assert len(payload) < 128 * 1024  # tiny on the wire
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.getinfo("invoice.pdf").file_size == 64 * 1024 * 1024
    return payload


def test_zip_member_cap_rejects_declared_bomb_before_any_read(monkeypatch):
    payload = _hostile_bomb_zip()

    def _forbidden_read(_self, name, pwd=None):
        raise AssertionError(f"zf.read() must never run for a capped member: {name}")

    monkeypatch.setattr(zipfile.ZipFile, "read", _forbidden_read)

    tracemalloc.start()
    try:
        expansion = email_fetcher._expand_zip_attachment(
            payload, zip_depth=0, filename="bomb.zip"
        )
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert expansion.rejected is False
    assert expansion.members == []
    assert [item["reason"] for item in expansion.skipped] == ["zip_member_too_large"]
    assert expansion.skipped[0]["declared_bytes"] == 64 * 1024 * 1024
    # No decompression of the 64 MiB member happened: only ZIP metadata was read.
    assert peak < 8 * 1024 * 1024, f"unexpected allocation peak: {peak}"


def test_zip_member_count_cap_rejects_whole_archive(monkeypatch):
    allowed = _zip_bytes([(f"invoice-{index}.pdf", b"%PDF-1.4\n") for index in range(64)])
    expansion = email_fetcher._expand_zip_attachment(allowed)
    assert expansion.rejected is False
    assert len(expansion.members) == 64

    def _forbidden_read(_self, name, pwd=None):
        raise AssertionError("overflowing archive members must not be read")

    monkeypatch.setattr(zipfile.ZipFile, "read", _forbidden_read)
    oversized = _zip_bytes(
        [(f"invoice-{index}.pdf", b"%PDF-1.4\n") for index in range(65)]
    )
    expansion = email_fetcher._expand_zip_attachment(oversized)
    assert expansion.rejected is True
    assert expansion.reject_reason == "zip_member_count_exceeded"
    assert expansion.members == []
    assert expansion.member_count == 65


def test_zip_total_uncompressed_cap_skips_excess_members(monkeypatch):
    monkeypatch.setattr(email_fetcher, "MAX_ZIP_TOTAL_BYTES", 1024)
    payload = _zip_bytes(
        [
            ("a.pdf", b"A" * 512),
            ("b.pdf", b"B" * 512),
            ("c.pdf", b"C" * 512),
        ]
    )
    expansion = email_fetcher._expand_zip_attachment(payload)
    assert [member["filename"] for member in expansion.members] == ["a.pdf", "b.pdf"]
    assert [item["reason"] for item in expansion.skipped] == ["zip_total_size_exceeded"]
    assert sum(len(member["payload"]) for member in expansion.members) <= 1024


def test_nested_zip_depth_cap_stops_expanding_third_level_archive():
    level_four = _zip_bytes([("final.pdf", b"%PDF-1.4 level4")])
    level_three = _zip_bytes([("level4.zip", level_four)])
    level_two = _zip_bytes([("level3.zip", level_three)])
    level_one = _zip_bytes([("level2.zip", level_two)])

    first = email_fetcher._expand_zip_attachment(level_one, zip_depth=0)
    assert [member["filename"] for member in first.members] == ["level2.zip"]
    assert first.members[0]["zip_depth"] == 1
    second = email_fetcher._expand_zip_attachment(
        first.members[0]["payload"], zip_depth=1
    )
    assert [member["filename"] for member in second.members] == ["level3.zip"]
    third = email_fetcher._expand_zip_attachment(
        second.members[0]["payload"], zip_depth=2
    )
    # A third nested archive is refused before its members can be read.
    assert third.members == []
    assert [item["reason"] for item in third.skipped] == [
        "zip_nesting_depth_exceeded"
    ]


def test_lying_zip_header_cannot_expand_past_member_cap():
    payload = _hostile_bomb_zip()  # 64 MiB member, ~65 KB on the wire
    buffer = io.BytesIO(payload)
    with zipfile.ZipFile(buffer) as archive:
        info = archive.getinfo("invoice.pdf")
        info.file_size = 16  # attacker-controlled central-directory lie
        tracemalloc.start()
        try:
            try:
                result = email_fetcher._read_zip_member_bounded(archive, info, 1024)
            except zipfile.BadZipFile:
                # zipfile itself rejects the size/CRC mismatch after a bounded
                # read; either outcome must never materialise the member.
                result = None
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    assert result is None
    assert peak < 8 * 1024 * 1024, f"unexpected allocation peak: {peak}"


class _FakeUidMail:
    """Minimal imaplib double: enough for MailboxScanner/EmailFetcher."""

    def __init__(self, messages):
        self.messages = dict(messages)
        self.ids = list(messages)
        self.uid_calls = []

    def select(self, mailbox, readonly=True):
        return "ok", [b""]

    def uid(self, command, *args):
        self.uid_calls.append((command, args))
        if command.upper() == "SEARCH":
            return "ok", [b" ".join(self.ids)]
        uid_set, query = args
        requested = uid_set.split(b",")
        parts = []
        if "HEADER.FIELDS" in query:
            return "ok", parts
        for sequence, uid in enumerate(reversed(requested), 900):
            parts.append(
                (f"{sequence} (UID {uid.decode()} RFC822".encode(), self.messages[uid])
            )
        return "ok", parts


def _attachment_message(*, filename, payload, body="Attached", subject="Invoice attachment"):
    message = EmailMessage()
    message["From"] = "billing@example.com"
    message["To"] = "invoice-user@example.com"
    message["Subject"] = subject
    message.set_content(body)
    message.add_attachment(
        payload, maintype="application", subtype="octet-stream", filename=filename
    )
    return message.as_bytes()


def _runtime_fetcher(tmp_path, raw_message, *, monitoring=True):
    fetcher = email_fetcher.EmailFetcher(
        "invoice-user@example.com",
        "auth-code",
        staging_dir=str(tmp_path / "staging"),
        monitoring_dir=str(tmp_path / "monitoring") if monitoring else None,
    )
    fetcher.mail = _FakeUidMail({b"1": raw_message})
    return fetcher


def test_valid_zip_still_expands_invoice_members(tmp_path):
    member_bytes = b"%PDF-1.4 normal invoice"
    payload = _zip_bytes(
        [
            ("invoice.pdf", member_bytes),
            ("readme.txt", b"not an extractable extension"),
        ]
    )
    raw = _attachment_message(filename="invoice-bundle.zip", payload=payload)
    fetcher = _runtime_fetcher(tmp_path, raw)

    result = fetcher.extract_attachments([b"1"])

    staged = [entry for entry in result if entry["original_filename"] == "invoice.pdf"]
    assert len(staged) == 1
    assert Path(staged[0]["filepath"]).read_bytes() == member_bytes


def test_oversized_zip_attachment_is_retained_and_reasons_are_diagnosed(tmp_path):
    hostile = _hostile_bomb_zip()
    raw = _attachment_message(filename="invoice-bomb.zip", payload=hostile)
    fetcher = _runtime_fetcher(tmp_path, raw)

    tracemalloc.start()
    try:
        result = fetcher.extract_attachments([b"1"])
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert peak < 32 * 1024 * 1024, f"unexpected allocation peak: {peak}"
    assert len(result) == 1
    entry = result[0]
    # The outer container is retained as evidence instead of silently dropped.
    assert entry["original_filename"] == "invoice-bomb.zip"
    assert entry["candidate_action"] == "retain_only"
    assert entry["prefilter_reason_code"] == "B_ZIP_CONTAINER_REJECTED"
    assert Path(entry["filepath"]).read_bytes() == hostile

    diagnostics = (tmp_path / "monitoring" / "extract_attachments_diagnostics.jsonl").read_text(
        encoding="utf-8"
    )
    assert "zip_member_too_large" in diagnostics
    inventory = (tmp_path / "monitoring" / "input_attachment_inventory.jsonl").read_text(
        encoding="utf-8"
    )
    assert "zip_container_rejected" in inventory


def test_nested_zip_depth_cap_surfaces_in_diagnostics(tmp_path):
    level_four = _zip_bytes([("final.pdf", b"%PDF-1.4 level4")])
    level_three = _zip_bytes([("level4.zip", level_four)])
    level_two = _zip_bytes([("level3.zip", level_three)])
    level_one = _zip_bytes([("level2.zip", level_two)])
    raw = _attachment_message(filename="invoice-nest.zip", payload=level_one)
    fetcher = _runtime_fetcher(tmp_path, raw)

    result = fetcher.extract_attachments([b"1"])

    staged_names = sorted(path.name for path in (tmp_path / "staging").rglob("*") if path.is_file())
    assert "final.pdf" not in staged_names
    assert "level4.zip" not in staged_names
    assert any(entry["original_filename"] == "level3.zip" for entry in result)

    diagnostics = (tmp_path / "monitoring" / "extract_attachments_diagnostics.jsonl").read_text(
        encoding="utf-8"
    )
    assert "zip_nesting_depth_exceeded" in diagnostics


def test_raw_rfc822_size_cap_skips_message_without_failing_run(tmp_path):
    raw = _attachment_message(
        filename="invoice.pdf",
        payload=b"%PDF-1.4\n",
        body="x" * 8192,
    )
    fetcher = _runtime_fetcher(tmp_path, raw)
    fetcher.max_raw_message_bytes = 1024

    result = fetcher.extract_attachments([b"1"])  # must not raise

    assert result == []
    assert not any((tmp_path / "staging").rglob("*"))
    diagnostics = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "monitoring").glob("*.jsonl")
    )
    assert "raw_message_too_large" in diagnostics
    assert "imap_message_too_large_skipped" in diagnostics
    assert "x" * 64 not in diagnostics  # message content never leaks


def test_mailbox_scanner_drops_oversized_payload_before_buffering():
    payload = b"P" * 300
    events = []

    def fetch(_uid_set, _query):
        return "ok", [(b"1 (UID 1 RFC822", payload)]

    mail = _FakeUidMail({b"1": b"unused"})
    mail.uid = lambda command, *args: (
        events.append(("uid", command)) or "ok", [(b"1 (UID 1 RFC822", payload)]
    )
    scanner = email_fetcher.MailboxScanner(
        mail, max_message_bytes=100, max_attempts=1, diagnostic_callback=events.append
    )
    batches = list(scanner.iter_message_batches([b"1"]))

    assert len(batches) == 1
    assert batches[0].messages == ()
    assert batches[0].unresolved_uids == ()
    assert batches[0].oversized_messages == ((b"1", 300),)
    oversized_events = [
        event for event in events if isinstance(event, dict) and event.get("event") == "imap_message_payload_too_large"
    ]
    assert len(oversized_events) == 1
    assert oversized_events[0]["payload_bytes"] == 300
    assert oversized_events[0]["limit"] == 100
    assert "PPP" not in repr(events)


# ==========================================================================
# 3) RunStateStore poll-copy optimization
# ==========================================================================
class _LegacyRunStateStore:
    """Executable oracle: the pre-hardening (baseline cfbd852) implementation.

    Every call deep-copied the whole state; it is kept verbatim enough to be a
    semantic reference for the optimized store (no-op notifications aside).
    """

    def __init__(self, event_sink=None, state_sink=None):
        self._lock = run_state_store.threading.RLock()
        self._event_sink = event_sink
        self._state_sink = state_sink
        self._terminal = False
        self._terminal_reason = ""
        self._state = RunStateStore._initial_state("")

    @property
    def terminal_reason(self):
        with self._lock:
            return self._terminal_reason

    def _emit(self, snapshot):
        callback = self._event_sink
        if callback is None:
            return
        try:
            callback(copy.deepcopy(snapshot))
        except Exception:
            return

    def _sync_state_sink(self, snapshot):
        callback = self._state_sink
        if callback is None:
            return
        try:
            callback(copy.deepcopy(snapshot))
        except Exception:
            return

    def reset(self, run_id, *, status_text="等待任务开始...", run_state="idle", progress=0):
        with self._lock:
            self._state = RunStateStore._initial_state(run_id)
            self._state["status_text"] = str(status_text)
            self._state["run_state"] = str(run_state)
            self._state["progress"] = max(0, min(100, int(progress)))
            self._state["is_running"] = self._state["run_state"] in {"running", "finalizing"}
            self._state["can_stop"] = self._state["run_state"] == "running"
            self._terminal = False
            self._terminal_reason = ""
            snapshot = copy.deepcopy(self._state)
            self._sync_state_sink(snapshot)
        self._emit(snapshot)

    def update(
        self,
        *,
        progress=None,
        status_text=None,
        run_state=None,
        last_error=None,
        stop_requested=None,
        quota_exhausted=None,
        quota_message=None,
        statistics=None,
        processed_invoices=None,
        error_invoices=None,
        categories=None,
        logs=None,
    ):
        with self._lock:
            if self._terminal:
                return
            if progress is not None:
                bounded = max(0, min(100, int(progress)))
                self._state["progress"] = max(int(self._state["progress"]), bounded)
            if status_text is not None:
                self._state["status_text"] = str(status_text)
            if run_state is not None:
                normalized = str(run_state)
                self._state["run_state"] = normalized
                self._state["is_running"] = normalized in {"running", "finalizing"}
            if last_error is not None:
                self._state["last_error"] = str(last_error)
            if stop_requested is not None:
                self._state["stop_requested"] = bool(stop_requested)
            if quota_exhausted is not None:
                self._state["quota_exhausted"] = bool(quota_exhausted)
            if quota_message is not None:
                self._state["quota_message"] = str(quota_message)
            if statistics is not None:
                self._state["stats"] = copy.deepcopy(dict(statistics))
            if processed_invoices is not None:
                self._state["processed_invoices"] = copy.deepcopy(list(processed_invoices))
            if error_invoices is not None:
                self._state["error_invoices"] = copy.deepcopy(list(error_invoices))
            if categories is not None:
                self._state["new_categories"] = sorted({str(item) for item in categories})
            if logs is not None:
                self._state["logs"] = copy.deepcopy(list(logs))
            self._state["can_stop"] = bool(
                self._state["run_state"] == "running"
                and self._state["is_running"]
                and not self._state["stop_requested"]
            )
            snapshot = copy.deepcopy(self._state)
            self._sync_state_sink(snapshot)
        self._emit(snapshot)

    def append_log(self, level, message, color="text-slate-700"):
        with self._lock:
            if self._terminal:
                return
            self._state["logs"].append(
                {
                    "time": time.strftime("[%H:%M:%S]"),
                    "type": str(level),
                    "color": str(color),
                    "msg": str(message),
                }
            )
            snapshot = copy.deepcopy(self._state)
            self._sync_state_sink(snapshot)
        self._emit(snapshot)

    def add_processed(self, item):
        with self._lock:
            if self._terminal:
                return
            self._state["processed_invoices"].append(copy.deepcopy(dict(item)))
            snapshot = copy.deepcopy(self._state)
            self._sync_state_sink(snapshot)
        self._emit(snapshot)

    def add_error(self, item):
        with self._lock:
            if self._terminal:
                return
            self._state["error_invoices"].append(copy.deepcopy(dict(item)))
            snapshot = copy.deepcopy(self._state)
            self._sync_state_sink(snapshot)
        self._emit(snapshot)

    def terminalize(self, state, *, status_text, last_error="", reason_code="", logs=None, statistics=None):
        normalized = str(state)
        if normalized not in {"completed", "failed"}:
            raise ValueError("terminal state must be completed or failed")
        with self._lock:
            if self._terminal:
                return
            self._state["run_state"] = normalized
            self._state["is_running"] = False
            self._state["can_stop"] = False
            self._state["status_text"] = str(status_text)
            self._state["last_error"] = str(last_error)
            if logs:
                self._state["logs"].extend(copy.deepcopy(list(logs)))
            if statistics is not None:
                self._state["stats"] = copy.deepcopy(dict(statistics))
            self._terminal_reason = str(reason_code or "")
            if normalized == "completed":
                self._state["progress"] = 100
            elif self._state["progress"] >= 100:
                self._state["progress"] = 99
            self._terminal = True
            snapshot = copy.deepcopy(self._state)
            self._sync_state_sink(snapshot)
        self._emit(snapshot)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def frontend_snapshot(self, *, build_identity=None, raw_date_range="", imap_query_range=""):
        snapshot = self.snapshot()
        snapshot["logs"] = snapshot["logs"][-20:]
        snapshot.pop("processed_invoices", None)
        snapshot.pop("error_invoices", None)
        snapshot.pop("run_id", None)
        snapshot["build_identity"] = copy.deepcopy(dict(build_identity or {}))
        snapshot["raw_date_range"] = str(raw_date_range or "")
        snapshot["imap_query_range"] = str(imap_query_range or "")
        return snapshot


def _drive_store(store):
    """Apply the same operation stream to any compatible store."""

    store.reset("run-1")
    steps = []

    def record(label):
        steps.append(
            (
                label,
                store.snapshot(),
                store.frontend_snapshot(
                    build_identity={"label": {"nested": [1]}},
                    raw_date_range="2026-06-01 ~ 2026-06-30",
                    imap_query_range="01-Jun-2026:30-Jun-2026",
                ),
                store.terminal_reason,
            )
        )

    record("reset")
    store.update(
        progress=50,
        status_text="half",
        statistics={"emails": 2, "nested": {"x": [1]}},
        logs=[{"msg": "one"}],
    )
    record("update-scalars")
    store.update(progress=10)  # monotonic clamp, no other change
    record("progress-lower")
    store.update(run_state="running", stop_requested=False)
    record("running")
    invoices = [{"id": 1, "meta": {"items": [1, 2]}}]
    store.update(
        processed_invoices=invoices,
        error_invoices=[{"id": "e1", "meta": {}}],
        categories=["b", "a", "b"],
        logs=[{"msg": "one"}, {"msg": "two"}],
    )
    record("sequences")
    invoices.append({"id": 2, "meta": {"items": [3]}})
    store.update(processed_invoices=invoices, logs=[{"msg": "one"}, {"msg": "two"}, {"msg": "three"}])
    record("append-only")
    store.append_log("info", "four")
    record("append-log")
    store.add_processed({"id": 3, "meta": {"items": [4]}})
    record("add-processed")
    store.add_error({"id": "e2", "meta": {"items": [5]}})
    record("add-error")
    modified = copy.deepcopy(invoices)
    modified[0]["meta"]["items"].append(9)
    store.update(processed_invoices=modified)
    record("in-place-mutation")
    store.update(
        statistics={"emails": 5, "invoices": 2, "errors": 1},
        quota_exhausted=True,
        quota_message="quota",
    )
    record("stats-quota")
    store.update(status_text="half")  # unchanged no-op
    record("no-op")
    store.terminalize(
        "failed",
        status_text="处理失败",
        last_error="failed",
        reason_code="PROCESSING_FAILED",
        logs=[{"msg": "terminal"}],
        statistics={"emails": 9},
    )
    record("terminalize")
    store.update(progress=1, status_text="late")
    store.append_log("late", "ignored")
    store.add_processed({"id": 9})
    record("after-terminal")
    return steps


def test_run_state_store_is_semantically_equivalent_to_legacy_oracle():
    optimized = RunStateStore()
    oracle = _LegacyRunStateStore()

    optimized_steps = _drive_store(optimized)
    oracle_steps = _drive_store(oracle)

    assert len(optimized_steps) == len(oracle_steps)
    for (opt_label, opt_state, opt_frontend, opt_reason), (
        ref_label,
        ref_state,
        ref_frontend,
        ref_reason,
    ) in zip(optimized_steps, oracle_steps):
        assert opt_label == ref_label
        assert opt_state == ref_state, f"state diverged after {opt_label}"
        assert opt_frontend == ref_frontend, f"frontend snapshot diverged after {opt_label}"
        assert opt_reason == ref_reason


def test_run_state_store_snapshots_are_isolated_and_frontend_shape_matches():
    store = RunStateStore()
    store.reset("run-2")
    invoices = [{"id": 1, "meta": {"items": [1]}}]
    logs = [{"msg": "one"}]
    store.update(processed_invoices=invoices, error_invoices=[{"id": "e"}], logs=logs)

    # Mutating the caller's inputs after update must not reach the store.
    invoices[0]["meta"]["items"].append(2)
    invoices.append({"id": 2})
    logs[0]["msg"] = "mutated"
    snapshot = store.snapshot()
    assert snapshot["processed_invoices"] == [{"id": 1, "meta": {"items": [1]}}]
    assert snapshot["logs"] == [{"msg": "one"}]

    # Mutating a returned snapshot must not reach the store either.
    snapshot["processed_invoices"][0]["meta"]["items"].append(99)
    snapshot["stats"]["emails"] = 123
    assert store.snapshot()["processed_invoices"] == [{"id": 1, "meta": {"items": [1]}}]
    assert store.snapshot()["stats"]["emails"] == 0

    frontend = store.frontend_snapshot(build_identity={"b": 1})
    assert set(frontend) == {
        "progress",
        "status_text",
        "logs",
        "new_categories",
        "stats",
        "is_running",
        "run_state",
        "last_error",
        "stop_requested",
        "can_stop",
        "quota_exhausted",
        "quota_message",
        "build_identity",
        "raw_date_range",
        "imap_query_range",
    }
    assert "processed_invoices" not in frontend and "error_invoices" not in frontend
    frontend["logs"][0]["msg"] = "mutated"
    assert store.snapshot()["logs"][0]["msg"] == "one"


def test_unchanged_update_copies_nothing_and_notifies_nobody(monkeypatch):
    sink_calls = []

    def state_sink(snapshot):
        sink_calls.append(snapshot)

    store = RunStateStore(state_sink=state_sink)
    store.reset("run-3")
    invoices = [{"id": index, "meta": {"tags": ["a"]}} for index in range(50)]
    store.update(
        progress=30,
        status_text="text",
        run_state="running",
        statistics={"emails": 3},
        processed_invoices=invoices,
        error_invoices=[],
        categories=["A"],
        logs=[{"msg": "x"}],
    )
    current = store.snapshot()
    calls_after_warmup = len(sink_calls)

    real_deepcopy = copy.deepcopy
    deepcopy_calls = {"count": 0}

    def counting_deepcopy(value, *args, **kwargs):
        deepcopy_calls["count"] += 1
        return real_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr(run_state_store.copy, "deepcopy", counting_deepcopy)

    # Identical poll values (what the 1 s get_progress sync does when nothing moved).
    store.update(
        progress=current["progress"],
        status_text=current["status_text"],
        run_state=current["run_state"],
        last_error=current["last_error"],
        stop_requested=current["stop_requested"],
        quota_exhausted=current["quota_exhausted"],
        quota_message=current["quota_message"],
        statistics=current["stats"],
        processed_invoices=current["processed_invoices"],
        error_invoices=current["error_invoices"],
        categories=current["new_categories"],
        logs=current["logs"],
    )

    assert deepcopy_calls["count"] == 0
    assert len(sink_calls) == calls_after_warmup


def _poll_cycle_seconds(store, view, iterations=15):
    for _ in range(2):  # warm up
        view.sync(store)
    started = time.perf_counter()
    for _ in range(iterations):
        view.sync(store)
    return time.perf_counter() - started, iterations


class _LegacyView:
    """Stand-in for app_api's legacy attributes + state_sink round-trip."""

    def __init__(self):
        self.processed_invoices = []
        self.error_invoices = []
        self.logs = []
        self.stats = {}
        self.categories = set()
        self.progress = 0
        self.status_text = ""
        self.run_state = "idle"
        self.last_error = ""
        self.stop_requested = False
        self.quota_exhausted = False
        self.quota_message = ""

    def apply(self, snapshot):
        self.progress = int(snapshot.get("progress", 0) or 0)
        self.status_text = str(snapshot.get("status_text", ""))
        self.logs = copy.deepcopy(list(snapshot.get("logs", [])))
        self.categories = set(snapshot.get("new_categories", []))
        self.stats = copy.deepcopy(dict(snapshot.get("stats", {})))
        self.processed_invoices = copy.deepcopy(list(snapshot.get("processed_invoices", [])))
        self.error_invoices = copy.deepcopy(list(snapshot.get("error_invoices", [])))
        self.run_state = str(snapshot.get("run_state", "idle"))
        self.last_error = str(snapshot.get("last_error", ""))
        self.stop_requested = bool(snapshot.get("stop_requested", False))
        self.quota_exhausted = bool(snapshot.get("quota_exhausted", False))
        self.quota_message = str(snapshot.get("quota_message", ""))

    def sync(self, store):
        store.update(
            progress=self.progress,
            status_text=self.status_text,
            run_state=self.run_state,
            last_error=self.last_error,
            stop_requested=self.stop_requested,
            quota_exhausted=self.quota_exhausted,
            quota_message=self.quota_message,
            statistics=self.stats,
            processed_invoices=self.processed_invoices,
            error_invoices=self.error_invoices,
            categories=self.categories,
            logs=self.logs,
        )


def _populate_for_benchmark(store, view, invoice_count=1000):
    invoices = [
        {
            "id": index,
            "document_id": f"doc-{index}",
            "date": "2026-06-01",
            "amount": "¥ 100.00",
            "category": "餐饮",
            "merchant": f"seller-{index}",
            "path": f"C:/invoices/{index}.pdf",
            "meta": {"tags": ["a", "b"], "nested": {"list": [index]}},
        }
        for index in range(invoice_count)
    ]
    logs = [{"msg": f"log-{index}"} for index in range(200)]
    store.reset("bench")
    store.update(
        progress=50,
        status_text="running",
        run_state="running",
        statistics={"emails": invoice_count, "invoices": invoice_count, "errors": 0},
        processed_invoices=invoices,
        error_invoices=[],
        categories=["餐饮", "住宿"],
        logs=logs,
    )
    view.sync(store)  # let the round-trip settle once


def test_run_state_poll_cycle_with_1000_invoices_beats_legacy_copying():
    optimized_view = _LegacyView()
    optimized = RunStateStore(state_sink=optimized_view.apply)
    _populate_for_benchmark(optimized, optimized_view)

    legacy_view = _LegacyView()
    legacy = _LegacyRunnerForBenchmark(state_sink=legacy_view.apply)
    _populate_for_benchmark(legacy, legacy_view)

    optimized_seconds, iterations = _poll_cycle_seconds(optimized, optimized_view)
    legacy_seconds, _ = _poll_cycle_seconds(legacy, legacy_view)

    per_poll_ms = optimized_seconds / iterations * 1000
    legacy_per_poll_ms = legacy_seconds / iterations * 1000
    print(
        f"\n[run-state poll benchmark] 1000 invoices x {iterations} idle polls: "
        f"optimized={per_poll_ms:.3f} ms/poll, legacy={legacy_per_poll_ms:.3f} ms/poll "
        f"(speed-up x{legacy_seconds / max(optimized_seconds, 1e-9):.1f})"
    )
    # The optimized store does comparison-only work on unchanged polls; allow a
    # wide margin so the assertion stays stable on loaded CI machines.
    assert optimized_seconds < legacy_seconds / 3
    assert per_poll_ms < 5.0


class _LegacyRunnerForBenchmark(_LegacyRunStateStore):
    """Legacy oracle that accepts the optimized store's ``state_sink`` kwarg."""

    def __init__(self, state_sink=None):
        super().__init__(state_sink=state_sink)

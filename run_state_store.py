from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable, Mapping


_TERMINAL_STATES = {"completed", "failed"}


def _bounded_progress(value: Any) -> int:
    return max(0, min(100, int(value)))


class RunStateStore:
    """Thread-safe owner of the frontend-visible state for one active run.

    Polling contract: the desktop frontend calls ``get_progress`` (every 1 s) and
    ``get_results`` (every 3 s); both funnel the legacy app attributes back
    through :meth:`update` before reading. The previous implementation deep-copied
    the whole state (including every processed/error invoice) on every call, which
    is O(n) per poll and therefore O(n^2) over a run.

    The store now keeps a single private state dict and applies copy-on-write:
    a field is deep-copied only when its content actually changed. Appending to a
    list only copies the new tail. Unchanged polls are comparison-only no-ops.
    Everything handed to callers is still a fully independent deep copy, so the
    public semantics (snapshot isolation, monotonic progress, terminal lock-out)
    are unchanged.
    """

    def __init__(
        self,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
        state_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self._lock = threading.RLock()
        self._event_sink = event_sink
        self._state_sink = state_sink
        self._terminal = False
        self._terminal_reason = ""
        self._state = self._initial_state("")

    @staticmethod
    def _initial_state(run_id: str) -> dict[str, Any]:
        return {
            "run_id": str(run_id or ""),
            "progress": 0,
            "status_text": "等待任务开始...",
            "logs": [],
            "new_categories": [],
            "stats": {"emails": 0, "invoices": 0, "errors": 0},
            "processed_invoices": [],
            "error_invoices": [],
            "is_running": False,
            "run_state": "idle",
            "last_error": "",
            "stop_requested": False,
            "can_stop": False,
            "quota_exhausted": False,
            "quota_message": "",
        }

    # ------------------------------------------------------------------ sinks
    def _notify_locked(self) -> dict[str, Any] | None:
        """Build at most one private snapshot and feed the state sink.

        Must be called with ``self._lock`` held. Returns the snapshot to hand to
        the event sink *after* the lock is released, or ``None`` when no sink is
        registered (in which case no copy is performed at all). Each callback
        still receives an independent copy it may mutate freely.
        """

        if self._event_sink is None and self._state_sink is None:
            return None
        snapshot = copy.deepcopy(self._state)
        state_sink = self._state_sink
        if state_sink is not None:
            # If an event sink also needs this snapshot, isolate them from each
            # other; otherwise the snapshot is private to the state sink.
            payload = snapshot if self._event_sink is None else copy.deepcopy(snapshot)
            try:
                state_sink(payload)
            except Exception:
                pass
        return snapshot

    def _emit(self, snapshot: dict[str, Any] | None) -> None:
        callback = self._event_sink
        if callback is None or snapshot is None:
            return
        try:
            callback(snapshot)
        except Exception:
            return

    # -------------------------------------------------------------- primitives
    def _replace_sequence(self, field: str, incoming: list[Any]) -> bool:
        """Copy only the changed part of a list field; return True if changed."""

        current = self._state[field]
        if incoming is current:
            return False
        if len(incoming) == len(current) and incoming == current:
            return False
        if len(incoming) > len(current) and incoming[: len(current)] == current:
            # Append-only update: keep the store's private copies of the prefix
            # and deep-copy just the new tail.
            tail = [copy.deepcopy(item) for item in incoming[len(current) :]]
            self._state[field] = current + tail
            return True
        self._state[field] = copy.deepcopy(list(incoming))
        return True

    def _refresh_text(self, field: str, value: Any) -> bool:
        text = str(value)
        if text == self._state[field]:
            return False
        self._state[field] = text
        return True

    def _refresh_bool(self, field: str, value: Any) -> bool:
        normalized = bool(value)
        if normalized == self._state[field]:
            return False
        self._state[field] = normalized
        return True

    # ------------------------------------------------------------------- state
    @property
    def terminal_reason(self) -> str:
        with self._lock:
            return self._terminal_reason

    def reset(
        self,
        run_id: str,
        *,
        status_text: str = "等待任务开始...",
        run_state: str = "idle",
        progress: int = 0,
    ) -> None:
        with self._lock:
            self._state = self._initial_state(run_id)
            self._state["status_text"] = str(status_text)
            self._state["run_state"] = str(run_state)
            self._state["progress"] = _bounded_progress(progress)
            self._state["is_running"] = self._state["run_state"] in {"running", "finalizing"}
            self._state["can_stop"] = self._state["run_state"] == "running"
            self._terminal = False
            self._terminal_reason = ""
            snapshot = self._notify_locked()
        self._emit(snapshot)

    def update(
        self,
        *,
        progress: int | None = None,
        status_text: str | None = None,
        run_state: str | None = None,
        last_error: str | None = None,
        stop_requested: bool | None = None,
        quota_exhausted: bool | None = None,
        quota_message: str | None = None,
        statistics: Mapping[str, Any] | None = None,
        processed_invoices: list[Mapping[str, Any]] | None = None,
        error_invoices: list[Mapping[str, Any]] | None = None,
        categories: list[str] | set[str] | tuple[str, ...] | None = None,
        logs: list[Mapping[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            if self._terminal:
                return
            state = self._state
            changed = False
            if progress is not None:
                bounded = _bounded_progress(progress)
                if bounded > int(state["progress"]):
                    state["progress"] = bounded
                    changed = True
            if status_text is not None:
                changed = self._refresh_text("status_text", status_text) or changed
            if run_state is not None:
                normalized = str(run_state)
                if normalized != state["run_state"]:
                    state["run_state"] = normalized
                    changed = True
                expected_is_running = normalized in {"running", "finalizing"}
                if expected_is_running != state["is_running"]:
                    state["is_running"] = expected_is_running
                    changed = True
            if last_error is not None:
                changed = self._refresh_text("last_error", last_error) or changed
            if stop_requested is not None:
                changed = self._refresh_bool("stop_requested", stop_requested) or changed
            if quota_exhausted is not None:
                changed = self._refresh_bool("quota_exhausted", quota_exhausted) or changed
            if quota_message is not None:
                changed = self._refresh_text("quota_message", quota_message) or changed
            if statistics is not None:
                incoming_stats = dict(statistics)
                if incoming_stats != state["stats"]:
                    state["stats"] = copy.deepcopy(incoming_stats)
                    changed = True
            if processed_invoices is not None:
                incoming = (
                    processed_invoices
                    if isinstance(processed_invoices, list)
                    else list(processed_invoices)
                )
                changed = self._replace_sequence("processed_invoices", incoming) or changed
            if error_invoices is not None:
                incoming = (
                    error_invoices
                    if isinstance(error_invoices, list)
                    else list(error_invoices)
                )
                changed = self._replace_sequence("error_invoices", incoming) or changed
            if categories is not None:
                normalized_categories = sorted({str(item) for item in categories})
                if normalized_categories != state["new_categories"]:
                    state["new_categories"] = normalized_categories
                    changed = True
            if logs is not None:
                incoming = logs if isinstance(logs, list) else list(logs)
                changed = self._replace_sequence("logs", incoming) or changed
            if not changed:
                # Nothing new: skip both the snapshot copies and the sink calls.
                return
            expected_can_stop = bool(
                state["run_state"] == "running"
                and state["is_running"]
                and not state["stop_requested"]
            )
            if expected_can_stop != state["can_stop"]:
                state["can_stop"] = expected_can_stop
            snapshot = self._notify_locked()
        self._emit(snapshot)

    def append_log(self, level: str, message: str, color: str = "text-slate-700") -> None:
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
            snapshot = self._notify_locked()
        self._emit(snapshot)

    def add_processed(self, item: Mapping[str, Any]) -> None:
        with self._lock:
            if self._terminal:
                return
            self._state["processed_invoices"].append(copy.deepcopy(dict(item)))
            snapshot = self._notify_locked()
        self._emit(snapshot)

    def add_error(self, item: Mapping[str, Any]) -> None:
        with self._lock:
            if self._terminal:
                return
            self._state["error_invoices"].append(copy.deepcopy(dict(item)))
            snapshot = self._notify_locked()
        self._emit(snapshot)

    def terminal(self, state: str, *, status_text: str, last_error: str = "") -> None:
        self.terminalize(
            state,
            status_text=status_text,
            last_error=last_error,
            reason_code="",
        )

    def terminalize(
        self,
        state: str,
        *,
        status_text: str,
        last_error: str = "",
        reason_code: str = "",
        logs: list[Mapping[str, Any]] | None = None,
        statistics: Mapping[str, Any] | None = None,
    ) -> None:
        normalized = str(state)
        if normalized not in _TERMINAL_STATES:
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
            snapshot = self._notify_locked()
        self._emit(snapshot)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def header(self) -> dict[str, Any]:
        """Small projection for incremental result polling (no invoice lists)."""
        with self._lock:
            return {
                "run_id": str(self._state["run_id"]),
                "new_categories": list(self._state["new_categories"]),
                "run_state": str(self._state["run_state"]),
                "is_running": bool(self._state["is_running"]),
            }

    def sequence_counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "processed_invoices": len(self._state["processed_invoices"]),
                "error_invoices": len(self._state["error_invoices"]),
            }

    def slice(self, field: str, start: int) -> list[Any]:
        """Return (and copy) only ``state[field][start:]`` under the lock."""
        if field not in {"processed_invoices", "error_invoices"}:
            raise ValueError(f"unsupported slice field: {field}")
        with self._lock:
            try:
                offset = max(0, int(start))
            except (TypeError, ValueError):
                offset = 0
            return copy.deepcopy(list(self._state[field][offset:]))

    def frontend_snapshot(
        self,
        *,
        build_identity: Mapping[str, Any] | None = None,
        raw_date_range: str = "",
        imap_query_range: str = "",
    ) -> dict[str, Any]:
        # Read directly under the lock and copy only the fields the frontend
        # actually receives: the invoice lists are excluded entirely and only
        # the last 20 log entries are copied. This removes the full-state deep
        # copy that used to run on every 1 s progress poll.
        with self._lock:
            state = self._state
            snapshot = {
                "progress": state["progress"],
                "status_text": state["status_text"],
                "logs": copy.deepcopy(state["logs"][-20:]),
                "new_categories": list(state["new_categories"]),
                "stats": copy.deepcopy(state["stats"]),
                "is_running": state["is_running"],
                "run_state": state["run_state"],
                "last_error": state["last_error"],
                "stop_requested": state["stop_requested"],
                "can_stop": state["can_stop"],
                "quota_exhausted": state["quota_exhausted"],
                "quota_message": state["quota_message"],
            }
        snapshot["build_identity"] = copy.deepcopy(dict(build_identity or {}))
        snapshot["raw_date_range"] = str(raw_date_range or "")
        snapshot["imap_query_range"] = str(imap_query_range or "")
        return snapshot

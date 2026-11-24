"""Packaged diagnostics, trace-store and URL evidence helpers."""

from __future__ import annotations

import json
import os
import threading
import time

from run_lifecycle import RunState
from url_trace_sanitizer import (
    sanitize_persistence_payload,
    stable_hash,
)
from user_settings import (
    get_packaged_diagnostics_dir,
)


class DiagnosticsMixin:
    def _diag_append_jsonl(self, path, payload):
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with self._diag_lock:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(payload, ensure_ascii=False, default=str))
                    fh.write("\n")
        except Exception as exc:
            print(f"[diag] append jsonl failed: {path}: {exc}")

    def _diag_write_json(self, path, payload):
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temp_path = f"{path}.tmp"
            with self._diag_lock:
                with open(temp_path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
                os.replace(temp_path, path)
        except Exception as exc:
            print(f"[diag] write json failed: {path}: {exc}")

    def _packaged_diag_dir(self):
        if not self._packaged_diag_enabled:
            return ""
        try:
            return get_packaged_diagnostics_dir()
        except Exception:
            return ""

    def _packaged_diag_file(self):
        diag_dir = self._packaged_diag_dir()
        if not diag_dir:
            return ""
        return os.path.join(diag_dir, "packaged_5p_diag.jsonl")

    def _packaged_diag_email_domain(self, email_address):
        email_text = str(email_address or "").strip()
        if "@" not in email_text:
            return ""
        return email_text.split("@", 1)[1].lower()

    def _sensitive_summary(self, email_address="", auth_code="", api_key=""):
        return {
            "email_domain": self._packaged_diag_email_domain(email_address),
            "has_auth_code": bool(auth_code),
            "has_api_key": bool(api_key),
        }

    def _packaged_diag_summary(self, summary):
        if not isinstance(summary, dict):
            return {}

        allowed_keys = {
            "requested_save_path",
            "effective_save_path",
            "date_from",
            "date_to",
            "email_domain",
            "has_auth_code",
            "has_api_key",
            "email_count",
            "attachment_count",
            "file_name",
            "thread_is_alive",
            "target_progress",
            "attachments",
            "poll_index",
            "logs_count",
            "include_traceback",
            "thread_target",
            "thread_target_ident",
            "connect_result",
            "scan_result_count",
            "extract_result_count",
            "url_result_count",
        }
        allowed = {key: value for key, value in summary.items() if key in allowed_keys}
        return sanitize_persistence_payload(allowed)

    def _packaged_diag_write(self, stage, function_name, outcome, summary=None, exc=None):
        if not self._packaged_diag_enabled:
            return

        exc_type = ""
        exc_message_hash = ""
        if exc is not None:
            exc_type = getattr(getattr(exc, "__class__", None), "__name__", "") or type(exc).__name__
            exc_message_hash = stable_hash(str(exc))

        self._diag_append_jsonl(
            self._packaged_diag_file(),
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "stage": stage,
                "function": function_name,
                "outcome": outcome,
                "thread_name": threading.current_thread().name,
                "thread_ident": threading.current_thread().ident,
                "pid": os.getpid(),
                "run_state": self.run_state,
                "progress": self.progress,
                "status_hash": stable_hash(self.status_text),
                "summary": self._packaged_diag_summary(summary),
                "exc_type": exc_type,
                "exc_message_hash": exc_message_hash,
            },
        )

    def _packaged_diag_reset(self, summary=None):
        if not self._packaged_diag_enabled:
            return

        diag_file = self._packaged_diag_file()
        if not diag_file:
            return

        try:
            os.makedirs(os.path.dirname(diag_file), exist_ok=True)
            with self._diag_lock:
                with open(diag_file, "w", encoding="utf-8"):
                    pass
        except Exception as exc:
            print(f"[diag] reset packaged jsonl failed: {diag_file}: {exc}")
            return

        self._packaged_diag_poll_count = 0
        self._packaged_diag_last_progress_signature = None
        self._packaged_diag_write("session_start", "start_processing", "success", summary=summary)

    def _install_packaged_thread_excepthook(self):
        if not self._packaged_diag_enabled or self._packaged_diag_excepthook_installed:
            return

        previous_hook = getattr(threading, "excepthook", None)

        def _hook(args):
            try:
                thread_obj = getattr(args, "thread", None)
                self._packaged_diag_write(
                    "thread_unhandled_exception",
                    "threading.excepthook",
                    "exception",
                    summary={
                        "thread_target": getattr(thread_obj, "name", ""),
                        "thread_target_ident": getattr(thread_obj, "ident", None),
                    },
                    exc=getattr(args, "exc_value", None),
                )
            except Exception:
                pass

            if previous_hook:
                previous_hook(args)

        threading.excepthook = _hook
        self._packaged_diag_excepthook_installed = True

    def _packaged_diag_log_progress_poll(self, payload):
        if not self._packaged_diag_enabled:
            return

        self._packaged_diag_poll_count += 1
        signature = (
            payload.get("progress"),
            payload.get("run_state"),
            payload.get("status_text"),
            payload.get("last_error"),
        )
        should_log = self._packaged_diag_poll_count <= 20 or signature != self._packaged_diag_last_progress_signature
        self._packaged_diag_last_progress_signature = signature
        if not should_log:
            return

        self._packaged_diag_write(
            "progress_poll",
            "get_progress",
            "success",
            summary={
                "poll_index": self._packaged_diag_poll_count,
                "logs_count": len(payload.get("logs", []) or []),
            },
        )

    def _safe_emit_run_state_event(self, from_state, to_state):
        if not self._run_context.get("enabled"):
            return
        self._diag_append_jsonl(
            self._monitoring_path("run_state_events.jsonl"),
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "from_state": from_state,
                "to_state": to_state,
                "progress": self.progress,
                "status_text": self.status_text,
                "last_error": self.last_error,
                **self._snapshot_counts(),
            },
        )

    def _safe_emit_stage_event(self, stage, event, extra=None):
        if not self._run_context.get("enabled"):
            return
        payload = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stage": stage,
            "event": event,
            "run_state": self.run_state,
            "progress": self.progress,
            "status_hash": stable_hash(self.status_text),
            **self._snapshot_counts(),
        }
        if extra:
            safe_extra = sanitize_persistence_payload(dict(extra))
            handle = self._active_run_handle
            if (
                handle is not None
                and handle.state is RunState.FAILED
                and safe_extra.get("result") in {"completed", "stopped", "stopped_before_extract", "stopped_after_extract"}
            ):
                safe_extra["result"] = "failed"
                safe_extra["reason"] = handle.error
            payload.update(safe_extra)
        self._diag_append_jsonl(self._monitoring_path("stage_events.jsonl"), payload)

    def _safe_emit_artifact_event(self, kind, path, document_id=None, source_kind=None, reason_code=None, category=None, extra=None):
        if not self._run_context.get("enabled"):
            return
        if source_kind == "url":
            payload = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "artifact_id": stable_hash(
                    {"kind": kind, "path": path, "document_id": document_id}
                ),
                "path_hash": stable_hash(path),
                **self._snapshot_counts(),
            }
            payload.update(
                sanitize_persistence_payload(
                    {
                        "kind": kind,
                        "source_kind": source_kind,
                        "reason_code": reason_code,
                        "category": category,
                    }
                )
            )
            if document_id:
                payload["document_hash"] = stable_hash(document_id)
            if extra:
                safe_extra = sanitize_persistence_payload(dict(extra))
                payload.update(
                    {
                        key: value
                        for key, value in safe_extra.items()
                        if key in {
                            "status",
                            "type",
                            "category",
                            "provider",
                            "provider_family",
                            "reason_code",
                        }
                        or key.endswith(("_count", "_ms", "_seconds"))
                    }
                )
            self._diag_append_jsonl(
                self._monitoring_path("artifact_events.jsonl"), payload
            )
            return
        payload = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind,
            "path": path,
            "document_id": document_id,
            "source_kind": source_kind,
            "reason_code": reason_code,
            "category": category,
            **self._snapshot_counts(),
        }
        if extra:
            payload.update(extra)
        self._diag_append_jsonl(self._monitoring_path("artifact_events.jsonl"), payload)

    def _safe_emit_input_inventory_event(self, payload):
        if not self._run_context.get("enabled"):
            return
        self._diag_append_jsonl(
            self._monitoring_path("input_attachment_inventory.jsonl"),
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                **payload,
            },
        )

    def _attachment_diag_metadata(self, info, file_name=None, document_id=None, extra=None):
        payload = {
            "document_id": document_id,
            "email_id": info.get("email_id"),
            "sender": info.get("sender"),
            "subject": info.get("subject", ""),
            "file_name": file_name or info.get("file_name") or os.path.basename(str(info.get("filepath", ""))),
            "original_filename": info.get("original_filename"),
            "attachment_ext": info.get("attachment_ext"),
            "payload_size": info.get("payload_size"),
            "mime_content_type": info.get("mime_content_type"),
            "content_disposition": info.get("content_disposition"),
            "attachment_pair_key": info.get("attachment_pair_key"),
            "sibling_pdf_present": info.get("sibling_pdf_present"),
            "sibling_ofd_present": info.get("sibling_ofd_present"),
            "sibling_xml_present": info.get("sibling_xml_present"),
            "provider_unzipped_pair_suspected": info.get("provider_unzipped_pair_suspected"),
            "zip_context": info.get("zip_context"),
            "candidate_bucket": info.get("candidate_bucket"),
            "candidate_action": info.get("candidate_action"),
            "candidate_index": info.get("candidate_index"),
            "source_kind": info.get("source_kind"),
            "prefilter_reason_code": info.get("prefilter_reason_code"),
            "prefilter_signals": info.get("prefilter_signals", {}),
            "source_url": info.get("source_url"),
            "resolved_url": info.get("resolved_url"),
            "anchor_text": info.get("anchor_text"),
            "url_host": info.get("url_host"),
            "url_path": info.get("url_path"),
            "provider_family": info.get("provider_family"),
            "provider_expected_fields": info.get("provider_expected_fields"),
            "provider_group_key": info.get("provider_group_key"),
            "provider_candidate_urls": info.get("provider_candidate_urls"),
            "provider_recovered_fields": info.get("provider_recovered_fields"),
            "provider_recovery_status": info.get("provider_recovery_status"),
            "download_mode": info.get("download_mode"),
            "wrapper_detected": info.get("wrapper_detected"),
        }
        if extra:
            payload.update(extra)
        return self._sanitize_url_persistence_payload(payload)

    @staticmethod
    def _sanitize_url_persistence_payload(payload):
        return sanitize_persistence_payload(dict(payload or {}))

    def _is_controlled_truth_run(self):
        if not self._run_context.get("enabled"):
            return False

        run_id = str(self._run_context.get("run_id", "") or "").lower()
        if any(token in run_id for token in ("lockcheck", "regression", "frontend_full_run", "manual_frontend_run")):
            return True

        return bool(self._run_context.get("monitoring_dir"))

    def _build_email_level_url_evidence_key(self, info):
        if not info or not info.get("is_url", False):
            return ""

        provider_family = str(info.get("provider_family") or "").strip().lower()
        if provider_family:
            return ""

        email_id = str(info.get("email_id") or "").strip()
        subject = str(info.get("subject") or "").strip().lower()
        sender = str(info.get("sender") or "").strip().lower()
        host = str(info.get("url_host") or "").strip().lower()

        if email_id:
            return f"email:{email_id}"
        if subject or sender:
            return f"fallback:{sender}|{subject}"
        if host:
            return f"host:{host}"
        return ""

    def _should_capture_email_level_url_evidence(self, info):
        aggregation_key = self._build_email_level_url_evidence_key(info)
        if not aggregation_key:
            return True, ""
        if aggregation_key in self._email_level_url_evidence_seen:
            return False, aggregation_key
        self._email_level_url_evidence_seen.add(aggregation_key)
        return True, aggregation_key


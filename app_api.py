import copy
import importlib
import json
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from brand_generated import THREAD_NAME_TRUTH_AUDIT
from app_services.admission import AdmissionMixin
from app_services.diagnostics import DiagnosticsMixin
from app_services.errors import (
    ImapCertificateError,
    ImapTimeoutError,
    ProcessingLoopFailure,
    QuotaExceededError,
    RemoteAuthError,
    TruthAuditEvidenceError,
    TruthAuditTimeout,
)
from app_services.exports import write_result_detail_workbook
from app_services.settings_rules import SettingsRulesMixin
from build_identity import load_build_identity
from company_rules import DEFAULT_COMPANY
from document_types import (
    MANUAL_REVIEW_FOLDER,
    classify_cwt_document_type as _classify_cwt_document_type,
    normalize_document_type_for_archive as _normalize_document_type_for_archive,
)
from email_channel import resolve_channel
from frontend_run_context import ensure_run_context_dirs, load_run_context, make_run_staging_dir, serialize_run_context
from glm_runtime import DEEPSEEK_PROVIDER, GlmRequestError, GlmRuntime, normalize_provider
from run_coordinator import RunCoordinator
from run_lifecycle import RunLifecycle, RunState
from run_state_store import RunStateStore
from provider_direct_invoice import DIRECT_INVOICE_FAMILIES
from url_trace_sanitizer import (
    build_url_evidence,
    sanitize_url_trace_record,
    stable_hash,
)
from user_settings import (
    DEFAULT_GLM_MODEL_CANDIDATES,
    DEFAULT_GLM_PROFILE_LIMITS,
    UserSettingsStore,
    ensure_directory,
    get_default_save_path as resolve_default_save_path,
    get_default_debug_trace_path,
    get_output_state_dir,
)


DEFAULT_TRUTH_AUDIT_FINALIZE_TIMEOUT_SECONDS = 120.0
PROVIDER_URL_RETRY_REASON_CODES = frozenset(
    {
        "URL_DOWNLOAD_FAILED",
        "URL_PAGE_TIMEOUT",
        "URL_RECOVERY_DEADLINE_EXCEEDED",
        "URL_RECOVERY_WORKER_FAILED",
    }
)


@dataclass(frozen=True)
class TruthAuditPaths:
    run_root: Path
    monitoring_dir: Path
    artifact_dir: Path
    report_path: Path
    error_path: Path
    index_path: Path
    run_config_path: Path


@dataclass(frozen=True)
class TruthAuditJob:
    run_id: str
    paths: TruthAuditPaths
    thread: threading.Thread
    ready: threading.Event
    abandoned: threading.Event
    result: dict


class _ProcessingPipelineSession:
    def __init__(
        self,
        *,
        api,
        candidates,
        pipeline,
        archive_service,
        save_path,
        output_state_dir,
        working_history,
        business_records,
        sidecar,
        trace_store,
        owned_extractor=None,
        provider_retry_delay_seconds=0.0,
        url_recovery_scheduler=None,
        dry_run=False,
    ):
        self._api = api
        self.candidates = candidates
        self._pipeline = pipeline
        self._archive_service = archive_service
        self._dry_run = bool(dry_run)
        self._save_path = save_path
        self._output_state_dir = output_state_dir
        self._working_history = working_history
        self._business_records = business_records
        self._sidecar = sidecar
        self._trace_store = trace_store
        self._owned_extractor = owned_extractor
        self._provider_retry_delay_seconds = max(
            0.0, float(provider_retry_delay_seconds)
        )
        if url_recovery_scheduler is None:
            from deferred_url_recovery import (
                DEFAULT_URL_RECOVERY_MAX_WORKERS,
                DeferredUrlRecoveryScheduler,
            )

            url_recovery_scheduler = DeferredUrlRecoveryScheduler(
                max_workers=DEFAULT_URL_RECOVERY_MAX_WORKERS,
                stop_requested=lambda: bool(
                    getattr(self._api, "_stop_requested", False)
                ),
            )
        self._url_recovery_scheduler = url_recovery_scheduler
        self._provider_url_candidates = []
        self._candidate_total = len(candidates)
        self._closed = False

    def extract(self):
        candidates = list(self.candidates)
        primary = [
            candidate
            for candidate in candidates
            if candidate.identity.source_kind != "url"
        ]
        self._provider_url_candidates = [
            candidate
            for candidate in candidates
            if candidate.identity.source_kind == "url"
        ]
        return self._pipeline.extract(primary, progress_total=self._candidate_total)

    def _record_deferred_outcomes(self, outcomes):
        for outcome in outcomes:
            event = {
                "document_id": outcome.candidate.identity.document_id,
                "sequence": outcome.candidate.sequence,
                "status": outcome.status,
                "reason_code": outcome.reason_code,
            }
            self._trace_store.set_fields(
                event["document_id"], extraction_result=dict(event)
            )
            self._api._safe_emit_stage_event(
                "extraction_pipeline", "trace", dict(event)
            )

    def _recover_deferred_candidate(self, candidate):
        resolver = getattr(self._pipeline, "resolve_one", None)
        if callable(resolver):
            return resolver(candidate)
        outcomes = self._pipeline.extract([candidate], _emit_progress_events=False)
        if len(outcomes) != 1:
            raise RuntimeError("deferred recovery did not return exactly one outcome")
        return outcomes[0]

    def _retry_deferred_candidate(self, candidate):
        outcomes = self._pipeline.retry_current_run_failures([candidate])
        if len(outcomes) != 1:
            raise RuntimeError("deferred retry did not return exactly one outcome")
        return outcomes[0]

    def _canonical_info_by_document_id(self, archived_outcomes):
        document_ids = {
            archived.outcome.candidate.identity.document_id
            for archived in archived_outcomes
        }
        records = {}
        getter = getattr(self._trace_store, "get_record", None)
        if callable(getter):
            records = {
                document_id: getter(document_id) or {}
                for document_id in document_ids
            }
        else:
            iterator = getattr(self._trace_store, "iter_records", None)
            if callable(iterator):
                records = {
                    str(record.get("document_id") or ""): record
                    for record in iterator()
                    if isinstance(record, dict)
                }
        return {
            document_id: dict(record.get("normalized_fields") or {})
            for document_id, record in records.items()
            if isinstance(record, dict)
        }

    @staticmethod
    def _is_strong_provider_retry_candidate(candidate):
        legacy = candidate.to_legacy()
        return bool(
            candidate.identity.source_kind == "url"
            and legacy.get("provider_family")
        )

    def _wait_for_provider_retry(self) -> bool:
        remaining = self._provider_retry_delay_seconds
        while remaining > 0:
            if bool(getattr(self._api, "_stop_requested", False)):
                return False
            interval = min(0.25, remaining)
            time.sleep(interval)
            remaining -= interval
        return not bool(getattr(self._api, "_stop_requested", False))

    def archive(self, outcomes):
        from archive_service import ArchiveReport
        from candidate_pipeline import partition_redundant_provider_candidates

        def merge_reports(reports):
            return ArchiveReport(
                outcomes=tuple(
                    sorted(
                        (
                            archived
                            for source_report in reports
                            for archived in source_report.outcomes
                        ),
                        key=lambda archived: archived.outcome.candidate.sequence,
                    )
                ),
                archived_count=sum(item.archived_count for item in reports),
                retained_count=sum(item.retained_count for item in reports),
                manual_count=sum(item.manual_count for item in reports),
                unresolved_count=sum(item.unresolved_count for item in reports),
                duplicate_count=sum(item.duplicate_count for item in reports),
            )

        primary_outcomes = list(outcomes)
        primary_report = self._archive_service.archive(
            primary_outcomes, self._save_path, finalize=False
        )
        skipped, pending = partition_redundant_provider_candidates(
            self._provider_url_candidates,
            primary_report.outcomes,
            canonical_info_by_document_id=self._canonical_info_by_document_id(
                primary_report.outcomes
            ),
        )
        skipped_by_document_id = {
            outcome.candidate.identity.document_id: outcome for outcome in skipped
        }
        deferred_candidates = sorted(
            [
                *(outcome.candidate for outcome in skipped),
                *pending,
            ],
            key=lambda candidate: candidate.sequence,
        )

        def recover_one(candidate):
            skipped_outcome = skipped_by_document_id.get(candidate.identity.document_id)
            if skipped_outcome is not None:
                return skipped_outcome
            return self._recover_deferred_candidate(candidate)

        provider_outcomes = self._url_recovery_scheduler.recover(
            deferred_candidates,
            recover_one,
            progress_offset=len(primary_outcomes),
            progress_total=self._candidate_total,
        )
        self._record_deferred_outcomes(provider_outcomes)
        failed_provider_outcomes = [
            outcome
            for outcome in provider_outcomes
            if outcome.status == "unresolved"
        ]
        failed_document_ids = {
            outcome.candidate.identity.document_id
            for outcome in failed_provider_outcomes
        }
        archiveable_outcomes = sorted(
            [
                *(
                    outcome
                    for outcome in provider_outcomes
                    if outcome.candidate.identity.document_id
                    not in failed_document_ids
                ),
            ],
            key=lambda outcome: outcome.candidate.sequence,
        )
        reports = [primary_report]
        if archiveable_outcomes:
            reports.append(
                self._archive_service.archive(
                    archiveable_outcomes, self._save_path, finalize=False
                )
            )

        archived_evidence = tuple(
            archived
            for source_report in reports
            for archived in source_report.outcomes
        )
        recovered_failures, still_pending = partition_redundant_provider_candidates(
            [outcome.candidate for outcome in failed_provider_outcomes],
            archived_evidence,
            canonical_info_by_document_id=self._canonical_info_by_document_id(
                archived_evidence
            )
        )
        self._record_deferred_outcomes(recovered_failures)
        still_pending_ids = {
            candidate.identity.document_id for candidate in still_pending
        }
        remaining_failures = [
            outcome
            for outcome in failed_provider_outcomes
            if outcome.candidate.identity.document_id in still_pending_ids
        ]
        retryable_failures = [
            outcome
            for outcome in remaining_failures
            if outcome.reason_code in PROVIDER_URL_RETRY_REASON_CODES
            and self._is_strong_provider_retry_candidate(outcome.candidate)
        ]
        retryable_ids = {
            outcome.candidate.identity.document_id for outcome in retryable_failures
        }
        nonretryable_failures = [
            outcome
            for outcome in remaining_failures
            if outcome.candidate.identity.document_id not in retryable_ids
        ]
        retried_failures = []
        recovered_retry_failures = []
        if retryable_failures and self._wait_for_provider_retry():
            retry_outcomes = self._url_recovery_scheduler.recover(
                [outcome.candidate for outcome in retryable_failures],
                self._retry_deferred_candidate,
                emit_progress=False,
            )
            retried_failures = [
                outcome
                for outcome in retry_outcomes
                if outcome.status == "unresolved"
            ]
            retried_failure_ids = {
                outcome.candidate.identity.document_id
                for outcome in retried_failures
            }
            retried_archiveable = [
                outcome
                for outcome in retry_outcomes
                if outcome.candidate.identity.document_id not in retried_failure_ids
            ]
            if retried_archiveable:
                reports.append(
                    self._archive_service.archive(
                        retried_archiveable, self._save_path, finalize=False
                    )
                )
            archived_evidence = tuple(
                archived
                for source_report in reports
                for archived in source_report.outcomes
            )
            recovered_retry_failures, retry_still_pending = (
                partition_redundant_provider_candidates(
                    [outcome.candidate for outcome in retried_failures],
                    archived_evidence,
                    canonical_info_by_document_id=self._canonical_info_by_document_id(
                        archived_evidence
                    ),
                )
            )
            self._record_deferred_outcomes(recovered_retry_failures)
            retry_pending_ids = {
                candidate.identity.document_id for candidate in retry_still_pending
            }
            retried_failures = [
                outcome
                for outcome in retried_failures
                if outcome.candidate.identity.document_id in retry_pending_ids
            ]
        elif retryable_failures:
            retried_failures = list(retryable_failures)
        terminal_failures = sorted(
            [
                *recovered_failures,
                *nonretryable_failures,
                *recovered_retry_failures,
                *retried_failures,
            ],
            key=lambda outcome: outcome.candidate.sequence,
        )
        if terminal_failures:
            reports.append(
                self._archive_service.archive(
                    terminal_failures, self._save_path, finalize=False
                )
            )

        report = merge_reports(reports)
        report = self._archive_service.finalize(report, self._save_path)
        if self._dry_run:
            # Preview runs never move files, never persist a ledger, and never
            # leave "running/failed" markers in the user's output directory.
            report = self._normalize_preview_report(report)
            self._sync_preview_paths(report)
            sync = getattr(self._api, "_sync_run_state_store_from_legacy", None)
            if callable(sync):
                sync()
            return report
        self._sync_final_archive_paths(report)
        if not report.can_complete:
            self._api._mark_output_run_state(
                self._output_state_dir,
                "failed",
                failure_reason="processing_pipeline_incomplete",
            )
            raise ProcessingLoopFailure("PROCESSING_PIPELINE_INCOMPLETE")
        self._api._commit_output_state(
            self._output_state_dir,
            self._working_history,
            self._business_records,
        )
        return report

    def _normalize_preview_report(self, report):
        """Keep preview errors visible while letting the preview run finish.

        A preview is not an archive: manual-review and unresolved rows are
        reported in the result page, they must not turn the whole preview into a
        failed run (the user is only inspecting the plan).
        """
        from dataclasses import replace

        if report.can_complete:
            return report
        return replace(report, unresolved_count=0)

    def _sync_preview_paths(self, report):
        """Refresh planned preview paths without requiring files to exist."""
        iter_records = getattr(self._trace_store, "iter_records", None)
        planned = {
            str(row.get("document_id")): str(row.get("archive_target") or "")
            for row in (iter_records() if callable(iter_records) else ())
            if row.get("document_id") and row.get("archive_target")
        }
        for item in report.outcomes:
            path = str(item.archive_path or "")
            if path:
                planned[item.outcome.candidate.identity.document_id] = path
        for records in (
            getattr(self._api, "processed_invoices", []),
            getattr(self._api, "error_invoices", []),
        ):
            for row in list(records):
                document_id = str(row.get("document_id") or "")
                path = planned.get(document_id, "")
                if path:
                    row["path"] = path
                    if "name" in row:
                        row["name"] = os.path.basename(path)

    def _sync_final_archive_paths(self, report):
        iter_records = getattr(self._trace_store, "iter_records", None)
        final_paths = {
            str(row.get("document_id")): str(row.get("archive_target"))
            for row in (iter_records() if callable(iter_records) else ())
            if row.get("document_id") and row.get("archive_target")
        }
        for item in report.outcomes:
            path = str(item.archive_path or "")
            if path and os.path.isfile(path):
                final_paths[item.outcome.candidate.identity.document_id] = path

        processed = getattr(self._api, "processed_invoices", [])
        errors = getattr(self._api, "error_invoices", [])
        for records in (processed, errors):
            for row in list(records):
                document_id = str(row.get("document_id") or "")
                if not document_id:
                    continue
                path = final_paths.get(document_id, "")
                if path and os.path.isfile(path):
                    row["path"] = path
                    if "name" in row:
                        row["name"] = os.path.basename(path)
                elif records is processed and not os.path.isfile(row.get("path") or ""):
                    records.remove(row)
                    self._api.stats["invoices"] = max(0, self._api.stats["invoices"] - 1)
                    self._api.stats["errors"] += 1
                    errors.append({
                        **row, "status": "处理失败", "reason": "ARCHIVE_ARTIFACT_MISSING",
                    })

        adapter = getattr(getattr(self._archive_service, "_finalizer", None), "__self__", None)
        for document_id, key in getattr(adapter, "business_keys_by_document_id", {}).items():
            path = final_paths.get(document_id, "")
            record = self._business_records.get(key)
            if path and os.path.isfile(path) and isinstance(record, dict):
                record["file"] = os.path.basename(path)
        sync = getattr(self._api, "_sync_run_state_store_from_legacy", None)
        if callable(sync):
            sync()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._sidecar.clear()
        if getattr(self._api, "_pipeline_sidecar", None) is self._sidecar:
            delattr(self._api, "_pipeline_sidecar")
        try:
            self._trace_store.flush()
        except Exception:
            pass
        close_extractor = getattr(self._owned_extractor, "close", None)
        if callable(close_extractor):
            close_extractor()


def build_processing_history_key(info, file_name, pdf_path):
    from candidate_pipeline import build_compatibility_history_key

    return build_compatibility_history_key(info, file_name, pdf_path)


def build_document_trace_id(info, file_name, pdf_path):
    import hashlib

    info = info or {}
    source_locator = str(info.get("source_url") or info.get("filepath") or pdf_path or "").strip()
    if source_locator and not info.get("is_url", False):
        source_locator = os.path.normcase(os.path.abspath(source_locator))
    evidence = {
        "processing_history_key": build_processing_history_key(info, file_name, pdf_path),
        "source_message_uid": str(info.get("email_id") or info.get("source_email_id") or "").strip(),
        "source_filename": str(file_name or "").strip(),
        "source_locator": source_locator,
        "source_kind": str(info.get("source_kind") or "").strip(),
        "source_url": str(info.get("source_url") or "").strip(),
        "provider_group_key": str(info.get("provider_group_key") or "").strip(),
    }
    canonical = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_artifact_role(info_json, file_name=""):
    info_json = info_json or {}
    doc_type = str(info_json.get("Type") or "").strip().lower()
    evidence = f"{doc_type} {file_name}".lower()

    if any(token in evidence for token in ("住宿水单", "水单", "folio", "酒店账单")):
        return "hotel_folio"
    ride_evidence = any(token in evidence for token in ("打车", "滴滴", "高德", "约车", "ride"))
    itinerary_evidence = bool(info_json.get("_is_itinerary")) or any(
        token in evidence for token in ("行程单", "行程报销单", "itinerary")
    )
    if ride_evidence and itinerary_evidence:
        return "ride_itinerary"
    if ride_evidence:
        return "ride_invoice"
    if "住宿" in evidence or "hotel" in evidence:
        return "hotel_invoice"
    return "invoice"


def build_business_record_key(code, number, info_json, file_name=""):
    identity = f"{str(code or '').strip()}_{str(number or '').strip()}"
    return f"{identity}::{canonical_artifact_role(info_json, file_name)}"


def is_business_duplicate(code, number, records, info_json, file_name=""):
    if not str(code or "").strip() and not str(number or "").strip():
        return False
    records = records or {}
    role = canonical_artifact_role(info_json, file_name)
    if build_business_record_key(code, number, info_json, file_name) in records:
        return True

    legacy_key = f"{str(code or '').strip()}_{str(number or '').strip()}"
    legacy_record = records.get(legacy_key)
    if not isinstance(legacy_record, dict):
        return False
    stored_role = str(legacy_record.get("artifact_role") or "").strip()
    if not stored_role and legacy_record.get("file"):
        stored_role = canonical_artifact_role({}, legacy_record["file"])
    return stored_role == role if stored_role else role == "invoice"


def record_business_success(records, code, number, info_json, file_name, date="", amount=""):
    key = build_business_record_key(code, number, info_json, file_name)
    records[key] = {
        "file": file_name,
        "date": date or info_json.get("Date", ""),
        "amount": amount or info_json.get("Amount", ""),
        "artifact_role": canonical_artifact_role(info_json, file_name),
    }
    return key


def classify_cwt_document_type(info_json, info, file_name, local_cits_fast_path=False):
    return _classify_cwt_document_type(info_json, info, file_name, local_cits_fast_path)


def normalize_document_type_for_archive(info_json, file_name, cwt_classified=False):
    return _normalize_document_type_for_archive(info_json, file_name, cwt_classified)


class _FallbackDocumentTraceStore:
    """In-memory trace store used when the optional diagnostics module is absent."""

    def __init__(self, output_path=None):
        self.output_path = os.path.abspath(
            output_path or get_default_debug_trace_path()
        )
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        self._records = {}
        self._order = []
        self._archive_index = {}
        self._url_document_ids = set()

    def start_document(
        self,
        source_filename,
        source_path=None,
        document_id=None,
        persistence_is_url=False,
    ):
        doc_id = document_id or uuid.uuid4().hex
        if doc_id not in self._records:
            self._records[doc_id] = {
                "source_filename": source_filename,
                "document_id": doc_id,
                "extractor_raw_result": None,
                "normalized_fields": None,
                "classification_result": None,
                "naming_result": None,
                "combine_keys": None,
                "combine_result": None,
                "archive_target": None,
                "failure_reason": None,
            }
            if source_path:
                self._records[doc_id]["source_path"] = source_path
            self._order.append(doc_id)
        if persistence_is_url:
            self._url_document_ids.add(doc_id)
        return doc_id

    def get_record(self, document_id):
        return self._records.get(document_id)

    def iter_records(self):
        for document_id in self._order:
            yield self._records[document_id]

    def set_fields(self, document_id, **fields):
        record = self._records.get(document_id)
        if not record:
            return

        for key, value in fields.items():
            record[key] = copy.deepcopy(value)

        archive_target = fields.get("archive_target")
        if archive_target:
            self.bind_archive_target(document_id, archive_target)

    def bind_archive_target(self, document_id, archive_target):
        record = self._records.get(document_id)
        if not record or not archive_target:
            return

        old_target = record.get("archive_target")
        if old_target:
            self._archive_index.pop(self._normalize_path(old_target), None)

        normalized = self._normalize_path(archive_target)
        self._archive_index[normalized] = document_id
        record["archive_target"] = archive_target

    def move_archive_target(self, old_target, new_target):
        if not old_target or not new_target:
            return None

        normalized_old = self._normalize_path(old_target)
        document_id = self._archive_index.pop(normalized_old, None)
        if not document_id:
            return None

        normalized_new = self._normalize_path(new_target)
        self._archive_index[normalized_new] = document_id
        self._records[document_id]["archive_target"] = new_target
        return document_id

    def get_document_id_by_archive_target(self, archive_target):
        if not archive_target:
            return None
        return self._archive_index.get(self._normalize_path(archive_target))

    def record_failure_event(self, document_id, code, stage, message=None, severity="failure"):
        record = self._records.get(document_id)
        if not record:
            return

        event = {
            "code": code,
            "stage": stage,
            "severity": severity,
        }
        if message:
            event["message"] = message

        failure_reason = record.get("failure_reason")
        if not failure_reason:
            record["failure_reason"] = dict(event)
            record["failure_reason"]["history"] = [dict(event)]
            return

        history = failure_reason.setdefault("history", [])
        history.append(dict(event))

        if self._severity_rank(severity) >= self._severity_rank(failure_reason.get("severity")):
            failure_reason.update(event)

    def flush(self):
        temp_path = f"{self.output_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            for document_id in self._order:
                record = self._records[document_id]
                if document_id in self._url_document_ids:
                    record = sanitize_url_trace_record(record)
                json.dump(
                    record,
                    handle,
                    ensure_ascii=False,
                    default=str,
                )
                handle.write("\n")
        os.replace(temp_path, self.output_path)

    @staticmethod
    def _normalize_path(path):
        return os.path.normcase(os.path.abspath(path))

    @staticmethod
    def _severity_rank(severity):
        ranks = {
            None: 0,
            "info": 1,
            "skipped": 2,
            "fallback": 3,
            "failure": 4,
        }
        return ranks.get(severity, 0)

class InvoiceAppAPI(AdmissionMixin, SettingsRulesMixin, DiagnosticsMixin):
    def __init__(self, truth_audit_timeout_seconds=None, revision_resolver=None):
        self._run_context = load_run_context()
        if revision_resolver is None:
            from run_evidence import default_revision

            revision_resolver = default_revision
        self._revision_resolver = revision_resolver
        self._diag_lock = threading.Lock()
        self._url_retention_ledger_lock = threading.Lock()
        self._packaged_diag_enabled = bool(getattr(sys, "frozen", False))
        self._packaged_diag_poll_count = 0
        self._packaged_diag_last_progress_signature = None
        self._packaged_diag_excepthook_installed = False
        self.progress = 0
        self.status_text = "Ready to start..."
        self.logs = []
        self._legacy_sync_signature = None
        self._is_running = False
        self._stop_requested = False
        self.run_state = "idle"
        self.last_error = ""
        self.quota_exhausted = False
        self.quota_message = ""
        self._active_ai_provider = "glm"
        self._worker_thread = None
        self._active_fetcher = None
        self._imap_abort_run_id = None
        self._preserved_staging_dir = None
        self._truth_audit_thread = None
        self._truth_audit_job = None
        if truth_audit_timeout_seconds is None:
            truth_audit_timeout_seconds = DEFAULT_TRUTH_AUDIT_FINALIZE_TIMEOUT_SECONDS
        self._truth_audit_timeout_seconds = max(0.001, float(truth_audit_timeout_seconds))
        self._admission_lock = threading.RLock()
        self._settings_lock = threading.RLock()
        self._run_lifecycle = RunLifecycle()
        self._active_run_handle = None
        self._active_temp_dir = None
        self._terminal_frontend_run_id = ""
        self._settings_store = UserSettingsStore()
        self._requested_save_path = ""
        self._effective_save_path = ""
        self._effective_date_from = ""
        self._effective_date_to = ""
        self._raw_date_range_display = ""
        self._imap_query_range_display = ""
        self._current_run_id = self._run_context.get("run_id", "")
        self.audit_counts = {"manual_check": 0, "retention": 0, "raw_invoices": 0}
        self.discovered_categories = set()
        self.processed_invoices = []
        self.error_invoices = []
        self.stats = {"emails": 0, "invoices": 0, "errors": 0}
        self._email_level_url_evidence_seen = set()
        self._last_export_path = ""
        self._active_task_mode = "mail"
        self._last_fetch_summary = {}
        self._last_organize_result = None
        self._active_run_config = {}
        self._timing_metrics = {}
        self._run_state_store = RunStateStore(state_sink=self._apply_run_state_snapshot)
        self._install_packaged_thread_excepthook()
        self.build_identity = load_build_identity()
        self._validate_runtime_build_identity()
        # Release-prep candidate: startup must not trigger local developer scans.

    def _create_document_trace_store(self, output_path=None):
        try:
            trace_module = importlib.import_module("diagnostics_trace")
            trace_store_cls = getattr(trace_module, "DocumentTraceStore")
            return trace_store_cls(output_path=output_path)
        except Exception as exc:
            self._packaged_diag_write(
                "document_trace_store_fallback",
                "_run_processing_loop",
                "exception",
                summary={"include_traceback": False},
                exc=exc,
            )
            return _FallbackDocumentTraceStore(output_path=output_path)


    def _refresh_run_context(self):
        refreshed_context = load_run_context()
        if refreshed_context != self._run_context:
            self._run_context = refreshed_context
        ensure_run_context_dirs(self._run_context)
        self._current_run_id = self._run_context.get("run_id", "")
        return self._run_context

    def _prepare_run_lifecycle(self):
        active = self._active_run_handle
        if active is not None:
            raise RuntimeError("a run handle is already assigned")

        run_token = uuid.uuid4().hex
        external_run_id = str(self._current_run_id or self._run_context.get("run_id", "") or "run")
        lifecycle_run_id = f"{external_run_id}-{run_token}"
        staging_dir = make_run_staging_dir(self._run_context, lifecycle_run_id)
        handle = self._run_lifecycle.begin(lifecycle_run_id, staging_dir)
        run_root = str(self._run_context.get("run_root", "") or "").strip()
        temp_root = Path(run_root).resolve() / "temp" if run_root else Path.cwd() / "temp"
        self._active_temp_dir = temp_root / lifecycle_run_id
        self._active_run_handle = handle
        self._imap_abort_run_id = None
        self._preserved_staging_dir = None
        self._terminal_frontend_run_id = ""
        return handle

    def _apply_run_state_snapshot(self, snapshot):
        previous_state = getattr(self, "run_state", "idle")
        self.progress = int(snapshot.get("progress", 0) or 0)
        self.status_text = str(snapshot.get("status_text", ""))
        # RunStateStore hands this sink a read-only shallow view; records are
        # immutable after ingest and sequence updates publish new lists, so the
        # bridge can adopt the references without per-invoice copying.
        self.logs = snapshot.get("logs", [])
        self.discovered_categories = set(snapshot.get("new_categories", []))
        self.stats = snapshot.get("stats", {})
        self.processed_invoices = snapshot.get("processed_invoices", [])
        self.error_invoices = snapshot.get("error_invoices", [])
        self._is_running = bool(snapshot.get("is_running", False))
        self.run_state = str(snapshot.get("run_state", "idle"))
        self.last_error = str(snapshot.get("last_error", ""))
        self._stop_requested = bool(snapshot.get("stop_requested", False))
        self.quota_exhausted = bool(snapshot.get("quota_exhausted", False))
        self.quota_message = str(snapshot.get("quota_message", ""))
        if previous_state != self.run_state:
            self._safe_emit_run_state_event(previous_state, self.run_state)

    def _active_staging_path(self):
        if self._active_run_handle is not None:
            return str(self._active_run_handle.staging_dir)
        return str(self._run_context.get("staging_dir") or "staging")

    @staticmethod
    def _resolve_truth_audit_paths(context, run_id):
        context = dict(context or {})
        configured_root = str(context.get("run_root") or "").strip()
        if configured_root:
            run_root = Path(configured_root).resolve()
        else:
            configured_monitoring = str(context.get("monitoring_dir") or "").strip()
            run_root = (
                Path(configured_monitoring).resolve().parent
                if configured_monitoring
                else Path.cwd().resolve()
            )
        monitoring_dir = run_root / "monitoring"
        safe_run_id = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            str(run_id or "run"),
        ).strip("-.") or "run"
        artifact_dir = monitoring_dir / "quarantined" / safe_run_id
        return TruthAuditPaths(
            run_root=run_root,
            monitoring_dir=monitoring_dir,
            artifact_dir=artifact_dir,
            report_path=artifact_dir / "email_truth_audit.json",
            error_path=artifact_dir / "email_truth_audit_error.json",
            index_path=artifact_dir / "truth_audit_index.json",
            run_config_path=monitoring_dir / "run_config.json",
        )

    def _monitoring_path(self, filename):
        run_context = self._refresh_run_context()
        monitoring_dir = run_context.get("monitoring_dir", "")
        if not monitoring_dir:
            return ""
        return os.path.join(monitoring_dir, filename)

    def _snapshot_counts(self):
        return {
            "emails": int(getattr(self, "stats", {}).get("emails", 0) or 0),
            "archived": int(getattr(self, "stats", {}).get("invoices", 0) or 0),
            "manual_check": int(getattr(self, "audit_counts", {}).get("manual_check", 0) or 0),
            "retention": int(getattr(self, "audit_counts", {}).get("retention", 0) or 0),
            "raw_invoices": int(getattr(self, "audit_counts", {}).get("raw_invoices", 0) or 0),
            "errors": int(getattr(self, "stats", {}).get("errors", 0) or 0),
        }

    def _reset_timing_metrics(self):
        self._timing_metrics = {}

    def _record_timing_metric(self, name, elapsed_seconds):
        metric_name = str(name or "").strip()
        if not metric_name:
            return
        try:
            elapsed = max(0.0, float(elapsed_seconds or 0.0))
        except (TypeError, ValueError):
            return
        bucket = self._timing_metrics.setdefault(
            metric_name,
            {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0},
        )
        bucket["count"] = int(bucket.get("count", 0) or 0) + 1
        bucket["total_seconds"] = float(bucket.get("total_seconds", 0.0) or 0.0) + elapsed
        bucket["max_seconds"] = max(float(bucket.get("max_seconds", 0.0) or 0.0), elapsed)

    def _build_timing_breakdown(self):
        breakdown = {}
        for metric_name in sorted(self._timing_metrics):
            bucket = self._timing_metrics.get(metric_name, {})
            count = int(bucket.get("count", 0) or 0)
            total_seconds = float(bucket.get("total_seconds", 0.0) or 0.0)
            max_seconds = float(bucket.get("max_seconds", 0.0) or 0.0)
            breakdown[metric_name] = {
                "count": count,
                "total_seconds": round(total_seconds, 3),
                "avg_seconds": round(total_seconds / count, 3) if count else 0.0,
                "max_seconds": round(max_seconds, 3),
            }
        return breakdown

    def _resolve_active_company(self):
        configured_company = str((self._active_run_config or {}).get("company", "") or "").strip()
        if configured_company:
            return configured_company
        return (
            self._run_context.get("company")
            or (self._settings_store.load() or {}).get("company")
            or DEFAULT_COMPANY
        )

    def _effective_save_dir(self, requested_save_path):
        if self._run_context.get("enabled"):
            return self._run_context.get("output_dir", requested_save_path)
        return requested_save_path

    def _effective_date_range(self, date_from, date_to):
        if not self._run_context.get("enabled"):
            return date_from, date_to
        locked_from = self._run_context.get("locked_date_from", "") or date_from
        locked_to = self._run_context.get("locked_date_to", "") or date_to
        return locked_from, locked_to

    def _safe_write_run_config(
        self,
        email_address,
        auth_code="",
        api_key="",
        *,
        request=None,
    ):
        if not self._run_context.get("enabled"):
            return
        lifecycle_run_id = str(
            self._active_run_handle.run_id if self._active_run_handle is not None else ""
        )
        canonical_run_id = str(
            lifecycle_run_id
            or getattr(request, "run_id", "")
            or self._current_run_id
        )
        paths = self._resolve_truth_audit_paths(self._run_context, canonical_run_id)
        from run_evidence import RevisionUnavailable, default_hardware

        hardware_mode, hardware_fingerprint = default_hardware()
        before_exclusive = str(getattr(request, "before_exclusive", "") or "")
        account_channel = str(getattr(request, "channel_id", "") or "")
        mailbox = str(getattr(request, "mailbox", "") or "INBOX")
        run_mode = str(getattr(request, "run_mode", "") or "controlled-run")
        target_identifier = str(
            getattr(request, "target_identifier", "")
            or (self._active_run_config or {}).get("company")
            or ""
        )
        candidate_version = str(
            getattr(request, "candidate_version", "") or "source"
        )
        candidate_revision = str(
            getattr(request, "trusted_revision", "") or ""
        ).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", candidate_revision):
            raise RevisionUnavailable()
        self._diag_write_json(
            str(paths.run_config_path),
            {
                **serialize_run_context(self._run_context),
                "run_id": canonical_run_id,
                "staging_dir": self._active_staging_path(),
                "monitoring_dir": str(paths.monitoring_dir),
                "truth_audit_artifact_dir": str(paths.artifact_dir),
                "truth_audit_index_path": str(paths.index_path),
                "email_domain": self._packaged_diag_email_domain(email_address),
                "has_auth_code": bool(auth_code),
                "has_api_key": bool(api_key),
                "ai_provider": normalize_provider(
                    getattr(self, "_active_ai_provider", "glm")
                ),
                "requested_save_path": self._requested_save_path,
                "effective_save_path": self._effective_save_path,
                "date_from": self._effective_date_from,
                "date_to": self._effective_date_to,
                "active_run_config": dict(self._active_run_config or {}),
                "before_exclusive": before_exclusive,
                "account_channel": account_channel,
                "mailbox": mailbox,
                "target_company": target_identifier,
                "run_mode": run_mode,
                "hardware_mode": hardware_mode,
                "hardware_fingerprint": hardware_fingerprint,
                "candidate_revision": candidate_revision,
                "candidate_version": candidate_version,
                "controlled_run": True,
                "stage_map": {
                    "start_processing": "active",
                    "run_coordinator": "active",
                    "candidate_pipeline": "active",
                    "extraction_pipeline": "active",
                    "archive_service": "active",
                    "cleanup_finalize": "active",
                },
            },
        )

    def _start_truth_audit_async(self, email_address, auth_code):
        if not self._run_context.get("enabled") or not email_address or not auth_code:
            self._truth_audit_thread = None
            self._truth_audit_job = None
            return

        context = dict(self._run_context)
        run_id = str(
            (self._active_run_handle.run_id if self._active_run_handle is not None else "")
            or self._current_run_id
            or context.get("run_id", "")
            or uuid.uuid4().hex
        )
        paths = self._resolve_truth_audit_paths(context, run_id)
        ready = threading.Event()
        abandoned = threading.Event()
        result = {}
        date_from = self._effective_date_from
        date_to = self._effective_date_to

        def _write_evidence(source_path, payload, status, reason_code, user_message):
            self._diag_write_json(str(source_path), payload)
            index_payload = {
                "schema_version": 1,
                "run_id": run_id,
                "status": status,
                "reason_code": reason_code,
                "artifact_path": str(source_path),
            }
            self._diag_write_json(str(paths.index_path), index_payload)
            valid = False
            try:
                persisted_index = json.loads(paths.index_path.read_text(encoding="utf-8"))
                persisted_artifact = Path(persisted_index.get("artifact_path", "")).resolve()
                persisted_artifact.relative_to(paths.artifact_dir.resolve())
                valid = bool(
                    persisted_index.get("run_id") == run_id
                    and persisted_index.get("status") == status
                    and persisted_index.get("reason_code") == reason_code
                    and persisted_artifact == source_path.resolve()
                    and persisted_artifact.exists()
                )
            except Exception:
                valid = False
            result.update(
                {
                    "valid": valid,
                    "status": status,
                    "reason_code": reason_code,
                    "user_message": user_message,
                    "source_path": source_path,
                    "index_path": paths.index_path,
                }
            )

        def _runner():
            try:
                module = importlib.import_module("audit_email_truth")
                collect_truth_table = getattr(module, "collect_truth_table")

                report = collect_truth_table(
                    email_address,
                    auth_code,
                    date_from,
                    date_to,
                )
                if not isinstance(report, dict):
                    raise ValueError("TRUTH_AUDIT_EVIDENCE_INVALID")
                _write_evidence(
                    paths.report_path,
                    report,
                    "success",
                    "TRUTH_AUDIT_OK",
                    "",
                )
            except ModuleNotFoundError as exc:
                _write_evidence(
                    paths.error_path,
                    {
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "skipped",
                        "reason": "AUDIT_EMAIL_TRUTH_MODULE_MISSING",
                        "error_type": type(exc).__name__,
                        "error_hash": stable_hash(str(exc))[:12],
                    },
                    "failed",
                    "AUDIT_EMAIL_TRUTH_MODULE_MISSING",
                    "真值审计模块不可用，请查看诊断报告。",
                )
            except Exception as exc:
                reason_code = (
                    "TRUTH_AUDIT_EVIDENCE_INVALID"
                    if str(exc) == "TRUTH_AUDIT_EVIDENCE_INVALID"
                    else "TRUTH_AUDIT_FAILED"
                )
                user_message = (
                    "真值审计证据无效，请查看诊断报告。"
                    if reason_code == "TRUTH_AUDIT_EVIDENCE_INVALID"
                    else "真值审计失败，请查看诊断报告。"
                )
                _write_evidence(
                    paths.error_path,
                    {
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "reason": reason_code,
                        "error_type": type(exc).__name__,
                        "error_hash": stable_hash(str(exc))[:12],
                    },
                    "failed",
                    reason_code,
                    user_message,
                )
            finally:
                ready.set()

        thread = threading.Thread(target=_runner, name=THREAD_NAME_TRUTH_AUDIT, daemon=True)
        job = TruthAuditJob(
            run_id=run_id,
            paths=paths,
            thread=thread,
            ready=ready,
            abandoned=abandoned,
            result=result,
        )
        self._truth_audit_thread = thread
        self._truth_audit_job = job
        try:
            thread.start()
        except Exception:
            abandoned.set()
            self._truth_audit_thread = None
            self._truth_audit_job = None
            raise
        return thread

    def _await_truth_audit(self):
        job = self._truth_audit_job
        if job is None:
            return
        if job.thread is threading.current_thread():
            raise RuntimeError("truth audit cannot join its own thread")
        # The accepted strict audit takes about 5-12 seconds locally; 120 seconds
        # leaves a conservative production margin while still bounding finalization.
        deadline = time.monotonic() + self._truth_audit_timeout_seconds

        def _expire_job():
            job.abandoned.set()
            self._truth_audit_thread = None
            if self._truth_audit_job is job:
                self._truth_audit_job = None
            raise TruthAuditTimeout("TRUTH_AUDIT_TIMEOUT")

        if not job.ready.wait(self._truth_audit_timeout_seconds):
            _expire_job()

        active_handle = self._active_run_handle
        if (
            job.abandoned.is_set()
            or active_handle is None
            or active_handle.run_id != job.run_id
        ):
            job.abandoned.set()
            self._truth_audit_thread = None
            if self._truth_audit_job is job:
                self._truth_audit_job = None
            raise TruthAuditEvidenceError(
                "TRUTH_AUDIT_EVIDENCE_INVALID",
                "真值审计证据无效，请查看诊断报告。",
            )

        if time.monotonic() > deadline:
            _expire_job()
        self._truth_audit_thread = None
        if self._truth_audit_job is job:
            self._truth_audit_job = None
        if not job.result.get("valid"):
            raise TruthAuditEvidenceError(
                "TRUTH_AUDIT_EVIDENCE_INVALID",
                "真值审计证据无效，请查看诊断报告。",
            )
        if job.result.get("status") != "success":
            raise TruthAuditEvidenceError(
                job.result.get("reason_code") or "TRUTH_AUDIT_FAILED",
                job.result.get("user_message") or "真值审计失败，请查看诊断报告。",
            )

    def _inspect_pdf_health(self, pdf_path):
        if not pdf_path or not str(pdf_path).lower().endswith(".pdf"):
            return None

        pdf_health = {
            "exists": False,
            "size_bytes": 0,
            "starts_with_pdf_magic": False,
            "fitz_open_ok": False,
            "page_count": 0,
            "first_page_text_len": 0,
            "render_to_base64_ok": None,
            "pdf_health_class": "ok",
            "pdf_health_reason": "",
        }
        try:
            pdf_health["exists"] = os.path.exists(pdf_path)
            if not pdf_health["exists"]:
                pdf_health["pdf_health_class"] = "unopenable_pdf"
                pdf_health["pdf_health_reason"] = "missing_file"
                return pdf_health

            pdf_health["size_bytes"] = os.path.getsize(pdf_path)
            if pdf_health["size_bytes"] <= 0:
                pdf_health["pdf_health_class"] = "empty_pdf"
                pdf_health["pdf_health_reason"] = "zero_byte_file"
                return pdf_health

            try:
                with open(pdf_path, "rb") as fh:
                    pdf_health["starts_with_pdf_magic"] = fh.read(5).startswith(b"%PDF")
            except Exception:
                pass

            try:
                import fitz

                with fitz.open(pdf_path) as doc:
                    pdf_health["fitz_open_ok"] = True
                    pdf_health["page_count"] = len(doc)
                    if len(doc) > 0:
                        text_parts = []
                        for page_index in range(min(2, len(doc))):
                            text_parts.append(doc.load_page(page_index).get_text("text") or "")
                        pdf_health["first_page_text_len"] = len("".join(text_parts).strip())
            except Exception as exc:
                pdf_health["fitz_open_ok"] = False
                pdf_health["pdf_health_class"] = "corrupt_pdf" if not pdf_health["starts_with_pdf_magic"] else "unopenable_pdf"
                pdf_health["pdf_health_reason"] = str(exc)
                return pdf_health

            if pdf_health["page_count"] == 0:
                pdf_health["pdf_health_class"] = "empty_pdf"
                pdf_health["pdf_health_reason"] = "no_pages"
            return pdf_health
        except Exception as exc:
            return {
                **pdf_health,
                "pdf_health_class": "unopenable_pdf",
                "pdf_health_reason": str(exc),
            }

    def _apply_render_health(self, pdf_health, base64_img):
        if not pdf_health:
            return None
        pdf_health = dict(pdf_health)
        pdf_health["render_to_base64_ok"] = bool(base64_img)
        if base64_img:
            return pdf_health
        if pdf_health["pdf_health_class"] == "ok":
            if pdf_health.get("page_count", 0) == 0 or pdf_health.get("size_bytes", 0) == 0:
                pdf_health["pdf_health_class"] = "empty_pdf"
                pdf_health["pdf_health_reason"] = pdf_health.get("pdf_health_reason") or "no_renderable_pages"
            elif pdf_health.get("first_page_text_len", 0) == 0:
                pdf_health["pdf_health_class"] = "empty_pdf"
                pdf_health["pdf_health_reason"] = pdf_health.get("pdf_health_reason") or "empty_text_and_render_failed"
            else:
                pdf_health["pdf_health_class"] = "render_failed_pdf"
                pdf_health["pdf_health_reason"] = pdf_health.get("pdf_health_reason") or "base64_render_failed"
        return pdf_health

    @staticmethod
    def _compact_text(value):
        import re

        return re.sub(r"\s+", "", str(value or "")).strip().lower()

    @staticmethod
    def _compact_entity_text(value):
        import re
        import unicodedata

        text = unicodedata.normalize("NFKC", str(value or ""))
        return re.sub(r"\s+", "", text).strip().lower()

    def _extract_pdf_preview_text(self, pdf_path, max_pages=2):
        if not pdf_path or not str(pdf_path).lower().endswith(".pdf") or not os.path.exists(pdf_path):
            return ""
        try:
            import fitz

            texts = []
            with fitz.open(pdf_path) as doc:
                for page_index in range(min(max_pages, len(doc))):
                    texts.append(doc.load_page(page_index).get_text("text") or "")
            return "\n".join(texts).strip()
        except Exception:
            return ""

    def _has_structured_invoice_anchor(self, text):
        compact = self._compact_text(text)
        if not compact:
            return False
        anchors = [
            "发票号码",
            "发票代码",
            "购买方名称",
            "销售方名称",
            "价税合计",
            "开票日期",
            "invoice_number",
            "invoicenumber",
            "seller",
            "purchaser",
        ]
        return any(anchor in compact for anchor in anchors)

    def _match_wrapper_or_utility_reason(self, preview_text, info):
        compact = self._compact_text(preview_text)
        provider_family = str(info.get("provider_family", "") or "").lower()
        if not compact:
            return ""

        baiwang_hits = sum(
            1
            for token in ["发票预览", "下载pdf文件", "下载ofd文件", "下载xml文件", "关于百望", "previewinvoice"]
            if self._compact_text(token) in compact
        )
        if provider_family == "baiwang" and baiwang_hits >= 2 and not self._has_structured_invoice_anchor(preview_text):
            return "BAIWANG_WRAPPER_PAGE"

        if "connectingtotheitunesstore" in compact and "ifyoudonthaveitunes" in compact:
            return "UTILITY_PAGE_ITUNES_REDIRECT"

        if "票通云" in preview_text and (
            "提升运营效率" in preview_text or "发票链接一键" in preview_text or "多维链接" in preview_text
        ):
            return "UTILITY_PAGE_PROVIDER_MARKETING"

        return ""

    def _looks_like_train_ticket(self, doc_type, seller, info_json, info, file_name, pdf_path=""):
        from document_types import looks_like_train_ticket

        return looks_like_train_ticket(
            doc_type,
            seller,
            info_json,
            info,
            file_name,
            preview_loader=lambda: self._extract_pdf_preview_text(
                pdf_path, max_pages=1
            ),
        )

    def _provider_fields_match(self, expected_fields, normalized_snapshot, info_json, recovered_fields=None):
        expected = dict(expected_fields or {})
        if not any(str(value or "").strip() for value in expected.values()):
            return True, "no_expected_fields"

        normalized_snapshot = normalized_snapshot or {}
        recovered_fields = recovered_fields or {}
        invoice_number = str(
            normalized_snapshot.get("InvoiceNumber")
            or info_json.get("InvoiceNumber")
            or info_json.get("invoice_number")
            or recovered_fields.get("invoice_number")
            or ""
        ).strip()
        seller = self._compact_entity_text(
            normalized_snapshot.get("Seller")
            or info_json.get("Seller")
            or recovered_fields.get("seller")
            or ""
        )
        amount = str(
            normalized_snapshot.get("Amount")
            or info_json.get("Amount")
            or recovered_fields.get("amount")
            or ""
        ).strip()
        date = str(
            normalized_snapshot.get("Date")
            or info_json.get("Date")
            or recovered_fields.get("invoice_date")
            or ""
        ).strip()

        expected_number = str(expected.get("invoice_number") or "").strip()
        if expected_number:
            return invoice_number == expected_number, "invoice_number"

        expected_seller = self._compact_entity_text(expected.get("seller") or "")
        expected_amount = str(expected.get("amount") or "").strip()
        expected_date = str(expected.get("invoice_date") or "").strip()

        seller_match = not expected_seller or expected_seller in seller or seller in expected_seller
        amount_match = not expected_amount or expected_amount == amount
        date_match = not expected_date or expected_date == date
        return seller_match and amount_match and date_match, "seller_amount_date"

    def _evaluate_document_acceptance(self, info, info_json, normalized_snapshot, pdf_health, pdf_path):
        preview_text = self._extract_pdf_preview_text(pdf_path)
        wrapper_reason = self._match_wrapper_or_utility_reason(preview_text, info)
        provider_family = str(info.get("provider_family", "") or "").lower()
        expected_fields = info.get("provider_expected_fields") or {}
        recovered_fields = info.get("provider_recovered_fields") or {}

        result = {
            "accepted": True,
            "reason_code": "",
            "bucket": "",
            "message": "",
            "provider_family": provider_family,
            "expected_fields": expected_fields,
            "pdf_preview_excerpt": preview_text[:500],
            "pdf_health_class": (pdf_health or {}).get("pdf_health_class", ""),
        }

        if wrapper_reason:
            result.update({
                "accepted": False,
                "reason_code": wrapper_reason,
                "bucket": "provider_wrapper_rejected",
                "message": "Downloaded result still looks like a provider wrapper or utility page.",
            })
            return result

        if provider_family == "baiwang":
            matched, matched_on = self._provider_fields_match(
                expected_fields,
                normalized_snapshot,
                info_json,
                recovered_fields=recovered_fields,
            )
            result["matched_on"] = matched_on
            if not matched:
                result.update({
                    "accepted": False,
                    "reason_code": "BAIWANG_EXPECTED_ENTITY_MISMATCH",
                    "bucket": "provider_entity_mismatch",
                    "message": "Downloaded Baiwang result does not match seller/amount/date/invoice anchors from email body.",
                })
                return result

        if provider_family in DIRECT_INVOICE_FAMILIES:
            invoice_number = str(
                normalized_snapshot.get("InvoiceNumber")
                or info_json.get("InvoiceNumber")
                or info_json.get("invoice_number")
                or recovered_fields.get("invoice_number")
                or ""
            ).strip()
            expected_number = str(expected_fields.get("invoice_number") or "").strip()
            if expected_number and invoice_number and invoice_number != expected_number:
                result.update({
                    "accepted": False,
                    "reason_code": "DIRECT_INVOICE_EXPECTED_ENTITY_MISMATCH",
                    "bucket": "provider_entity_mismatch",
                    "message": "Downloaded direct-invoice PDF exposes a conflicting invoice number.",
                    "matched_on": "invoice_number_conflict",
                })
                return result

            seller = self._compact_entity_text(
                normalized_snapshot.get("Seller")
                or info_json.get("Seller")
                or recovered_fields.get("seller")
                or ""
            )
            expected_seller = self._compact_entity_text(expected_fields.get("seller") or "")
            if expected_seller and seller and expected_seller not in seller and seller not in expected_seller:
                result.update({
                    "accepted": False,
                    "reason_code": "DIRECT_INVOICE_EXPECTED_ENTITY_MISMATCH",
                    "bucket": "provider_entity_mismatch",
                    "message": "Downloaded direct-invoice PDF exposes a conflicting seller entity.",
                    "matched_on": "seller_conflict",
                })
                return result

        return result

    def _set_run_state(self, run_state, status_text=None, progress=None, last_error=None):
        previous_state = self.run_state
        self.run_state = run_state
        self._is_running = run_state in {"running", "finalizing"}
        if status_text is not None:
            self.status_text = status_text
        if progress is not None:
            self.progress = progress
        if last_error is not None:
            self.last_error = last_error
        self._safe_emit_run_state_event(previous_state, run_state)

    def _sync_run_state_store_from_legacy(self):
        # Polling used to replay the full legacy lists into the store on every
        # tick, which made update() compare thousands of rows per second. Skip
        # the whole sync when neither scalars nor sequence identities changed.
        signature = (
            self.progress,
            self.status_text,
            self.run_state,
            self.last_error,
            self._stop_requested,
            self.quota_exhausted,
            self.quota_message,
            id(self.logs),
            len(self.logs),
            id(self.processed_invoices),
            len(self.processed_invoices),
            id(self.error_invoices),
            len(self.error_invoices),
            id(self.discovered_categories),
            len(self.discovered_categories),
            id(self.stats),
            len(self.stats),
        )
        if signature == self._legacy_sync_signature:
            return
        self._legacy_sync_signature = signature
        self._run_state_store.update(
            progress=self.progress,
            status_text=self.status_text,
            run_state=self.run_state,
            last_error=self.last_error,
            stop_requested=self._stop_requested,
            quota_exhausted=self.quota_exhausted,
            quota_message=self.quota_message,
            statistics=self.stats,
            processed_invoices=self.processed_invoices,
            error_invoices=self.error_invoices,
            categories=self.discovered_categories,
            logs=self.logs,
        )

    def _begin_run(self, status_text):
        handle = self._active_run_handle
        if handle is not None and handle.state in {RunState.COMPLETED, RunState.FAILED}:
            self._active_run_handle = None
            handle = None
        if handle is None:
            handle = self._prepare_run_lifecycle()
        if handle.state is RunState.CREATED:
            handle.advance(RunState.SCANNING)
        self.progress = 0
        self.logs = []
        self._legacy_sync_signature = None
        self._stop_requested = False
        self.quota_exhausted = False
        self.quota_message = ""
        self._last_export_path = ""
        self.discovered_categories.clear()
        self.processed_invoices = []
        self.error_invoices = []
        self.stats = {"emails": 0, "invoices": 0, "errors": 0}
        self.audit_counts = {"manual_check": 0, "retention": 0, "raw_invoices": 0}
        self._email_level_url_evidence_seen = set()
        self._reset_timing_metrics()
        self.build_identity = load_build_identity()
        self._set_run_state("running", status_text=status_text, progress=0, last_error="")
        build_label = self.build_identity.get("build_label", "")
        source_revision = self.build_identity.get("source_revision", "")
        review_folder = self.build_identity.get("manual_review_folder", MANUAL_REVIEW_FOLDER)
        build_stamp = " / ".join([part for part in [build_label, source_revision] if part])
        if build_stamp:
            self._append_log("构建", f"当前构建：{build_stamp}；复核目录：{review_folder}", "text-slate-400")

    def _append_log(self, level, message, color="text-slate-700"):
        self.logs.append({
            "time": time.strftime("[%H:%M:%S]"),
            "type": level,
            "color": color,
            "msg": message,
        })

    @staticmethod
    def _url_candidate_label(info):
        info = info or {}
        identity = {
            "source_url": info.get("source_url") or info.get("filepath") or "",
            "email_id": info.get("email_id") or info.get("source_email_id") or "",
            "provider_family": info.get("provider_family") or "",
        }
        return f"URL-candidate-{stable_hash(identity)[:12]}"

    def _sanitize_url_candidate_logs(self, start_index, info):
        label = self._url_candidate_label(info)
        for entry in self.logs[max(0, int(start_index or 0)):]:
            if isinstance(entry, dict):
                entry["msg"] = f"URL candidate processing event [{label}]"

    def _on_email_fetcher_progress(self, message):
        message = str(message or "").strip()
        if not message:
            return
        self.logs.append({
            "time": time.strftime("[%H:%M:%S]"),
            "type": "运行",
            "color": "text-blue-400",
            "msg": message,
        })

    @staticmethod
    def _user_safe_source_reference(source_path):
        if not source_path:
            return ""
        text = str(source_path)
        if text.startswith(("http://", "https://")):
            return text
        text = text.rstrip("\\/")
        return os.path.basename(text) or text

    def _request_safe_stop(self, message="正在安全停止，当前文件处理完后结束..."):
        if self._stop_requested:
            return
        self._stop_requested = True
        fetcher = self._active_fetcher
        abort = getattr(fetcher, "abort", None)
        if callable(abort):
            handle = self._active_run_handle
            if handle is not None:
                self._imap_abort_run_id = handle.run_id
            abort()
        self.status_text = message
        self._append_log("停止", message, "text-amber-600")
        self._sync_run_state_store_from_legacy()

    def _resolve_quota_message(self, error_text):
        normalized = str(error_text or "").lower()
        if not normalized:
            return ""
        quota_patterns = [
            "status code 402",
            "402 client error",
            "payment required",
            "余额不足",
            "额度不足",
            "quota",
            "insufficient balance",
            "insufficient_quota",
            "billing",
        ]
        if any(token in normalized for token in quota_patterns):
            return self._quota_message_text()
        return ""

    def _provider_label(self):
        provider = normalize_provider(getattr(self, "_active_ai_provider", "glm"))
        return "DeepSeek" if provider == DEEPSEEK_PROVIDER else "GLM"

    def _quota_message_text(self):
        return f"{self._provider_label()} API 额度已耗尽，请充值或更换可用的 API Key。"

    def _mark_quota_exhausted(self, message=None):
        self.quota_exhausted = True
        self.quota_message = message or self._quota_message_text()
        self.status_text = self.quota_message
        self._append_log("额度", self.quota_message, "text-rose-600")

    def _safe_failure_contract(self, status_text, error_message):
        status = str(status_text or "")
        error = str(error_message or "")
        normalized = f"{status} {error}".upper()
        if "MISSING_REQUIRED_CREDENTIALS" in normalized:
            return "MISSING_REQUIRED_CREDENTIALS", "缺少必要凭证，请填写邮箱、授权码和 API Key。"
        if "IMAP_LOGIN_FAILED" in normalized or "邮箱登录失败" in status:
            return "IMAP_LOGIN_FAILED", "邮箱登录失败，请检查授权码和 IMAP 设置。"
        if "IMAP_TLS_CERTIFICATE_INVALID" in normalized:
            return "IMAP_TLS_CERTIFICATE_INVALID", ImapCertificateError.user_message
        if "IMAP_CONNECTION_TIMEOUT" in normalized:
            return "IMAP_CONNECTION_TIMEOUT", ImapTimeoutError.user_message
        if "QUOTA_EXHAUSTED" in normalized or "额度" in status:
            return "QUOTA_EXHAUSTED", self._quota_message_text()
        if "UNRESOLVED_MAILBOX_INPUT" in normalized:
            return "UNRESOLVED_MAILBOX_INPUT", "部分邮件在重试后仍无法读取，本次任务已失败；已读取产物保留供诊断。"
        if "MAILBOX_SCAN_FAILED" in normalized:
            return "MAILBOX_SCAN_FAILED", "邮箱扫描响应异常，本次任务已失败；请重试并查看诊断报告。"
        if "WORKER_START_FAILED" in normalized or "启动失败" in status:
            return "WORKER_START_FAILED", "后台任务启动失败，请重试。"
        return "PROCESSING_FAILED", "处理过程中发生异常，请重试；如持续失败请查看诊断报告。"

    def _finish_run(self, success, status_text, last_error=""):
        self._legacy_sync_signature = None
        handle = self._active_run_handle or self._prepare_run_lifecycle()
        if handle.state not in {RunState.COMPLETED, RunState.FAILED}:
            if not success:
                reason_code, user_message = self._safe_failure_contract(status_text, last_error)
                handle.fail(
                    RuntimeError(last_error or status_text or reason_code),
                    reason_code=reason_code,
                    user_message=user_message,
                )
            self._mark_finalizing()
            self._start_async_finalizers()

        if self._terminal_frontend_run_id == handle.run_id:
            return
        self._terminal_frontend_run_id = handle.run_id
        effective_success = bool(success and handle.state is RunState.COMPLETED)
        if effective_success:
            self._set_run_state("completed", status_text=status_text, progress=100, last_error="")
        else:
            if success:
                self.logs[:] = [entry for entry in self.logs if entry.get("type") != "完成"]
            failed_progress = self.progress if self.progress and self.progress < 100 else 99
            lifecycle_error = handle.error or last_error
            failed_status = status_text if not success else "处理失败"
            self._set_run_state("failed", status_text=failed_status, progress=failed_progress, last_error=lifecycle_error)
        self._worker_thread = None


    def _auto_start_local_scan(self):
        self.logs.append({
            "time": time.strftime("[%H:%M:%S]"),
            "type": "INFO",
            "color": "text-slate-500",
            "msg": "Local auto scan is disabled in the release-prep candidate.",
        })
        return {"success": False, "message": "AUTO_LOCAL_SCAN_DISABLED"}

    def get_default_save_path(self):
        """前端初始化时获取默认的保存路径（桌面下的发票整理文件夹）"""
        run_context = self._refresh_run_context()
        if run_context.get("enabled"):
            return ensure_directory(run_context.get("output_dir", ""))
        return ensure_directory(resolve_default_save_path())

    def _normalize_user_save_path(self, path_value=""):
        run_context = self._refresh_run_context()
        if run_context.get("enabled"):
            return ensure_directory(run_context.get("output_dir", ""))

        candidate_path = str(path_value or "").strip()
        if not candidate_path:
            candidate_path = resolve_default_save_path()
        return ensure_directory(candidate_path)

    def _output_state_dir(self, save_path):
        return get_output_state_dir(save_path or self.get_default_save_path())

    def _history_file_path(self, output_state_dir):
        return os.path.join(output_state_dir, ".antigravity_history.json")

    def _committed_state_file_path(self, output_state_dir):
        return os.path.join(output_state_dir, "committed_state.json")

    def _run_state_file_path(self, output_state_dir):
        return os.path.join(output_state_dir, "run_state.json")

    def _read_json_file(self, path, default):
        if not path or not os.path.exists(path):
            return copy.deepcopy(default)
        try:
            # utf-8-sig tolerates a BOM; Windows editors/PowerShell can add one and
            # a single BOM must not make the whole ledger look corrupt.
            with open(path, "r", encoding="utf-8-sig") as handle:
                return json.load(handle)
        except Exception:
            return copy.deepcopy(default)

    def _quarantine_unreadable_state(self, output_state_dir, reason):
        """Back up unreadable scoped state instead of failing the run."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        for filename in (
            "committed_state.json",
            ".antigravity_history.json",
            "processed_records.json",
        ):
            path = os.path.join(output_state_dir, filename)
            if not os.path.exists(path):
                continue
            try:
                os.replace(path, f"{path}.corrupt-{timestamp}")
            except OSError:
                try:
                    os.remove(path)
                except OSError:
                    continue
        try:
            self._append_log(
                "维护",
                f"检测到台账文件异常（{reason}），已备份并重建台账。",
                "text-amber-500",
            )
        except Exception:
            pass

    def _write_json_file(self, path, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        os.replace(temp_path, path)

    def _mark_output_run_state(self, output_state_dir, status, **extra):
        payload = {
            "status": status,
            "run_id": self._current_run_id or "",
            "save_path": self._effective_save_path or self._requested_save_path or "",
            "date_from": self._effective_date_from or "",
            "date_to": self._effective_date_to or "",
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        payload.update({key: value for key, value in extra.items() if value not in (None, "")})
        self._write_json_file(self._run_state_file_path(output_state_dir), payload)
        return payload

    def _load_output_run_state(self, output_state_dir):
        return self._read_json_file(self._run_state_file_path(output_state_dir), {})

    def _archive_folder_history_path(self, output_state_dir):
        return os.path.join(output_state_dir, "archive_folders.json")

    def _load_archive_folder_history(self, save_path):
        """Return category folders used by earlier runs for this library.

        Rules may rename or remove a category folder; the history keeps the old
        folder excluded from rescans and known to the flat-layout migration.
        """
        state_dir = self._output_state_dir(save_path)
        payload = self._read_json_file(
            self._archive_folder_history_path(state_dir), {}
        )
        folders = payload.get("folders") if isinstance(payload, dict) else []
        if not isinstance(folders, (list, tuple, set)):
            return ()
        from organize_layout import IN_PLACE_TOOL_DIR_NAMES

        cleaned = []
        for value in folders:
            name = str(value or "").strip()
            if (
                not name
                or os.path.basename(name) != name
                or name in IN_PLACE_TOOL_DIR_NAMES
            ):
                continue
            if name not in cleaned:
                cleaned.append(name)
        return tuple(cleaned)

    def _load_archive_file_categories(self, save_path):
        """Return the last known category folder for archived file names."""
        state_dir = self._output_state_dir(save_path)
        payload = self._read_json_file(
            self._archive_folder_history_path(state_dir), {}
        )
        raw_files = payload.get("files") if isinstance(payload, dict) else {}
        if not isinstance(raw_files, dict):
            return {}
        from organize_layout import IN_PLACE_TOOL_DIR_NAMES

        cleaned = {}
        for raw_name, raw_folder in raw_files.items():
            name = str(raw_name or "").strip()
            folder = str(raw_folder or "").strip()
            if (
                not name
                or os.path.basename(name) != name
                or not folder
                or os.path.basename(folder) != folder
                or folder in IN_PLACE_TOOL_DIR_NAMES
            ):
                continue
            cleaned[name] = folder
        return cleaned

    def _record_archive_folder_history(
        self, save_path, folders, file_folders=None
    ):
        """Persist category folders and per-file folder evidence (best effort)."""
        from organize_layout import IN_PLACE_TOOL_DIR_NAMES

        history = list(self._load_archive_folder_history(save_path))
        for value in folders or ():
            name = str(value or "").strip()
            if (
                not name
                or os.path.basename(name) != name
                or name in IN_PLACE_TOOL_DIR_NAMES
            ):
                continue
            if name not in history:
                history.append(name)
        known_files = self._load_archive_file_categories(save_path)
        for raw_name, raw_folder in dict(file_folders or {}).items():
            name = str(raw_name or "").strip()
            folder = str(raw_folder or "").strip()
            if (
                not name
                or os.path.basename(name) != name
                or not folder
                or os.path.basename(folder) != folder
                or folder in IN_PLACE_TOOL_DIR_NAMES
            ):
                continue
            known_files[name] = folder
        if not history and not known_files:
            return ()
        state_dir = self._output_state_dir(save_path)
        try:
            self._write_json_file(
                self._archive_folder_history_path(state_dir),
                {
                    "folders": sorted(history),
                    "files": dict(sorted(known_files.items())),
                },
            )
        except OSError:
            return tuple(history)
        return tuple(history)

    def _migrate_completed_output_state(self, output_state_dir):
        committed_path = self._committed_state_file_path(output_state_dir)
        if os.path.exists(committed_path):
            return
        run_state = self._load_output_run_state(output_state_dir)
        if not isinstance(run_state, dict) or run_state.get("status") != "completed":
            return
        with open(self._history_file_path(output_state_dir), "r", encoding="utf-8") as handle:
            history = json.load(handle)
        with open(os.path.join(output_state_dir, "processed_records.json"), "r", encoding="utf-8") as handle:
            records = json.load(handle)
        if (
            not isinstance(history, list)
            or any(not isinstance(item, str) for item in history)
            or not isinstance(records, dict)
            or any(not isinstance(key, str) for key in records)
        ):
            raise ValueError("Completed output state is unreadable")
        self._write_json_file(
            committed_path,
            {"history": history, "business_records": records},
        )

    def _load_committed_history(self, output_state_dir):
        committed_path = self._committed_state_file_path(output_state_dir)
        if os.path.exists(committed_path):
            snapshot = self._read_json_file(committed_path, None)
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("history"), list):
                self._quarantine_unreadable_state(
                    output_state_dir, "committed_state_unreadable"
                )
                return set()
            return {str(key) for key in snapshot["history"] if isinstance(key, str) and key}
        run_state = self._load_output_run_state(output_state_dir)
        if str(run_state.get("status") or "").strip().lower() != "completed":
            return set()
        history = self._read_json_file(self._history_file_path(output_state_dir), [])
        if not isinstance(history, list):
            return set()
        return {
            str(item).strip()
            for item in history
            if isinstance(item, str) and str(item).strip()
        }

    def _load_business_records(self, save_path, output_state_dir, extractor=None, backup_legacy=True):
        legacy_path = os.path.join(save_path, "processed_records.json")
        legacy = extractor.load_processed_records() if extractor else {}
        if os.path.isfile(legacy_path):
            with open(legacy_path, "r", encoding="utf-8-sig") as handle:
                legacy = json.load(handle)
        if not isinstance(legacy, dict):
            raise ValueError("Legacy business records must be an object")
        if os.path.isfile(legacy_path) and backup_legacy:
            backup = os.path.join(output_state_dir, "processed_records.legacy-backup.json")
            if not os.path.exists(backup):
                self._write_json_file(backup, legacy)

        committed_path = self._committed_state_file_path(output_state_dir)
        if os.path.exists(committed_path):
            snapshot = self._read_json_file(committed_path, None)
            scoped = snapshot.get("business_records") if isinstance(snapshot, dict) else None
            if not isinstance(scoped, dict):
                self._quarantine_unreadable_state(
                    output_state_dir, "committed_state_unreadable"
                )
                scoped = {}
        else:
            scoped_path = os.path.join(output_state_dir, "processed_records.json")
            scoped = {}
            if self._load_output_run_state(output_state_dir).get("status") == "completed" and os.path.isfile(scoped_path):
                with open(scoped_path, "r", encoding="utf-8-sig") as handle:
                    scoped = json.load(handle)
        if not isinstance(scoped, dict):
            raise ValueError("Scoped business records must be an object")
        return {**legacy, **scoped}

    def _archived_filename_index(self, save_path):
        """Collect the file names currently present under the user-visible archive root."""
        names = set()
        root = os.path.abspath(str(save_path or ""))
        if not os.path.isdir(root):
            return names
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                relative = os.path.relpath(dirpath, root)
                depth = 0 if relative == "." else relative.count(os.sep) + 1
                # Audit-retention evidence is not an archived invoice; never use it
                # to prove that a business record's file still exists.
                dirnames[:] = [name for name in dirnames if name != "_audit_retention"]
                if depth >= 4:
                    dirnames[:] = []
                for name in filenames:
                    names.add(name)
        except OSError:
            return names
        return names

    def _repair_stale_archive_ledger(
        self, save_path, output_state_dir, business_records, history_keys
    ):
        """Rebuild the dedupe ledger when the files it references have disappeared.

        Business records only store the archived file *name*; the opaque history
        ids that suppress re-processing cannot be mapped back to a single record.
        When any recorded file is missing we therefore drop the stale records and
        reset the history set, so a normal scan can fetch and archive those
        invoices again. Records whose files still exist stay in the ledger, and
        archive-level dedupe keeps protecting them.
        """
        records = dict(business_records or {})
        if not records:
            return records, history_keys
        existing_names = self._archived_filename_index(save_path)
        stale_keys = []
        for key, record in records.items():
            if not isinstance(record, dict):
                continue
            filename = os.path.basename(str(record.get("file") or "").strip())
            if filename and filename not in existing_names:
                stale_keys.append(key)
        if not stale_keys:
            return records, history_keys

        backup_path = os.path.join(
            output_state_dir, f"ledger-repair-{time.strftime('%Y%m%d_%H%M%S')}.json"
        )
        try:
            self._write_json_file(
                backup_path,
                {
                    "reason": "ARCHIVED_FILES_MISSING",
                    "stale_records": {key: records[key] for key in stale_keys},
                    "history": sorted(str(item) for item in (history_keys or ())),
                },
            )
        except Exception:
            backup_path = ""

        for key in stale_keys:
            records.pop(key, None)
        repaired_history = set()
        try:
            # Persist the repair immediately so an interrupted run cannot leave
            # the stale ledger in place for the next attempt.
            self._write_json_file(self._history_file_path(output_state_dir), [])
            self._write_json_file(
                os.path.join(output_state_dir, "processed_records.json"), records
            )
            self._write_json_file(
                self._committed_state_file_path(output_state_dir),
                {"history": [], "business_records": records},
            )
        except Exception:
            pass

        self._append_log(
            "维护",
            (
                f"检测到 {len(stale_keys)} 条历史归档文件缺失，已重建去重台账；"
                "本次扫描会重新处理这些发票。"
            ),
            "text-amber-500",
        )
        emit = getattr(self, "_safe_emit_stage_event", None)
        if callable(emit):
            try:
                emit(
                    "ledger_repair",
                    "repaired",
                    {"stale_records": len(stale_keys), "backup_path": backup_path},
                )
            except Exception:
                pass
        return records, repaired_history

    def _commit_output_state(self, output_state_dir, history_keys, business_records):
        committed_history = sorted({str(item).strip() for item in (history_keys or set()) if str(item).strip()})
        self._write_json_file(self._history_file_path(output_state_dir), committed_history)
        self._write_json_file(os.path.join(output_state_dir, "processed_records.json"), business_records or {})
        self._write_json_file(
            self._committed_state_file_path(output_state_dir),
            {"history": committed_history, "business_records": business_records or {}},
        )
        self._mark_output_run_state(
            output_state_dir,
            "completed",
            history_count=len(committed_history),
            business_record_count=len(business_records or {}),
        )

    def _validate_runtime_build_identity(self):
        identity = dict(self.build_identity or {})
        issues = []
        if getattr(sys, "frozen", False) and not identity.get("identity_path"):
            issues.append("missing build identity payload")
        if identity.get("manual_review_folder") and identity.get("manual_review_folder") != MANUAL_REVIEW_FOLDER:
            issues.append(
                f"manual review folder mismatch: expected {MANUAL_REVIEW_FOLDER}, got {identity.get('manual_review_folder')}"
            )
        if issues:
            raise RuntimeError("Build identity validation failed: " + "; ".join(issues))

    def _default_user_settings(self):
        return {
            "email": "",
            "auth_code": "",
            "api_key": "",
            "ai_provider": "glm",
            "deepseek_api_key": "",
            "save_path": self.get_default_save_path(),
            "date_from": "",
            "date_to": "",
            "quick_range": "last_30_days",
            "company": "",
            "glm_profile_limits": copy.deepcopy(DEFAULT_GLM_PROFILE_LIMITS),
            "glm_model_candidates": copy.deepcopy(DEFAULT_GLM_MODEL_CANDIDATES),
            "remember_settings": True,
            # Feature split (v0.3): mail / fetch-only / local-folder organizing.
            "task_mode": "mail",
            "local_input_dir": "",
            # Empty means "same folder as local_input_dir" (in-place organizing).
            "local_output_dir": "",
            # Keep per-category archive folders (False = flat into the root).
            "local_split_by_category": True,
        }

    @staticmethod
    def _normalize_task_mode(value):
        mode = str(value or "").strip().lower()
        return mode if mode in {"mail", "fetch", "local"} else "mail"

    def get_run_context(self):
        return serialize_run_context(self._refresh_run_context())

    def test_connection(self, email, auth_code, api_key="", ai_provider="glm"):

        """前端测试连接时调用；无 API Key 时只验证邮箱并确认本地识别引擎可用。"""
        api_key = str(api_key or "")
        provider = normalize_provider(ai_provider)
        is_deepseek = provider == DEEPSEEK_PROVIDER
        provider_label = "DeepSeek" if is_deepseek else "智谱 GLM"
        api_label = "DeepSeek" if is_deepseek else "GLM"
        connection_target = "DeepSeek" if is_deepseek else "智谱"
        print(
            "Testing connection",
            {
                "email_domain": self._packaged_diag_email_domain(email),
                "has_auth_code": bool(auth_code),
                "api_key_length": len(api_key),
                "ai_provider": provider,
            },
        )

        # 邮箱连接测试（仅在填写授权码时执行）
        if auth_code:
            fetcher = None
            try:
                from email_fetcher import EmailFetcher
                channel = resolve_channel(email)
                fetcher = EmailFetcher(
                    email,
                    auth_code,
                    imap_server=channel["imap_host"],
                    imap_port=channel["imap_port"],
                )
                if not fetcher.connect():
                    if getattr(fetcher, "certificate_error", False):
                        return {"success": False, "message": ImapCertificateError.user_message}
                    if getattr(fetcher, "timeout_error", False):
                        return {"success": False, "message": ImapTimeoutError.user_message}
                    return {"success": False, "message": "邮箱 IMAP 登录验证失败"}
            except Exception:
                return {"success": False, "message": "邮箱连接异常，请检查授权码、IMAP 设置或网络"}
            finally:
                if fetcher is not None:
                    fetcher.disconnect()
        
        if not api_key:
            if auth_code:
                return {
                    "success": True,
                    "message": "连接成功 - 邮箱验证通过，本地识别引擎已就绪（无需 API Key）",
                }
            return {"success": False, "message": "请填写邮箱地址和授权码"}

        if len(api_key) <= 5:
            return {"success": False, "message": "连接失败 - API Key 格式不正确"}

        runtime = None
        try:
            payload = {
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 5
            }
            runtime = GlmRuntime(
                api_key,
                provider=provider,
                settings=self._settings_store.load() or {},
            )
            runtime.request(
                "text",
                payload,
                lambda body: body["choices"][0]["message"]["content"],
                attempts=1,
                timeout_seconds=15,
            )
            return {"success": True, "message": f"连接成功 - {provider_label} 服务已就绪"}
        except GlmRequestError as exc:
            if exc.http_status == 401:
                return {"success": False, "message": "连接失败 - API Key 鉴权未通过或无效"}
            if exc.http_status == 402:
                return {"success": False, "message": f"连接失败 - {api_label} API 额度已耗尽，请充值或更换 API Key"}
            if exc.http_status == 429 or exc.business_code == 1302 or exc.reason == "rate_limited":
                return {"success": False, "message": "连接失败 - 触发限流，请求并发过高"}
            if exc.reason == "timeout":
                return {"success": False, "message": "API连接失败 - 请求超时，请检查您的网络连接"}
            if exc.reason == "connection_error":
                return {"success": False, "message": f"API连接失败 - 无法连接到{connection_target} API 服务器"}
            if exc.http_status is not None:
                return {"success": False, "message": f"连接异常 - 状态码: {exc.http_status}"}
            return {"success": False, "message": f"网络或API未知异常: {api_label} 请求失败"}
        except Exception:
            return {"success": False, "message": f"网络或API未知异常: {api_label} 请求失败"}
        finally:
            if runtime is not None:
                close_runtime = getattr(runtime, "close", None)
                if callable(close_runtime):
                    close_runtime()

    def test_email_auth(self, email_address, auth_code):
        if not email_address or not auth_code:
            return {"success": False, "message": "请先填写邮箱地址和授权码"}
        from email_fetcher import EmailFetcher
        fetcher = None
        try:
            channel = resolve_channel(email_address)
            fetcher = EmailFetcher(
                email_address,
                auth_code,
                imap_server=channel["imap_host"],
                imap_port=channel["imap_port"],
            )
            if not fetcher.connect():
                if getattr(fetcher, "certificate_error", False):
                    return {"success": False, "message": ImapCertificateError.user_message}
                if getattr(fetcher, "timeout_error", False):
                    return {"success": False, "message": ImapTimeoutError.user_message}
                return {"success": False, "message": "邮箱授权验证失败，请检查授权码、IMAP 设置或网络"}
            return {"success": True, "message": "邮箱授权验证成功"}
        except Exception:
            return {"success": False, "message": "邮箱授权验证失败，请检查授权码、IMAP 设置或网络"}
        finally:
            if fetcher is not None:
                fetcher.disconnect()



    def _processing_worker(self, request, run_handle, dependencies):
        try:
            if run_handle is None or run_handle is not self._active_run_handle:
                raise RuntimeError("reserved run handle ownership is required")
            if request.run_id != run_handle.run_id:
                raise RuntimeError("run request does not match reserved handle")
            coordinator = RunCoordinator(
                self._run_lifecycle,
                self._run_state_store,
                dependencies,
            )
            return coordinator.run(request, handle=run_handle)
        except Exception as exc:
            self._close_run_dependencies(dependencies)
            self._packaged_diag_write(
                "coordinator_worker_exception",
                "_processing_worker",
                "exception",
                exc=exc,
            )
            if run_handle is not None and run_handle.state in {RunState.COMPLETED, RunState.FAILED}:
                return None
            if run_handle is not None:
                self._finalize_admission_failure(
                    run_handle,
                    exc,
                    reason_code="COORDINATOR_START_FAILED",
                )
            return None
        finally:
            current = threading.current_thread()
            with self._admission_lock:
                if self._worker_thread is current:
                    self._worker_thread = None

    def _run_processing_loop(
        self,
        attachments_info,
        api_key,
        save_path,
        since_date=None,
        before_date=None,
        rules_text="",
    ):
        import inspect
        from invoice_extractor import InvoiceExtractor

        if not attachments_info:
            return self._run_processing_loop_with_extractor(
                attachments_info,
                api_key,
                save_path,
                since_date,
                before_date,
                rules_text,
                _extractor=None,
            )
        extractor_parameters = inspect.signature(InvoiceExtractor).parameters.values()
        supports_glm_settings = any(
            parameter.name == "glm_settings"
            or parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in extractor_parameters
        )
        supports_ai_provider = any(
            parameter.name == "ai_provider"
            or parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in extractor_parameters
        )
        extractor_kwargs = {"api_key": api_key, "output_dir": save_path}
        if supports_glm_settings:
            extractor_kwargs["glm_settings"] = self._settings_store.load() or {}
        if supports_ai_provider:
            extractor_kwargs["ai_provider"] = getattr(self, "_active_ai_provider", "glm")
        owned_extractor = InvoiceExtractor(**extractor_kwargs)
        try:
            return self._run_processing_loop_with_extractor(
                attachments_info,
                api_key,
                save_path,
                since_date,
                before_date,
                rules_text,
                _extractor=owned_extractor,
            )
        finally:
            close_extractor = getattr(owned_extractor, "close", None)
            if callable(close_extractor):
                close_extractor()

    def _run_processing_loop_with_extractor(
        self,
        attachments_info,
        api_key,
        save_path,
        since_date=None,
        before_date=None,
        rules_text="",
        _extractor=None,
        _worker_extractor_factory=None,
        _archive_operation=None,
        _pairing_finalizer=None,
    ):
        from app_archive_adapter import AppArchiveAdapter
        from archive_service import ArchiveService
        from candidate_pipeline import CandidatePipeline, CandidatePreflight
        from extraction_pipeline import ExtractionPipeline, SharedRuntimeRemoteExtractor

        del AppArchiveAdapter, ArchiveService, CandidatePipeline, CandidatePreflight
        del ExtractionPipeline, SharedRuntimeRemoteExtractor
        session = self._create_processing_pipeline_session(
            attachments_info,
            api_key,
            save_path,
            since_date,
            before_date,
            rules_text,
            _extractor=_extractor,
            _worker_extractor_factory=_worker_extractor_factory,
            _archive_operation=_archive_operation,
            _pairing_finalizer=_pairing_finalizer,
            _prepare_remote_images=False,
        )
        try:
            outcomes = session.extract()
            return session.archive(outcomes)
        except (ProcessingLoopFailure, QuotaExceededError, RemoteAuthError):
            raise
        except Exception as exc:
            raise ProcessingLoopFailure("PROCESSING_PIPELINE_EXCEPTION") from exc
        finally:
            session.close()

    def _create_processing_pipeline_session(
        self,
        attachments_info,
        api_key,
        save_path,
        since_date=None,
        before_date=None,
        rules_text="",
        *,
        _extractor=None,
        _worker_extractor_factory=None,
        _archive_operation=None,
        _pairing_finalizer=None,
        _owned_extractor=None,
        _prepare_remote_images=True,
        _dry_run=False,
        _flat_layout=False,
    ):
        from app_archive_adapter import AppArchiveAdapter
        from archive_service import ArchiveService
        from bounded_url_recovery import BoundedUrlRecoveryClient
        from candidate_pipeline import CandidatePipeline, CandidatePreflight
        from deferred_url_recovery import (
            DEFAULT_URL_RECOVERY_MAX_WORKERS,
            DeferredUrlRecoveryScheduler,
        )
        from extraction_pipeline import ExtractionPipeline, SharedRuntimeRemoteExtractor
        from invoice_extractor import InvoiceExtractor

        dry_run = bool(_dry_run)
        candidates = CandidatePipeline().collect(attachments_info)
        output_state_dir = self._output_state_dir(save_path)
        if dry_run:
            # Preview must not migrate, repair, or rewrite the user's ledger.
            business_records = self._load_business_records(
                save_path, output_state_dir, _extractor, backup_legacy=False
            )
            working_history = set(self._load_committed_history(output_state_dir))
        else:
            self._migrate_completed_output_state(output_state_dir)
            business_records = self._load_business_records(
                save_path, output_state_dir, _extractor
            )
            working_history = set(self._load_committed_history(output_state_dir))
            business_records, working_history = self._repair_stale_archive_ledger(
                save_path, output_state_dir, business_records, working_history
            )
        sidecar = {}
        sidecar_lock = threading.Lock()
        self._pipeline_sidecar = sidecar
        trace_store = self._create_document_trace_store(
            output_path=(
                None
                if dry_run
                else self._run_context.get("debug_trace_path") or None
            )
        )
        for candidate in candidates:
            trace_store.start_document(
                source_filename=candidate.source_filename,
                source_path=candidate.source_path,
                document_id=candidate.identity.document_id,
                persistence_is_url=candidate.identity.source_kind == "url",
            )
        if not dry_run:
            self._mark_output_run_state(output_state_dir, "running")

        worker_factory = _worker_extractor_factory
        if worker_factory is None:
            def worker_factory(_runtime):
                # No-API recognition: extract_remote_only runs the local
                # parser + OCR engine, never a remote model request.
                return InvoiceExtractor(
                    api_key=api_key,
                    output_dir=save_path,
                    glm_runtime=_runtime,
                    close_glm_runtime=False,
                    local_recognition_only=True,
                )

        preflight = CandidatePreflight(
            api=self,
            extractor=_extractor,
            working_history=working_history,
            sidecar=sidecar,
            sidecar_lock=sidecar_lock,
            converter_factory=lambda: BoundedUrlRecoveryClient(
                staging_dir=self._active_staging_path(), timeout_ms=30000
            ),
            prepare_remote_images=_prepare_remote_images,
        )
        remote = SharedRuntimeRemoteExtractor(
            owner_extractor=_extractor,
            sidecar=sidecar,
            sidecar_lock=sidecar_lock,
            worker_factory=worker_factory,
            custom_rules=rules_text,
            since_date=since_date,
            before_date=before_date,
        )

        def _progress(completed, total, percent):
            self.progress = min(90, 45 + int(percent * 0.45))
            self.status_text = f"正在解析发票 ({completed}/{total})..."
            self._safe_emit_stage_event(
                "extraction_pipeline",
                "progress",
                {"completed": completed, "total": total, "percent": percent},
            )

        def _trace(event):
            trace_store.set_fields(event["document_id"], extraction_result=dict(event))
            self._safe_emit_stage_event("extraction_pipeline", "trace", dict(event))

        adapter = AppArchiveAdapter(
            api=self,
            extractor=_extractor,
            save_path=save_path,
            business_records=business_records,
            trace_store=trace_store,
            pairing_finalizer=_pairing_finalizer,
            dry_run=dry_run,
            flat_layout=bool(_flat_layout),
        )
        archive_service = ArchiveService(
            normalizer=adapter.normalize,
            classifier=adapter.classify,
            archive_operation=_archive_operation or adapter.archive_operation,
            dedupe_key=adapter.dedupe_key,
            existing_dedupe_keys=business_records.keys(),
            finalizer=adapter.finalize,
            event_sink=lambda event: self._safe_emit_stage_event(
                "archive_service", "artifact", event
            ),
        )

        pipeline = ExtractionPipeline(
            local_parser=preflight,
            remote_extractor=remote,
            max_workers=2,
            verified_ceiling=remote.verified_ceiling,
            stop_requested=lambda: bool(getattr(self, "_stop_requested", False)),
            progress_callback=_progress,
            trace_sink=_trace,
        )
        url_recovery_scheduler = DeferredUrlRecoveryScheduler(
            max_workers=DEFAULT_URL_RECOVERY_MAX_WORKERS,
            stop_requested=lambda: bool(getattr(self, "_stop_requested", False)),
            progress_callback=_progress,
        )
        return _ProcessingPipelineSession(
            api=self,
            candidates=candidates,
            pipeline=pipeline,
            archive_service=archive_service,
            save_path=save_path,
            output_state_dir=output_state_dir,
            working_history=working_history,
            business_records=business_records,
            sidecar=sidecar,
            trace_store=trace_store,
            owned_extractor=_owned_extractor,
            provider_retry_delay_seconds=20.0,
            url_recovery_scheduler=url_recovery_scheduler,
            dry_run=dry_run,
        )

    def _retain_artifact(self, save_path, source_path, bucket, reason, metadata=None):
        """在 staging 清理前保留一份可追踪的原件副本。"""
        import json
        import shutil
        import uuid

        retention_dir = os.path.join(save_path, "_audit_retention", bucket)
        os.makedirs(retention_dir, exist_ok=True)
        runtime_metadata = dict(metadata or {})
        safe_metadata = self._sanitize_url_persistence_payload(runtime_metadata)

        is_url_placeholder = (
            runtime_metadata
            and (
                runtime_metadata.get("source_kind") == "url"
                or str(source_path).startswith(("http://", "https://"))
            )
            and (not source_path or not os.path.exists(source_path))
        )
        batched_url_retention = bool(
            is_url_placeholder
            and bucket == "pipeline_retained"
            and str(runtime_metadata.get("candidate_action") or "") == "retain_only"
            and not str(runtime_metadata.get("provider_family") or "").strip()
        )

        if is_url_placeholder:
            url_evidence = build_url_evidence(source_path, bucket)
            if batched_url_retention:
                target_path = os.path.join(retention_dir, "url_retention_index.jsonl")
            else:
                candidate_index = int(runtime_metadata.get("candidate_index", 1) or 1)
                original_name = (
                    f"LinkRetention_{url_evidence['source_hash'][:16]}_"
                    f"{candidate_index}.url.txt"
                )
                target_name = original_name
                target_path = os.path.join(retention_dir, target_name)
                while os.path.exists(target_path):
                    stem, ext = os.path.splitext(original_name)
                    target_name = f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
                    target_path = os.path.join(retention_dir, target_name)
                with open(target_path, "w", encoding="utf-8") as fh:
                    json.dump(url_evidence, fh, ensure_ascii=False, indent=2)
        else:
            if not source_path or not os.path.exists(source_path):
                return source_path

            original_name = os.path.basename(source_path)
            target_name = original_name
            target_path = os.path.join(retention_dir, target_name)
            while os.path.exists(target_path):
                stem, ext = os.path.splitext(original_name)
                target_name = f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
                target_path = os.path.join(retention_dir, target_name)

            shutil.copy2(source_path, target_path)

        payload = {
            "kind": "retention",
            "status": "retained",
            "reason_code": str(bucket),
            "reason_hash": stable_hash(reason),
            "source_hash": stable_hash(
                source_path if is_url_placeholder else self._user_safe_source_reference(source_path)
            ),
            "retained_name_hash": stable_hash(os.path.basename(target_path)),
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if is_url_placeholder:
            payload.update(url_evidence)
        if safe_metadata:
            payload["metadata"] = safe_metadata

        if batched_url_retention:
            with self._url_retention_ledger_lock:
                with open(target_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                    fh.write("\n")
        else:
            sidecar = f"{target_path}.json"
            try:
                with open(sidecar, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2)
            except Exception as exc:
                print(f"Failed to write retention sidecar {sidecar}: {exc}")

        self.audit_counts["retention"] = int(self.audit_counts.get("retention", 0) or 0) + 1
        self._safe_emit_artifact_event(
            "retention",
            os.path.basename(target_path),
            document_id=safe_metadata.get("document_hash"),
            source_kind=safe_metadata.get("source_kind"),
            reason_code=safe_metadata.get("prefilter_reason_code") or bucket,
            category=bucket,
            extra={
                "bucket": bucket,
                "retention_reason_hash": stable_hash(reason),
                "metadata": safe_metadata,
            },
        )

        return target_path

    def _send_to_manual_check(self, save_path, source_path, reason, metadata=None, is_url=False):
        """把待人工复核候选写入用户输出目录下的中文复核目录。"""
        import json
        import shutil
        import uuid

        manual_dir = os.path.join(save_path, MANUAL_REVIEW_FOLDER)
        has_local_file = bool(source_path and os.path.isfile(source_path))
        is_url_placeholder = is_url and not has_local_file
        if is_url_placeholder and not str(source_path).startswith(("http://", "https://")):
            raise FileNotFoundError("Downloaded manual-review artifact is missing")
        if is_url and has_local_file:
            staging = os.path.realpath(self._active_staging_path())
            source = os.path.realpath(source_path)
            if os.path.commonpath((staging, source)) != staging:
                raise ValueError("Downloaded manual-review artifact is outside run staging")
            was_preserved = self._preserved_staging_dir == staging
            self._preserved_staging_dir = staging

        try:
            os.makedirs(manual_dir, exist_ok=True)
        except OSError:
            if is_url and has_local_file:
                self._append_log("错误", f"人工复核副本保存失败，下载原件已保留：{source}", "text-error")
            raise
        runtime_metadata = dict(metadata or {})
        safe_metadata = self._sanitize_url_persistence_payload(runtime_metadata)

        def _unique_path(filename):
            target_path = os.path.join(manual_dir, filename)
            while os.path.exists(target_path):
                stem, ext = os.path.splitext(filename)
                filename_local = f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
                target_path = os.path.join(manual_dir, filename_local)
                filename = filename_local
            return target_path

        if is_url_placeholder:
            url_evidence = build_url_evidence(source_path, reason)
            candidate_index = int(runtime_metadata.get("candidate_index", 1) or 1)
            target_path = _unique_path(
                f"P0_LinkReview_{url_evidence['source_hash'][:16]}_"
                f"{candidate_index}.url.txt"
            )
            with open(target_path, "w", encoding="utf-8") as fh:
                json.dump(url_evidence, fh, ensure_ascii=False, indent=2)
        else:
            if not source_path or not os.path.exists(source_path):
                return source_path
            original_name = os.path.basename(source_path)
            prefix = "P0_Review"
            if runtime_metadata.get("file_name") and not is_url:
                original_name = os.path.basename(str(runtime_metadata["file_name"]))
            target_path = _unique_path(f"{prefix}_{original_name}")
            try:
                shutil.copy2(source_path, target_path)
            except OSError:
                if is_url and has_local_file:
                    self._append_log(
                        "错误",
                        f"人工复核副本保存失败，下载原件已保留：{source}",
                        "text-error",
                    )
                if os.path.exists(target_path):
                    try:
                        os.remove(target_path)
                    except OSError:
                        pass
                raise
            if is_url and has_local_file and not was_preserved:
                self._preserved_staging_dir = None

        sidecar = f"{target_path}.json"
        payload = {
            "kind": "manual_check",
            "status": "pending_review",
            "reason_hash": stable_hash(reason),
            "source_hash": stable_hash(
                source_path if is_url_placeholder else self._user_safe_source_reference(source_path)
            ),
            "review_name_hash": stable_hash(os.path.basename(target_path)),
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "is_url": is_url,
        }
        if is_url_placeholder:
            payload.update(url_evidence)
        if safe_metadata:
            payload["metadata"] = safe_metadata

        try:
            with open(sidecar, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"Failed to write manual-check sidecar {sidecar}: {exc}")

        self.audit_counts["manual_check"] = int(self.audit_counts.get("manual_check", 0) or 0) + 1
        self._safe_emit_artifact_event(
            "manual_check",
            os.path.basename(target_path),
            document_id=safe_metadata.get("document_hash"),
            source_kind=safe_metadata.get("source_kind"),
            reason_code="manual_review",
            category=MANUAL_REVIEW_FOLDER,
            extra={
                "is_url": bool(is_url),
                "reason_hash": stable_hash(reason),
                "metadata": safe_metadata,
            },
        )

        return target_path

    def _cwt_cancellation_matching(self, save_path):
        """CWT 取消撮合: 根据取消知会中的人名，在已归档的住宿确认单中寻找匹配的预订，
        将匹配的预订也移入待人工复核，并在 sidecar 中注明撮合关系。"""
        import re
        import shutil
        import json

        cancellations = getattr(self, '_cwt_cancellation_registry', [])
        if not cancellations:
            return {}
        moved_paths = {}

        # 从取消知会文件名中提取人名
        # 格式: 酒店预定取消知会-{name}-{date}入住-{city} (CONNECT 订单号：{order}).pdf
        cancel_pattern = re.compile(r'取消知会[_\-]?(\S+?)[_\-]\d')

        manual_dir = os.path.join(save_path, MANUAL_REVIEW_FOLDER)
        hotel_dir = os.path.join(save_path, "住宿发票")

        for cancel in cancellations:
            cancel_fn = cancel.get("file_name", "")
            m = cancel_pattern.search(cancel_fn)
            if not m:
                continue
            person_name = m.group(1)
            if not person_name or len(person_name) < 2:
                continue

            # 搜索住宿发票目录中匹配此人名的住宿确认单
            if not os.path.isdir(hotel_dir):
                continue
            for fn in os.listdir(hotel_dir):
                if person_name in fn and "酒店" in fn.lower():
                    src = os.path.join(hotel_dir, fn)
                    dst = os.path.join(manual_dir, f"P0_CancelMatch_{fn}")
                    if os.path.exists(dst):
                        continue
                    os.makedirs(manual_dir, exist_ok=True)
                    shutil.move(src, dst)
                    moved_paths[src] = dst
                    # 写 sidecar
                    sidecar = {
                        "reason": "CWT_CANCELLATION_MATCH",
                        "matched_cancellation": cancel_fn,
                        "matched_person": person_name,
                        "original_path": self._user_safe_source_reference(src),
                        "review_path": dst,
                        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    try:
                        with open(f"{dst}.json", "w", encoding="utf-8") as fh:
                            json.dump(sidecar, fh, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    self.logs.append({"time": time.strftime("[%H:%M:%S]"), "type": "撮合:", "color": "text-amber-400", "msg": f"匹配到取消对应的预订: {fn} ↔ {cancel_fn}"})
        return moved_paths

    def _record_error_log(
        self,
        save_path,
        email_title,
        error_reason,
        *,
        url_candidate_info=None,
    ):
        """记录错误日志到对应的 csv 文件中"""
        import os
        import csv
        
        # 目录保护
        if not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)
            
        if url_candidate_info:
            email_title = self._url_candidate_label(url_candidate_info)
            error_reason = f"URL_CANDIDATE_ERROR:{stable_hash(error_reason)[:16]}"

        log_file = os.path.join(save_path, "异常发票处理日志.csv")
        file_exists = os.path.exists(log_file)
        
        try:
            with open(log_file, 'a', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = ['处理时间', '邮件标题', '错误原因']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    '处理时间': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    '邮件标题': email_title,
                    '错误原因': error_reason
                })
        except Exception as e:
            print(f"Failed to write error log: {e}")

    def _cleanup_temp_folders(self, staging_dir=None, temp_dir=None):
        """自动清理程序执行过程中产生的临时文件夹"""
        import shutil

        if staging_dir is None and self._active_run_handle is not None:
            staging_dir = self._active_run_handle.staging_dir
        if temp_dir is None:
            temp_dir = self._active_temp_dir
        temp_paths = [staging_dir, temp_dir]
        failures = []

        for target_path in temp_paths:
            if not target_path or not os.path.exists(target_path) or not os.path.isdir(target_path):
                continue
            if staging_dir and os.path.realpath(target_path) == self._preserved_staging_dir:
                continue
            try:
                shutil.rmtree(target_path)
                print(f"Cleaned up temp folder: {target_path}")
            except Exception as e:
                failure_id = stable_hash(f"{type(e).__name__}:{e}")[:12]
                print(f"Failed to clean temporary folder [{failure_id}]")
                self.logs.append({
                    "time": time.strftime("[%H:%M:%S]"),
                    "type": "ERROR",
                    "color": "text-error",
                    "msg": f"Failed to clean temporary folder [{failure_id}]",
                })
                failures.append((type(e).__name__, failure_id))
        if failures:
            exc_type, failure_id = failures[0]
            raise RuntimeError(f"cleanup failed:{exc_type}:{failure_id}:count={len(failures)}")

    def _start_async_finalizers(self, fetcher=None):
        handle = self._active_run_handle or self._prepare_run_lifecycle()
        if handle.state not in {RunState.FINALIZING, RunState.COMPLETED, RunState.FAILED}:
            handle.advance(RunState.REPORTING)
        if self.run_state != "finalizing":
            self._mark_finalizing()
        self._safe_emit_stage_event("cleanup_finalize", "enter")
        staging_dir = handle.staging_dir
        temp_dir = self._active_temp_dir
        callbacks = [("report", self._await_truth_audit)]
        if fetcher is not None:
            callbacks.append(("disconnect", fetcher.disconnect))
        callbacks.append(
            (
                "cleanup",
                lambda: self._cleanup_temp_folders(staging_dir=staging_dir, temp_dir=temp_dir),
            )
        )
        state = handle.finalize(callbacks)
        self._safe_emit_stage_event(
            "cleanup_finalize",
            "exit",
            {"result": "failed" if state is RunState.FAILED else "completed"},
        )
        return state

    def _mark_finalizing(self):
        finalizing_progress = self.progress if self.progress >= 95 else 99
        self._set_run_state("finalizing", status_text="正在收尾...", progress=finalizing_progress)

    def _fail_run(
        self,
        status_text,
        error_message,
        fetcher=None,
        include_traceback=False,
        reason_code="",
        user_message="",
    ):
        active_exc = sys.exc_info()[1]
        self._packaged_diag_write(
            "fail_run",
            "_fail_run",
            "exception" if active_exc is not None else "failure",
            summary={"include_traceback": bool(include_traceback)},
            exc=active_exc,
        )
        handle = self._active_run_handle
        if handle is None:
            handle = self._prepare_run_lifecycle()
        if not reason_code or not user_message:
            inferred_code, inferred_message = self._safe_failure_contract(status_text, error_message)
            reason_code = reason_code or inferred_code
            user_message = user_message or inferred_message
        handle.fail(
            active_exc or RuntimeError(error_message or reason_code),
            reason_code=reason_code,
            user_message=user_message,
        )
        self._mark_finalizing()
        self._start_async_finalizers(fetcher)

        self.logs.append({
            "time": time.strftime("[%H:%M:%S]"),
            "type": "ERROR",
            "color": "text-error",
            "msg": f"System exception: {handle.error}",
        })
        self._finish_run(False, status_text, last_error=handle.error)

    def _validate_date_range(self, date_from, date_to):
        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        if date_from and not date_pattern.match(str(date_from)):
            return "开始日期格式必须为 YYYY-MM-DD"
        if date_to and not date_pattern.match(str(date_to)):
            return "结束日期格式必须为 YYYY-MM-DD"
        if date_from and date_to and date_from > date_to:
            return "开始日期不能晚于结束日期"
        return ""

    def _manual_check_path(self):
        base_path = self._effective_save_path or self._requested_save_path or self.get_default_save_path()
        return os.path.join(base_path, MANUAL_REVIEW_FOLDER)

    def _build_error_breakdown(self):
        breakdown = {
            "manual_review": 0,
            "retained_record": 0,
            "processing_error": 0,
        }
        reason_codes = {}

        for item in list(self.error_invoices):
            group_key, _group_label = self._classify_error_invoice(item)
            if group_key not in breakdown:
                group_key = "processing_error"
            breakdown[group_key] += 1
            reason_code = str((item or {}).get("reason", "") or "").strip()
            if reason_code:
                reason_codes[reason_code] = int(reason_codes.get(reason_code, 0) or 0) + 1

        breakdown["reason_codes"] = reason_codes
        return breakdown

    def _summarize_stats(self):
        breakdown = self._build_error_breakdown()
        manual_review_count = max(
            int(breakdown.get("manual_review", 0) or 0),
            int(self.audit_counts.get("manual_check", 0) or 0),
        )
        retention_count = max(
            int(breakdown.get("retained_record", 0) or 0),
            int(self.audit_counts.get("retention", 0) or 0),
        )
        classification_counts: dict[str, int] = {}
        classification_sources: dict[str, int] = {}
        unclassified_count = 0
        dictionary_hit_count = 0

        def add_classification(row, *, unknown=False):
            nonlocal unclassified_count, dictionary_hit_count
            name = str((row or {}).get("category") or "").strip() or "未分类"
            if not unknown:
                classification_counts[name] = (
                    int(classification_counts.get(name, 0) or 0) + 1
                )
            source = (
                "unknown"
                if unknown
                else str((row or {}).get("classification_source") or "builtin").strip()
                or "builtin"
            )
            classification_sources[source] = (
                int(classification_sources.get(source, 0) or 0) + 1
            )
            if unknown:
                unclassified_count += 1
            if source == "dictionary":
                dictionary_hit_count += 1

        for row in list(self.processed_invoices):
            add_classification(row)
        for row in list(self.error_invoices):
            if str((row or {}).get("reason") or "").strip() == "CLASSIFICATION_UNKNOWN":
                add_classification(row, unknown=True)

        classification_counts = dict(
            sorted(classification_counts.items(), key=lambda item: (-item[1], item[0]))
        )
        classification_sources = dict(
            sorted(classification_sources.items(), key=lambda item: (-item[1], item[0]))
        )
        return {
            "emails": int(self.stats.get("emails", 0) or 0),
            "success_count": len(self.processed_invoices),
            "error_count": len(self.error_invoices),
            "manual_check_count": manual_review_count,
            "retention_count": retention_count,
            "raw_invoice_count": int(self.audit_counts.get("raw_invoices", 0) or 0),
            "processing_error_count": int(breakdown.get("processing_error", 0) or 0),
            "classification_breakdown": classification_counts,
            "classification_source_breakdown": classification_sources,
            "unclassified_count": unclassified_count,
            "dictionary_hit_count": dictionary_hit_count,
            "result_breakdown": {
                "manual_review": manual_review_count,
                "retained_record": retention_count,
                "processing_error": int(breakdown.get("processing_error", 0) or 0),
            },
            "reason_code_breakdown": breakdown.get("reason_codes", {}),
            "timing_breakdown": self._build_timing_breakdown(),
            "quota_exhausted": bool(self.quota_exhausted),
            "quota_message": self.quota_message,
            "run_state": self.run_state,
            "status_text": self.status_text,
        }

    def _classify_error_invoice(self, item):
        path = str((item or {}).get("path", "") or "")
        artifact_kind = str((item or {}).get("artifact_kind", "") or "").strip().lower()
        status = str((item or {}).get("status", "") or "")
        reason = str((item or {}).get("reason", "") or "")
        category = str((item or {}).get("category", "") or "")
        merchant = str((item or {}).get("merchant", "") or "")
        normalized = " ".join([path, status, reason, category, merchant]).lower()
        normalized_path = path.replace("\\", "/").lower()

        if artifact_kind == "manual_check" or "/manual_check/" in normalized_path or f"/{MANUAL_REVIEW_FOLDER.lower()}/" in normalized_path:
            return "manual_review", "待人工复核"
        if artifact_kind == "retention" or "/_audit_retention/" in normalized_path:
            return "retained_record", "保留记录"
        if "manual_check" in normalized or "人工复核" in normalized or "待人工复核" in normalized:
            return "manual_review", "待人工复核"
        if any(token in normalized for token in [
            "_audit_retention",
            "controlled_run_non_provider_url",
            "history_skipped",
            "prefilter_b_retained",
            "provider_recovery_failed",
            "url_non_invoice_page_skipped",
            "model_rejected",
            "受控跑批保全",
            "已保全待判断",
            "保全",
            "保留",
            "retention",
        ]):
            return "retained_record", "保留记录"
        if any(token in normalized for token in [
            "url_page_timeout",
            "url_auth_wall_detected",
            "url_no_response",
            "url_download_failed",
            "链接下载失败",
        ]):
            return "processing_error", "真实处理异常"
        if self._resolve_quota_message(normalized):
            return "processing_error", "真实处理异常"
        if any(token in normalized for token in [
            "processing_errors",
            "处理中断遗漏",
            "pipeline 断层遗漏",
            "系统遗漏",
            "处理单张票据时抛出异常",
            "异常",
            "failed",
            "error",
        ]):
            return "processing_error", "真实处理异常"
        return "processing_error", "真实处理异常"

    def _group_error_invoices(self):
        grouped = {}
        for item in list(self.error_invoices):
            group_key, group_label = self._classify_error_invoice(item)
            group = grouped.setdefault(group_key, {"key": group_key, "label": group_label, "count": 0, "items": []})
            enriched = dict(item)
            enriched["groupKey"] = group_key
            enriched["groupLabel"] = group_label
            group["items"].append(enriched)
            group["count"] += 1
        return list(grouped.values())

    def stop_processing(self):
        if self.run_state == "finalizing":
            return {"success": False, "message": "任务正在收尾，请稍候"}
        if not self._is_running or not (self._worker_thread and self._worker_thread.is_alive()):
            return {"success": False, "message": "当前没有正在运行的任务"}
        self._request_safe_stop()
        return {"success": True, "message": "已收到停止指令，当前文件处理完成后将结束任务"}

    def close_window(self):
        try:
            import webview
        except ImportError:
            return {"success": False, "message": "桌面窗口接口不可用"}

        if not webview.windows:
            return {"success": False, "message": "当前没有可关闭的桌面窗口"}

        window = webview.windows[0]

        def _shutdown():
            try:
                window.destroy()
            finally:
                time.sleep(0.15)
                os._exit(0)

        threading.Thread(target=_shutdown, daemon=True).start()
        return {"success": True, "message": "窗口关闭中"}

    def _active_desktop_window(self, action_label):
        try:
            import webview
        except ImportError:
            return None, {"success": False, "message": "桌面窗口接口不可用"}

        if not webview.windows:
            return None, {"success": False, "message": f"当前没有可{action_label}的桌面窗口"}
        return webview.windows[0], None

    def minimize_window(self):
        window, error = self._active_desktop_window("最小化")
        if error:
            return error

        try:
            window.minimize()
            return {"success": True, "message": "窗口已最小化"}
        except Exception as exc:
            return {"success": False, "message": f"窗口最小化失败: {exc}"}

    def maximize_window(self):
        window, error = self._active_desktop_window("最大化")
        if error:
            return error

        try:
            window.maximize()
            return {"success": True, "message": "窗口已最大化"}
        except Exception as exc:
            return {"success": False, "message": f"窗口最大化失败: {exc}"}

    def open_manual_check_folder(self):
        manual_path = self._manual_check_path()
        return self.open_folder(manual_path)

    def start_fetch_only(
        self, save_path, date_from=None, date_to=None, email_address=None, auth_code=None
    ):
        """Feature ①: extract attachments into inbox/ + manifest.jsonl only."""
        if (
            not self._run_lifecycle.can_begin
            or self._is_running
            or (self._worker_thread and self._worker_thread.is_alive())
        ):
            return {"success": False, "message": "任务已在运行中"}
        if not email_address or not auth_code:
            return {"success": False, "message": "缺少必要凭证，请填写邮箱地址和授权码"}

        candidate, secrets, date_error = self._build_admission_candidate(
            rules_text="",
            save_path=save_path,
            date_from=date_from,
            date_to=date_to,
            email_address=email_address,
            auth_code=auth_code,
            api_key="",
            ai_provider="glm",
        )
        if date_error:
            return {"success": False, "message": date_error}
        return self._admit_processing_run(
            candidate=candidate, secrets=secrets, fetch_only=True
        )

    def get_processed_records(self):
        """前端数据分析页面调用，获取已处理的账单或发票记录"""
        self._sync_run_state_store_from_legacy()
        return self._run_state_store.snapshot()["processed_invoices"]

    def get_progress(self):
        """前端轮询进度条和日志调用"""
        self._sync_run_state_store_from_legacy()
        payload = self._run_state_store.frontend_snapshot(
            build_identity=self.build_identity,
            raw_date_range=self._raw_date_range_display,
            imap_query_range=self._imap_query_range_display,
        )
        payload["task_mode"] = str(getattr(self, "_active_task_mode", "mail") or "mail")
        payload["dry_run"] = bool(
            payload["task_mode"] == "local"
            and (getattr(self, "_last_organize_result", None) or {}).get("dry_run")
        )
        self._packaged_diag_log_progress_poll(payload)
        return payload

    def get_results(self):
        """前端分析页调用，获取最终的统计数据"""
        self._sync_run_state_store_from_legacy()
        state_snapshot = self._run_state_store.snapshot()
        processed_invoices = state_snapshot["processed_invoices"]
        error_invoices = state_snapshot["error_invoices"]
        categories = state_snapshot["new_categories"]
        grouped_errors = self._group_error_invoices()
        summary = self._summarize_stats()
        return {
            "categories": categories,
            "successInvoices": processed_invoices,
            "errorInvoices": error_invoices,
            "groupedErrorInvoices": grouped_errors,
            "manual_check_path": self._manual_check_path(),
            "output_path": self._effective_save_path or self._requested_save_path or self.get_default_save_path(),
            "summary": summary,
            "build_identity": self.build_identity,
            "raw_date_range": self._raw_date_range_display,
            "imap_query_range": self._imap_query_range_display,
            "resultBreakdown": summary.get("result_breakdown", {}),
            "reasonCodeBreakdown": summary.get("reason_code_breakdown", {}),
            "quota_exhausted": self.quota_exhausted,
            "quota_message": self.quota_message,
            "last_export_path": self._last_export_path,
            "task_mode": str(getattr(self, "_active_task_mode", "mail") or "mail"),
            "dry_run": bool(
                getattr(self, "_active_task_mode", "mail") == "local"
                and (self._last_organize_result or {}).get("dry_run")
            ),
            "input_dir": str((self._last_organize_result or {}).get("input_dir") or ""),
            "fetch_summary": dict(getattr(self, "_last_fetch_summary", {}) or {}),
            "organize_summary": dict(getattr(self, "_last_organize_result", None) or {}),
            "invoices": processed_invoices # 兼容旧的数据结构
        }

    def get_results_delta(self, since_success=0, since_error=0):
        """Incremental results for the analysis page; cursors are list lengths."""
        self._sync_run_state_store_from_legacy()
        header = self._run_state_store.header()
        counts = self._run_state_store.sequence_counts()
        processed_total = counts["processed_invoices"]
        error_total = counts["error_invoices"]
        try:
            start_success = max(0, int(since_success or 0))
            start_error = max(0, int(since_error or 0))
        except (TypeError, ValueError):
            start_success = start_error = 0
        reset = start_success > processed_total or start_error > error_total
        if reset:
            start_success = start_error = 0
        success_invoices = self._run_state_store.slice(
            "processed_invoices", start_success
        )
        error_invoices = self._run_state_store.slice("error_invoices", start_error)
        summary = self._summarize_stats()
        return {
            "run_id": header["run_id"],
            "reset": reset,
            "cursor": {"success": processed_total, "error": error_total},
            "categories": header["new_categories"],
            "successInvoices": success_invoices,
            "errorInvoices": error_invoices,
            "groupedErrorInvoices": self._group_error_invoices(),
            "manual_check_path": self._manual_check_path(),
            "output_path": self._effective_save_path
            or self._requested_save_path
            or self.get_default_save_path(),
            "summary": summary,
            "build_identity": self.build_identity,
            "raw_date_range": self._raw_date_range_display,
            "imap_query_range": self._imap_query_range_display,
            "resultBreakdown": summary.get("result_breakdown", {}),
            "reasonCodeBreakdown": summary.get("reason_code_breakdown", {}),
            "quota_exhausted": self.quota_exhausted,
            "quota_message": self.quota_message,
            "last_export_path": self._last_export_path,
            "task_mode": str(getattr(self, "_active_task_mode", "mail") or "mail"),
            "dry_run": bool(
                getattr(self, "_active_task_mode", "mail") == "local"
                and (self._last_organize_result or {}).get("dry_run")
            ),
            "input_dir": str(
                (self._last_organize_result or {}).get("input_dir") or ""
            ),
            "fetch_summary": dict(getattr(self, "_last_fetch_summary", {}) or {}),
            "organize_summary": dict(
                getattr(self, "_last_organize_result", None) or {}
            ),
            "invoices": success_invoices,
        }

    def choose_directory(self):
        """调用系统原生目录选择器"""
        run_context = self._refresh_run_context()
        if run_context.get("enabled"):
            return {"success": True, "path": run_context.get("output_dir", "")}
        print("Opening directory dialog...")
        import webview
        # webview.windows 列表包含了所有当前活动的窗口，取第一个
        if webview.windows:
            window = webview.windows[0]
            # webview.FOLDER_DIALOG
            result = window.create_file_dialog(webview.FOLDER_DIALOG)
            if result and len(result) > 0:
                print(f"Selected: {result[0]}")
                import os as _os

                try:
                    self._approved_bridge_directories().add(_os.path.realpath(result[0]))
                except OSError:
                    pass
                return {"success": True, "path": result[0]}
        return {"success": False}

    def _approved_bridge_directories(self):
        approved = getattr(self, "_approved_directories", None)
        if approved is None:
            approved = set()
            self._approved_directories = approved
        return approved

    def _bridge_allowed_roots(self):
        """Directories the page bridge may touch (defense-in-depth for js_api)."""
        import os

        roots: list[str] = []
        run_context = self._run_context if isinstance(self._run_context, dict) else {}
        for value in (
            self._effective_save_path,
            self._requested_save_path,
            run_context.get("output_dir"),
            run_context.get("run_root"),
            self.get_default_save_path(),
            self._last_export_path,
        ):
            text = str(value or "").strip()
            if not text:
                continue
            try:
                if os.path.isfile(text):
                    text = os.path.dirname(text)
                roots.append(os.path.realpath(text))
            except OSError:
                continue
        for extra in (self._active_staging_path, self._manual_check_path):
            try:
                roots.append(os.path.realpath(extra()))
            except Exception:
                continue
        roots.extend(self._approved_bridge_directories())
        return [root for root in roots if root]

    def _bridge_path_is_allowed(self, path):
        """Reject UNC/traversal and anything outside the app's own output trees."""
        import os

        text = str(path or "").strip()
        if not text:
            return False
        if text.startswith("\\\\") or text.startswith("//"):
            return False
        try:
            resolved = os.path.realpath(os.path.abspath(text))
        except (OSError, ValueError):
            return False
        if not os.path.isabs(resolved):
            return False
        for root in self._bridge_allowed_roots():
            try:
                if os.path.commonpath([resolved, root]) == root:
                    return True
            except (ValueError, OSError):
                continue
        return False

    def _bridge_path_rejects_unc_or_traversal(self, path):
        """Reject network shares and '..' traversal for page-supplied write paths."""
        import os

        text = str(path or "").strip()
        if not text:
            return False
        if text.startswith("\\\\") or text.startswith("//"):
            return True
        return ".." in os.path.normpath(text).split(os.sep)

    def open_folder(self, path):
        """调用系统资源管理器打开特定文件夹"""
        import os
        import platform
        import subprocess

        # 确保存储的路径分隔符是环境兼容的
        path = os.path.normpath(str(path or ""))
        print(f"Opening folder: {path}")

        if not self._bridge_path_is_allowed(path):
            return {"success": False, "message": "该目录不在允许访问的范围内"}

        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                 return {"success": False, "message": f"无法创建目录: {str(e)}"}

        try:
            if platform.system() == "Windows":
                # Windows：推荐采用 subprocess.Popen 或者 os.startfile 这里采用 explorer 确保前台弹出
                subprocess.Popen(f'explorer "{path}"')
            elif platform.system() == "Darwin":
                # macOS
                subprocess.Popen(["open", path])
            else:
                # Linux
                subprocess.Popen(["xdg-open", path])
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def view_invoice(self, path):
        """在系统默认查看器中打开单张发票或图片"""
        print(f"Viewing invoice: {path}")
        import os
        import platform
        import subprocess

        path = os.path.normpath(str(path or ""))
        if not self._bridge_path_is_allowed(path):
            return {"success": False, "message": "该文件不在允许访问的范围内"}
        if not os.path.exists(path):
            return {"success": False, "message": "文件不存在"}
            
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return {"success": True, "message": "已在外部程序中打开文件"}
        except Exception as e:
            return {"success": False, "message": f"打开失败: {str(e)}"}

    def export_run_summary(self, export_path=""):
        target_dir = (
            export_path
            or self._effective_save_path
            or self._requested_save_path
            or self.get_default_save_path()
        )
        if export_path and self._bridge_path_rejects_unc_or_traversal(export_path):
            return {"success": False, "message": "导出目录不可用"}
        os.makedirs(target_dir, exist_ok=True)
        export_file = write_result_detail_workbook(
            target_dir,
            self.processed_invoices,
            self._group_error_invoices(),
        )
        if export_file is None:
            return {"success": False, "message": "缺少 openpyxl 依赖，无法导出 Excel"}
        self._last_export_path = export_file
        return {"success": True, "message": "结果明细已导出", "path": export_file}


if __name__ == "__main__":
    # 提供 CLI 测试入口
    print(">>> [测试入口] 从终端直接启动 app_api.py")
    app = InvoiceAppAPI()
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(">>> 退出程序。")

"""Run admission and dependency assembly extracted from InvoiceAppAPI."""

from __future__ import annotations

import errno
import imaplib
import json
import os
import re
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app_services.errors import (
    ImapCertificateError,
    ImapLoginError,
    ImapTimeoutError,
    ProcessingLoopFailure,
    QuotaExhaustedError,
    RemoteAuthError,
)
from brand_generated import TEMP_DIR_PREFIX, THREAD_NAME_WORKER
from email_channel import is_supported_email, resolve_channel
from frontend_run_context import ensure_run_context_dirs, load_run_context
from glm_runtime import DEEPSEEK_PROVIDER, normalize_provider
from report_service import ReportService
from run_coordinator import RunDependencies, RunImapCancelled, RunRequest
from run_lifecycle import RunState
from run_state_store import RunStateStore
from url_trace_sanitizer import stable_hash
from user_settings import get_default_save_path as resolve_default_save_path


@dataclass(frozen=True)
class _RunAdmissionCandidate:
    rules_text: str
    requested_save_path: str
    effective_save_path: str
    date_from: str
    date_to: str
    account_id: str
    channel_id: str
    email_domain: str
    run_context_json: str
    started_at: str

    def run_context(self):
        return json.loads(self.run_context_json)


class _RunAdmissionSecrets:
    __slots__ = ("email_address", "auth_code", "api_key", "ai_provider")

    def __init__(self, email_address, auth_code, api_key, ai_provider="glm"):
        self.email_address = str(email_address or "")
        self.auth_code = str(auth_code or "")
        self.api_key = str(api_key or "")
        self.ai_provider = normalize_provider(ai_provider)

    def __repr__(self):
        return "_RunAdmissionSecrets(<process-only redacted>)"


class AdmissionMixin:
    def _build_run_dependencies(
        self,
        request,
        *,
        email_address,
        auth_code,
        api_key,
        ai_provider="glm",
        fetch_only=False,
    ):
        from datetime import datetime, timedelta
        import inspect

        provider = normalize_provider(ai_provider)

        from email_fetcher import EmailFetcher
        from invoice_extractor import InvoiceExtractor
        from mailbox_scanner import MailboxScanError
        from run_evidence import RunEvidenceWriter

        resources = {"fetcher": None, "pipeline": None}

        def cancelled_imap_abort(fetcher, exc):
            handle = self._active_run_handle
            if (
                not self._stop_requested
                or self._imap_abort_run_id != request.run_id
                or handle is None
                or handle.run_id != request.run_id
                or self._active_fetcher is not fetcher
            ):
                return False
            if isinstance(exc, MailboxScanError):
                exc = exc.__cause__
            return isinstance(exc, (
                ConnectionAbortedError, ConnectionResetError, BrokenPipeError,
                imaplib.IMAP4.abort, ssl.SSLEOFError, ssl.SSLZeroReturnError,
            )) or (
                isinstance(exc, OSError)
                and not isinstance(exc, TimeoutError)
                and exc.errno in {errno.EBADF, errno.ENOTCONN, errno.ECONNRESET, errno.EPIPE}
            )

        account_label = f"{request.channel_id}:{request.account_id}"

        def sanitize_runtime_message(message):
            text = str(message or "")
            replacements = {
                str(email_address or ""): account_label,
                str(auth_code or ""): "[redacted-auth]",
                str(api_key or ""): "[redacted-api-key]",
            }
            for sensitive, replacement in replacements.items():
                if sensitive:
                    text = re.sub(re.escape(sensitive), replacement, text, flags=re.IGNORECASE)
            return text

        def connect(_request):
            channel = resolve_channel(email_address)
            fetcher = EmailFetcher(
                email_address,
                auth_code,
                imap_server=channel["imap_host"],
                imap_port=channel["imap_port"],
                staging_dir=self._active_staging_path(),
                monitoring_dir=self._run_context.get("monitoring_dir"),
                progress_callback=lambda message: self._on_email_fetcher_progress(
                    sanitize_runtime_message(message)
                ),
            )
            resources["fetcher"] = fetcher
            self._active_fetcher = fetcher
            self._append_log(
                "运行",
                f"正在连接邮箱通道 {request.channel_id}（账户 {request.account_id}）...",
                "text-blue-400",
            )
            if not fetcher.connect():
                if cancelled_imap_abort(fetcher, getattr(fetcher, "connection_error", None)):
                    raise RunImapCancelled(request.run_id)
                if getattr(fetcher, "certificate_error", False):
                    raise ImapCertificateError("IMAP_TLS_CERTIFICATE_INVALID")
                if getattr(fetcher, "timeout_error", False):
                    raise ImapTimeoutError("IMAP_CONNECTION_TIMEOUT")
                raise ImapLoginError("IMAP_LOGIN_FAILED")
            return fetcher

        def scan(fetcher, _request):
            since_date = request.date_from or (
                datetime.now() - timedelta(days=30)
            ).strftime("%Y-%m-%d")
            before_date = (
                datetime.strptime(request.date_to, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d") if request.date_to else (
                datetime.now() + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            self._raw_date_range_display = f"{since_date} -> {request.date_to or since_date}"
            self._imap_query_range_display = f"SINCE {since_date} / BEFORE {before_date}"
            self._coordinator_since_date = since_date
            self._coordinator_before_date = before_date
            self._append_log("运行", f"原始用户范围：{self._raw_date_range_display}", "text-blue-400")
            self._append_log("运行", f"实际 IMAP 查询：{self._imap_query_range_display}", "text-blue-400")
            try:
                email_ids = fetcher.fetch_emails_by_date(
                    since_date=since_date,
                    before_date=before_date,
                )
            except Exception as exc:
                if cancelled_imap_abort(fetcher, exc):
                    raise RunImapCancelled(request.run_id) from exc
                raise
            self.stats["emails"] = len(email_ids)
            self._append_log("信息", f"共匹配到 {len(email_ids)} 封邮件。", "text-emerald-400")
            if self._stop_requested:
                self._sync_run_state_store_from_legacy()
            return email_ids

        def candidate(fetcher_email_ids, _request):
            fetcher = resources["fetcher"]
            self._append_log("运行", "正在下载并提取附件...", "text-blue-400")
            try:
                attachments = fetcher.extract_attachments(fetcher_email_ids)
            except Exception as exc:
                if cancelled_imap_abort(fetcher, exc):
                    raise RunImapCancelled(request.run_id) from exc
                raise
            if fetch_only:
                # Feature ① stops here: save files + manifest, never parse.
                from fetch_only import save_fetch_rows

                summary = save_fetch_rows(
                    request.save_path, list(attachments or []), mailbox="INBOX"
                )
                self._last_fetch_summary = summary.to_dict()
                self._append_log(
                    "信息",
                    (
                        f"已提取 {summary.saved_count} 个附件到 inbox"
                        f"（重复 {summary.duplicate_count} 个，"
                        f"需人工打开链接 {summary.link_count} 个）。"
                    ),
                    "text-emerald-400",
                )
                if summary.warnings:
                    for warning in summary.warnings[:5]:
                        self._append_log("提示", warning, "text-amber-500")
                return []
            self._append_log("信息", f"共提取到 {len(attachments)} 个附件。", "text-emerald-400")
            return attachments

        def extract(attachments, _request):
            if fetch_only:
                return []
            compatibility_hook = self.__dict__.get("_run_processing_loop")
            if callable(compatibility_hook):
                resources["compatibility_report"] = compatibility_hook(
                    attachments,
                    api_key,
                    request.save_path,
                    getattr(self, "_coordinator_since_date", request.date_from),
                    getattr(self, "_coordinator_before_date", request.date_to),
                    request.rules_text,
                )
                self._sync_run_state_store_from_legacy()
                return [resources["compatibility_report"]]
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
            extractor_kwargs = {"api_key": api_key, "output_dir": request.save_path}
            if supports_glm_settings:
                extractor_kwargs["glm_settings"] = self._settings_store.load() or {}
            if supports_ai_provider:
                extractor_kwargs["ai_provider"] = provider
            extractor = InvoiceExtractor(**extractor_kwargs)
            pipeline = self._create_processing_pipeline_session(
                attachments,
                api_key,
                request.save_path,
                getattr(self, "_coordinator_since_date", request.date_from),
                getattr(self, "_coordinator_before_date", request.date_to),
                request.rules_text,
                _extractor=extractor,
                _owned_extractor=extractor,
                _prepare_remote_images=False,
            )
            resources["pipeline"] = pipeline
            return pipeline.extract()

        def archive(outcomes, _request):
            if fetch_only:
                # Feature ① deliberately performs no archiving: the inbox handoff
                # is the final artifact of a fetch-only run.
                return type(
                    "FetchOnlyArchiveReport",
                    (),
                    {
                        "can_complete": True,
                        "archived_count": 0,
                        "retained_count": 0,
                        "manual_count": 0,
                        "unresolved_count": 0,
                        "duplicate_count": 0,
                    },
                )()
            if "compatibility_report" in resources:
                if self.quota_exhausted:
                    raise QuotaExhaustedError(self.quota_message or "QUOTA_EXHAUSTED")
                report = resources["compatibility_report"]
                if report is None:
                    report = type(
                        "CompatibilityArchiveReport",
                        (),
                        {"can_complete": True, "archived_count": 0},
                    )()
                return report
            pipeline = resources["pipeline"]
            try:
                report = pipeline.archive(outcomes)
            except ProcessingLoopFailure:
                statuses = {str(getattr(outcome, "status", "")) for outcome in outcomes}
                if "quota_exhausted" in statuses or self.quota_exhausted:
                    raise QuotaExhaustedError("QUOTA_EXHAUSTED") from None
                if "auth_failed" in statuses:
                    raise RemoteAuthError("REMOTE_AUTH_FAILED") from None
                raise
            if self.quota_exhausted:
                raise QuotaExhaustedError(self.quota_message or "QUOTA_EXHAUSTED")
            self._sync_run_state_store_from_legacy()
            return report

        def report_callback(_context, _result):
            self._await_truth_audit()

        def pipeline_close():
            try:
                self._active_fetcher = None
                pipeline = resources.get("pipeline")
                if pipeline is not None:
                    pipeline.close()
            finally:
                self._sync_run_state_store_from_legacy()

        def disconnect_callback(_context, fetcher):
            try:
                fetcher.disconnect()
            finally:
                if self._active_fetcher is fetcher:
                    self._active_fetcher = None

        def cleanup_callback(context):
            self._cleanup_temp_folders(
                staging_dir=context.staging_dir,
                temp_dir=self._active_temp_dir,
            )

        return RunDependencies(
            connect=connect,
            scan=scan,
            candidate=candidate,
            extract=extract,
            archive=archive,
            report_service=ReportService(
                report_callback=report_callback,
                disconnect_callback=disconnect_callback,
                cleanup_callback=cleanup_callback,
                timeout_seconds=self._truth_audit_timeout_seconds + 1.0,
                evidence_writer=RunEvidenceWriter(
                    version_resolver=lambda: request.candidate_version,
                ),
                evidence_required=request.evidence_required,
            ),
            cancel_requested=lambda: bool(self._stop_requested),
            secrets={"auth_code": auth_code, "api_key": api_key},
            finalizer_session=lambda: resources.get("fetcher"),
            pipeline_close=pipeline_close,
            state_flush=self._sync_run_state_store_from_legacy,
        )


    def _build_local_organize_dependencies(self, request):
        """Dependencies for feature ②: local files in, archive + ledger out.

        The mailbox is never connected and no mail configuration is read.
        """
        from local_organize import LocalOrganizer, OrganizeRequest, export_summary
        from organize_source import rows_from_documents

        organize_request = OrganizeRequest(
            input_dir=str(request.input_dir or ""),
            output_dir=str(request.save_path or ""),
            rules_text=str(getattr(request, "rules_text", "") or ""),
            dry_run=bool(getattr(request, "dry_run", False)),
            run_id=str(request.run_id or ""),
            split_by_category=bool(getattr(request, "split_by_category", True)),
        )
        resources = {"scan": None, "organizer": None}

        def connect(_request):
            self._append_log(
                "运行",
                "本地整理模式：不连接邮箱，不读取邮箱配置。",
                "text-blue-400",
            )
            return None

        def scan(_session, _request):
            self._append_log(
                "运行", f"正在扫描本地文件夹：{request.input_dir}", "text-blue-400"
            )
            organizer = LocalOrganizer(self, organize_request)
            resources["organizer"] = organizer
            scan_result = organizer.scan()
            resources["scan"] = scan_result
            migration = getattr(organizer, "last_layout_migration", None)
            layout_migrated = int(getattr(migration, "moved_count", 0) or 0)
            layout_planned = int(getattr(migration, "planned_count", 0) or 0)
            layout_label = (
                "按分类分目录"
                if organize_request.split_by_category
                else "不建分类子目录"
            )
            if layout_migrated:
                self._append_log(
                    "信息",
                    (
                        f"已按「{layout_label}」设置调整已归档文件位置："
                        f"{layout_migrated} 个。"
                    ),
                    "text-emerald-400",
                )
            elif layout_planned:
                self._append_log(
                    "信息",
                    (
                        f"预览：将按「{layout_label}」设置调整已归档文件位置："
                        f"{layout_planned} 个。"
                    ),
                    "text-blue-400",
                )
            for warning in list(getattr(migration, "warnings", ()) or ())[:5]:
                self._append_log("提示", str(warning), "text-amber-500")
            self.stats["emails"] = scan_result.file_count
            self._append_log(
                "信息",
                f"共发现 {scan_result.file_count} 个可整理文件。",
                "text-emerald-400",
            )
            if scan_result.manifest_entries:
                self._append_log(
                    "信息",
                    (
                        f"检测到提取清单 manifest.jsonl（{scan_result.manifest_entries} 条），"
                        "将保留邮箱来源信息。"
                    ),
                    "text-slate-400",
                )
            for warning in scan_result.warnings[:5]:
                self._append_log("提示", warning, "text-amber-500")
            if self._stop_requested:
                self._sync_run_state_store_from_legacy()
            return scan_result.documents

        def candidate(documents, _request):
            rows = rows_from_documents(tuple(documents))
            self._append_log(
                "信息", f"共收集到 {len(rows)} 个待识别文件。", "text-emerald-400"
            )
            return rows

        def extract(rows, _request):
            organizer = resources.get("organizer")
            if organizer is None:
                organizer = LocalOrganizer(self, organize_request)
                resources["organizer"] = organizer
            return organizer.extract(list(rows))

        def archive(outcomes, _request):
            organizer = resources.get("organizer")
            if organizer is None:
                raise ProcessingLoopFailure("ORGANIZE_SESSION_MISSING")
            report = organizer.archive(outcomes)
            relocation = dict(getattr(organizer, "last_relocation", {}) or {})
            raw_moved = int(relocation.get("raw_moved_count", 0) or 0)
            duplicates_moved = int(
                relocation.get("duplicates_moved_count", 0) or 0
            )
            if raw_moved:
                self._append_log(
                    "信息",
                    f"原件已原样移入「整理前发票」文件夹保留（文件名不变）：{raw_moved} 个。",
                    "text-emerald-400",
                )
            if duplicates_moved:
                self._append_log(
                    "信息",
                    f"重复文件已移入 duplicates 文件夹：{duplicates_moved} 个。",
                    "text-amber-500",
                )
            for warning in list(relocation.get("warnings", []) or [])[:5]:
                self._append_log("提示", str(warning), "text-amber-500")
            return report

        def report_callback(_context, run_result):
            scan_result = resources.get("scan")
            report = getattr(run_result, "archive_report", None)
            organizer = resources.get("organizer")
            relocation = dict(
                getattr(organizer, "last_relocation", {}) or {}
            )
            migration = getattr(organizer, "last_layout_migration", None)
            classification_summary = self._summarize_stats()
            classification_warnings = []
            if int(classification_summary.get("unclassified_count", 0) or 0) > 0:
                classification_warnings.append(
                    "有 %d 张发票未命中归类规则，已放入「待人工复核」"
                    % int(classification_summary.get("unclassified_count", 0) or 0)
                )
            if scan_result is not None:
                self._last_organize_result = {
                    "input_dir": str(request.input_dir or ""),
                    "output_dir": str(request.save_path or ""),
                    "dry_run": bool(getattr(request, "dry_run", False)),
                    "in_place": os.path.abspath(str(request.input_dir or ""))
                    == os.path.abspath(str(request.save_path or "")),
                    "split_by_category": bool(
                        getattr(request, "split_by_category", True)
                    ),
                    "scanned_files": int(getattr(scan_result, "file_count", 0) or 0),
                    "duplicate_files": int(
                        getattr(scan_result, "skipped_duplicates", 0) or 0
                    ),
                    "manifest_entries": int(
                        getattr(scan_result, "manifest_entries", 0) or 0
                    ),
                    "archived_count": int(
                        getattr(report, "archived_count", 0) or 0
                    ),
                    "duplicate_count": int(
                        getattr(report, "duplicate_count", 0) or 0
                    ),
                    "manual_count": int(getattr(report, "manual_count", 0) or 0),
                    "retained_count": int(
                        getattr(report, "retained_count", 0) or 0
                    ),
                    "unresolved_count": int(
                        getattr(report, "unresolved_count", 0) or 0
                    ),
                    "raw_moved_count": int(
                        relocation.get("raw_moved_count", 0) or 0
                    ),
                    "duplicates_moved_count": int(
                        relocation.get("duplicates_moved_count", 0) or 0
                    ),
                    "originals_kept_count": int(
                        relocation.get("originals_kept_count", 0) or 0
                    ),
                    # Migration/relocation notes are product-facing messages; keep
                    # them visible to API consumers instead of only in the log.
                    "warnings": [
                        *classification_warnings,
                        *[str(item) for item in relocation.get("warnings", []) or []],
                        *[str(item) for item in getattr(migration, "warnings", ()) or ()],
                        *[str(item) for item in getattr(scan_result, "warnings", ()) or ()],
                    ][:20],
                    "classification_counts": dict(
                        classification_summary.get("classification_breakdown") or {}
                    ),
                    "classification_source_counts": dict(
                        classification_summary.get(
                            "classification_source_breakdown"
                        )
                        or {}
                    ),
                    "unclassified_count": int(
                        classification_summary.get("unclassified_count", 0) or 0
                    ),
                    "dictionary_hit_count": int(
                        classification_summary.get("dictionary_hit_count", 0) or 0
                    ),
                    "layout_migrated_count": int(
                        getattr(migration, "moved_count", 0) or 0
                    ),
                    "layout_planned_count": (
                        int(getattr(migration, "planned_count", 0) or 0)
                        if bool(getattr(request, "dry_run", False))
                        else 0
                    ),
                }
            if not bool(getattr(request, "dry_run", False)):
                path = export_summary(self, request.save_path)
                if path:
                    self._last_export_path = path
                    self._append_log(
                        "信息", f"结果明细已导出：{path}", "text-emerald-400"
                    )
            self._sync_run_state_store_from_legacy()

        def pipeline_close():
            organizer = resources.get("organizer")
            if organizer is not None:
                organizer.close()
            self._sync_run_state_store_from_legacy()

        def cleanup_callback(context):
            self._cleanup_temp_folders(
                staging_dir=context.staging_dir,
                temp_dir=self._active_temp_dir,
            )

        return RunDependencies(
            connect=connect,
            scan=scan,
            candidate=candidate,
            extract=extract,
            archive=archive,
            report_service=ReportService(
                report_callback=report_callback,
                cleanup_callback=cleanup_callback,
                timeout_seconds=120.0,
            ),
            cancel_requested=lambda: bool(self._stop_requested),
            pipeline_close=pipeline_close,
            state_flush=self._sync_run_state_store_from_legacy,
        )


    def _finalize_admission_failure(self, handle, exc, *, reason_code="WORKER_START_FAILED"):
        if handle.state in {RunState.COMPLETED, RunState.FAILED}:
            return handle.state
        handle.fail(
            exc,
            reason_code=reason_code,
            user_message=str(
                getattr(exc, "user_message", "") or "后台任务启动失败，请重试。"
            ),
        )
        self._run_state_store.update(
            run_state="finalizing",
            progress=99,
            status_text="正在收尾...",
        )
        staging_dir = handle.staging_dir
        temp_dir = self._active_temp_dir
        state = handle.finalize(
            [
                ("report", self._await_truth_audit),
                (
                    "cleanup",
                    lambda: self._cleanup_temp_folders(
                        staging_dir=staging_dir,
                        temp_dir=temp_dir,
                    ),
                ),
            ]
        )
        error = handle.error
        self._run_state_store.terminalize(
            "failed",
            status_text="启动失败",
            last_error=error,
            reason_code=reason_code,
            logs=[
                {
                    "time": time.strftime("[%H:%M:%S]"),
                    "type": "ERROR",
                    "color": "text-error",
                    "msg": f"System exception: {error}",
                }
            ],
        )
        self._worker_thread = None
        return state

    def _build_admission_candidate(
        self,
        *,
        rules_text,
        save_path,
        date_from,
        date_to,
        email_address,
        auth_code,
        api_key,
        ai_provider="glm",
    ):
        run_context = dict(load_run_context() or {})
        requested_save_path = str(
            save_path
            or (
                run_context.get("output_dir", "")
                if run_context.get("enabled")
                else resolve_default_save_path()
            )
        )
        effective_save_path = str(
            run_context.get("output_dir", requested_save_path)
            if run_context.get("enabled")
            else requested_save_path
        )
        effective_date_from = str(
            (run_context.get("locked_date_from", "") if run_context.get("enabled") else "")
            or date_from
            or ""
        )
        effective_date_to = str(
            (run_context.get("locked_date_to", "") if run_context.get("enabled") else "")
            or date_to
            or ""
        )
        date_error = self._validate_date_range(effective_date_from, effective_date_to)
        if date_error:
            return None, None, date_error

        email_text = str(email_address or "")
        email_domain = email_text.rsplit("@", 1)[-1].lower() if "@" in email_text else ""
        if not is_supported_email(email_text):
            return None, None, "暂不支持该邮箱域名，请更换为受支持的常用邮箱。"
        candidate = _RunAdmissionCandidate(
            rules_text=str(rules_text or ""),
            requested_save_path=requested_save_path,
            effective_save_path=effective_save_path,
            date_from=effective_date_from,
            date_to=effective_date_to,
            account_id=stable_hash(email_text)[:12],
            channel_id=resolve_channel(email_text)["channel_id"] or "email",
            email_domain=email_domain,
            run_context_json=json.dumps(run_context, ensure_ascii=False, sort_keys=True),
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return candidate, _RunAdmissionSecrets(
            email_text, auth_code, api_key, ai_provider
        ), ""

    def _restore_failed_admission(self, previous, previous_settings, settings_existed, settings_touched):
        if settings_touched:
            try:
                if settings_existed:
                    self._settings_store.save(previous_settings)
                else:
                    self._settings_store.clear()
            except Exception:
                pass
        for name, value in previous.items():
            setattr(self, name, value)

    def _reset_run_state_for_admission(self, run_id):
        self._legacy_sync_signature = None
        reset_kwargs = {
            "status_text": "正在准备运行...",
            "run_state": "running",
            "progress": 5,
        }
        try:
            self._run_state_store.reset(run_id, **reset_kwargs)
            return
        except Exception:
            previous_store = self._run_state_store
            self._run_state_store = RunStateStore(
                event_sink=getattr(previous_store, "_event_sink", None),
                state_sink=self._apply_run_state_snapshot,
            )
            try:
                self._run_state_store.reset(run_id, **reset_kwargs)
            except Exception:
                pass
            raise RuntimeError("run state initialization failed") from None

    @staticmethod
    def _admission_missing_directories(context, save_path):
        targets = {
            str(context.get(key) or "").strip()
            for key in (
                "run_root",
                "output_dir",
                "staging_dir",
                "diagnostics_dir",
                "monitoring_dir",
                "qc_dir",
            )
        }
        targets.add(str(save_path or "").strip())
        missing = set()
        for value in targets:
            if not value:
                continue
            path = Path(value).resolve()
            while not path.exists() and path != path.parent:
                missing.add(path)
                path = path.parent
        return tuple(sorted(missing, key=lambda item: len(item.parts), reverse=True))

    @staticmethod
    def _remove_empty_admission_directories(paths):
        import shutil

        for path in paths:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            except OSError:
                continue

    @staticmethod
    def _close_run_dependencies(dependencies):
        service = getattr(dependencies, "report_service", None)
        close = getattr(service, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _admit_processing_run(
        self,
        *,
        candidate,
        secrets,
        fetch_only=False,
    ):
        with self._admission_lock:
            worker_active = bool(self._worker_thread and self._worker_thread.is_alive())
            active_handle = self._active_run_handle
            handle_active = bool(
                active_handle
                and active_handle.state not in {RunState.COMPLETED, RunState.FAILED}
            )
            if worker_active or handle_active or not self._run_lifecycle.can_begin:
                return {"success": False, "message": "任务已在运行中"}
            if active_handle is not None:
                self._active_run_handle = None
            if not fetch_only:
                rules_error = self._classification_rules_error(
                    getattr(candidate, "effective_save_path", "")
                )
                if rules_error:
                    return {"success": False, "message": rules_error}

            previous = {
                "_run_context": self._run_context,
                "_current_run_id": self._current_run_id,
                "_requested_save_path": self._requested_save_path,
                "_effective_save_path": self._effective_save_path,
                "_effective_date_from": self._effective_date_from,
                "_effective_date_to": self._effective_date_to,
                "_active_run_config": self._active_run_config,
                "_active_temp_dir": self._active_temp_dir,
                "_truth_audit_thread": self._truth_audit_thread,
                "_truth_audit_job": self._truth_audit_job,
                "_active_ai_provider": getattr(self, "_active_ai_provider", "glm"),
            }
            previous_settings = {}
            settings_existed = os.path.exists(self._settings_store.settings_path)
            settings_touched = False
            handle = None
            dependencies = None
            admission_missing_dirs = ()
            try:
                self._run_context = candidate.run_context()
                self._current_run_id = str(self._run_context.get("run_id", "") or "")
                admission_missing_dirs = self._admission_missing_directories(
                    self._run_context,
                    candidate.effective_save_path,
                )
                handle = self._prepare_run_lifecycle()
                self._reset_run_state_for_admission(handle.run_id)
                from run_evidence import RevisionUnavailable

                trusted_revision = str(self._revision_resolver() or "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{40}", trusted_revision):
                    raise RevisionUnavailable()
                ensure_run_context_dirs(self._run_context)
                previous_settings = self._settings_store.load() or {}
                self._requested_save_path = candidate.requested_save_path
                self._effective_save_path = candidate.effective_save_path
                self._effective_date_from = candidate.date_from
                self._effective_date_to = candidate.date_to

                active_company = str(previous_settings.get("company") or "").strip()
                remember_settings = bool(previous_settings.get("remember_settings", True))
                self._active_ai_provider = normalize_provider(secrets.ai_provider)
                self._active_run_config = {
                    "company": active_company,
                    "save_path": candidate.effective_save_path,
                    "date_from": candidate.date_from,
                    "date_to": candidate.date_to,
                    "started_at": candidate.started_at,
                }

                os.makedirs(candidate.effective_save_path, exist_ok=True)
                if remember_settings:
                    settings_payload = {
                        "email": secrets.email_address,
                        "auth_code": secrets.auth_code,
                        "ai_provider": self._active_ai_provider,
                        "save_path": candidate.effective_save_path,
                        "date_from": candidate.date_from,
                        "date_to": candidate.date_to,
                        "company": active_company,
                        "remember_settings": True,
                    }
                    if str(secrets.api_key or "").strip():
                        # Legacy-only: local recognition never needs an API key, so
                        # an empty value must not overwrite a previously stored one.
                        active_key_field = (
                            "deepseek_api_key"
                            if self._active_ai_provider == DEEPSEEK_PROVIDER
                            else "api_key"
                        )
                        settings_payload[active_key_field] = secrets.api_key
                else:
                    settings_payload = {"remember_settings": False}
                settings_touched = True
                save_result = self.save_user_settings(settings_payload)
                if not bool((save_result or {}).get("success")):
                    raise RuntimeError("settings persistence failed")

                request = RunRequest(
                    run_id=handle.run_id,
                    date_from=candidate.date_from,
                    date_to=candidate.date_to,
                    save_path=candidate.effective_save_path,
                    rules_text=candidate.rules_text,
                    account_id=candidate.account_id,
                    channel_id=candidate.channel_id,
                    before_exclusive=(
                        datetime.strptime(candidate.date_to, "%Y-%m-%d")
                        + timedelta(days=1)
                    ).strftime("%Y-%m-%d"),
                    account_domain=candidate.email_domain,
                    mailbox="INBOX",
                    target_identifier=active_company,
                    run_mode=str(
                        self._run_context.get("autostart_mode")
                        or ("controlled-run" if self._run_context.get("enabled") else "interactive")
                    ),
                    run_root=str(self._run_context.get("run_root") or ""),
                    evidence_required=bool(
                        self._run_context.get("enabled")
                        and self._run_context.get("run_root")
                    ),
                    candidate_version=str(
                        self._run_context.get("candidate_version") or "source"
                    ),
                    trusted_revision=trusted_revision,
                    validation_required=bool(
                        self._run_context.get("validation_required", False)
                    ),
                    manifest_included_count=int(
                        self._run_context.get("manifest_included_count", 0) or 0
                    ),
                    source_mode="mail",
                    fetch_only=bool(fetch_only),
                )
                self._active_task_mode = "fetch" if fetch_only else "mail"
                self._last_fetch_summary = {}
                self._last_organize_result = None
                dependencies = self._build_run_dependencies(
                    request,
                    email_address=secrets.email_address,
                    auth_code=secrets.auth_code,
                    api_key=secrets.api_key,
                    ai_provider=secrets.ai_provider,
                    fetch_only=bool(fetch_only),
                )
                self._safe_write_run_config(
                    secrets.email_address,
                    auth_code=secrets.auth_code,
                    api_key=secrets.api_key,
                    request=request,
                )
            except Exception as exc:
                self._close_run_dependencies(dependencies)
                if handle is not None:
                    reason_code = str(
                        getattr(exc, "reason_code", "") or "WORKER_START_FAILED"
                    )
                    self._finalize_admission_failure(
                        handle,
                        exc,
                        reason_code=reason_code,
                    )
                self._restore_failed_admission(
                    previous,
                    previous_settings,
                    settings_existed,
                    settings_touched,
                )
                self._remove_empty_admission_directories(admission_missing_dirs)
                return {"success": False, "message": "后台任务启动失败"}

            self._run_state_store.append_log(
                "信息",
                "前端请求已接收，后台任务正在启动。",
                "text-blue-400",
            )
            self._packaged_diag_reset(
                {
                    "requested_save_path": candidate.requested_save_path,
                    "effective_save_path": candidate.effective_save_path,
                    "date_from": candidate.date_from,
                    "date_to": candidate.date_to,
                    "email_domain": candidate.email_domain,
                    "has_auth_code": bool(secrets.auth_code),
                    "has_api_key": bool(secrets.api_key),
                }
            )
            self._packaged_diag_write(
                "progress_5_written",
                "start_processing",
                "success",
                summary={
                    "requested_save_path": candidate.requested_save_path,
                    "effective_save_path": candidate.effective_save_path,
                    "date_from": candidate.date_from,
                    "date_to": candidate.date_to,
                    "email_domain": candidate.email_domain,
                    "has_auth_code": bool(secrets.auth_code),
                    "has_api_key": bool(secrets.api_key),
                },
            )
            self._safe_emit_stage_event(
                "start_processing",
                "enter",
                {
                    "requested_save_path": candidate.requested_save_path,
                    "effective_save_path": candidate.effective_save_path,
                    "date_from": candidate.date_from,
                    "date_to": candidate.date_to,
                    **self._sensitive_summary(
                        secrets.email_address,
                        secrets.auth_code,
                        secrets.api_key,
                    ),
                },
            )
            try:
                if not fetch_only:
                    self._start_truth_audit_async(secrets.email_address, secrets.auth_code)
            except Exception as exc:
                self._close_run_dependencies(dependencies)
                self._safe_emit_stage_event(
                    "start_processing",
                    "exit",
                    {"result": "failed", "reason": "WORKER_START_FAILED"},
                )
                self._finalize_admission_failure(handle, exc)
                self._restore_failed_admission(
                    previous,
                    previous_settings,
                    settings_existed,
                    settings_touched,
                )
                return {"success": False, "message": "后台任务启动失败"}

            thread = threading.Thread(
                target=self._processing_worker,
                args=(request, handle, dependencies),
                name=THREAD_NAME_WORKER,
                daemon=True,
            )
            self._worker_thread = thread
            self._packaged_diag_write("worker_thread_created", "start_processing", "success")
            try:
                thread.start()
            except Exception as exc:
                self._close_run_dependencies(dependencies)
                self._finalize_admission_failure(handle, exc)
                self._restore_failed_admission(
                    previous,
                    previous_settings,
                    settings_existed,
                    settings_touched,
                )
                return {"success": False, "message": "后台任务启动失败"}
            self._packaged_diag_write(
                "worker_thread_started",
                "start_processing",
                "success",
                summary={"thread_is_alive": bool(thread.is_alive())},
            )
            self._safe_emit_stage_event("start_processing", "exit", {"result": "started"})
            return {"success": True, "message": "任务已启动"}

    def start_processing(self, rules_text, save_path, date_from=None, date_to=None, email_address=None, auth_code=None, api_key="", ai_provider="glm"):
        if not self._run_lifecycle.can_begin or self._is_running or (self._worker_thread and self._worker_thread.is_alive()):
            return {"success": False, "message": "任务已在运行中"}

        if not email_address or not auth_code:
            return {"success": False, "message": "缺少必要凭证，请填写邮箱地址和授权码"}

        candidate, secrets, date_error = self._build_admission_candidate(
            rules_text=rules_text,
            save_path=save_path,
            date_from=date_from,
            date_to=date_to,
            email_address=email_address,
            auth_code=auth_code,
            api_key=api_key,
            ai_provider=ai_provider,
        )
        if date_error:
            return {"success": False, "message": date_error}

        return self._admit_processing_run(
            candidate=candidate,
            secrets=secrets,
        )

    def start_local_organize(self, input_dir, save_path="", dry_run=False, split_by_category=True):
        """Feature ②: organize a local folder automatically (in place by default).

        ``split_by_category`` keeps the per-category archive folders; ``False``
        archives every processed invoice flat into the output root.
        """
        if (
            not self._run_lifecycle.can_begin
            or self._is_running
            or (self._worker_thread and self._worker_thread.is_alive())
        ):
            return {"success": False, "message": "任务已在运行中"}

        from local_organize import is_filesystem_root

        input_text = str(input_dir or "").strip()
        if not input_text:
            return {"success": False, "message": "请选择要整理的本地文件夹"}
        if not os.path.isdir(input_text):
            return {"success": False, "message": "要整理的本地文件夹不存在"}
        if is_filesystem_root(input_text):
            return {
                "success": False,
                "message": "不能直接整理磁盘根目录，请选择具体的发票文件夹",
            }
        save_text = str(save_path or "").strip() or input_text
        if os.path.exists(save_text) and not os.path.isdir(save_text):
            return {"success": False, "message": "输出路径不是文件夹"}
        if str(save_text).startswith(("\\\\", "//")):
            return {"success": False, "message": "不支持网络共享路径"}

        return self._admit_local_organize(
            input_text, save_text, bool(dry_run), bool(split_by_category)
        )

    def _admit_local_organize(self, input_dir, save_path, dry_run, split_by_category=True):
        with self._admission_lock:
            worker_active = bool(self._worker_thread and self._worker_thread.is_alive())
            active_handle = self._active_run_handle
            handle_active = bool(
                active_handle
                and active_handle.state not in {RunState.COMPLETED, RunState.FAILED}
            )
            if worker_active or handle_active or not self._run_lifecycle.can_begin:
                return {"success": False, "message": "任务已在运行中"}
            if active_handle is not None:
                self._active_run_handle = None
            rules_error = self._classification_rules_error(
                os.path.abspath(str(save_path or "").strip() or input_dir)
            )
            if rules_error:
                return {"success": False, "message": rules_error}

            previous = {
                "_run_context": self._run_context,
                "_current_run_id": self._current_run_id,
                "_requested_save_path": self._requested_save_path,
                "_effective_save_path": self._effective_save_path,
                "_effective_date_from": self._effective_date_from,
                "_effective_date_to": self._effective_date_to,
                "_raw_date_range_display": self._raw_date_range_display,
                "_imap_query_range_display": self._imap_query_range_display,
                "_active_run_config": self._active_run_config,
                "_active_temp_dir": self._active_temp_dir,
                "_active_task_mode": getattr(self, "_active_task_mode", "mail"),
                "_last_fetch_summary": getattr(self, "_last_fetch_summary", {}),
                "_last_organize_result": getattr(self, "_last_organize_result", None),
            }
            previous_settings = {}
            settings_existed = os.path.exists(self._settings_store.settings_path)
            settings_touched = False
            handle = None
            dependencies = None
            admission_missing_dirs = ()
            try:
                context = dict(self._run_context or {})
                context.setdefault("enabled", False)
                effective_save_path = str(save_path or "").strip() or input_dir
                if context.get("enabled") and context.get("output_dir"):
                    effective_save_path = str(context.get("output_dir"))
                effective_save_path = os.path.abspath(effective_save_path)
                context["output_dir"] = effective_save_path
                context["run_root"] = str(context.get("run_root") or effective_save_path)
                if not str(context.get("staging_dir") or "").strip():
                    import tempfile

                    context["staging_dir"] = os.path.join(
                        tempfile.gettempdir(), f"{TEMP_DIR_PREFIX}-local"
                    )
                self._run_context = context
                self._current_run_id = str(context.get("run_id") or "")
                admission_missing_dirs = self._admission_missing_directories(
                    context, effective_save_path
                )
                handle = self._prepare_run_lifecycle()
                self._reset_run_state_for_admission(handle.run_id)
                ensure_run_context_dirs(context)
                previous_settings = self._settings_store.load() or {}
                self._requested_save_path = effective_save_path
                self._effective_save_path = effective_save_path
                self._effective_date_from = ""
                self._effective_date_to = ""
                self._raw_date_range_display = ""
                self._imap_query_range_display = ""

                active_company = str(previous_settings.get("company") or "").strip()
                self._active_run_config = {
                    "company": active_company,
                    "save_path": effective_save_path,
                    "date_from": "",
                    "date_to": "",
                    "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                os.makedirs(effective_save_path, exist_ok=True)
                settings_touched = True
                # Never overwrite the mail mode save_path: local organizing keeps
                # its own output setting ("" means "same folder as the invoices").
                local_output_dir = "" if os.path.abspath(input_dir) == effective_save_path else effective_save_path
                save_result = self.save_user_settings(
                    {
                        "task_mode": "local",
                        "local_input_dir": input_dir,
                        "local_output_dir": local_output_dir,
                        "local_split_by_category": bool(split_by_category),
                        "company": active_company,
                    }
                )
                if not bool((save_result or {}).get("success")):
                    raise RuntimeError("settings persistence failed")

                request = RunRequest(
                    run_id=handle.run_id,
                    date_from="",
                    date_to="",
                    save_path=effective_save_path,
                    rules_text="",
                    account_id=stable_hash(input_dir)[:12],
                    channel_id="local",
                    run_mode=str(
                        self._run_context.get("autostart_mode")
                        or (
                            "controlled-run"
                            if self._run_context.get("enabled")
                            else "interactive"
                        )
                    ),
                    run_root=str(self._run_context.get("run_root") or ""),
                    source_mode="local",
                    input_dir=input_dir,
                    dry_run=bool(dry_run),
                    split_by_category=bool(split_by_category),
                )
                self._active_task_mode = "local"
                self._last_fetch_summary = {}
                self._last_organize_result = None
                dependencies = self._build_local_organize_dependencies(request)
            except Exception as exc:
                self._close_run_dependencies(dependencies)
                if handle is not None:
                    reason_code = str(
                        getattr(exc, "reason_code", "") or "WORKER_START_FAILED"
                    )
                    self._finalize_admission_failure(
                        handle, exc, reason_code=reason_code
                    )
                self._restore_failed_admission(
                    previous, previous_settings, settings_existed, settings_touched
                )
                self._remove_empty_admission_directories(admission_missing_dirs)
                return {"success": False, "message": "本地整理任务启动失败"}

            self._run_state_store.append_log(
                "信息", "本地整理请求已接收，后台任务正在启动。", "text-blue-400"
            )
            self._safe_emit_stage_event(
                "start_local_organize",
                "enter",
                {
                    "input_dir": input_dir,
                    "output_dir": str(request.save_path),
                    "dry_run": bool(dry_run),
                    "split_by_category": bool(split_by_category),
                },
            )
            thread = threading.Thread(
                target=self._processing_worker,
                args=(request, handle, dependencies),
                name=THREAD_NAME_WORKER,
                daemon=True,
            )
            self._worker_thread = thread
            try:
                thread.start()
            except Exception as exc:
                self._close_run_dependencies(dependencies)
                self._finalize_admission_failure(handle, exc)
                self._restore_failed_admission(
                    previous, previous_settings, settings_existed, settings_touched
                )
                return {"success": False, "message": "本地整理任务启动失败"}
            self._safe_emit_stage_event(
                "start_local_organize", "exit", {"result": "started"}
            )
            return {
                "success": True,
                "message": "本地整理任务已启动" if not dry_run else "本地预览任务已启动",
            }


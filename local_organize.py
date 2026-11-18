"""Local folder organizing (product feature ②): files -> archive + ledger.

This module is the offline counterpart of the mailbox fetch path. It never
imports ``email_fetcher`` / ``email_channel`` / IMAP code and never reads mail
configuration: any local directory (a fetch-produced ``inbox/``, a phone export,
a WeChat download folder, paperwork photos) can be organized on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any

import fetch_handoff
import organize_source


@dataclass(frozen=True)
class OrganizeRequest:
    input_dir: str
    output_dir: str
    rules_text: str = ""
    dry_run: bool = False
    run_id: str = ""
    recursive: bool = True
    source_label: str = "本地文件夹整理"

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.input_dir, fetch_handoff.MANIFEST_FILENAME)

    @property
    def inbox_dir(self) -> str:
        return os.path.join(self.output_dir, fetch_handoff.INBOX_DIRNAME)


@dataclass
class OrganizeResult:
    request: OrganizeRequest
    run_id: str
    scanned_files: int = 0
    duplicate_files: int = 0
    unsupported_files: int = 0
    manifest_entries: int = 0
    archived_count: int = 0
    duplicate_count: int = 0
    manual_count: int = 0
    retained_count: int = 0
    unresolved_count: int = 0
    report_path: str = ""
    warnings: tuple[str, ...] = ()
    preview_rows: tuple[dict[str, Any], ...] = ()
    duration_seconds: float = 0.0

    @property
    def dry_run(self) -> bool:
        return bool(self.request.dry_run)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "input_dir": self.request.input_dir,
            "output_dir": self.request.output_dir,
            "dry_run": self.dry_run,
            "scanned_files": self.scanned_files,
            "duplicate_files": self.duplicate_files,
            "unsupported_files": self.unsupported_files,
            "manifest_entries": self.manifest_entries,
            "archived_count": self.archived_count,
            "duplicate_count": self.duplicate_count,
            "manual_count": self.manual_count,
            "retained_count": self.retained_count,
            "unresolved_count": self.unresolved_count,
            "report_path": self.report_path,
            "warnings": list(self.warnings),
            "preview_rows": list(self.preview_rows),
            "duration_seconds": round(self.duration_seconds, 3),
        }


def validate_request(request: OrganizeRequest) -> str | None:
    """Return a user-facing validation error, or None when the request is usable."""
    input_dir = str(request.input_dir or "").strip()
    if not input_dir:
        return "请选择要整理的本地文件夹"
    if not os.path.isdir(input_dir):
        return "要整理的本地文件夹不存在"
    output_dir = str(request.output_dir or "").strip()
    if not output_dir:
        return "请选择输出目录"
    if os.path.exists(output_dir) and not os.path.isdir(output_dir):
        return "输出路径不是文件夹"
    return None


def _exclude_paths(request: OrganizeRequest) -> tuple[str, ...]:
    """Never re-scan the archive root when it lives inside the input folder."""
    input_dir = os.path.abspath(request.input_dir)
    output_dir = os.path.abspath(request.output_dir)
    if output_dir == input_dir:
        return ()
    try:
        common = os.path.commonpath([input_dir, output_dir])
    except ValueError:
        return ()
    if common == output_dir:
        # Output is a parent of the input: nothing to exclude (input subtree only).
        return ()
    if common == input_dir:
        return (output_dir,)
    return ()


def scan_input(request: OrganizeRequest) -> organize_source.LocalScanResult:
    manifest_path = request.manifest_path if os.path.isfile(request.manifest_path) else None
    return organize_source.scan_local_directory(
        request.input_dir,
        exclude_paths=_exclude_paths(request),
        manifest_path=manifest_path,
        recursive=request.recursive,
    )


def candidate_rows(
    scan: organize_source.LocalScanResult,
) -> list[dict[str, Any]]:
    return organize_source.to_attachment_rows(scan)


def create_extractor(output_dir: str, *, api_key: str = ""):
    from invoice_extractor import InvoiceExtractor

    return InvoiceExtractor(api_key=api_key, output_dir=output_dir)


def export_summary(api: Any, save_path: str) -> str:
    """Reuse the product's Excel report for an applied organize run."""
    exporter = getattr(api, "export_run_summary", None)
    if not callable(exporter):
        return ""
    try:
        result = exporter(save_path) or {}
    except Exception:
        return ""
    if result.get("success"):
        return str(result.get("path") or "")
    return ""


class LocalOrganizer:
    """Synchronous organizer used by the CLI and by the desktop worker."""

    def __init__(self, api: Any, request: OrganizeRequest) -> None:
        self.api = api
        self.request = request
        self._session = None
        self._extractor = None
        self.scan_result: organize_source.LocalScanResult | None = None

    # ----------------------------------------------------------------- stages
    def prepare_api(self) -> None:
        """Mirror the run context the processing pipeline expects."""
        request = self.request
        run_id = str(request.run_id or f"local-organize-{time.strftime('%Y%m%d%H%M%S')}")
        output_dir = os.path.abspath(request.output_dir)
        os.makedirs(output_dir, exist_ok=True)
        self.api._run_context = {
            "enabled": False,
            "run_id": run_id,
            "run_root": output_dir,
            "staging_dir": os.path.join(output_dir, ".local-staging", run_id),
        }
        self.api._current_run_id = run_id
        self.api._requested_save_path = output_dir
        self.api._effective_save_path = output_dir
        self.api._effective_date_from = ""
        self.api._effective_date_to = ""
        self.api._stop_requested = False
        self.api._active_run_config = {
            "company": self._active_company(),
            "save_path": output_dir,
            "date_from": "",
            "date_to": "",
        }

    def _active_company(self) -> str:
        try:
            resolver = getattr(self.api, "_resolve_active_company", None)
            if callable(resolver):
                return str(resolver() or "")
        except Exception:
            return ""
        return ""

    def scan(self) -> organize_source.LocalScanResult:
        self.scan_result = scan_input(self.request)
        return self.scan_result

    def extract(self, rows: list[dict[str, Any]]):
        self._extractor = create_extractor(self.request.output_dir)
        self._session = self.api._create_processing_pipeline_session(
            rows,
            "",
            self.request.output_dir,
            "",
            "",
            self.request.rules_text,
            _extractor=self._extractor,
            _owned_extractor=self._extractor,
            _prepare_remote_images=False,
            _dry_run=self.request.dry_run,
        )
        return self._session.extract()

    def archive(self, outcomes):
        if self._session is None:
            raise RuntimeError("organize session is not open")
        return self._session.archive(outcomes)

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            finally:
                self._session = None

    # ------------------------------------------------------------------- run
    def run(self) -> OrganizeResult:
        error = validate_request(self.request)
        if error:
            raise ValueError(error)
        started = time.monotonic()
        request = self.request
        self.prepare_api()
        try:
            scan = self.scan()
            rows = candidate_rows(scan)
            outcomes = self.extract(rows)
            report = self.archive(outcomes)
        finally:
            self.close()

        report_path = ""
        if not request.dry_run:
            report_path = export_summary(self.api, request.output_dir)
        preview_rows = tuple(
            dict(row)
            for row in list(getattr(self.api, "processed_invoices", [])) + list(
                getattr(self.api, "error_invoices", [])
            )
        )
        return OrganizeResult(
            request=request,
            run_id=str(self.api._current_run_id or ""),
            scanned_files=scan.file_count,
            duplicate_files=scan.skipped_duplicates,
            unsupported_files=scan.skipped_unsupported,
            manifest_entries=scan.manifest_entries,
            archived_count=int(getattr(report, "archived_count", 0) or 0),
            duplicate_count=int(getattr(report, "duplicate_count", 0) or 0),
            manual_count=int(getattr(report, "manual_count", 0) or 0),
            retained_count=int(getattr(report, "retained_count", 0) or 0),
            unresolved_count=int(getattr(report, "unresolved_count", 0) or 0),
            report_path=report_path,
            warnings=tuple(scan.warnings),
            preview_rows=preview_rows,
            duration_seconds=time.monotonic() - started,
        )


def run_local_organize(api: Any, request: OrganizeRequest) -> OrganizeResult:
    return LocalOrganizer(api, request).run()

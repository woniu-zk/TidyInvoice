"""Local folder organizing (product feature ②): files -> archive + ledger.

This module is the offline counterpart of the mailbox fetch path. It never
imports ``email_fetcher`` / ``email_channel`` / IMAP code and never reads mail
configuration: any local directory (a fetch-produced ``inbox/``, a phone export,
a WeChat download folder, paperwork photos) can be organized on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import filecmp
import os
import shutil
import time
from typing import Any

import fetch_handoff
import organize_source
from organize_layout import (
    LEGACY_ORIGINALS_DIR_NAME,
    ORIGINALS_DIR_NAME,
    LayoutMigration,
    archive_dir_names,
    enforce_layout,
    organized_output_name_re,
)


def is_filesystem_root(path: str | os.PathLike[str]) -> bool:
    """Return True for drive roots / filesystem roots (e.g. ``C:\\`` or ``/``)."""
    resolved = os.path.abspath(str(path or ""))
    _drive, rest = os.path.splitdrive(resolved)
    return not rest.replace("/", "").replace("\\", "").strip()


@dataclass(frozen=True)
class OrganizeRequest:
    input_dir: str
    output_dir: str = ""
    rules_text: str = ""
    dry_run: bool = False
    run_id: str = ""
    recursive: bool = True
    source_label: str = "本地文件夹整理"
    #: True keeps the per-category archive folders (餐饮/, 充电/, ...). False
    #: archives every processed invoice flat into the output root; the file name
    #: still carries the category, and the originals/duplicates/review buckets
    #: are kept. Either way a re-run skips files an earlier run already produced.
    split_by_category: bool = True

    @property
    def resolved_output_dir(self) -> str:
        """Output root, defaulting to the input folder (in-place organizing)."""
        output = str(self.output_dir or "").strip()
        return os.path.abspath(output or self.input_dir)

    @property
    def in_place(self) -> bool:
        try:
            return os.path.abspath(self.input_dir) == self.resolved_output_dir
        except (OSError, ValueError):
            return False

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.input_dir, fetch_handoff.MANIFEST_FILENAME)

    @property
    def inbox_dir(self) -> str:
        return os.path.join(self.resolved_output_dir, fetch_handoff.INBOX_DIRNAME)


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
    raw_moved_count: int = 0
    duplicates_moved_count: int = 0
    originals_kept_count: int = 0
    #: Archived invoices moved to match the requested directory layout (e.g. a
    #: flat archive switched to the per-category folders). ``layout_planned_count``
    #: is the preview of the same re-layout for dry runs.
    layout_migrated_count: int = 0
    layout_planned_count: int = 0
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
            "output_dir": self.request.resolved_output_dir,
            "dry_run": self.dry_run,
            "in_place": self.request.in_place,
            "split_by_category": bool(self.request.split_by_category),
            "scanned_files": self.scanned_files,
            "duplicate_files": self.duplicate_files,
            "unsupported_files": self.unsupported_files,
            "manifest_entries": self.manifest_entries,
            "archived_count": self.archived_count,
            "duplicate_count": self.duplicate_count,
            "manual_count": self.manual_count,
            "retained_count": self.retained_count,
            "unresolved_count": self.unresolved_count,
            "raw_moved_count": self.raw_moved_count,
            "duplicates_moved_count": self.duplicates_moved_count,
            "originals_kept_count": self.originals_kept_count,
            "layout_migrated_count": self.layout_migrated_count,
            "layout_planned_count": self.layout_planned_count,
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
    if is_filesystem_root(input_dir):
        return "不能直接整理磁盘根目录，请选择具体的发票文件夹"
    output_dir = str(request.output_dir or "").strip() or input_dir
    if os.path.exists(output_dir) and not os.path.isdir(output_dir):
        return "输出路径不是文件夹"
    return None


def _exclude_paths(request: OrganizeRequest) -> tuple[str, ...]:
    """Never re-scan the archive root when it lives inside the input folder."""
    input_dir = os.path.abspath(request.input_dir)
    output_dir = request.resolved_output_dir
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
    scan = organize_source.scan_local_directory(
        request.input_dir,
        exclude_paths=_exclude_paths(request),
        exclude_root_child_dir_names=(
            archive_dir_names() if request.in_place else ()
        ),
        manifest_path=manifest_path,
        recursive=request.recursive,
    )
    if request.in_place:
        scan = _drop_organized_outputs(scan)
    return scan


def _drop_organized_outputs(
    scan: organize_source.LocalScanResult,
) -> organize_source.LocalScanResult:
    """Skip root-level files a previous in-place run already organized.

    This applies to both layouts: a flat run leaves its output in the folder
    root, and re-processing those files would only move them into
    ``duplicates/``. Only root-level names are considered, so a user child
    folder that merely reuses an archived name is still scanned normally.
    """
    pattern = organized_output_name_re()
    kept = []
    skipped = 0
    for document in scan.documents:
        name = os.path.basename(document.path)
        if "/" not in document.rel_path and pattern.match(name):
            skipped += 1
            continue
        kept.append(document)
    if not skipped:
        return scan
    warnings = tuple(scan.warnings) + (
        f"已跳过上次整理生成的文件 {skipped} 个（不重复整理）",
    )
    return replace(scan, documents=tuple(kept), warnings=warnings)


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
        self._run_id = ""
        self.scan_result: organize_source.LocalScanResult | None = None
        self.last_layout_migration: LayoutMigration | None = None
        self.last_relocation: dict[str, Any] = {
            "raw_moved_count": 0,
            "duplicates_moved_count": 0,
            "originals_kept_count": 0,
            "warnings": [],
        }

    # ----------------------------------------------------------------- stages
    def prepare_api(self) -> None:
        """Mirror the run context the processing pipeline expects."""
        request = self.request
        run_id = str(request.run_id or f"local-organize-{time.strftime('%Y%m%d%H%M%S')}")
        self._run_id = run_id
        output_dir = request.resolved_output_dir
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
        # Enforce the layout this run asks for before scanning: when an earlier
        # run already organized this folder with the other layout, its archive
        # files are moved now instead of being skipped as "already organized".
        self.last_layout_migration = enforce_layout(
            self.request.resolved_output_dir,
            split_by_category=self.request.split_by_category,
            dry_run=self.request.dry_run,
        )
        self.scan_result = scan_input(self.request)
        return self.scan_result

    def extract(self, rows: list[dict[str, Any]]):
        output_dir = self.request.resolved_output_dir
        self._extractor = create_extractor(output_dir)
        self._session = self.api._create_processing_pipeline_session(
            rows,
            "",
            output_dir,
            "",
            "",
            self.request.rules_text,
            _extractor=self._extractor,
            _owned_extractor=self._extractor,
            _prepare_remote_images=False,
            _dry_run=self.request.dry_run,
            _flat_layout=not self.request.split_by_category,
        )
        return self._session.extract()

    def archive(self, outcomes):
        if self._session is None:
            raise RuntimeError("organize session is not open")
        report = self._session.archive(outcomes)
        if not self.request.dry_run and self.request.in_place:
            self._relocate_originals(report)
        return report

    # ------------------------------------------------------- in-place cleanup
    def _migrate_legacy_originals(self, root: str, raw_root: str) -> list[str]:
        """Rename an older ``raw/`` originals bucket to ``整理前发票/``.

        Older builds saved processed originals under ``<input>/raw/``. The bucket
        is renamed now so the folder the user sees carries the product name; the
        files inside are not moved, renamed, or rewritten. When the current
        bucket already exists the legacy one is left where it is (it stays a
        tool-owned folder) instead of merging two buckets.
        """
        legacy = os.path.join(root, LEGACY_ORIGINALS_DIR_NAME)
        if os.path.islink(legacy) or not os.path.isdir(legacy):
            return []
        if os.path.exists(raw_root):
            return [
                "检测到旧版「raw」文件夹；因「整理前发票」已存在，未自动改名合并"
            ]
        try:
            os.rename(legacy, raw_root)
        except OSError as exc:
            return [f"旧版「raw」文件夹未能改名为「整理前发票」：{type(exc).__name__}"]
        return ["旧版「raw」文件夹已改名为「整理前发票」（内部文件保持原样）"]

    def _relocate_originals(self, report) -> None:
        """Move processed originals out of the folder root (in-place mode only).

        - archived / manual_review / retained: the original file itself goes to
          ``<input>/整理前发票/`` **as the user had it** — same file name, same
          bytes, and the same relative path when it came from a sub-folder.
          There is no renaming and no ``YYYY/MM`` bucketing; a later run that
          would hit the same path never renames either, it keeps the file name
          and stores the later copy under ``整理前发票/<run_id>/``.
        - duplicate: move to ``<input>/duplicates/`` so a re-run stays clean
        - unresolved: leave untouched for the user to inspect

        A legacy ``raw/`` bucket from older builds is renamed to the current
        bucket name first (best-effort; its content is not altered).

        Every move is best-effort: a failure keeps the original where it is and
        never fails the run.
        """
        root = os.path.abspath(self.request.input_dir)
        raw_root = os.path.join(root, ORIGINALS_DIR_NAME)
        duplicates_root = os.path.join(root, "duplicates")
        run_id = self._run_id or "run"
        tool_dirs = archive_dir_names()
        counts = {
            "raw_moved_count": 0,
            "duplicates_moved_count": 0,
            "originals_kept_count": 0,
            "warnings": [],
        }
        counts["warnings"].extend(self._migrate_legacy_originals(root, raw_root))

        for archived in getattr(report, "outcomes", ()) or ():
            outcome = getattr(archived, "outcome", None)
            if outcome is None:
                continue
            source = str(getattr(outcome, "candidate", None).source_path or "")
            if not source or not os.path.isfile(source):
                continue
            source_abs = os.path.abspath(source)
            if not self._is_inside(source_abs, root):
                continue
            first_part = os.path.relpath(source_abs, root).split(os.sep, 1)[0]
            if first_part in tool_dirs:
                # Already relocated by an earlier step/run.
                continue

            try:
                if bool(getattr(archived, "duplicate", False)):
                    target = self._move_unique(source_abs, duplicates_root, os.path.basename(source_abs))
                    if target:
                        counts["duplicates_moved_count"] += 1
                elif str(getattr(outcome, "status", "")) in {
                    "resolved",
                    "archived",
                    "manual_review",
                    "retained",
                }:
                    target, conflicted = self._verbatim_raw_target(
                        source_abs, root, raw_root, run_id
                    )
                    if target is None:
                        # 整理前发票/ already holds a byte-identical original:
                        # this copy is redundant, keep it with the duplicates.
                        target = self._move_unique(
                            source_abs, duplicates_root, os.path.basename(source_abs)
                        )
                        if target:
                            counts["duplicates_moved_count"] += 1
                    else:
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        shutil.move(source_abs, target)
                        counts["raw_moved_count"] += 1
                        if conflicted:
                            counts["warnings"].append(
                                "整理前发票中已有同名但内容不同的原件，为不改名已单独保存："
                                f"{os.path.relpath(target, raw_root)}"
                            )
                else:
                    counts["originals_kept_count"] += 1
            except OSError as exc:
                counts["originals_kept_count"] += 1
                counts["warnings"].append(
                    "原文件未能原样移入「整理前发票」，已保留原位："
                    f"{os.path.basename(source_abs)}（{type(exc).__name__}）"
                )

        self.last_relocation = counts

    def _verbatim_raw_target(
        self, source: str, root: str, raw_root: str, run_id: str
    ) -> tuple[str | None, bool]:
        """Pick a ``整理前发票/`` destination that never modifies the name.

        The original keeps its file name and, when it came from a sub-folder,
        its relative path. Returns ``(None, False)`` when the bucket already
        holds a byte-identical copy (the caller then treats the file as a
        duplicate). A genuine same-name conflict from a later run is stored
        under a run-scoped folder instead of being renamed; the second return
        value reports that fallback so the run can explain itself.
        """
        relative = os.path.relpath(os.path.abspath(source), os.path.abspath(root))
        target = os.path.join(raw_root, relative)
        if not os.path.exists(target):
            return target, False
        try:
            identical = os.path.isfile(target) and filecmp.cmp(
                source, target, shallow=False
            )
        except OSError:
            identical = False
        if identical:
            return None, False
        # Never rename: the later original goes into its own run folder.
        run_dir = os.path.join(raw_root, str(run_id or "run"))
        target = os.path.join(run_dir, relative)
        index = 2
        while os.path.exists(target):
            target = os.path.join(f"{run_dir}_{index}", relative)
            index += 1
        return target, True

    @staticmethod
    def _is_inside(path: str, root: str) -> bool:
        try:
            return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
        except ValueError:
            return False

    @staticmethod
    def _move_unique(source: str, target_dir: str, name: str) -> str:
        os.makedirs(target_dir, exist_ok=True)
        stem, ext = os.path.splitext(str(name or "document"))
        candidate = os.path.join(target_dir, f"{stem}{ext}")
        index = 2
        while os.path.exists(candidate):
            candidate = os.path.join(target_dir, f"{stem}_{index}{ext}")
            index += 1
        shutil.move(source, candidate)
        return candidate

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
            report_path = export_summary(self.api, request.resolved_output_dir)
        preview_rows = tuple(
            dict(row)
            for row in list(getattr(self.api, "processed_invoices", [])) + list(
                getattr(self.api, "error_invoices", [])
            )
        )
        relocation = dict(getattr(self, "last_relocation", {}) or {})
        migration = self.last_layout_migration
        layout_migrated = int(getattr(migration, "moved_count", 0) or 0)
        # ``layout_planned_count`` is a preview value: an applied run reports the
        # moves it performed through ``layout_migrated_count`` instead.
        layout_planned = (
            int(getattr(migration, "planned_count", 0) or 0)
            if request.dry_run
            else 0
        )
        layout_warnings = tuple(str(item) for item in getattr(migration, "warnings", ()) or ())
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
            raw_moved_count=int(relocation.get("raw_moved_count", 0) or 0),
            duplicates_moved_count=int(
                relocation.get("duplicates_moved_count", 0) or 0
            ),
            originals_kept_count=int(relocation.get("originals_kept_count", 0) or 0),
            layout_migrated_count=layout_migrated,
            layout_planned_count=layout_planned,
            report_path=report_path,
            warnings=tuple(scan.warnings)
            + layout_warnings
            + tuple(str(item) for item in relocation.get("warnings", []) or []),
            preview_rows=preview_rows,
            duration_seconds=time.monotonic() - started,
        )


def run_local_organize(api: Any, request: OrganizeRequest) -> OrganizeResult:
    return LocalOrganizer(api, request).run()

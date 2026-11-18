"""Scan an arbitrary local directory into email-compatible attachment rows.

This is the organizer's entry point for feature ② ("organize"). It never imports
the IMAP fetcher and never reads mail configuration: the only optional link to
the fetch feature is the public ``manifest.jsonl`` handoff contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import fetch_handoff

#: Directory names that never contain user invoices (tool state, build output,
#: the app's own review/retention buckets). The input directory itself is always
#: scanned, so an ``inbox/`` folder remains a valid input.
SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        "venv",
        "node_modules",
        "temp",
        "tmp",
        "staging",
        "monitoring",
        "diagnostics",
        "_audit_retention",
        "duplicates",
        "待人工复核",
        "人工复核",
        "release-assets",
        "release-bundle",
        "dist",
        "build",
    }
)

#: Tool-owned files that are not invoices even when their suffix matches.
SKIP_FILE_NAMES = frozenset(
    {
        fetch_handoff.MANIFEST_FILENAME,
        fetch_handoff.FETCH_TODO_FILENAME,
        fetch_handoff.FETCH_STATE_FILENAME,
        "processed_records.json",
        "processed_records.legacy-backup.json",
        "committed_state.json",
        ".antigravity_history.json",
        "run_state.json",
        "summary_report.xlsx",
    }
)

#: Local files are parsed as normal invoice candidates. Tier 2 mirrors the
#: "high confidence document" tier of the mailbox funnel; tier 3 would route
#: everything to manual review.
LOCAL_ATTACHMENT_TIER = 2


@dataclass(frozen=True)
class LocalDocument:
    path: str
    rel_path: str
    size: int
    sha256: str
    source: str = fetch_handoff.SOURCE_LOCAL
    provenance: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class LocalScanResult:
    root: str
    documents: tuple[LocalDocument, ...]
    skipped_duplicates: int = 0
    skipped_unsupported: int = 0
    manifest_entries: int = 0
    warnings: tuple[str, ...] = ()

    @property
    def file_count(self) -> int:
        return len(self.documents)

    def to_attachment_rows(self) -> list[dict[str, Any]]:
        return to_attachment_rows(self)


def _is_skipped_file(path: Path) -> bool:
    name = path.name
    if name in SKIP_FILE_NAMES:
        return True
    if name.startswith(".") and name not in {".pdf", ".xml"}:
        return True
    return False


def _excluded_roots(exclude_paths: Iterable[str | os.PathLike[str]]) -> list[Path]:
    roots: list[Path] = []
    for value in exclude_paths or ():
        text = str(value or "").strip()
        if not text:
            continue
        try:
            roots.append(Path(text).resolve())
        except OSError:
            continue
    return roots


def _is_under_excluded(path: Path, excluded: list[Path]) -> bool:
    resolved = path.resolve()
    for root in excluded:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def scan_local_directory(
    root: str | os.PathLike[str],
    *,
    exclude_paths: Iterable[str | os.PathLike[str]] = (),
    manifest_path: str | os.PathLike[str] | None = None,
    recursive: bool = True,
) -> LocalScanResult:
    """Collect supported documents below ``root``.

    - deterministic order (sorted directories and file names)
    - SHA256 dedupe inside one batch (same bytes are only processed once)
    - optional provenance enrichment from a fetch ``manifest.jsonl``
    """
    base = Path(root)
    if not base.exists():
        raise FileNotFoundError(f"输入文件夹不存在: {base}")
    if not base.is_dir():
        raise NotADirectoryError(f"输入路径不是文件夹: {base}")
    base = base.resolve()

    by_sha, by_rel, manifest_warnings = fetch_handoff.manifest_index(
        root=base, manifest_path=manifest_path
    )
    excluded = _excluded_roots(exclude_paths)

    documents: list[LocalDocument] = []
    seen_sha: set[str] = set()
    skipped_duplicates = 0
    skipped_unsupported = 0
    warnings: list[str] = list(manifest_warnings)

    for dirpath, dirnames, filenames in os.walk(base, topdown=True):
        current = Path(dirpath)
        keep_dirs = []
        for name in sorted(dirnames):
            candidate = current / name
            if name in SKIP_DIR_NAMES:
                continue
            if _is_under_excluded(candidate, excluded):
                continue
            keep_dirs.append(name)
        dirnames[:] = keep_dirs
        if not recursive:
            dirnames[:] = []

        for name in sorted(filenames):
            path = current / name
            if _is_skipped_file(path):
                continue
            if not fetch_handoff.is_supported_document(path):
                skipped_unsupported += 1
                continue
            if _is_under_excluded(path, excluded):
                continue
            try:
                resolved = path.resolve()
                digest = fetch_handoff.sha256_file(resolved)
                size = resolved.stat().st_size
            except OSError:
                warnings.append(f"文件无法读取，已跳过: {name}")
                continue
            if digest in seen_sha:
                skipped_duplicates += 1
                continue
            seen_sha.add(digest)
            relative = fetch_handoff.relative_posix_path(resolved, base)
            provenance_entry = by_sha.get(digest) or by_rel.get(relative)
            provenance: dict[str, Any] = {}
            if provenance_entry is not None:
                provenance = provenance_entry.to_dict()
            documents.append(
                LocalDocument(
                    path=str(resolved),
                    rel_path=relative,
                    size=size,
                    sha256=digest,
                    source=str((provenance or {}).get("source") or fetch_handoff.SOURCE_LOCAL),
                    provenance=provenance,
                )
            )

    # Manifest entries whose files vanished are reported, never silently dropped.
    for entry in by_sha.values():
        if entry.sha256 in seen_sha:
            continue
        manifest_file = base / entry.rel_path
        if not manifest_file.is_file():
            warnings.append(f"manifest 记录的文件不存在: {entry.rel_path}")

    return LocalScanResult(
        root=str(base),
        documents=tuple(documents),
        skipped_duplicates=skipped_duplicates,
        skipped_unsupported=skipped_unsupported,
        manifest_entries=len(by_sha),
        warnings=tuple(warnings),
    )


def to_attachment_rows(
    scan: LocalScanResult,
) -> list[dict[str, Any]]:
    """Convert scanned documents into the attachment-row contract used by the
    candidate/extraction pipeline (same shape as ``EmailFetcher`` results)."""
    return rows_from_documents(scan.documents)


def rows_from_documents(documents: Iterable[LocalDocument]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, document in enumerate(documents):
        provenance = dict(document.provenance or {})
        is_mail = str(provenance.get("source") or "") == fetch_handoff.SOURCE_MAIL
        row: dict[str, Any] = {
            "filepath": document.path,
            "tier": LOCAL_ATTACHMENT_TIER,
            "subject": str(provenance.get("subject") or ""),
            "sender": str(provenance.get("sender") or ""),
            "is_url": False,
            "original_filename": str(
                provenance.get("orig_name") or os.path.basename(document.path)
            ),
            "email_id": str(provenance.get("uid") or f"local-{index}"),
            "channel": "mail" if is_mail else "local",
            "source": fetch_handoff.SOURCE_MAIL if is_mail else fetch_handoff.SOURCE_LOCAL,
            "candidate_action": "",
            "prefilter_reason_code": "",
        }
        for key in (
            "mailbox",
            "uid",
            "uidvalidity",
            "message_id",
            "msg_part",
            "received_at",
            "sha256",
        ):
            value = provenance.get(key)
            if value:
                row[key] = value
        rows.append(row)
    return rows

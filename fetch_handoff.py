"""Handoff contract between email extraction (fetch) and local organizing.

The two features are deliberately decoupled:

* fetch  : mailbox -> files + ``manifest.jsonl`` (no parsing at all)
* organize: any local directory -> archive + ledger (never reads mail config)

Both sides only share this module's on-disk format. It contains no IMAP code and
no invoice-parsing code, so either side can be used on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

MANIFEST_FILENAME = "manifest.jsonl"
FETCH_TODO_FILENAME = "fetch_todo.jsonl"
FETCH_STATE_FILENAME = ".fetch_state.json"
INBOX_DIRNAME = "inbox"

SOURCE_MAIL = "mail"
SOURCE_LOCAL = "local"

#: File types the organizer understands. Kept next to the handoff contract so a
#: fetch-only run can decide what to save without importing the parser.
SUPPORTED_DOCUMENT_SUFFIXES = frozenset(
    {".pdf", ".ofd", ".xml", ".jpg", ".jpeg", ".png", ".webp"}
)

_SAFE_NAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MAX_NAME_BYTES = 120


def sha256_file(path: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> str:
    """Streaming SHA256 used by both the inbox writer and the local scanner."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_handoff_filename(name: str) -> str:
    """Return a filesystem-safe attachment name while keeping the extension."""
    text = str(name or "").strip().replace("\r", " ").replace("\n", " ")
    text = _SAFE_NAME_RE.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = "attachment"
    stem, suffix = os.path.splitext(text)
    encoded = stem.encode("utf-8")
    while len(encoded) > _MAX_NAME_BYTES and len(stem) > 1:
        stem = stem[:-1]
        encoded = stem.encode("utf-8")
    return f"{stem}{suffix}"


def is_supported_document(path: str | os.PathLike[str]) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_DOCUMENT_SUFFIXES


def relative_posix_path(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        relative = Path(path.name)
    return relative.as_posix()


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class ManifestEntry:
    """One line of ``manifest.jsonl`` (public, hand-writable contract)."""

    sha256: str
    rel_path: str
    orig_name: str
    ext: str
    size: int
    source: str = SOURCE_MAIL
    mailbox: str = ""
    uid: str = ""
    uidvalidity: str = ""
    message_id: str = ""
    msg_part: str = ""
    subject: str = ""
    sender: str = ""
    received_at: str = ""
    fetched_at: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "rel_path": self.rel_path,
            "orig_name": self.orig_name,
            "ext": self.ext,
            "size": int(self.size),
            "source": self.source,
            "mailbox": self.mailbox,
            "uid": self.uid,
            "uidvalidity": self.uidvalidity,
            "message_id": self.message_id,
            "msg_part": self.msg_part,
            "subject": self.subject,
            "sender": self.sender,
            "received_at": self.received_at,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ManifestEntry":
        sha = _optional_text(payload.get("sha256")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("manifest entry sha256 must be a lowercase sha256 hex digest")
        rel_path = _optional_text(payload.get("rel_path")).replace("\\", "/").lstrip("/")
        orig_name = _optional_text(payload.get("orig_name")) or os.path.basename(rel_path)
        ext = _optional_text(payload.get("ext")).lower() or Path(orig_name).suffix.lower()
        try:
            size = int(payload.get("size") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("manifest entry size must be an integer") from exc
        source = _optional_text(payload.get("source")) or SOURCE_MAIL
        return cls(
            sha256=sha,
            rel_path=rel_path,
            orig_name=orig_name,
            ext=ext.lstrip("."),
            size=size,
            source=source,
            mailbox=_optional_text(payload.get("mailbox")),
            uid=_optional_text(payload.get("uid")),
            uidvalidity=_optional_text(payload.get("uidvalidity")),
            message_id=_optional_text(payload.get("message_id")),
            msg_part=_optional_text(payload.get("msg_part")),
            subject=_optional_text(payload.get("subject")),
            sender=_optional_text(payload.get("sender")),
            received_at=_optional_text(payload.get("received_at")),
            fetched_at=_optional_text(payload.get("fetched_at")),
        )


def read_manifest(
    manifest_path: str | os.PathLike[str],
) -> tuple[list[ManifestEntry], list[str]]:
    """Read a manifest tolerantly.

    Malformed lines are reported through the warning list instead of aborting a
    run: manifests are documented as hand-editable, so a broken line must not
    destroy the whole inbox.
    """
    path = Path(manifest_path)
    entries: list[ManifestEntry] = []
    warnings: list[str] = []
    if not path.is_file():
        return entries, warnings
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    warnings.append(f"manifest 第 {line_number} 行不是合法 JSON，已跳过")
                    continue
                if not isinstance(payload, dict):
                    warnings.append(f"manifest 第 {line_number} 行不是对象，已跳过")
                    continue
                try:
                    entries.append(ManifestEntry.from_dict(payload))
                except ValueError as exc:
                    warnings.append(f"manifest 第 {line_number} 行无效：{exc}")
    except OSError as exc:
        warnings.append(f"manifest 读取失败：{type(exc).__name__}")
    return entries, warnings


def append_manifest(
    manifest_path: str | os.PathLike[str],
    entries: Iterable[ManifestEntry],
) -> None:
    path = Path(manifest_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False))
            handle.write("\n")


def append_todo(path: str | os.PathLike[str], record: Mapping[str, Any]) -> None:
    """Record something a fetch-only run could not save (e.g. a portal link)."""
    todo_path = Path(path)
    todo_path.parent.mkdir(parents=True, exist_ok=True)
    with open(todo_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), ensure_ascii=False, default=str))
        handle.write("\n")


def load_fetch_state(path: str | os.PathLike[str]) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.is_file():
        return {}
    try:
        with open(state_path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_fetch_state(path: str | os.PathLike[str], payload: Mapping[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_name(state_path.name + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, indent=2, default=str)
    os.replace(temp_path, state_path)


def date_bucket(iso_timestamp: str, *, fallback: datetime | None = None) -> str:
    """Return ``YYYY/MM`` for the inbox layout, tolerating broken timestamps."""
    text = _optional_text(iso_timestamp)
    if text:
        candidate = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            parsed = None
        if parsed is not None:
            return f"{parsed.year:04d}/{parsed.month:02d}"
    moment = fallback or datetime.now()
    return f"{moment.year:04d}/{moment.month:02d}"


class InboxWriter:
    """Write fetch results into ``inbox/`` and append their manifest lines.

    Idempotent by content SHA256: saving the same attachment twice returns the
    existing entry and does not duplicate the file or the manifest line.
    """

    def __init__(
        self,
        inbox_dir: str | os.PathLike[str],
        *,
        manifest_path: str | os.PathLike[str] | None = None,
        todo_path: str | os.PathLike[str] | None = None,
        state_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.root = Path(inbox_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = Path(manifest_path) if manifest_path else self.root / MANIFEST_FILENAME
        self.todo_path = Path(todo_path) if todo_path else self.root / FETCH_TODO_FILENAME
        self.state_path = Path(state_path) if state_path else self.root / FETCH_STATE_FILENAME
        entries, warnings = read_manifest(self.manifest_path)
        self.warnings: list[str] = warnings
        self._by_sha: dict[str, ManifestEntry] = {}
        self._by_rel: dict[str, ManifestEntry] = {}
        for entry in entries:
            self._by_sha.setdefault(entry.sha256, entry)
            self._by_rel.setdefault(entry.rel_path, entry)

    def existing(self, sha256: str) -> ManifestEntry | None:
        return self._by_sha.get(str(sha256 or "").lower())

    def _target_for(self, sha256: str, orig_name: str, *, received_at: str) -> Path:
        bucket = date_bucket(received_at)
        safe_name = safe_handoff_filename(orig_name)
        stem, suffix = os.path.splitext(safe_name)
        filename = f"{sha256[:8]}_{stem}{suffix}"
        target = self.root / bucket / filename
        if target.exists() and sha256_file(target) != sha256:
            for index in range(2, 1000):
                candidate = self.root / bucket / f"{sha256[:8]}_{stem}_{index}{suffix}"
                if not candidate.exists():
                    return candidate
            raise OSError("无法为提取结果分配唯一文件名")
        return target

    def save_attachment(
        self,
        source_path: str | os.PathLike[str],
        *,
        orig_name: str = "",
        sha256: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ManifestEntry:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(f"attachment source not found: {source}")
        meta = dict(metadata or {})
        digest = str(sha256 or meta.get("sha256") or "").strip().lower()
        if not digest:
            digest = sha256_file(source)
        existing = self._by_sha.get(digest)
        if existing is not None:
            return existing

        name = str(orig_name or meta.get("original_filename") or source.name)
        received_at = _optional_text(meta.get("received_at"))
        target = self._target_for(digest, name, received_at=received_at)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.with_name(target.name + ".part")
        with open(source, "rb") as reader, open(temp_path, "wb") as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(chunk)
        os.replace(temp_path, target)

        rel_path = relative_posix_path(target, self.root)
        entry = ManifestEntry(
            sha256=digest,
            rel_path=rel_path,
            orig_name=name,
            ext=target.suffix.lower().lstrip("."),
            size=target.stat().st_size,
            source=_optional_text(meta.get("source")) or SOURCE_MAIL,
            mailbox=_optional_text(meta.get("mailbox")),
            uid=_optional_text(meta.get("uid")),
            uidvalidity=_optional_text(meta.get("uidvalidity")),
            message_id=_optional_text(meta.get("message_id")),
            msg_part=_optional_text(meta.get("msg_part")),
            subject=_optional_text(meta.get("subject")),
            sender=_optional_text(meta.get("sender")),
            received_at=_optional_text(meta.get("received_at")),
            fetched_at=_optional_text(meta.get("fetched_at")) or utc_now_iso(),
        )
        append_manifest(self.manifest_path, [entry])
        self._by_sha[digest] = entry
        self._by_rel[rel_path] = entry
        return entry

    def record_todo(self, record: Mapping[str, Any]) -> None:
        payload = dict(record)
        payload.setdefault("recorded_at", utc_now_iso())
        append_todo(self.todo_path, payload)

    def save_state(self, payload: Mapping[str, Any]) -> None:
        save_fetch_state(self.state_path, payload)


def manifest_index(
    *,
    root: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str] | None = None,
) -> tuple[dict[str, ManifestEntry], dict[str, ManifestEntry], list[str]]:
    """Index a manifest by SHA256 and by POSIX relative path (for organizers)."""
    base = Path(root)
    path = Path(manifest_path) if manifest_path else base / MANIFEST_FILENAME
    entries, warnings = read_manifest(path)
    by_sha: dict[str, ManifestEntry] = {}
    by_rel: dict[str, ManifestEntry] = {}
    for entry in entries:
        by_sha.setdefault(entry.sha256, entry)
        by_rel.setdefault(entry.rel_path, entry)
    return by_sha, by_rel, warnings

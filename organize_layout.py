"""Archive layout re-migration for the local folder organizer.

Local organizing can arrange archived invoices in two layouts:

- category layout (the product checkbox 按分类分目录): one subfolder per document
  type (``打车/``, ``餐饮/``, ...);
- flat layout: every archived invoice sits directly in the archive root, with the
  category kept in the file name.

The organizer never re-processes files it produced itself (that would only move
them into ``duplicates/``), so a run that starts on a folder an earlier run
already organized has to move those archive files itself when the requested
layout differs. :func:`enforce_layout` recognises the organizer's own output by
the file names it generates and moves only those files; anything the organizer
did not produce (user documents, custom subfolders, ``整理前发票/``,
``duplicates/``, ``待人工复核/`` ...) is never touched.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import functools
import os
import re
import shutil
import stat

#: File suffixes the organizer can archive (mirrors ``fetch_handoff``).
ARCHIVE_SUFFIXES: tuple[str, ...] = (
    ".pdf",
    ".ofd",
    ".xml",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
)

#: Public alias: the archive suffixes a layout migration may move.
SUPPORTED_LAYOUT_SUFFIXES = ARCHIVE_SUFFIXES

#: Folder that keeps processed originals untouched: original file name,
#: original content, no month sub-folders.
ORIGINALS_DIR_NAME = "整理前发票"

#: Older builds saved the same bucket as ``raw/``. It stays recognised as a
#: tool-owned folder so an old bucket is never rescanned as new input and an
#: applied in-place run can rename it to :data:`ORIGINALS_DIR_NAME`.
LEGACY_ORIGINALS_DIR_NAME = "raw"
LEGACY_ORIGINALS_DIR_NAMES = frozenset({LEGACY_ORIGINALS_DIR_NAME})

#: Root-level folders that the in-place organizer treats as its own buckets.
#: Re-layout never moves archived invoices out of them or into them.
IN_PLACE_TOOL_DIR_NAMES = frozenset(
    {
        ORIGINALS_DIR_NAME,
        *LEGACY_ORIGINALS_DIR_NAMES,
        "duplicates",
        "_audit_retention",
        "待人工复核",
        "人工复核",
        ".local-staging",
        # User/global classification rules live inside the invoice library and
        # must never be rescanned as invoice input.
        "rules",
    }
)

_TRAIN_TYPE = "火车票"


def category_folder_names(extra: Iterable[str] = ()) -> frozenset[str]:
    """Folder names the category layout can create.

    ``extra`` carries user-configured archive folders; the default set stays
    exactly the document-type registry so existing callers are unchanged.
    """
    from document_types import DOCUMENT_TYPES

    folders = {
        str(entry.get("archive_folder") or "").strip()
        for entry in DOCUMENT_TYPES.values()
    }
    folders.discard("")
    folders.update(
        str(name or "").strip()
        for name in extra
        if str(name or "").strip()
    )
    folders.difference_update(IN_PLACE_TOOL_DIR_NAMES)
    return frozenset(folders)


def archive_dir_names(extra: Iterable[str] = ()) -> frozenset[str]:
    """Per-category archive folders plus the organizer's own tool buckets."""
    return frozenset(category_folder_names(extra=extra)) | IN_PLACE_TOOL_DIR_NAMES


@functools.lru_cache(maxsize=1)
def _display_type_folders() -> dict[str, str]:
    """Map every display type the archive step can put in a file name to a folder.

    ``invoice_extractor._plan_archive_target`` writes ``display_type`` into the
    file name: the normalized document type, ``<type>行程单`` for ride
    itineraries, or ``住宿水单`` for hotel folios. The archive folder is resolved
    from the underlying registered type, exactly like the category layout does.
    """
    from document_types import DOCUMENT_TYPES, get_archive_folder

    mapping: dict[str, str] = {}
    for doc_type in DOCUMENT_TYPES:
        mapping[doc_type] = get_archive_folder(doc_type)
        itinerary = f"{doc_type}行程单"
        mapping.setdefault(itinerary, get_archive_folder(doc_type))
    return mapping


@functools.lru_cache(maxsize=1)
def _standard_name_re() -> re.Pattern[str]:
    display_types = sorted(_display_type_folders(), key=len, reverse=True)
    alternation = "|".join(re.escape(token) for token in display_types)
    suffixes = "|".join(re.escape(suffix.lstrip(".")) for suffix in ARCHIVE_SUFFIXES)
    return re.compile(
        r"^(?P<date>\d{4}[^_]*)_"
        rf"(?P<type>{alternation})_"
        r"(?P<amount>[-\d.]+)_"
        rf"(?P<seller>.+)\.(?:{suffixes})$",
        re.IGNORECASE,
    )


@functools.lru_cache(maxsize=1)
def _train_name_re() -> re.Pattern[str]:
    suffixes = "|".join(re.escape(suffix.lstrip(".")) for suffix in ARCHIVE_SUFFIXES)
    return re.compile(
        rf"^\d{{4}}[^_]*?(?:-[^-]+){{2}}-{_TRAIN_TYPE}\.(?:{suffixes})$",
        re.IGNORECASE,
    )


@functools.lru_cache(maxsize=1)
def _paired_name_re() -> re.Pattern[str]:
    """Paired archive renames produced by ``archive_pairing.build_*_pair_renames``."""
    suffixes = "|".join(re.escape(suffix.lstrip(".")) for suffix in ARCHIVE_SUFFIXES)
    return re.compile(
        rf"^(?P<date>\d{{4,8}})-(?P<seller>[^-]+)-\d{{2}}-"
        rf"(?P<role>发票|行程单|水单)_(?P<amount>[-\d.]+)元\.(?:{suffixes})$",
        re.IGNORECASE,
    )


def _paired_category(text: str) -> str | None:
    """Derive the category of a paired archive rename from its platform/role text.

    The pairing step only renames inside ``打车/`` (平台 token: 滴滴/高德) and
    ``住宿发票/`` (``住宿`` token), so those tokens are enough to re-file a pair.
    """
    from document_types import get_archive_folder

    if "住宿" in text:
        return get_archive_folder("住宿发票")
    if any(token in text for token in ("滴滴", "高德", "约车", "盛智", "畅行", "打车", "出租")):
        return get_archive_folder("打车")
    return None


@functools.lru_cache(maxsize=1)
def _organized_output_name_re() -> re.Pattern[str]:
    suffixes = "|".join(re.escape(suffix.lstrip(".")) for suffix in ARCHIVE_SUFFIXES)
    display_types = sorted(_display_type_folders(), key=len, reverse=True)
    alternation = "|".join(re.escape(token) for token in display_types)
    return re.compile(
        r"^(?:"
        r"\d{4}[^_]*_"
        rf"(?:{alternation})_"
        r"[-\d.]+_.+"
        rf"|\d{{4}}[^_]*?(?:-[^-]+){{2}}-{_TRAIN_TYPE}"
        r"|\d{4,8}-[^-]+-\d{2}-(?:发票|行程单|水单)_[-\d.]+元"
        rf")\.(?:{suffixes})$",
        re.IGNORECASE,
    )


def _display_type_document_type(display_type: str) -> str:
    """Map a file-name display type back to a registered document type."""
    from document_types import DOCUMENT_TYPES, normalize_document_type

    value = str(display_type or "").strip()
    if value in DOCUMENT_TYPES:
        return value
    if value.endswith("行程单") and value[:-3] in DOCUMENT_TYPES:
        return value[:-3]
    return normalize_document_type(value)


def archive_name_fields(name: str) -> dict[str, str] | None:
    """Best-effort invoice fields recoverable from an organizer output name."""
    text = str(name or "").strip()
    if not text or os.path.basename(text) != text:
        return None
    standard = _standard_name_re().match(text)
    if standard is not None:
        return {
            "type": _display_type_document_type(standard.group("type")),
            "seller": standard.group("seller"),
            "item": "",
            "amount": standard.group("amount"),
            "purchaser": "",
        }
    if _train_name_re().match(text):
        return {
            "type": _TRAIN_TYPE,
            "seller": "中国铁路",
            "item": "",
            "amount": "",
            "purchaser": "",
        }
    paired = _paired_name_re().match(text)
    if paired is not None:
        role = paired.group("role")
        return {
            "type": "住宿水单" if role == "水单" else "",
            "seller": paired.group("seller"),
            "item": "",
            "amount": paired.group("amount"),
            "purchaser": "",
        }
    return None


def organized_output_category(
    name: str, rule_set: object | None = None
) -> str | None:
    """Return the category folder for an organizer-produced archive name.

    ``name`` is a plain file name (no directories). ``None`` means the name was
    not produced by the organizer, or its category cannot be derived from the
    name alone (a paired archive rename whose platform/role gives no category).
    When ``rule_set`` is supplied, keyword/amount/type rules are re-evaluated
    against fields recoverable from the name; unknown classifications fall back
    to the built-in type folder so a layout switch never dumps files into review.
    """
    text = str(name or "").strip()
    if not text or os.path.basename(text) != text:
        return None
    if rule_set is not None:
        fields = archive_name_fields(text)
        if fields is not None:
            try:
                from expense_rules import classify

                result = classify(fields, rule_set)
                folder = str(getattr(result, "archive_folder", "") or "").strip()
                if (
                    str(getattr(result, "source", "") or "") != "unknown"
                    and folder
                    and folder not in IN_PLACE_TOOL_DIR_NAMES
                    and os.path.basename(folder) == folder
                ):
                    return folder
            except Exception:
                pass
    standard = _standard_name_re().match(text)
    if standard is not None:
        display_type = standard.group("type")
        folders = _display_type_folders()
        if display_type in folders:
            return folders[display_type]
        folded = {key.casefold(): value for key, value in folders.items()}
        return folded.get(display_type.casefold())
    if _train_name_re().match(text):
        from document_types import get_archive_folder

        return get_archive_folder(_TRAIN_TYPE)
    if _paired_name_re().match(text):
        return _paired_category(text)
    return None


def is_organized_output_name(name: str) -> bool:
    """True when ``name`` is a file name the organizer itself produces."""
    return _organized_output_name_re().match(str(name or "")) is not None


def organized_output_name_re() -> re.Pattern[str]:
    """Regex matching exactly the file names :func:`is_organized_output_name` accepts."""
    return _organized_output_name_re()


@dataclass(frozen=True)
class LayoutMigration:
    """Result of enforcing the requested archive layout before scanning."""

    layout: str
    dry_run: bool
    planned: tuple[tuple[str, str], ...] = ()
    moved: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def planned_count(self) -> int:
        return len(self.planned)

    @property
    def moved_count(self) -> int:
        return len(self.moved)


def _is_linklike(path: str) -> bool:
    """True when ``path`` is a symlink/junction/reparse point or unreadable.

    Re-layout must never walk through a link: a junction named like a category
    folder would otherwise move files into (or out of) a directory outside the
    archive root.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_reparse_tag", 0))


def _is_inside_root(path: str, root: str) -> bool:
    """True when the resolved ``path`` stays inside the resolved archive root."""
    try:
        resolved = os.path.realpath(path)
        base = os.path.realpath(root)
        return os.path.commonpath([resolved, base]) == base
    except (OSError, ValueError):
        return False


def _plan_category_layout(
    root: str,
    rule_set: object | None = None,
    file_category_map: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Archive files sitting in the root that belong in a category folder."""
    planned: list[tuple[str, str]] = []
    declared = dict(file_category_map or {})
    from expense_rules import is_safe_folder_name

    for name in sorted(os.listdir(root)):
        source = os.path.join(root, name)
        if _is_linklike(source) or not os.path.isfile(source):
            continue
        category = str(declared.get(name) or "").strip()
        if category and (
            not is_safe_folder_name(category)
            or category in IN_PLACE_TOOL_DIR_NAMES
            or os.path.basename(category) != category
        ):
            category = ""
        if not category:
            category = organized_output_category(name, rule_set=rule_set)
        if not category:
            continue
        target_dir = os.path.join(root, category)
        if os.path.abspath(target_dir) == os.path.abspath(root):
            continue
        if _is_linklike(target_dir):
            # Never write through a junction/symlink that impersonates a folder.
            continue
        if os.path.exists(target_dir) and not os.path.isdir(target_dir):
            # A user file occupies the folder name; leave the archive in place.
            continue
        planned.append((source, os.path.join(target_dir, name)))
    return planned


def _plan_flat_layout(
    root: str, extra_category_folders: Iterable[str] = ()
) -> list[tuple[str, str]]:
    """Archive files inside category folders that belong in the root."""
    planned: list[tuple[str, str]] = []
    for folder in sorted(
        category_folder_names(extra=extra_category_folders)
    ):
        category_dir = os.path.join(root, folder)
        if _is_linklike(category_dir) or not os.path.isdir(category_dir):
            continue
        for name in sorted(os.listdir(category_dir)):
            source = os.path.join(category_dir, name)
            if _is_linklike(source) or not os.path.isfile(source):
                continue
            if not is_organized_output_name(name):
                continue
            planned.append((source, os.path.join(root, name)))
    return planned


def _move_unique(source: str, target: str) -> str:
    """Move ``source`` to ``target`` without overwriting an existing file."""
    stem, suffix = os.path.splitext(target)
    candidate = target
    index = 2
    while os.path.exists(candidate):
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    os.makedirs(os.path.dirname(candidate), exist_ok=True)
    shutil.move(source, candidate)
    return candidate


def _prune_empty_category_dirs(
    root: str, extra_category_folders: Iterable[str] = ()
) -> None:
    """Remove known category folders that the flat layout left empty."""
    for folder in sorted(
        category_folder_names(extra=extra_category_folders)
    ):
        candidate = os.path.join(root, folder)
        if _is_linklike(candidate) or not os.path.isdir(candidate):
            continue
        try:
            if not os.listdir(candidate):
                os.rmdir(candidate)
        except OSError:
            continue


def enforce_layout(
    archive_root: str,
    *,
    split_by_category: bool,
    dry_run: bool = False,
    extra_category_folders: Iterable[str] = (),
    rule_set: object | None = None,
    file_category_map: dict[str, str] | None = None,
) -> LayoutMigration:
    """Move the organizer's own archive files to the requested layout.

    ``archive_root`` is the folder the organizer archives into (the resolved
    output folder: the invoice folder itself for in-place organizing). The
    function is best-effort: a file that cannot be moved stays where it is and
    becomes a warning; it never raises for a single file and never touches files
    the organizer did not produce.
    """
    layout = "category" if split_by_category else "flat"
    root = os.path.abspath(str(archive_root or "").strip())
    if not str(archive_root or "").strip() or not os.path.isdir(root):
        return LayoutMigration(layout=layout, dry_run=bool(dry_run))

    try:
        planned = (
            _plan_category_layout(
                root, rule_set=rule_set, file_category_map=file_category_map
            )
            if split_by_category
            else _plan_flat_layout(root, extra_category_folders)
        )
    except OSError:
        return LayoutMigration(layout=layout, dry_run=bool(dry_run))

    if dry_run:
        return LayoutMigration(
            layout=layout, dry_run=True, planned=tuple(planned)
        )

    moved: list[tuple[str, str]] = []
    warnings: list[str] = []
    for source, target in planned:
        if not _is_inside_root(os.path.dirname(target), root):
            warnings.append(
                f"未能调整归档位置：{os.path.basename(source)}（目标文件夹不可用）"
            )
            continue
        try:
            final_path = _move_unique(source, target)
        except OSError as exc:
            warnings.append(
                f"未能调整归档位置：{os.path.basename(source)}（{type(exc).__name__}）"
            )
            continue
        moved.append((source, final_path))

    if not split_by_category:
        _prune_empty_category_dirs(root, extra_category_folders)

    return LayoutMigration(
        layout=layout,
        dry_run=False,
        planned=tuple(planned),
        moved=tuple(moved),
        warnings=tuple(warnings),
    )

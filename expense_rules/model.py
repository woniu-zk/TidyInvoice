"""Data model shared by the InvoiceFlowAI classification-rules core.

This module is dependency-light on purpose: it defines the immutable values,
the configuration exception and the folder-name safety policy that the loader,
the matcher and the persistence layer all agree on. Nothing in here touches the
filesystem.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Any

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

#: Category ids are the stable configuration keys (lower-case snake case).
CATEGORY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: Longest folder name the archive layer accepts (same budget the organizer uses).
MAX_FOLDER_NAME_LENGTH = 64

#: Rules scopes: user-wide (settings dir) and per invoice library.
SCOPE_GLOBAL = "global"
SCOPE_LIBRARY = "library"
RULE_SCOPES = (SCOPE_GLOBAL, SCOPE_LIBRARY)

#: Where a category definition came from (render as "内置/自定义" in the UI).
CATEGORY_SOURCE_BUILTIN = "builtin"
CATEGORY_SOURCE_USER = "user"
CATEGORY_SOURCE_UNKNOWN = "unknown"

#: How a document was classified (``ClassificationResult.source``).
SOURCE_DICTIONARY = "dictionary"
SOURCE_USER_RULE = "user_rule"
SOURCE_RULE_PACK = "rule_pack"
SOURCE_BUILTIN_KEYWORD = "builtin_keyword"
SOURCE_BUILTIN_TYPE = "builtin_type"
SOURCE_UNKNOWN = "unknown"

#: Fields a rule can match on. ``any`` is accepted as a friendly alias for
#: ``seller_item`` in user-edited YAML (the UI uses ``any``).
MATCH_SELLER = "seller"
MATCH_ITEM = "item"
MATCH_SELLER_ITEM = "seller_item"
MATCH_ANY = "any"
MATCH_FIELDS = (MATCH_SELLER, MATCH_ITEM, MATCH_SELLER_ITEM, MATCH_ANY)
DEFAULT_MATCH = MATCH_SELLER_ITEM

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

#: Category entry fields the loader understands. Anything else is a warning so
#: a typo is reported instead of being silently ignored.
KNOWN_CATEGORY_FIELDS = frozenset(
    {
        "id",
        "name",
        "archive_folder",
        "priority",
        "enabled",
        "keywords",
        "exclude_keywords",
        "invoice_types",
        "amount_range",
        "match",
        "description",
        "auto_folder",
        "target_type",
    }
)

#: Top-level keys of a ``categories.yaml`` / rule-pack file.
KNOWN_CATEGORIES_FILE_FIELDS = frozenset(
    {"version", "categories", "fallback", "type_categories"}
)
KNOWN_TERMS_FILE_FIELDS = frozenset({"version", "terms"})

#: Tool-owned buckets inside an invoice library. A category must never be able
#: to archive into one of them: the organizer relies on them staying separate.
RESERVED_FOLDER_NAMES = frozenset(
    {
        "待人工复核",
        "人工复核",
        "整理前发票",
        "raw",
        "duplicates",
        "_audit_retention",
        ".local-staging",
        "inbox",
        "rules",
        "非目标公司发票",
        "个人非报销发票",
    }
)
_RESERVED_FOLDER_NAMES_CASEFOLDED = frozenset(
    name.casefold() for name in RESERVED_FOLDER_NAMES
)

#: Windows reserves these device names (with or without an extension).
WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)

_FORBIDDEN_FOLDER_CHARS = frozenset('/\\:*?"<>|')


# --------------------------------------------------------------------------- #
# Text normalization
# --------------------------------------------------------------------------- #


def normalize_text(value: object) -> str:
    """NFKC + casefold + whitespace-free form used for keyword/name matching."""
    text = "" if value is None else str(value)
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for char in normalized if not char.isspace())


def normalize_tin(value: object) -> str:
    """Uppercase, whitespace-free form used for exact seller-tax-id matching."""
    text = "" if value is None else str(value)
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).upper()
    return "".join(char for char in normalized if not char.isspace())


# --------------------------------------------------------------------------- #
# Folder-name safety
# --------------------------------------------------------------------------- #


def is_safe_folder_name(value: object) -> bool:
    """True when ``value`` is a safe single-segment archive folder name.

    Rejects path separators, Windows-forbidden characters, control characters,
    trailing dots/spaces, reserved device names and the organizer's own tool
    buckets, plus over-long names.
    """
    if not isinstance(value, str):
        return False
    text = value
    if not text or text in {".", ".."}:
        return False
    if len(text) > MAX_FOLDER_NAME_LENGTH:
        return False
    # Trailing spaces are dropped by Windows APIs and the resulting folder can
    # collide with another category; trailing dots have the same problem.
    if text != text.rstrip(" "):
        return False
    if text.endswith("."):
        return False
    if any(char in _FORBIDDEN_FOLDER_CHARS for char in text):
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return False
    if text.casefold() in _RESERVED_FOLDER_NAMES_CASEFOLDED:
        return False
    device_stem = text.split(".", 1)[0].rstrip(" ").casefold()
    if device_stem in WINDOWS_RESERVED_DEVICE_NAMES:
        return False
    return True


# --------------------------------------------------------------------------- #
# Keyword / amount based folder naming (``auto_folder`` rules)
# --------------------------------------------------------------------------- #


def sanitize_rule_keyword(value: object) -> str:
    """Turn a rule keyword into the folder-safe core of an automatic folder.

    Applies NFKC, replaces path separators, Windows-forbidden characters and
    control characters with ``-``, collapses whitespace to single spaces and
    trims trailing dots/spaces. May return ``""`` when nothing usable remains.
    """
    text = "" if value is None else str(value)
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).strip()
    if not text:
        return ""
    # Whitespace (including tabs/newlines) collapses to a single space first so
    # a multi-line keyword does not become a row of dashes.
    text = re.sub(r"\s+", " ", text)
    cleaned = "".join(
        "-"
        if char in _FORBIDDEN_FOLDER_CHARS or ord(char) < 32 or ord(char) == 127
        else char
        for char in text
    )
    return cleaned.strip().rstrip(" .")


def _amount_bound_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("金额边界必须是数字或 null")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"无效的金额边界: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"金额边界必须是有限数: {value!r}")
    return amount


def format_amount_bound(value: object) -> str:
    """Trimmed numeric text for an amount bound (``100.0`` -> ``100``)."""
    amount = _amount_bound_decimal(value)
    if amount is None:
        return ""
    text = format(amount.normalize(), "f")
    return "0" if text == "-0" else text


def amount_range_folder_suffix(amount_range: object) -> str:
    """Folder-name suffix describing an amount range.

    ``None``/empty -> ``""``; equal bounds -> the value; lower only ->
    ``"<min>以上"``; upper only -> ``"<max>以下"``; both -> ``"<min>-<max>"``
    for non-negative ranges and ``"<min>至<max>"`` when a bound is negative.
    """
    if amount_range is None:
        return ""
    if isinstance(amount_range, (str, bytes)) or isinstance(amount_range, Mapping):
        raise ValueError("amount_range 必须是金额边界列表")
    try:
        values = list(amount_range)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("amount_range 必须是金额边界列表") from exc
    if not values:
        return ""
    if len(values) > 2:
        raise ValueError("amount_range 最多包含两个金额边界")
    lower_value = _amount_bound_decimal(values[0])
    upper_value = _amount_bound_decimal(values[1]) if len(values) > 1 else None
    lower_text = format_amount_bound(lower_value)
    upper_text = format_amount_bound(upper_value)
    if lower_text and upper_text:
        if lower_text == upper_text:
            return lower_text
        if (lower_value is not None and lower_value < 0) or (
            upper_value is not None and upper_value < 0
        ):
            return f"{lower_text}至{upper_text}"
        return f"{lower_text}-{upper_text}"
    if lower_text:
        return f"{lower_text}以上"
    if upper_text:
        return f"{upper_text}以下"
    return ""


def folder_from_keyword(keyword: object, amount_range: object = None) -> str:
    """Derive the archive folder for an ``auto_folder`` rule.

    The folder is ``sanitize_rule_keyword(keyword)`` plus
    :func:`amount_range_folder_suffix`, truncated to
    :data:`MAX_FOLDER_NAME_LENGTH` characters (the keyword part is shortened
    first so the suffix always fits). Raises :class:`ValueError` when the
    keyword yields no usable folder core.
    """
    sanitized = sanitize_rule_keyword(keyword)
    if not sanitized:
        raise ValueError("规则关键词无法生成文件夹名（关键词为空或全部为非法字符）")
    suffix = amount_range_folder_suffix(amount_range)
    room = MAX_FOLDER_NAME_LENGTH - len(suffix)
    if room <= 0:
        combined = sanitized + suffix
    else:
        base = sanitized[:room].rstrip(" .")
        if not base:
            base = sanitized[:room]
        combined = base + suffix
    combined = combined[:MAX_FOLDER_NAME_LENGTH].rstrip(" .")
    if not combined:
        raise ValueError("规则关键词无法生成文件夹名")
    return combined


def folder_from_type_and_amount(type_name: object, amount_range: object = None) -> str:
    """Derive the archive folder for a ``target_type`` rule.

    The folder is ``<target_type>`` without an amount range, otherwise
    ``<target_type>-<suffix>`` reusing :func:`amount_range_folder_suffix`
    (``酒店-100-200``, ``酒店-100以上``, ``酒店-100`` ...). Raises
    :class:`ValueError` for an empty type name or a folder longer than
    :data:`MAX_FOLDER_NAME_LENGTH`.
    """
    base = "" if type_name is None else str(type_name).strip()
    if not base:
        raise ValueError("目标票种名称不能为空")
    suffix = amount_range_folder_suffix(amount_range)
    folder = base if not suffix else f"{base}-{suffix}"
    if len(folder) > MAX_FOLDER_NAME_LENGTH:
        raise ValueError(
            f"目标票种与金额生成的文件夹名超过 {MAX_FOLDER_NAME_LENGTH} 个字符: {folder!r}"
        )
    return folder


# --------------------------------------------------------------------------- #
# Source tracking / issues
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourceRef:
    """Where a merged configuration value came from."""

    file: str = ""
    line: int = 0
    layer_index: int = -1
    kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "layer_index": self.layer_index,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class RuleIssue:
    """One configuration problem, located at ``file:line`` when possible."""

    file: str
    line: int
    message: str
    severity: str = SEVERITY_ERROR

    def __str__(self) -> str:
        location = f"{self.file}:{self.line}" if self.file else str(self.line)
        return f"{location}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "severity": self.severity,
        }


class RuleConfigError(ValueError):
    """Raised when a rule configuration contains errors.

    ``issues`` keeps every collected issue (errors and warnings) so the caller
    can render an editor-style diagnostics list. Warnings alone never raise.
    """

    def __init__(self, issues: tuple[RuleIssue, ...] | list[RuleIssue]) -> None:
        self.issues: tuple[RuleIssue, ...] = tuple(issues)
        error_lines = [str(issue) for issue in self.issues if issue.severity == SEVERITY_ERROR]
        all_lines = [str(issue) for issue in self.issues]
        rendered = error_lines or all_lines
        message = "分类规则配置有误"
        if rendered:
            message = f"{message}:\n" + "\n".join(rendered)
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Effective configuration values
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CategoryRule:
    """The effective (merged) definition of one category/rule.

    ``target_type`` (optional) marks a user *output-type* rule: the value is a
    built-in document type or a global custom type and becomes the archive
    folder base (``<target_type>`` or ``<target_type>-<amount suffix>``). Such
    rules ignore the ``invoice_types`` match gate.

    ``priority`` and ``auto_folder`` are deprecated compatibility fields: the
    loader still parses them (``priority`` with a warning) but matching follows
    the declaration/list order and ``target_type`` takes precedence for folder
    derivation.
    """

    id: str
    name: str
    archive_folder: str
    priority: int = 0
    enabled: bool = True
    keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    invoice_types: tuple[str, ...] = ()
    amount_range: tuple[Decimal | None, Decimal | None] | None = None
    match: str = DEFAULT_MATCH
    description: str = ""
    auto_folder: bool = False
    target_type: str = ""
    builtin_rule: bool = False
    scope: str = CATEGORY_SOURCE_BUILTIN
    layer_index: int = 0
    layer_order: int = 0
    layer_kind: str = "builtin"
    source_file: str = ""
    source_line: int = 0
    field_sources: Mapping[str, SourceRef] = field(default_factory=dict)

    @property
    def is_builtin(self) -> bool:
        return self.scope == CATEGORY_SOURCE_BUILTIN

    @property
    def keyword_source(self) -> SourceRef:
        """Where the effective keyword list came from (falls back to the entry)."""
        fallback = SourceRef(
            self.source_file,
            self.source_line,
            self.layer_index,
            self.layer_kind,
        )
        return self.field_sources.get("keywords", fallback)

    def amount_bounds(self) -> tuple[Decimal | None, Decimal | None] | None:
        return self.amount_range

    def to_dict(self) -> dict[str, Any]:
        amount_range: list[str | None] | None = None
        if self.amount_range is not None:
            amount_range = [
                format_amount_bound(bound) or None for bound in self.amount_range
            ]
        return {
            "id": self.id,
            "name": self.name,
            "archive_folder": self.archive_folder,
            "priority": self.priority,
            "enabled": self.enabled,
            "keywords": list(self.keywords),
            "exclude_keywords": list(self.exclude_keywords),
            "invoice_types": list(self.invoice_types),
            "amount_range": amount_range,
            "match": self.match,
            "description": self.description,
            "auto_folder": self.auto_folder,
            "target_type": self.target_type,
            "builtin_rule": self.builtin_rule,
            "scope": self.scope,
            "layer_index": self.layer_index,
            "layer_order": self.layer_order,
            "layer_kind": self.layer_kind,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "field_sources": {
                key: value.to_dict() for key, value in self.field_sources.items()
            },
        }


@dataclass(frozen=True)
class TermEntry:
    """One seller dictionary entry (seller name or seller TIN -> category)."""

    raw: str
    category_id: str
    normalized_tin: str
    normalized_name: str
    file: str = ""
    line: int = 0
    layer_index: int = 0
    order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.raw,
            "category_id": self.category_id,
            "file": self.file,
            "line": self.line,
            "layer_index": self.layer_index,
            "order": self.order,
        }


@dataclass(frozen=True)
class RuleSet:
    """An immutable, validated snapshot of the effective classification rules.

    ``categories`` is the declaration-ordered tuple of :class:`CategoryRule`
    objects (including disabled ones); ``category_map`` offers id lookup.
    ``ordered_categories`` is the pre-computed match order: enabled categories
    sorted by layer (later layer first), then declaration/list order within the
    layer, then id. ``priority`` values are parsed for compatibility but never
    affect the match order.

    ``custom_types`` are the user's global custom invoice types and
    ``document_types`` is the full selectable type list (built-in then custom);
    ``custom_types_path`` points at the global ``custom_types.yaml``.
    """

    categories: tuple[CategoryRule, ...] = ()
    category_map: Mapping[str, CategoryRule] = field(default_factory=dict)
    ordered_categories: tuple[CategoryRule, ...] = ()
    fallback_id: str = ""
    type_categories: Mapping[str, str] = field(default_factory=dict)
    type_category_sources: Mapping[str, SourceRef] = field(default_factory=dict)
    terms: Mapping[str, str] = field(default_factory=dict)
    term_entries: tuple[TermEntry, ...] = ()
    custom_types: tuple[str, ...] = ()
    document_types: tuple[str, ...] = ()
    custom_types_path: str = ""
    builtin_category_ids: tuple[str, ...] = ()
    warnings: tuple[RuleIssue, ...] = ()
    builtin_path: str = ""
    global_rules_dir: str = ""
    library_dir: str | None = None
    library_rules_dir: str | None = None
    overrides_applied: tuple[str, ...] = ()

    @property
    def fallback(self) -> CategoryRule:
        try:
            return self.category_map[self.fallback_id]
        except KeyError as exc:  # pragma: no cover - loader always validates
            raise KeyError(f"未找到 fallback 分类: {self.fallback_id}") from exc

    @property
    def issues(self) -> tuple[RuleIssue, ...]:
        """Alias for :attr:`warnings` (warnings do not abort loading)."""
        return self.warnings

    def get_category(self, category_id: object) -> CategoryRule | None:
        return self.category_map.get(str(category_id or ""))

    def enabled_categories(self) -> tuple[CategoryRule, ...]:
        return tuple(rule for rule in self.categories if rule.enabled)

    def to_dict(self) -> dict[str, Any]:
        return {
            "categories": [rule.to_dict() for rule in self.categories],
            "fallback": self.fallback_id,
            "type_categories": dict(self.type_categories),
            "terms": dict(self.terms),
            "custom_types": list(self.custom_types),
            "document_types": list(self.document_types),
            "custom_types_path": self.custom_types_path,
            "builtin_category_ids": list(self.builtin_category_ids),
            "warnings": [issue.to_dict() for issue in self.warnings],
            "builtin_path": self.builtin_path,
            "global_rules_dir": self.global_rules_dir,
            "library_dir": self.library_dir,
            "library_rules_dir": self.library_rules_dir,
            "overrides_applied": list(self.overrides_applied),
        }


@dataclass(frozen=True)
class ScopeData:
    """Raw, validated contents of one scope (one rules directory).

    This is the read/save representation used by the rules editor: it contains
    only what that scope's files declare, never the merged effective result.
    """

    scope: str
    rules_dir: str
    categories: tuple[dict[str, Any], ...] = ()
    terms: Mapping[str, str] = field(default_factory=dict)
    fallback: str | None = None
    type_categories: Mapping[str, str] = field(default_factory=dict)
    version: int | None = None
    files: tuple[str, ...] = ()
    warnings: tuple[RuleIssue, ...] = ()

    @property
    def exists(self) -> bool:
        return bool(self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "rules_dir": self.rules_dir,
            "categories": [dict(entry) for entry in self.categories],
            "terms": dict(self.terms),
            "fallback": self.fallback,
            "type_categories": dict(self.type_categories),
            "version": self.version,
            "files": list(self.files),
            "warnings": [issue.to_dict() for issue in self.warnings],
        }


@dataclass(frozen=True)
class ClassificationResult:
    """The outcome of classifying one document's normalized fields."""

    category_id: str
    category_name: str
    archive_folder: str
    category_src: str = CATEGORY_SOURCE_UNKNOWN
    source: str = SOURCE_UNKNOWN
    rule_id: str = ""
    keyword: str = ""
    priority: int = 0
    source_file: str = ""
    source_line: int = 0
    chain: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_unknown(self) -> bool:
        return self.source == SOURCE_UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation (Decimal bounds are already strings)."""
        return {
            "category_id": self.category_id,
            "category_name": self.category_name,
            "archive_folder": self.archive_folder,
            "category_src": self.category_src,
            "source": self.source,
            "rule_id": self.rule_id,
            "keyword": self.keyword,
            "priority": self.priority,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "chain": [dict(item) for item in self.chain],
        }

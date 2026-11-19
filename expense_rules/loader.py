"""Loading, merging and validating the layered classification rules.

Layers (lowest precedence first):

1. the built-in ``builtin/categories.yaml`` (L0 defaults);
2. the global user ``<settings>/rules/categories.yaml``;
3. the library ``<library>/rules/categories.yaml``;
4. every global ``<settings>/rules/rules.d/*.yaml`` rule pack, sorted by name;
5. every library ``<library>/rules/rules.d/*.yaml`` rule pack, sorted by name.
   (``.yml`` files are accepted as the same YAML format.)

Categories merge by ``id`` field-by-field: only fields present in a later YAML
entry replace the effective value (``keywords: []`` is an explicit empty list
and therefore replaces). Every merged field keeps its source file/line so the
UI and ``explain()`` can point at the exact configuration.

Matching follows the declaration/list order (later layer first, then the order
of the entries inside that layer). ``priority`` is still parsed for backward
compatibility, but it is ignored and produces a warning. ``auto_folder: true``
rules derive ``name``/``archive_folder`` from their first keyword and their
``amount_range`` via :func:`expense_rules.model.folder_from_keyword`.

Seller dictionary terms live in ``user_terms.yaml`` files (global then library).

The loader never writes files. ``overrides`` exists for the rules editor: it
replaces one scope's categories/terms/fallback/type_categories in memory using
exactly the same validation and merge path, so an unsaved draft can be
classified without touching the user's rules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import functools
import os
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from .model import (
    CATEGORY_ID_RE,
    CATEGORY_SOURCE_BUILTIN,
    CATEGORY_SOURCE_USER,
    DEFAULT_MATCH,
    KNOWN_CATEGORIES_FILE_FIELDS,
    KNOWN_CATEGORY_FIELDS,
    KNOWN_TERMS_FILE_FIELDS,
    MATCH_FIELDS,
    RULE_SCOPES,
    SCOPE_GLOBAL,
    SCOPE_LIBRARY,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    CategoryRule,
    RuleConfigError,
    RuleIssue,
    RuleSet,
    ScopeData,
    SourceRef,
    TermEntry,
    folder_from_keyword,
    folder_from_type_and_amount,
    is_safe_folder_name,
    normalize_text,
    normalize_tin,
)
from .types import (
    CUSTOM_TYPES_FILE_NAME,
    load_custom_types,
    load_custom_types_file,
)

#: File names inside a rules directory (``<settings>/rules`` or ``<lib>/rules``).
CATEGORIES_FILE_NAME = "categories.yaml"
USER_TERMS_FILE_NAME = "user_terms.yaml"
RULES_DIR_NAME = "rules"
RULE_PACKS_DIR_NAME = "rules.d"
#: Rule packs are YAML documents; ``.yml`` is accepted as the same format
#: (the rules-editor file listing already reports both extensions).
RULE_PACK_SUFFIXES = (".yaml", ".yml")

_INVALID = object()

_OVERRIDE_KEYS = frozenset({"categories", "fallback", "type_categories", "terms"})


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def has_errors(issues: Sequence[RuleIssue]) -> bool:
    """True when at least one issue is an error (warnings never abort loading)."""
    return any(issue.severity == SEVERITY_ERROR for issue in issues)


def _clean_path(value: object) -> str | None:
    if value is None:
        return None
    try:
        text = os.fspath(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(f"路径必须是字符串或 PathLike，收到: {type(value).__name__}") from exc
    cleaned = str(text).strip()
    if not cleaned:
        return None
    return os.path.abspath(cleaned)


def default_builtin_path() -> str:
    """``<repository>/builtin/categories.yaml`` shipped with the application."""
    repository_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repository_root, "builtin", CATEGORIES_FILE_NAME)


def default_global_rules_dir() -> str:
    """User-wide rules directory, next to the application settings file."""
    import user_settings

    return os.path.join(user_settings.get_settings_dir(), RULES_DIR_NAME)


def resolve_rules_dir(
    scope: str, library_dir: object = None, global_rules_dir: object = None
) -> str:
    """Resolve the rules directory for ``scope`` (``"global"``/``"library"``)."""
    scope_text = str(scope or "").strip()
    if scope_text == SCOPE_GLOBAL:
        cleaned = _clean_path(global_rules_dir)
        return cleaned if cleaned else default_global_rules_dir()
    if scope_text == SCOPE_LIBRARY:
        library = _clean_path(library_dir)
        if library is None:
            raise ValueError("library 作用域需要 library_dir")
        return os.path.join(library, RULES_DIR_NAME)
    raise ValueError(f"未知的规则作用域: {scope!r}（可选 global/library）")


@functools.lru_cache(maxsize=1)
def _builtin_document_type_names() -> tuple[str, ...]:
    from document_types import get_document_type_names

    return tuple(get_document_type_names())


@functools.lru_cache(maxsize=1)
def _registered_type_names() -> frozenset[str]:
    return frozenset(_builtin_document_type_names())


def _yaml_error_line(exc: yaml.YAMLError) -> int:
    for attribute in ("problem_mark", "context_mark"):
        mark = getattr(exc, attribute, None)
        if mark is not None:
            try:
                return int(mark.line) + 1
            except (TypeError, ValueError):
                continue
    return 1


def _yaml_error_message(exc: yaml.YAMLError) -> str:
    parts = []
    context = getattr(exc, "context", None)
    problem = getattr(exc, "problem", None)
    if context:
        parts.append(str(context))
    if problem:
        parts.append(str(problem))
    if parts:
        return "；".join(parts)
    text = str(exc).strip().splitlines()
    return text[0] if text else type(exc).__name__


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


# --------------------------------------------------------------------------- #
# YAML parsing with line-number tracking
# --------------------------------------------------------------------------- #


def _iter_duplicate_keys(node: Node):
    """Yield ``(line, message)`` for duplicate keys anywhere in the document."""
    if isinstance(node, MappingNode):
        seen: set[str] = set()
        for key_node, value_node in node.value:
            if isinstance(key_node, ScalarNode):
                key_text = str(key_node.value)
                if key_text in seen:
                    yield (
                        key_node.start_mark.line + 1,
                        f"重复的映射键: {key_text}",
                    )
                else:
                    seen.add(key_text)
            else:
                yield (key_node.start_mark.line + 1, "映射键必须是标量")
            yield from _iter_duplicate_keys(value_node)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            yield from _iter_duplicate_keys(item)


class _YamlDocument:
    """A composed YAML document that keeps node marks for precise diagnostics."""

    def __init__(self, path: str, text: str) -> None:
        self.path = path
        self.text = text
        self.root: Node | None = None
        self.data: dict[str, Any] = {}
        self.issues: list[RuleIssue] = []

    def load(self) -> bool:
        try:
            self.root = yaml.compose(self.text)
        except yaml.YAMLError as exc:
            self.issues.append(
                RuleIssue(
                    self.path,
                    _yaml_error_line(exc),
                    f"YAML 解析失败: {_yaml_error_message(exc)}",
                )
            )
            return False
        if self.root is not None:
            for line, message in _iter_duplicate_keys(self.root):
                self.issues.append(RuleIssue(self.path, line, message))
            if has_errors(self.issues):
                # safe_load silently keeps the last duplicate; stop here.
                return False
        try:
            data = yaml.safe_load(self.text)
        except yaml.YAMLError as exc:
            self.issues.append(
                RuleIssue(
                    self.path,
                    _yaml_error_line(exc),
                    f"YAML 解析失败: {_yaml_error_message(exc)}",
                )
            )
            return False
        if data is None:
            data = {}
        if not isinstance(data, dict):
            self.issues.append(
                RuleIssue(self.path, self._root_line(), "规则文件顶层必须是映射（mapping）")
            )
            return False
        self.data = data
        return True

    # -- node access ------------------------------------------------------- #
    def _root_line(self) -> int:
        if self.root is None:
            return 1
        return self.root.start_mark.line + 1

    def _mapping_pairs(self) -> list[tuple[str | None, Node, Node]]:
        root = self.root
        if not isinstance(root, MappingNode):
            return []
        pairs: list[tuple[str | None, Node, Node]] = []
        for key_node, value_node in root.value:
            key_text = key_node.value if isinstance(key_node, ScalarNode) else None
            pairs.append((key_text if isinstance(key_text, str) else None, key_node, value_node))
        return pairs

    def top_pair(self, key: str) -> tuple[Node, Node] | None:
        for pair_key, key_node, value_node in self._mapping_pairs():
            if pair_key == key:
                return key_node, value_node
        return None

    def top_key_line(self, key: str) -> int:
        pair = self.top_pair(key)
        if pair is None:
            return self._root_line()
        return pair[0].start_mark.line + 1

    def top_value_node(self, key: str) -> Node | None:
        pair = self.top_pair(key)
        return None if pair is None else pair[1]

    def sequence_item_nodes(self, key: str) -> list[Node] | None:
        node = self.top_value_node(key)
        if not isinstance(node, SequenceNode):
            return None
        return list(node.value)

    def sequence_item_lines(self, key: str) -> list[int]:
        nodes = self.sequence_item_nodes(key)
        if nodes is None:
            return []
        return [item.start_mark.line + 1 for item in nodes]

    def sequence_item_field_lines(self, key: str, index: int) -> dict[str, int]:
        nodes = self.sequence_item_nodes(key)
        if nodes is None or index >= len(nodes):
            return {}
        item = nodes[index]
        if not isinstance(item, MappingNode):
            return {}
        lines: dict[str, int] = {}
        for field_key, _field_value in item.value:
            if isinstance(field_key, ScalarNode):
                lines[str(field_key.value)] = field_key.start_mark.line + 1
        return lines

    def mapping_entry_lines(self, key: str) -> dict[str, int]:
        node = self.top_value_node(key)
        if not isinstance(node, MappingNode):
            return {}
        lines: dict[str, int] = {}
        for entry_key, _entry_value in node.value:
            if isinstance(entry_key, ScalarNode):
                lines[str(entry_key.value)] = entry_key.start_mark.line + 1
        return lines


def _validate_version(document: _YamlDocument, issues: list[RuleIssue]) -> int | None:
    if "version" not in document.data:
        return None
    value = document.data.get("version")
    line = document.top_key_line("version")
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        issues.append(
            RuleIssue(
                document.path,
                line,
                f"不支持的规则版本: {value!r}（仅支持 version: 1）",
            )
        )
        return None
    return 1


@dataclass
class _ParsedCategoryEntry:
    raw: Mapping[str, Any]
    line: int
    field_lines: Mapping[str, int]

    def field_line(self, field_name: str) -> int:
        return int(self.field_lines.get(field_name, self.line))


@dataclass
class _ParsedCategoriesFile:
    path: str
    entries: list[_ParsedCategoryEntry]
    fallback: tuple[str, int] | None
    type_categories: list[tuple[str, str, int]]
    version: int | None
    issues: list[RuleIssue]


@dataclass
class _ParsedTermsFile:
    path: str
    terms: list[tuple[str, str, int]]
    version: int | None
    issues: list[RuleIssue]


def _read_yaml_document(path: str) -> _YamlDocument | None:
    try:
        text = _read_text(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuleConfigError(
            [RuleIssue(path, 0, f"无法读取规则文件: {type(exc).__name__}")]
        ) from exc
    document = _YamlDocument(path, text)
    document.load()
    return document


def parse_categories_file(path: str) -> _ParsedCategoriesFile | None:
    """Parse one ``categories.yaml``/rule-pack file; ``None`` when missing."""
    document = _read_yaml_document(path)
    if document is None:
        return None
    issues = list(document.issues)
    if has_errors(issues):
        return _ParsedCategoriesFile(path, [], None, [], None, issues)

    version = _validate_version(document, issues)
    for key in document.data:
        if not isinstance(key, str) or key not in KNOWN_CATEGORIES_FILE_FIELDS:
            issues.append(
                RuleIssue(
                    path,
                    document.top_key_line(str(key)),
                    f"未知的顶层字段: {key}",
                    SEVERITY_WARNING,
                )
            )

    entries: list[_ParsedCategoryEntry] = []
    raw_categories = document.data.get("categories", [])
    if raw_categories is None:
        raw_categories = []
    if isinstance(raw_categories, (str, bytes)) or not isinstance(raw_categories, list):
        issues.append(
            RuleIssue(path, document.top_key_line("categories"), "categories 必须是分类条目列表")
        )
        raw_categories = []
    item_lines = document.sequence_item_lines("categories")
    for index, item in enumerate(raw_categories):
        line = item_lines[index] if index < len(item_lines) else document.top_key_line("categories")
        if not isinstance(item, Mapping):
            issues.append(RuleIssue(path, line, "分类条目必须是映射（mapping）"))
            continue
        entries.append(
            _ParsedCategoryEntry(
                raw=dict(item),
                line=line,
                field_lines=document.sequence_item_field_lines("categories", index),
            )
        )

    fallback: tuple[str, int] | None = None
    if "fallback" in document.data:
        raw_fallback = document.data.get("fallback")
        line = document.top_key_line("fallback")
        if not isinstance(raw_fallback, str) or not raw_fallback.strip():
            issues.append(RuleIssue(path, line, "fallback 必须是非空字符串分类 id"))
        else:
            fallback = (raw_fallback.strip(), line)

    type_categories: list[tuple[str, str, int]] = []
    raw_type_map = document.data.get("type_categories", {})
    if raw_type_map is None:
        raw_type_map = {}
    if not isinstance(raw_type_map, Mapping):
        issues.append(
            RuleIssue(
                path,
                document.top_key_line("type_categories"),
                "type_categories 必须是 票种名称 -> 分类 id 的映射",
            )
        )
    else:
        entry_lines = document.mapping_entry_lines("type_categories")
        default_line = document.top_key_line("type_categories")
        for raw_type, raw_target in raw_type_map.items():
            line = int(entry_lines.get(str(raw_type), default_line))
            if not isinstance(raw_type, str) or not raw_type.strip():
                issues.append(RuleIssue(path, line, "type_categories 的键必须是票种名称"))
                continue
            if not isinstance(raw_target, str) or not raw_target.strip():
                issues.append(
                    RuleIssue(path, line, f"票种 {raw_type} 的分类必须是分类 id 字符串")
                )
                continue
            type_categories.append((raw_type.strip(), raw_target.strip(), line))

    return _ParsedCategoriesFile(path, entries, fallback, type_categories, version, issues)


def parse_terms_file(path: str) -> _ParsedTermsFile | None:
    """Parse one ``user_terms.yaml`` file; ``None`` when missing."""
    document = _read_yaml_document(path)
    if document is None:
        return None
    issues = list(document.issues)
    if has_errors(issues):
        return _ParsedTermsFile(path, [], None, issues)

    version = _validate_version(document, issues)
    for key in document.data:
        if not isinstance(key, str) or key not in KNOWN_TERMS_FILE_FIELDS:
            issues.append(
                RuleIssue(
                    path,
                    document.top_key_line(str(key)),
                    f"未知的顶层字段: {key}",
                    SEVERITY_WARNING,
                )
            )

    terms: list[tuple[str, str, int]] = []
    raw_terms = document.data.get("terms", {})
    if raw_terms is None:
        raw_terms = {}
    if not isinstance(raw_terms, Mapping):
        issues.append(
            RuleIssue(
                path,
                document.top_key_line("terms"),
                "terms 必须是 卖方名称/税号 -> 分类 id 的映射",
            )
        )
    else:
        entry_lines = document.mapping_entry_lines("terms")
        default_line = document.top_key_line("terms")
        for raw_term, raw_target in raw_terms.items():
            line = int(entry_lines.get(str(raw_term), default_line))
            if not isinstance(raw_term, str) or not raw_term.strip():
                issues.append(RuleIssue(path, line, "terms 的键必须是非空字符串"))
                continue
            if not isinstance(raw_target, str) or not raw_target.strip():
                issues.append(RuleIssue(path, line, f"词条 {raw_term} 的分类必须是分类 id 字符串"))
                continue
            terms.append((raw_term.strip(), raw_target.strip(), line))

    return _ParsedTermsFile(path, terms, version, issues)


# --------------------------------------------------------------------------- #
# Layers
# --------------------------------------------------------------------------- #


@dataclass
class _CategoryLayer:
    file: str
    kind: str
    scope: str
    entries: tuple[_ParsedCategoryEntry, ...]
    fallback: tuple[str, int] | None
    type_categories: tuple[tuple[str, str, int], ...]
    issues: tuple[RuleIssue, ...]


@dataclass
class _TermsLayer:
    file: str
    entries: tuple[tuple[str, str, int], ...]
    issues: tuple[RuleIssue, ...]


def _layer_from_parsed(
    parsed: _ParsedCategoriesFile, *, kind: str, scope: str
) -> _CategoryLayer:
    return _CategoryLayer(
        file=parsed.path,
        kind=kind,
        scope=scope,
        entries=tuple(parsed.entries),
        fallback=parsed.fallback,
        type_categories=tuple(parsed.type_categories),
        issues=tuple(parsed.issues),
    )


def _terms_layer_from_parsed(parsed: _ParsedTermsFile) -> _TermsLayer:
    return _TermsLayer(
        file=parsed.path,
        entries=tuple(parsed.terms),
        issues=tuple(parsed.issues),
    )


def list_rule_packs(rules_dir: str) -> list[str]:
    """Sorted ``rules.d/*.yaml`` files of one rules directory (missing dir => [])."""
    packs_dir = os.path.join(rules_dir, RULE_PACKS_DIR_NAME)
    try:
        names = sorted(os.listdir(packs_dir))
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []
    except OSError:
        return []
    paths = []
    for name in names:
        if not name.lower().endswith(RULE_PACK_SUFFIXES):
            continue
        path = os.path.join(packs_dir, name)
        if os.path.isfile(path):
            paths.append(path)
    return paths


# --------------------------------------------------------------------------- #
# In-memory overrides (rules-editor draft preview)
# --------------------------------------------------------------------------- #


def _normalize_overrides(overrides: object, library_dir: str | None) -> dict[str, object]:
    if overrides is None:
        return {}
    if not isinstance(overrides, Mapping):
        raise TypeError("overrides 必须是 作用域 -> ScopeData/映射 的映射")
    normalized: dict[str, object] = {}
    for raw_scope, value in overrides.items():
        scope = str(raw_scope or "").strip()
        if scope not in RULE_SCOPES:
            raise ValueError(f"未知的规则作用域: {raw_scope!r}（可选 global/library）")
        if scope == SCOPE_LIBRARY and library_dir is None:
            raise ValueError("library 作用域覆盖需要 library_dir")
        normalized[scope] = value
    return normalized


def _split_override(
    override: object, label: str, *, warn_unknown: bool
) -> tuple[dict[str, Any], list[RuleIssue]]:
    issues: list[RuleIssue] = []
    if isinstance(override, ScopeData):
        return (
            {
                "categories": [dict(entry) for entry in override.categories],
                "fallback": override.fallback,
                "type_categories": dict(override.type_categories),
                "terms": dict(override.terms),
            },
            issues,
        )
    if not isinstance(override, Mapping):
        raise TypeError(
            f"规则覆盖值必须是 ScopeData 或映射，收到: {type(override).__name__}"
        )
    if warn_unknown:
        for key in override:
            if key not in _OVERRIDE_KEYS:
                issues.append(
                    RuleIssue(label, 1, f"覆盖草稿中的未知字段: {key}", SEVERITY_WARNING)
                )
    return (
        {
            "categories": override.get("categories", []),
            "fallback": override.get("fallback"),
            "type_categories": override.get("type_categories", {}),
            "terms": override.get("terms", {}),
        },
        issues,
    )


def _override_category_layer(
    target_file: str, override: object
) -> _CategoryLayer:
    label = f"{target_file}（内存草稿）"
    parts, issues = _split_override(override, label, warn_unknown=True)
    entries: list[_ParsedCategoryEntry] = []
    raw_categories = parts.get("categories")
    if raw_categories is None:
        raw_categories = []
    if isinstance(raw_categories, (str, bytes)) or not isinstance(
        raw_categories, (list, tuple)
    ):
        issues.append(RuleIssue(label, 1, "categories 必须是分类条目列表"))
        raw_categories = []
    for index, item in enumerate(raw_categories):
        line = index + 1
        if not isinstance(item, Mapping):
            issues.append(RuleIssue(label, line, "分类条目必须是映射（mapping）"))
            continue
        entries.append(_ParsedCategoryEntry(raw=dict(item), line=line, field_lines={}))

    fallback: tuple[str, int] | None = None
    raw_fallback = parts.get("fallback")
    if raw_fallback is not None:
        if not isinstance(raw_fallback, str) or not raw_fallback.strip():
            issues.append(RuleIssue(label, 1, "fallback 必须是非空字符串分类 id"))
        else:
            fallback = (raw_fallback.strip(), 1)

    type_categories: list[tuple[str, str, int]] = []
    raw_type_map = parts.get("type_categories")
    if raw_type_map is None:
        raw_type_map = {}
    if not isinstance(raw_type_map, Mapping):
        issues.append(RuleIssue(label, 1, "type_categories 必须是 票种名称 -> 分类 id 的映射"))
    else:
        for index, (raw_type, raw_target) in enumerate(raw_type_map.items()):
            line = index + 1
            if not isinstance(raw_type, str) or not raw_type.strip():
                issues.append(RuleIssue(label, line, "type_categories 的键必须是票种名称"))
                continue
            if not isinstance(raw_target, str) or not raw_target.strip():
                issues.append(
                    RuleIssue(label, line, f"票种 {raw_type} 的分类必须是分类 id 字符串")
                )
                continue
            type_categories.append((raw_type.strip(), raw_target.strip(), line))

    return _CategoryLayer(
        file=label,
        kind="categories",
        scope=CATEGORY_SOURCE_USER,
        entries=tuple(entries),
        fallback=fallback,
        type_categories=tuple(type_categories),
        issues=tuple(issues),
    )


def _override_terms_layer(target_file: str, override: object) -> _TermsLayer:
    label = f"{target_file}（内存草稿）"
    parts, issues = _split_override(override, label, warn_unknown=False)
    entries: list[tuple[str, str, int]] = []
    raw_terms = parts.get("terms")
    if raw_terms is None:
        raw_terms = {}
    if not isinstance(raw_terms, Mapping):
        issues.append(
            RuleIssue(label, 1, "terms 必须是 卖方名称/税号 -> 分类 id 的映射")
        )
    else:
        for index, (raw_term, raw_target) in enumerate(raw_terms.items()):
            line = index + 1
            if not isinstance(raw_term, str) or not raw_term.strip():
                issues.append(RuleIssue(label, line, "terms 的键必须是非空字符串"))
                continue
            if not isinstance(raw_target, str) or not raw_target.strip():
                issues.append(
                    RuleIssue(label, line, f"词条 {raw_term} 的分类必须是分类 id 字符串")
                )
                continue
            entries.append((raw_term.strip(), raw_target.strip(), line))
    return _TermsLayer(file=label, entries=tuple(entries), issues=tuple(issues))


# --------------------------------------------------------------------------- #
# Field coercion
# --------------------------------------------------------------------------- #


def _coerce_non_empty_text(
    value: object, path: str, line: int, issues: list[RuleIssue], field_name: str
) -> str | object:
    if not isinstance(value, str) or not value.strip():
        issues.append(RuleIssue(path, line, f"{field_name} 必须是非空字符串"))
        return _INVALID
    return value.strip()


def _coerce_string_list(
    value: object,
    path: str,
    line: int,
    issues: list[RuleIssue],
    field_name: str,
) -> tuple[str, ...] | object:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        issues.append(RuleIssue(path, line, f"{field_name} 必须是字符串列表"))
        return _INVALID
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            issues.append(RuleIssue(path, line, f"{field_name} 的每一项必须是非空字符串"))
            return _INVALID
        result.append(item.strip())
    return tuple(result)


def _coerce_invoice_types(
    value: object, path: str, line: int, issues: list[RuleIssue]
) -> tuple[str, ...] | object:
    coerced = _coerce_string_list(value, path, line, issues, "invoice_types")
    if coerced is _INVALID:
        return _INVALID
    registered = _registered_type_names()
    for item in coerced:  # type: ignore[union-attr]
        if item not in registered:
            issues.append(
                RuleIssue(path, line, f"invoice_types 中的票种未注册: {item}")
            )
            return _INVALID
    return coerced


def _coerce_amount_bound(
    value: object, path: str, line: int, issues: list[RuleIssue]
) -> Decimal | None | object:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        issues.append(
            RuleIssue(path, line, "amount_range 的每一项必须是数字或 null")
        )
        return _INVALID
    try:
        converted = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        issues.append(RuleIssue(path, line, f"amount_range 的数值无效: {value!r}"))
        return _INVALID
    if not converted.is_finite():
        issues.append(RuleIssue(path, line, f"amount_range 的数值必须是有限数: {value!r}"))
        return _INVALID
    return converted


def _coerce_amount_range(
    value: object, path: str, line: int, issues: list[RuleIssue]
) -> tuple[Decimal | None, Decimal | None] | None | object:
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or isinstance(value, Mapping) or not isinstance(
        value, (list, tuple)
    ):
        issues.append(
            RuleIssue(path, line, "amount_range 必须是 [下限, 上限] 两项列表（可为 null）")
        )
        return _INVALID
    if len(value) == 0:
        return None
    if len(value) != 2:
        issues.append(
            RuleIssue(path, line, "amount_range 必须恰好包含 [下限, 上限] 两项")
        )
        return _INVALID
    lower = _coerce_amount_bound(value[0], path, line, issues)
    if lower is _INVALID:
        return _INVALID
    upper = _coerce_amount_bound(value[1], path, line, issues)
    if upper is _INVALID:
        return _INVALID
    if lower is not None and upper is not None and lower > upper:
        issues.append(
            RuleIssue(path, line, f"amount_range 下限 {lower} 大于上限 {upper}")
        )
        return _INVALID
    return (lower, upper)


def _coerce_field(
    field_name: str,
    value: object,
    *,
    path: str,
    line: int,
    issues: list[RuleIssue],
    known_types: frozenset[str] | None = None,
) -> Any:
    if field_name == "name":
        return _coerce_non_empty_text(value, path, line, issues, "name")
    if field_name == "archive_folder":
        text = _coerce_non_empty_text(value, path, line, issues, "archive_folder")
        if text is _INVALID:
            return _INVALID
        if not is_safe_folder_name(text):
            issues.append(
                RuleIssue(path, line, f"archive_folder 不是安全的文件夹名: {text!r}")
            )
            return _INVALID
        return text
    if field_name == "enabled":
        if not isinstance(value, bool):
            issues.append(RuleIssue(path, line, "enabled 必须是布尔值 true/false"))
            return _INVALID
        return value
    if field_name == "auto_folder":
        if not isinstance(value, bool):
            issues.append(RuleIssue(path, line, "auto_folder 必须是布尔值 true/false"))
            return _INVALID
        return value
    if field_name == "target_type":
        text = _coerce_non_empty_text(value, path, line, issues, "target_type")
        if text is _INVALID:
            return _INVALID
        known = known_types if known_types is not None else _registered_type_names()
        if text not in known:
            issues.append(
                RuleIssue(path, line, f"target_type 不是已注册票种: {text}")
            )
            return _INVALID
        return text
    if field_name in {"keywords", "exclude_keywords"}:
        return _coerce_string_list(value, path, line, issues, field_name)
    if field_name == "invoice_types":
        return _coerce_invoice_types(value, path, line, issues)
    if field_name == "amount_range":
        return _coerce_amount_range(value, path, line, issues)
    if field_name == "match":
        if not isinstance(value, str) or value.strip() not in MATCH_FIELDS:
            issues.append(
                RuleIssue(
                    path,
                    line,
                    f"match 必须是 {', '.join(MATCH_FIELDS)} 之一",
                )
            )
            return _INVALID
        return value.strip()
    if field_name == "description":
        if not isinstance(value, str):
            issues.append(RuleIssue(path, line, "description 必须是字符串"))
            return _INVALID
        return value.strip()
    return _INVALID


# --------------------------------------------------------------------------- #
# Merge + validation
# --------------------------------------------------------------------------- #


def _merge_categories(
    category_layers: Sequence[_CategoryLayer],
    issues: list[RuleIssue],
    *,
    known_types: frozenset[str] | None = None,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, SourceRef]],
    dict[str, dict[str, Any]],
    dict[str, int],
]:
    merged: dict[str, dict[str, Any]] = {}
    field_sources: dict[str, dict[str, SourceRef]] = {}
    meta: dict[str, dict[str, Any]] = {}
    declaration_order: dict[str, int] = {}
    next_order = 0

    for layer_index, layer in enumerate(category_layers, start=1):
        issues.extend(layer.issues)
        seen_ids: set[str] = set()
        for entry_order, entry in enumerate(layer.entries):
            raw = entry.raw
            raw_id = raw.get("id")
            id_line = entry.field_line("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                issues.append(RuleIssue(layer.file, id_line, "分类条目缺少字符串 id"))
                continue
            category_id = raw_id.strip()
            if not CATEGORY_ID_RE.match(category_id):
                issues.append(
                    RuleIssue(
                        layer.file,
                        id_line,
                        f"分类 id 不合法: {category_id!r}（需匹配 ^[a-z][a-z0-9_]*$）",
                    )
                )
                continue
            if category_id in seen_ids:
                issues.append(
                    RuleIssue(layer.file, id_line, f"同一文件内分类 id 重复: {category_id}")
                )
                continue
            seen_ids.add(category_id)

            for raw_field in raw:
                if not isinstance(raw_field, str) or raw_field not in KNOWN_CATEGORY_FIELDS:
                    issues.append(
                        RuleIssue(
                            layer.file,
                            entry.field_line(str(raw_field)),
                            f"未知的分类字段: {raw_field}",
                            SEVERITY_WARNING,
                        )
                    )

            coerced: dict[str, Any] = {}
            if "priority" in raw:
                issues.append(
                    RuleIssue(
                        layer.file,
                        entry.field_line("priority"),
                        "priority 已不再使用，规则按列表顺序匹配",
                        SEVERITY_WARNING,
                    )
                )
                priority_raw = raw.get("priority")
                coerced["priority"] = (
                    priority_raw
                    if isinstance(priority_raw, int)
                    and not isinstance(priority_raw, bool)
                    else 0
                )
            for field_name in sorted(KNOWN_CATEGORY_FIELDS - {"id", "priority"}):
                if field_name not in raw:
                    continue
                value = _coerce_field(
                    field_name,
                    raw[field_name],
                    path=layer.file,
                    line=entry.field_line(field_name),
                    issues=issues,
                    known_types=known_types,
                )
                if value is not _INVALID:
                    coerced[field_name] = value

            if category_id not in merged:
                merged[category_id] = {}
                field_sources[category_id] = {}
                declaration_order[category_id] = next_order
                next_order += 1
            merged[category_id].update(coerced)
            for field_name in coerced:
                field_sources[category_id][field_name] = SourceRef(
                    file=layer.file,
                    line=entry.field_line(field_name),
                    layer_index=layer_index,
                    kind=layer.kind,
                )
            meta[category_id] = {
                "scope": layer.scope,
                "layer_index": layer_index,
                "layer_order": entry_order,
                "file": layer.file,
                "line": entry.line,
                "kind": layer.kind,
            }

    return merged, field_sources, meta, declaration_order


def _finalize_categories(
    merged: Mapping[str, dict[str, Any]],
    field_sources: Mapping[str, dict[str, SourceRef]],
    meta: Mapping[str, dict[str, Any]],
    declaration_order: Mapping[str, int],
    issues: list[RuleIssue],
    *,
    builtin_ids: frozenset[str] = frozenset(),
) -> tuple[CategoryRule, ...]:
    rules: list[CategoryRule] = []
    for category_id in sorted(merged, key=lambda item: declaration_order[item]):
        fields = merged[category_id]
        info = meta[category_id]
        keywords = tuple(fields.get("keywords", ()))
        auto_folder = bool(fields.get("auto_folder", False))
        target_type = str(fields.get("target_type") or "")
        builtin_rule = category_id in builtin_ids
        name = fields.get("name")
        folder = fields.get("archive_folder")
        if target_type:
            # Output-type rule: folder/name are derived from the target type and
            # the optional amount range. Built-in categories may have no keyword
            # (type-only fallback) and keep their invoice_types gate in the engine.
            keywords_source = field_sources[category_id].get(
                "keywords", SourceRef(info["file"], info["line"])
            )
            if not keywords and not builtin_rule:
                issues.append(
                    RuleIssue(
                        keywords_source.file,
                        keywords_source.line,
                        "输出票种规则必须填写关键词",
                    )
                )
                name = ""
                folder = ""
            else:
                try:
                    folder = folder_from_type_and_amount(
                        target_type, fields.get("amount_range")
                    )
                except ValueError as exc:
                    issues.append(
                        RuleIssue(keywords_source.file, keywords_source.line, str(exc))
                    )
                    folder = ""
                name = folder
                if folder and not is_safe_folder_name(folder):
                    issues.append(
                        RuleIssue(
                            keywords_source.file,
                            keywords_source.line,
                            f"输出票种文件夹名不安全: {folder!r}",
                        )
                    )
                if folder:
                    derived = SourceRef(
                        keywords_source.file,
                        keywords_source.line,
                        keywords_source.layer_index,
                        "target_type",
                    )
                    field_sources[category_id]["name"] = derived
                    field_sources[category_id]["archive_folder"] = derived
        elif auto_folder:
            keywords_source = field_sources[category_id].get(
                "keywords", SourceRef(info["file"], info["line"])
            )
            if not keywords:
                issues.append(
                    RuleIssue(
                        keywords_source.file,
                        keywords_source.line,
                        "自动文件夹规则必须填写关键词",
                    )
                )
                name = ""
                folder = ""
            else:
                try:
                    folder = folder_from_keyword(
                        keywords[0], fields.get("amount_range")
                    )
                except ValueError as exc:
                    issues.append(
                        RuleIssue(keywords_source.file, keywords_source.line, str(exc))
                    )
                    folder = ""
                name = folder
                if folder and not is_safe_folder_name(folder):
                    issues.append(
                        RuleIssue(
                            keywords_source.file,
                            keywords_source.line,
                            f"自动文件夹名称不安全: {folder!r}",
                        )
                    )
                if folder:
                    derived = SourceRef(
                        keywords_source.file,
                        keywords_source.line,
                        keywords_source.layer_index,
                        "auto_folder",
                    )
                    field_sources[category_id]["name"] = derived
                    field_sources[category_id]["archive_folder"] = derived
        else:
            if name is None:
                issues.append(
                    RuleIssue(
                        info["file"],
                        info["line"],
                        f"分类 {category_id} 缺少 name（无法从更早层级继承）",
                    )
                )
            if folder is None:
                folder = name
                if folder is not None and not is_safe_folder_name(folder):
                    name_source = field_sources[category_id].get(
                        "name", SourceRef(info["file"], info["line"])
                    )
                    issues.append(
                        RuleIssue(
                            name_source.file,
                            name_source.line,
                            f"分类 {category_id} 的默认归档文件夹名不安全: {folder!r}",
                        )
                    )
                    folder = ""
        amount_range = fields.get("amount_range")
        rule = CategoryRule(
            id=category_id,
            name=str(name or ""),
            archive_folder=str(folder or ""),
            priority=int(fields.get("priority", 0) or 0),
            enabled=bool(fields.get("enabled", True)),
            keywords=keywords,
            exclude_keywords=tuple(fields.get("exclude_keywords", ())),
            invoice_types=tuple(fields.get("invoice_types", ())),
            amount_range=amount_range,
            match=str(fields.get("match", DEFAULT_MATCH)),
            description=str(fields.get("description") or ""),
            auto_folder=auto_folder,
            target_type=target_type,
            builtin_rule=builtin_rule,
            scope=str(info["scope"]),
            layer_index=int(info["layer_index"]),
            layer_order=int(info["layer_order"]),
            layer_kind=str(info["kind"]),
            source_file=str(info["file"]),
            source_line=int(info["line"]),
            field_sources=dict(field_sources[category_id]),
        )
        rules.append(rule)
    return tuple(rules)


def _assemble_rule_set(
    *,
    category_layers: Sequence[_CategoryLayer],
    terms_layers: Sequence[_TermsLayer],
    builtin_path: str,
    global_rules_dir: str,
    library_dir: str | None,
    library_rules_dir: str | None,
    overrides_applied: tuple[str, ...],
    custom_types: tuple[str, ...] = (),
    document_types: tuple[str, ...] = (),
    custom_types_path: str = "",
    builtin_category_ids: tuple[str, ...] = (),
    custom_types_issues: tuple[RuleIssue, ...] = (),
) -> RuleSet:
    issues: list[RuleIssue] = list(custom_types_issues)
    known_types = frozenset(document_types)
    merged, field_sources, meta, declaration_order = _merge_categories(
        category_layers, issues, known_types=known_types
    )
    category_rules = _finalize_categories(
        merged,
        field_sources,
        meta,
        declaration_order,
        issues,
        builtin_ids=frozenset(builtin_category_ids),
    )
    category_map = {rule.id: rule for rule in category_rules}

    # fallback: later layer wins per key
    fallback_id = ""
    fallback_ref: SourceRef | None = None
    for layer_index, layer in enumerate(category_layers, start=1):
        if layer.fallback is None:
            continue
        fallback_text, fallback_line = layer.fallback
        fallback_id = fallback_text.strip()
        fallback_ref = SourceRef(layer.file, fallback_line, layer_index, layer.kind)
    if not fallback_id:
        issues.append(RuleIssue(builtin_path, 1, "缺少 fallback 分类 id"))
    elif fallback_id not in category_map:
        ref = fallback_ref or SourceRef(builtin_path, 1)
        issues.append(RuleIssue(ref.file, ref.line, f"fallback 分类不存在: {fallback_id}"))
    elif not category_map[fallback_id].enabled:
        ref = fallback_ref or SourceRef(builtin_path, 1)
        issues.append(RuleIssue(ref.file, ref.line, f"fallback 分类已被禁用: {fallback_id}"))

    # type_categories: later layer wins per key
    type_categories: dict[str, str] = {}
    type_category_sources: dict[str, SourceRef] = {}
    for layer_index, layer in enumerate(category_layers, start=1):
        for raw_type, target, line in layer.type_categories:
            type_categories[raw_type] = target
            type_category_sources[raw_type] = SourceRef(
                layer.file, line, layer_index, layer.kind
            )
    registered = _registered_type_names()
    for raw_type, target in type_categories.items():
        source = type_category_sources[raw_type]
        if raw_type not in registered:
            issues.append(
                RuleIssue(
                    source.file,
                    source.line,
                    f"type_categories 中的票种未注册: {raw_type}",
                    SEVERITY_WARNING,
                )
            )
        if target not in category_map:
            issues.append(
                RuleIssue(
                    source.file,
                    source.line,
                    f"type_categories 指向不存在的分类: {raw_type} -> {target}",
                )
            )
        elif not category_map[target].enabled:
            issues.append(
                RuleIssue(
                    source.file,
                    source.line,
                    f"type_categories 指向已禁用的分类: {raw_type} -> {target}",
                    SEVERITY_WARNING,
                )
            )

    # seller dictionary terms: later layer wins per term
    terms: dict[str, str] = {}
    term_refs: dict[str, SourceRef] = {}
    term_orders: dict[str, int] = {}
    for layer_index, layer in enumerate(terms_layers, start=1):
        issues.extend(layer.issues)
        for entry_order, (raw_term, target, line) in enumerate(layer.entries):
            terms[raw_term] = target
            term_refs[raw_term] = SourceRef(layer.file, line, layer_index, "terms")
            term_orders[raw_term] = entry_order
    for raw_term, target in terms.items():
        ref = term_refs[raw_term]
        if target not in category_map:
            issues.append(
                RuleIssue(ref.file, ref.line, f"词条 {raw_term} 指向不存在的分类: {target}")
            )
        elif not category_map[target].enabled:
            issues.append(
                RuleIssue(ref.file, ref.line, f"词条 {raw_term} 指向已禁用的分类: {target}")
            )

    if has_errors(issues):
        raise RuleConfigError(issues)

    term_entries = tuple(
        TermEntry(
            raw=raw_term,
            category_id=target,
            normalized_tin=normalize_tin(raw_term),
            normalized_name=normalize_text(raw_term),
            file=term_refs[raw_term].file,
            line=term_refs[raw_term].line,
            layer_index=term_refs[raw_term].layer_index,
            order=term_orders[raw_term],
        )
        for raw_term, target in sorted(
            terms.items(),
            key=lambda item: (
                term_refs[item[0]].layer_index,
                term_orders[item[0]],
            ),
        )
    )

    # Matching follows the list order: later layer first, then declaration/list
    # order within the layer. ``priority`` is parsed for compatibility only.
    ordered_categories = tuple(
        sorted(
            (rule for rule in category_rules if rule.enabled),
            key=lambda rule: (
                -rule.layer_index,
                rule.layer_order,
                rule.id,
            ),
        )
    )
    warnings = tuple(issue for issue in issues if issue.severity == SEVERITY_WARNING)

    return RuleSet(
        categories=category_rules,
        category_map=category_map,
        ordered_categories=ordered_categories,
        fallback_id=fallback_id,
        type_categories=type_categories,
        type_category_sources=type_category_sources,
        terms=terms,
        term_entries=term_entries,
        custom_types=custom_types,
        document_types=document_types,
        custom_types_path=custom_types_path,
        builtin_category_ids=builtin_category_ids,
        warnings=warnings,
        builtin_path=builtin_path,
        global_rules_dir=global_rules_dir if global_rules_dir else default_global_rules_dir(),
        library_dir=library_dir,
        library_rules_dir=library_rules_dir,
        overrides_applied=overrides_applied,
    )


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #


def load_rule_set(
    library_dir: object = None,
    *,
    global_rules_dir: object = None,
    builtin_path: object = None,
    overrides: Mapping[str, ScopeData | Mapping[str, Any]] | None = None,
    custom_types_path: object = None,
) -> RuleSet:
    """Load, merge and validate the effective rule set.

    ``library_dir`` enables the per-library layers (``<library>/rules``).
    ``global_rules_dir``/``builtin_path`` override the default locations (tests
    and development use this). ``overrides`` replaces one scope's own
    categories/terms/fallback/type_categories in memory -- no file is written.
    ``custom_types_path`` overrides the global ``custom_types.yaml`` location
    (mostly for tests); by default it lives in ``global_rules_dir``.
    """
    library = _clean_path(library_dir)
    global_dir = _clean_path(global_rules_dir) or default_global_rules_dir()
    builtin = _clean_path(builtin_path) or default_builtin_path()
    library_rules = os.path.join(library, RULES_DIR_NAME) if library else None
    override_map = _normalize_overrides(overrides, library)
    overrides_applied = tuple(scope for scope in RULE_SCOPES if scope in override_map)

    if custom_types_path is not None:
        custom_types = load_custom_types_file(
            _clean_path(custom_types_path)
            or os.path.join(global_dir, CUSTOM_TYPES_FILE_NAME)
        )
    else:
        custom_types = load_custom_types(global_dir)
    builtin_types = _builtin_document_type_names()
    document_types = builtin_types + tuple(
        name for name in custom_types.names if name not in builtin_types
    )

    builtin_parsed = parse_categories_file(builtin)
    if builtin_parsed is None:
        raise RuleConfigError(
            [RuleIssue(builtin, 0, "找不到内置分类规则文件")]
        )
    category_layers: list[_CategoryLayer] = [
        _layer_from_parsed(
            builtin_parsed, kind="builtin", scope=CATEGORY_SOURCE_BUILTIN
        )
    ]

    scope_dirs: list[tuple[str, str | None]] = [
        (SCOPE_GLOBAL, global_dir),
        (SCOPE_LIBRARY, library_rules),
    ]

    for scope, rules_dir in scope_dirs:
        if rules_dir is None:
            continue
        if scope in override_map:
            category_layers.append(
                _override_category_layer(
                    os.path.join(rules_dir, CATEGORIES_FILE_NAME),
                    override_map[scope],
                )
            )
            continue
        parsed = parse_categories_file(os.path.join(rules_dir, CATEGORIES_FILE_NAME))
        if parsed is not None:
            category_layers.append(
                _layer_from_parsed(parsed, kind="categories", scope=CATEGORY_SOURCE_USER)
            )

    for scope, rules_dir in scope_dirs:
        if rules_dir is None:
            continue
        for pack_path in list_rule_packs(rules_dir):
            parsed = parse_categories_file(pack_path)
            if parsed is not None:
                category_layers.append(
                    _layer_from_parsed(parsed, kind="pack", scope=CATEGORY_SOURCE_USER)
                )

    terms_layers: list[_TermsLayer] = []
    for scope, rules_dir in scope_dirs:
        if rules_dir is None:
            continue
        if scope in override_map:
            terms_layers.append(
                _override_terms_layer(
                    os.path.join(rules_dir, USER_TERMS_FILE_NAME),
                    override_map[scope],
                )
            )
            continue
        parsed_terms = parse_terms_file(os.path.join(rules_dir, USER_TERMS_FILE_NAME))
        if parsed_terms is not None:
            terms_layers.append(_terms_layer_from_parsed(parsed_terms))

    return _assemble_rule_set(
        category_layers=category_layers,
        terms_layers=terms_layers,
        builtin_path=builtin,
        global_rules_dir=global_dir,
        library_dir=library,
        library_rules_dir=library_rules,
        overrides_applied=overrides_applied,
        custom_types=tuple(custom_types.names),
        document_types=document_types,
        custom_types_path=custom_types.path,
        builtin_category_ids=tuple(
            str(entry.raw.get("id") or "")
            for entry in builtin_parsed.entries
            if str(entry.raw.get("id") or "")
        ),
        custom_types_issues=tuple(custom_types.issues),
    )


def build_rule_set(
    library_dir: object = None,
    *,
    global_rules_dir: object = None,
    builtin_path: object = None,
    overrides: Mapping[str, ScopeData | Mapping[str, Any]] | None = None,
    custom_types_path: object = None,
) -> RuleSet:
    """Draft-preview variant of :func:`load_rule_set` (in-memory overrides)."""
    return load_rule_set(
        library_dir,
        global_rules_dir=global_rules_dir,
        builtin_path=builtin_path,
        overrides=overrides,
        custom_types_path=custom_types_path,
    )

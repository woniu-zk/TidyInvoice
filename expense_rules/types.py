"""Global custom invoice types (``<global_rules_dir>/custom_types.yaml``).

Custom types are cost-accounting labels the user defines once and can then pick
as the ``target_type`` of classification rules in any scope (global or any
invoice library). They augment the built-in
:data:`document_types.DOCUMENT_TYPES` vocabulary; built-in types cannot be
redefined or removed.

File shape::

    version: 1
    types:
      - 酒店
      - 会议

The parser keeps ``file:line`` information on every issue and the writer uses
the same atomic-write / ``.backup`` pattern as the rule stores.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import functools
import os
import shutil
import tempfile
import unicodedata
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from brand_generated import RULE_FILE_HEADER

from .model import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    RuleConfigError,
    RuleIssue,
    is_safe_folder_name,
)

CUSTOM_TYPES_FILE_NAME = "custom_types.yaml"
MAX_CUSTOM_TYPE_NAME_LENGTH = 32
BACKUP_DIR_NAME = ".backup"
MAX_BACKUP_DIRS = 20

_KNOWN_FILE_FIELDS = frozenset({"version", "types"})

_HEADER = (
    RULE_FILE_HEADER + " 全局自定义票种\n"
    "#\n"
    "# 这里登记的票种会在全局规则与各发票库规则中作为 target_type 可选；\n"
    "# 内置票种无需登记，也不能通过本文件删除。\n"
    "# 名称须 <=32 字符，且能安全用作归档文件夹名（不能是保留目录名）。\n"
    "#\n"
    "# version: 1\n"
    "# types:\n"
    "#   - 酒店\n"
    "#   - 会议\n"
)


@dataclass(frozen=True)
class CustomTypeEntry:
    """One ``types:`` list entry with its source location."""

    name: str
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "file": self.file, "line": self.line}


@dataclass(frozen=True)
class CustomTypes:
    """Parsed global custom invoice types plus any issues found while loading."""

    names: tuple[str, ...] = ()
    path: str = ""
    issues: tuple[RuleIssue, ...] = ()
    entries: tuple[CustomTypeEntry, ...] = ()

    @property
    def exists(self) -> bool:
        return bool(self.path) and os.path.isfile(self.path)

    @property
    def errors(self) -> tuple[RuleIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == SEVERITY_ERROR)

    def to_dict(self) -> dict[str, Any]:
        return {
            "names": list(self.names),
            "path": self.path,
            "issues": [issue.to_dict() for issue in self.issues],
            "entries": [entry.to_dict() for entry in self.entries],
        }


# --------------------------------------------------------------------------- #
# Name validation
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=1)
def _builtin_type_names() -> tuple[str, ...]:
    from document_types import get_document_type_names

    return tuple(get_document_type_names())


def _normalize_type_name(value: object) -> str:
    text = "" if value is None else str(value)
    return unicodedata.normalize("NFKC", text).casefold().strip()


def custom_type_name_error(name: object, existing_names: Iterable[str]) -> str:
    """Return ``""`` when ``name`` is a valid custom type, else an error message.

    A valid name is a string, non-empty, <= 32 characters, safe as an archive
    folder name and unique (NFKC/casefold normalized) against the built-in
    document types and ``existing_names``.
    """
    if not isinstance(name, str):
        return "票种名称必须是字符串"
    text = name.strip()
    if not text:
        return "票种名称不能为空"
    if len(text) > MAX_CUSTOM_TYPE_NAME_LENGTH:
        return f"票种名称不能超过 {MAX_CUSTOM_TYPE_NAME_LENGTH} 个字符"
    if not is_safe_folder_name(text):
        return f"票种名称不是安全的文件夹名: {text!r}"
    normalized = _normalize_type_name(text)
    for builtin in _builtin_type_names():
        if _normalize_type_name(builtin) == normalized:
            return f"票种名称与内置票种重名: {text}"
    for existing in existing_names:
        if _normalize_type_name(existing) == normalized:
            return f"票种名称已存在: {text}"
    return ""


def builtin_type_names() -> tuple[str, ...]:
    """The built-in document type vocabulary (shared convenience helper)."""
    return _builtin_type_names()


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #


def _clean_dir(value: object) -> str | None:
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


def _default_global_rules_dir() -> str:
    import user_settings

    return os.path.join(user_settings.get_settings_dir(), "rules")


def _resolve_rules_dir(global_rules_dir: object) -> str:
    cleaned = _clean_dir(global_rules_dir)
    return cleaned if cleaned else _default_global_rules_dir()


def custom_types_file_path(global_rules_dir: object = None) -> str:
    """Absolute path of the global ``custom_types.yaml`` for a rules dir."""
    return os.path.join(_resolve_rules_dir(global_rules_dir), CUSTOM_TYPES_FILE_NAME)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


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


def _iter_duplicate_keys(node: Node):
    if isinstance(node, MappingNode):
        seen: set[str] = set()
        for key_node, value_node in node.value:
            if isinstance(key_node, ScalarNode):
                key_text = str(key_node.value)
                if key_text in seen:
                    yield key_node.start_mark.line + 1, f"重复的映射键: {key_text}"
                else:
                    seen.add(key_text)
            else:
                yield key_node.start_mark.line + 1, "映射键必须是标量"
            yield from _iter_duplicate_keys(value_node)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            yield from _iter_duplicate_keys(item)


def _top_key_line(root: Node | None, key: str) -> int:
    if isinstance(root, MappingNode):
        for key_node, _value_node in root.value:
            if isinstance(key_node, ScalarNode) and str(key_node.value) == key:
                return key_node.start_mark.line + 1
    return 1


def _type_item_lines(root: Node | None) -> list[int]:
    if not isinstance(root, MappingNode):
        return []
    for key_node, value_node in root.value:
        if not isinstance(key_node, ScalarNode) or str(key_node.value) != "types":
            continue
        if not isinstance(value_node, SequenceNode):
            return []
        return [item.start_mark.line + 1 for item in value_node.value]
    return []


def _has_errors(issues: Iterable[RuleIssue]) -> bool:
    return any(issue.severity == SEVERITY_ERROR for issue in issues)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


def load_custom_types_file(path: object) -> CustomTypes:
    """Load one ``custom_types.yaml`` path (missing file => empty, no issues)."""
    resolved = _clean_dir(path) or ""
    if not resolved:
        return CustomTypes()
    try:
        text = _read_text(resolved)
    except FileNotFoundError:
        return CustomTypes(path=resolved)
    except OSError as exc:
        return CustomTypes(
            path=resolved,
            issues=(
                RuleIssue(resolved, 0, f"无法读取票种文件: {type(exc).__name__}"),
            ),
        )

    issues: list[RuleIssue] = []
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        return CustomTypes(
            path=resolved,
            issues=(
                RuleIssue(
                    resolved,
                    _yaml_error_line(exc),
                    f"YAML 解析失败: {_yaml_error_message(exc)}",
                ),
            ),
        )
    if root is not None:
        for line, message in _iter_duplicate_keys(root):
            issues.append(RuleIssue(resolved, line, message))
        if _has_errors(issues):
            return CustomTypes(path=resolved, issues=tuple(issues))

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return CustomTypes(
            path=resolved,
            issues=(
                RuleIssue(
                    resolved,
                    _yaml_error_line(exc),
                    f"YAML 解析失败: {_yaml_error_message(exc)}",
                ),
            ),
        )
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return CustomTypes(
            path=resolved,
            issues=(RuleIssue(resolved, 1, "票种文件顶层必须是映射（mapping）"),),
        )

    if "version" in data:
        version = data.get("version")
        line = _top_key_line(root, "version")
        if isinstance(version, bool) or not isinstance(version, int) or version != 1:
            issues.append(
                RuleIssue(
                    resolved,
                    line,
                    f"不支持的票种文件版本: {version!r}（仅支持 version: 1）",
                )
            )
    for key in data:
        if not isinstance(key, str) or key not in _KNOWN_FILE_FIELDS:
            issues.append(
                RuleIssue(
                    resolved,
                    _top_key_line(root, str(key)),
                    f"未知的顶层字段: {key}",
                    SEVERITY_WARNING,
                )
            )

    raw_types = data.get("types", [])
    if raw_types is None:
        raw_types = []
    if isinstance(raw_types, (str, bytes)) or not isinstance(raw_types, list):
        issues.append(
            RuleIssue(
                resolved,
                _top_key_line(root, "types"),
                "types 必须是票种名称列表",
            )
        )
        raw_types = []

    item_lines = _type_item_lines(root)
    default_line = _top_key_line(root, "types")
    names: list[str] = []
    entries: list[CustomTypeEntry] = []
    for index, item in enumerate(raw_types):
        line = item_lines[index] if index < len(item_lines) else default_line
        if not isinstance(item, str) or not item.strip():
            issues.append(RuleIssue(resolved, line, "票种名称必须是非空字符串"))
            continue
        name = item.strip()
        error = custom_type_name_error(name, names)
        if error:
            if any(
                _normalize_type_name(name) == _normalize_type_name(existing)
                for existing in names
            ):
                issues.append(RuleIssue(resolved, line, f"票种名称重复: {name}"))
            else:
                issues.append(RuleIssue(resolved, line, error))
            continue
        names.append(name)
        entries.append(CustomTypeEntry(name=name, file=resolved, line=line))

    return CustomTypes(
        names=tuple(names),
        path=resolved,
        issues=tuple(issues),
        entries=tuple(entries),
    )


def load_custom_types(global_rules_dir: object = None) -> CustomTypes:
    """Load the global custom types for ``global_rules_dir`` (default settings)."""
    return load_custom_types_file(custom_types_file_path(global_rules_dir))


def raise_for_custom_types_issues(custom_types: CustomTypes) -> None:
    """Raise :class:`RuleConfigError` when the loaded type file has errors."""
    if _has_errors(custom_types.issues):
        raise RuleConfigError(custom_types.issues)


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def _dump_yaml(payload: dict[str, Any]) -> str:
    body = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    if not body.endswith("\n"):
        body += "\n"
    return _HEADER + body


def _atomic_write_text(path: str, text: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    file_descriptor, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _prune_backups(backup_root: str) -> None:
    try:
        entries = sorted(
            name
            for name in os.listdir(backup_root)
            if os.path.isdir(os.path.join(backup_root, name))
        )
    except OSError:
        return
    while len(entries) > MAX_BACKUP_DIRS:
        oldest = entries.pop(0)
        try:
            shutil.rmtree(os.path.join(backup_root, oldest))
        except OSError:
            continue


def _create_backup(rules_dir: str) -> str:
    source = os.path.join(rules_dir, CUSTOM_TYPES_FILE_NAME)
    if not os.path.isfile(source):
        return ""
    backup_root = os.path.join(rules_dir, BACKUP_DIR_NAME)
    os.makedirs(backup_root, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = f"{stamp}-{os.getpid()}"
    target = os.path.join(backup_root, base_name)
    counter = 2
    while os.path.exists(target):
        target = os.path.join(backup_root, f"{base_name}-{counter}")
        counter += 1
    os.makedirs(target)
    shutil.copy2(source, os.path.join(target, CUSTOM_TYPES_FILE_NAME))
    _prune_backups(backup_root)
    return target


def _coerce_name_list(names: object) -> list[object]:
    if isinstance(names, (str, bytes)) or not isinstance(names, Iterable):
        raise TypeError("names 必须是票种名称的可迭代对象")
    return list(names)


def save_custom_types(global_rules_dir: object, names: Iterable[str]) -> CustomTypes:
    """Validate and atomically persist the global custom type list."""
    directory = _resolve_rules_dir(global_rules_dir)
    path = os.path.join(directory, CUSTOM_TYPES_FILE_NAME)
    current = load_custom_types_file(path)
    raise_for_custom_types_issues(current)

    raw_names = _coerce_name_list(names)
    cleaned: list[str] = []
    issues: list[RuleIssue] = []
    for index, raw in enumerate(raw_names):
        if not isinstance(raw, str):
            issues.append(RuleIssue(path, index + 1, "票种名称必须是字符串"))
            continue
        text = raw.strip()
        if text and any(
            _normalize_type_name(text) == _normalize_type_name(existing)
            for existing in cleaned
        ):
            continue  # silently de-duplicate the submitted list
        error = custom_type_name_error(text, cleaned)
        if error:
            issues.append(RuleIssue(path, index + 1, error))
            continue
        cleaned.append(text)
    if issues:
        raise RuleConfigError(issues)

    payload = {"version": 1, "types": cleaned}
    os.makedirs(directory, exist_ok=True)
    _create_backup(directory)
    _atomic_write_text(path, _dump_yaml(payload))
    return load_custom_types_file(path)


def add_custom_type(name: str, global_rules_dir: object = None) -> CustomTypes:
    """Add one global custom type (idempotent for an existing normalized name)."""
    directory = _resolve_rules_dir(global_rules_dir)
    path = os.path.join(directory, CUSTOM_TYPES_FILE_NAME)
    current = load_custom_types_file(path)
    raise_for_custom_types_issues(current)
    if not isinstance(name, str):
        raise RuleConfigError([RuleIssue(path, 1, "票种名称必须是字符串")])
    text = name.strip()
    normalized = _normalize_type_name(text)
    if normalized and any(
        _normalize_type_name(existing) == normalized for existing in current.names
    ):
        return current
    error = custom_type_name_error(text, current.names)
    if error:
        raise RuleConfigError([RuleIssue(path, 1, error)])
    return save_custom_types(directory, (*current.names, text))


def remove_custom_type(name: str, global_rules_dir: object = None) -> CustomTypes:
    """Remove one global custom type; built-in types and unknown names are kept."""
    directory = _resolve_rules_dir(global_rules_dir)
    path = os.path.join(directory, CUSTOM_TYPES_FILE_NAME)
    current = load_custom_types_file(path)
    raise_for_custom_types_issues(current)
    if not isinstance(name, str) or not name.strip():
        raise RuleConfigError([RuleIssue(path, 1, "票种名称不能为空")])
    text = name.strip()
    normalized = _normalize_type_name(text)
    for builtin in _builtin_type_names():
        if _normalize_type_name(builtin) == normalized:
            raise RuleConfigError(
                [RuleIssue(path, 1, f"内置票种不可删除: {text}")]
            )
    remaining = tuple(
        existing
        for existing in current.names
        if _normalize_type_name(existing) != normalized
    )
    if len(remaining) == len(current.names):
        return current
    return save_custom_types(directory, remaining)


__all__ = [
    "CUSTOM_TYPES_FILE_NAME",
    "CustomTypeEntry",
    "CustomTypes",
    "builtin_type_names",
    "custom_type_name_error",
    "custom_types_file_path",
    "load_custom_types",
    "load_custom_types_file",
    "raise_for_custom_types_issues",
    "remove_custom_type",
    "save_custom_types",
    "add_custom_type",
]

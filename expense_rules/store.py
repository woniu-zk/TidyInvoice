"""Scope persistence: read/save/reset/template for rules directories.

``read_scope``/``save_scope``/``reset_scope``/``ensure_scope_template`` work on
one scope at a time (global ``<settings>/rules`` or library ``<library>/rules``).

Saving always validates the *merged* result first (via the loader's in-memory
override path), so a broken edit can never be written. Existing rule files are
backed up to ``<rules>/.backup/<YYYYmmdd-HHMMSS>-<pid>/`` (newest 20 kept) and
every write is atomic (temp file + ``os.replace``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
import os
import shutil
import tempfile
from typing import Any

import yaml

from .loader import (
    CATEGORIES_FILE_NAME,
    USER_TERMS_FILE_NAME,
    default_global_rules_dir,
    has_errors,
    load_rule_set,
    parse_categories_file,
    parse_terms_file,
    resolve_rules_dir,
)
from .model import (
    RuleConfigError,
    RuleIssue,
    RuleSet,
    ScopeData,
    SEVERITY_WARNING,
)

BACKUP_DIR_NAME = ".backup"
MAX_BACKUP_DIRS = 20

_CATEGORIES_HEADER = (
    "# InvoiceFlowAI 分类规则（{scope_label}）\n"
    "#\n"
    "# 只写需要覆盖的字段即可：分类按 id 合并，未写的字段沿用更早的层级\n"
    "# （内置默认 -> 全局 -> 当前发票库 -> rules.d 规则包）。\n"
    "# 保存时应用会先校验合并结果，并把旧文件备份到 .backup/ 目录。\n"
    "#\n"
    "# 规则按列表顺序匹配：越晚的层级越优先，同层内越靠前的条目越优先；\n"
    "# priority 字段已废弃（旧配置仍可读取，但不再影响匹配顺序）。\n"
    "# 自定义票种在全局 rules/custom_types.yaml 中登记后可在任何作用域使用。\n"
    "#\n"
    "# categories:\n"
    "#   - id: taxi\n"
    "#     keywords: [滴滴]\n"
    "#\n"
    "#   # 推荐写法：target_type 指定输出票种（内置票种或全局 custom_types.yaml\n"
    "#   # 中的自定义票种），归档文件夹 = 票种 + 金额区间后缀。\n"
    "#   # 这类规则不按 invoice_types 过滤，只按关键词与金额匹配。\n"
    "#   - id: rule_1\n"
    "#     target_type: 住宿发票\n"
    "#     keywords: [酒店]\n"
    "#     amount_range: [100, 200]\n"
    "#     # -> 文件夹 住宿发票-100-200\n"
    "#\n"
    "#   # 兼容旧写法：auto_folder 规则由「第一个关键词 + amount_range」自动\n"
    "#   # 生成分类名与归档文件夹（例如 餐饮、餐饮100以上、餐饮100-200）。\n"
    "#   - id: meal_100\n"
    "#     auto_folder: true\n"
    "#     keywords: [餐饮]\n"
    "#     amount_range: [100, null]\n"
    "# fallback: other\n"
    "# type_categories:\n"
    "#   打车: taxi\n"
)

_TERMS_HEADER = (
    "# InvoiceFlowAI 卖方字典（{scope_label}）\n"
    "#\n"
    "# 词条（卖方名称或卖方税号）-> 分类 id。\n"
    "# 税号按忽略空格、忽略大小写精确匹配；名称按包含匹配（越长越优先）。\n"
    "#\n"
    "# terms:\n"
    "#   滴滴出行科技有限公司: taxi\n"
    "#   91110108MA01ABCDEF: taxi\n"
)

_SCOPE_LABELS = {"global": "全局", "library": "当前发票库"}


def _scope_label(scope: str) -> str:
    return _SCOPE_LABELS.get(scope, scope)


def _rules_dir_for(scope: str, library_dir: object) -> str:
    return resolve_rules_dir(scope, library_dir)


def read_scope(scope: str, library_dir: object = None) -> ScopeData:
    """Read the raw (unmerged) contents of one scope's rules directory."""
    rules_dir = _rules_dir_for(scope, library_dir)
    categories_path = os.path.join(rules_dir, CATEGORIES_FILE_NAME)
    terms_path = os.path.join(rules_dir, USER_TERMS_FILE_NAME)

    issues: list[RuleIssue] = []
    files: list[str] = []
    categories: tuple[dict[str, Any], ...] = ()
    fallback: str | None = None
    type_categories: dict[str, str] = {}
    version: int | None = None
    terms: dict[str, str] = {}

    categories_file = parse_categories_file(categories_path)
    if categories_file is not None:
        files.append(categories_path)
        issues.extend(categories_file.issues)
        categories = tuple(dict(entry.raw) for entry in categories_file.entries)
        fallback = categories_file.fallback[0] if categories_file.fallback else None
        type_categories = {
            raw_type: target for raw_type, target, _line in categories_file.type_categories
        }
        version = categories_file.version

    terms_file = parse_terms_file(terms_path)
    if terms_file is not None:
        files.append(terms_path)
        issues.extend(terms_file.issues)
        terms = {raw_term: target for raw_term, target, _line in terms_file.terms}
        if version is None:
            version = terms_file.version

    if has_errors(issues):
        raise RuleConfigError(issues)
    warnings = tuple(issue for issue in issues if issue.severity == SEVERITY_WARNING)
    return ScopeData(
        scope=str(scope),
        rules_dir=rules_dir,
        categories=categories,
        terms=terms,
        fallback=fallback,
        type_categories=type_categories,
        version=version,
        files=tuple(files),
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def _scope_file_payload(
    categories: Iterable[Mapping[str, Any]],
    fallback: str | None,
    type_categories: Mapping[str, str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"version": 1}
    if fallback:
        payload["fallback"] = fallback
    if type_categories:
        payload["type_categories"] = dict(type_categories)
    payload["categories"] = [dict(category) for category in categories]
    return payload


def _dump_yaml(payload: Mapping[str, Any], header: str) -> str:
    body = yaml.safe_dump(
        dict(payload),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    if not body.endswith("\n"):
        body += "\n"
    return header + body


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


def _create_backup(rules_dir: str, file_names: Iterable[str]) -> str:
    """Copy existing rule files into a fresh timestamped backup dir (or "")."""
    existing = [
        name
        for name in file_names
        if os.path.isfile(os.path.join(rules_dir, name))
    ]
    if not existing:
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
    for name in existing:
        shutil.copy2(os.path.join(rules_dir, name), os.path.join(target, name))
    _prune_backups(backup_root)
    return target


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


def save_scope(
    scope: str,
    library_dir: object,
    categories: Iterable[Mapping[str, Any]],
    terms: Mapping[str, str],
    fallback: str | None = None,
) -> RuleSet:
    """Validate and atomically persist one scope's categories + terms."""
    rules_dir = _rules_dir_for(scope, library_dir)
    current = read_scope(scope, library_dir)
    proposed_categories = [dict(entry) for entry in categories]
    proposed_terms = dict(terms)
    proposed_fallback = current.fallback if fallback is None else fallback
    proposed = ScopeData(
        scope=str(scope),
        rules_dir=rules_dir,
        categories=tuple(proposed_categories),
        terms=proposed_terms,
        fallback=proposed_fallback,
        type_categories=dict(current.type_categories),
        version=1,
    )

    # Validate the merged result before touching any file on disk.
    load_rule_set(
        library_dir if str(scope) == "library" else None,
        overrides={str(scope): proposed},
    )

    categories_text = _dump_yaml(
        _scope_file_payload(
            proposed_categories,
            proposed_fallback,
            current.type_categories,
        ),
        _CATEGORIES_HEADER.format(scope_label=_scope_label(str(scope))),
    )
    terms_payload: dict[str, Any] = {"version": 1, "terms": dict(proposed_terms)}
    terms_text = _dump_yaml(
        terms_payload,
        _TERMS_HEADER.format(scope_label=_scope_label(str(scope))),
    )

    os.makedirs(rules_dir, exist_ok=True)
    _create_backup(rules_dir, (CATEGORIES_FILE_NAME, USER_TERMS_FILE_NAME))
    _atomic_write_text(os.path.join(rules_dir, CATEGORIES_FILE_NAME), categories_text)
    _atomic_write_text(os.path.join(rules_dir, USER_TERMS_FILE_NAME), terms_text)

    return load_rule_set(library_dir if str(scope) == "library" else None)


def reset_scope(scope: str, library_dir: object) -> list[str]:
    """Back up then remove categories.yaml/user_terms.yaml (keeps rules.d)."""
    rules_dir = _rules_dir_for(scope, library_dir)
    backup_dir = _create_backup(rules_dir, (CATEGORIES_FILE_NAME, USER_TERMS_FILE_NAME))
    for name in (CATEGORIES_FILE_NAME, USER_TERMS_FILE_NAME):
        path = os.path.join(rules_dir, name)
        if os.path.isfile(path):
            os.remove(path)
    return [backup_dir] if backup_dir else []


def ensure_scope_template(scope: str, library_dir: object = None) -> str:
    """Create commented-but-valid scope files when missing; return categories path."""
    rules_dir = _rules_dir_for(scope, library_dir)
    os.makedirs(rules_dir, exist_ok=True)
    categories_path = os.path.join(rules_dir, CATEGORIES_FILE_NAME)
    terms_path = os.path.join(rules_dir, USER_TERMS_FILE_NAME)
    if not os.path.isfile(categories_path):
        _atomic_write_text(
            categories_path,
            _CATEGORIES_HEADER.format(scope_label=_scope_label(str(scope)))
            + "version: 1\ncategories: []\n",
        )
    if not os.path.isfile(terms_path):
        _atomic_write_text(
            terms_path,
            _TERMS_HEADER.format(scope_label=_scope_label(str(scope)))
            + "version: 1\nterms: {}\n",
        )
    return categories_path


def default_rules_dir() -> str:
    """The user-wide rules directory used when no explicit dir is given."""
    return default_global_rules_dir()

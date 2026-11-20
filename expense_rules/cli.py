"""Command line interface for the classification-rules core.

Usage examples::

    python -m expense_rules.cli list
    python -m expense_rules.cli --library ./发票库 list
    python -m expense_rules.cli validate
    python -m expense_rules.cli test --type 其他 --seller 滴滴出行
    python -m expense_rules.cli explain --text 酒店 --type 其他
    python -m expense_rules.cli add-keyword taxi 新平台名
    python -m expense_rules.cli add-category parking --name 停车费 --archive-folder 停车费
    python -m expense_rules.cli remove-keyword taxi 新平台名
    python -m expense_rules.cli disable quota
    python -m expense_rules.cli rename quota 定额发票
    python -m expense_rules.cli terms --add 滴滴出行科技有限公司=taxi
    python -m expense_rules.cli reset --yes

``--library DIR`` selects that invoice library's rules scope; without it the
global user scope is used. Write commands persist through :func:`save_scope`,
which validates the merged rule set and backs up the previous files first.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Sequence

from brand_generated import BRAND_NAME

from .engine import classify, explain
from .loader import load_rule_set
from .model import (
    CATEGORY_ID_RE,
    SCOPE_GLOBAL,
    SCOPE_LIBRARY,
    RuleConfigError,
    RuleIssue,
    RuleSet,
    amount_range_folder_suffix,
    folder_from_type_and_amount,
    format_amount_bound,
)
from .store import ensure_scope_template, read_scope, reset_scope, save_scope
from .types import (
    add_custom_type,
    builtin_type_names,
    load_custom_types,
    remove_custom_type,
)


# --------------------------------------------------------------------------- #
# Common helpers
# --------------------------------------------------------------------------- #


def _library_from_args(args: argparse.Namespace) -> str:
    return str(getattr(args, "library", "") or "").strip()


def _scope_name(library: str) -> str:
    return SCOPE_LIBRARY if library else SCOPE_GLOBAL


def _scope_arg(library: str) -> str | None:
    return library or None


def _load_rules(library: str) -> RuleSet:
    return load_rule_set(_scope_arg(library))


def _print_issues(issues: Sequence[RuleIssue], args: argparse.Namespace) -> None:
    if getattr(args, "json", False):
        payload = {"ok": False, "issues": [issue.to_dict() for issue in issues]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for issue in issues:
        print(str(issue), file=sys.stderr)


def _scope_categories(library: str) -> tuple[list[dict[str, Any]], dict[str, str], str | None]:
    data = read_scope(_scope_name(library), _scope_arg(library))
    return [dict(entry) for entry in data.categories], dict(data.terms), data.fallback


def _persist(
    library: str,
    categories: list[dict[str, Any]],
    terms: dict[str, str],
    fallback: str | None,
) -> RuleSet:
    return save_scope(
        _scope_name(library),
        _scope_arg(library),
        categories,
        terms,
        fallback=fallback,
    )


def _upsert_category(
    entries: list[dict[str, Any]], category_id: str, updates: dict[str, Any]
) -> list[dict[str, Any]]:
    """Insert/merge a minimal category override, preserving existing fields."""
    result: list[dict[str, Any]] = []
    found = False
    for entry in entries:
        current = dict(entry)
        if str(current.get("id") or "").strip() == category_id:
            current.update(updates)
            found = True
        result.append(current)
    if not found:
        new_entry: dict[str, Any] = {"id": category_id}
        new_entry.update(updates)
        result.append(new_entry)
    return result


def _fields_from_args(args: argparse.Namespace) -> dict[str, str]:
    text = str(getattr(args, "text", "") or "").strip()
    seller = str(getattr(args, "seller", "") or "").strip()
    item = str(getattr(args, "item", "") or "").strip()
    return {
        "seller": seller or text,
        "seller_tin": str(getattr(args, "seller_tin", "") or ""),
        "item": item or text,
        "type": str(getattr(args, "type", "") or ""),
        "amount": str(getattr(args, "amount", "") or ""),
    }


def _open_with_system(path: str) -> None:
    startfile = getattr(os, "startfile", None)
    if callable(startfile):
        startfile(path)
        return
    if sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
        return
    subprocess.run(["xdg-open", path], check=False)


def _format_keywords(keywords: Sequence[Any]) -> str:
    items = [str(item) for item in keywords or () if str(item).strip()]
    return "、".join(items) if items else "-"


def _format_invoice_types(invoice_types: Sequence[Any]) -> str:
    items = [str(item) for item in invoice_types or () if str(item).strip()]
    return "、".join(items) if items else "全部"


def _amount_range_values(amount_range: object) -> list[str | None] | None:
    """JSON-friendly amount range (trimmed strings) or ``None``."""
    if amount_range is None:
        return None
    if isinstance(amount_range, (str, bytes)) or not isinstance(
        amount_range, (list, tuple)
    ):
        return None
    values = list(amount_range)[:2]
    while len(values) < 2:
        values.append(None)
    return [format_amount_bound(bound) or None for bound in values]


def _amount_text(amount_range: object) -> str:
    """Compact display text for an amount range (``100-200``/``100以上``)."""
    if amount_range is None:
        return "-"
    try:
        suffix = amount_range_folder_suffix(amount_range)
    except (ValueError, TypeError):
        return str(amount_range)
    return suffix or "-"


def _amount_arg_to_number(value: object) -> int | float | None:
    if value is None:
        return None
    number = float(value)
    if number.is_integer():
        int_value = int(number)
        return int_value if int_value == number else number
    return number


def _next_rule_id(rule_set: RuleSet) -> str:
    index = 1
    while f"rule_{index}" in rule_set.category_map:
        index += 1
    return f"rule_{index}"


def _rule_ids_referencing_type(rule_set: RuleSet, type_name: str) -> list[str]:
    return [
        rule.id
        for rule in rule_set.categories
        if rule.target_type and rule.target_type == type_name
    ]


def _print_rule_row(
    category_id: str,
    folder: str,
    keywords: Sequence[Any],
    amount_range: object,
    invoice_types: Sequence[Any],
    enabled: bool,
    scope: str,
    source: str,
    auto_folder: bool = False,
    target_type: str = "",
) -> None:
    state = "启用" if enabled else "停用"
    auto_mark = "[自动文件夹]" if auto_folder else ""
    if target_type:
        # target_type rules do not use invoice_types as a user-facing condition.
        rule_mark = f" | 输出票种={target_type}"
    else:
        rule_mark = f" | 票种={_format_invoice_types(invoice_types)}"
    print(
        f"{category_id} | 文件夹={folder or '-'} | 关键词={_format_keywords(keywords)}"
        f" | 金额={_amount_text(amount_range)}"
        f"{rule_mark} | {state}{auto_mark} | {scope} | {source}"
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def _cmd_list(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    scope_choice = str(getattr(args, "scope", "all") or "all")
    rows: list[dict[str, Any]] = []
    if scope_choice == "all":
        rule_set = _load_rules(library)
        for rule in rule_set.categories:
            rows.append(
                {
                    "id": rule.id,
                    "name": rule.name,
                    "archive_folder": rule.archive_folder,
                    "keywords": list(rule.keywords),
                    "amount_range": _amount_range_values(rule.amount_range),
                    "invoice_types": list(rule.invoice_types),
                    "enabled": rule.enabled,
                    "auto_folder": rule.auto_folder,
                    "target_type": rule.target_type,
                    "scope": rule.scope,
                    "source": f"{rule.source_file}:{rule.source_line}",
                }
            )
    else:
        scope = SCOPE_LIBRARY if scope_choice == "library" else SCOPE_GLOBAL
        data = read_scope(scope, _scope_arg(library))
        for entry in data.categories:
            rows.append(
                {
                    "id": str(entry.get("id") or ""),
                    "name": str(entry.get("name") or ""),
                    "archive_folder": str(entry.get("archive_folder") or ""),
                    "keywords": list(entry.get("keywords") or []),
                    "amount_range": _amount_range_values(entry.get("amount_range")),
                    "invoice_types": list(entry.get("invoice_types") or []),
                    "enabled": bool(entry.get("enabled", True)),
                    "auto_folder": bool(entry.get("auto_folder", False)),
                    "target_type": str(entry.get("target_type") or ""),
                    "scope": scope,
                    "source": str(data.rules_dir),
                }
            )
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "categories": rows}, ensure_ascii=False, indent=2))
        return 0
    rules_dir = library + "/rules" if library else _load_rules(library).global_rules_dir
    print(f"规则目录: {rules_dir}")
    print("（按列表顺序匹配：越晚的层级越靠前；priority 已废弃）")
    for row in rows:
        _print_rule_row(
            row["id"],
            row["archive_folder"],
            row["keywords"],
            row["amount_range"],
            row["invoice_types"],
            row["enabled"],
            row["scope"],
            row["source"],
            bool(row["auto_folder"]),
            str(row.get("target_type") or ""),
        )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    rule_set = _load_rules(library)
    warnings = [issue.to_dict() for issue in rule_set.warnings]
    if getattr(args, "json", False):
        payload = {
            "ok": True,
            "categories": len(rule_set.categories),
            "enabled": len(rule_set.ordered_categories),
            "fallback": rule_set.fallback_id,
            "custom_types": list(rule_set.custom_types),
            "document_types": list(rule_set.document_types),
            "custom_types_path": rule_set.custom_types_path,
            "warnings": warnings,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(
        f"规则有效：分类 {len(rule_set.categories)} 个"
        f"（启用 {len(rule_set.ordered_categories)} 个），兜底分类 {rule_set.fallback_id}"
    )
    if rule_set.custom_types:
        print(
            f"自定义票种 {len(rule_set.custom_types)} 个: "
            f"{'、'.join(rule_set.custom_types)}"
        )
    for warning in warnings:
        print(f"提示: {warning['file']}:{warning['line']}: {warning['message']}")
    return 0


def _cmd_test(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    rule_set = _load_rules(library)
    result = classify(_fields_from_args(args), rule_set)
    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0
    print(f"分类: {result.category_id} / {result.category_name}")
    print(f"归档目录: {result.archive_folder}")
    print(f"来源: {result.source}（{result.category_src}）")
    print(f"规则: {result.rule_id or '-'}  关键词: {result.keyword or '-'}")
    location = f"{result.source_file}:{result.source_line}" if result.source_file else "-"
    print(f"来源位置: {location}")
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    rule_set = _load_rules(library)
    payload = explain(_fields_from_args(args), rule_set)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"分类: {payload['category_id']} / {payload['category_name']}")
    print(f"归档目录: {payload['archive_folder']}")
    print(f"来源: {payload['source']}（{payload['category_src']}）")
    print("匹配过程:")
    for item in payload.get("chain", []):
        if not isinstance(item, dict):
            continue
        detail = " ".join(
            f"{key}={value}"
            for key, value in item.items()
            if key not in {"stage", "hit"}
            and isinstance(value, (str, int, bool))
        )
        hit = "命中" if item.get("hit") else "跳过"
        stage = str(item.get("stage") or "?")
        print(f"  [{hit}] {stage}: {detail}")
    return 0


def _cmd_edit(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    path = ensure_scope_template(_scope_name(library), _scope_arg(library))
    print(f"规则文件: {path}")
    _open_with_system(path)
    return 0


def _cmd_add_rule(args: argparse.Namespace) -> int:
    """Add a target-type rule: keyword/amount match output type + derived folder."""
    library = _library_from_args(args)
    keyword = str(args.keyword or "").strip()
    if not keyword:
        raise ValueError("关键词不能为空")
    target_type = str(getattr(args, "type", "") or "").strip()
    if not target_type:
        raise ValueError("add-rule 需要 --type 指定输出票种")
    lower = _amount_arg_to_number(getattr(args, "amount_min", None))
    upper = _amount_arg_to_number(getattr(args, "amount_max", None))
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("金额下限不能大于金额上限")
    amount_range: list[int | float | None] | None = None
    if lower is not None or upper is not None:
        amount_range = [lower, upper]
    rule_set = _load_rules(library)
    if target_type not in rule_set.document_types:
        raise ValueError(
            f"未知票种: {target_type}（可用内置票种或全局自定义票种）"
        )
    try:
        preview_folder = folder_from_type_and_amount(target_type, amount_range)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    rule_id = _next_rule_id(rule_set)
    entries, terms, fallback = _scope_categories(library)
    entry: dict[str, Any] = {
        "id": rule_id,
        "target_type": target_type,
        "keywords": [keyword],
    }
    if amount_range is not None:
        entry["amount_range"] = amount_range
    entries = _upsert_category(entries, rule_id, entry)
    rule_set = _persist(library, entries, terms, fallback)
    category = rule_set.get_category(rule_id)
    folder = category.archive_folder if category is not None else preview_folder
    print(
        f"已新增规则 {rule_id}: 关键词={keyword}"
        f" | 金额={_amount_text(category.amount_range if category else amount_range)}"
        f" | 输出票种={target_type}"
        f" -> 文件夹 {folder}"
    )
    return 0


def _cmd_add_category(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    category_id = str(args.id or "").strip()
    if not CATEGORY_ID_RE.match(category_id):
        raise ValueError(
            f"分类 id 不合法: {category_id!r}（需匹配 ^[a-z][a-z0-9_]*$）"
        )
    rule_set = _load_rules(library)
    if rule_set.get_category(category_id) is not None:
        raise ValueError(f"分类已存在: {category_id}")
    entries, terms, fallback = _scope_categories(library)
    name = str(args.name or "").strip()
    entry: dict[str, Any] = {
        "id": category_id,
        "name": name,
        "archive_folder": str(args.folder or name).strip(),
        "match": "seller_item" if str(args.match) == "any" else str(args.match),
    }
    keywords = [
        str(keyword).strip()
        for keyword in (args.keyword or [])
        if str(keyword).strip()
    ]
    if keywords:
        entry["keywords"] = keywords
    amount_min = _amount_arg_to_number(getattr(args, "amount_min", None))
    amount_max = _amount_arg_to_number(getattr(args, "amount_max", None))
    if amount_min is not None or amount_max is not None:
        entry["amount_range"] = [amount_min, amount_max]
    entries = _upsert_category(entries, category_id, entry)
    rule_set = _persist(library, entries, terms, fallback)
    print(f"已新增分类 {category_id}（当前共 {len(rule_set.categories)} 个分类）")
    return 0


def _cmd_add_keyword(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    rule_set = _load_rules(library)
    category = rule_set.get_category(args.category)
    if category is None:
        raise ValueError(f"未知分类: {args.category}")
    effective = list(category.keywords)
    added: list[str] = []
    for raw_keyword in args.keywords:
        keyword = str(raw_keyword or "").strip()
        if not keyword:
            continue
        if keyword not in effective:
            effective.append(keyword)
            added.append(keyword)
    if not added:
        print("关键词均已存在，无需修改")
        return 0
    entries, terms, fallback = _scope_categories(library)
    entries = _upsert_category(entries, category.id, {"keywords": effective})
    rule_set = _persist(library, entries, terms, fallback)
    current = rule_set.get_category(category.id)
    print(
        f"已为分类 {category.id} 添加关键词: {'、'.join(added)}"
        f"（当前 {len(current.keywords) if current else 0} 个）"
    )
    return 0


def _cmd_remove_keyword(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    rule_set = _load_rules(library)
    category = rule_set.get_category(args.category)
    if category is None:
        raise ValueError(f"未知分类: {args.category}")
    removing = {str(keyword or "").strip() for keyword in args.keywords}
    removing.discard("")
    remaining = [keyword for keyword in category.keywords if keyword not in removing]
    missing = sorted(removing - set(category.keywords))
    if len(remaining) == len(category.keywords):
        print(f"分类 {category.id} 没有这些关键词: {'、'.join(missing)}")
        return 1
    entries, terms, fallback = _scope_categories(library)
    entries = _upsert_category(entries, category.id, {"keywords": remaining})
    _persist(library, entries, terms, fallback)
    if missing:
        print(f"提示: 未找到关键词: {'、'.join(missing)}", file=sys.stderr)
    print(f"已从分类 {category.id} 移除关键词（当前 {len(remaining)} 个）")
    return 0


def _cmd_set_enabled(args: argparse.Namespace, *, enabled: bool) -> int:
    library = _library_from_args(args)
    rule_set = _load_rules(library)
    category = rule_set.get_category(args.category)
    if category is None:
        raise ValueError(f"未知分类: {args.category}")
    entries, terms, fallback = _scope_categories(library)
    entries = _upsert_category(entries, category.id, {"enabled": enabled})
    _persist(library, entries, terms, fallback)
    print(f"已{'启用' if enabled else '停用'}分类 {category.id}")
    return 0


def _cmd_enable(args: argparse.Namespace) -> int:
    return _cmd_set_enabled(args, enabled=True)


def _cmd_disable(args: argparse.Namespace) -> int:
    return _cmd_set_enabled(args, enabled=False)


def _cmd_rename(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    rule_set = _load_rules(library)
    category = rule_set.get_category(args.category)
    if category is None:
        raise ValueError(f"未知分类: {args.category}")
    name = str(args.name or "").strip()
    if not name:
        raise ValueError("新名称不能为空")
    updates: dict[str, Any] = {"name": name}
    if "archive_folder" not in category.field_sources:
        # The folder was implicitly derived from the old name; pin it so a
        # rename never moves already-archived files.
        updates["archive_folder"] = category.archive_folder
    entries, terms, fallback = _scope_categories(library)
    entries = _upsert_category(entries, category.id, updates)
    _persist(library, entries, terms, fallback)
    print(f"已重命名分类 {category.id}: {category.name} -> {name}")
    return 0


def _cmd_terms(args: argparse.Namespace) -> int:
    library = _library_from_args(args)
    rule_set = _load_rules(library)
    entries, terms, fallback = _scope_categories(library)
    changed = False
    for raw_spec in args.add or []:
        spec = str(raw_spec or "")
        if "=" not in spec:
            raise ValueError("--add 需要 TERM=CATEGORY_ID 格式")
        raw_term, raw_category = spec.rsplit("=", 1)
        term = raw_term.strip()
        category_id = raw_category.strip()
        if not term or not category_id:
            raise ValueError("--add 需要 TERM=CATEGORY_ID 格式")
        category = rule_set.get_category(category_id)
        if category is None:
            raise ValueError(f"未知分类: {category_id}")
        if not category.enabled:
            raise ValueError(f"分类已停用: {category_id}")
        terms[term] = category_id
        changed = True
    for raw_term in args.remove or []:
        term = str(raw_term or "").strip()
        if term in terms:
            del terms[term]
            changed = True
        else:
            print(f"提示: 词条不存在: {term}", file=sys.stderr)
    if changed:
        rule_set = _persist(library, entries, terms, fallback)
        print(f"已保存词条（当前 {len(rule_set.terms)} 条）")
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "terms": dict(rule_set.terms)}, ensure_ascii=False, indent=2))
        return 0
    if not changed or args.list:
        print("卖方字典:")
        for term, category_id in sorted(rule_set.terms.items()):
            print(f"  {term} -> {category_id}")
        if not rule_set.terms:
            print("  （空）")
    return 0


def _cmd_types(args: argparse.Namespace) -> int:
    """Manage the global custom invoice types (``custom_types.yaml``)."""
    action = str(getattr(args, "action", "") or "").strip()
    name = str(getattr(args, "name", "") or "").strip()
    library = _library_from_args(args)
    if action == "list":
        types = load_custom_types()
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "custom_types": list(types.names),
                        "builtin_types": list(builtin_type_names()),
                        "path": types.path,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(f"自定义票种文件: {types.path}")
        print(f"内置票种: {'、'.join(builtin_type_names())}")
        print(
            "自定义票种: "
            + ("、".join(types.names) if types.names else "（空）")
        )
        return 0
    if action == "add":
        if not name:
            raise ValueError("types add 需要票种名称")
        types = add_custom_type(name)
    elif action == "remove":
        if not name:
            raise ValueError("types remove 需要票种名称")
        if name in builtin_type_names():
            raise ValueError(f"内置票种不可删除: {name}")
        references = _rule_ids_referencing_type(_load_rules(None), name)
        if library:
            # The types file is global, but a removal must not silently break
            # rules of the current invoice library either.
            references += _rule_ids_referencing_type(_load_rules(library), name)
        unique_references = list(dict.fromkeys(references))
        if unique_references:
            raise ValueError(
                f"自定义票种 {name} 仍被规则引用: {'、'.join(unique_references)}"
            )
        types = remove_custom_type(name)
    else:
        raise ValueError(f"未知的 types 操作: {action}")

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "ok": True,
                    "action": action,
                    "custom_types": list(types.names),
                    "path": types.path,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    verb = "新增" if action == "add" else "删除"
    print(f"已{verb}自定义票种 {name}（当前: {'、'.join(types.names) or '空'}）")
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    if not getattr(args, "yes", False):
        print(
            "reset 会删除当前作用域的 categories.yaml/user_terms.yaml（先备份）；"
            "请加 --yes 确认",
            file=sys.stderr,
        )
        return 2
    library = _library_from_args(args)
    backups = reset_scope(_scope_name(library), _scope_arg(library))
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "backups": backups}, ensure_ascii=False, indent=2))
        return 0
    if backups:
        print(f"已重置；旧文件备份在: {backups[0]}")
    else:
        print("当前作用域没有可重置的规则文件")
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--library",
        default="",
        metavar="DIR",
        help="发票库目录；指定后读写该库的规则作用域（默认全局规则）",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")


def _add_match_fields(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--text", default="", help="同时作为卖方与票面明细文本")
    parser.add_argument("--seller", default="", help="卖方名称")
    parser.add_argument("--seller-tin", default="", dest="seller_tin", help="卖方税号")
    parser.add_argument("--item", default="", help="票面明细/商品名称")
    parser.add_argument("--type", default="", help="已识别票种（如 打车/住宿发票）")
    parser.add_argument("--amount", default="", help="金额")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expense_rules",
        description=f"{BRAND_NAME} 分类规则管理（全局规则 / 发票库规则）",
    )
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="列出分类规则")
    _add_common(list_parser)
    list_parser.add_argument(
        "--scope",
        choices=("all", "global", "library"),
        default="all",
        help="all=合并后的生效规则（默认）；global/library=只看该作用域自己的条目",
    )
    list_parser.set_defaults(handler=_cmd_list)

    validate_parser = subparsers.add_parser("validate", help="校验规则文件")
    _add_common(validate_parser)
    validate_parser.set_defaults(handler=_cmd_validate)

    test_parser = subparsers.add_parser("test", help="对一条样例做分类")
    _add_common(test_parser)
    _add_match_fields(test_parser)
    test_parser.set_defaults(handler=_cmd_test)

    explain_parser = subparsers.add_parser("explain", help="输出分类与完整匹配过程")
    _add_common(explain_parser)
    _add_match_fields(explain_parser)
    explain_parser.set_defaults(handler=_cmd_explain)

    edit_parser = subparsers.add_parser("edit", help="用系统默认编辑器打开规则文件")
    _add_common(edit_parser)
    edit_parser.set_defaults(handler=_cmd_edit)

    add_rule = subparsers.add_parser(
        "add-rule",
        help="新增输出票种规则（按关键词/金额匹配，文件夹由票种自动生成）",
    )
    _add_common(add_rule)
    add_rule.add_argument("keyword", help="匹配关键词")
    add_rule.add_argument(
        "--type",
        dest="type",
        required=True,
        help="输出票种（内置票种或全局自定义票种）",
    )
    add_rule.add_argument("--amount-min", type=float, default=None, help="金额下限（含）")
    add_rule.add_argument("--amount-max", type=float, default=None, help="金额上限（含）")
    add_rule.set_defaults(handler=_cmd_add_rule)

    add_category = subparsers.add_parser(
        "add-category",
        help="高级：手工新增分类（旧式，名称/文件夹需自己指定）",
    )
    _add_common(add_category)
    add_category.add_argument("id", help="分类 id（小写字母开头，可含数字/下划线）")
    add_category.add_argument("--name", required=True, help="分类显示名")
    add_category.add_argument(
        "--folder",
        "--archive-folder",
        dest="folder",
        default="",
        help="归档文件夹名（默认同显示名）",
    )
    add_category.add_argument(
        "--match",
        choices=("any", "seller", "item", "seller_item"),
        default="seller_item",
        help="关键词匹配文本范围",
    )
    add_category.add_argument(
        "--keyword",
        "--keywords",
        dest="keyword",
        action="append",
        default=[],
        help="初始关键词（可重复）",
    )
    add_category.add_argument("--amount-min", type=float, default=None, help="金额下限（含）")
    add_category.add_argument("--amount-max", type=float, default=None, help="金额上限（含）")
    add_category.set_defaults(handler=_cmd_add_category)

    add_keyword = subparsers.add_parser("add-keyword", help="为分类追加关键词")
    _add_common(add_keyword)
    add_keyword.add_argument("category", help="分类 id")
    add_keyword.add_argument("keywords", nargs="+", help="一个或多个关键词")
    add_keyword.set_defaults(handler=_cmd_add_keyword)

    remove_keyword = subparsers.add_parser("remove-keyword", help="从分类移除关键词")
    _add_common(remove_keyword)
    remove_keyword.add_argument("category", help="分类 id")
    remove_keyword.add_argument("keywords", nargs="+", help="一个或多个关键词")
    remove_keyword.set_defaults(handler=_cmd_remove_keyword)

    enable_parser = subparsers.add_parser("enable", help="启用分类")
    _add_common(enable_parser)
    enable_parser.add_argument("category", help="分类 id")
    enable_parser.set_defaults(handler=_cmd_enable)

    disable_parser = subparsers.add_parser("disable", help="停用分类")
    _add_common(disable_parser)
    disable_parser.add_argument("category", help="分类 id")
    disable_parser.set_defaults(handler=_cmd_disable)

    rename_parser = subparsers.add_parser("rename", help="重命名分类")
    _add_common(rename_parser)
    rename_parser.add_argument("category", help="分类 id")
    rename_parser.add_argument("name", help="新显示名")
    rename_parser.set_defaults(handler=_cmd_rename)

    terms_parser = subparsers.add_parser("terms", help="管理卖方字典词条")
    _add_common(terms_parser)
    terms_parser.add_argument(
        "--add",
        action="append",
        default=[],
        metavar="TERM=CATEGORY",
        help="新增/覆盖词条（可重复）",
    )
    terms_parser.add_argument(
        "--remove",
        action="append",
        default=[],
        metavar="TERM",
        help="删除词条（可重复）",
    )
    terms_parser.add_argument("--list", action="store_true", help="列出当前词条")
    terms_parser.set_defaults(handler=_cmd_terms)

    types_parser = subparsers.add_parser(
        "types", help="管理全局自定义票种（custom_types.yaml，全局生效）"
    )
    _add_common(types_parser)
    types_parser.add_argument("action", choices=("list", "add", "remove"))
    types_parser.add_argument("name", nargs="?", default="", help="票种名称")
    types_parser.set_defaults(handler=_cmd_types)

    reset_parser = subparsers.add_parser("reset", help="备份并清空当前作用域规则")
    _add_common(reset_parser)
    reset_parser.add_argument("--yes", action="store_true", help="确认执行（必须）")
    reset_parser.set_defaults(handler=_cmd_reset)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return int(handler(args) or 0)
    except RuleConfigError as exc:
        _print_issues(exc.issues, args)
        return 1
    except (OSError, ValueError, TypeError) as exc:
        if getattr(args, "json", False):
            payload = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

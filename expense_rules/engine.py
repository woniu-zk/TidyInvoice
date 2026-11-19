"""Classification engine: normalize document fields and match the rule set.

Matching order (first hit wins):

1. the seller dictionary (seller TIN exact match; else seller name substring,
   longest term first, later layer wins ties);
2. enabled categories in the pre-computed match order (later layer first,
   then declaration/list order within the layer) -- each rule checks its
   ``invoice_types``, ``amount_range``, ``match`` text and exclude keywords;
3. the ``type_categories`` fallback for the recognized document type;
4. unknown: the result carries the fallback category identity but
   ``source``/``category_src`` stay ``"unknown"`` so the caller can route the
   document to manual review.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from document_types import normalize_document_type
from invoice_domain import parse_amount

from .model import (
    CATEGORY_SOURCE_BUILTIN,
    CATEGORY_SOURCE_UNKNOWN,
    CATEGORY_SOURCE_USER,
    DEFAULT_MATCH,
    MATCH_FIELDS,
    MATCH_ITEM,
    MATCH_SELLER,
    SOURCE_BUILTIN_KEYWORD,
    SOURCE_BUILTIN_TYPE,
    SOURCE_DICTIONARY,
    SOURCE_RULE_PACK,
    SOURCE_UNKNOWN,
    SOURCE_USER_RULE,
    CategoryRule,
    ClassificationResult,
    RuleSet,
    SourceRef,
    TermEntry,
    normalize_text,
    normalize_tin,
)

DEFAULT_DOCUMENT_TYPE = "其他"

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "seller": (
        "seller",
        "seller_name",
        "sellername",
        "merchant",
        "merchant_name",
        "销售方",
        "销方名称",
        "商户",
    ),
    "seller_tin": (
        "seller_tin",
        "sellertin",
        "seller_tax_id",
        "seller_taxid",
        "seller_tax_no",
        "sellertaxno",
        "销方税号",
        "销售方税号",
    ),
    "item": (
        "item",
        "items",
        "item_name",
        "item_names",
        "goods",
        "goods_name",
        "product",
        "product_name",
        "商品名称",
        "货物名称",
        "项目名称",
        "项目/商品名称",
    ),
    "type": (
        "type",
        "document_type",
        "doc_type",
        "invoice_type",
        "票据类型",
        "票种",
        "类型",
    ),
    "amount": (
        "amount",
        "total",
        "total_amount",
        "amount_total",
        "价税合计",
        "金额",
        "合计金额",
    ),
    "purchaser": (
        "purchaser",
        "buyer",
        "buyer_name",
        "购买方",
        "购方名称",
    ),
}


def _build_field_alias_map() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for canonical, names in _FIELD_ALIASES.items():
        for name in names:
            aliases[name.casefold()] = canonical
    return aliases


_FIELD_ALIAS_MAP = _build_field_alias_map()


def _as_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _safe_parse_amount(value: object) -> Decimal | None:
    try:
        return parse_amount(value)
    except (TypeError, ValueError):
        return None


def normalize_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a classification payload to the documented canonical keys.

    Canonical keys: ``seller``, ``seller_tin``, ``item``, ``type``, ``amount``,
    ``purchaser``. A few common aliases (``Seller``, ``Item``, ``Amount``,
    ``item_name``, ...) are accepted so callers can pass invoice payloads
    directly.
    """
    normalized: dict[str, Any] = {
        "seller": "",
        "seller_tin": "",
        "item": "",
        "type": "",
        "amount": None,
        "purchaser": "",
    }
    if fields is None:
        return normalized
    if not isinstance(fields, Mapping):
        raise TypeError("fields 必须是映射（mapping）")
    for raw_key, raw_value in fields.items():
        canonical = _FIELD_ALIAS_MAP.get(str(raw_key or "").strip().casefold())
        if canonical is None:
            continue
        if canonical == "amount":
            normalized["amount"] = _safe_parse_amount(raw_value)
        else:
            normalized[canonical] = _as_text(raw_value)
    return normalized


def _normalized_type(raw_type: object) -> str:
    text = _as_text(raw_type)
    if not text:
        return DEFAULT_DOCUMENT_TYPE
    return str(normalize_document_type(text))


def _match_dictionary(
    rule_set: RuleSet, fields: Mapping[str, Any]
) -> tuple[TermEntry | None, str]:
    """Return ``(term_entry, kind)`` for the first seller dictionary hit."""
    seller_tin = normalize_tin(fields.get("seller_tin"))
    if seller_tin:
        candidates = [
            entry
            for entry in rule_set.term_entries
            if entry.normalized_tin == seller_tin
        ]
        if candidates:
            # Later layer wins ties (the loader records layer_index/order).
            chosen = max(candidates, key=lambda entry: (entry.layer_index, entry.order))
            return chosen, "seller_tin"
    seller_text = normalize_text(fields.get("seller"))
    if not seller_text:
        return None, ""
    ordered = sorted(
        rule_set.term_entries,
        key=lambda entry: (-len(entry.normalized_name), -entry.layer_index, -entry.order),
    )
    for entry in ordered:
        if entry.normalized_name and entry.normalized_name in seller_text:
            return entry, "seller_name"
    return None, ""


def _evaluate_rule(
    rule: CategoryRule,
    *,
    type_name: str,
    seller_text: str,
    item_text: str,
    amount: Decimal | None,
) -> dict[str, Any]:
    """Evaluate one keyword rule and return its chain record."""
    detail: dict[str, Any] = {
        "stage": "rule",
        "rule_id": rule.id,
        "hit": False,
        "reason": "",
    }
    if not rule.enabled:
        detail["reason"] = "disabled"
        return detail
    # Output-type rules (``target_type``) pick the archive type themselves, so
    # the recognized ``invoice_types`` must not gate user rules. Built-in rules
    # keep their historical invoice-types gate even when they carry a target_type.
    if rule.target_type:
        detail["target_type"] = rule.target_type
        if (
            rule.builtin_rule
            and rule.invoice_types
            and type_name not in rule.invoice_types
        ):
            detail["reason"] = "invoice_type_mismatch"
            return detail
    elif rule.invoice_types and type_name not in rule.invoice_types:
        detail["reason"] = "invoice_type_mismatch"
        return detail
    if rule.amount_range is not None:
        if amount is None:
            detail["reason"] = "amount_missing"
            return detail
        lower, upper = rule.amount_range
        if lower is not None and amount < lower:
            detail["reason"] = "amount_out_of_range"
            return detail
        if upper is not None and amount > upper:
            detail["reason"] = "amount_out_of_range"
            return detail
    if rule.match == MATCH_SELLER:
        match_text = seller_text
    elif rule.match == MATCH_ITEM:
        match_text = item_text
    else:
        match_text = seller_text + item_text
    if not match_text:
        detail["reason"] = "empty_match_text"
        return detail
    for excluded in rule.exclude_keywords:
        normalized_exclude = normalize_text(excluded)
        if normalized_exclude and normalized_exclude in match_text:
            detail["reason"] = "excluded"
            detail["exclude_keyword"] = excluded
            return detail
    for keyword in rule.keywords:
        normalized_keyword = normalize_text(keyword)
        if normalized_keyword and normalized_keyword in match_text:
            detail["hit"] = True
            detail["reason"] = "keyword"
            detail["keyword"] = keyword
            return detail
    detail["reason"] = "no_keyword_matched"
    return detail


def _keyword_rule_source(rule: CategoryRule) -> str:
    if rule.scope == CATEGORY_SOURCE_BUILTIN:
        return SOURCE_BUILTIN_KEYWORD
    if rule.layer_kind == "pack":
        return SOURCE_RULE_PACK
    return SOURCE_USER_RULE


def _type_rule_source(source: SourceRef | None) -> str:
    kind = source.kind if source is not None else ""
    if kind == "builtin":
        return SOURCE_BUILTIN_TYPE
    if kind == "pack":
        return SOURCE_RULE_PACK
    return SOURCE_USER_RULE


def _result_for_category(
    category: CategoryRule,
    *,
    source: str,
    rule_id: str = "",
    keyword: str = "",
    priority: int = 0,
    source_ref: SourceRef | None = None,
    chain: list[dict[str, Any]],
    evidence_user: bool = False,
    category_src: str | None = None,
) -> ClassificationResult:
    if category_src is None:
        # A decision is "user" when the matching evidence came from user
        # configuration (dictionary/user rule/overridden type mapping) or when
        # the effective category itself was redefined by a user layer.
        category_src = (
            CATEGORY_SOURCE_USER
            if evidence_user or category.scope == CATEGORY_SOURCE_USER
            else CATEGORY_SOURCE_BUILTIN
        )
    return ClassificationResult(
        category_id=category.id,
        category_name=category.name,
        archive_folder=category.archive_folder,
        category_src=category_src,
        source=source,
        rule_id=rule_id,
        keyword=keyword,
        priority=priority,
        source_file=source_ref.file if source_ref is not None else "",
        source_line=source_ref.line if source_ref is not None else 0,
        chain=chain,
    )


def classify(
    fields: Mapping[str, Any] | None,
    rule_set: RuleSet,
) -> ClassificationResult:
    """Classify one document's fields against ``rule_set``."""
    if not isinstance(rule_set, RuleSet):
        raise TypeError("rule_set 必须是 RuleSet")
    normalized = normalize_fields(fields)
    type_name = _normalized_type(normalized.get("type"))
    seller_text = normalize_text(normalized.get("seller"))
    item_text = normalize_text(normalized.get("item"))
    amount = normalized.get("amount")
    chain: list[dict[str, Any]] = [
        {
            "stage": "input",
            "seller": normalized.get("seller") or "",
            "seller_tin": normalized.get("seller_tin") or "",
            "item": normalized.get("item") or "",
            "type": normalized.get("type") or "",
            "normalized_type": type_name,
            "amount": "" if amount is None else format(amount, "f"),
        }
    ]

    # 1) Seller dictionary (exact TIN, then seller-name substring).
    term, dictionary_kind = _match_dictionary(rule_set, normalized)
    chain.append(
        {
            "stage": "dictionary",
            "hit": term is not None,
            "kind": dictionary_kind,
            "term": term.raw if term is not None else "",
            "category": term.category_id if term is not None else "",
        }
    )
    if term is not None:
        category = rule_set.category_map.get(term.category_id)
        if category is not None:
            chain.append(
                {
                    "stage": "result",
                    "source": SOURCE_DICTIONARY,
                    "category": category.id,
                }
            )
            return _result_for_category(
                category,
                source=SOURCE_DICTIONARY,
                rule_id=category.id,
                keyword=term.raw,
                source_ref=SourceRef(
                    file=term.file,
                    line=term.line,
                    layer_index=term.layer_index,
                    kind="terms",
                ),
                evidence_user=True,
                chain=chain,
            )

    # 2) Keyword rules in the effective match order.
    evaluated = 0
    disabled = len(rule_set.categories) - len(rule_set.ordered_categories)
    for rule in rule_set.ordered_categories:
        evaluated += 1
        detail = _evaluate_rule(
            rule,
            type_name=type_name,
            seller_text=seller_text,
            item_text=item_text,
            amount=amount,
        )
        chain.append(detail)
        if not detail.get("hit"):
            continue
        source = _keyword_rule_source(rule)
        keyword = str(detail.get("keyword") or "")
        chain.append({"stage": "result", "source": source, "category": rule.id})
        return _result_for_category(
            rule,
            source=source,
            rule_id=rule.id,
            keyword=keyword,
            priority=rule.priority,
            source_ref=rule.keyword_source,
            evidence_user=rule.scope != CATEGORY_SOURCE_BUILTIN,
            chain=chain,
        )
    chain.append({"stage": "rule_scan", "evaluated": evaluated, "disabled_skipped": disabled})

    # 3) Recognized document type -> category mapping.
    mapped_category_id = rule_set.type_categories.get(type_name)
    type_source = rule_set.type_category_sources.get(type_name)
    if mapped_category_id:
        category = rule_set.category_map.get(mapped_category_id)
        if category is None or not category.enabled:
            chain.append(
                {
                    "stage": "type_fallback",
                    "hit": False,
                    "invoice_type": type_name,
                    "reason": "target_missing_or_disabled",
                }
            )
        else:
            source = _type_rule_source(type_source)
            chain.append(
                {
                    "stage": "type_fallback",
                    "hit": True,
                    "invoice_type": type_name,
                    "category": category.id,
                }
            )
            return _result_for_category(
                category,
                source=source,
                rule_id=category.id,
                source_ref=type_source,
                evidence_user=bool(type_source and type_source.kind != "builtin"),
                chain=chain,
            )
    else:
        chain.append(
            {
                "stage": "type_fallback",
                "hit": False,
                "invoice_type": type_name,
                "reason": "type_not_mapped",
            }
        )

    # 4) Unknown: keep the fallback identity, but flag it for manual review.
    fallback = rule_set.fallback
    chain.append(
        {
            "stage": "fallback",
            "category": fallback.id,
            "reason": "no_rule_matched",
        }
    )
    return ClassificationResult(
        category_id=fallback.id,
        category_name=fallback.name,
        archive_folder=fallback.archive_folder,
        category_src=CATEGORY_SOURCE_UNKNOWN,
        source=SOURCE_UNKNOWN,
        rule_id="",
        keyword="",
        priority=0,
        source_file="",
        source_line=0,
        chain=chain,
    )


def explain(
    fields: Mapping[str, Any] | None,
    rule_set: RuleSet,
) -> dict[str, Any]:
    """Classify and return the JSON-safe result plus the evaluation chain."""
    result = classify(fields, rule_set)
    payload = result.to_dict()
    normalized = normalize_fields(fields)
    amount = normalized.get("amount")
    payload["fields"] = {
        "seller": normalized.get("seller") or "",
        "seller_tin": normalized.get("seller_tin") or "",
        "item": normalized.get("item") or "",
        "type": normalized.get("type") or "",
        "normalized_type": _normalized_type(normalized.get("type")),
        "amount": "" if amount is None else format(amount, "f"),
        "purchaser": normalized.get("purchaser") or "",
    }
    return payload


def result_to_dict(result: ClassificationResult) -> dict[str, Any]:
    """Serialize a :class:`ClassificationResult` for JSON/UI consumption."""
    if isinstance(result, ClassificationResult):
        return result.to_dict()
    raise TypeError("result 必须是 ClassificationResult")


# Keep the documented default visible to callers that introspect the matcher.
DEFAULT_MATCH_FIELD = DEFAULT_MATCH
SUPPORTED_MATCH_FIELDS = MATCH_FIELDS

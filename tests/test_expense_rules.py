"""Unit tests for the InvoiceFlowAI classification-rules core.

Every test passes an explicit ``global_rules_dir``/``builtin_path`` (or an
isolated ``APPDATA``) so the suite never depends on the operator's real
``%APPDATA%/InvoiceFlowAI`` rules.
"""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pytest

import expense_rules
import expense_rules.cli as rules_cli
from document_types import DOCUMENT_TYPES, get_archive_folder
from expense_rules import (
    CATEGORY_SOURCE_BUILTIN,
    CATEGORY_SOURCE_UNKNOWN,
    CATEGORY_SOURCE_USER,
    CUSTOM_TYPES_FILE_NAME,
    SOURCE_BUILTIN_KEYWORD,
    SOURCE_BUILTIN_TYPE,
    SOURCE_DICTIONARY,
    SOURCE_RULE_PACK,
    SOURCE_UNKNOWN,
    SOURCE_USER_RULE,
    CategoryRule,
    ClassificationResult,
    CustomTypeEntry,
    CustomTypes,
    RuleConfigError,
    RuleIssue,
    RuleSet,
    ScopeData,
    add_custom_type,
    amount_range_folder_suffix,
    build_rule_set,
    classify,
    custom_type_name_error,
    ensure_scope_template,
    explain,
    folder_from_keyword,
    folder_from_type_and_amount,
    format_amount_bound,
    is_safe_folder_name,
    load_custom_types,
    load_rule_set,
    read_scope,
    remove_custom_type,
    reset_scope,
    result_to_dict,
    sanitize_rule_keyword,
    save_custom_types,
    save_scope,
)

ROOT = Path(__file__).resolve().parents[1]
BUILTIN_PATH = ROOT / "builtin" / "categories.yaml"

# Declaration order of the shipped L0 categories (also the match order).
EXPECTED_CATEGORIES: dict[str, tuple[str, str]] = {
    "toll_summary": ("通行费汇总单", "通行费汇总单"),
    "qr": ("开票二维码", "开票二维码"),
    "travel_fee": ("差旅服务费", "差旅服务费"),
    "charging": ("充电", "充电"),
    "toll": ("过路费", "过路费"),
    "flight": ("机票", "机票"),
    "train": ("火车票", "火车票"),
    "hotel": ("住宿发票", "住宿发票"),
    "taxi": ("打车", "打车"),
    "meal": ("餐饮", "餐饮"),
    "quota": ("定额发票", "定额发票"),
    "other": ("其他", "其他"),
}

#: Types handled by the application's safety isolation step, not by rules.
ISOLATED_TYPES = {"非目标公司发票", "个人非报销发票"}
UNMAPPED_TYPES = ISOLATED_TYPES | {"其他"}

MINI_BUILTIN_TEXT = """\
version: 1
fallback: other
type_categories:
  打车: taxi
  餐饮: meal
categories:
  - id: taxi
    name: 打车
    archive_folder: 打车
    invoice_types: [其他]
    keywords: [滴滴]
  - id: meal
    name: 餐饮
    archive_folder: 餐饮
    invoice_types: [其他]
    keywords: [餐饮]
  - id: train
    name: 火车票
    archive_folder: 火车票
    invoice_types: [其他]
    keywords: [中国铁路]
  - id: other
    name: 其他
    archive_folder: 其他
    invoice_types: [其他]
    keywords: []
"""

ORDER_BUILTIN_TEXT = """\
version: 1
fallback: other
categories:
  - id: alpha
    name: 甲
    archive_folder: 甲
    invoice_types: [其他]
    keywords: [共享词]
  - id: beta
    name: 乙
    archive_folder: 乙
    invoice_types: [其他]
    keywords: [共享词]
  - id: other
    name: 其他
    archive_folder: 其他
    invoice_types: [其他]
    keywords: []
"""

#: Legacy file: both rules use ``priority`` values that contradict the list
#: order. The loader must keep parsing the field (compatibility) and warn, but
#: match in declaration order (``first`` wins).
LEGACY_PRIORITY_BUILTIN_TEXT = """\
version: 1
fallback: other
categories:
  - id: first
    name: 先声明
    archive_folder: 先声明
    priority: 10
    invoice_types: [其他]
    keywords: [共享词]
  - id: second
    name: 后声明
    archive_folder: 后声明
    priority: 900
    invoice_types: [其他]
    keywords: [共享词]
  - id: other
    name: 其他
    archive_folder: 其他
    priority: 0
    invoice_types: [其他]
    keywords: []
"""

AUTO_BUILTIN_TEXT = """\
version: 1
fallback: other
categories:
  - id: meal_auto
    auto_folder: true
    invoice_types: [其他]
    keywords: [餐饮]
  - id: other
    name: 其他
    archive_folder: 其他
    invoice_types: [其他]
    keywords: []
"""

BOUND_BUILTIN_TEXT = """\
version: 1
fallback: other
categories:
  - id: big
    name: 大额
    archive_folder: 大额
    invoice_types: [其他]
    keywords: [大额]
    amount_range: [100, 200]
  - id: other
    name: 其他
    archive_folder: 其他
    invoice_types: [其他]
    keywords: []
"""

MATCH_BUILTIN_TEXT = """\
version: 1
fallback: other
categories:
  - id: seller_only
    name: 仅卖方
    archive_folder: 仅卖方
    match: seller
    invoice_types: [其他]
    keywords: [卖方词]
  - id: item_only
    name: 仅明细
    archive_folder: 仅明细
    match: item
    invoice_types: [其他]
    keywords: [明细词]
  - id: both
    name: 两者
    archive_folder: 两者
    match: seller_item
    invoice_types: [其他]
    keywords: [任意词]
  - id: other
    name: 其他
    archive_folder: 其他
    invoice_types: [其他]
    keywords: []
"""

NORMALIZE_BUILTIN_TEXT = """\
version: 1
fallback: other
categories:
  - id: etc_rule
    name: ETC
    archive_folder: ETC
    invoice_types: [其他]
    keywords: ["ＥＴＣ", "Folio"]
  - id: other
    name: 其他
    archive_folder: 其他
    invoice_types: [其他]
    keywords: []
"""

INVOICE_TYPES_BUILTIN_TEXT = """\
version: 1
fallback: other
type_categories:
  餐饮: meal
categories:
  - id: meal_special
    name: 餐饮专词
    archive_folder: 餐饮专词
    invoice_types: [餐饮]
    keywords: [专词]
  - id: any_special
    name: 任意专词
    archive_folder: 任意专词
    invoice_types: []
    keywords: [专词]
  - id: meal
    name: 餐饮
    archive_folder: 餐饮
    invoice_types: [其他]
    keywords: [餐饮]
  - id: other
    name: 其他
    archive_folder: 其他
    invoice_types: [其他]
    keywords: []
"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_lines(path: Path, lines: list[str]) -> Path:
    return _write_text(path, "\n".join(lines) + "\n")


def _write_builtin(tmp_path: Path, text: str) -> Path:
    return _write_text(tmp_path / "builtin" / "categories.yaml", text)


def _load(
    tmp_path: Path,
    *,
    builtin: Path = BUILTIN_PATH,
    library: Path | None = None,
    global_dir: Path | None = None,
) -> RuleSet:
    return load_rule_set(
        library,
        global_rules_dir=str(global_dir if global_dir is not None else tmp_path / "global"),
        builtin_path=str(builtin),
    )


def _global_rules_dir(tmp_path: Path) -> Path:
    return tmp_path / "global"


def _write_global(tmp_path: Path, lines: list[str], *, name: str = "categories.yaml") -> Path:
    return _write_lines(_global_rules_dir(tmp_path) / name, lines)


@pytest.fixture()
def mini_builtin(tmp_path: Path) -> Path:
    return _write_builtin(tmp_path, MINI_BUILTIN_TEXT)


def _load_config_error(tmp_path: Path, lines: list[str], *, name: str = "categories.yaml") -> tuple[RuleConfigError, Path]:
    path = _write_global(tmp_path, lines, name=name)
    try:
        _load(tmp_path)
    except RuleConfigError as exc:
        return exc, path
    raise AssertionError("expected RuleConfigError, config loaded successfully")


def _issue_lines(exc: RuleConfigError) -> set[int]:
    return {issue.line for issue in exc.issues}


# --------------------------------------------------------------------------- #
# Public API surface
# --------------------------------------------------------------------------- #


class TestPublicApi:
    def test_stable_api_is_exported(self) -> None:
        for name in (
            "load_rule_set",
            "classify",
            "explain",
            "read_scope",
            "save_scope",
            "reset_scope",
            "ensure_scope_template",
            "is_safe_folder_name",
            "RuleConfigError",
            "RuleIssue",
            "RuleSet",
            "ClassificationResult",
            "CategoryRule",
            "ScopeData",
            "build_rule_set",
            "result_to_dict",
            "sanitize_rule_keyword",
            "format_amount_bound",
            "amount_range_folder_suffix",
            "folder_from_keyword",
        ):
            assert hasattr(expense_rules, name), name

    def test_load_rule_set_signature_accepts_overrides(self, tmp_path: Path) -> None:
        rule_set = expense_rules.load_rule_set(
            None,
            global_rules_dir=str(_global_rules_dir(tmp_path)),
            builtin_path=str(BUILTIN_PATH),
            overrides={"global": {"categories": []}},
        )
        assert rule_set.overrides_applied == ("global",)


# --------------------------------------------------------------------------- #
# L0 built-in defaults
# --------------------------------------------------------------------------- #


class TestBuiltinDefaults:
    def test_categories_and_archive_folders(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        assert set(rule_set.category_map) == set(EXPECTED_CATEGORIES)
        for category_id, (name, folder) in EXPECTED_CATEGORIES.items():
            rule = rule_set.category_map[category_id]
            assert isinstance(rule, CategoryRule)
            assert rule.name == name
            assert rule.archive_folder == folder
            assert is_safe_folder_name(rule.archive_folder)
            assert rule.scope == CATEGORY_SOURCE_BUILTIN
        assert [rule.id for rule in rule_set.categories] == list(EXPECTED_CATEGORIES)
        assert [rule.id for rule in rule_set.ordered_categories] == list(EXPECTED_CATEGORIES)
        assert rule_set.fallback_id == "other"

    def test_builtin_does_not_use_deprecated_priority(self, tmp_path: Path) -> None:
        text = BUILTIN_PATH.read_text(encoding="utf-8")
        assert "priority:" not in text
        rule_set = _load(tmp_path)
        assert rule_set.warnings == ()
        assert all(rule.priority == 0 for rule in rule_set.categories)
        assert all(rule.auto_folder is False for rule in rule_set.categories)
        assert all(rule.target_type == "" for rule in rule_set.categories)

    def test_document_types_are_builtin_types_without_custom_ones(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        assert rule_set.document_types == tuple(DOCUMENT_TYPES)
        assert rule_set.custom_types == ()
        assert rule_set.custom_types_path.endswith(CUSTOM_TYPES_FILE_NAME)

    def test_type_categories_cover_the_document_type_registry(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        assert set(rule_set.type_categories) == set(DOCUMENT_TYPES) - UNMAPPED_TYPES
        for doc_type in set(DOCUMENT_TYPES) - UNMAPPED_TYPES:
            category = rule_set.category_map[rule_set.type_categories[doc_type]]
            assert category.archive_folder == get_archive_folder(doc_type)

    def test_every_recognized_type_keeps_its_current_archive_folder(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        for doc_type in set(DOCUMENT_TYPES) - UNMAPPED_TYPES:
            result = classify({"type": doc_type}, rule_set)
            assert result.category_id == rule_set.type_categories[doc_type], doc_type
            assert result.archive_folder == get_archive_folder(doc_type), doc_type
            assert result.source == SOURCE_BUILTIN_TYPE
            assert result.category_src == CATEGORY_SOURCE_BUILTIN

    def test_builtin_keyword_rules_are_scoped_to_unrecognized_types(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        for rule in rule_set.categories:
            if rule.keywords:
                assert rule.invoice_types == ("其他",), rule.id
        assert rule_set.category_map["other"].keywords == ()

    def test_keyword_rule_fires_only_when_type_is_inconclusive(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        result = classify({"type": "其他", "seller": "滴滴出行科技有限公司"}, rule_set)
        assert result.category_id == "taxi"
        assert result.source == SOURCE_BUILTIN_KEYWORD
        assert result.keyword == "滴滴"
        assert result.rule_id == "taxi"
        assert result.archive_folder == "打车"
        assert result.category_src == CATEGORY_SOURCE_BUILTIN

        recognized = classify({"type": "餐饮", "seller": "滴滴出行"}, rule_set)
        assert recognized.category_id == "meal"
        assert recognized.source == SOURCE_BUILTIN_TYPE

    def test_lodging_subtypes_map_to_hotel_folder(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        for doc_type in ("住宿水单", "住宿确认单", "住宿发票"):
            result = classify({"type": doc_type}, rule_set)
            assert result.category_id == "hotel"
            assert result.archive_folder == "住宿发票"

    def test_isolated_and_other_types_are_not_type_mapped(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        for doc_type in UNMAPPED_TYPES:
            assert doc_type not in rule_set.type_categories
            result = classify({"type": doc_type}, rule_set)
            assert result.category_id == "other"
            assert result.source == SOURCE_UNKNOWN
            assert result.category_src == CATEGORY_SOURCE_UNKNOWN

    def test_unknown_falls_back_with_unknown_source(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        result = classify({"type": "其他", "seller": "某某办公用品公司", "item": "打印纸"}, rule_set)
        assert isinstance(result, ClassificationResult)
        assert result.category_id == "other"
        assert result.category_name == "其他"
        assert result.archive_folder == "其他"
        assert result.category_src == CATEGORY_SOURCE_UNKNOWN
        assert result.source == SOURCE_UNKNOWN
        assert result.rule_id == ""
        assert result.keyword == ""
        assert result.source_file == ""
        assert result.source_line == 0


# --------------------------------------------------------------------------- #
# Loading / paths
# --------------------------------------------------------------------------- #


class TestLoading:
    def test_default_global_rules_dir_uses_settings_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        appdata = tmp_path / "appdata"
        monkeypatch.setenv("APPDATA", str(appdata))
        rule_set = load_rule_set(builtin_path=str(BUILTIN_PATH))
        expected = appdata / "InvoiceFlowAI" / "rules"
        assert Path(rule_set.global_rules_dir) == expected
        assert rule_set.library_dir is None
        assert rule_set.library_rules_dir is None

    def test_library_rules_dir_is_library_subfolder(self, tmp_path: Path) -> None:
        library = tmp_path / "发票库"
        library.mkdir()
        rule_set = load_rule_set(
            library,
            global_rules_dir=str(_global_rules_dir(tmp_path)),
            builtin_path=str(BUILTIN_PATH),
        )
        assert rule_set.library_dir == str(library.resolve())
        assert Path(rule_set.library_rules_dir) == (library / "rules").resolve()

    def test_missing_global_and_library_files_are_optional(self, tmp_path: Path) -> None:
        library = tmp_path / "library"
        library.mkdir()
        rule_set = _load(tmp_path, library=library)
        assert len(rule_set.categories) == len(EXPECTED_CATEGORIES)
        assert rule_set.terms == {}
        assert rule_set.warnings == ()

    def test_missing_builtin_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuleConfigError) as excinfo:
            load_rule_set(
                global_rules_dir=str(_global_rules_dir(tmp_path)),
                builtin_path=str(tmp_path / "missing.yaml"),
            )
        assert any("找不到内置分类规则文件" in issue.message for issue in excinfo.value.issues)

    def test_path_objects_are_accepted(self, tmp_path: Path) -> None:
        rule_set = load_rule_set(
            tmp_path / "library",
            global_rules_dir=_global_rules_dir(tmp_path),
            builtin_path=BUILTIN_PATH,
        )
        assert rule_set.builtin_path == str(BUILTIN_PATH)

    def test_unknown_scope_in_overrides_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            load_rule_set(
                global_rules_dir=str(_global_rules_dir(tmp_path)),
                builtin_path=str(BUILTIN_PATH),
                overrides={"workspace": {}},
            )

    def test_library_override_requires_library_dir(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            load_rule_set(
                global_rules_dir=str(_global_rules_dir(tmp_path)),
                builtin_path=str(BUILTIN_PATH),
                overrides={"library": {}},
            )


# --------------------------------------------------------------------------- #
# Field-level merge
# --------------------------------------------------------------------------- #


class TestFieldMerge:
    def test_later_layer_replaces_only_present_fields(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        path = _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    name: 自定义打车",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        rule = rule_set.category_map["taxi"]
        assert rule.name == "自定义打车"
        assert rule.archive_folder == "打车"
        assert rule.priority == 0
        assert rule.keywords == ("滴滴",)
        assert rule.scope == CATEGORY_SOURCE_USER
        assert rule.field_sources["name"].file == str(path)
        assert rule.field_sources["name"].line == 4
        assert rule.field_sources["keywords"].file == str(mini_builtin)

    def test_empty_keywords_list_replaces(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    keywords: []",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.category_map["taxi"].keywords == ()
        result = classify({"type": "其他", "seller": "滴滴出行"}, rule_set)
        assert result.source == SOURCE_UNKNOWN

    def test_invoice_types_empty_list_clears_type_restriction(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    invoice_types: []",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.category_map["taxi"].invoice_types == ()
        result = classify({"type": "打车", "seller": "滴滴出行"}, rule_set)
        assert result.category_id == "taxi"
        assert result.source == SOURCE_USER_RULE

    def test_library_layer_overrides_global_layer(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        library = tmp_path / "library"
        library.mkdir()
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    keywords: [全局词]",
            ],
        )
        _write_lines(
            library / "rules" / "categories.yaml",
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    keywords: [库内词]",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin, library=library)
        assert rule_set.category_map["taxi"].keywords == ("库内词",)
        assert classify({"type": "其他", "seller": "库内词"}, rule_set).category_id == "taxi"
        assert classify({"type": "其他", "seller": "全局词"}, rule_set).source == SOURCE_UNKNOWN

    def test_rule_pack_layers_are_sorted_and_later_wins(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        packs = _global_rules_dir(tmp_path) / "rules.d"
        _write_lines(
            packs / "10-first.yaml",
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    keywords: [包一词]",
            ],
        )
        _write_lines(
            packs / "20-second.yaml",
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    keywords: [包二词]",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.category_map["taxi"].keywords == ("包二词",)
        result = classify({"type": "其他", "seller": "包二词"}, rule_set)
        assert result.category_id == "taxi"
        assert result.source == SOURCE_RULE_PACK

    def test_library_pack_overrides_global_pack(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        library = tmp_path / "library"
        library.mkdir()
        _write_lines(
            _global_rules_dir(tmp_path) / "rules.d" / "10-global.yaml",
            ["version: 1", "categories:", "  - id: taxi", "    keywords: [全局包词]"],
        )
        _write_lines(
            library / "rules" / "rules.d" / "10-library.yaml",
            ["version: 1", "categories:", "  - id: taxi", "    keywords: [库包词]"],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin, library=library)
        assert rule_set.category_map["taxi"].keywords == ("库包词",)

    def test_yml_rule_pack_is_loaded(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_lines(
            _global_rules_dir(tmp_path) / "rules.d" / "10-pack.yml",
            ["version: 1", "categories:", "  - id: taxi", "    keywords: [yml词]"],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.category_map["taxi"].keywords == ("yml词",)

    def test_fallback_and_type_categories_merge_per_key(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "fallback: meal",
                "type_categories:",
                "  打车: meal",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.fallback_id == "meal"
        assert rule_set.type_categories["打车"] == "meal"
        assert rule_set.type_categories["餐饮"] == "meal"
        result = classify({"type": "打车"}, rule_set)
        assert result.category_id == "meal"
        assert result.source == SOURCE_USER_RULE
        # The type mapping override is user configuration.
        assert result.category_src == CATEGORY_SOURCE_USER

    def test_field_sources_track_each_layer(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        library = tmp_path / "library"
        library.mkdir()
        global_path = _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    name: 全局名"],
        )
        library_path = _write_lines(
            library / "rules" / "categories.yaml",
            ["version: 1", "categories:", "  - id: taxi", "    keywords: [库词]"],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin, library=library)
        rule = rule_set.category_map["taxi"]
        assert rule.field_sources["name"].file == str(global_path)
        assert rule.field_sources["keywords"].file == str(library_path)
        assert rule.field_sources["archive_folder"].file == str(mini_builtin)
        assert rule.source_file == str(library_path)

    def test_disabled_builtin_category_stops_keyword_and_type_matches(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    enabled: false",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.category_map["taxi"].enabled is False
        keyword_result = classify({"type": "其他", "seller": "滴滴出行"}, rule_set)
        assert keyword_result.source == SOURCE_UNKNOWN
        type_result = classify({"type": "打车"}, rule_set)
        assert type_result.source == SOURCE_UNKNOWN
        assert {
            "stage": "type_fallback",
            "hit": False,
            "invoice_type": "打车",
            "reason": "target_missing_or_disabled",
        } in type_result.chain
        assert any("已禁用" in issue.message for issue in rule_set.warnings)


# --------------------------------------------------------------------------- #
# Match order
# --------------------------------------------------------------------------- #


class TestMatchOrder:
    def test_legacy_priority_is_ignored_and_warned(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, LEGACY_PRIORITY_BUILTIN_TEXT)
        rule_set = _load(tmp_path, builtin=builtin)
        # Declaration order wins even though the second rule has priority 900.
        result = classify({"type": "其他", "seller": "共享词"}, rule_set)
        assert result.category_id == "first"
        # The field is still parsed for API compatibility...
        assert rule_set.category_map["first"].priority == 10
        assert rule_set.category_map["second"].priority == 900
        # ... but every occurrence produces a deprecation warning.
        assert len(rule_set.warnings) == 3
        assert all(
            "priority 已不再使用，规则按列表顺序匹配" in issue.message
            for issue in rule_set.warnings
        )
        assert all(issue.severity == "warning" for issue in rule_set.warnings)
        assert [rule.id for rule in rule_set.ordered_categories] == [
            "first",
            "second",
            "other",
        ]

    def test_declaration_order_within_layer(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, ORDER_BUILTIN_TEXT)
        rule_set = _load(tmp_path, builtin=builtin)
        result = classify({"type": "其他", "item": "共享词"}, rule_set)
        assert result.category_id == "alpha"

    def test_later_layer_first(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: gamma",
                "    name: 丙",
                "    archive_folder: 丙",
                "    invoice_types: [其他]",
                "    keywords: [共享词]",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        result = classify({"type": "其他", "seller": "共享词"}, rule_set)
        assert result.category_id == "gamma"
        assert [rule.id for rule in rule_set.ordered_categories][0] == "gamma"

    def test_disabled_categories_are_not_evaluated(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: meal", "    enabled: false"],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        result = classify({"type": "其他", "item": "餐饮"}, rule_set)
        assert result.source == SOURCE_UNKNOWN
        scan = [item for item in result.chain if item.get("stage") == "rule_scan"]
        assert scan and scan[0]["disabled_skipped"] == 1


# --------------------------------------------------------------------------- #
# Matching conditions
# --------------------------------------------------------------------------- #


class TestMatchingConditions:
    def test_match_seller_item_and_seller_item_scope(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, MATCH_BUILTIN_TEXT)
        rule_set = _load(tmp_path, builtin=builtin)

        seller_result = classify({"type": "其他", "seller": "卖方词"}, rule_set)
        assert seller_result.category_id == "seller_only"

        item_result = classify({"type": "其他", "item": "明细词"}, rule_set)
        assert item_result.category_id == "item_only"

        both_result = classify({"type": "其他", "seller": "任意词"}, rule_set)
        assert both_result.category_id == "both"

        # A seller-only rule must not inspect the item text.
        skipped = classify({"type": "其他", "item": "卖方词"}, rule_set)
        assert skipped.source == SOURCE_UNKNOWN

    def test_amount_range_is_inclusive(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, BOUND_BUILTIN_TEXT)
        rule_set = _load(tmp_path, builtin=builtin)
        assert classify({"type": "其他", "seller": "大额", "amount": "100"}, rule_set).category_id == "big"
        assert classify({"type": "其他", "seller": "大额", "amount": "200"}, rule_set).category_id == "big"
        assert classify({"type": "其他", "seller": "大额", "amount": "150.50"}, rule_set).category_id == "big"
        assert classify({"type": "其他", "seller": "大额", "amount": "99.99"}, rule_set).source == SOURCE_UNKNOWN
        assert classify({"type": "其他", "seller": "大额", "amount": "200.01"}, rule_set).source == SOURCE_UNKNOWN
        assert classify({"type": "其他", "seller": "大额"}, rule_set).source == SOURCE_UNKNOWN

    def test_amount_range_supports_signed_values(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: refund",
                "    name: 退款",
                "    archive_folder: 退款",
                "    invoice_types: [其他]",
                "    keywords: [退款]",
                "    amount_range: [-200, -100]",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert classify({"type": "其他", "seller": "退款", "amount": "-150"}, rule_set).category_id == "refund"
        # Parenthesised positives are the legacy negative convention.
        assert classify({"type": "其他", "seller": "退款", "amount": "(150)"}, rule_set).category_id == "refund"
        assert classify({"type": "其他", "seller": "退款", "amount": "-50"}, rule_set).source == SOURCE_UNKNOWN
        assert rule_set.category_map["refund"].amount_range is not None

    def test_exclude_keywords_skip_the_rule(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    exclude_keywords: [取消]",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert classify({"type": "其他", "seller": "取消滴滴订单"}, rule_set).source == SOURCE_UNKNOWN
        assert classify({"type": "其他", "seller": "滴滴出行"}, rule_set).category_id == "taxi"

    def test_nfkc_casefold_and_whitespace_normalization(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, NORMALIZE_BUILTIN_TEXT)
        rule_set = _load(tmp_path, builtin=builtin)
        assert classify({"type": "其他", "seller": "e t c 科技有限公司"}, rule_set).category_id == "etc_rule"
        assert classify({"type": "其他", "item": "F O L I O 账单"}, rule_set).category_id == "etc_rule"

    def test_invoice_types_gate_rules(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, INVOICE_TYPES_BUILTIN_TEXT)
        rule_set = _load(tmp_path, builtin=builtin)
        # Empty invoice_types = no type restriction.
        assert classify({"type": "其他", "seller": "专词"}, rule_set).category_id == "any_special"
        # A rule restricted to 餐饮 applies when the recognized type is 餐饮.
        meal_result = classify({"type": "餐饮", "seller": "专词"}, rule_set)
        assert meal_result.category_id == "meal_special"
        assert meal_result.source == SOURCE_BUILTIN_KEYWORD
        # ... and not when the type is something else.
        assert classify({"type": "打车", "seller": "专词"}, rule_set).category_id == "any_special"

    def test_amount_range_empty_list_clears_inherited_range(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, BOUND_BUILTIN_TEXT)
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: big",
                "    amount_range: []",
            ],
        )
        rule_set = _load(tmp_path, builtin=builtin)
        assert rule_set.category_map["big"].amount_range is None
        assert classify({"type": "其他", "seller": "大额"}, rule_set).category_id == "big"

    def test_fields_are_normalized_from_payload_aliases(self, tmp_path: Path, mini_builtin: Path) -> None:
        rule_set = _load(tmp_path, builtin=mini_builtin)
        result = classify(
            {"Type": "其他", "Seller": "滴滴出行", "Item": "服务费", "Amount": "¥ 12.00"},
            rule_set,
        )
        assert result.category_id == "taxi"
        chain_input = result.chain[0]
        assert chain_input["stage"] == "input"
        assert chain_input["amount"] == "12.00"

    def test_type_aliases_are_normalized_to_registered_types(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        rule_set = _load(tmp_path, builtin=mini_builtin)
        result = classify({"type": "酒店住宿发票"}, rule_set)
        # normalize_document_type maps it to 住宿发票, which the mini builtin
        # does not map, so this documents the normalized type in the chain.
        assert result.chain[0]["normalized_type"] == "住宿发票"


# --------------------------------------------------------------------------- #
# auto_folder naming helpers
# --------------------------------------------------------------------------- #


class TestRuleFolderHelpers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("餐饮", "餐饮"),
            ("  餐饮  ", "餐饮"),
            ("特/殊:词*?", "特-殊-词--"),
            ("a\tb\n c", "a b c"),
            ("餐饮. ", "餐饮"),
            ("abc...", "abc"),
            ("ＡＢＣ", "ABC"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_sanitize_rule_keyword(self, value: object, expected: str) -> None:
        assert sanitize_rule_keyword(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, ""),
            (0, "0"),
            (100, "100"),
            (100.0, "100"),
            (100.50, "100.5"),
            ("100.500", "100.5"),
            (Decimal("100.00"), "100"),
            (Decimal("-0.0"), "0"),
            (-100.25, "-100.25"),
        ],
    )
    def test_format_amount_bound(self, value: object, expected: str) -> None:
        assert format_amount_bound(value) == expected

    @pytest.mark.parametrize(
        ("amount_range", "expected"),
        [
            (None, ""),
            ((), ""),
            ([None, None], ""),
            ([100, 100], "100"),
            ([100, None], "100以上"),
            ([None, 200], "200以下"),
            ([100, 200], "100-200"),
            ([-200, -100], "-200至-100"),
            ([-100, 100], "-100至100"),
            ([100.5, 200.25], "100.5-200.25"),
            ([0, 0], "0"),
        ],
    )
    def test_amount_range_folder_suffix(self, amount_range: object, expected: str) -> None:
        assert amount_range_folder_suffix(amount_range) == expected

    def test_amount_range_folder_suffix_rejects_invalid_values(self) -> None:
        with pytest.raises(ValueError):
            amount_range_folder_suffix("100-200")
        with pytest.raises(ValueError):
            amount_range_folder_suffix([1, 2, 3])
        with pytest.raises(ValueError):
            amount_range_folder_suffix([True, 1])

    @pytest.mark.parametrize(
        ("keyword", "amount_range", "expected"),
        [
            ("餐饮", None, "餐饮"),
            (" 餐饮 ", [100, None], "餐饮100以上"),
            ("餐饮", [None, 200], "餐饮200以下"),
            ("餐饮", [100, 200], "餐饮100-200"),
            ("餐饮", [100, 100], "餐饮100"),
            ("餐饮", [-200, -100], "餐饮-200至-100"),
            ("特/殊:词", None, "特-殊-词"),
        ],
    )
    def test_folder_from_keyword(
        self, keyword: str, amount_range: object, expected: str
    ) -> None:
        assert folder_from_keyword(keyword, amount_range) == expected

    def test_folder_from_keyword_truncates_to_64(self) -> None:
        folder = folder_from_keyword("长" * 80)
        assert len(folder) == 64
        assert folder == "长" * 64

    def test_folder_from_keyword_keeps_suffix_when_truncating(self) -> None:
        folder = folder_from_keyword("长" * 80, [100, 200])
        assert len(folder) <= 64
        assert folder.endswith("100-200")
        assert folder.startswith("长")

    def test_folder_from_keyword_requires_usable_keyword(self) -> None:
        for keyword in ("", "   ", None, " . "):
            with pytest.raises(ValueError):
                folder_from_keyword(keyword)


def _auto_builtin_text(
    *,
    keyword: str = "餐饮",
    amount_range_line: str = "",
    extra_entry_lines: list[str] | None = None,
) -> str:
    lines = [
        "version: 1",
        "fallback: other",
        "categories:",
        "  - id: auto_rule",
        "    auto_folder: true",
        "    invoice_types: [其他]",
        f"    keywords: [{json.dumps(keyword, ensure_ascii=False)}]",
    ]
    if amount_range_line:
        lines.append(f"    amount_range: {amount_range_line}")
    if extra_entry_lines:
        lines.extend(extra_entry_lines)
    lines.extend(
        [
            "  - id: other",
            "    name: 其他",
            "    archive_folder: 其他",
            "    invoice_types: [其他]",
            "    keywords: []",
        ]
    )
    return "\n".join(lines) + "\n"


class TestAutoFolderRules:
    def test_auto_folder_derives_name_and_folder(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, _auto_builtin_text())
        rule_set = _load(tmp_path, builtin=builtin)
        rule = rule_set.category_map["auto_rule"]
        assert rule.auto_folder is True
        assert rule.name == "餐饮"
        assert rule.archive_folder == "餐饮"
        assert rule.field_sources["archive_folder"].kind == "auto_folder"
        result = classify({"type": "其他", "seller": "餐饮"}, rule_set)
        assert result.category_id == "auto_rule"
        assert result.category_name == "餐饮"
        assert result.archive_folder == "餐饮"

    @pytest.mark.parametrize(
        ("amount_range_line", "expected_folder"),
        [
            ("", "餐饮"),
            ("[100, 100]", "餐饮100"),
            ("[100, null]", "餐饮100以上"),
            ("[null, 200]", "餐饮200以下"),
            ("[100, 200]", "餐饮100-200"),
            ("[-200, -100]", "餐饮-200至-100"),
            ("[100.5, 200.25]", "餐饮100.5-200.25"),
        ],
    )
    def test_auto_folder_uses_amount_range(
        self, tmp_path: Path, amount_range_line: str, expected_folder: str
    ) -> None:
        builtin = _write_builtin(
            tmp_path, _auto_builtin_text(amount_range_line=amount_range_line)
        )
        rule_set = _load(tmp_path, builtin=builtin)
        rule = rule_set.category_map["auto_rule"]
        assert rule.archive_folder == expected_folder
        assert rule.name == expected_folder
        assert is_safe_folder_name(rule.archive_folder)

    def test_auto_folder_sanitizes_invalid_characters(self, tmp_path: Path) -> None:
        builtin = _write_builtin(
            tmp_path, _auto_builtin_text(keyword="特/殊:词* 名")
        )
        rule_set = _load(tmp_path, builtin=builtin)
        folder = rule_set.category_map["auto_rule"].archive_folder
        assert folder == "特-殊-词- 名"
        for forbidden in '/\\:*?"<>|':
            assert forbidden not in folder

    def test_auto_folder_requires_keywords(self, tmp_path: Path) -> None:
        builtin = _write_builtin(
            tmp_path,
            "\n".join(
                [
                    "version: 1",
                    "fallback: other",
                    "categories:",
                    "  - id: auto_rule",
                    "    auto_folder: true",
                    "  - id: other",
                    "    name: 其他",
                    "    archive_folder: 其他",
                    "    keywords: []",
                ]
            )
            + "\n",
        )
        with pytest.raises(RuleConfigError) as excinfo:
            _load(tmp_path, builtin=builtin)
        issue = next(
            item for item in excinfo.value.issues if "必须填写关键词" in item.message
        )
        assert issue.line == 4
        assert issue.severity == "error"

    def test_auto_folder_rejects_unusable_keyword(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, _auto_builtin_text(keyword=" . "))
        with pytest.raises(RuleConfigError) as excinfo:
            _load(tmp_path, builtin=builtin)
        assert any(
            "无法生成文件夹名" in issue.message for issue in excinfo.value.issues
        )

    def test_auto_folder_rejects_reserved_folder_name(self, tmp_path: Path) -> None:
        builtin = _write_builtin(tmp_path, _auto_builtin_text(keyword="rules"))
        with pytest.raises(RuleConfigError) as excinfo:
            _load(tmp_path, builtin=builtin)
        assert any(
            "自动文件夹名称不安全" in issue.message for issue in excinfo.value.issues
        )

    def test_auto_folder_truncates_long_keyword(self, tmp_path: Path) -> None:
        builtin = _write_builtin(
            tmp_path, _auto_builtin_text(keyword="长" * 80)
        )
        rule_set = _load(tmp_path, builtin=builtin)
        folder = rule_set.category_map["auto_rule"].archive_folder
        assert len(folder) == 64

    def test_auto_folder_ignores_explicit_name_and_folder(self, tmp_path: Path) -> None:
        builtin = _write_builtin(
            tmp_path,
            _auto_builtin_text(
                extra_entry_lines=["    name: 显式名", "    archive_folder: 显式文件夹"]
            ),
        )
        rule_set = _load(tmp_path, builtin=builtin)
        rule = rule_set.category_map["auto_rule"]
        assert rule.name == "餐饮"
        assert rule.archive_folder == "餐饮"

    def test_auto_flag_can_be_added_to_existing_rule(self, tmp_path: Path) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: meal", "    auto_folder: true"],
        )
        rule_set = _load(tmp_path)
        rule = rule_set.category_map["meal"]
        assert rule.auto_folder is True
        assert rule.archive_folder == "餐饮"
        assert rule.name == "餐饮"
        assert rule.keywords  # the builtin keyword list was inherited

    def test_auto_folder_matching_respects_amount_range(self, tmp_path: Path) -> None:
        builtin = _write_builtin(
            tmp_path, _auto_builtin_text(amount_range_line="[100, null]")
        )
        rule_set = _load(tmp_path, builtin=builtin)
        matched = classify(
            {"type": "其他", "seller": "餐饮", "amount": "150"}, rule_set
        )
        assert matched.category_id == "auto_rule"
        assert matched.archive_folder == "餐饮100以上"
        assert matched.keyword == "餐饮"
        missing_amount = classify({"type": "其他", "seller": "餐饮"}, rule_set)
        assert missing_amount.source == SOURCE_UNKNOWN
        below_range = classify(
            {"type": "其他", "seller": "餐饮", "amount": "50"}, rule_set
        )
        assert below_range.source == SOURCE_UNKNOWN


# --------------------------------------------------------------------------- #
# Global custom invoice types (custom_types.yaml)
# --------------------------------------------------------------------------- #


def _write_custom_types(tmp_path: Path, names: list[str]) -> Path:
    lines = ["version: 1", "types:"]
    lines.extend(f"  - {name}" for name in names)
    return _write_global(tmp_path, lines, name=CUSTOM_TYPES_FILE_NAME)


class TestCustomTypes:
    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        directory = tmp_path / "rules"
        types = load_custom_types(directory)
        assert isinstance(types, CustomTypes)
        assert types.names == ()
        assert types.issues == ()
        assert types.entries == ()
        assert types.exists is False
        assert Path(types.path) == (directory / CUSTOM_TYPES_FILE_NAME).resolve()
        assert types.to_dict()["names"] == []

    def test_load_valid_file_keeps_order_and_lines(self, tmp_path: Path) -> None:
        path = _write_custom_types(tmp_path, ["酒店", "会议"])
        types = load_custom_types(_global_rules_dir(tmp_path))
        assert types.names == ("酒店", "会议")
        assert types.issues == ()
        assert types.exists is True
        assert Path(types.path) == path
        assert [entry.name for entry in types.entries] == ["酒店", "会议"]
        assert isinstance(types.entries[0], CustomTypeEntry)
        assert types.entries[0].line == 3
        assert types.entries[1].line == 4
        assert types.to_dict()["names"] == ["酒店", "会议"]

    def test_default_global_path_uses_settings_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        appdata = tmp_path / "appdata"
        monkeypatch.setenv("APPDATA", str(appdata))
        types = load_custom_types()
        expected = appdata / "InvoiceFlowAI" / "rules" / CUSTOM_TYPES_FILE_NAME
        assert Path(types.path) == expected
        assert types.exists is False

    def test_invalid_yaml_reports_line(self, tmp_path: Path) -> None:
        path = _write_text(
            _global_rules_dir(tmp_path) / CUSTOM_TYPES_FILE_NAME, "types: [\n"
        )
        types = load_custom_types(_global_rules_dir(tmp_path))
        assert types.names == ()
        assert types.errors
        assert any("YAML 解析失败" in issue.message for issue in types.issues)
        assert all(issue.file == str(path) for issue in types.issues)
        assert any(issue.line >= 1 for issue in types.issues)

    def test_top_level_must_be_mapping(self, tmp_path: Path) -> None:
        _write_text(_global_rules_dir(tmp_path) / CUSTOM_TYPES_FILE_NAME, "- 酒店\n")
        types = load_custom_types(_global_rules_dir(tmp_path))
        assert any("顶层必须是映射" in issue.message for issue in types.issues)

    def test_duplicate_mapping_key_rejected(self, tmp_path: Path) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "types: [酒店]", "types: [会议]"],
            name=CUSTOM_TYPES_FILE_NAME,
        )
        types = load_custom_types(_global_rules_dir(tmp_path))
        assert any(
            "重复的映射键" in issue.message and issue.line == 3
            for issue in types.issues
        )

    def test_version_must_be_one(self, tmp_path: Path) -> None:
        _write_global(
            tmp_path, ["version: 2", "types: []"], name=CUSTOM_TYPES_FILE_NAME
        )
        types = load_custom_types(_global_rules_dir(tmp_path))
        assert any("不支持的票种文件版本" in issue.message for issue in types.issues)
        assert any(issue.line == 1 for issue in types.issues)

    def test_duplicate_names_in_file_rejected(self, tmp_path: Path) -> None:
        path = _write_global(
            tmp_path,
            ["version: 1", "types:", "  - 酒店", "  - 酒店"],
            name=CUSTOM_TYPES_FILE_NAME,
        )
        types = load_custom_types(_global_rules_dir(tmp_path))
        assert types.names == ("酒店",)
        issue = next(item for item in types.errors if "重复" in item.message)
        assert issue.file == str(path)
        assert issue.line == 4

    def test_invalid_names_are_reported_with_lines(self, tmp_path: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "types:",
                '  - ""',
                "  - 坏/名",
                "  - rules",
                "  - 住宿发票",
                f"  - {'长' * 33}",
            ],
            name=CUSTOM_TYPES_FILE_NAME,
        )
        types = load_custom_types(_global_rules_dir(tmp_path))
        assert types.names == ()
        assert {issue.line for issue in types.errors} == {3, 4, 5, 6, 7}
        messages = " ".join(issue.message for issue in types.errors)
        assert "非空字符串" in messages
        assert "不是安全的文件夹名" in messages
        assert "内置票种重名" in messages
        assert "32" in messages

    def test_unknown_top_level_field_is_warning(self, tmp_path: Path) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "types: [酒店]", "extra: 1"],
            name=CUSTOM_TYPES_FILE_NAME,
        )
        types = load_custom_types(_global_rules_dir(tmp_path))
        assert types.names == ("酒店",)
        assert types.errors == ()
        assert any("未知的顶层字段" in issue.message for issue in types.issues)

    def test_save_creates_file_with_header_and_backup(self, tmp_path: Path) -> None:
        directory = _global_rules_dir(tmp_path)
        first = save_custom_types(directory, ["酒店"])
        assert first.names == ("酒店",)
        path = Path(first.path)
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# InvoiceFlowAI")
        assert "version: 1" in text
        assert list(path.parent.glob("*.tmp")) == []

        second = save_custom_types(directory, ["酒店", "会议"])
        assert second.names == ("酒店", "会议")
        backup_root = directory / ".backup"
        backups = [entry for entry in backup_root.iterdir() if entry.is_dir()]
        assert len(backups) == 1
        backup_file = backups[0] / CUSTOM_TYPES_FILE_NAME
        assert backup_file.is_file()
        assert "酒店" in backup_file.read_text(encoding="utf-8")

    def test_save_validates_before_writing(self, tmp_path: Path) -> None:
        directory = _global_rules_dir(tmp_path)
        save_custom_types(directory, ["酒店"])
        save_custom_types(directory, ["酒店", "会议"])
        path = directory / CUSTOM_TYPES_FILE_NAME
        before = path.read_text(encoding="utf-8")
        backups_before = len(list((directory / ".backup").iterdir()))
        with pytest.raises(RuleConfigError):
            save_custom_types(directory, ["坏/名"])
        assert path.read_text(encoding="utf-8") == before
        assert len(list((directory / ".backup").iterdir())) == backups_before

    def test_save_dedupes_normalized_names(self, tmp_path: Path) -> None:
        types = save_custom_types(
            _global_rules_dir(tmp_path), ["酒店", "酒店", "ＨＯＴＥＬ", "hotel"]
        )
        assert types.names == ("酒店", "ＨＯＴＥＬ")

    def test_add_custom_type_is_idempotent_and_persists(self, tmp_path: Path) -> None:
        directory = _global_rules_dir(tmp_path)
        assert add_custom_type("酒店", directory).names == ("酒店",)
        assert add_custom_type("酒店", directory).names == ("酒店",)
        types = add_custom_type("会议", directory)
        assert types.names == ("酒店", "会议")
        assert load_custom_types(directory).names == ("酒店", "会议")

    @pytest.mark.parametrize(
        "name",
        ["", "坏/名", "住宿发票", "rules", "长" * 33, None],
    )
    def test_add_custom_type_rejects_invalid_names(
        self, tmp_path: Path, name: object
    ) -> None:
        directory = _global_rules_dir(tmp_path)
        with pytest.raises(RuleConfigError):
            add_custom_type(name, directory)  # type: ignore[arg-type]
        assert load_custom_types(directory).names == ()

    def test_remove_custom_type(self, tmp_path: Path) -> None:
        directory = _global_rules_dir(tmp_path)
        add_custom_type("酒店", directory)
        add_custom_type("会议", directory)
        types = remove_custom_type("会议", directory)
        assert types.names == ("酒店",)
        assert remove_custom_type("不存在", directory).names == ("酒店",)
        assert load_custom_types(directory).names == ("酒店",)

    def test_remove_builtin_type_raises(self, tmp_path: Path) -> None:
        directory = _global_rules_dir(tmp_path)
        with pytest.raises(RuleConfigError) as excinfo:
            remove_custom_type("住宿发票", directory)
        assert "内置票种不可删除" in str(excinfo.value)

    @pytest.mark.parametrize(
        ("name", "existing", "fragment"),
        [
            ("酒店", [], None),
            ("", [], "不能为空"),
            ("坏/名", [], "不是安全的文件夹名"),
            ("住宿发票", [], "内置票种重名"),
            ("酒店", ["酒店"], "已存在"),
            ("ＨＯＴＥＬ", ["hotel"], "已存在"),
            ("长" * 33, [], "32"),
            (123, [], "必须是字符串"),
        ],
    )
    def test_custom_type_name_error(
        self, name: object, existing: list[str], fragment: str | None
    ) -> None:
        error = custom_type_name_error(name, existing)
        if fragment is None:
            assert error == ""
        else:
            assert fragment in error

    def test_invalid_custom_types_file_blocks_load_rule_set(self, tmp_path: Path) -> None:
        path = _write_global(
            tmp_path,
            ["version: 1", "types:", "  - 坏/名"],
            name=CUSTOM_TYPES_FILE_NAME,
        )
        with pytest.raises(RuleConfigError) as excinfo:
            _load(tmp_path)
        issue = next(
            item
            for item in excinfo.value.issues
            if "不是安全的文件夹名" in item.message
        )
        assert issue.file == str(path)
        assert issue.line == 3


# --------------------------------------------------------------------------- #
# target_type folder derivation
# --------------------------------------------------------------------------- #


class TestFolderFromTypeAndAmount:
    @pytest.mark.parametrize(
        ("type_name", "amount_range", "expected"),
        [
            ("酒店", None, "酒店"),
            ("酒店", [], "酒店"),
            (" 酒店 ", None, "酒店"),
            ("酒店", [100, 200], "酒店-100-200"),
            ("酒店", [100, None], "酒店-100以上"),
            ("酒店", [None, 200], "酒店-200以下"),
            ("酒店", [100, 100], "酒店-100"),
            ("酒店", [-200, -100], "酒店--200至-100"),
            ("酒店", [100.5, 200.25], "酒店-100.5-200.25"),
        ],
    )
    def test_derivation(
        self, type_name: str, amount_range: object, expected: str
    ) -> None:
        assert folder_from_type_and_amount(type_name, amount_range) == expected

    def test_empty_type_raises(self) -> None:
        for type_name in ("", "   ", None):
            with pytest.raises(ValueError):
                folder_from_type_and_amount(type_name)

    def test_too_long_folder_raises(self) -> None:
        with pytest.raises(ValueError):
            folder_from_type_and_amount("长" * 60, [100, 200])


# --------------------------------------------------------------------------- #
# target_type rules
# --------------------------------------------------------------------------- #


class TestTargetTypeRules:
    def test_target_rule_derives_folder_and_name(self, tmp_path: Path) -> None:
        _write_custom_types(tmp_path, ["酒店"])
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: hotel_rule",
                "    target_type: 酒店",
                "    keywords: [酒店]",
                "    amount_range: [100, 200]",
            ],
        )
        rule_set = _load(tmp_path)
        assert rule_set.custom_types == ("酒店",)
        assert rule_set.document_types[-1] == "酒店"
        assert "住宿发票" in rule_set.document_types
        rule = rule_set.category_map["hotel_rule"]
        assert rule.target_type == "酒店"
        assert rule.name == "酒店-100-200"
        assert rule.archive_folder == "酒店-100-200"
        assert rule.field_sources["archive_folder"].kind == "target_type"
        result = classify({"type": "其他", "seller": "酒店", "amount": "150"}, rule_set)
        assert result.category_id == "hotel_rule"
        assert result.category_name == "酒店-100-200"
        assert result.archive_folder == "酒店-100-200"
        assert result.source == SOURCE_USER_RULE
        assert result.category_src == CATEGORY_SOURCE_USER

    def test_target_rule_without_amount_range_uses_type_name(self, tmp_path: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: stay_rule",
                "    target_type: 住宿发票",
                "    keywords: [住宿]",
            ],
        )
        rule_set = _load(tmp_path)
        rule = rule_set.category_map["stay_rule"]
        assert rule.name == "住宿发票"
        assert rule.archive_folder == "住宿发票"

    def test_target_rule_ignores_invoice_types_gate(self, tmp_path: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: stay_rule",
                "    target_type: 住宿发票",
                "    keywords: [住宿]",
                "    invoice_types: [其他]",
            ],
        )
        rule_set = _load(tmp_path)
        # Recognized type 打车 would fail the legacy invoice_types gate.
        result = classify({"type": "打车", "seller": "住宿"}, rule_set)
        assert result.category_id == "stay_rule"
        assert result.archive_folder == "住宿发票"
        assert result.source == SOURCE_USER_RULE
        # Missing type also matches.
        assert classify({"seller": "住宿"}, rule_set).category_id == "stay_rule"

    def test_legacy_rule_keeps_invoice_types_gate(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        assert all(rule.target_type == "" for rule in rule_set.categories)
        # Built-in taxi keyword rule only applies when type recognition is 其他.
        gated = classify({"type": "打车", "seller": "滴滴"}, rule_set)
        assert gated.source == SOURCE_BUILTIN_TYPE
        ungated = classify({"type": "其他", "seller": "滴滴"}, rule_set)
        assert ungated.source == SOURCE_BUILTIN_KEYWORD
        # A user legacy rule with invoice_types keeps the same restriction.
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: legacy_rule",
                "    name: 旧规则",
                "    archive_folder: 旧规则",
                "    keywords: [旧词]",
                "    invoice_types: [其他]",
            ],
        )
        rule_set = _load(tmp_path)
        assert classify({"type": "打车", "seller": "旧词"}, rule_set).source != SOURCE_USER_RULE
        assert classify({"type": "其他", "seller": "旧词"}, rule_set).category_id == "legacy_rule"

    def test_unknown_target_type_rejected(self, tmp_path: Path) -> None:
        expr, path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: bad_rule",
                "    target_type: 不存在票种",
                "    keywords: [词]",
            ],
        )
        issue = next(
            item
            for item in expr.issues
            if "target_type 不是已注册票种" in item.message
        )
        assert issue.file == str(path)
        assert issue.line == 4

    def test_target_rule_requires_keywords(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: bad_rule",
                "    target_type: 住宿发票",
            ],
        )
        assert any("必须填写关键词" in issue.message for issue in expr.issues)

    def test_target_rule_negative_amount_suffix(self, tmp_path: Path) -> None:
        _write_custom_types(tmp_path, ["酒店"])
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: refund_rule",
                "    target_type: 酒店",
                "    keywords: [退款]",
                "    amount_range: [-200, -100]",
            ],
        )
        rule_set = _load(tmp_path)
        assert rule_set.category_map["refund_rule"].archive_folder == "酒店--200至-100"
        result = classify(
            {"type": "其他", "seller": "退款", "amount": "-150"}, rule_set
        )
        assert result.archive_folder == "酒店--200至-100"

    def test_target_rule_too_long_folder_rejected(self, tmp_path: Path) -> None:
        huge = "1" + "0" * 39
        huge_upper = "2" + "0" * 39
        expr, _path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: long_rule",
                "    target_type: 住宿发票",
                "    keywords: [长]",
                f"    amount_range: [{huge}, {huge_upper}]",
            ],
        )
        assert any("64" in issue.message for issue in expr.issues)

    def test_target_rule_reserved_builtin_type_rejected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: reserved_rule",
                "    target_type: 非目标公司发票",
                "    keywords: [甲]",
            ],
        )
        assert any("不安全" in issue.message for issue in expr.issues)

    def test_global_custom_type_usable_from_library_rule(self, tmp_path: Path) -> None:
        _write_custom_types(tmp_path, ["会议"])
        library = tmp_path / "library"
        library.mkdir()
        _write_lines(
            library / "rules" / "categories.yaml",
            [
                "version: 1",
                "categories:",
                "  - id: meeting_rule",
                "    target_type: 会议",
                "    keywords: [会议费]",
            ],
        )
        rule_set = _load(tmp_path, library=library)
        assert rule_set.custom_types == ("会议",)
        assert Path(rule_set.custom_types_path) == (
            _global_rules_dir(tmp_path) / CUSTOM_TYPES_FILE_NAME
        ).resolve()
        rule = rule_set.category_map["meeting_rule"]
        assert rule.name == "会议"
        assert rule.archive_folder == "会议"
        result = classify({"type": "其他", "seller": "会议费"}, rule_set)
        assert result.category_id == "meeting_rule"
        assert result.archive_folder == "会议"

    def test_target_type_takes_precedence_over_legacy_auto_folder(
        self, tmp_path: Path
    ) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: mixed_rule",
                "    target_type: 住宿发票",
                "    auto_folder: true",
                "    name: 显式名",
                "    archive_folder: 显式文件夹",
                "    keywords: [酒店]",
                "    amount_range: [100, 200]",
            ],
        )
        rule_set = _load(tmp_path)
        rule = rule_set.category_map["mixed_rule"]
        assert rule.auto_folder is True
        assert rule.name == "住宿发票-100-200"
        assert rule.archive_folder == "住宿发票-100-200"

    def test_custom_types_path_injection(self, tmp_path: Path) -> None:
        custom_path = _write_lines(
            tmp_path / "elsewhere" / CUSTOM_TYPES_FILE_NAME,
            ["version: 1", "types:", "  - 酒店"],
        )
        rule_set = load_rule_set(
            global_rules_dir=str(_global_rules_dir(tmp_path)),
            builtin_path=str(BUILTIN_PATH),
            custom_types_path=str(custom_path),
        )
        assert rule_set.custom_types == ("酒店",)
        assert rule_set.custom_types_path == str(custom_path.resolve())

    def test_ruleset_to_dict_includes_type_fields(self, tmp_path: Path) -> None:
        _write_custom_types(tmp_path, ["酒店"])
        rule_set = _load(tmp_path)
        payload = rule_set.to_dict()
        assert payload["custom_types"] == ["酒店"]
        assert "酒店" in payload["document_types"]
        assert payload["custom_types_path"].endswith(CUSTOM_TYPES_FILE_NAME)
        assert "target_type" in payload["categories"][0]

    def test_legacy_auto_folder_and_manual_rules_still_load(self, tmp_path: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: legacy_auto",
                "    auto_folder: true",
                "    keywords: [餐饮]",
                "  - id: legacy_manual",
                "    name: 手工",
                "    archive_folder: 手工",
                "    keywords: [手工词]",
            ],
        )
        rule_set = _load(tmp_path)
        assert rule_set.category_map["legacy_auto"].archive_folder == "餐饮"
        assert rule_set.category_map["legacy_auto"].target_type == ""
        assert rule_set.category_map["legacy_manual"].archive_folder == "手工"
        assert rule_set.category_map["legacy_manual"].target_type == ""


# --------------------------------------------------------------------------- #
# Seller dictionary (user_terms.yaml)
# --------------------------------------------------------------------------- #


class TestSellerDictionary:
    def test_seller_tin_exact_match_ignores_case_and_spaces(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "terms:",
                '  "9111 0108 MA01 ABCDEF": meal',
            ],
            name="user_terms.yaml",
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        result = classify({"type": "其他", "seller_tin": "91110108ma01 abcdef"}, rule_set)
        assert result.category_id == "meal"
        assert result.source == SOURCE_DICTIONARY
        # The dictionary is user configuration, so the decision is "user" even
        # though the meal category itself is a built-in default.
        assert result.category_src == CATEGORY_SOURCE_USER
        assert result.rule_id == "meal"
        assert result.keyword == "9111 0108 MA01 ABCDEF"

    def test_seller_name_substring_match(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "terms:", "  滴滴出行科技有限公司: taxi"],
            name="user_terms.yaml",
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        result = classify(
            {"type": "其他", "seller": "滴滴出行科技有限公司北京分公司"}, rule_set
        )
        assert result.category_id == "taxi"
        assert result.source == SOURCE_DICTIONARY
        assert result.chain[1]["kind"] == "seller_name"

    def test_longest_name_term_wins(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "terms:",
                "  滴滴: taxi",
                "  滴滴出行: train",
            ],
            name="user_terms.yaml",
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert classify({"type": "其他", "seller": "滴滴出行科技"}, rule_set).category_id == "train"

    def test_dictionary_precedes_keyword_rules(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "terms:", "  滴滴: train"],
            name="user_terms.yaml",
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        result = classify({"type": "其他", "seller": "滴滴出行"}, rule_set)
        assert result.category_id == "train"
        assert result.source == SOURCE_DICTIONARY

    def test_library_term_wins_tie(self, tmp_path: Path, mini_builtin: Path) -> None:
        library = tmp_path / "library"
        library.mkdir()
        _write_global(
            tmp_path,
            ["version: 1", "terms:", "  某某公司: taxi"],
            name="user_terms.yaml",
        )
        _write_lines(
            library / "rules" / "user_terms.yaml",
            ["version: 1", "terms:", "  某某公司: meal"],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin, library=library)
        assert rule_set.terms["某某公司"] == "meal"
        assert classify({"type": "其他", "seller": "某某公司"}, rule_set).category_id == "meal"

    def test_unknown_term_category_raises_with_line(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        expr, path = _raise_for_terms(
            tmp_path,
            ["version: 1", "terms:", "  某某公司: nope"],
        )
        assert path == _global_rules_dir(tmp_path) / "user_terms.yaml"
        assert 3 in _issue_lines(expr)
        assert any("不存在的分类" in issue.message for issue in expr.issues)

    def test_term_for_disabled_category_raises(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    enabled: false"],
        )
        expr, _path = _raise_for_terms(
            tmp_path, ["version: 1", "terms:", "  滴滴: taxi"], builtin=mini_builtin
        )
        assert any("已禁用" in issue.message for issue in expr.issues)

    def test_duplicate_term_key_rejected(self, tmp_path: Path, mini_builtin: Path) -> None:
        expr, _path = _raise_for_terms(
            tmp_path,
            ["version: 1", "terms:", "  某某公司: taxi", "  某某公司: meal"],
            builtin=mini_builtin,
        )
        assert 4 in _issue_lines(expr)


def _raise_for_terms(
    tmp_path: Path,
    lines: list[str],
    *,
    builtin: Path = BUILTIN_PATH,
) -> tuple[RuleConfigError, Path]:
    path = _write_global(tmp_path, lines, name="user_terms.yaml")
    try:
        _load(tmp_path, builtin=builtin)
    except RuleConfigError as exc:
        return exc, path
    raise AssertionError("expected RuleConfigError")


# --------------------------------------------------------------------------- #
# explain() / serialization
# --------------------------------------------------------------------------- #


class TestExplain:
    def test_explain_returns_result_fields_and_chain(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        payload = explain({"type": "其他", "seller": "滴滴出行"}, rule_set)
        assert payload["category_id"] == "taxi"
        assert payload["source"] == SOURCE_BUILTIN_KEYWORD
        assert isinstance(payload["chain"], list)
        assert payload["fields"]["seller"] == "滴滴出行"
        json.dumps(payload, ensure_ascii=False)

    def test_explain_reports_user_rule_file_and_line(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        path = _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    keywords: [草稿词]",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        payload = explain({"type": "其他", "seller": "草稿词"}, rule_set)
        assert payload["source"] == SOURCE_USER_RULE
        assert payload["category_src"] == CATEGORY_SOURCE_USER
        assert payload["source_file"] == str(path)
        assert payload["source_line"] == 4
        assert payload["rule_id"] == "taxi"
        assert payload["keyword"] == "草稿词"

    def test_result_to_dict_matches_to_dict(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        result = classify({"type": "打车"}, rule_set)
        assert result_to_dict(result) == result.to_dict()
        json.dumps(result_to_dict(result), ensure_ascii=False)

    def test_unknown_chain_reports_fallback(self, tmp_path: Path) -> None:
        rule_set = _load(tmp_path)
        payload = explain({"type": "其他", "seller": "无关公司"}, rule_set)
        stages = [item.get("stage") for item in payload["chain"]]
        assert "dictionary" in stages
        assert "type_fallback" in stages
        assert stages[-1] == "fallback"
        assert payload["chain"][-1]["category"] == "other"

    def test_classify_rejects_non_rule_set(self) -> None:
        with pytest.raises(TypeError):
            classify({}, object())  # type: ignore[arg-type]

    def test_category_src_marks_user_driven_decisions(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        rule_set = _load(tmp_path, builtin=mini_builtin)
        builtin_keyword = classify({"type": "其他", "seller": "滴滴"}, rule_set)
        assert builtin_keyword.source == SOURCE_BUILTIN_KEYWORD
        assert builtin_keyword.category_src == CATEGORY_SOURCE_BUILTIN
        builtin_type = classify({"type": "打车"}, rule_set)
        assert builtin_type.source == SOURCE_BUILTIN_TYPE
        assert builtin_type.category_src == CATEGORY_SOURCE_BUILTIN

        _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    keywords: [用户词]"],
        )
        _write_global(
            tmp_path,
            ["version: 1", "terms:", "  用户卖方: meal"],
            name="user_terms.yaml",
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        user_rule = classify({"type": "其他", "seller": "用户词"}, rule_set)
        assert user_rule.category_src == CATEGORY_SOURCE_USER
        assert user_rule.source == SOURCE_USER_RULE
        dictionary = classify({"type": "其他", "seller": "用户卖方"}, rule_set)
        assert dictionary.category_src == CATEGORY_SOURCE_USER


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


class TestValidation:
    def test_invalid_category_id_reports_exact_line(self, tmp_path: Path) -> None:
        expr, path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: Taxi",
                "    name: 打车",
            ],
        )
        assert path == _global_rules_dir(tmp_path) / "categories.yaml"
        assert 3 in _issue_lines(expr)
        assert any("分类 id 不合法" in issue.message for issue in expr.issues)
        assert isinstance(expr.issues, tuple)
        assert all(isinstance(issue, RuleIssue) for issue in expr.issues)
        assert str(path) in str(expr)

    def test_duplicate_category_id_within_file(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "  - id: taxi",
            ],
        )
        assert 4 in _issue_lines(expr)
        assert any("重复" in issue.message for issue in expr.issues)

    def test_duplicate_yaml_mapping_key_rejected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "fallback: other",
                "fallback: meal",
            ],
        )
        assert 3 in _issue_lines(expr)
        assert any("重复的映射键" in issue.message for issue in expr.issues)

    def test_unsupported_version_rejected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(tmp_path, ["version: 2", "categories: []"])
        assert 1 in _issue_lines(expr)

    def test_priority_bool_is_ignored_with_warning(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        path = _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    priority: true"],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.category_map["taxi"].priority == 0
        warning = next(
            issue for issue in rule_set.warnings if "priority" in issue.message
        )
        assert warning.severity == "warning"
        assert warning.file == str(path)
        assert warning.line == 4
        assert warning.message == "priority 已不再使用，规则按列表顺序匹配"

    def test_priority_string_is_ignored_with_warning(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    priority: high"],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.category_map["taxi"].priority == 0
        assert any("priority 已不再使用" in issue.message for issue in rule_set.warnings)

    def test_enabled_string_rejected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    enabled: yes please"],
        )
        assert any("enabled 必须是布尔值" in issue.message for issue in expr.issues)

    def test_invalid_match_rejected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    match: everything"],
        )
        assert any("match 必须是" in issue.message for issue in expr.issues)

    def test_unregistered_invoice_type_rejected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    invoice_types: [不存在的票种]",
            ],
        )
        assert any("票种未注册" in issue.message for issue in expr.issues)

    def test_keywords_must_be_string_list(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    keywords: 滴滴"],
        )
        assert any("字符串列表" in issue.message for issue in expr.issues)

    def test_keyword_items_must_be_strings(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    keywords: [滴滴, 3]"],
        )
        assert any("每一项必须是非空字符串" in issue.message for issue in expr.issues)

    @pytest.mark.parametrize(
        ("amount_range", "expected_fragment"),
        [
            ("[1, 2, 3]", "必须恰好包含"),
            ("[200, 100]", "下限"),
            ("[true, 10]", "数字或 null"),
            ("[abc, 10]", "数字或 null"),
            ("{}", "[下限, 上限]"),
        ],
    )
    def test_invalid_amount_range(
        self, tmp_path: Path, amount_range: str, expected_fragment: str
    ) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                f"    amount_range: {amount_range}",
            ],
        )
        assert any(expected_fragment in issue.message for issue in expr.issues)

    def test_unknown_category_field_is_a_warning(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: taxi",
                "    keywordz: [typо]",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.warnings
        warning = rule_set.warnings[0]
        assert warning.severity == "warning"
        assert warning.line == 4
        assert "未知的分类字段" in warning.message

    def test_unknown_top_level_field_is_a_warning(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(tmp_path, ["version: 1", "categoryz: []"])
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert any("未知的顶层字段" in issue.message for issue in rule_set.warnings)

    def test_unsafe_archive_folder_rejected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    archive_folder: 坏/目录"],
        )
        assert any("不是安全的文件夹名" in issue.message for issue in expr.issues)

    def test_reserved_tool_folder_rejected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    archive_folder: rules"],
        )
        assert any("不是安全的文件夹名" in issue.message for issue in expr.issues)

    def test_fallback_must_exist(self, tmp_path: Path, mini_builtin: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            ["version: 1", "fallback: nope"],
        )
        assert any("不存在" in issue.message for issue in expr.issues)

    def test_fallback_must_be_enabled(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: other", "    enabled: false"],
        )
        try:
            _load(tmp_path, builtin=mini_builtin)
        except RuleConfigError as exc:
            assert any("fallback 分类已被禁用" in issue.message for issue in exc.issues)
        else:
            raise AssertionError("expected RuleConfigError")

    def test_new_category_requires_name(self, tmp_path: Path, mini_builtin: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            ["version: 1", "categories:", "  - id: parking", "    enabled: true"],
        )
        assert any("缺少 name" in issue.message for issue in expr.issues)

    def test_inherited_name_is_allowed(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: taxi", "    enabled: true"],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.category_map["taxi"].name == "打车"

    def test_type_categories_unknown_category_rejected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            ["version: 1", "type_categories:", "  打车: nope"],
        )
        assert any("指向不存在的分类" in issue.message for issue in expr.issues)

    def test_type_categories_disabled_target_warns_but_loads(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        _write_global(
            tmp_path,
            ["version: 1", "categories:", "  - id: meal", "    enabled: false"],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert any("指向已禁用的分类" in issue.message for issue in rule_set.warnings)
        result = classify({"type": "餐饮"}, rule_set)
        assert result.source == SOURCE_UNKNOWN

    def test_invalid_yaml_syntax_reports_line(self, tmp_path: Path) -> None:
        _write_text(_global_rules_dir(tmp_path) / "categories.yaml", "categories: [\n")
        with pytest.raises(RuleConfigError) as excinfo:
            _load(tmp_path)
        assert any(issue.line >= 1 for issue in excinfo.value.issues)
        assert any("YAML 解析失败" in issue.message for issue in excinfo.value.issues)

    def test_top_level_must_be_mapping(self, tmp_path: Path) -> None:
        _write_text(_global_rules_dir(tmp_path) / "categories.yaml", "- a\n- b\n")
        with pytest.raises(RuleConfigError) as excinfo:
            _load(tmp_path)
        assert any("顶层必须是映射" in issue.message for issue in excinfo.value.issues)

    def test_all_errors_are_collected(self, tmp_path: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            [
                "version: 9",
                "categories:",
                "  - id: BadId",
                "  - id: also_bad",
                "    archive_folder: 坏/目录",
                "    name: 缺失",
            ],
        )
        assert len([issue for issue in expr.issues if issue.severity == "error"]) >= 2

    def test_category_archive_folder_defaults_to_name(self, tmp_path: Path, mini_builtin: Path) -> None:
        _write_global(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: parking",
                "    name: 停车费",
            ],
        )
        rule_set = _load(tmp_path, builtin=mini_builtin)
        assert rule_set.category_map["parking"].archive_folder == "停车费"

    def test_unsafe_default_folder_name_rejected(self, tmp_path: Path, mini_builtin: Path) -> None:
        expr, _path = _load_config_error(
            tmp_path,
            [
                "version: 1",
                "categories:",
                "  - id: parking",
                "    name: 坏/名称",
            ],
        )
        assert any("默认归档文件夹名不安全" in issue.message for issue in expr.issues)


# --------------------------------------------------------------------------- #
# is_safe_folder_name
# --------------------------------------------------------------------------- #


class TestSafeFolderNames:
    @pytest.mark.parametrize(
        "name",
        [
            "打车",
            "其他",
            "通讯费",
            "parking",
            "A B",
            "a.b",
            "x" * 64,
        ],
    )
    def test_safe_names(self, name: str) -> None:
        assert is_safe_folder_name(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "",
            ".",
            "..",
            "a/b",
            "a\\b",
            'a:b',
            "a*b",
            "a?b",
            'a"b',
            "a<b",
            "a>b",
            "a|b",
            "abc.",
            "abc ",
            "a" * 65,
            "CON",
            "con",
            "NUL.txt",
            "COM1",
            "lpt9",
            "\x01bad",
            "\x7fbad",
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
        ],
    )
    def test_unsafe_names(self, name: str) -> None:
        assert is_safe_folder_name(name) is False

    @pytest.mark.parametrize("name", [None, 123, ["打车"]])
    def test_non_string_values(self, name: object) -> None:
        assert is_safe_folder_name(name) is False


# --------------------------------------------------------------------------- #
# Scope read/save/reset/template
# --------------------------------------------------------------------------- #


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    path = tmp_path / "发票库"
    path.mkdir()
    return path


class TestScopeRead:
    def test_empty_scope(self, library: Path) -> None:
        data = read_scope("library", library)
        assert isinstance(data, ScopeData)
        assert data.categories == ()
        assert data.terms == {}
        assert data.fallback is None
        assert data.type_categories == {}
        assert data.exists is False
        assert Path(data.rules_dir) == (library / "rules").resolve()

    def test_invalid_scope_raises_value_error(self, library: Path) -> None:
        with pytest.raises(ValueError):
            read_scope("workspace", library)
        with pytest.raises(ValueError):
            read_scope("library", None)

    def test_read_scope_roundtrip(self, library: Path, tmp_path: Path) -> None:
        categories = [
            {
                "id": "parking",
                "name": "停车费",
                "archive_folder": "停车费",
                "invoice_types": ["其他"],
                "keywords": ["停车"],
            }
        ]
        terms = {"某某停车管理有限公司": "parking"}
        save_scope("library", library, categories, terms)
        data = read_scope("library", library)
        assert data.exists is True
        assert [dict(entry) for entry in data.categories] == categories
        assert data.terms == terms
        assert Path(data.rules_dir) == (library / "rules").resolve()

    def test_read_scope_rejects_invalid_file(self, library: Path) -> None:
        _write_text(library / "rules" / "categories.yaml", "categories: [\n")
        with pytest.raises(RuleConfigError):
            read_scope("library", library)

    def test_read_scope_serializes(self, library: Path) -> None:
        data = read_scope("library", library)
        json.dumps(data.to_dict(), ensure_ascii=False)


class TestSaveScope:
    def test_save_scope_writes_valid_files_and_returns_rule_set(self, library: Path) -> None:
        categories = [
            {
                "id": "parking",
                "name": "停车费",
                "archive_folder": "停车费",
                "invoice_types": ["其他"],
                "keywords": ["停车"],
            }
        ]
        terms = {"某某停车管理有限公司": "parking"}
        rule_set = save_scope("library", library, categories, terms)
        assert isinstance(rule_set, RuleSet)
        assert rule_set.category_map["parking"].archive_folder == "停车费"
        assert rule_set.category_map["parking"].scope == CATEGORY_SOURCE_USER
        categories_path = library / "rules" / "categories.yaml"
        terms_path = library / "rules" / "user_terms.yaml"
        assert categories_path.is_file()
        assert terms_path.is_file()
        assert categories_path.read_text(encoding="utf-8").startswith("# InvoiceFlowAI")
        reloaded = _load(tmp_path=library.parent, library=library)
        result = classify({"type": "其他", "seller": "某某停车管理有限公司"}, reloaded)
        assert result.category_id == "parking"
        assert result.source == SOURCE_DICTIONARY

    def test_save_scope_validates_before_writing(self, library: Path) -> None:
        categories_path = library / "rules" / "categories.yaml"
        good = [
            "version: 1",
            "categories:",
            "  - id: parking",
            "    name: 停车费",
            "    archive_folder: 停车费",
        ]
        _write_lines(categories_path, good)
        before = categories_path.read_text(encoding="utf-8")
        bad = [{"id": "parking", "name": "停车费", "archive_folder": "坏/目录"}]
        with pytest.raises(RuleConfigError):
            save_scope("library", library, bad, {})
        assert categories_path.read_text(encoding="utf-8") == before
        assert not (library / "rules" / ".backup").exists()

    def test_save_scope_backs_up_previous_files(self, library: Path) -> None:
        first = [
            {
                "id": "parking",
                "name": "停车费",
                "archive_folder": "停车费",
                "keywords": ["旧词"],
            }
        ]
        save_scope("library", library, first, {})
        second = [
            {
                "id": "parking",
                "name": "停车费",
                "archive_folder": "停车费",
                "keywords": ["新词"],
            }
        ]
        save_scope("library", library, second, {})
        backup_root = library / "rules" / ".backup"
        backups = [entry for entry in backup_root.iterdir() if entry.is_dir()]
        assert len(backups) == 1
        assert (backups[0] / "categories.yaml").is_file()
        assert "旧词" in (backups[0] / "categories.yaml").read_text(encoding="utf-8")
        assert classify({"type": "其他", "seller": "停车"}, build_rule_set(
            library
        )).category_id == "other"

    def test_backup_retention_keeps_newest_twenty(self, library: Path) -> None:
        backup_root = library / "rules" / ".backup"
        backup_root.mkdir(parents=True)
        for index in range(25):
            (backup_root / f"20000101-0000{index:02d}-1").mkdir()
        _write_lines(
            library / "rules" / "categories.yaml",
            ["version: 1", "categories: []"],
        )
        save_scope(
            "library",
            library,
            [{"id": "parking", "name": "停车费", "archive_folder": "停车费"}],
            {},
        )
        remaining = [entry for entry in backup_root.iterdir() if entry.is_dir()]
        assert len(remaining) == 20

    def test_save_scope_preserves_type_categories(self, library: Path) -> None:
        _write_lines(
            library / "rules" / "categories.yaml",
            [
                "version: 1",
                "type_categories:",
                "  打车: meal",
                "categories: []",
            ],
        )
        save_scope(
            "library",
            library,
            [{"id": "parking", "name": "停车费", "archive_folder": "停车费"}],
            {},
        )
        data = read_scope("library", library)
        assert data.type_categories == {"打车": "meal"}
        rule_set = _load(tmp_path=library.parent, library=library)
        assert rule_set.type_categories["打车"] == "meal"

    def test_atomic_write_leaves_no_temp_files(self, library: Path) -> None:
        save_scope(
            "library",
            library,
            [{"id": "parking", "name": "停车费", "archive_folder": "停车费"}],
            {},
        )
        leftovers = list((library / "rules").glob("*.tmp"))
        assert leftovers == []

    def test_save_scope_global_writes_into_settings_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        appdata = tmp_path / "appdata"
        monkeypatch.setenv("APPDATA", str(appdata))
        save_scope(
            "global",
            None,
            [{"id": "gift", "name": "礼品", "archive_folder": "礼品", "keywords": ["礼品"]}],
            {},
        )
        categories_path = appdata / "InvoiceFlowAI" / "rules" / "categories.yaml"
        assert categories_path.is_file()
        rule_set = load_rule_set()
        assert "gift" in rule_set.category_map

    def test_save_scope_rejects_unknown_scope(self, library: Path) -> None:
        with pytest.raises(ValueError):
            save_scope("workspace", library, [], {})

    def test_save_scope_terms_are_persisted_independently(self, library: Path) -> None:
        save_scope("library", library, [], {"某某公司": "other"})
        data = read_scope("library", library)
        assert data.terms == {"某某公司": "other"}
        # Saving categories again without passing terms overwrites the terms
        # file with the explicitly provided (empty) mapping.
        save_scope("library", library, [], {})
        assert read_scope("library", library).terms == {}


class TestResetAndTemplate:
    def test_reset_scope_backs_up_then_removes(self, library: Path) -> None:
        save_scope(
            "library",
            library,
            [{"id": "parking", "name": "停车费", "archive_folder": "停车费"}],
            {"某某公司": "parking"},
        )
        pack = _write_lines(
            library / "rules" / "rules.d" / "10-pack.yaml",
            ["version: 1", "categories: []"],
        )
        backups = reset_scope("library", library)
        assert len(backups) == 1
        backup_dir = Path(backups[0])
        assert (backup_dir / "categories.yaml").is_file()
        assert (backup_dir / "user_terms.yaml").is_file()
        assert not (library / "rules" / "categories.yaml").exists()
        assert not (library / "rules" / "user_terms.yaml").exists()
        assert pack.is_file(), "rules.d must not be touched by reset"

    def test_reset_scope_without_files_returns_empty_list(self, library: Path) -> None:
        assert reset_scope("library", library) == []

    def test_ensure_scope_template_creates_valid_files(self, library: Path, tmp_path: Path) -> None:
        path = Path(ensure_scope_template("library", library))
        assert path == (library / "rules" / "categories.yaml").resolve()
        assert path.is_file()
        assert (library / "rules" / "user_terms.yaml").is_file()
        rule_set = _load(tmp_path=tmp_path, library=library)
        assert set(rule_set.category_map) == set(EXPECTED_CATEGORIES)
        assert rule_set.terms == {}
        before = path.read_text(encoding="utf-8")
        assert Path(ensure_scope_template("library", library)) == path
        assert path.read_text(encoding="utf-8") == before

    def test_ensure_scope_template_does_not_overwrite(self, library: Path) -> None:
        categories_path = library / "rules" / "categories.yaml"
        _write_text(categories_path, "version: 1\ncategories: []\n")
        ensure_scope_template("library", library)
        assert categories_path.read_text(encoding="utf-8") == "version: 1\ncategories: []\n"

    def test_scope_template_documents_list_order_and_auto_folder(
        self, library: Path
    ) -> None:
        path = Path(ensure_scope_template("library", library))
        text = path.read_text(encoding="utf-8")
        assert "priority: 60" not in text
        assert " auto_folder: true" in text
        assert "按列表顺序匹配" in text
        assert "不再影响匹配顺序" in text


# --------------------------------------------------------------------------- #
# In-memory overrides (web draft preview)
# --------------------------------------------------------------------------- #


class TestOverrides:
    def test_override_categories_affect_classification_without_writes(
        self, tmp_path: Path, mini_builtin: Path
    ) -> None:
        global_dir = _global_rules_dir(tmp_path)
        rule_set = build_rule_set(
            global_rules_dir=global_dir,
            builtin_path=mini_builtin,
            overrides={
                "global": {
                    "categories": [
                        {
                            "id": "taxi",
                            "keywords": ["草稿词"],
                        }
                    ]
                }
            },
        )
        assert rule_set.overrides_applied == ("global",)
        result = classify({"type": "其他", "seller": "草稿词"}, rule_set)
        assert result.category_id == "taxi"
        assert result.source == SOURCE_USER_RULE
        assert not (global_dir / "categories.yaml").exists(), "override must not write files"
        assert not (global_dir / "user_terms.yaml").exists()

    def test_override_terms_and_fallback(self, tmp_path: Path, mini_builtin: Path) -> None:
        rule_set = build_rule_set(
            global_rules_dir=_global_rules_dir(tmp_path),
            builtin_path=mini_builtin,
            overrides={
                "global": {
                    "categories": [],
                    "terms": {"草稿卖方": "meal"},
                    "fallback": "meal",
                    "type_categories": {},
                }
            },
        )
        assert classify({"type": "其他", "seller": "草稿卖方"}, rule_set).category_id == "meal"
        unknown = classify({"type": "其他", "seller": "无关"}, rule_set)
        assert unknown.category_id == "meal"
        assert unknown.source == SOURCE_UNKNOWN

    def test_override_accepts_scope_data(self, tmp_path: Path, mini_builtin: Path) -> None:
        scope_data = ScopeData(
            scope="global",
            rules_dir=str(_global_rules_dir(tmp_path)),
            categories=(
                {
                    "id": "taxi",
                    "name": "打车",
                    "archive_folder": "打车",
                    "keywords": ["草稿词"],
                },
            ),
            terms={},
            fallback=None,
            type_categories={},
        )
        rule_set = build_rule_set(
            global_rules_dir=_global_rules_dir(tmp_path),
            builtin_path=mini_builtin,
            overrides={"global": scope_data},
        )
        assert rule_set.category_map["taxi"].keywords == ("草稿词",)

    def test_override_invalid_config_raises(self, tmp_path: Path, mini_builtin: Path) -> None:
        with pytest.raises(RuleConfigError) as excinfo:
            build_rule_set(
                global_rules_dir=_global_rules_dir(tmp_path),
                builtin_path=mini_builtin,
                overrides={"global": {"categories": [{"id": "BadId"}]}},
            )
        assert any("分类 id 不合法" in issue.message for issue in excinfo.value.issues)

    def test_library_override_uses_library_layer(self, tmp_path: Path, mini_builtin: Path) -> None:
        library = tmp_path / "library"
        library.mkdir()
        rule_set = build_rule_set(
            library,
            global_rules_dir=_global_rules_dir(tmp_path),
            builtin_path=mini_builtin,
            overrides={"library": {"categories": [{"id": "taxi", "keywords": ["库草稿"]}]}},
        )
        assert rule_set.library_dir == str(library.resolve())
        assert classify({"type": "其他", "seller": "库草稿"}, rule_set).category_id == "taxi"

    def test_build_rule_set_matches_load_rule_set(self, tmp_path: Path, mini_builtin: Path) -> None:
        left = load_rule_set(
            global_rules_dir=str(_global_rules_dir(tmp_path)),
            builtin_path=str(mini_builtin),
        )
        right = build_rule_set(
            global_rules_dir=str(_global_rules_dir(tmp_path)),
            builtin_path=str(mini_builtin),
        )
        assert left.to_dict() == right.to_dict()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@pytest.fixture()
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    appdata = tmp_path / "appdata"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    return appdata


class TestCli:
    def test_parser_has_all_subcommands(self) -> None:
        parser = rules_cli._build_parser()
        subparsers_action = next(
            action
            for action in parser._actions
            if action.__class__.__name__ == "_SubParsersAction"
        )
        assert set(subparsers_action.choices) == {
            "list",
            "validate",
            "test",
            "explain",
            "edit",
            "add-rule",
            "add-category",
            "add-keyword",
            "remove-keyword",
            "disable",
            "enable",
            "rename",
            "terms",
            "types",
            "reset",
        }

    def test_cli_does_not_depend_on_organize_cli(self) -> None:
        source = (ROOT / "expense_rules" / "cli.py").read_text(encoding="utf-8")
        assert "organize_cli" not in source

    def test_list_json(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["list", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        ids = [row["id"] for row in payload["categories"]]
        assert ids == list(EXPECTED_CATEGORIES)
        taxi = next(row for row in payload["categories"] if row["id"] == "taxi")
        assert "priority" not in taxi
        assert taxi["archive_folder"] == "打车"
        assert taxi["keywords"] == ["滴滴", "高德", "曹操", "T3", "出租", "网约车", "客运服务", "运输服务", "盛智", "畅行"]
        assert taxi["amount_range"] is None
        assert taxi["invoice_types"] == ["其他"]
        assert taxi["auto_folder"] is False

    def test_list_human_has_no_priority_column(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["list"]) == 0
        out = capsys.readouterr().out
        assert "优先级" not in out
        assert "关键词=" in out
        assert "金额=" in out
        assert "票种=" in out
        assert "文件夹=" in out

    def test_list_shows_target_type_and_hides_invoice_gate(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rules_dir = cli_env / "InvoiceFlowAI" / "rules"
        _write_lines(
            rules_dir / CUSTOM_TYPES_FILE_NAME,
            ["version: 1", "types:", "  - 酒店"],
        )
        _write_lines(
            rules_dir / "categories.yaml",
            [
                "version: 1",
                "categories:",
                "  - id: hotel_rule",
                "    target_type: 酒店",
                "    keywords: [酒店]",
                "    amount_range: [100, 200]",
                "    invoice_types: [其他]",
            ],
        )
        assert rules_cli.main(["list", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        row = next(item for item in payload["categories"] if item["id"] == "hotel_rule")
        assert row["target_type"] == "酒店"
        assert row["archive_folder"] == "酒店-100-200"
        assert row["amount_range"] == ["100", "200"]

        assert rules_cli.main(["list"]) == 0
        target_line = next(
            line
            for line in capsys.readouterr().out.splitlines()
            if "hotel_rule" in line
        )
        assert "输出票种=酒店" in target_line
        assert " | 票种=" not in target_line
        assert "酒店-100-200" in target_line

    def test_test_command_json(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["test", "--type", "打车", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["category_id"] == "taxi"
        assert payload["source"] == SOURCE_BUILTIN_TYPE

    def test_explain_command_json(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["explain", "--type", "其他", "--seller", "滴滴", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["category_id"] == "taxi"
        assert isinstance(payload["chain"], list)

    def test_validate_reports_broken_rules(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_lines(
            cli_env / "InvoiceFlowAI" / "rules" / "categories.yaml",
            ["version: 1", "categories:", "  - id: BadId"],
        )
        assert rules_cli.main(["validate"]) == 1
        captured = capsys.readouterr()
        assert "分类 id 不合法" in captured.err
        assert "categories.yaml" in captured.err

    def test_validate_warns_about_legacy_priority(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_lines(
            cli_env / "InvoiceFlowAI" / "rules" / "categories.yaml",
            ["version: 1", "categories:", "  - id: taxi", "    priority: 60"],
        )
        assert rules_cli.main(["validate"]) == 0
        out = capsys.readouterr().out
        assert "priority 已不再使用，规则按列表顺序匹配" in out

    def test_add_and_remove_keyword(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["add-keyword", "taxi", "新平台词"]) == 0
        capsys.readouterr()
        rule_set = load_rule_set()
        assert "新平台词" in rule_set.category_map["taxi"].keywords
        assert (
            classify({"type": "其他", "seller": "新平台词"}, rule_set).category_id == "taxi"
        )
        assert rules_cli.main(["remove-keyword", "taxi", "新平台词"]) == 0
        capsys.readouterr()
        rule_set = load_rule_set()
        assert "新平台词" not in rule_set.category_map["taxi"].keywords
        assert classify({"type": "其他", "seller": "新平台词"}, rule_set).source == SOURCE_UNKNOWN

    def test_add_keyword_unknown_category(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["add-keyword", "nope", "词"]) == 2
        assert "未知分类" in capsys.readouterr().err

    def test_remove_keyword_not_present(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["remove-keyword", "taxi", "不存在的词"]) == 1
        assert "没有这些关键词" in capsys.readouterr().out

    def test_add_category(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert (
            rules_cli.main(
                ["add-category", "parking", "--name", "停车费", "--keyword", "停车"]
            )
            == 0
        )
        capsys.readouterr()
        rule_set = load_rule_set()
        assert rule_set.category_map["parking"].archive_folder == "停车费"
        assert rule_set.category_map["parking"].keywords == ("停车",)

    def test_add_category_duplicate_rejected(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["add-category", "taxi", "--name", "重复"]) == 2
        assert "分类已存在" in capsys.readouterr().err

    def test_add_category_invalid_id_rejected(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["add-category", "BadId", "--name", "坏"]) == 2
        assert "分类 id 不合法" in capsys.readouterr().err

    def test_add_category_priority_flag_removed(self, cli_env: Path) -> None:
        with pytest.raises(SystemExit):
            rules_cli.main(
                ["add-category", "parking", "--name", "停车费", "--priority", "5"]
            )

    def test_add_category_with_folder_flag(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            rules_cli.main(
                ["add-category", "parking", "--name", "停车费", "--folder", "停车"]
            )
            == 0
        )
        capsys.readouterr()
        assert load_rule_set().category_map["parking"].archive_folder == "停车"

    def test_add_rule_creates_target_type_rule(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            rules_cli.main(
                [
                    "add-rule",
                    "餐饮",
                    "--type",
                    "住宿发票",
                    "--amount-min",
                    "100",
                ]
            )
            == 0
        )
        out = capsys.readouterr().out
        assert "rule_1" in out
        assert "住宿发票-100以上" in out
        rule_set = load_rule_set()
        rule = rule_set.category_map["rule_1"]
        assert rule.target_type == "住宿发票"
        assert rule.auto_folder is False
        assert rule.invoice_types == ()
        assert rule.archive_folder == "住宿发票-100以上"
        assert rule.name == "住宿发票-100以上"
        assert rule.amount_range == (Decimal("100"), None)
        # target_type rules ignore the invoice-type gate entirely.
        matched = classify(
            {"type": "打车", "seller": "餐饮", "amount": "150"}, rule_set
        )
        assert matched.category_id == "rule_1"
        assert matched.archive_folder == "住宿发票-100以上"
        assert classify(
            {"type": "其他", "seller": "餐饮", "amount": "50"}, rule_set
        ).category_id == "meal"

    def test_add_rule_with_custom_type(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["types", "add", "会议"]) == 0
        capsys.readouterr()
        assert rules_cli.main(["add-rule", "会议费", "--type", "会议"]) == 0
        capsys.readouterr()
        rule = load_rule_set().category_map["rule_1"]
        assert rule.target_type == "会议"
        assert rule.archive_folder == "会议"

    def test_add_rule_requires_type(self, cli_env: Path) -> None:
        with pytest.raises(SystemExit):
            rules_cli.main(["add-rule", "餐饮"])

    def test_add_rule_rejects_unknown_type(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["add-rule", "餐饮", "--type", "不存在票种"]) == 2
        assert "未知票种" in capsys.readouterr().err

    def test_add_rule_rejects_legacy_flags(self, cli_env: Path) -> None:
        with pytest.raises(SystemExit):
            rules_cli.main(["add-rule", "餐饮", "--type", "餐饮", "--invoice-types", "餐饮"])

    def test_add_rule_increments_ids(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["add-rule", "词一", "--type", "餐饮"]) == 0
        assert rules_cli.main(["add-rule", "词二", "--type", "餐饮"]) == 0
        capsys.readouterr()
        rule_set = load_rule_set()
        assert "rule_1" in rule_set.category_map
        assert "rule_2" in rule_set.category_map

    def test_add_rule_invalid_amount_range(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            rules_cli.main(
                [
                    "add-rule",
                    "餐饮",
                    "--type",
                    "餐饮",
                    "--amount-min",
                    "200",
                    "--amount-max",
                    "100",
                ]
            )
            == 2
        )
        assert "下限" in capsys.readouterr().err

    def test_types_list_add_remove(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["types", "list", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["custom_types"] == []
        assert payload["builtin_types"]
        assert payload["path"].endswith(CUSTOM_TYPES_FILE_NAME)

        assert rules_cli.main(["types", "add", "酒店"]) == 0
        capsys.readouterr()
        assert rules_cli.main(["types", "list", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["custom_types"] == ["酒店"]

        assert rules_cli.main(["types", "add", "酒店"]) == 0
        capsys.readouterr()
        assert load_custom_types().names == ("酒店",)

        assert rules_cli.main(["types", "remove", "酒店"]) == 0
        capsys.readouterr()
        assert load_custom_types().names == ()

    def test_types_add_builtin_rejected(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["types", "add", "住宿发票"]) == 1
        assert "内置票种" in capsys.readouterr().err

    def test_types_remove_builtin_rejected(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["types", "remove", "住宿发票"]) == 2
        assert "内置票种不可删除" in capsys.readouterr().err

    def test_types_remove_referenced_global_rule_fails(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rules_dir = cli_env / "InvoiceFlowAI" / "rules"
        assert rules_cli.main(["types", "add", "酒店"]) == 0
        capsys.readouterr()
        _write_lines(
            rules_dir / "categories.yaml",
            ["version: 1", "categories:", "  - id: stay", "    target_type: 酒店", "    keywords: [酒店]"],
        )
        assert rules_cli.main(["types", "remove", "酒店"]) == 2
        err = capsys.readouterr().err
        assert "仍被规则引用" in err
        assert "stay" in err
        assert load_custom_types().names == ("酒店",)

    def test_types_remove_referenced_library_rule_fails(
        self, cli_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        library = tmp_path / "library"
        library.mkdir()
        assert rules_cli.main(["types", "add", "会议"]) == 0
        capsys.readouterr()
        _write_lines(
            library / "rules" / "categories.yaml",
            ["version: 1", "categories:", "  - id: meeting", "    target_type: 会议", "    keywords: [会议]"],
        )
        assert (
            rules_cli.main(
                ["types", "remove", "会议", "--library", str(library)]
            )
            == 2
        )
        err = capsys.readouterr().err
        assert "仍被规则引用" in err
        assert "meeting" in err

    def test_types_require_name(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["types", "add"]) == 2
        assert "需要票种名称" in capsys.readouterr().err
        assert rules_cli.main(["types", "remove"]) == 2
        assert "需要票种名称" in capsys.readouterr().err

    def test_disable_and_enable(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["disable", "meal"]) == 0
        capsys.readouterr()
        assert load_rule_set().category_map["meal"].enabled is False
        assert rules_cli.main(["enable", "meal"]) == 0
        capsys.readouterr()
        assert load_rule_set().category_map["meal"].enabled is True

    def test_rename_preserves_archive_folder(
        self, cli_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rules_cli.main(["rename", "meal", "吃饭"]) == 0
        capsys.readouterr()
        rule = load_rule_set().category_map["meal"]
        assert rule.name == "吃饭"
        assert rule.archive_folder == "餐饮"

    def test_terms_add_and_remove(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["terms", "--add", "某某餐饮公司=meal"]) == 0
        capsys.readouterr()
        rule_set = load_rule_set()
        assert rule_set.terms["某某餐饮公司"] == "meal"
        assert rules_cli.main(["terms", "--remove", "某某餐饮公司"]) == 0
        capsys.readouterr()
        assert load_rule_set().terms == {}

    def test_reset_requires_yes(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["reset"]) == 2
        assert "--yes" in capsys.readouterr().err

    def test_reset_after_save(self, cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rules_cli.main(["add-category", "parking", "--name", "停车费"]) == 0
        capsys.readouterr()
        assert rules_cli.main(["reset", "--yes", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert len(payload["backups"]) == 1
        assert "parking" not in load_rule_set().category_map

    def test_edit_opens_template(
        self,
        cli_env: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        opened: list[str] = []
        monkeypatch.setattr(rules_cli, "_open_with_system", lambda path: opened.append(path))
        assert rules_cli.main(["edit"]) == 0
        out = capsys.readouterr().out
        assert "categories.yaml" in out
        assert opened
        assert Path(opened[0]).is_file()

    def test_library_scope_flag(self, cli_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        library = tmp_path / "library"
        library.mkdir()
        assert rules_cli.main(["add-keyword", "taxi", "库内词", "--library", str(library)]) == 0
        capsys.readouterr()
        assert (library / "rules" / "categories.yaml").is_file()
        rule_set = load_rule_set(library)
        assert "库内词" in rule_set.category_map["taxi"].keywords

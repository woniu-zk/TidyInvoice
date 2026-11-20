"""End-to-end coverage for user-configurable expense classification rules."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

SAMPLE_EINVOICE_TEXT = """电子发票（普通发票）
发票号码：26112000000012345678
开票日期：2026年03月15日
购买方信息
名称：北京示例科技有限公司
统一社会信用代码/纳税人识别号：91110108MA01ABCDEF
销售方信息
名称：上海滴滴出行科技有限公司
统一社会信用代码/纳税人识别号：91310115MA1K9XYZ12
项目名称 规格型号 单位 数量 单价 金额 税率/征收率 税额
*运输服务*客运服务费 1 100.00 100.00 3% 3.00
合计 ¥100.00 ¥3.00
价税合计（大写）壹佰零叁元整 （小写）¥103.00
备注：
"""


def _write_pdf_with_text(path: Path, lines: list[str]) -> Path:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72.0, 90.0 + index * 28.0), line, fontname="china-s", fontsize=11)
    document.save(str(path))
    document.close()
    return path


def _write_invoice_xml(
    path: Path,
    *,
    number: str = "26112000000012345678",
    seller: str = "上海滴滴出行科技有限公司",
    purchaser: str = "北京示例科技有限公司",
    amount: str = "103.00",
    item: str = "",
) -> Path:
    item_xml = f"<spmc>{item}</spmc>" if item else ""
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Invoice>"
        f"<fphm>{number}</fphm>"
        "<kprq>2026-03-15</kprq>"
        f"<gmfmc>{purchaser}</gmfmc>"
        f"<xfmc>{seller}</xfmc>"
        f"<jshj>{amount}</jshj>"
        f"{item_xml}"
        "</Invoice>",
        encoding="utf-8",
    )
    return path


def _wait_for_terminal(api, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = api.get_progress()
        if snapshot.get("run_state") in {"completed", "failed"}:
            return snapshot
        time.sleep(0.05)
    raise AssertionError(f"run did not finish: {api.get_progress()}")


def _start_local(api, input_dir: Path, *, split_by_category: bool = True) -> dict:
    result = api.start_local_organize(
        str(input_dir), split_by_category=split_by_category
    )
    assert result.get("success") is True, result
    snapshot = _wait_for_terminal(api)
    assert snapshot["run_state"] == "completed", snapshot
    return snapshot


def _write_global_rules(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "AppData" / "Roaming" / "TidyInvoice" / "rules" / "categories.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _custom_rule_yaml() -> str:
    return """version: 1
categories:
  - id: large_amount
    name: 大额
    archive_folder: 大额
    priority: 200
    enabled: true
    match: seller
    keywords: [滴滴]
    amount_range: [100, null]
"""


def test_saved_global_rule_routes_next_run_to_custom_folder(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "large_amount",
                    "name": "大额",
                    "archive_folder": "大额",
                    "priority": 200,
                    "enabled": True,
                    "match": "any",
                    "invoice_types": [],
                    "keywords": ["滴滴"],
                    "exclude_keywords": [],
                    "amount_range": [100, None],
                }
            ],
            "terms": [],
            "fallback": "other",
        }
    )
    assert saved["success"] is True, saved

    loaded = api.load_classification_rules("")
    assert loaded["success"] is True, loaded
    large = next(
        item for item in loaded["effective_categories"] if item["id"] == "large_amount"
    )
    assert large["archive_folder"] == "大额"
    assert large["source_layer"] == "global"

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(inbox / "大额滴滴.xml", amount="103.00")
    _write_invoice_xml(
        inbox / "小额滴滴.xml",
        number="26112000000099999999",
        amount="99.00",
    )

    _start_local(api, inbox)

    archived = [path for path in inbox.rglob("*") if path.is_file()]
    names = {path.name for path in archived}
    assert any(path.parent.name == "大额" for path in archived), names
    assert any(path.parent.name == "打车" for path in archived), names


def test_unknown_invoice_enters_manual_review_and_reports_unclassified(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(inbox / "未知服务商.xml", seller="未知服务商", amount="12.00")

    _start_local(api, inbox)

    review_dir = inbox / "待人工复核"
    assert review_dir.is_dir()
    assert any(review_dir.iterdir())
    results = api.get_results()
    summary = results["summary"]
    assert summary["unclassified_count"] == 1
    assert summary["classification_source_breakdown"].get("unknown") == 1
    assert "其他" not in summary["classification_breakdown"]
    assert results["organize_summary"]["unclassified_count"] == 1
    assert not (inbox / "其他").exists(), "unknown invoices must not be silently filed as 其他"


def test_broken_rule_file_blocks_run_and_reports_line(tmp_path: Path):
    from app_api import InvoiceAppAPI

    rules_path = _write_global_rules(
        tmp_path,
        "version: 1\ncategories:\n  - id: broken\n    keywords: 123\n",
    )
    api = InvoiceAppAPI()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(inbox / "发票.xml")

    result = api.start_local_organize(str(inbox))
    assert result["success"] is False
    assert str(rules_path) in result["message"] or "categories.yaml" in result["message"]
    assert ":" in result["message"]


def test_rules_folder_is_never_scanned_in_place(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    rule_file = inbox / "rules" / "categories.yaml"
    rule_file.parent.mkdir()
    rule_file.write_text("version: 1\ncategories: []\n", encoding="utf-8")
    _write_invoice_xml(inbox / "发票.xml")

    _start_local(api, inbox)

    assert rule_file.is_file()
    assert rule_file.read_text(encoding="utf-8") == "version: 1\ncategories: []\n"


def test_library_rule_overrides_global_rule(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    library = tmp_path / "library"
    library.mkdir()
    _write_global_rules(tmp_path, _custom_rule_yaml())
    api.save_user_settings(
        {"task_mode": "local", "local_input_dir": str(library)}
    )
    saved = api.save_classification_rules(
        {
            "scope": "library",
            "library_dir": str(library),
            "categories": [
                {
                    "id": "large_amount",
                    "name": "本库大额",
                    "archive_folder": "本库大额",
                    "priority": 300,
                    "enabled": True,
                    "match": "seller",
                    "keywords": ["滴滴"],
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved

    loaded = api.load_classification_rules(str(library))
    assert loaded["success"] is True, loaded
    large = next(
        item for item in loaded["effective_categories"] if item["id"] == "large_amount"
    )
    assert large["name"] == "本库大额"
    assert large["archive_folder"] == "本库大额"
    assert large["source_layer"] == "library"


def test_flat_layout_applies_rule_without_creating_folder(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    _write_global_rules(tmp_path, _custom_rule_yaml())
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(inbox / "大额滴滴.xml", amount="103.00")

    _start_local(api, inbox, split_by_category=False)

    assert not (inbox / "大额").exists()
    root_files = [
        path
        for path in inbox.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".xml", ".ofd"}
    ]
    assert root_files
    summary = api.get_results()["organize_summary"]
    assert summary["split_by_category"] is False


def test_layout_switch_reapplies_rules_and_keeps_custom_folder(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    _write_global_rules(tmp_path, _custom_rule_yaml())
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(inbox / "大额滴滴.xml", amount="103.00")

    _start_local(api, inbox, split_by_category=True)
    first = api.get_results()["organize_summary"]
    assert first["split_by_category"] is True
    assert any(path.parent.name == "大额" for path in inbox.rglob("*.xml"))

    _start_local(api, inbox, split_by_category=False)
    root_files = [
        path
        for path in inbox.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".xml", ".ofd"}
    ]
    assert root_files, [
        ascii(path.relative_to(inbox).as_posix()) for path in inbox.rglob("*")
    ]
    assert not (inbox / "大额").exists()

    _start_local(api, inbox, split_by_category=True)
    assert any(path.parent.name == "大额" for path in inbox.rglob("*.xml"))


def test_rules_cli_add_rule_creates_target_type_folder(tmp_path: Path):
    from expense_rules import load_rule_set
    from expense_rules.cli import main as rules_main

    exit_code = rules_main(
        [
            "add-rule",
            "酒店",
            "--type",
            "住宿发票",
            "--amount-min",
            "100",
            "--amount-max",
            "200",
        ]
    )
    assert exit_code == 0
    category = load_rule_set().get_category("rule_1")
    assert category is not None
    assert category.target_type == "住宿发票"
    assert category.archive_folder == "住宿发票-100-200"
    assert category.keywords == ("酒店",)
    assert category.invoice_types == ()


def test_yaml_match_any_alias_is_accepted(tmp_path: Path):
    from expense_rules import classify, load_rule_set

    _write_global_rules(
        tmp_path,
        "version: 1\ncategories:\n"
        "  - id: any_rule\n    name: 任意匹配\n    archive_folder: 任意匹配\n"
        "    priority: 500\n    match: any\n    keywords: [滴滴]\n",
    )
    rule_set = load_rule_set()
    category = rule_set.get_category("any_rule")
    assert category is not None
    assert category.match == "any"
    result = classify(
        {"type": "其他", "seller": "上海滴滴出行科技有限公司", "amount": "12.00"},
        rule_set,
    )
    assert result.category_id == "any_rule"


def test_rules_api_status_and_draft_test_and_reset(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    draft_result = api.test_classification_rules(
        {
            "scope": "global",
            "draft": {
                "categories": [
                    {
                        "id": "draft_big",
                        "name": "草稿大额",
                        "archive_folder": "草稿大额",
                        "priority": 200,
                        "enabled": True,
                        "match": "any",
                        "keywords": ["滴滴"],
                        "amount_range": [100, None],
                    }
                ],
                "terms": [],
                "fallback": "other",
            },
            "fields": {
                "seller": "滴滴出行",
                "type": "打车",
                "amount": "103.00",
            },
        }
    )
    assert draft_result["success"] is True, draft_result
    assert draft_result["draft_used"] is True
    assert draft_result["result"]["category_id"] == "draft_big"

    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "persisted_big",
                    "name": "保存大额",
                    "archive_folder": "保存大额",
                    "priority": 200,
                    "enabled": True,
                    "match": "any",
                    "keywords": ["滴滴"],
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True
    status = api.get_classification_rules_status()
    assert status["success"] is True
    assert status["issues"] == []
    reset = api.reset_classification_rules("global")
    assert reset["success"] is True
    assert reset["backups"]
    assert api.load_classification_rules("")["effective_categories"][-1]["id"] == "other"


def test_custom_type_is_global_and_target_rule_uses_type_amount_folder(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    created = api.create_classification_type({"name": "酒店"})
    assert created["success"] is True, created
    assert "酒店" in created["custom_types"]
    assert "酒店" in created["document_types"]

    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "hotel_big",
                    "target_type": "酒店",
                    "keywords": ["酒店"],
                    "amount_range": [100, 200],
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved
    loaded = api.load_classification_rules("")
    category = next(
        item
        for item in loaded["effective_categories"]
        if item["id"] == "hotel_big"
    )
    assert category["target_type"] == "酒店"
    assert category["archive_folder"] == "酒店-100-200"
    assert "酒店" in loaded["document_types"]

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(
        inbox / "hotel.xml", amount="150.00", item="酒店住宿服务"
    )
    _start_local(api, inbox)
    assert (inbox / "酒店-100-200").is_dir(), [
        ascii(path.relative_to(inbox).as_posix()) for path in inbox.rglob("*")
    ]

    blocked = api.delete_classification_type({"name": "酒店"})
    assert blocked["success"] is False
    assert any("酒店" in item.get("message", "") for item in blocked["issues"])

    cleared = api.save_classification_rules(
        {"scope": "global", "categories": [], "terms": []}
    )
    assert cleared["success"] is True, cleared
    deleted = api.delete_classification_type({"name": "酒店"})
    assert deleted["success"] is True, deleted
    assert "酒店" not in deleted["custom_types"]


def test_builtin_type_can_be_rule_target_and_type_name_validates(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    duplicate = api.create_classification_type({"name": "住宿发票"})
    assert duplicate["success"] is False
    assert duplicate["issues"]

    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "builtin_target",
                    "target_type": "住宿发票",
                    "keywords": ["酒店"],
                    "amount_range": [100, None],
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved
    loaded = api.load_classification_rules("")
    category = next(
        item
        for item in loaded["effective_categories"]
        if item["id"] == "builtin_target"
    )
    assert category["archive_folder"] == "住宿发票-100以上"


def test_custom_type_created_for_library_rule_is_global(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    library = tmp_path / "library"
    library.mkdir()
    api.save_user_settings(
        {"task_mode": "local", "local_input_dir": str(library)}
    )
    created = api.create_classification_type({"name": "会议"})
    assert created["success"] is True, created

    saved = api.save_classification_rules(
        {
            "scope": "library",
            "library_dir": str(library),
            "categories": [
                {
                    "id": "meeting_rule",
                    "target_type": "会议",
                    "keywords": ["会议"],
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved
    global_loaded = api.load_classification_rules("")
    library_loaded = api.load_classification_rules(str(library))
    assert "会议" in global_loaded["document_types"]
    assert "会议" in library_loaded["document_types"]
    category = next(
        item
        for item in library_loaded["effective_categories"]
        if item["id"] == "meeting_rule"
    )
    assert category["target_type"] == "会议"
    assert category["archive_folder"] == "会议"


def test_target_rule_ignores_legacy_invoice_types_gate(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "hotel_keyword",
                    "target_type": "住宿发票",
                    "keywords": ["酒店"],
                    "invoice_types": ["住宿发票"],
                    "auto_folder": False,
                    "archive_folder": "旧文件夹",
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    # Seller contains 滴滴, so the recognized type is 打车; the target rule must
    # still match because target_type is an output, not a condition.
    _write_invoice_xml(
        inbox / "hotel-taxi.xml", amount="88.00", item="酒店住宿服务"
    )
    _start_local(api, inbox)
    assert (inbox / "住宿发票").is_dir(), [
        ascii(path.relative_to(inbox).as_posix()) for path in inbox.rglob("*")
    ]


def test_builtin_rule_can_be_overridden_and_restored(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    created = api.create_classification_type({"name": "酒店"})
    assert created["success"] is True, created
    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "taxi",
                    "target_type": "酒店",
                    "keywords": ["滴滴"],
                    "amount_range": [100, 200],
                    "enabled": True,
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved
    loaded = api.load_classification_rules("")
    taxi = next(
        item for item in loaded["effective_categories"] if item["id"] == "taxi"
    )
    assert taxi["target_type"] == "酒店"
    assert taxi["archive_folder"] == "酒店-100-200"
    assert "taxi" in loaded["builtin_category_ids"]

    restored = api.reset_builtin_classification_rules(
        {"scope": "global", "scope_mode": "current", "category_id": "taxi"}
    )
    assert restored["success"] is True, restored
    loaded = api.load_classification_rules("")
    taxi = next(
        item for item in loaded["effective_categories"] if item["id"] == "taxi"
    )
    assert taxi["archive_folder"] == "打车"
    assert taxi["source_layer"] == "builtin"


def test_builtin_target_rule_keeps_invoice_type_gate(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    created = api.create_classification_type({"name": "酒店"})
    assert created["success"] is True, created
    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "hotel",
                    "target_type": "酒店",
                    "keywords": ["酒店"],
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    # Seller contains 滴滴 -> recognized type is 打车. The built-in override
    # inherits the built-in hotel invoice_types gate (其他), so its keyword must
    # not match; the recognized taxi type maps to the taxi folder.
    _write_invoice_xml(
        inbox / "taxi-hotel.xml",
        seller="上海滴滴出行科技有限公司",
        amount="88.00",
        item="酒店住宿服务",
    )
    _start_local(api, inbox)
    assert (inbox / "打车").is_dir(), [
        ascii(path.relative_to(inbox).as_posix()) for path in inbox.rglob("*")
    ]
    assert not (inbox / "酒店").exists()


def test_restore_all_builtin_overrides_across_scopes(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    library = tmp_path / "library"
    library.mkdir()
    api.save_user_settings({"task_mode": "local", "local_input_dir": str(library)})
    global_saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "hotel",
                    "name": "住宿自定义",
                    "archive_folder": "住宿自定义",
                    "keywords": ["酒店"],
                    "invoice_types": ["其他"],
                },
                {
                    "id": "keep_rule",
                    "target_type": "住宿发票",
                    "keywords": ["保留"],
                },
            ],
            "terms": [],
        }
    )
    assert global_saved["success"] is True, global_saved
    library_saved = api.save_classification_rules(
        {
            "scope": "library",
            "library_dir": str(library),
            "categories": [
                {
                    "id": "taxi",
                    "name": "本库打车",
                    "archive_folder": "本库打车",
                    "keywords": ["滴滴"],
                    "invoice_types": ["其他"],
                }
            ],
            "terms": [],
        }
    )
    assert library_saved["success"] is True, library_saved

    restored = api.reset_builtin_classification_rules(
        {
            "scope": "global",
            "library_dir": str(library),
            "scope_mode": "all",
        }
    )
    assert restored["success"] is True, restored
    assert set(restored["scopes"]) == {"global", "library"}
    loaded = api.load_classification_rules(str(library))
    by_id = {item["id"]: item for item in loaded["effective_categories"]}
    assert by_id["taxi"]["archive_folder"] == "打车"
    assert by_id["hotel"]["archive_folder"] == "住宿发票"
    assert by_id["taxi"]["source_layer"] == "builtin"
    assert by_id["hotel"]["source_layer"] == "builtin"
    assert by_id["keep_rule"]["target_type"] == "住宿发票"


def test_auto_folder_rule_uses_keyword_and_amount_range(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "auto_big",
                    "keywords": ["滴滴"],
                    "amount_range": [100, 200],
                    "auto_folder": True,
                    "enabled": True,
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved
    loaded = api.load_classification_rules("")
    auto_big = next(
        item for item in loaded["effective_categories"] if item["id"] == "auto_big"
    )
    assert auto_big["auto_folder"] is True
    assert auto_big["archive_folder"] == "滴滴100-200"

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(inbox / "一百五.xml", amount="150.00")
    _write_invoice_xml(inbox / "二百五.xml", number="26112000000099999999", amount="250.00")

    _start_local(api, inbox)

    folders = {path.parent.name for path in inbox.rglob("*.xml")}
    assert "滴滴100-200" in folders, [
        ascii(path.relative_to(inbox).as_posix()) for path in inbox.rglob("*")
    ]
    assert "打车" in folders, folders


def test_auto_folder_without_range_is_keyword(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "auto_taxi",
                    "keywords": ["滴滴"],
                    "auto_folder": True,
                    "enabled": True,
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(inbox / "滴滴.xml", amount="42.00")
    _start_local(api, inbox)
    assert (inbox / "滴滴").is_dir()


def test_auto_folder_layout_switch_keeps_item_keyword_folder(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "auto_item",
                    "keywords": ["客运服务费"],
                    "auto_folder": True,
                    "enabled": True,
                }
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(
        inbox / "item.xml", seller="未知服务商", amount="50.00", item="客运服务费"
    )

    _start_local(api, inbox, split_by_category=True)
    assert (inbox / "客运服务费").is_dir()

    _start_local(api, inbox, split_by_category=False)
    root_files = [
        path
        for path in inbox.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".xml", ".ofd"}
    ]
    assert root_files

    _start_local(api, inbox, split_by_category=True)
    assert (inbox / "客运服务费").is_dir(), [
        ascii(path.relative_to(inbox).as_posix()) for path in inbox.rglob("*")
    ]


def test_priority_does_not_override_list_order(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    saved = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "first_rule",
                    "keywords": ["滴滴"],
                    "auto_folder": True,
                    "enabled": True,
                    "priority": 1,
                },
                {
                    "id": "second_rule",
                    "keywords": ["滴滴"],
                    "auto_folder": True,
                    "enabled": True,
                    "priority": 999,
                },
            ],
            "terms": [],
        }
    )
    assert saved["success"] is True, saved
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_invoice_xml(inbox / "滴滴.xml", amount="42.00")
    _start_local(api, inbox)
    assert (inbox / "滴滴").is_dir()
    assert not (inbox / "滴滴42").exists()


def test_auto_folder_rejects_empty_keyword(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    result = api.save_classification_rules(
        {
            "scope": "global",
            "categories": [
                {
                    "id": "no_keyword",
                    "keywords": [],
                    "auto_folder": True,
                    "enabled": True,
                }
            ],
            "terms": [],
        }
    )
    assert result["success"] is False
    assert any("关键词" in item.get("message", "") for item in result["issues"])


def test_paired_ride_artifacts_follow_the_invoice_category(tmp_path: Path):
    """A rule matching the invoice must not split its itinerary into another folder."""
    import shutil
    from types import SimpleNamespace

    from app_api import _FallbackDocumentTraceStore
    from archive_service import ArchiveService
    from candidate_pipeline import CandidatePipeline
    from expense_rules import load_rule_set
    from extraction_pipeline import ExtractionOutcome

    _write_global_rules(tmp_path, _custom_rule_yaml())
    rule_set = load_rule_set()
    output = tmp_path / "output"
    output.mkdir()

    sources = {}
    candidates = []
    for name, itinerary in (("invoice.pdf", False), ("itinerary.pdf", True)):
        source = tmp_path / name
        source.write_bytes(b"payload")
        sources[name] = source
        candidates.append(
            CandidatePipeline().collect(
                [{"filepath": str(source), "email_id": "ride-mail-1"}]
            )[0]
        )

    class Extractor:
        last_route_trace = {"status": "archived"}

        def route_and_rename_file(
            self, path, info_json, custom_rules=None, flat_layout=False
        ):
            del flat_layout
            folder = str(info_json.get("Type") or "其他")
            if custom_rules:
                for keyword, target in custom_rules.items():
                    if keyword in folder:
                        folder = target
                        break
            target_dir = output / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            display = "打车行程单" if info_json.get("_is_itinerary") else "打车"
            number = info_json.get("InvoiceNumber") or "0"
            target = target_dir / f"20260610_{display}_103.00_滴滴{number}.pdf"
            shutil.copy2(path, target)
            return True, str(target)

    class Api:
        def __init__(self):
            self.processed_invoices = []
            self.error_invoices = []
            self.discovered_categories = set()
            self.stats = {"invoices": 0, "errors": 0}
            self.logs = []
            self._cwt_cancellation_registry = []
            self.artifact_events = []

        @staticmethod
        def _resolve_active_company():
            return ""

        @staticmethod
        def _inspect_pdf_health(_path):
            return {"pdf_health_class": "healthy"}

        @staticmethod
        def _retain_artifact(_root, path, _bucket, _reason, _metadata):
            return path

        @staticmethod
        def _send_to_manual_check(_root, path, _reason, **_kwargs):
            return path

        def _safe_emit_artifact_event(self, event, path, **kwargs):
            self.artifact_events.append((event, path, kwargs))

        @staticmethod
        def _safe_emit_stage_event(*_args, **_kwargs):
            return None

        @staticmethod
        def _cwt_cancellation_matching(_root):
            return None

        @staticmethod
        def _record_archive_folder_history(_save_path, _folders, _file_folders=None):
            return None

    api = Api()
    acceptance = SimpleNamespace(
        evaluate=lambda *_args, **_kwargs: {"accepted": True},
        normalized_snapshot=lambda fields: dict(fields),
    )

    from app_archive_adapter import AppArchiveAdapter

    trace_store = _FallbackDocumentTraceStore(tmp_path / "trace.jsonl")
    for candidate in candidates:
        trace_store.start_document(
            source_filename=candidate.source_filename,
            source_path=candidate.source_path,
            document_id=candidate.identity.document_id,
        )
    adapter = AppArchiveAdapter(
        api=api,
        extractor=Extractor(),
        save_path=str(output),
        business_records={},
        trace_store=trace_store,
        acceptance_service=acceptance,
        classification_rule_set=rule_set,
    )

    outcomes = []
    for index, candidate in enumerate(candidates):
        info = {
            "Date": "20260610",
            "Amount": "103.00",
            "Purchaser": "北京示例科技有限公司",
            "Seller": "上海滴滴出行科技有限公司",
            "Type": "打车",
            "InvoiceCode": "",
            "InvoiceNumber": f"2611200000000000000{index}",
            "is_invoice": True,
        }
        if index == 1:
            info["_is_itinerary"] = True
        outcomes.append(
            ExtractionOutcome.resolved(
                candidate,
                {
                    "pdf_path": str(sources[Path(candidate.source_path).name]),
                    "metadata": {
                        "filepath": candidate.source_path,
                        "email_id": "ride-mail-1",
                    },
                    "info_json": info,
                },
            )
        )

    report = ArchiveService(
        normalizer=adapter.normalize,
        classifier=adapter.classify,
        archive_operation=adapter.archive_operation,
        dedupe_key=adapter.dedupe_key,
        finalizer=adapter.finalize,
    ).archive(outcomes, output)

    assert report.can_complete is True
    assert (output / "大额").is_dir(), [ascii(p.name) for p in output.iterdir()]
    custom_files = [path for path in (output / "大额").iterdir() if path.is_file()]
    assert len(custom_files) == 2, list(output.rglob("*"))
    assert not (output / "打车").exists() or not any((output / "打车").iterdir())
    categories = {row["category"] for row in api.processed_invoices}
    assert categories == {"大额"}

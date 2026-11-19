"""End-to-end tests for feature ② (local organize) and feature ① (fetch-only).

The two product features must stay independent:
- fetch  : mailbox -> inbox/ + manifest.jsonl (no parsing)
- organize: any local directory -> archive + ledger (no mailbox config)
"""

from __future__ import annotations

import ast
import json
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


def _write_invoice_xml(path: Path, *, number: str = "26112000000012345678") -> Path:
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Invoice>"
        f"<fphm>{number}</fphm>"
        "<kprq>2026-03-15</kprq>"
        "<gmfmc>北京示例科技有限公司</gmfmc>"
        "<xfmc>上海滴滴出行科技有限公司</xfmc>"
        "<jshj>103.00</jshj>"
        "</Invoice>",
        encoding="utf-8",
    )
    return path


def _build_inbox(root: Path) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    files = [
        _write_pdf_with_text(root / "发票A.pdf", SAMPLE_EINVOICE_TEXT.splitlines()),
        _write_invoice_xml(root / "发票B.xml", number="26112000000099999999"),
        _write_invoice_xml(root / "发票C.xml"),
        (root / "说明.txt"),
    ]
    files[-1].write_text("not an invoice", encoding="utf-8")
    return files


def _wait_for_terminal(api, timeout: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = api.get_progress()
        if snapshot.get("run_state") in {"completed", "failed"}:
            return snapshot
        time.sleep(0.05)
    raise AssertionError(f"run did not finish: {api.get_progress()}")


def _start_local(
    api,
    input_dir: Path,
    output_dir: Path | None = None,
    dry_run: bool = False,
    split_by_category: bool = True,
) -> dict:
    args = [str(input_dir)] if output_dir is None else [str(input_dir), str(output_dir)]
    result = api.start_local_organize(
        *args, dry_run=dry_run, split_by_category=split_by_category
    )
    assert result.get("success") is True, result
    snapshot = _wait_for_terminal(api)
    assert snapshot["run_state"] == "completed", snapshot
    return snapshot


def _root_invoice_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".xml", ".ofd"}
    ]


def test_start_local_organize_validates_requests(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    empty = api.start_local_organize("", str(tmp_path / "out"))
    assert empty["success"] is False and "文件夹" in empty["message"]

    missing = api.start_local_organize(str(tmp_path / "missing"), str(tmp_path / "out"))
    assert missing["success"] is False and "不存在" in missing["message"]

    anchor = Path(tmp_path.anchor) if tmp_path.anchor else None
    if anchor is not None and str(anchor):
        drive_root = api.start_local_organize(str(anchor), str(tmp_path / "out"))
        assert drive_root["success"] is False
        assert "磁盘根目录" in drive_root["message"]

    # Same folder is the default in-place mode and must be accepted.
    folder = tmp_path / "invoices"
    _build_inbox(folder)
    same = _start_local(api, folder, dry_run=True)
    assert same["run_state"] == "completed"


def test_local_organize_in_place_apply_relocates_and_is_idempotent(tmp_path: Path):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    original_names = {path.name for path in _root_invoice_files(inbox)}
    assert original_names == {"发票A.pdf", "发票B.xml", "发票C.xml"}

    api = InvoiceAppAPI()
    snapshot = _start_local(api, inbox)
    assert snapshot["status_text"] in {"整理完成", "处理完成"}

    results = api.get_results()
    assert results["task_mode"] == "local"
    assert results["dry_run"] is False
    assert results["input_dir"] == str(inbox)
    assert results["output_path"] == str(inbox)
    summary = results["organize_summary"]
    assert summary["output_dir"] == str(inbox)
    assert summary["in_place"] is True
    assert summary["split_by_category"] is True
    assert api.load_user_settings()["settings"]["local_split_by_category"] is True
    assert summary["scanned_files"] == 3
    assert summary["archived_count"] >= 2
    assert summary["raw_moved_count"] >= 2
    assert summary["duplicates_moved_count"] >= 1

    archived = [
        path
        for path in inbox.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pdf", ".xml"}
    ]
    assert archived, "local organize did not archive any file"
    assert any(path.parent.name == "打车" for path in archived)
    assert any("整理前发票" in path.parts for path in archived), archived
    raw_files = [
        path
        for path in inbox.rglob("*")
        if path.is_file() and "整理前发票" in path.parts
    ]
    assert raw_files, "originals were not moved into 整理前发票/"
    assert {path.name for path in raw_files} == {"发票A.pdf", "发票B.xml"}
    duplicate_files = [
        path for path in inbox.rglob("*") if path.is_file() and "duplicates" in path.parts
    ]
    assert duplicate_files, "duplicate original was not moved into duplicates/"
    assert {path.name for path in duplicate_files} == {"发票C.xml"}
    assert _root_invoice_files(inbox) == [], "processed originals must leave the folder root"
    assert any(path.suffix == ".xlsx" for path in inbox.rglob("*"))

    # A second run over the same folder is idempotent: no new archives/moves.
    files_after_first = {path for path in inbox.rglob("*") if path.is_file()}
    second = _start_local(api, inbox)
    assert second["run_state"] == "completed"
    second_results = api.get_results()
    second_summary = second_results["organize_summary"]
    assert second_summary["scanned_files"] == 0
    assert second_summary["archived_count"] == 0
    assert second_summary["raw_moved_count"] == 0
    assert second_summary["duplicates_moved_count"] == 0
    files_after_second = {path for path in inbox.rglob("*") if path.is_file()}
    # The second run may write a fresh Excel report, but must not add archives.
    new_files = files_after_second - files_after_first
    assert all(path.suffix == ".xlsx" for path in new_files), new_files


def test_local_organize_in_place_dry_run_writes_nothing(tmp_path: Path):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    before = sorted(path.relative_to(inbox).as_posix() for path in inbox.rglob("*") if path.is_file())

    api = InvoiceAppAPI()
    _start_local(api, inbox, dry_run=True)

    results = api.get_results()
    assert results["dry_run"] is True
    rows = [row for row in results["successInvoices"] if row.get("preview")]
    assert rows, "dry-run must expose preview rows"
    assert all(row.get("path") for row in rows)
    after = sorted(path.relative_to(inbox).as_posix() for path in inbox.rglob("*") if path.is_file())
    assert after == before, "dry-run must not move or create files"
    assert not (inbox / "整理前发票").exists()
    assert not (inbox / "duplicates").exists()


def test_local_organize_custom_output_copies_without_relocating(tmp_path: Path):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    output = tmp_path / "output"
    originals_before = sorted(path.name for path in _root_invoice_files(inbox))

    api = InvoiceAppAPI()
    _start_local(api, inbox, output_dir=output)

    results = api.get_results()
    summary = results["organize_summary"]
    assert results["output_path"] == str(output)
    assert summary["output_dir"] == str(output)
    assert summary["in_place"] is False
    assert summary["archived_count"] >= 2
    assert summary["raw_moved_count"] == 0
    assert not (inbox / "整理前发票").exists()
    assert sorted(path.name for path in _root_invoice_files(inbox)) == originals_before
    archived = [
        path
        for path in output.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pdf", ".xml"}
    ]
    assert archived and any(path.parent.name == "打车" for path in archived)


def test_local_organize_does_not_overwrite_mail_save_path(tmp_path: Path):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    mail_save_path = tmp_path / "mail-library"
    api = InvoiceAppAPI()
    saved = api.save_user_settings(
        {"save_path": str(mail_save_path), "email": "user@qq.com", "auth_code": "auth"}
    )
    assert saved["success"] is True

    _start_local(api, inbox)

    settings = api.load_user_settings()["settings"]
    assert settings["save_path"] == str(mail_save_path)
    assert settings["task_mode"] == "local"
    assert settings["local_input_dir"] == str(inbox)
    assert settings["local_output_dir"] == ""


def test_local_organize_relocation_failure_keeps_original(tmp_path: Path, monkeypatch):
    from app_api import InvoiceAppAPI
    from local_organize import LocalOrganizer, OrganizeRequest

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)

    api = InvoiceAppAPI()
    organizer = LocalOrganizer(
        api,
        OrganizeRequest(input_dir=str(inbox), output_dir=str(inbox), dry_run=False),
    )

    def _boom(*_args, **_kwargs):
        raise OSError("simulated move failure")

    # Originals are relocated verbatim into 整理前发票/ through this resolver;
    # making it fail must leave them in place instead of failing the run.
    monkeypatch.setattr(organizer, "_verbatim_raw_target", _boom)
    result = organizer.run()

    assert result.archived_count >= 2
    assert result.raw_moved_count == 0
    assert result.originals_kept_count >= 1
    assert any("整理前发票" in warning for warning in result.warnings)
    assert _root_invoice_files(inbox), "originals must stay in place when relocation fails"


def test_preview_archive_target_is_pure_and_deterministic(tmp_path: Path):
    from invoice_extractor import InvoiceExtractor

    output = tmp_path / "output"
    extractor = InvoiceExtractor(api_key="", output_dir=str(output))
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4 stub")
    payload = {
        "is_invoice": True,
        "Date": "2026-03-15",
        "Seller": "上海滴滴出行科技有限公司",
        "Amount": "103.00",
        "InvoiceNumber": "26112000000012345678",
        "Type": "打车",
    }

    first = extractor.preview_archive_target(str(source), payload)
    second = extractor.preview_archive_target(str(source), payload)

    assert first["status"] == "archived"
    assert first["target_folder"] == "打车"
    assert Path(first["planned_path"]).parent.name == "打车"
    assert Path(first["planned_path"]).name.startswith("2026-03-15_打车_103.00")
    assert first["planned_path"] != second["planned_path"], "batch duplicates need distinct previews"
    assert not output.exists() or not any(output.rglob("*"))

    unclear = extractor.preview_archive_target(
        str(source), {"is_invoice": True, "Type": "其他"}
    )
    assert unclear["status"] == "manual_check"
    assert "待人工复核" in unclear["planned_path"]


def test_flat_layout_archive_lands_in_the_output_root(tmp_path: Path):
    from invoice_extractor import InvoiceExtractor

    output = tmp_path / "output"
    extractor = InvoiceExtractor(api_key="", output_dir=str(output))
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4 stub")
    payload = {
        "is_invoice": True,
        "Date": "2026-11-07",
        "Seller": "广州市泷泽电子科技有限公司",
        "Amount": "220.67",
        "InvoiceNumber": "26442000012806743906",
        "Type": "充电",
    }

    preview = extractor.preview_archive_target(
        str(source), payload, flat_layout=True
    )
    assert preview["status"] == "archived"
    assert preview["target_folder"] == ""
    assert Path(preview["planned_path"]).parent == output
    assert Path(preview["planned_path"]).name.startswith("2026-11-07_充电_220.67_")

    success, final_path = extractor.route_and_rename_file(
        str(source), payload, flat_layout=True
    )
    assert success is True
    assert Path(final_path).parent == output
    assert Path(final_path).name.startswith("2026-11-07_充电_220.67_")
    # The category is kept in the file name only; no category subfolder is made.
    assert not (output / "充电").exists()


def test_local_organize_flat_layout_keeps_files_in_folder_root(tmp_path: Path):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)

    api = InvoiceAppAPI()
    _start_local(api, inbox, split_by_category=False)

    results = api.get_results()
    summary = results["organize_summary"]
    assert summary["split_by_category"] is False
    assert summary["in_place"] is True
    assert summary["archived_count"] >= 2
    # The layout choice is persisted with the rest of the local-mode settings.
    assert api.load_user_settings()["settings"]["local_split_by_category"] is False

    root_invoices = _root_invoice_files(inbox)
    assert root_invoices, "flat layout must keep archived files in the folder root"
    assert any("打车" in path.name for path in root_invoices), root_invoices
    for category_folder in ("打车", "餐饮", "充电", "其他"):
        assert not (inbox / category_folder).exists(), category_folder

    # Originals still leave the root, duplicates still go to duplicates/.
    raw_files = [
        path
        for path in inbox.rglob("*")
        if path.is_file() and "整理前发票" in path.parts
    ]
    assert {path.name for path in raw_files} == {"发票A.pdf", "发票B.xml"}
    duplicate_files = [
        path for path in inbox.rglob("*") if path.is_file() and "duplicates" in path.parts
    ]
    assert {path.name for path in duplicate_files} == {"发票C.xml"}

    # A second flat run recognises its own output and skips it instead of
    # treating it as new input (which would move it into duplicates/).
    _start_local(api, inbox, split_by_category=False)
    second = api.get_results()["organize_summary"]
    assert second["scanned_files"] == 0
    assert second["archived_count"] == 0
    assert second["raw_moved_count"] == 0
    assert second["duplicates_moved_count"] == 0
    assert sorted(path.name for path in _root_invoice_files(inbox)) == sorted(
        path.name for path in root_invoices
    )

    # Switching to 按分类分目录 re-lays-out the flat run's own output: the archived
    # files move into 打车/ instead of being skipped and left in the root forever.
    duplicates_before = sorted(
        path.relative_to(inbox).as_posix()
        for path in inbox.rglob("*")
        if path.is_file() and "duplicates" in path.parts
    )
    assert duplicates_before, "the flat run should have moved the duplicate aside"
    _start_local(api, inbox, split_by_category=True)
    third = api.get_results()["organize_summary"]
    assert third["split_by_category"] is True
    assert third["scanned_files"] == 0
    assert third["duplicates_moved_count"] == 0
    assert third["layout_migrated_count"] == 2
    assert _root_invoice_files(inbox) == []
    archived_under_category = [
        path for path in (inbox / "打车").rglob("*") if path.is_file()
    ]
    assert sorted(path.name for path in archived_under_category) == sorted(
        path.name for path in root_invoices
    )
    # The layout switch must not turn the previous archive files into duplicates.
    duplicates_after = sorted(
        path.relative_to(inbox).as_posix()
        for path in inbox.rglob("*")
        if path.is_file() and "duplicates" in path.parts
    )
    assert duplicates_after == duplicates_before


def test_local_organize_flat_layout_custom_output_stays_flat(tmp_path: Path):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    output = tmp_path / "output"

    api = InvoiceAppAPI()
    _start_local(api, inbox, output_dir=output, split_by_category=False)

    summary = api.get_results()["organize_summary"]
    assert summary["split_by_category"] is False
    assert summary["in_place"] is False
    assert _root_invoice_files(output), "flat archive must land in the output root"
    for category_folder in ("打车", "餐饮", "充电", "其他"):
        assert not (output / category_folder).exists(), category_folder
    # Custom-output runs keep the originals where the user left them.
    assert not (inbox / "整理前发票").exists()


class _FakeFetcher:
    instances: list["_FakeFetcher"] = []

    def __init__(self, email, auth_code, **kwargs):
        self.email = email
        self.auth_code = auth_code
        self.kwargs = kwargs
        self.staging_dir = kwargs.get("staging_dir") or ""
        self.connected = False
        self.certificate_error = False
        self.timeout_error = False
        _FakeFetcher.instances.append(self)

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def fetch_emails_by_date(self, since_date, before_date=None, mailbox="INBOX"):
        del since_date, before_date, mailbox
        return ["101", "102"]

    def extract_attachments(self, email_ids, mailbox="INBOX"):
        del email_ids
        staged = Path(self.staging_dir)
        staged.mkdir(parents=True, exist_ok=True)
        attachment = staged / "invoice.pdf"
        attachment.write_bytes(b"%PDF-1.4 fake invoice bytes")
        return [
            {
                "filepath": str(attachment),
                "tier": 2,
                "subject": "您的电子发票",
                "sender": "invoice@jd.com",
                "is_url": False,
                "email_id": "101",
                "original_filename": "增值税电子普通发票.pdf",
                "message_id": "<abc@jd.com>",
                "received_at": "2026-10-01T09:00:00+08:00",
                "mailbox": mailbox,
            },
            {
                "filepath": "https://example.invalid/download",
                "tier": 2,
                "subject": "发票下载链接",
                "sender": "invoice@jd.com",
                "is_url": True,
                "email_id": "102",
            },
        ]


def test_fetch_only_writes_inbox_manifest_and_never_parses(tmp_path: Path, monkeypatch):
    import email_fetcher
    from app_api import InvoiceAppAPI
    from run_coordinator import RunRequest

    monkeypatch.setattr(email_fetcher, "EmailFetcher", _FakeFetcher)
    _FakeFetcher.instances.clear()

    output = tmp_path / "output"
    api = InvoiceAppAPI()
    request = RunRequest(
        run_id="fetch-only-1",
        date_from="2026-10-01",
        date_to="2026-10-31",
        save_path=str(output),
        rules_text="",
        account_id="hash",
        channel_id="qq",
        source_mode="mail",
        fetch_only=True,
    )
    dependencies = api._build_run_dependencies(
        request,
        email_address="a@qq.com",
        auth_code="auth",
        api_key="",
        fetch_only=True,
    )
    fetcher = dependencies.connect(request)
    email_ids = dependencies.scan(fetcher, request)
    rows = dependencies.candidate(email_ids, request)

    assert rows == []
    inbox = output / "inbox"
    manifest = inbox / "manifest.jsonl"
    assert manifest.is_file()
    entries = [
        json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line
    ]
    assert len(entries) == 1
    assert entries[0]["source"] == "mail"
    assert entries[0]["uid"] == "101"
    assert entries[0]["message_id"] == "<abc@jd.com>"
    assert len(list(inbox.rglob("*.pdf"))) == 1
    assert (inbox / "fetch_todo.jsonl").is_file()
    assert dependencies.extract([], request) == []
    report = dependencies.archive([], request)
    assert report.can_complete is True
    assert api._last_fetch_summary["attachments"] == 1
    assert api._last_fetch_summary["todos"] == 1
    assert _FakeFetcher.instances and _FakeFetcher.instances[0].staging_dir


def test_start_fetch_only_requires_credentials(tmp_path: Path):
    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    missing = api.start_fetch_only(str(tmp_path), email_address="", auth_code="")
    assert missing["success"] is False
    assert "邮箱" in missing["message"]


# ---------------------------------------------------------------------------
# Architectural decoupling guards (feature ① / feature ② must not couple)
# ---------------------------------------------------------------------------

DECOUPLED_ORGANIZE_MODULES = (
    "organize_source.py",
    "local_organize.py",
    "fetch_handoff.py",
    "organize_cli.py",
)
MAILBOX_MODULES = {
    "email_fetcher",
    "email_channel",
    "mailbox_scanner",
    "imaplib",
    "provider_baiwang",
    "provider_direct_invoice",
}
PARSER_MODULES = {
    "invoice_extractor",
    "local_recognition",
    "candidate_pipeline",
    "extraction_pipeline",
    "app_api",
    "app_archive_adapter",
}


def _imported_modules(path: Path, *, top_level_only: bool) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    if top_level_only:
        nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    else:
        nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    for node in nodes:
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("module_name", DECOUPLED_ORGANIZE_MODULES)
def test_organize_modules_never_import_mailbox_code(module_name: str):
    path = Path(__file__).resolve().parents[1] / module_name
    imported = _imported_modules(path, top_level_only=False)
    assert not (imported & MAILBOX_MODULES), (
        f"{module_name} must stay usable without any mailbox configuration, "
        f"but imports {sorted(imported & MAILBOX_MODULES)}"
    )


@pytest.mark.parametrize("module_name", ("email_fetcher.py", "fetch_only.py"))
def test_fetch_modules_never_import_the_parser(module_name: str):
    path = Path(__file__).resolve().parents[1] / module_name
    imported = _imported_modules(path, top_level_only=True)
    assert not (imported & PARSER_MODULES), (
        f"{module_name} must not parse invoices, but imports "
        f"{sorted(imported & PARSER_MODULES)}"
    )


def test_organize_cli_defaults_to_same_folder_dry_run(tmp_path: Path, capsys):
    import organize_cli

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    before = sorted(path.relative_to(inbox).as_posix() for path in inbox.rglob("*") if path.is_file())

    exit_code = organize_cli.main(["organize", str(inbox), "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err

    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["output_dir"] == str(inbox.resolve())
    assert payload["scanned_files"] == 3
    assert payload["archived_count"] >= 2
    after = sorted(path.relative_to(inbox).as_posix() for path in inbox.rglob("*") if path.is_file())
    assert after == before, "CLI preview must not write or move files"


def test_organize_cli_apply_organizes_in_place(tmp_path: Path, capsys):
    import organize_cli

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)

    exit_code = organize_cli.main(["organize", str(inbox), "--apply", "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err

    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    assert payload["output_dir"] == str(inbox.resolve())
    assert payload["archived_count"] >= 2
    assert payload["raw_moved_count"] >= 2
    assert payload["duplicates_moved_count"] >= 1
    assert (inbox / "整理前发票").is_dir()
    assert (inbox / "duplicates").is_dir()
    assert not [
        path
        for path in inbox.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".xml", ".ofd"}
    ]

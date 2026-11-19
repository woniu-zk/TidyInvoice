"""The originals bucket keeps processed files exactly as the user had them.

Product requirement (user feedback): in-place organizing may keep originals in a
dedicated bucket, but those originals must be preserved verbatim — original file
name, original bytes, original sub-folder — instead of being renamed and sorted
into ``YYYY/MM`` month buckets. The bucket is named ``整理前发票/``; older builds
called it ``raw/`` and that legacy folder is renamed in place.
"""

from __future__ import annotations

import time
from pathlib import Path

ORIGINALS_DIRNAME = "整理前发票"


def _write_invoice_xml(path: Path, *, number: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _start_local(api, inbox: Path, *, dry_run: bool = False) -> dict:
    result = api.start_local_organize(str(inbox), dry_run=dry_run)
    assert result.get("success") is True, result
    deadline = time.monotonic() + 180.0
    while time.monotonic() < deadline:
        snapshot = api.get_progress()
        if snapshot.get("run_state") in {"completed", "failed"}:
            assert snapshot["run_state"] == "completed", snapshot
            return snapshot
        time.sleep(0.05)
    raise AssertionError(f"run did not finish: {api.get_progress()}")


def test_originals_bucket_keeps_names_bytes_and_subfolders(tmp_path: Path):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    top = _write_invoice_xml(inbox / "发票.xml", number="26112000000012345671")
    nested = _write_invoice_xml(
        inbox / "微信下载" / "发票.xml", number="26112000000012345672"
    )
    top_bytes, nested_bytes = top.read_bytes(), nested.read_bytes()

    api = InvoiceAppAPI()
    _start_local(api, inbox)

    summary = api.get_results()["organize_summary"]
    assert summary["in_place"] is True
    assert summary["raw_moved_count"] == 2
    assert api.get_results()["dry_run"] is False

    originals = inbox / ORIGINALS_DIRNAME
    # Original names and the original sub-folder are kept as they were; no
    # renamed ``_2`` copies and no month folders.
    assert {path.name for path in originals.iterdir()} == {"微信下载", "发票.xml"}
    assert (originals / "发票.xml").read_bytes() == top_bytes
    assert (originals / "微信下载" / "发票.xml").read_bytes() == nested_bytes
    assert not any(
        path.is_dir() and path.name.isdigit() for path in originals.iterdir()
    )
    assert not any("_2" in path.name for path in originals.rglob("*"))


def test_originals_bucket_never_renames_when_the_same_name_appears_again(
    tmp_path: Path,
):
    from app_api import InvoiceAppAPI
    from local_organize import LocalOrganizer, OrganizeRequest

    inbox = tmp_path / "inbox"
    first = _write_invoice_xml(inbox / "发票.xml", number="26112000000012345681")
    first_bytes = first.read_bytes()

    api = InvoiceAppAPI()
    LocalOrganizer(
        api, OrganizeRequest(input_dir=str(inbox), output_dir=str(inbox))
    ).run()
    assert (inbox / ORIGINALS_DIRNAME / "发票.xml").read_bytes() == first_bytes

    # A later download reuses the same file name with different content. The
    # organizer must not overwrite the first original and must not rename the
    # second one either.
    second = _write_invoice_xml(inbox / "发票.xml", number="26112000000012345682")
    second_bytes = second.read_bytes()
    result = LocalOrganizer(
        api, OrganizeRequest(input_dir=str(inbox), output_dir=str(inbox))
    ).run()

    assert result.raw_moved_count == 1
    assert any("同名" in warning for warning in result.warnings), result.warnings
    copies = sorted((inbox / ORIGINALS_DIRNAME).rglob("发票.xml"))
    assert len(copies) == 2, copies
    assert {path.read_bytes() for path in copies} == {first_bytes, second_bytes}
    assert all(path.name == "发票.xml" for path in copies)


def test_legacy_raw_bucket_is_renamed_to_the_product_name(tmp_path: Path):
    from local_organize import LocalOrganizer, OrganizeRequest

    inbox = tmp_path / "inbox"
    legacy_file = inbox / "raw" / "2026" / "11" / "旧版原件.pdf"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_bytes(b"%PDF-1.4 legacy original bytes")
    _write_invoice_xml(inbox / "新发票.xml", number="26112000000012345701")

    from app_api import InvoiceAppAPI

    api = InvoiceAppAPI()
    result = LocalOrganizer(
        api, OrganizeRequest(input_dir=str(inbox), output_dir=str(inbox))
    ).run()

    originals = inbox / ORIGINALS_DIRNAME
    assert originals.is_dir()
    assert not (inbox / "raw").exists()
    assert result.raw_moved_count == 1
    # The legacy bucket is only renamed: its files keep their names, bytes, and
    # old placement; the new original lands next to it with its own name.
    assert (originals / "2026" / "11" / "旧版原件.pdf").read_bytes() == (
        b"%PDF-1.4 legacy original bytes"
    )
    assert (originals / "新发票.xml").is_file()
    assert any("已改名为「整理前发票」" in warning for warning in result.warnings)


def test_legacy_raw_is_left_alone_when_the_current_bucket_exists(tmp_path: Path):
    from app_api import InvoiceAppAPI
    from local_organize import LocalOrganizer, OrganizeRequest

    inbox = tmp_path / "inbox"
    legacy_file = inbox / "raw" / "旧版原件.pdf"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_bytes(b"%PDF-1.4 legacy untouched")
    current_file = inbox / ORIGINALS_DIRNAME / "已有原件.pdf"
    current_file.parent.mkdir(parents=True)
    current_file.write_bytes(b"%PDF-1.4 current untouched")
    _write_invoice_xml(inbox / "新发票.xml", number="26112000000012345702")

    api = InvoiceAppAPI()
    result = LocalOrganizer(
        api, OrganizeRequest(input_dir=str(inbox), output_dir=str(inbox))
    ).run()

    # Two buckets are never merged automatically; the legacy one stays put and
    # the run says so instead of touching either bucket.
    assert legacy_file.read_bytes() == b"%PDF-1.4 legacy untouched"
    assert current_file.read_bytes() == b"%PDF-1.4 current untouched"
    assert any("未自动改名合并" in warning for warning in result.warnings)
    assert (inbox / ORIGINALS_DIRNAME / "新发票.xml").is_file()


def test_cli_reports_verbatim_originals_bucket(tmp_path: Path, capsys):
    import organize_cli

    inbox = tmp_path / "inbox"
    _write_invoice_xml(inbox / "发票.xml", number="26112000000012345691")

    exit_code = organize_cli.main(["organize", str(inbox), "--apply"])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert "整理前发票" in captured.out
    assert (inbox / ORIGINALS_DIRNAME / "发票.xml").is_file()

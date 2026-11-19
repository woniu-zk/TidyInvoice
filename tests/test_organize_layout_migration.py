"""Tests for archive layout re-migration in the local folder organizer.

Reported bug: the first in-place organize run with 按分类分目录 unchecked archives
flat into the folder root; ticking the checkbox and organizing again did nothing
because the scanner silently skipped the organizer's own output. ``organize_layout``
now re-lays-out those archive files to match the requested layout before scanning,
so neither direction of the split_by_category switch leaves the folder in the
previous layout.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

import organize_layout
from document_types import DOCUMENT_TYPES

# The public contract of organize_layout: archive suffixes the organizer can emit.
SUPPORTED_LAYOUT_SUFFIXES = (
    ".pdf",
    ".ofd",
    ".xml",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
)

# <date>_<display-type>_<amount>_<seller><ext> names the organizer produces.
STANDARD_CATEGORY_NAMES = (
    ("20260315_打车_103.00_上海滴滴出行科技有限公司.pdf", "打车"),
    ("20260315_餐饮_45.50_某餐厅.xml", "餐饮"),
    ("2026-03-15_打车_103.00_滴滴.pdf", "打车"),
    ("2026年03月15日_餐饮_45.50_某餐厅.ofd", "餐饮"),
    ("20260315_打车行程单_103.00_滴滴.pdf", "打车"),
    ("20260315_住宿水单_103.00_某酒店.pdf", "住宿发票"),
    ("20260315_住宿确认单_103.00_某酒店.pdf", "住宿发票"),
)

# <date>-<dep>-<dest>-火车票<ext> names the organizer produces for train tickets.
TRAIN_NAMES = (
    "20260315-上海-北京-火车票.pdf",
    "2026-03-15-上海-北京-火车票.pdf",
)

# Paired-archive renames (archive_pairing.build_*_pair_renames): the organizer's
# own output; the category is recovered from the platform/role token.
PAIRED_NAMES = (
    ("0315-滴滴-01-发票_103.00元.pdf", "打车"),
    ("0315-高德-02-行程单_103.00元.pdf", "打车"),
    ("20260315-住宿-01-水单_88.00元.pdf", "住宿发票"),
    ("20260315-住宿-01-发票_88.00元.pdf", "住宿发票"),
)

# Paired-shaped but no usable category token: recognized, category not derivable.
PAIRED_UNCATEGORIZED_NAMES = (
    "0315-某平台-01-发票_103.00元.pdf",
)

# Anything the organizer did not produce (or cannot re-layout) must be rejected.
REJECTED_NAMES = (
    "说明.txt",
    "发票A.pdf",
    "20260315_未知类型_103.00_x.pdf",
    "20260315_打车_103.00_滴滴.xlsx",
    "20260315_打车_103.00_滴滴",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write(path: Path, payload: bytes = b"payload") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _tree(root: Path) -> list[tuple[str, bool, bytes]]:
    """Deterministic snapshot of files/directories below ``root``."""
    snapshot: list[tuple[str, bool, bytes]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot.append((relative, True, b""))
        else:
            snapshot.append((relative, False, path.read_bytes()))
    return snapshot


def _file_bytes_under(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ---- API-level helpers, copied from tests/test_organize_local_mode.py ---------

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


# ---------------------------------------------------------------------------
# a. name recognition
# ---------------------------------------------------------------------------


def test_supported_layout_suffixes_contract():
    assert tuple(organize_layout.SUPPORTED_LAYOUT_SUFFIXES) == SUPPORTED_LAYOUT_SUFFIXES


def test_category_folder_names_come_from_the_document_type_registry_only():
    expected = frozenset(
        str(entry.get("archive_folder") or "").strip()
        for entry in DOCUMENT_TYPES.values()
        if str(entry.get("archive_folder") or "").strip()
    )
    names = organize_layout.category_folder_names()

    assert isinstance(names, frozenset)
    assert names == expected
    assert {"打车", "餐饮", "火车票", "住宿发票"} <= names
    # Tool buckets are not categories and must never be planned as targets.
    assert not names & {
        "整理前发票",
        "raw",
        "duplicates",
        "待人工复核",
        "人工复核",
        "_audit_retention",
        ".local-staging",
    }


@pytest.mark.parametrize(("name", "category"), STANDARD_CATEGORY_NAMES)
def test_organized_output_category_recognizes_standard_archive_names(name, category):
    assert organize_layout.organized_output_category(name) == category
    assert organize_layout.is_organized_output_name(name) is True


@pytest.mark.parametrize("name", TRAIN_NAMES)
def test_organized_output_category_recognizes_train_ticket_names(name):
    assert organize_layout.organized_output_category(name) == "火车票"
    assert organize_layout.is_organized_output_name(name) is True


@pytest.mark.parametrize(("name", "category"), PAIRED_NAMES)
def test_paired_archive_names_recover_the_category_from_platform_tokens(
    name, category
):
    assert organize_layout.organized_output_category(name) == category
    assert organize_layout.is_organized_output_name(name) is True


@pytest.mark.parametrize("name", PAIRED_UNCATEGORIZED_NAMES)
def test_paired_names_without_a_category_token_stay_uncategorized(name):
    assert organize_layout.organized_output_category(name) is None
    assert organize_layout.is_organized_output_name(name) is True


@pytest.mark.parametrize("name", REJECTED_NAMES)
def test_non_organizer_names_are_rejected(name):
    assert organize_layout.organized_output_category(name) is None
    assert organize_layout.is_organized_output_name(name) is False


def test_organized_output_name_regex_matches_exactly_the_organizer_output():
    pattern = organize_layout.organized_output_name_re()

    assert isinstance(pattern, re.Pattern)
    accepted = (
        [name for name, _category in STANDARD_CATEGORY_NAMES]
        + list(TRAIN_NAMES)
        + [name for name, _category in PAIRED_NAMES]
        + list(PAIRED_UNCATEGORIZED_NAMES)
    )
    for name in accepted:
        assert pattern.match(name) is not None, name
        assert organize_layout.is_organized_output_name(name) is True, name
    for name in REJECTED_NAMES:
        assert pattern.match(name) is None, name
        assert organize_layout.is_organized_output_name(name) is False, name


# ---------------------------------------------------------------------------
# b. enforce_layout unit tests
# ---------------------------------------------------------------------------


def test_enforce_layout_moves_flat_archive_files_into_category_folders(tmp_path: Path):
    root = tmp_path / "archive"
    taxi = _write(root / "20260315_打车_103.00_上海滴滴出行科技有限公司.pdf", b"taxi-pdf")
    dining = _write(root / "20260315_餐饮_45.50_某餐厅.xml", b"dining-xml")
    train = _write(root / "20260315-上海-北京-火车票.pdf", b"train-pdf")
    note = _write(root / "说明.txt", b"not an invoice")
    user_invoice = _write(root / "发票A.pdf", b"user invoice")
    unknown = _write(root / "20260315_未知类型_103.00_x.pdf", b"unknown category")
    user_folder_file = _write(root / "客户资料" / "合同.pdf", b"user contract")
    # A recognized name that is not directly inside the archive root must stay put.
    nested_archive = _write(
        root / "客户资料" / "20260315_打车_103.00_滴滴.pdf", b"nested"
    )

    migration = organize_layout.enforce_layout(str(root), split_by_category=True)

    assert isinstance(migration, organize_layout.LayoutMigration)
    assert migration.layout == "category"
    assert migration.dry_run is False
    assert migration.moved_count == 3
    assert migration.planned_count == 3
    assert len(migration.moved) == len(migration.planned) == 3
    assert all(
        Path(source).is_absolute() and Path(target).is_absolute()
        for source, target in migration.moved
    )

    expected_targets = {
        taxi.name: (root / "打车" / taxi.name, b"taxi-pdf"),
        dining.name: (root / "餐饮" / dining.name, b"dining-xml"),
        train.name: (root / "火车票" / train.name, b"train-pdf"),
    }
    for target, payload in expected_targets.values():
        assert target.is_file(), target
        assert target.read_bytes() == payload, target
    assert {Path(target).name for _source, target in migration.moved} == set(
        expected_targets
    )
    for source in (taxi, dining, train):
        assert not source.exists(), source

    # User content is never touched by the re-layout.
    assert note.read_bytes() == b"not an invoice"
    assert user_invoice.read_bytes() == b"user invoice"
    assert user_folder_file.read_bytes() == b"user contract"
    assert nested_archive.read_bytes() == b"nested"
    assert unknown.read_bytes() == b"unknown category"
    assert (root / "未知类型").exists() is False

    # Idempotent: the same layout never moves anything a second time.
    second = organize_layout.enforce_layout(str(root), split_by_category=True)
    assert second.moved_count == 0
    assert second.planned_count == 0


def test_enforce_layout_flattens_category_folders_and_prunes_empty_ones(tmp_path: Path):
    root = tmp_path / "archive"
    taxi_standard = _write(
        root / "打车" / "20260315_打车_103.00_上海滴滴出行科技有限公司.pdf", b"taxi-standard"
    )
    taxi_paired = _write(root / "打车" / "0315-滴滴-01-发票_103.00元.pdf", b"taxi-paired")
    hotel_standard = _write(
        root / "住宿发票" / "20260315_住宿水单_88.00_某酒店.pdf", b"hotel-standard"
    )
    # A user file inside a category folder is not organizer output: keep it there.
    category_user_file = _write(root / "餐饮" / "说明.txt", b"user note")
    review = _write(root / "待人工复核" / "x.pdf", b"review")
    raw = _write(root / "raw" / "y.pdf", b"raw original")
    duplicate = _write(root / "duplicates" / "z.pdf", b"duplicate original")
    user_file = _write(root / "user.pdf", b"user invoice")

    migration = organize_layout.enforce_layout(str(root), split_by_category=False)

    assert migration.layout == "flat"
    assert migration.dry_run is False
    assert migration.moved_count == 3
    assert migration.planned_count == 3
    expected_names = {taxi_standard.name, taxi_paired.name, hotel_standard.name}
    assert {Path(target).name for _source, target in migration.moved} == expected_names
    assert all(Path(target).parent == root for _source, target in migration.moved)
    moved_contents = {
        taxi_standard.name: b"taxi-standard",
        taxi_paired.name: b"taxi-paired",
        hotel_standard.name: b"hotel-standard",
    }
    for name, payload in moved_contents.items():
        assert (root / name).read_bytes() == payload, name
    for source in (taxi_standard, taxi_paired, hotel_standard):
        assert not source.exists(), source
    # Known category folders that the flat layout left empty are pruned.
    assert not (root / "打车").exists()
    assert not (root / "住宿发票").exists()

    # Untouched buckets / user files.
    assert category_user_file.read_bytes() == b"user note"
    assert (root / "餐饮").is_dir(), "a category folder holding a user file must stay"
    assert review.read_bytes() == b"review"
    assert raw.read_bytes() == b"raw original"
    assert duplicate.read_bytes() == b"duplicate original"
    assert user_file.read_bytes() == b"user invoice"

    # Idempotent: flattening again moves nothing (the files are already in the root).
    second = organize_layout.enforce_layout(str(root), split_by_category=False)
    assert second.moved_count == 0
    assert second.planned_count == 0


def test_enforce_layout_dry_run_plans_category_moves_without_writing(tmp_path: Path):
    root = tmp_path / "archive"
    flat_archive = _write(
        root / "20260315_打车_103.00_上海滴滴出行科技有限公司.pdf", b"flat archive"
    )
    _write(root / "说明.txt", b"note")
    before = _tree(root)

    migration = organize_layout.enforce_layout(
        str(root), split_by_category=True, dry_run=True
    )

    assert migration.layout == "category"
    assert migration.dry_run is True
    assert migration.moved_count == 0
    assert migration.planned_count == 1
    (source, target), = migration.planned
    assert Path(source) == flat_archive
    assert Path(target) == root / "打车" / flat_archive.name
    # dry-run must not move files, create directories or even mkdir the target.
    assert not (root / "打车").exists()
    assert _tree(root) == before


def test_enforce_layout_dry_run_plans_flat_moves_without_writing(tmp_path: Path):
    root = tmp_path / "archive"
    categorized = _write(
        root / "打车" / "20260315_打车_103.00_上海滴滴出行科技有限公司.pdf", b"categorized"
    )
    before = _tree(root)

    migration = organize_layout.enforce_layout(
        str(root), split_by_category=False, dry_run=True
    )

    assert migration.layout == "flat"
    assert migration.dry_run is True
    assert migration.moved_count == 0
    assert migration.planned_count == 1
    assert (root / "打车" / categorized.name).is_file()
    assert not (root / categorized.name).exists()
    assert _tree(root) == before


def test_enforce_layout_flat_collision_renames_without_overwriting(tmp_path: Path):
    root = tmp_path / "archive"
    name = "20260315_打车_103.00_上海滴滴出行科技有限公司.pdf"
    root_copy = _write(root / name, b"already in the root")
    categorized_copy = _write(root / "打车" / name, b"archived in the category folder")

    migration = organize_layout.enforce_layout(str(root), split_by_category=False)

    assert migration.moved_count == 1
    (source, target), = migration.moved
    assert Path(source) == categorized_copy
    assert Path(target) == root / "20260315_打车_103.00_上海滴滴出行科技有限公司_2.pdf"
    assert root_copy.read_bytes() == b"already in the root"
    assert Path(target).read_bytes() == b"archived in the category folder"
    assert not categorized_copy.exists()
    # The category folder became empty after the move and is pruned.
    assert not (root / "打车").exists()


def test_enforce_layout_keeps_unknown_category_root_files_in_place(tmp_path: Path):
    root = tmp_path / "archive"
    _write(root / "20260315_未知类型_103.00_x.pdf", b"unknown category")
    _write(root / "说明.txt", b"note")
    before = _tree(root)

    migration = organize_layout.enforce_layout(str(root), split_by_category=True)

    assert migration.layout == "category"
    assert migration.moved_count == 0
    assert migration.planned_count == 0
    assert _tree(root) == before
    assert not (root / "未知类型").exists()


def test_enforce_layout_files_paired_archive_names_into_category_folders(
    tmp_path: Path,
):
    root = tmp_path / "archive"
    ride_invoice = _write(root / "0315-滴滴-01-发票_103.00元.pdf", b"ride-invoice")
    ride_itinerary = _write(root / "0315-滴滴-01-行程单_103.00元.pdf", b"ride-itinerary")
    hotel_folio = _write(root / "20260315-住宿-01-水单_88.00元.pdf", b"hotel-folio")
    # No category token: recognized output, but it must stay in place (never lost).
    uncategorized = _write(root / "0315-某平台-01-发票_103.00元.pdf", b"unknown")

    migration = organize_layout.enforce_layout(str(root), split_by_category=True)

    assert migration.moved_count == 3
    assert (root / "打车" / ride_invoice.name).read_bytes() == b"ride-invoice"
    assert (root / "打车" / ride_itinerary.name).read_bytes() == b"ride-itinerary"
    assert (root / "住宿发票" / hotel_folio.name).read_bytes() == b"hotel-folio"
    assert uncategorized.read_bytes() == b"unknown"


def _directory_link_or_skip(target: Path, link: Path) -> None:
    """Create a directory symlink/junction, or skip when the OS forbids it."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks/junctions are not available in this environment")


def test_enforce_layout_never_writes_through_a_linked_category_folder(
    tmp_path: Path,
):
    root = tmp_path / "archive"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    archive = _write(root / "20260315_打车_103.00_上海滴滴出行科技有限公司.pdf", b"archive")
    _directory_link_or_skip(outside, root / "打车")

    migration = organize_layout.enforce_layout(str(root), split_by_category=True)

    assert migration.moved_count == 0
    assert archive.read_bytes() == b"archive"
    assert not list(outside.iterdir()), "nothing may be written outside the archive root"


def test_enforce_layout_never_flattens_through_a_linked_category_folder(
    tmp_path: Path,
):
    root = tmp_path / "archive"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_archive = _write(
        outside / "20260315_打车_103.00_上海滴滴出行科技有限公司.pdf", b"outside archive"
    )
    _directory_link_or_skip(outside, root / "打车")

    migration = organize_layout.enforce_layout(str(root), split_by_category=False)

    assert migration.moved_count == 0
    assert outside_archive.read_bytes() == b"outside archive"
    assert not (root / outside_archive.name).exists()
    # The link itself is not a category folder: it must not be pruned.
    assert (root / "打车").exists()


# ---------------------------------------------------------------------------
# c. API end-to-end tests: the user-reported flow on one and the same folder
# ---------------------------------------------------------------------------


def test_local_organize_flat_run_then_category_run_relayouts_archives(
    tmp_path: Path,
):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    api = InvoiceAppAPI()

    # First organize: 按分类分目录 unchecked -> archived invoices stay in the root.
    _start_local(api, inbox, split_by_category=False)
    flat_summary = api.get_results()["organize_summary"]
    assert flat_summary["split_by_category"] is False
    assert flat_summary["layout_migrated_count"] == 0
    assert flat_summary["layout_planned_count"] == 0
    root_archives = _root_invoice_files(inbox)
    assert len(root_archives) == 2, root_archives
    assert all("打车" in path.name for path in root_archives), root_archives
    assert not (inbox / "打车").exists()
    raw_before = _file_bytes_under(inbox / "整理前发票")
    duplicates_before = _file_bytes_under(inbox / "duplicates")
    assert raw_before, "flat run must still relocate the originals into 整理前发票/"
    assert duplicates_before, "flat run must still relocate the duplicate"

    # Second organize: tick 按分类分目录 -> the flat archive files are re-laid-out
    # into 打车/ before scanning; nothing is re-scanned or duplicated.
    _start_local(api, inbox, split_by_category=True)
    results = api.get_results()
    summary = results["organize_summary"]
    assert summary["split_by_category"] is True
    assert summary["in_place"] is True
    assert summary["scanned_files"] == 0
    assert summary["layout_migrated_count"] == 2
    # An applied run reports moves, not a dry-run preview.
    assert summary["layout_planned_count"] == 0
    assert summary["duplicates_moved_count"] == 0
    assert _root_invoice_files(inbox) == [], "the folder root must be clean now"

    categorized = [path for path in (inbox / "打车").rglob("*") if path.is_file()]
    assert sorted(path.name for path in categorized) == sorted(
        path.name for path in root_archives
    )
    assert len(categorized) == 2
    assert _file_bytes_under(inbox / "整理前发票") == raw_before
    assert _file_bytes_under(inbox / "duplicates") == duplicates_before

    # A following category run is a no-op.
    _start_local(api, inbox, split_by_category=True)
    third = api.get_results()["organize_summary"]
    assert third["layout_migrated_count"] == 0
    assert third["scanned_files"] == 0
    assert _root_invoice_files(inbox) == []
    assert sorted(path.name for path in categorized) == sorted(
        path.name
        for path in (inbox / "打车").rglob("*")
        if path.is_file()
    )


def test_local_organize_category_run_then_flat_run_relayouts_archives(tmp_path: Path):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    api = InvoiceAppAPI()

    # First organize: 按分类分目录 checked -> archived into 打车/.
    _start_local(api, inbox, split_by_category=True)
    first = api.get_results()["organize_summary"]
    assert first["layout_migrated_count"] == 0
    assert first["archived_count"] >= 2
    assert _root_invoice_files(inbox) == []
    categorized_archives = [
        path.name for path in (inbox / "打车").rglob("*") if path.is_file()
    ]
    assert len(categorized_archives) == 2, categorized_archives
    raw_before = _file_bytes_under(inbox / "整理前发票")
    duplicates_before = _file_bytes_under(inbox / "duplicates")

    # Second organize: 按分类分目录 unchecked -> the archive files move back to
    # the root and the now-empty category folder disappears.
    _start_local(api, inbox, split_by_category=False)
    summary = api.get_results()["organize_summary"]
    assert summary["split_by_category"] is False
    assert summary["in_place"] is True
    assert summary["layout_migrated_count"] == 2
    assert summary["layout_planned_count"] == 0
    assert summary["scanned_files"] == 0
    assert summary["duplicates_moved_count"] == 0
    assert not (inbox / "打车").exists()
    assert sorted(path.name for path in _root_invoice_files(inbox)) == sorted(
        categorized_archives
    )
    assert _file_bytes_under(inbox / "整理前发票") == raw_before
    assert _file_bytes_under(inbox / "duplicates") == duplicates_before

    # A following flat run is a no-op.
    _start_local(api, inbox, split_by_category=False)
    third = api.get_results()["organize_summary"]
    assert third["layout_migrated_count"] == 0
    assert third["scanned_files"] == 0
    assert sorted(path.name for path in _root_invoice_files(inbox)) == sorted(
        categorized_archives
    )


def test_local_organize_dry_run_previews_layout_migration_without_moving(
    tmp_path: Path,
):
    from app_api import InvoiceAppAPI

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    flat_archive = _write(
        inbox / "20260315_餐饮_45.50_某餐厅.xml",
        b"<Invoice>archive left by an earlier flat run</Invoice>",
    )
    before = _tree(inbox)

    api = InvoiceAppAPI()
    _start_local(api, inbox, dry_run=True)

    results = api.get_results()
    summary = results["organize_summary"]
    assert results["dry_run"] is True
    assert summary["layout_migrated_count"] == 0
    assert summary["layout_planned_count"] == 1
    assert not (inbox / "餐饮").exists()
    assert flat_archive.is_file()
    assert _tree(inbox) == before


# ---------------------------------------------------------------------------
# CLI JSON contract: the layout counters are part of the scriptable payload.
# ---------------------------------------------------------------------------


def test_organize_cli_json_exposes_layout_migration_counts(tmp_path: Path, capsys):
    import organize_cli

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    flat_archive = _write(
        inbox / "20260315_餐饮_45.50_某餐厅.xml",
        b"<Invoice>archive left by an earlier flat run</Invoice>",
    )

    exit_code = organize_cli.main(["organize", str(inbox), "--apply", "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err

    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["layout_migrated_count"] == 1
    # Apply runs report moves; the dry-run-only preview counter stays 0.
    assert payload["layout_planned_count"] == 0
    assert payload["archived_count"] >= 2
    assert (inbox / "餐饮" / flat_archive.name).is_file()


def test_organize_cli_json_dry_run_reports_planned_layout_migration(
    tmp_path: Path, capsys
):
    import organize_cli

    inbox = tmp_path / "inbox"
    _build_inbox(inbox)
    flat_archive = _write(
        inbox / "20260315_餐饮_45.50_某餐厅.xml",
        b"<Invoice>archive left by an earlier flat run</Invoice>",
    )
    before = _tree(inbox)

    exit_code = organize_cli.main(["organize", str(inbox), "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err

    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["layout_migrated_count"] == 0
    assert payload["layout_planned_count"] == 1
    assert flat_archive.is_file()
    assert not (inbox / "餐饮").exists()
    assert _tree(inbox) == before

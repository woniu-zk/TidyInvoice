"""Contract tests for the fetch -> organize handoff and the local folder scanner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fetch_handoff
import organize_source


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_inbox_writer_saves_attachment_and_manifest_entry(tmp_path: Path):
    inbox = tmp_path / "inbox"
    source = _write(tmp_path / "staged" / "增值税电子普通发票.pdf", b"%PDF-1.4 invoice")
    writer = fetch_handoff.InboxWriter(inbox)

    entry = writer.save_attachment(
        source,
        orig_name="增值税电子普通发票.pdf",
        metadata={
            "mailbox": "QQ",
            "uid": "4567",
            "uidvalidity": "1234567890",
            "message_id": "<abc@jd.com>",
            "msg_part": "2",
            "subject": "您的电子发票已开具",
            "sender": "invoice@jd.com",
            "received_at": "2026-10-01T09:00:00+08:00",
        },
    )

    assert entry.sha256 == fetch_handoff.sha256_file(source)
    assert entry.rel_path == f"2026/10/{entry.sha256[:8]}_增值税电子普通发票.pdf"
    stored = inbox / entry.rel_path
    assert stored.read_bytes() == source.read_bytes()
    assert entry.mailbox == "QQ"
    assert entry.uid == "4567"
    assert entry.message_id == "<abc@jd.com>"
    assert entry.received_at.startswith("2026-10-01")
    assert entry.ext == "pdf"
    assert entry.size == len(b"%PDF-1.4 invoice")

    lines = (inbox / fetch_handoff.MANIFEST_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["sha256"] == entry.sha256
    assert payload["source"] == "mail"
    assert payload["subject"] == "您的电子发票已开具"

    # Idempotent: same bytes never create a second file or manifest line.
    again = writer.save_attachment(source, orig_name="增值税电子普通发票.pdf")
    assert again == entry
    lines_after = (inbox / fetch_handoff.MANIFEST_FILENAME).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines_after) == 1
    archived = sorted(path for path in inbox.rglob("*") if path.is_file())
    assert archived == sorted([inbox / fetch_handoff.MANIFEST_FILENAME, stored])


def test_inbox_writer_is_idempotent_across_instances(tmp_path: Path):
    inbox = tmp_path / "inbox"
    source = _write(tmp_path / "a.xml", b"<Invoice/>")
    first = fetch_handoff.InboxWriter(inbox).save_attachment(source, orig_name="a.xml")

    second = fetch_handoff.InboxWriter(inbox)
    assert second.existing(first.sha256) is not None
    entry = second.save_attachment(source, orig_name="a.xml")
    assert entry.sha256 == first.sha256
    assert len(inbox.joinpath(fetch_handoff.MANIFEST_FILENAME).read_text("utf-8").splitlines()) == 1


def test_read_manifest_tolerates_broken_lines(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    good = {
        "sha256": "a" * 64,
        "rel_path": "2026/10/aaaaaaaa_a.pdf",
        "orig_name": "a.pdf",
        "ext": "pdf",
        "size": 3,
        "source": "mail",
    }
    manifest.write_text(
        json.dumps(good) + "\n"
        "not-json\n"
        "{}\n"
        + json.dumps({**good, "sha256": "B" * 64}) + "\n",
        encoding="utf-8",
    )

    entries, warnings = fetch_handoff.read_manifest(manifest)

    # Hand-editable contract: uppercase digests are normalised, broken lines are
    # reported instead of aborting the whole inbox.
    assert [entry.sha256 for entry in entries] == ["a" * 64, "b" * 64]
    assert len(warnings) == 2


def test_manifest_offset_and_todo_and_state(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    writer = fetch_handoff.InboxWriter(inbox)
    writer.save_attachment(_write(tmp_path / "x.png", b"png"), orig_name="x.png")
    writer.record_todo({"kind": "portal_link", "url_sha256": "b" * 64})
    writer.save_state({"mail.qq": {"uidvalidity": "1", "uids": ["1", "2"]}})

    todo_lines = inbox.joinpath(fetch_handoff.FETCH_TODO_FILENAME).read_text("utf-8").splitlines()
    assert json.loads(todo_lines[0])["kind"] == "portal_link"
    state = fetch_handoff.load_fetch_state(inbox / fetch_handoff.FETCH_STATE_FILENAME)
    assert state["mail.qq"]["uids"] == ["1", "2"]


def test_date_bucket_tolerates_bad_timestamp():
    assert fetch_handoff.date_bucket("2026-10-01T09:00:00+08:00").startswith("2026/10")
    assert fetch_handoff.date_bucket("not-a-date").count("/") == 1


def _build_local_tree(root: Path) -> dict[str, Path]:
    files = {
        "a": _write(root / "发票A.pdf", b"%PDF-1.4 alpha"),
        "b": _write(root / "2026" / "发票B.ofd", b"OFD beta"),
        "dup": _write(root / "backup" / "发票A-copy.pdf", b"%PDF-1.4 alpha"),
        "unsupported": _write(root / "说明.docx", b"word"),
        "state": _write(root / "processed_records.json", b"{}"),
    }
    _write(root / "_audit_retention" / "retained.pdf", b"%PDF-1.4 retained")
    _write(root / "待人工复核" / "manual.pdf", b"%PDF-1.4 manual")
    return files


def test_scan_local_directory_dedupes_and_reads_manifest(tmp_path: Path):
    tree = _build_local_tree(tmp_path)
    manifest_sha = fetch_handoff.sha256_file(tree["a"])
    fetch_handoff.append_manifest(
        tmp_path / fetch_handoff.MANIFEST_FILENAME,
        [
            fetch_handoff.ManifestEntry(
                sha256=manifest_sha,
                rel_path="发票A.pdf",
                orig_name="发票A.pdf",
                ext="pdf",
                size=tree["a"].stat().st_size,
                source="mail",
                mailbox="QQ",
                uid="4567",
                message_id="<a@b>",
                subject="电子发票",
                sender="invoice@jd.com",
                received_at="2026-10-01T09:00:00+08:00",
            )
        ],
    )

    scan = organize_source.scan_local_directory(tmp_path)

    assert scan.file_count == 2
    assert scan.skipped_duplicates == 1
    assert scan.skipped_unsupported == 1
    paths = [Path(document.path).name for document in scan.documents]
    assert paths == ["发票A.pdf", "发票B.ofd"]
    first = scan.documents[0]
    assert first.source == "mail"
    assert first.provenance["uid"] == "4567"

    rows = scan.to_attachment_rows()
    assert rows[0]["filepath"] == str(tree["a"].resolve())
    assert rows[0]["source"] == "mail"
    assert rows[0]["email_id"] == "4567"
    assert rows[0]["subject"] == "电子发票"
    assert rows[0]["is_url"] is False
    assert rows[1]["source"] == "local"
    assert rows[1]["email_id"] == "local-1"


def test_scan_local_directory_reports_manifest_file_missing(tmp_path: Path):
    _write(tmp_path / "a.pdf", b"%PDF-1.4 alpha")
    fetch_handoff.append_manifest(
        tmp_path / fetch_handoff.MANIFEST_FILENAME,
        [
            fetch_handoff.ManifestEntry(
                sha256="c" * 64,
                rel_path="gone.pdf",
                orig_name="gone.pdf",
                ext="pdf",
                size=3,
            )
        ],
    )

    scan = organize_source.scan_local_directory(tmp_path)

    assert scan.file_count == 1
    assert scan.manifest_entries == 1
    assert any("gone.pdf" in warning for warning in scan.warnings)


def test_scan_local_directory_excludes_output_root(tmp_path: Path):
    inbox = tmp_path / "inbox"
    output = tmp_path / "output"
    _write(inbox / "a.pdf", b"%PDF-1.4 alpha")
    _write(output / "打车" / "archived.pdf", b"%PDF-1.4 archived")
    _write(output / "b.ofd", b"OFD beta")

    scan = organize_source.scan_local_directory(inbox, exclude_paths=[output])

    assert scan.file_count == 1
    assert Path(scan.documents[0].path) == inbox.joinpath("a.pdf").resolve()


def test_scan_local_directory_excludes_root_child_dirs_only(tmp_path: Path):
    root = tmp_path / "inbox"
    _write(root / "a.pdf", b"%PDF-1.4 alpha")
    _write(root / "raw" / "2026" / "01" / "original.pdf", b"%PDF-1.4 original")
    # A same-named folder deeper in the tree is user content, not our output.
    _write(root / "phone" / "raw" / "nested.pdf", b"%PDF-1.4 nested")

    scan = organize_source.scan_local_directory(
        root, exclude_root_child_dir_names={"raw", "duplicates", "打车"}
    )

    paths = sorted(Path(document.path).name for document in scan.documents)
    assert paths == ["a.pdf", "nested.pdf"]


def test_scan_local_directory_rejects_missing_root(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        organize_source.scan_local_directory(tmp_path / "missing")

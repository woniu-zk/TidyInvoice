"""Mailbox fetch-only runner (product feature ①): email -> inbox + manifest.

Only this module (and the app's GUI bridge) imports the IMAP fetcher. It never
parses an invoice: the handoff is "files + metadata", so the result can be used by
``local_organize`` or by any other tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import os
import shutil
import tempfile
from typing import Any, Callable

import fetch_handoff


@dataclass(frozen=True)
class FetchOnlyRequest:
    email_address: str
    auth_code: str
    output_dir: str
    date_from: str = ""
    date_to: str = ""
    mailbox: str = "INBOX"
    imap_host: str = ""
    imap_port: int = 0


@dataclass
class FetchOnlyResult:
    ok: bool
    message: str = ""
    error_reason: str = ""
    email_count: int = 0
    attachment_count: int = 0
    saved_count: int = 0
    duplicate_count: int = 0
    link_count: int = 0
    inbox_dir: str = ""
    manifest_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachments": int(self.saved_count),
            "inbox_dir": self.inbox_dir,
            "manifest_path": self.manifest_path,
            "todos": int(self.link_count),
        }


@dataclass
class InboxSaveSummary:
    saved_count: int = 0
    duplicate_count: int = 0
    link_count: int = 0
    inbox_dir: str = ""
    manifest_path: str = ""
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachments": int(self.saved_count),
            "inbox_dir": self.inbox_dir,
            "manifest_path": self.manifest_path,
            "todos": int(self.link_count),
        }


def _stable_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()


def _iso_date_bounds(request: FetchOnlyRequest) -> tuple[str, str]:
    today = datetime.now().date()

    def parse(value: str, fallback: date) -> date:
        text = str(value or "").strip()
        if not text:
            return fallback
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return fallback

    since = parse(request.date_from, today - timedelta(days=30))
    before = parse(request.date_to, today) + timedelta(days=1)
    return since.strftime("%Y-%m-%d"), before.strftime("%Y-%m-%d")


def save_fetch_rows(
    output_dir: str,
    rows: list[dict[str, Any]],
    *,
    mailbox: str = "INBOX",
) -> InboxSaveSummary:
    """Persist extracted attachments into ``<output>/inbox`` + manifest."""
    inbox_dir = os.path.join(output_dir, fetch_handoff.INBOX_DIRNAME)
    writer = fetch_handoff.InboxWriter(inbox_dir)
    summary = InboxSaveSummary(
        inbox_dir=inbox_dir,
        manifest_path=str(writer.manifest_path),
        warnings=tuple(writer.warnings),
    )
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("is_url"):
            writer.record_todo(
                {
                    "kind": "portal_link",
                    "url_sha256": _stable_hash(str(row.get("filepath") or "")),
                    "provider_family": str(row.get("provider_family") or ""),
                    "subject": str(row.get("subject") or ""),
                    "sender": str(row.get("sender") or ""),
                    "mailbox": str(mailbox or ""),
                    "uid": str(row.get("email_id") or ""),
                    "reason": "附件为下载链接，需人工打开并保存",
                }
            )
            summary.link_count += 1
            continue
        source_path = str(row.get("filepath") or "")
        if not source_path or not os.path.isfile(source_path):
            continue
        digest = str(row.get("sha256") or "").strip().lower()
        if not digest:
            # Older fetchers did not put a content digest on the row; compute it
            # once here so duplicate accounting and the manifest stay correct.
            try:
                digest = fetch_handoff.sha256_file(source_path)
            except OSError:
                digest = ""
        existed = bool(digest and writer.existing(digest))
        writer.save_attachment(
            source_path,
            orig_name=str(
                row.get("original_filename") or os.path.basename(source_path)
            ),
            sha256=digest,
            metadata={
                "source": fetch_handoff.SOURCE_MAIL,
                "mailbox": str(row.get("mailbox") or mailbox or ""),
                "uid": str(row.get("uid") or row.get("email_id") or ""),
                "uidvalidity": str(row.get("uidvalidity") or ""),
                "message_id": str(row.get("message_id") or ""),
                "msg_part": str(row.get("msg_part") or ""),
                "subject": str(row.get("subject") or ""),
                "sender": str(row.get("sender") or ""),
                "received_at": str(row.get("received_at") or ""),
                "fetched_at": fetch_handoff.utc_now_iso(),
            },
        )
        if existed:
            summary.duplicate_count += 1
        else:
            summary.saved_count += 1
    writer.save_state(
        {
            "version": 1,
            "last_run": fetch_handoff.utc_now_iso(),
            "mailbox": str(mailbox or ""),
            "rows": int(len(rows or [])),
            "saved": int(summary.saved_count),
            "duplicates": int(summary.duplicate_count),
            "links": int(summary.link_count),
        }
    )
    return summary


class FetchOnlyRunner:
    """Run one mailbox fetch without any parsing/archiving step."""

    def __init__(
        self,
        *,
        fetcher_factory: Callable[..., Any] | None = None,
        channel_resolver: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._fetcher_factory = fetcher_factory
        self._channel_resolver = channel_resolver

    def _make_fetcher(self, request: FetchOnlyRequest, staging_dir: str):
        if self._fetcher_factory is not None:
            return self._fetcher_factory(
                request.email_address,
                request.auth_code,
                staging_dir=staging_dir,
            )
        from email_channel import resolve_channel
        from email_fetcher import EmailFetcher

        resolver = self._channel_resolver or resolve_channel
        channel = resolver(request.email_address)
        return EmailFetcher(
            request.email_address,
            request.auth_code,
            imap_server=request.imap_host or channel["imap_host"],
            imap_port=request.imap_port or channel["imap_port"],
            staging_dir=staging_dir,
        )

    def run(self, request: FetchOnlyRequest) -> FetchOnlyResult:
        if not request.email_address or not request.auth_code:
            return FetchOnlyResult(
                ok=False, message="请填写邮箱地址和授权码", error_reason="MISSING_CREDENTIALS"
            )
        output_dir = os.path.abspath(request.output_dir or "")
        if not output_dir:
            return FetchOnlyResult(
                ok=False, message="请选择输出目录", error_reason="MISSING_OUTPUT_DIR"
            )
        os.makedirs(output_dir, exist_ok=True)
        staging_dir = tempfile.mkdtemp(prefix="invoicefetch-", dir=output_dir)
        fetcher = None
        rows: list[dict[str, Any]] = []
        email_ids: list[Any] = []
        try:
            fetcher = self._make_fetcher(request, staging_dir)
            if not fetcher.connect():
                if getattr(fetcher, "certificate_error", False):
                    return FetchOnlyResult(
                        ok=False,
                        message="邮箱证书验证失败",
                        error_reason="IMAP_TLS_CERTIFICATE_INVALID",
                    )
                if getattr(fetcher, "timeout_error", False):
                    return FetchOnlyResult(
                        ok=False,
                        message="邮箱连接超时",
                        error_reason="IMAP_CONNECTION_TIMEOUT",
                    )
                return FetchOnlyResult(
                    ok=False,
                    message="邮箱登录失败，请检查授权码或 IMAP 设置",
                    error_reason="IMAP_LOGIN_FAILED",
                )
            since, before = _iso_date_bounds(request)
            email_ids = fetcher.fetch_emails_by_date(
                since_date=since, before_date=before
            )
            rows = fetcher.extract_attachments(email_ids, mailbox=request.mailbox)
            summary = save_fetch_rows(
                output_dir, list(rows or []), mailbox=request.mailbox
            )
            return FetchOnlyResult(
                ok=True,
                message="附件已提取到 inbox，等待整理",
                email_count=len(email_ids or []),
                attachment_count=len(rows or []),
                saved_count=summary.saved_count,
                duplicate_count=summary.duplicate_count,
                link_count=summary.link_count,
                inbox_dir=summary.inbox_dir,
                manifest_path=summary.manifest_path,
            )
        finally:
            if fetcher is not None:
                try:
                    fetcher.disconnect()
                except Exception:
                    pass
            # The inbox copies are complete at this point; drop the staging tree.
            try:
                shutil.rmtree(staging_dir, ignore_errors=True)
            except Exception:
                pass


def run_fetch_only(request: FetchOnlyRequest, **runner_kwargs: Any) -> FetchOnlyResult:
    return FetchOnlyRunner(**runner_kwargs).run(request)

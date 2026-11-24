from __future__ import annotations

import datetime as dt
import email
import email.utils
import hashlib
import imaplib
import re
import ssl
import time
from dataclasses import dataclass
from typing import Callable, Iterable


# Fixed UTC+8 offset: China has had no DST since 1991, so this is byte-for-byte
# equivalent to Asia/Shanghai for every real message date, while removing the
# import-time `zoneinfo`/tzdata dependency that broke Windows release builds.
SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8))

# IMAP SEARCH wants English month abbreviations regardless of the host locale,
# so format the date explicitly instead of relying on strftime("%b").
_IMAP_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
# Server-side SINCE is deliberately widened by a few days: headers and
# INTERNALDATE can disagree by timezone/skew, and the local exact filter below
# still removes everything outside the requested window.
SCAN_SINCE_OVERLAP_DAYS = 3


def _imap_date(value: dt.date) -> str:
    return f"{value.day:02d}-{_IMAP_MONTHS[value.month - 1]}-{value.year}"

# A single RFC822 message is fully buffered before MIME parsing, so its byte
# length is attacker-controlled (any sender can deliver a huge message, or the
# server can return a missing message body). Refuse to hold anything above this
# hard cap; the caller records the skip reason instead of failing the whole run.
DEFAULT_MAX_MESSAGE_BYTES = 50 * 1024 * 1024

_UID_PATTERN = re.compile(rb"\bUID\s+(\d+)\b", flags=re.IGNORECASE)
_INTERNALDATE_PATTERN = re.compile(
    rb'\bINTERNALDATE\s+"([^"]+)"', flags=re.IGNORECASE
)


class MailboxScanError(RuntimeError):
    """Raised when mailbox scope cannot be established without risking P0."""

    reason_code = "MAILBOX_SCAN_FAILED"
    user_message = "邮箱扫描响应异常，本次任务已失败；请重试并查看诊断报告。"


class UnresolvedMailboxInputError(RuntimeError):
    reason_code = "UNRESOLVED_MAILBOX_INPUT"
    user_message = "部分邮件在重试后仍无法读取，本次任务已失败；已读取产物保留供诊断。"

    def __init__(self, uids):
        normalized = MailboxScanner.normalize_uids(uids)
        self.unresolved_count = len(normalized)
        self.uid_hashes = tuple(
            hashlib.sha256(uid).hexdigest()[:12] for uid in normalized
        )
        hashes = ",".join(self.uid_hashes)
        super().__init__(
            f"{self.reason_code}; unresolved_count={self.unresolved_count}; uid_hashes={hashes}"
        )

    def diagnostic_payload(self):
        return {
            "event": "unresolved_mailbox_input",
            "reason_code": self.reason_code,
            "unresolved_count": self.unresolved_count,
            "uid_hashes": list(self.uid_hashes),
        }


@dataclass(frozen=True)
class MessageRef:
    uid: bytes
    message_date: dt.datetime | None
    internal_date: dt.datetime | None


@dataclass(frozen=True)
class MessageBatch:
    requested_uids: tuple[bytes, ...]
    messages: tuple[tuple[bytes, bytes], ...]
    unresolved_uids: tuple[bytes, ...]
    # UID -> raw byte length for messages rejected by the hard size cap. They are
    # deliberately not reported as unresolved: the caller records a skip reason.
    oversized_messages: tuple[tuple[bytes, int], ...] = ()


class MailboxScanner:
    HEADER_QUERY = "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (DATE)])"
    MESSAGE_QUERY = "(UID RFC822)"

    def __init__(
        self,
        mail,
        *,
        header_batch_size: int = 200,
        body_batch_size: int = 25,
        max_attempts: int = 2,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        diagnostic_callback: Callable[[dict], None] | None = None,
    ):
        if header_batch_size < 1 or body_batch_size < 1 or max_attempts < 1:
            raise ValueError("batch sizes and max_attempts must be positive")
        if int(max_message_bytes) < 1:
            raise ValueError("max_message_bytes must be positive")
        self.mail = mail
        self.header_batch_size = header_batch_size
        self.body_batch_size = body_batch_size
        self.max_attempts = max_attempts
        self.max_message_bytes = int(max_message_bytes)
        self.diagnostic_callback = diagnostic_callback
        # Filled by select_mailbox(); used by fetch-only resume to decide whether
        # a stored last-UID checkpoint is still comparable.
        self.uidvalidity = ""

    def scan(
        self,
        since: dt.date,
        before: dt.date | None,
        mailbox: str = "INBOX",
        *,
        full_scan: bool = False,
    ) -> list[MessageRef]:
        since = self._require_date(since, "since")
        before = self._require_date(before, "before", allow_none=True)
        if before is not None and before <= since:
            raise ValueError("before must be after since")

        self.select_mailbox(mailbox)

        search_since = since - dt.timedelta(days=SCAN_SINCE_OVERLAP_DAYS)
        uids = self._search_uids(search_since, full_scan=full_scan)
        headers: dict[bytes, MessageRef] = {}
        for chunk in self._chunks(uids, self.header_batch_size):
            headers.update(self._fetch_header_subset(chunk))

        retained = []
        for uid in uids:
            ref = headers.get(uid, MessageRef(uid, None, None))
            effective_date = ref.message_date or ref.internal_date
            if effective_date is None:
                retained.append(ref)
                continue
            local_day = effective_date.astimezone(SHANGHAI_TZ).date()
            if local_day < since or (before is not None and local_day >= before):
                continue
            retained.append(ref)
        self._emit("imap_scan_complete", searched=len(uids), retained=len(retained))
        return retained

    def select_mailbox(self, mailbox="INBOX"):
        try:
            status, _ = self.mail.select(mailbox, readonly=True)
        except Exception as exc:
            raise MailboxScanError("IMAP SELECT failed") from exc
        if not self.is_ok_status(status):
            raise MailboxScanError("IMAP SELECT failed")
        self.uidvalidity = self._read_uidvalidity()

    def _read_uidvalidity(self) -> str:
        """Return the selected mailbox UIDVALIDITY, or "" when unavailable."""
        response = getattr(self.mail, "response", None)
        if not callable(response):
            return ""
        try:
            status, data = response("UIDVALIDITY")
        except Exception:
            return ""
        if str(status or "").upper() != "UIDVALIDITY" or not data:
            return ""
        value = data[0]
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("ascii", errors="ignore")
        text = str(value or "").strip()
        return text if text.isdigit() else ""

    def iter_message_batches(
        self, uids: Iterable[bytes], query: str | None = None
    ):
        ordered_uids = self.normalize_uids(uids)
        query = self._ensure_uid_query(query or self.MESSAGE_QUERY)
        for chunk in self._chunks(ordered_uids, self.body_batch_size):
            fetched, oversized, unresolved = self._fetch_message_subset(chunk, query)
            ordered_messages = tuple(
                (uid, fetched[uid]) for uid in chunk if uid in fetched
            )
            self._emit(
                "imap_message_batch_ready",
                requested_count=len(chunk),
                buffered_count=len(ordered_messages),
                oversized_count=len(oversized),
                unresolved_count=len(unresolved),
            )
            yield MessageBatch(
                tuple(chunk),
                ordered_messages,
                tuple(unresolved),
                tuple((uid, oversized[uid]) for uid in chunk if uid in oversized),
            )
            del fetched
            del ordered_messages
            del unresolved
            del oversized

    def fetch_messages(
        self, uids: Iterable[bytes], query: str | None = None
    ) -> dict[bytes, bytes]:
        ordered_uids = self.normalize_uids(uids)
        if len(ordered_uids) > self.body_batch_size:
            raise ValueError("fetch_messages accepts at most one configured message batch")
        batches = self.iter_message_batches(ordered_uids, query=query)
        first = next(batches, None)
        return dict(first.messages) if first is not None else {}

    def _search_uids(self, since: dt.date | None, *, full_scan: bool = False) -> list[bytes]:
        if full_scan or since is None:
            label = "UID SEARCH ALL"
            args: tuple[object, ...] = ("SEARCH", None, "ALL")
        else:
            query_date = _imap_date(since)
            label = f"UID SEARCH SINCE {query_date}"
            args = ("SEARCH", None, "SINCE", query_date)

        last_exc: BaseException | None = None
        attempts = max(1, int(self.max_attempts))
        for attempt in range(attempts):
            try:
                status, response = self.mail.uid(*args)
            except Exception as exc:
                last_exc = exc
            else:
                if self.is_ok_status(status):
                    return self._parse_search_uids(response, label)
                last_exc = None
            if attempt + 1 < attempts:
                time.sleep(0.2 * (attempt + 1))
        raise MailboxScanError(f"{label} failed") from last_exc

    def _search_all_uids(self) -> list[bytes]:
        """Full-mailbox escape hatch for servers that reject SINCE."""
        return self._search_uids(None, full_scan=True)

    def _parse_search_uids(self, response: object, label: str) -> list[bytes]:
        tokens = []
        malformed = False
        for item in response if isinstance(response, (list, tuple)) else [response]:
            if item is None:
                continue
            if isinstance(item, bytearray):
                item = bytes(item)
            if not isinstance(item, bytes):
                malformed = True
                continue
            stripped = item.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if any(not part.isdigit() for part in parts):
                malformed = True
                continue
            tokens.extend(parts)
        if malformed:
            raise MailboxScanError(f"malformed {label} response")
        return self.normalize_uids(tokens)

    def _fetch_header_subset(self, uids: list[bytes]) -> dict[bytes, MessageRef]:
        if not uids:
            return {}
        response = self._uid_fetch_with_retry(uids, self.HEADER_QUERY, "header")
        parsed = self._parse_headers(response, set(uids)) if response is not None else {}
        missing = [uid for uid in uids if uid not in parsed]
        if not missing:
            return parsed
        if len(uids) == 1:
            self._emit_failed("header", uids)
            parsed[uids[0]] = MessageRef(uids[0], None, None)
            return parsed
        for subset in self._split(missing):
            parsed.update(self._fetch_header_subset(subset))
        return parsed

    def _fetch_message_subset(self, uids: list[bytes], query: str):
        if not uids:
            return {}, {}, []
        response = self._uid_fetch_with_retry(uids, query, "message")
        if response is not None:
            parsed, oversized = self._parse_payloads(response, set(uids))
        else:
            parsed, oversized = {}, {}
        # Cap-rejected payloads are intentionally excluded from the retry path:
        # re-fetching a too-large message cannot make it smaller and would
        # amplify the download.
        missing = [uid for uid in uids if uid not in parsed and uid not in oversized]
        if not missing:
            return parsed, oversized, []
        if len(uids) == 1:
            self._emit_failed("message", uids)
            return parsed, oversized, list(missing)
        unresolved = []
        for subset in self._split(missing):
            child_parsed, child_oversized, child_unresolved = self._fetch_message_subset(
                subset, query
            )
            parsed.update(child_parsed)
            oversized.update(child_oversized)
            unresolved.extend(child_unresolved)
        return parsed, oversized, unresolved

    @staticmethod
    def _ensure_uid_query(query: str) -> str:
        normalized = str(query or "").strip()
        if not normalized.startswith("(") or not normalized.endswith(")"):
            raise ValueError("FETCH query must be parenthesized")
        inner = normalized[1:-1].strip()
        if re.search(r"(?:^|\s)UID(?:\s|$)", inner, flags=re.IGNORECASE):
            return normalized
        return f"(UID {inner})"

    def _uid_fetch_with_retry(self, uids: list[bytes], query: str, purpose: str):
        uid_set = b",".join(uids)
        last_error_type = "malformed_response"
        for _attempt in range(1, self.max_attempts + 1):
            try:
                status, response = self.mail.uid("FETCH", uid_set, query)
                if self.is_ok_status(status) and isinstance(response, (list, tuple)):
                    return response
                last_error_type = "fetch_status"
            except Exception as exc:
                if isinstance(exc, (TimeoutError, ConnectionError, imaplib.IMAP4.abort, ssl.SSLEOFError, ssl.SSLZeroReturnError)):
                    raise MailboxScanError("IMAP FETCH connection failed") from exc
                last_error_type = type(exc).__name__
        self._emit(
            "imap_fetch_retry_exhausted",
            purpose=purpose,
            batch_size=len(uids),
            attempts=self.max_attempts,
            reason=last_error_type,
        )
        return None

    @classmethod
    def _parse_headers(cls, response, requested: set[bytes]) -> dict[bytes, MessageRef]:
        parsed = {}
        for metadata, payload in cls._response_tuples(response):
            uid = cls.extract_uid(metadata)
            if uid not in requested or uid in parsed:
                continue
            internal_date = cls.extract_internal_date(metadata)
            message_date = None
            try:
                header = email.message_from_bytes(payload)
                raw_date = header.get("Date")
                if raw_date:
                    message_date = cls._to_shanghai(email.utils.parsedate_to_datetime(raw_date))
            except Exception:
                message_date = None
            parsed[uid] = MessageRef(uid, message_date, internal_date)
        return parsed

    def _parse_payloads(self, response, requested: set[bytes]):
        parsed: dict[bytes, bytes] = {}
        oversized: dict[bytes, int] = {}
        limit = self.max_message_bytes
        for metadata, payload in self._response_tuples(response):
            uid = self.extract_uid(metadata)
            if uid not in requested or uid in parsed or not payload:
                continue
            size = len(payload)
            if size > limit:
                oversized[uid] = size
                self._emit(
                    "imap_message_payload_too_large",
                    uid_hash=hashlib.sha256(uid).hexdigest()[:12],
                    payload_bytes=size,
                    limit=limit,
                )
                continue
            parsed[uid] = payload
        return parsed, oversized

    @staticmethod
    def _response_tuples(response):
        if not isinstance(response, (list, tuple)):
            return
        for item in response:
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            metadata, payload = item[0], item[1]
            if isinstance(metadata, bytearray):
                metadata = bytes(metadata)
            if isinstance(payload, bytearray):
                payload = bytes(payload)
            if isinstance(metadata, bytes) and isinstance(payload, bytes):
                yield metadata, payload

    @staticmethod
    def extract_uid(metadata: bytes) -> bytes:
        match = _UID_PATTERN.search(metadata)
        return match.group(1) if match else b""

    @classmethod
    def extract_internal_date(cls, metadata: bytes) -> dt.datetime | None:
        match = _INTERNALDATE_PATTERN.search(metadata)
        if not match:
            return None
        try:
            parsed = email.utils.parsedate_to_datetime(match.group(1).decode("ascii"))
        except Exception:
            return None
        return cls._to_shanghai(parsed)

    @staticmethod
    def _to_shanghai(value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=SHANGHAI_TZ)
        return value.astimezone(SHANGHAI_TZ)

    @staticmethod
    def _require_date(value, name, allow_none=False):
        if value is None and allow_none:
            return None
        if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
            raise TypeError(f"{name} must be a date")
        return value

    @staticmethod
    def is_ok_status(status) -> bool:
        if isinstance(status, bytes):
            status = status.decode("ascii", errors="ignore")
        return str(status or "").casefold() == "ok"

    @staticmethod
    def normalize_uids(uids: Iterable[bytes]) -> list[bytes]:
        result = []
        seen = set()
        for uid in uids:
            if isinstance(uid, bytearray):
                uid = bytes(uid)
            elif isinstance(uid, str):
                uid = uid.encode("ascii", errors="ignore")
            if not isinstance(uid, bytes) or not uid.isdigit() or uid in seen:
                continue
            seen.add(uid)
            result.append(uid)
        return result

    @staticmethod
    def _chunks(values: list[bytes], size: int):
        for start in range(0, len(values), size):
            yield values[start : start + size]

    @staticmethod
    def _split(values: list[bytes]):
        midpoint = max(1, len(values) // 2)
        return [values[:midpoint], values[midpoint:]] if len(values) > 1 else [values]

    def _emit_failed(self, purpose: str, uids: list[bytes]):
        digest = hashlib.sha256(b",".join(uids)).hexdigest()[:12]
        self._emit(
            "imap_fetch_failed",
            purpose=purpose,
            batch_size=len(uids),
            uid_set_hash=digest,
        )

    def _emit(self, event: str, **fields):
        if self.diagnostic_callback is None:
            return
        try:
            self.diagnostic_callback({"event": event, **fields})
        except Exception:
            pass

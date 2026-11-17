import email_fetcher
import pytest

from email_channel import is_supported_email, resolve_channel
from truth_contracts import TruthContractError, TruthManifest


class _FakeMail:
    def __init__(self, response):
        self.response = response
        self.sent = b""

    def _new_tag(self):
        return b"A001"

    def send(self, line):
        self.sent = line

    def readline(self):
        return self.response


def test_88_channel_resolves_to_perfect_world_imap():
    channel = resolve_channel("user@88.com")

    assert channel["imap_host"] == "imap.88.com"
    assert channel["imap_port"] == 993
    assert channel["requires_id_cmd"] is True
    assert is_supported_email("USER@88.COM") is True


def test_email_fetcher_defaults_resolve_88_channel(tmp_path):
    fetcher = email_fetcher.EmailFetcher(
        "user@88.com", "dedicated-password", staging_dir=str(tmp_path)
    )

    assert fetcher.imap_server == "imap.88.com"
    assert fetcher.imap_port == 993


def test_email_fetcher_keeps_explicit_channel_override(tmp_path):
    fetcher = email_fetcher.EmailFetcher(
        "user@88.com",
        "dedicated-password",
        imap_server="imap.example.test",
        imap_port=1993,
        staging_dir=str(tmp_path),
    )

    assert fetcher.imap_server == "imap.example.test"
    assert fetcher.imap_port == 1993


def test_88_mailbox_sends_id_command_after_login(tmp_path, caplog):
    fetcher = email_fetcher.EmailFetcher(
        "user@88.com", "dedicated-password", staging_dir=str(tmp_path)
    )
    fake_mail = _FakeMail(b"A001 BAD Unsupported command")
    fetcher.mail = fake_mail

    fetcher._send_imap_id_command()

    assert fake_mail.sent.startswith(b"A001 ID")
    assert "rejected the optional ID command" in caplog.text


def test_id_command_eof_remains_fatal(tmp_path):
    fetcher = email_fetcher.EmailFetcher(
        "user@88.com", "dedicated-password", staging_dir=str(tmp_path)
    )
    fetcher.mail = _FakeMail(b"")

    with pytest.raises(ConnectionError):
        fetcher._send_imap_id_command()


def test_truth_manifest_accepts_88_channel():
    payload = {
        "summary": {
            "dataset": "fixture",
            "finalized": True,
            "pending_review_count": 0,
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
            "before_exclusive": "2026-02-01",
            "account_domain": "88.com",
            "account_channel": "88",
            "mailbox": "INBOX",
            "target_company": "Acme",
            "included_count": 0,
            "excluded_count": 0,
        },
        "included": [],
        "excluded": [],
        "pending_review": [],
    }

    manifest = TruthManifest.from_mapping(payload)

    assert manifest.account_domain == "88.com"
    assert manifest.account_channel == "88"


def test_truth_manifest_rejects_conflicting_88_channel():
    payload = {
        "summary": {
            "dataset": "fixture",
            "finalized": True,
            "pending_review_count": 0,
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
            "before_exclusive": "2026-02-01",
            "account_domain": "88.com",
            "account_channel": "qq",
            "mailbox": "INBOX",
            "target_company": "Acme",
            "included_count": 0,
            "excluded_count": 0,
        },
        "included": [],
        "excluded": [],
        "pending_review": [],
    }

    with pytest.raises(TruthContractError) as error:
        TruthManifest.from_mapping(payload)

    assert error.value.code == "unsupported_account_channel"

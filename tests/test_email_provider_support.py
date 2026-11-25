"""Mailbox provider registry coverage and cross-language allowlist sync tests."""

import re
from pathlib import Path

import pytest

import email_channel
import email_fetcher
from app_api import InvoiceAppAPI
from email_channel import resolve_channel, supported_domains
from fetch_only import FetchOnlyRequest, FetchOnlyRunner
from truth_contracts import TruthContractError, TruthManifest, _CHANNELS

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SRC = ROOT / "plugins" / "dsh-invoice-downloader" / "src"


@pytest.mark.parametrize(
    ("domain", "host", "channel_id", "needs_id"),
    [
        ("qq.com", "imap.qq.com", "qq", False),
        ("vip.qq.com", "imap.qq.com", "qq", False),
        ("foxmail.com", "imap.qq.com", "qq", False),
        ("exmail.qq.com", "imap.exmail.qq.com", "exmail", False),
        ("163.com", "imap.163.com", "163", True),
        ("126.com", "imap.126.com", "126", True),
        ("188.com", "imap.188.com", "188", True),
        ("yeah.net", "imap.yeah.net", "yeah", True),
        ("qiye.163.com", "imap.qiye.163.com", "qiye163", True),
        ("88.com", "imap.88.com", "88", True),
        ("sina.cn", "imap.sina.com", "sina", False),
        ("sohu.com", "imap.sohu.com", "sohu", False),
        ("aliyun.com", "imap.aliyun.com", "aliyun", False),
        ("qiye.aliyun.com", "imap.qiye.aliyun.com", "aliyun", False),
        ("gmail.com", "imap.gmail.com", "gmail", False),
        ("icloud.com", "imap.mail.me.com", "icloud", False),
        ("yahoo.com", "imap.mail.yahoo.com", "yahoo", False),
        ("gmx.com", "imap.gmx.com", "gmx", False),
    ],
)
def test_registry_routes_common_domains(domain, host, channel_id, needs_id):
    channel = resolve_channel(f"user@{domain}")

    assert channel["imap_host"] == host
    assert channel["imap_port"] == 993
    assert channel["channel_id"] == channel_id
    assert channel["requires_id_cmd"] is needs_id
    assert channel["supported"] is True


def test_domain_lookup_is_case_insensitive_and_uses_last_at():
    channel = resolve_channel("USER+invoice@GMAIL.COM")

    assert channel["imap_host"] == "imap.gmail.com"
    assert channel["supported"] is True


def test_registry_entries_are_complete():
    for domain, channel in email_channel.EMAIL_CHANNELS.items():
        assert channel["imap_host"].startswith("imap."), domain
        assert channel["imap_port"] == 993, domain
        assert channel["channel_id"], domain
        assert channel["auth_hint"], domain
        assert channel["display"], domain
        assert isinstance(channel["requires_id_cmd"], bool), domain


def test_explicit_imap_host_still_allows_custom_domains(tmp_path):
    fetcher = email_fetcher.EmailFetcher(
        "user@corp.example",
        "auth",
        imap_server="imap.corp.example",
        imap_port=1993,
        staging_dir=str(tmp_path),
    )

    assert fetcher.unsupported_mailbox is False
    assert fetcher.imap_server == "imap.corp.example"
    assert fetcher.imap_port == 1993


def test_unknown_domain_is_not_silently_routed_to_qq():
    channel = resolve_channel("user@outlook.com")

    assert channel["supported"] is False
    assert channel["imap_host"] == ""
    assert channel["channel_id"] == "custom"


def test_fetcher_refuses_unknown_domain_without_opening_a_socket(tmp_path):
    fetcher = email_fetcher.EmailFetcher(
        "user@outlook.com", "auth", staging_dir=str(tmp_path)
    )

    assert fetcher.unsupported_mailbox is True
    assert fetcher.connect() is False
    assert fetcher.unsupported_mailbox is True
    assert fetcher.mail is None


def test_fetch_only_rejects_unknown_domain_before_writing(tmp_path):
    output_dir = tmp_path / "output"

    result = FetchOnlyRunner().run(
        FetchOnlyRequest(
            email_address="user@outlook.com",
            auth_code="auth",
            output_dir=str(output_dir),
        )
    )

    assert result.ok is False
    assert result.error_reason == "UNSUPPORTED_MAILBOX"
    assert not output_dir.exists()


def test_start_processing_and_fetch_only_reject_unknown_domain(tmp_path):
    api = InvoiceAppAPI()

    started = api.start_processing(
        "",
        str(tmp_path / "output"),
        email_address="user@outlook.com",
        auth_code="auth",
    )
    fetched = api.start_fetch_only(
        str(tmp_path / "output"),
        email_address="user@outlook.com",
        auth_code="auth",
    )

    expected = "暂不支持该邮箱域名，请更换为受支持的常用邮箱。"
    assert started == {"success": False, "message": expected}
    assert fetched == {"success": False, "message": expected}


def test_truth_manifest_accepts_new_channels():
    for domain, channel_id in (("126.com", "126"), ("gmail.com", "gmail")):
        payload = {
            "summary": {
                "dataset": "fixture",
                "finalized": True,
                "pending_review_count": 0,
                "date_from": "2026-01-01",
                "date_to": "2026-01-31",
                "before_exclusive": "2026-02-01",
                "account_domain": domain,
                "account_channel": channel_id,
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
        assert manifest.account_channel == channel_id


def test_truth_manifest_still_rejects_unknown_domain():
    payload = {
        "summary": {
            "dataset": "fixture",
            "finalized": True,
            "pending_review_count": 0,
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
            "before_exclusive": "2026-02-01",
            "account_domain": "outlook.com",
            "account_channel": "outlook",
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


def test_truth_channel_map_matches_registry():
    assert _CHANNELS == {
        domain: channel["channel_id"]
        for domain, channel in email_channel.EMAIL_CHANNELS.items()
    }


def test_frontend_domain_list_matches_registry():
    source = (ROOT / "templates" / "index_app.js").read_text(encoding="utf-8")
    match = re.search(r"const EMAIL_PROVIDER_DOMAINS = \[(.*?)\];", source, re.S)

    assert match, "EMAIL_PROVIDER_DOMAINS is missing from the settings UI"
    assert set(re.findall(r'"([^"]+)"', match.group(1))) == set(supported_domains())


def test_plugin_domain_list_matches_registry():
    source = (PLUGIN_SRC / "rpc-handler.ts").read_text(encoding="utf-8")
    match = re.search(
        r"const SUPPORTED_IMAP_DOMAINS = new Set\(\[(.*?)\]\)", source, re.S
    )

    assert match, "SUPPORTED_IMAP_DOMAINS is missing from the plugin RPC handler"
    assert set(re.findall(r"'([^']+)'", match.group(1))) == set(supported_domains())

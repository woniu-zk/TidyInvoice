"""Guard against re-introducing dead legacy helpers or fake-success placeholders."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_dead_legacy_helpers_are_removed():
    assert "_legacy_extract_attachments_pre_release_prep" not in _source(
        "email_fetcher.py"
    )

    app_api = _source("app_api.py")
    assert "_legacy_export_result_detail_pre_release_prep" not in app_api
    assert "_legacy_export_run_summary_pre_release_prep" not in app_api


def test_fake_success_retry_placeholders_are_removed():
    app_api = _source("app_api.py")
    assert "def retry_all_errors" not in app_api
    assert "def retry_single_invoice" not in app_api

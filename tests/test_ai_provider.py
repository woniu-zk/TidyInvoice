import json
from pathlib import Path
from types import SimpleNamespace

from app_api import InvoiceAppAPI
from glm_runtime import (
    DEEPSEEK_CHAT_ENDPOINT,
    DEEPSEEK_MODEL,
    GlmRequestError,
    GlmRuntime,
    default_profiles,
)
from invoice_extractor import InvoiceExtractor
from user_settings import UserSettingsStore


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload

    def close(self):
        pass


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _RecordingRuntime:
    provider = "deepseek"
    supports_ocr = False
    profiles = {
        "text": SimpleNamespace(name=DEEPSEEK_MODEL),
        "vision_quality": SimpleNamespace(name=DEEPSEEK_MODEL),
    }

    def __init__(self):
        self.calls = []

    def request(self, profile_name, payload, parser, **_kwargs):
        self.calls.append((profile_name, payload))
        return parser(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "is_invoice": True,
                                    "Date": "20260101",
                                    "Purchaser": "Acme",
                                    "Seller": "测试商户",
                                    "Amount": "10.00",
                                    "Type": "餐饮",
                                    "category": "餐饮",
                                }
                            )
                        }
                    }
                ]
            }
        )


def test_deepseek_profiles_cover_text_and_vision_without_ocr():
    profiles = default_profiles(provider="deepseek")

    assert set(profiles) == {"text", "vision_quality"}
    assert profiles["text"].name == DEEPSEEK_MODEL
    assert profiles["vision_quality"].name == DEEPSEEK_MODEL
    assert profiles["text"].endpoint == DEEPSEEK_CHAT_ENDPOINT


def test_deepseek_runtime_posts_to_deepseek_endpoint():
    session = FakeSession(
        [FakeResponse({"choices": [{"message": {"content": "ok"}}]})]
    )
    runtime = GlmRuntime("local-key", provider="deepseek", session=session)

    result = runtime.request(
        "text",
        {"messages": [{"role": "user", "content": "Hi"}]},
        lambda body: body["choices"][0]["message"]["content"],
    )

    assert result == "ok"
    endpoint, kwargs = session.calls[0]
    assert endpoint == DEEPSEEK_CHAT_ENDPOINT
    assert kwargs["json"]["model"] == DEEPSEEK_MODEL
    assert kwargs["headers"]["Authorization"] == "Bearer local-key"


def test_deepseek_request_error_uses_provider_label():
    error = GlmRequestError("text", provider="deepseek", reason="http_error")

    assert str(error).startswith("DeepSeek request failed")


def test_deepseek_extractor_skips_ocr_and_uses_json_vision_payload(tmp_path):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n" + b"x" * 2000)
    runtime = _RecordingRuntime()
    extractor = InvoiceExtractor(
        "local-key",
        str(tmp_path / "output"),
        glm_runtime=runtime,
        close_glm_runtime=False,
    )

    result = extractor.extract_info_via_llm(
        ["ZmFrZQ=="], pdf_path=str(pdf_path), _allow_local_probe=False
    )

    assert result is not None
    assert [profile for profile, _payload in runtime.calls] == ["vision_quality"]
    _profile, payload = runtime.calls[0]
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert "json" in payload["messages"][0]["content"][0]["text"]
    trace = extractor.last_extraction_trace
    assert trace["track_a"] == {
        "status": "skipped",
        "reason_code": "PROVIDER_OCR_UNAVAILABLE",
        "message": "provider has no OCR profile",
    }
    assert trace["engine"] == "track_b"
    assert trace["reason_code"] == "TRACK_A_SKIPPED_TRACK_B_FALLBACK"


def test_glm_extractor_payload_keeps_existing_shape(tmp_path):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n" + b"x" * 2000)
    runtime = _RecordingRuntime()
    runtime.provider = "glm"
    extractor = InvoiceExtractor(
        "local-key",
        str(tmp_path / "output"),
        glm_runtime=runtime,
        close_glm_runtime=False,
    )

    extractor.extract_info_via_llm(
        ["ZmFrZQ=="], pdf_path=str(pdf_path), _allow_local_probe=False
    )

    _profile, payload = runtime.calls[0]
    assert "thinking" not in payload
    assert "response_format" not in payload


def test_deepseek_key_uses_protected_storage(tmp_path):
    settings_path = tmp_path / "user_settings.json"
    store = UserSettingsStore(str(settings_path))

    store.save(
        {
            "ai_provider": "deepseek",
            "api_key": "glm-secret",
            "deepseek_api_key": "deepseek-secret",
        }
    )

    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["values"] == {"ai_provider": "deepseek"}
    assert set(persisted["protected"]) == {"api_key", "deepseek_api_key"}
    raw_text = settings_path.read_text(encoding="utf-8")
    assert "glm-secret" not in raw_text
    assert "deepseek-secret" not in raw_text
    assert store.load() == {
        "ai_provider": "deepseek",
        "api_key": "glm-secret",
        "deepseek_api_key": "deepseek-secret",
    }


def test_admission_persists_deepseek_key_without_overwriting_glm_key(
    tmp_path, monkeypatch
):
    api = InvoiceAppAPI()
    saved_payloads = []

    monkeypatch.setattr(
        api,
        "save_user_settings",
        lambda settings: saved_payloads.append(dict(settings))
        or {"success": True},
    )
    monkeypatch.setattr(
        api,
        "_build_run_dependencies",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("stop")),
    )
    monkeypatch.setattr(api, "_cleanup_temp_folders", lambda **_kwargs: None)
    monkeypatch.setattr(api, "_start_truth_audit_async", lambda *_args: None)

    result = api.start_processing(
        "",
        str(tmp_path / "output"),
        email_address="user@88.com",
        auth_code="mail-auth",
        api_key="deepseek-key",
        ai_provider="deepseek",
    )

    assert result == {"success": False, "message": "后台任务启动失败"}
    payload = saved_payloads[0]
    assert payload["ai_provider"] == "deepseek"
    assert payload["deepseek_api_key"] == "deepseek-key"
    assert "api_key" not in payload
    assert api._active_ai_provider == "glm"


def test_frontend_offers_88_mailbox_and_local_engine_block():
    source = (ROOT / "templates" / "index_app.js").read_text(encoding="utf-8")

    assert '{ value: "88.com", label: "88.com" }' in source
    # The product now recognizes invoices locally: no model provider switch and
    # no API-key field may be offered in the settings UI.
    assert "本地识别引擎" in source
    assert "LOCAL_ENGINE_ITEMS" in source
    assert "DEEPSEEK_PLATFORM_URL" not in source
    assert "deepseek_api_key" not in source
    assert 'rawDomain === "163.com" ? "163.com" : "qq.com"' not in source

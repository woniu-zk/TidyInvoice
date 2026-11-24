import json
from pathlib import Path

import user_settings


def test_macos_settings_keep_secrets_in_keychain_and_clear_them(tmp_path, monkeypatch):
    """The persisted settings seam must not write macOS secrets to disk."""
    monkeypatch.setattr(user_settings, "_is_macos", lambda: True, raising=False)
    keychain = {}

    def store_secret(settings_path, key, value):
        marker = f"keychain:{Path(settings_path).name}:{key}"
        keychain[marker] = value
        return marker

    def load_secret(marker):
        return keychain.get(marker, "")

    def delete_secret(marker):
        keychain.pop(marker, None)

    monkeypatch.setattr(
        user_settings, "_store_macos_keychain_secret", store_secret, raising=False
    )
    monkeypatch.setattr(
        user_settings, "_load_macos_keychain_secret", load_secret, raising=False
    )
    monkeypatch.setattr(
        user_settings, "_delete_macos_keychain_secret", delete_secret, raising=False
    )

    settings_path = tmp_path / "user_settings.json"
    store = user_settings.UserSettingsStore(settings_path=str(settings_path))
    store.save(
        {
            "email": "user@example.com",
            "auth_code": "mail-secret",
            "api_key": "api-secret",
        }
    )

    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["values"] == {"email": "user@example.com"}
    assert persisted["protected"] == {
        "auth_code": "keychain:user_settings.json:auth_code",
        "api_key": "keychain:user_settings.json:api_key",
    }
    assert "mail-secret" not in settings_path.read_text(encoding="utf-8")
    assert "api-secret" not in settings_path.read_text(encoding="utf-8")
    assert store.load() == {
        "email": "user@example.com",
        "auth_code": "mail-secret",
        "api_key": "api-secret",
    }

    store.clear()

    assert not settings_path.exists()
    assert keychain == {}


def test_user_settings_load_uses_mtime_cache_and_invalidates_on_save(
    tmp_path, monkeypatch
):
    settings_path = tmp_path / "user_settings.json"
    store = user_settings.UserSettingsStore(settings_path=str(settings_path))
    store.save({"email": "user@example.com", "company": "ACME"})

    calls = {"count": 0}
    real_load = user_settings.json.load

    def counting_load(handle, *args, **kwargs):
        calls["count"] += 1
        return real_load(handle, *args, **kwargs)

    monkeypatch.setattr(user_settings.json, "load", counting_load)

    assert store.load()["company"] == "ACME"
    assert calls["count"] == 1
    # Second poll hits the cache instead of re-reading and decrypting the file.
    assert store.load()["company"] == "ACME"
    assert calls["count"] == 1

    store.save({"email": "user@example.com", "company": "Other"})
    assert store.load()["company"] == "Other"
    assert calls["count"] == 2

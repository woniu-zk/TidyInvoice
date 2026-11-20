"""WebView2 delivery modes: fixed bundled runtime vs system (evergreen) runtime.

These tests pin the contract shared by ``main.py``, the release scripts and the
PyInstaller spec so the two build flavours cannot silently drift apart.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import main

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_BUILD = ROOT / "build" / "windows"
MANIFEST_PATH = WINDOWS_BUILD / "resources.manifest.json"
RUNTIME_SOURCES_PATH = WINDOWS_BUILD / "runtime-sources.json"
SPEC_PATH = WINDOWS_BUILD / "TidyInvoice.spec"
BUILD_RELEASE_PATH = WINDOWS_BUILD / "build_release.ps1"
PREPARE_RUNTIME_PATH = WINDOWS_BUILD / "prepare_runtime.ps1"
RELEASE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-desktop.yml"
QUALIFY_SCRIPT_PATH = ROOT / ".github" / "scripts" / "qualify-windows-release.ps1"

REQUIRES_WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows-only WebView2 wiring")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_fixed_runtime(current_dir: Path) -> Path:
    runtime_dir = current_dir / "build" / "runtime" / "webview2-fixed"
    runtime_dir.mkdir(parents=True)
    for name in ("msedgewebview2.exe", "msedge.dll", "resources.pak"):
        (runtime_dir / name).write_bytes(b"stub")
    (runtime_dir / "Locales").mkdir()
    return runtime_dir


def _fake_webview():
    return SimpleNamespace(settings={})


@REQUIRES_WINDOWS
def test_resolve_mode_auto_detects_fixed_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv(main.WEBVIEW2_MODE_ENV, raising=False)
    _make_fixed_runtime(tmp_path)

    assert main._resolve_webview2_mode(tmp_path) == "fixed"


@REQUIRES_WINDOWS
def test_resolve_mode_auto_falls_back_to_evergreen(tmp_path, monkeypatch):
    monkeypatch.delenv(main.WEBVIEW2_MODE_ENV, raising=False)

    assert main._resolve_webview2_mode(tmp_path) == "evergreen"


@REQUIRES_WINDOWS
def test_resolve_mode_env_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.setenv(main.WEBVIEW2_MODE_ENV, "evergreen")
    _make_fixed_runtime(tmp_path)

    assert main._resolve_webview2_mode(tmp_path) == "evergreen"
    # An explicit CLI choice always beats the environment.
    assert main._resolve_webview2_mode(tmp_path, requested_mode="fixed") == "fixed"


def test_resolve_mode_rejects_unknown_mode(monkeypatch):
    monkeypatch.delenv(main.WEBVIEW2_MODE_ENV, raising=False)
    with pytest.raises(ValueError):
        main._resolve_webview2_mode(ROOT, requested_mode="portable")


@REQUIRES_WINDOWS
def test_configure_fixed_mode_sets_bundled_runtime_path(tmp_path, monkeypatch):
    monkeypatch.delenv(main.WEBVIEW2_MODE_ENV, raising=False)
    runtime_dir = _make_fixed_runtime(tmp_path)
    webview_module = _fake_webview()

    info = main._configure_webview_runtime(
        webview_module, tmp_path, requested_mode="fixed"
    )

    assert info["mode"] == "fixed"
    assert info["runtime_dir"] == str(runtime_dir.resolve())
    assert webview_module.settings["WEBVIEW2_RUNTIME_PATH"] == info["runtime_dir"]


@REQUIRES_WINDOWS
def test_configure_evergreen_uses_system_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv(main.WEBVIEW2_MODE_ENV, raising=False)
    monkeypatch.setattr(main, "_read_system_webview2_version", lambda: "146.0.3856.84")
    webview_module = _fake_webview()

    info = main._configure_webview_runtime(
        webview_module, tmp_path, requested_mode="evergreen"
    )

    assert info["mode"] == "evergreen"
    assert info["source"] == "system"
    assert info["version"] == "146.0.3856.84"
    assert "WEBVIEW2_RUNTIME_PATH" not in webview_module.settings


@REQUIRES_WINDOWS
def test_configure_evergreen_installs_bootstrapper_when_runtime_missing(tmp_path, monkeypatch):
    monkeypatch.delenv(main.WEBVIEW2_MODE_ENV, raising=False)
    versions = iter(["", "146.0.3856.84"])
    monkeypatch.setattr(main, "_read_system_webview2_version", lambda: next(versions))
    bootstrapper = tmp_path / "MicrosoftEdgeWebView2Setup.exe"
    bootstrapper.write_bytes(b"stub")
    monkeypatch.setattr(main, "_find_webview2_bootstrapper", lambda _current: bootstrapper)
    installed = []
    monkeypatch.setattr(
        main, "_install_webview2_bootstrapper", lambda path: installed.append(path) or 0
    )

    info = main._configure_webview_runtime(_fake_webview(), tmp_path, requested_mode="evergreen")

    assert installed == [bootstrapper]
    assert info["source"] == "bootstrapper"
    assert info["bootstrapper_exit_code"] == 0
    assert info["version"] == "146.0.3856.84"


@REQUIRES_WINDOWS
def test_configure_evergreen_without_runtime_or_bootstrapper_fails_actionably(tmp_path, monkeypatch):
    monkeypatch.delenv(main.WEBVIEW2_MODE_ENV, raising=False)
    monkeypatch.setattr(main, "_read_system_webview2_version", lambda: "")
    monkeypatch.setattr(main, "_find_webview2_bootstrapper", lambda _current: None)

    with pytest.raises(RuntimeError) as excinfo:
        main._configure_webview_runtime(_fake_webview(), tmp_path, requested_mode="evergreen")

    assert "WebView2" in str(excinfo.value)
    assert main.WEBVIEW2_DOWNLOAD_URL in str(excinfo.value)


def test_configure_on_non_windows_is_a_noop(monkeypatch):
    monkeypatch.setattr(main, "os", SimpleNamespace(name="posix"))
    webview_module = _fake_webview()

    info = main._configure_webview_runtime(webview_module, ROOT)

    assert info["mode"] == "system"
    assert webview_module.settings == {}


def test_cli_accepts_webview2_mode_override():
    assert main._parse_args([]).webview2_mode == ""
    assert main._parse_args(["--webview2-mode", "evergreen"]).webview2_mode == "evergreen"
    assert main._parse_args(["--webview2-mode", "fixed"]).webview2_mode == "fixed"


def test_validate_runtime_dir_rejects_incomplete_runtime(tmp_path):
    runtime_dir = tmp_path / "webview2-fixed"
    runtime_dir.mkdir()
    (runtime_dir / "msedge.dll").write_bytes(b"stub")

    with pytest.raises(FileNotFoundError):
        main._validate_webview2_runtime_dir(runtime_dir)
    assert main._webview2_runtime_dir_complete(runtime_dir) is False


# ---------------------------------------------------------------------------
# Packaging / release wiring contract
# ---------------------------------------------------------------------------


def test_runtime_sources_declare_both_webview2_modes_and_bootstrapper():
    payload = json.loads(_read(RUNTIME_SOURCES_PATH))
    webview2 = payload["webview2"]

    assert webview2["modes"]["default"] == "fixed"
    assert set(webview2["modes"]["supported"]) == {"fixed", "evergreen"}
    bootstrapper = webview2["bootstrapper"]
    assert bootstrapper["path"].endswith("MicrosoftEdgeWebView2Setup.exe")
    assert bootstrapper["download_url"].startswith("https://")
    assert bootstrapper["install_args"] == ["/silent", "/install"]


def test_resources_manifest_datas_are_mode_specific_and_optional():
    manifest = json.loads(_read(MANIFEST_PATH))
    webview2 = manifest["webview2"]

    assert webview2["defaultMode"] == "fixed"
    assert set(webview2["modes"]) == {"fixed", "evergreen"}
    datas = {str(item["source"]).replace("\\", "/"): item for item in manifest["datas"]}
    fixed = datas[webview2["fixedRuntimeSource"]]
    bootstrapper = datas[webview2["bootstrapperSource"]]
    # Both payloads are build-time hydrated; a missing one must never fail the build.
    assert fixed["optional"] is True
    assert bootstrapper["optional"] is True
    assert bootstrapper["target"] == webview2["bootstrapperTarget"]


def test_pyinstaller_spec_filters_datas_by_webview2_mode():
    source = _read(SPEC_PATH)

    assert "TIDYINVOICE_WEBVIEW2_MODE" in source
    assert "fixedRuntimeSource" in source
    assert "bootstrapperSource" in source
    assert 'webview2_mode == "evergreen"' in source


def test_build_release_script_supports_both_modes():
    source = _read(BUILD_RELEASE_PATH)

    assert '[ValidateSet("fixed", "evergreen")]' in source
    assert "TIDYINVOICE_WEBVIEW2_MODE" in source
    assert "WebView2 delivery mode:" in source
    # Evergreen builds must not require the fixed runtime payload.
    assert "$WebView2Mode -eq \"evergreen\"" in source


def test_prepare_runtime_script_downloads_bootstrapper_for_evergreen():
    source = _read(PREPARE_RUNTIME_PATH)

    assert '[ValidateSet("fixed", "evergreen", "both")]' in source
    assert "function Install-WebView2Bootstrapper" in source
    assert "bootstrapper.download_url" in source
    assert '$WebView2Mode -eq "evergreen"' in source


def test_release_workflow_and_qualification_script_pass_mode_through():
    workflow = _read(RELEASE_WORKFLOW_PATH)
    assert "webview2_mode:" in workflow
    assert "WEBVIEW2_MODE:" in workflow
    assert "-WebView2Mode $env:WEBVIEW2_MODE" in workflow

    qualify = _read(QUALIFY_SCRIPT_PATH)
    assert '[ValidateSet("fixed", "evergreen")]' in qualify
    assert "-WebView2Mode $WebView2Mode" in qualify

"""Brand single-source contract.

The product identity lives in ``brand.json``; Python and the desktop frontend
consume generated artifacts instead of hard-coding a product name. These tests
fail when the generated artifacts drift, when a runtime surface re-introduces a
brand literal, or when the packaged entry point stops verifying the brand file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import brand_generated
import build_identity
import user_settings

ROOT = Path(__file__).resolve().parents[1]
BRAND_PATH = ROOT / "brand.json"
PY_PATH = ROOT / "brand_generated.py"
JS_PATH = ROOT / "templates" / "brand.generated.js"
HTML_PATH = ROOT / "templates" / "index.html"
BUILT_PATH = ROOT / "templates" / "index_app.built.js"
GENERATE_SCRIPT = ROOT / "tools" / "brand" / "generate.mjs"
CHECK_SCRIPT = ROOT / "tools" / "brand" / "check.mjs"


def _brand() -> dict:
    return json.loads(BRAND_PATH.read_text(encoding="utf-8"))


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available in this environment")
    return node


def test_brand_json_covers_every_generated_field():
    brand = _brand()
    assert brand["schemaVersion"] == 1
    assert brand["identity"]["displayName"]["zh"]
    assert brand["identity"]["displayName"]["en"]
    assert brand["identity"]["slug"].islower()
    assert brand["runtime"]["appDirName"]
    assert brand["runtime"]["mutexName"].startswith("Local\\")
    assert brand["urls"]["repo"].startswith("https://")
    assert brand["upstream"]["author"]


def test_python_constants_track_brand_json():
    brand = _brand()
    assert brand_generated.BRAND_NAME == brand["identity"]["displayName"]["zh"]
    assert brand_generated.BRAND_NAME_EN == brand["identity"]["displayName"]["en"]
    assert brand_generated.BRAND_SLUG == brand["identity"]["slug"]
    assert brand_generated.BRAND_REPO_URL == brand["urls"]["repo"]
    assert brand_generated.APP_DIR_NAME == brand["runtime"]["appDirName"]
    assert list(brand_generated.LEGACY_APP_DIR_NAMES) == brand["runtime"]["legacyAppDirNames"]
    assert brand_generated.SINGLE_INSTANCE_MUTEX_NAME == brand["runtime"]["mutexName"]
    assert brand_generated.RULE_FILE_HEADER == brand["runtime"]["ruleFileHeader"]
    assert brand_generated.IMAP_CLIENT_NAME == brand["runtime"]["imapClientName"]
    assert brand_generated.WEBVIEW2_MODE_ENV == brand["env"]["webview2Mode"]
    assert brand_generated.RUN_CONTEXT_ENV_VAR == brand["env"]["runContextPath"]


def test_runtime_modules_read_the_brand_module():
    brand = _brand()
    assert user_settings.APP_DIR_NAME == brand["runtime"]["appDirName"]
    assert list(user_settings.LEGACY_APP_DIR_NAMES) == brand["runtime"]["legacyAppDirNames"]
    assert build_identity.build_runtime_identity()["baseline"] == brand_generated.BUILD_IDENTITY_NAME
    assert brand_generated.BUILD_IDENTITY_NAME == brand["runtime"]["buildIdentityName"]


def test_generated_artifacts_exist_and_carry_brand_values():
    brand = _brand()
    assert PY_PATH.is_file()
    assert JS_PATH.is_file()
    js = JS_PATH.read_text(encoding="utf-8")
    assert json.dumps(brand["identity"]["displayName"]["zh"], ensure_ascii=False) in js
    assert json.dumps(brand["urls"]["repo"]) in js
    assert json.dumps(brand["runtime"]["sessionStoragePrefix"]) in js


def test_html_loads_brand_before_the_app_bundle():
    html = HTML_PATH.read_text(encoding="utf-8")
    brand_index = html.find('<script src="./brand.generated.js"></script>')
    bundle_index = html.find('<script src="./index_app.built.js"></script>')
    assert brand_index >= 0, "index.html must load templates/brand.generated.js"
    assert bundle_index >= 0
    assert brand_index < bundle_index, "brand.generated.js must load before index_app.built.js"


def test_compiled_bundle_contains_no_brand_literal():
    built = BUILT_PATH.read_text(encoding="utf-8")
    brand = _brand()
    for token in (
        brand["identity"]["displayName"]["zh"],
        brand["identity"]["displayName"]["en"],
        brand["upstream"]["handle"],
        brand["upstream"]["npmScope"],
    ):
        assert token not in built, f"compiled bundle leaked brand literal: {token!r}"


def test_packaged_entry_point_verifies_the_brand_file():
    import main as main_module

    html_path = main_module._ensure_expected_frontend_assets(ROOT)
    assert html_path == HTML_PATH


def test_generate_script_reports_up_to_date_artifacts():
    node = _node()
    run = subprocess.run(
        [node, str(GENERATE_SCRIPT), "--check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert run.returncode == 0, f"brand artifacts drifted from brand.json:\n{run.stdout}\n{run.stderr}"


def test_runtime_surfaces_are_free_of_brand_literals():
    node = _node()
    run = subprocess.run(
        [node, str(CHECK_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert run.returncode == 0, f"runtime brand literals detected:\n{run.stdout}\n{run.stderr}"

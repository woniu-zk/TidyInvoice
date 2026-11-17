"""Frontend build contract for the no-API local-recognition frontend.

Covers:
- JSX is precompiled at build time into templates/index_app.built.js
- templates/index.html no longer loads Babel or Tailwind at runtime
- the strict CSP is present and compatible with the precompiled bundle
- settings UI no longer exposes API-key / AI-provider fields
- main.py validates the built bundle and enforces a single application instance
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
HTML_PATH = TEMPLATES / "index.html"
SOURCE_PATH = TEMPLATES / "index_app.js"
BUILT_PATH = TEMPLATES / "index_app.built.js"
STATIC_DIR = TEMPLATES / "static"
TOOLS_DIR = ROOT / "tools"
COMPILE_SCRIPT = TOOLS_DIR / "compile-frontend.mjs"
BABEL_PATH = TOOLS_DIR / "vendor" / "babel.min.js"
MAIN_PATH = ROOT / "main.py"

CSP_CONTENT = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'none'; base-uri 'none'; "
    "form-action 'none'"
)
RUNTIME_SCRIPTS = [
    "./static/react.min.js",
    "./static/react-dom.min.js",
    "./static/history.min.js",
    "./static/react-router.min.js",
    "./static/react-router-dom.min.js",
    "./index_app.built.js",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_built_bundle_exists_and_keeps_frontend_markers():
    assert BUILT_PATH.is_file(), "templates/index_app.built.js is missing; run node tools/compile-frontend.mjs"
    built = _read(BUILT_PATH)
    assert len(built.encode("utf-8")) > 10_000, "compiled bundle looks empty"
    for marker in ('name: "InvoiceFlowAI"', 'subtitle: "AI发票管家', "const APP_VISIBLE_COPY = {"):
        assert marker in built, f"compiled bundle lost marker: {marker!r}"
    assert "React.createElement(" in built, "compiled bundle does not look like Babel output"
    assert "</div>" not in built, "compiled bundle still contains raw JSX"
    assert "eval(" not in built, "compiled bundle must stay CSP-safe (no eval)"


def test_html_loads_precompiled_bundle_only():
    html = _read(HTML_PATH)
    assert '<script src="./index_app.built.js"></script>' in html
    assert "text/babel" not in html
    assert "babel.min.js" not in html
    assert "tailwind.min.css" not in html
    assert "./index_app.js" not in html

    script_sources = re.findall(r'<script[^>]*\bsrc="([^"]+)"', html)
    assert script_sources == RUNTIME_SCRIPTS
    assert len(re.findall(r"<script\b", html)) == len(RUNTIME_SCRIPTS)


def test_static_assets_no_longer_ship_babel_or_tailwind():
    static_names = {path.name for path in STATIC_DIR.iterdir() if path.is_file()}
    assert "babel.min.js" not in static_names
    assert "tailwind.min.css" not in static_names
    for required in (
        "react.min.js",
        "react-dom.min.js",
        "history.min.js",
        "react-router.min.js",
        "react-router-dom.min.js",
        "material-symbols-outlined.ttf",
    ):
        assert required in static_names
    assert BABEL_PATH.is_file(), "build-time Babel must stay vendored under tools/vendor"
    assert BABEL_PATH.stat().st_size > 1_000_000


def test_strict_csp_meta_is_present():
    html = _read(HTML_PATH)
    meta_matches = re.findall(
        r'<meta[^>]+http-equiv="Content-Security-Policy"[^>]+content="([^"]+)"',
        html,
    )
    assert len(meta_matches) == 1, "expected exactly one CSP meta tag"
    normalized_csp = " ".join(meta_matches[0].split())
    assert normalized_csp == CSP_CONTENT
    assert "unsafe-eval" not in normalized_csp
    assert "script-src 'self'" in normalized_csp


def test_settings_ui_no_longer_exposes_api_key_or_provider_fields():
    source = _read(SOURCE_PATH)
    removed_fragments = [
        "API Key",
        "api_key",
        "deepseek_api_key",
        "ai_provider",
        "DEEPSEEK_PLATFORM_URL",
        "ZHIPU_PLATFORM_URL",
        "showApiKey",
        "apiStatus",
        "activeApiKey",
        "智能处理引擎",
        "模型服务",
    ]
    for fragment in removed_fragments:
        assert fragment not in source, f"settings UI still references {fragment!r}"

    # Local recognition engine block replaces the former AI provider card.
    assert 'title="本地识别引擎"' in source
    assert "PDF 文本解析" in source
    assert "OFD 解析" in source
    assert "本地 OCR" in source
    assert "无需联网" in source

    assert 'callApi("start_processing", "", settings.save_path, runSettings.date_from, runSettings.date_to, String(settings.email).trim(), settings.auth_code)' in source
    assert re.search(
        r'callApi\(\s*"test_connection",\s*String\(settings\.email\)\.trim\(\),\s*String\(settings\.auth_code\)\.trim\(\)\s*\)',
        source,
    ), "test_connection must only send email and auth_code"
    assert "test_email_auth" not in source


def test_main_entrypoint_checks_built_bundle_and_single_instance_guard():
    main_source = _read(MAIN_PATH)
    assert '"templates" / "index_app.built.js"' in main_source
    assert '"templates" / "index_app.js"' not in main_source
    for marker in ("CreateMutexW", "SINGLE_INSTANCE_MUTEX_NAME", "fcntl.flock", "已在运行"):
        assert marker in main_source
    assert "def _acquire_single_instance_guard(" in main_source
    assert "def _show_already_running_message(" in main_source
    assert "_acquire_single_instance_guard()" in main_source
    assert "return 2" in main_source

    import main as main_module

    assert callable(main_module._acquire_single_instance_guard)
    assert callable(main_module._show_already_running_message)
    assert callable(main_module._ensure_expected_frontend_assets)
    html_path = main_module._ensure_expected_frontend_assets(ROOT)
    assert html_path == HTML_PATH


def test_compile_script_exposes_deterministic_check_mode():
    script = _read(COMPILE_SCRIPT)
    assert "--check" in script
    assert "sha256" in script
    assert "babel.min.js" in script
    assert "templates" in script


def test_node_build_check_matches_committed_bundle():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available in this environment")

    check = subprocess.run(
        [node, str(COMPILE_SCRIPT), "--check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert check.returncode == 0, f"node tools/compile-frontend.mjs --check failed:\n{check.stdout}\n{check.stderr}"
    sha_match = re.search(r"sha256=([0-9a-f]{64})", check.stdout)
    assert sha_match, f"compile check did not report a SHA256:\n{check.stdout}"
    expected_sha = hashlib.sha256(BUILT_PATH.read_bytes()).hexdigest()
    assert sha_match.group(1) == expected_sha

    syntax_check = subprocess.run(
        [node, "--check", str(BUILT_PATH)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert syntax_check.returncode == 0, syntax_check.stderr

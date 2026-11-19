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
import json
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


_JS_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _decode_js_unicode_escapes(text: str) -> str:
    """Babel escapes non-ASCII JSX text as ``\\uXXXX``; decode for copy checks."""
    return _JS_UNICODE_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), text)


def test_task_mode_ui_follows_organize_frontend_contract():
    """三种任务模式（mail / fetch / local）必须按本地整理契约实现。"""
    source = _read(SOURCE_PATH)
    built = _decode_js_unicode_escapes(_read(BUILT_PATH))


    mode_copy = (
        "邮箱提取并整理",
        "仅提取到 inbox",
        "本地文件夹整理",
        "开始整理",
        "整理进目录",
        "按分类分目录",
        "仅提取完成",
        "本地整理完成",
        "附件已保存到 inbox 文件夹，并写入 manifest.jsonl；未进行识别和归档。",
        "已按分类与命名规则归档本地发票；原件已原样保留在「整理前发票」文件夹（文件名不变），重复文件已移入 duplicates 文件夹。",
        "已按分类与命名规则归档本地发票；原始文件保留在发票文件夹，未移动。",
        "已按命名规则整理本地发票（未建分类子目录）；原件已原样保留在「整理前发票」文件夹（文件名不变），重复文件已移入 duplicates 文件夹。",
        "已按命名规则整理本地发票（未建分类子目录）；原始文件保留在发票文件夹，未移动。",
        "默认同发票文件夹",
        "恢复默认（发票文件夹）",
    )
    persistence_fields = ("task_mode", "local_input_dir", "local_output_dir", "local_split_by_category")
    for marker in mode_copy + persistence_fields:
        assert marker in source, f"task mode UI is missing {marker!r}"
        assert marker in built, f"compiled bundle is missing {marker!r}"

    # 本地模式不再提供预览入口。
    for removed in (
        "开始预览",
        "仅预览，不移动文件",
        "本地预览完成",
        "local_dry_run",
        "localPreviewLabel",
    ):
        assert removed not in source, f"legacy preview UI still present: {removed!r}"
        assert removed not in built, f"compiled bundle still contains preview UI: {removed!r}"

    # fetch 模式：savePath, dateFrom, dateTo, email, authCode
    assert (
        'callApi("start_fetch_only", settings.save_path, runSettings.date_from, runSettings.date_to, '
        "String(settings.email).trim(), settings.auth_code)"
    ) in source
    # local 模式：inputDir, effectiveOutput（默认等于发票文件夹）, dry_run=false, 分目录选项
    assert (
        'callApi("start_local_organize", inputDir, outputDir, false, localSplitByCategory)'
    ) in source
    # mail 模式：沿用原调用，rules_text 传空
    assert (
        'callApi("start_processing", "", settings.save_path, runSettings.date_from, runSettings.date_to, '
        "String(settings.email).trim(), settings.auth_code)"
    ) in source

    start_calls = re.findall(r'callApi\("(start_[a-z_]+)"', source)
    assert sorted(start_calls) == ["start_fetch_only", "start_local_organize", "start_processing"], start_calls


def test_settings_top_level_cards_never_flex_shrink_into_slivers():
    """Regression: the 任务类型 card must not be flex-shrunk to a 1px sliver.

    The settings page is a flex column; a new top-level card without an explicit
    ``flex: 0 0 auto`` was shrunk to one pixel by the page layout, so the whole
    mode selector was invisible while still present in the DOM.
    """
    html = _read(HTML_PATH)
    normalized = " ".join(html.split())
    assert ".page-wrap--settings > .surface-card" in normalized, (
        "top-level settings cards need an explicit flex-shrink opt-out"
    )
    assert ".page-wrap--settings { min-height: 100%; height: auto; justify-content: flex-start;" in normalized
    assert normalized.count("flex: 0 0 auto") >= 2


def test_toggle_checkboxes_keep_a_visible_native_box():
    """Regression: the global input reset stripped the native checkbox glyph.

    ``input:not([type="date"]) { appearance: none }`` removed the box and tick,
    so 「按分类分目录」/「自动记住当前配置」 rendered as invisible 18x18 hit
    areas while the label text stayed visible.
    """
    html = " ".join(_read(HTML_PATH).split())
    assert '.toggle-row input[type="checkbox"]' in html
    rule_start = html.index('.toggle-row input[type="checkbox"]')
    rule = html[rule_start:rule_start + 320]
    assert "appearance: auto" in rule
    assert "-webkit-appearance: auto" in rule
    # The global reset stays for the text inputs; the toggle rule must override it.
    assert 'input:not([type="date"]), select { appearance: none' in html


# --------------------------------------------------------------------------- #
# Expense classification rules page (/rules) - target types redesign
# --------------------------------------------------------------------------- #

RULES_NAV_ITEM = (
    '{ key: "rules", label: "归类规则", description: "目标票种、关键词与金额", '
    'icon: "rule", path: "/rules" }'
)
RULES_ROUTE = (
    '<Route path="/rules" element={<RulesPage onOpenDisclaimer={() => '
    "setShowDisclaimer(true)} />} />"
)
RULES_VISIBLE_COPY = (
    "归类规则",
    "全局规则",
    "当前发票库",
    "规则作用范围",
    "规则列表",
    "词典与测试",
    "票种管理",
    "自定义规则",
    "新增规则",
    "编辑规则",
    "关键词",
    "金额下限",
    "金额上限",
    "启用",
    "目标票种",
    "新建票种",
    "确认新建",
    "归档到",
    "内置默认规则",
    "规则从上到下匹配",
    "命中第一条即停止",
    "内置票种",
    "自定义票种",
    "自定义票种全局可用，全局规则和当前发票库规则都能选择",
    "自定义票种是规则的目标票种",
    "内置票种是发票识别结果",
    "销售方词典",
    "销售方名称或税号",
    "添加词典",
    "规则测试",
    "测试归类结果",
    "将进入待人工复核",
    "未归类发票",
    "据此新建规则",
    "保存规则",
    "重新加载",
    "恢复默认",
    "打开规则目录",
    "费用归类规则",
    "管理归类规则",
    "分类汇总",
    "在界面保存会重写当前作用范围的规则文件",
    "请选择目标票种",
    "条 · 可覆盖",
    "已修改",
    "编辑内置规则",
    "全部恢复默认",
    "保存覆盖",
    "内置规则原有的票种兜底条件会自动保留",
    "只按票种兜底",
    "缺少目标票种",
    "确认恢复",
    "恢复范围",
    "仅当前作用范围",
    "只删除当前作用范围（",
    "全局 + 当前发票库",
    "将删除内置规则的自定义覆盖，恢复出厂默认；会先自动备份",
    "当前有未保存的修改，恢复默认后会重新加载规则并丢弃这些修改",
    "同时清理全局规则和当前发票库的内置覆盖",
    "当前没有可用发票库，无法选择",
)

_RULES_BUNDLE_DRIVER_JS = r'''
const fs = require("node:fs");
const vm = require("node:vm");
let code = fs.readFileSync(process.argv[2], "utf8");
const lines = code.trimEnd().split("\n");
if (lines[lines.length - 1].includes("root.render(")) lines.pop();
if (lines[lines.length - 1].includes("createRoot(")) lines.pop();
const sandbox = {
    console,
    process,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    document: {
        getElementById: () => ({}),
        createElement: () => ({ style: {}, setAttribute() {}, appendChild() {}, click() {} }),
        body: { appendChild() {}, removeChild() {} },
    },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.React = {
    useState: (value) => [value, () => {}],
    useEffect: () => {},
    useMemo: (factory) => factory(),
    useRef: (value) => ({ current: value }),
    createElement: () => null,
    Fragment: {},
};
sandbox.ReactDOM = { createRoot: () => ({ render: () => {} }) };
sandbox.ReactRouterDOM = {
    MemoryRouter: () => null,
    Routes: () => null,
    Route: () => null,
    useNavigate: () => () => {},
};
vm.createContext(sandbox);
vm.runInContext(lines.join("\n"), sandbox, { filename: "index_app.built.js" });
const probeSource = fs.readFileSync(process.argv[3], "utf8");
vm.runInContext(probeSource, sandbox, { filename: "rules_probe.js" });
console.log(JSON.stringify(sandbox.__probeResult));
'''

_RULES_BUNDLE_PROBE_JS = r'''
globalThis.__probeResult = (function () {
    var legacyOne = normalizeUserRuleEntry({ id: "rule_1", keywords: ["滴滴"], invoice_types: ["打车"] });
    var legacyMany = normalizeUserRuleEntry({ id: "rule_2", keywords: ["x"], invoice_types: ["打车", "餐饮"] });
    var explicit = normalizeUserRuleEntry({ id: "rule_3", keywords: ["x"], target_type: "会议", invoice_types: ["打车"] });
    var saved = toSaveUserRule({
        id: "rule_4",
        name: "",
        target_type: "酒店",
        mainKeyword: "酒店",
        legacyExtraKeywords: ["住宿"],
        amount_range: [100, 200],
        enabled: true,
        match: "seller",
        exclude_keywords: ["充值"],
    });
    var mixedDraft = buildUserRuleDraft({
        categories: [
            { id: "taxi", name: "打车", archive_folder: "打车", keywords: ["滴滴"], amount_range: [], invoice_types: ["打车"], enabled: true },
            { id: "rule_9", target_type: "会议", keywords: ["会议费"], amount_range: [] },
        ],
        terms: [],
    }, "global", ["taxi", "meal"], ["打车", "会议", "餐饮"]);
    var invalidLegacyDraft = buildUserRuleDraft({
        categories: [
            { id: "meal", name: "旧名称", archive_folder: "旧文件夹", keywords: ["餐"], amount_range: [], enabled: true },
        ],
        terms: [],
    }, "global", ["meal"], ["打车", "会议", "餐饮"]);
    var savedBuiltin = toSaveBuiltinOverride({
        id: "taxi",
        name: "打车",
        archive_folder: "打车文件夹",
        keywords: ["滴滴", "出租"],
        amount_range: [100, null],
        invoice_types: ["打车", "餐饮"],
        enabled: false,
        target_type: "会议",
        priority: 10,
    });
    return {
        folders: {
            none: buildRuleFolderName("酒店", []),
            range: buildRuleFolderName("酒店", [100, 200]),
            minOnly: buildRuleFolderName("酒店", [100, null]),
            maxOnly: buildRuleFolderName("酒店", [null, 200]),
            equal: buildRuleFolderName("酒店", [100, 100]),
            negative: buildRuleFolderName("酒店", [-200, -100]),
            decimal: buildRuleFolderName("会议", [100.5, null]),
            emptyType: buildRuleFolderName("", [100, 200]),
        },
        legacyOneTarget: legacyOne.target_type,
        legacyManyTarget: legacyMany.target_type,
        explicitTarget: explicit.target_type,
        previewFolder: ruleEntryPreviewFolder(legacyOne),
        saved: saved,
        savedKeys: Object.keys(saved).sort(),
        mixedUserIds: mixedDraft.categories.map(function (item) { return item.id; }),
        mixedBuiltinIds: mixedDraft.builtinOverrides.map(function (item) { return item.id; }),
        mixedBuiltinTarget: mixedDraft.builtinOverrides[0].target_type,
        mixedBuiltinKeys: Object.keys(mixedDraft.builtinOverrides[0]).sort(),
        invalidLegacyTarget: invalidLegacyDraft.builtinOverrides[0].target_type,
        savedBuiltin: savedBuiltin,
        savedBuiltinKeys: Object.keys(savedBuiltin).sort(),
    };
})();
'''


def test_rules_route_navigation_and_backend_calls():
    source = _read(SOURCE_PATH)
    assert RULES_NAV_ITEM in source, "navigation is missing the /rules entry"
    assert RULES_ROUTE in source, "App routes are missing the /rules RulesPage route"
    assert "function RulesPage(" in source

    # Exactly one startup status probe (Settings bootstrap), never the 3s polling.
    assert source.count('callApi("get_classification_rules_status")') == 1
    assert "setInterval(loadResults, 3000)" in source, "analysis polling contract changed"

    for marker in (
        'callApi("load_classification_rules", "")',
        'callApi("load_classification_rules", libraryDir)',
        'callApi("save_classification_rules", {',
        'callApi("reset_classification_rules", scope, libraryDir)',
        'callApi("reset_builtin_classification_rules", {',
        'callApi("open_rules_folder", scope, libraryDir)',
        'callApi("test_classification_rules", {',
        'callApi("create_classification_type", { name })',
        'callApi("delete_classification_type", { name, library_dir: libraryDir })',
    ):
        assert marker in source, f"rules page is missing API call {marker!r}"

    # Restore confirm dialog passes scope mode + optional category id.
    for marker in (
        "scope_mode: restoreMode",
        "category_id: restoreDialog.categoryId || \"\"",
        'scope_mode: restoreMode,',
    ):
        assert marker in source, f"builtin restore API payload is missing {marker!r}"

    # Saving sends the whole current-scope rule list with target types and
    # built-in overrides (builtin ids keep the builtin field contract).
    assert "categories: draft.categories.map(toSaveUserRule).concat((draft.builtinOverrides || []).map(toSaveBuiltinOverride))" in source
    assert "terms: draft.terms.map(toSaveRuleTerm)" in source
    assert "fallback: draft.fallback || \"\"" in source
    assert "target_type: targetType" in source


def test_rules_page_visible_copy_stays_product_facing():
    source = _read(SOURCE_PATH)
    built = _decode_js_unicode_escapes(_read(BUILT_PATH))
    for marker in RULES_VISIBLE_COPY:
        assert marker in source, f"rules page copy is missing {marker!r}"
        assert marker in built, f"compiled bundle is missing rules copy {marker!r}"

    forbidden = (
        "TODO",
        "FIXME",
        "mockup",
        "设计稿",
        "实现说明",
        "保留原有",
        "只重做",
        "仅重构",
        "Apple",
        "phase 1",
    )
    for fragment in forbidden:
        assert fragment not in source, f"developer-facing copy leaked: {fragment!r}"
        assert fragment not in built, f"compiled bundle leaked developer copy: {fragment!r}"


def test_rules_page_removed_concepts_are_gone():
    source = _read(SOURCE_PATH)
    built = _decode_js_unicode_escapes(_read(BUILT_PATH))
    html = _read(HTML_PATH)
    for fragment in (
        "自动文件夹",
        "适用票种",
        "优先级",
        "priority",
        "auto_folder",
        "buildAutoFolderName",
        "sanitizeRuleKeyword",
        "handleEditorToggleType",
    ):
        assert fragment not in source, f"removed rules concept still referenced: {fragment!r}"
    for fragment in ("自动文件夹", "适用票种", "优先级", "priority", "auto_folder"):
        assert fragment not in built, f"compiled bundle still shows removed concept: {fragment!r}"
    for fragment in (".rule-chip-select", ".rule-ticket-tag", ".rule-auto-folder"):
        assert fragment not in html, f"obsolete rules style still present: {fragment!r}"


def test_rules_target_type_folder_contract(tmp_path=None):
    source = _read(SOURCE_PATH)
    for marker in (
        "function buildRuleFolderName(",
        "const suffix = amountRangeFolderSuffix(amountRange);",
        "return suffix ? `${typeName}-${suffix}` : typeName;",
        "function normalizeUserRuleEntry(",
        "const legacyInvoiceTypes = (Array.isArray(source.invoice_types)",
        "if (!targetType && legacyInvoiceTypes.length === 1) targetType = legacyInvoiceTypes[0];",
        "function ruleEntryPreviewFolder(",
        "function handleAddRule(",
        "function handleEditRule(",
        "function handleDeleteRule(",
        "function handleMoveRule(",
        "function handleToggleRule(",
        "handleMoveRule(row.index, -1)",
        "handleMoveRule(row.index, 1)",
        "handleDeleteRule(row.index)",
        "handleToggleRule(row.index)",
        "handleEditRule(row.index)",
        "formatRuleAmountRangeLabel(row.amount_range)",
        "rule-category-row__name",
        "rule-target-tag",
        "缺少目标票种",
    ):
        assert marker in source, f"target-type rule contract is missing {marker!r}"
    # Flat list only, still in declaration order.
    assert "rows.sort" not in source
    assert "buildRuleRows" not in source


def test_rules_editor_target_type_and_archive_preview_contract():
    source = _read(SOURCE_PATH)
    for marker in (
        "function RuleEditor(",
        "function emptyUserRuleEditor(",
        "function userRuleEditorFromEntry(",
        "目标票种",
        "新建票种",
        "确认新建",
        "rule-target-row",
        "rule-archive-summary",
        "归档到",
        "buildRuleFolderName(editor.targetType",
        "RULE_TARGET_TYPE_HELP",
        "请选择目标票种",
        "function toSaveUserRule(",
        "target_type: targetType",
        "keywords: [keyword].concat(extraKeywords)",
        "amount_range: normalizeRuleAmountRange(source.amount_range)",
        "disabled={saving || loading || missingTargetCount > 0 || missingBuiltinTargetCount > 0}",
        "没有选择目标票种，请逐条编辑补选后再保存",
    ):
        assert marker in source, f"target-type editor is missing {marker!r}"

    # Legacy fields are preserved in the saved payload without being exposed.
    for marker in (
        "if (source.match) payload.match = String(source.match);",
        "payload.exclude_keywords",
        "legacyExtraKeywords",
        "legacyExcludeKeywords",
    ):
        assert marker in source, f"legacy rule fields are not preserved: {marker!r}"

    # Blocking save for unmigrated legacy rules.
    assert "const missingTargetCount = useMemo(" in source
    assert "const missingBuiltinTargetCount = useMemo(" in source
    assert "if (missingTargetCount > 0 || missingBuiltinTargetCount > 0)" in source


def test_rules_custom_type_management_contract():
    source = _read(SOURCE_PATH)
    built = _decode_js_unicode_escapes(_read(BUILT_PATH))
    for marker in (
        "function RuleTypesManager(",
        "payload.custom_types",
        "payload.builtin_types",
        "Array.isArray(payload.document_types)",
        "async function handleCreateType(",
        "async function handleDeleteType(",
        "callApi(\"create_classification_type\", { name })",
        "callApi(\"delete_classification_type\", { name, library_dir: libraryDir })",
        "applyTypeSnapshot(",
        "setTypeIssues",
        "票种操作未完成",
        "自定义票种全局可用，全局规则和当前发票库规则都能选择",
        "内置票种",
        "自定义票种",
        "rules-types-layout",
        "rules-type-row",
        "rule-type-chip",
        'label: "票种管理"',
        'activePanel === "types"',
        "aria-label={`删除票种 ${name}`}",
    ):
        assert marker in source, f"custom type management is missing {marker!r}"
    # Built-in types are rendered read-only; only custom types get delete buttons.
    assert "builtinTypes.map((name) => <span key={name} className=\"rule-type-chip\">" in source
    assert "customTypes.map((name) => (" in source
    for marker in ("票种管理", "内置票种", "自定义票种"):
        assert marker in built, f"compiled bundle is missing type copy {marker!r}"


def test_rules_test_result_and_unclassified_prefill_contract():
    source = _read(SOURCE_PATH)
    built = _decode_js_unicode_escapes(_read(BUILT_PATH))
    for marker in (
        "目标票种",
        "归档到",
        "命中关键词",
        "规则位置",
        "result.target_type",
        "result.archive_folder",
        "targetTypeById",
        "result.chain",
        "匹配过程",
    ):
        assert marker in source, f"rule test result is missing {marker!r}"
    assert "result.priority" not in source
    assert "将进入待人工复核" in built

    # Unclassified helper prefills keyword + exact amount; target type stays blank.
    for marker in (
        "function handlePrefillFromInvoice(",
        "unclassified_invoices",
        "form.keyword = merchant",
        "form.amountMin = amount === null ? \"\" : String(amount)",
        "form.amountMax = amount === null ? \"\" : String(amount)",
        "请选择目标票种后添加到列表",
        "据此新建规则",
    ):
        assert marker in source, f"unclassified helper is missing {marker!r}"
    assert "replace(/[¥￥元,\\s]/g" in source, "parseRuleAmount must strip currency markers"
    assert "parseRuleAmount(invoice.amount)" in source
    assert "function formatRuleInvoiceAmountLabel(" in source
    assert "formatRuleInvoiceAmountLabel(row.amount)" in source


def _extract_js_function(source, name):
    start = source.index(f"function {name}(")
    next_start = source.find("\nfunction ", start + 1)
    return source[start:] if next_start < 0 else source[start:next_start]


def test_rules_builtin_rules_split_and_editable_contract():
    source = _read(SOURCE_PATH)
    built = _decode_js_unicode_escapes(_read(BUILT_PATH))
    # Split raw scope categories by backend builtin_category_ids: the main
    # custom-rule list only receives ids that are not builtin.
    for marker in (
        "rulesData.builtin_category_ids",
        "payload.builtin_category_ids",
        "const builtinIdSet = useMemo(",
        'buildUserRuleDraft(payload.global, "global", loadedBuiltinIds, documentTypes)',
        'buildUserRuleDraft(payload.library, "library", loadedBuiltinIds, documentTypes)',
        "draft.builtinOverrides",
        "function normalizeBuiltinOverride(",
        "function toSaveBuiltinOverride(",
        "function isValidRuleTargetType(",
        "function RuleBuiltinSection(",
        "function RuleBuiltinEditor(",
        "内置默认规则",
        "条 · 可覆盖",
        "已修改",
        "全部恢复默认",
        "编辑内置规则",
        "保存覆盖",
        "内置规则原有的票种兜底条件会自动保留",
        "只按票种兜底",
        "缺少目标票种",
        "请选择目标票种",
        "onEdit={handleEditBuiltinRule}",
        "onToggle={handleToggleBuiltinRule}",
        "onRestore={handleRestoreBuiltinRule}",
        "onRestoreAll={handleRestoreAllBuiltin}",
        "onCreateType={handleCreateType}",
        "documentTypes={documentTypes}",
    ):
        assert marker in source, f"editable builtin rules contract is missing {marker!r}"
    # Built-in editor uses the same target-type model as new rules.
    editor = _extract_js_function(source, "RuleBuiltinEditor")
    for marker in (
        "目标票种",
        "新建票种",
        "确认新建",
        "关键词",
        "金额下限",
        "金额上限",
        "启用",
        "归档到",
        "rule-archive-summary",
        "buildRuleFolderName(editor.targetType",
        'documentTypes.map((type) => ({ value: type, label: type }))',
    ):
        assert marker in editor, f"builtin editor is missing {marker!r}"
    for forbidden in (
        'field-label">名称',
        'field-label">归档文件夹',
        'field-label">适用票种',
        "rule-chip-select",
        "invoiceTypes",
    ):
        assert forbidden not in editor, f"builtin editor still contains removed field {forbidden!r}"
    # Built-in row default target comes from target_type || archive_folder and
    # is validated against registered document types.
    assert "(item.target_type || item.archive_folder || \"\")" in source
    assert "isValidRuleTargetType(candidateTarget, documentTypes)" in source
    assert "previewFolder: buildRuleFolderName(targetType, amountRange)" in source
    assert "missingBuiltinTargetCount" in source
    assert "有 {missingBuiltinTargetCount} 条内置规则修改还没有选择目标票种" in source
    assert "disabled={saving || loading || missingTargetCount > 0 || missingBuiltinTargetCount > 0}" in source
    # The old read-only section is gone.
    assert "function RuleBuiltinDefaults(" not in source
    assert "条 · 只读" not in source
    for marker in ("内置默认规则", "已修改", "全部恢复默认", "保存覆盖", "缺少目标票种"):
        assert marker in built, f"compiled bundle is missing builtin editing copy {marker!r}"


def test_rules_builtin_restore_dialog_and_api_contract():
    source = _read(SOURCE_PATH)
    built = _decode_js_unicode_escapes(_read(BUILT_PATH))
    for marker in (
        "function RuleRestoreDialog(",
        "function openRestoreDialog(",
        "function handleRestoreBuiltinRule(",
        "function handleRestoreAllBuiltin(",
        "async function handleConfirmRestoreBuiltin(",
        'callApi("reset_builtin_classification_rules", {',
        "scope_mode: restoreMode",
        "category_id: restoreDialog.categoryId || \"\"",
        "仅当前作用范围",
        "全局 + 当前发票库",
        "将删除内置规则的自定义覆盖，恢复出厂默认；会先自动备份",
        "当前有未保存的修改，恢复默认后会重新加载规则并丢弃这些修改",
        "确认恢复",
        "disabled={!libraryAvailable}",
        "role=\"radiogroup\"",
        "type=\"radio\"",
        "await reloadRules({ silent: true })",
    ):
        assert marker in source, f"builtin restore dialog contract is missing {marker!r}"
    # The API receives the current scope; scope_mode expands it server-side.
    assert "scope,\n                library_dir: libraryDir,\n                scope_mode: restoreMode,\n                category_id: restoreDialog.categoryId || \"\"," in source
    # Two-step: row/header restore buttons only open the dialog; the dialog's
    # confirm button performs the API call.
    assert "onClick={() => onRestore(row)}" in source
    assert "onClick={onRestoreAll}" in source
    assert "onClick={onConfirm}" in source
    assert "onClick={onCancel}" in source
    for marker in ("恢复默认", "仅当前作用范围", "全局 + 当前发票库", "确认恢复"):
        assert marker in built, f"compiled bundle is missing restore copy {marker!r}"


def test_rules_auto_folder_preview_formats_match_contract(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available in this environment")
    driver = tmp_path / "rules_bundle_driver.cjs"
    probe = tmp_path / "rules_bundle_probe.js"
    driver.write_text(_RULES_BUNDLE_DRIVER_JS, encoding="utf-8")
    probe.write_text(_RULES_BUNDLE_PROBE_JS, encoding="utf-8")
    run = subprocess.run(
        [node, str(driver), str(BUILT_PATH), str(probe)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert run.returncode == 0, f"node probe failed:\n{run.stdout}\n{run.stderr}"
    data = json.loads(run.stdout.strip().splitlines()[-1])
    assert data["folders"] == {
        "none": "酒店",
        "range": "酒店-100-200",
        "minOnly": "酒店-100以上",
        "maxOnly": "酒店-200以下",
        "equal": "酒店-100",
        "negative": "酒店--200至-100",
        "decimal": "会议-100.5以上",
        "emptyType": "",
    }
    assert data["legacyOneTarget"] == "打车"
    assert data["legacyManyTarget"] == ""
    assert data["explicitTarget"] == "会议"
    assert data["previewFolder"] == "打车"
    saved = data["saved"]
    assert saved["target_type"] == "酒店"
    assert saved["name"] == "酒店-100-200"
    assert saved["keywords"] == ["酒店", "住宿"]
    assert saved["amount_range"] == [100, 200]
    assert saved["match"] == "seller"
    assert saved["exclude_keywords"] == ["充值"]
    assert data["savedKeys"] == [
        "amount_range",
        "enabled",
        "exclude_keywords",
        "id",
        "keywords",
        "match",
        "name",
        "target_type",
    ]
    # Builtin overrides are split out of user rules, derive a target type and
    # keep only the target-type rule payload.
    assert data["mixedUserIds"] == ["rule_9"]
    assert data["mixedBuiltinIds"] == ["taxi"]
    assert data["mixedBuiltinTarget"] == "打车"
    assert data["mixedBuiltinKeys"] == ["amount_range", "enabled", "id", "keywords", "target_type"]
    # Legacy override with a non-type archive folder must require a new target.
    assert data["invalidLegacyTarget"] == ""
    assert data["savedBuiltin"] == {
        "id": "taxi",
        "target_type": "会议",
        "keywords": ["滴滴", "出租"],
        "amount_range": [100, None],
        "enabled": False,
    }
    assert data["savedBuiltinKeys"] == [
        "amount_range",
        "enabled",
        "id",
        "keywords",
        "target_type",
    ]


def test_settings_page_cards_the_classification_rules_entry():
    source = _read(SOURCE_PATH)
    assert 'title="费用归类规则"' in source
    assert 'onClick={() => navigate("/rules")}' in source
    assert "按目标票种、关键词与金额范围生成归档文件夹" in source
    assert 'callApi("get_classification_rules_status").catch(() => ({}))' in source
    assert "rulesStatus: rulesStatusRes || {}" in source
    assert "const [rulesStatus, setRulesStatus] = useState({});" in source
    assert "setRulesStatus(state.rulesStatus || {});" in source
    assert "const rulesIssues = normalizeRuleIssues(rulesStatus && rulesStatus.issues);" in source
    assert "归类规则配置需要确认" in source


def test_analysis_page_shows_classification_summary_and_rules_banner():
    source = _read(SOURCE_PATH)
    built = _decode_js_unicode_escapes(_read(BUILT_PATH))
    for marker in (
        "summary.classification_breakdown",
        "summary.classification_source_breakdown",
        "summary.unclassified_count",
        "classificationEntries",
        "classificationSourceEntries",
        "classificationSourceLabel",
        "检测到 ${unclassifiedCount} 张发票未归类",
    ):
        assert marker in source, f"analysis page is missing {marker!r}"
    for marker in (
        "分类汇总",
        "归类提示",
        "管理归类规则",
    ):
        assert marker in source, f"analysis page copy is missing {marker!r}"
        assert marker in built, f"compiled bundle is missing analysis copy {marker!r}"


def test_rules_page_top_level_cards_never_flex_shrink_into_slivers():
    html = " ".join(_read(HTML_PATH).split())
    assert ".page-wrap--rules { min-height: 100%; height: auto; justify-content: flex-start;" in html, (
        "the rules page wrap needs the same flex guard as the settings page"
    )
    assert ".page-wrap--rules > .surface-card { flex: 0 0 auto; min-height: auto; }" in html
    assert ".page-wrap--rules > .rules-panel," in html
    assert ".page-wrap--rules > .rules-builtin," in html
    assert ".page-wrap--rules > .rules-types-layout," in html
    assert ".page-wrap--analysis, .page-wrap--rules {" in html, "rules page must join the flex-column page-wrap group"
    # The analysis page carries the classification summary + unclassified banner;
    # its hero card must not be flex-shrunk into clipping its own content.
    assert ".page-wrap--analysis { min-height: 100%; height: auto; justify-content: flex-start;" in html
    assert ".page-wrap--analysis > .surface-card," in html
    for marker in (
        ".rules-panel {",
        ".rules-tabbar {",
        ".rules-layout {",
        "grid-template-columns: minmax(0, 1.18fr) minmax(0, 1fr)",
        ".rules-types-layout {",
        ".rules-tools-layout {",
        ".rules-column {",
        ".rule-category-row {",
        ".rule-category-row__name--missing",
        ".rule-target-row {",
        ".rule-target-tag {",
        ".rule-archive-summary {",
        ".rule-type-create {",
        ".rule-type-chip {",
        ".rules-type-row {",
        ".rules-kv-list {",
        ".rule-dictionary-row {",
        ".rule-unclassified-row {",
        ".rules-builtin {",
        ".rules-builtin-row {",
        ".rules-builtin-row__folder {",
        ".rules-builtin-row__actions {",
        ".rule-textarea {",
        ".restore-dialog {",
        ".restore-options {",
        ".restore-option {",
        ".classification-summary {",
    ):
        assert marker in html, f"rules page styles are missing {marker!r}"
    assert ".rules-builtin__summary" not in html
    assert ".rules-builtin-head" not in html
    assert ".rules-builtin-row__types" not in html
    assert ".rule-chip-select" not in html
    # Responsive: the two-column layouts collapse on narrower windows.
    assert ".rules-layout, .rules-tools-layout, .rules-types-layout { grid-template-columns: 1fr; }" in html
    assert ".rules-editor-grid, .rules-test-grid, .rules-kv-list, .rule-dictionary-form, .rules-builtin-row { grid-template-columns: 1fr; }" in html
    assert html.count("flex: 0 0 auto") >= 5

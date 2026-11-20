#!/usr/bin/env node
/**
 * 品牌生成器：把 brand.json 渲染成各语言/各工具链可直接消费的生成物。
 *
 * 输入: brand.json
 * 产物:
 *   brand_generated.py          (Python 回归常量)
 *   templates/brand.generated.js (桌面端 window.__APP_BRAND__)
 *
 * 用法:
 *   node tools/brand/generate.mjs            # 重新生成
 *   node tools/brand/generate.mjs --check    # 校验生成物与 brand.json 一致，不一致退出码 1
 *
 * 生成必须确定性: 相同 brand.json + 相同版本 => 相同字节。
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const TOOLS_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = join(TOOLS_DIR, "..", "..");
const BRAND_PATH = join(ROOT, "brand.json");
const PY_PATH = join(ROOT, "brand_generated.py");
const JS_PATH = join(ROOT, "templates", "brand.generated.js");

const GENERATED_BY = "node tools/brand/generate.mjs";
const SOURCE = "brand.json";

const checkMode = process.argv.includes("--check");
const unsupportedArgs = process.argv.slice(2).filter((arg) => arg !== "--check");
if (unsupportedArgs.length > 0) {
    console.error(`[brand] 未知参数: ${unsupportedArgs.join(" ")}`);
    console.error("[brand] 用法: node tools/brand/generate.mjs [--check]");
    process.exit(1);
}

function fail(message) {
    console.error(`[brand] ${message}`);
    process.exit(1);
}

function readBrand() {
    if (!existsSync(BRAND_PATH)) {
        fail(`缺少品牌源文件: ${relative(ROOT, BRAND_PATH)}`);
    }
    let brand;
    try {
        brand = JSON.parse(readFileSync(BRAND_PATH, "utf8"));
    } catch (error) {
        fail(`brand.json 不是合法 JSON: ${error.message}`);
    }
    validate(brand);
    return brand;
}

function requireString(value, label) {
    if (typeof value !== "string" || value.trim() === "") {
        fail(`brand.json 缺少非空字符串字段: ${label}`);
    }
    return value;
}

function requireStringArray(value, label) {
    if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
        fail(`brand.json 字段必须是字符串数组: ${label}`);
    }
    return value;
}

function validate(brand) {
    requireString(brand.identity?.displayName?.zh, "identity.displayName.zh");
    requireString(brand.identity?.displayName?.en, "identity.displayName.en");
    requireString(brand.identity?.slug, "identity.slug");
    requireString(brand.identity?.pythonPackage, "identity.pythonPackage");
    requireString(brand.identity?.tagline?.zh, "identity.tagline.zh");
    requireString(brand.identity?.tagline?.en, "identity.tagline.en");
    requireString(brand.identity?.copyrightHolder, "identity.copyrightHolder");
    requireString(brand.identity?.license, "identity.license");
    requireString(brand.urls?.repo, "urls.repo");
    requireString(brand.urls?.issues, "urls.issues");
    requireString(brand.urls?.releasesLatest, "urls.releasesLatest");
    requireString(brand.runtime?.appDirName, "runtime.appDirName");
    requireStringArray(brand.runtime?.legacyAppDirNames, "runtime.legacyAppDirNames");
    requireString(brand.runtime?.mutexName, "runtime.mutexName");
    requireString(brand.runtime?.tempFilePrefix, "runtime.tempFilePrefix");
    requireString(brand.runtime?.tempDirPrefix, "runtime.tempDirPrefix");
    requireString(brand.runtime?.nodePreloadPrefix, "runtime.nodePreloadPrefix");
    requireString(brand.runtime?.sessionStoragePrefix, "runtime.sessionStoragePrefix");
    requireString(brand.runtime?.imapClientName, "runtime.imapClientName");
    requireString(brand.runtime?.ruleFileHeader, "runtime.ruleFileHeader");
    requireString(brand.runtime?.threadNameTruthAudit, "runtime.threadNameTruthAudit");
    requireString(brand.runtime?.threadNameWorker, "runtime.threadNameWorker");
    requireString(brand.runtime?.buildIdentityName, "runtime.buildIdentityName");
    requireString(brand.env?.webview2Mode, "env.webview2Mode");
    requireString(brand.env?.runContextPath, "env.runContextPath");
    requireString(brand.env?.playwrightSmoke, "env.playwrightSmoke");
    requireString(brand.env?.candidateRevision, "env.candidateRevision");
    requireString(brand.upstream?.author, "upstream.author");
    requireString(brand.upstream?.handle, "upstream.handle");
    if (brand.identity.slug !== brand.identity.slug.toLowerCase()) {
        fail("identity.slug 必须是小写 ASCII slug");
    }
    if (!/^[a-z][a-z0-9-]*$/.test(brand.identity.slug)) {
        fail("identity.slug 只允许小写字母、数字与连字符，且以字母开头");
    }
    if (!/^[a-z][a-z0-9_]*$/.test(brand.identity.pythonPackage)) {
        fail("identity.pythonPackage 必须是合法的小写 Python 包名");
    }
}

function jsonString(value) {
    // JSON 字符串字面量同时是合法的 Python 字符串字面量（含中文，不转义）。
    return JSON.stringify(String(value));
}

function pyTuple(values) {
    if (values.length === 0) {
        return "()";
    }
    const lines = values.map((value) => `    ${jsonString(value)},`).join("\n");
    return `(\n${lines}\n)`;
}

function renderPython(brand) {
    const lines = [
        '"""生成文件，请勿手改。',
        "",
        `来源：${SOURCE}（品牌单一事实源）`,
        `生成：${GENERATED_BY}`,
        '"""',
        "",
        `BRAND_NAME = ${jsonString(brand.identity.displayName.zh)}`,
        `BRAND_NAME_EN = ${jsonString(brand.identity.displayName.en)}`,
        `BRAND_SLUG = ${jsonString(brand.identity.slug)}`,
        `BRAND_PACKAGE = ${jsonString(brand.identity.pythonPackage)}`,
        `BRAND_TAGLINE = ${jsonString(brand.identity.tagline.zh)}`,
        `BRAND_TAGLINE_EN = ${jsonString(brand.identity.tagline.en)}`,
        `BRAND_FOOTER_STAMP = ${jsonString(brand.identity.footerStamp || "")}`,
        `BRAND_COPYRIGHT_HOLDER = ${jsonString(brand.identity.copyrightHolder)}`,
        `BRAND_LICENSE = ${jsonString(brand.identity.license)}`,
        `BRAND_YEAR = ${Number.isInteger(brand.identity.year) ? brand.identity.year : 0}`,
        `BRAND_REPO_URL = ${jsonString(brand.urls.repo)}`,
        `BRAND_ISSUES_URL = ${jsonString(brand.urls.issues)}`,
        `BRAND_RELEASES_URL = ${jsonString(brand.urls.releasesLatest)}`,
        `BRAND_REPO_LABEL = ${jsonString(brand.urls.repoLabel || "")}`,
        "",
        `UPSTREAM_PROJECT_NAME = ${jsonString(brand.upstream?.projectName || "")}`,
        `UPSTREAM_BRAND_NAME = ${jsonString(brand.upstream?.brandName || "")}`,
        `UPSTREAM_AUTHOR = ${jsonString(brand.upstream.author)}`,
        `UPSTREAM_HANDLE = ${jsonString(brand.upstream.handle)}`,
        `UPSTREAM_NPM_SCOPE = ${jsonString(brand.upstream?.npmScope || "")}`,
        `UPSTREAM_REPO_URL = ${jsonString(brand.upstream?.repoUrl || "")}`,
        "",
        `APP_DIR_NAME = ${jsonString(brand.runtime.appDirName)}`,
        `LEGACY_APP_DIR_NAMES = ${pyTuple(brand.runtime.legacyAppDirNames)}`,
        `SINGLE_INSTANCE_MUTEX_NAME = ${jsonString(brand.runtime.mutexName)}`,
        `TEMP_FILE_PREFIX = ${jsonString(brand.runtime.tempFilePrefix)}`,
        `TEMP_DIR_PREFIX = ${jsonString(brand.runtime.tempDirPrefix)}`,
        `NODE_PRELOAD_PREFIX = ${jsonString(brand.runtime.nodePreloadPrefix)}`,
        `SESSION_STORAGE_PREFIX = ${jsonString(brand.runtime.sessionStoragePrefix)}`,
        `IMAP_CLIENT_NAME = ${jsonString(brand.runtime.imapClientName)}`,
        `RULE_FILE_HEADER = ${jsonString(brand.runtime.ruleFileHeader)}`,
        `THREAD_NAME_TRUTH_AUDIT = ${jsonString(brand.runtime.threadNameTruthAudit)}`,
        `THREAD_NAME_WORKER = ${jsonString(brand.runtime.threadNameWorker)}`,
        `BUILD_IDENTITY_NAME = ${jsonString(brand.runtime.buildIdentityName)}`,
        "",
        `WEBVIEW2_MODE_ENV = ${jsonString(brand.env.webview2Mode)}`,
        `RUN_CONTEXT_ENV_VAR = ${jsonString(brand.env.runContextPath)}`,
        `PLAYWRIGHT_SMOKE_ENV_VAR = ${jsonString(brand.env.playwrightSmoke)}`,
        `CANDIDATE_REVISION_ENV_VAR = ${jsonString(brand.env.candidateRevision)}`,
    ];
    return `${lines.join("\n")}\n`;
}

function renderJavaScript(brand) {
    const payload = {
        name: brand.identity.displayName.zh,
        nameEn: brand.identity.displayName.en,
        subtitle: brand.identity.tagline.zh,
        subtitleEn: brand.identity.tagline.en,
        footerVersion: brand.identity.displayName.zh,
        footerStamp: brand.identity.footerStamp || "",
        githubLabel: brand.urls.repoLabel || "",
        githubUrl: brand.urls.repo,
        repoUrl: brand.urls.repo,
        issuesUrl: brand.urls.issues,
        releasesUrl: brand.urls.releasesLatest,
        sessionStoragePrefix: brand.runtime.sessionStoragePrefix,
    };
    const body = JSON.stringify(payload, null, 4)
        .split("\n")
        .map((line, index) => (index === 0 ? line : `    ${line}`))
        .join("\n");
    return [
        "/*! 生成文件，请勿手改。",
        ` *  来源：${SOURCE}（品牌单一事实源）`,
        ` *  生成：${GENERATED_BY}`,
        " */",
        "(function () {",
        '    "use strict";',
        "    if (typeof window === \"undefined\") {",
        "        return;",
        "    }",
        `    window.__APP_BRAND__ = Object.freeze(${body});`,
        "})();",
        "",
    ].join("\n");
}

function writeOrCheck(path, expected) {
    const label = relative(ROOT, path);
    if (checkMode) {
        if (!existsSync(path)) {
            fail(`生成物缺失: ${label}（请运行 ${GENERATED_BY}）`);
        }
        const actual = readFileSync(path, "utf8");
        if (actual !== expected) {
            fail(`生成物与 brand.json 不一致: ${label}（请运行 ${GENERATED_BY}）`);
        }
        console.log(`[brand] 已是最新: ${label}`);
        return;
    }
    if (existsSync(path) && readFileSync(path, "utf8") === expected) {
        console.log(`[brand] 未变化: ${label}`);
        return;
    }
    writeFileSync(path, expected, "utf8");
    console.log(`[brand] 已生成: ${label}`);
}

const brand = readBrand();
writeOrCheck(PY_PATH, renderPython(brand));
writeOrCheck(JS_PATH, renderJavaScript(brand));
console.log(`[brand] OK（${checkMode ? "校验" : "生成"}）`);

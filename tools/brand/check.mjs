#!/usr/bin/env node
/**
 * 品牌泄漏检查：确认品牌字面量只出现在允许的位置。
 *
 * 分层策略（随里程碑逐步收紧）：
 *   runtime  — 运行时 Python / 桌面端模板：硬性要求 0 命中（默认即失败）
 *   tests / build / plugins / docs — 输出待迁移清单；--strict 时同样失败
 *
 * 用法:
 *   node tools/brand/check.mjs            # 硬性校验 runtime 区域
 *   node tools/brand/check.mjs --strict   # 所有区域均要求 0 命中（迁移完成后使用）
 *   node tools/brand/check.mjs --list     # 只打印清单，任何区域都不失败
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const TOOLS_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = join(TOOLS_DIR, "..", "..");

const args = process.argv.slice(2);
const allowed = new Set(["--strict", "--list"]);
const unknown = args.filter((arg) => !allowed.has(arg));
if (unknown.length > 0) {
    console.error(`[brand-check] 未知参数: ${unknown.join(" ")}`);
    process.exit(1);
}
const strictMode = args.includes("--strict");
const listMode = args.includes("--list");

const SKIP_DIRS = new Set([
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    "__pycache__",
    "node_modules",
    "dist",
    "tmp",
    "staging",
    "extracted_invoices",
    "release-assets",
    "release-bundle",
]);
const SKIP_PATH_PREFIXES = [
    "build/work",
    "build/runtime",
    "build/dist",
    "plugins/dsh-invoice-downloader/lib",
    "plugins/dsh-invoice-downloader/runtime",
    "plugins/dsh-invoice-downloader/node_modules",
];
const TEXT_SUFFIXES = new Set([
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".md",
    ".txt",
    ".ps1",
    ".sh",
    ".iss",
    ".spec",
    ".html",
    ".cmd",
]);
// 生成物与品牌源本身按设计包含品牌字面量。
const ALLOWED_FILES = new Set([
    "brand.json",
    "brand_generated.py",
    "templates/brand.generated.js",
    // 构建期生成的临时产物（同样在 .gitignore 中）。
    "build/windows/build-identity.generated.json",
    "build/windows/version-info.generated.txt",
]);

function readBrand() {
    try {
        return JSON.parse(readFileSync(join(ROOT, "brand.json"), "utf8"));
    } catch (error) {
        console.error(`[brand-check] 无法读取 brand.json: ${error.message}`);
        process.exit(1);
    }
}

function brandTokens(brand) {
    const tokens = new Set();
    const add = (value) => {
        const text = String(value || "").trim();
        if (text.length >= 5) {
            tokens.add(text);
        }
    };
    add(brand.identity?.displayName?.zh);
    add(brand.identity?.displayName?.en);
    add(brand.identity?.slug);
    add(brand.identity?.pythonPackage);
    add(brand.runtime?.appDirName);
    add(brand.runtime?.buildIdentityName);
    add(brand.runtime?.ruleFileHeader?.replace(/^#+\s*/, ""));
    add(brand.upstream?.brandName);
    add(brand.upstream?.author);
    add(brand.upstream?.handle);
    add(brand.upstream?.npmScope);
    add(brand.upstream?.repoUrl);
    add(brand.urls?.repo);
    // 仓库路径（含仓库名）同样视为品牌痕迹。
    try {
        const repoPath = new URL(brand.urls.repo).pathname.replace(/^\/|\/$/g, "");
        add(repoPath);
        const segments = repoPath.split("/").filter(Boolean);
        if (segments.length > 0) {
            add(segments[segments.length - 1]);
        }
    } catch {
        // repo URL 不是合法 URL 时忽略这一段。
    }
    return [...tokens];
}

function classify(relPath) {
    if (/^tests\//.test(relPath) || relPath.startsWith("plugins/dsh-invoice-downloader/tests/")) {
        return "tests";
    }
    if (relPath.startsWith("build/") || relPath.startsWith(".github/")) return "build";
    if (relPath.startsWith("plugins/")) return "plugins";
    // 根目录治理与说明文档（含溯源署名）按设计允许出现品牌与上游信息。
    const isRootDoc =
        /^(README|NOTICE|LICENSE|AGENTS\.md|CHANGELOG|CONTRIBUTING|SECURITY|CODE_OF_CONDUCT|AUTHORS|THIRD_PARTY_NOTICES)/.test(
            relPath,
        );
    if (isRootDoc || relPath.startsWith("docs/")) {
        return "docs";
    }
    return "runtime";
}

function* walk(dir) {
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        const rel = relative(ROOT, full).split(sep).join("/");
        if (SKIP_DIRS.has(entry)) continue;
        if (SKIP_PATH_PREFIXES.some((prefix) => rel === prefix || rel.startsWith(`${prefix}/`))) {
            continue;
        }
        const stats = statSync(full);
        if (stats.isDirectory()) {
            yield* walk(full);
            continue;
        }
        const dot = entry.lastIndexOf(".");
        const suffix = dot >= 0 ? entry.slice(dot).toLowerCase() : "";
        if (!TEXT_SUFFIXES.has(suffix)) continue;
        if (ALLOWED_FILES.has(rel)) continue;
        yield rel;
    }
}

const brand = readBrand();
const tokens = brandTokens(brand).sort((a, b) => b.length - a.length);
const findings = [];
for (const rel of walk(ROOT)) {
    let text;
    try {
        text = readFileSync(join(ROOT, rel), "utf8");
    } catch {
        continue;
    }
    const hits = tokens.filter((token) => text.includes(token));
    if (hits.length > 0) {
        findings.push({ file: rel, area: classify(rel), tokens: hits });
    }
}

const areas = ["runtime", "tests", "build", "plugins", "docs"];
const counts = Object.fromEntries(areas.map((area) => [area, 0]));
for (const finding of findings) {
    counts[finding.area] += 1;
}

if (findings.length > 0) {
    for (const finding of findings) {
        console.log(`[${finding.area}] ${finding.file}: ${finding.tokens.join(", ")}`);
    }
}

console.log(
    `[brand-check] 命中文件数: runtime=${counts.runtime} tests=${counts.tests} ` +
        `build=${counts.build} plugins=${counts.plugins} docs=${counts.docs}`,
);

if (listMode) {
    console.log("[brand-check] 仅清单模式，未做失败判定");
    process.exit(0);
}

const failingAreas = strictMode ? areas : ["runtime"];
const failed = failingAreas.filter((area) => counts[area] > 0);
if (failed.length > 0) {
    console.error(`[brand-check] 失败: ${failed.join(", ")} 区域仍存在品牌字面量`);
    process.exit(1);
}
console.log(`[brand-check] OK（严格模式=${strictMode}）`);

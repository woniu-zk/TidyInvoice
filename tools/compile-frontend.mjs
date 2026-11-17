#!/usr/bin/env node
/**
 * InvoiceFlowAI 前端构建脚本（构建期预编译，运行期不再加载 Babel）。
 *
 * 输入: templates/index_app.js          (JSX 源码)
 * 产物: templates/index_app.built.js    (浏览器可直接执行的 JS)
 * 工具: tools/vendor/babel.min.js       (仅构建期使用，不随安装包发布)
 *
 * 用法:
 *   node tools/compile-frontend.mjs            # 生成产物并打印 SHA256
 *   node tools/compile-frontend.mjs --check    # 校验已提交产物是否与源码一致，不一致退出码 1
 *
 * 输出必须确定性: 相同源码 + 相同 Babel 版本 => 相同字节。
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const TOOLS_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(TOOLS_DIR);
const SOURCE_PATH = join(ROOT, "templates", "index_app.js");
const OUTPUT_PATH = join(ROOT, "templates", "index_app.built.js");
const BABEL_PATH = join(TOOLS_DIR, "vendor", "babel.min.js");
const OUTPUT_BANNER =
    "/*! InvoiceFlowAI 前端产物 - 由 tools/compile-frontend.mjs 依据 templates/index_app.js 生成，请勿手改。 */";
const REQUIRED_OUTPUT_MARKERS = [
    'name: "InvoiceFlowAI"',
    'subtitle: "AI发票管家',
    "const APP_VISIBLE_COPY = {",
    "React.createElement(",
];

const checkMode = process.argv.includes("--check");
const unsupportedArgs = process.argv.slice(2).filter((arg) => arg !== "--check");
if (unsupportedArgs.length > 0) {
    console.error(`[compile-frontend] 未知参数: ${unsupportedArgs.join(" ")}`);
    console.error("[compile-frontend] 用法: node tools/compile-frontend.mjs [--check]");
    process.exit(1);
}

function sha256(text) {
    return createHash("sha256").update(text, "utf8").digest("hex");
}

function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function loadBabelStandalone() {
    if (!existsSync(BABEL_PATH)) {
        throw new Error(`缺少构建依赖: ${relative(ROOT, BABEL_PATH)}`);
    }
    // Babel standalone 是为浏览器打包的 UMD，需要最小 DOM 桩才能在 Node 中加载。
    const sandbox = {
        console,
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
    };
    sandbox.document = {
        head: { appendChild() {} },
        createElement() {
            return { setAttribute() {}, appendChild() {} };
        },
        getElementsByTagName() {
            return [];
        },
        querySelectorAll() {
            return [];
        },
        addEventListener() {},
    };
    sandbox.window = sandbox;
    sandbox.self = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(readFileSync(BABEL_PATH, "utf8"), sandbox, {
        filename: "babel.min.js",
    });
    const babel = sandbox.Babel;
    if (!babel || typeof babel.transform !== "function") {
        throw new Error("babel.min.js 加载失败: 未找到 Babel.transform");
    }
    return babel;
}

function compile() {
    if (!existsSync(SOURCE_PATH)) {
        throw new Error(`缺少源码: ${relative(ROOT, SOURCE_PATH)}`);
    }
    const source = readFileSync(SOURCE_PATH, "utf8");
    const babel = loadBabelStandalone();
    const result = babel.transform(source, {
        presets: ["react"],
        filename: "index_app.js",
        sourceMaps: false,
        compact: false,
        comments: true,
    });
    if (!result || typeof result.code !== "string" || !result.code.trim()) {
        throw new Error("Babel 未产出任何代码");
    }
    // 统一为 LF、结尾单个换行，保证跨平台字节一致。
    const normalizedCode = `${result.code.replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/\s+$/, "")}\n`;
    const bannerText = `${OUTPUT_BANNER}\n`;
    const output = `${bannerText}${normalizedCode}`;
    const missing = REQUIRED_OUTPUT_MARKERS.filter((marker) => !output.includes(marker));
    if (missing.length > 0) {
        throw new Error(`产物缺少必要标记: ${missing.join(", ")}`);
    }
    return { source, output };
}

function main() {
    const { source, output } = compile();
    const outputSha256 = sha256(output);
    const sourceSha256 = sha256(source);

    if (checkMode) {
        if (!existsSync(OUTPUT_PATH)) {
            console.error(`[compile-frontend] 检查失败: 未找到产物 ${relative(ROOT, OUTPUT_PATH)}`);
            console.error("[compile-frontend] 请运行: node tools/compile-frontend.mjs");
            process.exit(1);
        }
        const committed = readFileSync(OUTPUT_PATH, "utf8");
        const committedSha256 = sha256(committed);
        if (committed !== output) {
            console.error("[compile-frontend] 检查失败: 产物与源码不一致");
            console.error(`  源码: ${relative(ROOT, SOURCE_PATH)} sha256=${sourceSha256}`);
            console.error(`  期望: ${relative(ROOT, OUTPUT_PATH)} sha256=${outputSha256}`);
            console.error(`  实际: ${relative(ROOT, OUTPUT_PATH)} sha256=${committedSha256}`);
            console.error("[compile-frontend] 请运行: node tools/compile-frontend.mjs");
            process.exit(1);
        }
        console.log(`[compile-frontend] 产物已是最新: ${relative(ROOT, OUTPUT_PATH)}`);
        console.log(`[compile-frontend] sha256=${outputSha256}`);
        return;
    }

    writeFileSync(OUTPUT_PATH, output, "utf8");
    console.log(`[compile-frontend] 源码: ${relative(ROOT, SOURCE_PATH)} sha256=${sourceSha256}`);
    console.log(
        `[compile-frontend] 产物: ${relative(ROOT, OUTPUT_PATH)} ` +
            `${formatBytes(Buffer.byteLength(source, "utf8"))} -> ${formatBytes(Buffer.byteLength(output, "utf8"))} ` +
            `sha256=${outputSha256}`,
    );
    console.log("[compile-frontend] OK");
}

try {
    main();
} catch (error) {
    console.error(`[compile-frontend] 构建失败: ${error && error.message ? error.message : error}`);
    process.exit(1);
}

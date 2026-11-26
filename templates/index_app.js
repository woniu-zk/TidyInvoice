const { useEffect, useMemo, useRef, useState } = React;
const { createRoot } = ReactDOM;
const { MemoryRouter, Routes, Route, useNavigate, useLocation } = ReactRouterDOM;

function isoDate(date) {
    const year = date.getFullYear();
    const month = `${date.getMonth() + 1}`.padStart(2, "0");
    const day = `${date.getDate()}`.padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function shiftDays(days) {
    const date = new Date();
    date.setDate(date.getDate() + days);
    return date;
}

function lastDaysRange(days) {
    return {
        date_from: isoDate(shiftDays(-(days - 1))),
        date_to: isoDate(new Date()),
    };
}

const DEFAULT_SETTINGS = {
    email: "",
    auth_code: "",
    save_path: "",
    company: "",
    remember_settings: true,
    task_mode: "mail",
    local_input_dir: "",
    // Empty means "same folder as local_input_dir" (in-place organizing).
    local_output_dir: "",
    // Keep the per-category archive folders (餐饮/充电/...).
    local_split_by_category: true,
};

const DEFAULT_RUN_SETTINGS = {
    ...lastDaysRange(30),
    quick_range: "last_30_days",
};

const DEFAULT_PROGRESS = {
    progress: 0,
    status_text: "等待任务开始...",
    logs: [],
    stats: { emails: 0, invoices: 0, errors: 0 },
    is_running: false,
    run_state: "idle",
    task_mode: "mail",
    dry_run: false,
    last_error: "",
    stop_requested: false,
    can_stop: false,
    quota_exhausted: false,
    quota_message: "",
    build_identity: null,
};

// 品牌标识来自 templates/brand.generated.js（由 brand.json 生成，勿手改）。
// 界面文案（任务模式、结果横幅等）仍在本文件内，后续由 i18n 词表接管。
if (!window.__APP_BRAND__) {
    throw new Error("品牌清单未加载：templates/brand.generated.js 必须在 index_app.built.js 之前引入");
}

const APP_BRAND = Object.freeze({
    name: window.__APP_BRAND__.name,
    nameEn: window.__APP_BRAND__.nameEn,
    subtitle: window.__APP_BRAND__.subtitle,
});

const APP_VISIBLE_COPY = {
    topSubtitle: window.__APP_BRAND__.subtitle,
    footerVersion: window.__APP_BRAND__.footerVersion,
    footerStamp: window.__APP_BRAND__.footerStamp,
    githubLabel: window.__APP_BRAND__.githubLabel,
    githubUrl: window.__APP_BRAND__.githubUrl,
    taskModes: {
        fetch: {
            label: "邮箱提取",
            description: "只把邮箱附件保存到 inbox 文件夹并生成清单，不做识别和归档。",
            badge: "只保存附件",
        },
        local: {
            label: "本地整理",
            description: "读取本机发票文件夹，离线识别后按分类与命名规则归档，不需要邮箱和网络。",
            badge: "本机离线整理",
        },
        mail: {
            label: "邮箱提取并整理",
            description: "连接邮箱提取附件，识别后按分类与命名规则归档。",
            badge: "识别后归档",
        },
    },
    resultBanners: {
        fetch: {
            eyebrow: "提取结果",
            title: "仅提取完成",
            text: "附件已保存到 inbox 文件夹，并写入 manifest.jsonl；未进行识别和归档。",
        },
        localApply: {
            eyebrow: "整理结果",
            title: "本地整理完成",
            text: "已按分类与命名规则归档本地发票；原件已原样保留在「整理前发票」文件夹（文件名不变），重复文件已移入 duplicates 文件夹。",
        },
        localApplyCustom: {
            eyebrow: "整理结果",
            title: "本地整理完成",
            text: "已按分类与命名规则归档本地发票；原始文件保留在发票文件夹，未移动。",
        },
        localApplyFlat: {
            eyebrow: "整理结果",
            title: "本地整理完成",
            text: "已按命名规则整理本地发票（未建分类子目录）；原件已原样保留在「整理前发票」文件夹（文件名不变），重复文件已移入 duplicates 文件夹。",
        },
        localApplyCustomFlat: {
            eyebrow: "整理结果",
            title: "本地整理完成",
            text: "已按命名规则整理本地发票（未建分类子目录）；原始文件保留在发票文件夹，未移动。",
        },
    },
};

const TASK_MODE_OPTIONS = [
    { value: "fetch", ...APP_VISIBLE_COPY.taskModes.fetch },
    { value: "local", ...APP_VISIBLE_COPY.taskModes.local },
    { value: "mail", ...APP_VISIBLE_COPY.taskModes.mail },
];
const TASK_MODE_VALUES = new Set(TASK_MODE_OPTIONS.map((option) => option.value));

const EMAIL_PROVIDER_DOMAINS = [
    "qq.com",
    "vip.qq.com",
    "foxmail.com",
    "163.com",
    "126.com",
    "188.com",
    "yeah.net",
    "qiye.163.com",
    "88.com",
    "exmail.qq.com",
    "sina.com",
    "sina.cn",
    "sohu.com",
    "21cn.com",
    "263.net",
    "189.cn",
    "139.com",
    "aliyun.com",
    "qiye.aliyun.com",
    "gmail.com",
    "googlemail.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "yahoo.com",
    "ymail.com",
    "zoho.com",
    "yandex.com",
    "gmx.net",
    "gmx.com",
    "aol.com",
    "fastmail.com",
];
const SUPPORTED_EMAIL_DOMAINS = new Set(EMAIL_PROVIDER_DOMAINS);

const DISCLAIMER_SOFTWARE_ITEMS = [
    "本软件用于票据整理、归档与复核辅助处理。",
    "本软件不附带任何真实邮箱凭据。",
    "请仅填写并使用你自己的邮箱授权信息。",
    "涉及报销、入账或合规判断的重要票据，请务必进行人工复核。",
];

const DISCLAIMER_ITEMS = [
    "本工具用于票据整理与归档辅助，识别结果应结合业务流程进行复核。",
    "对于识别、归档、遗漏、误判及由此产生的后果，工具方不承担责任。",
    "使用者应自行遵守所在公司关于票据数据与信息安全管理的相关规定。",
    "涉及报销、入账或合规判断的重要票据，请务必进行人工复核。",
];

const UI_COPY = {
    shell: {
        close: "关闭程序",
        closing: "正在关闭...",
        closeFailed: "关闭程序失败，请稍后重试。",
        minimize: "最小化窗口",
        minimizing: "正在最小化...",
        minimizeFailed: "最小化窗口失败，请稍后重试。",
        maximize: "最大化窗口",
        maximizing: "正在最大化...",
        maximizeFailed: "最大化窗口失败，请稍后重试。",
        windowSubtitle: "桌面工作区",
    },
    navigation: [
        { key: "home", label: "首页", description: "提取与整理", icon: "space_dashboard", path: "/" },
        { key: "results", label: "结果", description: "汇总与导出", icon: "assessment", path: "/results" },
        { key: "settings", label: "设置", description: "邮箱与规则", icon: "settings", path: "/settings" },
    ],
    pages: {
        home: {
            eyebrow: "工作台",
            title: "首页",
            description: "确认提取时间与输出位置，然后开始邮箱提取或本地整理。",
            bootstrapTitle: "正在载入",
            bootstrapDescription: "正在初始化本地设置。",
            bootstrapMessage: "正在连接桌面接口并加载本地设置，请稍候。",
            errorDescription: "本地设置初始化失败。",
            errorMessage: "本地设置初始化失败，请重启应用。",
            controlledNotice: "受控复跑已锁定输出目录与日期窗口。",
            readonlyBadge: "只读",
            emailLabel: "提取邮箱",
            companyLabel: "公司配置",
            unconfigured: "尚未配置",
            goSettings: "前往设置",
            readonlyHint: "邮箱、授权码与公司名称在设置页维护，此处仅展示当前配置。",
            outputTitle: "输出目录设置",
            outputHint: "邮箱提取与邮箱提取并整理会把附件和归档写入该目录；本地整理使用下方归档目录。",
            browseDirectory: "浏览目录",
            pathLocked: "路径已锁定",
            dateTitle: "提取时间",
            dateHint: "确认起止日期后开始提取，日期范围会随任务一起提交。",
            localTitle: "本地整理",
            localInputLabel: "本地发票文件夹",
            localOutputLabel: "归档目录",
            chooseFolder: "选择文件夹",
            chooseOther: "选择其他目录",
            resetLocalOutput: "恢复默认（发票文件夹）",
            splitByCategory: "按分类分目录",
            splitHelpOn: "按发票类型建立 餐饮/充电 等子目录归档；原件按原文件名原样保留在「整理前发票」文件夹。",
            splitHelpOff: "不建分类子目录：整理后的发票直接放在该文件夹里，文件名仍带类型；原件按原文件名原样保留在「整理前发票」文件夹。",
            localHint: "本地整理会读取该文件夹并在归档目录生成分类结果，不需要邮箱和网络。",
            actionsTitle: "开始处理",
            actionHint: "邮箱提取只保存附件；本地整理在本机完成识别归档；邮箱提取并整理会提取附件后按规则归档。",
            progressTitle: "处理进度",
            statusWaiting: "等待任务开始",
            currentOperation: "当前操作",
            progressLabel: "完成度",
            liveRefresh: "进度与处理信息保持实时刷新。",
            stopPending: "已收到安全停止指令。",
            stopDetail: "系统将在当前文件处理完成后安全停止。",
            processingDetail: "邮件抓取、票据识别与归档整理将依次执行。",
            processingDetailFetch: "本轮只提取邮箱附件，不会进行识别与归档。",
            processingDetailLocal: "本地文件扫描、票据识别与归档整理将依次执行。",
            scanEmailsLabel: "已扫描邮件",
            scanFilesLabel: "已扫描文件",
            stopNotice: "已收到安全停止指令，当前邮件或当前文件处理完成后将结束任务。",
            runEmpty: "尚未开始处理。完成配置后点击上方按钮开始。",
            runInfoTitle: "处理信息",
            runInfoEmpty: "暂无运行信息。",
            startTimeLabel: "开始时间",
            elapsedLabel: "已运行",
            updatedLabel: "最近更新",
            viewResults: "查看结果",
            stop: "停止运行",
            stopping: "正在停止...",
            footerMeta: "任务运行时可以安全停止，当前邮件或当前文件处理完成后结束。",
        },
        analysis: {
            eyebrow: "处理汇总",
            title: "结果分析",
            footerText: "当前页: 结果",
            statusSummary: "运行结果",
            resultTitle: "本次处理完成",
            reviewTitle: "待人工复核",
            reviewEmpty: "当前没有待人工复核记录。",
            reviewReady: "请优先前往待人工复核文件夹处理这些记录。",
            reviewIdle: "结果明细仍可导出查看，输出目录会保留本轮成功归档结果。",
            classificationTitle: "分类汇总",
            classificationEmpty: "本轮还没有可统计的分类结果。",
        },
        settings: {
            eyebrow: "基础配置",
            title: "设置",
            description: "邮箱、公司与归类规则都在这里维护；规则保存后在下一次整理时生效。",
            footerText: "当前页: 设置",
            emailSection: "邮箱配置",
            rulesSection: "规则设置",
            emailCardTitle: "邮箱源配置",
            companyCardTitle: "公司配置",
            controlledNotice: "受控复跑已锁定输出目录与日期窗口，相关配置不可修改。",
            remember: "自动记住当前配置",
            savedHint: "配置保存在本机。",
        },
        rules: {
            title: "归类规则",
            description: "用目标票种、关键词和金额范围建立归档规则；保存后在下一次整理时生效。",
        },
    },
};

const RULE_SCOPE_OPTIONS = [
    { value: "global", label: "全局规则", description: "对本机所有发票库生效，适合长期稳定的规则。" },
    { value: "library", label: "当前发票库", description: "只对当前发票库生效，适合单个项目或单个文件夹的特殊规则。" },
];

const RULE_PANEL_OPTIONS = [
    { value: "rules", label: "规则列表" },
    { value: "tools", label: "词典与测试" },
    { value: "types", label: "票种管理" },
];

const RULE_SOURCE_LAYER_LABELS = {
    builtin: "内置",
    global: "全局",
    library: "发票库",
    pack: "规则包",
};

const CLASSIFICATION_SOURCE_LABELS = {
    builtin_keyword: "内置关键词",
    builtin_type: "票种兜底",
    user_rule: "用户规则",
    rule_pack: "规则包",
    dictionary: "销售方词典",
    unknown: "未归类",
    skipped: "未参与归类",
    isolation: "隔离类型",
};

const RULE_CHAIN_REASON_LABELS = {
    disabled: "规则已停用",
    invoice_type_mismatch: "票种不符",
    amount_missing: "票面金额缺失",
    amount_out_of_range: "金额不在范围内",
    empty_match_text: "没有可匹配的销售方或明细",
    excluded: "命中排除关键词",
    no_keyword_matched: "未命中关键词",
    keyword: "命中关键词",
};

const RULE_ORDER_HELP = "规则从上到下匹配，命中第一条即停止。匹配顺序：当前发票库规则 → 全局规则 → 内置默认。";

const RULE_TARGET_TYPE_HELP = "目标票种决定归档文件夹和归类结果。内置票种是发票识别结果；自定义票种全局可用，可以给任意规则指定。";

const RULE_CUSTOM_TYPE_HELP = "自定义票种全局可用，全局规则和当前发票库规则都能选择。";

function ruleScopeLabel(scope) {
    const option = RULE_SCOPE_OPTIONS.find((item) => item.value === scope);
    return option ? option.label : RULE_SCOPE_OPTIONS[0].label;
}

function ruleScopeDescription(scope) {
    const option = RULE_SCOPE_OPTIONS.find((item) => item.value === scope);
    return option ? option.description : RULE_SCOPE_OPTIONS[0].description;
}

function ruleLayerLabel(layer) {
    const key = String(layer || "").trim();
    return RULE_SOURCE_LAYER_LABELS[key] || (key ? key : "未标注");
}

function classificationSourceLabel(source) {
    const key = String(source || "").trim();
    if (!key) return "未标注";
    return CLASSIFICATION_SOURCE_LABELS[key] || key;
}

function parseRuleAmount(value) {
    if (value === null || value === undefined || value === "") return null;
    // Invoice rows can carry currency-formatted amounts ("¥ 103.00").
    const cleaned = String(value).replace(/[¥￥元,\s]/g, "");
    if (!cleaned) return null;
    const number = Number(cleaned);
    return Number.isFinite(number) ? number : null;
}

function ruleAmountInputValue(value) {
    const number = parseRuleAmount(value);
    return number === null ? "" : String(number);
}

function normalizeRuleAmountRange(value) {
    if (!Array.isArray(value) || value.length === 0) return [];
    const min = value.length > 0 ? parseRuleAmount(value[0]) : null;
    const max = value.length > 1 ? parseRuleAmount(value[1]) : null;
    if (min === null && max === null) return [];
    return [min, max];
}

function buildRuleAmountRange(minText, maxText) {
    const min = parseRuleAmount(minText);
    const max = parseRuleAmount(maxText);
    if (min === null && max === null) return [];
    return [min, max];
}

function splitRuleKeywords(value) {
    const tokens = String(value || "").split(/[,，、;；\n\r]+/);
    const keywords = [];
    tokens.forEach((token) => {
        const text = token.trim();
        if (text && keywords.indexOf(text) === -1) keywords.push(text);
    });
    return keywords;
}

function formatRuleAmountBound(value) {
    const number = parseRuleAmount(value);
    if (number === null) return "";
    // Mirrors the backend Decimal trimming: 100.0 -> "100", 100.50 -> "100.5".
    return String(number);
}

function amountRangeFolderSuffix(amountRange) {
    const range = normalizeRuleAmountRange(amountRange);
    if (range.length === 0) return "";
    const min = range[0];
    const max = range[1];
    const minText = formatRuleAmountBound(min);
    const maxText = formatRuleAmountBound(max);
    if (min !== null && max !== null && min === max) return minText;
    if (min !== null && max === null) return `${minText}以上`;
    if (min === null && max !== null) return `${maxText}以下`;
    if (min !== null && max !== null) {
        if (min < 0 || max < 0) return `${minText}至${maxText}`;
        return `${minText}-${maxText}`;
    }
    return "";
}

function buildRuleFolderName(targetType, amountRange) {
    const typeName = String(targetType || "").trim();
    if (!typeName) return "";
    const suffix = amountRangeFolderSuffix(amountRange);
    return suffix ? `${typeName}-${suffix}` : typeName;
}

function formatRuleAmountRangeLabel(amountRange) {
    const range = normalizeRuleAmountRange(amountRange);
    if (range.length === 0) return "不限金额";
    const min = range[0];
    const max = range[1];
    const minText = formatRuleAmountBound(min);
    const maxText = formatRuleAmountBound(max);
    if (min !== null && max !== null && min === max) return `${minText} 元`;
    if (min !== null && max === null) return `${minText} 元以上`;
    if (min === null && max !== null) return `${maxText} 元以下`;
    if (min !== null && max !== null) {
        return min < 0 || max < 0 ? `${minText} 至 ${maxText} 元` : `${minText}-${maxText} 元`;
    }
    return "不限金额";
}

function formatRuleInvoiceAmountLabel(value) {
    const raw = String(value === null || value === undefined ? "" : value).trim();
    if (!raw) return "--";
    const number = parseRuleAmount(raw);
    if (number === null) return raw;
    return `${number.toFixed(2)} 元`;
}

function cleanRuleLocationFile(file) {
    // Draft-preview source labels may append a trailing parenthetical suffix;
    // strip it so only the real rule file path is shown to the user.
    return String(file || "").replace(/（[^（）]*）$/, "").trim();
}

function ruleLocationText(file, line) {
    const cleaned = cleanRuleLocationFile(file);
    const name = cleaned ? fileNameFromPath(cleaned) : "";
    const lineNumber = Number(line || 0);
    if (!name) return "";
    return lineNumber > 0 ? `${name}:${lineNumber}` : name;
}

function ruleLocationTitle(file, line) {
    const name = cleanRuleLocationFile(file);
    const lineNumber = Number(line || 0);
    if (!name) return "";
    return lineNumber > 0 ? `${name}:${lineNumber}` : name;
}

function nextRuleCategoryId(existing) {
    const used = new Set((existing || []).map((item) => String((item && item.id) || "")));
    let index = 1;
    while (used.has(`rule_${index}`)) index += 1;
    return `rule_${index}`;
}

function normalizeRuleIssues(value) {
    const issues = [];
    (Array.isArray(value) ? value : []).forEach((item) => {
        if (!item) return;
        if (typeof item === "string") {
            const text = item.trim();
            if (text) issues.push({ file: "", line: 0, message: text, severity: "error", text });
            return;
        }
        const file = String(item.file || "");
        const line = Number(item.line || 0);
        const message = String(item.message || item.text || "");
        const severity = String(item.severity || "error").toLowerCase() === "warning" ? "warning" : "error";
        const location = file ? ruleLocationTitle(file, line) : "";
        const text = String(item.text || "").trim() || (location && message ? `${location}: ${message}` : location || message);
        if (message || text) issues.push({ file, line, message, severity, text });
    });
    return issues;
}

function cloneRuleTerm(term, scope) {
    const source = term || {};
    return {
        term: String(source.term || source.seller_name || source.seller_tin || ""),
        category: String(source.category || ""),
        source_layer: String(source.source_layer || scope || ""),
        source_file: String(source.source_file || ""),
        source_line: Number(source.source_line || 0),
    };
}

function normalizeRuleTermEntries(value, scope) {
    const entries = [];
    if (Array.isArray(value)) {
        value.forEach((item) => entries.push(cloneRuleTerm(item, scope)));
    } else if (value && typeof value === "object") {
        Object.keys(value).forEach((term) => {
            entries.push(cloneRuleTerm({ term, category: value[term] }, scope));
        });
    }
    return entries.filter((item) => item.term);
}

function toSaveRuleTerm(term) {
    const source = term || {};
    return {
        term: String(source.term || "").trim(),
        category: String(source.category || "").trim(),
    };
}

function normalizeUserRuleEntry(entry) {
    const source = entry || {};
    const keywords = (Array.isArray(source.keywords) ? source.keywords : [])
        .map((item) => String(item).trim())
        .filter(Boolean);
    const legacyInvoiceTypes = (Array.isArray(source.invoice_types) ? source.invoice_types : [])
        .map((item) => String(item).trim())
        .filter(Boolean);
    let targetType = String(source.target_type || "").trim();
    // Legacy rules saved before target types existed: a single invoice type is
    // the only unambiguous migration hint. Anything else requires the user to pick.
    if (!targetType && legacyInvoiceTypes.length === 1) targetType = legacyInvoiceTypes[0];
    return {
        id: String(source.id || ""),
        name: String(source.name || ""),
        target_type: targetType,
        keywords,
        mainKeyword: keywords[0] || "",
        legacyExtraKeywords: keywords.slice(1),
        amount_range: normalizeRuleAmountRange(source.amount_range),
        enabled: source.enabled !== false,
        match: String(source.match || ""),
        exclude_keywords: (Array.isArray(source.exclude_keywords) ? source.exclude_keywords : [])
            .map((item) => String(item))
            .filter(Boolean),
    };
}

function normalizeBuiltinOverride(entry, documentTypes) {
    const source = entry || {};
    // Builtin defaults have no target_type; their archive folder is the
    // recognized type used as the default target. Legacy overrides may carry an
    // invalid folder, which requires the user to pick a target type again.
    const candidate = String(source.target_type || source.archive_folder || "").trim();
    const targetType = isValidRuleTargetType(candidate, documentTypes) ? candidate : "";
    return {
        id: String(source.id || ""),
        target_type: targetType,
        keywords: (Array.isArray(source.keywords) ? source.keywords : [])
            .map((item) => String(item).trim())
            .filter(Boolean),
        amount_range: normalizeRuleAmountRange(source.amount_range),
        enabled: source.enabled !== false,
    };
}

function buildUserRuleDraft(scopeData, scope, builtinIds, documentTypes) {
    const data = scopeData || {};
    const builtinIdSet = new Set((builtinIds || []).map((item) => String(item)));
    const categories = [];
    const builtinOverrides = [];
    (Array.isArray(data.categories) ? data.categories : []).forEach((item) => {
        const id = String((item && item.id) || "");
        if (id && builtinIdSet.has(id)) builtinOverrides.push(normalizeBuiltinOverride(item, documentTypes));
        else categories.push(normalizeUserRuleEntry(item));
    });
    return {
        categories,
        builtinOverrides,
        terms: normalizeRuleTermEntries(data.terms, scope),
        fallback: String(data.fallback || ""),
    };
}

function toSaveUserRule(entry) {
    const source = entry || {};
    const keyword = String(source.mainKeyword || "").trim();
    const targetType = String(source.target_type || "").trim();
    const extraKeywords = (Array.isArray(source.legacyExtraKeywords) ? source.legacyExtraKeywords : [])
        .map((item) => String(item).trim())
        .filter((item) => item && item !== keyword);
    const payload = {
        id: String(source.id || "").trim(),
        name: String(source.name || "").trim() || buildRuleFolderName(targetType, source.amount_range) || keyword,
        target_type: targetType,
        keywords: [keyword].concat(extraKeywords),
        amount_range: normalizeRuleAmountRange(source.amount_range),
        enabled: source.enabled !== false,
    };
    // Legacy fields stay in the saved payload but are not shown in the editor.
    if (source.match) payload.match = String(source.match);
    if (Array.isArray(source.exclude_keywords) && source.exclude_keywords.length > 0) {
        payload.exclude_keywords = source.exclude_keywords.map((item) => String(item));
    }
    return payload;
}

function toSaveBuiltinOverride(entry) {
    const source = entry || {};
    // Builtin overrides only carry the target-type rule fields. The builtin
    // invoice_types gate and default name/folder are inherited on load.
    return {
        id: String(source.id || "").trim(),
        target_type: String(source.target_type || "").trim(),
        keywords: (Array.isArray(source.keywords) ? source.keywords : []).map((item) => String(item)),
        amount_range: normalizeRuleAmountRange(source.amount_range),
        enabled: source.enabled !== false,
    };
}

function isValidRuleTargetType(value, documentTypes) {
    const text = String(value || "").trim();
    if (!text) return false;
    if (!Array.isArray(documentTypes) || documentTypes.length === 0) return true;
    return documentTypes.indexOf(text) >= 0;
}

function ruleEntryPreviewFolder(entry) {
    return buildRuleFolderName(entry && entry.target_type, entry && entry.amount_range);
}

function buildRuleCategoryNameMap(entries) {
    const map = {};
    (entries || []).forEach((item) => {
        const id = String((item && item.id) || "");
        if (id) map[id] = String((item && (item.name || item.archive_folder)) || id);
    });
    return map;
}

function describeRuleChainStep(step, categoryNameById) {
    if (!step || typeof step !== "object") return "";
    const lookupCategory = (value) => {
        const key = String(value || "");
        if (!key) return "";
        const map = categoryNameById || {};
        const name = map[key];
        return name ? `${name}` : key;
    };
    const stage = String(step.stage || "");
    if (stage === "input") {
        const parts = [];
        if (step.seller) parts.push(`销售方「${step.seller}」`);
        if (step.seller_tin) parts.push(`税号「${step.seller_tin}」`);
        if (step.item) parts.push(`明细「${step.item}」`);
        const typeText = String(step.normalized_type || step.type || "");
        if (typeText) parts.push(`票种「${typeText}」`);
        const amountText = step.amount === null || step.amount === undefined ? "" : String(step.amount);
        if (amountText) parts.push(`金额 ${amountText}`);
        return `读取字段：${parts.length > 0 ? parts.join("，") : "没有可用字段"}`;
    }
    if (stage === "dictionary") {
        if (!step.hit) return "销售方词典：未命中";
        const kindText = step.kind === "seller_tin" ? "销售方税号" : step.kind === "seller_name" ? "销售方名称" : "销售方";
        return `销售方词典：${kindText}「${safeText(step.term, "")}」归入 ${lookupCategory(step.category) || "对应规则"}`;
    }
    if (stage === "rule") {
        const target = lookupCategory(step.rule_id) || safeText(step.rule_id, "规则");
        if (step.hit) {
            const keywordText = step.keyword ? `关键词「${step.keyword}」` : "匹配条件";
            return `规则「${target}」命中${keywordText}`;
        }
        const reason = RULE_CHAIN_REASON_LABELS[String(step.reason || "")] || "";
        return reason ? `规则「${target}」未命中：${reason}` : "";
    }
    if (stage === "rule_scan") {
        const evaluated = Number(step.evaluated || 0);
        const skipped = Number(step.disabled_skipped || 0);
        return `按列表顺序检查 ${evaluated} 条启用规则${skipped > 0 ? `，跳过 ${skipped} 条停用规则` : ""}`;
    }
    if (stage === "type_fallback") {
        if (step.hit) return `票种兜底：${safeText(step.invoice_type, "该票种")} 归入 ${lookupCategory(step.category) || "对应类目"}`;
        return "";
    }
    if (stage === "result") {
        return `最终归类：${classificationSourceLabel(step.source)}${step.category ? ` → ${lookupCategory(step.category) || step.category}` : ""}`;
    }
    if (stage === "fallback") {
        return `使用兜底类目 ${lookupCategory(step.category) || safeText(step.category, "默认类目")}`;
    }
    return "";
}

function emptyUserRuleEditor() {
    return {
        mode: "new",
        id: "",
        originalId: "",
        error: "",
        targetType: "",
        keyword: "",
        amountMin: "",
        amountMax: "",
        enabled: true,
        legacyMatch: "",
        legacyExcludeKeywords: [],
        legacyExtraKeywords: [],
        name: "",
    };
}

function userRuleEditorFromEntry(entry) {
    const source = entry || {};
    const range = normalizeRuleAmountRange(source.amount_range);
    return {
        mode: "edit",
        id: String(source.id || ""),
        originalId: String(source.id || ""),
        error: "",
        targetType: String(source.target_type || ""),
        keyword: String(source.mainKeyword || ""),
        amountMin: range.length > 0 ? ruleAmountInputValue(range[0]) : "",
        amountMax: range.length > 1 ? ruleAmountInputValue(range[1]) : "",
        enabled: source.enabled !== false,
        legacyMatch: String(source.match || ""),
        legacyExcludeKeywords: (Array.isArray(source.exclude_keywords) ? source.exclude_keywords : []).map((item) => String(item)),
        legacyExtraKeywords: (Array.isArray(source.legacyExtraKeywords) ? source.legacyExtraKeywords : []).map((item) => String(item)),
        name: String(source.name || ""),
    };
}

function joinClasses(...values) {
    return values.filter(Boolean).join(" ");
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function openExternalUrl(url) {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
}

async function waitForApi() {
    for (let attempt = 0; attempt < 120; attempt += 1) {
        if (window.pywebview && window.pywebview.api) {
            return window.pywebview.api;
        }
        await sleep(100);
    }
    throw new Error("桌面接口尚未就绪，请稍后重试。");
}

async function waitForApiMethod(method) {
    const api = await waitForApi();
    for (let attempt = 0; attempt < 120; attempt += 1) {
        if (typeof api[method] === "function") {
            return api[method].bind(api);
        }
        await sleep(100);
    }
    throw new Error(`缺少后端接口: ${method}`);
}

async function callApi(method, ...args) {
    const callTarget = await waitForApiMethod(method);
    return callTarget(...args);
}

function emailDomainOf(email) {
    const value = String(email || "").trim();
    const separatorIndex = value.lastIndexOf("@");
    return separatorIndex >= 0 ? value.slice(separatorIndex + 1).toLowerCase() : "";
}

function validateEmail(email) {
    const value = String(email || "").trim();
    if (!value) {
        return "请输入邮箱地址。";
    }
    if (!/^[^\s@]+@[^\s@]+$/.test(value)) {
        return "邮箱地址格式不正确。";
    }
    if (!SUPPORTED_EMAIL_DOMAINS.has(emailDomainOf(value))) {
        return "暂不支持该邮箱域名，请更换为受支持的常用邮箱。";
    }
    return "";
}

/* COMPANY_MAP removed — company is now free-text input */

function validateDateRange(dateFrom, dateTo) {
    const pattern = /^\d{4}-\d{2}-\d{2}$/;
    if (!pattern.test(String(dateFrom || ""))) {
        return "开始日期格式必须为 YYYY-MM-DD。";
    }
    if (!pattern.test(String(dateTo || ""))) {
        return "结束日期格式必须为 YYYY-MM-DD。";
    }
    if (dateFrom > dateTo) {
        return "开始日期不能晚于结束日期。";
    }
    return "";
}

function maskEmail(email) {
    const value = String(email || "");
    const [name, domain] = value.split("@");
    if (!name || !domain) {
        return value || "--";
    }
    if (name.length <= 2) {
        return `${name[0] || ""}***@${domain}`;
    }
    return `${name.slice(0, 2)}***@${domain}`;
}

function safeText(value, fallback = "--") {
    return value === undefined || value === null || value === "" ? fallback : String(value);
}

function preferNonEmpty(...values) {
    for (const value of values) {
        if (value !== undefined && value !== null && String(value).trim() !== "") {
            return value;
        }
    }
    return "";
}

function normalizeTaskMode(value) {
    const mode = String(value || "").trim();
    return TASK_MODE_VALUES.has(mode) ? mode : "mail";
}

function fileNameFromPath(path, fallback = "未命名文件") {
    const value = String(path || "");
    if (!value) {
        return fallback;
    }
    const parts = value.split(/[/\\]/);
    return parts[parts.length - 1] || fallback;
}

function parentFolder(path) {
    const value = String(path || "");
    if (!value) {
        return "";
    }
    return value.replace(/[/\\][^/\\]+$/, "");
}

const BRAND_SESSION_PREFIX = window.__APP_BRAND__.sessionStoragePrefix;
const SESSION_SETTINGS_KEY = `${BRAND_SESSION_PREFIX}.session.settings`;
const SESSION_RUN_SETTINGS_KEY = `${BRAND_SESSION_PREFIX}.session.runSettings`;
const CONTROLLED_AUTOSTART_PREFIX = `${BRAND_SESSION_PREFIX}.controlledAutostart`;

function readSessionValue(key) {
    try {
        const raw = window.sessionStorage.getItem(key);
        return raw ? JSON.parse(raw) : {};
    } catch (error) {
        return {};
    }
}

function writeSessionValue(key, value) {
    try {
        window.sessionStorage.setItem(key, JSON.stringify(value || {}));
    } catch (error) {
        console.warn("Failed to write session state", error);
    }
}

function hasExplicitQaRunContext(runContext) {
    return !!(runContext && runContext.explicit_run_context && runContext.controlled_run);
}

function shouldAutostartControlledRun(runContext) {
    return !!(hasExplicitQaRunContext(runContext) && runContext.autostart_enabled);
}

function controlledAutostartStateKey(runContext) {
    const token = safeText((runContext && runContext.autostart_token) || "", "").trim();
    const runId = safeText((runContext && runContext.run_id) || "", "").trim();
    return [CONTROLLED_AUTOSTART_PREFIX, token || runId || "default"].join(".");
}

function markControlledAutostartConsumed(runContext) {
    writeSessionValue(controlledAutostartStateKey(runContext), {
        consumed: true,
        consumed_at: new Date().toISOString(),
    });
}

function isControlledAutostartConsumed(runContext) {
    const payload = readSessionValue(controlledAutostartStateKey(runContext));
    return !!payload.consumed;
}

function buildPersistPayload(settings, runSettings, runContext) {
    const payload = {
        ...DEFAULT_SETTINGS,
        ...DEFAULT_RUN_SETTINGS,
        ...(runSettings || {}),
        ...(settings || {}),
    };

    if (hasExplicitQaRunContext(runContext)) {
        if (runContext.locked_output_path) {
            payload.save_path = runContext.locked_output_path;
        }
        if (runContext.locked_date_from) {
            payload.date_from = runContext.locked_date_from;
        }
        if (runContext.locked_date_to) {
            payload.date_to = runContext.locked_date_to;
        }
    }

    payload.task_mode = normalizeTaskMode(payload.task_mode);
    payload.local_input_dir = String(payload.local_input_dir || "").trim();
    payload.local_output_dir = String(payload.local_output_dir || "").trim();
    payload.local_split_by_category = payload.local_split_by_category !== false;

    return payload;
}

async function loadShellState() {
    const [settingsRes, runContextRes, rulesStatusRes] = await Promise.all([
        callApi("load_user_settings"),
        callApi("get_run_context").catch(() => ({})),
        callApi("get_classification_rules_status").catch(() => ({})),
    ]);

    const storedPayload = Object.assign({}, DEFAULT_SETTINGS, DEFAULT_RUN_SETTINGS, (settingsRes && settingsRes.settings) || {});
    const sessionSettings = readSessionValue(SESSION_SETTINGS_KEY);
    const sessionRunSettings = readSessionValue(SESSION_RUN_SETTINGS_KEY);
    const runContext = runContextRes || {};

    const settings = {
        email: preferNonEmpty(sessionSettings.email, storedPayload.email),
        // Sensitive values must not be revived from WebView session state.
        auth_code: preferNonEmpty(storedPayload.auth_code),
        save_path: preferNonEmpty(sessionSettings.save_path, storedPayload.save_path),
        company: preferNonEmpty(sessionSettings.company, storedPayload.company),
        remember_settings: sessionSettings.remember_settings === undefined
            ? storedPayload.remember_settings !== false
            : sessionSettings.remember_settings !== false,
        task_mode: normalizeTaskMode(preferNonEmpty(sessionSettings.task_mode, storedPayload.task_mode, "mail")),
        local_input_dir: preferNonEmpty(sessionSettings.local_input_dir, storedPayload.local_input_dir),
        local_output_dir: preferNonEmpty(sessionSettings.local_output_dir, storedPayload.local_output_dir),
        local_split_by_category: sessionSettings.local_split_by_category === undefined
            ? storedPayload.local_split_by_category !== false
            : sessionSettings.local_split_by_category !== false,
    };

    const runSettings = {
        date_from: preferNonEmpty(sessionRunSettings.date_from, storedPayload.date_from, DEFAULT_RUN_SETTINGS.date_from),
        date_to: preferNonEmpty(sessionRunSettings.date_to, storedPayload.date_to, DEFAULT_RUN_SETTINGS.date_to),
        quick_range: preferNonEmpty(sessionRunSettings.quick_range, storedPayload.quick_range, "last_30_days"),
    };

    if (hasExplicitQaRunContext(runContext)) {
        if (runContext.locked_email) {
            settings.email = runContext.locked_email;
        }
        if (runContext.locked_output_path) {
            settings.save_path = runContext.locked_output_path;
        }
        if (runContext.locked_date_from) {
            runSettings.date_from = runContext.locked_date_from;
        }
        if (runContext.locked_date_to) {
            runSettings.date_to = runContext.locked_date_to;
        }
    }

    return { settings, runSettings, runContext, rulesStatus: rulesStatusRes || {} };
}

async function persistUserSettings(settings, runSettings, runContext) {
    const payload = buildPersistPayload(settings, runSettings, runContext);
    writeSessionValue(SESSION_SETTINGS_KEY, {
        email: payload.email || "",
        save_path: payload.save_path || "",
        company: payload.company || "",
        remember_settings: payload.remember_settings !== false,
        task_mode: normalizeTaskMode(payload.task_mode),
        local_input_dir: payload.local_input_dir || "",
        local_output_dir: payload.local_output_dir || "",
        local_split_by_category: payload.local_split_by_category !== false,
    });
    writeSessionValue(SESSION_RUN_SETTINGS_KEY, {
        date_from: payload.date_from || "",
        date_to: payload.date_to || "",
        quick_range: payload.quick_range || DEFAULT_RUN_SETTINGS.quick_range,
    });

    if (payload.remember_settings === false) {
        return callApi("save_user_settings", { remember_settings: false });
    }
    return callApi("save_user_settings", payload);
}

function toneFromAsyncStatus(status) {
    if (status === "success") return "success";
    if (status === "error") return "error";
    if (status === "testing") return "info";
    return "info";
}

function pad2(value) {
    return `${value}`.padStart(2, "0");
}

function formatClock(timestamp) {
    const value = Number(timestamp || 0);
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`;
}

function formatDuration(totalSeconds) {
    const value = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const minutes = Math.floor(value / 60);
    const seconds = value % 60;
    if (minutes > 0) return `${minutes}分${pad2(seconds)}秒`;
    return `${seconds}秒`;
}

const THEME_STORAGE_KEY = `${BRAND_SESSION_PREFIX}.theme`;

function readStoredTheme() {
    try {
        if (typeof window !== "undefined" && window.localStorage) {
            const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
            if (stored === "light" || stored === "dark") return stored;
        }
    } catch (error) {
        // Local storage can be unavailable in restricted webviews.
    }
    try {
        if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
            if (window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
        }
    } catch (error) {
        // Fall back to the dark workspace when the media query is unavailable.
    }
    return "dark";
}

function applyTheme(theme) {
    try {
        if (typeof document !== "undefined" && document && document.documentElement) {
            document.documentElement.dataset.theme = theme;
        }
    } catch (error) {
        // Theme application is best effort; the default palette stays usable.
    }
}

const INITIAL_THEME = readStoredTheme();
applyTheme(INITIAL_THEME);

function persistTheme(theme) {
    try {
        if (typeof window !== "undefined" && window.localStorage) {
            window.localStorage.setItem(THEME_STORAGE_KEY, theme);
        }
    } catch (error) {
        // Remembering the theme is optional.
    }
}

function useTheme() {
    const [theme, setTheme] = useState(INITIAL_THEME);

    useEffect(() => {
        applyTheme(theme);
    }, [theme]);

    function toggleTheme() {
        setTheme((current) => {
            const next = current === "dark" ? "light" : "dark";
            persistTheme(next);
            return next;
        });
    }

    return { theme, toggleTheme };
}

function useShellSettings() {
    const [settings, setSettings] = useState(DEFAULT_SETTINGS);
    const [runSettings, setRunSettings] = useState(DEFAULT_RUN_SETTINGS);
    const [runContext, setRunContext] = useState({ controlled_run: false, explicit_run_context: false });
    const [rulesStatus, setRulesStatus] = useState({});
    const [bootstrapState, setBootstrapState] = useState("bootstrapping");
    const [bootstrapError, setBootstrapError] = useState("");
    const saveTimerRef = useRef(null);
    const settingsRef = useRef(DEFAULT_SETTINGS);
    const runSettingsRef = useRef(DEFAULT_RUN_SETTINGS);
    const runContextRef = useRef({ controlled_run: false, explicit_run_context: false });

    useEffect(() => {
        let active = true;
        (async () => {
            try {
                const state = await loadShellState();
                if (!active) return;
                settingsRef.current = state.settings;
                runSettingsRef.current = state.runSettings;
                runContextRef.current = state.runContext;
                setSettings(state.settings);
                setRunSettings(state.runSettings);
                setRunContext(state.runContext);
                setRulesStatus(state.rulesStatus || {});
                setBootstrapError("");
                setBootstrapState("bootstrapped");
            } catch (error) {
                if (!active) return;
                setBootstrapError(error.message || UI_COPY.pages.home.errorMessage);
                setBootstrapState("bootstrap_failed");
            }
        })();
        return () => {
            active = false;
            if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        };
    }, []);

    useEffect(() => {
        if (bootstrapState !== "bootstrapped") return undefined;
        if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        saveTimerRef.current = setTimeout(() => {
            persistNow().catch((error) => {
                console.error("Failed to save settings", error);
            });
        }, 400);
        return () => {
            if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        };
    }, [bootstrapState, settings, runSettings, runContext]);

    function updateSetting(key, value) {
        setSettings((current) => {
            const next = { ...current, [key]: value };
            settingsRef.current = next;
            return next;
        });
    }

    function setDateValue(field, value) {
        setRunSettings((current) => {
            const next = { ...current, [field]: value, quick_range: "custom" };
            runSettingsRef.current = next;
            return next;
        });
    }

    async function persistNow(overrides) {
        const nextSettings = (overrides && overrides.settings) || settingsRef.current;
        const nextRunSettings = (overrides && overrides.runSettings) || runSettingsRef.current;
        return persistUserSettings(nextSettings, nextRunSettings, runContextRef.current);
    }

    return {
        settings,
        runSettings,
        runContext,
        rulesStatus,
        bootstrapState,
        bootstrapError,
        updateSetting,
        setDateValue,
        persistNow,
    };
}

function resolveGroupTone(groupKey) {
    if (groupKey === "manual_review") return "group-chip--warning";
    if (groupKey === "retained_record") return "group-chip--info";
    if (groupKey === "processing_error") return "group-chip--error";
    return "";
}

const LOG_KIND_LABELS = {
    error: "异常",
    warning: "提醒",
    success: "成功",
    info: "信息",
};

function resolveLogTone(log) {
    const sample = `${String(log && log.color || "")} ${String(log && log.type || "")}`.toLowerCase();
    if (sample.includes("error") || sample.includes("red")) return "error";
    if (sample.includes("warning") || sample.includes("warn") || sample.includes("amber") || sample.includes("orange")) return "warning";
    if (sample.includes("success") || sample.includes("green") || sample.includes("emerald")) return "success";
    if (sample.includes("info") || sample.includes("blue") || sample.includes("cyan")) return "info";
    return "";
}

function resolveLogToneClass(log) {
    const tone = resolveLogTone(log);
    return tone ? `run-log__kind run-log__kind--${tone}` : "run-log__kind";
}

// 日志级别是后端字段；界面上按中文呈现，未识别的级别原样回退。
function resolveLogKindLabel(log) {
    const tone = resolveLogTone(log);
    if (tone) return LOG_KIND_LABELS[tone];
    return safeText(log && log.type, "日志");
}

function NoticeBox({ tone = "info", className = "", children }) {
    return <div className={joinClasses("notice", `notice--${tone}`, className)}>{children}</div>;
}

function InlineStatus({ tone = "info", children }) {
    const icon = tone === "success" ? "task_alt" : tone === "error" ? "error" : tone === "warning" ? "warning" : "info";
    return (
        <div className={joinClasses("inline-status", `inline-status--${tone}`)}>
            <span aria-hidden="true" className="material-symbols-outlined inline-status__icon">{icon}</span>
            <span className="inline-status__text">{children}</span>
        </div>
    );
}

function StatusPill({ tone = "neutral", icon, children }) {
    return (
        <span className={joinClasses("status-pill", tone !== "neutral" && `status-pill--${tone}`)}>
            {icon && <span aria-hidden="true" className="material-symbols-outlined" style={{ fontSize: 16 }}>{icon}</span>}
            <span>{children}</span>
        </span>
    );
}

function SectionHeader({ title, indicator }) {
    return (
        <div className="section-header">
            <div className="section-title">
                <span>{title}</span>
            </div>
            {indicator ? <div className="u-text-muted" style={{ fontSize: 12 }}>{indicator}</div> : null}
        </div>
    );
}

function PageHeader({ title, description, badge }) {
    return (
        <div className="page-header-shell">
            <div>
                <h1 className="page-title">{title}</h1>
                {description ? <p className="page-description">{description}</p> : null}
            </div>
            {badge ? <div className="page-header-badge">{badge}</div> : null}
        </div>
    );
}

function PageFooter({ left, right }) {
    return (
        <footer className="footer-bar">
            <div className="footer-slot">{left}</div>
            <div className="footer-slot footer-slot--right">{right}</div>
        </footer>
    );
}

function DarkSelect({ value, options, onChange, disabled = false, ariaLabel }) {
    const [open, setOpen] = useState(false);
    const rootRef = useRef(null);
    const activeOption = options.find((option) => option.value === value) || options[0] || { value: "", label: "" };

    useEffect(() => {
        if (!open) return undefined;

        function handlePointerDown(event) {
            if (rootRef.current && !rootRef.current.contains(event.target)) {
                setOpen(false);
            }
        }

        function handleKeyDown(event) {
            if (event.key === "Escape") {
                setOpen(false);
            }
        }

        window.addEventListener("mousedown", handlePointerDown);
        window.addEventListener("keydown", handleKeyDown);
        return () => {
            window.removeEventListener("mousedown", handlePointerDown);
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [open]);

    function handleSelect(nextValue) {
        onChange(nextValue);
        setOpen(false);
    }

    return (
        <div ref={rootRef} className={joinClasses("field-shell", "field-shell--dropdown", disabled && "field-shell--readonly", open && "field-shell--dropdown-open")}>
            <button
                type="button"
                className="field-dropdown-trigger"
                aria-haspopup="listbox"
                aria-expanded={open}
                aria-label={ariaLabel}
                onClick={() => !disabled && setOpen((current) => !current)}
                disabled={disabled}
            >
                <span className="field-dropdown-trigger__label">{activeOption.label}</span>
                <span aria-hidden="true" className="material-symbols-outlined field-dropdown-trigger__icon">{open ? "expand_less" : "expand_more"}</span>
            </button>
            {open ? (
                <div className="field-dropdown-menu" role="listbox" aria-label={ariaLabel}>
                    {options.map((option) => (
                        <button
                            key={option.value}
                            type="button"
                            className={joinClasses("field-dropdown-option", option.value === activeOption.value && "is-active")}
                            onClick={() => handleSelect(option.value)}
                        >
                            <span>{option.label}</span>
                            {option.value === activeOption.value ? <span aria-hidden="true" className="material-symbols-outlined">check</span> : null}
                        </button>
                    ))}
                </div>
            ) : null}
        </div>
    );
}

function DateField({ label, value, onChange, disabled = false, id = "date-field" }) {
    const inputRef = useRef(null);

    function openPicker() {
        if (disabled || !inputRef.current) return;
        if (typeof inputRef.current.showPicker === "function") {
            try {
                inputRef.current.showPicker();
                return;
            } catch (error) {
                // Fall back to focus/click on runtimes without showPicker support.
            }
        }
        inputRef.current.focus();
        inputRef.current.click();
    }

    return (
        <div className="field-block" style={{ flex: 1 }}>
            <label className="field-label" htmlFor={id}>{label}</label>
            <div className={joinClasses("field-shell", "field-shell--date", disabled && "field-shell--readonly")}>
                <input
                    id={id}
                    ref={inputRef}
                    type="date"
                    className="field-input field-input--date"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onClick={openPicker}
                    disabled={disabled}
                />
                <button type="button" className="field-shell-button" onClick={openPicker} disabled={disabled} aria-label={`${label}日历`}>
                    <span aria-hidden="true" className="material-symbols-outlined">calendar_month</span>
                </button>
            </div>
        </div>
    );
}

function AppWindowChrome({ active }) {
    const [closing, setClosing] = useState(false);
    const [minimizing, setMinimizing] = useState(false);
    const [maximizing, setMaximizing] = useState(false);
    const activeItem = UI_COPY.navigation.find((item) => item.key === active);

    async function handleMinimize() {
        if (minimizing) return;
        setMinimizing(true);
        try {
            const result = await callApi("minimize_window");
            if (!result || !result.success) {
                throw new Error((result && result.message) || UI_COPY.shell.minimizeFailed);
            }
        } catch (error) {
            window.alert(error.message || UI_COPY.shell.minimizeFailed);
        } finally {
            setMinimizing(false);
        }
    }

    async function handleMaximize() {
        if (maximizing) return;
        setMaximizing(true);
        try {
            const result = await callApi("maximize_window");
            if (!result || !result.success) {
                throw new Error((result && result.message) || UI_COPY.shell.maximizeFailed);
            }
        } catch (error) {
            window.alert(error.message || UI_COPY.shell.maximizeFailed);
        } finally {
            setMaximizing(false);
        }
    }

    async function handleClose() {
        if (closing) return;
        setClosing(true);
        try {
            const result = await callApi("close_window");
            if (!result || !result.success) {
                throw new Error((result && result.message) || UI_COPY.shell.closeFailed);
            }
        } catch (error) {
            setClosing(false);
            window.alert(error.message || UI_COPY.shell.closeFailed);
        }
    }

    return (
        <div className="window-controls">
            <button
                type="button"
                className="window-traffic-button window-traffic-button--minimize"
                onClick={handleMinimize}
                disabled={minimizing || maximizing || closing}
                aria-label={minimizing ? UI_COPY.shell.minimizing : UI_COPY.shell.minimize}
                title={minimizing ? UI_COPY.shell.minimizing : UI_COPY.shell.minimize}
            >
                <span className="window-traffic-button__glyph"></span>
            </button>
            <button
                type="button"
                className="window-traffic-button window-traffic-button--maximize"
                onClick={handleMaximize}
                disabled={minimizing || maximizing || closing}
                aria-label={maximizing ? UI_COPY.shell.maximizing : UI_COPY.shell.maximize}
                title={maximizing ? UI_COPY.shell.maximizing : UI_COPY.shell.maximize}
            >
                <span className="window-traffic-button__glyph"></span>
            </button>
            <button
                type="button"
                className="window-traffic-button window-traffic-button--close"
                onClick={handleClose}
                disabled={minimizing || maximizing || closing}
                aria-label={closing ? UI_COPY.shell.closing : UI_COPY.shell.close}
                title={closing ? UI_COPY.shell.closing : UI_COPY.shell.close}
            >
                <span className="window-traffic-button__glyph"></span>
            </button>
        </div>
    );
}

function AppSidebar({ active, theme, onToggleTheme, onOpenDisclaimer }) {
    const navigate = useNavigate();
    const githubUrl = APP_VISIBLE_COPY.githubUrl;
    const themeLabel = theme === "dark" ? "浅色模式" : "深色模式";
    const themeActionLabel = theme === "dark" ? "切换到浅色模式" : "切换到深色模式";

    return (
        <aside className="app-sidebar">
            <div className="sidebar-brand pywebview-drag-region">
                <span className="sidebar-brand__name">{APP_BRAND.name}</span>
            </div>

            <nav className="sidebar-nav" aria-label="主导航">
                {UI_COPY.navigation.map((item) => (
                    <button
                        key={item.key}
                        type="button"
                        className={joinClasses("sidebar-tab", active === item.key && "is-active")}
                        aria-current={active === item.key ? "page" : undefined}
                        onClick={() => navigate(item.path)}
                    >
                        <span aria-hidden="true" className="sidebar-tab__icon material-symbols-outlined">{item.icon}</span>
                        <span>{item.label}</span>
                    </button>
                ))}
            </nav>

            <div className="sidebar-spacer pywebview-drag-region"></div>

            <div className="sidebar-foot">
                <button type="button" className="sidebar-action" onClick={onToggleTheme} aria-label={themeActionLabel} title={themeActionLabel}>
                    <span aria-hidden="true" className="material-symbols-outlined">{theme === "dark" ? "light_mode" : "dark_mode"}</span>
                    <span>{themeLabel}</span>
                </button>
                <button type="button" className="sidebar-action" onClick={onOpenDisclaimer}>
                    <span aria-hidden="true" className="material-symbols-outlined">balance</span>
                    <span>免责声明</span>
                </button>
                <button type="button" className="sidebar-action" onClick={() => openExternalUrl(githubUrl)}>
                    <span aria-hidden="true" className="material-symbols-outlined">code</span>
                    <span>{APP_VISIBLE_COPY.githubLabel}</span>
                </button>
            </div>

            <AppWindowChrome active={active} />
        </aside>
    );
}

function AppShell({ active, theme, onToggleTheme, onOpenDisclaimer, children, footerLeft, footerRight, contentClassName = "", contentScrollable = true }) {
    return (
        <div className="app-shell">
            <AppSidebar active={active} theme={theme} onToggleTheme={onToggleTheme} onOpenDisclaimer={onOpenDisclaimer} />
            <main className="app-main">
                <div className={joinClasses("page-scroll", !contentScrollable && "page-scroll--locked", contentClassName)}>{children}</div>
                <PageFooter left={footerLeft} right={footerRight} />
            </main>
        </div>
    );
}

function BootstrapStatePage({ active, theme, onToggleTheme, onOpenDisclaimer, eyebrow, title, description, tone, message, footerText }) {
    return (
        <AppShell active={active} theme={theme} onToggleTheme={onToggleTheme} onOpenDisclaimer={onOpenDisclaimer} footerRight={<p className="footer-meta">{footerText}</p>}>
            <div className="page-wrap page-wrap--narrow">
                <PageHeader eyebrow={eyebrow} title={title} description={description} />
                <NoticeBox tone={tone}>{message}</NoticeBox>
            </div>
        </AppShell>
    );
}

function SummaryField({ span = 6, label, value, helper, icon, tone = "", mono = false, truncate = false }) {
    return (
        <div className={joinClasses("summary-item", tone)} style={{ gridColumn: `span ${span} / span ${span}` }}>
            <div className="summary-item__icon"><span aria-hidden="true" className="material-symbols-outlined">{icon}</span></div>
            <div className="summary-item__copy">
                <p className="summary-item__label">{label}</p>
                <p className={joinClasses("summary-item__value", mono && "u-mono", truncate && "u-truncate")}>{value}</p>
                {helper ? <p className="summary-item__helper">{helper}</p> : null}
            </div>
        </div>
    );
}

function DisclaimerDialog({ open, onClose }) {
    const cardRef = useRef(null);
    const titleId = "disclaimer-dialog-title";

    useEffect(() => {
        if (!open) return undefined;
        const previouslyFocused = document.activeElement;
        function handleKeydown(event) {
            if (event.key === "Escape") onClose();
        }
        window.addEventListener("keydown", handleKeydown);
        if (cardRef.current && cardRef.current.focus) cardRef.current.focus();
        return () => {
            window.removeEventListener("keydown", handleKeydown);
            // 关闭后把焦点还给触发它的按钮，键盘用户不会丢失位置。
            if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
        };
    }, [open, onClose]);

    if (!open) return null;

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={cardRef} onClick={(event) => event.stopPropagation()}>
                <div className="modal-head">
                    <div>
                        <p className="page-eyebrow" style={{ marginBottom: 10 }}>免责声明</p>
                        <h2 id={titleId} className="sheet-title">使用前请确认以下事项</h2>
                    </div>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={onClose} aria-label="关闭免责声明">
                        <span aria-hidden="true" className="material-symbols-outlined">close</span>
                    </button>
                </div>
                <div className="modal-body">
                    <section className="modal-section">
                        <p className="modal-label">软件说明</p>
                        <ul className="modal-list">
                            {DISCLAIMER_SOFTWARE_ITEMS.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                    </section>
                    <section className="modal-section">
                        <p className="modal-label">风险提示</p>
                        <ul className="modal-list">
                            {DISCLAIMER_ITEMS.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                    </section>
                </div>
                <div className="modal-footer">
                    <button type="button" className="btn btn--primary" onClick={onClose}>我已知晓</button>
                </div>
            </div>
        </div>
    );
}

const SETTINGS_SECTION_OPTIONS = [
    { value: "email", label: UI_COPY.pages.settings.emailSection, icon: "mail" },
    { value: "rules", label: UI_COPY.pages.settings.rulesSection, icon: "rule" },
];

function HomePage({ shell, theme, onToggleTheme, onOpenDisclaimer }) {
    const navigate = useNavigate();
    const { settings, runSettings, runContext, updateSetting, setDateValue, persistNow } = shell;
    const [starting, setStarting] = useState(false);
    const [pageError, setPageError] = useState("");
    const [progressState, setProgressState] = useState(DEFAULT_PROGRESS);
    const [pollNonce, setPollNonce] = useState(0);
    const [nowTick, setNowTick] = useState(Date.now());
    const [lastUpdatedAt, setLastUpdatedAt] = useState(0);
    const progressRef = useRef(null);
    const progressStateRef = useRef(DEFAULT_PROGRESS);
    const runStartedAtRef = useRef(0);
    const runFinishedAtRef = useRef(0);
    const autostartTimerRef = useRef(null);
    const autostartTriggeredRef = useRef(false);

    const copy = UI_COPY.pages.home;
    const controlledRun = hasExplicitQaRunContext(runContext);
    const emailValue = String(settings.email || "").trim();
    const companyValue = String(settings.company || "").trim();
    const localInputDir = String(settings.local_input_dir || "").trim();
    const localOutputDir = String(settings.local_output_dir || "").trim();
    const localSplitByCategory = settings.local_split_by_category !== false;
    const taskOptions = useMemo(
        () => TASK_MODE_OPTIONS.map((option) => ({
            ...option,
            icon: option.value === "fetch" ? "download" : option.value === "local" ? "folder_open" : "mail",
            primary: option.value === "mail",
        })),
        []
    );

    useEffect(() => {
        progressStateRef.current = progressState;
    }, [progressState]);

    useEffect(() => {
        let active = true;
        let timer = null;
        const tick = async () => {
            try {
                const data = await callApi("get_progress");
                if (!active || !data) return;
                const next = {
                    ...DEFAULT_PROGRESS,
                    ...data,
                    stats: Object.assign({}, DEFAULT_PROGRESS.stats, data.stats || {}),
                };
                const previous = progressStateRef.current;
                if (next.is_running && !previous.is_running) {
                    if (!runStartedAtRef.current) runStartedAtRef.current = Date.now();
                    runFinishedAtRef.current = 0;
                }
                if (!next.is_running && previous.is_running && ["completed", "failed"].includes(next.run_state)) {
                    runFinishedAtRef.current = Date.now();
                }
                progressStateRef.current = next;
                setProgressState(next);
                setLastUpdatedAt(Date.now());
            } catch (error) {
                if (!active) return;
                setProgressState((current) => ({ ...current, last_error: error.message || "获取进度失败。" }));
            }
            if (!active) return;
            const delay = progressStateRef.current.is_running ? 1000 : 5000;
            timer = setTimeout(tick, delay);
        };
        tick();
        return () => {
            active = false;
            if (timer) clearTimeout(timer);
        };
    }, [pollNonce]);

    useEffect(() => {
        if (!progressState.is_running) return undefined;
        setNowTick(Date.now());
        const timer = setInterval(() => setNowTick(Date.now()), 1000);
        return () => clearInterval(timer);
    }, [progressState.is_running]);

    useEffect(() => {
        if (shell.bootstrapState !== "bootstrapped" || starting || autostartTriggeredRef.current || !shouldAutostartControlledRun(runContext)) return undefined;
        if (isControlledAutostartConsumed(runContext)) {
            autostartTriggeredRef.current = true;
            return undefined;
        }
        const delayMs = Math.max(0, Number(runContext.autostart_delay_ms || 0));
        autostartTimerRef.current = setTimeout(() => {
            autostartTriggeredRef.current = true;
            markControlledAutostartConsumed(runContext);
            startTask(normalizeTaskMode(settings.task_mode));
        }, delayMs);
        return () => {
            if (autostartTimerRef.current) clearTimeout(autostartTimerRef.current);
        };
    }, [shell.bootstrapState, runContext, starting, settings, runSettings]);

    function updateSettingAndClear(key, value) {
        updateSetting(key, value);
        setPageError("");
    }

    function setDateValueAndClear(field, value) {
        setDateValue(field, value);
        setPageError("");
    }

    async function handleChooseDirectory() {
        if (controlledRun) return;
        try {
            const result = await callApi("choose_directory");
            if (result && result.success && result.path) updateSettingAndClear("save_path", result.path);
        } catch (error) {
            setPageError(error.message || "选择目录失败。");
        }
    }

    async function handleChooseInputDirectory() {
        try {
            const result = await callApi("choose_directory");
            if (result && result.success && result.path) updateSettingAndClear("local_input_dir", result.path);
        } catch (error) {
            setPageError(error.message || "选择文件夹失败。");
        }
    }

    async function handleChooseLocalOutputDirectory() {
        if (controlledRun) return;
        try {
            const result = await callApi("choose_directory");
            if (result && result.success && result.path) updateSettingAndClear("local_output_dir", result.path);
        } catch (error) {
            setPageError(error.message || "选择目录失败。");
        }
    }

    function handleResetLocalOutputDirectory() {
        if (controlledRun) return;
        updateSettingAndClear("local_output_dir", "");
    }

    function validateTask(mode) {
        if (mode === "local") {
            if (!localInputDir) return "请选择要整理的本地发票文件夹。";
            return "";
        }
        const emailError = validateEmail(settings.email);
        if (emailError) return emailError;
        if (!settings.auth_code) return "请先在设置中填写邮箱授权码。";
        if (!String(settings.save_path || "").trim()) return "请先选择输出目录。";
        const dateError = validateDateRange(runSettings.date_from, runSettings.date_to);
        if (dateError) return dateError;
        if (mode === "mail" && !companyValue) return "请先在设置中填写公司名称。";
        return "";
    }

    async function startTask(mode) {
        if (starting) return;
        if (progressStateRef.current.is_running) {
            setPageError("任务正在运行，请等待结束或先停止当前任务。");
            return;
        }
        const taskError = validateTask(mode);
        if (taskError) {
            setPageError(taskError);
            return;
        }
        setPageError("");
        setStarting(true);
        try {
            const nextSettings = { ...settings, task_mode: mode };
            updateSetting("task_mode", mode);
            await persistNow({ settings: nextSettings });
            let result = null;
            if (mode === "local") {
                const inputDir = String(settings.local_input_dir || "").trim();
                const outputDir = String(settings.local_output_dir || "").trim() || inputDir;
                result = await callApi("start_local_organize", inputDir, outputDir, false, localSplitByCategory);
            } else if (mode === "fetch") {
                result = await callApi("start_fetch_only", settings.save_path, runSettings.date_from, runSettings.date_to, String(settings.email).trim(), settings.auth_code);
            } else {
                result = await callApi("start_processing", "", settings.save_path, runSettings.date_from, runSettings.date_to, String(settings.email).trim(), settings.auth_code);
            }
            if (!result || !result.success) {
                setPageError((result && result.message) || "任务启动失败。");
                return;
            }
            runStartedAtRef.current = Date.now();
            runFinishedAtRef.current = 0;
            setPollNonce((current) => current + 1);
            if (progressRef.current && progressRef.current.scrollIntoView) {
                progressRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
        } catch (error) {
            setPageError(error.message || "任务启动失败。");
        } finally {
            setStarting(false);
        }
    }

    async function handleStop() {
        if (!progressState.can_stop) return;
        try {
            const result = await callApi("stop_processing");
            if (!result || !result.success) window.alert((result && result.message) || "停止指令发送失败。");
        } catch (error) {
            window.alert(error.message || "停止指令发送失败。");
        }
    }

    const stats = progressState.stats || DEFAULT_PROGRESS.stats;
    const logs = (progressState.logs || []).slice(-6);
    const progressTaskMode = normalizeTaskMode(progressState.task_mode);
    const progressModeOption = TASK_MODE_OPTIONS.find((option) => option.value === progressTaskMode) || TASK_MODE_OPTIONS[0];
    const isLocalTask = progressTaskMode === "local";
    const statusTone = progressState.run_state === "failed" ? "error" : progressState.run_state === "completed" ? "success" : progressState.is_running ? "info" : "neutral";
    const statusLabel = progressState.run_state === "failed" ? "处理失败" : progressState.run_state === "completed" ? "处理完成" : progressState.is_running ? "正在运行" : copy.statusWaiting;
    const processingDetail = progressState.stop_requested
        ? copy.stopDetail
        : progressTaskMode === "fetch"
            ? copy.processingDetailFetch
            : isLocalTask
                ? copy.processingDetailLocal
                : copy.processingDetail;
    const startedAt = runStartedAtRef.current;
    const endedAt = progressState.is_running ? nowTick : (runFinishedAtRef.current || nowTick);
    const elapsedLabel = startedAt ? formatDuration((endedAt - startedAt) / 1000) : "—";
    const hasRunData = progressState.is_running || progressState.run_state !== "idle" || logs.length > 0 || Number(progressState.progress || 0) > 0;
    const canViewResults = !progressState.is_running && ["completed", "failed"].includes(progressState.run_state);
    const activeTaskMode = normalizeTaskMode(settings.task_mode);
    const activeTaskOption = taskOptions.find((option) => option.value === activeTaskMode) || taskOptions[0];

    return (
        <AppShell
            active="home"
            theme={theme}
            onToggleTheme={onToggleTheme}
            onOpenDisclaimer={onOpenDisclaimer}
            footerLeft={<p className="footer-meta">{controlledRun ? copy.controlledNotice : copy.footerMeta}</p>}
            footerRight={canViewResults
                ? <button type="button" className="btn btn--secondary btn--sm" onClick={() => navigate("/results")}><span aria-hidden="true" className="material-symbols-outlined">arrow_forward</span><span>{copy.viewResults}</span></button>
                : null}
        >
            <div className="page-wrap page-wrap--home">
                <PageHeader
                    title={copy.title}
                    description={copy.description}
                    badge={controlledRun ? <StatusPill tone="info">受控前端复跑</StatusPill> : null}
                />
                {pageError ? <NoticeBox tone="error">{pageError}</NoticeBox> : null}
                {controlledRun ? <p className="page-inline-note">{copy.controlledNotice}</p> : null}

                <section className="surface-card">
                    <div className="card-stack card-stack--compact">
                        <div className="mode-picker" role="radiogroup" aria-label={copy.actionsTitle} aria-describedby="task-mode-help">
                            {taskOptions.map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    role="radio"
                                    aria-checked={activeTaskMode === option.value}
                                    className={joinClasses("mode-option", activeTaskMode === option.value && "is-selected")}
                                    onClick={() => updateSettingAndClear("task_mode", option.value)}
                                    disabled={starting || progressState.is_running}
                                >
                                    <span className="mode-option__label">{option.label}</span>
                                </button>
                            ))}
                        </div>
                        <p className="field-help" id="task-mode-help">{activeTaskOption.description}</p>
                        <div className="run-band__actions">
                            <button
                                type="button"
                                className="btn btn--primary"
                                onClick={() => startTask(activeTaskMode)}
                                disabled={starting || progressState.is_running}
                            >
                                <span aria-hidden="true" className="material-symbols-outlined">play_arrow</span>
                                <span>{starting ? "启动中..." : copy.actionsTitle}</span>
                            </button>
                        </div>
                    </div>
                </section>

                <section className="surface-card" ref={progressRef}>
                    <SectionHeader
                        icon="monitor_heart"
                        title={copy.progressTitle}
                        indicator={<StatusPill tone={statusTone}>{statusLabel}</StatusPill>}
                    />
                    <div className="run-progress" aria-live="polite">
                        {hasRunData ? (
                            <>
                                <div className="run-progress__head">
                                    <div>
                                        <p className="progress-kicker">{progressModeOption.label} · {copy.currentOperation}</p>
                                        <h2 className="progress-title">{progressState.status_text || copy.statusWaiting}</h2>
                                        <p className="progress-meta">{processingDetail}</p>
                                    </div>
                                    <div className="progress-value"><strong className="u-tabular">{progressState.progress}%</strong><span>{copy.progressLabel}</span></div>
                                </div>
                                <div
                                    className="progress-track"
                                    role="progressbar"
                                    aria-label={copy.progressLabel}
                                    aria-valuemin={0}
                                    aria-valuemax={100}
                                    aria-valuenow={Math.max(0, Math.min(100, Number(progressState.progress) || 0))}
                                ><div className="progress-fill" style={{ width: `${progressState.progress}%` }}></div></div>
                                <div className="run-progress__meta">
                                    <span><strong>{copy.startTimeLabel}</strong>{formatClock(startedAt)}</span>
                                    <span><strong>{copy.elapsedLabel}</strong>{elapsedLabel}</span>
                                    <span><strong>{copy.updatedLabel}</strong>{formatClock(lastUpdatedAt)}</span>
                                </div>
                                <div className="run-stats">
                                    <div className="summary-item summary-item--accent">
                                        <div className="summary-item__copy">
                                            <p className="summary-item__label">{isLocalTask ? copy.scanFilesLabel : copy.scanEmailsLabel}</p>
                                            <p className="summary-item__value u-tabular">{stats.emails || 0}</p>
                                        </div>
                                    </div>
                                    <div className="summary-item summary-item--success">
                                        <div className="summary-item__copy">
                                            <p className="summary-item__label">已识别发票</p>
                                            <p className="summary-item__value u-tabular">{stats.invoices || 0}</p>
                                        </div>
                                    </div>
                                    <div className="summary-item summary-item--warning">
                                        <div className="summary-item__copy">
                                            <p className="summary-item__label">异常处理</p>
                                            <p className="summary-item__value u-tabular">{stats.errors || 0}</p>
                                        </div>
                                    </div>
                                </div>
                                {progressState.last_error && progressState.run_state === "failed" ? <NoticeBox tone="error">{progressState.last_error}</NoticeBox> : null}
                                {progressState.quota_exhausted && progressState.quota_message ? <NoticeBox tone="warning">{progressState.quota_message}</NoticeBox> : null}
                                {progressState.stop_requested && progressState.run_state !== "failed" ? <NoticeBox tone="warning">{copy.stopNotice}</NoticeBox> : null}
                                <div className="run-log">
                                    <div className="run-log__head"><span aria-hidden="true" className="material-symbols-outlined">info</span><span>{copy.runInfoTitle}</span></div>
                                    {logs.length > 0 ? logs.map((log, index) => (
                                        <div key={`${log.time || "log"}-${index}`} className="run-log__line">
                                            <span className="run-log__time">{safeText(log.time, "[实时]")}</span>
                                            <span className={resolveLogToneClass(log)}>{resolveLogKindLabel(log)}</span>
                                            <span className="run-log__text">{safeText(log.msg, "-")}</span>
                                        </div>
                                    )) : <p className="run-log__empty">{copy.runInfoEmpty}</p>}
                                </div>
                                <div className="footer-cluster">
                                    {progressState.is_running || progressState.can_stop ? (
                                        <button type="button" className="btn btn--danger" onClick={handleStop} disabled={!progressState.can_stop}>
                                            <span aria-hidden="true" className="material-symbols-outlined">{progressState.stop_requested ? "sync" : "close"}</span>
                                            <span>{progressState.stop_requested ? copy.stopping : copy.stop}</span>
                                        </button>
                                    ) : null}
                                    {canViewResults ? (
                                        <button type="button" className="btn btn--secondary" onClick={() => navigate("/results")}>
                                            <span aria-hidden="true" className="material-symbols-outlined">arrow_forward</span>
                                            <span>{copy.viewResults}</span>
                                        </button>
                                    ) : null}
                                </div>
                            </>
                        ) : (
                            <div className="run-empty">
                                <span aria-hidden="true" className="material-symbols-outlined">play_circle</span>
                                <p>{copy.runEmpty}</p>
                            </div>
                        )}
                    </div>
                </section>

                <div className="settings-grid settings-grid--fit">
                    <div className="settings-column">
                        <section className="surface-card">
                            <SectionHeader
                                icon="alternate_email"
                                title="邮箱与公司"
                            />
                            <div className="card-stack card-stack--compact">
                                <div className="field-block">
                                    <label className="field-label" htmlFor="field-2">{copy.emailLabel}</label>
                                    <div className="field-shell field-shell--readonly">
                                        <span aria-hidden="true" className="field-icon material-symbols-outlined">alternate_email</span>
                                        <input id="field-2" type="text" readOnly className="field-input u-mono" value={emailValue} placeholder={copy.unconfigured} title={emailValue || copy.unconfigured} />
                                    </div>
                                    {!emailValue ? <p className="field-help field-help--subtle">{copy.unconfigured}</p> : null}
                                </div>
                                <div className="field-block">
                                    <label className="field-label" htmlFor="field-3">{copy.companyLabel}</label>
                                    <div className="field-shell field-shell--readonly">
                                        <span aria-hidden="true" className="field-icon material-symbols-outlined">business</span>
                                        <input id="field-3" type="text" readOnly className="field-input" value={companyValue} placeholder={copy.unconfigured} title={companyValue || copy.unconfigured} />
                                    </div>
                                    {!companyValue ? <p className="field-help field-help--subtle">{copy.unconfigured}</p> : null}
                                </div>
                                <p className="field-help">{copy.readonlyHint}</p>
                                <div className="footer-cluster">
                                    <button type="button" className="btn btn--secondary btn--sm" onClick={() => navigate("/settings")}>
                                        <span aria-hidden="true" className="material-symbols-outlined">settings</span>
                                        <span>{copy.goSettings}</span>
                                    </button>
                                </div>
                            </div>
                        </section>

                        <section className="surface-card">
                            <SectionHeader
                                icon="schedule"
                                title={copy.dateTitle}
                                indicator={controlledRun ? <StatusPill tone="info" icon="lock">已锁定</StatusPill> : null}
                            />
                            <div className="card-stack card-stack--compact">
                                <div className="field-row field-row--dates settings-date-row">
                                    <DateField label="开始日期" id="run-date-from" value={runSettings.date_from} onChange={(value) => setDateValueAndClear("date_from", value)} disabled={controlledRun} />
                                    <span className="field-separator">—</span>
                                    <DateField label="结束日期" id="run-date-to" value={runSettings.date_to} onChange={(value) => setDateValueAndClear("date_to", value)} disabled={controlledRun} />
                                </div>
                                <p className="field-help field-help--subtle">{copy.dateHint}</p>
                            </div>
                        </section>
                    </div>

                    <div className="settings-column">
                        <section className="surface-card">
                            <SectionHeader
                                icon="folder_open"
                                title={copy.outputTitle}
                                indicator={controlledRun ? <StatusPill tone="info">已锁定</StatusPill> : null}
                            />
                            <div className="card-stack card-stack--compact">
                                <div className={joinClasses("field-shell", "field-shell--readonly", !settings.save_path && "field-shell--error")}>
                                    <span aria-hidden="true" className="field-icon material-symbols-outlined">folder</span>
                                    <input type="text" readOnly aria-label={copy.outputTitle} className="field-input u-mono" value={settings.save_path || ""} placeholder="请选择本地输出目录" title={settings.save_path || ""} />
                                </div>
                                <div className="footer-cluster">
                                    <button type="button" className="btn btn--secondary btn--sm" onClick={handleChooseDirectory} disabled={controlledRun}>
                                        <span aria-hidden="true" className="material-symbols-outlined">folder_open</span>
                                        <span>{controlledRun ? copy.pathLocked : copy.browseDirectory}</span>
                                    </button>
                                </div>
                                <p className="field-help">{controlledRun ? copy.controlledNotice : copy.outputHint}</p>
                            </div>
                        </section>

                        <section className="surface-card">
                            <SectionHeader
                                icon="folder"
                                title={copy.localTitle}
                                indicator={<StatusPill tone={localInputDir ? "success" : "warning"} icon="folder">{localInputDir ? "已选择" : "待选择"}</StatusPill>}
                            />
                            <div className="card-stack card-stack--compact">
                                <div className="field-block">
                                    <label className="field-label" htmlFor="field-4">{copy.localInputLabel}</label>
                                    <div className={joinClasses("field-shell", "field-shell--readonly", !localInputDir && "field-shell--error")}>
                                        <span aria-hidden="true" className="field-icon material-symbols-outlined">folder</span>
                                        <input id="field-4" type="text" readOnly className="field-input u-mono" value={localInputDir} placeholder="请选择要整理的本地文件夹" title={localInputDir} />
                                    </div>
                                    <div className="footer-cluster">
                                        <button type="button" className="btn btn--secondary btn--sm" onClick={handleChooseInputDirectory}>
                                            <span aria-hidden="true" className="material-symbols-outlined">folder_open</span>
                                            <span>{copy.chooseFolder}</span>
                                        </button>
                                    </div>
                                </div>
                                <div className="field-block">
                                    <label className="field-label" htmlFor="field-5">{copy.localOutputLabel}</label>
                                    <div className="field-shell field-shell--readonly">
                                        <span aria-hidden="true" className="field-icon material-symbols-outlined">drive_file_move</span>
                                        <input id="field-5" type="text" readOnly className="field-input u-mono" value={localOutputDir || localInputDir} placeholder="默认同发票文件夹" title={localOutputDir || localInputDir} />
                                    </div>
                                    <div className="footer-cluster">
                                        <button type="button" className="btn btn--secondary btn--sm" onClick={handleChooseLocalOutputDirectory} disabled={controlledRun}>
                                            <span aria-hidden="true" className="material-symbols-outlined">folder_open</span>
                                            <span>{copy.chooseOther}</span>
                                        </button>
                                        {localOutputDir && !controlledRun ? (
                                            <button type="button" className="btn btn--ghost btn--sm" onClick={handleResetLocalOutputDirectory}>
                                                <span aria-hidden="true" className="material-symbols-outlined">undo</span>
                                                <span>{copy.resetLocalOutput}</span>
                                            </button>
                                        ) : null}
                                    </div>
                                </div>
                                <label className="toggle-row">
                                    <input type="checkbox" checked={localSplitByCategory} onChange={(event) => updateSettingAndClear("local_split_by_category", event.target.checked)} disabled={controlledRun} />
                                    <span>{copy.splitByCategory}</span>
                                </label>
                                <p className="field-help">{localSplitByCategory ? copy.splitHelpOn : copy.splitHelpOff}</p>
                                <p className="field-help field-help--subtle">{copy.localHint}</p>
                            </div>
                        </section>
                    </div>
                </div>

            </div>
        </AppShell>
    );
}

function SettingsPage({ shell, theme, onToggleTheme, onOpenDisclaimer }) {
    const location = useLocation();
    const { settings, runContext, rulesStatus, updateSetting, persistNow } = shell;
    const [showAuthCode, setShowAuthCode] = useState(false);
    const [pageError, setPageError] = useState("");
    const [emailStatus, setEmailStatus] = useState({ status: "idle", message: "" });
    const initialSection = location && location.state && location.state.settingsSection === "rules" ? "rules" : "email";
    const [section, setSection] = useState(initialSection);

    const copy = UI_COPY.pages.settings;
    const controlledRun = hasExplicitQaRunContext(runContext);
    const emailError = validateEmail(settings.email);
    const emailDomain = emailDomainOf(settings.email);
    const emailSupported = !emailError && !!emailDomain;
    const rulesIssues = normalizeRuleIssues(rulesStatus && rulesStatus.issues);
    const rulesLibraryAvailable = !!(rulesStatus && rulesStatus.library_available);

    useEffect(() => {
        const requested = location && location.state && location.state.settingsSection;
        if (requested === "rules" || requested === "email") setSection(requested);
    }, [location]);

    function updateSettingAndClear(key, value) {
        updateSetting(key, value);
        setPageError("");
        if (key === "email" || key === "auth_code") setEmailStatus({ status: "idle", message: "" });
    }

    async function handleTestConnection() {
        const emailValidation = validateEmail(settings.email);
        if (emailValidation) {
            setEmailStatus({ status: "error", message: emailValidation });
            return;
        }
        if (!settings.auth_code) {
            setEmailStatus({ status: "error", message: "请输入邮箱授权码。" });
            return;
        }
        setEmailStatus({ status: "testing", message: "正在测试邮箱连接..." });
        try {
            const result = await callApi(
                "test_connection",
                String(settings.email).trim(),
                String(settings.auth_code).trim()
            );
            setEmailStatus({ status: result && result.success ? "success" : "error", message: result && result.message ? result.message : "邮箱连接测试失败。" });
        } catch (error) {
            setEmailStatus({ status: "error", message: error.message || "邮箱连接测试失败。" });
        }
    }

    async function handleSectionChange(nextSection) {
        if (nextSection === section) return;
        if (nextSection === "rules") {
            try {
                await persistNow();
            } catch (error) {
                console.error("Failed to save settings before loading rules", error);
            }
        }
        setSection(nextSection);
    }

    return (
        <AppShell
            active="settings"
            theme={theme}
            onToggleTheme={onToggleTheme}
            onOpenDisclaimer={onOpenDisclaimer}
            footerLeft={
                <label className="toggle-row">
                    <input type="checkbox" checked={settings.remember_settings !== false} onChange={(event) => updateSettingAndClear("remember_settings", event.target.checked)} />
                    <span>{copy.remember}</span>
                </label>
            }
            footerRight={
                <StatusPill tone={controlledRun ? "info" : "neutral"} icon={controlledRun ? "lock" : "save"}>
                    {controlledRun ? "受控复跑" : copy.savedHint}
                </StatusPill>
            }
        >
            <div className="page-wrap page-wrap--settings">
                <PageHeader title={copy.title} description={copy.description} />
                {pageError ? <NoticeBox tone="error">{pageError}</NoticeBox> : null}
                {controlledRun ? <p className="page-inline-note">{copy.controlledNotice}</p> : null}

                <div className="settings-tabbar" role="tablist" aria-label="设置分区">
                    {SETTINGS_SECTION_OPTIONS.map((option) => (
                        <button
                            key={option.value}
                            type="button"
                            role="tab"
                            aria-selected={section === option.value}
                            className={joinClasses("quick-chip", "settings-tab", section === option.value && "is-active")}
                            onClick={() => handleSectionChange(option.value)}
                        >
                            <span aria-hidden="true" className="material-symbols-outlined">{option.icon}</span>
                            <span>{option.label}</span>
                            {option.value === "rules" && rulesIssues.length > 0 ? <span className="settings-tab__badge">{rulesIssues.length}</span> : null}
                        </button>
                    ))}
                </div>

                <div className={joinClasses("settings-section", section !== "email" && "is-hidden")} hidden={section !== "email"}>
                    <div className="settings-grid settings-grid--fit">
                        <div className="settings-column">
                            <section className="surface-card">
                                <SectionHeader icon="mail" title={copy.emailCardTitle} indicator={<StatusPill tone={emailSupported ? "success" : "warning"} icon="mail">{emailSupported ? "域名可用" : "待确认"}</StatusPill>} />
                                <div className="card-stack card-stack--compact">
                                    <div className="field-block">
                                        <label className="field-label" htmlFor="field-6">邮箱地址</label>
                                        <div className="field-shell">
                                            <span aria-hidden="true" className="field-icon material-symbols-outlined">alternate_email</span>
                                            <input id="field-6" type="text" className="field-input" placeholder="name@qq.com" value={settings.email} onChange={(event) => updateSettingAndClear("email", event.target.value)} />
                                        </div>
                                        <p className="field-help">
                                            {emailSupported
                                                ? `${emailDomain} 属于受支持的邮箱域名。`
                                                : "支持 QQ、网易 163/126/188/yeah、88、腾讯企业邮、阿里邮箱、新浪、搜狐、21CN、263、139/189 及 Gmail、iCloud、Yahoo 等常用邮箱；国际邮箱请使用应用专用密码。"}
                                        </p>
                                    </div>
                                    <div className="field-block">
                                        <label className="field-label" htmlFor="field-7">授权码</label>
                                        <div className="field-shell">
                                            <span aria-hidden="true" className="field-icon material-symbols-outlined">key</span>
                                            <input id="field-7" type={showAuthCode ? "text" : "password"} className="field-input u-mono" placeholder="请输入邮箱授权码" value={settings.auth_code} onChange={(event) => updateSettingAndClear("auth_code", event.target.value)} />
                                            <button type="button" className="field-mask-toggle" aria-label={showAuthCode ? "隐藏授权码" : "显示授权码"} aria-pressed={showAuthCode} onClick={() => setShowAuthCode((current) => !current)}>
                                                <span aria-hidden="true" className="material-symbols-outlined">{showAuthCode ? "visibility" : "visibility_off"}</span>
                                            </button>
                                        </div>
                                        <div className="footer-cluster">
                                            <button type="button" className="btn btn--secondary btn--sm" onClick={handleTestConnection} disabled={emailStatus.status === "testing"}>
                                                <span aria-hidden="true" className="material-symbols-outlined">{emailStatus.status === "testing" ? "sync" : "link"}</span>
                                                <span>{emailStatus.status === "testing" ? "测试中..." : "测试邮箱连接"}</span>
                                            </button>
                                        </div>
                                        {emailStatus.status !== "idle" ? <InlineStatus tone={toneFromAsyncStatus(emailStatus.status)}>{emailStatus.message}</InlineStatus> : null}
                                    </div>
                                </div>
                            </section>
                        </div>
                        <div className="settings-column">
                            <section className="surface-card">
                                <SectionHeader icon="business" title={copy.companyCardTitle} indicator={<StatusPill tone={String(settings.company || "").trim() ? "success" : "warning"} icon="apartment">购买方校验</StatusPill>} />
                                <div className="card-stack card-stack--compact">
                                    <div className="field-block">
                                        <label className="field-label" htmlFor="field-8">公司 <span className="field-required">*</span></label>
                                        <div className={joinClasses("field-shell", !String(settings.company || "").trim() ? "field-shell--error" : "")}>
                                            <span aria-hidden="true" className="field-icon material-symbols-outlined">domain</span>
                                            <input id="field-8" type="text" className="field-input" placeholder="填写用于匹配购买方的公司名称" value={settings.company || ""} onChange={(event) => updateSettingAndClear("company", event.target.value)} />
                                        </div>
                                        {!String(settings.company || "").trim()
                                            ? <p className="field-help field-help--subtle">填写公司名称后按购买方字段匹配；首页会只读展示该名称。</p>
                                            : <p className="field-help field-help--subtle">按购买方包含“{String(settings.company).trim()}”进行匹配；明确不匹配的票据会单独进入“非目标公司发票”。</p>}
                                    </div>
                                    <p className="field-help">邮箱任务需要公司名称用于购买方校验；只做邮箱提取时可不填。</p>
                                </div>
                            </section>
                        </div>
                    </div>
                </div>

                <div className={joinClasses("settings-section", section !== "rules" && "is-hidden")} hidden={section !== "rules"}>
                    <div className="settings-rules-head">
                        <div>
                            <p className="page-eyebrow">{UI_COPY.pages.rules.title}</p>
                            <p className="field-help">{UI_COPY.pages.rules.description}</p>
                        </div>
                        <StatusPill tone={rulesIssues.length > 0 ? "warning" : "success"} icon={rulesIssues.length > 0 ? "warning" : "rule"}>
                            {rulesIssues.length > 0 ? `${rulesIssues.length} 条提示` : (rulesLibraryAvailable ? "含发票库规则" : "使用全局规则")}
                        </StatusPill>
                    </div>
                    <RulesWorkspace prepare={() => persistNow()} />
                </div>
            </div>
        </AppShell>
    );
}


function fileExtension(path) {
    const value = String(path || "").toLowerCase();
    if (!value) return "";
    if (value.endsWith(".url.txt")) return ".url.txt";
    const match = value.match(/(\.[^./\\]+)$/);
    return match ? match[1] : "";
}

function describeResultFile(path) {
    const extension = fileExtension(path);
    if ([".pdf", ".jpg", ".jpeg", ".png", ".ofd", ".xml"].includes(extension)) {
        return { extension, fileKindLabel: extension === ".xml" ? "XML 原件" : extension === ".ofd" ? "OFD 原件" : [".jpg", ".jpeg", ".png"].includes(extension) ? "图片原件" : "PDF 原件" };
    }
    if ([".txt", ".url.txt", ".log", ".json"].includes(extension)) {
        return { extension, fileKindLabel: extension === ".url.txt" ? "链接记录" : "记录文件" };
    }
    return { extension, fileKindLabel: "文件" };
}

function normalizeSuccessInvoices(items, offset = 0) {
    return (items || []).map((item, index) => {
        const path = item.path || "";
        const fileMeta = describeResultFile(path);
        const globalIndex = offset + index;
        return {
            key: path || `${item.date || "row"}-${globalIndex}`,
            date: safeText(item.date),
            amount: safeText(item.amount),
            merchant: safeText(item.merchant || item.vendor),
            archiveType: String(item.category || "").trim() || safeText(fileMeta.fileKindLabel),
            path,
            fileName: fileNameFromPath(path),
        };
    });
}

function normalizeGroupedErrors(groups) {
    return (groups || []).map((group, groupIndex) => ({
        key: group.key || `group-${groupIndex}`,
        label: group.key === "retained_record"
            ? "暂存记录"
            : group.key === "manual_review"
                ? "待人工复核"
                : group.key === "processing_error"
                    ? "真实异常"
                    : group.label || "待处理记录",
        count: Number(group.count || 0),
        items: (group.items || []).map((item, itemIndex) => {
            const path = item.path || "";
            return { rowKey: path || `${group.key || "group"}-${itemIndex}`, date: safeText(item.date), reason: safeText(item.reason, group.label || "待处理"), status: safeText(item.status, "待处理"), merchant: safeText(item.merchant), path, fileName: fileNameFromPath(path) };
        }),
    }));
}

function buildResultStatusText(successCount, manualCheckCount, retentionCount, processingErrorCount) {
    const pendingCount = manualCheckCount + retentionCount + processingErrorCount;
    if (successCount > 0 && pendingCount === 0) return "主要结果已经整理完成，本轮没有需要额外关注的记录。";
    if (successCount > 0 && pendingCount > 0) {
        if (manualCheckCount > 0 && retentionCount > 0 && processingErrorCount > 0) {
            return `已整理 ${successCount} 条成功记录；请先处理 ${manualCheckCount} 条待人工复核记录，另有 ${retentionCount} 条暂存记录与 ${processingErrorCount} 条真实异常需要查看。`;
        }
        if (manualCheckCount > 0 && retentionCount > 0) {
            return `已整理 ${successCount} 条成功记录；请优先查看 ${manualCheckCount} 条待人工复核记录，另有 ${retentionCount} 条暂存记录可按需导出查看。`;
        }
        if (manualCheckCount > 0 && processingErrorCount > 0) {
            return `已整理 ${successCount} 条成功记录；当前需要关注 ${manualCheckCount} 条待人工复核记录和 ${processingErrorCount} 条真实异常。`;
        }
        if (manualCheckCount > 0) {
            return `已整理 ${successCount} 条成功记录；当前需要你关注的是 ${manualCheckCount} 条待人工复核记录。`;
        }
        if (retentionCount > 0 && processingErrorCount > 0) {
            return `已整理 ${successCount} 条成功记录，另有 ${retentionCount} 条暂存记录和 ${processingErrorCount} 条真实异常需要查看。`;
        }
        if (retentionCount > 0) return `已整理 ${successCount} 条成功记录，另有 ${retentionCount} 条暂存记录可按需导出查看。`;
        if (processingErrorCount > 0) return `已整理 ${successCount} 条成功记录，但仍有 ${processingErrorCount} 条真实异常需要排查。`;
    }
    if (successCount === 0 && pendingCount > 0) {
        if (manualCheckCount > 0) return `本轮暂无可直接归档的记录；请先查看 ${manualCheckCount} 条待人工复核记录，其余结果可按需导出查看。`;
        if (retentionCount > 0 && processingErrorCount > 0) return `本轮暂无可直接归档的记录，当前有 ${retentionCount} 条暂存记录和 ${processingErrorCount} 条真实异常。`;
        if (retentionCount > 0) return "本轮暂无可直接归档的记录，当前结果可通过导出明细进一步查看。";
        if (processingErrorCount > 0) return `本轮暂无可直接归档的记录，当前有 ${processingErrorCount} 条真实异常需要排查。`;
    }
    return "本轮尚未生成可展示的结果记录。";
}

function ResultSummaryCard({ icon, label, value, helper, tone = "info" }) {
    return (
        <section className={joinClasses("stat-card", `stat-card--${tone}`)}>
            <div className="stat-card__top">
                <div className="stat-card__icon"><span aria-hidden="true" className="material-symbols-outlined">{icon}</span></div>
                <div className="stat-card__copy"><p className="stat-card__label">{label}</p><p className="stat-card__value u-tabular">{value}</p></div>
            </div>
            <p className="stat-card__helper">{helper}</p>
        </section>
    );
}

function ResultToolbarButton({ icon, label, onClick, disabled = false, primary = false }) {
    return <button type="button" className={joinClasses("btn", primary ? "btn--primary" : "btn--secondary", "btn--sm")} onClick={onClick} disabled={disabled}><span aria-hidden="true" className="material-symbols-outlined">{icon}</span><span>{label}</span></button>;
}

function ResultActionBanner({ tone = "warning", icon, eyebrow, title, text, buttonLabel, onClick, disabled = false, pathText = "", chips = null }) {
    return (
        <section className={joinClasses("manual-banner", tone === "neutral" && "manual-banner--calm", tone === "neutral" && "manual-banner--output")}>
            <div className="manual-banner__lead">
                <div className="manual-banner__icon"><span aria-hidden="true" className="material-symbols-outlined">{icon}</span></div>
                <div>
                    <p className="manual-banner__eyebrow">{eyebrow}</p>
                    <p className="manual-banner__title">{title}</p>
                    <p className="manual-banner__text">{text}</p>
                    {pathText ? <p className="manual-banner__path u-mono" title={pathText}>{pathText}</p> : null}
                    {chips}
                </div>
            </div>
            <button type="button" className="btn btn--secondary" onClick={onClick} disabled={disabled}>
                <span aria-hidden="true" className="material-symbols-outlined">{icon}</span>
                <span>{buttonLabel}</span>
            </button>
        </section>
    );
}

function RuleIssues({ issues, title = "规则校验未通过", tone = "error" }) {
    const items = normalizeRuleIssues(issues);
    if (items.length === 0) return null;
    return (
        <NoticeBox tone={tone}>
            <div className="rule-issues">
                <p className="rule-issues__title">{title}</p>
                <ul className="rule-issue-list">
                    {items.map((issue, index) => (
                        <li key={`${issue.text}-${index}`} className="rule-issue-item" title={ruleLocationTitle(issue.file, issue.line)}>{issue.text}</li>
                    ))}
                </ul>
            </div>
        </NoticeBox>
    );
}

function RuleEditor({ editor, documentTypes, onChange, onCreateType, onCommit, onCancel }) {
    const [creatingType, setCreatingType] = useState(false);
    const [typeName, setTypeName] = useState("");
    const [typeError, setTypeError] = useState("");
    const [typeBusy, setTypeBusy] = useState(false);

    if (!editor) {
        return (
            <div className="rules-empty-state">
                <span aria-hidden="true" className="material-symbols-outlined">edit_note</span>
                <p>选择一条规则编辑，或新增一条规则。</p>
            </div>
        );
    }

    const previewFolder = buildRuleFolderName(editor.targetType, buildRuleAmountRange(editor.amountMin, editor.amountMax));
    const typeOptions = [{ value: "", label: "请选择目标票种" }].concat(documentTypes.map((type) => ({ value: type, label: type })));

    async function handleCreateType() {
        const name = typeName.trim();
        if (!name) {
            setTypeError("请填写票种名称。");
            return;
        }
        if (typeBusy) return;
        setTypeBusy(true);
        try {
            const result = await onCreateType(name);
            if (!result || result.success !== true) {
                const issueText = result && Array.isArray(result.issues) && result.issues.length > 0
                    ? String(result.issues[0].text || result.issues[0].message || "")
                    : "";
                setTypeError(issueText || (result && result.message) || "新建票种失败，请稍后重试。");
                return;
            }
            setCreatingType(false);
            setTypeName("");
            setTypeError("");
            onChange({ targetType: String(result.name || name) });
        } finally {
            setTypeBusy(false);
        }
    }

    function handleCancelCreateType() {
        setCreatingType(false);
        setTypeName("");
        setTypeError("");
    }

    return (
        <div className="card-stack card-stack--compact">
            <div className="rules-editor-grid">
                <div className="field-block field-block--wide">
                    <label className="field-label">目标票种 <span className="field-required">*</span></label>
                    <div className="rule-target-row">
                        <div className="rule-target-select">
                            <DarkSelect value={editor.targetType} options={typeOptions} onChange={(value) => onChange({ targetType: value })} ariaLabel="目标票种" />
                        </div>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => {
                            setCreatingType(true);
                            setTypeError("");
                        }}>
                            <span aria-hidden="true" className="material-symbols-outlined">add</span>
                            <span>新建票种</span>
                        </button>
                    </div>
                    {creatingType ? (
                        <div className="rule-type-create">
                            <div className="field-shell" style={{ flex: 1, minWidth: 140 }}>
                                <span aria-hidden="true" className="field-icon material-symbols-outlined">category</span>
                                <input type="text" className="field-input" placeholder="输入新票种名称，如 会议" value={typeName} onChange={(event) => {
                                    setTypeName(event.target.value);
                                    setTypeError("");
                                }} autoFocus />
                            </div>
                            <button type="button" className="btn btn--primary btn--sm" onClick={handleCreateType} disabled={typeBusy}>
                                <span aria-hidden="true" className="material-symbols-outlined">{typeBusy ? "sync" : "check"}</span>
                                <span>{typeBusy ? "创建中..." : "确认新建"}</span>
                            </button>
                            <button type="button" className="btn btn--ghost btn--sm" onClick={handleCancelCreateType} disabled={typeBusy}>
                                <span>取消</span>
                            </button>
                        </div>
                    ) : null}
                    {typeError ? <p className="field-help field-help--error">{typeError}</p> : null}
                    <p className="field-help">{RULE_TARGET_TYPE_HELP}</p>
                </div>
                <div className="field-block field-block--wide">
                    <label className="field-label" htmlFor="field-9">关键词 <span className="field-required">*</span></label>
                    <div className="field-shell">
                        <span aria-hidden="true" className="field-icon material-symbols-outlined">key</span>
                        <input id="field-9" type="text" className="field-input" placeholder="如 滴滴、星巴克、某某酒店" value={editor.keyword} onChange={(event) => onChange({ keyword: event.target.value })} />
                    </div>
                    <p className="field-help">发票的销售方或明细包含该关键词时命中本规则。</p>
                </div>
                <div className="field-block">
                    <label className="field-label" htmlFor="field-10">金额下限</label>
                    <div className="field-shell">
                        <input id="field-10" type="text" inputMode="decimal" className="field-input u-tabular" placeholder="不限" value={editor.amountMin} onChange={(event) => onChange({ amountMin: event.target.value })} />
                    </div>
                </div>
                <div className="field-block">
                    <label className="field-label" htmlFor="field-11">金额上限</label>
                    <div className="field-shell">
                        <input id="field-11" type="text" inputMode="decimal" className="field-input u-tabular" placeholder="不限" value={editor.amountMax} onChange={(event) => onChange({ amountMax: event.target.value })} />
                    </div>
                </div>
                <div className="field-block">
                    <label className="field-label" htmlFor="field-12">启用</label>
                    <label className="toggle-row">
                        <input id="field-12" type="checkbox" checked={editor.enabled !== false} onChange={(event) => onChange({ enabled: event.target.checked })} />
                        <span>{editor.enabled !== false ? "已启用" : "已停用"}</span>
                    </label>
                </div>
                <div className="field-block field-block--wide">
                    <label className="field-label">归档到</label>
                    <div className="rule-archive-summary">
                        <span aria-hidden="true" className="material-symbols-outlined">folder</span>
                        <span>{previewFolder ? `归档到：${previewFolder}` : "请选择目标票种，并填写关键词和金额范围"}</span>
                    </div>
                    <p className="field-help">文件夹由目标票种和金额范围自动生成，不需要手动填写；保存后生效。</p>
                </div>
            </div>
            {editor.error ? <NoticeBox tone="error">{editor.error}</NoticeBox> : null}
            <div className="footer-cluster">
                <button type="button" className="btn btn--primary btn--sm" onClick={onCommit}>
                    <span aria-hidden="true" className="material-symbols-outlined">check</span>
                    <span>{editor.mode === "new" ? "添加规则" : "保存修改"}</span>
                </button>
                <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel}>
                    <span aria-hidden="true" className="material-symbols-outlined">close</span>
                    <span>取消</span>
                </button>
            </div>
        </div>
    );
}

function RuleTestResult({ result, categoryNameById, targetTypeById }) {
    if (!result) return null;
    const unknown = String(result.source || "") === "unknown" || !String(result.category_id || "").trim();
    if (unknown) {
        return (
            <NoticeBox tone="warning">
                <div>
                    <p className="rule-test-result__unknown">将进入待人工复核</p>
                    <p className="field-help">这张发票没有命中任何已启用规则，整理时会放入「待人工复核」文件夹。</p>
                </div>
            </NoticeBox>
        );
    }
    const categoryId = String(result.category_id || "");
    const targetType = String(result.target_type || (targetTypeById || {})[categoryId] || "");
    const chainSteps = (Array.isArray(result.chain) ? result.chain : [])
        .map((step) => describeRuleChainStep(step, categoryNameById))
        .filter(Boolean)
        .slice(0, 10);
    return (
        <div className="rule-test-result">
            <div className="rule-category-row__title">
                <StatusPill tone="success" icon="task_alt">{safeText(result.category_name, safeText(result.archive_folder, "已归类"))}</StatusPill>
                {targetType ? <span className="rule-target-tag" title={`目标票种：${targetType}`}>{targetType}</span> : null}
            </div>
            <div className="rules-kv-list">
                <div className="rules-kv"><span>目标票种</span><strong>{targetType || "--"}</strong></div>
                <div className="rules-kv"><span>归档到</span><strong className="u-mono">{safeText(result.archive_folder, "--")}</strong></div>
                <div className="rules-kv"><span>命中关键词</span><strong>{safeText(result.keyword, "--")}</strong></div>
                <div className="rules-kv"><span>规则位置</span><strong className="u-mono">{ruleLocationText(result.source_file, result.source_line) || "--"}</strong></div>
                <div className="rules-kv"><span>归类来源</span><strong>{classificationSourceLabel(result.source)}</strong></div>
            </div>
            {chainSteps.length > 0 ? (
                <div className="rule-chain-block">
                    <p className="field-label">匹配过程</p>
                    <div className="rule-chain">
                        {chainSteps.map((step, index) => <span key={`${index}-${step}`} className="rule-chain__step">{step}</span>)}
                    </div>
                </div>
            ) : null}
        </div>
    );
}

function RuleDictionarySection({ terms, categoryOptions, scope, onAddTerm, onDeleteTerm }) {
    const [termText, setTermText] = useState("");
    const [category, setCategory] = useState("");
    const [error, setError] = useState("");
    const categoryNameById = useMemo(() => {
        const map = {};
        (categoryOptions || []).forEach((item) => {
            const id = String((item && item.id) || "");
            if (!id) return;
            map[id] = buildRuleFolderName(item.target_type, item.amount_range) || String(item.name || item.archive_folder || id);
        });
        return map;
    }, [categoryOptions]);
    const selectOptions = useMemo(() => {
        const options = [{ value: "", label: "选择规则" }];
        (categoryOptions || []).forEach((item) => {
            const id = String((item && item.id) || "");
            if (!id) return;
            const name = buildRuleFolderName(item.target_type, item.amount_range) || String(item.name || "");
            options.push({ value: id, label: name ? `${name}（${id}）` : id });
        });
        return options;
    }, [categoryOptions]);

    function handleAdd() {
        const term = termText.trim();
        if (!term) return setError("请填写销售方名称或税号。");
        if (!category) return setError("请选择归入的规则。");
        if ((terms || []).some((item) => String((item && item.term) || "").trim() === term)) {
            return setError("该销售方已在词典中，请直接修改现有条目。");
        }
        setError("");
        onAddTerm({ term, category });
        setTermText("");
        setCategory("");
    }

    return (
        <div className="card-stack card-stack--compact">
            <div className="rule-dictionary-form">
                <div className="field-block">
                    <label className="field-label" htmlFor="field-13">销售方名称或税号</label>
                    <div className="field-shell">
                        <input id="field-13" type="text" className="field-input" placeholder="如 某某餐饮管理有限公司" value={termText} onChange={(event) => {
                            setTermText(event.target.value);
                            setError("");
                        }} />
                    </div>
                </div>
                <div className="field-block">
                    <label className="field-label">归入规则</label>
                    <DarkSelect value={category} options={selectOptions} onChange={(value) => {
                        setCategory(value);
                        setError("");
                    }} ariaLabel="词典归入规则" />
                </div>
            </div>
            <div className="footer-cluster">
                <button type="button" className="btn btn--secondary btn--sm" onClick={handleAdd}>
                    <span aria-hidden="true" className="material-symbols-outlined">add_circle</span>
                    <span>添加词典</span>
                </button>
                <span className="field-help">按销售方精确匹配，适合固定供应商。</span>
            </div>
            {error ? <NoticeBox tone="error">{error}</NoticeBox> : null}
            {(terms || []).length === 0 ? <p className="field-help">还没有销售方词典条目。</p> : (
                <div className="rule-dictionary-list">
                    {terms.map((term, index) => (
                        <div key={`${term.term}-${index}`} className="rule-dictionary-row">
                            <div className="rule-dictionary-row__copy">
                                <strong className="u-truncate" title={term.term}>{term.term || "未命名销售方"}</strong>
                                <span>归入 {categoryNameById[String(term.category || "")] || safeText(term.category, "未指定规则")}</span>
                            </div>
                            <StatusPill tone="neutral">{ruleLayerLabel(term.source_layer || scope)}</StatusPill>
                            <button type="button" className="rule-icon-button" title="删除词典条目" aria-label={`删除 ${term.term}`} onClick={() => onDeleteTerm(index)}>
                                <span aria-hidden="true" className="material-symbols-outlined">delete</span>
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function RuleUnclassifiedSection({ invoices, onPrefill }) {
    const rows = Array.isArray(invoices) ? invoices : [];
    if (rows.length === 0) return null;
    return (
        <section className="surface-card">
            <SectionHeader icon="help" title="未归类发票" indicator={<StatusPill tone="warning" icon="warning">待补充规则</StatusPill>} />
            <div className="card-stack card-stack--compact">
                <p className="field-help">这些发票在最近一次整理中没有命中任何规则，整理后会进入待人工复核。可按发票信息预填一条规则，并选择目标票种。</p>
                <div className="rule-unclassified-list">
                    {rows.slice(0, 20).map((row, index) => (
                        <div key={`${row.document_id || row.path || "invoice"}-${index}`} className="rule-unclassified-row">
                            <div className="rule-unclassified-row__copy">
                                <strong className="u-truncate" title={safeText(row.merchant, "")}>{safeText(row.merchant, "未识别销售方")}</strong>
                                <span>{safeText(row.type, "未知票种")} · {formatRuleInvoiceAmountLabel(row.amount)}{row.date ? ` · ${row.date}` : ""}</span>
                            </div>
                            <button type="button" className="btn btn--secondary btn--sm" onClick={() => onPrefill(row)}>
                                <span aria-hidden="true" className="material-symbols-outlined">add_circle</span>
                                <span>据此新建规则</span>
                            </button>
                        </div>
                    ))}
                </div>
                {rows.length > 20 ? <p className="field-help">仅显示前 20 条，共 {rows.length} 条。</p> : null}
            </div>
        </section>
    );
}

function RuleBuiltinSection({ rows, busy, onEdit, onToggle, onRestore, onRestoreAll }) {
    const items = Array.isArray(rows) ? rows : [];
    return (
        <section className="surface-card rules-builtin">
            <SectionHeader icon="inventory_2" title="内置默认规则" indicator={<StatusPill tone="neutral">{`${items.length} 条 · 可覆盖`}</StatusPill>} />
            <div className="card-stack card-stack--compact">
                <div className="rules-toolbar">
                    <p className="field-help">内置规则可按当前作用范围覆盖；目标票种决定归档文件夹和归类结果，内置规则原有的票种兜底条件会自动保留。未命中自定义规则时按列表顺序兜底。</p>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={onRestoreAll} disabled={busy}>
                        <span aria-hidden="true" className="material-symbols-outlined">restart_alt</span>
                        <span>全部恢复默认</span>
                    </button>
                </div>
                {items.length === 0 ? (
                    <p className="field-help">暂未获取到内置规则。</p>
                ) : (
                    <div className="rules-builtin-list">
                        {items.map((row) => {
                            const keywords = (Array.isArray(row.keywords) ? row.keywords : []).map((value) => String(value));
                            const folderText = row.previewFolder || "请选择目标票种";
                            return (
                                <div className="rules-builtin-row" key={row.id}>
                                    <span className="rules-builtin-row__folder u-truncate" title={folderText}>
                                        <span aria-hidden="true" className="material-symbols-outlined">folder</span>
                                        <span className="u-truncate">{folderText}</span>
                                        {row.target_type
                                            ? <span className="rule-target-tag" title={`目标票种：${row.target_type}`}>{row.target_type}</span>
                                            : <StatusPill tone="warning">缺少目标票种</StatusPill>}
                                    </span>
                                    <span className="rules-builtin-row__keywords u-truncate" title={keywords.join("、")}>{keywords.length > 0 ? keywords.join("、") : "无关键词"}</span>
                                    <span className="rules-builtin-row__badge">
                                        <StatusPill tone={row.modified ? "warning" : "neutral"}>{row.modified ? "已修改" : "内置"}</StatusPill>
                                        {row.enabled === false ? <StatusPill tone="warning">已停用</StatusPill> : null}
                                    </span>
                                    <span className="rules-builtin-row__actions">
                                        <button
                                            type="button"
                                            className={joinClasses("rule-icon-button", row.enabled !== false && "is-active")}
                                            title={row.enabled !== false ? "停用" : "启用"}
                                            aria-label={`${row.enabled !== false ? "停用" : "启用"}内置规则 ${folderText}`}
                                            onClick={() => onToggle(row)}
                                        >
                                            <span aria-hidden="true" className="material-symbols-outlined">{row.enabled !== false ? "toggle_on" : "toggle_off"}</span>
                                        </button>
                                        <button type="button" className="rule-icon-button" title="编辑" aria-label={`编辑内置规则 ${folderText}`} onClick={() => onEdit(row)}>
                                            <span aria-hidden="true" className="material-symbols-outlined">edit</span>
                                        </button>
                                        <button type="button" className="rule-icon-button" title="恢复默认" aria-label={`恢复默认内置规则 ${folderText}`} onClick={() => onRestore(row)}>
                                            <span aria-hidden="true" className="material-symbols-outlined">restart_alt</span>
                                        </button>
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </section>
    );
}

function RuleBuiltinEditor({ editor, documentTypes, onChange, onCreateType, onCommit, onCancel }) {
    const [creatingType, setCreatingType] = useState(false);
    const [typeName, setTypeName] = useState("");
    const [typeError, setTypeError] = useState("");
    const [typeBusy, setTypeBusy] = useState(false);

    if (!editor) {
        return (
            <div className="rules-empty-state">
                <span aria-hidden="true" className="material-symbols-outlined">inventory_2</span>
                <p>从内置默认规则中选择一条进行覆盖编辑。</p>
            </div>
        );
    }

    const previewFolder = buildRuleFolderName(editor.targetType, buildRuleAmountRange(editor.amountMin, editor.amountMax));
    const typeOptions = [{ value: "", label: "请选择目标票种" }].concat(documentTypes.map((type) => ({ value: type, label: type })));

    async function handleCreateType() {
        const name = typeName.trim();
        if (!name) {
            setTypeError("请填写票种名称。");
            return;
        }
        if (typeBusy) return;
        setTypeBusy(true);
        try {
            const result = await onCreateType(name);
            if (!result || result.success !== true) {
                const issueText = result && Array.isArray(result.issues) && result.issues.length > 0
                    ? String(result.issues[0].text || result.issues[0].message || "")
                    : "";
                setTypeError(issueText || (result && result.message) || "新建票种失败，请稍后重试。");
                return;
            }
            setCreatingType(false);
            setTypeName("");
            setTypeError("");
            onChange({ targetType: String(result.name || name) });
        } finally {
            setTypeBusy(false);
        }
    }

    function handleCancelCreateType() {
        setCreatingType(false);
        setTypeName("");
        setTypeError("");
    }

    return (
        <div className="card-stack card-stack--compact">
            <div className="rules-editor-grid">
                <div className="field-block field-block--wide">
                    <label className="field-label">目标票种 <span className="field-required">*</span></label>
                    <div className="rule-target-row">
                        <div className="rule-target-select">
                            <DarkSelect value={editor.targetType} options={typeOptions} onChange={(value) => onChange({ targetType: value })} ariaLabel="目标票种" />
                        </div>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => {
                            setCreatingType(true);
                            setTypeError("");
                        }}>
                            <span aria-hidden="true" className="material-symbols-outlined">add</span>
                            <span>新建票种</span>
                        </button>
                    </div>
                    {creatingType ? (
                        <div className="rule-type-create">
                            <div className="field-shell" style={{ flex: 1, minWidth: 140 }}>
                                <span aria-hidden="true" className="field-icon material-symbols-outlined">category</span>
                                <input type="text" className="field-input" placeholder="输入新票种名称，如 会议" value={typeName} onChange={(event) => {
                                    setTypeName(event.target.value);
                                    setTypeError("");
                                }} autoFocus />
                            </div>
                            <button type="button" className="btn btn--primary btn--sm" onClick={handleCreateType} disabled={typeBusy}>
                                <span aria-hidden="true" className="material-symbols-outlined">{typeBusy ? "sync" : "check"}</span>
                                <span>{typeBusy ? "创建中..." : "确认新建"}</span>
                            </button>
                            <button type="button" className="btn btn--ghost btn--sm" onClick={handleCancelCreateType} disabled={typeBusy}>
                                <span>取消</span>
                            </button>
                        </div>
                    ) : null}
                    {typeError ? <p className="field-help field-help--error">{typeError}</p> : null}
                    <p className="field-help">{RULE_TARGET_TYPE_HELP}</p>
                </div>
                <div className="field-block field-block--wide">
                    <label className="field-label" htmlFor="field-14">关键词</label>
                    <textarea id="field-14" className="rule-textarea" placeholder="多个关键词用逗号或换行分隔" value={editor.keywordsText} onChange={(event) => onChange({ keywordsText: event.target.value })} />
                    <p className="field-help">命中任一关键词时使用这条内置规则；留空表示该规则只按票种兜底。</p>
                </div>
                <div className="field-block">
                    <label className="field-label" htmlFor="field-15">金额下限</label>
                    <div className="field-shell">
                        <input id="field-15" type="text" inputMode="decimal" className="field-input u-tabular" placeholder="不限" value={editor.amountMin} onChange={(event) => onChange({ amountMin: event.target.value })} />
                    </div>
                </div>
                <div className="field-block">
                    <label className="field-label" htmlFor="field-16">金额上限</label>
                    <div className="field-shell">
                        <input id="field-16" type="text" inputMode="decimal" className="field-input u-tabular" placeholder="不限" value={editor.amountMax} onChange={(event) => onChange({ amountMax: event.target.value })} />
                    </div>
                </div>
                <div className="field-block">
                    <label className="field-label" htmlFor="field-17">启用</label>
                    <label className="toggle-row">
                        <input id="field-17" type="checkbox" checked={editor.enabled !== false} onChange={(event) => onChange({ enabled: event.target.checked })} />
                        <span>{editor.enabled !== false ? "已启用" : "已停用"}</span>
                    </label>
                </div>
                <div className="field-block field-block--wide">
                    <label className="field-label">归档到</label>
                    <div className="rule-archive-summary">
                        <span aria-hidden="true" className="material-symbols-outlined">folder</span>
                        <span>{previewFolder ? `归档到：${previewFolder}` : "请选择目标票种，并填写关键词和金额范围"}</span>
                    </div>
                    <p className="field-help">文件夹由目标票种和金额范围自动生成，不需要手动填写；保存后生效。</p>
                </div>
            </div>
            {editor.error ? <NoticeBox tone="error">{editor.error}</NoticeBox> : null}
            <div className="footer-cluster">
                <button type="button" className="btn btn--primary btn--sm" onClick={onCommit}>
                    <span aria-hidden="true" className="material-symbols-outlined">check</span>
                    <span>保存覆盖</span>
                </button>
                <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel}>
                    <span aria-hidden="true" className="material-symbols-outlined">close</span>
                    <span>取消</span>
                </button>
            </div>
        </div>
    );
}

function RuleRestoreDialog({ dialog, mode, busy, error, issues, libraryAvailable, scopeLabel, dirty, onModeChange, onConfirm, onCancel }) {
    const cardRef = useRef(null);
    const titleId = "restore-dialog-title";
    const open = !!dialog;

    useEffect(() => {
        if (!open) return undefined;
        const previouslyFocused = document.activeElement;
        if (cardRef.current && cardRef.current.focus) cardRef.current.focus();
        return () => {
            if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
        };
    }, [open]);

    if (!dialog) return null;
    return (
        <div className="modal-overlay" onClick={onCancel}>
            <div className="modal-card restore-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={cardRef} onClick={(event) => event.stopPropagation()}>
                <div className="modal-head">
                    <div>
                        <p className="page-eyebrow">恢复默认</p>
                        <h2 id={titleId} className="sheet-title">{dialog.title}</h2>
                    </div>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel} aria-label="关闭">
                        <span aria-hidden="true" className="material-symbols-outlined">close</span>
                    </button>
                </div>
                <div className="modal-body">
                    <p className="field-help">将删除内置规则的自定义覆盖，恢复出厂默认；会先自动备份。</p>
                    {dirty ? <NoticeBox tone="warning">当前有未保存的修改，恢复默认后会重新加载规则并丢弃这些修改。</NoticeBox> : null}
                    <p className="field-label">恢复范围</p>
                    <div className="restore-options" role="radiogroup" aria-label="恢复范围">
                        <label className={joinClasses("restore-option", mode === "current" && "is-selected")}>
                            <input type="radio" name="restore-scope" checked={mode === "current"} onChange={() => onModeChange("current")} />
                            <span className="restore-option__copy">
                                <strong>仅当前作用范围</strong>
                                <span>{`只删除当前作用范围（${scopeLabel}）内的内置覆盖`}</span>
                            </span>
                        </label>
                        <label className={joinClasses("restore-option", mode === "all" && "is-selected", !libraryAvailable && "is-disabled")}>
                            <input type="radio" name="restore-scope" checked={mode === "all"} onChange={() => {
                                if (libraryAvailable) onModeChange("all");
                            }} disabled={!libraryAvailable} />
                            <span className="restore-option__copy">
                                <strong>全局 + 当前发票库</strong>
                                <span>{libraryAvailable ? "同时清理全局规则和当前发票库的内置覆盖" : "当前没有可用发票库，无法选择"}</span>
                            </span>
                        </label>
                    </div>
                    {error ? <NoticeBox tone="error">{error}</NoticeBox> : null}
                    {issues && issues.length > 0 ? <RuleIssues issues={issues} title="恢复未完成" /> : null}
                </div>
                <div className="modal-footer">
                    <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>取消</button>
                    <button type="button" className="btn btn--primary" onClick={onConfirm} disabled={busy}>
                        <span aria-hidden="true" className="material-symbols-outlined">{busy ? "sync" : "restart_alt"}</span>
                        <span>{busy ? "恢复中..." : "确认恢复"}</span>
                    </button>
                </div>
            </div>
        </div>
    );
}

function RuleTypesManager({ builtinTypes, customTypes, issues, busy, onDeleteType }) {
    return (
        <div className="rules-types-layout">
            <section className="surface-card">
                <SectionHeader icon="verified" title="内置票种" indicator={<StatusPill tone="neutral">{`${builtinTypes.length} 个 · 只读`}</StatusPill>} />
                <div className="card-stack card-stack--compact">
                    <p className="field-help">内置票种来自发票识别结果，不能删除或改名。</p>
                    {builtinTypes.length === 0 ? (
                        <p className="field-help">暂未获取到内置票种。</p>
                    ) : (
                        <div className="rules-type-list">
                            {builtinTypes.map((name) => <span key={name} className="rule-type-chip">{name}</span>)}
                        </div>
                    )}
                </div>
            </section>
            <section className="surface-card">
                <SectionHeader icon="category" title="自定义票种" indicator={<StatusPill tone="info">{`${customTypes.length} 个`}</StatusPill>} />
                <div className="card-stack card-stack--compact">
                    <p className="field-help">{RULE_CUSTOM_TYPE_HELP}</p>
                    <p className="field-help">自定义票种是规则的目标票种；在规则编辑器中点「新建票种」即可添加。</p>
                    {issues && issues.length > 0 ? <RuleIssues issues={issues} title="票种操作未完成" /> : null}
                    {customTypes.length === 0 ? (
                        <div className="rules-empty-state">
                            <span aria-hidden="true" className="material-symbols-outlined">category</span>
                            <p>还没有自定义票种，可在规则编辑器中新建。</p>
                        </div>
                    ) : (
                        <div className="rules-type-rows">
                            {customTypes.map((name) => (
                                <div className="rules-type-row" key={name}>
                                    <span className="rules-type-row__name u-truncate" title={name}>{name}</span>
                                    <StatusPill tone="neutral">自定义</StatusPill>
                                    <button
                                        type="button"
                                        className="rule-icon-button rule-icon-button--danger"
                                        title="删除票种"
                                        aria-label={`删除票种 ${name}`}
                                        disabled={busy}
                                        onClick={() => onDeleteType(name)}
                                    >
                                        <span aria-hidden="true" className="material-symbols-outlined">delete</span>
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </section>
        </div>
    );
}

function AnalysisPage({ theme, onToggleTheme, onOpenDisclaimer }) {
    const navigate = useNavigate();
    const [summary, setSummary] = useState({});
    const [successInvoices, setSuccessInvoices] = useState([]);
    const [groupedErrors, setGroupedErrors] = useState([]);
    const [manualCheckPath, setManualCheckPath] = useState("");
    const [outputPath, setOutputPath] = useState("");
    const [resultBreakdown, setResultBreakdown] = useState({});
    const [quotaMessage, setQuotaMessage] = useState("");
    const [quotaExhausted, setQuotaExhausted] = useState(false);
    const [lastExportPath, setLastExportPath] = useState("");
    const [loadingError, setLoadingError] = useState("");
    const [exporting, setExporting] = useState(false);
    const [resultTaskMode, setResultTaskMode] = useState("mail");
    const [organizeSummary, setOrganizeSummary] = useState({});
    const [fetchSummary, setFetchSummary] = useState({});
    const successCursorRef = useRef(0);
    const errorCursorRef = useRef(0);
    const resultRunIdRef = useRef("");

    useEffect(() => {
        let active = true;
        let timer = null;
        const loadResults = async () => {
            try {
                const [results, settingsRes] = await Promise.all([
                    callApi("get_results_delta", successCursorRef.current, errorCursorRef.current),
                    callApi("load_user_settings").catch(() => null),
                ]);
                if (!active || !results) return;
                const runId = String(results.run_id || "");
                if (results.reset || runId !== resultRunIdRef.current) {
                    resultRunIdRef.current = runId;
                    successCursorRef.current = 0;
                    errorCursorRef.current = 0;
                    setSuccessInvoices([]);
                }
                const incoming = normalizeSuccessInvoices(
                    results.successInvoices || [],
                    successCursorRef.current
                );
                if (incoming.length) {
                    setSuccessInvoices((previous) => previous.concat(incoming));
                }
                successCursorRef.current = Number((results.cursor && results.cursor.success) || 0);
                errorCursorRef.current = Number((results.cursor && results.cursor.error) || 0);
                setSummary(results.summary || {});
                setGroupedErrors(normalizeGroupedErrors(results.groupedErrorInvoices || []));
                setManualCheckPath(results.manual_check_path || "");
                setResultBreakdown(results.resultBreakdown || (results.summary && results.summary.result_breakdown) || {});
                setQuotaExhausted(!!results.quota_exhausted);
                setQuotaMessage(results.quota_message || "");
                setLastExportPath(results.last_export_path || "");
                setResultTaskMode(normalizeTaskMode(results.task_mode));
                setOrganizeSummary(results.organize_summary || {});
                setFetchSummary(results.fetch_summary || {});
                const baseOutput = results.output_path || parentFolder(results.manual_check_path || "") || (settingsRes && settingsRes.settings ? settingsRes.settings.save_path || "" : "");
                setOutputPath(baseOutput);
                setLoadingError("");
            } catch (error) {
                if (active) setLoadingError(error.message || "结果加载失败。");
            }
        };
        loadResults();
        timer = setInterval(loadResults, 3000);
        return () => {
            active = false;
            if (timer) clearInterval(timer);
        };
    }, []);

    const totalErrors = useMemo(() => groupedErrors.reduce((acc, group) => acc + (group.count || group.items.length || 0), 0), [groupedErrors]);
    const successCount = Number(summary.success_count || successInvoices.length);
    const manualReviewGroup = groupedErrors.find((group) => group.key === "manual_review");
    const manualCheckCount = Number(summary.manual_check_count || resultBreakdown.manual_review || (manualReviewGroup && manualReviewGroup.count) || 0);
    const retentionCount = Number(summary.retention_count || resultBreakdown.retained_record || 0);
    const processingErrorCount = Number(summary.processing_error_count || resultBreakdown.processing_error || 0);
    const pendingCount = manualCheckCount + retentionCount + processingErrorCount || Number(summary.error_count || totalErrors || 0);
    const totalResultCount = successCount + pendingCount;
    const statusText = buildResultStatusText(successCount, manualCheckCount, retentionCount, processingErrorCount);
    const groupedVisible = groupedErrors.filter((group) => Number(group.count || group.items.length || 0) > 0);
    const classificationBreakdown = (summary && summary.classification_breakdown) || (organizeSummary && organizeSummary.classification_counts) || {};
    const classificationSources = (summary && summary.classification_source_breakdown) || (organizeSummary && organizeSummary.classification_source_counts) || {};
    const unclassifiedCount = Number(
        (summary && summary.unclassified_count)
        || (organizeSummary && organizeSummary.unclassified_count)
        || 0
    );
    const classificationEntries = Object.keys(classificationBreakdown)
        .map((name) => ({ name: String(name || ""), count: Number(classificationBreakdown[name] || 0) }))
        .filter((item) => item.name && item.count > 0)
        .sort((left, right) => right.count - left.count);
    const classificationSourceEntries = Object.keys(classificationSources)
        .map((source) => ({ source: String(source || ""), count: Number(classificationSources[source] || 0) }))
        .filter((item) => item.source && item.count > 0)
        .sort((left, right) => right.count - left.count);
    const isFetchResult = resultTaskMode === "fetch";
    const isLocalResult = resultTaskMode === "local";
    const localInPlace = isLocalResult && !!organizeSummary.in_place;
    const localSplitByCategory = organizeSummary.split_by_category !== false;
    const resultHeadline = isFetchResult
        ? "本次提取完成"
        : isLocalResult
            ? "本次整理完成"
            : UI_COPY.pages.analysis.resultTitle;
    const fetchAttachments = Number(fetchSummary.attachments || 0);
    const fetchTodoCount = Number(fetchSummary.todos || 0);
    const fetchInboxDir = fetchSummary.inbox_dir || "";
    const fetchManifestPath = fetchSummary.manifest_path || "";
    const bannerCopy = isFetchResult
        ? APP_VISIBLE_COPY.resultBanners.fetch
        : isLocalResult
            ? (localInPlace
                ? (localSplitByCategory ? APP_VISIBLE_COPY.resultBanners.localApply : APP_VISIBLE_COPY.resultBanners.localApplyFlat)
                : (localSplitByCategory ? APP_VISIBLE_COPY.resultBanners.localApplyCustom : APP_VISIBLE_COPY.resultBanners.localApplyCustomFlat))
            : null;
    const completionBanner = bannerCopy
        ? {
            eyebrow: bannerCopy.eyebrow,
            title: bannerCopy.title,
            text: bannerCopy.text,
            icon: isFetchResult ? "inbox" : "task_alt",
            pathText: isFetchResult ? (fetchManifestPath || fetchInboxDir || outputPath) : outputPath,
            openPath: isFetchResult ? (fetchInboxDir || outputPath) : outputPath,
            buttonLabel: isFetchResult ? "打开 inbox 文件夹" : "打开输出目录",
        }
        : null;
    const outputBanner = {
        icon: "folder",
        eyebrow: isLocalResult && localInPlace ? "发票文件夹" : "输出目录",
        title: outputPath
            ? (isFetchResult ? "提取结果已写入输出目录" : localInPlace ? "归档结果已写入发票文件夹" : isLocalResult ? "归档结果已写入输出目录" : "归档结果与暂存记录已写入输出目录")
            : "当前还没有可打开的输出目录",
        text: outputPath
            ? (isFetchResult ? "inbox 文件夹与 manifest.jsonl 位于该目录下，可从这里继续查看。" : localInPlace ? (localSplitByCategory ? "分类文件、「整理前发票」中的原件、重复件与导出明细都可以从这里继续查看。" : "整理后的文件、「整理前发票」中的原件、重复件与导出明细都可以从这里继续查看。") : isLocalResult ? "归档副本与导出明细已写入该目录；原始文件保留在发票文件夹。" : "成功归档文件、暂存记录和导出结果都可以从这里继续查看。")
            : "待本轮生成结果后，可从这里直接打开输出目录。",
        pathText: outputPath || "",
        buttonLabel: "打开输出目录",
        openPath: outputPath || parentFolder(manualCheckPath),
    };

    async function handleOpenPath(target) {
        if (!target) return;
        await callApi("open_folder", target);
    }

    async function handleOpenManualCheck() {
        await callApi("open_manual_check_folder");
    }

    async function openExportedSummary(path) {
        if (!path) throw new Error("结果明细已导出，但未返回文件路径。");
        const openResult = await callApi("view_invoice", path);
        if (!openResult || !openResult.success) throw new Error((openResult && openResult.message) || "结果明细已导出，但打开文件失败。");
    }

    async function handleExport() {
        setExporting(true);
        try {
            const result = await callApi("export_run_summary", outputPath || "");
            if (result && result.success) {
                const exportedPath = result.path || "";
                setLastExportPath(exportedPath);
                await openExportedSummary(exportedPath);
            } else {
                window.alert((result && result.message) || "导出失败。");
            }
        } catch (error) {
            window.alert(error.message || "导出失败。");
        } finally {
            setExporting(false);
        }
    }

    const summaryCards = isFetchResult
        ? [
            { key: "attachments", icon: "attach_file", label: "已提取附件", value: fetchAttachments, helper: fetchAttachments > 0 ? "附件已保存到 inbox 文件夹。" : "本轮未提取到附件。", tone: "success" },
            { key: "todos", icon: "pending_actions", label: "待处理事项", value: fetchTodoCount, helper: fetchTodoCount > 0 ? "提取过程中有记录需要后续处理。" : "本轮提取没有待处理事项。", tone: fetchTodoCount > 0 ? "warning" : "info" },
        ]
        : [
            { key: "success", icon: "task_alt", label: "处理成功", value: successCount, helper: successCount > 0 ? (isLocalResult ? (localInPlace ? "归档文件已写入发票文件夹。" : "归档副本已写入输出目录。") : "归档文件已写入输出目录。") : "当前还没有成功记录。", tone: "success" },
            { key: "retention", icon: "inventory_2", label: "暂存记录", value: retentionCount, helper: retentionCount > 0 ? "已保留但未成功归档，可按需导出查看。" : "当前没有暂存记录。", tone: "info" },
            { key: "manual", icon: "folder_open", label: "待人工复核", value: manualCheckCount, helper: manualCheckCount > 0 ? "这是当前需要优先处理的内容。" : "当前没有待人工复核项。", tone: manualCheckCount > 0 ? "warning" : "info" },
        ];

    return (
        <AppShell
            active="results"
            theme={theme}
            onToggleTheme={onToggleTheme}
            onOpenDisclaimer={onOpenDisclaimer}
            footerLeft={<button type="button" className="btn btn--ghost" onClick={() => navigate("/")}><span aria-hidden="true" className="material-symbols-outlined">add_circle</span><span>开始新批次</span></button>}
            footerRight={lastExportPath ? <p className="footer-meta">最近导出: {fileNameFromPath(lastExportPath)}</p> : null}
        >
            <div className="page-wrap page-wrap--analysis">
                <PageHeader title={UI_COPY.pages.analysis.title} />

                {completionBanner ? (
                    <ResultActionBanner
                        tone="neutral"
                        icon={completionBanner.icon}
                        eyebrow={completionBanner.eyebrow}
                        title={completionBanner.title}
                        text={completionBanner.text}
                        pathText={completionBanner.pathText || ""}
                        buttonLabel={completionBanner.buttonLabel}
                        onClick={() => handleOpenPath(completionBanner.openPath)}
                        disabled={!completionBanner.openPath}
                    />
                ) : null}

                <section className="surface-card surface-card--hero">
                    <div className="hero-body">
                        <div className="hero-head">
                            <div>
                                <p className="progress-kicker">{UI_COPY.pages.analysis.statusSummary}</p>
                                <h2 className="result-headline">{resultHeadline}</h2>
                                {isFetchResult ? (
                                    <p className="result-meta">本轮共提取 <strong className="u-tabular">{fetchAttachments}</strong> 个附件，清单已写入 inbox 文件夹。</p>
                                ) : (
                                    <p className="result-meta">共整理 <strong className="u-tabular">{totalResultCount}</strong> 条结果记录。{statusText}</p>
                                )}
                            </div>
                            <div className="footer-cluster">
                                <ResultToolbarButton icon={exporting ? "sync" : "download"} label={exporting ? "导出中..." : "导出结果明细"} onClick={handleExport} disabled={exporting} primary />
                            </div>
                        </div>
                        <div className="cards-grid">{summaryCards.map((card) => <ResultSummaryCard key={card.key} {...card} />)}</div>
                        {classificationEntries.length > 0 || classificationSourceEntries.length > 0 ? (
                            <div className="classification-summary">
                                <div className="classification-summary__head">
                                    <span aria-hidden="true" className="material-symbols-outlined">category</span>
                                    <span>{UI_COPY.pages.analysis.classificationTitle}</span>
                                </div>
                                {classificationEntries.length > 0 ? (
                                    <div className="group-strip group-strip--inline">
                                        {classificationEntries.slice(0, 12).map((item) => (
                                            <span key={item.name} className="group-chip">
                                                <span>{item.name}</span>
                                                <span className="u-tabular">{item.count}</span>
                                            </span>
                                        ))}
                                        {classificationEntries.length > 12 ? (
                                            <span className="group-chip group-chip--info">其他 {classificationEntries.length - 12} 类</span>
                                        ) : null}
                                    </div>
                                ) : null}
                                {classificationSourceEntries.length > 0 ? (
                                    <p className="field-help">
                                        归类来源：{classificationSourceEntries.map((item) => `${classificationSourceLabel(item.source)} ${item.count}`).join(" · ")}
                                    </p>
                                ) : null}
                            </div>
                        ) : null}
                        {quotaExhausted && quotaMessage ? <NoticeBox tone="warning">{quotaMessage}</NoticeBox> : null}
                        {processingErrorCount > 0 ? <NoticeBox tone="warning">检测到 {processingErrorCount} 条真实异常，请通过“导出结果明细”继续排查。</NoticeBox> : null}
                    </div>
                </section>

                {loadingError ? <NoticeBox tone="error">{loadingError}</NoticeBox> : null}
                {unclassifiedCount > 0 ? (
                    <ResultActionBanner
                        icon="rule"
                        eyebrow="归类提示"
                        title={`检测到 ${unclassifiedCount} 张发票未归类`}
                        text="这些发票没有命中任何已启用类目，整理后会进入待人工复核。补充归类规则后重新整理即可自动归档。"
                        buttonLabel="管理归类规则"
                        onClick={() => navigate("/settings", { state: { settingsSection: "rules" } })}
                    />
                ) : null}
                {manualCheckCount > 0 ? (
                    <ResultActionBanner
                        icon="folder_open"
                        eyebrow={UI_COPY.pages.analysis.reviewTitle}
                        title={`检测到 ${manualCheckCount} 条待人工复核记录`}
                        text={UI_COPY.pages.analysis.reviewReady}
                        chips={groupedVisible.length > 0 ? <div className="group-strip group-strip--inline">{groupedVisible.map((group) => <span key={group.key} className={joinClasses("group-chip", resolveGroupTone(group.key))}><span>{group.label}</span><span className="u-tabular">{Number(group.count || group.items.length || 0)}</span></span>)}</div> : null}
                        buttonLabel="打开待人工复核"
                        onClick={handleOpenManualCheck}
                        disabled={!manualCheckCount}
                    />
                ) : null}
                <ResultActionBanner
                    tone="neutral"
                    icon={outputBanner.icon}
                    eyebrow={outputBanner.eyebrow}
                    title={outputBanner.title}
                    text={outputBanner.text}
                    pathText={outputBanner.pathText}
                    buttonLabel={outputBanner.buttonLabel}
                    onClick={() => handleOpenPath(outputBanner.openPath)}
                    disabled={!outputBanner.openPath}
                />
            </div>
        </AppShell>
    );
}

function RulesWorkspace({ prepare }) {
    const [rulesData, setRulesData] = useState(null);
    const [libraryDir, setLibraryDir] = useState("");
    const [scope, setScope] = useState("global");
    const [scopeDrafts, setScopeDrafts] = useState({
        global: buildUserRuleDraft(null, "global", []),
        library: buildUserRuleDraft(null, "library", []),
    });
    const [dirtyScopes, setDirtyScopes] = useState({ global: false, library: false });
    const [activePanel, setActivePanel] = useState("rules");
    const [typesState, setTypesState] = useState({ documentTypes: [], customTypes: [], builtinTypes: [] });
    const [typeIssues, setTypeIssues] = useState([]);
    const [editor, setEditor] = useState(null);
    const [builtinEditor, setBuiltinEditor] = useState(null);
    const [restoreDialog, setRestoreDialog] = useState(null);
    const [restoreMode, setRestoreMode] = useState("current");
    const [restoreBusy, setRestoreBusy] = useState(false);
    const [restoreError, setRestoreError] = useState("");
    const [restoreIssues, setRestoreIssues] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState("");
    const [saving, setSaving] = useState(false);
    const [busyAction, setBusyAction] = useState("");
    const [actionState, setActionState] = useState({ tone: "info", message: "" });
    const [saveIssues, setSaveIssues] = useState([]);
    const [testFields, setTestFields] = useState({ seller: "", seller_tin: "", item: "", type: "", amount: "" });
    const [testState, setTestState] = useState({ status: "idle", result: null, issues: [], message: "" });

    const builtinCategoryIds = useMemo(
        () => (rulesData && Array.isArray(rulesData.builtin_category_ids)
            ? rulesData.builtin_category_ids.map((item) => String(item))
            : []),
        [rulesData]
    );
    const builtinIdSet = useMemo(() => new Set(builtinCategoryIds), [builtinCategoryIds]);
    const documentTypes = typesState.documentTypes;
    const builtinTypes = typesState.builtinTypes;
    const draft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const dirty = !!dirtyScopes[scope];
    const libraryAvailable = !!(rulesData && rulesData.library_available);
    const effectiveCategories = rulesData && Array.isArray(rulesData.effective_categories) ? rulesData.effective_categories : [];
    const ruleRows = useMemo(() => draft.categories.map((entry, index) => Object.assign({}, entry, {
        index,
        previewFolder: ruleEntryPreviewFolder(entry),
    })), [draft]);
    const missingTargetCount = useMemo(
        () => draft.categories.filter((entry) => !String((entry && entry.target_type) || "").trim()).length,
        [draft]
    );
    const missingBuiltinTargetCount = useMemo(
        () => (draft.builtinOverrides || []).filter((entry) => !String((entry && entry.target_type) || "").trim()).length,
        [draft]
    );
    const persistedOverrideScopes = useMemo(() => {
        const map = {};
        ["global", "library"].forEach((scopeName) => {
            const scopeData = rulesData && rulesData[scopeName];
            const categories = scopeData && Array.isArray(scopeData.categories) ? scopeData.categories : [];
            categories.forEach((item) => {
                const id = String((item && item.id) || "");
                if (!id || !builtinIdSet.has(id)) return;
                if (!map[id]) map[id] = [];
                if (map[id].indexOf(scopeName) < 0) map[id].push(scopeName);
            });
        });
        return map;
    }, [rulesData, builtinIdSet]);
    const builtinRows = useMemo(() => {
        const draftById = new Map();
        (draft.builtinOverrides || []).forEach((entry) => {
            if (entry.id) draftById.set(String(entry.id), entry);
        });
        const rows = [];
        const seen = new Set();
        effectiveCategories.forEach((item) => {
            const id = String((item && item.id) || "");
            if (!id || !builtinIdSet.has(id) || seen.has(id)) return;
            seen.add(id);
            const override = draftById.get(id);
            const persistedScopes = persistedOverrideScopes[id] || [];
            const base = override || {
                id,
                target_type: String(item.target_type || ""),
                keywords: (Array.isArray(item.keywords) ? item.keywords : []).map((value) => String(value)),
                amount_range: normalizeRuleAmountRange(item.amount_range),
                enabled: item.enabled !== false,
            };
            const candidateTarget = String(
                (override && override.target_type) || (item.target_type || item.archive_folder || "")
            ).trim();
            const targetType = isValidRuleTargetType(candidateTarget, documentTypes) ? candidateTarget : "";
            const amountRange = override ? override.amount_range : normalizeRuleAmountRange(item.amount_range);
            rows.push({
                id,
                defaultLabel: String(item.name || item.archive_folder || id),
                target_type: targetType,
                keywords: base.keywords || [],
                amount_range: amountRange,
                enabled: override ? override.enabled : item.enabled !== false,
                previewFolder: buildRuleFolderName(targetType, amountRange),
                modified: !!override || persistedScopes.length > 0,
                overrideScopes: persistedScopes,
            });
        });
        (draft.builtinOverrides || []).forEach((entry) => {
            const id = String(entry.id || "");
            if (!id || seen.has(id)) return;
            seen.add(id);
            const targetType = isValidRuleTargetType(entry.target_type, documentTypes) ? entry.target_type : "";
            rows.push({
                id,
                defaultLabel: targetType || id,
                target_type: targetType,
                keywords: entry.keywords || [],
                amount_range: entry.amount_range || [],
                enabled: entry.enabled !== false,
                previewFolder: buildRuleFolderName(targetType, entry.amount_range),
                modified: true,
                overrideScopes: persistedOverrideScopes[id] || [],
            });
        });
        return rows;
    }, [effectiveCategories, draft, builtinIdSet, persistedOverrideScopes, documentTypes]);
    const categoryNameById = useMemo(() => {
        const entries = effectiveCategories.map((item) => ({ id: item.id, name: item.name || item.archive_folder }));
        ruleRows.forEach((row) => entries.push({ id: row.id, name: row.previewFolder || row.name }));
        builtinRows.forEach((row) => entries.push({ id: row.id, name: row.previewFolder || row.target_type || row.id }));
        return buildRuleCategoryNameMap(entries);
    }, [effectiveCategories, ruleRows, builtinRows]);
    const targetTypeById = useMemo(() => {
        const map = {};
        effectiveCategories.forEach((item) => {
            const id = String((item && item.id) || "");
            if (id) map[id] = String(item.target_type || "");
        });
        ruleRows.forEach((row) => {
            const id = String(row.id || "");
            if (id) map[id] = String(row.target_type || "");
        });
        builtinRows.forEach((row) => {
            const id = String(row.id || "");
            if (id) map[id] = String(row.target_type || "");
        });
        return map;
    }, [effectiveCategories, ruleRows, builtinRows]);
    const loadIssues = useMemo(() => normalizeRuleIssues(rulesData && rulesData.issues), [rulesData]);
    const loadWarnings = (rulesData && Array.isArray(rulesData.warnings) ? rulesData.warnings : [])
        .map((item) => String((item && (item.text || item.message)) || "").trim())
        .filter(Boolean);
    const unclassifiedInvoices = rulesData && Array.isArray(rulesData.unclassified_invoices) ? rulesData.unclassified_invoices : [];
    const scopeRulesDir = scope === "library"
        ? (rulesData && rulesData.library_rules_dir) || ""
        : (rulesData && rulesData.global_rules_dir) || "";
    const directoryText = safeText(scopeRulesDir, "尚未创建");


    useEffect(() => {
        let active = true;
        (async () => {
            try {
                if (prepare) await prepare();
                const data = await callApi("load_classification_rules", "");
                if (!active) return;
                applyRulesData(data);
            } catch (error) {
                if (active) setLoadError(error.message || "归类规则加载失败，请稍后重试。");
            } finally {
                if (active) setLoading(false);
            }
        })();
        return () => {
            active = false;
        };
    }, []);

    useEffect(() => {
        if (scope === "library" && rulesData && !rulesData.library_available) setScope("global");
    }, [scope, rulesData]);

    function applyRulesData(data) {
        const payload = data || {};
        const customTypes = Array.isArray(payload.custom_types) ? payload.custom_types.map((item) => String(item)) : [];
        const documentTypes = Array.isArray(payload.document_types) ? payload.document_types.map((item) => String(item)) : [];
        const builtinTypes = Array.isArray(payload.builtin_types)
            ? payload.builtin_types.map((item) => String(item))
            : documentTypes.filter((item) => customTypes.indexOf(item) < 0);
        const loadedBuiltinIds = Array.isArray(payload.builtin_category_ids)
            ? payload.builtin_category_ids.map((item) => String(item))
            : [];
        setTypesState({ documentTypes, customTypes, builtinTypes });
        setTypeIssues([]);
        setRulesData(payload);
        setLibraryDir(String(payload.library_dir || ""));
        setScopeDrafts({
            global: buildUserRuleDraft(payload.global, "global", loadedBuiltinIds, documentTypes),
            library: buildUserRuleDraft(payload.library, "library", loadedBuiltinIds, documentTypes),
        });
        setDirtyScopes({ global: false, library: false });
        setEditor(null);
        setBuiltinEditor(null);
        setRestoreDialog(null);
        setRestoreError("");
        setRestoreIssues([]);
        setSaveIssues([]);
        setLoadError(payload.success === false ? (payload.message || "归类规则配置有误，请按提示修正。") : "");
    }

    function applyTypeSnapshot(result, fallbackName, options) {
        const remove = !!(options && options.remove);
        const snapshot = result || {};
        setTypesState((current) => {
            let documentTypes = Array.isArray(snapshot.document_types)
                ? snapshot.document_types.map((item) => String(item))
                : current.documentTypes;
            let customTypes = Array.isArray(snapshot.custom_types)
                ? snapshot.custom_types.map((item) => String(item))
                : current.customTypes;
            const builtinTypes = Array.isArray(snapshot.builtin_types)
                ? snapshot.builtin_types.map((item) => String(item))
                : current.builtinTypes;
            if (fallbackName && !Array.isArray(snapshot.document_types)) {
                if (remove) {
                    documentTypes = documentTypes.filter((item) => item !== fallbackName);
                    customTypes = customTypes.filter((item) => item !== fallbackName);
                } else {
                    if (documentTypes.indexOf(fallbackName) < 0) documentTypes = documentTypes.concat([fallbackName]);
                    if (customTypes.indexOf(fallbackName) < 0) customTypes = customTypes.concat([fallbackName]);
                }
            }
            return { documentTypes, customTypes, builtinTypes };
        });
    }

    async function reloadRules(options) {
        const silent = !!(options && options.silent);
        if (!silent) setBusyAction("reload");
        setLoadError("");
        try {
            const data = await callApi("load_classification_rules", libraryDir);
            applyRulesData(data);
            if (!silent) setActionState({ tone: "info", message: "" });
        } catch (error) {
            setLoadError(error.message || "归类规则加载失败，请稍后重试。");
        } finally {
            setBusyAction("");
        }
    }

    function commitDraft(nextDraft, message, tone) {
        setScopeDrafts((current) => Object.assign({}, current, { [scope]: nextDraft }));
        setDirtyScopes((current) => Object.assign({}, current, { [scope]: true }));
        setSaveIssues([]);
        setActionState(message ? { tone: tone || "success", message } : { tone: "info", message: "" });
        setTestState((current) => (current.status === "idle" ? current : { status: "idle", result: null, issues: [], message: "" }));
    }

    function handleScopeChange(nextScope) {
        if (nextScope === "library" && !libraryAvailable) return;
        setScope(nextScope);
        setEditor(null);
        setBuiltinEditor(null);
        setSaveIssues([]);
        setActionState({ tone: "info", message: "" });
        setTestState({ status: "idle", result: null, issues: [], message: "" });
    }

    function handlePanelChange(nextPanel) {
        setActivePanel(nextPanel);
        setEditor(null);
        setBuiltinEditor(null);
        setActionState({ tone: "info", message: "" });
        setTypeIssues([]);
    }

    function handleAddRule() {
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const form = emptyUserRuleEditor();
        form.id = nextRuleCategoryId(currentDraft.categories.concat(effectiveCategories));
        setEditor(form);
        setSaveIssues([]);
        setActionState({ tone: "info", message: "" });
    }

    function handleEditRule(index) {
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const entry = currentDraft.categories[index];
        if (!entry) return;
        setEditor(userRuleEditorFromEntry(entry));
        setSaveIssues([]);
        setActionState({ tone: "info", message: "" });
    }

    function handleDeleteRule(index) {
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const entry = currentDraft.categories[index];
        if (!entry) return;
        const categories = currentDraft.categories.filter((item, itemIndex) => itemIndex !== index);
        if (editor && String(editor.originalId) === String(entry.id)) setEditor(null);
        commitDraft(
            Object.assign({}, currentDraft, { categories }),
            `已删除规则「${ruleEntryPreviewFolder(entry) || entry.mainKeyword || "未命名规则"}」，保存后生效。`,
            "info"
        );
    }

    function handleMoveRule(index, direction) {
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const categories = currentDraft.categories.slice();
        const targetIndex = index + direction;
        if (index < 0 || targetIndex < 0 || targetIndex >= categories.length) return;
        const moving = categories[index];
        categories[index] = categories[targetIndex];
        categories[targetIndex] = moving;
        commitDraft(Object.assign({}, currentDraft, { categories }), "已调整规则顺序，保存后生效。", "info");
    }

    function handleToggleRule(index) {
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const categories = currentDraft.categories.slice();
        const current = categories[index];
        if (!current) return;
        categories[index] = Object.assign({}, current, { enabled: current.enabled === false });
        const nextEnabled = categories[index].enabled !== false;
        commitDraft(
            Object.assign({}, currentDraft, { categories }),
            nextEnabled ? "已启用该规则，保存后生效。" : "已停用该规则，保存后生效。",
            "info"
        );
    }

    function handleEditorChange(patch) {
        setEditor((current) => (current ? Object.assign({}, current, patch, { error: "" }) : current));
    }

    function handleEditorCommit() {
        if (!editor) return;
        const targetType = String(editor.targetType || "").trim();
        const keyword = String(editor.keyword || "").trim();
        const amountMin = parseRuleAmount(editor.amountMin);
        const amountMax = parseRuleAmount(editor.amountMax);
        const errors = [];
        if (!targetType) {
            errors.push("请选择目标票种。");
        } else if (documentTypes.length > 0 && documentTypes.indexOf(targetType) < 0) {
            errors.push("目标票种已失效，请重新选择。");
        }
        if (!keyword) errors.push("请填写关键词。");
        if (String(editor.amountMin || "").trim() && amountMin === null) errors.push("金额下限必须是数字。");
        if (String(editor.amountMax || "").trim() && amountMax === null) errors.push("金额上限必须是数字。");
        if (amountMin !== null && amountMax !== null && amountMin > amountMax) errors.push("金额下限不能大于金额上限。");
        if (errors.length > 0) {
            setEditor(Object.assign({}, editor, { error: errors[0] }));
            return;
        }
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const id = editor.mode === "edit"
            ? editor.originalId
            : (editor.id || nextRuleCategoryId(currentDraft.categories.concat(effectiveCategories)));
        const extraKeywords = (Array.isArray(editor.legacyExtraKeywords) ? editor.legacyExtraKeywords : [])
            .map((item) => String(item).trim())
            .filter((item) => item && item !== keyword);
        const amountRange = buildRuleAmountRange(editor.amountMin, editor.amountMax);
        const entry = {
            id: String(id || "").trim(),
            name: editor.name || buildRuleFolderName(targetType, amountRange) || keyword,
            target_type: targetType,
            keywords: [keyword].concat(extraKeywords),
            mainKeyword: keyword,
            legacyExtraKeywords: extraKeywords,
            amount_range: amountRange,
            enabled: editor.enabled !== false,
            match: editor.legacyMatch || "",
            exclude_keywords: (Array.isArray(editor.legacyExcludeKeywords) ? editor.legacyExcludeKeywords : []).slice(),
        };
        let categories = currentDraft.categories.slice();
        if (editor.mode === "edit") {
            const index = categories.findIndex((item) => String(item.id) === String(editor.originalId));
            if (index >= 0) categories[index] = entry;
            else categories.push(entry);
        } else {
            categories.push(entry);
        }
        commitDraft(
            Object.assign({}, currentDraft, { categories }),
            editor.mode === "new" ? "已添加规则，保存后生效。" : "已更新规则，保存后生效。",
            "success"
        );
        setEditor(null);
    }

    function upsertBuiltinOverride(entry, message) {
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const overrides = (currentDraft.builtinOverrides || []).slice();
        const index = overrides.findIndex((item) => String(item.id) === String(entry.id));
        if (index >= 0) overrides[index] = entry;
        else overrides.push(entry);
        commitDraft(Object.assign({}, currentDraft, { builtinOverrides: overrides }), message, "info");
    }

    function handleEditBuiltinRule(row) {
        if (!row) return;
        const range = normalizeRuleAmountRange(row.amount_range);
        setBuiltinEditor({
            id: String(row.id || ""),
            label: String(row.defaultLabel || row.target_type || row.id || ""),
            error: "",
            targetType: String(row.target_type || ""),
            keywordsText: (Array.isArray(row.keywords) ? row.keywords : []).join("，"),
            amountMin: range.length > 0 ? ruleAmountInputValue(range[0]) : "",
            amountMax: range.length > 1 ? ruleAmountInputValue(range[1]) : "",
            enabled: row.enabled !== false,
        });
        setActionState({ tone: "info", message: "" });
    }

    function handleBuiltinEditorChange(patch) {
        setBuiltinEditor((current) => (current ? Object.assign({}, current, patch, { error: "" }) : current));
    }

    function handleBuiltinEditorCommit() {
        if (!builtinEditor) return;
        const targetType = String(builtinEditor.targetType || "").trim();
        const amountMin = parseRuleAmount(builtinEditor.amountMin);
        const amountMax = parseRuleAmount(builtinEditor.amountMax);
        const errors = [];
        if (!targetType) {
            errors.push("请选择目标票种。");
        } else if (documentTypes.length > 0 && documentTypes.indexOf(targetType) < 0) {
            errors.push("目标票种已失效，请重新选择。");
        }
        if (String(builtinEditor.amountMin || "").trim() && amountMin === null) errors.push("金额下限必须是数字。");
        if (String(builtinEditor.amountMax || "").trim() && amountMax === null) errors.push("金额上限必须是数字。");
        if (amountMin !== null && amountMax !== null && amountMin > amountMax) errors.push("金额下限不能大于金额上限。");
        if (errors.length > 0) {
            setBuiltinEditor(Object.assign({}, builtinEditor, { error: errors[0] }));
            return;
        }
        upsertBuiltinOverride({
            id: builtinEditor.id,
            target_type: targetType,
            keywords: splitRuleKeywords(builtinEditor.keywordsText),
            amount_range: buildRuleAmountRange(builtinEditor.amountMin, builtinEditor.amountMax),
            enabled: builtinEditor.enabled !== false,
        }, "已更新内置规则覆盖，保存后生效。");
        setBuiltinEditor(null);
    }

    function handleToggleBuiltinRule(row) {
        if (!row) return;
        const entry = normalizeBuiltinOverride(row, documentTypes);
        entry.enabled = row.enabled === false;
        upsertBuiltinOverride(entry, entry.enabled ? "已启用内置规则，保存后生效。" : "已停用内置规则，保存后生效。");
    }

    function openRestoreDialog(categoryId, title) {
        let defaultMode = "current";
        if (categoryId) {
            const persistedScopes = persistedOverrideScopes[categoryId] || [];
            if (persistedScopes.length > 0 && persistedScopes.indexOf(scope) < 0 && libraryAvailable) {
                defaultMode = "all";
            }
        }
        setRestoreDialog({ categoryId: String(categoryId || ""), title });
        setRestoreMode(defaultMode);
        setRestoreError("");
        setRestoreIssues([]);
    }

    function handleRestoreBuiltinRule(row) {
        if (!row) return;
        openRestoreDialog(row.id, `恢复「${row.defaultLabel || row.previewFolder || row.id}」的默认设置`);
    }

    function handleRestoreAllBuiltin() {
        openRestoreDialog("", "恢复全部内置默认规则");
    }

    async function handleConfirmRestoreBuiltin() {
        if (!restoreDialog || restoreBusy) return;
        setRestoreBusy(true);
        setRestoreError("");
        setRestoreIssues([]);
        try {
            // scope stays the current editing scope; scope_mode expands it to
            // global + current library for the "全部" option.
            const result = await callApi("reset_builtin_classification_rules", {
                scope,
                library_dir: libraryDir,
                scope_mode: restoreMode,
                category_id: restoreDialog.categoryId || "",
            });
            if (!result || result.success !== true) {
                setRestoreError((result && result.message) || "恢复默认失败，请稍后重试。");
                setRestoreIssues(normalizeRuleIssues(result && result.issues));
                return;
            }
            setRestoreDialog(null);
            setActionState({ tone: "success", message: result.message || "已恢复内置规则默认设置。" });
            await reloadRules({ silent: true });
        } catch (error) {
            setRestoreError(error.message || "恢复默认失败，请稍后重试。");
        } finally {
            setRestoreBusy(false);
        }
    }

    async function handleCreateType(name) {
        try {
            const result = await callApi("create_classification_type", { name });
            if (!result || result.success !== true) {
                applyTypeSnapshot(result, name);
                return {
                    success: false,
                    message: (result && result.message) || "新建票种失败，请稍后重试。",
                    issues: normalizeRuleIssues(result && result.issues),
                };
            }
            applyTypeSnapshot(result, name);
            const createdName = String(name || "").trim();
            setTypeIssues([]);
            setActionState({ tone: "success", message: (result && result.message) || `已新建票种「${createdName}」。` });
            return { success: true, name: createdName, message: (result && result.message) || "" };
        } catch (error) {
            return { success: false, message: error.message || "新建票种失败，请稍后重试。", issues: [] };
        }
    }

    async function handleDeleteType(name) {
        if (busyAction) return;
        setBusyAction("type");
        try {
            const result = await callApi("delete_classification_type", { name, library_dir: libraryDir });
            if (!result || result.success !== true) {
                applyTypeSnapshot(result, name);
                setTypeIssues(normalizeRuleIssues(result && result.issues));
                setActionState({ tone: "error", message: (result && result.message) || `删除票种「${name}」失败，请检查是否有规则正在使用它。` });
                return;
            }
            applyTypeSnapshot(result, name, { remove: true });
            setTypeIssues([]);
            if (editor && String(editor.targetType || "") === name) {
                setEditor(Object.assign({}, editor, { targetType: "" }));
            }
            setActionState({ tone: "success", message: (result && result.message) || `已删除票种「${name}」。` });
        } catch (error) {
            setTypeIssues([]);
            setActionState({ tone: "error", message: error.message || `删除票种「${name}」失败，请稍后重试。` });
        } finally {
            setBusyAction("");
        }
    }

    function handlePrefillFromInvoice(row) {
        const invoice = row || {};
        const merchant = String(invoice.merchant || "").trim();
        const amount = parseRuleAmount(invoice.amount);
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const form = emptyUserRuleEditor();
        form.id = nextRuleCategoryId(currentDraft.categories.concat(effectiveCategories));
        form.keyword = merchant;
        form.amountMin = amount === null ? "" : String(amount);
        form.amountMax = amount === null ? "" : String(amount);
        setEditor(form);
        setSaveIssues([]);
        setActionState({ tone: "info", message: "已按这张发票预填关键词和金额，请选择目标票种后添加到列表。" });
    }

    function handleAddRuleTerm(term) {
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const entry = cloneRuleTerm(Object.assign({}, term, { source_layer: scope }), scope);
        commitDraft(Object.assign({}, currentDraft, { terms: currentDraft.terms.concat([entry]) }), "已加入销售方词典，保存后生效。", "success");
    }

    function handleDeleteRuleTerm(index) {
        const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
        const terms = currentDraft.terms.filter((item, itemIndex) => itemIndex !== index);
        commitDraft(Object.assign({}, currentDraft, { terms }), "已从销售方词典移除，保存后生效。", "info");
    }

    async function handleSaveRules() {
        if (saving) return;
        if (missingTargetCount > 0 || missingBuiltinTargetCount > 0) {
            const parts = [];
            if (missingTargetCount > 0) parts.push(`${missingTargetCount} 条自定义规则`);
            if (missingBuiltinTargetCount > 0) parts.push(`${missingBuiltinTargetCount} 条内置规则修改`);
            setActionState({ tone: "error", message: `还有 ${parts.join("、")}没有选择目标票种，请逐条编辑补选后再保存。` });
            return;
        }
        setSaving(true);
        setSaveIssues([]);
        try {
            const result = await callApi("save_classification_rules", {
                library_dir: libraryDir,
                scope,
                fallback: draft.fallback || "",
                categories: draft.categories.map(toSaveUserRule).concat((draft.builtinOverrides || []).map(toSaveBuiltinOverride)),
                terms: draft.terms.map(toSaveRuleTerm),
            });
            if (!result || result.success !== true) {
                setSaveIssues(normalizeRuleIssues(result && result.issues));
                setActionState({ tone: "error", message: (result && result.message) || "规则保存失败，请检查目标票种、关键词与金额范围。" });
                return;
            }
            setDirtyScopes((current) => Object.assign({}, current, { [scope]: false }));
            setActionState({ tone: "success", message: result.message || "规则已保存，下一次整理生效。" });
            await reloadRules({ silent: true });
        } catch (error) {
            setActionState({ tone: "error", message: error.message || "规则保存失败，请稍后重试。" });
        } finally {
            setSaving(false);
        }
    }

    async function handleResetScope() {
        if (busyAction) return;
        const scopeName = ruleScopeLabel(scope);
        if (!window.confirm(`恢复默认会覆盖「${scopeName}」当前的自定义规则与销售方词典，并自动备份现有规则文件。是否继续？`)) return;
        setBusyAction("reset");
        try {
            const result = await callApi("reset_classification_rules", scope, libraryDir);
            if (!result || result.success !== true) {
                setActionState({ tone: "error", message: (result && result.message) || "恢复默认失败，请稍后重试。" });
                return;
            }
            setActionState({ tone: "success", message: result.message || "已恢复默认规则。" });
            await reloadRules({ silent: true });
        } catch (error) {
            setActionState({ tone: "error", message: error.message || "恢复默认失败，请稍后重试。" });
        } finally {
            setBusyAction("");
        }
    }

    async function handleOpenRulesFolder() {
        if (busyAction) return;
        setBusyAction("folder");
        try {
            const result = await callApi("open_rules_folder", scope, libraryDir);
            const opened = !!(result && result.success);
            setActionState({
                tone: opened ? "success" : "error",
                message: (result && result.message) || (opened ? "已打开规则目录。" : "打开规则目录失败。"),
            });
        } catch (error) {
            setActionState({ tone: "error", message: error.message || "打开规则目录失败。" });
        } finally {
            setBusyAction("");
        }
    }

    async function handleTestRules() {
        setTestState({ status: "testing", result: null, issues: [], message: "" });
        try {
            const result = await callApi("test_classification_rules", {
                library_dir: libraryDir,
                scope,
                draft: {
                    categories: draft.categories.map(toSaveUserRule),
                    terms: draft.terms.map(toSaveRuleTerm),
                    fallback: draft.fallback || "",
                },
                fields: {
                    seller: String(testFields.seller || "").trim(),
                    seller_tin: String(testFields.seller_tin || "").trim(),
                    item: String(testFields.item || "").trim(),
                    type: String(testFields.type || "").trim(),
                    amount: String(testFields.amount || "").trim(),
                },
            });
            if (!result || result.success !== true) {
                setTestState({
                    status: "error",
                    result: null,
                    issues: normalizeRuleIssues(result && result.issues),
                    message: (result && result.message) || "规则测试失败，请检查输入内容。",
                });
                return;
            }
            setTestState({ status: "success", result: result.result || null, issues: [], message: "" });
        } catch (error) {
            setTestState({ status: "error", result: null, issues: [], message: error.message || "规则测试失败，请稍后重试。" });
        }
    }

    function updateTestField(field, value) {
        setTestFields((current) => Object.assign({}, current, { [field]: value }));
    }

    return (
        <>
            <div className="rules-workspace">
                <div className="rules-action-bar">
                    <div className="footer-cluster">
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => reloadRules()} disabled={busyAction === "reload"}>
                            <span aria-hidden="true" className="material-symbols-outlined">{busyAction === "reload" ? "sync" : "refresh"}</span>
                            <span>{busyAction === "reload" ? "加载中..." : "重新加载"}</span>
                        </button>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={handleOpenRulesFolder} disabled={busyAction === "folder"}>
                            <span aria-hidden="true" className="material-symbols-outlined">folder_open</span>
                            <span>打开规则目录</span>
                        </button>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={handleResetScope} disabled={busyAction === "reset"}>
                            <span aria-hidden="true" className="material-symbols-outlined">restart_alt</span>
                            <span>{busyAction === "reset" ? "恢复中..." : "恢复默认"}</span>
                        </button>
                    </div>
                    <div className="footer-cluster">
                        <StatusPill tone={dirty ? "warning" : "success"} icon={dirty ? "edit" : "task_alt"}>{dirty ? "有未保存修改" : "规则已加载"}</StatusPill>
                        <button type="button" className="btn btn--primary btn--sm" onClick={handleSaveRules} disabled={saving || loading || missingTargetCount > 0 || missingBuiltinTargetCount > 0}>
                            <span aria-hidden="true" className="material-symbols-outlined">{saving ? "sync" : "save"}</span>
                            <span>{saving ? "保存中..." : "保存规则"}</span>
                        </button>
                    </div>
                </div>

                {loading && !rulesData ? <NoticeBox tone="info">正在加载归类规则...</NoticeBox> : null}
                {loadError ? <NoticeBox tone="error">{loadError}</NoticeBox> : null}
                {actionState.message ? <NoticeBox tone={actionState.tone}>{actionState.message}</NoticeBox> : null}
                {loadIssues.length > 0 ? <RuleIssues issues={loadIssues} title="规则文件存在问题" /> : null}
                {loadWarnings.length > 0 ? <RuleIssues issues={loadWarnings} title="规则文件提示" tone="warning" /> : null}
                {saveIssues.length > 0 ? <RuleIssues issues={saveIssues} title="规则校验未通过，请修正后再次保存" /> : null}

                <section className="surface-card">
                    <SectionHeader
                        icon="layers"
                        title="规则作用范围"
                        indicator={<StatusPill tone={dirty ? "warning" : "neutral"}>{`${draft.categories.length} 条自定义规则`}</StatusPill>}
                    />
                    <div className="card-stack card-stack--compact">
                        <div className="rules-scope-tabs" role="group" aria-label="规则作用范围">
                            {RULE_SCOPE_OPTIONS.map((option) => {
                                const optionDisabled = option.value === "library" && !libraryAvailable;
                                return (
                                    <button
                                        key={option.value}
                                        type="button"
                                        className={joinClasses("quick-chip", scope === option.value && "is-active")}
                                        aria-pressed={scope === option.value}
                                        disabled={optionDisabled}
                                        onClick={() => handleScopeChange(option.value)}
                                    >
                                        {option.label}
                                    </button>
                                );
                            })}
                        </div>
                        <p className="field-help">{ruleScopeDescription(scope)}</p>
                        <div className="field-help-group">
                            <p className="field-help field-help--subtle u-mono u-truncate" title={directoryText}>规则文件：{directoryText}</p>
                            <p className="field-help">在界面保存会重写当前作用范围的规则文件；如需保留 YAML 注释，请直接编辑规则文件。</p>
                            {!libraryAvailable ? <p className="field-help">暂未识别到当前发票库：先完成一次本地整理或选择输出目录后，才能切换「当前发票库」并保存库内规则。</p> : null}
                        </div>
                    </div>
                </section>

                <div className="rules-tabbar" role="tablist" aria-label="归类规则分区">
                    {RULE_PANEL_OPTIONS.map((option) => (
                        <button
                            key={option.value}
                            type="button"
                            role="tab"
                            aria-selected={activePanel === option.value}
                            className={joinClasses("quick-chip", activePanel === option.value && "is-active")}
                            onClick={() => handlePanelChange(option.value)}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>

                {activePanel === "tools" ? (
                    <div className="rules-tools-layout">
                        <div className="rules-column">
                            <section className="surface-card">
                                <SectionHeader icon="experiment" title="规则测试" indicator={<StatusPill tone="info">不写入规则文件</StatusPill>} />
                                <div className="card-stack card-stack--compact">
                                    <p className="field-help">用当前编辑中的规则试算一张发票，不会写入规则文件，也不影响已保存配置。</p>
                                    <div className="rules-test-grid">
                                        <div className="field-block">
                                            <label className="field-label" htmlFor="field-18">销售方</label>
                                            <div className="field-shell">
                                                <input id="field-18" type="text" className="field-input" placeholder="如 某某餐饮管理有限公司" value={testFields.seller} onChange={(event) => updateTestField("seller", event.target.value)} />
                                            </div>
                                        </div>
                                        <div className="field-block">
                                            <label className="field-label" htmlFor="field-19">销售方税号</label>
                                            <div className="field-shell">
                                                <input id="field-19" type="text" className="field-input u-mono" placeholder="可选" value={testFields.seller_tin} onChange={(event) => updateTestField("seller_tin", event.target.value)} />
                                            </div>
                                        </div>
                                        <div className="field-block">
                                            <label className="field-label" htmlFor="field-20">发票明细</label>
                                            <div className="field-shell">
                                                <input id="field-20" type="text" className="field-input" placeholder="如 餐饮服务" value={testFields.item} onChange={(event) => updateTestField("item", event.target.value)} />
                                            </div>
                                        </div>
                                        <div className="field-block">
                                            <label className="field-label">票种</label>
                                            <DarkSelect
                                                value={testFields.type}
                                                options={[{ value: "", label: "不限票种" }].concat(documentTypes.map((type) => ({ value: type, label: type })))}
                                                onChange={(value) => updateTestField("type", value)}
                                                ariaLabel="测试票种"
                                            />
                                        </div>
                                        <div className="field-block">
                                            <label className="field-label" htmlFor="field-21">金额</label>
                                            <div className="field-shell">
                                                <input id="field-21" type="text" inputMode="decimal" className="field-input u-tabular" placeholder="如 128.00" value={testFields.amount} onChange={(event) => updateTestField("amount", event.target.value)} />
                                            </div>
                                        </div>
                                    </div>
                                    <div className="footer-cluster">
                                        <button type="button" className="btn btn--secondary btn--sm" onClick={handleTestRules} disabled={testState.status === "testing"}>
                                            <span aria-hidden="true" className="material-symbols-outlined">{testState.status === "testing" ? "sync" : "play_arrow"}</span>
                                            <span>{testState.status === "testing" ? "测试中..." : "测试归类结果"}</span>
                                        </button>
                                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setTestState({ status: "idle", result: null, issues: [], message: "" })}>
                                            <span aria-hidden="true" className="material-symbols-outlined">clear_all</span>
                                            <span>清空结果</span>
                                        </button>
                                    </div>
                                    {testState.message ? <NoticeBox tone={testState.status === "error" ? "error" : "info"}>{testState.message}</NoticeBox> : null}
                                    {testState.issues.length > 0 ? <RuleIssues issues={testState.issues} title="测试校验未通过" /> : null}
                                    <RuleTestResult result={testState.result} categoryNameById={categoryNameById} targetTypeById={targetTypeById} />
                                </div>
                            </section>
                        </div>
                        <div className="rules-column">
                            <section className="surface-card">
                                <SectionHeader icon="menu_book" title="销售方词典" indicator={<StatusPill tone="info">{`${draft.terms.length} 条`}</StatusPill>} />
                                <RuleDictionarySection
                                    terms={draft.terms}
                                    categoryOptions={ruleRows}
                                    scope={scope}
                                    onAddTerm={handleAddRuleTerm}
                                    onDeleteTerm={handleDeleteRuleTerm}
                                />
                            </section>
                        </div>
                    </div>
                ) : activePanel === "types" ? (
                    <RuleTypesManager
                        builtinTypes={typesState.builtinTypes}
                        customTypes={typesState.customTypes}
                        issues={typeIssues}
                        busy={busyAction === "type"}
                        onDeleteType={handleDeleteType}
                    />
                ) : (
                    <div className="rules-panel">
                        <NoticeBox tone="info">{RULE_ORDER_HELP}</NoticeBox>

                        {missingTargetCount > 0 ? (
                            <NoticeBox tone="warning">
                                有 {missingTargetCount} 条历史规则还没有选择目标票种，请逐条编辑补选后再保存。
                            </NoticeBox>
                        ) : null}
                        {missingBuiltinTargetCount > 0 ? (
                            <NoticeBox tone="warning">
                                有 {missingBuiltinTargetCount} 条内置规则修改还没有选择目标票种，请逐条编辑补选后再保存。
                            </NoticeBox>
                        ) : null}

                        <RuleUnclassifiedSection invoices={unclassifiedInvoices} onPrefill={handlePrefillFromInvoice} />

                        <div className="rules-layout">
                            <div className="rules-column rules-column--main">
                                <section className="surface-card">
                                    <SectionHeader icon="rule" title="自定义规则" />
                                    <div className="card-stack card-stack--compact">
                                        <div className="rules-toolbar">
                                            <p className="field-help">每条规则由目标票种、关键词和金额范围组成，文件夹按「目标票种 + 金额范围」自动生成。</p>
                                            <button type="button" className="btn btn--secondary btn--sm" onClick={handleAddRule}>
                                                <span aria-hidden="true" className="material-symbols-outlined">add</span>
                                                <span>新增规则</span>
                                            </button>
                                        </div>
                                        {ruleRows.length === 0 ? (
                                            <div className="rules-empty-state">
                                                <span aria-hidden="true" className="material-symbols-outlined">rule</span>
                                                <p>当前作用范围还没有自定义规则，点击「新增规则」创建第一条规则。</p>
                                            </div>
                                        ) : (
                                            <div className="rules-category-list">
                                                {ruleRows.map((row) => (
                                                    <div key={String(row.id || row.index)} className={joinClasses("rule-category-row", row.enabled === false && "is-disabled")}>
                                                        <div className="rule-category-row__main">
                                                            <div className="rule-category-row__title">
                                                                <span aria-hidden="true" className="rule-category-row__folder-icon material-symbols-outlined">folder</span>
                                                                <span className={joinClasses("rule-category-row__name", "u-truncate", !row.previewFolder && "rule-category-row__name--missing")} title={row.previewFolder || "请选择目标票种"}>
                                                                    {row.previewFolder || "请选择目标票种"}
                                                                </span>
                                                                {row.target_type
                                                                    ? <span className="rule-target-tag" title={`目标票种：${row.target_type}`}>{row.target_type}</span>
                                                                    : <StatusPill tone="warning">缺少目标票种</StatusPill>}
                                                                {row.enabled === false ? <StatusPill tone="warning">已停用</StatusPill> : null}
                                                            </div>
                                                            <div className="rule-category-row__meta">
                                                                <span>关键词 <strong>{safeText(row.mainKeyword, "未填写")}</strong></span>
                                                                <span>金额 <strong>{formatRuleAmountRangeLabel(row.amount_range)}</strong></span>
                                                                {row.target_type && documentTypes.length > 0 && documentTypes.indexOf(row.target_type) < 0 ? <StatusPill tone="error">票种已失效</StatusPill> : null}
                                                            </div>
                                                        </div>
                                                        <div className="rule-category-row__actions">
                                                            <button
                                                                type="button"
                                                                className={joinClasses("rule-icon-button", row.enabled !== false && "is-active")}
                                                                title={row.enabled !== false ? "停用" : "启用"}
                                                                aria-label={`${row.enabled !== false ? "停用" : "启用"} ${row.previewFolder || "规则"}`}
                                                                onClick={() => handleToggleRule(row.index)}
                                                            >
                                                                <span aria-hidden="true" className="material-symbols-outlined">{row.enabled !== false ? "toggle_on" : "toggle_off"}</span>
                                                            </button>
                                                            <button type="button" className="rule-icon-button" title="上移" aria-label={`上移 ${row.previewFolder || "规则"}`} disabled={row.index === 0} onClick={() => handleMoveRule(row.index, -1)}>
                                                                <span aria-hidden="true" className="material-symbols-outlined">arrow_upward</span>
                                                            </button>
                                                            <button type="button" className="rule-icon-button" title="下移" aria-label={`下移 ${row.previewFolder || "规则"}`} disabled={row.index === ruleRows.length - 1} onClick={() => handleMoveRule(row.index, 1)}>
                                                                <span aria-hidden="true" className="material-symbols-outlined">arrow_downward</span>
                                                            </button>
                                                            <button type="button" className="rule-icon-button" title="编辑" aria-label={`编辑 ${row.previewFolder || "规则"}`} onClick={() => handleEditRule(row.index)}>
                                                                <span aria-hidden="true" className="material-symbols-outlined">edit</span>
                                                            </button>
                                                            <button type="button" className="rule-icon-button rule-icon-button--danger" title="删除" aria-label={`删除 ${row.previewFolder || "规则"}`} onClick={() => handleDeleteRule(row.index)}>
                                                                <span aria-hidden="true" className="material-symbols-outlined">delete</span>
                                                            </button>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </section>
                            </div>

                            <div className="rules-column rules-column--side">
                                {builtinEditor ? null : (
                                    <section className="surface-card">
                                        <SectionHeader
                                            icon={editor && editor.mode === "edit" ? "edit_note" : "add_circle"}
                                            title={editor ? (editor.mode === "new" ? "新增规则" : "编辑规则") : "规则编辑"}
                                            indicator={editor ? <StatusPill tone="info">{ruleScopeLabel(scope)}</StatusPill> : null}
                                        />
                                        <RuleEditor
                                            editor={editor}
                                            documentTypes={documentTypes}
                                            onChange={handleEditorChange}
                                            onCreateType={handleCreateType}
                                            onCommit={handleEditorCommit}
                                            onCancel={() => {
                                                setEditor(null);
                                                setSaveIssues([]);
                                            }}
                                        />
                                    </section>
                                )}
                            </div>
                        </div>

                        {builtinEditor ? (
                            <section className="surface-card">
                                <SectionHeader icon="edit_note" title={builtinEditor.label ? `编辑内置规则：${builtinEditor.label}` : "编辑内置规则"} indicator={<StatusPill tone="info">{ruleScopeLabel(scope)}</StatusPill>} />
                                <RuleBuiltinEditor
                                    editor={builtinEditor}
                                    documentTypes={documentTypes}
                                    onChange={handleBuiltinEditorChange}
                                    onCreateType={handleCreateType}
                                    onCommit={handleBuiltinEditorCommit}
                                    onCancel={() => setBuiltinEditor(null)}
                                />
                            </section>
                        ) : null}

                        <RuleBuiltinSection
                            rows={builtinRows}
                            busy={saving || restoreBusy}
                            onEdit={handleEditBuiltinRule}
                            onToggle={handleToggleBuiltinRule}
                            onRestore={handleRestoreBuiltinRule}
                            onRestoreAll={handleRestoreAllBuiltin}
                        />
                    </div>
                )}
            </div>
            <RuleRestoreDialog
                dialog={restoreDialog}
                mode={restoreMode}
                busy={restoreBusy}
                error={restoreError}
                issues={restoreIssues}
                libraryAvailable={libraryAvailable}
                scopeLabel={ruleScopeLabel(scope)}
                dirty={dirty}
                onModeChange={setRestoreMode}
                onConfirm={handleConfirmRestoreBuiltin}
                onCancel={() => {
                    setRestoreDialog(null);
                    setRestoreError("");
                    setRestoreIssues([]);
                }}
            />
        </>
    );
}

const ReactComponentBase = (React && React.Component) || class ReactComponentFallback {
    constructor(props) {
        this.props = props;
        this.state = {};
    }

    setState(next) {
        this.state = { ...this.state, ...next };
    }
};

class ErrorBoundary extends ReactComponentBase {
    constructor(props) {
        super(props);
        this.state = { error: null };
    }

    static getDerivedStateFromError(error) {
        return { error };
    }

    componentDidCatch(error) {
        if (window.console && console.error) {
            console.error("interface render failed", error);
        }
    }

    render() {
        if (this.state.error) {
            return (
                <div style={{ minHeight: "100vh", padding: "48px", background: "#0f172a", color: "#e5e7eb" }}>
                    <h1 style={{ fontSize: "20px", marginBottom: "12px" }}>界面加载失败</h1>
                    <p style={{ marginBottom: "20px", color: "#cbd5e1" }}>请关闭应用后重新打开；若问题持续，请查看诊断日志。</p>
                    <button
                        type="button"
                        onClick={() => window.location.reload()}
                        style={{ padding: "8px 16px", borderRadius: "6px", border: "1px solid #475569", background: "#1e293b", color: "#e5e7eb" }}
                    >
                        重新加载
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}

function reportClientFatal(detail) {
    try {
        console.error("interface fatal", detail);
    } catch (_error) {
        // Console may be unavailable in the packaged shell.
    }
    const container = document.getElementById("root");
    if (container && !container.hasChildNodes()) {
        container.textContent = "界面加载失败，请重新打开应用。";
    }
}

if (typeof window.addEventListener === "function") {
    window.addEventListener("error", (event) => reportClientFatal(event.error || event.message));
    window.addEventListener("unhandledrejection", (event) => reportClientFatal(event.reason));
}

function App() {
    const [showDisclaimer, setShowDisclaimer] = useState(false);
    const { theme, toggleTheme } = useTheme();
    const shell = useShellSettings();
    const openDisclaimer = () => setShowDisclaimer(true);
    const bootstrapping = shell.bootstrapState !== "bootstrapped";
    const bootstrapFailed = shell.bootstrapState === "bootstrap_failed";

    return (
        <>
            <MemoryRouter>
                {bootstrapping ? (
                    <BootstrapStatePage
                        active="home"
                        theme={theme}
                        onToggleTheme={toggleTheme}
                        onOpenDisclaimer={openDisclaimer}
                        eyebrow={UI_COPY.pages.home.eyebrow}
                        title={UI_COPY.pages.home.bootstrapTitle}
                        description={bootstrapFailed ? UI_COPY.pages.home.errorDescription : UI_COPY.pages.home.bootstrapDescription}
                        tone={bootstrapFailed ? "error" : "info"}
                        message={bootstrapFailed ? (shell.bootstrapError || UI_COPY.pages.home.errorMessage) : UI_COPY.pages.home.bootstrapMessage}
                        footerText="正在载入"
                    />
                ) : (
                    <Routes>
                        <Route path="/" element={<HomePage shell={shell} theme={theme} onToggleTheme={toggleTheme} onOpenDisclaimer={openDisclaimer} />} />
                        <Route path="/results" element={<AnalysisPage theme={theme} onToggleTheme={toggleTheme} onOpenDisclaimer={openDisclaimer} />} />
                        <Route path="/settings" element={<SettingsPage shell={shell} theme={theme} onToggleTheme={toggleTheme} onOpenDisclaimer={openDisclaimer} />} />
                    </Routes>
                )}
            </MemoryRouter>
            <DisclaimerDialog open={showDisclaimer} onClose={() => setShowDisclaimer(false)} />
        </>
    );
}

document.title = APP_BRAND.name;
const root = createRoot(document.getElementById("root"));
root.render(<ErrorBoundary><App /></ErrorBoundary>);

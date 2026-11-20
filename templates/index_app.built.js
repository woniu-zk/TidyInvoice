/*! 前端产物 - 由 tools/compile-frontend.mjs 依据 templates/index_app.js 生成，请勿手改。 */
function _extends() { _extends = Object.assign ? Object.assign.bind() : function (target) { for (var i = 1; i < arguments.length; i++) { var source = arguments[i]; for (var key in source) { if (Object.prototype.hasOwnProperty.call(source, key)) { target[key] = source[key]; } } } return target; }; return _extends.apply(this, arguments); }
const {
  useEffect,
  useMemo,
  useRef,
  useState
} = React;
const {
  createRoot
} = ReactDOM;
const {
  MemoryRouter,
  Routes,
  Route,
  useNavigate
} = ReactRouterDOM;
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
    date_to: isoDate(new Date())
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
  local_split_by_category: true
};
const DEFAULT_RUN_SETTINGS = {
  ...lastDaysRange(30),
  quick_range: "last_30_days"
};
const DEFAULT_PROGRESS = {
  progress: 0,
  status_text: "等待任务开始...",
  logs: [],
  stats: {
    emails: 0,
    invoices: 0,
    errors: 0
  },
  is_running: false,
  run_state: "idle",
  task_mode: "mail",
  dry_run: false,
  last_error: "",
  stop_requested: false,
  can_stop: false,
  quota_exhausted: false,
  quota_message: "",
  build_identity: null
};

// 品牌标识来自 templates/brand.generated.js（由 brand.json 生成，勿手改）。
// 界面文案（任务模式、结果横幅等）仍在本文件内，后续由 i18n 词表接管。
if (!window.__APP_BRAND__) {
  throw new Error("品牌清单未加载：templates/brand.generated.js 必须在 index_app.built.js 之前引入");
}
const APP_BRAND = Object.freeze({
  name: window.__APP_BRAND__.name,
  subtitle: window.__APP_BRAND__.subtitle
});
const APP_VISIBLE_COPY = {
  topSubtitle: window.__APP_BRAND__.subtitle,
  footerVersion: window.__APP_BRAND__.footerVersion,
  footerStamp: window.__APP_BRAND__.footerStamp,
  githubLabel: window.__APP_BRAND__.githubLabel,
  githubUrl: window.__APP_BRAND__.githubUrl,
  taskModes: {
    mail: {
      label: "邮箱提取并整理",
      description: "连接邮箱提取附件，识别后按分类与命名规则归档。",
      badge: "识别后归档"
    },
    fetch: {
      label: "仅提取到 inbox",
      description: "只把邮箱附件保存到 inbox 文件夹并生成清单，不做识别和归档。",
      badge: "只保存附件"
    },
    local: {
      label: "本地文件夹整理",
      description: "读取本机文件夹中的发票文件，直接在该文件夹内离线识别并自动分类归档，不需要邮箱和网络。",
      badge: "本机离线整理"
    }
  },
  resultBanners: {
    fetch: {
      eyebrow: "提取结果",
      title: "仅提取完成",
      text: "附件已保存到 inbox 文件夹，并写入 manifest.jsonl；未进行识别和归档。"
    },
    localApply: {
      eyebrow: "整理结果",
      title: "本地整理完成",
      text: "已按分类与命名规则归档本地发票；原件已原样保留在「整理前发票」文件夹（文件名不变），重复文件已移入 duplicates 文件夹。"
    },
    localApplyCustom: {
      eyebrow: "整理结果",
      title: "本地整理完成",
      text: "已按分类与命名规则归档本地发票；原始文件保留在发票文件夹，未移动。"
    },
    localApplyFlat: {
      eyebrow: "整理结果",
      title: "本地整理完成",
      text: "已按命名规则整理本地发票（未建分类子目录）；原件已原样保留在「整理前发票」文件夹（文件名不变），重复文件已移入 duplicates 文件夹。"
    },
    localApplyCustomFlat: {
      eyebrow: "整理结果",
      title: "本地整理完成",
      text: "已按命名规则整理本地发票（未建分类子目录）；原始文件保留在发票文件夹，未移动。"
    }
  }
};
const TASK_MODE_OPTIONS = [{
  value: "mail",
  ...APP_VISIBLE_COPY.taskModes.mail
}, {
  value: "fetch",
  ...APP_VISIBLE_COPY.taskModes.fetch
}, {
  value: "local",
  ...APP_VISIBLE_COPY.taskModes.local
}];
const TASK_MODE_VALUES = new Set(TASK_MODE_OPTIONS.map(option => option.value));
const EMAIL_DOMAIN_OPTIONS = [{
  value: "qq.com",
  label: "qq.com"
}, {
  value: "163.com",
  label: "163.com"
}, {
  value: "88.com",
  label: "88.com"
}];
const SUPPORTED_EMAIL_DOMAINS = new Set(EMAIL_DOMAIN_OPTIONS.map(option => option.value));
const LOCAL_ENGINE_ITEMS = [{
  key: "pdf-text",
  icon: "description",
  title: "PDF 文本解析",
  description: "直接读取电子发票的版式文本与明细。"
}, {
  key: "ofd",
  icon: "picture_as_pdf",
  title: "OFD 解析",
  description: "解析国标版式文件中的票面信息。"
}, {
  key: "ocr",
  icon: "document_scanner",
  title: "本地 OCR",
  description: "扫描件与图片在本机离线识别。"
}];
const DISCLAIMER_SOFTWARE_ITEMS = ["本软件用于票据整理、归档与复核辅助处理。", "本软件不附带任何真实邮箱凭据。", "请仅填写并使用你自己的邮箱授权信息。", "涉及报销、入账或合规判断的重要票据，请务必进行人工复核。"];
const DISCLAIMER_ITEMS = ["本工具用于票据整理与归档辅助，识别结果应结合业务流程进行复核。", "对于识别、归档、遗漏、误判及由此产生的后果，工具方不承担责任。", "使用者应自行遵守所在公司关于票据数据与信息安全管理的相关规定。", "涉及报销、入账或合规判断的重要票据，请务必进行人工复核。"];
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
    windowSubtitle: "桌面工作区"
  },
  navigation: [{
    key: "settings",
    label: "启动配置",
    description: "邮箱、识别与日期",
    icon: "tune",
    path: "/"
  }, {
    key: "processing",
    label: "处理中心",
    description: "进度与日志",
    icon: "data_thresholding",
    path: "/processing"
  }, {
    key: "analysis",
    label: "结果分析",
    description: "总览与导出",
    icon: "assessment",
    path: "/analysis"
  }, {
    key: "rules",
    label: "归类规则",
    description: "目标票种、关键词与金额",
    icon: "rule",
    path: "/rules"
  }],
  pages: {
    settings: {
      eyebrow: "Step 1",
      title: "启动配置",
      footerText: "当前页: 启动配置",
      bootstrapTitle: "启动配置",
      bootstrapDescription: "正在初始化本地设置。",
      bootstrapMessage: "正在连接桌面接口并加载本地设置，请稍候。",
      errorDescription: "本地设置初始化失败。",
      controlledNotice: "受控复跑已锁定输出目录与日期窗口。"
    },
    processing: {
      eyebrow: "Step 2",
      title: "处理中心",
      footerText: "当前页: 处理中心",
      closeHint: "关闭程序会直接结束当前窗口与任务进程，请仅在确认后执行。",
      statusWaiting: "等待任务状态",
      currentOperation: "当前操作",
      progressLabel: "完成度",
      liveRefresh: "进度与日志保持实时刷新。",
      stopPending: "已收到安全停止指令。",
      stopDetail: "系统将在当前文件处理完成后安全停止。",
      processingDetail: "邮件抓取、票据恢复与本地识别将依次执行。",
      processingDetailFetch: "本轮只提取邮箱附件，不会进行识别与归档。",
      processingDetailLocal: "本地文件扫描、票据识别与归档整理将依次执行。",
      scanEmailsLabel: "已扫描邮件",
      scanFilesLabel: "已扫描文件",
      stopNotice: "已收到安全停止指令，当前邮件或当前文件处理完成后将结束任务。"
    },
    analysis: {
      eyebrow: "Step 3",
      title: "结果分析",
      footerText: "当前页: 结果分析",
      statusSummary: "运行结果",
      resultTitle: "本次处理完成",
      reviewTitle: "待人工复核",
      reviewEmpty: "当前没有待人工复核记录。",
      reviewReady: "请优先前往待人工复核文件夹处理这些记录。",
      reviewIdle: "结果明细仍可导出查看，输出目录会保留本轮成功归档结果。",
      classificationTitle: "分类汇总",
      classificationEmpty: "本轮还没有可统计的分类结果。"
    },
    rules: {
      title: "归类规则",
      description: "用目标票种、关键词和金额范围建立归档规则；保存后在下一次整理时生效。"
    }
  }
};
const RULE_SCOPE_OPTIONS = [{
  value: "global",
  label: "全局规则",
  description: "对本机所有发票库生效，适合长期稳定的规则。"
}, {
  value: "library",
  label: "当前发票库",
  description: "只对当前发票库生效，适合单个项目或单个文件夹的特殊规则。"
}];
const RULE_PANEL_OPTIONS = [{
  value: "rules",
  label: "规则列表"
}, {
  value: "tools",
  label: "词典与测试"
}, {
  value: "types",
  label: "票种管理"
}];
const RULE_SOURCE_LAYER_LABELS = {
  builtin: "内置",
  global: "全局",
  library: "发票库",
  pack: "规则包"
};
const CLASSIFICATION_SOURCE_LABELS = {
  builtin_keyword: "内置关键词",
  builtin_type: "票种兜底",
  user_rule: "用户规则",
  rule_pack: "规则包",
  dictionary: "销售方词典",
  unknown: "未归类",
  skipped: "未参与归类",
  isolation: "隔离类型"
};
const RULE_CHAIN_REASON_LABELS = {
  disabled: "规则已停用",
  invoice_type_mismatch: "票种不符",
  amount_missing: "票面金额缺失",
  amount_out_of_range: "金额不在范围内",
  empty_match_text: "没有可匹配的销售方或明细",
  excluded: "命中排除关键词",
  no_keyword_matched: "未命中关键词",
  keyword: "命中关键词"
};
const RULE_ORDER_HELP = "规则从上到下匹配，命中第一条即停止。匹配顺序：当前发票库规则 → 全局规则 → 内置默认。";
const RULE_TARGET_TYPE_HELP = "目标票种决定归档文件夹和归类结果。内置票种是发票识别结果；自定义票种全局可用，可以给任意规则指定。";
const RULE_CUSTOM_TYPE_HELP = "自定义票种全局可用，全局规则和当前发票库规则都能选择。";
function ruleScopeLabel(scope) {
  const option = RULE_SCOPE_OPTIONS.find(item => item.value === scope);
  return option ? option.label : RULE_SCOPE_OPTIONS[0].label;
}
function ruleScopeDescription(scope) {
  const option = RULE_SCOPE_OPTIONS.find(item => item.value === scope);
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
  tokens.forEach(token => {
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
  const used = new Set((existing || []).map(item => String(item && item.id || "")));
  let index = 1;
  while (used.has(`rule_${index}`)) index += 1;
  return `rule_${index}`;
}
function normalizeRuleIssues(value) {
  const issues = [];
  (Array.isArray(value) ? value : []).forEach(item => {
    if (!item) return;
    if (typeof item === "string") {
      const text = item.trim();
      if (text) issues.push({
        file: "",
        line: 0,
        message: text,
        severity: "error",
        text
      });
      return;
    }
    const file = String(item.file || "");
    const line = Number(item.line || 0);
    const message = String(item.message || item.text || "");
    const severity = String(item.severity || "error").toLowerCase() === "warning" ? "warning" : "error";
    const location = file ? ruleLocationTitle(file, line) : "";
    const text = String(item.text || "").trim() || (location && message ? `${location}: ${message}` : location || message);
    if (message || text) issues.push({
      file,
      line,
      message,
      severity,
      text
    });
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
    source_line: Number(source.source_line || 0)
  };
}
function normalizeRuleTermEntries(value, scope) {
  const entries = [];
  if (Array.isArray(value)) {
    value.forEach(item => entries.push(cloneRuleTerm(item, scope)));
  } else if (value && typeof value === "object") {
    Object.keys(value).forEach(term => {
      entries.push(cloneRuleTerm({
        term,
        category: value[term]
      }, scope));
    });
  }
  return entries.filter(item => item.term);
}
function toSaveRuleTerm(term) {
  const source = term || {};
  return {
    term: String(source.term || "").trim(),
    category: String(source.category || "").trim()
  };
}
function normalizeUserRuleEntry(entry) {
  const source = entry || {};
  const keywords = (Array.isArray(source.keywords) ? source.keywords : []).map(item => String(item).trim()).filter(Boolean);
  const legacyInvoiceTypes = (Array.isArray(source.invoice_types) ? source.invoice_types : []).map(item => String(item).trim()).filter(Boolean);
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
    exclude_keywords: (Array.isArray(source.exclude_keywords) ? source.exclude_keywords : []).map(item => String(item)).filter(Boolean)
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
    keywords: (Array.isArray(source.keywords) ? source.keywords : []).map(item => String(item).trim()).filter(Boolean),
    amount_range: normalizeRuleAmountRange(source.amount_range),
    enabled: source.enabled !== false
  };
}
function buildUserRuleDraft(scopeData, scope, builtinIds, documentTypes) {
  const data = scopeData || {};
  const builtinIdSet = new Set((builtinIds || []).map(item => String(item)));
  const categories = [];
  const builtinOverrides = [];
  (Array.isArray(data.categories) ? data.categories : []).forEach(item => {
    const id = String(item && item.id || "");
    if (id && builtinIdSet.has(id)) builtinOverrides.push(normalizeBuiltinOverride(item, documentTypes));else categories.push(normalizeUserRuleEntry(item));
  });
  return {
    categories,
    builtinOverrides,
    terms: normalizeRuleTermEntries(data.terms, scope),
    fallback: String(data.fallback || "")
  };
}
function toSaveUserRule(entry) {
  const source = entry || {};
  const keyword = String(source.mainKeyword || "").trim();
  const targetType = String(source.target_type || "").trim();
  const extraKeywords = (Array.isArray(source.legacyExtraKeywords) ? source.legacyExtraKeywords : []).map(item => String(item).trim()).filter(item => item && item !== keyword);
  const payload = {
    id: String(source.id || "").trim(),
    name: String(source.name || "").trim() || buildRuleFolderName(targetType, source.amount_range) || keyword,
    target_type: targetType,
    keywords: [keyword].concat(extraKeywords),
    amount_range: normalizeRuleAmountRange(source.amount_range),
    enabled: source.enabled !== false
  };
  // Legacy fields stay in the saved payload but are not shown in the editor.
  if (source.match) payload.match = String(source.match);
  if (Array.isArray(source.exclude_keywords) && source.exclude_keywords.length > 0) {
    payload.exclude_keywords = source.exclude_keywords.map(item => String(item));
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
    keywords: (Array.isArray(source.keywords) ? source.keywords : []).map(item => String(item)),
    amount_range: normalizeRuleAmountRange(source.amount_range),
    enabled: source.enabled !== false
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
  (entries || []).forEach(item => {
    const id = String(item && item.id || "");
    if (id) map[id] = String(item && (item.name || item.archive_folder) || id);
  });
  return map;
}
function describeRuleChainStep(step, categoryNameById) {
  if (!step || typeof step !== "object") return "";
  const lookupCategory = value => {
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
    name: ""
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
    legacyExcludeKeywords: (Array.isArray(source.exclude_keywords) ? source.exclude_keywords : []).map(item => String(item)),
    legacyExtraKeywords: (Array.isArray(source.legacyExtraKeywords) ? source.legacyExtraKeywords : []).map(item => String(item)),
    name: String(source.name || "")
  };
}
function joinClasses(...values) {
  return values.filter(Boolean).join(" ");
}
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
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
function validateEmail(email) {
  const value = String(email || "").trim();
  if (!value) {
    return "请输入邮箱地址。";
  }
  if (!/@(qq|163|88)\.com$/i.test(value)) {
    return "当前支持 QQ 邮箱、163 邮箱和 88 邮箱。";
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
  const token = safeText(runContext && runContext.autostart_token || "", "").trim();
  const runId = safeText(runContext && runContext.run_id || "", "").trim();
  return [CONTROLLED_AUTOSTART_PREFIX, token || runId || "default"].join(".");
}
function markControlledAutostartConsumed(runContext) {
  writeSessionValue(controlledAutostartStateKey(runContext), {
    consumed: true,
    consumed_at: new Date().toISOString()
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
    ...(settings || {})
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
  const [settingsRes, runContextRes, rulesStatusRes] = await Promise.all([callApi("load_user_settings"), callApi("get_run_context").catch(() => ({})), callApi("get_classification_rules_status").catch(() => ({}))]);
  const storedPayload = Object.assign({}, DEFAULT_SETTINGS, DEFAULT_RUN_SETTINGS, settingsRes && settingsRes.settings || {});
  const sessionSettings = readSessionValue(SESSION_SETTINGS_KEY);
  const sessionRunSettings = readSessionValue(SESSION_RUN_SETTINGS_KEY);
  const runContext = runContextRes || {};
  const settings = {
    email: preferNonEmpty(sessionSettings.email, storedPayload.email),
    // Sensitive values must not be revived from WebView session state.
    auth_code: preferNonEmpty(storedPayload.auth_code),
    save_path: preferNonEmpty(sessionSettings.save_path, storedPayload.save_path),
    company: preferNonEmpty(sessionSettings.company, storedPayload.company),
    remember_settings: sessionSettings.remember_settings === undefined ? storedPayload.remember_settings !== false : sessionSettings.remember_settings !== false,
    task_mode: normalizeTaskMode(preferNonEmpty(sessionSettings.task_mode, storedPayload.task_mode, "mail")),
    local_input_dir: preferNonEmpty(sessionSettings.local_input_dir, storedPayload.local_input_dir),
    local_output_dir: preferNonEmpty(sessionSettings.local_output_dir, storedPayload.local_output_dir),
    local_split_by_category: sessionSettings.local_split_by_category === undefined ? storedPayload.local_split_by_category !== false : sessionSettings.local_split_by_category !== false
  };
  const runSettings = {
    date_from: preferNonEmpty(sessionRunSettings.date_from, storedPayload.date_from, DEFAULT_RUN_SETTINGS.date_from),
    date_to: preferNonEmpty(sessionRunSettings.date_to, storedPayload.date_to, DEFAULT_RUN_SETTINGS.date_to),
    quick_range: preferNonEmpty(sessionRunSettings.quick_range, storedPayload.quick_range, "last_30_days")
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
  return {
    settings,
    runSettings,
    runContext,
    rulesStatus: rulesStatusRes || {}
  };
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
    local_split_by_category: payload.local_split_by_category !== false
  });
  writeSessionValue(SESSION_RUN_SETTINGS_KEY, {
    date_from: payload.date_from || "",
    date_to: payload.date_to || "",
    quick_range: payload.quick_range || DEFAULT_RUN_SETTINGS.quick_range
  });
  if (payload.remember_settings === false) {
    return callApi("save_user_settings", {
      remember_settings: false
    });
  }
  return callApi("save_user_settings", payload);
}
function toneFromAsyncStatus(status) {
  if (status === "success") return "success";
  if (status === "error") return "error";
  if (status === "testing") return "info";
  return "info";
}
function splitEmailAddress(email) {
  const value = String(email || "").trim();
  const separatorIndex = value.lastIndexOf("@");
  const username = separatorIndex >= 0 ? value.slice(0, separatorIndex) : value;
  const rawDomain = separatorIndex >= 0 ? value.slice(separatorIndex + 1).toLowerCase() : "";
  const domain = SUPPORTED_EMAIL_DOMAINS.has(rawDomain) ? rawDomain : "qq.com";
  return {
    username,
    domain
  };
}
function resolveGroupTone(groupKey) {
  if (groupKey === "manual_review") return "group-chip--warning";
  if (groupKey === "retained_record") return "group-chip--info";
  if (groupKey === "processing_error") return "group-chip--error";
  return "";
}
function resolveLogToneClass(log) {
  const sample = `${String(log && log.color || "")} ${String(log && log.type || "")}`.toLowerCase();
  if (sample.includes("error") || sample.includes("red")) return "terminal-kind terminal-kind--error";
  if (sample.includes("warning") || sample.includes("warn") || sample.includes("amber") || sample.includes("orange")) return "terminal-kind terminal-kind--warning";
  if (sample.includes("success") || sample.includes("green") || sample.includes("emerald")) return "terminal-kind terminal-kind--success";
  if (sample.includes("info") || sample.includes("blue") || sample.includes("cyan")) return "terminal-kind terminal-kind--info";
  return "terminal-kind";
}
function NoticeBox({
  tone = "info",
  className = "",
  children
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: joinClasses("notice", `notice--${tone}`, className)
  }, children);
}
function InlineStatus({
  tone = "info",
  children
}) {
  const icon = tone === "success" ? "task_alt" : tone === "error" ? "error" : tone === "warning" ? "warning" : "info";
  return /*#__PURE__*/React.createElement("div", {
    className: joinClasses("inline-status", `inline-status--${tone}`)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined inline-status__icon"
  }, icon), /*#__PURE__*/React.createElement("span", {
    className: "inline-status__text"
  }, children));
}
function StatusPill({
  tone = "neutral",
  icon,
  children
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: joinClasses("status-pill", tone !== "neutral" && `status-pill--${tone}`)
  }, icon && /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined",
    style: {
      fontSize: 16
    }
  }, icon), /*#__PURE__*/React.createElement("span", null, children));
}
function SectionHeader({
  icon,
  title,
  indicator
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "section-header"
  }, /*#__PURE__*/React.createElement("div", {
    className: "section-title"
  }, /*#__PURE__*/React.createElement("span", {
    className: "section-title__icon material-symbols-outlined"
  }, icon), /*#__PURE__*/React.createElement("span", null, title)), indicator ? /*#__PURE__*/React.createElement("div", {
    className: "u-text-muted",
    style: {
      fontSize: 12
    }
  }, indicator) : null);
}
function PageHeader({
  eyebrow,
  title,
  description,
  badge
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "page-header-shell"
  }, /*#__PURE__*/React.createElement("div", null, eyebrow ? /*#__PURE__*/React.createElement("p", {
    className: "page-eyebrow"
  }, eyebrow) : null, /*#__PURE__*/React.createElement("h1", {
    className: "page-title"
  }, title), description ? /*#__PURE__*/React.createElement("p", {
    className: "page-description"
  }, description) : null), badge ? /*#__PURE__*/React.createElement("div", {
    className: "page-header-badge"
  }, badge) : null);
}
function PageFooter({
  left,
  right
}) {
  return /*#__PURE__*/React.createElement("footer", {
    className: "footer-bar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "footer-slot"
  }, left), /*#__PURE__*/React.createElement("div", {
    className: "footer-slot footer-slot--right"
  }, right));
}
function DarkSelect({
  value,
  options,
  onChange,
  disabled = false,
  ariaLabel
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const activeOption = options.find(option => option.value === value) || options[0] || {
    value: "",
    label: ""
  };
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
  return /*#__PURE__*/React.createElement("div", {
    ref: rootRef,
    className: joinClasses("field-shell", "field-shell--dropdown", disabled && "field-shell--readonly", open && "field-shell--dropdown-open")
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "field-dropdown-trigger",
    "aria-haspopup": "listbox",
    "aria-expanded": open,
    "aria-label": ariaLabel,
    onClick: () => !disabled && setOpen(current => !current),
    disabled: disabled
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-dropdown-trigger__label"
  }, activeOption.label), /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined field-dropdown-trigger__icon"
  }, open ? "expand_less" : "expand_more")), open ? /*#__PURE__*/React.createElement("div", {
    className: "field-dropdown-menu",
    role: "listbox",
    "aria-label": ariaLabel
  }, options.map(option => /*#__PURE__*/React.createElement("button", {
    key: option.value,
    type: "button",
    className: joinClasses("field-dropdown-option", option.value === activeOption.value && "is-active"),
    onClick: () => handleSelect(option.value)
  }, /*#__PURE__*/React.createElement("span", null, option.label), option.value === activeOption.value ? /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "check") : null))) : null);
}
function DateField({
  label,
  value,
  onChange,
  disabled = false
}) {
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
  return /*#__PURE__*/React.createElement("div", {
    className: "field-block",
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, label), /*#__PURE__*/React.createElement("div", {
    className: joinClasses("field-shell", "field-shell--date", disabled && "field-shell--readonly")
  }, /*#__PURE__*/React.createElement("input", {
    ref: inputRef,
    type: "date",
    className: "field-input field-input--date",
    value: value,
    onChange: event => onChange(event.target.value),
    onClick: openPicker,
    disabled: disabled
  }), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "field-shell-button",
    onClick: openPicker,
    disabled: disabled,
    "aria-label": `${label}日历`
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "calendar_month"))));
}
function AppWindowChrome({
  active
}) {
  const [closing, setClosing] = useState(false);
  const [minimizing, setMinimizing] = useState(false);
  const [maximizing, setMaximizing] = useState(false);
  const activeItem = UI_COPY.navigation.find(item => item.key === active);
  async function handleMinimize() {
    if (minimizing) return;
    setMinimizing(true);
    try {
      const result = await callApi("minimize_window");
      if (!result || !result.success) {
        throw new Error(result && result.message || UI_COPY.shell.minimizeFailed);
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
        throw new Error(result && result.message || UI_COPY.shell.maximizeFailed);
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
        throw new Error(result && result.message || UI_COPY.shell.closeFailed);
      }
    } catch (error) {
      setClosing(false);
      window.alert(error.message || UI_COPY.shell.closeFailed);
    }
  }
  return /*#__PURE__*/React.createElement("div", {
    className: "window-chrome"
  }, /*#__PURE__*/React.createElement("div", {
    className: "window-drag-region"
  }, /*#__PURE__*/React.createElement("div", {
    className: "window-title-stack"
  }, /*#__PURE__*/React.createElement("span", {
    className: "window-title"
  }, APP_BRAND.name), /*#__PURE__*/React.createElement("span", {
    className: "window-subtitle"
  }, activeItem && activeItem.label || UI_COPY.shell.windowSubtitle))), /*#__PURE__*/React.createElement("div", {
    className: "window-controls"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "window-traffic-button window-traffic-button--minimize",
    onClick: handleMinimize,
    disabled: minimizing || maximizing || closing,
    "aria-label": minimizing ? UI_COPY.shell.minimizing : UI_COPY.shell.minimize,
    title: minimizing ? UI_COPY.shell.minimizing : UI_COPY.shell.minimize
  }, /*#__PURE__*/React.createElement("span", {
    className: "window-traffic-button__glyph"
  })), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "window-traffic-button window-traffic-button--maximize",
    onClick: handleMaximize,
    disabled: minimizing || maximizing || closing,
    "aria-label": maximizing ? UI_COPY.shell.maximizing : UI_COPY.shell.maximize,
    title: maximizing ? UI_COPY.shell.maximizing : UI_COPY.shell.maximize
  }, /*#__PURE__*/React.createElement("span", {
    className: "window-traffic-button__glyph"
  })), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "window-traffic-button window-traffic-button--close",
    onClick: handleClose,
    disabled: minimizing || maximizing || closing,
    "aria-label": closing ? UI_COPY.shell.closing : UI_COPY.shell.close,
    title: closing ? UI_COPY.shell.closing : UI_COPY.shell.close
  }, /*#__PURE__*/React.createElement("span", {
    className: "window-traffic-button__glyph"
  }))));
}
function AppShell({
  active,
  onOpenDisclaimer,
  children,
  footerLeft,
  footerRight,
  contentClassName = "",
  contentScrollable = true
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "app-shell"
  }, /*#__PURE__*/React.createElement(Sidebar, {
    active: active,
    onOpenDisclaimer: onOpenDisclaimer
  }), /*#__PURE__*/React.createElement("main", {
    className: "app-main"
  }, /*#__PURE__*/React.createElement(AppWindowChrome, {
    active: active
  }), /*#__PURE__*/React.createElement("div", {
    className: joinClasses("page-scroll", !contentScrollable && "page-scroll--locked", contentClassName)
  }, children), /*#__PURE__*/React.createElement(PageFooter, {
    left: footerLeft,
    right: footerRight
  })));
}
function BootstrapStatePage({
  active,
  onOpenDisclaimer,
  eyebrow,
  title,
  description,
  tone,
  message,
  footerText
}) {
  return /*#__PURE__*/React.createElement(AppShell, {
    active: active,
    onOpenDisclaimer: onOpenDisclaimer,
    footerRight: /*#__PURE__*/React.createElement("p", {
      className: "footer-meta"
    }, footerText)
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-wrap page-wrap--narrow"
  }, /*#__PURE__*/React.createElement(PageHeader, {
    eyebrow: eyebrow,
    title: title,
    description: description
  }), /*#__PURE__*/React.createElement(NoticeBox, {
    tone: tone
  }, message)));
}
function SummaryField({
  span = 6,
  label,
  value,
  helper,
  icon,
  tone = "",
  mono = false,
  truncate = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: joinClasses("summary-item", tone),
    style: {
      gridColumn: `span ${span} / span ${span}`
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "summary-item__icon"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, icon)), /*#__PURE__*/React.createElement("div", {
    className: "summary-item__copy"
  }, /*#__PURE__*/React.createElement("p", {
    className: "summary-item__label"
  }, label), /*#__PURE__*/React.createElement("p", {
    className: joinClasses("summary-item__value", mono && "u-mono", truncate && "u-truncate")
  }, value), helper ? /*#__PURE__*/React.createElement("p", {
    className: "summary-item__helper"
  }, helper) : null));
}
function DisclaimerDialog({
  open,
  onClose
}) {
  useEffect(() => {
    if (!open) return undefined;
    function handleKeydown(event) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [open, onClose]);
  if (!open) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "modal-overlay",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("div", {
    className: "modal-card",
    onClick: event => event.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "modal-head"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    className: "page-eyebrow",
    style: {
      marginBottom: 10
    }
  }, "\u514D\u8D23\u58F0\u660E"), /*#__PURE__*/React.createElement("h2", {
    className: "page-title",
    style: {
      fontSize: 28
    }
  }, "\u4F7F\u7528\u524D\u8BF7\u786E\u8BA4\u4EE5\u4E0B\u4E8B\u9879")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "close"))), /*#__PURE__*/React.createElement("div", {
    className: "modal-body"
  }, /*#__PURE__*/React.createElement("section", {
    className: "modal-section"
  }, /*#__PURE__*/React.createElement("p", {
    className: "modal-label"
  }, "\u8F6F\u4EF6\u8BF4\u660E"), /*#__PURE__*/React.createElement("ul", {
    className: "modal-list"
  }, DISCLAIMER_SOFTWARE_ITEMS.map(item => /*#__PURE__*/React.createElement("li", {
    key: item
  }, item)))), /*#__PURE__*/React.createElement("section", {
    className: "modal-section"
  }, /*#__PURE__*/React.createElement("p", {
    className: "modal-label"
  }, "\u98CE\u9669\u63D0\u793A"), /*#__PURE__*/React.createElement("ul", {
    className: "modal-list"
  }, DISCLAIMER_ITEMS.map(item => /*#__PURE__*/React.createElement("li", {
    key: item
  }, item))))), /*#__PURE__*/React.createElement("div", {
    className: "modal-footer"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--primary",
    onClick: onClose
  }, "\u6211\u5DF2\u77E5\u6653"))));
}
function Sidebar({
  active,
  onOpenDisclaimer
}) {
  const navigate = useNavigate();
  const githubUrl = APP_VISIBLE_COPY.githubUrl;
  return /*#__PURE__*/React.createElement("aside", {
    className: "app-sidebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sidebar-top"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sidebar-logo"
  }, "IF"), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    className: "sidebar-title"
  }, APP_BRAND.name), /*#__PURE__*/React.createElement("p", {
    className: "sidebar-subtitle"
  }, APP_VISIBLE_COPY.topSubtitle))), /*#__PURE__*/React.createElement("nav", {
    className: "sidebar-nav"
  }, UI_COPY.navigation.map(item => /*#__PURE__*/React.createElement("button", {
    key: item.key,
    type: "button",
    className: joinClasses("sidebar-nav__item", active === item.key && "is-active"),
    onClick: () => navigate(item.path)
  }, /*#__PURE__*/React.createElement("span", {
    className: "sidebar-nav__item-icon material-symbols-outlined"
  }, item.icon), /*#__PURE__*/React.createElement("span", {
    className: "sidebar-nav__item-copy"
  }, /*#__PURE__*/React.createElement("strong", null, item.label), /*#__PURE__*/React.createElement("span", null, item.description))))), /*#__PURE__*/React.createElement("div", {
    className: "sidebar-footer"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "sidebar-foot-button",
    onClick: () => navigate("/")
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "restart_alt"), /*#__PURE__*/React.createElement("span", {
    className: "sidebar-foot-button__label"
  }, "\u56DE\u5230\u9996\u9875")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "sidebar-foot-button",
    onClick: onOpenDisclaimer
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "balance"), /*#__PURE__*/React.createElement("span", {
    className: "sidebar-foot-button__label"
  }, "\u514D\u8D23\u58F0\u660E")), /*#__PURE__*/React.createElement("div", {
    className: "sidebar-link-row"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "sidebar-foot-chip sidebar-foot-chip--single",
    onClick: () => openExternalUrl(githubUrl)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "code"), /*#__PURE__*/React.createElement("span", null, APP_VISIBLE_COPY.githubLabel))), /*#__PURE__*/React.createElement("div", {
    className: "sidebar-brand"
  }, /*#__PURE__*/React.createElement("span", {
    className: "sidebar-brand__dot"
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    className: "sidebar-brand__name"
  }, APP_VISIBLE_COPY.footerVersion), /*#__PURE__*/React.createElement("p", {
    className: "sidebar-brand__sub"
  }, APP_VISIBLE_COPY.footerStamp)))));
}
function SettingsPage({
  onOpenDisclaimer
}) {
  const navigate = useNavigate();
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [runSettings, setRunSettings] = useState(DEFAULT_RUN_SETTINGS);
  const [runContext, setRunContext] = useState({
    controlled_run: false,
    explicit_run_context: false
  });
  const [showAuthCode, setShowAuthCode] = useState(false);
  const [pageError, setPageError] = useState("");
  const [emailStatus, setEmailStatus] = useState({
    status: "idle",
    message: ""
  });
  const [bootstrapState, setBootstrapState] = useState("bootstrapping");
  const [bootstrapError, setBootstrapError] = useState("");
  const [starting, setStarting] = useState(false);
  const [rulesStatus, setRulesStatus] = useState({});
  const saveTimerRef = useRef(null);
  const autostartTimerRef = useRef(null);
  const autostartTriggeredRef = useRef(false);
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const state = await loadShellState();
        if (!active) return;
        setSettings(state.settings);
        setRunSettings(state.runSettings);
        setRunContext(state.runContext);
        setRulesStatus(state.rulesStatus || {});
        setBootstrapError("");
        setBootstrapState("bootstrapped");
      } catch (error) {
        if (active) {
          setBootstrapError(error.message || "初始化设置失败，请重启应用。");
          setBootstrapState("bootstrap_failed");
        }
      }
    })();
    return () => {
      active = false;
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      if (autostartTimerRef.current) clearTimeout(autostartTimerRef.current);
    };
  }, []);
  useEffect(() => {
    if (bootstrapState !== "bootstrapped") return undefined;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      persistUserSettings(settings, runSettings, runContext).catch(error => {
        console.error("Failed to save settings", error);
      });
    }, 400);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [bootstrapState, settings, runSettings, runContext]);
  const controlledRun = hasExplicitQaRunContext(runContext);
  const taskMode = normalizeTaskMode(settings.task_mode);
  const isMailMode = taskMode === "mail";
  const isFetchMode = taskMode === "fetch";
  const isLocalMode = taskMode === "local";
  const localInputDir = String(settings.local_input_dir || "").trim();
  const localOutputDir = String(settings.local_output_dir || "").trim();
  const localSplitByCategory = settings.local_split_by_category !== false;
  const activeTaskMode = TASK_MODE_OPTIONS.find(option => option.value === taskMode) || TASK_MODE_OPTIONS[0];
  const emailParts = splitEmailAddress(settings.email);
  const dateError = validateDateRange(runSettings.date_from, runSettings.date_to);
  const startButtonLabel = isLocalMode ? "开始整理" : isFetchMode ? "开始提取" : "开始处理";
  const startButtonIcon = "play_arrow";
  const canStart = isLocalMode ? !!localInputDir : !validateEmail(settings.email) && !!settings.auth_code && (isFetchMode || !!String(settings.company || "").trim()) && !!String(settings.save_path || "").trim() && !dateError;
  const rulesIssues = normalizeRuleIssues(rulesStatus && rulesStatus.issues);
  const rulesLibraryAvailable = !!(rulesStatus && rulesStatus.library_available);
  useEffect(() => {
    if (bootstrapState !== "bootstrapped" || starting || autostartTriggeredRef.current || !shouldAutostartControlledRun(runContext)) return undefined;
    if (isControlledAutostartConsumed(runContext)) {
      autostartTriggeredRef.current = true;
      return undefined;
    }
    const delayMs = Math.max(0, Number(runContext.autostart_delay_ms || 0));
    autostartTimerRef.current = setTimeout(() => {
      autostartTriggeredRef.current = true;
      markControlledAutostartConsumed(runContext);
      handleStart();
    }, delayMs);
    return () => {
      if (autostartTimerRef.current) clearTimeout(autostartTimerRef.current);
    };
  }, [bootstrapState, runContext, starting, settings, runSettings]);
  function updateSetting(key, value) {
    setSettings(current => ({
      ...current,
      [key]: value
    }));
    setPageError("");
    if (key === "email" || key === "auth_code") setEmailStatus({
      status: "idle",
      message: ""
    });
  }
  function setDateValue(field, value) {
    setRunSettings(current => ({
      ...current,
      [field]: value,
      quick_range: "custom"
    }));
    setPageError("");
  }
  async function handleChooseDirectory() {
    if (controlledRun) return;
    try {
      const result = await callApi("choose_directory");
      if (result && result.success && result.path) updateSetting("save_path", result.path);
    } catch (error) {
      setPageError(error.message || "选择目录失败。");
    }
  }
  async function handleChooseInputDirectory() {
    try {
      const result = await callApi("choose_directory");
      if (result && result.success && result.path) updateSetting("local_input_dir", result.path);
    } catch (error) {
      setPageError(error.message || "选择文件夹失败。");
    }
  }
  async function handleChooseLocalOutputDirectory() {
    if (controlledRun) return;
    try {
      const result = await callApi("choose_directory");
      if (result && result.success && result.path) updateSetting("local_output_dir", result.path);
    } catch (error) {
      setPageError(error.message || "选择目录失败。");
    }
  }
  function handleResetLocalOutputDirectory() {
    if (controlledRun) return;
    updateSetting("local_output_dir", "");
  }
  async function handleTestConnection() {
    const emailError = validateEmail(settings.email);
    if (emailError) {
      setEmailStatus({
        status: "error",
        message: emailError
      });
      return;
    }
    if (!settings.auth_code) {
      setEmailStatus({
        status: "error",
        message: "请输入邮箱授权码。"
      });
      return;
    }
    setEmailStatus({
      status: "testing",
      message: "正在测试邮箱连接..."
    });
    try {
      const result = await callApi("test_connection", String(settings.email).trim(), String(settings.auth_code).trim());
      setEmailStatus({
        status: result && result.success ? "success" : "error",
        message: result && result.message ? result.message : "邮箱连接测试失败。"
      });
    } catch (error) {
      setEmailStatus({
        status: "error",
        message: error.message || "邮箱连接测试失败。"
      });
    }
  }
  async function handleStart() {
    if (isLocalMode) {
      const inputDir = String(settings.local_input_dir || "").trim();
      if (!inputDir) return setPageError("请选择要整理的本地文件夹。");
      const outputDir = String(settings.local_output_dir || "").trim() || inputDir;
      setStarting(true);
      try {
        await persistUserSettings(settings, runSettings, runContext);
        const result = await callApi("start_local_organize", inputDir, outputDir, false, localSplitByCategory);
        if (!result || !result.success) {
          setPageError(result && result.message ? result.message : "任务启动失败。");
          return;
        }
        navigate("/processing");
      } catch (error) {
        setPageError(error.message || "任务启动失败。");
      } finally {
        setStarting(false);
      }
      return;
    }
    const emailError = validateEmail(settings.email);
    if (emailError) return setPageError(emailError);
    if (!settings.auth_code) return setPageError("请输入邮箱授权码。");
    if (isMailMode && (!settings.company || !settings.company.trim())) return setPageError("请填写公司名称。");
    if (!settings.save_path) return setPageError("请选择输出目录。");
    if (dateError) return setPageError(dateError);
    setStarting(true);
    try {
      await persistUserSettings(settings, runSettings, runContext);
      const result = isFetchMode ? await callApi("start_fetch_only", settings.save_path, runSettings.date_from, runSettings.date_to, String(settings.email).trim(), settings.auth_code) : await callApi("start_processing", "", settings.save_path, runSettings.date_from, runSettings.date_to, String(settings.email).trim(), settings.auth_code);
      if (!result || !result.success) {
        setPageError(result && result.message ? result.message : "任务启动失败。");
        return;
      }
      navigate("/processing");
    } catch (error) {
      setPageError(error.message || "任务启动失败。");
    } finally {
      setStarting(false);
    }
  }
  if (bootstrapState === "bootstrapping") {
    return /*#__PURE__*/React.createElement(BootstrapStatePage, {
      active: "settings",
      onOpenDisclaimer: onOpenDisclaimer,
      eyebrow: UI_COPY.pages.settings.eyebrow,
      title: UI_COPY.pages.settings.bootstrapTitle,
      description: UI_COPY.pages.settings.bootstrapDescription,
      tone: "info",
      message: UI_COPY.pages.settings.bootstrapMessage,
      footerText: UI_COPY.pages.settings.footerText
    });
  }
  if (bootstrapState === "bootstrap_failed") {
    return /*#__PURE__*/React.createElement(BootstrapStatePage, {
      active: "settings",
      onOpenDisclaimer: onOpenDisclaimer,
      eyebrow: UI_COPY.pages.settings.eyebrow,
      title: UI_COPY.pages.settings.bootstrapTitle,
      description: UI_COPY.pages.settings.errorDescription,
      tone: "error",
      message: bootstrapError || "初始化设置失败，请重启应用。",
      footerText: UI_COPY.pages.settings.footerText
    });
  }
  return /*#__PURE__*/React.createElement(AppShell, {
    active: "settings",
    onOpenDisclaimer: onOpenDisclaimer,
    footerLeft: /*#__PURE__*/React.createElement("label", {
      className: "toggle-row"
    }, /*#__PURE__*/React.createElement("input", {
      type: "checkbox",
      checked: settings.remember_settings !== false,
      onChange: event => updateSetting("remember_settings", event.target.checked)
    }), /*#__PURE__*/React.createElement("span", null, "\u81EA\u52A8\u8BB0\u4F4F\u5F53\u524D\u914D\u7F6E")),
    footerRight: /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn btn--primary",
      onClick: handleStart,
      disabled: !canStart || starting
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, starting ? "sync" : startButtonIcon), /*#__PURE__*/React.createElement("span", null, starting ? "启动中..." : startButtonLabel))
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-wrap page-wrap--settings"
  }, /*#__PURE__*/React.createElement(PageHeader, {
    eyebrow: UI_COPY.pages.settings.eyebrow,
    title: UI_COPY.pages.settings.title,
    badge: controlledRun ? /*#__PURE__*/React.createElement(StatusPill, {
      tone: "info",
      icon: "lock_clock"
    }, "\u53D7\u63A7\u524D\u7AEF\u590D\u8DD1") : null
  }), pageError ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "error"
  }, pageError) : null, controlledRun ? /*#__PURE__*/React.createElement("p", {
    className: "page-inline-note"
  }, UI_COPY.pages.settings.controlledNotice) : null, /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "category",
    title: "\u4EFB\u52A1\u7C7B\u578B",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "info",
      icon: isLocalMode ? "offline_bolt" : isFetchMode ? "inbox" : "mail"
    }, activeTaskMode.badge)
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "quick-range",
    role: "group",
    "aria-label": "\u4EFB\u52A1\u7C7B\u578B"
  }, TASK_MODE_OPTIONS.map(option => /*#__PURE__*/React.createElement("button", {
    key: option.value,
    type: "button",
    className: joinClasses("quick-chip", taskMode === option.value && "is-active"),
    "aria-pressed": taskMode === option.value,
    onClick: () => updateSetting("task_mode", option.value)
  }, option.label))), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, activeTaskMode.description))), /*#__PURE__*/React.createElement("div", {
    className: "settings-grid settings-grid--fit"
  }, /*#__PURE__*/React.createElement("div", {
    className: "settings-column"
  }, isLocalMode ? /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "folder_open",
    title: "\u53D1\u7968\u6587\u4EF6\u5939",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: settings.local_input_dir ? "success" : "warning",
      icon: "folder"
    }, settings.local_input_dir ? "已选择" : "待选择")
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: joinClasses("field-shell", "field-shell--readonly", !settings.local_input_dir && "field-shell--error")
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-icon material-symbols-outlined"
  }, "folder"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    readOnly: true,
    className: "field-input u-mono",
    value: settings.local_input_dir || "",
    placeholder: "\u8BF7\u9009\u62E9\u8981\u6574\u7406\u7684\u672C\u5730\u6587\u4EF6\u5939",
    title: settings.local_input_dir || ""
  })), /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--secondary btn--sm",
    onClick: handleChooseInputDirectory
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "folder_open"), /*#__PURE__*/React.createElement("span", null, "\u9009\u62E9\u6587\u4EF6\u5939"))), /*#__PURE__*/React.createElement("label", {
    className: "toggle-row"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: localSplitByCategory,
    onChange: event => updateSetting("local_split_by_category", event.target.checked),
    disabled: controlledRun
  }), /*#__PURE__*/React.createElement("span", null, "\u6309\u5206\u7C7B\u5206\u76EE\u5F55")), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, localSplitByCategory ? "按发票类型建立 餐饮/充电 等子目录归档；原件按原文件名原样保留在「整理前发票」文件夹（不改名、不分月份），重复件与待人工复核单独存放。" : "不建分类子目录：整理后的发票直接放在该文件夹里，文件名仍带类型；原件按原文件名原样保留在「整理前发票」文件夹（不改名、不分月份），重复件与待人工复核单独存放。"), /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--primary btn--sm",
    onClick: handleStart,
    disabled: !canStart || starting
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, starting ? "sync" : "play_arrow"), /*#__PURE__*/React.createElement("span", null, starting ? "启动中..." : "整理进目录"))), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u70B9\u51FB\u300C\u6574\u7406\u8FDB\u76EE\u5F55\u300D\u6216\u5E95\u90E8\u300C\u5F00\u59CB\u6574\u7406\u300D\u540E\uFF0C\u53D1\u7968\u4F1A\u5728\u8BE5\u6587\u4EF6\u5939\u5185\u6309\u5F53\u524D\u9009\u9879\u79BB\u7EBF\u8BC6\u522B\u5E76\u5F52\u6863\uFF1B\u539F\u4EF6\u6309\u539F\u6587\u4EF6\u540D\u539F\u6837\u4FDD\u7559\u5728\u300C\u6574\u7406\u524D\u53D1\u7968\u300D\u6587\u4EF6\u5939\uFF08\u4E0D\u6539\u540D\u3001\u4E0D\u5206\u6708\u4EFD\uFF09\u3002"))) : /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "mail",
    title: "\u90AE\u7BB1\u6E90\u914D\u7F6E",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "warning",
      icon: "mail"
    }, "\u5F85\u786E\u8BA4")
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u90AE\u7BB1\u5730\u5740"), /*#__PURE__*/React.createElement("div", {
    className: "field-row"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-shell",
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-icon material-symbols-outlined"
  }, "alternate_email"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "field-input",
    placeholder: "\u90AE\u7BB1\u7528\u6237\u540D",
    value: emailParts.username,
    onChange: event => {
      const username = event.target.value.replace(/@/g, "");
      updateSetting("email", username ? `${username}@${emailParts.domain}` : "");
    }
  })), /*#__PURE__*/React.createElement("span", {
    className: "u-text-muted"
  }, "@"), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 136
    }
  }, /*#__PURE__*/React.createElement(DarkSelect, {
    value: emailParts.domain,
    options: EMAIL_DOMAIN_OPTIONS,
    ariaLabel: "\u90AE\u7BB1\u57DF\u540D",
    onChange: domain => updateSetting("email", emailParts.username ? `${emailParts.username}@${domain}` : "")
  }))), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u5F53\u524D\u652F\u6301 QQ\u3001163 \u4E0E 88 \u90AE\u7BB1\uFF0C\u57DF\u540D\u4F1A\u51B3\u5B9A\u90AE\u7BB1\u7684\u8FDE\u63A5\u65B9\u5F0F\u3002")), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u6388\u6743\u7801"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-icon material-symbols-outlined"
  }, "key"), /*#__PURE__*/React.createElement("input", {
    type: showAuthCode ? "text" : "password",
    className: "field-input u-mono",
    placeholder: "\u8BF7\u8F93\u5165\u90AE\u7BB1\u6388\u6743\u7801",
    value: settings.auth_code,
    onChange: event => updateSetting("auth_code", event.target.value)
  }), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "field-mask-toggle",
    onClick: () => setShowAuthCode(current => !current)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, showAuthCode ? "visibility" : "visibility_off"))), /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--secondary btn--sm",
    onClick: handleTestConnection,
    disabled: emailStatus.status === "testing"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, emailStatus.status === "testing" ? "sync" : "link"), /*#__PURE__*/React.createElement("span", null, emailStatus.status === "testing" ? "测试中..." : "测试邮箱连接"))), emailStatus.status !== "idle" ? /*#__PURE__*/React.createElement(InlineStatus, {
    tone: toneFromAsyncStatus(emailStatus.status)
  }, emailStatus.message) : null))), /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "folder_open",
    title: "\u8F93\u51FA\u76EE\u5F55\u8BBE\u7F6E",
    indicator: controlledRun ? /*#__PURE__*/React.createElement(StatusPill, {
      tone: "info",
      icon: "lock"
    }, "\u5DF2\u9501\u5B9A") : isLocalMode ? "默认同发票文件夹" : isFetchMode ? "保存提取附件" : "保存原件与结果"
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: joinClasses("field-shell", "field-shell--readonly", isLocalMode ? !localInputDir && "field-shell--error" : !settings.save_path && "field-shell--error")
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-icon material-symbols-outlined"
  }, "folder"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    readOnly: true,
    className: "field-input u-mono",
    value: isLocalMode ? localOutputDir || localInputDir : settings.save_path,
    placeholder: isLocalMode ? "默认与发票文件夹相同" : "请选择本地输出目录",
    title: isLocalMode ? localOutputDir || localInputDir : settings.save_path
  })), /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--secondary btn--sm",
    onClick: isLocalMode ? handleChooseLocalOutputDirectory : handleChooseDirectory,
    disabled: controlledRun
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "folder_open"), /*#__PURE__*/React.createElement("span", null, controlledRun ? "路径已锁定" : "浏览目录")), isLocalMode && !controlledRun && localOutputDir ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: handleResetLocalOutputDirectory
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "undo"), /*#__PURE__*/React.createElement("span", null, "\u6062\u590D\u9ED8\u8BA4\uFF08\u53D1\u7968\u6587\u4EF6\u5939\uFF09")) : null), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, controlledRun ? "当前为受控前端复跑，本轮输出目录由诊断上下文锁定。" : isLocalMode ? localSplitByCategory ? "默认与发票文件夹相同：分类文件、「整理前发票」中的原件与结果明细都会写入该文件夹；改为其他目录时仅复制归档副本，原件留在发票文件夹不动。" : "默认与发票文件夹相同：整理后的文件、「整理前发票」中的原件与结果明细都会写入该文件夹；改为其他目录时仅复制归档副本，原件留在发票文件夹不动。" : isFetchMode ? "邮箱附件会保存到该目录下的 inbox 文件夹，并生成清单文件。" : "系统会在此目录下按发票类型保存归档文件，并生成待人工复核目录。")))), /*#__PURE__*/React.createElement("div", {
    className: "settings-column"
  }, /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "memory",
    title: "\u672C\u5730\u8BC6\u522B\u5F15\u64CE",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "success",
      icon: "offline_bolt"
    }, "\u79BB\u7EBF\u8FD0\u884C")
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "engine-list"
  }, LOCAL_ENGINE_ITEMS.map(item => /*#__PURE__*/React.createElement("div", {
    className: "engine-item",
    key: item.key
  }, /*#__PURE__*/React.createElement("span", {
    className: "engine-item__icon material-symbols-outlined"
  }, item.icon), /*#__PURE__*/React.createElement("div", {
    className: "engine-item__copy"
  }, /*#__PURE__*/React.createElement("strong", null, item.title), /*#__PURE__*/React.createElement("span", null, item.description)), /*#__PURE__*/React.createElement("span", {
    className: "engine-item__tag"
  }, "\u5185\u7F6E")))), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u65E0\u9700\u8054\u7F51\u3001\u65E0\u9700\u586B\u5199\u5BC6\u94A5\uFF0C\u652F\u6301\u7535\u5B50\u53D1\u7968\u3001OFD \u7248\u5F0F\u6587\u4EF6\u4E0E\u626B\u63CF\u4EF6\u7684\u672C\u5730\u89E3\u6790\uFF0C\u7968\u636E\u5185\u5BB9\u4E0D\u4F1A\u4E0A\u4F20\u3002"))), /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "rule",
    title: "\u8D39\u7528\u5F52\u7C7B\u89C4\u5219",
    indicator: rulesIssues.length > 0 ? /*#__PURE__*/React.createElement(StatusPill, {
      tone: "warning",
      icon: "warning"
    }, `${rulesIssues.length} 条提示`) : /*#__PURE__*/React.createElement(StatusPill, {
      tone: "success",
      icon: "rule"
    }, rulesLibraryAvailable ? "含发票库规则" : "使用全局规则")
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u6309\u76EE\u6807\u7968\u79CD\u3001\u5173\u952E\u8BCD\u4E0E\u91D1\u989D\u8303\u56F4\u751F\u6210\u5F52\u6863\u6587\u4EF6\u5939\uFF1B\u4FDD\u5B58\u540E\u7684\u89C4\u5219\u5728\u4E0B\u4E00\u6B21\u6574\u7406\u65F6\u751F\u6548\u3002"), rulesIssues.length > 0 ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-issues"
  }, /*#__PURE__*/React.createElement("p", {
    className: "rule-issues__title"
  }, "\u5F52\u7C7B\u89C4\u5219\u914D\u7F6E\u9700\u8981\u786E\u8BA4"), /*#__PURE__*/React.createElement("ul", {
    className: "rule-issue-list"
  }, rulesIssues.slice(0, 3).map((issue, index) => /*#__PURE__*/React.createElement("li", {
    key: `${issue.text}-${index}`,
    className: "rule-issue-item"
  }, issue.text))), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u8BF7\u8FDB\u5165\u5F52\u7C7B\u89C4\u5219\u9875\u4FEE\u6B63\uFF0C\u6216\u5728\u89C4\u5219\u76EE\u5F55\u4E2D\u76F4\u63A5\u7F16\u8F91\u89C4\u5219\u6587\u4EF6\u3002"))) : null, /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--secondary btn--sm",
    onClick: () => navigate("/rules")
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "rule"), /*#__PURE__*/React.createElement("span", null, "\u7BA1\u7406\u5F52\u7C7B\u89C4\u5219"))))), isLocalMode ? null : /*#__PURE__*/React.createElement("section", {
    className: "surface-card surface-card--compact settings-date-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "calendar_month",
    title: "\u63D0\u53D6\u65F6\u95F4\u8303\u56F4",
    indicator: controlledRun ? /*#__PURE__*/React.createElement(StatusPill, {
      tone: "info",
      icon: "lock"
    }, "\u5DF2\u9501\u5B9A") : null
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-row field-row--dates settings-date-row"
  }, /*#__PURE__*/React.createElement(DateField, {
    label: "\u5F00\u59CB\u65E5\u671F",
    value: runSettings.date_from,
    onChange: value => setDateValue("date_from", value),
    disabled: controlledRun
  }), /*#__PURE__*/React.createElement("span", {
    className: "field-separator"
  }, "\u2014"), /*#__PURE__*/React.createElement(DateField, {
    label: "\u7ED3\u675F\u65E5\u671F",
    value: runSettings.date_to,
    onChange: value => setDateValue("date_to", value),
    disabled: controlledRun
  })), controlledRun ? /*#__PURE__*/React.createElement("p", {
    className: "field-help field-help--subtle"
  }, "\u5F53\u524D\u4E3A\u53D7\u63A7\u590D\u8DD1\uFF0C\u65E5\u671F\u8303\u56F4\u5DF2\u6309\u4E0A\u4E0B\u6587\u9501\u5B9A\u3002") : /*#__PURE__*/React.createElement("p", {
    className: "field-help field-help--subtle"
  }, "\u786E\u8BA4\u8D77\u6B62\u65E5\u671F\u540E\u53EF\u76F4\u63A5\u5F00\u59CB\u63D0\u53D6\uFF0C\u672C\u9875\u4E0D\u518D\u8FDB\u5165\u72EC\u7ACB\u786E\u8BA4\u6D41\u7A0B\u3002"))), isMailMode ? /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "business",
    title: "\u516C\u53F8\u914D\u7F6E",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: settings.company && settings.company.trim() ? "success" : "warning",
      icon: "apartment"
    }, "\u8D2D\u4E70\u65B9\u6821\u9A8C")
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u516C\u53F8 ", /*#__PURE__*/React.createElement("span", {
    className: "field-required"
  }, "*")), /*#__PURE__*/React.createElement("div", {
    className: joinClasses("field-shell", !settings.company || !settings.company.trim() ? "field-shell--error" : "")
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-icon material-symbols-outlined"
  }, "domain"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "field-input",
    placeholder: "\u586B\u5199\u7528\u4E8E\u5339\u914D\u8D2D\u4E70\u65B9\u7684\u516C\u53F8\u540D\u79F0",
    value: settings.company || "",
    onChange: event => updateSetting("company", event.target.value)
  })), !settings.company || !settings.company.trim() ? /*#__PURE__*/React.createElement("p", {
    className: "field-help field-help--subtle"
  }, "\u586B\u5199\u516C\u53F8\u540D\u79F0\u540E\u6309\u8D2D\u4E70\u65B9\u5B57\u6BB5\u5339\u914D\u3002") : /*#__PURE__*/React.createElement("p", {
    className: "field-help field-help--subtle"
  }, "\u6309\u8D2D\u4E70\u65B9\u5305\u542B\u201C", settings.company.trim(), "\u201D\u8FDB\u884C\u5339\u914D\uFF1B\u660E\u786E\u4E0D\u5339\u914D\u7684\u7968\u636E\u4F1A\u5355\u72EC\u8FDB\u5165\u201C\u975E\u76EE\u6807\u516C\u53F8\u53D1\u7968\u201D\u3002")))) : null))));
}
function ProcessingPage({
  onOpenDisclaimer
}) {
  const navigate = useNavigate();
  const [progressState, setProgressState] = useState(DEFAULT_PROGRESS);
  const redirectRef = useRef(false);
  const terminalBodyRef = useRef(null);
  useEffect(() => {
    let active = true;
    let timer = null;
    const poll = async () => {
      try {
        const data = await callApi("get_progress");
        if (!active || !data) return;
        setProgressState({
          ...DEFAULT_PROGRESS,
          ...data,
          stats: Object.assign({}, DEFAULT_PROGRESS.stats, data.stats || {})
        });
        if (!redirectRef.current && ["completed", "failed"].includes(data.run_state) && !data.is_running) {
          redirectRef.current = true;
          setTimeout(() => navigate("/analysis"), 1200);
        }
      } catch (error) {
        if (active) setProgressState(current => ({
          ...current,
          last_error: error.message || "获取进度失败。"
        }));
      }
    };
    poll();
    timer = setInterval(poll, 1000);
    return () => {
      active = false;
      if (timer) clearInterval(timer);
    };
  }, [navigate]);
  async function handleStop() {
    if (!progressState.can_stop) return;
    try {
      const result = await callApi("stop_processing");
      if (!result || !result.success) window.alert(result && result.message ? result.message : "停止指令发送失败。");
    } catch (error) {
      window.alert(error.message || "停止指令发送失败。");
    }
  }
  const stats = progressState.stats || DEFAULT_PROGRESS.stats;
  const logs = progressState.logs || [];
  const taskMode = normalizeTaskMode(progressState.task_mode);
  const isLocalTask = taskMode === "local";
  const statusTone = progressState.run_state === "failed" ? "error" : progressState.run_state === "completed" ? "success" : progressState.is_running ? "info" : "neutral";
  const statusLabel = progressState.run_state === "failed" ? "处理失败" : progressState.run_state === "completed" ? "处理完成" : progressState.is_running ? "实时连接已建立" : UI_COPY.pages.processing.statusWaiting;
  const processingDetail = progressState.stop_requested ? UI_COPY.pages.processing.stopDetail : taskMode === "fetch" ? UI_COPY.pages.processing.processingDetailFetch : isLocalTask ? UI_COPY.pages.processing.processingDetailLocal : UI_COPY.pages.processing.processingDetail;
  useEffect(() => {
    if (!terminalBodyRef.current) return;
    terminalBodyRef.current.scrollTop = terminalBodyRef.current.scrollHeight;
  }, [logs, progressState.is_running, progressState.stop_requested]);
  return /*#__PURE__*/React.createElement(AppShell, {
    active: "processing",
    onOpenDisclaimer: onOpenDisclaimer,
    contentScrollable: false,
    footerLeft: /*#__PURE__*/React.createElement("p", {
      className: "footer-meta"
    }, UI_COPY.pages.processing.closeHint),
    footerRight: /*#__PURE__*/React.createElement(StatusPill, {
      tone: statusTone,
      icon: progressState.is_running ? "radar" : "schedule"
    }, statusLabel)
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-wrap page-wrap--processing"
  }, /*#__PURE__*/React.createElement(PageHeader, {
    eyebrow: UI_COPY.pages.processing.eyebrow,
    title: UI_COPY.pages.processing.title
  }), /*#__PURE__*/React.createElement("section", {
    className: "surface-card surface-card--hero"
  }, /*#__PURE__*/React.createElement("div", {
    className: "progress-hero"
  }, /*#__PURE__*/React.createElement("div", {
    className: "progress-main"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    className: "progress-kicker"
  }, UI_COPY.pages.processing.currentOperation), /*#__PURE__*/React.createElement("h2", {
    className: "progress-title"
  }, progressState.status_text), /*#__PURE__*/React.createElement("p", {
    className: "progress-meta"
  }, processingDetail)), /*#__PURE__*/React.createElement("div", {
    className: "progress-actions"
  }, /*#__PURE__*/React.createElement("div", {
    className: "progress-value"
  }, /*#__PURE__*/React.createElement("strong", {
    className: "u-tabular"
  }, progressState.progress, "%"), /*#__PURE__*/React.createElement("span", null, UI_COPY.pages.processing.progressLabel)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--danger",
    onClick: handleStop,
    disabled: !progressState.can_stop
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, progressState.stop_requested ? "sync" : "close"), /*#__PURE__*/React.createElement("span", null, progressState.stop_requested ? "正在停止..." : "停止运行")))), /*#__PURE__*/React.createElement("div", {
    className: "progress-track"
  }, /*#__PURE__*/React.createElement("div", {
    className: "progress-fill",
    style: {
      width: `${progressState.progress}%`
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "progress-caption"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "sync"), /*#__PURE__*/React.createElement("span", null, progressState.stop_requested ? UI_COPY.pages.processing.stopPending : UI_COPY.pages.processing.liveRefresh)), progressState.last_error && progressState.run_state === "failed" ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "error"
  }, progressState.last_error) : null, progressState.quota_exhausted && progressState.quota_message ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, progressState.quota_message) : null, progressState.stop_requested && progressState.run_state !== "failed" ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, UI_COPY.pages.processing.stopNotice) : null)), /*#__PURE__*/React.createElement("div", {
    className: "metrics-grid"
  }, /*#__PURE__*/React.createElement("div", {
    className: "metric-card metric-card--blue"
  }, /*#__PURE__*/React.createElement("div", {
    className: "metric-card__icon"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, isLocalTask ? "folder_open" : "mail")), /*#__PURE__*/React.createElement("div", {
    className: "metric-card__copy"
  }, /*#__PURE__*/React.createElement("p", {
    className: "metric-card__label"
  }, isLocalTask ? UI_COPY.pages.processing.scanFilesLabel : UI_COPY.pages.processing.scanEmailsLabel), /*#__PURE__*/React.createElement("p", {
    className: "metric-card__value u-tabular"
  }, stats.emails || 0))), /*#__PURE__*/React.createElement("div", {
    className: "metric-card metric-card--green"
  }, /*#__PURE__*/React.createElement("div", {
    className: "metric-card__icon"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "description")), /*#__PURE__*/React.createElement("div", {
    className: "metric-card__copy"
  }, /*#__PURE__*/React.createElement("p", {
    className: "metric-card__label"
  }, "\u5DF2\u8BC6\u522B\u53D1\u7968"), /*#__PURE__*/React.createElement("p", {
    className: "metric-card__value u-tabular"
  }, stats.invoices || 0))), /*#__PURE__*/React.createElement("div", {
    className: "metric-card metric-card--amber"
  }, /*#__PURE__*/React.createElement("div", {
    className: "metric-card__icon"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "warning")), /*#__PURE__*/React.createElement("div", {
    className: "metric-card__copy"
  }, /*#__PURE__*/React.createElement("p", {
    className: "metric-card__label"
  }, "\u5F02\u5E38\u5904\u7406"), /*#__PURE__*/React.createElement("p", {
    className: "metric-card__value u-tabular"
  }, stats.errors || 0)))), /*#__PURE__*/React.createElement("section", {
    className: "surface-card surface-card--terminal processing-terminal",
    style: {
      flex: 1,
      minHeight: 0,
      display: "flex",
      flexDirection: "column"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "terminal-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "terminal-title"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "terminal"), /*#__PURE__*/React.createElement("span", null, "\u5B9E\u65F6\u6267\u884C\u65E5\u5FD7")), /*#__PURE__*/React.createElement("div", {
    className: "terminal-dots"
  }, /*#__PURE__*/React.createElement("span", {
    className: "terminal-dot"
  }), /*#__PURE__*/React.createElement("span", {
    className: "terminal-dot"
  }), /*#__PURE__*/React.createElement("span", {
    className: "terminal-dot"
  }))), /*#__PURE__*/React.createElement("div", {
    ref: terminalBodyRef,
    className: "terminal-body"
  }, /*#__PURE__*/React.createElement("p", {
    className: "terminal-intro"
  }, "-- \u53D1\u7968\u52A9\u624B\u5F15\u64CE\u5DF2\u8FDE\u63A5 --", /*#__PURE__*/React.createElement("br", null), "-- \u8FDB\u5EA6\u4E0E\u65E5\u5FD7\u5B9E\u65F6\u5237\u65B0\u4E2D --"), logs.map((log, index) => /*#__PURE__*/React.createElement("div", {
    key: `${log.time || "log"}-${index}`,
    className: "terminal-line"
  }, /*#__PURE__*/React.createElement("span", {
    className: "terminal-time"
  }, safeText(log.time, "[实时]")), /*#__PURE__*/React.createElement("span", {
    className: resolveLogToneClass(log)
  }, safeText(log.type, "LOG")), /*#__PURE__*/React.createElement("span", {
    className: "terminal-text"
  }, safeText(log.msg, "-")))), progressState.is_running ? /*#__PURE__*/React.createElement("div", {
    className: "terminal-line",
    style: {
      marginTop: 4
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "terminal-time"
  }, "[\u5B9E\u65F6]"), /*#__PURE__*/React.createElement("span", {
    className: "terminal-kind terminal-kind--info"
  }, "\u72B6\u6001"), /*#__PURE__*/React.createElement("span", {
    className: "terminal-text"
  }, progressState.stop_requested ? "正在安全停止..." : "任务持续执行中...", /*#__PURE__*/React.createElement("span", {
    className: "terminal-cursor"
  }))) : null))));
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
    return {
      extension,
      fileKindLabel: extension === ".xml" ? "XML 原件" : extension === ".ofd" ? "OFD 原件" : [".jpg", ".jpeg", ".png"].includes(extension) ? "图片原件" : "PDF 原件"
    };
  }
  if ([".txt", ".url.txt", ".log", ".json"].includes(extension)) {
    return {
      extension,
      fileKindLabel: extension === ".url.txt" ? "链接记录" : "记录文件"
    };
  }
  return {
    extension,
    fileKindLabel: "文件"
  };
}
function normalizeSuccessInvoices(items) {
  return (items || []).map((item, index) => {
    const path = item.path || "";
    const fileMeta = describeResultFile(path);
    return {
      key: path || `${item.date || "row"}-${index}`,
      date: safeText(item.date),
      amount: safeText(item.amount),
      merchant: safeText(item.merchant || item.vendor),
      archiveType: String(item.category || "").trim() || safeText(fileMeta.fileKindLabel),
      path,
      fileName: fileNameFromPath(path)
    };
  });
}
function normalizeGroupedErrors(groups) {
  return (groups || []).map((group, groupIndex) => ({
    key: group.key || `group-${groupIndex}`,
    label: group.key === "retained_record" ? "暂存记录" : group.key === "manual_review" ? "待人工复核" : group.key === "processing_error" ? "真实异常" : group.label || "待处理记录",
    count: Number(group.count || 0),
    items: (group.items || []).map((item, itemIndex) => {
      const path = item.path || "";
      return {
        rowKey: path || `${group.key || "group"}-${itemIndex}`,
        date: safeText(item.date),
        reason: safeText(item.reason, group.label || "待处理"),
        status: safeText(item.status, "待处理"),
        merchant: safeText(item.merchant),
        path,
        fileName: fileNameFromPath(path)
      };
    })
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
function ResultSummaryCard({
  icon,
  label,
  value,
  helper,
  tone = "info"
}) {
  return /*#__PURE__*/React.createElement("section", {
    className: joinClasses("stat-card", `stat-card--${tone}`)
  }, /*#__PURE__*/React.createElement("div", {
    className: "stat-card__top"
  }, /*#__PURE__*/React.createElement("div", {
    className: "stat-card__icon"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, icon)), /*#__PURE__*/React.createElement("div", {
    className: "stat-card__copy"
  }, /*#__PURE__*/React.createElement("p", {
    className: "stat-card__label"
  }, label), /*#__PURE__*/React.createElement("p", {
    className: "stat-card__value u-tabular"
  }, value))), /*#__PURE__*/React.createElement("p", {
    className: "stat-card__helper"
  }, helper));
}
function ResultToolbarButton({
  icon,
  label,
  onClick,
  disabled = false,
  primary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: joinClasses("btn", primary ? "btn--primary" : "btn--secondary", "btn--sm"),
    onClick: onClick,
    disabled: disabled
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, icon), /*#__PURE__*/React.createElement("span", null, label));
}
function ResultActionBanner({
  tone = "warning",
  icon,
  eyebrow,
  title,
  text,
  buttonLabel,
  onClick,
  disabled = false,
  pathText = "",
  chips = null
}) {
  return /*#__PURE__*/React.createElement("section", {
    className: joinClasses("manual-banner", tone === "neutral" && "manual-banner--calm", tone === "neutral" && "manual-banner--output")
  }, /*#__PURE__*/React.createElement("div", {
    className: "manual-banner__lead"
  }, /*#__PURE__*/React.createElement("div", {
    className: "manual-banner__icon"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, icon)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    className: "manual-banner__eyebrow"
  }, eyebrow), /*#__PURE__*/React.createElement("p", {
    className: "manual-banner__title"
  }, title), /*#__PURE__*/React.createElement("p", {
    className: "manual-banner__text"
  }, text), pathText ? /*#__PURE__*/React.createElement("p", {
    className: "manual-banner__path u-mono",
    title: pathText
  }, pathText) : null, chips)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--secondary",
    onClick: onClick,
    disabled: disabled
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, icon), /*#__PURE__*/React.createElement("span", null, buttonLabel)));
}
function RuleIssues({
  issues,
  title = "规则校验未通过",
  tone = "error"
}) {
  const items = normalizeRuleIssues(issues);
  if (items.length === 0) return null;
  return /*#__PURE__*/React.createElement(NoticeBox, {
    tone: tone
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-issues"
  }, /*#__PURE__*/React.createElement("p", {
    className: "rule-issues__title"
  }, title), /*#__PURE__*/React.createElement("ul", {
    className: "rule-issue-list"
  }, items.map((issue, index) => /*#__PURE__*/React.createElement("li", {
    key: `${issue.text}-${index}`,
    className: "rule-issue-item",
    title: ruleLocationTitle(issue.file, issue.line)
  }, issue.text)))));
}
function RuleEditor({
  editor,
  documentTypes,
  onChange,
  onCreateType,
  onCommit,
  onCancel
}) {
  const [creatingType, setCreatingType] = useState(false);
  const [typeName, setTypeName] = useState("");
  const [typeError, setTypeError] = useState("");
  const [typeBusy, setTypeBusy] = useState(false);
  if (!editor) {
    return /*#__PURE__*/React.createElement("div", {
      className: "rules-empty-state"
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, "edit_note"), /*#__PURE__*/React.createElement("p", null, "\u9009\u62E9\u4E00\u6761\u89C4\u5219\u7F16\u8F91\uFF0C\u6216\u65B0\u589E\u4E00\u6761\u89C4\u5219\u3002"));
  }
  const previewFolder = buildRuleFolderName(editor.targetType, buildRuleAmountRange(editor.amountMin, editor.amountMax));
  const typeOptions = [{
    value: "",
    label: "请选择目标票种"
  }].concat(documentTypes.map(type => ({
    value: type,
    label: type
  })));
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
        const issueText = result && Array.isArray(result.issues) && result.issues.length > 0 ? String(result.issues[0].text || result.issues[0].message || "") : "";
        setTypeError(issueText || result && result.message || "新建票种失败，请稍后重试。");
        return;
      }
      setCreatingType(false);
      setTypeName("");
      setTypeError("");
      onChange({
        targetType: String(result.name || name)
      });
    } finally {
      setTypeBusy(false);
    }
  }
  function handleCancelCreateType() {
    setCreatingType(false);
    setTypeName("");
    setTypeError("");
  }
  return /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rules-editor-grid"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-block field-block--wide"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u76EE\u6807\u7968\u79CD ", /*#__PURE__*/React.createElement("span", {
    className: "field-required"
  }, "*")), /*#__PURE__*/React.createElement("div", {
    className: "rule-target-row"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-target-select"
  }, /*#__PURE__*/React.createElement(DarkSelect, {
    value: editor.targetType,
    options: typeOptions,
    onChange: value => onChange({
      targetType: value
    }),
    ariaLabel: "\u76EE\u6807\u7968\u79CD"
  })), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: () => {
      setCreatingType(true);
      setTypeError("");
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "add"), /*#__PURE__*/React.createElement("span", null, "\u65B0\u5EFA\u7968\u79CD"))), creatingType ? /*#__PURE__*/React.createElement("div", {
    className: "rule-type-create"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-shell",
    style: {
      flex: 1,
      minWidth: 140
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-icon material-symbols-outlined"
  }, "category"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "field-input",
    placeholder: "\u8F93\u5165\u65B0\u7968\u79CD\u540D\u79F0\uFF0C\u5982 \u4F1A\u8BAE",
    value: typeName,
    onChange: event => {
      setTypeName(event.target.value);
      setTypeError("");
    },
    autoFocus: true
  })), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--primary btn--sm",
    onClick: handleCreateType,
    disabled: typeBusy
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, typeBusy ? "sync" : "check"), /*#__PURE__*/React.createElement("span", null, typeBusy ? "创建中..." : "确认新建")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: handleCancelCreateType,
    disabled: typeBusy
  }, /*#__PURE__*/React.createElement("span", null, "\u53D6\u6D88"))) : null, typeError ? /*#__PURE__*/React.createElement("p", {
    className: "field-help field-help--error"
  }, typeError) : null, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, RULE_TARGET_TYPE_HELP)), /*#__PURE__*/React.createElement("div", {
    className: "field-block field-block--wide"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u5173\u952E\u8BCD ", /*#__PURE__*/React.createElement("span", {
    className: "field-required"
  }, "*")), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-icon material-symbols-outlined"
  }, "key"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "field-input",
    placeholder: "\u5982 \u6EF4\u6EF4\u3001\u661F\u5DF4\u514B\u3001\u67D0\u67D0\u9152\u5E97",
    value: editor.keyword,
    onChange: event => onChange({
      keyword: event.target.value
    })
  })), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u53D1\u7968\u7684\u9500\u552E\u65B9\u6216\u660E\u7EC6\u5305\u542B\u8BE5\u5173\u952E\u8BCD\u65F6\u547D\u4E2D\u672C\u89C4\u5219\u3002")), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u91D1\u989D\u4E0B\u9650"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    inputMode: "decimal",
    className: "field-input u-tabular",
    placeholder: "\u4E0D\u9650",
    value: editor.amountMin,
    onChange: event => onChange({
      amountMin: event.target.value
    })
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u91D1\u989D\u4E0A\u9650"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    inputMode: "decimal",
    className: "field-input u-tabular",
    placeholder: "\u4E0D\u9650",
    value: editor.amountMax,
    onChange: event => onChange({
      amountMax: event.target.value
    })
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u542F\u7528"), /*#__PURE__*/React.createElement("label", {
    className: "toggle-row"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: editor.enabled !== false,
    onChange: event => onChange({
      enabled: event.target.checked
    })
  }), /*#__PURE__*/React.createElement("span", null, editor.enabled !== false ? "已启用" : "已停用"))), /*#__PURE__*/React.createElement("div", {
    className: "field-block field-block--wide"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u5F52\u6863\u5230"), /*#__PURE__*/React.createElement("div", {
    className: "rule-archive-summary"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "folder"), /*#__PURE__*/React.createElement("span", null, previewFolder ? `归档到：${previewFolder}` : "请选择目标票种，并填写关键词和金额范围")), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u6587\u4EF6\u5939\u7531\u76EE\u6807\u7968\u79CD\u548C\u91D1\u989D\u8303\u56F4\u81EA\u52A8\u751F\u6210\uFF0C\u4E0D\u9700\u8981\u624B\u52A8\u586B\u5199\uFF1B\u4FDD\u5B58\u540E\u751F\u6548\u3002"))), editor.error ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "error"
  }, editor.error) : null, /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--primary btn--sm",
    onClick: onCommit
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "check"), /*#__PURE__*/React.createElement("span", null, editor.mode === "new" ? "添加规则" : "保存修改")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: onCancel
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "close"), /*#__PURE__*/React.createElement("span", null, "\u53D6\u6D88"))));
}
function RuleTestResult({
  result,
  categoryNameById,
  targetTypeById
}) {
  if (!result) return null;
  const unknown = String(result.source || "") === "unknown" || !String(result.category_id || "").trim();
  if (unknown) {
    return /*#__PURE__*/React.createElement(NoticeBox, {
      tone: "warning"
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
      className: "rule-test-result__unknown"
    }, "\u5C06\u8FDB\u5165\u5F85\u4EBA\u5DE5\u590D\u6838"), /*#__PURE__*/React.createElement("p", {
      className: "field-help"
    }, "\u8FD9\u5F20\u53D1\u7968\u6CA1\u6709\u547D\u4E2D\u4EFB\u4F55\u5DF2\u542F\u7528\u89C4\u5219\uFF0C\u6574\u7406\u65F6\u4F1A\u653E\u5165\u300C\u5F85\u4EBA\u5DE5\u590D\u6838\u300D\u6587\u4EF6\u5939\u3002")));
  }
  const categoryId = String(result.category_id || "");
  const targetType = String(result.target_type || (targetTypeById || {})[categoryId] || "");
  const chainSteps = (Array.isArray(result.chain) ? result.chain : []).map(step => describeRuleChainStep(step, categoryNameById)).filter(Boolean).slice(0, 10);
  return /*#__PURE__*/React.createElement("div", {
    className: "rule-test-result"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-category-row__title"
  }, /*#__PURE__*/React.createElement(StatusPill, {
    tone: "success",
    icon: "task_alt"
  }, safeText(result.category_name, safeText(result.archive_folder, "已归类"))), targetType ? /*#__PURE__*/React.createElement("span", {
    className: "rule-target-tag",
    title: `目标票种：${targetType}`
  }, targetType) : null), /*#__PURE__*/React.createElement("div", {
    className: "rules-kv-list"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rules-kv"
  }, /*#__PURE__*/React.createElement("span", null, "\u76EE\u6807\u7968\u79CD"), /*#__PURE__*/React.createElement("strong", null, targetType || "--")), /*#__PURE__*/React.createElement("div", {
    className: "rules-kv"
  }, /*#__PURE__*/React.createElement("span", null, "\u5F52\u6863\u5230"), /*#__PURE__*/React.createElement("strong", {
    className: "u-mono"
  }, safeText(result.archive_folder, "--"))), /*#__PURE__*/React.createElement("div", {
    className: "rules-kv"
  }, /*#__PURE__*/React.createElement("span", null, "\u547D\u4E2D\u5173\u952E\u8BCD"), /*#__PURE__*/React.createElement("strong", null, safeText(result.keyword, "--"))), /*#__PURE__*/React.createElement("div", {
    className: "rules-kv"
  }, /*#__PURE__*/React.createElement("span", null, "\u89C4\u5219\u4F4D\u7F6E"), /*#__PURE__*/React.createElement("strong", {
    className: "u-mono"
  }, ruleLocationText(result.source_file, result.source_line) || "--")), /*#__PURE__*/React.createElement("div", {
    className: "rules-kv"
  }, /*#__PURE__*/React.createElement("span", null, "\u5F52\u7C7B\u6765\u6E90"), /*#__PURE__*/React.createElement("strong", null, classificationSourceLabel(result.source)))), chainSteps.length > 0 ? /*#__PURE__*/React.createElement("div", {
    className: "rule-chain-block"
  }, /*#__PURE__*/React.createElement("p", {
    className: "field-label"
  }, "\u5339\u914D\u8FC7\u7A0B"), /*#__PURE__*/React.createElement("div", {
    className: "rule-chain"
  }, chainSteps.map((step, index) => /*#__PURE__*/React.createElement("span", {
    key: `${index}-${step}`,
    className: "rule-chain__step"
  }, step)))) : null);
}
function RuleDictionarySection({
  terms,
  categoryOptions,
  scope,
  onAddTerm,
  onDeleteTerm
}) {
  const [termText, setTermText] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState("");
  const categoryNameById = useMemo(() => {
    const map = {};
    (categoryOptions || []).forEach(item => {
      const id = String(item && item.id || "");
      if (!id) return;
      map[id] = buildRuleFolderName(item.target_type, item.amount_range) || String(item.name || item.archive_folder || id);
    });
    return map;
  }, [categoryOptions]);
  const selectOptions = useMemo(() => {
    const options = [{
      value: "",
      label: "选择规则"
    }];
    (categoryOptions || []).forEach(item => {
      const id = String(item && item.id || "");
      if (!id) return;
      const name = buildRuleFolderName(item.target_type, item.amount_range) || String(item.name || "");
      options.push({
        value: id,
        label: name ? `${name}（${id}）` : id
      });
    });
    return options;
  }, [categoryOptions]);
  function handleAdd() {
    const term = termText.trim();
    if (!term) return setError("请填写销售方名称或税号。");
    if (!category) return setError("请选择归入的规则。");
    if ((terms || []).some(item => String(item && item.term || "").trim() === term)) {
      return setError("该销售方已在词典中，请直接修改现有条目。");
    }
    setError("");
    onAddTerm({
      term,
      category
    });
    setTermText("");
    setCategory("");
  }
  return /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-dictionary-form"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u9500\u552E\u65B9\u540D\u79F0\u6216\u7A0E\u53F7"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "field-input",
    placeholder: "\u5982 \u67D0\u67D0\u9910\u996E\u7BA1\u7406\u6709\u9650\u516C\u53F8",
    value: termText,
    onChange: event => {
      setTermText(event.target.value);
      setError("");
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u5F52\u5165\u89C4\u5219"), /*#__PURE__*/React.createElement(DarkSelect, {
    value: category,
    options: selectOptions,
    onChange: value => {
      setCategory(value);
      setError("");
    },
    ariaLabel: "\u8BCD\u5178\u5F52\u5165\u89C4\u5219"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--secondary btn--sm",
    onClick: handleAdd
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "add_circle"), /*#__PURE__*/React.createElement("span", null, "\u6DFB\u52A0\u8BCD\u5178")), /*#__PURE__*/React.createElement("span", {
    className: "field-help"
  }, "\u6309\u9500\u552E\u65B9\u7CBE\u786E\u5339\u914D\uFF0C\u9002\u5408\u56FA\u5B9A\u4F9B\u5E94\u5546\u3002")), error ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "error"
  }, error) : null, (terms || []).length === 0 ? /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u8FD8\u6CA1\u6709\u9500\u552E\u65B9\u8BCD\u5178\u6761\u76EE\u3002") : /*#__PURE__*/React.createElement("div", {
    className: "rule-dictionary-list"
  }, terms.map((term, index) => /*#__PURE__*/React.createElement("div", {
    key: `${term.term}-${index}`,
    className: "rule-dictionary-row"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-dictionary-row__copy"
  }, /*#__PURE__*/React.createElement("strong", {
    className: "u-truncate",
    title: term.term
  }, term.term || "未命名销售方"), /*#__PURE__*/React.createElement("span", null, "\u5F52\u5165 ", categoryNameById[String(term.category || "")] || safeText(term.category, "未指定规则"))), /*#__PURE__*/React.createElement(StatusPill, {
    tone: "neutral"
  }, ruleLayerLabel(term.source_layer || scope)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "rule-icon-button",
    title: "\u5220\u9664\u8BCD\u5178\u6761\u76EE",
    "aria-label": `删除 ${term.term}`,
    onClick: () => onDeleteTerm(index)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "delete"))))));
}
function RuleUnclassifiedSection({
  invoices,
  onPrefill
}) {
  const rows = Array.isArray(invoices) ? invoices : [];
  if (rows.length === 0) return null;
  return /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "help",
    title: "\u672A\u5F52\u7C7B\u53D1\u7968",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "warning",
      icon: "warning"
    }, "\u5F85\u8865\u5145\u89C4\u5219")
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u8FD9\u4E9B\u53D1\u7968\u5728\u6700\u8FD1\u4E00\u6B21\u6574\u7406\u4E2D\u6CA1\u6709\u547D\u4E2D\u4EFB\u4F55\u89C4\u5219\uFF0C\u6574\u7406\u540E\u4F1A\u8FDB\u5165\u5F85\u4EBA\u5DE5\u590D\u6838\u3002\u53EF\u6309\u53D1\u7968\u4FE1\u606F\u9884\u586B\u4E00\u6761\u89C4\u5219\uFF0C\u5E76\u9009\u62E9\u76EE\u6807\u7968\u79CD\u3002"), /*#__PURE__*/React.createElement("div", {
    className: "rule-unclassified-list"
  }, rows.slice(0, 20).map((row, index) => /*#__PURE__*/React.createElement("div", {
    key: `${row.document_id || row.path || "invoice"}-${index}`,
    className: "rule-unclassified-row"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-unclassified-row__copy"
  }, /*#__PURE__*/React.createElement("strong", {
    className: "u-truncate",
    title: safeText(row.merchant, "")
  }, safeText(row.merchant, "未识别销售方")), /*#__PURE__*/React.createElement("span", null, safeText(row.type, "未知票种"), " \xB7 ", formatRuleInvoiceAmountLabel(row.amount), row.date ? ` · ${row.date}` : "")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--secondary btn--sm",
    onClick: () => onPrefill(row)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "add_circle"), /*#__PURE__*/React.createElement("span", null, "\u636E\u6B64\u65B0\u5EFA\u89C4\u5219"))))), rows.length > 20 ? /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u4EC5\u663E\u793A\u524D 20 \u6761\uFF0C\u5171 ", rows.length, " \u6761\u3002") : null));
}
function RuleBuiltinSection({
  rows,
  busy,
  onEdit,
  onToggle,
  onRestore,
  onRestoreAll
}) {
  const items = Array.isArray(rows) ? rows : [];
  return /*#__PURE__*/React.createElement("section", {
    className: "surface-card rules-builtin"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "inventory_2",
    title: "\u5185\u7F6E\u9ED8\u8BA4\u89C4\u5219",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "neutral"
    }, `${items.length} 条 · 可覆盖`)
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rules-toolbar"
  }, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u5185\u7F6E\u89C4\u5219\u53EF\u6309\u5F53\u524D\u4F5C\u7528\u8303\u56F4\u8986\u76D6\uFF1B\u76EE\u6807\u7968\u79CD\u51B3\u5B9A\u5F52\u6863\u6587\u4EF6\u5939\u548C\u5F52\u7C7B\u7ED3\u679C\uFF0C\u5185\u7F6E\u89C4\u5219\u539F\u6709\u7684\u7968\u79CD\u515C\u5E95\u6761\u4EF6\u4F1A\u81EA\u52A8\u4FDD\u7559\u3002\u672A\u547D\u4E2D\u81EA\u5B9A\u4E49\u89C4\u5219\u65F6\u6309\u5217\u8868\u987A\u5E8F\u515C\u5E95\u3002"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: onRestoreAll,
    disabled: busy
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "restart_alt"), /*#__PURE__*/React.createElement("span", null, "\u5168\u90E8\u6062\u590D\u9ED8\u8BA4"))), items.length === 0 ? /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u6682\u672A\u83B7\u53D6\u5230\u5185\u7F6E\u89C4\u5219\u3002") : /*#__PURE__*/React.createElement("div", {
    className: "rules-builtin-list"
  }, items.map(row => {
    const keywords = (Array.isArray(row.keywords) ? row.keywords : []).map(value => String(value));
    const folderText = row.previewFolder || "请选择目标票种";
    return /*#__PURE__*/React.createElement("div", {
      className: "rules-builtin-row",
      key: row.id
    }, /*#__PURE__*/React.createElement("span", {
      className: "rules-builtin-row__folder u-truncate",
      title: folderText
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, "folder"), /*#__PURE__*/React.createElement("span", {
      className: "u-truncate"
    }, folderText), row.target_type ? /*#__PURE__*/React.createElement("span", {
      className: "rule-target-tag",
      title: `目标票种：${row.target_type}`
    }, row.target_type) : /*#__PURE__*/React.createElement(StatusPill, {
      tone: "warning"
    }, "\u7F3A\u5C11\u76EE\u6807\u7968\u79CD")), /*#__PURE__*/React.createElement("span", {
      className: "rules-builtin-row__keywords u-truncate",
      title: keywords.join("、")
    }, keywords.length > 0 ? keywords.join("、") : "无关键词"), /*#__PURE__*/React.createElement("span", {
      className: "rules-builtin-row__badge"
    }, /*#__PURE__*/React.createElement(StatusPill, {
      tone: row.modified ? "warning" : "neutral"
    }, row.modified ? "已修改" : "内置"), row.enabled === false ? /*#__PURE__*/React.createElement(StatusPill, {
      tone: "warning"
    }, "\u5DF2\u505C\u7528") : null), /*#__PURE__*/React.createElement("span", {
      className: "rules-builtin-row__actions"
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: joinClasses("rule-icon-button", row.enabled !== false && "is-active"),
      title: row.enabled !== false ? "停用" : "启用",
      "aria-label": `${row.enabled !== false ? "停用" : "启用"}内置规则 ${folderText}`,
      onClick: () => onToggle(row)
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, row.enabled !== false ? "toggle_on" : "toggle_off")), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "rule-icon-button",
      title: "\u7F16\u8F91",
      "aria-label": `编辑内置规则 ${folderText}`,
      onClick: () => onEdit(row)
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, "edit")), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "rule-icon-button",
      title: "\u6062\u590D\u9ED8\u8BA4",
      "aria-label": `恢复默认内置规则 ${folderText}`,
      onClick: () => onRestore(row)
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, "restart_alt"))));
  }))));
}
function RuleBuiltinEditor({
  editor,
  documentTypes,
  onChange,
  onCreateType,
  onCommit,
  onCancel
}) {
  const [creatingType, setCreatingType] = useState(false);
  const [typeName, setTypeName] = useState("");
  const [typeError, setTypeError] = useState("");
  const [typeBusy, setTypeBusy] = useState(false);
  if (!editor) {
    return /*#__PURE__*/React.createElement("div", {
      className: "rules-empty-state"
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, "inventory_2"), /*#__PURE__*/React.createElement("p", null, "\u4ECE\u5185\u7F6E\u9ED8\u8BA4\u89C4\u5219\u4E2D\u9009\u62E9\u4E00\u6761\u8FDB\u884C\u8986\u76D6\u7F16\u8F91\u3002"));
  }
  const previewFolder = buildRuleFolderName(editor.targetType, buildRuleAmountRange(editor.amountMin, editor.amountMax));
  const typeOptions = [{
    value: "",
    label: "请选择目标票种"
  }].concat(documentTypes.map(type => ({
    value: type,
    label: type
  })));
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
        const issueText = result && Array.isArray(result.issues) && result.issues.length > 0 ? String(result.issues[0].text || result.issues[0].message || "") : "";
        setTypeError(issueText || result && result.message || "新建票种失败，请稍后重试。");
        return;
      }
      setCreatingType(false);
      setTypeName("");
      setTypeError("");
      onChange({
        targetType: String(result.name || name)
      });
    } finally {
      setTypeBusy(false);
    }
  }
  function handleCancelCreateType() {
    setCreatingType(false);
    setTypeName("");
    setTypeError("");
  }
  return /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rules-editor-grid"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-block field-block--wide"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u76EE\u6807\u7968\u79CD ", /*#__PURE__*/React.createElement("span", {
    className: "field-required"
  }, "*")), /*#__PURE__*/React.createElement("div", {
    className: "rule-target-row"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-target-select"
  }, /*#__PURE__*/React.createElement(DarkSelect, {
    value: editor.targetType,
    options: typeOptions,
    onChange: value => onChange({
      targetType: value
    }),
    ariaLabel: "\u76EE\u6807\u7968\u79CD"
  })), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: () => {
      setCreatingType(true);
      setTypeError("");
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "add"), /*#__PURE__*/React.createElement("span", null, "\u65B0\u5EFA\u7968\u79CD"))), creatingType ? /*#__PURE__*/React.createElement("div", {
    className: "rule-type-create"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-shell",
    style: {
      flex: 1,
      minWidth: 140
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-icon material-symbols-outlined"
  }, "category"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "field-input",
    placeholder: "\u8F93\u5165\u65B0\u7968\u79CD\u540D\u79F0\uFF0C\u5982 \u4F1A\u8BAE",
    value: typeName,
    onChange: event => {
      setTypeName(event.target.value);
      setTypeError("");
    },
    autoFocus: true
  })), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--primary btn--sm",
    onClick: handleCreateType,
    disabled: typeBusy
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, typeBusy ? "sync" : "check"), /*#__PURE__*/React.createElement("span", null, typeBusy ? "创建中..." : "确认新建")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: handleCancelCreateType,
    disabled: typeBusy
  }, /*#__PURE__*/React.createElement("span", null, "\u53D6\u6D88"))) : null, typeError ? /*#__PURE__*/React.createElement("p", {
    className: "field-help field-help--error"
  }, typeError) : null, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, RULE_TARGET_TYPE_HELP)), /*#__PURE__*/React.createElement("div", {
    className: "field-block field-block--wide"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u5173\u952E\u8BCD"), /*#__PURE__*/React.createElement("textarea", {
    className: "rule-textarea",
    placeholder: "\u591A\u4E2A\u5173\u952E\u8BCD\u7528\u9017\u53F7\u6216\u6362\u884C\u5206\u9694",
    value: editor.keywordsText,
    onChange: event => onChange({
      keywordsText: event.target.value
    })
  }), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u547D\u4E2D\u4EFB\u4E00\u5173\u952E\u8BCD\u65F6\u4F7F\u7528\u8FD9\u6761\u5185\u7F6E\u89C4\u5219\uFF1B\u7559\u7A7A\u8868\u793A\u8BE5\u89C4\u5219\u53EA\u6309\u7968\u79CD\u515C\u5E95\u3002")), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u91D1\u989D\u4E0B\u9650"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    inputMode: "decimal",
    className: "field-input u-tabular",
    placeholder: "\u4E0D\u9650",
    value: editor.amountMin,
    onChange: event => onChange({
      amountMin: event.target.value
    })
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u91D1\u989D\u4E0A\u9650"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    inputMode: "decimal",
    className: "field-input u-tabular",
    placeholder: "\u4E0D\u9650",
    value: editor.amountMax,
    onChange: event => onChange({
      amountMax: event.target.value
    })
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u542F\u7528"), /*#__PURE__*/React.createElement("label", {
    className: "toggle-row"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: editor.enabled !== false,
    onChange: event => onChange({
      enabled: event.target.checked
    })
  }), /*#__PURE__*/React.createElement("span", null, editor.enabled !== false ? "已启用" : "已停用"))), /*#__PURE__*/React.createElement("div", {
    className: "field-block field-block--wide"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u5F52\u6863\u5230"), /*#__PURE__*/React.createElement("div", {
    className: "rule-archive-summary"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "folder"), /*#__PURE__*/React.createElement("span", null, previewFolder ? `归档到：${previewFolder}` : "请选择目标票种，并填写关键词和金额范围")), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u6587\u4EF6\u5939\u7531\u76EE\u6807\u7968\u79CD\u548C\u91D1\u989D\u8303\u56F4\u81EA\u52A8\u751F\u6210\uFF0C\u4E0D\u9700\u8981\u624B\u52A8\u586B\u5199\uFF1B\u4FDD\u5B58\u540E\u751F\u6548\u3002"))), editor.error ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "error"
  }, editor.error) : null, /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--primary btn--sm",
    onClick: onCommit
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "check"), /*#__PURE__*/React.createElement("span", null, "\u4FDD\u5B58\u8986\u76D6")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: onCancel
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "close"), /*#__PURE__*/React.createElement("span", null, "\u53D6\u6D88"))));
}
function RuleRestoreDialog({
  dialog,
  mode,
  busy,
  error,
  issues,
  libraryAvailable,
  scopeLabel,
  dirty,
  onModeChange,
  onConfirm,
  onCancel
}) {
  if (!dialog) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "modal-overlay",
    onClick: onCancel
  }, /*#__PURE__*/React.createElement("div", {
    className: "modal-card restore-dialog",
    onClick: event => event.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "modal-head"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    className: "page-eyebrow"
  }, "\u6062\u590D\u9ED8\u8BA4"), /*#__PURE__*/React.createElement("h2", {
    className: "page-title",
    style: {
      fontSize: 26
    }
  }, dialog.title)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: onCancel,
    "aria-label": "\u5173\u95ED"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "close"))), /*#__PURE__*/React.createElement("div", {
    className: "modal-body"
  }, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u5C06\u5220\u9664\u5185\u7F6E\u89C4\u5219\u7684\u81EA\u5B9A\u4E49\u8986\u76D6\uFF0C\u6062\u590D\u51FA\u5382\u9ED8\u8BA4\uFF1B\u4F1A\u5148\u81EA\u52A8\u5907\u4EFD\u3002"), dirty ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, "\u5F53\u524D\u6709\u672A\u4FDD\u5B58\u7684\u4FEE\u6539\uFF0C\u6062\u590D\u9ED8\u8BA4\u540E\u4F1A\u91CD\u65B0\u52A0\u8F7D\u89C4\u5219\u5E76\u4E22\u5F03\u8FD9\u4E9B\u4FEE\u6539\u3002") : null, /*#__PURE__*/React.createElement("p", {
    className: "field-label"
  }, "\u6062\u590D\u8303\u56F4"), /*#__PURE__*/React.createElement("div", {
    className: "restore-options",
    role: "radiogroup",
    "aria-label": "\u6062\u590D\u8303\u56F4"
  }, /*#__PURE__*/React.createElement("label", {
    className: joinClasses("restore-option", mode === "current" && "is-selected")
  }, /*#__PURE__*/React.createElement("input", {
    type: "radio",
    name: "restore-scope",
    checked: mode === "current",
    onChange: () => onModeChange("current")
  }), /*#__PURE__*/React.createElement("span", {
    className: "restore-option__copy"
  }, /*#__PURE__*/React.createElement("strong", null, "\u4EC5\u5F53\u524D\u4F5C\u7528\u8303\u56F4"), /*#__PURE__*/React.createElement("span", null, `只删除当前作用范围（${scopeLabel}）内的内置覆盖`))), /*#__PURE__*/React.createElement("label", {
    className: joinClasses("restore-option", mode === "all" && "is-selected", !libraryAvailable && "is-disabled")
  }, /*#__PURE__*/React.createElement("input", {
    type: "radio",
    name: "restore-scope",
    checked: mode === "all",
    onChange: () => {
      if (libraryAvailable) onModeChange("all");
    },
    disabled: !libraryAvailable
  }), /*#__PURE__*/React.createElement("span", {
    className: "restore-option__copy"
  }, /*#__PURE__*/React.createElement("strong", null, "\u5168\u5C40 + \u5F53\u524D\u53D1\u7968\u5E93"), /*#__PURE__*/React.createElement("span", null, libraryAvailable ? "同时清理全局规则和当前发票库的内置覆盖" : "当前没有可用发票库，无法选择")))), error ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "error"
  }, error) : null, issues && issues.length > 0 ? /*#__PURE__*/React.createElement(RuleIssues, {
    issues: issues,
    title: "\u6062\u590D\u672A\u5B8C\u6210"
  }) : null), /*#__PURE__*/React.createElement("div", {
    className: "modal-footer"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost",
    onClick: onCancel,
    disabled: busy
  }, "\u53D6\u6D88"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--primary",
    onClick: onConfirm,
    disabled: busy
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, busy ? "sync" : "restart_alt"), /*#__PURE__*/React.createElement("span", null, busy ? "恢复中..." : "确认恢复")))));
}
function RuleTypesManager({
  builtinTypes,
  customTypes,
  issues,
  busy,
  onDeleteType
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "rules-types-layout"
  }, /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "verified",
    title: "\u5185\u7F6E\u7968\u79CD",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "neutral"
    }, `${builtinTypes.length} 个 · 只读`)
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u5185\u7F6E\u7968\u79CD\u6765\u81EA\u53D1\u7968\u8BC6\u522B\u7ED3\u679C\uFF0C\u4E0D\u80FD\u5220\u9664\u6216\u6539\u540D\u3002"), builtinTypes.length === 0 ? /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u6682\u672A\u83B7\u53D6\u5230\u5185\u7F6E\u7968\u79CD\u3002") : /*#__PURE__*/React.createElement("div", {
    className: "rules-type-list"
  }, builtinTypes.map(name => /*#__PURE__*/React.createElement("span", {
    key: name,
    className: "rule-type-chip"
  }, name))))), /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "category",
    title: "\u81EA\u5B9A\u4E49\u7968\u79CD",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "info"
    }, `${customTypes.length} 个`)
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, RULE_CUSTOM_TYPE_HELP), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u81EA\u5B9A\u4E49\u7968\u79CD\u662F\u89C4\u5219\u7684\u76EE\u6807\u7968\u79CD\uFF1B\u5728\u89C4\u5219\u7F16\u8F91\u5668\u4E2D\u70B9\u300C\u65B0\u5EFA\u7968\u79CD\u300D\u5373\u53EF\u6DFB\u52A0\u3002"), issues && issues.length > 0 ? /*#__PURE__*/React.createElement(RuleIssues, {
    issues: issues,
    title: "\u7968\u79CD\u64CD\u4F5C\u672A\u5B8C\u6210"
  }) : null, customTypes.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "rules-empty-state"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "category"), /*#__PURE__*/React.createElement("p", null, "\u8FD8\u6CA1\u6709\u81EA\u5B9A\u4E49\u7968\u79CD\uFF0C\u53EF\u5728\u89C4\u5219\u7F16\u8F91\u5668\u4E2D\u65B0\u5EFA\u3002")) : /*#__PURE__*/React.createElement("div", {
    className: "rules-type-rows"
  }, customTypes.map(name => /*#__PURE__*/React.createElement("div", {
    className: "rules-type-row",
    key: name
  }, /*#__PURE__*/React.createElement("span", {
    className: "rules-type-row__name u-truncate",
    title: name
  }, name), /*#__PURE__*/React.createElement(StatusPill, {
    tone: "neutral"
  }, "\u81EA\u5B9A\u4E49"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "rule-icon-button rule-icon-button--danger",
    title: "\u5220\u9664\u7968\u79CD",
    "aria-label": `删除票种 ${name}`,
    disabled: busy,
    onClick: () => onDeleteType(name)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "delete"))))))));
}
function AnalysisPage({
  onOpenDisclaimer
}) {
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
  useEffect(() => {
    let active = true;
    let timer = null;
    const loadResults = async () => {
      try {
        const [results, settingsRes] = await Promise.all([callApi("get_results"), callApi("load_user_settings").catch(() => null)]);
        if (!active || !results) return;
        setSummary(results.summary || {});
        setSuccessInvoices(normalizeSuccessInvoices(results.successInvoices || []));
        setGroupedErrors(normalizeGroupedErrors(results.groupedErrorInvoices || []));
        setManualCheckPath(results.manual_check_path || "");
        setResultBreakdown(results.resultBreakdown || results.summary && results.summary.result_breakdown || {});
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
  const manualReviewGroup = groupedErrors.find(group => group.key === "manual_review");
  const manualCheckCount = Number(summary.manual_check_count || resultBreakdown.manual_review || manualReviewGroup && manualReviewGroup.count || 0);
  const retentionCount = Number(summary.retention_count || resultBreakdown.retained_record || 0);
  const processingErrorCount = Number(summary.processing_error_count || resultBreakdown.processing_error || 0);
  const pendingCount = manualCheckCount + retentionCount + processingErrorCount || Number(summary.error_count || totalErrors || 0);
  const totalResultCount = successCount + pendingCount;
  const statusText = buildResultStatusText(successCount, manualCheckCount, retentionCount, processingErrorCount);
  const groupedVisible = groupedErrors.filter(group => Number(group.count || group.items.length || 0) > 0);
  const classificationBreakdown = summary && summary.classification_breakdown || organizeSummary && organizeSummary.classification_counts || {};
  const classificationSources = summary && summary.classification_source_breakdown || organizeSummary && organizeSummary.classification_source_counts || {};
  const unclassifiedCount = Number(summary && summary.unclassified_count || organizeSummary && organizeSummary.unclassified_count || 0);
  const classificationEntries = Object.keys(classificationBreakdown).map(name => ({
    name: String(name || ""),
    count: Number(classificationBreakdown[name] || 0)
  })).filter(item => item.name && item.count > 0).sort((left, right) => right.count - left.count);
  const classificationSourceEntries = Object.keys(classificationSources).map(source => ({
    source: String(source || ""),
    count: Number(classificationSources[source] || 0)
  })).filter(item => item.source && item.count > 0).sort((left, right) => right.count - left.count);
  const isFetchResult = resultTaskMode === "fetch";
  const isLocalResult = resultTaskMode === "local";
  const localInPlace = isLocalResult && !!organizeSummary.in_place;
  const localSplitByCategory = organizeSummary.split_by_category !== false;
  const resultHeadline = isFetchResult ? "本次提取完成" : isLocalResult ? "本次整理完成" : UI_COPY.pages.analysis.resultTitle;
  const fetchAttachments = Number(fetchSummary.attachments || 0);
  const fetchTodoCount = Number(fetchSummary.todos || 0);
  const fetchInboxDir = fetchSummary.inbox_dir || "";
  const fetchManifestPath = fetchSummary.manifest_path || "";
  const bannerCopy = isFetchResult ? APP_VISIBLE_COPY.resultBanners.fetch : isLocalResult ? localInPlace ? localSplitByCategory ? APP_VISIBLE_COPY.resultBanners.localApply : APP_VISIBLE_COPY.resultBanners.localApplyFlat : localSplitByCategory ? APP_VISIBLE_COPY.resultBanners.localApplyCustom : APP_VISIBLE_COPY.resultBanners.localApplyCustomFlat : null;
  const completionBanner = bannerCopy ? {
    eyebrow: bannerCopy.eyebrow,
    title: bannerCopy.title,
    text: bannerCopy.text,
    icon: isFetchResult ? "inbox" : "task_alt",
    pathText: isFetchResult ? fetchManifestPath || fetchInboxDir || outputPath : outputPath,
    openPath: isFetchResult ? fetchInboxDir || outputPath : outputPath,
    buttonLabel: isFetchResult ? "打开 inbox 文件夹" : "打开输出目录"
  } : null;
  const outputBanner = {
    icon: "folder",
    eyebrow: isLocalResult && localInPlace ? "发票文件夹" : "输出目录",
    title: outputPath ? isFetchResult ? "提取结果已写入输出目录" : localInPlace ? "归档结果已写入发票文件夹" : isLocalResult ? "归档结果已写入输出目录" : "归档结果与暂存记录已写入输出目录" : "当前还没有可打开的输出目录",
    text: outputPath ? isFetchResult ? "inbox 文件夹与 manifest.jsonl 位于该目录下，可从这里继续查看。" : localInPlace ? localSplitByCategory ? "分类文件、「整理前发票」中的原件、重复件与导出明细都可以从这里继续查看。" : "整理后的文件、「整理前发票」中的原件、重复件与导出明细都可以从这里继续查看。" : isLocalResult ? "归档副本与导出明细已写入该目录；原始文件保留在发票文件夹。" : "成功归档文件、暂存记录和导出结果都可以从这里继续查看。" : "待本轮生成结果后，可从这里直接打开输出目录。",
    pathText: outputPath || "",
    buttonLabel: "打开输出目录",
    openPath: outputPath || parentFolder(manualCheckPath)
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
    if (!openResult || !openResult.success) throw new Error(openResult && openResult.message || "结果明细已导出，但打开文件失败。");
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
        window.alert(result && result.message || "导出失败。");
      }
    } catch (error) {
      window.alert(error.message || "导出失败。");
    } finally {
      setExporting(false);
    }
  }
  const summaryCards = isFetchResult ? [{
    key: "attachments",
    icon: "attach_file",
    label: "已提取附件",
    value: fetchAttachments,
    helper: fetchAttachments > 0 ? "附件已保存到 inbox 文件夹。" : "本轮未提取到附件。",
    tone: "success"
  }, {
    key: "todos",
    icon: "pending_actions",
    label: "待处理事项",
    value: fetchTodoCount,
    helper: fetchTodoCount > 0 ? "提取过程中有记录需要后续处理。" : "本轮提取没有待处理事项。",
    tone: fetchTodoCount > 0 ? "warning" : "info"
  }] : [{
    key: "success",
    icon: "task_alt",
    label: "处理成功",
    value: successCount,
    helper: successCount > 0 ? isLocalResult ? localInPlace ? "归档文件已写入发票文件夹。" : "归档副本已写入输出目录。" : "归档文件已写入输出目录。" : "当前还没有成功记录。",
    tone: "success"
  }, {
    key: "retention",
    icon: "inventory_2",
    label: "暂存记录",
    value: retentionCount,
    helper: retentionCount > 0 ? "系统已保全但未纳入成功归档，可按需导出查看。" : "当前没有暂存记录。",
    tone: "info"
  }, {
    key: "manual",
    icon: "folder_open",
    label: "待人工复核",
    value: manualCheckCount,
    helper: manualCheckCount > 0 ? "这是当前需要优先处理的内容。" : "当前没有待人工复核项。",
    tone: manualCheckCount > 0 ? "warning" : "info"
  }];
  return /*#__PURE__*/React.createElement(AppShell, {
    active: "analysis",
    onOpenDisclaimer: onOpenDisclaimer,
    footerLeft: /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn btn--ghost",
      onClick: () => navigate("/")
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, "add_circle"), /*#__PURE__*/React.createElement("span", null, "\u5F00\u59CB\u65B0\u6279\u6B21")),
    footerRight: lastExportPath ? /*#__PURE__*/React.createElement("p", {
      className: "footer-meta"
    }, "\u6700\u8FD1\u5BFC\u51FA: ", fileNameFromPath(lastExportPath)) : null
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-wrap page-wrap--analysis"
  }, /*#__PURE__*/React.createElement(PageHeader, {
    eyebrow: UI_COPY.pages.analysis.eyebrow,
    title: UI_COPY.pages.analysis.title
  }), completionBanner ? /*#__PURE__*/React.createElement(ResultActionBanner, {
    tone: "neutral",
    icon: completionBanner.icon,
    eyebrow: completionBanner.eyebrow,
    title: completionBanner.title,
    text: completionBanner.text,
    pathText: completionBanner.pathText || "",
    buttonLabel: completionBanner.buttonLabel,
    onClick: () => handleOpenPath(completionBanner.openPath),
    disabled: !completionBanner.openPath
  }) : null, /*#__PURE__*/React.createElement("section", {
    className: "surface-card surface-card--hero"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 18,
      display: "flex",
      flexDirection: "column",
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "flex-start",
      gap: 16,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    className: "progress-kicker"
  }, UI_COPY.pages.analysis.statusSummary), /*#__PURE__*/React.createElement("h2", {
    className: "progress-title"
  }, resultHeadline), isFetchResult ? /*#__PURE__*/React.createElement("p", {
    className: "progress-meta"
  }, "\u672C\u8F6E\u5171\u63D0\u53D6 ", /*#__PURE__*/React.createElement("strong", {
    className: "u-tabular"
  }, fetchAttachments), " \u4E2A\u9644\u4EF6\uFF0C\u6E05\u5355\u5DF2\u5199\u5165 inbox \u6587\u4EF6\u5939\u3002") : /*#__PURE__*/React.createElement("p", {
    className: "progress-meta"
  }, "\u5171\u6574\u7406 ", /*#__PURE__*/React.createElement("strong", {
    className: "u-tabular"
  }, totalResultCount), " \u6761\u7ED3\u679C\u8BB0\u5F55\u3002", statusText)), /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement(ResultToolbarButton, {
    icon: exporting ? "sync" : "download",
    label: exporting ? "导出中..." : "导出结果明细",
    onClick: handleExport,
    disabled: exporting,
    primary: true
  }))), /*#__PURE__*/React.createElement("div", {
    className: "cards-grid"
  }, summaryCards.map(card => /*#__PURE__*/React.createElement(ResultSummaryCard, _extends({
    key: card.key
  }, card)))), classificationEntries.length > 0 || classificationSourceEntries.length > 0 ? /*#__PURE__*/React.createElement("div", {
    className: "classification-summary"
  }, /*#__PURE__*/React.createElement("div", {
    className: "classification-summary__head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "category"), /*#__PURE__*/React.createElement("span", null, UI_COPY.pages.analysis.classificationTitle)), classificationEntries.length > 0 ? /*#__PURE__*/React.createElement("div", {
    className: "group-strip group-strip--inline"
  }, classificationEntries.slice(0, 12).map(item => /*#__PURE__*/React.createElement("span", {
    key: item.name,
    className: "group-chip"
  }, /*#__PURE__*/React.createElement("span", null, item.name), /*#__PURE__*/React.createElement("span", {
    className: "u-tabular"
  }, item.count))), classificationEntries.length > 12 ? /*#__PURE__*/React.createElement("span", {
    className: "group-chip group-chip--info"
  }, "\u5176\u4ED6 ", classificationEntries.length - 12, " \u7C7B") : null) : null, classificationSourceEntries.length > 0 ? /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u5F52\u7C7B\u6765\u6E90\uFF1A", classificationSourceEntries.map(item => `${classificationSourceLabel(item.source)} ${item.count}`).join(" · ")) : null) : null, quotaExhausted && quotaMessage ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, quotaMessage) : null, processingErrorCount > 0 ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, "\u68C0\u6D4B\u5230 ", processingErrorCount, " \u6761\u771F\u5B9E\u5F02\u5E38\uFF0C\u8BF7\u901A\u8FC7\u201C\u5BFC\u51FA\u7ED3\u679C\u660E\u7EC6\u201D\u7EE7\u7EED\u6392\u67E5\u3002") : null)), loadingError ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "error"
  }, loadingError) : null, unclassifiedCount > 0 ? /*#__PURE__*/React.createElement(ResultActionBanner, {
    icon: "rule",
    eyebrow: "\u5F52\u7C7B\u63D0\u793A",
    title: `检测到 ${unclassifiedCount} 张发票未归类`,
    text: "\u8FD9\u4E9B\u53D1\u7968\u6CA1\u6709\u547D\u4E2D\u4EFB\u4F55\u5DF2\u542F\u7528\u7C7B\u76EE\uFF0C\u6574\u7406\u540E\u4F1A\u8FDB\u5165\u5F85\u4EBA\u5DE5\u590D\u6838\u3002\u8865\u5145\u5F52\u7C7B\u89C4\u5219\u540E\u91CD\u65B0\u6574\u7406\u5373\u53EF\u81EA\u52A8\u5F52\u6863\u3002",
    buttonLabel: "\u7BA1\u7406\u5F52\u7C7B\u89C4\u5219",
    onClick: () => navigate("/rules")
  }) : null, manualCheckCount > 0 ? /*#__PURE__*/React.createElement(ResultActionBanner, {
    icon: "folder_open",
    eyebrow: UI_COPY.pages.analysis.reviewTitle,
    title: `检测到 ${manualCheckCount} 条待人工复核记录`,
    text: UI_COPY.pages.analysis.reviewReady,
    chips: groupedVisible.length > 0 ? /*#__PURE__*/React.createElement("div", {
      className: "group-strip group-strip--inline"
    }, groupedVisible.map(group => /*#__PURE__*/React.createElement("span", {
      key: group.key,
      className: joinClasses("group-chip", resolveGroupTone(group.key))
    }, /*#__PURE__*/React.createElement("span", null, group.label), /*#__PURE__*/React.createElement("span", {
      className: "u-tabular"
    }, Number(group.count || group.items.length || 0))))) : null,
    buttonLabel: "\u6253\u5F00\u5F85\u4EBA\u5DE5\u590D\u6838",
    onClick: handleOpenManualCheck,
    disabled: !manualCheckCount
  }) : null, /*#__PURE__*/React.createElement(ResultActionBanner, {
    tone: "neutral",
    icon: outputBanner.icon,
    eyebrow: outputBanner.eyebrow,
    title: outputBanner.title,
    text: outputBanner.text,
    pathText: outputBanner.pathText,
    buttonLabel: outputBanner.buttonLabel,
    onClick: () => handleOpenPath(outputBanner.openPath),
    disabled: !outputBanner.openPath
  })));
}
function RulesPage({
  onOpenDisclaimer
}) {
  const [rulesData, setRulesData] = useState(null);
  const [libraryDir, setLibraryDir] = useState("");
  const [scope, setScope] = useState("global");
  const [scopeDrafts, setScopeDrafts] = useState({
    global: buildUserRuleDraft(null, "global", []),
    library: buildUserRuleDraft(null, "library", [])
  });
  const [dirtyScopes, setDirtyScopes] = useState({
    global: false,
    library: false
  });
  const [activePanel, setActivePanel] = useState("rules");
  const [typesState, setTypesState] = useState({
    documentTypes: [],
    customTypes: [],
    builtinTypes: []
  });
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
  const [actionState, setActionState] = useState({
    tone: "info",
    message: ""
  });
  const [saveIssues, setSaveIssues] = useState([]);
  const [testFields, setTestFields] = useState({
    seller: "",
    seller_tin: "",
    item: "",
    type: "",
    amount: ""
  });
  const [testState, setTestState] = useState({
    status: "idle",
    result: null,
    issues: [],
    message: ""
  });
  const builtinCategoryIds = useMemo(() => rulesData && Array.isArray(rulesData.builtin_category_ids) ? rulesData.builtin_category_ids.map(item => String(item)) : [], [rulesData]);
  const builtinIdSet = useMemo(() => new Set(builtinCategoryIds), [builtinCategoryIds]);
  const documentTypes = typesState.documentTypes;
  const builtinTypes = typesState.builtinTypes;
  const draft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
  const dirty = !!dirtyScopes[scope];
  const libraryAvailable = !!(rulesData && rulesData.library_available);
  const effectiveCategories = rulesData && Array.isArray(rulesData.effective_categories) ? rulesData.effective_categories : [];
  const ruleRows = useMemo(() => draft.categories.map((entry, index) => Object.assign({}, entry, {
    index,
    previewFolder: ruleEntryPreviewFolder(entry)
  })), [draft]);
  const missingTargetCount = useMemo(() => draft.categories.filter(entry => !String(entry && entry.target_type || "").trim()).length, [draft]);
  const missingBuiltinTargetCount = useMemo(() => (draft.builtinOverrides || []).filter(entry => !String(entry && entry.target_type || "").trim()).length, [draft]);
  const persistedOverrideScopes = useMemo(() => {
    const map = {};
    ["global", "library"].forEach(scopeName => {
      const scopeData = rulesData && rulesData[scopeName];
      const categories = scopeData && Array.isArray(scopeData.categories) ? scopeData.categories : [];
      categories.forEach(item => {
        const id = String(item && item.id || "");
        if (!id || !builtinIdSet.has(id)) return;
        if (!map[id]) map[id] = [];
        if (map[id].indexOf(scopeName) < 0) map[id].push(scopeName);
      });
    });
    return map;
  }, [rulesData, builtinIdSet]);
  const builtinRows = useMemo(() => {
    const draftById = new Map();
    (draft.builtinOverrides || []).forEach(entry => {
      if (entry.id) draftById.set(String(entry.id), entry);
    });
    const rows = [];
    const seen = new Set();
    effectiveCategories.forEach(item => {
      const id = String(item && item.id || "");
      if (!id || !builtinIdSet.has(id) || seen.has(id)) return;
      seen.add(id);
      const override = draftById.get(id);
      const persistedScopes = persistedOverrideScopes[id] || [];
      const base = override || {
        id,
        target_type: String(item.target_type || ""),
        keywords: (Array.isArray(item.keywords) ? item.keywords : []).map(value => String(value)),
        amount_range: normalizeRuleAmountRange(item.amount_range),
        enabled: item.enabled !== false
      };
      const candidateTarget = String(override && override.target_type || item.target_type || item.archive_folder || "").trim();
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
        overrideScopes: persistedScopes
      });
    });
    (draft.builtinOverrides || []).forEach(entry => {
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
        overrideScopes: persistedOverrideScopes[id] || []
      });
    });
    return rows;
  }, [effectiveCategories, draft, builtinIdSet, persistedOverrideScopes, documentTypes]);
  const categoryNameById = useMemo(() => {
    const entries = effectiveCategories.map(item => ({
      id: item.id,
      name: item.name || item.archive_folder
    }));
    ruleRows.forEach(row => entries.push({
      id: row.id,
      name: row.previewFolder || row.name
    }));
    builtinRows.forEach(row => entries.push({
      id: row.id,
      name: row.previewFolder || row.target_type || row.id
    }));
    return buildRuleCategoryNameMap(entries);
  }, [effectiveCategories, ruleRows, builtinRows]);
  const targetTypeById = useMemo(() => {
    const map = {};
    effectiveCategories.forEach(item => {
      const id = String(item && item.id || "");
      if (id) map[id] = String(item.target_type || "");
    });
    ruleRows.forEach(row => {
      const id = String(row.id || "");
      if (id) map[id] = String(row.target_type || "");
    });
    builtinRows.forEach(row => {
      const id = String(row.id || "");
      if (id) map[id] = String(row.target_type || "");
    });
    return map;
  }, [effectiveCategories, ruleRows, builtinRows]);
  const loadIssues = useMemo(() => normalizeRuleIssues(rulesData && rulesData.issues), [rulesData]);
  const loadWarnings = (rulesData && Array.isArray(rulesData.warnings) ? rulesData.warnings : []).map(item => String(item && (item.text || item.message) || "").trim()).filter(Boolean);
  const unclassifiedInvoices = rulesData && Array.isArray(rulesData.unclassified_invoices) ? rulesData.unclassified_invoices : [];
  const scopeRulesDir = scope === "library" ? rulesData && rulesData.library_rules_dir || "" : rulesData && rulesData.global_rules_dir || "";
  const directoryText = safeText(scopeRulesDir, "尚未创建");
  useEffect(() => {
    let active = true;
    (async () => {
      try {
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
    const customTypes = Array.isArray(payload.custom_types) ? payload.custom_types.map(item => String(item)) : [];
    const documentTypes = Array.isArray(payload.document_types) ? payload.document_types.map(item => String(item)) : [];
    const builtinTypes = Array.isArray(payload.builtin_types) ? payload.builtin_types.map(item => String(item)) : documentTypes.filter(item => customTypes.indexOf(item) < 0);
    const loadedBuiltinIds = Array.isArray(payload.builtin_category_ids) ? payload.builtin_category_ids.map(item => String(item)) : [];
    setTypesState({
      documentTypes,
      customTypes,
      builtinTypes
    });
    setTypeIssues([]);
    setRulesData(payload);
    setLibraryDir(String(payload.library_dir || ""));
    setScopeDrafts({
      global: buildUserRuleDraft(payload.global, "global", loadedBuiltinIds, documentTypes),
      library: buildUserRuleDraft(payload.library, "library", loadedBuiltinIds, documentTypes)
    });
    setDirtyScopes({
      global: false,
      library: false
    });
    setEditor(null);
    setBuiltinEditor(null);
    setRestoreDialog(null);
    setRestoreError("");
    setRestoreIssues([]);
    setSaveIssues([]);
    setLoadError(payload.success === false ? payload.message || "归类规则配置有误，请按提示修正。" : "");
  }
  function applyTypeSnapshot(result, fallbackName, options) {
    const remove = !!(options && options.remove);
    const snapshot = result || {};
    setTypesState(current => {
      let documentTypes = Array.isArray(snapshot.document_types) ? snapshot.document_types.map(item => String(item)) : current.documentTypes;
      let customTypes = Array.isArray(snapshot.custom_types) ? snapshot.custom_types.map(item => String(item)) : current.customTypes;
      const builtinTypes = Array.isArray(snapshot.builtin_types) ? snapshot.builtin_types.map(item => String(item)) : current.builtinTypes;
      if (fallbackName && !Array.isArray(snapshot.document_types)) {
        if (remove) {
          documentTypes = documentTypes.filter(item => item !== fallbackName);
          customTypes = customTypes.filter(item => item !== fallbackName);
        } else {
          if (documentTypes.indexOf(fallbackName) < 0) documentTypes = documentTypes.concat([fallbackName]);
          if (customTypes.indexOf(fallbackName) < 0) customTypes = customTypes.concat([fallbackName]);
        }
      }
      return {
        documentTypes,
        customTypes,
        builtinTypes
      };
    });
  }
  async function reloadRules(options) {
    const silent = !!(options && options.silent);
    if (!silent) setBusyAction("reload");
    setLoadError("");
    try {
      const data = await callApi("load_classification_rules", libraryDir);
      applyRulesData(data);
      if (!silent) setActionState({
        tone: "info",
        message: ""
      });
    } catch (error) {
      setLoadError(error.message || "归类规则加载失败，请稍后重试。");
    } finally {
      setBusyAction("");
    }
  }
  function commitDraft(nextDraft, message, tone) {
    setScopeDrafts(current => Object.assign({}, current, {
      [scope]: nextDraft
    }));
    setDirtyScopes(current => Object.assign({}, current, {
      [scope]: true
    }));
    setSaveIssues([]);
    setActionState(message ? {
      tone: tone || "success",
      message
    } : {
      tone: "info",
      message: ""
    });
    setTestState(current => current.status === "idle" ? current : {
      status: "idle",
      result: null,
      issues: [],
      message: ""
    });
  }
  function handleScopeChange(nextScope) {
    if (nextScope === "library" && !libraryAvailable) return;
    setScope(nextScope);
    setEditor(null);
    setBuiltinEditor(null);
    setSaveIssues([]);
    setActionState({
      tone: "info",
      message: ""
    });
    setTestState({
      status: "idle",
      result: null,
      issues: [],
      message: ""
    });
  }
  function handlePanelChange(nextPanel) {
    setActivePanel(nextPanel);
    setEditor(null);
    setBuiltinEditor(null);
    setActionState({
      tone: "info",
      message: ""
    });
    setTypeIssues([]);
  }
  function handleAddRule() {
    const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const form = emptyUserRuleEditor();
    form.id = nextRuleCategoryId(currentDraft.categories.concat(effectiveCategories));
    setEditor(form);
    setSaveIssues([]);
    setActionState({
      tone: "info",
      message: ""
    });
  }
  function handleEditRule(index) {
    const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const entry = currentDraft.categories[index];
    if (!entry) return;
    setEditor(userRuleEditorFromEntry(entry));
    setSaveIssues([]);
    setActionState({
      tone: "info",
      message: ""
    });
  }
  function handleDeleteRule(index) {
    const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const entry = currentDraft.categories[index];
    if (!entry) return;
    const categories = currentDraft.categories.filter((item, itemIndex) => itemIndex !== index);
    if (editor && String(editor.originalId) === String(entry.id)) setEditor(null);
    commitDraft(Object.assign({}, currentDraft, {
      categories
    }), `已删除规则「${ruleEntryPreviewFolder(entry) || entry.mainKeyword || "未命名规则"}」，保存后生效。`, "info");
  }
  function handleMoveRule(index, direction) {
    const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const categories = currentDraft.categories.slice();
    const targetIndex = index + direction;
    if (index < 0 || targetIndex < 0 || targetIndex >= categories.length) return;
    const moving = categories[index];
    categories[index] = categories[targetIndex];
    categories[targetIndex] = moving;
    commitDraft(Object.assign({}, currentDraft, {
      categories
    }), "已调整规则顺序，保存后生效。", "info");
  }
  function handleToggleRule(index) {
    const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const categories = currentDraft.categories.slice();
    const current = categories[index];
    if (!current) return;
    categories[index] = Object.assign({}, current, {
      enabled: current.enabled === false
    });
    const nextEnabled = categories[index].enabled !== false;
    commitDraft(Object.assign({}, currentDraft, {
      categories
    }), nextEnabled ? "已启用该规则，保存后生效。" : "已停用该规则，保存后生效。", "info");
  }
  function handleEditorChange(patch) {
    setEditor(current => current ? Object.assign({}, current, patch, {
      error: ""
    }) : current);
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
      setEditor(Object.assign({}, editor, {
        error: errors[0]
      }));
      return;
    }
    const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const id = editor.mode === "edit" ? editor.originalId : editor.id || nextRuleCategoryId(currentDraft.categories.concat(effectiveCategories));
    const extraKeywords = (Array.isArray(editor.legacyExtraKeywords) ? editor.legacyExtraKeywords : []).map(item => String(item).trim()).filter(item => item && item !== keyword);
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
      exclude_keywords: (Array.isArray(editor.legacyExcludeKeywords) ? editor.legacyExcludeKeywords : []).slice()
    };
    let categories = currentDraft.categories.slice();
    if (editor.mode === "edit") {
      const index = categories.findIndex(item => String(item.id) === String(editor.originalId));
      if (index >= 0) categories[index] = entry;else categories.push(entry);
    } else {
      categories.push(entry);
    }
    commitDraft(Object.assign({}, currentDraft, {
      categories
    }), editor.mode === "new" ? "已添加规则，保存后生效。" : "已更新规则，保存后生效。", "success");
    setEditor(null);
  }
  function upsertBuiltinOverride(entry, message) {
    const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const overrides = (currentDraft.builtinOverrides || []).slice();
    const index = overrides.findIndex(item => String(item.id) === String(entry.id));
    if (index >= 0) overrides[index] = entry;else overrides.push(entry);
    commitDraft(Object.assign({}, currentDraft, {
      builtinOverrides: overrides
    }), message, "info");
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
      enabled: row.enabled !== false
    });
    setActionState({
      tone: "info",
      message: ""
    });
  }
  function handleBuiltinEditorChange(patch) {
    setBuiltinEditor(current => current ? Object.assign({}, current, patch, {
      error: ""
    }) : current);
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
      setBuiltinEditor(Object.assign({}, builtinEditor, {
        error: errors[0]
      }));
      return;
    }
    upsertBuiltinOverride({
      id: builtinEditor.id,
      target_type: targetType,
      keywords: splitRuleKeywords(builtinEditor.keywordsText),
      amount_range: buildRuleAmountRange(builtinEditor.amountMin, builtinEditor.amountMax),
      enabled: builtinEditor.enabled !== false
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
    setRestoreDialog({
      categoryId: String(categoryId || ""),
      title
    });
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
        category_id: restoreDialog.categoryId || ""
      });
      if (!result || result.success !== true) {
        setRestoreError(result && result.message || "恢复默认失败，请稍后重试。");
        setRestoreIssues(normalizeRuleIssues(result && result.issues));
        return;
      }
      setRestoreDialog(null);
      setActionState({
        tone: "success",
        message: result.message || "已恢复内置规则默认设置。"
      });
      await reloadRules({
        silent: true
      });
    } catch (error) {
      setRestoreError(error.message || "恢复默认失败，请稍后重试。");
    } finally {
      setRestoreBusy(false);
    }
  }
  async function handleCreateType(name) {
    try {
      const result = await callApi("create_classification_type", {
        name
      });
      if (!result || result.success !== true) {
        applyTypeSnapshot(result, name);
        return {
          success: false,
          message: result && result.message || "新建票种失败，请稍后重试。",
          issues: normalizeRuleIssues(result && result.issues)
        };
      }
      applyTypeSnapshot(result, name);
      const createdName = String(name || "").trim();
      setTypeIssues([]);
      setActionState({
        tone: "success",
        message: result && result.message || `已新建票种「${createdName}」。`
      });
      return {
        success: true,
        name: createdName,
        message: result && result.message || ""
      };
    } catch (error) {
      return {
        success: false,
        message: error.message || "新建票种失败，请稍后重试。",
        issues: []
      };
    }
  }
  async function handleDeleteType(name) {
    if (busyAction) return;
    setBusyAction("type");
    try {
      const result = await callApi("delete_classification_type", {
        name,
        library_dir: libraryDir
      });
      if (!result || result.success !== true) {
        applyTypeSnapshot(result, name);
        setTypeIssues(normalizeRuleIssues(result && result.issues));
        setActionState({
          tone: "error",
          message: result && result.message || `删除票种「${name}」失败，请检查是否有规则正在使用它。`
        });
        return;
      }
      applyTypeSnapshot(result, name, {
        remove: true
      });
      setTypeIssues([]);
      if (editor && String(editor.targetType || "") === name) {
        setEditor(Object.assign({}, editor, {
          targetType: ""
        }));
      }
      setActionState({
        tone: "success",
        message: result && result.message || `已删除票种「${name}」。`
      });
    } catch (error) {
      setTypeIssues([]);
      setActionState({
        tone: "error",
        message: error.message || `删除票种「${name}」失败，请稍后重试。`
      });
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
    setActionState({
      tone: "info",
      message: "已按这张发票预填关键词和金额，请选择目标票种后添加到列表。"
    });
  }
  function handleAddRuleTerm(term) {
    const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const entry = cloneRuleTerm(Object.assign({}, term, {
      source_layer: scope
    }), scope);
    commitDraft(Object.assign({}, currentDraft, {
      terms: currentDraft.terms.concat([entry])
    }), "已加入销售方词典，保存后生效。", "success");
  }
  function handleDeleteRuleTerm(index) {
    const currentDraft = scopeDrafts[scope] || buildUserRuleDraft(null, scope, builtinCategoryIds, documentTypes);
    const terms = currentDraft.terms.filter((item, itemIndex) => itemIndex !== index);
    commitDraft(Object.assign({}, currentDraft, {
      terms
    }), "已从销售方词典移除，保存后生效。", "info");
  }
  async function handleSaveRules() {
    if (saving) return;
    if (missingTargetCount > 0 || missingBuiltinTargetCount > 0) {
      const parts = [];
      if (missingTargetCount > 0) parts.push(`${missingTargetCount} 条自定义规则`);
      if (missingBuiltinTargetCount > 0) parts.push(`${missingBuiltinTargetCount} 条内置规则修改`);
      setActionState({
        tone: "error",
        message: `还有 ${parts.join("、")}没有选择目标票种，请逐条编辑补选后再保存。`
      });
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
        terms: draft.terms.map(toSaveRuleTerm)
      });
      if (!result || result.success !== true) {
        setSaveIssues(normalizeRuleIssues(result && result.issues));
        setActionState({
          tone: "error",
          message: result && result.message || "规则保存失败，请检查目标票种、关键词与金额范围。"
        });
        return;
      }
      setDirtyScopes(current => Object.assign({}, current, {
        [scope]: false
      }));
      setActionState({
        tone: "success",
        message: result.message || "规则已保存，下一次整理生效。"
      });
      await reloadRules({
        silent: true
      });
    } catch (error) {
      setActionState({
        tone: "error",
        message: error.message || "规则保存失败，请稍后重试。"
      });
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
        setActionState({
          tone: "error",
          message: result && result.message || "恢复默认失败，请稍后重试。"
        });
        return;
      }
      setActionState({
        tone: "success",
        message: result.message || "已恢复默认规则。"
      });
      await reloadRules({
        silent: true
      });
    } catch (error) {
      setActionState({
        tone: "error",
        message: error.message || "恢复默认失败，请稍后重试。"
      });
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
        message: result && result.message || (opened ? "已打开规则目录。" : "打开规则目录失败。")
      });
    } catch (error) {
      setActionState({
        tone: "error",
        message: error.message || "打开规则目录失败。"
      });
    } finally {
      setBusyAction("");
    }
  }
  async function handleTestRules() {
    setTestState({
      status: "testing",
      result: null,
      issues: [],
      message: ""
    });
    try {
      const result = await callApi("test_classification_rules", {
        library_dir: libraryDir,
        scope,
        draft: {
          categories: draft.categories.map(toSaveUserRule),
          terms: draft.terms.map(toSaveRuleTerm),
          fallback: draft.fallback || ""
        },
        fields: {
          seller: String(testFields.seller || "").trim(),
          seller_tin: String(testFields.seller_tin || "").trim(),
          item: String(testFields.item || "").trim(),
          type: String(testFields.type || "").trim(),
          amount: String(testFields.amount || "").trim()
        }
      });
      if (!result || result.success !== true) {
        setTestState({
          status: "error",
          result: null,
          issues: normalizeRuleIssues(result && result.issues),
          message: result && result.message || "规则测试失败，请检查输入内容。"
        });
        return;
      }
      setTestState({
        status: "success",
        result: result.result || null,
        issues: [],
        message: ""
      });
    } catch (error) {
      setTestState({
        status: "error",
        result: null,
        issues: [],
        message: error.message || "规则测试失败，请稍后重试。"
      });
    }
  }
  function updateTestField(field, value) {
    setTestFields(current => Object.assign({}, current, {
      [field]: value
    }));
  }
  return /*#__PURE__*/React.createElement(AppShell, {
    active: "rules",
    onOpenDisclaimer: onOpenDisclaimer,
    footerLeft: /*#__PURE__*/React.createElement("div", {
      className: "footer-cluster"
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn btn--ghost btn--sm",
      onClick: () => reloadRules(),
      disabled: busyAction === "reload"
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, busyAction === "reload" ? "sync" : "refresh"), /*#__PURE__*/React.createElement("span", null, busyAction === "reload" ? "加载中..." : "重新加载")), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn btn--ghost btn--sm",
      onClick: handleOpenRulesFolder,
      disabled: busyAction === "folder"
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, "folder_open"), /*#__PURE__*/React.createElement("span", null, "\u6253\u5F00\u89C4\u5219\u76EE\u5F55")), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn btn--ghost btn--sm",
      onClick: handleResetScope,
      disabled: busyAction === "reset"
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, "restart_alt"), /*#__PURE__*/React.createElement("span", null, busyAction === "reset" ? "恢复中..." : "恢复默认"))),
    footerRight: /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn btn--primary",
      onClick: handleSaveRules,
      disabled: saving || loading || missingTargetCount > 0 || missingBuiltinTargetCount > 0
    }, /*#__PURE__*/React.createElement("span", {
      className: "material-symbols-outlined"
    }, saving ? "sync" : "save"), /*#__PURE__*/React.createElement("span", null, saving ? "保存中..." : "保存规则"))
  }, /*#__PURE__*/React.createElement("div", {
    className: "page-wrap page-wrap--rules"
  }, /*#__PURE__*/React.createElement(PageHeader, {
    title: UI_COPY.pages.rules.title,
    description: UI_COPY.pages.rules.description,
    badge: /*#__PURE__*/React.createElement(StatusPill, {
      tone: dirty ? "warning" : "success",
      icon: dirty ? "edit" : "task_alt"
    }, dirty ? "有未保存修改" : "规则已加载")
  }), loading && !rulesData ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "info"
  }, "\u6B63\u5728\u52A0\u8F7D\u5F52\u7C7B\u89C4\u5219...") : null, loadError ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "error"
  }, loadError) : null, actionState.message ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: actionState.tone
  }, actionState.message) : null, loadIssues.length > 0 ? /*#__PURE__*/React.createElement(RuleIssues, {
    issues: loadIssues,
    title: "\u89C4\u5219\u6587\u4EF6\u5B58\u5728\u95EE\u9898"
  }) : null, loadWarnings.length > 0 ? /*#__PURE__*/React.createElement(RuleIssues, {
    issues: loadWarnings,
    title: "\u89C4\u5219\u6587\u4EF6\u63D0\u793A",
    tone: "warning"
  }) : null, saveIssues.length > 0 ? /*#__PURE__*/React.createElement(RuleIssues, {
    issues: saveIssues,
    title: "\u89C4\u5219\u6821\u9A8C\u672A\u901A\u8FC7\uFF0C\u8BF7\u4FEE\u6B63\u540E\u518D\u6B21\u4FDD\u5B58"
  }) : null, /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "layers",
    title: "\u89C4\u5219\u4F5C\u7528\u8303\u56F4",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: dirty ? "warning" : "neutral"
    }, `${draft.categories.length} 条自定义规则`)
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rules-scope-tabs",
    role: "group",
    "aria-label": "\u89C4\u5219\u4F5C\u7528\u8303\u56F4"
  }, RULE_SCOPE_OPTIONS.map(option => {
    const optionDisabled = option.value === "library" && !libraryAvailable;
    return /*#__PURE__*/React.createElement("button", {
      key: option.value,
      type: "button",
      className: joinClasses("quick-chip", scope === option.value && "is-active"),
      "aria-pressed": scope === option.value,
      disabled: optionDisabled,
      onClick: () => handleScopeChange(option.value)
    }, option.label);
  })), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, ruleScopeDescription(scope)), /*#__PURE__*/React.createElement("p", {
    className: "field-help field-help--subtle u-mono u-truncate",
    title: directoryText
  }, "\u89C4\u5219\u6587\u4EF6\uFF1A", directoryText), /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u5728\u754C\u9762\u4FDD\u5B58\u4F1A\u91CD\u5199\u5F53\u524D\u4F5C\u7528\u8303\u56F4\u7684\u89C4\u5219\u6587\u4EF6\uFF1B\u5982\u9700\u4FDD\u7559 YAML \u6CE8\u91CA\uFF0C\u8BF7\u76F4\u63A5\u7F16\u8F91\u89C4\u5219\u6587\u4EF6\u3002"), !libraryAvailable ? /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u6682\u672A\u8BC6\u522B\u5230\u5F53\u524D\u53D1\u7968\u5E93\uFF1A\u5148\u5B8C\u6210\u4E00\u6B21\u672C\u5730\u6574\u7406\u6216\u9009\u62E9\u8F93\u51FA\u76EE\u5F55\u540E\uFF0C\u624D\u80FD\u5207\u6362\u300C\u5F53\u524D\u53D1\u7968\u5E93\u300D\u5E76\u4FDD\u5B58\u5E93\u5185\u89C4\u5219\u3002") : null)), /*#__PURE__*/React.createElement("div", {
    className: "rules-tabbar",
    role: "tablist",
    "aria-label": "\u5F52\u7C7B\u89C4\u5219\u5206\u533A"
  }, RULE_PANEL_OPTIONS.map(option => /*#__PURE__*/React.createElement("button", {
    key: option.value,
    type: "button",
    role: "tab",
    "aria-selected": activePanel === option.value,
    className: joinClasses("quick-chip", activePanel === option.value && "is-active"),
    onClick: () => handlePanelChange(option.value)
  }, option.label))), activePanel === "tools" ? /*#__PURE__*/React.createElement("div", {
    className: "rules-tools-layout"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rules-column"
  }, /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "experiment",
    title: "\u89C4\u5219\u6D4B\u8BD5",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "info"
    }, "\u4E0D\u5199\u5165\u89C4\u5219\u6587\u4EF6")
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u7528\u5F53\u524D\u7F16\u8F91\u4E2D\u7684\u89C4\u5219\u8BD5\u7B97\u4E00\u5F20\u53D1\u7968\uFF0C\u4E0D\u4F1A\u5199\u5165\u89C4\u5219\u6587\u4EF6\uFF0C\u4E5F\u4E0D\u5F71\u54CD\u5DF2\u4FDD\u5B58\u914D\u7F6E\u3002"), /*#__PURE__*/React.createElement("div", {
    className: "rules-test-grid"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u9500\u552E\u65B9"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "field-input",
    placeholder: "\u5982 \u67D0\u67D0\u9910\u996E\u7BA1\u7406\u6709\u9650\u516C\u53F8",
    value: testFields.seller,
    onChange: event => updateTestField("seller", event.target.value)
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u9500\u552E\u65B9\u7A0E\u53F7"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "field-input u-mono",
    placeholder: "\u53EF\u9009",
    value: testFields.seller_tin,
    onChange: event => updateTestField("seller_tin", event.target.value)
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u53D1\u7968\u660E\u7EC6"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "field-input",
    placeholder: "\u5982 \u9910\u996E\u670D\u52A1",
    value: testFields.item,
    onChange: event => updateTestField("item", event.target.value)
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u7968\u79CD"), /*#__PURE__*/React.createElement(DarkSelect, {
    value: testFields.type,
    options: [{
      value: "",
      label: "不限票种"
    }].concat(documentTypes.map(type => ({
      value: type,
      label: type
    }))),
    onChange: value => updateTestField("type", value),
    ariaLabel: "\u6D4B\u8BD5\u7968\u79CD"
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-block"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "\u91D1\u989D"), /*#__PURE__*/React.createElement("div", {
    className: "field-shell"
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    inputMode: "decimal",
    className: "field-input u-tabular",
    placeholder: "\u5982 128.00",
    value: testFields.amount,
    onChange: event => updateTestField("amount", event.target.value)
  })))), /*#__PURE__*/React.createElement("div", {
    className: "footer-cluster"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--secondary btn--sm",
    onClick: handleTestRules,
    disabled: testState.status === "testing"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, testState.status === "testing" ? "sync" : "play_arrow"), /*#__PURE__*/React.createElement("span", null, testState.status === "testing" ? "测试中..." : "测试归类结果")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--ghost btn--sm",
    onClick: () => setTestState({
      status: "idle",
      result: null,
      issues: [],
      message: ""
    })
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "clear_all"), /*#__PURE__*/React.createElement("span", null, "\u6E05\u7A7A\u7ED3\u679C"))), testState.message ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: testState.status === "error" ? "error" : "info"
  }, testState.message) : null, testState.issues.length > 0 ? /*#__PURE__*/React.createElement(RuleIssues, {
    issues: testState.issues,
    title: "\u6D4B\u8BD5\u6821\u9A8C\u672A\u901A\u8FC7"
  }) : null, /*#__PURE__*/React.createElement(RuleTestResult, {
    result: testState.result,
    categoryNameById: categoryNameById,
    targetTypeById: targetTypeById
  })))), /*#__PURE__*/React.createElement("div", {
    className: "rules-column"
  }, /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "menu_book",
    title: "\u9500\u552E\u65B9\u8BCD\u5178",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "info"
    }, `${draft.terms.length} 条`)
  }), /*#__PURE__*/React.createElement(RuleDictionarySection, {
    terms: draft.terms,
    categoryOptions: ruleRows,
    scope: scope,
    onAddTerm: handleAddRuleTerm,
    onDeleteTerm: handleDeleteRuleTerm
  })))) : activePanel === "types" ? /*#__PURE__*/React.createElement(RuleTypesManager, {
    builtinTypes: typesState.builtinTypes,
    customTypes: typesState.customTypes,
    issues: typeIssues,
    busy: busyAction === "type",
    onDeleteType: handleDeleteType
  }) : /*#__PURE__*/React.createElement("div", {
    className: "rules-panel"
  }, /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "info"
  }, RULE_ORDER_HELP), missingTargetCount > 0 ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, "\u6709 ", missingTargetCount, " \u6761\u5386\u53F2\u89C4\u5219\u8FD8\u6CA1\u6709\u9009\u62E9\u76EE\u6807\u7968\u79CD\uFF0C\u8BF7\u9010\u6761\u7F16\u8F91\u8865\u9009\u540E\u518D\u4FDD\u5B58\u3002") : null, missingBuiltinTargetCount > 0 ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, "\u6709 ", missingBuiltinTargetCount, " \u6761\u5185\u7F6E\u89C4\u5219\u4FEE\u6539\u8FD8\u6CA1\u6709\u9009\u62E9\u76EE\u6807\u7968\u79CD\uFF0C\u8BF7\u9010\u6761\u7F16\u8F91\u8865\u9009\u540E\u518D\u4FDD\u5B58\u3002") : null, /*#__PURE__*/React.createElement(RuleUnclassifiedSection, {
    invoices: unclassifiedInvoices,
    onPrefill: handlePrefillFromInvoice
  }), /*#__PURE__*/React.createElement("div", {
    className: "rules-layout"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rules-column rules-column--main"
  }, /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "rule",
    title: "\u81EA\u5B9A\u4E49\u89C4\u5219"
  }), /*#__PURE__*/React.createElement("div", {
    className: "card-stack card-stack--compact"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rules-toolbar"
  }, /*#__PURE__*/React.createElement("p", {
    className: "field-help"
  }, "\u6BCF\u6761\u89C4\u5219\u7531\u76EE\u6807\u7968\u79CD\u3001\u5173\u952E\u8BCD\u548C\u91D1\u989D\u8303\u56F4\u7EC4\u6210\uFF0C\u6587\u4EF6\u5939\u6309\u300C\u76EE\u6807\u7968\u79CD + \u91D1\u989D\u8303\u56F4\u300D\u81EA\u52A8\u751F\u6210\u3002"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn btn--secondary btn--sm",
    onClick: handleAddRule
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "add"), /*#__PURE__*/React.createElement("span", null, "\u65B0\u589E\u89C4\u5219"))), ruleRows.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "rules-empty-state"
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "rule"), /*#__PURE__*/React.createElement("p", null, "\u5F53\u524D\u4F5C\u7528\u8303\u56F4\u8FD8\u6CA1\u6709\u81EA\u5B9A\u4E49\u89C4\u5219\uFF0C\u70B9\u51FB\u300C\u65B0\u589E\u89C4\u5219\u300D\u521B\u5EFA\u7B2C\u4E00\u6761\u89C4\u5219\u3002")) : /*#__PURE__*/React.createElement("div", {
    className: "rules-category-list"
  }, ruleRows.map(row => /*#__PURE__*/React.createElement("div", {
    key: String(row.id || row.index),
    className: joinClasses("rule-category-row", row.enabled === false && "is-disabled")
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-category-row__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rule-category-row__title"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rule-category-row__folder-icon material-symbols-outlined"
  }, "folder"), /*#__PURE__*/React.createElement("span", {
    className: joinClasses("rule-category-row__name", "u-truncate", !row.previewFolder && "rule-category-row__name--missing"),
    title: row.previewFolder || "请选择目标票种"
  }, row.previewFolder || "请选择目标票种"), row.target_type ? /*#__PURE__*/React.createElement("span", {
    className: "rule-target-tag",
    title: `目标票种：${row.target_type}`
  }, row.target_type) : /*#__PURE__*/React.createElement(StatusPill, {
    tone: "warning"
  }, "\u7F3A\u5C11\u76EE\u6807\u7968\u79CD"), row.enabled === false ? /*#__PURE__*/React.createElement(StatusPill, {
    tone: "warning"
  }, "\u5DF2\u505C\u7528") : null), /*#__PURE__*/React.createElement("div", {
    className: "rule-category-row__meta"
  }, /*#__PURE__*/React.createElement("span", null, "\u5173\u952E\u8BCD ", /*#__PURE__*/React.createElement("strong", null, safeText(row.mainKeyword, "未填写"))), /*#__PURE__*/React.createElement("span", null, "\u91D1\u989D ", /*#__PURE__*/React.createElement("strong", null, formatRuleAmountRangeLabel(row.amount_range))), row.target_type && documentTypes.length > 0 && documentTypes.indexOf(row.target_type) < 0 ? /*#__PURE__*/React.createElement(StatusPill, {
    tone: "error"
  }, "\u7968\u79CD\u5DF2\u5931\u6548") : null)), /*#__PURE__*/React.createElement("div", {
    className: "rule-category-row__actions"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: joinClasses("rule-icon-button", row.enabled !== false && "is-active"),
    title: row.enabled !== false ? "停用" : "启用",
    "aria-label": `${row.enabled !== false ? "停用" : "启用"} ${row.previewFolder || "规则"}`,
    onClick: () => handleToggleRule(row.index)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, row.enabled !== false ? "toggle_on" : "toggle_off")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "rule-icon-button",
    title: "\u4E0A\u79FB",
    "aria-label": `上移 ${row.previewFolder || "规则"}`,
    disabled: row.index === 0,
    onClick: () => handleMoveRule(row.index, -1)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "arrow_upward")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "rule-icon-button",
    title: "\u4E0B\u79FB",
    "aria-label": `下移 ${row.previewFolder || "规则"}`,
    disabled: row.index === ruleRows.length - 1,
    onClick: () => handleMoveRule(row.index, 1)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "arrow_downward")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "rule-icon-button",
    title: "\u7F16\u8F91",
    "aria-label": `编辑 ${row.previewFolder || "规则"}`,
    onClick: () => handleEditRule(row.index)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "edit")), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "rule-icon-button rule-icon-button--danger",
    title: "\u5220\u9664",
    "aria-label": `删除 ${row.previewFolder || "规则"}`,
    onClick: () => handleDeleteRule(row.index)
  }, /*#__PURE__*/React.createElement("span", {
    className: "material-symbols-outlined"
  }, "delete"))))))))), /*#__PURE__*/React.createElement("div", {
    className: "rules-column rules-column--side"
  }, builtinEditor ? null : /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: editor && editor.mode === "edit" ? "edit_note" : "add_circle",
    title: editor ? editor.mode === "new" ? "新增规则" : "编辑规则" : "规则编辑",
    indicator: editor ? /*#__PURE__*/React.createElement(StatusPill, {
      tone: "info"
    }, ruleScopeLabel(scope)) : null
  }), /*#__PURE__*/React.createElement(RuleEditor, {
    editor: editor,
    documentTypes: documentTypes,
    onChange: handleEditorChange,
    onCreateType: handleCreateType,
    onCommit: handleEditorCommit,
    onCancel: () => {
      setEditor(null);
      setSaveIssues([]);
    }
  })))), builtinEditor ? /*#__PURE__*/React.createElement("section", {
    className: "surface-card"
  }, /*#__PURE__*/React.createElement(SectionHeader, {
    icon: "edit_note",
    title: builtinEditor.label ? `编辑内置规则：${builtinEditor.label}` : "编辑内置规则",
    indicator: /*#__PURE__*/React.createElement(StatusPill, {
      tone: "info"
    }, ruleScopeLabel(scope))
  }), /*#__PURE__*/React.createElement(RuleBuiltinEditor, {
    editor: builtinEditor,
    documentTypes: documentTypes,
    onChange: handleBuiltinEditorChange,
    onCreateType: handleCreateType,
    onCommit: handleBuiltinEditorCommit,
    onCancel: () => setBuiltinEditor(null)
  })) : null, /*#__PURE__*/React.createElement(RuleBuiltinSection, {
    rows: builtinRows,
    busy: saving || restoreBusy,
    onEdit: handleEditBuiltinRule,
    onToggle: handleToggleBuiltinRule,
    onRestore: handleRestoreBuiltinRule,
    onRestoreAll: handleRestoreAllBuiltin
  }))), /*#__PURE__*/React.createElement(RuleRestoreDialog, {
    dialog: restoreDialog,
    mode: restoreMode,
    busy: restoreBusy,
    error: restoreError,
    issues: restoreIssues,
    libraryAvailable: libraryAvailable,
    scopeLabel: ruleScopeLabel(scope),
    dirty: dirty,
    onModeChange: setRestoreMode,
    onConfirm: handleConfirmRestoreBuiltin,
    onCancel: () => {
      setRestoreDialog(null);
      setRestoreError("");
      setRestoreIssues([]);
    }
  }));
}
function App() {
  const [showDisclaimer, setShowDisclaimer] = useState(false);
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(MemoryRouter, null, /*#__PURE__*/React.createElement(Routes, null, /*#__PURE__*/React.createElement(Route, {
    path: "/",
    element: /*#__PURE__*/React.createElement(SettingsPage, {
      onOpenDisclaimer: () => setShowDisclaimer(true)
    })
  }), /*#__PURE__*/React.createElement(Route, {
    path: "/processing",
    element: /*#__PURE__*/React.createElement(ProcessingPage, {
      onOpenDisclaimer: () => setShowDisclaimer(true)
    })
  }), /*#__PURE__*/React.createElement(Route, {
    path: "/analysis",
    element: /*#__PURE__*/React.createElement(AnalysisPage, {
      onOpenDisclaimer: () => setShowDisclaimer(true)
    })
  }), /*#__PURE__*/React.createElement(Route, {
    path: "/rules",
    element: /*#__PURE__*/React.createElement(RulesPage, {
      onOpenDisclaimer: () => setShowDisclaimer(true)
    })
  }))), /*#__PURE__*/React.createElement(DisclaimerDialog, {
    open: showDisclaimer,
    onClose: () => setShowDisclaimer(false)
  }));
}
document.title = APP_BRAND.name;
const root = createRoot(document.getElementById("root"));
root.render( /*#__PURE__*/React.createElement(App, null));

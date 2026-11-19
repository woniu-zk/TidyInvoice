/*! InvoiceFlowAI 前端产物 - 由 tools/compile-frontend.mjs 依据 templates/index_app.js 生成，请勿手改。 */
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
const APP_BRAND = {
  name: "InvoiceFlowAI",
  subtitle: "AI发票管家"
};
const APP_VISIBLE_COPY = {
  topSubtitle: "AI发票管家",
  footerVersion: "InvoiceFlowAI",
  footerStamp: "P-H-Dx",
  githubLabel: "产品官网",
  githubUrl: "https://github.com/EthanYoQ/Invoice-Downloader",
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
      reviewIdle: "结果明细仍可导出查看，输出目录会保留本轮成功归档结果。"
    }
  }
};
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
const SESSION_SETTINGS_KEY = "invoiceflow.session.settings";
const SESSION_RUN_SETTINGS_KEY = "invoiceflow.session.runSettings";
const CONTROLLED_AUTOSTART_PREFIX = "invoiceflow.controlledAutostart";
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
  const [settingsRes, runContextRes] = await Promise.all([callApi("load_user_settings"), callApi("get_run_context").catch(() => ({}))]);
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
    runContext
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
  }, "\u65E0\u9700\u8054\u7F51\u3001\u65E0\u9700\u586B\u5199\u5BC6\u94A5\uFF0C\u652F\u6301\u7535\u5B50\u53D1\u7968\u3001OFD \u7248\u5F0F\u6587\u4EF6\u4E0E\u626B\u63CF\u4EF6\u7684\u672C\u5730\u89E3\u6790\uFF0C\u7968\u636E\u5185\u5BB9\u4E0D\u4F1A\u4E0A\u4F20\u3002"))), isLocalMode ? null : /*#__PURE__*/React.createElement("section", {
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
    contentScrollable: false,
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
  }, card)))), quotaExhausted && quotaMessage ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, quotaMessage) : null, processingErrorCount > 0 ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "warning"
  }, "\u68C0\u6D4B\u5230 ", processingErrorCount, " \u6761\u771F\u5B9E\u5F02\u5E38\uFF0C\u8BF7\u901A\u8FC7\u201C\u5BFC\u51FA\u7ED3\u679C\u660E\u7EC6\u201D\u7EE7\u7EED\u6392\u67E5\u3002") : null)), loadingError ? /*#__PURE__*/React.createElement(NoticeBox, {
    tone: "error"
  }, loadingError) : null, manualCheckCount > 0 ? /*#__PURE__*/React.createElement(ResultActionBanner, {
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
  }))), /*#__PURE__*/React.createElement(DisclaimerDialog, {
    open: showDisclaimer,
    onClose: () => setShowDisclaimer(false)
  }));
}
const root = createRoot(document.getElementById("root"));
root.render( /*#__PURE__*/React.createElement(App, null));

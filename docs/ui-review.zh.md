# 前端 UI 审核报告（2026-11-25）

范围：`templates/index.html`（样式与设计令牌）、`templates/index_app.js`（React/JSX 界面）、`templates/brand.generated.js` 与 `brand.json` 的品牌呈现。
结论：**P0（客观缺陷：对比度、中文排版、键盘可达性、读屏语义、品牌残留）已在本次修复；P1/P2 属于结构性与视觉识别层面的改写，只出方案，未实施。**

> 说明：本轮开始前工作区已存在大量未提交改动（`README*.md`、`app_api.py`、`docs/project-overview.zh.md`、`tests/test_ai_provider.py`、`tests/test_frontend_build_contract.py` 等，以及 `templates/index_app.js` 中既有的界面重构）。本报告的"改前"数据取自本会话开始时的工作区快照，与 `HEAD` 不一致，复核时请以自身基线为准。

## 1. 审核方法与证据

| 环节 | 做法 |
| --- | --- |
| 技能选型 | 已安装的 ui-skills 中取 2 个：`ui-skills-root`（路由）→ `improve-ui`（既有界面改进清单）+ `frontend-design`（视觉语言与 AI 默认风格识别）。`npx ui-skills` CLI 在本机被沙箱挡住 npm 缓存（EPERM），因此直接使用 `~/.agents/skills` 下的已安装全文。 |
| 静态审核 | 阅读 1650 行页面（含约 1590 行 CSS）与 4456 行 JSX，统计字号/圆角/字距/大写变换的分布，核对 `tests/test_frontend_build_contract.py` 等契约测试中的界面字面量断言。 |
| 计算样式 | 用 Playwright + `http.server` 直接渲染真实产物，注入 mock 的 `window.pywebview.api`（`tmp/ui-audit/run_shots.py`），读取 `getComputedStyle`，避免"看代码猜效果"。 |
| 对比度 | 按 sRGB 合成（页面渐变 → `--panel` → 卡片白叠加）后用 WCAG 2.1 相对亮度公式计算，深/浅两套主题分别算。 |
| 键盘走查 | 自动 Tab 序列逐元素读取 `outline-*` 计算值；检查图标按钮可访问名称、输入框 label 关联、弹层焦点归属。 |
| 回归 | `pytest` 全量 + ruff + `compile-frontend --check` + `brand/generate --check` + `brand/check`。 |

## 2. P0 已修清单

### 2.1 对比度与设计令牌（`templates/index.html`）

| 问题 | 改前（实测） | 改动 | 改后（实测） |
| --- | --- | --- | --- |
| 二级文字整体不达 AA | `--text-dim` = `rgba(208,220,242,0.46)`，卡片 **3.63:1**、卡片头 **3.54:1**；浅色主题 **3.38:1**。该令牌承载 `field-help`、导航副标题、卡片标签、页脚说明等 30 处 | 深色 `:root` 与浅色 `:root[data-theme="light"]` 均改为 `0.60` / `0.65`（见 `index.html:29`、`index.html:1384`） | 卡片 **5.25:1**、卡片头 **5.02:1**、浅色 **5.05:1** |
| 只读路径框的空状态提示几乎不可见 | `.field-input::placeholder` = `0.22` alpha → **1.77:1**；"请选择本地输出目录"这类说明实际读不到 | 占位符、`.rule-textarea::placeholder`、`.field-help--subtle` 统一改用 `var(--text-dim)` | 深色 **5.41:1**、浅色 **5.05:1** |
| 主按钮白字不达 AA | `.btn--primary` 渐变 `#5f9bff → #3476ff`，白字 **2.76–4.05:1**（12px 正文） | 渐变改为 `#2f6ad9 → #2358c4`（`index.html:1096`）；品牌蓝 `--blue` 仍用于图标、强调文字与焦点环 | 白字 **5.02–6.43:1** |
| 焦点环没有令牌 | 仅窗口按钮有 `:focus-visible`；其余依赖浏览器默认环 | 新增 `--focus-ring`（深 `#7fb0ff` / 浅 `#2563eb`）与统一焦点环规则（`index.html:1349`） | 见 2.3 |

### 2.2 中文排版（`templates/index.html`）

| 问题 | 证据 | 改动 |
| --- | --- | --- |
| 中文标签套用拉丁排版手法 | `text-transform: uppercase` **11 处**，`letter-spacing` **22 处**；`.section-title` 是 11px + `0.14em` + uppercase，`.page-eyebrow` 10px + `0.16em` + uppercase，`.modal-label` 12px + `0.18em`；对 CJK 而言 uppercase 无效、字距只是把汉字拉开 | uppercase 全部移除（现 0 处），字距收敛到 `≤0.02em`（现 9 处），仅保留等宽路径与数字场景 |
| 中文标题被负字距挤压 | `.page-title` `-0.05em`（32px 下每字 -1.6px）、`.progress-title` `-0.04em` | 改为 `-0.01em`；负字距只留给 `u-tabular` 数字 |
| 正文与辅助文字过小 | 92 条字号声明中 37 条小于 12px；`field-help` 10.5px、`section-title` 11px、`metric-card__label` 10px、`sidebar-subtitle` 10px、`run-log` 11px | 引入 `--fs-xs: 12px` / `--fs-sm: 13px`（`index.html:31`），正文与辅助文字统一到 12px，卡片标题提升到 13px；字号种类 17 → 14，<12px 声明仅剩 4 处（侧栏品牌微文案与页签角标） |

### 2.3 键盘与读屏（`index.html` + `index_app.js`）

| 问题 | 改动 |
| --- | --- |
| 大多数按钮/页签/图标按钮只有浏览器默认焦点环，样式不统一，且全局 `transition: all` 让焦点环淡入 160ms | 统一焦点环覆盖 12 类控件（`.btn`、`.quick-chip`、`.sidebar-nav__item`、`.settings-tab`、`.rule-icon-button` 等），并 `transition: none` 保证即时反馈（`index.html:1349`）；Tab 实测 `outline: solid 2px rgb(127,176,255)` |
| 装饰性图标全部进入可访问名称（85 个 Material Symbols 字形） | 全部 `aria-hidden="true"`，可访问名称统计：图标按钮 0 个缺名（自动检查 `.unnamed === []`） |
| 29 个 `<label class="field-label">` 未与输入框关联，`htmlFor` 为 0，点击标签不聚焦 | 21 组生成 `id`/`htmlFor` 配对（`field-2`…`field-21`）；`DateField` 改为接收 `id` 属性并在首页传 `run-date-from`/`run-date-to`，避免同一组件重复渲染时 id 冲突（`index_app.js:1341`）；纯自定义下拉（`DarkSelect`）保留其自带 `ariaLabel` |
| 首页"输出目录"只读框没有任何可访问名称 | 补 `aria-label={copy.outputTitle}`（`index_app.js:1946`） |
| 两个弹层不是对话框语义、无焦点管理 | 免责声明（`index_app.js:1534`）与恢复默认（`index_app.js:2952`）加 `role="dialog"`、`aria-modal="true"`、`aria-labelledby`、`tabIndex={-1}`，打开时聚焦卡片、关闭时把焦点还给触发按钮；关闭按钮补 `aria-label` |
| 进度条无进度语义、运行状态不播报 | `.progress-track` 加 `role="progressbar"` + `aria-valuemin/max/now`，运行容器加 `aria-live="polite"`（`index_app.js:2035`、`2048`） |
| 侧栏当前页只靠颜色区分 | 当前导航项补 `aria-current="page"`（`index_app.js:1588`） |
| 授权码显隐按钮无名称、无状态 | 补 `aria-label` + `aria-pressed`（`index_app.js:2249`） |
| 窗口交通灯点击区仅 14×14，低于 24×24 最小值 | 视觉保持 14px，`::after` 扩展命中区到 24px（`index.html:1371`） |
| 无 `prefers-reduced-motion` 处理，进度条扫描动画无限循环 | 新增媒体查询（`index.html:1642`），关闭动效与位移动效 |

### 2.4 品牌呈现（`index_app.js`）

- 侧栏 Logo 硬编码 `"IF"`（上游 InvoiceFlow 残留），与 `brand.json` 的 `整票 / TidyInvoice` 不符。改为运行时取 `nameEn` 前两位（`APP_MONOGRAM`，`index_app.js:74`、`1575`），产物中不出现任何品牌字面量，`test_brand_consistency.py` 仍通过。

## 3. 复测结果

| 指标 | 改前 | 改后 |
| --- | --- | --- |
| 二级文字对比度（深/浅） | 3.63 / 3.38 | **5.25 / 5.05** |
| 占位提示对比度 | 1.77 | **5.41** |
| 主按钮白字对比度 | 2.76–4.05 | **5.02–6.43** |
| `text-transform: uppercase` | 11 处 | **0** |
| 字号种类 / <12px 声明 | 17 种 / 37 条 | **14 种 / 4** |
| `aria-hidden` 装饰图标 | 0 | **85** |
| `htmlFor` 关联 | 0 | **21** |
| 无名称的可见按钮 | 未测 | **0** |
| 键盘焦点环 | 仅窗口按钮 | **12 类控件，2px 即时显示** |
| `role="dialog"` / `progressbar` / `aria-current` | 0 / 0 / 0 | **2 / 1 / 1** |

门禁：`pytest` 1462 passed / 2 skipped / 1 deselected（机器绑定用例按 AGENTS.md deselect）；`ruff check .` 通过；`compile-frontend --check` 与 `brand/generate --check`、`brand/check` 均通过；`index_app.built.js` 已随源码重编译。

## 4. P1 建议（结构层）与处理状态

> 第二轮"版式重构（账册）"落地了 P1-1/2/3/4/6/8/9 与大部分 P2；**第三轮已把视觉语言整体切换为 Apple/macOS**（账册版废弃），当前设计契约见 [ui-design.zh.md](ui-design.zh.md)，改造计划与决策记录见 [ui-apple-plan.zh.md](ui-apple-plan.zh.md)。

| 编号 | 问题与证据 | 建议 | 状态 |
| --- | --- | --- | --- |
| P1-1 | 首页首屏是 6 张同构卡片，真正的结果（处理进度）排在最末，1440×900 下首屏看不到 | 把"启动 + 处理进度"提升到首屏 | **已完成**：顺序改为 页头 → 任务模式 + 开始 → 处理进度 → 配置账册；空状态压缩为一行虚线框 |
| P1-2 | 三个任务按钮平铺，模式与动作混在同一排 | 先选模式，再点唯一主按钮 | **已完成**：`.mode-picker` 三格单选（`role="radio"`）+ 单一「开始处理」 |
| P1-3 | 装饰性状态胶囊 5–6 个/屏："只读"（绿色+眼睛图标，语义错配）、"邮箱任务"、"三种方式" | 只保留有决策价值的标记 | **已完成**：删除"只读""邮箱任务""三种方式"；状态改为方点+文字，保留"已选择/待选择/已锁定" |
| P1-4 | 结果页 7 个同构表面：hero + 3 统计卡 + 3 个 banner | 合并为账册式结果页 | **已完成**：hero 为单张抬起的纸、统计为等宽数字三格（顶部语义色条）、banner 改为"左侧色条 + 规则线"的行 |
| P1-5 | `window.alert` 4 处阻断式报错 | 改内联状态 | **未做**（保留在待办：HomePage 停止/窗口控制、AnalysisPage 导出） |
| P1-6 | 窗口标题区三处重复表达"你在首页"；侧栏底部重复渲染品牌名 | 顶栏只留一次品牌 | **已完成**：顶栏 = 品牌角标 + 名称 + 页签 + 动作 + 窗口控件；页脚只保留页面状态与次操作 |
| P1-7 | 行话与开发语气：日志级别 `INFO/SUCCESS/WARNING` 直出；"系统已保全…"；`footerText: "当前页: 设置"` 死文案 | 中文化/改写/删除 | **已完成**：日志级别映射为 信息/成功/提醒/异常（未知级别原样回退）；"系统已保全但未纳入成功归档" → "已保留但未成功归档"；死文案不再渲染 |
| P1-8 | 侧栏导航项都带与标签同义的副标题 | 删除副标题 | **已完成**：页签只保留标签 |
| P1-9 | 字段说明与标签几乎同权 | 建立三级 | **已完成**：标签 12px/600 `--ink-2`、说明 12px/400 `--ink-3`、分区标题 13px/650 |

## 5. P2 方向（视觉识别）与处理状态

1. **收敛设计令牌** —— 第三轮改为 Apple 令牌体系：`--r-card: 10px` / `--r-ctl: 6px` 两档圆角，阴影只留浮层（popover 与弹窗）。
2. **降低表面噪声** —— 第三轮用材料分层（半透明侧栏）+ 内嵌分组列表取代卡片堆叠。
3. **平台语汇** —— 第三轮采用 macOS 交通灯（左上角，悬停显字形）；同时在样式表内保留 `data-controls="win"` 覆盖块，一行属性即可切回 Windows 右侧线条控件。窗口拖动已修复（`pywebview-drag-region`）。
4. **CJK 排版基准** —— 13/12/26/20/34 五级，字体栈以 SF Pro 起头、Windows 回退 Segoe/雅黑。
5. **整体语言切换（第三轮）** —— **已完成**：Apple/macOS 语汇（分段控件、UISwitch、popover、语义色数字、0.5px 分隔线）；对比度修正 6 处（见 [ui-design.zh.md](ui-design.zh.md) §3）；契约测试仅更新开关一条断言。

## 6. 未覆盖与限制

- 渲染台用 mock 桥（`load_user_settings`、`get_run_context`、`get_classification_rules_status`、`load_classification_rules`、`get_progress`、`get_results_delta`），未接真实后端；因此"开始时间/已运行"等依赖真实运行态的数据显示为 `—`，属 mock 限制而非缺陷。
- 未做 760px/1180px 窄窗口截图（桌面应用最小窗口较大），断点行为仅做 CSS 检查。
- 未做真实读屏（NVDA/讲述人）验证，`aria-*` 结论来自 DOM 与可访问名称统计。
- 未做长文本/极端路径（超长目录、超长公司名）的溢出压测。
- 未测高对比度模式（Windows 强制对比色）下的表现。

## 7. 复现方式

```powershell
# 1) 渲染台（临时脚本，位于 gitignore 的 tmp/ 下）
.venv\Scripts\python.exe tmp\ui-audit\run_shots.py after      # 截图输出到 design/ui-review/
.venv\Scripts\python.exe tmp\ui-audit\probe_styles.py         # 关键元素计算样式
.venv\Scripts\python.exe tmp\ui-audit\audit.py                # 可访问名称 / 焦点环 / 弹层

# 2) 门禁
.venv\Scripts\python.exe -m pytest -q --deselect "tests/test_batch_validation.py::test_pinned_baseline_contract_uses_current_stable_hardware_fingerprint"
.venv\Scripts\python.exe -m ruff check .
node tools/compile-frontend.mjs --check
node tools/brand/generate.mjs --check
node tools/brand/check.mjs
```

## 8. 截图索引（`design/ui-review/`，已被 `.gitignore` 忽略）

`before-*` 为改前基线（玻璃卡片版），`after-*` 为版式重构后（账册版）。覆盖：首页空闲/完成、处理进度（滚动到底）、结果页、设置页、规则工作区、免责声明弹层、下拉浮层，深浅两套主题各一份。

新设计规范见 [ui-design.zh.md](ui-design.zh.md)；本轮改动的代码入口是 `templates/index.html`（整份样式表重写）与 `templates/index_app.js`（顶栏组件 `AppTopBar`、`AppShell`、`HomePage`、`AnalysisPage` 的结果首屏）。

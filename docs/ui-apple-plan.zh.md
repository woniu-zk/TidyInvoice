# Apple（macOS）风格改造计划

目标：把现有界面（当前为"账册"版）整体替换为 Apple/macOS 语汇，并保证功能、契约测试与无障碍不回退。
状态：**已实施（2026-11-26）**。三个待拍板项按建议执行：macOS 交通灯（保留 `data-controls="win"` 覆盖块）、主操作留在内容区、字体用系统近似。实际改动：`templates/index.html` 样式表整份重写、`templates/index_app.js`（AppSidebar / 分段控件 / 分组标题 / 弹层标题）、`tests/test_frontend_build_contract.py`（开关断言 1 处）、`docs/ui-design.zh.md` 重写。

---

## 1. 设计决策

### 1.1 窗口与外壳

| 项 | 决定 |
| --- | --- |
| 窗口 | 无边框窗口，控件改为 **macOS 交通灯**：左上角、12px 圆、间距 8px，悬停整组才显示 ×/−/+ 字形 |
| 侧栏 | **232px 半透明材料**：浅色 `rgba(242,242,245,.78)` + `blur(24px) saturate(180%)`；深色 `rgba(38,38,38,.72)`。侧栏贯通窗口高度，顶部留 44px 给交通灯 |
| 品牌 | 侧栏内 13px/600 名称（去掉字母角标 `topbar-mark`） |
| 导航 | 侧栏行：图标（16px，取自 `UI_COPY.navigation[].icon`）+ 13px 标签；选中 = 强调色 10% 底 + 强调色文字 + 6px 圆角 |
| 侧栏底部 | 主题切换 / 免责声明 / 仓库 三行 12px 次级文字，`0.5px` 上分隔线 |
| 内容区 | `#f5f5f7`（浅）/ `#1e1e1e`（深），进度、卡片全部不透明 |
| 拖动 | `pywebview-drag-region` 放在品牌行与顶部 44px 留白条；导航、按钮不参与 |
| 底部状态条 | 30px、11px 次级文字、`0.5px` 上分隔线 |
| 阴影 | **只给浮层**（下拉、弹层）：`0 12px 34px rgba(0,0,0,.16)` + `0 0 0 0.5px` 描边；内容卡片只用 `0.5px` 分隔线 |

### 1.2 控件映射（顺手把语义改对）

| 现有控件 | Apple 化之后 |
| --- | --- |
| 三个并列"任务模式"卡片 | **分段控件**（track + 滑块），段内只放标签；说明改为控件下方一行，跟随当前选中项 |
| 主操作按钮 + 次级按钮混排 | 主操作 = 实心强调色；次级 = 灰色填充；第三级 = 纯文字（filled > tinted > plain） |
| "按分类分目录"复选、页脚"自动记住配置"复选 | **UISwitch**（38×22，绿色开启态，160ms 缓动） |
| 分组标题 + 带色边卡片 | **内嵌分组列表**：12px 次级文字标题在卡片外，卡片内为字段列表 |
| 状态胶囊 | 保留胶囊，但改为语义色 8–12% 底 + 语义色文字（Apple badge 语言） |
| 设置页签 / 规则分区页签 | **分段控件**（同一套） |
| 下拉菜单 | **popover**：10px 圆角、5px 内边距、26px 行高、悬停 = 强调色反白 |
| 三个结果数字（彩底卡） | 一行三列，数字本身染语义色，列间 `0.5px` 内缩分隔线 |

### 1.3 颜色：Apple 原值需要修正（对比度）

Apple 的系统色是按 SF 字重与自身排版调过的，直接搬过来有 5 处在 12–13px 文字上不达 AA。采用值均已实测：

| 令牌 | Apple 原值 | 采用值 | 原因 |
| --- | --- | --- | --- |
| 浅色 `--label-2`（次级文字） | `rgba(60,60,67,.6)` = **3.44:1** | `rgba(60,60,67,.78)` = **5.62:1**（窗口底 5.32） | AA |
| 浅色 `--green` | `#248a3d` = **4.40:1** | `#1d7a35` = **5.40:1** | AA |
| 深色 `--red` | `#ff453a` = **4.21:1** | `#ff6961` = **5.09:1** | AA |
| 浅色主按钮底 | `#0071e3` 白字 = 4.70 | `--accent-fill: #0064c8` = **5.74:1** | AA 余量（`--accent` 仍用于图标/描边/文字） |
| 深色主按钮底 | `#0a84ff` 白字 = **3.65:1** | `--accent-fill: #0a6fd6` = **4.93:1** | AA |
| 深色强调色文字 | `#0a84ff` on 卡 = **3.94:1** | `--accent-text: #64b5ff` = **6.56:1** | AA |

其余实测：浅色主文字 16.8 / 深色 13.2；浅色绿 5.40、橙 `#b25000` 5.20、红 `#d70015` 5.38；深色绿 `#30d158` 7.10、橙 `#ff9f0a` 6.98。分段控件滑块与轨道之间用 `0 0 0 0.5px rgba(0,0,0,.06)` 描边区分（同色时不靠对比度）。

同时保留契约测试要求的别名：浅色块内必须有 `--text-main: #182234;`，两套主题都要有 `color-scheme: dark;` / `color-scheme: light;`。

### 1.4 字体与排版

- 栈：`"SF Pro Text","SF Pro Display",-apple-system,"Segoe UI Variable Text","Segoe UI","PingFang SC","Microsoft YaHei UI"`。**Windows 上 SF Pro 不存在**，实际落到 Segoe/雅黑——这是本方案唯一无法 1:1 的部分，需在文档标注。
- 标尺：大标题 26px/700（-0.022em）、分组标题 12px/500、正文 13px/400、次要 12px、数字 22/30/34px 600 + `tabular-nums`、日志 11px 等宽。
- 中文不做大写变换、不加字距；仅西文数字保留 `letter-spacing: -0.01em`。

### 1.5 动效与可达性

- 选中滑块 120ms `cubic-bezier(.4,0,.2,1)`；开关 160ms；进度条 260ms。`prefers-reduced-motion` 下全部降为 0.001ms。
- 焦点：`:focus-visible` 用 `0 0 0 3px rgba(accent,.45)` 光环（Apple 焦点环），保留现有 12 类控件的焦点覆盖。
- 自定义开关必须保留：键盘 Space 切换、`:focus-visible` 光环、`aria-*` 不变。

---

## 2. 文件级改动

### 2.1 `templates/index.html`（整份 `<style>` 替换）

分区块重写：基础复位 → 令牌（深/浅）→ 外壳（侧栏/交通灯/内容/页脚）→ 页面骨架 → 分组卡片 → 字段与开关 → 按钮/分段控件/胶囊 → 状态与提示 → 进度与日志 → 结果页 → 设置页 → **规则工作区（约 60 个 `.rule-*`/`.rules-*` 选择器，按同一语言重绘）** → 弹层/下拉 → 工具类 → 焦点环 → 响应式（1180 / 820）。

**必须逐字保留的字符串**（否则契约测试失败）：

```
.page-wrap--settings > .surface-card,
.page-wrap--home > .surface-card,
.page-wrap--settings, .page-wrap--home { min-height: 100%; height: auto; justify-content: flex-start;
.page-wrap--settings, .page-wrap--analysis, .page-wrap--home {
.page-wrap--settings .settings-section, .page-wrap--settings .rules-workspace { flex: 0 0 auto; }
.rules-workspace > * { flex: 0 0 auto; }
.rules-action-bar {   .settings-tabbar {   .settings-section {
.page-wrap--analysis { min-height: 100%; height: auto; justify-content: flex-start;
.page-wrap--analysis > .surface-card,
.rules-panel { .rules-tabbar { .rules-layout { .rules-types-layout { .rules-tools-layout { .rules-column {
.rule-category-row { .rule-category-row__name--missing .rule-target-row { .rule-target-tag {
.rule-archive-summary { .rule-type-create { .rule-type-chip { .rules-type-row { .rules-kv-list {
.rule-dictionary-row { .rule-unclassified-row { .rules-builtin { .rules-builtin-row {
.rules-builtin-row__folder { .rules-builtin-row__actions { .rule-textarea { .restore-dialog {
.restore-options { .restore-option { .classification-summary {
grid-template-columns: minmax(0, 1.18fr) minmax(0, 1fr)
.rules-layout, .rules-tools-layout, .rules-types-layout { grid-template-columns: 1fr; }        ← 媒体查询内，单行
.rules-editor-grid, .rules-test-grid, .rules-kv-list, .rule-dictionary-form, .rules-builtin-row { grid-template-columns: 1fr; }   ← 媒体查询内，单行
input:not([type="date"]), select { appearance: none
--text-main: #182234;        color-scheme: dark;        color-scheme: light;        :root[data-theme="light"]        prefers-color-scheme: light
flex: 0 0 auto   ≥ 5 处
```

**不得出现**：`.rules-builtin__summary`、`.rules-builtin-head`、`.rules-builtin-row__types`、`.rule-chip-select`、`.rule-ticket-tag`、`.rule-auto-folder`、`.engine-item`、`.engine-list`、`.terminal-body`、`.page-wrap--rules`；以及任何品牌字面量（`tools/brand/check.mjs` 会拦 runtime 文件）。

### 2.2 `templates/index_app.js`

| 改动 | 说明 |
| --- | --- |
| `AppTopBar` → `AppSidebar` | 组件语义与渲染位置已经变成侧栏，类名同步为 `.app-sidebar` / `.sidebar-*`；`AppShell` 调用点改名 |
| 导航图标回归 JSX | 用 `UI_COPY.navigation[].icon` 渲染 `<span aria-hidden="true" className="material-symbols-outlined">`，替代预览里用 `:nth-child` 注图标 CSS 的临时做法 |
| 模式说明下沉 | 分段控件内不再渲染 `mode-option__desc`；改为控件下一行渲染当前选中模式的 `description`，供读屏与视力用户（不再靠 `display:none` 隐藏信息） |
| `SectionHeader` | 不再渲染图标（Apple 分组标题是纯文字）；`icon` 属性保留但不再使用，注释标明后续清理 |
| 其余 | 文案常量、`callApi` 调用、`aria-*`、`pywebview-drag-region`（品牌行 + 顶部留白条）全部不动 |

### 2.3 文档

- `docs/ui-design.zh.md`：整篇改写为 Apple 规范（令牌表含上表修正值、控件映射、窗口语汇、字体限制、验证方式）。
- `docs/ui-review.zh.md`：§4/§5 增补"A 轮：账册 → E 轮：Apple"的演进记录与截图索引。

### 2.4 测试（唯一一处）

`tests/test_frontend_build_contract.py::test_toggle_checkboxes_keep_a_visible_native_box` 断言 `.toggle-row input[type="checkbox"]` 规则内必须有 `appearance: auto`。Apple 版是**有意**自绘开关（`appearance: none` + 轨道 + 圆点），所以要按"保持原意（控件必须可见可点）"重写：

```python
def test_toggle_rows_draw_a_visible_switch():
    """UISwitch 形态：显式取消原生外观，但必须画出轨道与圆点，且可点击。"""
    html = " ".join(_read(HTML_PATH).split())
    assert '.toggle-row input[type="checkbox"]' in html
    start = html.index('.toggle-row input[type="checkbox"]')
    rule = html[start:start + 620]
    assert "appearance: none" in rule
    assert "width: 38px" in rule and "height: 22px" in rule
    assert 'input[type="checkbox"]::before' in html
    assert 'input[type="checkbox"]:checked' in html
    assert 'input:not([type="date"]), select { appearance: none' in html
```

其余契约测试**不改**（已逐条核对：文案、导航字面量、`window-traffic-button--maximize`、CSP、脚本顺序、品牌、规则页选择器与媒体查询字符串均保留）。

---

## 3. 实施顺序

| 阶段 | 内容 | 完成标志 |
| --- | --- | --- |
| **P0 骨架** | 令牌（含对比度修正）、侧栏材料、交通灯、内容区、页脚、排版标尺 | `compile-frontend` 通过；首页深浅两色截图与预览一致 |
| **P1 内容语言** | 分组卡片、字段、UISwitch、按钮、分段控件、状态胶囊、进度、结果页、设置页签 | 首页/结果/设置 三面截图通过；`test_frontend_build_contract` 全绿（含新开关断言） |
| **P2 密集面** | 规则工作区全部 `.rule-*`、下拉 popover、免责声明弹层、工具类、断点 | 规则列表/词典测试两页 + 两个浮层截图通过 |
| **P3 收尾** | 焦点环、reduced-motion、滚动条、文档、a11y 与对比度复核 | §5 全表通过；全量 `pytest` 绿 |

每阶段结束都跑一次：`node tools/compile-frontend.mjs` + 相关契约测试 + 截图台。

---

## 4. 验证清单

**门禁**

```powershell
node tools/compile-frontend.mjs
.venv\Scripts\python.exe -m pytest -q --deselect "tests/test_batch_validation.py::test_pinned_baseline_contract_uses_current_stable_hardware_fingerprint"
.venv\Scripts\python.exe -m ruff check .
node tools/compile-frontend.mjs --check
node tools/brand/generate.mjs --check
node tools/brand/check.mjs
```

**截图矩阵（16 张，`tmp/ui-audit/run_shots.py` 已具备能力）**
首页空闲 / 首页完成 / 进度滚动 / 结果页 / 设置·邮件 / 设置·规则列表 / 设置·词典与测试 / 免责声明弹层，各深 + 浅。

**自动化检查**
- 可访问名称：可见按钮 0 个缺名；图标全部 `aria-hidden`；输入框全部有 `label[for]` 或 `aria-label`。
- 弹层：`role=dialog` + `aria-modal` + 打开聚焦 / 关闭归还焦点。
- 0 重复 id、0 console error、0 page error。
- DOM 用到的 class 与样式表定义做差集，必须为空（`pywebview-drag-region` 除外）。
- 对比度：按 §1.3 采用值重算，正文/次级/主按钮/语义色全部 ≥ 4.5。

---

## 5. 风险与回滚

| 风险 | 处理 |
| --- | --- |
| Windows 无 SF Pro / SF Symbols，成品与预览有字形差异 | 文档标注；用字重与字距补偿；不引入需授权字体 |
| 交通灯在 Windows 上是移植语汇 | 预留 `.app-shell[data-controls="win"]` 覆盖块（约 15 行），一行属性即可切回 Windows 风格控件 |
| `backdrop-filter` 在低配机有开销 | 只在侧栏使用，静态，不加动画 |
| 自定义开关影响可访问性 | 保留原生 `input`（Space 可切换）、焦点光环；测试断言覆盖 |
| 样式表整份重写可能漏类 | 差集脚本把关；分阶段截图 |
| 账册版被整体替换 | 现样式在 git 历史里，可 `git checkout` 回滚 |

---

## 6. 待你拍板的三件事

1. **窗口控件**：macOS 交通灯（默认，最像 Apple）／ Windows 原生控件（更合平台，其余仍 Apple）。→ 建议：交通灯 + 预留一行切换。
2. **主操作位置**：留在内容区（默认，改动小）／ 移到侧栏顶部常驻（更 Apple，但要改 `AppShell` 结构）。→ 建议：留在内容区。
3. **字体**：接受 Segoe/雅黑 近似（默认）／ 自备 SF Pro 授权并放到 `templates/static/`（可 1:1，但涉及授权与体积）。→ 建议：近似。

确认（或改）这三点后，我按 P0→P3 开始实施。

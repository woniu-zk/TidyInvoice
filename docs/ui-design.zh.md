# 界面设计规范（Apple / macOS）

本文件是 `templates/index.html` 与 `templates/index_app.js` 界面层的设计契约。新增或修改界面时先读这里再动样式；与本文冲突的写法先改本文。

> 演进：玻璃卡片（初版）→ 账册 Ledger（第二轮，已废弃）→ **Apple / macOS（当前）**。

## 1. 定位与原则

这是一支 Windows 上的桌面工具，界面按 **macOS 应用**的组织方式设计：侧栏材料 + 系统字号 + 内嵌分组列表 + 系统控件（分段控件、开关、popover）。四条硬规则：

1. **材料分层，不用投影堆叠。** 侧栏半透明材料，内容不透明；阴影只给浮层（下拉、弹窗）。
2. **一个强调色。** 只有系统强调色（浅 `#0071e3` / 深 `#0a84ff`）与四种语义色；其余是标签、填充与分隔线。
3. **控件用系统的，不发明。** 模式选择 = 分段控件，开关 = UISwitch，下拉 = popover，状态 = 胶囊徽标。
4. **中文优先排版。** 13px 正文、12px 次要、26px 大标题；不做大写变换、不加字距，数字全 tabular。

## 2. 版式模型

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ ● ● ●  整票        │  首页                                        （内容区）  │
│  ▸ 首页            │  一句话说明                                               │
│    结果            │  ┌ 分组标题 ────────────────────────────────────────┐    │
│    设置            │  │ (分段控件：邮箱提取 / 本地整理 / 邮箱提取并整理)  │    │
│                    │  │ 当前模式的说明                                  │    │
│                    │  │ [ 开始处理 ]                                    │    │
│                    │  └─────────────────────────────────────────────────┘    │
│                    │  处理进度                              等待任务开始        │
│                    │  ┌─────────────────────────────────────────────────┐    │
│ 深色模式            │  │ 尚未开始处理…                                    │    │
│ 免责声明            │  └─────────────────────────────────────────────────┘    │
│ GitHub 仓库        │  邮箱与公司                    输出目录设置                │
│                    │  ┌ 卡片 ─────────────┐   ┌ 卡片 ─────────────┐          │
├────────────────────┴───────────────────────────────────────────────────────┤
│ 底部说明                                                       次操作        │
└───────────────────────────────────────────────────────────────────────────────┘
```

- **侧栏** 232px：半透明材料（`backdrop-filter: saturate(180%) blur(24px)`），顶部 44px 留给交通灯，品牌名 13px/600，导航行 30px（图标 16px + 标签），选中 = 强调色 10% 底 + 强调色文字 + 6px 圆角；底部三行工具动作 12px。
- **内容区**：`#f5f5f7`（浅）/ `#1e1e1e`（深），`page-wrap` 最大 1080px。
- **页头**：26px/700 标题（-0.022em）+ 13px 说明 + 右侧状态胶囊。
- **分组**：分组标题 12px 次级色在**卡片外**（左内缩 4px），卡片 10px 圆角、`0.5px` 分隔线、12–14px 内边距。
- **页脚**：30px、11px 次级文字、`0.5px` 上分隔线。

## 3. 令牌

深色为 `:root`，浅色为 `:root[data-theme="light"]`（并有一份 `prefers-color-scheme: light` 兜底）。组件层只引用令牌。

| 令牌 | 深色 | 浅色 | 用途 |
| --- | --- | --- | --- |
| `--window` | `#1e1e1e` | `#f5f5f7` | 内容区底色 |
| `--sidebar` | `rgba(44,44,46,.72)` | `rgba(242,242,245,.78)` | 侧栏材料 |
| `--card` | `#2a2a2a` | `#ffffff` | 分组卡片、弹层 |
| `--card-2` | `#323232` | `#fbfbfd` | 卡片内控件底 |
| `--fill` / `--fill-2` | `rgba(118,118,128,.24)` / `.16` | `.12` / `.08` | 填充（胶囊、禁用、次要区） |
| `--separator` | `rgba(255,255,255,.11)` | `rgba(60,60,67,.13)` | 0.5px 线 |
| `--label` / `--label-2` / `--label-3` | `#f5f5f7` / `rgba(235,235,245,.62)` / `.34` | `#1d1d1f` / `rgba(60,60,67,.78)` / `.34` | 主 / 次 / 仅图标 |
| `--accent` / `--accent-fill` / `--accent-text` | `#0a84ff` / `#0a6fd6` / `#64b5ff` | `#0071e3` / `#0064c8` / `#0064c8` | 图标与描边 / 实心按钮底 / 强调色文字 |
| `--green` `--orange` `--red` `--blue` | `#30d158` `#ff9f0a` `#ff6961` `#64b5ff` | `#1d7a35` `#b25000` `#d70015` `#0064c8` | 语义色 |
| `--seg-track` / `--seg-thumb` | `rgba(118,118,128,.2)` / `#636366` | `.12` / `#ffffff` | 分段控件 |
| `--shadow-pop` / `--shadow-sheet` | 深色投影 | 浅色投影 | 仅浮层 |
| `--r-card` / `--r-ctl` | `10px` / `6px` | 同 | 卡片 / 控件 |

**对比度修正（不要退回 Apple 原值）**：Apple 的 `secondaryLabel`（60%）、`systemGreen`、深色 `systemRed`、深色实心按钮（白字 3.65:1）在 12–13px 文字上不达 AA，因此：

| 令牌 | Apple 原值 | 采用值 | 实测 |
| --- | --- | --- | --- |
| 浅色 `--label-2` | `rgba(60,60,67,.6)` = 3.44 | `.78` | **5.62**（窗底 5.32） |
| 浅色 `--green` | `#248a3d` = 4.40 | `#1d7a35` | **5.40** |
| 深色 `--red` | `#ff453a` = 4.21 | `#ff6961` | **5.09** |
| 浅色实心按钮 | `#0071e3` 白字 4.70 | `--accent-fill: #0064c8` | **5.74** |
| 深色实心按钮 | `#0a84ff` 白字 3.65 | `--accent-fill: #0a6fd6` | **4.93** |
| 深色强调文字 | `#0a84ff` = 3.94 | `--accent-text: #64b5ff` | **6.56** |

`--label-3` **只用于图标与分隔符**，不得用于文本；占位符用 `--label-2`。

## 4. 排版

| 角色 | 字号/字重 |
| --- | --- |
| 页面标题 | 26px / 700 / -0.022em |
| 分组标题 | 12px / 500 / `--label-2` |
| 正文与字段 | 13px / 400 |
| 次要说明 | 12px / 400 / `--label-2` |
| 关键数字 | 22 / 30 / 34px / 600 / tabular |
| 弹层标题 | 20px / 600 |
| 机器串 | 11–12px 等宽 |

字体栈以 `SF Pro Text / SF Pro Display` 开头，Windows 上实际落到 `Segoe UI Variable / 微软雅黑`——这是唯一无法 1:1 的部分，**不引入需授权字体**。

## 5. 控件映射

| 场景 | 实现 |
| --- | --- |
| 任务模式 | `.mode-picker` 分段控件（3 段，只放标签）；当前模式说明由 `#task-mode-help` 一行承载，`aria-describedby` 关联 |
| 主操作 | `.btn--primary` 实心强调色；次级 `.btn--secondary` 灰色填充；第三级 `.btn--ghost` 纯文字；破坏性 `.btn--danger` |
| 开关 | `.toggle-row input[type="checkbox"]` = UISwitch（38×22，轨道 + `::before` 圆点，开启态绿色，160ms 缓动，Space 可切换） |
| 下拉 | `.field-dropdown-menu` = popover（10px 圆角、5px 内边距、26px 行、悬停强调色反白） |
| 状态 | `.status-pill` / `.group-chip` / `.inline-status` = 语义色 8–12% 底 + 语义色文字胶囊 |
| 页签 | 设置页与规则分区 = 分段控件（滑块 + 阴影） |
| 结果数字 | 三列，数字染语义色，列间 `0.5px` 内缩分隔线 |
| 提示条 | `.manual-banner` = 灰色填充卡（次级于主卡） |
| 弹窗 | `.modal-card` = 14px 圆角卡片 + 超大投影 + 背景 32% 遮罩与 2px 模糊 |

## 6. 窗口语汇

- 无边框窗口，**左上角交通灯**（12px 圆、间距 8px、悬停整组显示 ×/−/+）。
- 拖动区：`.sidebar-brand` 与 `.sidebar-spacer` 带 `pywebview-drag-region`（pywebview 默认选择器）。
- **可一键切回 Windows 控件**：在 `<html>` 上加 `data-controls="win"`，交通灯变为右上角 46×46 的线条按钮（`⌗` 覆盖块在样式表内已就绪）。

## 7. 可访问性

- 焦点：`:focus-visible` 用 `0 0 0 3px var(--focus)` 光环（按钮、页签、分段、图标按钮、开关、单选）。
- 自定义开关保留原生 `input`（键盘可用）、焦点光环；契约测试 `test_toggle_rows_draw_a_visible_switch` 守住"可见、可点"。
- 装饰图标全部 `aria-hidden="true"`；输入框均有 `label[for]` 或 `aria-label`；弹层 `role="dialog"` + `aria-modal` + 焦点进入/归还；进度条 `role="progressbar"`；当前页 `aria-current="page"`。
- `prefers-reduced-motion` 下所有过渡降到 0.001ms。

## 8. 修改约束（契约测试固定）

以下字符串必须逐字保留，否则 `tests/test_frontend_build_contract.py` 失败：

```
.page-wrap--settings > .surface-card,     .page-wrap--home > .surface-card,
.page-wrap--settings, .page-wrap--home { min-height: 100%; height: auto; justify-content: flex-start;
.page-wrap--settings, .page-wrap--analysis, .page-wrap--home {
.page-wrap--settings .settings-section, .page-wrap--settings .rules-workspace { flex: 0 0 auto; }
.rules-workspace > * { flex: 0 0 auto; }
.page-wrap--analysis { min-height: 100%; height: auto; justify-content: flex-start;
.page-wrap--analysis > .surface-card,
grid-template-columns: minmax(0, 1.18fr) minmax(0, 1fr)
.rules-layout, .rules-tools-layout, .rules-types-layout { grid-template-columns: 1fr; }
.rules-editor-grid, .rules-test-grid, .rules-kv-list, .rule-dictionary-form, .rules-builtin-row { grid-template-columns: 1fr; }
input:not([type="date"]), select { appearance: none
--text-main: #182234;   color-scheme: dark;   color-scheme: light;   prefers-color-scheme: light
flex: 0 0 auto（≥5 处）
```

以及规则工作区的一批选择器（`.rules-panel`、`.rules-tabbar`、`.rules-layout`、`.rule-category-row`、`.rule-target-tag`、`.rules-kv-list`、`.rule-textarea`、`.restore-dialog`、`.classification-summary` 等）。`templates/index.html` 与产物中**不得出现品牌字面量**。

## 9. 验证

```powershell
node tools/compile-frontend.mjs
.venv\Scripts\python.exe -m pytest -q --deselect "tests/test_batch_validation.py::test_pinned_baseline_contract_uses_current_stable_hardware_fingerprint"
.venv\Scripts\python.exe -m ruff check .
node tools/compile-frontend.mjs --check
node tools/brand/generate.mjs --check
node tools/brand/check.mjs
```

视觉与可达性：`tmp/ui-audit/run_shots.py` 出首页/进度/结果/设置/规则/弹层/下拉 × 深浅；`tmp/ui-audit/audit.py` 查可访问名称、焦点、弹层、重复 id、控制台报错。截图落在 `design/ui-review/`（已被 `.gitignore` 忽略）。

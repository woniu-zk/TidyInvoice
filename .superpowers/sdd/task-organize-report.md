# Task: 功能②（P0）整理 organize — 提取与整理功能分离

> 依据：`创意项目/发票管理/产品方案-差异化与优先需求.md` v0.3（功能② P0 + 解耦三原则）
> 基线：`3be73be`（本报告提交前 HEAD）
> 目标范围由用户确认：在 **Invoice-Downloader** 仓库落地「本地文件夹整理」并把「邮箱提取」与「整理」拆成两条互不依赖的链路。

## Status

PASS pending independent re-run of the final clean tree. 三条用户链路均已实现并有可复现证据：

1. **邮箱提取并整理**（原有 mail 链路，行为不变）
2. **仅提取到 inbox**（新 fetch-only：邮箱 → `inbox/` + `manifest.jsonl`，不解析、不归档）
3. **本地文件夹整理**（新 local：任意本地目录 → 离线识别 → 分类/重命名 → 归档，默认仅预览）

## 架构与解耦

新增模块（组织器一侧不 import 任何 IMAP/邮箱模块；提取一侧不 import 解析器）：

| 文件 | 职责 |
|---|---|
| `fetch_handoff.py` | 公开交接契约：`inbox/` 布局、`manifest.jsonl` 读写、`fetch_todo.jsonl`、`.fetch_state.json`。无 IMAP、无解析。 |
| `organize_source.py` | 扫描任意本地目录 → 与邮件附件同形的 attachment rows（sha256 去重、输出目录排除、跳过工具状态目录、manifest 来源信息回填）。 |
| `local_organize.py` | 本地整理编排（scan → extract → archive → Excel 报表），dry-run 预览/apply 两种模式；CLI 与桌面端共用。 |
| `fetch_only.py` | 邮箱附件 → inbox + manifest；只在提取阶段使用 IMAP，不做解析。 |
| `organize_cli.py` | 独立命令行入口：`organize`（默认预览）与 `fetch`（只提取）。 |
| `app_api.py` | 新增 `start_local_organize()` / `start_fetch_only()`、本地整理 RunDependencies、dry-run pipeline 装配、`get_results/get_progress` 模式字段。 |
| `app_archive_adapter.py` | 新增 preview 归档操作：只计算计划路径与结果行，不复制文件、不写台账、不做配对/CWT 移动。 |
| `invoice_extractor.py` | 抽出纯决策函数 `_plan_archive_target()`，新增 `preview_archive_target()`；`route_and_rename_file()` 行为保持不变。 |
| `run_coordinator.py` | `RunRequest` 增加 `source_mode/fetch_only/input_dir/dry_run`；阶段文案与终态文案按模式区分。 |
| `email_fetcher.py` | 附件行补充 `mailbox/message_id/received_at`，供 manifest 记录来源。 |
| `templates/index_app.js` | 新增「任务类型」三段选择、本地文件夹选择、仅预览复选框、三种结果页横幅与处理页标签；重编译 `index_app.built.js`。 |
| `build/windows/resources.manifest.json` | 打包 hiddenImports/requiredPaths 增加新模块。 |

**解耦硬约束（测试强制，`tests/test_organize_local_mode.py`）**

- `organize_source.py / local_organize.py / fetch_handoff.py / organize_cli.py` 源码级 AST 检查：不得 import `email_fetcher / email_channel / mailbox_scanner / imaplib / provider_*`。
- `email_fetcher.py / fetch_only.py` 顶层 import：不得 import `invoice_extractor / local_recognition / candidate_pipeline / extraction_pipeline / app_api / app_archive_adapter`。
- 两者只通过 `manifest.jsonl` 交接；本地整理在无任何邮箱配置、断网时可完整运行（既有离线识别引擎 + 本模块无网络 import）。

**预览安全性（dry-run）**

- 不移动/复制/重命名文件，不写 `committed_state.json` 台账，不写 `run_state.json`「running」标记，不做配对重命名与 CWT 取消匹配。
- 预览结果通过 `processed_invoices/error_invoices` 中带 `preview: true` 的行呈现，应用后可再次执行真实整理。
- 已由 `tests/test_organize_local_mode.py` 断言「预览后输出目录 0 个文件」「二次预览结果稳定」。

## 用户链路

- 桌面端设置页「任务类型」：邮箱提取并整理 / 仅提取到 inbox / 本地文件夹整理；三种模式持久化（`task_mode/local_input_dir/local_dry_run`）。
- 「本地文件夹整理」默认「仅预览，不移动文件」，按钮「开始预览」；取消勾选后「开始整理」。
- 结果页横幅：`仅提取完成` / `本地预览完成` / `本地整理完成`（文案契约见 `tmp/organize-frontend-contract.md`，随任务清理）。
- CLI：`python organize_cli.py organize <目录> --output <库> [--apply] [--json]`，`python organize_cli.py fetch --email ... --auth-code env:VAR --output <库>`。

## Verification

（以下均为实际运行结果）

```text
ruff check .                         -> All checks passed!
python -m pytest -q                  -> 966 passed, 115 subtests, 1 failed (env_bound 机器指纹基线，改动前同样失败)
node tools/compile-frontend.mjs --check -> OK sha256=5f2b0aa0f270d6c66d072d465600aa17d074ace85861e78aacd39311fbbea10a
pytest tests/test_frontend_build_contract.py -q -> 9 passed
pytest tests/test_organize_local_mode.py tests/test_organize_local_source.py -q -> 22 passed
Playwright mocked frontend smoke（4 场景：fetch / local-preview / local-apply / mail 回归）-> ALL SCENARIOS PASSED
真实 pywebview/WebView2 + Playwright/CDP 端到端（GUI 设置→预览→结果→设置→整理）-> PASS（见下方证据）
```

CLI 手工端到端（`tmp/e2e-organize`，4 个候选 + 1 个非发票文件）：

```text
预览:  扫描 4 · 忽略非发票 1 · 归档 2 · 重复跳过 2 -> 输出目录 0 个文件
apply: 输出 打车/…pdf、非目标公司发票/…xml、结果明细_*.xlsx
重跑:  归档 0 · 重复跳过 4（台账幂等，无重复归档）
```

真实 GUI 端到端（隔离 APPDATA、独立单实例 mutex、WebView2 CDP 9333，验证后自动关闭）：

```text
settings: task_mode=local / local_input_dir 恢复 / 开始预览可用
preview : 扫描状态文案出现 → 结果页「本地预览完成」；get_results(): task_mode=local, dry_run=true,
          successInvoices 2 条且 preview=true；输出目录 0 个文件
apply   : 取消预览 → 开始整理 → 结果页「本地整理完成」；输出目录出现 打车/*.pdf、
          其他/*.xml、结果明细_*.xlsx；get_results() dry_run=false、organize_summary.archived_count=2
console : 无 page/console error
截图    : tmp/gui-e2e/01-settings-local.png / 02-analysis-preview.png / 03-analysis-apply.png
report  : tmp/gui-e2e/report.json -> {"ok": true, ...}
```

## Post-verification UI fix（用户反馈「重启后还是旧 UI」）

根因不是缓存或构建产物：新「任务类型」卡片插入到 `page-wrap--settings` 这个 **flex 列** 后，作为可收缩 flex item 被压缩到 **1px 高**。DOM 与文案查询全部正常，所以自动化断言与文本冒烟都通过，但视觉上整张卡片不可见，等于旧 UI。用真实 WebView2 + CDP 测得该 section 高度 `h=1`、下一张卡片上移。

修复（`templates/index.html`）：

```css
.page-wrap--settings { ... flex: 0 0 auto; }
.page-wrap--settings > .surface-card { flex: 0 0 auto; min-height: auto; }
```

新增回归测试 `test_settings_top_level_cards_never_flex_shrink_into_slivers`（同一文件的构建契约测试内，断言两条 CSS 规则存在）。

修复后真实 WebView2 CDP 实测：任务类型 section `h=1 -> 136`；`任务类型` 卡片与三种模式按钮可见；重新执行真实 GUI e2e（预览→结果→取消预览→整理）全部通过，无 console error。

## Concerns / Limitations

- 真实邮箱 IMAP 的 fetch-only 链路只做了依赖注入级单测（假 fetcher）+ 真实 EmailFetcher 既有测试，没有用真实账号跑（与仓库既有测试策略一致；mail 全链路行为未改动）。
- 本地整理的「历史去重」依赖输出目录绑定的已提交台账；预览模式只读台账、不做台账自愈（自愈会写文件）。
- 桌面端受控 QA run-context 未新增 `locked_input_dir` 字段；本地模式在受控复跑时输出目录仍按既有逻辑锁定，输入目录来自用户选择。
- `manifest.jsonl` 的邮箱来源信息写入依赖真实 EmailFetcher 附件行（已补充字段）；手工放入的 manifest 同样被接受（格式容忍坏行，坏行跳过并提示）。
- 既有 `test_batch_validation` 机器指纹用例在本机失败（env_bound；改动前的基线同样失败），与本功能无关。

## Files

新增：`fetch_handoff.py` `organize_source.py` `local_organize.py` `fetch_only.py` `organize_cli.py` `tests/test_organize_local_mode.py` `tests/test_organize_local_source.py`
修改：`app_api.py` `app_archive_adapter.py` `invoice_extractor.py` `run_coordinator.py` `email_fetcher.py` `templates/index.html` `templates/index_app.js` `templates/index_app.built.js` `tests/test_frontend_build_contract.py` `tests/test_run_coordinator.py` `build/windows/resources.manifest.json` `README.md` `README.en.md`

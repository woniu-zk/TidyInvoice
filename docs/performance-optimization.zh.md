# 鲁棒性 × 速度平衡优化记录

> 本次改动对应的设计口径：**可逆操作求快，不可逆操作求稳**；每个文件的内容摘要、PDF 文本、页面渲染在一次运行内各只产出一次；无界等待统一变为有界降级。

## 1. 提交清单

| 提交 | 内容 |
|---|---|
| `4532b65` | gac：项目总览文档与品牌图（本机快捷方式未提交） |
| `f55eb48` | 运行终态兜底与收尾异常隔离 |
| `965d569` | 附件摘要一次计算与探测缓存 |
| `ffb7d4c` | 识别资源上限与有界 OCR |
| `2aa5513` | IMAP 增量扫描与可恢复写入 |
| `4b02105` | 性能基准与前端渲染兜底 |

## 2. 改动明细

### 2.1 运行终态（`run_coordinator.py` / `run_lifecycle.py` / `report_service.py`）

- 编排层改捕 `BaseException`；收尾回调构造失败也会先把运行标记为失败，再继续 `finalize`。
- `RunHandle.finalize` 用 `try/finally` 保证终态判定、`_release` 与 `_finalized` 事件必达；单个收尾回调抛 `BaseException` 只记失败，不再泄漏运行槽位。
- `ReportService` 缺证据写入器时改抛带 `reason_code` 的 `FinalizerSetupError`。
- 回归：回调构造抛错、阶段 `BaseException`、收尾回调 `BaseException` 三类场景均可再次启动。

### 2.2 一次原则（`email_fetcher.py` / `fetch_only.py` / `candidate_pipeline.py` / `invoice_extractor.py`）

- 附件落盘时计算一次 SHA256，写入结果行、输入清单与候选 metadata；候选链路与 inbox 写入复用该摘要，缺失才回退流式计算。
- 修复 fetch-only 去重计数：`digest` 不再恒为空，`duplicate_count/saved_count` 与 manifest 摘要一致。
- `InvoiceExtractor` 增加实例级 PDF 文本缓存（路径 + mtime + size + 页数），7 个版面探测共享一次 `fitz.open`；文件变化后自动失效。
- 收尾状态 sink 不再对同一快照做第二次深拷贝。
- `UserSettingsStore.load` 按 mtime/size 命中内存缓存，避免轮询时反复 DPAPI/Keychain 解密；保存与清除使缓存失效；`save_user_settings` 的读-改-写加锁。

### 2.3 有界慢路径（`local_recognition.py` / `extraction_pipeline.py`）

- OFD：成员数 ≤512、单成员 ≤32 MB、总解压 ≤128 MB。
- 图片：像素 ≤40 MP；长边 >4000 px 时仅 OCR 输入缩放到 3000 px，归档保留原图。
- XML：≤20 MB，拒绝 `DOCTYPE`。
- OCR：单文件 deadline 15 s；每次推理在独立线程等待，超时记 `LOCAL_RECOGNITION_TIMEOUT` 并放弃；单轮最多 2 个放弃任务，超限记 `LOCAL_OCR_BUDGET_EXHAUSTED` 直接转人工复核。
- 二维码仅在缺票号时解码；图片已有票号时跳过，避免无条件 cv2 检测。
- 提取批次开始时重置 OCR 预算。

### 2.4 可恢复路径（`mailbox_scanner.py` / `fetch_handoff.py` / `archive_pairing_service.py`）

- IMAP 改为服务端 `UID SEARCH SINCE <since-3d>`（3 天重叠吸收时区/头日期偏差），本地精确日期过滤仍然保留；SEARCH 增加重试与退避；保留 `full_scan=True` 全量重扫逃生口。
- manifest / todo 追加后 `flush + fsync`；fetch state 改为唯一临时名 + `fsync` + `os.replace`，异常清理临时文件。
- 配对移动前校验两个源文件都存在；第二个文件移动失败时回滚已移动文件与 trace 目标，不再留下半配对。

### 2.5 度量与前端（`tools/bench_pipeline.py` / `templates/index_app.js`）

- 新增离线基准工具，覆盖探测、文本识别、假 OCR 路径、1000 次状态更新、摘要吞吐与状态峰值内存；支持 `--assert-budget` 与 JSON 输出。
- 新增每周性能工作流（非 PR 门禁）。
- 前端增加 ErrorBoundary 与全局 `error` / `unhandledrejection` 兜底，渲染异常时给出可重新加载的失败页，避免无边框窗口白屏。

## 3. 实测数据（本机 Windows / Python 3.12 / `--count 20`）

| 指标 | 结果 |
|---|---|
| 版面探测（每个文件新建 extractor） | p50 2.1 ms，p95 4.0 ms |
| 文本层 PDF 识别 | p50 1.4 ms，p95 2.1 ms |
| 扫描件识别（假 OCR，含 200 DPI 渲染） | p50 50.8 ms，p95 54.6 ms |
| 状态存储 1000 次追加（含 sink） | 641 ms |
| 摘要吞吐 | 约 1.2 GB/s |
| 状态 sink 峰值分配（tracemalloc） | 0.49 MB |

> 基准使用确定性假 OCR，不测 ONNX 推理本身；数值只用于同机回归，不跨机器比较。

## 4. 验证

- `pytest -q --deselect ...env_bound...`：**1407 passed, 2 skipped, 1 deselected, 120 subtests passed**，耗时约 132 s。
- `ruff check .`：通过。
- `node tools/compile-frontend.mjs --check`：产物与源码一致。
- `node tools/brand/generate.mjs --check`、`node tools/brand/check.mjs`：通过。
- 工作区仅保留未跟踪的本机快捷方式 `启动应用.lnk`（含绝对路径，未提交）。

## 5. 权衡与未完成项

- OCR 超时为软超时：进程内无法中断 ONNX 推理，超时线程会自然结束；用「单轮最多 2 个放弃任务」限制累积。
- 未做 10 分钟 OCR 总墙钟预算：会误伤长批次扫描件；改用放弃任务上限，兼顾可预期性与完成率。
- 证据链仍对输出树全量哈希：分级校验涉及台账格式与证据契约，留待单独批次。
- `fetch_state.json` 尚未在读信前用于跳过 UID；需要改 fetcher 入参契约。
- 每 50 封的检查点未实现；IMAP 已改为服务端时间过滤，重跑成本显著降低。
- 状态 sink 的整份快照深拷贝仍为 O(n)；本次只去掉第二份拷贝。
- `get_results` 仍回全量数组；建议后续加 `since` 游标。
- `app_api` 巨类未拆分。

## 6. 回滚

每个批次独立提交，可单独 `git revert`；状态文件保持向后兼容，无 schema 变更。

## 7. 第二批（E1–E6）

### 7.1 提交清单

| 提交 | 内容 |
|---|---|
| `ed4ba0a` | 清理 380 行不可达旧实现、2 个死导出、2 个恒 success 重试占位 |
| `376a929` | fetch-only 增量抓取：`fetch_state` v2、UIDVALIDITY 校验、UID 跳过、批级检查点 |
| `cb8227d` | `get_results_delta` 增量游标、前端游标追加、legacy→store 同步短路 |
| `aba48d7` | 证据 inventory 按 size+mtime 复用 capture 摘要，变更文件自动重算 |
| `1236145` | 导出逻辑移出 `app_api` → `app_services/exports.py`，插件引擎清单同步 |
| `cf4fa8d` | 设置/规则桥接移出 → `app_services/settings_rules.py` |
| `6d57302` | 诊断/事件发射移出 → `app_services/diagnostics.py` |
| `daca753` | 运行准入/依赖装配移出 → `app_services/admission.py` |
| `1dbe960` | 可选 OCR 进程运行时（默认 thread，`TIDYINVOICE_OCR_RUNTIME=process` 开启） |

### 7.2 结构与行为变化

- `app_api.py` 从约 6519 行降到 3336 行；`InvoiceAppAPI` 仍作为 js_api 门面，公开/私有方法名不变。
- 新增 `app_services/` 包（admission / diagnostics / errors / exports / settings_rules），插件 `prepare-engine.mjs` 已加入对应 vendored 源文件。
- `fetch_state.json` 升级为 v2：`uidvalidity + last_uid`；v1 状态安全降级为“不跳过”。
- 结果页轮询改为 `get_results_delta`；`run_id` 变化或游标越界时自动重置。
- 证据 inventory 复用只在 capture 后 `size+mtime` 未变时生效；validator 仍全量复核。
- OCR 默认仍是线程软超时；进程模式超时会 terminate 子进程并在下次调用重启。

### 7.3 验证

- 全量：**1425 passed, 2 skipped, 1 deselected, 120 subtests passed**（约 124 s）。
- `ruff check .`、前端 `--check`、品牌门禁：通过。
- 插件：`npm test`（24 passed）、`npm run test:package`（layout/privacy ok）。
- 基准（同机 `--count 20`）：探测 p95 2.6 ms、文本识别 p95 2.6 ms、假 OCR p95 54.6 ms、状态 1000 次 669 ms、摘要约 1.25 GB/s，全部在预算内。

### 7.4 第二轮结束时的遗留（已在第 8 节更新）

- 状态 store 在每次变更时仍整份深拷贝（O(n)），E3 只短路了轮询回灌。
- 主邮件模式尚未使用 UID 检查点（E2 只覆盖 fetch-only）。
- 证据 schema 未升级；复用统计未写入证据契约。
- OCR 进程模式未在 Windows 冻结包与插件 headless 环境做真实 ONNX 压测，默认保持关闭。
- `app_api` 仍含窗口/路径桥接与结果聚合，未拆到更细的 facade 服务。

## 8. 第三轮（S1–S4）：收尾决策与实测

| 提交 | 内容 |
|---|---|
| `16a73b8` | 状态快照改为浅视图 + 写时复制，热路径不再整份深拷贝 |
| `ea8d585` | 新增真实 OCR 压测；进程模式超时改为强杀并立即重启 |
| `3963625` | 插件引擎 `--check` 与 CI 触发范围 |
| 本节文档 | 主邮件 UID、schema、vendored engine 的结论 |

### 8.1 状态深拷贝：替代方案与结论

可选方案包括：不可变记录 + 结构共享、copy-on-write + 浅快照、delta/事件 sink、删除 legacy 镜像改为单一数据源、只在序列化边界复制。本轮采用 **copy-on-write + 浅视图 sink**：

- `RunStateStore._notify_locked()` 在只有 state_sink 时返回 `dict(self._state)` 浅视图；有 event sink 时仍深拷贝。
- 追加日志/发票/错误改为发布新列表，已发出的快照不会被后续写入修改。
- `app_api._apply_run_state_snapshot()` 直接采纳列表引用，不再 `list()/dict()` 复制。
- `snapshot()` 仍深拷贝，外部快照隔离语义不变。

**是否全面**：热路径已全面（每张发票的状态更新不再 O(n) 复制）；`snapshot()`、`get_results()`、`slice()` 仍按需复制，这是有意的冷边界隔离，不是遗漏。实测 1000 次 `add_processed` 从约 **669 ms** 降到 **约 3.5 ms**。

### 8.2 主邮件 UID 检查点：有什么用、为什么暂不做

- 用处：主模式默认按近 30 天窗口重扫，文档级摘要只能防止重复归档，不能避免重复下载与 OCR；检查点可让第二次运行只拉新 UID。1000 封 × 1 MB 约 1 GB 网络，扫描件 OCR 更贵。
- 暂不做：只有“一封邮件的全部文档都已归档/重复/无附件”才能推进；人工复核、失败、URL 未恢复必须阻塞；规则变更、输出目录变更、UIDVALIDITY 变更都要失效。任一条件处理错就会静默漏票，风险高于收益。
- 若后续实现，必须同时具备：opt-in 开关、连续成功前缀、规则指纹、UIDVALIDITY 校验、全量重扫入口、失败/复核邮件不推进。

### 8.3 schema：作用与必要性

- `run_evidence.schema_version = 1` 是证据文件的格式契约，validator 只接受 1；stat 复用不改变输出字段与 `evidence_digest` 语义，因此**不升级**。升版本会让旧 validator/QA 工具拒绝新证据。
- `fetch_state.version = 2` 是磁盘状态的迁移标记：v1 无 `last_uid`，读取时安全降级为不跳过；v2 才有 UIDVALIDITY/检查点。
- 只有新增/删除/改变证据字段时才需要 bump；复用条数属于诊断信息，不写入证据契约。

### 8.4 真实 OCR 压测结果

同机 Windows / Python 3.12 / `rapidocr_onnxruntime`，2 页合成发票，10 次热调用：

| 指标 | thread | process |
|---|---|---|
| 冷启动首次 2 页识别 | 4.12 s | 4.55 s |
| 单页热调用 p50 / p95 | 1.11 / 1.16 s | 1.13 / 1.15 s |
| 2 worker 并发总耗时 | 2.19 s | 2.25 s |
| 超时检测（子进程强杀） | — | 0.52 s |
| 超时后重启 | — | 0.44 s |
| 父进程 RSS（未含子进程） | 154 MB | 157 MB |
| 遗留子进程 | 0 | 0 |

结论：进程模式热路径与线程模式基本持平，冷启动多约 0.4 s，能硬杀卡死推理且不泄漏子进程；**但尚未在 Windows 冻结包与插件 headless 环境做真实 ONNX 集成压测，默认仍关闭**（`TIDYINVOICE_OCR_RUNTIME=process` 才启用）。

### 8.5 插件 vendored engine：不必要入库

- `npm pack` 的 `prepack` 会执行 `test:package`，其 `pretest:package` 先运行 `prepare-engine.mjs` 从仓库根生成引擎；`verify-package.mjs` 再校验清单。因此 tarball 一定包含最新引擎，git 不需要跟踪生成物。
- 本轮修正了真正的缺口：插件 CI 的 `paths` 现在覆盖根目录 `*.py`、`app_services/**`、`expense_rules/**`、`builtin/**`，并显式执行 `prepare-engine`、`check-engine`、`test:package`。
- 新增 `npm run check-engine`：对比生成物与源文件哈希/清单；缺失或过期退出 1（已在“删除生成文件”场景验证）。
- 只有未来要求“git clone 后不装 Node/npm 直接可用”或需要逐行审计引擎差异时，才改为跟踪并配合 `--check`。

### 8.6 仍未做

- 主邮件 UID 检查点（按 8.2 的决策暂不实现）。
- 证据 schema 升级（无必要）。
- OCR 进程模式在冻结包/插件 headless 的真实 ONNX 集成压测与默认启用。
- `app_api` 剩余窗口/路径桥接与结果聚合的更细拆分。

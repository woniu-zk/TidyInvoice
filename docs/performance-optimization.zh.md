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

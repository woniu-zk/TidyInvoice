# 项目协作约定（面向人类贡献者与 AI 代理）

## 品牌与身份

- 产品名、署名、仓库地址、应用目录、进程名与环境变量前缀都只在 [`brand.json`](brand.json) 中维护；Python 与桌面端通过生成物消费，新增硬编码会被 `node tools/brand/check.mjs` 拦下。
- 改动品牌后必须运行 `node tools/brand/generate.mjs` 并提交生成物；不要手改 `brand_generated.py`、`templates/brand.generated.js`、`templates/index_app.built.js`。
- 上游品牌只允许出现在 `brand.json` 的 `upstream` 段、`LICENSE`、`NOTICE`、[`docs/UPSTREAM.md`](docs/UPSTREAM.md) 与 `CHANGELOG.md` 的溯源段落。

## 工程门禁

提交前至少跑通与改动范围相关的门禁：

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
node tools/compile-frontend.mjs --check
node tools/brand/generate.mjs --check
node tools/brand/check.mjs
```

说明：`tests/test_batch_validation.py::test_pinned_baseline_contract_uses_current_stable_hardware_fingerprint` 是机器绑定的 `env_bound` 用例，本地全量会失败、CI 以 `--deselect` 排除；其余用例应为绿。

改动 `templates/index_app.js` 后必须运行 `node tools/compile-frontend.mjs` 并提交产物。插件改动需另跑 `cd plugins/dsh-invoice-downloader && npm test && npm run test:package`。

## 前端文案

- 不要把设计说明、实现说明、改造理由、TODO、评审意见或范围解释渲染成用户可见文案。
- 页面头部、徽章、状态栏、辅助说明、空状态与对话框副标题是开发语气最易泄漏的区域，改版后需逐屏检查。
- 可见文案应来自产品意图与用户工作流，而不是实现过程注释。
- 品牌相关的可见文案来自 `templates/brand.generated.js`；后续多语言文案来自 `templates/locale/*.json`，不要在组件里新增硬编码产品名。

## README 规范

- 以仓库当前提交的 `README.md` / `README.en.md` 结构为基线：中文为主、英文镜像；保留徽章、整体工作流程、识别链路、配置指南、常见问题、隐私与安全、免责声明、许可证与页脚等章节。
- README 改动限于事实修正、链接修复、发布状态同步与品牌/署名替换；不要主动重排或重写文档结构。
- 内容应读起来像面向用户的产品手册，而不是交接备忘或内部工程总结。
- 发布资产变化时，先更新下载链接与发布说明，再对外发布。
- 不写入个人数据、内部测试标签、开发注释或过时的发布指引。

## 数据与隐私

- 真实邮箱、真实发票内容、真实公司名与个人姓名不得进入仓库（含测试夹具与示例数据）。
- 日志、诊断与提交信息中不得包含授权码、邮箱地址等凭据信息。

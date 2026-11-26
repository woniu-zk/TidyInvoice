# Changelog

本文件记录项目的重要变更，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [Unreleased]

### Added

- 新增常用邮箱通道：网易（163 / 126 / 188 / yeah.net / 网易企业邮）、88 邮箱、腾讯企业邮、新浪、搜狐、21CN、263、139 / 189、阿里邮箱，以及 Gmail、iCloud、Yahoo、Zoho、Yandex、GMX、AOL、Fastmail；未知域名改为明确提示不支持，不再静默回落到 QQ 邮箱。
- 新增品牌单一事实源 `brand.json` 与生成器 `tools/brand/generate.mjs`，一次生成 Python 常量与桌面端品牌清单。
- 新增品牌泄漏检查 `tools/brand/check.mjs` 与一致性测试 `tests/test_brand_consistency.py`。
- 新增 [`docs/UPSTREAM.md`](docs/UPSTREAM.md)：上游来源、许可证义务与向上游回馈的方式。
- 新增 [`docs/brand.md`](docs/brand.md)：品牌配置字段说明与改名步骤。
- 新增许可证说明体系：[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)、[`docs/LICENSING.md`](docs/LICENSING.md)、[`LICENSES/AGPL-3.0.txt`](LICENSES/AGPL-3.0.txt) 与第三方兜底许可文本，明确「自有代码 Apache-2.0 + 分发包含 AGPL-3.0 组件 PyMuPDF」的双层结论。
- 新增 `tools/licenses/collect.py`：构建期生成第三方许可清单与文本；Windows 安装包与 macOS `.app` 均随包分发 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 与 `licenses/`。

### Changed

- 桌面端邮箱地址改为完整地址输入并即时校验；文档补充支持的邮箱列表与各邮箱授权码差异。
- 产品更名为 **整票（TidyInvoice）**：仓库迁至 `woniu-zk/tidyinvoice`，npm 包改为 `@woniu-zk/dsh-invoice-downloader`，安装包与 DMG 资产名同步更新。
- 应用数据目录改为 `%APPDATA%\TidyInvoice`（macOS 为 `~/Library/Application Support/TidyInvoice`），旧的 `InvoiceFlowAI` 目录会作为迁移来源自动读取。
- 环境变量前缀统一改为 `TIDYINVOICE_*`；单实例互斥量、临时文件、IMAP 客户端标识与线程名同步更名。
- Windows 安装器使用新的 `AppId`，避免与上游安装互相覆盖；macOS bundle id 改为 `com.github.woniu-zk.tidyinvoice`。
- 品牌图标改为「蜗牛」标识（`build/assets/tidyinvoice-icon.png`，Windows `.ico` 由母版导出）。
- 运行时身份（窗口标题、单实例互斥量、应用目录与旧目录迁移、环境变量、IMAP 客户端名、线程名、规则文件头）改由生成的品牌常量提供，不再在各模块中硬编码。
- 桌面端品牌名、副标题、仓库入口与会话存储前缀改由 `templates/brand.generated.js` 注入；页面标题在启动时按品牌设置。
- 构建包检查改为校验结构标记（`const APP_BRAND =`、`window.__APP_BRAND__` 等），不再依赖产品名字面量。
- 内置分类规则文件头不再写入应用名，数据文件保持品牌中立。

### Removed

- 移除内部交付报告（`.superpowers/sdd/*`）与含旧品牌的 README 截图；产品截图待重新拍摄后回填。
- 测试夹具中的真实姓名替换为虚构姓名。

### Fixed

- 修正 `AGENTS.md` 中指向不存在提交的 README 基线说明，改为可验证的结构约定。
- 修正桌面端窗口不居中：显示前按主显示器工作区与 DPI 摆放，窗口完整落在屏幕内。
- 修正桌面端窗口无法缩放：无边框窗口补上边/角缩放手势，改由前端指针事件驱动。
- 修正桌面端窗口无法拖动：拖动区选择器与界面类名 `pywebview-drag-region` 对齐。

### Known issues

- `tests/test_batch_validation.py::test_pinned_baseline_contract_uses_current_stable_hardware_fingerprint` 绑定参考机器硬件指纹，托管 CI 与本地全量运行均会失败，CI 以 `--deselect` 排除。

# 贡献指南

感谢你愿意参与本项目的开发。本项目是本地优先的电子发票整理与报销准备工具，包含桌面端、命令行入口与 DeepSeek Harness 插件三部分。本文档说明如何搭建本地开发环境、运行检查，以及提交与评审流程。

参与本项目即表示你同意遵守 [行为准则](CODE_OF_CONDUCT.md)。

## 目录

- [可以贡献什么](#可以贡献什么)
- [环境要求](#环境要求)
- [Windows 环境搭建](#windows-环境搭建)
- [macOS 环境搭建](#macos-环境搭建)
- [常用命令](#常用命令)
- [关于机器绑定测试](#关于机器绑定测试)
- [品牌与身份](#品牌与身份)
- [提交信息规范](#提交信息规范)
- [DCO 签署](#dco-签署)
- [生成物与禁止手改清单](#生成物与禁止手改清单)
- [PR 流程与检查清单](#pr-流程与检查清单)
- [安全漏洞](#安全漏洞)
- [数据与隐私](#数据与隐私)

## 可以贡献什么

- 缺陷修复，尤其是可复现的识别、归档、规则匹配问题
- 本地解析、OCR、规则抽取相关的测试与边界用例
- 桌面端界面（`templates/index_app.js` + React）与文档改进
- 分类归档、Excel 汇总、命令行入口的改进
- DeepSeek Harness 插件（`plugins/dsh-invoice-downloader`）
- 构建、打包与工程化改进

提交较大的功能改动前，建议先通过 issue 说明使用场景与方案，避免重复工作。

## 环境要求

| 依赖 | 要求 | 说明 |
| --- | --- | --- |
| Python | 3.12 | `pyproject.toml` 的 `target-version = "py312"`；CI 与发布构建均使用 Python 3.12 |
| Node.js | 24.x | 前端与品牌生成脚本需要 Node；插件 `engines.node` 要求 `>=24.9.0`，插件 CI 使用 Node 24 |
| npm | >=10 | 插件 `engines.npm` 要求 |
| Git | 2.x | 提交需要 DCO 签署 |

Python 运行期与测试依赖统一由 [requirements.test.txt](requirements.test.txt) 安装；该文件通过 `-r requirements.txt` 间接引入运行期依赖。

## Windows 环境搭建

在仓库根目录执行：

```powershell
# 1. 创建虚拟环境（需要 Python 3.12）
python -m venv .venv

# 2. 安装运行期 + 测试依赖（含 pytest、ruff）
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.test.txt

# 3. 可选：链接发票恢复使用 Playwright + Chromium
.\.venv\Scripts\python.exe -m playwright install chromium
```

启动桌面端：

```powershell
.\.venv\Scripts\python.exe main.py
```

仓库根目录另提供 Windows 启动脚本，内部同样调用 `.venv\Scripts\python.exe main.py`。

## macOS 环境搭建

支持 Apple Silicon（CI 的 macOS 发布构建为 arm64）。在仓库根目录执行：

```bash
# 1. 创建虚拟环境（需要 Python 3.12）
python3.12 -m venv .venv

# 2. 安装 pyzbar 的系统依赖（macOS CI 同样安装 zbar）
brew install zbar

# 3. 安装运行期 + 测试依赖
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.test.txt

# 4. 可选：链接发票恢复使用 Playwright + Chromium
.venv/bin/python -m playwright install chromium
```

启动桌面端：

```bash
.venv/bin/python main.py
```

## 常用命令

以下命令默认在仓库根目录执行。提交前至少跑通与改动范围相关的门禁。

### 运行测试

Windows：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

macOS：

```bash
.venv/bin/python -m pytest -q
```

- 当前完整套件收集到 **1388** 个用例（测试位于 `tests/`；数量随用例新增会变化，以 `pytest --collect-only -q` 的输出为准）。
- `tests/conftest.py` 会把 `APPDATA` / `LOCALAPPDATA` 指向测试临时目录，测试不会读写你本机的真实设置与发票数据。
- 运行测试前请确认已安装 `requirements.test.txt`（包含 pytest）。

### Lint

Windows：

```powershell
.\.venv\Scripts\python.exe -m ruff check .
```

macOS：

```bash
.venv/bin/python -m ruff check .
```

- ruff 固定为 `0.17.5`（见 `requirements.test.txt`），CI 与之一致。
- 配置在 `pyproject.toml` 的 `[tool.ruff]`：目标 Python 3.12，规则集 `E4`/`E7`/`E9`/`F`，`line-length = 100`。
- 当前工作树应输出 `All checks passed!`。
- 仓库没有接入独立的 formatter；不要为了格式化提交大范围无关改动。

### 前端产物

```powershell
# 只校验已提交产物与 templates/index_app.js 是否一致（不一致退出码 1）
node tools/compile-frontend.mjs --check

# 重新生成 templates/index_app.built.js
node tools/compile-frontend.mjs
```

- 只要改动了 `templates/index_app.js`，就必须重新生成并**提交** `templates/index_app.built.js`；否则 `--check` 与 `tests/test_frontend_build_contract.py` 会失败。
- 产物由 `tools/compile-frontend.mjs` 配合 `tools/vendor/babel.min.js` 生成，必须由脚本产出，**不要手动编辑**。

### 品牌生成物与一致性检查

```powershell
# 校验品牌生成物与 brand.json 是否一致（不一致退出码 1）
node tools/brand/generate.mjs --check

# 品牌字面量泄漏检查（默认硬性校验运行时代码区域）
node tools/brand/check.mjs
```

- 产品名、署名、仓库地址、应用目录名、进程名与环境变量前缀只在 [brand.json](brand.json) 中维护；Python 与桌面端通过生成物消费，不要在代码里新增硬编码。
- 改动品牌后必须运行 `node tools/brand/generate.mjs` 并提交生成物；不要手改 `brand_generated.py`、`templates/brand.generated.js`、`templates/index_app.built.js`。
- 上游品牌只允许出现在 `brand.json` 的 `upstream` 段、`LICENSE`、`NOTICE`、`docs/UPSTREAM.md` 与 `CHANGELOG.md` 的溯源段落。

### DeepSeek Harness 插件

```powershell
cd plugins/dsh-invoice-downloader
npm ci
npm test
npm run test:package
```

- `npm test` 会先执行 `npm run build`（TypeScript 编译）。
- `npm run test:package` 会先通过 `prepare-engine` 生成插件内的引擎副本，再校验发布包内容。
- 插件 CI（`.github/workflows/dsh-plugin-smoke.yml`）在 macOS 上执行上述步骤，并额外打包、安装到隔离的 DSH profile，做加载与 RPC 冒烟。

## 关于机器绑定测试

`tests/test_batch_validation.py::test_pinned_baseline_contract_uses_current_stable_hardware_fingerprint` 校验的是冻结性能基线所绑定的**参考机硬件指纹**，并带有 `@pytest.mark.env_bound` 标记。它在非参考机上（包括托管 CI runner）预期失败，CI 会通过 `--deselect` 排除它。**这条失败不代表工程环境坏了。**

本地跳过它运行完整套件：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --deselect=tests/test_batch_validation.py::test_pinned_baseline_contract_uses_current_stable_hardware_fingerprint
```

CI 中 Windows 全量套件与发布测试门禁都使用同一条 `--deselect`（见 `.github/workflows/core-tests.yml`、`.github/workflows/release-desktop.yml`）。macOS 任务只运行可移植子集：

```bash
.venv/bin/python -m pytest -q \
  tests/test_core_review_fixes.py tests/test_invoice_regression_p2.py \
  tests/test_mailbox_scanner.py tests/test_pairing_engine.py \
  tests/test_run_coordinator.py tests/test_run_lifecycle.py \
  tests/test_task8_review_remediation.py
```

## 品牌与身份

- 品牌相关事实（产品名、署名、仓库与发布链接、应用目录、进程/互斥量名、环境变量前缀）只在 `brand.json` 维护，`brand_generated.py` 与 `templates/brand.generated.js` 是它的生成物。
- 新增用户可见品牌文案应来自 `templates/brand.generated.js`，不要在组件里硬编码产品名。
- `node tools/brand/check.mjs` 会检查品牌字面量是否出现在允许的位置；提交前请确认运行时代码区域 0 命中。

## 提交信息规范

采用 `type(scope): 摘要` 的 Conventional Commits 风格，`scope` 可省略：

| 类型 | 用途 |
| --- | --- |
| `feat` | 新增功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档变更 |
| `chore` | 构建、依赖、工具等杂项 |
| `refactor` | 不改变外部行为的重构 |
| `test` | 测试新增或调整 |

约定：

- 摘要使用祈使句，直接说明改了什么；中英文均可。
- 一个提交只做一件事，一个 PR 围绕一个主题。
- 破坏性变更请在正文写 `BREAKING CHANGE:` 并说明迁移方式。

示例（格式参考仓库现有提交历史）：

```text
feat: 本地整理布局切换与原件原样保留
fix: tolerate BOM/corrupt scoped state files instead of failing the run
docs: 补充 Windows 源码启动说明
test: 覆盖 URL 恢复策略的非公网地址拒绝
```

## DCO 签署

本项目采用 [Developer Certificate of Origin 1.1](https://developercertificate.org/)（DCO）作为贡献者原创声明，不需要额外签署 CLA。

每个提交都必须包含 `Signed-off-by` 行：

```powershell
git commit -s -m "fix: ..."

# 已提交但忘记签署时：
git commit --amend -s --no-edit
```

签署行格式：

```text
Signed-off-by: 你的名字 <你的邮箱>
```

姓名与邮箱应与提交作者一致，并且你确认有权按[项目许可证](LICENSE)提交该贡献。PR 中如存在未签署的提交，维护者会要求补签后再合并。

## 生成物与禁止手改清单

以下内容由脚本生成。请修改源文件或生成脚本后重新生成，不要手动编辑，也不要在 PR 中直接提交手工改动：

| 路径 | 生成方式 | 是否入库 |
| --- | --- | --- |
| `brand_generated.py`、`templates/brand.generated.js` | `node tools/brand/generate.mjs` | 是，必须与 `brand.json` 的改动一起提交 |
| `templates/index_app.built.js` | `node tools/compile-frontend.mjs` | 是，必须与 `templates/index_app.js` 的改动一起提交 |
| `plugins/dsh-invoice-downloader/lib/**` | `npm run build`（tsc） | 否（`.gitignore` 忽略） |
| `build/windows/version-info.generated.txt`、`build/windows/build-identity.generated.json` | 构建脚本 | 否（`.gitignore` 忽略） |
| `build/`、`dist/`、`release-assets/`、`release-bundle/` | 构建 / 发布产物 | 否（`.gitignore` 忽略） |
| 其他文件名含 `generated` 的构建产物 | 各自的生成脚本 | 视 `.gitignore` |

如确需调整生成结果，请修改生成脚本或源文件，并在 PR 中说明所用生成命令与结果。

## PR 流程与检查清单

1. 先搜索现有 issue，避免重复；较大的改动先开 issue 讨论。
2. 从仓库默认分支创建特性分支（例如 `fix/invoice-archive-order`）。
3. 完成改动，并在本地运行门禁：

   ```powershell
   # 本地全量会因机器绑定的 env_bound 用例失败，处理方式见「关于机器绑定测试」
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe -m ruff check .
   node tools/compile-frontend.mjs --check
   node tools/brand/generate.mjs --check
   node tools/brand/check.mjs
   ```

4. 按 [PR 模板](.github/PULL_REQUEST_TEMPLATE.md) 填写说明、验证步骤与测试证据。
5. 提交 PR 后关注 CI：`core-tests.yml` 先跑 ruff lint，再跑 Windows 全量套件与 macOS 可移植子集；涉及插件时还会触发 `dsh-plugin-smoke.yml`。
6. 处理审查意见；如被要求补签 DCO 或重新生成产物，请更新同一分支。

提交前自查：

- [ ] 测试与 lint 通过（或已在 PR 中说明无法运行的原因与范围）
- [ ] 前端源码有改动时，已重新生成并提交 `templates/index_app.built.js`
- [ ] 品牌有改动时，已运行品牌生成器、提交生成物并通过品牌检查
- [ ] 没有提交真实发票、邮箱地址、授权码、`.env`、诊断日志或其他构建产物
- [ ] 没有引入遥测、外部识别 API 或需要联网的识别路径
- [ ] 如改动了依赖版本，已同步 `requirements*.txt` 与打包契约测试
- [ ] 每个提交都包含 DCO `Signed-off-by`
- [ ] 文档描述与命令行为一致

## 安全漏洞

**不要在公开 issue / PR 中披露安全漏洞**，也不要附带真实凭据或发票数据。请按 [SECURITY.md](SECURITY.md) 中的私密渠道报告，具体联系方式见该文档。

## 数据与隐私

- 提交 issue / PR 时请对日志、截图和路径脱敏，移除邮箱地址、授权码、发票内容与个人姓名。
- 本项目坚持本地识别与无遥测；请勿在贡献中引入把发票内容或使用数据发送到第三方的逻辑。

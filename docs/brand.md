# 品牌与身份配置

产品的名称、署名、仓库地址、应用目录与安装身份都来自**单一事实源** [`brand.json`](../brand.json)。Python 代码、桌面端前端与后续的构建脚本都消费它的生成物，不再各自硬编码品牌字面量。

## 文件关系

```
brand.json                     ← 唯一需要人编辑的品牌源
  ├─ brand_generated.py        ← 生成物：Python 常量（导入即用）
  └─ templates/brand.generated.js ← 生成物：桌面端 window.__APP_BRAND__
```

生成命令：

```powershell
node tools/brand/generate.mjs          # 重新生成
node tools/brand/generate.mjs --check  # 校验生成物与 brand.json 一致
```

生成物必须提交入库。改动 `brand.json` 后忘记重新生成时，`--check` 与 `tests/test_brand_consistency.py` 都会失败。

## 字段含义

| 字段 | 作用域 |
|---|---|
| `identity.displayName.zh/en` | 产品名：窗口标题、界面标题、文档 |
| `identity.slug` / `identity.pythonPackage` | 可执行文件名、Python 包名、URL 与目录命名 |
| `identity.tagline` | 界面副标题 |
| `identity.copyrightHolder` / `identity.year` | NOTICE、版本资源、文件头署名 |
| `urls.*` | 界面里的仓库入口、README 徽章与下载链接 |
| `upstream.*` | 上游来源与署名；泄漏检查也用它识别上游痕迹 |
| `runtime.appDirName` / `legacyAppDirNames` | `%APPDATA%` 配置、规则、状态目录；旧目录用于迁移 |
| `runtime.mutexName` / `tempFilePrefix` / `tempDirPrefix` | 单实例互斥量与临时文件命名 |
| `runtime.imapClientName` | IMAP `ID` 命令中上报给邮件服务器的客户端名 |
| `runtime.ruleFileHeader` | 生成的规则 YAML 文件头署名 |
| `env.*` | 运行时环境变量名（构建脚本、测试、诊断共用） |
| `build.*` | Windows/macOS/npm 发布身份（当前仍在构建脚本中，逐步迁移到生成物） |

## 改名步骤

1. 编辑 `brand.json`：改 `identity`、`urls`、`upstream` 之外只保留上游信息，同步 `runtime.*` 与 `env.*` 的命名（建议统一用新 slug 的前缀）。
2. 运行 `node tools/brand/generate.mjs`，提交两个生成物。
3. 运行 `node tools/brand/check.mjs --list`，按输出清单逐项替换剩余字面量。
4. 同步发布身份：Windows 安装器 `AppId`（必须换新 GUID，否则会与上游安装互相覆盖）、macOS bundle id、npm scope。
5. 更新 [`LICENSE`](../LICENSE) / [`NOTICE`](../NOTICE) / [`docs/UPSTREAM.md`](UPSTREAM.md) 的署名与派生说明。
6. 全量验证：`pytest -q`、`ruff check .`、`node tools/compile-frontend.mjs --check`、`node tools/brand/generate.mjs --check`。

## 泄漏检查的分区

`node tools/brand/check.mjs` 按区域统计品牌字面量：

| 区域 | 默认行为 | 说明 |
|---|---|---|
| `runtime` | **硬性失败** | 根目录 Python、`expense_rules/`、桌面端模板 |
| `tests` | 仅报告 | 断言与夹具中的品牌引用 |
| `build` | 仅报告 | `.github/` 与 `build/` 的发布身份 |
| `plugins` | 仅报告 | DSH 插件包（有自己的 npm 身份） |
| `docs` | 仅报告 | README、NOTICE、文档：按设计保留溯源信息 |

迁移完成后用 `node tools/brand/check.mjs --strict` 收紧为全域 0 命中。

## 不要做的事

- 不要手改 `brand_generated.py`、`templates/brand.generated.js`、`templates/index_app.built.js`；
- 不要在界面或构建门禁里写死产品名——门禁只校验结构标记（`const APP_BRAND =`、`window.__APP_BRAND__` 等）；
- 不要把上游品牌写进新的代码路径：它只应出现在 `brand.json` 的 `upstream` 段、NOTICE、本目录文档与 CHANGELOG 的溯源段落。

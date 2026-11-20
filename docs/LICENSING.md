# 许可证说明

这份文档说明「整票（TidyInvoice）」的许可证结构，以及使用、再分发和商业化的边界。

## 一句话概括

- **仓库里的自有代码**：Apache License 2.0 —— 可商用、可修改、可闭源集成。
- **发布的安装包**：包内含 **AGPL-3.0 组件 PyMuPDF**，因此分发物需要按 AGPL-3.0 提供对应源码。
- **第三方依赖**：各自许可证，随包附文本与清单。

## 1. 文件对应关系

| 文件 | 作用 |
|---|---|
| [`LICENSE`](../LICENSE) | 本项目自有代码的 Apache-2.0 全文 |
| [`NOTICE`](../NOTICE) | 上游项目与本项目的归属声明（上游声明原文保留） |
| [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) | 第三方组件、许可证与源码获取方式 |
| [`LICENSES/AGPL-3.0.txt`](../LICENSES/AGPL-3.0.txt) | AGPL-3.0 全文（PyMuPDF 适用） |
| [`LICENSES/third-party/`](../LICENSES/third-party/) | wheel 未自带许可文本的依赖兜底文本 |
| [`docs/UPSTREAM.md`](UPSTREAM.md) | 衍生关系、许可证义务与向上游回馈 |
| `tools/licenses/collect.py` | 构建期生成依赖许可清单与文本 |

## 2. 你可以做什么

### 对仓库自有代码（Apache-2.0）

- 使用、修改、分发、商用、闭源集成；
- 再分发时须保留版权声明、许可证文本、[`NOTICE`](../NOTICE) 归属与第三方声明；
- 不得暗示原作者为你的修改背书。

### 对发布安装包（含 AGPL-3.0 组件）

- 安装、自用、在公司内部使用；
- 再分发时，必须让接收者能够获得对应源码（本项目仓库 + PyMuPDF 对应版本），并保留许可声明；
- 可以收费（AGPL 不禁止商业化），但**不能阻止接收者再分发**。

### 企业使用

- 内部部署不需要对外开源你的内部数据与流程；
- 若你修改了程序并让外部用户通过网络交互使用，需按 AGPL-3.0 §13 向这些网络用户提供对应源码；
- 上架应用商店或通过 OSS 合规审计时，AGPL 组件通常需要单独说明，建议提前准备第三方声明。

## 3. 再分发者的义务清单

1. 保留 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 与 `licenses/` 目录；
2. 保留 PyMuPDF 的版权与 AGPL-3.0 文本，不得移除；
3. 提供对应源码的获取方式（仓库地址 + 版本 tag / PyMuPDF 版本）；
4. 不得附加与 AGPL 冲突的额外限制（例如禁止再分发、禁止反向工程）。

## 4. 常见问题

**能收费吗？**
能。开源不等于免费；可以卖安装包、支持、部署、SLA。

**能把付费功能闭源、打进同一个安装包吗？**
不能。AGPL 要求向收到分发物的人提供完整对应源码；付费模块若与主程序编译/打包在一起，同样受 AGPL 约束。

**想把付费功能闭源，有什么合法做法？**
把它做成独立程序（独立进程、独立安装、通过 HTTP / IPC / 文件通信，不 `import` 主程序模块），单独许可；或购买 PyMuPDF 商业许可后做整体商业授权。

**能只提供云端服务、不发安装包吗？**
托管未修改版本一般不额外触发 §13；一旦修改了程序并对外提供交互式服务，就需要向网络用户提供源码。

**用户能自己编译并使用吗？**
可以。Apache-2.0 与 AGPL-3.0 都允许；客户付钱买的是交付、支持与责任。

**能做双许可吗？**
可以，但需要：① 你拥有相关代码版权或已取得贡献者授权（当前仓库使用 DCO，不足以重新许可他人贡献，需 CLA）；② 解决 PyMuPDF 的 AGPL 约束。

**换掉 PyMuPDF 可行吗？**
可行：文本抽取可换 `pdfplumber` / `pypdf`，渲染可换 `pypdfium2`；改动点在 PDF 解析、渲染与 OCR 前处理相关模块，需要回归识别用例。

## 5. 核查方式

```powershell
# 生成第三方许可清单（构建环境需已安装 requirements.release.txt）
.venv\Scripts\python.exe tools\licenses\collect.py --output build\licenses

# 检查品牌/许可文档改动没有引入构建门禁问题
.venv\Scripts\python.exe -m ruff check .
node tools/brand/check.mjs
```

发布前确认：`build/licenses/third-party/INDEX.md` 中没有「未提供」，安装包内包含 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 与 `licenses/`。

## 6. 商业许可路径

- **PyMuPDF**：向 Artifex 购买商业许可后，可闭源分发包含 PyMuPDF 的安装包；
- **自身代码双许可**：社区版维持 Apache-2.0（或 AGPL），商业版按专有许可提供；需要 CLA 与明确的贡献者授权；
- **服务型收费**：签名安装包、自动更新、优先支持、部署培训、企业 SLA —— 不改变任何许可证。

## 7. 贡献与 CLA

当前 [CONTRIBUTING.md](../CONTRIBUTING.md) 要求 DCO 签署，贡献按本仓库许可证授权。若未来引入双许可或专有版本，需要在此之前改为 CLA 并取得既有贡献者的书面同意。

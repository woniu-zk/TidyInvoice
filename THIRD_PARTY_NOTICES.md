# 第三方声明（Third-Party Notices）

本文件说明「整票（TidyInvoice）」在**发布安装包**中分发的第三方组件、适用许可证，以及再分发时需要履行的义务。

## 1. 许可证分层

| 范围 | 许可证 | 说明 |
|---|---|---|
| 本项目自有代码 | Apache License 2.0 | 全文见 [LICENSE](LICENSE) |
| 上游衍生部分 | Apache License 2.0 | 归属见 [NOTICE](NOTICE) 与 [docs/UPSTREAM.md](docs/UPSTREAM.md) |
| 第三方运行时依赖 | 各自许可证（见第 2 节） | 发布包内附许可文本 |
| PyMuPDF | AGPL-3.0 或 Artifex 商业许可 | 见第 3 节 |

## 2. 运行时依赖

以下版本取自 `requirements.release.txt` 与插件 `runtime/requirements-headless.txt`，许可证取自各 wheel 元数据。

| 组件 | 版本 | 许可证 | 项目主页 |
|---|---|---|---|
| beautifulsoup4 | 4.14.3 | MIT | https://www.crummy.com/software/BeautifulSoup/ |
| clr_loader | 0.2.10 | MIT | https://github.com/pythonnet/clr-loader |
| keyring | 25.7.0 | MIT | https://github.com/jaraco/keyring |
| openpyxl | 3.1.5 | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| pillow | 12.1.1 | MIT-CMU (HPND) | https://python-pillow.github.io |
| playwright | 1.58.0 | Apache-2.0 | https://github.com/microsoft/playwright-python |
| **PyMuPDF** | **1.27.1** | **AGPL-3.0 或商业许可** | https://github.com/pymupdf/pymupdf |
| pythonnet | 3.0.5 | MIT | https://github.com/pythonnet/pythonnet |
| pywebview | 6.1 | BSD-3-Clause | https://pywebview.flowrl.com/ |
| pyzbar | 0.1.9 | MIT | https://github.com/NaturalHistoryMuseum/pyzbar |
| requests | 2.32.5 | Apache-2.0 | https://github.com/psf/requests |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0 | https://github.com/RapidAI/RapidOCR |
| onnxruntime | 1.32.0 | MIT | https://onnxruntime.ai |
| opencv-python | 5.0.0.93 | Apache-2.0 | https://github.com/opencv/opencv-python |
| numpy | 2.5.5 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml |
| urllib3 | 2.8.0 | MIT | https://pypi.org/project/urllib3/ |
| shapely | 2.2.0 | BSD-3-Clause | https://github.com/shapely/shapely |
| pyclipper | 1.4.0 | MIT | https://github.com/fonttools/pyclipper |
| protobuf | 7.36.2 | BSD-3-Clause | https://github.com/protocolbuffers/protobuf |
| flatbuffers | 25.12.19 | Apache-2.0 | https://github.com/google/flatbuffers |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | https://tqdm.github.io |
| tzdata | 2026.4 | Apache-2.0 | https://github.com/python/tzdata |

第三方依赖的完整清单（含传递依赖、许可文件与来源）由 `tools/licenses/collect.py` 在构建时生成，随发布包提供于：

- Windows：安装目录下的 `licenses/third-party/INDEX.md`
- macOS：`TidyInvoice.app/Contents/Resources/licenses/third-party/INDEX.md`

## 3. AGPL-3.0 组件：PyMuPDF

- **用途**：PDF 文本层解析、页面渲染与 PDF 生成。
- **许可**：GNU Affero General Public License v3.0（AGPL-3.0），或向 Artifex 购买商业许可。
- **修改情况**：本项目未修改 PyMuPDF 源码。
- **影响**：Windows 安装版 / 免安装版与 macOS DMG 中包含 PyMuPDF 的二进制，因此**发布的分发物需满足 AGPL-3.0**：向接收者提供完整对应源码、保留版权与许可声明、不得附加额外限制。
- **完整许可文本**：仓库内 [`LICENSES/AGPL-3.0.txt`](LICENSES/AGPL-3.0.txt)；发布包内 `licenses/PyMuPDF-<版本>/AGPL-3.0.txt`。
- **对应源码获取方式**：
  1. 本项目源码（含构建脚本、依赖清单与打包配置）：见 [README](README.md) 中的仓库地址，使用与发布版本一致的 tag；
  2. PyMuPDF 对应版本（1.27.1）源码：<https://github.com/pymupdf/pymupdf>；
  3. Python 运行时依赖的版本固定清单：`requirements.release.txt`。
- **商业许可**：若需要闭源分发，请购买 Artifex 商业许可，或替换该组件（见 [docs/LICENSING.md](docs/LICENSING.md)）。

## 4. 发布包内的许可文件

| 文件 | 内容 |
|---|---|
| `LICENSE` | 本项目自有代码的 Apache-2.0 全文 |
| `NOTICE` | 上游与本项目的归属声明 |
| `THIRD_PARTY_NOTICES.md` | 本文件 |
| `licenses/AGPL-3.0.txt`、`licenses/third-party/` | AGPL-3.0 全文与各依赖许可文本、清单 |

Windows 安装包与免安装包把这些文件放在应用根目录；macOS 放在 `TidyInvoice.app/Contents/Resources/`。

## 5. DeepSeek Harness 插件（npm）

插件 npm 包本身**不包含** Python 运行时依赖，首次安装引擎时由用户在本机 `pip install` `runtime/requirements-headless.txt` 中的固定版本，其中包含 AGPL-3.0 的 PyMuPDF。因此：

- 插件包不是 PyMuPDF 的分发者，但仍需在文档中如实标注该运行时依赖及其许可证；
- 插件的 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 随 npm 包提供。

## 6. 更新与核查

```powershell
# 重新生成发布包的第三方许可清单
.venv\Scripts\python.exe tools\licenses\collect.py --output build\licenses
```

核查要点：`INDEX.md` 中不应出现「未提供」；新增依赖需同时更新本文件与 `LICENSES/third-party/` 下的兜底文本。

## 7. 免责声明

本文件是工程层面的合规说明，不构成法律意见。商业分发、并购尽调或应用商店上架前，建议由律师复核。

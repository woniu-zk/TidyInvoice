# WebView2 交付模式（fixed / evergreen）说明

本文档说明 整票（TidyInvoice）桌面端两种 WebView2 交付方式、构建命令、运行时行为与验证方法。
默认构建仍是 **fixed（内置固定版运行时）**，`evergreen` 为可选精简构建；两者共用同一套业务代码。

## 1. 两种模式

| | `fixed`（默认） | `evergreen`（可选） |
|---|---|---|
| WebView2 来源 | 安装包内置固定版运行时（pin + SHA256） | 使用机器已安装的系统 WebView2 运行时 |
| 离线可用 | ✅ 完全离线（不依赖系统组件） | ⚠️ 需要系统已装 WebView2（Win11 自带；Win10 通常已随 Edge 安装） |
| 安装包增量 | 内置运行时（裁剪后约 445 MiB） | 不内置运行时；可选携带 ~1.8 MiB bootstrapper 兜底安装 |
| 渲染确定性 | 固定版本，可复现 | 随系统 Edge 更新 |
| 适用场景 | 离线/内网/需固定渲染版本 | 追求小安装包、目标机器为 Win11 |

## 2. 构建命令

```powershell
# fixed（默认，行为与之前一致；会先裁剪固定运行时再打包）
.\build\windows\prepare_runtime.ps1 -WebView2Mode fixed
.\build\windows\build_release.ps1 -Version 2026.11.17.1 -WebView2Mode fixed `
  -RunPyInstaller -RunPortableZip -RunInstaller

# evergreen（系统运行时；构建机网络可用时自动下载 bootstrapper，否则仅警告）
.\build\windows\prepare_runtime.ps1 -WebView2Mode evergreen
.\build\windows\build_release.ps1 -Version 2026.11.17.1 -WebView2Mode evergreen `
  -RunPyInstaller -RunPortableZip -RunInstaller
```

- `prepare_runtime.ps1` 额外支持 `-WebView2Mode both`（固定运行时 + bootstrapper 都准备，便于同时产出两种构建）。
- 发布工作流 `.github/workflows/release-desktop.yml` 的 `workflow_dispatch` 新增 `webview2_mode` 输入（`fixed` / `evergreen`，默认 `fixed`），透传到 `qualify-windows-release.ps1 -WebView2Mode`。
- bootstrapper 下载地址固定为 Microsoft 官方链接（`build/windows/runtime-sources.json` → `webview2.bootstrapper.download_url`）；下载失败不会阻塞构建，只会降级为"依赖系统运行时"。

## 3. 运行时行为（`main.py`）

优先级：**命令行 `--webview2-mode fixed|evergreen` > 环境变量 `TIDYINVOICE_WEBVIEW2_MODE` > 自动检测**。

自动检测规则：能找到完整的固定版运行时目录则用 `fixed`，否则用 `evergreen`。

`evergreen` 模式下：

1. 读取注册表判断系统 WebView2 是否已安装（HKLM 64/32 位与 HKCU 的 `EdgeUpdate\Clients\{F3017226-…}`，读 `pv` 版本）；
2. 已安装 → 直接使用系统运行时；
3. 未安装但有 bootstrapper（安装包 `runtime/MicrosoftEdgeWebView2Setup.exe` 或 `build/runtime/`）→ 静默执行 `/silent /install`，安装后重试检测；
4. 仍未安装 → 抛错并在启动错误框/诊断中给出官方下载地址，不会静默崩溃。

启动诊断文件（`%LOCALAPPDATA%/TidyInvoice/diagnostics/webview_startup.json`）记录 `webview2_mode`、`webview2_version`、`runtime_dir`，便于现场排障。

## 4. 打包清单如何切换

- `build/windows/resources.manifest.json` → `webview2` 段声明 `defaultMode`、`modes`、`fixedRuntimeSource`、`bootstrapperSource/Target`；两个数据源在 `datas` 中均为 `optional: true`（构建期 hydrate，缺一个不应失败）。
- `build/windows/TidyInvoice.spec` 依据 `TIDYINVOICE_WEBVIEW2_MODE` 过滤 `datas`：`evergreen` 不打包固定运行时；`fixed` 不打包 bootstrapper。
- `build/windows/build_release.ps1`：`evergreen` 下跳过固定运行时 `requiredPaths` 校验与裁剪步骤，并把模式写入 PyInstaller 子进程环境变量。
- 固定运行时裁剪策略（`webview2-prune-policy.json`）仅在 `fixed` 构建中生效。

## 5. 验证

```powershell
# 模式解析 / 运行时配置 / 打包契约（14 条）
.\.venv\Scripts\python.exe -m pytest -q tests\test_webview2_modes.py

# PowerShell 语法与 JSON 有效性
powershell -NoProfile -Command "[void][System.Management.Automation.Language.Parser]::ParseFile('build\windows\build_release.ps1',[ref]$null,[ref]$null)"

# 构建预检（evergreen；本机无 PyInstaller 时最终会停在依赖检查，属预期）
powershell -NoProfile -ExecutionPolicy Bypass -File build\windows\build_release.ps1 -WebView2Mode evergreen -SkipPythonVersionCheck
```

已验证：`fixed` 模式在固定运行时缺失时会在 `requiredPaths` 处失败；`evergreen` 模式跳过该要求并继续到依赖检查（两者均以脚本方式验证）。完整 PyInstaller/Inno 构建与真机启动需在有打包环境与 WebView2 的机器上复核。

## 6. 回退

- 不传 `-WebView2Mode` 即回到默认 `fixed`，行为与改造前一致（发布工作流默认输入也是 `fixed`）。
- 固定运行时资产未被删除：仅在 `fixed` 构建时按策略裁剪，`prepare_runtime.ps1 -Force` 可重新 hydrate。

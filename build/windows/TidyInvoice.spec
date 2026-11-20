# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import json
import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


ROOT = Path(SPECPATH).resolve().parents[1]
MANIFEST_PATH = ROOT / "build" / "windows" / "resources.manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _require_module(module_name):
    """Fail the packaging run loudly when a required bundle module is missing."""
    if importlib.util.find_spec(module_name) is None:
        raise SystemExit(
            "OCR packaging dependency missing: "
            f"{module_name}. Install requirements.release.txt before building."
        )


datas = []
runtime_source_override = os.environ.get("TIDYINVOICE_RUNTIME_SOURCE", "").strip()
webview2_config = MANIFEST.get("webview2") or {}
webview2_mode = (
    os.environ.get("TIDYINVOICE_WEBVIEW2_MODE")
    or str(webview2_config.get("defaultMode") or "fixed")
).strip().lower()
if webview2_mode not in (webview2_config.get("modes") or ["fixed"]):
    raise SystemExit(
        f"Unsupported WebView2 mode for packaging: {webview2_mode}. "
        f"Expected one of: {', '.join(webview2_config.get('modes') or ['fixed'])}."
    )
fixed_runtime_source = str(webview2_config.get("fixedRuntimeSource") or "").strip()
bootstrapper_source = str(webview2_config.get("bootstrapperSource") or "").strip()
for item in MANIFEST["datas"]:
    item_source = str(item["source"])
    if item_source == fixed_runtime_source and webview2_mode == "evergreen":
        # Evergreen builds use the machine-wide runtime; never ship the fixed runtime.
        continue
    if item_source == bootstrapper_source and webview2_mode != "evergreen":
        # Fixed-runtime builds are self-contained; the bootstrapper is not needed.
        continue
    source_path = ROOT / item["source"]
    if runtime_source_override and item["source"] == MANIFEST["chromium"]["stagingDir"]:
        source_path = Path(runtime_source_override)
    if source_path.exists():
        datas.append((str(source_path), item["target"]))
    elif not item.get("optional", False):
        raise SystemExit(f"Required data path not found: {source_path}")

hiddenimports = list(MANIFEST.get("hiddenImports", []))
hiddenimports.extend(collect_submodules("pyzbar"))
binaries = list(collect_dynamic_libs("pyzbar"))

# ---------------------------------------------------------------------------
# Local no-API OCR engine (RapidOCR + ONNX Runtime).
#
# RapidOCR's PP-OCR ONNX model files and ONNX Runtime's native provider DLLs
# are loaded lazily/dynamically and are not reliably discovered by static
# analysis, so the module lists are declared in resources.manifest.json
# ("ocr" section) and expanded here with PyInstaller's collection helpers.
# The existing manifest "datas" mechanism above stays untouched.
# ---------------------------------------------------------------------------
ocr_config = MANIFEST.get("ocr") or {}

for module_name in ocr_config.get("requiredModules", []):
    _require_module(module_name)

for module_name in ocr_config.get("submodulePackages", []):
    _require_module(module_name)
    hiddenimports.extend(collect_submodules(module_name))

for module_name in ocr_config.get("dataModules", []):
    _require_module(module_name)
    datas.extend(collect_data_files(module_name))

for module_name in ocr_config.get("binaryModules", []):
    _require_module(module_name)
    binaries.extend(collect_dynamic_libs(module_name))

runtime_hooks = [str(ROOT / MANIFEST["runtimeHook"])]
version_path = ROOT / MANIFEST["version"]["rendered"]
version_file = str(version_path) if version_path.exists() else None
manifest_file = None
manifest_setting = (MANIFEST.get("windowsManifest") or "").strip()
if manifest_setting:
    manifest_path = ROOT / manifest_setting
    if not manifest_path.exists():
        raise SystemExit(f"Configured Windows manifest not found: {manifest_path}")
    manifest_file = str(manifest_path)
icon_value = None
icon_setting = ((MANIFEST.get("icon") or {}).get("exeIconPath") or "").strip()
if icon_setting:
    icon_path = ROOT / icon_setting
    if not icon_path.exists():
        raise SystemExit(f"Configured EXE icon not found: {icon_path}")
    icon_value = str(icon_path)


a = Analysis(
    [str(ROOT / MANIFEST["entryScript"])],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=MANIFEST["appName"],
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=version_file,
    icon=icon_value,
    manifest=manifest_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=MANIFEST["appName"],
)

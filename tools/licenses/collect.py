"""Collect third-party license texts for a release bundle.

Reads the pinned runtime requirements, resolves the installed distributions and
copies every license / notice file they ship into::

    <output>/<distribution>-<version>/

Wheels that do not carry their own license text are covered by the maintained
fallbacks in ``LICENSES/third-party`` (and ``LICENSES/AGPL-3.0.txt`` for the
AGPL-3.0 component). It also writes ``<output>/INDEX.md`` with a deterministic
inventory (package, version, declared license, source URL), so the shipped
installer contains the notices that permissive licenses require.
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.metadata as metadata
import pathlib
import shutil
import sys

DEFAULT_REQUIREMENTS = (
    "requirements.release.txt",
    "plugins/dsh-invoice-downloader/runtime/requirements-headless.txt",
)
LICENSE_FILE_PATTERNS = ("LICEN*", "COPYING*", "NOTICE*", "AUTHORS*", "COPYRIGHT*")
INDEX_NAME = "INDEX.md"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FALLBACK_DIR = REPO_ROOT / "LICENSES" / "third-party"
# 双许可组件：随包提供 AGPL-3.0 全文，商业许可需另行购买。
EXTRA_LICENSE_FILES = {"pymupdf": REPO_ROOT / "LICENSES" / "AGPL-3.0.txt"}


def _normalized(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(".", "_")


def _distribution_names(requirements_paths: list[pathlib.Path]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for path in requirements_paths:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name = line.split("==")[0].split(">=")[0].split("[")[0]
            name = name.split(";")[0].split(" ")[0].strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)
    return names


def _declared_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    license_field = (meta.get("License") or "").strip().splitlines()
    if license_field:
        value = license_field[0].strip()
        if value:
            return value
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return "UNKNOWN"


def _source_url(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in {"source", "source code", "repository", "homepage"}:
            return url.strip()
    homepage = (meta.get("Home-page") or "").strip()
    if homepage:
        return homepage
    return f"https://pypi.org/project/{meta.get('Name', '').strip()}/"


def _shiped_license_files(dist: metadata.Distribution) -> list[pathlib.Path]:
    base = pathlib.Path(dist.locate_file(""))
    found: list[pathlib.Path] = []
    for entry in dist.files or []:
        if not any(fnmatch.fnmatch(entry.name.upper(), pattern) for pattern in LICENSE_FILE_PATTERNS):
            continue
        path = pathlib.Path(dist.locate_file(entry))
        if path.is_file():
            found.append(path.relative_to(base))
    return sorted(found)


def _fallback_files(name: str) -> list[pathlib.Path]:
    key = _normalized(name)
    matches: list[pathlib.Path] = []
    if FALLBACK_DIR.is_dir():
        for candidate in sorted(FALLBACK_DIR.iterdir()):
            if candidate.is_file() and _normalized(candidate.name).startswith(key):
                matches.append(candidate)
    return matches


def _extra_files(name: str) -> list[pathlib.Path]:
    extra = EXTRA_LICENSE_FILES.get(_normalized(name))
    if extra is not None and extra.is_file():
        return [extra]
    return []


def _copy_package(dist: metadata.Distribution, output_root: pathlib.Path) -> dict[str, object]:
    name = (dist.metadata.get("Name") or "").strip()
    version = (dist.version or "").strip()
    base = pathlib.Path(dist.locate_file(""))
    target_dir = output_root / f"{name}-{version}"
    copied: list[str] = []

    shipped = _shiped_license_files(dist)
    if shipped:
        for relative in shipped:
            destination = target_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / relative, destination)
            copied.append(str(relative).replace("\\", "/"))

    if not copied:
        for source in _fallback_files(name):
            # 统一落到 <包名>-<版本>/ 根下，避免暴露维护目录结构。
            destination = target_dir / source.name
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied.append(source.name)

    # 双许可 / 需要额外全文的组件：无论 wheel 是否附带许可，都补齐完整文本。
    for source in _extra_files(name):
        destination = target_dir / source.name
        target_dir.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)
        if source.name not in copied:
            copied.append(source.name)

    return {
        "name": name,
        "version": version,
        "license": _declared_license(dist),
        "source": _source_url(dist),
        "files": copied,
    }


def _write_index(rows: list[dict[str, object]], output_root: pathlib.Path) -> None:
    lines = [
        "# Third-party license inventory",
        "",
        "由 `tools/licenses/collect.py` 依据当前构建环境生成，请勿手改。",
        "",
        "| 组件 | 版本 | 声明许可 | 许可文本 | 来源 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        file_count = len(row["files"])
        license_cell = f"{file_count} 个文件" if file_count else "未提供"
        lines.append(
            f"| {row['name']} | {row['version']} | {row['license']} | {license_cell} | {row['source']} |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 本项目自有代码的许可见仓库根目录 `LICENSE`；上游与第三方归属见 `NOTICE`、`THIRD_PARTY_NOTICES.md`。",
            "- AGPL-3.0 组件 PyMuPDF 的完整许可文本见同目录 `PyMuPDF-<version>/AGPL-3.0.txt`。",
        ]
    )
    missing = [row["name"] for row in rows if not row["files"]]
    if missing:
        lines.append("- 以下依赖仍未取得许可文本，请在发布前补齐：" + "、".join(missing))
    else:
        lines.append("- 所有依赖均已附带许可文本。")
    (output_root / INDEX_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="输出目录（发布包的 licenses 目录）")
    parser.add_argument(
        "--requirements",
        action="append",
        default=None,
        help="依赖清单路径，可重复；默认使用 release 与插件运行时清单",
    )
    args = parser.parse_args(argv)

    requirements = [pathlib.Path(p) for p in (args.requirements or DEFAULT_REQUIREMENTS)]
    missing_requirements = [str(p) for p in requirements if not p.is_file()]
    if missing_requirements:
        print(f"[licenses] 缺少依赖清单: {', '.join(missing_requirements)}", file=sys.stderr)
        return 1

    output_root = pathlib.Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    for name in _distribution_names(requirements):
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            print(f"[licenses] 警告: 未安装 {name}，跳过", file=sys.stderr)
            continue
        rows.append(_copy_package(dist, output_root))

    _write_index(rows, output_root)
    missing = [row["name"] for row in rows if not row["files"]]
    print(f"[licenses] 已收集 {len(rows)} 个组件，缺少许可文本 {len(missing)} 个 -> {output_root}")
    if missing:
        print("[licenses] 缺少: " + ", ".join(missing), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

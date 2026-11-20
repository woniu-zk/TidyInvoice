"""License inventory gate.

Every pinned runtime dependency must ship a license text in the release bundle,
otherwise the installer would distribute third-party code without the notices
that MIT / BSD / Apache-2.0 require. The AGPL-3.0 component (PyMuPDF) must also
carry the full license text.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "tools" / "licenses" / "collect.py"
AGPL_TEXT = ROOT / "LICENSES" / "AGPL-3.0.txt"


def _requirement_names() -> list[str]:
    names: list[str] = []
    for relative in (
        "requirements.release.txt",
        "plugins/dsh-invoice-downloader/runtime/requirements-headless.txt",
    ):
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name = line.split("==")[0].split(">=")[0].split("[")[0].split(";")[0].strip()
            if name and name.lower() not in {item.lower() for item in names}:
                names.append(name)
    return names


def test_agpl_text_is_checked_in():
    assert AGPL_TEXT.is_file()
    text = AGPL_TEXT.read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text
    assert "Version 3" in text
    assert len(text) > 30_000


def test_collector_covers_every_pinned_dependency(tmp_path):
    output = tmp_path / "licenses"
    run = subprocess.run(
        [sys.executable, str(COLLECTOR), "--output", str(output)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert run.returncode == 0, f"license collector failed:\n{run.stdout}\n{run.stderr}"

    index = (output / "INDEX.md").read_text(encoding="utf-8")
    assert "未提供" not in index, "a dependency shipped without a license text"
    assert "仍未取得许可文本" not in index

    lowered = index.lower()
    for name in _requirement_names():
        assert name.lower() in lowered, f"{name} is missing from the license inventory"


def test_agpl_component_carries_the_full_license(tmp_path):
    output = tmp_path / "licenses"
    run = subprocess.run(
        [sys.executable, str(COLLECTOR), "--output", str(output)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert run.returncode == 0, f"license collector failed:\n{run.stdout}\n{run.stderr}"
    pymupdf_dirs = [path for path in output.iterdir() if path.is_dir() and path.name.lower().startswith("pymupdf")]
    assert pymupdf_dirs, "PyMuPDF license directory was not generated"
    agpl_files = list(pymupdf_dirs[0].glob("AGPL-3.0.txt"))
    assert agpl_files, "AGPL-3.0 full text missing for PyMuPDF"
    assert agpl_files[0].stat().st_size > 30_000

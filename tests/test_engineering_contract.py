"""Engineering/tooling contract tests.

Covers the minimal engineering-hardening baseline that is not exercised by the
packaging contract tests:

- ``pyproject.toml`` carries the ruff / pytest / mypy configuration.
- the machine-bound baseline test is registered with the ``env_bound`` marker.
- ``core-tests.yml`` runs a pinned ruff lint job before the test matrix.
- the pinned ruff version is identical in ``requirements.test.txt`` and CI.
- ``ruff check .`` actually passes for the current working tree.

The tests are offline; the ruff invocation uses the repository virtualenv (or a
``ruff`` on PATH) and is skipped when ruff is not installed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
REQUIREMENTS_TEST_PATH = ROOT / "requirements.test.txt"
CORE_TESTS_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "core-tests.yml"
BATCH_VALIDATION_PATH = ROOT / "tests" / "test_batch_validation.py"
ENV_BOUND_TEST_NAME = "test_pinned_baseline_contract_uses_current_stable_hardware_fingerprint"

REQUIRED_RUFF_SELECT = {"E4", "E7", "E9", "F"}
REQUIRED_RUFF_EXCLUDES = {
    ".venv",
    "build",
    "tmp",
    "plugins/dsh-invoice-downloader/node_modules",
    "plugins/dsh-invoice-downloader/lib",
    "plugins/dsh-invoice-downloader/runtime",
    "tests/fixtures",
}
REQUIRED_PYTEST_MARKERS = {"env_bound", "slow", "network"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_pyproject() -> dict:
    assert PYPROJECT_PATH.is_file(), "pyproject.toml is missing"
    with PYPROJECT_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _load_workflow() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(_read(CORE_TESTS_WORKFLOW_PATH))


def _normalized_requirement_lines(path: Path) -> list[str]:
    lines = []
    for raw_line in _read(path).splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _pinned_ruff_version() -> str:
    matches = [
        match
        for line in _normalized_requirement_lines(REQUIREMENTS_TEST_PATH)
        for match in re.findall(r"^ruff==([0-9][0-9A-Za-z.\-]*)$", line)
    ]
    assert len(matches) == 1, (
        "requirements.test.txt must pin exactly one ruff version, found: "
        f"{matches}"
    )
    return matches[0]


def _workflow_step_text(job: dict) -> str:
    return json.dumps(job.get("steps", []), ensure_ascii=False)


def _job_needs(job: dict) -> list[str]:
    needs = job.get("needs") or []
    if isinstance(needs, str):
        return [needs]
    return list(needs)


def _ruff_executable() -> str | None:
    venv_names = ("Scripts/ruff.exe", "bin/ruff") if os.name == "nt" else ("bin/ruff", "Scripts/ruff.exe")
    for relative_name in venv_names:
        candidate = ROOT / ".venv" / relative_name
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ruff")


def test_pyproject_has_ruff_configuration():
    pyproject = _load_pyproject()
    ruff = pyproject["tool"]["ruff"]
    lint = ruff["lint"]

    assert ruff["target-version"] == "py312"
    assert ruff["line-length"] == 100
    # Rule selectors may be grouped ("E4") or expanded ("E401"); accept both.
    selected = set(lint["select"])
    for selector in REQUIRED_RUFF_SELECT:
        assert any(entry == selector or entry.startswith(selector) for entry in selected), (
            f"pyproject.toml ruff select does not cover {selector}"
        )

    excluded = {str(entry).replace("\\", "/") for entry in ruff["exclude"]}
    missing = REQUIRED_RUFF_EXCLUDES - excluded
    assert not missing, f"pyproject.toml ruff excludes are missing: {sorted(missing)}"


def test_pyproject_registers_pytest_markers_and_testpaths():
    pyproject = _load_pyproject()
    pytest_config = pyproject["tool"]["pytest"]["ini_options"]

    assert pytest_config["testpaths"] == ["tests"]
    markers = pytest_config["markers"]
    assert isinstance(markers, list)
    marker_names = {str(marker).split(":", 1)[0].strip() for marker in markers}
    missing = REQUIRED_PYTEST_MARKERS - marker_names
    assert not missing, f"pyproject.toml pytest markers are missing: {sorted(missing)}"
    for marker in REQUIRED_PYTEST_MARKERS:
        assert any(str(entry).startswith(f"{marker}:") for entry in markers), (
            f"pytest marker {marker!r} has no description in pyproject.toml"
        )


def test_pyproject_has_opt_in_mypy_configuration():
    pyproject = _load_pyproject()
    mypy = pyproject["tool"]["mypy"]

    assert mypy["python_version"] == "3.12"
    assert mypy["ignore_missing_imports"] is True
    assert mypy["check_untyped_defs"] is False


def test_machine_bound_baseline_test_is_marked_env_bound():
    source = _read(BATCH_VALIDATION_PATH)
    assert re.search(
        r"@pytest\.mark\.env_bound\s*\n\s*def " + re.escape(ENV_BOUND_TEST_NAME) + r"\s*\(",
        source,
    ), (
        f"{ENV_BOUND_TEST_NAME} must carry the @pytest.mark.env_bound marker "
        "so hosted runners can filter it (assertions must stay unchanged)"
    )


def test_core_tests_workflow_has_pinned_ruff_lint_job():
    workflow = _load_workflow()
    jobs = workflow["jobs"]
    expected_version = _pinned_ruff_version()

    assert "lint" in jobs, "core-tests.yml must define a lint job"
    lint_job = jobs["lint"]
    assert lint_job["runs-on"] == "ubuntu-latest"
    lint_text = _workflow_step_text(lint_job)
    pinned_versions = set(re.findall(r"ruff==([0-9][0-9A-Za-z.\-]*)", lint_text))
    assert pinned_versions == {expected_version}, (
        "core-tests.yml ruff pin must match requirements.test.txt: "
        f"workflow={sorted(pinned_versions)}, requirements={expected_version}"
    )
    assert "ruff check ." in lint_text

    # The test matrix.gate only runs after lint passes.
    assert "lint" in _job_needs(jobs["test"])
    assert jobs["test"]["strategy"]["matrix"]["os"] == ["windows-latest", "macos-15"]


def test_requirements_pin_ruff_and_keep_existing_test_pins():
    lines = _normalized_requirement_lines(REQUIREMENTS_TEST_PATH)
    expected = {
        "pytest==9.1.1",
        "tzdata==2026.4",
        "cryptography==46.0.5",
        f"ruff=={_pinned_ruff_version()}",
        "-r requirements.txt",
    }
    assert expected <= set(lines), f"requirements.test.txt is missing entries: {sorted(expected - set(lines))}"


def test_ruff_check_passes_on_current_working_tree():
    ruff = _ruff_executable()
    if ruff is None:
        pytest.skip("ruff is not installed; install it with: pip install -r requirements.test.txt")

    result = subprocess.run(
        [ruff, "check", "."],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert result.returncode == 0, (
        f"`ruff check .` failed with exit code {result.returncode}:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    excluded_top_level = {
        ".venv",
        "build",
        "tmp",
        "staging",
        "extracted_invoices",
        "release-assets",
        "release-bundle",
        "design",
        ".superpowers",
    }
    excluded_plugin_parts = {"node_modules", "lib", "runtime"}
    files_result = subprocess.run(
        [ruff, "check", "--show-files", "."],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert files_result.returncode == 0, files_result.stderr
    considered = [
        Path(line.strip())
        for line in files_result.stdout.splitlines()
        if line.strip().endswith(".py")
    ]
    assert considered, "ruff --show-files reported no Python files"
    for path in considered:
        relative = path.resolve()
        try:
            parts = relative.relative_to(ROOT.resolve()).parts
        except ValueError:
            parts = relative.parts
        assert parts[0] not in excluded_top_level, f"ruff considered an excluded tree: {relative}"
        if parts[0] == "plugins" and len(parts) >= 4 and parts[1] == "dsh-invoice-downloader":
            assert parts[2] not in excluded_plugin_parts, (
                f"ruff considered an excluded plugin tree: {relative}"
            )


def test_sys_version_matches_pyproject_target():
    pyproject = _load_pyproject()
    assert pyproject["tool"]["ruff"]["target-version"] == f"py{sys.version_info.major}{sys.version_info.minor}"

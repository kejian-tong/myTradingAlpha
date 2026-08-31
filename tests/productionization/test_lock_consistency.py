"""RED contract tests for the FND-04 lockfile and locked-CI boundary."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"
LOCK_PATH = REPOSITORY_ROOT / "uv.lock"
LOCK_CHECKER_PATH = REPOSITORY_ROOT / "scripts" / "check_lock_consistency.py"
CI_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
README_PATH = REPOSITORY_ROOT / "README.md"

SUPPORTED_PYTHON_VERSIONS = {"3.10", "3.11", "3.12", "3.13", "3.14"}
SETUP_UV_COMMIT = "20cfd1bf945f4377ade1205e4dbc17946fc9a30d"
UV_VERSION = "0.12.7"


def _require_file(path: Path, contract: str) -> Path:
    if not path.is_file():
        pytest.fail(f"FND-04 contract is not implemented: missing {contract} at {path}")
    return path


def _run_lock_checker(root: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    _require_file(LOCK_CHECKER_PATH, "lock consistency checker")
    return subprocess.run(
        [sys.executable, str(LOCK_CHECKER_PATH), str(root)],
        cwd=REPOSITORY_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def _project_dependency_names() -> set[str]:
    project_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    project_match = re.search(
        r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)",
        project_text,
    )
    assert project_match is not None, "pyproject.toml must declare [project]"
    dependencies_match = re.search(
        r"(?ms)^dependencies\s*=\s*\[(.*?)^\s*\]",
        project_match.group(1),
    )
    assert dependencies_match is not None, "[project].dependencies must remain declared"

    names: set[str] = set()
    for requirement in re.findall(r'^\s*"([^"]+)"', dependencies_match.group(1), re.MULTILINE):
        name = re.split(r"[<>=!~;\[\s]", requirement, maxsplit=1)[0]
        names.add(re.sub(r"[-_.]+", "-", name.lower()))
    return names


def _lock_package_names(lock_text: str) -> set[str]:
    return {
        re.sub(r"[-_.]+", "-", name.lower())
        for name in re.findall(r'^name\s*=\s*"([^"]+)"\s*$', lock_text, re.MULTILINE)
    }


def _fake_uv(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Return an environment with a network-free uv stub that records argv."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_path = tmp_path / "uv-args.json"
    uv_path = bin_dir / "uv"
    uv_path.write_text(
        "#!" + sys.executable + "\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['FAKE_UV_ARGS']).write_text(\n"
        "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
        ")\n",
        encoding="utf-8",
    )
    uv_path.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["FAKE_UV_ARGS"] = str(args_path)
    return env, args_path


def _copy_lock_project(tmp_path: Path) -> Path:
    """Create a tracked, isolated lock project for static mismatch diagnostics."""

    _require_file(LOCK_PATH, "uv.lock")
    root = tmp_path / "lock-project"
    root.mkdir()
    shutil.copy2(PYPROJECT_PATH, root / "pyproject.toml")
    shutil.copy2(LOCK_PATH, root / "uv.lock")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "pyproject.toml", "uv.lock"], check=True)
    return root


def test_current_lockfile_is_tracked_and_matches_project_dependencies() -> None:
    lock_path = _require_file(LOCK_PATH, "uv.lock")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "uv.lock"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, tracked.stdout + tracked.stderr

    lock_text = lock_path.read_text(encoding="utf-8")
    assert re.search(r'^version\s*=\s*\d+\s*$', lock_text, re.MULTILINE)
    assert re.search(r'^revision\s*=\s*\d+\s*$', lock_text, re.MULTILINE)
    assert re.search(r'^requires-python\s*=\s*">=3\.10"\s*$', lock_text, re.MULTILINE)
    package_names = _lock_package_names(lock_text)
    assert "tradingagents" in package_names
    assert _project_dependency_names() <= package_names
    assert re.search(r'^source\s*=\s*\{\s*editable\s*=\s*"\."\s*\}', lock_text, re.MULTILINE)


def test_project_keeps_python_floor_and_pins_the_uv_tool_version() -> None:
    project_text = PYPROJECT_PATH.read_text(encoding="utf-8")

    assert re.search(r'^requires-python\s*=\s*">=3\.10"\s*$', project_text, re.MULTILINE)
    uv_section = re.search(r"(?ms)^\[tool\.uv\]\s*(.*?)(?=^\[|\Z)", project_text)
    assert uv_section is not None, "pyproject.toml must pin the project uv version"
    assert re.search(
        rf'^required-version\s*=\s*"=={re.escape(UV_VERSION)}"\s*$',
        uv_section.group(1),
        re.MULTILINE,
    )


def test_ci_uses_the_locked_uv_matrix_and_current_foundation_gate() -> None:
    ci_text = CI_PATH.read_text(encoding="utf-8")
    matrix_match = re.search(r"(?ms)^\s*python-version:\s*\[(.*?)\]", ci_text)
    matrix_versions = set(
        re.findall(r'["\'](3\.\d+)["\']', matrix_match.group(1))
        if matrix_match is not None
        else ()
    )
    matrix_versions.update(re.findall(r'python-version:\s*["\'](3\.\d+)["\']', ci_text))

    assert matrix_versions >= SUPPORTED_PYTHON_VERSIONS
    assert f"astral-sh/setup-uv@{SETUP_UV_COMMIT}" in ci_text
    assert re.search(rf"version:\s*[\"']?{re.escape(UV_VERSION)}[\"']?", ci_text)
    assert "uv sync --locked" in ci_text
    assert re.search(
        r"(?im)^\s*name:\s*.*foundation.*(?:contract|docs|lock).*\s*$",
        ci_text,
    )

    # FND-04 owns only the current foundation contract/docs/lock gate. Future
    # PIT, signal, backtest, portfolio/risk, execution, experiment, OMS,
    # paper, and live gates belong to later roadmap slices.
    future_gate_terms = (
        "point-in-time",
        "backtest",
        "portfolio",
        "risk engine",
        "oms",
        "paper broker",
        "live broker",
    )
    lowered = ci_text.lower()
    assert not [term for term in future_gate_terms if term in lowered]


def test_ci_binds_uv_to_each_intended_interpreter_without_split_ownership() -> None:
    workflow = yaml.safe_load(CI_PATH.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    expected_python = {
        "test": "${{ matrix.python-version }}",
        "smoke-install": "3.14",
        "lint": "3.14",
        "foundation-contract-docs-lock": "3.14",
    }

    assert set(expected_python) <= set(jobs)
    for job_name, python_version in expected_python.items():
        steps = jobs[job_name]["steps"]
        uv_steps = [
            step
            for step in steps
            if step.get("uses", "").startswith(f"astral-sh/setup-uv@{SETUP_UV_COMMIT}")
        ]
        assert len(uv_steps) == 1, job_name
        assert uv_steps[0]["with"]["version"] == UV_VERSION
        assert uv_steps[0]["with"]["python-version"] == python_version

    assert not any(
        step.get("uses", "").startswith("actions/setup-python@")
        for job in jobs.values()
        for step in job.get("steps", [])
    )


def test_readme_prefers_locked_uv_and_keeps_a_pip_fallback() -> None:
    readme_text = README_PATH.read_text(encoding="utf-8").lower()

    assert "uv sync --locked" in readme_text
    assert "uv.lock" in readme_text
    assert "pip" in readme_text
    assert "fallback" in readme_text or "rollback" in readme_text
    assert "python" in readme_text and ">=3.10" in readme_text
    assert "tradingagents" in readme_text
    assert "python -m cli.main" in readme_text


def test_notice_is_optional_but_required_to_be_a_nonempty_tracked_record() -> None:
    notice_path = REPOSITORY_ROOT / "NOTICE"
    if not notice_path.exists():
        return

    assert notice_path.is_file()
    assert notice_path.read_text(encoding="utf-8").strip()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "NOTICE"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, tracked.stdout + tracked.stderr


def test_lock_checker_runs_immutable_uv_check_without_rewriting_lock(tmp_path: Path) -> None:
    lock_path = _require_file(LOCK_PATH, "uv.lock")
    before = lock_path.read_bytes()
    env, args_path = _fake_uv(tmp_path)

    result = _run_lock_checker(REPOSITORY_ROOT, env=env)

    assert result.returncode == 0, _combined_output(result)
    assert json.loads(args_path.read_text(encoding="utf-8")) == ["lock", "--check"]
    assert lock_path.read_bytes() == before


def test_lock_checker_reports_a_missing_lockfile(tmp_path: Path) -> None:
    root = tmp_path / "missing-lock"
    root.mkdir()
    shutil.copy2(PYPROJECT_PATH, root / "pyproject.toml")
    env, _ = _fake_uv(tmp_path)

    result = _run_lock_checker(root, env=env)

    assert result.returncode != 0
    assert "uv.lock" in _combined_output(result)


def test_lock_checker_reports_requires_python_drift_without_mutating_lock(tmp_path: Path) -> None:
    root = _copy_lock_project(tmp_path)
    lock_path = root / "uv.lock"
    lock_text = lock_path.read_text(encoding="utf-8")
    drifted, replacements = re.subn(
        r'^requires-python\s*=\s*">=3\.10"\s*$',
        'requires-python = ">=3.11"',
        lock_text,
        count=1,
        flags=re.MULTILINE,
    )
    assert replacements == 1, "the generated lock must carry the project Python floor"
    lock_path.write_text(drifted, encoding="utf-8")
    drifted_bytes = lock_path.read_bytes()
    env, _ = _fake_uv(tmp_path)

    result = _run_lock_checker(root, env=env)

    assert result.returncode != 0
    assert re.search(r"(?i)(requires-python|mismatch|drift)", _combined_output(result))
    assert lock_path.read_bytes() == drifted_bytes

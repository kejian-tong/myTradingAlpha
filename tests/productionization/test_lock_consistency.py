"""RED contract tests for the FND-04 lockfile and locked-CI boundary."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from packaging.version import InvalidVersion, Version

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"
LOCK_PATH = REPOSITORY_ROOT / "uv.lock"
LOCK_CHECKER_PATH = REPOSITORY_ROOT / "scripts" / "check_lock_consistency.py"
CI_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
README_PATH = REPOSITORY_ROOT / "README.md"

CI_PYTHON_VERSIONS = {"3.14"}
SETUP_UV_COMMIT = "07a047e608db84b3d8c06cd9a7c7dcc9c355c18e"
UV_VERSION = "0.13.5"
UPLOAD_ARTIFACT_COMMIT = "ea165f8d65b6e75b540449e92b4886f43607fa02"
DOWNLOAD_ARTIFACT_COMMIT = "d3f86a106a0bac45b974a628896c90dbdf5c8093"
PARTITION_SCRIPT = "scripts/ci_partition.py"
PARTITION_SHARDS = ("test-shard-0", "test-shard-1")
PINNED_TEST_RUNNER_JOBS = {
    "test-shard-0",
    "test-shard-1",
    "test",
    "serial-baseline",
}


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


def _project_dependency_specs() -> dict[str, str]:
    project_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    project_match = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", project_text)
    assert project_match is not None, "pyproject.toml must declare [project]"
    dependencies_match = re.search(
        r"(?ms)^dependencies\s*=\s*\[(.*?)^\s*\]",
        project_match.group(1),
    )
    assert dependencies_match is not None, "[project].dependencies must remain declared"
    requirements = re.findall(r'^\s*"([^"\n]+)"', dependencies_match.group(1), re.MULTILINE)
    specs = {}
    for requirement in requirements:
        name = re.split(r"[<>=!~;\[\s]", requirement, maxsplit=1)[0]
        normalized_name = re.sub(r"[-_.]+", "-", name.lower())
        specs[normalized_name] = requirement[len(name) :]
    return specs


def _lock_package_names(lock_text: str) -> set[str]:
    return {
        re.sub(r"[-_.]+", "-", name.lower())
        for name in re.findall(r'^name\s*=\s*"([^"]+)"\s*$', lock_text, re.MULTILINE)
    }


def _lock_package_versions(lock_text: str) -> dict[str, set[str]]:
    versions = {}
    blocks = re.split(r"(?m)^\[\[package\]\]\s*$", lock_text)
    for block in blocks[1:]:
        name = re.search(r'(?m)^name\s*=\s*"([^"]+)"\s*$', block)
        version = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', block)
        if name is not None and version is not None:
            normalized_name = re.sub(r"[-_.]+", "-", name.group(1).lower())
            versions.setdefault(normalized_name, set()).add(version.group(1))
    return versions


def _meets_version_floor(actual: str, minimum: str) -> bool:
    try:
        return Version(actual) >= Version(minimum)
    except InvalidVersion:
        return False


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


def test_active_lock_meets_all_reviewed_security_minimums() -> None:
    lock_text = _require_file(LOCK_PATH, "uv.lock").read_text(encoding="utf-8")
    versions = _lock_package_versions(lock_text)
    minimums = {
        "aiohttp": "3.14.4",
        "certifi": "2026.10.18",
        "langgraph": "1.2.14",
        "langgraph-sdk": "0.4.6",
        "langgraph-checkpoint": "4.3.0",
        "langgraph-checkpoint-sqlite": "3.1.2",
        "multidict": "6.9.1",
        "setuptools": "84.1.0",
        "yarl": "1.25.1",
    }

    for package, minimum in minimums.items():
        assert package in versions, f"uv.lock omits required package {package}"
        assert all(_meets_version_floor(version, minimum) for version in versions[package]), (
            f"uv.lock pins {package} {sorted(versions[package])}, below reviewed minimum {minimum}"
        )


def test_locked_floor_rejects_a_vulnerable_alternate_variant_hidden_by_a_patched_version() -> None:
    lock_text = '''
[[package]]
name = "multidict"
version = "6.8.0"

[[package]]
name = "multidict"
version = "7.2.1"
'''

    versions = _lock_package_versions(lock_text)

    assert versions["multidict"] == {"6.8.0", "7.2.1"}
    assert not all(_meets_version_floor(version, "6.9.1") for version in versions["multidict"])


def test_locked_floor_comparison_rejects_prereleases_and_malformed_versions() -> None:
    assert not _meets_version_floor("3.14.4rc1", "3.14.4")
    assert not _meets_version_floor("not-a-version", "3.14.4")
    assert _meets_version_floor("3.14.4.post1", "3.14.4")


def test_locked_floor_comparison_accepts_a_newer_safe_patch_version() -> None:
    assert _meets_version_floor("3.14.5", "3.14.4")


def test_project_and_pip_fallback_declare_reviewed_security_minimums() -> None:
    specs = _project_dependency_specs()
    minimums = {
        "aiohttp": ">=3.14.4,<4",
        "certifi": ">=2026.10.18",
        "langgraph": ">=1.2.14,<2",
        "langgraph-checkpoint-sqlite": ">=3.1.2",
        "multidict": ">=6.9.1,<7",
        "setuptools": ">=84.1.0",
    }

    for package, minimum in minimums.items():
        assert specs.get(package) == minimum, (
            f"pip fallback must constrain {package} to the reviewed minimum {minimum}"
        )


def test_source_build_uses_reviewed_setuptools_security_minimum() -> None:
    project_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    build_match = re.search(r"(?ms)^\[build-system\]\s*(.*?)(?=^\[|\Z)", project_text)
    assert build_match is not None, "pyproject.toml must declare [build-system]"
    build_requirements_match = re.search(
        r"(?ms)^requires\s*=\s*\[(.*?)\]",
        build_match.group(1),
    )
    assert build_requirements_match is not None, "build backend requirements must remain explicit"
    build_requirements = re.findall(r"[\"']([^\"']+)[\"']", build_requirements_match.group(1))
    setuptools_requirements = [
        requirement
        for requirement in build_requirements
        if re.match(r"(?i)^setuptools(?=$|[<>=!~;\[\s])", requirement)
    ]
    assert len(setuptools_requirements) == 1, "source build must constrain setuptools exactly once"
    setuptools_floor = re.search(
        r"(?:^|,)\s*>=\s*([^,;\s]+)",
        setuptools_requirements[0][len("setuptools") :],
    )
    assert setuptools_floor is not None, "source build setuptools lower bound is missing"
    assert _meets_version_floor(setuptools_floor.group(1), "84.1.0"), (
        "source builds must use the reviewed setuptools security minimum"
    )


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

    assert matrix_versions == CI_PYTHON_VERSIONS
    _assert_active_ci_policy(yaml.safe_load(ci_text))
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
        "test-shard-0": "3.14",
        "test-shard-1": "3.14",
        "test": "3.14",
        "smoke-install": "3.14",
        "lint": "3.14",
        "serial-baseline": "3.14",
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


def _required_ci_runs() -> dict[str, dict[str, str]]:
    shard_commands = {
        "Install locked environment (with dev extras)": "uv sync --locked --extra dev",
        "Collect full test suite": (
            f"uv run --no-sync python {PARTITION_SCRIPT} collect --output collection.json"
        ),
    }
    runs = {
        "test-shard-0": {
            **shard_commands,
            "Run assigned test partition": (
                f"uv run --no-sync python {PARTITION_SCRIPT} run --shard 0 --output shard-0.json"
            ),
        },
        "test-shard-1": {
            **shard_commands,
            "Run assigned test partition": (
                f"uv run --no-sync python {PARTITION_SCRIPT} run --shard 1 --output shard-1.json"
            ),
        },
        "test": {
            "Install locked environment (with dev extras)": "uv sync --locked --extra dev",
            "Prepare coverage artifact": "mkdir -p ci-coverage",
            "Collect independent coverage reference": (
                f"uv run --no-sync python {PARTITION_SCRIPT} collect --output ci-coverage/reference.json"
            ),
            "Verify complete shard coverage": (
                f"uv run --no-sync python {PARTITION_SCRIPT} verify --reference ci-coverage/reference.json --receipts ci-shard-receipts > ci-coverage/summary.json"
            ),
        },
        "foundation-contract-docs-lock": {},
        "smoke-install": {
            "Fresh locked install (no dev extras) and import": "uv sync --locked --no-dev --no-editable",
            "Import installed packages": (
                'PYTHON="$GITHUB_WORKSPACE/.venv/bin/python"\n'
                'cd "$(mktemp -d)"\n'
                '"$PYTHON" -I "$GITHUB_WORKSPACE/scripts/smoke_installed.py"'
            ),
        },
        "lint": {
            "Install locked development environment": "uv sync --locked --extra dev",
            "Lint the repository": "uv run --no-sync ruff check .",
            "Check diff integrity against event base": (
                'if [[ "${{ github.event_name }}" == "pull_request" ]]; then\n'
                '  BASE_SHA="${{ github.event.pull_request.base.sha }}"\n'
                'else\n  BASE_SHA="${{ github.event.before }}"\nfi\n'
                'git cat-file -e "${BASE_SHA}^{commit}"\n'
                'git diff --check "$BASE_SHA" HEAD'
            ),
            "Run network-deny canary": (
                'uv run --no-sync pytest -q -m "not integration" '
                'tests/productionization/test_validation_boundaries.py -k network_denial_canary'
            ),
            "Check agent harness": "uv run --no-sync python scripts/check_agent_harness.py",
            "Check dependency direction": "uv run --no-sync python scripts/check_dependency_direction.py",
            "Check lock consistency": "uv run --no-sync python scripts/check_lock_consistency.py",
            "Check Markdown contracts": "uv run --no-sync python scripts/check_markdown_contracts.py",
        },
    }
    runs["serial-baseline"] = {
        "Install locked environment (with dev extras)": "uv sync --locked --extra dev",
        "Run serial reference suite": (
            f"uv run --no-sync python {PARTITION_SCRIPT} run --shard serial --output serial.json"
        ),
    }
    return runs


def _upload_artifact_step(job: dict, name: str) -> dict:
    steps = job.get("steps")
    assert type(steps) is list
    uploaders = [
        step
        for step in steps
        if type(step) is dict and step.get("uses") == f"actions/upload-artifact@{UPLOAD_ARTIFACT_COMMIT}"
    ]
    assert len(uploaders) == 1
    uploader = uploaders[0]
    options = uploader.get("with")
    assert type(options) is dict
    assert options.get("name") == name
    assert type(options.get("path")) is str and options["path"]
    assert options.get("if-no-files-found") == "error"
    assert type(options.get("retention-days")) is int
    assert 1 <= options["retention-days"] <= 7
    return uploader


def _assert_active_ci_policy(workflow: dict) -> None:
    jobs = workflow.get("jobs")
    required = {
        *PARTITION_SHARDS,
        "test",
        "foundation-contract-docs-lock",
        "smoke-install",
        "lint",
        "serial-baseline",
    }
    assert type(jobs) is dict and set(jobs) == required
    assert jobs["test"]["name"] == "tests (py3.14)"
    assert jobs["test"].get("needs") == list(PARTITION_SHARDS)
    assert jobs["test"].get("if") == "${{ always() }}"
    assert jobs["foundation-contract-docs-lock"].get("needs") == [
        "test",
        "lint",
        "smoke-install",
    ]

    expected_artifact = {
        "test-shard-0": "ci-shard-receipt-0",
        "test-shard-1": "ci-shard-receipt-1",
        "test": "ci-coverage",
        "serial-baseline": "ci-serial-reference",
    }
    required_runs = _required_ci_runs()
    assert {
        job_name for job_name in required_runs if jobs[job_name].get("runs-on") == "ubuntu-24.04"
    } == PINNED_TEST_RUNNER_JOBS
    for job_name, commands in required_runs.items():
        job = jobs.get(job_name)
        assert type(job) is dict
        expected_runner = "ubuntu-24.04" if job_name in PINNED_TEST_RUNNER_JOBS else "ubuntu-latest"
        assert job.get("runs-on") == expected_runner
        if job_name == "foundation-contract-docs-lock":
            assert type(job.get("if")) is str
            assert job["if"] == "${{ always() }}"
        elif job_name == "test":
            assert job.get("if") == "${{ always() }}"
        elif job_name == "serial-baseline":
            assert job.get("if") == (
                "${{ github.event_name == 'pull_request' && "
                "contains(github.event.pull_request.labels.*.name, 'ci-partition-benchmark') }}"
            )
            assert "test" not in job.get("needs", [])
        else:
            assert job.get("if", True) is True
        assert job.get("continue-on-error", False) is False
        steps = job.get("steps")
        assert type(steps) is list and all(type(step) is dict for step in steps)
        for step in steps:
            assert step.get("continue-on-error", False) is False
            assert step.get("if", True) is True
        uv_steps = [
            step
            for step in steps
            if step.get("uses") == f"astral-sh/setup-uv@{SETUP_UV_COMMIT}"
        ]
        if job_name == "foundation-contract-docs-lock":
            assert job["name"] == "Foundation contract/docs/lock"
            assert job.get("timeout-minutes") == 5
            assert len(steps) == 1
            assert steps[0].get("name") == "Verify Foundation dependency results"
            assert steps[0].get("shell") == "bash"
            assert not uv_steps
        else:
            assert len(uv_steps) == 1
            assert uv_steps[0]["with"]["version"] == UV_VERSION
            assert uv_steps[0]["with"]["python-version"] == "3.14"
        assert "strategy" not in job
        for name, command in commands.items():
            matches = [step for step in steps if step.get("name") == name]
            assert len(matches) == 1
            assert matches[0].get("run", "").strip() == command
        if job_name in expected_artifact:
            _upload_artifact_step(job, expected_artifact[job_name])

    for job_name in PARTITION_SHARDS:
        job = jobs[job_name]
        assert job.get("needs", []) == []
        names = [step.get("name") for step in job["steps"]]
        assert names.index("Collect full test suite") < names.index("Run assigned test partition")
        assert names.index("Run assigned test partition") < names.index("Upload shard receipt")
    aggregate_steps = jobs["test"]["steps"]
    downloaders = [
        step
        for step in aggregate_steps
        if step.get("uses") == f"actions/download-artifact@{DOWNLOAD_ARTIFACT_COMMIT}"
    ]
    assert len(downloaders) == 1
    download_options = downloaders[0].get("with")
    assert type(download_options) is dict
    assert download_options.get("pattern") == "ci-shard-receipt-*"
    assert download_options.get("merge-multiple") is True
    assert type(download_options.get("path")) is str
    aggregate_names = [step.get("name") for step in aggregate_steps]
    assert aggregate_names.index("Download shard receipts") < aggregate_names.index(
        "Verify complete shard coverage"
    )
    assert aggregate_names.index("Collect independent coverage reference") < aggregate_names.index(
        "Verify complete shard coverage"
    )
    assert aggregate_names.index("Verify complete shard coverage") < aggregate_names.index(
        "Upload coverage evidence"
    )


def _valid_ci_policy_fixture() -> dict:
    """Build one valid fixed-topology policy fixture for mutation tests.

    The checked-in workflow intentionally remains pre-partition during RED, so
    mutation tests must not use it as their positive baseline. This synthetic
    fixture lets each mutation demonstrate that the policy rejects that
    specific violation rather than merely rejecting the preexisting workflow.
    """
    jobs = {}
    for job_name, commands in _required_ci_runs().items():
        if job_name == "foundation-contract-docs-lock":
            jobs[job_name] = {
                "name": "Foundation contract/docs/lock",
                "runs-on": "ubuntu-latest",
                "needs": ["test", "lint", "smoke-install"],
                "if": "${{ always() }}",
                "timeout-minutes": 5,
                "steps": [
                    {
                        "name": "Verify Foundation dependency results",
                        "shell": "bash",
                        "run": "true",
                    }
                ],
            }
            continue

        steps = [
            {
                "name": "Set up uv",
                "uses": f"astral-sh/setup-uv@{SETUP_UV_COMMIT}",
                "with": {"version": UV_VERSION, "python-version": "3.14"},
            }
        ]
        for name, command in commands.items():
            if name == "Verify complete shard coverage":
                steps.append(
                    {
                        "name": "Download shard receipts",
                        "uses": f"actions/download-artifact@{DOWNLOAD_ARTIFACT_COMMIT}",
                        "with": {
                            "pattern": "ci-shard-receipt-*",
                            "merge-multiple": True,
                            "path": "ci-shard-receipts",
                        },
                    }
                )
            steps.append({"name": name, "run": command})

        artifact_name = {
            "test-shard-0": "ci-shard-receipt-0",
            "test-shard-1": "ci-shard-receipt-1",
            "test": "ci-coverage",
            "serial-baseline": "ci-serial-reference",
        }.get(job_name)
        if artifact_name is not None:
            steps.append(
                {
                    "name": {
                        "test-shard-0": "Upload shard receipt",
                        "test-shard-1": "Upload shard receipt",
                        "test": "Upload coverage evidence",
                        "serial-baseline": "Upload serial reference",
                    }[job_name],
                    "uses": f"actions/upload-artifact@{UPLOAD_ARTIFACT_COMMIT}",
                    "with": {
                        "name": artifact_name,
                        "path": {
                            "test-shard-0": "shard-0.json",
                            "test-shard-1": "shard-1.json",
                            "test": "ci-coverage",
                            "serial-baseline": "serial.json",
                        }[job_name],
                        "if-no-files-found": "error",
                        "retention-days": 3,
                    },
                }
            )

        runner = "ubuntu-24.04" if job_name in PINNED_TEST_RUNNER_JOBS else "ubuntu-latest"
        job = {"runs-on": runner, "steps": steps}
        if job_name == "test-shard-0":
            job.update({"name": "test-shard-0", "needs": []})
        elif job_name == "test-shard-1":
            job.update({"name": "test-shard-1", "needs": []})
        elif job_name == "test":
            job.update(
                {
                    "name": "tests (py3.14)",
                    "needs": list(PARTITION_SHARDS),
                    "if": "${{ always() }}",
                }
            )
        elif job_name == "serial-baseline":
            job.update(
                {
                    "name": "serial baseline (py3.14)",
                    "if": (
                        "${{ github.event_name == 'pull_request' && "
                        "contains(github.event.pull_request.labels.*.name, 'ci-partition-benchmark') }}"
                    ),
                }
            )
        else:
            job["name"] = job_name
        jobs[job_name] = job
    return {"jobs": jobs}


def _active_ci_fixture() -> dict:
    return yaml.safe_load(CI_PATH.read_text(encoding="utf-8"))


def test_active_ci_runtime_fixture_preserves_all_locked_full_and_security_gates() -> None:
    _assert_active_ci_policy(_active_ci_fixture())


def test_active_ci_policy_pins_exactly_the_four_test_jobs_to_ubuntu_24_04() -> None:
    template = _valid_ci_policy_fixture()
    _assert_active_ci_policy(template)

    for job_name in PINNED_TEST_RUNNER_JOBS:
        candidate = copy.deepcopy(template)
        candidate["jobs"][job_name]["runs-on"] = "ubuntu-latest"
        with pytest.raises(AssertionError):
            _assert_active_ci_policy(candidate)

    for job_name in set(template["jobs"]) - PINNED_TEST_RUNNER_JOBS:
        candidate = copy.deepcopy(template)
        candidate["jobs"][job_name]["runs-on"] = "ubuntu-24.04"
        with pytest.raises(AssertionError):
            _assert_active_ci_policy(candidate)


def test_active_ci_policy_rejects_retired_ambiguous_or_hidden_matrix_expansion() -> None:
    template = _valid_ci_policy_fixture()
    _assert_active_ci_policy(template)
    for job_name in template["jobs"]:
        candidate = copy.deepcopy(template)
        candidate["jobs"][job_name]["strategy"] = {
            "matrix": {"python-version": ["3.14"], "os": ["ubuntu-latest"]}
        }
        with pytest.raises(AssertionError):
            _assert_active_ci_policy(candidate)
    for extra_job in ("test-shard-2", "test-python-3.13", "extra-required-gate"):
        candidate = copy.deepcopy(template)
        candidate["jobs"][extra_job] = copy.deepcopy(candidate["jobs"]["test-shard-0"])
        with pytest.raises(AssertionError):
            _assert_active_ci_policy(candidate)
    candidate = copy.deepcopy(template)
    candidate["jobs"]["test"]["needs"] = ["test-shard-0", "test-shard-1", "serial-baseline"]
    with pytest.raises(AssertionError):
        _assert_active_ci_policy(candidate)


def test_active_ci_policy_rejects_removed_filtered_or_disabled_required_work() -> None:
    template = _valid_ci_policy_fixture()
    _assert_active_ci_policy(template)
    for job_name, commands in _required_ci_runs().items():
        candidate = copy.deepcopy(template)
        candidate["jobs"].pop(job_name)
        with pytest.raises(AssertionError):
            _assert_active_ci_policy(candidate)
        if job_name != "serial-baseline":
            for flag, value in (
                ("if", False),
                ("if", "${{ false }}"),
                ("if", 1),
                ("continue-on-error", True),
            ):
                candidate = copy.deepcopy(template)
                candidate["jobs"][job_name][flag] = value
                with pytest.raises(AssertionError):
                    _assert_active_ci_policy(candidate)
        for name in commands:
            candidate = copy.deepcopy(template)
            steps = candidate["jobs"][job_name]["steps"]
            index = next(index for index, step in enumerate(steps) if step.get("name") == name)
            for alteration in ("remove", "filter", "if", "continue-on-error"):
                broken = copy.deepcopy(candidate)
                target = broken["jobs"][job_name]["steps"]
                if alteration == "remove":
                    target.pop(index)
                elif alteration == "filter":
                    target[index]["run"] += " -- -k narrowed_selection"
                else:
                    target[index][alteration] = alteration == "continue-on-error"
                with pytest.raises(AssertionError):
                    _assert_active_ci_policy(broken)

    for value in (False, "${{ false }}", "always()"):
        candidate = copy.deepcopy(template)
        candidate["jobs"]["serial-baseline"]["if"] = value
        with pytest.raises(AssertionError):
            _assert_active_ci_policy(candidate)

from __future__ import annotations

import base64
import copy
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_PATH = ROOT / ".github/workflows/ci.yml"
PYPROJECT_PATH = ROOT / "pyproject.toml"
VALIDATION_POLICY_PATH = ROOT / "docs/productionization/VALIDATION_EFFICIENCY.md"
FOUNDATION_JOB_ID = "foundation-contract-docs-lock"
FOUNDATION_JOB_NAME = "Foundation contract/docs/lock"
FOUNDATION_STEP_NAME = "Verify Foundation dependency results"
FOUNDATION_JOB_KEYS = {"name", "runs-on", "needs", "if", "timeout-minutes", "steps"}
FOUNDATION_ENV = {
    "TEST_RESULT": "${{ needs.test.result }}",
    "LINT_RESULT": "${{ needs.lint.result }}",
    "SMOKE_RESULT": "${{ needs['smoke-install'].result }}",
}
FOUNDATION_RUN = """set -euo pipefail
if [[ "${TEST_RESULT:-}" != "success" || "${LINT_RESULT:-}" != "success" || "${SMOKE_RESULT:-}" != "success" ]]; then
  printf '%s\\n' 'Foundation dependency coverage did not complete successfully.' >&2
  exit 1
fi
printf '%s\\n' 'Foundation dependency coverage is satisfied by test, lint, and smoke-install.'"""
FULL_TEST_COMMAND = "uv run --no-sync pytest -q"


def _workflow() -> dict:
    return yaml.safe_load(CI_PATH.read_text(encoding="utf-8"))


def _assert_foundation_contract(workflow: dict) -> dict:
    jobs = workflow.get("jobs")
    assert type(jobs) is dict
    job = jobs.get(FOUNDATION_JOB_ID)
    assert type(job) is dict, "Foundation dependency aggregation job is missing"
    assert job.get("name") == FOUNDATION_JOB_NAME

    steps = job.get("steps")
    assert type(steps) is list
    matches = [step for step in steps if type(step) is dict and step.get("name") == FOUNDATION_STEP_NAME]
    assert len(matches) == 1, "named Foundation dependency result step is missing or duplicated"
    step = matches[0]

    assert set(job) == FOUNDATION_JOB_KEYS
    assert job.get("runs-on") == "ubuntu-latest"
    assert job.get("needs") == ["test", "lint", "smoke-install"]
    assert job.get("if") == "${{ always() }}"
    assert job.get("timeout-minutes") == 5
    assert len(steps) == 1
    assert type(step) is dict
    assert step.get("name") == FOUNDATION_STEP_NAME
    assert step.get("shell") == "bash"
    assert set(step) == {"name", "shell", "env", "run"}
    assert step.get("env") == FOUNDATION_ENV
    run = step.get("run")
    assert type(run) is str and run.strip() == FOUNDATION_RUN
    return step


def _assert_no_pytest_selector_env(workflow: dict) -> None:
    jobs = workflow.get("jobs")
    assert type(jobs) is dict
    scopes = [workflow]
    for job in jobs.values():
        assert type(job) is dict
        scopes.append(job)
        steps = job.get("steps", [])
        assert type(steps) is list
        scopes.extend(step for step in steps if type(step) is dict)

    for scope in scopes:
        environment = scope.get("env")
        assert environment is None or type(environment) is dict
        if type(environment) is dict:
            assert all(type(key) is str for key in environment)
            assert not [key for key in environment if key.upper().startswith("PYTEST_")]


def _valid_workflow() -> dict:
    return {
        "jobs": {
            FOUNDATION_JOB_ID: {
                "name": FOUNDATION_JOB_NAME,
                "runs-on": "ubuntu-latest",
                "needs": ["test", "lint", "smoke-install"],
                "if": "${{ always() }}",
                "timeout-minutes": 5,
                "steps": [
                    {
                        "name": FOUNDATION_STEP_NAME,
                        "shell": "bash",
                        "env": dict(FOUNDATION_ENV),
                        "run": FOUNDATION_RUN,
                    }
                ],
            }
        }
    }


def _run_shell(script: str, results: dict[str, str]) -> subprocess.CompletedProcess[str]:
    environment = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", **results}
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_foundation_gate_executes_only_after_locating_the_new_metadata_step() -> None:
    step = _assert_foundation_contract(_workflow())
    result = _run_shell(
        step["run"],
        {"TEST_RESULT": "success", "LINT_RESULT": "success", "SMOKE_RESULT": "success"},
    )

    assert result.returncode == 0, "Foundation gate rejected three successful dependencies"
    if result.stdout != "Foundation dependency coverage is satisfied by test, lint, and smoke-install.\n":
        pytest.fail("Foundation gate emitted an unexpected success diagnostic")
    if result.stderr:
        pytest.fail("Foundation gate emitted an unexpected success error")


def test_foundation_gate_rejects_non_success_results_without_leaking_values() -> None:
    step = _assert_foundation_contract(_workflow())
    raw_sentinel = "HARNESS/EFF03+REDACTION=CANARY"
    encoded_sentinels = (
        base64.b64encode(raw_sentinel.encode("ascii")).decode("ascii"),
        quote(raw_sentinel, safe=""),
    )
    assert raw_sentinel not in encoded_sentinels
    invalid_results = (
        ("failure", "failure"),
        ("cancelled", "cancelled"),
        ("skipped", "skipped"),
        ("unknown", "unknown"),
        ("empty", ""),
        ("uppercase", "SUCCESS"),
        ("leading whitespace", " success"),
        ("trailing whitespace", "success "),
        ("whitespace-only", " \t "),
        ("newline prefix", "\nsuccess"),
        ("newline suffix", "success\n"),
        ("lookalike", "successx"),
        ("Unicode lookalike", "ѕuccess"),
        ("escaped success", r"\x73uccess"),
        ("raw payload", f"{raw_sentinel} $(printf inert)"),
        ("base64 payload", f"{encoded_sentinels[0]} $(printf inert)"),
        ("URL-encoded payload", f"{encoded_sentinels[1]} $(printf inert)"),
        ("shell metacharacters", f"success; {raw_sentinel}"),
    )
    fixed_diagnostic = "Foundation dependency coverage did not complete successfully.\n"

    for result_name, invalid in invalid_results:
        for position in FOUNDATION_ENV:
            results = dict.fromkeys(FOUNDATION_ENV, "success")
            results[position] = invalid
            result = _run_shell(step["run"], results)

            if result.returncode == 0:
                pytest.fail(f"Foundation gate accepted {result_name} in {position}")
            if result.stdout:
                pytest.fail("Foundation gate emitted unexpected stdout for an invalid result")
            if result.stderr != fixed_diagnostic:
                pytest.fail("Foundation gate emitted a non-fixed error diagnostic")
            output = result.stdout + result.stderr
            if raw_sentinel in output or any(marker in output for marker in encoded_sentinels):
                pytest.fail("Foundation gate leaked a synthetic raw or encoded sentinel")

    for position in FOUNDATION_ENV:
        results = dict.fromkeys(FOUNDATION_ENV, "success")
        results.pop(position)
        result = _run_shell(step["run"], results)
        if result.returncode == 0 or result.stderr != fixed_diagnostic or result.stdout:
            pytest.fail(f"Foundation gate did not fail closed when {position} was missing")


def test_foundation_contract_rejects_dependency_shell_and_filter_drift() -> None:
    valid = _valid_workflow()
    _assert_foundation_contract(valid)

    mutations = (
        ("missing dependency", lambda job: job.__setitem__("needs", ["test", "lint"])),
        (
            "extra dependency",
            lambda job: job.__setitem__("needs", ["test", "lint", "smoke-install", "codeql"]),
        ),
        ("green-skip condition", lambda job: job.__setitem__("if", "${{ success() }}")),
        ("job continuation", lambda job: job.__setitem__("continue-on-error", True)),
        ("job execution permission", lambda job: job.__setitem__("permissions", {"contents": "write"})),
        ("wrong result binding", lambda job: job["steps"][0]["env"].__setitem__("TEST_RESULT", "success")),
        (
            "continuation",
            lambda job: job["steps"][0].__setitem__("continue-on-error", True),
        ),
        ("step condition", lambda job: job["steps"][0].__setitem__("if", "always()")),
        (
            "boolean acceptance",
            lambda job: job["steps"][0].__setitem__(
                "run", FOUNDATION_RUN.replace(" || ", " && ", 1)
            ),
        ),
        ("shell selector", lambda job: job["steps"][0].__setitem__("run", f"{FOUNDATION_RUN}\npytest -k smoke")),
    )
    for label, mutate in mutations:
        candidate = copy.deepcopy(valid)
        mutate(candidate["jobs"][FOUNDATION_JOB_ID])
        try:
            _assert_foundation_contract(candidate)
        except AssertionError:
            continue
        pytest.fail(f"Foundation contract accepted {label}")


def test_workflow_selector_environment_is_rejected_at_workflow_job_and_step_levels() -> None:
    valid = _valid_workflow()
    _assert_no_pytest_selector_env(valid)

    mutations = (
        ("workflow", lambda workflow: workflow.__setitem__("env", {"PYTEST_ADDOPTS": "-k smoke"})),
        (
            "job",
            lambda workflow: workflow["jobs"][FOUNDATION_JOB_ID].__setitem__(
                "env", {"PYTEST_ADDOPTS": "-k smoke"}
            ),
        ),
        (
            "step",
            lambda workflow: workflow["jobs"][FOUNDATION_JOB_ID]["steps"][0]["env"].__setitem__(
                "PYTEST_PLUGINS", "pytest_randomly"
            ),
        ),
    )
    for location, mutate in mutations:
        candidate = copy.deepcopy(valid)
        mutate(candidate)
        try:
            _assert_no_pytest_selector_env(candidate)
        except AssertionError:
            continue
        pytest.fail(f"workflow selector environment was accepted at {location} level")


def test_full_ci_and_pytest_discovery_remain_unfiltered() -> None:
    workflow = _workflow()
    _assert_no_pytest_selector_env(workflow)
    jobs = workflow["jobs"]
    test_job = jobs["test"]
    steps = test_job["steps"]
    full_test_steps = [step for step in steps if step.get("name") == "Run test suite"]
    assert len(full_test_steps) == 1
    assert full_test_steps[0].get("run", "").strip() == FULL_TEST_COMMAND
    assert full_test_steps[0].get("if", True) is True
    assert full_test_steps[0].get("continue-on-error", False) is False

    pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")
    assert re.search(r'(?m)^testpaths\s*=\s*\["tests"\]\s*$', pyproject)
    assert re.search(r'(?m)^addopts\s*=\s*"-ra --strict-markers"\s*$', pyproject)
    assert (ROOT / ".github/workflows/codeql.yml").is_file()
    assert (ROOT / ".github/workflows/dependency-review.yml").is_file()


def test_validation_policy_is_bounded_and_names_local_execution_ownership() -> None:
    if not VALIDATION_POLICY_PATH.is_file():
        pytest.fail("validation ownership policy is missing")
    raw = VALIDATION_POLICY_PATH.read_bytes()
    assert len(raw) <= 6_144
    policy = raw.decode("utf-8")
    normalized = " ".join(policy.split())
    assert re.search(r"(?i)default owner.{0,20}master", normalized)
    for marker in (
        "local full suite",
        "uv run --no-sync python -m pytest -q",
        "source SHA",
        "base SHA",
        "checkout SHA",
        "tree SHA",
        "designated owner",
        "exact command",
        "Python/uv/lock/environment",
        "completion",
        "exit",
        "counts",
        "skips",
        "reasons",
        "full logs",
        "CI run/job/attempt",
        "before/after cleanliness",
        "completed verifiable evidence",
        "identical source/runtime/command",
        "new commit",
        "invalidates affected proof",
        "controlling reviewer",
        "verify the completed local full run",
        "required CI",
        "Master gate",
        "rollback",
    ):
        assert marker in normalized, f"validation ownership policy omits {marker!r}"

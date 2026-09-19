from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_required_ruff_status_carries_harness_contract() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    lint_job = workflow.split("\n  lint:\n", 1)[1].split("\n  foundation-contract-docs-lock:\n", 1)[0]

    assert 'name: ruff (strict, full repo)' in lint_job
    for command in (
        "python scripts/check_agent_harness.py",
        "python scripts/check_dependency_direction.py",
        "python scripts/check_lock_consistency.py",
        "python scripts/check_markdown_contracts.py",
    ):
        assert command in lint_job


def test_foundation_job_leaves_static_harness_contract_to_required_lint() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    lint = workflow.split("\n  lint:\n", 1)[1].split(
        "\n  foundation-contract-docs-lock:\n", 1
    )[0]
    foundation = workflow.split("\n  foundation-contract-docs-lock:\n", 1)[1]

    for command in (
        "python scripts/check_agent_harness.py",
        "python scripts/check_dependency_direction.py",
        "python scripts/check_lock_consistency.py",
        "python scripts/check_markdown_contracts.py",
    ):
        assert lint.count(command) == 1
        assert command not in foundation
    assert "uv sync --locked --extra dev" in foundation
    assert "uv run --no-sync pytest -q tests/productionization" in foundation

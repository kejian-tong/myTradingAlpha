"""RED contract tests for the FND-04 tracked-Markdown validation boundary."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_CHECKER_PATH = REPOSITORY_ROOT / "scripts" / "check_markdown_contracts.py"
LICENSE_PATH = REPOSITORY_ROOT / "LICENSE"
UPSTREAM_PATH = REPOSITORY_ROOT / "UPSTREAM.md"
CHANGES_PATH = REPOSITORY_ROOT / "CHANGES_FROM_UPSTREAM.md"
ROADMAP_PATH = REPOSITORY_ROOT / "docs" / "productionization" / "07_PR_IMPLEMENTATION_PLAN.md"
PHASE_ROOT = REPOSITORY_ROOT / "docs" / "productionization" / "phases"

PHASES = (
    "00-foundation",
    "01-point-in-time-data",
    "02-evidence-agent-boundary",
    "03-backtest-ledger",
    "04-portfolio-risk",
    "05-execution-cost-liquidity",
    "06-experiment-alpha-validation",
    "07-broker-oms-paper-reconciliation",
    "08-forward-paper-gate",
    "09-live-pilot",
)

ROADMAP_IDS = frozenset(
    f"{prefix}-{number:02d}"
    for prefix, count in (
        ("FND", 4),
        ("PIT", 6),
        ("SIG", 5),
        ("BT", 6),
        ("RSK", 5),
        ("EXC", 4),
        ("EXP", 4),
        ("OMS", 6),
        ("FWD", 3),
        ("LIVE", 4),
    )
    for number in range(1, count + 1)
)
ROADMAP_ID_PATTERN = re.compile(r"\b(?:FND|PIT|SIG|BT|RSK|EXC|EXP|OMS|FWD|LIVE)-\d{2}\b")


def _require_file(path: Path, contract: str) -> Path:
    if not path.is_file():
        pytest.fail(f"FND-04 contract is not implemented: missing {contract} at {path}")
    return path


def _run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    _require_file(MARKDOWN_CHECKER_PATH, "Markdown contract checker")
    return subprocess.run(
        [sys.executable, str(MARKDOWN_CHECKER_PATH), str(root)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def _init_fixture_repo(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)


def _write_fixture_file(root: Path, relative_path: str, content: str, *, tracked: bool = True) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if tracked:
        subprocess.run(["git", "-C", str(root), "add", relative_path], check=True)


def _valid_markdown_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "markdown-project"
    root.mkdir()
    _init_fixture_repo(root)

    _write_fixture_file(
        root,
        "LICENSE",
        "Apache License\nVersion 2.0, January 2004\n",
    )
    _write_fixture_file(
        root,
        "UPSTREAM.md",
        "# Upstream\n\nIndependent history; fetch, review, and cherry-pick selected changes.\n",
    )
    _write_fixture_file(
        root,
        "CHANGES_FROM_UPSTREAM.md",
        "# Changes\n\nNo production portfolio or broker behavior is claimed here.\n",
    )
    _write_fixture_file(
        root,
        "README.md",
        "# Fixture\n\n"
        "[Roadmap](docs/productionization/07_PR_IMPLEMENTATION_PLAN.md)\n"
        "[External](https://example.com/reference)\n"
        "[Email](mailto:maintainer@example.com)\n"
        "[Section](#section)\n",
    )
    _write_fixture_file(
        root,
        "docs/productionization/README.md",
        "# Productionization\n\n"
        + "\n".join(
            f"[{phase}](phases/{phase}/DESIGN.md)"
            for phase in PHASES
        )
        + "\n",
    )
    _write_fixture_file(
        root,
        "docs/productionization/07_PR_IMPLEMENTATION_PLAN.md",
        "# Roadmap\n\n"
        + "\n".join(f"- **{roadmap_id}**\n" for roadmap_id in sorted(ROADMAP_IDS))
        + "\n",
    )
    for phase in PHASES:
        phase_text = (
            f"# {phase}\n\n"
            "```text\n"
            "This fixture is intentionally network-free.\n"
            "```\n"
        )
        _write_fixture_file(root, f"docs/productionization/phases/{phase}/DESIGN.md", phase_text)
        _write_fixture_file(
            root,
            f"docs/productionization/phases/{phase}/IMPLEMENTATION.md",
            phase_text,
        )

    # JIT templates contain intentionally unresolved placeholders. They are
    # documentation scaffolding, not relative paths or missing contracts.
    _write_fixture_file(
        root,
        "docs/productionization/PR_IMPLEMENTATION_SPEC_TEMPLATE.md",
        "# JIT spec\n\nRoadmap `<PR-ID>` uses `<path>` and `<symbols>`.\n"
        "[Placeholder target](<path>)\n",
    )
    return root


def _add_tracked(root: Path, relative_path: str, content: str) -> None:
    _write_fixture_file(root, relative_path, content, tracked=True)


def test_current_tracked_markdown_contracts_pass() -> None:
    result = _run_checker(REPOSITORY_ROOT)

    assert result.returncode == 0, _combined_output(result)


def test_repository_retains_apache_license_and_independent_upstream_records() -> None:
    license_text = _require_file(LICENSE_PATH, "Apache LICENSE").read_text(encoding="utf-8")
    upstream_text = _require_file(UPSTREAM_PATH, "UPSTREAM.md").read_text(encoding="utf-8")
    changes_text = _require_file(CHANGES_PATH, "CHANGES_FROM_UPSTREAM.md").read_text(encoding="utf-8")

    assert "Apache License" in license_text
    assert "Version 2.0" in license_text
    assert "independently maintained" in upstream_text
    assert "cherry-pick" in upstream_text
    assert "No production" in changes_text
    assert not (REPOSITORY_ROOT / "NOTICE").exists()


def test_roadmap_has_exactly_47_unique_ids_and_all_phase_document_pairs() -> None:
    roadmap_text = _require_file(ROADMAP_PATH, "47-slice roadmap").read_text(encoding="utf-8")
    roadmap_ids = set(ROADMAP_ID_PATTERN.findall(roadmap_text))

    assert len(roadmap_ids) == 47
    assert roadmap_ids == ROADMAP_IDS
    for phase in PHASES:
        assert (PHASE_ROOT / phase / "DESIGN.md").is_file(), phase
        assert (PHASE_ROOT / phase / "IMPLEMENTATION.md").is_file(), phase


def test_checker_accepts_external_mailto_anchor_and_jit_placeholder_links(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)

    result = _run_checker(root)

    assert result.returncode == 0, _combined_output(result)


def test_checker_rejects_missing_local_relative_link(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)
    _add_tracked(root, "docs/missing-link.md", "[Missing](does-not-exist.md)\n")

    result = _run_checker(root)
    output = _combined_output(result)

    assert result.returncode != 0
    assert "does-not-exist.md" in output
    assert "missing-link.md" in output


def test_checker_rejects_relative_path_escape(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)
    _add_tracked(
        root,
        "docs/productionization/escape.md",
        "[Outside](../../../../outside.md)\n",
    )

    result = _run_checker(root)
    output = _combined_output(result)

    assert result.returncode != 0
    assert "escape.md" in output
    assert re.search(r"(?i)(escape|outside|repository|root)", output)


def test_checker_rejects_unbalanced_fence(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)
    _add_tracked(root, "docs/unbalanced.md", "```python\nprint('unterminated')\n")

    result = _run_checker(root)
    output = _combined_output(result)

    assert result.returncode != 0
    assert "unbalanced.md" in output
    assert "fence" in output.lower()


def test_checker_rejects_mismatched_fence_markers(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)
    _add_tracked(root, "docs/mismatched.md", "```python\nbody\n~~~\n")

    result = _run_checker(root)
    output = _combined_output(result)

    assert result.returncode != 0
    assert "mismatched.md" in output
    assert "fence" in output.lower()


def test_checker_ignores_untracked_markdown(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)
    _write_fixture_file(
        root,
        "docs/untracked.md",
        "[Missing](not-present.md)\n```\nunbalanced\n",
        tracked=False,
    )

    result = _run_checker(root)

    assert result.returncode == 0, _combined_output(result)


def test_checker_diagnostics_are_deterministic_and_path_sorted(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)
    _add_tracked(root, "docs/z-broken.md", "[Missing](z-target.md)\n")
    _add_tracked(root, "docs/a-broken.md", "[Missing](a-target.md)\n")

    first = _run_checker(root)
    second = _run_checker(root)
    first_output = _combined_output(first)
    second_output = _combined_output(second)

    assert first.returncode != 0
    assert second.returncode != 0
    assert first_output == second_output
    assert first_output.index("a-broken.md") < first_output.index("z-broken.md")


def test_checker_requires_every_phase_design_and_implementation_pair(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)
    missing = root / "docs" / "productionization" / "phases" / "04-portfolio-risk" / "DESIGN.md"
    missing.unlink()
    subprocess.run(["git", "-C", str(root), "add", "-u"], check=True)

    result = _run_checker(root)
    output = _combined_output(result)

    assert result.returncode != 0
    assert "04-portfolio-risk" in output
    assert "DESIGN.md" in output


def test_checker_rejects_a_nonroadmap_id_that_breaks_the_47_id_contract(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)
    plan_path = root / "docs" / "productionization" / "07_PR_IMPLEMENTATION_PLAN.md"
    with plan_path.open("a", encoding="utf-8") as plan:
        plan.write("- **FND-99**\n")
    subprocess.run(["git", "-C", str(root), "add", str(plan_path.relative_to(root))], check=True)

    result = _run_checker(root)
    output = _combined_output(result)

    assert result.returncode != 0
    assert "FND-99" in output or "47" in output or "roadmap" in output.lower()


def test_checker_rejects_duplicate_bold_roadmap_definition(tmp_path: Path) -> None:
    root = _valid_markdown_fixture(tmp_path)
    plan_path = root / "docs" / "productionization" / "07_PR_IMPLEMENTATION_PLAN.md"
    with plan_path.open("a", encoding="utf-8") as plan:
        plan.write("- **FND-01 Duplicate definition**\n")
    subprocess.run(["git", "-C", str(root), "add", str(plan_path.relative_to(root))], check=True)

    result = _run_checker(root)
    output = _combined_output(result)

    assert result.returncode != 0
    assert "FND-01" in output or "duplicate" in output.lower() or "47" in output

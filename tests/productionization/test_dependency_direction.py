"""Tests for the foundation package ownership rule."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = REPOSITORY_ROOT / "scripts" / "check_dependency_direction.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("dependency_direction_checker", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load checker from {CHECKER_PATH}")
    checker = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = checker
    spec.loader.exec_module(checker)
    return checker


def _write_fixture(root: Path, relative_path: str, source: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_current_repository_has_valid_dependency_direction() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER_PATH)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "source",
    [
        "import tradingagents\n",
        "import tradingagents as research_graph\n",
        "from tradingagents import graph\n",
        "from tradingagents.graph import setup as graph_setup\n",
    ],
)
def test_non_research_production_package_cannot_import_tradingagents(
    tmp_path: Path, source: str
) -> None:
    _write_fixture(tmp_path, "mytradingalpha/quant/signals.py", source)

    violations = _load_checker().find_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].path == tmp_path / "mytradingalpha/quant/signals.py"
    assert violations[0].line == 1
    assert "mytradingalpha.research" in violations[0].message


def test_tradingagents_cannot_import_production_package(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        "tradingagents/graph/setup.py",
        "from mytradingalpha.contracts import schemas\n",
    )

    violations = _load_checker().find_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].path == tmp_path / "tradingagents/graph/setup.py"
    assert "tradingagents" in violations[0].message


def test_research_adapter_is_the_narrow_reverse_import_exception(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        "mytradingalpha/research/tradingagents_adapter.py",
        "import tradingagents.graph.setup as graph_setup\n"
        "from tradingagents.graph import propagation\n",
    )

    assert _load_checker().find_violations(tmp_path) == []


def test_non_import_mentions_do_not_trigger_dependency_violation(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        "mytradingalpha/quant/signals.py",
        "DOC = 'tradingagents is upstream'\n"
        "# tradingagents import is intentionally only documentation\n",
    )

    assert _load_checker().find_violations(tmp_path) == []


def test_cli_reports_actionable_path_and_line_for_violation(tmp_path: Path) -> None:
    _write_fixture(tmp_path, "mytradingalpha/portfolio/allocator.py", "import tradingagents\n")

    result = subprocess.run(
        [sys.executable, str(CHECKER_PATH), str(tmp_path)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "mytradingalpha/portfolio/allocator.py:1" in result.stderr
    assert "mytradingalpha.research" in result.stderr

"""Bounded dynamic-import analysis: never execute candidate source."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _violations(tmp_path: Path, source: str, package: str = "mytradingalpha/quant"):
    path = tmp_path / package / "candidate.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(
        "audit_dependency_checker", ROOT / "scripts/check_dependency_direction.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.find_violations(tmp_path)


@pytest.mark.parametrize("source", [
    'import importlib\nimportlib.import_module("tradingagents.graph")',
    'import importlib as il\nil.import_module(name="tradingagents.graph")',
    'from importlib import import_module as load\nload("tradingagents.graph")',
    '__import__("tradingagents.graph")',
    'import builtins as b\nb.__import__("tradingagents.graph")',
    'from builtins import __import__ as load\nload("tradingagents.graph")',
    'import importlib\nload = importlib.import_module\nload("tradingagents.graph")',
    'import importlib\nimportlib.import_module(".graph", package="tradingagents")',
    'import importlib\ndef f():\n    return importlib.import_module("tradingagents.graph")',
])
def test_literal_dynamic_forbidden_imports_fail(tmp_path: Path, source: str) -> None:
    findings = _violations(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].imported_module == "tradingagents.graph"
    assert findings[0].line > 0


def test_reverse_dynamic_import_is_forbidden(tmp_path: Path) -> None:
    findings = _violations(tmp_path, '__import__("mytradingalpha.risk")', "tradingagents/graph")
    assert len(findings) == 1


def test_research_adapter_exception_is_preserved(tmp_path: Path) -> None:
    assert not _violations(tmp_path, '__import__("tradingagents.graph")', "mytradingalpha/research")


@pytest.mark.parametrize("source", [
    'import importlib\nname = input()\nimportlib.import_module(name)',
    'import importlib\nimportlib.import_module(".graph", package=unknown)',
])
def test_unresolved_loader_requires_manual_review(tmp_path: Path, source: str) -> None:
    findings = _violations(tmp_path, source)
    assert len(findings) == 1
    assert "manual review" in findings[0].message


@pytest.mark.parametrize("source", [
    'import importlib\nimportlib.import_module("json")',
    'def f(importlib):\n    return importlib.import_module("tradingagents.graph")',
    'from importlib import import_module as load\ndef f(load):\n    return load("tradingagents.graph")',
    'import importlib\nimportlib = object()\nimportlib.import_module("tradingagents.graph")',
    'def __import__(name): return name\n__import__("tradingagents.graph")',
    '# __import__("tradingagents.graph")\nTEXT = "tradingagents.graph"',
])
def test_legal_shadowed_and_nonexecuting_patterns_do_not_false_positive(tmp_path: Path, source: str) -> None:
    assert not _violations(tmp_path, source)

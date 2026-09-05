"""Assignment target expressions are checked in order without executing source."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _violations(tmp_path: Path, source: str, package: str = "mytradingalpha/quant"):
    path = tmp_path / package / "candidate.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "assignment_dependency_checker", ROOT / "scripts/check_dependency_direction.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.find_violations(tmp_path)


@pytest.mark.parametrize("statement", [
    'items[load("tradingagents.graph")] = None',
    'load("tradingagents.graph").value = None',
    'first = items[load("tradingagents.graph")] = None',
    '(first, items[load("tradingagents.graph")]) = values',
    '[first, [items[load("tradingagents.graph")]]] = values',
    'first, *items[load("tradingagents.graph")] = values',
    'items[load("tradingagents.graph")]: object = None',
    'items[load("tradingagents.graph")]: object',
    'load("tradingagents.graph").value: object = None',
    'load("tradingagents.graph").value: object',
    'def f():\n    items[load("tradingagents.graph")]: object',
    'def f():\n    items[load("tradingagents.graph")]: object = None',
])
def test_target_loader_dependency_is_reported(tmp_path: Path, statement: str) -> None:
    findings = _violations(tmp_path, 'from importlib import import_module as load\n' + statement)
    assert len(findings) == 1
    assert findings[0].imported_module == "tradingagents.graph"
    assert findings[0].line >= 2


@pytest.mark.parametrize("statement", [
    'items[load(module_name)] = None',
    'items[load(module_name)]: object',
])
def test_unresolved_target_loader_requires_review(tmp_path: Path, statement: str) -> None:
    findings = _violations(tmp_path, 'from importlib import import_module as load\n' + statement)
    assert len(findings) == 1
    assert findings[0].imported_module == "<dynamic>"


@pytest.mark.parametrize("source", [
    'from importlib import import_module as load\nitems[load("json")] = None',
    'def f(load):\n    items[load("tradingagents.graph")] = None',
    'from importlib import import_module as load\nload = items[load("tradingagents.graph")] = str',
    'from importlib import import_module as load\n(load, items[load("tradingagents.graph")]) = values',
    'from importlib import import_module as load\n[first, [load, items[load("tradingagents.graph")]]] = values',
])
def test_allowed_and_left_to_right_shadowed_targets_do_not_false_positive(
    tmp_path: Path, source: str
) -> None:
    assert _violations(tmp_path, source) == []


@pytest.mark.parametrize("statement", [
    'items[load("tradingagents.graph")], load = values',
    'alias = items["key"] = load\nalias("tradingagents.graph")',
    'load: object\nitems[load("tradingagents.graph")] = None',
    'items[(lambda load: 0)(None)] = None\nload("tradingagents.graph")',
])
def test_target_traversal_preserves_loader_aliases_and_scope(tmp_path: Path, statement: str) -> None:
    findings = _violations(tmp_path, 'from importlib import import_module as load\n' + statement)
    assert len(findings) == 1
    assert findings[0].imported_module == "tradingagents.graph"


def test_rhs_then_target_then_annotation_order(tmp_path: Path) -> None:
    source = ('items[__import__("tradingagents.target")]: '
              '__import__("tradingagents.annotation") = __import__("tradingagents.value")')
    assert [v.imported_module for v in _violations(tmp_path, source)] == [
        "tradingagents.value", "tradingagents.target", "tradingagents.annotation"
    ]


def test_reverse_dependency_and_research_exception(tmp_path: Path) -> None:
    assert len(_violations(tmp_path, 'items[__import__("mytradingalpha.risk")] = None',
                           "tradingagents/graph")) == 1
    assert _violations(tmp_path / "allowed", 'items[__import__("tradingagents.graph")] = None',
                       "mytradingalpha/research") == []


def test_target_source_is_parsed_only(tmp_path: Path) -> None:
    sentinel = tmp_path / "must_not_exist"
    source = (f'open({str(sentinel)!r}, "w").write("unexpected")\n'
              'items[__import__("tradingagents.graph")] = None')
    assert len(_violations(tmp_path, source)) == 1
    assert not sentinel.exists()

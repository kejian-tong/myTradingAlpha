"""Annotation loader dependencies are scanned as source, never evaluated."""

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
        "annotation_dependency_checker", ROOT / "scripts/check_dependency_direction.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.find_violations(tmp_path)


@pytest.mark.parametrize("source", [
    'value: __import__("tradingagents.graph")',
    'value: __import__("tradingagents.graph") = None',
    'class C:\n    value: __import__("tradingagents.graph")',
    'def f(value: __import__("tradingagents.graph")): pass',
    'def f(value: __import__("tradingagents.graph"), /): pass',
    'def f(*, value: __import__("tradingagents.graph")): pass',
    'def f(*values: __import__("tradingagents.graph")): pass',
    'def f(**values: __import__("tradingagents.graph")): pass',
    'def f() -> __import__("tradingagents.graph"): pass',
    'async def f() -> __import__("tradingagents.graph"): pass',
    'import importlib as il\nvalue: il.import_module("tradingagents.graph")',
    'from importlib import import_module as load\ndef f(load: load("tradingagents.graph")): pass',
    'class C:\n    from importlib import import_module as load\n    def f(self, x: load("tradingagents.graph")): pass',
    'def outer():\n    class C:\n        value: __import__("tradingagents.graph")',
    'from __future__ import annotations\nvalue: __import__("tradingagents.graph")',
    # These execute annotations on supported Python <=3.13, but not 3.14.
    'obj.value: __import__("tradingagents.graph")',
    'obj[0]: __import__("tradingagents.graph")',
    '(value): __import__("tradingagents.graph")',
])
def test_annotation_loader_dependency_is_reported(tmp_path: Path, source: str) -> None:
    findings = _violations(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].imported_module == "tradingagents.graph"
    assert findings[0].path == tmp_path / "mytradingalpha/quant/candidate.py"
    assert findings[0].line > 0


@pytest.mark.parametrize("source", [
    'value: __import__(module_name)',
    'import importlib\ndef f() -> importlib.import_module(module_name): pass',
])
def test_unresolved_annotation_loader_requires_review(tmp_path: Path, source: str) -> None:
    findings = _violations(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].imported_module == "<dynamic>"
    assert "manual review" in findings[0].message


@pytest.mark.parametrize("source", [
    'value: str = "tradingagents.graph"',
    'value: "__import__(\'tradingagents.graph\')"',
    'def f() -> "__import__(\'tradingagents.graph\')": pass',
    'value: __import__("json")',
    'def f():\n    value: __import__("tradingagents.graph")',
    'def f():\n    value: __import__("tradingagents.graph") = None',
    'class C:\n    def f(self):\n        value: __import__("tradingagents.graph")',
    'def outer(load):\n    def inner() -> load("tradingagents.graph"): pass',
    'class C:\n    load = str\n    def f(self, x: load("tradingagents.graph")): pass',
    # Assignment happens before the annotation in eager-annotation Python.
    'from importlib import import_module as load\nload: load("tradingagents.graph") = str',
])
def test_nonexecuted_or_nonloader_annotations_do_not_false_positive(
    tmp_path: Path, source: str
) -> None:
    assert _violations(tmp_path, source) == []


def test_function_local_annotation_does_not_hide_an_executed_value(tmp_path: Path) -> None:
    source = 'def f():\n    value: str = __import__("tradingagents.graph")'
    findings = _violations(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].imported_module == "tradingagents.graph"


def test_annotation_reverse_import_and_research_exception(tmp_path: Path) -> None:
    findings = _violations(
        tmp_path, 'value: __import__("mytradingalpha.risk")', "tradingagents/graph"
    )
    assert len(findings) == 1
    assert findings[0].imported_module == "mytradingalpha.risk"
    other_root = tmp_path / "permitted"
    assert _violations(
        other_root, 'value: __import__("tradingagents.graph")', "mytradingalpha/research"
    ) == []


def test_annotation_source_is_not_executed(tmp_path: Path) -> None:
    source = 'raise AssertionError("source must never run")\nvalue: __import__("tradingagents.graph")'
    findings = _violations(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].line == 2

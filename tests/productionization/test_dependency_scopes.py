"""A06 follow-up: lexical scopes and possible branch bindings, without execution."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _violations(tmp_path: Path, source: str):
    candidate = tmp_path / "mytradingalpha/quant/candidate.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "scope_dependency_checker", ROOT / "scripts/check_dependency_direction.py"
    )
    checker = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = checker
    spec.loader.exec_module(checker)
    return checker.find_violations(tmp_path)


@pytest.mark.parametrize("source", [
    'import importlib\nclass C:\n    importlib = None\n'
    '    def f(self): return importlib.import_module("tradingagents.graph")\n',
    'import importlib\nclass C:\n    importlib = None\n'
    '    f = lambda: importlib.import_module("tradingagents.graph")\n',
    'import importlib\nclass C:\n    importlib = None\n'
    '    values = [importlib.import_module("tradingagents.graph") for x in items]\n',
    'import importlib\nimportlib: object\nimportlib.import_module("tradingagents.graph")\n',
    'if flag:\n    import importlib as loader\nelse:\n    loader = None\n'
    'loader.import_module("tradingagents.graph")\n',
    'if flag:\n    from importlib import import_module as loader\nelse:\n    loader = None\n'
    'loader("tradingagents.graph")\n',
    'import importlib\nif flag:\n    importlib = None\n'
    'importlib.import_module("tradingagents.graph")\n',
    'import importlib\nf = lambda importlib: None\n'
    'importlib.import_module("tradingagents.graph")\n',
    'import importlib\nitems = [importlib for importlib in values]\n'
    'importlib.import_module("tradingagents.graph")\n',
    'import importlib\nvalues = [x for x in importlib.import_module("tradingagents.graph")]\n',
    'import importlib\nclass C:\n'
    '    def f(self, x=importlib.import_module("tradingagents.graph")): return x\n',
])
def test_possible_literal_dependency_is_not_lost(tmp_path: Path, source: str) -> None:
    findings = _violations(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].imported_module == "tradingagents.graph"


@pytest.mark.parametrize("source", [
    'import importlib\nf = lambda importlib: importlib.import_module("tradingagents.graph")\n',
    'import importlib\nx = [importlib.import_module("tradingagents.graph") for importlib in values]\n',
    'import importlib\nx = {importlib.import_module("tradingagents.graph") for importlib in values}\n',
    'import importlib\nx = (importlib.import_module("tradingagents.graph") for importlib in values)\n',
    'import importlib\nx = {k: importlib.import_module("tradingagents.graph") for k, importlib in values}\n',
    'import importlib\ndef f():\n    importlib: object\n'
    '    return importlib.import_module("tradingagents.graph")\n',
    'import importlib\ndef f():\n    importlib.import_module("tradingagents.graph")\n'
    '    importlib = None\n',
    'class C:\n    import importlib\n'
    '    def f(self): return importlib.import_module("tradingagents.graph")\n',
    'if flag:\n    import importlib as loader\nelse:\n    loader = None\n'
    'loader.import_module("json")\n',
    'import importlib\ndef f(importlib): return importlib.import_module("tradingagents.graph")\n',
])
def test_local_shadowing_does_not_claim_a_real_loader(tmp_path: Path, source: str) -> None:
    assert not _violations(tmp_path, source)


def test_branch_join_retains_all_recognized_loader_kinds(tmp_path: Path) -> None:
    source = ('if flag:\n    from importlib import import_module as load\n'
              'else:\n    from builtins import __import__ as load\n'
              'load(".graph", package="tradingagents")\n')
    # One branch has a known forbidden target; the other cannot resolve this call.
    findings = _violations(tmp_path, source)
    assert any(item.imported_module == "tradingagents.graph" for item in findings)


def test_lambda_default_is_evaluated_in_enclosing_scope(tmp_path: Path) -> None:
    findings = _violations(tmp_path, 'import importlib\nf = lambda x=importlib.import_module("tradingagents.graph"): x\n')
    assert len(findings) == 1


def test_candidate_is_only_parsed_never_run(tmp_path: Path) -> None:
    sentinel = tmp_path / "must_not_exist"
    source = f'open({str(sentinel)!r}, "w").write("executed")\nimport importlib\nimportlib.import_module("json")\n'
    assert not _violations(tmp_path, source)
    assert not sentinel.exists()

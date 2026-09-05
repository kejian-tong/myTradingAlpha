"""Annotation-only and annotated self-assignment preserve module loader bindings."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.productionization.test_dependency_scopes import _violations


@pytest.mark.parametrize("annotation", ["importlib: object", "importlib: object = importlib"])
def test_annotated_module_loader_keeps_its_value(tmp_path: Path, annotation: str) -> None:
    source = f'import importlib\n{annotation}\nimportlib.import_module("tradingagents.graph")\n'
    findings = _violations(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].imported_module == "tradingagents.graph"

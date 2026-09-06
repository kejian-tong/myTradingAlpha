"""AUD-M01 bounded expression and control-flow binding contracts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _violations(tmp_path: Path, source: str):
    candidate = tmp_path / "mytradingalpha/quant/candidate.py"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "control_flow_dependency_checker",
        ROOT / "scripts/check_dependency_direction.py",
    )
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = checker
    spec.loader.exec_module(checker)
    return checker.find_violations(tmp_path)


def _assert_forbidden(tmp_path: Path, source: str, expected: str = "tradingagents.graph") -> None:
    findings = _violations(tmp_path, source)
    assert len(findings) == 1
    assert findings[0].imported_module == expected


@pytest.mark.parametrize(
    "source",
    (
        "from importlib import import_module\n"
        '(load := import_module)("tradingagents.graph")\n',
        "import importlib\n"
        '(load := importlib.import_module)("tradingagents.graph")\n',
    ),
)
def test_named_expression_loader_is_detected(tmp_path: Path, source: str) -> None:
    _assert_forbidden(tmp_path, source)


def test_named_expression_unresolved_loader_requires_one_review(tmp_path: Path) -> None:
    findings = _violations(
        tmp_path,
        "from importlib import import_module\n(load := import_module)(module_name)\n",
    )
    assert len(findings) == 1
    assert findings[0].imported_module == "<dynamic>"
    assert "manual review" in findings[0].message


@pytest.mark.parametrize(
    "source",
    (
        "import importlib\n(importlib := safe)\n"
        'importlib.import_module("tradingagents.graph")\n',
        "from importlib import import_module as load\n(load := safe)\n"
        'load("tradingagents.graph")\n',
        "from importlib import import_module as load\nimport json\n(load := json.loads)\n"
        'load("tradingagents.graph")\n',
    ),
)
def test_named_expression_shadow_does_not_false_positive(
    tmp_path: Path,
    source: str,
) -> None:
    assert _violations(tmp_path, source) == []


@pytest.mark.parametrize(
    "source",
    (
        "from importlib import import_module\n"
        '(import_module if flag else safe)("tradingagents.graph")\n',
        "from importlib import import_module\n"
        "load = import_module if flag else safe\n"
        'load("tradingagents.graph")\n',
        "import importlib\n"
        "load = importlib.import_module if flag else safe\n"
        'load("tradingagents.graph")\n',
    ),
)
def test_conditional_expression_retains_possible_loader(
    tmp_path: Path,
    source: str,
) -> None:
    _assert_forbidden(tmp_path, source)


def test_conditional_expression_safe_values_do_not_false_positive(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "import json\nload = json.loads if flag else safe\n"
        'load("tradingagents.graph")\n',
    ) == []


@pytest.mark.parametrize(
    "source",
    (
        "from importlib import import_module as load\n"
        "try:\n    load = safe\nexcept Exception:\n    pass\n"
        'load("tradingagents.graph")\n',
        "from importlib import import_module\nload = safe\n"
        "try:\n    load = import_module\n    risky()\n    load = safe\n"
        "except Exception:\n    load(\"tradingagents.graph\")\n",
        "from importlib import import_module\nload = safe\n"
        "try:\n    risky()\nexcept Exception:\n    load = import_module\n"
        'load("tradingagents.graph")\n',
        "from importlib import import_module\nload = safe\n"
        "try:\n    pass\nexcept Exception:\n    pass\n"
        "else:\n    load = import_module\n"
        'load("tradingagents.graph")\n',
        "from importlib import import_module\nload = safe\n"
        "try:\n    if flag:\n        load = import_module\n"
        "except Exception:\n    pass\n"
        "finally:\n    load(\"tradingagents.graph\")\n",
    ),
)
def test_try_paths_retain_reachable_loader(tmp_path: Path, source: str) -> None:
    _assert_forbidden(tmp_path, source)


def test_finally_safe_overwrite_remains_safe(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module as load\n"
        "try:\n    risky()\nexcept Exception:\n    pass\n"
        "finally:\n    load = safe\n"
        'load("tradingagents.graph")\n',
    ) == []


@pytest.mark.parametrize("keyword", ("for", "async for"))
def test_for_target_shadows_loader_before_body(tmp_path: Path, keyword: str) -> None:
    statement = f'{keyword} load in values:\n        load("tradingagents.graph")'
    source = (
        "from importlib import import_module as load\n"
        + (f"async def run():\n    {statement}\n" if keyword.startswith("async") else statement + "\n")
    )
    assert _violations(tmp_path, source) == []


@pytest.mark.parametrize("keyword", ("for", "async for"))
def test_for_iterable_loader_call_is_evaluated(tmp_path: Path, keyword: str) -> None:
    statement = f'{keyword} item in load("tradingagents.graph"):\n        pass'
    source = (
        "from importlib import import_module as load\n"
        + (f"async def run():\n    {statement}\n" if keyword.startswith("async") else statement + "\n")
    )
    _assert_forbidden(tmp_path, source)


def test_for_zero_iteration_preserves_preloop_loader(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module as load\n"
        "for load in values:\n    pass\n"
        'load("tradingagents.graph")\n',
    )


def test_for_body_loader_reaches_next_iteration_without_duplicates(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "for item in values:\n"
        '    load("tradingagents.graph")\n'
        "    load = import_module\n",
    )


def test_for_else_receives_possible_body_loader(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "for item in values:\n    load = import_module\n"
        'else:\n    load("tradingagents.graph")\n',
    )


def test_while_zero_iteration_preserves_preloop_loader(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module as load\n"
        "while flag:\n    load = safe\n"
        'load("tradingagents.graph")\n',
    )


def test_while_test_sees_loader_from_prior_iteration_once(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        'while load("tradingagents.graph"):\n    load = import_module\n',
    )


def test_while_else_receives_possible_body_loader(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "while flag:\n    load = import_module\n"
        'else:\n    load("tradingagents.graph")\n',
    )


def test_while_safe_paths_do_not_false_positive(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "load = safe\nwhile flag:\n    load = safe\n"
        'else:\n    load("tradingagents.graph")\n',
    ) == []


def test_while_test_binding_applies_before_zero_iteration_exit(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module as load\n"
        "while (load := safe):\n    pass\n"
        'load("tradingagents.graph")\n',
    ) == []


@pytest.mark.parametrize("keyword", ("with", "async with"))
def test_with_target_shadows_loader_before_body(tmp_path: Path, keyword: str) -> None:
    statement = f'{keyword} manager as load:\n        load("tradingagents.graph")'
    source = (
        "from importlib import import_module as load\n"
        + (f"async def run():\n    {statement}\n" if keyword.startswith("async") else statement + "\n")
    )
    assert _violations(tmp_path, source) == []


@pytest.mark.parametrize("keyword", ("with", "async with"))
def test_with_context_loader_call_precedes_target_shadow(tmp_path: Path, keyword: str) -> None:
    statement = f'{keyword} load("tradingagents.graph") as value:\n        pass'
    source = (
        "from importlib import import_module as load\n"
        + (f"async def run():\n    {statement}\n" if keyword.startswith("async") else statement + "\n")
    )
    _assert_forbidden(tmp_path, source)


@pytest.mark.parametrize("keyword", ("with", "async with"))
def test_with_items_bind_sequentially(tmp_path: Path, keyword: str) -> None:
    statement = (
        f'{keyword} first as load, load("tradingagents.graph") as value:\n        pass'
    )
    source = (
        "from importlib import import_module as load\n"
        + (f"async def run():\n    {statement}\n" if keyword.startswith("async") else statement + "\n")
    )
    assert _violations(tmp_path, source) == []


def test_comprehension_named_expression_immediate_call_is_detected(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\n"
        'values = [(load := import_module)("tradingagents.graph") for item in items]\n',
    )


def test_comprehension_named_expression_updates_containing_scope(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "values = [(load := import_module) for item in items]\n"
        'load("tradingagents.graph")\n',
    )


def test_comprehension_named_expression_updates_containing_function_scope(
    tmp_path: Path,
) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\n"
        "def run():\n"
        "    values = [(load := import_module) for item in items]\n"
        '    load("tradingagents.graph")\n',
    )


def test_comprehension_safe_walrus_is_local_not_outer_loader(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module as load\n"
        "def run():\n"
        "    values = [(load := safe) for item in items]\n"
        '    load("tradingagents.graph")\n',
    ) == []


def test_comprehension_zero_iteration_preserves_outer_loader(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module as load\n"
        "values = [(load := safe) for item in items]\n"
        'load("tradingagents.graph")\n',
    )


def test_comprehension_named_expression_shadow_applies_inside_expression(
    tmp_path: Path,
) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module as load\n"
        'values = [(load := safe) and load("tradingagents.graph") for item in items]\n',
    ) == []


def test_fixed_point_unresolved_loader_is_reported_once(tmp_path: Path) -> None:
    findings = _violations(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "while flag:\n    load = import_module\n    load(module_name)\n",
    )
    assert len(findings) == 1
    assert findings[0].imported_module == "<dynamic>"


def test_json_and_parameter_shadows_remain_safe(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "import json\nload = json.loads if flag else safe\n"
        "def run(load):\n    while flag:\n        load(\"tradingagents.graph\")\n"
        "with manager as load:\n    load(\"tradingagents.graph\")\n",
    ) == []


def test_control_flow_source_is_parsed_only(tmp_path: Path) -> None:
    sentinel = tmp_path / "must_not_exist"
    source = (
        f'open({str(sentinel)!r}, "w").write("executed")\n'
        "from importlib import import_module\n"
        "while flag:\n    load = import_module\n"
        'load("tradingagents.graph")\n'
    )
    _assert_forbidden(tmp_path, source)
    assert not sentinel.exists()

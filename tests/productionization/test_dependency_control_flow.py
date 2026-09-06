"""AUD-M01 bounded expression and control-flow binding contracts."""

from __future__ import annotations

import ast
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


def test_review_repair_callable_ifexp_applies_test_shadow_before_resolution(
    tmp_path: Path,
) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module as load\n"
        '(load if (load := safe) else safe)("tradingagents.graph")\n',
    ) == []


def test_review_repair_callable_ifexp_applies_test_loader_before_resolution(
    tmp_path: Path,
) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        '(load if (load := import_module) else safe)("tradingagents.graph")\n',
    )


def test_review_repair_callable_ifexp_unresolved_target_is_unique(tmp_path: Path) -> None:
    findings = _violations(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "(load if (load := import_module) else safe)(module_name)\n",
    )
    assert len(findings) == 1
    assert findings[0].imported_module == "<dynamic>"


def test_review_repair_callable_then_nested_argument_calls_are_ordered_once(
    tmp_path: Path,
) -> None:
    findings = _violations(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        '(load if (load := import_module) else safe)("tradingagents.outer", '
        'value=load("tradingagents.argument"))\n',
    )
    assert [finding.imported_module for finding in findings] == [
        "tradingagents.outer",
        "tradingagents.argument",
    ]


@pytest.mark.skipif(not hasattr(ast, "TryStar"), reason="except* requires Python 3.11+")
def test_review_repair_trystar_prior_handler_loader_reaches_later_handler(
    tmp_path: Path,
) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "try:\n    risky()\n"
        "except* FirstError:\n    load = import_module\n"
        'except* SecondError:\n    load("tradingagents.graph")\n',
    )


@pytest.mark.skipif(not hasattr(ast, "TryStar"), reason="except* requires Python 3.11+")
def test_review_repair_trystar_no_match_path_preserves_loader(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module as load\n"
        "try:\n    risky()\n"
        "except* FirstError:\n    load = safe\n"
        'except* SecondError:\n    load("tradingagents.graph")\n',
    )


@pytest.mark.skipif(not hasattr(ast, "TryStar"), reason="except* requires Python 3.11+")
def test_review_repair_trystar_safe_sequential_handlers_do_not_false_positive(
    tmp_path: Path,
) -> None:
    assert _violations(
        tmp_path,
        "load = safe\ntry:\n    risky()\n"
        "except* FirstError:\n    load = safe\n"
        'except* SecondError:\n    load("tradingagents.graph")\n',
    ) == []


@pytest.mark.parametrize("keyword", ("for", "async for"))
def test_review_repair_no_break_for_else_overwrite_controls_postloop(
    tmp_path: Path,
    keyword: str,
) -> None:
    if keyword.startswith("async"):
        source = (
            "from importlib import import_module\n"
            "async def run():\n"
            "    load = import_module\n"
            "    async for item in values:\n"
            "        load = import_module\n"
            "    else:\n"
            "        load = safe\n"
            '    load("tradingagents.graph")\n'
        )
    else:
        source = (
            "from importlib import import_module\n"
            "load = import_module\n"
            "for item in values:\n"
            "    load = import_module\n"
            "else:\n"
            "    load = safe\n"
            'load("tradingagents.graph")\n'
        )
    assert _violations(tmp_path, source) == []


def test_review_repair_no_break_while_else_overwrite_controls_postloop(
    tmp_path: Path,
) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module as load\n"
        "while flag:\n    load = safe\n"
        "else:\n    load = safe\n"
        'load("tradingagents.graph")\n',
    ) == []


@pytest.mark.parametrize("keyword", ("for", "async for"))
def test_review_repair_current_loop_break_retains_loader_exit(
    tmp_path: Path,
    keyword: str,
) -> None:
    if keyword.startswith("async"):
        source = (
            "from importlib import import_module\n"
            "async def run():\n"
            "    load = safe\n"
            "    async for item in values:\n"
            "        load = import_module\n"
            "        break\n"
            "    else:\n"
            "        load = safe\n"
            '    load("tradingagents.graph")\n'
        )
    else:
        source = (
            "from importlib import import_module\n"
            "load = safe\n"
            "for item in values:\n"
            "    load = import_module\n"
            "    break\n"
            "else:\n"
            "    load = safe\n"
            'load("tradingagents.graph")\n'
        )
    _assert_forbidden(tmp_path, source)


def test_review_repair_current_while_break_retains_loader_exit(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "while flag:\n    load = import_module\n    break\n"
        "else:\n    load = safe\n"
        'load("tradingagents.graph")\n',
    )


def test_review_repair_nested_loop_break_does_not_skip_outer_else(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module as load\n"
        "for item in values:\n    while flag:\n        break\n"
        "else:\n    load = safe\n"
        'load("tradingagents.graph")\n',
    ) == []


def test_review_repair_generator_walrus_is_lazy_at_construction(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "values = ((load := import_module) for item in items)\n"
        'load("tradingagents.graph")\n',
    ) == []


def test_review_repair_generator_deferred_body_is_still_inspected(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module as load\n"
        'values = (load("tradingagents.graph") for item in items)\n',
    )


def test_review_repair_generator_first_iterable_is_eagerly_inspected(tmp_path: Path) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module as load\n"
        'values = (item for item in load("tradingagents.graph"))\n',
    )


@pytest.mark.parametrize(
    "expression",
    (
        "[(load := import_module) for item in items]",
        "{(load := import_module) for item in items}",
        "{item: (load := import_module) for item in items}",
    ),
)
def test_review_repair_eager_comprehensions_still_propagate_walrus(
    tmp_path: Path,
    expression: str,
) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        f"values = {expression}\n"
        'load("tradingagents.graph")\n',
    )


def test_review_repair_handler_target_is_cleared_on_exceptional_finally_path(
    tmp_path: Path,
) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "try:\n    risky()\n"
        "except Exception as load:\n    load = import_module\n    raise\n"
        'finally:\n    load("tradingagents.graph")\n',
    ) == []


def test_review_repair_handler_cleanup_preserves_outer_loader_success_path(
    tmp_path: Path,
) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module as load\n"
        "try:\n    risky()\n"
        "except Exception as load:\n    load = safe\n    raise\n"
        'finally:\n    load("tradingagents.graph")\n',
    )


@pytest.mark.skipif(not hasattr(ast, "TryStar"), reason="except* requires Python 3.11+")
def test_review_repair_trystar_target_is_cleared_before_finally(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "try:\n    risky()\n"
        "except* Exception as load:\n    load = import_module\n    raise\n"
        'finally:\n    load("tradingagents.graph")\n',
    ) == []


@pytest.mark.skipif(hasattr(ast, "TryStar"), reason="Python 3.11+ supports except*")
def test_second_review_repair_py310_trystar_is_a_parse_error(tmp_path: Path) -> None:
    findings = _violations(
        tmp_path,
        "try:\n    risky()\nexcept* Exception:\n    pass\n",
    )
    assert len(findings) == 1
    assert findings[0].imported_module == "<parse error>"
    assert "could not parse Python source" in findings[0].message


@pytest.mark.parametrize("container", ("if", "try", "except", "finally"))
def test_second_review_repair_captures_exact_nested_break_state(
    tmp_path: Path,
    container: str,
) -> None:
    if container == "if":
        body = (
            "    if flag:\n"
            "        load = import_module\n"
            "        break\n"
            "        load = safe\n"
        )
    elif container == "try":
        body = (
            "    try:\n"
            "        load = import_module\n"
            "        break\n"
            "        load = safe\n"
        )
    elif container == "except":
        body = (
            "    try:\n"
            "        risky()\n"
            "    except Exception:\n"
            "        load = import_module\n"
            "        break\n"
            "        load = safe\n"
        )
    else:
        assert container == "finally"
        body = (
            "    try:\n"
            "        pass\n"
            "    finally:\n"
            "        load = import_module\n"
            "        break\n"
            "        load = safe\n"
        )
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "for item in values:\n"
        + body
        + "else:\n    load = safe\n"
        + 'load("tradingagents.graph")\n',
    )


@pytest.mark.parametrize("outer", ("for", "async for", "while"))
def test_second_review_repair_nested_loop_else_break_targets_outer_loop(
    tmp_path: Path,
    outer: str,
) -> None:
    if outer == "async for":
        source = (
            "from importlib import import_module\n"
            "async def run():\n"
            "    load = safe\n"
            "    async for outer_item in values:\n"
            "        for inner_item in other_values:\n"
            "            pass\n"
            "        else:\n"
            "            load = import_module\n"
            "            break\n"
            "            load = safe\n"
            "    else:\n"
            "        load = safe\n"
            '    load("tradingagents.graph")\n'
        )
    else:
        outer_header = "for outer_item in values:" if outer == "for" else "while outer_flag:"
        source = (
            "from importlib import import_module\n"
            "load = safe\n"
            f"{outer_header}\n"
            "    for inner_item in other_values:\n"
            "        pass\n"
            "    else:\n"
            "        load = import_module\n"
            "        break\n"
            "        load = safe\n"
            "else:\n"
            "    load = safe\n"
            'load("tradingagents.graph")\n'
        )
    _assert_forbidden(tmp_path, source)


def test_second_review_repair_nested_loop_body_break_remains_inner(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        "from importlib import import_module as load\n"
        "for outer_item in values:\n"
        "    for inner_item in other_values:\n"
        "        break\n"
        "else:\n"
        "    load = safe\n"
        'load("tradingagents.graph")\n',
    ) == []


def test_second_review_repair_direct_break_is_unique_and_not_erased(
    tmp_path: Path,
) -> None:
    _assert_forbidden(
        tmp_path,
        "from importlib import import_module\nload = safe\n"
        "for item in values:\n"
        "    load = import_module\n"
        "    break\n"
        "    load = safe\n"
        "else:\n"
        "    load = safe\n"
        'load("tradingagents.graph")\n',
    )

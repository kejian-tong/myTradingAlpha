"""Executable specification regressions, not implementations of future trading phases.

Only inspected arithmetic-only documentation functions are evaluated. No imports,
attributes, calls, I/O, model, broker, clock, or arbitrary code are allowed in them.
"""

from __future__ import annotations

import ast
import re
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/productionization"


def _read(path: str) -> str:
    return (DOCS / path).read_text(encoding="utf-8")


def _accounting_equations() -> dict:
    text = _read("03_CONTRACTS_AND_SCHEMAS.md")
    match = re.search(r"<!-- accounting-equations -->\s*```python\n(.*?)\n```", text, re.S)
    assert match, "missing unit-explicit accounting specification"
    source = match.group(1)
    assert len(source) < 4096
    tree = ast.parse(source)
    allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
               ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Add, ast.Sub,
               ast.Mult, ast.USub)
    assert all(isinstance(node, allowed) for node in ast.walk(tree))
    assert {node.name for node in tree.body} == {"fill_cash_delta", "implementation_shortfall"}
    assert all(not node.decorator_list and len(node.body) == 1 for node in tree.body)
    namespace = {"__builtins__": {}}
    exec(compile(tree, "<audited-accounting-equations>", "exec"), namespace)
    return namespace


@pytest.mark.parametrize(("quantity", "price", "fee", "cash", "loss"), [
    ("10", "100.6", "1", "-1007", "7"),
    ("-10", "99.4", "1", "993", "7"),
    ("10", "100", "0", "-1000", "0"),
    ("-10", "100", "0", "1000", "0"),
])
def test_fill_price_and_explicit_fee_are_charged_once(quantity, price, fee, cash, loss) -> None:
    equations = _accounting_equations()
    q, p, f = map(Decimal, (quantity, price, fee))
    actual = equations["fill_cash_delta"](q, p, f)
    assert actual == Decimal(cash)
    assert actual + q * Decimal("100") == -Decimal(loss)
    assert equations["implementation_shortfall"](q, p, Decimal("100"), f) == Decimal(loss)


def test_order_fee_allocation_across_three_partial_fills_balances() -> None:
    equation = _accounting_equations()["fill_cash_delta"]
    fills = [(Decimal(q), Decimal(f)) for q, f in (("2", ".2"), ("3", ".3"), ("5", ".5"))]
    assert sum(f for _, f in fills) == Decimal("1")
    cash = sum(equation(q, Decimal("100.6"), f) for q, f in fills)
    assert cash == Decimal("-1007")
    assert cash + Decimal("10") * Decimal("100") == Decimal("-7")
    assert "fee_policy_id" in _read("03_CONTRACTS_AND_SCHEMAS.md")


def _transitions() -> dict[str, set[str]]:
    table = _read("03_CONTRACTS_AND_SCHEMAS.md").split("## OMS transition table", 1)[1]
    result = {}
    for line in table.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] in {"Submitted", "Acknowledged", "Partial", "Unknown"}:
            result[cells[0]] = set(cells[1].split(", "))
    return result


def test_documented_transitions_accept_distinct_partial_events_then_fill_or_expiry() -> None:
    transitions = _transitions()
    state = "Acknowledged"
    for following in ("Partial", "Partial", "Filled"):
        assert following in transitions[state]
        state = following
    assert "Expired" in transitions["Partial"]
    text = _read("03_CONTRACTS_AND_SCHEMAS.md")
    assert "same event ID and identical payload" in text
    assert "cumulative_filled" in text and "late" in text


def test_unknown_ack_retains_query_only_recovery() -> None:
    assert not ({"Submitting", "Submitted"} & _transitions()["Unknown"])
    assert "never blindly resubmit" in _read("03_CONTRACTS_AND_SCHEMAS.md")


def test_cost_and_oms_implementation_text_does_not_reintroduce_old_rules() -> None:
    cost = _read("phases/05-execution-cost-liquidity/IMPLEMENTATION.md")
    assert "cost = spread + slippage + commission + impact_cost" not in cost
    assert "explicit_fee" in cost and "attribution only" in cost
    for path in ("phases/07-broker-oms-paper-reconciliation/DESIGN.md", "07_PR_IMPLEMENTATION_PLAN.md"):
        text = _read(path)
        assert "partial" in text.lower() and "cumulative_filled" in text
        assert "Partial→Filled/Cancelled/Rejected." not in text
        assert "partial → filled/cancelled/rejected`." not in text


def test_wire_contracts_have_first_use_owners_without_duplicate_registries() -> None:
    text = _read("03_CONTRACTS_AND_SCHEMAS.md")
    for name, first_use in (("ResearchNote", "SIG-02"), ("QuantSignal", "SIG-03"),
                            ("LLMOverlay", "SIG-04"), ("SignalEnvelope", "SIG-05"),
                            ("OrderIntent / Fill", "BT-02"), ("OrderEvent", "OMS-01")):
        assert f"| {name} | {first_use} |" in text
    experiment = _read("phases/06-experiment-alpha-validation/IMPLEMENTATION.md")
    assert "ExperimentRegistry" in experiment
    assert "`mytradingalpha/experiments/registry.py`: `VariantRegistry" not in experiment
    backtest = _read("phases/03-backtest-ledger/IMPLEMENTATION.md")
    assert "mytradingalpha/backtest/costs/__init__.py" in backtest
    assert "`mytradingalpha/backtest/costs.py`" not in backtest


def test_optional_optimizer_does_not_become_a_mandatory_baseline_gate() -> None:
    text = _read("phases/04-portfolio-risk/IMPLEMENTATION.md")
    assert "RSK-01 through RSK-04" in text
    assert "not_applicable" in text
    assert "All RSK PRs pass" not in text
    assert "no dynamic fallback" in text


def test_response_producer_handoff_retains_existing_v1_cutoff_and_scope() -> None:
    text = _read("03_CONTRACTS_AND_SCHEMAS.md")
    assert "## Closed response capture and replay handoff" in text
    for invariant in ("FWD-01", "pre-close", "input_freeze_time", "available_at <= knowledge_cutoff",
                      "ingested_at <= knowledge_cutoff", "never backdate", "SIG-02", "no new inference"):
        assert invariant in text
    experiment = _read("phases/06-experiment-alpha-validation/IMPLEMENTATION.md")
    assert "distinct captured response" in experiment
    assert "insufficient_evidence" in experiment
    forward = _read("phases/08-forward-paper-gate/IMPLEMENTATION.md")
    assert "input_freeze_time" in forward and "actual capture timestamps" in forward


def test_simulation_is_not_real_operational_promotion_evidence() -> None:
    text = _read("phases/08-forward-paper-gate/IMPLEMENTATION.md")
    assert "Software acceptance" in text and "Operational promotion" in text
    assert "real elapsed sessions" in text and "not operational promotion evidence" in text
    gates = _read("06_ROADMAP_AND_PHASE_GATES.md")
    assert "Non-goals are broker writes before Phase 09" not in gates
    assert "live-broker writes before Phase 09" in gates


def test_current_documentation_points_to_real_contract_and_test_paths() -> None:
    for phase in ("00-foundation", "01-point-in-time-data"):
        text = _read(f"phases/{phase}/DESIGN.md")
        assert "Status: implemented" in text
    assert "Status: partially implemented" in _read("phases/02-evidence-agent-boundary/DESIGN.md")
    matrix = _read("appendices/B_TEST_MATRIX.md")
    assert "## Implemented productionization checks" in matrix
    implemented = matrix.split("## Implemented productionization checks", 1)[1].split("## Planned productionization checks", 1)[0]
    paths = re.findall(r"`(tests/productionization/[a-zA-Z0-9_./-]+\.py)`", implemented)
    assert len(paths) >= 8
    assert all((ROOT / path).is_file() for path in paths)
    assert "A future locked CI job" not in matrix
    assert "contracts/test_run_context.py" not in matrix
    assert "data/test_cutoff_selection.py" not in matrix
    contracts = _read("03_CONTRACTS_AND_SCHEMAS.md")
    assert "typed-domain v1" in contracts and "data/bundle.py" in contracts
    assert "not directly loadable" in _read("appendices/D_CONFIG_EXAMPLES.md")


def test_roadmap_retains_all_47_unique_definitions_and_dependency_order() -> None:
    rows = []
    for line in _read("07_PR_IMPLEMENTATION_PLAN.md").splitlines():
        match = re.match(r"\| \*\*([A-Z]+-\d{2}) [^|]+\| ([^|]+)\|", line)
        if match:
            rows.append(match.groups())
    assert len(rows) == len({identifier for identifier, _ in rows}) == 47
    seen = set()
    for identifier, dependencies in rows:
        for prefix, first, last in re.findall(r"([A-Z]+)-(\d{2})(?:\.\.(\d{2}))?", dependencies):
            for number in range(int(first), int(last or first) + 1):
                assert f"{prefix}-{number:02d}" in seen
        seen.add(identifier)

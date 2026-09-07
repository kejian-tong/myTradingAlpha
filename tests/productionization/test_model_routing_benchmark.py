from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/model_routing_benchmark.py"
    spec = importlib.util.spec_from_file_location("model_routing_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(model: str, *, task_id: str = "t1", quality: float = 90, duration: int = 100,
         retries: int = 0, acceptance: bool = True, safety: bool = True,
         missed: int = 0, tokens: bool = True, effort: str = "max") -> dict:
    row = {
        "task_id": task_id,
        "task_class": "exploration",
        "model": model,
        "effort": effort,
        "acceptance_pass": acceptance,
        "safety_gate_pass": safety,
        "missed_blocker_high": missed,
        "quality_score": quality,
        "duration_ms": duration,
        "retries": retries,
    }
    if tokens:
        row.update(input_tokens=100_000, cached_input_tokens=20_000, output_tokens=10_000)
    return row


def test_current_luna_credit_formula() -> None:
    benchmark = _module()
    assert benchmark.token_cost(_row("gpt-5.6-luna"), benchmark.CREDIT_RATES) == 0.81


def test_astra_credit_formula_is_two_point_five_times_sol_for_same_tokens() -> None:
    benchmark = _module()
    sol = benchmark.token_cost(_row("gpt-5.6-sol", effort="xhigh"), benchmark.CREDIT_RATES)
    astra = benchmark.token_cost(_row("gpt-6-astra", effort="xhigh"), benchmark.CREDIT_RATES)
    assert sol == 15.2
    assert astra == 38.0
    assert astra / sol == 2.5


def test_cheaper_route_is_excluded_when_safety_or_acceptance_fails() -> None:
    benchmark = _module()
    rows = [
        _row("gpt-5.6-luna", acceptance=False),
        _row("gpt-5.6-terra", task_id="t2", quality=91),
    ]
    result = benchmark.analyze(rows)["task_classes"]["exploration"]
    luna = next(route for route in result["routes"] if route["model"] == "gpt-5.6-luna")
    assert luna["eligible_runs"] == 0
    assert result["pareto_frontier"] == [{"model": "gpt-5.6-terra", "effort": "max"}]


def test_pareto_frontier_keeps_tradeoffs_and_removes_dominated_route() -> None:
    benchmark = _module()
    rows = [
        _row("gpt-5.6-luna", quality=88, duration=80),
        _row("gpt-5.6-terra", task_id="t2", quality=94, duration=90),
        _row("gpt-5.6-sol", task_id="t3", quality=90, duration=120, retries=1),
    ]
    frontier = benchmark.analyze(rows)["task_classes"]["exploration"]["pareto_frontier"]
    assert {item["model"] for item in frontier} == {"gpt-5.6-luna", "gpt-5.6-terra"}


def test_astra_and_sol_both_remain_when_canary_buys_quality_and_latency_at_higher_cost() -> None:
    benchmark = _module()
    rows = [
        _row("gpt-5.6-sol", task_id="hard-1", quality=96, duration=100, effort="xhigh"),
        _row("gpt-6-astra", task_id="hard-1", quality=99, duration=70, effort="xhigh"),
    ]
    result = benchmark.analyze(rows)
    frontier = result["task_classes"]["exploration"]["pareto_frontier"]
    assert {(item["model"], item["effort"]) for item in frontier} == {
        ("gpt-5.6-sol", "xhigh"),
        ("gpt-6-astra", "xhigh"),
    }
    pairing = result["astra_canary_pairing"]["exploration"]
    assert pairing["shared_task_ids"] == ["hard-1"]
    assert pairing["pairing_complete"] is True


def test_astra_pairing_rejects_unequal_historical_task_sets() -> None:
    benchmark = _module()
    rows = [
        _row("gpt-5.6-sol", task_id="hard-1", effort="xhigh"),
        _row("gpt-5.6-sol", task_id="hard-2", effort="xhigh"),
        _row("gpt-6-astra", task_id="hard-1", effort="xhigh"),
    ]
    pairing = benchmark.analyze(rows)["astra_canary_pairing"]["exploration"]
    assert pairing["shared_task_ids"] == ["hard-1"]
    assert pairing["baseline_only"] == ["hard-2"]
    assert pairing["canary_only"] == []
    assert pairing["pairing_complete"] is False


def test_missing_token_observation_never_becomes_false_cost_winner() -> None:
    benchmark = _module()
    rows = [
        _row("gpt-5.6-luna", tokens=False),
        _row("gpt-5.6-terra", task_id="t2"),
    ]
    result = benchmark.analyze(rows)["task_classes"]["exploration"]
    assert result["cost_comparison_status"] == "incomplete"
    luna = next(route for route in result["routes"] if route["model"] == "gpt-5.6-luna")
    assert luna["credits_mean"] is None
    assert {item["model"] for item in result["pareto_frontier"]} == {"gpt-5.6-terra"}


def test_missed_blocker_high_is_hard_ineligibility() -> None:
    benchmark = _module()
    row = _row("gpt-5.6-luna", missed=1)
    assert benchmark.eligible(benchmark.validate(row)) is False

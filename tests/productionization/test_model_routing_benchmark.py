from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVAL_DATE = date(2026, 9, 7)


def _module():
    path = ROOT / "scripts/model_routing_benchmark.py"
    spec = importlib.util.spec_from_file_location("model_routing_benchmark", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(
    model: str,
    *,
    task_id: str = "t1",
    task_class: str = "exploration",
    quality: float = 90,
    duration: int = 100,
    retries: int = 0,
    acceptance: bool = True,
    safety: bool = True,
    missed: int = 0,
    tokens: bool = True,
    effort: str = "max",
) -> dict:
    row = {
        "task_id": task_id,
        "task_class": task_class,
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


def _route_rows(model: str, *, count: int = 5, effort: str = "max", **kwargs) -> list[dict]:
    return [
        _row(model, task_id=f"t{index}", effort=effort, **kwargs)
        for index in range(1, count + 1)
    ]


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


def test_reliability_gate_counts_failed_runs_instead_of_survivorship_filtering() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-5.6-luna", quality=100, duration=20)
    luna[0]["acceptance_pass"] = False
    luna[0]["quality_score"] = 0
    luna[0]["duration_ms"] = 500
    terra = _route_rows("gpt-5.6-terra", quality=91, duration=90)

    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    luna_summary = next(route for route in result["routes"] if route["model"] == "gpt-5.6-luna")
    assert luna_summary["eligible_runs"] == 4
    assert luna_summary["acceptance_rate"] == 0.8
    assert luna_summary["quality_mean"] == 80
    assert luna_summary["duration_ms_mean"] == 116
    assert luna_summary["reliability_eligible"] is False
    assert "acceptance_rate_below_floor" in luna_summary["reliability_reasons"]
    assert result["comparison_status"] == "complete"
    assert result["pareto_frontier"] == [{"model": "gpt-5.6-terra", "effort": "max"}]


def test_safety_failure_and_missed_blocker_are_hard_route_ineligibility() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-5.6-luna")
    luna[0]["safety_gate_pass"] = False
    luna[1]["missed_blocker_high"] = 1
    terra = _route_rows("gpt-5.6-terra")

    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    summary = next(route for route in result["routes"] if route["model"] == "gpt-5.6-luna")
    assert summary["safety_failures"] == 1
    assert summary["missed_blocker_high_total"] == 1
    assert summary["reliability_eligible"] is False
    assert {"safety_failure", "missed_blocker_high"} <= set(summary["reliability_reasons"])
    assert result["pareto_frontier"] == [{"model": "gpt-5.6-terra", "effort": "max"}]


def test_generalized_pairing_rejects_different_task_sets() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-5.6-luna")
    terra = _route_rows("gpt-5.6-terra")
    terra[-1]["task_id"] = "different-task"

    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    pairing = result["comparison_pairing"]
    assert pairing["pairing_complete"] is False
    assert pairing["missing_task_ids"]["gpt-5.6-luna|max"] == ["different-task"]
    assert pairing["missing_task_ids"]["gpt-5.6-terra|max"] == ["t5"]
    assert result["comparison_status"] == "incomplete_pairing"
    assert result["pareto_frontier"] == []


def test_minimum_paired_sample_blocks_single_task_comparison() -> None:
    benchmark = _module()
    rows = [
        _row("gpt-5.6-sol", task_id="hard-1", effort="xhigh"),
        _row("gpt-6-astra", task_id="hard-1", effort="xhigh"),
    ]
    result = benchmark.analyze(rows, evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    assert result["comparison_pairing"]["pairing_complete"] is True
    assert result["comparison_pairing"]["minimum_pairing_met"] is False
    assert result["comparison_status"] == "insufficient_sample"
    assert result["pareto_frontier"] == []


def test_pareto_frontier_uses_five_fully_paired_reliable_tasks() -> None:
    benchmark = _module()
    rows = [
        *_route_rows("gpt-5.6-luna", quality=88, duration=80),
        *_route_rows("gpt-5.6-terra", quality=94, duration=90),
        *_route_rows("gpt-5.6-sol", quality=90, duration=120, retries=1),
    ]
    result = benchmark.analyze(rows, evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    assert result["comparison_status"] == "complete"
    assert {item["model"] for item in result["pareto_frontier"]} == {
        "gpt-5.6-luna",
        "gpt-5.6-terra",
    }
    assert result["promotion_evidence_ready"] is False


def test_astra_and_sol_tradeoff_survives_paired_reliability_gate() -> None:
    benchmark = _module()
    rows = [
        *_route_rows("gpt-5.6-sol", quality=96, duration=100, effort="xhigh"),
        *_route_rows("gpt-6-astra", quality=99, duration=70, effort="xhigh"),
    ]
    result = benchmark.analyze(rows, evaluation_date=EVAL_DATE)
    frontier = result["task_classes"]["exploration"]["pareto_frontier"]
    assert {(item["model"], item["effort"]) for item in frontier} == {
        ("gpt-5.6-sol", "xhigh"),
        ("gpt-6-astra", "xhigh"),
    }
    pairing = result["astra_canary_pairing"]["exploration"]
    assert pairing["shared_task_ids"] == ["t1", "t2", "t3", "t4", "t5"]
    assert pairing["pairing_complete"] is True
    assert result["task_classes"]["exploration"]["promotion_evidence_ready"] is False


def test_missing_token_observation_blocks_cost_frontier_for_all_reliable_routes() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-5.6-luna")
    luna[0].pop("input_tokens")
    luna[0].pop("cached_input_tokens")
    luna[0].pop("output_tokens")
    terra = _route_rows("gpt-5.6-terra")

    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    assert result["comparison_status"] == "incomplete_cost_observation"
    assert result["pareto_frontier"] == []
    luna_summary = next(route for route in result["routes"] if route["model"] == "gpt-5.6-luna")
    assert luna_summary["credits_mean"] is None


def test_stale_or_unchecked_rate_card_blocks_cost_frontier() -> None:
    benchmark = _module()
    rows = [*_route_rows("gpt-5.6-luna"), *_route_rows("gpt-5.6-terra")]

    unchecked = benchmark.analyze(rows)["task_classes"]["exploration"]
    assert unchecked["comparison_status"] == "unchecked_rate_card"
    assert unchecked["pareto_frontier"] == []

    stale_result = benchmark.analyze(rows, evaluation_date=date(2026, 10, 8))
    assert stale_result["rate_card_freshness"]["status"] == "stale"
    stale = stale_result["task_classes"]["exploration"]
    assert stale["comparison_status"] == "stale_rate_card"
    assert stale["pareto_frontier"] == []


def test_promotion_evidence_requires_ten_paired_reliable_routes() -> None:
    benchmark = _module()
    five = [*_route_rows("gpt-5.6-luna"), *_route_rows("gpt-5.6-terra")]
    assert benchmark.analyze(five, evaluation_date=EVAL_DATE)["task_classes"]["exploration"][
        "promotion_evidence_ready"
    ] is False

    ten = [
        *_route_rows("gpt-5.6-luna", count=10),
        *_route_rows("gpt-5.6-terra", count=10),
    ]
    result = benchmark.analyze(ten, evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    assert result["comparison_pairing"]["promotion_sample_target_met"] is True
    assert result["promotion_evidence_ready"] is True


def test_duplicate_route_task_id_is_rejected() -> None:
    benchmark = _module()
    duplicate = _row("gpt-5.6-luna")
    with pytest.raises(ValueError, match="duplicate task_id"):
        benchmark.analyze([duplicate, dict(duplicate)], evaluation_date=EVAL_DATE)


def test_acceptance_floor_is_route_level_not_any_failure_is_absolute() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-5.6-luna", count=20)
    luna[0]["acceptance_pass"] = False
    terra = _route_rows("gpt-5.6-terra", count=20)
    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    summary = next(route for route in result["routes"] if route["model"] == "gpt-5.6-luna")
    assert summary["acceptance_rate"] == 0.95
    assert summary["reliability_eligible"] is True


def test_missed_blocker_high_is_still_per_run_ineligible() -> None:
    benchmark = _module()
    row = _row("gpt-5.6-luna", missed=1)
    assert benchmark.eligible(benchmark.validate(row)) is False

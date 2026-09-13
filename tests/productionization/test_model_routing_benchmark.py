from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVAL_DATE = date(2026, 9, 7)
PROVENANCE_FIELDS = (
    "repository_commit_sha",
    "repository_tree_sha",
    "task_manifest_sha256",
)


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
    row.update(_task_provenance(task_class, task_id))
    if tokens:
        row.update(input_tokens=100_000, cached_input_tokens=20_000, output_tokens=10_000)
    return row


def _route_rows(model: str, *, count: int = 5, effort: str | None = None, **kwargs) -> list[dict]:
    if effort is None:
        effort = {
            "gpt-5.6-luna": "max",
            "gpt-5.6-terra": "medium",
            "gpt-5.6-sol": "high",
            "gpt-6-astra": "xhigh",
        }[model]
    return [
        _row(model, task_id=f"t{index}", effort=effort, **kwargs)
        for index in range(1, count + 1)
    ]


def _task_provenance(task_class: str, task_id: str) -> dict[str, str]:
    """Derive deterministic evidence from the pair whose frozen manifest binds prompt/scope,
    acceptance matrix, and known findings.
    """
    seed = f"{task_class}\0{task_id}".encode()
    return {
        "repository_commit_sha": hashlib.sha1(seed).hexdigest(),
        "repository_tree_sha": hashlib.sha1(b"tree\0" + seed).hexdigest(),
        "task_manifest_sha256": hashlib.sha256(b"manifest\0" + seed).hexdigest(),
    }


def _provenance_row(
    model: str,
    *,
    task_id: str = "t1",
    task_class: str = "exploration",
    effort: str = "max",
    provenance: dict[str, str] | None = None,
    **kwargs,
) -> dict:
    """Build a row with pair-derived provenance; the manifest binds prompt/scope, acceptance matrix,
    and known findings.
    """
    row = _row(model, task_id=task_id, task_class=task_class, effort=effort, **kwargs)
    if provenance is not None:
        row.update(provenance)
    return row


def test_valid_enriched_record_preserves_frozen_task_provenance() -> None:
    benchmark = _module()
    validated = benchmark.validate(_provenance_row("gpt-5.6-luna"))
    expected = _task_provenance("exploration", "t1")
    assert {field: validated[field] for field in expected} == expected


@pytest.mark.parametrize("field", PROVENANCE_FIELDS)
def test_missing_task_provenance_field_is_rejected(field: str) -> None:
    benchmark = _module()
    row = _provenance_row("gpt-5.6-luna")
    del row[field]
    with pytest.raises(ValueError, match="provenance"):
        benchmark.validate(row)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("repository_commit_sha", "A" * 40),
        ("repository_tree_sha", "g" * 40),
        ("task_manifest_sha256", "c" * 63),
    ),
)
def test_malformed_task_provenance_field_is_rejected(field: str, value: str) -> None:
    benchmark = _module()
    row = _provenance_row("gpt-5.6-luna")
    row[field] = value
    with pytest.raises(ValueError, match="provenance"):
        benchmark.validate(row)


def test_same_task_across_routes_requires_identical_provenance() -> None:
    benchmark = _module()
    left = _provenance_row("gpt-5.6-luna", task_id="frozen-task")
    mismatched = dict(_task_provenance("exploration", "frozen-task"), repository_tree_sha="d" * 40)
    right = _provenance_row(
        "gpt-5.6-sol", task_id="frozen-task", effort="high", provenance=mismatched
    )
    with pytest.raises(ValueError, match="provenance"):
        benchmark.analyze([left, right], evaluation_date=EVAL_DATE)


def test_analyze_exposes_validated_task_provenance_for_auditable_output() -> None:
    benchmark = _module()
    rows = [
        _provenance_row("gpt-5.6-luna", task_id="frozen-task"),
        _provenance_row("gpt-5.6-sol", task_id="frozen-task", effort="high"),
    ]
    result = benchmark.analyze(rows, evaluation_date=EVAL_DATE)
    assert result["task_provenance"]["exploration"]["frozen-task"] == _task_provenance(
        "exploration", "frozen-task"
    )


@pytest.mark.parametrize("quality", [float("nan"), float("inf"), float("-inf")])
def test_validate_rejects_non_finite_quality_score(quality: float) -> None:
    benchmark = _module()
    with pytest.raises(ValueError, match="quality_score"):
        benchmark.validate(_row("gpt-5.6-luna", quality=quality))


@pytest.mark.parametrize("quality", [float("nan"), float("inf"), float("-inf")])
def test_load_jsonl_rejects_json_non_finite_quality_score(tmp_path: Path, quality: float) -> None:
    benchmark = _module()
    row = _row("gpt-5.6-luna", quality=quality)
    path = tmp_path / "non-finite.jsonl"
    path.write_text(json.dumps(row, allow_nan=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="quality_score"):
        benchmark.load_jsonl(path)


def test_load_jsonl_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    benchmark = _module()
    encoded = json.dumps(_row("gpt-5.6-luna"))
    duplicate = encoded.replace(
        '{"task_id": "t1"', '{"task_id": "t1", "task_id": "duplicate"', 1
    )
    path = tmp_path / "duplicate.jsonl"
    path.write_text(duplicate + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        benchmark.load_jsonl(path)


_ALLOWED_MODEL_EFFORT_PAIRS = (
    ("gpt-5.6-luna", "max"),
    ("gpt-5.6-terra", "medium"),
    ("gpt-5.6-terra", "high"),
    ("gpt-5.6-terra", "xhigh"),
    ("gpt-5.6-sol", "high"),
    ("gpt-5.6-sol", "xhigh"),
    ("gpt-6-astra", "xhigh"),
)


@pytest.mark.parametrize(("model", "effort"), _ALLOWED_MODEL_EFFORT_PAIRS)
def test_benchmark_matrix_accepts_allowed_model_effort_pairs(model: str, effort: str) -> None:
    benchmark = _module()
    validated = benchmark.validate(_row(model, effort=effort))
    assert (validated["model"], validated["effort"]) == (model, effort)


_DISALLOWED_MODEL_EFFORT_PAIRS = (
    ("gpt-5.6-luna", "medium"),
    ("gpt-5.6-luna", "high"),
    ("gpt-5.6-luna", "xhigh"),
    ("gpt-5.6-terra", "max"),
    ("gpt-5.6-sol", "max"),
    ("gpt-5.6-sol", "medium"),
    ("gpt-6-astra", "max"),
    ("gpt-6-astra", "medium"),
    ("gpt-6-astra", "high"),
)


@pytest.mark.parametrize(("model", "effort"), _DISALLOWED_MODEL_EFFORT_PAIRS)
def test_benchmark_matrix_rejects_disallowed_model_effort_pairs(model: str, effort: str) -> None:
    benchmark = _module()
    with pytest.raises(ValueError, match="effort"):
        benchmark.validate(_row(model, effort=effort))


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
    assert result["pareto_frontier"] == [{"model": "gpt-5.6-terra", "effort": "medium"}]


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
    assert result["pareto_frontier"] == [{"model": "gpt-5.6-terra", "effort": "medium"}]


def test_generalized_pairing_rejects_different_task_sets() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-5.6-luna")
    terra = _route_rows("gpt-5.6-terra")
    terra[-1]["task_id"] = "different-task"

    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    pairing = result["comparison_pairing"]
    assert pairing["pairing_complete"] is False
    assert pairing["missing_task_ids"]["gpt-5.6-luna|max"] == ["different-task"]
    assert pairing["missing_task_ids"]["gpt-5.6-terra|medium"] == ["t5"]
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

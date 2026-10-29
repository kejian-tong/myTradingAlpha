from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVAL_DATE = date(2026, 9, 7)
CURRENT_CARD_ID = "work_codex_standard_2026_10_28"
CURRENT_CARD_DATE = date(2026, 10, 28)
CURRENT_CARD_SOURCE = "https://learn.chatgpt.com/docs/pricing"
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
            "gpt-6-luna": "max",
            "gpt-5.6-terra": "medium",
            "gpt-6-sol": "high",
            "gpt-6.1-sol": "xhigh",
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


def _v2_row(
    model: str,
    *,
    task_id: str = "t1",
    task_class: str = "exploration",
    effort: str = "max",
    task_usage_complete: bool = True,
    pricing_surface: str = "historical_work_codex",
    context_tier: str = "short",
    usage_overrides: dict | None = None,
    **kwargs,
) -> dict:
    row = _provenance_row(
        model,
        task_id=task_id,
        task_class=task_class,
        effort=effort,
        tokens=False,
        **kwargs,
    )
    identity = f"{task_class}\0{task_id}\0{model}\0{effort}".encode()
    usage = {
        "observation_ref": hashlib.sha256(identity).hexdigest(),
        "revision": 0,
        "source_kind": "runtime_report",
        "usage_scope": "task",
        "aggregation_scope": "exclusive",
        "input_tokens": 100_000,
        "cached_input_tokens": 20_000,
        "cache_write_tokens": 0,
        "cache_write_30m_tokens": 0,
        "cache_write_12h_tokens": 0,
        "output_tokens": 10_000,
        "reasoning_output_tokens": 1_000,
    }
    if usage_overrides is not None:
        usage.update(usage_overrides)
    row.update(
        schema_version=2,
        usage=usage,
        task_usage_complete=task_usage_complete,
        pricing_surface=pricing_surface,
        context_tier=context_tier,
    )
    return row


def _v2_route_rows(model: str, *, count: int = 5, effort: str | None = None, **kwargs) -> list[dict]:
    if effort is None:
        effort = {
            "gpt-6-luna": "max",
            "gpt-5.6-terra": "medium",
            "gpt-6-sol": "high",
            "gpt-6.1-sol": "xhigh",
            "gpt-6-astra": "xhigh",
        }[model]
    return [
        _v2_row(model, task_id=f"t{index}", effort=effort, **kwargs)
        for index in range(1, count + 1)
    ]


def test_valid_enriched_record_preserves_frozen_task_provenance() -> None:
    benchmark = _module()
    validated = benchmark.validate(_provenance_row("gpt-6-luna"))
    expected = _task_provenance("exploration", "t1")
    assert {field: validated[field] for field in expected} == expected


@pytest.mark.parametrize("field", PROVENANCE_FIELDS)
def test_missing_task_provenance_field_is_rejected(field: str) -> None:
    benchmark = _module()
    row = _provenance_row("gpt-6-luna")
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
    row = _provenance_row("gpt-6-luna")
    row[field] = value
    with pytest.raises(ValueError, match="provenance"):
        benchmark.validate(row)


def test_same_task_across_routes_requires_identical_provenance() -> None:
    benchmark = _module()
    left = _provenance_row("gpt-6-luna", task_id="frozen-task")
    mismatched = dict(_task_provenance("exploration", "frozen-task"), repository_tree_sha="d" * 40)
    right = _provenance_row(
        "gpt-6-sol", task_id="frozen-task", effort="high", provenance=mismatched
    )
    with pytest.raises(ValueError, match="provenance"):
        benchmark.analyze([left, right], evaluation_date=EVAL_DATE)


def test_analyze_exposes_validated_task_provenance_for_auditable_output() -> None:
    benchmark = _module()
    rows = [
        _provenance_row("gpt-6-luna", task_id="frozen-task"),
        _provenance_row("gpt-6-sol", task_id="frozen-task", effort="high"),
    ]
    result = benchmark.analyze(rows, evaluation_date=EVAL_DATE)
    assert result["task_provenance"]["exploration"]["frozen-task"] == _task_provenance(
        "exploration", "frozen-task"
    )


@pytest.mark.parametrize("quality", [float("nan"), float("inf"), float("-inf")])
def test_validate_rejects_non_finite_quality_score(quality: float) -> None:
    benchmark = _module()
    with pytest.raises(ValueError, match="quality_score"):
        benchmark.validate(_row("gpt-6-luna", quality=quality))


@pytest.mark.parametrize("quality", [float("nan"), float("inf"), float("-inf")])
def test_load_jsonl_rejects_json_non_finite_quality_score(tmp_path: Path, quality: float) -> None:
    benchmark = _module()
    row = _row("gpt-6-luna", quality=quality)
    path = tmp_path / "non-finite.jsonl"
    path.write_text(json.dumps(row, allow_nan=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="quality_score"):
        benchmark.load_jsonl(path)


def test_huge_integer_quality_score_raises_value_error() -> None:
    benchmark = _module()
    with pytest.raises(ValueError, match="quality_score"):
        benchmark.validate(_row("gpt-6-luna", quality=2**1024))


_INTEGER_BOUND_FIELDS = (
    "missed_blocker_high",
    "duration_ms",
    "retries",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
)


@pytest.mark.parametrize("field", _INTEGER_BOUND_FIELDS)
def test_nonnegative_integer_fields_bound_to_signed_64_bit(field: str) -> None:
    benchmark = _module()
    row = _row("gpt-6-luna")
    row[field] = 2**63 - 1
    assert benchmark.validate(row)[field] == 2**63 - 1
    row[field] = 2**63
    with pytest.raises(ValueError, match=field):
        benchmark.validate(row)


def test_load_jsonl_rejects_oversized_integer_with_line_context(tmp_path: Path) -> None:
    benchmark = _module()
    row = _row("gpt-6-luna")
    row["duration_ms"] = 2**63
    path = tmp_path / "oversized-integer.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        benchmark.load_jsonl(path)


def test_load_jsonl_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    benchmark = _module()
    encoded = json.dumps(_row("gpt-6-luna"))
    duplicate = encoded.replace(
        '{"task_id": "t1"', '{"task_id": "t1", "task_id": "duplicate"', 1
    )
    path = tmp_path / "duplicate.jsonl"
    path.write_text(duplicate + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        benchmark.load_jsonl(path)


_ALLOWED_MODEL_EFFORT_PAIRS = (
    ("gpt-6-luna", "max"),
    ("gpt-5.6-terra", "medium"),
    ("gpt-5.6-terra", "high"),
    ("gpt-5.6-terra", "xhigh"),
    ("gpt-6-sol", "high"),
    ("gpt-6-sol", "xhigh"),
    ("gpt-6.1-sol", "xhigh"),
    ("gpt-6-astra", "xhigh"),
)


@pytest.mark.parametrize(("model", "effort"), _ALLOWED_MODEL_EFFORT_PAIRS)
def test_benchmark_matrix_accepts_allowed_model_effort_pairs(model: str, effort: str) -> None:
    benchmark = _module()
    validated = benchmark.validate(_row(model, effort=effort))
    assert (validated["model"], validated["effort"]) == (model, effort)


_DISALLOWED_MODEL_EFFORT_PAIRS = (
    ("gpt-6-luna", "medium"),
    ("gpt-6-luna", "high"),
    ("gpt-6-luna", "xhigh"),
    ("gpt-5.6-terra", "max"),
    ("gpt-6-sol", "max"),
    ("gpt-6-sol", "medium"),
    ("gpt-6.1-sol", "high"),
    ("gpt-6.1-sol", "medium"),
    ("gpt-6.1-sol", "max"),
    ("gpt-6-astra", "max"),
    ("gpt-6-astra", "medium"),
    ("gpt-6-astra", "high"),
)


@pytest.mark.parametrize(("model", "effort"), _DISALLOWED_MODEL_EFFORT_PAIRS)
def test_benchmark_matrix_rejects_disallowed_model_effort_pairs(model: str, effort: str) -> None:
    benchmark = _module()
    with pytest.raises(ValueError, match="effort"):
        benchmark.validate(_row(model, effort=effort))


@pytest.mark.parametrize(
    ("model", "effort"),
    (
        ("gpt-5.6-luna", "max"),
        ("gpt-5.6-sol", "high"),
        ("gpt-5.6-sol", "xhigh"),
    ),
)
def test_benchmark_matrix_rejects_retired_active_model_ids(model: str, effort: str) -> None:
    benchmark = _module()
    with pytest.raises(ValueError, match="model"):
        benchmark.validate(_row(model, effort=effort))


@pytest.mark.parametrize(
    ("model", "effort"),
    (("gpt-6-luna-max", "max"), ("gpt-6-sol-xhigh", "xhigh")),
)
def test_benchmark_matrix_rejects_invented_combined_model_ids(model: str, effort: str) -> None:
    benchmark = _module()
    with pytest.raises(ValueError, match="model"):
        benchmark.validate(_row(model, effort=effort))


def test_current_luna_credit_formula() -> None:
    benchmark = _module()
    assert benchmark.token_cost(_row("gpt-6-luna"), benchmark.CREDIT_RATES) == 0.81


def test_v2_inclusive_input_is_priced_once_while_legacy_formula_stays_frozen() -> None:
    benchmark = _module()
    legacy = _row("gpt-6-luna")
    inclusive = _v2_row("gpt-6-luna")

    assert benchmark.token_cost(legacy, benchmark.CREDIT_RATES) == 0.81
    assert benchmark.token_cost(inclusive, benchmark.CREDIT_RATES) == pytest.approx(0.71)
    assert benchmark.validate(inclusive)["usage"]["reasoning_output_tokens"] == 1_000


@pytest.mark.parametrize(
    ("model", "effort", "expected_credits"),
    (
        ("gpt-6-luna", "max", 0.33),
        ("gpt-5.6-terra", "medium", 7.1),
        ("gpt-6-sol", "high", 6.6),
        ("gpt-6.1-sol", "xhigh", 6.55),
        ("gpt-6-astra", "xhigh", 33.0),
    ),
)
def test_dated_work_standard_card_prices_current_v2_usage_without_rewriting_history(
    model: str,
    effort: str,
    expected_credits: float,
) -> None:
    benchmark = _module()
    current = _v2_row(
        model,
        effort=effort,
        pricing_surface=CURRENT_CARD_ID,
    )

    result = benchmark.analyze([current], evaluation_date=CURRENT_CARD_DATE)
    route = result["task_classes"]["exploration"]["routes"][0]

    assert result["pricing_surface"] == CURRENT_CARD_ID
    assert result["rate_card_as_of"] == CURRENT_CARD_DATE.isoformat()
    assert result["credit_rate_source"] == CURRENT_CARD_SOURCE
    assert route["credits_mean"] == pytest.approx(expected_credits)
    assert route["cost_observation_complete"] is True
    assert route["usd_mean"] is None
    assert route["usd_cost_observation_complete"] is False
    assert benchmark.token_cost(_row("gpt-6-luna"), benchmark.CREDIT_RATES) == 0.81
    assert benchmark.token_cost(
        _v2_row("gpt-6-luna"), benchmark.CREDIT_RATES
    ) == pytest.approx(0.71)


def test_current_card_does_not_charge_cache_writes_twice() -> None:
    benchmark = _module()
    without_writes = _v2_row(
        "gpt-6-luna",
        pricing_surface=CURRENT_CARD_ID,
    )
    with_inclusive_writes = _v2_row(
        "gpt-6-luna",
        pricing_surface=CURRENT_CARD_ID,
        usage_overrides={
            "cache_write_tokens": 1_000,
            "cache_write_30m_tokens": 600,
            "cache_write_12h_tokens": 400,
        },
    )

    no_write_result = benchmark.analyze([without_writes], evaluation_date=CURRENT_CARD_DATE)
    write_result = benchmark.analyze([with_inclusive_writes], evaluation_date=CURRENT_CARD_DATE)

    assert (
        no_write_result["task_classes"]["exploration"]["routes"][0]["credits_mean"]
        == pytest.approx(0.33)
    )
    assert (
        write_result["task_classes"]["exploration"]["routes"][0]["credits_mean"]
        == pytest.approx(0.33)
    )


@pytest.mark.parametrize(
    ("evaluation_date", "age_days", "status", "fresh"),
    (
        (date(2026, 10, 27), -1, "evaluation_precedes_rate_card", False),
        (date(2026, 10, 28), 0, "fresh", True),
        (date(2026, 11, 27), 30, "fresh", True),
        (date(2026, 11, 28), 31, "stale", False),
    ),
)
def test_current_card_has_independent_as_of_date_and_freshness(
    evaluation_date: date,
    age_days: int,
    status: str,
    fresh: bool,
) -> None:
    benchmark = _module()
    row = _v2_row("gpt-6-luna", pricing_surface=CURRENT_CARD_ID)

    result = benchmark.analyze([row], evaluation_date=evaluation_date)

    assert result["rate_card_as_of"] == CURRENT_CARD_DATE.isoformat()
    assert result["rate_card_freshness"] == {
        "as_of": CURRENT_CARD_DATE.isoformat(),
        "evaluation_date": evaluation_date.isoformat(),
        "age_days": age_days,
        "max_age_days": 30,
        "status": status,
        "fresh": fresh,
    }


def test_known_card_mixture_is_rejected_before_pricing_or_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _module()
    rows = [
        _v2_row("gpt-6-luna", pricing_surface="historical_work_codex"),
        _v2_row("gpt-6-luna", task_id="t2", pricing_surface=CURRENT_CARD_ID),
    ]
    calculations: list[str] = []
    original_eligible = benchmark.eligible
    original_token_cost = benchmark.token_cost

    def observed_eligible(*args, **kwargs):
        calculations.append("eligible")
        return original_eligible(*args, **kwargs)

    def observed_token_cost(*args, **kwargs):
        calculations.append("token_cost")
        return original_token_cost(*args, **kwargs)

    monkeypatch.setattr(benchmark, "eligible", observed_eligible)
    monkeypatch.setattr(benchmark, "token_cost", observed_token_cost)

    with pytest.raises(ValueError, match="pricing surfaces") as error:
        benchmark.analyze(rows, evaluation_date=CURRENT_CARD_DATE)

    assert calculations == []
    assert CURRENT_CARD_ID not in str(error.value)


@pytest.mark.parametrize("tier", ["long", "mixed"])
def test_current_sol_long_and_mixed_contexts_use_subscription_credit_rates(tier: str) -> None:
    benchmark = _module()
    row = _v2_row(
        "gpt-6.1-sol",
        effort="xhigh",
        pricing_surface=CURRENT_CARD_ID,
        context_tier=tier,
    )

    result = benchmark.analyze([row], evaluation_date=CURRENT_CARD_DATE)
    route = result["task_classes"]["exploration"]["routes"][0]

    assert route["credits_mean"] == pytest.approx(6.55)
    assert route["usd_mean"] is None
    assert route["usd_cost_observation_complete"] is False


@pytest.mark.parametrize(("model", "effort"), (("gpt-6-luna", "max"), ("gpt-5.6-terra", "medium")))
@pytest.mark.parametrize("tier", ["long", "mixed", "unknown"])
def test_unverified_long_tiers_remain_unpriced(
    model: str,
    effort: str,
    tier: str,
) -> None:
    benchmark = _module()
    row = _v2_row(
        model,
        effort=effort,
        pricing_surface=CURRENT_CARD_ID,
        context_tier=tier,
    )

    result = benchmark.analyze([row], evaluation_date=CURRENT_CARD_DATE)
    route = result["task_classes"]["exploration"]["routes"][0]

    assert route["credits_mean"] is None
    assert route["usd_mean"] is None
    assert route["cost_observation_complete"] is False
    assert route["usd_cost_observation_complete"] is False


def test_current_card_retains_failed_runs_and_blocks_false_frontier() -> None:
    benchmark = _module()
    luna = _v2_route_rows(
        "gpt-6-luna",
        pricing_surface=CURRENT_CARD_ID,
        quality=100,
        duration=20,
    )
    luna[0]["acceptance_pass"] = False
    luna[0]["quality_score"] = 0
    luna[0]["duration_ms"] = 500
    terra = _v2_route_rows(
        "gpt-5.6-terra",
        pricing_surface=CURRENT_CARD_ID,
        quality=91,
        duration=90,
    )
    terra[-1]["usage"]["aggregation_scope"] = "includes_children"

    result = benchmark.analyze([*luna, *terra], evaluation_date=CURRENT_CARD_DATE)[
        "task_classes"]["exploration"]
    luna_route = next(route for route in result["routes"] if route["model"] == "gpt-6-luna")
    terra_route = next(route for route in result["routes"] if route["model"] == "gpt-5.6-terra")

    assert luna_route["runs"] == 5
    assert luna_route["eligible_runs"] == 4
    assert luna_route["quality_mean"] == 80
    assert luna_route["reliability_eligible"] is False
    assert luna_route["reliability_reasons"] == ["acceptance_rate_below_floor"]
    assert terra_route["runs"] == 5
    assert terra_route["cost_observation_complete"] is False
    assert result["comparison_status"] == "incomplete_cost_observation"
    assert result["pareto_frontier"] == []


def test_analyze_rejects_hostile_list_and_over_limit_before_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _module()
    callbacks: list[str] = []

    class HostileList(list):
        def __iter__(self):
            callbacks.append("iter")
            return super().__iter__()

        def __len__(self):
            callbacks.append("len")
            return super().__len__()

    def unexpected_validation(_row):
        callbacks.append("validate")
        raise AssertionError("validation ran before public collection admission")

    monkeypatch.setattr(benchmark, "validate", unexpected_validation)

    with pytest.raises(ValueError):
        benchmark.analyze(HostileList([{}]), evaluation_date=CURRENT_CARD_DATE)
    assert callbacks == []

    with pytest.raises(ValueError) as error:
        benchmark.analyze([{}] * 10_001, evaluation_date=CURRENT_CARD_DATE)
    assert callbacks == []
    assert "10,001" not in str(error.value)
    assert len(str(error.value)) <= 256


def test_analyze_accepts_the_10000_record_boundary_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _module()
    validated: list[object] = []

    def stop_at_first_validation(row):
        validated.append(row)
        raise ValueError("bounded validation probe")

    monkeypatch.setattr(benchmark, "validate", stop_at_first_validation)
    with pytest.raises(ValueError, match="bounded validation probe"):
        benchmark.analyze([{}] * 10_000, evaluation_date=CURRENT_CARD_DATE)
    assert len(validated) == 1


def test_analyze_rejects_hostile_date_before_date_callbacks() -> None:
    benchmark = _module()
    callbacks: list[str] = []
    sentinel = "PRIVATE_DATE_SENTINEL"

    class HostileDate(date):
        def isoformat(self) -> str:
            callbacks.append("isoformat")
            return sentinel

        def __sub__(self, other):
            callbacks.append("sub")
            raise AssertionError(sentinel)

    with pytest.raises(ValueError) as error:
        benchmark.analyze([], evaluation_date=HostileDate(2026, 10, 28))

    assert callbacks == []
    assert sentinel not in str(error.value)
    assert len(str(error.value)) <= 256


def test_invalid_pricing_surface_error_does_not_echo_private_input() -> None:
    benchmark = _module()
    sentinel = "PRIVATE_PRICING_SURFACE_SENTINEL"
    row = _v2_row("gpt-6-luna", pricing_surface=sentinel)

    with pytest.raises(ValueError) as error:
        benchmark.analyze([row], evaluation_date=CURRENT_CARD_DATE)

    assert sentinel not in str(error.value)
    assert len(str(error.value)) <= 256


def test_v2_benchmark_rejects_legacy_flat_token_fields_and_non_boolean_completeness() -> None:
    benchmark = _module()
    mixed_flat_fields = _v2_row("gpt-6-luna")
    mixed_flat_fields.update(input_tokens=100_000, cached_input_tokens=20_000, output_tokens=10_000)
    with pytest.raises(ValueError, match="schema"):
        benchmark.validate(mixed_flat_fields)

    non_boolean = _v2_row("gpt-6-luna", task_usage_complete=1)
    with pytest.raises(ValueError, match="task_usage_complete"):
        benchmark.validate(non_boolean)


@pytest.mark.parametrize(
    ("overrides", "complete", "surface", "tier"),
    (
        ({"usage_scope": "request"}, False, "historical_work_codex", "short"),
        ({"usage_scope": "turn"}, False, "historical_work_codex", "short"),
        ({"usage_scope": "agent"}, False, "historical_work_codex", "short"),
        ({"cache_write_tokens": 1, "cache_write_30m_tokens": 1}, True, "historical_work_codex", "short"),
        ({"cache_write_tokens": None}, True, "historical_work_codex", "short"),
        ({"aggregation_scope": "includes_children"}, True, "historical_work_codex", "short"),
        ({"aggregation_scope": "unknown"}, True, "historical_work_codex", "short"),
        ({"input_tokens": None}, True, "historical_work_codex", "short"),
        ({}, True, "unknown", "short"),
        ({}, True, "historical_work_codex", "long"),
        ({}, True, "historical_work_codex", "mixed"),
    ),
)
def test_v2_non_whole_task_or_unknown_consumption_is_unpriced(
    overrides: dict,
    complete: bool,
    surface: str,
    tier: str,
) -> None:
    benchmark = _module()
    row = _v2_row(
        "gpt-6-luna",
        task_usage_complete=complete,
        pricing_surface=surface,
        context_tier=tier,
        usage_overrides=overrides,
    )
    assert benchmark.validate(row)["schema_version"] == 2
    assert benchmark.token_cost(row, benchmark.CREDIT_RATES) is None


@pytest.mark.parametrize(("input_tokens", "should_reject"), ((272_000, False), (272_001, True)))
def test_request_scope_exposure_boundary_applies_before_pricing(
    input_tokens: int,
    should_reject: bool,
) -> None:
    benchmark = _module()
    row = _v2_row(
        "gpt-6-luna",
        task_usage_complete=False,
        usage_overrides={"usage_scope": "request", "input_tokens": input_tokens},
    )
    if should_reject:
        with pytest.raises(ValueError, match="272000"):
            benchmark.validate(row)
    else:
        assert benchmark.token_cost(benchmark.validate(row), benchmark.CREDIT_RATES) is None


def test_request_level_consumption_cannot_create_cheaper_whole_task_frontier() -> None:
    benchmark = _module()
    whole_task = _v2_route_rows("gpt-6-luna", quality=90, duration=100)
    single_request = _v2_route_rows(
        "gpt-5.6-terra",
        quality=99,
        duration=1,
        usage_overrides={
            "usage_scope": "request",
            "input_tokens": 1_000,
            "cached_input_tokens": 0,
            "output_tokens": 100,
            "reasoning_output_tokens": 50,
        },
        task_usage_complete=False,
    )

    result = benchmark.analyze(
        [*whole_task, *single_request],
        evaluation_date=EVAL_DATE,
    )["task_classes"]["exploration"]
    assert result["comparison_status"] == "incomplete_cost_observation"
    assert result["pareto_frontier"] == []
    terra = next(route for route in result["routes"] if route["model"] == "gpt-5.6-terra")
    assert terra["credits_mean"] is None
    assert terra["cost_observation_complete"] is False


def test_mixed_legacy_and_v2_comparison_is_rejected_without_normalization() -> None:
    benchmark = _module()
    legacy = _route_rows("gpt-6-luna")
    versioned = _v2_route_rows("gpt-5.6-terra")
    with pytest.raises(ValueError, match="mixed schema"):
        benchmark.analyze([*legacy, *versioned], evaluation_date=EVAL_DATE)


def test_astra_credit_formula_is_two_point_five_times_sol_for_same_tokens() -> None:
    benchmark = _module()
    sol = benchmark.token_cost(_row("gpt-6-sol", effort="xhigh"), benchmark.CREDIT_RATES)
    astra = benchmark.token_cost(_row("gpt-6-astra", effort="xhigh"), benchmark.CREDIT_RATES)
    assert sol == 15.2
    assert astra == 38.0
    assert astra / sol == 2.5


def test_reliability_gate_counts_failed_runs_instead_of_survivorship_filtering() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-6-luna", quality=100, duration=20)
    luna[0]["acceptance_pass"] = False
    luna[0]["quality_score"] = 0
    luna[0]["duration_ms"] = 500
    terra = _route_rows("gpt-5.6-terra", quality=91, duration=90)

    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    luna_summary = next(route for route in result["routes"] if route["model"] == "gpt-6-luna")
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
    luna = _route_rows("gpt-6-luna")
    luna[0]["safety_gate_pass"] = False
    luna[1]["missed_blocker_high"] = 1
    terra = _route_rows("gpt-5.6-terra")

    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    summary = next(route for route in result["routes"] if route["model"] == "gpt-6-luna")
    assert summary["safety_failures"] == 1
    assert summary["missed_blocker_high_total"] == 1
    assert summary["reliability_eligible"] is False
    assert {"safety_failure", "missed_blocker_high"} <= set(summary["reliability_reasons"])
    assert result["pareto_frontier"] == [{"model": "gpt-5.6-terra", "effort": "medium"}]


def test_generalized_pairing_rejects_different_task_sets() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-6-luna")
    terra = _route_rows("gpt-5.6-terra")
    terra[-1]["task_id"] = "different-task"

    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    pairing = result["comparison_pairing"]
    assert pairing["pairing_complete"] is False
    assert pairing["missing_task_ids"]["gpt-6-luna|max"] == ["different-task"]
    assert pairing["missing_task_ids"]["gpt-5.6-terra|medium"] == ["t5"]
    assert result["comparison_status"] == "incomplete_pairing"
    assert result["pareto_frontier"] == []


def test_minimum_paired_sample_blocks_single_task_comparison() -> None:
    benchmark = _module()
    rows = [
        _row("gpt-6-sol", task_id="hard-1", effort="xhigh"),
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
        *_route_rows("gpt-6-luna", quality=88, duration=80),
        *_route_rows("gpt-5.6-terra", quality=94, duration=90),
        *_route_rows("gpt-6-sol", quality=90, duration=120, retries=1),
    ]
    result = benchmark.analyze(rows, evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    assert result["comparison_status"] == "complete"
    assert {item["model"] for item in result["pareto_frontier"]} == {
        "gpt-6-luna",
        "gpt-5.6-terra",
    }
    assert result["promotion_evidence_ready"] is False


def test_astra_and_sol_tradeoff_survives_paired_reliability_gate() -> None:
    benchmark = _module()
    rows = [
        *_route_rows("gpt-6-sol", quality=96, duration=100, effort="xhigh"),
        *_route_rows("gpt-6-astra", quality=99, duration=70, effort="xhigh"),
    ]
    result = benchmark.analyze(rows, evaluation_date=EVAL_DATE)
    frontier = result["task_classes"]["exploration"]["pareto_frontier"]
    assert {(item["model"], item["effort"]) for item in frontier} == {
        ("gpt-6-sol", "xhigh"),
        ("gpt-6-astra", "xhigh"),
    }
    pairing = result["astra_canary_pairing"]["exploration"]
    assert pairing["shared_task_ids"] == ["t1", "t2", "t3", "t4", "t5"]
    assert pairing["pairing_complete"] is True
    assert result["task_classes"]["exploration"]["promotion_evidence_ready"] is False


def test_current_sol_and_astra_pair_is_supported_but_unpriced() -> None:
    benchmark = _module()
    rows = [
        *_route_rows("gpt-6.1-sol", effort="xhigh"),
        *_route_rows("gpt-6-astra", effort="xhigh"),
    ]

    result = benchmark.analyze(rows, evaluation_date=EVAL_DATE)
    task_class = result["task_classes"]["exploration"]
    assert task_class["comparison_status"] == "unknown_route_pricing"
    assert task_class["cost_comparison_status"] == "unknown_route_pricing"
    assert task_class["pareto_frontier"] == []
    assert task_class["promotion_evidence_ready"] is False
    sol_summary = next(route for route in task_class["routes"] if route["model"] == "gpt-6.1-sol")
    astra_summary = next(route for route in task_class["routes"] if route["model"] == "gpt-6-astra")
    assert sol_summary["credits_mean"] is None
    assert sol_summary["usd_mean"] is None
    assert sol_summary["cost_observation_complete"] is False
    assert astra_summary["credits_mean"] is not None
    assert astra_summary["usd_mean"] is not None
    assert astra_summary["cost_observation_complete"] is True
    sol_rows = [row for row in rows if row["model"] == "gpt-6.1-sol"]
    assert all(
        benchmark.token_cost(row, benchmark.CREDIT_RATES) is None
        and benchmark.token_cost(row, benchmark.USD_RATES) is None
        for row in sol_rows
    )
    pairing = result["astra_canary_pairing"]["exploration"]
    assert pairing["shared_task_ids"] == ["t1", "t2", "t3", "t4", "t5"]
    assert pairing["pairing_complete"] is True


def test_historical_and_current_astra_pairings_remain_separate() -> None:
    benchmark = _module()
    rows = [
        _row("gpt-6-sol", task_id="historical-1", effort="xhigh"),
        _row("gpt-6-astra", task_id="historical-1", effort="xhigh"),
        _row("gpt-6.1-sol", task_id="current-1", effort="xhigh"),
        _row("gpt-6-astra", task_id="current-1", effort="xhigh"),
    ]

    pairings = benchmark.analyze(rows, evaluation_date=EVAL_DATE)["astra_canary_pairing"]["exploration"]
    assert pairings["shared_task_ids"] == ["historical-1"]
    assert pairings["current_route_pairing"]["shared_task_ids"] == ["current-1"]


def test_missing_token_observation_blocks_cost_frontier_for_all_reliable_routes() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-6-luna")
    luna[0].pop("input_tokens")
    luna[0].pop("cached_input_tokens")
    luna[0].pop("output_tokens")
    terra = _route_rows("gpt-5.6-terra")

    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    assert result["comparison_status"] == "incomplete_cost_observation"
    assert result["pareto_frontier"] == []
    luna_summary = next(route for route in result["routes"] if route["model"] == "gpt-6-luna")
    assert luna_summary["credits_mean"] is None


def test_stale_or_unchecked_rate_card_blocks_cost_frontier() -> None:
    benchmark = _module()
    rows = [*_route_rows("gpt-6-luna"), *_route_rows("gpt-5.6-terra")]

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
    five = [*_route_rows("gpt-6-luna"), *_route_rows("gpt-5.6-terra")]
    assert benchmark.analyze(five, evaluation_date=EVAL_DATE)["task_classes"]["exploration"][
        "promotion_evidence_ready"
    ] is False

    ten = [
        *_route_rows("gpt-6-luna", count=10),
        *_route_rows("gpt-5.6-terra", count=10),
    ]
    result = benchmark.analyze(ten, evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    assert result["comparison_pairing"]["promotion_sample_target_met"] is True
    assert result["promotion_evidence_ready"] is True


def test_duplicate_route_task_id_is_rejected() -> None:
    benchmark = _module()
    duplicate = _row("gpt-6-luna")
    with pytest.raises(ValueError, match="duplicate task_id"):
        benchmark.analyze([duplicate, dict(duplicate)], evaluation_date=EVAL_DATE)


def test_acceptance_floor_is_route_level_not_any_failure_is_absolute() -> None:
    benchmark = _module()
    luna = _route_rows("gpt-6-luna", count=20)
    luna[0]["acceptance_pass"] = False
    terra = _route_rows("gpt-5.6-terra", count=20)
    result = benchmark.analyze([*luna, *terra], evaluation_date=EVAL_DATE)["task_classes"]["exploration"]
    summary = next(route for route in result["routes"] if route["model"] == "gpt-6-luna")
    assert summary["acceptance_rate"] == 0.95
    assert summary["reliability_eligible"] is True


def test_missed_blocker_high_is_still_per_run_ineligible() -> None:
    benchmark = _module()
    row = _row("gpt-6-luna", missed=1)
    assert benchmark.eligible(benchmark.validate(row)) is False


@pytest.mark.parametrize("identity_field", ("task_id", "task_class", "model", "effort"))
@pytest.mark.parametrize("reuse", ("identical", "conflicting", "higher_revision"))
def test_r2_v2_observation_cannot_supply_different_run_identities(
    monkeypatch, identity_field: str, reuse: str
) -> None:
    benchmark = _module()
    rows = [
        *_v2_route_rows("gpt-5.6-terra", effort="high"),
        *_v2_route_rows("gpt-6-sol", effort="high"),
    ]
    source = rows[0]
    if identity_field == "task_id":
        target = rows[1]
    elif identity_field == "model":
        target = rows[5]
    elif identity_field == "effort":
        other_effort = _v2_route_rows("gpt-5.6-terra", effort="xhigh")
        rows.extend(other_effort)
        target = other_effort[0]
    else:
        other_class = [
            *_v2_route_rows("gpt-5.6-terra", effort="high", task_class="review"),
            *_v2_route_rows("gpt-6-sol", effort="high", task_class="review"),
        ]
        rows.extend(other_class)
        target = other_class[0]
    target["usage"] = dict(source["usage"])
    if reuse == "conflicting":
        target["usage"]["input_tokens"] += 1
    elif reuse == "higher_revision":
        target["usage"]["revision"] += 1

    calculations = []
    for name in ("eligible", "token_cost"):
        original = getattr(benchmark, name)

        def observed(*args, _name=name, _original=original, **kwargs):
            calculations.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(benchmark, name, observed)

    with pytest.raises(ValueError) as error:
        benchmark.analyze(rows, evaluation_date=EVAL_DATE)
    assert calculations == [], "shared evidence reached sample eligibility or pricing"
    assert source["usage"]["observation_ref"] not in str(error.value)
    assert all(row["task_id"] not in str(error.value) for row in rows)
    assert len(str(error.value)) <= 256


def test_r2_unique_v2_observations_keep_complete_pairing_and_duplicate_row_rejection() -> None:
    benchmark = _module()
    rows = [*_v2_route_rows("gpt-6-luna"), *_v2_route_rows("gpt-5.6-terra")]
    assert len({row["usage"]["observation_ref"] for row in rows}) == len(rows)

    result = benchmark.analyze(rows, evaluation_date=EVAL_DATE)["task_classes"]["exploration"]

    assert result["comparison_status"] == "complete"
    assert all(route["runs"] == route["eligible_runs"] == 5 for route in result["routes"])
    assert result["pareto_frontier"] == [{"model": "gpt-6-luna", "effort": "max"}]
    with pytest.raises(ValueError, match="duplicate task_id"):
        benchmark.analyze([*rows, rows[0]], evaluation_date=EVAL_DATE)

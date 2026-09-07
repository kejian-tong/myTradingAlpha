"""Evaluate Codex model routes with paired, reliability-first Pareto analysis.

Input is JSONL with one benchmark-run record per line. This tool never invokes a
model, changes routing, or grants merge authority; it evaluates supplied evidence.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import fmean

RATE_CARD_AS_OF = "2026-09-07"
RATE_CARD_MAX_AGE_DAYS = 30
MIN_PAIRED_TASKS = 5
PROMOTION_TASK_TARGET = 10
MIN_ACCEPTANCE_RATE = 0.95
CREDIT_RATE_SOURCE = "https://help.openai.com/en/articles/11481834"
USD_RATE_SOURCE = "https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing"

# Current ChatGPT Work/Codex token-based credits per 1M tokens.
CREDIT_RATES = {
    "gpt-5.6-luna": {"input": 5.0, "cached_input": 0.5, "output": 30.0},
    "gpt-5.6-terra": {"input": 50.0, "cached_input": 5.0, "output": 300.0},
    "gpt-5.6-sol": {"input": 100.0, "cached_input": 10.0, "output": 500.0},
    "gpt-6-astra": {"input": 250.0, "cached_input": 25.0, "output": 1250.0},
}

# Enterprise token-based USD rates per 1M tokens, used only when useful for comparison.
USD_RATES = {
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "cached_input": 0.20, "output": 12.00},
    "gpt-5.6-sol": {"input": 4.00, "cached_input": 0.40, "output": 20.00},
    "gpt-6-astra": {"input": 10.00, "cached_input": 1.00, "output": 50.00},
}

_MODELS = frozenset(CREDIT_RATES)
_TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens")
_REQUIRED = {
    "task_id", "task_class", "model", "effort", "acceptance_pass", "safety_gate_pass",
    "missed_blocker_high", "quality_score", "duration_ms", "retries",
}
_OPTIONAL = set(_TOKEN_FIELDS)


def _number(value: object, *, name: str) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def validate(record: object) -> dict:
    if type(record) is not dict:
        raise ValueError("benchmark record must be an object")
    keys = set(record)
    if not keys >= _REQUIRED or not keys <= (_REQUIRED | _OPTIONAL):
        raise ValueError("benchmark record fields differ from reviewed schema")
    for key in ("task_id", "task_class", "model", "effort"):
        if type(record[key]) is not str or not record[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if record["model"] not in _MODELS:
        raise ValueError("model is not in the routing benchmark set")
    for key in ("acceptance_pass", "safety_gate_pass"):
        if type(record[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    for key in ("missed_blocker_high", "duration_ms", "retries"):
        if type(record[key]) is not int or isinstance(record[key], bool) or record[key] < 0:
            raise ValueError(f"{key} must be a non-negative integer")
    quality = _number(record["quality_score"], name="quality_score")
    if quality > 100:
        raise ValueError("quality_score must be <= 100")
    present_tokens = [key in record for key in _TOKEN_FIELDS]
    if any(present_tokens) and not all(present_tokens):
        raise ValueError("token observations must provide input/cached/output together")
    if all(present_tokens):
        for key in _TOKEN_FIELDS:
            if type(record[key]) is not int or isinstance(record[key], bool) or record[key] < 0:
                raise ValueError(f"{key} must be a non-negative integer")
    return dict(record)


def eligible(record: dict) -> bool:
    """Return per-run correctness/safety eligibility for diagnostics."""
    return (
        record["acceptance_pass"] is True
        and record["safety_gate_pass"] is True
        and record["missed_blocker_high"] == 0
    )


def token_cost(record: dict, rates: dict[str, dict[str, float]]) -> float | None:
    if not all(key in record for key in _TOKEN_FIELDS):
        return None
    model_rates = rates[record["model"]]
    return (
        record["input_tokens"] / 1_000_000 * model_rates["input"]
        + record["cached_input_tokens"] / 1_000_000 * model_rates["cached_input"]
        + record["output_tokens"] / 1_000_000 * model_rates["output"]
    )


def _aggregate(rows: list[dict]) -> dict:
    """Aggregate every end-to-end task run so failures cannot disappear from route economics."""
    run_count = len(rows)
    eligible_count = sum(eligible(row) for row in rows)
    acceptance_count = sum(row["acceptance_pass"] is True for row in rows)
    safety_failures = sum(row["safety_gate_pass"] is False for row in rows)
    missed_blocker_high_total = sum(row["missed_blocker_high"] for row in rows)
    acceptance_rate = acceptance_count / run_count
    costs = [token_cost(row, CREDIT_RATES) for row in rows]
    usd = [token_cost(row, USD_RATES) for row in rows]
    cost_complete = all(value is not None for value in costs)

    reliability_reasons = []
    if run_count < MIN_PAIRED_TASKS:
        reliability_reasons.append("insufficient_sample")
    if acceptance_rate < MIN_ACCEPTANCE_RATE:
        reliability_reasons.append("acceptance_rate_below_floor")
    if safety_failures:
        reliability_reasons.append("safety_failure")
    if missed_blocker_high_total:
        reliability_reasons.append("missed_blocker_high")

    return {
        "runs": run_count,
        "eligible_runs": eligible_count,
        "ineligible_runs": run_count - eligible_count,
        "acceptance_rate": acceptance_rate,
        "safety_failures": safety_failures,
        "missed_blocker_high_total": missed_blocker_high_total,
        "reliability_eligible": not reliability_reasons,
        "reliability_reasons": reliability_reasons,
        "quality_mean": fmean(row["quality_score"] for row in rows),
        "duration_ms_mean": fmean(row["duration_ms"] for row in rows),
        "retries_mean": fmean(row["retries"] for row in rows),
        "credits_mean": fmean(value for value in costs if value is not None) if cost_complete else None,
        "usd_mean": fmean(value for value in usd if value is not None) if cost_complete else None,
        "cost_observation_complete": cost_complete,
    }


def _dominates(left: dict, right: dict) -> bool:
    higher_or_equal_quality = left["quality_mean"] >= right["quality_mean"]
    lower_or_equal_time = left["duration_ms_mean"] <= right["duration_ms_mean"]
    lower_or_equal_retries = left["retries_mean"] <= right["retries_mean"]
    lower_or_equal_cost = left["credits_mean"] <= right["credits_mean"]
    strictly_better = (
        left["quality_mean"] > right["quality_mean"]
        or left["duration_ms_mean"] < right["duration_ms_mean"]
        or left["retries_mean"] < right["retries_mean"]
        or left["credits_mean"] < right["credits_mean"]
    )
    return higher_or_equal_quality and lower_or_equal_time and lower_or_equal_retries and lower_or_equal_cost and strictly_better


def _route_key(model: str, effort: str) -> str:
    return f"{model}|{effort}"


def _comparison_pairing(rows: list[dict]) -> dict[str, dict]:
    by_class: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        key = _route_key(row["model"], row["effort"])
        by_class[row["task_class"]][key].add(row["task_id"])

    result = {}
    for task_class, route_ids in sorted(by_class.items()):
        sets = list(route_ids.values())
        all_ids = set().union(*sets) if sets else set()
        shared = set.intersection(*sets) if sets else set()
        pairing_complete = len(sets) >= 2 and bool(shared) and all(ids == sets[0] for ids in sets[1:])
        result[task_class] = {
            "route_task_ids": {key: sorted(ids) for key, ids in sorted(route_ids.items())},
            "shared_task_ids": sorted(shared),
            "all_task_ids": sorted(all_ids),
            "missing_task_ids": {
                key: sorted(all_ids - ids) for key, ids in sorted(route_ids.items())
            },
            "pairing_complete": pairing_complete,
            "paired_task_count": len(shared),
            "minimum_paired_tasks": MIN_PAIRED_TASKS,
            "minimum_pairing_met": pairing_complete and len(shared) >= MIN_PAIRED_TASKS,
            "promotion_task_target": PROMOTION_TASK_TARGET,
            "promotion_sample_target_met": pairing_complete and len(shared) >= PROMOTION_TASK_TARGET,
        }
    return result


def _astra_pairing(rows: list[dict]) -> dict[str, dict]:
    by_class: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"sol_xhigh": set(), "astra_xhigh": set()})
    for row in rows:
        key = None
        if (row["model"], row["effort"]) == ("gpt-5.6-sol", "xhigh"):
            key = "sol_xhigh"
        elif (row["model"], row["effort"]) == ("gpt-6-astra", "xhigh"):
            key = "astra_xhigh"
        if key is not None:
            by_class[row["task_class"]][key].add(row["task_id"])

    result = {}
    for task_class, ids in sorted(by_class.items()):
        baseline = ids["sol_xhigh"]
        canary = ids["astra_xhigh"]
        shared = baseline & canary
        result[task_class] = {
            "baseline_task_ids": sorted(baseline),
            "canary_task_ids": sorted(canary),
            "shared_task_ids": sorted(shared),
            "baseline_only": sorted(baseline - canary),
            "canary_only": sorted(canary - baseline),
            "pairing_complete": bool(shared) and baseline == canary,
        }
    return result


def _rate_card_freshness(evaluation_date: date | None) -> dict:
    as_of = date.fromisoformat(RATE_CARD_AS_OF)
    if evaluation_date is None:
        return {
            "as_of": RATE_CARD_AS_OF,
            "evaluation_date": None,
            "age_days": None,
            "max_age_days": RATE_CARD_MAX_AGE_DAYS,
            "status": "unchecked",
            "fresh": False,
        }
    age_days = (evaluation_date - as_of).days
    if age_days < 0:
        status = "evaluation_precedes_rate_card"
        fresh = False
    elif age_days <= RATE_CARD_MAX_AGE_DAYS:
        status = "fresh"
        fresh = True
    else:
        status = "stale"
        fresh = False
    return {
        "as_of": RATE_CARD_AS_OF,
        "evaluation_date": evaluation_date.isoformat(),
        "age_days": age_days,
        "max_age_days": RATE_CARD_MAX_AGE_DAYS,
        "status": status,
        "fresh": fresh,
    }


def _comparison_status(routes: list[dict], pairing: dict, freshness: dict) -> str:
    if not freshness["fresh"]:
        return {
            "unchecked": "unchecked_rate_card",
            "stale": "stale_rate_card",
            "evaluation_precedes_rate_card": "evaluation_precedes_rate_card",
        }[freshness["status"]]
    if not pairing["pairing_complete"]:
        return "incomplete_pairing"
    if not pairing["minimum_pairing_met"]:
        return "insufficient_sample"
    reliable = [route for route in routes if route["reliability_eligible"]]
    if not reliable:
        return "no_reliable_routes"
    if any(not route["cost_observation_complete"] for route in reliable):
        return "incomplete_cost_observation"
    return "complete"


def analyze(records: list[dict], *, evaluation_date: date | None = None) -> dict:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    validated = []
    identities = set()
    for raw in records:
        row = validate(raw)
        identity = (row["task_class"], row["model"], row["effort"], row["task_id"])
        if identity in identities:
            raise ValueError("duplicate task_id for the same task class/model/effort route")
        identities.add(identity)
        validated.append(row)
        grouped[(row["task_class"], row["model"], row["effort"])].append(row)

    by_class: dict[str, list[dict]] = defaultdict(list)
    for (task_class, model, effort), rows in sorted(grouped.items()):
        summary = {"model": model, "effort": effort, **_aggregate(rows)}
        by_class[task_class].append(summary)

    pairing_by_class = _comparison_pairing(validated)
    freshness = _rate_card_freshness(evaluation_date)
    result_classes = {}
    for task_class, routes in sorted(by_class.items()):
        pairing = pairing_by_class[task_class]
        status = _comparison_status(routes, pairing, freshness)
        candidates = [route for route in routes if route["reliability_eligible"]]
        frontier = []
        if status == "complete":
            for route in candidates:
                if not any(_dominates(other, route) for other in candidates if other is not route):
                    frontier.append({"model": route["model"], "effort": route["effort"]})
        result_classes[task_class] = {
            "routes": routes,
            "comparison_pairing": pairing,
            "comparison_status": status,
            "cost_comparison_status": status,
            "pareto_frontier": frontier,
            "promotion_evidence_ready": (
                status == "complete"
                and pairing["promotion_sample_target_met"]
                and len(candidates) >= 2
            ),
        }

    return {
        "rate_card_as_of": RATE_CARD_AS_OF,
        "rate_card_freshness": freshness,
        "credit_rate_source": CREDIT_RATE_SOURCE,
        "usd_rate_source": USD_RATE_SOURCE,
        "minimum_acceptance_rate": MIN_ACCEPTANCE_RATE,
        "minimum_paired_tasks": MIN_PAIRED_TASKS,
        "promotion_task_target": PROMOTION_TASK_TARGET,
        "comparison_pairing": pairing_by_class,
        "astra_canary_pairing": _astra_pairing(validated),
        "task_classes": result_classes,
    }


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(validate(json.loads(line)))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid benchmark record on line {number}: {exc}") from exc
    return rows


def _evaluation_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("evaluation date must be YYYY-MM-DD") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--evaluation-date",
        type=_evaluation_date,
        default=date.today(),
        help="date used to enforce rate-card freshness (default: today)",
    )
    args = parser.parse_args()
    result = analyze(load_jsonl(args.input), evaluation_date=args.evaluation_date)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

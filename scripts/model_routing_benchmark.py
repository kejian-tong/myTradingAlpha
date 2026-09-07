"""Evaluate Codex model routes with correctness-first, cost-aware Pareto analysis.

Input is JSONL with one benchmark-run record per line. This tool never invokes a
model, changes routing, or grants merge authority; it evaluates supplied evidence.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean

RATE_CARD_AS_OF = "2026-09-07"
CREDIT_RATE_SOURCE = "https://help.openai.com/en/articles/11481834"
USD_RATE_SOURCE = "https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing"

# Current ChatGPT Work/Codex token-based credits per 1M tokens.
CREDIT_RATES = {
    "gpt-5.6-luna": {"input": 5.0, "cached_input": 0.5, "output": 30.0},
    "gpt-5.6-terra": {"input": 50.0, "cached_input": 5.0, "output": 300.0},
    "gpt-5.6-sol": {"input": 100.0, "cached_input": 10.0, "output": 500.0},
}

# Enterprise token-based USD rates per 1M tokens, used only when useful for comparison.
USD_RATES = {
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "cached_input": 0.20, "output": 12.00},
    "gpt-5.6-sol": {"input": 4.00, "cached_input": 0.40, "output": 20.00},
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
    if not _REQUIRED <= keys or not keys <= (_REQUIRED | _OPTIONAL):
        raise ValueError("benchmark record fields differ from reviewed schema")
    for key in ("task_id", "task_class", "model", "effort"):
        if type(record[key]) is not str or not record[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if record["model"] not in _MODELS:
        raise ValueError("model is not in the GPT-5.6 benchmark set")
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
    qualifying = [row for row in rows if eligible(row)]
    costs = [token_cost(row, CREDIT_RATES) for row in qualifying]
    usd = [token_cost(row, USD_RATES) for row in qualifying]
    cost_complete = bool(qualifying) and all(value is not None for value in costs)
    return {
        "runs": len(rows),
        "eligible_runs": len(qualifying),
        "ineligible_runs": len(rows) - len(qualifying),
        "quality_mean": fmean(row["quality_score"] for row in qualifying) if qualifying else None,
        "duration_ms_mean": fmean(row["duration_ms"] for row in qualifying) if qualifying else None,
        "retries_mean": fmean(row["retries"] for row in qualifying) if qualifying else None,
        "credits_mean": fmean(costs) if cost_complete else None,
        "usd_mean": fmean(usd) if cost_complete else None,
        "cost_observation_complete": cost_complete,
    }


def _dominates(left: dict, right: dict) -> bool:
    # Both must have complete quality/time/retry/cost observations and be eligible.
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


def analyze(records: list[dict]) -> dict:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for raw in records:
        row = validate(raw)
        grouped[(row["task_class"], row["model"], row["effort"])].append(row)

    by_class: dict[str, list[dict]] = defaultdict(list)
    for (task_class, model, effort), rows in sorted(grouped.items()):
        summary = {"model": model, "effort": effort, **_aggregate(rows)}
        by_class[task_class].append(summary)

    result_classes = {}
    for task_class, routes in sorted(by_class.items()):
        candidates = [
            route for route in routes
            if route["eligible_runs"] > 0
            and route["quality_mean"] is not None
            and route["cost_observation_complete"]
        ]
        frontier = []
        for route in candidates:
            if not any(_dominates(other, route) for other in candidates if other is not route):
                frontier.append({"model": route["model"], "effort": route["effort"]})
        result_classes[task_class] = {
            "routes": routes,
            "pareto_frontier": frontier,
            "cost_comparison_status": "complete" if len(candidates) == len([r for r in routes if r["eligible_runs"] > 0]) else "incomplete",
        }

    return {
        "rate_card_as_of": RATE_CARD_AS_OF,
        "credit_rate_source": CREDIT_RATE_SOURCE,
        "usd_rate_source": USD_RATE_SOURCE,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(load_jsonl(args.input)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

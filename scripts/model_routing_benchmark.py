"""Evaluate Codex model routes with paired, reliability-first Pareto analysis.

Input is JSONL with one benchmark-run record per line. This tool never invokes a
model, changes routing, or grants merge authority; it evaluates supplied evidence.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
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
    "gpt-6-luna": {"input": 5.0, "cached_input": 0.5, "output": 30.0},
    "gpt-5.6-terra": {"input": 50.0, "cached_input": 5.0, "output": 300.0},
    "gpt-6-sol": {"input": 100.0, "cached_input": 10.0, "output": 500.0},
    "gpt-6-astra": {"input": 250.0, "cached_input": 25.0, "output": 1250.0},
}

# Enterprise token-based USD rates per 1M tokens, used only when useful for comparison.
USD_RATES = {
    "gpt-6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "cached_input": 0.20, "output": 12.00},
    "gpt-6-sol": {"input": 4.00, "cached_input": 0.40, "output": 20.00},
    "gpt-6-astra": {"input": 10.00, "cached_input": 1.00, "output": 50.00},
}

_TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens")
MAX_SIGNED_INT = 2**63 - 1
_NONNEGATIVE_INTEGER_FIELDS = ("missed_blocker_high", "duration_ms", "retries")
_PROVENANCE_FIELDS = (
    "repository_commit_sha",
    "repository_tree_sha",
    "task_manifest_sha256",
)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_EFFORTS = {
    "gpt-6-luna": frozenset({"max"}),
    "gpt-5.6-terra": frozenset({"medium", "high", "xhigh"}),
    "gpt-6-sol": frozenset({"high", "xhigh"}),
    "gpt-6.1-sol": frozenset({"xhigh"}),
    "gpt-6-astra": frozenset({"xhigh"}),
}
_MODELS = frozenset(_ALLOWED_EFFORTS)

# These route pairs are the dated rate-card coverage. Current GPT-6.1 Sol/xhigh
# is accepted benchmark evidence but remains unpriced until verified Work/Codex
# and Enterprise rates are available.
_RATE_CARD_ROUTE_PAIRS = frozenset(
    {
        ("gpt-6-luna", "max"),
        ("gpt-5.6-terra", "medium"),
        ("gpt-5.6-terra", "high"),
        ("gpt-5.6-terra", "xhigh"),
        ("gpt-6-sol", "high"),
        ("gpt-6-sol", "xhigh"),
        ("gpt-6-astra", "xhigh"),
    }
)
_REQUIRED = {
    "task_id", "task_class", "model", "effort", "acceptance_pass", "safety_gate_pass",
    "missed_blocker_high", "quality_score", "duration_ms", "retries", *_PROVENANCE_FIELDS,
}
_OPTIONAL = set(_TOKEN_FIELDS)
_V2_REQUIRED = {"schema_version", "usage", "task_usage_complete", "pricing_surface", "context_tier"}
_V2_PRICING_SURFACES = frozenset({"historical_work_codex", "unknown"})
_V2_CONTEXT_TIERS = frozenset({"short", "long", "mixed", "unknown"})
_LABEL_MAX_BYTES = 128


def _observations_module():
    path = Path(__file__).resolve().with_name("harness_observations.py")
    spec = importlib.util.spec_from_file_location("benchmark_harness_observations", path)
    if spec is None or spec.loader is None:
        raise OSError("cannot load harness observations module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _keys(record: dict) -> set[str]:
    keys = []
    for key in dict.keys(record):
        if type(key) is not str:
            raise ValueError("benchmark record fields must be built-in strings")
        keys.append(key)
    return set(keys)


def _label(value: object, *, name: str) -> str:
    if type(value) is not str or not value or len(value) > _LABEL_MAX_BYTES:
        raise ValueError(f"{name} must be a bounded non-empty string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must be valid Unicode") from exc
    if len(encoded) > _LABEL_MAX_BYTES or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f"{name} must be a bounded valid Unicode string")
    return value


def _validate_common(record: dict) -> dict:
    for key in ("task_id", "task_class", "model", "effort"):
        _label(record[key], name=key)
    if record["model"] not in _MODELS:
        raise ValueError("model is not in the routing benchmark set")
    if record["effort"] not in _ALLOWED_EFFORTS[record["model"]]:
        raise ValueError("model/effort pair is not in the routing benchmark policy matrix")
    if (
        type(record["repository_commit_sha"]) is not str
        or _HEX40.fullmatch(record["repository_commit_sha"]) is None
        or type(record["repository_tree_sha"]) is not str
        or _HEX40.fullmatch(record["repository_tree_sha"]) is None
        or type(record["task_manifest_sha256"]) is not str
        or _HEX64.fullmatch(record["task_manifest_sha256"]) is None
    ):
        raise ValueError("benchmark record provenance fields must be lowercase hexadecimal")
    for key in ("acceptance_pass", "safety_gate_pass"):
        if type(record[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    for key in _NONNEGATIVE_INTEGER_FIELDS:
        if type(record[key]) is not int or not 0 <= record[key] <= MAX_SIGNED_INT:
            raise ValueError(f"{key} must be a non-negative signed 64-bit integer")
    quality = _number(record["quality_score"], name="quality_score")
    if quality > 100:
        raise ValueError("quality_score must be <= 100")
    return dict(record)


def _number(value: object, *, name: str) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def validate(record: object) -> dict:
    if type(record) is not dict:
        raise ValueError("benchmark record must be an object")
    keys = _keys(record)
    missing_provenance = set(_PROVENANCE_FIELDS) - keys
    if missing_provenance:
        raise ValueError("benchmark record provenance fields are required")
    if "schema_version" not in keys:
        if not keys >= _REQUIRED or not keys <= (_REQUIRED | _OPTIONAL):
            raise ValueError("benchmark record fields differ from reviewed schema")
        result = _validate_common(record)
        present_tokens = [key in keys for key in _TOKEN_FIELDS]
        if any(present_tokens) and not all(present_tokens):
            raise ValueError("token observations must provide input/cached/output together")
        if all(present_tokens):
            for key in _TOKEN_FIELDS:
                if type(record[key]) is not int or not 0 <= record[key] <= MAX_SIGNED_INT:
                    raise ValueError(f"{key} must be a non-negative signed 64-bit integer")
        return result

    allowed = _REQUIRED | _V2_REQUIRED
    if not keys >= (_REQUIRED | _V2_REQUIRED) or not keys <= allowed:
        raise ValueError("benchmark record fields differ from reviewed v2 schema")
    if type(record["schema_version"]) is not int or record["schema_version"] != 2:
        raise ValueError("schema_version must equal 2")
    if any(key in keys for key in _TOKEN_FIELDS):
        raise ValueError("v2 benchmark record cannot contain legacy flat token fields")
    if type(record["task_usage_complete"]) is not bool:
        raise ValueError("task_usage_complete must be boolean")
    if (
        type(record["pricing_surface"]) is not str
        or record["pricing_surface"] not in _V2_PRICING_SURFACES
    ):
        raise ValueError("pricing_surface is unsupported")
    if (
        type(record["context_tier"]) is not str
        or record["context_tier"] not in _V2_CONTEXT_TIERS
    ):
        raise ValueError("context_tier is unsupported")
    result = _validate_common(record)
    observations = _observations_module()
    usage = observations.validate_usage(record["usage"])
    if (
        usage["usage_scope"] == "request"
        and record["context_tier"] == "short"
        and usage["input_tokens"] is not None
        and usage["input_tokens"] > observations.REQUEST_INPUT_EXPOSURE_LIMIT
    ):
        raise ValueError("request input exposure exceeds 272000 tokens")
    result["usage"] = usage
    return result


def eligible(record: dict) -> bool:
    """Return per-run correctness/safety eligibility for diagnostics."""
    return (
        record["acceptance_pass"] is True
        and record["safety_gate_pass"] is True
        and record["missed_blocker_high"] == 0
    )


def token_cost(record: dict, rates: dict[str, dict[str, float]]) -> float | None:
    if record.get("schema_version") == 2:
        usage = record.get("usage")
        if type(usage) is not dict:
            return None
        if (
            record.get("task_usage_complete") is not True
            or usage.get("usage_scope") != "task"
            or usage.get("aggregation_scope") != "exclusive"
            or record.get("pricing_surface") != "historical_work_codex"
            or record.get("context_tier") != "short"
            or usage.get("input_tokens") is None
            or usage.get("cached_input_tokens") is None
            or usage.get("output_tokens") is None
            or usage.get("cache_write_tokens") != 0
            or any(
                value not in (None, 0)
                for value in (
                    usage.get("cache_write_30m_tokens"),
                    usage.get("cache_write_12h_tokens"),
                )
            )
        ):
            return None
        if (record["model"], record["effort"]) not in _RATE_CARD_ROUTE_PAIRS:
            return None
        model_rates = rates.get(record["model"])
        if model_rates is None:
            return None
        ordinary_input = usage["input_tokens"] - usage["cached_input_tokens"]
        if ordinary_input < 0:
            return None
        return (
            ordinary_input / 1_000_000 * model_rates["input"]
            + usage["cached_input_tokens"] / 1_000_000 * model_rates["cached_input"]
            + usage["output_tokens"] / 1_000_000 * model_rates["output"]
        )
    if not all(key in record for key in _TOKEN_FIELDS):
        return None
    if (record["model"], record["effort"]) not in _RATE_CARD_ROUTE_PAIRS:
        return None
    model_rates = rates.get(record["model"])
    if model_rates is None:
        return None
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
    pair_specs = {
        "historical": (("gpt-6-sol", "xhigh"), ("gpt-6-astra", "xhigh")),
        "current": (("gpt-6.1-sol", "xhigh"), ("gpt-6-astra", "xhigh")),
    }
    by_class: dict[str, dict[str, dict[str, set[str]]]] = defaultdict(
        lambda: {
            variant: {"baseline": set(), "canary": set()}
            for variant in pair_specs
        }
    )
    for row in rows:
        identity = (row["model"], row["effort"])
        for variant, (baseline_route, canary_route) in pair_specs.items():
            if identity == baseline_route:
                by_class[row["task_class"]][variant]["baseline"].add(row["task_id"])
            elif identity == canary_route:
                by_class[row["task_class"]][variant]["canary"].add(row["task_id"])

    def summarize(ids: dict[str, set[str]]) -> dict[str, object]:
        baseline = ids["baseline"]
        canary = ids["canary"]
        shared = baseline & canary
        return {
            "baseline_task_ids": sorted(baseline),
            "canary_task_ids": sorted(canary),
            "shared_task_ids": sorted(shared),
            "baseline_only": sorted(baseline - canary),
            "canary_only": sorted(canary - baseline),
            "pairing_complete": bool(shared) and baseline == canary,
        }

    result = {}
    for task_class, variants in sorted(by_class.items()):
        historical_present = bool(variants["historical"]["baseline"])
        current_present = bool(variants["current"]["baseline"])
        canary_present = bool(variants["historical"]["canary"])
        if historical_present:
            result[task_class] = summarize(variants["historical"])
            if current_present:
                result[task_class]["current_route_pairing"] = summarize(variants["current"])
        elif current_present:
            result[task_class] = summarize(variants["current"])
        elif canary_present:
            result[task_class] = summarize(variants["historical"])
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
    if any((route["model"], route["effort"]) not in _RATE_CARD_ROUTE_PAIRS for route in routes):
        return "unknown_route_pricing"
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
    provenance_by_task: dict[tuple[str, str], dict[str, str]] = {}
    for raw in records:
        row = validate(raw)
        task_key = (row["task_class"], row["task_id"])
        provenance = {field: row[field] for field in _PROVENANCE_FIELDS}
        prior_provenance = provenance_by_task.get(task_key)
        if prior_provenance is not None and prior_provenance != provenance:
            raise ValueError("task provenance mismatch across model/effort routes")
        provenance_by_task[task_key] = provenance
        identity = (row["task_class"], row["model"], row["effort"], row["task_id"])
        if identity in identities:
            raise ValueError("duplicate task_id for the same task class/model/effort route")
        identities.add(identity)
        validated.append(row)
        grouped[(row["task_class"], row["model"], row["effort"])].append(row)

    if len({row.get("schema_version", 1) for row in validated}) > 1:
        raise ValueError("mixed schema benchmark comparisons are not allowed")

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
        "task_provenance": {
            task_class: {
                task_id: provenance_by_task[(task_class, task_id)]
                for task_id in sorted(
                    task_id_value
                    for class_value, task_id_value in provenance_by_task
                    if class_value == task_class
                )
            }
            for task_class in sorted({class_value for class_value, _ in provenance_by_task})
        },
        "task_classes": result_classes,
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def load_jsonl(path: Path) -> list[dict]:
    try:
        raw_rows = _observations_module().load_jsonl(path)
    except ValueError as exc:
        if "non-finite JSON number" in str(exc):
            raise ValueError("quality_score must be finite") from exc
        raise
    rows = []
    for number, raw in enumerate(raw_rows, start=1):
        try:
            rows.append(validate(raw))
        except ValueError as exc:
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

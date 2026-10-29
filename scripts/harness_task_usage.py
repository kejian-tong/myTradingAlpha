"""Bounded, explicit accounting for sanitized task-usage observations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__:
    from . import harness_observations
else:  # Direct script execution from an unrelated working directory.
    import harness_observations

MAX_ROWS = 10_000
MAX_AGENTS = 256
MAX_SIGNED_INT = 2**63 - 1
_HEX64 = frozenset("0123456789abcdef")
_AGENT_KEYS = frozenset({"record_type", "agent_ref", "parent_ref"})
_RESPONSE_KEYS = frozenset({"record_type", "agent_ref", "response_ref", "usage"})
_USAGE_KEYS = frozenset(
    {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"}
)
_RAW_METRICS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
_METRICS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
    "uncached_input_tokens",
    "nonreasoning_output_tokens",
)
_ERROR = "invalid task usage input"


def _fail() -> ValueError:
    """Return one fixed diagnostic without incorporating caller data."""
    return ValueError(_ERROR)


def _valid_ref(value: object) -> bool:
    if type(value) is not str or len(value) != 64:
        return False
    return all(char in _HEX64 for char in value)


def _validate_keys(row: dict, expected: frozenset[str]) -> None:
    # Reject wrong cardinality before iterating, then reject hostile key types
    # before building sets or performing membership checks.
    if len(row) != len(expected):
        raise _fail()
    keys = []
    for key in dict.keys(row):
        if type(key) is not str:
            raise _fail()
        keys.append(key)
    if set(keys) != expected:
        raise _fail()


def _checked_add(left: int, right: int) -> int:
    total = left + right
    if total > MAX_SIGNED_INT:
        raise _fail()
    return total


def _sum_known(values: list[int]) -> int | None:
    if not values:
        return None
    total = 0
    for value in values:
        total = _checked_add(total, value)
    return total


def _response_metrics(values: tuple[int | None, ...]) -> dict[str, int | None]:
    input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens = values
    if (
        input_tokens is not None
        and cached_input_tokens is not None
        and cached_input_tokens > input_tokens
    ):
        raise _fail()
    if (
        output_tokens is not None
        and reasoning_output_tokens is not None
        and reasoning_output_tokens > output_tokens
    ):
        raise _fail()

    total_tokens = None
    if input_tokens is not None and output_tokens is not None:
        total_tokens = _checked_add(input_tokens, output_tokens)
    uncached_input_tokens = None
    if input_tokens is not None and cached_input_tokens is not None:
        uncached_input_tokens = input_tokens - cached_input_tokens
    nonreasoning_output_tokens = None
    if output_tokens is not None and reasoning_output_tokens is not None:
        nonreasoning_output_tokens = output_tokens - reasoning_output_tokens

    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": total_tokens,
        "uncached_input_tokens": uncached_input_tokens,
        "nonreasoning_output_tokens": nonreasoning_output_tokens,
    }


def _summarize_group(
    agent_refs: list[str],
    responses: list[tuple[str, dict[str, int | None]]],
    retry_count: int,
) -> dict:
    agent_count = len(agent_refs)
    responding_agents = {owner for owner, _metrics in responses}
    agents_with_usage = len(responding_agents)
    agents_missing_usage = agent_count - agents_with_usage
    response_metrics = [metrics for _owner, metrics in responses]

    if agent_count == 0:
        observed_totals = dict.fromkeys(_METRICS, 0)
        complete_totals = dict.fromkeys(_METRICS, 0)
        coverage_qualifier = "empty_supplied_group"
    else:
        observed_totals = {}
        complete_totals = {}
        coverage_qualifier = "explicit_inventory_only"
        for metric in _METRICS:
            known = [
                values[metric]
                for values in response_metrics
                if values[metric] is not None
            ]
            observed_totals[metric] = _sum_known(known)
            if agents_missing_usage or any(values[metric] is None for values in response_metrics):
                complete_totals[metric] = None
            else:
                complete_totals[metric] = _sum_known(known)

    return {
        "coverage_qualifier": coverage_qualifier,
        "agent_count": agent_count,
        "agents_with_usage": agents_with_usage,
        "agents_missing_usage": agents_missing_usage,
        "response_count": len(response_metrics),
        "retry_count": retry_count,
        "observed_totals": observed_totals,
        "complete_totals": complete_totals,
    }


def summarize_task_usage(records: object, *, root_ref: object) -> dict:
    """Summarize explicit sanitized agent and response records without side effects."""
    if not _valid_ref(root_ref):
        raise _fail()
    if type(records) not in (list, tuple) or len(records) > MAX_ROWS:
        raise _fail()

    parents: dict[str, str | None] = {}
    response_rows: dict[
        str, tuple[str, tuple[int | None, ...], dict[str, int | None]]
    ] = {}
    retry_owners: dict[str, int] = {}

    for row in records:
        if type(row) is not dict:
            raise _fail()
        if len(row) not in (len(_AGENT_KEYS), len(_RESPONSE_KEYS)):
            raise _fail()
        # Inspect keys as plain objects before any hashing or set comparison.
        row_keys = []
        for key in dict.keys(row):
            if type(key) is not str:
                raise _fail()
            row_keys.append(key)
        key_set = set(row_keys)
        if key_set == _AGENT_KEYS:
            record_type = dict.__getitem__(row, "record_type")
            if type(record_type) is not str or record_type != "agent":
                raise _fail()
            agent_ref = dict.__getitem__(row, "agent_ref")
            parent_ref = dict.__getitem__(row, "parent_ref")
            if not _valid_ref(agent_ref):
                raise _fail()
            if parent_ref is not None and not _valid_ref(parent_ref):
                raise _fail()
            previous = parents.get(agent_ref, _MISSING)
            if previous is not _MISSING and previous != parent_ref:
                raise _fail()
            if previous is _MISSING:
                parents[agent_ref] = parent_ref
                if len(parents) > MAX_AGENTS:
                    raise _fail()
        elif key_set == _RESPONSE_KEYS:
            record_type = dict.__getitem__(row, "record_type")
            if type(record_type) is not str or record_type != "response_usage":
                raise _fail()
            agent_ref = dict.__getitem__(row, "agent_ref")
            response_ref = dict.__getitem__(row, "response_ref")
            usage = dict.__getitem__(row, "usage")
            if not _valid_ref(agent_ref) or not _valid_ref(response_ref):
                raise _fail()
            if type(usage) is not dict:
                raise _fail()
            _validate_keys(usage, _USAGE_KEYS)
            values = []
            for key in _RAW_METRICS:
                value = dict.__getitem__(usage, key)
                if value is not None and (
                    type(value) is not int or not 0 <= value <= MAX_SIGNED_INT
                ):
                    raise _fail()
                values.append(value)
            raw_values = tuple(values)
            derived = _response_metrics(raw_values)
            previous = response_rows.get(response_ref)
            current = (agent_ref, raw_values)
            if previous is None:
                response_rows[response_ref] = (agent_ref, raw_values, derived)
            elif previous[:2] != current:
                raise _fail()
            else:
                retry_owners[response_ref] = retry_owners.get(response_ref, 0) + 1
        else:
            raise _fail()

    if root_ref not in parents or parents[root_ref] is not None:
        raise _fail()

    children_by_parent: dict[str, list[str]] = {agent_ref: [] for agent_ref in parents}
    for agent_ref, parent_ref in parents.items():
        if agent_ref == root_ref:
            continue
        if parent_ref is None or parent_ref == agent_ref or parent_ref not in parents:
            raise _fail()
        children_by_parent[parent_ref].append(agent_ref)

    visited = {root_ref}
    pending = [root_ref]
    while pending:
        parent = pending.pop()
        for child in children_by_parent[parent]:
            if child in visited:
                raise _fail()
            visited.add(child)
            pending.append(child)
    if len(visited) != len(parents):
        raise _fail()

    root_responses: list[tuple[str, dict[str, int | None]]] = []
    child_responses: list[tuple[str, dict[str, int | None]]] = []
    combined_responses: list[tuple[str, dict[str, int | None]]] = []
    root_retries = 0
    child_retries = 0
    for response_ref, response in response_rows.items():
        owner, raw_values, derived = response
        if owner not in parents:
            raise _fail()
        combined_responses.append((owner, derived))
        retries = retry_owners.get(response_ref, 0)
        if retries:
            if owner == root_ref:
                root_retries += retries
            else:
                child_retries += retries
        if owner == root_ref:
            root_responses.append((owner, derived))
        else:
            child_responses.append((owner, derived))

    root_group = _summarize_group([root_ref], root_responses, root_retries)
    child_refs = [agent_ref for agent_ref in parents if agent_ref != root_ref]
    child_group = _summarize_group(child_refs, child_responses, child_retries)
    combined_group = _summarize_group(list(parents), combined_responses, root_retries + child_retries)
    return {
        "schema_version": 1,
        "root_ref": root_ref,
        "inventory_coverage": "explicit_inventory_only",
        "root": root_group,
        "children": child_group,
        "combined": combined_group,
    }


_MISSING = object()


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise _fail()


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description="Summarize explicit sanitized task usage records.")
    parser.add_argument("--observations", required=True)
    parser.add_argument("--root-ref", required=True)
    try:
        arguments = parser.parse_args(argv)
        records = harness_observations.load_jsonl(Path(arguments.observations))
        summary = summarize_task_usage(records, root_ref=arguments.root_ref)
        sys.stdout.write(json.dumps(summary, separators=(",", ":")) + "\n")
        return 0
    except (OSError, TypeError, ValueError):
        sys.stderr.write(f"error: {_ERROR}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

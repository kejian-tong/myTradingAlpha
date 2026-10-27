"""Bounded JSON codecs and explicit token-usage accounting for the Codex harness."""
from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path

MAX_RECORD_BYTES = 16_384
MAX_FILE_BYTES = 16_777_216
MAX_JSONL_RECORDS = 10_000
MAX_SIGNED_INT = 2**63 - 1
MAX_JSON_DEPTH = 64
REQUEST_INPUT_EXPOSURE_LIMIT = 272_000

USAGE_KEYS = (
    "observation_ref",
    "revision",
    "source_kind",
    "usage_scope",
    "aggregation_scope",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "cache_write_30m_tokens",
    "cache_write_12h_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
COUNT_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "cache_write_30m_tokens",
    "cache_write_12h_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
SUMMARY_KEYS = (*COUNT_KEYS, "non_cached_input_tokens", "ordinary_input_tokens")
_SOURCE_KINDS = frozenset({"runtime_report", "caller_report"})
_USAGE_SCOPES = frozenset({"request", "turn", "agent", "task"})
_AGGREGATION_SCOPES = frozenset({"exclusive", "includes_children", "unknown"})
_HEX64 = frozenset("0123456789abcdef")


def _error(message: str) -> ValueError:
    """Return a bounded diagnostic that never incorporates caller text."""
    return ValueError(message)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _error("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise _error("non-finite JSON number")


def _check_depth(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise _error("JSON nesting depth exceeds the reviewed limit")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                return  # The JSON parser will report the malformed delimiter.


def _check_json_tree(root: object) -> None:
    pending = [root]
    while pending:
        value = pending.pop()
        if type(value) is str:
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                raise _error("JSON contains an invalid Unicode surrogate")
        elif type(value) is list:
            pending.extend(value)
        elif type(value) is dict:
            for key, item in dict.items(value):
                if type(key) is not str:
                    raise _error("JSON object keys must be strings")
                if any(0xD800 <= ord(char) <= 0xDFFF for char in key):
                    raise _error("JSON contains an invalid Unicode surrogate")
                pending.append(item)
        elif type(value) is float:
            if not math.isfinite(value):
                raise _error("non-finite JSON number")
        elif value is None or type(value) in (bool, int):
            continue
        else:  # JSON's parser should never produce another built-in type.
            raise _error("JSON contains an unsupported value")


def decode_json(data: str | bytes, *, max_bytes: int = MAX_RECORD_BYTES) -> object:
    """Decode bounded strict JSON, rejecting duplicate keys and unsafe scalar values."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_FILE_BYTES:
        raise _error("JSON byte limit is invalid")
    if type(data) is bytes:
        if len(data) > max_bytes:
            raise _error("JSON record size exceeds the reviewed limit")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _error("JSON input is not valid UTF-8") from exc
    elif type(data) is str:
        if len(data) > max_bytes:
            raise _error("JSON record size exceeds the reviewed limit")
        try:
            encoded = data.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _error("JSON input contains invalid Unicode") from exc
        if len(encoded) > max_bytes:
            raise _error("JSON record size exceeds the reviewed limit")
        text = data
    else:
        raise _error("JSON input must be a built-in string or bytes")

    _check_depth(text)
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ValueError as exc:
        if str(exc) in {
            "duplicate JSON object key",
            "non-finite JSON number",
        }:
            raise
        raise _error("invalid JSON input") from exc
    except (json.JSONDecodeError, RecursionError) as exc:
        raise _error("invalid JSON input") from exc
    _check_json_tree(value)
    return value


def _safe_read(path: Path, *, max_bytes: int) -> bytes:
    """Read a regular file without following symlinks or blocking on special files."""
    try:
        expected = path.lstat()
    except OSError as exc:
        raise _error("input file cannot be inspected safely") from exc
    if not stat.S_ISREG(expected.st_mode):
        raise _error("input must be a regular file")
    if expected.st_size > max_bytes:
        raise _error("JSONL file size exceeds the reviewed limit")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise _error("input file cannot be opened safely") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_dev != expected.st_dev
            or info.st_ino != expected.st_ino
        ):
            raise _error("input file changed during safe open")
        if info.st_size > max_bytes:
            raise _error("JSONL file size exceeds the reviewed limit")
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(65_536, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise _error("JSONL file size exceeds the reviewed limit")
        return b"".join(chunks)
    finally:
        os.close(fd)


def load_jsonl(path: Path) -> list[object]:
    """Load bounded JSONL from a regular file, rejecting partial or oversized records."""
    if type(path) is str:
        if not path or len(path) > 4_096:
            raise _error("JSONL path is outside the reviewed bound")
        try:
            path.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _error("JSONL path contains invalid Unicode") from exc
        path = Path(path)
    elif type(path) is not type(Path()):
        raise _error("JSONL path must be a built-in string or Path")
    raw = _safe_read(path, max_bytes=MAX_FILE_BYTES)
    rows = []
    offset = 0
    number = 0
    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        if newline < 0:
            line = raw[offset:]
            offset = len(raw)
        else:
            line = raw[offset:newline]
            offset = newline + 1
        number += 1
        if line.endswith(b"\r"):
            line = line[:-1]
        if not line.strip():
            continue
        if len(line) > MAX_RECORD_BYTES:
            raise _error("JSONL record size exceeds the reviewed limit")
        try:
            rows.append(decode_json(line, max_bytes=MAX_RECORD_BYTES))
        except ValueError as exc:
            raise _error(f"invalid JSONL record on line {number}: {exc}") from exc
        if len(rows) > MAX_JSONL_RECORDS:
            raise _error("JSONL record count exceeds the reviewed limit")
    return rows


def _validate_usage_keys(usage: dict) -> None:
    # Validate exact key types before building sets, copying, hashing, or formatting.
    keys = []
    for key in dict.keys(usage):
        if type(key) is not str:
            raise _error("usage fields must be built-in strings")
        keys.append(key)
    key_set = set(keys)
    if key_set != set(USAGE_KEYS):
        raise _error("usage fields differ from the reviewed schema")


def _checked_add(left: int, right: int) -> int:
    total = left + right
    if total > MAX_SIGNED_INT:
        raise _error("derived token arithmetic exceeds signed 64-bit bounds")
    return total


def validate_usage(usage: object) -> dict:
    """Validate and detach one v2 usage object using exact built-in primitives."""
    if type(usage) is not dict:
        raise _error("usage must be a built-in dictionary")
    _validate_usage_keys(usage)

    observation_ref = usage["observation_ref"]
    if (
        type(observation_ref) is not str
        or len(observation_ref) != 64
        or any(char not in _HEX64 for char in observation_ref)
    ):
        raise _error("observation_ref must be lowercase hexadecimal")
    revision = usage["revision"]
    if type(revision) is not int or not 0 <= revision <= MAX_SIGNED_INT:
        raise _error("revision must be a non-negative signed 64-bit integer")
    source_kind = usage["source_kind"]
    if type(source_kind) is not str or source_kind not in _SOURCE_KINDS:
        raise _error("source_kind is unsupported")
    usage_scope = usage["usage_scope"]
    if type(usage_scope) is not str or usage_scope not in _USAGE_SCOPES:
        raise _error("usage_scope is unsupported")
    aggregation_scope = usage["aggregation_scope"]
    if type(aggregation_scope) is not str or aggregation_scope not in _AGGREGATION_SCOPES:
        raise _error("aggregation_scope is unsupported")

    for field in COUNT_KEYS:
        value = usage[field]
        if value is not None and (
            type(value) is not int or not 0 <= value <= MAX_SIGNED_INT
        ):
            raise _error(f"{field} must be null or a non-negative signed 64-bit integer")

    detached = {key: usage[key] for key in USAGE_KEYS}
    cached = detached["cached_input_tokens"]
    total_writes = detached["cache_write_tokens"]
    ttl_30m = detached["cache_write_30m_tokens"]
    ttl_12h = detached["cache_write_12h_tokens"]
    known_children = 0
    children_known = True
    for component in (ttl_30m, ttl_12h):
        if component is None:
            children_known = False
        else:
            known_children = _checked_add(known_children, component)
    if total_writes is not None and known_children > total_writes:
        raise _error("known cache-write children exceed the known parent total")
    if total_writes is not None and children_known and known_children != total_writes:
        raise _error("known cache-write components differ from the parent total")

    input_tokens = detached["input_tokens"]
    write_lower_bound = total_writes if total_writes is not None else known_children
    if input_tokens is not None:
        input_lower_bound = write_lower_bound
        if cached is not None:
            input_lower_bound = _checked_add(cached, input_lower_bound)
        if input_lower_bound > input_tokens:
            raise _error("known cached input and cache writes exceed input tokens")

    output = detached["output_tokens"]
    reasoning = detached["reasoning_output_tokens"]
    if output is not None and reasoning is not None and reasoning > output:
        raise _error("reasoning output exceeds output tokens")
    return detached


def _canonical_usage(usage: dict) -> tuple[object, ...]:
    return tuple(usage[key] for key in USAGE_KEYS)


def _record_metric(usage: dict, key: str) -> int | None:
    if key in COUNT_KEYS:
        return usage[key]
    input_tokens = usage["input_tokens"]
    cached = usage["cached_input_tokens"]
    writes = usage["cache_write_tokens"]
    if input_tokens is None or cached is None:
        return None
    non_cached = input_tokens - cached
    if key == "non_cached_input_tokens":
        return non_cached
    if writes is None:
        return None
    ordinary = non_cached - writes
    if ordinary < 0:
        raise _error("ordinary input arithmetic is inconsistent")
    return ordinary


def summarize_usage(usages: object) -> dict:
    """Select latest immutable snapshots and report per-scope observed/complete totals."""
    if type(usages) not in (list, tuple):
        raise _error("usage observations must be a built-in list or tuple")
    identities: dict[str, tuple[str, str, str]] = {}
    revisions: dict[str, dict[int, tuple[object, ...]]] = {}
    latest: dict[str, dict] = {}
    for raw in usages:
        usage = validate_usage(raw)
        ref = usage["observation_ref"]
        identity = (
            usage["source_kind"],
            usage["usage_scope"],
            usage["aggregation_scope"],
        )
        prior_identity = identities.get(ref)
        if prior_identity is not None and prior_identity != identity:
            raise _error("observation identity cannot be rebound")
        identities[ref] = identity

        revision = usage["revision"]
        canonical = _canonical_usage(usage)
        series_revisions = revisions.setdefault(ref, {})
        prior = series_revisions.get(revision)
        if prior is not None and prior != canonical:
            raise _error("conflicting content for an observation revision")
        series_revisions[revision] = canonical
        current = latest.get(ref)
        if current is None or revision > current["revision"]:
            latest[ref] = usage

    by_scope: dict[str, list[dict]] = {}
    for usage in latest.values():
        by_scope.setdefault(usage["usage_scope"], []).append(usage)

    summary = {}
    exposure_over_limit = 0
    exposure_unknown = 0
    for scope in sorted(by_scope):
        records = by_scope[scope]
        exclusive = [row for row in records if row["aggregation_scope"] == "exclusive"]
        excluded = [row for row in records if row["aggregation_scope"] != "exclusive"]
        unknown_records = [
            row for row in records if any(row[key] is None for key in COUNT_KEYS)
        ]
        observed_totals = {}
        complete_totals = {}
        for metric in SUMMARY_KEYS:
            known_values = [
                value
                for row in exclusive
                if (value := _record_metric(row, metric)) is not None
            ]
            observed_total = 0
            for value in known_values:
                observed_total = _checked_add(observed_total, value)
            observed_totals[metric] = observed_total if known_values else None
            complete = bool(exclusive) and not excluded
            if complete:
                complete = all(_record_metric(row, metric) is not None for row in exclusive)
            complete_totals[metric] = observed_total if complete else None

        summary[scope] = {
            "observed_totals": observed_totals,
            "complete_totals": complete_totals,
            "coverage": {
                "selected_records": len(records),
                "exclusive_records": len(exclusive),
                "excluded_records": len(excluded),
                "unknown_records": len(unknown_records),
            },
        }
        if scope == "request":
            for row in records:
                input_tokens = row["input_tokens"]
                if row["aggregation_scope"] != "exclusive" or input_tokens is None:
                    exposure_unknown += 1
                elif input_tokens > REQUEST_INPUT_EXPOSURE_LIMIT:
                    exposure_over_limit += 1

    return {
        "by_usage_scope": summary,
        "request_input_exposure": {
            "over_limit_count": exposure_over_limit,
            "unknown_count": exposure_unknown,
        },
    }

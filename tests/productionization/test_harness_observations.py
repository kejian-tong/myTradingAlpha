from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OBSERVATIONS = ROOT / "scripts/harness_observations.py"
MAX_RECORD_BYTES = 16_384
MAX_FILE_BYTES = 16_777_216
MAX_JSONL_RECORDS = 10_000
MAX_SIGNED_INT = 2**63 - 1


def _module():
    # Keep RED behavioral: the shared contract is intentionally absent on base.
    assert OBSERVATIONS.is_file(), (
        "missing explicit token-accounting contract: scripts/harness_observations.py"
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location("harness_observations", OBSERVATIONS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _usage(
    *,
    observation_ref: str = "a" * 64,
    revision: int = 0,
    usage_scope: str = "task",
    aggregation_scope: str = "exclusive",
    source_kind: str = "runtime_report",
    input_tokens: int | None = 100,
    cached_input_tokens: int | None = 20,
    cache_write_tokens: int | None = 0,
    cache_write_30m_tokens: int | None = 0,
    cache_write_12h_tokens: int | None = 0,
    output_tokens: int | None = 30,
    reasoning_output_tokens: int | None = 10,
) -> dict:
    return {
        "observation_ref": observation_ref,
        "revision": revision,
        "source_kind": source_kind,
        "usage_scope": usage_scope,
        "aggregation_scope": aggregation_scope,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cache_write_30m_tokens": cache_write_30m_tokens,
        "cache_write_12h_tokens": cache_write_12h_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
    }


def test_usage_schema_preserves_nulls_and_requires_exact_count_fields() -> None:
    observations = _module()
    usage = _usage(
        cached_input_tokens=None,
        cache_write_tokens=None,
        cache_write_30m_tokens=None,
        cache_write_12h_tokens=None,
        reasoning_output_tokens=None,
    )
    validated = observations.validate_usage(usage)
    assert validated["cached_input_tokens"] is None
    assert validated["cache_write_tokens"] is None
    assert validated["reasoning_output_tokens"] is None

    missing = dict(usage)
    del missing["output_tokens"]
    with pytest.raises(ValueError, match="usage fields"):
        observations.validate_usage(missing)

    unknown = dict(usage)
    unknown["prompt"] = "private-value-marker"
    with pytest.raises(ValueError, match="usage fields") as error:
        observations.validate_usage(unknown)
    assert "private-value-marker" not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("input_tokens", True),
        ("cached_input_tokens", -1),
        ("cache_write_tokens", MAX_SIGNED_INT + 1),
        ("output_tokens", 1.0),
        ("reasoning_output_tokens", "4"),
    ),
)
def test_usage_counts_require_nullable_exact_signed_64_bit_integers(field: str, value: object) -> None:
    observations = _module()
    usage = _usage()
    usage[field] = value
    with pytest.raises(ValueError, match=field):
        observations.validate_usage(usage)


def test_usage_validates_cache_write_and_reasoning_subset_relationships() -> None:
    observations = _module()
    valid = _usage(
        input_tokens=100,
        cached_input_tokens=30,
        cache_write_tokens=20,
        cache_write_30m_tokens=12,
        cache_write_12h_tokens=8,
        output_tokens=40,
        reasoning_output_tokens=39,
    )
    assert observations.validate_usage(valid)["input_tokens"] == 100

    invalid_cases = (
        {**valid, "cached_input_tokens": 81},
        {**valid, "cache_write_30m_tokens": 13},
        {**valid, "reasoning_output_tokens": 41},
        {**valid, "cache_write_30m_tokens": 20, "cache_write_12h_tokens": 1},
    )
    for usage in invalid_cases:
        with pytest.raises(ValueError):
            observations.validate_usage(usage)

    # Unknown cache-write details stay unknown instead of being filled with zero.
    partial = _usage(
        input_tokens=100,
        cached_input_tokens=20,
        cache_write_tokens=None,
        cache_write_30m_tokens=5,
        cache_write_12h_tokens=None,
    )
    assert observations.validate_usage(partial)["cache_write_12h_tokens"] is None

    lower_bound_overflow = _usage(
        input_tokens=100,
        cached_input_tokens=None,
        cache_write_tokens=None,
        cache_write_30m_tokens=101,
        cache_write_12h_tokens=None,
    )
    with pytest.raises(ValueError, match="cache writes"):
        observations.validate_usage(lower_bound_overflow)


def test_usage_validation_rejects_callback_bearing_subclasses_before_copying() -> None:
    observations = _module()

    class HostileMapping(dict):
        def items(self):
            raise AssertionError("must reject subclass before invoking callbacks")

    with pytest.raises(ValueError, match="built-in dictionary"):
        observations.validate_usage(HostileMapping(_usage()))

    class HostileInt(int):
        def __int__(self):
            raise AssertionError("must not coerce a subclass")

    usage = _usage()
    usage["input_tokens"] = HostileInt(100)
    with pytest.raises(ValueError, match="input_tokens"):
        observations.validate_usage(usage)


def test_validated_usage_is_detached_from_caller_mutation() -> None:
    observations = _module()
    supplied = _usage()
    validated = observations.validate_usage(supplied)
    assert validated is not supplied
    validated["input_tokens"] = 7
    assert supplied["input_tokens"] == 100


def test_decode_json_rejects_duplicate_equivalent_keys_nonfinite_and_surrogates() -> None:
    observations = _module()
    with pytest.raises(ValueError, match="duplicate"):
        observations.decode_json('{"usage": 1, "\\u0075sage": 2}')
    with pytest.raises(ValueError, match="finite"):
        observations.decode_json('{"count": NaN}')
    with pytest.raises(ValueError, match="finite"):
        observations.decode_json('{"count": 1e999}')
    with pytest.raises(ValueError, match="surrogate|Unicode"):
        observations.decode_json('{"label": "\\ud800"}')


def test_decode_json_rejects_excessive_nesting_with_a_bounded_error() -> None:
    observations = _module()
    nested = ("[" * 1_000) + "0" + ("]" * 1_000)
    with pytest.raises(ValueError, match="nesting|depth"):
        observations.decode_json(nested)


def test_decode_json_enforces_inclusive_record_byte_limit() -> None:
    observations = _module()
    at_limit = '"' + ("x" * (MAX_RECORD_BYTES - 2)) + '"'
    over_limit = at_limit + " "
    assert len(at_limit.encode("utf-8")) == MAX_RECORD_BYTES
    assert observations.decode_json(at_limit) == "x" * (MAX_RECORD_BYTES - 2)
    with pytest.raises(ValueError, match="record size"):
        observations.decode_json(over_limit)


def test_load_jsonl_enforces_record_count_and_file_limits(tmp_path: Path) -> None:
    observations = _module()
    path = tmp_path / "records.jsonl"
    path.write_text("{}\n" * MAX_JSONL_RECORDS, encoding="utf-8")
    assert len(observations.load_jsonl(path)) == MAX_JSONL_RECORDS
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="record count"):
        observations.load_jsonl(path)

    oversized = tmp_path / "sparse-oversized.jsonl"
    with oversized.open("wb") as handle:
        handle.truncate(MAX_FILE_BYTES + 1)
    before = oversized.stat().st_size
    with pytest.raises(ValueError, match="file size"):
        observations.load_jsonl(oversized)
    assert oversized.stat().st_size == before


def test_load_jsonl_bounds_reads_when_a_file_grows_after_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = _module()
    path = tmp_path / "growing.jsonl"
    path.write_bytes(b"{}\n")
    original_read = os.read
    bytes_read = 0
    grew = False

    def grow_after_first_read(fd: int, size: int) -> bytes:
        nonlocal bytes_read, grew
        chunk = original_read(fd, size)
        bytes_read += len(chunk)
        if not grew:
            os.truncate(path, MAX_FILE_BYTES + 1)
            grew = True
        return chunk

    monkeypatch.setattr(observations.os, "read", grow_after_first_read)
    with pytest.raises(ValueError, match="file size"):
        observations.load_jsonl(path)
    assert bytes_read <= MAX_FILE_BYTES + 1


def test_load_jsonl_rejects_fifo_without_waiting_for_a_writer(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    _module()
    fifo = tmp_path / "stream.jsonl"
    os.mkfifo(fifo)
    code = (
        "import importlib.util, sys; "
        f"spec=importlib.util.spec_from_file_location('harness_observations', {str(OBSERVATIONS)!r}); "
        "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
        f"module.load_jsonl({str(fifo)!r})"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert result.returncode != 0
    assert "regular file" in result.stderr


def test_load_jsonl_rejects_symlink_without_modifying_target(tmp_path: Path) -> None:
    observations = _module()
    target = tmp_path / "target.jsonl"
    target.write_bytes(b"{}\n")
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)
    before = target.read_bytes()

    with pytest.raises(ValueError, match="regular file"):
        observations.load_jsonl(link)
    assert target.read_bytes() == before


def test_snapshot_revisions_replace_in_any_arrival_order_and_scope_is_partitioned() -> None:
    observations = _module()
    first = _usage(revision=0, input_tokens=100, output_tokens=20)
    latest = _usage(revision=1, input_tokens=120, output_tokens=25)
    request = _usage(
        observation_ref="b" * 64,
        usage_scope="request",
        input_tokens=272_000,
    )
    forward = observations.summarize_usage([first, latest, request])
    reverse = observations.summarize_usage([request, latest, first])

    task_scope = forward["by_usage_scope"]["task"]
    request_scope = forward["by_usage_scope"]["request"]
    assert task_scope["complete_totals"]["input_tokens"] == 120
    assert task_scope["complete_totals"]["output_tokens"] == 25
    assert request_scope["complete_totals"]["input_tokens"] == 272_000
    assert set(forward["by_usage_scope"]) == {"task", "request"}
    assert forward["by_usage_scope"] == reverse["by_usage_scope"]


def test_identical_duplicate_snapshot_with_reordered_keys_counts_once() -> None:
    observations = _module()
    first = _usage(input_tokens=100)
    reordered_retry = dict(reversed(list(first.items())))
    summary = observations.summarize_usage([first, reordered_retry])
    task = summary["by_usage_scope"]["task"]
    assert task["coverage"]["selected_records"] == 1
    assert task["complete_totals"]["input_tokens"] == 100


@pytest.mark.parametrize("identity_field", ("source_kind", "usage_scope", "aggregation_scope"))
def test_snapshot_identity_cannot_be_rebound(identity_field: str) -> None:
    observations = _module()
    first = _usage(revision=0)
    latest = _usage(revision=1)
    rebound = _usage(revision=2)
    rebound[identity_field] = {
        "source_kind": "caller_report",
        "usage_scope": "turn",
        "aggregation_scope": "includes_children",
    }[identity_field]
    with pytest.raises(ValueError, match="identity"):
        observations.summarize_usage([first, latest, rebound])


def test_conflicting_superseded_revision_is_rejected_independent_of_key_order() -> None:
    observations = _module()
    first = _usage(revision=0, input_tokens=100)
    latest = _usage(revision=1, input_tokens=120)
    conflict = dict(reversed(list(_usage(revision=0, input_tokens=101).items())))
    with pytest.raises(ValueError, match="revision"):
        observations.summarize_usage([first, latest, conflict])


def test_excluded_aggregate_records_and_unknown_fields_never_claim_complete_totals() -> None:
    observations = _module()
    exclusive = _usage(input_tokens=100)
    children = _usage(
        observation_ref="b" * 64,
        aggregation_scope="includes_children",
        input_tokens=900,
    )
    unknown = _usage(
        observation_ref="c" * 64,
        input_tokens=None,
    )
    summary = observations.summarize_usage([exclusive, children, unknown])
    task = summary["by_usage_scope"]["task"]
    assert task["observed_totals"]["input_tokens"] == 100
    assert task["complete_totals"]["input_tokens"] is None
    assert task["coverage"]["excluded_records"] == 1
    assert task["coverage"]["unknown_records"] == 1

    all_unknown = observations.summarize_usage([_usage(input_tokens=None)])
    unknown_input = all_unknown["by_usage_scope"]["task"]
    assert unknown_input["observed_totals"]["input_tokens"] is None
    assert unknown_input["complete_totals"]["input_tokens"] is None


def test_request_exposure_uses_known_request_input_only_and_inclusive_threshold() -> None:
    observations = _module()
    rows = [
        _usage(observation_ref="a" * 64, usage_scope="request", input_tokens=272_000),
        _usage(observation_ref="b" * 64, usage_scope="request", input_tokens=272_001),
        _usage(observation_ref="c" * 64, usage_scope="turn", input_tokens=800_000),
        _usage(observation_ref="d" * 64, usage_scope="request", input_tokens=None),
    ]
    exposure = observations.summarize_usage(rows)["request_input_exposure"]
    assert exposure["over_limit_count"] == 1
    assert exposure["unknown_count"] == 1


def test_usage_derived_arithmetic_is_bounded_and_diagnostic_is_sanitized() -> None:
    observations = _module()
    left = _usage(observation_ref="a" * 64, input_tokens=MAX_SIGNED_INT)
    right = _usage(observation_ref="b" * 64, input_tokens=1)
    with pytest.raises(ValueError) as error:
        observations.summarize_usage([left, right])
    assert "a" * 64 not in str(error.value)
    assert "b" * 64 not in str(error.value)


def test_accounting_codec_is_pure_and_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    observations = _module()

    def forbidden(*args, **kwargs):
        raise AssertionError("pure accounting must not perform I/O or launch processes")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    usage = _usage()
    assert observations.validate_usage(usage)["input_tokens"] == 100
    assert observations.summarize_usage([usage])["by_usage_scope"]["task"]["complete_totals"][
        "input_tokens"
    ] == 100

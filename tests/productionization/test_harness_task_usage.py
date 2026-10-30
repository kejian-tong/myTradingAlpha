from __future__ import annotations

import base64
import builtins
import importlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/harness_task_usage.py"
ROOT_REF = "a" * 64
CHILD_REF = "b" * 64
GRANDCHILD_REF = "c" * 64
OTHER_REF = "d" * 64
RESPONSE_REF = "e" * 64
RESPONSE_REF_2 = "f" * 64
MAX_SIGNED_INT = 2**63 - 1
MAX_ROWS = 10_000
MAX_AGENTS = 256
METRICS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
    "uncached_input_tokens",
    "nonreasoning_output_tokens",
)


def _module():
    # Keep RED behavioral: the new contract is intentionally absent on base.
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        module = importlib.import_module("scripts.harness_task_usage")
    except ModuleNotFoundError as exc:
        if exc.name == "scripts.harness_task_usage":
            pytest.fail("missing explicit task usage contract: scripts.harness_task_usage")
        raise
    if not callable(getattr(module, "summarize_task_usage", None)):
        pytest.fail("missing explicit task usage contract: summarize_task_usage")
    return module


def _agent(agent_ref: str = ROOT_REF, parent_ref: str | None = None) -> dict:
    return {
        "record_type": "agent",
        "agent_ref": agent_ref,
        "parent_ref": parent_ref,
    }


def _response(
    agent_ref: str = ROOT_REF,
    response_ref: str = RESPONSE_REF,
    *,
    input_tokens: int | None = 100,
    cached_input_tokens: int | None = 20,
    output_tokens: int | None = 30,
    reasoning_output_tokens: int | None = 10,
) -> dict:
    return {
        "record_type": "response_usage",
        "agent_ref": agent_ref,
        "response_ref": response_ref,
        "usage": {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
        },
    }


def _summary(records: list | tuple, *, root_ref: str = ROOT_REF) -> dict:
    return _module().summarize_task_usage(records, root_ref=root_ref)


def _assert_summary_schema(summary: dict) -> None:
    assert set(summary) == {
        "schema_version",
        "root_ref",
        "inventory_coverage",
        "root",
        "children",
        "combined",
    }
    assert summary["schema_version"] == 1
    assert summary["root_ref"] == ROOT_REF
    assert summary["inventory_coverage"] == "explicit_inventory_only"
    group_fields = {
        "coverage_qualifier",
        "agent_count",
        "agents_with_usage",
        "agents_missing_usage",
        "response_count",
        "retry_count",
        "observed_totals",
        "complete_totals",
    }
    for name in ("root", "children", "combined"):
        group = summary[name]
        assert set(group) == group_fields
        for counter in (
            "agent_count",
            "agents_with_usage",
            "agents_missing_usage",
            "response_count",
            "retry_count",
        ):
            assert type(group[counter]) is int
            assert group[counter] >= 0
        assert set(group["observed_totals"]) == set(METRICS)
        assert set(group["complete_totals"]) == set(METRICS)
        for totals in (group["observed_totals"], group["complete_totals"]):
            assert all(value is None or type(value) is int for value in totals.values())
        assert group["coverage_qualifier"] in {
            "explicit_inventory_only",
            "empty_supplied_group",
        }


def _assert_fixed_error(error: ValueError, *secrets: str) -> None:
    message = str(error)
    assert 0 < len(message.encode("utf-8")) <= 256
    assert type(error) is ValueError
    assert error.__cause__ is None
    assert all(secret not in message for secret in secrets)


def _assert_rejected(records: object, *secrets: str, root_ref: str = ROOT_REF) -> None:
    module = _module()
    with pytest.raises(ValueError) as error:
        module.summarize_task_usage(records, root_ref=root_ref)
    _assert_fixed_error(error.value, *secrets)


def _run_cli(
    observations: Path,
    *,
    root_ref: str = ROOT_REF,
    extra_args: tuple[str, ...] = (),
    cwd: Path,
    timeout: float = 5,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--observations",
            str(observations),
            "--root-ref",
            root_ref,
            *extra_args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _assert_cli_failure(result: subprocess.CompletedProcess[str], *secrets: str) -> None:
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Traceback" not in output
    assert len(output.encode("utf-8")) <= 512
    assert all(secret not in output for secret in secrets)


def test_task_usage_reports_root_children_combined_and_subset_arithmetic() -> None:
    records = [
        _agent(ROOT_REF),
        _agent(CHILD_REF, ROOT_REF),
        _response(
            input_tokens=100,
            cached_input_tokens=20,
            output_tokens=40,
            reasoning_output_tokens=10,
        ),
        _response(
            response_ref=RESPONSE_REF_2,
            input_tokens=50,
            cached_input_tokens=5,
            output_tokens=12,
            reasoning_output_tokens=2,
        ),
        _response(
            CHILD_REF,
            "1" * 64,
            input_tokens=20,
            cached_input_tokens=5,
            output_tokens=8,
            reasoning_output_tokens=3,
        ),
    ]

    summary = _summary(records)

    _assert_summary_schema(summary)
    root = summary["root"]
    assert root["agent_count"] == 1
    assert root["agents_with_usage"] == 1
    assert root["agents_missing_usage"] == 0
    assert root["response_count"] == 2
    assert root["retry_count"] == 0
    assert root["observed_totals"] == root["complete_totals"]
    assert root["complete_totals"] == {
        "input_tokens": 150,
        "cached_input_tokens": 25,
        "output_tokens": 52,
        "reasoning_output_tokens": 12,
        "total_tokens": 202,
        "uncached_input_tokens": 125,
        "nonreasoning_output_tokens": 40,
    }

    children = summary["children"]
    assert children["agent_count"] == 1
    assert children["agents_with_usage"] == 1
    assert children["agents_missing_usage"] == 0
    assert children["response_count"] == 1
    assert children["complete_totals"] == {
        "input_tokens": 20,
        "cached_input_tokens": 5,
        "output_tokens": 8,
        "reasoning_output_tokens": 3,
        "total_tokens": 28,
        "uncached_input_tokens": 15,
        "nonreasoning_output_tokens": 5,
    }

    combined = summary["combined"]
    assert combined["agent_count"] == 2
    assert combined["response_count"] == 3
    assert combined["complete_totals"]["total_tokens"] == 230
    assert combined["complete_totals"]["uncached_input_tokens"] == 140
    assert combined["complete_totals"]["nonreasoning_output_tokens"] == 45
    # Cached and reasoning counts are subsets, not additional total tokens.
    assert combined["complete_totals"]["total_tokens"] == 150 + 20 + 52 + 8


def test_missing_response_and_null_metrics_remain_incomplete_and_disclosed() -> None:
    records = [
        _agent(ROOT_REF),
        _response(
            input_tokens=10,
            cached_input_tokens=2,
            output_tokens=3,
            reasoning_output_tokens=1,
        ),
        _response(
            CHILD_REF,
            "2" * 64,
            input_tokens=None,
            cached_input_tokens=0,
            output_tokens=6,
            reasoning_output_tokens=None,
        ),
        _agent(CHILD_REF, ROOT_REF),
        _agent(GRANDCHILD_REF, CHILD_REF),
    ]

    summary = _summary(records)

    children = summary["children"]
    assert children["agent_count"] == 2
    assert children["agents_with_usage"] == 1
    assert children["agents_missing_usage"] == 1
    assert children["response_count"] == 1
    assert children["observed_totals"]["input_tokens"] is None
    assert children["complete_totals"]["input_tokens"] is None
    assert children["complete_totals"]["total_tokens"] is None

    combined = summary["combined"]
    assert combined["agents_with_usage"] == 2
    assert combined["agents_missing_usage"] == 1
    assert combined["response_count"] == 2
    assert combined["observed_totals"]["input_tokens"] == 10
    assert combined["observed_totals"]["cached_input_tokens"] == 2
    assert combined["observed_totals"]["output_tokens"] == 9
    assert combined["complete_totals"]["input_tokens"] is None
    assert combined["complete_totals"]["reasoning_output_tokens"] is None
    assert combined["complete_totals"]["total_tokens"] is None


def test_no_response_is_unknown_while_an_empty_children_group_is_qualified() -> None:
    summary = _summary([_agent(ROOT_REF)])

    root = summary["root"]
    assert root["agent_count"] == 1
    assert root["agents_with_usage"] == 0
    assert root["agents_missing_usage"] == 1
    assert root["observed_totals"]["input_tokens"] is None
    assert root["complete_totals"]["input_tokens"] is None

    children = summary["children"]
    assert children["agent_count"] == 0
    assert children["coverage_qualifier"] == "empty_supplied_group"
    assert children["complete_totals"]["input_tokens"] == 0
    assert summary["inventory_coverage"] == "explicit_inventory_only"


def test_global_retry_dedup_is_order_independent_and_rows_may_precede_registration() -> None:
    response = _response(CHILD_REF, RESPONSE_REF)
    reordered = {
        "usage": dict(reversed(list(response["usage"].items()))),
        "response_ref": response["response_ref"],
        "agent_ref": response["agent_ref"],
        "record_type": response["record_type"],
    }
    rows = [
        response,
        _agent(CHILD_REF, ROOT_REF),
        reordered,
        _agent(ROOT_REF),
    ]

    first = _summary(rows)
    second = _summary(
        [
            _agent(ROOT_REF),
            _agent(CHILD_REF, ROOT_REF),
            reordered,
            response,
        ]
    )

    assert first == second
    assert first["root"]["response_count"] == 0
    assert first["children"]["response_count"] == 1
    assert first["children"]["retry_count"] == 1
    assert first["combined"]["response_count"] == 1
    assert first["combined"]["retry_count"] == 1


@pytest.mark.parametrize("conflict", ("owner", "count", "null"))
def test_response_reference_cannot_be_rebound_or_partially_revised(conflict: str) -> None:
    first = _response(ROOT_REF, RESPONSE_REF)
    second = _response(ROOT_REF, RESPONSE_REF)
    if conflict == "owner":
        second["agent_ref"] = CHILD_REF
    elif conflict == "count":
        second["usage"]["output_tokens"] = 31
    else:
        second["usage"]["output_tokens"] = None
    _assert_rejected(
        [_agent(ROOT_REF), _agent(CHILD_REF, ROOT_REF), first, second],
        *("private-response-marker",),
    )


def test_identical_agent_registration_deduplicates_and_conflicting_parent_rejects() -> None:
    summary = _summary(
        [
            _agent(ROOT_REF),
            _agent(CHILD_REF, ROOT_REF),
            _agent(CHILD_REF, ROOT_REF),
            _response(CHILD_REF),
        ]
    )
    assert summary["combined"]["agent_count"] == 2

    _assert_rejected(
        [
            _agent(ROOT_REF),
            _agent(CHILD_REF, ROOT_REF),
            _agent(OTHER_REF, ROOT_REF),
            _agent(CHILD_REF, OTHER_REF),
        ]
    )


@pytest.mark.parametrize(
    "records",
    (
        [_agent(ROOT_REF), _agent(CHILD_REF, OTHER_REF)],
        [_agent(ROOT_REF), _agent(CHILD_REF, CHILD_REF)],
        [_agent(ROOT_REF), _agent(CHILD_REF, GRANDCHILD_REF), _agent(GRANDCHILD_REF, CHILD_REF)],
        [_agent(ROOT_REF), _agent(CHILD_REF, None)],
        [_agent(CHILD_REF, ROOT_REF)],
        [_agent(ROOT_REF, CHILD_REF), _agent(CHILD_REF, ROOT_REF)],
        [_agent(ROOT_REF), _response(CHILD_REF)],
    ),
    ids=(
        "unknown-parent",
        "self-parent",
        "cycle",
        "second-root",
        "missing-selected-root",
        "selected-root-has-parent",
        "unknown-response-owner",
    ),
)
def test_inventory_must_be_a_single_connected_rooted_graph(records: list[dict]) -> None:
    _assert_rejected(records, *("private-graph-marker",))


@pytest.mark.parametrize(
    "row",
    (
        {"record_type": "agent", "agent_ref": ROOT_REF},
        {**_agent(), "unexpected": "private-field-marker"},
        {
            "record_type": "response_usage",
            "agent_ref": ROOT_REF,
            "response_ref": RESPONSE_REF,
        },
        {**_response(), "unexpected": "private-field-marker"},
    ),
    ids=("missing-agent-parent", "extra-agent-field", "missing-usage", "extra-usage-field"),
)
def test_exact_row_schemas_and_unknown_fields_fail_closed(row: dict) -> None:
    _assert_rejected([_agent(ROOT_REF), row], *("private-field-marker",))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("input_tokens", True),
        ("cached_input_tokens", -1),
        ("output_tokens", MAX_SIGNED_INT + 1),
        ("reasoning_output_tokens", 1.0),
        ("input_tokens", "private-count-marker"),
    ),
)
def test_counts_are_nullable_exact_nonnegative_signed_64_bit_integers(
    field: str,
    value: object,
) -> None:
    usage = _response()["usage"]
    usage[field] = value
    _assert_rejected(
        [_agent(ROOT_REF), {**_response(), "usage": usage}],
        *("private-count-marker",),
    )


def test_known_subset_relationships_are_enforced_but_unknown_operands_stay_unknown() -> None:
    too_much_cache = _response(input_tokens=10, cached_input_tokens=11)
    too_much_reasoning = _response(output_tokens=10, reasoning_output_tokens=11)
    _assert_rejected([_agent(ROOT_REF), too_much_cache])
    _assert_rejected([_agent(ROOT_REF), too_much_reasoning])

    summary = _summary(
        [
            _agent(ROOT_REF),
            _response(
                input_tokens=None,
                cached_input_tokens=5,
                output_tokens=None,
                reasoning_output_tokens=2,
            ),
        ]
    )
    assert summary["root"]["complete_totals"]["input_tokens"] is None
    assert summary["root"]["complete_totals"]["output_tokens"] is None


def test_hostile_collections_and_scalar_subclasses_are_rejected_before_callbacks() -> None:
    module = _module()

    class HostileList(list):
        def __iter__(self):
            raise AssertionError("list subclass callback must not run")

    class HostileDict(dict):
        def keys(self):
            raise AssertionError("mapping subclass callback must not run")

        def items(self):
            raise AssertionError("mapping subclass callback must not run")

        def __iter__(self):
            raise AssertionError("mapping subclass callback must not run")

    class HostileString(str):
        def __hash__(self):
            raise AssertionError("string subclass hash must not run")

        def __eq__(self, other):
            raise AssertionError("string subclass equality must not run")

    class CountedKey(str):
        hash_calls = 0

        def __hash__(self):
            type(self).hash_calls += 1
            return str.__hash__(self)

        def __eq__(self, other):
            raise AssertionError("string subclass equality must not run")

    class HostileInt(int):
        def __int__(self):
            raise AssertionError("integer subclass conversion must not run")

    with pytest.raises(ValueError) as error:
        module.summarize_task_usage(HostileList([_agent(ROOT_REF)]), root_ref=ROOT_REF)
    _assert_fixed_error(error.value)

    def callback_records():
        raise AssertionError("non-built-in iterable must not be consumed")
        yield _agent(ROOT_REF)

    with pytest.raises(ValueError) as error:
        module.summarize_task_usage(callback_records(), root_ref=ROOT_REF)
    _assert_fixed_error(error.value)

    with pytest.raises(ValueError) as error:
        module.summarize_task_usage([HostileDict(_agent(ROOT_REF))], root_ref=ROOT_REF)
    _assert_fixed_error(error.value)

    hostile_usage = _response()
    hostile_usage["usage"] = HostileDict(hostile_usage["usage"])
    with pytest.raises(ValueError) as error:
        module.summarize_task_usage([_agent(ROOT_REF), hostile_usage], root_ref=ROOT_REF)
    _assert_fixed_error(error.value)

    hostile_key = CountedKey("unexpected")
    invalid_key_row = _agent(ROOT_REF)
    invalid_key_row[hostile_key] = "private-key-marker"
    CountedKey.hash_calls = 0
    with pytest.raises(ValueError) as error:
        module.summarize_task_usage([invalid_key_row], root_ref=ROOT_REF)
    _assert_fixed_error(error.value, "private-key-marker")
    assert CountedKey.hash_calls == 0

    hostile_id = _agent(ROOT_REF)
    hostile_id["agent_ref"] = HostileString(ROOT_REF)
    with pytest.raises(ValueError) as error:
        module.summarize_task_usage([hostile_id], root_ref=ROOT_REF)
    _assert_fixed_error(error.value)

    with pytest.raises(ValueError) as error:
        module.summarize_task_usage([_agent(ROOT_REF)], root_ref=HostileString(ROOT_REF))
    _assert_fixed_error(error.value)

    hostile_count = _response()
    hostile_count["usage"]["input_tokens"] = HostileInt(100)
    with pytest.raises(ValueError) as error:
        module.summarize_task_usage([_agent(ROOT_REF), hostile_count], root_ref=ROOT_REF)
    _assert_fixed_error(error.value)


@pytest.mark.parametrize("container_type", (list, tuple), ids=("list", "tuple"))
@pytest.mark.parametrize("equality_mode", ("raises", "deceptive"))
def test_sequence_subclasses_with_hostile_metaclass_are_rejected_before_callbacks(
    container_type: type, equality_mode: str
) -> None:
    module = _module()
    calls = {"equality": 0, "length": 0, "iteration": 0}

    class HostileSequenceMeta(type):
        def __eq__(cls, other: object) -> bool:
            calls["equality"] += 1
            if equality_mode == "raises":
                raise RuntimeError("private metaclass equality marker")
            return True

        __hash__ = type.__hash__

    class HostileSequence(container_type, metaclass=HostileSequenceMeta):
        def __len__(self) -> int:
            calls["length"] += 1
            raise RuntimeError("private sequence length marker")

        def __iter__(self):
            calls["iteration"] += 1
            raise RuntimeError("private sequence iteration marker")

    records = HostileSequence([_agent(ROOT_REF)])
    error = None
    try:
        module.summarize_task_usage(records, root_ref=ROOT_REF)
    except BaseException as exc:
        error = exc

    assert calls == {"equality": 0, "length": 0, "iteration": 0}
    assert type(error) is ValueError
    _assert_fixed_error(error)


def test_identifier_validation_and_errors_do_not_echo_untrusted_values() -> None:
    secret = "private-identifier-marker"
    bad_agent = _agent(secret, ROOT_REF)
    _assert_rejected([_agent(ROOT_REF), bad_agent], secret)

    bad_response = _response(response_ref=secret)
    _assert_rejected([_agent(ROOT_REF), bad_response], *[secret])
    _assert_rejected([_agent(ROOT_REF)], secret, root_ref=secret)

    for invalid_id in ("A" * 64, "g" * 64):
        _assert_rejected([_agent(ROOT_REF), _agent(invalid_id, ROOT_REF)])


def test_caller_mutation_cannot_change_an_already_created_summary() -> None:
    root = _agent(ROOT_REF)
    response = _response()
    records = [root, response]
    summary = _summary(records)
    before = json.dumps(summary, sort_keys=True)

    response["usage"]["input_tokens"] = 999
    response["response_ref"] = "9" * 64
    records.append(_agent(CHILD_REF, ROOT_REF))
    root["parent_ref"] = CHILD_REF

    assert json.dumps(summary, sort_keys=True) == before
    assert summary["combined"]["agent_count"] == 1


def test_input_row_and_agent_limits_are_inclusive_and_graph_walk_is_iterative() -> None:
    module = _module()
    duplicate_rows = [_agent(ROOT_REF) for _ in range(MAX_ROWS)]
    at_row_limit = module.summarize_task_usage(duplicate_rows, root_ref=ROOT_REF)
    assert at_row_limit["combined"]["agent_count"] == 1
    _assert_rejected([*duplicate_rows, _agent(ROOT_REF)])

    ids = [f"{index:064x}" for index in range(MAX_AGENTS + 1)]
    at_agent_limit = [_agent(ids[0])]
    at_agent_limit.extend(
        _agent(ids[index], ids[index - 1]) for index in range(1, MAX_AGENTS)
    )
    at_agent_limit_summary = module.summarize_task_usage(
        tuple(reversed(at_agent_limit)), root_ref=ids[0]
    )
    assert at_agent_limit_summary["combined"]["agent_count"] == MAX_AGENTS
    assert at_agent_limit_summary["combined"]["agents_missing_usage"] == MAX_AGENTS

    over_agent_limit = [_agent(ids[0])]
    over_agent_limit.extend(
        _agent(ids[index], ids[index - 1]) for index in range(1, MAX_AGENTS + 1)
    )
    _assert_rejected(over_agent_limit, root_ref=ids[0])


def test_cli_jsonl_record_count_limit_is_inclusive(tmp_path: Path) -> None:
    _module()
    path = tmp_path / "many-rows.jsonl"
    row = (json.dumps(_agent(ROOT_REF), separators=(",", ":")) + "\n").encode()
    path.write_bytes(row * MAX_ROWS)

    at_limit = _run_cli(path, cwd=tmp_path)
    assert at_limit.returncode == 0, at_limit.stderr
    assert json.loads(at_limit.stdout)["combined"]["agent_count"] == 1

    with path.open("ab") as handle:
        handle.write(row)
    over_limit = _run_cli(path, cwd=tmp_path)
    _assert_cli_failure(over_limit, str(path))


def test_cli_jsonl_file_size_limit_rejects_without_echoing_path(tmp_path: Path) -> None:
    _module()
    path = tmp_path / "oversized-file.jsonl"
    with path.open("wb") as handle:
        handle.truncate(16_777_217)

    result = _run_cli(path, cwd=tmp_path)

    _assert_cli_failure(result, str(path))


def test_aggregate_and_derived_arithmetic_reject_signed_64_bit_overflow() -> None:
    aggregate_overflow = [
        _agent(ROOT_REF),
        _agent(CHILD_REF, ROOT_REF),
        _response(input_tokens=MAX_SIGNED_INT, cached_input_tokens=0),
        _response(
            CHILD_REF,
            RESPONSE_REF_2,
            input_tokens=1,
            cached_input_tokens=0,
        ),
    ]
    _assert_rejected(aggregate_overflow)

    derived_overflow = [
        _agent(ROOT_REF),
        _response(
            input_tokens=MAX_SIGNED_INT,
            cached_input_tokens=0,
            output_tokens=1,
            reasoning_output_tokens=0,
        ),
    ]
    _assert_rejected(derived_overflow)


def test_summary_is_bounded_and_contains_only_fixed_allowlisted_data() -> None:
    summary = _summary([_agent(ROOT_REF), _response()])
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    assert len(encoded.encode("utf-8")) <= 4_096
    assert "prompt" not in encoded
    assert "response_ref" not in encoded
    assert "reasoning text" not in encoded


def test_summarizer_has_no_network_process_or_persistence_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def forbidden(*args, **kwargs):
        raise AssertionError("pure task usage summarization attempted a side effect")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)

    summary = module.summarize_task_usage([_agent(ROOT_REF), _response()], root_ref=ROOT_REF)
    assert summary["combined"]["complete_totals"]["total_tokens"] == 130


def test_cli_reads_only_one_explicit_jsonl_file_and_accepts_escaped_ids(tmp_path: Path) -> None:
    _module()
    observations = tmp_path / "selected.jsonl"
    escaped_root = "\\u0061" * 64
    agent_line = (
        '{"record_type":"agent","agent_ref":"'
        + escaped_root
        + '","parent_ref":null}'
    )
    response_line = json.dumps(_response(), separators=(",", ":"))
    observations.write_text(agent_line + "\n" + response_line + "\n", encoding="utf-8")
    ignored = tmp_path / "ignored.jsonl"
    ignored.write_text(
        json.dumps(_agent(CHILD_REF, ROOT_REF)) + "\n", encoding="utf-8"
    )

    result = _run_cli(observations, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    summary = json.loads(result.stdout)
    _assert_summary_schema(summary)
    assert summary["combined"]["agent_count"] == 1
    assert summary["combined"]["response_count"] == 1


@pytest.mark.parametrize(
    "contents",
    (
        b'{"record_type":"agent","record_type":"agent"}\n',
        b'{"record_type":"agent","agent_ref":"\\ud800"}\n',
        b'{"record_type":"agent"}\xff\n',
        b'{"record_type":"agent","unused":"' + (b"x" * 16_384) + b'"}\n',
    ),
    ids=("duplicate-json-key", "escaped-surrogate", "invalid-utf8", "oversized-row"),
)
def test_cli_strict_jsonl_errors_are_bounded_and_redacted(
    tmp_path: Path,
    contents: bytes,
) -> None:
    _module()
    path = tmp_path / "malformed-input.jsonl"
    path.write_bytes(contents)

    result = _run_cli(path, cwd=tmp_path)

    _assert_cli_failure(result, str(path))


def test_cli_parser_file_and_root_errors_do_not_echo_untrusted_values(tmp_path: Path) -> None:
    _module()
    valid = tmp_path / "valid.jsonl"
    valid.write_text(json.dumps(_agent(ROOT_REF)) + "\n", encoding="utf-8")
    marker = "private-cli-marker"

    parser_error = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--observations",
            str(valid),
            "--root-ref",
            ROOT_REF,
            "--unexpected",
            marker,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    _assert_cli_failure(parser_error, marker)

    missing = tmp_path / f"{marker}.jsonl"
    file_error = _run_cli(missing, cwd=tmp_path)
    _assert_cli_failure(file_error, marker, str(missing))

    root_error = _run_cli(valid, root_ref=marker, cwd=tmp_path)
    _assert_cli_failure(root_error, marker)


def test_cli_rejects_symlinks_without_modifying_the_target(tmp_path: Path) -> None:
    _module()
    target = tmp_path / "target.jsonl"
    target.write_text(json.dumps(_agent(ROOT_REF)) + "\n", encoding="utf-8")
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)
    before = target.read_bytes()

    result = _run_cli(link, cwd=tmp_path)

    _assert_cli_failure(result, str(link))
    assert target.read_bytes() == before


def test_cli_rejects_fifo_without_waiting_for_a_writer(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    _module()
    fifo = tmp_path / "stream.jsonl"
    os.mkfifo(fifo)

    result = _run_cli(fifo, cwd=tmp_path, timeout=3)

    _assert_cli_failure(result, str(fifo))


@pytest.mark.parametrize("missing", (True, False), ids=("missing-key", "extra-key"))
def test_nested_usage_requires_the_exact_counter_schema(missing: bool) -> None:
    response = _response()
    if missing:
        del response["usage"]["input_tokens"]
    else:
        response["usage"]["unexpected"] = "private-nested-usage-marker"

    _assert_rejected(
        [_agent(ROOT_REF), response],
        "private-nested-usage-marker",
    )


def test_hostile_record_type_and_nested_usage_key_are_rejected_before_callbacks() -> None:
    module = _module()

    class HostileString(str):
        def __hash__(self):
            raise AssertionError("record_type subclass hash must not run")

        def __eq__(self, other):
            raise AssertionError("record_type subclass equality must not run")

    class CountedKey(str):
        hash_calls = 0

        def __hash__(self):
            type(self).hash_calls += 1
            return str.__hash__(self)

        def __eq__(self, other):
            raise AssertionError("usage-key subclass equality must not run")

    hostile_type = _agent(ROOT_REF)
    hostile_type["record_type"] = HostileString("agent")
    with pytest.raises(ValueError) as error:
        module.summarize_task_usage([hostile_type], root_ref=ROOT_REF)
    _assert_fixed_error(error.value)

    response = _response()
    key = CountedKey("unexpected")
    response["usage"][key] = "private-hostile-usage-key-marker"
    CountedKey.hash_calls = 0
    with pytest.raises(ValueError) as error:
        module.summarize_task_usage([_agent(ROOT_REF), response], root_ref=ROOT_REF)
    _assert_fixed_error(error.value, "private-hostile-usage-key-marker")
    assert CountedKey.hash_calls == 0


def test_per_metric_completeness_and_observed_subtotals_use_known_response_operands() -> None:
    summary = _summary(
        [
            _agent(ROOT_REF),
            _agent(CHILD_REF, ROOT_REF),
            _response(
                input_tokens=10,
                cached_input_tokens=None,
                output_tokens=2,
                reasoning_output_tokens=None,
            ),
            _response(
                CHILD_REF,
                "9" * 64,
                input_tokens=None,
                cached_input_tokens=5,
                output_tokens=8,
                reasoning_output_tokens=3,
            ),
        ]
    )

    combined = summary["combined"]
    assert combined["observed_totals"] == {
        "input_tokens": 10,
        "cached_input_tokens": 5,
        "output_tokens": 10,
        "reasoning_output_tokens": 3,
        "total_tokens": 12,
        "uncached_input_tokens": None,
        "nonreasoning_output_tokens": 5,
    }
    assert combined["complete_totals"] == {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": 10,
        "reasoning_output_tokens": None,
        "total_tokens": None,
        "uncached_input_tokens": None,
        "nonreasoning_output_tokens": None,
    }
    # The root has input but no cached count; the child has cache but no input.
    # Subtracting the aggregate partial sums would fabricate uncached_input=5.
    assert combined["observed_totals"]["uncached_input_tokens"] is None


def test_encoded_secrets_are_redacted_from_nested_api_json_parser_and_path_errors(
    tmp_path: Path,
) -> None:
    raw_secret = "private sentinel:alpha"
    base64_secret = base64.b64encode(raw_secret.encode("utf-8")).decode("ascii")
    url_secret = quote(raw_secret, safe="")
    secrets = (raw_secret, base64_secret, url_secret)

    malformed = _response()
    malformed["usage"][raw_secret] = base64_secret
    malformed["usage"]["output_tokens"] = url_secret
    _assert_rejected([_agent(ROOT_REF), malformed], *secrets)

    nested_path = tmp_path / f"{raw_secret}.jsonl"
    nested_path.write_text(
        json.dumps(_agent(ROOT_REF))
        + "\n"
        + json.dumps(malformed)
        + "\n",
        encoding="utf-8",
    )
    nested_cli_error = _run_cli(nested_path, cwd=tmp_path)
    _assert_cli_failure(nested_cli_error, *secrets, str(nested_path))

    invalid_json = tmp_path / "invalid-secret.jsonl"
    invalid_json.write_text(
        '{"record_type":"agent","unused":"'
        + raw_secret
        + base64_secret
        + url_secret
        + '"\n',
        encoding="utf-8",
    )
    json_error = _run_cli(invalid_json, cwd=tmp_path)
    _assert_cli_failure(json_error, *secrets)

    valid = tmp_path / "valid-secret.jsonl"
    valid.write_text(json.dumps(_agent(ROOT_REF)) + "\n", encoding="utf-8")
    parser_error = _run_cli(
        valid,
        cwd=tmp_path,
        extra_args=("--unexpected", *secrets),
    )
    _assert_cli_failure(parser_error, *secrets)

    missing_path = tmp_path / f"{raw_secret}-{base64_secret}-{url_secret}.jsonl"
    path_error = _run_cli(missing_path, cwd=tmp_path)
    _assert_cli_failure(path_error, *secrets, str(missing_path))

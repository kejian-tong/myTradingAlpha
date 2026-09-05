"""SIG-01 canonical cached graph-response contract.

All records in this module and its JSON fixture are deterministic contract
fixtures. They are not production captures and do not represent real inference.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from mytradingalpha.data.bundle import BundleReplayPolicy
from mytradingalpha.data.provenance import SourceManifest
from mytradingalpha.research.cached_response import (
    CACHED_RESPONSE_SCHEMA_VERSION,
    MAX_CACHED_RESPONSE_BYTES,
    MAX_CACHED_RESPONSE_DEPTH,
    MAX_CACHED_RESPONSE_NODES,
    MAX_CACHED_RESPONSE_STRING_BYTES,
    CachedGraphResponse,
    CachedGraphResponseConflictError,
    CachedGraphResponseCorruptionError,
    CachedGraphResponseMismatchError,
    CachedGraphResponseRepository,
    CachedGraphResponseUnavailableError,
    CachedGraphSelection,
    build_cached_graph_response,
    parse_cached_graph_response,
)
from tests.productionization.data.test_bundle_replay import _build as build_fixture_bundle
from tradingagents.graph.historical import HistoricalRuntimeOutputError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/research/cached_graph_response_v1.json"
RESPONSE_DOMAIN = b"mytradingalpha.cached_graph_response.v1\x00"
RESPONSE_ID = "cached-response-sig01-v1"
GRAPH_ARTIFACT_ID = "graph-artifact-v1"
GRAPH_ARTIFACT_HASH = f"sha256:{'1' * 64}"
MODEL_ARTIFACT_ID = "model-artifact-v1"
MODEL_ARTIFACT_HASH = f"sha256:{'2' * 64}"
RUNTIME_MANIFEST_ID = "runtime-manifest-v1"
RUNTIME_MANIFEST_HASH = f"sha256:{'3' * 64}"


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def checksum(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical(value)).hexdigest()}"


def response_hash(payload_without_hash: dict[str, object]) -> str:
    return f"sha256:{hashlib.sha256(RESPONSE_DOMAIN + canonical(payload_without_hash)).hexdigest()}"


def rehash_record_payload(payload: dict[str, object]) -> dict[str, object]:
    output_hash = checksum(payload["output"])
    payload["output_hash"] = output_hash
    payload["capture_manifest"]["checksum"] = output_hash
    hash_payload = {key: value for key, value in payload.items() if key != "response_hash"}
    payload["response_hash"] = response_hash(hash_payload)
    return payload


def make_output(*, rating: str = "Hold") -> dict[str, object]:
    return {
        "asset_type": "stock",
        "company_of_interest": "NEW",
        "final_trade_decision": f"**Rating**: {rating}\n\nDeterministic cached research fixture.",
        "fundamentals_report": "Fixture fundamentals evidence summary.",
        "instrument_context": "Symbol: NEW; instrument_id: inst-acme; asset_class: equity; exchange: XNYS; currency: USD",
        "investment_debate_state": {
            "bear_history": "",
            "bull_history": "",
            "count": 0,
            "current_response": "",
            "history": "",
            "judge_decision": "",
        },
        "investment_plan": "Fixture prose investment plan.",
        "market_report": "Fixture market evidence summary.",
        "messages": [
            ["human", "NEW"],
            {
                "role": "assistant",
                "content": "Fixture research response.",
                "response_metadata": {"source": "test-only-cache"},
            },
        ],
        "news_report": "Fixture news evidence summary.",
        "past_context": "",
        "risk_debate_state": {
            "aggressive_history": "",
            "conservative_history": "",
            "count": 0,
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "history": "",
            "judge_decision": "",
            "latest_speaker": "",
            "neutral_history": "",
        },
        "sentiment_report": "Fixture sentiment evidence summary.",
        "trade_date": "2024-06-30",
        "trader_investment_plan": "Fixture prose trader plan.",
    }


def make_capture_manifest(output: object, **updates: object) -> SourceManifest:
    fields: dict[str, object] = {
        "schema_version": "v1",
        "manifest_id": "cached-response-capture-v1",
        "source": "test-fixture",
        "source_locator": "fixture://research/cached-response/v1",
        "fetched_at": "2024-06-30T23:59:59Z",
        "event_time": "2024-06-30T23:59:59Z",
        "published_at": "2024-06-30T23:59:59Z",
        "available_at": "2024-06-30T23:59:59Z",
        "ingested_at": "2024-06-30T23:59:59Z",
        "checksum": checksum(output),
        "terms": "synthetic-test-fixture",
        "revision": 0,
    }
    fields.update(updates)
    return SourceManifest(**fields)  # type: ignore[arg-type]


def make_response_kwargs(
    *,
    bundle: object | None = None,
    context: object | None = None,
    output: dict[str, object] | None = None,
    **updates: object,
) -> dict[str, object]:
    bundle = bundle or build_fixture_bundle()
    output = output or make_output()
    capture_manifest = updates.pop("capture_manifest", None)
    if capture_manifest is None:
        capture_manifest = make_capture_manifest(output)
    fields: dict[str, object] = {
        "schema_version": CACHED_RESPONSE_SCHEMA_VERSION,
        "response_id": RESPONSE_ID,
        "bundle_id": bundle.bundle_id,
        "bundle_hash": bundle.bundle_hash,
        "knowledge_cutoff": bundle.knowledge_cutoff,
        "calendar_id": bundle.calendar.calendar_id,
        "replay_policy": bundle.replay_policy,
        "variant_id": "variant-research-adapter",
        "trade_date": "2024-06-30",
        "ticker": "NEW",
        "instrument_id": "inst-acme",
        "asset_type": "stock",
        "instrument_context": str(output["instrument_context"]),
        "graph_artifact_id": GRAPH_ARTIFACT_ID,
        "graph_artifact_hash": GRAPH_ARTIFACT_HASH,
        "model_artifact_id": MODEL_ARTIFACT_ID,
        "model_artifact_hash": MODEL_ARTIFACT_HASH,
        "runtime_manifest_id": RUNTIME_MANIFEST_ID,
        "runtime_manifest_hash": RUNTIME_MANIFEST_HASH,
        "capture_manifest": capture_manifest,
        "output": output,
    }
    if context is not None:
        fields["variant_id"] = context.variant_id
    fields.update(updates)
    return fields


def make_selection(
    *, expected_response_hash: str | None = None, **updates: object
) -> CachedGraphSelection:
    fields: dict[str, object] = {
        "response_id": RESPONSE_ID,
        "expected_response_hash": expected_response_hash or f"sha256:{'0' * 64}",
        "graph_artifact_id": GRAPH_ARTIFACT_ID,
        "graph_artifact_hash": GRAPH_ARTIFACT_HASH,
        "model_artifact_id": MODEL_ARTIFACT_ID,
        "model_artifact_hash": MODEL_ARTIFACT_HASH,
        "runtime_manifest_id": RUNTIME_MANIFEST_ID,
        "runtime_manifest_hash": RUNTIME_MANIFEST_HASH,
    }
    fields.update(updates)
    return CachedGraphSelection(**fields)  # type: ignore[arg-type]


def bound_kwargs(record: CachedGraphResponse, **updates: object) -> dict[str, object]:
    fields = {
        name: getattr(record, name)
        for name in (
            "bundle_id",
            "bundle_hash",
            "knowledge_cutoff",
            "calendar_id",
            "replay_policy",
            "variant_id",
            "trade_date",
            "ticker",
            "instrument_id",
            "asset_type",
            "instrument_context",
        )
    }
    fields.update(updates)
    return fields


def test_schema_and_limits_are_exact() -> None:
    assert CACHED_RESPONSE_SCHEMA_VERSION == "v1"
    assert MAX_CACHED_RESPONSE_BYTES == 4_194_304
    assert MAX_CACHED_RESPONSE_DEPTH == 64
    assert MAX_CACHED_RESPONSE_NODES == 100_000
    assert MAX_CACHED_RESPONSE_STRING_BYTES == 1_048_576
    assert CachedGraphSelection.model_config["frozen"] is True
    assert CachedGraphResponse.model_config["frozen"] is True
    assert set(CachedGraphSelection.model_fields) == {
        "response_id",
        "expected_response_hash",
        "graph_artifact_id",
        "graph_artifact_hash",
        "model_artifact_id",
        "model_artifact_hash",
        "runtime_manifest_id",
        "runtime_manifest_hash",
    }
    assert set(CachedGraphResponse.model_fields) == {
        "schema_version",
        "response_id",
        "response_hash",
        "bundle_id",
        "bundle_hash",
        "knowledge_cutoff",
        "calendar_id",
        "replay_policy",
        "variant_id",
        "trade_date",
        "ticker",
        "instrument_id",
        "asset_type",
        "instrument_context",
        "graph_artifact_id",
        "graph_artifact_hash",
        "model_artifact_id",
        "model_artifact_hash",
        "runtime_manifest_id",
        "runtime_manifest_hash",
        "capture_manifest",
        "output",
        "output_hash",
    }


def test_fixture_is_exact_canonical_round_trip_and_repeatable() -> None:
    # The repository text fixture has one conventional final newline; the sealed
    # payload supplied to production is the exact canonical JSON value bytes.
    raw = FIXTURE.read_bytes().removesuffix(b"\n")
    record = parse_cached_graph_response(raw)
    rebuilt = build_cached_graph_response(**make_response_kwargs())
    assert raw == rebuilt == build_cached_graph_response(**make_response_kwargs())
    assert canonical(json.loads(raw)) == raw
    assert parse_cached_graph_response(raw) == record
    assert record.output == make_output()


def test_output_and_domain_separated_response_hashes_bind_exact_bytes() -> None:
    raw = build_cached_graph_response(**make_response_kwargs())
    payload = json.loads(raw)
    declared_response_hash = payload.pop("response_hash")
    assert payload["output_hash"] == checksum(payload["output"])
    assert payload["capture_manifest"]["checksum"] == payload["output_hash"]
    assert declared_response_hash == response_hash(payload)
    assert declared_response_hash != checksum(payload)


def test_direct_contract_validation_enforces_intrinsic_hash_output_and_date_integrity() -> None:
    baseline = json.loads(FIXTURE.read_bytes())
    assert CachedGraphResponse.model_validate(baseline).response_hash == baseline["response_hash"]

    invalid_payloads: list[dict[str, object]] = []
    for field in ("response_hash", "output_hash"):
        changed = deepcopy(baseline)
        changed[field] = f"sha256:{'0' * 64}"
        invalid_payloads.append(changed)

    changed = deepcopy(baseline)
    changed["trade_date"] = "2024-06-29"
    hash_payload = {key: value for key, value in changed.items() if key != "response_hash"}
    changed["response_hash"] = response_hash(hash_payload)
    invalid_payloads.append(changed)

    changed = deepcopy(baseline)
    changed["output"]["orders"] = []
    changed["output_hash"] = checksum(changed["output"])
    changed["capture_manifest"]["checksum"] = changed["output_hash"]
    hash_payload = {key: value for key, value in changed.items() if key != "response_hash"}
    changed["response_hash"] = response_hash(hash_payload)
    invalid_payloads.append(changed)

    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            CachedGraphResponse.model_validate(payload)


def test_direct_contract_rejects_source_manifest_subclass_without_serializer_access() -> None:
    record = parse_cached_graph_response(FIXTURE.read_bytes().removesuffix(b"\n"))
    calls: list[str] = []

    class HostileManifest(SourceManifest):
        def model_dump(self, *args: object, **kwargs: object) -> object:
            calls.append("model_dump")
            raise AssertionError("subclass serializer accessed")

    hostile = HostileManifest.model_construct(**record.capture_manifest.model_dump(mode="python"))
    payload = record.model_dump(mode="python")
    payload["capture_manifest"] = hostile
    with pytest.raises(ValidationError):
        CachedGraphResponse.model_validate(payload)
    assert calls == []


class HookProbe:
    def __init__(self, effects: list[str], label: str) -> None:
        object.__setattr__(self, "effects", effects)
        object.__setattr__(self, "label", label)

    def _effect(self, operation: str) -> None:
        object.__getattribute__(self, "effects").append(
            f"{object.__getattribute__(self, 'label')}.{operation}"
        )

    def __eq__(self, other: object) -> bool:
        self._effect("eq")
        return False

    def __lt__(self, other: object) -> bool:
        self._effect("lt")
        return False

    def __le__(self, other: object) -> bool:
        self._effect("le")
        return False

    def __gt__(self, other: object) -> bool:
        self._effect("gt")
        return False

    def __ge__(self, other: object) -> bool:
        self._effect("ge")
        return False

    def __str__(self) -> str:
        self._effect("str")
        return "hook-probe"

    def __iter__(self) -> Iterator[object]:
        self._effect("iter")
        return iter(())


def constructed_manifest_with(field: str, value: object) -> SourceManifest:
    manifest = make_capture_manifest(make_output())
    fields = manifest.model_dump(mode="python")
    fields[field] = value
    return SourceManifest.model_construct(**fields)


@pytest.mark.parametrize(
    "field",
    ["checksum", "fetched_at", "event_time", "published_at", "available_at", "ingested_at"],
)
@pytest.mark.parametrize("surface", ["builder", "public-model"])
def test_hostile_constructed_manifest_fields_are_rejected_without_hooks(
    field: str, surface: str
) -> None:
    effects: list[str] = []
    hostile = constructed_manifest_with(field, HookProbe(effects, field))
    if surface == "builder":
        with pytest.raises(CachedGraphResponseCorruptionError):
            build_cached_graph_response(**make_response_kwargs(capture_manifest=hostile))
    else:
        payload = parse_cached_graph_response(FIXTURE.read_bytes().removesuffix(b"\n")).model_dump(
            mode="python"
        )
        payload["capture_manifest"] = hostile
        with pytest.raises(ValidationError):
            CachedGraphResponse.model_validate(payload)
    assert effects == []


def test_manifest_subclass_is_rejected_before_any_attribute_or_serializer_hook() -> None:
    effects: list[str] = []
    manifest = make_capture_manifest(make_output())

    class HostileManifest(SourceManifest):
        def __getattribute__(self, name: str) -> object:
            if name not in {"__class__", "__dict__"}:
                effects.append(f"getattribute:{name}")
            return super().__getattribute__(name)

        def model_dump(self, *args: object, **kwargs: object) -> object:
            effects.append("model_dump")
            raise AssertionError("manifest serializer hook executed")

    hostile = HostileManifest.model_construct(**manifest.model_dump(mode="python"))
    effects.clear()
    with pytest.raises(CachedGraphResponseCorruptionError):
        build_cached_graph_response(**make_response_kwargs(capture_manifest=hostile))
    payload = parse_cached_graph_response(FIXTURE.read_bytes().removesuffix(b"\n")).model_dump(
        mode="python"
    )
    payload["capture_manifest"] = hostile
    with pytest.raises(ValidationError):
        CachedGraphResponse.model_validate(payload)
    assert effects == []


def test_manifest_primitive_subclasses_and_bool_revision_are_rejected_without_hooks() -> None:
    effects: list[str] = []

    class DateTimeSubclass(datetime):
        def __lt__(self, other: object) -> bool:
            effects.append("datetime.lt")
            return super().__lt__(other)  # type: ignore[arg-type]

    for field, value in (
        ("checksum", HookString(f"sha256:{'a' * 64}", effects)),
        ("available_at", DateTimeSubclass(2024, 6, 30, tzinfo=timezone.utc)),
        ("revision", True),
    ):
        hostile = constructed_manifest_with(field, value)
        effects.clear()
        with pytest.raises(CachedGraphResponseCorruptionError):
            build_cached_graph_response(**make_response_kwargs(capture_manifest=hostile))
        assert effects == []


@pytest.mark.parametrize("kind", ["dict-subclass", "custom-mapping"])
def test_manifest_mapping_subclasses_are_rejected_without_hooks(kind: str) -> None:
    effects: list[str] = []
    fields = make_capture_manifest(make_output()).model_dump(mode="python")
    hostile: object = (
        HookDict(fields, effects) if kind == "dict-subclass" else HookMapping(fields, effects)
    )
    with pytest.raises(CachedGraphResponseCorruptionError):
        build_cached_graph_response(
            **make_response_kwargs(capture_manifest=hostile)  # type: ignore[arg-type]
        )
    assert effects == []


class HookDict(dict[object, object]):
    def __init__(self, value: Mapping[object, object], effects: list[str]) -> None:
        dict.__init__(self, value)
        self.effects = effects

    def __iter__(self) -> Iterator[object]:
        self.effects.append("dict.iter")
        return dict.__iter__(self)

    def __getitem__(self, key: object) -> object:
        self.effects.append("dict.getitem")
        return dict.__getitem__(self, key)

    def items(self):
        self.effects.append("dict.items")
        return dict.items(self)

    def keys(self):
        self.effects.append("dict.keys")
        return dict.keys(self)


class HookMapping(Mapping[object, object]):
    def __init__(self, value: dict[object, object], effects: list[str]) -> None:
        self._value = value
        self.effects = effects

    def __iter__(self) -> Iterator[object]:
        self.effects.append("mapping.iter")
        return iter(self._value)

    def __len__(self) -> int:
        self.effects.append("mapping.len")
        return len(self._value)

    def __getitem__(self, key: object) -> object:
        self.effects.append("mapping.getitem")
        return self._value[key]


class HookList(list[object]):
    def __init__(self, value: list[object], effects: list[str]) -> None:
        list.__init__(self, value)
        self.effects = effects

    def __iter__(self) -> Iterator[object]:
        self.effects.append("list.iter")
        return list.__iter__(self)

    def __getitem__(self, key: object) -> object:
        self.effects.append("list.getitem")
        return list.__getitem__(self, key)  # type: ignore[index]


class HookString(str):
    def __new__(cls, value: str, effects: list[str]):
        instance = str.__new__(cls, value)
        instance.effects = effects
        return instance

    def __str__(self) -> str:
        self.effects.append("string.str")
        return str.__str__(self)

    def encode(self, *args: object, **kwargs: object) -> bytes:
        self.effects.append("string.encode")
        return str.encode(self, *args, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["dict-subclass", "custom-mapping"])
def test_public_model_rejects_nonexact_outer_mapping_without_hooks(kind: str) -> None:
    effects: list[str] = []
    payload = parse_cached_graph_response(FIXTURE.read_bytes().removesuffix(b"\n")).model_dump(
        mode="python"
    )
    hostile: object = (
        HookDict(payload, effects) if kind == "dict-subclass" else HookMapping(payload, effects)
    )
    with pytest.raises(ValidationError):
        CachedGraphResponse.model_validate(hostile)
    assert effects == []


@pytest.mark.parametrize("kind", ["dict-subclass", "custom-mapping"])
@pytest.mark.parametrize("surface", ["builder", "public-model"])
def test_nonexact_output_mapping_is_rejected_without_hooks(kind: str, surface: str) -> None:
    effects: list[str] = []
    output = make_output()
    hostile: object = (
        HookDict(output, effects) if kind == "dict-subclass" else HookMapping(output, effects)
    )
    if surface == "builder":
        kwargs = make_response_kwargs(
            output=hostile,  # type: ignore[arg-type]
            capture_manifest=make_capture_manifest(output),
        )
        effects.clear()
        with pytest.raises(CachedGraphResponseCorruptionError):
            build_cached_graph_response(**kwargs)
    else:
        payload = parse_cached_graph_response(FIXTURE.read_bytes().removesuffix(b"\n")).model_dump(
            mode="python"
        )
        payload["output"] = hostile
        with pytest.raises(ValidationError):
            CachedGraphResponse.model_validate(payload)
    assert effects == []


@pytest.mark.parametrize("kind", ["mapping", "list", "string"])
@pytest.mark.parametrize("surface", ["builder", "public-model"])
def test_nested_output_subclasses_are_rejected_without_hooks(kind: str, surface: str) -> None:
    effects: list[str] = []
    output = make_output()
    if kind == "mapping":
        value: object = HookMapping({"citation": "e1"}, effects)
    elif kind == "list":
        value = HookList(["e1"], effects)
    else:
        value = HookString("e1", effects)
    output["messages"].append(
        {"role": "assistant", "content": "Research", "response_metadata": {"hostile": value}}
    )
    if surface == "builder":
        with pytest.raises(CachedGraphResponseCorruptionError):
            build_cached_graph_response(
                **make_response_kwargs(
                    output=output,
                    capture_manifest=make_capture_manifest(make_output()),
                )
            )
    else:
        payload = parse_cached_graph_response(FIXTURE.read_bytes().removesuffix(b"\n")).model_dump(
            mode="python"
        )
        payload["output"] = output
        with pytest.raises(ValidationError):
            CachedGraphResponse.model_validate(payload)
    assert effects == []


def test_nonexact_outer_string_key_is_rejected_without_hooks() -> None:
    effects: list[str] = []
    payload = parse_cached_graph_response(FIXTURE.read_bytes().removesuffix(b"\n")).model_dump(
        mode="python"
    )
    output = payload.pop("output")
    payload[HookString("output", effects)] = output
    effects.clear()
    with pytest.raises(ValidationError):
        CachedGraphResponse.model_validate(payload)
    assert effects == []


def test_valid_exact_manifest_and_manifest_dict_preserve_fixture_bytes() -> None:
    output = make_output()
    manifest = make_capture_manifest(output)
    assert build_cached_graph_response(
        **make_response_kwargs(capture_manifest=manifest)
    ) == FIXTURE.read_bytes().removesuffix(b"\n")
    assert build_cached_graph_response(
        **make_response_kwargs(capture_manifest=manifest.model_dump(mode="python"))
    ) == FIXTURE.read_bytes().removesuffix(b"\n")


class ObservedTzInfo(tzinfo):
    def __init__(self, effects: list[str]) -> None:
        self.effects = effects

    def utcoffset(self, value: datetime | None) -> timedelta:
        self.effects.append("tzinfo.utcoffset")
        return timedelta(0)

    def dst(self, value: datetime | None) -> timedelta:
        self.effects.append("tzinfo.dst")
        return timedelta(0)

    def tzname(self, value: datetime | None) -> str:
        self.effects.append("tzinfo.tzname")
        return "observed"

    def fromutc(self, value: datetime) -> datetime:
        self.effects.append("tzinfo.fromutc")
        return value


class DateTimeSubclass(datetime):
    pass


@pytest.mark.parametrize(
    "invalid_cutoff",
    [
        datetime(2024, 6, 30, 23, 59, 59),
        datetime(2024, 6, 30, 18, 59, 59, tzinfo=timezone(timedelta(hours=-5))),
        DateTimeSubclass(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc),
    ],
    ids=["naive", "non-utc", "datetime-subclass"],
)
def test_builder_rejects_noncanonical_python_cutoff_datetimes(
    invalid_cutoff: datetime,
) -> None:
    with pytest.raises(CachedGraphResponseCorruptionError):
        build_cached_graph_response(**make_response_kwargs(knowledge_cutoff=invalid_cutoff))


def test_builder_rejects_custom_tzinfo_cutoff_without_observation() -> None:
    effects: list[str] = []
    cutoff = datetime(2024, 6, 30, 23, 59, 59, tzinfo=ObservedTzInfo(effects))
    effects.clear()
    with pytest.raises(CachedGraphResponseCorruptionError):
        build_cached_graph_response(**make_response_kwargs(knowledge_cutoff=cutoff))
    assert effects == []


def test_builder_accepts_exact_utc_datetime_and_offset_string_cutoff() -> None:
    expected = FIXTURE.read_bytes().removesuffix(b"\n")
    assert (
        build_cached_graph_response(
            **make_response_kwargs(
                knowledge_cutoff=datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
            )
        )
        == expected
    )
    assert (
        build_cached_graph_response(
            **make_response_kwargs(knowledge_cutoff="2024-06-30T18:59:59-05:00")
        )
        == expected
    )


@pytest.mark.parametrize(
    "field", ["fetched_at", "event_time", "published_at", "available_at", "ingested_at"]
)
@pytest.mark.parametrize("representation", ["manifest", "dict"])
def test_manifest_custom_tzinfo_is_rejected_without_observation(
    field: str, representation: str
) -> None:
    effects: list[str] = []
    fields = make_capture_manifest(make_output()).model_dump(mode="python")
    fields[field] = datetime(2024, 6, 30, 23, 59, 59, tzinfo=ObservedTzInfo(effects))
    manifest: object = (
        SourceManifest.model_construct(**fields) if representation == "manifest" else fields
    )
    effects.clear()
    with pytest.raises(CachedGraphResponseCorruptionError):
        build_cached_graph_response(
            **make_response_kwargs(capture_manifest=manifest)  # type: ignore[arg-type]
        )
    assert effects == []


def test_manifest_offset_strings_normalize_to_exact_utc_fixture() -> None:
    fields = make_capture_manifest(make_output()).model_dump(mode="json")
    for field in ("fetched_at", "event_time", "published_at", "available_at", "ingested_at"):
        fields[field] = "2024-06-30T18:59:59-05:00"
    assert build_cached_graph_response(
        **make_response_kwargs(capture_manifest=fields)
    ) == FIXTURE.read_bytes().removesuffix(b"\n")


@pytest.mark.parametrize("surface", ["class", "type-adapter"])
@pytest.mark.parametrize("subclass", [False, True], ids=["exact-model", "model-subclass"])
def test_constructed_response_instances_revalidate_before_nested_access(
    surface: str, subclass: bool
) -> None:
    effects: list[str] = []
    record = parse_cached_graph_response(FIXTURE.read_bytes().removesuffix(b"\n"))
    manifest_fields = record.capture_manifest.model_dump(mode="python")
    manifest_fields["checksum"] = HookProbe(effects, "constructed-checksum")
    payload = record.model_dump(mode="python")
    payload["capture_manifest"] = SourceManifest.model_construct(**manifest_fields)

    model_type = CachedGraphResponse
    if subclass:

        class ResponseSubclass(CachedGraphResponse):
            pass

        model_type = ResponseSubclass
    constructed = model_type.model_construct(**payload)
    effects.clear()
    with pytest.raises(ValidationError):
        if surface == "class":
            CachedGraphResponse.model_validate(constructed)
        else:
            TypeAdapter(CachedGraphResponse).validate_python(constructed)
    assert effects == []


def cutoff_payload(*, policy: str, future_availability: bool) -> dict[str, object]:
    payload = json.loads(FIXTURE.read_bytes())
    payload["replay_policy"] = policy
    manifest = payload["capture_manifest"]
    manifest["published_at"] = None
    if future_availability:
        manifest["available_at"] = "2024-07-01T00:00:00Z"
        manifest["fetched_at"] = "2024-07-01T00:00:00Z"
    else:
        manifest["available_at"] = "2024-06-30T23:59:58Z"
        manifest["fetched_at"] = "2024-06-30T23:59:59Z"
    manifest["ingested_at"] = "2024-07-01T00:00:00Z"
    return rehash_record_payload(payload)


def test_public_contract_rejects_rehashed_future_availability_and_late_archive() -> None:
    for payload in (
        cutoff_payload(policy="availability", future_availability=True),
        cutoff_payload(policy="archive_realistic", future_availability=False),
    ):
        with pytest.raises(ValidationError):
            CachedGraphResponse.model_validate(payload)


def test_public_contract_allows_availability_policy_late_ingestion() -> None:
    payload = cutoff_payload(policy="availability", future_availability=False)
    record = CachedGraphResponse.model_validate(payload)
    assert record.capture_manifest.ingested_at > record.knowledge_cutoff


def test_parser_preserves_typed_unavailable_for_rehashed_cutoff_ineligible_records() -> None:
    for payload in (
        cutoff_payload(policy="availability", future_availability=True),
        cutoff_payload(policy="archive_realistic", future_availability=False),
    ):
        with pytest.raises(CachedGraphResponseUnavailableError):
            parse_cached_graph_response(canonical(payload))


def test_tuple_input_becomes_array_without_hooks() -> None:
    output = make_output()
    output["messages"] = (("human", "NEW"), ("assistant", "Fixture research response."))
    record = parse_cached_graph_response(
        build_cached_graph_response(
            **make_response_kwargs(output=output, capture_manifest=make_capture_manifest(output))
        )
    )
    assert record.output["messages"] == [
        ["human", "NEW"],
        ["assistant", "Fixture research response."],
    ]


def test_builder_rejects_malformed_or_authority_output_before_sealing() -> None:
    for output in (
        {**make_output(), "orders": []},
        {**make_output(), "market_report": 7},
    ):
        with pytest.raises(HistoricalRuntimeOutputError):
            build_cached_graph_response(
                **make_response_kwargs(
                    output=output, capture_manifest=make_capture_manifest(output)
                )
            )


def deeply_encoded_output(depth: int = 1_500) -> dict[str, object]:
    output = make_output()
    arguments = '{"n":' * (depth - 1) + "0" + "}" * (depth - 1)
    output["messages"].append(
        {
            "role": "assistant",
            "content": "Research",
            "additional_kwargs": {"function_call": {"name": "research", "arguments": arguments}},
        }
    )
    return output


def test_builder_maps_deep_encoded_arguments_to_typed_output_error() -> None:
    output = deeply_encoded_output()
    with pytest.raises(HistoricalRuntimeOutputError):
        build_cached_graph_response(
            **make_response_kwargs(output=output, capture_manifest=make_capture_manifest(output))
        )


def test_parser_maps_rehashed_deep_encoded_arguments_to_corruption() -> None:
    payload = json.loads(FIXTURE.read_bytes())
    payload["output"] = deeply_encoded_output()
    with pytest.raises(CachedGraphResponseCorruptionError):
        parse_cached_graph_response(canonical(rehash_record_payload(payload)))


def test_builder_rejects_schema_string_subclass() -> None:
    class StringSubclass(str):
        pass

    with pytest.raises(CachedGraphResponseCorruptionError):
        build_cached_graph_response(**make_response_kwargs(schema_version=StringSubclass("v1")))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(schema_version="v2"),
        lambda p: p.update(output_hash=f"sha256:{'0' * 64}"),
        lambda p: p.update(response_hash=f"sha256:{'0' * 64}"),
        lambda p: p["capture_manifest"].update(checksum=f"sha256:{'0' * 64}"),
        lambda p: p["output"].update(market_report="tampered"),
    ],
)
def test_parser_rejects_schema_hash_and_payload_tampering(mutation) -> None:
    payload = json.loads(FIXTURE.read_bytes())
    mutation(payload)
    with pytest.raises(CachedGraphResponseCorruptionError):
        parse_cached_graph_response(canonical(payload))


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        b'{"schema_version":"v1","schema_version":"v1"}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e400}',
        b"{}\n",
        b'{ "x":1}',
        b'{"x": 1}',
        b'{"b":1,"a":2}',
    ],
)
def test_parser_rejects_bad_utf8_duplicates_nonfinite_overflow_and_noncanonical_raw(
    raw: bytes,
) -> None:
    with pytest.raises(CachedGraphResponseCorruptionError):
        parse_cached_graph_response(raw)


def test_parser_and_repository_require_exact_bytes_and_selection_types() -> None:
    class BytesSubclass(bytes):
        pass

    raw = FIXTURE.read_bytes().removesuffix(b"\n")
    repository = CachedGraphResponseRepository()
    with pytest.raises(CachedGraphResponseCorruptionError):
        parse_cached_graph_response(BytesSubclass(raw))
    with pytest.raises(CachedGraphResponseCorruptionError):
        repository.seal(BytesSubclass(raw))
    record = repository.seal(raw)

    class SelectionSubclass(CachedGraphSelection):
        def model_dump(self, *args: object, **kwargs: object) -> object:
            raise AssertionError((args, kwargs))

    hostile = SelectionSubclass.model_construct(
        **make_selection(expected_response_hash=record.response_hash).model_dump(mode="python")
    )
    with pytest.raises(CachedGraphResponseMismatchError):
        repository.get_bound(hostile, **bound_kwargs(record))


def test_repository_seal_is_idempotent_and_returns_defensive_reparses() -> None:
    raw = FIXTURE.read_bytes().removesuffix(b"\n")
    repository = CachedGraphResponseRepository()
    first = repository.seal(raw)
    first.output["market_report"] = "caller mutation"
    second = repository.seal(raw)
    assert second.output["market_report"] == "Fixture market evidence summary."
    assert first is not second
    selection = make_selection(expected_response_hash=first.response_hash)
    assert repository.get_bound(selection, **bound_kwargs(first)) == second


def test_repository_rejects_same_id_with_different_bytes() -> None:
    repository = CachedGraphResponseRepository()
    repository.seal(FIXTURE.read_bytes().removesuffix(b"\n"))
    with pytest.raises(CachedGraphResponseConflictError):
        repository.seal(
            build_cached_graph_response(
                **make_response_kwargs(
                    output=make_output(rating="Sell"),
                    capture_manifest=make_capture_manifest(make_output(rating="Sell")),
                )
            )
        )


def test_repository_missing_and_tampered_storage_fail_typed() -> None:
    repository = CachedGraphResponseRepository()
    with pytest.raises(CachedGraphResponseUnavailableError):
        repository.get_bound(
            make_selection(),
            **bound_kwargs(parse_cached_graph_response(FIXTURE.read_bytes().removesuffix(b"\n"))),
        )
    record = repository.seal(FIXTURE.read_bytes().removesuffix(b"\n"))
    repository._records[record.response_id] = b"corrupt"  # deliberate storage-integrity probe
    with pytest.raises(CachedGraphResponseCorruptionError):
        repository.get_bound(
            make_selection(expected_response_hash=record.response_hash), **bound_kwargs(record)
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("bundle_id", "bundle-other"),
        ("bundle_hash", f"sha256:{'4' * 64}"),
        ("knowledge_cutoff", "2024-06-30T23:59:58Z"),
        ("calendar_id", "calendar-other"),
        ("replay_policy", BundleReplayPolicy.AVAILABILITY),
        ("variant_id", "variant-other"),
        ("trade_date", "2024-06-29"),
        ("ticker", "OLD"),
        ("instrument_id", "instrument-other"),
        ("asset_type", "crypto"),
        ("instrument_context", "different sealed context"),
    ],
)
def test_get_bound_denies_every_bundle_context_instrument_binding(
    field: str, replacement: object
) -> None:
    repository = CachedGraphResponseRepository()
    record = repository.seal(FIXTURE.read_bytes().removesuffix(b"\n"))
    with pytest.raises((CachedGraphResponseMismatchError, CachedGraphResponseUnavailableError)):
        repository.get_bound(
            make_selection(expected_response_hash=record.response_hash),
            **bound_kwargs(record, **{field: replacement}),
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("response_id", "response-other"),
        ("expected_response_hash", f"sha256:{'4' * 64}"),
        ("graph_artifact_id", "graph-other"),
        ("graph_artifact_hash", f"sha256:{'4' * 64}"),
        ("model_artifact_id", "model-other"),
        ("model_artifact_hash", f"sha256:{'4' * 64}"),
        ("runtime_manifest_id", "runtime-other"),
        ("runtime_manifest_hash", f"sha256:{'4' * 64}"),
    ],
)
def test_get_bound_denies_every_exact_selection_binding(field: str, replacement: str) -> None:
    repository = CachedGraphResponseRepository()
    record = repository.seal(FIXTURE.read_bytes().removesuffix(b"\n"))
    selection_updates = {"expected_response_hash": record.response_hash, field: replacement}
    selection = make_selection(**selection_updates)
    error = (
        CachedGraphResponseUnavailableError
        if field == "response_id"
        else CachedGraphResponseMismatchError
    )
    with pytest.raises(error):
        repository.get_bound(selection, **bound_kwargs(record))


@pytest.mark.parametrize(
    ("policy", "available_delta", "ingested_delta", "allowed"),
    [
        (BundleReplayPolicy.AVAILABILITY, -1, 1, True),
        (BundleReplayPolicy.AVAILABILITY, 0, 1, True),
        (BundleReplayPolicy.AVAILABILITY, 1, 1, False),
        (BundleReplayPolicy.ARCHIVE_REALISTIC, -1, -1, True),
        (BundleReplayPolicy.ARCHIVE_REALISTIC, 0, 0, True),
        (BundleReplayPolicy.ARCHIVE_REALISTIC, -1, 1, False),
    ],
)
def test_capture_cutoffs_follow_availability_and_archive_policy(
    policy, available_delta, ingested_delta, allowed
):
    bundle = build_fixture_bundle()
    output = make_output()
    cutoff = bundle.knowledge_cutoff
    fetched_delta = max(available_delta, min(0, ingested_delta))
    manifest = make_capture_manifest(
        output,
        published_at=None,
        available_at=cutoff + timedelta(seconds=available_delta),
        fetched_at=cutoff + timedelta(seconds=fetched_delta),
        ingested_at=cutoff + timedelta(seconds=ingested_delta),
    )
    kwargs = make_response_kwargs(
        bundle=bundle, output=output, replay_policy=policy, capture_manifest=manifest
    )
    if allowed:
        assert (
            parse_cached_graph_response(build_cached_graph_response(**kwargs)).replay_policy
            is policy
        )
    else:
        with pytest.raises(CachedGraphResponseUnavailableError):
            build_cached_graph_response(**kwargs)


@pytest.mark.parametrize("trade_date", ["2024-06-29", "2024-07-01"])
def test_response_intrinsic_trade_date_must_equal_utc_cutoff_date(trade_date: str) -> None:
    with pytest.raises(CachedGraphResponseMismatchError):
        build_cached_graph_response(**make_response_kwargs(trade_date=trade_date))


def nested(depth: int) -> dict[str, object]:
    value: object = "leaf"
    for index in range(depth):
        value = {f"n{index}": value}
    return {"role": "assistant", "content": "Research", "response_metadata": {"nested": value}}


def test_limits_reject_record_bytes_depth_nodes_and_string_size() -> None:
    output = make_output()
    for field in ("market_report", "fundamentals_report", "sentiment_report", "news_report"):
        output[field] = "x" * MAX_CACHED_RESPONSE_STRING_BYTES
    with pytest.raises(CachedGraphResponseCorruptionError, match="size"):
        build_cached_graph_response(
            **make_response_kwargs(output=output, capture_manifest=make_capture_manifest(output))
        )
    output = make_output()
    output["messages"].append(nested(MAX_CACHED_RESPONSE_DEPTH + 1))
    with pytest.raises(CachedGraphResponseCorruptionError, match="depth"):
        build_cached_graph_response(
            **make_response_kwargs(output=output, capture_manifest=make_capture_manifest(output))
        )
    output = make_output()
    output["messages"].extend("x" for _ in range(MAX_CACHED_RESPONSE_NODES))
    with pytest.raises(CachedGraphResponseCorruptionError, match="node"):
        build_cached_graph_response(
            **make_response_kwargs(output=output, capture_manifest=make_capture_manifest(output))
        )
    output = make_output()
    output["market_report"] = "é" * (MAX_CACHED_RESPONSE_STRING_BYTES // 2 + 1)
    with pytest.raises(CachedGraphResponseCorruptionError, match="string"):
        build_cached_graph_response(
            **make_response_kwargs(output=output, capture_manifest=make_capture_manifest(output))
        )
    with pytest.raises(CachedGraphResponseCorruptionError, match="size"):
        parse_cached_graph_response(b" " * (MAX_CACHED_RESPONSE_BYTES + 1))


@pytest.mark.parametrize(
    "placement",
    ["opaque", "callable", "dict-subclass", "list-subclass", "string-subclass", "non-string-key"],
)
def test_builder_rejects_opaque_custom_callback_and_non_string_key_without_hooks(
    placement: str,
) -> None:
    calls: list[str] = []

    class Opaque:
        def __str__(self):
            calls.append("str")
            raise AssertionError("hook")

        def __iter__(self):
            calls.append("iter")
            raise AssertionError("hook")

    class DictSubclass(dict):
        pass

    class ListSubclass(list):
        pass

    class StringSubclass(str):
        pass

    output = make_output()
    if placement == "opaque":
        output["messages"].append(Opaque())
    elif placement == "callable":
        output["messages"].append(lambda: None)
    elif placement == "dict-subclass":
        output["messages"].append(DictSubclass(role="assistant", content="x"))
    elif placement == "list-subclass":
        output["messages"] = ListSubclass(output["messages"])
    elif placement == "string-subclass":
        output["market_report"] = StringSubclass("x")
    else:
        output["messages"].append({1: "not-a-string-key"})
    with pytest.raises(CachedGraphResponseCorruptionError):
        build_cached_graph_response(
            **make_response_kwargs(
                output=output, capture_manifest=make_capture_manifest(make_output())
            )
        )
    assert calls == []


def test_builder_rejects_cycles_without_copy_or_serialization_hooks() -> None:
    output = make_output()
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    output["messages"].append(cyclic)
    with pytest.raises(CachedGraphResponseCorruptionError):
        build_cached_graph_response(
            **make_response_kwargs(
                output=output, capture_manifest=make_capture_manifest(make_output())
            )
        )


def test_builder_and_parser_reject_lone_surrogates_as_typed_corruption() -> None:
    output = make_output()
    output["market_report"] = "\ud800"
    with pytest.raises(CachedGraphResponseCorruptionError, match="UTF-8"):
        build_cached_graph_response(
            **make_response_kwargs(
                output=output, capture_manifest=make_capture_manifest(make_output())
            )
        )

    raw = (
        FIXTURE.read_bytes()
        .removesuffix(b"\n")
        .replace(b"Fixture market evidence summary.", b"\\ud800")
    )
    with pytest.raises(CachedGraphResponseCorruptionError, match="UTF-8"):
        parse_cached_graph_response(raw)

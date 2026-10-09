"""BT-01 RED contracts for witnessed session binding and deterministic events.

The BT API is imported only from test bodies so this module collects on the
dependency-valid base and reports an explicit missing-contract RED.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import socket
import subprocess
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, time as wall_time, timedelta, timezone, tzinfo
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mytradingalpha.contracts.research import (
    EvidenceReference,
    ResearchNote,
    ResearchProvenance,
    derive_research_note_id,
)
from mytradingalpha.contracts.schemas import Mode, NetworkPolicy, RunContext
from mytradingalpha.contracts.signals import LLMOverlay, QuantSignal
from mytradingalpha.data.bars import DailyBar
from mytradingalpha.data.bundle import (
    BundleReplayPolicy,
    EvidenceBundle,
    build_evidence_bundle,
)
from mytradingalpha.data.calendar import TradingCalendar
from mytradingalpha.data.events import EventKind, NewsEvent, ReplayPolicy
from mytradingalpha.data.provenance import SourceManifest
from mytradingalpha.data.universe import Instrument, SymbolAlias, UniverseMembership
from mytradingalpha.quant.envelope import combine_quant_overlay
from mytradingalpha.quant.variants import VariantRegistry
from tests.productionization.quant import test_signal as quant_fixtures
from tests.productionization.research import test_overlay as research_fixtures

BINDING_HASH_DOMAIN = b"mytradingalpha:bt01:binding:v1\0"
EVENT_HASH_DOMAIN = b"mytradingalpha:bt01:event:v1\0"
MAX_SOURCE_TEXT_BYTES = 65_536
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_RUN_SOURCE_BYTES = 16 * 1024 * 1024
MAX_SEQUENCE = (1 << 63) - 1
EXPECTED_SOURCE_FINGERPRINT = (
    "sha256:919a029cd3cc041ad34fbc8a8d9f25f6248237c722afd978048843f625470859"
)
EXPECTED_DECISION_EVENT_ID = (
    "bt01-event:67c6b0309da989a4f756ea580d76958a30db5c21c54afff3e2e0f6c666ac60d2"
)
EXPECTED_OPPORTUNITY_EVENT_ID = (
    "bt01-event:3d2e9d949f5c478c9f93ac12115ce8738a87b739a405787feb215ed10d2c5b40"
)
DECISION_TIME = "2024-07-02T20:00:00Z"
PRE_CLOSE_CUTOFF = "2024-07-01T20:04:00Z"


def _bt_api() -> SimpleNamespace:
    """Load the BT-01 surface at execution time, preserving an auditable RED."""

    try:
        clock = importlib.import_module("mytradingalpha.backtest.clock")
        events = importlib.import_module("mytradingalpha.backtest.events")
        runner = importlib.import_module("mytradingalpha.backtest.runner")
        return SimpleNamespace(
            BacktestInputError=clock.BacktestInputError,
            SessionBinding=clock.SessionBinding,
            SessionClock=clock.SessionClock,
            BacktestEvent=events.BacktestEvent,
            DecisionEvent=events.DecisionEvent,
            OpportunityEvent=events.OpportunityEvent,
            BacktestRunner=runner.BacktestRunner,
            clock_module=clock,
            events_module=events,
            runner_module=runner,
        )
    except ModuleNotFoundError as exc:
        if not (exc.name or "").startswith("mytradingalpha.backtest"):
            raise
        pytest.fail(f"BT-01 RED: clock, events, and runner API is missing ({exc.name})")
    except AttributeError as exc:
        pytest.fail(f"BT-01 RED: clock, events, and runner API is incomplete ({exc})")


def _expect_bt_error(
    api: SimpleNamespace,
    reason_code: str,
    action: Callable[[], object],
) -> None:
    with pytest.raises(api.BacktestInputError) as captured:
        action()
    actual = getattr(captured.value.reason_code, "value", captured.value.reason_code)
    assert actual == reason_code
    assert len(str(captured.value)) <= 256


def _context(
    bundle: EvidenceBundle,
    *,
    run_id: str,
    variant_id: str,
    decision_time: str,
    earliest_execution_time: str,
    base_currency: str = "USD",
    calendar_id: str | None = None,
) -> RunContext:
    return RunContext(
        schema_version="v1",
        run_id=run_id,
        mode=Mode.HISTORICAL,
        variant_id=variant_id,
        decision_time=decision_time,
        knowledge_cutoff=bundle.knowledge_cutoff,
        earliest_execution_time=earliest_execution_time,
        bundle_id=bundle.bundle_id,
        bundle_hash=bundle.bundle_hash,
        calendar_id=calendar_id or bundle.calendar.calendar_id,
        base_currency=base_currency,
        network_policy=NetworkPolicy(),
    )


def _quant_only_inputs(
    *,
    bundle: EvidenceBundle | None = None,
    decision_time: str = DECISION_TIME,
    cutoff: str = PRE_CLOSE_CUTOFF,
    earliest_execution_time: str = "2024-07-03T13:30:00Z",
    run_id: str = "run-bt01-preclose",
    variant_id: str = "variant-bt01-quant-only",
    base_currency: str = "USD",
    calendar_id: str | None = None,
    legacy_calendar: bool = False,
) -> tuple[RunContext, EvidenceBundle, Any]:
    selected_bundle = bundle or quant_fixtures._bundle(
        cutoff=cutoff,
        legacy_calendar=legacy_calendar,
    )
    quant = quant_fixtures._score(
        quant_fixtures._api(), bundle=selected_bundle, run_id=run_id
    )
    context = _context(
        selected_bundle,
        run_id=run_id,
        variant_id=variant_id,
        decision_time=decision_time,
        earliest_execution_time=earliest_execution_time,
        base_currency=base_currency,
        calendar_id=calendar_id,
    )
    registry = VariantRegistry().register(context.variant_id, kind="quant_only")
    envelope = combine_quant_overlay(quant, context=context, registry=registry)
    return context, selected_bundle, envelope


def _research_inputs(
    *,
    note_transform: Callable[[ResearchNote], ResearchNote] | None = None,
    decision_time: str = "2024-07-03T17:00:00Z",
    earliest_execution_time: str = "2024-07-05T13:30:00Z",
    variant_id: str | None = None,
    run_id: str | None = None,
) -> tuple[RunContext, EvidenceBundle, Any]:
    bundle, source_note, quant = research_fixtures.bound_inputs.__wrapped__()
    note = source_note if note_transform is None else note_transform(source_note)
    selected_run_id = run_id or note.run_id
    selected_variant_id = variant_id or note.variant_id
    context = _context(
        bundle,
        run_id=selected_run_id,
        variant_id=selected_variant_id,
        decision_time=decision_time,
        earliest_execution_time=earliest_execution_time,
    )
    registry = VariantRegistry().register(context.variant_id, kind="quant_llm")
    overlay = LLMOverlay.model_validate(research_fixtures._candidate(note, quant))
    envelope = combine_quant_overlay(
        quant,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )
    return context, bundle, envelope


def _archive_realistic_note_variant(
    note: ResearchNote,
    *,
    replay_policy: str | None = None,
    thesis: str | None = None,
    risks: tuple[str, ...] | None = None,
    capture_manifest: dict[str, object] | None = None,
    citations: list[dict[str, object]] | None = None,
) -> ResearchNote:
    payload = note.model_dump(mode="python")
    payload["note_id"] = "note-pending"
    if replay_policy is not None:
        payload["replay_policy"] = replay_policy
    if thesis is not None:
        payload["thesis"] = thesis
    if risks is not None:
        payload["risks"] = risks
    if capture_manifest is not None:
        payload["capture_manifest"] = capture_manifest
    if citations is not None:
        payload["citations"] = citations
    provisional = ResearchNote.model_validate(payload)
    payload["note_id"] = derive_research_note_id(provisional)
    return ResearchNote.model_validate(payload)


def _updated_note_source(
    note: ResearchNote,
    *,
    late_capture: bool = False,
    late_citation_index: int | None = None,
) -> ResearchNote:
    cutoff = note.knowledge_cutoff
    payload = note.model_dump(mode="python")
    payload["replay_policy"] = "availability"
    if late_capture:
        capture = dict(payload["capture_manifest"])
        capture["fetched_at"] = cutoff + timedelta(minutes=1)
        capture["ingested_at"] = cutoff + timedelta(minutes=2)
        payload["capture_manifest"] = capture
    if late_citation_index is not None:
        citations = list(payload["citations"])
        citation = dict(citations[late_citation_index])
        provenance = dict(citation["provenance"])
        provenance["fetched_at"] = cutoff + timedelta(minutes=1)
        provenance["ingested_at"] = cutoff + timedelta(minutes=2)
        citation["provenance"] = provenance
        citations[late_citation_index] = citation
        payload["citations"] = citations
    payload["note_id"] = "note-pending"
    provisional = ResearchNote.model_validate(payload)
    payload["note_id"] = derive_research_note_id(provisional)
    return ResearchNote.model_validate(payload)


def _rebuild_bundle(
    bundle: EvidenceBundle,
    *,
    bundle_id: str | None = None,
    instruments: tuple[Instrument, ...] | None = None,
    aliases: tuple[SymbolAlias, ...] | None = None,
    memberships: tuple[UniverseMembership, ...] | None = None,
) -> EvidenceBundle:
    return build_evidence_bundle(
        schema_version=bundle.schema_version,
        bundle_id=bundle_id or bundle.bundle_id,
        created_at=bundle.created_at,
        knowledge_cutoff=bundle.knowledge_cutoff,
        replay_policy=bundle.replay_policy,
        requirements=bundle.requirements,
        missing_optional=bundle.missing_optional,
        calendar=bundle.calendar,
        instrument_candidates=instruments or bundle.instruments,
        alias_candidates=aliases or bundle.aliases,
        membership_candidates=memberships or bundle.memberships,
        action_candidates=bundle.actions,
        bar_candidates=bundle.bars,
        filing_candidates=bundle.filings,
        event_candidates=bundle.events,
        social_post_candidates=bundle.social_posts,
        macro_observation_candidates=bundle.macro_observations,
    )


def _source_payload(context: RunContext, bundle: EvidenceBundle, envelope: Any) -> dict[str, object]:
    return {
        "context": context.model_dump(mode="json"),
        "bundle": bundle.model_dump(mode="json"),
        "envelope": envelope.model_dump(mode="json"),
    }


def _canonical_source_bytes(
    context: RunContext,
    bundle: EvidenceBundle,
    envelope: Any,
) -> bytes:
    return json.dumps(
        _source_payload(context, bundle, envelope),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")


def _source_fingerprint(
    context: RunContext,
    bundle: EvidenceBundle,
    envelope: Any,
) -> str:
    return "sha256:" + hashlib.sha256(
        BINDING_HASH_DOMAIN + _canonical_source_bytes(context, bundle, envelope)
    ).hexdigest()


def _rehashed_quant_signal(signal: QuantSignal, **updates: object) -> QuantSignal:
    payload = signal.model_dump(mode="json")
    payload.update(updates)
    payload.pop("signal_id")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")
    payload["signal_id"] = "quant-signal:" + hashlib.sha256(
        quant_fixtures.HASH_DOMAINS["quant_signal"].encode("utf-8") + encoded
    ).hexdigest()
    return QuantSignal.model_validate(payload)


def _utc_json(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decision_event_payload(
    context: RunContext,
    bundle: EvidenceBundle,
    envelope: Any,
    binding: Any,
) -> dict[str, object]:
    return {
        "schema_version": "v1",
        "stage": "decision",
        "run_id": context.run_id,
        "instrument_id": envelope.quant.instrument_id,
        "variant_id": context.variant_id,
        "calendar_id": bundle.calendar.calendar_id,
        "session_date": binding.session.session_date.isoformat(),
        "economic_time": _utc_json(context.decision_time),
        "observed_at": _utc_json(context.decision_time),
        "decision_time": _utc_json(context.decision_time),
        "knowledge_cutoff": _utc_json(context.knowledge_cutoff),
        "bundle_id": bundle.bundle_id,
        "bundle_hash": bundle.bundle_hash,
        "envelope_id": envelope.envelope_id,
        "source_fingerprint": _source_fingerprint(context, bundle, envelope),
        "shadow_only": True,
        "no_trade": envelope.no_trade,
    }


def _opportunity_event_payload(
    context: RunContext,
    bundle: EvidenceBundle,
    envelope: Any,
    binding: Any,
    decision_event_id: str,
) -> dict[str, object]:
    return {
        "schema_version": "v1",
        "stage": "opportunity",
        "run_id": context.run_id,
        "instrument_id": envelope.quant.instrument_id,
        "variant_id": context.variant_id,
        "calendar_id": bundle.calendar.calendar_id,
        "session_date": binding.next_session.session_date.isoformat(),
        "economic_time": _utc_json(binding.next_session.open_at),
        "observed_at": _utc_json(context.decision_time),
        "decision_time": _utc_json(context.decision_time),
        "knowledge_cutoff": _utc_json(context.knowledge_cutoff),
        "bundle_id": bundle.bundle_id,
        "bundle_hash": bundle.bundle_hash,
        "envelope_id": envelope.envelope_id,
        "source_fingerprint": _source_fingerprint(context, bundle, envelope),
        "shadow_only": True,
        "no_trade": envelope.no_trade,
        "outcome_start": _utc_json(binding.next_session.open_at),
        "outcome_end": _utc_json(binding.next_session.close_at),
        "earliest_execution_time": _utc_json(context.earliest_execution_time),
        "decision_event_id": decision_event_id,
    }


def _event_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")
    return "bt01-event:" + hashlib.sha256(EVENT_HASH_DOMAIN + encoded).hexdigest()


def _citation_manifest_hash(manifest: SourceManifest) -> str:
    canonical = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _bundle_for_timezone(
    *,
    timezone_name: str,
    calendar_id: str,
    cutoff: str,
    open_local: wall_time,
    close_local: wall_time,
) -> EvidenceBundle:
    source_calendar = quant_fixtures._calendar()
    calendar_payload = source_calendar.model_dump(mode="python")
    calendar_payload["calendar_id"] = calendar_id
    calendar_payload["timezone"] = timezone_name
    calendar_payload["replay_evidence"] = None
    local_zone = ZoneInfo(timezone_name)
    sessions: list[dict[str, object]] = []
    for source_session in source_calendar.schedule:
        session_date = source_session.session_date
        local_open = datetime.combine(session_date, open_local, tzinfo=local_zone)
        local_close = datetime.combine(session_date, close_local, tzinfo=local_zone)
        sessions.append(
            {
                **source_session.model_dump(mode="python"),
                "calendar_id": calendar_id,
                "open_at": local_open.astimezone(timezone.utc),
                "close_at": local_close.astimezone(timezone.utc),
            }
        )
    calendar_payload["schedule"] = tuple(sessions)
    calendar_payload["closures"] = tuple(
        {**closure.model_dump(mode="python"), "calendar_id": calendar_id}
        for closure in source_calendar.closures
    )
    calendar = TradingCalendar.model_validate(calendar_payload)

    bars: list[DailyBar] = []
    for source_bar in quant_fixtures._bars():
        close_at = calendar.session(source_bar.session_date).close_at
        manifest = SourceManifest.model_validate(
            {
                **source_bar.manifest.model_dump(mode="python"),
                "event_time": close_at,
                "available_at": close_at + timedelta(minutes=1),
                "fetched_at": close_at + timedelta(minutes=2),
                "ingested_at": close_at + timedelta(minutes=3),
            }
        )
        bars.append(
            DailyBar.model_validate(
                {
                    **source_bar.model_dump(mode="python"),
                    "calendar_id": calendar_id,
                    "manifest": manifest,
                }
            )
        )
    return quant_fixtures._bundle(
        calendar=calendar,
        bars=tuple(bars),
        cutoff=cutoff,
    )


def _bundle_with_large_event_bodies(body_lengths: tuple[int, ...]) -> EvidenceBundle:
    cutoff = "2024-07-02T20:04:00Z"
    original_bundle = quant_fixtures._bundle(cutoff=cutoff)
    events: list[NewsEvent] = []
    first_event_time = datetime(2024, 2, 1, tzinfo=timezone.utc)
    for index, body_length in enumerate(body_lengths):
        body = "x" * body_length
        event_time = first_event_time + timedelta(seconds=index)
        available_at = event_time + timedelta(seconds=2)
        manifest = SourceManifest(
            schema_version="v1",
            manifest_id=f"bt01-large-event-manifest-{index:03d}",
            source="bt01-large-event-fixture",
            source_locator=f"fixture://bt01/events/{index:03d}",
            fetched_at=event_time + timedelta(seconds=3),
            event_time=event_time,
            published_at=event_time + timedelta(seconds=1),
            available_at=available_at,
            ingested_at=event_time + timedelta(seconds=4),
            checksum="sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
            terms="synthetic BT-01 resource fixture",
            revision=0,
        )
        events.append(
            NewsEvent(
                schema_version="v1",
                event_id=f"bt01-large-event-{index:03d}",
                instrument_id="inst-survivor",
                kind=EventKind.NEWS,
                title="Synthetic large event",
                body=body,
                publisher="BT-01 fixture publisher",
                url=None,
                replay_policy=ReplayPolicy.ARCHIVED,
                manifest=manifest,
            )
        )
    return quant_fixtures._bundle(
        cutoff=cutoff,
        events=(*original_bundle.events, *events),
    )


def _bundle_with_numeric_source(
    *,
    price: Decimal,
    volume: int,
) -> EvidenceBundle:
    cutoff = PRE_CLOSE_CUTOFF
    bars = []
    for source_bar in quant_fixtures._bars():
        fields = source_bar.model_dump(mode="python")
        fields.update(open=price, high=price, low=price, close=price)
        if not bars:
            fields["volume"] = volume
        bars.append(DailyBar.model_validate(fields))
    return quant_fixtures._bundle(cutoff=cutoff, bars=tuple(bars))


def _mutated_numeric_inputs(
    *,
    field_name: str,
    value: Decimal | int,
) -> tuple[RunContext, EvidenceBundle, Any]:
    context, bundle, envelope = _quant_only_inputs()
    target_bar = bundle.bars[0]
    fields = (
        ("open", "high", "low", "close")
        if field_name == "price"
        else (field_name,)
    )
    for field in fields:
        object.__setattr__(target_bar, field, value)
    return context, bundle, envelope


def _large_event_research_inputs(
    bundle: EvidenceBundle,
    *,
    variant_id: str,
) -> tuple[RunContext, EvidenceBundle, Any]:
    run_id = "run-bt01-resource-boundary"
    # Reuse a signal scored from the unchanged PIT bundle because the added
    # synthetic news bodies are outside SIG-03's feature input. Rebinding its
    # exact wire references exercises BT's full-source byte bound; it is not
    # evidence of recomputation, model provenance, or market behavior.
    source_bundle = quant_fixtures._bundle(cutoff=bundle.knowledge_cutoff.isoformat())
    source_quant = quant_fixtures._score(
        quant_fixtures._api(), bundle=source_bundle, run_id=run_id
    )
    quant_payload = source_quant.model_dump(mode="json")
    quant_payload["bundle_id"] = bundle.bundle_id
    quant_payload["bundle_hash"] = bundle.bundle_hash
    quant_payload.pop("signal_id")
    encoded_quant = json.dumps(
        quant_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")
    quant_payload["signal_id"] = "quant-signal:" + hashlib.sha256(
        quant_fixtures.HASH_DOMAINS["quant_signal"].encode("utf-8") + encoded_quant
    ).hexdigest()
    quant = QuantSignal.model_validate(quant_payload)
    context = _context(
        bundle,
        run_id=quant.run_id,
        variant_id=variant_id,
        decision_time="2024-07-03T17:00:00Z",
        earliest_execution_time="2024-07-05T13:30:00Z",
    )
    event_records = tuple(
        event for event in bundle.events if event.event_id.startswith("bt01-large-event-")
    )
    midpoint = len(event_records) // 2
    claim_citations = {
        "thesis": tuple(
            EvidenceReference(
                schema_version="v1",
                bundle_id=bundle.bundle_id,
                domain="events",
                record_id=event.event_id,
            )
            for event in event_records[:midpoint]
        ),
        "risks": tuple(
            EvidenceReference(
                schema_version="v1",
                bundle_id=bundle.bundle_id,
                domain="events",
                record_id=event.event_id,
            )
            for event in event_records[midpoint:]
        ),
    }
    output = research_fixtures.make_output()
    instrument_context = (
        "Symbol: KEEP; instrument_id: inst-survivor; asset_class: equity; "
        "exchange: XNAS; currency: USD"
    )
    output.update(
        research_fixtures.create_historical_initial_state(
            company_name="KEEP",
            trade_date="2024-07-02",
            asset_type="stock",
            instrument_context=instrument_context,
        )
    )
    response = research_fixtures.parse_cached_graph_response(
        research_fixtures.build_cached_graph_response(
            **research_fixtures.make_response_kwargs(
                bundle=bundle,
                context=context,
                output=output,
                variant_id=variant_id,
                instrument_id="inst-survivor",
                ticker="KEEP",
                trade_date="2024-07-02",
                instrument_context=instrument_context,
            )
        )
    )
    note = research_fixtures.ResearchNoteBuilder(
        bundle=bundle,
        context=context,
        response=response,
    ).build(
        source_agent="sentiment_analyst",
        source_fields={"thesis": "market_report", "risks": "news_report"},
        claim_citations=claim_citations,
    )
    registry = VariantRegistry().register(variant_id, kind="quant_llm")
    overlay = LLMOverlay.model_validate(
        research_fixtures._candidate(note, quant)
    )
    envelope = combine_quant_overlay(
        quant,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )
    return context, bundle, envelope


def _mismatched_citation_note(note: ResearchNote) -> ResearchNote:
    payload = note.model_dump(mode="python")
    citations = list(payload["citations"])
    citation = dict(citations[0])
    provenance = dict(citation["provenance"])
    fabricated_manifest = {
        key: value for key, value in provenance.items() if key != "manifest_hash"
    }
    fabricated_manifest["revision"] += 1
    source_manifest = SourceManifest.model_validate(
        {
            **fabricated_manifest,
            "source_locator": "fixture://different-valid-source",
            "terms": "fixture terms",
        }
    )
    changed = source_manifest.model_dump(mode="json")
    changed["source_locator"] = "[REDACTED]"
    changed["terms"] = "[REDACTED]"
    changed["manifest_hash"] = _citation_manifest_hash(source_manifest)
    citation["provenance"] = ResearchProvenance.model_validate(changed)
    citations[0] = citation
    return _archive_realistic_note_variant(note, citations=citations)


def test_exact_witnessed_close_maps_to_calendar_next_early_close_without_backdating() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    assert bundle.replay_policy.value == "archive_realistic"
    assert context.decision_time.isoformat() == "2024-07-02T20:00:00+00:00"
    assert context.knowledge_cutoff.isoformat() == "2024-07-01T20:04:00+00:00"
    assert not any(
        item.session_date == date(2024, 7, 2) for item in bundle.bars
    )

    binding = api.SessionClock.bind(context, bundle, envelope)
    assert binding.session.session_date == date(2024, 7, 2)
    assert binding.session.close_at == context.decision_time
    assert binding.next_session.session_date == date(2024, 7, 3)
    assert binding.next_session.session_type.value == "early_close"

    events = api.BacktestRunner().run((binding,))
    assert tuple(event.stage for event in events) == ("decision", "opportunity")
    assert tuple(event.sequence for event in events) == (0, 1)
    assert events[0].economic_time == context.decision_time
    assert events[0].observed_at == context.decision_time
    assert events[1].economic_time == binding.next_session.open_at
    assert events[1].observed_at == context.decision_time
    assert events[1].outcome_start == binding.next_session.open_at
    assert events[1].outcome_end == binding.next_session.close_at
    assert events[1].outcome_end.isoformat() == "2024-07-03T17:00:00+00:00"
    assert events[1].earliest_execution_time == context.earliest_execution_time
    assert events[1].decision_event_id == events[0].event_id

    for event in events:
        payload = event.model_dump(mode="json")
        assert payload["source_fingerprint"] == _source_fingerprint(
            context, bundle, envelope
        )
        assert payload["shadow_only"] is True
        assert payload["no_trade"] is False
        assert not {"quantity", "intent_id", "fill_id", "order_id"} & set(payload)
        assert "effective_score" not in payload


@pytest.mark.parametrize(
    "decision_time",
    ("2024-07-02T19:59:59.999999Z", "2024-07-02T20:00:00.000001Z"),
)
def test_decision_must_match_witnessed_close_to_one_microsecond(
    decision_time: str,
) -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs(decision_time=decision_time)
    _expect_bt_error(
        api,
        "decision_not_close",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def test_cutoff_equality_is_accepted_without_the_unavailable_closing_bar() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs(
        decision_time=DECISION_TIME,
        cutoff=DECISION_TIME,
        earliest_execution_time="2024-07-03T13:30:00Z",
        run_id="run-bt01-cutoff-equality",
    )
    assert context.knowledge_cutoff == context.decision_time
    assert not any(item.session_date == date(2024, 7, 2) for item in bundle.bars)
    binding = api.SessionClock.bind(context, bundle, envelope)
    assert len(api.BacktestRunner().run((binding,))) == 2


def test_execution_before_next_verified_open_is_rejected() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs(
        earliest_execution_time="2024-07-02T20:00:00.000001Z",
        run_id="run-bt01-early-execution",
    )
    _expect_bt_error(
        api,
        "execution_too_early",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def test_later_than_next_close_is_retained_as_descriptive_lower_bound() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs(
        earliest_execution_time="2024-07-03T17:00:00.000001Z",
        run_id="run-bt01-late-lower-bound",
    )
    binding = api.SessionClock.bind(context, bundle, envelope)
    (decision, opportunity) = api.BacktestRunner().run((binding,))
    assert decision.stage == "decision"
    assert opportunity.stage == "opportunity"
    assert opportunity.earliest_execution_time > opportunity.outcome_end
    assert opportunity.outcome_start == binding.next_session.open_at
    assert opportunity.outcome_end == binding.next_session.close_at


def test_legacy_calendar_without_presealed_replay_witness_is_rejected() -> None:
    api = _bt_api()
    witnessed_context, _, witnessed_envelope = _quant_only_inputs(
        run_id="run-bt01-no-calendar-witness",
    )
    bundle = quant_fixtures._bundle(cutoff=PRE_CLOSE_CUTOFF, legacy_calendar=True)
    context = _context(
        bundle,
        run_id=witnessed_context.run_id,
        variant_id=witnessed_context.variant_id,
        decision_time=DECISION_TIME,
        earliest_execution_time=witnessed_context.earliest_execution_time.isoformat(),
    )
    quant = _rehashed_quant_signal(
        witnessed_envelope.quant, bundle_id=bundle.bundle_id, bundle_hash=bundle.bundle_hash
    )
    envelope = combine_quant_overlay(
        quant,
        context=context,
        registry=VariantRegistry().register(context.variant_id, kind="quant_only"),
    )
    assert bundle.calendar.replay_evidence is None
    _expect_bt_error(
        api,
        "witness_missing",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def test_coverage_end_fails_closed_without_calendar_gap_inference() -> None:
    api = _bt_api()
    calendar = quant_fixtures._gapped_quant_calendar()
    bundle = quant_fixtures._bundle(
        calendar=calendar,
        bars=quant_fixtures._gapped_bars(),
        cutoff="2024-07-02T19:59:00Z",
    )
    context, bundle, envelope = _quant_only_inputs(
        bundle=bundle,
        decision_time=DECISION_TIME,
        earliest_execution_time="2024-07-03T13:30:00Z",
        run_id="run-bt01-coverage-end",
    )
    _expect_bt_error(
        api,
        "session_unavailable",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def _custom_timezone_binding(
    api: SimpleNamespace,
    *,
    timezone_name: str,
    calendar_id: str,
    open_local: wall_time,
    close_local: wall_time,
    decision_time: str,
    session_date: str,
    run_id: str,
) -> tuple[Any, RunContext, EvidenceBundle, Any]:
    bundle = _bundle_for_timezone(
        timezone_name=timezone_name,
        calendar_id=calendar_id,
        cutoff="2024-07-02T19:59:00Z",
        open_local=open_local,
        close_local=close_local,
    )
    next_session = bundle.calendar.next_session(session_date)
    quant = quant_fixtures._score(
        quant_fixtures._api(), bundle=bundle, run_id=run_id
    )
    context = _context(
        bundle,
        run_id=run_id,
        variant_id="variant-bt01-zoned",
        decision_time=decision_time,
        earliest_execution_time=next_session.open_at.isoformat(),
    )
    envelope = combine_quant_overlay(
        quant,
        context=context,
        registry=VariantRegistry().register(context.variant_id, kind="quant_only"),
    )
    return api.SessionClock.bind(context, bundle, envelope), context, bundle, envelope


def test_presealed_non_utc_witness_uses_exchange_local_date_not_utc_date() -> None:
    api = _bt_api()
    binding, context, _, _ = _custom_timezone_binding(
        api,
        timezone_name="Pacific/Honolulu",
        calendar_id="calendar-bt01-hnl",
        open_local=wall_time(9, 30),
        close_local=wall_time(16, 0),
        decision_time="2024-07-03T02:00:00Z",
        session_date="2024-07-02",
        run_id="run-bt01-honolulu-local-date",
    )
    assert context.decision_time.date() == date(2024, 7, 3)
    assert binding.session.session_date == date(2024, 7, 2)
    assert binding.session.close_at == context.decision_time
    assert tuple(event.stage for event in api.BacktestRunner().run((binding,))) == (
        "decision",
        "opportunity",
    )


def test_cross_calendar_session_sort_cannot_regress_utc_economic_time() -> None:
    api = _bt_api()
    honolulu_binding, _, _, _ = _custom_timezone_binding(
        api,
        timezone_name="Pacific/Honolulu",
        calendar_id="calendar-bt01-hnl-reversal",
        open_local=wall_time(9, 30),
        close_local=wall_time(16, 0),
        decision_time="2024-07-03T02:00:00Z",
        session_date="2024-07-02",
        run_id="run-bt01-honolulu-reversal",
    )
    kiritimati_binding, _, _, _ = _custom_timezone_binding(
        api,
        timezone_name="Pacific/Kiritimati",
        calendar_id="calendar-bt01-kiritimati-reversal",
        open_local=wall_time(9, 0),
        close_local=wall_time(12, 0),
        decision_time="2024-07-02T22:00:00Z",
        session_date="2024-07-03",
        run_id="run-bt01-kiritimati-reversal",
    )
    assert honolulu_binding.session.session_date < kiritimati_binding.session.session_date
    assert honolulu_binding.session.close_at > kiritimati_binding.session.close_at
    _expect_bt_error(
        api,
        "event_invalid",
        lambda: api.BacktestRunner().run((honolulu_binding, kiritimati_binding)),
    )


def test_presealed_witness_avoids_timezone_recapture_and_host_timezone_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()

    def forbidden(*args: object, **kwargs: object) -> Any:
        del args, kwargs
        pytest.fail("BT-01 used an unsealed timezone or calendar-capture path")

    calendar_module = importlib.import_module("mytradingalpha.data.calendar")
    monkeypatch.setattr(calendar_module, "ZoneInfo", forbidden)
    monkeypatch.setattr(calendar_module, "capture_calendar_replay_evidence", forbidden)
    binding = api.SessionClock.bind(context, bundle, envelope)
    assert api.BacktestRunner().run((binding,))


def test_no_trade_envelope_still_emits_two_shadow_events_without_intent_authority() -> None:
    api = _bt_api()
    bundle, source_note, quant = research_fixtures.bound_inputs.__wrapped__()
    decision_context = _context(
        bundle,
        run_id=source_note.run_id,
        variant_id=source_note.variant_id,
        decision_time="2024-07-03T17:00:00Z",
        earliest_execution_time="2024-07-05T13:30:00Z",
    )
    registry = VariantRegistry().register(decision_context.variant_id, kind="quant_llm")
    no_overlay = combine_quant_overlay(
        quant,
        context=decision_context,
        registry=registry,
        note=source_note,
    )
    assert no_overlay.no_trade is True
    binding = api.SessionClock.bind(decision_context, bundle, no_overlay)
    events = api.BacktestRunner().run((binding,))
    assert len(events) == 2
    assert all(event.shadow_only is True and event.no_trade is True for event in events)
    assert tuple(event.stage for event in events) == ("decision", "opportunity")
    assert not any(
        {"quantity", "intent_id", "fill_id", "order_id", "target_weight"}
        & set(event.model_dump(mode="json"))
        for event in events
    )


def test_archive_realistic_research_capture_and_citations_are_pre_cutoff_inputs() -> None:
    api = _bt_api()
    context, bundle, envelope = _research_inputs()
    assert bundle.replay_policy.value == "archive_realistic"
    assert envelope.note is not None
    note = envelope.note
    assert note.capture_manifest.available_at <= context.knowledge_cutoff
    assert note.capture_manifest.ingested_at <= context.knowledge_cutoff
    assert all(
        citation.provenance.available_at <= context.knowledge_cutoff
        and citation.provenance.ingested_at <= context.knowledge_cutoff
        for citation in note.citations
    )
    binding = api.SessionClock.bind(context, bundle, envelope)
    events = api.BacktestRunner().run((binding,))
    assert tuple(event.stage for event in events) == ("decision", "opportunity")


@pytest.mark.parametrize(
    "transform",
    (
        lambda note: _updated_note_source(note, late_capture=True),
        lambda note: _updated_note_source(note, late_citation_index=0),
    ),
    ids=("late-capture", "late-cited-ingestion"),
)
def test_archive_realistic_rejects_valid_availability_note_with_late_ingestion(
    transform: Callable[[ResearchNote], ResearchNote],
) -> None:
    api = _bt_api()
    context, bundle, envelope = _research_inputs(note_transform=transform)
    assert envelope.note is not None
    assert envelope.note.replay_policy == "availability"
    assert envelope.note.note_hash
    assert envelope.envelope_id
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def test_archive_realistic_rejects_inconsistent_note_policy_even_when_timely() -> None:
    api = _bt_api()

    def availability_note(note: ResearchNote) -> ResearchNote:
        return _archive_realistic_note_variant(note, replay_policy="availability")

    context, bundle, envelope = _research_inputs(note_transform=availability_note)
    assert bundle.replay_policy.value == "archive_realistic"
    assert envelope.note is not None
    assert envelope.note.replay_policy == "availability"
    assert all(
        citation.provenance.ingested_at <= context.knowledge_cutoff
        for citation in envelope.note.citations
    )
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def test_research_citation_must_resolve_to_one_exact_typed_bundle_record() -> None:
    api = _bt_api()

    def absent_reference(note: ResearchNote) -> ResearchNote:
        payload = note.model_dump(mode="python")
        citations = list(payload["citations"])
        citation = dict(citations[0])
        reference = dict(citation["reference"])
        reference["record_id"] = "absent-citation-record"
        citation["reference"] = reference
        citations[0] = citation
        return _archive_realistic_note_variant(note, citations=citations)

    context, bundle, envelope = _research_inputs(note_transform=absent_reference)
    assert envelope.note is not None
    assert envelope.note.note_hash
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def test_research_citation_manifest_hash_cannot_bind_a_rehashed_different_manifest() -> None:
    api = _bt_api()
    context, bundle, envelope = _research_inputs(note_transform=_mismatched_citation_note)
    assert envelope.note is not None
    changed = envelope.note.citations[0]
    assert changed.provenance.manifest_hash == _citation_manifest_hash(
        SourceManifest.model_validate(
            {
                **{
                    key: value
                    for key, value in changed.provenance.model_dump(mode="json").items()
                    if key != "manifest_hash"
                },
                "source_locator": "fixture://different-valid-source",
                "terms": "fixture terms",
            }
        )
    )
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def test_event_bytes_and_ids_bind_the_complete_canonical_source_snapshot() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)
    decision, opportunity = api.BacktestRunner().run((binding,))
    expected_fingerprint = _source_fingerprint(context, bundle, envelope)
    assert expected_fingerprint == EXPECTED_SOURCE_FINGERPRINT
    assert decision.source_fingerprint == expected_fingerprint
    assert opportunity.source_fingerprint == expected_fingerprint
    assert type(decision) is api.DecisionEvent
    assert type(opportunity) is api.OpportunityEvent

    expected_decision_payload = _decision_event_payload(
        context, bundle, envelope, binding
    )
    expected_decision_id = _event_id(expected_decision_payload)
    assert expected_decision_id == EXPECTED_DECISION_EVENT_ID
    assert decision.event_id == EXPECTED_DECISION_EVENT_ID
    expected_decision = {
        **expected_decision_payload,
        "event_id": EXPECTED_DECISION_EVENT_ID,
        "sequence": 0,
    }
    assert decision.model_dump(mode="json") == expected_decision
    assert decision.canonical_bytes() == json.dumps(
        expected_decision,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")

    expected_opportunity_payload = _opportunity_event_payload(
        context, bundle, envelope, binding, EXPECTED_DECISION_EVENT_ID
    )
    expected_opportunity_id = _event_id(expected_opportunity_payload)
    assert expected_opportunity_id == EXPECTED_OPPORTUNITY_EVENT_ID
    expected_opportunity = {
        **expected_opportunity_payload,
        "event_id": expected_opportunity_id,
        "sequence": 1,
    }
    assert opportunity.model_dump(mode="json") == expected_opportunity
    assert opportunity.canonical_bytes() == json.dumps(
        expected_opportunity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")


def test_event_identity_is_stable_for_permuted_inputs_repeated_runs_and_sequence_offsets() -> None:
    api = _bt_api()
    context_a, bundle_a, envelope_a = _quant_only_inputs(
        variant_id="variant-bt01-a",
        run_id="run-bt01-a",
    )
    context_b, bundle_b, envelope_b = _quant_only_inputs(
        variant_id="variant-bt01-b",
        run_id="run-bt01-b",
    )
    binding_a = api.SessionClock.bind(context_a, bundle_a, envelope_a)
    binding_b = api.SessionClock.bind(context_b, bundle_b, envelope_b)
    runner = api.BacktestRunner()
    forward = runner.run((binding_a, binding_b))
    reverse = runner.run((binding_b, binding_a))
    repeated = runner.run((binding_a, binding_b))
    assert tuple(event.canonical_bytes() for event in forward) == tuple(
        event.canonical_bytes() for event in reverse
    )
    assert tuple(event.canonical_bytes() for event in forward) == tuple(
        event.canonical_bytes() for event in repeated
    )

    offset = runner.run((binding_a,), start_sequence=41)
    assert tuple(event.sequence for event in offset) == (41, 42)
    assert tuple(event.event_id for event in offset) == tuple(
        event.event_id for event in runner.run((binding_a,))
    )


def test_empty_input_is_a_stateless_empty_result_and_repeated_slot_is_rejected() -> None:
    api = _bt_api()
    runner = api.BacktestRunner()
    assert runner.run(()) == ()
    assert runner.run((), start_sequence=MAX_SEQUENCE) == ()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)
    _expect_bt_error(
        api,
        "duplicate_decision_slot",
        lambda: runner.run((binding, binding)),
    )


def test_maximum_binding_and_event_counts_are_accepted_and_one_over_is_rejected() -> None:
    api = _bt_api()
    bundle = quant_fixtures._bundle(cutoff=PRE_CLOSE_CUTOFF)
    quant = quant_fixtures._score(
        quant_fixtures._api(), bundle=bundle, run_id="run-bt01-count-limit"
    )
    bindings = []
    for index in range(257):
        variant_id = f"variant-bt01-limit-{index:03d}"
        context = _context(
            bundle,
            run_id=quant.run_id,
            variant_id=variant_id,
            decision_time=DECISION_TIME,
            earliest_execution_time="2024-07-03T13:30:00Z",
        )
        envelope = combine_quant_overlay(
            quant,
            context=context,
            registry=VariantRegistry().register(variant_id, kind="quant_only"),
        )
        bindings.append(api.SessionClock.bind(context, bundle, envelope))

    runner = api.BacktestRunner()
    at_limit = runner.run(tuple(bindings[:256]))
    assert len(at_limit) == 512
    assert tuple(event.sequence for event in at_limit) == tuple(range(512))
    _expect_bt_error(
        api,
        "resource_limit",
        lambda: runner.run(tuple(bindings)),
    )


def test_conflicting_bindings_for_the_same_decision_slot_are_rejected() -> None:
    api = _bt_api()
    context_a, bundle_a, envelope_a = _quant_only_inputs(
        run_id="run-bt01-slot-a",
        variant_id="variant-bt01-same-slot",
    )
    context_b, bundle_b, envelope_b = _quant_only_inputs(
        run_id="run-bt01-slot-b",
        variant_id="variant-bt01-same-slot",
    )
    binding_a = api.SessionClock.bind(context_a, bundle_a, envelope_a)
    binding_b = api.SessionClock.bind(context_b, bundle_b, envelope_b)
    _expect_bt_error(
        api,
        "duplicate_decision_slot",
        lambda: api.BacktestRunner().run((binding_a, binding_b)),
    )


def test_forced_event_id_collision_rejects_distinct_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)

    class ConstantDigest:
        def hexdigest(self) -> str:
            return "0" * 64

    fake_hashlib = SimpleNamespace(sha256=lambda data: ConstantDigest())
    monkeypatch.setattr(api.events_module, "hashlib", fake_hashlib)
    _expect_bt_error(
        api,
        "duplicate_event_id",
        lambda: api.BacktestRunner().run((binding,)),
    )


def test_bad_start_sequences_and_overflow_fail_before_returning_partial_events() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)
    runner = api.BacktestRunner()
    valid = runner.run((binding,), start_sequence=MAX_SEQUENCE - 1)
    assert tuple(event.sequence for event in valid) == (MAX_SEQUENCE - 1, MAX_SEQUENCE)
    for invalid in (True, -1, MAX_SEQUENCE + 1):
        _expect_bt_error(
            api,
            "sequence_invalid",
            lambda invalid=invalid: runner.run((binding,), start_sequence=invalid),
        )
    _expect_bt_error(
        api,
        "sequence_invalid",
        lambda: runner.run((binding,), start_sequence=MAX_SEQUENCE),
    )


def test_unsupported_iterables_callbacks_and_outcomes_are_rejected_without_consumption() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)
    calls: list[str] = []

    class HostileIterable:
        def __iter__(self) -> object:
            calls.append("iter")
            return iter((binding,))

    _expect_bt_error(
        api,
        "input_invalid",
        lambda: api.BacktestRunner().run(HostileIterable()),
    )
    assert calls == []
    with pytest.raises(TypeError):
        api.BacktestRunner().run((binding,), outcome=object())


def test_runner_denies_network_file_process_environment_and_zoneinfo_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)

    def forbidden(*args: object, **kwargs: object) -> Any:
        del args, kwargs
        pytest.fail("BT-01 attempted an external side effect")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("os.getenv", forbidden)
    events = api.BacktestRunner().run((binding,))
    assert len(events) == 2
    assert all(event.observed_at == context.decision_time for event in events)


def test_bundle_and_context_identity_mismatches_fail_closed() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    different_bundle = _rebuild_bundle(bundle, bundle_id="bundle-bt01-other")
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(context, different_bundle, envelope),
    )
    cutoff_bundle = quant_fixtures._bundle(cutoff="2024-07-01T20:03:00Z")
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(context, cutoff_bundle, envelope),
    )

    different_variant_context = _context(
        bundle,
        run_id=context.run_id,
        variant_id="variant-bt01-different-context",
        decision_time=DECISION_TIME,
        earliest_execution_time=context.earliest_execution_time.isoformat(),
    )
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(different_variant_context, bundle, envelope),
    )

    different_calendar_context = _context(
        bundle,
        run_id=context.run_id,
        variant_id=context.variant_id,
        decision_time=DECISION_TIME,
        earliest_execution_time=context.earliest_execution_time.isoformat(),
        calendar_id="XNYS.other-calendar.v1",
    )
    different_calendar_envelope = combine_quant_overlay(
        envelope.quant,
        context=different_calendar_context,
        registry=VariantRegistry().register(
            different_calendar_context.variant_id, kind="quant_only"
        ),
    )
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(
            different_calendar_context, bundle, different_calendar_envelope
        ),
    )


def test_direct_session_binding_construction_enforces_the_same_contract() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    direct = api.SessionBinding(context, bundle, envelope)
    assert direct.bundle.bundle_id == bundle.bundle_id
    assert len(api.BacktestRunner().run((direct,))) == 2

    mismatched_bundle = _rebuild_bundle(bundle, bundle_id="bundle-bt01-direct-mismatch")
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionBinding(context, mismatched_bundle, envelope),
    )


def test_context_currency_and_witnessed_universe_date_must_match_instrument() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs(base_currency="EUR")
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )

    context, bundle, envelope = _quant_only_inputs(
        run_id="run-bt01-instrument-membership-mismatch"
    )
    unselected_signal = _rehashed_quant_signal(
        envelope.quant,
        instrument_id="inst-not-in-this-bundle",
    )
    unselected_envelope = combine_quant_overlay(
        unselected_signal,
        context=context,
        registry=VariantRegistry().register(context.variant_id, kind="quant_only"),
    )
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(context, bundle, unselected_envelope),
    )

    original_context, original_bundle, original_envelope = _quant_only_inputs()
    expired_instruments = tuple(
        Instrument.model_validate(
            {
                **instrument.model_dump(mode="python"),
                **(
                    {"active_to": date(2024, 7, 2)}
                    if instrument.instrument_id == "inst-survivor"
                    else {}
                ),
            }
        )
        for instrument in original_bundle.instruments
    )
    expired_memberships = tuple(
        UniverseMembership.model_validate(
            {
                **membership.model_dump(mode="python"),
                **(
                    {"valid_to": date(2024, 7, 2)}
                    if membership.instrument_id == "inst-survivor"
                    else {}
                ),
            }
        )
        for membership in original_bundle.memberships
    )
    expired_aliases = tuple(
        SymbolAlias.model_validate(
            {
                **alias.model_dump(mode="python"),
                **(
                    {"valid_to": date(2024, 7, 2)}
                    if alias.instrument_id == "inst-survivor"
                    else {}
                ),
            }
        )
        for alias in original_bundle.aliases
    )
    expired_bundle = _rebuild_bundle(
        original_bundle,
        instruments=expired_instruments,
        aliases=expired_aliases,
        memberships=expired_memberships,
    )
    expired_context, expired_bundle, expired_envelope = _quant_only_inputs(
        bundle=expired_bundle,
        run_id=original_context.run_id,
        variant_id=original_context.variant_id,
    )
    assert original_envelope.quant.instrument_id == "inst-survivor"
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(expired_context, expired_bundle, expired_envelope),
    )


def test_source_getters_are_defensive_and_original_v1_bytes_and_ids_remain_unchanged() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    source_bytes = _canonical_source_bytes(context, bundle, envelope)
    source_ids = (bundle.bundle_id, bundle.bundle_hash, envelope.envelope_id)
    binding = api.SessionClock.bind(context, bundle, envelope)

    first_bundle = binding.bundle
    first_context = binding.context
    first_envelope = binding.envelope
    object.__setattr__(first_bundle, "bundle_id", "bundle-mutated-copy")
    object.__setattr__(first_context, "run_id", "run-mutated-copy")
    object.__setattr__(first_envelope, "envelope_id", "signal-envelope:" + "0" * 64)

    second_bundle = binding.bundle
    second_context = binding.context
    second_envelope = binding.envelope
    assert second_bundle.bundle_id == source_ids[0]
    assert second_context.run_id == context.run_id
    assert second_envelope.envelope_id == source_ids[2]
    assert (bundle.bundle_id, bundle.bundle_hash, envelope.envelope_id) == source_ids
    assert _canonical_source_bytes(context, bundle, envelope) == source_bytes
    assert api.BacktestRunner().run((binding,))


def test_low_level_source_snapshot_tampering_is_detected_before_event_sealing() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)
    slots = getattr(type(binding), "__slots__", ())
    private_bundle_slot = next(
        (
            name
            for name in slots
            if type(object.__getattribute__(binding, name)) is EvidenceBundle
        ),
        None,
    )
    assert private_bundle_slot is not None, "SessionBinding must use private source snapshots"
    changed_bundle = _rebuild_bundle(bundle, bundle_id="bundle-bt01-tampered")
    object.__setattr__(binding, private_bundle_slot, changed_bundle)
    _expect_bt_error(
        api,
        "source_changed",
        lambda: api.BacktestRunner().run((binding,)),
    )


def test_hostile_metaclass_hash_and_equality_are_never_called_during_rejection() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    protocol_calls = {"hash": 0, "eq": 0}

    class HostileMeta(type):
        def __hash__(cls) -> int:
            protocol_calls["hash"] += 1
            return 1

        def __eq__(cls, other: object) -> bool:
            del other
            protocol_calls["eq"] += 1
            return False

    class HostileValue(metaclass=HostileMeta):
        pass

    _expect_bt_error(
        api,
        "input_invalid",
        lambda: api.SessionClock.bind(HostileValue(), bundle, envelope),
    )
    assert protocol_calls == {"hash": 0, "eq": 0}

    corrupted_context = _context(
        bundle,
        run_id=context.run_id,
        variant_id=context.variant_id,
        decision_time=DECISION_TIME,
        earliest_execution_time=context.earliest_execution_time.isoformat(),
    )
    storage = object.__getattribute__(corrupted_context, "__dict__")
    dict.__setitem__(storage, "network_policy", HostileValue())
    protocol_calls.update(hash=0, eq=0)
    _expect_bt_error(
        api,
        "source_invalid",
        lambda: api.SessionClock.bind(corrupted_context, bundle, envelope),
    )
    assert protocol_calls == {"hash": 0, "eq": 0}


def test_hostile_timezone_protocol_is_not_called_before_rejecting_source() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    calls: list[str] = []

    class HostileTimezone(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta:
            del dt
            calls.append("utcoffset")
            raise AssertionError("hostile timezone must not be queried")

        def dst(self, dt: datetime | None) -> timedelta | None:
            del dt
            calls.append("dst")
            raise AssertionError("hostile timezone must not be queried")

    corrupted = datetime(2024, 7, 2, 20, 0, tzinfo=HostileTimezone())
    storage = object.__getattribute__(context, "__dict__")
    dict.__setitem__(storage, "decision_time", corrupted)
    _expect_bt_error(
        api,
        "source_invalid",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )
    assert calls == []


def test_callbacks_proxies_subclasses_and_corrupt_storage_are_rejected_before_protocols() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    protocol_calls: list[str] = []

    class ContextProxy:
        def __getattr__(self, name: str) -> object:
            protocol_calls.append(name)
            raise AssertionError("BT-01 must not inspect a proxy")

    _expect_bt_error(
        api,
        "input_invalid",
        lambda: api.SessionClock.bind(ContextProxy(), bundle, envelope),
    )
    assert protocol_calls == []

    class ContextSubclass(RunContext):
        pass

    subclass = ContextSubclass.model_validate(context.model_dump(mode="python"))
    _expect_bt_error(
        api,
        "input_invalid",
        lambda: api.SessionClock.bind(subclass, bundle, envelope),
    )


def test_source_mutation_after_binding_cannot_change_emitted_events() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)
    before = tuple(event.canonical_bytes() for event in api.BacktestRunner().run((binding,)))
    object.__setattr__(bundle, "bundle_id", "bundle-caller-mutated")
    object.__setattr__(context, "run_id", "run-caller-mutated")
    after = tuple(event.canonical_bytes() for event in api.BacktestRunner().run((binding,)))
    assert after == before


def test_source_revalidation_rejects_corrupt_v1_storage_with_stable_non_echo_error() -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    storage = object.__getattribute__(bundle, "__dict__")
    dict.__setitem__(storage, "bundle_hash", "sha256:" + "0" * 64)
    _expect_bt_error(
        api,
        "source_invalid",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def test_decimal_and_integer_source_bounds_accept_the_limit_and_reject_overflow() -> None:
    api = _bt_api()
    exact_decimal = Decimal("1." + "0" * 62 + "1")
    exact_volume = (1 << 256) - 1
    assert len(exact_decimal.as_tuple().digits) == 64
    assert exact_decimal.as_tuple().exponent == -63
    assert exact_volume.bit_length() == 256

    bundle = _bundle_with_numeric_source(price=exact_decimal, volume=exact_volume)
    context, bundle, envelope = _quant_only_inputs(bundle=bundle)
    binding = api.SessionClock.bind(context, bundle, envelope)
    assert len(api.BacktestRunner().run((binding,))) == 2

    for index, boundary_value in enumerate((Decimal("1E-64"), Decimal("1E64"))):
        boundary_bundle = _bundle_with_numeric_source(
            price=boundary_value,
            volume=1,
        )
        boundary_context, boundary_bundle, boundary_envelope = _quant_only_inputs(
            bundle=boundary_bundle,
            run_id=f"run-bt01-decimal-exponent-{index}",
        )
        assert boundary_value.as_tuple().exponent in {-64, 64}
        boundary_binding = api.SessionClock.bind(
            boundary_context,
            boundary_bundle,
            boundary_envelope,
        )
        assert len(api.BacktestRunner().run((boundary_binding,))) == 2

    over_coefficient = Decimal("1." + "0" * 63 + "1")
    assert len(over_coefficient.as_tuple().digits) == 65
    coefficient_context, coefficient_bundle, coefficient_envelope = (
        _mutated_numeric_inputs(field_name="price", value=over_coefficient)
    )
    _expect_bt_error(
        api,
        "resource_limit",
        lambda: api.SessionClock.bind(
            coefficient_context,
            coefficient_bundle,
            coefficient_envelope,
        ),
    )

    for over_exponent in (Decimal("1E-65"), Decimal("1E65")):
        over_exponent_context, over_exponent_bundle, over_exponent_envelope = (
            _mutated_numeric_inputs(field_name="price", value=over_exponent)
        )
        assert over_exponent.as_tuple().exponent not in {-64, 64}
        _expect_bt_error(
            api,
            "resource_limit",
            lambda c=over_exponent_context, b=over_exponent_bundle, e=over_exponent_envelope: api.SessionClock.bind(
                c, b, e
            ),
        )

    integer_context, integer_bundle, integer_envelope = _mutated_numeric_inputs(
        field_name="volume",
        value=1 << 256,
    )
    _expect_bt_error(
        api,
        "resource_limit",
        lambda: api.SessionClock.bind(
            integer_context,
            integer_bundle,
            integer_envelope,
        ),
    )


def test_single_and_aggregate_canonical_source_byte_limits_are_inclusive() -> None:
    api = _bt_api()
    event_count = 32
    base_bundle = _bundle_with_large_event_bodies((1,) * event_count)
    base_context, _, base_envelope = _large_event_research_inputs(
        base_bundle,
        variant_id="variant-bt01-budget-a",
    )
    base_size = len(BINDING_HASH_DOMAIN) + len(
        _canonical_source_bytes(base_context, base_bundle, base_envelope)
    )
    remaining = MAX_SOURCE_BYTES - base_size
    max_extra = event_count * (MAX_SOURCE_TEXT_BYTES - 1)
    assert 0 < remaining <= max_extra
    per_event, remainder = divmod(remaining, event_count)
    body_lengths = tuple(
        1 + per_event + (1 if index < remainder else 0)
        for index in range(event_count)
    )
    assert max(body_lengths) <= MAX_SOURCE_TEXT_BYTES

    boundary_bundle = _bundle_with_large_event_bodies(body_lengths)
    bindings = []
    assert 8 * MAX_SOURCE_BYTES == MAX_RUN_SOURCE_BYTES
    for suffix in "abcdefghi":
        context, bundle, envelope = _large_event_research_inputs(
            boundary_bundle,
            variant_id=f"variant-bt01-budget-{suffix}",
        )
        source_size = len(BINDING_HASH_DOMAIN) + len(
            _canonical_source_bytes(context, bundle, envelope)
        )
        assert source_size == MAX_SOURCE_BYTES
        bindings.append(api.SessionClock.bind(context, bundle, envelope))

    at_limit = api.BacktestRunner().run(tuple(bindings[:8]))
    assert len(at_limit) == 16
    assert len({event.source_fingerprint for event in at_limit}) == 8
    _expect_bt_error(
        api,
        "resource_limit",
        lambda: api.BacktestRunner().run(tuple(bindings)),
    )


def test_source_text_utf8_limit_accepts_exact_bytes_and_rejects_one_more() -> None:
    api = _bt_api()

    def exact_text(note: ResearchNote) -> ResearchNote:
        return _archive_realistic_note_variant(
            note,
            thesis="x" * MAX_SOURCE_TEXT_BYTES,
        )

    context, bundle, envelope = _research_inputs(note_transform=exact_text)
    assert envelope.note is not None
    assert len(envelope.note.thesis.encode("utf-8")) == MAX_SOURCE_TEXT_BYTES
    assert len(BINDING_HASH_DOMAIN) + len(
        _canonical_source_bytes(context, bundle, envelope)
    ) < MAX_SOURCE_BYTES
    binding = api.SessionClock.bind(context, bundle, envelope)
    assert len(api.BacktestRunner().run((binding,))) == 2

    def one_more_byte(note: ResearchNote) -> ResearchNote:
        return _archive_realistic_note_variant(
            note,
            thesis="x" * (MAX_SOURCE_TEXT_BYTES + 1),
        )

    over_context, over_bundle, over_envelope = _research_inputs(
        note_transform=one_more_byte
    )
    assert over_envelope.note is not None
    assert len(over_envelope.note.thesis.encode("utf-8")) == MAX_SOURCE_TEXT_BYTES + 1
    _expect_bt_error(
        api,
        "resource_limit",
        lambda: api.SessionClock.bind(over_context, over_bundle, over_envelope),
    )


@pytest.mark.parametrize("changed_cache", ("fingerprint", "json", "json_and_fingerprint"))
def test_repair_cached_source_seals_must_match_independently_derived_sources(
    changed_cache: str,
) -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)
    original_bytes = _canonical_source_bytes(context, bundle, envelope)
    original_fingerprint = _source_fingerprint(context, bundle, envelope)
    assert object.__getattribute__(binding, "_sealed_source_json") == original_bytes
    assert object.__getattribute__(binding, "_source_fingerprint") == original_fingerprint
    assert len(api.BacktestRunner().run((binding,))) == 2

    wrong_json = b"{}"
    if changed_cache in ("json", "json_and_fingerprint"):
        object.__setattr__(binding, "_sealed_source_json", wrong_json)
    if changed_cache == "fingerprint":
        object.__setattr__(binding, "_source_fingerprint", "sha256:" + "0" * 64)
    elif changed_cache == "json_and_fingerprint":
        wrong_fingerprint = "sha256:" + hashlib.sha256(
            BINDING_HASH_DOMAIN + wrong_json
        ).hexdigest()
        assert wrong_fingerprint != original_fingerprint
        object.__setattr__(binding, "_source_fingerprint", wrong_fingerprint)
    _expect_bt_error(
        api,
        "source_changed",
        lambda: api.BacktestRunner().run((binding,)),
    )


def test_repair_full_envelope_context_currency_must_equal_ingress_context() -> None:
    api = _bt_api()
    envelope_context, bundle, envelope = _quant_only_inputs(base_currency="EUR")
    context = _context(
        bundle,
        run_id=envelope_context.run_id,
        variant_id=envelope_context.variant_id,
        decision_time=DECISION_TIME,
        earliest_execution_time=envelope_context.earliest_execution_time.isoformat(),
        base_currency="USD",
    )
    assert envelope.context.base_currency == "EUR"
    assert context.base_currency == bundle.instruments[0].currency == "USD"
    _expect_bt_error(
        api,
        "binding_mismatch",
        lambda: api.SessionClock.bind(context, bundle, envelope),
    )


def test_repair_short_source_caches_cannot_underreport_actual_aggregate_bytes() -> None:
    api = _bt_api()
    event_count = 32
    base_bundle = _bundle_with_large_event_bodies((1,) * event_count)
    base_context, _, base_envelope = _large_event_research_inputs(
        base_bundle, variant_id="variant-bt01-budget-a"
    )
    base_size = len(BINDING_HASH_DOMAIN) + len(
        _canonical_source_bytes(base_context, base_bundle, base_envelope)
    )
    per_event, remainder = divmod(MAX_SOURCE_BYTES - base_size, event_count)
    body_lengths = tuple(
        1 + per_event + (1 if index < remainder else 0)
        for index in range(event_count)
    )
    boundary_bundle = _bundle_with_large_event_bodies(body_lengths)
    bindings = []
    actual_run_bytes = 0
    for suffix in "abcdefghi":
        context, bundle, envelope = _large_event_research_inputs(
            boundary_bundle, variant_id=f"variant-bt01-budget-{suffix}"
        )
        actual_bytes = len(BINDING_HASH_DOMAIN) + len(
            _canonical_source_bytes(context, bundle, envelope)
        )
        assert actual_bytes == MAX_SOURCE_BYTES
        actual_run_bytes += actual_bytes
        bindings.append(api.SessionClock.bind(context, bundle, envelope))
    assert actual_run_bytes == 9 * MAX_SOURCE_BYTES > MAX_RUN_SOURCE_BYTES

    # The coherent pair is still false evidence of the retained source content.
    short_json = b"{}"
    short_fingerprint = "sha256:" + hashlib.sha256(
        BINDING_HASH_DOMAIN + short_json
    ).hexdigest()
    for binding in bindings:
        object.__setattr__(binding, "_sealed_source_json", short_json)
        object.__setattr__(binding, "_source_fingerprint", short_fingerprint)
    assert sum(
        len(BINDING_HASH_DOMAIN)
        + len(object.__getattribute__(binding, "_sealed_source_json"))
        for binding in bindings
    ) < MAX_RUN_SOURCE_BYTES
    _expect_bt_error(
        api,
        "source_changed",
        lambda: api.BacktestRunner().run(tuple(bindings)),
    )


@pytest.mark.parametrize("boundary", ("ingress", "getter", "runner"))
@pytest.mark.parametrize("metadata_kind", ("foreign", "set_subclass", "unknown_field", "foreign_field"))
def test_repair_model_fields_set_metadata_rejects_before_caller_protocols(
    boundary: str,
    metadata_kind: str,
) -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)
    assert binding.context == context
    assert len(api.BacktestRunner().run((binding,))) == 2
    calls = {"copy": 0, "deepcopy": 0, "iteration": 0, "hash": 0, "equality": 0}

    class ForeignMetadata:
        def __copy__(self) -> object:
            calls["copy"] += 1
            return self

        def __deepcopy__(self, memo: object) -> object:
            del memo
            calls["deepcopy"] += 1
            return self

        def __iter__(self) -> object:
            calls["iteration"] += 1
            return iter(())

        def __hash__(self) -> int:
            calls["hash"] += 1
            return 1

        def __eq__(self, other: object) -> bool:
            del other
            calls["equality"] += 1
            return False

    class MetadataSet(set, ForeignMetadata):
        def __copy__(self) -> object:
            return ForeignMetadata.__copy__(self)

        def __iter__(self) -> object:
            return ForeignMetadata.__iter__(self)

    if metadata_kind == "foreign":
        metadata = ForeignMetadata()
    elif metadata_kind == "set_subclass":
        metadata = MetadataSet(RunContext.model_fields)
    elif metadata_kind == "unknown_field":
        metadata = {"foreign_stored_field"}
    else:
        metadata = {ForeignMetadata()}
    calls.update(dict.fromkeys(calls, 0))
    target = context if boundary == "ingress" else object.__getattribute__(
        binding, "_context_snapshot"
    )
    object.__setattr__(target, "__pydantic_fields_set__", metadata)
    reason = "source_invalid" if boundary == "ingress" else "source_changed"

    def action() -> object:
        if boundary == "ingress":
            return api.SessionClock.bind(context, bundle, envelope)
        if boundary == "getter":
            return binding.context
        return api.BacktestRunner().run((binding,))
    try:
        _expect_bt_error(api, reason, action)
    finally:
        assert calls == dict.fromkeys(calls, 0)


def _forged_archive_policy_inputs() -> tuple[RunContext, EvidenceBundle, Any]:
    """Make an explicit malicious fixture, without a source authenticity claim."""

    original_context, original_bundle, original_envelope = _quant_only_inputs()
    fake_policy = str.__new__(BundleReplayPolicy, "archive_realistic")
    object.__setattr__(fake_policy, "_name_", "ARCHIVE_REALISTIC")
    object.__setattr__(fake_policy, "_value_", "archive_realistic")
    assert type(fake_policy) is BundleReplayPolicy
    assert fake_policy is not BundleReplayPolicy.ARCHIVE_REALISTIC
    assert fake_policy.value == BundleReplayPolicy.ARCHIVE_REALISTIC.value

    first_bar = original_bundle.bars[0]
    late_manifest = SourceManifest.model_validate(
        {
            **first_bar.manifest.model_dump(mode="python"),
            "ingested_at": original_bundle.knowledge_cutoff + timedelta(minutes=1),
        }
    )
    late_bar = DailyBar.model_validate(
        {**first_bar.model_dump(mode="python"), "manifest": late_manifest}
    )
    bars = (late_bar, *original_bundle.bars[1:])
    wire = original_bundle.model_dump(mode="json")
    wire["bars"] = [bar.model_dump(mode="json") for bar in bars]
    semantic = {
        key: value
        for key, value in wire.items()
        if key not in ("bundle_id", "bundle_hash", "created_at")
    }
    rehashed_bundle_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            semantic, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    payload = original_bundle.model_dump(mode="python")
    payload.update(bars=bars, bundle_hash=rehashed_bundle_hash)
    with pytest.raises(ValueError, match="ineligible_bars_evidence_in_sealed_bundle"):
        EvidenceBundle.model_validate(payload)
    payload["replay_policy"] = fake_policy
    bundle = EvidenceBundle.model_validate(payload)
    assert bundle.replay_policy is fake_policy
    assert bundle.bars[0].manifest.ingested_at > bundle.knowledge_cutoff
    context = _context(
        bundle,
        run_id=original_context.run_id,
        variant_id=original_context.variant_id,
        decision_time=DECISION_TIME,
        earliest_execution_time=original_context.earliest_execution_time.isoformat(),
    )
    quant = _rehashed_quant_signal(
        original_envelope.quant, bundle_id=bundle.bundle_id, bundle_hash=bundle.bundle_hash
    )
    envelope = combine_quant_overlay(
        quant,
        context=context,
        registry=VariantRegistry().register(context.variant_id, kind="quant_only"),
    )
    return context, bundle, envelope


def test_repair_forged_archive_enum_rejects_before_inherited_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt_api()
    canonical_context, canonical_bundle, canonical_envelope = _quant_only_inputs()
    assert canonical_bundle.replay_policy is BundleReplayPolicy.ARCHIVE_REALISTIC
    canonical_binding = api.SessionClock.bind(
        canonical_context, canonical_bundle, canonical_envelope
    )
    assert len(api.BacktestRunner().run((canonical_binding,))) == 2
    context, bundle, envelope = _forged_archive_policy_inputs()
    original_validate = EvidenceBundle.model_validate
    inherited_calls: list[str] = []

    def track_validation(cls: type, *args: Any, **kwargs: Any) -> EvidenceBundle:
        del cls
        inherited_calls.append("bundle_validation")
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(EvidenceBundle, "model_validate", classmethod(track_validation))
    try:
        _expect_bt_error(
            api, "source_invalid", lambda: api.SessionClock.bind(context, bundle, envelope)
        )
    finally:
        assert inherited_calls == []


@pytest.mark.parametrize("mutation", ("cache_only", "coherent_sources_and_seals"))
def test_repair_completion_must_equal_retained_ingress_sources(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    api = _bt_api()
    context, bundle, envelope = _quant_only_inputs()
    binding = api.SessionClock.bind(context, bundle, envelope)
    new_context, new_bundle, new_envelope = _quant_only_inputs(run_id="run-bt01-replacement")
    replacement = api.SessionClock.bind(new_context, new_bundle, new_envelope)
    original_events = api.BacktestRunner().run((binding,))
    replacement_events = api.BacktestRunner().run((replacement,))
    assert tuple(event.run_id for event in original_events) == (context.run_id,) * 2
    assert tuple(event.run_id for event in replacement_events) == (new_context.run_id,) * 2
    assert original_events[0].source_fingerprint != replacement_events[0].source_fingerprint
    original_builder = api.runner_module._build_decision_event
    builder_calls: list[str] = []

    def mutate_after_decision(**kwargs: Any) -> Any:
        decision = original_builder(**kwargs)
        assert decision.run_id == context.run_id
        builder_calls.append("decision_built")
        if mutation == "cache_only":
            changed_json = b"{}"
            object.__setattr__(binding, "_sealed_source_json", changed_json)
            object.__setattr__(
                binding,
                "_source_fingerprint",
                "sha256:" + hashlib.sha256(BINDING_HASH_DOMAIN + changed_json).hexdigest(),
            )
        else:
            # Replace every private source and seal with another valid binding.
            for slot in type(binding).__slots__:
                object.__setattr__(binding, slot, object.__getattribute__(replacement, slot))
        return decision

    monkeypatch.setattr(api.runner_module, "_build_decision_event", mutate_after_decision)
    result = None

    def run() -> None:
        nonlocal result
        result = api.BacktestRunner().run((binding,))

    _expect_bt_error(api, "source_changed", run)
    assert builder_calls == ["decision_built"]
    assert result is None

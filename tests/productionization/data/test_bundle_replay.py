"""PIT-06 contract for canonical EvidenceBundle sealing and offline replay."""

from __future__ import annotations

import builtins
import inspect
import json
import socket
import time
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

import mytradingalpha.data.replay_guard as replay_guard_module
from mytradingalpha.contracts.schemas import Mode, NetworkPolicy, RunContext
from mytradingalpha.data.actions import (
    CorporateAction,
    DelistingAction,
    DividendAction,
    SplitAction,
    TickerChangeAction,
)
from mytradingalpha.data.bars import BarFinality, DailyBar
from mytradingalpha.data.bundle import (
    BundleReplayPolicy,
    EvidenceBundle,
    EvidenceBundleError,
    EvidenceDomain,
    EvidenceRequirement,
    InvalidEvidenceError,
    MissingEvidence,
    MissingRequiredEvidenceError,
    build_evidence_bundle,
)
from mytradingalpha.data.calendar import (
    CalendarClosure,
    CalendarCoverageRange,
    TradingCalendar,
    TradingSession,
)
from mytradingalpha.data.events import NewsEvent
from mytradingalpha.data.fundamentals import FinancialFiling
from mytradingalpha.data.macro import MacroObservation
from mytradingalpha.data.provenance import SourceManifest
from mytradingalpha.data.replay_guard import (
    HistoricalDataGuard,
    HistoricalDataGuardError,
    HistoricalReplayDeniedError,
    HistoricalReplayMismatchError,
)
from mytradingalpha.data.repository import (
    EvidenceBundleConflictError,
    EvidenceBundleCorruptionError,
    EvidenceBundleNotFoundError,
    EvidenceRepository,
    EvidenceRepositoryError,
)
from mytradingalpha.data.social import SocialPlatform, SocialPost
from mytradingalpha.data.universe import Instrument, SymbolAlias, UniverseMembership

FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "pit"
FIXTURE_PATH = FIXTURE_DIRECTORY / "evidence_bundle_v1.json"


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _fixture() -> dict[str, object]:
    return _load_json(FIXTURE_PATH)


def _fixture_mapping(name: str) -> dict[str, object]:
    fixture = _fixture()
    sources = fixture["source_fixtures"]
    assert isinstance(sources, dict)
    source_name = sources[name]
    assert isinstance(source_name, str)
    return _load_json(FIXTURE_DIRECTORY / source_name)


def _calendar() -> TradingCalendar:
    payload = _fixture_mapping("calendar")
    return TradingCalendar(
        schema_version=payload["schema_version"],
        calendar_id=payload["calendar_id"],
        timezone=payload["timezone"],
        coverage_start=payload["coverage_start"],
        coverage_end=payload["coverage_end"],
        coverage_ranges=tuple(
            CalendarCoverageRange.model_validate(item) for item in payload["coverage_ranges"]
        ),
        closures=tuple(CalendarClosure.model_validate(item) for item in payload["closures"]),
        schedule=tuple(TradingSession.model_validate(item) for item in payload["sessions"]),
    )


def _indexed_payloads(
    source_name: str,
    collection: str,
) -> tuple[dict[str, object], ...]:
    fixture = _fixture()
    indexes_by_collection = fixture["candidate_indexes"]
    assert isinstance(indexes_by_collection, dict)
    indexes = indexes_by_collection[collection]
    assert isinstance(indexes, list)
    source = _fixture_mapping(source_name)
    records = source[collection]
    assert isinstance(records, list)
    result: list[dict[str, object]] = []
    for index in indexes:
        assert isinstance(index, int)
        payload = deepcopy(records[index])
        assert isinstance(payload, dict)
        result.append(payload)
    return tuple(result)


def _models(
    source_name: str,
    collection: str,
    model: type[Instrument]
    | type[SymbolAlias]
    | type[UniverseMembership]
    | type[FinancialFiling]
    | type[NewsEvent]
    | type[SocialPost]
    | type[MacroObservation],
) -> tuple[object, ...]:
    return tuple(model.model_validate(item) for item in _indexed_payloads(source_name, collection))


def _actions() -> tuple[CorporateAction, ...]:
    adapter = TypeAdapter(CorporateAction)
    return tuple(
        adapter.validate_python(item) for item in _indexed_payloads("universe_actions", "actions")
    )


def _bars() -> tuple[DailyBar, ...]:
    fixture = _fixture()
    candidates = fixture["bar_candidates"]
    assert isinstance(candidates, list)
    return tuple(DailyBar.model_validate(item) for item in candidates)


def _social_candidates(*indexes: int) -> tuple[SocialPost, ...]:
    source = _fixture_mapping("events_social_macro")
    candidates = source["social_posts"]
    assert isinstance(candidates, list)
    return tuple(SocialPost.model_validate(candidates[index]) for index in indexes)


def _additional_instruments() -> tuple[Instrument, ...]:
    fixture = _fixture()
    candidates = fixture["additional_instruments"]
    assert isinstance(candidates, list)
    return tuple(Instrument.model_validate(item) for item in candidates)


def _updated_manifest(
    manifest: SourceManifest,
    **updates: object,
) -> SourceManifest:
    return SourceManifest.model_validate(
        {**manifest.model_dump(mode="python"), **updates}
    )


def _requirements() -> tuple[EvidenceRequirement, ...]:
    fixture = _fixture()
    requirements = fixture["requirements"]
    assert isinstance(requirements, list)
    return tuple(EvidenceRequirement.model_validate(item) for item in requirements)


def _missing_optional() -> tuple[MissingEvidence, ...]:
    fixture = _fixture()
    missing = fixture["missing_optional"]
    assert isinstance(missing, list)
    return tuple(MissingEvidence.model_validate(item) for item in missing)


def _candidate_fields() -> dict[str, object]:
    return {
        "calendar": _calendar(),
        "instrument_candidates": (
            *_models("universe_actions", "instruments", Instrument),
            *_additional_instruments(),
        ),
        "alias_candidates": _models("universe_actions", "aliases", SymbolAlias),
        "membership_candidates": _models("universe_actions", "memberships", UniverseMembership),
        "action_candidates": _actions(),
        "bar_candidates": _bars(),
        "filing_candidates": _models("financial_vintages", "filings", FinancialFiling),
        "event_candidates": _models("events_social_macro", "events", NewsEvent),
        "social_post_candidates": _models("events_social_macro", "social_posts", SocialPost),
        "macro_observation_candidates": _models(
            "events_social_macro", "macro_observations", MacroObservation
        ),
    }


def _build(**overrides: object) -> EvidenceBundle:
    fixture = _fixture()
    fields: dict[str, object] = {
        "schema_version": fixture["schema_version"],
        "bundle_id": fixture["bundle_id"],
        "created_at": fixture["created_at"],
        "knowledge_cutoff": fixture["knowledge_cutoff"],
        "replay_policy": fixture["replay_policy"],
        "requirements": _requirements(),
        "missing_optional": _missing_optional(),
        **_candidate_fields(),
    }
    fields.update(overrides)
    return build_evidence_bundle(**fields)  # type: ignore[arg-type]


def _context(bundle: EvidenceBundle, **overrides: object) -> RunContext:
    fields: dict[str, object] = {
        "schema_version": "v1",
        "run_id": "run-pit-06",
        "mode": Mode.HISTORICAL,
        "variant_id": "variant-replay",
        "decision_time": "2024-07-01T20:00:00Z",
        "knowledge_cutoff": bundle.knowledge_cutoff,
        "earliest_execution_time": "2024-07-02T13:30:00Z",
        "bundle_id": bundle.bundle_id,
        "bundle_hash": bundle.bundle_hash,
        "calendar_id": bundle.calendar.calendar_id,
        "base_currency": "USD",
        "network_policy": NetworkPolicy(),
    }
    fields.update(overrides)
    return RunContext(**fields)  # type: ignore[arg-type]


def _retime_manifest(
    manifest: SourceManifest,
    *,
    available_at: str,
    fetched_at: str,
    ingested_at: str,
) -> SourceManifest:
    payload = manifest.model_dump(mode="python")
    payload.update(
        available_at=available_at,
        fetched_at=fetched_at,
        ingested_at=ingested_at,
    )
    return SourceManifest.model_validate(payload)


def test_pit_06_public_enums_errors_and_explicit_signatures_are_stable() -> None:
    assert {item.value for item in EvidenceDomain} == {
        "calendar",
        "instruments",
        "aliases",
        "memberships",
        "actions",
        "bars",
        "filings",
        "events",
        "social",
        "macro",
    }
    assert {item.value for item in BundleReplayPolicy} == {
        "availability",
        "archive_realistic",
    }
    assert issubclass(MissingRequiredEvidenceError, EvidenceBundleError)
    assert issubclass(InvalidEvidenceError, EvidenceBundleError)
    assert issubclass(EvidenceBundleConflictError, EvidenceRepositoryError)
    assert issubclass(EvidenceBundleNotFoundError, EvidenceRepositoryError)
    assert issubclass(EvidenceBundleCorruptionError, EvidenceRepositoryError)
    assert issubclass(HistoricalReplayDeniedError, HistoricalDataGuardError)
    assert issubclass(HistoricalReplayMismatchError, HistoricalDataGuardError)

    assert tuple(inspect.signature(build_evidence_bundle).parameters) == (
        "schema_version",
        "bundle_id",
        "created_at",
        "knowledge_cutoff",
        "replay_policy",
        "requirements",
        "missing_optional",
        "calendar",
        "instrument_candidates",
        "alias_candidates",
        "membership_candidates",
        "action_candidates",
        "bar_candidates",
        "filing_candidates",
        "event_candidates",
        "social_post_candidates",
        "macro_observation_candidates",
    )
    assert tuple(inspect.signature(EvidenceRepository.seal).parameters) == (
        "self",
        "bundle",
    )
    assert tuple(inspect.signature(EvidenceRepository.get).parameters) == (
        "self",
        "bundle_id",
    )
    assert tuple(inspect.signature(HistoricalDataGuard.replay).parameters) == (
        "repository",
        "bundle_id",
        "context",
    )


def test_bundle_contracts_are_frozen_strict_and_expose_only_v1_fields() -> None:
    assert set(EvidenceRequirement.model_fields) == {
        "schema_version",
        "domain",
        "required",
    }
    assert set(MissingEvidence.model_fields) == {
        "schema_version",
        "domain",
        "reason",
    }
    assert set(EvidenceBundle.model_fields) == {
        "schema_version",
        "bundle_id",
        "bundle_hash",
        "created_at",
        "knowledge_cutoff",
        "replay_policy",
        "requirements",
        "missing_optional",
        "calendar",
        "instruments",
        "aliases",
        "memberships",
        "actions",
        "bars",
        "filings",
        "events",
        "social_posts",
        "macro_observations",
    }

    with pytest.raises(ValidationError):
        EvidenceRequirement(
            schema_version="v1",
            domain=EvidenceDomain.BARS,
            required=1,
        )
    with pytest.raises(ValidationError):
        EvidenceRequirement(
            schema_version="v1",
            domain=EvidenceDomain.BARS,
            required=True,
            extra_field="forbidden",  # type: ignore[call-arg]
        )

    bundle = _build()
    assert all(
        isinstance(value, tuple)
        for value in (
            bundle.requirements,
            bundle.missing_optional,
            bundle.instruments,
            bundle.aliases,
            bundle.memberships,
            bundle.actions,
            bundle.bars,
            bundle.filings,
            bundle.events,
            bundle.social_posts,
            bundle.macro_observations,
        )
    )
    with pytest.raises(ValidationError):
        bundle.bundle_id = "changed"


def test_fixture_build_selects_highest_eligible_revisions_and_missing_optional() -> None:
    bundle = _build()

    assert bundle.schema_version == "v1"
    assert bundle.bundle_id == "bundle-2024-06-30"
    assert bundle.created_at == datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert bundle.knowledge_cutoff == datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
    assert bundle.replay_policy is BundleReplayPolicy.ARCHIVE_REALISTIC
    assert bundle.calendar.calendar_id == "XNYS.synthetic.v1"
    assert bundle.social_posts == ()
    assert bundle.missing_optional == (
        MissingEvidence(
            schema_version="v1",
            domain=EvidenceDomain.SOCIAL,
            reason="optional_source_not_captured",
        ),
    )
    assert (
        next(
            action for action in bundle.actions if isinstance(action, DividendAction)
        ).manifest.revision
        == 1
    )
    assert bundle.bars[0].manifest.revision == 1
    assert bundle.bars[0].close.as_tuple() == _bars()[1].close.as_tuple()
    assert bundle.filings[0].filing_id == "AAPL-2023-10K-r1"
    assert bundle.events[0].event_id == "news-aapl-earnings"
    assert bundle.events[0].manifest.revision == 1
    assert bundle.macro_observations[0].manifest.revision == 1
    assert bundle.bundle_hash == _fixture()["expected_bundle_hash"]


def test_canonical_hash_and_order_ignore_only_bundle_identity_and_creation_time() -> None:
    candidates = _candidate_fields()
    first = _build()
    second = _build(
        bundle_id="bundle-other-id",
        created_at="2040-12-31T23:59:59Z",
        instrument_candidates=tuple(reversed(candidates["instrument_candidates"])),
        alias_candidates=tuple(reversed(candidates["alias_candidates"])),
        membership_candidates=tuple(reversed(candidates["membership_candidates"])),
        action_candidates=tuple(reversed(candidates["action_candidates"])),
        bar_candidates=tuple(reversed(candidates["bar_candidates"])),
        filing_candidates=tuple(reversed(candidates["filing_candidates"])),
        event_candidates=tuple(reversed(candidates["event_candidates"])),
        macro_observation_candidates=tuple(reversed(candidates["macro_observation_candidates"])),
        requirements=tuple(reversed(_requirements())),
    )

    assert second.bundle_hash == first.bundle_hash
    assert tuple(item.instrument_id for item in second.instruments) == tuple(
        sorted(item.instrument_id for item in second.instruments)
    )
    assert tuple(item.domain.value for item in second.requirements) == tuple(
        sorted(item.domain.value for item in second.requirements)
    )


def test_every_semantic_control_changes_the_hash() -> None:
    baseline = _build()
    availability = _build(replay_policy=BundleReplayPolicy.AVAILABILITY)
    earlier_cutoff = _build(knowledge_cutoff="2024-06-29T23:59:59Z")
    optional_macro = _build(
        requirements=tuple(
            requirement.model_copy(update={"required": False})
            if requirement.domain is EvidenceDomain.MACRO
            else requirement
            for requirement in _requirements()
        )
    )
    alternate_calendar = _calendar().model_copy(update={"calendar_id": "XNYS.synthetic.v2"})
    alternate_calendar = TradingCalendar.model_validate(
        {
            **alternate_calendar.model_dump(mode="python"),
            "schedule": tuple(
                session.model_copy(update={"calendar_id": "XNYS.synthetic.v2"})
                for session in alternate_calendar.schedule
            ),
            "closures": tuple(
                closure.model_copy(update={"calendar_id": "XNYS.synthetic.v2"})
                for closure in alternate_calendar.closures
            ),
        }
    )
    alternate_bars = tuple(
        bar.model_copy(update={"calendar_id": "XNYS.synthetic.v2"})
        for bar in _bars()
    )
    changed_calendar = _build(
        calendar=alternate_calendar,
        bar_candidates=alternate_bars,
    )

    hashes = {
        baseline.bundle_hash,
        availability.bundle_hash,
        earlier_cutoff.bundle_hash,
        optional_macro.bundle_hash,
        changed_calendar.bundle_hash,
    }
    assert len(hashes) == 5


@pytest.mark.parametrize(
    ("candidate_field", "bundle_field"),
    [
        ("instrument_candidates", "instruments"),
        ("alias_candidates", "aliases"),
        ("membership_candidates", "memberships"),
        ("action_candidates", "actions"),
        ("bar_candidates", "bars"),
        ("filing_candidates", "filings"),
        ("event_candidates", "events"),
        ("macro_observation_candidates", "macro_observations"),
    ],
)
def test_each_selected_domain_is_semantic(
    candidate_field: str,
    bundle_field: str,
) -> None:
    baseline = _build()
    candidates = _candidate_fields()[candidate_field]
    assert isinstance(candidates, tuple)
    if candidate_field == "instrument_candidates":
        changed_candidates = tuple(
            candidate.model_copy(update={"exchange": "ARCX"})
            if candidate.instrument_id == "AAPL"
            else candidate
            for candidate in candidates
        )
    else:
        changed_candidates = candidates[:-1]
    changed = _build(**{candidate_field: changed_candidates})

    assert getattr(changed, bundle_field) != getattr(baseline, bundle_field)
    assert changed.bundle_hash != baseline.bundle_hash


def test_availability_and_archive_realistic_policies_use_distinct_cutoffs() -> None:
    cutoff = "2024-05-30T23:59:59Z"
    archive_bundle = _build(knowledge_cutoff=cutoff)
    availability_bundle = _build(
        knowledge_cutoff=cutoff,
        replay_policy=BundleReplayPolicy.AVAILABILITY,
    )

    archive_dividend = next(
        action for action in archive_bundle.actions if isinstance(action, DividendAction)
    )
    availability_dividend = next(
        action for action in availability_bundle.actions if isinstance(action, DividendAction)
    )
    assert archive_dividend.manifest.revision == 0
    assert availability_dividend.manifest.revision == 1


def test_required_missing_fails_and_optional_missing_must_be_explicit() -> None:
    with pytest.raises(MissingRequiredEvidenceError, match="macro"):
        _build(macro_observation_candidates=())

    with pytest.raises(InvalidEvidenceError, match="social"):
        _build(missing_optional=())

    with pytest.raises(MissingRequiredEvidenceError, match="social"):
        _build(
            requirements=tuple(
                item.model_copy(update={"required": True})
                if item.domain is EvidenceDomain.SOCIAL
                else item
                for item in _requirements()
            ),
            missing_optional=(),
        )


def test_future_candidates_are_filtered_before_requiredness_is_evaluated() -> None:
    bar = _bars()[1]
    future = bar.model_copy(
        update={
            "manifest": _retime_manifest(
                bar.manifest,
                available_at="2025-01-01T00:00:00Z",
                fetched_at="2025-01-01T00:01:00Z",
                ingested_at="2025-01-01T00:02:00Z",
            )
        }
    )

    with pytest.raises(MissingRequiredEvidenceError, match="bars"):
        _build(bar_candidates=(future,))


def test_live_only_and_undated_or_bypassed_invalid_candidates_fail_closed() -> None:
    source = _fixture_mapping("events_social_macro")
    events = source["events"]
    assert isinstance(events, list)
    live_only = NewsEvent.model_validate(events[4])
    with pytest.raises(InvalidEvidenceError, match="live"):
        _build(event_candidates=(*_candidate_fields()["event_candidates"], live_only))

    event = _models("events_social_macro", "events", NewsEvent)[0]
    assert isinstance(event, NewsEvent)
    undated_manifest = SourceManifest.model_construct(
        **{
            **event.manifest.model_dump(mode="python"),
            "event_time": None,
            "published_at": None,
        }
    )
    undated = NewsEvent.model_construct(
        **{**event.model_dump(mode="python"), "manifest": undated_manifest}
    )
    with pytest.raises(InvalidEvidenceError, match="undated"):
        _build(event_candidates=(undated,))

    invalid = event.model_copy(deep=True)
    object.__setattr__(invalid.manifest, "revision", -1)
    with pytest.raises(InvalidEvidenceError):
        _build(event_candidates=(invalid,))


def test_requirement_matrix_is_complete_unique_and_matches_missing_records() -> None:
    duplicate = (*_requirements(), _requirements()[0])
    with pytest.raises(InvalidEvidenceError, match="requirement"):
        _build(requirements=duplicate)

    with pytest.raises(InvalidEvidenceError, match="requirement"):
        _build(requirements=_requirements()[:-1])

    extra_missing = (
        *_missing_optional(),
        MissingEvidence(
            schema_version="v1",
            domain=EvidenceDomain.EVENTS,
            reason="contradicts_present_evidence",
        ),
    )
    with pytest.raises(InvalidEvidenceError, match="events"):
        _build(missing_optional=extra_missing)


def test_repository_is_idempotent_by_id_and_hash_with_typed_failures() -> None:
    repository = EvidenceRepository()
    bundle = _build()

    sealed = repository.seal(bundle)
    repeated = repository.seal(bundle)
    assert sealed == bundle
    assert repeated == bundle
    assert repository.get(bundle.bundle_id) == bundle

    conflict = _build(
        replay_policy=BundleReplayPolicy.AVAILABILITY,
        bundle_id=bundle.bundle_id,
    )
    with pytest.raises(EvidenceBundleConflictError):
        repository.seal(conflict)
    with pytest.raises(EvidenceBundleNotFoundError):
        repository.get("bundle-does-not-exist")
    with pytest.raises(EvidenceRepositoryError):
        repository.get(" invalid ")


def test_repository_revalidates_rehashes_and_defensively_copies_both_boundaries() -> None:
    repository = EvidenceRepository()
    original = _build()
    expected_calendar_id = original.calendar.calendar_id
    repository.seal(original)

    object.__setattr__(original.calendar, "calendar_id", "tampered-original")
    assert repository.get(original.bundle_id).calendar.calendar_id == expected_calendar_id

    returned = repository.get(original.bundle_id)
    object.__setattr__(returned.calendar, "calendar_id", "tampered-return")
    assert repository.get(original.bundle_id).calendar.calendar_id == expected_calendar_id

    bad_hash = _build()
    object.__setattr__(
        bad_hash,
        "bundle_hash",
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    )
    with pytest.raises(EvidenceBundleCorruptionError):
        EvidenceRepository().seal(bad_hash)

    stored = repository._bundles[original.bundle_id]
    object.__setattr__(stored.calendar, "calendar_id", "tampered-store")
    with pytest.raises(EvidenceBundleCorruptionError):
        repository.get(original.bundle_id)


def test_historical_guard_requires_concretely_validated_historical_zero_egress() -> None:
    bundle = _build()
    context = _context(bundle)
    HistoricalDataGuard.assert_network_denied(context)

    with pytest.raises(HistoricalReplayDeniedError):
        HistoricalDataGuard.assert_network_denied(_context(bundle, mode=Mode.FORWARD_PAPER))

    bypassed_policy = NetworkPolicy.model_construct(data_capture_egress=True)
    bypassed_context = RunContext.model_construct(
        **{
            **context.model_dump(mode="python"),
            "network_policy": bypassed_policy,
        }
    )
    with pytest.raises(HistoricalReplayDeniedError):
        HistoricalDataGuard.assert_network_denied(bypassed_context)


@pytest.mark.parametrize(
    "override",
    [
        {"bundle_id": "bundle-wrong"},
        {
            "bundle_hash": (
                "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            )
        },
        {"knowledge_cutoff": "2024-06-29T23:59:59Z"},
        {"calendar_id": "calendar-wrong"},
    ],
)
def test_replay_binds_context_to_exact_bundle_identity_hash_cutoff_and_calendar(
    override: dict[str, object],
) -> None:
    repository = EvidenceRepository()
    bundle = repository.seal(_build())

    with pytest.raises(HistoricalReplayMismatchError):
        HistoricalDataGuard.replay(
            repository,
            bundle.bundle_id,
            _context(bundle, **override),
        )


def test_replay_is_repeatable_and_performs_no_file_network_or_clock_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = EvidenceRepository()
    bundle = repository.seal(_build())
    context = _context(bundle)

    def denied(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("historical replay attempted external I/O or wall-clock access")

    monkeypatch.setattr(builtins, "open", denied)
    monkeypatch.setattr(Path, "open", denied)
    monkeypatch.setattr(Path, "read_text", denied)
    monkeypatch.setattr(Path, "write_text", denied)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(time, "time", denied)
    if hasattr(replay_guard_module, "datetime"):

        class DeniedDateTime:
            @classmethod
            def now(cls, *_args: object, **_kwargs: object) -> object:
                return denied()

            @classmethod
            def utcnow(cls, *_args: object, **_kwargs: object) -> object:
                return denied()

        monkeypatch.setattr(replay_guard_module, "datetime", DeniedDateTime)

    first = HistoricalDataGuard.replay(repository, bundle.bundle_id, context)
    second = HistoricalDataGuard.replay(repository, bundle.bundle_id, context)
    assert first == second == bundle
    assert first is not second


def test_runtime_boundaries_reject_bypassed_bundle_and_context_mutation() -> None:
    repository = EvidenceRepository()
    bundle = repository.seal(_build())
    context = _context(bundle)

    tampered_context = context.model_copy(deep=True)
    object.__setattr__(tampered_context, "bundle_hash", "not-a-canonical-hash")
    with pytest.raises(HistoricalReplayDeniedError):
        HistoricalDataGuard.replay(
            repository,
            bundle.bundle_id,
            tampered_context,
        )

    tampered_bundle = bundle.model_copy(deep=True)
    object.__setattr__(tampered_bundle.bars[0].manifest, "revision", -1)
    with pytest.raises(EvidenceBundleCorruptionError):
        EvidenceRepository().seal(tampered_bundle)


@pytest.mark.parametrize(
    "defect",
    [
        "calendar_mismatch",
        "preliminary",
        "undated",
        "event_time_mismatch",
    ],
)
def test_bundle_revalidates_selected_bars_as_one_calendar_aggregate(defect: str) -> None:
    bar = _bars()[1]
    if defect == "calendar_mismatch":
        invalid = bar.model_copy(update={"calendar_id": "OTHER.synthetic.v1"})
    elif defect == "preliminary":
        invalid = bar.model_copy(update={"finality": BarFinality.PRELIMINARY})
    elif defect == "undated":
        invalid = bar.model_copy(
            update={
                "manifest": _updated_manifest(bar.manifest, event_time=None),
            }
        )
    else:
        invalid = bar.model_copy(
            update={
                "manifest": _updated_manifest(
                    bar.manifest,
                    event_time="2024-03-08T20:59:00Z",
                ),
            }
        )

    with pytest.raises(InvalidEvidenceError, match="bars"):
        _build(bar_candidates=(invalid,))


@pytest.mark.parametrize("domain", ["aliases", "memberships"])
def test_bundle_rejects_orphan_universe_records(domain: str) -> None:
    candidates = _candidate_fields()
    if domain == "aliases":
        aliases = candidates["alias_candidates"]
        assert isinstance(aliases, tuple)
        orphan = aliases[0].model_copy(update={"instrument_id": "instrument-missing"})
        overrides = {"alias_candidates": (orphan, *aliases[1:])}
    else:
        memberships = candidates["membership_candidates"]
        assert isinstance(memberships, tuple)
        orphan = memberships[0].model_copy(
            update={"instrument_id": "instrument-missing"}
        )
        overrides = {"membership_candidates": (orphan, *memberships[1:])}

    with pytest.raises(InvalidEvidenceError, match=domain):
        _build(**overrides)


@pytest.mark.parametrize(
    "domain",
    ["actions", "filings", "events", "social", "macro"],
)
def test_bundle_rejects_aggregate_revision_series_and_chronology_conflicts(
    domain: str,
) -> None:
    if domain == "actions":
        actions = list(_actions())
        actions[3] = actions[3].model_copy(update={"instrument_id": "AAPL"})
        overrides: dict[str, object] = {"action_candidates": tuple(actions)}
    elif domain == "filings":
        filings = _candidate_fields()["filing_candidates"]
        assert isinstance(filings, tuple)
        revision = filings[1]
        regressed_manifest = _updated_manifest(
            revision.manifest,
            published_at="2024-02-14T13:00:00Z",
            available_at="2024-02-14T13:05:00Z",
            fetched_at="2024-02-14T13:06:00Z",
            ingested_at="2024-02-14T13:07:00Z",
        )
        regressed = revision.model_copy(
            update={
                "filed_at": datetime(2024, 2, 14, 13, 0, tzinfo=timezone.utc),
                "manifest": regressed_manifest,
            }
        )
        overrides = {"filing_candidates": (filings[0], regressed)}
    elif domain == "events":
        events = _candidate_fields()["event_candidates"]
        assert isinstance(events, tuple)
        changed = events[1].model_copy(update={"instrument_id": "inst-acme"})
        overrides = {"event_candidates": (events[0], changed, *events[2:])}
    elif domain == "social":
        posts = _social_candidates(0, 1)
        changed = posts[1].model_copy(update={"platform": SocialPlatform.STOCKTWITS})
        overrides = {
            "social_post_candidates": (posts[0], changed),
            "missing_optional": (),
        }
    else:
        observations = _candidate_fields()["macro_observation_candidates"]
        assert isinstance(observations, tuple)
        changed = observations[1].model_copy(update={"units": "percent"})
        overrides = {"macro_observation_candidates": (observations[0], changed)}

    with pytest.raises(InvalidEvidenceError, match=domain):
        _build(**overrides)


@pytest.mark.parametrize(
    "domain",
    ["actions", "bars", "filings", "events", "social"],
)
def test_every_instrument_bearing_domain_references_a_selected_instrument(
    domain: str,
) -> None:
    candidates = _candidate_fields()
    if domain == "actions":
        actions = candidates["action_candidates"]
        assert isinstance(actions, tuple)
        orphan = actions[0].model_copy(update={"instrument_id": "instrument-missing"})
        overrides: dict[str, object] = {
            "action_candidates": (orphan, *actions[1:]),
        }
    elif domain == "bars":
        bars = candidates["bar_candidates"]
        assert isinstance(bars, tuple)
        orphan = bars[1].model_copy(update={"instrument_id": "instrument-missing"})
        overrides = {"bar_candidates": (orphan,)}
    elif domain == "filings":
        filings = candidates["filing_candidates"]
        assert isinstance(filings, tuple)
        orphan = filings[1].model_copy(update={"instrument_id": "instrument-missing"})
        overrides = {"filing_candidates": (orphan,)}
    elif domain == "events":
        events = candidates["event_candidates"]
        assert isinstance(events, tuple)
        orphan = events[1].model_copy(update={"instrument_id": "instrument-missing"})
        overrides = {"event_candidates": (orphan, *events[2:])}
    else:
        orphan = _social_candidates(1)[0].model_copy(
            update={"instrument_id": "instrument-missing"}
        )
        overrides = {
            "social_post_candidates": (orphan,),
            "missing_optional": (),
        }

    with pytest.raises(InvalidEvidenceError, match="instrument"):
        _build(**overrides)


def test_same_primary_id_from_different_sources_is_rejected_in_every_order() -> None:
    event = _models("events_social_macro", "events", NewsEvent)[2]
    assert isinstance(event, NewsEvent)
    other_source = event.model_copy(
        update={
            "manifest": _updated_manifest(event.manifest, source="other-news-source"),
        }
    )

    for candidates in ((event, other_source), (other_source, event)):
        with pytest.raises(InvalidEvidenceError, match="events"):
            _build(event_candidates=candidates)


def test_nonempty_social_evidence_is_canonical_semantic_input() -> None:
    posts = _social_candidates(0, 1, 2)
    first = _build(social_post_candidates=posts, missing_optional=())
    permuted = _build(
        bundle_id="bundle-social-permuted",
        created_at="2042-01-01T00:00:00Z",
        social_post_candidates=tuple(reversed(posts)),
        missing_optional=(),
    )
    without_tied_post = _build(
        social_post_candidates=posts[:2],
        missing_optional=(),
    )

    assert tuple(post.post_id for post in first.social_posts) == (
        "reddit-aapl-thread",
        "reddit-aapl-tied",
    )
    assert first.bundle_hash == permuted.bundle_hash
    assert first.bundle_hash != without_tied_post.bundle_hash


def test_replay_denies_repository_subclasses_before_overridable_get_or_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class HostileRepository(EvidenceRepository):
        def get(self, bundle_id: str) -> EvidenceBundle:
            socket.socket()
            with builtins.open("ignored"):
                pass
            time.time()
            return super().get(bundle_id)

    repository = HostileRepository()
    bundle = repository.seal(_build())
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: calls.append("socket"))
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *_args, **_kwargs: calls.append("open") or nullcontext(),
    )
    monkeypatch.setattr(time, "time", lambda: calls.append("clock"))

    with pytest.raises(HistoricalReplayDeniedError, match="repository"):
        HistoricalDataGuard.replay(repository, bundle.bundle_id, _context(bundle))
    assert calls == []


@pytest.mark.parametrize("entrypoint", ["assert_network_denied", "replay"])
def test_historical_guard_denies_run_context_subclasses_before_model_dump_or_io(
    entrypoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class HostileRunContext(RunContext):
        def model_dump(self, *args: object, **kwargs: object) -> dict[str, object]:
            socket.socket()
            with builtins.open("ignored"):
                pass
            time.time()
            return super().model_dump(*args, **kwargs)

    repository = EvidenceRepository()
    bundle = repository.seal(_build())
    hostile = HostileRunContext.model_validate(
        _context(bundle).model_dump(mode="python")
    )
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: calls.append("socket"))
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *_args, **_kwargs: calls.append("open") or nullcontext(),
    )
    monkeypatch.setattr(time, "time", lambda: calls.append("clock"))

    with pytest.raises(HistoricalReplayDeniedError, match="RunContext"):
        if entrypoint == "assert_network_denied":
            HistoricalDataGuard.assert_network_denied(hostile)
        else:
            HistoricalDataGuard.replay(repository, bundle.bundle_id, hostile)
    assert calls == []


@pytest.mark.parametrize(
    ("requested_id", "context_id"),
    [
        ("bundle-requested-other", "bundle-2024-06-30"),
        ("bundle-2024-06-30", "bundle-context-other"),
    ],
)
def test_replay_rejects_requested_context_id_mismatch_before_repository_lookup(
    requested_id: str,
    context_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = EvidenceRepository()
    bundle = repository.seal(_build())

    def unexpected_get(_bundle_id: str) -> EvidenceBundle:
        raise AssertionError("repository lookup occurred before ID binding")

    monkeypatch.setattr(repository, "get", unexpected_get)
    with pytest.raises(HistoricalReplayMismatchError, match="ID"):
        HistoricalDataGuard.replay(
            repository,
            requested_id,
            _context(bundle, bundle_id=context_id),
        )


def test_serialized_nested_tamper_is_rejected_before_storage() -> None:
    serialized = _build().model_dump(mode="json")
    bars = serialized["bars"]
    assert isinstance(bars, list)
    bar = bars[0]
    assert isinstance(bar, dict)
    bar["close"] = "999.00"

    with pytest.raises(EvidenceBundleCorruptionError):
        EvidenceRepository().seal(serialized)  # type: ignore[arg-type]


def test_pit_06_modules_do_not_import_research_graph_or_offer_io_adapters() -> None:
    for module in (
        inspect.getmodule(build_evidence_bundle),
        inspect.getmodule(EvidenceRepository),
        inspect.getmodule(HistoricalDataGuard),
    ):
        assert module is not None
        source = inspect.getsource(module)
        assert "tradingagents" not in source
        assert "requests" not in source
        assert "httpx" not in source
        assert "urllib" not in source
        assert "subprocess" not in source

    assert not hasattr(EvidenceRepository, "delete")
    assert not hasattr(EvidenceRepository, "update")
    assert not hasattr(EvidenceRepository, "replace")
    assert not hasattr(HistoricalDataGuard, "capture")
    assert not hasattr(HistoricalDataGuard, "fetch")


def test_fixture_names_only_synthetic_inputs_and_no_live_credentials() -> None:
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "api_key" not in lowered
    assert "access_token" not in lowered
    assert "client_secret" not in lowered
    assert "broker" not in lowered
    assert "live_write" not in lowered
    assert "paper_write" not in lowered
    assert set(_fixture()["source_fixtures"]) == {
        "calendar",
        "universe_actions",
        "financial_vintages",
        "events_social_macro",
    }


def test_action_union_remains_exactly_the_existing_pit_05_types() -> None:
    assert {type(action) for action in _actions()} == {
        TickerChangeAction,
        SplitAction,
        DividendAction,
    }
    assert DelistingAction not in {type(action) for action in _actions()}

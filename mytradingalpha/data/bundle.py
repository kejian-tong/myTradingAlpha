"""Canonical point-in-time evidence selection and immutable bundle sealing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal, TypeVar

from pydantic import StrictBool, TypeAdapter, ValidationError, field_validator, model_validator

from mytradingalpha.contracts.common import StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .actions import CorporateAction, CorporateActionRepository
from .bars import BarRepository, DailyBar
from .calendar import TradingCalendar
from .events import EventRepository, NewsEvent, ReplayPolicy
from .fundamentals import FilingRepository, FinancialFiling
from .macro import MacroObservation, MacroRepository
from .provenance import CanonicalChecksum, SourceManifest
from .social import SocialPost, SocialRepository
from .universe import Instrument, SymbolAlias, UniverseManifest, UniverseMembership


class EvidenceBundleError(ValueError):
    """Base class for public evidence-bundle construction failures."""


class MissingRequiredEvidenceError(EvidenceBundleError):
    """Raised when a required domain has no cutoff-eligible evidence."""


class InvalidEvidenceError(EvidenceBundleError):
    """Raised when candidates or bundle policy cannot be validated safely."""


class EvidenceDomain(str, Enum):
    """Stable evidence-domain wire values."""

    CALENDAR = "calendar"
    INSTRUMENTS = "instruments"
    ALIASES = "aliases"
    MEMBERSHIPS = "memberships"
    ACTIONS = "actions"
    BARS = "bars"
    FILINGS = "filings"
    EVENTS = "events"
    SOCIAL = "social"
    MACRO = "macro"


class BundleReplayPolicy(str, Enum):
    """Cutoff policy applied while selecting a sealed bundle."""

    AVAILABILITY = "availability"
    ARCHIVE_REALISTIC = "archive_realistic"


class EvidenceRequirement(ContractModel):
    """Whether one evidence domain must be present in a bundle."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    domain: EvidenceDomain
    required: StrictBool


class MissingEvidence(ContractModel):
    """Explicit reason for one absent optional evidence domain."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    domain: EvidenceDomain
    reason: StableId


_Record = TypeVar(
    "_Record",
    Instrument,
    SymbolAlias,
    UniverseMembership,
    CorporateAction,
    DailyBar,
    FinancialFiling,
    NewsEvent,
    SocialPost,
    MacroObservation,
)


def _model_payload(value: object) -> object:
    if isinstance(value, ContractModel):
        return value.model_dump(mode="python")
    return value


def _revalidate_model(value: object, model: type[_Record], *, domain: str) -> _Record:
    manifest = getattr(value, "manifest", None)
    if (
        domain != "bars"
        and isinstance(manifest, SourceManifest)
        and (manifest.event_time is None or manifest.published_at is None)
    ):
        raise InvalidEvidenceError(f"undated_{domain}_evidence_is_not_replayable")
    try:
        return model.model_validate(_model_payload(value))
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError(f"invalid_{domain}_evidence") from exc


def _revalidate_action(value: object) -> CorporateAction:
    try:
        return TypeAdapter(CorporateAction).validate_python(_model_payload(value))
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_actions_evidence") from exc


def _revalidate_sequence(
    values: object,
    model: type[_Record],
    *,
    domain: str,
) -> tuple[_Record, ...]:
    if not isinstance(values, (tuple, list)):
        raise InvalidEvidenceError(f"invalid_{domain}_candidates: expected a sequence")
    return tuple(_revalidate_model(value, model, domain=domain) for value in values)


def _revalidate_actions(values: object) -> tuple[CorporateAction, ...]:
    if not isinstance(values, (tuple, list)):
        raise InvalidEvidenceError("invalid_actions_candidates: expected a sequence")
    return tuple(_revalidate_action(value) for value in values)


def _manifest(record: object) -> SourceManifest:
    manifest = getattr(record, "manifest", None)
    if not isinstance(manifest, SourceManifest):
        raise InvalidEvidenceError("evidence_manifest_required")
    return manifest


def _reject_non_historical_candidates(records: Sequence[object], *, domain: str) -> None:
    for record in records:
        replay_policy = getattr(record, "replay_policy", None)
        if replay_policy is ReplayPolicy.LIVE_NOW_ONLY:
            raise InvalidEvidenceError(f"live_only_{domain}_evidence_is_not_replayable")

        manifest = _manifest(record)
        if not isinstance(record, DailyBar) and (
            manifest.event_time is None or manifest.published_at is None
        ):
            raise InvalidEvidenceError(f"undated_{domain}_evidence_is_not_replayable")


def _eligible(
    record: object,
    cutoff: datetime,
    policy: BundleReplayPolicy,
) -> bool:
    manifest = _manifest(record)
    if manifest.available_at > cutoff:
        return False
    return not (
        policy is BundleReplayPolicy.ARCHIVE_REALISTIC
        and manifest.ingested_at > cutoff
    )


def _eligible_records(
    records: Sequence[_Record],
    cutoff: datetime,
    policy: BundleReplayPolicy,
) -> tuple[_Record, ...]:
    return tuple(record for record in records if _eligible(record, cutoff, policy))


def _select_revisions(
    records: Sequence[_Record],
    *,
    identity: Callable[[_Record], tuple[object, ...]],
    sort_key: Callable[[_Record], tuple[object, ...]],
    cutoff: datetime,
    policy: BundleReplayPolicy,
    domain: str,
) -> tuple[_Record, ...]:
    selected: dict[tuple[object, ...], _Record] = {}
    revisions: set[tuple[tuple[object, ...], int]] = set()
    for record in records:
        if not _eligible(record, cutoff, policy):
            continue
        key = identity(record)
        revision = _manifest(record).revision
        revision_key = (key, revision)
        if revision_key in revisions:
            raise InvalidEvidenceError(f"duplicate_{domain}_identity_revision")
        revisions.add(revision_key)
        current = selected.get(key)
        if current is None or revision > _manifest(current).revision:
            selected[key] = record
    return tuple(sorted(selected.values(), key=sort_key))


def _instrument_identity(record: Instrument) -> tuple[object, ...]:
    return (record.instrument_id, record.manifest.source)


def _instrument_sort_key(record: Instrument) -> tuple[object, ...]:
    return (
        record.instrument_id,
        record.manifest.source,
        record.manifest.revision,
        record.manifest.manifest_id,
    )


def _alias_identity(record: SymbolAlias) -> tuple[object, ...]:
    return (record.alias_id, record.manifest.source)


def _alias_sort_key(record: SymbolAlias) -> tuple[object, ...]:
    return (
        record.alias_id,
        record.instrument_id,
        record.symbol,
        record.valid_from.isoformat(),
        record.valid_to.isoformat() if record.valid_to is not None else "",
        record.manifest.source,
        record.manifest.revision,
        record.manifest.manifest_id,
    )


def _membership_identity(record: UniverseMembership) -> tuple[object, ...]:
    return (record.membership_id, record.manifest.source)


def _membership_sort_key(record: UniverseMembership) -> tuple[object, ...]:
    return (
        record.membership_id,
        record.universe_id,
        record.instrument_id,
        record.valid_from.isoformat(),
        record.valid_to.isoformat() if record.valid_to is not None else "",
        record.manifest.source,
        record.manifest.revision,
        record.manifest.manifest_id,
    )


def _action_identity(record: CorporateAction) -> tuple[object, ...]:
    return (record.action_id, record.manifest.source)


def _action_sort_key(record: CorporateAction) -> tuple[object, ...]:
    return (
        record.action_id,
        record.instrument_id,
        record.action_type.value,
        record.effective_date,
        record.manifest.source,
        record.manifest.revision,
        record.manifest.manifest_id,
    )


def _bar_identity(record: DailyBar) -> tuple[object, ...]:
    return (
        record.instrument_id,
        record.calendar_id,
        record.session_date,
        record.interval,
        record.adjustment_basis.value,
        record.adjustment_version,
        record.manifest.source,
    )


def _bar_sort_key(record: DailyBar) -> tuple[object, ...]:
    return (
        record.bar_id,
        record.instrument_id,
        record.calendar_id,
        record.session_date,
        record.interval,
        record.adjustment_basis.value,
        record.adjustment_version or "",
        record.manifest.source,
        record.manifest.revision,
        record.manifest.manifest_id,
    )


def _filing_identity(record: FinancialFiling) -> tuple[object, ...]:
    return (
        record.instrument_id,
        record.statement_type.value,
        record.reporting_period.value,
        record.form_type,
        record.fiscal_period_start,
        record.fiscal_period_end,
        record.currency,
        record.unit_scale.value,
        record.manifest.source,
    )


def _filing_sort_key(record: FinancialFiling) -> tuple[object, ...]:
    return (
        record.filing_id,
        record.accession_id,
        *_filing_identity(record),
        record.manifest.revision,
        record.manifest.manifest_id,
    )


def _event_identity(record: NewsEvent) -> tuple[object, ...]:
    return (record.event_id, record.manifest.source)


def _event_sort_key(record: NewsEvent) -> tuple[object, ...]:
    return (
        record.event_id,
        record.instrument_id or "",
        record.kind.value,
        record.manifest.event_time,
        record.manifest.source,
        record.manifest.revision,
        record.manifest.manifest_id,
    )


def _social_identity(record: SocialPost) -> tuple[object, ...]:
    return (record.post_id, record.manifest.source)


def _social_sort_key(record: SocialPost) -> tuple[object, ...]:
    return (
        record.post_id,
        record.instrument_id,
        record.platform.value,
        record.manifest.event_time,
        record.manifest.source,
        record.manifest.revision,
        record.manifest.manifest_id,
    )


def _macro_identity(record: MacroObservation) -> tuple[object, ...]:
    return (record.observation_id, record.manifest.source)


def _macro_sort_key(record: MacroObservation) -> tuple[object, ...]:
    return (
        record.observation_id,
        record.series_id,
        record.observation_date,
        record.units,
        record.frequency.value,
        record.manifest.source,
        record.manifest.revision,
        record.manifest.manifest_id,
    )


def _ensure_unique_selected(
    records: Sequence[_Record],
    *,
    identity: Callable[[_Record], tuple[object, ...]],
    domain: str,
) -> None:
    identities: set[tuple[object, ...]] = set()
    for record in records:
        key = identity(record)
        if key in identities:
            raise ValueError(f"multiple_selected_revisions_for_{domain}_identity")
        identities.add(key)


@dataclass(frozen=True)
class _ValidatedSelectedEvidence:
    instruments: tuple[Instrument, ...]
    aliases: tuple[SymbolAlias, ...]
    memberships: tuple[UniverseMembership, ...]
    actions: tuple[CorporateAction, ...]
    bars: tuple[DailyBar, ...]
    filings: tuple[FinancialFiling, ...]
    events: tuple[NewsEvent, ...]
    social_posts: tuple[SocialPost, ...]
    macro_observations: tuple[MacroObservation, ...]


def _validate_revision_histories(
    *,
    actions: Sequence[CorporateAction],
    filings: Sequence[FinancialFiling],
    events: Sequence[NewsEvent],
    social_posts: Sequence[SocialPost],
    macro_observations: Sequence[MacroObservation],
) -> tuple[
    tuple[CorporateAction, ...],
    tuple[FinancialFiling, ...],
    tuple[NewsEvent, ...],
    tuple[SocialPost, ...],
    tuple[MacroObservation, ...],
]:
    try:
        action_history = CorporateActionRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            actions=actions,
        ).actions
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_actions_aggregate") from exc
    try:
        filing_history = FilingRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            filings=filings,
        ).filings
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_filings_aggregate") from exc
    try:
        event_history = EventRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            events=events,
        ).events
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_events_aggregate") from exc
    try:
        social_history = SocialRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            posts=social_posts,
        ).posts
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_social_aggregate") from exc
    try:
        macro_history = MacroRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            observations=macro_observations,
        ).observations
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_macro_aggregate") from exc
    return (
        action_history,
        filing_history,
        event_history,
        social_history,
        macro_history,
    )


def _validate_selected_aggregates(
    *,
    calendar: TradingCalendar,
    instruments: Sequence[Instrument],
    aliases: Sequence[SymbolAlias],
    memberships: Sequence[UniverseMembership],
    actions: Sequence[CorporateAction],
    bars: Sequence[DailyBar],
    filings: Sequence[FinancialFiling],
    events: Sequence[NewsEvent],
    social_posts: Sequence[SocialPost],
    macro_observations: Sequence[MacroObservation],
) -> _ValidatedSelectedEvidence:
    try:
        universe = UniverseManifest(
            schema_version=CURRENT_SCHEMA_VERSION,
            instruments=instruments,
            aliases=aliases,
            memberships=memberships,
        )
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError(
            "invalid_aliases_memberships_universe_aggregate"
        ) from exc
    try:
        canonical_bars = BarRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            calendar=calendar,
            bars=bars,
        ).bars
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_bars_aggregate") from exc
    try:
        canonical_actions = CorporateActionRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            actions=actions,
        ).actions
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_actions_aggregate") from exc
    try:
        canonical_filings = FilingRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            filings=filings,
        ).filings
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_filings_aggregate") from exc
    try:
        canonical_events = EventRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            events=events,
        ).events
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_events_aggregate") from exc
    try:
        canonical_social = SocialRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            posts=social_posts,
        ).posts
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_social_aggregate") from exc
    try:
        canonical_macro = MacroRepository(
            schema_version=CURRENT_SCHEMA_VERSION,
            observations=macro_observations,
        ).observations
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_macro_aggregate") from exc

    instrument_ids = {instrument.instrument_id for instrument in universe.instruments}
    referenced_instruments = (
        *(action.instrument_id for action in canonical_actions),
        *(bar.instrument_id for bar in canonical_bars),
        *(filing.instrument_id for filing in canonical_filings),
        *(
            event.instrument_id
            for event in canonical_events
            if event.instrument_id is not None
        ),
        *(post.instrument_id for post in canonical_social),
    )
    unknown = sorted(set(referenced_instruments) - instrument_ids)
    if unknown:
        raise InvalidEvidenceError(
            f"unselected_instrument_reference: {unknown[0]}"
        )

    return _ValidatedSelectedEvidence(
        instruments=tuple(sorted(universe.instruments, key=_instrument_sort_key)),
        aliases=tuple(sorted(universe.aliases, key=_alias_sort_key)),
        memberships=tuple(sorted(universe.memberships, key=_membership_sort_key)),
        actions=tuple(sorted(canonical_actions, key=_action_sort_key)),
        bars=tuple(sorted(canonical_bars, key=_bar_sort_key)),
        filings=tuple(sorted(canonical_filings, key=_filing_sort_key)),
        events=tuple(sorted(canonical_events, key=_event_sort_key)),
        social_posts=tuple(sorted(canonical_social, key=_social_sort_key)),
        macro_observations=tuple(sorted(canonical_macro, key=_macro_sort_key)),
    )


def _requirements_by_domain(
    requirements: Sequence[EvidenceRequirement],
) -> dict[EvidenceDomain, EvidenceRequirement]:
    result: dict[EvidenceDomain, EvidenceRequirement] = {}
    for requirement in requirements:
        if requirement.domain in result:
            raise InvalidEvidenceError("duplicate_evidence_requirement")
        result[requirement.domain] = requirement
    if set(result) != set(EvidenceDomain):
        raise InvalidEvidenceError("incomplete_evidence_requirement_matrix")
    return result


def _presence(
    *,
    calendar: TradingCalendar,
    instruments: Sequence[Instrument],
    aliases: Sequence[SymbolAlias],
    memberships: Sequence[UniverseMembership],
    actions: Sequence[CorporateAction],
    bars: Sequence[DailyBar],
    filings: Sequence[FinancialFiling],
    events: Sequence[NewsEvent],
    social_posts: Sequence[SocialPost],
    macro_observations: Sequence[MacroObservation],
) -> dict[EvidenceDomain, bool]:
    return {
        EvidenceDomain.CALENDAR: calendar is not None,
        EvidenceDomain.INSTRUMENTS: bool(instruments),
        EvidenceDomain.ALIASES: bool(aliases),
        EvidenceDomain.MEMBERSHIPS: bool(memberships),
        EvidenceDomain.ACTIONS: bool(actions),
        EvidenceDomain.BARS: bool(bars),
        EvidenceDomain.FILINGS: bool(filings),
        EvidenceDomain.EVENTS: bool(events),
        EvidenceDomain.SOCIAL: bool(social_posts),
        EvidenceDomain.MACRO: bool(macro_observations),
    }


def _validate_missingness(
    requirements: Sequence[EvidenceRequirement],
    missing_optional: Sequence[MissingEvidence],
    present: dict[EvidenceDomain, bool],
    *,
    typed_missing_required: bool,
) -> None:
    by_domain = _requirements_by_domain(requirements)
    missing_by_domain: dict[EvidenceDomain, MissingEvidence] = {}
    for missing in missing_optional:
        if missing.domain in missing_by_domain:
            raise InvalidEvidenceError("duplicate_missing_optional_evidence")
        missing_by_domain[missing.domain] = missing

    for domain, requirement in by_domain.items():
        if requirement.required and not present[domain]:
            if typed_missing_required:
                raise MissingRequiredEvidenceError(
                    f"required evidence domain is missing: {domain.value}"
                )
            raise ValueError(f"required evidence domain is missing: {domain.value}")
        if requirement.required and domain in missing_by_domain:
            raise InvalidEvidenceError(
                f"required evidence cannot be marked optional-missing: {domain.value}"
            )
        if not requirement.required and present[domain] and domain in missing_by_domain:
            raise InvalidEvidenceError(
                f"present optional evidence cannot be marked missing: {domain.value}"
            )
        if not requirement.required and not present[domain] and domain not in missing_by_domain:
            raise InvalidEvidenceError(
                f"optional evidence absence requires a reason: {domain.value}"
            )

    unexpected = set(missing_by_domain) - {
        domain
        for domain, requirement in by_domain.items()
        if not requirement.required and not present[domain]
    }
    if unexpected:
        domain = sorted(item.value for item in unexpected)[0]
        raise InvalidEvidenceError(f"invalid missing-optional evidence: {domain}")


def _semantic_payload(
    *,
    schema_version: str,
    knowledge_cutoff: datetime,
    replay_policy: BundleReplayPolicy,
    requirements: Sequence[EvidenceRequirement],
    missing_optional: Sequence[MissingEvidence],
    calendar: TradingCalendar,
    instruments: Sequence[Instrument],
    aliases: Sequence[SymbolAlias],
    memberships: Sequence[UniverseMembership],
    actions: Sequence[CorporateAction],
    bars: Sequence[DailyBar],
    filings: Sequence[FinancialFiling],
    events: Sequence[NewsEvent],
    social_posts: Sequence[SocialPost],
    macro_observations: Sequence[MacroObservation],
) -> dict[str, object]:
    timestamp = TypeAdapter(UtcDateTime).dump_python(knowledge_cutoff, mode="json")
    return {
        "schema_version": schema_version,
        "knowledge_cutoff": timestamp,
        "replay_policy": replay_policy.value,
        "requirements": [item.model_dump(mode="json") for item in requirements],
        "missing_optional": [item.model_dump(mode="json") for item in missing_optional],
        "calendar": calendar.model_dump(mode="json"),
        "instruments": [item.model_dump(mode="json") for item in instruments],
        "aliases": [item.model_dump(mode="json") for item in aliases],
        "memberships": [item.model_dump(mode="json") for item in memberships],
        "actions": [item.model_dump(mode="json") for item in actions],
        "bars": [item.model_dump(mode="json") for item in bars],
        "filings": [item.model_dump(mode="json") for item in filings],
        "events": [item.model_dump(mode="json") for item in events],
        "social_posts": [item.model_dump(mode="json") for item in social_posts],
        "macro_observations": [
            item.model_dump(mode="json") for item in macro_observations
        ],
    }


def _semantic_hash(**components: object) -> str:
    payload = _semantic_payload(**components)  # type: ignore[arg-type]
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


class EvidenceBundle(ContractModel):
    """One immutable, canonical, content-addressed historical evidence bundle."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    bundle_id: StableId
    bundle_hash: CanonicalChecksum
    created_at: UtcDateTime
    knowledge_cutoff: UtcDateTime
    replay_policy: BundleReplayPolicy
    requirements: tuple[EvidenceRequirement, ...]
    missing_optional: tuple[MissingEvidence, ...]
    calendar: TradingCalendar
    instruments: tuple[Instrument, ...]
    aliases: tuple[SymbolAlias, ...]
    memberships: tuple[UniverseMembership, ...]
    actions: tuple[CorporateAction, ...]
    bars: tuple[DailyBar, ...]
    filings: tuple[FinancialFiling, ...]
    events: tuple[NewsEvent, ...]
    social_posts: tuple[SocialPost, ...]
    macro_observations: tuple[MacroObservation, ...]

    @field_validator("requirements", mode="before")
    @classmethod
    def revalidate_requirements(cls, value: object) -> tuple[EvidenceRequirement, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_requirements: expected a sequence")
        requirements = tuple(
            EvidenceRequirement.model_validate(_model_payload(item)) for item in value
        )
        return tuple(sorted(requirements, key=lambda item: item.domain.value))

    @field_validator("missing_optional", mode="before")
    @classmethod
    def revalidate_missing_optional(cls, value: object) -> tuple[MissingEvidence, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_missing_optional: expected a sequence")
        missing = tuple(MissingEvidence.model_validate(_model_payload(item)) for item in value)
        return tuple(sorted(missing, key=lambda item: item.domain.value))

    @field_validator("calendar", mode="before")
    @classmethod
    def revalidate_calendar(cls, value: object) -> TradingCalendar:
        return TradingCalendar.model_validate(_model_payload(value))

    @field_validator("instruments", mode="before")
    @classmethod
    def revalidate_instruments(cls, value: object) -> tuple[Instrument, ...]:
        return tuple(
            sorted(
                _revalidate_sequence(value, Instrument, domain="instruments"),
                key=_instrument_sort_key,
            )
        )

    @field_validator("aliases", mode="before")
    @classmethod
    def revalidate_aliases(cls, value: object) -> tuple[SymbolAlias, ...]:
        return tuple(
            sorted(
                _revalidate_sequence(value, SymbolAlias, domain="aliases"),
                key=_alias_sort_key,
            )
        )

    @field_validator("memberships", mode="before")
    @classmethod
    def revalidate_memberships(cls, value: object) -> tuple[UniverseMembership, ...]:
        return tuple(
            sorted(
                _revalidate_sequence(value, UniverseMembership, domain="memberships"),
                key=_membership_sort_key,
            )
        )

    @field_validator("actions", mode="before")
    @classmethod
    def revalidate_actions(cls, value: object) -> tuple[CorporateAction, ...]:
        return tuple(sorted(_revalidate_actions(value), key=_action_sort_key))

    @field_validator("bars", mode="before")
    @classmethod
    def revalidate_bars(cls, value: object) -> tuple[DailyBar, ...]:
        return tuple(
            sorted(
                _revalidate_sequence(value, DailyBar, domain="bars"),
                key=_bar_sort_key,
            )
        )

    @field_validator("filings", mode="before")
    @classmethod
    def revalidate_filings(cls, value: object) -> tuple[FinancialFiling, ...]:
        return tuple(
            sorted(
                _revalidate_sequence(value, FinancialFiling, domain="filings"),
                key=_filing_sort_key,
            )
        )

    @field_validator("events", mode="before")
    @classmethod
    def revalidate_events(cls, value: object) -> tuple[NewsEvent, ...]:
        return tuple(
            sorted(
                _revalidate_sequence(value, NewsEvent, domain="events"),
                key=_event_sort_key,
            )
        )

    @field_validator("social_posts", mode="before")
    @classmethod
    def revalidate_social_posts(cls, value: object) -> tuple[SocialPost, ...]:
        return tuple(
            sorted(
                _revalidate_sequence(value, SocialPost, domain="social"),
                key=_social_sort_key,
            )
        )

    @field_validator("macro_observations", mode="before")
    @classmethod
    def revalidate_macro_observations(cls, value: object) -> tuple[MacroObservation, ...]:
        return tuple(
            sorted(
                _revalidate_sequence(value, MacroObservation, domain="macro"),
                key=_macro_sort_key,
            )
        )

    @model_validator(mode="after")
    def validate_sealed_bundle(self) -> EvidenceBundle:
        for domain, records, identity in (
            ("instruments", self.instruments, _instrument_identity),
            ("aliases", self.aliases, _alias_identity),
            ("memberships", self.memberships, _membership_identity),
            ("actions", self.actions, _action_identity),
            ("bars", self.bars, _bar_identity),
            ("filings", self.filings, _filing_identity),
            ("events", self.events, _event_identity),
            ("social", self.social_posts, _social_identity),
            ("macro", self.macro_observations, _macro_identity),
        ):
            _ensure_unique_selected(records, identity=identity, domain=domain)

        for domain, records in (
            ("instruments", self.instruments),
            ("aliases", self.aliases),
            ("memberships", self.memberships),
            ("actions", self.actions),
            ("bars", self.bars),
            ("filings", self.filings),
            ("events", self.events),
            ("social", self.social_posts),
            ("macro", self.macro_observations),
        ):
            _reject_non_historical_candidates(records, domain=domain)
            if any(
                not _eligible(record, self.knowledge_cutoff, self.replay_policy)
                for record in records
            ):
                raise ValueError(f"ineligible_{domain}_evidence_in_sealed_bundle")

        validated = _validate_selected_aggregates(
            calendar=self.calendar,
            instruments=self.instruments,
            aliases=self.aliases,
            memberships=self.memberships,
            actions=self.actions,
            bars=self.bars,
            filings=self.filings,
            events=self.events,
            social_posts=self.social_posts,
            macro_observations=self.macro_observations,
        )
        if (
            validated.instruments != self.instruments
            or validated.aliases != self.aliases
            or validated.memberships != self.memberships
            or validated.actions != self.actions
            or validated.bars != self.bars
            or validated.filings != self.filings
            or validated.events != self.events
            or validated.social_posts != self.social_posts
            or validated.macro_observations != self.macro_observations
        ):
            raise ValueError("noncanonical_selected_evidence_order")

        present = _presence(
            calendar=self.calendar,
            instruments=self.instruments,
            aliases=self.aliases,
            memberships=self.memberships,
            actions=self.actions,
            bars=self.bars,
            filings=self.filings,
            events=self.events,
            social_posts=self.social_posts,
            macro_observations=self.macro_observations,
        )
        _validate_missingness(
            self.requirements,
            self.missing_optional,
            present,
            typed_missing_required=False,
        )
        expected_hash = _semantic_hash(
            schema_version=self.schema_version,
            knowledge_cutoff=self.knowledge_cutoff,
            replay_policy=self.replay_policy,
            requirements=self.requirements,
            missing_optional=self.missing_optional,
            calendar=self.calendar,
            instruments=self.instruments,
            aliases=self.aliases,
            memberships=self.memberships,
            actions=self.actions,
            bars=self.bars,
            filings=self.filings,
            events=self.events,
            social_posts=self.social_posts,
            macro_observations=self.macro_observations,
        )
        if self.bundle_hash != expected_hash:
            raise ValueError("bundle_hash_mismatch")
        return self


def build_evidence_bundle(
    schema_version: Literal[CURRENT_SCHEMA_VERSION],
    bundle_id: StableId,
    created_at: UtcDateTime,
    knowledge_cutoff: UtcDateTime,
    replay_policy: BundleReplayPolicy,
    requirements: Sequence[EvidenceRequirement],
    missing_optional: Sequence[MissingEvidence],
    calendar: TradingCalendar,
    instrument_candidates: Sequence[Instrument],
    alias_candidates: Sequence[SymbolAlias],
    membership_candidates: Sequence[UniverseMembership],
    action_candidates: Sequence[CorporateAction],
    bar_candidates: Sequence[DailyBar],
    filing_candidates: Sequence[FinancialFiling],
    event_candidates: Sequence[NewsEvent],
    social_post_candidates: Sequence[SocialPost],
    macro_observation_candidates: Sequence[MacroObservation],
) -> EvidenceBundle:
    """Validate, select, canonicalize, and seal one deterministic v1 bundle."""

    try:
        cutoff = TypeAdapter(UtcDateTime).validate_python(knowledge_cutoff)
        policy = TypeAdapter(BundleReplayPolicy).validate_python(replay_policy)
        validated_calendar = TradingCalendar.model_validate(_model_payload(calendar))
        validated_requirements = tuple(
            sorted(
                (
                    EvidenceRequirement.model_validate(_model_payload(item))
                    for item in requirements
                ),
                key=lambda item: item.domain.value,
            )
        )
        validated_missing = tuple(
            sorted(
                (MissingEvidence.model_validate(_model_payload(item)) for item in missing_optional),
                key=lambda item: item.domain.value,
            )
        )
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_bundle_metadata") from exc

    instruments = _revalidate_sequence(
        instrument_candidates, Instrument, domain="instruments"
    )
    aliases = _revalidate_sequence(alias_candidates, SymbolAlias, domain="aliases")
    memberships = _revalidate_sequence(
        membership_candidates, UniverseMembership, domain="memberships"
    )
    actions = _revalidate_actions(action_candidates)
    bars = _revalidate_sequence(bar_candidates, DailyBar, domain="bars")
    filings = _revalidate_sequence(
        filing_candidates, FinancialFiling, domain="filings"
    )
    events = _revalidate_sequence(event_candidates, NewsEvent, domain="events")
    social_posts = _revalidate_sequence(
        social_post_candidates, SocialPost, domain="social"
    )
    macro_observations = _revalidate_sequence(
        macro_observation_candidates, MacroObservation, domain="macro"
    )

    for domain, records in (
        ("instruments", instruments),
        ("aliases", aliases),
        ("memberships", memberships),
        ("actions", actions),
        ("bars", bars),
        ("filings", filings),
        ("events", events),
        ("social", social_posts),
        ("macro", macro_observations),
    ):
        _reject_non_historical_candidates(records, domain=domain)

    eligible_instruments = _eligible_records(instruments, cutoff, policy)
    eligible_aliases = _eligible_records(aliases, cutoff, policy)
    eligible_memberships = _eligible_records(memberships, cutoff, policy)
    eligible_actions = _eligible_records(actions, cutoff, policy)
    eligible_bars = _eligible_records(bars, cutoff, policy)
    eligible_filings = _eligible_records(filings, cutoff, policy)
    eligible_events = _eligible_records(events, cutoff, policy)
    eligible_social = _eligible_records(social_posts, cutoff, policy)
    eligible_macro = _eligible_records(macro_observations, cutoff, policy)
    (
        eligible_actions,
        eligible_filings,
        eligible_events,
        eligible_social,
        eligible_macro,
    ) = _validate_revision_histories(
        actions=eligible_actions,
        filings=eligible_filings,
        events=eligible_events,
        social_posts=eligible_social,
        macro_observations=eligible_macro,
    )

    selected_instruments = _select_revisions(
        eligible_instruments,
        identity=_instrument_identity,
        sort_key=_instrument_sort_key,
        cutoff=cutoff,
        policy=policy,
        domain="instruments",
    )
    selected_aliases = _select_revisions(
        eligible_aliases,
        identity=_alias_identity,
        sort_key=_alias_sort_key,
        cutoff=cutoff,
        policy=policy,
        domain="aliases",
    )
    selected_memberships = _select_revisions(
        eligible_memberships,
        identity=_membership_identity,
        sort_key=_membership_sort_key,
        cutoff=cutoff,
        policy=policy,
        domain="memberships",
    )
    selected_actions = _select_revisions(
        eligible_actions,
        identity=_action_identity,
        sort_key=_action_sort_key,
        cutoff=cutoff,
        policy=policy,
        domain="actions",
    )
    selected_bars = _select_revisions(
        eligible_bars,
        identity=_bar_identity,
        sort_key=_bar_sort_key,
        cutoff=cutoff,
        policy=policy,
        domain="bars",
    )
    selected_filings = _select_revisions(
        eligible_filings,
        identity=_filing_identity,
        sort_key=_filing_sort_key,
        cutoff=cutoff,
        policy=policy,
        domain="filings",
    )
    selected_events = _select_revisions(
        eligible_events,
        identity=_event_identity,
        sort_key=_event_sort_key,
        cutoff=cutoff,
        policy=policy,
        domain="events",
    )
    selected_social = _select_revisions(
        eligible_social,
        identity=_social_identity,
        sort_key=_social_sort_key,
        cutoff=cutoff,
        policy=policy,
        domain="social",
    )
    selected_macro = _select_revisions(
        eligible_macro,
        identity=_macro_identity,
        sort_key=_macro_sort_key,
        cutoff=cutoff,
        policy=policy,
        domain="macro",
    )

    validated_selected = _validate_selected_aggregates(
        calendar=validated_calendar,
        instruments=selected_instruments,
        aliases=selected_aliases,
        memberships=selected_memberships,
        actions=selected_actions,
        bars=selected_bars,
        filings=selected_filings,
        events=selected_events,
        social_posts=selected_social,
        macro_observations=selected_macro,
    )
    selected_instruments = validated_selected.instruments
    selected_aliases = validated_selected.aliases
    selected_memberships = validated_selected.memberships
    selected_actions = validated_selected.actions
    selected_bars = validated_selected.bars
    selected_filings = validated_selected.filings
    selected_events = validated_selected.events
    selected_social = validated_selected.social_posts
    selected_macro = validated_selected.macro_observations

    present = _presence(
        calendar=validated_calendar,
        instruments=selected_instruments,
        aliases=selected_aliases,
        memberships=selected_memberships,
        actions=selected_actions,
        bars=selected_bars,
        filings=selected_filings,
        events=selected_events,
        social_posts=selected_social,
        macro_observations=selected_macro,
    )
    _validate_missingness(
        validated_requirements,
        validated_missing,
        present,
        typed_missing_required=True,
    )

    bundle_hash = _semantic_hash(
        schema_version=schema_version,
        knowledge_cutoff=cutoff,
        replay_policy=policy,
        requirements=validated_requirements,
        missing_optional=validated_missing,
        calendar=validated_calendar,
        instruments=selected_instruments,
        aliases=selected_aliases,
        memberships=selected_memberships,
        actions=selected_actions,
        bars=selected_bars,
        filings=selected_filings,
        events=selected_events,
        social_posts=selected_social,
        macro_observations=selected_macro,
    )
    try:
        return EvidenceBundle(
            schema_version=schema_version,
            bundle_id=bundle_id,
            bundle_hash=bundle_hash,
            created_at=created_at,
            knowledge_cutoff=cutoff,
            replay_policy=policy,
            requirements=validated_requirements,
            missing_optional=validated_missing,
            calendar=validated_calendar,
            instruments=selected_instruments,
            aliases=selected_aliases,
            memberships=selected_memberships,
            actions=selected_actions,
            bars=selected_bars,
            filings=selected_filings,
            events=selected_events,
            social_posts=selected_social,
            macro_observations=selected_macro,
        )
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidEvidenceError("invalid_sealed_evidence_bundle") from exc


__all__ = [
    "BundleReplayPolicy",
    "EvidenceBundle",
    "EvidenceBundleError",
    "EvidenceDomain",
    "EvidenceRequirement",
    "InvalidEvidenceError",
    "MissingEvidence",
    "MissingRequiredEvidenceError",
    "build_evidence_bundle",
]

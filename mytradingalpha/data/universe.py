"""Immutable historical universe and symbol-identity contracts."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BeforeValidator,
    Field,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from mytradingalpha.contracts.common import StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .calendar import ExactDate
from .provenance import SourceManifest

_STABLE_ID_ADAPTER = TypeAdapter(StableId)
_EXACT_DATE_ADAPTER = TypeAdapter(ExactDate)
_UTC_DATETIME_ADAPTER = TypeAdapter(UtcDateTime)


def _validate_symbol(value: object) -> object:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("invalid_symbol: expected a non-empty trimmed symbol")
    try:
        _STABLE_ID_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise ValueError("invalid_symbol: expected a stable symbol") from exc
    return value


ExactSymbol = Annotated[StrictStr, BeforeValidator(_validate_symbol)]


class UniverseRepositoryError(ValueError):
    """Base class for public historical-universe query failures."""


class UniverseMissingError(UniverseRepositoryError):
    """Raised when no universe record matches every explicit selector."""


class UniverseFutureError(UniverseRepositoryError):
    """Raised when matching universe evidence is unavailable at the cutoff."""


class UniverseQueryError(UniverseRepositoryError):
    """Raised when a universe query contains an invalid selector."""


class UniverseConflictError(UniverseRepositoryError):
    """Raised when repository state is ambiguous or internally inconsistent."""


class AssetClass(str, Enum):
    """Stable asset classifications supported by the initial PIT allowlist."""

    EQUITY = "equity"
    ETF = "etf"


def _validate_half_open_interval(start: date, end: date | None, *, label: str) -> None:
    if end is not None and start >= end:
        raise ValueError(f"invalid_{label}: start must precede exclusive end")


def _date_in_interval(value: date, start: date, end: date | None) -> bool:
    return start <= value and (end is None or value < end)


def _intervals_overlap(
    left_start: date,
    left_end: date | None,
    right_start: date,
    right_end: date | None,
) -> bool:
    return (right_end is None or left_start < right_end) and (
        left_end is None or right_start < left_end
    )


def _interval_within(
    child_start: date,
    child_end: date | None,
    parent_start: date,
    parent_end: date | None,
) -> bool:
    if child_start < parent_start:
        return False
    if parent_end is None:
        return True
    return child_end is not None and child_end <= parent_end


def _revalidate_manifest(value: object) -> SourceManifest:
    return SourceManifest.model_validate(
        value.model_dump(mode="python") if isinstance(value, SourceManifest) else value
    )


class Instrument(ContractModel):
    """One immutable stable instrument identity and active interval."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    instrument_id: StableId
    initial_symbol: ExactSymbol
    asset_class: AssetClass
    currency: StableId
    exchange: StableId
    active_from: ExactDate
    active_to: ExactDate | None
    lot_size: StrictInt = Field(ge=1)
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return _revalidate_manifest(value)

    @model_validator(mode="after")
    def validate_instrument(self) -> Instrument:
        _validate_half_open_interval(
            self.active_from,
            self.active_to,
            label="instrument_interval",
        )
        return self


class SymbolAlias(ContractModel):
    """One date-valid symbol mapped to a stable instrument identity."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    alias_id: StableId
    instrument_id: StableId
    symbol: ExactSymbol
    valid_from: ExactDate
    valid_to: ExactDate | None
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return _revalidate_manifest(value)

    @model_validator(mode="after")
    def validate_alias(self) -> SymbolAlias:
        _validate_half_open_interval(self.valid_from, self.valid_to, label="alias_interval")
        return self


class UniverseMembership(ContractModel):
    """One date-valid membership in a named universe."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    membership_id: StableId
    universe_id: StableId
    instrument_id: StableId
    valid_from: ExactDate
    valid_to: ExactDate | None
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return _revalidate_manifest(value)

    @model_validator(mode="after")
    def validate_membership(self) -> UniverseMembership:
        _validate_half_open_interval(
            self.valid_from,
            self.valid_to,
            label="membership_interval",
        )
        return self


def _query_stable_id(value: object, *, field: str) -> str:
    try:
        return _STABLE_ID_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise UniverseQueryError(f"invalid_{field}: expected a stable identifier") from exc


def _query_symbol(value: object) -> str:
    try:
        return TypeAdapter(ExactSymbol).validate_python(value)
    except ValidationError as exc:
        raise UniverseQueryError("invalid_symbol: expected an exact stable symbol") from exc


def _query_date(value: object) -> date:
    try:
        return _EXACT_DATE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise UniverseQueryError("invalid_as_of: expected an exact ISO date") from exc


def _query_cutoff(value: object) -> datetime:
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise UniverseQueryError(
            "invalid_knowledge_cutoff: expected an aware ISO timestamp"
        ) from exc


class UniverseManifest(ContractModel):
    """Frozen, canonical historical universe, identity, and membership evidence."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    instruments: tuple[Instrument, ...]
    aliases: tuple[SymbolAlias, ...]
    memberships: tuple[UniverseMembership, ...]

    @field_validator("instruments", mode="before")
    @classmethod
    def revalidate_and_sort_instruments(cls, value: object) -> tuple[Instrument, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_instruments: expected an instrument sequence")
        instruments = tuple(
            Instrument.model_validate(
                item.model_dump(mode="python") if isinstance(item, Instrument) else item
            )
            for item in value
        )
        return tuple(sorted(instruments, key=lambda item: item.instrument_id))

    @field_validator("aliases", mode="before")
    @classmethod
    def revalidate_and_sort_aliases(cls, value: object) -> tuple[SymbolAlias, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_aliases: expected an alias sequence")
        aliases = tuple(
            SymbolAlias.model_validate(
                item.model_dump(mode="python") if isinstance(item, SymbolAlias) else item
            )
            for item in value
        )
        return tuple(sorted(aliases, key=lambda item: item.alias_id))

    @field_validator("memberships", mode="before")
    @classmethod
    def revalidate_and_sort_memberships(
        cls,
        value: object,
    ) -> tuple[UniverseMembership, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_memberships: expected a membership sequence")
        memberships = tuple(
            UniverseMembership.model_validate(
                item.model_dump(mode="python") if isinstance(item, UniverseMembership) else item
            )
            for item in value
        )
        return tuple(sorted(memberships, key=lambda item: item.membership_id))

    @model_validator(mode="after")
    def validate_manifest(self) -> UniverseManifest:
        instruments_by_id: dict[str, Instrument] = {}
        for instrument in self.instruments:
            if instrument.instrument_id in instruments_by_id:
                raise ValueError("duplicate_instrument_id")
            instruments_by_id[instrument.instrument_id] = instrument

        alias_ids: set[str] = set()
        aliases_by_instrument: dict[str, list[SymbolAlias]] = {}
        for alias in self.aliases:
            if alias.alias_id in alias_ids:
                raise ValueError("duplicate_alias_id")
            alias_ids.add(alias.alias_id)
            instrument = instruments_by_id.get(alias.instrument_id)
            if instrument is None:
                raise ValueError("orphan_symbol_alias")
            if not _interval_within(
                alias.valid_from,
                alias.valid_to,
                instrument.active_from,
                instrument.active_to,
            ):
                raise ValueError("alias_interval_outside_instrument_activity")
            aliases_by_instrument.setdefault(alias.instrument_id, []).append(alias)

        for aliases in aliases_by_instrument.values():
            ordered = sorted(aliases, key=lambda item: (item.valid_from, item.alias_id))
            for previous, current in zip(ordered, ordered[1:], strict=False):
                if _intervals_overlap(
                    previous.valid_from,
                    previous.valid_to,
                    current.valid_from,
                    current.valid_to,
                ):
                    raise ValueError("overlapping_symbol_alias_intervals")

        membership_ids: set[str] = set()
        memberships_by_key: dict[tuple[str, str], list[UniverseMembership]] = {}
        for membership in self.memberships:
            if membership.membership_id in membership_ids:
                raise ValueError("duplicate_membership_id")
            membership_ids.add(membership.membership_id)
            instrument = instruments_by_id.get(membership.instrument_id)
            if instrument is None:
                raise ValueError("orphan_universe_membership")
            if not _interval_within(
                membership.valid_from,
                membership.valid_to,
                instrument.active_from,
                instrument.active_to,
            ):
                raise ValueError("membership_interval_outside_instrument_activity")
            key = (membership.universe_id, membership.instrument_id)
            memberships_by_key.setdefault(key, []).append(membership)

        for memberships in memberships_by_key.values():
            ordered = sorted(
                memberships,
                key=lambda item: (item.valid_from, item.membership_id),
            )
            for previous, current in zip(ordered, ordered[1:], strict=False):
                if _intervals_overlap(
                    previous.valid_from,
                    previous.valid_to,
                    current.valid_from,
                    current.valid_to,
                ):
                    raise ValueError("overlapping_universe_membership_intervals")
        return self

    def members(
        self,
        as_of: date | str,
        *,
        knowledge_cutoff: datetime | str,
        source: str,
        universe_id: str,
    ) -> tuple[Instrument, ...]:
        """Return instruments active in ``universe_id`` on the exact date."""

        manifest = self._revalidate_for_query()
        return manifest._select_members(
            as_of,
            knowledge_cutoff=knowledge_cutoff,
            source=source,
            universe_id=universe_id,
        )

    def resolve_symbol(
        self,
        symbol: str,
        as_of: date | str,
        *,
        knowledge_cutoff: datetime | str,
        source: str,
    ) -> Instrument:
        """Resolve one date-valid alias to its stable instrument identity."""

        manifest = self._revalidate_for_query()
        return manifest._select_symbol(
            symbol,
            as_of,
            knowledge_cutoff=knowledge_cutoff,
            source=source,
        )

    def _revalidate_for_query(self) -> UniverseManifest:
        try:
            return type(self).model_validate(self.model_dump(mode="python"))
        except (TypeError, ValidationError, ValueError) as exc:
            raise UniverseConflictError(
                "invalid_repository_state: universe manifest validation failed"
            ) from exc

    def _select_members(
        self,
        as_of: object,
        *,
        knowledge_cutoff: object,
        source: object,
        universe_id: object,
    ) -> tuple[Instrument, ...]:
        query_date = _query_date(as_of)
        cutoff = _query_cutoff(knowledge_cutoff)
        source_id = _query_stable_id(source, field="source")
        query_universe = _query_stable_id(universe_id, field="universe_id")
        instruments_by_id = {item.instrument_id: item for item in self.instruments}

        matching = tuple(
            membership
            for membership in self.memberships
            if membership.universe_id == query_universe
            and membership.manifest.source == source_id
            and _date_in_interval(
                query_date,
                membership.valid_from,
                membership.valid_to,
            )
            and _date_in_interval(
                query_date,
                instruments_by_id[membership.instrument_id].active_from,
                instruments_by_id[membership.instrument_id].active_to,
            )
            and instruments_by_id[membership.instrument_id].manifest.source == source_id
        )
        if not matching:
            raise UniverseMissingError("no universe membership matches the exact query")

        eligible = tuple(
            membership
            for membership in matching
            if membership.manifest.available_at <= cutoff
            and instruments_by_id[membership.instrument_id].manifest.available_at <= cutoff
        )
        if not eligible:
            raise UniverseFutureError(
                "matching universe memberships exist but are unavailable at the cutoff"
            )
        return tuple(
            sorted(
                (instruments_by_id[item.instrument_id] for item in eligible),
                key=lambda instrument: instrument.instrument_id,
            )
        )

    def _select_symbol(
        self,
        symbol: object,
        as_of: object,
        *,
        knowledge_cutoff: object,
        source: object,
    ) -> Instrument:
        query_symbol = _query_symbol(symbol)
        query_date = _query_date(as_of)
        cutoff = _query_cutoff(knowledge_cutoff)
        source_id = _query_stable_id(source, field="source")
        instruments_by_id = {item.instrument_id: item for item in self.instruments}
        matching = tuple(
            alias
            for alias in self.aliases
            if alias.symbol == query_symbol
            and alias.manifest.source == source_id
            and _date_in_interval(query_date, alias.valid_from, alias.valid_to)
            and _date_in_interval(
                query_date,
                instruments_by_id[alias.instrument_id].active_from,
                instruments_by_id[alias.instrument_id].active_to,
            )
            and instruments_by_id[alias.instrument_id].manifest.source == source_id
        )
        if not matching:
            raise UniverseMissingError("no symbol alias matches the exact query")

        eligible = tuple(
            alias
            for alias in matching
            if alias.manifest.available_at <= cutoff
            and instruments_by_id[alias.instrument_id].manifest.available_at <= cutoff
        )
        if not eligible:
            raise UniverseFutureError(
                "matching symbol aliases exist but are unavailable at the cutoff"
            )
        if len(eligible) != 1:
            raise UniverseConflictError("multiple symbol aliases match the exact query")
        return instruments_by_id[eligible[0].instrument_id]


__all__ = [
    "AssetClass",
    "Instrument",
    "SymbolAlias",
    "UniverseConflictError",
    "UniverseFutureError",
    "UniverseManifest",
    "UniverseMembership",
    "UniverseMissingError",
    "UniverseQueryError",
    "UniverseRepositoryError",
]

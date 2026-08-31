"""Immutable corporate-action records and point-in-time state projection."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BeforeValidator,
    Field,
    StrictBool,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from mytradingalpha.contracts.common import DecimalString, StableId, UtcDateTime
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


def _validate_required_text(value: object) -> object:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("invalid_text: expected a non-empty trimmed string")
    return value


ExactSymbol = Annotated[StrictStr, BeforeValidator(_validate_symbol)]
RequiredText = Annotated[StrictStr, BeforeValidator(_validate_required_text)]


class CorporateActionRepositoryError(ValueError):
    """Base class for public corporate-action query failures."""


class CorporateActionMissingError(CorporateActionRepositoryError):
    """Raised when an instrument has no action series in the repository."""


class CorporateActionFutureError(CorporateActionRepositoryError):
    """Raised when every effective action is unavailable at the cutoff."""


class CorporateActionQueryError(CorporateActionRepositoryError):
    """Raised when an action query contains an invalid selector."""


class CorporateActionConflictError(CorporateActionRepositoryError):
    """Raised when action history cannot produce one deterministic projection."""


class ActionType(str, Enum):
    """Stable supported corporate-action wire values."""

    TICKER_CHANGE = "ticker_change"
    SPLIT = "split"
    DIVIDEND = "dividend"
    DELISTING = "delisting"


def _revalidate_manifest(value: object) -> SourceManifest:
    return SourceManifest.model_validate(
        value.model_dump(mode="python") if isinstance(value, SourceManifest) else value
    )


def _validate_action_manifest(
    manifest: SourceManifest,
    effective_date: date,
    *,
    label: str,
) -> None:
    if manifest.event_time is None:
        raise ValueError(f"{label}_event_time_required")
    if manifest.event_time.date() != effective_date:
        raise ValueError(f"{label}_event_date_must_equal_effective_date")
    if manifest.published_at is None:
        raise ValueError(f"{label}_publication_required")


class TickerChangeAction(ContractModel):
    """One immutable stable-symbol transition."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    action_type: Literal[ActionType.TICKER_CHANGE]
    action_id: StableId
    instrument_id: StableId
    effective_date: ExactDate
    old_symbol: ExactSymbol
    new_symbol: ExactSymbol
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return _revalidate_manifest(value)

    @model_validator(mode="after")
    def validate_action(self) -> TickerChangeAction:
        if self.old_symbol == self.new_symbol:
            raise ValueError("ticker_change_symbols_must_differ")
        _validate_action_manifest(
            self.manifest,
            self.effective_date,
            label="ticker_change",
        )
        return self


class SplitAction(ContractModel):
    """One immutable exact share-ratio event, without position accounting."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    action_type: Literal[ActionType.SPLIT]
    action_id: StableId
    instrument_id: StableId
    effective_date: ExactDate
    new_shares_per_old_share: DecimalString
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return _revalidate_manifest(value)

    @model_validator(mode="after")
    def validate_action(self) -> SplitAction:
        if self.new_shares_per_old_share <= Decimal(0):
            raise ValueError("split_ratio_must_be_positive")
        _validate_action_manifest(self.manifest, self.effective_date, label="split")
        return self


class DividendAction(ContractModel):
    """One immutable exact dividend declaration, without cash accounting."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    action_type: Literal[ActionType.DIVIDEND]
    action_id: StableId
    instrument_id: StableId
    effective_date: ExactDate
    amount_per_share: DecimalString
    currency: StableId
    payable_date: ExactDate
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return _revalidate_manifest(value)

    @model_validator(mode="after")
    def validate_action(self) -> DividendAction:
        if self.amount_per_share <= Decimal(0):
            raise ValueError("dividend_amount_must_be_positive")
        if self.payable_date < self.effective_date:
            raise ValueError("dividend_payable_date_precedes_effective_date")
        _validate_action_manifest(self.manifest, self.effective_date, label="dividend")
        return self


class DelistingAction(ContractModel):
    """One immutable delisting state event, without settlement policy."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    action_type: Literal[ActionType.DELISTING]
    action_id: StableId
    instrument_id: StableId
    effective_date: ExactDate
    reason: RequiredText
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return _revalidate_manifest(value)

    @model_validator(mode="after")
    def validate_action(self) -> DelistingAction:
        _validate_action_manifest(self.manifest, self.effective_date, label="delisting")
        return self


CorporateAction = Annotated[
    TickerChangeAction | SplitAction | DividendAction | DelistingAction,
    Field(discriminator="action_type"),
]


def _action_sort_key(action: CorporateAction) -> tuple[object, ...]:
    return (action.effective_date, action.action_id, action.manifest.revision)


def _action_series_key(action: CorporateAction) -> tuple[object, ...]:
    return (
        action.action_id,
        action.instrument_id,
        action.action_type,
        action.effective_date,
        action.manifest.source,
    )


def _query_stable_id(value: object, *, field: str) -> str:
    try:
        return _STABLE_ID_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise CorporateActionQueryError(f"invalid_{field}: expected a stable identifier") from exc


def _query_symbol(value: object) -> str:
    try:
        return TypeAdapter(ExactSymbol).validate_python(value)
    except ValidationError as exc:
        raise CorporateActionQueryError(
            "invalid_initial_symbol: expected an exact stable symbol"
        ) from exc


def _query_date(value: object) -> date:
    try:
        return _EXACT_DATE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise CorporateActionQueryError("invalid_as_of: expected an exact ISO date") from exc


def _query_cutoff(value: object) -> datetime:
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise CorporateActionQueryError(
            "invalid_knowledge_cutoff: expected an aware ISO timestamp"
        ) from exc


class ActionProjection(ContractModel):
    """Identity-only state after replaying selected corporate-action evidence."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    instrument_id: StableId
    as_of: ExactDate
    symbol: ExactSymbol
    active: StrictBool
    actions: tuple[CorporateAction, ...]

    @field_validator("actions", mode="before")
    @classmethod
    def revalidate_actions(cls, value: object) -> tuple[CorporateAction, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_actions: expected an action sequence")
        adapter = TypeAdapter(CorporateAction)
        actions = tuple(
            adapter.validate_python(
                item.model_dump(mode="python")
                if isinstance(
                    item,
                    (TickerChangeAction, SplitAction, DividendAction, DelistingAction),
                )
                else item
            )
            for item in value
        )
        return tuple(sorted(actions, key=_action_sort_key))


class CorporateActionRepository(ContractModel):
    """Frozen, canonical action revision series with PIT projection."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    actions: tuple[CorporateAction, ...]

    @field_validator("actions", mode="before")
    @classmethod
    def revalidate_and_sort_actions(cls, value: object) -> tuple[CorporateAction, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_actions: expected an action sequence")
        adapter = TypeAdapter(CorporateAction)
        actions = tuple(
            adapter.validate_python(
                item.model_dump(mode="python")
                if isinstance(
                    item,
                    (TickerChangeAction, SplitAction, DividendAction, DelistingAction),
                )
                else item
            )
            for item in value
        )
        return tuple(sorted(actions, key=_action_sort_key))

    @model_validator(mode="after")
    def validate_repository(self) -> CorporateActionRepository:
        business_revisions: set[tuple[str, int]] = set()
        by_action_id: dict[str, list[CorporateAction]] = {}
        for action in self.actions:
            business_revision = (action.action_id, action.manifest.revision)
            if business_revision in business_revisions:
                raise ValueError("duplicate_action_id_revision")
            business_revisions.add(business_revision)
            by_action_id.setdefault(action.action_id, []).append(action)

        for series in by_action_id.values():
            ordered = sorted(series, key=lambda item: item.manifest.revision)
            first_key = _action_series_key(ordered[0])
            previous: CorporateAction | None = None
            for action in ordered:
                if _action_series_key(action) != first_key:
                    raise ValueError("action_revision_series_mismatch")
                if previous is not None and (
                    action.manifest.published_at < previous.manifest.published_at
                    or action.manifest.available_at < previous.manifest.available_at
                ):
                    raise ValueError("action_revision_chronology_regressed")
                previous = action
        return self

    def apply(
        self,
        instrument_id: str,
        as_of: date | str,
        *,
        knowledge_cutoff: datetime | str,
        source: str,
        initial_symbol: str,
    ) -> ActionProjection:
        """Project symbol/activity state from actions known by the cutoff."""

        repository = self._revalidate_for_query()
        return repository._apply(
            instrument_id,
            as_of,
            knowledge_cutoff=knowledge_cutoff,
            source=source,
            initial_symbol=initial_symbol,
        )

    def _revalidate_for_query(self) -> CorporateActionRepository:
        try:
            return type(self).model_validate(self.model_dump(mode="python"))
        except (TypeError, ValidationError, ValueError) as exc:
            raise CorporateActionConflictError(
                "invalid_repository_state: corporate-action validation failed"
            ) from exc

    def _apply(
        self,
        instrument_id: object,
        as_of: object,
        *,
        knowledge_cutoff: object,
        source: object,
        initial_symbol: object,
    ) -> ActionProjection:
        instrument = _query_stable_id(instrument_id, field="instrument_id")
        query_date = _query_date(as_of)
        cutoff = _query_cutoff(knowledge_cutoff)
        source_id = _query_stable_id(source, field="source")
        symbol = _query_symbol(initial_symbol)

        instrument_actions = tuple(
            action
            for action in self.actions
            if action.instrument_id == instrument and action.manifest.source == source_id
        )
        if not instrument_actions:
            raise CorporateActionMissingError(
                "no corporate actions match the instrument and source"
            )

        effective = tuple(
            action for action in instrument_actions if action.effective_date <= query_date
        )
        eligible = tuple(action for action in effective if action.manifest.available_at <= cutoff)
        if effective and not eligible:
            raise CorporateActionFutureError(
                "effective actions exist but none is available by the cutoff"
            )

        selected_by_id: dict[str, CorporateAction] = {}
        for action in eligible:
            selected = selected_by_id.get(action.action_id)
            if selected is None or action.manifest.revision > selected.manifest.revision:
                selected_by_id[action.action_id] = action
        selected_actions = tuple(sorted(selected_by_id.values(), key=_action_sort_key))

        active = True
        for action in selected_actions:
            if isinstance(action, TickerChangeAction):
                if action.old_symbol != symbol:
                    raise CorporateActionConflictError(
                        "ticker-change history does not continue from the projected symbol"
                    )
                symbol = action.new_symbol
            elif isinstance(action, DelistingAction):
                active = False

        return ActionProjection(
            schema_version=CURRENT_SCHEMA_VERSION,
            instrument_id=instrument,
            as_of=query_date,
            symbol=symbol,
            active=active,
            actions=selected_actions,
        )


__all__ = [
    "ActionProjection",
    "ActionType",
    "CorporateActionConflictError",
    "CorporateActionFutureError",
    "CorporateActionMissingError",
    "CorporateActionQueryError",
    "CorporateActionRepository",
    "CorporateActionRepositoryError",
    "DelistingAction",
    "DividendAction",
    "SplitAction",
    "TickerChangeAction",
]

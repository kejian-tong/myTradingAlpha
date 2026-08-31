"""Immutable financial filing contracts and point-in-time repository selection."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import TypeAdapter, ValidationError, field_validator, model_validator

from mytradingalpha.contracts.common import DecimalString, StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .calendar import ExactDate
from .provenance import SourceManifest
from .vintages import VintageConflictError, VintageFutureError, VintageSelector

_STABLE_ID_ADAPTER = TypeAdapter(StableId)
_EXACT_DATE_ADAPTER = TypeAdapter(ExactDate)
_UTC_DATETIME_ADAPTER = TypeAdapter(UtcDateTime)


class FilingRepositoryError(ValueError):
    """Base class for public financial filing query failures."""


class FilingMissingError(FilingRepositoryError):
    """Raised when no filing series matches every explicit selector."""


class FilingFutureError(FilingRepositoryError):
    """Raised when an exact filing series has only future revisions."""


class FilingQueryError(FilingRepositoryError):
    """Raised when a filing query contains an invalid selector."""


class StatementType(str, Enum):
    """Stable financial statement classification wire values."""

    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"


class ReportingPeriod(str, Enum):
    """Stable financial reporting cadence wire values."""

    ANNUAL = "annual"
    QUARTERLY = "quarterly"


class UnitScale(str, Enum):
    """Stable scale applied uniformly to a filing's facts."""

    UNITS = "units"
    THOUSANDS = "thousands"
    MILLIONS = "millions"


class FinancialFact(ContractModel):
    """One exact, named financial value in a normalized filing."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    name: StableId
    value: DecimalString


class FinancialFiling(ContractModel):
    """One immutable filing revision bound to complete capture provenance."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    filing_id: StableId
    accession_id: StableId
    instrument_id: StableId
    statement_type: StatementType
    reporting_period: ReportingPeriod
    form_type: StableId
    fiscal_period_start: ExactDate
    fiscal_period_end: ExactDate
    filed_at: UtcDateTime
    currency: StableId
    unit_scale: UnitScale
    facts: tuple[FinancialFact, ...]
    manifest: SourceManifest

    @field_validator("facts", mode="before")
    @classmethod
    def revalidate_and_sort_facts(cls, value: object) -> tuple[FinancialFact, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_facts: expected a fact sequence")
        facts = tuple(
            FinancialFact.model_validate(
                item.model_dump() if isinstance(item, FinancialFact) else item
            )
            for item in value
        )
        if not facts:
            raise ValueError("invalid_facts: at least one financial fact is required")
        names: set[str] = set()
        for fact in facts:
            if fact.name in names:
                raise ValueError("duplicate_financial_fact_name")
            names.add(fact.name)
        return tuple(sorted(facts, key=lambda fact: fact.name))

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return SourceManifest.model_validate(
            value.model_dump() if isinstance(value, SourceManifest) else value
        )

    @model_validator(mode="after")
    def validate_filing(self) -> FinancialFiling:
        if self.fiscal_period_start > self.fiscal_period_end:
            raise ValueError("invalid_fiscal_period: start must not exceed end")
        if self.manifest.published_at is None:
            raise ValueError("filing_publication_required")
        if self.manifest.published_at != self.filed_at:
            raise ValueError("filing_publication_must_equal_filed_at")
        if self.manifest.available_at < self.filed_at:
            raise ValueError("filing_available_before_filed_at")
        if self.manifest.event_time is None:
            raise ValueError("filing_event_time_required")
        if self.manifest.event_time.date() != self.fiscal_period_end:
            raise ValueError("filing_event_time_must_match_fiscal_period_end")
        if self.manifest.event_time >= self.filed_at:
            raise ValueError("filing_event_time_must_be_before_filed_at")
        return self

    @property
    def vintage_key(self) -> tuple[object, ...]:
        """Return the complete explicit identity of this filing revision series."""

        return (
            self.instrument_id,
            self.fiscal_period_start,
            self.fiscal_period_end,
            self.manifest.source,
            self.statement_type,
            self.reporting_period,
            self.form_type,
            self.currency,
            self.unit_scale,
        )


def _filing_sort_key(filing: FinancialFiling) -> tuple[object, ...]:
    return (*filing.vintage_key, filing.manifest.revision, filing.filing_id)


def _business_revision_key(filing: FinancialFiling) -> tuple[object, ...]:
    return (*filing.vintage_key, filing.manifest.revision)


def _query_stable_id(value: object, *, field: str) -> str:
    try:
        return _STABLE_ID_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise FilingQueryError(f"invalid_{field}: expected a stable identifier") from exc


def _query_date(value: object, *, field: str) -> date:
    try:
        return _EXACT_DATE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise FilingQueryError(f"invalid_{field}: expected an exact ISO date") from exc


def _query_cutoff(value: object) -> datetime:
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise FilingQueryError("invalid_knowledge_cutoff: expected an aware ISO timestamp") from exc


def _query_enum(value: object, enum_type: type[Enum], *, field: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            raise FilingQueryError(f"invalid_{field}") from exc
    raise FilingQueryError(f"invalid_{field}")


class FilingRepository(ContractModel):
    """A frozen, deterministically ordered collection of financial filings."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    filings: tuple[FinancialFiling, ...]

    @field_validator("filings", mode="before")
    @classmethod
    def revalidate_and_sort_filings(cls, value: object) -> tuple[FinancialFiling, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_filings: expected a filing sequence")
        filings = tuple(
            FinancialFiling.model_validate(
                item.model_dump() if isinstance(item, FinancialFiling) else item
            )
            for item in value
        )
        return tuple(sorted(filings, key=_filing_sort_key))

    @model_validator(mode="after")
    def validate_repository(self) -> FilingRepository:
        filing_ids: set[str] = set()
        business_revision_keys: set[tuple[object, ...]] = set()
        by_vintage: dict[tuple[object, ...], list[FinancialFiling]] = {}
        for filing in self.filings:
            if filing.filing_id in filing_ids:
                raise ValueError("duplicate_filing_id")
            filing_ids.add(filing.filing_id)

            business_revision_key = _business_revision_key(filing)
            if business_revision_key in business_revision_keys:
                raise ValueError("duplicate_filing_business_key")
            business_revision_keys.add(business_revision_key)
            by_vintage.setdefault(filing.vintage_key, []).append(filing)

        for series in by_vintage.values():
            ordered = sorted(series, key=lambda filing: filing.manifest.revision)
            previous: FinancialFiling | None = None
            for filing in ordered:
                if previous is not None and (
                    filing.filed_at < previous.filed_at
                    or filing.manifest.available_at < previous.manifest.available_at
                ):
                    raise ValueError(
                        "revision_chronology: higher revisions cannot regress filing or availability"
                    )
                previous = filing
        return self

    def as_of(
        self,
        instrument_id: str,
        fiscal_period_start: date | str,
        fiscal_period_end: date | str,
        *,
        knowledge_cutoff: datetime | str,
        source: str,
        statement_type: StatementType | str,
        reporting_period: ReportingPeriod | str,
        form_type: str,
        currency: str,
        unit_scale: UnitScale | str,
    ) -> FinancialFiling:
        """Select the highest revision in one exact filing series by cutoff."""

        repository = self._revalidate_for_query()
        return repository._select_as_of(
            instrument_id,
            fiscal_period_start,
            fiscal_period_end,
            knowledge_cutoff=knowledge_cutoff,
            source=source,
            statement_type=statement_type,
            reporting_period=reporting_period,
            form_type=form_type,
            currency=currency,
            unit_scale=unit_scale,
        )

    def _revalidate_for_query(self) -> FilingRepository:
        try:
            return type(self).model_validate(self.model_dump(mode="python"))
        except (TypeError, ValidationError, ValueError) as exc:
            raise FilingQueryError(
                "invalid_repository_state: filing repository validation failed"
            ) from exc

    def _select_as_of(
        self,
        instrument_id: str,
        fiscal_period_start: date | str,
        fiscal_period_end: date | str,
        *,
        knowledge_cutoff: datetime | str,
        source: str,
        statement_type: StatementType | str,
        reporting_period: ReportingPeriod | str,
        form_type: str,
        currency: str,
        unit_scale: UnitScale | str,
    ) -> FinancialFiling:
        """Select from an already revalidated and canonical repository."""

        instrument = _query_stable_id(instrument_id, field="instrument_id")
        period_start = _query_date(fiscal_period_start, field="fiscal_period_start")
        period_end = _query_date(fiscal_period_end, field="fiscal_period_end")
        cutoff = _query_cutoff(knowledge_cutoff)
        source_id = _query_stable_id(source, field="source")
        statement = _query_enum(statement_type, StatementType, field="statement_type")
        period = _query_enum(reporting_period, ReportingPeriod, field="reporting_period")
        form = _query_stable_id(form_type, field="form_type")
        currency_id = _query_stable_id(currency, field="currency")
        scale = _query_enum(unit_scale, UnitScale, field="unit_scale")

        matching = tuple(
            filing
            for filing in self.filings
            if filing.instrument_id == instrument
            and filing.fiscal_period_start == period_start
            and filing.fiscal_period_end == period_end
            and filing.manifest.source == source_id
            and filing.statement_type is statement
            and filing.reporting_period is period
            and filing.form_type == form
            and filing.currency == currency_id
            and filing.unit_scale is scale
        )
        if not matching:
            raise FilingMissingError("no filing matches every explicit selector")

        try:
            return VintageSelector().select(matching, knowledge_cutoff=cutoff)
        except VintageFutureError as exc:
            raise FilingFutureError(
                "matching filing revisions exist but none is available by the cutoff"
            ) from exc
        except VintageConflictError as exc:
            raise FilingQueryError(
                "invalid_repository_state: filing vintage selection conflicted"
            ) from exc


__all__ = [
    "FilingFutureError",
    "FilingMissingError",
    "FilingQueryError",
    "FilingRepository",
    "FilingRepositoryError",
    "FinancialFact",
    "FinancialFiling",
    "ReportingPeriod",
    "StatementType",
    "UnitScale",
]

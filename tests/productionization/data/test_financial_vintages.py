"""PIT-03 contract tests for financial filing availability and vintages."""

from __future__ import annotations

import inspect
import json
import socket
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import mytradingalpha.data.fundamentals as fundamentals_module
import pytest
from mytradingalpha.data.fundamentals import (
    FilingFutureError,
    FilingMissingError,
    FilingQueryError,
    FilingRepository,
    FilingRepositoryError,
    FinancialFact,
    FinancialFiling,
    ReportingPeriod,
    StatementType,
    UnitScale,
)
from mytradingalpha.data.vintages import (
    VintageConflictError,
    VintageFutureError,
    VintageMissingError,
    VintageSelectionError,
    VintageSelector,
)
from pydantic import ValidationError

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "pit" / "financial_vintages_v1.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _filing_payload(index: int = 0) -> dict[str, object]:
    fixture = _fixture()
    filings = fixture["filings"]
    assert isinstance(filings, list)
    payload = deepcopy(filings[index])
    assert isinstance(payload, dict)
    return payload


def _filing(
    index: int = 0,
    *,
    overrides: dict[str, object] | None = None,
    manifest_overrides: dict[str, object] | None = None,
    facts: list[dict[str, object]] | None = None,
) -> FinancialFiling:
    payload = _filing_payload(index)
    if overrides:
        payload.update(overrides)
    if facts is not None:
        payload["facts"] = facts
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    if manifest_overrides:
        manifest.update(manifest_overrides)
    return FinancialFiling.model_validate(payload)


def _repository(*filings: FinancialFiling) -> FilingRepository:
    return FilingRepository(schema_version="v1", filings=filings)


def _query(
    repository: FilingRepository,
    *,
    knowledge_cutoff: object = "2024-03-01T14:10:00Z",
    **overrides: object,
) -> FinancialFiling:
    selectors: dict[str, object] = {
        "instrument_id": "AAPL",
        "fiscal_period_end": "2023-12-31",
        "knowledge_cutoff": knowledge_cutoff,
        "source": "synthetic-sec",
        "statement_type": StatementType.BALANCE_SHEET,
        "reporting_period": ReportingPeriod.ANNUAL,
        "form_type": "10-K",
        "currency": "USD",
        "unit_scale": UnitScale.MILLIONS,
    }
    selectors.update(overrides)
    return repository.as_of(**selectors)  # type: ignore[arg-type]


def _retimed_filing(
    index: int,
    *,
    filed_at: str,
    available_at: str,
    fetched_at: str,
    ingested_at: str,
    revision: int,
    filing_id: str,
    accession_id: str,
) -> FinancialFiling:
    return _filing(
        index,
        overrides={
            "filing_id": filing_id,
            "accession_id": accession_id,
            "filed_at": filed_at,
        },
        manifest_overrides={
            "manifest_id": f"{filing_id}-capture",
            "source_locator": f"fixture://sec/AAPL/2023/10-K/{filing_id}",
            "published_at": filed_at,
            "available_at": available_at,
            "fetched_at": fetched_at,
            "ingested_at": ingested_at,
            "revision": revision,
        },
    )


def test_financial_enums_have_stable_wire_values() -> None:
    assert {item.value for item in StatementType} == {
        "balance_sheet",
        "income_statement",
        "cash_flow",
    }
    assert {item.value for item in ReportingPeriod} == {"annual", "quarterly"}
    assert {item.value for item in UnitScale} == {"units", "thousands", "millions"}


def test_financial_contracts_expose_only_the_v1_fields() -> None:
    assert set(FinancialFact.model_fields) == {"schema_version", "name", "value"}
    assert set(FinancialFiling.model_fields) == {
        "schema_version",
        "filing_id",
        "accession_id",
        "instrument_id",
        "statement_type",
        "reporting_period",
        "form_type",
        "fiscal_period_start",
        "fiscal_period_end",
        "filed_at",
        "currency",
        "unit_scale",
        "facts",
        "manifest",
    }
    assert set(FilingRepository.model_fields) == {"schema_version", "filings"}


def test_fixture_round_trips_exact_fields_facts_and_decimal_strings() -> None:
    filing = _filing()

    assert filing.schema_version == "v1"
    assert filing.filing_id == "AAPL-2023-10K-r0"
    assert filing.accession_id == "0000320193-24-000001"
    assert filing.instrument_id == "AAPL"
    assert filing.statement_type is StatementType.BALANCE_SHEET
    assert filing.reporting_period is ReportingPeriod.ANNUAL
    assert filing.form_type == "10-K"
    assert filing.fiscal_period_start == date(2023, 1, 1)
    assert filing.fiscal_period_end == date(2023, 12, 31)
    assert filing.filed_at == datetime(2024, 2, 15, 13, 0, tzinfo=timezone.utc)
    assert filing.currency == "USD"
    assert filing.unit_scale is UnitScale.MILLIONS
    assert tuple(fact.name for fact in filing.facts) == (
        "assets",
        "discontinued_operations",
        "liabilities",
    )
    assert tuple(fact.value for fact in filing.facts) == (
        Decimal("352583.000"),
        Decimal("12.500"),
        Decimal("290437.000"),
    )
    assert filing.model_dump(mode="json")["facts"][0]["value"] == "352583.000"
    assert FinancialFiling.model_validate_json(filing.model_dump_json()) == filing


def test_filings_facts_manifests_and_repository_are_deeply_frozen() -> None:
    filing = _filing()
    repository = _repository(filing)

    with pytest.raises(ValidationError):
        filing.currency = "EUR"
    with pytest.raises(ValidationError):
        filing.facts[0].value = Decimal("0")
    with pytest.raises(ValidationError):
        filing.manifest.source = "other"
    with pytest.raises(ValidationError):
        repository.filings = ()


def test_contracts_forbid_extra_fields_and_require_exact_v1_schema() -> None:
    fact = _filing().facts[0]
    filing_payload = _filing_payload()

    with pytest.raises(ValidationError):
        FinancialFact.model_validate({**fact.model_dump(), "unit": "USD"})
    with pytest.raises(ValidationError):
        FinancialFiling.model_validate({**filing_payload, "provider_payload": {}})
    with pytest.raises(ValidationError):
        FinancialFact(schema_version="v2", name="assets", value="1")
    with pytest.raises(ValidationError):
        _filing(overrides={"schema_version": "v2"})
    with pytest.raises(ValidationError):
        FilingRepository(schema_version="v2", filings=())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("filing_id", ""),
        ("accession_id", "not stable"),
        ("instrument_id", " AAPL"),
        ("form_type", "10 K"),
        ("currency", ""),
    ],
)
def test_filing_identifiers_are_stable_ids(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _filing(overrides={field: value})


@pytest.mark.parametrize("name", ["", "not stable", " assets", "assets "])
def test_fact_name_is_a_stable_id(name: object) -> None:
    with pytest.raises(ValidationError):
        FinancialFact(schema_version="v1", name=name, value="1")


@pytest.mark.parametrize(
    "value",
    [1.25, True, False, "NaN", "Infinity", "-Infinity", "", " 1", "1 ", None],
)
def test_financial_fact_requires_an_exact_finite_decimal(value: object) -> None:
    with pytest.raises(ValidationError):
        FinancialFact(schema_version="v1", name="assets", value=value)


def test_facts_are_required_nonempty_unique_and_canonically_sorted() -> None:
    facts = _filing_payload()["facts"]
    assert isinstance(facts, list)
    unsorted = list(reversed(facts))
    filing = _filing(facts=unsorted)

    assert tuple(fact.name for fact in filing.facts) == tuple(
        sorted(fact["name"] for fact in facts)
    )
    assert isinstance(filing.facts, tuple)

    for invalid_facts in ([], [facts[0], deepcopy(facts[0])]):
        with pytest.raises(ValidationError):
            _filing(facts=invalid_facts)

    payload = _filing_payload()
    payload.pop("facts")
    with pytest.raises(ValidationError):
        FinancialFiling.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("statement_type", "assets"),
        ("reporting_period", "monthly"),
        ("unit_scale", "billions"),
    ],
)
def test_filing_rejects_unknown_statement_period_and_unit_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _filing(overrides={field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"fiscal_period_start": "2024-01-01"},
        {"fiscal_period_start": datetime(2023, 1, 1, tzinfo=timezone.utc)},
        {"fiscal_period_end": 20231231},
        {"fiscal_period_end": "2023-12-31T00:00:00Z"},
        {"fiscal_period_end": " 2023-12-31"},
    ],
)
def test_filing_requires_exact_dates_and_ordered_fiscal_period(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _filing(overrides=overrides)


@pytest.mark.parametrize("missing", ["filed_at", "published_at", "available_at"])
def test_filing_requires_filed_published_and_available_timestamps(missing: str) -> None:
    payload = _filing_payload()
    if missing == "filed_at":
        payload.pop(missing)
    else:
        manifest = payload["manifest"]
        assert isinstance(manifest, dict)
        manifest.pop(missing)

    with pytest.raises(ValidationError):
        FinancialFiling.model_validate(payload)


@pytest.mark.parametrize(
    ("filed_at", "published_at"),
    [
        ("2024-02-15T13:00:00Z", None),
        ("2024-02-15T13:00:00Z", "2024-02-15T13:00:00.000001Z"),
        ("2024-02-15T13:00:00Z", "2024-02-15T12:59:59.999999Z"),
        ("2024-02-15", "2024-02-15T13:00:00Z"),
    ],
)
def test_manifest_publication_is_required_and_exactly_the_filing_instant(
    filed_at: object, published_at: object
) -> None:
    with pytest.raises(ValidationError):
        _filing(
            overrides={"filed_at": filed_at},
            manifest_overrides={"published_at": published_at},
        )


@pytest.mark.parametrize(
    "manifest_overrides",
    [
        {"available_at": None},
        {"available_at": "2024-02-15T12:59:59.999999Z"},
        {"event_time": None},
        {"event_time": "2023-12-30T23:59:59Z"},
        {"event_time": "2024-01-01T00:00:00Z"},
    ],
)
def test_filing_rejects_missing_early_or_wrong_period_provenance(
    manifest_overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _filing(manifest_overrides=manifest_overrides)


def test_event_time_may_be_any_utc_instant_on_the_fiscal_period_end() -> None:
    filing = _filing(manifest_overrides={"event_time": "2023-12-31T00:00:00Z"})

    assert filing.manifest.event_time == datetime(2023, 12, 31, tzinfo=timezone.utc)


def test_repository_is_deterministically_sorted_and_read_only() -> None:
    original = _filing(0)
    restatement = _filing(1)
    forward = _repository(restatement, original)
    reverse = _repository(original, restatement)

    assert isinstance(forward.filings, tuple)
    assert forward.filings == reverse.filings
    assert forward.model_dump_json() == reverse.model_dump_json()
    assert tuple(item.manifest.revision for item in forward.filings) == (0, 1)


def test_repository_rejects_duplicate_filing_id() -> None:
    original = _filing(0)
    same_id_other_series = _filing(
        1,
        overrides={
            "filing_id": original.filing_id,
            "statement_type": StatementType.CASH_FLOW,
        },
    )

    with pytest.raises(ValidationError, match="duplicate_filing_id"):
        _repository(original, same_id_other_series)


def test_repository_rejects_duplicate_business_key_and_revision() -> None:
    original = _filing(0)
    duplicate_revision = _filing(
        0,
        overrides={
            "filing_id": "AAPL-2023-10K-r0-duplicate",
            "accession_id": "0000320193-24-000009",
        },
        manifest_overrides={
            "manifest_id": "AAPL-2023-10K-capture-r0-duplicate",
            "source_locator": "fixture://sec/AAPL/2023/10-K/r0-duplicate",
        },
    )

    with pytest.raises(ValidationError, match="duplicate_filing_business_key"):
        _repository(original, duplicate_revision)


def test_repository_rejects_revision_series_with_filing_time_regression() -> None:
    original = _filing(0)
    later_revision_filed_earlier = _retimed_filing(
        1,
        filed_at="2024-02-14T13:00:00Z",
        available_at="2024-02-16T13:05:00Z",
        fetched_at="2024-02-16T13:06:00Z",
        ingested_at="2024-02-16T13:07:00Z",
        revision=1,
        filing_id="AAPL-2023-10K-r1-early-filed",
        accession_id="0000320193-24-000010",
    )

    with pytest.raises(ValidationError, match="revision_chronology"):
        _repository(original, later_revision_filed_earlier)


def test_repository_rejects_revision_series_with_availability_regression() -> None:
    delayed_original = _retimed_filing(
        0,
        filed_at="2024-02-15T13:00:00Z",
        available_at="2024-03-10T13:05:00Z",
        fetched_at="2024-03-10T13:06:00Z",
        ingested_at="2024-03-10T13:07:00Z",
        revision=0,
        filing_id="AAPL-2023-10K-r0-delayed",
        accession_id="0000320193-24-000011",
    )
    restatement = _retimed_filing(
        1,
        filed_at="2024-03-01T14:00:00Z",
        available_at="2024-03-01T14:10:00Z",
        fetched_at="2024-03-01T14:11:00Z",
        ingested_at="2024-03-01T14:12:00Z",
        revision=1,
        filing_id="AAPL-2023-10K-r1-fast",
        accession_id="0000320193-24-000012",
    )

    with pytest.raises(ValidationError, match="revision_chronology"):
        _repository(delayed_original, restatement)


def test_vintage_selector_public_errors_and_signature_are_stable() -> None:
    assert issubclass(VintageMissingError, VintageSelectionError)
    assert issubclass(VintageFutureError, VintageSelectionError)
    assert issubclass(VintageConflictError, VintageSelectionError)
    signature = inspect.signature(VintageSelector.select)

    assert tuple(signature.parameters) == ("self", "candidates", "knowledge_cutoff")
    assert signature.parameters["candidates"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert signature.parameters["knowledge_cutoff"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["knowledge_cutoff"].default is inspect.Parameter.empty


def test_vintage_selector_requires_nonempty_same_key_unique_revision_candidates() -> None:
    selector = VintageSelector()
    original = _filing(0)
    other_key = _filing(1, overrides={"currency": "EUR"})
    duplicate_revision = _filing(
        0,
        overrides={"filing_id": "AAPL-2023-10K-r0-other"},
        manifest_overrides={"manifest_id": "AAPL-2023-10K-capture-r0-other"},
    )

    with pytest.raises(VintageMissingError):
        selector.select((), knowledge_cutoff="2024-03-01T14:10:00Z")
    with pytest.raises(VintageConflictError):
        selector.select((original, other_key), knowledge_cutoff="2024-03-01T14:10:00Z")
    with pytest.raises(VintageConflictError):
        selector.select(
            (original, duplicate_revision),
            knowledge_cutoff="2024-03-01T14:10:00Z",
        )


@pytest.mark.parametrize(
    "cutoff",
    [
        datetime(2024, 3, 1, 14, 10),
        "2024-03-01",
        "2024-03-01T14:10:00",
        1709302200,
        1709302200.0,
        True,
    ],
)
def test_vintage_selector_requires_an_aware_exact_cutoff(cutoff: object) -> None:
    with pytest.raises(VintageSelectionError):
        VintageSelector().select((_filing(0),), knowledge_cutoff=cutoff)


def test_fiscal_end_before_cutoff_does_not_make_a_later_filing_available() -> None:
    original = _filing(0)
    cutoff = datetime(2024, 1, 31, tzinfo=timezone.utc)

    assert original.fiscal_period_end < cutoff.date()
    with pytest.raises(VintageFutureError):
        VintageSelector().select((original,), knowledge_cutoff=cutoff)


def test_publication_and_availability_equality_are_inclusive() -> None:
    original = _filing(0)
    selector = VintageSelector()

    assert original.manifest.published_at == original.filed_at
    assert selector.select((original,), knowledge_cutoff=original.manifest.available_at) == original
    with pytest.raises(VintageFutureError):
        selector.select(
            (original,),
            knowledge_cutoff=original.manifest.available_at - timedelta(microseconds=1),
        )


def test_highest_eligible_revision_wins_before_and_after_restatement() -> None:
    original = _filing(0)
    restatement = _filing(1)
    selector = VintageSelector()

    assert (
        selector.select((restatement, original), knowledge_cutoff=original.manifest.available_at)
        == original
    )
    assert (
        selector.select((original, restatement), knowledge_cutoff=restatement.manifest.available_at)
        == restatement
    )


def test_revision_selection_ignores_input_and_availability_order() -> None:
    revision_zero = _retimed_filing(
        0,
        filed_at="2024-01-10T12:00:00Z",
        available_at="2024-02-10T12:00:00Z",
        fetched_at="2024-02-10T12:01:00Z",
        ingested_at="2024-02-10T12:02:00Z",
        revision=0,
        filing_id="AAPL-2023-10K-r0-slow",
        accession_id="0000320193-24-000020",
    )
    revision_one = _retimed_filing(
        1,
        filed_at="2024-01-20T12:00:00Z",
        available_at="2024-01-25T12:00:00Z",
        fetched_at="2024-01-25T12:01:00Z",
        ingested_at="2024-01-25T12:02:00Z",
        revision=1,
        filing_id="AAPL-2023-10K-r1-fast",
        accession_id="0000320193-24-000021",
    )
    selector = VintageSelector()

    for candidates in ((revision_zero, revision_one), (revision_one, revision_zero)):
        assert selector.select(candidates, knowledge_cutoff="2024-03-01T00:00:00Z") == revision_one


def test_revision_selection_breaks_tied_availability_only_by_revision() -> None:
    revision_zero = _retimed_filing(
        0,
        filed_at="2024-01-10T12:00:00Z",
        available_at="2024-02-01T12:00:00Z",
        fetched_at="2024-02-01T12:01:00Z",
        ingested_at="2024-02-01T12:02:00Z",
        revision=0,
        filing_id="AAPL-2023-10K-r0-tied",
        accession_id="0000320193-24-000022",
    )
    revision_one = _retimed_filing(
        1,
        filed_at="2024-01-20T12:00:00Z",
        available_at="2024-02-01T12:00:00Z",
        fetched_at="2024-02-01T12:01:00Z",
        ingested_at="2024-02-01T12:02:00Z",
        revision=1,
        filing_id="AAPL-2023-10K-r1-tied",
        accession_id="0000320193-24-000023",
    )

    assert (
        VintageSelector().select(
            (revision_one, revision_zero), knowledge_cutoff="2024-02-01T12:00:00Z"
        )
        == revision_one
    )


def test_ingested_after_cutoff_remains_eligible_until_pit_06_archive_policy() -> None:
    filing = _retimed_filing(
        0,
        filed_at="2024-02-01T12:00:00Z",
        available_at="2024-02-01T12:01:00Z",
        fetched_at="2024-02-01T12:02:00Z",
        ingested_at="2024-04-01T00:00:00Z",
        revision=0,
        filing_id="AAPL-2023-10K-r0-late-ingest",
        accession_id="0000320193-24-000024",
    )
    cutoff = datetime(2024, 3, 1, tzinfo=timezone.utc)

    assert filing.manifest.ingested_at > cutoff
    assert VintageSelector().select((filing,), knowledge_cutoff=cutoff) == filing


def test_repository_public_errors_and_as_of_signature_are_stable() -> None:
    assert issubclass(FilingMissingError, FilingRepositoryError)
    assert issubclass(FilingFutureError, FilingRepositoryError)
    assert issubclass(FilingQueryError, FilingRepositoryError)
    signature = inspect.signature(FilingRepository.as_of)

    assert tuple(signature.parameters) == (
        "self",
        "instrument_id",
        "fiscal_period_end",
        "knowledge_cutoff",
        "source",
        "statement_type",
        "reporting_period",
        "form_type",
        "currency",
        "unit_scale",
    )
    for name in (
        "knowledge_cutoff",
        "source",
        "statement_type",
        "reporting_period",
        "form_type",
        "currency",
        "unit_scale",
    ):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters[name].default is inspect.Parameter.empty


def test_repository_as_of_uses_inclusive_availability_and_highest_revision() -> None:
    original = _filing(0)
    restatement = _filing(1)
    repository = _repository(restatement, original)

    assert _query(repository, knowledge_cutoff=original.manifest.available_at) == original
    assert _query(repository, knowledge_cutoff=restatement.manifest.available_at) == restatement
    with pytest.raises(FilingFutureError):
        _query(
            repository,
            knowledge_cutoff=original.manifest.available_at - timedelta(microseconds=1),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"instrument_id": "MSFT"},
        {"fiscal_period_end": "2022-12-31"},
        {"source": "other-source"},
        {"statement_type": StatementType.CASH_FLOW},
        {"reporting_period": ReportingPeriod.QUARTERLY},
        {"form_type": "10-Q"},
        {"currency": "EUR"},
        {"unit_scale": UnitScale.THOUSANDS},
    ],
)
def test_repository_never_falls_back_across_any_explicit_selector(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(FilingMissingError):
        _query(_repository(_filing(0), _filing(1)), **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"instrument_id": "not stable"},
        {"fiscal_period_end": datetime(2023, 12, 31, tzinfo=timezone.utc)},
        {"fiscal_period_end": "2023-12-31T00:00:00Z"},
        {"knowledge_cutoff": datetime(2024, 3, 1, 14, 10)},
        {"knowledge_cutoff": "2024-03-01"},
        {"source": ""},
        {"statement_type": "assets"},
        {"reporting_period": "monthly"},
        {"form_type": "10 K"},
        {"currency": "US D"},
        {"unit_scale": "billions"},
    ],
)
def test_repository_rejects_malformed_queries_as_query_errors(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(FilingQueryError):
        _query(_repository(_filing(0), _filing(1)), **overrides)


def test_repository_distinguishes_missing_series_from_future_exact_series() -> None:
    repository = _repository(_filing(0))

    with pytest.raises(FilingFutureError):
        _query(repository, knowledge_cutoff="2024-01-01T00:00:00Z")
    with pytest.raises(FilingMissingError):
        _query(repository, fiscal_period_end="2022-12-31")


def test_repository_delegates_exact_series_vintage_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(_filing(0), _filing(1))
    calls: list[tuple[tuple[FinancialFiling, ...], object]] = []
    original_select = VintageSelector.select

    def recording_select(
        self: VintageSelector,
        candidates: tuple[FinancialFiling, ...],
        *,
        knowledge_cutoff: object,
    ) -> FinancialFiling:
        calls.append((candidates, knowledge_cutoff))
        return original_select(self, candidates, knowledge_cutoff=knowledge_cutoff)

    monkeypatch.setattr(VintageSelector, "select", recording_select)

    selected = _query(repository)

    assert selected.manifest.revision == 1
    assert len(calls) == 1
    assert {candidate.filing_id for candidate in calls[0][0]} == {
        "AAPL-2023-10K-r0",
        "AAPL-2023-10K-r1",
    }


def test_removed_fact_in_restatement_stays_absent_without_imputation() -> None:
    selected = _query(_repository(_filing(0), _filing(1)))

    assert selected.manifest.revision == 1
    assert "discontinued_operations" not in {fact.name for fact in selected.facts}
    assert tuple(fact.name for fact in selected.facts) == ("assets", "liabilities")


def test_financial_vintage_selection_is_network_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PIT-03 selection attempted network access")

    monkeypatch.setattr(socket, "socket", deny_socket)
    repository = _repository(_filing(0), _filing(1))

    assert _query(repository).filing_id == "AAPL-2023-10K-r1"
    assert (
        VintageSelector()
        .select(repository.filings, knowledge_cutoff="2024-03-01T14:10:00Z")
        .filing_id
        == "AAPL-2023-10K-r1"
    )


def test_pit_03_exports_only_financial_vintage_contracts_not_future_observations() -> None:
    assert not hasattr(fundamentals_module, "Observation")
    assert not hasattr(fundamentals_module, "ArchivePolicy")
    assert not hasattr(fundamentals_module, "EvidenceBundle")

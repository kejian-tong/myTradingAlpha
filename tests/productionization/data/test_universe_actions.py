"""PIT-05 contracts for historical universes and corporate-action projection."""

from __future__ import annotations

import builtins
import inspect
import json
import socket
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import mytradingalpha.data.universe as universe_module
import pytest
from mytradingalpha.data.actions import (
    ActionProjection,
    ActionType,
    CorporateActionConflictError,
    CorporateActionFutureError,
    CorporateActionMissingError,
    CorporateActionQueryError,
    CorporateActionRepository,
    CorporateActionRepositoryError,
    DelistingAction,
    DividendAction,
    SplitAction,
    TickerChangeAction,
)
from mytradingalpha.data.universe import (
    AssetClass,
    Instrument,
    SymbolAlias,
    UniverseConflictError,
    UniverseFutureError,
    UniverseManifest,
    UniverseMembership,
    UniverseMissingError,
    UniverseQueryError,
    UniverseRepositoryError,
)
from pydantic import ValidationError

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "pit" / "universe_actions_v1.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _payload(collection: str, index: int) -> dict[str, object]:
    values = _fixture()[collection]
    assert isinstance(values, list)
    payload = deepcopy(values[index])
    assert isinstance(payload, dict)
    return payload


def _instrument(
    index: int = 0,
    *,
    overrides: dict[str, object] | None = None,
    manifest_overrides: dict[str, object] | None = None,
) -> Instrument:
    payload = _payload("instruments", index)
    if overrides:
        payload.update(overrides)
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    if manifest_overrides:
        manifest.update(manifest_overrides)
    return Instrument.model_validate(payload)


def _alias(
    index: int = 0,
    *,
    overrides: dict[str, object] | None = None,
    manifest_overrides: dict[str, object] | None = None,
) -> SymbolAlias:
    payload = _payload("aliases", index)
    if overrides:
        payload.update(overrides)
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    if manifest_overrides:
        manifest.update(manifest_overrides)
    return SymbolAlias.model_validate(payload)


def _membership(
    index: int = 0,
    *,
    overrides: dict[str, object] | None = None,
    manifest_overrides: dict[str, object] | None = None,
) -> UniverseMembership:
    payload = _payload("memberships", index)
    if overrides:
        payload.update(overrides)
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    if manifest_overrides:
        manifest.update(manifest_overrides)
    return UniverseMembership.model_validate(payload)


def _action_payload(index: int) -> dict[str, object]:
    return _payload("actions", index)


def _action(
    index: int,
    *,
    overrides: dict[str, object] | None = None,
    manifest_overrides: dict[str, object] | None = None,
) -> TickerChangeAction | SplitAction | DividendAction | DelistingAction:
    payload = _action_payload(index)
    if overrides:
        payload.update(overrides)
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    if manifest_overrides:
        manifest.update(manifest_overrides)
    factories = {
        "ticker_change": TickerChangeAction,
        "split": SplitAction,
        "dividend": DividendAction,
        "delisting": DelistingAction,
    }
    action_type = payload["action_type"]
    assert isinstance(action_type, str)
    return factories[action_type].model_validate(payload)


def _universe_manifest(
    *,
    instruments: tuple[Instrument, ...] | list[Instrument] | None = None,
    aliases: tuple[SymbolAlias, ...] | list[SymbolAlias] | None = None,
    memberships: tuple[UniverseMembership, ...] | list[UniverseMembership] | None = None,
) -> UniverseManifest:
    return UniverseManifest(
        schema_version="v1",
        instruments=instruments
        if instruments is not None
        else tuple(_instrument(index) for index in range(3)),
        aliases=aliases if aliases is not None else tuple(_alias(index) for index in range(4)),
        memberships=memberships
        if memberships is not None
        else tuple(_membership(index) for index in range(3)),
    )


def _action_repository(
    *actions: TickerChangeAction | SplitAction | DividendAction | DelistingAction,
) -> CorporateActionRepository:
    selected = actions or tuple(_action(index) for index in range(5))
    return CorporateActionRepository(schema_version="v1", actions=selected)


def _members(
    manifest: UniverseManifest,
    *,
    as_of: object = "2024-06-30",
    knowledge_cutoff: object = "2024-06-30T23:59:59Z",
    source: object = "synthetic-universe",
    universe_id: object = "us-liquid-v1",
) -> tuple[Instrument, ...]:
    return manifest.members(
        as_of,  # type: ignore[arg-type]
        knowledge_cutoff=knowledge_cutoff,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        universe_id=universe_id,  # type: ignore[arg-type]
    )


def _resolve_symbol(
    manifest: UniverseManifest,
    *,
    symbol: object = "NEW",
    as_of: object = "2024-06-30",
    knowledge_cutoff: object = "2024-06-30T23:59:59Z",
    source: object = "synthetic-universe",
) -> Instrument:
    return manifest.resolve_symbol(
        symbol,  # type: ignore[arg-type]
        as_of,  # type: ignore[arg-type]
        knowledge_cutoff=knowledge_cutoff,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
    )


def _apply(
    repository: CorporateActionRepository,
    *,
    instrument_id: object = "inst-acme",
    as_of: object = "2024-06-30",
    knowledge_cutoff: object = "2024-06-30T23:59:59Z",
    source: object = "synthetic-actions",
    initial_symbol: object = "OLD",
) -> ActionProjection:
    return repository.apply(
        instrument_id,  # type: ignore[arg-type]
        as_of,  # type: ignore[arg-type]
        knowledge_cutoff=knowledge_cutoff,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        initial_symbol=initial_symbol,  # type: ignore[arg-type]
    )


def test_pit_05_enums_and_error_hierarchies_have_stable_public_values() -> None:
    assert {item.value for item in AssetClass} == {"equity", "etf"}
    assert {item.value for item in ActionType} == {
        "ticker_change",
        "split",
        "dividend",
        "delisting",
    }
    assert issubclass(UniverseMissingError, UniverseRepositoryError)
    assert issubclass(UniverseFutureError, UniverseRepositoryError)
    assert issubclass(UniverseQueryError, UniverseRepositoryError)
    assert issubclass(UniverseConflictError, UniverseRepositoryError)
    assert issubclass(CorporateActionMissingError, CorporateActionRepositoryError)
    assert issubclass(CorporateActionFutureError, CorporateActionRepositoryError)
    assert issubclass(CorporateActionQueryError, CorporateActionRepositoryError)
    assert issubclass(CorporateActionConflictError, CorporateActionRepositoryError)


def test_universe_contracts_expose_only_frozen_v1_fields() -> None:
    assert set(Instrument.model_fields) == {
        "schema_version",
        "instrument_id",
        "initial_symbol",
        "asset_class",
        "currency",
        "exchange",
        "active_from",
        "active_to",
        "lot_size",
        "manifest",
    }
    assert set(SymbolAlias.model_fields) == {
        "schema_version",
        "alias_id",
        "instrument_id",
        "symbol",
        "valid_from",
        "valid_to",
        "manifest",
    }
    assert set(UniverseMembership.model_fields) == {
        "schema_version",
        "membership_id",
        "universe_id",
        "instrument_id",
        "valid_from",
        "valid_to",
        "manifest",
    }
    assert set(UniverseManifest.model_fields) == {
        "schema_version",
        "instruments",
        "aliases",
        "memberships",
    }


def test_action_contracts_expose_only_concrete_v1_fields() -> None:
    common = {
        "schema_version",
        "action_type",
        "action_id",
        "instrument_id",
        "effective_date",
        "manifest",
    }
    assert set(TickerChangeAction.model_fields) == common | {"old_symbol", "new_symbol"}
    assert set(SplitAction.model_fields) == common | {"new_shares_per_old_share"}
    assert set(DividendAction.model_fields) == common | {
        "amount_per_share",
        "currency",
        "payable_date",
    }
    assert set(DelistingAction.model_fields) == common | {"reason"}
    assert "settlement" not in DelistingAction.model_fields
    assert set(CorporateActionRepository.model_fields) == {"schema_version", "actions"}
    assert set(ActionProjection.model_fields) == {
        "schema_version",
        "instrument_id",
        "as_of",
        "symbol",
        "active",
        "actions",
    }


def test_fixture_round_trips_stable_identity_and_exact_decimal_strings() -> None:
    instrument = _instrument()
    ticker_change = _action(0)
    split = _action(1)
    dividend = _action(3)
    delisting = _action(4)

    assert instrument.instrument_id == "inst-acme"
    assert instrument.initial_symbol == "OLD"
    assert instrument.asset_class is AssetClass.EQUITY
    assert instrument.active_from == date(2020, 1, 2)
    assert instrument.active_to == date(2024, 7, 1)
    assert ticker_change.action_type is ActionType.TICKER_CHANGE
    assert split.new_shares_per_old_share == Decimal("2.000000")
    assert dividend.amount_per_share == Decimal("0.1250")
    assert split.model_dump(mode="json")["new_shares_per_old_share"] == "2.000000"
    assert dividend.model_dump(mode="json")["amount_per_share"] == "0.1250"
    assert delisting.reason == "merger completed"
    assert Instrument.model_validate_json(instrument.model_dump_json()) == instrument
    assert SplitAction.model_validate_json(split.model_dump_json()) == split
    assert DividendAction.model_validate_json(dividend.model_dump_json()) == dividend


def test_records_nested_manifests_repositories_and_projections_are_deeply_frozen() -> None:
    manifest = _universe_manifest()
    repository = _action_repository()
    projection = _apply(repository)

    with pytest.raises(ValidationError):
        manifest.instruments[0].initial_symbol = "CHANGED"
    with pytest.raises(ValidationError):
        manifest.aliases[0].manifest.source = "changed"
    with pytest.raises(ValidationError):
        manifest.memberships = ()
    with pytest.raises(ValidationError):
        repository.actions = ()
    with pytest.raises(ValidationError):
        projection.symbol = "CHANGED"


@pytest.mark.parametrize(
    ("factory", "collection", "index"),
    [
        (Instrument.model_validate, "instruments", 0),
        (SymbolAlias.model_validate, "aliases", 0),
        (UniverseMembership.model_validate, "memberships", 0),
        (TickerChangeAction.model_validate, "actions", 0),
        (SplitAction.model_validate, "actions", 1),
        (DividendAction.model_validate, "actions", 2),
        (DelistingAction.model_validate, "actions", 4),
    ],
)
def test_records_forbid_extra_fields_and_require_exact_v1_schema(
    factory: object,
    collection: str,
    index: int,
) -> None:
    payload = _payload(collection, index)
    with pytest.raises(ValidationError):
        factory({**payload, "provider_payload": {}})  # type: ignore[operator]
    payload["schema_version"] = "v2"
    with pytest.raises(ValidationError):
        factory(payload)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (_instrument, "instrument_id", "not stable"),
        (_instrument, "initial_symbol", " OLD"),
        (_instrument, "currency", ""),
        (_instrument, "exchange", "XNYS "),
        (_alias, "alias_id", ""),
        (_alias, "symbol", "NEW "),
        (_membership, "membership_id", "not stable"),
        (_membership, "universe_id", " us-liquid-v1"),
    ],
)
def test_universe_identifiers_symbols_and_selectors_are_exact_trimmed_values(
    factory: object,
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        factory(overrides={field: value})  # type: ignore[operator]


@pytest.mark.parametrize("value", [0, -1, 1.0, True, "1", None])
def test_instrument_lot_size_is_a_strict_positive_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        _instrument(overrides={"lot_size": value})


@pytest.mark.parametrize(
    ("factory", "from_field", "to_field", "overrides"),
    [
        (_instrument, "active_from", "active_to", {"active_from": "2020-01-02T00:00:00Z"}),
        (_instrument, "active_from", "active_to", {"active_from": "2024-07-01"}),
        (_instrument, "active_from", "active_to", {"active_to": "2020-01-01"}),
        (_alias, "valid_from", "valid_to", {"valid_from": 20200102}),
        (_alias, "valid_from", "valid_to", {"valid_to": "2020-01-02"}),
        (_membership, "valid_from", "valid_to", {"valid_to": "2020-01-02"}),
    ],
)
def test_universe_intervals_require_exact_dates_and_nonempty_half_open_order(
    factory: object,
    from_field: str,
    to_field: str,
    overrides: dict[str, object],
) -> None:
    assert from_field != to_field
    with pytest.raises(ValidationError):
        factory(overrides=overrides)  # type: ignore[operator]


def test_universe_manifest_canonically_sorts_immutable_tuple_collections() -> None:
    manifest = _universe_manifest(
        instruments=list(reversed([_instrument(index) for index in range(3)])),
        aliases=list(reversed([_alias(index) for index in range(4)])),
        memberships=list(reversed([_membership(index) for index in range(3)])),
    )

    assert isinstance(manifest.instruments, tuple)
    assert isinstance(manifest.aliases, tuple)
    assert isinstance(manifest.memberships, tuple)
    assert tuple(item.instrument_id for item in manifest.instruments) == (
        "inst-acme",
        "inst-market-etf",
        "inst-survivor",
    )
    assert tuple(item.alias_id for item in manifest.aliases) == tuple(
        sorted(item.alias_id for item in manifest.aliases)
    )
    assert tuple(item.membership_id for item in manifest.memberships) == tuple(
        sorted(item.membership_id for item in manifest.memberships)
    )


@pytest.mark.parametrize("collection", ["instruments", "aliases", "memberships"])
def test_universe_manifest_rejects_duplicate_business_ids(collection: str) -> None:
    values = {
        "instruments": [_instrument(), _instrument()],
        "aliases": [_alias(), _alias()],
        "memberships": [_membership(), _membership()],
    }
    kwargs = {
        "instruments": [_instrument()],
        "aliases": [_alias()],
        "memberships": [_membership()],
    }
    kwargs[collection] = values[collection]
    with pytest.raises(ValidationError):
        _universe_manifest(**kwargs)  # type: ignore[arg-type]


def test_universe_manifest_rejects_orphan_and_overlapping_aliases_and_memberships() -> None:
    orphan_alias = _alias(overrides={"instrument_id": "inst-unknown"})
    overlapping_alias = _alias(
        overrides={
            "alias_id": "alias-acme-old-overlap",
            "valid_from": "2024-03-14",
            "valid_to": "2024-03-16",
        }
    )
    overlapping_membership = _membership(
        overrides={
            "membership_id": "membership-us-liquid-acme-overlap",
            "valid_from": "2024-06-30",
            "valid_to": None,
        }
    )

    with pytest.raises(ValidationError):
        _universe_manifest(aliases=[_alias(), orphan_alias])
    with pytest.raises(ValidationError):
        _universe_manifest(aliases=[_alias(0), _alias(1), overlapping_alias])
    with pytest.raises(ValidationError):
        _universe_manifest(memberships=[_membership(), overlapping_membership])


def test_membership_is_historical_includes_survivors_and_etfs_and_uses_half_open_bounds() -> None:
    manifest = _universe_manifest()

    before_delisting = _members(manifest, as_of="2024-06-30")
    on_delisting = _members(manifest, as_of="2024-07-01")

    assert tuple(item.instrument_id for item in before_delisting) == (
        "inst-acme",
        "inst-market-etf",
        "inst-survivor",
    )
    assert tuple(item.asset_class for item in before_delisting) == (
        AssetClass.EQUITY,
        AssetClass.ETF,
        AssetClass.EQUITY,
    )
    assert tuple(item.instrument_id for item in on_delisting) == (
        "inst-market-etf",
        "inst-survivor",
    )


def test_membership_start_is_inclusive_and_requires_both_instrument_and_membership_validity() -> (
    None
):
    manifest = _universe_manifest()

    members = _members(
        manifest,
        as_of="2020-01-02",
        knowledge_cutoff="2020-01-02T23:59:59Z",
    )

    assert "inst-acme" in {item.instrument_id for item in members}


def test_symbol_resolution_tracks_alias_intervals_without_changing_stable_identity() -> None:
    manifest = _universe_manifest()

    old = _resolve_symbol(
        manifest,
        symbol="OLD",
        as_of="2024-03-14",
        knowledge_cutoff="2024-03-14T23:59:59Z",
    )
    new = _resolve_symbol(manifest, symbol="NEW", as_of="2024-03-15")

    assert old.instrument_id == new.instrument_id == "inst-acme"
    assert old.initial_symbol == new.initial_symbol == "OLD"
    with pytest.raises(UniverseMissingError):
        _resolve_symbol(manifest, symbol="OLD", as_of="2024-03-15")
    with pytest.raises(UniverseMissingError):
        _resolve_symbol(manifest, symbol="NEW", as_of="2024-07-01")


def test_universe_queries_enforce_availability_cutoff_without_ingestion_cutoff() -> None:
    late_ingested = _membership(
        manifest_overrides={
            "available_at": "2020-01-01T13:00:00Z",
            "fetched_at": "2020-01-01T13:02:00Z",
            "ingested_at": "2024-12-31T23:59:59Z",
        }
    )
    manifest = _universe_manifest(memberships=[late_ingested, _membership(1), _membership(2)])

    assert "inst-acme" in {
        item.instrument_id
        for item in _members(
            manifest,
            as_of="2024-06-30",
            knowledge_cutoff="2020-01-02T23:59:59Z",
        )
    }


def test_universe_queries_distinguish_future_missing_and_malformed_inputs() -> None:
    future_membership = _membership(
        manifest_overrides={
            "available_at": "2024-08-01T13:00:00Z",
            "fetched_at": "2024-08-01T13:01:00Z",
            "ingested_at": "2024-08-01T13:02:00Z",
        }
    )
    manifest = _universe_manifest(memberships=[future_membership])

    with pytest.raises(UniverseFutureError):
        _members(manifest, knowledge_cutoff="2024-06-30T23:59:59Z")
    with pytest.raises(UniverseMissingError):
        _members(_universe_manifest(), universe_id="unknown-universe")
    with pytest.raises(UniverseMissingError):
        _resolve_symbol(_universe_manifest(), symbol="UNKNOWN")

    for overrides in (
        {"as_of": "2024-06-30T00:00:00Z"},
        {"as_of": datetime(2024, 6, 30, tzinfo=timezone.utc)},
        {"knowledge_cutoff": "2024-06-30"},
        {"knowledge_cutoff": datetime(2024, 6, 30)},
        {"source": "not stable"},
        {"universe_id": ""},
    ):
        with pytest.raises(UniverseQueryError):
            _members(_universe_manifest(), **overrides)


def test_universe_query_defensively_revalidates_bypassed_nested_state() -> None:
    valid = _universe_manifest()
    invalid_membership = valid.memberships[0].model_copy(update={"valid_to": date(2019, 1, 1)})
    bypassed = UniverseManifest.model_construct(
        schema_version="v1",
        instruments=valid.instruments,
        aliases=valid.aliases,
        memberships=(invalid_membership, *valid.memberships[1:]),
    )

    with pytest.raises(UniverseConflictError):
        _members(bypassed)


def test_action_records_require_matching_discriminator_exact_date_and_event_date() -> None:
    for index, wrong_type in (
        (0, "split"),
        (1, "dividend"),
        (2, "delisting"),
        (4, "ticker_change"),
    ):
        with pytest.raises(ValidationError):
            _action(index, overrides={"action_type": wrong_type})

    with pytest.raises(ValidationError):
        _action(0, overrides={"effective_date": "2024-03-15T00:00:00Z"})
    with pytest.raises(ValidationError):
        _action(0, manifest_overrides={"event_time": "2024-03-14T23:59:59Z"})
    with pytest.raises(ValidationError):
        _action(0, manifest_overrides={"event_time": None})


def test_action_publication_is_required_but_may_precede_or_follow_effective_event() -> None:
    before = _action(0)
    after = _action(
        0,
        manifest_overrides={
            "published_at": "2024-03-16T13:00:00Z",
            "available_at": "2024-03-16T13:00:00Z",
            "fetched_at": "2024-03-16T13:01:00Z",
            "ingested_at": "2024-03-16T13:02:00Z",
        },
    )

    assert before.manifest.published_at < before.manifest.event_time
    assert after.manifest.published_at > after.manifest.event_time
    with pytest.raises(ValidationError):
        _action(0, manifest_overrides={"published_at": None})


@pytest.mark.parametrize("value", ["0", "-1", 1.5, True, "NaN", "Infinity", " 2", None])
def test_split_ratio_is_an_exact_strictly_positive_decimal(value: object) -> None:
    with pytest.raises(ValidationError):
        _action(1, overrides={"new_shares_per_old_share": value})


@pytest.mark.parametrize("value", ["0", "-0.01", 0.1, True, "NaN", "Infinity", " 0.1", None])
def test_dividend_amount_is_an_exact_strictly_positive_decimal(value: object) -> None:
    with pytest.raises(ValidationError):
        _action(2, overrides={"amount_per_share": value})


def test_dividend_payable_date_is_not_before_effective_ex_date() -> None:
    assert _action(2).payable_date == date(2024, 5, 31)
    assert _action(2, overrides={"payable_date": "2024-05-15"}).payable_date == date(2024, 5, 15)
    with pytest.raises(ValidationError):
        _action(2, overrides={"payable_date": "2024-05-14"})


@pytest.mark.parametrize(
    ("index", "overrides"),
    [
        (0, {"old_symbol": "SAME", "new_symbol": "SAME"}),
        (0, {"old_symbol": " OLD"}),
        (0, {"new_symbol": "NEW "}),
        (2, {"currency": "USD "}),
        (4, {"reason": ""}),
        (4, {"reason": " padded"}),
        (4, {"settlement": "1.00"}),
    ],
)
def test_action_specific_fields_reject_ambiguous_or_future_accounting_values(
    index: int,
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _action(index, overrides=overrides)


def test_action_repository_canonically_sorts_revision_series() -> None:
    repository = _action_repository(*reversed([_action(index) for index in range(5)]))

    assert isinstance(repository.actions, tuple)
    assert tuple(
        (item.effective_date, item.action_id, item.manifest.revision) for item in repository.actions
    ) == tuple(
        sorted(
            (
                item.effective_date,
                item.action_id,
                item.manifest.revision,
            )
            for item in repository.actions
        )
    )


def test_action_repository_rejects_duplicate_and_inconsistent_revision_series() -> None:
    duplicate = _action(0)
    wrong_instrument = _action(
        3,
        overrides={"instrument_id": "inst-other"},
        manifest_overrides={"manifest_id": "action-acme-dividend-r1-other"},
    )
    regressed_revision = _action(
        3,
        manifest_overrides={
            "published_at": "2024-04-30T13:00:00Z",
            "available_at": "2024-04-30T13:00:00Z",
            "fetched_at": "2024-04-30T13:01:00Z",
            "ingested_at": "2024-04-30T13:02:00Z",
        },
    )

    with pytest.raises(ValidationError):
        _action_repository(duplicate, duplicate)
    with pytest.raises(ValidationError):
        _action_repository(_action(2), wrong_instrument)
    with pytest.raises(ValidationError):
        _action_repository(_action(2), regressed_revision)


def test_apply_selects_highest_available_revision_and_preserves_exact_action_terms() -> None:
    repository = _action_repository()

    before_revision = _apply(repository, knowledge_cutoff="2024-05-19T23:59:59Z")
    after_revision = _apply(repository, knowledge_cutoff="2024-05-20T13:00:00Z")

    first_dividend = next(
        action for action in before_revision.actions if action.action_type is ActionType.DIVIDEND
    )
    revised_dividend = next(
        action for action in after_revision.actions if action.action_type is ActionType.DIVIDEND
    )
    assert first_dividend.amount_per_share == Decimal("0.1000")
    assert first_dividend.manifest.revision == 0
    assert revised_dividend.amount_per_share == Decimal("0.1250")
    assert revised_dividend.manifest.revision == 1
    assert revised_dividend.model_dump(mode="json")["amount_per_share"] == "0.1250"


def test_apply_uses_effective_date_boundary_updates_symbol_and_stops_at_as_of() -> None:
    repository = _action_repository()

    before = _apply(repository, as_of="2024-03-14")
    on_change = _apply(repository, as_of="2024-03-15")
    after_split = _apply(repository, as_of="2024-04-01")

    assert before.symbol == "OLD"
    assert before.actions == ()
    assert on_change.symbol == "NEW"
    assert tuple(item.action_type for item in on_change.actions) == (ActionType.TICKER_CHANGE,)
    assert tuple(item.action_type for item in after_split.actions) == (
        ActionType.TICKER_CHANGE,
        ActionType.SPLIT,
    )


def test_apply_marks_instrument_inactive_on_delisting_effective_date() -> None:
    repository = _action_repository()

    before = _apply(repository, as_of="2024-06-30")
    delisted = _apply(repository, as_of="2024-07-01")

    assert before.active is True
    assert delisted.active is False
    assert delisted.symbol == "NEW"
    assert delisted.actions[-1].action_type is ActionType.DELISTING


def test_apply_enforces_availability_but_explicitly_defers_ingested_cutoff() -> None:
    repository = _action_repository()

    projection = _apply(
        repository,
        as_of="2024-05-15",
        knowledge_cutoff="2024-05-20T13:00:00Z",
    )

    revised = next(
        action for action in projection.actions if action.action_type is ActionType.DIVIDEND
    )
    assert revised.manifest.revision == 1
    assert revised.manifest.ingested_at > datetime(2024, 5, 20, 13, tzinfo=timezone.utc)


def test_apply_distinguishes_future_missing_and_malformed_queries() -> None:
    repository = _action_repository()

    with pytest.raises(CorporateActionFutureError):
        _apply(
            repository,
            as_of="2024-03-15",
            knowledge_cutoff="2024-03-01T00:00:00Z",
        )
    with pytest.raises(CorporateActionMissingError):
        _apply(repository, instrument_id="inst-unknown")

    for overrides in (
        {"instrument_id": "not stable"},
        {"as_of": "2024-06-30T00:00:00Z"},
        {"as_of": datetime(2024, 6, 30, tzinfo=timezone.utc)},
        {"knowledge_cutoff": "2024-06-30"},
        {"knowledge_cutoff": datetime(2024, 6, 30)},
        {"source": "synthetic actions"},
        {"initial_symbol": " OLD"},
    ):
        with pytest.raises(CorporateActionQueryError):
            _apply(repository, **overrides)


def test_apply_defensively_revalidates_bypassed_conflicting_revision_state() -> None:
    valid = _action_repository()
    conflicting = valid.actions[0].model_copy(update={"instrument_id": "inst-other"})
    bypassed = CorporateActionRepository.model_construct(
        schema_version="v1",
        actions=(valid.actions[0], conflicting),
    )

    with pytest.raises(CorporateActionConflictError):
        _apply(bypassed)


def test_public_query_signatures_require_explicit_cutoff_source_and_identity() -> None:
    assert str(inspect.signature(UniverseManifest.members)) == (
        "(self, as_of: 'date | str', *, knowledge_cutoff: 'datetime | str', "
        "source: 'str', universe_id: 'str') -> 'tuple[Instrument, ...]'"
    )
    assert str(inspect.signature(UniverseManifest.resolve_symbol)) == (
        "(self, symbol: 'str', as_of: 'date | str', *, knowledge_cutoff: "
        "'datetime | str', source: 'str') -> 'Instrument'"
    )
    assert str(inspect.signature(CorporateActionRepository.apply)) == (
        "(self, instrument_id: 'str', as_of: 'date | str', *, knowledge_cutoff: "
        "'datetime | str', source: 'str', initial_symbol: 'str') -> 'ActionProjection'"
    )


def test_in_memory_queries_do_not_access_network_filesystem_or_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _universe_manifest()
    repository = _action_repository()

    def denied(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("PIT-05 in-memory selection attempted an external read")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(builtins, "open", denied)
    monkeypatch.setattr(universe_module, "datetime", denied, raising=False)

    assert _members(manifest)
    assert _resolve_symbol(manifest).instrument_id == "inst-acme"
    assert _apply(repository).instrument_id == "inst-acme"


def test_pit_05_has_no_holdings_cash_or_accounting_methods() -> None:
    prohibited = {
        "adjust_holdings",
        "apply_to_holdings",
        "credit_cash",
        "settle_cash",
        "post_dividend",
        "calculate_nav",
    }

    assert prohibited.isdisjoint(vars(CorporateActionRepository))
    assert prohibited.isdisjoint(vars(ActionProjection))
    assert set(ActionProjection.model_fields).isdisjoint(
        {"holdings", "positions", "cash", "receivables", "liabilities", "nav"}
    )

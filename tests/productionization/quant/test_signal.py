"""SIG-03 RED contract for deterministic close-return features and QuantSignal.

The SIG-03 modules are deliberately imported only from test execution.  The
tests therefore collect on the dependency-valid base and fail for the expected
missing API until the production implementation is added.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mytradingalpha.data.actions import CorporateAction
from mytradingalpha.data.bars import AdjustmentBasis, BarFinality, DailyBar
from mytradingalpha.data.bundle import (
    EvidenceBundle,
    EvidenceRequirement,
    MissingEvidence,
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
from mytradingalpha.data.universe import Instrument, SymbolAlias, UniverseMembership

ROOT = Path(__file__).parents[3]
PIT_FIXTURES = ROOT / "tests" / "productionization" / "fixtures" / "pit"
QUANT_FIXTURE = (
    ROOT / "tests" / "productionization" / "fixtures" / "quant" / "sig03_contract.json"
)

REASON_CODES = {
    "instrument_not_in_bundle",
    "instrument_inactive_as_of",
    "instrument_not_in_universe",
    "ambiguous_universe_membership",
    "calendar_session_unavailable",
    "bar_series_ambiguous",
    "exact_session_bar_missing",
    "insufficient_lookback",
    "required_feature_missing",
    "optional_feature_missing",
}
STATUS_VALUES = {"valid", "degraded", "invalid"}
OBSERVATION_STATUS_VALUES = {"available", "missing"}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert type(payload) is dict
    return payload


def _fixture() -> dict[str, Any]:
    return _load_json(QUANT_FIXTURE)


def _pit_fixture() -> dict[str, Any]:
    return _load_json(PIT_FIXTURES / "evidence_bundle_v1.json")


def _pit_source(name: str) -> dict[str, Any]:
    sources = _pit_fixture()["source_fixtures"]
    assert type(sources) is dict
    path = sources[name]
    assert type(path) is str
    return _load_json(PIT_FIXTURES / path)


def _calendar() -> TradingCalendar:
    payload = _pit_source("calendar")
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


def _indexed(source_name: str, collection: str) -> tuple[dict[str, Any], ...]:
    fixture = _pit_fixture()
    indexes = fixture["candidate_indexes"][collection]
    records = _pit_source(source_name)[collection]
    assert type(indexes) is list
    assert type(records) is list
    return tuple(deepcopy(records[index]) for index in indexes)


def _models(source_name: str, collection: str, model: type[Any]) -> tuple[Any, ...]:
    return tuple(model.model_validate(item) for item in _indexed(source_name, collection))


def _additional_instruments() -> tuple[Instrument, ...]:
    records = _pit_fixture()["additional_instruments"]
    assert type(records) is list
    return tuple(Instrument.model_validate(item) for item in records)


def _manifest(
    session_date: str,
    *,
    source: str,
    revision: int = 0,
    available_offset_minutes: int = 1,
    ingestion_offset_minutes: int = 3,
) -> SourceManifest:
    session = _calendar().session(session_date)
    close = session.close_at
    available = close + timedelta(minutes=available_offset_minutes)
    fetched = available + timedelta(minutes=1)
    ingested = close + timedelta(minutes=ingestion_offset_minutes)
    digest = hashlib.sha256(f"{source}:{session_date}:r{revision}".encode()).hexdigest()
    return SourceManifest(
        schema_version="v1",
        manifest_id=f"{source}-{session_date}-r{revision}",
        source=source,
        source_locator=f"fixture://quant/bars/{source}/{session_date}/r{revision}",
        fetched_at=fetched,
        event_time=close,
        published_at=None,
        available_at=available,
        ingested_at=ingested,
        checksum=f"sha256:{digest}",
        terms="synthetic quant contract fixture",
        revision=revision,
    )


def _bar(
    session_date: str,
    close: str,
    *,
    source: str = "synthetic-quant-bars",
    revision: int = 0,
    adjustment_basis: AdjustmentBasis = AdjustmentBasis.UNADJUSTED,
    adjustment_version: str | None = None,
    available_offset_minutes: int = 1,
    ingestion_offset_minutes: int = 3,
) -> DailyBar:
    return DailyBar(
        schema_version="v1",
        bar_id=(
            f"bar-inst-survivor-{source}-{session_date}-"
            f"{adjustment_basis.value}-{adjustment_version or 'none'}-r{revision}"
        ),
        instrument_id="inst-survivor",
        calendar_id="XNYS.synthetic.v1",
        session_date=session_date,
        interval="1d",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1_000_000,
        adjustment_basis=adjustment_basis,
        adjustment_version=adjustment_version,
        finality=BarFinality.FINAL,
        manifest=_manifest(
            session_date,
            source=source,
            revision=revision,
            available_offset_minutes=available_offset_minutes,
            ingestion_offset_minutes=ingestion_offset_minutes,
        ),
    )


def _bars() -> tuple[DailyBar, ...]:
    required = tuple(
        _bar(session, close)
        for session, close in (
            ("2024-03-08", "100.00"),
            ("2024-03-11", "110.00"),
            ("2024-07-02", "121.00"),
        )
    )
    optional = tuple(
        _bar(session, close, source="synthetic-optional-bars")
        for session, close in (
            ("2024-03-08", "200.00"),
            ("2024-03-11", "220.00"),
            ("2024-07-02", "242.00"),
        )
    )
    return (*required, *optional)


def _requirements() -> tuple[EvidenceRequirement, ...]:
    return tuple(
        EvidenceRequirement.model_validate(item) for item in _pit_fixture()["requirements"]
    )


def _missing_optional() -> tuple[MissingEvidence, ...]:
    return tuple(
        MissingEvidence.model_validate(item) for item in _pit_fixture()["missing_optional"]
    )


def _bundle(
    *,
    bars: tuple[DailyBar, ...] | None = None,
    cutoff: str = "2024-07-02T20:04:00Z",
    replay_policy: str = "archive_realistic",
    instruments: tuple[Instrument, ...] | None = None,
    memberships: tuple[UniverseMembership, ...] | None = None,
    aliases: tuple[SymbolAlias, ...] | None = None,
) -> EvidenceBundle:
    return build_evidence_bundle(
        schema_version="v1",
        bundle_id="bundle-sig03-fixture",
        created_at="2030-01-01T00:00:00Z",
        knowledge_cutoff=cutoff,
        replay_policy=replay_policy,
        requirements=_requirements(),
        missing_optional=_missing_optional(),
        calendar=_calendar(),
        instrument_candidates=(
            instruments
            if instruments is not None
            else (
                *_models("universe_actions", "instruments", Instrument),
                *_additional_instruments(),
            )
        ),
        alias_candidates=(
            aliases if aliases is not None else _models("universe_actions", "aliases", SymbolAlias)
        ),
        membership_candidates=(
            memberships
            if memberships is not None
            else _models("universe_actions", "memberships", UniverseMembership)
        ),
        action_candidates=tuple(
            TypeAdapter(CorporateAction).validate_python(item)
            for item in _indexed("universe_actions", "actions")
        ),
        bar_candidates=_bars() if bars is None else bars,
        filing_candidates=_models("financial_vintages", "filings", FinancialFiling),
        event_candidates=_models("events_social_macro", "events", NewsEvent),
        social_post_candidates=(),
        macro_observation_candidates=_models(
            "events_social_macro", "macro_observations", MacroObservation
        ),
    )


def _api() -> SimpleNamespace:
    """Load SIG-03 modules only after collection, so RED is an API failure."""

    try:
        import mytradingalpha.quant.features as features_module
        import mytradingalpha.quant.models as models_module
        import mytradingalpha.quant.signal as signal_module
        from mytradingalpha.contracts.signals import QuantSignal, QuantSignalStatus
        from mytradingalpha.quant.features import (
            FeatureConfiguration,
            FeatureObservation,
            FeatureSet,
            FeatureSpec,
            QuantInputError,
        )
        from mytradingalpha.quant.models import ModelArtifact, ModelFeature
        from mytradingalpha.quant.signal import QuantSignalModel
    except (ImportError, AttributeError) as exc:
        pytest.fail(f"SIG-03 API missing: {exc}")
    return SimpleNamespace(
        FeatureConfiguration=FeatureConfiguration,
        FeatureObservation=FeatureObservation,
        FeatureSet=FeatureSet,
        FeatureSpec=FeatureSpec,
        ModelArtifact=ModelArtifact,
        ModelFeature=ModelFeature,
        QuantInputError=QuantInputError,
        QuantSignal=QuantSignal,
        QuantSignalModel=QuantSignalModel,
        QuantSignalStatus=QuantSignalStatus,
        features_module=features_module,
        models_module=models_module,
        signal_module=signal_module,
    )


def _config_payload() -> dict[str, Any]:
    return deepcopy(_fixture()["configuration"])


def _model_payload() -> dict[str, Any]:
    return deepcopy(_fixture()["model"])


def _configuration(api: SimpleNamespace, **overrides: Any) -> Any:
    fields = _config_payload()
    fields["features"] = tuple(api.FeatureSpec.model_validate(item) for item in fields["features"])
    fields.update(overrides)
    return api.FeatureConfiguration.model_validate(fields)


def _artifact(api: SimpleNamespace, **overrides: Any) -> Any:
    fields = _model_payload()
    fields["features"] = tuple(api.ModelFeature.model_validate(item) for item in fields["features"])
    fields.update(overrides)
    return api.ModelArtifact.model_validate(fields)


def _matching_artifact(api: SimpleNamespace, configuration: Any) -> Any:
    model_features = []
    schema_payload = []
    for spec in configuration.features:
        payload = spec.model_dump(mode="json")
        schema_payload.append(payload)
        payload["weight"] = (
            "2.000000000000" if spec.feature_id == "close_return_1d" else "0.500000000000"
        )
        if not spec.required:
            payload["missing_value"] = "0.000000000000"
        model_features.append(api.ModelFeature.model_validate(payload))
    feature_schema_hash = _canonical_hash(
        HASH_DOMAINS["feature_schema"],
        sorted(schema_payload, key=lambda item: item["feature_id"]),
    )
    return api.ModelArtifact.create(
        model_id="model-artifact-matching-v1",
        model_version="v1",
        horizon_sessions=configuration.horizon_sessions,
        decimal_places=12,
        score_min=Decimal("-1"),
        score_max=Decimal("1"),
        feature_config_hash=configuration.content_hash,
        feature_schema_hash=feature_schema_hash,
        features=tuple(model_features),
        intercept=Decimal("0.000000000000"),
    )


def _features(
    api: SimpleNamespace,
    *,
    bundle: EvidenceBundle | None = None,
    configuration: Any | None = None,
    instrument_id: str | None = None,
) -> Any:
    scenario = _fixture()["scenario"]
    return api.FeatureSet.compute(
        bundle=bundle or _bundle(),
        configuration=configuration or _configuration(api),
        instrument_id=instrument_id or scenario["instrument_id"],
    )


def _score(
    api: SimpleNamespace,
    *,
    feature_set: Any | None = None,
    artifact: Any | None = None,
    run_id: str = "run-sig03-fixture",
) -> Any:
    return api.QuantSignalModel(artifact or _artifact(api)).score(
        feature_set or _features(api),
        run_id=run_id,
    )


def _status(value: Any) -> str:
    status = value.status
    return getattr(status, "value", status)


def _codes(value: Any) -> tuple[str, ...]:
    return tuple(getattr(item, "value", item) for item in value.reason_codes)


HASH_DOMAINS = {
    "feature_configuration": "mytradingalpha:sig03:feature-configuration:v1\0",
    "feature_schema": "mytradingalpha:sig03:feature-schema:v1\0",
    "feature_set": "mytradingalpha:sig03:feature-set:v1\0",
    "model_artifact": "mytradingalpha:sig03:model-artifact:v1\0",
    "quant_signal": "mytradingalpha:sig03:quant-signal:v1\0",
}


def _canonical_hash(domain: str, payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    canonical = domain.encode("utf-8") + encoded
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _assert_plain_data_model(model: Any) -> None:
    assert model.model_config.get("extra") == "forbid"
    assert model.model_config.get("frozen") is True


def _assert_no_authority_fields(model: Any) -> None:
    forbidden = {
        "target_weight",
        "target_weights",
        "allocation",
        "quantity",
        "order",
        "order_id",
        "broker",
        "broker_id",
        "portfolio",
        "risk_decision",
        "credentials",
        "overlay",
        "envelope",
        "variant_registry",
    }
    assert forbidden.isdisjoint(set(model.model_fields))


def test_quant_signal_wire_status_reason_and_shadow_authority_are_exact() -> None:
    api = _api()
    assert set(api.QuantSignal.model_fields) == {
        "schema_version",
        "signal_id",
        "run_id",
        "bundle_id",
        "bundle_hash",
        "instrument_id",
        "as_of",
        "horizon_sessions",
        "score",
        "decimal_places",
        "feature_ids",
        "feature_schema_hash",
        "feature_config_hash",
        "feature_hash",
        "model_id",
        "model_version",
        "model_hash",
        "missing_required_feature_ids",
        "missing_optional_feature_ids",
        "status",
        "reason_codes",
        "shadow_only",
    }
    assert {item.value for item in api.QuantSignalStatus} == STATUS_VALUES
    assert _codes(_score(api)) == ()
    signal = _score(api)
    assert signal.run_id == "run-sig03-fixture"
    bundle = _bundle()
    assert signal.bundle_id == bundle.bundle_id
    assert signal.bundle_hash == bundle.bundle_hash == _fixture()["scenario"]["expected_bundle_hash"]
    assert signal.decimal_places == 12
    assert signal.shadow_only is True
    assert signal.score == Decimal(_fixture()["scenario"]["expected_score"])
    assert signal.as_of == datetime(2024, 7, 2, 20, tzinfo=timezone.utc)
    assert signal.horizon_sessions == 1
    assert re.fullmatch(r"quant-signal:[0-9a-f]{64}", signal.signal_id)
    signal_payload = signal.model_dump(mode="json")
    signal_payload.pop("signal_id")
    assert _canonical_hash(HASH_DOMAINS["quant_signal"], signal_payload) == _fixture()["scenario"]["expected_signal_hash"]
    assert signal.signal_id == "quant-signal:" + _fixture()["scenario"]["expected_signal_hash"].removeprefix("sha256:")
    assert not hasattr(signal, "target_weight")
    _assert_no_authority_fields(api.QuantSignal)


def test_reason_enum_values_and_feature_set_wire_are_exact() -> None:
    api = _api()
    assert set(REASON_CODES) == set(_fixture()["scenario"]["reason_codes"])
    assert set(api.FeatureObservation.model_fields) == {
        "schema_version",
        "feature_id",
        "feature_version",
        "value",
        "required",
        "status",
        "reason_code",
        "as_of",
        "anchor_session",
        "lookback_sessions",
        "lookback_session",
        "latest_available_at",
        "source_bar_ids",
        "source_manifest_ids",
        "source_revisions",
    }
    assert set(api.FeatureSet.model_fields) == {
        "schema_version",
        "bundle_id",
        "bundle_hash",
        "instrument_id",
        "as_of",
        "knowledge_cutoff",
        "horizon_sessions",
        "configuration_id",
        "configuration_version",
        "feature_config_hash",
        "feature_schema_hash",
        "feature_hash",
        "observations",
        "missing_required_feature_ids",
        "missing_optional_feature_ids",
        "status",
        "reason_codes",
    }
    assert set(OBSERVATION_STATUS_VALUES) == set(_fixture()["scenario"]["observation_statuses"])
    _assert_plain_data_model(api.QuantSignal)
    _assert_plain_data_model(api.FeatureObservation)
    _assert_plain_data_model(api.FeatureSet)


def test_feature_spec_and_configuration_exact_fields_and_hashes() -> None:
    api = _api()
    exported_domains = {
        "feature_configuration": api.features_module.HASH_DOMAIN_FEATURE_CONFIGURATION,
        "feature_schema": api.features_module.HASH_DOMAIN_FEATURE_SCHEMA,
        "feature_set": api.features_module.HASH_DOMAIN_FEATURE_SET,
        "model_artifact": api.models_module.HASH_DOMAIN_MODEL_ARTIFACT,
        "quant_signal": api.signal_module.HASH_DOMAIN_QUANT_SIGNAL,
    }
    assert exported_domains == HASH_DOMAINS
    assert set(api.FeatureSpec.model_fields) == {
        "schema_version",
        "feature_id",
        "feature_version",
        "kind",
        "bar_source",
        "interval",
        "adjustment_basis",
        "adjustment_version",
        "lookback_sessions",
        "required",
    }
    assert set(api.FeatureConfiguration.model_fields) == {
        "schema_version",
        "configuration_id",
        "configuration_version",
        "universe_id",
        "calendar_id",
        "horizon_sessions",
        "features",
        "content_hash",
    }
    config = _configuration(api)
    assert config.content_hash == _config_payload()["content_hash"]
    config_semantic = _config_payload()
    config_hash = config_semantic.pop("content_hash")
    assert _canonical_hash(HASH_DOMAINS["feature_configuration"], config_semantic) == config_hash
    schema_semantic = sorted(
        config_semantic["features"], key=lambda item: item["feature_id"]
    )
    assert _canonical_hash(HASH_DOMAINS["feature_schema"], schema_semantic) == _model_payload()[
        "feature_schema_hash"
    ]
    assert tuple(item.feature_id for item in config.features) == (
        "close_return_1d",
        "close_return_2d_optional",
    )
    assert all(item.kind == "close_return" for item in config.features)
    assert all(item.interval == "1d" for item in config.features)
    assert all(item.adjustment_basis == AdjustmentBasis.UNADJUSTED for item in config.features)
    assert config.horizon_sessions == 1
    assert config.universe_id == "us-liquid-v1"
    assert config.calendar_id == "XNYS.synthetic.v1"
    with pytest.raises(ValidationError):
        api.FeatureSpec.model_validate(
            {**_config_payload()["features"][0], "kind": "volume_return"}
        )
    with pytest.raises(ValidationError):
        api.FeatureConfiguration.model_validate(
            {**_config_payload(), "unexpected_authority": "orders"}
        )
    with pytest.raises(ValidationError):
        api.FeatureConfiguration.model_validate(
            {**_config_payload(), "content_hash": "sha256:bad"}
        )


def test_feature_configuration_create_is_canonical_and_order_invariant() -> None:
    api = _api()
    config = _configuration(api)
    created = api.FeatureConfiguration.create(
        configuration_id=config.configuration_id,
        configuration_version=config.configuration_version,
        universe_id=config.universe_id,
        calendar_id=config.calendar_id,
        horizon_sessions=config.horizon_sessions,
        features=tuple(reversed(config.features)),
    )
    assert created.content_hash == config.content_hash
    assert tuple(item.feature_id for item in created.features) == (
        "close_return_1d",
        "close_return_2d_optional",
    )
    with pytest.raises((ValidationError, TypeError, ValueError)):
        api.FeatureConfiguration.create(
            configuration_id="config-bad",
            configuration_version="v1",
            universe_id="us-liquid-v1",
            calendar_id="XNYS.synthetic.v1",
            horizon_sessions=253,
            features=config.features,
        )


def test_observations_bind_exact_sessions_availability_and_sorted_provenance() -> None:
    api = _api()
    with pytest.raises(TypeError):
        api.FeatureSet.compute(
            bundle=_bundle(),
            configuration=_configuration(api),
            instrument_id="inst-survivor",
            as_of="2024-01-01T00:00:00Z",
            horizon_sessions=99,
        )
    feature_set = _features(api)
    assert feature_set.as_of == datetime(2024, 7, 2, 20, tzinfo=timezone.utc)
    assert feature_set.knowledge_cutoff == _bundle().knowledge_cutoff
    assert tuple(item.feature_id for item in feature_set.observations) == (
        "close_return_1d",
        "close_return_2d_optional",
    )
    required, optional = feature_set.observations
    assert required.value == Decimal("0.100000000000")
    assert optional.value == Decimal("0.210000000000")
    assert required.feature_version == "v1"
    assert optional.feature_version == "v1"
    assert required.required is True
    assert optional.required is False
    assert required.status == "available"
    assert optional.status == "available"
    assert required.reason_code is None
    assert optional.reason_code is None
    assert required.anchor_session == "2024-07-02"
    assert optional.anchor_session == "2024-07-02"
    assert required.lookback_sessions == 1
    assert optional.lookback_sessions == 2
    assert required.lookback_session == "2024-03-11"
    assert optional.lookback_session == "2024-03-08"
    assert required.latest_available_at == datetime(2024, 7, 2, 20, 1, tzinfo=timezone.utc)
    assert optional.latest_available_at == datetime(2024, 7, 2, 20, 1, tzinfo=timezone.utc)
    assert tuple(required.source_bar_ids) == (
        "bar-inst-survivor-synthetic-quant-bars-2024-03-11-unadjusted-none-r0",
        "bar-inst-survivor-synthetic-quant-bars-2024-07-02-unadjusted-none-r0",
    )
    assert tuple(required.source_manifest_ids) == (
        "synthetic-quant-bars-2024-03-11-r0",
        "synthetic-quant-bars-2024-07-02-r0",
    )
    assert tuple(required.source_revisions) == (0, 0)
    assert tuple(optional.source_bar_ids) == (
        "bar-inst-survivor-synthetic-optional-bars-2024-03-08-unadjusted-none-r0",
        "bar-inst-survivor-synthetic-optional-bars-2024-03-11-unadjusted-none-r0",
        "bar-inst-survivor-synthetic-optional-bars-2024-07-02-unadjusted-none-r0",
    )
    assert tuple(optional.source_manifest_ids) == (
        "synthetic-optional-bars-2024-03-08-r0",
        "synthetic-optional-bars-2024-03-11-r0",
        "synthetic-optional-bars-2024-07-02-r0",
    )
    assert tuple(optional.source_revisions) == (0, 0, 0)
    assert feature_set.missing_required_feature_ids == ()
    assert feature_set.missing_optional_feature_ids == ()
    assert _status(feature_set) == "valid"
    assert _codes(feature_set) == ()
    assert feature_set.feature_hash == _fixture()["scenario"]["expected_feature_hash"]
    feature_semantic = feature_set.model_dump(mode="json")
    feature_semantic.pop("feature_hash")
    assert _canonical_hash(HASH_DOMAINS["feature_set"], feature_semantic) == feature_set.feature_hash


def test_exact_session_lookback_has_no_gap_fallback() -> None:
    api = _api()
    missing_expected = _bundle(
        bars=tuple(
            item
            for item in _bars()
            if item.session_date != datetime(2024, 3, 11).date()
        )
    )
    feature_set = _features(api, bundle=missing_expected)
    assert _status(feature_set) == "invalid"
    assert _codes(feature_set) == ("insufficient_lookback", "required_feature_missing")
    assert feature_set.observations[0].value is None
    assert feature_set.observations[0].reason_code == "insufficient_lookback"
    assert feature_set.observations[0].lookback_session is None
    assert feature_set.observations[1].value is None
    assert feature_set.observations[1].reason_code == "insufficient_lookback"
    assert feature_set.observations[1].lookback_session is None


def test_availability_and_archive_realistic_replay_boundaries_are_distinct() -> None:
    api = _api()
    cutoff = "2024-07-02T20:02:00Z"
    availability = _bundle(cutoff=cutoff, replay_policy="availability")
    archive = _bundle(cutoff=cutoff, replay_policy="archive_realistic")
    assert availability.validate_sealed_bundle() is availability
    assert archive.validate_sealed_bundle() is archive
    available = _features(api, bundle=availability)
    archived = _features(api, bundle=archive)
    assert _status(available) == "valid"
    assert available.observations[0].value == Decimal("0.100000000000")
    assert _status(archived) == "invalid"
    assert "exact_session_bar_missing" in _codes(archived)
    assert archived.observations[0].value is None


def test_revision_and_cutoff_boundary_selection_stays_sealed_and_deterministic() -> None:
    api = _api()
    revised = _bar(
        "2024-07-02",
        "122.00",
        revision=1,
        available_offset_minutes=2,
        ingestion_offset_minutes=4,
    )
    revised_bundle = _bundle(
        bars=tuple(item for item in _bars() if not (
            item.manifest.source == "synthetic-quant-bars"
            and item.session_date == datetime(2024, 7, 2).date()
        )) + (revised,),
        cutoff="2024-07-02T20:04:00Z",
    )
    assert revised_bundle.validate_sealed_bundle() is revised_bundle
    revised_features = _features(api, bundle=revised_bundle)
    assert revised_features.observations[0].value == Decimal("0.109090909091")
    boundary = _bundle(cutoff="2024-07-02T20:01:00Z", replay_policy="availability")
    assert boundary.validate_sealed_bundle() is boundary
    assert _features(api, bundle=boundary).observations[0].value == Decimal("0.100000000000")
    with pytest.raises(api.QuantInputError):
        _features(api, bundle=boundary.model_copy(update={"bars": (*boundary.bars, revised)}))


def test_model_feature_and_model_artifact_plain_data_contract_is_exact() -> None:
    api = _api()
    assert set(api.ModelFeature.model_fields) == {
        "schema_version",
        "feature_id",
        "feature_version",
        "kind",
        "bar_source",
        "interval",
        "adjustment_basis",
        "adjustment_version",
        "lookback_sessions",
        "required",
        "weight",
        "missing_value",
    }
    assert set(api.ModelArtifact.model_fields) == {
        "schema_version",
        "model_id",
        "model_version",
        "horizon_sessions",
        "decimal_places",
        "score_min",
        "score_max",
        "feature_config_hash",
        "feature_schema_hash",
        "features",
        "intercept",
        "content_hash",
    }
    artifact = _artifact(api)
    assert artifact.content_hash == _model_payload()["content_hash"]
    model_semantic = _model_payload()
    model_hash = model_semantic.pop("content_hash")
    assert _canonical_hash(HASH_DOMAINS["model_artifact"], model_semantic) == model_hash
    assert artifact.decimal_places == 12
    assert artifact.score_min == Decimal("-1")
    assert artifact.score_max == Decimal("1")
    assert tuple(item.feature_id for item in artifact.features) == (
        "close_return_1d",
        "close_return_2d_optional",
    )
    assert artifact.features[0].missing_value is None
    assert artifact.features[1].missing_value == Decimal("0.000000000000")
    assert artifact.intercept == Decimal("0.000000000000")
    for model in (api.ModelFeature, api.ModelArtifact):
        _assert_plain_data_model(model)
    with pytest.raises(ValidationError):
        api.ModelFeature.model_validate(
            {**_model_payload()["features"][0], "missing_value": "0"}
        )
    with pytest.raises(ValidationError):
        api.ModelFeature.model_validate(
            {**_model_payload()["features"][1], "missing_value": None}
        )
    with pytest.raises(ValidationError):
        api.ModelArtifact.model_validate(
            {**_model_payload(), "features": _model_payload()["features"], "content_hash": "sha256:bad"}
        )


def test_model_artifact_create_hashes_plain_data_and_rejects_mismatch() -> None:
    api = _api()
    artifact = _artifact(api)
    created = api.ModelArtifact.create(
        model_id=artifact.model_id,
        model_version=artifact.model_version,
        horizon_sessions=artifact.horizon_sessions,
        decimal_places=artifact.decimal_places,
        score_min=artifact.score_min,
        score_max=artifact.score_max,
        feature_config_hash=artifact.feature_config_hash,
        feature_schema_hash=artifact.feature_schema_hash,
        features=tuple(reversed(artifact.features)),
        intercept=artifact.intercept,
    )
    assert created.content_hash == artifact.content_hash
    with pytest.raises((ValidationError, TypeError, ValueError)):
        api.ModelArtifact.create(
            model_id=artifact.model_id,
            model_version=artifact.model_version,
            horizon_sessions=artifact.horizon_sessions,
            decimal_places=artifact.decimal_places,
            score_min=artifact.score_min,
            score_max=artifact.score_max,
            feature_config_hash="sha256:bad",
            feature_schema_hash=artifact.feature_schema_hash,
            features=artifact.features,
            intercept=artifact.intercept,
        )


def test_score_is_exact_decimal_half_even_bounded_and_requires_run_id() -> None:
    api = _api()
    signal = _score(api)
    assert signal.score == Decimal("0.305000000000")
    assert signal.score.as_tuple().exponent == -12
    assert -1 <= signal.score <= 1
    with pytest.raises(TypeError):
        api.QuantSignalModel(_artifact(api)).score(_features(api))
    clipped = _artifact(
        api,
        features=tuple(
            item.model_copy(
                update={
                    "weight": "1000000000000.5"
                    if item.feature_id == "close_return_1d"
                    else item.weight
                }
            )
            for item in _artifact(api).features
        ),
        intercept="0.0000000000005",
    )
    clipped_signal = _score(api, artifact=clipped)
    assert clipped_signal.score == Decimal("1.000000000000")
    assert clipped_signal.decimal_places == 12


def test_float_bool_nonfinite_and_extreme_decimal_inputs_are_rejected() -> None:
    api = _api()
    for model, payload in (
        (api.FeatureSpec, _config_payload()["features"][0]),
        (api.ModelFeature, _model_payload()["features"][0]),
    ):
        invalid_values = {
            "lookback_sessions": (0.1, True, "NaN", "Infinity", "1e100000"),
            "required": (1, 0.1, "true", "NaN"),
            "weight": (0.1, True, "NaN", "Infinity", "1e100000"),
        }
        for field, values in invalid_values.items():
            if field not in payload:
                continue
            for value in values:
                candidate = {**payload, field: value}
                with pytest.raises(ValidationError):
                    model.model_validate(candidate)
    with pytest.raises(ValidationError):
        api.ModelArtifact.model_validate({**_model_payload(), "intercept": 0.1})


def test_fixed_resource_caps_are_not_caller_configurable() -> None:
    api = _api()
    assert api.features_module.MAX_FEATURES == 32
    assert api.features_module.MAX_LOOKBACK_SESSIONS == 252
    assert api.features_module.MAX_HORIZON_SESSIONS == 252
    assert api.features_module.MAX_BARS == 4096
    for module in (api.features_module, api.models_module, api.signal_module):
        for name in ("MAX_CANONICAL_BYTES", "MAX_IDENTIFIER_LENGTH", "MAX_NESTING_DEPTH"):
            assert isinstance(getattr(module, name), int)
            assert getattr(module, name) > 0
    with pytest.raises((ValidationError, TypeError, ValueError)):
        api.FeatureConfiguration.create(
            configuration_id="config-too-many",
            configuration_version="v1",
            universe_id="us-liquid-v1",
            calendar_id="XNYS.synthetic.v1",
            horizon_sessions=1,
            features=tuple(
                api.FeatureSpec.model_validate(
                    {
                        **_config_payload()["features"][0],
                        "feature_id": f"close_return_{i}",
                    }
                )
                for i in range(33)
            ),
        )
    with pytest.raises((ValidationError, TypeError, ValueError)):
        api.FeatureSpec.model_validate(
            {**_config_payload()["features"][0], "lookback_sessions": 253}
        )
    with pytest.raises((ValidationError, TypeError, ValueError)):
        api.FeatureConfiguration.create(
            configuration_id="config-horizon-too-large",
            configuration_version="v1",
            universe_id="us-liquid-v1",
            calendar_id="XNYS.synthetic.v1",
            horizon_sessions=253,
            features=_configuration(api).features,
        )
    with pytest.raises((ValidationError, TypeError, ValueError)):
        api.FeatureSpec.model_validate(
            {**_config_payload()["features"][0], "feature_id": "x" * 129}
        )
    baseline = _bundle()
    hostile_bars = (*baseline.bars, *([baseline.bars[0]] * 4091))
    with pytest.raises(api.QuantInputError) as exc_info:
        _features(api, bundle=baseline.model_copy(update={"bars": hostile_bars}))
    assert "hostile" not in str(exc_info.value)
    for value in ("NaN", "Infinity", "-Infinity", "1e100000"):
        with pytest.raises((ValidationError, ValueError)) as exc_info:
            api.ModelArtifact.model_validate({**_model_payload(), "intercept": value})
        assert value not in str(exc_info.value)


def test_required_invalid_optional_degraded_and_missing_ids_are_distinct() -> None:
    api = _api()
    required_missing_spec = api.FeatureSpec.model_validate(
        {**_config_payload()["features"][0], "bar_source": "missing-required-source"}
    )
    required_config = api.FeatureConfiguration.create(
        configuration_id="config-required-missing",
        configuration_version="v1",
        universe_id="us-liquid-v1",
        calendar_id="XNYS.synthetic.v1",
        horizon_sessions=1,
        features=(required_missing_spec, _configuration(api).features[1]),
    )
    invalid = _features(api, configuration=required_config)
    assert _status(invalid) == "invalid"
    assert invalid.missing_required_feature_ids == ("close_return_1d",)
    assert "required_feature_missing" in _codes(invalid)
    invalid_signal = _score(
        api,
        feature_set=invalid,
        artifact=_matching_artifact(api, required_config),
    )
    assert _status(invalid_signal) == "invalid"
    assert invalid_signal.score is None
    assert invalid_signal.missing_required_feature_ids == ("close_return_1d",)
    assert "required_feature_missing" in _codes(invalid_signal)
    optional_specs = list(_configuration(api).features)
    optional_specs[1] = optional_specs[1].model_copy(
        update={"bar_source": "missing-optional-source"}
    )
    optional_config = api.FeatureConfiguration.create(
        configuration_id="config-optional-missing",
        configuration_version="v1",
        universe_id="us-liquid-v1",
        calendar_id="XNYS.synthetic.v1",
        horizon_sessions=1,
        features=tuple(optional_specs),
    )
    degraded = _features(api, configuration=optional_config)
    assert _status(degraded) == "degraded"
    assert degraded.missing_required_feature_ids == ()
    assert degraded.missing_optional_feature_ids == ("close_return_2d_optional",)
    assert "optional_feature_missing" in _codes(degraded)
    degraded_signal = _score(
        api,
        feature_set=degraded,
        artifact=_matching_artifact(api, optional_config),
    )
    assert _status(degraded_signal) == "degraded"
    assert degraded_signal.score == Decimal("0.200000000000")
    assert degraded_signal.missing_required_feature_ids == ()
    assert degraded_signal.missing_optional_feature_ids == ("close_return_2d_optional",)
    assert "optional_feature_missing" in _codes(degraded_signal)


def test_reason_codes_remain_stable_without_manufacturing_invalid_bundle_states() -> None:
    api = _api()
    baseline = _bundle()
    assert set(REASON_CODES) == set(_fixture()["scenario"]["reason_codes"])
    assert _status(_features(api, instrument_id="not-in-bundle")) == "invalid"
    assert "instrument_not_in_bundle" in _codes(_features(api, instrument_id="not-in-bundle"))
    assert "instrument_inactive_as_of" in _codes(_features(api, instrument_id="inst-acme"))
    no_membership = tuple(
        item for item in baseline.memberships if item.instrument_id != "inst-survivor"
    )
    result = _features(api, bundle=_bundle(memberships=no_membership))
    assert _status(result) == "invalid"
    assert "instrument_not_in_universe" in _codes(result)
    calendar_config = api.FeatureConfiguration.create(
        configuration_id="config-calendar-mismatch",
        configuration_version="v1",
        universe_id="us-liquid-v1",
        calendar_id="other-calendar",
        horizon_sessions=1,
        features=_configuration(api).features,
    )
    calendar_result = _features(api, configuration=calendar_config)
    assert _status(calendar_result) == "invalid"
    assert "calendar_session_unavailable" in _codes(calendar_result)
    other_series = (*baseline.bars, _bar(
        "2024-07-02",
        "121.00",
        source="unrelated-bars",
        adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED,
        adjustment_version="provider-v1",
    ))
    unaffected = _features(api, bundle=_bundle(bars=other_series))
    assert _status(unaffected) == "valid"
    absent_source = api.FeatureConfiguration.create(
        configuration_id="config-absent-source",
        configuration_version="v1",
        universe_id="us-liquid-v1",
        calendar_id="XNYS.synthetic.v1",
        horizon_sessions=1,
        features=(
            _configuration(api).features[0].model_copy(update={"bar_source": "absent-source"}),
            _configuration(api).features[1],
        ),
    )
    absent = _features(api, configuration=absent_source)
    assert _status(absent) == "invalid"
    assert "exact_session_bar_missing" in _codes(absent)
    with pytest.raises(api.QuantInputError):
        _features(api, bundle=baseline.model_copy(update={"memberships": no_membership + (baseline.memberships[0],)}))
    with pytest.raises(api.QuantInputError):
        _features(api, bundle=baseline.model_copy(update={"bars": (*baseline.bars, baseline.bars[0])}))


def test_config_and_model_hash_mismatch_is_generic_quant_input_error() -> None:
    api = _api()
    config = _configuration(api)
    feature_set = _features(api)
    bad_artifact = _model_payload()
    bad_artifact["feature_config_hash"] = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    with pytest.raises(api.QuantInputError):
        api.ModelArtifact.model_validate(bad_artifact)
    with pytest.raises(ValidationError):
        api.ModelArtifact.model_validate({**_model_payload(), "content_hash": "sha256:bad"})
    with pytest.raises(api.QuantInputError):
        api.QuantSignalModel(_artifact(api)).score(
            feature_set.model_copy(update={"feature_config_hash": "sha256:bad"}),
            run_id="run-sig03-fixture",
        )
    assert feature_set.feature_config_hash == config.content_hash


def test_hostile_subclasses_callbacks_custom_containers_and_deep_mutation_fail_closed() -> None:
    api = _api()

    class FeatureSpecSubclass(api.FeatureSpec):
        pass

    class CallbackDict(dict[str, Any]):
        def __iter__(self):
            raise AssertionError("custom container executed")

    callback_state = {"called": False}

    class HostileBundle(EvidenceBundle):
        def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            callback_state["called"] = True
            raise AssertionError("hostile model_dump executed")

    with pytest.raises((ValidationError, TypeError, ValueError)):
        api.FeatureSpec.model_validate(
            FeatureSpecSubclass.model_validate(_config_payload()["features"][0])
        )
    with pytest.raises((ValidationError, TypeError, ValueError, AssertionError)):
        api.ModelArtifact.model_validate(CallbackDict(_model_payload()))
    with pytest.raises((ValidationError, TypeError, ValueError, AssertionError)):
        api.FeatureConfiguration.model_validate(
            {**_config_payload(), "features": CallbackDict({"feature": _config_payload()["features"][0]})}
        )
    hostile_bundle = HostileBundle.model_validate(_bundle().model_dump(mode="python"))
    with pytest.raises(api.QuantInputError) as exc_info:
        _features(api, bundle=hostile_bundle)
    assert not callback_state["called"]
    assert "hostile" not in str(exc_info.value)
    tampered_bundle = _bundle()
    object.__setattr__(tampered_bundle.bars[0], "close", Decimal("999.00"))
    with pytest.raises(api.QuantInputError):
        _features(api, bundle=tampered_bundle)
    tampered_manifest_bundle = _bundle()
    object.__setattr__(tampered_manifest_bundle.bars[0].manifest, "source", "secret-provider")
    with pytest.raises(api.QuantInputError) as exc_info:
        _features(api, bundle=tampered_manifest_bundle)
    assert "secret-provider" not in str(exc_info.value)
    feature_set = _features(api)
    hash_before = feature_set.feature_hash
    with pytest.raises((TypeError, ValidationError, AttributeError)):
        feature_set.observations[0].value = Decimal("9")
    assert feature_set.feature_hash == hash_before
    artifact = _artifact(api)
    artifact_hash = artifact.content_hash
    object.__setattr__(artifact.features[0], "weight", Decimal("999"))
    with pytest.raises(api.QuantInputError):
        api.QuantSignalModel(artifact).score(feature_set, run_id="run-sig03-fixture")
    assert artifact.content_hash == artifact_hash
    with pytest.raises((TypeError, ValidationError, AttributeError)):
        feature_set.observations[0].source_bar_ids[0] = "mutated"
    assert feature_set.feature_hash == hash_before


def test_unicode_surrogates_and_secret_bearing_identifiers_are_rejected_and_not_serialized() -> None:
    api = _api()
    for identifier in ("bad\ud800", "api-key-123", "secret-token", "password"):
        with pytest.raises(ValidationError):
            api.FeatureSpec.model_validate(
                {**_config_payload()["features"][0], "feature_id": identifier}
            )
    with pytest.raises(ValidationError):
        api.ModelArtifact.model_validate({**_model_payload(), "model_id": "secret\udfff"})
    serialized = _score(api).model_dump_json()
    assert "api-key" not in serialized
    assert "password" not in serialized


def test_repeated_concurrent_subprocess_and_decimal_context_results_are_identical() -> None:
    api = _api()
    baseline = _score(api).model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=8) as pool:
        outputs = list(pool.map(lambda _: _score(api).model_dump(mode="json"), range(16)))
    assert outputs == [baseline] * 16
    old_precision = getcontext().prec
    try:
        getcontext().prec = 7
        low_precision = _score(api).model_dump(mode="json")
    finally:
        getcontext().prec = old_precision
    assert low_precision == baseline
    script = (
        "from tests.productionization.quant.test_signal import _api, _score; "
        "print(_score(_api()).model_dump_json())"
    )
    child = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONHASHSEED": "random"},
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(child.stdout) == baseline


def test_network_dns_filesystem_path_subprocess_provider_and_clock_are_not_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    feature_set = _features(api)

    def deny(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("SIG-03 side effect is forbidden")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(socket, "gethostbyname", deny)
    artifact = _artifact(api)
    monkeypatch.setattr(builtins, "open", deny)
    monkeypatch.setattr(Path, "open", deny)
    monkeypatch.setattr(Path, "read_text", deny)
    monkeypatch.setattr(subprocess, "run", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    for module in (api.features_module, api.models_module, api.signal_module):
        for name in ("clock", "now", "utcnow", "provider", "model_provider", "data_provider"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, deny)
    first = api.QuantSignalModel(artifact).score(feature_set, run_id="run-sig03-fixture")
    second = api.QuantSignalModel(artifact).score(feature_set, run_id="run-sig03-fixture")
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_static_quant_dependency_direction_and_no_later_authority() -> None:
    paths = [
        *(ROOT / "mytradingalpha" / "quant").glob("*.py"),
        ROOT / "mytradingalpha" / "contracts" / "signals.py",
    ]
    forbidden_modules = {
        "mytradingalpha.research",
        "mytradingalpha.portfolio",
        "mytradingalpha.risk",
        "mytradingalpha.backtest",
        "mytradingalpha.execution",
        "tradingagents",
        "socket",
        "requests",
        "urllib",
        "subprocess",
        "pickle",
        "cloudpickle",
        "os",
        "pathlib",
        "time",
        "datetime",
        "random",
        "importlib",
    }
    forbidden_names = {
        "target_weight",
        "target_weights",
        "allocation",
        "quantity",
        "order_id",
        "broker",
        "portfolio",
        "risk_decision",
        "LLMOverlay",
        "SignalEnvelope",
        "VariantRegistry",
    }
    for path in paths:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        path_forbidden_modules = forbidden_modules
        if path.parent.name == "contracts":
            path_forbidden_modules = forbidden_modules - {"datetime"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name not in path_forbidden_modules for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in path_forbidden_modules
            elif isinstance(node, ast.Name):
                assert node.id not in forbidden_names
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_names
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {
                    "open",
                    "eval",
                    "exec",
                    "compile",
                    "__import__",
                }


def _rekey_signal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(payload)
    payload.pop("signal_id", None)
    payload["signal_id"] = "quant-signal:" + _canonical_hash(
        HASH_DOMAINS["quant_signal"],
        {key: value for key, value in payload.items() if key != "signal_id"},
    ).removeprefix("sha256:")
    return payload


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("intercept", "0.000000000001"),
        ("horizon_sessions", 2),
    ),
)
def test_serialized_model_artifact_semantic_change_never_recomputes_old_hash(
    field: str,
    value: object,
) -> None:
    api = _api()
    payload = _model_payload()
    payload[field] = value
    with pytest.raises(api.QuantInputError):
        api.ModelArtifact.model_validate(payload)


def test_model_feature_schema_hash_binding_has_no_valid_sha_fallback() -> None:
    api = _api()
    feature_set = _features(api)
    artifact = _artifact(api)
    full_schema_hash = api.models_module._model_feature_full_hash(artifact.features)
    payload = feature_set.model_dump(mode="json")
    payload["feature_schema_hash"] = full_schema_hash
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    tampered = api.FeatureSet.model_validate(payload)
    with pytest.raises(api.QuantInputError):
        api.QuantSignalModel(artifact).score(tampered, run_id="run-sig03-fixture")


def test_intrinsic_signal_status_and_direct_score_invariants_are_fail_closed() -> None:
    api = _api()
    valid = _score(api)
    base = valid.model_dump(mode="json")
    invalid_payload = _rekey_signal_payload(
        {
            **base,
            "status": "invalid",
            "score": "0.100000000000",
            "reason_codes": ["required_feature_missing"],
        }
    )
    with pytest.raises(ValidationError):
        api.QuantSignal.model_validate(invalid_payload)
    valid_missing = _rekey_signal_payload(
        {**base, "missing_optional_feature_ids": ["close_return_2d_optional"]}
    )
    with pytest.raises(ValidationError):
        api.QuantSignal.model_validate(valid_missing)
    degraded = _rekey_signal_payload(
        {
            **base,
            "status": "degraded",
            "missing_optional_feature_ids": ["close_return_2d_optional"],
            "reason_codes": ["optional_feature_missing"],
        }
    )
    assert api.QuantSignal.model_validate(degraded).status.value == "degraded"
    invalid = _rekey_signal_payload(
        {
            **base,
            "status": "invalid",
            "score": None,
            "reason_codes": ["required_feature_missing"],
            "missing_required_feature_ids": ["close_return_1d"],
        }
    )
    assert api.QuantSignal.model_validate(invalid).score is None
    for score in (0.1, True, "NaN", "Infinity", "1.1", "0.1"):
        with pytest.raises(ValidationError):
            api.QuantSignal.model_validate(_rekey_signal_payload({**base, "score": score}))
    mismatch = dict(base)
    mismatch["signal_id"] = "quant-signal:" + "0" * 64
    with pytest.raises(ValidationError):
        api.QuantSignal.model_validate(mismatch)


def test_observation_and_feature_set_intrinsic_consistency_is_enforced() -> None:
    api = _api()
    observation = _features(api).observations[0].model_dump(mode="json")
    for mutation in (
        {"status": "available", "value": None},
        {"status": "available", "reason_code": "required_feature_missing"},
        {"status": "available", "lookback_session": None},
        {"status": "missing", "value": "0.100000000000"},
        {"status": "missing", "source_bar_ids": ["bar-only"]},
    ):
        with pytest.raises(ValidationError):
            api.FeatureObservation.model_validate({**observation, **mutation})
    feature_set = _features(api)
    duplicate = feature_set.model_dump(mode="json")
    duplicate["observations"] = [*duplicate["observations"], duplicate["observations"][0]]
    duplicate.pop("feature_hash")
    duplicate["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], duplicate)
    with pytest.raises(ValidationError):
        api.FeatureSet.model_validate(duplicate)
    mismatch = feature_set.model_dump(mode="json")
    mismatch["missing_required_feature_ids"] = ["close_return_1d"]
    mismatch.pop("feature_hash")
    mismatch["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], mismatch)
    with pytest.raises(ValidationError):
        api.FeatureSet.model_validate(mismatch)


def test_exact_tuple_subclass_and_nested_hostile_models_are_rejected_without_callbacks() -> None:
    api = _api()

    class EvilTuple(tuple):
        def __len__(self) -> int:
            raise AssertionError("tuple callback executed")

        def __iter__(self):
            raise AssertionError("tuple callback executed")

    bundle = _bundle()
    object.__setattr__(bundle, "bars", EvilTuple(tuple(bundle.bars)))
    with pytest.raises(api.QuantInputError) as exc_info:
        _features(api, bundle=bundle)
    assert "tuple callback" not in str(exc_info.value)

    class EvilFeatureSpec(api.FeatureSpec):
        pass

    config = _configuration(api)
    object.__setattr__(
        config,
        "features",
        (
            EvilFeatureSpec.model_validate(config.features[0].model_dump(mode="python")),
            config.features[1],
        ),
    )
    with pytest.raises(api.QuantInputError):
        _features(api, configuration=config)

    class CanaryKey(str):
        def __hash__(self) -> int:
            return hash(str(self))

        def __eq__(self, other: object) -> bool:
            raise AssertionError("hostile key comparison executed")

    artifact = _artifact(api)
    storage = dict(object.__getattribute__(artifact, "__dict__"))
    storage[CanaryKey("model_id")] = storage.pop("model_id")
    object.__setattr__(artifact, "__dict__", storage)
    with pytest.raises(api.QuantInputError) as exc_info:
        api.QuantSignalModel(artifact)
    assert "hostile key" not in str(exc_info.value)


def test_decimal_subclasses_are_rejected_and_negative_zero_is_normalized() -> None:
    api = _api()

    class DecimalSubclass(Decimal):
        pass

    with pytest.raises(ValidationError):
        api.ModelFeature.model_validate(
            {**_model_payload()["features"][0], "weight": DecimalSubclass("1")}
        )
    feature = api.ModelFeature.model_validate(
        {**_model_payload()["features"][0], "weight": "-0.000000000000"}
    )
    assert feature.weight == Decimal("0.000000000000")
    assert feature.weight.as_tuple().sign == 0

"""SIG-03 RED contract for deterministic close-return features and QuantSignal.

The SIG-03 modules are deliberately imported only from test execution.  The
tests therefore collect on the dependency-valid base and fail for the expected
missing API until the production implementation is added.
"""

from __future__ import annotations

import ast
import base64
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
from decimal import ROUND_UP, Decimal, Inexact, Rounded, getcontext, setcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mytradingalpha.data.actions import CorporateAction
from mytradingalpha.data.bars import AdjustmentBasis, BarFinality, DailyBar
from mytradingalpha.data.bundle import (
    EvidenceBundle,
    EvidenceDomain,
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
    payload["coverage_ranges"][1]["start"] = "2024-06-28"
    payload["closures"].extend(
        (
            {
                "schema_version": "v1",
                "calendar_id": "XNYS.synthetic.v1",
                "date": "2024-06-29",
                "reason": "weekend",
            },
            {
                "schema_version": "v1",
                "calendar_id": "XNYS.synthetic.v1",
                "date": "2024-06-30",
                "reason": "weekend",
            },
        )
    )
    payload["closures"].sort(key=lambda item: item["date"])
    payload["sessions"].extend(
        (
            {
                "schema_version": "v1",
                "calendar_id": "XNYS.synthetic.v1",
                "session_date": "2024-06-28",
                "open_at": "2024-06-28T13:30:00Z",
                "close_at": "2024-06-28T20:00:00Z",
                "session_type": "regular",
            },
            {
                "schema_version": "v1",
                "calendar_id": "XNYS.synthetic.v1",
                "session_date": "2024-07-01",
                "open_at": "2024-07-01T13:30:00Z",
                "close_at": "2024-07-01T20:00:00Z",
                "session_type": "regular",
            },
        )
    )
    payload["sessions"].sort(key=lambda item: item["session_date"])
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


def _gapped_quant_calendar() -> TradingCalendar:
    """Independent source calendar with a deliberately unverified spring gap."""

    return TradingCalendar.model_validate(
        {
            "schema_version": "v1",
            "calendar_id": "XNYS.synthetic.v1",
            "timezone": "America/New_York",
            "coverage_start": "2024-03-08",
            "coverage_end": "2024-07-02",
            "coverage_ranges": (
                {"start": "2024-03-08", "end": "2024-03-11"},
                {"start": "2024-07-02", "end": "2024-07-02"},
            ),
            "closures": (
                {
                    "schema_version": "v1",
                    "calendar_id": "XNYS.synthetic.v1",
                    "date": "2024-03-09",
                    "reason": "weekend",
                },
                {
                    "schema_version": "v1",
                    "calendar_id": "XNYS.synthetic.v1",
                    "date": "2024-03-10",
                    "reason": "weekend",
                },
            ),
            "schedule": (
                {
                    "schema_version": "v1",
                    "calendar_id": "XNYS.synthetic.v1",
                    "session_date": "2024-03-08",
                    "open_at": "2024-03-08T14:30:00Z",
                    "close_at": "2024-03-08T21:00:00Z",
                    "session_type": "regular",
                },
                {
                    "schema_version": "v1",
                    "calendar_id": "XNYS.synthetic.v1",
                    "session_date": "2024-03-11",
                    "open_at": "2024-03-11T13:30:00Z",
                    "close_at": "2024-03-11T20:00:00Z",
                    "session_type": "regular",
                },
                {
                    "schema_version": "v1",
                    "calendar_id": "XNYS.synthetic.v1",
                    "session_date": "2024-07-02",
                    "open_at": "2024-07-02T13:30:00Z",
                    "close_at": "2024-07-02T20:00:00Z",
                    "session_type": "regular",
                },
            ),
        }
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
            ("2024-06-28", "100.00"),
            ("2024-07-01", "110.00"),
            ("2024-07-02", "121.00"),
        )
    )
    optional = tuple(
        _bar(session, close, source="synthetic-optional-bars")
        for session, close in (
            ("2024-03-08", "200.00"),
            ("2024-03-11", "220.00"),
            ("2024-06-28", "200.00"),
            ("2024-07-01", "220.00"),
            ("2024-07-02", "242.00"),
        )
    )
    return (*required, *optional)


def _gapped_bars() -> tuple[DailyBar, ...]:
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
    calendar: TradingCalendar | None = None,
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
        calendar=_calendar() if calendar is None else calendar,
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
        schema_payload.append(deepcopy(payload))
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
    bundle: EvidenceBundle | None = None,
    configuration: Any | None = None,
) -> Any:
    sealed_bundle = bundle or _bundle()
    sealed_configuration = configuration or _configuration(api)
    return api.QuantSignalModel(artifact or _artifact(api)).score(
        feature_set
        or _features(
            api,
            bundle=sealed_bundle,
            configuration=sealed_configuration,
        ),
        run_id=run_id,
        bundle=sealed_bundle,
        configuration=sealed_configuration,
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


def _intended_feature_payload_with_session_lineage(api: SimpleNamespace) -> dict[str, Any]:
    """Build the intended wire payload independently of production hashing code."""

    payload = _features(api).model_dump(mode="json")
    expected_dates = {
        "close_return_1d": ["2024-07-01", "2024-07-02"],
        "close_return_2d_optional": [
            "2024-06-28",
            "2024-07-01",
            "2024-07-02",
        ],
    }
    for observation in payload["observations"]:
        observation["source_session_dates"] = expected_dates[observation["feature_id"]]
    payload.pop("feature_hash")
    return payload


def _intended_signal_payload_with_session_lineage(api: SimpleNamespace) -> dict[str, Any]:
    """Bind the independently computed feature hash into the intended signal payload."""

    payload = _score(api).model_dump(mode="json")
    payload.pop("signal_id")
    payload["feature_hash"] = _canonical_hash(
        HASH_DOMAINS["feature_set"],
        _intended_feature_payload_with_session_lineage(api),
    )
    return payload


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
    intended_signal_payload = _intended_signal_payload_with_session_lineage(api)
    assert _canonical_hash(
        HASH_DOMAINS["quant_signal"], intended_signal_payload
    ) == _fixture()["scenario"]["expected_signal_hash"]
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
        "source_session_dates",
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
    assert required.lookback_session == "2024-07-01"
    assert optional.lookback_session == "2024-06-28"
    assert required.latest_available_at == datetime(2024, 7, 2, 20, 1, tzinfo=timezone.utc)
    assert optional.latest_available_at == datetime(2024, 7, 2, 20, 1, tzinfo=timezone.utc)
    assert tuple(required.source_bar_ids) == (
        "bar-inst-survivor-synthetic-quant-bars-2024-07-01-unadjusted-none-r0",
        "bar-inst-survivor-synthetic-quant-bars-2024-07-02-unadjusted-none-r0",
    )
    assert tuple(required.source_manifest_ids) == (
        "synthetic-quant-bars-2024-07-01-r0",
        "synthetic-quant-bars-2024-07-02-r0",
    )
    assert tuple(required.source_revisions) == (0, 0)
    assert tuple(required.source_session_dates) == (
        "2024-07-01",
        "2024-07-02",
    )
    assert tuple(optional.source_bar_ids) == (
        "bar-inst-survivor-synthetic-optional-bars-2024-06-28-unadjusted-none-r0",
        "bar-inst-survivor-synthetic-optional-bars-2024-07-01-unadjusted-none-r0",
        "bar-inst-survivor-synthetic-optional-bars-2024-07-02-unadjusted-none-r0",
    )
    assert tuple(optional.source_manifest_ids) == (
        "synthetic-optional-bars-2024-06-28-r0",
        "synthetic-optional-bars-2024-07-01-r0",
        "synthetic-optional-bars-2024-07-02-r0",
    )
    assert tuple(optional.source_revisions) == (0, 0, 0)
    assert tuple(optional.source_session_dates) == (
        "2024-06-28",
        "2024-07-01",
        "2024-07-02",
    )
    assert feature_set.missing_required_feature_ids == ()
    assert feature_set.missing_optional_feature_ids == ()
    assert _status(feature_set) == "valid"
    assert _codes(feature_set) == ()
    intended_payload = _intended_feature_payload_with_session_lineage(api)
    assert _canonical_hash(
        HASH_DOMAINS["feature_set"], intended_payload
    ) == _fixture()["scenario"]["expected_feature_hash"]
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
            if item.session_date != datetime(2024, 7, 1).date()
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
        api.QuantSignalModel(_artifact(api)).score(
            _features(api),
            bundle=_bundle(),
            configuration=_configuration(api),
        )
    base_artifact = _artifact(api)
    clipped = api.ModelArtifact.create(
        model_id=base_artifact.model_id,
        model_version=base_artifact.model_version,
        horizon_sessions=base_artifact.horizon_sessions,
        decimal_places=base_artifact.decimal_places,
        score_min=base_artifact.score_min,
        score_max=base_artifact.score_max,
        feature_config_hash=base_artifact.feature_config_hash,
        feature_schema_hash=base_artifact.feature_schema_hash,
        features=tuple(
            item.model_copy(
                update={
                    "weight": "1000000000000.5"
                    if item.feature_id == "close_return_1d"
                    else item.weight
                }
            )
            for item in base_artifact.features
        ),
        intercept=Decimal("0.0000000000005"),
    )
    clipped_signal = _score(api, artifact=clipped)
    assert clipped_signal.score == Decimal("1.000000000000")
    assert clipped_signal.decimal_places == 12


def test_score_requires_exact_sealed_bundle_and_feature_configuration() -> None:
    api = _api()
    bundle = _bundle()
    configuration = _configuration(api)
    feature_set = _features(api, bundle=bundle, configuration=configuration)
    model = api.QuantSignalModel(_artifact(api))
    signal = model.score(
        feature_set,
        run_id="run-explicit-score-provenance",
        bundle=bundle,
        configuration=configuration,
    )
    assert signal.bundle_hash == bundle.bundle_hash
    assert signal.feature_config_hash == configuration.content_hash

    with pytest.raises(TypeError):
        model.score(
            feature_set,
            run_id="run-missing-score-bundle",
            configuration=configuration,
        )
    with pytest.raises(TypeError):
        model.score(
            feature_set,
            run_id="run-missing-score-configuration",
            bundle=bundle,
        )
    for wrong_bundle, wrong_configuration in (
        (object(), configuration),
        (bundle, object()),
    ):
        with pytest.raises(api.QuantInputError):
            model.score(
                feature_set,
                run_id="run-wrong-score-provenance",
                bundle=wrong_bundle,
                configuration=wrong_configuration,
            )

    tampered_bundle = _bundle()
    object.__setattr__(tampered_bundle, "bundle_id", "bundle-tampered-after-seal")
    with pytest.raises(api.QuantInputError):
        model.score(
            feature_set,
            run_id="run-tampered-score-bundle",
            bundle=tampered_bundle,
            configuration=configuration,
        )
    tampered_configuration = _configuration(api)
    object.__setattr__(
        tampered_configuration,
        "configuration_id",
        "configuration-tampered-after-hash",
    )
    with pytest.raises(api.QuantInputError):
        model.score(
            feature_set,
            run_id="run-tampered-score-configuration",
            bundle=bundle,
            configuration=tampered_configuration,
        )


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
    with pytest.raises(api.QuantInputError):
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
        configuration=required_config,
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
        configuration=optional_config,
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
            bundle=_bundle(),
            configuration=config,
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
        api.QuantSignalModel(artifact).score(
            feature_set,
            run_id="run-sig03-fixture",
            bundle=_bundle(),
            configuration=_configuration(api),
        )
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
    bundle = _bundle()
    configuration = _configuration(api)
    feature_set = _features(api, bundle=bundle, configuration=configuration)

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
    first = api.QuantSignalModel(artifact).score(
        feature_set,
        run_id="run-sig03-fixture",
        bundle=bundle,
        configuration=configuration,
    )
    second = api.QuantSignalModel(artifact).score(
        feature_set,
        run_id="run-sig03-fixture",
        bundle=bundle,
        configuration=configuration,
    )
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
    full_schema_payload = []
    for feature in artifact.features:
        payload = feature.model_dump(mode="json", exclude_none=True)
        payload["weight"] = format(feature.weight, ".12f")
        if feature.missing_value is not None:
            payload["missing_value"] = format(feature.missing_value, ".12f")
        full_schema_payload.append(payload)
    full_schema_hash = _canonical_hash(
        HASH_DOMAINS["feature_schema"],
        full_schema_payload,
    )
    payload = feature_set.model_dump(mode="json")
    payload["feature_schema_hash"] = full_schema_hash
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    tampered = api.FeatureSet.model_validate(payload)
    with pytest.raises(api.QuantInputError):
        api.QuantSignalModel(artifact).score(
            tampered,
            run_id="run-sig03-fixture",
            bundle=_bundle(),
            configuration=_configuration(api),
        )


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


def test_sensitive_identifier_canary_is_rejected_without_error_or_canonical_echo() -> None:
    api = _api()
    canary = "api-key-CANARY-DO-NOT-ECHO"
    cases = (
        (api.FeatureSpec, {**_config_payload()["features"][0], "feature_id": canary}),
        (api.FeatureConfiguration, {**_config_payload(), "configuration_id": canary}),
        (api.FeatureObservation, {**_features(api).observations[0].model_dump(mode="json"), "feature_id": canary}),
        (api.FeatureSet, {**_features(api).model_dump(mode="json"), "instrument_id": canary}),
        (api.ModelFeature, {**_model_payload()["features"][0], "feature_id": canary}),
        (api.ModelArtifact, {**_model_payload(), "model_id": canary}),
        (api.QuantSignal, {**_score(api).model_dump(mode="json"), "run_id": canary}),
    )
    for model, payload in cases:
        original_payload = deepcopy(payload)
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate(payload)
        assert canary not in str(exc_info.value)
        assert payload == original_payload


def test_feature_compute_ignores_hostile_ambient_decimal_contexts() -> None:
    api = _api()
    baseline = _features(api).model_dump(mode="json")

    def compute_with_context(*, precision: int, hostile: bool) -> dict[str, Any]:
        previous = getcontext().copy()
        try:
            context = getcontext()
            context.prec = precision
            context.rounding = ROUND_UP
            context.traps[Inexact] = hostile
            context.traps[Rounded] = hostile
            context.clear_flags()
            return _features(api).model_dump(mode="json")
        finally:
            setcontext(previous)

    assert compute_with_context(precision=28, hostile=False) == baseline
    assert compute_with_context(precision=7, hostile=False) == baseline
    assert compute_with_context(precision=1, hostile=True) == baseline
    assert compute_with_context(precision=28, hostile=False) == baseline
    assert compute_with_context(precision=1, hostile=True) == baseline
    contexts = tuple((1, True) if index % 2 else (7, False) for index in range(16))
    with ThreadPoolExecutor(max_workers=8) as pool:
        outputs = list(
            pool.map(
                lambda settings: compute_with_context(
                    precision=settings[0], hostile=settings[1]
                ),
                contexts,
            )
        )
    assert outputs == [baseline] * len(contexts)


def test_public_plain_dict_boundaries_reject_hostile_string_keys_without_callbacks() -> None:
    api = _api()
    state = {"armed": False, "calls": 0}

    class HostileKey(str):
        def _trip(self) -> None:
            if state["armed"]:
                state["calls"] += 1
                raise AssertionError("hostile key callback executed")

        def __hash__(self) -> int:
            self._trip()
            return str.__hash__(self)

        def __eq__(self, other: object) -> bool:
            self._trip()
            return str.__eq__(self, other)

        def __str__(self) -> str:
            self._trip()
            return str.__str__(self)

        def __iter__(self):
            self._trip()
            return iter(())

        def casefold(self) -> str:
            self._trip()
            return str.casefold(self)

        def encode(self, *args: Any, **kwargs: Any) -> bytes:
            self._trip()
            return str.encode(self, *args, **kwargs)

    cases = (
        (api.FeatureSpec, _config_payload()["features"][0], "feature_id"),
        (api.FeatureConfiguration, _config_payload(), "configuration_id"),
        (
            api.FeatureObservation,
            _features(api).observations[0].model_dump(mode="json"),
            "feature_id",
        ),
        (api.FeatureSet, _features(api).model_dump(mode="json"), "instrument_id"),
        (api.ModelFeature, _model_payload()["features"][0], "feature_id"),
        (api.ModelArtifact, _model_payload(), "feature_config_hash"),
        (api.QuantSignal, _score(api).model_dump(mode="json"), "run_id"),
    )
    for model, source, field in cases:
        payload = deepcopy(source)
        field_value = payload.pop(field)
        key = HostileKey(field)
        payload[key] = field_value
        state["calls"] = 0
        state["armed"] = True
        try:
            with pytest.raises((ValidationError, ValueError, api.QuantInputError)):
                model.model_validate(payload)
        finally:
            state["armed"] = False
        assert state["calls"] == 0


def test_quant_signal_direct_wire_enforces_exact_score_range() -> None:
    api = _api()
    base = _score(api).model_dump(mode="json")
    for score in ("-1.000000000000", "1.000000000000"):
        validated = api.QuantSignal.model_validate(
            _rekey_signal_payload({**base, "score": score})
        )
        assert validated.score == Decimal(score)
    for score in ("-1.000000000001", "1.000000000001"):
        with pytest.raises(ValidationError):
            api.QuantSignal.model_validate(
                _rekey_signal_payload({**base, "score": score})
            )


def test_feature_observation_direct_wire_requires_canonical_fixed_decimal() -> None:
    api = _api()
    base = _features(api).observations[0].model_dump(mode="json")
    canonical = api.FeatureObservation.model_validate(
        {**base, "value": "0.100000000000"}
    )
    negative_zero = api.FeatureObservation.model_validate(
        {**base, "value": "-0.000000000000"}
    )
    positive_zero = api.FeatureObservation.model_validate(
        {**base, "value": "0.000000000000"}
    )
    assert canonical.value == Decimal("0.100000000000")
    assert canonical.value.as_tuple().exponent == -12
    assert negative_zero.value == Decimal("0.000000000000")
    assert negative_zero.value.as_tuple().sign == 0
    assert negative_zero.model_dump_json() == positive_zero.model_dump_json()
    for value in (
        "0.1",
        "0.1000000000009",
        "NaN",
        "Infinity",
        "-Infinity",
        "1E+100000",
        "1E-100000",
    ):
        with pytest.raises((ValidationError, api.QuantInputError)):
            api.FeatureObservation.model_validate({**base, "value": value})


@pytest.mark.parametrize("value", ("0.1000000000009", "1E+100000"))
def test_rehashed_feature_set_rejects_bad_decimal_before_scoring(value: str) -> None:
    api = _api()
    payload = _features(api).model_dump(mode="json")
    payload["observations"][0]["value"] = value
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    try:
        candidate = api.FeatureSet.model_validate(payload)
    except (ValidationError, api.QuantInputError):
        return
    with pytest.raises(api.QuantInputError):
        api.QuantSignalModel(_artifact(api)).score(
            candidate,
            run_id="run-bad-feature-decimal",
            bundle=_bundle(),
            configuration=_configuration(api),
        )


def test_quant_signal_direct_resource_limits_are_exact_and_not_truncated() -> None:
    api = _api()
    base = _score(api).model_dump(mode="json")
    run_at_cap = "r" * 128
    run_over_cap = "r" * 129
    ids_at_cap = tuple(f"feature-{index:02d}" for index in range(32))
    at_cap = api.QuantSignal.model_validate(
        _rekey_signal_payload(
            {**base, "run_id": run_at_cap, "feature_ids": list(ids_at_cap)}
        )
    )
    assert at_cap.run_id == run_at_cap
    assert at_cap.feature_ids == ids_at_cap
    with pytest.raises(ValidationError):
        api.QuantSignal.model_validate(
            _rekey_signal_payload({**base, "run_id": run_over_cap})
        )
    with pytest.raises(ValidationError):
        api.QuantSignal.model_validate(
            _rekey_signal_payload(
                {
                    **base,
                    "feature_ids": [*ids_at_cap, "feature-32"],
                }
            )
        )


def test_public_feature_and_model_constructors_check_count_before_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    specs = tuple(
        api.FeatureSpec.model_validate(
            {
                **_config_payload()["features"][0],
                "feature_id": f"bounded-feature-{index:02d}",
            }
        )
        for index in range(32)
    )
    configuration = api.FeatureConfiguration.create(
        configuration_id="config-at-feature-cap",
        configuration_version="v1",
        universe_id="us-liquid-v1",
        calendar_id="XNYS.synthetic.v1",
        horizon_sessions=1,
        features=specs,
    )
    assert len(configuration.features) == 32
    model_features = tuple(
        api.ModelFeature.model_validate(
            {
                **spec.model_dump(mode="json"),
                "weight": "0.000000000000",
            }
        )
        for spec in specs
    )
    schema_hash = _canonical_hash(
        HASH_DOMAINS["feature_schema"],
        [spec.model_dump(mode="json") for spec in specs],
    )
    artifact = api.ModelArtifact.create(
        model_id="model-at-feature-cap",
        model_version="v1",
        horizon_sessions=1,
        decimal_places=12,
        score_min=Decimal("-1"),
        score_max=Decimal("1"),
        feature_config_hash=configuration.content_hash,
        feature_schema_hash=schema_hash,
        features=model_features,
        intercept=Decimal("0.000000000000"),
    )
    assert len(artifact.features) == 32

    spec_calls = {"count": 0}

    def feature_tripwire(cls: type[Any], value: object, *args: Any, **kwargs: Any) -> Any:
        spec_calls["count"] += 1
        raise AssertionError("feature element callback executed")

    monkeypatch.setattr(api.FeatureSpec, "model_validate", classmethod(feature_tripwire))
    with pytest.raises((ValidationError, ValueError, api.QuantInputError)):
        api.FeatureConfiguration.create(
            configuration_id="config-over-feature-cap",
            configuration_version="v1",
            universe_id="us-liquid-v1",
            calendar_id="XNYS.synthetic.v1",
            horizon_sessions=1,
            features=(*specs, specs[0]),
        )
    assert spec_calls["count"] == 0
    monkeypatch.undo()

    model_calls = {"count": 0}

    def model_tripwire(cls: type[Any], value: object, *args: Any, **kwargs: Any) -> Any:
        model_calls["count"] += 1
        raise AssertionError("model element callback executed")

    monkeypatch.setattr(api.ModelFeature, "model_validate", classmethod(model_tripwire))
    with pytest.raises((ValidationError, ValueError, api.QuantInputError)):
        api.ModelArtifact.create(
            model_id="model-over-feature-cap",
            model_version="v1",
            horizon_sessions=1,
            decimal_places=12,
            score_min=Decimal("-1"),
            score_max=Decimal("1"),
            feature_config_hash=configuration.content_hash,
            feature_schema_hash=schema_hash,
            features=(*model_features, model_features[0]),
            intercept=Decimal("0.000000000000"),
        )
    assert model_calls["count"] == 0


def test_structural_and_canonical_limits_have_exact_cap_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    spec_payload = _config_payload()["features"][0]
    monkeypatch.setattr(api.features_module, "MAX_NESTING_DEPTH", 1)
    assert api.FeatureSpec.model_validate(spec_payload).feature_id == spec_payload["feature_id"]
    monkeypatch.setattr(api.features_module, "MAX_NESTING_DEPTH", 0)
    with pytest.raises(ValidationError):
        api.FeatureSpec.model_validate(spec_payload)
    monkeypatch.undo()

    payload = {"probe": "canonical-boundary"}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    canonical_size = len(HASH_DOMAINS["quant_signal"].encode("utf-8") + encoded)
    expected = _canonical_hash(HASH_DOMAINS["quant_signal"], payload)
    monkeypatch.setattr(api.signal_module, "MAX_CANONICAL_BYTES", canonical_size)
    assert api.signal_module._canonical_hash(payload) == expected
    monkeypatch.setattr(api.signal_module, "MAX_CANONICAL_BYTES", canonical_size - 1)
    with pytest.raises(api.QuantInputError):
        api.signal_module._canonical_hash(payload)
    monkeypatch.undo()

    original_walk = api.features_module._safe_bundle_value
    calls = {"count": 0}

    def counted_walk(*args: Any, **kwargs: Any) -> object:
        calls["count"] += 1
        return original_walk(*args, **kwargs)

    monkeypatch.setattr(api.features_module, "_MAX_BUNDLE_WALK_NODES", 1_000_000)
    monkeypatch.setattr(api.features_module, "_safe_bundle_value", counted_walk)
    baseline = _features(api).model_dump(mode="json")
    node_count = calls["count"]
    assert node_count > 0
    monkeypatch.setattr(api.features_module, "_safe_bundle_value", original_walk)
    monkeypatch.setattr(api.features_module, "_MAX_BUNDLE_WALK_NODES", node_count)
    assert _features(api).model_dump(mode="json") == baseline
    monkeypatch.setattr(api.features_module, "_MAX_BUNDLE_WALK_NODES", node_count - 1)
    with pytest.raises(api.QuantInputError):
        _features(api)


@pytest.mark.parametrize("mutation", ("weight", "missing_value"))
def test_stored_model_artifact_mutation_cannot_change_subsequent_scores(
    mutation: str,
) -> None:
    api = _api()
    bundle = _bundle()
    if mutation == "weight":
        configuration = _configuration(api)
        feature_set = _features(api, bundle=bundle, configuration=configuration)
        artifact = _artifact(api)
        feature_index = 0
        replacement = Decimal("9.000000000000")
    else:
        specs = list(_configuration(api).features)
        specs[1] = specs[1].model_copy(update={"bar_source": "missing-optional-source"})
        configuration = api.FeatureConfiguration.create(
            configuration_id="config-mutated-default",
            configuration_version="v1",
            universe_id="us-liquid-v1",
            calendar_id="XNYS.synthetic.v1",
            horizon_sessions=1,
            features=tuple(specs),
        )
        feature_set = _features(api, bundle=bundle, configuration=configuration)
        artifact = _matching_artifact(api, configuration)
        feature_index = 1
        replacement = Decimal("0.900000000000")
    model = api.QuantSignalModel(artifact)
    baseline = model.score(
        feature_set,
        run_id="run-stored-model-mutation",
        bundle=bundle,
        configuration=configuration,
    ).model_dump(mode="json")
    stored_artifact = object.__getattribute__(model, "_artifact")
    object.__setattr__(
        stored_artifact.features[feature_index],
        mutation,
        replacement,
    )

    def score_or_typed_error(_: int) -> dict[str, Any] | str:
        try:
            return model.score(
                feature_set,
                run_id="run-stored-model-mutation",
                bundle=bundle,
                configuration=configuration,
            ).model_dump(mode="json")
        except api.QuantInputError:
            return "typed-rejection"

    repeated = [score_or_typed_error(index) for index in range(4)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        concurrent = list(pool.map(score_or_typed_error, range(16)))
    assert all(item == "typed-rejection" or item == baseline for item in repeated)
    assert all(item == "typed-rejection" or item == baseline for item in concurrent)


def test_encoded_secret_canaries_are_rejected_without_canonical_or_error_echo() -> None:
    api = _api()
    canary = "secret-canary-SIG03-8d92a6"
    raw = canary.encode("utf-8")
    encodings = (
        base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="),
        "".join(f"%{byte:02X}" for byte in raw),
        "".join(f"\\u{ord(character):04x}" for character in canary),
        raw.hex(),
    )
    assert base64.urlsafe_b64decode(encodings[0] + "=" * (-len(encodings[0]) % 4)).decode() == canary
    assert bytes(int(encodings[1][index + 1 : index + 3], 16) for index in range(0, len(encodings[1]), 3)).decode() == canary
    assert "".join(chr(int(encodings[2][index + 2 : index + 6], 16)) for index in range(0, len(encodings[2]), 6)) == canary
    assert bytes.fromhex(encodings[3]).decode() == canary

    for encoded in encodings:
        base_signal = _score(api).model_dump(mode="json")
        cases = (
            lambda encoded=encoded: api.FeatureSpec.model_validate(
                {**_config_payload()["features"][0], "feature_id": encoded}
            ),
            lambda encoded=encoded: api.FeatureConfiguration.create(
                configuration_id=encoded,
                configuration_version="v1",
                universe_id="us-liquid-v1",
                calendar_id="XNYS.synthetic.v1",
                horizon_sessions=1,
                features=_configuration(api).features,
            ),
            lambda encoded=encoded: api.ModelFeature.model_validate(
                {**_model_payload()["features"][0], "feature_id": encoded}
            ),
            lambda encoded=encoded: api.ModelArtifact.create(
                model_id=encoded,
                model_version=_artifact(api).model_version,
                horizon_sessions=_artifact(api).horizon_sessions,
                decimal_places=12,
                score_min=Decimal("-1"),
                score_max=Decimal("1"),
                feature_config_hash=_artifact(api).feature_config_hash,
                feature_schema_hash=_artifact(api).feature_schema_hash,
                features=_artifact(api).features,
                intercept=_artifact(api).intercept,
            ),
            lambda encoded=encoded: _score(api, run_id=encoded),
            lambda encoded=encoded, base_signal=base_signal: api.QuantSignal.model_validate(
                _rekey_signal_payload({**base_signal, "instrument_id": encoded})
            ),
        )
        for construct in cases:
            try:
                accepted = construct()
            except (ValidationError, ValueError, api.QuantInputError) as exc:
                rendered = str(exc)
                assert encoded not in rendered
                assert canary not in rendered
            else:
                serialized = accepted.model_dump_json()
                assert encoded not in serialized
                assert canary not in serialized
                pytest.fail("encoded secret identifier was accepted")


def test_no_closed_calendar_session_returns_canonical_invalid_feature_set() -> None:
    api = _api()
    requirements = tuple(
        EvidenceRequirement(schema_version="v1", domain=domain, required=False)
        for domain in EvidenceDomain
    )
    absent_domains = (
        EvidenceDomain.ACTIONS,
        EvidenceDomain.BARS,
        EvidenceDomain.FILINGS,
        EvidenceDomain.EVENTS,
        EvidenceDomain.SOCIAL,
        EvidenceDomain.MACRO,
    )
    missing_optional = tuple(
        MissingEvidence(
            schema_version="v1",
            domain=domain,
            reason="optional_before_first_close",
        )
        for domain in absent_domains
    )
    bundle = build_evidence_bundle(
        schema_version="v1",
        bundle_id="bundle-before-first-close",
        created_at="2030-01-01T00:00:00Z",
        knowledge_cutoff="2024-03-08T20:59:59Z",
        replay_policy="archive_realistic",
        requirements=requirements,
        missing_optional=missing_optional,
        calendar=_calendar(),
        instrument_candidates=(
            *_models("universe_actions", "instruments", Instrument),
            *_additional_instruments(),
        ),
        alias_candidates=_models("universe_actions", "aliases", SymbolAlias),
        membership_candidates=_models(
            "universe_actions", "memberships", UniverseMembership
        ),
        action_candidates=(),
        bar_candidates=(),
        filing_candidates=(),
        event_candidates=(),
        social_post_candidates=(),
        macro_observation_candidates=(),
    )
    result = _features(api, bundle=bundle)
    assert _status(result) == "invalid"
    assert "calendar_session_unavailable" in _codes(result)
    assert result.as_of == bundle.knowledge_cutoff
    assert all(item.anchor_session is None for item in result.observations)
    assert all(item.lookback_session is None for item in result.observations)


def test_recursive_and_embedded_secret_encodings_reject_without_echo() -> None:
    api = _api()
    canary = "secret-canary-SIG03-8d92a6"
    raw = canary.encode("utf-8")
    padded_base64 = base64.b64encode(raw).decode("ascii")
    base64url = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    double_base64url = base64.urlsafe_b64encode(base64url.encode("ascii")).decode(
        "ascii"
    ).rstrip("=")
    percent = "".join(f"%{byte:02X}" for byte in raw)
    unicode_escape = "".join(f"\\u{ord(character):04x}" for character in canary)
    hexadecimal = raw.hex()
    embedded = tuple(
        (f"{kind}-{prefix or 'plain'}", f"{prefix}{encoded}")
        for kind, encoded in (
            ("base64url", base64url),
            ("percent", percent),
            ("unicode", unicode_escape),
            ("hex", hexadecimal),
        )
        for prefix in ("id:", "id.", "id-")
    )
    encoded_forms = (
        ("padded-base64", padded_base64),
        ("double-base64url", double_base64url),
        *embedded,
    )
    assert base64.b64decode(padded_base64).decode("utf-8") == canary
    first_layer = base64.urlsafe_b64decode(
        double_base64url + "=" * (-len(double_base64url) % 4)
    ).decode("ascii")
    assert first_layer == base64url
    assert base64.urlsafe_b64decode(
        first_layer + "=" * (-len(first_layer) % 4)
    ).decode("utf-8") == canary

    violations: list[str] = []
    for label, encoded in encoded_forms:
        boundaries = (
            (
                "feature",
                lambda encoded=encoded: api.FeatureSpec.model_validate(
                    {**_config_payload()["features"][0], "feature_id": encoded}
                ),
            ),
            ("run", lambda encoded=encoded: _score(api, run_id=encoded)),
        )
        for boundary, construct in boundaries:
            try:
                accepted = construct()
            except (ValidationError, ValueError, api.QuantInputError) as exc:
                rendered = str(exc)
                if encoded in rendered or canary in rendered:
                    violations.append(f"{label}:{boundary}:echo")
            else:
                serialized = accepted.model_dump_json()
                if encoded in serialized or canary in serialized:
                    violations.append(f"{label}:{boundary}:accepted")

    safe_controls = (
        base64.urlsafe_b64encode(b"public-id").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"\x00\xff\x00").decode("ascii").rstrip("="),
        b"public-id".hex(),
        b"\x00\xff\x00".hex(),
    )
    for safe in safe_controls:
        assert (
            api.FeatureSpec.model_validate(
                {**_config_payload()["features"][0], "feature_id": safe}
            ).feature_id
            == safe
        )
        assert _score(api, run_id=safe).run_id == safe
    assert violations == []


def test_feature_observation_provenance_cardinality_and_early_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    base = _features(api).observations[0].model_dump(mode="json")

    def payload_with_count(count: int) -> dict[str, Any]:
        source_session_dates = (
            ["2024-07-01", "2024-07-02"]
            if count == 2
            else ["2024-07-01"] * count
        )
        return {
            **base,
            "source_bar_ids": [f"bar-provenance-{index}" for index in range(count)],
            "source_manifest_ids": [
                f"manifest-provenance-{index}" for index in range(count)
            ],
            "source_revisions": list(range(count)),
            "source_session_dates": source_session_dates,
        }

    exact = api.FeatureObservation.model_validate(payload_with_count(2))
    assert exact.lookback_sessions == 1
    assert len(exact.source_bar_ids) == exact.lookback_sessions + 1
    violations: list[str] = []
    for count in (1, 3, 254, 10_000):
        try:
            api.FeatureObservation.model_validate(payload_with_count(count))
        except (ValidationError, ValueError, api.QuantInputError):
            pass
        else:
            violations.append(f"available-count-{count}")
    mismatched = payload_with_count(2)
    mismatched["source_manifest_ids"] = mismatched["source_manifest_ids"][:1]
    with pytest.raises(ValidationError):
        api.FeatureObservation.model_validate(mismatched)

    missing = {
        **base,
        "value": None,
        "status": "missing",
        "reason_code": "insufficient_lookback",
        "lookback_session": None,
        "latest_available_at": None,
        "source_bar_ids": [],
        "source_manifest_ids": [],
        "source_revisions": [],
        "source_session_dates": [],
    }
    assert api.FeatureObservation.model_validate(missing).source_bar_ids == ()
    nonempty_missing = {
        **missing,
        "source_bar_ids": ["bar-provenance-0"],
        "source_manifest_ids": ["manifest-provenance-0"],
        "source_revisions": [0],
        "source_session_dates": ["2024-03-11"],
    }
    with pytest.raises(ValidationError):
        api.FeatureObservation.model_validate(nonempty_missing)

    callback_calls = {"count": 0}

    def tripwire(value: object) -> str:
        callback_calls["count"] += 1
        raise AssertionError("provenance element callback executed")

    monkeypatch.setattr(api.features_module, "validate_sig03_identifier", tripwire)
    try:
        with pytest.raises((ValidationError, ValueError, api.QuantInputError)):
            api.FeatureObservation.model_validate(payload_with_count(254))
    finally:
        monkeypatch.undo()
    if callback_calls["count"] != 0:
        violations.append("over-cap-element-callback")

    feature_set_payload = _features(api).model_dump(mode="json")
    feature_set_payload["observations"][0] = payload_with_count(3)
    feature_set_payload.pop("feature_hash")
    feature_set_payload["feature_hash"] = _canonical_hash(
        HASH_DOMAINS["feature_set"], feature_set_payload
    )
    try:
        fabricated = api.FeatureSet.model_validate(feature_set_payload)
    except (ValidationError, ValueError, api.QuantInputError):
        pass
    else:
        try:
            api.QuantSignalModel(_artifact(api)).score(
                fabricated,
                run_id="run-fabricated-provenance",
                bundle=_bundle(),
                configuration=_configuration(api),
            )
        except api.QuantInputError:
            pass
        else:
            violations.append("rehashed-feature-set-scored")
    assert violations == []


def _recursive_base64url(value: str, layers: int) -> str:
    encoded = value
    for _ in range(layers):
        encoded = base64.urlsafe_b64encode(encoded.encode("utf-8")).decode("ascii").rstrip("=")
    return encoded


def _rehashed_feature_set_payload(api: SimpleNamespace) -> dict[str, Any]:
    payload = _features(api).model_dump(mode="json")
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    return payload


def _rehashed_configuration_payload(secret_value: str) -> dict[str, Any]:
    payload = _config_payload()
    payload["configuration_id"] = secret_value
    payload.pop("content_hash")
    payload["content_hash"] = _canonical_hash(
        HASH_DOMAINS["feature_configuration"], payload
    )
    return payload


def _rehashed_model_payload(secret_value: str) -> dict[str, Any]:
    payload = _model_payload()
    payload["model_id"] = secret_value
    payload.pop("content_hash")
    payload["content_hash"] = _canonical_hash(HASH_DOMAINS["model_artifact"], payload)
    return payload


def test_round3_recursive_embedded_secrets_reject_across_all_construction_paths() -> None:
    api = _api()
    canary = "secret"
    single = _recursive_base64url(canary, 1)
    five_layers = _recursive_base64url(canary, 5)
    maximum_within_cap = canary
    while True:
        candidate = _recursive_base64url(maximum_within_cap, 1)
        if len(candidate.encode("utf-8")) > 128:
            break
        maximum_within_cap = candidate
    raw = canary.encode("utf-8")
    unicode_encoded = "".join(
        "\\u" + format(ord(character), "04x") for character in canary
    )
    encodings = (
        five_layers,
        maximum_within_cap,
        f"public.{single}.identifier",
        f"public{single}identifier",
        base64.b64encode(raw).decode("ascii"),
        _recursive_base64url(canary, 2),
        f"public:{''.join(f'%{byte:02X}' for byte in raw)}:identifier",
        f"public-{unicode_encoded}-identifier",
        f"public_{raw.hex()}_identifier",
    )
    assert len(five_layers.encode("utf-8")) <= 128
    assert len(maximum_within_cap.encode("utf-8")) <= 128
    assert len(_recursive_base64url(maximum_within_cap, 1).encode("utf-8")) > 128

    violations: list[str] = []
    for encoded in encodings:
        feature_set_payload = _features(api).model_dump(mode="json")
        feature_set_payload["instrument_id"] = encoded
        feature_set_payload.pop("feature_hash")
        feature_set_payload["feature_hash"] = _canonical_hash(
            HASH_DOMAINS["feature_set"], feature_set_payload
        )
        signal_payload = _rekey_signal_payload(
            {**_score(api).model_dump(mode="json"), "run_id": encoded}
        )
        cases = (
            (
                "FeatureSpec",
                api.FeatureSpec,
                {**_config_payload()["features"][0], "feature_id": encoded},
            ),
            (
                "FeatureConfiguration",
                api.FeatureConfiguration,
                _rehashed_configuration_payload(encoded),
            ),
            (
                "FeatureObservation",
                api.FeatureObservation,
                {
                    **_features(api).observations[0].model_dump(mode="json"),
                    "feature_id": encoded,
                },
            ),
            ("FeatureSet", api.FeatureSet, feature_set_payload),
            (
                "ModelFeature",
                api.ModelFeature,
                {**_model_payload()["features"][0], "feature_id": encoded},
            ),
            ("ModelArtifact", api.ModelArtifact, _rehashed_model_payload(encoded)),
            ("QuantSignal", api.QuantSignal, signal_payload),
        )
        for label, model, payload in cases:
            for path, construct in (
                ("model_validate", lambda model=model, payload=payload: model.model_validate(payload)),
                ("constructor", lambda model=model, payload=payload: model(**payload)),
            ):
                try:
                    accepted = construct()
                except (ValidationError, ValueError, api.QuantInputError) as exc:
                    rendered = str(exc)
                    if encoded in rendered or canary in rendered:
                        violations.append(f"{label}:{path}:echo")
                else:
                    rendered = accepted.model_dump_json()
                    if encoded in rendered or canary in rendered:
                        violations.append(f"{label}:{path}:accepted")
        try:
            _score(api, run_id=encoded)
        except (ValidationError, ValueError, api.QuantInputError) as exc:
            rendered = str(exc)
            if encoded in rendered or canary in rendered:
                violations.append("run_id:echo")
        else:
            violations.append("run_id:accepted")

    for safe in (
        f"public.{_recursive_base64url('public-id', 1)}.identifier",
        f"public{_recursive_base64url('public-id', 1)}identifier",
    ):
        spec_payload = {**_config_payload()["features"][0], "feature_id": safe}
        assert api.FeatureSpec.model_validate(spec_payload).feature_id == safe
        assert api.FeatureSpec(**spec_payload).feature_id == safe
        assert _score(api, run_id=safe).run_id == safe
    assert violations == []


@pytest.mark.parametrize(
    "mutation",
    (
        "latest_after_cutoff",
        "observation_as_of_mismatch",
        "observation_as_of_future",
        "negative_revision",
        "duplicate_bar_id",
        "duplicate_manifest_id",
        "reversed_sessions",
        "equal_sessions",
        "anchor_after_as_of",
    ),
)
def test_round3_rehashed_feature_set_rejects_invalid_provenance_semantics(
    mutation: str,
) -> None:
    api = _api()
    payload = _features(api).model_dump(mode="json")
    observation = payload["observations"][0]
    if mutation == "latest_after_cutoff":
        observation["latest_available_at"] = "2024-07-02T20:05:00Z"
    elif mutation == "observation_as_of_mismatch":
        observation["as_of"] = "2024-07-02T19:59:00Z"
    elif mutation == "observation_as_of_future":
        observation["as_of"] = "2024-07-02T20:05:00Z"
    elif mutation == "negative_revision":
        observation["source_revisions"][0] = -1
    elif mutation == "duplicate_bar_id":
        observation["source_bar_ids"][0] = observation["source_bar_ids"][1]
    elif mutation == "duplicate_manifest_id":
        observation["source_manifest_ids"][0] = observation["source_manifest_ids"][1]
    elif mutation == "reversed_sessions":
        observation["lookback_session"] = "2024-07-03"
    elif mutation == "equal_sessions":
        observation["lookback_session"] = observation["anchor_session"]
    elif mutation == "anchor_after_as_of":
        observation["anchor_session"] = "2024-07-03"
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    assert payload["feature_hash"] == _canonical_hash(
        HASH_DOMAINS["feature_set"],
        {key: value for key, value in payload.items() if key != "feature_hash"},
    )
    with pytest.raises((ValidationError, api.QuantInputError)):
        api.FeatureSet.model_validate(payload)


@pytest.mark.parametrize("mutation", ("feature_version", "required", "lookback"))
def test_round3_rehashed_feature_schema_mismatch_is_typed_before_scoring(
    mutation: str,
) -> None:
    api = _api()
    payload = _features(api).model_dump(mode="json")
    observation = payload["observations"][0]
    observation.setdefault(
        "source_session_dates", ["2024-07-01", "2024-07-02"]
    )
    if mutation == "feature_version":
        observation["feature_version"] = "v2"
    elif mutation == "required":
        observation["required"] = False
    else:
        observation["lookback_sessions"] = 2
        observation["lookback_session"] = "2024-06-28"
        observation["source_bar_ids"].insert(0, "bar-extra-schema-mismatch")
        observation["source_manifest_ids"].insert(0, "manifest-extra-schema-mismatch")
        observation["source_revisions"].insert(0, 0)
        observation["source_session_dates"].insert(0, "2024-06-28")
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    candidate = api.FeatureSet.model_validate(payload)
    with pytest.raises(api.QuantInputError):
        api.QuantSignalModel(_artifact(api)).score(
            candidate,
            run_id=f"run-schema-mismatch-{mutation}",
            bundle=_bundle(),
            configuration=_configuration(api),
        )


def test_round3_pathological_builtin_identifier_is_capped_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mytradingalpha.contracts.signals as signal_contracts

    calls = {"count": 0}

    def decode_tripwire(value: str) -> tuple[str, ...]:
        calls["count"] += 1
        raise AssertionError("decode helper reached for over-cap identifier")

    monkeypatch.setattr(
        signal_contracts,
        "_decoded_identifier_candidates",
        decode_tripwire,
    )
    with pytest.raises(ValueError):
        signal_contracts.validate_sig03_identifier("x" * 4_000_000)
    assert calls["count"] == 0


def test_decoded_sensitive_wrappers_reject_all_outward_identifier_paths_without_echo() -> None:
    api = _api()
    decoded_values = (
        "sk-proj-testsecret",
        "AKIAIOSFODNN7EXAMPLE",
        "-----BEGIN PRIVATE KEY-----",
        "api key",
        "Bearer secret",
        '{"secret":"value"}',
    )
    encoded_forms: list[tuple[str, str]] = []
    for index, decoded in enumerate(decoded_values):
        encoded = base64.urlsafe_b64encode(decoded.encode("utf-8")).decode("ascii").rstrip("=")
        wrapped = f"public.{encoded}.identifier" if index != 1 else f"public{encoded}identifier"
        encoded_forms.append((decoded, wrapped))
        encoded_forms.append(
            (
                decoded,
                f"layer.{base64.urlsafe_b64encode(encoded.encode('ascii')).decode('ascii').rstrip('=')}.v1",
            )
        )
    percent_decoded = "api key"
    percent_encoded = "".join(f"%{byte:02X}" for byte in percent_decoded.encode("utf-8"))
    encoded_forms.append((percent_decoded, f"public{percent_encoded}identifier"))

    violations: list[str] = []
    for decoded, encoded in encoded_forms:
        observation_payload = _features(api).observations[0].model_dump(mode="json")
        source_bar_ids = list(observation_payload["source_bar_ids"])
        source_bar_ids[0] = encoded
        source_manifest_ids = list(observation_payload["source_manifest_ids"])
        source_manifest_ids[0] = encoded
        feature_set_payload = _features(api).model_dump(mode="json")
        feature_set_payload["instrument_id"] = encoded
        feature_set_payload.pop("feature_hash")
        feature_set_payload["feature_hash"] = _canonical_hash(
            HASH_DOMAINS["feature_set"], feature_set_payload
        )
        cases = (
            (
                "feature-spec",
                api.FeatureSpec,
                {**_config_payload()["features"][0], "feature_id": encoded},
            ),
            (
                "configuration",
                api.FeatureConfiguration,
                _rehashed_configuration_payload(encoded),
            ),
            (
                "observation-bar",
                api.FeatureObservation,
                {**observation_payload, "source_bar_ids": source_bar_ids},
            ),
            (
                "observation-manifest",
                api.FeatureObservation,
                {**observation_payload, "source_manifest_ids": source_manifest_ids},
            ),
            ("feature-set", api.FeatureSet, feature_set_payload),
            (
                "model-feature",
                api.ModelFeature,
                {**_model_payload()["features"][0], "feature_id": encoded},
            ),
            ("model-artifact", api.ModelArtifact, _rehashed_model_payload(encoded)),
            (
                "quant-signal",
                api.QuantSignal,
                _rekey_signal_payload(
                    {**_score(api).model_dump(mode="json"), "run_id": encoded}
                ),
            ),
        )
        for label, model, payload in cases:
            for path, construct in (
                ("model_validate", lambda model=model, payload=payload: model.model_validate(payload)),
                ("constructor", lambda model=model, payload=payload: model(**payload)),
            ):
                try:
                    accepted = construct()
                except (ValidationError, ValueError, api.QuantInputError) as exc:
                    rendered = str(exc)
                    if encoded in rendered or decoded in rendered:
                        violations.append(f"{label}:{path}:echo")
                else:
                    serialized = accepted.model_dump_json()
                    if encoded in serialized or decoded in serialized:
                        violations.append(f"{label}:{path}:accepted")
        try:
            _score(api, run_id=encoded)
        except (ValidationError, ValueError, api.QuantInputError) as exc:
            rendered = str(exc)
            if encoded in rendered or decoded in rendered:
                violations.append("run-id:echo")
        else:
            violations.append("run-id:accepted")

    safe_controls = (
        base64.urlsafe_b64encode(b"public label").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b'{"label":"value"}').decode("ascii").rstrip("="),
    )
    for safe in safe_controls:
        wrapped = f"public.{safe}.identifier"
        spec_payload = {**_config_payload()["features"][0], "feature_id": wrapped}
        assert api.FeatureSpec.model_validate(spec_payload).feature_id == wrapped
        assert api.FeatureSpec(**spec_payload).feature_id == wrapped
        assert _score(api, run_id=wrapped).run_id == wrapped
    direct_safe_controls = (
        "terms-market-v1",
        "authorization-model-v1",
        "bearer-feature-v1",
        "account-id-feature-v1",
        "source-locator-model-v1",
    )
    for safe in direct_safe_controls:
        spec_payload = {**_config_payload()["features"][0], "feature_id": safe}
        assert api.FeatureSpec.model_validate(spec_payload).feature_id == safe
        assert api.FeatureSpec(**spec_payload).feature_id == safe
        assert _score(api, run_id=safe).run_id == safe
    assert violations == []


def test_feature_observation_wire_records_exact_source_session_lineage() -> None:
    api = _api()
    assert "source_session_dates" in api.FeatureObservation.model_fields
    observations = _features(api).observations
    assert observations[0].source_session_dates == (
        "2024-07-01",
        "2024-07-02",
    )
    assert observations[1].source_session_dates == (
        "2024-06-28",
        "2024-07-01",
        "2024-07-02",
    )
    missing_bundle = _bundle(
        bars=tuple(
            item for item in _bars() if item.session_date != datetime(2024, 7, 1).date()
        )
    )
    missing = _features(api, bundle=missing_bundle)
    assert all(item.source_session_dates == () for item in missing.observations)


@pytest.mark.parametrize(
    "mutation",
    (
        "reversed",
        "duplicate",
        "first_mismatch",
        "last_mismatch",
        "noncanonical",
        "count_mismatch",
    ),
)
def test_rehashed_feature_set_rejects_invalid_source_session_lineage(
    mutation: str,
) -> None:
    api = _api()
    payload = _intended_feature_payload_with_session_lineage(api)
    observation = payload["observations"][0]
    if mutation == "reversed":
        observation["source_session_dates"] = list(
            reversed(observation["source_session_dates"])
        )
    elif mutation == "duplicate":
        observation["source_session_dates"] = ["2024-07-01", "2024-07-01"]
    elif mutation == "first_mismatch":
        observation["source_session_dates"][0] = "2024-06-28"
    elif mutation == "last_mismatch":
        observation["source_session_dates"][-1] = "2024-07-01"
    elif mutation == "noncanonical":
        observation["source_session_dates"][0] = "2024-7-01"
    else:
        observation["source_session_dates"] = observation["source_session_dates"][:1]
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    with pytest.raises((ValidationError, api.QuantInputError)):
        api.FeatureSet.model_validate(payload)


def test_scoring_defensively_rejects_rehashed_session_lineage_mutation() -> None:
    api = _api()
    assert "source_session_dates" in api.FeatureObservation.model_fields
    feature_set = _features(api)
    observation = feature_set.observations[0]
    object.__setattr__(
        observation,
        "source_session_dates",
        tuple(reversed(observation.source_session_dates)),
    )
    object.__setattr__(
        feature_set,
        "feature_hash",
        api.features_module.feature_set_hash(feature_set),
    )
    with pytest.raises(api.QuantInputError):
        api.QuantSignalModel(_artifact(api)).score(
            feature_set,
            run_id="run-invalid-source-session-lineage",
            bundle=_bundle(),
            configuration=_configuration(api),
        )


def _bundle_with_distinct_optional_revisions() -> EvidenceBundle:
    required = tuple(
        item
        for item in _bars()
        if item.manifest.source == "synthetic-quant-bars"
    )
    optional = tuple(
        _bar(
            session_date,
            close,
            source="synthetic-optional-bars",
            revision=revision,
        )
        for revision, (session_date, close) in enumerate(
            (
                ("2024-03-08", "200.00"),
                ("2024-03-11", "220.00"),
                ("2024-06-28", "200.00"),
                ("2024-07-01", "220.00"),
                ("2024-07-02", "242.00"),
            )
        )
    )
    return _bundle(bars=(*required, *optional))


def test_score_rejects_rehashed_noncalendar_intermediate_session() -> None:
    api = _api()
    bundle = _bundle()
    configuration = _configuration(api)
    payload = _features(
        api,
        bundle=bundle,
        configuration=configuration,
    ).model_dump(mode="json")
    payload["observations"][1]["source_session_dates"][1] = "2024-06-29"
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    fabricated = api.FeatureSet.model_validate(payload)
    with pytest.raises(api.QuantInputError):
        api.QuantSignalModel(_artifact(api)).score(
            fabricated,
            run_id="run-noncalendar-session-lineage",
            bundle=bundle,
            configuration=configuration,
        )


@pytest.mark.parametrize(
    "field",
    ("source_bar_ids", "source_manifest_ids", "source_revisions"),
)
def test_score_rejects_independently_permuted_parallel_provenance(
    field: str,
) -> None:
    api = _api()
    bundle = _bundle_with_distinct_optional_revisions()
    configuration = _configuration(api)
    payload = _features(
        api,
        bundle=bundle,
        configuration=configuration,
    ).model_dump(mode="json")
    provenance = payload["observations"][1][field]
    provenance[0], provenance[1] = provenance[1], provenance[0]
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    fabricated = api.FeatureSet.model_validate(payload)
    with pytest.raises(api.QuantInputError):
        api.QuantSignalModel(_artifact(api)).score(
            fabricated,
            run_id=f"run-permuted-{field}",
            bundle=bundle,
            configuration=configuration,
        )


def test_shared_redaction_only_decoded_values_reject_every_identifier_boundary() -> None:
    api = _api()
    decoded_values = (
        "Bearer abcdefgh",
        '{"authorization":"Basic YWJjOmRlZg=="}',
        "broker_account_id=acct-12345678",
    )
    encoded_forms: list[tuple[str, str]] = []
    for decoded in decoded_values:
        encoded = decoded
        for layer in range(1, 4):
            encoded = base64.urlsafe_b64encode(encoded.encode("utf-8")).decode(
                "ascii"
            ).rstrip("=")
            encoded_forms.append((decoded, f"layer{layer}.{encoded}.identifier"))

    violations: list[str] = []
    for decoded, encoded in encoded_forms:
        observation_payload = _features(api).observations[0].model_dump(mode="json")
        source_bar_ids = list(observation_payload["source_bar_ids"])
        source_bar_ids[0] = encoded
        source_manifest_ids = list(observation_payload["source_manifest_ids"])
        source_manifest_ids[0] = encoded
        feature_set_payload = _features(api).model_dump(mode="json")
        feature_set_payload["instrument_id"] = encoded
        feature_set_payload.pop("feature_hash")
        feature_set_payload["feature_hash"] = _canonical_hash(
            HASH_DOMAINS["feature_set"], feature_set_payload
        )
        cases = (
            (
                "feature-spec",
                api.FeatureSpec,
                {**_config_payload()["features"][0], "feature_id": encoded},
            ),
            (
                "configuration",
                api.FeatureConfiguration,
                _rehashed_configuration_payload(encoded),
            ),
            (
                "observation-bar",
                api.FeatureObservation,
                {**observation_payload, "source_bar_ids": source_bar_ids},
            ),
            (
                "observation-manifest",
                api.FeatureObservation,
                {**observation_payload, "source_manifest_ids": source_manifest_ids},
            ),
            ("feature-set", api.FeatureSet, feature_set_payload),
            (
                "model-feature",
                api.ModelFeature,
                {**_model_payload()["features"][0], "feature_id": encoded},
            ),
            ("model-artifact", api.ModelArtifact, _rehashed_model_payload(encoded)),
            (
                "quant-signal",
                api.QuantSignal,
                _rekey_signal_payload(
                    {**_score(api).model_dump(mode="json"), "run_id": encoded}
                ),
            ),
        )
        for label, model, payload in cases:
            for path, construct in (
                ("model_validate", lambda model=model, payload=payload: model.model_validate(payload)),
                ("constructor", lambda model=model, payload=payload: model(**payload)),
            ):
                try:
                    accepted = construct()
                except (ValidationError, ValueError, api.QuantInputError) as exc:
                    rendered = str(exc)
                    if encoded in rendered or decoded in rendered:
                        violations.append(f"{label}:{path}:echo")
                else:
                    serialized = accepted.model_dump_json()
                    if encoded in serialized or decoded in serialized:
                        violations.append(f"{label}:{path}:accepted")
        try:
            _score(api, run_id=encoded)
        except (ValidationError, ValueError, api.QuantInputError) as exc:
            rendered = str(exc)
            if encoded in rendered or decoded in rendered:
                violations.append("run-id:echo")
        else:
            violations.append("run-id:accepted")

    safe_controls = (
        "asia-market-v1",
        "asiatic-feature-v1",
        base64.urlsafe_b64encode(b"asia-market-v1").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"asiatic-feature-v1").decode("ascii").rstrip("="),
    )
    for safe in safe_controls:
        wrapped = f"public.{safe}.identifier"
        spec_payload = {**_config_payload()["features"][0], "feature_id": wrapped}
        assert api.FeatureSpec.model_validate(spec_payload).feature_id == wrapped
        assert api.FeatureSpec(**spec_payload).feature_id == wrapped
        assert _score(api, run_id=wrapped).run_id == wrapped
    assert violations == []


@pytest.mark.parametrize("field", ("score_min", "score_max", "intercept"))
def test_model_artifact_create_rejects_hostile_scalars_without_callbacks(
    field: str,
) -> None:
    api = _api()
    artifact = _artifact(api)
    calls = {"count": 0}

    class HostileScalar:
        def _trip(self) -> None:
            calls["count"] += 1
            raise AssertionError("hostile scalar conversion executed")

        def __str__(self) -> str:
            self._trip()

        def __repr__(self) -> str:
            self._trip()

        def __float__(self) -> float:
            self._trip()

        def __int__(self) -> int:
            self._trip()

        def __index__(self) -> int:
            self._trip()

    scalars: dict[str, object] = {
        "score_min": artifact.score_min,
        "score_max": artifact.score_max,
        "intercept": artifact.intercept,
    }
    scalars[field] = HostileScalar()
    with pytest.raises(api.QuantInputError) as exc_info:
        api.ModelArtifact.create(
            model_id=artifact.model_id,
            model_version=artifact.model_version,
            horizon_sessions=artifact.horizon_sessions,
            decimal_places=artifact.decimal_places,
            score_min=scalars["score_min"],
            score_max=scalars["score_max"],
            feature_config_hash=artifact.feature_config_hash,
            feature_schema_hash=artifact.feature_schema_hash,
            features=artifact.features,
            intercept=scalars["intercept"],
        )
    assert calls["count"] == 0
    assert "hostile scalar" not in str(exc_info.value)


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown-required",
        "unknown-optional",
        "required-reason-absent",
        "optional-invalid-reason-absent",
        "overlapping-missing-sets",
        "duplicate-required",
        "unsorted-optional",
    ),
)
def test_quant_signal_missing_feature_sets_are_intrinsically_bound(
    mutation: str,
) -> None:
    api = _api()
    payload = _score(api).model_dump(mode="json")
    if mutation == "unknown-required":
        payload.update(
            status="invalid",
            score=None,
            missing_required_feature_ids=["unknown-required-feature"],
            reason_codes=["required_feature_missing"],
        )
    elif mutation == "unknown-optional":
        payload.update(
            status="degraded",
            missing_optional_feature_ids=["unknown-optional-feature"],
            reason_codes=["optional_feature_missing"],
        )
    elif mutation == "required-reason-absent":
        payload.update(
            status="invalid",
            score=None,
            missing_required_feature_ids=["close_return_1d"],
            reason_codes=["exact_session_bar_missing"],
        )
    elif mutation == "optional-invalid-reason-absent":
        payload.update(
            status="invalid",
            score=None,
            missing_optional_feature_ids=["close_return_2d_optional"],
            reason_codes=["exact_session_bar_missing"],
        )
    elif mutation == "overlapping-missing-sets":
        payload.update(
            status="invalid",
            score=None,
            missing_required_feature_ids=["close_return_1d"],
            missing_optional_feature_ids=["close_return_1d"],
            reason_codes=["required_feature_missing", "optional_feature_missing"],
        )
    elif mutation == "duplicate-required":
        payload.update(
            status="invalid",
            score=None,
            missing_required_feature_ids=["close_return_1d", "close_return_1d"],
            reason_codes=["required_feature_missing"],
        )
    else:
        payload.update(
            status="invalid",
            score=None,
            missing_optional_feature_ids=[
                "close_return_2d_optional",
                "close_return_1d",
            ],
            reason_codes=["optional_feature_missing"],
        )
    rekeyed = _rekey_signal_payload(payload)
    with pytest.raises(ValidationError):
        api.QuantSignal.model_validate(rekeyed)
    with pytest.raises(ValidationError):
        api.QuantSignal(**rekeyed)


def test_malformed_decoded_secret_wrappers_reject_every_outward_identifier_path() -> None:
    api = _api()
    decoded_values = (
        '{"authorization":"Bearer abcdefgh"',
        'prefix{"broker_account_id":"acct-12345678"',
        '"api_key":"abcdefgh"}suffix',
    )
    encoded_forms: list[tuple[str, str]] = []
    for decoded in decoded_values:
        encoded = decoded
        for layer in range(1, 4):
            encoded = base64.urlsafe_b64encode(encoded.encode("utf-8")).decode(
                "ascii"
            ).rstrip("=")
            encoded_forms.append((decoded, f"malformed{layer}.{encoded}.wrapper"))
    embedded_decoded = "{Bearer abcdefgh"
    embedded_encoded = base64.urlsafe_b64encode(
        embedded_decoded.encode("utf-8")
    ).decode("ascii").rstrip("=")
    encoded_forms.append(
        (embedded_decoded, f"public{embedded_encoded}identifier")
    )
    unicode_decoded = "Ｂｅａｒｅｒ abcdefgh"
    unicode_encoded = base64.urlsafe_b64encode(
        unicode_decoded.encode("utf-8")
    ).decode("ascii").rstrip("=")
    encoded_forms.append(
        (unicode_decoded, f"unicode.{unicode_encoded}.wrapper")
    )

    violations: list[str] = []
    for decoded, encoded in encoded_forms:
        observation_payload = _features(api).observations[0].model_dump(mode="json")
        source_bar_ids = list(observation_payload["source_bar_ids"])
        source_bar_ids[0] = encoded
        source_manifest_ids = list(observation_payload["source_manifest_ids"])
        source_manifest_ids[0] = encoded
        feature_set_payload = _features(api).model_dump(mode="json")
        feature_set_payload["instrument_id"] = encoded
        feature_set_payload.pop("feature_hash")
        feature_set_payload["feature_hash"] = _canonical_hash(
            HASH_DOMAINS["feature_set"], feature_set_payload
        )
        cases = (
            (
                "feature-spec",
                api.FeatureSpec,
                {**_config_payload()["features"][0], "feature_id": encoded},
            ),
            (
                "configuration",
                api.FeatureConfiguration,
                _rehashed_configuration_payload(encoded),
            ),
            (
                "observation-bar",
                api.FeatureObservation,
                {**observation_payload, "source_bar_ids": source_bar_ids},
            ),
            (
                "observation-manifest",
                api.FeatureObservation,
                {**observation_payload, "source_manifest_ids": source_manifest_ids},
            ),
            ("feature-set", api.FeatureSet, feature_set_payload),
            (
                "model-feature",
                api.ModelFeature,
                {**_model_payload()["features"][0], "feature_id": encoded},
            ),
            ("model-artifact", api.ModelArtifact, _rehashed_model_payload(encoded)),
            (
                "quant-signal",
                api.QuantSignal,
                _rekey_signal_payload(
                    {**_score(api).model_dump(mode="json"), "run_id": encoded}
                ),
            ),
        )
        for label, model, payload in cases:
            for path, construct in (
                ("model_validate", lambda model=model, payload=payload: model.model_validate(payload)),
                ("constructor", lambda model=model, payload=payload: model(**payload)),
            ):
                try:
                    accepted = construct()
                except (ValidationError, ValueError, api.QuantInputError) as exc:
                    rendered = str(exc)
                    if encoded in rendered or decoded in rendered:
                        violations.append(f"{label}:{path}:echo")
                else:
                    serialized = accepted.model_dump_json()
                    if encoded in serialized or decoded in serialized:
                        violations.append(f"{label}:{path}:accepted")
        try:
            _score(api, run_id=encoded)
        except (ValidationError, ValueError, api.QuantInputError) as exc:
            rendered = str(exc)
            if encoded in rendered or decoded in rendered:
                violations.append("run-id:echo")
        else:
            violations.append("run-id:accepted")
    assert violations == []


def test_identifier_validation_has_no_process_global_raw_or_decoded_cache() -> None:
    import mytradingalpha.contracts.signals as signal_contracts

    for callable_value in (
        signal_contracts._decoded_identifier_candidates,
        signal_contracts._identifier_contains_sensitive_candidate,
    ):
        assert not hasattr(callable_value, "cache_info")
        assert not hasattr(callable_value, "cache_clear")
    source = (ROOT / "mytradingalpha" / "contracts" / "signals.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module == "functools"
        and any(alias.name == "lru_cache" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Name) and node.id == "lru_cache" for node in ast.walk(tree)
    )


def test_shared_sensitive_key_wrappers_are_rejected_without_echo() -> None:
    import mytradingalpha.contracts.signals as signal_contracts

    decoded_values = (
        "account_number=12345678",
        "source_locator=s3://private/path",
        "terms=private-value",
    )
    violations: list[str] = []
    for decoded in decoded_values:
        encoded = base64.urlsafe_b64encode(decoded.encode("utf-8")).decode(
            "ascii"
        ).rstrip("=")
        for label, wrapped in (
            ("ordinary", f"public.{encoded}.identifier"),
            ("embedded", f"public{encoded}identifier"),
        ):
            try:
                accepted = signal_contracts.validate_sig03_identifier(wrapped)
            except ValueError as exc:
                rendered = str(exc)
                if encoded in rendered or decoded in rendered:
                    violations.append(f"{label}:echo")
            else:
                violations.append(f"{label}:accepted:{accepted}")
    assert violations == []


@pytest.mark.parametrize("entrypoint", ("create", "model_validate"))
@pytest.mark.parametrize("hash_field", ("feature_config_hash", "feature_schema_hash"))
def test_model_artifact_hash_inputs_reject_subclasses_without_callbacks(
    entrypoint: str,
    hash_field: str,
) -> None:
    api = _api()
    artifact = _artifact(api)
    calls = {"count": 0}

    class HostileHash(str):
        def _trip(self) -> None:
            calls["count"] += 1
            raise AssertionError("hostile hash callback executed")

        def __eq__(self, other: object) -> bool:
            self._trip()

        def __hash__(self) -> int:
            self._trip()

        def __str__(self) -> str:
            self._trip()

        def __repr__(self) -> str:
            self._trip()

        def casefold(self) -> str:
            self._trip()

        def encode(self, *args: Any, **kwargs: Any) -> bytes:
            self._trip()

    hostile = HostileHash("sha256:" + "a" * 64)
    with pytest.raises(api.QuantInputError) as exc_info:
        if entrypoint == "create":
            kwargs = {
                "model_id": artifact.model_id,
                "model_version": artifact.model_version,
                "horizon_sessions": artifact.horizon_sessions,
                "decimal_places": artifact.decimal_places,
                "score_min": artifact.score_min,
                "score_max": artifact.score_max,
                "feature_config_hash": artifact.feature_config_hash,
                "feature_schema_hash": artifact.feature_schema_hash,
                "features": artifact.features,
                "intercept": artifact.intercept,
            }
            kwargs[hash_field] = hostile
            api.ModelArtifact.create(**kwargs)
        else:
            payload = artifact.model_dump(mode="python")
            payload[hash_field] = hostile
            api.ModelArtifact.model_validate(payload)
    assert calls["count"] == 0
    assert "hostile hash" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("status", "missing_required", "missing_optional", "reasons"),
    (
        (
            "degraded",
            [],
            ["close_return_2d_optional"],
            ["exact_session_bar_missing", "optional_feature_missing"],
        ),
        (
            "degraded",
            [],
            ["close_return_2d_optional"],
            ["instrument_not_in_bundle", "optional_feature_missing"],
        ),
        (
            "invalid",
            [],
            ["close_return_2d_optional"],
            ["optional_feature_missing"],
        ),
        ("invalid", [], [], ["bar_series_ambiguous"]),
        ("invalid", [], [], ["exact_session_bar_missing"]),
        ("invalid", [], [], ["insufficient_lookback"]),
    ),
)
def test_quant_signal_rejects_impossible_status_reason_missingness_cross_product(
    status: str,
    missing_required: list[str],
    missing_optional: list[str],
    reasons: list[str],
) -> None:
    api = _api()
    payload = _score(api).model_dump(mode="json")
    payload.update(
        status=status,
        score=None if status == "invalid" else payload["score"],
        missing_required_feature_ids=missing_required,
        missing_optional_feature_ids=missing_optional,
        reason_codes=reasons,
    )
    rekeyed = _rekey_signal_payload(payload)
    with pytest.raises(ValidationError):
        api.QuantSignal.model_validate(rekeyed)
    with pytest.raises(ValidationError):
        api.QuantSignal(**rekeyed)


@pytest.mark.parametrize(
    "reason",
    (
        "instrument_not_in_bundle",
        "instrument_inactive_as_of",
        "instrument_not_in_universe",
        "ambiguous_universe_membership",
        "calendar_session_unavailable",
    ),
)
def test_quant_signal_global_eligibility_reason_can_invalidate_without_missing_ids(
    reason: str,
) -> None:
    api = _api()
    payload = _score(api).model_dump(mode="json")
    payload.update(status="invalid", score=None, reason_codes=[reason])
    rekeyed = _rekey_signal_payload(payload)
    assert api.QuantSignal.model_validate(rekeyed).status.value == "invalid"
    assert api.QuantSignal(**rekeyed).status.value == "invalid"


def _all_optional_configuration(
    api: SimpleNamespace,
    *,
    calendar_id: str = "XNYS.synthetic.v1",
) -> Any:
    specs = tuple(
        api.FeatureSpec.model_validate(
            {**spec.model_dump(mode="json"), "required": False}
        )
        for spec in _configuration(api).features
    )
    return api.FeatureConfiguration.create(
        configuration_id=f"all-optional-{calendar_id.replace('.', '-')}",
        configuration_version="v1",
        universe_id="us-liquid-v1",
        calendar_id=calendar_id,
        horizon_sessions=1,
        features=specs,
    )


@pytest.mark.parametrize(
    ("scenario", "expected_global_reason"),
    (
        ("wrong-instrument", "instrument_not_in_bundle"),
        ("inactive", "instrument_inactive_as_of"),
        ("nonmember", "instrument_not_in_universe"),
        ("calendar", "calendar_session_unavailable"),
    ),
)
def test_all_optional_global_ineligibility_scores_explicit_invalid_signal(
    scenario: str,
    expected_global_reason: str,
) -> None:
    api = _api()
    bundle = _bundle()
    configuration = _all_optional_configuration(api)
    instrument_id = "inst-survivor"
    if scenario == "wrong-instrument":
        instrument_id = "not-in-bundle"
    elif scenario == "inactive":
        instrument_id = "inst-acme"
    elif scenario == "nonmember":
        bundle = _bundle(
            memberships=tuple(
                item
                for item in bundle.memberships
                if item.instrument_id != "inst-survivor"
            )
        )
    else:
        configuration = _all_optional_configuration(api, calendar_id="other-calendar")
    feature_set = _features(
        api,
        bundle=bundle,
        configuration=configuration,
        instrument_id=instrument_id,
    )
    assert feature_set.status == "invalid"
    assert feature_set.missing_required_feature_ids == ()
    expected_optional_ids = feature_set.missing_optional_feature_ids
    signal = _score(
        api,
        feature_set=feature_set,
        artifact=_matching_artifact(api, configuration),
        bundle=bundle,
        configuration=configuration,
        run_id=f"run-all-optional-{scenario}",
    )
    assert signal.status.value == "invalid"
    assert signal.score is None
    assert signal.missing_required_feature_ids == ()
    assert signal.missing_optional_feature_ids == expected_optional_ids
    assert expected_global_reason in _codes(signal)
    assert ("optional_feature_missing" in _codes(signal)) is bool(expected_optional_ids)
    assert set(_codes(feature_set)).issubset(_codes(signal))


@pytest.mark.parametrize(
    ("feature_reason", "global_reason"),
    (
        ("bar_series_ambiguous", None),
        ("exact_session_bar_missing", None),
        ("insufficient_lookback", None),
        ("bar_series_ambiguous", "instrument_not_in_bundle"),
        ("exact_session_bar_missing", "instrument_not_in_bundle"),
        ("insufficient_lookback", "instrument_not_in_bundle"),
    ),
)
def test_quant_signal_feature_reason_requires_explained_missing_feature(
    feature_reason: str,
    global_reason: str | None,
) -> None:
    api = _api()
    payload = _score(api).model_dump(mode="json")
    reasons = [feature_reason]
    if global_reason is not None:
        reasons.insert(0, global_reason)
    payload.update(status="invalid", score=None, reason_codes=reasons)
    rekeyed = _rekey_signal_payload(payload)
    with pytest.raises(ValidationError):
        api.QuantSignal.model_validate(rekeyed)
    with pytest.raises(ValidationError):
        api.QuantSignal(**rekeyed)


def test_safe_128_byte_identifier_stays_within_per_identifier_decode_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mytradingalpha.contracts.signals as signal_contracts

    calls = {"count": 0}
    original_decode = signal_contracts.base64.b64decode

    def counted_decode(*args: Any, **kwargs: Any) -> bytes:
        calls["count"] += 1
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(signal_contracts.base64, "b64decode", counted_decode)
    identifier = "Z" * 128
    assert signal_contracts.validate_sig03_identifier(identifier) == identifier
    assert 0 < calls["count"] <= 6_000


def test_pathological_at_cap_model_payload_exhausts_shared_decode_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    import mytradingalpha.contracts.signals as signal_contracts

    calls = {"count": 0}

    def counted_decode(*args: Any, **kwargs: Any) -> bytes:
        calls["count"] += 1
        return b""

    monkeypatch.setattr(signal_contracts.base64, "b64decode", counted_decode)
    base_spec = _config_payload()["features"][0]
    features = [
        {**base_spec, "feature_id": f"{index:04d}" + "Z" * 124}
        for index in range(32)
    ]
    payload = {
        "schema_version": "v1",
        "configuration_id": "pathological-at-cap-config",
        "configuration_version": "v1",
        "universe_id": "us-liquid-v1",
        "calendar_id": "XNYS.synthetic.v1",
        "horizon_sessions": 1,
        "features": features,
    }
    payload["content_hash"] = _canonical_hash(
        HASH_DOMAINS["feature_configuration"], payload
    )
    with pytest.raises((ValidationError, api.QuantInputError)):
        api.FeatureConfiguration.model_validate(payload)
    assert 0 < calls["count"] <= 6_001


def test_normal_at_cap_short_feature_payload_remains_accepted() -> None:
    api = _api()
    base_spec = _config_payload()["features"][0]
    features = [
        {**base_spec, "feature_id": f"normal-cap-feature-{index:02d}"}
        for index in range(32)
    ]
    payload = {
        "schema_version": "v1",
        "configuration_id": "normal-at-cap-config",
        "configuration_version": "v1",
        "universe_id": "us-liquid-v1",
        "calendar_id": "XNYS.synthetic.v1",
        "horizon_sessions": 1,
        "features": features,
    }
    payload["content_hash"] = _canonical_hash(
        HASH_DOMAINS["feature_configuration"], payload
    )
    validated = api.FeatureConfiguration.model_validate(payload)
    assert len(validated.features) == 32


def test_secret_word_prefix_labels_are_safe_but_exact_secrets_reject_without_echo() -> None:
    import mytradingalpha.contracts.signals as signal_contracts

    def encoded_forms(value: str) -> tuple[str, ...]:
        raw = value.encode("utf-8")
        return (
            value,
            base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="),
            raw.hex(),
            "".join(f"%{byte:02X}" for byte in raw),
        )

    for safe in ("tokenomics-v1", "secretary-model-v1"):
        for candidate in encoded_forms(safe):
            assert signal_contracts.validate_sig03_identifier(candidate) == candidate

    for secret in ("token", "secret", "api-key"):
        for candidate in encoded_forms(secret):
            with pytest.raises(ValueError) as exc_info:
                signal_contracts.validate_sig03_identifier(candidate)
            assert candidate not in str(exc_info.value)
            assert secret not in str(exc_info.value)


def _aggregate_feature_configuration_payload(
    feature_ids: list[str],
) -> dict[str, Any]:
    base_spec = _config_payload()["features"][0]
    payload: dict[str, Any] = {
        "schema_version": "v1",
        "configuration_id": "aggregate-budget-config",
        "configuration_version": "v1",
        "universe_id": "us-liquid-v1",
        "calendar_id": "XNYS.synthetic.v1",
        "horizon_sessions": 1,
        "features": [
            {**base_spec, "feature_id": feature_id} for feature_id in feature_ids
        ],
    }
    payload["content_hash"] = _canonical_hash(
        HASH_DOMAINS["feature_configuration"], payload
    )
    return payload


def _aggregate_feature_set_payload(
    api: SimpleNamespace,
    feature_ids: list[str],
) -> dict[str, Any]:
    payload = _features(api).model_dump(mode="json")
    template = payload["observations"][0]
    payload["observations"] = [
        {**deepcopy(template), "feature_id": feature_id}
        for feature_id in feature_ids
    ]
    payload["missing_required_feature_ids"] = []
    payload["missing_optional_feature_ids"] = []
    payload["status"] = "valid"
    payload["reason_codes"] = []
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)
    return payload


def _aggregate_model_artifact_payload(feature_ids: list[str]) -> dict[str, Any]:
    base_feature = _model_payload()["features"][0]
    features = [
        {**base_feature, "feature_id": feature_id} for feature_id in feature_ids
    ]
    schema_payload = [
        {
            key: value
            for key, value in feature.items()
            if key not in {"weight", "missing_value"}
        }
        for feature in features
    ]
    payload: dict[str, Any] = {
        "schema_version": "v1",
        "model_id": "aggregate-budget-model",
        "model_version": "v1",
        "horizon_sessions": 1,
        "decimal_places": 12,
        "score_min": "-1",
        "score_max": "1",
        "feature_config_hash": "sha256:" + "1" * 64,
        "feature_schema_hash": _canonical_hash(
            HASH_DOMAINS["feature_schema"], schema_payload
        ),
        "features": features,
        "intercept": "0.000000000000",
    }
    payload["content_hash"] = _canonical_hash(HASH_DOMAINS["model_artifact"], payload)
    return payload


def _aggregate_quant_signal_payload(
    api: SimpleNamespace,
    feature_ids: list[str],
) -> dict[str, Any]:
    payload = _score(api).model_dump(mode="json")
    payload["feature_ids"] = feature_ids
    payload["missing_required_feature_ids"] = []
    payload["missing_optional_feature_ids"] = []
    payload["status"] = "valid"
    payload["reason_codes"] = []
    return _rekey_signal_payload(payload)


def _aggregate_payload(
    api: SimpleNamespace,
    model_name: str,
    feature_ids: list[str],
) -> tuple[type[Any], dict[str, Any]]:
    if model_name == "FeatureConfiguration":
        return api.FeatureConfiguration, _aggregate_feature_configuration_payload(
            feature_ids
        )
    if model_name == "FeatureSet":
        return api.FeatureSet, _aggregate_feature_set_payload(api, feature_ids)
    if model_name == "ModelArtifact":
        return api.ModelArtifact, _aggregate_model_artifact_payload(feature_ids)
    return api.QuantSignal, _aggregate_quant_signal_payload(api, feature_ids)


@pytest.mark.parametrize(
    "model_name",
    ("FeatureConfiguration", "FeatureSet", "ModelArtifact", "QuantSignal"),
)
@pytest.mark.parametrize("entrypoint", ("model_validate", "constructor"))
def test_pathological_aggregate_identifiers_share_outer_decode_budget(
    model_name: str,
    entrypoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    import mytradingalpha.contracts.signals as signal_contracts

    calls = {"count": 0}

    def counted_decode(*args: Any, **kwargs: Any) -> bytes:
        calls["count"] += 1
        return b""

    feature_ids = [f"{index:04d}" + "Z" * 124 for index in range(32)]
    model, payload = _aggregate_payload(api, model_name, feature_ids)
    monkeypatch.setattr(signal_contracts.base64, "b64decode", counted_decode)
    with pytest.raises((ValidationError, api.QuantInputError, ValueError)):
        if entrypoint == "model_validate":
            model.model_validate(payload)
        else:
            model(**payload)
    assert 0 < calls["count"] <= 6_001


@pytest.mark.parametrize(
    "model_name",
    ("FeatureConfiguration", "FeatureSet", "ModelArtifact", "QuantSignal"),
)
@pytest.mark.parametrize("entrypoint", ("model_validate", "constructor"))
def test_normal_cap_payload_has_constructor_validation_parity(
    model_name: str,
    entrypoint: str,
) -> None:
    api = _api()
    feature_ids = [f"normal-feature-{index:02d}" for index in range(32)]
    model, payload = _aggregate_payload(api, model_name, feature_ids)
    validated = (
        model.model_validate(payload)
        if entrypoint == "model_validate"
        else model(**payload)
    )
    if model_name == "FeatureConfiguration":
        assert len(validated.features) == 32
    elif model_name == "FeatureSet":
        assert len(validated.observations) == 32
    elif model_name == "ModelArtifact":
        assert len(validated.features) == 32
    else:
        assert len(validated.feature_ids) == 32


@pytest.mark.parametrize(
    "field",
    (
        "observations",
        "missing_required_feature_ids",
        "missing_optional_feature_ids",
        "reason_codes",
    ),
)
@pytest.mark.parametrize("count", (33, 10_000))
@pytest.mark.parametrize("entrypoint", ("model_validate", "constructor"))
def test_feature_set_collection_caps_reject_before_sensitive_elements(
    field: str,
    count: int,
    entrypoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    payload = _features(api).model_dump(mode="json")
    if field == "observations":
        payload[field] = [deepcopy(payload[field][0]) for _ in range(count)]
    elif field == "reason_codes":
        payload[field] = ["optional_feature_missing"] * count
    else:
        payload[field] = [f"overcap-feature-{index}" for index in range(count)]
    payload.pop("feature_hash")
    payload["feature_hash"] = _canonical_hash(HASH_DOMAINS["feature_set"], payload)

    callbacks = {"count": 0}
    original_identifier = api.features_module.validate_sig03_identifier

    def guarded_identifier(value: object, *args: Any, **kwargs: Any) -> str:
        if type(value) is str and value.startswith("overcap-feature-"):
            callbacks["count"] += 1
            raise AssertionError("over-cap element validation executed")
        return original_identifier(value, *args, **kwargs)

    monkeypatch.setattr(
        api.features_module,
        "validate_sig03_identifier",
        guarded_identifier,
    )
    with pytest.raises((ValidationError, api.QuantInputError, ValueError)):
        if entrypoint == "model_validate":
            api.FeatureSet.model_validate(payload)
        else:
            api.FeatureSet(**payload)
    assert callbacks["count"] == 0


@pytest.mark.parametrize(
    "model_name",
    (
        "FeatureSpec",
        "FeatureConfiguration",
        "FeatureObservation",
        "FeatureSet",
        "ModelFeature",
        "ModelArtifact",
        "QuantSignal",
    ),
)
@pytest.mark.parametrize("entrypoint", ("model_validate", "constructor"))
def test_safe_128_byte_identifier_has_outward_constructor_parity(
    model_name: str,
    entrypoint: str,
) -> None:
    api = _api()
    safe_identifier = "Z" * 128
    if model_name == "FeatureSpec":
        model = api.FeatureSpec
        payload = {
            **_config_payload()["features"][0],
            "feature_id": safe_identifier,
        }
        identity_field = "feature_id"
    elif model_name == "FeatureConfiguration":
        model = api.FeatureConfiguration
        payload = _rehashed_configuration_payload(safe_identifier)
        identity_field = "configuration_id"
    elif model_name == "FeatureObservation":
        model = api.FeatureObservation
        payload = {
            **_features(api).observations[0].model_dump(mode="json"),
            "feature_id": safe_identifier,
        }
        identity_field = "feature_id"
    elif model_name == "FeatureSet":
        model = api.FeatureSet
        payload = _features(api).model_dump(mode="json")
        payload["instrument_id"] = safe_identifier
        payload.pop("feature_hash")
        payload["feature_hash"] = _canonical_hash(
            HASH_DOMAINS["feature_set"], payload
        )
        identity_field = "instrument_id"
    elif model_name == "ModelFeature":
        model = api.ModelFeature
        payload = {
            **_model_payload()["features"][0],
            "feature_id": safe_identifier,
        }
        identity_field = "feature_id"
    elif model_name == "ModelArtifact":
        model = api.ModelArtifact
        payload = _rehashed_model_payload(safe_identifier)
        identity_field = "model_id"
    else:
        model = api.QuantSignal
        payload = _rekey_signal_payload(
            {**_score(api).model_dump(mode="json"), "run_id": safe_identifier}
        )
        identity_field = "run_id"
    validated = (
        model.model_validate(payload)
        if entrypoint == "model_validate"
        else model(**payload)
    )
    assert getattr(validated, identity_field) == safe_identifier


def _safe_identifier_validation_case(
    api: SimpleNamespace,
    target: str,
) -> tuple[Any, str]:
    safe_identifier = "Z" * 128
    if target == "FeatureSpec.model_validate":
        payload = {
            **_config_payload()["features"][0],
            "feature_id": safe_identifier,
        }
        return lambda: api.FeatureSpec.model_validate(payload), "feature_id"
    if target == "FeatureSpec.constructor":
        payload = {
            **_config_payload()["features"][0],
            "feature_id": safe_identifier,
        }
        return lambda: api.FeatureSpec(**payload), "feature_id"
    if target.startswith("FeatureConfiguration."):
        payload = _rehashed_configuration_payload(safe_identifier)
        if target.endswith("model_validate"):
            return lambda: api.FeatureConfiguration.model_validate(payload), "configuration_id"
        if target.endswith("constructor"):
            return lambda: api.FeatureConfiguration(**payload), "configuration_id"
        configuration = _configuration(api)
        return (
            lambda: api.FeatureConfiguration.create(
                configuration_id=safe_identifier,
                configuration_version=configuration.configuration_version,
                universe_id=configuration.universe_id,
                calendar_id=configuration.calendar_id,
                horizon_sessions=configuration.horizon_sessions,
                features=configuration.features,
            ),
            "configuration_id",
        )
    if target.startswith("FeatureObservation."):
        payload = {
            **_features(api).observations[0].model_dump(mode="json"),
            "feature_id": safe_identifier,
        }
        construct = (
            (lambda: api.FeatureObservation.model_validate(payload))
            if target.endswith("model_validate")
            else (lambda: api.FeatureObservation(**payload))
        )
        return construct, "feature_id"
    if target.startswith("FeatureSet."):
        payload = _features(api).model_dump(mode="json")
        payload["instrument_id"] = safe_identifier
        payload.pop("feature_hash")
        payload["feature_hash"] = _canonical_hash(
            HASH_DOMAINS["feature_set"], payload
        )
        construct = (
            (lambda: api.FeatureSet.model_validate(payload))
            if target.endswith("model_validate")
            else (lambda: api.FeatureSet(**payload))
        )
        return construct, "instrument_id"
    if target.startswith("ModelFeature."):
        payload = {
            **_model_payload()["features"][0],
            "feature_id": safe_identifier,
        }
        construct = (
            (lambda: api.ModelFeature.model_validate(payload))
            if target.endswith("model_validate")
            else (lambda: api.ModelFeature(**payload))
        )
        return construct, "feature_id"
    if target.startswith("ModelArtifact."):
        payload = _rehashed_model_payload(safe_identifier)
        if target.endswith("model_validate"):
            return lambda: api.ModelArtifact.model_validate(payload), "model_id"
        if target.endswith("constructor"):
            return lambda: api.ModelArtifact(**payload), "model_id"
        artifact = _artifact(api)
        return (
            lambda: api.ModelArtifact.create(
                model_id=safe_identifier,
                model_version=artifact.model_version,
                horizon_sessions=artifact.horizon_sessions,
                decimal_places=artifact.decimal_places,
                score_min=artifact.score_min,
                score_max=artifact.score_max,
                feature_config_hash=artifact.feature_config_hash,
                feature_schema_hash=artifact.feature_schema_hash,
                features=artifact.features,
                intercept=artifact.intercept,
            ),
            "model_id",
        )
    payload = _rekey_signal_payload(
        {**_score(api).model_dump(mode="json"), "run_id": safe_identifier}
    )
    construct = (
        (lambda: api.QuantSignal.model_validate(payload))
        if target.endswith("model_validate")
        else (lambda: api.QuantSignal(**payload))
    )
    return construct, "run_id"


@pytest.mark.parametrize(
    "target",
    (
        "FeatureSpec.model_validate",
        "FeatureSpec.constructor",
        "FeatureConfiguration.model_validate",
        "FeatureConfiguration.constructor",
        "FeatureConfiguration.create",
        "FeatureObservation.model_validate",
        "FeatureObservation.constructor",
        "FeatureSet.model_validate",
        "FeatureSet.constructor",
        "ModelFeature.model_validate",
        "ModelFeature.constructor",
        "ModelArtifact.model_validate",
        "ModelArtifact.constructor",
        "ModelArtifact.create",
        "QuantSignal.model_validate",
        "QuantSignal.constructor",
    ),
)
def test_safe_128_byte_identifier_request_budget_covers_complete_entrypoint(
    target: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    import mytradingalpha.contracts.signals as signal_contracts

    construct, identity_field = _safe_identifier_validation_case(api, target)
    calls = {"count": 0}
    original_decode = signal_contracts.base64.b64decode

    def counted_decode(*args: Any, **kwargs: Any) -> bytes:
        calls["count"] += 1
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(signal_contracts.base64, "b64decode", counted_decode)
    validated = construct()
    assert getattr(validated, identity_field) == "Z" * 128
    assert 0 < calls["count"] <= 6_001


def _armed_model_subclass(
    parent: type[Any],
    payload: dict[str, Any],
    state: dict[str, Any],
) -> Any:
    class Armed(parent):
        def __getattribute__(self, name: str) -> Any:
            if state["armed"] and name != "__class__":
                state["calls"] += 1
                raise AssertionError(state["canary"])
            return super().__getattribute__(name)

    value = Armed.model_validate(payload)
    state["armed"] = True
    return value


@pytest.mark.parametrize(
    "hash_name",
    (
        "feature_configuration_hash",
        "feature_schema_hash",
        "feature_set_hash",
        "model_artifact_hash",
    ),
)
def test_exported_hash_helpers_require_exact_parent_type_without_callbacks(
    hash_name: str,
) -> None:
    api = _api()
    state = {"armed": False, "calls": 0, "canary": "HOSTILE-PARENT-CANARY"}
    if hash_name == "feature_configuration_hash":
        parent = api.FeatureConfiguration
        payload = _configuration(api).model_dump(mode="python")
        hash_helper = api.features_module.feature_configuration_hash
    elif hash_name == "feature_schema_hash":
        parent = api.FeatureSpec
        payload = _configuration(api).features[0].model_dump(mode="python")

        def hash_helper(value: object) -> str:
            return api.features_module.feature_schema_hash((value,))
    elif hash_name == "feature_set_hash":
        parent = api.FeatureSet
        payload = _features(api).model_dump(mode="python")
        hash_helper = api.features_module.feature_set_hash
    else:
        parent = api.ModelArtifact
        payload = _artifact(api).model_dump(mode="python")
        hash_helper = api.models_module.model_artifact_hash
    hostile = _armed_model_subclass(parent, payload, state)
    with pytest.raises(api.QuantInputError) as exc_info:
        hash_helper(hostile)
    assert state["calls"] == 0
    assert state["canary"] not in str(exc_info.value)


@pytest.mark.parametrize(
    "hash_name",
    (
        "feature_configuration_hash",
        "feature_schema_hash",
        "feature_set_hash",
        "model_artifact_hash",
    ),
)
def test_exported_hash_helpers_reject_outer_container_subclasses_without_callbacks(
    hash_name: str,
) -> None:
    api = _api()
    state = {"calls": 0, "canary": "HOSTILE-CONTAINER-CANARY"}

    class HostileDict(dict):
        def __getitem__(self, key: object) -> object:
            state["calls"] += 1
            raise AssertionError(state["canary"])

        def __iter__(self):
            state["calls"] += 1
            raise AssertionError(state["canary"])

    class HostileList(list):
        def __iter__(self):
            state["calls"] += 1
            raise AssertionError(state["canary"])

    if hash_name == "feature_configuration_hash":
        hostile: object = HostileDict(_config_payload())
        hash_helper = api.features_module.feature_configuration_hash
    elif hash_name == "feature_schema_hash":
        hostile = HostileList(_configuration(api).features)
        hash_helper = api.features_module.feature_schema_hash
    elif hash_name == "feature_set_hash":
        hostile = HostileDict(_features(api).model_dump(mode="python"))
        hash_helper = api.features_module.feature_set_hash
    else:
        hostile = HostileDict(_model_payload())
        hash_helper = api.models_module.model_artifact_hash
    with pytest.raises(api.QuantInputError) as exc_info:
        hash_helper(hostile)
    assert state["calls"] == 0
    assert state["canary"] not in str(exc_info.value)


@pytest.mark.parametrize(
    "hash_name",
    (
        "feature_configuration_hash",
        "feature_schema_hash",
        "feature_set_hash",
        "model_artifact_hash",
    ),
)
def test_exported_hash_helpers_reject_hostile_nested_models_without_callbacks(
    hash_name: str,
) -> None:
    api = _api()
    state = {"armed": False, "calls": 0, "canary": "HOSTILE-NESTED-CANARY"}
    if hash_name in {"feature_configuration_hash", "feature_schema_hash"}:
        parent = api.FeatureSpec
        payload = _configuration(api).features[0].model_dump(mode="python")
    elif hash_name == "feature_set_hash":
        parent = api.FeatureObservation
        payload = _features(api).observations[0].model_dump(mode="python")
    else:
        parent = api.ModelFeature
        payload = _artifact(api).features[0].model_dump(mode="python")
    hostile = _armed_model_subclass(parent, payload, state)
    if hash_name == "feature_configuration_hash":
        exact_parent = _configuration(api)
        object.__setattr__(
            exact_parent,
            "features",
            (hostile, *exact_parent.features[1:]),
        )
        hash_helper = api.features_module.feature_configuration_hash
        value: object = exact_parent
    elif hash_name == "feature_schema_hash":
        hash_helper = api.features_module.feature_schema_hash
        value = (hostile,)
    elif hash_name == "feature_set_hash":
        exact_parent = _features(api)
        object.__setattr__(
            exact_parent,
            "observations",
            (hostile, *exact_parent.observations[1:]),
        )
        hash_helper = api.features_module.feature_set_hash
        value = exact_parent
    else:
        exact_parent = _artifact(api)
        object.__setattr__(
            exact_parent,
            "features",
            (hostile, *exact_parent.features[1:]),
        )
        hash_helper = api.models_module.model_artifact_hash
        value = exact_parent
    with pytest.raises(api.QuantInputError) as exc_info:
        hash_helper(value)
    assert state["calls"] == 0
    assert state["canary"] not in str(exc_info.value)


def test_exported_hash_helpers_accept_normal_exact_instances() -> None:
    api = _api()
    configuration = _configuration(api)
    feature_set = _features(api)
    artifact = _artifact(api)
    assert (
        api.features_module.feature_configuration_hash(configuration)
        == configuration.content_hash
    )
    assert (
        api.features_module.feature_schema_hash(configuration.features)
        == artifact.feature_schema_hash
    )
    assert api.features_module.feature_set_hash(feature_set) == feature_set.feature_hash
    assert api.models_module.model_artifact_hash(artifact) == artifact.content_hash


@pytest.mark.parametrize("container_type", (tuple, list))
@pytest.mark.parametrize("count", (33, 10_000))
def test_feature_schema_hash_caps_collection_before_nested_copy(
    container_type: type[tuple[Any, ...]] | type[list[Any]],
    count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    spec = _configuration(api).features[0]
    features = container_type([spec] * count)
    calls = {"count": 0}

    def tripwire(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        raise AssertionError("nested feature copy executed")

    monkeypatch.setattr(api.features_module, "_copy_feature_spec", tripwire)
    monkeypatch.setattr(api.features_module, "_spec_payload", tripwire)
    with pytest.raises(api.QuantInputError):
        api.features_module.feature_schema_hash(features)
    assert calls["count"] == 0


@pytest.mark.parametrize("count", (33, 10_000))
def test_feature_configuration_hash_caps_features_before_sensitive_walk(
    count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    configuration = _configuration(api)
    object.__setattr__(
        configuration,
        "features",
        (configuration.features[0],) * count,
    )
    calls = {"count": 0}

    def tripwire(*args: Any, **kwargs: Any) -> None:
        calls["count"] += 1
        raise AssertionError("sensitive traversal executed")

    monkeypatch.setattr(api.features_module, "_prevalidate_sensitive", tripwire)
    monkeypatch.setattr(api.features_module, "_spec_payload", tripwire)
    with pytest.raises(api.QuantInputError):
        api.features_module.feature_configuration_hash(configuration)
    assert calls["count"] == 0


@pytest.mark.parametrize(
    "field",
    (
        "observations",
        "missing_required_feature_ids",
        "missing_optional_feature_ids",
        "reason_codes",
    ),
)
@pytest.mark.parametrize("count", (33, 10_000))
def test_feature_set_hash_caps_collections_before_sensitive_walk(
    field: str,
    count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    feature_set = _features(api)
    if field == "observations":
        value: tuple[Any, ...] = (feature_set.observations[0],) * count
    elif field == "reason_codes":
        value = ("optional_feature_missing",) * count
    else:
        value = ("safe-feature-id",) * count
    object.__setattr__(feature_set, field, value)
    calls = {"count": 0}

    def tripwire(*args: Any, **kwargs: Any) -> None:
        calls["count"] += 1
        raise AssertionError("sensitive traversal executed")

    monkeypatch.setattr(api.features_module, "_prevalidate_sensitive", tripwire)
    monkeypatch.setattr(api.features_module, "_feature_set_payload", tripwire)
    with pytest.raises(api.QuantInputError):
        api.features_module.feature_set_hash(feature_set)
    assert calls["count"] == 0


@pytest.mark.parametrize("count", (33, 10_000))
def test_model_artifact_hash_caps_features_before_sensitive_walk(
    count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    artifact = _artifact(api)
    object.__setattr__(artifact, "features", (artifact.features[0],) * count)
    calls = {"count": 0}

    def tripwire(*args: Any, **kwargs: Any) -> None:
        calls["count"] += 1
        raise AssertionError("sensitive traversal executed")

    monkeypatch.setattr(api.models_module, "_prevalidate_model_sensitive", tripwire)
    monkeypatch.setattr(api.models_module, "_artifact_payload", tripwire)
    with pytest.raises(api.QuantInputError):
        api.models_module.model_artifact_hash(artifact)
    assert calls["count"] == 0


def _context_validation_case(
    api: SimpleNamespace,
    model_name: str,
    identifier: str,
) -> tuple[type[Any], dict[str, Any], str]:
    if model_name == "FeatureSpec":
        return (
            api.FeatureSpec,
            {**_config_payload()["features"][0], "feature_id": identifier},
            "feature_id",
        )
    if model_name == "FeatureConfiguration":
        return (
            api.FeatureConfiguration,
            _rehashed_configuration_payload(identifier),
            "configuration_id",
        )
    if model_name == "FeatureObservation":
        return (
            api.FeatureObservation,
            {
                **_features(api).observations[0].model_dump(mode="json"),
                "feature_id": identifier,
            },
            "feature_id",
        )
    if model_name == "FeatureSet":
        payload = _features(api).model_dump(mode="json")
        payload["instrument_id"] = identifier
        payload.pop("feature_hash")
        payload["feature_hash"] = _canonical_hash(
            HASH_DOMAINS["feature_set"], payload
        )
        return api.FeatureSet, payload, "instrument_id"
    if model_name == "ModelFeature":
        return (
            api.ModelFeature,
            {**_model_payload()["features"][0], "feature_id": identifier},
            "feature_id",
        )
    if model_name == "ModelArtifact":
        return api.ModelArtifact, _rehashed_model_payload(identifier), "model_id"
    payload = _rekey_signal_payload(
        {**_score(api).model_dump(mode="json"), "run_id": identifier}
    )
    return api.QuantSignal, payload, "run_id"


_CONTEXT_MODEL_NAMES = (
    "FeatureSpec",
    "FeatureConfiguration",
    "FeatureObservation",
    "FeatureSet",
    "ModelFeature",
    "ModelArtifact",
    "QuantSignal",
)
_CONTEXT_SAFE_IDENTIFIER = "context-safe-identifier"
_CONTEXT_SECRET_IDENTIFIER = "api_key=round12-secret-value"


@pytest.mark.parametrize("model_name", _CONTEXT_MODEL_NAMES)
@pytest.mark.parametrize("accepted", (True, False))
def test_model_validate_never_mutates_or_retains_caller_context(
    model_name: str,
    accepted: bool,
) -> None:
    api = _api()
    identifier = (
        _CONTEXT_SAFE_IDENTIFIER if accepted else _CONTEXT_SECRET_IDENTIFIER
    )
    model, payload, identity_field = _context_validation_case(
        api, model_name, identifier
    )
    sentinel = object()
    context = {"user-sentinel": sentinel}
    if accepted:
        validated = model.model_validate(payload, context=context)
        assert getattr(validated, identity_field) == identifier
    else:
        with pytest.raises((ValidationError, api.QuantInputError, ValueError)) as exc_info:
            model.model_validate(payload, context=context)
        assert identifier not in str(exc_info.value)
    assert context == {"user-sentinel": sentinel}
    assert _CONTEXT_SECRET_IDENTIFIER not in repr(context)


@pytest.mark.parametrize("model_name", _CONTEXT_MODEL_NAMES)
@pytest.mark.parametrize(
    ("budget_state", "identifier", "accepted"),
    (
        ("empty-preseeded", _CONTEXT_SAFE_IDENTIFIER, True),
        ("memo-rejects-safe", _CONTEXT_SAFE_IDENTIFIER, True),
        ("memo-allows-secret", _CONTEXT_SECRET_IDENTIFIER, False),
        ("raised-exhausted", _CONTEXT_SAFE_IDENTIFIER, True),
    ),
)
def test_model_validate_ignores_external_private_decode_budget(
    model_name: str,
    budget_state: str,
    identifier: str,
    accepted: bool,
) -> None:
    api = _api()
    import mytradingalpha.contracts.signals as signal_contracts

    model, payload, identity_field = _context_validation_case(
        api, model_name, identifier
    )
    budget = signal_contracts._DecodeBudget(6_000)
    if budget_state == "memo-rejects-safe":
        budget.memo[identifier] = True
    elif budget_state == "memo-allows-secret":
        budget.memo[identifier] = False
    elif budget_state == "raised-exhausted":
        budget = signal_contracts._DecodeBudget(1)
        budget.consume()
        with pytest.raises(ValueError):
            budget.consume()
    before = (budget.attempts, budget.limit, dict(budget.memo))
    sentinel = object()
    context = {
        "user-sentinel": sentinel,
        signal_contracts._VALIDATION_BUDGET_KEY: budget,
    }
    if accepted:
        validated = model.model_validate(payload, context=context)
        assert getattr(validated, identity_field) == identifier
    else:
        with pytest.raises((ValidationError, api.QuantInputError, ValueError)) as exc_info:
            model.model_validate(payload, context=context)
        assert identifier not in str(exc_info.value)
    assert context == {
        "user-sentinel": sentinel,
        signal_contracts._VALIDATION_BUDGET_KEY: budget,
    }
    assert (budget.attempts, budget.limit, budget.memo) == before


@pytest.mark.parametrize("model_name", _CONTEXT_MODEL_NAMES)
def test_reused_caller_context_behaves_like_fresh_requests(model_name: str) -> None:
    api = _api()
    accepted_model, accepted_payload, identity_field = _context_validation_case(
        api, model_name, _CONTEXT_SAFE_IDENTIFIER
    )
    rejected_model, rejected_payload, _ = _context_validation_case(
        api, model_name, _CONTEXT_SECRET_IDENTIFIER
    )
    sentinel = object()
    context = {"user-sentinel": sentinel}
    for _ in range(2):
        validated = accepted_model.model_validate(accepted_payload, context=context)
        assert getattr(validated, identity_field) == _CONTEXT_SAFE_IDENTIFIER
        with pytest.raises((ValidationError, api.QuantInputError, ValueError)):
            rejected_model.model_validate(rejected_payload, context=context)
    assert context == {"user-sentinel": sentinel}


@pytest.mark.parametrize("model_name", _CONTEXT_MODEL_NAMES)
def test_concurrently_reused_caller_context_has_request_isolation(
    model_name: str,
) -> None:
    api = _api()
    accepted_model, accepted_payload, identity_field = _context_validation_case(
        api, model_name, _CONTEXT_SAFE_IDENTIFIER
    )
    rejected_model, rejected_payload, _ = _context_validation_case(
        api, model_name, _CONTEXT_SECRET_IDENTIFIER
    )
    sentinel = object()
    context = {"user-sentinel": sentinel}

    def validate_one(accepted: bool) -> bool:
        if accepted:
            try:
                validated = accepted_model.model_validate(
                    deepcopy(accepted_payload), context=context
                )
            except (ValidationError, api.QuantInputError, ValueError):
                return False
            return getattr(validated, identity_field) == _CONTEXT_SAFE_IDENTIFIER
        try:
            rejected_model.model_validate(
                deepcopy(rejected_payload), context=context
            )
        except (ValidationError, api.QuantInputError, ValueError):
            return True
        return False

    expected = (True, False, True, False, True, False, True, False)
    with ThreadPoolExecutor(max_workers=len(expected)) as executor:
        results = tuple(executor.map(validate_one, expected))
    assert results == (True,) * len(expected)
    assert context == {"user-sentinel": sentinel}
    assert _CONTEXT_SECRET_IDENTIFIER not in repr(context)


def test_gapped_calendar_never_turns_cross_range_lookback_available() -> None:
    api = _api()
    feature_set = _features(
        api,
        bundle=_bundle(
            calendar=_gapped_quant_calendar(),
            bars=_gapped_bars(),
        ),
    )
    observations = {item.feature_id: item for item in feature_set.observations}
    assert _status(feature_set) == "invalid"
    assert feature_set.missing_required_feature_ids == ("close_return_1d",)
    assert feature_set.missing_optional_feature_ids == (
        "close_return_2d_optional",
    )
    assert _codes(feature_set) == (
        "insufficient_lookback",
        "required_feature_missing",
    )
    for observation in observations.values():
        assert observation.status == "missing"
        assert observation.reason_code.value == "insufficient_lookback"
        assert observation.value is None
        assert observation.source_session_dates == ()


@pytest.mark.parametrize(
    "cutoff",
    (
        "2024-04-01T20:04:00Z",
        "2024-07-03T20:04:00Z",
    ),
)
def test_cutoff_without_verified_calendar_coverage_is_unavailable(
    cutoff: str,
) -> None:
    api = _api()
    feature_set = _features(
        api,
        bundle=_bundle(
            calendar=_gapped_quant_calendar(),
            bars=_gapped_bars(),
            cutoff=cutoff,
        ),
    )
    assert _status(feature_set) == "invalid"
    assert feature_set.missing_required_feature_ids == ("close_return_1d",)
    assert feature_set.missing_optional_feature_ids == (
        "close_return_2d_optional",
    )
    assert _codes(feature_set) == (
        "calendar_session_unavailable",
        "required_feature_missing",
    )
    assert all(
        observation.reason_code is not None
        and observation.reason_code.value == "calendar_session_unavailable"
        for observation in feature_set.observations
    )


def test_same_range_weekend_closures_preserve_valid_lookback() -> None:
    api = _api()
    required_spec = _configuration(api).features[0]
    configuration = api.FeatureConfiguration.create(
        configuration_id="same-range-weekend-config",
        configuration_version="v1",
        universe_id="us-liquid-v1",
        calendar_id="XNYS.synthetic.v1",
        horizon_sessions=1,
        features=(required_spec,),
    )
    feature_set = _features(
        api,
        configuration=configuration,
        bundle=_bundle(
            calendar=_gapped_quant_calendar(),
            bars=_gapped_bars(),
            cutoff="2024-03-11T20:04:00Z",
        ),
    )
    assert _status(feature_set) == "valid"
    assert feature_set.missing_required_feature_ids == ()
    assert feature_set.missing_optional_feature_ids == ()
    assert _codes(feature_set) == ()
    assert len(feature_set.observations) == 1
    observation = feature_set.observations[0]
    assert observation.value == Decimal("0.100000000000")
    assert observation.source_session_dates == ("2024-03-08", "2024-03-11")

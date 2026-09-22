"""SIG-03 contract tests for deterministic features and the shadow-only QuantSignal.

The quant API is imported inside test execution deliberately.  The RED commit must
collect successfully on the dependency-valid base even though the SIG-03 modules do
not exist yet; a missing API is an expected RED failure, not a collection failure.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import os
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
    BundleReplayPolicy,
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


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _contract_fixture() -> dict[str, Any]:
    return _load_json(QUANT_FIXTURE)


def _pit_fixture() -> dict[str, Any]:
    return _load_json(PIT_FIXTURES / "evidence_bundle_v1.json")


def _pit_source(name: str) -> dict[str, Any]:
    payload = _pit_fixture()["source_fixtures"]
    assert isinstance(payload, dict)
    source = payload[name]
    assert isinstance(source, str)
    return _load_json(PIT_FIXTURES / source)


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
    source = _pit_source(source_name)[collection]
    assert isinstance(indexes, list)
    assert isinstance(source, list)
    return tuple(deepcopy(source[index]) for index in indexes)


def _models(source_name: str, collection: str, model: type[Any]) -> tuple[Any, ...]:
    return tuple(model.model_validate(item) for item in _indexed(source_name, collection))


def _additional_instruments() -> tuple[Instrument, ...]:
    candidates = _pit_fixture()["additional_instruments"]
    assert isinstance(candidates, list)
    return tuple(Instrument.model_validate(item) for item in candidates)


def _manifest(session_date: str, *, revision: int = 0, source: str = "synthetic-quant-bars") -> SourceManifest:
    session = _calendar().session(session_date)
    close = session.close_at
    available = close + timedelta(minutes=1)
    fetched = available + timedelta(minutes=1)
    ingested = fetched + timedelta(minutes=1)
    digest = hashlib.sha256(f"{source}:{session_date}:{revision}".encode()).hexdigest()
    return SourceManifest(
        schema_version="v1",
        manifest_id=f"{source}-{session_date}-r{revision}",
        source=source,
        source_locator=f"fixture://quant/bars/{session_date}/r{revision}",
        fetched_at=fetched,
        event_time=close,
        published_at=None,
        available_at=available,
        ingested_at=ingested,
        checksum=f"sha256:{digest}",
        terms="synthetic quant contract fixture",
        revision=revision,
    )


def _bar(session_date: str, close: str, *, volume: int = 1_000_000) -> DailyBar:
    return DailyBar(
        schema_version="v1",
        bar_id=f"bar-inst-survivor-{session_date}",
        instrument_id="inst-survivor",
        calendar_id="XNYS.synthetic.v1",
        session_date=session_date,
        interval="1d",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        adjustment_basis=AdjustmentBasis.UNADJUSTED,
        adjustment_version=None,
        finality=BarFinality.FINAL,
        manifest=_manifest(session_date),
    )


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
    cutoff: str = "2024-07-03T23:59:59Z",
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
        bar_candidates=(
            bars
            if bars is not None
            else (
                _bar("2024-03-08", "100.00"),
                _bar("2024-03-11", "110.00"),
                _bar("2024-07-02", "121.00"),
            )
        ),
        filing_candidates=_models("financial_vintages", "filings", FinancialFiling),
        event_candidates=_models("events_social_macro", "events", NewsEvent),
        social_post_candidates=(),
        macro_observation_candidates=_models(
            "events_social_macro", "macro_observations", MacroObservation
        ),
    )


def _api() -> SimpleNamespace:
    """Load the public SIG-03 API only after pytest collection."""

    try:
        from mytradingalpha.contracts.signals import QuantSignal, QuantSignalStatus
        from mytradingalpha.quant.features import (
            FeatureConfiguration,
            FeatureSet,
            FeatureSpec,
        )
        from mytradingalpha.quant.models import ModelArtifact
        from mytradingalpha.quant.signal import QuantSignalModel
    except (ImportError, AttributeError) as exc:
        pytest.fail(f"SIG-03 API missing: {exc}")
    return SimpleNamespace(
        FeatureConfiguration=FeatureConfiguration,
        FeatureSet=FeatureSet,
        FeatureSpec=FeatureSpec,
        ModelArtifact=ModelArtifact,
        QuantSignal=QuantSignal,
        QuantSignalModel=QuantSignalModel,
        QuantSignalStatus=QuantSignalStatus,
    )


def _configuration(api: SimpleNamespace, **overrides: Any) -> Any:
    fixture = _contract_fixture()["configuration"]
    fields = deepcopy(fixture)
    fields["features"] = tuple(api.FeatureSpec.model_validate(item) for item in fields["features"])
    fields.update(overrides)
    return api.FeatureConfiguration(**fields)


def _artifact(api: SimpleNamespace, **overrides: Any) -> Any:
    fields = deepcopy(_contract_fixture()["model"])
    fields["feature_schema"] = tuple(fields["feature_schema"])
    fields.update(overrides)
    return api.ModelArtifact(**fields)


def _features(api: SimpleNamespace, bundle: EvidenceBundle | None = None, **overrides: Any) -> Any:
    fixture = _contract_fixture()
    fields = {
        "bundle": bundle or _bundle(),
        "instrument_id": fixture["instrument_id"],
        "as_of": fixture["as_of"],
        "horizon_sessions": fixture["horizon_sessions"],
        "configuration": _configuration(api),
    }
    fields.update(overrides)
    return api.FeatureSet.compute(**fields)


def _score(api: SimpleNamespace, *, bundle: EvidenceBundle | None = None, **overrides: Any) -> Any:
    features = _features(api, bundle=bundle, **overrides)
    return api.QuantSignalModel(_artifact(api)).score(features)


def _reason(result: Any) -> str | None:
    value = getattr(result, "reason_code", None)
    if value is not None:
        return getattr(value, "value", value)
    values = getattr(result, "reason_codes", ())
    return getattr(values[0], "value", values[0]) if values else None


def _status(result: Any) -> str:
    value = getattr(result, "status", None)
    return getattr(value, "value", value)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


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


def test_sig03_public_wire_and_status_contract_is_exact() -> None:
    api = _api()
    assert set(api.QuantSignal.model_fields) == {
        "schema_version",
        "signal_id",
        "bundle_id",
        "instrument_id",
        "as_of",
        "horizon_sessions",
        "feature_ids",
        "feature_hash",
        "model_id",
        "model_version",
        "model_hash",
        "score",
        "status",
        "reason_code",
    }
    assert {item.value for item in api.QuantSignalStatus} == {
        "valid",
        "degraded",
        "invalid",
    }
    _assert_no_authority_fields(api.QuantSignal)
    signal = _score(api)
    assert _status(signal) == "valid"
    assert signal.reason_code is None
    assert signal.score == Decimal("0.200000000000")
    assert signal.horizon_sessions == 1
    assert signal.as_of == datetime(2024, 7, 2, 20, tzinfo=timezone.utc)


def test_feature_configuration_freezes_exact_source_calendar_universe_and_adjustment_selectors() -> None:
    api = _api()
    config = _configuration(api)
    assert config.replay_policy == BundleReplayPolicy.ARCHIVE_REALISTIC
    assert config.configuration_id == "feature-config-sig03-v1"
    assert tuple(item.feature_id for item in config.features) == (
        "close_return_1d",
        "optional_volume_return_1d",
    )
    for feature in config.features:
        assert feature.source == "synthetic-quant-bars"
        assert feature.calendar_id == "XNYS.synthetic.v1"
        assert feature.universe_id == "us-liquid-v1"
        assert feature.adjustment_basis == AdjustmentBasis.UNADJUSTED
        assert feature.adjustment_version is None
    with pytest.raises(ValidationError):
        api.FeatureSpec.model_validate(
            {
                **_contract_fixture()["configuration"]["features"][0],
                "unexpected_authority": "orders",
            }
        )
    with pytest.raises(ValidationError):
        api.FeatureConfiguration.model_validate(
            {
                **_contract_fixture()["configuration"],
                "replay_policy": "live_now",
            }
        )


def test_feature_and_model_hashes_are_golden_and_order_invariant() -> None:
    api = _api()
    config = _configuration(api)
    artifact = _artifact(api)
    assert artifact.content_hash == _contract_fixture()["expected_model_hash"]
    first = _features(api)
    reversed_config = _configuration(api, features=tuple(reversed(config.features)))
    second = _features(api, configuration=reversed_config)
    assert first.feature_hash == _contract_fixture()["expected_feature_hash"]
    assert first.feature_hash == second.feature_hash
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert artifact.model_dump(mode="json") == _artifact(
        api,
        feature_schema=tuple(reversed(artifact.feature_schema)),
        weights={key: artifact.weights[key] for key in reversed(tuple(artifact.weights))},
    ).model_dump(mode="json")


def test_model_artifact_is_plain_data_canonical_and_immutable() -> None:
    api = _api()
    artifact = _artifact(api)
    assert artifact.content_hash.startswith("sha256:")
    assert artifact.feature_schema == ("close_return_1d", "optional_volume_return_1d")
    assert artifact.weights["close_return_1d"] == Decimal("2.000000000000")
    assert artifact.defaults["optional_volume_return_1d"] == Decimal("0.000000000000")
    assert artifact.bias == Decimal("0.000000000000")
    with pytest.raises((TypeError, ValidationError, AttributeError)):
        artifact.weights["close_return_1d"] = Decimal("9")
    with pytest.raises((TypeError, ValidationError, AttributeError)):
        artifact.artifact_id = "changed"
    assert not hasattr(artifact, "loader")
    assert not hasattr(artifact, "callable")
    assert not hasattr(artifact, "provider")
    assert not hasattr(artifact, "pickle")


def test_close_return_uses_exact_sessions_without_gap_fallback() -> None:
    api = _api()
    result = _features(api)
    assert result.values["close_return_1d"] == Decimal("0.100000000000")
    missing_expected_session = _bundle(
        bars=(_bar("2024-03-08", "100.00"), _bar("2024-07-02", "121.00")),
    )
    result = _features(api, bundle=missing_expected_session)
    assert _status(result) == "invalid"
    assert _reason(result) == "insufficient_lookback"


def test_required_invalid_and_optional_degraded_are_distinct() -> None:
    api = _api()
    required_only = _configuration(
        api,
        features=(
            api.FeatureSpec.model_validate(_contract_fixture()["configuration"]["features"][0]),
        ),
    )
    required_feature = required_only.features[0].model_copy(
        update={"source": "synthetic-quant-required-missing"}
    )
    invalid = _features(
        api,
        configuration=_configuration(api, features=(required_feature,)),
    )
    assert _status(invalid) == "invalid"
    assert _reason(invalid) == "required_feature_missing"
    degraded = _features(api)
    assert _status(degraded) == "valid"
    no_optional = _configuration(
        api,
        features=tuple(
            api.FeatureSpec.model_validate(item)
            for item in _contract_fixture()["configuration"]["features"]
        ),
    )
    optional_features = list(no_optional.features)
    optional_features[1] = optional_features[1].model_copy(
        update={"source": "synthetic-quant-optional-missing"}
    )
    optional_result = _features(
        api,
        configuration=_configuration(api, features=tuple(optional_features)),
    )
    assert _status(optional_result) == "degraded"
    assert _reason(optional_result) == "optional_feature_missing"


def test_signal_score_is_fixed_decimal_half_even_and_bounded() -> None:
    api = _api()
    artifact = _artifact(
        api,
        weights={"close_return_1d": "1000000000000.5", "optional_volume_return_1d": "0"},
        bias="0.0000000000005",
    )
    signal = api.QuantSignalModel(artifact).score(_features(api))
    assert signal.score == Decimal("1.000000000000")
    assert signal.score.as_tuple().exponent == -12
    with pytest.raises(ValidationError):
        api.ModelArtifact.model_validate(
            {**_contract_fixture()["model"], "weights": {"close_return_1d": 0.5}}
        )
    for value in ("NaN", "Infinity", "-Infinity", "1e100000"):
        with pytest.raises(ValidationError):
            api.ModelArtifact.model_validate(
                {**_contract_fixture()["model"], "bias": value}
            )


def test_signal_rejects_float_bool_nonfinite_and_extreme_decimal_inputs() -> None:
    api = _api()
    base = _contract_fixture()["model"]
    for field in ("bias", "score_scale"):
        for value in (0.1, True, "NaN", "Infinity", "1e100000"):
            with pytest.raises(ValidationError):
                api.ModelArtifact.model_validate({**base, field: value})
    with pytest.raises(ValidationError):
        api.FeatureSpec.model_validate(
            {**_contract_fixture()["configuration"]["features"][0], "lookback_sessions": True}
        )


def test_model_and_feature_size_caps_fail_closed() -> None:
    api = _api()
    with pytest.raises(ValidationError):
        api.FeatureConfiguration(
            **{
                **_contract_fixture()["configuration"],
                "features": tuple(
                    api.FeatureSpec.model_validate(
                        {
                            **_contract_fixture()["configuration"]["features"][0],
                            "feature_id": f"f-{i}",
                        }
                    )
                    for i in range(17)
                ),
            }
        )
    with pytest.raises(ValidationError):
        api.FeatureSpec.model_validate(
            {
                **_contract_fixture()["configuration"]["features"][0],
                "lookback_sessions": 33,
            }
        )
    with pytest.raises(ValidationError):
        api.ModelArtifact(
            **{
                **_contract_fixture()["model"],
                "feature_schema": tuple(f"f-{i}" for i in range(17)),
                "weights": {f"f-{i}": "1" for i in range(17)},
            }
        )


def test_instrument_resolution_is_identity_and_membership_safe() -> None:
    api = _api()
    for instrument_id, expected in (
        ("does-not-exist", "instrument_not_in_bundle"),
        ("inst-acme", "instrument_inactive_as_of"),
    ):
        result = _features(api, instrument_id=instrument_id)
        assert _status(result) == "invalid"
        assert _reason(result) == expected
    nonmember = _bundle(
        memberships=tuple(
            item for item in _models("universe_actions", "memberships", UniverseMembership)
            if item.instrument_id != "inst-survivor"
        ),
    )
    result = _features(api, bundle=nonmember)
    assert _status(result) == "invalid"
    assert _reason(result) == "instrument_not_in_universe"


def test_ambiguous_membership_and_ambiguous_bar_series_fail_closed() -> None:
    api = _api()
    memberships = list(_models("universe_actions", "memberships", UniverseMembership))
    memberships.append(
        memberships[1].model_copy(
            update={
                "membership_id": "membership-ambiguous",
                "universe_id": "us-liquid-v1",
                "valid_from": "2024-01-01",
                "valid_to": None,
            }
        )
    )
    result = _features(
        api,
        bundle=_bundle().model_copy(update={"memberships": tuple(memberships)}),
    )
    assert _status(result) == "invalid"
    assert _reason(result) == "ambiguous_universe_membership"
    ambiguous_bars = (
        _bar("2024-03-08", "100.00"),
        _bar("2024-03-11", "110.00"),
        _bar("2024-07-02", "121.00"),
        _bar("2024-07-02", "121.00", volume=2_000_000),
    )
    result = _features(api, bundle=_bundle().model_copy(update={"bars": ambiguous_bars}))
    assert _status(result) == "invalid"
    assert _reason(result) == "bar_series_ambiguous"


def test_calendar_source_adjustment_and_version_ambiguity_are_explicit() -> None:
    api = _api()
    cases = (
        ({"calendar_id": "other-calendar"}, "calendar_session_unavailable"),
        ({"source": "other-source"}, "bar_series_ambiguous"),
        ({"adjustment_basis": "provider_adjusted"}, "bar_series_ambiguous"),
        ({"adjustment_version": "provider-v2"}, "bar_series_ambiguous"),
    )
    for updates, expected in cases:
        features = tuple(
            api.FeatureSpec.model_validate(
                {
                    **_contract_fixture()["configuration"]["features"][0],
                    **updates,
                }
            )
        )
        result = _features(api, configuration=_configuration(api, features=features))
        assert _status(result) == "invalid"
        assert _reason(result) == expected


def test_cutoff_future_and_revision_rules_are_fail_closed() -> None:
    api = _api()
    future_cutoff = _bundle(cutoff="2024-07-02T20:00:00Z")
    result = _features(api, bundle=future_cutoff)
    assert _status(result) == "invalid"
    assert _reason(result) in {"calendar_session_unavailable", "exact_session_bar_missing"}
    future_bar = _bar("2024-07-02", "121.00")
    future_bar = future_bar.model_copy(
        update={
            "manifest": future_bar.manifest.model_copy(
                update={"available_at": "2024-07-03T00:00:00Z"}
            )
        }
    )
    result = _features(
        api,
        bundle=_bundle().model_copy(
            update={
                "bars": (
                    _bar("2024-03-08", "100"),
                    _bar("2024-03-11", "110"),
                    future_bar,
                )
            }
        ),
    )
    assert _status(result) == "invalid"
    assert _reason(result) == "exact_session_bar_missing"
    revised = _bar("2024-07-02", "121.00", revision=1)
    result = _features(
        api,
        bundle=_bundle().model_copy(
            update={
                "bars": (
                    _bar("2024-03-08", "100"),
                    _bar("2024-03-11", "110"),
                    revised,
                )
            }
        ),
    )
    assert _status(result) == "invalid"
    assert _reason(result) in {"exact_session_bar_missing", "bar_series_ambiguous"}


def test_replay_policy_is_strict_and_never_uses_created_or_wall_clock_time() -> None:
    api = _api()
    with pytest.raises((ValidationError, ValueError)):
        _configuration(api, replay_policy="availability")
    with pytest.raises((ValidationError, ValueError)):
        _bundle(replay_policy="availability")
    bundle = _bundle()
    created_late = bundle.model_copy(update={"created_at": datetime(2099, 1, 1, tzinfo=timezone.utc)})
    first = _score(api, bundle=bundle)
    second = _score(api, bundle=created_late)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_hostile_subclasses_callbacks_custom_containers_and_mutation_are_rejected() -> None:
    api = _api()

    class FeatureSpecSubclass(api.FeatureSpec):
        pass

    class CallbackMap(dict[str, Any]):
        def __iter__(self):
            raise AssertionError("custom container executed")

    class EvilBundle(EvidenceBundle):
        def __getattribute__(self, name: str) -> Any:
            if name == "bars":
                raise AssertionError("hostile bundle hook executed")
            return super().__getattribute__(name)

    with pytest.raises((ValidationError, TypeError, ValueError)):
        api.FeatureSpec.model_validate(FeatureSpecSubclass.model_validate(_contract_fixture()["configuration"]["features"][0]))
    with pytest.raises((ValidationError, TypeError, ValueError)):
        api.ModelArtifact.model_validate(CallbackMap(_contract_fixture()["model"]))
    with pytest.raises((ValidationError, TypeError, ValueError, AssertionError)):
        api.FeatureConfiguration.model_validate(
            {
                **_contract_fixture()["configuration"],
                "features": CallbackMap(
                    {"feature": _contract_fixture()["configuration"]["features"][0]}
                ),
            }
        )
    features = _features(api)
    before = features.feature_hash
    with pytest.raises((TypeError, ValidationError, AttributeError)):
        features.values["close_return_1d"] = Decimal("9")
    assert features.feature_hash == before
    with pytest.raises((ValidationError, TypeError, ValueError, AssertionError)):
        _features(api, bundle=EvilBundle.model_validate(_bundle().model_dump(mode="python")))


def test_unicode_surrogates_and_secret_bearing_identifiers_are_safe() -> None:
    api = _api()
    for identifier in ("bad\ud800", "api-key-123", "secret-token", "password"):
        with pytest.raises(ValidationError):
            api.FeatureSpec.model_validate(
                {
                    **_contract_fixture()["configuration"]["features"][0],
                    "feature_id": identifier,
                }
            )
    with pytest.raises(ValidationError):
        api.ModelArtifact.model_validate(
            {**_contract_fixture()["model"], "artifact_id": "secret\udfff"}
        )
    assert "api-key" not in _features(api).model_dump_json()


def test_repeat_concurrent_subprocess_hashseed_and_decimal_context_are_invariant(tmp_path: Path) -> None:
    api = _api()
    baseline = _score(api).model_dump(mode="json")
    outputs = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        outputs.extend(pool.map(lambda _: _score(api).model_dump(mode="json"), range(16)))
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
    env = {**os.environ, "PYTHONHASHSEED": "random"}
    child = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(child.stdout) == baseline


def test_feature_path_denies_network_filesystem_subprocess_provider_and_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    original_socket = socket.socket
    original_open = builtins.open

    def deny_socket(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    def deny_open(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("filesystem access is forbidden")

    monkeypatch.setattr(socket, "socket", deny_socket)
    monkeypatch.setattr(socket, "create_connection", deny_socket)
    monkeypatch.setattr(builtins, "open", deny_open)
    monkeypatch.setattr(subprocess, "run", deny_open)
    monkeypatch.setattr(subprocess, "Popen", deny_open)
    monkeypatch.setattr(datetime, "now", deny_open, raising=False)
    monkeypatch.setattr(datetime, "utcnow", deny_open, raising=False)
    monkeypatch.setattr(api.FeatureSet, "provider", property(lambda _: deny_open()), raising=False)
    assert _score(api).score == Decimal("0.200000000000")
    assert socket.socket is deny_socket
    assert builtins.open is deny_open
    assert original_socket is not deny_socket
    assert original_open is not deny_open


def test_static_quant_dependency_and_forbidden_authority_contract() -> None:
    quant_root = ROOT / "mytradingalpha" / "quant"
    forbidden_imports = (
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
    )
    forbidden_tokens = (
        "target_weight",
        "target_weights",
        "order_id",
        "broker",
        "portfolio",
        "LLMOverlay",
        "SignalEnvelope",
        "VariantRegistry",
    )
    for path in (*quant_root.glob("*.py"), ROOT / "mytradingalpha" / "contracts" / "signals.py"):
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert not any(f"import {name}" in source or f"from {name}" in source for name in forbidden_imports)
        assert not any(token in source for token in forbidden_tokens)

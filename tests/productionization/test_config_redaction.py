"""RED contract tests for the FND-03 configuration and observability boundary."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from mytradingalpha.contracts import RunContext

CONFIG_FIXTURES = Path(__file__).parent / "fixtures" / "config"
LOG_FIXTURE = Path(__file__).parent / "fixtures" / "logs" / "secret-bearing-record.json"

_NETWORK_COMPONENTS = (
    "data_capture_egress",
    "model_provider_egress",
    "research_tool_egress",
    "paper_broker_egress",
    "live_broker_egress",
)


def _historical_mapping() -> dict[str, Any]:
    return {
        "run": {
            "mode": "historical",
            "variant_id": "quant_only_v1",
            "decision_time": "2026-01-15T21:00:00Z",
            "knowledge_cutoff": "2026-01-15T21:00:00Z",
            "earliest_execution_time": "2026-01-16T14:30:00Z",
            "bundle_id": "bundle-2026-01-15-001",
            "bundle_hash": "sha256:0123456789abcdef",
            "calendar_id": "XNYS-regular-v1",
            "replay_policy": "archive_realistic",
        },
        "execution": {},
        "persistence": {
            "bundle_store": "fixture-bundle-store",
            "manifest_store": "fixture-manifest-store",
        },
    }


def _forward_paper_mapping() -> dict[str, Any]:
    return {
        "run": {
            "mode": "forward_paper",
            "variant_id": "quant_llm_v1",
            "calendar_id": "XNYS-regular-v1",
            "replay_policy": "availability",
            "network_policy": {
                "data_capture_egress": True,
                "model_provider_egress": True,
                "research_tool_egress": False,
                "paper_broker_egress": True,
                "live_broker_egress": False,
            },
        },
        "execution": {
            "paper_endpoint_id": "approved-paper-sandbox",
            "paper_write_enabled": False,
            "live_write_enabled": False,
        },
        "persistence": {
            "bundle_store": "fixture-bundle-store",
            "manifest_store": "fixture-manifest-store",
        },
    }


def _config_load(source: Any) -> Any:
    """Call the public loader without coupling tests to a private parser."""

    from mytradingalpha.ops.config import ProductionConfig

    return ProductionConfig.load(source)


def _config_dump(config: Any) -> dict[str, Any]:
    return config.model_dump(mode="json")


def _run_context_payload() -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "run_id": "run-2026-01-15-001",
        "mode": "historical",
        "variant_id": "quant_only_v1",
        "decision_time": "2026-01-15T21:00:00Z",
        "knowledge_cutoff": "2026-01-15T21:00:00Z",
        "earliest_execution_time": "2026-01-16T14:30:00Z",
        "bundle_id": "bundle-2026-01-15-001",
        "bundle_hash": "sha256:0123456789abcdef",
        "calendar_id": "XNYS-regular-v1",
    }


def test_production_loader_reads_the_non_secret_yaml_fixture() -> None:
    config = _config_load(CONFIG_FIXTURES / "historical.yaml")
    dumped = _config_dump(config)

    assert dumped["run"]["mode"] == "historical"
    assert dumped["run"]["variant_id"] == "quant_only_v1"
    assert dumped["persistence"]["bundle_store"] == "fixture-bundle-store"


@pytest.mark.parametrize("fixture_name", ["paper.yaml", "live-read-only.yaml"])
def test_nonhistorical_read_only_fixtures_keep_both_write_flags_disabled(fixture_name: str) -> None:
    dumped = _config_dump(_config_load(CONFIG_FIXTURES / fixture_name))

    assert dumped["execution"]["paper_write_enabled"] is False
    assert dumped["execution"]["live_write_enabled"] is False


def test_config_precedence_is_defaults_then_mapping_then_mytradingalpha_env(monkeypatch) -> None:
    monkeypatch.setenv("MYTRADINGALPHA_VARIANT_ID", "env-selected-variant")

    config = _config_load(_forward_paper_mapping())
    dumped = _config_dump(config)

    assert dumped["run"]["variant_id"] == "env-selected-variant"
    assert dumped["run"]["calendar_id"] == "XNYS-regular-v1"
    assert dumped["execution"]["paper_write_enabled"] is False
    assert dumped["execution"]["live_write_enabled"] is False


def test_allowlisted_component_environment_override_is_nested_under_run(monkeypatch) -> None:
    monkeypatch.setenv("MYTRADINGALPHA_DATA_CAPTURE_EGRESS", "false")

    dumped = _config_dump(_config_load(_forward_paper_mapping()))

    assert dumped["run"]["network_policy"]["data_capture_egress"] is False


@pytest.mark.parametrize(
    "environment_name, value",
    [
        ("MYTRADINGALPHA_PAPER_WRITE_ENABLED", "not-a-boolean"),
        ("MYTRADINGALPHA_UNSUPPORTED_FIELD", "value"),
    ],
)
def test_malformed_or_unknown_production_environment_fails_closed(
    monkeypatch, environment_name: str, value: str
) -> None:
    monkeypatch.setenv(environment_name, value)

    with pytest.raises(ValueError):
        _config_load(_forward_paper_mapping())


def test_config_resolution_materializes_the_all_false_default_network_policy() -> None:
    dumped = _config_dump(_config_load(_historical_mapping()))

    assert dumped["run"]["network_policy"] == dict.fromkeys(_NETWORK_COMPONENTS, False)


@pytest.mark.parametrize("field_name", ["mode", "variant_id", "calendar_id"])
def test_config_requires_explicit_mode_variant_and_calendar(field_name: str) -> None:
    config = _historical_mapping()
    config["run"].pop(field_name)

    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(config)


@pytest.mark.parametrize(
    "omitted_fields",
    [
        ("decision_time", "knowledge_cutoff", "earliest_execution_time"),
        ("bundle_id",),
        ("bundle_hash",),
    ],
)
def test_historical_config_requires_complete_time_and_bundle_metadata(
    omitted_fields: tuple[str, ...],
) -> None:
    config = _historical_mapping()
    for field_name in omitted_fields:
        config["run"].pop(field_name)

    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(config)


@pytest.mark.parametrize("field_name", ["bundle_id", "bundle_hash"])
def test_partial_bundle_identity_is_rejected_in_nonhistorical_modes(field_name: str) -> None:
    config = _forward_paper_mapping()
    config["run"][field_name] = "partial-bundle-identity"

    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(config)


def test_network_policy_is_component_scoped_immutable_extra_forbidden_and_deny_by_default() -> None:
    import mytradingalpha.contracts as contract_module
    from mytradingalpha.ops.config import NetworkPolicy

    policy = NetworkPolicy()

    assert contract_module.NetworkPolicy is NetworkPolicy
    assert policy.model_dump() == dict.fromkeys(_NETWORK_COMPONENTS, False)
    with pytest.raises((TypeError, ValidationError)):
        policy.data_capture_egress = True
    with pytest.raises(ValidationError):
        NetworkPolicy(unexpected_component=True)


def test_existing_v1_run_context_reads_with_an_all_false_network_policy() -> None:
    from mytradingalpha.ops.config import NetworkPolicy

    context = RunContext.model_validate(_run_context_payload())

    assert context.network_policy == NetworkPolicy()
    assert context.network_policy.model_dump() == dict.fromkeys(_NETWORK_COMPONENTS, False)


def test_historical_mode_fails_closed_for_any_egress_or_write_flag() -> None:
    policy_violation = _historical_mapping()
    policy_violation["run"]["network_policy"] = {"data_capture_egress": True}
    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(policy_violation)

    write_violation = _historical_mapping()
    write_violation["execution"]["live_write_enabled"] = True
    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(write_violation)


@pytest.mark.parametrize("component", ["research_tool_egress", "live_broker_egress"])
def test_forward_paper_cannot_enable_unapproved_network_components(component: str) -> None:
    policy_violation = _forward_paper_mapping()
    policy_violation["run"]["network_policy"][component] = True

    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(policy_violation)


def test_live_writes_are_rejected_before_phase_09_even_in_live_pilot_mode() -> None:
    config = _forward_paper_mapping()
    config["run"]["mode"] = "live_pilot"
    config["execution"]["live_write_enabled"] = True

    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(config)


def _live_read_only_mapping() -> dict[str, Any]:
    return yaml.safe_load(
        (CONFIG_FIXTURES / "live-read-only.yaml").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    ("section", "field_name"),
    [
        ("run", "live_level"),
        ("run", "required_gate_evidence_ref"),
        ("execution", "broker_endpoint_id"),
        ("execution", "secret_ref"),
    ],
)
def test_live_read_only_config_requires_complete_l0_gate_and_opaque_refs(
    section: str, field_name: str
) -> None:
    config = _live_read_only_mapping()
    config[section].pop(field_name)

    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(config)


def test_live_read_only_config_requires_human_approval_and_rejects_other_levels() -> None:
    missing_approval = _live_read_only_mapping()
    missing_approval["execution"]["human_approval_required"] = False
    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(missing_approval)

    unsupported_level = _live_read_only_mapping()
    unsupported_level["run"]["live_level"] = "L2"
    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(unsupported_level)


@pytest.mark.parametrize("mode", ["historical", "forward_paper"])
@pytest.mark.parametrize(
    ("section", "field_name", "value"),
    [
        ("run", "live_level", "L0"),
        ("run", "required_gate_evidence_ref", "unexpected-live-gate"),
        ("execution", "broker_endpoint_id", "unexpected-live-endpoint"),
        ("execution", "secret_ref", "unexpected-live-secret-ref"),
        ("execution", "human_approval_required", True),
    ],
)
def test_non_live_modes_reject_live_only_fields(
    mode: str, section: str, field_name: str, value: Any
) -> None:
    config = _historical_mapping() if mode == "historical" else _forward_paper_mapping()
    config[section][field_name] = value

    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(config)


@pytest.mark.parametrize("mode", ["historical", "live_pilot"])
@pytest.mark.parametrize("field_name", ["paper_endpoint_id", "approval_ref"])
def test_non_paper_modes_reject_paper_only_fields(mode: str, field_name: str) -> None:
    config = _historical_mapping() if mode == "historical" else _live_read_only_mapping()
    config["execution"][field_name] = "unexpected-paper-reference"

    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(config)


def test_paper_write_requires_forward_policy_approved_endpoint_and_approval_reference() -> None:
    missing_endpoint = _forward_paper_mapping()
    missing_endpoint["execution"]["paper_write_enabled"] = True
    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(missing_endpoint)

    approved = _forward_paper_mapping()
    approved["execution"].update(
        paper_write_enabled=True,
        paper_endpoint_id="approved-paper-sandbox",
        approval_ref="approved-paper-run-reference",
    )

    loaded = _config_load(approved)
    dumped = _config_dump(loaded)
    assert dumped["execution"]["paper_write_enabled"] is True
    assert dumped["execution"]["paper_endpoint_id"] == "approved-paper-sandbox"
    assert dumped["execution"]["approval_ref"] == "approved-paper-run-reference"


@pytest.mark.parametrize(
    "bad_update",
    [
        {"run": {"unexpected": "field"}},
        {"capture": {"provider_profile": "later-roadmap-field"}},
        {"execution": {"api_key": "fixture-api-key-not-secret"}},
        {"execution": {"password": "fixture-password-not-secret"}},
    ],
)
def test_config_rejects_unknown_or_secret_bearing_material(bad_update: dict[str, Any]) -> None:
    config = _historical_mapping()
    for section, values in bad_update.items():
        config.setdefault(section, {}).update(values)

    with pytest.raises((TypeError, ValueError, ValidationError)):
        _config_load(config)


def test_redaction_filter_scrubs_nested_and_formatted_secret_values() -> None:
    from mytradingalpha.ops.logging import RedactionFilter

    payload = json.loads(LOG_FIXTURE.read_text(encoding="utf-8"))
    secrets = tuple(payload.pop("_expected_secret_values"))
    formatted = logging.LogRecord(
        name="mytradingalpha.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="payload=%s authorization=%s",
        args=(payload, f"Bearer {secrets[1]}"),
        exc_info=None,
    )

    assert RedactionFilter().filter(formatted) is True
    rendered = formatted.getMessage()

    assert "redacted" in rendered.lower()
    assert all(secret not in rendered for secret in secrets)


def test_configured_logging_redacts_structured_text_and_raw_config_models() -> None:
    from mytradingalpha.ops.logging import configure_logging

    stream = StringIO()
    logger = logging.getLogger("mytradingalpha.test.redaction.end-to-end")
    logger.handlers.clear()
    configure_logging(logger=logger, stream=stream)

    config = _config_load(CONFIG_FIXTURES / "live-read-only.yaml")
    sentinels = (
        "json-secret-value",
        "json-access-secret",
        "refresh-secret-value",
        "quoted-secret-first",
        "quoted-secret-second",
        "approved-live-endpoint",
        "scoped-secret-reference",
        "phase-08-pass-record",
        "fixture-bundle-store",
        "fixture-manifest-store",
    )
    logger.info('{"api_key":"json-secret-value"}')
    logger.info('{"access_token": "json-access-secret"}')
    logger.info("refresh_token=refresh-secret-value")
    logger.info("password='quoted-secret-first quoted-secret-second'")
    logger.info("config=%s", config)

    rendered = stream.getvalue()

    assert "[REDACTED]" in rendered
    assert all(sentinel not in rendered for sentinel in sentinels)


@pytest.mark.parametrize(
    ("message", "sentinel"),
    [
        ("X-API-Key: x-api-key-sentinel", "x-api-key-sentinel"),
        ("X-Access-Token: x-access-token-sentinel", "x-access-token-sentinel"),
        ("X-Refresh-Token: x-refresh-token-sentinel", "x-refresh-token-sentinel"),
        ("provider_api_key=provider-api-key-sentinel", "provider-api-key-sentinel"),
        ("Authorization: Basic basic-auth-sentinel", "basic-auth-sentinel"),
        ("Authorization: Token token-auth-sentinel", "token-auth-sentinel"),
        ("Proxy-Authorization: Basic proxy-auth-sentinel", "proxy-auth-sentinel"),
        ("X-Authorization: Token x-auth-sentinel", "x-auth-sentinel"),
    ],
)
def test_configured_logging_redacts_prefixed_credentials_and_complete_authorization(
    message: str, sentinel: str
) -> None:
    from mytradingalpha.ops.logging import configure_logging

    stream = StringIO()
    logger = logging.getLogger("mytradingalpha.test.redaction.prefixed")
    logger.handlers.clear()
    configure_logging(logger=logger, stream=stream)

    logger.info(message)
    rendered = stream.getvalue()

    assert "[REDACTED]" in rendered
    assert sentinel not in rendered


def test_structured_logs_include_context_and_restore_nested_correlation_scopes() -> None:
    from mytradingalpha.ops.logging import configure_logging, correlation_scope

    stream = StringIO()
    logger = logging.getLogger("mytradingalpha.test.context")
    logger.handlers.clear()
    logger.propagate = False
    configure_logging(logger=logger, stream=stream)

    with correlation_scope(
        run_id="run-2026-01-15-001",
        correlation_id="corr-outer-001",
        mode="historical",
        variant_id="quant_only_v1",
        schema_version="v1",
    ):
        logger.info("outer")
        with correlation_scope(correlation_id="corr-inner-001"):
            logger.info("inner")
        logger.info("outer-restored")

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [record["message"] for record in records] == ["outer", "inner", "outer-restored"]
    assert [record["correlation_id"] for record in records] == [
        "corr-outer-001",
        "corr-inner-001",
        "corr-outer-001",
    ]
    assert all(
        {record["run_id"], record["mode"], record["variant_id"], record["schema_version"]}
        == {"run-2026-01-15-001", "historical", "quant_only_v1", "v1"}
        for record in records
    )


def test_existing_tradingagents_env_precedence_remains_unchanged(monkeypatch) -> None:
    import tradingagents.default_config as default_config

    original_keys = set(default_config._ENV_OVERRIDES)
    monkeypatch.setenv("MYTRADINGALPHA_LLM_PROVIDER", "must-not-bleed")

    assert set(default_config._ENV_OVERRIDES) == original_keys
    assert "MYTRADINGALPHA_LLM_PROVIDER" not in default_config._ENV_OVERRIDES


def test_config_mapping_is_not_mutated_by_resolution() -> None:
    source = _forward_paper_mapping()
    original = deepcopy(source)

    _config_load(source)

    assert source == original

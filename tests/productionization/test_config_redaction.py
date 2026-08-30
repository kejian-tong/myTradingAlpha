"""RED contract tests for the FND-03 configuration and observability boundary."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
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
        "capture": {"provider_profile": "approved-capture-profile"},
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

    assert dumped["mode"]["mode"] == "historical"
    assert dumped["mode"]["variant_id"] == "quant_only_v1"
    assert dumped["persistence"]["bundle_store"] == "fixture-bundle-store"


@pytest.mark.parametrize("fixture_name", ["paper.yaml", "live-read-only.yaml"])
def test_nonhistorical_read_only_fixtures_keep_both_write_flags_disabled(fixture_name: str) -> None:
    dumped = _config_dump(_config_load(CONFIG_FIXTURES / fixture_name))

    assert dumped["broker"]["paper_write_enabled"] is False
    assert dumped["broker"]["live_write_enabled"] is False


def test_config_precedence_is_defaults_then_mapping_then_mytradingalpha_env(monkeypatch) -> None:
    monkeypatch.setenv("MYTRADINGALPHA_VARIANT_ID", "env-selected-variant")

    config = _config_load(_forward_paper_mapping())
    dumped = _config_dump(config)

    assert dumped["mode"]["variant_id"] == "env-selected-variant"
    assert dumped["mode"]["calendar_id"] == "XNYS-regular-v1"
    assert dumped["broker"]["paper_write_enabled"] is False
    assert dumped["broker"]["live_write_enabled"] is False


def test_network_policy_is_component_scoped_immutable_extra_forbidden_and_deny_by_default() -> None:
    from mytradingalpha.ops.config import NetworkPolicy

    policy = NetworkPolicy()

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
    assert dumped["broker"]["paper_write_enabled"] is True
    assert dumped["broker"]["paper_endpoint_id"] == "approved-paper-sandbox"
    assert dumped["broker"]["approval_ref"] == "approved-paper-run-reference"


@pytest.mark.parametrize(
    "bad_update",
    [
        {"run": {"unexpected": "field"}},
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

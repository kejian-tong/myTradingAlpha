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


@pytest.mark.parametrize(
    ("template", "sentinel"),
    [
        ("Authorization: Basic %s", "lazy-basic-auth-sentinel"),
        ("Authorization: Token %s", "lazy-token-auth-sentinel"),
        ("Authorization: Bearer %s", "lazy-bearer-auth-sentinel"),
        ("Proxy-Authorization: Basic %s", "lazy-proxy-auth-sentinel"),
        ("X-Authorization: Token %s", "lazy-x-auth-sentinel"),
        ("X-API-Key: %s", "lazy-x-api-key-sentinel"),
        ("provider_api_key=%s", "lazy-provider-api-key-sentinel"),
    ],
)
def test_configured_logging_redacts_lazy_formatted_credentials(
    template: str, sentinel: str
) -> None:
    from mytradingalpha.ops.logging import configure_logging

    stream = StringIO()
    logger = logging.getLogger("mytradingalpha.test.redaction.lazy")
    logger.handlers.clear()
    configure_logging(logger=logger, stream=stream)

    logger.info(template, sentinel)
    rendered = stream.getvalue()

    assert "[REDACTED]" in rendered
    assert sentinel not in rendered


def test_configured_logging_consumes_complete_percent_encoded_credentials() -> None:
    from mytradingalpha.ops.logging import configure_logging

    stream = StringIO()
    logger = logging.getLogger("mytradingalpha.test.redaction.percent-encoded")
    logger.handlers.clear()
    configure_logging(logger=logger, stream=stream)

    logger.info("api_key=alpha%2Fomega")
    rendered = stream.getvalue()

    assert "[REDACTED]" in rendered
    assert "alpha%2Fomega" not in rendered
    assert "2Fomega" not in rendered


def test_configured_logging_preserves_ordinary_lazy_formatting() -> None:
    from mytradingalpha.ops.logging import configure_logging

    stream = StringIO()
    logger = logging.getLogger("mytradingalpha.test.formatting.lazy")
    logger.handlers.clear()
    configure_logging(logger=logger, stream=stream)

    logger.info("operation=%s count=%d", "ordinary", 2)

    assert json.loads(stream.getvalue())["message"] == "operation=ordinary count=2"


_AUD_H01_SECRET_FIELDS = (
    "api_secret",
    "consumer_secret",
    "aws_secret_access_key",
    "aws_access_key_id",
    "session_token",
    "auth_token",
    "api_key",
    "client_secret",
)


def _aud_h01_canary(field_name: str) -> str:
    return f"AUDH01_CANARY_{field_name.upper()}"


def _aud_h01_record(
    *,
    message: object,
    arguments: object = (),
) -> logging.LogRecord:
    return logging.LogRecord(
        name="mytradingalpha.test.aud-h01",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=arguments,
        exc_info=None,
    )


def _aud_h01_render(record: logging.LogRecord, template: str = "%(message)s") -> str:
    from mytradingalpha.ops.logging import RedactionFilter

    assert RedactionFilter().filter(record) is True
    return logging.Formatter(template).format(record)


@pytest.mark.parametrize("field_name", _AUD_H01_SECRET_FIELDS)
@pytest.mark.parametrize(
    "surface",
    ("text", "mapping", "nested", "lazy-positional", "lazy-mapping", "extra"),
)
def test_aud_h01_redacts_every_alias_across_log_record_surfaces(
    field_name: str,
    surface: str,
) -> None:
    canary = _aud_h01_canary(field_name)
    template = "%(message)s"
    if surface == "text":
        record = _aud_h01_record(message=f"failed: {field_name}={canary}")
    elif surface == "mapping":
        record = _aud_h01_record(message={field_name: canary})
    elif surface == "nested":
        record = _aud_h01_record(
            message={"payload": [{"entries": (({field_name: canary},),)}]}
        )
    elif surface == "lazy-positional":
        record = _aud_h01_record(message=f"{field_name}=%s", arguments=(canary,))
    elif surface == "lazy-mapping":
        record = _aud_h01_record(
            message=f"{field_name}=%({field_name})s",
            arguments={field_name: canary},
        )
    else:
        assert surface == "extra"
        record = _aud_h01_record(message="synthetic event")
        record.__dict__[field_name] = canary
        template = f"%(message)s %({field_name})s"

    rendered = _aud_h01_render(record, template)

    assert canary not in rendered
    assert "[REDACTED]" in rendered


@pytest.mark.parametrize(
    ("message", "canary"),
    (
        ("api_secret='AUDH01 CANARY QUOTED'", "AUDH01 CANARY QUOTED"),
        ('{"consumer_secret":"AUDH01_CANARY_JSON"}', "AUDH01_CANARY_JSON"),
        ("X-AWS-Secret-Access-Key: AUDH01_CANARY_HEADER", "AUDH01_CANARY_HEADER"),
        ("aws_access_key_id=424242", "424242"),
        ('session_token="AUDH01_CANARY_SESSION"', "AUDH01_CANARY_SESSION"),
        ("X-Auth-Token: AUDH01_CANARY_AUTH", "AUDH01_CANARY_AUTH"),
        ("api_key=AUDH01%2FCANARY", "AUDH01%2FCANARY"),
        ('{"client_secret": "AUDH01_CANARY_CLIENT"}', "AUDH01_CANARY_CLIENT"),
    ),
)
def test_aud_h01_redacts_quoted_json_header_numeric_and_encoded_values(
    message: str,
    canary: str,
) -> None:
    rendered = _aud_h01_render(_aud_h01_record(message=message))

    assert canary not in rendered
    assert "[REDACTED]" in rendered


def _aud_h01_standard_logger(name: str) -> tuple[logging.Logger, StringIO]:
    from mytradingalpha.ops.logging import RedactionFilter

    stream = StringIO()
    logger = logging.Logger(name)
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactionFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger, stream


@pytest.mark.parametrize("field_name", _AUD_H01_SECRET_FIELDS)
def test_aud_h01_logger_error_redacts_nested_exception_arguments(field_name: str) -> None:
    logger, stream = _aud_h01_standard_logger(f"aud-h01-error-{field_name}")
    canary = _aud_h01_canary(field_name)

    logger.error("failed: %s", ValueError(f"{field_name}={canary}"))
    rendered = stream.getvalue()

    assert canary not in rendered
    assert "[REDACTED]" in rendered
    assert "ValueError" not in rendered


@pytest.mark.parametrize("field_name", _AUD_H01_SECRET_FIELDS)
def test_aud_h01_logger_exception_redacts_generated_standard_traceback(
    field_name: str,
) -> None:
    logger, stream = _aud_h01_standard_logger(f"aud-h01-exception-{field_name}")
    canary = _aud_h01_canary(field_name)

    try:
        raise ValueError(f"failed: {field_name}={canary}")
    except ValueError:
        logger.exception("synthetic operation failed")
    rendered = stream.getvalue()

    assert canary not in rendered
    assert "[REDACTED]" in rendered
    assert "Traceback (most recent call last)" in rendered
    assert "ValueError: failed:" in rendered


@pytest.mark.parametrize("field_name", _AUD_H01_SECRET_FIELDS)
def test_aud_h01_filter_redacts_preexisting_exception_text(field_name: str) -> None:
    canary = _aud_h01_canary(field_name)
    record = _aud_h01_record(message="synthetic operation failed")
    record.exc_text = (
        "Traceback (most recent call last):\n"
        f"  File \"synthetic.py\", line 1\nValueError: failed: {field_name}={canary}"
    )

    rendered = _aud_h01_render(record)

    assert canary not in rendered
    assert "[REDACTED]" in rendered
    assert "Traceback (most recent call last)" in rendered
    assert "ValueError: failed:" in rendered


def test_aud_h01_preserves_delimiter_aware_negative_controls() -> None:
    payload = {
        "secretary": "office",
        "monkey": "banana",
        "token_count": 7,
        "run_id": "run-synthetic-001",
        "instrument_id": "instrument-synthetic-001",
        "count": 2,
        "api_secretary": "ordinary",
        "ordinary": ["text", 3, ("tuple", 4)],
    }

    rendered = _aud_h01_render(_aud_h01_record(message=payload))

    assert "[REDACTED]" not in rendered
    for value in ("office", "banana", "run-synthetic-001", "instrument-synthetic-001"):
        assert value in rendered
    assert "'token_count': 7" in rendered
    assert "'count': 2" in rendered


@pytest.mark.parametrize("field_name", _AUD_H01_SECRET_FIELDS)
def test_aud_h01_already_redacted_values_are_idempotent(field_name: str) -> None:
    record = _aud_h01_record(message=f"{field_name}=[REDACTED]")

    first = _aud_h01_render(record)
    second = _aud_h01_render(record)

    assert first == second == f"{field_name}=[REDACTED]"


def test_aud_h01_preserves_standard_malformed_formatting_failure() -> None:
    from mytradingalpha.ops.logging import RedactionFilter

    record = _aud_h01_record(message="count=%d", arguments=("not-a-number",))

    with pytest.raises(TypeError):
        RedactionFilter().filter(record)


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

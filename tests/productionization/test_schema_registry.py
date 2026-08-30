"""Focused tests for exact schema registration and direct migrations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError

from mytradingalpha.contracts import (
    CURRENT_SCHEMA_VERSION,
    FoundationReasonCode,
    MigrationPlan,
    SchemaRegistry,
    SchemaRegistryError,
)


class _RecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["v1"]
    value: StrictInt
    metadata: dict[str, Any]


class _RecordV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["v2"]
    value: StrictInt
    metadata: dict[str, Any]
    label: str


class _RecordV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["v3"]
    value: StrictInt
    metadata: dict[str, Any]
    label: str
    owner: str


def _registry() -> SchemaRegistry:
    registry = SchemaRegistry()
    registry.register_schema("example", "v1", _RecordV1)
    registry.register_schema("example", "v2", _RecordV2)
    registry.register_schema("example", "v3", _RecordV3)
    return registry


def test_current_schema_version_is_v1() -> None:
    assert CURRENT_SCHEMA_VERSION == "v1"


def test_foundation_reason_codes_are_stable_lowercase_values() -> None:
    assert {code.value for code in FoundationReasonCode} == {
        "missing_schema_version",
        "unsupported_schema_version",
        "invalid_identifier",
        "invalid_timestamp",
        "invalid_time_order",
        "invalid_decimal",
        "migration_unavailable",
    }


def test_registry_resolves_exact_registered_reader_and_parses_payload() -> None:
    registry = _registry()
    payload = {"schema_version": "v1", "value": 4, "metadata": {"source": "fixture"}}

    assert registry.resolve("example", "v1") is _RecordV1
    parsed = registry.parse("example", payload)

    assert isinstance(parsed, _RecordV1)
    assert parsed.value == 4


def test_registry_rejects_duplicate_and_unknown_schema_registration() -> None:
    registry = SchemaRegistry()
    registry.register_schema("example", "v1", _RecordV1)

    with pytest.raises(SchemaRegistryError):
        registry.register_schema("example", "v1", _RecordV1)
    with pytest.raises(SchemaRegistryError):
        registry.resolve("example", "v9")


def test_registry_rejects_missing_or_unknown_payload_version() -> None:
    registry = _registry()

    with pytest.raises(SchemaRegistryError):
        registry.parse("example", {"value": 4, "metadata": {}})
    with pytest.raises(SchemaRegistryError):
        registry.parse("example", {"schema_version": "v9", "value": 4, "metadata": {}})


def test_registry_uses_reader_validation_without_coercing_invalid_payload() -> None:
    registry = _registry()

    with pytest.raises(ValidationError):
        registry.parse("example", {"schema_version": "v1", "value": "4", "metadata": {}})


def test_direct_additive_migration_validates_target_and_preserves_source_nested_data() -> None:
    registry = _registry()
    source = {
        "schema_version": "v1",
        "value": 4,
        "metadata": {"nested": {"keep": True}},
    }
    original = deepcopy(source)

    def migrate(payload: dict[str, Any]) -> dict[str, Any]:
        payload["metadata"]["nested"]["keep"] = False
        payload["label"] = "migrated"
        payload["schema_version"] = "v2"
        return payload

    plan = MigrationPlan(
        record_type="example",
        source_version="v1",
        target_version="v2",
        migrate=migrate,
    )
    registry.register_migration(plan)

    migrated = registry.migrate("example", source, "v2")

    assert isinstance(migrated, _RecordV2)
    assert migrated.label == "migrated"
    assert source == original


def test_registry_does_not_search_migration_graph() -> None:
    registry = _registry()

    registry.register_migration(
        MigrationPlan(
            record_type="example",
            source_version="v1",
            target_version="v2",
            migrate=lambda payload: {**payload, "schema_version": "v2", "label": "v2"},
        )
    )
    registry.register_migration(
        MigrationPlan(
            record_type="example",
            source_version="v2",
            target_version="v3",
            migrate=lambda payload: {**payload, "schema_version": "v3", "owner": "ops"},
        )
    )

    with pytest.raises(SchemaRegistryError):
        registry.migrate(
            "example",
            {"schema_version": "v1", "value": 1, "metadata": {}},
            "v3",
        )


def test_registry_rejects_duplicate_and_unregistered_migrations() -> None:
    registry = _registry()
    plan = MigrationPlan(
        record_type="example",
        source_version="v1",
        target_version="v2",
        migrate=lambda payload: {**payload, "schema_version": "v2", "label": "v2"},
    )
    registry.register_migration(plan)

    with pytest.raises(SchemaRegistryError):
        registry.register_migration(plan)
    with pytest.raises(SchemaRegistryError):
        registry.migrate(
            "example",
            {"schema_version": "v2", "value": 1, "metadata": {}, "label": "v2"},
            "v3",
        )


@pytest.mark.parametrize(
    "migrated_payload",
    [
        {"schema_version": "v1", "value": 1, "metadata": {}, "label": "wrong-version"},
        {"schema_version": "v2", "metadata": {}, "label": "missing-value"},
        {"schema_version": "v2", "value": 1, "metadata": {}},
    ],
)
def test_registry_rejects_silent_version_or_field_drops(migrated_payload: dict[str, Any]) -> None:
    registry = _registry()
    registry.register_migration(
        MigrationPlan(
            record_type="example",
            source_version="v1",
            target_version="v2",
            migrate=lambda _payload, result=migrated_payload: result,
        )
    )

    with pytest.raises((SchemaRegistryError, ValidationError)):
        registry.migrate(
            "example",
            {"schema_version": "v1", "value": 1, "metadata": {}},
            "v2",
        )

"""Exact schema readers and explicitly registered direct migrations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .reason_codes import FoundationReasonCode

CURRENT_SCHEMA_VERSION = "v1"
_MISSING = object()


class SchemaRegistryError(ValueError):
    """Raised when a schema or direct migration cannot be resolved safely."""

    def __init__(self, message: str, reason_code: FoundationReasonCode) -> None:
        super().__init__(message)
        self.reason_code = reason_code


MigrationFunction = Callable[[dict[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class MigrationPlan:
    """One explicitly named, direct migration between two registered versions."""

    record_type: str
    source_version: str
    target_version: str
    migrate: MigrationFunction
    dropped_fields: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _validate_key_part(self.record_type, "record_type")
        _validate_key_part(self.source_version, "source_version")
        _validate_key_part(self.target_version, "target_version")
        if self.source_version == self.target_version:
            raise SchemaRegistryError(
                "source and target versions must differ for a migration",
                FoundationReasonCode.MIGRATION_UNAVAILABLE,
            )
        if not callable(self.migrate):
            raise SchemaRegistryError(
                "migration must be callable", FoundationReasonCode.MIGRATION_UNAVAILABLE
            )
        try:
            dropped_fields = frozenset(self.dropped_fields)
        except TypeError as exc:
            raise SchemaRegistryError(
                "dropped_fields must be an iterable of field names",
                FoundationReasonCode.MIGRATION_UNAVAILABLE,
            ) from exc
        if any(not isinstance(field_name, str) or not field_name for field_name in dropped_fields):
            raise SchemaRegistryError(
                "dropped_fields must contain non-empty names",
                FoundationReasonCode.MIGRATION_UNAVAILABLE,
            )
        object.__setattr__(self, "dropped_fields", dropped_fields)

    @property
    def from_version(self) -> str:
        """Compatibility spelling for the declared source version."""

        return self.source_version

    @property
    def to_version(self) -> str:
        """Compatibility spelling for the declared target version."""

        return self.target_version

    @property
    def transform(self) -> MigrationFunction:
        """Compatibility spelling for the migration callback."""

        return self.migrate


def _validate_key_part(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SchemaRegistryError(
            f"{label} must be a non-empty stable token",
            FoundationReasonCode.INVALID_IDENTIFIER,
        )
    return value


def _require_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise SchemaRegistryError(
            "schema payload must be a mapping", FoundationReasonCode.UNSUPPORTED_SCHEMA_VERSION
        )
    return dict(payload)


def _payload_version(payload: Mapping[str, Any]) -> str:
    version = payload.get("schema_version", _MISSING)
    if version is _MISSING or version is None:
        raise SchemaRegistryError(
            "schema_version is required", FoundationReasonCode.MISSING_SCHEMA_VERSION
        )
    if not isinstance(version, str) or not version:
        raise SchemaRegistryError(
            "schema_version must be a non-empty string",
            FoundationReasonCode.UNSUPPORTED_SCHEMA_VERSION,
        )
    return version


class SchemaRegistry:
    """Registry keyed by explicit ``(record_type, schema_version)`` pairs."""

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, str], type[BaseModel]] = {}
        self._migrations: dict[tuple[str, str, str], MigrationPlan] = {}

    def register_schema(
        self, record_type: str, version: str, reader: type[BaseModel]
    ) -> None:
        """Register one exact reader, rejecting duplicate keys."""

        record_type = _validate_key_part(record_type, "record_type")
        version = _validate_key_part(version, "version")
        try:
            is_reader = issubclass(reader, BaseModel)
        except TypeError:
            is_reader = False
        if not is_reader:
            raise SchemaRegistryError(
                "reader must be a Pydantic BaseModel subclass",
                FoundationReasonCode.UNSUPPORTED_SCHEMA_VERSION,
            )

        key = (record_type, version)
        if key in self._schemas:
            raise SchemaRegistryError(
                f"schema already registered for {record_type!r} {version!r}",
                FoundationReasonCode.UNSUPPORTED_SCHEMA_VERSION,
            )
        self._schemas[key] = reader

    def resolve(self, record_type: str, version: str | None = None) -> type[BaseModel]:
        """Return only the reader registered for the exact key."""

        record_type = _validate_key_part(record_type, "record_type")
        if version is None:
            raise SchemaRegistryError(
                "schema_version is required", FoundationReasonCode.MISSING_SCHEMA_VERSION
            )
        version = _validate_key_part(version, "version")
        try:
            return self._schemas[(record_type, version)]
        except KeyError as exc:
            raise SchemaRegistryError(
                f"no schema registered for {record_type!r} {version!r}",
                FoundationReasonCode.UNSUPPORTED_SCHEMA_VERSION,
            ) from exc

    def parse(
        self,
        record_type: str,
        payload: Mapping[str, Any],
        version: str | None = None,
    ) -> BaseModel:
        """Validate a payload through its exact registered reader."""

        payload_dict = _require_payload(payload)
        payload_version = _payload_version(payload_dict)
        if version is not None and version != payload_version:
            raise SchemaRegistryError(
                "explicit and payload schema versions differ",
                FoundationReasonCode.UNSUPPORTED_SCHEMA_VERSION,
            )
        reader = self.resolve(record_type, payload_version)
        parsed = reader.model_validate(deepcopy(payload_dict))
        self._ensure_reader_version(parsed, payload_version)
        return parsed

    def register_migration(self, plan: MigrationPlan) -> None:
        """Register one direct migration whose source and target readers exist."""

        if not isinstance(plan, MigrationPlan):
            raise SchemaRegistryError(
                "migration must be a MigrationPlan",
                FoundationReasonCode.MIGRATION_UNAVAILABLE,
            )
        self.resolve(plan.record_type, plan.source_version)
        self.resolve(plan.record_type, plan.target_version)
        key = (plan.record_type, plan.source_version, plan.target_version)
        if key in self._migrations:
            raise SchemaRegistryError(
                f"migration already registered for {key!r}",
                FoundationReasonCode.MIGRATION_UNAVAILABLE,
            )
        self._migrations[key] = plan

    def migrate(
        self,
        record_type: str,
        payload: Mapping[str, Any],
        target_version: str,
    ) -> BaseModel:
        """Apply one registered direct migration and validate its target reader."""

        payload_dict = _require_payload(payload)
        source_version = _payload_version(payload_dict)
        target_version = _validate_key_part(target_version, "target_version")
        if source_version == target_version:
            return self.parse(record_type, payload_dict, target_version)

        # Validate the source before invoking user-supplied migration code.  The
        # callback receives a separate deep copy below, so nested source data is
        # never exposed for mutation.
        self.parse(record_type, payload_dict, source_version)
        self.resolve(record_type, source_version)
        self.resolve(record_type, target_version)
        key = (record_type, source_version, target_version)
        try:
            plan = self._migrations[key]
        except KeyError as exc:
            raise SchemaRegistryError(
                f"no direct migration registered for {key!r}",
                FoundationReasonCode.MIGRATION_UNAVAILABLE,
            ) from exc

        try:
            migrated_payload = plan.migrate(deepcopy(payload_dict))
        except Exception as exc:
            raise SchemaRegistryError(
                f"migration {key!r} failed", FoundationReasonCode.MIGRATION_UNAVAILABLE
            ) from exc
        if not isinstance(migrated_payload, Mapping):
            raise SchemaRegistryError(
                "migration must return a mapping",
                FoundationReasonCode.MIGRATION_UNAVAILABLE,
            )
        migrated_dict = dict(migrated_payload)
        if migrated_dict.get("schema_version") != plan.target_version:
            raise SchemaRegistryError(
                "migration did not produce its declared target schema_version",
                FoundationReasonCode.UNSUPPORTED_SCHEMA_VERSION,
            )

        source_fields = set(payload_dict) - {"schema_version"}
        undeclared_drops = source_fields - set(plan.dropped_fields) - set(migrated_dict)
        if undeclared_drops:
            raise SchemaRegistryError(
                f"migration silently dropped fields: {sorted(undeclared_drops, key=repr)!r}",
                FoundationReasonCode.MIGRATION_UNAVAILABLE,
            )

        target_reader = self.resolve(record_type, target_version)
        target_fields = set(target_reader.model_fields)
        unknown_fields = set(migrated_dict) - target_fields
        if unknown_fields:
            raise SchemaRegistryError(
                "migration produced fields unknown to target reader: "
                f"{sorted(unknown_fields, key=repr)!r}",
                FoundationReasonCode.MIGRATION_UNAVAILABLE,
            )
        migrated = target_reader.model_validate(deepcopy(migrated_dict))
        self._ensure_reader_version(migrated, target_version)
        return migrated

    @staticmethod
    def _ensure_reader_version(parsed: BaseModel, expected_version: str) -> None:
        if "schema_version" not in parsed.model_fields:
            raise SchemaRegistryError(
                "registered reader must preserve schema_version",
                FoundationReasonCode.UNSUPPORTED_SCHEMA_VERSION,
            )
        if getattr(parsed, "schema_version", _MISSING) != expected_version:
            raise SchemaRegistryError(
                "reader returned a different schema_version",
                FoundationReasonCode.UNSUPPORTED_SCHEMA_VERSION,
            )


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MigrationPlan",
    "SchemaRegistry",
    "SchemaRegistryError",
]

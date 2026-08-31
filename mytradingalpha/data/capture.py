"""Pure byte capture and checksum binding for PIT-01."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import field_validator, model_validator

from mytradingalpha.contracts.common import StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .provenance import SourceManifest


def _copy_raw_bytes(value: object) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("raw_bytes must be bytes, bytearray, or memoryview")
    return bytes(value)


def _checksum(raw_bytes: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"


class CapturedPayload(ContractModel):
    """Immutable raw bytes bound to their validated provenance manifest."""

    manifest: SourceManifest
    raw_bytes: bytes

    @field_validator("raw_bytes", mode="before")
    @classmethod
    def copy_raw_bytes(cls, value: object) -> bytes:
        return _copy_raw_bytes(value)

    @model_validator(mode="after")
    def validate_checksum(self) -> CapturedPayload:
        if _checksum(self.raw_bytes) != self.manifest.checksum:
            raise ValueError("checksum_mismatch: raw bytes do not match the source manifest")
        return self


class CaptureClient:
    """Construct captured payloads without clocks, identifiers, transport, or I/O."""

    def capture(
        self,
        raw_bytes: bytes | bytearray | memoryview,
        *,
        schema_version: Literal[CURRENT_SCHEMA_VERSION],
        manifest_id: StableId,
        source: StableId,
        source_locator: str,
        fetched_at: UtcDateTime,
        event_time: UtcDateTime | None,
        published_at: UtcDateTime | None,
        available_at: UtcDateTime,
        ingested_at: UtcDateTime,
        terms: str,
        revision: int,
    ) -> CapturedPayload:
        """Copy raw bytes and bind them to explicitly supplied provenance."""

        immutable_bytes = _copy_raw_bytes(raw_bytes)
        manifest = SourceManifest(
            schema_version=schema_version,
            manifest_id=manifest_id,
            source=source,
            source_locator=source_locator,
            fetched_at=fetched_at,
            event_time=event_time,
            published_at=published_at,
            available_at=available_at,
            ingested_at=ingested_at,
            checksum=_checksum(immutable_bytes),
            terms=terms,
            revision=revision,
        )
        return CapturedPayload(manifest=manifest, raw_bytes=immutable_bytes)


__all__ = ["CaptureClient", "CapturedPayload"]

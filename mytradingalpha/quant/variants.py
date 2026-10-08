"""Immutable, explicitly selected SIG-05 signal variant snapshots."""

from __future__ import annotations

import hashlib
import json
import re

from mytradingalpha.contracts.signals import (
    HASH_DOMAIN_SIGNAL_VARIANT,
    SignalEnvelopeError,
    SignalEnvelopeReasonCode,
    SignalVariant,
    validate_sig03_identifier,
)
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

_VARIANT_KINDS = ("quant_only", "quant_llm")
_MAX_VARIANT_ID_BYTES = 128
_VARIANT_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")


def _variant_error(reason: SignalEnvelopeReasonCode) -> SignalEnvelopeError:
    return SignalEnvelopeError(reason)


def _bounded_identifier(value: str) -> bool:
    if type(value) is not str or len(value) > _MAX_VARIANT_ID_BYTES:
        return False
    try:
        encoded = value.encode("utf-8", "strict")
        if not encoded or len(encoded) > _MAX_VARIANT_ID_BYTES:
            return False
        validate_sig03_identifier(value)
    except (TypeError, ValueError, UnicodeError):
        return False
    return True


def _canonical_variant_hash(schema_version: str, variant_id: str, kind: str) -> str:
    fields: dict[str, object] = {
        "schema_version": schema_version,
        "variant_id": variant_id,
        "kind": kind,
    }
    canonical = json.dumps(
        fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")
    digest = hashlib.sha256(
        HASH_DOMAIN_SIGNAL_VARIANT.encode("utf-8") + canonical
    ).hexdigest()
    return f"sha256:{digest}"


def _entry_to_variant(entry: object) -> SignalVariant:
    if type(entry) is not tuple or tuple.__len__(entry) != 4:
        raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
    fields = tuple.__iter__(entry)
    schema_version, variant_id, kind, variant_hash = tuple(fields)
    if (
        type(schema_version) is not str
        or len(schema_version) != len(CURRENT_SCHEMA_VERSION)
        or schema_version != CURRENT_SCHEMA_VERSION
        or type(variant_id) is not str
        or type(kind) is not str
        or type(variant_hash) is not str
    ):
        raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
    if not _bounded_identifier(variant_id):
        raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
    if len(kind) > 10 or kind not in _VARIANT_KINDS:
        raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
    if len(variant_hash) != 71 or _VARIANT_HASH_RE.fullmatch(variant_hash) is None:
        raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
    try:
        expected_hash = _canonical_variant_hash(schema_version, variant_id, kind)
    except Exception:
        raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID) from None
    if variant_hash != expected_hash:
        raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
    try:
        return SignalVariant.model_validate(
            {
                "schema_version": schema_version,
                "variant_id": variant_id,
                "kind": kind,
                "variant_hash": variant_hash,
            }
        )
    except Exception:
        raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID) from None


class VariantRegistry(tuple):
    """A built-in immutable snapshot containing at most two primitive entries."""

    __slots__ = ()

    def __new__(cls) -> VariantRegistry:
        if cls is not VariantRegistry:
            raise SignalEnvelopeError(SignalEnvelopeReasonCode.VARIANT_INVALID)
        return tuple.__new__(cls, ())

    def _validated_entries(self) -> tuple[tuple[str, str, str, str], ...]:
        if type(self) is not VariantRegistry:
            raise SignalEnvelopeError(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if tuple.__len__(self) > 2:
            raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)

        entries: list[tuple[str, str, str, str]] = []
        seen_ids: set[str] = set()
        seen_kinds: set[str] = set()
        for entry in tuple.__iter__(self):
            variant = _entry_to_variant(entry)
            if variant.variant_id in seen_ids or variant.kind in seen_kinds:
                raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
            seen_ids.add(variant.variant_id)
            seen_kinds.add(variant.kind)
            # Retain only the four bounded immutable source strings.
            entries.append(
                (
                    variant.schema_version,
                    variant.variant_id,
                    variant.kind,
                    variant.variant_hash,
                )
            )
        return tuple(entries)

    def register(self, variant_id: str, *, kind: str) -> VariantRegistry:
        """Return a new snapshot containing one validated, explicit variant."""

        if type(self) is not VariantRegistry:
            raise SignalEnvelopeError(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if type(variant_id) is not str or type(kind) is not str:
            raise _variant_error(SignalEnvelopeReasonCode.INPUT_INVALID)
        # Bound attacker-controlled strings before hashing or set membership.
        if len(kind) > 10:
            raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if kind not in _VARIANT_KINDS:
            raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if not _bounded_identifier(variant_id):
            raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)

        entries = self._validated_entries()
        if len(entries) >= 2:
            raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if any(entry[1] == variant_id or entry[2] == kind for entry in entries):
            raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)

        try:
            schema_version = CURRENT_SCHEMA_VERSION
            variant_hash = _canonical_variant_hash(schema_version, variant_id, kind)
            # Validate before storing so every snapshot can be decoded identically.
            _entry_to_variant((schema_version, variant_id, kind, variant_hash))
        except Exception:
            raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID) from None

        snapshot = tuple.__new__(
            VariantRegistry,
            (*entries, (schema_version, variant_id, kind, variant_hash)),
        )
        return snapshot

    def resolve(self, variant_id: str) -> SignalVariant:
        """Resolve only an exact preregistered identity; never choose a default."""

        if type(self) is not VariantRegistry:
            raise SignalEnvelopeError(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if type(variant_id) is not str:
            raise _variant_error(SignalEnvelopeReasonCode.INPUT_INVALID)
        if not _bounded_identifier(variant_id):
            raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)
        for entry in self._validated_entries():
            if entry[1] == variant_id:
                return _entry_to_variant(entry)
        raise _variant_error(SignalEnvelopeReasonCode.VARIANT_INVALID)


__all__ = ["VariantRegistry"]

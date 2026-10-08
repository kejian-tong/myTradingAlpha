"""Immutable, explicitly selected SIG-05 signal variant snapshots."""

from __future__ import annotations

import hashlib
import json

from mytradingalpha.contracts.signals import (
    HASH_DOMAIN_SIGNAL_VARIANT,
    SignalEnvelopeError,
    SignalEnvelopeReasonCode,
    SignalVariant,
    validate_sig03_identifier,
)
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION


class VariantRegistry:
    """An immutable snapshot containing at most one entry for each SIG-05 kind."""

    __slots__ = ("_variants",)

    def __init__(self) -> None:
        object.__setattr__(self, "_variants", ())

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("VariantRegistry snapshots are immutable")

    @staticmethod
    def _error(reason: SignalEnvelopeReasonCode) -> SignalEnvelopeError:
        return SignalEnvelopeError(reason)

    def _validated_entries(self) -> tuple[SignalVariant, ...]:
        if type(self) is not VariantRegistry:
            raise SignalEnvelopeError(SignalEnvelopeReasonCode.VARIANT_INVALID)
        try:
            stored = object.__getattribute__(self, "_variants")
        except (AttributeError, TypeError):
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID) from None
        if type(stored) is not tuple or len(stored) > 2:
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID)

        validated: list[SignalVariant] = []
        seen_ids: set[str] = set()
        seen_kinds: set[str] = set()
        for value in stored:
            if type(value) is not SignalVariant:
                raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID)
            try:
                variant = SignalVariant.model_validate(value)
            except Exception:
                raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID) from None
            if variant.variant_id in seen_ids or variant.kind in seen_kinds:
                raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID)
            seen_ids.add(variant.variant_id)
            seen_kinds.add(variant.kind)
            validated.append(variant)
        return tuple(validated)

    def register(self, variant_id: str, *, kind: str) -> VariantRegistry:
        """Return a new snapshot containing one validated, explicit variant."""

        if type(self) is not VariantRegistry:
            raise SignalEnvelopeError(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if type(variant_id) is not str or type(kind) is not str:
            raise self._error(SignalEnvelopeReasonCode.INPUT_INVALID)
        if len(kind) > 10:
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if kind not in {"quant_only", "quant_llm"}:
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if len(variant_id) > 128:
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID)
        try:
            encoded_id = variant_id.encode("utf-8", "strict")
            if not encoded_id or len(encoded_id) > 128:
                raise ValueError
            validate_sig03_identifier(variant_id)
        except (TypeError, ValueError, UnicodeError):
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID) from None

        entries = self._validated_entries()
        if len(entries) >= 2:
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if any(item.variant_id == variant_id or item.kind == kind for item in entries):
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID)

        fields: dict[str, object] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "variant_id": variant_id,
            "kind": kind,
        }
        try:
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
            variant = SignalVariant.model_validate(
                {**fields, "variant_hash": f"sha256:{digest}"}
            )
        except Exception:
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID) from None

        snapshot = object.__new__(VariantRegistry)
        object.__setattr__(snapshot, "_variants", (*entries, variant))
        return snapshot

    def resolve(self, variant_id: str) -> SignalVariant:
        """Resolve only an exact preregistered identity; never choose a default."""

        if type(self) is not VariantRegistry:
            raise SignalEnvelopeError(SignalEnvelopeReasonCode.VARIANT_INVALID)
        if type(variant_id) is not str:
            raise self._error(SignalEnvelopeReasonCode.INPUT_INVALID)
        try:
            validate_sig03_identifier(variant_id)
        except (TypeError, ValueError):
            raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID) from None
        for variant in self._validated_entries():
            if variant.variant_id == variant_id:
                return variant
        raise self._error(SignalEnvelopeReasonCode.VARIANT_INVALID)


__all__ = ["VariantRegistry"]

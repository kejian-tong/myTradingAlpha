"""Pure SIG-05 composition of exact QuantSignal and optional LLMOverlay inputs."""

from __future__ import annotations

from mytradingalpha.contracts.research import ResearchNote
from mytradingalpha.contracts.schemas import RunContext
from mytradingalpha.contracts.signals import (
    HASH_DOMAIN_SIGNAL_ENVELOPE,
    MAX_SIG05_CANONICAL_BYTES,
    LLMOverlay,
    QuantSignal,
    QuantSignalStatus,
    SignalEnvelope,
    SignalEnvelopeError,
    SignalEnvelopeReasonCode,
    SignalVariant,
    _sig05_check_context_quant,
    _sig05_envelope_id,
    _sig05_expected_envelope,
    _sig05_json_bytes,
    _sig05_model_payload,
    _sig05_validate_context,
    _sig05_validate_overlay_lineage,
)
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .variants import VariantRegistry


def _reject(reason: SignalEnvelopeReasonCode) -> SignalEnvelopeError:
    return SignalEnvelopeError(reason)


def _copy_context(value: object) -> RunContext:
    if type(value) is not RunContext:
        raise _reject(SignalEnvelopeReasonCode.CONTEXT_INVALID)
    try:
        payload = _sig05_model_payload(value, RunContext)
        context = RunContext.model_validate(payload)
        _sig05_validate_context(context)
    except Exception as exc:
        del exc
        raise _reject(SignalEnvelopeReasonCode.CONTEXT_INVALID) from None
    return context


def _copy_quant(value: object) -> QuantSignal:
    if type(value) is not QuantSignal:
        raise _reject(SignalEnvelopeReasonCode.INPUT_INVALID)
    try:
        payload = _sig05_model_payload(value, QuantSignal)
        return QuantSignal.model_validate(payload)
    except Exception as exc:
        del exc
        raise _reject(SignalEnvelopeReasonCode.INPUT_INVALID) from None


def _copy_note(
    value: object,
    context: RunContext,
    quant: QuantSignal,
) -> tuple[ResearchNote | None, SignalEnvelopeReasonCode | None]:
    if value is None:
        return None, SignalEnvelopeReasonCode.NOTE_UNAVAILABLE
    if type(value) is not ResearchNote:
        return None, SignalEnvelopeReasonCode.NOTE_INVALID
    try:
        payload = _sig05_model_payload(value, ResearchNote)
        note = ResearchNote.model_validate(payload)
        note.canonical_bytes()
    except Exception:
        return None, SignalEnvelopeReasonCode.NOTE_INVALID

    if (
        note.run_id != context.run_id
        or note.variant_id != context.variant_id
        or note.bundle_id != context.bundle_id
        or note.bundle_hash != context.bundle_hash
        or note.calendar_id != context.calendar_id
        or note.knowledge_cutoff != context.knowledge_cutoff
    ):
        raise _reject(SignalEnvelopeReasonCode.CONTEXT_MISMATCH)
    if note.instrument_id != quant.instrument_id:
        return None, SignalEnvelopeReasonCode.NOTE_INVALID
    return note, None


def _copy_overlay(value: object) -> LLMOverlay | None:
    if type(value) is not LLMOverlay:
        return None
    try:
        payload = _sig05_model_payload(value, LLMOverlay)
        return LLMOverlay.model_validate(payload)
    except Exception:
        return None


def _envelope_payload(
    variant: SignalVariant,
    context: RunContext,
    quant: QuantSignal,
    note: ResearchNote | None,
    overlay: LLMOverlay | None,
    *,
    reason: SignalEnvelopeReasonCode | None,
) -> SignalEnvelope:
    reasons = () if reason is None else (reason,)
    try:
        score, multiplier, action, no_trade, reasons = _sig05_expected_envelope(
            variant,
            context,
            quant,
            note,
            overlay,
            absent_reasons=reasons,
        )
        payload: dict[str, object] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "envelope_id": "signal-envelope:" + "0" * 64,
            "variant": variant.model_dump(mode="json"),
            "context": context.model_dump(mode="json"),
            "quant": quant.model_dump(mode="json"),
            "note": None if note is None else note.model_dump(mode="json"),
            "overlay": None if overlay is None else overlay.model_dump(mode="json"),
            "effective_score": format(score, "f"),
            "effective_multiplier": format(multiplier, "f"),
            "effective_action": action,
            "no_trade": no_trade,
            "reason_codes": [item.value for item in reasons],
            "created_at": context.decision_time.isoformat().replace("+00:00", "Z"),
            "shadow_only": True,
        }
        # Hash the canonical complete source payload after every source has
        # been detached and independently validated.
        canonical = dict(payload)
        canonical.pop("envelope_id")
        _sig05_json_bytes(
            canonical,
            HASH_DOMAIN_SIGNAL_ENVELOPE,
            MAX_SIG05_CANONICAL_BYTES,
        )
        payload["envelope_id"] = _sig05_envelope_id(canonical)
        return SignalEnvelope.model_validate(payload)
    except SignalEnvelopeError:
        raise
    except Exception as exc:
        del exc
        raise _reject(SignalEnvelopeReasonCode.INPUT_INVALID) from None


def combine_quant_overlay(
    quant_signal: QuantSignal,
    *,
    context: RunContext,
    registry: VariantRegistry,
    note: ResearchNote | None = None,
    overlay: LLMOverlay | None = None,
) -> SignalEnvelope:
    """Build a deterministic envelope for the exact preregistered context variant."""

    copied_context = _copy_context(context)
    copied_quant = _copy_quant(quant_signal)
    if type(registry) is not VariantRegistry:
        raise _reject(SignalEnvelopeReasonCode.VARIANT_INVALID)
    try:
        variant = registry.resolve(copied_context.variant_id)
    except SignalEnvelopeError:
        raise
    except Exception as exc:
        del exc
        raise _reject(SignalEnvelopeReasonCode.VARIANT_INVALID) from None
    try:
        _sig05_check_context_quant(variant, copied_context, copied_quant)
    except Exception as exc:
        del exc
        raise _reject(SignalEnvelopeReasonCode.CONTEXT_MISMATCH) from None

    if variant.kind == "quant_only":
        if note is not None or overlay is not None:
            raise _reject(SignalEnvelopeReasonCode.UNEXPECTED_RESEARCH)
        return _envelope_payload(
            variant,
            copied_context,
            copied_quant,
            None,
            None,
            reason=None,
        )

    copied_note, note_reason = _copy_note(note, copied_context, copied_quant)
    if note_reason is not None:
        return _envelope_payload(
            variant,
            copied_context,
            copied_quant,
            None,
            None,
            reason=note_reason,
        )
    if copied_quant.status is QuantSignalStatus.INVALID or copied_quant.score is None:
        return _envelope_payload(
            variant,
            copied_context,
            copied_quant,
            None,
            None,
            reason=SignalEnvelopeReasonCode.QUANT_INVALID,
        )
    assert copied_note is not None

    copied_overlay = _copy_overlay(overlay)
    if copied_overlay is None:
        overlay_reason = (
            SignalEnvelopeReasonCode.OVERLAY_UNAVAILABLE
            if overlay is None
            else SignalEnvelopeReasonCode.OVERLAY_INVALID
        )
        return _envelope_payload(
            variant,
            copied_context,
            copied_quant,
            copied_note,
            None,
            reason=overlay_reason,
        )
    try:
        _sig05_validate_overlay_lineage(
            copied_overlay,
            copied_note,
            copied_quant,
            copied_context,
        )
    except Exception:
        return _envelope_payload(
            variant,
            copied_context,
            copied_quant,
            copied_note,
            None,
            reason=SignalEnvelopeReasonCode.OVERLAY_INVALID,
        )

    return _envelope_payload(
        variant,
        copied_context,
        copied_quant,
        copied_note,
        copied_overlay,
        reason=None,
    )


__all__ = ["combine_quant_overlay"]

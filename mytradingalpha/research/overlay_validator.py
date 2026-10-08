"""Pure validation for caller-supplied SIG-04 overlay candidates."""

from __future__ import annotations

from mytradingalpha.contracts.research import ResearchNote
from mytradingalpha.contracts.signals import (
    LLMOverlay,
    QuantSignal,
    QuantSignalStatus,
)


class OverlayValidationError(ValueError):
    """Generic fail-closed overlay validation error without caller data."""

    def __init__(self) -> None:
        super().__init__("overlay validation failed")


class InvalidQuantSignalError(OverlayValidationError):
    """Raised when the supplied quantitative signal is unusable."""

    def __init__(self) -> None:
        ValueError.__init__(self, "overlay validation failed")


def _invalid() -> OverlayValidationError:
    return OverlayValidationError()


def _prepare_inputs(
    note: object,
    quant_signal: object,
) -> tuple[ResearchNote, QuantSignal]:
    """Revalidate and detach exact immutable input records."""

    if type(note) is not ResearchNote or type(quant_signal) is not QuantSignal:
        raise _invalid()
    try:
        note_copy = ResearchNote.model_validate(note)
        note_copy.canonical_bytes()
        quant_copy = QuantSignal.model_validate(quant_signal)
    except Exception:
        raise _invalid() from None

    if (
        note_copy.run_id != quant_copy.run_id
        or note_copy.bundle_id != quant_copy.bundle_id
        or note_copy.bundle_hash != quant_copy.bundle_hash
        or note_copy.instrument_id != quant_copy.instrument_id
    ):
        raise _invalid()
    if quant_copy.status is QuantSignalStatus.INVALID or quant_copy.score is None:
        raise InvalidQuantSignalError()
    if quant_copy.as_of > note_copy.knowledge_cutoff:
        raise InvalidQuantSignalError()
    return note_copy, quant_copy


def _validate_candidate(
    candidate: object,
    note: ResearchNote,
    quant_signal: QuantSignal,
) -> LLMOverlay:
    if type(candidate) is not dict:
        raise _invalid()
    try:
        overlay = LLMOverlay.model_validate(candidate)
        note_hash = note.note_hash
        if (
            overlay.note_id != note.note_id
            or overlay.note_hash != note_hash
            or overlay.quant_signal_id != quant_signal.signal_id
            or overlay.run_id != note.run_id
            or overlay.bundle_id != note.bundle_id
            or overlay.bundle_hash != note.bundle_hash
            or overlay.instrument_id != note.instrument_id
            or overlay.generated_at > note.knowledge_cutoff
        ):
            raise _invalid()

        cited_ids = {
            f"{citation.reference.domain}:{citation.reference.record_id}"
            for citation in note.citations
        }
        if not set(overlay.evidence_ids).issubset(cited_ids):
            raise _invalid()
        return overlay
    except OverlayValidationError:
        raise
    except Exception:
        raise _invalid() from None


def validate_overlay(
    candidate: object,
    note: object,
    quant_signal: object,
) -> LLMOverlay:
    """Validate a bounded candidate against defensive note and signal copies."""

    note_copy, quant_copy = _prepare_inputs(note, quant_signal)
    return _validate_candidate(candidate, note_copy, quant_copy)


__all__ = [
    "InvalidQuantSignalError",
    "OverlayValidationError",
    "validate_overlay",
]

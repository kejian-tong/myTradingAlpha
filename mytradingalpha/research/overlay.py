"""Pure fail-closed service for optional SIG-04 overlay candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mytradingalpha.contracts.signals import LLMOverlay

from .overlay_validator import (
    InvalidQuantSignalError,
    OverlayValidationError,
    _prepare_inputs,
    _validate_candidate,
)


class OverlayGuardReasonCode(str, Enum):
    """Stable bounded local outcome codes for the SIG-04 guard."""

    APPLIED = "overlay_applied"
    ABSTAINED = "overlay_abstained"
    INVALID = "overlay_invalid"
    QUANT_INVALID = "quant_invalid"
    UNAVAILABLE = "overlay_unavailable"
    VETOED = "overlay_vetoed"
    ZERO_MULTIPLIER = "overlay_zero_multiplier"


@dataclass(frozen=True, slots=True)
class OverlayGuardResult:
    """Immutable local outcome; it conveys no portfolio or order authority."""

    overlay: LLMOverlay | None
    no_trade: bool
    reason_code: OverlayGuardReasonCode


class LLMOverlayService:
    """Evaluate one caller-supplied overlay without invoking an inference provider."""

    __slots__ = ()

    def evaluate(
        self,
        note: object,
        quant_signal: object,
        candidate: object,
    ) -> OverlayGuardResult:
        try:
            note_copy, quant_copy = _prepare_inputs(note, quant_signal)
        except InvalidQuantSignalError:
            return OverlayGuardResult(
                overlay=None,
                no_trade=True,
                reason_code=OverlayGuardReasonCode.QUANT_INVALID,
            )
        except Exception:
            return OverlayGuardResult(
                overlay=None,
                no_trade=True,
                reason_code=OverlayGuardReasonCode.INVALID,
            )

        if candidate is None:
            return OverlayGuardResult(
                overlay=None,
                no_trade=True,
                reason_code=OverlayGuardReasonCode.UNAVAILABLE,
            )

        try:
            overlay = _validate_candidate(candidate, note_copy, quant_copy)
        except OverlayValidationError:
            return OverlayGuardResult(
                overlay=None,
                no_trade=True,
                reason_code=OverlayGuardReasonCode.INVALID,
            )
        except Exception:
            return OverlayGuardResult(
                overlay=None,
                no_trade=True,
                reason_code=OverlayGuardReasonCode.INVALID,
            )

        if overlay.abstain:
            return OverlayGuardResult(
                overlay=overlay,
                no_trade=True,
                reason_code=OverlayGuardReasonCode.ABSTAINED,
            )
        if overlay.action == "veto":
            return OverlayGuardResult(
                overlay=overlay,
                no_trade=True,
                reason_code=OverlayGuardReasonCode.VETOED,
            )
        if overlay.multiplier == 0:
            return OverlayGuardResult(
                overlay=overlay,
                no_trade=True,
                reason_code=OverlayGuardReasonCode.ZERO_MULTIPLIER,
            )
        return OverlayGuardResult(
            overlay=overlay,
            no_trade=False,
            reason_code=OverlayGuardReasonCode.APPLIED,
        )


__all__ = [
    "LLMOverlayService",
    "OverlayGuardReasonCode",
    "OverlayGuardResult",
]

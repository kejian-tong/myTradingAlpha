"""Explicit, side-effect-free execution seam for caller-supplied historical runtimes.

This module deliberately does not construct :class:`TradingAgentsGraph`.  A caller owns
the opaque evidence/context objects and supplies the only runner that may be invoked.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .propagation import Propagator
from .signal_processing import SignalProcessor

_REPORT_FIELDS = (
    "market_report",
    "fundamentals_report",
    "sentiment_report",
    "news_report",
)
_PROSE_FIELDS = (
    *_REPORT_FIELDS,
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
)
_INVEST_DEBATE_FIELDS = {
    "bull_history",
    "bear_history",
    "history",
    "current_response",
    "judge_decision",
    "count",
}
_RISK_DEBATE_FIELDS = {
    "aggressive_history",
    "conservative_history",
    "neutral_history",
    "history",
    "latest_speaker",
    "current_aggressive_response",
    "current_conservative_response",
    "current_neutral_response",
    "judge_decision",
    "count",
}
_AUTHORITY_FIELDS = {
    "target_weight",
    "target_weights",
    "portfolio_allocation",
    "order",
    "order_intent",
    "quantity",
    "broker",
    "broker_id",
    "credentials",
    "risk_authorization",
}


class HistoricalRuntimeError(ValueError):
    """Base class for historical runtime boundary failures."""


class HistoricalRuntimeUnavailableError(HistoricalRuntimeError):
    """Raised when no explicit offline runtime was supplied."""


class HistoricalRuntimeTypeError(HistoricalRuntimeError):
    """Raised when the runtime is not the exact concrete wrapper type."""


class HistoricalRuntimeOutputError(HistoricalRuntimeError):
    """Raised when an injected runner returns an unsafe or incompatible state."""


HistoricalRunner = Callable[[object, object, dict[str, object]], object]


@dataclass(frozen=True, slots=True)
class OfflineGraphRuntime:
    """Concrete wrapper around one explicitly caller-supplied deterministic runner.

    Construction of this wrapper does not prove that the callable is a deployable
    offline model.  The caller is responsible for supplying an approved local runner;
    this seam never supplies or discovers a default provider.
    """

    runner: HistoricalRunner

    def __post_init__(self) -> None:
        if not callable(self.runner):
            raise HistoricalRuntimeTypeError("historical runner must be callable")


def create_historical_initial_state(
    *,
    company_name: str,
    trade_date: str,
    asset_type: str,
    instrument_context: str,
) -> dict[str, object]:
    """Create the current graph state shape without memory or current-provider access."""

    propagator = Propagator()
    return propagator.create_initial_state(
        company_name,
        trade_date,
        asset_type=asset_type,
        past_context="",
        instrument_context=instrument_context,
    )


def _require_runtime(runtime: object | None) -> OfflineGraphRuntime:
    if runtime is None:
        raise HistoricalRuntimeUnavailableError(
            "an explicit approved local/offline graph runtime is required"
        )
    if type(runtime) is not OfflineGraphRuntime:
        raise HistoricalRuntimeTypeError(
            "historical execution requires the exact OfflineGraphRuntime type"
        )
    return runtime


def _assert_string_mapping(
    value: object,
    *,
    field: str,
    required_fields: set[str],
) -> None:
    if not isinstance(value, Mapping) or set(value) != required_fields:
        raise HistoricalRuntimeOutputError(f"invalid historical {field} shape")
    for key, item in value.items():
        if key == "count":
            if isinstance(item, bool) or not isinstance(item, int):
                raise HistoricalRuntimeOutputError(
                    f"invalid historical {field} count"
                )
        elif not isinstance(item, str):
            raise HistoricalRuntimeOutputError(
                f"invalid historical {field} prose field"
            )


def _contains_authority_field(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _AUTHORITY_FIELDS:
                return True
            if _contains_authority_field(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_authority_field(item) for item in value)
    return False


def _validated_final_state(
    output: object,
    *,
    initial_state: dict[str, object],
) -> dict[str, object]:
    if type(output) is not dict:
        raise HistoricalRuntimeOutputError(
            "historical runtime must return a plain final-state mapping"
        )
    final_state: dict[str, Any] = dict(output)
    if _contains_authority_field(final_state):
        raise HistoricalRuntimeOutputError(
            "historical research output cannot contain authority fields"
        )

    for field in _PROSE_FIELDS:
        if not isinstance(final_state.get(field), str):
            raise HistoricalRuntimeOutputError(
                f"historical runtime output requires string field {field}"
            )
    if not isinstance(final_state.get("messages"), list):
        raise HistoricalRuntimeOutputError(
            "historical runtime output requires the current messages list"
        )

    _assert_string_mapping(
        final_state.get("investment_debate_state"),
        field="investment debate",
        required_fields=_INVEST_DEBATE_FIELDS,
    )
    _assert_string_mapping(
        final_state.get("risk_debate_state"),
        field="risk debate",
        required_fields=_RISK_DEBATE_FIELDS,
    )

    for field in (
        "company_of_interest",
        "asset_type",
        "instrument_context",
        "trade_date",
        "past_context",
    ):
        if final_state.get(field) != initial_state[field]:
            raise HistoricalRuntimeOutputError(
                f"historical runtime changed bound state field {field}"
            )
    return final_state


def run_historical(
    runtime: OfflineGraphRuntime | None,
    bundle: object,
    context: object,
    *,
    company_name: str,
    trade_date: str,
    asset_type: str = "stock",
    instrument_context: str,
) -> tuple[dict[str, object], str]:
    """Invoke exactly one explicit runner and preserve the legacy prose/signal shape."""

    checked_runtime = _require_runtime(runtime)
    initial_state = create_historical_initial_state(
        company_name=company_name,
        trade_date=trade_date,
        asset_type=asset_type,
        instrument_context=instrument_context,
    )
    output = checked_runtime.runner(bundle, context, initial_state)
    final_state = _validated_final_state(output, initial_state=initial_state)
    signal = SignalProcessor().process_signal(final_state["final_trade_decision"])
    return final_state, signal


__all__ = [
    "HistoricalRuntimeError",
    "HistoricalRuntimeOutputError",
    "HistoricalRuntimeTypeError",
    "HistoricalRuntimeUnavailableError",
    "OfflineGraphRuntime",
    "create_historical_initial_state",
    "run_historical",
]

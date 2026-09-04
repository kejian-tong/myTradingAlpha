"""Explicit, side-effect-free execution seam for caller-supplied historical runtimes.

This module deliberately does not construct :class:`TradingAgentsGraph`.  A caller owns
the opaque evidence/context objects and supplies the only runner that may be invoked.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import (
    AIMessage,
    ChatMessage,
    FunctionMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

from .propagation import Propagator
from .signal_processing import SignalProcessor

_BOUND_FIELDS = (
    "company_of_interest",
    "asset_type",
    "instrument_context",
    "trade_date",
    "past_context",
)
_SUPPORTED_MESSAGE_TYPES = (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    FunctionMessage,
    ChatMessage,
    RemoveMessage,
)
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
    "portfolio",
    "portfolio_weights",
    "order",
    "orders",
    "order_intent",
    "order_intents",
    "order_type",
    "quantity",
    "quantities",
    "broker",
    "broker_fields",
    "broker_id",
    "broker_credentials",
    "credential",
    "credentials",
    "risk_authorization",
    "risk_authorizations",
}
_ALLOWED_FINAL_STATE_FIELDS = {
    "messages",
    "company_of_interest",
    "asset_type",
    "instrument_context",
    "trade_date",
    "sender",
    *_REPORT_FIELDS,
    "investment_debate_state",
    "investment_plan",
    "trader_investment_plan",
    "risk_debate_state",
    "final_trade_decision",
    "past_context",
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


def _contains_encoded_argument_authority(call: object, field: str) -> bool:
    if type(call) is not dict or field not in call:
        raise HistoricalRuntimeOutputError("historical call requires structured arguments")
    arguments = call[field]
    if type(arguments) is not str:
        raise HistoricalRuntimeOutputError("historical call arguments require a JSON object")
    try:
        decoded = json.loads(arguments)
    except ValueError as exc:
        raise HistoricalRuntimeOutputError("invalid historical call argument JSON") from exc
    if type(decoded) is not dict:
        raise HistoricalRuntimeOutputError("historical call arguments require a JSON object")
    return _contains_authority_field(decoded)


def _contains_ai_call_authority(message: AIMessage) -> bool:
    # Only these known structured argument locations encode JSON. Research prose
    # and arbitrary metadata strings remain prose and are never parsed as calls.
    additional = message.additional_kwargs
    if type(additional) is not dict:
        raise HistoricalRuntimeOutputError("historical AI metadata requires a plain mapping")
    if "function_call" in additional and _contains_encoded_argument_authority(
        additional["function_call"], "arguments"
    ):
        return True
    raw_calls = additional.get("tool_calls", [])
    if type(raw_calls) is not list or type(message.invalid_tool_calls) is not list:
        raise HistoricalRuntimeOutputError("historical AI call collections require plain lists")
    for call in raw_calls:
        if type(call) is not dict or "function" not in call:
            raise HistoricalRuntimeOutputError("historical AI call requires a function mapping")
        if _contains_encoded_argument_authority(call["function"], "arguments"):
            return True
    return any(
        _contains_encoded_argument_authority(call, "args")
        for call in message.invalid_tool_calls
    )


def _contains_authority_field(value: object) -> bool:
    if type(value) in _SUPPORTED_MESSAGE_TYPES:
        # Inspect concrete message data, including Pydantic extras, without calling
        # serializers that could execute opaque/custom payload methods.
        if _contains_authority_field(value.__dict__) or _contains_authority_field(
            value.__pydantic_extra__
        ):
            return True
        return type(value) is AIMessage and _contains_ai_call_authority(value)
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise HistoricalRuntimeOutputError("historical output requires string data keys")
            if key.lower() in _AUTHORITY_FIELDS:
                return True
            if _contains_authority_field(item):
                return True
    elif type(value) in (list, tuple):
        return any(_contains_authority_field(item) for item in value)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise HistoricalRuntimeOutputError(
            "historical output contains an unsupported opaque data or message object"
        )
    return False


def _validated_final_state(
    output: object,
    *,
    bound_state: dict[str, object],
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
    if not final_state.keys() <= _ALLOWED_FINAL_STATE_FIELDS:
        raise HistoricalRuntimeOutputError(
            "historical runtime output contains fields outside AgentState"
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
    if "sender" in final_state and not isinstance(final_state["sender"], str):
        raise HistoricalRuntimeOutputError(
            "historical runtime output requires a string sender"
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

    for field in _BOUND_FIELDS:
        if final_state.get(field) != bound_state[field]:
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
    # Bound values are strings; this private mapping shares no mutable state with
    # the runner's input and is never passed to the runner.
    bound_state = {field: initial_state[field] for field in _BOUND_FIELDS}
    output = checked_runtime.runner(bundle, context, initial_state)
    final_state = _validated_final_state(output, bound_state=bound_state)
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

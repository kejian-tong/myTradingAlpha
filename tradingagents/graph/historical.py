"""Explicit, side-effect-free execution seam for caller-supplied historical runtimes.

This module deliberately does not construct :class:`TradingAgentsGraph`.  A caller owns
the opaque evidence/context objects and supplies the only runner that may be invoked.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
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
    convert_to_messages,
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
_SUPPORTED_MESSAGE_TYPES = {
    AIMessage: "ai",
    HumanMessage: "human",
    SystemMessage: "system",
    ToolMessage: "tool",
    FunctionMessage: "function",
    ChatMessage: "chat",
    RemoveMessage: "remove",
}
_CONSTRUCTOR_MESSAGE_NAMES = {
    "AIMessage", "AIMessageChunk", "HumanMessage", "HumanMessageChunk",
    "SystemMessage", "SystemMessageChunk", "ToolMessage", "ToolMessageChunk",
    "FunctionMessage", "FunctionMessageChunk", "RemoveMessage",
}
_OBJECT_CALL_BLOCKS = {"tool_call", "server_tool_call"}
_ENCODED_CALL_BLOCKS = {"invalid_tool_call", "tool_call_chunk", "server_tool_call_chunk"}
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


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate call argument member")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-JSON call argument constant")


def _validate_call_arguments(
    call: object, field: str, *, encoded: bool, require_string: bool = False,
) -> None:
    if type(call) is not dict or field not in call:
        raise HistoricalRuntimeOutputError("historical call requires structured arguments")
    arguments = call[field]
    if require_string and type(arguments) is not str:
        raise HistoricalRuntimeOutputError("encoded historical call arguments require JSON strings")
    if encoded and type(arguments) is str:
        try:
            arguments = json.loads(
                arguments, object_pairs_hook=_json_object, parse_constant=_reject_json_constant,
            )
        except ValueError as exc:
            raise HistoricalRuntimeOutputError("invalid historical call argument JSON") from exc
        if _contains_authority_field(arguments, allow_messages=False):
            raise HistoricalRuntimeOutputError("historical calls cannot contain authority fields")
        _validate_call_tree(arguments)
    if type(arguments) is not dict:
        raise HistoricalRuntimeOutputError("historical call arguments require a JSON object")


def _validate_function_call(call: object) -> None:
    if type(call) is not dict or type(call.get("name")) is not str:
        raise HistoricalRuntimeOutputError("historical function calls require a plain name")
    _validate_call_arguments(call, "arguments", encoded=True)


def _validate_call_list(
    calls: object, *, normalized: bool = False, encoded_kind: str | None = None,
) -> None:
    if type(calls) is not list:
        raise HistoricalRuntimeOutputError("historical call collections require plain lists")
    for call in calls:
        if type(call) is not dict:
            raise HistoricalRuntimeOutputError("historical calls require plain mappings")
        if type(call.get("id")) not in (str, type(None)):
            raise HistoricalRuntimeOutputError("invalid historical call identifier")
        if "function" in call:
            if normalized or encoded_kind or call.get("type", "function") != "function":
                raise HistoricalRuntimeOutputError("invalid normalized historical call shape")
            _validate_function_call(call["function"])
            # Normalization drops conflicting sibling arguments; inspect them too.
            if "args" in call:
                _validate_call_arguments(call, "args", encoded=False)
        elif encoded_kind:
            if (
                call.get("type", encoded_kind) != encoded_kind
                or type(call.get("name")) not in (str, type(None))
            ):
                raise HistoricalRuntimeOutputError("invalid encoded historical call shape")
            _validate_call_arguments(call, "args", encoded=True, require_string=True)
        else:
            if (
                call.get("type", "tool_call") != "tool_call"
                or type(call.get("name")) is not str or "id" not in call
            ):
                raise HistoricalRuntimeOutputError("invalid normalized historical call shape")
            _validate_call_arguments(call, "args", encoded=False)


def _validate_call_tree(value: object, *, normalized: bool = False) -> None:
    """Inspect recognized call locations in the ORIGINAL data, including shadowed fields.

    Only call arguments encode JSON. Prose/description strings are never parsed.
    This walk does not translate provider content, deserialize objects, or execute calls.
    """
    if type(value) is dict:
        for field in ("additional_kwargs", "response_metadata"):
            if field in value and type(value[field]) is not dict:
                raise HistoricalRuntimeOutputError("historical metadata requires a plain mapping")
        if "function_call" in value:
            _validate_function_call(value["function_call"])
        if "tool_calls" in value:
            _validate_call_list(value["tool_calls"], normalized=normalized)
        for field in ("invalid_tool_calls", "tool_call_chunks", "server_tool_call_chunks"):
            if field in value:
                _validate_call_list(value[field], encoded_kind=field.removesuffix("s"))
        kind = value.get("type")
        if type(kind) is str:
            if kind in _OBJECT_CALL_BLOCKS:
                if type(value.get("name")) is not str or "id" not in value:
                    raise HistoricalRuntimeOutputError("invalid historical call block shape")
                _validate_call_arguments(value, "args", encoded=False)
            elif kind in _ENCODED_CALL_BLOCKS:
                _validate_call_arguments(value, "args", encoded=True, require_string=True)
            elif kind == "function_call":
                # OpenAI Responses stores arguments directly in this content block.
                _validate_function_call(value)
            elif kind.endswith((
                "tool_call", "tool_call_chunk", "tool_use", "function_call", "function_call_chunk",
            )):
                raise HistoricalRuntimeOutputError("unsupported historical execution-bearing block")
        for item in value.values():
            _validate_call_tree(item)
    elif type(value) in (list, tuple):
        for item in value:
            _validate_call_tree(item)


def _validate_message_content(content: object, *, nullable: bool = False) -> None:
    if type(content) is str or (nullable and content is None):
        return
    if type(content) is not list or any(type(item) not in (str, dict) for item in content):
        raise HistoricalRuntimeOutputError("invalid historical message content shape")
    for block in content:
        if type(block) is dict and any(
            field in block for field in ("args", "arguments", "input", "function")
        ):
            kind = block.get("type")
            if type(kind) is not str or kind not in (
                _OBJECT_CALL_BLOCKS | _ENCODED_CALL_BLOCKS | {"function_call"}
            ):
                raise HistoricalRuntimeOutputError("unsupported historical execution-bearing block")


def _validate_message(message: object) -> None:
    if type(message) in _SUPPORTED_MESSAGE_TYPES:
        # Read stored fields, never serializers, content_blocks, or provider adapters.
        data = message.__dict__
        extras = message.__pydantic_extra__
        if data.get("type") != _SUPPORTED_MESSAGE_TYPES[type(message)]:
            raise HistoricalRuntimeOutputError("invalid concrete historical message type")
        _validate_message_content(data.get("content"))
        for field in ("additional_kwargs", "response_metadata"):
            if type(data.get(field)) is not dict:
                raise HistoricalRuntimeOutputError("historical metadata requires a plain mapping")
        # Existing messages bypass LangChain conversion and can have mutated fields.
        if type(message) is AIMessage and (
            "tool_calls" not in data or "invalid_tool_calls" not in data
        ):
            raise HistoricalRuntimeOutputError("missing normalized historical call collections")
        _validate_call_tree(data, normalized=type(message) is AIMessage)
        _validate_call_tree(extras)
        return

    # This scan precedes deepcopy/conversion so opaque objects cannot run copy hooks,
    # coercions, or serializers. Conversion receives only defensive plain data.
    if _contains_authority_field(message, allow_messages=False):
        raise HistoricalRuntimeOutputError("historical messages cannot contain authority fields")
    _validate_call_tree(message)
    if type(message) is dict:
        fields = message
        if message.get("type") == "constructor":
            identifier = message.get("id")
            if (
                type(message.get("lc")) is not int or message["lc"] != 1
                or type(identifier) is not list or not identifier
                or any(type(part) is not str for part in identifier)
                or identifier[-1] not in _CONSTRUCTOR_MESSAGE_NAMES
                or type(message.get("kwargs")) is not dict
            ):
                raise HistoricalRuntimeOutputError("unsupported historical message constructor")
            fields = message["kwargs"]
        if "content" in message:
            _validate_message_content(message["content"], nullable=True)
        if "content" in fields:
            _validate_message_content(fields["content"], nullable=True)
    elif type(message) in (tuple, list):
        if len(message) != 2 or type(message[0]) is not str:
            raise HistoricalRuntimeOutputError("invalid historical role/content message")
        _validate_message_content(message[1])
    elif type(message) is not str:
        raise HistoricalRuntimeOutputError("unsupported historical message representation")
    try:
        # Installed convert_to_messages uses a finite message-class mapping. Inspect
        # both sides: it merges metadata and can drop outer envelope/Remove content.
        canonical = convert_to_messages([deepcopy(message)])[0]
    except (ValueError, TypeError, KeyError, NotImplementedError) as exc:
        raise HistoricalRuntimeOutputError("invalid historical message representation") from exc
    if type(canonical) not in _SUPPORTED_MESSAGE_TYPES:
        raise HistoricalRuntimeOutputError("unsupported canonical historical message")
    if _contains_authority_field(canonical):
        raise HistoricalRuntimeOutputError("historical messages cannot contain authority fields")
    _validate_message(canonical)


def _contains_authority_field(value: object, *, allow_messages: bool = True) -> bool:
    if allow_messages and type(value) in _SUPPORTED_MESSAGE_TYPES:
        # Inspect concrete message data, including Pydantic extras, without calling
        # serializers that could execute opaque/custom payload methods.
        return (
            _contains_authority_field(value.__dict__, allow_messages=False)
            or _contains_authority_field(value.__pydantic_extra__, allow_messages=False)
        )
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise HistoricalRuntimeOutputError("historical output requires string data keys")
            if key.lower() in _AUTHORITY_FIELDS:
                return True
            if _contains_authority_field(item, allow_messages=allow_messages):
                return True
    elif type(value) in (list, tuple):
        return any(_contains_authority_field(item, allow_messages=allow_messages) for item in value)
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
    for message in final_state["messages"]:
        _validate_message(message)
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
    try:
        final_state = _validated_final_state(output, bound_state=bound_state)
    except RecursionError as exc:
        raise HistoricalRuntimeOutputError("cyclic or excessively nested historical output") from exc
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

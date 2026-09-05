"""Pure validation of closed, cached historical graph responses.

This module accepts plain data only. It does not construct a graph, load code,
invoke tools, deserialize provider objects, or perform model inference.
"""

from __future__ import annotations

import json
from copy import deepcopy
from math import isfinite
from typing import Any

from .propagation import Propagator
from .signal_processing import SignalProcessor

_BOUND_FIELDS = (
    "company_of_interest",
    "asset_type",
    "instrument_context",
    "trade_date",
    "past_context",
)
_REPORT_FIELDS = ("market_report", "fundamentals_report", "sentiment_report", "news_report")
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
# Only normalize spellings of this finite reserved namespace, not arbitrary prose.
_NORMALIZED_AUTHORITY_FIELDS = frozenset(field.replace("_", "") for field in _AUTHORITY_FIELDS)
_MESSAGE_ROLES = {
    "ai",
    "assistant",
    "human",
    "user",
    "system",
    "tool",
    "function",
    "chat",
    "remove",
}
_OBJECT_CALL_BLOCKS = {"tool_call", "server_tool_call"}
_ENCODED_CALL_BLOCKS = {"invalid_tool_call", "tool_call_chunk", "server_tool_call_chunk"}
_MAX_PLAIN_DEPTH = 64
_MAX_PLAIN_NODES = 100_000
_MAX_PLAIN_STRING_BYTES = 1_048_576


class HistoricalRuntimeError(ValueError):
    """Base class for cached historical response validation failures."""


class HistoricalRuntimeOutputError(HistoricalRuntimeError):
    """Raised when cached graph output is unsafe or incompatible."""


def _require_exact_bound_strings(
    *,
    company_name: object,
    trade_date: object,
    asset_type: object,
    instrument_context: object,
) -> None:
    if any(
        type(value) is not str
        for value in (company_name, trade_date, asset_type, instrument_context)
    ):
        raise HistoricalRuntimeOutputError("historical bound arguments require exact strings")


def create_historical_initial_state(
    *,
    company_name: str,
    trade_date: str,
    asset_type: str,
    instrument_context: str,
) -> dict[str, object]:
    """Create the current graph state shape without running the graph."""

    _require_exact_bound_strings(
        company_name=company_name,
        trade_date=trade_date,
        asset_type=asset_type,
        instrument_context=instrument_context,
    )
    return Propagator().create_initial_state(
        company_name,
        trade_date,
        asset_type=asset_type,
        past_context="",
        instrument_context=instrument_context,
    )


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise HistoricalRuntimeOutputError("historical output strings must be valid UTF-8") from exc


def _plain_data(
    value: object,
    *,
    seen: set[int],
    depth: int,
    counter: list[int],
) -> None:
    if depth > _MAX_PLAIN_DEPTH:
        raise HistoricalRuntimeOutputError("historical output exceeds maximum depth")
    counter[0] += 1
    if counter[0] > _MAX_PLAIN_NODES:
        raise HistoricalRuntimeOutputError("historical output exceeds maximum node count")
    value_type = type(value)
    if value_type is str:
        if _utf8_size(value) > _MAX_PLAIN_STRING_BYTES:
            raise HistoricalRuntimeOutputError("historical output string exceeds maximum size")
        return
    if value_type is float and not isfinite(value):
        raise HistoricalRuntimeOutputError("historical output requires finite numbers")
    if value_type in (int, float, bool, type(None)):
        return
    if value_type not in (dict, list):
        raise HistoricalRuntimeOutputError("historical output requires plain JSON data")
    identity = id(value)
    if identity in seen:
        raise HistoricalRuntimeOutputError("cyclic historical output")
    seen.add(identity)
    try:
        if value_type is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise HistoricalRuntimeOutputError(
                        "historical output requires string data keys"
                    )
                if _utf8_size(key) > _MAX_PLAIN_STRING_BYTES:
                    raise HistoricalRuntimeOutputError(
                        "historical output key exceeds maximum string size"
                    )
                _plain_data(
                    item,
                    seen=seen,
                    depth=depth + 1,
                    counter=counter,
                )
        else:
            for item in value:
                _plain_data(
                    item,
                    seen=seen,
                    depth=depth + 1,
                    counter=counter,
                )
    finally:
        seen.remove(identity)


def _bounded_plain_data(value: object) -> None:
    try:
        _plain_data(value, seen=set(), depth=1, counter=[0])
    except RecursionError as exc:
        raise HistoricalRuntimeOutputError("historical output exceeds maximum depth") from exc


def _contains_authority_field(value: object) -> bool:
    if type(value) is dict:
        for key, item in value.items():
            normalized_key = key.casefold().replace("_", "").replace("-", "")
            if normalized_key in _NORMALIZED_AUTHORITY_FIELDS or _contains_authority_field(item):
                return True
    elif type(value) is list:
        return any(_contains_authority_field(item) for item in value)
    return False


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate call argument member")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite call argument")


def _parse_argument_object(value: object) -> dict[str, object]:
    if type(value) is not str:
        raise HistoricalRuntimeOutputError("encoded historical call arguments require JSON strings")
    try:
        parsed = json.loads(value, object_pairs_hook=_json_object, parse_constant=_reject_constant)
    except (ValueError, OverflowError, RecursionError) as exc:
        raise HistoricalRuntimeOutputError("invalid historical call argument JSON") from exc
    _bounded_plain_data(parsed)
    if type(parsed) is not dict:
        raise HistoricalRuntimeOutputError("historical call arguments require a JSON object")
    if _contains_authority_field(parsed):
        raise HistoricalRuntimeOutputError("historical calls cannot contain authority fields")
    return parsed


def _validate_object_arguments(value: object) -> None:
    if type(value) is not dict:
        raise HistoricalRuntimeOutputError("historical call arguments require a plain object")
    _bounded_plain_data(value)
    if _contains_authority_field(value):
        raise HistoricalRuntimeOutputError("historical calls cannot contain authority fields")


def _validate_function_call(call: object) -> None:
    if type(call) is not dict or type(call.get("name")) is not str or "arguments" not in call:
        raise HistoricalRuntimeOutputError("invalid historical function call")
    _parse_argument_object(call["arguments"])


def _validate_call_list(calls: object, *, kind: str) -> None:
    if type(calls) is not list:
        raise HistoricalRuntimeOutputError("historical call collections require plain lists")
    for call in calls:
        if type(call) is not dict:
            raise HistoricalRuntimeOutputError("historical calls require plain objects")
        if kind == "raw_tool_calls":
            if call.get("type", "function") != "function" or type(call.get("id")) not in (
                str,
                type(None),
            ):
                raise HistoricalRuntimeOutputError("invalid raw historical call identity")
            _validate_function_call(call.get("function"))
        elif kind == "tool_calls":
            if (
                call.get("type", "tool_call") != "tool_call"
                or type(call.get("name")) is not str
                or type(call.get("id")) not in (str, type(None))
                or "id" not in call
            ):
                raise HistoricalRuntimeOutputError("invalid normalized historical call identity")
            _validate_object_arguments(call.get("args"))
        else:
            expected = kind.removesuffix("s")
            if (
                call.get("type", expected) != expected
                or type(call.get("id")) not in (str, type(None))
                or type(call.get("name")) not in (str, type(None))
            ):
                raise HistoricalRuntimeOutputError("invalid encoded historical call identity")
            _parse_argument_object(call.get("args"))


def _validate_call_tree(value: object) -> None:
    if type(value) is dict:
        for field in ("additional_kwargs", "response_metadata"):
            if field in value and type(value[field]) is not dict:
                raise HistoricalRuntimeOutputError("historical metadata requires a plain object")
        if "function_call" in value:
            _validate_function_call(value["function_call"])
        if "tool_calls" in value:
            calls = value["tool_calls"]
            raw = type(calls) is list and any(
                type(item) is dict and "function" in item for item in calls
            )
            _validate_call_list(calls, kind="raw_tool_calls" if raw else "tool_calls")
        for field in ("invalid_tool_calls", "tool_call_chunks", "server_tool_call_chunks"):
            if field in value:
                _validate_call_list(value[field], kind=field)
        for item in value.values():
            _validate_call_tree(item)
    elif type(value) is list:
        for item in value:
            _validate_call_tree(item)


def _validate_content_block(block: dict[str, object]) -> None:
    kind = block.get("type")
    if kind == "non_standard":
        wrapped = block.get("value")
        if type(wrapped) is not dict:
            raise HistoricalRuntimeOutputError("historical content wrapper requires a plain object")
        _validate_content_block(wrapped)
        return
    if kind in _OBJECT_CALL_BLOCKS | _ENCODED_CALL_BLOCKS | {"function_call"}:
        id_field = "call_id" if kind == "function_call" else "id"
        optional_identity = kind == "server_tool_call_chunk"
        nullable_id = kind in {"tool_call", "invalid_tool_call", "tool_call_chunk"}
        nullable_name = kind in {"invalid_tool_call", "tool_call_chunk"}
        for field, nullable in ((id_field, nullable_id), ("name", nullable_name)):
            if field not in block:
                if optional_identity:
                    continue
                raise HistoricalRuntimeOutputError("missing historical content-call identity")
            if type(block[field]) is not str and not (nullable and block[field] is None):
                raise HistoricalRuntimeOutputError("invalid historical content-call identity")
        argument_field = "arguments" if kind == "function_call" else "args"
        if kind in _OBJECT_CALL_BLOCKS:
            _validate_object_arguments(block.get(argument_field))
        else:
            _parse_argument_object(block.get(argument_field))
        for field, types in (
            ("index", (int, str)),
            ("extras", (dict,)),
            ("error", (str, type(None))),
        ):
            if field in block and (
                type(block[field]) not in types or (field == "index" and type(block[field]) is bool)
            ):
                raise HistoricalRuntimeOutputError("invalid historical content-call metadata")
    elif any(field in block for field in ("args", "arguments", "input", "function")):
        raise HistoricalRuntimeOutputError("unsupported historical execution-bearing block")


def _validate_message_content(content: object) -> None:
    if type(content) is str or content is None:
        return
    if type(content) is not list or any(type(item) not in (str, dict) for item in content):
        raise HistoricalRuntimeOutputError("invalid historical message content")
    for item in content:
        if type(item) is dict:
            _validate_content_block(item)


def _validate_message(message: object) -> None:
    if type(message) is str:
        return
    if type(message) is list:
        if len(message) != 2 or type(message[0]) is not str or message[0] not in _MESSAGE_ROLES:
            raise HistoricalRuntimeOutputError("invalid historical role/content message")
        _validate_message_content(message[1])
        _validate_call_tree(message)
        return
    if type(message) is not dict or "content" not in message:
        raise HistoricalRuntimeOutputError("unsupported historical message representation")
    selectors = [field for field in ("role", "type") if field in message]
    if len(selectors) != 1:
        raise HistoricalRuntimeOutputError("historical messages require one exact role selector")
    selector = message[selectors[0]]
    if type(selector) is not str or selector not in _MESSAGE_ROLES:
        raise HistoricalRuntimeOutputError("invalid historical message role")
    _validate_message_content(message["content"])
    _validate_call_tree(message)


def _assert_debate(value: object, *, field: str, required: set[str]) -> None:
    if type(value) is not dict or set(value) != required:
        raise HistoricalRuntimeOutputError(f"invalid historical {field} shape")
    for key, item in value.items():
        if key == "count":
            if type(item) is not int:
                raise HistoricalRuntimeOutputError(f"invalid historical {field} count")
        elif type(item) is not str:
            raise HistoricalRuntimeOutputError(f"invalid historical {field} prose")


def validate_historical_response(
    output: object,
    *,
    company_name: str,
    trade_date: str,
    asset_type: str = "stock",
    instrument_context: str,
) -> tuple[dict[str, object], str]:
    """Validate plain cached output and return a defensive legacy state/signal."""

    _require_exact_bound_strings(
        company_name=company_name,
        trade_date=trade_date,
        asset_type=asset_type,
        instrument_context=instrument_context,
    )
    _bounded_plain_data(output)
    if type(output) is not dict:
        raise HistoricalRuntimeOutputError("historical response must be a plain final-state object")
    if _contains_authority_field(output):
        raise HistoricalRuntimeOutputError("historical response cannot contain authority fields")
    if not output.keys() <= _ALLOWED_FINAL_STATE_FIELDS:
        raise HistoricalRuntimeOutputError("historical response contains fields outside AgentState")
    final_state: dict[str, Any] = deepcopy(output)
    bound = create_historical_initial_state(
        company_name=company_name,
        trade_date=trade_date,
        asset_type=asset_type,
        instrument_context=instrument_context,
    )
    for field in _PROSE_FIELDS:
        if type(final_state.get(field)) is not str:
            raise HistoricalRuntimeOutputError(f"historical response requires string field {field}")
    if type(final_state.get("messages")) is not list:
        raise HistoricalRuntimeOutputError("historical response requires a messages list")
    for message in final_state["messages"]:
        _validate_message(message)
    if "sender" in final_state and type(final_state["sender"]) is not str:
        raise HistoricalRuntimeOutputError("historical response requires a string sender")
    _assert_debate(
        final_state.get("investment_debate_state"),
        field="investment debate",
        required=_INVEST_DEBATE_FIELDS,
    )
    _assert_debate(
        final_state.get("risk_debate_state"), field="risk debate", required=_RISK_DEBATE_FIELDS
    )
    for field in _BOUND_FIELDS:
        if final_state.get(field) != bound[field]:
            raise HistoricalRuntimeOutputError(
                f"historical response changed bound state field {field}"
            )
    signal = SignalProcessor().process_signal(final_state["final_trade_decision"])
    return final_state, signal


__all__ = [
    "HistoricalRuntimeError",
    "HistoricalRuntimeOutputError",
    "create_historical_initial_state",
    "validate_historical_response",
]

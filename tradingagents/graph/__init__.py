"""Public graph exports resolved lazily from a closed module map."""

from __future__ import annotations

from typing import Any

__all__ = [
    "TradingAgentsGraph",
    "ConditionalLogic",
    "GraphSetup",
    "HistoricalRuntimeError",
    "HistoricalRuntimeOutputError",
    "Propagator",
    "Reflector",
    "SignalProcessor",
    "create_historical_initial_state",
    "validate_historical_response",
]

_EXPORTS = {
    "TradingAgentsGraph": ("tradingagents.graph.trading_graph", "TradingAgentsGraph"),
    "ConditionalLogic": ("tradingagents.graph.conditional_logic", "ConditionalLogic"),
    "GraphSetup": ("tradingagents.graph.setup", "GraphSetup"),
    "HistoricalRuntimeError": (
        "tradingagents.graph.historical",
        "HistoricalRuntimeError",
    ),
    "HistoricalRuntimeOutputError": (
        "tradingagents.graph.historical",
        "HistoricalRuntimeOutputError",
    ),
    "Propagator": ("tradingagents.graph.propagation", "Propagator"),
    "Reflector": ("tradingagents.graph.reflection", "Reflector"),
    "SignalProcessor": ("tradingagents.graph.signal_processing", "SignalProcessor"),
    "create_historical_initial_state": (
        "tradingagents.graph.historical",
        "create_historical_initial_state",
    ),
    "validate_historical_response": (
        "tradingagents.graph.historical",
        "validate_historical_response",
    ),
}


def _load_export(name: str) -> Any:
    if name == "TradingAgentsGraph":
        from .trading_graph import TradingAgentsGraph

        values = {"TradingAgentsGraph": TradingAgentsGraph}
    elif name == "ConditionalLogic":
        from .conditional_logic import ConditionalLogic

        values = {"ConditionalLogic": ConditionalLogic}
    elif name == "GraphSetup":
        from .setup import GraphSetup

        values = {"GraphSetup": GraphSetup}
    elif name in {
        "HistoricalRuntimeError",
        "HistoricalRuntimeOutputError",
        "create_historical_initial_state",
        "validate_historical_response",
    }:
        from .historical import (
            HistoricalRuntimeError,
            HistoricalRuntimeOutputError,
            create_historical_initial_state,
            validate_historical_response,
        )

        values = {
            "HistoricalRuntimeError": HistoricalRuntimeError,
            "HistoricalRuntimeOutputError": HistoricalRuntimeOutputError,
            "create_historical_initial_state": create_historical_initial_state,
            "validate_historical_response": validate_historical_response,
        }
    elif name == "Propagator":
        from .propagation import Propagator

        values = {"Propagator": Propagator}
    elif name == "Reflector":
        from .reflection import Reflector

        values = {"Reflector": Reflector}
    elif name == "SignalProcessor":
        from .signal_processing import SignalProcessor

        values = {"SignalProcessor": SignalProcessor}
    else:  # pragma: no cover - the closed map has no other values
        raise AssertionError(f"unhandled graph export {name!r}")
    return values[name]


def __getattr__(name: str) -> Any:
    """Resolve a documented public export from the fixed map."""

    try:
        _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = _load_export(name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

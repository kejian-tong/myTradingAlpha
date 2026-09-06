"""Public agent exports resolved lazily from a closed module map."""

from __future__ import annotations

from typing import Any

__all__ = [
    "AgentState",
    "create_msg_delete",
    "InvestDebateState",
    "RiskDebateState",
    "create_bear_researcher",
    "create_bull_researcher",
    "create_research_manager",
    "create_fundamentals_analyst",
    "create_market_analyst",
    "create_neutral_debator",
    "create_news_analyst",
    "create_aggressive_debator",
    "create_portfolio_manager",
    "create_conservative_debator",
    "create_sentiment_analyst",
    "create_social_media_analyst",  # deprecated; will be removed in a future version
    "create_trader",
]

_EXPORTS = {
    "AgentState": ("tradingagents.agents.utils.agent_states", "AgentState"),
    "create_msg_delete": ("tradingagents.agents.utils.agent_utils", "create_msg_delete"),
    "InvestDebateState": (
        "tradingagents.agents.utils.agent_states",
        "InvestDebateState",
    ),
    "RiskDebateState": ("tradingagents.agents.utils.agent_states", "RiskDebateState"),
    "create_bear_researcher": (
        "tradingagents.agents.researchers.bear_researcher",
        "create_bear_researcher",
    ),
    "create_bull_researcher": (
        "tradingagents.agents.researchers.bull_researcher",
        "create_bull_researcher",
    ),
    "create_research_manager": (
        "tradingagents.agents.managers.research_manager",
        "create_research_manager",
    ),
    "create_fundamentals_analyst": (
        "tradingagents.agents.analysts.fundamentals_analyst",
        "create_fundamentals_analyst",
    ),
    "create_market_analyst": (
        "tradingagents.agents.analysts.market_analyst",
        "create_market_analyst",
    ),
    "create_neutral_debator": (
        "tradingagents.agents.risk_mgmt.neutral_debator",
        "create_neutral_debator",
    ),
    "create_news_analyst": (
        "tradingagents.agents.analysts.news_analyst",
        "create_news_analyst",
    ),
    "create_aggressive_debator": (
        "tradingagents.agents.risk_mgmt.aggressive_debator",
        "create_aggressive_debator",
    ),
    "create_portfolio_manager": (
        "tradingagents.agents.managers.portfolio_manager",
        "create_portfolio_manager",
    ),
    "create_conservative_debator": (
        "tradingagents.agents.risk_mgmt.conservative_debator",
        "create_conservative_debator",
    ),
    "create_sentiment_analyst": (
        "tradingagents.agents.analysts.sentiment_analyst",
        "create_sentiment_analyst",
    ),
    "create_social_media_analyst": (
        "tradingagents.agents.analysts.sentiment_analyst",
        "create_social_media_analyst",
    ),
    "create_trader": ("tradingagents.agents.trader.trader", "create_trader"),
}


def _load_export(name: str) -> Any:
    if name in {"AgentState", "InvestDebateState", "RiskDebateState"}:
        from .utils.agent_states import AgentState, InvestDebateState, RiskDebateState

        values = {
            "AgentState": AgentState,
            "InvestDebateState": InvestDebateState,
            "RiskDebateState": RiskDebateState,
        }
    elif name == "create_msg_delete":
        from .utils.agent_utils import create_msg_delete

        values = {"create_msg_delete": create_msg_delete}
    elif name == "create_bear_researcher":
        from .researchers.bear_researcher import create_bear_researcher

        values = {"create_bear_researcher": create_bear_researcher}
    elif name == "create_bull_researcher":
        from .researchers.bull_researcher import create_bull_researcher

        values = {"create_bull_researcher": create_bull_researcher}
    elif name == "create_research_manager":
        from .managers.research_manager import create_research_manager

        values = {"create_research_manager": create_research_manager}
    elif name == "create_fundamentals_analyst":
        from .analysts.fundamentals_analyst import create_fundamentals_analyst

        values = {"create_fundamentals_analyst": create_fundamentals_analyst}
    elif name == "create_market_analyst":
        from .analysts.market_analyst import create_market_analyst

        values = {"create_market_analyst": create_market_analyst}
    elif name == "create_neutral_debator":
        from .risk_mgmt.neutral_debator import create_neutral_debator

        values = {"create_neutral_debator": create_neutral_debator}
    elif name == "create_news_analyst":
        from .analysts.news_analyst import create_news_analyst

        values = {"create_news_analyst": create_news_analyst}
    elif name == "create_aggressive_debator":
        from .risk_mgmt.aggressive_debator import create_aggressive_debator

        values = {"create_aggressive_debator": create_aggressive_debator}
    elif name == "create_portfolio_manager":
        from .managers.portfolio_manager import create_portfolio_manager

        values = {"create_portfolio_manager": create_portfolio_manager}
    elif name == "create_conservative_debator":
        from .risk_mgmt.conservative_debator import create_conservative_debator

        values = {"create_conservative_debator": create_conservative_debator}
    elif name in {"create_sentiment_analyst", "create_social_media_analyst"}:
        from .analysts.sentiment_analyst import (
            create_sentiment_analyst,
            create_social_media_analyst,
        )

        values = {
            "create_sentiment_analyst": create_sentiment_analyst,
            "create_social_media_analyst": create_social_media_analyst,
        }
    elif name == "create_trader":
        from .trader.trader import create_trader

        values = {"create_trader": create_trader}
    else:  # pragma: no cover - the closed map has no other values
        raise AssertionError(f"unhandled agent export {name!r}")
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

"""Sealed EvidenceBundle adapter for the opt-in historical Research Graph seam."""

from __future__ import annotations

from datetime import date

from mytradingalpha.contracts.schemas import RunContext
from mytradingalpha.data.bundle import EvidenceBundle
from mytradingalpha.data.replay_guard import HistoricalDataGuard
from mytradingalpha.data.repository import EvidenceRepository
from mytradingalpha.data.universe import AssetClass, Instrument
from tradingagents.graph.historical import OfflineGraphRuntime, run_historical


class ResearchAdapterError(ValueError):
    """Base class for production-owned Research Graph adapter failures."""


class HistoricalInstrumentError(ResearchAdapterError):
    """Raised when sealed evidence cannot resolve one exact historical instrument."""


def _trade_date(value: object) -> date:
    if not isinstance(value, str):
        raise HistoricalInstrumentError("invalid trade date: expected an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise HistoricalInstrumentError("invalid trade date: expected YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise HistoricalInstrumentError("invalid trade date: expected exact YYYY-MM-DD")
    return parsed


def _active_on(value: date, start: date, end: date | None) -> bool:
    return start <= value and (end is None or value < end)


def _resolve_instrument(
    bundle: EvidenceBundle,
    *,
    ticker: str,
    trade_date: str,
    asset_type: str,
) -> tuple[Instrument, str]:
    as_of = _trade_date(trade_date)
    if not isinstance(ticker, str) or not ticker or ticker != ticker.strip():
        raise HistoricalInstrumentError("missing sealed instrument: invalid ticker")

    instrument_by_id = {item.instrument_id: item for item in bundle.instruments}
    candidate_ids = {
        alias.instrument_id
        for alias in bundle.aliases
        if alias.symbol == ticker
        and _active_on(as_of, alias.valid_from, alias.valid_to)
    }
    candidates = [
        instrument_by_id[instrument_id]
        for instrument_id in sorted(candidate_ids)
        if instrument_id in instrument_by_id
        and _active_on(
            as_of,
            instrument_by_id[instrument_id].active_from,
            instrument_by_id[instrument_id].active_to,
        )
    ]
    if not candidates:
        raise HistoricalInstrumentError(
            f"missing sealed instrument for ticker {ticker!r} on trade date {trade_date}"
        )
    if len(candidates) != 1:
        raise HistoricalInstrumentError(
            f"ambiguous sealed instrument for ticker {ticker!r} on trade date {trade_date}"
        )

    instrument = candidates[0]
    permitted_classes = (
        {AssetClass.EQUITY, AssetClass.ETF} if asset_type == "stock" else set()
    )
    if instrument.asset_class not in permitted_classes:
        raise HistoricalInstrumentError(
            f"asset type mismatch for sealed instrument {instrument.instrument_id!r}"
        )

    context = (
        f"Symbol: {ticker}; instrument_id: {instrument.instrument_id}; "
        f"asset_class: {instrument.asset_class.value}; exchange: {instrument.exchange}; "
        f"currency: {instrument.currency}"
    )
    return instrument, context


class ResearchAdapter:
    """Bind one sealed repository to one explicit offline Research Graph runtime."""

    def __init__(
        self,
        repository: EvidenceRepository,
        runtime: OfflineGraphRuntime | None,
    ) -> None:
        self._repository = repository
        self._runtime = runtime

    def run(
        self,
        bundle_id: str,
        context: RunContext,
        *,
        ticker: str,
        trade_date: str,
        asset_type: str = "stock",
    ) -> tuple[dict[str, object], str]:
        """Replay the exact sealed bundle and invoke the offline seam once."""

        bundle, bound_context = HistoricalDataGuard.replay_bound(
            self._repository,
            bundle_id,
            context,
        )
        _, instrument_context = _resolve_instrument(
            bundle,
            ticker=ticker,
            trade_date=trade_date,
            asset_type=asset_type,
        )
        return run_historical(
            self._runtime,
            bundle,
            bound_context,
            company_name=ticker,
            trade_date=trade_date,
            asset_type=asset_type,
            instrument_context=instrument_context,
        )


__all__ = [
    "HistoricalInstrumentError",
    "ResearchAdapter",
    "ResearchAdapterError",
]

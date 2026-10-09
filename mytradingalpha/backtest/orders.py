"""Private per-run order scratch owned by the pure BT-02 simulator."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SimOrder:
    """Immutable terminal or horizon summary for one fixture intent."""

    intent_id: str
    remaining_quantity: Decimal
    cumulative_quantity: Decimal
    cumulative_fee: Decimal
    status: str
    reason_code: str | None


class OrderBook:
    """Run-local mutable reducer state; never shared across simulator calls."""

    __slots__ = ("_orders",)

    def __init__(self) -> None:
        self._orders: dict[str, object] = {}

    def add(self, intent_id: str, order: object) -> None:
        self._orders[intent_id] = order

    def get(self, intent_id: str) -> object:
        return self._orders[intent_id]

    def values(self) -> tuple[object, ...]:
        return tuple(self._orders[key] for key in sorted(self._orders))


__all__ = ["OrderBook", "SimOrder"]

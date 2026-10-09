"""Stable BT-02 public facade for explicit, versioned offline costs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, localcontext
from itertools import islice
from typing import Literal

from pydantic import StrictStr, model_validator

from mytradingalpha.contracts.orders import (
    CostBreakdown,
    OrderInputError,
    _canonical_json,
    _contract_storage_fingerprint,
    _decimal,
    _fixed_context,
    _raw_payload,
    _require_complete_payload,
    _safe_id_token,
    _safe_string,
    _StrictContract,
    _wire_mapping,
    _wire_payload,
)

_POLICY_DOMAIN = b"mytradingalpha:bt02:cost-policy:v1\0"
_ZERO = Decimal("0")
_MAX_QTY = Decimal("1000000000")
_MAX_RATE = Decimal("1000000")
_MAX_MONEY = Decimal("1E24")


def _reject(reason: str = "policy_invalid") -> None:
    raise OrderInputError(reason) from None


def _validate_policy_payload(p: dict[str, object]) -> None:
    for name in (
        "schema_version", "policy_version", "numeric_policy_version",
        "fee_policy_id", "currency",
    ):
        _safe_string(p[name])
        _safe_id_token(p[name])
    if (
        p["schema_version"] != "v1"
        or p["numeric_policy_version"] != "bt02-decimal-v1"
        or p["fee_policy_id"] != "bt02-usd-cumulative-v1"
        or p["currency"] != "USD"
    ):
        _reject("policy_invalid")
    half = _decimal(
        p["half_spread_bps"], low_exp=-6, high_exp=6, max_adjusted=4,
        maximum=Decimal("9999"), nonnegative=True,
    )
    slip = _decimal(
        p["slippage_bps"], low_exp=-6, high_exp=6, max_adjusted=4,
        maximum=Decimal("9999"), nonnegative=True,
    )
    with localcontext(_fixed_context()):
        total_bps = half + slip
    if total_bps >= Decimal("10000"):
        _reject("policy_invalid")
    _decimal(
        p["commission_per_share"], low_exp=-6, high_exp=6,
        max_adjusted=6, maximum=_MAX_RATE, nonnegative=True,
    )
    _decimal(
        p["order_minimum"], low_exp=-6, high_exp=6,
        max_adjusted=6, maximum=_MAX_RATE, nonnegative=True,
    )
    _decimal(
        p["fixed_share_cap"], low_exp=-6, high_exp=9,
        max_adjusted=9, maximum=_MAX_QTY, nonnegative=True,
    )
    lot = _decimal(
        p["lot_size"], low_exp=-6, high_exp=9,
        max_adjusted=9, maximum=_MAX_QTY, positive=True,
    )
    if lot < Decimal("0.000001"):
        _reject("policy_invalid")


def _policy_payload(policy: object) -> dict[str, object]:
    if type(policy) is not CostPolicy:
        _reject("policy_invalid")
    try:
        storage = object.__getattribute__(policy, "__dict__")
        extra = object.__getattribute__(policy, "__pydantic_extra__")
        private = object.__getattribute__(policy, "__pydantic_private__")
        fields_set = object.__getattribute__(policy, "__pydantic_fields_set__")
    except Exception:
        _reject("policy_invalid")
    fields = tuple(CostPolicy.model_fields)
    if (
        type(storage) is not dict
        or extra is not None
        or private is not None
        or type(fields_set) is not set
        or set.__len__(fields_set) > 64
        or dict.__len__(storage) != len(fields)
    ):
        _reject("resource_limit" if type(fields_set) is set and set.__len__(fields_set) > 64 else "policy_invalid")
    keys = tuple(islice(dict.keys(storage), 65))
    metadata = tuple(islice(set.__iter__(fields_set), 65))
    if len(keys) > len(fields) or len(metadata) > 64:
        _reject("resource_limit")
    if any(type(item) is not str for item in metadata):
        _reject("policy_invalid")
    if set(metadata) != set(fields):
        _reject("policy_invalid")
    if any(type(key) is not str for key in keys) or any(
        not any(key == expected for expected in fields) for key in keys
    ):
        _reject("policy_invalid")
    return {name: dict.__getitem__(storage, name) for name in fields}


def revalidate_cost_policy(value: object) -> CostPolicy:
    payload = _policy_payload(value)
    try:
        return CostPolicy.model_validate(payload)
    except OrderInputError:
        _reject("policy_invalid")
    except Exception:
        _reject("policy_invalid")


class CostPolicy(_StrictContract):
    """Required economic assumptions and fixed numeric/fee policies."""

    schema_version: StrictStr
    policy_version: StrictStr
    numeric_policy_version: StrictStr
    fee_policy_id: StrictStr
    currency: StrictStr
    half_spread_bps: Decimal
    slippage_bps: Decimal
    commission_per_share: Decimal
    order_minimum: Decimal
    fixed_share_cap: Decimal
    lot_size: Decimal

    @classmethod
    def _guard_input(cls, value: dict[str, object]) -> dict[str, object]:
        _require_complete_payload(value, cls, "policy_invalid")
        _validate_policy_payload(value)
        return value

    @model_validator(mode="after")
    def validate_policy(self) -> CostPolicy:
        _validate_policy_payload(_raw_payload(self, include_id=True))
        return self

    def canonical_bytes(self) -> bytes:
        p = _raw_payload(revalidate_cost_policy(self), include_id=True)
        return _canonical_json(_wire_mapping(p))

    @property
    def policy_hash(self) -> str:
        return "sha256:" + hashlib.sha256(_POLICY_DOMAIN + self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class CostQuote:
    """Immutable quote containing all-in price and descriptive friction."""

    price: Decimal
    fee: Decimal
    cost_breakdown: CostBreakdown
    policy_version: str
    policy_hash: str


class CostModel:
    """Pure constant adverse spread/slippage and cumulative-fee model."""

    @staticmethod
    def quote(
        reference_price: Decimal,
        side: Literal["buy", "sell"] | str,
        filled_quantity: Decimal,
        cumulative_quantity: Decimal,
        policy: CostPolicy,
    ) -> CostQuote:
        ingress_storage = _contract_storage_fingerprint(policy, CostPolicy)
        owned_policy = revalidate_cost_policy(policy)
        if _contract_storage_fingerprint(policy, CostPolicy) != ingress_storage:
            _reject("source_changed")
        ingress_policy = owned_policy.canonical_bytes()
        reference = _decimal(
            reference_price, low_exp=-6, high_exp=9, max_adjusted=9,
            maximum=_MAX_QTY, positive=True,
        )
        filled = _decimal(
            filled_quantity, low_exp=-6, high_exp=9, max_adjusted=9,
            maximum=_MAX_QTY, positive=True,
        )
        cumulative = _decimal(
            cumulative_quantity, low_exp=-6, high_exp=9, max_adjusted=9,
            maximum=_MAX_QTY, positive=True,
        )
        if type(side) is not str or side not in ("buy", "sell") or filled > cumulative:
            _reject("numeric_invalid")
        p = _raw_payload(owned_policy, include_id=True)
        with localcontext(_fixed_context()):
            before = cumulative - filled
            sign = Decimal(1) if side == "buy" else Decimal(-1)
            price = reference + sign * reference * (p["half_spread_bps"] + p["slippage_bps"]) / Decimal(10_000)
            spread = reference * p["half_spread_bps"] * filled / Decimal(10_000)
            slippage = reference * p["slippage_bps"] * filled / Decimal(10_000)
            from mytradingalpha.contracts.orders import _fee_due

            fee = _fee_due(cumulative, p["commission_per_share"], p["order_minimum"]) - _fee_due(
                before, p["commission_per_share"], p["order_minimum"]
            )
        price = _decimal(
            price, low_exp=-16, high_exp=10, max_adjusted=9,
            maximum=Decimal("2000000000"), positive=True,
        )
        if side == "sell" and price <= _ZERO:
            _reject("numeric_invalid")
        spread = _decimal(
            spread, low_exp=-24, high_exp=24, max_adjusted=24,
            maximum=_MAX_MONEY, nonnegative=True,
        )
        slippage = _decimal(
            slippage, low_exp=-24, high_exp=24, max_adjusted=24,
            maximum=_MAX_MONEY, nonnegative=True,
        )
        fee = _decimal(
            fee, low_exp=-24, high_exp=24, max_adjusted=24,
            maximum=_MAX_MONEY, nonnegative=True,
        )
        breakdown = CostBreakdown(
            half_spread_bps=p["half_spread_bps"],
            slippage_bps=p["slippage_bps"],
            commission_per_share=p["commission_per_share"],
            order_minimum=p["order_minimum"],
            spread=spread,
            slippage=slippage,
            impact=None,
            impact_status="unavailable",
            adv=None,
            adv_status="unavailable",
            capacity=None,
            capacity_status="unavailable",
        )
        completion_policy = revalidate_cost_policy(policy)
        if (
            completion_policy.canonical_bytes() != ingress_policy
            or _contract_storage_fingerprint(policy, CostPolicy) != ingress_storage
        ):
            _reject("source_changed")
        return CostQuote(
            price=price,
            fee=fee,
            cost_breakdown=breakdown,
            policy_version=p["policy_version"],
            policy_hash=owned_policy.policy_hash,
        )


__all__ = ["CostModel", "CostPolicy", "CostQuote"]

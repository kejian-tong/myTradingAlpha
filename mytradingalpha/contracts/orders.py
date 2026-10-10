"""Shared, simulation-only order and fill wire contracts for BT-02."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from itertools import islice
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError, model_validator
from pydantic_core import PydanticSerializationError, core_schema

from mytradingalpha.contracts.redaction import validate_artifact_text
from mytradingalpha.contracts.signals import validate_sig03_identifier

_INTENT_DOMAIN = b"mytradingalpha:bt02:intent:v1\0"
_FILL_DOMAIN = b"mytradingalpha:bt02:fill:v1\0"
_INTENT_ID = re.compile(r"bt02-intent:[0-9a-f]{64}\Z", re.ASCII)
_FILL_ID = re.compile(r"bt02-fill:[0-9a-f]{64}\Z", re.ASCII)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_BT01_EVENT = re.compile(r"bt01-event:[0-9a-f]{64}\Z", re.ASCII)
_ENVELOPE = re.compile(r"signal-envelope:[0-9a-f]{64}\Z", re.ASCII)
_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.:-]{0,126}[A-Za-z0-9])?\Z", re.ASCII)


class OrderInputError(ValueError):
    """A fixed, redacted failure for malformed BT-02 input."""

    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str = "input_invalid") -> None:
        allowed = {
            "input_invalid",
            "resource_limit",
            "source_changed",
            "binding_mismatch",
            "intent_invalid",
            "policy_invalid",
            "outcome_invalid",
            "outcome_unavailable",
            "duplicate_intent",
            "duplicate_outcome",
            "session_unavailable",
            "numeric_invalid",
        }
        self.reason_code = (
            reason_code
            if type(reason_code) is str and reason_code in allowed
            else "input_invalid"
        )
        super().__init__(f"BT-02 input rejected ({self.reason_code})")

    def errors(self) -> list[dict[str, object]]:
        """Return structured diagnostics without reflecting submitted values."""

        return [{"type": "order_input_error", "loc": (), "msg": str(self), "input": None}]


def _reject(reason: str = "input_invalid") -> None:
    raise OrderInputError(reason) from None


def _fixed_context() -> Context:
    context = Context(
        prec=100,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
    )
    for signal in tuple(context.traps):
        context.traps[signal] = False
    context.traps[InvalidOperation] = True
    context.traps[DivisionByZero] = True
    context.traps[Overflow] = True
    context.clear_flags()
    return context


def _safe_string(value: object, *, max_bytes: int = 128, allow_empty: bool = False) -> str:
    if type(value) is not str:
        _reject()
    try:
        if not value and not allow_empty:
            _reject()
        if len(value) > max_bytes:
            _reject("resource_limit")
        raw = value.encode("utf-8", "strict")
        if len(raw) > max_bytes:
            _reject("resource_limit")
        if validate_sig03_identifier(value) != value or validate_artifact_text(value) != value:
            _reject()
        return value
    except OrderInputError:
        raise
    except Exception:
        _reject()


def _safe_token(value: object, pattern: re.Pattern[str]) -> str:
    checked = _safe_string(value)
    try:
        if not pattern.fullmatch(checked):
            _reject()
    except OrderInputError:
        raise
    except Exception:
        _reject()
    return checked


def _safe_id_token(value: object) -> str:
    return _safe_token(value, _TOKEN)


def _safe_utc(value: object) -> datetime:
    if type(value) is not datetime:
        _reject()
    zone = object.__getattribute__(value, "tzinfo")
    if type(zone) is not timezone:
        _reject()
    try:
        offset = timezone.utcoffset(zone, value)
    except Exception:
        _reject()
    if type(offset) is not timedelta or offset != timedelta(0):
        _reject()
    return value


def _safe_date(value: object) -> date:
    if type(value) is not date:
        _reject()
    return value


def _decimal_exponent(value: Decimal, low: int, high: int) -> int:
    # The finite candidate list prevents hostile exponents from reaching tuple,
    # formatting, normalization, or rational conversion operations.
    for exponent in range(low, high + 1):
        if value.same_quantum(Decimal((0, (1,), exponent))):
            return exponent
    _reject("numeric_invalid")
    raise AssertionError("unreachable")


def _decimal(
    value: object,
    *,
    low_exp: int,
    high_exp: int,
    max_adjusted: int,
    maximum: Decimal,
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal:
    if type(value) is not Decimal:
        _reject("input_invalid")
    try:
        if not value.is_finite():
            _reject("numeric_invalid")
        exponent = _decimal_exponent(value, low_exp, high_exp)
        if value.is_zero():
            if positive:
                _reject("numeric_invalid")
            return Decimal(0)
        adjusted = value.adjusted()
        if adjusted > max_adjusted or value.copy_abs() > maximum:
            _reject("numeric_invalid")
        if positive and value <= 0:
            _reject("numeric_invalid")
        if nonnegative and value < 0:
            _reject("numeric_invalid")
        sign, digits, stored_exponent = value.as_tuple()
        if stored_exponent != exponent or len(digits) > max_adjusted - exponent + 1:
            _reject("numeric_invalid")
        del sign
        return value
    except OrderInputError:
        raise
    except Exception:
        _reject("numeric_invalid")


def _decimal_wire(value: Decimal) -> str:
    """Serialize a previously bounded Decimal as normalized fixed notation."""

    sign, digits, exponent = value.as_tuple()
    if not any(digits):
        return "0"
    coefficient = "".join(str(item) for item in digits)
    if exponent >= 0:
        rendered = coefficient + ("0" * exponent)
    else:
        point = len(coefficient) + exponent
        if point > 0:
            rendered = coefficient[:point] + "." + coefficient[point:]
        else:
            rendered = "0." + ("0" * (-point)) + coefficient
        rendered = rendered.rstrip("0").rstrip(".")
    return ("-" if sign else "") + rendered


def _json_time(value: datetime) -> str:
    utc = value.astimezone(timezone.utc)
    return utc.isoformat(timespec="auto").replace("+00:00", "Z")


def _wire_value(value: object) -> object:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is Decimal:
        return _decimal_wire(value)
    if type(value) is datetime:
        return _json_time(value)
    if type(value) is date:
        return value.isoformat()
    if type(value) in (CostBreakdown, OrderIntent, Fill):
        return _wire_payload(value, include_id=True)
    _reject()
    raise AssertionError("unreachable")


def _canonical_json(payload: dict[str, object]) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", "strict")
    except Exception:
        _reject()
    if len(encoded) > 16_384:
        _reject("resource_limit")
    return encoded


def _raw_payload(model: _StrictContract, *, include_id: bool) -> dict[str, object]:
    names = tuple(type(model).model_fields)
    payload: dict[str, object] = {}
    own_id = "intent_id" if type(model) is OrderIntent else "fill_id"
    for name in names:
        if not include_id and name == own_id:
            continue
        payload[name] = object.__getattribute__(model, name)
    return payload


def _wire_payload(model: _StrictContract, *, include_id: bool) -> dict[str, object]:
    return {
        name: _wire_value(value)
        for name, value in _raw_payload(model, include_id=include_id).items()
    }


def _owned_mapping(value: object, fields: tuple[str, ...]) -> dict[str, object]:
    if type(value) is not dict or dict.__len__(value) > 64:
        _reject("input_invalid")
    try:
        entries = tuple(islice(dict.items(value), 65))
    except Exception:
        _reject("input_invalid")
    if len(entries) > 64:
        _reject("resource_limit")
    keys = tuple(key for key, _ in entries)
    if any(type(key) is not str for key in keys):
        _reject("input_invalid")
    allowed = set(fields)
    if any(key not in allowed for key in keys):
        _reject("input_invalid")
    return dict(entries)


def _schema_rejection() -> ValidationError:
    """Keep schema diagnostics independent of caller input and exceptions."""

    return ValidationError.from_exception_data(
        "BT-02",
        [{
            "type": "value_error",
            "loc": (),
            "input": None,
            "ctx": {"error": OrderInputError("input_invalid")},
        }],
    )


class _StrictContract(BaseModel):
    """Pydantic value surface with exact primitive Python ingress only."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        arbitrary_types_allowed=True,
        revalidate_instances="always",
    )

    @classmethod
    def __get_pydantic_core_schema__(cls, source: type[object], handler: Any) -> Any:
        schema = handler(source)
        if cls.__name__ == "_StrictContract":
            return schema

        def deny_json(_: object) -> object:
            raise _schema_rejection() from None

        def validate_fixed(value: object, inner: Any) -> object:
            with localcontext(_fixed_context()):
                try:
                    if type(value) is cls:
                        owned = _contract_payload(value, cls, "input_invalid")
                    else:
                        owned = _owned_mapping(value, tuple(cls.model_fields))
                    guarded = cls._guard_input(owned)
                    return inner(guarded)
                except Exception:
                    raise _schema_rejection() from None

        def serialize_checked(
            value: object, inner: Any, info: core_schema.SerializationInfo,
        ) -> object:
            try:
                if (
                    type(value) is not cls
                    or info.include is not None
                    or info.exclude is not None
                    or info.context is not None
                ):
                    _reject("input_invalid")
                payload = _contract_payload(value, cls, "input_invalid")
                owned = cls.model_validate(payload)
                return inner(owned)
            except Exception:
                raise PydanticSerializationError("BT-02 serialization rejected") from None

        python_schema = core_schema.no_info_wrap_validator_function(validate_fixed, schema)

        return core_schema.json_or_python_schema(
            json_schema=core_schema.no_info_plain_validator_function(deny_json),
            python_schema=python_schema,
            serialization=core_schema.wrap_serializer_function_ser_schema(
                serialize_checked,
                info_arg=True,
                schema=schema,
            ),
        )

    @model_validator(mode="before")
    @classmethod
    def _strict_input(cls, value: object) -> object:
        if type(value) is cls:
            return cls._guard_input(_contract_payload(value, cls, "input_invalid"))
        if type(value) is not dict:
            _reject("input_invalid")
        return cls._guard_input(_owned_mapping(value, tuple(cls.model_fields)))

    @classmethod
    def _guard_input(cls, value: dict[str, object]) -> dict[str, object]:
        return value

    def __init__(self, **data: Any) -> None:
        try:
            owned = _owned_mapping(data, tuple(type(self).model_fields))
            guarded = type(self)._guard_input(owned)
            super().__init__(**guarded)
        except OrderInputError:
            raise
        except Exception:
            _reject("input_invalid")

    @classmethod
    def model_validate(cls, obj: object, *args: object, **kwargs: object) -> Any:
        if args or kwargs:
            _reject("input_invalid")
        if type(obj) is cls:
            obj = _contract_payload(obj, cls, "input_invalid")
        return cls(**cls._guard_input(_owned_mapping(obj, tuple(cls.model_fields))))

    @classmethod
    def model_validate_json(cls, *_: object, **__: object) -> Any:
        _reject("input_invalid")

    @classmethod
    def model_validate_strings(cls, *_: object, **__: object) -> Any:
        _reject("input_invalid")

    @staticmethod
    def _dump_options(options: dict[str, object]) -> dict[str, object]:
        """Own bounded scalar options; reject caller-controlled serializer hooks."""

        optional_bools = ("by_alias", "polymorphic_serialization")
        bools = (
            "exclude_unset", "exclude_defaults", "exclude_none",
            "exclude_computed_fields", "round_trip", "serialize_as_any",
        )
        none_only = ("include", "exclude", "context", "fallback")
        owned = _owned_mapping(options, ("mode", "warnings", *optional_bools, *bools, *none_only))
        for name, value in owned.items():
            if name in none_only:
                if value is not None:
                    _reject("input_invalid")
            elif name == "mode":
                if type(value) is not str or value not in ("python", "json"):
                    _reject("input_invalid")
            elif name == "warnings":
                if type(value) is not bool and (
                    type(value) is not str or value not in ("none", "warn", "error")
                ):
                    _reject("input_invalid")
            elif type(value) is not bool and not (name in optional_bools and value is None):
                _reject("input_invalid")
        return owned

    def model_dump(self, *args: object, **kwargs: object) -> dict[str, object]:
        if args:
            _reject("input_invalid")
        options = _StrictContract._dump_options(kwargs)
        payload = _contract_payload(self, type(self), "input_invalid")
        try:
            checked = type(self).model_validate(payload)
            return BaseModel.model_dump(checked, **options)  # type: ignore[return-value]
        except OrderInputError:
            raise
        except Exception:
            _reject("input_invalid")

    def model_dump_json(self, *args: object, **kwargs: object) -> str:
        if args or kwargs:
            _reject("input_invalid")
        payload = _contract_payload(self, type(self), "input_invalid")
        try:
            checked = type(self).model_validate(payload)
            return _canonical_json(_wire_payload(checked, include_id=True)).decode("utf-8")
        except OrderInputError:
            raise
        except Exception:
            _reject("input_invalid")


def _validate_common_strings(payload: dict[str, object], names: tuple[str, ...]) -> None:
    for name in names:
        _safe_string(payload[name])


def _validate_intent_payload(payload: dict[str, object], *, check_id: bool) -> None:
    string_fields = (
        "schema_version",
        "run_id",
        "instrument_id",
        "calendar_id",
        "variant_id",
        "decision_event_id",
        "envelope_id",
        "source_fingerprint",
        "currency",
        "side",
        "order_type",
        "time_in_force",
        "plan_id",
        "risk_decision_id",
        "risk_policy_version",
        "outcome_source",
        "execution_authority",
    )
    _validate_common_strings(payload, string_fields)
    for name in (
        "schema_version", "run_id", "instrument_id", "calendar_id", "variant_id",
        "currency", "side", "order_type", "time_in_force", "plan_id",
        "risk_decision_id", "risk_policy_version", "outcome_source",
        "execution_authority",
    ):
        _safe_id_token(payload[name])
    if payload["schema_version"] != "v1" or payload["currency"] != "USD":
        _reject("intent_invalid")
    if payload["side"] not in ("buy", "sell"):
        _reject("intent_invalid")
    if payload["order_type"] not in ("market", "limit"):
        _reject("intent_invalid")
    if payload["time_in_force"] not in ("day", "gtc", "ioc", "fok"):
        _reject("intent_invalid")
    if payload["execution_authority"] != "simulation_only":
        _reject("intent_invalid")
    _safe_token(payload["decision_event_id"], _BT01_EVENT)
    _safe_token(payload["envelope_id"], _ENVELOPE)
    _safe_token(payload["source_fingerprint"], _SHA256)
    quantity = _decimal(
        payload["quantity"], low_exp=-6, high_exp=9, max_adjusted=9,
        maximum=Decimal("1000000000"), positive=True,
    )
    limit = payload["limit_price"]
    if payload["order_type"] == "market":
        if limit is not None:
            _reject("intent_invalid")
    else:
        _decimal(
            limit, low_exp=-6, high_exp=9, max_adjusted=9,
            maximum=Decimal("1000000000"), positive=True,
        )
    first_date = _safe_date(payload["first_session_date"])
    del first_date
    decision_time = _safe_utc(payload["decision_time"])
    created_at = _safe_utc(payload["created_at"])
    earliest = _safe_utc(payload["earliest_submit_time"])
    expires = _safe_utc(payload["expires_at"])
    if not decision_time <= created_at < earliest <= expires:
        _reject("intent_invalid")
    revision = payload["outcome_revision"]
    if type(revision) is not int or not 0 <= revision <= 2**31 - 1:
        _reject("intent_invalid")
    if check_id:
        supplied = _safe_token(payload["intent_id"], _INTENT_ID)
        expected = "bt02-intent:" + hashlib.sha256(
            _INTENT_DOMAIN + _canonical_json(_wire_mapping(payload, omit="intent_id"))
        ).hexdigest()
        if supplied != expected:
            _reject("intent_invalid")
    del quantity


def _wire_mapping(payload: dict[str, object], *, omit: str | None = None) -> dict[str, object]:
    return {
        key: _wire_value(value)
        for key, value in payload.items()
        if key != omit
    }


def _fee_due(cumulative: Decimal, commission: Decimal, minimum: Decimal) -> Decimal:
    if cumulative == 0:
        return Decimal("0.00")
    with localcontext(_fixed_context()):
        raw = max(minimum, commission * cumulative)
        return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_cost_breakdown_payload(p: dict[str, object]) -> None:
    for status in ("impact_status", "adv_status", "capacity_status"):
        _safe_string(p[status])
    for name in ("impact", "adv", "capacity"):
        if p[name] is not None:
            _reject("policy_invalid")
        if p[f"{name}_status"] != "unavailable":
            _reject("policy_invalid")
    _decimal(p["half_spread_bps"], low_exp=-6, high_exp=6, max_adjusted=4, maximum=Decimal("9999"), nonnegative=True)
    _decimal(p["slippage_bps"], low_exp=-6, high_exp=6, max_adjusted=4, maximum=Decimal("9999"), nonnegative=True)
    with localcontext(_fixed_context()):
        total_bps = p["half_spread_bps"] + p["slippage_bps"]
    if total_bps >= Decimal("10000"):
        _reject("policy_invalid")
    _decimal(p["commission_per_share"], low_exp=-6, high_exp=6, max_adjusted=6, maximum=Decimal("1000000"), nonnegative=True)
    _decimal(p["order_minimum"], low_exp=-6, high_exp=6, max_adjusted=6, maximum=Decimal("1000000"), nonnegative=True)
    _decimal(p["spread"], low_exp=-24, high_exp=24, max_adjusted=24, maximum=Decimal("1E24"), nonnegative=True)
    _decimal(p["slippage"], low_exp=-24, high_exp=24, max_adjusted=24, maximum=Decimal("1E24"), nonnegative=True)


def _require_complete_payload(payload: dict[str, object], model_type: type[_StrictContract], reason: str) -> None:
    if set(payload) != set(model_type.model_fields):
        _reject(reason)


class CostBreakdown(_StrictContract):
    """Fixed-shape explicit friction attribution for an actual fill."""

    half_spread_bps: Decimal
    slippage_bps: Decimal
    commission_per_share: Decimal
    order_minimum: Decimal
    spread: Decimal
    slippage: Decimal
    impact: Decimal | None
    impact_status: StrictStr
    adv: Decimal | None
    adv_status: StrictStr
    capacity: Decimal | None
    capacity_status: StrictStr

    @classmethod
    def _guard_input(cls, value: dict[str, object]) -> dict[str, object]:
        _require_complete_payload(value, cls, "policy_invalid")
        _validate_cost_breakdown_payload(value)
        return value

    @model_validator(mode="after")
    def validate_breakdown(self) -> CostBreakdown:
        p = _raw_payload(self, include_id=True)
        _validate_cost_breakdown_payload(p)
        return self


class OrderIntent(_StrictContract):
    """Immutable shared simulation-only precommitted order intent."""

    schema_version: StrictStr
    intent_id: StrictStr
    run_id: StrictStr
    instrument_id: StrictStr
    calendar_id: StrictStr
    variant_id: StrictStr
    decision_event_id: StrictStr
    envelope_id: StrictStr
    source_fingerprint: StrictStr
    currency: StrictStr
    side: Literal["buy", "sell"]
    quantity: Decimal
    order_type: Literal["market", "limit"]
    limit_price: Decimal | None
    first_session_date: date
    decision_time: datetime
    created_at: datetime
    earliest_submit_time: datetime
    expires_at: datetime
    time_in_force: Literal["day", "gtc", "ioc", "fok"]
    plan_id: StrictStr
    risk_decision_id: StrictStr
    risk_policy_version: StrictStr
    outcome_source: StrictStr
    outcome_revision: StrictInt
    execution_authority: StrictStr

    @classmethod
    def _guard_input(cls, value: dict[str, object]) -> dict[str, object]:
        _require_complete_payload(value, cls, "intent_invalid")
        _validate_intent_payload(value, check_id=True)
        return value

    @model_validator(mode="after")
    def validate_intent(self) -> OrderIntent:
        _validate_intent_payload(_raw_payload(self, include_id=True), check_id=True)
        return self

    def canonical_bytes(self) -> bytes:
        owned = revalidate_order_intent(self)
        return _canonical_json(_wire_payload(owned, include_id=True))

    @property
    def intent_hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_bytes()).hexdigest()


def build_order_intent(**fields: object) -> OrderIntent:
    names = tuple(OrderIntent.model_fields)
    payload = _owned_mapping(fields, tuple(name for name in names if name != "intent_id"))
    if "intent_id" in payload:
        _reject("intent_invalid")
    if set(payload) != set(names) - {"intent_id"}:
        _reject("intent_invalid")
    _validate_intent_payload({**payload, "intent_id": "bt02-intent:" + ("0" * 64)}, check_id=False)
    identity = "bt02-intent:" + hashlib.sha256(
        _INTENT_DOMAIN + _canonical_json(_wire_mapping(payload))
    ).hexdigest()
    return OrderIntent(**{**payload, "intent_id": identity})


def _validate_fill_payload(payload: dict[str, object], *, check_id: bool) -> None:
    string_fields = (
        "schema_version", "fill_id", "intent_id", "intent_hash", "run_id",
        "instrument_id", "calendar_id", "variant_id", "decision_event_id",
        "envelope_id", "source_fingerprint", "currency", "side",
        "cost_policy_version", "cost_policy_hash", "fee_policy_id", "bar_id",
        "manifest_id", "outcome_source", "source_checksum", "outcome_hash",
        "execution_authority", "liquidity",
    )
    _validate_common_strings(payload, tuple(name for name in string_fields if name != "fill_id"))
    for name in (
        "schema_version", "run_id", "instrument_id", "calendar_id", "variant_id",
        "currency", "side", "cost_policy_version", "fee_policy_id", "bar_id",
        "manifest_id", "outcome_source", "execution_authority", "liquidity",
    ):
        _safe_id_token(payload[name])
    if payload["schema_version"] != "v1" or payload["currency"] != "USD":
        _reject("input_invalid")
    if payload["side"] not in ("buy", "sell"):
        _reject("input_invalid")
    if payload["execution_authority"] != "simulation_only" or payload["liquidity"] != "simulated":
        _reject("input_invalid")
    _safe_token(payload["intent_id"], _INTENT_ID)
    _safe_token(payload["intent_hash"], _SHA256)
    _safe_token(payload["decision_event_id"], _BT01_EVENT)
    _safe_token(payload["envelope_id"], _ENVELOPE)
    _safe_token(payload["source_fingerprint"], _SHA256)
    _safe_token(payload["cost_policy_hash"], _SHA256)
    _safe_token(payload["source_checksum"], _SHA256)
    _safe_token(payload["outcome_hash"], _SHA256)
    quantity = _decimal(payload["quantity"], low_exp=-6, high_exp=9, max_adjusted=9, maximum=Decimal("1E9"), positive=True)
    before = _decimal(payload["cumulative_quantity_before"], low_exp=-6, high_exp=9, max_adjusted=9, maximum=Decimal("1E9"), nonnegative=True)
    after = _decimal(payload["cumulative_quantity_after"], low_exp=-6, high_exp=9, max_adjusted=9, maximum=Decimal("1E9"), positive=True)
    price = _decimal(payload["price"], low_exp=-16, high_exp=10, max_adjusted=9, maximum=Decimal("2E9"), positive=True)
    reference = _decimal(payload["reference_price"], low_exp=-6, high_exp=9, max_adjusted=9, maximum=Decimal("1E9"), positive=True)
    fee = _decimal(payload["fee"], low_exp=-24, high_exp=24, max_adjusted=24, maximum=Decimal("1E24"), nonnegative=True)
    with localcontext(_fixed_context()):
        cumulative_delta = after - before
    if cumulative_delta != quantity or after > Decimal("1E9"):
        _reject("input_invalid")
    if type(payload["outcome_revision"]) is not int or not 0 <= payload["outcome_revision"] <= 2**31 - 1:
        _reject("outcome_invalid")
    session = _safe_date(payload["session_date"])
    del session
    fill_time = _safe_utc(payload["fill_time"])
    received_at = _safe_utc(payload["received_at"])
    if received_at <= fill_time:
        _reject("outcome_invalid")
    cost = payload["cost_breakdown"]
    if type(cost) is dict:
        cost = CostBreakdown.model_validate(cost)
    if type(cost) is not CostBreakdown:
        _reject("input_invalid")
    cost_payload = _raw_payload(cost, include_id=True)
    for name in ("impact", "adv", "capacity"):
        if cost_payload[name] is not None or cost_payload[f"{name}_status"] != "unavailable":
            _reject("policy_invalid")
    with localcontext(_fixed_context()):
        bps = cost.half_spread_bps + cost.slippage_bps
        direction = Decimal(1) if payload["side"] == "buy" else Decimal(-1)
        expected_price = reference + direction * reference * bps / Decimal(10_000)
        expected_spread = reference * cost.half_spread_bps * quantity / Decimal(10_000)
        expected_slippage = reference * cost.slippage_bps * quantity / Decimal(10_000)
        expected_fee = _fee_due(after, cost.commission_per_share, cost.order_minimum) - _fee_due(
            before, cost.commission_per_share, cost.order_minimum
        )
    _decimal(expected_price, low_exp=-16, high_exp=10, max_adjusted=9, maximum=Decimal("2E9"), positive=True)
    _decimal(expected_spread, low_exp=-24, high_exp=24, max_adjusted=24, maximum=Decimal("1E24"), nonnegative=True)
    _decimal(expected_slippage, low_exp=-24, high_exp=24, max_adjusted=24, maximum=Decimal("1E24"), nonnegative=True)
    if price != expected_price or cost.spread != expected_spread or cost.slippage != expected_slippage or fee != expected_fee:
        _reject("input_invalid")
    _safe_token(payload["fill_id"], _FILL_ID) if check_id else None
    if check_id:
        expected = "bt02-fill:" + hashlib.sha256(
            _FILL_DOMAIN + _canonical_json(_wire_mapping(payload, omit="fill_id"))
        ).hexdigest()
        if payload["fill_id"] != expected:
            _reject("input_invalid")
    del quantity


class Fill(_StrictContract):
    """Immutable simulation fill; never a broker or accounting ledger event."""

    schema_version: StrictStr
    fill_id: StrictStr
    intent_id: StrictStr
    intent_hash: StrictStr
    run_id: StrictStr
    instrument_id: StrictStr
    calendar_id: StrictStr
    variant_id: StrictStr
    decision_event_id: StrictStr
    envelope_id: StrictStr
    source_fingerprint: StrictStr
    currency: StrictStr
    side: Literal["buy", "sell"]
    quantity: Decimal
    cumulative_quantity_before: Decimal
    cumulative_quantity_after: Decimal
    price: Decimal
    reference_price: Decimal
    fee: Decimal
    cost_breakdown: CostBreakdown
    cost_policy_version: StrictStr
    cost_policy_hash: StrictStr
    fee_policy_id: StrictStr
    bar_id: StrictStr
    manifest_id: StrictStr
    outcome_source: StrictStr
    outcome_revision: StrictInt
    source_checksum: StrictStr
    outcome_hash: StrictStr
    session_date: date
    fill_time: datetime
    received_at: datetime
    execution_authority: StrictStr
    liquidity: StrictStr

    @classmethod
    def _guard_input(cls, value: dict[str, object]) -> dict[str, object]:
        _require_complete_payload(value, cls, "input_invalid")
        payload = dict(value)
        nested = payload["cost_breakdown"]
        if type(nested) is dict:
            payload["cost_breakdown"] = CostBreakdown.model_validate(nested)
        elif type(nested) is CostBreakdown:
            nested_payload = _contract_payload(nested, CostBreakdown, "input_invalid")
            payload["cost_breakdown"] = CostBreakdown.model_validate(nested_payload)
        else:
            _reject("input_invalid")
        _validate_fill_payload(payload, check_id=True)
        return payload

    @model_validator(mode="after")
    def validate_fill(self) -> Fill:
        _validate_fill_payload(_raw_payload(self, include_id=True), check_id=True)
        return self

    def canonical_bytes(self) -> bytes:
        owned = revalidate_fill(self)
        return _canonical_json(_wire_payload(owned, include_id=True))


def build_fill(**fields: object) -> Fill:
    names = tuple(Fill.model_fields)
    payload = _owned_mapping(fields, tuple(name for name in names if name != "fill_id"))
    if "fill_id" in payload:
        _reject("input_invalid")
    if set(payload) != set(names) - {"fill_id"}:
        _reject("input_invalid")
    if type(payload.get("cost_breakdown")) is dict:
        payload["cost_breakdown"] = CostBreakdown.model_validate(payload["cost_breakdown"])
    elif type(payload.get("cost_breakdown")) is CostBreakdown:
        payload["cost_breakdown"] = CostBreakdown.model_validate(
            _contract_payload(payload["cost_breakdown"], CostBreakdown, "input_invalid")
        )
    _validate_fill_payload({**payload, "fill_id": "bt02-fill:" + ("0" * 64)}, check_id=False)
    wire = _wire_mapping(payload)
    fill_id = "bt02-fill:" + hashlib.sha256(_FILL_DOMAIN + _canonical_json(wire)).hexdigest()
    return Fill(**{**payload, "fill_id": fill_id})


def _contract_snapshot(
    value: object,
    model_type: type[_StrictContract],
    reason: str,
) -> tuple[dict[str, object], tuple[str, ...]]:
    """Own bounded raw fields and metadata before inspecting their contents."""

    if type(value) is not model_type:
        _reject(reason)
    try:
        storage = object.__getattribute__(value, "__dict__")
        extras = object.__getattribute__(value, "__pydantic_extra__")
        private = object.__getattribute__(value, "__pydantic_private__")
        fields_set = object.__getattribute__(value, "__pydantic_fields_set__")
    except Exception:
        _reject(reason)
    if (
        type(storage) is not dict
        or extras is not None
        or private is not None
        or type(fields_set) is not set
    ):
        _reject(reason)
    try:
        entries = tuple(islice(dict.items(storage), 65))
        metadata = tuple(islice(set.__iter__(fields_set), 65))
    except Exception:
        _reject(reason)
    if len(entries) > 64 or len(metadata) > 64:
        _reject("resource_limit")
    names = tuple(model_type.model_fields)
    keys = tuple(key for key, _ in entries)
    if len(keys) != len(names):
        _reject(reason)
    if any(type(key) is not str for key in keys):
        _reject(reason)
    if set(keys) != set(names):
        _reject(reason)
    if any(type(item) is not str for item in metadata) or set(metadata) != set(names):
        _reject(reason)
    return dict(entries), metadata


def _contract_payload(value: object, model_type: type[_StrictContract], reason: str) -> dict[str, object]:
    return _contract_snapshot(value, model_type, reason)[0]


def _typed_storage_value(
    value: object,
    *,
    cost_snapshot: tuple[dict[str, object], tuple[str, ...]] | None = None,
) -> object:
    value_type = type(value)
    if value is None or value_type in (bool, int, str):
        return value
    if value_type is Decimal:
        sign, digits, exponent = value.as_tuple()
        return ("Decimal", sign, tuple(digits), exponent)
    if value_type is datetime:
        checked = _safe_utc(value)
        return (
            "datetime",
            checked.year,
            checked.month,
            checked.day,
            checked.hour,
            checked.minute,
            checked.second,
            checked.microsecond,
        )
    if value_type is date:
        checked_date = _safe_date(value)
        return ("date", checked_date.year, checked_date.month, checked_date.day)
    if value_type is CostBreakdown:
        nested, metadata = (
            _contract_snapshot(value, CostBreakdown, "input_invalid")
            if cost_snapshot is None else cost_snapshot
        )
        CostBreakdown._guard_input(nested)
        return (
            "CostBreakdown",
            tuple((name, _typed_storage_value(nested[name])) for name in CostBreakdown.model_fields),
            tuple(sorted(metadata)),
        )
    _reject("input_invalid")
    raise AssertionError("unreachable")


def _contract_storage_fingerprint(
    value: object,
    model_type: type[_StrictContract],
    *,
    reason: str = "input_invalid",
) -> tuple[object, ...]:
    """Capture exact typed fields independently of normalized wire bytes."""

    payload, metadata = _contract_snapshot(value, model_type, "input_invalid")
    cost_snapshot = None
    if model_type is Fill:
        cost_snapshot = _contract_snapshot(payload["cost_breakdown"], CostBreakdown, "input_invalid")
    try:
        validation_payload = payload
        if cost_snapshot is not None:
            validation_payload = {
                **payload,
                "cost_breakdown": CostBreakdown.model_validate(cost_snapshot[0]),
            }
        model_type._guard_input(validation_payload)
    except OrderInputError:
        _reject(reason)
    except Exception:
        _reject(reason)
    metadata_snapshot = tuple(sorted(metadata))
    return (
        model_type.__name__,
        tuple(
            (name, _typed_storage_value(
                payload[name],
                cost_snapshot=cost_snapshot if name == "cost_breakdown" else None,
            ))
            for name in model_type.model_fields
        ),
        metadata_snapshot,
    )


def revalidate_order_intent(value: object, *, reason: str = "intent_invalid") -> OrderIntent:
    payload = _contract_payload(value, OrderIntent, reason)
    try:
        return OrderIntent.model_validate(payload)
    except OrderInputError:
        _reject(reason)
    except Exception:
        _reject(reason)


def revalidate_fill(value: object, *, reason: str = "input_invalid") -> Fill:
    payload = _contract_payload(value, Fill, reason)
    try:
        return Fill.model_validate(payload)
    except OrderInputError:
        _reject(reason)
    except Exception:
        _reject(reason)


__all__ = [
    "CostBreakdown",
    "Fill",
    "OrderInputError",
    "OrderIntent",
    "build_fill",
    "build_order_intent",
]

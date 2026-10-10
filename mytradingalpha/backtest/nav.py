"""Pure retrospective NAV valuation over sealed BT-02 marks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from mytradingalpha.backtest.clock import (
    SessionBinding,
    _capture_root,
    _CaptureBudget,
    _storage_bytes,
)
from mytradingalpha.backtest.fills import OutcomeEvidence
from mytradingalpha.data.bars import AdjustmentBasis, BarFinality
from mytradingalpha.data.bundle import BundleReplayPolicy

from .ledger import (
    _MAX_EVENT_BYTES,
    _MAX_INSTRUMENTS,
    LedgerBalance,
    _binding_capture,
    _binding_refresh,
    _canonical_json,
    _capture_call,
    _clone_balance,
    _contract_call,
    _decimal_checked,
    _exact_decimal,
    _outcome_capture,
    _outcome_refresh,
    _reject,
    _safe_date,
    _safe_identifier,
    _safe_saved,
    _safe_utc,
    _saved_bytes,
    _verify_balance,
)

_NAV_DOMAIN = b"mytradingalpha:bt03:nav-policy:v1\0"
_MARK_DOMAIN = b"mytradingalpha:bt03:eligible-mark:v1\0"
_MAX_MARKS = 256
_NUMERIC_POLICY_VERSION = "bt03-decimal-v1"
_FORMULA_VERSION = "bt03-nav-v1"
_MISSING = object()


def _currency(value: object) -> str:
    return _safe_identifier(value)


def _strict_model(value: object, model_type: type[object]) -> None:
    if type(value) is not model_type:
        _reject()


def _capture_mark(value: object) -> tuple[tuple[object, ...], bytes]:
    return _capture_call(lambda: _capture_mark_native(value), "source_changed")


def _capture_mark_native(value: object) -> tuple[tuple[object, ...], bytes]:
    if type(value) is not EligibleMark:
        _reject()
    _saved_bytes(object.__getattribute__(value, "_seal"), 32)
    binding = object.__getattribute__(value, "_binding")
    binding_seals = object.__getattribute__(value, "_binding_seals")
    _safe_saved(binding_seals)
    outcome = object.__getattribute__(value, "_outcome")
    outcome_seals = object.__getattribute__(value, "_outcome_seals")
    _safe_saved(outcome_seals)
    prepared = _binding_refresh(binding, binding_seals)
    outcome_state = _outcome_refresh(outcome, outcome_seals)
    witness = _canonical_json(
        [
            hashlib.sha256(prepared[5]).hexdigest(),
            prepared[6],
            hashlib.sha256(prepared[7]).hexdigest(),
            hashlib.sha256(outcome_state[4]).hexdigest(),
            hashlib.sha256(outcome_state[6]).hexdigest(),
            outcome_state[5],
        ]
    )
    saved = object.__getattribute__(value, "_seal")
    current = hashlib.sha256(_MARK_DOMAIN + witness).digest()
    if type(saved) is not bytes or current != saved:
        _reject("source_changed")
    return (prepared, outcome_state), witness


class EligibleMark:
    """Owned full-source mark candidate; eligibility is decided by NAV policy."""

    __slots__ = ("_binding", "_binding_seals", "_outcome", "_outcome_seals", "_seal")

    def __init__(
        self,
        *,
        binding: object = _MISSING,
        outcome: object = _MISSING,
        **unknown: object,
    ) -> None:
        if unknown:
            _reject("input_invalid", TypeError)
        binding_copy, binding_seals = _binding_capture(binding)
        outcome_copy, outcome_seals = _outcome_capture(outcome)
        object.__setattr__(self, "_binding", binding_copy)
        object.__setattr__(self, "_binding_seals", binding_seals)
        object.__setattr__(self, "_outcome", outcome_copy)
        object.__setattr__(self, "_outcome_seals", outcome_seals)
        witness = _canonical_json(
            [
                hashlib.sha256(binding_seals[0]).hexdigest(),
                binding_seals[1],
                hashlib.sha256(binding_seals[2]).hexdigest(),
                hashlib.sha256(outcome_seals[0]).hexdigest(),
                hashlib.sha256(outcome_seals[1]).hexdigest(),
                outcome_seals[2],
            ]
        )
        _binding_refresh(binding, binding_seals)
        _outcome_refresh(outcome, outcome_seals)
        object.__setattr__(self, "_seal", hashlib.sha256(_MARK_DOMAIN + witness).digest())

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("EligibleMark is immutable")

    def __repr__(self) -> str:
        return "EligibleMark(<sealed>)"

    @property
    def binding(self) -> SessionBinding:
        _capture_mark(self)
        return _binding_capture(object.__getattribute__(self, "_binding"))[0]

    @property
    def outcome(self) -> OutcomeEvidence:
        _capture_mark(self)
        return _outcome_capture(object.__getattribute__(self, "_outcome"))[0]


class AccountingPolicy:
    """Explicit target, currency and source cutoffs for one retrospective NAV."""

    __slots__ = (
        "_binding", "_binding_seals", "_session_date", "_valuation_cutoff", "_archive_cutoff",
        "_currency", "_mark_source", "_mark_revision", "_canonical", "_seal",
    )

    def __init__(
        self,
        *,
        binding: object = _MISSING,
        session_date: object = _MISSING,
        valuation_cutoff: object = _MISSING,
        archive_cutoff: object = _MISSING,
        currency: object = _MISSING,
        mark_source: object = _MISSING,
        mark_revision: object = _MISSING,
        **unknown: object,
    ) -> None:
        if unknown:
            _reject("input_invalid", TypeError)
        binding_copy, binding_seals = _binding_capture(binding)
        target = _safe_date(session_date)
        valuation = _safe_utc(valuation_cutoff)
        archive = _safe_utc(archive_cutoff)
        ccy = _currency(currency)
        source = _safe_identifier(mark_source)
        if type(mark_revision) is not int or not 0 <= mark_revision <= (1 << 31) - 1:
            _reject()
        object.__setattr__(self, "_binding", binding_copy)
        object.__setattr__(self, "_binding_seals", binding_seals)
        object.__setattr__(self, "_session_date", target)
        object.__setattr__(self, "_valuation_cutoff", valuation)
        object.__setattr__(self, "_archive_cutoff", archive)
        object.__setattr__(self, "_currency", ccy)
        object.__setattr__(self, "_mark_source", source)
        object.__setattr__(self, "_mark_revision", mark_revision)
        canonical = _canonical_json(
            {
                "archive_cutoff": archive.isoformat(timespec="auto").replace("+00:00", "Z"),
                "binding_source": binding_seals[0].decode("utf-8"),
                "binding_storage_seal": hashlib.sha256(binding_seals[2]).hexdigest(),
                "currency": ccy,
                "formula_version": _FORMULA_VERSION,
                "mark_revision": mark_revision,
                "mark_source": source,
                "numeric_policy_version": _NUMERIC_POLICY_VERSION,
                "schema_version": "v1",
                "session_date": target.isoformat(),
                "valuation_cutoff": valuation.isoformat(timespec="auto").replace("+00:00", "Z"),
            }
        )
        object.__setattr__(self, "_canonical", canonical)
        object.__setattr__(self, "_seal", hashlib.sha256(_NAV_DOMAIN + canonical).digest())

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("AccountingPolicy is immutable")

    def __repr__(self) -> str:
        return "AccountingPolicy(<sealed>)"

    @property
    def binding(self) -> SessionBinding:
        _refresh_policy(self)
        return _binding_capture(object.__getattribute__(self, "_binding"))[0]

    @property
    def session_date(self) -> date:
        _refresh_policy(self)
        return object.__getattribute__(self, "_session_date")

    @property
    def valuation_cutoff(self) -> datetime:
        _refresh_policy(self)
        return object.__getattribute__(self, "_valuation_cutoff")

    @property
    def archive_cutoff(self) -> datetime:
        _refresh_policy(self)
        return object.__getattribute__(self, "_archive_cutoff")

    @property
    def currency(self) -> str:
        _refresh_policy(self)
        return object.__getattribute__(self, "_currency")

    @property
    def mark_source(self) -> str:
        _refresh_policy(self)
        return object.__getattribute__(self, "_mark_source")

    @property
    def mark_revision(self) -> int:
        _refresh_policy(self)
        return object.__getattribute__(self, "_mark_revision")

    def canonical_bytes(self) -> bytes:
        return _refresh_policy(self)


def _refresh_policy(policy: object, captured: list[object] | None = None) -> bytes:
    return _capture_call(lambda: _refresh_policy_native(policy, captured), "source_changed")


def _refresh_policy_native(policy: object, captured: list[object] | None) -> bytes:
    if type(policy) is not AccountingPolicy:
        _reject()
    _saved_bytes(object.__getattribute__(policy, "_canonical"), _MAX_EVENT_BYTES)
    _saved_bytes(object.__getattribute__(policy, "_seal"), 32)
    binding = object.__getattribute__(policy, "_binding")
    seals = object.__getattribute__(policy, "_binding_seals")
    _safe_saved(seals)
    prepared = _binding_refresh(binding, seals)
    target = _safe_date(object.__getattribute__(policy, "_session_date"))
    valuation = _safe_utc(object.__getattribute__(policy, "_valuation_cutoff"))
    archive = _safe_utc(object.__getattribute__(policy, "_archive_cutoff"))
    currency = _currency(object.__getattribute__(policy, "_currency"))
    source = _safe_identifier(object.__getattribute__(policy, "_mark_source"))
    revision = object.__getattribute__(policy, "_mark_revision")
    if type(revision) is not int or not 0 <= revision <= (1 << 31) - 1:
        _reject("source_changed")
    canonical = _canonical_json(
        {
            "archive_cutoff": archive.isoformat(timespec="auto").replace("+00:00", "Z"),
            "binding_source": seals[0].decode("utf-8"),
            "binding_storage_seal": hashlib.sha256(seals[2]).hexdigest(),
            "currency": currency,
            "formula_version": _FORMULA_VERSION,
            "mark_revision": revision,
            "mark_source": source,
            "numeric_policy_version": _NUMERIC_POLICY_VERSION,
            "schema_version": "v1",
            "session_date": target.isoformat(),
            "valuation_cutoff": valuation.isoformat(timespec="auto").replace("+00:00", "Z"),
        }
    )
    saved = object.__getattribute__(policy, "_canonical")
    seal = object.__getattribute__(policy, "_seal")
    if type(saved) is not bytes or type(seal) is not bytes or canonical != saved or hashlib.sha256(_NAV_DOMAIN + canonical).digest() != seal:
        _reject("source_changed")
    if captured is not None:
        captured.extend((prepared, target, valuation, archive, currency, source, revision))
    return canonical


@dataclass(frozen=True, slots=True)
class NAVResult:
    status: str
    value: Decimal | None
    reason_code: str | None
    run_valid: bool
    formula_version: str = _FORMULA_VERSION
    numeric_policy_version: str = _NUMERIC_POLICY_VERSION

    @property
    def reason(self) -> str | None:
        return self.reason_code


def _unavailable(reason: str) -> NAVResult:
    return NAVResult("unavailable", None, reason, False)


def _available(value: Decimal) -> NAVResult:
    return NAVResult("available", value, None, True)


def _instrument_from_binding(prepared: tuple[object, ...]) -> tuple[str, str, object]:
    context, bundle, envelope = prepared[:3]
    quant = object.__getattribute__(envelope, "quant")
    instrument_id = _safe_identifier(object.__getattribute__(quant, "instrument_id"))
    instruments = object.__getattribute__(bundle, "instruments")
    matches = tuple(item for item in instruments if object.__getattribute__(item, "instrument_id") == instrument_id)
    if len(matches) != 1:
        _reject("binding_mismatch")
    return (
        _safe_identifier(object.__getattribute__(context, "run_id")),
        _safe_identifier(object.__getattribute__(bundle.calendar, "calendar_id")),
        matches[0],
    )


def _binding_run_group(prepared: tuple[object, ...]) -> tuple[bytes, bytes]:
    """Bind a mark to the run and full bundle while allowing per-instrument envelopes."""

    context, bundle = prepared[0], prepared[1]
    context_wire = _contract_call(lambda: context.model_dump(mode="json"), "source_changed")
    bundle_wire = _contract_call(lambda: bundle.model_dump(mode="json"), "source_changed")
    canonical = _canonical_json({"bundle": bundle_wire, "context": context_wire})
    budget = _CaptureBudget()
    storage = _storage_bytes(_capture_root(context, budget), _capture_root(bundle, budget))
    return canonical, storage


class NAVCalculator:
    """Compute a sealed retrospective NAV or a stable unavailable result."""

    __slots__ = ()

    def compute(
        self,
        balance: object = _MISSING,
        marks: object = _MISSING,
        policy: object = _MISSING,
        **unknown: object,
    ) -> NAVResult:
        if unknown:
            _reject("input_invalid", TypeError)
        if type(balance) is not LedgerBalance or type(policy) is not AccountingPolicy:
            _reject()
        if type(marks) is not tuple:
            _reject()
        if len(marks) > _MAX_MARKS:
            _reject("resource_limit")
        balance_ingress = _verify_balance(balance)
        owned_balance = _clone_balance(balance)
        policy_parts: list[object] = []
        policy_ingress = _refresh_policy(policy, policy_parts)
        mark_parts = tuple(_capture_mark(mark) for mark in marks)
        result = self._compute_owned(owned_balance, mark_parts, tuple(policy_parts))
        # Validate original native and canonical snapshots after every source
        # capture/reduction opportunity, including unavailable results.
        if _verify_balance(balance) != balance_ingress or _refresh_policy(policy) != policy_ingress:
            _reject("source_changed")
        for mark, (_state, witness) in zip(marks, mark_parts, strict=True):
            if _capture_mark(mark)[1] != witness:
                _reject("source_changed")
        return result

    @staticmethod
    def _compute_owned(
        balance: LedgerBalance, marks: tuple[object, ...], policy: tuple[object, ...]
    ) -> NAVResult:
        policy_prepared, target, valuation_cutoff, archive_cutoff, currency, source, revision = policy
        run_id, calendar_id, _policy_instrument = _instrument_from_binding(policy_prepared)
        policy_source_group = _binding_run_group(policy_prepared)
        policy_calendar = object.__getattribute__(policy_prepared[1], "calendar")
        target_session: object | None = None
        session_error = False
        try:
            target_session = policy_calendar.session(target)
        except Exception:
            session_error = True
        if session_error or target_session is None:
            return _unavailable("target_session_unavailable")

        if balance.run_id != run_id or balance.calendar_id != calendar_id:
            return _unavailable("binding_mismatch")
        if balance.currency != currency:
            return _unavailable("currency_mismatch")
        target_close = object.__getattribute__(target_session, "close_at")
        if target_close < balance.opening_time:
            return _unavailable("target_before_opening_state")
        if balance.latest_economic_time is not None and object.__getattribute__(target_session, "close_at") < balance.latest_economic_time:
            return _unavailable("target_before_economic_state")
        if valuation_cutoff < target_close or archive_cutoff < target_close:
            return _unavailable("target_after_cutoff")
        if balance.latest_observation_time is not None and valuation_cutoff < balance.latest_observation_time:
            return _unavailable("observation_after_valuation_cutoff")
        replay_policy = object.__getattribute__(object.__getattribute__(policy_prepared[1], "replay_policy"), "value")
        if replay_policy == BundleReplayPolicy.ARCHIVE_REALISTIC.value and balance.latest_observation_time is not None and archive_cutoff < balance.latest_observation_time:
            return _unavailable("observation_after_archive_cutoff")

        holdings = {instrument: quantity for instrument, quantity in balance.positions if quantity > 0}
        mark_prices: dict[str, Decimal] = {}
        seen: set[str] = set()
        if len(holdings) > _MAX_INSTRUMENTS:
            _reject("resource_limit")
        for mark_state, _witness in marks:
            mark_prepared, outcome_state = mark_state
            mark_run, mark_calendar, mark_instrument = _instrument_from_binding(mark_prepared)
            if mark_run != balance.run_id or mark_calendar != balance.calendar_id:
                return _unavailable("mark_binding_mismatch")
            if _binding_run_group(mark_prepared) != policy_source_group:
                return _unavailable("mark_source_binding_mismatch")
            bar = outcome_state[0]
            manifest = object.__getattribute__(bar, "manifest")
            instrument_id = _safe_identifier(object.__getattribute__(bar, "instrument_id"))
            instrument_source_id = _safe_identifier(object.__getattribute__(mark_instrument, "instrument_id"))
            if instrument_id != instrument_source_id:
                return _unavailable("wrong_instrument")
            if object.__getattribute__(bar, "calendar_id") != balance.calendar_id:
                return _unavailable("wrong_calendar")
            if object.__getattribute__(bar, "session_date") != target:
                return _unavailable("wrong_session")
            if object.__getattribute__(bar, "interval") != "1d":
                return _unavailable("wrong_interval")
            if object.__getattribute__(bar, "finality") is not BarFinality.FINAL:
                return _unavailable("mark_not_final")
            if object.__getattribute__(bar, "adjustment_basis") is not AdjustmentBasis.UNADJUSTED:
                return _unavailable("mark_adjusted")
            if object.__getattribute__(manifest, "event_time") != target_close:
                return _unavailable("wrong_mark_event_time")
            if object.__getattribute__(manifest, "source") != source:
                return _unavailable("wrong_mark_source")
            if object.__getattribute__(manifest, "revision") != revision:
                return _unavailable("wrong_mark_revision")
            availability = _safe_utc(object.__getattribute__(manifest, "available_at"))
            ingestion = _safe_utc(object.__getattribute__(manifest, "ingested_at"))
            if availability > valuation_cutoff:
                return _unavailable("mark_after_valuation_cutoff")
            if replay_policy == BundleReplayPolicy.ARCHIVE_REALISTIC.value and ingestion > archive_cutoff:
                return _unavailable("mark_after_archive_cutoff")
            instrument_currency = object.__getattribute__(mark_instrument, "currency")
            if instrument_currency != balance.currency or instrument_currency != currency:
                return _unavailable("currency_mismatch")
            if instrument_id in seen:
                return _unavailable("duplicate_mark")
            seen.add(instrument_id)
            if instrument_id not in holdings:
                return _unavailable("unexpected_mark")
            mark_prices[instrument_id] = _decimal_checked(object.__getattribute__(bar, "close"), "execution", positive=True)

        if set(mark_prices) != set(holdings):
            return _unavailable("missing_mark")
        value = _exact_decimal(
            lambda: balance.cash
            + sum((quantity * mark_prices[instrument] for instrument, quantity in holdings.items()), Decimal(0))
            + balance.receivables
            - balance.liabilities
        )
        value = _decimal_checked(value, "money")
        return _available(value)


__all__ = ["AccountingPolicy", "EligibleMark", "NAVCalculator", "NAVResult"]

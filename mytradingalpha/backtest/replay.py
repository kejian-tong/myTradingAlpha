"""Deterministic BT-05 operation receipts and explicit-root immutable recovery."""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import PosixPath

from mytradingalpha.contracts.orders import _fixed_context

from . import (
    benchmarks as _bench,
    corporate_actions as _actions,
    fills as _fills,
    ledger as _ledger,
    nav as _nav,
)
from .manifest import (
    MAX_OPERATIONS,
    MAX_RECORD,
    PRIORITY,
    SERIALIZATION,
    ReplayManifest,
    _benchmark_prefix,
    _decimal,
    _decode,
    _exact_event,
    _exact_result,
    _fail,
    _hash,
    _json,
    _mget,
    _native,
    _new_ledger,
    _output_material,
    _Projection,
    _strategy_nav,
    _tuple,
)
from .orders import SimOrder

_OPERATION_DOMAIN = b"mytradingalpha:bt05:operation-prefix:v1\0"
_LOCK = ".bt05.lock"
_NAME = re.compile(r"(?:operation|checkpoint)-([0-9]{6})\.json\Z")
_TEMP = re.compile(r"\.tmp-([0-9]{6})\Z")
_CP_FIELDS = frozenset((
    "schema_version", "semantic_input_hash", "artifact_integrity_hash", "operation_count",
    "operation_prefix_hash", "next_cursor", "ledger_event_count", "ledger_tail_hash",
    "ledger_balance", "ledger_native_witness", "orders", "attempt_state", "remaining_cap",
    "action_state", "cash_benchmark", "buy_and_hold_benchmark", "reducer_versions",
    "numeric_policy_version", "serialization_version", "closed_sessions", "status", "reason_code",
    "benchmark_full_integrity",
))


class ReplayCheckpoint:
    """Derived immutable evidence; decode never restores a reducer's internals."""

    __slots__ = ("_raw", "_seal")

    def __init__(self, *_: object, **__: object) -> None:
        _fail()

    @classmethod
    def from_bytes(cls, raw: bytes) -> ReplayCheckpoint:
        if cls is not ReplayCheckpoint:
            _fail()
        data = _decode(raw)
        if type(data) is not dict or set(data) != _CP_FIELDS:
            _fail()
        if data["schema_version"] != "v1" or data["serialization_version"] != SERIALIZATION or data["numeric_policy_version"] != "bt03-decimal-v1":
            _fail()
        for name in ("operation_count", "ledger_event_count", "closed_sessions"):
            if type(data[name]) is not int or not 0 <= data[name] <= MAX_OPERATIONS:
                _fail()
        for name in ("semantic_input_hash", "artifact_integrity_hash", "operation_prefix_hash", "ledger_tail_hash"):
            value = data[name]
            if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
                _fail()
        _checkpoint_schema(data)
        value = object.__new__(cls)
        object.__setattr__(value, "_raw", raw)
        object.__setattr__(value, "_seal", hashlib.sha256(raw).digest())
        return value

    def canonical_bytes(self) -> bytes:
        if type(self) is not ReplayCheckpoint:
            _fail()
        raw, seal = object.__getattribute__(self, "_raw"), object.__getattribute__(self, "_seal")
        if type(raw) is not bytes or len(raw) > MAX_RECORD or type(seal) is not bytes or len(seal) != 32:
            _fail()
        if hashlib.sha256(raw).digest() != seal:
            _fail()
        return raw

    def __getattr__(self, name: str) -> object:
        if type(name) is not str or name not in _CP_FIELDS:
            raise AttributeError("unknown checkpoint field")
        return _decode(self.canonical_bytes())[name]

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ReplayCheckpoint is immutable")


def _hex(value: object) -> None:
    if type(value) is not str or len(value) > MAX_RECORD or len(value) % 2 or re.fullmatch(r"[0-9a-f]+", value) is None:
        _fail()


def _date_string(value: object, *, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        _fail()
    from datetime import date
    try:
        if date.fromisoformat(value).isoformat() != value:
            _fail()
    except ValueError:
        _fail()


def _native_order(value: object) -> None:
    if type(value) is not list or len(value) != 2 or value[0] != "SimOrder" or type(value[1]) is not dict:
        _fail()
    fields = value[1]
    if set(fields) != {"intent_id", "remaining_quantity", "cumulative_quantity", "cumulative_fee", "status", "reason_code"}:
        _fail()
    if type(fields["intent_id"]) is not str or fields["status"] not in ("filled", "cancelled", "expired", "open_at_horizon"):
        _fail()
    if fields["reason_code"] is not None and type(fields["reason_code"]) is not str:
        _fail()
    for name in ("remaining_quantity", "cumulative_quantity", "cumulative_fee"):
        number = fields[name]
        if type(number) is not list or len(number) != 4 or number[0] != "Decimal":
            _fail()
        _, sign, digits, exponent = number
        if type(sign) is not int or sign not in (0, 1) or type(digits) is not list or not 1 <= len(digits) <= 128:
            _fail()
        if any(type(digit) is not int or not 0 <= digit <= 9 for digit in digits) or type(exponent) is not int or not -64 <= exponent <= 64:
            _fail()
        decimal = Decimal((sign, tuple(digits), exponent))
        _decimal(decimal)
        if decimal < 0:
            _fail()


def _checkpoint_schema(data: dict) -> None:
    cursor = data["next_cursor"]
    if type(cursor) is not dict or set(cursor) != {"operation_index", "session_index", "session_date", "stage", "intent_position"}:
        _fail()
    if type(cursor["operation_index"]) is not int or cursor["operation_index"] != data["operation_count"]:
        _fail()
    if type(cursor["session_index"]) is not int or not 0 <= cursor["session_index"] <= 16:
        _fail()
    if cursor["stage"] not in ("opening", "payment", "attempt", "closing", "complete", "unavailable"):
        _fail()
    _date_string(cursor["session_date"], nullable=cursor["stage"] in ("complete", "unavailable"))
    if cursor["stage"] == "attempt":
        if type(cursor["intent_position"]) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", cursor["intent_position"]) is None:
            _fail()
    elif cursor["intent_position"] is not None:
        _fail()
    reducers = data["reducer_versions"]
    if type(reducers) is not dict or set(reducers) != {"runner", "priority", "cost", "action"} or reducers["runner"] != "bt05-operation-v1" or reducers["priority"] != PRIORITY:
        _fail()
    if any(type(reducers[name]) is not str or not reducers[name] for name in ("cost", "action")):
        _fail()
    if data["status"] not in ("available", "unavailable") or not 0 <= data["closed_sessions"] <= 16:
        _fail()
    if (data["status"] == "available" and data["reason_code"] is not None) or (data["status"] == "unavailable" and (type(data["reason_code"]) is not str or not data["reason_code"])):
        _fail()
    _hex(data["ledger_native_witness"])
    for field in ("cash_benchmark", "buy_and_hold_benchmark"):
        value = data[field]
        if type(value) is not dict or set(value) != {"source_type", "native_witness"} or value["source_type"] != "BenchmarkSeries":
            _fail()
        _hex(value["native_witness"])
    if type(data["orders"]) is not list or len(data["orders"]) > 256 or type(data["attempt_state"]) is not list or len(data["attempt_state"]) != len(data["orders"]):
        _fail()
    for order in data["orders"]:
        _native_order(order)
    for attempt in data["attempt_state"]:
        if type(attempt) is not dict or set(attempt) != {"intent_id", "last_session", "next_session", "native_state"}:
            _fail()
        _date_string(attempt["last_session"])
        _date_string(attempt["next_session"])
        _native_order(attempt["native_state"])
        if attempt["intent_id"] != attempt["native_state"][1]["intent_id"]:
            _fail()
    if type(data["remaining_cap"]) is not list:
        _fail()
    for cap in data["remaining_cap"]:
        if type(cap) is not list or len(cap) != 3 or type(cap[0]) is not str or type(cap[2]) is not str or len(cap[2]) > 200:
            _fail()
        _date_string(cap[1], nullable=False)
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", cap[2]) is None:
            _fail()
        number = Decimal(cap[2])
        if _decimal(number) != cap[2]:
            _fail()
    balance = data["ledger_balance"]
    fields = {"calendar_id", "cash", "currency", "event_count", "fill_ids", "instrument_ids", "genesis_hash", "intent_ownership", "latest_economic_time", "latest_observation_time", "liabilities", "numeric_policy_version", "obligations", "opening_cash", "opening_time", "positions", "prefix_count", "prefix_tail", "recognized_expense", "recognized_income", "receivables", "resolution_cutoff", "run_id", "schema_version", "session_cap_ownership", "start_sequence", "total_fees", "next_sequence"}
    if type(balance) is not dict or set(balance) not in (fields, fields | {"action_state"}):
        _fail()
    if balance["schema_version"] != "v1" or balance["numeric_policy_version"] != "bt03-decimal-v1" or balance["event_count"] != data["ledger_event_count"] or balance["prefix_tail"] != data["ledger_tail_hash"]:
        _fail()
    if type(data["action_state"]) is not dict or set(data["action_state"]) != set(_actions._ActionState._fields):
        _fail()
    if type(data["benchmark_full_integrity"]) is not list or len(data["benchmark_full_integrity"]) != 2:
        _fail()
    if any(type(item) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", item) is None for item in data["benchmark_full_integrity"]):
        _fail()


@dataclass(frozen=True, slots=True, eq=False)
class ReplayResult:
    events: tuple
    balances: tuple
    nav_points: tuple
    orders: tuple
    cash_benchmark: _bench.BenchmarkSeries
    buy_and_hold_benchmark: _bench.BenchmarkSeries
    checkpoint: ReplayCheckpoint
    status: str
    run_valid: bool
    reason_code: str | None
    completed: bool
    semantic_input_hash: str
    economic_output_hash: str
    artifact_integrity_hash: str

    @property
    def results(self) -> tuple:
        return (*self.balances, *self.nav_points, *self.orders, self.cash_benchmark, self.buy_and_hold_benchmark)


class _Engine:
    """Replay financial authority with existing reducers; keep progress separate."""

    def __init__(self, manifest: ReplayManifest) -> None:
        manifest._refresh()
        self.manifest, self.projection = manifest, _Projection(manifest)
        self.operations = object.__getattribute__(manifest, "_operations")
        self.ledger = _new_ledger(manifest)
        self.balance = self.ledger.balance()
        self.events, self.event_records = [], []
        self._wire_cache = None
        self._balance_record()
        self.index, self.closed = 0, 0
        self.balances, self.nav_points, self.cap, self.attempts = [], [], {}, {}
        self.status, self.reason = "available", None
        self.full_benchmarks = manifest._benchmarks()
        self.benchmarks = tuple(_benchmark_prefix(full, 0) for full in self.full_benchmarks)
        self.benchmark_records = tuple(_exact_result(prefix) for prefix in self.benchmarks)
        self.full_integrity = [_hash(b"mytradingalpha:bt05:benchmark-integrity:v1\0", _json(_exact_result(full))) for full in self.full_benchmarks]
        self.semantic_input = manifest.semantic_input_hash()
        self.exact_input = manifest.artifact_integrity_hash()
        self.prefix = _hash(_OPERATION_DOMAIN, _json({"schema_version": "v1", "semantic_input_hash": self.semantic_input,
                                                      "artifact_integrity_hash": self.exact_input}))
        self.orders, self.intent_by_semantic, self.bindings = {}, {}, {}
        for binding in _mget(manifest, "bindings"):
            data = _fills._binding_data(binding)[0]
            self.bindings[data.decision_event_id] = binding
        for intent in _mget(manifest, "intents"):
            self.orders[intent.intent_id] = [intent.quantity, Decimal(0), Decimal(0), "open_at_horizon", None]
            self.attempts[intent.intent_id] = None
            self.intent_by_semantic[self.projection.reference("intent", intent.intent_id)] = intent
        self.outcomes = {}
        for outcome in _mget(manifest, "outcomes"):
            bar = object.__getattribute__(outcome, "_bar_snapshot")
            self.outcomes[(bar.instrument_id, bar.calendar_id, bar.session_date, bar.manifest.source, bar.manifest.revision)] = outcome

    def orders_result(self) -> tuple:
        ordered = sorted(self.orders, key=lambda identifier: self.projection.reference("intent", identifier))
        return tuple(SimOrder(identifier, *self.orders[identifier]) for identifier in ordered)

    def cursor(self) -> dict:
        if self.index == len(self.operations) or self.status != "available":
            return {"operation_index": self.index, "session_index": self.closed, "session_date": None,
                    "stage": "complete" if self.status == "available" else "unavailable", "intent_position": None}
        row = self.operations[self.index]
        return {"operation_index": self.index, "session_index": row[0], "session_date": row[1],
                "stage": row[2], "intent_position": row[3]}

    def checkpoint_data(self, *, prefix: str | None = None) -> dict:
        balance = self.balance
        attempts = []
        for order in self.orders_result():
            next_session = None
            if order.status == "open_at_horizon":
                semantic = self.projection.reference("intent", order.intent_id)
                next_session = next((row[1] for row in self.operations[self.index:] if row[2] == "attempt" and row[3] == semantic), None)
            attempts.append({"intent_id": order.intent_id, "last_session": self.attempts[order.intent_id],
                             "next_session": next_session, "native_state": _native(order)})
        return {
            "schema_version": "v1", "semantic_input_hash": self.semantic_input,
            "artifact_integrity_hash": self.exact_input,
            "operation_count": self.index, "operation_prefix_hash": self.prefix if prefix is None else prefix,
            "next_cursor": self.cursor(), "ledger_event_count": balance.event_count,
            "ledger_tail_hash": balance.prefix_hashes[-1] if balance.prefix_hashes else balance.genesis_hash,
            "ledger_balance": self.balance_wire, "ledger_native_witness": self.balance_native,
            "orders": [_native(order) for order in self.orders_result()], "attempt_state": attempts,
            "remaining_cap": [[instrument, day.isoformat(), _decimal(quantity)] for (instrument, day), quantity in sorted(self.cap.items())],
            "action_state": self.action_wire,
            "cash_benchmark": self.benchmark_records[0], "buy_and_hold_benchmark": self.benchmark_records[1],
            "reducer_versions": {"runner": "bt05-operation-v1", "priority": PRIORITY,
                                 "cost": _mget(self.manifest, "cost_policy").policy_version,
                                 "action": _actions._get(_mget(self.manifest, "action_policy"), "policy_version")},
            "numeric_policy_version": "bt03-decimal-v1", "serialization_version": SERIALIZATION,
            "closed_sessions": self.closed, "status": self.status, "reason_code": self.reason,
            "benchmark_full_integrity": self.full_integrity,
        }

    def checkpoint(self) -> ReplayCheckpoint:
        return ReplayCheckpoint.from_bytes(_json(self.checkpoint_data()))

    def step(self) -> bytes:
        if self.index >= len(self.operations) or self.status != "available":
            _fail()
        self.manifest._refresh()
        self._wire_cache = None
        row = self.operations[self.index]
        item = _mget(self.manifest, "sessions")[row[0]]
        session, stage = _actions._get(item, "session"), row[2]
        before_count = len(self.events)
        event_id = f"bt05-event-{self.index:06d}"
        if stage == "opening":
            for intent in _mget(self.manifest, "intents"):
                if self.orders[intent.intent_id][3] == "open_at_horizon" and intent.expires_at < session.open_at:
                    self.orders[intent.intent_id][3:] = ["expired", "intent_expired"]
            actions, mergers = _actions._get(item, "actions"), _actions._get(item, "mergers")
            outstanding = tuple(sorted((intent for intent in _mget(self.manifest, "intents")
                if self.orders[intent.intent_id][3] == "open_at_horizon" and intent.created_at < session.open_at),
                key=lambda intent: self.projection.reference("intent", intent.intent_id)))
            if not actions and not mergers:
                outstanding = ()
            if len(outstanding) > 64:
                _fail()
            common = _actions._get(_mget(self.manifest, "cash_benchmark_policy"), "common")
            events = _actions.CorporateActionReducer().apply_opening_actions(self.balance, actions, session,
                _mget(self.manifest, "action_policy"), calendar=_actions._get(common, "calendar"), event_id=event_id,
                outstanding_intents=outstanding, references=_actions._get(item, "references"), mergers=mergers,
                replay_policy=_actions._get(common, "replay_policy"), archive_cutoff=session.open_at)
            for event in events:
                self._append(event)
            for cancellation in _actions._get(self.ledger.action_state(), "cancelled_intents"):
                identifier = _actions._get(cancellation, "intent_id")
                if identifier not in self.orders:
                    _fail()
                if self.orders[identifier][3] == "open_at_horizon":
                    self.orders[identifier][3:] = ["cancelled", _actions._get(cancellation, "reason")]
        elif stage == "payment":
            common = _actions._get(_mget(self.manifest, "cash_benchmark_policy"), "common")
            events = _actions.CorporateActionReducer().apply_payments(self.balance, session,
                _mget(self.manifest, "action_policy"), calendar=_actions._get(common, "calendar"), event_id=event_id)
            for event in events:
                self._append(event)
        elif stage == "attempt":
            self._attempt(self.intent_by_semantic[row[3]], session, event_id)
        elif stage == "closing":
            self._closing(item, session)
        else:
            _fail()
        self.index += 1
        if len(self.events) - before_count not in (0, 1):
            _fail()
        data = self.checkpoint_data()
        del data["operation_prefix_hash"]
        record = {"schema_version": "v1", "operation_index": self.index - 1, "cursor": row,
                  "previous_hash": self.prefix, "event": None if len(self.events) == before_count else self.event_records[-1],
                  "progress": data}
        raw = _json(record, 16 * 1024 * 1024)
        self.prefix = _hash(_OPERATION_DOMAIN, raw)
        self.manifest._refresh()
        return raw

    def _balance_record(self) -> None:
        """Consume only the immutable balance just issued by our owned Ledger."""
        balance = self.balance
        self.balance_wire = _decode(object.__getattribute__(balance, "_canonical"))
        self.balance_native = _json(_ledger._jsonable(object.__getattribute__(balance, "_witness"))).hex()
        self.action_wire = _decode(_actions._state(balance).canonical_bytes())

    def _append(self, event: _ledger.LedgerEvent) -> None:
        balance = self.ledger.append(event)
        if balance.event_count != len(self.events) + 1:
            _fail()
        self.balance = balance
        # Ledger.append validated and defensively retained this newly constructed
        # event. Retain its accepted canonical/native record once for this operation.
        raw = object.__getattribute__(event, "_canonical")
        witness = object.__getattribute__(event, "_storage_witness")
        self.events.append(event)
        self.event_records.append({"canonical_utf8": raw.decode(), "event_native_witness": _json(_ledger._jsonable(witness)).hex()})
        self._balance_record()

    def _attempt(self, intent: object, session: object, event_id: str) -> None:
        state = self.orders[intent.intent_id]
        if state[3] != "open_at_horizon":
            return  # A planned slot is a receipt, never a repeated terminal attempt.
        self.attempts[intent.intent_id] = session.session_date.isoformat()
        if session.close_at < intent.earliest_submit_time:
            state[4] = "not_yet_eligible"
            if intent.time_in_force != "gtc":
                state[3] = "expired"
            return
        key = (intent.instrument_id, intent.calendar_id, session.session_date, intent.outcome_source, intent.outcome_revision)
        outcome = self.outcomes.get(key)
        if outcome is None:
            _fail()
        policy = _mget(self.manifest, "cost_policy")
        slot = (intent.instrument_id, session.session_date)
        cap = self.cap.setdefault(slot, policy.fixed_share_cap)
        balance = self.balance
        shares = dict(balance.positions).get(intent.instrument_id, Decimal(0))
        binding = self.bindings[intent.decision_event_id]
        decision = _fills.FillModel.simulate(intent, outcome, state[0], balance.cash, shares, cap, policy,
            binding=binding, session_date=session.session_date, cumulative_quantity=state[1])
        if decision.fill is not None:
            fill = decision.fill
            self._append(_ledger.LedgerEvent.for_fill(event_id=event_id, sequence=balance.next_sequence,
                previous_hash=balance.prefix_hashes[-1] if balance.prefix_hashes else balance.genesis_hash,
                intent=intent, fill=fill, binding=binding, outcome=outcome, policy=policy))
            with localcontext(_fixed_context()):
                state[0] -= fill.quantity
                state[1] += fill.quantity
                state[2] += fill.fee
                self.cap[slot] -= fill.quantity
            if state[0] == 0:
                state[3:] = ["filled", None]
        if state[3] != "filled":
            if intent.time_in_force == "day":
                state[3:] = ["expired", "day_remainder_expired"]
            elif intent.time_in_force != "gtc":
                state[3:] = ["cancelled", "time_in_force_remainder_cancelled"]
            else:
                state[4] = decision.reason_code

    def _closing(self, item: object, session: object) -> None:
        for intent in _mget(self.manifest, "intents"):
            state = self.orders[intent.intent_id]
            if state[3] == "open_at_horizon" and intent.first_session_date <= session.session_date and intent.expires_at <= session.close_at:
                state[3:] = ["expired", "intent_expired"]
        balance = self.balance
        nav = _strategy_nav(balance, item)
        self.balances.append(balance)
        self.nav_points.append(nav)
        self.closed += 1
        prefixes = []
        for full in self.full_benchmarks:
            points = _actions._get(full, "nav_points")
            failed = self.closed > len(points) or (self.closed <= len(points) and not points[self.closed - 1].run_valid)
            prefix = _benchmark_prefix(full, self.closed, reached_failure=failed)
            prefixes.append(prefix)
            if failed:
                self.status, self.reason = "unavailable", _actions._get(full, "reason_code") or "required_benchmark_unavailable"
        self.benchmarks = tuple(prefixes)
        self.benchmark_records = tuple(_exact_result(prefix) for prefix in self.benchmarks)
        if not nav.run_valid:
            self.status, self.reason = "unavailable", nav.reason_code

    def result(self) -> ReplayResult:
        self.manifest._refresh()
        # No caller receives an Engine-owned graph, including on repeated reads.
        events = tuple(_ledger._clone_event(event) for event in self.events)
        balances = tuple(_ledger._clone_balance(balance) for balance in self.balances)
        points = tuple(_nav.NAVResult(point.status, point.value, point.reason_code, point.run_valid,
                                     point.formula_version, point.numeric_policy_version) for point in self.nav_points)
        orders = self.orders_result()
        cash, bh = tuple(_actions._clone_value(value) for value in self.benchmarks)
        results = (*balances, *points, *orders, cash, bh)
        checkpoint = self.checkpoint()
        economic, integrity, event_records, result_records = _output_material(self.manifest, events, results)
        result = ReplayResult(events, balances, points, orders, cash, bh, checkpoint, self.status,
            self.status == "available", self.reason, self.index == len(self.operations) or self.status != "available",
            self.manifest.semantic_input_hash(), economic, integrity)
        self._wire_cache = _json({"schema_version": "v1", "semantic_input_hash": result.semantic_input_hash,
            "economic_output_hash": economic, "artifact_integrity_hash": integrity,
            "status": result.status, "reason_code": result.reason_code, "run_valid": result.run_valid,
            "checkpoint": _decode(checkpoint.canonical_bytes()), "events": event_records, "results": result_records})
        self.manifest._refresh()
        return result


def _result_bytes(result: ReplayResult) -> bytes:
    return _json({"schema_version": "v1", "semantic_input_hash": result.semantic_input_hash,
        "economic_output_hash": result.economic_output_hash, "artifact_integrity_hash": result.artifact_integrity_hash,
        "status": result.status, "reason_code": result.reason_code, "run_valid": result.run_valid,
        "checkpoint": _decode(result.checkpoint.canonical_bytes()),
        "events": [_exact_event(event) for event in result.events], "results": [_exact_result(value) for value in result.results]})


def _root_path(root: object) -> str:
    if type(root) is str:
        return root
    if type(root) is not PosixPath:
        _fail()
    # Inspect only declared native slots, never a property that could render
    # the caller's mutable Path before its stored values have been admitted.
    declared = {name for owner in PosixPath.__mro__
                for name in owner.__dict__.get("__slots__", ())}
    if "_raw_paths" in declared:
        authority = "_raw_paths"
    elif "_parts" in declared:
        authority = "_parts"
    else:
        _fail()
    captured, byte_count, component_count = {}, 0, 0

    def admit_text(value: object) -> str:
        nonlocal byte_count
        if type(value) is not str or len(value) > 65536:
            _fail()
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError:
            _fail()
        if size > 65536 or byte_count + size > 65536:
            _fail()
        byte_count += size
        return value

    component_fields = ("_raw_paths", "_parts", "_tail_cached")
    for name in ("_str", "_drv", "_root", *component_fields):
        if name not in declared:
            continue
        try:
            value = object.__getattribute__(root, name)
        except AttributeError:
            if name == authority:
                _fail()
            continue
        if name in component_fields:
            if (type(value) is not list and type(value) is not tuple) or len(value) > 4096:
                _fail()
            parts = []
            for item in value:
                component_count += 1
                if component_count > 4096:
                    _fail()
                parts.append(admit_text(item))
            captured[name] = tuple(parts)
        else:
            captured[name] = admit_text(value)
    # No caller-owned object or container is consulted beyond this snapshot.
    owned = PosixPath(*captured[authority])
    path = str(owned)
    for name, expected in captured.items():
        try:
            actual = path if name == "_str" else object.__getattribute__(owned, name)
        except AttributeError:
            _fail()
        if name in component_fields:
            actual = tuple(actual)
        if expected != actual:
            _fail()
    return path


class ReplayRunner:
    """One descriptor-anchored OS append owner beneath an existing absolute root."""

    __slots__ = ("_fds", "_chain", "_root", "_lock", "_closed", "_accepted")

    def __init__(self, *, root: object) -> None:
        if type(self) is not ReplayRunner:
            _fail()
        self._fds, self._chain, self._root, self._lock, self._closed = [], [], None, None, False
        self._accepted = {}
        try:
            path = _root_path(root)
            if type(path) is not str or len(path) > 4096 or not path.startswith("/") or "\0" in path:
                _fail()
            try:
                path_size = len(path.encode("utf-8"))
            except UnicodeError:
                _fail()
            if path_size > 4096:
                _fail()
            parts = path.split("/")[1:]
            if not parts or len(parts) > 64 or any(not part or part in (".", "..") for part in parts):
                _fail()
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            parent = os.open("/", flags)
            self._fds.append(parent)
            for part in parts:
                descriptor = os.open(part, flags, dir_fd=parent)
                self._fds.append(descriptor)
                identity = os.fstat(descriptor)
                self._chain.append((parent, part, descriptor, identity.st_dev, identity.st_ino))
                parent = descriptor
            self._root = parent
            root_stat = os.fstat(parent)
            if root_stat.st_uid != os.getuid() or root_stat.st_mode & 0o022:
                _fail()
            inventory = self._inventory()
            if _LOCK not in inventory and len(inventory) >= 16384:
                _fail()
            created = False
            try:
                lock = os.open(_LOCK, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                created = True
            except FileExistsError:
                lock = os.open(_LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            self._fds.append(lock)
            self._lock = lock
            current = os.fstat(lock)
            if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or current.st_uid != os.getuid() or current.st_mode & 0o022:
                _fail()
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._verify()
            self._inventory()
            if created:
                os.fsync(lock)
                os.fsync(parent)
        except BaseException as error:
            self.close()
            if isinstance(error, OSError):
                _fail()
            raise

    def __enter__(self) -> ReplayRunner:
        self._verify()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in reversed(self._fds):
            os.close(descriptor)
        self._fds = []

    def _verify(self) -> None:
        if type(self) is not ReplayRunner or type(self._closed) is not bool or self._closed or type(self._root) is not int or type(self._lock) is not int:
            _fail()
        if type(self._chain) is not list or len(self._chain) > 64:
            _fail()
        for row in self._chain:
            if type(row) is not tuple or len(row) != 5 or any(type(row[index]) is not int for index in (0, 2, 3, 4)) or type(row[1]) is not str:
                _fail()
        try:
            for parent, name, descriptor, device, inode in self._chain:
                linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
                pinned = os.fstat(descriptor)
                if not stat.S_ISDIR(linked.st_mode) or (linked.st_dev, linked.st_ino) != (device, inode) or (pinned.st_dev, pinned.st_ino) != (device, inode):
                    _fail()
            linked = os.stat(_LOCK, dir_fd=self._root, follow_symlinks=False)
            pinned = os.fstat(self._lock)
            root = os.fstat(self._root)
            if root.st_uid != os.getuid() or root.st_mode & 0o022:
                _fail()
            if not stat.S_ISREG(linked.st_mode) or linked.st_nlink != 1 or linked.st_uid != os.getuid() or linked.st_mode & 0o022 or (linked.st_dev, linked.st_ino) != (pinned.st_dev, pinned.st_ino):
                _fail()
        except OSError:
            _fail()

    def _inventory(self) -> dict:
        result, inodes, retained = {}, {}, 0
        try:
            with os.scandir(self._root) as entries:
                for entry in entries:
                    if len(result) >= 16384 or type(entry.name) is not str:
                        _fail()
                    name = entry.name
                    if name not in (_LOCK, "manifest.json", "result.json") and _NAME.fullmatch(name) is None and _TEMP.fullmatch(name) is None:
                        _fail()
                    info = os.stat(name, dir_fd=self._root, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > MAX_RECORD or info.st_mode & 0o022:
                        _fail()
                    retained += info.st_size
                    if retained > 256 * 1024 * 1024:
                        _fail()
                    result[name] = info
                    inodes.setdefault((info.st_dev, info.st_ino), []).append(name)
        except OSError:
            _fail()
        for names in inodes.values():
            info = result[names[0]]
            if info.st_nlink != len(names):
                _fail()
            if len(names) > 1 and (len(names) != 2 or sum(_TEMP.fullmatch(name) is not None for name in names) != 1 or _LOCK in names):
                _fail()
        return result

    def _read(self, name: str, maximum: int = MAX_RECORD) -> bytes:
        self._artifact_name(name)
        if type(maximum) is not int or not 0 < maximum <= MAX_RECORD:
            _fail()
        self._verify()
        descriptor = None
        try:
            prior = os.stat(name, dir_fd=self._root, follow_symlinks=False)
            if not stat.S_ISREG(prior.st_mode) or prior.st_size > maximum:
                _fail()
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._root)
            actual = os.fstat(descriptor)
            if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino, actual.st_size) != (prior.st_dev, prior.st_ino, prior.st_size):
                _fail()
            chunks, size = [], 0
            while True:
                block = os.read(descriptor, min(1024 * 1024, maximum + 1 - size))
                if not block:
                    break
                size += len(block)
                if size > maximum:
                    _fail()
                chunks.append(block)
            after = os.fstat(descriptor)
            leaf = os.stat(name, dir_fd=self._root, follow_symlinks=False)
            identity = self._identity(actual)
            if identity != self._identity(after) or identity != self._identity(leaf) or size != actual.st_size:
                _fail()
            if name in self._accepted and self._accepted[name] != identity:
                _fail()
            self._accepted[name] = identity
            return b"".join(chunks)
        except OSError:
            _fail()
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _identity(info: os.stat_result) -> tuple:
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink, info.st_mode, info.st_uid)

    @staticmethod
    def _artifact_name(name: object) -> None:
        if type(name) is not str:
            _fail()
        if name in ("manifest.json", "result.json"):
            return
        match = _NAME.fullmatch(name)
        if match is None or int(match[1]) > MAX_OPERATIONS:
            _fail()

    def _verify_accepted(self) -> None:
        if type(self._accepted) is not dict or len(self._accepted) > 16384:
            _fail()
        if any(type(name) is not str for name in dict.keys(self._accepted)):
            _fail()
        for expected in dict.values(self._accepted):
            if type(expected) is not tuple or len(expected) != 8 or any(type(value) is not int for value in expected):
                _fail()
        try:
            for name, expected in self._accepted.items():
                current = os.stat(name, dir_fd=self._root, follow_symlinks=False)
                if not stat.S_ISREG(current.st_mode) or self._identity(current) != expected:
                    _fail()
        except OSError:
            _fail()

    def _publish(self, name: str, raw: bytes, manifest: ReplayManifest) -> None:
        self._artifact_name(name)
        if type(manifest) is not ReplayManifest or type(raw) is not bytes or len(raw) > MAX_RECORD:
            _fail()
        self._verify()
        self._verify_accepted()
        manifest._refresh()
        inventory = self._inventory()
        if name in inventory:
            if self._read(name) != raw:
                _fail()
            manifest._refresh()
            self._verify()
            self._verify_accepted()
            return
        if len(inventory) >= 16383 or sum(item.st_size for item in inventory.values()) + len(raw) * 2 > 256 * 1024 * 1024:
            _fail()
        next_temp = max((int(match[1]) for item in inventory if (match := _TEMP.fullmatch(item)) is not None), default=-1) + 1
        if next_temp >= 16384:
            _fail()
        temporary = f".tmp-{next_temp:06d}"
        descriptor = reader = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._root)
            offset = 0
            while offset < len(raw):
                written = os.write(descriptor, raw[offset:offset + 1024 * 1024])
                if written <= 0:
                    _fail()
                offset += written
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            pinned = os.fstat(descriptor)
            linked = os.stat(temporary, dir_fd=self._root, follow_symlinks=False)
            if not stat.S_ISREG(linked.st_mode) or linked.st_nlink != 1 or (linked.st_dev, linked.st_ino, linked.st_size) != (pinned.st_dev, pinned.st_ino, len(raw)):
                _fail()
            self._verify()
            manifest._refresh()
            os.link(temporary, name, src_dir_fd=self._root, dst_dir_fd=self._root, follow_symlinks=False)
            os.unlink(temporary, dir_fd=self._root)
            os.fsync(self._root)
            self._verify()
            self._verify_accepted()
            # Link/unlink changes ctime, so take fresh authority from the
            # original descriptor rather than adopting the final pathname.
            pinned = os.fstat(descriptor)
            identity = self._identity(pinned)
            if (not stat.S_ISREG(pinned.st_mode) or pinned.st_uid != os.getuid()
                    or stat.S_IMODE(pinned.st_mode) != 0o400 or pinned.st_nlink != 1
                    or pinned.st_size != len(raw)):
                _fail()
            leaf = os.stat(name, dir_fd=self._root, follow_symlinks=False)
            if self._identity(leaf) != identity:
                _fail()
            reader = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._root)
            if self._identity(os.fstat(reader)) != identity:
                _fail()
            offset = 0
            while offset < len(raw):
                block = os.read(reader, min(1024 * 1024, len(raw) - offset))
                if not block or block != raw[offset:offset + len(block)]:
                    _fail()
                offset += len(block)
            if os.read(reader, 1):
                _fail()
            if (self._identity(os.fstat(descriptor)) != identity
                    or self._identity(os.fstat(reader)) != identity
                    or self._identity(os.stat(name, dir_fd=self._root, follow_symlinks=False)) != identity):
                _fail()
            self._accepted[name] = identity
        except OSError:
            _fail()
        finally:
            if reader is not None:
                os.close(reader)
            if descriptor is not None:
                os.close(descriptor)
        manifest._refresh()
        self._verify()
        self._verify_accepted()

    def run(self, manifest: ReplayManifest, *, max_operations: int | None = None) -> ReplayResult:
        return self._execute(manifest, None, None, max_operations, new=True)

    def resume(self, manifest: ReplayManifest, checkpoint: ReplayCheckpoint | None = None,
               events: tuple | None = None, *, max_operations: int | None = None) -> ReplayResult:
        return self._execute(manifest, checkpoint, events, max_operations, new=False)

    def _execute(self, manifest: object, checkpoint: object, events: object,
                 maximum: object, *, new: bool) -> ReplayResult:
        if type(manifest) is not ReplayManifest:
            _fail()
        if maximum is not None and (type(maximum) is not int or not 0 <= maximum <= MAX_OPERATIONS):
            _fail()
        if checkpoint is not None and type(checkpoint) is not ReplayCheckpoint:
            _fail()
        if events is not None:
            _tuple(events)
            if any(type(event) is not _ledger.LedgerEvent for event in events):
                _fail()
        self._verify()
        manifest._refresh()
        inventory = self._inventory()
        published = {name for name in inventory if name != _LOCK and _TEMP.fullmatch(name) is None}
        if new:
            if published:
                _fail()
        elif "manifest.json" not in published or self._read("manifest.json") != manifest.canonical_bytes():
            _fail()
        operation_names, checkpoints = {}, {}
        for name in published:
            match = _NAME.fullmatch(name)
            if match is None:
                continue
            index = int(match[1])
            if index > MAX_OPERATIONS:
                _fail()
            if name.startswith("operation-"):
                operation_names[index] = name
            else:
                raw = self._read(name)
                checked = ReplayCheckpoint.from_bytes(raw)
                if checked.operation_count != index:
                    _fail()
                checkpoints[index] = raw
        count = len(operation_names)
        if set(operation_names) != set(range(count)) or any(index > count for index in checkpoints):
            _fail()
        if checkpoint is not None:
            raw = checkpoint.canonical_bytes()
            if checkpoints.get(checkpoint.operation_count) != raw:
                _fail()
        engine = _Engine(manifest)
        current = engine.checkpoint().canonical_bytes()
        if 0 in checkpoints and checkpoints[0] != current:
            _fail()
        for index in range(count):
            stored = self._read(operation_names[index], 16 * 1024 * 1024)
            _decode(stored, 16 * 1024 * 1024)
            expected = engine.step()
            if stored != expected:
                _fail()
            current = engine.checkpoint().canonical_bytes()
            if index + 1 in checkpoints and checkpoints[index + 1] != current:
                _fail()
        if events is not None:
            actual = tuple(engine.events)
            if len(events) != len(actual) or any(_exact_event(left) != _exact_event(right) for left, right in zip(events, actual, strict=True)):
                _fail()
        validated_result = None
        if "result.json" in published:
            if not (engine.index == len(engine.operations) or engine.status != "available"):
                _fail()
            validated_result = engine.result()
            if self._read("result.json") != engine._wire_cache:
                _fail()
        self._verify_accepted()
        # Every existing record is reconciled before creating any new artifact.
        if new:
            self._publish("manifest.json", manifest.canonical_bytes(), manifest)
        if 0 not in checkpoints and count == 0:
            self._publish("checkpoint-000000.json", current, manifest)
        added = 0
        while engine.index < len(engine.operations) and engine.status == "available" and (maximum is None or added < maximum):
            raw = engine.step()
            self._publish(f"operation-{engine.index - 1:06d}.json", raw, manifest)
            self._publish(f"checkpoint-{engine.index:06d}.json", engine.checkpoint().canonical_bytes(), manifest)
            added += 1
        result = validated_result if validated_result is not None else engine.result()
        if result.completed:
            self._publish("result.json", engine._wire_cache, manifest)
        manifest._refresh()
        self._verify()
        self._verify_accepted()
        return result


__all__ = ["ReplayCheckpoint", "ReplayResult", "ReplayRunner"]

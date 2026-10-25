"""Typed, source-preserving identities for the opt-in BT-05 offline runner.

Economic projections are versioned by exact production type. Native admission is
separate from projection: no caller serializer, protocol or object loader runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import weakref
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from threading import Condition, RLock
from typing import NamedTuple

from mytradingalpha.contracts import orders as _contracts
from mytradingalpha.contracts.orders import CostBreakdown, Fill, OrderIntent
from mytradingalpha.contracts.research import ResearchNote
from mytradingalpha.contracts.schemas import RunContext
from mytradingalpha.contracts.signals import LLMOverlay, QuantSignal, SignalEnvelope
from mytradingalpha.data.bundle import EvidenceBundle

from . import (
    benchmarks as _bench,
    clock as _clock,
    corporate_actions as _actions,
    fills as _fills,
    ledger as _ledger,
    nav as _nav,
)
from .costs import CostPolicy
from .orders import SimOrder
from .runner import BacktestRunner

SEMANTIC_DOMAIN = b"mytradingalpha:bt05:semantic-input:v1\0"
ECONOMIC_DOMAIN = b"mytradingalpha:bt05:economic-output:v1\0"
ARTIFACT_DOMAIN = b"mytradingalpha:bt05:artifact-integrity:v1\0"
REFERENCE_DOMAIN = b"mytradingalpha:bt05:semantic-reference:v1\0"
SERIALIZATION = "bt05-canonical-v1"
PRIORITY = "bt05-semantic-priority-v1"
MAX_RECORD = 64 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
MAX_SOURCES = 16 * 1024 * 1024
MAX_OPERATIONS = 4096
_FIELDS = (
    "schema_version", "run_id", "correlation_id", "created_at", "bindings", "intents",
    "outcomes", "sessions", "cost_policy", "action_policy", "cash_benchmark_policy",
    "buy_and_hold_policy", "opening_cash", "opening_time", "resolution_cutoff",
    "start_sequence", "code_version", "config_version", "model_version",
    "configuration", "seed", "priority_policy",
)
_ROOTS = ("bindings", "intents", "outcomes", "sessions", "cost_policy",
          "action_policy", "cash_benchmark_policy", "buy_and_hold_policy")
_MODELS = (*_clock._MODEL_TYPES, OrderIntent, Fill, CostBreakdown, CostPolicy)
_MODEL_FIELDS = {model: tuple(model.model_fields) for model in _MODELS}
_VALUES = (*_actions._ACTION_VALUES, *_bench._BENCH_VALUES)
_VALUE_FIELDS = {model: model._fields for model in _VALUES}
_NAV_FIELDS = ("status", "value", "reason_code", "run_valid", "formula_version", "numeric_policy_version")
_ORDER_FIELDS = ("intent_id", "remaining_quantity", "cumulative_quantity", "cumulative_fee", "status", "reason_code")
_BLOB_KEYS = frozenset(("canonical_utf8", "native_witness", "native_inputs", "ledger_native_witness", "event_native_witness"))
_HEAVY_LIMIT = 64 * 1024 * 1024
_HEAVY_ENTRIES = 8
_BENCHMARK_LIMIT = 16 * 1024 * 1024
_BENCHMARK_ENTRIES = 4
_TRACE_LIMIT = 48 * 1024 * 1024
_TRACE_ENTRIES = 4


class _IssuerRecord(NamedTuple):
    reference: weakref.ReferenceType
    facts: tuple[bytes, ...]
    benchmark_digest: bytes | None = None
    corrupt: bool = False
    trace_digest: bytes | None = None


@dataclass(slots=True)
class _BenchmarkEntry:
    reference: weakref.ReferenceType
    values: tuple
    native: bytes
    canonical: tuple[bytes, bytes]
    charge: int
    nodes: int
    process_id: int
    pins: int = 0


class _BenchmarkUse(NamedTuple):
    entry: _BenchmarkEntry
    process_id: int
    work: int
    reference: weakref.ReferenceType


@dataclass(slots=True)
class _TraceEntry:
    reference: weakref.ReferenceType
    facts: tuple
    process_id: int
    schema: str
    semantic: str
    exact: str
    operations: tuple
    checkpoints: tuple
    wire: object
    result: object
    native: bytes
    graph_charge: int
    nodes: int
    charge: int
    work: int
    pins: int = 0


# None of these authority records is reachable through a manifest/cache token.
# Weak references, rather than object IDs alone, bind every lookup to its lifetime.
_ISSUER_LOCK = Condition(RLock())
_ISSUERS: dict[int, _IssuerRecord] = {}
_CONSTRUCTING: dict[int, tuple[weakref.ReferenceType, bool]] = {}
_BENCHMARKS: OrderedDict[int, _BenchmarkEntry] = OrderedDict()
_RETAINED_BYTES = 0
_WORK_BYTES = 0
_WORK_COUNT = 0
_PROCESS_ID = os.getpid()
_TRACES: OrderedDict[int, _TraceEntry] = OrderedDict()
_TRACE_BYTES = 0
_TRACE_WORK_BYTES = 0
_TRACE_WORK_COUNT = 0


def _process() -> int:
    """A child replaces process-local locks before acquiring any inherited lock."""
    global _PROCESS_ID, _ISSUER_LOCK, _ISSUERS, _CONSTRUCTING, _BENCHMARKS, _TRACES
    global _RETAINED_BYTES, _WORK_BYTES, _WORK_COUNT
    global _TRACE_BYTES, _TRACE_WORK_BYTES, _TRACE_WORK_COUNT
    current = os.getpid()
    if type(current) is not int or current <= 0 or type(_PROCESS_ID) is not int:
        _fail()
    if current != _PROCESS_ID:
        retained = {}
        for key, record in tuple(_ISSUERS.items()):
            if type(record) is not _IssuerRecord or type(record.reference) is not weakref.ReferenceType or type(record.corrupt) is not bool:
                _fail()
            if type(record.facts) is not tuple or len(record.facts) != 6 or any(type(fact) is not bytes or len(fact) != 32 for fact in record.facts):
                _fail()
            owner = record.reference()
            if owner is not None:
                if type(owner) is not ReplayManifest or key != id(owner):
                    _fail()
                retained[key] = record._replace(benchmark_digest=None, trace_digest=None)
        _ISSUER_LOCK = Condition(RLock())
        _PROCESS_ID = current
        _ISSUERS, _CONSTRUCTING = retained, {}
        _BENCHMARKS, _TRACES = OrderedDict(), OrderedDict()
        _RETAINED_BYTES = _WORK_BYTES = _WORK_COUNT = 0
        _TRACE_BYTES = _TRACE_WORK_BYTES = _TRACE_WORK_COUNT = 0
    return current


def _remove_entry(entry: _BenchmarkEntry) -> None:
    global _RETAINED_BYTES
    key = id(entry.reference)
    if _BENCHMARKS.get(key) is not entry:
        _fail()
    del _BENCHMARKS[key]
    _RETAINED_BYTES -= entry.charge


def _weak_cleanup(owner_id: int, reference: weakref.ReferenceType) -> None:
    _process()
    if type(owner_id) is not int or type(reference) is not weakref.ReferenceType or reference() is not None:
        return
    _process()
    with _ISSUER_LOCK:
        record = _ISSUERS.get(owner_id)
        if record is not None and record.reference is reference:
            del _ISSUERS[owner_id]
        pending = _CONSTRUCTING.get(owner_id)
        if pending is not None and pending[0] is reference:
            del _CONSTRUCTING[owner_id]
        entry = _BENCHMARKS.get(id(reference))
        if entry is not None:
            _admit_benchmark(entry)
            if entry.reference is reference and entry.pins == 0:
                _remove_entry(entry)
        trace = _TRACES.get(id(reference))
        if trace is not None:
            if type(trace) is not _TraceEntry:
                _fail()
            if type(trace.pins) is not int or type(trace.charge) is not int or trace.pins < 0 or not 0 < trace.charge <= _TRACE_LIMIT:
                _fail()
            if trace.reference is reference and trace.pins == 0:
                _remove_trace(trace)
        _ISSUER_LOCK.notify_all()


def _issuer(owner: ReplayManifest) -> _IssuerRecord:
    _process()
    if type(owner) is not ReplayManifest:
        _fail()
    _process()
    with _ISSUER_LOCK:
        record = _ISSUERS.get(id(owner))
        if type(record) is not _IssuerRecord or type(record.reference) is not weakref.ReferenceType or type(record.corrupt) is not bool:
            _fail()
        if type(record.facts) is not tuple or len(record.facts) != 6 or any(type(fact) is not bytes or len(fact) != 32 for fact in record.facts):
            _fail()
        if any(value is not None and (type(value) is not bytes or len(value) != 32) for value in (record.benchmark_digest, record.trace_digest)):
            _fail()
        if record.reference() is not owner or record.corrupt:
            _fail()
        return record


def _pool_check() -> None:
    if any(type(value) is not int for value in (_RETAINED_BYTES, _WORK_BYTES, _WORK_COUNT, _TRACE_BYTES, _TRACE_WORK_BYTES, _TRACE_WORK_COUNT)):
        _fail()
    if type(_BENCHMARKS) is not OrderedDict or type(_TRACES) is not OrderedDict:
        _fail()
    if len(_BENCHMARKS) + _WORK_COUNT > _BENCHMARK_ENTRIES or _RETAINED_BYTES + _WORK_BYTES > _BENCHMARK_LIMIT:
        _fail()
    if len(_TRACES) + _TRACE_WORK_COUNT > _TRACE_ENTRIES or _TRACE_BYTES + _TRACE_WORK_BYTES > _TRACE_LIMIT:
        _fail()
    if min(_TRACE_BYTES, _TRACE_WORK_BYTES, _TRACE_WORK_COUNT) < 0:
        _fail()
    if min(_RETAINED_BYTES, _WORK_BYTES, _WORK_COUNT) < 0:
        _fail()


def _remove_trace(entry: _TraceEntry) -> None:
    global _TRACE_BYTES
    if _TRACES.get(id(entry.reference)) is not entry:
        _fail()
    del _TRACES[id(entry.reference)]
    _TRACE_BYTES -= entry.charge


def _poison(entry: _BenchmarkEntry) -> None:
    owner = entry.reference()
    if owner is not None:
        record = _ISSUERS.get(id(owner))
        if record is not None and record.reference is entry.reference:
            _ISSUERS[id(owner)] = record._replace(corrupt=True)


def _admit_benchmark(entry: _BenchmarkEntry) -> None:
    if type(entry) is not _BenchmarkEntry or type(entry.reference) is not weakref.ReferenceType:
        _fail()
    if any(type(value) is not int for value in (entry.charge, entry.nodes, entry.pins, entry.process_id)):
        _fail()
    if not 0 < entry.charge <= _BENCHMARK_LIMIT or not 0 < entry.nodes <= 1_000_000 or not 0 <= entry.pins <= _BENCHMARK_ENTRIES or entry.process_id <= 0:
        _fail()
    if type(entry.native) is not bytes or len(entry.native) != 32 or type(entry.canonical) is not tuple or len(entry.canonical) != 2:
        _fail()
    if any(type(raw) is not bytes or len(raw) > _BENCHMARK_LIMIT for raw in entry.canonical) or type(entry.values) is not tuple or len(entry.values) != 2 or any(type(value) is not _bench.BenchmarkSeries for value in entry.values):
        _fail()


def _check_entry(entry: _BenchmarkEntry) -> None:
    _admit_benchmark(entry)
    owner = entry.reference()
    if owner is None:
        _fail()
    record = _issuer(owner)
    if type(entry.native) is not bytes or len(entry.native) > _BENCHMARK_LIMIT or type(entry.canonical) is not tuple or len(entry.canonical) != 2:
        _fail()
    if any(type(raw) is not bytes or len(raw) > _BENCHMARK_LIMIT for raw in entry.canonical):
        _fail()
    if type(entry.charge) is not int or not 0 < entry.charge <= _BENCHMARK_LIMIT or type(entry.nodes) is not int or not 0 < entry.nodes <= 1_000_000 or entry.process_id != _process():
        _fail()
    if record.benchmark_digest != _benchmark_digest(entry.native, entry.canonical, entry.charge, entry.nodes):
        _poison(entry)
        _fail()
    try:
        current, canonical, charge, nodes = _benchmark_measurement(entry.values)
        if (current, canonical, charge, nodes) != (entry.native, entry.canonical, entry.charge, entry.nodes):
            _fail()
    except Exception:
        _poison(entry)
        _fail()


def _evict_one(excluded: int | None = None) -> bool:
    global _WORK_BYTES, _WORK_COUNT
    process_id = _process()
    for key, entry in tuple(_BENCHMARKS.items()):
        _admit_benchmark(entry)
        if type(key) is not int or key != id(entry.reference):
            _fail()
        if key == excluded or entry.pins:
            continue
        if entry.reference() is None:
            _remove_entry(entry)
            return True
        # Verify before eviction: corrupted evidence is never an ordinary miss.
        work = 2 * entry.charge
        if _RETAINED_BYTES + _WORK_BYTES + work > _BENCHMARK_LIMIT or len(_BENCHMARKS) + _WORK_COUNT + 1 > _BENCHMARK_ENTRIES:
            continue
        _WORK_BYTES += work
        _WORK_COUNT += 1
        try:
            _pool_check()
            _check_entry(entry)
            _remove_entry(entry)
            return True
        finally:
            if _process() == process_id:
                _WORK_BYTES -= work
                _WORK_COUNT -= 1
                _ISSUER_LOCK.notify_all()
    return False


def _pin_benchmarks(owner: ReplayManifest) -> _BenchmarkUse | None:
    global _WORK_BYTES, _WORK_COUNT
    _process()
    with _ISSUER_LOCK:
        while True:
            record = _issuer(owner)
            key = id(record.reference)
            entry = _BENCHMARKS.get(key)
            if entry is None:
                return None
            _admit_benchmark(entry)
            if entry.pins > _WORK_COUNT:
                _fail()
            if entry.reference is not record.reference or entry.reference() is not owner:
                _fail()
            work = 2 * entry.charge
            if _RETAINED_BYTES + _WORK_BYTES + work <= _BENCHMARK_LIMIT and len(_BENCHMARKS) + _WORK_COUNT + 1 <= _BENCHMARK_ENTRIES:
                entry.pins += 1
                _WORK_BYTES += work
                _WORK_COUNT += 1
                _BENCHMARKS.move_to_end(key)
                _pool_check()
                return _BenchmarkUse(entry, _PROCESS_ID, work, record.reference)
            if not _evict_one(key):
                if not _WORK_COUNT:
                    _fail()  # Every retained entry was admitted with usable workspace.
                return None  # No retained proof is consumed without workspace.


def _unpin_benchmarks(use: _BenchmarkUse) -> None:
    global _WORK_BYTES, _WORK_COUNT
    entry = use.entry
    if _process() != use.process_id:
        return  # An inherited in-flight reader owns no child reservation.
    _process()
    with _ISSUER_LOCK:
        _pool_check()
        if _BENCHMARKS.get(id(use.reference)) is not entry:
            _fail()
        # Cleanup uses the immutable reservation, even if verification detected
        # corrupt mutable entry metadata. No corrupted arithmetic runs here.
        entry.pins = max(0, entry.pins - 1) if type(entry.pins) is int else 0
        _WORK_BYTES -= use.work
        _WORK_COUNT -= 1
        if entry.pins == 0 and use.reference() is None:
            _remove_entry(entry)
        _pool_check()
        _ISSUER_LOCK.notify_all()


def _reserve_benchmark_build(owner: ReplayManifest) -> bool:
    global _WORK_BYTES, _WORK_COUNT
    _process()
    with _ISSUER_LOCK:
        while True:
            record = _issuer(owner)
            if id(record.reference) in _BENCHMARKS:
                return False
            # A cold builder reserves the complete worst-case evidence budget.
            # This deliberately favours boundedness over concurrent cold builds.
            if _RETAINED_BYTES + _WORK_BYTES == 0 and _WORK_COUNT == 0:
                _WORK_BYTES = _BENCHMARK_LIMIT
                _WORK_COUNT = 1
                _pool_check()
                return True
            if not _evict_one():
                return False  # Optional collection never waits on an active reader.


def _release_benchmark_build(process_id: int) -> None:
    global _WORK_BYTES, _WORK_COUNT
    if _process() != process_id:
        return
    _process()
    with _ISSUER_LOCK:
        _WORK_BYTES -= _BENCHMARK_LIMIT
        _WORK_COUNT -= 1
        _pool_check()
        _ISSUER_LOCK.notify_all()


class _CacheCapacity(Exception):
    pass


class ReplayInputError(ValueError):
    """A fixed diagnostic never reflects untrusted input or a nested exception."""

    def __init__(self) -> None:
        super().__init__("BT-05 replay rejected")


def _fail() -> None:
    raise ReplayInputError() from None


def _tuple(value: object, maximum: int = 4096) -> tuple:
    if type(value) is not tuple or len(value) > maximum:
        _fail()
    return value


def _text(value: object, maximum: int = 65536) -> str:
    if type(value) is not str or len(value) > maximum:
        _fail()
    try:
        if len(value.encode("utf-8")) > maximum:
            _fail()
    except UnicodeError:
        _fail()
    return value


def _decimal(value: object) -> str:
    if type(value) is not Decimal or not value.is_finite():
        _fail()
    sign, digits, exponent = value.as_tuple()
    if type(exponent) is not int or len(digits) > 128 or not -64 <= exponent <= 64:
        _fail()
    if value.copy_abs() > Decimal("1E64"):
        _fail()
    if not any(digits):
        return "0"
    coefficient = "".join(str(digit) for digit in digits)
    point = len(coefficient) + exponent
    if point <= 0:
        result = "0." + "0" * -point + coefficient
    elif point >= len(coefficient):
        result = coefficient + "0" * (point - len(coefficient))
    else:
        result = coefficient[:point] + "." + coefficient[point:]
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return ("-" if sign else "") + result


def _time(value: object) -> str:
    if type(value) is not datetime or object.__getattribute__(value, "tzinfo") is not timezone.utc:
        _fail()
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value: object, maximum: int = MAX_RECORD) -> bytes:
    _json_admission(value, maximum)
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        _fail()
    if len(raw) > maximum:
        _fail()
    return raw


def _json_admission(value: object, maximum: int) -> int:
    stack, active, nodes, size = [(value, 0, False)], set(), 0, 0
    while stack:
        item, depth, leaving = stack.pop()
        kind = type(item)
        if leaving:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > 1_000_000 or depth > 64:
            _fail()
        if item is None or kind is bool:
            size += 4 if item is None or item is True else 5
        elif kind is int:
            if item.bit_length() > 256:
                _fail()
            size += len(str(item))
        elif kind is str:
            if len(item) > maximum:
                _fail()
            try:
                encoded = item.encode("utf-8")
            except UnicodeError:
                _fail()
            size += len(encoded) + 2
            size += sum(1 if byte in (34, 92, 8, 9, 10, 12, 13) else 5 if byte < 32 else 0 for byte in encoded)
        elif kind is dict or kind is list or kind is tuple:
            if id(item) in active or len(item) > (128 if kind is dict else 4096):
                _fail()
            active.add(id(item))
            stack.append((item, depth, True))
            size += 2 + max(0, len(item) * (2 if kind is dict else 1) - 1)
            if kind is dict:
                if any(type(key) is not str for key in dict.keys(item)):
                    _fail()
                for key, child in dict.items(item):
                    stack.extend(((key, depth + 1, False), (child, depth + 1, False)))
            else:
                stack.extend((child, depth + 1, False) for child in item)
        else:
            _fail()
        if size > maximum:
            _fail()
    return size


def _unique(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _decode(raw: object, maximum: int = MAX_RECORD) -> object:
    """Bound raw bytes and nesting before the duplicate-aware JSON decoder."""
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        _fail()
    depth, quoted, escaped = 0, False, False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 64:
                _fail()
        elif byte in (93, 125):
            depth -= 1
            if depth < 0:
                _fail()
    if quoted or depth:
        _fail()
    _lexical_limits(raw, maximum)
    try:
        value = json.loads(raw, object_pairs_hook=_unique,
                           parse_float=lambda _: _fail(), parse_constant=lambda _: _fail())
    except (ValueError, UnicodeError, RecursionError):
        _fail()
    stack, nodes = [(value, 0, None)], 0
    while stack:
        item, level, name = stack.pop()
        nodes += 1
        if nodes > 1_000_000 or level > 64:
            _fail()
        kind = type(item)
        if kind is dict:
            if len(item) > 128:
                _fail()
            for key, child in item.items():
                _text(key)
                stack.append((child, level + 1, key))
        elif kind is list:
            if len(item) > 4096:
                _fail()
            stack.extend((child, level + 1, None) for child in item)
        elif kind is str:
            _text(item, maximum if name in _BLOB_KEYS else 65536)
        elif kind is int:
            if item.bit_length() > 256:
                _fail()
        elif item is not None and kind is not bool:
            _fail()
    if _json(value, maximum) != raw:
        _fail()
    return value


def _lexical_limits(raw: bytes, maximum: int) -> None:
    """Admit tokens and collection cardinality before allocating decoded JSON."""
    frames, nodes, offset = [], 0, 0
    length = len(raw)
    while offset < length:
        byte = raw[offset]
        if byte in (9, 10, 13, 32):
            offset += 1
            continue
        frame = frames[-1] if frames else None
        if byte == 44:
            if frame is not None:
                frame[2] = True
                if frame[0] == 123:
                    frame[3] = None
            offset += 1
            continue
        if byte == 58:
            if frame is not None:
                frame[1] += 1
                if frame[0] != 123 or frame[1] > 128:
                    _fail()
                frame[2] = True
            offset += 1
            continue
        if byte in (93, 125):
            if not frames:
                _fail()
            frames.pop()
            offset += 1
            continue
        is_key = frame is not None and frame[0] == 123 and frame[3] is None and byte == 34
        if frame is not None and frame[0] == 91 and frame[2]:
            frame[1] += 1
            frame[2] = False
            if frame[1] > 4096:
                _fail()
        nodes += 1
        if nodes > 1_000_000:
            _fail()
        if byte in (91, 123):
            frames.append([byte, 0, True, None])
            if len(frames) > 64:
                _fail()
            offset += 1
        elif byte == 34:
            start = offset
            offset += 1
            escaped = False
            while offset < length:
                current = raw[offset]
                offset += 1
                if escaped:
                    escaped = False
                elif current == 92:
                    escaped = True
                elif current == 34:
                    break
            else:
                _fail()
            owner = None if frame is None else frame[3]
            limit = maximum if not is_key and owner in _BLOB_KEYS else 6 * 65536 + 2
            if offset - start > limit:
                _fail()
            if is_key:
                try:
                    key = json.loads(raw[start:offset])
                except (ValueError, UnicodeError):
                    _fail()
                _text(key)
                frame[3] = key
        else:
            start = offset
            while offset < length and raw[offset] not in (9, 10, 13, 32, 44, 93, 125, 58):
                offset += 1
            if offset == start or offset - start > 80:
                _fail()


def _hash(domain: bytes, raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(domain + raw).hexdigest()


def _ref(kind: str, value: object) -> str:
    return _hash(REFERENCE_DOMAIN, _json({"type": kind, "value": value}))


class _Budget:
    __slots__ = ("nodes", "bytes", "active")

    def __init__(self) -> None:
        self.nodes, self.bytes, self.active = 0, 0, set()

    def charge(self, size: int) -> None:
        self.bytes += size
        if self.bytes > MAX_RECORD:
            _fail()

    def string(self, value: str) -> None:
        self.charge(len(value.encode("utf-8")))


class _CacheBudget(_Budget):
    __slots__ = ()

    def charge(self, size: int) -> None:
        self.bytes += size
        if self.bytes > _BENCHMARK_LIMIT:
            raise _CacheCapacity()

    def string(self, value: str) -> None:
        # Private cache copies admit the widest built-in Unicode storage and
        # its temporary UTF-8 encoding. Public native admission is unchanged.
        self.charge(8 * len(value))


def _cache_native_digest(tree: object, budget: _Budget) -> bytes:
    _json_admission(tree, MAX_RECORD)
    stack, longest = [tree], 0
    while stack:
        value = stack.pop()
        if type(value) is str:
            longest = max(longest, len(value))
        elif type(value) is dict:
            stack.extend(value.keys())
            stack.extend(value.values())
        elif type(value) is list or type(value) is tuple:
            stack.extend(value)
    # An encoded string chunk has at most six characters per input character;
    # charge its widest str storage, UTF-8 copy and bounded encoder frames.
    budget.charge(32 * longest + 4096)
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(tree):
        digest.update(chunk.encode("utf-8"))
    return digest.digest()


def _benchmark_digest(native: bytes, canonical: tuple, charge: int, nodes: int) -> bytes:
    digest = hashlib.sha256(b"bt05-private-benchmark-v2\0")
    digest.update(_json((charge, nodes)))
    for raw in (native, *canonical):
        digest.update(hashlib.sha256(raw).digest())
    return digest.digest()


def _benchmark_measurement(values: tuple) -> tuple[bytes, tuple, int, int]:
    if type(values) is not tuple or len(values) != 2 or any(type(value) is not _bench.BenchmarkSeries for value in values):
        _fail()
    budget = _CacheBudget()
    tree = _native(values, budget)
    canonical = tuple(object.__getattribute__(value, "_canonical") for value in values)
    if any(type(raw) is not bytes or len(raw) > MAX_RECORD for raw in canonical):
        _fail()
    budget.charge(sum(len(raw) for raw in canonical) + 128)
    native = _cache_native_digest(tree, budget)
    return native, canonical, budget.bytes, budget.nodes


def _verify_origin(owner: ReplayManifest, facts: tuple) -> None:
    if type(owner) is not ReplayManifest or type(facts) is not tuple or len(facts) != 6:
        _fail()
    if any(type(fact) is not bytes or len(fact) != 32 for fact in facts):
        _fail()
    raw = tuple(object.__getattribute__(owner, name) for name in ("_native", "_owned_native", "_semantic", "_canonical"))
    if any(type(value) is not bytes or len(value) > MAX_RECORD for value in raw):
        _fail()
    integrity = object.__getattribute__(owner, "_integrity")
    if type(integrity) is not bytes or len(integrity) != 32:
        _fail()
    original = _source_capture(object.__getattribute__(owner, "_original"))
    owned = _source_capture(object.__getattribute__(owner, "_owned"))
    if original != raw[0] or owned != raw[1]:
        _fail()
    measured = (*tuple(hashlib.sha256(value).digest() for value in raw),
                hashlib.sha256(_json(object.__getattribute__(owner, "_operations"))).digest(),
                hashlib.sha256(owner._cache_bytes()).digest())
    if measured != facts or integrity != facts[5]:
        _fail()


def _copy_benchmark_entry(owner: ReplayManifest, use: _BenchmarkUse) -> tuple:
    entry = use.entry
    try:
        owner._refresh()
        _process()
        with _ISSUER_LOCK:
            if entry.reference() is not owner:
                _fail()
            _check_entry(entry)
        values = tuple(_actions._clone_value(value) for value in entry.values)
        if _benchmark_measurement(values) != (entry.native, entry.canonical, entry.charge, entry.nodes):
            _fail()
        _process()
        with _ISSUER_LOCK:
            _check_entry(entry)
        owner._refresh()
        return values
    except Exception:
        _process()
        with _ISSUER_LOCK:
            _poison(entry)
        _fail()
    finally:
        _unpin_benchmarks(use)


def _native(value: object, budget: _Budget | None = None, depth: int = 0) -> object:
    """Copy exact known native storage, including representation and source seals."""
    budget = _Budget() if budget is None else budget
    budget.nodes += 1
    budget.charge(256)  # Covers generated tags, field names and JSON punctuation.
    if budget.nodes > 1_000_000 or depth > 64:
        _fail()
    kind = type(value)
    if value is None or kind is bool:
        return value
    if kind is str:
        text = _text(value)
        budget.string(text)
        return text
    if kind is int:
        if value.bit_length() > 256:
            _fail()
        return ["int", value]
    if kind is Decimal:
        _decimal(value)
        sign, digits, exponent = value.as_tuple()
        return ["Decimal", sign, list(digits), exponent]
    if kind is datetime:
        return ["datetime", _time(value)]
    if kind is date:
        return ["date", value.isoformat()]
    if kind is bytes:
        if len(value) > MAX_SOURCES:
            _fail()
        budget.charge(len(value))
        return ["bytes", len(value), hashlib.sha256(value).hexdigest()]
    if any(kind is enum for enum in _clock._ENUM_TYPES):
        if not any(value is member for member in kind.__members__.values()):
            _fail()
        return ["enum", kind.__name__, _native(object.__getattribute__(value, "_value_"), budget, depth + 1)]
    if kind is tuple:
        _tuple(value)
        identity = id(value)
        if identity in budget.active:
            _fail()
        budget.active.add(identity)
        try:
            return ["tuple", [_native(item, budget, depth + 1) for item in value]]
        finally:
            budget.active.remove(identity)
    if any(kind is model for model in _MODELS):
        fields = _MODEL_FIELDS[kind]
        data = object.__getattribute__(value, "__dict__")
        extra = object.__getattribute__(value, "__pydantic_extra__")
        private = object.__getattribute__(value, "__pydantic_private__")
        marked = object.__getattribute__(value, "__pydantic_fields_set__")
        if type(data) is not dict or len(data) != len(fields) or extra is not None or private is not None or type(marked) is not set:
            _fail()
        keys = tuple(dict.keys(data))
        if set.__len__(marked) > 128:
            _fail()
        marks = tuple(set.__iter__(marked))
        if any(type(key) is not str for key in (*keys, *marks)):
            _fail()
        if any(key not in fields for key in (*keys, *marks)) or len(marks) > 128:
            _fail()
        identity = id(value)
        if identity in budget.active:
            _fail()
        budget.active.add(identity)
        try:
            return [kind.__name__, sorted(marks), {name: _native(dict.__getitem__(data, name), budget, depth + 1) for name in fields}]
        finally:
            budget.active.remove(identity)
    slots = None
    if kind is _clock.SessionBinding:
        slots = ("_context_snapshot", "_bundle_snapshot", "_envelope_snapshot", "_session_snapshot", "_next_session_snapshot",
                 "_sealed_source_json", "_source_fingerprint", "_sealed_storage_bytes")
    elif kind is _fills.OutcomeEvidence:
        slots = _fills.OutcomeEvidence.__slots__
    elif kind is _nav.EligibleMark or kind is _nav.AccountingPolicy:
        slots = kind.__slots__
    elif any(kind is model for model in _VALUES):
        data = object.__getattribute__(value, "_data")
        if type(data) is not tuple or len(data) != len(_VALUE_FIELDS[kind]):
            _fail()
        slots = ("_data", "_canonical", "_storage")
    elif kind is _nav.NAVResult:
        slots = _NAV_FIELDS
    elif kind is SimOrder:
        slots = _ORDER_FIELDS
    elif kind is _ledger.ObligationBalance:
        slots = ("obligation_id", "kind", "amount_created", "amount_remaining", "due_at", "economic_time")
    elif kind is _ledger.IntentOwnership:
        slots = ("intent_id", "intent_hash", "instrument_id", "side", "quantity", "cumulative_quantity", "cumulative_fee",
                 "policy_version", "fee_policy_id", "fixed_share_cap", "last_session_date", "terminal", "time_in_force", "fill_ids")
    elif kind is _ledger.SessionCapOwnership:
        slots = ("instrument_id", "session_date", "filled_quantity", "fixed_share_cap", "policy_version", "fee_policy_id")
    elif kind is _ledger.LedgerEvent or kind is _ledger.LedgerBalance:
        slots = kind.__slots__
    if slots is not None:
        identity = id(value)
        if identity in budget.active:
            _fail()
        budget.active.add(identity)
        try:
            return [kind.__name__, {name: _native(object.__getattribute__(value, name), budget, depth + 1) for name in slots}]
        finally:
            budget.active.remove(identity)
    _fail()


def _source_capture(fields: dict) -> bytes:
    if type(fields) is not dict or len(fields) != len(_FIELDS):
        _fail()
    keys = tuple(dict.keys(fields))
    if any(type(key) is not str for key in keys) or any(key not in _FIELDS for key in keys):
        _fail()
    budget = _Budget()
    tree = {name: _native(fields[name], budget) for name in _FIELDS}
    return _encode_native(tree)


def _encode_native(tree: object) -> bytes:
    """Encode only the fresh built-in tree produced by bounded native admission."""
    # Callers supply _native output, never a caller object or a restored graph.
    raw = json.dumps(tree, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_RECORD:
        _fail()
    return raw


def _owned_source(value: object) -> object:
    try:
        if type(value) is tuple:
            return tuple(_owned_source(item) for item in value)
        if type(value) is _fills.OutcomeEvidence:
            return _ledger._outcome_from_state(_fills._refresh_outcome(value))
        return _actions._part(value, validate=True)[0]
    except Exception:
        _fail()


def _mget(manifest: ReplayManifest, name: str) -> object:
    data = object.__getattribute__(manifest, "_owned")
    if type(data) is not dict or len(data) != len(_FIELDS):
        _fail()
    keys = tuple(dict.keys(data))
    if any(type(key) is not str for key in keys) or any(key not in _FIELDS for key in keys):
        _fail()
    return dict.__getitem__(data, name)


class _Projection:
    """Only these exact, typed v1 records may change declared identity fields."""

    __slots__ = ("manifest", "refs", "bindings", "exact_bindings", "intents", "outcomes", "exact_outcomes", "policy", "prefixes", "fill_refs")

    def __init__(self, manifest: ReplayManifest) -> None:
        self.manifest, self.refs, self.bindings, self.intents, self.outcomes = manifest, {}, {}, {}, {}
        self.exact_bindings, self.exact_outcomes = {}, {}
        self.prefixes, self.fill_refs = {}, {}
        for binding in _mget(manifest, "bindings"):
            self.binding(binding)
        # Marks and benchmark members can hold independently sealed bindings.
        for item in _mget(manifest, "sessions"):
            for mark in _actions._get(item, "marks"):
                self.binding(object.__getattribute__(mark, "_binding"))
            self.binding(object.__getattribute__(_actions._get(item, "accounting_policy"), "_binding"))
        bh = _mget(manifest, "buy_and_hold_policy")
        for member in _actions._get(bh, "members"):
            self.binding(_actions._get(member, "binding"))
        self.policy = self.model(_mget(manifest, "cost_policy"))
        cost = _mget(manifest, "cost_policy")
        self.refs[("cost", cost.policy_hash)] = _ref("CostPolicy", self.policy)
        for intent in (*_mget(manifest, "intents"), *tuple(_actions._get(member, "intent") for member in _actions._get(bh, "members"))):
            self.intent(intent)
        for outcome in _mget(manifest, "outcomes"):
            self.outcome(outcome)
        for item in _mget(manifest, "sessions"):
            for mark in _actions._get(item, "marks"):
                self.outcome(object.__getattribute__(mark, "_outcome"))
            for source in (*_actions._get(item, "actions"), *_actions._get(item, "mergers")):
                key = hashlib.sha256(object.__getattribute__(source, "_canonical") + object.__getattribute__(source, "_storage")).hexdigest()
                self.refs[("action_source", key)] = _ref(type(source).__name__, self.value(source))

    def model(self, value: object) -> dict:
        kind = type(value)
        if not any(kind is model for model in _MODELS):
            _fail()
        if kind is SignalEnvelope:
            fields = {name: object.__getattribute__(value, name) for name in _MODEL_FIELDS[kind]}
            # Dependencies are projected before their derived references.
            quant = self.model(fields["quant"])
            note = None if fields["note"] is None else self.model(fields["note"])
            overlay = None if fields["overlay"] is None else self.model(fields["overlay"])
            result = {name: self.value(item) for name, item in fields.items() if name not in ("envelope_id", "quant", "note", "overlay")}
            result.update(quant=quant, note=note, overlay=overlay)
            result["envelope_id"] = _ref("SignalEnvelope", result)
            self.refs[("envelope", fields["envelope_id"])] = result["envelope_id"]
            return result
        omitted = {
            RunContext: ("run_id",), EvidenceBundle: ("created_at",),
            QuantSignal: ("run_id", "signal_id"),
            ResearchNote: ("run_id", "note_id", "response_id", "response_hash"),
            LLMOverlay: ("run_id", "overlay_id", "note_id", "note_hash", "quant_signal_id"),
            OrderIntent: ("run_id", "intent_id"), Fill: ("run_id", "fill_id"),
        }.get(kind, ())
        result = {name: self.value(object.__getattribute__(value, name)) for name in _MODEL_FIELDS[kind] if name not in omitted}
        if kind is QuantSignal:
            result["signal_id"] = _ref("QuantSignal", result)
            self.refs[("quant", value.signal_id)] = result["signal_id"]
        elif kind is ResearchNote:
            result["note_id"] = _ref("ResearchNote", result)
            self.refs[("note", value.note_id)] = result["note_id"]
            self.refs[("note_hash", value.note_hash)] = result["note_id"]
        elif kind is LLMOverlay:
            result.update(note_id=self.reference("note", value.note_id), note_hash=self.reference("note_hash", value.note_hash),
                          quant_signal_id=self.reference("quant", value.quant_signal_id))
            result["overlay_id"] = _ref("LLMOverlay", result)
        elif kind is OrderIntent or kind is Fill:
            for field, reference in (("decision_event_id", "decision"), ("envelope_id", "envelope"), ("source_fingerprint", "binding")):
                result[field] = self.reference(reference, object.__getattribute__(value, field))
            if kind is OrderIntent:
                result["intent_id"] = _ref("OrderIntent", result)
                self.refs[("intent", value.intent_id)] = result["intent_id"]
                self.refs[("intent_hash", value.intent_hash)] = result["intent_id"]
            else:
                result["intent_id"] = self.reference("intent", value.intent_id)
                result["intent_hash"] = self.reference("intent_hash", value.intent_hash)
                result["outcome_hash"] = self.reference("outcome", value.outcome_hash)
                result["cost_policy_hash"] = self.reference("cost", value.cost_policy_hash)
                result["fill_id"] = _ref("Fill", result)
                self.fill_refs[value.fill_id] = result["fill_id"]
        return result

    def reference(self, kind: str, identifier: str) -> str:
        result = self.refs.get((kind, identifier))
        if result is None:
            _fail()
        return result

    def binding(self, binding: _clock.SessionBinding) -> dict:
        exact = object.__getattribute__(binding, "_source_fingerprint")
        if exact in self.bindings:
            return self.bindings[exact]
        context = object.__getattribute__(binding, "_context_snapshot")
        result = {"context": self.model(context), "bundle": self.model(object.__getattribute__(binding, "_bundle_snapshot")),
                  "envelope": self.model(object.__getattribute__(binding, "_envelope_snapshot")),
                  "session": self.model(object.__getattribute__(binding, "_session_snapshot")),
                  "next_session": self.model(object.__getattribute__(binding, "_next_session_snapshot"))}
        semantic = _ref("SessionBinding", result)
        self.refs[("binding", exact)] = semantic
        source = object.__getattribute__(binding, "_sealed_source_json")
        native = object.__getattribute__(binding, "_sealed_storage_bytes")
        self.refs[("position_binding", hashlib.sha256(source + native).hexdigest())] = semantic
        decision = BacktestRunner().run((binding,))[0]
        self.refs[("decision", decision.event_id)] = _ref("DecisionEvent", {"binding": semantic, "decision_time": _time(context.decision_time)})
        self.bindings[exact] = result
        self.exact_bindings[exact] = binding
        return result

    def intent(self, intent: OrderIntent) -> dict:
        result = self.model(intent)
        self.intents[intent.intent_id] = result
        return result

    def outcome(self, outcome: _fills.OutcomeEvidence) -> dict:
        result = {"bar": self.model(object.__getattribute__(outcome, "_bar_snapshot")),
                  "outcome_cutoff": _time(object.__getattribute__(outcome, "_outcome_cutoff")),
                  "archive_cutoff": _time(object.__getattribute__(outcome, "_archive_cutoff")),
                  "replay_policy": self.value(object.__getattribute__(outcome, "_replay_policy"))}
        exact = object.__getattribute__(outcome, "_outcome_hash")
        self.refs[("outcome", exact)] = _ref("OutcomeEvidence", result)
        self.outcomes[exact] = result
        self.exact_outcomes[exact] = outcome
        return result

    def value(self, value: object) -> object:
        kind = type(value)
        if value is None or kind is bool or kind is str or kind is int:
            return value
        if kind is Decimal:
            return _decimal(value)
        if kind is datetime:
            return _time(value)
        if kind is date:
            return value.isoformat()
        if kind is tuple:
            return [self.value(item) for item in value]
        if any(kind is enum for enum in _clock._ENUM_TYPES):
            return object.__getattribute__(value, "_value_")
        if any(kind is model for model in _MODELS):
            return self.model(value)
        if kind is _clock.SessionBinding:
            return self.binding(value)
        if kind is _fills.OutcomeEvidence:
            return self.outcome(value)
        if kind is _nav.EligibleMark:
            return {"binding": self.binding(object.__getattribute__(value, "_binding")),
                    "outcome": self.outcome(object.__getattribute__(value, "_outcome"))}
        if kind is _nav.AccountingPolicy:
            return {"binding": self.binding(object.__getattribute__(value, "_binding")),
                    **{name: self.value(object.__getattribute__(value, "_" + name)) for name in
                       ("session_date", "valuation_cutoff", "archive_cutoff", "currency", "mark_source", "mark_revision")}}
        if any(kind is model for model in _VALUES):
            result = {name: self.value(_actions._get(value, name)) for name in _VALUE_FIELDS[kind]
                      if not (kind is _bench.BenchmarkCommonPolicy and name == "run_id")
                      and not (kind is _actions.PositionReference and name in ("run_id", "binding_hash"))
                      and not (kind is _actions._ActionBatch and name == "prior_balance")
                      and not (kind is _actions._ActionState and name in ("calendar_bytes", "policy_bytes"))}
            if kind is _actions.PositionReference:
                result["binding_hash"] = self.reference("position_binding", _actions._get(value, "binding_hash"))
            if kind is _actions._Cancellation:
                result["intent_id"] = self.reference("intent", _actions._get(value, "intent_id"))
            if kind is _actions._Applied:
                result["source_hash"] = self.reference("action_source", _actions._get(value, "source_hash"))
            if kind is _actions._ActionBatch:
                result["outstanding_intents"].sort(key=lambda item: item["intent_id"])
            if kind is _actions._ActionState:
                result["cancelled_intents"].sort(key=lambda item: item["fields"]["intent_id"])
                # These fields encode known, already verified typed policies.
                result["calendar"] = self.model(_actions._get(_actions._get(_mget(self.manifest, "cash_benchmark_policy"), "common"), "calendar"))
                result["policy"] = self.value(_mget(self.manifest, "action_policy"))
            return {"type": kind.__name__, "fields": result}
        _fail()


class ReplayManifest:
    """Immutable exact-type manifest; all economic policies are explicit."""

    __slots__ = ("_original", "_owned", "_native", "_owned_native", "_semantic", "_canonical", "_operations", "_integrity", "__weakref__")

    def __new__(cls, **_: object) -> ReplayManifest:
        if cls is not ReplayManifest:
            _fail()
        owner = object.__new__(cls)
        owner_id = id(owner)
        reference = weakref.ref(owner, lambda reference, owner_id=owner_id: _weak_cleanup(owner_id, reference))
        _process()
        with _ISSUER_LOCK:
            old = _ISSUERS.get(owner_id)
            if old is not None:
                if old.reference() is not None:
                    _fail()
                _weak_cleanup(owner_id, old.reference)
            _CONSTRUCTING[owner_id] = (reference, False)
        return owner

    def __init__(self, **fields: object) -> None:
        _process()
        with _ISSUER_LOCK:
            pending = _CONSTRUCTING.get(id(self))
            if type(self) is not ReplayManifest or id(self) in _ISSUERS or pending is None or pending[0]() is not self or pending[1]:
                _fail()
            reference = pending[0]
            _CONSTRUCTING[id(self)] = (reference, True)
        try:
            facts = self._initialize(fields)
            _verify_origin(self, facts)
            _process()
            with _ISSUER_LOCK:
                current = _CONSTRUCTING.get(id(self))
                if current is None or current[0] is not reference or not current[1] or id(self) in _ISSUERS:
                    _fail()
                # Only this completed constructor path issues origin authority.
                _ISSUERS[id(self)] = _IssuerRecord(reference, facts)
                del _CONSTRUCTING[id(self)]
        except BaseException:
            _process()
            with _ISSUER_LOCK:
                current = _CONSTRUCTING.get(id(self))
                if current is not None and current[0] is reference:
                    del _CONSTRUCTING[id(self)]
            raise

    def _initialize(self, fields: dict) -> tuple[bytes, ...]:
        _process()
        with _ISSUER_LOCK:
            pending = _CONSTRUCTING.get(id(self))
            if id(self) in _ISSUERS or pending is None or pending[0]() is not self or not pending[1]:
                _fail()
        if type(self) is not ReplayManifest or len(fields) != len(_FIELDS) or any(type(name) is not str for name in fields):
            _fail()
        if any(name not in _FIELDS for name in fields):
            _fail()
        limits = (("bindings", 256, _clock.SessionBinding), ("intents", 256, OrderIntent),
                  ("outcomes", 4096, _fills.OutcomeEvidence), ("sessions", 16, _bench.BenchmarkSessionInput))
        for name, maximum, expected in limits:
            values = _tuple(fields[name], maximum)
            if any(type(value) is not expected for value in values):
                _fail()
        for name, expected in (("cost_policy", CostPolicy), ("action_policy", _actions.ActionPolicy),
                               ("cash_benchmark_policy", _bench.CashBenchmarkPolicy), ("buy_and_hold_policy", _bench.BuyAndHoldPolicy)):
            if type(fields[name]) is not expected:
                _fail()
        for name in ("schema_version", "run_id", "correlation_id", "code_version", "config_version", "model_version", "priority_policy"):
            _text(fields[name])
        if fields["schema_version"] != "v1" or fields["priority_policy"] != PRIORITY:
            _fail()
        if not fields["bindings"] or not fields["sessions"]:
            _fail()
        for name in ("seed", "start_sequence"):
            if type(fields[name]) is not int or fields[name] < 0 or fields[name].bit_length() > 256:
                _fail()
        _decimal(fields["opening_cash"])
        for name in ("created_at", "opening_time", "resolution_cutoff"):
            _time(fields[name])
        configuration = _tuple(fields["configuration"])
        for pair in configuration:
            if len(_tuple(pair, 2)) != 2:
                _fail()
            _text(pair[0])
            _text(pair[1])
        if tuple(sorted(configuration)) != configuration or len({pair[0] for pair in configuration}) != len(configuration):
            _fail()
        native = _source_capture(fields)  # Complete native admission precedes callbacks or equality.
        owned = {name: _owned_source(fields[name]) if name in _ROOTS else fields[name] for name in _FIELDS}
        object.__setattr__(self, "_original", dict(fields))
        object.__setattr__(self, "_owned", owned)
        object.__setattr__(self, "_native", native)
        owned_native = _source_capture(owned)
        object.__setattr__(self, "_owned_native", owned_native)
        self._validate()
        projection = _Projection(self)
        operations = self._plan(projection)
        object.__setattr__(self, "_operations", operations)
        semantic = {name: projection.value(owned[name]) for name in _FIELDS
                    if name not in ("run_id", "correlation_id", "created_at", "bindings", "intents", "outcomes")}
        semantic["bindings"] = sorted((projection.binding(value) for value in owned["bindings"]), key=lambda value: _ref("SessionBinding", value))
        semantic["intents"] = sorted((projection.intents[value.intent_id] for value in owned["intents"]), key=lambda value: value["intent_id"])
        semantic["outcomes"] = sorted((projection.outcomes[object.__getattribute__(value, "_outcome_hash")] for value in owned["outcomes"]), key=lambda value: _ref("OutcomeEvidence", value))
        semantic.update(serialization_version=SERIALIZATION, numeric_policy_version="bt02-decimal-v1", operations=operations)
        semantic_raw = _json(semantic)
        object.__setattr__(self, "_semantic", semantic_raw)
        exact_sources, total = [], 0
        for name in _ROOTS:
            roots = owned[name] if name in ("bindings", "intents", "outcomes", "sessions") else (owned[name],)
            for source in roots:
                if type(source) is _clock.SessionBinding:
                    raw = object.__getattribute__(source, "_sealed_source_json")
                    witness = object.__getattribute__(source, "_sealed_storage_bytes")
                elif type(source) is _fills.OutcomeEvidence:
                    raw = _fills._refresh_outcome(source)[4]
                    witness = _json(_native(source))
                else:
                    parts = _actions._part(source)
                    raw = parts[1].encode("utf-8") if type(parts[1]) is str else _json(parts[1])
                    witness = _json(_native(source))
                if len(raw) > MAX_SOURCE:
                    _fail()
                total += len(raw) + len(witness)
                if total > MAX_SOURCES:
                    _fail()
                exact_sources.append({"source_type": type(source).__name__, "canonical_utf8": raw.decode("utf-8"), "native_witness": witness.hex()})
        canonical = {"schema_version": "v1", "serialization_version": SERIALIZATION, "priority_policy": PRIORITY,
                     "semantic_input": semantic, "operational": {name: projection.value(owned[name]) for name in ("run_id", "correlation_id", "created_at")},
                     "exact_sources": exact_sources, "native_inputs": native.hex()}
        canonical_raw = _json(canonical)
        object.__setattr__(self, "_canonical", canonical_raw)
        integrity = hashlib.sha256(self._cache_bytes()).digest()
        object.__setattr__(self, "_integrity", integrity)
        return (*tuple(hashlib.sha256(value).digest() for value in (native, owned_native, semantic_raw, canonical_raw)),
                hashlib.sha256(_json(operations)).digest(), integrity)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ReplayManifest is immutable")

    def _refresh(self) -> None:
        record = _issuer(self)
        _verify_origin(self, record.facts)

    def _cache_bytes(self) -> bytes:
        operations = _tuple(object.__getattribute__(self, "_operations"), MAX_OPERATIONS)
        for row in operations:
            if len(_tuple(row, 4)) != 4 or type(row[0]) is not int or type(row[1]) is not str or type(row[2]) is not str or (row[3] is not None and type(row[3]) is not str):
                _fail()
        return _json({"records": [hashlib.sha256(object.__getattribute__(self, name)).hexdigest()
                                  for name in ("_native", "_owned_native", "_semantic", "_canonical")], "operations": operations})

    def _validate(self) -> None:
        bindings, sessions = _mget(self, "bindings"), _mget(self, "sessions")
        BacktestRunner().run(bindings)
        data = tuple(_fills._binding_data(binding)[0] for binding in bindings)
        run = _mget(self, "run_id")
        common = _actions._get(_mget(self, "cash_benchmark_policy"), "common")
        bh_common = _actions._get(_mget(self, "buy_and_hold_policy"), "common")
        if _actions._part(common)[2] != _actions._part(bh_common)[2]:
            _fail()
        calendar = _actions._get(common, "calendar")
        if any(item.context.run_id != run or item.calendar.calendar_id != calendar.calendar_id for item in data):
            _fail()
        first = data[0]
        group = (first.context.run_id, first.calendar.calendar_id, first.context.variant_id, first.context.base_currency,
                 first.bundle.replay_policy, first.calendar_fingerprint)
        if any((item.context.run_id, item.calendar.calendar_id, item.context.variant_id, item.context.base_currency,
                item.bundle.replay_policy, item.calendar_fingerprint) != group for item in data):
            _fail()
        if _json(_native(calendar)) != _json(_native(first.calendar)):
            _fail()
        _ledger._sequence_value(_mget(self, "start_sequence"))
        for name in ("run_id", "opening_cash", "opening_time", "resolution_cutoff"):
            if _mget(self, name) != _actions._get(common, name):
                _fail()
        if _mget(self, "cost_policy").canonical_bytes() != _actions._get(common, "cost_policy").canonical_bytes() or _mget(self, "action_policy").canonical_bytes() != _actions._get(common, "action_policy").canonical_bytes():
            _fail()
        expected = _actions._get(common, "entry_session")
        for index, item in enumerate(sessions):
            session = _actions._get(item, "session")
            if session.session_date != expected or not _bench._aligned(item, common):
                _fail()
            if index + 1 < len(sessions):
                expected = calendar.next_session(session.session_date).session_date
        if expected != _actions._get(common, "end_session"):
            _fail()
        binding_map = {item.decision_event_id: item for item in data}
        outcome_bindings = {}
        for item in data:
            selected = outcome_bindings.get(item.instrument_id)
            if selected is None or (item.next_session.close_at, item.decision_event_id) < (selected.next_session.close_at, selected.decision_event_id):
                outcome_bindings[item.instrument_id] = item
        identifiers = set()
        for intent in _mget(self, "intents"):
            _fills._binding_for_intent(intent, binding_map)
            if intent.intent_id in identifiers:
                _fail()
            identifiers.add(intent.intent_id)
        outcomes = set()
        for outcome in _mget(self, "outcomes"):
            _, _, _, key = _fills._validate_outcome_record(outcome, outcome_bindings)
            if key in outcomes:
                _fail()
            outcomes.add(key)

    def _plan(self, projection: _Projection) -> tuple:
        intents = _mget(self, "intents")
        semantic_ids = tuple(projection.reference("intent", intent.intent_id) for intent in intents)
        if len(set(semantic_ids)) != len(semantic_ids):
            _fail()
        ordered = sorted(intents, key=lambda intent: (intent.instrument_id, projection.reference("intent", intent.intent_id)))
        operations = []
        for index, item in enumerate(_mget(self, "sessions")):
            session = _actions._get(item, "session")
            base = (index, session.session_date.isoformat())
            operations.extend((*base, stage, None) for stage in ("opening", "payment"))
            for intent in ordered:
                if session.session_date < intent.first_session_date or session.close_at > intent.expires_at:
                    continue
                if intent.time_in_force != "gtc" and session.session_date != intent.first_session_date:
                    continue
                operations.append((*base, "attempt", projection.reference("intent", intent.intent_id)))
            operations.append((*base, "closing", None))
            if len(operations) > MAX_OPERATIONS:
                _fail()
        return tuple(operations)

    def canonical_bytes(self) -> bytes:
        self._refresh()
        return object.__getattribute__(self, "_canonical")

    def semantic_bytes(self) -> bytes:
        self._refresh()
        return object.__getattribute__(self, "_semantic")

    def semantic_input_hash(self) -> str:
        return _hash(SEMANTIC_DOMAIN, self.semantic_bytes())

    def _benchmarks(self) -> tuple:
        global _RETAINED_BYTES, _WORK_BYTES, _WORK_COUNT
        self._refresh()
        process_id = _process()
        entry = _pin_benchmarks(self)
        if entry is not None:
            return _copy_benchmark_entry(self, entry)
        reserved = _reserve_benchmark_build(self)
        try:
            self._refresh()
            runner = _bench.BenchmarkRunner()
            values = (runner.run_cash(_mget(self, "sessions"), policy=_mget(self, "cash_benchmark_policy")),
                      runner.run_buy_and_hold(_mget(self, "sessions"), policy=_mget(self, "buy_and_hold_policy")))
            self._refresh()
            if not reserved:
                return values
            try:
                native, canonical, charge, nodes = _benchmark_measurement(values)
            except _CacheCapacity:
                # Genuine bounded cold validation conveys no retained proof graph.
                self._refresh()
                return values
            digest = _benchmark_digest(native, canonical, charge, nodes)
            if _process() != process_id:
                _fail()
            with _ISSUER_LOCK:
                record = _issuer(self)
                if record.benchmark_digest is not None and record.benchmark_digest != digest:
                    _ISSUERS[id(self)] = record._replace(corrupt=True)
                    _fail()
                # Caller-supplied proof facts cannot reach this issuance point.
                # Both trusted runners and all fresh/completion guards finished.
                _ISSUERS[id(self)] = record._replace(benchmark_digest=digest)
                if 3 * charge <= _BENCHMARK_LIMIT:
                    entry = _BenchmarkEntry(record.reference, values, native, canonical, charge, nodes, process_id, pins=1)
                    _BENCHMARKS[id(record.reference)] = entry
                    _RETAINED_BYTES += charge
                    _WORK_BYTES += 2 * charge - _BENCHMARK_LIMIT
                    reserved = False
                    _pool_check()
                    _ISSUER_LOCK.notify_all()
                else:
                    entry = None
            if entry is not None:
                return _copy_benchmark_entry(self, _BenchmarkUse(entry, process_id, 2 * charge, record.reference))
            # No module-owned graph is retained on the genuine cold path.
            self._refresh()
            return values
        except Exception:
            _fail()
        finally:
            if reserved:
                _release_benchmark_build(process_id)

    def economic_bytes(self, events: tuple, results: tuple) -> bytes:
        self._refresh()
        _tuple(events)
        _tuple(results)
        before = _encode_native(_native((events, results), _Budget()))
        value = _economic_projection(self, events, results)
        if _encode_native(_native((events, results), _Budget())) != before:
            _fail()
        self._refresh()
        return _json({"schema_version": "v1", "semantic_input_hash": self.semantic_input_hash(), **value})

    def economic_output_hash(self, events: tuple, results: tuple) -> str:
        return _hash(ECONOMIC_DOMAIN, self.economic_bytes(events, results))

    def artifact_integrity_hash(self, *, events: tuple = (), results: tuple = ()) -> str:
        _tuple(events)
        _tuple(results)
        raw = self.canonical_bytes()
        if not events and not results:
            return _hash(ARTIFACT_DOMAIN, raw)
        return _output_material(self, events, results)[1]


def _output_material(manifest: ReplayManifest, events: tuple, results: tuple) -> tuple:
    """One guarded output operation computes both identities and exact records."""
    manifest._refresh()
    _tuple(events)
    _tuple(results)
    budget = _Budget()
    before = _encode_native(_native((events, results), budget))
    economic = _economic_projection(manifest, events, results)
    economic_raw = _json({"schema_version": "v1", "semantic_input_hash": manifest.semantic_input_hash(), **economic})
    event_records = [_exact_event(event) for event in events]
    result_records = [_exact_result(result) for result in results]
    exact = {"manifest": _decode(manifest.canonical_bytes()), "events": event_records, "results": result_records}
    exact_raw = _json(exact)
    if _encode_native(_native((events, results), _Budget())) != before:
        _fail()
    manifest._refresh()
    return (_hash(ECONOMIC_DOMAIN, economic_raw), _hash(ARTIFACT_DOMAIN, exact_raw), event_records, result_records)


def _exact_event(event: object) -> dict:
    if type(event) is not _ledger.LedgerEvent:
        _fail()
    raw, witness, _ = _ledger._verify_event(event)
    return {"canonical_utf8": raw.decode(), "event_native_witness": _json(_ledger._jsonable(witness)).hex()}


def _exact_result(result: object) -> dict:
    kind = type(result)
    if kind is _ledger.LedgerBalance:
        raw, witness = _ledger._verify_balance(result)
        return {"source_type": "LedgerBalance", "canonical_utf8": raw.decode(), "native_witness": _json(_ledger._jsonable(witness)).hex()}
    if kind is _nav.NAVResult or kind is SimOrder or kind is _bench.BenchmarkSeries:
        native = _native(result)
        return {"source_type": kind.__name__, "native_witness": _json(native).hex()}
    _fail()


def _new_ledger(manifest: ReplayManifest, *, benchmark: bool = False) -> _ledger.Ledger:
    common = _actions._get(_mget(manifest, "cash_benchmark_policy"), "common")
    return _ledger.Ledger(
        run_id=_mget(manifest, "run_id"), calendar_id=_actions._get(common, "calendar").calendar_id,
        currency="USD", opening_cash=_mget(manifest, "opening_cash"), opening_time=_mget(manifest, "opening_time"),
        resolution_cutoff=_mget(manifest, "resolution_cutoff"), start_sequence=0 if benchmark else _mget(manifest, "start_sequence"),
    )


def _balance_projection(balance: _ledger.LedgerBalance, projection: _Projection, prefixes: tuple) -> dict:
    _ledger._verify_balance(balance)
    scalar_fields = ("schema_version", "numeric_policy_version", "calendar_id", "currency", "opening_cash",
                     "opening_time", "resolution_cutoff", "start_sequence", "cash", "positions", "receivables",
                     "liabilities", "recognized_income", "recognized_expense", "total_fees", "event_count",
                     "next_sequence", "latest_economic_time", "latest_observation_time")
    result = {name: projection.value(object.__getattribute__(balance, name)) for name in scalar_fields}
    result["genesis_hash"] = prefixes[0]
    result["prefix_count"] = balance.event_count
    result["prefix_tail"] = prefixes[-1]
    result["fill_ids"] = sorted(projection.fill_refs[identifier] for identifier in balance.fill_ids)
    result["instrument_ids"] = sorted(balance.instrument_ids)
    result["obligations"] = [
        {name: projection.value(object.__getattribute__(item, name)) for name in
         ("obligation_id", "kind", "amount_created", "amount_remaining", "due_at", "economic_time")}
        for item in balance.obligations
    ]
    owners = []
    for item in balance.intent_ownership:
        owner = {name: projection.value(object.__getattribute__(item, name)) for name in
                 ("instrument_id", "side", "quantity", "cumulative_quantity", "cumulative_fee", "policy_version",
                  "fee_policy_id", "fixed_share_cap", "last_session_date", "terminal", "time_in_force")}
        owner.update(intent_id=projection.reference("intent", item.intent_id),
                     intent_hash=projection.reference("intent_hash", item.intent_hash),
                     fill_ids=[projection.fill_refs[identifier] for identifier in item.fill_ids])
        owners.append(owner)
    result["intent_ownership"] = sorted(owners, key=lambda item: item["intent_id"])
    result["session_cap_ownership"] = [
        {name: projection.value(object.__getattribute__(item, name)) for name in
         ("instrument_id", "session_date", "filled_quantity", "fixed_share_cap", "policy_version", "fee_policy_id")}
        for item in balance.session_cap_ownership
    ]
    result["action_state"] = projection.value(_actions._state(balance))
    return result


def _event_projection(event: _ledger.LedgerEvent, projection: _Projection, prior: dict, previous: str,
                      allowed: dict, before: _ledger.LedgerBalance, namespace: str) -> dict:
    _ledger._verify_event(event)
    kind = object.__getattribute__(event, "_kind")
    result = {"schema_version": "v1", "kind": kind, "sequence": event.sequence,
              "calendar_id": object.__getattribute__(event, "_calendar_id"), "currency": "USD",
              "previous_hash": previous,
              "economic_time": _time(object.__getattribute__(event, "_economic_time")),
              "observed_at": _time(object.__getattribute__(event, "_observed_at"))}
    if kind == "fill":
        intent, fill, binding, outcome, policy = _ledger._event_fill_parts(event)
        expected = allowed.get(intent.intent_id)
        if expected is None or intent.canonical_bytes() != expected.canonical_bytes():
            _fail()
        if _json(_native(intent)) != _json(_native(expected)):
            _fail()
        if policy.canonical_bytes() != _mget(projection.manifest, "cost_policy").canonical_bytes():
            _fail()
        if _json(_native(policy)) != _json(_native(_mget(projection.manifest, "cost_policy"))):
            _fail()
        owned_binding = projection.exact_bindings.get(object.__getattribute__(binding, "_source_fingerprint"))
        owned_outcome = projection.exact_outcomes.get(object.__getattribute__(outcome, "_outcome_hash"))
        if owned_binding is None or owned_outcome is None:
            _fail()
        if _json(_native(binding)) != _json(_native(owned_binding)) or _json(_native(outcome)) != _json(_native(owned_outcome)):
            _fail()
        result.update(intent=projection.model(intent), fill=projection.model(fill),
                      binding=projection.binding(binding), outcome=projection.outcome(outcome), policy=projection.model(policy))
    elif kind == "action_batch":
        batch = object.__getattribute__(event, "_action_batch")
        _bind_action_batch(projection, batch, before, namespace)
        action = projection.value(batch)
        action["fields"]["prior_balance"] = _ref("LedgerBalance", prior)
        result["action"] = action
    else:
        _fail()
    result["event_id"] = _ref("LedgerEvent", result)
    return result


def _bind_action_batch(projection: _Projection, batch: object, before: _ledger.LedgerBalance, namespace: str) -> None:
    manifest = projection.manifest
    session = _actions._get(batch, "session")
    item = next((item for item in _mget(manifest, "sessions")
                 if _actions._get(item, "session").session_date == session.session_date), None)
    if item is None or _json(_native(session)) != _json(_native(_actions._get(item, "session"))):
        _fail()
    common = _actions._get(_mget(manifest, "cash_benchmark_policy"), "common")
    for field, expected in (("policy", _mget(manifest, "action_policy")), ("calendar", _actions._get(common, "calendar"))):
        if _json(_native(_actions._get(batch, field))) != _json(_native(expected)):
            _fail()
    if _actions._get(batch, "archive_cutoff") != session.open_at:
        _fail()
    if _actions._get(batch, "mode") == "payment":
        if any(_actions._get(batch, field) for field in ("actions", "references", "mergers", "outstanding_intents")):
            _fail()
        return
    if _actions._get(batch, "mode") != "opening" or _actions._get(batch, "replay_policy") is not _actions._get(common, "replay_policy"):
        _fail()
    for field in ("actions", "references", "mergers"):
        if _json(_native(_actions._get(batch, field))) != _json(_native(_actions._get(item, field))):
            _fail()
    cancelled = {_actions._get(item, "intent_id") for item in _actions._get(_actions._state(before), "cancelled_intents")}
    owners = {owner.intent_id: owner for owner in before.intent_ownership}
    expected = []
    if namespace == "strategy" and (_actions._get(item, "actions") or _actions._get(item, "mergers")):
        for intent in _mget(manifest, "intents"):
            owner = owners.get(intent.intent_id)
            if intent.created_at >= session.open_at or intent.expires_at < session.open_at or intent.intent_id in cancelled:
                continue
            if owner is not None and owner.terminal:
                continue
            if intent.time_in_force != "gtc" and intent.first_session_date < session.session_date:
                continue
            expected.append(intent)
    def order(intent: OrderIntent) -> str:
        return projection.reference("intent", intent.intent_id)
    supplied = _actions._get(batch, "outstanding_intents")
    if len(supplied) != len(expected) or _json(_native(tuple(sorted(supplied, key=order)))) != _json(_native(tuple(sorted(expected, key=order)))):
        _fail()


def _project_ledger(manifest: ReplayManifest, events: tuple, projection: _Projection, *, namespace: str = "strategy", requested: set | None = None) -> tuple:
    _tuple(events)
    if any(type(event) is not _ledger.LedgerEvent for event in events):
        _fail()
    ledger = _new_ledger(manifest, benchmark=namespace != "strategy")
    allowed = {intent.intent_id: intent for intent in _mget(manifest, "intents")}
    if namespace != "strategy":
        allowed = {intent.intent_id: intent for intent in (
            _actions._get(member, "intent") for member in _actions._get(_mget(manifest, "buy_and_hold_policy"), "members"))}
    genesis = _ref("LedgerGenesis", {"namespace": namespace, "calendar_id": ledger.balance().calendar_id,
        "currency": "USD", "opening_cash": _decimal(_mget(manifest, "opening_cash")),
        "opening_time": _time(_mget(manifest, "opening_time")), "resolution_cutoff": _time(_mget(manifest, "resolution_cutoff")),
        "start_sequence": ledger.balance().start_sequence, "numeric_policy_version": "bt03-decimal-v1"})
    requested = {len(events)} if requested is None else requested
    previous, projected, states, exact_states = genesis, [], {}, {}
    balance = ledger.balance()
    if 0 in requested:
        states[0] = _balance_projection(balance, projection, (genesis, previous))
        exact_states[0] = balance
    seen, retained = set(), 0
    for event in events:
        raw, _, size = _ledger._verify_event(event)
        retained += size
        if retained > MAX_RECORD or len(raw) > 4 * 1024 * 1024 or event.event_id in seen:
            _fail()
        seen.add(event.event_id)
        prior = _balance_projection(balance, projection, (genesis, previous)) if event.kind == "action_batch" else {}
        economic = _event_projection(event, projection, prior, previous, allowed, balance, namespace)
        balance = ledger.append(event)
        projected.append(economic)
        previous = _ref("LedgerPrefix", {"previous": previous, "event": economic["event_id"]})
        if balance.event_count in requested:
            states[balance.event_count] = _balance_projection(balance, projection, (genesis, previous))
            exact_states[balance.event_count] = balance
    return projected, states, exact_states


def _nav_projection(result: _nav.NAVResult) -> dict:
    _native(result)
    if result.formula_version != "bt03-nav-v1" or result.numeric_policy_version != "bt03-decimal-v1":
        _fail()
    if result.status == "available":
        if result.run_valid is not True or result.reason_code is not None or type(result.value) is not Decimal or result.value < 0:
            _fail()
    elif result.status == "unavailable":
        if result.run_valid is not False or result.value is not None or type(result.reason_code) is not str or not result.reason_code:
            _fail()
    else:
        _fail()
    projection = {"status": result.status, "value": None if result.value is None else _decimal(result.value),
                  "run_valid": result.run_valid, "reason_code": result.reason_code,
                  "formula_version": result.formula_version, "numeric_policy_version": result.numeric_policy_version}
    return projection


def _benchmark_prefix(full: _bench.BenchmarkSeries, completed: int, *, reached_failure: bool = False) -> _bench.BenchmarkSeries:
    balances, points = _actions._get(full, "balances"), _actions._get(full, "nav_points")
    count = min(completed, len(balances))
    selected = balances[:count]
    events = _actions._get(full, "events")[:selected[-1].event_count] if selected else ()
    failed = reached_failure or (count and not points[count - 1].run_valid)
    return _bench.BenchmarkSeries(status="unavailable" if failed else "available", run_valid=not failed,
        reason_code=_actions._get(full, "reason_code") if failed else None,
        events=events, balances=selected, nav_points=points[:count], policy=_actions._get(full, "policy"))


def _strategy_nav(balance: _ledger.LedgerBalance, item: _bench.BenchmarkSessionInput) -> _nav.NAVResult:
    """Select the strategy's required marks from the shared frozen session input."""
    held = {instrument for instrument, quantity in balance.positions if quantity > 0}
    marks = tuple(mark for mark in _actions._get(item, "marks")
                  if object.__getattribute__(object.__getattribute__(mark, "_outcome"), "_bar_snapshot").instrument_id in held)
    return _nav.NAVCalculator().compute(balance, marks, _actions._get(item, "accounting_policy"))


def _economic_projection(manifest: ReplayManifest, events: tuple, results: tuple) -> dict:
    _tuple(events)
    _tuple(results)
    # Result types are admitted before any result callback, hashing or equality.
    budget, retained = _Budget(), 0
    for event in events:
        if type(event) is not _ledger.LedgerEvent:
            _fail()
        raw = object.__getattribute__(event, "_canonical")
        if type(raw) is not bytes:
            _fail()
        retained += len(raw)
        if retained > MAX_RECORD:
            _fail()
    for value in results:
        if not any(type(value) is expected for expected in (_ledger.LedgerBalance, _nav.NAVResult, SimOrder, _bench.BenchmarkSeries)):
            _fail()
        if type(value) is _ledger.LedgerBalance or type(value) is _bench.BenchmarkSeries:
            raw = object.__getattribute__(value, "_canonical")
            if type(raw) is not bytes:
                _fail()
            retained += len(raw)
            if retained > MAX_RECORD:
                _fail()
    for value in (*events, *results):
        _native(value, budget)
    requested = {len(events), 0}
    requested.update(value.event_count for value in results if type(value) is _ledger.LedgerBalance)
    nav_indices = []
    if any(type(value) is _nav.NAVResult for value in results):
        for item in _mget(manifest, "sessions"):
            session = _actions._get(item, "session")
            index = sum(object.__getattribute__(event, "_economic_time") <= session.close_at for event in events)
            nav_indices.append(index)
            requested.add(index)
    projection = _Projection(manifest)
    projected_events, balances, exact_balances = _project_ledger(manifest, events, projection, requested=requested)
    result_values = []
    allowed_nav = None
    for value in results:
        kind = type(value)
        if kind is _ledger.LedgerBalance:
            index = value.event_count
            if index not in balances or _ledger._verify_balance(value) != _ledger._verify_balance(exact_balances[index]):
                _fail()
            result_values.append({"type": "LedgerBalance", "value": balances[index]})
        elif kind is SimOrder:
            _native(value)
            if value.reason_code is not None and type(value.reason_code) is not str:
                _fail()
            intent = next((intent for intent in _mget(manifest, "intents") if intent.intent_id == value.intent_id), None)
            if intent is None or value.status not in ("filled", "cancelled", "expired", "open_at_horizon"):
                _fail()
            for quantity in (value.remaining_quantity, value.cumulative_quantity, value.cumulative_fee):
                _decimal(quantity)
                if quantity < 0:
                    _fail()
            from decimal import localcontext
            with localcontext(_contracts._fixed_context()):
                if value.remaining_quantity + value.cumulative_quantity != intent.quantity:
                    _fail()
            owners = {item.intent_id: item for item in exact_balances[len(events)].intent_ownership}
            owner = owners.get(value.intent_id)
            if (value.cumulative_quantity, value.cumulative_fee) != ((Decimal(0), Decimal(0)) if owner is None else (owner.cumulative_quantity, owner.cumulative_fee)):
                _fail()
            if (value.status == "filled" and (value.remaining_quantity != 0 or value.reason_code is not None)) or (value.status in ("cancelled", "expired") and not value.reason_code):
                _fail()
            result_values.append({"type": "SimOrder", "value": {"intent_id": projection.reference("intent", value.intent_id),
                **{name: projection.value(object.__getattribute__(value, name)) for name in _ORDER_FIELDS if name != "intent_id"}}})
        elif kind is _nav.NAVResult:
            nav_value = _nav_projection(value)
            if allowed_nav is None:
                allowed_nav = []
                for item, index in zip(_mget(manifest, "sessions"), nav_indices, strict=True):
                    actual = _strategy_nav(exact_balances[index], item)
                    allowed_nav.append(_nav_projection(actual))
            if nav_value not in allowed_nav:
                _fail()
            result_values.append({"type": "NAVResult", "value": nav_value})
        else:
            fulls = manifest._benchmarks()
            policy = _actions._get(value, "policy")
            slot = 0 if type(policy) is _bench.CashBenchmarkPolicy else 1 if type(policy) is _bench.BuyAndHoldPolicy else -1
            if slot < 0:
                _fail()
            full = fulls[slot]
            count = len(_actions._get(value, "balances"))
            status, valid, reason = (_actions._get(value, name) for name in ("status", "run_valid", "reason_code"))
            if status == "available":
                if valid is not True or reason is not None:
                    _fail()
            elif status != "unavailable" or valid is not False or type(reason) is not str or not reason:
                _fail()
            candidates = [_benchmark_prefix(full, count)]
            if not _actions._get(full, "run_valid") and count == len(_actions._get(full, "balances")):
                candidates.append(_benchmark_prefix(full, count, reached_failure=True))
            if not any(value.canonical_bytes() == candidate.canonical_bytes() and _json(_native(value)) == _json(_native(candidate)) for candidate in candidates):
                _fail()
            bench_events, bench_balances, _ = _project_ledger(manifest, _actions._get(value, "events"), projection,
                namespace="cash" if slot == 0 else "buy_and_hold",
                requested={balance.event_count for balance in _actions._get(value, "balances")})
            projected = {"status": _actions._get(value, "status"), "run_valid": _actions._get(value, "run_valid"),
                         "reason_code": _actions._get(value, "reason_code"), "policy": projection.value(policy),
                         "events": bench_events,
                         "balances": [bench_balances[balance.event_count] for balance in _actions._get(value, "balances")],
                         "nav_points": [_nav_projection(nav) for nav in _actions._get(value, "nav_points")]}
            result_values.append({"type": "BenchmarkSeries", "value": projected})
    return {"events": projected_events, "results": result_values}

"""Sealed, witnessed opening actions for the in-memory simulation ledger.

PIT records remain the source of action identity. Supplementary financial terms
are explicit simulation evidence; no provider, calendar capture or IO is used.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from pydantic import TypeAdapter

from mytradingalpha.backtest.clock import (
    SessionBinding,
    _capture_root,
    _capture_value,
    _CaptureBudget,
    _captured_payload,
    _CapturedModel,
    _require_captured_witness,
    _storage_bytes,
)
from mytradingalpha.backtest.costs import CostPolicy
from mytradingalpha.contracts.common import (
    CanonicalChecksum,
    StableId,
    UtcDateTime,
    _serialize_utc_datetime,
)
from mytradingalpha.contracts.orders import OrderIntent, _decimal_wire
from mytradingalpha.contracts.schemas import RunContext
from mytradingalpha.contracts.signals import SignalEnvelope
from mytradingalpha.data import bundle as _pit_bundle
from mytradingalpha.data.actions import (
    CorporateActionRepository,
    DelistingAction,
    DividendAction,
    SplitAction,
    TickerChangeAction,
)
from mytradingalpha.data.bars import AdjustmentBasis, BarFinality, BarRepository, DailyBar
from mytradingalpha.data.bundle import (
    BundleReplayPolicy,
    EvidenceBundle,
    EvidenceRequirement,
    MissingEvidence,
)
from mytradingalpha.data.calendar import TradingCalendar, TradingSession
from mytradingalpha.data.events import EventRepository, NewsEvent
from mytradingalpha.data.fundamentals import FilingRepository, FinancialFiling
from mytradingalpha.data.macro import MacroObservation, MacroRepository
from mytradingalpha.data.provenance import SourceManifest
from mytradingalpha.data.social import SocialPost, SocialRepository
from mytradingalpha.data.universe import (
    Instrument,
    SymbolAlias,
    UniverseManifest,
    UniverseMembership,
)

from .fills import OutcomeEvidence
from .ledger import (
    _MAX_EVENT_BYTES,
    LedgerBalance,
    LedgerEvent,
    ObligationBalance,
    _binding_capture,
    _binding_from_prepared,
    _canonical_json,
    _capture_call,
    _clone_balance,
    _contract_record,
    _decimal_checked,
    _empty_event,
    _exact_decimal,
    _jsonable,
    _reject,
    _safe_date,
    _safe_hash,
    _safe_identifier,
    _safe_utc,
    _seal_event,
    _verify_balance,
)
from .nav import AccountingPolicy, EligibleMark, NAVResult, _capture_mark, _refresh_policy

_ZERO = Decimal(0)
_MODEL_TYPES = (SplitAction, DividendAction, TickerChangeAction, DelistingAction,
                SourceManifest, TradingCalendar, TradingSession, DailyBar, Instrument, EvidenceBundle)
_ACTION_TYPES = (SplitAction, DividendAction, TickerChangeAction, DelistingAction)
_DOMAIN = b"mytradingalpha:bt04:native:v1\0"
_MAX_SOURCE = 2 * 1024 * 1024
_MAX_RUN = 16 * 1024 * 1024
_BENCH_VALUES: tuple[type, ...] = ()
_BUNDLE_METADATA = TypeAdapter(tuple[Literal["v1"], StableId, CanonicalChecksum, UtcDateTime, UtcDateTime, BundleReplayPolicy])


def _bundle_leaf(captured, permitted):
    if type(captured) is not _CapturedModel or not any(captured.model_type is cls for cls in permitted):
        _reject()
    return captured.model_type.model_validate(_captured_payload(captured, construct=False))


def _pure_bundle(captured):
    """Fixed PIT-v1 semantic proof, with no repository before-validators.

    Native capture has already guarded the complete graph. Leaf class schemas
    are compiled at import; fixed aggregates reuse their existing after-checks.
    No caller-supplied seal or hash carries semantic authority.
    """
    _require_captured_witness(captured)
    owned = _captured_payload(captured, construct=True)
    _BUNDLE_METADATA.validate_python((owned.schema_version, owned.bundle_id, owned.bundle_hash,
        owned.created_at, owned.knowledge_cutoff, owned.replay_policy))
    calendar = TradingCalendar.model_validate(_captured_payload(captured.fields["calendar"], construct=False))
    requirements = tuple(_bundle_leaf(v, (EvidenceRequirement,)) for v in captured.fields["requirements"])
    missing = tuple(_bundle_leaf(v, (MissingEvidence,)) for v in captured.fields["missing_optional"])
    fields = {}
    # This is the fixed v1 schema, not an extension or reducer registry.
    for name, types, key in (
        ("instruments", (Instrument,), _pit_bundle._instrument_sort_key),
        ("aliases", (SymbolAlias,), _pit_bundle._alias_sort_key),
        ("memberships", (UniverseMembership,), _pit_bundle._membership_sort_key),
        ("actions", _ACTION_TYPES, _pit_bundle._action_sort_key),
        ("bars", (DailyBar,), _pit_bundle._bar_sort_key),
        ("filings", (FinancialFiling,), _pit_bundle._filing_sort_key),
        ("events", (NewsEvent,), _pit_bundle._event_sort_key),
        ("social_posts", (SocialPost,), _pit_bundle._social_sort_key),
        ("macro_observations", (MacroObservation,), _pit_bundle._macro_sort_key),
    ):
        records = tuple(_bundle_leaf(v, types) for v in captured.fields[name])
        if records != tuple(sorted(records, key=key)):
            _reject()
        fields[name] = records
    if requirements != tuple(sorted(requirements, key=lambda r: r.domain.value)) or missing != tuple(sorted(missing, key=lambda r: r.domain.value)):
        _reject()
    universe = UniverseManifest.model_construct(schema_version="v1", instruments=fields["instruments"], aliases=fields["aliases"], memberships=fields["memberships"])
    UniverseManifest.validate_manifest(universe)
    BarRepository.validate_repository(BarRepository.model_construct(schema_version="v1", calendar=calendar, bars=fields["bars"]))
    CorporateActionRepository.validate_repository(CorporateActionRepository.model_construct(schema_version="v1", actions=fields["actions"]))
    FilingRepository.validate_repository(FilingRepository.model_construct(schema_version="v1", filings=fields["filings"]))
    EventRepository.validate_repository(EventRepository.model_construct(schema_version="v1", events=fields["events"]))
    SocialRepository.validate_repository(SocialRepository.model_construct(schema_version="v1", posts=fields["social_posts"]))
    MacroRepository.validate_repository(MacroRepository.model_construct(schema_version="v1", observations=fields["macro_observations"]))
    identifiers = {r.instrument_id for r in fields["instruments"]}
    for name in ("actions", "bars", "filings", "events", "social_posts"):
        if any(r.instrument_id is not None and r.instrument_id not in identifiers for r in fields[name]):
            _reject()
    for name, identity in (
        ("instruments", _pit_bundle._instrument_identity), ("aliases", _pit_bundle._alias_identity),
        ("memberships", _pit_bundle._membership_identity), ("actions", _pit_bundle._action_identity),
        ("bars", _pit_bundle._bar_identity), ("filings", _pit_bundle._filing_identity),
        ("events", _pit_bundle._event_identity), ("social_posts", _pit_bundle._social_identity),
        ("macro_observations", _pit_bundle._macro_identity),
    ):
        _pit_bundle._ensure_unique_selected(fields[name], identity=identity, domain=name)
        _pit_bundle._reject_non_historical_candidates(fields[name], domain=name)
        if any(not _pit_bundle._eligible(r, owned.knowledge_cutoff, owned.replay_policy) for r in fields[name]):
            _reject()
    present = _pit_bundle._presence(calendar=calendar, **fields)
    _pit_bundle._validate_missingness(requirements, missing, present, typed_missing_required=False)
    # Exactly the existing PIT semantic payload, including a present witness.
    payload = {"schema_version": owned.schema_version,
        "knowledge_cutoff": _serialize_utc_datetime(owned.knowledge_cutoff),
        "replay_policy": owned.replay_policy.value,
        "requirements": [r.model_dump(mode="json") for r in requirements],
        "missing_optional": [r.model_dump(mode="json") for r in missing],
        "calendar": calendar.model_dump(mode="json"),
        **{name: [r.model_dump(mode="json") for r in records] for name, records in fields.items()}}
    import json

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if owned.bundle_hash != "sha256:" + hashlib.sha256(raw).hexdigest():
        _reject()
    return owned


def _prove_binding_bundle(binding):
    from .clock import SessionBinding

    if type(binding) is not SessionBinding:
        _reject()
    bundle = object.__getattribute__(binding, "_bundle_snapshot")
    _model(bundle, validate=True)


class _RequestAdmission:
    """One operation's actual-source admission; occurrences are never deduplicated."""

    __slots__ = ("budget", "source_bytes", "components", "active")

    def __init__(self):
        self.budget = _CaptureBudget()
        self.source_bytes = 0
        self.components = []
        self.active = set()

    def charge(self, size):
        self.source_bytes += size
        if self.source_bytes > _MAX_RUN or self.budget.run_nodes > 1_000_000:
            _reject("resource_limit")

    def note(self, tag, raw):
        self.components.append((tag, hashlib.sha256(raw).digest()))

    def root(self, value, depth):
        captured = _capture_call(lambda: _capture_at(value, self.budget, depth))
        _capture_text(captured)
        raw = _storage_bytes(captured)
        if len(raw) > _MAX_SOURCE:
            _reject("resource_limit")
        self.note("native", raw)
        return captured

    def binding(self, value, depth):
        _guard_binding(value)
        from .clock import _BINDING_DOMAIN, SessionBinding, _source_json

        if type(value) is not SessionBinding:
            _reject()
        roots = tuple(self.root(object.__getattribute__(value, name), depth + 1) for name in (
            "_context_snapshot", "_bundle_snapshot", "_envelope_snapshot", "_session_snapshot", "_next_session_snapshot"))
        _capture_call(lambda: _require_captured_witness(roots[1]))
        owned = tuple(_captured_payload(r, construct=True) for r in roots)
        raw = _capture_call(lambda: _source_json(*owned[:3]))
        native = _storage_bytes(*roots)
        saved = object.__getattribute__(value, "_sealed_source_json")
        storage = object.__getattribute__(value, "_sealed_storage_bytes")
        fingerprint = object.__getattribute__(value, "_source_fingerprint")
        if type(saved) is not bytes or type(storage) is not bytes or len(raw) + len(native) > _MAX_SOURCE:
            _reject("resource_limit")
        if saved != raw or storage != native or type(fingerprint) is not str or fingerprint != "sha256:" + hashlib.sha256(_BINDING_DOMAIN + raw).hexdigest():
            _reject("source_changed")
        self.budget.run_nodes += 4
        self.charge(len(_BINDING_DOMAIN) + len(raw))
        self.note("binding", raw)

    def outcome(self, value, depth):
        _guard_outcome(value)
        from .fills import OutcomeEvidence, _outcome_wire

        if type(value) is not OutcomeEvidence:
            _reject()
        captures = tuple(self.root(object.__getattribute__(value, name), depth + 1) for name in (
            "_bar_snapshot", "_outcome_cutoff", "_archive_cutoff", "_replay_policy"))
        owned = tuple(_captured_payload(c, construct=True) for c in captures)
        raw = _capture_call(lambda: _canonical_json(_outcome_wire(*owned)))
        saved = object.__getattribute__(value, "_sealed_bytes")
        if type(saved) is not bytes or saved != raw:
            _reject("source_changed")
        self.budget.run_nodes += 4
        self.charge(len(raw))
        for name in ("_sealed_storage", "_outcome_hash"):
            seal = object.__getattribute__(value, name)
            if type(seal) is not bytes and type(seal) is not str:
                _reject()
            if type(seal) is bytes and len(seal) > _MAX_SOURCE:
                _reject("resource_limit")
            if type(seal) is str:
                from .ledger import _safe_hash

                _safe_hash(seal)
            self.derived(name, seal.encode() if type(seal) is str else seal)

    def derived(self, tag, raw):
        self.components.append(("derived:" + tag, raw))

    def visit(self, value, depth=0):
        from mytradingalpha.contracts.orders import _contract_storage_fingerprint

        from .clock import SessionBinding
        from .fills import OutcomeEvidence

        if depth > 64:
            _reject("resource_limit")
        cls = type(value)
        if cls is SessionBinding:
            self.binding(value, depth)
        elif cls is OutcomeEvidence:
            self.outcome(value, depth)
        elif cls is EligibleMark or cls is AccountingPolicy:
            _guard_opaque(value)
            self.budget.run_nodes += 1
            self.charge(2)
            self.visit(object.__getattribute__(value, "_binding"), depth + 1)
            if cls is EligibleMark:
                self.visit(object.__getattribute__(value, "_outcome"), depth + 1)
                names = ("_binding_seals", "_outcome_seals", "_seal")
            else:
                for name in ("_session_date", "_valuation_cutoff", "_archive_cutoff", "_currency", "_mark_source", "_mark_revision"):
                    self.visit(object.__getattribute__(value, name), depth + 1)
                names = ("_binding_seals", "_canonical", "_seal")
            for name in names:
                raw = object.__getattribute__(value, name)
                if type(raw) is bytes:
                    if len(raw) > _MAX_RUN:
                        _reject("resource_limit")
                    self.derived(name, raw)
                elif type(raw) is tuple:
                    from .ledger import _safe_hash

                    _tuple(raw, 3)
                    if len(raw) != 3:
                        _reject()
                    for index, seal in enumerate(raw):
                        if type(seal) is str:
                            _safe_hash(seal)
                            self.derived(name + str(index), seal.encode())
                        elif type(seal) is bytes:
                            if len(seal) > _MAX_SOURCE:
                                _reject("resource_limit")
                            self.derived(name + str(index), seal)
                        else:
                            _reject()
                else:
                    _reject()
        elif cls is OrderIntent or cls is CostPolicy:
            _capture_call(lambda: _contract_storage_fingerprint(value, cls, reason="source_changed"))
            payload = object.__getattribute__(value, "__dict__")
            fields_set = tuple(sorted(object.__getattribute__(value, "__pydantic_fields_set__")))
            captured = self.root(payload, depth + 1)
            self.root(fields_set, depth + 1)
            self.budget.run_nodes += 5 * len(cls.model_fields) + 4
            owned = cls.model_construct(_fields_set=set(fields_set), **_captured_payload(captured, construct=True))
            self.charge(len(_capture_call(lambda: _canonical_json(owned.model_dump(mode="json")))))
        elif any(cls is model for model in _MODEL_TYPES):
            captured = self.root(value, depth)
            if cls is EvidenceBundle:
                _capture_call(lambda: _require_captured_witness(captured))
            elif cls is TradingCalendar and captured.fields["replay_evidence"] is None:
                _reject()
            owned = _captured_payload(captured, construct=True)
            raw = _capture_call(lambda: _canonical_json(owned.model_dump(mode="json")))
            if len(raw) > _MAX_SOURCE:
                _reject("resource_limit")
            self.charge(len(raw))
        elif any(cls is model for model in _known_values()):
            identity = id(value)
            if identity in self.active:
                _reject()
            self.active.add(identity)
            try:
                fields = cls._fields
                data = _tuple(object.__getattribute__(value, "_data"), len(fields))
                if len(data) != len(fields):
                    _reject()
                _guard_fields(cls, data)
                canonical, storage = _guard_representations(value)
                self.budget.run_nodes += 1 + len(fields)
                self.charge(len(_canonical_json(fields)))
                self.derived("_canonical", canonical)
                self.derived("_storage", storage)
                for item in data:
                    self.visit(item, depth + 1)
            finally:
                self.active.remove(identity)
        elif cls is tuple:
            _tuple(value, 4096)
            self.budget.run_nodes += 1
            self.charge(2 + max(0, len(value) - 1))
            for item in value:
                self.visit(item, depth + 1)
        elif cls is bytes:
            self.budget.run_nodes += 1
            self.charge(len(value))
            self.note("bytes", value)
        else:
            captured = self.root(value, depth)
            owned = _captured_payload(captured, construct=True)
            # Primitive source encoding is bounded independently from native seals.
            raw = _canonical_json(_part(owned)[1])
            self.charge(len(raw))
        self.charge(0)


def _admit_request(policy, sessions):
    admission = _RequestAdmission()
    admission.visit(policy)
    admission.visit(sessions)
    return tuple(admission.components), admission.source_bytes, admission.budget.run_nodes


def _tuple(value: object, maximum: int) -> tuple:
    if type(value) is not tuple:
        _reject()
    if len(value) > maximum:
        _reject("resource_limit")
    return value


def _text(value: object) -> str:
    if type(value) is not str:
        _reject()
    if len(value) > 2048:
        _reject("resource_limit")
    encoded = _capture_call(lambda: value.encode("utf-8", "strict"))
    if len(encoded) > 2048:
        _reject("resource_limit")
    return value


def _capture_text(capture: object) -> None:
    pending = [capture]
    while pending:
        item = pending.pop()
        if type(item) is str:
            _text(item)
        elif type(item) is _CapturedModel:
            pending.extend(item.fields.values())
        elif type(item) is dict:
            pending.extend(dict.values(item))
        elif type(item) in (list, tuple):
            pending.extend(item)


def _capture_at(value, budget, depth):
    budget.begin_source()
    return _capture_value(value, budget, depth)


def _model(value: object, *, validate: bool, budget: _CaptureBudget | None = None, depth: int = 0) -> tuple[object, object, object]:
    if not any(type(value) is cls for cls in _MODEL_TYPES):
        _reject()
    capture_budget = _CaptureBudget() if budget is None else budget
    captured = _capture_call(lambda: _capture_at(value, capture_budget, depth))
    _capture_text(captured)
    if type(value) is TradingCalendar and captured.fields["replay_evidence"] is None:
        _reject()
    if type(value) is EvidenceBundle:
        _capture_call(lambda: _require_captured_witness(captured))
    native = _storage_bytes(captured)
    if len(native) > _MAX_SOURCE:
        _reject("resource_limit")
    if validate:
        payload = _captured_payload(captured, construct=False)
        owned = _capture_call(lambda: _pure_bundle(captured) if type(value) is EvidenceBundle else type(value).model_validate(payload))
        after = _capture_call(lambda: _capture_root(value, _CaptureBudget()))
        checked = _capture_call(lambda: _capture_root(owned, _CaptureBudget()))
        if _storage_bytes(after) != native:
            _reject("source_changed")
        preserved = _captured_payload(captured, construct=True)
        if _canonical_json(owned.model_dump(mode="json")) != _canonical_json(preserved.model_dump(mode="json")):
            _reject("source_changed")
        del checked
        owned = preserved
    else:
        owned = _captured_payload(captured, construct=True)
    wire = _capture_call(lambda: owned.model_dump(mode="json"))
    return owned, wire, [type(value).__name__, native.hex()]


def _known_values() -> tuple[type, ...]:
    # Benchmarks installs its exact six classes once, during module initialization.
    return _ACTION_VALUES + _BENCH_VALUES


def _typed(value, *classes):
    if not any(type(value) is cls for cls in classes):
        _reject()
    if type(value) is str:
        _text(value)
    elif type(value) is int and value.bit_length() > 256:
        _reject("resource_limit")
    elif type(value) is Decimal:
        _decimal_checked(value, "money")


def _bytes_bound(value, maximum, *, exact=None):
    _typed(value, bytes)
    if len(value) > maximum:
        _reject("resource_limit")
    if exact is not None and len(value) != exact:
        _reject("source_changed")
    return value


def _typed_tuple(value, maximum, *classes, minimum=0):
    values = _tuple(value, maximum)
    if len(values) < minimum or any(not any(type(item) is cls for cls in classes) for item in values):
        _reject()
    return values


def _guard_fields(cls, data):
    """Check fixed native field shapes before recursive capture or seal work."""
    _tuple(data, len(cls._fields))
    if len(data) != len(cls._fields):
        _reject("source_changed")
    optional = type(None)
    term_types = (str, str, str, str, str, date, str, int, SourceManifest)
    if cls is ActionPolicy:
        kinds = (str, str, str, AdjustmentBasis, str, str, str)
    elif cls is SplitTerms:
        kinds = term_types + (str, Decimal, (Decimal, optional), (date, optional))
    elif cls is DividendTerms:
        kinds = term_types + (str, (str, optional), (Decimal, optional))
    elif cls is DelistingTerms:
        kinds = term_types + (str, Decimal, (date, optional))
    elif cls is AvailableCorporateAction:
        kinds = (_ACTION_TYPES, (SplitTerms, DividendTerms, DelistingTerms, optional))
    elif cls is PositionReference:
        kinds = (str, str, Decimal, DailyBar, Instrument, TradingCalendar, str, str)
    elif cls is MergerMapping:
        kinds = (str, str, str, str, str, str, date, Decimal, SourceManifest)
    elif cls is _Applied:
        kinds = (str, int, str)
    elif cls is _Cancellation:
        kinds = (str, str)
    elif cls is _SplitReference:
        kinds = (str, int, int, int, int)
    elif cls is _Claim:
        kinds = (str, str, str, Decimal, datetime, bool)
    elif cls is _ActionState:
        kinds = (tuple, tuple, tuple, tuple, tuple, tuple, tuple, bytes, bytes)
    elif cls is _ActionBatch:
        kinds = (str, bytes, TradingSession, TradingCalendar, ActionPolicy, tuple, tuple, tuple, tuple, BundleReplayPolicy, datetime)
    elif _BENCH_VALUES:
        common, cash, member, buy_hold, session, series = _BENCH_VALUES
        if cls is common:
            kinds = (str, str, str, Decimal, datetime, datetime, TradingCalendar, str, CostPolicy, ActionPolicy, date, date, str, int, BundleReplayPolicy)
        elif cls is cash:
            kinds = (common, str, Decimal)
        elif cls is member:
            kinds = (str, Decimal, Decimal, Decimal, OrderIntent, SessionBinding)
        elif cls is buy_hold:
            kinds = (common, EvidenceBundle, tuple, str, str, str)
        elif cls is session:
            kinds = (TradingSession, tuple, AccountingPolicy, tuple, tuple, tuple)
        elif cls is series:
            kinds = (str, bool, (str, optional), tuple, tuple, tuple, (cash, buy_hold))
        else:
            _reject()
    else:
        _reject()
    for value, allowed in zip(data, kinds, strict=True):
        _typed(value, *(allowed if type(allowed) is tuple else (allowed,)))
    if cls is AvailableCorporateAction:
        expected = {SplitAction: SplitTerms, DividendAction: DividendTerms, DelistingAction: DelistingTerms}.get(type(data[0]))
        if data[1] is not None and type(data[1]) is not expected:
            _reject()
    elif cls is _ActionState:
        for index, child in ((0, _Applied), (2, _Cancellation), (4, _SplitReference), (6, _Claim)):
            _typed_tuple(data[index], 4096, child)
        _typed_tuple(data[3], 256, str)
        for index, right in ((1, str), (5, datetime)):
            for pair in _typed_tuple(data[index], 256, tuple):
                _tuple(pair, 2)
                if len(pair) != 2:
                    _reject()
                _typed(pair[0], str)
                _typed(pair[1], right)
        for value in data[7:]:
            _bytes_bound(value, _MAX_SOURCE)
    elif cls is _ActionBatch:
        _bytes_bound(data[1], 32, exact=32)
        for index, maximum, child in ((5, 64, AvailableCorporateAction), (6, 64, OrderIntent), (7, 32, PositionReference), (8, 32, MergerMapping)):
            _typed_tuple(data[index], maximum, child)
    elif _BENCH_VALUES:
        if cls is _BENCH_VALUES[3]:
            _typed_tuple(data[2], 8, _BENCH_VALUES[2], minimum=1)
        elif cls is _BENCH_VALUES[4]:
            for index, maximum, child in ((1, 8, EligibleMark), (3, 64, AvailableCorporateAction), (4, 32, PositionReference), (5, 32, MergerMapping)):
                _typed_tuple(data[index], maximum, child)
        elif cls is _BENCH_VALUES[5]:
            _typed_tuple(data[3], 4096, LedgerEvent)
            _typed_tuple(data[4], 16, LedgerBalance)
            _typed_tuple(data[5], 16, NAVResult)


def _guard_representations(value):
    canonical = _bytes_bound(object.__getattribute__(value, "_canonical"), _MAX_RUN)
    storage = _bytes_bound(object.__getattribute__(value, "_storage"), _MAX_RUN)
    if len(canonical) + len(storage) > _MAX_RUN:
        _reject("resource_limit")
    return canonical, storage


def _guard_binding(value):
    _typed(value, SessionBinding)
    for name, cls in (("_context_snapshot", RunContext), ("_bundle_snapshot", EvidenceBundle),
                      ("_envelope_snapshot", SignalEnvelope), ("_session_snapshot", TradingSession),
                      ("_next_session_snapshot", TradingSession)):
        _typed(object.__getattribute__(value, name), cls)
    for name in ("_sealed_source_json", "_sealed_storage_bytes"):
        _bytes_bound(object.__getattribute__(value, name), _MAX_SOURCE)
    _safe_hash(object.__getattribute__(value, "_source_fingerprint"))


def _guard_outcome(value):
    _typed(value, OutcomeEvidence)
    for name, cls in (("_bar_snapshot", DailyBar), ("_outcome_cutoff", datetime),
                      ("_archive_cutoff", datetime), ("_replay_policy", BundleReplayPolicy)):
        _typed(object.__getattribute__(value, name), cls)
    for name in ("_sealed_bytes", "_sealed_storage"):
        _bytes_bound(object.__getattribute__(value, name), _MAX_SOURCE)
    _safe_hash(object.__getattribute__(value, "_outcome_hash"))


def _guard_seal_tuple(value, *, outcome=False):
    _tuple(value, 3)
    if len(value) != 3:
        _reject("source_changed")
    _bytes_bound(value[0], _MAX_SOURCE)
    if outcome:
        _bytes_bound(value[1], _MAX_SOURCE)
        _safe_hash(value[2])
    else:
        _safe_hash(value[1])
        _bytes_bound(value[2], _MAX_SOURCE)


def _guard_opaque(value):
    _guard_binding(object.__getattribute__(value, "_binding"))
    _guard_seal_tuple(object.__getattribute__(value, "_binding_seals"))
    _bytes_bound(object.__getattribute__(value, "_seal"), 32, exact=32)
    if type(value) is EligibleMark:
        _guard_outcome(object.__getattribute__(value, "_outcome"))
        _guard_seal_tuple(object.__getattribute__(value, "_outcome_seals"), outcome=True)
    elif type(value) is AccountingPolicy:
        _bytes_bound(object.__getattribute__(value, "_canonical"), _MAX_EVENT_BYTES)
        for name, cls in (("_session_date", date), ("_valuation_cutoff", datetime), ("_archive_cutoff", datetime),
                          ("_currency", str), ("_mark_source", str), ("_mark_revision", int)):
            _typed(object.__getattribute__(value, name), cls)
    else:
        _reject()


def _value_parts(cls, data, *, validate=False, depth=0, budget=None, active=None):
    if not _BENCH_VALUES or cls is not _BENCH_VALUES[5]:
        return _parts(data, validate=validate, depth=depth, budget=budget, active=active)
    # Only Series.policy embeds the full validated native payload without hex.
    budget = _CaptureBudget() if budget is None else budget
    active = set() if active is None else active
    parts = _parts(data[:6], validate=validate, depth=depth, budget=budget, active=active)
    budget.run_nodes += 1
    if budget.run_nodes > 1_000_000 or depth > 64:
        _reject("resource_limit")
    policy = _clone_value(data[6], budget=budget, depth=depth + 1, active=active)
    canonical, storage = _guard_representations(policy)
    if not storage.startswith(_DOMAIN):
        _reject("source_changed")
    # The policy has already been fully cloned and independently revalidated.
    # Exact round-trip rejects duplicate keys, whitespace and noncanonical JSON.
    payload = _capture_call(lambda: json.loads(storage[len(_DOMAIN):], parse_constant=lambda _: _reject("source_changed")))
    if _DOMAIN + _canonical_json(payload) != storage:
        _reject("source_changed")
    part = (policy, [type(policy).__name__, canonical.decode("utf-8")],
            ["series-policy-native-v1", _DOMAIN.decode("utf-8"), type(policy).__name__, payload])
    if sum(len(_canonical_json(p[1])) + len(_canonical_json(p[2])) for p in (*parts, part)) > _MAX_RUN:
        _reject("resource_limit")
    return (*parts, part)


def _parts(values: tuple, *, validate: bool = False, depth: int = 0, budget: _CaptureBudget | None = None, active: set[int] | None = None) -> tuple:
    result = []
    size = 0
    budget = _CaptureBudget() if budget is None else budget
    active = set() if active is None else active
    for value in values:
        part = _part(value, validate=validate, depth=depth, budget=budget, active=active)
        size += len(_canonical_json(part[1])) + len(_canonical_json(part[2]))
        if size > _MAX_RUN:
            _reject("resource_limit")
        result.append(part)
    return tuple(result)


def _part(value: object, *, validate: bool = False, depth: int = 0, budget: _CaptureBudget | None = None, active: set[int] | None = None) -> tuple[object, object, object]:
    budget = _CaptureBudget() if budget is None else budget
    active = set() if active is None else active
    budget.run_nodes += 1
    if budget.run_nodes > 1_000_000:
        _reject("resource_limit")
    if depth > 64:
        _reject("resource_limit")
    native = type(value)
    if value is None or native is bool:
        return value, value, value
    if native is str:
        _text(value)
        return value, value, value
    if native is bytes:
        if len(value) > _MAX_RUN:
            _reject("resource_limit")
        return value, ["bytes", value.hex()], ["bytes", value.hex()]
    if native is int:
        if value.bit_length() > 256:
            _reject("resource_limit")
        return value, value, ["int", value]
    if native is Decimal:
        _decimal_checked(value, "money")
        return value, _decimal_wire(value), ["Decimal", str(value)]
    if native is date:
        return value, value.isoformat(), ["date", value.isoformat()]
    if native is datetime:
        _safe_utc(value)
        return value, value.isoformat(), ["datetime", value.isoformat()]
    if native is AdjustmentBasis or native is BundleReplayPolicy:
        if not any(value is item for item in native):
            _reject()
        return value, value.value, [native.__name__, value.value]
    if any(native is cls for cls in _MODEL_TYPES):
        return _model(value, validate=validate, budget=budget, depth=depth)
    if native is OrderIntent or native is CostPolicy:
        owned, wire, storage = _contract_record(value, native, "source_changed")
        return owned, wire.decode(), [native.__name__, _jsonable(storage)]
    if native is EligibleMark:
        _guard_opaque(value)
        _prove_binding_bundle(object.__getattribute__(value, "_binding"))
        (binding, outcome), witness = _capture_mark(value)
        for root in (*binding[:3], outcome[0]):
            _capture_call(lambda root=root: _capture_at(root, budget, depth + 1))
        from .ledger import _outcome_from_state
        clone = object.__new__(EligibleMark)
        for name in EligibleMark.__slots__:
            object.__setattr__(clone, name, object.__getattribute__(value, name))
        object.__setattr__(clone, "_binding", _binding_from_prepared(binding))
        object.__setattr__(clone, "_outcome", _outcome_from_state(outcome))
        wire = [binding[5].decode(), outcome[4].decode()]
        return clone, wire, [wire, binding[7].hex(), outcome[6].hex(), witness.hex()]
    if native is AccountingPolicy:
        _guard_opaque(value)
        _prove_binding_bundle(object.__getattribute__(value, "_binding"))
        parts = []
        wire = _refresh_policy(value, parts)
        clone = object.__new__(AccountingPolicy)
        for name in AccountingPolicy.__slots__:
            object.__setattr__(clone, name, object.__getattribute__(value, name))
        binding, _ = _binding_capture(object.__getattribute__(value, "_binding"))
        for name in ("_context_snapshot", "_bundle_snapshot", "_envelope_snapshot"):
            _capture_call(lambda name=name: _capture_at(object.__getattribute__(binding, name), budget, depth + 1))
        object.__setattr__(clone, "_binding", binding)
        return clone, wire.decode(), [wire.decode(), object.__getattribute__(binding, "_sealed_storage_bytes").hex()]
    from .clock import SessionBinding
    if native is SessionBinding:
        _guard_binding(value)
        _prove_binding_bundle(value)
        clone, seals = _binding_capture(value)
        for name in ("_context_snapshot", "_bundle_snapshot", "_envelope_snapshot"):
            _capture_call(lambda name=name: _capture_at(object.__getattribute__(clone, name), budget, depth + 1))
        return clone, seals[0].decode(), [seals[0].decode(), seals[1], seals[2].hex()]
    if native is LedgerBalance:
        wire, witness = _verify_balance(value)
        return _clone_balance(value), wire.decode(), [wire.decode(), _jsonable(witness)]
    if native is LedgerEvent:
        from .ledger import _capture_event
        clone, wire, witness, _ = _capture_event(value)
        return clone, wire.decode(), [wire.decode(), _jsonable(witness)]
    from .nav import NAVResult
    if native is NAVResult:
        if type(value.status) is not str or type(value.run_valid) is not bool:
            _reject()
        fields = (value.status, value.value, value.reason_code, value.run_valid, value.formula_version, value.numeric_policy_version)
        owned, wire, storage = _part(fields, validate=validate, depth=depth + 1, budget=budget, active=active)
        return NAVResult(*owned), wire, storage
    if native is tuple:
        _tuple(value, 4096)
        parts = _parts(value, validate=validate, depth=depth + 1, budget=budget, active=active)
        return tuple(p[0] for p in parts), [p[1] for p in parts], [p[2] for p in parts]
    if any(native is cls for cls in _known_values()):
        clone = _clone_value(value, budget=budget, depth=depth + 1, active=active)
        return clone, [native.__name__, clone._canonical.decode()], [native.__name__, clone._storage.hex()]
    _reject()


class _Value:
    """Fixed-field native value, with defensive access and two independent seals."""
    __slots__ = ("_data", "_canonical", "_storage")
    _fields: tuple[str, ...] = ()

    def __init__(self, **fields: object) -> None:
        if not any(type(self) is cls for cls in _known_values()) or set(fields) != set(self._fields):
            _reject("input_invalid", TypeError)
        raw = tuple(fields[name] for name in self._fields)
        _guard_fields(type(self), raw)
        parts = _value_parts(type(self), raw, validate=True)
        data = tuple(p[0] for p in parts)
        object.__setattr__(self, "_data", data)
        _capture_call(self._validate)
        canonical = _canonical_json(dict(zip(self._fields, (p[1] for p in parts), strict=True)))
        storage = _DOMAIN + _canonical_json([p[2] for p in parts])
        if len(canonical) + len(storage) > _MAX_RUN:
            _reject("resource_limit")
        object.__setattr__(self, "_canonical", canonical)
        object.__setattr__(self, "_storage", storage)
        # Recheck ingress after all trusted model/contract validation.
        current = _value_parts(type(self), raw)
        if canonical != _canonical_json(dict(zip(self._fields, (p[1] for p in current), strict=True))) or storage != _DOMAIN + _canonical_json([p[2] for p in current]):
            _reject("source_changed")

    def _validate(self) -> None:
        pass

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("BT-04 value is immutable")

    def __getattr__(self, name: str) -> object:
        if name not in type(self)._fields:
            raise AttributeError("unknown BT-04 field")
        clone = _clone_value(self)
        return object.__getattribute__(clone, "_data")[type(self)._fields.index(name)]

    def __repr__(self) -> str:
        return "BT04Value(<sealed>)"

    def canonical_bytes(self) -> bytes:
        return _clone_value(self)._canonical


def _get(value: _Value, name: str) -> object:
    return object.__getattribute__(value, "_data")[type(value)._fields.index(name)]


def _clone_value(value: object, *, budget: _CaptureBudget | None = None, depth: int = 0, active: set[int] | None = None) -> _Value:
    if not any(type(value) is cls for cls in _known_values()):
        _reject()
    if depth > 64:
        _reject("resource_limit")
    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        _reject()
    active.add(identity)
    try:
        return _clone_value_native(value, budget=budget, depth=depth, active=active)
    finally:
        active.remove(identity)


def _clone_value_native(value, *, budget, depth, active):
    data = _tuple(object.__getattribute__(value, "_data"), len(type(value)._fields))
    if len(data) != len(type(value)._fields):
        _reject("source_changed")
    _guard_fields(type(value), data)
    canonical, storage = _guard_representations(value)
    parts = _value_parts(type(value), data, validate=True, depth=depth + 1, budget=budget, active=active)
    if canonical != _canonical_json(dict(zip(type(value)._fields, (p[1] for p in parts), strict=True))) or storage != _DOMAIN + _canonical_json([p[2] for p in parts]):
        _reject("source_changed")
    clone = object.__new__(type(value))
    object.__setattr__(clone, "_data", tuple(p[0] for p in parts))
    object.__setattr__(clone, "_canonical", canonical)
    object.__setattr__(clone, "_storage", storage)
    # These seals are integrity evidence, not issuer authentication. Revalidate
    # owned field semantics even when a caller has recomputed matching seals.
    _capture_call(clone._validate)
    return clone


def _required(value: _Value, name: str, expected: object) -> None:
    actual = _get(value, name)
    if type(actual) is not type(expected) or actual != expected:
        _reject()


class ActionPolicy(_Value):
    __slots__ = ()
    _fields = ("schema_version", "policy_version", "currency", "price_basis", "fractional_shares", "payment_rule", "dividend_treatment")

    def _validate(self) -> None:
        _required(self, "schema_version", "v1")
        _safe_identifier(_get(self, "policy_version"))
        _required(self, "currency", "USD")
        _required(self, "price_basis", AdjustmentBasis.UNADJUSTED)
        if _get(self, "fractional_shares") not in ("retain_exact", "cash_in_lieu"):
            _reject()
        _required(self, "payment_rule", "next_witnessed_session")
        _required(self, "dividend_treatment", "cash_no_reinvestment")


_TERM_FIELDS = ("schema_version", "policy_version", "action_id", "instrument_id", "currency", "effective_date", "action_source", "action_revision", "manifest")


class _Terms(_Value):
    __slots__ = ()

    def _validate(self) -> None:
        _required(self, "schema_version", "v1")
        for field in ("policy_version", "action_id", "instrument_id", "action_source"):
            _safe_identifier(_get(self, field))
        _required(self, "currency", "USD")
        _safe_date(_get(self, "effective_date"))
        revision = _get(self, "action_revision")
        if type(revision) is not int or not 0 <= revision <= (1 << 31) - 1 or type(_get(self, "manifest")) is not SourceManifest:
            _reject()
        manifest = _get(self, "manifest")
        if manifest.event_time is None or manifest.event_time.date() != _get(self, "effective_date") or manifest.published_at is None:
            _reject("binding_mismatch")


class SplitTerms(_Terms):
    __slots__ = ()
    _fields = _TERM_FIELDS + ("fractional_shares", "lot_size", "cash_in_lieu_price", "payable_date")

    def _validate(self) -> None:
        super()._validate()
        if _get(self, "fractional_shares") not in ("retain_exact", "cash_in_lieu"):
            _reject()
        _decimal_checked(_get(self, "lot_size"), "quantity", positive=True)
        if _get(self, "fractional_shares") == "cash_in_lieu":
            _decimal_checked(_get(self, "cash_in_lieu_price"), "execution", positive=True)
            if _safe_date(_get(self, "payable_date")) < _get(self, "effective_date"):
                _reject()
        elif _get(self, "cash_in_lieu_price") is not None or _get(self, "payable_date") is not None:
            _reject()


class DividendTerms(_Terms):
    __slots__ = ()
    _fields = _TERM_FIELDS + ("amount_basis", "conversion_action_id", "conversion_ratio")

    def _validate(self) -> None:
        super()._validate()
        if _get(self, "amount_basis") == "pre_split":
            _safe_identifier(_get(self, "conversion_action_id"))
            _decimal_checked(_get(self, "conversion_ratio"), "money", positive=True)
        elif _get(self, "amount_basis") != "post_split" or _get(self, "conversion_action_id") is not None or _get(self, "conversion_ratio") is not None:
            _reject()


class DelistingTerms(_Terms):
    __slots__ = ()
    _fields = _TERM_FIELDS + ("settlement", "amount_per_share", "payable_date")

    def _validate(self) -> None:
        super()._validate()
        if _get(self, "settlement") == "cash":
            _decimal_checked(_get(self, "amount_per_share"), "execution", positive=True)
            if _safe_date(_get(self, "payable_date")) < _get(self, "effective_date"):
                _reject()
        elif _get(self, "settlement") != "writeoff" or _get(self, "payable_date") is not None:
            _reject()
        else:
            _required(self, "amount_per_share", _ZERO)


class AvailableCorporateAction(_Value):
    __slots__ = ()
    _fields = ("action", "terms")

    def _validate(self) -> None:
        action, terms = _get(self, "action"), _get(self, "terms")
        if type(action) not in _ACTION_TYPES:
            _reject()
        if type(action) is SplitAction:
            _decimal_checked(action.new_shares_per_old_share, "money", positive=True)
        if terms is None:
            return
        expected = {SplitAction: SplitTerms, DividendAction: DividendTerms, DelistingAction: DelistingTerms}.get(type(action))
        if type(terms) is not expected:
            _reject()
        for field, expected_value in (("action_id", action.action_id), ("instrument_id", action.instrument_id),
                                      ("effective_date", action.effective_date), ("currency", "USD"),
                                      ("action_source", action.manifest.source), ("action_revision", action.manifest.revision)):
            _required(terms, field, expected_value)
        if type(action) is DividendAction and action.currency != "USD":
            _reject()


class PositionReference(_Value):
    __slots__ = ()
    _fields = ("instrument_id", "symbol", "cost_basis", "bar", "instrument", "calendar", "run_id", "binding_hash")

    def __init__(self, *, instrument_id: object, symbol: object, cost_basis: object, mark: object, **unknown: object) -> None:
        if unknown or type(mark) is not EligibleMark:
            _reject()
        _safe_identifier(instrument_id)
        _guard_opaque(mark)
        _prove_binding_bundle(object.__getattribute__(mark, "_binding"))
        (binding, outcome), witness = _capture_mark(mark)
        bar = outcome[0]
        matches = tuple(item for item in binding[1].instruments if item.instrument_id == instrument_id)
        if len(matches) != 1 or bar.instrument_id != instrument_id or bar.adjustment_basis is not AdjustmentBasis.UNADJUSTED or bar.finality is not BarFinality.FINAL:
            _reject()
        if matches[0].currency != "USD" or bar.calendar_id != binding[1].calendar.calendar_id or bar.manifest.available_at > outcome[1]:
            _reject()
        if outcome[3] is BundleReplayPolicy.ARCHIVE_REALISTIC and bar.manifest.ingested_at > outcome[2]:
            _reject()
        super().__init__(instrument_id=instrument_id, symbol=symbol, cost_basis=cost_basis, bar=bar,
                         instrument=matches[0], calendar=binding[1].calendar, run_id=binding[0].run_id,
                         binding_hash=hashlib.sha256(binding[5] + binding[7]).hexdigest())
        if _capture_mark(mark)[1] != witness:
            _reject("source_changed")

    def _validate(self) -> None:
        _safe_identifier(_get(self, "instrument_id"))
        _safe_identifier(_get(self, "symbol"))
        _decimal_checked(_get(self, "cost_basis"), "execution", positive=True)
        bar, instrument, calendar = _get(self, "bar"), _get(self, "instrument"), _get(self, "calendar")
        if type(bar) is not DailyBar or type(instrument) is not Instrument or type(calendar) is not TradingCalendar:
            _reject()
        if bar.instrument_id != _get(self, "instrument_id") or instrument.instrument_id != bar.instrument_id or instrument.currency != "USD" or bar.calendar_id != calendar.calendar_id or bar.adjustment_basis is not AdjustmentBasis.UNADJUSTED or bar.finality is not BarFinality.FINAL:
            _reject("binding_mismatch")
        _decimal_checked(bar.close, "execution", positive=True)
        _safe_identifier(_get(self, "run_id"))
        digest = _get(self, "binding_hash")
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            _reject()


class MergerMapping(_Value):
    __slots__ = ()
    _fields = ("schema_version", "mapping_id", "policy_version", "source_instrument_id", "target_instrument_id", "currency", "effective_date", "new_shares_per_old_share", "manifest")

    def _validate(self) -> None:
        _required(self, "schema_version", "v1")
        _required(self, "currency", "USD")
        for name in ("mapping_id", "policy_version", "source_instrument_id", "target_instrument_id"):
            _safe_identifier(_get(self, name))
        if _get(self, "source_instrument_id") == _get(self, "target_instrument_id") or type(_get(self, "manifest")) is not SourceManifest:
            _reject()
        _safe_date(_get(self, "effective_date"))
        _decimal_checked(_get(self, "new_shares_per_old_share"), "money", positive=True)
        manifest = _get(self, "manifest")
        if manifest.event_time is None or manifest.event_time.date() != _get(self, "effective_date") or manifest.published_at is None:
            _reject("binding_mismatch")


class _Applied(_Value):
    __slots__ = ()
    _fields = ("action_id", "revision", "source_hash")

    def _validate(self) -> None:
        _safe_identifier(_get(self, "action_id"))
        revision, digest = _get(self, "revision"), _get(self, "source_hash")
        if type(revision) is not int or not 0 <= revision <= (1 << 31) - 1 or type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            _reject()


class _Cancellation(_Value):
    __slots__ = ()
    _fields = ("intent_id", "reason")

    def _validate(self) -> None:
        _safe_identifier(_get(self, "intent_id"))
        if _get(self, "reason") not in ("split_preexisting_intent", "delisting_preexisting_intent", "merger_preexisting_intent"):
            _reject()


class _SplitReference(_Value):
    __slots__ = ()
    _fields = ("instrument_id", "cost_basis_numerator", "cost_basis_denominator", "mark_numerator", "mark_denominator")

    def _validate(self) -> None:
        _safe_identifier(_get(self, "instrument_id"))
        for name in self._fields[1:]:
            value = _get(self, name)
            if type(value) is not int or value <= 0 or value.bit_length() > 256:
                _reject("numeric_invalid")


class _Claim(_Value):
    __slots__ = ()
    _fields = ("obligation_id", "action_id", "kind", "amount", "due_at", "paid")

    def _validate(self) -> None:
        _safe_identifier(_get(self, "obligation_id"))
        _safe_identifier(_get(self, "action_id"))
        if _get(self, "kind") not in ("dividend", "principal") or type(_get(self, "paid")) is not bool:
            _reject()
        _decimal_checked(_get(self, "amount"), "money", positive=True)
        _safe_utc(_get(self, "due_at"))


class _ActionState(_Value):
    __slots__ = ()
    _fields = ("applied_actions", "symbols", "cancelled_intents", "closed_instruments", "split_references", "split_boundaries", "claims", "calendar_bytes", "policy_bytes")

    def _validate(self) -> None:
        for name, cls, key in (("applied_actions", _Applied, "action_id"), ("cancelled_intents", _Cancellation, "intent_id"), ("split_references", _SplitReference, "instrument_id"), ("claims", _Claim, "obligation_id")):
            values = _tuple(_get(self, name), 4096)
            if any(type(v) is not cls for v in values):
                _reject()
            keys = tuple(_get(v, key) for v in values)
            if keys != tuple(sorted(set(keys))):
                _reject()
        for name in ("symbols", "split_boundaries"):
            values = _tuple(_get(self, name), 256)
            for pair in values:
                _tuple(pair, 2)
                if len(pair) != 2:
                    _reject()
                _safe_identifier(pair[0])
                if name == "symbols":
                    _safe_identifier(pair[1])
                else:
                    _safe_utc(pair[1])
            keys = tuple(p[0] for p in values)
            if keys != tuple(sorted(set(keys))):
                _reject()
        closed = _tuple(_get(self, "closed_instruments"), 256)
        for instrument in closed:
            _safe_identifier(instrument)
        if closed != tuple(sorted(set(closed))):
            _reject()
        for name in ("calendar_bytes", "policy_bytes"):
            raw = _get(self, name)
            if type(raw) is not bytes or len(raw) > _MAX_SOURCE:
                _reject()


class _ActionBatch(_Value):
    __slots__ = ()
    _fields = ("mode", "prior_balance", "session", "calendar", "policy", "actions", "outstanding_intents", "references", "mergers", "replay_policy", "archive_cutoff")

    def __init__(self, **fields: object) -> None:
        for name, maximum in (("actions", 64), ("outstanding_intents", 64), ("references", 32), ("mergers", 32)):
            if name in fields:
                _tuple(fields[name], maximum)
        super().__init__(**fields)

    def _validate(self) -> None:
        if _get(self, "mode") not in ("opening", "payment") or type(_get(self, "prior_balance")) is not bytes or len(_get(self, "prior_balance")) != 32:
            _reject()
        for name, cls in (("session", TradingSession), ("calendar", TradingCalendar), ("policy", ActionPolicy), ("replay_policy", BundleReplayPolicy)):
            if type(_get(self, name)) is not cls:
                _reject()
        _safe_utc(_get(self, "archive_cutoff"))
        for name, cls, maximum in (("actions", AvailableCorporateAction, 64), ("outstanding_intents", OrderIntent, 64), ("references", PositionReference, 32), ("mergers", MergerMapping, 32)):
            values = _tuple(_get(self, name), maximum)
            if any(type(v) is not cls for v in values):
                _reject()
        if _get(self, "mode") == "payment" and any(_get(self, name) for name in ("actions", "outstanding_intents", "references", "mergers")):
            _reject()


_ACTION_VALUES = (ActionPolicy, SplitTerms, DividendTerms, DelistingTerms, AvailableCorporateAction,
                  PositionReference, MergerMapping, _Applied, _Cancellation, _SplitReference,
                  _Claim, _ActionState, _ActionBatch)


def _empty_action_state() -> _ActionState:
    return _ActionState(applied_actions=(), symbols=(), cancelled_intents=(), closed_instruments=(),
                        split_references=(), split_boundaries=(), claims=(), calendar_bytes=b"", policy_bytes=b"")


def _state(balance: LedgerBalance) -> _ActionState:
    value = object.__getattribute__(balance, "_action_state")
    return _empty_action_state() if value is None else _clone_value(value)


def _calendar(value: object, session: object) -> tuple[TradingCalendar, TradingSession, bytes]:
    if type(value) is not TradingCalendar or type(session) is not TradingSession:
        _reject()
    cal, wire, _ = _model(value, validate=True)
    ses, _, _ = _model(session, validate=True)
    if cal.replay_evidence is None:
        _reject()
    actual = _capture_call(lambda: cal.session(ses.session_date))
    if _model(actual, validate=False)[2] != _model(ses, validate=False)[2]:
        _reject("binding_mismatch")
    days = tuple(d for d in cal.replay_evidence.days if d.local_date == ses.session_date)
    if len(days) != 1 or not days[0].start_utc <= ses.open_at < ses.close_at < days[0].end_utc:
        _reject()
    return cal, ses, _canonical_json(wire)


def _due(calendar: TradingCalendar, payable: date) -> datetime:
    # session() can fail for a witnessed closure; next_session() verifies coverage
    # and never infers weekends or bridges gaps.
    schedule = tuple(s for s in calendar.schedule if s.session_date == payable)
    if schedule:
        session = _capture_call(lambda: calendar.session(payable))
    else:
        session = _capture_call(lambda: calendar.next_session(payable))
    return _calendar(calendar, session)[1].open_at


def _provenance(manifest: SourceManifest, session: TradingSession, replay: BundleReplayPolicy, archive: datetime) -> None:
    if manifest.available_at > session.open_at:
        _reject("chronology_invalid")
    if replay is BundleReplayPolicy.ARCHIVE_REALISTIC and manifest.ingested_at > min(session.open_at, archive):
        _reject("chronology_invalid")


def _selection(batch: _ActionBatch, before: LedgerBalance) -> tuple:
    calendar, session, calendar_bytes = _calendar(_get(batch, "calendar"), _get(batch, "session"))
    if calendar.calendar_id != before.calendar_id:
        _reject("binding_mismatch")
    policy = _get(batch, "policy")
    state = _state(before)
    if _get(state, "calendar_bytes") and (_get(state, "calendar_bytes") != calendar_bytes or _get(state, "policy_bytes") != policy.canonical_bytes()):
        _reject("binding_mismatch")
    if _get(batch, "prior_balance") != _balance_identity(before):
        _reject("event_conflict")
    if _get(batch, "mode") == "payment":
        return calendar, session, calendar_bytes, (), ()
    intents = _get(batch, "outstanding_intents")
    if len({i.intent_id for i in intents}) != len(intents):
        _reject("event_conflict")
    replay, archive = _get(batch, "replay_policy"), _get(batch, "archive_cutoff")
    if type(replay) is not BundleReplayPolicy:
        _reject()
    _safe_utc(archive)
    groups = {}
    for wrapper in _get(batch, "actions"):
        action = _get(wrapper, "action")
        groups.setdefault(action.action_id, []).append(wrapper)
    if len(groups) + len(_get(batch, "mergers")) > 32:
        _reject("resource_limit")
    selected = []
    applied = {_get(a, "action_id"): a for a in _get(state, "applied_actions")}
    for action_id, group in sorted(groups.items()):
        group.sort(key=lambda w: _get(w, "action").manifest.revision)
        first = _get(group[0], "action")
        prior = None
        for wrapper in group:
            action = _get(wrapper, "action")
            if (action.instrument_id, type(action), action.effective_date, action.manifest.source) != (first.instrument_id, type(first), first.effective_date, first.manifest.source):
                _reject("binding_mismatch")
            if prior is not None and (action.manifest.revision <= prior.revision or action.manifest.available_at < prior.available_at or action.manifest.ingested_at < prior.ingested_at or action.manifest.published_at < prior.published_at):
                _reject("chronology_invalid")
            # Every supplied effective revision must be eligible. A future revision
            # cannot hide behind a prior eligible record in this conservative v1.
            effective = _capture_call(lambda action=action: calendar.session(action.effective_date))
            _provenance(action.manifest, effective, replay, archive)
            terms = _get(wrapper, "terms")
            if terms is not None:
                _provenance(_get(terms, "manifest"), effective, replay, archive)
            prior = action.manifest
        wrapper = group[-1]
        action = _get(wrapper, "action")
        digest = hashlib.sha256(wrapper._canonical + wrapper._storage).hexdigest()
        if action_id in applied:
            old = applied[action_id]
            if _get(old, "revision") != action.manifest.revision or _get(old, "source_hash") != digest:
                _reject("event_conflict")
            continue
        if action.effective_date != session.session_date:
            _reject("chronology_invalid")
        if type(action) is not TickerChangeAction and _get(wrapper, "terms") is None:
            _reject()
        selected.append(wrapper)
    mappings = []
    ids = set(groups)
    for mapping in _get(batch, "mergers"):
        key = _get(mapping, "mapping_id")
        if key in ids:
            _reject("event_conflict")
        ids.add(key)
        _provenance(_get(mapping, "manifest"), session, replay, archive)
        digest = hashlib.sha256(mapping._canonical + mapping._storage).hexdigest()
        if key in applied:
            if _get(applied[key], "source_hash") != digest:
                _reject("event_conflict")
            continue
        if _get(mapping, "effective_date") != session.session_date:
            _reject("chronology_invalid")
        mappings.append(mapping)
    priority = {SplitAction: 0, TickerChangeAction: 1, DelistingAction: 2, DividendAction: 3}
    selected.sort(key=lambda w: (priority[type(_get(w, "action"))], _get(w, "action").instrument_id, _get(w, "action").action_id))
    if (selected or mappings) and before.latest_economic_time is not None and before.latest_economic_time >= session.open_at:
        _reject("chronology_invalid")
    split_ids = [a.instrument_id for w in selected if type(a := _get(w, "action")) is SplitAction]
    if len(split_ids) != len(set(split_ids)):
        _reject("event_conflict")
    mapping_sources = {_get(m, "source_instrument_id") for m in mappings}
    mapping_targets = {_get(m, "target_instrument_id") for m in mappings}
    if mapping_sources & mapping_targets:
        _reject("binding_mismatch")
    if any(type(a := _get(w, "action")) is DividendAction and a.instrument_id in mapping_sources for w in selected):
        _reject("binding_mismatch")
    mappings.sort(key=lambda m: _get(m, "mapping_id"))
    affected = {_get(w, "action").instrument_id for w in selected if type(_get(w, "action")) is SplitAction or type(_get(w, "action")) is DelistingAction}
    affected.update(_get(m, "source_instrument_id") for m in mappings)
    candidates = {i.intent_id for i in intents if i.instrument_id in affected and i.created_at < session.open_at}
    candidates.update(o.intent_id for o in before.intent_ownership if o.instrument_id in affected and not o.terminal)
    already_cancelled = {_get(c, "intent_id") for c in _get(state, "cancelled_intents")}
    if len(candidates - already_cancelled) > 64:
        _reject("resource_limit")
    return calendar, session, calendar_bytes, tuple(selected), tuple(mappings)


def _balance_identity(balance: LedgerBalance) -> bytes:
    wire, witness = _verify_balance(balance)
    return hashlib.sha256(wire + _canonical_json(_jsonable(witness))).digest()


def _rational_reference(instrument: str, basis: Fraction, mark: Fraction) -> _SplitReference:
    for number in (basis.numerator, basis.denominator, mark.numerator, mark.denominator):
        if number.bit_length() > 256:
            _reject("resource_limit")
    return _SplitReference(instrument_id=instrument, cost_basis_numerator=basis.numerator,
        cost_basis_denominator=basis.denominator, mark_numerator=mark.numerator, mark_denominator=mark.denominator)


def _claim_id(action_id: str) -> str:
    return "bt04-" + hashlib.sha256(action_id.encode()).hexdigest()


def _validate_reference(reference, before, session, calendar, replay, archive) -> None:
    if reference is None or _get(reference, "run_id") != before.run_id:
        _reject("binding_mismatch")
    bar = _get(reference, "bar")
    if _get(reference, "calendar").calendar_id != before.calendar_id or bar.session_date >= session.session_date:
        _reject("binding_mismatch")
    _provenance(bar.manifest, session, replay, archive)
    prior_session = _capture_call(lambda: calendar.session(bar.session_date))
    following = _capture_call(lambda: calendar.next_session(bar.session_date))
    if following.session_date != session.session_date or bar.manifest.event_time != prior_session.close_at:
        _reject("binding_mismatch")


def _fractional(quantity: Decimal, terms: SplitTerms, policy: ActionPolicy) -> tuple[Decimal, Decimal]:
    if _get(terms, "fractional_shares") != _get(policy, "fractional_shares"):
        _reject()
    if _get(terms, "fractional_shares") == "retain_exact":
        # Remove only arithmetic trailing zeros; this never rounds precision.
        normalized = _exact_decimal(lambda: quantity.normalize())
        return _decimal_checked(normalized, "holding", nonnegative=True), _ZERO
    lot = _get(terms, "lot_size")
    units = Fraction(quantity) // Fraction(lot)
    retained = _exact_decimal(lambda: Decimal(units) * lot)
    remainder = _exact_decimal(lambda: quantity - retained)
    return _decimal_checked(retained, "holding", nonnegative=True), _decimal_checked(_exact_decimal(lambda: remainder * _get(terms, "cash_in_lieu_price")), "money", nonnegative=True)


def _reduce_batch(before: LedgerBalance, batch: _ActionBatch) -> tuple:
    """Publication reducer. The accounting module independently checks economics."""
    calendar, session, cal_bytes, selected, mappings = _selection(batch, before)
    old = _state(before)
    positions = dict(before.positions)
    carried_entitlement = dict(before.positions)
    obligations = {o.obligation_id: o for o in before.obligations}
    cash, income = before.cash, before.recognized_income
    applied = {_get(a, "action_id"): a for a in _get(old, "applied_actions")}
    symbols = dict(_get(old, "symbols"))
    cancelled = {_get(c, "intent_id"): c for c in _get(old, "cancelled_intents")}
    closed = set(_get(old, "closed_instruments"))
    refs = {_get(r, "instrument_id"): r for r in _get(old, "split_references")}
    boundaries = dict(_get(old, "split_boundaries"))
    claims = {_get(c, "obligation_id"): c for c in _get(old, "claims")}
    references = {_get(r, "instrument_id"): r for r in _get(batch, "references")}
    if len(references) != len(_get(batch, "references")):
        _reject("event_conflict")
    instruments = set(before.instrument_ids)
    policy = _get(batch, "policy")
    converted_in_batch = set()

    def claim(action_id: str, amount: Decimal, payable: date, kind: str) -> None:
        nonlocal income
        due = _due(calendar, payable)
        if amount == 0:
            return
        key = _claim_id(action_id)
        if key in obligations or key in claims or len(obligations) >= 256:
            _reject("obligation_invalid")
        amount = _decimal_checked(amount, "money", positive=True)
        obligations[key] = ObligationBalance(key, "receivable", amount, amount, due, session.open_at)
        claims[key] = _Claim(obligation_id=key, action_id=action_id, kind=kind, amount=amount, due_at=due, paid=False)
        if kind == "dividend":
            income = _decimal_checked(_exact_decimal(lambda: income + amount), "money", nonnegative=True)

    def cancel(instrument: str, reason: str) -> None:
        for intent in _get(batch, "outstanding_intents"):
            if intent.run_id != before.run_id or intent.calendar_id != before.calendar_id or intent.currency != before.currency:
                _reject("binding_mismatch")
            if intent.instrument_id == instrument and intent.created_at < session.open_at:
                cancelled.setdefault(intent.intent_id, _Cancellation(intent_id=intent.intent_id, reason=reason))
        for owner in before.intent_ownership:
            if owner.instrument_id == instrument and not owner.terminal:
                cancelled.setdefault(owner.intent_id, _Cancellation(intent_id=owner.intent_id, reason=reason))
        if len(cancelled) > 4096:
            _reject("resource_limit")

    # Identity mappings occur between split conversion and dividend entitlement.
    for wrapper in selected:
        action = _get(wrapper, "action")
        if type(action) is DividendAction:
            continue
        instrument = action.instrument_id
        if instrument in closed:
            _reject("event_conflict")
        quantity = positions.get(instrument, _ZERO)
        terms = _get(wrapper, "terms")
        if type(action) is SplitAction:
            ratio = action.new_shares_per_old_share
            converted = _exact_decimal(lambda quantity=quantity, ratio=ratio: quantity * ratio)
            kept, proceeds = _fractional(converted, terms, policy)
            if quantity:
                reference = references.get(instrument)
                _validate_reference(reference, before, session, calendar, _get(batch, "replay_policy"), _get(batch, "archive_cutoff"))
                # Each opening starts from its supplied eligible reference.
                previous = refs.get(instrument) if instrument in converted_in_batch else None
                basis = Fraction(_get(reference, "cost_basis")) if previous is None else Fraction(_get(previous, "cost_basis_numerator"), _get(previous, "cost_basis_denominator"))
                mark = Fraction(_get(reference, "bar").close) if previous is None else Fraction(_get(previous, "mark_numerator"), _get(previous, "mark_denominator"))
                refs[instrument] = _rational_reference(instrument, basis / Fraction(ratio), mark / Fraction(ratio))
                converted_in_batch.add(instrument)
            positions[instrument] = kept
            carried_entitlement[instrument] = kept
            boundaries[instrument] = session.open_at
            cancel(instrument, "split_preexisting_intent")
            if _get(terms, "fractional_shares") == "cash_in_lieu":
                claim(action.action_id, proceeds, _get(terms, "payable_date"), "principal")
        elif type(action) is TickerChangeAction:
            current = symbols.get(instrument)
            if current is None:
                reference = references.get(instrument)
                if reference is None:
                    _reject("binding_mismatch")
                current = _get(reference, "symbol")
            if current != action.old_symbol:
                _reject("binding_mismatch")
            symbols[instrument] = action.new_symbol
        elif type(action) is DelistingAction:
            positions.pop(instrument, None)
            closed.add(instrument)
            cancel(instrument, "delisting_preexisting_intent")
            if _get(terms, "settlement") == "cash":
                claim(action.action_id, _exact_decimal(lambda quantity=quantity, terms=terms: quantity * _get(terms, "amount_per_share")), _get(terms, "payable_date"), "principal")
    for mapping in mappings:
        source, target = _get(mapping, "source_instrument_id"), _get(mapping, "target_instrument_id")
        if source in closed or target in closed:
            _reject("event_conflict")
        quantity = positions.pop(source, _ZERO)
        converted = _exact_decimal(lambda target=target, quantity=quantity, mapping=mapping: positions.get(target, _ZERO) + quantity * _get(mapping, "new_shares_per_old_share"))
        positions[target] = _decimal_checked(_exact_decimal(lambda converted=converted: converted.normalize()), "holding", nonnegative=True)
        carried_entitlement.pop(source, None)
        carried_entitlement[target] = positions[target]
        closed.add(source)
        cancel(source, "merger_preexisting_intent")
        instruments.add(target)
        key = _get(mapping, "mapping_id")
        applied[key] = _Applied(action_id=key, revision=_get(mapping, "manifest").revision, source_hash=hashlib.sha256(mapping._canonical + mapping._storage).hexdigest())
    for wrapper in selected:
        action, terms = _get(wrapper, "action"), _get(wrapper, "terms")
        if type(action) is DividendAction:
            quantity = carried_entitlement.get(action.instrument_id, _ZERO)
            entitlement = Fraction(quantity) * Fraction(action.amount_per_share)
            if _get(terms, "amount_basis") == "pre_split":
                conversions = tuple(_get(w, "action") for w in selected if type(_get(w, "action")) is SplitAction and _get(w, "action").action_id == _get(terms, "conversion_action_id") and _get(w, "action").instrument_id == action.instrument_id)
                if len(conversions) != 1 or conversions[0].new_shares_per_old_share != _get(terms, "conversion_ratio"):
                    _reject()
                entitlement /= Fraction(_get(terms, "conversion_ratio"))
            amount = _exact_decimal(lambda entitlement=entitlement: Decimal(entitlement.numerator) / Decimal(entitlement.denominator))
            claim(action.action_id, amount, action.payable_date, "dividend")
        applied[action.action_id] = _Applied(action_id=action.action_id, revision=action.manifest.revision,
            source_hash=hashlib.sha256(wrapper._canonical + wrapper._storage).hexdigest())
    if _get(batch, "mode") == "payment":
        for key, record in tuple(claims.items()):
            if not _get(record, "paid") and _get(record, "due_at") <= session.open_at:
                amount = _get(record, "amount")
                obligation = obligations.get(key)
                if obligation is None or obligation.amount_remaining != amount:
                    _reject("obligation_invalid")
                cash = _decimal_checked(_exact_decimal(lambda cash=cash, amount=amount: cash + amount), "money", nonnegative=True)
                obligations[key] = ObligationBalance(key, "receivable", amount, _ZERO, obligation.due_at, obligation.economic_time)
                claims[key] = _Claim(obligation_id=key, action_id=_get(record, "action_id"), kind=_get(record, "kind"), amount=amount, due_at=_get(record, "due_at"), paid=True)
    state = _ActionState(applied_actions=tuple(applied[k] for k in sorted(applied)), symbols=tuple(sorted(symbols.items())),
        cancelled_intents=tuple(cancelled[k] for k in sorted(cancelled)), closed_instruments=tuple(sorted(closed)),
        split_references=tuple(refs[k] for k in sorted(refs)), split_boundaries=tuple(sorted(boundaries.items())),
        claims=tuple(claims[k] for k in sorted(claims)), calendar_bytes=cal_bytes, policy_bytes=policy.canonical_bytes())
    positions = {k: v for k, v in positions.items() if v}
    return cash, positions, tuple(obligations[k] for k in sorted(obligations)), income, state, frozenset(instruments)


class CorporateActionReducer:
    __slots__ = ()

    def apply_opening_actions(self, balance: object, actions: object, session: object, policy: object, *,
                              calendar: object, event_id: object, outstanding_intents: object,
                              references: object, mergers: object, replay_policy: object, archive_cutoff: object,
                              **unknown: object) -> tuple[LedgerEvent, ...]:
        if unknown:
            _reject("input_invalid", TypeError)
        _tuple(actions, 64)
        _tuple(outstanding_intents, 64)
        _tuple(references, 32)
        _tuple(mergers, 32)
        if any(type(a) is not AvailableCorporateAction for a in actions) or any(type(i) is not OrderIntent for i in outstanding_intents) or any(type(r) is not PositionReference for r in references) or any(type(m) is not MergerMapping for m in mergers) or type(policy) is not ActionPolicy:
            _reject()
        return self._events(balance, session, policy, calendar, event_id, "opening", actions,
                            outstanding_intents, references, mergers, replay_policy, archive_cutoff)

    def apply_payments(self, balance: object, session: object, policy: object, *, calendar: object,
                       event_id: object, **unknown: object) -> tuple[LedgerEvent, ...]:
        if unknown:
            _reject("input_invalid", TypeError)
        if type(policy) is not ActionPolicy:
            _reject()
        return self._events(balance, session, policy, calendar, event_id, "payment", (), (), (), (), BundleReplayPolicy.ARCHIVE_REALISTIC, _safe_utc(object.__getattribute__(session, "open_at")) if type(session) is TradingSession else None)

    @staticmethod
    def _events(balance, session, policy, calendar, event_id, mode, actions, intents, references, mergers, replay, archive):
        ingress = _verify_balance(balance)
        before = _clone_balance(balance)
        cal, ses, _ = _calendar(calendar, session)
        token = _safe_identifier(event_id)
        batch = _ActionBatch(mode=mode, prior_balance=_balance_identity(before), session=ses, calendar=cal,
            policy=policy, actions=actions, outstanding_intents=intents, references=references,
            mergers=mergers, replay_policy=replay, archive_cutoff=archive)
        cash, positions, obligations, income, state, instruments = _reduce_batch(before, batch)
        old = _state(before)
        changed = state.canonical_bytes() != old.canonical_bytes()
        # Empty opening/payment evaluation does not initialize an action history.
        if mode == "opening":
            changed = tuple(a._canonical for a in _get(state, "applied_actions")) != tuple(a._canonical for a in _get(old, "applied_actions"))
        else:
            changed = tuple(c._canonical for c in _get(state, "claims")) != tuple(c._canonical for c in _get(old, "claims"))
        event = None
        if changed:
            event = _empty_event(LedgerEvent)
            for name, value in (("_kind", "action_batch"), ("_event_id", token), ("_sequence", before.next_sequence),
                                ("_previous_hash", before.prefix_hashes[-1] if before.prefix_hashes else before.genesis_hash),
                                ("previous_hash", before.prefix_hashes[-1] if before.prefix_hashes else before.genesis_hash),
                                ("_run_id", before.run_id), ("_calendar_id", before.calendar_id), ("_currency", before.currency),
                                ("_economic_time", ses.open_at), ("_observed_at", ses.open_at), ("_action_batch", batch)):
                object.__setattr__(event, name, value)
            _seal_event(event)
        if _verify_balance(balance) != ingress:
            _reject("source_changed")
        # Revalidate every original source after all reduction and serialization.
        original = (policy, actions, intents, references, mergers, replay, archive)
        captured = (_get(batch, "policy"), _get(batch, "actions"), _get(batch, "outstanding_intents"), _get(batch, "references"), _get(batch, "mergers"), _get(batch, "replay_policy"), _get(batch, "archive_cutoff"))
        if _part(original)[2] != _part(captured)[2] or _model(calendar, validate=False)[2] != _model(cal, validate=False)[2] or _model(session, validate=False)[2] != _model(ses, validate=False)[2]:
            _reject("source_changed")
        return () if event is None else (event,)


__all__ = ["ActionPolicy", "AvailableCorporateAction", "SplitTerms", "DividendTerms", "DelistingTerms", "PositionReference", "MergerMapping", "CorporateActionReducer"]

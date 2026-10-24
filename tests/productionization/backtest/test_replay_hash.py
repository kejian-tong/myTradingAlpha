"""BT-05 RED contracts for typed identity and immutable local recovery.

Resolve the new API in test bodies: the BT-04 base must collect successfully and
fail for the missing manifested-replay behavior. All financial inputs below use
the real PIT/SIG/BT validators. Cached fixture graphs are read-only; corruption
tests alter fresh inputs or files owned by their individual temporary root.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import json
import os
import socket
import subprocess
import urllib.request
import zoneinfo
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, Rounded, localcontext
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest

from mytradingalpha.contracts.research import EvidenceReference
from mytradingalpha.contracts.signals import LLMOverlay
from mytradingalpha.quant.envelope import combine_quant_overlay
from mytradingalpha.quant.variants import VariantRegistry
from tests.productionization.backtest import (
    test_actions_benchmarks as bt04,
    test_clock_events as bt01,
    test_fills_costs as bt02,
    test_ledger_nav as bt03,
)
from tests.productionization.quant import test_signal as quant
from tests.productionization.research import test_overlay as research

D = Decimal
UTC = timezone.utc
PRIORITY = "bt05-semantic-priority-v1"
DOMAINS = (
    b"mytradingalpha:bt05:semantic-input:v1\0",
    b"mytradingalpha:bt05:economic-output:v1\0",
    b"mytradingalpha:bt05:artifact-integrity:v1\0",
)
OPENING = bt03.OPENING_TIME
CREATED = datetime(2024, 7, 11, 1, 2, 3, 456789, UTC)
ROOT = Path(__file__).resolve().parents[3]


def _api() -> SimpleNamespace:
    modules = {}
    for name in ("manifest", "replay"):
        try:
            modules[name] = importlib.import_module(f"mytradingalpha.backtest.{name}")
        except ModuleNotFoundError as error:
            if error.name == f"mytradingalpha.backtest.{name}":
                pytest.fail(f"BT-05 RED: missing {name} behavioral contract", pytrace=False)
            raise
    expected = {"manifest": ("ReplayManifest",),
                "replay": ("ReplayRunner", "ReplayCheckpoint", "ReplayResult")}
    for module, names in expected.items():
        for name in names:
            assert hasattr(modules[module], name), f"BT-05 RED: missing {name} contract"
    return SimpleNamespace(**{name: getattr(modules[module], name)
                              for module, names in expected.items() for name in names})


def _research_case(run_id: str) -> SimpleNamespace:
    """Capture a genuine data-only note with this run's exact references."""
    bundle = quant._bundle(calendar=bt04._case().bundle.calendar)
    variant = "variant-bt05-quant-llm"
    captured_context = bt01._context(
        bundle, run_id=run_id, variant_id=variant,
        decision_time="2024-07-02T20:04:00Z",
        earliest_execution_time="2024-07-03T13:30:00Z",
    )
    instrument = ("Symbol: KEEP; instrument_id: inst-survivor; asset_class: equity; "
                  "exchange: XNAS; currency: USD")
    output = research.make_output()
    output.update(research.create_historical_initial_state(
        company_name="KEEP", trade_date="2024-07-02", asset_type="stock",
        instrument_context=instrument,
    ))
    captured = research.parse_cached_graph_response(research.build_cached_graph_response(
        **research.make_response_kwargs(
            bundle=bundle, context=captured_context, output=output,
            response_id=f"response-{run_id}", instrument_id=bt04.INST,
            ticker="KEEP", trade_date="2024-07-02", instrument_context=instrument,
        )
    ))
    note = research.ResearchNoteBuilder(
        bundle=bundle, context=captured_context, response=captured,
    ).build(source_agent="sentiment_analyst",
            source_fields={"thesis": "market_report", "risks": "news_report"},
            claim_citations={
                "thesis": (EvidenceReference(schema_version="v1", bundle_id=bundle.bundle_id,
                                             domain="actions", record_id="action-acme-split"),),
                "risks": (EvidenceReference(schema_version="v1", bundle_id=bundle.bundle_id,
                                            domain="events", record_id="news-aapl-earnings"),),
            })
    signal = quant._score(quant._api(), bundle=bundle, run_id=run_id)
    context = bt01._context(
        bundle, run_id=run_id, variant_id=variant,
        decision_time="2024-07-03T17:00:00Z",
        earliest_execution_time="2024-07-05T13:30:00Z",
    )
    overlay = LLMOverlay.model_validate(research._candidate(note, signal))
    envelope = combine_quant_overlay(
        signal, context=context, registry=VariantRegistry().register(variant, kind="quant_llm"),
        note=note, overlay=overlay,
    )
    binding = bt01._bt_api().SessionClock.bind(context, bundle, envelope)
    decision, opportunity = bt01._bt_api().BacktestRunner().run((binding,))
    return SimpleNamespace(context=context, bundle=bundle, envelope=envelope,
                           binding=binding, decision=decision, opportunity=opportunity)


def _fields(*, run_id: str = "run-bt05-fixture", kind: str = "quant_only",
            actions: bool = False, prices: tuple[str, ...] | None = None,
            order: dict[str, Any] | None = None, costs: dict[str, Any] | None = None,
            days: int = 3, bundle_cutoff: str | None = None) -> tuple[dict[str, Any], SimpleNamespace]:
    a2, a3, a4 = bt02._bt02_api(), bt03._bt03_api(), bt04._api()
    case = _research_case(run_id) if kind == "quant_llm" else bt02._case_for_bundle(
        bundle=bt04._case().bundle if bundle_cutoff is None else quant._bundle(
            calendar=bt04._case().bundle.calendar, cutoff=bundle_cutoff),
        run_id=run_id, variant_id="variant-bt01-quant-only",
        decision_time=bt01.DECISION_TIME, earliest_execution_time="2024-07-03T13:30:00Z",
    )
    first = bt04.SESSIONS.index(case.binding.next_session.session_date)
    selected = bt04.SESSIONS[first:first + days]
    price_values = prices or (("100", "50", "50") if actions else ("100",) * days)
    assert len(price_values) == days
    cost = bt02._policy(a2, **{
        "half_spread_bps": D("0"), "slippage_bps": D("0"),
        "commission_per_share": D("0"), "order_minimum": D("1"),
        "fixed_share_cap": D("2"), "lot_size": D("1"), **(costs or {}),
    })
    intent = bt02._intent(a2, case, **{
        "quantity": D("3"), "time_in_force": "gtc",
        "expires_at": case.bundle.calendar.session(selected[-1]).close_at,
        "plan_id": "plan-alpha", **(order or {}),
    })
    outcomes = tuple(bt02._outcome(a2, case, session=day, price=D(price))
                     for day, price in zip(selected, price_values, strict=True))
    session_inputs = []
    for index, (day, price) in enumerate(zip(selected, price_values, strict=True)):
        day_actions, references = (), ()
        if actions and index == 1:
            day_actions = tuple(bt04._available(a4, bt04._action(
                action_kind, f"bt05-{action_kind}", effective=day,
                **({"payable_date": selected[2]} if action_kind == "dividend" else {})))
                for action_kind in ("split", "dividend"))
            references = (a4.PositionReference(
                instrument_id=bt04.INST, symbol="KEEP", cost_basis=D("100"),
                mark=bt03._mark(a3, case, outcomes[index - 1]),
            ),)
        session_inputs.append(bt04._session_input(
            a4, day, case=case, price=price, actions=day_actions, references=references,
        ))
    common = bt04._common(a4, case=case, cost_policy=cost, end=selected[-1],
                          entry_session=selected[0], replay_policy=case.bundle.replay_policy)
    benchmark_intent = bt02._intent(
        a2, case, quantity=D("1"), plan_id="plan-benchmark",
        time_in_force="day", expires_at=case.binding.next_session.close_at,
    )
    member = bt04._member(
        a4, instrument_id=bt04.INST, weight=D(price_values[0]) / D("2000"),
        quantity="1", lot_size=D("1"), intent=benchmark_intent, binding=case.binding,
    )
    cash = a4.CashBenchmarkPolicy(common=common, interest_policy="zero", annual_rate=D("0"))
    bh = bt04._bh_policy(a4, common=common, members=(member,), universe=case.bundle)
    fields = {
        "schema_version": "v1", "run_id": run_id, "correlation_id": f"correlation-{run_id}",
        "created_at": CREATED, "bindings": (case.binding,), "intents": (intent,), "outcomes": outcomes,
        "sessions": tuple(session_inputs), "cost_policy": cost, "action_policy": bt04._policy(a4),
        "cash_benchmark_policy": cash, "buy_and_hold_policy": bh,
        "opening_cash": D("2000"), "opening_time": OPENING,
        "resolution_cutoff": common.resolution_cutoff, "start_sequence": 0,
        "code_version": "bt05-code-fixture-v1", "config_version": "bt05-config-fixture-v1",
        "model_version": "bt05-model-fixture-v1",
        "configuration": (("label", "caf\u00e9"), ("mode", "synthetic")),
        "seed": 17, "priority_policy": PRIORITY,
    }
    return fields, case


def _manifest(api: SimpleNamespace, **options: Any) -> tuple[Any, dict[str, Any], Any]:
    fields, case = _fields(**options)
    return api.ReplayManifest(**fields), fields, case


def _run(api: SimpleNamespace, root: Path, manifest: Any, *, max_operations: int | None = None) -> Any:
    root.mkdir()
    with api.ReplayRunner(root=root) as runner:
        return runner.run(manifest, max_operations=max_operations)


def _resume(api: SimpleNamespace, root: Path, manifest: Any, **kwargs: Any) -> Any:
    with api.ReplayRunner(root=root) as runner:
        return runner.resume(manifest, **kwargs)


def _reject(call: Any) -> BaseException:
    with pytest.raises((TypeError, ValueError, RuntimeError, OverflowError)) as captured:
        call()
    assert len(str(captured.value)) <= 256
    assert "sensitive-sentinel" not in str(captured.value)
    assert captured.value.__cause__ is None
    return captured.value


def _digest(domain: bytes, raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(domain + raw).hexdigest()


def _json(raw: bytes) -> Any:
    return json.loads(raw)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(sorted((p.name, p.read_bytes()) for p in root.iterdir() if p.is_file()))


def _records(root: Path, prefix: str) -> list[Path]:
    """The local v1 layout uses immutable manifest/operation/checkpoint/result names."""
    return sorted(p for p in root.iterdir() if p.name.startswith(prefix) and p.suffix == ".json")


def _economic(result: Any) -> tuple[Any, ...]:
    return (result.economic_output_hash,
            tuple(event.canonical_bytes() for event in result.events),
            tuple(balance.canonical_bytes() for balance in result.balances),
            result.nav_points, result.orders,
            result.cash_benchmark.canonical_bytes(), result.buy_and_hold_benchmark.canonical_bytes(),
            result.status, result.run_valid, result.reason_code)


def _oracle(fields: dict[str, Any], case: Any) -> Any:
    return bt02._run(bt02._bt02_api(), case, fields["intents"], fields["outcomes"],
                     fields["cost_policy"], cash=fields["opening_cash"],
                     end_session=fields["sessions"][-1].session.session_date)


@pytest.mark.parametrize("kind", ("quant_only", "quant_llm"))
@pytest.mark.parametrize("actions", (False, True))
def test_fixture_composes_real_sealed_signals_fills_and_independent_benchmarks(kind: str, actions: bool) -> None:
    fields, case = _fields(kind=kind, actions=actions)
    assert case.binding.bundle.calendar.replay_evidence is not None
    assert case.envelope.shadow_only
    assert (case.envelope.note is not None) == (kind == "quant_llm")
    oracle = _oracle(fields, case)
    assert sum((fill.quantity for fill in oracle.fills), D("0")) == D("3")
    assert sum((fill.fee for fill in oracle.fills), D("0")) == D("1")
    api = bt04._api()
    cash = api.BenchmarkRunner().run_cash(fields["sessions"], policy=fields["cash_benchmark_policy"])
    bh = api.BenchmarkRunner().run_buy_and_hold(fields["sessions"], policy=fields["buy_and_hold_policy"])
    assert cash.run_valid and bh.run_valid
    assert len(cash.nav_points) == len(bh.nav_points) == 3
    if actions:
        assert len(bh.events) >= 3
        assert bh.balances[-1].positions == ((bt04.INST, D("2")),)
        assert bh.balances[-1].receivables == D("0")
    else:
        assert cash.events == () and len(bh.events) == 1


def test_three_hash_domains_use_independent_canonical_utf8_preimages(tmp_path: Path) -> None:
    api = _api()
    wire = b'{"decimal":"0","label":"caf\xc3\xa9","utc":"2024-07-11T01:02:03.456789Z"}'
    assert tuple(_digest(domain, wire) for domain in DOMAINS) == (
        "sha256:bf0e1c646b34795d5857941926c1821071c6d48df218449fc34521f8fcfa0936",
        "sha256:712da5a5366c4bd29e3b4aa688769dca29f6fe7de2c068dc6faca66494b1a7b1",
        "sha256:a18f06d62164a48ca531d2f128e8e81da498c5e74277e2f6ff4d5684b9a4b7f3",
    )
    manifest, fields, _ = _manifest(api)
    result = _run(api, tmp_path / "run", manifest)
    semantic = manifest.semantic_bytes()
    economic = manifest.economic_bytes(result.events, result.results)
    artifact = manifest.canonical_bytes()
    for raw in (semantic, economic, artifact):
        assert type(raw) is bytes and _canonical(_json(raw)) == raw
    for raw in (semantic, artifact):
        assert b"caf\xc3\xa9" in raw and b"\\u00e9" not in raw
    assert manifest.semantic_input_hash().encode() in economic
    assert manifest.semantic_input_hash() == _digest(DOMAINS[0], semantic)
    assert manifest.economic_output_hash(result.events, result.results) == _digest(DOMAINS[1], economic)
    assert manifest.artifact_integrity_hash() == _digest(DOMAINS[2], artifact)
    assert len({manifest.semantic_input_hash(), result.economic_output_hash,
                manifest.artifact_integrity_hash()}) == 3
    assert PRIORITY.encode() in semantic and PRIORITY.encode() in artifact
    assert fields["created_at"].isoformat(timespec="microseconds").replace("+00:00", "Z").encode() in artifact
    assert manifest.semantic_input_hash().startswith("sha256:")
    assert len(manifest.semantic_input_hash()) == 71
    assert result.artifact_integrity_hash == manifest.artifact_integrity_hash(
        events=result.events, results=result.results)
    assert result.artifact_integrity_hash != manifest.artifact_integrity_hash()


@pytest.mark.parametrize("kind", ("quant_only", "quant_llm"))
@pytest.mark.parametrize("actions", (False, True))
def test_run_and_operational_lineage_exclusions_preserve_typed_sources(
    tmp_path: Path, kind: str, actions: bool,
) -> None:
    api = _api()
    left, lf, lc = _manifest(api, run_id="run-bt05-A", kind=kind, actions=actions)
    rf, rc = _fields(run_id="run-bt05-B", kind=kind, actions=actions)
    rf.update(created_at=CREATED + timedelta(days=1), correlation_id="different-correlation")
    right = api.ReplayManifest(**rf)
    sealed = (lc.bundle.model_dump_json(), rc.bundle.model_dump_json(),
              lc.envelope.model_dump_json(), rc.envelope.model_dump_json(),
              tuple(i.canonical_bytes() for i in lf["intents"] + rf["intents"]))
    assert left.semantic_bytes() == right.semantic_bytes()
    assert left.semantic_input_hash() == right.semantic_input_hash()
    assert left.artifact_integrity_hash() != right.artifact_integrity_hash()
    lresult = _run(api, tmp_path / "left", left)
    rresult = _run(api, tmp_path / "right", right)
    assert lresult.economic_output_hash == rresult.economic_output_hash
    assert left.economic_bytes(lresult.events, lresult.results) == right.economic_bytes(rresult.events, rresult.results)
    assert lresult.artifact_integrity_hash != rresult.artifact_integrity_hash
    assert sealed == (lc.bundle.model_dump_json(), rc.bundle.model_dump_json(),
                      lc.envelope.model_dump_json(), rc.envelope.model_dump_json(),
                      tuple(i.canonical_bytes() for i in lf["intents"] + rf["intents"]))
    if kind == "quant_llm":
        assert lc.envelope.note.note_id != rc.envelope.note.note_id
        assert lc.envelope.overlay.overlay_id != rc.envelope.overlay.overlay_id
        assert lc.envelope.note.output_hash == rc.envelope.note.output_hash


@pytest.mark.parametrize("field,value", (
    ("seed", 18), ("code_version", "bt05-code-v2"),
    ("config_version", "bt05-config-v2"), ("model_version", "bt05-model-v2"),
    ("configuration", (("label", "caf\u00e9"), ("mode", "changed"))),
    ("start_sequence", 7),
))
def test_material_manifest_input_changes_output_identity_even_when_numbers_agree(
    tmp_path: Path, field: str, value: Any,
) -> None:
    api = _api()
    left, fields, _ = _manifest(api)
    right = api.ReplayManifest(**{**fields, field: value})
    lresult = _run(api, tmp_path / "left", left)
    rresult = _run(api, tmp_path / "right", right)
    assert lresult.balances[-1].cash == rresult.balances[-1].cash
    assert lresult.balances[-1].positions == rresult.balances[-1].positions
    assert left.semantic_input_hash() != right.semantic_input_hash()
    assert lresult.economic_output_hash != rresult.economic_output_hash


@pytest.mark.parametrize("change", ("fee", "spread", "cap", "source", "availability", "ingestion", "cutoff", "knowledge_cutoff", "created_at"))
def test_economic_policy_provenance_and_order_times_are_material(change: str) -> None:
    api = _api()
    left, fields, case = _manifest(api)
    if change in ("fee", "spread", "cap"):
        key = {"fee": "order_minimum", "spread": "half_spread_bps", "cap": "fixed_share_cap"}[change]
        changed, _ = _fields(costs={key: D("2") if change != "cap" else D("3")})
    elif change == "knowledge_cutoff":
        changed, _ = _fields(bundle_cutoff="2024-07-01T20:04:01Z")
    elif change == "created_at":
        changed, _ = _fields(order={"created_at": case.context.decision_time + timedelta(seconds=1)})
    else:
        changed = dict(fields)
        kwargs = {"source": {"source": "synthetic-other-source"},
                  "availability": {"available_offset_minutes": 2},
                  "ingestion": {"ingestion_offset_minutes": 4},
                  "cutoff": {"outcome_cutoff": fields["outcomes"][0].outcome_cutoff + timedelta(seconds=1)}}[change]
        altered = bt02._outcome(bt02._bt02_api(), case, **kwargs)
        changed["outcomes"] = (altered,) + fields["outcomes"][1:]
        if change == "source":
            changed["intents"] = (bt02._intent(
                bt02._bt02_api(), case, quantity=D("3"), time_in_force="gtc",
                expires_at=fields["intents"][0].expires_at, plan_id="plan-alpha",
                outcome_source="synthetic-other-source"),)
    assert left.semantic_input_hash() != api.ReplayManifest(**changed).semantic_input_hash()


def test_competing_intents_have_run_independent_semantic_priority(tmp_path: Path) -> None:
    api = _api()
    manifests, fields_list, results, legacy = [], [], [], []
    for suffix in ("0", "5"):
        fields, case = _fields(run_id=f"run-bt05-order-probe-{suffix}")
        first = bt02._intent(bt02._bt02_api(), case, quantity=D("1"), plan_id="plan-alpha")
        second = bt02._intent(bt02._bt02_api(), case, quantity=D("2"), plan_id="plan-beta")
        fields["intents"] = (first, second)
        manifest = api.ReplayManifest(**fields)
        manifests.append(manifest)
        fields_list.append(fields)
        results.append(_run(api, tmp_path / suffix, manifest))
        legacy.append(_oracle(fields, case))
    exact_priorities = [tuple(i.plan_id for i in sorted(f["intents"], key=lambda i: i.intent_id)) for f in fields_list]
    assert exact_priorities[0] == tuple(reversed(exact_priorities[1]))
    assert sorted(sum((f.fee for f in r.fills), D("0")) for r in legacy) == [D("1"), D("2")]
    assert manifests[0].semantic_input_hash() == manifests[1].semantic_input_hash()
    assert results[0].economic_output_hash == results[1].economic_output_hash
    assert manifests[0].economic_bytes(results[0].events, results[0].results) == manifests[1].economic_bytes(results[1].events, results[1].results)
    allocations = []
    for fields, result in zip(fields_list, results, strict=True):
        plan = {i.intent_id: i.plan_id for i in fields["intents"]}
        allocations.append(sorted((plan[o.intent_id], o.cumulative_quantity, o.cumulative_fee, o.status) for o in result.orders))
    assert allocations[0] == allocations[1]
    assert results[0].artifact_integrity_hash != results[1].artifact_integrity_hash
    # Reordering set-like caller input changes neither priority nor economics.
    reversed_fields = {**fields_list[0], "intents": tuple(reversed(fields_list[0]["intents"]))}
    assert api.ReplayManifest(**reversed_fields).semantic_input_hash() == manifests[0].semantic_input_hash()


def test_duplicate_projected_intent_is_rejected_without_arbitrary_tie_break() -> None:
    api = _api()
    fields, _ = _fields()
    _reject(lambda: api.ReplayManifest(**{**fields, "intents": fields["intents"] * 2}))


@pytest.mark.parametrize("cancel", (False, True))
def test_set_like_ownership_and_cancellation_indexes_use_projected_identity(tmp_path: Path, cancel: bool) -> None:
    api = _api()
    wires = []
    for suffix in ("0", "5"):
        fields, case = _fields(run_id=f"run-bt05-order-probe-{suffix}", actions=cancel,
                               costs={"fixed_share_cap": D("4")})
        fields["intents"] = tuple(bt02._intent(bt02._bt02_api(), case,
            quantity=D(quantity), plan_id=plan, time_in_force="gtc",
            expires_at=fields["intents"][0].expires_at,
            order_type="limit", limit_price=D("1" if cancel else "101"))
            for quantity, plan in (("1", "plan-alpha"), ("2", "plan-beta")))
        manifest = api.ReplayManifest(**fields)
        result = _run(api, tmp_path / suffix, manifest)
        assert len(result.orders) == 2
        assert all(order.status == ("cancelled" if cancel else "filled") for order in result.orders)
        wires.append(manifest.economic_bytes(result.events, result.results))
    assert wires[0] == wires[1]


@pytest.mark.parametrize("tif", ("day", "gtc", "ioc", "fok"))
@pytest.mark.parametrize("marketable", (True, False))
def test_replay_matches_existing_single_intent_tif_and_fee_oracle(
    tmp_path: Path, tif: str, marketable: bool,
) -> None:
    api = _api()
    manifest, fields, case = _manifest(api, order={
        "time_in_force": tif, "order_type": "limit", "limit_price": D("101" if marketable else "99"),
    })
    oracle = _oracle(fields, case)
    result = _run(api, tmp_path / "run", manifest)
    assert result.orders == oracle.orders
    assert result.balances[-1].cash == oracle.cash
    assert result.balances[-1].positions == oracle.holdings
    assert result.balances[-1].total_fees == sum((fill.fee for fill in oracle.fills), D("0"))


@pytest.mark.parametrize("tif", ("day", "gtc", "ioc", "fok"))
def test_no_fill_operation_is_durable_even_with_empty_ledger_prefix(tmp_path: Path, tif: str) -> None:
    api = _api()
    manifest, _, _ = _manifest(api, order={"time_in_force": tif, "order_type": "limit", "limit_price": D("1")})
    partial = _run(api, tmp_path / "run", manifest, max_operations=3)
    assert partial.checkpoint.operation_count == 3
    assert partial.checkpoint.ledger_event_count == 0 and partial.events == ()
    assert len(_records(tmp_path / "run", "operation-")) == 3
    resumed = _resume(api, tmp_path / "run", manifest)
    full = _run(api, tmp_path / "full", manifest)
    assert _economic(resumed) == _economic(full)
    assert _economic(_resume(api, tmp_path / "run", manifest)) == _economic(full)


@pytest.mark.parametrize("tif", ("day", "gtc", "ioc", "fok"))
@pytest.mark.parametrize("timing", ("expires_before_close", "submit_after_first_close"))
def test_expiry_and_not_yet_eligible_reasons_match_existing_simulator(
    tmp_path: Path, tif: str, timing: str,
) -> None:
    api = _api()
    _, case = _fields()
    close = case.binding.next_session.close_at
    order = {"time_in_force": tif}
    if timing == "expires_before_close":
        order["expires_at"] = close - timedelta(seconds=1)
    else:
        order["earliest_submit_time"] = close + timedelta(seconds=1)
    manifest, fields, case = _manifest(api, order=order)
    result = _run(api, tmp_path / "run", manifest)
    assert result.orders == _oracle(fields, case).orders


@pytest.mark.parametrize("action_kind", ("split", "delisting"))
def test_action_cancels_never_filled_gtc_remainder_and_keeps_atomic_action_state(tmp_path: Path, action_kind: str) -> None:
    api = _api()
    fields, case = _fields(actions=True, order={"order_type": "limit", "limit_price": D("1")})
    if action_kind == "delisting":
        sessions = list(fields["sessions"])
        sessions[1] = bt04._session_input(bt04._api(), bt04.EX_DATE, case=case,
            actions=(bt04._available(bt04._api(), bt04._action("delisting", "bt05-delist")),))
        fields["sessions"] = tuple(sessions)
    manifest = api.ReplayManifest(**fields)
    result = _run(api, tmp_path / "run", manifest)
    assert result.orders[0].status == "cancelled"
    assert result.orders[0].cumulative_quantity == D("0")
    assert result.orders[0].reason_code
    assert result.balances[-1].positions == ()
    assert result.balances[-1].cash == D("2000")
    assert result.checkpoint.operation_count > result.checkpoint.ledger_event_count
    assert any(e.kind == "action_batch" for e in result.events)


def test_action_does_not_cancel_intent_created_after_its_opening_boundary(tmp_path: Path) -> None:
    api = _api()
    fields, case = _fields(actions=True)
    later = bt02._case_for_bundle(
        bundle=case.bundle, run_id=case.context.run_id, variant_id=case.context.variant_id,
        decision_time="2024-07-05T20:00:00Z", earliest_execution_time="2024-07-08T13:30:00Z",
    )
    intent = bt02._intent(bt02._bt02_api(), later, quantity=D("1"), plan_id="plan-after-split")
    fields.update(bindings=fields["bindings"] + (later.binding,), intents=fields["intents"] + (intent,))
    result = _run(api, tmp_path / "run", api.ReplayManifest(**fields))
    later_order = next(order for order in result.orders if order.intent_id == intent.intent_id)
    assert later_order.status == "filled" and later_order.cumulative_quantity == D("1")


def test_checkpoint_binds_complete_cursor_native_state_and_three_independent_ledgers(tmp_path: Path) -> None:
    api = _api()
    manifest, _, _ = _manifest(api, actions=True)
    result = _run(api, tmp_path / "run", manifest, max_operations=4)
    checkpoint = result.checkpoint
    assert type(checkpoint) is api.ReplayCheckpoint
    raw = checkpoint.canonical_bytes()
    assert api.ReplayCheckpoint.from_bytes(raw).canonical_bytes() == raw
    required = {"schema_version", "semantic_input_hash", "artifact_integrity_hash",
                "operation_count", "operation_prefix_hash", "next_cursor", "ledger_event_count",
                "ledger_tail_hash", "ledger_balance", "ledger_native_witness", "orders",
                "attempt_state", "remaining_cap", "action_state", "cash_benchmark",
                "buy_and_hold_benchmark", "reducer_versions", "numeric_policy_version", "serialization_version"}
    assert required <= set(_json(raw))
    assert checkpoint.semantic_input_hash == manifest.semantic_input_hash()
    assert checkpoint.artifact_integrity_hash == manifest.artifact_integrity_hash()
    with pytest.raises((AttributeError, TypeError)):
        checkpoint.operation_count = 999
    assert result.cash_benchmark.events == ()
    assert len(result.buy_and_hold_benchmark.events) == 1
    assert result.events[0].event_id != result.buy_and_hold_benchmark.events[0].event_id or result.events[0].canonical_bytes() != result.buy_and_hold_benchmark.events[0].canonical_bytes()


@pytest.mark.parametrize("completed", (0, 1, 2, 3))
def test_benchmark_prefixes_follow_closing_stages_without_future_suffix(tmp_path: Path, completed: int) -> None:
    api = _api()
    manifest, fields, _ = _manifest(api)
    full = _run(api, tmp_path / "full", manifest)
    # This GTC fixture attempts each of the first two closes; the third is terminal.
    limits = (0, 4, 8, full.checkpoint.operation_count)
    prefix = _run(api, tmp_path / "prefix", manifest, max_operations=limits[completed])
    for short, whole in ((prefix.cash_benchmark, full.cash_benchmark),
                         (prefix.buy_and_hold_benchmark, full.buy_and_hold_benchmark)):
        assert short.policy.canonical_bytes() == whole.policy.canonical_bytes()
        assert short.policy.common.end_session == fields["sessions"][-1].session.session_date
        assert len(short.balances) == len(short.nav_points) == completed
        assert short.nav_points == whole.nav_points[:completed]
        assert tuple(b.canonical_bytes() for b in short.balances) == tuple(b.canonical_bytes() for b in whole.balances[:completed])
        expected_count = whole.balances[completed - 1].event_count if completed else 0
        assert tuple(e.canonical_bytes() for e in short.events) == tuple(e.canonical_bytes() for e in whole.events[:expected_count])
        assert short.run_valid and short.reason_code is None


def test_failed_required_benchmark_is_retained_only_when_its_failure_boundary_is_reached(tmp_path: Path) -> None:
    api = _api()
    fields, case = _fields()
    sessions = list(fields["sessions"])
    sessions[1] = bt04._session_input(bt04._api(), sessions[1].session.session_date, case=case, marks=())
    fields["sessions"] = tuple(sessions)
    manifest = api.ReplayManifest(**fields)
    early = _run(api, tmp_path / "early", manifest, max_operations=4)
    assert early.run_valid and early.buy_and_hold_benchmark.run_valid
    assert len(early.buy_and_hold_benchmark.nav_points) == 1
    failed = _resume(api, tmp_path / "early", manifest)
    assert failed.status == "unavailable" and not failed.run_valid and failed.reason_code
    assert not failed.buy_and_hold_benchmark.run_valid
    assert failed.buy_and_hold_benchmark.nav_points[-1].status == "unavailable"
    assert len(failed.buy_and_hold_benchmark.nav_points) == 2
    assert _economic(_resume(api, tmp_path / "early", manifest)) == _economic(failed)


def test_every_operation_boundary_and_stale_checkpoint_resume_once(tmp_path: Path) -> None:
    api = _api()
    manifest, _, _ = _manifest(api, actions=True)
    full = _run(api, tmp_path / "full", manifest)
    for index in range(full.checkpoint.operation_count + 1):
        root = tmp_path / f"cut-{index}"
        partial = _run(api, root, manifest, max_operations=index)
        checkpoint = partial.checkpoint
        assert checkpoint.operation_count == index
        resumed = _resume(api, root, manifest, checkpoint=checkpoint, events=partial.events)
        assert _economic(resumed) == _economic(full)
        # A formerly complete supplied prefix is stale after new operations publish.
        if len(partial.events) != len(resumed.events):
            _reject(lambda root=root, partial=partial: _resume(api, root, manifest, events=partial.events))
        assert _economic(_resume(api, root, manifest, checkpoint=checkpoint)) == _economic(full)
        before = _snapshot(root)
        assert _economic(_resume(api, root, manifest)) == _economic(full)
        assert _snapshot(root) == before


class _Crash(BaseException):
    pass


@pytest.mark.parametrize("operation", ("link", "fsync"))
@pytest.mark.parametrize("when", ("before", "after"))
def test_each_atomic_publication_and_sync_crash_retains_recoverable_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, when: str,
) -> None:
    api = _api()
    manifest, _, _ = _manifest(api, actions=True)
    real = getattr(os, operation)
    observed = []
    def count(*args: Any, **kwargs: Any) -> Any:
        observed.append(1)
        return real(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(os, operation, count)
        full = _run(api, tmp_path / "full", manifest)
    assert observed, "storage must use fsync plus create-only atomic link publication"
    for cut in range(1, len(observed) + 1):
        root = tmp_path / f"crash-{cut}"
        calls = 0
        def crash(*args: Any, _cut: int = cut, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == _cut and when == "before":
                raise _Crash()
            answer = real(*args, **kwargs)
            if calls == _cut and when == "after":
                raise _Crash()
            return answer
        with monkeypatch.context() as patch:
            patch.setattr(os, operation, crash)
            with pytest.raises(_Crash):
                _run(api, root, manifest)
        before = dict(_snapshot(root))
        if _records(root, "manifest"):
            recovered = _resume(api, root, manifest)
        else:
            with api.ReplayRunner(root=root) as runner:
                recovered = runner.run(manifest)
        assert _economic(recovered) == _economic(full)
        after = dict(_snapshot(root))
        assert all(after.get(name) == raw for name, raw in before.items())
        assert _economic(_resume(api, root, manifest)) == _economic(full)


@pytest.mark.parametrize("damage", ("torn_operation", "missing_operation", "duplicate_operation", "torn_checkpoint", "old_checkpoint", "result"))
def test_persisted_corruption_rejects_and_retains_all_evidence(tmp_path: Path, damage: str) -> None:
    api = _api()
    manifest, _, _ = _manifest(api, actions=True)
    root = tmp_path / "run"
    _run(api, root, manifest)
    operations, checkpoints = _records(root, "operation-"), _records(root, "checkpoint-")
    assert operations and len(checkpoints) >= 2
    if damage == "missing_operation":
        operations[0].unlink()
    elif damage == "duplicate_operation":
        (root / "operation-999999.json").write_bytes(operations[0].read_bytes())
    else:
        target = operations[0] if damage == "torn_operation" else (
            checkpoints[0] if damage in ("torn_checkpoint", "old_checkpoint") else _records(root, "result")[0])
        target.chmod(0o600)  # Corrupt only this test's artifact, even when publication is read-only.
        target.write_bytes(target.read_bytes()[:-1] if damage != "old_checkpoint" else b"{}")
    before = _snapshot(root)
    _reject(lambda: _resume(api, root, manifest))
    assert _snapshot(root) == before


@pytest.mark.parametrize("field", ("operation_count", "operation_prefix_hash", "next_cursor", "ledger_event_count", "ledger_tail_hash", "orders", "attempt_state", "remaining_cap", "action_state", "cash_benchmark", "buy_and_hold_benchmark", "reducer_versions", "numeric_policy_version"))
def test_checkpoint_fields_are_reconciled_instead_of_trusted(tmp_path: Path, field: str) -> None:
    api = _api()
    manifest, _, _ = _manifest(api)
    root = tmp_path / "run"
    result = _run(api, root, manifest, max_operations=4)
    raw = _json(result.checkpoint.canonical_bytes())
    raw[field] = 999 if field.endswith("count") else "sensitive-sentinel"
    before = _snapshot(root)
    def attempt() -> Any:
        checkpoint = api.ReplayCheckpoint.from_bytes(_canonical(raw))
        return _resume(api, root, manifest, checkpoint=checkpoint)
    _reject(attempt)
    assert _snapshot(root) == before


@pytest.mark.parametrize("supply", ("missing", "extra", "reordered", "changed", "foreign_checkpoint"))
def test_explicit_resume_evidence_must_equal_published_exact_prefix(tmp_path: Path, supply: str) -> None:
    api = _api()
    manifest, _, _ = _manifest(api, actions=True)
    root = tmp_path / "run"
    full = _run(api, root, manifest)
    other_manifest, _, _ = _manifest(api, run_id="run-bt05-foreign-checkpoint")
    other = _run(api, tmp_path / "other", other_manifest, max_operations=1)
    events = full.events
    kwargs = {}
    if supply == "missing":
        kwargs["events"] = events[:-1]
    elif supply == "extra":
        kwargs["events"] = events + (events[-1],)
    elif supply == "reordered":
        assert len(events) > 1
        kwargs["events"] = tuple(reversed(events))
    elif supply == "changed":
        kwargs["events"] = events
    else:
        kwargs["checkpoint"] = other.checkpoint
    before = _snapshot(root)
    def resume_corrupt_evidence() -> Any:
        if supply == "changed":
            # This event was returned by this fresh run; no cached source is mutated.
            object.__setattr__(events[0], "_event_id", "changed-label")
        return _resume(api, root, manifest, **kwargs)
    _reject(resume_corrupt_evidence)
    assert _snapshot(root) == before


def test_changed_manifest_or_new_run_over_existing_artifacts_rejects(tmp_path: Path) -> None:
    api = _api()
    manifest, fields, _ = _manifest(api)
    root = tmp_path / "run"
    _run(api, root, manifest, max_operations=1)
    changed = api.ReplayManifest(**{**fields, "seed": 18})
    before = _snapshot(root)
    _reject(lambda: _resume(api, root, changed))
    with api.ReplayRunner(root=root) as runner:
        _reject(lambda: runner.run(manifest))
    assert _snapshot(root) == before


def test_output_hash_rejects_valid_same_run_plan_not_owned_by_manifest() -> None:
    api = _api()
    manifest, fields, case = _manifest(api)
    a2, a3 = bt02._bt02_api(), bt03._bt03_api()
    intent = bt02._intent(a2, case, quantity=D("1"), plan_id="unowned-plan")
    outcome = fields["outcomes"][0]
    fill = bt03._make_fill(a2, case, intent=intent, outcome=outcome, policy=fields["cost_policy"])
    ledger = bt03._new_ledger(a3, case, opening_cash=fields["opening_cash"],
                              resolution_cutoff=fields["resolution_cutoff"])
    event = bt03._fill_event(a3, ledger, intent=intent, fill=fill, case=case,
                             outcome=outcome, policy=fields["cost_policy"], event_id="foreign-plan")
    ledger.append(event)
    _reject(lambda: manifest.economic_output_hash((event,), (ledger.balance(),)))


@pytest.mark.parametrize("result_kind", ("unknown", "wrapper", "bad_nav", "bad_order", "foreign_benchmark", "mutated_balance"))
def test_output_hash_accepts_only_fixed_valid_manifest_bound_result_schemas(tmp_path: Path, result_kind: str) -> None:
    api = _api()
    manifest, fields, _ = _manifest(api)
    result = _run(api, tmp_path / "run", manifest)
    if result_kind == "unknown":
        value = {"cash": "1"}
    elif result_kind == "wrapper":
        value = result
    elif result_kind == "bad_nav":
        value = type(result.nav_points[0])("available", None, None, True)
    elif result_kind == "bad_order":
        value = type(result.orders[0])("unowned-intent", D("0"), D("1"), D("1"), "filled", None)
    elif result_kind == "foreign_benchmark":
        foreign, _ = _fields(run_id=fields["run_id"], prices=("101", "101", "101"))
        value = bt04._api().BenchmarkRunner().run_buy_and_hold(foreign["sessions"], policy=foreign["buy_and_hold_policy"])
        assert value.run_valid
    else:
        value = copy.deepcopy(result.balances[-1])
        object.__setattr__(value, "cash", value.cash + D("1"))
    _reject(lambda: manifest.economic_output_hash(result.events, (value,)))


def test_economic_sequence_is_material_but_event_labels_are_artifact_lineage(tmp_path: Path) -> None:
    api = _api()
    manifest, _, _ = _manifest(api, actions=True)
    result = _run(api, tmp_path / "run", manifest)
    assert len(result.events) > 1
    _reject(lambda: manifest.economic_output_hash(tuple(reversed(result.events)), result.results))
    # Label exclusion never bypasses exact ID uniqueness or source/prefix validation.
    _reject(lambda: manifest.economic_output_hash(result.events + (result.events[0],), result.results))


@pytest.mark.parametrize("mutation", ("decimal_equal", "signed_zero", "utc_representation", "source_id", "hidden_field"))
def test_native_source_mutation_after_manifest_sealing_is_rejected(mutation: str) -> None:
    api = _api()
    manifest, fields, _ = _manifest(api)
    intent = fields["intents"][0]
    if mutation == "decimal_equal":
        object.__setattr__(intent, "quantity", D("3.00"))
    elif mutation == "signed_zero":
        object.__setattr__(fields["cost_policy"], "half_spread_bps", D("-0"))
    elif mutation == "utc_representation":
        object.__setattr__(intent, "created_at", intent.created_at.replace(tzinfo=timezone(timedelta(0), "other-UTC")))
    elif mutation == "source_id":
        object.__setattr__(intent, "plan_id", "changed-plan")
    else:
        object.__getattribute__(intent, "__dict__")["unknown"] = "sensitive-sentinel"
    for action in (manifest.semantic_input_hash, manifest.artifact_integrity_hash, manifest.canonical_bytes):
        _reject(action)


def test_completion_rechecks_sources_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    manifest, fields, _ = _manifest(api)
    a2 = bt02._bt02_api()
    original = a2.FillModel.simulate
    changed = False
    def mutate(*args: Any, **kwargs: Any) -> Any:
        nonlocal changed
        answer = original(*args, **kwargs)
        if not changed:
            changed = True
            object.__setattr__(fields["intents"][0], "quantity", D("3.000"))
        return answer
    monkeypatch.setattr(a2.FillModel, "simulate", staticmethod(mutate))
    root = tmp_path / "run"
    _reject(lambda: _run(api, root, manifest))
    assert changed
    assert not _records(root, "result")


class _Hostile:
    calls = 0
    def __getattribute__(self, name: str) -> Any:
        type(self).calls += 1
        raise AssertionError("hostile callback executed")
    def __iter__(self) -> Any:
        type(self).calls += 1
        raise AssertionError("hostile iteration executed")
    def __eq__(self, other: Any) -> bool:
        type(self).calls += 1
        raise AssertionError("hostile equality executed")
    def __hash__(self) -> int:
        type(self).calls += 1
        raise AssertionError("hostile hash executed")
    def __fspath__(self) -> str:
        type(self).calls += 1
        raise AssertionError("hostile path callback executed")


@pytest.mark.parametrize("field", ("bindings", "intents", "outcomes", "sessions", "cost_policy", "action_policy", "cash_benchmark_policy", "buy_and_hold_policy", "run_id", "configuration", "seed", "created_at"))
def test_hostile_values_reject_before_protocol_or_serializer_callbacks(field: str) -> None:
    api = _api()
    fields, _ = _fields()
    _Hostile.calls = 0
    _reject(lambda: api.ReplayManifest(**{**fields, field: _Hostile()}))
    assert _Hostile.calls == 0


def test_hostile_nested_model_keys_reject_before_hash_or_equality() -> None:
    api = _api()
    fields, _ = _fields()
    calls = []
    class Key(str):
        def __hash__(self) -> int:
            calls.append("hash")
            return str.__hash__(self)
        def __eq__(self, other: Any) -> bool:
            calls.append("equality")
            return str.__eq__(self, other)
    context = object.__getattribute__(fields["bindings"][0], "_context_snapshot")
    storage = dict(object.__getattribute__(context, "__dict__"))
    run_id = storage.pop("run_id")
    storage[Key("run_id")] = run_id
    object.__setattr__(context, "__dict__", storage)
    calls.clear()
    _reject(lambda: api.ReplayManifest(**fields))
    assert calls == []


@pytest.mark.parametrize("phase", ("before_admission", "after_hash"))
@pytest.mark.parametrize("target", ("quant_native", "note", "overlay_native", "context", "quant_hostile", "note_hostile", "overlay_hostile", "context_hostile", "unknown_nested"))
def test_nested_sig05_and_context_sources_are_refreshed_without_callbacks(phase: str, target: str) -> None:
    api = _api()
    fields, _ = _fields(kind="quant_llm")
    binding = fields["bindings"][0]
    envelope = object.__getattribute__(binding, "_envelope_snapshot")
    context = object.__getattribute__(binding, "_context_snapshot")
    manifest = api.ReplayManifest(**fields) if phase == "after_hash" else None
    if manifest is not None:
        manifest.semantic_input_hash()
    _Hostile.calls = 0
    if target in ("quant_native", "overlay_native"):
        source = envelope.quant if target == "quant_native" else envelope.overlay
        name = "score" if target == "quant_native" else "multiplier"
        original = object.__getattribute__(source, name)
        sign, digits, exponent = original.as_tuple()
        replacement = D((sign, digits + (0,), exponent - 1))
        assert replacement == original and replacement.as_tuple() != original.as_tuple()
        object.__setattr__(source, name, replacement)
    elif target == "note":
        object.__setattr__(envelope.note, "thesis", "Changed captured research content.")
    elif target == "context":
        object.__setattr__(context, "knowledge_cutoff", context.knowledge_cutoff + timedelta(microseconds=1))
    elif target == "unknown_nested":
        object.__getattribute__(envelope.note, "__dict__")["unknown"] = _Hostile()
    else:
        source, name = {"quant_hostile": (envelope.quant, "score"),
                        "note_hostile": (envelope.note, "thesis"),
                        "overlay_hostile": (envelope.overlay, "multiplier"),
                        "context_hostile": (context, "run_id")}[target]
        object.__setattr__(source, name, _Hostile())
    if phase == "before_admission":
        _reject(lambda: api.ReplayManifest(**fields))
    else:
        for action in (manifest.semantic_input_hash, manifest.artifact_integrity_hash, manifest.canonical_bytes):
            _reject(action)
    assert _Hostile.calls == 0


@pytest.mark.parametrize("invalid", ("list", "tuple_subclass", "generator", "cycle", "unknown_field", "unknown_version", "bool_seed", "float_seed", "surrogate", "nan", "infinity", "decimal_subclass", "wrong_priority"))
def test_strict_manifest_admission_rejects_ambiguous_or_unknown_values(invalid: str) -> None:
    api = _api()
    fields, _ = _fields()
    class TupleSubclass(tuple):
        pass
    class DecimalSubclass(Decimal):
        pass
    if invalid == "list":
        fields["bindings"] = list(fields["bindings"])
    elif invalid == "tuple_subclass":
        fields["bindings"] = TupleSubclass(fields["bindings"])
    elif invalid == "generator":
        fields["bindings"] = iter(fields["bindings"])
    elif invalid == "cycle":
        cycle: list[Any] = []
        cycle.append(cycle)
        fields["configuration"] = cycle
    elif invalid == "unknown_field":
        fields["unknown"] = "sensitive-sentinel"
    elif invalid == "unknown_version":
        fields["schema_version"] = "v999"
    elif invalid == "bool_seed":
        fields["seed"] = True
    elif invalid == "float_seed":
        fields["seed"] = 1.5
    elif invalid == "surrogate":
        fields["configuration"] = (("label", "\ud800"),)
    elif invalid == "wrong_priority":
        fields["priority_policy"] = "exact-id-priority"
    else:
        fields["opening_cash"] = {"nan": D("NaN"), "infinity": D("Infinity"),
                                   "decimal_subclass": DecimalSubclass("2000")}[invalid]
    _reject(lambda: api.ReplayManifest(**fields))


@pytest.mark.parametrize("invalid", ("duplicate", "escaped_duplicate", "unknown", "version", "nan", "float", "depth", "oversize", "surrogate", "trailing", "utf8"))
def test_checkpoint_raw_json_rejects_before_decode_or_unbounded_work(invalid: str, tmp_path: Path) -> None:
    api = _api()
    manifest, _, _ = _manifest(api)
    result = _run(api, tmp_path / "run", manifest, max_operations=0)
    raw = result.checkpoint.canonical_bytes()
    field = next(iter(_json(raw)))
    repeated = json.dumps(field).encode()
    if invalid in ("duplicate", "escaped_duplicate"):
        key = repeated if invalid == "duplicate" else f'"\\u{ord(field[0]):04x}{field[1:]}"'.encode()
        altered = b"{" + key + b":null," + raw[1:]
    elif invalid in ("unknown", "version"):
        data = _json(raw)
        data["unknown" if invalid == "unknown" else "schema_version"] = "v999"
        altered = _canonical(data)
    else:
        altered = {"nan": b'{"value":NaN}', "float": b'{"value":1.5}',
                   "depth": b"[" * 65 + b"0" + b"]" * 65,
                   "oversize": b" " * (64 * 1024 * 1024 + 1),
                   "surrogate": b'{"value":"\\ud800"}', "trailing": raw + b"{}",
                   "utf8": b'{"value":"\xff"}'}[invalid]
    _reject(lambda: api.ReplayCheckpoint.from_bytes(altered))


@pytest.mark.parametrize("field,value", (
    ("seed", 1 << 256), ("opening_cash", D("1E65")),
    ("opening_cash", D("1E-65")), ("opening_cash", D("1" * 129)),
    ("opening_cash", D("1E1000000000")), ("opening_cash", D("1E-1000000000")),
    ("configuration", (("x", "x" * 65537),)),
    ("configuration", (("x", "\u00e9" * 32769),)),
    ("configuration", tuple((f"k{i:04d}", "v") for i in range(4097))),
))
def test_frozen_scalar_and_collection_resource_limits(field: str, value: Any) -> None:
    api = _api()
    fields, _ = _fields()
    _reject(lambda: api.ReplayManifest(**{**fields, field: value}))


def test_exact_text_and_integer_limits_and_decimal_context_are_deterministic() -> None:
    api = _api()
    fields, _ = _fields()
    fields.update(seed=(1 << 256) - 1, configuration=(("label", "\u00e9" * 32768),))
    manifest = api.ReplayManifest(**fields)
    expected = (manifest.semantic_bytes(), manifest.semantic_input_hash(), manifest.canonical_bytes())
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = context.traps[Rounded] = True
        assert (manifest.semantic_bytes(), manifest.semantic_input_hash(), manifest.canonical_bytes()) == expected
    left = api.ReplayManifest(**{**fields, "opening_cash": D("2000.00")})
    assert left.semantic_input_hash() == manifest.semantic_input_hash()
    assert left.artifact_integrity_hash() != manifest.artifact_integrity_hash()


@pytest.mark.parametrize("field,limit", (("bindings", 256), ("intents", 256), ("outcomes", 4096), ("sessions", 16)))
def test_record_count_one_over_rejects_before_nested_validation(field: str, limit: int) -> None:
    api = _api()
    fields, _ = _fields()
    _Hostile.calls = 0
    _reject(lambda: api.ReplayManifest(**{**fields, field: (_Hostile(),) * (limit + 1)}))
    assert _Hostile.calls == 0


@pytest.mark.parametrize("case", ("relative", "missing", "parent", "symlink_root", "symlink_ancestor", "file", "hostile"))
def test_explicit_root_admission_cannot_escape_or_invoke_pathlike(tmp_path: Path, case: str) -> None:
    api = _api()
    target = tmp_path / "target"
    target.mkdir()
    sentinel = target / "outside-sentinel"
    sentinel.write_bytes(b"unchanged")
    _Hostile.calls = 0
    if case == "relative":
        root: Any = Path("relative")
    elif case == "missing":
        root = tmp_path / "missing"
    elif case == "parent":
        root = target / ".." / "target"
    elif case in ("symlink_root", "symlink_ancestor"):
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        root = link if case == "symlink_root" else link / "child"
        if case == "symlink_ancestor":
            (target / "child").mkdir()
    elif case == "file":
        root = sentinel
    else:
        root = _Hostile()
    _reject(lambda: api.ReplayRunner(root=root))
    assert sentinel.read_bytes() == b"unchanged" and _Hostile.calls == 0


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "fifo", "directory", "oversize", "unknown"))
def test_unsafe_root_entries_reject_without_reading_or_changing_outside_bytes(tmp_path: Path, kind: str) -> None:
    api = _api()
    manifest, _, _ = _manifest(api)
    root = tmp_path / "run"
    root.mkdir()
    sentinel = tmp_path / "outside"
    sentinel.write_bytes(b"outside-unchanged")
    path = root / "operation-000000.json"
    if kind == "symlink":
        path.symlink_to(sentinel)
    elif kind == "hardlink":
        os.link(sentinel, path)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "oversize":
        with path.open("wb") as handle:
            handle.truncate(64 * 1024 * 1024 + 1)
    else:
        path.write_bytes(b"{}")
    def open_run() -> Any:
        with api.ReplayRunner(root=root) as runner:
            return runner.resume(manifest)
    _reject(open_run)
    assert sentinel.read_bytes() == b"outside-unchanged"


def test_root_directory_entry_bound_fails_closed(tmp_path: Path) -> None:
    api = _api()
    root = tmp_path / "run"
    root.mkdir()
    for index in range(16385):
        (root / f"abandoned-{index:05d}").touch()
    _reject(lambda: api.ReplayRunner(root=root))
    assert len(tuple(root.iterdir())) == 16385


def test_second_writer_rejects_and_releasing_owner_allows_resume(tmp_path: Path) -> None:
    api = _api()
    manifest, _, _ = _manifest(api)
    root = tmp_path / "run"
    root.mkdir()
    with api.ReplayRunner(root=root) as owner:
        partial = owner.run(manifest, max_operations=1)
        _reject(lambda: api.ReplayRunner(root=root))
    resumed = _resume(api, root, manifest, checkpoint=partial.checkpoint)
    assert resumed.run_valid


def test_process_death_releases_kernel_lock_without_removing_ownership_inode(tmp_path: Path) -> None:
    api = _api()
    manifest, _, _ = _manifest(api)
    root = tmp_path / "run"
    root.mkdir()
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        try:
            runner = api.ReplayRunner(root=root)
            runner.run(manifest, max_operations=3)
            os.write(write_fd, b"ready")
        except BaseException:
            os._exit(2)
        os._exit(0)  # Deliberately bypass context-manager close and Python finalizers.
    os.close(write_fd)
    try:
        receipt = os.read(read_fd, 16)
    finally:
        os.close(read_fd)
    _, status = os.waitpid(child, 0)
    assert receipt == b"ready" and os.waitstatus_to_exitcode(status) == 0
    before = dict(_snapshot(root))
    recovered = _resume(api, root, manifest)
    assert recovered.run_valid
    after = dict(_snapshot(root))
    assert all(after.get(name) == raw for name, raw in before.items())


def test_deterministic_two_writer_race_has_one_append_owner(tmp_path: Path) -> None:
    api = _api()
    manifest, _, _ = _manifest(api)
    root = tmp_path / "run"
    root.mkdir()
    entered, release = Event(), Event()
    def owner() -> Any:
        with api.ReplayRunner(root=root) as runner:
            entered.set()
            assert release.wait(10)
            return runner.run(manifest)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owner)
        assert entered.wait(10)
        try:
            _reject(lambda: api.ReplayRunner(root=root))
        finally:
            release.set()
        result = future.result(timeout=20)
    assert result.run_valid
    assert _economic(_resume(api, root, manifest)) == _economic(result)


@pytest.mark.parametrize("replace", ("root", "lock"))
def test_pinned_root_and_lock_inode_replacement_prevents_publication(tmp_path: Path, replace: str) -> None:
    api = _api()
    manifest, _, _ = _manifest(api)
    root = tmp_path / "run"
    root.mkdir()
    with api.ReplayRunner(root=root) as runner:
        if replace == "root":
            root.rename(tmp_path / "original")
            root.mkdir()
            sentinel = root / "outside-sentinel"
        else:
            locks = tuple(root.iterdir())
            assert len(locks) == 1 and locks[0].is_file()
            locks[0].rename(root / "abandoned-original-lock")
            sentinel = locks[0]
        sentinel.write_bytes(b"unchanged")
        _reject(lambda: runner.run(manifest))
        assert sentinel.read_bytes() == b"unchanged"


def test_local_success_and_negative_paths_deny_egress_process_environment_and_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    manifest, fields, _ = _manifest(api)
    root = tmp_path / "run"
    root.mkdir()
    changed = api.ReplayManifest(**{**fields, "seed": 18})
    calls = []
    def deny(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        raise AssertionError("BT-05 forbidden side effect")
    # Build all sources first, then arm the success and failure paths themselves.
    with monkeypatch.context() as patch:
        for target, name in ((socket, "socket"), (socket, "create_connection"),
                             (urllib.request, "urlopen"), (subprocess, "Popen"),
                             (subprocess, "run"), (os, "getenv"), (os, "system"),
                             (zoneinfo, "ZoneInfo")):
            patch.setattr(target, name, deny)
        patch.setattr(type(os.environ), "__getitem__", deny)
        patch.setattr(type(os.environ), "get", deny)
        controls = (
            lambda: socket.create_connection(("denied.invalid", 443)),
            lambda: subprocess.run(("unapproved-command",)),
            lambda: os.getenv("BT05_FORBIDDEN_ENVIRONMENT"),
            lambda: zoneinfo.ZoneInfo("UTC"),
        )
        for control in controls:
            with pytest.raises(AssertionError, match="BT-05 forbidden side effect"):
                control()
        assert len(calls) == len(controls)
        calls.clear()
        with api.ReplayRunner(root=root) as runner:
            partial = runner.run(manifest, max_operations=3)
        with api.ReplayRunner(root=root) as runner:
            _reject(lambda: runner.resume(changed))
            result = runner.resume(manifest, checkpoint=partial.checkpoint)
        assert result.run_valid
    assert calls == []


def test_backtest_imports_and_source_do_not_add_forbidden_runtime_dependencies() -> None:
    _api()
    forbidden = ("tradingagents", "subprocess", "socket", "urllib", "requests", "httpx",
                 "langgraph", "langchain", "openai", "anthropic", "dotenv", "keyring")
    for module in ("manifest", "replay"):
        path = ROOT / "mytradingalpha" / "backtest" / f"{module}.py"
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports = (node.module or "",)
            else:
                imports = ()
            assert not any(name == prefix or name.startswith(prefix + ".")
                           for name in imports for prefix in forbidden)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "__import__", "getattr"}
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"environ", "getenv", "system", "popen", "ZoneInfo"}


def test_exact_source_bytes_and_native_witnesses_survive_resume(tmp_path: Path) -> None:
    api = _api()
    manifest, fields, case = _manifest(api, kind="quant_llm")
    exact = manifest.canonical_bytes()
    # Fixed v1 records retain an existing binding's exact canonical UTF-8 bytes
    # and native storage witness; this is not a serializer protocol or key filter.
    binding = fields["bindings"][0]
    expected_source = {
        "source_type": "SessionBinding",
        "canonical_utf8": object.__getattribute__(binding, "_sealed_source_json").decode("utf-8"),
        "native_witness": object.__getattribute__(binding, "_sealed_storage_bytes").hex(),
    }
    exact_sources = _json(exact)["exact_sources"]
    assert expected_source in exact_sources
    restored_source = expected_source["canonical_utf8"].encode("utf-8")
    restored_native = bytes.fromhex(expected_source["native_witness"])
    assert restored_source == object.__getattribute__(binding, "_sealed_source_json")
    assert restored_native == object.__getattribute__(binding, "_sealed_storage_bytes")
    assert case.envelope.note.note_id.encode() in restored_source
    assert case.envelope.quant.signal_id.encode() in restored_source
    sources = (case.bundle.model_dump_json(), case.envelope.model_dump_json(),
               fields["intents"][0].canonical_bytes(), fields["outcomes"][0].bar.model_dump_json())
    partial = _run(api, tmp_path / "run", manifest, max_operations=3)
    result = _resume(api, tmp_path / "run", manifest, events=partial.events)
    assert result.run_valid and manifest.canonical_bytes() == exact
    persisted = _records(tmp_path / "run", "manifest")
    assert len(persisted) == 1 and persisted[0].read_bytes() == exact
    assert expected_source in _json(persisted[0].read_bytes())["exact_sources"]
    assert sources == (case.bundle.model_dump_json(), case.envelope.model_dump_json(),
                       fields["intents"][0].canonical_bytes(), fields["outcomes"][0].bar.model_dump_json())
    assert manifest.artifact_integrity_hash() != result.artifact_integrity_hash


# P1 repair RED: caller-recomputed seals are not ownership or issuer authority.
def _p1_expect_prohibited_mutation(action: Any) -> None:
    # A repaired implementation may remove the old fields/helpers or reject the
    # installation itself. It need not retain an unsafe private mutation API.
    with pytest.raises((AttributeError, TypeError, ValueError, RuntimeError, OverflowError)) as caught:
        action()
    assert len(str(caught.value)) <= 256
    assert caught.value.__cause__ is None


def test_bt05_p1_resealed_benchmark_cache_cannot_authorize_counterfeit_cash_nav() -> None:
    api = _api()
    manifest, fields, _ = _manifest(api)
    runner = bt04._api().BenchmarkRunner()
    correct_cash = runner.run_cash(fields["sessions"], policy=fields["cash_benchmark_policy"])
    correct_bh = runner.run_buy_and_hold(fields["sessions"], policy=fields["buy_and_hold_policy"])
    assert correct_cash.run_valid and correct_bh.run_valid
    assert all(point.value == D("2000") for point in correct_cash.nav_points)
    genuine_hash = manifest.economic_output_hash((), (correct_cash,))
    assert genuine_hash.startswith("sha256:") and len(genuine_hash) == 71

    forged_points = tuple(type(point)(
        status="available", value=D("2001"), reason_code=None, run_valid=True,
        formula_version=point.formula_version, numeric_policy_version=point.numeric_policy_version,
    ) for point in correct_cash.nav_points)
    forged_cash = type(correct_cash)(
        status=correct_cash.status, run_valid=correct_cash.run_valid,
        reason_code=correct_cash.reason_code, events=correct_cash.events,
        balances=correct_cash.balances, nav_points=forged_points, policy=correct_cash.policy,
    )
    assert all(point.value == D("2001") for point in forged_cash.nav_points)
    _p1_expect_prohibited_mutation(lambda: manifest.economic_output_hash((), (forged_cash,)))
    print("P1 Cash controls PASS: real NAV 2000 accepted; ordinary counterfeit NAV 2001 rejected")

    def replace_and_reseal() -> None:
        module = importlib.import_module("mytradingalpha.backtest.manifest")
        replacement = (forged_cash, correct_bh)
        object.__setattr__(manifest, "_benchmark_cache", replacement)
        object.__setattr__(manifest, "_benchmark_seal", module._encode_native(module._native(replacement)))
        manifest.economic_output_hash((), (forged_cash,))

    _p1_expect_prohibited_mutation(replace_and_reseal)


def test_bt05_p1_resealed_owned_sources_cannot_authorize_changed_seed() -> None:
    api = _api()
    manifest, fields, _ = _manifest(api)
    original_hash = manifest.semantic_input_hash()
    changed_seed = fields["seed"] + 1
    fresh = api.ReplayManifest(**{**fields, "seed": changed_seed})
    assert fresh.semantic_input_hash() != original_hash
    assert manifest.semantic_input_hash() == original_hash
    print("P1 owned-source controls PASS: a fresh changed-seed manifest is valid and has a distinct input identity")

    def change_owned_and_reseal() -> None:
        module = importlib.import_module("mytradingalpha.backtest.manifest")
        owned = object.__getattribute__(manifest, "_owned")
        owned["seed"] = changed_seed
        object.__setattr__(manifest, "_owned_native", module._source_capture(owned))
        object.__setattr__(manifest, "_integrity", hashlib.sha256(
            object.__getattribute__(manifest, "_cache_bytes")()
        ).digest())
        manifest.semantic_input_hash()

    _p1_expect_prohibited_mutation(change_owned_and_reseal)


def test_bt05_p1_existing_manifest_cannot_be_reinitialized_in_place() -> None:
    api = _api()
    manifest, fields, _ = _manifest(api)
    original_hash = manifest.semantic_input_hash()
    changed = {**fields, "seed": fields["seed"] + 1}
    fresh = api.ReplayManifest(**changed)
    assert fresh.semantic_input_hash() != original_hash
    assert manifest.semantic_input_hash() == original_hash
    print("P1 constructor controls PASS: fresh construction works without changing the existing manifest")

    def reinitialize_existing() -> None:
        api.ReplayManifest.__init__(manifest, **changed)
        manifest.semantic_input_hash()

    _p1_expect_prohibited_mutation(reinitialize_existing)

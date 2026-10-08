"""SIG-05 signal envelope and explicit-variant contract tests.

Inputs reuse the sealed synthetic note and quant signal from SIG-04. Imports of
the SIG-05 API stay inside test bodies so this file collects on the prerequisite
base and produces an auditable missing-contract RED.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import io
import json
import os
import re
import socket
import subprocess
import urllib.request
from copy import deepcopy
from decimal import ROUND_UP, Decimal, Inexact, Rounded, getcontext, setcontext
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mytradingalpha.contracts.schemas import Mode, NetworkPolicy, RunContext
from mytradingalpha.contracts.signals import QuantSignal
from tests.productionization.quant import test_signal as quant_fixtures
from tests.productionization.research import test_overlay as overlay_fixtures

ROOT = Path(__file__).resolve().parents[3]
ENVELOPE_HASH_DOMAIN = b"mytradingalpha:sig05:signal-envelope:v1\0"


def _api() -> SimpleNamespace:
    """Load SIG-05 only while a test is running, allowing a useful RED."""

    try:
        contracts = importlib.import_module("mytradingalpha.contracts.signals")
        variants = importlib.import_module("mytradingalpha.quant.variants")
        envelope = importlib.import_module("mytradingalpha.quant.envelope")
        return SimpleNamespace(
            SignalEnvelope=contracts.SignalEnvelope,
            SignalVariant=contracts.SignalVariant,
            SignalEnvelopeError=contracts.SignalEnvelopeError,
            VariantRegistry=variants.VariantRegistry,
            combine_quant_overlay=envelope.combine_quant_overlay,
            contracts_module=contracts,
            variants_module=variants,
            envelope_module=envelope,
        )
    except (ModuleNotFoundError, AttributeError) as exc:
        missing = getattr(exc, "name", None) or str(exc)
        pytest.fail(f"SIG-05 RED: envelope and variant API is missing ({missing})")


@pytest.fixture(scope="module")
def bound_sources() -> tuple[Any, Any, Any]:
    """Reuse SIG-04's sealed, deterministic EvidenceBundle/Note/QuantSignal."""

    fixture_function = overlay_fixtures.bound_inputs.__wrapped__
    return fixture_function()


def _context(
    note: Any,
    *,
    variant_id: str | None = None,
    run_id: str | None = None,
    bundle_id: str | None = None,
    bundle_hash: str | None = None,
    calendar_id: str | None = None,
    decision_time: str = "2024-07-02T20:04:00Z",
    knowledge_cutoff: str | None = None,
    earliest_execution_time: str = "2024-07-03T13:30:00Z",
    network_policy: NetworkPolicy | None = None,
) -> RunContext:
    return RunContext(
        schema_version="v1",
        run_id=run_id or note.run_id,
        mode=Mode.HISTORICAL,
        variant_id=variant_id or note.variant_id,
        decision_time=decision_time,
        knowledge_cutoff=knowledge_cutoff or note.knowledge_cutoff,
        earliest_execution_time=earliest_execution_time,
        bundle_id=bundle_id or note.bundle_id,
        bundle_hash=bundle_hash or note.bundle_hash,
        calendar_id=calendar_id or note.calendar_id,
        base_currency="USD",
        network_policy=network_policy or NetworkPolicy(),
    )


def _registry(api: SimpleNamespace, variant_id: str, kind: str) -> Any:
    return api.VariantRegistry().register(variant_id, kind=kind)


def _rehash_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Recompute a valid content ID after a semantic mutation."""

    changed = deepcopy(payload)
    prefix = changed["envelope_id"].split(":", 1)[0]
    changed.pop("envelope_id")
    encoded = json.dumps(
        changed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")
    changed["envelope_id"] = (
        f"{prefix}:{hashlib.sha256(ENVELOPE_HASH_DOMAIN + encoded).hexdigest()}"
    )
    return changed


def _llm_inputs(
    note: Any,
    quant_signal: Any,
    *,
    context_updates: dict[str, object] | None = None,
    multiplier: str = "0.5",
) -> tuple[RunContext, Any, Any]:
    api = _api()
    context = _context(note, **(context_updates or {}))
    candidate = overlay_fixtures._candidate(note, quant_signal, multiplier=multiplier)
    overlay = api.contracts_module.LLMOverlay.model_validate(candidate)
    registry = _registry(api, context.variant_id, "quant_llm")
    return context, registry, overlay


def _assert_no_trade(envelope: Any, *, expected_variant: str = "quant_llm") -> None:
    assert envelope.no_trade is True
    assert envelope.variant.kind == expected_variant
    assert envelope.effective_score == Decimal("0")
    assert envelope.effective_score.as_tuple().exponent == -24
    assert envelope.effective_multiplier == Decimal("0")
    assert envelope.effective_multiplier.as_tuple().exponent == -24
    assert envelope.reason_codes
    assert all(
        isinstance(reason, Enum)
        and type(reason).__module__ == "mytradingalpha.contracts.signals"
        and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", str(reason.value))
        for reason in envelope.reason_codes
    )


def _expect_safe_error(api: SimpleNamespace, call: Any, *canaries: str) -> None:
    with pytest.raises(api.SignalEnvelopeError) as exc_info:
        call()
    assert exc_info.value.no_trade is True
    reason = exc_info.value.reason_code
    reason_text = reason.value if isinstance(reason, Enum) else reason
    assert type(reason_text) is str
    assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason_text)
    for canary in canaries:
        assert canary not in str(exc_info.value)


def test_sig05_api_exists_and_is_owned_by_contract_and_quant_modules() -> None:
    api = _api()
    assert api.SignalEnvelope.__module__ == "mytradingalpha.contracts.signals"
    assert api.SignalVariant.__module__ == "mytradingalpha.contracts.signals"
    assert api.VariantRegistry.__module__ == "mytradingalpha.quant.variants"
    assert api.combine_quant_overlay.__module__ == "mytradingalpha.quant.envelope"


def test_variant_registry_returns_immutable_explicit_snapshots() -> None:
    api = _api()
    empty = api.VariantRegistry()
    quant_only = empty.register("variant-quant-only", kind="quant_only")
    quant_llm = quant_only.register("variant-quant-llm", kind="quant_llm")

    assert quant_llm != quant_only
    assert quant_only != empty
    _expect_safe_error(api, lambda: empty.resolve("variant-quant-only"))
    _expect_safe_error(api, lambda: quant_only.resolve("variant-quant-llm"))
    assert quant_llm.resolve("variant-quant-only").variant_id == "variant-quant-only"
    assert quant_llm.resolve("variant-quant-llm").variant_id == "variant-quant-llm"
    assert quant_only.resolve("variant-quant-only").variant_hash == (
        "sha256:b9f7a3c63f356cea98b1d04bac32d6047ae485ef81e034560fbd837533f8a3e8"
    )
    assert quant_llm.resolve("variant-quant-llm").variant_hash == (
        "sha256:936b6d3272a721e61bd66f8730d73d51c017a02b65896ac7fb5fae816b31ebfa"
    )
    variant_json = json.dumps(
        quant_only.resolve("variant-quant-only").model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises((TypeError, ValueError, ValidationError)):
        api.SignalVariant.model_validate_json(variant_json)
    with pytest.raises((TypeError, ValueError, ValidationError)):
        TypeAdapter(api.SignalVariant).validate_json(variant_json)

    # Mutating objects returned through either read path cannot alter a saved snapshot.
    resolved = quant_only.resolve("variant-quant-only")
    dict.__setitem__(object.__getattribute__(resolved, "__dict__"), "kind", "quant_llm")
    assert quant_only.resolve("variant-quant-only").kind == "quant_only"
    assert quant_llm.resolve("variant-quant-only").kind == "quant_only"


@pytest.mark.parametrize(
    ("first_id", "first_kind", "second_id", "second_kind"),
    [
        ("variant-one", "quant_only", "variant-one", "quant_llm"),
        ("variant-one", "quant_only", "variant-two", "quant_only"),
        ("variant-one", "quant_only", "variant-two", "unregistered"),
    ],
)
def test_registry_rejects_duplicate_identity_kind_and_unknown_kind(
    first_id: str,
    first_kind: str,
    second_id: str,
    second_kind: str,
) -> None:
    api = _api()
    registry = _registry(api, first_id, first_kind)
    before = registry.resolve(first_id).model_dump(mode="json")
    _expect_safe_error(
        api,
        lambda: registry.register(second_id, kind=second_kind),
    )
    assert registry.resolve(first_id).model_dump(mode="json") == before


def test_registry_is_bounded_and_unknown_identity_has_no_default() -> None:
    api = _api()
    registry = api.VariantRegistry().register("variant-one", kind="quant_only")
    registry = registry.register("variant-two", kind="quant_llm")
    before = {
        variant_id: registry.resolve(variant_id).model_dump(mode="json")
        for variant_id in ("variant-one", "variant-two")
    }
    _expect_safe_error(
        api,
        lambda: registry.register("variant-three", kind="quant_only"),
    )
    assert {
        variant_id: registry.resolve(variant_id).model_dump(mode="json")
        for variant_id in ("variant-one", "variant-two")
    } == before
    _expect_safe_error(api, lambda: registry.resolve("variant-unregistered"))


def test_variant_ids_are_bounded_and_artifact_safe() -> None:
    api = _api()
    registry = api.VariantRegistry()
    for invalid_id in ("../variant", "variant/../other", "x" * 129, "secret=SIG05_ID_CANARY"):
        _expect_safe_error(
            api,
            lambda invalid_id=invalid_id: registry.register(
                invalid_id,
                kind="quant_only",
            ),
            "SIG05_ID_CANARY",
        )


def test_quant_only_preserves_score_and_rejects_any_research_source(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context = _context(note, variant_id="variant-quant-only")
    registry = _registry(api, context.variant_id, "quant_only")

    envelope = api.combine_quant_overlay(quant_signal, context=context, registry=registry)

    assert envelope.variant.kind == "quant_only"
    assert envelope.quant.signal_id == quant_signal.signal_id
    assert envelope.note is None
    assert envelope.overlay is None
    assert envelope.effective_score == quant_signal.score.quantize(Decimal("0.000000000000000000000000"))
    assert envelope.effective_multiplier == Decimal("1.000000000000000000000000")
    assert envelope.effective_action == "eligible"
    assert envelope.no_trade is False
    _expect_safe_error(
        api,
        lambda: api.combine_quant_overlay(
            quant_signal,
            context=context,
            registry=registry,
            note=note,
        ),
    )

    candidate = overlay_fixtures._candidate(note, quant_signal)
    supplied_overlay = api.contracts_module.LLMOverlay.model_validate(candidate)
    _expect_safe_error(
        api,
        lambda: api.combine_quant_overlay(
            quant_signal,
            context=context,
            registry=registry,
            overlay=supplied_overlay,
        ),
    )


def test_quant_llm_attenuates_without_amplification_and_keeps_full_lineage(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    attenuating = api.contracts_module.LLMOverlay.model_validate(
        overlay_fixtures._candidate(note, quant_signal, multiplier="0.25")
    )

    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=attenuating,
    )

    assert envelope.variant.kind == "quant_llm"
    assert envelope.context.variant_id == note.variant_id
    assert envelope.note.note_id == note.note_id
    assert envelope.note.note_hash == note.note_hash
    assert envelope.overlay.overlay_id == attenuating.overlay_id
    assert envelope.effective_multiplier == Decimal("0.25").quantize(
        Decimal("0.000000000000000000000000")
    )
    assert envelope.effective_score == (quant_signal.score * Decimal("0.25")).quantize(
        Decimal("0.000000000000000000000000")
    )
    assert abs(envelope.effective_score) <= abs(quant_signal.score)
    assert envelope.effective_action == "attenuated"
    assert envelope.no_trade is False


@pytest.mark.parametrize("missing", ["note", "overlay", "both"])
def test_quant_llm_missing_source_fails_closed_in_same_variant_without_fallback(
    bound_sources: tuple[Any, Any, Any],
    missing: str,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    supplied_note = None if missing in {"note", "both"} else note
    supplied_overlay = None if missing in {"overlay", "both"} else overlay

    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=supplied_note,
        overlay=supplied_overlay,
    )

    _assert_no_trade(envelope)
    if supplied_note is None:
        assert envelope.note is None
        assert envelope.overlay is None
    else:
        assert envelope.note.canonical_bytes() == note.canonical_bytes()
        assert envelope.note.note_hash == note.note_hash
        if supplied_overlay is None:
            assert envelope.overlay is None
        else:
            assert envelope.overlay.overlay_id == overlay.overlay_id
            assert envelope.overlay.model_dump(mode="json") == overlay.model_dump(mode="json")
    assert envelope.variant.variant_id == context.variant_id


@pytest.mark.parametrize(
    ("action", "abstain", "multiplier", "expected_action"),
    [
        ("veto", False, "0", "vetoed"),
        (None, True, "0", "abstain"),
        ("attenuate", False, "0", "abstain"),
    ],
)
def test_veto_abstention_and_zero_multiplier_are_no_trade(
    bound_sources: tuple[Any, Any, Any],
    action: str | None,
    abstain: bool,
    multiplier: str,
    expected_action: str,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, _ = _llm_inputs(note, quant_signal)
    overlay = api.contracts_module.LLMOverlay.model_validate(
        overlay_fixtures._candidate(
            note,
            quant_signal,
            action=action,
            abstain=abstain,
            multiplier=multiplier,
        )
    )

    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )

    _assert_no_trade(envelope)
    assert envelope.effective_action == expected_action


def test_invalid_quant_is_no_trade_and_malformed_quant_is_rejected(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    bundle, note, quant_signal = bound_sources
    api = _api()
    context, registry, _ = _llm_inputs(note, quant_signal)
    invalid = overlay_fixtures._invalid_quant_signal(bundle, note)
    invalid_overlay = api.contracts_module.LLMOverlay.model_validate(
        overlay_fixtures._candidate(note, invalid)
    )

    envelope = api.combine_quant_overlay(
        invalid,
        context=context,
        registry=registry,
        note=note,
        overlay=invalid_overlay,
    )
    _assert_no_trade(envelope)
    assert "quant_invalid" in {str(item.value if hasattr(item, "value") else item) for item in envelope.reason_codes}

    corrupted_storage = object.__getattribute__(quant_signal, "__dict__")
    original_score = dict.__getitem__(corrupted_storage, "score")
    valid_overlay = api.contracts_module.LLMOverlay.model_validate(
        overlay_fixtures._candidate(note, quant_signal)
    )
    dict.__setitem__(corrupted_storage, "score", Decimal("1E+999999"))
    try:
        _expect_safe_error(
            api,
            lambda: api.combine_quant_overlay(
                quant_signal,
                context=context,
                registry=registry,
                note=note,
                overlay=valid_overlay,
            ),
        )
    finally:
        dict.__setitem__(corrupted_storage, "score", original_score)


def test_quant_only_invalid_signal_is_zero_no_trade_without_overlay_fallback(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    bundle, note, _ = bound_sources
    api = _api()
    invalid = overlay_fixtures._invalid_quant_signal(bundle, note)
    context = _context(note, variant_id="variant-quant-only")
    registry = _registry(api, context.variant_id, "quant_only")

    envelope = api.combine_quant_overlay(invalid, context=context, registry=registry)

    _assert_no_trade(envelope, expected_variant="quant_only")
    assert envelope.note is None
    assert envelope.overlay is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "run-quant-other"),
        ("bundle_id", "bundle-quant-other"),
        ("bundle_hash", f"sha256:{'1' * 64}"),
        ("as_of", "2024-07-02T20:05:00Z"),
    ],
)
def test_rehashed_quant_context_identity_and_time_mismatches_raise(
    bound_sources: tuple[Any, Any, Any],
    field: str,
    value: str,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, _ = _llm_inputs(note, quant_signal)
    payload = quant_signal.model_dump(mode="json")
    payload[field] = value
    changed_signal = QuantSignal.model_validate(quant_fixtures._rekey_signal_payload(payload))
    overlay = api.contracts_module.LLMOverlay.model_validate(
        overlay_fixtures._candidate(note, changed_signal)
    )

    _expect_safe_error(
        api,
        lambda: api.combine_quant_overlay(
            changed_signal,
            context=context,
            registry=registry,
            note=note,
            overlay=overlay,
        ),
    )


def test_rehashed_quant_instrument_mismatch_sanitizes_sources_in_same_variant(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, _ = _llm_inputs(note, quant_signal)
    payload = quant_signal.model_dump(mode="json")
    payload["instrument_id"] = "instrument-quant-other"
    changed_signal = QuantSignal.model_validate(quant_fixtures._rekey_signal_payload(payload))
    overlay = api.contracts_module.LLMOverlay.model_validate(
        overlay_fixtures._candidate(note, changed_signal)
    )

    envelope = api.combine_quant_overlay(
        changed_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )

    _assert_no_trade(envelope)
    assert envelope.note is None
    assert envelope.overlay is None


def test_zero_quant_score_has_zero_influence_and_no_trade(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    quant_payload = quant_signal.model_dump(mode="json")
    quant_payload["score"] = "0.000000000000"
    zero_signal = QuantSignal.model_validate(quant_fixtures._rekey_signal_payload(quant_payload))
    context = _context(note, variant_id="variant-quant-only")
    registry = _registry(api, context.variant_id, "quant_only")

    envelope = api.combine_quant_overlay(zero_signal, context=context, registry=registry)

    assert envelope.effective_score == Decimal("0").quantize(
        Decimal("0.000000000000000000000000")
    )
    assert envelope.effective_action == "abstain"
    assert envelope.no_trade is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("note_id", "note:other"),
        ("note_hash", f"sha256:{'0' * 64}"),
        ("quant_signal_id", f"quant-signal:{'0' * 64}"),
        ("run_id", "run-other"),
        ("bundle_id", "bundle-other"),
        ("bundle_hash", f"sha256:{'0' * 64}"),
        ("instrument_id", "instrument-other"),
        ("evidence_ids", ["actions:uncited-record"]),
        ("generated_at", "2024-07-02T20:05:00Z"),
    ],
)
def test_rehashed_overlay_lineage_mismatches_fail_closed_in_quant_llm_variant(
    bound_sources: tuple[Any, Any, Any],
    field: str,
    value: object,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, _ = _llm_inputs(note, quant_signal)
    candidate = overlay_fixtures._candidate(note, quant_signal, **{field: value})
    # _candidate recomputes the overlay content ID, so this exercises source
    # lineage validation rather than a stale overlay hash.
    overlay = api.contracts_module.LLMOverlay.model_validate(candidate)

    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )
    _assert_no_trade(envelope)
    assert envelope.variant.kind == "quant_llm"
    assert envelope.note.canonical_bytes() == note.canonical_bytes()
    assert envelope.note.note_hash == note.note_hash
    assert envelope.overlay is None


@pytest.mark.parametrize(
    "field_update",
    [
        {"run_id": "run-other"},
        {"variant_id": "variant-other"},
        {"bundle_id": "bundle-other"},
        {"bundle_hash": f"sha256:{'0' * 64}"},
        {"calendar_id": "calendar-other"},
        {"knowledge_cutoff": "2024-07-02T20:00:00Z"},
    ],
)
def test_exact_context_identity_and_cutoff_mismatches_fail_closed(
    bound_sources: tuple[Any, Any, Any],
    field_update: dict[str, object],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    update = dict(field_update)
    context = _context(note, **update)
    registry = _registry(api, context.variant_id, "quant_llm")
    overlay = api.contracts_module.LLMOverlay.model_validate(
        overlay_fixtures._candidate(note, quant_signal)
    )

    _expect_safe_error(
        api,
        lambda: api.combine_quant_overlay(
            quant_signal,
            context=context,
            registry=registry,
            note=note,
            overlay=overlay,
        ),
    )


def test_unregistered_context_variant_never_switches_to_available_variant(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context = _context(note, variant_id="variant-unregistered")
    registry = api.VariantRegistry().register(note.variant_id, kind="quant_llm")
    registry = registry.register("variant-quant-only", kind="quant_only")

    _expect_safe_error(
        api,
        lambda: api.combine_quant_overlay(
            quant_signal,
            context=context,
            registry=registry,
            note=note,
            overlay=None,
        ),
    )


def test_composer_does_not_trust_sig04_guard_result_flags(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, _ = _llm_inputs(note, quant_signal)
    sig04 = overlay_fixtures._load_sig04()
    candidate = overlay_fixtures._candidate(note, quant_signal)
    guard_result = overlay_fixtures._service(sig04).evaluate(note, quant_signal, candidate)
    assert type(guard_result) is sig04.OverlayGuardResult
    assert guard_result.no_trade is False

    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=guard_result,
    )

    _assert_no_trade(envelope)
    assert envelope.overlay is None


def test_hostile_context_and_network_policy_are_rejected_before_callbacks(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    invoked: list[str] = []

    class HostileContext(RunContext):
        def __getattribute__(self, name: str) -> object:
            invoked.append(name)
            raise AssertionError("context callback must not run")

    hostile = object.__new__(HostileContext)
    _expect_safe_error(
        api,
        lambda: api.combine_quant_overlay(
            quant_signal,
            context=hostile,
            registry=registry,
            note=note,
            overlay=overlay,
        ),
    )
    assert invoked == []

    unsafe_policy = NetworkPolicy.model_construct(live_broker_egress=True)
    corrupted_context = context.model_copy(update={"network_policy": unsafe_policy})
    _expect_safe_error(
        api,
        lambda: api.combine_quant_overlay(
            quant_signal,
            context=corrupted_context,
            registry=registry,
            note=note,
            overlay=overlay,
        ),
    )


@pytest.mark.parametrize(
    "egress_field",
    [
        "data_capture_egress",
        "model_provider_egress",
        "research_tool_egress",
        "paper_broker_egress",
        "live_broker_egress",
    ],
)
def test_any_enabled_context_egress_fails_closed(
    bound_sources: tuple[Any, Any, Any],
    egress_field: str,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    unsafe_policy = NetworkPolicy.model_construct(**{egress_field: True})
    unsafe_context = context.model_copy(update={"network_policy": unsafe_policy})

    _expect_safe_error(
        api,
        lambda: api.combine_quant_overlay(
            quant_signal,
            context=unsafe_context,
            registry=registry,
            note=note,
            overlay=overlay,
        ),
    )


@pytest.mark.parametrize("mode", [Mode.FORWARD_PAPER, Mode.LIVE_PILOT])
def test_nonhistorical_all_egress_false_contexts_are_out_of_scope_and_rejected(
    bound_sources: tuple[Any, Any, Any],
    mode: Mode,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    context_data = context.model_dump(mode="python")
    context_data["mode"] = mode
    valid_nonhistorical_context = RunContext.model_validate(context_data)
    assert not any(valid_nonhistorical_context.network_policy.model_dump().values())

    _expect_safe_error(
        api,
        lambda: api.combine_quant_overlay(
            quant_signal,
            context=valid_nonhistorical_context,
            registry=registry,
            note=note,
            overlay=overlay,
        ),
    )


def test_context_and_network_policy_are_copied_defensively(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )
    assert envelope.context.model_dump(mode="json") == context.model_dump(mode="json")

    dict.__setitem__(object.__getattribute__(context, "__dict__"), "variant_id", "tampered")
    dict.__setitem__(
        object.__getattribute__(context.network_policy, "__dict__"),
        "live_broker_egress",
        True,
    )
    assert envelope.context.variant_id == note.variant_id
    assert envelope.context.network_policy.live_broker_egress is False


def test_composition_detaches_quant_note_and_overlay_source_storage(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )
    original_bytes = envelope.canonical_bytes()
    original_id = envelope.envelope_id
    original_score = quant_signal.score
    original_thesis = note.thesis
    original_note_hash = note.note_hash
    original_multiplier = overlay.multiplier

    quant_storage = object.__getattribute__(quant_signal, "__dict__")
    note_storage = object.__getattribute__(note, "__dict__")
    overlay_storage = object.__getattribute__(overlay, "__dict__")
    dict.__setitem__(quant_storage, "score", Decimal("0.125000000000"))
    dict.__setitem__(note_storage, "thesis", "caller-mutated source")
    dict.__setitem__(overlay_storage, "multiplier", Decimal("0.25"))
    try:
        assert envelope.canonical_bytes() == original_bytes
        assert envelope.envelope_id == original_id
        assert envelope.quant.score == original_score
        assert envelope.note.thesis == original_thesis
        assert envelope.note.note_hash == original_note_hash
        assert envelope.overlay.multiplier == original_multiplier
    finally:
        dict.__setitem__(quant_storage, "score", original_score)
        dict.__setitem__(note_storage, "thesis", original_thesis)
        dict.__setitem__(overlay_storage, "multiplier", original_multiplier)


def test_invalid_note_or_overlay_is_same_variant_zero_no_trade_without_echo(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    canary = "SIG05_SECRET_CANARY"
    malformed_note = {"thesis": canary, "nested": [[[[canary]]]]}

    for bad_note, bad_overlay in (
        (malformed_note, overlay),
        (note, SimpleNamespace(overlay=overlay, no_trade=False)),
    ):
        envelope = api.combine_quant_overlay(
            quant_signal,
            context=context,
            registry=registry,
            note=bad_note,
            overlay=bad_overlay,
        )
        _assert_no_trade(envelope)
        assert canary not in str(envelope.reason_codes)
        assert canary not in repr(envelope)
        if type(bad_note) is not type(note):
            assert envelope.note is None
            assert envelope.overlay is None
        elif type(bad_overlay) is not api.contracts_module.LLMOverlay:
            assert envelope.note.canonical_bytes() == note.canonical_bytes()
            assert envelope.overlay is None


@pytest.mark.parametrize(
    "case",
    ["note_text", "note_depth", "quant_features", "overlay_evidence"],
)
def test_corrupted_supported_model_storage_hits_resource_bounds_fail_closed(
    bound_sources: tuple[Any, Any, Any],
    case: str,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    if case == "note_text":
        storage = object.__getattribute__(note, "__dict__")
        field = "thesis"
        original = dict.__getitem__(storage, field)
        dict.__setitem__(storage, field, "x" * (1_048_576 + 1))
    elif case == "note_depth":
        storage = object.__getattribute__(note, "__dict__")
        field = "citations"
        original = dict.__getitem__(storage, field)
        citation = note.citations[0].model_dump(mode="python")
        reference = dict(citation["reference"])
        nested: object = "leaf"
        for _ in range(32):
            nested = {"nested": nested}
        reference["record_id"] = nested
        citation["reference"] = reference
        dict.__setitem__(storage, field, (citation,))
    elif case == "quant_features":
        storage = object.__getattribute__(quant_signal, "__dict__")
        field = "feature_ids"
        original = dict.__getitem__(storage, field)
        dict.__setitem__(
            storage,
            field,
            tuple(f"feature-{index:03}" for index in range(33)),
        )
    else:
        storage = object.__getattribute__(overlay, "__dict__")
        field = "evidence_ids"
        original = dict.__getitem__(storage, field)
        dict.__setitem__(
            storage,
            field,
            tuple(f"evidence-{index:03}" for index in range(33)),
        )

    try:
        if case == "quant_features":
            _expect_safe_error(
                api,
                lambda: api.combine_quant_overlay(
                    quant_signal,
                    context=context,
                    registry=registry,
                    note=note,
                    overlay=overlay,
                ),
            )
            return

        envelope = api.combine_quant_overlay(
            quant_signal,
            context=context,
            registry=registry,
            note=note,
            overlay=overlay,
        )
        _assert_no_trade(envelope)
        if case in {"note_text", "note_depth"}:
            assert envelope.note is None
            assert envelope.overlay is None
        else:
            assert envelope.note.canonical_bytes() == note.canonical_bytes()
            assert envelope.overlay is None
    finally:
        dict.__setitem__(storage, field, original)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("effective_score", "0.999999999999999999999999"),
        ("effective_multiplier", "0.990000000000000000000000"),
        ("effective_action", "eligible"),
        ("no_trade", True),
        ("reason_codes", ["quant_invalid"]),
        ("context.run_id", "run-envelope-other"),
    ],
)
def test_envelope_revalidates_semantics_after_rehashed_tampering(
    bound_sources: tuple[Any, Any, Any],
    path: str,
    value: object,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )
    payload = envelope.model_dump(mode="json")
    if "." in path:
        parent, field = path.split(".", 1)
        payload[parent][field] = value
    else:
        payload[path] = value
    forged = _rehash_envelope(payload)

    with pytest.raises((ValidationError, ValueError, TypeError)):
        api.SignalEnvelope.model_validate(forged)

    original_bytes = envelope.canonical_bytes()
    validated = api.SignalEnvelope.model_validate(envelope)
    assert validated.canonical_bytes() == original_bytes

    stored = object.__getattribute__(envelope, "__dict__")
    original_multiplier = dict.__getitem__(stored, "effective_multiplier")
    dict.__setitem__(
        stored,
        "effective_multiplier",
        Decimal("0.990000000000000000000000"),
    )
    try:
        with pytest.raises((ValidationError, ValueError, TypeError)):
            api.SignalEnvelope.model_validate(envelope)
        with pytest.raises((ValidationError, ValueError, TypeError)):
            envelope.canonical_bytes()
    finally:
        dict.__setitem__(stored, "effective_multiplier", original_multiplier)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("effective_score", 0.5),
        ("effective_score", True),
        ("effective_score", "NaN"),
        ("effective_score", "1e100000"),
        ("effective_multiplier", 0.5),
        ("effective_multiplier", True),
    ],
)
def test_rehashed_envelope_rejects_inexact_numeric_wire_values(
    bound_sources: tuple[Any, Any, Any],
    field: str,
    value: object,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )
    payload = envelope.model_dump(mode="json")
    payload[field] = value
    rehashed = _rehash_envelope(payload)

    with pytest.raises((ValidationError, ValueError, TypeError)):
        api.SignalEnvelope.model_validate(rehashed)


def test_canonical_envelope_roundtrip_and_repeat_are_stable_and_json_bounded(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(
        note,
        quant_signal,
        multiplier="0.123456789012",
    )
    original_context = getcontext().copy()
    try:
        getcontext().prec = 6
        getcontext().rounding = ROUND_UP
        getcontext().traps[Inexact] = True
        getcontext().traps[Rounded] = True
        first = api.combine_quant_overlay(
            quant_signal,
            context=context,
            registry=registry,
            note=note,
            overlay=overlay,
        )
        first_bytes = first.canonical_bytes()
        getcontext().prec = 50
        second = api.combine_quant_overlay(
            quant_signal,
            context=context,
            registry=registry,
            note=note,
            overlay=overlay,
        )
        second_bytes = second.canonical_bytes()
    finally:
        setcontext(original_context)

    assert first_bytes == second_bytes
    assert first.envelope_id == second.envelope_id
    assert first.envelope_id == _rehash_envelope(json.loads(first_bytes))["envelope_id"]
    assert first.effective_score == (
        quant_signal.score * Decimal("0.123456789012")
    ).quantize(Decimal("0.000000000000000000000000"))
    assert first.effective_multiplier == Decimal("0.123456789012000000000000")
    assert first.created_at == context.decision_time
    assert first.shadow_only is True
    decoded = json.loads(first_bytes)
    roundtrip = api.SignalEnvelope.model_validate(decoded)
    assert roundtrip.canonical_bytes() == first_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()

    with pytest.raises((TypeError, ValueError, ValidationError)):
        api.SignalEnvelope.model_validate_json(first_bytes)
    with pytest.raises((TypeError, ValueError, ValidationError)):
        TypeAdapter(api.SignalEnvelope).validate_json(first_bytes)


def test_canonical_envelope_contains_complete_context_and_source_contracts(
    bound_sources: tuple[Any, Any, Any],
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    envelope = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )
    payload = json.loads(envelope.canonical_bytes())

    assert set(payload["context"]) == set(RunContext.model_fields)
    assert set(payload["quant"]) == set(QuantSignal.model_fields)
    assert set(payload["note"]) == set(note.__class__.model_fields)
    assert set(payload["overlay"]) == set(overlay.__class__.model_fields)
    assert payload["variant"]["variant_id"] == context.variant_id
    assert payload["variant"]["kind"] == "quant_llm"
    assert payload["shadow_only"] is True


def test_envelope_has_no_json_consumer_or_research_provider_dependency() -> None:
    api = _api()
    forbidden_roots = {
        "anthropic",
        "httpx",
        "importlib",
        "openai",
        "os",
        "pickle",
        "requests",
        "socket",
        "subprocess",
        "tradingagents",
        "urllib",
    }
    modules = (
        api.contracts_module,
        api.variants_module,
        api.envelope_module,
    )
    for module in modules:
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        imported_roots = {name.split(".", 1)[0] for name in imported}
        assert imported_roots.isdisjoint(forbidden_roots)
        assert all(
            not (name.startswith("mytradingalpha.research") or name == "tradingagents")
            for name in imported
        )


def test_composition_does_not_call_network_filesystem_or_process(
    bound_sources: tuple[Any, Any, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, note, quant_signal = bound_sources
    api = _api()
    context, registry, overlay = _llm_inputs(note, quant_signal)
    calls: list[str] = []

    def forbidden(name: str):
        def invoke(*args: object, **kwargs: object) -> object:
            del args, kwargs
            calls.append(name)
            raise AssertionError(f"forbidden side effect: {name}")

        return invoke

    monkeypatch.setattr(socket, "socket", forbidden("socket.socket"))
    monkeypatch.setattr(socket, "create_connection", forbidden("socket.create_connection"))
    monkeypatch.setattr(urllib.request, "urlopen", forbidden("urlopen"))
    monkeypatch.setattr(subprocess, "run", forbidden("subprocess.run"))
    monkeypatch.setattr(subprocess, "Popen", forbidden("subprocess.Popen"))
    monkeypatch.setattr(builtins, "open", forbidden("open"))
    monkeypatch.setattr(io, "open", forbidden("io.open"))
    monkeypatch.setattr(os, "open", forbidden("os.open"))

    result = api.combine_quant_overlay(
        quant_signal,
        context=context,
        registry=registry,
        note=note,
        overlay=overlay,
    )

    assert result.no_trade is False
    assert calls == []


def test_quant_only_and_quant_llm_are_explicitly_registered_not_implicitly_selected() -> None:
    api = _api()
    empty = api.VariantRegistry()
    _expect_safe_error(api, lambda: empty.resolve("variant-quant-only"))
    assert set(api.SignalVariant.model_fields) == {
        "schema_version",
        "variant_id",
        "kind",
        "variant_hash",
    }
    assert "variant" in api.SignalEnvelope.model_fields
    assert "context" in api.SignalEnvelope.model_fields
    assert "quant" in api.SignalEnvelope.model_fields
    assert "effective_multiplier" in api.SignalEnvelope.model_fields
    assert "no_trade" in api.SignalEnvelope.model_fields

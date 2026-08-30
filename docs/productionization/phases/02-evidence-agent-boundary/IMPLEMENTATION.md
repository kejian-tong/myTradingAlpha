# Phase 02 — Evidence and Agent Boundary Implementation

Commands are planned until a PR records exact output.

## Ordered PR/work packages

1. **SIG-01** — read-only Research Graph adapter.
2. **SIG-02** — EvidenceToolset and ResearchNote.
3. **SIG-03** — deterministic features and QuantSignal.
4. **SIG-04** — bounded LLMOverlay validator.
5. **SIG-05** — SignalEnvelope and variant registry.

## Exact existing files to touch

- [`tradingagents/graph/setup.py`](../../../../tradingagents/graph/setup.py) and [`propagation.py`](../../../../tradingagents/graph/propagation.py) only at an adapter seam.
- [`tradingagents/agents/utils/agent_states.py`](../../../../tradingagents/agents/utils/agent_states.py) only for typed context extraction; do not add portfolio/order state.
- [`tradingagents/agents/schemas.py`](../../../../tradingagents/agents/schemas.py) only for compatibility rendering if required.
- [`tradingagents/graph/signal_processing.py`](../../../../tradingagents/graph/signal_processing.py) only to preserve current string API.
- [`tradingagents/graph/trading_graph.py`](../../../../tradingagents/graph/trading_graph.py) only to ensure historical mode bypasses pending outcome resolution.

## Proposed files, classes, and APIs

- `mytradingalpha/research/tradingagents_adapter.py`: `ResearchAdapter.run(bundle, context) -> list[ResearchNote]`.
- `mytradingalpha/research/evidence_tools.py`: `EvidenceToolset.get/list_citations()`.
- `mytradingalpha/research/notes.py`: `ResearchNoteBuilder.build()`.
- `mytradingalpha/quant/features.py`: `FeatureSet.compute(bundle, instrument)`.
- `mytradingalpha/quant/signal.py`: `QuantSignalModel.score(features)`.
- `mytradingalpha/quant/models.py`: `ModelArtifact` with content hash and feature schema.
- `mytradingalpha/research/overlay.py`: `LLMOverlayService.evaluate(note, quant_signal)`.
- `mytradingalpha/research/overlay_validator.py`: `validate_overlay()` and no-trade failure mapping.
- `mytradingalpha/quant/envelope.py`: `combine_quant_overlay()`.
- `mytradingalpha/quant/variants.py`: `VariantRegistry.register/resolve()`.

## Schema and pseudocode

```text
bundle -> FeatureSet -> QuantSignal
bundle -> ResearchAdapter -> ResearchNote -> optional OverlayService

overlay_result:
  if timeout/schema_error/abstain: SignalEnvelope(action="abstain")
  if veto: multiplier=0, action="veto"
  if attenuate: 0 <= multiplier <= 1, action="attenuate"
  otherwise: reject; never infer a default action

Quant-only and Quant+LLM are separate VariantRegistry entries.
```

The validator rejects extra output fields that represent weights, quantity, order type, broker IDs, or credentials. It rejects multiplier values outside [0,1], veto with nonzero multiplier, and any envelope whose bundle/context hash is inconsistent.

## Red-green-refactor

1. Red: add tests for network access in historical mode, missing citation, overlay forbidden fields, multiplier >1, veto mismatch, timeout, schema error, abstain, and variant fallback.
2. Green: implement the read-only adapter, deterministic feature path, typed validator, envelope, and registry.
3. Refactor: isolate compatibility rendering from domain contracts and freeze the public action/variant names.

## Exact tests and fixtures

- `tests/productionization/research/test_adapter.py`: sequential graph invocation against a sealed bundle, historical network denial, pending-memory bypass.
- `tests/productionization/research/test_evidence_tools.py`: citation completeness, immutable item, prompt-injection text treated as data.
- `tests/productionization/quant/test_signal.py`: feature golden file, deterministic repeat, missing-feature status, model hash.
- `tests/productionization/research/test_overlay.py`: attenuate/veto/abstain, timeout/schema error no-trade, forbidden fields, multiplier bounds.
- `tests/productionization/quant/test_envelope_variants.py`: Quant-only and Quant+LLM IDs, no dynamic fallback, envelope serialization.
- `tests/productionization/fixtures/evidence/bundle-minimal.json` and `overlay-{attenuate,veto,abstain,error}.json`.

## Validation commands

```bash
python -m pytest -q tests/productionization/research tests/productionization/quant
python -m pytest -q tests/test_analyst_execution.py tests/test_signal_processing.py tests/test_checkpoint_resume.py
python scripts/check_dependency_direction.py
ruff check .
```

These commands are planned; the PR report must state whether each ran and include no credentials or live payloads.

## Migration and compatibility

The default `TradingAgentsGraph` and `SignalProcessor.process_signal()` remain compatible. The new adapter is opt-in by mode/variant and emits an envelope alongside existing reports. Historical runs use only sealed bundles; forward paper can capture current inputs before invoking the adapter. Disable the new path to roll back without deleting envelopes or changing current memory records.

## Definition of done

- All SIG PRs are merged in order with exact focused tests.
- QuantSignal is independently reproducible and has no portfolio authority.
- LLMOverlay is optional, has only attenuate/veto plus abstain, and failure is no trade.
- Variant registry keeps Quant-only separate from Quant+LLM.
- No production code under `tradingagents/` imports `mytradingalpha`.
- Gate evidence is `pass`; otherwise `fail` or `insufficient_evidence` blocks Phase 03/04.

## Evidence and rollback

Evidence includes bundle/envelope hashes, fixture manifests, property-test output, adapter dependency graph, and model artifact IDs. Rollback disables the adapter/overlay consumer and returns to current reports; it never turns an overlay error into quant execution and never mutates sealed evidence.

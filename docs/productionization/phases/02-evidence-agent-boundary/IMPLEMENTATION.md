# Phase 02 — Evidence and Agent Boundary Implementation

Commands are planned until a PR records exact output.

## Ordered PR/work packages

1. **SIG-01** — read-only Research Graph adapter.
2. **SIG-02** — EvidenceToolset and ResearchNote.
3. **SIG-03** — deterministic features and QuantSignal.
4. **SIG-04** — bounded LLMOverlay validator.
5. **SIG-05** — SignalEnvelope and variant registry.

## Exact existing files to touch

- For SIG-01, keep [`tradingagents/graph/trading_graph.py`](../../../../tradingagents/graph/trading_graph.py), [`setup.py`](../../../../tradingagents/graph/setup.py), and [`propagation.py`](../../../../tradingagents/graph/propagation.py) as the unchanged default path. Add the historical path in a separate module and update `tradingagents/graph/__init__.py` only for additive exports if required.
- Reuse the current `Propagator.create_initial_state()` and `SignalProcessor.process_signal()` contracts without changing their ordinary behavior.
- Later SIG slices may touch analyst utilities or schemas only when their own JIT contract requires it; do not pull those changes into SIG-01.

## Proposed files, classes, and APIs

- `tradingagents/graph/historical.py`: pure cached-state validation and five-tier rendering; no callable or runtime loading.
- `mytradingalpha/data/replay_guard.py`: additive `HistoricalDataGuard.replay_bound(...) -> tuple[EvidenceBundle, RunContext]` returns the guard-validated canonical binding; existing `replay(...) -> EvidenceBundle` remains compatible.
- `mytradingalpha/research/cached_response.py`: separate v1 canonical response contract, exact selection, byte sealer/parser, append-only repository, hashes, provenance/cutoff checks, and typed errors.
- `mytradingalpha/research/tradingagents_adapter.py`: constructor-injected exact evidence/response repositories and selection; `ResearchAdapter.run(bundle_id, context, *, ticker, trade_date, asset_type="stock") -> tuple[dict[str, object], str]`.
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

1. SIG-01 Red: add exact sealed repository/context/response binding, canonical bytes/hash/provenance/cutoff/date failures, no-callable denial, side-effect observers, state/output compatibility, authority denial, and SIG-02-deferral tests.
2. SIG-01 Green: implement only the closed response contract/repository, pure `tradingagents` validator, and adapter; do not change ordinary graph execution or add a remote/current fallback.
3. Later SIG PRs repeat their own RED/GREEN cycles for evidence citations, deterministic quant, overlay validation, and envelope/variant behavior.
4. Refactor: isolate compatibility rendering from domain contracts and freeze the public action/variant names without crossing PR boundaries.

## Exact tests and fixtures

- `tests/productionization/research/test_adapter.py`: exact sealed bundle/context/response replay, side-effect denial, UTC cutoff-date rule, current final/five-tier compatibility, and fail-closed output/authority boundaries.
- `tests/productionization/research/test_cached_response.py`: canonical bytes, exact selection/bindings, provenance cutoffs, append-only conflicts, corruption, limits, and hostile non-data rejection.
- `tests/productionization/research/test_adapter_repairs.py`: bound-field mutation denial, sealed alias intervals, defensive canonical context handoff, UTC cutoff-date enforcement, and authority checks in supported plain messages/structured call arguments.
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

The default `TradingAgentsGraph` and `SignalProcessor.process_signal()` remain compatible. The SIG-01 adapter is opt-in, preserves the legacy prose state and five-tier string, and requires an exact sealed bundle plus exact canonical cached response. It does not emit a `ResearchNote` or `SignalEnvelope`; those remain later SIG slices. Disable the new path to roll back without deleting bundles/responses or changing current memory records. Forward-paper behavior remains outside SIG-01.

SIG-01 tests seal deterministic canonical response fixtures through the production parser. Fixtures
prove replay mechanics only and are never described as real model inference. The approved
[SIG-01 amendment](SIG_01_AMENDMENT_PROPOSAL.md) forbids callable execution and defines the UTC
cutoff-date rule. Missing response evidence never permits a remote, current-vendor, Quant-only, or
ordinary-graph fallback.

## Definition of done

- All SIG PRs are merged in order with exact focused tests.
- QuantSignal is independently reproducible and has no portfolio authority.
- LLMOverlay is optional, has only attenuate/veto plus abstain, and failure is no trade.
- Variant registry keeps Quant-only separate from Quant+LLM.
- No production code under `tradingagents/` imports `mytradingalpha`.
- Gate evidence is `pass`; otherwise `fail` or `insufficient_evidence` blocks Phase 03/04.

## Evidence and rollback

Evidence includes bundle/envelope hashes, fixture manifests, property-test output, adapter dependency graph, and model artifact IDs. Rollback disables the adapter/overlay consumer and returns to current reports; it never turns an overlay error into quant execution and never mutates sealed evidence.

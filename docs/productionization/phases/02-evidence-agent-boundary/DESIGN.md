# Phase 02 — Evidence and Agent Boundary Design

Status: planned. This phase uses the current Research Graph for interpretation while moving authority for numeric signals and risk-sensitive actions outside the LLM.

## Goals

- Give analysts read-only access to cited EvidenceBundle items.
- Produce deterministic `QuantSignal` independently from the Research adapter.
- Constrain an optional `LLMOverlay` to attenuate/veto/abstain and make all failures no-trade.

## Scope

Research adapter, evidence tools, `ResearchNote`, deterministic feature/signal service, overlay validator, `SignalEnvelope`, and explicit Quant-only/Quant+LLM variant registration.

## Non-goals

No target weights, portfolio allocator, RiskEngine, order intent, broker credential, or dynamic fallback from an overlay run. No change to the public default behavior of `tradingagents`.

## Dependencies

Depends on Phase 01 sealed EvidenceBundle and Phase 00 contracts. Current graph seams are [`setup.py`](../../../../tradingagents/graph/setup.py#L113-L154), [`propagation.py`](../../../../tradingagents/graph/propagation.py#L8-L76), [`agent_states.py`](../../../../tradingagents/agents/utils/agent_states.py#L47-L76), [`schemas.py`](../../../../tradingagents/agents/schemas.py#L121-L223), and [`signal_processing.py`](../../../../tradingagents/graph/signal_processing.py#L20-L30).

## Components and dataflow

```text
EvidenceBundle ───────────────> Quant feature service ───> QuantSignal
      |
      +-> SIG-01 read-only adapter ───> legacy prose graph state
                                            |
                                            +-> SIG-02 ResearchNote ───> optional LLMOverlay
QuantSignal + optional overlay ─────────> SignalEnvelope
```

The two branches are independent: QuantSignal does not depend on LLM output, and the Research adapter does not grant the LLM access to network, credentials, weights, or orders. An overlay timeout/schema error or abstain yields no trade. Quant-only is a separate preregistered experiment variant, not runtime fallback.

## Current integration points

- [`GraphSetup.setup_graph`](../../../../tradingagents/graph/setup.py#L61-L154) builds sequential analysts and later decision nodes; the adapter must wrap this boundary rather than add portfolio behavior to the graph.
- [`AgentState`](../../../../tradingagents/agents/utils/agent_states.py#L47-L76) carries prose reports/debate state but no numeric portfolio fields.
- [`TraderProposal`](../../../../tradingagents/agents/schemas.py#L121-L180) has string `position_sizing`, and [`PortfolioDecision`](../../../../tradingagents/agents/schemas.py#L188-L223) is rating/prose.
- [`SignalProcessor`](../../../../tradingagents/graph/signal_processing.py#L20-L30) returns a five-tier string and is not a target-weight service.
- [`TradingAgentsGraph._resolve_pending_entries`](../../../../tradingagents/graph/trading_graph.py#L296-L334) performs current-time outcome fetches at run start; the historical adapter must bypass it.

## SIG-01 historical execution decision

SIG-01 adds a separate, typed, explicitly opt-in historical execution seam under
`tradingagents.graph`; it does not add a historical flag inside the ordinary `TradingAgentsGraph`
path. The normal constructor, CLI, and `propagate()` continue to create and use the configured model
clients, current research tools, memory, reporting, and optional checkpoints exactly as before.

The production-owned `ResearchAdapter` is constructed with one exact in-memory `EvidenceRepository`
and an explicitly supplied concrete `OfflineGraphRuntime`. Its run entry point accepts a bundle ID,
an exact historical `RunContext`, ticker, trade date, and asset type. It first calls
`HistoricalDataGuard.replay()` to bind the exact sealed bundle ID/hash/cutoff/calendar and require every
egress flag to be false. It then resolves the instrument only from sealed aliases/instruments, creates
the current graph initial-state shape with empty past context, and calls the injected offline runtime
once. The generic seam receives the sealed bundle as an opaque caller-owned input and never imports
`mytradingalpha`.

The historical seam never constructs or calls ordinary `TradingAgentsGraph.propagate()`, pending
outcome/reflection logic, current identity or vendor helpers, memory, reports, caches, checkpoints, or a
configured remote model. Missing, wrong, or subclassed runtime objects fail closed before overridable
runtime methods. Malformed output and new target/order/broker/credential/risk-authority fields also
fail closed. Existing prose plan language remains legacy research output, not numeric production
portfolio or order authority.

SIG-01 supplies only the minimal bundle-backed input boundary needed for offline graph invocation. The
public `EvidenceToolset`, citation enumeration/completeness, prompt-injection rendering policy,
`ResearchNote`, and `ResearchNoteBuilder` remain SIG-02. A deterministic fake runner proves the
adapter/execution-seam contract in tests; it is not evidence that a deployable real offline model
runtime exists or that historical inference, alpha, paper, or live execution is ready. The adapter
returns typed unavailable rather than falling back to a remote model or ordinary graph.

## Interfaces and invariants

`EvidenceToolset.get(evidence_id)` returns immutable content plus provenance only. `QuantSignal` is deterministic for a fixed bundle, feature version, and model artifact. `LLMOverlay` is optional; when present it has `action=attenuate|veto`, a separate `abstain` flag, and `multiplier ∈ [0,1]`. Veto requires multiplier 0; abstain or overlay failure means no trade. There is no overlay field for target weights, orders, credentials, or increased quant influence. `SignalEnvelope` records source IDs and reason codes and is valid only when the cutoff invariant holds.

## Decisions and alternatives

- Use a narrow adapter around `tradingagents` rather than fork the graph or add portfolio fields to `AgentState`.
- Keep QuantSignal independent to permit deterministic testing and a separately preregistered Quant-only row.
- Use a typed overlay validator rather than prompt-only instructions.
- Treat overlay failure as no trade rather than silently executing the quant path; operational continuity can be evaluated by the separate Quant-only experiment.

## Failure, security, and observability

Missing evidence is a reason-coded degradation or run failure according to variant policy. Prompt-injection text is untrusted evidence and cannot change tools or permissions. LLM calls use no broker credentials and receive only selected evidence excerpts. Observe evidence IDs, overlay latency, validation failures, abstain/veto counts, quant score, effective multiplier, and no-trade reason; do not log raw secrets or unrestricted payloads.

## Migration and rollback

Run the adapter and signals in shadow mode while existing markdown reports remain the user-facing output. Disable the new adapter or overlay flag to return to the current Research Graph. Stored envelopes remain immutable and are never edited to fit a later interpretation.

## Acceptance and gate

Pass requires offline evidence-only adapter tests, deterministic QuantSignal repeatability, overlay property tests proving no forbidden fields/actions, explicit no-trade failure behavior, and separate variant IDs. `fail` or `insufficient_evidence` blocks portfolio/backtest promotion.

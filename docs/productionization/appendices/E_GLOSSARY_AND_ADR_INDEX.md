# Appendix E — Glossary and ADR Index

## Glossary

| Term | Definition |
| --- | --- |
| Available-at / `available_at` | Earliest time an observation could have been used by the system, after publication and access latency. This is the core PIT timing rule. |
| Archive-realistic replay | Historical replay that requires both `available_at` and `ingested_at` to be no later than the knowledge cutoff. |
| B&H | Buy-and-hold benchmark with explicit corporate-action/dividend treatment. |
| Bundle hash | Content-addressed identity for an immutable EvidenceBundle. |
| Capacity | The size/participation limit at which an intent cannot be filled under the stated liquidity and cost assumptions. |
| Decision time | Close-time timestamp at which a target decision is made. |
| EvidenceBundle | Immutable, provenance-rich set of observations authorized for a run. |
| Fail-closed | Any missing/invalid safety input rejects or halts instead of assuming approval. Safety takes priority over continuing on a guess. |
| GateEvidence | Immutable record of a phase/promotion decision, evidence URIs, metrics, reviewer, and rollback plan. |
| Knowledge cutoff | Latest information time visible to a historical run. |
| L0/L1/L2 | Live-pilot levels: read-only; human-approved one/few symbols; human-approved small allowlist. |
| MDD | Maximum drawdown from a prior equity peak. |
| No trade | Valid outcome for missing evidence, overlay abstain/error, risk rejection, or unapproved intent. |
| Overlay | Optional LLM research/risk filter that can attenuate or veto a QuantSignal; it cannot create weights/orders. |
| PIT | Point-in-time data: what was knowable at the historical decision time, not what is known now. |
| Paper endpoint | Isolated simulated broker endpoint; its writes are allowed only after Phase 07/08 approval and are not live broker writes. |
| Persistent halt | Durable stop state that survives process restart and requires an authorized clear event. |
| Quant-only | Separately preregistered deterministic quantitative variant with no runtime overlay fallback. |
| Reconciliation | Comparison of local ledger/account state with endpoint cash, positions, orders, fills, and snapshot identity. |
| Resize | Risk decision that replaces a target with constrained weights and requires revalidation before intent approval. |
| SignalEnvelope | Typed combination of QuantSignal and optional overlay with effective action, multiplier, provenance, and reason codes. |
| Semantic/economic hash | Canonical artifact identity that omits non-semantic run IDs and wall-clock fields while retaining economic inputs/results. |
| Turnover | Trading activity relative to portfolio value under the declared measurement convention. |

## ADR index

| ADR | Decision | Evidence |
| --- | --- | --- |
| ADR-001 | Keep `tradingagents/` as the upstream-derived Research Graph; add production-owned `mytradingalpha/` package. | [02 Target Architecture](../02_TARGET_ARCHITECTURE.md), [Phase 00 Design](../phases/00-foundation/DESIGN.md) |
| ADR-002 | Only `mytradingalpha.research` may import `tradingagents`; no file under `tradingagents/` imports `mytradingalpha`. | [02 Target Architecture](../02_TARGET_ARCHITECTURE.md) |
| ADR-003 | Historical mode reads immutable, network-free EvidenceBundle with availability and optional ingestion cutoff. | [03 Contracts](../03_CONTRACTS_AND_SCHEMAS.md), [Phase 01 Design](../phases/01-point-in-time-data/DESIGN.md) |
| ADR-004 | QuantSignal is independent; optional LLMOverlay can attenuate/veto/abstain only, with failure no-trade. | [00 Comparison](../00_COMPARISON_AND_DECISIONS.md), [Phase 02 Design](../phases/02-evidence-agent-boundary/DESIGN.md) |
| ADR-005 | Rule allocator ships before optional constrained optimizer; deterministic RiskEngine is shared, persistent, and fail-closed. | [Phase 04 Design](../phases/04-portfolio-risk/DESIGN.md) |
| ADR-006 | Deterministic simulator and append-only ledger precede OMS; fees are posted once and not double-counted in NAV. | [Phase 03 Design](../phases/03-backtest-ledger/DESIGN.md) |
| ADR-007 | Paper and future live share OMS contracts; unknown ACK pauses/query and never blindly resubmits. | [Phase 07 Design](../phases/07-broker-oms-paper-reconciliation/DESIGN.md) |
| ADR-008 | Eight to twelve weeks of forward paper primarily proves operational reliability; promotion requires complete evidence. | [Phase 08 Design](../phases/08-forward-paper-gate/DESIGN.md) |
| ADR-009 | Live rollout is L0 → L1 → L2; later automation needs a new approval and emergency action is policy/human/liquidity/reconciliation gated. | [Phase 09 Design](../phases/09-live-pilot/DESIGN.md) |
| ADR-010 | Adopt `uv.lock` as the single lock mechanism, with locked CI and a documented pip rollback path while preserving Python 3.10–3.14. | [Phase 00 Implementation](../phases/00-foundation/IMPLEMENTATION.md), [07 PR Plan](../07_PR_IMPLEMENTATION_PLAN.md) |
| ADR-011 | Keep current unrelated Git histories independent; sync upstream by fetch/review/cherry-pick or reviewed diff. | [`UPSTREAM.md`](../../../UPSTREAM.md), [`CHANGES_FROM_UPSTREAM.md`](../../../CHANGES_FROM_UPSTREAM.md) |

ADR entries are indexes to the design records, not evidence that a future implementation has shipped.

## Remediation clarifications and unresolved changes

[Shared contracts](../03_CONTRACTS_AND_SCHEMAS.md) now identify first-use wire owners, all-in fill
price versus incremental explicit fees, and distinct partial-fill event semantics. These repair
implementation ambiguity without introducing the future runtime modules. The closed-response
handoff preserves the approved SIG-01 v1 time contract; a different derived-artifact or session-clock
contract remains a separately approved architecture change, not silently approved by this index.
Current/target schemas and software/operational gate evidence must not be conflated.

# Comparison and Decisions

This comparison uses three inputs: the current repository at baseline `212dcef`, a user-provided attachment containing 19 Markdown files (approximately 5,475 lines), and the previous read-only document set containing 34 Markdown files (approximately 2,259 lines). The attachment is not a public source and is identified here only as user-provided material. The current repository and its source symbols are the authority for code facts.

## Verdict

Neither source set is best alone. The attachment is the stronger implementation blueprint for PR decomposition, contracts, and canary operations; the prior docs are stronger on code audit, paper evidence, leakage controls, and fail-closed safety. This repo-specific synthesis combines those strengths with the actual `myTradingAlpha` baseline and is the recommended source of truth for implementation.

## Scored comparison

Scores are 1–5 for usefulness to this repository's productionization objective. A score measures coverage and actionability, not correctness by itself.

| Dimension | Previous docs | User attachment | Current-repo synthesis | Decision |
| --- | ---: | ---: | ---: | --- |
| Current-code grounding | 4 | 2 | 5 | Keep exact current paths/symbols and correct claims against baseline source. |
| Fixed-source/PIT audit | 5 | 3 | 5 | Adopt the previous fixed-source audit; add attachment's ingestion/archive distinctions. |
| Contracts and invariants | 4 | 5 | 5 | Adopt implementable schemas from both; make time and accounting invariants explicit. |
| PR decomposition | 3 | 5 | 5 | Adopt the attachment's granular slices, normalize to exactly 47 dependency-ordered PRs. |
| Canary/paper operations | 3 | 5 | 5 | Adopt canary, OMS lifecycle, and reconciliation sequencing; retain paper-only boundary. |
| Alpha evidence/statistics | 5 | 4 | 5 | Retain previous paper-evidence and leakage discipline; add attachment's experiment breadth. |
| Memory and fail-closed overlay | 5 | 2 | 5 | Retain previous memory-leakage and fail-closed overlay treatment; reject permissive support. |
| Requirement traceability | 5 | 3 | 5 | Preserve the previous traceability style and map every requirement to a PR/test. |
| License/upstream caution | 4 | 4 | 5 | Reconcile both into repo-specific Apache-2.0 and unrelated-history guidance. |

## What is adopted

- From the attachment: richer PR decomposition, directly usable contract shapes, canary levels, OMS transition coverage, explicit paper operations, and operational rollback language.
- From the previous docs: fixed-source audit, paper-evidence distinction, memory-leakage controls, requirement traceability, and a fail-closed LLM overlay.
- From the current repository: exact `tradingagents/` integration points, provider registry and typed outputs, current cache/news fixes, CI/security checks, and the independent history/upstream snapshot.

## What is rejected or corrected

- The attachment's `SUPPORT` / confidence-increase overlay behavior is rejected. The current contract is an optional overlay with attenuate/veto plus a separate abstain flag; failure or abstain is no trade, and it cannot increase quant influence or produce weights/orders.
- Any document that treats the current project as a portfolio or execution system is corrected. `AgentState` has no cash, positions, orders, fills, NAV, or constraints, and `PortfolioDecision` is rating/prose.
- A dynamic Quant-only fallback inside the overlay is rejected. Quant-only is a separately preregistered variant with its own report row.
- A current-day live-data interpretation of historical replay is rejected. Replay consumes an immutable, network-free `EvidenceBundle` with `available_at` and, when required, `ingested_at` cutoff checks.
- Raw close-minus-benchmark is not called portfolio alpha; costs, holdings, exposure, turnover, beta, and capacity are required.
- A merge recommendation based on unrelated histories is corrected to fetch/review/cherry-pick or apply reviewed diffs. See [`UPSTREAM.md`](../../UPSTREAM.md).
- Backtrader's dependency is not treated as a shipped backtest. The deterministic simulator and ledger must be implemented and tested before any framework integration.

## Resolved architecture decisions

1. `tradingagents/` stays an upstream-derived Research Graph with minimal direct changes.
2. Future production-owned code lives under `mytradingalpha/` with bounded contexts `contracts`, `data`, `research`, `quant`, `portfolio`, `risk`, `backtest`, `execution`, `experiments`, and `ops`.
3. MVP is daily, long-only, unlevered, liquid US equities/ETFs, small allowlist, close decision, earliest next-session execution.
4. Historical mode is immutable and network-free; forward-paper mode uses captured inputs and operational adapters.
5. Rule allocation ships before an optional constrained optimizer; deterministic hard risk is shared and fail-closed.
6. A deterministic execution simulator precedes OMS and broker adapters.
7. Operational gates progress from L0 read-only to L1 human-approved one/few symbols, L2 small allowlist, and only a separately approved later automation level.

## Official references

- [TradingAgents upstream repository](https://github.com/TauricResearch/TradingAgents)
- [TradingAgents paper, arXiv:2412.20138](https://arxiv.org/abs/2412.20138)
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- [GitHub documentation on comparing commits](https://docs.github.com/en/pull-requests/committing-changes-to-your-project/working-with-commits/comparing-commits)

These links provide public context; user-provided document sets remain comparison inputs, not citations.

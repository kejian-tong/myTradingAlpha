# myTradingAlpha Productionization

This documentation turns the current `tradingagents/` research graph into an implementable, staged productionization plan. It is predominantly English so engineers can use exact APIs, schemas, commands, and acceptance gates; short Chinese notes explain specialized concepts such as point-in-time data and fail-closed risk. 当前状态仍是 research/recommendation only, not a portfolio or execution system.

## North-star boundary

The first product boundary is daily, long-only, unlevered research and recommendation for liquid US equities/ETFs from a small allowlist. A decision is made at the close and, at the earliest, executed in the next eligible session. The current graph remains upstream-derived research code. A future `mytradingalpha/` package owns contracts, data, research adapters, quant, portfolio, risk, backtest, execution, experiments, and operations. Only `mytradingalpha.research` may import `tradingagents`; no file under `tradingagents/` may import `mytradingalpha`.

LLM output is a bounded research/risk overlay. It may attenuate or veto a deterministic quantitative signal; an overlay failure or abstain means no trade. It cannot increase quant influence, create target weights or orders, or access broker credentials. Quant-only is a separately preregistered experiment variant, never a runtime fallback from Quant+LLM. Hard risk is deterministic, shared, independent of LangGraph, and fail-closed; a persistent halt survives process restarts.

Historical replay reads only an immutable `EvidenceBundle`, sets every component-scoped egress field false, and permits only cached bundle responses. Every datum must satisfy `available_at <= knowledge_cutoff`; archive-realistic forward replay also requires `ingested_at <= knowledge_cutoff`. Preserve publication time, event time, validity intervals, revisions, and replay policy. Forward paper may enable approved data capture/model-provider/PAPER egress while research-tool and live-broker egress remain false.

## Navigation

- [Comparison and decisions](00_COMPARISON_AND_DECISIONS.md)
- [Current-state audit](01_CURRENT_STATE_AUDIT.md)
- [Target architecture](02_TARGET_ARCHITECTURE.md)
- [Contracts and schemas](03_CONTRACTS_AND_SCHEMAS.md)
- [Validation and alpha evidence](04_VALIDATION_AND_ALPHA_EVIDENCE.md)
- [License and upstream strategy](05_REPOSITORY_LICENSE_AND_UPSTREAM.md)
- [Roadmap and phase gates](06_ROADMAP_AND_PHASE_GATES.md)
- [47-PR implementation plan](07_PR_IMPLEMENTATION_PLAN.md)

### Phase documents

| Phase | Design | Implementation |
| --- | --- | --- |
| 00 Foundation | [DESIGN](phases/00-foundation/DESIGN.md) | [IMPLEMENTATION](phases/00-foundation/IMPLEMENTATION.md) |
| 01 Point-in-time data | [DESIGN](phases/01-point-in-time-data/DESIGN.md) | [IMPLEMENTATION](phases/01-point-in-time-data/IMPLEMENTATION.md) |
| 02 Evidence/agent boundary | [DESIGN](phases/02-evidence-agent-boundary/DESIGN.md) | [IMPLEMENTATION](phases/02-evidence-agent-boundary/IMPLEMENTATION.md) |
| 03 Backtest/ledger | [DESIGN](phases/03-backtest-ledger/DESIGN.md) | [IMPLEMENTATION](phases/03-backtest-ledger/IMPLEMENTATION.md) |
| 04 Portfolio/risk | [DESIGN](phases/04-portfolio-risk/DESIGN.md) | [IMPLEMENTATION](phases/04-portfolio-risk/IMPLEMENTATION.md) |
| 05 Execution/cost/liquidity | [DESIGN](phases/05-execution-cost-liquidity/DESIGN.md) | [IMPLEMENTATION](phases/05-execution-cost-liquidity/IMPLEMENTATION.md) |
| 06 Experiment/alpha validation | [DESIGN](phases/06-experiment-alpha-validation/DESIGN.md) | [IMPLEMENTATION](phases/06-experiment-alpha-validation/IMPLEMENTATION.md) |
| 07 Broker/OMS/paper/reconciliation | [DESIGN](phases/07-broker-oms-paper-reconciliation/DESIGN.md) | [IMPLEMENTATION](phases/07-broker-oms-paper-reconciliation/IMPLEMENTATION.md) |
| 08 Forward paper gate | [DESIGN](phases/08-forward-paper-gate/DESIGN.md) | [IMPLEMENTATION](phases/08-forward-paper-gate/IMPLEMENTATION.md) |
| 09 Live pilot | [DESIGN](phases/09-live-pilot/DESIGN.md) | [IMPLEMENTATION](phases/09-live-pilot/IMPLEMENTATION.md) |

### Appendices

- [A. Requirements traceability](appendices/A_REQUIREMENTS_TRACEABILITY.md)
- [B. Test matrix](appendices/B_TEST_MATRIX.md)
- [C. Operational runbooks](appendices/C_OPERATIONAL_RUNBOOKS.md)
- [D. Configuration examples](appendices/D_CONFIG_EXAMPLES.md)
- [E. Glossary and ADR index](appendices/E_GLOSSARY_AND_ADR_INDEX.md)

## Reading and evidence policy

The phases are ordered `00 foundation → 01 PIT → 02 evidence/agent boundary → 03 backtest/ledger → 04 portfolio/risk → 05 execution cost/liquidity → 06 experiment/alpha → 07 OMS/paper/reconciliation → 08 8–12 week forward paper gate → 09 tiny live pilot`. Commands in implementation documents are planned commands unless a validation record explicitly says they were run. Current baseline evidence is limited to local-contract checks and green GitHub CI; it does not prove PIT correctness, backtest alpha, paper readiness, or live readiness.

There is no fixed live risk number in this plan. Risk limits, allowlists, credentials, and broker settings are deployment configuration subject to approval and should never be copied from examples into a live environment.

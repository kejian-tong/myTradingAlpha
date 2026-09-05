# Appendix A — Requirements Traceability

This matrix maps the delegated requirements to the consolidated documents, master PR slices, and planned tests. Commands are plans until their implementation PR records actual output. A requirement without a passing gate remains `fail` or `insufficient_evidence`.

| ID | Requirement | Design/roadmap evidence | Master PR / phase implementation | Planned tests or command |
| --- | --- | --- | --- | --- |
| R-01 | Preserve current Research Graph and add future production-owned package with one-way dependency | [02 Target Architecture](../02_TARGET_ARCHITECTURE.md), [00 Design](../phases/00-foundation/DESIGN.md) | FND-01; Phase 00 implementation | `test_dependency_direction.py`, `check_dependency_direction.py` |
| R-02 | Daily, long-only, unlevered liquid US equity/ETF MVP and earliest next-session execution | [02 Target Architecture](../02_TARGET_ARCHITECTURE.md), [06 Roadmap](../06_ROADMAP_AND_PHASE_GATES.md) | BT-01, RSK-02; Phases 03/04 | `test_clock_events.py`, `test_rule_allocator.py` |
| R-03 | LLM overlay may attenuate/veto/abstain only; failure is no-trade; no target weights/orders/credentials | [00 Comparison](../00_COMPARISON_AND_DECISIONS.md), [03 Contracts](../03_CONTRACTS_AND_SCHEMAS.md), [Phase 02 Design](../phases/02-evidence-agent-boundary/DESIGN.md) | SIG-04/SIG-05; Phase 02 implementation | `test_overlay.py`, forbidden-field/property tests |
| R-04 | Quant-only is separate preregistered variant, never dynamic overlay fallback | [04 Validation](../04_VALIDATION_AND_ALPHA_EVIDENCE.md), [Phase 06 Design](../phases/06-experiment-alpha-validation/DESIGN.md) | SIG-05, EXP-01/02 | `test_envelope_variants.py`, `test_matrix_seeds.py` |
| R-05 | Historical mode is immutable EvidenceBundle and network-free | [02 Target Architecture](../02_TARGET_ARCHITECTURE.md), [Phase 01 Design](../phases/01-point-in-time-data/DESIGN.md), [Phase 02 Design](../phases/02-evidence-agent-boundary/DESIGN.md) | PIT-06, SIG-01 | `test_bundle_replay.py`; cached-response hash/binding/cutoff tests; adapter no-callable, side-effect observer, UTC-date, output, and default-compatibility contract |
| R-06 | Enforce availability and archive ingestion cutoffs, preserving publication/event/valid/revision metadata | [03 Contracts](../03_CONTRACTS_AND_SCHEMAS.md), [01 Audit](../01_CURRENT_STATE_AUDIT.md) | PIT-01..06 | `test_cutoff_selection.py`, `test_financial_vintages.py` |
| R-07 | Address current yfinance/social/Polymarket/FRED/PIT/universe risks | [01 Audit](../01_CURRENT_STATE_AUDIT.md), [Phase 01 implementation](../phases/01-point-in-time-data/IMPLEMENTATION.md) | PIT-02..06 | bars/news/social/macro/universe fixtures |
| R-08 | Rule allocator before optional constrained optimizer; hard deterministic risk is shared/fail-closed/persistent | [02 Target Architecture](../02_TARGET_ARCHITECTURE.md), [Phase 04 Design](../phases/04-portfolio-risk/DESIGN.md) | RSK-02..05 | `test_engine_halts.py`, restart/property tests |
| R-09 | Deterministic simulator before OMS; fee-once NAV accounting | [03 Contracts](../03_CONTRACTS_AND_SCHEMAS.md), [Phase 03 Design](../phases/03-backtest-ledger/DESIGN.md) | BT-01..06 | `test_ledger_nav.py`, `test_fills_costs.py` |
| R-10 | Explicit spread/slippage/impact/liquidity/capacity and no double-counted fees | [04 Validation](../04_VALIDATION_AND_ALPHA_EVIDENCE.md), [Phase 05 Design](../phases/05-execution-cost-liquidity/DESIGN.md) | EXC-01..04 | `test_impact_liquidity.py`, `test_scenarios.py` |
| R-11 | Validate Cash, B&H, trend, Single Agent, No Debate, No Memory, Full Multi-agent, Quant-only, Quant+LLM | [04 Validation](../04_VALIDATION_AND_ALPHA_EVIDENCE.md) | EXP-01/02; Phase 06 implementation | `test_matrix_seeds.py` |
| R-12 | Use >=10 screen and >=30 final seeds unless budget preregistered | [04 Validation](../04_VALIDATION_AND_ALPHA_EVIDENCE.md), [Phase 06 Design](../phases/06-experiment-alpha-validation/DESIGN.md) | EXP-01/02 | seed threshold/property tests |
| R-13 | Report median/p5/p95/worst and required performance/risk/trading/relative/capacity metrics | [04 Validation](../04_VALIDATION_AND_ALPHA_EVIDENCE.md) | BT-06, EXP-04 | `test_metrics_reports.py`, `test_reports_gate.py` |
| R-14 | Walk-forward purge/embargo, sealed holdout, block bootstrap, DSR/PBO | [04 Validation](../04_VALIDATION_AND_ALPHA_EVIDENCE.md), [Phase 06 implementation](../phases/06-experiment-alpha-validation/IMPLEMENTATION.md) | EXP-03 | `test_walk_forward.py`, `test_statistics.py` |
| R-15 | Operate forward paper 8–12 weeks for operational reliability | [06 Roadmap](../06_ROADMAP_AND_PHASE_GATES.md), [Phase 08 Design](../phases/08-forward-paper-gate/DESIGN.md) | FWD-01..03 | `test_gate_promotion.py`, simulated calendar run |
| R-16 | Apache-2.0, no current NOTICE, retain notices/mark modifications/trademarks separate | [05 License](../05_REPOSITORY_LICENSE_AND_UPSTREAM.md), [UPSTREAM](../../../UPSTREAM.md) | FND-04; Phase 00 implementation | license/header/notice review and docs checks |
| R-17 | Independent history/upstream sync via fetch/review/cherry-pick or reviewed diff; no ancestry shortcut | [UPSTREAM](../../../UPSTREAM.md), [CHANGES](../../../CHANGES_FROM_UPSTREAM.md) | FND-04 | provenance review and link checks |
| R-18 | OMS transitions, stable IDs, outbox, reconciliation, unknown-ACK pause/query | [03 Contracts](../03_CONTRACTS_AND_SCHEMAS.md), [Phase 07 Design](../phases/07-broker-oms-paper-reconciliation/DESIGN.md) | OMS-01..06 | `test_state_machine.py`, `test_outbox_ids.py`, `test_reconciliation.py` |
| R-19 | Paper endpoint write allowed only after approval; live broker write false until Phase 09 | [02 Target Architecture](../02_TARGET_ARCHITECTURE.md), [Phase 07/08/09 designs](../phases/07-broker-oms-paper-reconciliation/DESIGN.md) | OMS-04, FWD-01..03, LIVE-01..02 | fake/sandbox paper test, live-write denial |
| R-20 | L0 read-only, L1 human-approved one/few symbols, L2 small allowlist, later automation new approval | [06 Roadmap](../06_ROADMAP_AND_PHASE_GATES.md), [Phase 09 Design](../phases/09-live-pilot/DESIGN.md) | LIVE-01..04 | `test_credentials_l0.py`, `test_l1_canary.py`, `test_l2_limits.py` |
| R-21 | Emergency handling requires human/liquidity/open-order/reconciliation policy; no unconditional liquidation | [Phase 09 Design](../phases/09-live-pilot/DESIGN.md), [Runbooks](C_OPERATIONAL_RUNBOOKS.md) | LIVE-04 | `test_kill_incident.py` |
| R-22 | Lock one mechanism, preserve Python 3.10–3.14, migrate/rollback from pip lower bounds | [Phase 00 Design](../phases/00-foundation/DESIGN.md), [07 PR plan](../07_PR_IMPLEMENTATION_PLAN.md) | FND-04 | `test_lock_consistency.py`, locked CI matrix |
| R-23 | Exactly 47 dependency-ordered PR slices and first two-week plan | [07 PR Plan](../07_PR_IMPLEMENTATION_PLAN.md) | FND-01 through LIVE-04 | PR-ID audit script, phase cross-reference audit |
| R-24 | Documentation is evidence-backed, no production readiness or alpha claim from current baseline | [01 Audit](../01_CURRENT_STATE_AUDIT.md), [04 Validation](../04_VALIDATION_AND_ALPHA_EVIDENCE.md) | all gates | `git diff --check`, Markdown/link/fence checks, review sign-off |

## Gate ownership

| Gate | Required records | Blocking status |
| --- | --- | --- |
| Foundation | schema/config/dependency/lock checks | fail or insufficient evidence |
| PIT | cutoff/revision/calendar/delisting/network-denial evidence | fail or insufficient evidence |
| Signal | overlay property/no-trade/variant evidence | fail or insufficient evidence |
| Backtest | event/fill/ledger/hash/metric evidence | fail or insufficient evidence |
| Portfolio/risk | target/constraint/resize/halt evidence | fail or insufficient evidence |
| Paper | OMS/PAPER/reconciliation evidence | fail or insufficient evidence |
| Forward | complete 8–12 week operational evidence | fail or insufficient evidence |
| Live | explicit level approval and drills | fail or insufficient evidence; no waiver |

# Appendix B — Test Matrix

This matrix separates implemented checks from planned verification. Test existence is not a PASS claim: bind each execution result to its exact head/base/tree. Historical counts are not current results.

## Current baseline regression

| Layer | Existing command/tests | What it proves | What it does not prove |
| --- | --- | --- | --- |
| Lint | `ruff check .` | Current Python style/static checks | PIT, ledger, broker, or alpha validity |
| Unit/integration | `python -m pytest -q` | Current graph/dataflow contract; historical baseline in 01_CURRENT_STATE_AUDIT was 576 passed, 2 skipped, 18 warnings, 69 subtests | Production package or paper/live readiness |
| Date/look-ahead | `pytest -q tests/test_date_boundaries.py tests/test_news_lookahead.py tests/test_yfinance_stale_ohlcv_guard.py` | Existing date filtering and stale guard behavior | Filing availability/vintage, archive replay, universe survivorship |
| Providers | `pytest -q tests/test_vendor_routing.py tests/test_provider_registry.py tests/test_polymarket.py` | Current provider routing and resilience | Network-free historical mode |
| Structured output | `pytest -q tests/test_structured_agents.py tests/test_signal_processing.py` | Current typed agent/render/string API | Numeric target portfolio or bounded overlay |
| Recovery/reporting | `pytest -q tests/test_checkpoint_resume.py tests/test_memory_log.py tests/test_reporting.py` | Current checkpoint/memory/report behavior | Append-only financial ledger or reconciliation |

## Implemented productionization checks

Run in the reviewed environment: `uv sync --locked --extra dev`, then
`uv run --no-sync pytest -q tests/productionization`. Default provider integrations are opt-in,
not enabled by the presence of a credential. These actual paths supersede old planned aliases.

| Area | Actual tests | Scope |
| --- | --- | --- |
| Common time/schema | `tests/productionization/test_contract_common.py`, `tests/productionization/test_run_context.py`, `tests/productionization/test_schema_registry.py` | Strict scalar/context/version rules |
| Config/logging | `tests/productionization/test_config_redaction.py`, `tests/productionization/test_audit_runtime_boundaries.py` | Redaction, dedicated handlers, microsecond precision |
| Dependency/lock/docs | `tests/productionization/test_dependency_direction.py`, `tests/productionization/test_dynamic_dependency_direction.py`, `tests/productionization/test_lock_consistency.py`, `tests/productionization/test_markdown_contracts.py` | Static policy and reproducibility checks |
| PIT capture | `tests/productionization/data/test_capture_provenance.py` | Raw capture/provenance/cutoffs |
| PIT typed domains | `tests/productionization/data/test_bars_calendar.py`, `tests/productionization/data/test_universe_actions.py`, `tests/productionization/data/test_financial_vintages.py`, `tests/productionization/data/test_events_macro.py` | Domain cutoff/vintage/action/calendar invariants |
| Sealed bundle | `tests/productionization/data/test_bundle_replay.py` | Canonical bytes, exact binding, replay policy |
| Closed research | `tests/productionization/research/test_adapter.py`, `tests/productionization/research/test_adapter_repairs.py`, `tests/productionization/research/test_cached_response.py`, `tests/productionization/research/test_authority_aliases.py` | No live inference; exact data-only cached replay and negative boundaries |
| Validation tooling | `tests/productionization/test_validation_boundaries.py`, `tests/productionization/test_harness_contracts.py` | Opt-in integration, installed origins, offline policy predicates |
| Design handoffs | `tests/productionization/test_design_handoffs.py` | Executable specification, not future ledger/OMS runtime |

## Planned productionization checks

| Area | Test module/fixture | Required assertions | Planned command |
| --- | --- | --- | --- |
| Evidence citations | `research/test_evidence_tools.py` | Every note cites IDs; prompt-injection text remains data; provenance retained | `pytest -q tests/productionization/research` |
| Quant | `quant/test_signal.py` | Fixed bundle/config/model yields same score; missing feature status explicit | `pytest -q tests/productionization/quant` |
| Overlay | `research/test_overlay.py` | Optional overlay; attenuate/veto plus abstain; multiplier [0,1]; timeout/error/abstain no trade; forbidden fields rejected | same |
| Variants | `quant/test_envelope_variants.py` | Quant-only separate from Quant+LLM; no dynamic fallback | same |
| Clock/events | `backtest/test_clock_events.py` | Close decision and earliest next-session execution; ordered events; restart sequence | `pytest -q tests/productionization/backtest` |
| Fills/costs | `backtest/test_fills_costs.py` | Deterministic fills, explicit spread/slippage/commission/impact, partial fill | same |
| Ledger/NAV | `backtest/test_ledger_nav.py` | Append-only, cash/position/receivable/liability balance, fee posted once, NAV formula, duplicate detection | same |
| Actions/benchmarks | `backtest/test_actions_benchmarks.py` | Corporate actions, Cash/B&H benchmark, raw return not called alpha | same |
| Replay hash | `backtest/test_replay_hash.py` | Economic/artifact hash excludes non-semantic run ID/wall clock and changes on semantic inputs | same |
| Metrics | `backtest/test_metrics_reports.py` | median/p5/p95/worst; Sharpe/Sortino/Calmar/MDD/turnover/cost/alpha/beta/IR/tracking error/exposure/capacity | same |
| Allocator | `portfolio/test_rule_allocator.py` | Long-only, unlevered, allowlist, cash weight, deterministic ordering, empty case | `pytest -q tests/productionization/portfolio` |
| Risk | `risk/test_engine_halts.py` | approve/reject/resize/revalidation, fail closed, persistent halt restart/clear | `pytest -q tests/productionization/risk` |
| Optimizer | `portfolio/test_optimizer.py` | Constraint feasibility, timeout, same RiskEngine, rule comparison, default off | portfolio command |
| Liquidity/cost | `costs/test_impact_liquidity.py` | PIT ADV, stale/missing rejection, monotonic impact, capacity | `pytest -q tests/productionization/costs` |
| Partial/capacity | `costs/test_partial_capacity.py` | Incremental fills, residual cancellation, no forced fills | same |
| Experiments | `experiments/test_matrix_seeds.py` | Nine required variants; 10 screening/30 final seeds or preregistered budget | `pytest -q tests/productionization/experiments` |
| Walk-forward | `experiments/test_walk_forward.py` | Purge/embargo, no overlap, sealed access, post-opening read-only audit and contamination rule | same |
| Statistics | `experiments/test_statistics.py` | Block bootstrap, DSR/PBO inputs/trial count, deterministic seeds | same |
| Gate report | `experiments/test_reports_gate.py` | Metrics complete; pass/fail/insufficient evidence; no mandatory waiver | same |
| OMS | `execution/test_state_machine.py` | Full status transitions with risk/approval before submission; unknown ACK pause/query | `pytest -q tests/productionization/execution` |
| Idempotency | `execution/test_outbox_ids.py` | Stable IDs, duplicate/conflict handling, restart recovery | same |
| Paper | `execution/test_paper_broker.py`, `test_paper_endpoint.py` | Local deterministic and approved external PAPER parity; default false; live write denied | same |
| Reconciliation | `execution/test_reconciliation.py` | Cash/positions/open orders/fills/hash match; delta halts/investigates | same |
| Forward | `forward/test_gate_promotion.py` | 8–12 week complete/incomplete session behavior, paper mode, review gate | `pytest -q tests/productionization/forward` |
| Live | `live/test_credentials_l0.py`, `test_l1_canary.py`, `test_l2_limits.py`, `test_kill_incident.py` | L0 no-write; human approvals; allowlist/limits; policy-driven emergency plan requiring human/liquidity/open-order/reconcile assessment | `pytest -q tests/productionization/live` |

## CI ordering

Run focused tests for the changed phase, then contract/dependency/link/fence checks, then full current baseline tests and Ruff. Current CI runs Python 3.10–3.14 using `uv sync --locked --extra dev`, full pytest, Ruff, dependency/Markdown/lock checks, and a non-editable installed-origin smoke outside the checkout. The Foundation job includes productionization tests. Optional live integrations are not counted as passed when skipped. Synthetic 8–12 week tests validate software only; operational promotion requires real elapsed sessions and human approval.

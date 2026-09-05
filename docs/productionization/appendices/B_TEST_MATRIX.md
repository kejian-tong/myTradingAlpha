# Appendix B — Test Matrix

This matrix is the planned verification surface. It separates current-repository regression checks from future productionization checks and names deterministic fixtures. No row is a claim that the future test exists or passes today.

## Current baseline regression

| Layer | Existing command/tests | What it proves | What it does not prove |
| --- | --- | --- | --- |
| Lint | `ruff check .` | Current Python style/static checks | PIT, ledger, broker, or alpha validity |
| Unit/integration | `python -m pytest -q` | Current graph/dataflow contract; supplied baseline was 576 passed, 2 skipped, 18 warnings, 69 subtests | Production package or paper/live readiness |
| Date/look-ahead | `pytest -q tests/test_date_boundaries.py tests/test_news_lookahead.py tests/test_yfinance_stale_ohlcv_guard.py` | Existing date filtering and stale guard behavior | Filing availability/vintage, archive replay, universe survivorship |
| Providers | `pytest -q tests/test_vendor_routing.py tests/test_provider_registry.py tests/test_polymarket.py` | Current provider routing and resilience | Network-free historical mode |
| Structured output | `pytest -q tests/test_structured_agents.py tests/test_signal_processing.py` | Current typed agent/render/string API | Numeric target portfolio or bounded overlay |
| Recovery/reporting | `pytest -q tests/test_checkpoint_resume.py tests/test_memory_log.py tests/test_reporting.py` | Current checkpoint/memory/report behavior | Append-only financial ledger or reconciliation |

## Future productionization matrix

| Area | Test module/fixture | Required assertions | Planned command |
| --- | --- | --- | --- |
| Contract time | `contracts/test_run_context.py` | UTC-aware; `knowledge_cutoff <= decision_time < earliest_execution_time`; invalid order rejected | `python -m pytest -q tests/productionization/contracts` |
| Schema versions | `contracts/test_schema_registry.py` | Additive migration; unknown version rejected; no silent field drop | same |
| Dependency/lock | `test_dependency_direction.py`, `test_lock_consistency.py` | No `tradingagents` → `mytradingalpha`; only research adapter reverse import; `uv.lock` matches source and Python 3.10–3.14 | `python scripts/check_dependency_direction.py && python scripts/check_lock_consistency.py` |
| Redaction | `test_config_redaction.py`, secret-bearing fixture | No API key/access token/broker secret in logs/artifacts | `pytest -q tests/productionization/test_config_redaction.py` |
| PIT cutoff | `data/test_cutoff_selection.py` | Future availability excluded; archive ingestion cutoff applied; undated policy explicit | `pytest -q tests/productionization/data/test_cutoff_selection.py` |
| Revisions/vintages | `data/test_financial_vintages.py`, `test_events_macro.py` | Latest valid revision available by cutoff selected; filing vs fiscal date distinguished; macro vintage captured | same |
| Bars/calendar | `data/test_bars_calendar.py` | Session/holiday/early-close, adjustment policy, stale/missing bar behavior | same |
| Universe/actions | `data/test_universe_actions.py` | Delisting/ticker changes/splits/dividends and historical membership applied | same |
| Bundle replay | `data/test_bundle_replay.py` | Immutable bundle, canonical semantic hash, network-denied repeat; wall-clock/run IDs excluded from semantic hash | same |
| Research adapter | `research/test_adapter.py`, `research/test_cached_response.py` | Exact bundle/context/response ID/hash/instrument/artifact/provenance binding; bounded canonical JSON only; availability/archive cutoff and UTC snapshot-date rule; no callable/dynamic loading; current final/five-tier shape; provider/persistence/checkpoint/file/socket/clock/env denied; missing/corrupt/mismatched/unsafe output fails closed; ordinary graph remains default | `pytest -q tests/productionization/research` |
| Evidence citations | `research/test_evidence_tools.py` | Every note cites IDs; prompt-injection text remains data; provenance retained | same |
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

Run focused tests for the changed phase, then contract/dependency/link/fence checks, then full current baseline tests and Ruff. A future locked CI job should run the Python 3.10–3.14 matrix with `uv sync --locked`; until that migration is approved, the current pip lower-bound CI remains the baseline comparison.

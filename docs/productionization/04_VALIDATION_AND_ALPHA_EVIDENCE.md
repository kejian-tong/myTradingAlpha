# Validation and Alpha Evidence

## Claims policy

The current project is a research/recommendation graph. Passing unit tests or producing a favorable chart is not evidence of portfolio alpha, paper readiness, or live readiness. A valid claim must identify the data snapshot, variant, seeds, costs, execution assumptions, split policy, and reviewer. Forward paper primarily tests operational reliability; it does not establish long-term alpha.

## Paper evidence baseline

The prior audited paper evidence covers 2024-01-01 through 2024-03-29, approximately three months. Its narrative discusses more stocks, while Table 1 reports AAPL, GOOGL, and AMZN; the reported TradingAgents Sharpe values are 8.21, 6.39, and 5.60 respectively. The comparison baselines are B&H, MACD, KDJ+RSI, ZMR, and SMA, and the reported metrics are cumulative return (CR), annualized return, Sharpe, and maximum drawdown (MDD). A footnote describes 11 LLM calls and 20+ tool calls per prediction and acknowledges that longer tests are needed. Source: the [TradingAgents paper PDF](https://arxiv.org/pdf/2412.20138).

This is an evidence review, not an investment claim. The paper does not establish strict PIT release/vintage proof, transaction-cost/fill/liquidity/impact details, multiple seeds or confidence intervals, walk-forward evaluation with a locked holdout, or reproducible released artifacts. The requirements below therefore treat the paper as useful historical context and a motivation for stronger controls, not as validation of the current repository or a production strategy.

## Required variants

Every final report includes these rows with identical universe, dates, data snapshot, cost model, and reporting metrics:

1. **Cash** — zero-risk reference with all capital held as cash.
2. **B&H** — buy-and-hold benchmark with explicit rebalance/dividend policy.
3. **Trend** — deterministic trend baseline with preregistered lookback and no LLM.
4. **Single Agent** — one selected research agent plus a deterministic mapping.
5. **No Debate** — research path without bull/bear debate.
6. **No Memory** — full eligible pipeline with memory disabled.
7. **Full Multi-agent** — current research graph adapter with deterministic downstream decisions.
8. **Quant-only** — deterministic quant signal, separately preregistered; no dynamic fallback from an overlay run.
9. **Quant+LLM** — quant signal plus an optional bounded LLM overlay; when present it may attenuate or veto and carries a separate abstain flag; overlay failure or abstain is no trade.

The attachment's permissive confidence-increase variant is not a comparison row because it would allow the overlay to increase quant influence. Quant-only is run as its own preregistered variant, never as a dynamic fallback from Quant+LLM.

## Seed and budget policy

Screening uses at least 10 independent seeds per variant. The final report uses at least 30 independent seeds per variant unless a smaller budget is preregistered before inspecting results, with the reason, expected uncertainty, and decision consequence recorded in `ExperimentSpec`. Seeds control model sampling and any stochastic simulator component; deterministic variants still publish the complete seed list for comparability.

Reports show median, p5, p95, and worst-case results across seeds. A single best seed is never the headline result.

## Time-split discipline

- Use walk-forward train/validation/test windows with a purge around labels and an embargo after each training window. The purge removes overlapping information; the embargo prevents adjacent leakage.
- Keep a sealed holdout period and universe manifest outside the tuning loop. Open it only after variant code, metrics, cost model, and seed list are frozen.
- Preserve event time, published time, available time, ingestion time, revision, and validity interval for each feature. A fiscal-period filter is not a filing-availability filter.
- Include delisted names and historical membership where the strategy claims an investable universe. Report survivorship and selection policy.
- Use only the immutable bundle in historical mode. Current-time yfinance, StockTwits/Reddit, Polymarket, pending-memory outcome fetches, and provider retries with future knowledge are forbidden.

## Metrics

The report includes, per seed and aggregate:

| Category | Required measures |
| --- | --- |
| Return/risk | cumulative return, CAGR, volatility, Sharpe, Sortino, Calmar, maximum drawdown (MDD), drawdown duration, median/p5/p95/worst |
| Trading | turnover, trade count, hit rate, holding period, gross cost, commissions, spread, slippage, market impact, net cost |
| Relative performance | alpha, beta, information ratio (IR), tracking error, active return, benchmark-relative drawdown |
| Exposure/capacity | gross and net exposure, sector/concentration exposure, cash, leverage check, ADV participation, capacity under stress costs |
| Operations | run latency, missing/stale evidence, LLM error/abstain rate, risk rejects, fill rate, unknown acknowledgements, reconciliation breaks |

Costs are applied once in the ledger and carried into NAV; reports must not subtract the same fee again. Raw close-minus-benchmark is not portfolio alpha.

## Statistical safeguards

- Use block bootstrap over time blocks, preserving serial dependence, to produce uncertainty intervals for return, alpha, and risk metrics.
- Report Deflated Sharpe Ratio (DSR) when multiple trials or variants were searched, with the number of trials and selection rule.
- Report Probability of Backtest Overfitting (PBO) or an equivalent combinatorial split diagnostic when the search space permits it.
- Record all rejected runs, failed seeds, data gaps, and post-hoc exclusions. An excluded seed requires a reason code and cannot be silently removed.
- Use a preregistered decision rule; do not promote a variant because it wins one metric while degrading cost, drawdown, or capacity.

## Walk-forward report shape

```text
window_id, train_start, train_end, validation_start, validation_end,
test_start, test_end, purge_sessions, embargo_sessions, universe_hash,
bundle_hash, variant_id, seed, gross_return, net_return, MDD, turnover,
cost, alpha, beta, IR, tracking_error, capacity, status
```

The report stores code/config/artifact hashes and links to immutable evidence. It does not include credentials or raw sensitive provider payloads.

## Forward-paper evidence

Operate the selected candidate for 8–12 weeks with:

- a daily close capture and bundle hash;
- the same decision and risk path as the eventual pilot;
- deterministic paper fills with spread/slippage assumptions recorded;
- human approval logs where required;
- append-only intents, events, fills, NAV, costs, and reconciliation;
- daily data-quality, latency, alert, and incident records; and
- weekly review of drift, missingness, operational failures, and discrepancy closure.

Pass requires complete evidence for the required sessions, no unexplained reconciliation break, no unreviewed hard-risk breach, repeatable reruns from the captured bundle, and an explicit approval. Alpha remains provisional until sealed holdout and operational evidence are reviewed together.

## Acceptance gates

| Gate | Evidence | Result if missing |
| --- | --- | --- |
| Data | PIT cutoff tests, revisions/vintages, delistings, bundle hash | reject run |
| Reproducibility | repeat replay, seed manifest, lock/constraints record | reject report |
| Portfolio | ledger identities, fee-once invariant, exposure/turnover | reject candidate |
| Statistics | walk-forward purge/embargo, bootstrap, DSR/PBO where applicable | no alpha claim |
| Operations | 8–12 week paper completeness and reconciliation | no promotion |
| Governance | reviewer, variant preregistration, sealed holdout record | no promotion |

No mandatory promotion gate may be waived by changing the metric definition after results are visible. Use only `pass`, `fail`, or `insufficient_evidence`; `insufficient_evidence` blocks promotion and requires a new evidence record. A non-promotion deviation may be recorded for audit, but its status remains `fail` or `insufficient_evidence`.

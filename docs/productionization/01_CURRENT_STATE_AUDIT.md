# Current-State Audit

## Scope and provenance

This audit targets the current repository baseline `212dcef3a7b6865f513b9400436e59b7aa967984` and compares it with upstream snapshot `a33fd4c0f134485a43553a2c23a63cb14adbd88f`. It is not an audit of a historical package release. Upstream tag `v0.3.1` is at `01477f9`; six later upstream commits already present in this tree are `d78c698`, `40774ca`, `3f6c082`, `030b434`, `7bbe33a`, and `a33fd4c`. The independent histories have no merge base, so path/blob comparison is used. See [`UPSTREAM.md`](../../UPSTREAM.md) and [`CHANGES_FROM_UPSTREAM.md`](../../CHANGES_FROM_UPSTREAM.md).

## What exists today

| Area | Evidence in current tree | Interpretation |
| --- | --- | --- |
| Research graph | [`tradingagents/graph/setup.py`](../../tradingagents/graph/setup.py#L113-L154) connects analysts sequentially, then research, trader, risk, and portfolio nodes. | Useful research/recommendation workflow; not portfolio execution. |
| State | [`AgentState`](../../tradingagents/agents/utils/agent_states.py#L47-L76) contains reports, debate state, trade date, and memory context. | No cash, positions, orders, fills, NAV, constraints, or portfolio snapshot. |
| Typed output | [`TraderProposal`](../../tradingagents/agents/schemas.py#L121-L180) uses string `position_sizing`; [`PortfolioDecision`](../../tradingagents/agents/schemas.py#L188-L223) is rating/prose; [`SignalProcessor`](../../tradingagents/graph/signal_processing.py#L20-L30) returns a five-tier string. | These are human-readable research artifacts, not numeric target portfolios or order intents. |
| Provider/data boundary | [`tradingagents/dataflows/interface.py`](../../tradingagents/dataflows/interface.py) exposes vendor routing and fallback; tests cover provider routing and unavailable data. | A useful adapter seam; it does not provide immutable PIT archives. |
| Checkpointing/reporting | [`tradingagents/graph/checkpointer.py`](../../tradingagents/graph/checkpointer.py), [`tradingagents/reporting.py`](../../tradingagents/reporting.py), and memory utilities persist graph runs and markdown reports. | Reproducibility aids, not an append-only trading ledger. |
| CI/security | [`ci.yml`](../../.github/workflows/ci.yml) tests Python 3.10–3.14, smoke-imports, and Ruff; CodeQL and dependency review are present. | Strong local engineering baseline; no production readiness implication. |
| Dependencies | [`pyproject.toml`](../../pyproject.toml) has open lower bounds and no lock file. | Reproducibility requires a future lock/constraints policy. |

## Temporal and data risks

- [`TradingAgentsGraph._resolve_pending_entries`](../../tradingagents/graph/trading_graph.py#L296-L334) runs at the start of `propagate`, fetches current prices/benchmark outcomes, and generates reflections. In historical replay this can leak future information and must be bypassed by an immutable EvidenceBundle path.
- [`sentiment_analyst.py`](../../tradingagents/agents/analysts/sentiment_analyst.py#L61-L81) prefetches current StockTwits and Reddit data without a trade-date cutoff; this is not a valid historical input.
- [`polymarket.py`](../../tradingagents/dataflows/polymarket.py#L47-L107) deliberately uses live-now event filtering; it is unavailable to network-free historical replay.
- `yfinance` fundamentals in [`y_finance.py`](../../tradingagents/dataflows/y_finance.py#L274-L338) document `curr_date` as unused for the overview, and statement filters use fiscal period columns in [`filter_financials_by_date`](../../tradingagents/dataflows/stockstats_utils.py#L224-L232), not filing availability or revision vintages.
- [`fred.py`](../../tradingagents/dataflows/fred.py) limits observations by date but does not expose an ALFRED vintage/as-of retrieval contract.
- [`load_ohlcv`](../../tradingagents/dataflows/stockstats_utils.py#L148-L221) filters rows to `curr_date`, but downloads with `auto_adjust=True`; a production PIT archive must preserve the provider snapshot and adjustment policy explicitly.
- No PIT universe/delisting/corporate-action system exists. Survivorship bias remains unaddressed.

## Backtest, portfolio, and execution gaps

The dependency on Backtrader in [`pyproject.toml`](../../pyproject.toml) is not a shipped deterministic simulator. There is no production-owned backtest runner, append-only ledger, cash/position accounting, optimizer, target portfolio, order-intent model, broker adapter, fill model, OMS transition table, or reconciliation workflow. Existing raw return and benchmark reflection paths do not prove portfolio alpha, capacity, or implementable costs.

## Strengths to preserve

The current code has a provider/vendor registry, typed agent outputs, checkpointing, report writing, news UTC/end-exclusive and current-day OHLCV refresh fixes, and CI/security checks. Keep those seams stable while adding a separate package. Existing tests include date boundaries, news look-ahead guards, provider routing, structured output, stale-data handling, checkpoint resume, and memory logging.

## Baseline validation evidence

On Python 3.12 in a fresh temporary virtual environment, the baseline validation supplied for this audit is:

- `ruff check .`: passed.
- `python -m pytest -q`: 576 passed, 2 skipped, 18 warnings, and 69 subtests passed.
- Skips were the optional `langchain_aws` coverage and a live DeepSeek API-key path.
- Current GitHub CI at this SHA is successful across its configured jobs.

These are local-contract and CI signals only. They do not prove PIT correctness, deterministic backtest correctness, alpha, forward-paper reliability, or live readiness. Open dependency lower bounds and the absence of a lock file also prevent strict environment reproducibility.

## Audit acceptance

The audit is accepted when every new implementation PR links the exact current integration point it touches, adds a deterministic fixture, records a failure/rollback path, and keeps historical mode network-free. No claim of paper or live readiness may be made until the phase gates in [`06_ROADMAP_AND_PHASE_GATES.md`](06_ROADMAP_AND_PHASE_GATES.md) are evidenced.

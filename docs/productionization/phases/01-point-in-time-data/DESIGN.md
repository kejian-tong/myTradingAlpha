# Phase 01 — Point-in-Time Data Design

Status: implemented at the current contract scope. PIT-01 through PIT-06 have shipped with typed-domain fixture/contract evidence; complete vendor coverage and historical authenticity remain separate evidence obligations. This phase creates immutable, availability-aware inputs for historical and archive-realistic replay.

## Goals

- Capture raw provider responses with provenance, checksums, timestamps, revisions, and terms metadata.
- Normalize bars, fundamentals, news/social, macro, corporate actions, calendars, and universe membership.
- Build an immutable, hash-addressed `EvidenceBundle` and a network-denied replay guard.

## Scope

Raw/canonical/PIT layers, exchange calendar, adjusted/unadjusted price policy, filing/vintage availability, event timestamps, corporate actions, delistings, small allowlist manifests, bundle sealing, and quality/leakage checks.

## Non-goals

No quant model, LLM prompt redesign, portfolio target, order, broker adapter, live ingestion, or return/alpha claim.

## Dependencies

Depends on Phase 00 contracts/config. Current source seams are [`tradingagents/dataflows/interface.py`](../../../../tradingagents/dataflows/interface.py), [`stockstats_utils.py`](../../../../tradingagents/dataflows/stockstats_utils.py), [`y_finance.py`](../../../../tradingagents/dataflows/y_finance.py), [`alpha_vantage_fundamentals.py`](../../../../tradingagents/dataflows/alpha_vantage_fundamentals.py), [`yfinance_news.py`](../../../../tradingagents/dataflows/yfinance_news.py), [`fred.py`](../../../../tradingagents/dataflows/fred.py), [`polymarket.py`](../../../../tradingagents/dataflows/polymarket.py), and [`symbol_utils.py`](../../../../tradingagents/dataflows/symbol_utils.py).

## Components and dataflow

```text
provider capture -> raw immutable object -> normalized records -> PIT selector
       -> calendar/universe/action joins -> EvidenceBundle seal -> replay guard
```

Selection is by availability and validity, not merely event/fiscal date. Archive-realistic policy additionally enforces `ingested_at <= knowledge_cutoff`.

## Current integration points

- [`load_ohlcv`](../../../../tradingagents/dataflows/stockstats_utils.py#L148-L221) filters by `curr_date` but uses live yfinance downloads and `auto_adjust=True`.
- [`filter_financials_by_date`](../../../../tradingagents/dataflows/stockstats_utils.py#L224-L232) filters fiscal-period columns, not filing availability.
- [`get_fundamentals`](../../../../tradingagents/dataflows/y_finance.py#L274-L338) documents `curr_date` as unused for its overview.
- [`create_sentiment_analyst`](../../../../tradingagents/agents/analysts/sentiment_analyst.py#L61-L81) prefetches current social/news data without an archival capture contract.
- [`get_prediction_markets`](../../../../tradingagents/dataflows/polymarket.py#L68-L107) uses live-now event filtering.

## Interfaces and invariants

`CapturedPayload` has source, locator, fetched time, checksum, and raw bytes. `Observation` has event time, published time when known, `available_at`, `ingested_at`, validity interval, revision, quality, and source locator. `EvidenceBundle` is immutable and content-addressed. For every selected observation, `available_at <= knowledge_cutoff`; archive-realistic replay also requires `ingested_at <= knowledge_cutoff`. Undated items are rejected or explicitly marked unavailable. Current-time calls are impossible in historical mode.

## Decisions and alternatives

- Preserve raw and normalized layers rather than only final CSVs so revisions and provenance remain auditable.
- Use a versioned exchange calendar and explicit adjustment policy rather than relying on provider defaults.
- Include delisted/inactive membership rather than a survivor-only list.
- Use an internal content-addressed store first; a hosted lakehouse is a later deployment choice, not a prerequisite for the contract.

## Failure, security, and observability

Required source failure rejects a bundle; optional source failure is a reason-coded degradation and is accepted only by a variant policy. Malformed timestamps, checksum mismatch, impossible validity intervals, and future availability fail closed. Provider credentials are used only by capture jobs, never passed to research agents or stored in bundles. Observe source latency, row counts, missingness, stale bars, revision counts, and bundle hash.

## Migration and rollback

Run the bundle builder beside existing dataflows. Existing analyst tools remain unchanged for non-historical runs. A bad source adapter is disabled and the previous sealed bundle or a smaller allowlist is selected; raw captures are retained for forensic review. Never mutate a sealed bundle to repair data.

## Acceptance and gate

Pass requires future/undated/revision/delisting/calendar fixtures, deterministic bundle hash, archive-realistic cutoff checks, and a network-denied replay. `insufficient_evidence` blocks signal/backtest work.

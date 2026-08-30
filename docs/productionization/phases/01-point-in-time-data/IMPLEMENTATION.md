# Phase 01 — Point-in-Time Data Implementation

Commands below are planned until an implementation record provides output.

## Ordered PR/work packages

1. **PIT-01** — capture/provenance/raw store.
2. **PIT-02** — bars and exchange calendar.
3. **PIT-03** — financial filing availability and vintages.
4. **PIT-04** — news, social, and macro captures.
5. **PIT-05** — universe, delistings, and corporate actions.
6. **PIT-06** — EvidenceBundle builder and replay guard.

## Exact existing files to touch

- [`tradingagents/dataflows/interface.py`](../../../../tradingagents/dataflows/interface.py) only for a narrow capture adapter, if needed.
- [`tradingagents/dataflows/stockstats_utils.py`](../../../../tradingagents/dataflows/stockstats_utils.py) only to expose existing normalization without changing default behavior.
- [`tradingagents/dataflows/y_finance.py`](../../../../tradingagents/dataflows/y_finance.py), [`alpha_vantage_fundamentals.py`](../../../../tradingagents/dataflows/alpha_vantage_fundamentals.py), [`yfinance_news.py`](../../../../tradingagents/dataflows/yfinance_news.py), [`fred.py`](../../../../tradingagents/dataflows/fred.py), and [`polymarket.py`](../../../../tradingagents/dataflows/polymarket.py) only at adapter boundaries.
- [`tradingagents/dataflows/symbol_utils.py`](../../../../tradingagents/dataflows/symbol_utils.py) for canonical instrument mapping reuse.

## Proposed files, classes, and APIs

- `mytradingalpha/data/capture.py`: `CaptureClient.capture()` -> `CapturedPayload`.
- `mytradingalpha/data/provenance.py`: `SourceManifest`, `RevisionRecord`, `AvailabilityPolicy`.
- `mytradingalpha/data/raw_store.py`: `RawStore.put/get()` with checksum verification.
- `mytradingalpha/data/bars.py`: `BarRepository.as_of()`.
- `mytradingalpha/data/calendar.py`: `TradingCalendar.sessions/next_session()`.
- `mytradingalpha/data/fundamentals.py`: `FilingRepository.as_of()`.
- `mytradingalpha/data/vintages.py`: `VintageSelector.select()`.
- `mytradingalpha/data/events.py`, `social.py`, `macro.py`: captured event repositories.
- `mytradingalpha/data/universe.py`: `UniverseManifest.members(as_of)`.
- `mytradingalpha/data/actions.py`: `CorporateActionRepository.apply()`.
- `mytradingalpha/data/bundle.py`: `build_evidence_bundle()` and `EvidenceRepository.seal()`.
- `mytradingalpha/data/replay_guard.py`: `HistoricalDataGuard.assert_network_denied()`.

## Schema and pseudocode

```text
capture(source, locator, payload, fetched_at)
  -> checksum = sha256(payload)
  -> persist immutable raw object and SourceManifest

select(observations, cutoff, policy)
  -> reject available_at > cutoff
  -> if archive_realistic: reject ingested_at > cutoff
  -> choose highest revision valid at cutoff
  -> retain source/time/revision IDs

seal(records, manifest)
  -> canonical sort -> canonical JSON -> bundle_hash
  -> mark immutable -> reject any later mutation
```

## Red-green-refactor

1. Red: create fixtures where an event is published after its event date, a restatement arrives later, a bar is future-dated, a symbol delists, and a source is undated.
2. Green: implement timestamp selection, revision selection, calendar, universe/action joins, and bundle sealing.
3. Refactor: isolate vendor adapters, make canonical serialization stable, and add an explicit network guard.

## Exact tests and fixtures

- `tests/productionization/data/test_cutoff_selection.py`: future availability, archive ingestion, undated rejection, revision choice.
- `tests/productionization/data/test_bars_calendar.py`: UTC/session boundaries, holiday/early close, stale/missing bars, adjustment policy.
- `tests/productionization/data/test_financial_vintages.py`: filing date vs fiscal period, restatement, vintage selection.
- `tests/productionization/data/test_events_macro.py`: news publication, social capture, FRED-style vintage, Polymarket blocked replay.
- `tests/productionization/data/test_universe_actions.py`: delisting, ticker change, split, dividend, allowlist membership.
- `tests/productionization/data/test_bundle_replay.py`: canonical hash, mutation rejection, network-denied historical run.
- Fixtures under `tests/productionization/fixtures/pit/` contain no live provider response beyond minimal synthetic examples.

## Validation commands

```bash
python -m pytest -q tests/productionization/data
python -m pytest -q tests/test_date_boundaries.py tests/test_news_lookahead.py tests/test_alpha_vantage_hardening.py
ruff check .
python scripts/check_dependency_direction.py
```

The commands are planned for implementation; each PR records the actual interpreter and fixture manifest hash.

## Migration and compatibility

Do not remove or change current vendor functions. Add a `HistoricalDataProvider` interface and select it only when `RunContext.mode=historical`. Existing cache files are read-only inputs or ignored; no current cache is silently promoted to an immutable archive. Bundle schema migration creates a new bundle ID/hash and leaves old bundles readable.

## Definition of done

- All six PIT PRs pass focused tests and a repeat offline replay.
- Every selected observation carries availability/provenance/revision metadata.
- Current-time tools are inaccessible from historical mode.
- Calendar, corporate-action, and historical-universe policies are versioned.
- Gate evidence is `pass`; `fail` or `insufficient_evidence` blocks Phase 02.

## Evidence and rollback

Evidence consists of synthetic fixture manifests, bundle hashes, cutoff test output, network-denial output, and data-quality counters. Rollback disables the new provider/bundle selector and returns non-historical calls to existing dataflows; sealed raw objects and prior bundles remain intact. No external data deletion or provider write is authorized.

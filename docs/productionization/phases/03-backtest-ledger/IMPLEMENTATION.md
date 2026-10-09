# Phase 03 — Backtest and Ledger Implementation

Status: planned. This document is an implementation plan; its commands and test names are not claims that code or tests exist or have run. The PH03-DOCS reconciliation is prose-only, so its RED phase is not applicable and it creates no synthetic failing test. Each future executable BT PR must have its own exact-base JIT, dedicated tests-only RED commit pushed before implementation, focused expected failure, minimum GREEN, in-scope refactor, exact validation and rollback evidence. Implement one BT ID per fresh Master session after its prerequisite is merged and main is refreshed.

## Current integration facts and compatibility

The existing source of historical inputs is `mytradingalpha.data.bundle.EvidenceBundle` with its typed-domain v1 records and `mytradingalpha.contracts.schemas.RunContext`. The existing `mytradingalpha.data.calendar.TradingCalendar` exposes `session(date)`, `next_session(date)`, `sessions(start, end)`, and optional `replay_evidence`; `capture_calendar_replay_evidence()` produces the bounded timezone replay witness. The new BT runner requires that witness locally without making it mandatory for legacy PIT readers. `mytradingalpha.contracts.signals.SignalEnvelope` is immutable, full-source, shadow-only, rejects JSON ingress and validates `created_at == context.decision_time`.

No current `TradingAgentsGraph`, graph checkpointer, yfinance cache, current provider, or live research output is a Phase 03 outcome or ledger. Do not edit `tradingagents/`, import it from backtest code, reuse its pending-return state as financial history, or change its imports, CLI, config precedence, distribution identity, or persisted artifacts. The planned runner takes only bounded validated values. It does not call provider/model code, network, subprocesses, environment/credential discovery, allocator, risk, OMS, broker or promotion APIs. Do not introduce Backtrader or another dependency.

At replay, map `decision_time` through exactly one sealed `CalendarReplayDay` with `start_utc <= decision_time < end_utc`, use its `local_date`, then verify `TradingCalendar.session(local_date).close_at == decision_time`. Do not use host `ZoneInfo` or current timezone data, or capture calendar replay evidence during BT. Require the presealed witness only at the BT boundary; leave legacy PIT readers unchanged.

## Ordered implementation and test ownership

| PR | Dependencies | Production files and proposed symbols | Planned tests and observable acceptance | Rollback |
| --- | --- | --- | --- | --- |
| BT-01 | PIT-06, SIG-05 | `mytradingalpha/backtest/clock.py`: `SessionBinding`, `SessionClock`; `events.py`: `BacktestEvent`, `DecisionEvent`, `OpportunityEvent`; `runner.py`: `BacktestRunner`. No `contracts/orders.py` or accounting file. | `tests/productionization/backtest/test_clock_events.py`: exact close/date binding, cutoff and next verified open, witnessed holiday/early close, gap/end denial, no-trade, stable event order/sequence, mutation and callback rejection. Acceptance: deterministic decision plus next-session opportunity events, zero fills and no quantity mapping. | Disable only the new offline runner. Preserve existing typed bundles, envelopes and Research Graph behavior. |
| BT-02 | BT-01 | `mytradingalpha/contracts/orders.py`: first shared `OrderIntent` and `Fill`; `mytradingalpha/backtest/orders.py`: `SimOrder`, `OrderBook`; `fills.py`: `FillModel`, `Simulator`; `costs/__init__.py`: public `CostModel.quote()` facade. | `test_fills_costs.py`: adverse buy/sell price, marketable/non-marketable limit, no clipping, next-session close versus later receipt time, TIF, fixed-share cap/lot, cash/holding bounds, zero cap, no-trade, explicit zero versus missing/negative costs, cumulative fee minimum across 2/3/5 partials, and no short/leverage. Acceptance: deterministic simulation-only partial fills and fee/cost attribution, with no ledger runtime or OMS effects. | Select a prior versioned offline cost/fill policy for a new derived simulation. Keep existing cost policies and artifacts. |
| BT-03 | BT-02 | `mytradingalpha/backtest/ledger.py`: internal `LedgerEvent`, `LedgerBalance`, `Ledger.append/replay/balance`; `nav.py`: `NAVCalculator.compute`; `accounting.py`: `AccountingInvariant.check`. | `test_ledger_nav.py`: atomic fill, cash/position/NAV identity, fee once, same-ID/same-payload no-op, conflicting ID, sequence gap, defensive immutability, insufficient cash, oversell, exact Decimal bounds, balanced receivable/liability, and missing/future/stale/wrong-currency mark. Acceptance: append-only replay reproduces balances and rejects any illegal partial state before mutation. | Stop new appends and replay the last valid immutable prefix into a new derived artifact. Never edit/delete ledger history. |
| BT-04 | BT-03, PIT-05 | `mytradingalpha/backtest/corporate_actions.py`: action reducer and settlement events; `benchmarks.py`: independent Cash and B&H reducers/series. Consume current PIT action contracts; do not change them. | `test_actions_benchmarks.py`: late revision, adjusted-price/action conflict, exact split NAV preservation, split/identity/dividend tie priority, cancellation of pre-split orders, fraction/cash-in-lieu, pretrade entitlement, once-only receivable/payment, non-session pay date, alias identity, unavailable merger, missing/explicit delisting settlement, separate cash/B&H ledgers, no survivor selection or unconfigured reinvestment. Acceptance: action and benchmark series are deterministic and versioned. | Select the prior action/benchmark policy and replay to a new artifact. Retain every previous artifact and failed run. |
| BT-05 | BT-01 through BT-04 | `mytradingalpha/backtest/manifest.py`: `ReplayManifest`, typed economic projections, three hash functions; `replay.py`: `ReplayCheckpoint`, `ReplayRunner` and explicit-root atomic persistence/resume. Do not modify/reuse `tradingagents/graph/checkpointer.py`. | `test_replay_hash.py`: different run IDs with same economic inputs produce distinct exact artifact hashes but equal semantic/economic hashes; changed cutoff/data/fee/config/code/seed changes the relevant hash; nested SIG source projection; unknown fields/version, duplicate keys, cycles, NaN/infinity, custom objects and oversized data reject; crash boundaries, torn prefix, changed inputs, path escape/symlink and concurrent writer reject. Acceptance: unchanged resume matches uninterrupted economics and every mismatch retains evidence and stops. | Stop resume on mismatch. Keep old manifests/results immutable and create a new artifact for changed semantics; no migration overwrites. |
| BT-06 | BT-03 through BT-05 | `mytradingalpha/backtest/metrics.py`: versioned metric values/reducers; `reports.py`: run aggregation/report schema. Use the ledger and three BT-05 hashes as inputs. | `test_metrics_reports.py`: aligned formula goldens, sample thresholds, zero denominators, irregular elapsed days, risk-free/benchmark alignment, drawdown censoring, turnover/exposure/cost units, unavailable later fields, FIFO-only lot metrics, failed-run retention, single-run insufficiency and linear p5/median/p95/worst. Acceptance: deterministic formula-versioned records with explicit status, value/reason, units and sample count; no significance or promotion claim. | Re-render from immutable ledger/artifacts with the prior report schema. Do not mutate economic history to repair a report. |

## BT-01 — Session clock and runner

### Proposed interfaces

These signatures describe intended ownership only; no Phase 03 code currently defines them. The BT-01 JIT fixes exact field bounds, reason codes and serialization before RED.

```python
SessionClock.bind(
    context: RunContext,
    bundle: EvidenceBundle,
    envelope: SignalEnvelope,
) -> SessionBinding

BacktestRunner.run(
    bindings: tuple[SessionBinding, ...],
) -> tuple[BacktestEvent, ...]
```

`SessionBinding` captures exact validated immutable production contracts and the witnessed calendar contained in the bundle. Snapshot and revalidate nested values at ingress; the runner accepts tuples of plain bounded data only, with no callback, iterable protocol, loader, provider, filesystem root, model, or arbitrary object. Validate exact run/bundle/hash, envelope/context, variant, instrument and calendar bindings. Require the BT replay witness, while leaving the optional PIT read contract unchanged.

For each binding derive the exchange-local date from the witnessed calendar and require `decision_time` to equal that exact session's close. Require `knowledge_cutoff <= decision_time`; require the context's earliest execution no earlier than the open of `calendar.next_session(local_date)`. Refuse a missing exact session, end of coverage, gap, absent witness, mismatched ID, or late availability/ingestion. Never infer weekdays, use UTC date as exchange date, or pass a `datetime` to the date-only calendar API.

Snapshot the canonical source state before reduction and verify it has not changed when the event result is sealed. Reject duplicate decision slots `(session_date, instrument_id, variant_id)` across bindings even when the bindings are identical. Reject any repeated emitted event ID even when its canonical payload is identical; conflicting reuse also rejects. Do not coalesce duplicate caller bindings or events. For accepted unique inputs, canonicalize bounded events by `(economic session/time, stage priority, instrument_id, event_id)`, then assign a contiguous sequence. Ambiguous ordering rejects. Stage priority is fixed in the design; BT-01 may emit only decision then next-session opportunity. Preserve both economic timestamp and later source availability/processing facts.

`SignalEnvelope.no_trade` yields an explicit no-trade decision and opportunity record but never authorizes a simulated action or intent. `shadow_only` must be true. BT-01 never turns a score into shares and emits no fills. An accepted next-session opportunity describes the witnessed session and a bounded outcome window only.

### RED, GREEN and refactor order

1. **RED:** Add only focused tests/fixtures for matching bundle and envelope, exact local close, cutoff equality/breach, next-session open across weekends/holidays/early close, unwitnessed calendar, missing/gapped/end coverage, non-trade and shadow flags, mismatched IDs, identical and conflicting duplicate decision slots, identical and conflicting duplicate event IDs, reordered unique-input canonicalization, source mutation, oversized input, and callback/iterator rejection. Run `python -m pytest -q tests/productionization/backtest/test_clock_events.py`; record the expected contract failures and commit/push the tests-only RED commit.
2. **GREEN:** Add only the clock, immutable binding/event types and pure runner. Output only decision and next-opportunity events. Do not add orders, fills, ledger, actions, persistence, reports, data loaders or graph edits.
3. **REFACTOR:** Centralize stable keys and exact calendar checks inside BT-01 files only. Re-run the focused test and the candidate validation floor.

**Acceptance:** Focused tests demonstrate exact witnessed-session timing, deterministic order/sequence, immutable binding, zero callbacks/egress and no BT-01 fill or sizing. Relevant PIT and SIG contract suites remain green. Disable the new runner to roll back; all source v1 bytes remain unchanged.

## BT-02 — Order, fill and cost engine

### Proposed interfaces and fields

`OrderIntent` and `Fill` first become shared contracts in `mytradingalpha/contracts/orders.py`; `SimOrder`, `OrderBook`, `Simulator` and `FillModel` remain internal. `CostModel.quote()` remains importable from `mytradingalpha.backtest.costs`. The future BT-02 JIT freezes exact names, limits, decimal scales and error codes.

The stable package facade is `mytradingalpha/backtest/costs/__init__.py`; EXC extends it without changing the existing `CostModel` import.

`OrderIntent` requires bounded stable `intent_id`, `run_id`, `instrument_id`, `decision_event_id`, `envelope_id`, and outcome source references; currency; `side`; positive finite Decimal `quantity`; `order_type`; optional `limit_price` required positive exactly for limit orders; `earliest_submit_time`; finite `expires_at`; `time_in_force`; `plan_id`, `risk_decision_id`, and `risk_policy_version`; and `execution_authority="simulation_only"`. Plan/risk references are simulation lineage only; OMS dispatch rejects this simulation-only v1 lineage, and any authority extension requires a separately versioned contract and explicit authorization. `Fill` carries stable `fill_id`, `intent_id`, actual positive quantity, all-in `price`, `reference_price`, non-negative incremental `fee`, cost breakdown and policy version, instrument/currency/source references, economic `fill_time`, later `received_at`/resolution time, and simulated provenance. Keep quantity positive; side supplies the signed quantity.

```python
CostModel.quote(
    reference_price: Decimal,
    side: Side,
    filled_quantity: Decimal,
    cumulative_quantity: Decimal,
    policy: CostPolicy,
) -> CostQuote

FillModel.simulate(
    intent: OrderIntent,
    outcome: DailyBar,
    remaining_quantity: Decimal,
    cash_available: Decimal,
    shares_available: Decimal,
    cap_remaining: Decimal,
    policy: CostPolicy,
) -> FillDecision
```

The baseline input policy contains explicit versioned constant spread bps, slippage bps, per-share commission, minimum fee, fixed-share per-instrument/session cap, lot assumption, currency, and numeric bounds. All fields are required; zero is accepted only when written explicitly. Negative, missing, non-finite, unsupported, stale or out-of-bound assumptions reject before a fill. Impact, ADV, empirical liquidity and capacity are unavailable until EXC; they cannot silently default to zero.

Use the reference session close. For `s=+1` buy and `s=-1` sell, `p_fill = P + s*P*(half_spread_bps+slippage_bps)/10000`. Attribute each friction component in total currency on actual filled shares. A limit fills only if this adverse price is marketable against the order's fixed limit; never clamp it to the limit. Baseline execution is the final close of the next eligible session only. `fill_time` is the close; `received_at` is later availability. The outcome bar is isolated from that session's earlier decision cutoff. Do not infer open, high, low, range path or same-bar permission.

For cumulative filled shares Q_after, commission rate c and order minimum m, fee due is zero at Q_after=0, else max(m,c*Q_after) rounded to USD 0.01 using ROUND_HALF_EVEN. Each fill's incremental fee is fee_due(Q_after)-fee_due(Q_before), where Q_before excludes the current fill; the minimum is charged once per order. Cash change is -signed_shares*execution_price-incremental_fee. Make affordability account for the resulting incremental fee. Bound every fill by remaining intent, cash, held shares for sells, fixed-share cap and lot. Consume cap in canonical stable intent-ID order. Zero cap means no fill. No shorting or leverage. The next verified eligible session close is the first attempt; enforce earliest_submit_time and finite expires_at at every attempt. DAY expires after its eligible-close attempt; GTC retries non-marketable or partial remainder at each subsequent verified eligible session close until expiry; IOC tries once then cancels its remainder; FOK fills the entire remaining affordable and cap-eligible quantity or none. A no-trade envelope cannot generate a new fixture intent.

### RED, GREEN, refactor and slice checks

1. **RED:** Test contract fields/strict Decimal/UTC/resource bounds; TIF including GTC retries and expiry boundaries; fixed intent before outcome; separate close fill and later receipt time; adverse buy/sell quotes; both limit directions; no limit price clipping; missing/negative/implicit-zero policy; zero cap; deterministic partial cap use; minimum fee on 2/3/5 fills; fee residual/cent rounding; cash and holdings limits; no shorts/leverage; no-trade; adjusted/provisional/wrong-source outcome rejection. Run `python -m pytest -q tests/productionization/backtest/test_fills_costs.py`; record expected failures and commit/push tests only.
2. **GREEN:** Add shared order wire contracts and the bounded offline simulator/cost facade only. Preserve the import `from mytradingalpha.backtest.costs import CostModel`. Do not add ledger runtime, NAV, corporate actions, replay storage, RSK target/risk, OMS state or broker writes.
3. **REFACTOR:** Keep public wire types in one contracts owner and internal simulator types in backtest. Verify no `tradingagents` import or scope spill; run the focused and validation floors.

**Acceptance:** Fixed inputs produce exact adverse prices, marketability, TIF outcomes, stable partials and cumulative fees; fee attribution reconciles without a second cash debit. Fills remain simulation-only and resolved only from sealed outcomes. A prior versioned policy may be selected for a new derived run; no existing policy or artifact is rewritten.


`DailyBar` must have `finality=FINAL` and `adjustment_basis=UNADJUSTED`; exact instrument, calendar, session, source and revision bindings plus outcome availability and archive ingestion cutoffs are required. Do not define a second `FinalDailyBar` contract.



## BT-03 — Append-only ledger and NAV

### Proposed interfaces

`LedgerEvent` and `LedgerBalance` are immutable internal types. No shared `PortfolioSnapshot` is introduced before RSK-01.

```python
Ledger.append(event: LedgerEvent) -> LedgerBalance
Ledger.replay(events: tuple[LedgerEvent, ...]) -> LedgerBalance
Ledger.balance() -> LedgerBalance
NAVCalculator.compute(
    balance: LedgerBalance,
    marks: tuple[EligibleMark, ...],
    policy: AccountingPolicy,
) -> NAVResult
AccountingInvariant.check(before: LedgerBalance, event: LedgerEvent, after: LedgerBalance) -> None
```

Opening cash and currency are explicit. A fill posting includes the complete validated intent/fill relationship and applies signed shares, all-in notional, incremental fee, and cumulative fee due atomically. `Ledger.append(event: LedgerEvent) -> LedgerBalance` validates the bounded event identity and canonical payload, then checks the event-ID index first. If the same ID and payload are already present, it appends nothing and returns the ledger's current `LedgerBalance`, exactly as `Ledger.balance()` does. It does not return the original event or an append receipt. The retry leaves the original event ID, sequence, payload, prefix hash, and state unchanged; retrying E1 after accepted E2 returns the balance after E2 and does not replay E1 or regress state. Reuse of an ID with changed payload conflicts. Only an unseen ID must match the exact next sequence before link, chronology, currency, arithmetic and accounting invariants are checked and state commits. Any rejection leaves state unchanged. Store/return defensive immutable data.

Long-only position and cash non-negativity are checked after every event. Reject insufficient-cash purchase and oversell. Receivable/liability creation and settlement post both sides. NAV is cash plus quantity times eligible unadjusted marks plus receivables less liabilities. Required missing, future, stale, wrong-session/instrument/currency marks return unavailable and invalidate the run; no zero or last-known-current fallback. Use a local Decimal context and explicit bounded scale/magnitude; notional and additions stay exact, only cumulative fee rounds to currency quantum. The report cannot round and mutate a ledger value.

### RED, GREEN, refactor and slice checks

1. **RED:** Test one event's cash/position delta, total NAV identity, fee once, atomic fill linkage, same-payload duplicate no-op, retry E1 after accepted E2 returning the current post-E2 balance without changing the event count, E1's original sequence/payload or prefix hash, conflicting ID, missing/reordered sequence, late/future event, defensive copies, cash/position negatives, oversell, explicit receivable and payable balance, mark coverage/currency and ambient Decimal context independence. Include failed append assertions proving the event count, prefix hash and current balance are unchanged. Run `python -m pytest -q tests/productionization/backtest/test_ledger_nav.py`; record expected failures and commit/push tests only.
2. **GREEN:** Add the minimal immutable event, append/replay/balance, NAV and accounting invariant behavior. Do not add action reducers or benchmark policies (BT-04) or persistence/checkpoints (BT-05).
3. **REFACTOR:** Keep append validation before state change and all arithmetic under explicit local policy. Replay every focused fixture from the opening balance and compare exact state.

**Acceptance:** Same inputs replay to the same event prefix, balances and NAV; retrying an identical event preserves its original sequence and prefix and returns the current balance; conflicting or invalid events leave state untouched. A damaged run stops at and retains its last valid prefix. Rollback replays that prefix into a new artifact and never edits/deletes history.


## BT-04 — Actions and benchmarks

### Proposed interfaces

```python
CorporateActionReducer.apply_opening_actions(
    balance: LedgerBalance,
    actions: tuple[AvailableCorporateAction, ...],
    session: TradingSession,
    policy: ActionPolicy,
) -> tuple[LedgerEvent, ...]

BenchmarkRunner.run_cash(..., policy: CashBenchmarkPolicy) -> BenchmarkSeries
BenchmarkRunner.run_buy_and_hold(..., policy: BuyAndHoldPolicy) -> BenchmarkSeries
```

Consume existing PIT action records without rewriting them. Select only the revision available at its effective application boundary and archive cutoff. Late evidence invalidates the run or requires a fresh manifest. Reject provider-adjusted prices when explicit actions are applied. Fix tie order as split, stable-ID identity update, dividend entitlement before any session trade. Apply exact split ratio and inverse per-share basis/mark; cancel existing pre-split intents with reason. Keep fractions exactly or require predeclared/evidenced cash-in-lieu. Dividend eligibility is opening holdings after the same-day split rule, before any fill. The declared amount is per post-split share; a pre-split or ambiguous source basis requires an evidenced conversion or the action is unavailable, never an assumed multiplier. Accrue once; pay by transfer from receivable to cash on pay date or a versioned next witnessed session when the pay date is closed, never earlier. Alias changes retain instrument ID and have no cash effect. Missing merger conversion evidence fails unavailable. Delisting cancels residual orders and requires versioned evidence for proceeds or explicit writeoff; never guess from last mark.

Cash and B&H have their own reducer, event stream, and NAV. Both use strategy initial capital, calendar, currency, cost and action policies. Cash earns zero unless an explicit evidenced rate is configured. B&H records the initial instruments/weights, entry session, lot and residual cash, does not rebalance, and holds cash dividends without reinvestment by default. Do not select only survivors or reuse the strategy ledger as a benchmark.

### RED, GREEN, refactor and slice checks

1. **RED:** Add fixtures for same-day split/dividend ordering and ambiguous pre/post-split dividend amount basis unavailable; revision available late; archive ingestion cutoff; adjusted close plus action; split ratio and NAV; existing intent cancellation; exact fraction and evidenced cash-in-lieu; entitlement before same-day trade; duplicate dividend accrual/payment; non-session pay date and no early cash; stable ticker alias; distinct-ID merger absent/present evidence; delisting absent settlement, explicit settlement and writeoff; Cash/B&H independent ledgers, initial cost, cash dividend, no rebalance, missing/delisted member. Run `python -m pytest -q tests/productionization/backtest/test_actions_benchmarks.py`; record expected failures and commit/push tests only.
2. **GREEN:** Add the BT-04 opening-action, settlement, and two independent benchmark reducers. Do not modify PIT action types, backtest fills/ledger ownership, or turn benchmark output into portfolio alpha.
3. **REFACTOR:** Centralize fixed action tie order and versioned settlement choice. Replay strategy and benchmark streams independently; check their cash/position/NAV invariants.

**Acceptance:** Action events are available at the declared effective boundary, reconcile the ledger, and fail closed for missing evidence. Cash/B&H assumptions are explicit and deterministic. Rollback replays a prior action/benchmark policy into a new artifact without mutating existing results.


## BT-05 — Manifest, semantic hashes and checkpoints

### Proposed interfaces

```python
ReplayManifest.semantic_input_hash() -> str
ReplayManifest.economic_output_hash(events: tuple[LedgerEvent, ...], results: tuple[object, ...]) -> str
ReplayManifest.artifact_integrity_hash() -> str
ReplayRunner.resume(manifest: ReplayManifest, checkpoint: ReplayCheckpoint, events: tuple[LedgerEvent, ...]) -> ReplayResult
```

The manifest's semantic input contains exact typed bundle/outcome source content projections, policies/witnesses, universe and instrument IDs, variant and full signal semantic content, model/config/code/schema versions, numerical/fill/cost/action/benchmark versions, initial capital, eligible sessions and seed. It binds exact original v1 source bytes, content hashes and IDs separately as integrity provenance; never rewrite source IDs or sealed bytes.

Maintain three independent domain-prefixed SHA-256 hashes: semantic input, economic output, and exact artifact integrity. The semantic projections are explicit, typed and versioned allowlists. Only each contract's declared run/correlation IDs, wall-clock operational timestamps, and derived run-dependent IDs/hash fields can be omitted. Exclude nested SIG-05 run-derived hashes only inside the known SIG schema and recompute all projected IDs/references. Keep decision/cutoff/availability/ingestion/publication/event/effective/payment/fill times, order and ledger sequence, and semantic `created_at`; specifically SIG-05 `created_at` is decision time and is economic. Preserve model/config/code versions and source/output economic content. Do not use generic recursive key stripping or pull a run-dependent exact integrity reference back into an economic payload.

`economic_output_hash` is domain-separated over `semantic_input_hash` and the typed projected economic events/results. A changed material policy, model, code, seed or source therefore changes the output identity even when the numeric results coincide.

Reject unknown schema/fields, cycles, duplicate JSON keys, NaN/infinity, custom objects, mutation, unbounded structures and oversize bytes before serialization/hash. Serialize bounded UTF-8 canonical JSON with sorted map keys, original economic event order, exact Decimal strings with documented normalization, and UTC times. The JIT fixes byte/item/depth/magnitude/scale bounds, Decimal/root/power versions and all domain/hash/version prefixes before RED.

The checkpoint binds both semantic and exact inputs; event prefix count and hash; next runner cursor; open intents; cumulative order fees; remaining cap; action entitlements/payables; Cash/B&H state; and reducer/schema versions. Events are authoritative. On resume verify all manifest and prefix values, replay/reconcile the checkpoint, then process exactly the next unapplied event. A crash before atomic fill append commits no half-fill. A crash after append but before checkpoint is idempotently replayed once. Torn record, changed input, unknown version, conflicting event, sequence/hash mismatch or checkpoint disagreement stops with evidence retained.

One explicit local append owner writes canonical immutable artifacts atomically only below an explicit caller-supplied root. Reject path escape, symlinks, overwriting an existing artifact and concurrent writers. No environment/credential discovery, network, subprocess, model or provider is allowed. A changed semantic input creates a new artifact. A recovered unchanged run must have the same economic output hash and exact economic events/results as uninterrupted execution; exact artifact integrity may differ when run/operational provenance differs.

### RED, GREEN, refactor and slice checks

1. **RED:** Test hash-domain separation, typed projections, different run IDs/operational times, retained economic time, SIG-05 source IDs, exact bytes, recomputed projected refs, changed data/cutoff/fee/config/code/seed including equal numeric outcomes, and output-hash binding to semantic_input_hash, unknown fields/version, nested unknown values, custom object/cycle/NaN/duplicate JSON/size/depth bounds, canonical Decimal/UTC, prefix digest and cursor, each crash point, changed manifest, torn event, conflicting ID, checkpoint disagreement, symlink/path traversal/overwrite and second writer. Run `python -m pytest -q tests/productionization/backtest/test_replay_hash.py`; record expected failures and commit/push tests only.
2. **GREEN:** Add only the manifest/projection/hash and explicit-root local immutable checkpoint/resume path. Keep graph checkpoints untouched. Do not add a database, hosted storage, scheduler, network, generic serializer/filter, or metric policy.
3. **REFACTOR:** Keep integrity and economic projections separate; mutation/validation runs before canonical output. Compare uninterrupted and every recoverable crash path against the same golden economic output.

**Acceptance:** Identical semantic inputs with different run IDs have equal semantic/economic hashes and distinct exact artifacts; every economic or policy change invalidates the required hash; unchanged resume exactly matches uninterrupted economics. Every malformed, changed or conflicting prefix stops without overwriting source or hiding the failure. Rollback retains all manifests/events and stops resume until a new valid artifact is produced.

## BT-06 — Metric formulas and golden report

### Proposed report contract

Each metric record is `{status: available|unavailable, value: Decimal|null, reason: stable code|null, units, formula_version, sample_count}`. Reject NaN/infinity and do not encode missing or undefined values as zero. Formula, annualization, Decimal/root/power precision, final serialization quantum and unavailable reason table are frozen in this BT-06 JIT before RED.

For positive, aligned, unflowed end-session NAV `V_0…V_n`, `r_i=V_i/V_(i-1)-1`; cumulative return is `V_n/V_0-1`; session-annualized return is `(V_n/V_0)^(A/n)-1` with explicit annual sessions `A` (252 is a declared assumption); calendar CAGR is `(V_n/V_0)^(365.25/D)-1` with actual positive UTC elapsed days `D`. Do not call session-annualized return calendar CAGR. Sample volatility is `sqrt(A)*sqrt(Σ(r_i−mean(r))²/(n−1))`. With aligned `rf_i`, `e_i=r_i−rf_i`; Sharpe is `sqrt(A)*mean(e)/sample_sd(e)`; Sortino is `sqrt(A)*mean(e)/sqrt(Σ(min(e_i,0)²)/n)`; Calmar is calendar CAGR divided by positive MDD. If actual elapsed-day CAGR is unavailable or MDD is not positive, Calmar is unavailable; any other undefined or zero denominator is unavailable.

Drawdown is `1−V_i/max(V_0…V_i)`; MDD is its maximum; duration counts consecutive unrecovered sessions and flags a terminal censored period. Given aligned benchmark returns `b_i`, active return is `r_i−b_i`; tracking error is `sqrt(A)*sample_sd(r−b)`; IR is `sqrt(A)*mean(r−b)/sample_sd(r−b)`; beta is `sample_cov(r−rf,b−rf)/sample_var(b−rf)`; descriptive arithmetic annual Jensen alpha is `A*(mean(r−rf)−beta*mean(b−rf))`. Require at least two observations, positive benchmark variance for beta, and identical currency/calendar/cost/net policy. Do not claim significance. Relative drawdown uses wealth `(V_i/V_0)/(B_i/B_0)`.

One-way session turnover is `Σ(abs(q_filled)*reference_price)/(2*opening_NAV)` including initial purchases; annualized turnover is `A*mean(session turnover)` across every eligible session. Gross exposure is `Σ(abs(q)*mark)/NAV`, net exposure is `Σ(q*mark)/NAV`, cash weight is `cash/NAV`, with long-only leverage and max instrument concentration explicit. Spread/slippage totals and explicit fees use actual fills. Impact, ADV and capacity stay unavailable. Shortfall includes fee once. Gross performance exists only as a same-fill-schedule reference-price/zero-fee counterfactual; otherwise unavailable. Do not adjust daily return by adding costs back. Distinguish fill count from closed round-trip lots; FIFO is required for hit rate/holding period or those metrics are unavailable. Simulation intent/fill counts do not imply risk rejects or broker ACKs.

For each metric, aggregate only comparable valid values by sorted linear quantile `h=(m−1)p`, interpolate between floor/ceil; `p=.05,.5,.95`. Report valid count `m`, total count, failed IDs and stable reasons, cohort identity and direction-aware worst. Never silently drop or label failed/incomparable runs as EXP qualification. With one valid run, distribution sufficiency is unavailable. Capacity/ADV/impact/sector without PIT classification/DSR/PBO/confidence/validated alpha/promotion remain unavailable until EXC/RSK/EXP/OMS/FWD owners provide evidence.


Aggregate a cohort only when variant, universe, calendar, currency, evaluation start/end sessions, initial capital, underlying PIT/source lineage, model/config/code versions, cost/action/benchmark policies, numeric policy and formula versions match. Seeds and run realization IDs may vary for descriptive distributions, but every run retains its own manifest and seed. Preserve every failed or incomparable run and its reason. BT-06 aggregation does not prove EXP preregistration or seed sufficiency and does not infer model-capture provenance.

The BT-06 RED fixtures compare same-cohort runs with different declared seeds/run IDs and change each comparability field in turn; mismatches remain visible with stable reasons and are excluded from the comparable distribution. Failed runs remain in the report's total cohort record.

### RED, GREEN, refactor and integrated gate

1. **RED:** Add goldens for aligned returns; session versus elapsed-day annualization; sample variance; Sharpe, Sortino, Calmar, MDD and censored duration; active return/TE/IR/beta/arithmetic alpha; relative drawdown; initial-purchase turnover; gross/net exposure/concentration/cash weight; cost/shortfall once; FIFO lot metrics or stable unavailability; n=0/1, zero denominator/benchmark variance, missing mark/risk-free/benchmark, wrong currency/calendar/policy, non-finite inputs, partial failed cohorts, single valid run, linear p5/median/p95 and worst direction. Verify unavailable future fields never serialize as `0`, NaN or infinity. Run `python -m pytest -q tests/productionization/backtest/test_metrics_reports.py`; record expected failures and commit/push tests only.
2. **GREEN:** Add deterministic formula-versioned reducers and report schema only. Do not change ledger arithmetic, rerun a strategy at free fills, add DSR/PBO/promotion thresholds, or claim validated alpha.
3. **REFACTOR:** Centralize numeric policy and stable unavailable reasons; report formulas beside golden inputs/expected values. Compare reports to immutable ledger and manifest hashes.
4. **Integrated fixture:** Include two instruments, holiday/early close, no-trade, precommitted next-session-close intent, both limit outcomes, 2/3/5 partials, fees/minimum/cap, atomic ledger/NAV, split + dividend entitlement/payment with declared post-split share basis, alias + missing and evidenced delisting settlement, separate Cash/B&H, uninterrupted and crash/resume paths, same economics/different run IDs, changed semantic input invalidation, formula goldens and explicit later-phase unavailability.

**Acceptance:** Every available value matches its pinned golden under the fixed Decimal policy. Every unsupported/unaligned case is unavailable with a stable reason; failed/incomparable runs remain visible; no report field claims validated alpha, measured capacity, significance or promotion. Phase gate passes only when all BT-01 through BT-06 PRs are merged in dependency order and their exact-head review, required CI and integrated checks pass. Missing evidence is `insufficient_evidence`; synthetic fixtures alone are not market evidence.

## Phase 03 validation floor and gate

These commands are required on each BT candidate as applicable to its changed boundary. The assigned JIT may add focused tests, not remove any relevant regression or safety gate.

```bash
python -m pytest -q tests/productionization/backtest/test_<owned_slice>.py
python -m pytest -q tests/productionization/data tests/productionization/quant
python -m pytest -q tests/productionization
python -m pytest -q
ruff check .
python scripts/check_dependency_direction.py
python scripts/check_agent_harness.py
python scripts/check_markdown_contracts.py
python scripts/check_lock_consistency.py
git diff --check
```

Also run applicable production package/import smoke and a clean installed-origin smoke, all five locked Python 3.10–3.14 CI test jobs, Ruff, CodeQL and Dependency Review. Do not claim a skipped optional integration as passed. Record interpreter, exact candidate SHA, commands, exit status, outputs, CI run identity and skipped tests. Each later commit makes earlier exact-head review and CI stale.

The phase gate is pass, fail, or insufficient_evidence, never inferred from a plan or synthetic run. It requires all six separately merged slices, complete exact-head reviews and CI, and successful required golden runs. Expected negative-case rejections and documented later-phase unavailable metrics must pass their assertions and do not themselves block software acceptance. An unexpected failure in a required successful golden run or failed required check blocks; missing artifacts/checks are insufficient_evidence. Failed or incomparable experiment runs remain visible and block EXP qualification. Even a phase pass remains software acceptance only; historical source authenticity, alpha, risk qualification, paper/live approval and Phase 04+ implementation are separate gates. Rollback preserves immutable bundles, decisions, event prefixes, manifests and failed artifacts; choose an older version to create a new derived result, never rewrite the old one.

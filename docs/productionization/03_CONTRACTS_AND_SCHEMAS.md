# Contracts and Schemas

The Pydantic-style sketches below describe target field semantics, not drop-in implementations or the current wire schema. Introduce each future contract only at its first-use slice. Existing implemented types and approved amendments take precedence; JSON/YAML examples illustrate shape only. Exact names and invariants are stable across historical, paper, and live modes. All timestamps are timezone-aware UTC ISO-8601 strings; all decimals are serialized as strings or fixed-precision decimal values at the API boundary.

## Implemented contract index

The current Foundation contracts are in `mytradingalpha/contracts/common.py`, `versions.py` and
`schemas.py`; they enforce strict UTC/decimal/ID/schema and component-scoped egress rules.
PIT-06 uses the **typed-domain v1** EvidenceBundle in `mytradingalpha/data/bundle.py`, not the generic
Observation-list sketch below. Domain records, provenance, calendar/universe manifests and canonical
hashes are authoritative in that implementation. SIG-01 uses the separate closed response contract
in `mytradingalpha/research/cached_response.py` and its [approved amendment](phases/02-evidence-agent-boundary/SIG_01_AMENDMENT_PROPOSAL.md).
Do not relocate existing types or regenerate sealed v1 bytes to match a sketch. Current runnable
checks are indexed in [Appendix B](appendices/B_TEST_MATRIX.md#implemented-productionization-checks).

## First-use wire ownership

These are delivery assignments, not a claim that future classes already exist. Wire definitions
have one owner under contracts; algorithms, aggregates and persistence stay in their bounded contexts.
The existing PIT/SIG-01 domain contracts retain their approved locations and public imports.

| Contract | First-use PR | Planned owner / consuming behavior |
| --- | --- | --- |
| ResearchNote | SIG-02 | `mytradingalpha/contracts/research.py`; research notes builder consumes it |
| QuantSignal | SIG-03 | `mytradingalpha/contracts/signals.py`; quant owns feature/scoring algorithms |
| LLMOverlay | SIG-04 | `mytradingalpha/contracts/signals.py`; research owns bounded overlay validation |
| SignalEnvelope | SIG-05 | `mytradingalpha/contracts/signals.py`; quant combines signals and owns VariantRegistry |
| OrderIntent / Fill | BT-02 | `mytradingalpha/contracts/orders.py`; simulator consumes these, SimOrder stays internal |
| PortfolioSnapshot / TargetPortfolio | RSK-01 | `mytradingalpha/contracts/portfolio.py`; portfolio owns allocation and snapshot access |
| RiskDecision | RSK-04 | `mytradingalpha/contracts/risk.py`; deterministic risk engine owns decisions |
| ExperimentSpec | EXP-01 | `mytradingalpha/contracts/experiments.py`; ExperimentRegistry references existing VariantRegistry IDs |
| OrderEvent | OMS-01 | `mytradingalpha/contracts/orders.py`; execution owns aggregate/event application |

BT-01 simulator events and BT-03 internal ledger snapshots are not prematurely implemented OMS or RSK wire models. BT-02 fixtures may use
explicit simulation-only plan/risk lineage; this cannot authorize dispatch or require RSK/OMS code
before its slice. EXC extends the BT-02 `mytradingalpha.backtest.costs` package facade without breaking
its public CostModel import. No later slice introduces a second VariantRegistry: EXP registers trial
specifications and references SIG-05 variant identities. Each first-use JIT fixes exact fields,
validation, serialization and public exports; do not create these future files during remediation.

## Shared types and time rule

```python
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field

Mode = Literal["historical", "forward_paper", "live_pilot"]
OrderStatus = Literal["proposed", "validated", "approved", "submitting", "submitted", "acknowledged", "partial", "filled", "cancelled", "rejected", "expired", "unknown"]

class NetworkPolicy(BaseModel):
    data_capture_egress: bool = False
    model_provider_egress: bool = False
    research_tool_egress: bool = False
    paper_broker_egress: bool = False
    live_broker_egress: bool = False

class RunContext(BaseModel):
    run_id: str
    mode: Mode
    variant_id: str
    decision_time: datetime
    knowledge_cutoff: datetime
    earliest_execution_time: datetime
    bundle_id: str
    bundle_hash: str
    calendar_id: str
    base_currency: str = "USD"
    network_policy: NetworkPolicy

class Instrument(BaseModel):
    instrument_id: str
    symbol: str
    asset_class: Literal["equity", "etf"]
    currency: str
    exchange: str
    active_from: datetime
    active_to: datetime | None = None
    lot_size: int = Field(ge=1)

class Observation(BaseModel):
    observation_id: str
    instrument_id: str | None = None
    field: str
    value: Decimal | str | bool | None
    event_time: datetime
    published_at: datetime | None = None
    available_at: datetime
    ingested_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    revision: int = Field(ge=0)
    source: str
    source_locator: str
    quality: Literal["usable", "degraded", "invalid"]

class EvidenceBundle(BaseModel):
    bundle_id: str
    bundle_hash: str
    created_at: datetime
    knowledge_cutoff: datetime
    observations: list[Observation]
    source_manifest: dict[str, str]
    universe_hash: str
    calendar_hash: str
    dataset_hash: str
    config_hash: str
    code_hash: str
    replay_policy: Literal["availability", "archive_realistic"]
    immutable: bool = True

class ResearchNote(BaseModel):
    note_id: str
    run_id: str
    instrument_id: str
    thesis: str
    risks: list[str]
    evidence_ids: list[str]
    source_agent: str
    generated_at: datetime
    model_id: str | None = None
    confidence_label: Literal["low", "medium", "high"] | None = None

class QuantSignal(BaseModel):
    signal_id: str
    run_id: str
    instrument_id: str
    score: Decimal
    expected_return: Decimal | None = None
    horizon_sessions: int = Field(ge=1)
    feature_ids: list[str]
    as_of: datetime
    model_version: str
    model_hash: str
    feature_hash: str
    uncertainty: Decimal | None = None
    training_start: datetime | None = None
    training_end: datetime | None = None
    valid_until: datetime | None = None
    status: Literal["valid", "degraded", "invalid"]

class LLMOverlay(BaseModel):
    overlay_id: str
    run_id: str
    bundle_id: str
    quant_signal_id: str
    instrument_id: str
    action: Literal["attenuate", "veto"] | None = None
    abstain: bool = False
    multiplier: Decimal = Field(ge=0, le=1)
    evidence_ids: list[str]
    rationale: str
    model_id: str
    generated_at: datetime
    schema_version: str

class SignalEnvelope(BaseModel):
    envelope_id: str
    quant: QuantSignal
    overlay: LLMOverlay | None = None
    effective_score: Decimal
    effective_action: Literal["eligible", "attenuated", "vetoed", "abstain"]
    reason_codes: list[str]
    created_at: datetime

class PortfolioSnapshot(BaseModel):
    snapshot_id: str
    run_id: str
    as_of: datetime
    cash: Decimal
    positions: dict[str, Decimal]
    mark_prices: dict[str, Decimal]
    receivables: Decimal
    liabilities: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    nav: Decimal
    ledger_sequence: int = Field(ge=0)

class TargetPortfolio(BaseModel):
    target_id: str
    run_id: str
    effective_time: datetime
    weights: dict[str, Decimal]
    cash_weight: Decimal
    rationale_ids: list[str]
    allocator_version: str

class RiskDecision(BaseModel):
    decision_id: str
    run_id: str
    target_id: str
    decision: Literal["approved", "resize", "rejected", "halted"]
    allowed_weights: dict[str, Decimal]
    reason_codes: list[str]
    evaluated_at: datetime
    policy_version: str
    persistent_halt: bool = False
    revalidation_required: bool = False
    prior_decision_id: str | None = None

class OrderIntent(BaseModel):
    intent_id: str
    run_id: str
    instrument_id: str
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0)
    order_type: Literal["market", "limit"]
    limit_price: Decimal | None = None
    earliest_submit_time: datetime
    risk_decision_id: str
    plan_id: str
    risk_policy_version: str
    client_order_id: str
    expires_at: datetime
    time_in_force: Literal["day", "gtc", "ioc", "fok"]

class OrderEvent(BaseModel):
    event_id: str
    intent_id: str
    status: OrderStatus
    event_time: datetime
    ingested_at: datetime
    broker_order_id: str | None = None
    broker_event_id: str | None = None
    reason_code: str | None = None
    raw_reference: str | None = None
    raw_hash: str | None = None
class Fill(BaseModel):
    fill_id: str
    intent_id: str
    broker_order_id: str | None = None
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    fill_time: datetime
    received_at: datetime
    cost_breakdown: dict[str, Decimal]
    liquidity: Literal["maker", "taker", "simulated", "unknown"]

class Reconciliation(BaseModel):
    reconciliation_id: str
    as_of: datetime
    local_ledger_sequence: int = Field(ge=0)
    broker_snapshot_hash: str
    cash_delta: Decimal
    position_deltas: dict[str, Decimal]
    open_order_deltas: list[str]
    status: Literal["matched", "investigate", "halted"]
    reason_codes: list[str]

class ExperimentSpec(BaseModel):
    experiment_id: str
    variants: list[str] = Field(min_length=1)
    universe_id: str
    data_snapshot: str
    split_policy: str
    windows: list[dict[str, str]]
    purge_sessions: int = Field(ge=0)
    embargo_sessions: int = Field(ge=0)
    seeds: list[int] = Field(min_length=1)
    metrics: list[str]
    costs_policy: str
    model_hash: str
    prompt_hash: str
    tool_hash: str
    cost_hash: str
    risk_hash: str
    selection_rule: str
    preregistered_at: datetime
    sealed_holdout_state: Literal["sealed", "opened_read_only", "contaminated", "new_required"] = "sealed"

class GateEvidence(BaseModel):
    gate_id: str
    subject: str
    status: Literal["pass", "fail", "insufficient_evidence"]
    evidence_uris: list[str]
    metrics: dict[str, Decimal | str]
    reviewer: str
    recorded_at: datetime
    rollback_plan: str
```

The worker may split these classes into modules, but field meaning and validation must remain compatible. String decimals avoid binary float surprises in persisted accounting; conversion to `Decimal` happens before validation.

`Instrument.instrument_id` is always required and stable. `Observation.instrument_id` is optional only for macro/global observations; instrument-level rows must carry it. `EvidenceBundle` hashes cover the universe, calendar, dataset, config, and code manifests. `RunContext.variant_id` identifies the variant for one run, while `ExperimentSpec.variants` enumerates the preregistered comparison set and does not duplicate a per-run field. `OrderIntent` carries the plan and risk-policy lineage, expiry, and time-in-force; `OrderEvent` carries broker event ingestion and raw-payload identity; `Fill.price` contains execution-price friction and `Fill.fee` is the incremental explicit cash fee; `Fill.cost_breakdown` is attribution only, not another cash debit. `sealed_holdout_state=opened_read_only` allows audit replay only; any tuning/model/metric/seed change makes the holdout contaminated and requires a new experiment.

## JSON example

```json
{
  "run_id": "run-2026-01-15-AAPL-001",
  "mode": "historical",
  "variant_id": "quant_only_v1",
  "decision_time": "2026-01-15T21:00:00Z",
  "knowledge_cutoff": "2026-01-15T21:00:00Z",
  "earliest_execution_time": "2026-01-16T14:30:00Z",
  "bundle_id": "bundle-2026-01-15-001",
  "bundle_hash": "sha256:replace-with-content-hash",
  "calendar_id": "XNYS-regular-v1",
  "network_policy": {
    "data_capture_egress": false,
    "model_provider_egress": false,
    "research_tool_egress": false,
    "paper_broker_egress": false,
    "live_broker_egress": false
  }
}
```

The hash value above is a shape example only; it is not a credential or a claim of an existing artifact.

## YAML configuration shape

```yaml
run:
  mode: historical
  variant_id: quant_only_v1
  network_policy:
    data_capture_egress: false
    model_provider_egress: false
    research_tool_egress: false
    paper_broker_egress: false
    live_broker_egress: false
  replay_policy: archive_realistic
  base_currency: USD
portfolio:
  allocator: rule_v1
  long_only: true
  leverage: 1.0
risk:
  fail_closed: true
  persistent_halt_store: sqlite_or_durable_store
execution:
  live_write_enabled: false
  unknown_ack_policy: pause_and_query
```

Examples contain no live credentials, fixed live risk limits, or broker identifiers.

## Invariants

1. **Time:** `knowledge_cutoff <= decision_time < earliest_execution_time`. Every observation satisfies `available_at <= knowledge_cutoff`; archive-realistic replay also requires `ingested_at <= knowledge_cutoff`. If `published_at` is absent, the policy must explicitly reject or classify the item as unavailable.
2. **Network policy:** Historical mode sets every `NetworkPolicy` field false and reads only sealed evidence plus separately sealed, exact-bound cached responses. Forward paper may enable `data_capture_egress`, approved `model_provider_egress`, and approved `paper_broker_egress`; `research_tool_egress` remains false and `live_broker_egress` remains false. Live pilot enables only the explicitly approved components.
3. **Immutability:** `EvidenceBundle` is content-addressed, immutable after sealing, and records event, publication, availability, ingestion, validity interval, revision, and replay policy. A later revision is a new observation, not an in-place edit.
4. **Signal authority:** `QuantSignal` is numeric and deterministic for a fixed bundle/config/model artifact. `LLMOverlay` is optional; when present it has only attenuate/veto plus an explicit abstain flag. `multiplier` is in [0,1], veto requires multiplier 0, and abstain always means no trade. No overlay field represents a target weight or order. Overlay failure is no trade; Quant-only is a separate preregistered variant.
5. **Portfolio:** `TargetPortfolio` is long-only, has non-negative asset weights, explicit cash weight, and total weight equal to 1 within configured decimal tolerance. Allocator output is not executable until `RiskDecision=approved`.
6. **Risk:** Risk checks are deterministic and independent of LLM output. Any missing price, invalid constraint, stale snapshot, hard-limit violation, or active persistent halt yields rejected/halted, never approval. A resize decision must produce a new constrained target and revalidate before an intent is approved; revalidation references the prior decision ID.
7. **Accounting:** `NAV = cash + sum(quantity * mark_price) + receivables - liabilities` after applying fills and corporate actions. A fee is posted exactly once as a cash ledger event and is not subtracted again in mark-to-market NAV. Return reports identify gross and net costs separately.
8. **OMS:** Valid transitions include `proposed -> validated -> approved -> submitting -> submitted -> acknowledged/rejected/expired/unknown`; `acknowledged -> filled/partial/cancelled/rejected/expired`; `partial -> partial/filled/cancelled/rejected/expired`. Risk validation and approval precede submission. Paper endpoint writes are permitted only after Phase 07 approval; live broker writes remain disabled until Phase 09. Unknown acknowledgement pauses and queries; it never blindly resubmits.
9. **Identity:** `intent_id`, `client_order_id`, broker order ID, and fill ID are stable and idempotent. Duplicate events are ignored by event ID; conflicting duplicates halt reconciliation.
10. **Reconciliation:** Local cash, positions, open orders, fills, and broker snapshot hash are compared. Any unexplained delta creates `investigate` or `halted` evidence before further writes.
11. **Experiment/gates:** Variant, seeds, data snapshot, split policy, costs policy, and sealed-holdout status are immutable once an experiment starts. Mandatory gates use `pass`, `fail`, or `insufficient_evidence`; there is no waiver path for live promotion.

## OMS transition table

The wire enum uses stable lowercase values; this table shows the business labels used in reviews. Risk validation and approval are deliberately visible before any submission state.

| Current | Allowed next state | Rule |
| --- | --- | --- |
| Proposed | Validated | Intent shape, expiry, TIF, plan, and policy are valid. |
| Validated | Approved, Rejected, Expired | `RiskDecision` and all deterministic constraints pass before approval. |
| Approved | Submitting, Rejected, Expired | Human/paper approval and scope checks pass. |
| Submitting | Submitted, Rejected, Expired, Unknown | A request is sent only to the approved PAPER/live endpoint for the mode. |
| Submitted | Acknowledged, Rejected, Expired, Unknown | Unknown acknowledgement pauses and starts query-only recovery. |
| Acknowledged | Filled, Partial, Cancelled, Rejected, Expired | Broker/PAPER event is accepted by ID and sequence. |
| Partial | Partial, Filled, Cancelled, Rejected, Expired | Distinct fill events advance cumulative_filled; remaining quantity is tracked, never invented. |
| Unknown | Acknowledged, Partial, Filled, Cancelled, Rejected, Expired | Only an observed query/reconciliation result can resolve uncertainty; never blindly resubmit. |

## OMS event application and observed facts

A repeated status is not a repeated event. The same event ID and identical payload is idempotent;
the same ID with a different payload halts processing for reconciliation. Distinct fills of 2, 3
and 5 shares on a 10-share order must produce Acknowledged -> Partial -> Partial -> Filled.
`cumulative_filled` is monotonic, never exceeds original quantity, and equals original quantity
before Filled; expiry/cancellation closes only the remaining quantity. Atomically apply each unique
fill and its incremental cash/fee entries once. Retain late/out-of-order broker facts with their raw
identity; reconcile authoritative cumulative state rather than dropping facts because a local ACK
was delayed. An unsupported transition or conflicting quantity stops dispatch and enters investigation;
it is not permission to fabricate an ACK or blindly resubmit. Broker-specific normalization and
late-fill/cancel races require explicit OMS adapter tests before external PAPER operation.

## Fill accounting units and fee-once rule

For equity/ETF fixtures, `signed_quantity` is shares (positive buy, negative sell), `execution_price`
and `reference_price` are currency/share, and `explicit_fee` is non-negative currency for this fill.
`Fill.quantity` remains a positive magnitude; side supplies the sign. Validate finite Decimal values,
positive price/quantity magnitude and valid currency before using these equations. Any future FX or
multiplier instrument requires an explicit extended contract, not accidental reuse of these units.

<!-- accounting-equations -->
```python
def fill_cash_delta(signed_quantity, execution_price, explicit_fee):
    return -signed_quantity * execution_price - explicit_fee


def implementation_shortfall(signed_quantity, execution_price, reference_price, explicit_fee):
    return signed_quantity * (execution_price - reference_price) + explicit_fee
```

Execution price already includes side-signed half-spread, slippage and per-share impact. Multiply
per-share components by actual filled magnitude only for total-currency attribution. Do not debit
that attribution or implementation_shortfall again. Post all-in notional and incremental explicit
fees atomically by fill/event ID; NAV reads the resulting cash without another fee subtraction.
For 10 shares at 100.6 versus reference 100 with fee 1, cash changes by -1007 and marked loss is 7.
For a sale of 10 at 99.4 with fee 1, cash changes by 993 and shortfall is also 7. Favorable real
execution may have negative price shortfall; it is not an invalid negative commission.

Version `fee_policy_id` and the cumulative fee allocation rule. Incremental explicit fees are
cumulative fee due after the fill minus fees already posted; do not charge the order minimum anew
for every partial fill. A 2/3/5 allocation with fees .2/.3/.5 must total 1 and reproduce the same
-1007 cash delta. Rounding/residual allocation and fee corrections must be deterministic and append-only.
A real rebate needs an explicitly modeled adjustment, not silent mutation of a sealed non-negative fee.
Determine remaining participation/capacity before quoting impact; consume capacity across fills and
never divide by zero or manufacture a fill when residual capacity is zero.

## Closed response capture and replay handoff

**Correction, 2026-09-05:** the [SIG-01 amendment approved for PR #24](phases/02-evidence-agent-boundary/SIG_01_AMENDMENT_PROPOSAL.md)
and implemented v1 validators govern this section. The earlier handoff text incorrectly applied
an ingestion cutoff to every response policy. Both policies require `available_at <= knowledge_cutoff`;
only archive-realistic replay additionally requires `ingested_at <= knowledge_cutoff`. Availability-only
backfilled research may ingest an already-available response later, but is not archive-realistic
operational evidence. It never permits labeling newly generated inference as historically available.
The response's input bundle, cutoff, calendar, variant, instrument, graph/model/runtime IDs and hashes
are exact bindings. Responses are separate canonical records, not fields added to EvidenceBundle v1.
A correct content hash proves integrity, not source authenticity or historical availability; producer
provenance still needs independent source evidence. PIT filtering does not eliminate LLM
training-knowledge leakage. No code, stored bytes, UTC trade-date rule, or approved cutoff changes here.

SIG-02 is a pure evidence/cached-state-to-note transformation with **no new inference**, provider
call, capture service, arbitrary runner or historical fallback. EXP-02 consumes existing independently
verified captures for model-bearing variants; each declared inference trial/seed needs a distinct
captured response and execution identity. Replaying one cache 30 times is determinism evidence, not
30 model trials. Cash, buy-and-hold, deterministic trend and Quant-only do not require model responses.
Missing qualified model trials yield insufficient_evidence; never fabricate complete alpha evidence.

FWD-01 owns the later controlled producer within its authorized capture scope. One archive-realistic
v1-compatible schedule freezes pre-close inputs at preregistered `input_freeze_time`, seals the exact bundle,
then requires the response to be genuinely available and ingested by the fixed close-time cutoff. The
current closing bar cannot enter those pre-close inputs. Record input freeze, request, completion,
availability, ingestion, distinct execution/seed and all artifact bindings in the capture manifest;
never backdate a response or move the deadline after observing latency. A t+5s response is unavailable
at cutoff t. Late/error/missing responses remain no-trade; historical replay never contacts a model.

This assigns a producer, not an early dependency or authorization to run FWD before EXP/OMS software
prerequisites. Earlier EXP software tests use fixtures; actual experiment promotion needs existing
qualified captures or later separately authorized collection. Preparatory capture cannot dispatch
orders. A different decision/capture clock or derived-artifact contract requires a separate approved
amendment and version/migration plan; this clarification does not approve such a redesign. No existing
bundle/response v1 bytes, strict cutoffs, UTC trade-date rule or human PAPER/live gates are relaxed.

### Executable response-policy examples

These synthetic cases describe response eligibility, not a new wire schema or real capture evidence.
`tests/productionization/test_closed_replay_documentation.py` combines these timestamps with the existing
synthetic response fixture and checks the real v1 sealer/parser. All other intrinsic fields are valid;
full bundle/context/artifact binding is tested separately by the research suite. Late ingestion alone
is permitted only by the availability policy; late availability fails both. The historical validator
accepts plain JSON message records and rejects concrete LangChain message objects before serialization.

<!-- sig01-response-examples -->
```json
{
  "knowledge_cutoff": "2024-06-30T23:59:59Z",
  "message_representation": "plain_json",
  "cases": [
    {"policy": "availability", "case": "before", "available_at": "2024-06-30T23:59:58Z", "ingested_at": "2024-06-30T23:59:58Z", "eligible": true},
    {"policy": "availability", "case": "at_cutoff", "available_at": "2024-06-30T23:59:59Z", "ingested_at": "2024-06-30T23:59:59Z", "eligible": true},
    {"policy": "availability", "case": "late_ingestion", "available_at": "2024-06-30T23:59:59Z", "ingested_at": "2024-07-01T00:00:04Z", "eligible": true},
    {"policy": "availability", "case": "late_availability", "available_at": "2024-07-01T00:00:04Z", "ingested_at": "2024-07-01T00:00:04Z", "eligible": false},
    {"policy": "archive_realistic", "case": "before", "available_at": "2024-06-30T23:59:58Z", "ingested_at": "2024-06-30T23:59:58Z", "eligible": true},
    {"policy": "archive_realistic", "case": "at_cutoff", "available_at": "2024-06-30T23:59:59Z", "ingested_at": "2024-06-30T23:59:59Z", "eligible": true},
    {"policy": "archive_realistic", "case": "late_ingestion", "available_at": "2024-06-30T23:59:59Z", "ingested_at": "2024-07-01T00:00:04Z", "eligible": false},
    {"policy": "archive_realistic", "case": "late_availability", "available_at": "2024-07-01T00:00:04Z", "ingested_at": "2024-07-01T00:00:04Z", "eligible": false}
  ]
}
```

## Schema evolution

Every persisted record carries `schema_version`; readers may accept older versions through explicit migrations, never by silently dropping fields. Additive fields are optional first, then required only after all writers migrate. A failed migration leaves the prior artifact untouched and stops the affected run.

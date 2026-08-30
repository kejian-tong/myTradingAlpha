# Appendix C — Operational Runbooks

These runbooks are implementation targets for local, paper, and approved pilot operations. They intentionally contain no credentials or fixed live risk limits. Operators record every action with `run_id`, bundle hash, policy version, and a reason code.

## Common preflight

1. Confirm the selected mode, variant, code/config/lock hashes, calendar, and bundle source.
2. Verify `knowledge_cutoff <= decision_time < earliest_execution_time`.
3. Confirm the allowlist and instrument identity are versioned and active.
4. Verify required data-quality checks, clock, and ledger sequence.
5. Confirm `live_write_enabled=false` unless a Phase 09 approval explicitly authorizes a live level. `paper_write_enabled` is also false until an approved PAPER run. Historical mode denies all component egress; forward mode allows only approved `data_capture_egress`, `model_provider_egress`, and PAPER egress while `research_tool_egress=false` and `live_broker_egress=false`.
6. Confirm alert routing, persistent halt state, and operator approval record.
7. Never copy secrets into shell history, prompts, fixtures, logs, or reports.

## Historical replay

1. Select an immutable bundle ID/hash and `mode=historical`.
2. Enable the network-denial guard; verify no current-time vendor, pending-memory outcome, or broker client is reachable.
3. Run the requested variant with a recorded seed and manifest.
4. Validate `available_at` and, for archive-realistic mode, `ingested_at` against the cutoff.
5. Review evidence citations, QuantSignal, optional overlay status, target/risk output, ledger/NAV, and semantic artifact hash.
6. If a cutoff violation or hash mismatch occurs, mark the run failed, retain artifacts, and do not infer a trade.

## PIT data incident

Trigger: future/undated observation, stale bar, missing vintage, checksum mismatch, or unexpected revision.

1. Stop affected bundle sealing and mark `DATA_PIT_INVALID`.
2. Record source, locator, timestamps, revision, checksum, and affected instruments.
3. Do not patch a sealed bundle. Capture a corrected payload as a new revision/bundle.
4. Re-run cutoff, calendar, universe, and replay tests offline.
5. Keep the affected variant at `fail` or `insufficient_evidence` until review; return to the prior valid bundle if policy permits.

## LLM overlay failure

Trigger: timeout, schema error, invalid multiplier/action, prompt-injection attempt, or missing cited evidence.

1. Record `LLM_OVERLAY_ERROR` or `LLM_OVERLAY_ABSTAIN` with model/provider ID and no secret payload.
2. Emit no trade for that Quant+LLM run. Do not switch dynamically to Quant-only.
3. Continue monitoring existing holdings through deterministic risk policy only.
4. If a Quant-only comparison is desired, start its separately preregistered variant/run.
5. Review model/output artifact and update `GateEvidence`; do not edit the original envelope.

## Risk reject or persistent halt

Trigger: hard-limit breach, stale snapshot, invalid constraint, risk service error, or reconciliation-linked halt.

1. Stop new intent creation and persist the halt with policy/version/reason.
2. Verify the halt survives process restart and that no outbox dispatcher bypasses it.
3. Recalculate snapshot, exposure, liquidity, and target from immutable inputs.
4. If a resize is appropriate, create a new target and `RiskDecision=resize` referencing the prior decision; revalidate before approval.
5. Clear a halt only through an authorized, audited clear event. Otherwise return to cash/no-trade.

## OMS unknown acknowledgement

Trigger: submission timeout, malformed acknowledgement, broker/PAPER endpoint uncertainty, or conflicting duplicate.

1. Transition the intent to `unknown` and pause dispatch.
2. Query by stable `client_order_id` and broker order ID; capture orders, fills, and account state.
3. Reconcile local outbox/ledger against the endpoint snapshot.
4. If found, append the observed event/fills idempotently; if not found, require human review and endpoint policy before any new intent.
5. Never blind-resubmit an unknown intent. A conflicting duplicate or unexplained delta persists a halt.

## Reconciliation break

Trigger: cash, positions, open orders, fills, ledger sequence, or snapshot hash differs.

1. Freeze new submissions and mark `Reconciliation=investigate` or `halted`.
2. Capture local ledger, outbox, endpoint snapshot, event/fill IDs, and timestamps.
3. Check duplicate events, partial fills, corporate actions, fees, and timezone/session boundaries.
4. Create a reviewed correction event or classify as unresolved; never rewrite history.
5. Resume only after matching cash/positions/open orders/fills and recording approval.

## Forward-paper daily run

1. Confirm session close and capture immutable evidence.
2. Run the candidate and deterministic RiskEngine; obtain required human approval.
3. Submit only to local PaperBroker or the approved external PAPER endpoint when `paper_write_enabled=true`.
4. Collect all order events/fills, append the ledger, calculate NAV/costs, and reconcile.
5. Record latency, missingness, no-trade reasons, fills, costs, approvals, incidents, and artifacts.
6. If the endpoint is unavailable, disable paper writes or explicitly switch to local paper and record the mode change; do not pool modes silently.

## Live pilot incident and emergency handling

1. Enter persistent halt and alert the operator; stop new submissions.
2. Query/cancel open orders according to approved broker policy and reconcile current positions/fills.
3. Assess current liquidity, open orders, positions, data freshness, and reconciliation status.
4. Obtain human authorization for a policy-compliant action plan. The plan may be no action, staged reduction, or another approved response; it must not unconditionally send market liquidation.
5. Execute only approved intents, then reconcile and document outcomes.
6. Return to L0/paper until a new gate evidence record authorizes resumption or scope change.

## Closeout checklist

Attach sanitized logs, bundle/ledger/outbox hashes, approvals, reason codes, endpoint status, and reviewer. Mark the gate `pass`, `fail`, or `insufficient_evidence`; mandatory promotion gates cannot be waived. Retain failed artifacts for audit and record the rollback target.

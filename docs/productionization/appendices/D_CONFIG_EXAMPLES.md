# Appendix D — Configuration Examples

These examples describe future configuration shape only and are not directly loadable by the current strict ProductionConfig. Values are non-secret examples; deployment must supply approved bundle IDs, endpoint identities, policy versions, and limits through controlled configuration. Do not copy an example into a live environment without review.

## Historical, network-free replay

```yaml
run:
  mode: historical
  variant_id: quant_only_v1
  decision_time: "2026-01-15T21:00:00Z"
  knowledge_cutoff: "2026-01-15T21:00:00Z"
  earliest_execution_time: "2026-01-16T14:30:00Z"
  bundle_id: bundle-from-approved-manifest
  bundle_hash: sha256-from-approved-manifest
  calendar_id: XNYS-regular-v1
  replay_policy: archive_realistic
  network_policy:
    data_capture_egress: false
    model_provider_egress: false
    research_tool_egress: false
    paper_broker_egress: false
    live_broker_egress: false
portfolio:
  allowlist_id: approved-small-universe
  allocator: rule_v1
  leverage_policy: unlevered
risk:
  fail_closed: true
  policy_version: approved-policy-version
execution:
  paper_write_enabled: false
  live_write_enabled: false
```

## Forward paper with an approved PAPER endpoint

```yaml
run:
  mode: forward_paper
  variant_id: quant_llm_v1
  calendar_id: XNYS-regular-v1
  replay_policy: availability
  network_policy:
    data_capture_egress: true
    model_provider_egress: true
    research_tool_egress: false
    paper_broker_egress: true
    live_broker_egress: false
capture:
  provider_profile: approved-capture-profile
  bundle_store: immutable-bundle-store
portfolio:
  allowlist_id: approved-small-universe
  allocator: rule_v1
risk:
  fail_closed: true
  policy_version: approved-policy-version
execution:
  paper_endpoint_id: approved-paper-sandbox
  paper_write_enabled: false
  live_write_enabled: false
  approval_ref: required-before-enabling-paper-write
```

An operator may enable `paper_write_enabled` only for an approved paper run, with a recorded scope and endpoint. `live_write_enabled` remains false. Research/LLM evidence tools remain network-denied even when capture or approved PAPER egress is enabled.

## Live pilot level configuration shape

```yaml
run:
  mode: live_pilot
  live_level: L0
  variant_id: approved-variant-id
  calendar_id: XNYS-regular-v1
  required_gate_evidence_ref: phase-08-pass-record
  network_policy:
    data_capture_egress: true
    model_provider_egress: true
    research_tool_egress: false
    paper_broker_egress: false
    live_broker_egress: false
portfolio:
  allowlist_id: approved-level-manifest
  allocator: rule_v1
risk:
  fail_closed: true
  policy_version: approved-live-policy-version
  limits_ref: approved-controlled-policy
execution:
  broker_endpoint_id: approved-live-endpoint
  secret_ref: scoped-secret-reference
  paper_write_enabled: false
  live_write_enabled: false
  human_approval_required: true
operations:
  persistent_halt_store: durable-halt-store
  alert_route: approved-operator-route
```

L0 is read-only. L1/L2 values require separate approvals and level-specific manifests. Live limits are intentionally referenced rather than embedded here; no fixed risk number is a safe default.

## Configuration invariants

- `knowledge_cutoff <= decision_time < earliest_execution_time`.
- Historical mode sets every component in `network_policy` to false and reads only cached bundle responses; both write flags are false.
- `paper_write_enabled` defaults false and can target only an approved PAPER endpoint.
- `live_write_enabled` remains false until a Phase 09 approval; it is not controlled by an LLM or Research Graph node.
- Secret values are resolved at the credential boundary and are absent from RunContext, prompts, logs, fixtures, and report artifacts.
- Any missing policy, bundle, endpoint, approval, or lock metadata fails closed.

## Current loadable examples

The actual FND-03 parser and precedence live in `mytradingalpha/ops/config.py`; use
`tests/productionization/fixtures/config/historical.yaml`, `paper.yaml` and `live-read-only.yaml`
with `tests/productionization/test_config_redaction.py` for the supported configuration contract.
A syntactically valid mode or egress flag is not authorization for its future runtime side effects.
Do not loosen current extra-field validation merely to accept the future sketches above.

# SIG-01 closed replay and date amendment — approved

Status: approved by the user on 2026-09-04 for implementation in existing PR #24. Approval does not
waive test-first history, independent review, exact-head CI, or the Master merge gate.

Independent reviews reproduced host clock access, bounded host file read/write, and socket creation
through the accepted caller callable. The approved repair removes every caller-supplied callable and
replaces execution with closed replay of a separately versioned canonical cached response. It also
defines the research date as the UTC date of the sealed knowledge cutoff.

## Approved date rule

`trade_date` is the UTC date label of the sealed evidence snapshot and must equal
`canonical_context.knowledge_cutoff.date().isoformat()`. The guard already binds the context cutoff to
the bundle cutoff. Reject earlier and later labels before alias resolution or cache lookup. Preserve
`knowledge_cutoff <= decision_time < earliest_execution_time`.

This labels a research snapshot. It does not infer an exchange session, price availability, execution
schedule, or portfolio clock; those remain later roadmap work. Tests cover earlier/future dates, UTC
midnight and offset normalization, a differing decision date, and weekend snapshot labels.

## Approved runtime decision

An in-process callable cannot be made capability-free by a marker, attestation, type check, serializer,
or cooperative monkeypatch. SIG-01 therefore uses closed cached-response replay:

- Remove the caller-supplied Python runner. The adapter accepts canonical data only, with no dynamic
  callable, plugin, code loading, pickle-like format, generic object deserialization, or implicit
  latest-result selection. This replays an already captured graph result; it does not perform or claim
  new model inference.
- Add a separately versioned production-owned cached-response contract, byte sealer/parser, immutable
  exact selection, and append-only in-memory repository. Preserve every EvidenceBundle v1 field, hash,
  fixture, and reader; do not insert fields into an existing sealed bundle.
- Select one exact response ID and expected response hash. Bind bundle ID/hash, cutoff, calendar,
  replay policy, variant, trade date, ticker, resolved instrument/asset, graph/model/runtime artifact
  IDs and hashes, capture provenance, canonical output hash, and response hash.
- Accept bounded canonical UTF-8 JSON bytes produced by the production sealer. Reject duplicate keys,
  non-finite numbers, opaque values, malformed message/call records, authority fields, bad hashes,
  oversized data, and excessive depth/node/string counts. Never accept executable objects.
- Require response `available_at <= knowledge_cutoff`; archive-realistic replay additionally requires
  `ingested_at <= knowledge_cutoff`. Provenance supplies these timestamps; never infer or backdate them
  from `trade_date`.
- Missing, corrupt, cutoff-ineligible, mismatched, or incomplete responses fail with typed errors. Do
  not synthesize cache content, retry, invoke the ordinary graph, or use a remote/current/Quant-only
  fallback.
- Keep `tradingagents.graph.historical` a pure plain-data legacy-state validator and five-tier renderer.
  It never imports `mytradingalpha`. The production adapter remains the only reverse importer.

An isolated executable runtime is rejected for SIG-01 because it would require a larger platform,
transport, packaging, and adversarial confinement scope. No trusted-caller attestation is accepted as
a replacement for enforcement.

## Scope and acceptance

The repair adds the cached-response contract/repository under `mytradingalpha.research`, the adapter
mapping, and the pure `tradingagents` validator. Existing RunContext/EvidenceBundle consumers, ordinary
Research Graph, CLI, configuration precedence, and persisted v1 artifacts remain compatible. No new
dependency is added.

Required evidence includes a test-only canonical response fixture sealed through production parsing;
canonical round-trip/hash/repeatability; exact binding, provenance, cutoff, limit, and date mutation
denials; callback/import/host-handle payload rejection before execution; unchanged unpatched
network/file/clock/environment observers; legacy output and default graph regressions; exact-head
independent review and CI. Fixtures are contract evidence, not real inference.

No EvidenceToolset, ResearchNote, citation-completeness workflow, quant, portfolio, risk, backtest,
broker, paper/live, capture service, durable cache persistence, or production transcript generation is
included. Rollback disables the opt-in adapter and preserves all sealed evidence/response artifacts.

If this closed data-only contract cannot meet these invariants without another trust-model change or
material expansion, stop for a new human decision. Otherwise complete all gates, merge SIG-01, and
stop without starting SIG-02.

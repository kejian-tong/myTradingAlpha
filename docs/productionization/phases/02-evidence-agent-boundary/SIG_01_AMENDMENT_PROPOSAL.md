# SIG-01 runtime and date amendment — proposed, not approved

The independent reviewer_max reproduced host clock access, bounded host file read/write, and AF_INET socket creation through the accepted callable at 9f1d0b4614fbb77acdd14933d904d8588fd84eb9. The current wrapper does not enforce zero egress. No runtime or date change below is authorized or implemented. The existing PR remains blocked until the user chooses an architecture and all final-head gates pass.

## Proposed narrow date rule

Treat SIG-01 trade_date as the UTC date label of the sealed evidence snapshot: it must equal canonical RunContext.knowledge_cutoff.date().isoformat(). The guard already requires the context cutoff to equal the bundle cutoff. Reject both earlier and later labels before invoking a runtime. Keep the existing RunContext ordering knowledge_cutoff <= decision_time < earliest_execution_time. This rule does not infer an exchange session, price availability, execution schedule, or portfolio clock; those remain their roadmap slices. Tests must include earlier and future dates, cutoff at UTC midnight, differing decision dates, and offset timestamps normalized to UTC. This is a proposed semantic choice requiring approval, not an inference from the existing fixtures.

## Runtime decision

An arbitrary in-process callable cannot be made capability-free by a marker, attestation, type check, serializer, or cooperative monkeypatch. A bare child process also does not establish filesystem, clock, credential, or network isolation. Keeping the existing requirements therefore needs an explicitly approved executable boundary.

Recommended amendment — closed cached-response replay:

- Replace the public caller-supplied Python runner with a closed, repository-owned replay evaluator that accepts canonical data only, with no dynamic callable/plugin/code loading. This changes the SIG-01 happy path from executing injected graph code to replaying an already captured graph result. It does not claim new model inference.
- Consume only provenance-bound cached graph responses sealed with the evidence input; preserve legacy prose state and five-tier signal at the adapter output. Each response must identify its input bundle hash, bound research date/instrument, graph/model artifact identity, capture provenance, and canonical output hash. Verify all bindings before returning data. Do not accept a caller-created result dictionary as an approved transcript.
- Reject a missing, mismatched, or incomplete cached response; no synthesized model output, live inference, remote provider, current data, or default graph fallback.
- Requires a separately versioned cached-response contract and sealing/hash/replay integration, because current EvidenceBundle has no model-response/transcript domain. Preserve all existing v1 bundle hashes and readers; do not insert fields into already sealed artifacts. Cached responses used as historical input must satisfy the existing availability cutoff and archive ingestion cutoff. Missing archived responses remain typed unavailable; never backdate newly generated responses or invent cache content. The exact versioned encoding belongs in the approved repair JIT before GREEN.
- This changes the invocation/trust interface and expands SIG-01's data contract. It does not supply arbitrary local Python model execution. Approval must explicitly cover these differences; no EvidenceToolset/ResearchNote/citations or SIG-02 behavior is included by implication.

Alternative requiring a different amendment — isolated executable runtime:

- Replace opaque live Python bundle/context objects and arbitrary callable injection with an explicit runtime artifact and a bounded data-only request/response protocol.
- An audited execution substrate must enforce no host filesystem or durable writes, network/DNS/provider/loopback access, ambient credentials, subprocess escape, or host wall clock. Supply deterministic run time from the request only.
- Enforce memory/compute/output limits; fail with typed unavailable when the protected substrate is missing and typed denial on forbidden capabilities. Failed enforcement or incomplete evidence must never fall back in process.
- Requires choosing and proving a concrete isolation substrate and platform support, packaging a compatible runtime, and expanding CI with adversarial capability-denial tests. A generic promise of a sandbox is insufficient. No such backend is implemented or approved in the current repository.

The Master and independent max reviewer recommend the closed replay direction as the smaller boundary. It still changes the trust/interface and data contract and therefore requires explicit architecture approval. The isolated-execution alternative has a larger platform and verification scope. Neither is a routine callable-type-check repair. The already authorized bound-state, alias, canonical-context, and message-metadata corrections can proceed independently of this choice.

## Expected approved scope and acceptance

If the recommended amendment is approved, the SIG-01 JIT must explicitly add the production-owned cached-response contract/sealer/repository and adapter mapping, the generic closed replay runtime, and their tests. Existing EvidenceBundle/RunContext consumers, original Research Graph, CLI, and persisted v1 artifacts remain compatible. New dependencies require a separate demonstrated need; no arbitrary object deserialization or pickle is allowed. No EvidenceToolset, ResearchNote, citation-completeness workflow, quant, portfolio, broker, paper, or live implementation is implied.

Required observable evidence includes a legitimate provenance-bound cached result, canonical round-trip/hash/binding checks, repeatable output, missing/mismatched response denial, and data that attempts callback/import/host-handle injection rejected before execution. Network/file/clock/credential observers must remain unchanged without test monkeypatches supplying the enforcement. Failure of runtime availability or any enforcement test remains blocking insufficient evidence. Tests may use explicit fixtures but production cannot synthesize fixtures as a fallback.

Rollback disables the new opt-in replay adapter and preserves all sealed evidence/cache artifacts. Ordinary graph behavior remains unchanged. A fresh independent named controlling review under the current AGENTS.md harness, required exact-head CI, and Master gate remain necessary; architecture approval alone does not authorize merge.

Approval requested: authorize the closed cached-response replay amendment and the UTC cutoff-date label rule above for SIG-01, or choose the isolated executable direction with its expanded design/platform scope. Until that decision arrives, keep H4 and M1 open and stop before dependent implementation.

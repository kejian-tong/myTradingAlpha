# Just-in-Time PR Implementation Spec Template

Status: execution-harness template. This file does **not** add or change production architecture.

Use this template for each productionization roadmap PR after the master has reconciled the actual
current `main`, merged prerequisites, applicable `AGENTS.md` files, and the approved productionization
docs. The instantiated spec is a **just-in-time implementation contract** for one roadmap PR ID.

Do not pre-generate or maintain 47 speculative copies of this file. The point of this template is to
turn stable architecture into exact implementation mechanics at the moment a PR starts, using the
repository that actually exists then.

The actual current repository is authoritative for implementation reality. Proposed filenames, APIs,
symbols, examples, or pseudocode from older architecture documents must be reconciled against current
`main` before they are copied into the active PR spec. Preserve the approved architectural invariant;
do not silently redesign or pull later-PR work forward when documentation has drifted.

Persist the completed spec in the PR body or as a durable GitHub PR-conversation artifact before the
GREEN implementation begins. A separate committed per-PR spec file is not required unless the roadmap
explicitly calls for one.

---

## PR identity and baseline

- **Roadmap PR ID / title:** `<PR-ID> — <title>`
- **Phase:** `<phase>`
- **Base `main` SHA:** `<exact SHA>`
- **Prerequisite roadmap PRs:** `<IDs>`
- **Prerequisite merge SHAs verified:** `<SHAs>`
- **Current branch:** `codex/<pr-id-lowercase>-<short-description>`

## 1. Current-state reconciliation

Record only evidence observed from the current repository/GitHub state.

- Current `main` SHA and cleanliness/status:
- Relevant merged/open PRs:
- Current package/module/interface reality:
- Existing tests/CI/tooling relevant to this slice:
- Stale `AGENT_STATE.md` fields reconciled, if any:
- Material documentation drift from current code:

If documentation and code conflict materially, state the conflict and the smallest backward-compatible
resolution that preserves the approved architecture. Do not continue on an unresolved material design
conflict.

## 2. Applicable instructions and architecture sources

Read completely and list the exact sources used:

- root and deeper applicable `AGENTS.md` files;
- `.codex/config.toml` and the selected named-agent config;
- `docs/productionization/README.md`;
- the assigned row in `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`;
- the relevant phase `DESIGN.md`;
- the relevant phase `IMPLEMENTATION.md`;
- applicable contracts/schemas, traceability, test-matrix, runbook, ADR, or config appendices.

For each material source, note the invariant or requirement it contributes to this PR.

## 3. Exact implementation scope

### Existing files to modify

| File | Exact symbols/sections | Why this PR must touch it |
| --- | --- | --- |
| `<path>` | `<symbols>` | `<reason>` |

### New files to add

| File | Main symbols/interfaces | Responsibility |
| --- | --- | --- |
| `<path>` | `<symbols>` | `<responsibility>` |

### Files explicitly not to touch

List high-risk or tempting files that remain outside this slice and why.

## 4. Interfaces, schemas, and invariants

For every public or cross-module contract changed/introduced, specify:

- exact symbol/class/function/protocol name;
- current or proposed signature/field shape;
- input/output types and serialization rules;
- validation constraints;
- identity/time/Decimal/versioning semantics where applicable;
- ownership/dependency-direction constraints;
- compatibility expectations for existing callers/readers.

Do not invent future interfaces that are not required by this PR's acceptance criteria.

## 5. Behavioral contract

Describe observable behavior, including:

- happy path;
- deterministic/replay behavior where applicable;
- time/cutoff/calendar semantics where applicable;
- state transitions/accounting/idempotency rules where applicable;
- required reason codes or explicit degraded/rejected states;
- default behavior and opt-in/feature-flag behavior;
- what must remain unchanged in `tradingagents` or other existing surfaces.

## 6. Failure and error semantics

Enumerate expected failure classes and exact response behavior.

| Failure / invalid input | Required behavior | Fail-open/closed | Evidence/test |
| --- | --- | --- | --- |
| `<case>` | `<behavior>` | `<policy>` | `<test>` |

No silent fallback, swallowed exception, blind retry/resubmit, or implicit data substitution unless the
approved design explicitly requires it.

## 7. Security, network, persistence, and side-effect boundaries

State explicitly whether this PR may:

- access network providers;
- access model providers;
- persist or mutate durable artifacts;
- access secrets/credentials;
- submit PAPER writes;
- submit LIVE writes;
- change scheduler/automation behavior;
- alter externally visible systems.

For every allowed side effect, name the gate/flag/approval boundary. If not explicitly allowed by the
roadmap, record `not permitted in this PR`.

## 8. Backward compatibility

Specify what existing behavior must remain compatible, including as applicable:

- public imports;
- CLI behavior;
- config/environment precedence;
- persisted schema readers;
- existing `tradingagents` behavior;
- existing fixtures/checkpoints/artifacts;
- Python/version/package support.

List any intentionally changed compatibility surface and the explicit roadmap authorization for it.

## 9. Explicit non-goals

List all adjacent work that this PR must not implement.

Include later roadmap IDs that are especially easy to pull forward accidentally.

## 10. Deferred later-PR work

| Deferred item | Owning future PR | Why it is deferred now |
| --- | --- | --- |
| `<item>` | `<PR-ID>` | `<reason>` |

A phase-wide command/file/API owned by a later slice is deferred; do not implement it merely to make a
phase document appear complete early.

## 11. Migration

Describe the additive or staged migration path for this PR only:

1. current state;
2. new reader/writer/config/adapter activation order;
3. compatibility period;
4. artifact/schema/version implications;
5. conditions that block migration.

If no migration is needed, state why.

## 12. Rollback

Define the smallest safe rollback:

- code/config to disable or revert;
- persisted artifacts that remain immutable/readable;
- whether replay/reconciliation is required;
- data/history that must never be deleted or rewritten;
- external effects, if any, that must be reconciled before resuming.

## 13. Ordered implementation sequence

Write the exact implementation order after current-state inspection.

1. `<step>`
2. `<step>`
3. `<step>`

Each step should identify files/symbols and the observable contract it establishes. Do not combine
future roadmap functionality into the sequence.

## 14. RED plan

Per `AGENT_AUDIT_PROTOCOL.md`, make the new contract fail durably before production implementation when
executable tests can express it.

### Tests/fixtures to add first

| Test / fixture | Contract expressed | Expected RED failure |
| --- | --- | --- |
| `<path::test>` | `<contract>` | `<expected failure>` |

### RED command

```bash
<exact focused command>
```

- Expected exit status:
- Expected failure count/summary:
- RED commit contents allowed: tests, fixtures, test harness only.
- RED commit SHA after push: `<fill after execution>`

If TDD is genuinely not applicable (for example, docs-only harness work), state the concrete reason.

## 15. GREEN plan

Describe the minimum production implementation required to make the RED contract pass, in order.

1. `<implementation step>`
2. `<implementation step>`

Do not weaken the RED assertions to obtain GREEN.

## 16. Refactor boundary

List cleanup allowed after GREEN, such as extracting a helper or consolidating duplicate validation.
Also list refactors explicitly forbidden because they would widen scope.

## 17. Exact validation plan

Record exact commands expected for this PR, distinguishing focused validation from the repository
regression floor and GitHub CI.

### Focused

```bash
<commands>
```

### Repository regression floor

```bash
ruff check .
python -m pytest -q
git diff --check
```

Add package/install/type/static/integration checks when the actual slice requires them. Mark
phase-wide later-slice commands `deferred/not applicable to <PR-ID>` rather than implementing them
early.

No command is considered PASS until it actually executes successfully on the applicable SHA.

## 18. Acceptance matrix

| Requirement / invariant | Planned evidence | PASS criterion |
| --- | --- | --- |
| `<requirement>` | `<test/diff/CI/artifact>` | `<criterion>` |

Include at minimum:

- assigned roadmap acceptance criteria;
- scope/non-goal compliance;
- backward compatibility;
- migration/rollback validity;
- focused tests;
- full required validation;
- required CI on exact final head;
- independent reviewer artifact;
- master merge-gate artifact.

## 19. Complexity and named-agent routing

- **Complexity:** `normal | high | critical`
- **Route:** `luna_sol_high | luna_sol_xhigh | sol_high_sol_xhigh | sol_xhigh_sol_xhigh`
- **Reason:** `<actual correctness/safety complexity>`
- **Implementer role:** `normal_implementer | high_implementer | critical_implementer`
- **Implementer config:** `.codex/agents/<file>.toml`
- **Configured model / effort:** `<model> / <effort>`
- **Reviewer role:** `reviewer_high | reviewer_xhigh`
- **Reviewer config:** `.codex/agents/<file>.toml`
- **Configured model / effort:** `<model> / <effort>`
- **Master route:** `<configured/requested route>`
- **Escalation triggers specific to this PR:** `<conditions>`

Master defaults to Sol/xhigh; normal/high/critical implementation remains Luna/max with Sol/high or
Sol/xhigh review; difficult escalation uses Sol/high implementation and Sol/xhigh review; the hardest
route uses Sol/xhigh implementation and fresh Sol/xhigh review. Review escalation follows
`reviewer_high -> reviewer_xhigh`. Record an evidence-based reason before the
difficult or hardest route, retain the underlying safety class, keep one writer, and preserve all
safety/promotion/stop gates.

If the required named role/config cannot be loaded, stop with `insufficient_evidence`; do not silently
substitute a generic agent and claim the configured route.

## 20. Pre-implementation go/no-go

Before GREEN production edits begin, the master confirms:

- [ ] current `main` and prerequisites reconciled;
- [ ] applicable instructions/docs read;
- [ ] exact scope/files/interfaces identified from current code;
- [ ] material design ambiguity resolved;
- [ ] non-goals/later slices explicit;
- [ ] migration/rollback defined;
- [ ] complexity and named-agent routing selected;
- [ ] RED plan is executable (or a specific N/A reason exists);
- [ ] acceptance matrix and validation commands are concrete;
- [ ] no prohibited paper/live/external side effect is introduced.

Only then proceed with the bounded implementation.

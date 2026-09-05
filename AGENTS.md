# myTradingAlpha Agent Harness

This file applies to the repository root and all descendants unless a deeper `AGENTS.md` provides
more specific instructions for a subtree.

## 1. Purpose and operating model

Use this repository as a disciplined, PR-by-PR productionization project. The current
`tradingagents/` package is the upstream-derived Research Graph. Production-owned functionality is
introduced incrementally under `mytradingalpha/` according to the approved productionization
roadmap.

For productionization work, default to **one roadmap PR ID per implementation session**. Do not
combine dependency-ordered roadmap slices in one implementation PR unless the user explicitly
overrides the roadmap.

Preferred operating model:

1. a long-lived **master/orchestrator** context tracks roadmap state, model routing, and merge order;
2. a fresh **implementer** context/subagent handles exactly one PR ID;
3. a separate fresh **reviewer/verifier** context/subagent independently reviews that PR;
4. the master performs a final evidence/architecture gate;
5. after merge, refresh `main`, reconcile durable state, and only then begin the next dependency-valid
   PR.

Do not treat an implementer's self-review as the final independent review.

Durable cross-session checkpoint:

- `docs/productionization/AGENT_STATE.md`

Every master/orchestrator session must read and reconcile that file with GitHub before continuing.
GitHub/current `main` remains authoritative if the state file is stale.

---

## 2. Authoritative productionization architecture

For productionization tasks, treat these as the approved architecture and dependency-ordered plan:

- `docs/productionization/README.md`
- `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`

For the assigned PR, also read the relevant phase documents completely:

- `docs/productionization/phases/<phase>/DESIGN.md`
- `docs/productionization/phases/<phase>/IMPLEMENTATION.md`

Use when applicable:

- `docs/productionization/appendices/A_REQUIREMENTS_TRACEABILITY.md`
- `docs/productionization/appendices/B_TEST_MATRIX.md`

The **actual current repository state is authoritative for implementation reality**. If documentation
names a file/interface that has changed, inspect current `main` and adapt the smallest implementation
that still satisfies the approved architectural invariant.

If current code and approved architecture materially conflict:

1. identify the drift explicitly;
2. preserve approved architectural invariants;
3. do not silently redesign the architecture;
4. do not expand into later roadmap slices;
5. report the conflict and choose the smallest safe backward-compatible implementation.

Commands in phase implementation documents are plans until concrete execution evidence exists. A
phase-wide command may belong to a later PR slice; do not implement later-slice tooling merely to make
that command available early.

---

## 3. Repository architecture invariants

### 3.1 Research/production ownership boundary

- `tradingagents/` remains the upstream-derived Research Graph.
- `mytradingalpha/` is the production-owned namespace introduced by the roadmap.
- No file under `tradingagents/` may import `mytradingalpha`.
- Only `mytradingalpha.research` may import/adapt `tradingagents`.
- Other `mytradingalpha` bounded contexts must not import `tradingagents` directly.
- Production domains consume production-owned contracts/interfaces rather than another domain's
  persistence internals.

### 3.2 Backward compatibility

Unless the assigned roadmap slice explicitly requires otherwise:

- preserve existing `tradingagents` public imports;
- preserve the existing `tradingagents` CLI entry point;
- preserve existing runtime behavior;
- preserve existing configuration/environment precedence;
- do not rename the current Python distribution merely because `mytradingalpha/` is introduced;
- do not rewrite existing persisted research artifacts merely to adopt future production schemas;
- prefer additive, opt-in changes over invasive migration.

### 3.3 Safety boundary

Do not introduce functionality before its assigned roadmap phase.

In particular, do not add broker, paper, or live order side effects unless the assigned PR explicitly
belongs to the approved broker/paper/live phases and its prerequisites are merged.

Before Phase 09, no live broker write is permitted. Earlier phases remain research/simulation/paper-
only exactly as specified by the roadmap. Do not copy example risk limits, allowlists, credentials, or
broker settings into live defaults.

Autonomous orchestration never authorizes an agent to waive an explicit paper/live promotion gate or
to approve its own real-world trading side effects.

---

## 4. Durable state and long-term project memory

`docs/productionization/AGENT_STATE.md` is the repository-tracked operational memory for fresh agent
contexts. It supplements, but never replaces, approved architecture documents or GitHub history.

The master/orchestrator owns this state. Keep it concise and evidence-backed. It must track at least:

- last reconciled `main` SHA;
- current/next roadmap PR ID and phase;
- last completed roadmap PR;
- compact per-PR ledger;
- requested and actual model/reasoning routing;
- escalation classification/reason when applicable;
- validation, CI, reviewer, and master verdicts;
- merge SHA when known;
- scope-leak status;
- blockers/evidence gaps and material deferred findings.

Recommended compact ledger entry:

```text
FND-01
base: <sha>
PR: #<n>
merge: <sha-or-pending>
complexity: normal|high|critical
implementer: <actual-model> / <actual-effort>
reviewer: <actual-model> / <actual-effort>
master: <actual-model> / <actual-effort>
escalation: none|<reason>
tests: PASS|FAIL|INSUFFICIENT_EVIDENCE
CI: PASS|FAIL|PENDING
review: APPROVE|REQUEST_CHANGES
scope leak: none|<summary>
next: FND-02|BLOCKED
```

### 4.1 State reconciliation

At the beginning of every master session:

1. read this `AGENTS.md` completely;
2. read `docs/productionization/AGENT_STATE.md` completely;
3. fetch current `main`, relevant open/merged PRs, and CI/check state;
4. reconcile stale state fields against GitHub;
5. repair prior pending merge/status/model fields when evidence proves the actual result;
6. continue only from the dependency-valid next PR.

Never trust the state file over actual GitHub history.

### 4.2 Updating state without weakening review

The implementer should not use the state file for implementation logic or speculative notes. The
master owns operational-state updates.

Before merge, record known base/head, model routing, validation, CI, reviewer/master verdict, scope
status, and `merge: pending` if needed. The reviewer must inspect state-file changes when they are part
of the PR.

After merge, reconcile the actual merge SHA before starting, or as the first state update of, the next
roadmap PR. If branch protection blocks direct post-merge state updates, do not bypass protection;
reconcile in the next normal branch/PR.

A fresh master must be able to recover from this file plus GitHub even when prior chat memory is gone.

---

## 5. Adaptive model routing and reasoning policy

Model routing is an **execution policy**, not production architecture. The master selects the strongest
appropriate model for each role and PR while avoiding unnecessary flagship-model use for routine work.

### 5.1 Default role routing

| Role | Requested model | Requested reasoning effort |
| --- | --- | --- |
| Master/orchestrator | GPT-5.6 Sol | xhigh / Extra High |
| Normal implementer | GPT-5.6 Luna | max |
| High implementer | GPT-5.6 Sol | high |
| Critical implementer | GPT-5.6 Sol | xhigh / Extra High |
| Independent reviewer / boundary reviewer | GPT-5.6 Sol | high, xhigh for escalation |
| Difficult review/implementation escalation (opt-in) | GPT-5.6 Sol | high -> xhigh |

Reasoning-effort labels may differ by runtime. Treat `xhigh` and UI wording such as `Extra High` as the
same intended tier when appropriate. Never falsely claim the runtime used a requested model/effort.

### 5.2 Complexity classes

Before spawning an implementer, the master must classify the assigned PR in the PR Scope Contract:

#### `normal`

Use by default for bounded, well-specified work with ordinary correctness risk, such as package
scaffolding, straightforward configuration plumbing, documentation/CI tooling, and simple adapters.

Requested routing:

- implementer: **GPT-5.6 Luna / max**;
- reviewer: **GPT-5.6 Sol / high** (`reviewer_high`);
- master: **GPT-5.6 Sol / xhigh**.

Keep normal work on this route unless new evidence changes its complexity classification. A routine
finding alone is not a reason to spend a stronger route.

#### `high`

Use when the PR contains materially elevated algorithmic, temporal, accounting, concurrency,
statistical, or architecture-correctness risk.

Requested routing:

- implementer: **GPT-5.6 Luna / max**;
- reviewer: **GPT-5.6 Sol / high** (`reviewer_high`);
- master: **GPT-5.6 Sol / xhigh**.

High work intentionally shares the normal starting route to control credits, but has explicit
follow-up rules:

- implementation complexity beyond the bounded Luna assignment: stop the prior writer, record the
  evidence, and use `high_implementer` / Sol high while keeping `reviewer_high` unless review also needs
  escalation;
- review ambiguity or subtle unresolved correctness risk: retain the current implementer and run a
  fresh `reviewer_xhigh` / Sol xhigh;
- both conditions: use the difficult-escalation route, Sol/high implementation plus Sol/xhigh review.

Typical `high` candidates include:

- point-in-time cutoff, publication, availability, ingestion, and revision semantics;
- EvidenceBundle canonical serialization/hash/replay correctness;
- deterministic event ordering and backtest replay;
- ledger/NAV/accounting and fee-once invariants;
- corporate actions and benchmark accounting;
- portfolio/risk constraints and numerical edge cases;
- spread/slippage/impact/liquidity/capacity accounting;
- walk-forward/statistical validation and holdout logic;
- state-machine correctness where no real broker side effect is yet enabled.

#### `critical`

Use when a subtle error can cross a safety boundary, create externally consequential behavior, corrupt
reconciliation/idempotency guarantees, or invalidate a promotion gate.

Requested routing:

- implementer: **GPT-5.6 Luna / max**;
- reviewer: **GPT-5.6 Sol / xhigh** (`reviewer_xhigh`) in a fresh independent context;
- master: **GPT-5.6 Sol / xhigh**.

Typical `critical` candidates include:

- OMS state transitions with externally meaningful effects;
- outbox/idempotency/exactly-once-style safeguards;
- broker reconciliation and unknown-ACK handling;
- paper/live broker-write boundaries and credential isolation;
- kill-switch/halt persistence and emergency controls;
- paper/live promotion logic and live pilot safety constraints.

`critical` model routing does **not** waive any human paper/live approval gate.

### 5.2.1 Graduated implementation/review routes

Complexity (`normal|high|critical`) describes correctness and safety risk. The requested routes are:

| Task route | Implementer | Reviewer | Intended trigger |
| --- | --- | --- | --- |
| normal | `normal_implementer` — Luna/max | `reviewer_high` — Sol/high | ordinary work; keep this route unchanged |
| high initial | `normal_implementer` — Luna/max | `reviewer_high` — Sol/high | same cost-conscious start as normal; explicit follow-up rules above |
| high implementation-only escalation | `high_implementer` — Sol/high | `reviewer_high` — Sol/high | implementation complexity only |
| high review-only escalation | `normal_implementer` — Luna/max | `reviewer_xhigh` — Sol/xhigh | review ambiguity only |
| critical | `normal_implementer` — Luna/max | `reviewer_xhigh` — Sol/xhigh | critical boundaries with a known implementation path |
| difficult escalation | `high_implementer` — Sol/high | `reviewer_xhigh` — Sol/xhigh | implementation needs more reasoning after high/critical analysis |
| hardest escalation | `critical_implementer` — Sol/xhigh | `reviewer_xhigh` — Sol/xhigh | deepest approved work using fresh independent maximum Sol reasoning |

Default to the first route appropriate for the task. A review-only escalation keeps the current
implementer and advances `reviewer_high -> reviewer_xhigh`. Record the route,
evidence-based reason, and affected roles in the JIT and `AGENT_STATE.md`. Stop the previous writer
before dispatching a replacement; only one production writer may run.

The Master defaults to **GPT-5.6 Sol / xhigh**. GPT-6 routes are temporarily disabled; changing this
requires a later reviewed harness PR and a fresh session. Configuration changes do not hot-switch an
existing Master.

Model routing does not change the underlying safety class, grant scope or authority, resolve a human
architecture decision, or waive any paper/live gate. If a required named route cannot be loaded,
record `insufficient_evidence` and stop before merge. Historical records keep their actual routes.

### 5.3 Dynamic escalation rules

The master chooses complexity from the actual current diff/scope, not merely the phase name. Do not
escalate solely because a PR is large; escalate because correctness or reasoning risk is materially
higher.

The master may escalate at any time when investigation/review reveals hidden complexity:

```text
normal -> high -> critical
```

Separately, escalate implementation/review routes in Section 5.2.1 without changing the underlying
safety class. Model escalation does not resolve any autonomous stop condition by itself.

Examples that justify escalation:

- documentation assumptions conflict with current code;
- invariants span multiple state transitions or clocks;
- numeric/accounting behavior has non-obvious edge cases;
- concurrency, retry, idempotency, or reconciliation semantics appear;
- a reviewer finds a subtle architecture/correctness issue;
- safety or external side-effect boundaries are involved.

Do not silently de-escalate a PR after a serious correctness finding. If de-escalation is justified,
record the reason in `AGENT_STATE.md`.

### 5.4 Reviewer independence and model diversity

Fresh context independence is mandatory even when implementer and reviewer use the same model tier.
For normal, high, and critical PRs, use Luna/max implementation with Sol/high or Sol/xhigh review
as specified above. For difficult escalation, use Sol implementation with Sol review. For the hardest
route, use Sol/xhigh implementation with an independent Sol/xhigh reviewer. Every reviewer remains
a separate fresh context and must inspect diff/tests/evidence independently.

The master is not a substitute for the independent reviewer; it is a final gate after review.

### 5.5 Requested routing versus actual runtime capability

These are requested routing policies, not assumptions about product/runtime capability.

Before delegation, use model/effort selection controls when the environment exposes them. If the
runtime cannot select the requested model or reasoning level:

1. do not falsely claim it did;
2. use the strongest available compatible model/effort that preserves the role's intent;
3. record **requested** and **actual** model/effort in `AGENT_STATE.md`;
4. preserve a fresh independent reviewer context;
5. if a `critical` task cannot obtain an adequately strong/independent runtime, stop with
   `insufficient_evidence` rather than weakening the gate.

Model names and available effort tiers may evolve. Update this section when the supported model fleet
changes; do not rewrite the 47 architecture PR definitions merely to change agent routing.

### 5.6 Activating routing changes

Model configuration edits apply to fresh sessions that actually load the updated trusted checkout.
They do not switch a running agent's model. After the harness PR merges, refresh the relevant checkout
with main and start a fresh Master session. Resume a paused PR with new agents only after its existing
stop conditions are resolved and the loaded routes are recorded; a blocked PR need not merge before
an independent harness update. Keep all previous review/model evidence intact and obtain new review
and CI for any new head. A configured route is not proof of a successful spawn.
Future PRs use these routes once loaded. Do not reopen, re-review, or rewrite completed PRs merely
because the harness changed; reconcile only stale operational status from GitHub evidence.

---

## 6. Required pre-flight for every productionization PR

Before editing code for a roadmap PR:

1. fetch/sync latest `main`;
2. verify repository/worktree status and do not overwrite unrelated user changes;
3. record exact `main` base SHA;
4. read this `AGENTS.md` and every deeper applicable `AGENTS.md`;
5. read/reconcile `docs/productionization/AGENT_STATE.md` with GitHub;
6. read completely:
   - `docs/productionization/README.md`;
   - the assigned PR row in `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`;
   - the relevant phase `DESIGN.md`;
   - the relevant phase `IMPLEMENTATION.md`;
7. inspect actual current files, interfaces, tests, packaging, and CI touched by the slice;
8. compare roadmap assumptions with current `main`;
9. determine exact scope **and complexity class** before implementation.

Produce a concise **PR Scope Contract** before coding with:

- PR ID/title and base `main` SHA;
- applicable `AGENTS.md` files and reconciled previous-state evidence;
- current-state drift/findings;
- exact existing/new files expected;
- public interfaces/invariants;
- focused tests/fixtures;
- explicit non-goals;
- migration and rollback;
- acceptance criteria and validation commands;
- later-PR items explicitly deferred;
- complexity: `normal`, `high`, or `critical`;
- requested implementer/reviewer/master model and reasoning effort;
- escalation rationale when class is not `normal`.

If productionization-related work has no PR ID, perform analysis only; do not guess a slice, unless the
session is explicitly an autonomous master resuming from reconciled `next_pr_id`.

---

## 7. Scope discipline

### 7.1 One PR slice means one PR slice

Implement only the assigned roadmap ID. Do not implement a later PR merely because its API appears in
a phase design, a future file/script is mentioned, or later work appears convenient while touching the
same module.

Prefer the smallest implementation satisfying the current slice while leaving a clean seam for later
work.

### 7.2 No speculative abstractions

Do not add placeholder services, future schemas, unused DI frameworks, broker interfaces, database
layers, or generalized registries unless required by the current slice's acceptance criteria. A
future-facing package directory required by the current slice may be empty; future behavior stays
future work.

### 7.3 Avoid opportunistic cleanup

Do not perform unrelated formatting sweeps, file moves, renames, dependency upgrades, or broad
refactors. Record unrelated technical debt separately rather than widening the active PR.

---

## 8. Test-first implementation

Use **red -> green -> refactor**.

### RED

Add the smallest focused failing tests expressing the assigned PR contract before production
implementation. Tests should exercise observable behavior or architectural invariants, not merely
mirror implementation structure.

### GREEN

Implement the minimum code required to satisfy new tests while preserving the existing suite.

### REFACTOR

Simplify names/structure without changing semantics or expanding scope.

For static architecture rules, prefer deterministic source/AST inspection over importing application
modules with side effects. Tests should be deterministic and network-free by default; external-service
tests remain explicit integration/smoke behavior only where the existing repo already treats them so.

---

## 9. Validation policy

Run validations applicable to the assigned slice and record exact results. Never claim a command was
run when it was not.

Default validation floor:

- focused tests for the assigned PR;
- assigned roadmap-specific validation script/test;
- `ruff check .`;
- `python -m pytest -q`;
- `git diff --check`.

Also run install/import/packaging smoke checks when packaging/public imports change.

If a phase implementation document lists a command owned by a later PR:

- mark it `deferred/not applicable to <current PR ID>`;
- do not implement the later script merely to satisfy the command.

Inspect CI/check results when tooling permits. Local pass is not a substitute for required CI evidence.
A pre-existing failure may be reported only with evidence that it is unrelated to the current diff.

---

## 10. Git and PR workflow

### 10.1 Branching

Branch from latest verified `main` for every roadmap slice.

Use `codex/<pr-id-lowercase>-<short-description>`, for example:

- `codex/fnd-01-package-boundary`
- `codex/pit-01-capture-provenance`

Do not reuse a prior implementation branch for a new roadmap PR.

### 10.2 Commits and pull requests

Use focused commits; do not mix unrelated cleanup.

Open a non-draft, ready-for-review PR targeting `main` only after applicable validation passes. The PR
body must include:

- roadmap PR ID/title and base `main` SHA;
- architecture/docs consulted and scope summary;
- exact files added/modified;
- tests added/changed and exact validation results;
- complexity class plus requested/actual model routing when known;
- migration/compatibility and rollback;
- explicit non-goals preserved;
- confirmation later slices were not implemented;
- unresolved evidence gaps.

By default, do not merge automatically. Automatic merging is allowed only when the user explicitly
activates autonomous mode for the master/orchestrator.

---

## 11. Master/orchestrator behavior

When acting as master:

1. reconcile `AGENT_STATE.md` with GitHub before selecting work;
2. maintain dependency order from `07_PR_IMPLEMENTATION_PLAN.md`;
3. classify the PR as normal/high/critical and choose routing under Section 5;
4. never start the next dependent PR before the current one passes review and is merged;
5. delegate exactly one implementation PR ID to a fresh implementer context;
6. after PR creation, delegate independent verification to a different fresh reviewer context;
7. independently inspect final evidence before declaring/performing merge;
8. update durable state/ledger with actual routing and evidence;
9. after merge, refresh `main`, reconcile merge SHA, then repeat pre-flight for the next PR.

The master may parallelize read-only investigation/review, but must not parallelize implementation of
dependency-ordered slices whose prerequisites are not merged.

Do not infer PASS from intent or PR prose. Require evidence.

Supervised-mode status when all gates pass:

`READY TO MERGE — <PR ID>`

### 11.1 Autonomous mode

A master may operate autonomously only when the user explicitly authorizes it in the kickoff/resume
instruction. Authorization may permit merging ordinary roadmap PRs after all required gates pass and
continuing without per-PR confirmation.

Autonomous loop:

```text
reconcile main/state
  -> classify PR + choose requested model routing
  -> spawn fresh implementer for exactly one PR ID
  -> implement/test/push/open PR
  -> spawn separate fresh reviewer
  -> fix BLOCKER/HIGH findings on same PR if necessary
  -> re-review
  -> verify required CI/checks
  -> master final gate
  -> merge PR
  -> refresh main
  -> reconcile/update durable ledger including actual routing
  -> spawn fresh implementer for next dependency-valid PR
```

Autonomous mode does not mean "merge despite uncertainty." The merge gate remains identical to
supervised mode.

### 11.2 Autonomous stop conditions

Even when authorized, stop and request human input instead of self-overriding when:

- a `BLOCKER`/`HIGH` reviewer finding remains unresolved;
- required CI/checks fail because of the current diff;
- a material architecture/document conflict requires redesign;
- a prerequisite PR/gate is missing or ambiguous;
- required GitHub write/merge permission is unavailable;
- branch protection/ruleset prevents the required operation;
- a blocking gate has `insufficient_evidence`;
- required credentials/secrets would need to be invented or supplied;
- an explicit human promotion/approval is required for externally consequential behavior;
- paper/live broker side effects would be enabled without the approved human gate;
- independent fresh reviewer context is unavailable when required;
- a critical task cannot obtain an adequately strong/independent model runtime.

Do not reinterpret autonomous execution as permission to weaken gates.

### 11.3 Fresh sessions versus fresh subagents

Do not assume a product/UI capability to create new user-visible threads. When subagents are supported,
use fresh subagent contexts for implementer/reviewer isolation. If the top-level master ends because
of product/session limits, persist/reconcile `AGENT_STATE.md`; a newly opened master can resume from
GitHub plus durable state. Never claim to have created a UI thread when that capability is absent.

---

## 12. Independent reviewer/verifier behavior

A reviewer reviews repository/diff evidence, not the implementer's summary.

Before verdict:

1. fetch current `main` and PR and verify base/head SHAs;
2. read applicable `AGENTS.md`, roadmap docs, and relevant state entries;
3. inspect every changed filename and complete diff;
4. inspect focused tests and relevant existing tests;
5. inspect CI/check results;
6. verify scope, backward compatibility, and model-routing claims.

Review for:

- roadmap acceptance criteria;
- later-phase leakage/scope creep;
- architecture/dependency-direction violations;
- packaging/install/public API/CLI/config regressions;
- ineffective/tautological tests or missing negative tests;
- unnecessary abstractions;
- side effects introduced too early;
- migration/rollback gaps;
- claims without execution evidence;
- inaccurate durable ledger/model-routing entries.

Classify findings as `BLOCKER`, `HIGH`, `MEDIUM`, `LOW`, or `NIT`. `BLOCKER` or `HIGH` prevents
approval.

For each BLOCKER/HIGH, report affected file, exact issue, violated invariant/criterion, smallest fix,
and test/evidence proving the fix.

Final reviewer verdict must be exactly one of:

- `APPROVE`
- `REQUEST CHANGES`

Do not start the next roadmap PR from a reviewer context.

---

## 13. Productionization phase guardrails

- **Foundation:** ownership/contracts/config-observability/reproducibility-CI only in their assigned
  slices; do not jump ahead.
- **Point-in-time data:** explicit availability/revision semantics and sealed replay; current network
  responses are not historical truth.
- **Evidence/signal:** Research Graph is an adapter/input; bounded LLM output must not directly create
  production portfolio weights/orders.
- **Backtest/ledger:** deterministic replay/fills/costs/accounting before broker/OMS; prevent lookahead
  and fee double counting.
- **Portfolio/risk:** hard risk is deterministic and independent of LangGraph; fail closed where
  required.
- **Execution/cost/liquidity:** model costs/liquidity explicitly before deployable-alpha claims.
- **Experiment/alpha:** follow preregistered variants, seed requirements, walk-forward/holdout and
  statistical gates; backtest improvement is not production readiness.
- **OMS/paper/forward/live:** respect staged safety gates. Autonomous orchestration cannot self-promote
  through a human approval gate; live write remains disabled until approved Phase 09 conditions.

---

## 14. Evidence and claims

Distinguish code/tests that exist, commands actually executed, CI evidence, planned future gates,
research results, paper readiness, and live readiness.

Do not claim PIT correctness, alpha, paper readiness, or live readiness from ordinary unit tests or
green CI alone.

Use `pass`, `fail`, or `insufficient_evidence` where docs define a gate. `insufficient_evidence`
blocks downstream promotion; it is not a waiver.

---

## 15. Default short prompts for new Codex sessions

Because this harness and `AGENT_STATE.md` carry stable policy/state, new sessions can use short prompts.

### Single implementation PR

> Implement FND-01 only. Follow AGENTS.md and the approved productionization roadmap. Use the model
> routing selected by the master/runtime, create a ready-for-review PR, and stop after FND-01.

### Independent review

> Review PR #<N> for <PR-ID>. Follow AGENTS.md. Independently verify scope, tests, CI, architecture,
> state/model ledger, and acceptance criteria. Do not modify code unless asked.

### Supervised master

> Act as the productionization master orchestrator. Follow AGENTS.md and reconcile AGENT_STATE.md.
> Start/continue from the next dependency-valid PR, classify complexity and apply adaptive model
> routing, use isolated implementer/reviewer agents, and stop before merging unless authorized.

### Autonomous master

> Act as the autonomous productionization master orchestrator. Follow AGENTS.md and reconcile
> AGENT_STATE.md with current GitHub state. Classify each PR and apply the adaptive model/reasoning
> routing policy. You are authorized to merge ordinary roadmap PRs after independent review, required
> validation, CI, and master gate pass; then refresh main, update durable state, and continue to the
> next dependency-valid PR using fresh implementer/reviewer contexts. Do not bypass explicit human
> paper/live promotion gates or blocking insufficient-evidence gates. Stop only on an AGENTS.md
> autonomous stop condition.

The short prompt selects role/mode. `AGENTS.md` supplies stable repository harness/model routing;
`AGENT_STATE.md` supplies durable cross-session execution state.

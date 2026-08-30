# myTradingAlpha Agent Harness

This file applies to the repository root and all descendants unless a deeper `AGENTS.md` provides more specific instructions for a subtree.

## 1. Purpose

Use this repository as a disciplined, PR-by-PR productionization project. The current `tradingagents/` package is the upstream-derived Research Graph. Production-owned functionality is introduced incrementally under `mytradingalpha/` according to the approved productionization roadmap.

For productionization work, default to **one roadmap PR ID per implementation session**. Do not combine dependency-ordered roadmap slices in one implementation PR unless the user explicitly overrides the roadmap.

The preferred operating model is:

1. a long-lived **master/orchestrator** session that tracks roadmap state and merge order;
2. a fresh **implementer** session/subagent for exactly one PR ID;
3. a separate fresh **reviewer/verifier** session/subagent for the completed PR;
4. master verification before merge;
5. refresh `main` after merge before starting the next PR.

Do not treat an implementer’s self-review as the final independent review.

---

## 2. Authoritative productionization architecture

For productionization tasks, treat these as the approved architecture and dependency-ordered implementation plan:

- `docs/productionization/README.md`
- `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`

For the assigned PR, also read the relevant phase documents completely:

- `docs/productionization/phases/<phase>/DESIGN.md`
- `docs/productionization/phases/<phase>/IMPLEMENTATION.md`

Use the traceability/test appendices when applicable:

- `docs/productionization/appendices/A_REQUIREMENTS_TRACEABILITY.md`
- `docs/productionization/appendices/B_TEST_MATRIX.md`

The **actual current repository state is authoritative for implementation reality**. If a document names a file that has already changed, inspect current `main` and adapt the smallest implementation that still satisfies the approved invariant.

If current code and approved architecture materially conflict:

1. identify the drift explicitly;
2. preserve approved architectural invariants;
3. do not silently redesign the architecture;
4. do not expand into later roadmap slices;
5. report the conflict and choose the smallest safe implementation that keeps backward compatibility.

Commands described in phase implementation documents are plans until there is concrete execution evidence. A phase-wide command may belong to a later PR slice; do not implement later-slice tooling merely to make a phase-wide command available early.

---

## 3. Repository architecture invariants

Preserve these invariants unless a later approved roadmap PR explicitly changes them.

### 3.1 Research/production ownership boundary

- `tradingagents/` remains the upstream-derived Research Graph.
- `mytradingalpha/` is the production-owned namespace introduced by the roadmap.
- No file under `tradingagents/` may import `mytradingalpha`.
- Only `mytradingalpha.research` may import/adapt `tradingagents`.
- Other `mytradingalpha` bounded contexts must not import `tradingagents` directly.
- Production domains consume production-owned contracts/interfaces rather than reaching into another domain’s persistence internals.

### 3.2 Backward compatibility

Unless the assigned roadmap slice explicitly requires otherwise:

- preserve existing `tradingagents` public imports;
- preserve the existing `tradingagents` CLI entry point;
- preserve existing runtime behavior;
- preserve existing configuration/environment precedence;
- do not rename the current Python distribution just because `mytradingalpha/` is introduced;
- do not rewrite existing persisted research artifacts merely to adopt future production schemas;
- prefer additive, opt-in changes over invasive migration.

### 3.3 Safety boundary

Do not introduce functionality before its assigned roadmap phase.

In particular, do not add broker, paper, or live order side effects unless the assigned PR explicitly belongs to the approved broker/paper/live phases and its prerequisites are merged.

Before Phase 09, no live broker write is permitted. Earlier phases must remain research/simulation/paper-only exactly as specified by the roadmap.

Do not copy example risk limits, allowlists, credentials, or broker settings into live defaults.

---

## 4. Required pre-flight for every productionization PR

Before editing code for a roadmap PR:

1. Fetch/sync the latest `main`.
2. Verify repository/worktree status and do not overwrite unrelated user changes.
3. Record the exact `main` base SHA.
4. Read this `AGENTS.md` and every deeper applicable `AGENTS.md`.
5. Read completely:
   - `docs/productionization/README.md`;
   - the assigned PR row in `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`;
   - the relevant phase `DESIGN.md`;
   - the relevant phase `IMPLEMENTATION.md`.
6. Inspect the actual current files, interfaces, tests, packaging, and CI touched by the slice.
7. Compare roadmap assumptions with current `main`.
8. Identify the exact scope before implementation.

Produce a concise **PR Scope Contract** before coding with:

- PR ID and title;
- base `main` SHA;
- applicable `AGENTS.md` files;
- current-state findings/drift;
- exact existing files expected to change;
- exact new files expected;
- public interfaces/invariants;
- focused tests/fixtures;
- explicit non-goals;
- migration behavior;
- rollback plan;
- acceptance criteria;
- validation commands;
- later-PR items explicitly deferred.

If the task is productionization-related but no PR ID is supplied, perform analysis only; do not guess a roadmap slice and do not start implementation.

---

## 5. Scope discipline

### 5.1 One PR slice means one PR slice

Implement only the assigned roadmap ID.

Do not implement a later PR merely because:

- its API is mentioned in a phase design;
- a phase-wide implementation document lists a future file;
- a later validation script does not exist yet;
- the later work appears easy to add while touching the same module;
- an abstraction could theoretically support future phases.

Prefer the smallest implementation that satisfies the current slice and leaves a clean seam for later work.

### 5.2 No speculative abstractions

Do not add placeholder services, empty future schemas, unused dependency injection frameworks, broker interfaces, database layers, or generalized registries unless they are required by the assigned PR’s acceptance criteria.

A future-facing package directory required by the current slice may be empty; future behavior should remain future work.

### 5.3 Avoid opportunistic cleanup

Do not perform unrelated formatting sweeps, file moves, renames, dependency upgrades, or broad refactors in a productionization PR.

If unrelated technical debt is discovered, record it separately instead of folding it into the current slice.

---

## 6. Test-first implementation

Use **red → green → refactor** for implementation PRs.

### RED

Add the smallest focused failing tests that express the assigned PR’s contract before production implementation.

Good tests should exercise observable behavior or architectural invariants, not merely duplicate implementation structure.

### GREEN

Implement the minimum code required to satisfy the new tests while preserving the existing suite.

### REFACTOR

Simplify names/structure without changing semantics or expanding scope.

For static architecture rules, prefer deterministic source/AST inspection over importing application modules with side effects.

Tests should be deterministic and network-free by default. External-service tests must only be used where the existing repository already treats them as explicit integration/smoke behavior.

---

## 7. Validation policy

Run validations applicable to the assigned slice and record exact results. Do not claim commands were run when they were not.

The default implementation-PR validation floor is:

- focused tests for the assigned PR;
- any assigned roadmap-specific validation script/test;
- `ruff check .`;
- `python -m pytest -q`;
- `git diff --check`.

Also run install/import/packaging smoke checks when the slice changes packaging or public imports.

If the phase implementation document lists a command whose script is intentionally owned by a later PR:

- mark it `deferred/not applicable to <current PR ID>`;
- do not implement the later script merely to satisfy the command.

When a PR is opened, inspect CI/check results when tooling permits. A local pass is not a substitute for required CI evidence.

A pre-existing failure may be reported only when there is evidence it is unrelated to the current diff; do not silently normalize failures.

---

## 8. Git and PR workflow

### 8.1 Branching

Branch from the latest verified `main` for each roadmap slice.

Use:

`codex/<pr-id-lowercase>-<short-description>`

Examples:

- `codex/fnd-01-package-boundary`
- `codex/pit-01-capture-provenance`

Do not reuse a prior implementation branch for a new roadmap PR.

### 8.2 Commits

Use focused commits. Do not mix unrelated cleanup with the assigned slice.

### 8.3 Pull request

Open a non-draft, ready-for-review PR targeting `main` after applicable validation passes.

The PR body must include:

- roadmap PR ID/title;
- base `main` SHA;
- architecture/docs consulted;
- scope summary;
- exact files added/modified;
- tests added/changed;
- exact validation results;
- migration/compatibility notes;
- rollback plan;
- explicit non-goals preserved;
- confirmation that later slices were not implemented;
- any unresolved evidence gap.

Do not merge automatically unless the user explicitly authorizes merging.

---

## 9. Master/orchestrator behavior

When acting as the master/orchestrator:

1. maintain dependency order from `07_PR_IMPLEMENTATION_PLAN.md`;
2. never start the next dependent PR before the current one passes review and is merged;
3. delegate one implementation PR ID to a fresh implementer context;
4. after the PR is created, delegate independent verification to a different fresh context;
5. independently inspect the final evidence before declaring the PR ready;
6. after the user merges, refresh `main`, record the new SHA, and repeat pre-flight for the next PR.

The master may parallelize **read-only investigation/review**, but must not parallelize implementation of dependency-ordered slices whose prerequisites are not merged.

Maintain a compact ledger in the master session:

- PR ID;
- base SHA;
- branch;
- PR URL;
- changed files;
- validation evidence;
- CI status;
- reviewer verdict;
- master verdict;
- merge SHA.

Do not infer PASS from intent or PR prose. Require evidence.

When all gates pass, report:

`READY TO MERGE — <PR ID>`

Do not merge unless explicitly authorized.

---

## 10. Independent reviewer/verifier behavior

A reviewer must review the repository/diff, not the implementer’s summary.

Before verdict:

1. fetch current `main` and the PR;
2. verify base/head SHAs;
3. read applicable `AGENTS.md` files and authoritative roadmap documents;
4. inspect every changed filename and the complete diff;
5. inspect focused tests and relevant existing tests;
6. inspect CI/check results when available;
7. verify scope and backward compatibility.

Review specifically for:

- roadmap acceptance criteria;
- later-phase leakage/scope creep;
- architecture/dependency-direction violations;
- packaging/install regressions;
- public API/CLI/config regressions;
- ineffective or tautological tests;
- missing negative tests;
- unnecessary abstractions;
- side effects that are too early for the roadmap;
- migration/rollback gaps;
- claims without execution evidence.

Classify findings as:

- `BLOCKER`
- `HIGH`
- `MEDIUM`
- `LOW`
- `NIT`

`BLOCKER` or `HIGH` prevents approval.

For each `BLOCKER`/`HIGH`, report:

- affected file;
- exact issue;
- violated invariant/acceptance criterion;
- smallest required fix;
- test/evidence that proves the fix.

Final reviewer verdict must be exactly one of:

- `APPROVE`
- `REQUEST CHANGES`

Do not start the next roadmap PR from a reviewer session.

---

## 11. Productionization phase guardrails

These summarize cross-cutting boundaries. The detailed roadmap remains authoritative.

### Foundation

Establish ownership, contracts, configuration/observability, reproducibility/CI in the specified slices. Do not jump from package skeleton to later contract/config/lockfile work in the wrong FND PR.

### Point-in-time data

Historical correctness requires explicit availability/revision semantics and sealed replay. Do not treat current network responses as historical truth.

### Evidence/signal

The Research Graph is an adapter/input to production research. LLM output is bounded according to the approved architecture and must not directly create production portfolio weights/orders.

### Backtest/ledger

Build deterministic replay, fills, costs, and accounting before broker/OMS work. Prevent fee double counting and lookahead.

### Portfolio/risk

Hard risk remains deterministic and independent of LangGraph. Fail closed where the design requires it.

### Execution/cost/liquidity

Model costs/liquidity explicitly before claiming deployable alpha.

### Experiment/alpha validation

Follow preregistered variants, seed requirements, walk-forward/holdout/statistical gates. Do not turn a backtest improvement into a production-readiness claim.

### OMS/paper/forward/live

Respect the staged safety gates. Paper and live writes are not generic capabilities to add early. Live write remains disabled until the approved live phase and explicit approval.

---

## 12. Evidence and claims

Distinguish clearly between:

- code/tests that exist;
- commands that were actually executed;
- CI evidence;
- planned future gates;
- research results;
- paper-readiness evidence;
- live-readiness evidence.

Do not claim PIT correctness, alpha, paper readiness, or live readiness from ordinary unit tests or green CI alone.

Use `pass`, `fail`, or `insufficient_evidence` where the productionization docs define a gate. `insufficient_evidence` blocks downstream promotion; it is not a waiver.

---

## 13. Default short prompts for new Codex sessions

Because this harness carries the stable instructions, a new productionization implementation session may be started with a short request such as:

> Implement FND-01 only. Follow AGENTS.md and the approved productionization roadmap. Create a ready-for-review PR and stop after FND-01.

A review session may be started with:

> Review PR #<N> for <PR-ID>. Follow AGENTS.md. Independently verify scope, tests, CI, architecture, and acceptance criteria. Do not modify code unless asked.

A master session may be started with:

> Act as the productionization master orchestrator. Follow AGENTS.md. Start/continue from <PR-ID>, use isolated implementer and reviewer agents, and stop before merging unless I explicitly authorize it.

The short prompt selects the role and PR. This `AGENTS.md` supplies the stable repository harness.

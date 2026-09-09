# myTradingAlpha Agent Harness

This file defines repository-wide agent policy. Codex automatic project-instruction discovery walks from
the project root to the current working directory (CWD) and stops there; deeper `AGENTS.md` files on that
root-to-CWD chain add path-specific instructions, with the closest discovered file providing local detail.
Do not assume a nested `AGENTS.md` outside the current CWD chain becomes loaded merely because a file in
that subtree is opened or edited. For every in-scope path outside the current CWD chain, the
`productionization-preflight` skill must explicitly read the applicable scoped `AGENTS.md` before edits.
The global safety, authority, language, routing, and merge rules below always remain in force.

## Repository language

All repository-authored engineering prose must be English, including docs, code comments/docstrings,
commit messages, PR text, reviews, and reports, even when the user asks in Chinese or another language.
Preserve product localization data, fixtures, exact identifiers, sealed artifacts, and immutable historical
evidence as data. Do not rewrite an original review/model verdict merely to make it match a newer policy.

## 2. Ownership and architecture invariants

This repository productionizes an upstream-derived Research Graph incrementally:

- `tradingagents/` is the upstream-derived research namespace.
- `mytradingalpha/` is the production-owned namespace.
- No module under `tradingagents/` may import `mytradingalpha`.
- Only `mytradingalpha.research` may import/adapt `tradingagents`.
- Other production bounded contexts consume production-owned contracts/interfaces and must not import
  `tradingagents` directly or another domain's persistence internals.

Unless the authorized slice explicitly requires otherwise, preserve existing `tradingagents` public
imports, CLI behavior, runtime behavior, configuration/environment precedence, distribution identity,
and persisted research artifacts. Prefer additive, opt-in changes over invasive migration.

Path-specific rules:

- `docs/productionization/AGENTS.md` — roadmap execution, JIT, operational state, review artifacts.
- `mytradingalpha/AGENTS.md` — production dependency, determinism, compatibility, side-effect rules.
- `tradingagents/AGENTS.md` — upstream/research compatibility boundary.
- `tests/productionization/AGENTS.md` — deterministic TDD/contract-test rules.

These scoped files are authoritative for their paths when applicable, but automatic discovery depends on
the root-to-CWD chain. Preflight explicitly loads any other scoped file needed by the authorized change.

## 3. Productionization authority and roadmap

Approved architecture and dependency order live in:

- `docs/productionization/README.md`;
- `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`;
- the assigned phase `DESIGN.md` and `IMPLEMENTATION.md`;
- applicable traceability/test appendices.

Actual current repository state is authoritative for implementation reality, but it does not grant
permission to redesign approved architecture. If current code and approved design materially conflict,
choose the smallest safe backward-compatible implementation that preserves the approved invariant; stop
for human resolution if that is not possible.

Default to one roadmap PR ID per implementation session. Do not start a dependency-ordered later slice
before the current slice is merged. A user-authorized bounded harness/maintenance task does not authorize
the next roadmap implementation PR.

For productionization workflow procedures, use the repo skills under `.agents/skills/`:

- `productionization-preflight`;
- `jit-scope-contract`;
- `tdd-red-green-evidence`;
- `exact-head-review`;
- `merge-gate`.

Skills describe how to execute repeatable procedures; they never override the invariants or authority in
this file or scoped `AGENTS.md` files.

## 4. Safety and external side effects

Do not introduce behavior before its approved roadmap phase or merged prerequisites. In particular:

- before Phase 09, no live broker write is permitted;
- no agent may invent credentials, secrets, account identifiers, allowlists, risk limits, or permissive
  live defaults;
- autonomous orchestration cannot waive paper/live promotion gates;
- an agent cannot approve its own externally consequential side effect;
- idempotency, reconciliation, unknown-ACK handling, kill/halt controls, credential isolation, and
  promotion gates fail closed when in scope.

Explicit human paper/live/promotion approval remains mandatory wherever the architecture requires it,
regardless of model strength, review count, automation mode, or passing tests.

## 5. Master-centric multi-agent model

The master/orchestrator owns scope, dependency order, model routing, JIT synthesis, triage, and the final
merge decision. The master/root context is the only project role allowed to spawn subagents.

Every project-scoped non-master named role must load `[agents] enabled = false`. A GPT-5.6 Sol
Multi-Agent V2 child may nevertheless expose collaboration controls; collaboration-control visibility alone
is not a stop condition. The Master remains the only role authorized to invoke collaboration controls or
delegate work. Do not invoke collaboration controls or delegate nested work from a non-master role. Any
attempted or completed nested delegation is a blocking violation. Record complete runtime observation and
stop on an actual non-master invocation attempt, while retaining `telemetry_conflict` for separate route or
loading contradictions.

Use hybrid concurrency:

- parallelize materially independent read-only exploration/audit/review when useful;
- allow at most one production-code writer for the active PR;
- never run a replacement writer concurrently with the prior writer;
- exact-head review lanes may run concurrently against the same frozen SHA;
- close completed child threads when no follow-up is expected.

The project concurrency guardrail is six open spawned threads. Six is burst headroom, not a target.
Do not spawn redundant agents merely to fill capacity.

Named specialist roles:

- `code_explorer` — read-only code/current-state exploration;
- `test_auditor` — read-only TDD/test/CI audit;
- `boundary_reviewer` — read-only architecture/security/scope boundary review;
- `external_spec_researcher` — on-demand read-only authoritative mutable external specification research.

Specialists add evidence; they never replace the controlling independent reviewer or self-authorize merge.
The `astra_canary` is not a production specialist: it is a shadow-only evaluator for closed historical or
immutable replay tasks and cannot participate in an active PR as writer, controlling reviewer, or Master.

### 5.1 Prospective read-only child admission

A read-only parent must be selected and observed before spawn; a child TOML request is not host enforcement.
The first child turn is admission-only: first turn: no tools or substantive work. The Master gives approval
only after a trusted post-spawn host observation confirms the child tuple, complete tool inventory, and
approval boundary. Missing, stale, contradictory, or out-of-order evidence causes lane invalidation and
`insufficient_evidence`; do not salvage the lane. Model self-report, Codex JSONL, `codex doctor`, static
TOML, hooks, telemetry, standalone fallback, and generic fallback are not authentication or a substitute
for the required host observation.

## 6. Adaptive model routing

Routing is execution policy, not production architecture. Select the least expensive adequate route from
evidence and record the requested/configured actual route. Never claim runtime telemetry that was not
observed.

Default named roles:

| Role | Model / effort |
| --- | --- |
| Master/orchestrator | GPT-5.6 Sol / xhigh |
| `normal_implementer` | GPT-5.6 Luna / max |
| `high_implementer` | GPT-5.6 Sol / high |
| `critical_implementer` | GPT-5.6 Sol / xhigh |
| `reviewer_high` | GPT-5.6 Sol / high |
| `reviewer_xhigh` | GPT-5.6 Sol / xhigh |
| `code_explorer` | GPT-5.6 Luna / max |
| `test_auditor` | GPT-5.6 Luna / max |
| `boundary_reviewer` | GPT-5.6 Sol / high |
| `external_spec_researcher` | GPT-5.6 Luna / max, read-only |
| `astra_canary` | GPT-6 Astra / xhigh, shadow-only read-only |

Complexity and production routes:

- `normal`: `normal_implementer` + `reviewer_high`;
- `high` initial: `normal_implementer` + `reviewer_high`;
- high implementation-only escalation: `high_implementer` + `reviewer_high`;
- high review-only escalation: `normal_implementer` + `reviewer_xhigh`;
- `critical`: `normal_implementer` + `reviewer_xhigh` when the implementation path is known;
- difficult escalation: `high_implementer` + `reviewer_xhigh`;
- hardest approved route: `critical_implementer` + fresh `reviewer_xhigh`.

Classify from actual correctness/safety risk rather than PR size. Elevated temporal, accounting,
statistical, concurrency, replay, idempotency, reconciliation, or state-machine risk can justify `high`.
Externally consequential OMS/broker/promotion/kill-switch boundaries can justify `critical`.

Implementation complexity alone escalates the writer; review ambiguity alone escalates the reviewer.
Stop the prior role before replacement and record the evidence-based reason. Do not silently de-escalate
a serious correctness finding.

GPT-6 production routes remain disabled unless a later reviewed harness change explicitly activates one.
The `astra_canary` does not activate GPT-6 for production: it may only replay frozen historical hardest/
critical tasks under the same acceptance and safety matrix as the Sol/xhigh baseline. Public model evals
are priors, not myTradingAlpha evidence. Canary promotion requires representative repo-specific evidence
and a separate reviewed harness PR; unavailable or incomparable canary runs remain `insufficient_evidence`.

## 7. Runtime evidence and fresh contexts

A config file expresses configured intent; it is not proof that a named role actually loaded. Distinguish
requested route, configured route, successfully loaded named-role configured actual, and any independent
runtime telemetry. Conflicting telemetry must be resolved before claiming a route.

If a required named role cannot be loaded, record `insufficient_evidence` and stop the affected merge gate.
Do not silently substitute a generic worker or different model and claim the intended route. An unavailable
optional `astra_canary` blocks only that canary comparison; it never weakens or replaces the active Sol
production route.

Routing/config/hook changes apply prospectively after merge, refreshed checkout, and fresh session/agent
loading. Running agents retain their historical routes. Do not relabel prior evidence.

## 8. Durable state and session recovery

`docs/productionization/AGENT_STATE.md` is master-owned operational memory. GitHub/current main remains
authoritative. Every fresh master for productionization work must reconcile the state file with current
GitHub before selecting work.

A fresh master must be able to recover from repository state plus GitHub without prior chat memory. Keep
state concise, evidence-backed, and limited to operational facts such as SHAs, PR IDs, routes, validation,
review/CI/gate verdicts, blockers, and the informational next dependency-valid slice.

Do not trust stale state over GitHub, and do not create speculative ledger claims for work that has not
executed.

## 9. Test, validation, and exact-head requirements

Executable roadmap behavior uses RED -> GREEN -> REFACTOR with durable commit evidence as defined by the
TDD skill and scoped test instructions. Docs/harness-only work may mark executable RED not applicable with
a concrete reason.

Default validation floor when applicable:

- focused tests for the active scope;
- roadmap-specific validation;
- `ruff check .`;
- `python -m pytest -q`;
- `git diff --check`;
- package/install/import smoke when public packaging/imports change;
- required GitHub CI/check evidence.

Never claim a command ran when it did not. Network/live-service tests are not a substitute for deterministic
contract tests.

Review and CI evidence are exact-head specific. Any new commit invalidates affected prior evidence. A
fresh controlling reviewer must inspect the exact final head; unresolved BLOCKER/HIGH from any material
review lane blocks merge.

## 10. Git, PR, and merge discipline

For roadmap slices, branch from latest verified main and use a dedicated branch. Keep commits focused; do
not mix unrelated cleanup, dependency upgrades, renames, or later-slice work.

PR descriptions must identify authorized scope/PR ID, base SHA, JIT/architecture sources, files changed,
validation evidence, complexity/routing, compatibility/rollback, non-goals, and unresolved evidence gaps.

The master alone owns the final merge gate. Reviewer APPROVE is necessary but not merge authority. Before
merge, require exact-final-head scope, independent review, required CI, compatibility/safety, and durable
merge-gate evidence. Bind autonomous merges to the expected head SHA.

Automatic merge is permitted only when the user explicitly authorizes autonomous execution for the
bounded task. Autonomous mode never means merge despite uncertainty.

## 11. Stop conditions

Stop instead of self-overriding when any of these remains material:

- unresolved BLOCKER/HIGH;
- attributable required-CI failure;
- material architecture conflict requiring redesign;
- missing/ambiguous prerequisite or authorization boundary;
- unavailable required named role or inadequate independent runtime;
- `insufficient_evidence` at a blocking gate;
- required credentials/secrets would need to be invented/supplied;
- branch protection/permission prevents the required operation;
- scope leakage into a later roadmap slice;
- explicit human paper/live/promotion approval is required.

## 12. Hooks and change control

Project hooks are defined in `.codex/hooks.json` and governed by
`docs/productionization/CODEX_HOOKS.md`. They provide lightweight supplemental feedback and do not replace
CI, independent review, the offline harness validator, or the master merge gate.

Treat `.codex/**`, `.agents/skills/**`, root/scoped `AGENTS.md`, agent configs, hooks, harness validators,
and their contract tests as security-sensitive execution-harness surfaces. Change them through reviewed,
bounded harness PRs with exact-head checks. Never place secrets, real broker credentials, or user-specific
absolute paths in harness configuration.

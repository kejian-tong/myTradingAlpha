# myTradingAlpha Agent Harness

This file is repository-wide policy. Automatic instruction discovery follows the project root to the current working directory (CWD)
and stops there; opening or editing a deeper file does not load its `AGENTS.md`; opened or edited content is not automatically loaded.
For paths outside that chain, `productionization-preflight` must explicitly read the scoped
instructions. This policy remains authoritative over configuration, role files, hooks, and skills.

## Repository language

Repository-authored engineering prose is English, including docs, code comments/docstrings, commit messages,
PR text, reviews, and reports requested in English or Chinese. Preserve localization strings, fixtures, identifiers, and
immutable historical evidence as data.

## 2. Ownership and architecture invariants

`tradingagents/` is the upstream-derived research namespace; `mytradingalpha/` is production-owned.
No `tradingagents/` module imports `mytradingalpha`; only `mytradingalpha.research` may adapt
`tradingagents`; other bounded contexts consume production contracts instead of research internals.
Unless an authorized slice says otherwise, preserve upstream public imports, CLI/runtime behavior,
configuration precedence, distribution identity, and persisted research artifacts. Prefer additive,
opt-in changes.

Scoped instruction routes are:

- `docs/productionization/AGENTS.md` — roadmap execution, JIT, state, and review artifacts;
- `mytradingalpha/AGENTS.md` — production dependencies, determinism, compatibility, and side effects;
- `tradingagents/AGENTS.md` — upstream/research compatibility;
- `tests/productionization/AGENTS.md` — deterministic TDD and contract tests.

## 3. Productionization authority and roadmap

Current GitHub/main and repository state define implementation reality. Approved architecture and order
come from `docs/productionization/README.md`, `07_PR_IMPLEMENTATION_PLAN.md`, the assigned phase
`DESIGN.md`/`IMPLEMENTATION.md`, and applicable traceability/test appendices. Do not redesign an approved
invariant to fit drift; stop for human resolution when a small compatible change cannot reconcile it.

Execute one authorized roadmap PR at a time. A bounded Harness maintenance PR does not authorize SIG-03
or a later productionization slice. The repository skills are the procedures for
`productionization-preflight`, `jit-scope-contract`, `tdd-red-green-evidence`, `exact-head-review`,
`merge-gate`, and `writer-lease`.

## 4. Safety and external side effects

Do not introduce behavior before its approved phase or prerequisites. Before Phase 09 no live broker
write is permitted. Never invent credentials, accounts, allowlists, risk limits, or permissive live
defaults. Orchestration cannot waive paper/live promotion approval; no agent may approve its own
externally consequential side effect. Idempotency, reconciliation, unknown-ACK handling, halts, secret
isolation, and promotion gates fail closed when applicable. Explicit human PAPER/live/promotion approval
remains mandatory.

## 5. Master-centric execution and ownership

The Master/orchestrator owns scope, dependency order, routing, JIT synthesis, triage, and the final merge
decision. Master-only delegation is a behavioral policy, not runtime identity enforcement. Every named
non-master role sets `[agents] enabled = false`; collaboration-control visibility alone is non-blocking.
Do not invoke collaboration controls or delegate nested work. Any attempted or completed nested delegation
is a blocking policy violation. A runtime-denied/no-op attempt is still an attempt; missing trustworthy
observation is `insufficient_evidence`, while `telemetry_conflict` remains distinct.

Use hybrid scheduling: independent reads/reviews may run together, but one production writer owns an
active PR. Never overlap a replacement writer. Review lanes inspect the same frozen exact head; close
completed lanes. The project guardrail is six concurrently open spawned threads, not a target or lifetime
cap. The Master alone decides and merges. GitHub Copilot review/coding agents must not be requested, mentioned, assigned, or used.

### 5.1 Native read-only admission

Native host-enforced read-only admission is preferred and required for reviewers, auditors, explorers,
external specification research, canaries, and every roadmap/product, broker, PAPER/live, promotion,
externally consequential, or critical-safety review. A fresh host-enforced read-only parent is required;
live parent overrides are controlling; before substantive work or any tool call, obtain post-spawn host-origin evidence
for the effective sandbox/profile/approval tuple and complete tool inventory. The first child turn is admission-only,
must receive no substantive task, make no tool call, and cannot self-approve; only then may the follow-up substantive task
be sent. On failure, interrupt and discard the lane. child/model prose is not host evidence; model self-report, caller-created JSON, hooks, telemetry, static TOML, and an
offline verifier cannot authenticate the host boundary. Missing evidence is `insufficient_evidence`.

The sole bounded Harness-review exception: explicit per-task human authorization may qualify
Harness-only maintenance when native admission is unavailable. It is not independent review, never
fabricates reviewer/model/runtime evidence, cannot authorize roadmap/product work, and cannot waive
broker, PAPER/live, promotion, or critical-safety gates.

## 6. Adaptive model routing

Routing is execution policy, not product architecture. Select the least expensive adequate named route;
record requested/configured actual route and never invent runtime telemetry.

| Role | Model / effort |
| --- | --- |
| Master/orchestrator | GPT-5.6 Sol / xhigh |
| `normal_implementer` | GPT-5.6 Luna / max |
| `high_implementer` | GPT-5.6 Sol / high |
| `critical_implementer` | GPT-5.6 Sol / xhigh |
| `reviewer_high` | GPT-5.6 Sol / high |
| `reviewer_xhigh` | GPT-5.6 Sol / xhigh |
| `code_explorer`, `test_auditor` | GPT-5.6 Luna / max |
| `boundary_reviewer` | GPT-5.6 Sol / high |
| `external_spec_researcher` | GPT-5.6 Luna / max |
| `astra_canary` | GPT-6 Astra / xhigh, shadow-only |

### Named route matrix

| class | named writer + controlling reviewer |
| --- | --- |
| normal | `normal_implementer` + `reviewer_high` |
| high initial | `normal_implementer` + `reviewer_high` |
| high implementation escalation | `high_implementer` + `reviewer_high` |
| high review escalation | `normal_implementer` + `reviewer_xhigh` |
| critical | `normal_implementer` + `reviewer_xhigh` |
| difficult | `high_implementer` + `reviewer_xhigh` |
| hardest | `critical_implementer` + `reviewer_xhigh` |

Normal and high share the initial route; critical uses `reviewer_xhigh`; implementation and review
escalations follow the exact matrix above. GPT-6 production routes remain disabled. The
`astra_canary` is shadow-only for closed historical/immutable replay and cannot write, control-review,
merge, or act as Master. An unavailable or incomparable canary is `insufficient_evidence`, not a route
substitute. Routing changes apply prospectively after merge, refreshed main, and a fresh session.

## 7. Runtime evidence and state

Configuration expresses intent; distinguish requested route, configured actual, loaded named role, and
independent runtime telemetry. Resolve conflicting telemetry before claiming a route. A required named
role that cannot load is `insufficient_evidence`; do not substitute a generic worker. Optional canary
unavailability blocks only its comparison.

`docs/productionization/AGENT_STATE.md` is Master-owned operational memory; GitHub/current main wins on
conflict. Reconcile it at fresh-master start and keep only bounded operational facts: PR/base/final SHAs,
routes, validation, reviews, gates, blockers, and the informational next dependency. Do not turn it into a
chronological log.

## 9. Test, validation, and exact-head requirements

Executable changes use RED -> GREEN -> REFACTOR with durable commit evidence. The default floor is focused
tests, roadmap validation, `ruff check .`, `python -m pytest -q`, `git diff --check`, and applicable
package/import smoke and required CI. Hooks and offline checks are supplemental; network/live tests do not
replace deterministic contracts. Review and CI evidence bind to the exact SHA; any new commit makes
affected evidence stale. A fresh controlling reviewer must inspect the final head and unresolved
BLOCKER/HIGH findings or required-CI failures stop merge. For explicitly authorized Harness-only
maintenance only, `DEGRADED_MASTER_REVIEW` may qualify missing native evidence; it is not independent review
and still requires exact-head review, complete validation/CI, disclosure, and no material
uncertainty.

## 10. Git, PR, and merge discipline

Roadmap branches start from verified main and contain one PR scope. Keep commits focused and identify
scope/base/JIT/files/validation/route/compatibility/rollback/non-goals in the PR. The Master alone owns
the final merge gate, which binds autonomous merge to the expected exact head and requires the durable
controlling review, writer evidence, required CI, safety checks, and no scope leak. For explicitly
authorized Harness-only maintenance only, `DEGRADED_MASTER_REVIEW` may use a separate Master artifact;
it is not independent review. Never request, assign, mention, or use GitHub Copilot agents.

## 11. Stop conditions

Stop for unresolved BLOCKER/HIGH, attributable required-CI failure, architecture conflict, missing
authorization/prerequisite, unavailable required role or runtime evidence, required credentials, branch
protection/permission failure, scope leakage, or a human paper/live/promotion gate. For explicitly
authorized Harness-only maintenance only, `DEGRADED_MASTER_REVIEW` is the narrow exception for missing
native independent-review evidence; it is not independent review and cannot waive safety or promotion
boundaries. Do not override a stop by weakening tests or inventing evidence.

## 12. Hooks and change control

`.codex/hooks.json` and the hook policy provide lightweight supplemental feedback. They do not replace CI,
independent review, the offline validator, or the Master gate. Treat `.codex/**`, `.agents/skills/**`,
AGENTS files, role/config files, hooks, and validators as security-sensitive harness surfaces; change them
through bounded reviewed Harness PRs. Never put secrets, real broker credentials, or user-specific
absolute paths in harness policy.

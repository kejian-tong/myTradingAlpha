# Productionization Agent State

This file is the durable, repository-tracked checkpoint for agent-driven productionization work.
It is operational state, not architecture. The approved architecture remains in
`docs/productionization/README.md`, `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`, and the
phase DESIGN/IMPLEMENTATION documents.

`AGENTS.md` defines how agents must use and maintain this file, including adaptive model routing.

## State schema

- `schema_version`: 2
- `last_reconciled_main_sha`: `0fbd318c4421eb303b6aa090458b9e844e0416e6`
- `roadmap_status`: `stopped_after_fnd_04`
- `current_pr_id`: `none`
- `next_pr_id`: `PIT-01`
- `current_phase`: `01-point-in-time-data`
- `autonomy_mode`: `stopped_by_user_after_fnd_04`
- `last_completed_roadmap_pr`: `FND-04`
- `default_master_route`: `GPT-5.6 Sol / xhigh`
- `default_normal_implementer_route`: `GPT-5.6 Luna / max`
- `default_reviewer_route`: `GPT-5.6 Sol / high`

The state above must be reconciled against GitHub before every implementation session. GitHub/main is
authoritative if this file is stale. Model names/effort tiers here describe requested policy; each PR
must record the actual runtime/model evidence when available.

## Durable architecture memory

Keep these invariants visible across fresh sessions:

- `tradingagents/` remains the upstream-derived Research Graph.
- `mytradingalpha/` is the production-owned namespace introduced incrementally by the roadmap.
- No file under `tradingagents/` may import `mytradingalpha`.
- Only `mytradingalpha.research` may import/adapt `tradingagents`.
- Existing `tradingagents` public imports, CLI behavior, and runtime behavior remain backward
  compatible unless an approved roadmap slice explicitly changes them.
- One dependency-ordered roadmap PR ID is implemented per PR by default.
- Later-slice work must not be pulled forward to satisfy phase-wide examples or planned commands.
- Historical correctness, alpha evidence, paper readiness, and live readiness require their own
  explicit roadmap gates; ordinary green unit tests/CI do not prove them.
- Broker/paper/live side effects remain prohibited until their approved phase and required approval
  gates.

## Durable model-routing memory

The master classifies each PR from actual scope/current code before implementation.

| Complexity | Implementer request | Reviewer request | Master request | Intended use |
| --- | --- | --- | --- | --- |
| `normal` | GPT-5.6 Luna / max | GPT-5.6 Sol / high | GPT-5.6 Sol / xhigh | bounded, well-specified ordinary-risk implementation |
| `high` | GPT-5.6 Sol / high | GPT-5.6 Sol / high, xhigh if needed | GPT-5.6 Sol / xhigh | temporal/accounting/numerical/statistical/state-machine correctness |
| `critical` | GPT-5.6 Sol / xhigh | GPT-5.6 Sol / xhigh | GPT-5.6 Sol / xhigh | safety/external-side-effect/idempotency/reconciliation/promotion boundaries |

Typical reasons to classify or escalate `high` include PIT cutoff/revision semantics, EvidenceBundle
canonical hashing, deterministic replay/event ordering, ledger/NAV accounting, corporate actions,
risk constraints, cost/liquidity/impact accounting, walk-forward statistics, and non-live state
machines.

Typical `critical` reasons include OMS/outbox/idempotency/reconciliation, unknown-ACK behavior,
broker credential/write boundaries, persistent halts/kill controls, and paper/live promotion logic.

The master may dynamically escalate `normal -> high -> critical` if investigation/review reveals
hidden complexity. Do not escalate only because a PR is large. Record the actual correctness/safety
reason.

If the runtime cannot select the requested model or effort:

- do not claim that it did;
- use the strongest available compatible route;
- preserve a fresh independent reviewer context;
- record requested and actual model/effort;
- for critical work, stop with `insufficient_evidence` if adequate model strength/independence is not
  available.

## Roadmap PR ledger

The master/orchestrator owns this ledger. Add one row per roadmap PR. Keep entries concise and based
on evidence, not intent.

| PR ID | Base main SHA | Branch | PR | Head / merge SHA | Complexity / actual routing | Tests | CI | Review | Scope leak | Status / next |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FND-01 | `8e1274a8c46a14e67266a135268252c328e724c2` | `codex/fnd-01-package-boundary` | #8 | implementation `b47b01526843b1601530cc2fabc148aa2e66191f` / merge `2993820d473c84b674de1f4e11f137e89b2c04d1` | `normal`; implementer requested/actual GPT-5.6 Luna / max; reviewer requested GPT-5.6 Sol / high, actual unknown/not exposed by reviewer runtime; master requested GPT-5.6 Sol / xhigh, actual unknown/not exposed by runtime | PASS — checker; focused 13; full 589 passed, 2 skipped; Ruff; clean-install smoke; diff check | PASS — required Python 3.10–3.14, clean-install, Ruff, CodeQL, and dependency review checks | APPROVE — no BLOCKER/HIGH/MEDIUM; LOW state-head label corrected | none | MERGED / next: FND-02 |
| FND-02 | `2993820d473c84b674de1f4e11f137e89b2c04d1` | `codex/fnd-02-contract-registry` | #10 | implementation `e1ee41fd638069770c842234242265eee47ea2c8`; repaired `bc7a2e51a60a9df3ae10f45de2f32c3915fcb9e6`; merge `09bb07689483b5a3507f2b230a32b90c6dd788b6` | `high` — escalated from `normal` after reviewer found numeric-string timestamp coercion and silent extra-field loss; initial implementer requested/actual GPT-5.6 Luna / max; repair implementer requested GPT-5.6 Sol / high, actual unknown/not exposed by repair runtime; reviewer requested GPT-5.6 Sol / high, actual unknown/not exposed by reviewer runtime; master requested GPT-5.6 Sol / xhigh, actual unknown/not exposed by runtime | PASS — focused 71 on Python 3.10; productionization 85; full 661 passed, 2 skipped; checker; Ruff; repaired wheel-install smoke; diff check | PASS — required Python 3.10–3.14, clean-install, Ruff, CodeQL, and dependency review checks | APPROVE — both prior HIGH findings resolved; no remaining findings | none | MERGED / next: FND-03 |
| FND-03 | `cbd1bb7a4d57143423509debe5aa2a737c4f8a07` | `codex/fnd-03-config-observability` | #13 | RED/JIT/GREEN `190cd46e` / `ab7ab281` / `694a6a6e`; repair RED/GREEN `9985c909` / `7ec49ebe`, `f494fb07` / `27da22ce`, `dc1ff090` / `1b515315`, `98ef29ea` / `db78553c`; final head `f650ff916755f083945f4bc0fb9c216d6acc1db8`; merge `06075e4a8aba7ee21cb5d911bd41b4360e00a9dc` | `high`, escalated for secret-redaction leakage and fail-closed mode gaps; initial `normal_implementer` / `.codex/agents/normal-implementer.toml` / configured actual GPT-5.6 Luna / max; repairs `high_implementer` / `.codex/agents/high-implementer.toml` / configured actual GPT-5.6 Sol / high; final `reviewer_high` / `.codex/agents/reviewer-high.toml` / configured actual GPT-5.6 Sol / high; master GPT-5.6 Sol / xhigh | PASS — focused 125; productionization 165; full 741 passed, 2 skipped; checker; Ruff; fresh Python 3.14 wheel/import smoke; diff | PASS — ten exact-head checks; CI `33342200220`; CodeQL `33342200218`; Dependency Review `33342200321`; status `99339857169` | APPROVE — definitive artifact PR comment `#issuecomment-5472021183`; master gate `#issuecomment-5472024626`; all prior findings closed | none | MERGED / next: FND-04 |
| FND-04 | `06075e4a8aba7ee21cb5d911bd41b4360e00a9dc` | `codex/fnd-04-lock-ci-doc-gates` | #14 | RED/GREEN `e37aaff3` / `eaf04029`; interpreter/roadmap RED/GREEN `b409643b` / `06ed13ce`; Markdown/NOTICE RED/GREEN `a36e8be7` / `abf42642`; NOTICE type RED/GREEN `6fcfadd1` / `b4a7878b`; final head `cb91948ffee10cc8c32c93975c0c00d2239ab1f4`; merge `0fbd318c4421eb303b6aa090458b9e844e0416e6` | `high`, escalated for NOTICE compatibility and Markdown semantics; initial `normal_implementer` / `.codex/agents/normal-implementer.toml` / configured actual GPT-5.6 Luna / max; repairs `high_implementer` / `.codex/agents/high-implementer.toml` / configured actual GPT-5.6 Sol / high; final `reviewer_high` / `.codex/agents/reviewer-high.toml` / configured actual GPT-5.6 Sol / high; master GPT-5.6 Sol / xhigh | PASS — focused 34; productionization 199; full and locked full 775 passed, 2 skipped; uv/checkers/Ruff/diff | PASS — 11 exact-head checks; CI `33347588879`; CodeQL `33347588858`; Dependency Review `33347588862`; status `99354684326` | APPROVE — definitive artifact `#issuecomment-5472655443`; master gate `#issuecomment-5472659493`; all prior findings closed | none | MERGED / next: PIT-01 (not started) |

Recommended compact representation in agent summaries:

```text
FND-01
base: <sha>
PR: #<n>
merge: <sha-or-pending>
complexity: normal|high|critical
requested implementer: <model> / <effort>
actual implementer: <model> / <effort>
requested reviewer: <model> / <effort>
actual reviewer: <model> / <effort>
actual master: <model> / <effort>
escalation: none|<reason>
tests: PASS|FAIL|INSUFFICIENT_EVIDENCE
CI: PASS|FAIL|PENDING
review: APPROVE|REQUEST_CHANGES
scope leak: none|<summary>
next: FND-02|BLOCKED
```

If exact actual model/effort metadata is unavailable, write `unknown/not exposed by runtime`; never
copy the requested route into the actual field without evidence.

## Harness/bootstrap history

This section tracks non-roadmap harness changes so they are not confused with the 47 productionization
PR IDs.

| Item | PR | Base SHA | Purpose | Status |
| --- | --- | --- | --- | --- |
| Agent harness bootstrap | #6 | `dc9bc864fc5c1188ec4fd180950dd3a52f7bcf3c` | Add root `AGENTS.md`, autonomous workflow, and durable state | merged as `6482bf97ac78f664f4081f1ff8b9f05645b454c5` |
| Adaptive model routing | #7 | `6482bf97ac78f664f4081f1ff8b9f05645b454c5` | Add complexity-based model/effort routing and actual-model ledger fields | merged as `8e1274a8c46a14e67266a135268252c328e724c2` |
| FND-02 durable-state reconciliation | #11 | `09bb07689483b5a3507f2b230a32b90c6dd788b6` | Reconcile the FND-02 merge and next-slice stop gate | merged as `c7db5486f1c0e844164a62e41fa499b84062a838` |
| Project-scoped runtime/audit hardening | #9 | `2993820d473c84b674de1f4e11f137e89b2c04d1` | Add the Codex runtime-routing and PR-audit harness | merged as `0dc55016db0a8b972855d3e3e6b9db5f2b1a7708` |
| Python 3.14 default alignment | #12 | `0dc55016db0a8b972855d3e3e6b9db5f2b1a7708` | Pin the preferred default runtime while preserving Python `>=3.10` compatibility | merged as `cbd1bb7a4d57143423509debe5aa2a737c4f8a07` |

## Current master pre-flight evidence

- GitHub and `origin/main` were reconciled after FND-04 merge at
  `0fbd318c4421eb303b6aa090458b9e844e0416e6`.
- `.python-version` declares Python `3.14.7`; `pyproject.toml` remains `requires-python = ">=3.10"`.
- The startup shell's bare `python` was `/Users/oliver/opt/anaconda3/bin/python` 3.8.5 and was not
  used for roadmap validation. The project environment used for FND-03 is
  `/Users/oliver/Desktop/myTradingAlpha/.venv/bin/python` 3.14.6, the available local Python 3.14.x
  interpreter.
- FND-03 merged as `06075e4a8aba7ee21cb5d911bd41b4360e00a9dc`; final review and master-gate
  artifacts are PR #13 comments `#issuecomment-5472021183` and `#issuecomment-5472024626`.
- FND-04 JIT implementation spec: PR #14 body; final review and master-gate artifacts are comments
  `#issuecomment-5472655443` and `#issuecomment-5472659493`.

## Open blockers and deferred work

- No FND-03 or FND-04 blocker remains; both are merged with final exact-head evidence.
- Foundation FND-01 through FND-04 is complete as implementation/CI evidence only; this does not prove
  PIT correctness, alpha, paper readiness, or live readiness.
- Per explicit user instruction, orchestration stopped after FND-04. `PIT-01` is the next
  dependency-valid roadmap ID for information only; no branch, PR, JIT spec, or agent was started.

Agents should record unrelated technical debt here only when it materially affects a future slice. Do
not use this section as permission to widen the active PR.

## Resume protocol for a fresh master session

On startup:

1. read root `AGENTS.md` completely;
2. read this file completely;
3. fetch current `main`, roadmap PRs, and relevant CI/check state;
4. reconcile this file with actual GitHub state;
5. repair pending/stale merge, PR, status, and model-routing fields from evidence;
6. read the approved roadmap and next PR's full phase DESIGN/IMPLEMENTATION docs;
7. classify the next PR's complexity and requested routing from actual current scope;
8. continue from `next_pr_id` only after prerequisites and prior merge evidence are confirmed.

If a session terminates unexpectedly, this file plus GitHub history must be sufficient for a fresh
master to recover without relying on chat memory.

## Autonomous-mode checkpoint rules

Autonomous execution is allowed only when the user explicitly authorizes it for the master session.
When authorized and the environment provides required GitHub write/merge permissions plus fresh
subagent contexts, the master may implement, independently review, merge, refresh `main`, update this
state, and proceed to the next dependency-ordered PR without per-PR confirmation.

For each PR, autonomous mode must still:

- classify complexity;
- apply/request the corresponding model routing;
- record actual routing when exposed;
- pass independent review, required validation, required CI, and the master gate.

Autonomous mode does **not** allow the agent to waive roadmap promotion gates or approve its own
real-world trading side effects. Stop for explicit human approval when the roadmap requires
promotion/approval for paper/live broker writes, credentials, live pilot levels, or another externally
consequential gate.

The master must also stop rather than self-override for unresolved BLOCKER/HIGH findings, attributable
CI failures, material architecture conflict, missing prerequisite, unavailable merge permission,
blocking `insufficient_evidence`, or inadequate model/reviewer capability for a critical task.

A Codex environment may support fresh subagents but not creation of new user-visible UI threads. Do
not pretend to create a new UI thread when that capability is unavailable. Fresh isolated subagent
contexts satisfy implementation/review isolation; this durable state supports resume from a newly
opened master session if the top-level session ends.

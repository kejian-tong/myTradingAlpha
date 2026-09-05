# Productionization Agent State

This file is the durable, repository-tracked checkpoint for agent-driven productionization work.
It is operational state, not architecture. The approved architecture remains in
`docs/productionization/README.md`, `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`, and the
phase DESIGN/IMPLEMENTATION documents.

`AGENTS.md` defines how agents must use and maintain this file, including adaptive model routing.

## State schema

- `schema_version`: 2
- `last_reconciled_main_sha`: `62a5b5cf7393e5a83b10de69289ac72789dbd12d`
- `roadmap_status`: `sig_01_closed_replay_amendment_approved_pre_red`
- `current_pr_id`: `SIG-01` (existing PR #24 only)
- `next_pr_id`: `SIG-01` (resume existing PR after blocker resolution; do not create a duplicate)
- `current_phase`: `02-evidence-agent-boundary`
- `autonomy_mode`: `autonomous_sig_01_only_active`
- `last_completed_roadmap_pr`: `PIT-06`
- `stop_after_pr_id`: `SIG-01` (do not start SIG-02)
- `default_master_route`: `GPT-5.6 Sol / xhigh`
- `default_normal_implementer_route`: `GPT-5.6 Luna / max`
- `default_high_implementer_route`: `GPT-5.6 Luna / max`
- `default_critical_implementer_route`: `GPT-5.6 Luna / max`
- `default_reviewer_route`: `GPT-5.6 Sol / high; reviewer_xhigh / Sol xhigh when escalated`
- `high_implementation_only_route`: `high_implementer Sol/high + reviewer_high Sol/high`
- `high_review_only_route`: `normal_implementer Luna/max + reviewer_xhigh Sol/xhigh`
- `difficult_escalation_route`: `high_implementer Sol/high + reviewer_xhigh Sol/xhigh`
- `hardest_escalation_route`: `critical_implementer Sol/xhigh + fresh reviewer_xhigh Sol/xhigh`
- `active_gpt6_routes`: `none (temporarily disabled)`

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

| Task route | Implementer request | Reviewer request | Master request | Intended use |
| --- | --- | --- | --- | --- |
| `normal` | GPT-5.6 Luna / max | GPT-5.6 Sol / high | GPT-5.6 Sol / xhigh | bounded, well-specified ordinary-risk implementation |
| `high initial` | GPT-5.6 Luna / max | GPT-5.6 Sol / high | GPT-5.6 Sol / xhigh | same starting cost as normal; explicit escalation rules |
| `high implementation-only` | GPT-5.6 Sol / high | GPT-5.6 Sol / high | GPT-5.6 Sol / xhigh | implementation complexity only |
| `high review-only` | GPT-5.6 Luna / max | GPT-5.6 Sol / xhigh | GPT-5.6 Sol / xhigh | review ambiguity only |
| `critical` | GPT-5.6 Luna / max | GPT-5.6 Sol / xhigh | GPT-5.6 Sol / xhigh | critical boundary with a known implementation path |
| `difficult escalation` | GPT-5.6 Sol / high | GPT-5.6 Sol / xhigh | GPT-5.6 Sol / xhigh | implementation needs more reasoning |
| `hardest escalation` | GPT-5.6 Sol / xhigh | GPT-5.6 Sol / xhigh | GPT-5.6 Sol / xhigh | deepest approved work; fresh independent maximum Sol reasoning |

The difficult and hardest routes are optional and preserve the underlying safety class. Escalate review
from Sol/high to Sol/xhigh only as evidence requires. Review-only escalation leaves
the implementer unchanged. New routes take effect after merge and fresh session loading, not
retroactively. Prior ledger entries below retain the model/effort actually used. This routing change
is not approval of any unresolved SIG-01 architecture decision.

Normal and high intentionally share the initial route. Normal remains there unless reclassified. High
implementation complexity alone selects the Sol/high writer; review ambiguity alone selects the
Sol/xhigh reviewer; both select difficult escalation. Record the evidence before replacement.

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
| PIT-01 | `8b2a19e68322a052a3d68f4da6ec2d50fb4f7cbd` | `codex/pit-01-capture-provenance` | #18 | RED `4113a5b2ad5c6674bdc4495894da391784625f61`; GREEN `ddd68bbb364b87107be97c03688f5201cc52f26b`; repair RED/GREEN `db733f826f37f50268f21768f9f76f155ec82e69` / `db0c689887b9ac8faadc7dc072371490b1be4b74`; second repair RED/GREEN `f04aa79c905c1f2595f9b4bfadaae7f0387f4a88` / `ef0c2cdcc99551b67ffc7945937882ba12d15500`; final head `16b653b86b401c59d04c33ec138663812bbc4db2`; merge `9f706c4242825fe0c6b46fab54d559c9370c2700` | `high`; `high_implementer` / `.codex/agents/high-implementer.toml` / configured actual GPT-5.6 Sol / high; final escalated `reviewer_xhigh` / `.codex/agents/reviewer-xhigh.toml` / configured actual GPT-5.6 Sol / xhigh; master GPT-5.6 Sol / xhigh | PASS — three auditable RED stages; focused 81; productionization 280; full 856 passed, 2 skipped, 69 subtests; PIT regressions 15/41; Ruff/checkers/diff; wheel/import smoke | PASS — 11 final-state-head checks; CI `33353584557`; CodeQL `33353584567`; Dependency Review `33353584546` | APPROVE — exact-head follow-up `#issuecomment-5473302443`; Master gate `#issuecomment-5473305733`; all prior findings closed | none | MERGED / next: PIT-02 |
| PIT-02 | `9f706c4242825fe0c6b46fab54d559c9370c2700` | `codex/pit-02-bars-calendar` | #19 | RED/GREEN `56291c5eeed922ac7bc50f6a0b554ecb7cc7dcf3` / `31c4a1d327676cbbcf0395f871b9f19ba6e876d3`; repair RED/GREEN `1839270d3f67c959f7a8757375c94b4a2b09acc4` / `4ed95c5b2e8bb71b0471144f3000fac1a60875d3`; final repair RED/GREEN `33e98e07a758413d986244ee7f06b2303a66660d` / `969adfe4291c0ae613e66724cb0bffffe5c08db4`; final head `dd57e43f8b9b1659caf41db9bcf427c650ae5b3d`; merge `47f2c325e4d71a3d79c601f9f3e25eb722df3809` | `high`; `high_implementer` / `.codex/agents/high-implementer.toml` / configured actual GPT-5.6 Sol / high; final `reviewer_high` / `.codex/agents/reviewer-high.toml` / configured actual GPT-5.6 Sol / high; master GPT-5.6 Sol / xhigh | PASS — three auditable RED stages; focused 85; productionization data 166; productionization 365; legacy 44; full 941 passed, 2 skipped, 69 subtests; Ruff/checkers/diff; wheel/import | PASS — 11 final-state-head checks; CI `33356996757`; CodeQL `33356996771`; Dependency Review `33356996764` | APPROVE — exact-head follow-up `#issuecomment-5473721046`; Master gate `#issuecomment-5473724757`; all prior findings closed | none | MERGED / next: PIT-03 |
| PIT-03 | `47f2c325e4d71a3d79c601f9f3e25eb722df3809` | `codex/pit-03-financial-vintages` | #20 | RED `d496043150fbfc66655e864687d140d048737dfb`; hygiene `fecf6f0366c606f271951474e583e55bf7b25321`; GREEN `8818726cd4a9da8f0ddb92780f2fde294c489fe0`; repair RED/GREEN `55404f0ede3dbfa9d0b02510429db79766337879` / `de7208cbdc6abf1ee069fccbcfac3b21a31cbd73`; final repair RED/correction/GREEN `38d687474b74da49498de3e68d0f6ee214f2cc76` / `2b98a260cfd9bd7ee528519eefed9935f3e3703a` / `c3b07a52f5dc7eedc1f95610a9ad049326b57398`; final head `af62fbb8ebedc395aa60cfb84623ff3353f956b1`; merge `f7d96ccfc311d4e48cf32748b4645343272eeb21` | `high`; `high_implementer` / `.codex/agents/high-implementer.toml` / configured actual GPT-5.6 Sol / high; final `reviewer_high` / `.codex/agents/reviewer-high.toml` / configured actual GPT-5.6 Sol / high; master GPT-5.6 Sol / xhigh | PASS — three auditable RED stages; focused 110; productionization data 276; productionization 475; legacy 22; full 1051 passed, 2 skipped, 69 subtests; Ruff/checkers/lock/diff; wheel/import | PASS — 11 final-state-head checks; CI `33360338842`; CodeQL `33360338840`; Dependency Review `33360338875` | APPROVE — exact-head follow-up `#issuecomment-5474126220`; Master gate `#issuecomment-5474126334`; all prior findings closed | none | MERGED / next: PIT-04 |
| PIT-04 | `f7d96ccfc311d4e48cf32748b4645343272eeb21` | `codex/pit-04-events-social-macro` | #21 | RED/hygiene/GREEN `3d2a8dd8dfb1001f22ff627267b88170913f8460` / `1ff3a81265f63dbaa70f79e4eca4336644280f2f` / `68d2d0bfe0a2e18b9bff3430943f721daa9e63cb`; repair RED/GREEN `b64a32566352cdd8938d4b5c7afe0bc2bf89b62d` / `d3891ba811245fc3e505389d88e2ea13d98cc362`; final head `6753b6da4b12a08bfda43d494681d2bac1ffd658`; merge `63a167f6fa737f48a7a5525ab19384afdca9fc37` | `high`; `high_implementer` / `.codex/agents/high-implementer.toml` / configured actual GPT-5.6 Sol / high; final `reviewer_high` / `.codex/agents/reviewer-high.toml` / configured actual GPT-5.6 Sol / high; master GPT-5.6 Sol / xhigh | PASS — two RED stages; focused 111; data 387; productionization 586; legacy 61; full 1162 passed, 2 skipped, 69 subtests; Ruff/checkers/lock/diff/wheel | PASS — CI `33362962359`; CodeQL `33362962349`; Dependency Review `33362962320` | APPROVE — exact-head `#issuecomment-5474461389`; Master `#issuecomment-5474461558`; nonblocking MEDIUM test hardening deferred | none | MERGED / next: PIT-05 |
| PIT-05 | `63a167f6fa737f48a7a5525ab19384afdca9fc37` | `codex/pit-05-universe-actions` | #22 | RED/hygiene/GREEN `02305814650fedff1e5bc91dd37b4a5a61e541a7` / `955fe503ba1a9908efa54131347dd4a57bdcacfd` / `f56ebfdbfbc993bde22b834dd125cb3b891d25ab`; final head `d0ea37014258d96dc6ab75e4ec2f805f9fabc1c9`; merge `4782754746e02efb28b3078707d7c266728b0970` | `high`; `high_implementer` / `.codex/agents/high-implementer.toml` / Sol high; final `reviewer_high` / `.codex/agents/reviewer-high.toml` / Sol high; master Sol/xhigh | PASS — focused 80; data 467; productionization 666; legacy 30; full 1242 passed, 2 skipped, 69 subtests; static/lock/wheel | PASS — CI `33365435326`; CodeQL `33365435294`; Dependency Review `33365435310` | APPROVE exact-head `#issuecomment-5474785612`; Master `#issuecomment-5474785805`; nonblocking deferred findings recorded | none | MERGED / next PIT-06 |
| PIT-06 | `4782754746e02efb28b3078707d7c266728b0970` | `codex/pit-06-evidence-bundle` | #23 | RED/hygiene/GREEN `4c3c40a85d9a44b485301839b35091d93537d240` / `0fd46cad906e75ff4f635e92cfc110ab55964211` / `bbb17f25b754db59b1db401e8390adba807a1d4f`; repair RED/corrections/GREEN `986ded3f05a0099d8d7291a8e3fe4b69145cc237` / `fb92e80f259832af4e55c66b76efbab311e4e24e`,`d648809b3a2dc58f9c54640a4ede7be290694ce0` / `239c5424224187328784dfa1ffa5d139a2fb95fc`; final RED/GREEN `029be583d13b539142278f1758ed0f9da5fe6372` / `31cdd058d1189bbff0f9ae28df83d0d789f71d32`; final head `7a9340be1e8d6997d7f5dfa6ba0e36befb05b153`; merge `1a185d4035db8807c12c5070c30cfe6d2979d968` | `high`; `high_implementer` Sol/high; final escalated `reviewer_xhigh` Sol/xhigh; master Sol/xhigh | PASS — focused 54; data 521; productionization 720; regressions 15; full 1296 passed, 2 skipped, 69 subtests; static/lock/wheel | PASS — CI `33370017680`; CodeQL `33370017614`; Dependency Review `33370017652` | APPROVE `#issuecomment-5475399753`; Master MERGE `#issuecomment-5475399932` | none | MERGED; next SIG-01 |
| SIG-01 | original `1a185d4035db8807c12c5070c30cfe6d2979d968`; current main `62a5b5cf7393e5a83b10de69289ac72789dbd12d` | `codex/sig-01-research-adapter` | #24 | latest RED `2026529c`; code `3f492251dd8844af19cccc8fa00a5ad21775ac1b`; reviewed `c40c855c974fafa74bf377b522b888058b03ae51`; merge none | `high`; historical Sol/max-route reports preserved with initial-high correction; final fresh `reviewer_xhigh` configured-actual Sol/xhigh under current harness | PASS — full 1988/2 skipped, focused 746, legacy 26; RED/static/wheel verified | PASS at c40c855 — CI `33935610539`, CodeQL `33935610547`, Dependency `33935610591`; later doc-checkpoint checks in PR artifacts | REQUEST CHANGES — `#issuecomment-5548422047`; H1/H2/H3/H5/M2/M3 closed; H4/M1 open | none | BLOCKED on human runtime/date amendment; no merge; SIG-02 prohibited |

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
| Hybrid concurrent agent harness | #17 | `70e4a9af5f040c10fa13b49f3dffc9e68573b7b2` | Add read-only pre-flight/review specialist lanes while preserving serialized production writes | merged as `8b2a19e68322a052a3d68f4da6ec2d50fb4f7cbd` |
| GPT-6 Astra max-tier harness | #25 | `1a185d4035db8807c12c5070c30cfe6d2979d968` | Add Astra routing and an optional max implementation/review tier | merged as `7af14f3bba7078f78cc807885b3c169acc6b7da5` |
| Cost-balanced routing ladder | #26 | `7af14f3bba7078f78cc807885b3c169acc6b7da5` | Prospective Luna/Sol/Astra-high routes; existing loaded/historical routes preserved | merged as `9dde1955484b793c4d8dba9c62794ae85b181bcf` |
| GPT-6 routes disabled | #27 | `9dde1955484b793c4d8dba9c62794ae85b181bcf` | Current defaults use Luna/Sol only; historical routes preserved | merged as `62a5b5cf7393e5a83b10de69289ac72789dbd12d` |

## Current SIG-01 checkpoint — 2026-09-04 local run

- Existing PR #24 only; no duplicate, SIG-02 branch, RED, JIT, PR, implementation, or promotion.
  Current main `62a5b5cf7393e5a83b10de69289ac72789dbd12d`; original SIG-01 base `1a185d4035db8807c12c5070c30cfe6d2979d968`.
  PR25 was verified merged at startup. Concurrent PR26/27 harness changes were later integrated
  without production/test changes, preserving all merge parents and original RED/GREEN history.
- Harness integrations: PR25 main via `9f1d0b4614fbb77acdd14933d904d8588fd84eb9`; PR26 main via
  `55cf4381a0cb4b2c5caa4e54347e875d5866deda`; PR27 main via `c40c855c974fafa74bf377b522b888058b03ae51`.
  Current config/AGENTS/protocol/template defaults match main. Retired max/Astra role files are absent.
- Latest user steering explicitly replaced the max-review request with the current harness and
  authorized direct merge only if all gates pass. Fresh named `reviewer_xhigh` successfully loaded
  current `.codex/agents/reviewer-xhigh.toml`: configured-actual `gpt-5.6-sol / xhigh`, matching the
  runtime's fixed route. Review-only escalation was justified by concrete representation/serialization
  findings. Both production writers are stopped; only one wrote at a time. No new GPT-6 child is used.
- Historical max implementation/review configuration reports remain preserved with PR25 provenance.
  [Initial high-route correction](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5548196904):
  file requested Astra/high but exposed fixed role specified Sol/high, so actual Astra/high was not
  verified. Successful spawn/instruction matching did not settle that conflict. No old report or
  completed FND/PIT model evidence was relabeled. This running Master was not hot-switched by config.
- [Max availability failure](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5548286323)
  was resolved by the user's new route selection, not a silent fallback. A temporary untracked role
  file was removed unchanged before any further max spawn; no retired role was committed/restored.
- Durable contracts: original PR body; [bounded repair JIT](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5547525453),
  [max H5 JIT](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5547726002),
  [final repair JIT](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5548126743), and
  [current Sol review JIT](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5548348098).
  Earlier reviews, decoding refinements, matrix audit and all original/repair REDs remain in Git/PR
  history; reasons and actual/requested roles were recorded before their applicable dispatches.
- Final repair RED `2026529c9fdefcd9765dc3b14708ddea67157bfe`: test-only, 138 expected failures / 126
  passing controls against durable production. GREEN `3f492251dd8844af19cccc8fa00a5ad21775ac1b`
  changes historical.py only (56 additions / 8 deletions); tests are in the preceding commit.
  Earlier compatibility control `285ea6f` passed its durable baseline and is not falsely called RED.
- [Fresh Sol review](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5548422047)
  at `c40c855c974fafa74bf377b522b888058b03ae51`: REQUEST CHANGES. H1/H2/H3/H5/M2/M3 CLOSED for
  the selected contract. HIGH H4 remains: arbitrary host callable is not an enforced zero-egress
  runtime. MEDIUM M1 remains: trade-date horizon needs an approved rule. These are human architecture
  decisions, not model/CI issues. LOW L1 prospective reviewer_max wording is corrected in this
  checkpoint; current-harness named review is required instead.
- Independent validation at c40c855: matrix 264; focused 746; legacy 26; full 1988 passed, 2 skipped,
  27 warnings, 69 subtests in 110.19s. Original and latest repair RED independently reproduced.
  Ruff/dependency/lock/Markdown/diff and exact repaired-code offline wheel evidence passed.
  All 11 exact-c40c855 checks passed: CI `33935610539`, CodeQL `33935610547`, Dependency Review
  `33935610591`. Skipped optional Bedrock/live DeepSeek checks are not successful integrations.
- This final documentation/state correction changes no production/tests. Exact-head follow-up review,
  CI, and the final Master DO NOT MERGE artifact are recorded in the PR conversation after its commit;
  prior CI and review never approve a new SHA. SIG-01 has no merge SHA and remains open.
- The [concrete runtime/date amendment](phases/02-evidence-agent-boundary/SIG_01_AMENDMENT_PROPOSAL.md)
  is ready for human review and remains unapproved: closed sealed cached-result replay with a new
  provenance-bound contract, plus trade_date equal to the UTC cutoff date. No runtime/cache/date
  implementation, trusted-caller substitute, real model deployment, broker/paper/live gate, or
  SIG-02 work is authorized by the model-routing change or conditional merge permission.
- Resume existing SIG-01 only after the human architecture decision. Use current main's named routes,
  explicit `gh --repo kejian-tong/myTradingAlpha`, fresh current-state reconciliation, and exact-head
  gates. Stop after SIG-01 merges; do not start the next slice.

## Approved SIG-01 closed-replay implementation checkpoint

- On 2026-09-04 the user approved the reviewed closed cached-response replay and UTC cutoff-date
  amendment and instructed the Master to continue. Conditional merge authorization remains active
  after all review, CI, and Master gates pass. Scope remains existing PR #24 only; stop after SIG-01
  and do not start SIG-02.
- Exact base main remains `62a5b5cf7393e5a83b10de69289ac72789dbd12d`; current branch pre-RED
  head is `28bb74b829e240db52191340d7754aff864448fc`. PR #24 is open and cleanly mergeable. No
  duplicate PR is created. Existing FND/PIT and SIG-01 history/model evidence remains unchanged.
- The approved architecture is recorded in
  [SIG_01_AMENDMENT_PROPOSAL.md](phases/02-evidence-agent-boundary/SIG_01_AMENDMENT_PROPOSAL.md),
  Phase 02 design/implementation, the SIG-01 roadmap row, and appendices A/B before repair RED.
  EvidenceBundle and RunContext v1 fields/hashes/readers remain unchanged.
- Exact response design: a separate v1 production-owned cached-response contract, immutable selection,
  canonical byte sealer/parser, and append-only in-memory repository. Selection requires exact response
  ID/hash plus graph/model/runtime artifact IDs and hashes. The record binds bundle ID/hash, UTC cutoff,
  calendar, replay policy, variant, UTC snapshot date, ticker, instrument/asset, capture provenance,
  canonical output hash, and response hash. Repository access is exact, never implicit/latest.
- The repository stores bounded canonical UTF-8 JSON bytes. The production sealer rejects duplicate
  keys, non-finite values, opaque/custom objects, authority fields, malformed message/call records,
  excessive total bytes, depth, nodes, or string size. Capture availability must be at/before cutoff;
  archive-realistic ingestion must also be at/before cutoff. Typed missing/corrupt/mismatch/unavailable
  failures return no state/signal and have no retry, synthesis, callable, dynamic load, or fallback.
- `trade_date` is approved as exactly the canonical UTC `knowledge_cutoff` date. Reject earlier/later
  values before alias resolution or response lookup. This is a research snapshot label; it does not
  infer session/execution behavior.
- `tradingagents.graph.historical` becomes a pure cached plain-state validator/five-tier renderer. It
  accepts no bundle/context/callable/plugin/import target or object deserializer and never imports
  `mytradingalpha`. The existing production adapter remains the only reverse importer. Ordinary graph,
  CLI, setup/propagation, provider config, persistence, and existing artifacts stay compatible.
- Complexity remains `high`. Selected current-harness route is difficult escalation: sole
  `high_implementer`, `.codex/agents/high-implementer.toml`, configured `gpt-5.6-sol / high`, followed
  by fresh independent `reviewer_xhigh`, `.codex/agents/reviewer-xhigh.toml`, configured
  `gpt-5.6-sol / xhigh`. Reason: canonical hashing, temporal cutoff/provenance, bounded parsing, and
  removal of a safety-boundary callable require elevated implementation and review. This is not a
  `critical` broker/live boundary. Both names/configs are present in the current runtime catalog;
  actual loading requires successful dispatch. Master uses current Sol/xhigh policy.
- One production writer only. Repair RED rewrites callable-oriented tests to the approved response
  contract and adds a test-only canonical raw response fixture before GREEN. GREEN may add
  `mytradingalpha/research/cached_response.py`, modify the adapter/pure validator/exports/research
  namespace, and update only focused SIG-01 tests. No EvidenceToolset/ResearchNote, quant, durable
  cache storage/capture service, broker/paper/live, dependency, or SIG-02 implementation.
- Required evidence: callable API removal/static denial; exact canonical round-trip/hash/repeat;
  ID/hash/bundle/context/date/instrument/artifact/provenance/cutoff mutation denial; no file/socket/
  clock/environment/provider/subprocess/import-hook effects without monkeypatch-based confinement;
  legacy state/five-tier and ordinary graph/CLI compatibility; unchanged EvidenceBundle v1 golden
  hashes; full local validation, fresh current-harness review, exact-head CI, and Master gate.

## Current master pre-flight evidence

- Historical PR #26 harness reconciliation (superseded operationally by the current checkpoint): PR #25 merged as current main
  `7af14f3bba7078f78cc807885b3c169acc6b7da5`. The user requested a new harness-only PR that restores
  Sol for the default Master, high/critical implementers, and standard/escalated reviewers while
  retaining Luna/max for normal/high/critical work and adding explicit Sol escalation plus a final
  Astra/high review step for the hardest approved work. Astra/max is removed to control credit use.
  SIG-01 PR #24 was observed open at `9f1d0b4614fbb77acdd14933d904d8588fd84eb9` during kickoff and is
  being modified outside this isolated worktree. This task does not inspect, edit, review, merge, or
  draw a new verdict about that head. Its owning session must reconcile the latest head and evidence.

- Historical PR #25 harness reconciliation: GitHub main was `1a185d4035db8807c12c5070c30cfe6d2979d968`.
  PIT-06 PR #23 is merged. SIG-01 PR #24 remains open at `ba228571c91d17648375d574450454006b66c55b`.
  [Independent review](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5487705172)
  is REQUEST CHANGES and the
  [Master gate](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5487707009)
  is DO NOT MERGE. That task authorized an independent routing/configuration PR only and performed no
  SIG-01 code, architecture resolution, re-review, or SIG-02 work. PR #25 declared Astra routes;
  successful named-role loading remained a fresh-session requirement. This paragraph is preserved as
  historical evidence and is superseded by the current cost-balanced routing policy above.

- GitHub and `origin/main` were reconciled through post-FND-04 state PR #16 and hybrid-harness PR #17
  at `8b2a19e68322a052a3d68f4da6ec2d50fb4f7cbd`; no project PR was open before PIT-01.
- `.python-version` declares Python `3.14.7`; `pyproject.toml` remains `requires-python = ">=3.10"`.
- The startup shell's bare `python` was `/Users/oliver/opt/anaconda3/bin/python` 3.8.5 and was not
  used for roadmap validation. The project environment used for FND-03 is
  `/Users/oliver/Desktop/myTradingAlpha/.venv/bin/python` 3.14.6, the available local Python 3.14.x
  interpreter.
- FND-03 merged as `06075e4a8aba7ee21cb5d911bd41b4360e00a9dc`; final review and master-gate
  artifacts are PR #13 comments `#issuecomment-5472021183` and `#issuecomment-5472024626`.
- FND-04 JIT implementation spec: PR #14 body; final review and master-gate artifacts are comments
  `#issuecomment-5472655443` and `#issuecomment-5472659493`.
- PIT-01 hybrid pre-flight used `code_explorer`, `test_auditor`, and `boundary_reviewer` against exact
  base `8b2a19e68322a052a3d68f4da6ec2d50fb4f7cbd`; no blocking design conflict was found. PR #18 contains
  the durable JIT spec, and RED `4113a5b2ad5c6674bdc4495894da391784625f61` is test/fixture-only with
  the expected missing-module failure. Two review/repair cycles added test-first checksum, path,
  independent-writer, and in-flight binding hardening. Implementation head `ef0c2cdc` passed all local
  validation. State-only final head `16b653b8` passed exact-head CI and escalated review, and PIT-01
  merged as `9f706c4242825fe0c6b46fab54d559c9370c2700`; PR #18 exact-head review and Master artifacts are
  `#issuecomment-5473302443` and `#issuecomment-5473305733`.
- PIT-02 hybrid pre-flight used the three read-only specialist lanes against exact base `9f706c4` and
  found no blocking design conflict. PR #19 contains the durable JIT spec; RED `56291c5e` is
  test/fixture-only with the expected missing-module failure. Two review/repair cycles added complete
  classified coverage windows, true session-distance staleness, explicit finality, isolated
  adjustment/revision evidence, and canonical coverage ranges. Implementation head `969adfe4` passed
  local validation. State-only final head `dd57e43f` passed exact-head CI and review, and PIT-02 merged
  as `47f2c325e4d71a3d79c601f9f3e25eb722df3809`; PR #19 exact-head review and Master artifacts are
  `#issuecomment-5473721046` and `#issuecomment-5473724757`.
- PIT-03 pre-flight used two read-only specialist lanes plus Master boundary synthesis against exact
  base `47f2c32`; a stale runtime thread prevented the optional third specialist spawn but did not
  affect the required implementer/reviewer roles. PR #20 contains the durable JIT spec; RED `d4960431`
  is test/fixture-only with the expected missing-module failure. Two review/repair cycles added strict
  fiscal/event chronology, complete fiscal interval identity, concrete selector revalidation, and
  malformed query handling. Implementation head `c3b07a52` passed local validation, exact-head CI,
  and `reviewer_high` APPROVE. State-only final head `af62fbb8` passed exact-head CI/review and PIT-03
  merged as `f7d96ccf`; review and Master artifacts are `#issuecomment-5474126220` and
  `#issuecomment-5474126334`.

## Open blockers and deferred work

- No FND-03 or FND-04 blocker remains; both are merged with final exact-head evidence.
- Foundation FND-01 through FND-04 is complete as implementation/CI evidence only; this does not prove
  PIT correctness, alpha, paper readiness, or live readiness.
- PIT-01 through PIT-06 are merged. Fresh Sol review closed SIG-01 H1/H2/H3/H5/M2/M3. H4 remains
  HIGH for unenforced host runtime capabilities; M1 remains an unapproved date/horizon decision.
  The current user changed reviewer routing and permits merge only after every gate passes; that
  does not approve the runtime/date architecture amendment. Master must not merge or implement
  dependent runtime/cache/date changes before human resolution. SIG-02 remains out of scope.
- PIT-06 trusted-input boundary: bundle/domain APIs require concrete validated project models. Hostile
  subclasses overriding `model_dump()` are a nonblocking future hardening item before exposing these
  constructors outside the trusted in-process contract; exact repository and RunContext subclasses
  are already denied at replay boundaries.

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

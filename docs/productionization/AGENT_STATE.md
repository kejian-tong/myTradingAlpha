# Productionization Agent State

This file is the durable, repository-tracked checkpoint for agent-driven productionization work.
It is operational state, not architecture. The approved architecture remains in
`docs/productionization/README.md`, `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`, and the
phase DESIGN/IMPLEMENTATION documents.

`AGENTS.md` defines how agents must use and maintain this file, including adaptive model routing.

## State schema

- `schema_version`: 2
- `last_reconciled_main_sha`: `9dde1955484b793c4d8dba9c62794ae85b181bcf`
- `roadmap_status`: `sig_01_repaired_pending_final_review_human_architecture_blocked`
- `current_pr_id`: `SIG-01` (existing PR #24 only)
- `next_pr_id`: `SIG-01` (resume existing PR after blocker resolution; do not create a duplicate)
- `current_phase`: `02-evidence-agent-boundary`
- `autonomy_mode`: `autonomous_sig_01_only_no_merge_until_all_gates_pass`
- `last_completed_roadmap_pr`: `PIT-06`
- `default_master_route`: `GPT-5.6 Sol / xhigh`
- `default_normal_implementer_route`: `GPT-5.6 Luna / max`
- `default_high_implementer_route`: `GPT-5.6 Luna / max`
- `default_critical_implementer_route`: `GPT-5.6 Luna / max`
- `default_reviewer_route`: `GPT-5.6 Sol / high; reviewer_xhigh / Sol xhigh when escalated`
- `high_implementation_only_route`: `high_implementer Sol/high + reviewer_high Sol/high`
- `high_review_only_route`: `normal_implementer Luna/max + reviewer_xhigh Sol/xhigh`
- `difficult_escalation_route`: `high_implementer Sol/high + reviewer_xhigh Sol/xhigh`
- `hardest_escalation_route`: `critical_implementer Sol/xhigh + reviewer_astra_high GPT-6 Astra/high`

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
| `hardest escalation` | GPT-5.6 Sol / xhigh | GPT-6 Astra / high | GPT-5.6 Sol / xhigh | deepest approved work; stronger independent reviewer |

The difficult and hardest routes are optional and preserve the underlying safety class. Escalate review
through Sol/high, Sol/xhigh, then Astra/high only as evidence requires. Review-only escalation leaves
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
| SIG-01 | `1a185d4035db8807c12c5070c30cfe6d2979d968` | `codex/sig-01-research-adapter` | #24 | reviewed head `ba228571c91d17648375d574450454006b66c55b`; merge pending | `high`; prior `high_implementer` / Sol high; prior `reviewer_high` / Sol high; prior Master / Sol xhigh (historical routes, not relabeled by this upgrade) | recorded PASS — focused 55, productionization 775, full 1351/2 skipped; RED histories independently verified | recorded PASS — `33460701725`, CodeQL `33460701701`, Dependency Review `33460701670` at the reviewed head | REQUEST CHANGES `#issuecomment-5487705172`; Master DO NOT MERGE `#issuecomment-5487707009` | none reported | BLOCKED on findings and human architecture decision; resume existing SIG-01 only |

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

## Current SIG-01 resume checkpoint — 2026-09-04

- Scope: complete existing PR #24 only; no duplicate PR and no SIG-02 branch, RED, JIT, PR, or
  implementation. Original base `1a185d4035db8807c12c5070c30cfe6d2979d968`; startup main
  `7af14f3bba7078f78cc807885b3c169acc6b7da5` from PR #25. Latest main is now
  `9dde1955484b793c4d8dba9c62794ae85b181bcf` from concurrently merged harness PR #26.
- Startup checkout was clean on PR #25 main and the runtime exposed named max roles. Full
  activation of the upgraded high-implementer model route was not established; see correction below.
  Merge `9f1d0b4614fbb77acdd14933d904d8588fd84eb9` integrated main into the existing branch,
  preserving parent `ba228571c91d17648375d574450454006b66c55b` and all original RED/GREEN history.
  Only state conflicted; main's harness and later REQUEST CHANGES / DO NOT MERGE evidence won.
- Historical original RED/GREEN: `6d4327c7e83189c7f2faae57eb0d97c24e0858d1` /
  `04c2dd6dc7abd383335e536a29d356fc179aec33`; original repair `c5178e3eaaa2d1be85defdc8239aa5d8d35892e6`
  / `6edc92b22cd94b402bb542683aa68039c9ecea36`. Historical Sol/high implementation/review and
  Sol/xhigh Master labels remain unchanged; completed FND/PIT ledger rows match main exactly.
- Fresh named loading succeeded for `reviewer_max` (initial and subsequent independent contexts),
  `high_implementer`, and final `max_implementer`, with loaded instructions matching their files.
  Max routes were reported as configured `gpt-6-astra / max`. Initial repairs requested Astra/high
  from the file but the runtime-exposed fixed `high_implementer` route is Sol/high; the earlier
  actual-Astra/high claim is not verified and is corrected below. Master requested/configured
  `gpt-6-astra / xhigh`; no hot switch to newer on-disk defaults is claimed.
  No additional backend telemetry is claimed. Both writers have stopped; only one ran at a time.
- Complexity remains `high`; `execution_tier: max` now covers implementation and fresh independent
  review. Initial review-only escalation adjudicated runtime/temporal ambiguity; implementation
  escalation followed repeated concrete gaps across message representations, encoded/normalized
  arguments, and normalization shadowing. Reasons and affected roles were recorded before dispatch
  in state commits and JITs; stronger routing never clears a human gate.
- Durable JITs: [resume](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5547417305),
  [independent repairs](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5547525453),
  [argument refinement](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5547575426),
  [max H5](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5547726002).
- Preserved fresh reviews: [9f1d0b4](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5547521216)
  confirmed H1–H5/M1; [f119f28](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5547725878)
  CLOSED H1/H2/H3, retained H5/H4/M1; the
  [read-only matrix](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5547794895)
  supplied additional concrete H5 cases without acting as final approval.
- Initial repair REDs: `bb30bd129ee471e9d5066fd257464291139431b0` (19 fail / 130 pass),
  `192bba8295f8e1d234cbe5d1195ff468815e1a57` (9 fail / 4 pass),
  `8958453a53cc0ba7b2955c29cb0f6dac21205746` (8 fail). GREEN
  `9e3875035d585c77e8d2632ad08e94b161521232` repaired H1/H2/H3 and part of H5.
- Max H5 REDs: `25d5c733f2d4d3aa865d06612e347b5d7cadab02` (215 fail / 59 pass),
  `3368421ec3c9f5e8114da50cbe63e061b762175c` (15 fail / 1 pass),
  `89846c482ae50b904bba8ae0dbe93a039ad7e843` (18 fail). All were test-only and pushed before GREEN;
  isolated archives excluded production WIP. Compatibility controls
  `285ea6f798d0ff0e10ae0af82c37f595ed9e3e31` passed on durable baseline and exposed 4 WIP failures;
  they are not falsely labeled failing baseline RED.
- Final H5 GREEN `d96797e987eaf1b78d5f4b39eb672e7e7646bfc3`; documentation-only clarification
  `76b40a8e381519b172f23ae4838f9cbcff59297c` explicitly denies runtime-isolation guarantees.
  Only historical.py and the adapter repair tests changed in the max writer's scope.
- Executed final behavioral validation: focused 482, legacy 26, productionization 1148; full 1724
  passed, 2 skipped, 27 warnings, 69 subtests in 104.50s. Ruff/dependency/lock/Markdown/diff/import
  checks passed. Exact 76b40a8 wheel was built/installed offline in a fresh environment with source
  hashes, imports/signatures, guard denial and malicious/benign message smoke verified.
- [Independent 379c30a review](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5548090259)
  retained HIGH H5 for `non_standard.value`, MEDIUM M2 nonfinite arguments and M3 call-content record
  shapes. H1/H2/H3 remain CLOSED; H4/M1 remain open. It independently passed focused 508, full 1724,
  all original/repair REDs and a clean wheel. Candidate CI was absent because the new main conflicted.
  Previous f119f28 CI (`33929795577`, `33929795487`, `33929795612`) remains historical only.
- H4 remains HIGH: arbitrary callable execution does not enforce zero egress. M1 remains a human
  date/horizon decision. The [amendment proposal](phases/02-evidence-agent-boundary/SIG_01_AMENDMENT_PROPOSAL.md)
  recommends closed cached-result replay and a UTC cutoff-date label, both unapproved. No runtime,
  cache schema, or horizon implementation occurred. Master remains DO NOT MERGE; SIG-01 is unmerged.
- Resume with explicit repository selection in GitHub commands (`--repo kejian-tong/myTradingAlpha`);
  implicit `gh` may select upstream. GitHub/current main and latest exact-head PR artifacts remain
  authoritative. No H4/M1 dependent implementation before the user approves the concrete amendment.

## Concurrent harness reconciliation and final bounded repair

- PR #26 merged at `2026-09-04T23:48:46Z`, main `9dde1955484b793c4d8dba9c62794ae85b181bcf`.
  It changes harness/state only and removes max role files in favor of the cost-balanced ladder.
  Current main's config/AGENTS/protocol/template changes are integrated intact; no retired max file
  is restored. State conflict resolution preserves latest SIG-01 evidence and current default routes.
- The active Master session loaded the PR #25 role catalog before this integration. Its actual
  Astra routes, successful named spawns, and max implementation/reviews remain factual historical
  evidence. Config sources for those routes are `.codex/agents/*` at `7af14f3`, not the changed/removed
  paths on new main. This session does not claim to have hot-loaded PR #26 defaults.
- The current user explicitly selected max implementation/review for this SIG-01 run. A retained
  loaded max writer may complete the narrow remaining H5/M2/M3 corrections; one writer only.
  A fresh independent reviewer is still mandatory after production repair. Requested `reviewer_max`
  must actually be available in the session-registered catalog, with its source/config provenance
  recorded, or review evidence remains insufficient. Future fresh Masters use current main's new
  defaults and verify their named-role availability; historical evidence is never relabeled.
- Remaining independent repair scope: recurse original content validation through non_standard.value
  and nested wrappers; reject nonfinite decoded/normalized argument numbers; validate supported
  content-call record fields/types consistent with current schemas. Add focused repair RED before
  GREEN; retain benign data, nullable/chunk compatibility and all previous tests. Only historical.py
  and the existing adapter repair tests may change. H4/M1 dependent implementation stays prohibited.

## Final bounded repair evidence and routing correction

- [379c30a review](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5548090259)
  and [final repair JIT](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5548126743)
  define remaining H5 wrapper and M2/M3 data-shape corrections; H4/M1 are excluded human decisions.
- Latest main `9dde195` integrated via `55cf4381a0cb4b2c5caa4e54347e875d5866deda` with no
  production/test changes. CI restarted and all 11 checks passed at that integration head.
- Repair RED `2026529c9fdefcd9765dc3b14708ddea67157bfe`: test-only, 138 expected failures and
  126 passing controls on unchanged durable production. GREEN
  `3f492251dd8844af19cccc8fa00a5ad21775ac1b`: 56 added / 8 removed production lines in historical.py.
  Only that module and existing repair tests changed. Writer is stopped on a clean pushed head.
- Executed final validation: new matrix 264; focused 746; legacy 26; productionization 1412;
  full 1988 passed, 2 skipped, 27 warnings, 69 subtests in 115.22s. Ruff/dependency/lock/Markdown/
  base diff/import checks and a fresh offline exact-head wheel with source hashes and installed
  guard/wrapper/finite-number/record/compatibility smoke passed. H5/M2/M3 are locally repaired;
  fresh independent closure and final-head CI remain required at this checkpoint.
- [Routing correction](https://github.com/kejian-tong/myTradingAlpha/pull/24#issuecomment-5548196904):
  the initial high_implementer on-disk PR25 file requested Astra/high, while the runtime's fixed-role
  definition specifies Sol/high. Successful spawn plus matching instruction text did not settle
  that conflict; do not claim verified actual Astra/high. Earlier reports are preserved but their
  file-based actual-route assertion is superseded. No completed historical PR is relabeled.
- Retained max writer/review contexts report their PR25 configured route, with source at `7af14f3`;
  there is no contrary fixed-model declaration for those max roles in the exposed catalog. No extra
  backend attestation is claimed. The final fresh named review must explicitly select
  `gpt-6-astra / max` through tool controls and record actual loading/provenance. If unavailable,
  mark insufficient evidence; do not use a generic substitute or restore retired configs.
- Requested route remains the user's explicit max selection for this active SIG-01 run. Future
  fresh Master defaults are PR26's ladder. H4/M1 remain open; no cached runtime, horizon rule,
  trust attestation replacement, broker/paper/live promotion, or SIG-02 work is authorized.

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
- PIT-01 through PIT-06 are merged. H1/H2/H3 are independently closed on SIG-01. H5 wrapped
  content plus M2/M3 data-shape corrections have local repair evidence pending final independent
  closure; H4 enforced runtime and M1 horizon require human approval of the concrete amendment. No attestation substitution or SIG-02 work is
  authorized. Latest exact-head artifacts, not older green checks or provisional local claims,
  control disposition. SIG-01 remains unmerged.
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

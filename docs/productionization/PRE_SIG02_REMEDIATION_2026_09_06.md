# Pre-SIG-02 Remediation: Verified Repairs and Recovery Record

Date: 2026-09-06 UTC. Scope: bounded audit remediation, not SIG-02 implementation.
Publication and final readback: [PR #39](https://github.com/kejian-tong/myTradingAlpha/pull/39).

## Independent audit supersession, 2026-09-06

This section supersedes the readiness and current-fact conclusions in the original #28-#39 report
below; it does not rewrite that report's authentic historical claims, RED/GREEN evidence, withdrawals
or scope. A later successful repair does not retroactively make an earlier statement correct.

The independent audit froze current-state review at successive immutable mains and completed the
confirmed repair queue through product-code main
`b1f019c498cb84d630fc923447b0d41e7bfcb0dc` (tree
`03d185859827d9f8013f6f1744fef3f191a2aad0`). The following defects were independently reproduced,
repaired in serial PRs, reviewed again at their final heads, merged with expected-head protection and
verified by post-push checks:

| Finding | Repair | Current disposition |
| --- | --- | --- |
| AUD-H03 closed replay imported ordinary runtime/provider paths and could mutate dotenv, warnings or socket state | PR #40 | Merged and verified; closed import/first-call path is pure while public ordinary imports retain dotenv precedence |
| AUD-H02 malformed sibling execution carriers were accepted in historical response representations | PR #41 | Merged and verified; carrier placement fails closed at validator, builder, correctly rehashed parser and repository boundaries |
| AUD-H01 common secret aliases, nested assignments and exception text could enter logs | PR #42 | Merged and verified after an independent REQUEST CHANGES; finite alias grammar covers structured/text/exception surfaces without generic substring matching |
| AUD-M01 bounded dependency analysis missed or misclassified NamedExpr, IfExp, try, loop, with, comprehension and mandatory break/finally paths | PR #43 | Merged and verified after multiple independent REQUEST CHANGES; Python 3.10-3.14 and exact break/finalizer semantics pass within the documented bounded analyzer |
| AUD-M02 Markdown/TOML language guard could reject hypothetical future localized data | No code change | Falsified as a current tracked-file defect: no legitimate current Markdown/TOML artifact is rejected; add a schema-qualified data marker only when a real artifact requires it |
| AUD-L01 stale/false operational evidence, including the claimed PR #39 conversation receipt | This final two-file reconciliation | PR #39 has zero issue comments and zero review objects; its immutable GitHub PR/commit/workflow records are the receipt |

PR #39's actual final head is `bb79a13e0bca1f498b14e584d852e72a46e5d658`, its merge is
`c02243ea25cb3e1be4c302c10b2e447a587604b2`, and both share tree
`8917ad6a156a7b45df450fd3fe157e43d96d1d7f`. Candidate CI/CodeQL/Dependency Review
`34006302600` / `34006302440` / `34006302913` and main-push CI/CodeQL
`34006575330` / `34006575329` passed. These immutable records correct the missing conversation
receipt; no historical comment or review was fabricated.

| PR | Final head | Actual merge | Candidate CI / CodeQL / Dependency Review | Main-push CI / CodeQL |
| --- | --- | --- | --- | --- |
| #40 | `7b566757ddcbe45d8b8f2f90d1c37699abeca74b` | `ca61fdc020bfa95e67a19fa518ee6427abde651a` | `34042663314` / `34042663311` / `34042663317` | `34043061438` / `34043061463` |
| #41 | `b35c83a5f742ccbc869ef2945ca422c3cc716767` | `56ee0a5d0a0633b8ae17b4095e7063d93f5da268` | `34044170605` / `34044170589` / `34044170583` | `34044607182` / `34044607180` |
| #42 | `0afae2986a1772897c939b20670d9a7353d142e4` | `5240885ebe15132b11fca17ccbf175c180675b9b` | `34050312728` / `34050312642` / `34050312669` | `34050719401` / `34050719320` |
| #43 | `20370f67c601f5dbd5693830a7805f5919f73fc4` | `b1f019c498cb84d630fc923447b0d41e7bfcb0dc` | `34054706215` / `34054706207` / `34054706271` | `34055267326` / `34055267342` |

The #28-#39 waiver and self-verification description below remain historical and expired. PRs
#40-#43 used a loaded `high_implementer` configured actual Sol/high and a separate
`reviewer_xhigh` configured actual Sol/xhigh, followed by a Master gate. No separately exposed backend
telemetry is claimed, and the comments containing those artifacts are evidence indexes rather than
formal GitHub review objects.

**Superseding SIG-02 decision:** after this reconciliation passes its own exact-head review and CI and
is merged, SIG-02 development may begin in a fresh, separately authorized JIT session. This decision
does not authorize merging SIG-02, autonomous continuation, or any later roadmap slice. SIG-02 must
retain domain-qualified evidence references, citation referential integrity distinct from semantic
support, immutable access, source/model/time provenance, deterministic note serialization, redaction,
safe rendering of untrusted content, and the narrow SIG-01 scope-test migration required for its new
files.

**Research/replay empirical assurance remains NO.** The repairs validate deterministic software and
closed synthetic replay contracts. This software evidence does not establish source authenticity,
real historical availability, real model inference, training-knowledge isolation, elapsed trials,
statistical alpha or deployable performance.

**Permission to merge future SIG-02 remains NO.** Its own final head needs independent review,
required CI and a Master gate under fresh authorization.

**PAPER/live promotion remains NO-GO.** No provider/broker operation, real order, deployment, forward
trial or human promotion gate was performed or approved.

The original report begins below and is retained for historical traceability.

## Decision and closure boundary

The six confirmed post-remediation code/document defects listed below have merged repairs in
PRs #33–#35, #37 and #38. The English-only authoring requirement is merged in #36. This publication
repairs the remaining operational checkpoint lag, STATE-01, without changing product code or policy.
Its own final head, merge SHA/time, resulting main/tree and post-merge workflows belong in the
publication PR's exact-version gate and readback, not in a self-referential follow-up commit.
A draft, pending check or unsuccessful merge is not closure.

**SIG-02 development readiness: GO for a separately authorized, narrowly scoped implementation
session after the publication gate passes.** No confirmed unresolved defect in this repair register
requires changing the approved SIG-01 contract first. The new session must refresh main, prepare its
JIT scope, use the normal harness review/routing requirements, and implement only the pure evidence,
citation, rendering and ResearchNote boundary. This is neither permission to resume autonomously nor
an assertion that every repository line has been semantically audited. Reading and verification gaps
are recorded below and remain gaps, not silently passed gates.

**Research/replay assurance:** the existing sealed, offline replay mechanics and regression suite are
validated at the cited versions. Real capture authenticity, historical availability, model inference,
independent trial/seed evidence and alpha are not established by those tests.

**PAPER/live promotion: NO-GO.** No real provider or broker integration, elapsed forward operation,
order execution, deployment or human promotion gate was performed or approved by this batch.

## Correcting the evidence record

The original claim that PR #31 was green and merged while its head was still test-only RED remains
[withdrawn](https://github.com/kejian-tong/myTradingAlpha/pull/31#issuecomment-5554253842). Its later
actual merge does not make that earlier statement true. The separate subsequent chat summaries saying
that no writes had completed, FRESH-01 was unfixed, and the English harness rule was absent were also
incorrect. Fresh GitHub reads established that #33–#36 were merged and #37 was the remaining draft.
They were not recreated. This recovery completed #37, discovered and repaired FRESH-03 in #38, and
reconciles the record here. Original RED commits, failed runs, reviews and withdrawals remain intact.

Author comments are evidence indexes, not independent verification. GitHub PR state, branch refs,
commit parents/trees, workflow records and original job logs are the underlying evidence. The owner's
explicit reviewer waiver applies only to this bounded repair batch. All gates were self-verification;
no independent APPROVE, named-agent spawn, model switch or branch-protection bypass is claimed.

## Reproducible baselines and environment

| Snapshot | Full commit SHA | Tree SHA | Meaning |
| --- | --- | --- | --- |
| Historical corrected reference | `b6ce5a3faaf7fe7d35e760d8a7d7be7c79f8d5d3` | `784de8212db2d71e95a63c6e5e7cfc3dccbbfc79` | Previous batch reference, not assumed current main |
| Recovery initial main | `c8ed290b74549d3c373e97f772eda5ed9c2dc157` | `ada50f841c4c099a4b0fc2c25feb8d21bc433756` | Fixed snapshot independently read after the 2026-09-06 authorization |
| Verified #37 main | `9078921d7fd071183b53dda6f53e17b6601f93c7` | `7b05deb2b720c5c273faea2d2a3c2cae201024bd` | Documentation repair, post-merge CI/CodeQL passed |
| Verified #38 code main | `58b7d1bf02d21f19c9efdcd10f6705559dd9ebd9` | `c66a7a7e72cfc7a19c48126757daf1cd4c5c7295` | Last product-code change; base of this publication |

Remote: `https://github.com/kejian-tong/myTradingAlpha`. Read/write operations used the connected
GitHub API. Source was read at fixed commits. No unrelated main movement was observed between the
serial gates. The publication branch is `codex/pre-sig02-recovery-evidence`; its source base is the
verified #38 main. The earlier unused `codex/pre-sig02-recovery-checkpoint` branch stayed at #37's
base without remote file edits or a PR when the runtime repair took priority.

Local workspace: `/mnt/data/pre_sig02_20260906/`. This is an **isolated partial reconstruction**, not
a complete latest-main checkout. The supplied archive is the older SIG-01 snapshot
`a614b8a27c6a822477235304f4749dc9c8163165`; unchanged files were compared by Git blob identity where
used. Local git indexes were used only for scoped diff checks; no user worktree was reset, cleaned,
stashed or overwritten. Container GitHub DNS prevented a complete clone. Local Python 3.13.5 and
available libraries are supplemental, not the locked project environment. No lock was regenerated or
dependency silently upgraded to work around this limitation.

Available capabilities used: GitHub reads/writes and Actions results, local filesystem/Python/git,
and official documentation browsing. The selected chat runtime performed the work; independent
backend reasoning telemetry and successfully loaded Codex named roles were not available. Root and
nested instruction files were inspected as repository instructions, not claimed automatically loaded
by a Codex subprocess. GitHub Actions used complete checkouts and the existing locked environment.

## Findings register and minimum repairs

Statuses below are CONFIRMED, except the explicitly falsified compatibility hypothesis. Severity uses
the repository's BLOCKER/HIGH/MEDIUM/LOW/NIT scale. None of these repairs changes persisted versions,
approved cutoff semantics or externally consequential promotion authority. Rollback is a new reviewed
PR preserving sealed artifacts and historical evidence, never a reset, force-push or weaker test.

| ID / class / severity | Affected full SHA | Evidence, expected versus actual behavior, repair and acceptance | Disposition |
| --- | --- | --- | --- |
| N01 / runtime / MEDIUM | `b6ce5a3faaf7fe7d35e760d8a7d7be7c79f8d5d3` | `contracts/common.py::_utc_datetime`: extreme offset conversion leaked OverflowError instead of the established validation error. #33 maps normalization overflow to ValueError; valid UTC extrema and microseconds remain controls. Existing validation already rejected the input; the defect was classification. | Fixed in #33; current full suite regressed |
| N03 / runtime / MEDIUM | `b6ce5a3faaf7fe7d35e760d8a7d7be7c79f8d5d3` | `data/raw_store.py::_decode_manifest` and `research/cached_response.py::parse_cached_graph_response`: deeply nested malformed JSON could leak decoder RecursionError. #33 maps it to the existing corruption errors, preserving canonical rejection and legitimate round trips. Decoder behavior differs by Python version; not every version is claimed to raise RecursionError. | Fixed in #33; current full suite regressed |
| N02 / validation tooling / MEDIUM | `07c63438e976f6a5a05586f7570a35443cdedac0` | `scripts/check_dependency_direction.py`, annotation visitors: annotation expressions and binding/shadowing differed from supported lexical semantics. #34 checks module/class/signature expressions, preserves bare annotations' existing values, and does not treat local variable annotations as runtime calls. Negative cases and scope controls retained. | Fixed in #34; current full suite regressed |
| FRESH-01 / validation tooling / MEDIUM | `3c42ac939c57c33df10c29f9fce07e7215fd1399` | `_DynamicImports.visit_Assign/visit_AnnAssign`: `items[load("tradingagents.graph")] = None` in a forbidden domain was missed because only the RHS was traversed. #35 checks target expressions in evaluation order, including nested targets, and preserves aliases/local shadowing. Recognized unresolved loaders request manual review. Twenty-six added cases include non-execution and legitimate imports. | Fixed in #35; not a demonstrated product dependency violation |
| LANG-01 / explicit owner requirement / LOW | `1e522e49d181633499e3077ce3350f3a2548f25a` | README previously permitted explanatory Chinese prose. #36 adds root `AGENTS.md` language policy, translates four explanatory lines and adds twelve regression/control cases. All engineering docs, notes, comments, docstrings, commit and PR prose must be English regardless of prompt language. Product localization, identifiers and original immutable evidence are not engineering commentary. | Implemented and merged in #36 |
| FRESH-02 / documentation / MEDIUM | `c8ed290b74549d3c373e97f772eda5ed9c2dc157` | Shared handoff prose wrongly imposed ingestion cutoff on both response policies; overviews also described embedded responses, concrete message objects and a stale package/capture boundary. #37 restores the approved policy-specific rule and separate plain-data response boundary. Eight timing cases execute through the real sealer/parser; message-object denial and stale-prose checks supplement them. | Fixed in #37; actual merge and push checks verified |
| FRESH-03 / runtime / MEDIUM | `9078921d7fd071183b53dda6f53e17b6601f93c7` | `tradingagents/graph/historical.py::_validate_content_block`, former lines 333–341: list/object `type` values passed the plain-data check but leaked unhashable TypeError at set membership. #38 validates the optional discriminator first. Twelve malformed direct/wrapped cases cover validator, sealer and parser; twelve controls preserve text, extension-string, absent and null selectors. Parser fixtures have correct canonical hashes so the actual output boundary is exercised. | Fixed in #38; actual merge and push checks verified |
| STATE-01 / operational lag / LOW | `58b7d1bf02d21f19c9efdcd10f6705559dd9ebd9` | `AGENT_STATE.md` still named #30 as reconciled main and #31 as pending. Current facts require the actual heads/merges through #38 while retaining withdrawn history and stopped roadmap status. One-shot factual specification: old state 3 pass/9 fail; repaired state 12 pass/0 fail. This is not a product state-machine bug. | Repaired by this publication; final gate/readback in #39 |

All product paths above are under `mytradingalpha/` unless explicitly prefixed otherwise. Original
findings' broader evidence is retained in the linked PRs rather than reclassified as newly executed
work. Six defect repairs plus LANG-01 and STATE-01 form eight tracked post-remediation work items;
A01–A12 are the original audit categories, not twelve additional new defects. No blocked architecture
proposal is labeled fixed. The only remaining completion gate for this publication is its own exact
candidate and actual post-merge verification; the source report does not invent that future result.

For FRESH-01, FRESH-02 and FRESH-03, the repair queue was a pre-SIG-02 completion blocker until its
specific regression and merge gates passed. Their fixes depend only on the already merged
Foundation/PIT/SIG-01 baseline. STATE-01 repairs recovery ambiguity, not a runtime prerequisite.
The source-level protections already rejected malformed historical output or prohibited later-scope
operations; no new evidence demonstrated code execution, network escape or order authority.

## A01–A12 recheck and architectural traceability

| Original category | Source/design-to-test assessment and disposition |
| --- | --- |
| A01 logging ownership/redaction | `ops/logging.py` rejects unsupported pre-existing handlers before reconfiguration, uses owned formatting and disables propagation. Repeated legitimate configuration and secret-redaction controls remain. This supported configuration boundary is not protection against a caller already executing arbitrary Python or adding handlers later. Original fix retained; no new confirmed logging defect in the reviewed path. |
| A02 PIT precision | UTC strings retain one-to-six fractional digits; excess precision is rejected rather than truncated across a cutoff. #33 adds typed overflow handling. Approved SIG-01 trade date remains the canonical UTC cutoff date, not a retroactively imposed session clock. |
| A03 authority-field aliases | The finite reserved namespace normalizes case, underscores and hyphens; plain nested metadata and decoded call arguments are checked. Unknown executable/opaque objects are rejected before serialization. #38 closes the adjacent content-discriminator error leak without granting new authority. |
| A04 ambient credentials | Default pytest replaces relevant provider keys with placeholders; marked real integration requires explicit opt-in and a real key. This prevents implicit provider selection, but placeholders/markers are not OS-level isolation. Complete collection and arbitrary future unmarked tests are not proven network-safe by this mechanism. |
| A05 installed-origin smoke | Actual #37/#38 smoke logs show non-editable locked installation, an external temporary cwd, Python `-I` and ten imports from the installed venv's site-packages. Checkout import shadowing is no longer the test's success path. |
| A06 dependency checker | #32 lexical-scope/branch repairs and #34/#35 annotation/target repairs are present. The checker recognizes bounded literal loaders and reports recognized unresolved loaders for review. It is not a general Python interpreter, reflection solver or runtime sandbox. |
| A07 harness/roles/skills | Root policy, role files and the offline harness checker distinguish requested, configured, loaded configured-actual and independent telemetry. Ordinary model routing and review rules are unchanged. Current official configuration guidance supports the inspected custom-role TOML shape; lack of extra telemetry does not invalidate genuine historical loaded-role evidence. No current named-role launch is claimed. |
| A08 future fill accounting | Shared contracts and Phases 03/05 distinguish all-in currency/share fill price, incremental explicit currency fees, and attribution that must not be debited twice. Decimal buy/sell and 2/3/5 partial-fill examples preserve fee-once and NAV identities. Design clarified; future ledger/cost code is not claimed implemented. |
| A09 future OMS | Shared contracts and Phase 07 permit Partial-to-Partial for distinct fills; identical event IDs/payloads are idempotent, conflicting duplicates halt investigation, cumulative quantities are monotonic and late facts are reconciled. Unknown ACK is query-only recovery, not blind resubmission. Broker normalization and atomic ledger/outbox behavior remain future implementation acceptance. |
| A10 capture timing/handoff | #37 corrects remaining contradiction against the approved amendment. Availability is required by cutoff in both policies; ingestion cutoff is additional for archive-realistic replay. The later pre-close freeze schedule cannot include the current closing bar or backdate late inference. EXP software fixtures do not imply real trials; model-free variants require no model response. |
| A11 cross-phase ownership | First-use shared wire owners, existing domain contracts, quant VariantRegistry versus ExperimentRegistry, stable `backtest.costs` facade and genuinely optional optimizer gates remain distinguished. There is no requirement to implement later modules merely to close documentation review. |
| A12 actual/planned/state | #37 fixes overview drift; this publication restores actual recovery facts. Historical reviews retain their original verdicts and dates. Current implemented behavior is not inferred from a proposal filename or `next_pr_id`; stopped roadmap and separate promotion gates remain explicit. |

The implemented flow is exact evidence/context binding in `HistoricalDataGuard.replay_bound`, sealed
alias/instrument resolution, exact cached response ID/hash plus calendar/variant/graph/model/runtime
bindings, and the plain-data historical validator returning defensive legacy state and a five-tier
string. The adapter does not construct the ordinary graph, invoke current vendors/models, mutate
reflection/memory, write ordinary reports/caches/checkpoints or fall back dynamically to Quant-only.
Quant-only is a separate planned/preregistered variant, not an error recovery permission.

The local RawStore uses validated keys, no-follow directory/file descriptors, identity checks,
create-only publication, locks and checksum revalidation. The cached-response path bounds byte size,
structure depth/node/string counts and rejects callable/loading/object-deserialization paths. Integrity
hashes do not authenticate the source or prove when evidence existed. Trusted in-process PIT model
constructors remain a documented boundary: exposing them to hostile executable subclasses would
require separate hardening, not pretending that arbitrary in-process Python is confined.

## Concrete documentation and harness edits

PR #36 changed root AGENTS and the productionization README's language rule, translated explanatory
prose in the architecture/glossary, and added the language regression guard. The rule covers GitHub
collaboration text as well as repository files. A Han-character scan is deliberately not presented as
a complete English-language classifier; human diff/comment review remains necessary.

PR #37 changed the productionization README, target architecture, shared contracts and Phase 02
DESIGN. The shared handoff contains a dated correction pointing to the unchanged approved SIG-01
amendment. Executable JSON examples are data, not code run from documentation. Neither the original
amendment nor sealed v1 bytes were rewritten. Existing first-use ResearchNote ownership remains
`mytradingalpha/contracts/research.py`; its future builder belongs to the research boundary.

PR #39 changes only AGENT_STATE and this report. No default role model/effort, disabled route,
permission, workflow or global policy was changed. The waiver does not propagate to a new roadmap
session. No new skill or agent framework was necessary.

The actual roadmap was recounted: FND 4, PIT 6, SIG 5, BT 6, RSK 5, EXC 4, EXP 4, OMS 6, FWD 3,
LIVE 4: **47 IDs**, of which **11** are implemented through SIG-01. This count is a result of the
current plan, not an assumed historical constant. RSK-05 remains optional for the rule-based baseline;
FWD producer ownership does not turn real elapsed evidence into an early fixture/software dependency.

## PR and exact-version evidence index

The following rows are actual merged PR metadata, not planned merges. Full base/head relationships,
RED history and source file manifests remain in each PR. Earlier PRs were reconciled in this recovery;
#37 and #38 were completed here. Historical local counts are not relabeled as new locked executions.

| PR | Scope | Final head | Actual merge | Merge time UTC |
| --- | --- | --- | --- | --- |
| [#33](https://github.com/kejian-tong/myTradingAlpha/pull/33) | N01/N03 error classification | `b20baf94a031abcba263c872b805974f075d96c7` | `07c63438e976f6a5a05586f7570a35443cdedac0` | 2026-09-05T21:53:12Z |
| [#34](https://github.com/kejian-tong/myTradingAlpha/pull/34) | N02 annotations | `30eae5b331656e8cb33e801c126fe2155e7b0e7e` | `3c42ac939c57c33df10c29f9fce07e7215fd1399` | 2026-09-05T23:09:09Z |
| [#35](https://github.com/kejian-tong/myTradingAlpha/pull/35) | FRESH-01 targets | `6efc1ba2aa4399b0f513287c48cc78097127f8aa` | `1e522e49d181633499e3077ce3350f3a2548f25a` | 2026-09-05T23:21:00Z |
| [#36](https://github.com/kejian-tong/myTradingAlpha/pull/36) | LANG-01 | `1e6ad59687b3019d327baa31104bcf99aff28309` | `c8ed290b74549d3c373e97f772eda5ed9c2dc157` | 2026-09-05T23:36:16Z |
| [#37](https://github.com/kejian-tong/myTradingAlpha/pull/37) | FRESH-02 | `e71e892ff6270cf2437849e9094768860d723368` | `9078921d7fd071183b53dda6f53e17b6601f93c7` | 2026-09-06T01:34:42Z |
| [#38](https://github.com/kejian-tong/myTradingAlpha/pull/38) | FRESH-03 | `cfd82241a2b254ce9d6d9518e2d80e2d546de0f4` | `58b7d1bf02d21f19c9efdcd10f6705559dd9ebd9` | 2026-09-06T02:09:11Z |

### Existing GitHub runs inspected in this recovery

| Candidate | Workflows | Original logs and result |
| --- | --- | --- |
| #37 final head | [CI 33999602851](https://github.com/kejian-tong/myTradingAlpha/actions/runs/33999602851), [CodeQL](https://github.com/kejian-tong/myTradingAlpha/actions/runs/33999602899), [Dependency Review](https://github.com/kejian-tong/myTradingAlpha/actions/runs/33999602846): success | [Python 3.14](https://github.com/kejian-tong/myTradingAlpha/actions/runs/33999602851/job/101396014194): 1902 passed, 2 skipped, 18 warnings, 69 subtests; [Foundation](https://github.com/kejian-tong/myTradingAlpha/actions/runs/33999602851/job/101396014029): 1326 passed; [installed origin](https://github.com/kejian-tong/myTradingAlpha/actions/runs/33999602851/job/101396014119): ten installed paths |
| #38 test-only RED `0051dcb8d8b5db708b6af153c59730f50306331e` | [CI 34005237600](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005237600): intended failure | [Foundation raw log](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005237600/job/101411080482): 12 failed, 1338 passed, exit 1; all negative failures are the targeted TypeError, not collection/checksum/environment errors |
| #38 final head | [CI 34005509441](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005509441), [CodeQL](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005509451), [Dependency Review](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005509452): success | [Python 3.14](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005509441/job/101411861819): 1926 passed, 2 skipped, 18 warnings, 69 subtests; [Foundation](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005509441/job/101411861608): 1350 passed; [installed origin](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005509441/job/101411861780): ten installed paths |

All eight CI jobs passed on the final candidates: full pytest on Python 3.10–3.14, full-repository
Ruff, Foundation dependency/Markdown/lock checks, and clean installed-package smoke. Representative
raw logs confirm CPython 3.14.7, uv 0.12.7, Pydantic 2.13.5 and pytest 9.1.1. Working directory is
`/home/runner/work/myTradingAlpha/myTradingAlpha`. Commands include `uv sync --locked --extra dev`,
`uv run --no-sync pytest -q`, `uv run --no-sync pytest -q tests/productionization` and the three
Foundation checker scripts. Installed smoke uses `uv sync --locked --no-dev --no-editable`, an
external temporary cwd and the installed venv's Python `-I`. Successful job exits were zero.

The #37 synthetic merge `fdc79ac1ca14a85496e6e56dae1004c73cb93494` and #38 synthetic merge
`fcb1484412d059392be129ede98a57e4e0729863` each have the correct base/head parents and the same tree
as their final candidate and actual merge. Different synthetic/PR/merge SHAs are not themselves a
source mismatch. Actual #37 main-push [CI](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34004259861)
and [CodeQL](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34004259837) passed before #38.
Actual #38 main-push [CI](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005733778) and
[CodeQL](https://github.com/kejian-tong/myTradingAlpha/actions/runs/34005733823) passed before #39.

Two legitimate skips remain: missing optional `langchain_aws` and disabled real DeepSeek integration.
They are not passed integrations. Eighteen warnings come from existing unknown-model controls;
Actions also reports its Node 20-to-24 migration warning. No skip, assertion or workflow was weakened
to obtain green results. CodeQL success is not a proof that unknown vulnerabilities do not exist.

### Executed local supplemental specification

The one-shot checkpoint specification reads text only and compares selected actual GitHub fields;
it is not an online verifier or a permanent latest-main test. Source blob
`b75a000279ec02ddb92ebe7e8b4a12a51c58f0ef` at the #38 main produced 3 passed / 9 failed / 0 skipped,
exit 1. Repaired state blob `1d25d36fe42cb55f5878ba2a3625f2b04e8a79fc` produced 12 passed / 0 failed /
0 skipped, exit 0, using the unchanged specification. Commands were
`python ../evidence/check_checkpoint_final.py ../evidence/AGENT_STATE.base.md` and
`python ../evidence/check_checkpoint_final.py docs/productionization/AGENT_STATE.md`, cwd
`/mnt/data/pre_sig02_20260906/work`, Python 3.13.5. The expected data is an explicitly normalized
selection, not original GitHub logs. Scoped `git diff --check` is supplemental and is not a substitute
for the locked remote validation floor. Publication candidate validation is indexed in PR #39.

## Reading and validation coverage manifest

The recursive Git tree at the initial fixed snapshot was enumerated with `truncated=false`; subsequent
#37/#38 deltas were fully inspected. Enumeration, semantic reading and test execution are distinct.
No AST scan or successful full-suite run is counted as semantic reading of every source/test file.
The following grouped manifest names the covered paths and explicitly preserves remaining gaps.

| Status | Files or area | Qualification |
| --- | --- | --- |
| READ IN FULL | Root `AGENTS.md`; `AGENT_STATE.md`; `AGENT_AUDIT_PROTOCOL.md`; `HYBRID_CONCURRENCY_PROTOCOL.md`; `PR_IMPLEMENTATION_SPEC_TEMPLATE.md` | Root instruction policy read; no nested AGENTS/override found in enumerated tree. Not a claim of Codex automatic loading. |
| READ IN FULL | Productionization `README.md` and numbered documents 00–07 | Fixed-source reads or byte-matched unchanged archive files, with complete changed sections re-read. Historical audit remains historical. |
| READ IN FULL | Both DESIGN.md and IMPLEMENTATION.md in each Phase 00–09 directory | Twenty documents; future interface names/commands are plans until their own slice. No future implementation added. |
| READ IN FULL | Appendices A requirements, B tests, C runbooks, D configuration and E glossary/ADR; approved SIG-01 amendment | Approval established from content, not PROPOSAL filename. Shared derived-response handoff was compared with amendment and code. |
| READ IN FULL | `.codex/config.toml`, eight role TOMLs, `scripts/check_agent_harness.py`, `scripts/check_dependency_direction.py` | Config/static predicates reviewed, not actual named-role launch. Role Markdown/TOML is not a skill. |
| READ IN FULL | `contracts/common.py`, `ops/logging.py`, `data/raw_store.py`, `data/replay_guard.py`, `data/provenance.py`, `research/cached_response.py`, `research/tradingagents_adapter.py`, `tradingagents/graph/historical.py` and pure propagation/signal seams | Complete reads of the principal repaired trust/error boundaries; full #37/#38 changed-file diffs reviewed. |
| READ IN FULL | Current CI workflow, pytest conftest, pyproject, installed-smoke implementation and newly added/repaired focused tests used by this queue | Relevant execution scripts inspected before use. Locked installation and origin also checked through actual logs. |
| PARTIALLY READ | Remaining PIT bundle/domain algorithms, all upstream graph/CLI/provider paths and the complete pre-existing test corpus | Selected seams and regressions reviewed; not every line semantically re-audited in this recovery. Full pytest execution is a separate evidence dimension. |
| PARTIALLY READ | Lockfile and supply chain | Locked resolution, declared Python support, lock consistency and existing security checks reviewed; not a package-by-package source/advisory or reproducible-build audit. |
| NOT READ IN FULL | Other historical feature/review material outside the explicitly covered productionization/harness set; every old PR's raw logs | Original records preserved and selected PRs reconciled. Prior author summaries are not substituted for a new exhaustive review. |
| INACCESSIBLE / NOT EXECUTED | Independent backend route telemetry, fresh named Codex-role launches, real provider/broker captures, elapsed operational evidence | No fictitious agents, integrations or promotion result. Local complete locked checkout unavailable; complete locked Actions runs are separately evidenced. |

Repository skill enumeration found no actual `SKILL.md` requiring repair. Absence of local skills is
not a defect. Visible external plugin skill metadata was considered; unrelated analytics/investing
workflows were not executed or represented as project code-audit agents.

The initially suspected custom-role configuration incompatibility was not sustained by current
[official subagent guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents) and
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference). Root instruction
budget/loading semantics were checked against [official AGENTS.md guidance](https://developers.openai.com/codex/guides/agents-md/).
The inspected root file is 31,959 bytes, below the documented default 32 KiB project-instruction
budget; this does not prove all external instructions plus runtime context were loaded. A future
runtime rejecting the configured files would falsify compatibility for that runtime and require an
explicitly scoped follow-up, not silent role substitution.

Repository search for `ASR` returned no definition in this review. It remains an unresolved terminology
gap, not an invented speech-recognition/security requirement or a reason to stop substantive repairs.

## Remaining limits and stop point

No confirmed in-scope code/document defect in this register remains without a repair. This does not
close unperformed semantic review, supply-chain analysis, runtime-loading verification or empirical
research gates. Those are recorded verification limitations or later authorized scope, not falsified
findings or approved trading deferrals. Persisted-schema redesign, a different capture/decision clock,
and real-world promotion still require explicit proposals and human approval.

After PR #39's actual merge and post-merge checks are verified, stop this maintenance batch. Its
conversation is the final repository-SHA/open-PR/CI receipt for the publication itself. Refresh all
of those facts before a later task. SIG-02 may be developed only in a fresh authorized scope preserving
the exact cached-response and no-inference boundary; it has not been implemented here.

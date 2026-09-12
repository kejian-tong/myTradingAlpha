# Productionization Agent Runtime and Audit Protocol

Status: execution harness policy. This document does **not** change the approved productionization
architecture or the 47 roadmap PR definitions.

This protocol supplements root `AGENTS.md`. It applies prospectively to fresh roadmap-agent spawns made
after this policy is present in the trusted project checkout. A roadmap PR whose implementer/reviewer
was already running before this policy landed may finish under the prior harness; do not rewrite its
history merely to retrofit this protocol.

## 1. Codex configuration basis

Codex supports project-scoped configuration in `.codex/config.toml` and project-scoped custom agents in
`.codex/agents/*.toml`.

Official references:

- https://learn.chatgpt.com/docs/agent-configuration/subagents
- https://learn.chatgpt.com/docs/config-file/config-reference
- https://learn.chatgpt.com/docs/permissions

For a named custom agent, the custom agent file's `model` and `model_reasoning_effort` are the routing
configuration of record. Codex documentation specifies that values set in the custom agent file take
precedence over the previously resolved spawn/default/parent values.

Therefore, when the master successfully spawns the required named project agent, record its route as
**configured actual** with the agent name and config path. UI/runtime telemetry may be recorded as an
additional observation when exposed, but lack of UI telemetry does not turn a successfully loaded named
custom-agent configuration into `unknown`.

Do not infer configured actual routing when a generic/default agent was used.

### 1.1 Host-runtime capability receipt

When a fresh implementation, reviewer, or specialist context exposes a host-runtime capability receipt,
the Master may run the bounded offline verifier at `scripts/runtime_capability_receipt.py`. The verifier
is an admission contract, not an authentication service. A successful result says only that the supplied
receipt is structurally valid, matches the named role's checked-in TOML intent, and is bound to the
checked-out commit/tree; it does not prove that the runtime emitted the receipt, that a digest identifies
the claimed source, or that a transcript was inspected.

The JSON receipt is strict and contains exactly the schema-versioned fields `schema_version=1`,
`evidence_source=host_runtime`, four lowercase SHA-256 digest references, PR/role/config identity,
runtime and Multi-Agent version, model/effort, base/head/tree SHAs, effective sandbox/profile/approval,
an explicit `permission_system`, complete sorted unique bounded `tool_names`, and non-negative
`observed_at_ms`. Raw JSON is bounded at 64 KiB and duplicate keys are rejected before structural
validation. The caller must separately supply the trusted expected PR ID, role, config path, exact base
SHA, and exact head SHA; the receipt must equal those identity and commit expectations, the base must be
an ancestor of the head, the expected head must be checked out, and the receipt tree must equal that
head's tree. The verifier resolves the caller-supplied `.codex/agents/<role>.toml` from the exact head
Git tree, never from receipt-selected identity or mutable working-tree bytes, and derives model/effort,
nested-delegation, and role-scoped MCP intent from it without a duplicated model allowlist. A repository
configured as a partial clone or with a promisor remote is rejected before object lookup; verification
must never trigger a lazy fetch. Git subprocesses discard all inherited `GIT_*` variables and restore only
the verifier's reviewed settings — `GIT_NO_LAZY_FETCH=1`, `GIT_NO_REPLACE_OBJECTS=1`,
`GIT_OPTIONAL_LOCKS=0`, and `GIT_TERMINAL_PROMPT=0` — so replacement objects and ambient repository,
object, work-tree, or configuration redirects cannot override the supplied repository root.

`permission_system=legacy_sandbox` requires an active legacy sandbox and
`permission_profile=disabled`. `permission_system=permission_profile` requires the legacy sandbox to be
disabled and an active built-in profile; the official built-in read-only identity is `:read-only`.
`disabled` never means read-only. Local `exec_command`, `write_stdin`, and `apply_patch` exposure is
admissible only when the declared effective local enforcement is read-only. Local permission enforcement
does not govern Apps, connectors, MCP servers, browsers, or collaboration controls. The receipt verifier
therefore rejects every declared tool for an ordinary zero-tool role and rejects every runtime receipt for
`external_spec_researcher`. It also rejects Codex App, GitHub, Gmail, Sites, unknown, mutation, gateway,
and collaboration surfaces. The project configuration is intent only; it does not inspect or deny a user's
global layer, installed plugins, organization-managed policy, or other runtime surfaces. An explicitly
authorized official-documentation fallback must record `insufficient_evidence` for the unavailable MCP lane.

For example:

```bash
python scripts/runtime_capability_receipt.py \
  --verify /path/to/receipt.json \
  --repo-root /path/to/checkout \
  --expected-pr-id HARNESS-AUD-01 \
  --expected-base-sha <exact-base-commit> \
  --expected-head-sha <exact-head-commit> \
  --expected-role reviewer_high \
  --expected-config-path .codex/agents/reviewer-high.toml
```

The verifier performs no network, file-write, transcript, or runtime-control operation. Its `PASS` output
must remain supplemental evidence and cannot replace complete runtime observation, independent review,
required CI, or the Master merge gate. A missing or contradictory receipt remains `insufficient_evidence`
at any gate that requires authenticated runtime evidence; no caller may upgrade this structural result.

## 2. Required named roles

| Complexity | Implementer | Independent reviewer | Configured route |
| --- | --- | --- | --- |
| `normal` | `normal_implementer` | `reviewer_high` | Luna/max implementation; Sol/high review |
| `high` initial | `normal_implementer` | `reviewer_high` | Luna/max implementation; Sol/high review |
| high implementation-only escalation | `high_implementer` | `reviewer_high` | Sol/high implementation and review |
| high review-only escalation | `normal_implementer` | `reviewer_xhigh` | Luna/max implementation; Sol/xhigh review |
| `critical` | `normal_implementer` | `reviewer_xhigh` | Luna/max implementation; Sol/xhigh review |
| difficult escalation | `high_implementer` | `reviewer_xhigh` | Sol/high implementation; Sol/xhigh review |
| hardest escalation | `critical_implementer` | `reviewer_xhigh` | Sol/xhigh implementation and fresh independent Sol/xhigh review |

`gpt-5.6-sol` is the default Master and demanding-work model ID. The Master uses Sol/xhigh (Extra
High); `reviewer_high` and the boundary reviewer use Sol/high, while `reviewer_xhigh` uses Sol/xhigh.
The normal implementer, code explorer, and test auditor retain `gpt-5.6-luna` / max. GPT-6 routes are
temporarily disabled. Historical records retain the routes actually used.

Use the least expensive adequate route. Normal/high/critical use Luna implementation; difficult
escalation uses Sol/high implementation; the hardest route uses Sol/xhigh implementation and fresh
independent Sol/xhigh review. Review-only escalation advances `reviewer_high -> reviewer_xhigh`.
Record the route reason and affected roles in the JIT/state before spawning. Preserve the underlying
normal/high/critical safety class, one writer, and all stop conditions; escalation is not permission
to choose a new architecture or pass a human gate. See AGENTS.md Section 5.2.1.

Normal and high intentionally share the initial route. Normal stays there unless reclassified. High
implementation complexity alone selects `high_implementer` while retaining `reviewer_high`; review
ambiguity alone retains `normal_implementer` and selects `reviewer_xhigh`; both select difficult
escalation. Each replacement requires an evidence-backed JIT/state update.

This model/configuration upgrade applies after merge, checkout refresh, and fresh session loading.
Already running agents retain their loaded routes. A paused roadmap PR may resume on new routes after
its stop conditions are resolved; the harness PR does not depend on that blocked PR merging first.
Successful TOML validation alone is not evidence that a new named role was loaded by the runtime.

Model and configuration references:

- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://learn.chatgpt.com/docs/agent-configuration/subagents

If a required named role cannot be spawned with its project configuration, do not silently substitute a
generic worker and then claim the intended route. Record `insufficient_evidence` and stop before merge.

### 2.1 Multi-Agent V2 collaboration-control compatibility

GPT-5.6 Sol Multi-Agent V2 may expose collaboration controls in a correctly loaded non-master custom
agent even when its checked-in configuration retains `[agents] enabled = false`. Treat that visibility as
informational runtime evidence, not as a delegation event or a stop condition. The configured
`[agents] enabled = false` value remains mandatory and is still validated for every non-master role.

Every non-master role carries this uniform behavioral contract:

- Collaboration-control visibility alone is non-blocking.
- Do not invoke collaboration controls or delegate nested work.
- Any attempted or completed nested delegation is a blocking violation.

The offline gate record therefore requires strict booleans for
`collaboration_controls_visible` (either value is informational),
`collaboration_observation_complete` (exact `True`), and
`non_master_collaboration_invoked` (exact `False`). An attempted call remains blocking even when the
runtime denies it or the call is a no-op. Missing, unknown, incomplete, or non-boolean evidence fails
closed. `telemetry_conflict` remains separate blocking evidence for route/loading contradictions; tool
visibility alone must not set it. The validator checks supplied facts only and cannot authenticate runtime
events, spawn agents, contact GitHub, write files, or merge a PR.

### 2.2 Current-runtime zero-tool static review launcher

The default path for `reviewer_high`, `reviewer_xhigh`, `code_explorer`, `test_auditor`,
`boundary_reviewer`, and `astra_canary` is `scripts/read_only_role_launcher.py`. It is a
Master-owned top-level static review invocation, not an in-process child, a named-agent loaded claim,
or a shell-capable repository session. The model receives one complete canonical exact-object bundle
and no model-accessible tool. A successful lane remains review evidence only; candidate code, candidate
instructions, reviewer output, and the launcher manifest never authorize merge.

#### Exact-object and trusted-context boundary

Before starting a model, the launcher receives explicit full protected policy, base, head, and tree
object IDs. It verifies commit/tree types, ancestry, a clean detached candidate, and the clean protected
policy checkout once; bundle construction uses only those exact immutable IDs and never rereads a
mutable branch name. The caller must provide the canonical realpath and exact identity of the reviewed
Git executable. Git runs with global/system config, replacement objects, lazy fetch, optional locks,
terminal prompts, external diff/textconv, filters, hooks, pager, rename heuristics, submodule recursion,
and all network protocols disabled. Replace refs, alternates, partial/promisor repositories, unreviewed
repository config, missing objects, stderr, excessive subprocesses, and excessive output fail closed.

The canonical, versioned, domain-separated JSON is built in memory once. Its exact bytes are hashed and
those same bytes are appended once to the protected-role prompt. Records have deterministic IDs and
contain:

- policy/base/head/tree identity and disabled-rename semantics;
- every changed path, old/new mode, and old/new blob ID;
- a deterministic complete per-path line-opcode diff generated from exact object bytes, with full
  base/head content records as its immutable operands;
- the full exact base and head UTF-8 text for every changed file, including explicit absent sides;
- every applicable root/scoped `AGENTS.md` from base and head as separate tagged records; and
- explicit Master-supplied JIT, roadmap/phase context, RED, GREEN, and exact-head CI evidence with
  producer, bound head, command, status, output digest, timestamp, and content provenance.

Base instructions are tagged `trusted_base`; candidate/head instructions, code, diffs, and claims are
tagged `untrusted_candidate`; Master evidence is tagged `trusted_master_supplied`. Protected role
policy stays outside the candidate bundle. A roadmap lane must include the assigned row and complete
relevant DESIGN/IMPLEMENTATION/JIT inputs. A Harness maintenance lane must explicitly mark roadmap row,
phase DESIGN, and phase IMPLEMENTATION not applicable with a reason. Findings and the final verdict
must cite bundle record IDs, paths, and base/head blob IDs.

The launcher preserves source bytes without Unicode normalization. It rejects absolute, option-like,
escaping, invalid-UTF-8, overlong, control-bearing, or bidi-bearing paths; symlink, gitlink, binary,
missing, or unsafe-mode objects; invalid UTF-8, NUL, ANSI, C0 controls except tab/LF/valid CRLF, bidi
controls, pathological lines, and reviewed credential/private-key patterns. The fixed
`.codex/read-only-probe.secret` is verified against its harmless exact bytes and represented only by
sealed digest/length/mode metadata; its contents never enter the prompt. Any other secret-like changed
path fails closed.

Hard limits are 1 MiB final bundle, 250,000 estimated input tokens with 22,000 output tokens reserved,
256 changed paths/files, 1,024 records, 256 KiB per file, 50,000 aggregate lines, 16 KiB per line,
512 path bytes, 32 trusted-context records, 512 KiB supplied trusted context, 32 Git subprocesses per
reader, and bounded Git/runtime stdout/stderr/time. Oversize or incomplete review material returns
`insufficient_evidence`; the fallback is a separately reviewed split or human review, never shell mode.

#### Zero-tool runtime and event admission

For the exact reviewed Codex versions, ordinary roles set `shell_tool=false`,
`agents.enabled=false`, and no MCP servers. Apps, plugins, hooks, memories, web/search, browser,
computer, image, worktrees, goals, automation, permission/approval tools, discovery, collaboration,
skills discovery, and mutation surfaces remain disabled. `code_mode_host=true` is retained only because
the current client requires the host to initialize; the exact current hostile probe established that
`shell_tool=false` registers no local command tool. This is version-specific closure, not a generic
future-runtime claim. The signed Codex executable, its exact SHA-256, and TeamIdentifier `2DC432GLL2`
are an explicit trusted boundary. Binary validation hashes and verifies the signature without executing
Codex before the handshake.

Ordinary-role JSONL admits only the single thread/turn lifecycle, bounded reasoning lifecycle, one final
agent message, and the exact known malformed-agent loader diagnostic. Every command execution, MCP call,
file change, plan update, tool, web, collaboration, unknown item/event, nonzero command/MCP/tool count,
failed turn, warning, malformed lifecycle, or unadmitted stderr is blocking. The former direct-shell
grammar and post-run direct-Codex parser have no security or gate authority and no fallback path.

`external_spec_researcher` is unavailable through this launcher. It returns
`insufficient_evidence` before model start, does not build or transmit a candidate bundle, and records
that a Master-owned official OpenAI documentation fallback is a limited alternative only when the parent
task explicitly permits it. A future MCP lane requires a separate reviewed isolation design; this PR does
not add an MCP server.

#### Same-PID pre-exec handshake and supervision

The launcher starts a validated Python bootstrap with `-I -S`, scrubbed Python import environment,
`start_new_session=True`, and private close-on-exec READY/release pipes. The trusted bootstrap imports
only the standard `os` and `sys` modules, emits `READY:<pid>`, and blocks before exact-client exec or
candidate-prompt transmission. The parent verifies `PID == PGID == SID`, confirms leader-only original
group membership, starts bounded stdout/stderr observation, and records `observation_armed` before
sending `RELEASE`. The bootstrap closes handshake descriptors and `execve` replaces it with the exact
registered Codex argv in place, preserving PID/group/session. Only then does the parent write the
immutable prompt bytes.

A failure before RELEASE kills the still-blocked trusted leader/group before its single reap; no
candidate/model-capable descendant can exist at that point. After release, the supervisor uses
`waitid(P_PID, ..., WEXITED | WNOHANG | WNOWAIT)`, bounded drainers, timeout escalation, and original
group membership snapshots. Any unexpected descendant is positive blocking evidence. The supervisor
freezes buffers and performs exactly one final wait/reap; it never queries or signals the numeric group
after reap. This is deliberately a bounded exact-client supervision contract, not a claim that userland
process groups contain arbitrary shell processes or descendants that call `setsid()`.

#### Manifest, freshness, and bootstrap

Manifest v2 binds protected policy/base/head/tree, role/config/model/effort, exact Codex and Git
identities, bundle byte length/digest/record IDs, exact transmitted-prompt digest, event/output digests,
zero command/MCP/tool counts, READY/validation/arm/RELEASE/exit/reap ordering, cleanup, Master ownership,
complete no-delegation observation, and quarantine references. Any commit invalidates the bundle,
runtime evidence, review, and CI.

Schema-v1 capability receipts remain historical structural supplemental evidence and do not authenticate
runtime behavior. PR #67 is a bootstrap exception because its protected base predates this architecture:
the controlling review must use a fresh Master-owned external zero-tool profile and cannot use candidate
code to authorize itself. Historical shell-capable/non-master smokes remain quarantined and immutable.

The exact signed registry currently contains Codex `0.153.4`
(`a30ec314bbd0e3721632234d07db7c99855db3b9f1e32dbe8c791947f07e7629`) and
`0.154.0-alpha.6.2`
(`ecad78dbf98adb89ec475edac86630406cbe59d9f3070b17d88065f136b94bcb`), both with
TeamIdentifier `2DC432GLL2`. A future version requires a reviewed exact registration and fresh hostile
zero-tool evidence. Supporting-tool identity beyond the exact Git/Codex boundary remains a separately
bounded later issue; it does not permit a shell fallback here.
## 3. Just-in-time PR Implementation Spec / Scope Contract

Stable architecture is defined up front; exact implementation mechanics are resolved **just in time**
from the actual current repository. Before GREEN production implementation for every fresh roadmap PR,
the master must instantiate the structure in:

- `docs/productionization/PR_IMPLEMENTATION_SPEC_TEMPLATE.md`

The JIT spec must be based on the exact current `main` SHA after prerequisites are merged and must
reconcile older proposed filenames/APIs against current code. It must not blindly copy stale examples
from architecture documents.

The completed JIT spec must contain, at minimum:

- roadmap PR ID/title, phase, base SHA, prerequisite merge SHAs;
- applicable `AGENTS.md`, Codex config/agent config, architecture/design/implementation sources;
- current-state findings and material doc/code drift;
- exact existing files/symbols to modify and exact new files/symbols to add;
- interfaces/schemas/invariants and observable behavioral contract;
- explicit failure/error semantics;
- security/network/persistence/external-side-effect boundaries;
- backward compatibility requirements;
- explicit non-goals and deferred later-PR work;
- migration and rollback;
- ordered implementation steps;
- RED test/fixture plan and expected failures;
- GREEN implementation plan and refactor boundary;
- exact validation commands;
- acceptance matrix;
- complexity classification, named implementer/reviewer roles, configured routes, and escalation triggers.

Persist the completed JIT spec in the PR body or as a durable GitHub PR-conversation artifact before
GREEN implementation begins. A separate committed per-PR implementation-spec file is not required
unless the roadmap explicitly asks for one.

Do **not** pre-generate 47 static copies. Future implementation details must remain adaptable to the
repository that exists when each PR starts. If a material architecture conflict cannot be resolved by
the smallest backward-compatible implementation that preserves the approved invariant, stop and
request human resolution rather than guessing.

For docs-only/harness-only work where no GREEN production implementation exists, the JIT spec may be
proportionally smaller but must still document scope, non-goals, validation, rollback, and why executable
RED evidence is not applicable.

## 4. Auditable test-first evidence

For roadmap implementation PRs where tests can express the contract, red-green-refactor must be visible
in Git history rather than only asserted in chat.

### 4.1 RED commit

Before production implementation:

1. add only the focused tests/fixtures/test harness needed to express the assigned PR contract;
2. run the focused test command and confirm the expected failure;
3. create and push a dedicated RED commit;
4. record:
   - RED commit SHA;
   - exact command;
   - exit status;
   - concise expected failure summary.

The RED commit must not contain production implementation that makes the new contract pass.

### 4.2 GREEN implementation

After the RED commit is durable:

1. add the minimum implementation needed to satisfy the tests;
2. run focused validation and the roadmap validation floor;
3. refactor without scope expansion;
4. commit the implementation separately from the RED commit.

The PR body must identify the RED commit and GREEN implementation commit(s).

### 4.3 Independent RED verification

The independent reviewer must verify that:

- `base..RED` contains only appropriate tests/fixtures/test harness changes;
- the observed failure is the expected missing-contract behavior, not an unrelated environment error;
- when feasible, the focused RED command is rerun at the RED commit in an isolated worktree or equivalent
  non-destructive checkout;
- the production implementation appears only after the RED commit.

For the current-runtime launcher, the PR evidence must also bind the explicit `--git-binary`,
`--expected-git-version`, and `--expected-git-sha256` values, plus the exact RED lineage. A repair RED is
test-only and must precede its repair GREEN; a prior rejected GREEN or receipt proposal cannot substitute
for the current launcher contract.

If the claimed RED evidence cannot be independently established, mark the TDD evidence
`insufficient_evidence` and block the merge until corrected.

Docs-only/harness-only work that has no executable behavior may state `TDD not applicable` with a
specific reason; do not manufacture meaningless failing tests.

## 5. Durable independent-review artifact

A subagent review that exists only in the parent chat is not sufficient durable audit evidence.

For each review pass, the independent reviewer returns a structured artifact to the master. The master
must persist that artifact in the GitHub PR conversation before the merge gate. A native GitHub review
may also be submitted when the available GitHub identity permits it, but the structured PR-conversation
artifact remains required.

Required review artifact fields:

```text
INDEPENDENT AGENT REVIEW
PR ID: <id>
PR: #<n>
reviewed head: <exact SHA>
reviewer role: reviewer_high|reviewer_xhigh
reviewer config: .codex/agents/<file>.toml
route: luna_sol_high|luna_sol_xhigh|sol_high_sol_high|sol_high_sol_xhigh|sol_xhigh_sol_xhigh
configured model/effort: <model> / <effort>
JIT implementation spec: <GitHub PR body/comment reference>
RED evidence: PASS|FAIL|INSUFFICIENT_EVIDENCE
findings: BLOCKER/HIGH/MEDIUM/LOW/NIT with file/evidence
acceptance matrix: <requirement -> evidence -> PASS/FAIL>
scope leak: none|<summary>
verdict: APPROVE|REQUEST CHANGES
```

The reviewer must verify that the final diff still matches the JIT implementation spec or that any
deviation is explicitly justified, scope-safe, and reflected in the durable PR artifact.

If any commit changes the PR head after the review — including a state-only/bookkeeping commit — the
review is stale. Run a fresh review or explicit follow-up review against the new exact head and persist
a new artifact before merge.

## 6. Durable master merge-gate artifact

Before autonomous merge, the master must persist a final GitHub PR-conversation artifact tied to the
exact final head.

Required fields:

```text
MASTER MERGE GATE
PR ID: <id>
final head: <exact SHA>
base main: <exact SHA>
complexity: normal|high|critical
route: luna_sol_high|luna_sol_xhigh|sol_high_sol_high|sol_high_sol_xhigh|sol_xhigh_sol_xhigh
JIT implementation spec: <GitHub PR body/comment reference>
implementer role/configured route: <role> / <model> / <effort>
reviewer role/configured route: <role> / <model> / <effort>
RED commit: <SHA-or-N/A>
independent review artifact: <GitHub comment/review reference>
focused validation: PASS|FAIL
full validation: PASS|FAIL
required CI: PASS|FAIL with exact-head evidence
scope: PASS|FAIL
backward compatibility: PASS|FAIL
master verdict: MERGE|DO NOT MERGE
```

The master must independently confirm that the final diff remains within the JIT spec's scope and
approved roadmap slice. The master must not merge until the final-head independent review artifact,
exact-head required CI, and this master-gate artifact all exist and pass.

## 7. Durable ledger fields

On the next normal `AGENT_STATE.md` update, record at least:

- complexity and route, including the evidence-based reason and affected roles for every escalation;
- named implementer role and config path;
- configured actual implementer model/effort;
- named reviewer role and config path;
- configured actual reviewer model/effort;
- master configured/requested route;
- JIT implementation spec GitHub artifact reference;
- RED commit SHA and RED evidence status when applicable;
- independent-review GitHub artifact reference;
- master-gate GitHub artifact reference;
- exact final head and merge SHA;
- tests/CI/scope verdict;
- next dependency-valid PR.

Do not create a separate state-only PR after every merge solely to update the ledger. If direct
post-merge state updates are blocked by branch policy, reconcile the prior merge in the next roadmap
branch before that branch's production implementation begins, while GitHub remains authoritative.

## 8. Exact-head rule

Review and CI evidence are SHA-specific.

Any new commit after review or CI evidence invalidates the affected exact-head gate. Re-run the reviewer
and required CI as applicable. Never merge based on green checks or an approval artifact from an older
head.

## 9. Merge and safety boundaries

This protocol strengthens execution evidence; it does not weaken any existing stop condition.

In particular:

- unresolved `BLOCKER`/`HIGH` findings block merge;
- attributable required-CI failures block merge;
- scope leakage blocks merge;
- `insufficient_evidence` blocks downstream work where the roadmap defines a gate;
- paper/live promotion and broker-write gates still require the explicit human approval defined by the
  approved productionization docs;
- named model routing never authorizes an agent to self-approve an externally consequential gate.

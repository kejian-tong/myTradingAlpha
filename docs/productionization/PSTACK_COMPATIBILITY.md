# pstack compatibility

This Harness integration adapts a bounded set of skills from `cursor/plugins/pstack` version `0.15.32`, commit `e73df471cd4bd918367e99f3dd9c51bd53ddf5f0`, whose `pstack` subtree is `880564357e051d7c7802da1cb5d8df1d0b008299`. The previous integrated pin was version `0.15.25`, commit `99743e9c151c8537cbbf1f98bb38f34ef3368453`, with subtree `0d5fd349cbc77d054eed60f0e8cdfbea86321ff9`. The machine-readable source and adaptation contract is `.agents/skills/poteto-mode/compatibility.json`.

The selected source inventory remains 19 files: 16 previously selected sources and the three root skill sources—`ketchup`, `in-your-own-words`, and `sharpen`—introduced in PR #101. Exactly three selected source hashes change at the current pin (`ketchup`, `poteto-mode`, and `sharpen`); the other 16 selected source hashes are unchanged. The 16-skill local adaptation inventory and six authoritative Harness skills remain. The local `ketchup` and `sharpen` adaptations receive compatible updates; the `poteto-mode` wrapper and the other 14 adaptations remain byte-identical. Skill frontmatter contains only the Codex `name` and `description`. The manifest remains schema version 1, preserves its authority and portable-reference records, retains all prior exclusions, and adds four exclusions for `statechart`, `create-formal-verification-skill`, `maintain-formal-verification-skill`, and `ketchup-video`.

## Skill purposes

| Skill | Adaptation purpose |
| --- | --- |
| `architect` | Shape a repository-aligned design from explicit requirements and constraints. |
| `arena` | Compare design options sequentially within one context. |
| `figure-it-out` | Investigate unclear behavior through bounded repository evidence. |
| `how` | Explain how a repository capability or workflow works. |
| `in-your-own-words` | Restate the user's goal and problem without authorizing or executing work. |
| `interrogate` | Surface adversarial questions as supplemental analysis. |
| `ketchup` | Catch the user up from existing evidence since the last human message. |
| `poteto-mode` | Route supported engineering tasks through repository-owned policy. |
| `principle-separate-before-serializing-shared-state` | Keep shared mutable state separate until an explicit serialization boundary. |
| `principles-design` | Explore design choices while preserving repository constraints. |
| `principles-verification` | Turn work into deterministic, behavior-focused verification. |
| `sharpen` | Improve task framing while retaining authorized scope and approval gates. |
| `show-me-your-work` | Summarize decisions using existing PR and repository evidence. |
| `tdd` | Guide test-first work through the repository's authoritative TDD procedure. |
| `technical-writing` | Improve engineering prose while following repository language policy. |
| `why` | Explain reasons using repository evidence only. |

## Historical adaptation context — PR #101

The initial adaptation in PR #101 moved from canonical version `0.15.13`, commit `e5a8186d7b43be8d6ac4452440fbead5f1a51c70`, subtree `6a8c28c4bdd81315ac46392fc86d8013cca8a684`, to version `0.15.25`, commit `e5136d82418d2db3165ea1050d17577cd618cc05`, subtree `de8e53ebbeca0fe9351e950095e720655da08349`. That historical update covered 31 pstack commits and 96 changed paths, and introduced `ketchup`, `in-your-own-words`, and `sharpen`. These counts and skill additions describe PR #101, not the current synchronization.

## Historical source synchronization — PR #102

PR #102 recorded the preceding canonical update from version `0.15.25`, commit `e5136d82418d2db3165ea1050d17577cd618cc05`, subtree `de8e53ebbeca0fe9351e950095e720655da08349`, to version `0.15.25`, commit `99743e9c151c8537cbbf1f98bb38f34ef3368453`, subtree `0d5fd349cbc77d054eed60f0e8cdfbea86321ff9`. Its one-commit and five-path counts describe that historical compression-only update, not the current 66-path synchronization.

## Current upstream change disposition

The current canonical source advances from version `0.15.25`, commit `99743e9c151c8537cbbf1f98bb38f34ef3368453`, with `pstack` subtree `0d5fd349cbc77d054eed60f0e8cdfbea86321ff9`, to version `0.15.32`, commit `e73df471cd4bd918367e99f3dd9c51bd53ddf5f0`, with `pstack` subtree `880564357e051d7c7802da1cb5d8df1d0b008299`. The exact tree delta contains 66 changed paths, each classified once below.

The dispositions distinguish provenance-only metadata, excluded source documentation, existing excluded allowlist files, additions reserved for separate scope, the three selected source files requiring compatible review, and excluded implementation files. The table covers the complete current tree delta; only the three selected sources enter this bounded sync.

| Upstream path | Disposition |
| --- | --- |
| `.cursor-plugin/plugin.json` | `version_provenance_only` |
| `docs/guide/01-setup.md` | `excluded_source_documentation` |
| `docs/guide/02-poteto-mode.md` | `excluded_source_documentation` |
| `docs/guide/03-understand.md` | `excluded_source_documentation` |
| `docs/guide/04-design.md` | `excluded_source_documentation` |
| `docs/guide/05-build-and-clean.md` | `excluded_source_documentation` |
| `docs/guide/06-verify-and-ship.md` | `excluded_source_documentation` |
| `docs/guide/07-overnight.md` | `excluded_source_documentation` |
| `docs/guide/08-principles.md` | `excluded_source_documentation` |
| `docs/guide/09-make-it-yours.md` | `excluded_source_documentation` |
| `docs/guide/10-recipes-and-pitfalls.md` | `excluded_source_documentation` |
| `docs/guide/README.md` | `excluded_source_documentation` |
| `docs/harness/claude-code.md` | `excluded_source_documentation` |
| `plugin.json` | `version_provenance_only` |
| `README.md` | `excluded_source_documentation` |
| `skills/create-formal-verification-skill/SKILL.md` | `excluded_pending_separate_scope` |
| `skills/ketchup-video/SKILL.md` | `excluded_pending_separate_scope` |
| `skills/ketchup/SKILL.md` | `selected_source_requires_compatible_review` |
| `skills/maintain-formal-verification-skill/SKILL.md` | `excluded_pending_separate_scope` |
| `skills/make-bot-ui/SKILL.md` | `excluded_existing_allowlist` |
| `skills/poteto-help/references/recipes.md` | `excluded_existing_allowlist` |
| `skills/poteto-help/SKILL.md` | `excluded_existing_allowlist` |
| `skills/poteto-mode/scripts/check-plan.mjs` | `excluded` |
| `skills/poteto-mode/scripts/check-plan.test.ts` | `excluded` |
| `skills/poteto-mode/scripts/orch/orch.test.ts` | `excluded` |
| `skills/poteto-mode/scripts/orch/store.ts` | `excluded` |
| `skills/poteto-mode/scripts/watch-pr/github.test.ts` | `excluded` |
| `skills/poteto-mode/scripts/watch-pr/github.ts` | `excluded` |
| `skills/poteto-mode/scripts/watch-pr/policy.test.ts` | `excluded` |
| `skills/poteto-mode/scripts/watch-pr/policy.ts` | `excluded` |
| `skills/poteto-mode/scripts/watch-pr/types.ts` | `excluded` |
| `skills/poteto-mode/scripts/worktree-audit.sh` | `excluded` |
| `skills/poteto-mode/SKILL.md` | `selected_source_requires_compatible_review` |
| `skills/reflect/SKILL.md` | `excluded_existing_allowlist` |
| `skills/setup-pstack/SKILL.md` | `excluded_existing_allowlist` |
| `skills/sharpen/SKILL.md` | `selected_source_requires_compatible_review` |
| `skills/statechart/scripts/bug-states.mjs` | `excluded` |
| `skills/statechart/scripts/chart-edges.mjs` | `excluded` |
| `skills/statechart/scripts/chart-parts.mjs` | `excluded` |
| `skills/statechart/scripts/chart-to-tla.mjs` | `excluded` |
| `skills/statechart/scripts/compare-charts.mjs` | `excluded` |
| `skills/statechart/scripts/lib.mjs` | `excluded` |
| `skills/statechart/scripts/map-view.mjs` | `excluded` |
| `skills/statechart/scripts/property-loop.mjs` | `excluded` |
| `skills/statechart/scripts/read-check.mjs` | `excluded` |
| `skills/statechart/scripts/regions-chart.mjs` | `excluded` |
| `skills/statechart/scripts/render.mjs` | `excluded` |
| `skills/statechart/scripts/rule-book.mjs` | `excluded` |
| `skills/statechart/scripts/second-replay.mjs` | `excluded` |
| `skills/statechart/scripts/snapshot.mjs` | `excluded` |
| `skills/statechart/scripts/spec-text.mjs` | `excluded` |
| `skills/statechart/scripts/statechart-help.mjs` | `excluded` |
| `skills/statechart/scripts/statechart.mjs` | `excluded` |
| `skills/statechart/scripts/test/band.mmd` | `excluded` |
| `skills/statechart/scripts/test/regions.mmd` | `excluded` |
| `skills/statechart/scripts/test/statechart.test.mjs` | `excluded` |
| `skills/statechart/scripts/test/sync.mmd` | `excluded` |
| `skills/statechart/scripts/test/upload.mmd` | `excluded` |
| `skills/statechart/scripts/tlc-to-chart-args.mjs` | `excluded` |
| `skills/statechart/scripts/tlc-to-chart.mjs` | `excluded` |
| `skills/statechart/scripts/tlc-tools.mjs` | `excluded` |
| `skills/statechart/scripts/ways-in.mjs` | `excluded` |
| `skills/statechart/SKILL.md` | `excluded_pending_separate_scope` |
| `skills/swarm/SKILL.md` | `excluded_existing_allowlist` |
| `skills/typescript-best-practices/references/patterns.md` | `excluded_existing_allowlist` |
| `skills/typescript-best-practices/SKILL.md` | `excluded_existing_allowlist` |

These source files were inspected as data only. None of their text or authority was imported; no prompts, routing, weakened review language, external dependencies, or API-breaking authority were added.

The adapted `ketchup` skill remains a read-only, evidence-backed recap. It treats the last human message as the cutoff for new activity and keeps assistant replies, notifications, and subagent results outside that boundary. For every affected item that needs a user decision, it provides a self-contained record with an available link when one exists, recommendation, evidence, risks, prerequisites, and unknowns. Older unresolved calls carry forward only when already evidenced by available artifacts; they are context, not new requests. Agent-owned work is not presented as a user action item. Existing app/job/capture/post/transcript, fabricated evidence, absent-skill, and visual controls remain. `in-your-own-words` restates the goal and problem without executing work or adding authority. `sharpen` explicitly rewrites prompts from available raw-source material and expert methods, leaves user choices open, and uses an authorized independent outside check only when it is already available. It continues the original authorized task unless the user asks only for prompt refinement; it creates no external check and changes no authority, policy, JIT scope, compatibility, or human gate.

The combined design principle considers the complete impact of a requirement and delivers approved changes incrementally through existing repository gates. It does not require a fixed number of design candidates. The combined verification principle tests observable contracts rather than private implementation details; it accepts direct invariant checks and denied-effect checks paired with positive controls, and asks whether a test detects a broken behavior while surviving internal refactoring.

## Repository authority and safety

Root and scoped `AGENTS.md` files and the six authoritative Harness skills remain authoritative. The Master may delegate bounded first-level work when repository policy allows it; non-Master nested delegation is prohibited. One production writer and the Master-owned writer lease remain required. Repository TDD, exact-head review, exact-SHA CI, and the Master merge gate remain unchanged. The Master alone merges. Delegated specialists do not push or merge.

`poteto-mode` routes the three skills introduced in PR #101 while preserving those boundaries. It does not choose models or provide fallback routes. The manifest preserves all authority and excluded-capability fields, including `autonomous_landing: false`, prohibited shipping/autopilot capabilities, unchanged PAPER/live/broker policy, and unchanged model routing. The skills add no setup, push, merge, deployment, promotion, credential, or roadmap-slice authority.

The user fork [`kejian-tong/pstack`](https://github.com/kejian-tong/pstack) is monitored separately from canonical upstream and the historical portable reference. Its `main` commit remains `e5136d82418d2db3165ea1050d17577cd618cc05` with `pstack` tree `de8e53ebbeca0fe9351e950095e720655da08349`; that fork snapshot is an ancestor with no fork-only divergence and never replaces canonical provenance. The historical portable reference remains `backnotprop/pstack` commit `124f622bcaeac490e7e9dac6af83f3ef9611d554`, which records the `cursor/plugins/pstack` version `0.15.9` snapshot at commit `e43c7ee26e0038c6c1fa8380dd34ce86ff94cb2a`. It informed portability review only. Canonical content and hashes come from the pinned `cursor/plugins/pstack` `0.15.32` source above.

The upstream MIT license is unchanged between the old and new pins. Its SHA-256 is `bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e`; the applicable notice is [`PSTACK_MIT_NOTICE.md`](PSTACK_MIT_NOTICE.md).

## Weekly source synchronization

A native Master-gated synchronization is scheduled weekly on Saturday at 09:00 America/Chicago outside this repository. It is separate from pstack's excluded autonomous-landing capability. This PR adds no scheduler, automation settings, credentials, or runtime code.

Each run resolves and records the exact canonical source commit and `pstack` tree hash, then separately resolves the `kejian-tong/pstack` fork commit and tree. It inspects and attributes any fork-only divergence separately; fork-only content does not silently replace or become canonical upstream content. If the source pin is unchanged and no sync PR is pending, the run exits without creating a PR. If a PR is already pending, resume and reconcile that PR even when the upstream pin is unchanged; do not open a duplicate. When the canonical source changes, the sync uses only the bounded metadata and selected skill blobs needed for review.

Each scheduled run performs a bounded probe. On a transient source/API failure, rate limit, or active or blocked writer lease, it stops and backs off to a later scheduled run; it does not poll or overlap another writer. A real source change follows repository RED/GREEN validation, a fresh exact-head review, and required CI. Only the Master may merge, through the expected-SHA merge gate. Pstack's `autonomous_landing` remains false and cannot waive repository or human approval gates.

Revert this Harness-only change to restore the prior local skills and source pins. There is no product/runtime migration.

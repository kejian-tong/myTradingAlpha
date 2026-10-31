# pstack compatibility

This Harness integration adapts a bounded set of skills from `cursor/plugins/pstack` version `0.15.36`, commit `4dd1d05818d19792e7cd6e818f1667f95f7e1dbe`, whose `pstack` subtree is `4719e1c4b4c43bac85d4206a8b41dd2899769c1c`. The previous integrated pin was version `0.15.32`, commit `e73df471cd4bd918367e99f3dd9c51bd53ddf5f0`, with subtree `880564357e051d7c7802da1cb5d8df1d0b008299`. The machine-readable source and adaptation contract is `.agents/skills/poteto-mode/compatibility.json`.

The selected source inventory remains 19 files: 16 previously selected sources and the three root skill sources—`ketchup`, `in-your-own-words`, and `sharpen`—introduced in PR #101. Exactly three selected source hashes change at the current pin (`arena`, `interrogate`, and `poteto-mode`); the other 16 selected source hashes are unchanged. The 16-skill local adaptation inventory and six authoritative Harness skills remain. Only the local `interrogate` adaptation changes in this update; the other 15 adaptations, including `arena` and `poteto-mode`, remain byte-identical. Skill frontmatter contains only the Codex `name` and `description`. The manifest remains schema version 1 and preserves its authority and portable-reference records. It retains the 17 exclusions established by the preceding integration (including `statechart`, `create-formal-verification-skill`, `maintain-formal-verification-skill`, and `ketchup-video`) and adds one exclusion for the changed but unselected `principle-explain-the-number` skill.

## Skill purposes

| Skill | Adaptation purpose |
| --- | --- |
| `architect` | Shape a repository-aligned design from explicit requirements and constraints. |
| `arena` | Compare design options sequentially within one context. |
| `figure-it-out` | Investigate unclear behavior through bounded repository evidence. |
| `how` | Explain how a repository capability or workflow works. |
| `in-your-own-words` | Restate the user's goal and problem without authorizing or executing work. |
| `interrogate` | Surface verified adversarial findings while retaining unexecuted material risks. |
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

PR #102 recorded the preceding canonical update from version `0.15.25`, commit `e5136d82418d2db3165ea1050d17577cd618cc05`, subtree `de8e53ebbeca0fe9351e950095e720655da08349`, to version `0.15.25`, commit `99743e9c151c8537cbbf1f98bb38f34ef3368453`, subtree `0d5fd349cbc77d054eed60f0e8cdfbea86321ff9`. Its one-commit and five-path counts describe that historical compression-only update, not the current 464-path synchronization.

## Current upstream change disposition

The current canonical source advances from version `0.15.32`, commit `e73df471cd4bd918367e99f3dd9c51bd53ddf5f0`, with `pstack` subtree `880564357e051d7c7802da1cb5d8df1d0b008299`, to version `0.15.36`, commit `4dd1d05818d19792e7cd6e818f1667f95f7e1dbe`, with `pstack` subtree `4719e1c4b4c43bac85d4206a8b41dd2899769c1c`. The exact tree delta contains 464 changed paths, each classified once below.

Three previously selected source hashes change (`arena`, `interrogate`, and `poteto-mode`). Only `interrogate` receives a local adaptation; its upstream workflow is narrowed to preserve repository authority, evidence boundaries, and unresolved material-risk handling. The changed `arena` and `poteto-mode` source bytes are excluded from adaptation. Their model-family fallback and cross-judge changes, mandatory first-message restatement, model defaults, and autopilot wording do not alter local skills or repository routing.

The paths for the 433 changed statechart entries, all other added scripts and playbooks, deleted interrogate references, and new guidance are excluded. Excluded implementation and corpus files were classified using frozen tree metadata; their scripts and corpus contents were not imported or run. The changed, unselected `principle-explain-the-number` capability, formal-verification skills, video, setup guidance, and remaining new playbooks are explicitly excluded from this sync. Version metadata paths provide provenance only. The complete mapping below records every changed path once.

| Upstream path | Disposition |
| --- | --- |
| `.cursor-plugin/plugin.json` | `version_provenance_only` |
| `README.md` | `excluded_source_documentation` |
| `docs/guide/04-design.md` | `excluded_source_documentation` |
| `docs/guide/06-verify-and-ship.md` | `excluded_source_documentation` |
| `docs/guide/07-overnight.md` | `excluded_source_documentation` |
| `docs/guide/10-recipes-and-pitfalls.md` | `excluded_source_documentation` |
| `plugin.json` | `version_provenance_only` |
| `skills/arena/SKILL.md` | `selected_source_requires_compatible_review` |
| `skills/create-formal-verification-skill/SKILL.md` | `excluded_existing_allowlist` |
| `skills/interrogate/SKILL.md` | `selected_source_requires_compatible_review` |
| `skills/interrogate/references/code-quality-review.md` | `excluded` |
| `skills/interrogate/references/lead-judgment.md` | `excluded` |
| `skills/interrogate/references/reviewer-prompt.md` | `excluded` |
| `skills/interrogate/references/rubric.md` | `excluded` |
| `skills/ketchup-video/SKILL.md` | `excluded_existing_allowlist` |
| `skills/poteto-help/SKILL.md` | `excluded_existing_allowlist` |
| `skills/poteto-help/references/recipes.md` | `excluded_existing_allowlist` |
| `skills/poteto-mode/SKILL.md` | `selected_source_requires_compatible_review` |
| `skills/poteto-mode/playbooks/autonomous-run.md` | `excluded` |
| `skills/poteto-mode/playbooks/autopilot-full.md` | `excluded` |
| `skills/poteto-mode/playbooks/autopilot-stack.md` | `excluded` |
| `skills/poteto-mode/playbooks/babysit.md` | `excluded` |
| `skills/poteto-mode/playbooks/multi-phase-plan.md` | `excluded` |
| `skills/poteto-mode/playbooks/opening-a-pr.md` | `excluded` |
| `skills/poteto-mode/playbooks/orchestrate.md` | `excluded` |
| `skills/poteto-mode/scripts/orch/orch.test.ts` | `excluded` |
| `skills/poteto-mode/scripts/orch/orch.ts` | `excluded` |
| `skills/poteto-mode/scripts/orch/store.ts` | `excluded` |
| `skills/poteto-mode/scripts/package.json` | `excluded` |
| `skills/principle-explain-the-number/SKILL.md` | `excluded_existing_allowlist` |
| `skills/setup-pstack/SKILL.md` | `excluded_existing_allowlist` |
| `skills/statechart/SKILL.md` | `excluded_pending_separate_scope` |
| `skills/statechart/references/render.md` | `excluded_pending_separate_scope` |
| `skills/statechart/scripts/backends/cfg.ts` | `excluded` |
| `skills/statechart/scripts/backends/mermaid.ts` | `excluded` |
| `skills/statechart/scripts/backends/plain-text.ts` | `excluded` |
| `skills/statechart/scripts/backends/report.ts` | `excluded` |
| `skills/statechart/scripts/bug-states.mjs` | `excluded` |
| `skills/statechart/scripts/chart-edges.mjs` | `excluded` |
| `skills/statechart/scripts/chart-parts.mjs` | `excluded` |
| `skills/statechart/scripts/chart-to-tla.mjs` | `excluded` |
| `skills/statechart/scripts/compare-charts.mjs` | `excluded` |
| `skills/statechart/scripts/frontends/config.ts` | `excluded` |
| `skills/statechart/scripts/frontends/dot.ts` | `excluded` |
| `skills/statechart/scripts/frontends/marks.ts` | `excluded` |
| `skills/statechart/scripts/frontends/messages.ts` | `excluded` |
| `skills/statechart/scripts/frontends/spec.ts` | `excluded` |
| `skills/statechart/scripts/frontends/trace.ts` | `excluded` |
| `skills/statechart/scripts/frontends/value.ts` | `excluded` |
| `skills/statechart/scripts/frontends/verdict.ts` | `excluded` |
| `skills/statechart/scripts/frontends/view.ts` | `excluded` |
| `skills/statechart/scripts/ir.ts` | `excluded` |
| `skills/statechart/scripts/lib.mjs` | `excluded` |
| `skills/statechart/scripts/map-view.mjs` | `excluded` |
| `skills/statechart/scripts/package.json` | `excluded` |
| `skills/statechart/scripts/passes/annotate.ts` | `excluded` |
| `skills/statechart/scripts/passes/label.ts` | `excluded` |
| `skills/statechart/scripts/passes/lift.ts` | `excluded` |
| `skills/statechart/scripts/passes/loop-check.ts` | `excluded` |
| `skills/statechart/scripts/passes/paths.ts` | `excluded` |
| `skills/statechart/scripts/passes/reach.ts` | `excluded` |
| `skills/statechart/scripts/passes/region-check.ts` | `excluded` |
| `skills/statechart/scripts/passes/regions.ts` | `excluded` |
| `skills/statechart/scripts/pipeline.ts` | `excluded` |
| `skills/statechart/scripts/property-loop.mjs` | `excluded` |
| `skills/statechart/scripts/read-check.mjs` | `excluded` |
| `skills/statechart/scripts/regions-chart.mjs` | `excluded` |
| `skills/statechart/scripts/render.mjs` | `excluded` |
| `skills/statechart/scripts/rule-book.mjs` | `excluded` |
| `skills/statechart/scripts/run.ts` | `excluded` |
| `skills/statechart/scripts/second-replay.mjs` | `excluded` |
| `skills/statechart/scripts/snapshot.mjs` | `excluded` |
| `skills/statechart/scripts/spec-text.mjs` | `excluded` |
| `skills/statechart/scripts/statechart` | `excluded` |
| `skills/statechart/scripts/statechart-help.mjs` | `excluded` |
| `skills/statechart/scripts/statechart.mjs` | `excluded` |
| `skills/statechart/scripts/statechart.ts` | `excluded` |
| `skills/statechart/scripts/test/ConfigOracle.java` | `excluded` |
| `skills/statechart/scripts/test/band.mmd` | `excluded` |
| `skills/statechart/scripts/test/chart.test.ts` | `excluded` |
| `skills/statechart/scripts/test/charts/Braces.mmd` | `excluded` |
| `skills/statechart/scripts/test/charts/Escapes.mmd` | `excluded` |
| `skills/statechart/scripts/test/charts/Phases.mmd` | `excluded` |
| `skills/statechart/scripts/test/cli.test.ts` | `excluded` |
| `skills/statechart/scripts/test/config-fuzz.test.ts` | `excluded` |
| `skills/statechart/scripts/test/corpus.test.ts` | `excluded` |
| `skills/statechart/scripts/test/corpus/Counter/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/Counter/Counter.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/Counter/Counter.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/Counter/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/Counter/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/Counter/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/Counter/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/Counter/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/CounterAction.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/CounterAction.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterAction/verdict-3.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/CounterDeadlock.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/CounterDeadlock.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterDeadlock/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/CounterFan.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/CounterFan.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterFan/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/ChartRun.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/CounterGuard.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/CounterGuard.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterGuard/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/CounterInitPast.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/CounterInitPast.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPast/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPastHolds/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPastHolds/CounterInitPastHolds.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPastHolds/CounterInitPastHolds.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPastHolds/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPastHolds/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPastHolds/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPastHolds/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInitPastHolds/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/CounterInstance.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/CounterInstance.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/CounterSteps.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterInstance/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/CounterJump.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/CounterJump.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterJump/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterLoop/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterLoop/CounterLoop.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterLoop/CounterLoop.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterLoop/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterLoop/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterLoop/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterLoop/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterLoop/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterLoop/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/CounterOrder.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/CounterOrder.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterOrder/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/CounterRules.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/CounterRules.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/Moves.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/verdict-3.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/verdict-3.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterRules/verdict-4.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/CounterStart.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/CounterStart.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStart/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStop/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStop/CounterStop.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStop/CounterStop.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStop/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStop/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStop/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStop/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterStop/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/CounterTie.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/CounterTie.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/verdict-3.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/verdict-3.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTie/verdict-4.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/CounterTieInGraph.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/CounterTieInGraph.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterTieInGraph/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/CounterView.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/CounterView.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/verdict-3.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/verdict-3.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/verdict-4.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/CounterView/view.mjs` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/DieHard.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/DieHard.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/DieHard/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/FirstRule.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/FirstRule.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/verdict-3.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/verdict-3.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/verdict-4.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/FirstRule/verdict-4.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/HiddenClock/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/HiddenClock/HiddenClock.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/HiddenClock/HiddenClock.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/HiddenClock/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/HiddenClock/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/HiddenClock/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/HiddenClock/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/HiddenClock/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/HiddenClock/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/Login/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/Login/Login.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/Login/Login.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/Login/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/Login/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/Login/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/Login/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/Login/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/Login/view.mjs` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginGuarded/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginGuarded/LoginGuarded.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginGuarded/LoginGuarded.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginGuarded/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginGuarded/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginGuarded/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginGuarded/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginGuarded/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginGuarded/view.mjs` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/LoginParallel.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/LoginParallel.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/LoginParallel/view.mjs` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/MediaPlayer.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/MediaPlayer.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayer/view.mjs` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerFixed/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerFixed/MediaPlayerFixed.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerFixed/MediaPlayerFixed.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerFixed/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerFixed/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerFixed/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerFixed/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerFixed/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerFixed/view.mjs` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/MediaPlayer.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/MediaPlayerProps.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/MediaPlayerProps.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/verdict-3.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/verdict-4.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/verdict-4.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/verdict-5.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/verdict-5.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/verdict-6.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/MediaPlayerProps/view.mjs` | `excluded` |
| `skills/statechart/scripts/test/corpus/PickWorker/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/PickWorker/PickWorker.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/PickWorker/PickWorker.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/PickWorker/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/PickWorker/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/PickWorker/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/PickWorker/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/PickWorker/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/Shadow.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/Shadow.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/ShadowLib.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/ShadowSub.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/Shadow/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/SpacedNames.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/SpacedNames.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/SpacedNames/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/TwoPhase.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/TwoPhase.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhase/view.mjs` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhaseFixed/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhaseFixed/TwoPhaseFixed.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhaseFixed/TwoPhaseFixed.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhaseFixed/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhaseFixed/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhaseFixed/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhaseFixed/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhaseFixed/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TwoPhaseFixed/view.mjs` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/ChartRun.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/TypeGuard.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/TypeGuard.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/TypeGuard/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/ChartRun.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/UserNoDeadlock.cfg` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/UserNoDeadlock.tla` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/chart.mmd` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/graph.dot` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/report.md` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/sany.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/verdict-1.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/verdict-1.out` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/verdict-2.exit` | `excluded` |
| `skills/statechart/scripts/test/corpus/UserNoDeadlock/verdict-2.out` | `excluded` |
| `skills/statechart/scripts/test/differential.test.ts` | `excluded` |
| `skills/statechart/scripts/test/grid/Grid.cfg` | `excluded` |
| `skills/statechart/scripts/test/grid/Grid.tla` | `excluded` |
| `skills/statechart/scripts/test/grid/sany.out` | `excluded` |
| `skills/statechart/scripts/test/java.ts` | `excluded` |
| `skills/statechart/scripts/test/labels.ts` | `excluded` |
| `skills/statechart/scripts/test/messages.test.ts` | `excluded` |
| `skills/statechart/scripts/test/pipeline.test.ts` | `excluded` |
| `skills/statechart/scripts/test/plain-tlc.test.ts` | `excluded` |
| `skills/statechart/scripts/test/regions.mmd` | `excluded` |
| `skills/statechart/scripts/test/render.test.ts` | `excluded` |
| `skills/statechart/scripts/test/statechart.test.mjs` | `excluded` |
| `skills/statechart/scripts/test/sync.mmd` | `excluded` |
| `skills/statechart/scripts/test/tlc-out.test.ts` | `excluded` |
| `skills/statechart/scripts/test/tlc.ts` | `excluded` |
| `skills/statechart/scripts/test/upload.mmd` | `excluded` |
| `skills/statechart/scripts/tlc-to-chart-args.mjs` | `excluded` |
| `skills/statechart/scripts/tlc-to-chart.mjs` | `excluded` |
| `skills/statechart/scripts/tlc-tools.mjs` | `excluded` |
| `skills/statechart/scripts/tsconfig.json` | `excluded` |
| `skills/statechart/scripts/ways-in.mjs` | `excluded` |
| `skills/statechart/scripts/worker.ts` | `excluded` |

The dispositions distinguish version-only provenance, excluded source documentation, the three selected source files that required compatibility assessment, already excluded allowlist files, additions reserved for separate scope, and excluded files. All 464 paths appear exactly once; only the `interrogate` source changes its adapted local bytes.

The adapted `interrogate` skill reports reproducible findings with the authorized command and actual versus expected output, grouped by root cause. A material policy or security risk that cannot safely be reproduced remains an unexecuted finding with its missing evidence, next authorized check, and gate effect. The skill remains read-only and supplemental. It adds no repair, scratch-file, fetched-script, nested delegation, credential, transcript, private-log, capture, or posting authority. It never replaces the exact-head reviewer, RED replay, exact-SHA CI, or Master merge gate.


## Repository authority and safety

Root and scoped `AGENTS.md` files and the six authoritative Harness skills remain authoritative. The Master may delegate bounded first-level work when repository policy allows it; non-Master nested delegation is prohibited. One production writer and the Master-owned writer lease remain required. Repository TDD, exact-head review, exact-SHA CI, and the Master merge gate remain unchanged. The Master alone merges. Delegated specialists do not push or merge.

`poteto-mode` routes the three skills introduced in PR #101 while preserving those boundaries. It does not choose models or provide fallback routes. The manifest preserves all authority and excluded-capability fields, including `autonomous_landing: false`, prohibited shipping/autopilot capabilities, unchanged PAPER/live/broker policy, and unchanged model routing. The skills add no setup, push, merge, deployment, promotion, credential, or roadmap-slice authority.

The user fork [`kejian-tong/pstack`](https://github.com/kejian-tong/pstack) is monitored separately from canonical upstream and the historical portable reference. Its frozen `main` commit is `9580c23696ac8d7abed0c166f2f9918800afb819`, with `pstack` tree `880564357e051d7c7802da1cb5d8df1d0b008299`, version `0.15.32`; it is an ancestor of the canonical source and contains no fork-only divergence. It does not replace canonical provenance, and the fork is not pushed by this sync. The historical portable reference remains `backnotprop/pstack` commit `124f622bcaeac490e7e9dac6af83f3ef9611d554`, which records the `cursor/plugins/pstack` version `0.15.9` snapshot at commit `e43c7ee26e0038c6c1fa8380dd34ce86ff94cb2a`. It informed portability review only. Canonical content and hashes come from the pinned `cursor/plugins/pstack` `0.15.36` source above.

The upstream MIT license terms and bytes are unchanged at this pin. Its SHA-256 is `bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e`; the applicable notice is [`PSTACK_MIT_NOTICE.md`](PSTACK_MIT_NOTICE.md).

## Weekly source synchronization

A native Master-gated synchronization is scheduled weekly on Saturday at 09:00 America/Chicago outside this repository. It is separate from pstack's excluded autonomous-landing capability. This PR adds no scheduler, automation settings, credentials, or runtime code.

Each run resolves and records the exact canonical source commit and `pstack` tree hash, then separately resolves the `kejian-tong/pstack` fork commit and tree. It inspects and attributes any fork-only divergence separately; fork-only content does not silently replace or become canonical upstream content. If the source pin is unchanged and no sync PR is pending, the run exits without creating a PR. If a PR is already pending, resume and reconcile that PR even when the upstream pin is unchanged; do not open a duplicate. When the canonical source changes, the sync uses only the bounded metadata and selected skill blobs needed for review.

Each scheduled run performs a bounded probe. On a transient source/API failure, rate limit, or active or blocked writer lease, it stops and backs off to a later scheduled run; it does not poll or overlap another writer. A real source change follows repository RED/GREEN validation, a fresh exact-head review, and required CI. Only the Master may merge, through the expected-SHA merge gate. Pstack's `autonomous_landing` remains false and cannot waive repository or human approval gates.

Revert this Harness-only change to restore the prior local skills and source pins. There is no product/runtime migration.

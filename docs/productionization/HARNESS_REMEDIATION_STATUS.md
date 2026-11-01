# Harness known-issue closure register

GitHub and current `main` are authoritative. This register links verified historical closures for HARNESS-EFF-06, HARNESS-PSTACK-01536 and DEPS-PYASN1-065. The active HARNESS-CLOSURE-01 / PR #114 scope remains in [AGENT_STATE](AGENT_STATE.md) and its [durable JIT](https://github.com/kejian-tong/myTradingAlpha/pull/114#issuecomment-6553084233); no completion is asserted here.

## Verified closures

| PR / scope | Reviewed source → merge (tree) | Review / gate / completion / validation |
|---|---|---|
| HARNESS-EFF-06 / #111 | `f5c5ea41382bbf3c33e1f2d5b3dc0df9185ba059` → `342b31134e2c9302b5ccb4ea91cd7bc08d17cc8f` (`f6a105adbe0d93917cf1a426a55b18ee5a7791a8`) | [review](https://github.com/kejian-tong/myTradingAlpha/pull/111#issuecomment-6540615142) · [gate](https://github.com/kejian-tong/myTradingAlpha/pull/111#issuecomment-6540633425) · [completion](https://github.com/kejian-tong/myTradingAlpha/pull/111#issuecomment-6540643196) · [validation](https://github.com/kejian-tong/myTradingAlpha/pull/111#issuecomment-6540483537) |
| HARNESS-PSTACK-01536 / #112 | `1232b9d40d629a06d93546b2df5e1fb2f02832ab` → `a657ffc7800358922c7043fb579916f7dadb969e` (`6c56ad3986e5ee4b546f45a665f95dbce0496a4d`) | [review](https://github.com/kejian-tong/myTradingAlpha/pull/112#issuecomment-6548726938) · [gate](https://github.com/kejian-tong/myTradingAlpha/pull/112#issuecomment-6548737518) · [completion](https://github.com/kejian-tong/myTradingAlpha/pull/112#issuecomment-6548796639) · [validation](https://github.com/kejian-tong/myTradingAlpha/pull/112#issuecomment-6548688628) |
| DEPS-PYASN1-065 / #113 | `acfdce1b5aa041b3f2e3efc7b4d3f6ea98699fa7` → `6ff575bcade4c2e541b64f48ee4936775e39eaee` (`e1e96da986bd5370dd07e03fbb64bb8a1e895b27`) | [review](https://github.com/kejian-tong/myTradingAlpha/pull/113#issuecomment-6552082623) · [gate](https://github.com/kejian-tong/myTradingAlpha/pull/113#issuecomment-6552090647) · [completion](https://github.com/kejian-tong/myTradingAlpha/pull/113#issuecomment-6552108186) · [local validation](https://github.com/kejian-tong/myTradingAlpha/pull/113#issuecomment-6552058166) · [CI coverage](https://github.com/kejian-tong/myTradingAlpha/pull/113#issuecomment-6551700703) |

### Recorded validation and limits

- PR #111 accounted for all 5,752 collected nodes across two shards: 5,748 passed, 4 existing skips and 69 passed subtests. On run `41165545533`, attempt 1, the same-attempt queue/setup-inclusive reduction was 34.48482770444026% (serial 11,666 seconds; partition plus aggregate 7,643 seconds). This is one historical paired result, not proof for a new head or a future speed guarantee.
- PR #112 recorded 5,750 passed, 4 skipped and 69 subtests in 10,600.21 seconds. A disclosed loss of optional diagnostic bytes remains unknown; the required evidence was completed and recorded separately.
- PR #113 recorded 5,750 passed, 4 skipped and 69 subtests in the 10,751.90-second full local run, with exact-head required CI evidence. RED/replay was approved N/A for this dependency-lock-only change; no repository executable, test or fixture changed.
- HARNESS-CLOSURE-01 changes documentation and tests only. Its benchmark status is N/A, never success; it makes no new runtime or performance claim.

## HARNESS-EFF-04 historical facts

The bounded EFF-04 work addressed Harness configuration, pricing inputs, dependency floors and validation reporting. It did not change production routing, trading behavior, broker authority, paper/live approval or later roadmap authorization.

| Area | Recorded change | Evidence boundary |
|---|---|---|
| Native compaction | Prospective project setting uses the 128,000-token total-scope threshold. The offline harness rejects wrong types/values, project context-window overrides and role-level capacity overrides. | Configuration is intent. It does not prove the host loaded the setting or which context survives compaction. Required reads and recovery references remain mandatory. |
| Benchmark pricing | Historical rates and 0.81/0.71 controls remain dated and unchanged. An explicit 2026-10-28 Work/Codex Standard card supports complete v2 usage; known-card mixtures reject. | Credits are derived estimates from asserted token usage. Current Enterprise USD, realized account charges and complete request-level billing are unknown. |
| Benchmark admission | Analysis rejects non-built-in or over-limit collections and non-built-in evaluation dates before callbacks or date operations. Whole-task, exclusive usage, observation ownership, reliability and pairing gates remain. | The analyzer is offline. A syntactically valid report does not authenticate its source or runtime. |
| Dependencies | The locked toolchain and seven reviewed package versions meet approved minimums. Matching lower bounds protect the documented pip fallback. | This is bounded security maintenance, not a general upgrade. Python remains >=3.10; CI remains on 3.14. |
| Validation | Full local and CI test commands retain unfiltered discovery and report the top 25 durations. | Durations are diagnostic measurements, not thresholds or proof of causal runtime savings. Master-owned full validation and CI remain required. |

Complete per-request billing coverage, account-specific realized charges, host identity and model/sandbox enforcement, actual configuration loading, retained context, and controlled before/after model-cost savings remain unknown external evidence requirements. Missing values stay unknown; credits are not USD, and telemetry gaps are not evidence. No benchmark here is a routing, review, merge or promotion decision.

Official historical references: [ChatGPT Work pricing](https://learn.chatgpt.com/docs/pricing), [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference), [uv 0.13.5](https://github.com/astral-sh/uv/releases/tag/0.13.5), and [setup-uv v10.3.2](https://github.com/astral-sh/setup-uv/releases/tag/v10.3.2).

## HARNESS-EFF-05 historical task-usage follow-up

The EFF-05 follow-up added a pure summarizer for caller-supplied pseudonymous agent inventory and response usage, plus guidance for interruptible work monitoring and context recovery. It changed no production code, runtime routing, legacy lifecycle telemetry, v2 usage accounting or benchmark pricing. The task summary is qualified to its explicit inventory; missing agents, responses and per-metric usage remain unknown. Its values do not authenticate runtime provenance, establish complete billing, or prove context-retention or cost savings. Authorization, exact-head validation, review and merge gates remain separate requirements.

## Rollback

Revert native compaction config, checker policy and corresponding guidance together. Current-card support can be reverted without rewriting historical records. Restore prior duration reporting with the matching policy/tests. Retain reviewed security floors when reverting unrelated Harness behavior; lowering them requires a separate reviewed decision. No persisted product schema or research artifact migration is introduced.

Revert the EFF-05 task-usage helper and focused contract tests with its guidance. Preserve the historical EFF-04 status and rollback facts above. No persisted product schema or research artifact migration is introduced.

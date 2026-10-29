# HARNESS-EFF-04 remediation status

This PR closes the remaining bounded Harness configuration, pricing-input, dependency-floor and
validation-reporting gaps. It does not change production routing, trading behavior, broker authority,
paper/live approval, or later roadmap authorization.

| Area | Repository change | Evidence boundary |
| --- | --- | --- |
| Native compaction | Prospective project setting uses the 128,000-token total-scope threshold. The offline harness rejects wrong types/values, project context-window overrides and role-level capacity overrides. | Configuration is intent. It does not prove the current host loaded the setting or guarantee which context survives compaction. Required reads and recovery references remain mandatory. |
| Benchmark pricing | Historical rates and 0.81/0.71 controls remain dated and unchanged. An explicit 2026-10-28 Work/Codex Standard card supports complete v2 usage; known-card mixtures reject. | Credits are derived estimates from asserted token usage. Current Enterprise USD, realized account charges and complete request-level billing are unknown. |
| Benchmark admission | Analysis rejects non-built-in or over-limit collections and non-built-in evaluation dates before callbacks or date operations. Whole-task, exclusive usage, observation ownership, reliability and pairing gates remain. | The analyzer is offline. A syntactically valid report does not authenticate its source or runtime. |
| Dependencies | The locked toolchain and seven reviewed package versions meet approved minimums. Matching lower bounds protect the documented pip fallback. | This is a bounded security maintenance update, not a general upgrade. Python remains >=3.10; CI remains on 3.14. |
| Validation | Full local and CI test commands retain unfiltered discovery and report the top 25 durations. | Durations are diagnostic measurements, not thresholds or proof of causal runtime savings. Master-owned full validation and CI remain required. |

## Remaining evidence requirements

The repository cannot establish complete per-request billing coverage, account-specific realized
charges, authenticated host model/sandbox enforcement, or controlled before/after model-cost savings.
These remain external evidence prerequisites. Missing values stay unknown; the benchmark does not infer
USD from credits, API prices or telemetry gaps. The current card is not a routing, review, merge or
promotion decision.

Official references checked for this change: [ChatGPT Work pricing](https://learn.chatgpt.com/docs/pricing),
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference),
[uv 0.13.5 release](https://github.com/astral-sh/uv/releases/tag/0.13.5), and
[setup-uv v10.3.2](https://github.com/astral-sh/setup-uv/releases/tag/v10.3.2).

## Rollback

Revert native compaction config, checker policy and corresponding guidance together. Current-card support
can be reverted without rewriting historical records. Restore prior duration reporting with the matching
policy/tests. Retain reviewed security floors when reverting unrelated Harness behavior; lowering them
requires a separate reviewed decision. No persisted product schema or research artifact migration is
introduced.

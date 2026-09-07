# Codex Feature Adoption Watchlist

Status: execution-harness change-control policy. The features below are intentionally **not** part of the
current myTradingAlpha productionization harness. This is a deliberate architecture decision, not missing
configuration. Any adoption requires a separate reviewed harness PR with a narrow pilot, rollback plan,
and exact-head validation; it must not arrive incidentally inside a product-roadmap PR.

## Current decisions

| Capability | Current status | Why | Earliest reconsideration trigger |
| --- | --- | --- | --- |
| project-local `.codex/rules/*.rules` | watch only | Codex Rules are experimental and can change; the current sandbox, master-only delegation, hooks and GitHub gates already constrain execution | Rules become stable enough for a small command-policy pilot with `codex execpolicy check` regression cases |
| Permission Profiles (`default_permissions` / `[permissions]`) | watch only | Permission Profiles are Beta and do not compose with the current `sandbox_mode`-based agent isolation; loaded `sandbox_mode` causes Codex to use the older sandbox system | permission profiles mature and a separate read-only-role pilot proves equivalent or stronger isolation before any migration |
| Codex Memories (`features.memories`) | off / watch only | this repository requires GitHub/repository-grounded, cross-session and cross-machine auditable recovery; hidden/local learned state must not become execution authority | a future design proves deterministic export/audit/recovery semantics and demonstrates clear value beyond `AGENT_STATE.md`, PR evidence and scoped instructions |
| OpenTelemetry exporters (`[otel]`) | watch only | current narrow Git-common-dir telemetry captures the routing/concurrency evidence this single repository needs without exporting prompts or broad runtime traces | multi-repo/team observability creates a concrete backend, retention, privacy and access-control requirement |
| repo-level Codex plugin configuration (`[plugins]`) | watch only | the harness is currently project-specific and already has repo Skills plus a capability-isolated MCP researcher; plugin packaging adds distribution/governance surface without current reuse benefit | the harness is deliberately reused across multiple repositories or teams and plugin packaging has a defined owner/versioning policy |

Official maturity/compatibility facts are mutable external facts. Re-check current OpenAI Codex
documentation before an adoption proposal; this file records the reviewed decision, not a claim that a
feature can never become appropriate.

## Guardrail semantics

`scripts/check_agent_harness.py` fails the reviewed project configuration when it detects any of these
unapproved adoption surfaces:

- a project-local `.codex/rules/` directory;
- `default_permissions` or a top-level `[permissions]` table in `.codex/config.toml`;
- `features.memories = true` or a top-level `[memories]` table;
- a top-level `[otel]` table;
- a top-level `[plugins]` table.

The guard is intentionally scoped to **project-repository configuration**. It does not claim to inspect or
control a user's global Codex layer, organization-managed requirements, installed ChatGPT plugins, or
runtime features outside this repository. If external managed policy conflicts with the project harness,
record the runtime conflict rather than claiming the project configuration enforced something it cannot
observe.

## Adoption protocol

A future proposal to adopt one watched capability must, at minimum:

1. cite current official feature maturity and compatibility semantics;
2. define the exact problem not adequately solved by the current harness;
3. use the smallest isolated pilot and name the affected roles/surfaces;
4. include deterministic contract/failure-injection tests and rollback;
5. preserve master-only orchestration, one production writer, exact-head review, human paper/live gates,
   GitHub-grounded recovery and capability isolation;
6. pass the required harness/static GitHub status, full CI, CodeQL and Dependency Review;
7. change this watchlist and the offline validator in the same reviewed PR.

Do not disable the guard merely to make an unrelated roadmap PR pass.

## Official references checked for this policy

- Codex Rules: https://developers.openai.com/codex/rules
- Codex Permission Profiles: https://developers.openai.com/codex/permissions
- Codex configuration reference: https://developers.openai.com/codex/config-reference

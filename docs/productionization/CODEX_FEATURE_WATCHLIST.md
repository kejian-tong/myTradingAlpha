# Codex Feature Adoption Watchlist

Status: execution-harness change-control policy. The features below are intentionally **not** part of the
current myTradingAlpha productionization harness. This is a deliberate architecture decision, not missing
configuration. Any adoption requires a separate reviewed harness PR with a narrow pilot, rollback plan,
and exact-head validation; it must not arrive incidentally inside a product-roadmap PR.

## Current decisions

| Capability | Current status | Why | Earliest reconsideration trigger |
| --- | --- | --- | --- |
| project-local `.codex/rules/*.rules` | watch only | Codex Rules are experimental and can change; the current sandbox, master-only delegation, hooks and GitHub gates already constrain execution | Rules become stable enough for a small command-policy pilot with `codex execpolicy check` regression cases |
| Permission Profiles (`default_permissions` / `[permissions]`) | global migration watch only | Permission Profiles are Beta and do not compose with the current `sandbox_mode`-based agent isolation; ordinary read-only lanes instead use a zero-tool static bundle with no local command dispatch | permission profiles mature and a separate pilot proves equivalent or stronger isolation before any migration |
| project Apps (`features.apps`) | explicitly disabled | productionization sessions do not need Codex Apps; the project setting records configuration intent without claiming control over global, installed-plugin, or managed runtime Apps | a separate reviewed pilot defines the required runtime capability receipt and verifies the actual App surface in a fresh session |
| Codex Memories (`features.memories`) | off / watch only | this repository requires GitHub/repository-grounded, cross-session and cross-machine auditable recovery; hidden/local learned state must not become execution authority | a future design proves deterministic export/audit/recovery semantics and demonstrates clear value beyond `AGENT_STATE.md`, PR evidence and scoped instructions |
| OpenTelemetry exporters (`[otel]`) | watch only | current narrow Git-common-dir telemetry captures the routing/concurrency evidence this single repository needs without exporting prompts or broad runtime traces | multi-repo/team observability creates a concrete backend, retention, privacy and access-control requirement |
| repo-level Codex plugin configuration (`[plugins]`) | watch only | the harness is currently project-specific and already has repo Skills; plugin packaging adds distribution/governance surface without current reuse benefit | the harness is deliberately reused across multiple repositories or teams and plugin packaging has a defined owner/versioning policy |

Official maturity/compatibility facts are mutable external facts. Re-check current OpenAI Codex
documentation before an adoption proposal; this file records the reviewed decision, not a claim that a
feature can never become appropriate.

## Guardrail semantics

`scripts/check_agent_harness.py` checks project configuration intent and fails the reviewed project
configuration when it detects any of these unapproved adoption surfaces or boundaries:

- a project-local `.codex/rules/` directory;
- `default_permissions` or a top-level `[permissions]` table in `.codex/config.toml`;
- a missing or non-false project `features.apps` setting;
- a project-level `[mcp_servers]` table;
- `features.memories = true` or a top-level `[memories]` table;
- a top-level `[otel]` table;
- a top-level `[plugins]` table.

The zero-tool static launcher does not configure a Permission Profile and does not add
`default_permissions` to `.codex/config.toml`. Its boundary is the exact runtime's proven absence of a
model local-command tool plus canonical prompt-only candidate delivery, exact signed-client identity,
and pre-exec handshake/runtime observation.

No repository role declares an MCP server. `external_spec_researcher` fails before model start until a
separate reviewed remote-isolation design exists, and it never receives candidate bundles. These checks
describe checked-in configuration intent only. The guard does not claim to inspect or control a user's
global Codex layer, organization-managed requirements, installed plugins, or other Apps. If external
managed policy conflicts with the project harness, record the runtime conflict rather than claiming the
project configuration enforced something it cannot observe.

## Adoption protocol

A future proposal to adopt one watched capability must, at minimum:

1. cite current official feature maturity and compatibility semantics;
2. define the exact problem not adequately solved by the current harness;
3. use the smallest isolated pilot and name the affected roles/surfaces;
4. include deterministic contract/failure-injection tests and rollback;
5. preserve master-only orchestration, one production writer, exact-head review, human paper/live gates,
   GitHub-grounded recovery and independently observed runtime capability boundaries;
6. pass the required harness/static GitHub status, full CI, CodeQL and Dependency Review;
7. change this watchlist and the offline validator in the same reviewed PR.

Do not disable the guard merely to make an unrelated roadmap PR pass.

## Official references checked for this policy

- Codex Rules: https://developers.openai.com/codex/rules
- Codex Permission Profiles: https://developers.openai.com/codex/permissions
- Codex configuration reference: https://developers.openai.com/codex/config-reference

# Upstream Research Namespace Instructions

This file applies to `tradingagents/**` and supplements root `AGENTS.md`.

## Upstream-derived ownership

`tradingagents/` is the upstream-derived Research Graph. Preserve it as a compatibility boundary rather
than turning it into the production application namespace.

- No module under `tradingagents` may import `mytradingalpha`.
- Production-owned behavior belongs under `mytradingalpha` and may adapt research behavior only through
  the approved `mytradingalpha.research` boundary.
- Do not move production contracts, persistence, risk, broker, promotion, or execution authority into
  this namespace.

## Compatibility-first changes

Unless a specifically authorized maintenance task requires an upstream-derived fix, prefer not to edit
this tree during productionization slices. When an edit is unavoidable:

- preserve existing public imports and CLI behavior;
- preserve configuration/environment precedence and default runtime behavior;
- keep the patch minimal and backward compatible;
- do not opportunistically refactor unrelated research code;
- add focused regression coverage that proves the compatibility surface remains intact.

Do not rename the Python distribution or rewrite persisted research artifacts merely to align with
production-owned schemas.

## External behavior

Research/provider/model calls retain their existing explicit boundaries. Do not introduce production
broker writes, portfolio authority, live credentials, or promotion decisions here. New deterministic
production evidence/contracts should be created in production-owned modules rather than hidden inside
research graph internals.

When current upstream reality and productionization documentation disagree, report the drift to the
master. Do not resolve it by silently coupling the two namespaces.

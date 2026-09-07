# Production Namespace Instructions

This file applies to `mytradingalpha/**` and supplements root `AGENTS.md`.

## Ownership and dependency boundaries

`mytradingalpha/` is the production-owned namespace. Preserve the root research/production boundary:

- only `mytradingalpha.research` may import or adapt `tradingagents`;
- other production bounded contexts must consume production-owned contracts/interfaces and must not
  import `tradingagents` directly;
- production domains must not reach into another domain's persistence internals;
- keep dependency direction explicit and enforceable by static tests where practical.

Prefer additive, typed, deterministic contracts over broad framework abstractions. Do not introduce
future services, registries, persistence layers, broker adapters, or generalized DI merely because a
later roadmap phase may need them.

## Compatibility

Unless the active roadmap slice explicitly changes a contract, preserve existing package/public import
behavior, serialized forms, configuration/environment precedence, and already sealed artifacts. Avoid
opportunistic renames, moves, dependency upgrades, or broad refactors.

Production code must not change `tradingagents` CLI/runtime behavior indirectly. Research-to-production
adaptation belongs at the approved boundary rather than through hidden cross-imports.

## Determinism and failure semantics

For PIT, evidence, backtest, accounting, risk, execution, OMS, and promotion logic, treat time,
provenance, ordering, idempotency, reconciliation, numerical semantics, and explicit error behavior as
first-class contracts. Fail closed when a required safety/correctness invariant cannot be established.
Do not infer successful side effects from intent, retries, or missing acknowledgements.

Keep tests network-free and deterministic by default. External-service behavior must be an explicit
integration/smoke boundary and may not become a required unit-test dependency.

## Side-effect safety

Do not add broker, paper, or live order side effects before their assigned roadmap phase and merged
prerequisites. Before Phase 09, no live broker write is permitted. Never place credentials, real account
identifiers, example secrets, or permissive live defaults into source/configuration.

Kill switches, halts, idempotency, reconciliation, credential isolation, and promotion gates are
fail-closed invariants when in scope. No autonomous agent may waive a human paper/live promotion gate or
approve its own externally consequential behavior.

## Implementation workflow

Follow the root single-writer rule. For roadmap work, read the applicable
`docs/productionization/AGENTS.md`, phase documents, and JIT contract before editing. Use the repo TDD
skill for executable changes, make the smallest GREEN implementation, and keep refactors within the JIT
boundary.

Do not treat passing new tests as sufficient if existing productionization, package/import, dependency,
or compatibility checks are affected. Record exact validation evidence and unresolved limitations.

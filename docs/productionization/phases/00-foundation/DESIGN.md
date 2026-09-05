# Phase 00 — Foundation Design

Status: implemented at the current contract scope. FND-01 through FND-04 have shipped; this is not a later-phase readiness claim. This phase establishes ownership and durable interfaces without changing the current Research Graph behavior.

## Goals

- Create the future `mytradingalpha/` package boundary and dependency rule: no file under `tradingagents/` imports `mytradingalpha`; only `mytradingalpha.research` imports `tradingagents` through an adapter.
- Define versioned Pydantic contracts, stable IDs, UTC timestamps, and Decimal serialization.
- Establish mode/variant configuration, secret redaction, correlation IDs, a single `uv.lock` mechanism, and documentation/CI checks.

## Scope

Package skeleton, contract registry, schema-version policy, configuration loader, structured logging/redaction, import/dependency checks, `uv.lock` and locked CI migration, and Markdown validation.

## Non-goals

No data ingestion, PIT archive, quant model, portfolio allocation, broker integration, order submission, database migration, or live deployment.

## Dependencies

The baseline is [`README.md`](../../../../README.md), [`pyproject.toml`](../../../../pyproject.toml), [`tradingagents/default_config.py`](../../../../tradingagents/default_config.py), and the existing CI/security workflows. There is no dependency on later phases.

## Components and dataflow

```text
validated config -> RunContext/IDs -> domain services -> structured logs/artifacts
                         |
                         +-> schema registry and dependency-direction check
```

All downstream packages import shared contracts, not one another's persistence details. Configuration is resolved before a run starts and is included in the run manifest.

## Current integration points

- [`tradingagents/default_config.py`](../../../../tradingagents/default_config.py) is the existing configuration seam; production config must be additive.
- [`tradingagents/__init__.py`](../../../../tradingagents/__init__.py) and package discovery in [`pyproject.toml`](../../../../pyproject.toml) define current imports.
- [`README.md`](../../../../README.md) and [`.github/workflows/ci.yml`](../../../../.github/workflows/ci.yml) are documentation/validation entry points.

## Interfaces and invariants

`RunContext` requires `run_id`, `mode`, `variant_id`, `decision_time`, `knowledge_cutoff`, `earliest_execution_time`, `bundle_id`, and `bundle_hash`. Enforce `knowledge_cutoff <= decision_time < earliest_execution_time`, UTC-aware timestamps, stable IDs, and `schema_version` on persisted records. Secret values are never serialized into logs or artifacts. The dependency check rejects every import from `tradingagents` into `mytradingalpha`; only `mytradingalpha.research` may import `tradingagents`.

## Decisions and alternatives

- Use a new package rather than expanding `tradingagents` to protect upstream-derived compatibility.
- Use Pydantic validation plus explicit schema versions rather than untyped dictionaries.
- Use structured JSON logs and a redaction filter rather than ad hoc string filtering.
- Adopt `uv.lock` as the single lock mechanism because `pyproject.toml` remains the source of declared dependencies. Migrate current pip lower-bound CI to locked `uv sync` after review, preserve Python 3.10–3.14, and retain a documented pip fallback for rollback.

## Failure, security, and observability

Invalid config or schema stops before any decision. Redaction tests cover API keys, access tokens, broker credentials, and private identifiers. Every log carries a correlation/run ID, mode, variant, and schema version without secrets. A missing or invalid schema version is an error, not a best-effort parse.

## Migration and rollback

The package is additive and opt-in. Existing callers continue importing `tradingagents` unchanged. If a new validator causes a false rejection, disable only the new entry point and keep the original config path; do not alter or delete existing artifacts. Schema migrations are additive readers first, followed by writer updates.

## Acceptance and gate

Pass requires importable package modules, validated example config, redaction/property tests, a dependency-direction check, Markdown/link/fence checks, and the current test/lint jobs green. `insufficient_evidence` blocks downstream implementation; it does not authorize a waiver.

# Phase 00 — Foundation Implementation

Commands in this document are planned commands until an implementation record shows that they were executed.

## Ordered PR/work packages

1. **FND-01** — add package ownership and empty bounded-context modules.
2. **FND-02** — add shared IDs, enums, Pydantic schemas, and schema-version registry.
3. **FND-03** — add production config resolution, redaction, and correlation logging.
4. **FND-04** — adopt `uv.lock`, migrate CI to locked sync, and add documentation contract checks.

## Exact existing files to touch

- [`README.md`](../../../../README.md) for the navigation link only.
- [`pyproject.toml`](../../../../pyproject.toml) for package discovery and only approved development tooling.
- [`tradingagents/default_config.py`](../../../../tradingagents/default_config.py) only where an additive config bridge is necessary.
- [`.github/workflows/ci.yml`](../../../../.github/workflows/ci.yml) only for validation invocation; no runtime behavior changes.

## Proposed files, classes, and APIs

- `mytradingalpha/contracts/common.py`: `UtcDateTime`, `StableId`, `DecimalString`.
- `mytradingalpha/contracts/versions.py`: `CURRENT_SCHEMA_VERSION`, `SchemaRegistry`, `MigrationPlan`.
- `mytradingalpha/contracts/schemas.py`: `RunContext` and shared contract base model.
- `mytradingalpha/contracts/reason_codes.py`: stable reason-code literals.
- `mytradingalpha/ops/config.py`: `ProductionConfig.load()`, `ModeConfig`, `NetworkPolicy`, and `BrokerConfig`.
- `mytradingalpha/ops/logging.py`: `RedactionFilter`, `configure_logging()`, `correlation_scope()`.
- `uv.lock` generated from [`pyproject.toml`](../../../../pyproject.toml).
- `scripts/check_dependency_direction.py`, `scripts/check_markdown_contracts.py`, and `scripts/check_lock_consistency.py`.

## Schema and pseudocode

```text
load config -> validate mode/variant/calendar -> reject missing required fields
             -> generate run_id/correlation_id -> emit RunContext
             -> pass only validated immutable context to services

serialize(record): redact secrets -> validate schema_version -> Decimal as string
```

`RunContext` validation must reject naive timestamps, reversed time boundaries, empty bundle IDs, any historical component egress, and `live_pilot` with a default-enabled `live_write_enabled` flag. In forward paper, only explicitly approved `data_capture_egress`, `model_provider_egress`, and `paper_broker_egress` may be enabled; `research_tool_egress` and `live_broker_egress` remain false. The logger must redact values by field name and never log the raw configuration object.

## Red-green-refactor

1. Red: add failing tests for reversed times, missing mode, secret log leakage, unknown schema version, illegal import direction, and lockfile drift.
2. Green: implement the smallest validators, registry, loader, filter, and scripts to satisfy those tests.
3. Refactor: split common contracts from ops concerns, freeze public names, and run format/lint without changing semantics.

## Exact tests and fixtures

- `tests/productionization/test_run_context.py`: valid historical/paper contexts, boundary equality, and invalid ordering.
- `tests/productionization/test_schema_registry.py`: version lookup, additive migration, unknown version rejection.
- `tests/productionization/test_config_redaction.py`: precedence, component-scoped egress, default-false paper/live flags, API-key/access-token redaction.
- `tests/productionization/test_dependency_direction.py`: every `tradingagents` -> `mytradingalpha` import is forbidden; only the research adapter may import `tradingagents`.
- `tests/productionization/test_lock_consistency.py`: `pyproject.toml`/`uv.lock` consistency and Python 3.10–3.14 resolution.
- `tests/productionization/fixtures/config/{historical,paper,live-read-only}.yaml` with no secrets or fixed live limits.
- `tests/productionization/fixtures/logs/secret-bearing-record.json` for redaction assertions.

## Validation commands

```bash
python scripts/check_dependency_direction.py
python scripts/check_markdown_contracts.py
python scripts/check_lock_consistency.py
ruff check .
python -m pytest -q tests/productionization
python -m pytest -q
git diff --check
```

These are planned for the implementation PR; the phase report must record exact output rather than infer success.

## Migration and compatibility

Do not rename or remove current `tradingagents` imports. The production package is not included in the existing runtime path until its schemas are stable. Additive config keys use a distinct namespace and preserve current environment precedence. Migrate current pip lower-bound CI to `uv sync --locked` while retaining a documented pip fallback; if lock resolution fails, restore the prior pip job and keep `uv.lock` unchanged. Persisted future records include `schema_version`; no current memory-log/report record is rewritten.

## Definition of done

- All four FND PRs are merged in order with focused tests.
- Contract examples validate without network or credentials.
- Dependency direction and redaction checks run in CI.
- Existing test/lint behavior is unchanged.
- A `GateEvidence` record has status `pass` with commands and artifact links; otherwise status is `fail` or `insufficient_evidence` and downstream work stops.

## Evidence and rollback

Evidence is the schema snapshot, config fixture hashes, test output, dependency graph output, and CI run URL. Rollback is a revert of the additive package/check scripts or disabling the new config bridge; existing Research Graph artifacts and imports remain available. No external side effect is permitted.

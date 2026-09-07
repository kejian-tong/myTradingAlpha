# Productionization Test Instructions

This file applies to `tests/productionization/**` and supplements root `AGENTS.md` and, when roadmap
work is involved, `docs/productionization/AGENTS.md`.

## Test contract

Tests must express observable behavior, architecture invariants, failure semantics, or durable evidence.
Do not mirror implementation structure merely to make coverage appear complete. Negative and boundary
cases are first-class for time/provenance, accounting, idempotency, reconciliation, security,
serialization, and promotion logic.

Tests are deterministic and network-free by default. Do not make unit/contract tests depend on live
models, brokers, data vendors, credentials, wall-clock timing, random external state, or internet
availability. Existing explicit integration/smoke tests remain separate and opt-in where applicable.

## RED evidence

For executable roadmap behavior, use the `tdd-red-green-evidence` repo skill. The dedicated RED commit
must contain only the smallest tests/fixtures/test harness needed to express the active PR contract.
The focused RED command must fail for the expected missing/incorrect behavior rather than collection,
syntax, dependency-install, or unrelated environment errors.

Do not weaken pre-existing assertions to manufacture RED. A narrow current-slice migration of an
absence assertion is acceptable only when the active roadmap slice now owns that previously forbidden
file/behavior and later-slice absence rules remain intact.

## Architecture and safety tests

Prefer deterministic AST/source/static inspection for dependency-direction and forbidden-side-effect
rules when importing application modules would execute provider/model/network behavior. Fail closed on
unknown or ambiguous constructs rather than silently accepting a rule that cannot be checked safely.

Keep explicit coverage for research/production dependency direction, package/import compatibility,
serialized contracts, no-current-data fallback, no-callable/loader boundaries, and paper/live safety
invariants as their roadmap phases require.

## Reviewability

Use clear fixture names and bounded data. Avoid giant golden blobs when a smaller canonical fixture can
prove the same invariant. When canonical bytes/hashes are the contract, keep exact expected values and
explain intentional version changes.

A passing focused test is not sufficient merge evidence by itself. Run the applicable productionization
regression set and the repository validation/CI floor required by the JIT contract.

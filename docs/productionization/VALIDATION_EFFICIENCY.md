# Validation ownership and evidence reuse

## Ownership

Default owner: Master. The Master owns one complete, unfiltered local full suite for each frozen candidate head. The full local suite command is `uv run --no-sync python -m pytest -q`; do not add selectors, skips, or hidden pytest environment settings. The Master records a different designated owner only when assigning that run. Writers perform focused tests and static checks, then stop before the full local run. Full GitHub CI remains a separate required run of the unfiltered test job, Ruff, clean-install smoke, and applicable required checks.

A fresh controlling reviewer verifies the committed RED replay, focused and negative checks, complete source, the actual local full-run evidence, and final-head CI. The reviewer may verify the completed local full run from its native evidence without repeating it when the source, runtime, and command match and no material concern is found. The reviewer may run it again when evidence is missing, inconsistent, or raises a material concern. A model summary, caller-created receipt, status label, incomplete log, or claimed run is not execution evidence.

## Evidence record and reuse

For each full local run, record the source SHA and tree SHA, base SHA, checkout SHA and tree SHA, designated owner, exact command including selectors (write `none` for the unfiltered command), Python/uv/lock/environment identity, completion and exit status, pass/fail/skip counts and skip reasons, full logs, and before/after cleanliness together with each SHA and tree. For CI, record the CI run/job/attempt, candidate SHA, completion and conclusion, and native log reference. Keep complete artifacts durable and summaries bounded. Do not put secrets, transcripts, or user-specific absolute paths in the evidence record.

Reuse only completed verifiable evidence for an identical source/runtime/command. A new commit invalidates affected proof. A source, tree, runtime, command, or checkout mismatch; incomplete log; missing identity; failure; or missing before/after cleanliness invalidates the affected evidence. Re-run the affected proof against the exact frozen head. Do not reuse results from another SHA or infer completion from a green summary. The full local run, all required CI, independent review, and Master gate remain mandatory; human paper/live and other approval gates are unchanged.

## CI coverage and aggregation

The CI `test` job remains the unfiltered `uv run --no-sync pytest -q` execution. Pytest discovery remains `testpaths = ["tests"]` with the checked-in `addopts`, so productionization tests run within the full suite. The Foundation status now aggregates the same-workflow `test`, `lint`, and `smoke-install` job results. It uses the `needs` dependency set and result context, with `always()` so its short metadata check can report failed or skipped prerequisites; its Bash step accepts only three exact `success` values and otherwise exits nonzero with a fixed diagnostic. It performs no checkout, setup, install, test execution, network call, or artifact collection.

GitHub documents [`needs`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds), the [`needs` result context](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#needs-context), and [`always()`](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#always). These are same-workflow dependency results, not authenticated receipts for a local run or evidence of a separate execution. Whole-workflow cancellation may prevent a completed aggregate; a missing or cancelled required check does not pass. CodeQL and Dependency Review remain independent required checks and are not represented by the Foundation aggregate.

## Metrics

Compare the number of full productionization-suite executions and setup steps before and after deduplication. Where comparable runner/runtime evidence exists, record elapsed job and workflow times with the matching head, run, job, and attempt. Do not infer billing, model-token savings, or financial performance from these measurements. No new runtime collector or cache is introduced.

## Rollback

The rollback restores the prior Foundation installation and productionization test execution, its matching contract tests, and the corresponding ownership description in a reviewed change. Preserve state and prior evidence, then rerun affected exact-head validation, review, and required CI.

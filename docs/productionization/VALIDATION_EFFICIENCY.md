# Validation ownership and evidence reuse

## Ownership

Default owner: Master. The Master owns one complete, unfiltered local full suite for each frozen candidate head. The full local suite command is `uv run --no-sync python -m pytest -q --durations=25`; do not add selectors, skips, or hidden pytest environment settings. The Master records a different designated owner only when assigning that run. Writers perform focused tests and static checks, then stop before the full local run. Full GitHub CI remains a separate required run of the unfiltered test job, Ruff, clean-install smoke, and applicable required checks.

A fresh controlling reviewer verifies the committed RED replay, focused and negative checks, complete source, the actual local full-run evidence, and final-head CI. The reviewer may verify the completed local full run from its native evidence without repeating it when the source, runtime, and command match and no material concern is found. The reviewer may run it again when evidence is missing, inconsistent, or raises a material concern. A model summary, caller-created receipt, status label, incomplete log, or claimed run is not execution evidence.

## Evidence record and reuse

For each full local run, record the source SHA and tree SHA, base SHA, checkout SHA and tree SHA, designated owner, exact command including selectors (write `none` for the unfiltered command), Python/uv/lock/environment identity, completion and exit status, pass/fail/skip counts and skip reasons, full logs, and before/after cleanliness together with each SHA and tree. For CI, record the CI run/job/attempt, candidate SHA, completion and conclusion, and native log reference. Keep complete artifacts durable and summaries bounded. Do not put secrets, transcripts, or user-specific absolute paths in the evidence record.

Reuse only completed verifiable evidence for an identical source/runtime/command. A new commit invalidates affected proof. A source, tree, runtime, command, or checkout mismatch; incomplete log; missing identity; failure; or missing before/after cleanliness invalidates the affected evidence. Re-run the affected proof against the exact frozen head. Do not reuse results from another SHA or infer completion from a green summary. The full local run, all required CI, independent review, and Master gate remain mandatory; human paper/live and other approval gates are unchanged.

## CI coverage and aggregation

The CI `test` job remains the unfiltered `uv run --no-sync pytest -q --durations=25` execution. Pytest discovery remains `testpaths = ["tests"]` with the checked-in `addopts`, so productionization tests run within the full suite. The Foundation status now aggregates the same-workflow `test`, `lint`, and `smoke-install` job results. It uses the `needs` dependency set and result context, with `always()` so its short metadata check can report failed or skipped prerequisites; its Bash step accepts only three exact `success` values and otherwise exits nonzero with a fixed diagnostic. It performs no checkout, setup, install, test execution, network call, or artifact collection.

GitHub documents [`needs`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds), the [`needs` result context](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#needs-context), and [`always()`](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#always). These are same-workflow dependency results, not authenticated receipts for a local run or evidence of a separate execution. Whole-workflow cancellation may prevent a completed aggregate; a missing or cancelled required check does not pass. CodeQL and Dependency Review remain independent required checks and are not represented by the Foundation aggregate.

## Metrics

Compare the number of full productionization-suite executions and setup steps before and after deduplication. Record the command's top 25 duration observations with the complete unfiltered results; they are diagnostic data, not a time threshold. Where comparable runner/runtime evidence exists, record elapsed job and workflow times with the matching head, run, job, and attempt. Do not infer billing, model-token savings, or financial performance from these measurements. No new runtime collector or cache is introduced.

The Master profiled the parameterized replay crash test at the base and interrupted it with SIGINT after
about 24 minutes because profiler overhead was substantial. The incomplete profile captured 4,313,568,601
calls in 1,429.741 profiled seconds; `_economic` accounted for 100 calls and 424.027 cumulative profiled
seconds. Pytest reported `KeyboardInterrupt` and `no tests ran` after 1,438.69 seconds although the outer
profiler process exited zero. This is incomplete diagnostic evidence, not a passing test, a completed crash
matrix, unprofiled elapsed time, or a performance-savings claim. It authorizes only computing the expected
`_economic(full)` reference tuple once per invocation in the two named recovery tests and reusing that
tuple in reference-side comparisons. All recovered-result computations and crash cuts remain. The
Master-owned unfiltered full suite covers the five affected cases and replay module; do not run the module
again merely to duplicate that required evidence.

## Long-running work and monitoring

Use native interruptible agent waits so the Master remains available for steering while independent work is running. For a long local command or CI run, keep the wait in a tool-side watcher and bind its result to the exact candidate SHA and, for CI, workflow run, job, and attempt. Preserve the complete private log and native exit/conclusion; summaries do not replace them. Pending, cancelled, timed-out, missing, or otherwise unknown results are not successful evidence. Notify the Master when work completes, fails, or reaches a decision point; avoid repeated model-side checks that report no change.

For a required CI run, bind the run to the candidate before waiting, watch it in a tool-side command, and
retain both watcher output and full logs. For example, in Bash:

```bash
CANDIDATE_SHA=<full-commit-sha>
RUN_ID=<workflow-run-id>
ATTEMPT=<run-attempt>
JOB_ID=<required-job-id>
EVIDENCE_DIR=<private-evidence-directory>
mkdir -p "$EVIDENCE_DIR"
gh api "repos/OWNER/REPO/actions/runs/$RUN_ID" > "$EVIDENCE_DIR/run-before.json"
jq -e --arg sha "$CANDIDATE_SHA" --argjson attempt "$ATTEMPT" \
  '.head_sha == $sha and .run_attempt == $attempt' "$EVIDENCE_DIR/run-before.json" > /dev/null || exit 1
set +e
gh run watch "$RUN_ID" --exit-status --interval 60 > "$EVIDENCE_DIR/watch.log" 2>&1
watch_exit=$?
printf '%s\n' "$watch_exit" > "$EVIDENCE_DIR/watch.exit"
gh api "repos/OWNER/REPO/actions/runs/$RUN_ID/attempts/$ATTEMPT/jobs" \
  > "$EVIDENCE_DIR/jobs.json"
gh run view "$RUN_ID" --log > "$EVIDENCE_DIR/full-run.log" 2>&1
logs_exit=$?
printf '%s\n' "$logs_exit" > "$EVIDENCE_DIR/full-run.exit"
gh run view "$RUN_ID" --log --job "$JOB_ID" > "$EVIDENCE_DIR/job-$JOB_ID.log" 2>&1
job_logs_exit=$?
printf '%s\n' "$job_logs_exit" > "$EVIDENCE_DIR/job-$JOB_ID.exit"
```

Re-read run metadata after the watch and confirm the exact SHA and attempt are unchanged, the run is
completed with `success`, and every required job ID for that attempt is completed with `success`. Require
zero native watcher and log-fetch exits and retain complete run/job logs privately. A changed attempt,
missing log, pending/cancelled/timeout/unknown status, or any failed/skipped required check is not a pass;
notify on completion, failure, or a decision that needs the Master.

## Rollback

The rollback restores the prior Foundation installation and productionization test execution, its matching contract tests, and the corresponding ownership description in a reviewed change. Preserve state and prior evidence, then rerun affected exact-head validation, review, and required CI.

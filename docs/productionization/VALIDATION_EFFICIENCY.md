# Validation ownership and evidence reuse

## Ownership

Default owner: Master. The Master owns one complete unfiltered local full suite per frozen candidate: `uv run --no-sync python -m pytest -q --durations=25`, with no selectors, skips or hidden pytest environment. The Master records another owner only when assigning that run. Writers run focused tests and static checks, then stop before the full run. Required GitHub CI is separate: the unfiltered test job, Ruff, clean-install smoke and applicable required checks.

A fresh controlling reviewer verifies committed RED replay, focused and negative checks, complete source, actual local full-run evidence and final-head CI. It may verify the completed local full run from native artifacts without rerunning when source, runtime and command match and no material concern exists; missing, inconsistent or concerning evidence requires a rerun. Summaries, caller receipts, status labels, incomplete logs and claims are not execution evidence.

## Evidence and reuse

For each local run record source SHA and tree SHA, base SHA, checkout SHA and tree SHA, designated owner, exact command and selectors (`none` when unfiltered), Python/uv/lock/environment identity, completion and native exit, pass/fail counts, skips and reasons, full logs, and before/after cleanliness with each SHA/tree. For CI record CI run/job/attempt, candidate SHA, completion/conclusion and native logs. Keep complete artifacts durable and summaries bounded; omit secrets, transcripts and user-specific paths.

Reuse only completed verifiable evidence for identical source/runtime/command. A new commit invalidates affected proof. Source/tree/runtime/command/checkout mismatch, incomplete log, missing identity or cleanliness, or failure invalidates it; rerun against the exact frozen head. Full local suite, all required CI, independent review and Master gate remain mandatory. Human paper/live and other approval gates are unchanged.

## CI coverage and metrics

The CI `test` job stays unfiltered: `uv run --no-sync pytest -q --durations=25`. Pytest discovery stays `testpaths = ["tests"]` with checked-in `addopts`. Foundation aggregates same-workflow `test`, `lint` and `smoke-install` via `needs` results and `always()`. Its Bash metadata check accepts only three exact `success` values; otherwise it exits nonzero with a fixed diagnostic. It does no checkout, setup, install, tests, network or artifact collection. A missing/cancelled aggregate or required check does not pass. CodeQL and Dependency Review remain independent required checks.

Compare full-suite execution and setup counts before/after deduplication. Keep top-25 duration observations with complete unfiltered results as diagnostics, not a threshold. Compare elapsed jobs/workflows only with matching head, run, job and attempt. Do not infer billing, token savings or financial performance. No runtime collector or cache is introduced.

## Profile limits

The Master interrupted the base parameterized replay crash-test profile with SIGINT after about 24 minutes because profiler overhead was substantial: 4,313,568,601 calls in 1,429.741 profiled seconds; `_economic` had 100 calls and 424.027 cumulative profiled seconds. Pytest reported `KeyboardInterrupt` and `no tests ran` after 1,438.69 seconds although outer cProfile exited zero. This incomplete diagnostic is not a pass, completed crash matrix, unprofiled time or savings claim. It authorizes only computing expected `_economic(full)` once per invocation in the two named recovery tests and reusing it in reference-side comparisons. Recovered-result computations and crash cuts stay unchanged. The Master-owned unfiltered suite covers the five cases and replay module; do not rerun that module merely to duplicate it.

## Long-running commands and CI

Use native interruptible agent waits so the Master can steer. Run long commands and CI watches in tool-side watchers bound to the candidate SHA; CI also binds workflow run, job and attempt. Keep complete private logs and native exit/conclusion; summaries do not replace them. Pending, cancelled, timed-out, missing or unknown results are not successful. Notify on completion, failure or a decision; avoid unchanged repeat checks.

For required CI, bind before waiting and keep watcher output and complete run/job logs. Example Bash recipe:

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

After watching, reread run metadata: exact SHA/attempt must remain unchanged, run must be completed `success`, and every required job for that attempt must be completed `success`. Require zero watcher and log-fetch exits AND nonempty complete run/job logs. Changed identity, missing/incomplete logs, pending/cancelled/timeout/unknown status, or failed/skipped required checks is not a pass. Notify on completion, failure or a decision needing the Master.

## Rollback

For rollback, restore prior Foundation installation and productionization test execution, matching contract tests and ownership description in a reviewed change. Preserve state and prior evidence; rerun affected exact-head validation, review and required CI.

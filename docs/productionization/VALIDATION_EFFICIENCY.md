# Validation ownership and evidence reuse

## Ownership

Default owner: Master. The Master owns one complete unfiltered local full suite per frozen candidate: `uv run --no-sync python -m pytest -q --durations=25`, with no selectors, skips or hidden pytest environment. The Master records another owner only when assigning that run. Writers run focused tests and static checks, then stop before the full run. Required GitHub CI is separate: the unfiltered test job, Ruff, clean-install smoke and applicable required checks.

A fresh controlling reviewer verifies committed RED replay, focused/negative checks, complete source and final CI. It may verify the completed local full run from native artifacts only when source/runtime/command match and no material concern exists; missing or inconsistent evidence requires rerun. Summaries, receipts, status labels, incomplete logs and claims are not evidence.

## Evidence and reuse

Record local source SHA/tree SHA, base SHA, checkout SHA/tree SHA, designated owner, exact command/selectors, Python/uv/lock/environment, completion/exit, counts, skips/reasons, full logs and before/after cleanliness. CI run/job/attempt records candidate SHA, conclusion and native logs. Preserve full artifacts; bound summaries; omit secrets, transcripts and user paths.

Reuse only completed verifiable evidence for identical source/runtime/command. A new commit invalidates affected proof. Mismatch, incomplete logs, missing identity/cleanliness or failure requires an exact frozen-head rerun. The full local suite, required CI, independent review, Master gate and human paper/live approvals remain mandatory.

## CI coverage and metrics

The required `tests (py3.14)` status aggregates two unconditional Python 3.14/uv 0.13.5 shards pinned to `ubuntu-24.04`; shard, aggregate and optional serial jobs log fixed `lscpu`/workspace `FSTYPE,OPTIONS`. Before collection/run, CLI reads duplicate-free native metadata once (max 16,384 bytes), requiring one `Runner Image` and unique `Image:`/`Version:` lines matching `ubuntu-24.04`, `ImageOS=ubuntu24` and strict ASCII dotted `ImageVersion`; failure is fixed and creates no output. Shards collect fully then run LPT; receipts prove disjoint coverage/lifecycle. Aggregate requires both shard successes, independently collects, verifies runtime bindings and uploads `ci-coverage`. References cap at 2,000,000 bytes; receipts at 8,000,000. Discovery stays unfiltered. Foundation fails without exact same-run `success` from test/lint/smoke-install and performs no checkout or tests. CodeQL and Dependency Review stay separate.

The `ci-partition-benchmark` PR label enables an optional same-run serial reference, independent of required coverage. Master compares native elapsed time through aggregate completion with serial completion (including queue/setup), plus pytest/shard durations. Require matching head, run/attempt, full Python, Runner Image/Image Version, lock and toolchain, and at least 25% reduction. Missing/skipped baseline, incomplete or mismatched evidence, or lower gain blocks merge. Top-25 durations are diagnostic only. Fixed positive timing observations guide assignment only. Make no billing/token/financial claims; no runtime collector or cache is introduced.

## Profile limits

The Master stopped the base replay crash-test profile with SIGINT after ~24 minutes: 4,313,568,601 calls in 1,429.741 profiled seconds; `_economic` had 100 calls/424.027 cumulative seconds. Pytest reported `KeyboardInterrupt` and `no tests ran` after 1,438.69 seconds although cProfile exited zero. This incomplete diagnostic is not a pass, completed crash matrix, unprofiled time or savings claim. It authorizes computing expected `_economic(full)` once per invocation in the two named recovery tests and reusing it for reference comparisons. Recovered-result computations/crash cuts stay unchanged. The Master full suite covers the five cases and replay module; do not rerun it solely to duplicate coverage.

## Long-running commands and CI

Use interruptible native waits. Bind long commands and CI watches to candidate SHA, run, job and attempt. Keep complete private logs and native exit/conclusion; summaries are not evidence. Pending, cancelled, timed-out, missing or unknown results fail. Notify on completion, failure or a decision; avoid unchanged checks.

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

Rollback restores prior Foundation installation, tests, assertions and ownership docs in a reviewed change. Record the rollback; preserve prior evidence, then rerun affected exact-head validation, review and required CI.

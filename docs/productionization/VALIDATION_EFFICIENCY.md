# Validation ownership and evidence reuse

## Ownership

Default owner: Master runs one complete, unfiltered local full suite per frozen candidate: `uv run --no-sync python -m pytest -q --durations=25`; no selectors, skips or hidden pytest environment. Reassignment requires a designated owner. Writers run focused tests/static checks, then stop before it. GitHub CI separately requires unfiltered tests, Ruff, clean-install smoke and applicable checks.

The fresh controlling reviewer checks committed RED replay, focused/negative checks, full source and final CI. It may verify the completed local full run from native artifacts only if source/runtime/command match and no material concern; else rerun. Summaries, receipts, statuses, incomplete logs and claims are not evidence.

## Evidence and reuse

Record source SHA and tree SHA, base SHA, checkout SHA and tree SHA, designated owner, exact command/selectors, Python/uv/lock/environment, completion/exit, counts/skips/reasons, full logs, before/after cleanliness. CI run/job/attempt bind candidate SHA, conclusion/native logs. Keep complete artifacts; bound summaries; omit secrets, transcripts, user paths.

Reuse only completed verifiable evidence for identical source/runtime/command. A new commit invalidates affected proof. Mismatch, incomplete logs, missing identity/cleanliness or failure requires exact frozen-head rerun. Full local suite, required CI, independent review, Master gate and human paper/live approvals remain mandatory.

## CI coverage and metrics

Required `tests (py3.14)` aggregates two unconditional Python 3.14/uv 0.13.5 shards on `ubuntu-24.04`. Shards/aggregate log fixed `lscpu`/workspace `FSTYPE,OPTIONS`; serial does so when required. Executed jobs' native setup logs must match metadata; optimization scope requires all four jobs. Before collection/run, CLI snapshots duplicate-free native JSON once (max 16,384 bytes), requiring one `Runner Image` group, one `Image:`=`ubuntu-24.04`, `ImageOS=ubuntu24` and strict ASCII dotted `Version:`. Native `Version:` is authoritative; inherited `ImageVersion` is ignored. Rejection is fixed; no output. Shards collect fully before LPT; receipts prove disjoint coverage/lifecycle. Aggregate requires shard successes, independently collects, verifies bindings and uploads `ci-coverage`. Reference/receipt caps: 2,000,000/8,000,000 bytes. Discovery stays unfiltered. Foundation requires exact same-run `success` from test/lint/smoke-install; no checkout/tests. CodeQL and Dependency Review stay separate.

`ci-partition-benchmark` schedules serial, not applicability. Outside partition/runtime optimization or a new performance claim, serial is optional and unrelated maintenance is N/A, never success. Those scopes require paired serial regardless of label; omitting/removing it leaves the baseline missing and blocks. Compare native serial/aggregate completion including queue/setup; require >=25% reduction and matching head/run/attempt/full Python/Runner Image/native `Version:`/lock/toolchain. Missing/skipped/incomplete/mismatched evidence or lower gain blocks. Record pytest/shard durations; top-25 is diagnostic; positive timings guide assignment only. No billing/token/financial claims or runtime collector/cache.

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

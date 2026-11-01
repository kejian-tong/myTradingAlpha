# Verified CI partitioning

## Execution model

The required `tests (py3.14)` status remains a stable aggregate over two explicit, unconditional jobs pinned to `ubuntu-24.04`. Shard and aggregate jobs, plus serial when required, log fixed `lscpu` and workspace filesystem (`FSTYPE,OPTIONS`) diagnostics. Native setup logs are required for every executed job and all four jobs in optimization scope. Each shard installs the locked development environment, performs full pytest collection, and executes its fixed assignment. The `test` aggregate first checks both native job results, independently collects the full suite, verifies both receipts against that reference, and uploads `ci-coverage`. A missing shard, failed runner, changed collection, or incomplete lifecycle fails the aggregate. Ruff, the isolated install smoke, static checks, CodeQL, Dependency Review, and the metadata-only Foundation gate remain separate required checks.

GitHub runs `serial-baseline` only when a pull request carries `ci-partition-benchmark`; the label controls scheduling, not benchmark applicability. Outside partition/runtime optimization or a new performance claim, the run is optional and unrelated maintenance records N/A, never success. Those scopes require the paired serial run regardless of label; omitting/removing the label leaves the baseline missing and blocks that scope. The job uses the same locked Python/uv toolchain and runner image, executes the complete suite, and uploads `ci-serial-reference`; it cannot delay or satisfy the required aggregate. Master compares native serial and aggregate completion, including queue/setup, and records pytest/shard durations. Require at least 25% reduction, matching candidate, workflow run/attempt, full Python, Runner Image/native `Version:`, lock/toolchain, and native setup-log equality for shard 0, shard 1, aggregate, and serial. Missing/skipped/incomplete/mismatched baseline or evidence, or lower gain, blocks that scope.

## Fixed CLI

Run commands from the Git checkout root:

```text
python scripts/ci_partition.py collect --output PATH
python scripts/ci_partition.py run --shard {0,1,serial} --output PATH
python scripts/ci_partition.py verify --reference PATH --receipts DIR [--serial PATH]
```

The interface accepts no pytest selectors, forwarded arguments, command strings, or weight overrides. Collection is full and unfiltered under the checked-in `testpaths` and `addopts`. A worker process runs pytest so interruption, early successful exit, or abrupt process termination cannot create a successful receipt. Output files are created exclusively and never replace existing paths. Inputs must be regular non-symlink files; FIFO and other special-file inputs fail without blocking. Diagnostics are fixed and do not echo artifact content.

Before collection, execution, or verification, the CLI reads the absolute `IMAGEDATA_FILE` path once (default `/imagegeneration/imagedata.json`) as a regular non-symlink file, bounded to 16,384 bytes. Duplicate-free native JSON must contain one `Runner Image` group with one `Image:` and one strict ASCII dotted `Version:` line. Only `ubuntu-24.04` with `ImageOS=ubuntu24` is accepted; the admitted native version comes from that operation's immutable bounded byte snapshot, although the file itself may change later. The inherited `ImageVersion` environment variable is ignored because it can be stale and does not establish which runner setup produced the operation. The snapshot value binds the reference and receipts, while native setup-log equality is required for every executed shard and aggregate, plus serial when required; all four must match in optimization scope. CLI admission alone does not prove the snapshot matches those logs. Admission rejection prints the unchanged `CI partition operation failed` first stderr line followed by one fixed reason code; diagnostics contain no metadata, path, environment, or exception text. Errors outside native runner admission retain only the original diagnostic, and rejection creates no output. Local fixtures supply their own native-format file; the workflow does not override the native path.

Collection IDs are unique and bounded. The canonical reference records both the sorted nodeid set and original pytest collection order. The approved timing observations from the recorded Ubuntu runner feed deterministic longest-processing-time scheduling with a 786 ms default: descending weight, nodeid tie-break, then assign to the currently lighter shard with shard 0 winning load ties. Each receipt retains the original order of its assigned IDs. Unknown and newly added tests receive the default weight and remain in the measured suite.

References use strict, duplicate-free canonical JSON and have a 2,000,000-byte maximum. Execution receipts use the same strict format and have an 8,000,000-byte maximum to cover the full serial run. Both formats reject unknown fields, duplicate IDs, invalid integer types, NaN, deep or oversized input, stale bindings, incomplete phases, and failed stages or subtests. Setup skips and expected xfails remain represented. Every selected test requires teardown accounting, and shard nodeids must form a disjoint complete union of the reference.

The reference and every receipt bind the candidate source SHA, actual checkout SHA and tree SHA, `uv.lock` digest, full Python version, uv version, workflow run and attempt, runner OS and native image OS/version. The candidate source and checkout may differ for a pull request merge checkout; both are checked against native workflow/Git context during CI verification.

## Offline artifact verification

The pure `scripts.ci_partition.verify_artifact_bytes` helper accepts the explicit native binding, immutable approved weights bytes, reference bytes, shard-zero bytes, shard-one bytes, and optional serial bytes. The binding has exactly these keys: `source_sha`, `checkout_sha`, `tree_sha`, `lock_sha256`, `workflow_run_id`, `workflow_run_attempt`, `runner_os`, `runner_image_os`, `runner_image_version`, `python_version`, and `uv_version`. It recomputes the reviewed deterministic LPT assignment and checks both receipts against it. The helper has no filesystem, environment, Git, or subprocess dependency; invalid snapshots raise `ValueError`. The CLI reads the fixed weights and each artifact once, derives binding values from its live checkout and workflow environment, and passes the snapshots to the same verifier.

The verifier returns a canonical coverage summary with exact artifact SHA-256 digests and a digest of sorted nodeids plus outcomes. If serial bytes are supplied, the verifier additionally requires exact nodeid and lifecycle/outcome parity. Without serial evidence, `serial_parity` is `null`; missing or skipped optional baseline is never a benchmark pass.

## Evidence limits

Partitioning proves test accounting and makes execution work concurrent. It does not reduce required test coverage or replace the Master-owned unfiltered local suite, required CI, fresh exact-head review, and merge gate. Historical weights influence assignment only; they are not proof of current speedup. Only complete, same-head native artifacts and logs support the measured 25% threshold.

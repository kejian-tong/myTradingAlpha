"""Behavioral contracts for the fixed two-runner CI partition CLI."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci_partition.py"
WEIGHTS = ROOT / "scripts" / "ci_partition_weights.json"
FIXED_ERROR = "CI partition operation failed\n"
WEIGHT_SOURCE_HEAD = "948cb8bb702dfaf0aa8db8f13d776e4afd33270a"
WEIGHT_RUN_ID = 41130111267
WEIGHT_JOB_ID = 124318560359
DEFAULT_WEIGHT_MS = 786
APPROVED_WEIGHTS_SHA256 = "9200d8af2316570148051728f0f85d1c4411bf08fbbec578f428aab61bb38095"
MAX_RUNNER_METADATA_BYTES = 16_384
RUNNER_IMAGE_VERSION = "202610.30.1"
MAX_REFERENCE_BYTES = 2_000_000
MAX_RECEIPT_BYTES = 8_000_000
MANIFEST_FIELDS = {
    "schema_version",
    "source_sha",
    "checkout_sha",
    "tree_sha",
    "lock_sha256",
    "workflow_run_id",
    "workflow_run_attempt",
    "runner_os",
    "runner_image_os",
    "runner_image_version",
    "python_version",
    "uv_version",
    "nodeids",
    "collection_order",
}
RECEIPT_FIELDS = {
    "schema_version",
    "shard",
    "source_sha",
    "checkout_sha",
    "tree_sha",
    "lock_sha256",
    "workflow_run_id",
    "workflow_run_attempt",
    "runner_os",
    "runner_image_os",
    "runner_image_version",
    "python_version",
    "uv_version",
    "elapsed_ms",
    "pytest_exit_code",
    "completed",
    "nodeids",
    "selected_nodeids",
    "outcomes",
}

EXPECTED_WEIGHTS_MS = {
    "tests/productionization/backtest/test_actions_benchmarks.py::test_bt04_repair_byte_admission_is_independent_of_native_node_limit[1539-True]": 60200,
    "tests/productionization/backtest/test_actions_benchmarks.py::test_bt04_repair_byte_admission_is_independent_of_native_node_limit[1653-False]": 48980,
    "tests/productionization/backtest/test_actions_benchmarks.py::test_bt04_repair_resource_admission_precedes_ledger_and_economics[12-True]": 68440,
    "tests/productionization/backtest/test_actions_benchmarks.py::test_eight_benchmark_members_sixteen_sessions_and_128_work_units_are_real": 185970,
    "tests/productionization/backtest/test_actions_benchmarks.py::test_outstanding_intent_count_accepts_64_unique_cancellations_and_rejects_65": 60950,
    "tests/productionization/backtest/test_actions_benchmarks.py::test_reference_count_accepts_32_genuine_instruments_and_rejects_33_before_work": 257730,
    "tests/productionization/backtest/test_ledger_nav.py::test_cumulative_fee_once_reconciles_two_three_and_five_partials[quantities2-cap2]": 36540,
    "tests/productionization/backtest/test_ledger_nav.py::test_sell_economics_and_public_checker_ignore_ambient_decimal_context[fractional-armed-ROUND_DOWN-replay]": 34710,
    "tests/productionization/backtest/test_ledger_nav.py::test_sell_economics_and_public_checker_ignore_ambient_decimal_context[fractional-armed-ROUND_UP-replay]": 34840,
    "tests/productionization/backtest/test_ledger_nav.py::test_sell_economics_and_public_checker_ignore_ambient_decimal_context[fractional-unarmed-ROUND_DOWN-replay]": 34820,
    "tests/productionization/backtest/test_ledger_nav.py::test_sell_economics_and_public_checker_ignore_ambient_decimal_context[fractional-unarmed-ROUND_UP-replay]": 34820,
    "tests/productionization/backtest/test_replay_hash.py::test_benchmark_prefixes_follow_closing_stages_without_future_suffix[3]": 34360,
    "tests/productionization/backtest/test_replay_hash.py::test_competing_intents_have_run_independent_semantic_priority": 75950,
    "tests/productionization/backtest/test_replay_hash.py::test_each_atomic_publication_and_sync_crash_retains_recoverable_prefix[after-fsync]": 701650,
    "tests/productionization/backtest/test_replay_hash.py::test_each_atomic_publication_and_sync_crash_retains_recoverable_prefix[after-link]": 349940,
    "tests/productionization/backtest/test_replay_hash.py::test_each_atomic_publication_and_sync_crash_retains_recoverable_prefix[before-fsync]": 699980,
    "tests/productionization/backtest/test_replay_hash.py::test_each_atomic_publication_and_sync_crash_retains_recoverable_prefix[before-link]": 352320,
    "tests/productionization/backtest/test_replay_hash.py::test_every_operation_boundary_and_stale_checkpoint_resume_once": 384210,
    "tests/productionization/backtest/test_replay_hash.py::test_run_and_operational_lineage_exclusions_preserve_typed_sources[False-quant_llm]": 79980,
    "tests/productionization/backtest/test_replay_hash.py::test_run_and_operational_lineage_exclusions_preserve_typed_sources[False-quant_only]": 72480,
    "tests/productionization/backtest/test_replay_hash.py::test_run_and_operational_lineage_exclusions_preserve_typed_sources[True-quant_llm]": 106280,
    "tests/productionization/backtest/test_replay_hash.py::test_run_and_operational_lineage_exclusions_preserve_typed_sources[True-quant_only]": 98390,
    "tests/productionization/backtest/test_replay_hash.py::test_set_like_ownership_and_cancellation_indexes_use_projected_identity[False]": 59170,
    "tests/productionization/backtest/test_replay_hash.py::test_set_like_ownership_and_cancellation_indexes_use_projected_identity[True]": 94350,
    "tests/productionization/backtest/test_replay_hash.py::test_three_hash_domains_use_independent_canonical_utf8_preimages": 57900,
}

LIFECYCLE_TESTS = '''\
import pytest


@pytest.fixture
def setup_skip():
    pytest.skip("valid setup skip")


def test_setup_skip(setup_skip):
    raise AssertionError("setup-skipped test body must not run")


def test_call_skip():
    pytest.skip("valid call skip")


@pytest.mark.xfail(reason="expected failure", strict=True)
def test_expected_xfail():
    assert False


def test_subtests_are_accounted_once(subtests):
    with subtests.test(case="first"):
        assert True
    with subtests.test(case="second"):
        pytest.skip("valid subtest skip")


def test_alpha():
    assert True


def test_beta():
    assert True
'''


@dataclass(frozen=True)
class TinyProject:
    root: Path
    env: dict[str, str]
    source_sha: str
    checkout_sha: str
    tree_sha: str


@dataclass(frozen=True)
class RunBundle:
    project: TinyProject
    reference: Path
    receipts: Path
    receipt_zero: Path
    receipt_one: Path
    serial: Path
    manifest: dict[str, Any]
    shard_zero: dict[str, Any]
    shard_one: dict[str, Any]
    serial_receipt: dict[str, Any]


def _require_cli() -> None:
    assert SCRIPT.is_file(), "CI partition contract is not implemented: missing scripts/ci_partition.py"
    assert WEIGHTS.is_file(), (
        "CI partition contract is not implemented: missing scripts/ci_partition_weights.json"
    )


def _metadata_json(groups: list[dict[str, Any]]) -> bytes:
    return json.dumps(groups, ensure_ascii=True, indent=2).encode("utf-8") + b"\n"


def _deeply_nested_value(depth: int) -> Any:
    value: Any = "deep"
    for _ in range(depth):
        value = [value]
    return value


def _runner_image_metadata(
    *, image: str = "ubuntu-24.04", version: str = RUNNER_IMAGE_VERSION
) -> bytes:
    return _metadata_json(
        [
            {"group": "Operating System", "detail": "Ubuntu 24.04"},
            {
                "group": "Runner Image",
                "detail": (
                    f"Image: {image}\nVersion: {version}\n"
                    "Image Release: https://github.com/actions/runner-images/releases/tag/ubuntu24/202610.30.1\n"
                    "Included Software: https://github.com/actions/runner-images"
                ),
            },
        ]
    )


def _write_runner_metadata(
    project: TinyProject,
    raw: bytes,
    *,
    name: str = "runner-imagedata.json",
) -> Path:
    path = project.root / name
    path.write_bytes(raw)
    project.env["IMAGEDATA_FILE"] = str(path)
    return path


def _assert_metadata_rejected(
    result: subprocess.CompletedProcess[str], output: Path, *, path: Path | None = None
) -> None:
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == FIXED_ERROR
    assert not output.exists()
    if path is not None:
        assert str(path) not in result.stdout + result.stderr


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


def _init_project(root: Path, *, test_files: dict[str, str] | None = None) -> TinyProject:
    _require_cli()
    root.mkdir(parents=True)
    (root / "scripts").mkdir()
    shutil.copyfile(SCRIPT, root / "scripts" / "ci_partition.py")
    shutil.copyfile(WEIGHTS, root / "scripts" / "ci_partition_weights.json")
    image_data_path = root / "runner-imagedata.json"
    image_data_path.write_bytes(_runner_image_metadata())
    (root / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\n'
        'testpaths = ["tests"]\n'
        'addopts = "-ra --strict-markers"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text("version = 1\n\n", encoding="utf-8")
    for relative, content in (test_files or {"tests/test_suite.py": LIFECYCLE_TESTS}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    _git(root, "init", "--quiet")
    _git(root, "config", "user.name", "CI Partition Test")
    _git(root, "config", "user.email", "ci-partition@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "fixture source commit")
    source_sha = _git(root, "rev-parse", "HEAD")
    _git(root, "commit", "--quiet", "--allow-empty", "-m", "fixture merge checkout")
    checkout_sha = _git(root, "rev-parse", "HEAD")
    tree_sha = _git(root, "rev-parse", "HEAD^{tree}")

    event_path = root.parent / "pull-request-event.json"
    event_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 4321,
                    "head": {"sha": source_sha},
                    "base": {"sha": "a" * 40},
                }
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "PYTEST_"))
    }
    env.update(
        {
            "CI": "true",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_REF": "refs/pull/4321/merge",
            "GITHUB_RUN_ID": "987654321",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_SHA": checkout_sha,
            "RUNNER_OS": "Linux",
            "ImageOS": "ubuntu24",
            "ImageVersion": RUNNER_IMAGE_VERSION,
            "IMAGEDATA_FILE": str(image_data_path),
        }
    )
    return TinyProject(root, env, source_sha, checkout_sha, tree_sha)


def _invoke(
    project: TinyProject,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: float = 20,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(project.root / "scripts" / "ci_partition.py"), *args],
        cwd=project.root,
        env=project.env if env is None else env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _successful(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, f"partition CLI failed: {result.stderr[-2000:]}"


def _load_canonical(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    value = json.loads(raw)
    canonical = json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii") + b"\n"
    assert raw == canonical, f"{path.name} is not canonical duplicate-free JSON"
    assert type(value) is dict
    return value


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii") + b"\n"


def _verify(bundle: RunBundle, receipts_dir: Path, *, serial: Path | None = None):
    args = ["verify", "--reference", str(bundle.reference), "--receipts", str(receipts_dir)]
    if serial is not None:
        args.extend(("--serial", str(serial)))
    return _invoke(bundle.project, *args)


def _copy_receipts(bundle: RunBundle, destination: Path) -> Path:
    destination.mkdir()
    shutil.copyfile(bundle.receipt_zero, destination / "shard-0.json")
    shutil.copyfile(bundle.receipt_one, destination / "shard-1.json")
    return destination


@pytest.fixture(scope="module")
def run_bundle(tmp_path_factory: pytest.TempPathFactory) -> RunBundle:
    project = _init_project(tmp_path_factory.mktemp("ci-partition") / "repo")
    output = project.root.parent / "outputs"
    output.mkdir()
    reference = output / "collection.json"
    result = _invoke(project, "collect", "--output", str(reference))
    _successful(result)
    manifest = _load_canonical(reference)

    receipt_zero = output / "shard-0.json"
    result = _invoke(project, "run", "--shard", "0", "--output", str(receipt_zero))
    _successful(result)
    shard_zero = _load_canonical(receipt_zero)

    receipt_one = output / "shard-1.json"
    result = _invoke(project, "run", "--shard", "1", "--output", str(receipt_one))
    _successful(result)
    shard_one = _load_canonical(receipt_one)

    serial = output / "serial.json"
    result = _invoke(project, "run", "--shard", "serial", "--output", str(serial))
    _successful(result)
    serial_receipt = _load_canonical(serial)

    return RunBundle(
        project,
        reference,
        output / "receipts",
        receipt_zero,
        receipt_one,
        serial,
        manifest,
        shard_zero,
        shard_one,
        serial_receipt,
    )


def test_00_cli_entrypoint_has_the_fixed_command_surface() -> None:
    _require_cli()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0
    assert "run" in result.stdout and "collect" in result.stdout and "verify" in result.stdout
    assert "--shard" in result.stdout and "--output" in result.stdout
    assert "--reference" in result.stdout and "--receipts" in result.stdout


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"{not-json", id="malformed-json"),
        pytest.param(b"\xff\xfe", id="malformed-utf8"),
        pytest.param(b"{}", id="wrong-root-object"),
        pytest.param(b"null", id="wrong-root-null"),
        pytest.param(b"[null]", id="wrong-entry-shape"),
        pytest.param(b'[{"group":"Runner Image","detail":7}]', id="wrong-detail-shape"),
        pytest.param(
            b'[{"group":"Runner Image","detail":"Image: ubuntu-24.04\\nVersion: 202610.30.1",'
            b'"\\u0067roup":"Other"}]',
            id="escaped-duplicate-json-key",
        ),
        pytest.param(
            _metadata_json([{"group": "Operating System", "detail": "Ubuntu 24.04"}]),
            id="missing-runner-image-group",
        ),
        pytest.param(
            _metadata_json(
                [
                    {"group": "Runner Image", "detail": "Image: ubuntu-24.04\nVersion: 202610.30.1"},
                    {"group": "Runner Image", "detail": "Image: ubuntu-24.04\nVersion: 202610.30.1"},
                ]
            ),
            id="duplicate-runner-image-group",
        ),
        pytest.param(
            _metadata_json([{"group": "Runnеr Image", "detail": "Image: ubuntu-24.04\nVersion: 202610.30.1"}]),
            id="unicode-confusable-group",
        ),
        pytest.param(
            _metadata_json(
                [
                    {
                        "group": "Runner Image",
                        "detail": "Image: ubuntu-24.04\nVersion: 202610.30.1\nVersion: 202610.30.1",
                    }
                ]
            ),
            id="duplicate-version-line",
        ),
        pytest.param(
            _metadata_json(
                [
                    {
                        "group": "Runner Image",
                        "detail": "Image: ubuntu-24.04\nImage: ubuntu-24.04\nVersion: 202610.30.1",
                    }
                ]
            ),
            id="duplicate-image-line",
        ),
        pytest.param(
            _metadata_json([{"group": "Runner Image", "detail": "Version: 202610.30.1"}]),
            id="missing-image-line",
        ),
        pytest.param(
            _metadata_json([{"group": "Runner Image", "detail": "Image: ubuntu-24.04"}]),
            id="missing-version-line",
        ),
        pytest.param(
            _metadata_json([{"group": "Runner Image", "detail": "Image: ubuntu-24.04\nVersion: 202610.30"}]),
            id="nondotted-version",
        ),
        pytest.param(
            _metadata_json([{"group": "Runner Image", "detail": "Image: ubuntu-24.04\nVersion: 202610.30.１"}]),
            id="nonascii-version-digit",
        ),
        pytest.param(_runner_image_metadata(image="ubuntu-22.04"), id="unsupported-image"),
        pytest.param(_runner_image_metadata(version="202610.30.2"), id="metadata-environment-version-mismatch"),
        pytest.param(
            _metadata_json(
                [
                    {
                        "group": "Runner Image",
                        "detail": "Image: ubuntu-24.04\nVersion: 202610.30.1\n" + "other\n" * 512,
                    }
                ]
            ),
            id="excessive-detail-lines",
        ),
        pytest.param(
            json.dumps(
                [{"group": "Runner Image", "detail": _deeply_nested_value(48)}],
                separators=(",", ":"),
            ).encode("utf-8"),
            id="deeply-nested-detail",
        ),
        pytest.param(
            json.dumps(
                [{"group": "x", "detail": ""} for _ in range(512)]
                + [{"group": "Runner Image", "detail": "Image: ubuntu-24.04\nVersion: 202610.30.1"}],
                separators=(",", ":"),
            ).encode("utf-8"),
            id="excessive-group-count",
        ),
    ],
)
def test_native_runner_metadata_rejects_ambiguous_or_unbounded_documents(
    tmp_path: Path, raw: bytes
) -> None:
    project = _init_project(tmp_path / "repo")
    metadata = _write_runner_metadata(project, raw)
    output = tmp_path / "collection.json"

    result = _invoke(project, "collect", "--output", str(output))

    _assert_metadata_rejected(result, output, path=metadata)


@pytest.mark.parametrize("command", ["collect", "run"])
@pytest.mark.parametrize(
    ("environment_key", "environment_value"),
    [
        pytest.param("ImageOS", "ubuntu22", id="image-os-mismatch"),
        pytest.param("ImageOS", "ubuntu24\n", id="image-os-control-character"),
        pytest.param("ImageVersion", "202610.31.1", id="image-version-mismatch"),
        pytest.param("ImageVersion", "202610.30.１", id="image-version-nonascii-digit"),
    ],
)
def test_native_environment_disagreement_fails_before_pytest_or_output(
    tmp_path: Path,
    command: str,
    environment_key: str,
    environment_value: str,
) -> None:
    sentinel = tmp_path / "collection-sentinel"
    project = _init_project(
        tmp_path / "repo",
        test_files={
            "conftest.py": (
                "import os\nfrom pathlib import Path\n"
                "Path(os.environ['PARTITION_TEST_SENTINEL']).write_text('collected')\n"
            ),
            "tests/test_sentinel.py": "def test_sentinel():\n    assert True\n",
        },
    )
    project.env["PARTITION_TEST_SENTINEL"] = str(sentinel)
    project.env[environment_key] = environment_value
    output = tmp_path / "operation.json"
    args = (
        ("collect", "--output", str(output))
        if command == "collect"
        else ("run", "--shard", "serial", "--output", str(output))
    )

    result = _invoke(project, *args)

    _assert_metadata_rejected(result, output, path=Path(project.env["IMAGEDATA_FILE"]))
    assert not sentinel.exists()


@pytest.mark.parametrize("path_kind", ["missing", "relative", "symlink", "directory", "fifo", "special"])
def test_runner_metadata_requires_an_absolute_regular_nonsymlink_file(
    tmp_path: Path, path_kind: str
) -> None:
    project = _init_project(tmp_path / "repo")
    valid_path = Path(project.env["IMAGEDATA_FILE"])
    if path_kind == "missing":
        metadata_path = tmp_path / "missing-imagedata.json"
        project.env["IMAGEDATA_FILE"] = str(metadata_path)
    elif path_kind == "relative":
        project.env["IMAGEDATA_FILE"] = valid_path.name
    elif path_kind == "symlink":
        metadata_path = tmp_path / "linked-imagedata.json"
        metadata_path.symlink_to(valid_path)
        project.env["IMAGEDATA_FILE"] = str(metadata_path)
    elif path_kind == "directory":
        metadata_path = tmp_path / "imagedata-directory"
        metadata_path.mkdir()
        project.env["IMAGEDATA_FILE"] = str(metadata_path)
    elif path_kind == "fifo":
        metadata_path = tmp_path / "imagedata.fifo"
        os.mkfifo(metadata_path)
        project.env["IMAGEDATA_FILE"] = str(metadata_path)
    else:
        metadata_path = Path("/dev/null")
        project.env["IMAGEDATA_FILE"] = str(metadata_path)
    output = tmp_path / "collection.json"

    result = _invoke(project, "collect", "--output", str(output), timeout=3)

    _assert_metadata_rejected(result, output, path=Path(project.env["IMAGEDATA_FILE"]))


def test_runner_metadata_rejection_does_not_leak_raw_encoded_or_path_secrets(tmp_path: Path) -> None:
    raw_secret = "HARNESS/EFF06+REDACTION=CANARY"
    encoded_secrets = (
        raw_secret,
        base64.b64encode(raw_secret.encode("ascii")).decode("ascii"),
        quote(raw_secret, safe=""),
    )
    project = _init_project(tmp_path / "repo")
    raw = json.dumps(
        [
            {"group": "Operating System", "detail": "Ubuntu 24.04"},
            {
                "group": "Runner Image",
                "detail": {"nested": [raw_secret, encoded_secrets[1], encoded_secrets[2]]},
            },
        ],
        ensure_ascii=True,
    ).encode("utf-8")
    metadata = project.root / f"metadata-{quote(raw_secret, safe='')}.json"
    metadata.write_bytes(raw)
    project.env["IMAGEDATA_FILE"] = str(metadata)
    output = tmp_path / "collection.json"

    result = _invoke(project, "collect", "--output", str(output))

    _assert_metadata_rejected(result, output, path=metadata)
    for secret in encoded_secrets:
        assert secret not in result.stdout + result.stderr


def test_runner_metadata_accepts_exact_byte_limit_and_rejects_one_byte_over(tmp_path: Path) -> None:
    project = _init_project(tmp_path / "repo")
    metadata = Path(project.env["IMAGEDATA_FILE"])
    valid = metadata.read_bytes()
    assert len(valid) < MAX_RUNNER_METADATA_BYTES
    metadata.write_bytes(valid + b" " * (MAX_RUNNER_METADATA_BYTES - len(valid)))
    exact_output = tmp_path / "exact-limit.json"

    exact_result = _invoke(project, "collect", "--output", str(exact_output))

    _successful(exact_result)
    assert exact_output.is_file()

    metadata.write_bytes(valid + b" " * (MAX_RUNNER_METADATA_BYTES + 1 - len(valid)))
    oversized_output = tmp_path / "oversized.json"

    oversized_result = _invoke(project, "collect", "--output", str(oversized_output))

    _assert_metadata_rejected(oversized_result, oversized_output, path=metadata)


def test_runner_metadata_is_one_immutable_snapshot_for_the_operation(tmp_path: Path) -> None:
    project = _init_project(
        tmp_path / "repo",
        test_files={
            "conftest.py": (
                "import os\nfrom pathlib import Path\n"
                "Path(os.environ['IMAGEDATA_FILE']).write_bytes(b'{malformed after admission')\n"
            ),
            "tests/test_snapshot.py": "def test_snapshot():\n    assert True\n",
        },
    )
    metadata = Path(project.env["IMAGEDATA_FILE"])
    output = tmp_path / "collection.json"

    result = _invoke(project, "collect", "--output", str(output))

    _successful(result)
    manifest = _load_canonical(output)
    assert metadata.read_bytes() == b"{malformed after admission"
    assert manifest["runner_image_os"] == "ubuntu24"
    assert manifest["runner_image_version"] == RUNNER_IMAGE_VERSION


def test_weights_are_the_approved_fixed_positive_observations() -> None:
    _require_cli()
    raw = WEIGHTS.read_bytes()
    weights = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == APPROVED_WEIGHTS_SHA256
    assert type(weights) is dict
    assert set(weights) == {"default_ms", "job_id", "run_id", "schema_version", "source_head", "weights_ms"}
    assert weights["schema_version"] == 1 and type(weights["schema_version"]) is int
    assert weights["source_head"] == WEIGHT_SOURCE_HEAD
    assert weights["run_id"] == WEIGHT_RUN_ID and type(weights["run_id"]) is int
    assert weights["job_id"] == WEIGHT_JOB_ID and type(weights["job_id"]) is int
    assert weights["default_ms"] == DEFAULT_WEIGHT_MS and type(weights["default_ms"]) is int
    assert weights["weights_ms"] == EXPECTED_WEIGHTS_MS
    assert all(type(value) is int and value > 0 for value in weights["weights_ms"].values())


def test_collection_and_receipts_are_canonical_bound_and_complete(run_bundle: RunBundle) -> None:
    manifest = run_bundle.manifest
    assert manifest["source_sha"] == run_bundle.project.source_sha
    assert manifest["checkout_sha"] == run_bundle.project.checkout_sha
    assert manifest["tree_sha"] == run_bundle.project.tree_sha
    assert manifest["source_sha"] != manifest["checkout_sha"]
    assert manifest["workflow_run_id"] == 987654321
    assert manifest["workflow_run_attempt"] == 1
    assert set(manifest) == MANIFEST_FIELDS
    assert manifest["runner_os"] == "Linux"
    assert manifest["runner_image_os"] == "ubuntu24"
    assert manifest["runner_image_version"] == "202610.30.1"
    assert manifest["python_version"] == platform.python_version()
    assert manifest["uv_version"] == "0.13.5"
    assert manifest["lock_sha256"] == hashlib.sha256((run_bundle.project.root / "uv.lock").read_bytes()).hexdigest()
    nodeids = manifest["nodeids"]
    collection_order = manifest["collection_order"]
    assert nodeids == sorted(set(nodeids)) and nodeids
    assert collection_order and len(collection_order) == len(nodeids)
    assert set(collection_order) == set(nodeids)

    for shard_name, receipt in (("0", run_bundle.shard_zero), ("1", run_bundle.shard_one)):
        assert set(receipt) == RECEIPT_FIELDS
        assert receipt["schema_version"] == 1
        assert receipt["shard"] == shard_name
        assert receipt["source_sha"] == manifest["source_sha"]
        assert receipt["checkout_sha"] == manifest["checkout_sha"]
        assert receipt["tree_sha"] == manifest["tree_sha"]
        assert receipt["lock_sha256"] == manifest["lock_sha256"]
        assert receipt["workflow_run_id"] == manifest["workflow_run_id"]
        assert receipt["workflow_run_attempt"] == manifest["workflow_run_attempt"]
        assert receipt["runner_os"] == manifest["runner_os"]
        assert receipt["runner_image_os"] == manifest["runner_image_os"]
        assert receipt["runner_image_version"] == manifest["runner_image_version"]
        assert receipt["nodeids"] == nodeids
        selected = receipt["selected_nodeids"]
        assert selected and len(selected) == len(set(selected))
        assert selected == [nodeid for nodeid in collection_order if nodeid in set(selected)]
        assert receipt["completed"] is True and receipt["pytest_exit_code"] == 0
        assert type(receipt["elapsed_ms"]) is int and receipt["elapsed_ms"] >= 0
        assert receipt["python_version"] == platform.python_version()
        assert receipt["uv_version"] == "0.13.5"
        outcomes = receipt["outcomes"]
        assert [item["nodeid"] for item in outcomes] == selected
        for item in outcomes:
            assert set(item) == {"nodeid", "setup", "call", "teardown", "xfail", "subtests"}
            assert item["setup"] in {"passed", "skipped", "failed"}
            assert item["call"] in {None, "passed", "skipped", "failed"}
            assert item["teardown"] in {"passed", "skipped", "failed"}
            assert type(item["xfail"]) is bool
            assert set(item["subtests"]) == {"passed", "skipped", "failed"}
            assert all(type(value) is int and value >= 0 for value in item["subtests"].values())


def test_lpt_uses_descending_fixed_weights_and_preserves_collection_order(run_bundle: RunBundle) -> None:
    nodeids = run_bundle.manifest["collection_order"]
    weights_doc = json.loads((run_bundle.project.root / "scripts" / "ci_partition_weights.json").read_text())
    weights = weights_doc["weights_ms"]
    loads = [0, 0]
    owners: dict[str, int] = {}
    for nodeid in sorted(nodeids, key=lambda value: (-weights.get(value, DEFAULT_WEIGHT_MS), value)):
        shard = 0 if loads[0] <= loads[1] else 1
        owners[nodeid] = shard
        loads[shard] += weights.get(nodeid, DEFAULT_WEIGHT_MS)
    for shard, receipt in enumerate((run_bundle.shard_zero, run_bundle.shard_one)):
        expected = [nodeid for nodeid in nodeids if owners[nodeid] == shard]
        assert receipt["selected_nodeids"] == expected
    left = set(run_bundle.shard_zero["selected_nodeids"])
    right = set(run_bundle.shard_one["selected_nodeids"])
    assert left.isdisjoint(right)
    assert left | right == set(nodeids)


def test_actual_pytest_lifecycle_counts_skips_xfails_and_subtests_once(run_bundle: RunBundle) -> None:
    outcomes = {
        item["nodeid"].split("::", maxsplit=1)[-1]: item
        for receipt in (run_bundle.shard_zero, run_bundle.shard_one)
        for item in receipt["outcomes"]
    }
    setup_skip = outcomes["test_setup_skip"]
    assert setup_skip["setup"] == "skipped" and setup_skip["call"] is None
    assert setup_skip["teardown"] == "passed"
    call_skip = outcomes["test_call_skip"]
    assert call_skip["setup"] == "passed" and call_skip["call"] == "skipped"
    assert call_skip["teardown"] == "passed"
    expected_xfail = outcomes["test_expected_xfail"]
    assert expected_xfail["xfail"] is True and expected_xfail["call"] == "skipped"
    subtests = outcomes["test_subtests_are_accounted_once"]
    assert subtests["call"] == "passed"
    assert subtests["subtests"] == {"passed": 1, "skipped": 1, "failed": 0}
    serial = run_bundle.serial_receipt
    assert serial["selected_nodeids"] == run_bundle.manifest["collection_order"]
    assert [item["nodeid"] for item in serial["outcomes"]] == run_bundle.manifest["collection_order"]
    serial_outcomes = {item["nodeid"]: item for item in serial["outcomes"]}
    partition_outcomes = {
        item["nodeid"]: item
        for receipt in (run_bundle.shard_zero, run_bundle.shard_one)
        for item in receipt["outcomes"]
    }
    assert serial_outcomes == partition_outcomes


def test_run_preserves_native_pytest_summary_skip_reasons_and_durations(
    run_bundle: RunBundle, tmp_path: Path
) -> None:
    receipt = tmp_path / "serial-output.json"
    result = _invoke(run_bundle.project, "run", "--shard", "serial", "--output", str(receipt))
    _successful(result)
    native_output = result.stdout + result.stderr
    assert "passed" in native_output
    assert "valid setup skip" in native_output
    assert "slowest 25 durations" in native_output
    assert receipt.is_file()


def test_aggregate_verification_proves_full_coverage_and_serial_parity(run_bundle: RunBundle, tmp_path: Path) -> None:
    receipts = _copy_receipts(run_bundle, tmp_path / "receipts")
    result = _verify(run_bundle, receipts, serial=run_bundle.serial)
    _successful(result)
    summary_bytes = result.stdout.encode("ascii")
    summary = json.loads(summary_bytes)
    assert summary_bytes.endswith(b"\n")
    assert summary_bytes == (
        json.dumps(summary, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")
    assert summary["schema_version"] == 1
    assert summary["completed"] is True
    assert summary["node_count"] == len(run_bundle.manifest["nodeids"])
    assert summary["shards"] == 2
    assert summary["serial_parity"] is True
    assert summary["binding"] == {
        key: run_bundle.manifest[key]
        for key in (
            "source_sha",
            "checkout_sha",
            "tree_sha",
            "lock_sha256",
            "workflow_run_id",
            "workflow_run_attempt",
            "runner_os",
            "runner_image_os",
            "runner_image_version",
            "python_version",
            "uv_version",
        )
    }
    assert summary["reference_sha256"] == hashlib.sha256(run_bundle.reference.read_bytes()).hexdigest()
    assert summary["shard_receipt_sha256"] == {
        "0": hashlib.sha256(run_bundle.receipt_zero.read_bytes()).hexdigest(),
        "1": hashlib.sha256(run_bundle.receipt_one.read_bytes()).hexdigest(),
    }
    expected_outcomes = sorted(
        run_bundle.shard_zero["outcomes"] + run_bundle.shard_one["outcomes"],
        key=lambda item: item["nodeid"],
    )
    assert summary["coverage_sha256"] == _canonical_digest(
        {"nodeids": run_bundle.manifest["nodeids"], "outcomes": expected_outcomes}
    )


def test_pure_bytes_verifier_accepts_explicit_native_binding_without_runtime_access(
    run_bundle: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_cli()
    from scripts import ci_partition

    expected_binding = {
        key: run_bundle.manifest[key]
        for key in (
            "source_sha",
            "checkout_sha",
            "tree_sha",
            "lock_sha256",
            "workflow_run_id",
            "workflow_run_attempt",
            "runner_os",
            "runner_image_os",
            "runner_image_version",
            "python_version",
            "uv_version",
        )
    }
    approved_weights_bytes = (run_bundle.project.root / "scripts" / "ci_partition_weights.json").read_bytes()

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("offline verifier attempted runtime or filesystem access")

    monkeypatch.setattr(ci_partition, "_read_regular_file", forbidden)
    monkeypatch.setattr(ci_partition, "_runtime_binding", forbidden)
    monkeypatch.setattr(ci_partition.subprocess, "run", forbidden)
    summary = ci_partition.verify_artifact_bytes(
        expected_binding,
        approved_weights_bytes,
        run_bundle.reference.read_bytes(),
        run_bundle.receipt_zero.read_bytes(),
        run_bundle.receipt_one.read_bytes(),
        run_bundle.serial.read_bytes(),
    )
    assert summary["completed"] is True
    assert summary["serial_parity"] is True
    assert summary["weights_sha256"] == hashlib.sha256(approved_weights_bytes).hexdigest()
    assert summary["reference_sha256"] == hashlib.sha256(
        run_bundle.reference.read_bytes()
    ).hexdigest()


def test_pure_verifier_rejects_alternative_disjoint_full_cover_assignment(
    run_bundle: RunBundle,
) -> None:
    from scripts.ci_partition import verify_artifact_bytes

    expected_binding = {
        key: run_bundle.manifest[key]
        for key in (
            "source_sha",
            "checkout_sha",
            "tree_sha",
            "lock_sha256",
            "workflow_run_id",
            "workflow_run_attempt",
            "runner_os",
            "runner_image_os",
            "runner_image_version",
            "python_version",
            "uv_version",
        )
    }
    zero = copy.deepcopy(run_bundle.shard_zero)
    one = copy.deepcopy(run_bundle.shard_one)
    zero_ids = set(zero["selected_nodeids"])
    one_ids = set(one["selected_nodeids"])
    assert zero_ids and one_ids and zero_ids.isdisjoint(one_ids)
    exchange_zero = zero["selected_nodeids"][0]
    exchange_one = one["selected_nodeids"][0]
    zero_ids.remove(exchange_zero)
    zero_ids.add(exchange_one)
    one_ids.remove(exchange_one)
    one_ids.add(exchange_zero)
    collection_order = run_bundle.manifest["collection_order"]
    zero["selected_nodeids"] = [nodeid for nodeid in collection_order if nodeid in zero_ids]
    one["selected_nodeids"] = [nodeid for nodeid in collection_order if nodeid in one_ids]
    zero_outcomes = {item["nodeid"]: item for item in run_bundle.shard_zero["outcomes"]}
    one_outcomes = {item["nodeid"]: item for item in run_bundle.shard_one["outcomes"]}
    combined_outcomes = {**zero_outcomes, **one_outcomes}
    zero["outcomes"] = [combined_outcomes[nodeid] for nodeid in zero["selected_nodeids"]]
    one["outcomes"] = [combined_outcomes[nodeid] for nodeid in one["selected_nodeids"]]
    assert set(zero["selected_nodeids"]).isdisjoint(one["selected_nodeids"])
    assert set(zero["selected_nodeids"]) | set(one["selected_nodeids"]) == set(collection_order)

    with pytest.raises(ValueError, match="invalid CI partition artifact evidence"):
        verify_artifact_bytes(
            expected_binding,
            (run_bundle.project.root / "scripts" / "ci_partition_weights.json").read_bytes(),
            run_bundle.reference.read_bytes(),
            _canonical_bytes(zero),
            _canonical_bytes(one),
        )


def test_worker_process_preserves_output_and_uses_bounded_mode_timeouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import ci_partition

    calls: list[tuple[list[str], dict[str, Any]]] = []
    report = {
        "exit_code": 0,
        "nodeids": [],
        "collection_before": [],
        "collection_after": [],
        "lifecycle": {},
    }

    monkeypatch.setattr(ci_partition, "_clean_pytest_environment", lambda: {})

    for mode, timeout in (("collect", 1_800), ("run", 18_000)):
        report_path = tmp_path / ("run.json" if mode == "run" else "collect.json")

        def write_report(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append((command, kwargs))
            report_path_arg = command[6]
            Path(report_path_arg).write_bytes(_canonical_bytes(report))
            return subprocess.CompletedProcess(command, 0, "", "")

        monkeypatch.setattr(ci_partition.subprocess, "run", write_report)
        ci_partition._child_process(tmp_path, mode, report_path, [])
        actual_command, actual_kwargs = calls[-1]
        assert actual_kwargs["timeout"] == timeout
        assert "stdout" not in actual_kwargs and "stderr" not in actual_kwargs
        assert actual_command[1:3] == ["-I", "-c"]


@pytest.mark.parametrize(
    "args",
    [
        ("run", "--shard", "2", "--output", "out.json"),
        ("run", "--shard", "0", "--output", "out.json", "--", "-k", "smoke"),
        ("collect", "--output", "out.json", "--", "--ignore=tests"),
        ("verify", "--reference", "ref.json", "--receipts", "out", "--command", "id"),
        ("run", "--shard", "serial", "--output", "out.json", "--weights", "other.json"),
    ],
)
def test_cli_rejects_arbitrary_commands_selectors_and_weight_overrides(
    run_bundle: RunBundle, args: tuple[str, ...]
) -> None:
    result = _invoke(run_bundle.project, *args)
    assert result.returncode != 0
    assert "-k" not in result.stdout + result.stderr or "-k" in args


def _mutations() -> list[tuple[str, Any]]:
    return [
        ("unknown field", lambda value: value.__setitem__("unrecognized", "CANARY")),
        ("boolean schema version", lambda value: value.__setitem__("schema_version", True)),
        ("stale source", lambda value: value.__setitem__("source_sha", "b" * 40)),
        ("stale checkout", lambda value: value.__setitem__("checkout_sha", "c" * 40)),
        ("stale tree", lambda value: value.__setitem__("tree_sha", "d" * 40)),
        ("stale lock", lambda value: value.__setitem__("lock_sha256", "e" * 64)),
        ("stale run", lambda value: value.__setitem__("workflow_run_id", 987654322)),
        ("stale attempt", lambda value: value.__setitem__("workflow_run_attempt", 2)),
        ("stale runner OS", lambda value: value.__setitem__("runner_os", "Windows")),
        ("stale runner image", lambda value: value.__setitem__("runner_image_version", "different")),
        ("wrong runtime", lambda value: value.__setitem__("python_version", "3.14")),
        ("wrong uv runtime", lambda value: value.__setitem__("uv_version", "0.12.7")),
        ("failed native exit", lambda value: value.__setitem__("pytest_exit_code", 1)),
        ("boolean native exit", lambda value: value.__setitem__("pytest_exit_code", True)),
        ("incomplete execution", lambda value: value.__setitem__("completed", False)),
        ("boolean integer", lambda value: value.__setitem__("workflow_run_attempt", True)),
        ("invalid elapsed boolean", lambda value: value.__setitem__("elapsed_ms", True)),
        ("duplicate collection id", lambda value: value["nodeids"].append(value["nodeids"][0])),
        ("unsorted collection", lambda value: value["nodeids"].reverse()),
        ("missing collection id", lambda value: value["nodeids"].pop()),
        ("duplicate selected id", lambda value: value["selected_nodeids"].append(value["selected_nodeids"][0])),
        ("missing outcome", lambda value: value["outcomes"].pop()),
        ("failed setup", lambda value: value["outcomes"][0].__setitem__("setup", "failed")),
        ("missing teardown", lambda value: value["outcomes"][0].__setitem__("teardown", None)),
        (
            "failed subtest",
            lambda value: value["outcomes"][0]["subtests"].__setitem__("failed", 1),
        ),
        (
            "boolean subtest count",
            lambda value: value["outcomes"][0]["subtests"].__setitem__("passed", True),
        ),
    ]


@pytest.mark.parametrize("label,mutate", _mutations())
def test_verify_rejects_receipt_binding_and_lifecycle_mutations(
    run_bundle: RunBundle, tmp_path: Path, label: str, mutate: Any
) -> None:
    receipts = _copy_receipts(run_bundle, tmp_path / "receipts")
    target = receipts / "shard-0.json"
    value = copy.deepcopy(run_bundle.shard_zero)
    mutate(value)
    target.write_bytes(
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    result = _verify(run_bundle, receipts)
    assert result.returncode != 0, f"verifier accepted {label}"
    assert result.stdout == ""
    assert result.stderr == FIXED_ERROR
    assert "CANARY" not in result.stderr


def test_verify_rejects_duplicate_keys_noncanonical_json_nan_and_deep_input(
    run_bundle: RunBundle, tmp_path: Path
) -> None:
    malformed = (
        run_bundle.receipt_zero.read_bytes().replace(
            b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1
        ),
        run_bundle.receipt_zero.read_bytes().replace(b'{', b'{ ', 1),
        run_bundle.receipt_zero.read_bytes().replace(b'"elapsed_ms":', b'"elapsed_ms":NaN', 1),
        b"[" * 2048 + b"]" * 2048,
    )
    for index, raw in enumerate(malformed):
        receipts = _copy_receipts(run_bundle, tmp_path / f"malformed-{index}")
        (receipts / "shard-0.json").write_bytes(raw)
        result = _verify(run_bundle, receipts)
        assert result.returncode != 0
        assert result.stdout == ""
        assert result.stderr == FIXED_ERROR


def test_verify_rejects_untrusted_reference_mutations(run_bundle: RunBundle, tmp_path: Path) -> None:
    mutations = (
        lambda value: value.__setitem__("unknown", "CANARY"),
        lambda value: value.__setitem__("source_sha", "b" * 40),
        lambda value: value.__setitem__("workflow_run_attempt", True),
        lambda value: value["nodeids"].append(value["nodeids"][0]),
        lambda value: value["collection_order"].pop(),
    )
    for index, mutate in enumerate(mutations):
        reference = tmp_path / f"reference-{index}.json"
        value = copy.deepcopy(run_bundle.manifest)
        mutate(value)
        reference.write_text(
            json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        receipts = _copy_receipts(run_bundle, tmp_path / f"receipts-{index}")
        result = _invoke(
            run_bundle.project,
            "verify",
            "--reference",
            str(reference),
            "--receipts",
            str(receipts),
        )
        assert result.returncode != 0
        assert result.stdout == "" and result.stderr == FIXED_ERROR


def test_verify_rejects_reference_collection_count_limit(run_bundle: RunBundle, tmp_path: Path) -> None:
    reference = copy.deepcopy(run_bundle.manifest)
    reference["nodeids"] = [f"test_{index:05d}" for index in range(50_001)]
    reference["collection_order"] = list(reference["nodeids"])
    raw = json.dumps(reference, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    assert len(raw) < 2_000_000
    reference_path = tmp_path / "too-many-nodeids.json"
    reference_path.write_bytes(raw + b"\n")
    receipts = _copy_receipts(run_bundle, tmp_path / "receipts")
    result = _invoke(
        run_bundle.project,
        "verify",
        "--reference",
        str(reference_path),
        "--receipts",
        str(receipts),
    )
    assert result.returncode != 0
    assert result.stdout == "" and result.stderr == FIXED_ERROR


def test_verify_rejects_oversized_inputs_and_sanitizes_nested_sentinels(
    run_bundle: RunBundle, tmp_path: Path
) -> None:
    canary = "CI-PARTITION-SECRET-CANARY"
    encoded = base64.b64encode(canary.encode()).decode()
    nested = quote(encoded, safe="")
    raw = json.dumps({"nested": {"value": [canary, encoded, nested]}}).encode()
    receipts = _copy_receipts(run_bundle, tmp_path / "oversized")
    (receipts / "shard-0.json").write_bytes(raw * ((MAX_RECEIPT_BYTES // len(raw)) + 1))
    result = _verify(run_bundle, receipts)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == FIXED_ERROR
    assert all(value not in result.stdout + result.stderr for value in (canary, encoded, nested))

    oversized_reference = tmp_path / "oversized-reference.json"
    oversized_reference.write_bytes(raw * ((MAX_REFERENCE_BYTES // len(raw)) + 1))
    result = _invoke(
        run_bundle.project,
        "verify",
        "--reference",
        str(oversized_reference),
        "--receipts",
        str(receipts),
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == FIXED_ERROR
    assert all(value not in result.stdout + result.stderr for value in (canary, encoded, nested))


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "overlap", "extra"])
def test_verify_rejects_missing_duplicate_overlapping_or_extra_shards(
    run_bundle: RunBundle, tmp_path: Path, mutation: str
) -> None:
    receipts = _copy_receipts(run_bundle, tmp_path / mutation)
    if mutation == "missing":
        (receipts / "shard-1.json").unlink()
    elif mutation == "duplicate":
        shutil.copyfile(receipts / "shard-0.json", receipts / "duplicate.json")
    elif mutation == "overlap":
        value = copy.deepcopy(run_bundle.shard_one)
        value["selected_nodeids"] = list(run_bundle.shard_zero["selected_nodeids"])
        value["outcomes"] = [
            row for row in run_bundle.shard_one["outcomes"]
            if row["nodeid"] in set(value["selected_nodeids"])
        ]
        (receipts / "shard-1.json").write_text(
            json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    else:
        (receipts / "unexpected.json").write_text("{}\n", encoding="utf-8")
    result = _verify(run_bundle, receipts)
    assert result.returncode != 0
    assert result.stdout == "" and result.stderr == FIXED_ERROR


def test_verify_rejects_serial_mismatch_and_runner_image_or_runtime_mismatch(
    run_bundle: RunBundle, tmp_path: Path
) -> None:
    receipts = _copy_receipts(run_bundle, tmp_path / "receipts")
    serial = tmp_path / "serial.json"
    serial_value = copy.deepcopy(run_bundle.serial_receipt)
    serial_value["python_version"] = "3.14.8"
    serial.write_text(
        json.dumps(serial_value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    result = _verify(run_bundle, receipts, serial=serial)
    assert result.returncode != 0 and result.stdout == "" and result.stderr == FIXED_ERROR

    serial.write_bytes(run_bundle.serial.read_bytes())
    serial_value = copy.deepcopy(run_bundle.serial_receipt)
    serial_value["runner_image_version"] = "different-image"
    serial.write_text(
        json.dumps(serial_value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    result = _verify(run_bundle, receipts, serial=serial)
    assert result.returncode != 0 and result.stdout == "" and result.stderr == FIXED_ERROR

    serial.write_bytes(run_bundle.serial.read_bytes())
    wrong_env = dict(run_bundle.project.env)
    wrong_env["GITHUB_RUN_ATTEMPT"] = "2"
    result = _invoke(
        run_bundle.project,
        "verify",
        "--reference",
        str(run_bundle.reference),
        "--receipts",
        str(receipts),
        "--serial",
        str(serial),
        env=wrong_env,
    )
    assert result.returncode != 0 and result.stdout == "" and result.stderr == FIXED_ERROR

    wrong_image_env = dict(run_bundle.project.env)
    wrong_image_env["ImageVersion"] = "202610.30.2"
    result = _invoke(
        run_bundle.project,
        "verify",
        "--reference",
        str(run_bundle.reference),
        "--receipts",
        str(receipts),
        env=wrong_image_env,
    )
    assert result.returncode != 0 and result.stdout == "" and result.stderr == FIXED_ERROR


def test_cli_rejects_hidden_pytest_selectors_and_plugin_deselection(tmp_path: Path) -> None:
    project = _init_project(tmp_path / "filtered", test_files={"tests/test_visible.py": "def test_visible(): pass\ndef test_hidden(): pass\n"})
    output = tmp_path / "filtered-collection.json"
    hidden_env = dict(project.env)
    hidden_env["PYTEST_ADDOPTS"] = "-k visible"
    result = _invoke(project, "collect", "--output", str(output), env=hidden_env)
    assert result.returncode != 0
    assert not output.exists()

    (project.root / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n"
        "    if items:\n"
        "        items.pop()\n",
        encoding="utf-8",
    )
    result = _invoke(project, "collect", "--output", str(output))
    assert result.returncode != 0
    assert not output.exists()


def test_hostile_nodeids_remain_data_and_do_not_run_shell_commands(tmp_path: Path) -> None:
    marker = "ci_partition_shell_injected"
    hostile_ids = (
        "semi; touch ci_partition_shell_injected; #",
        "dollar$(touch ci_partition_shell_injected)",
        "tick`touch ci_partition_shell_injected`",
        "unicode-雪-é",
        "line\nbreak",
    )
    test_source = (
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', range(5), ids="
        + repr(hostile_ids)
        + ")\ndef test_hostile_nodeid(value): pass\n"
    )
    project = _init_project(tmp_path / "hostile", test_files={"tests/test_hostile.py": test_source})
    output = tmp_path / "hostile-output"
    output.mkdir()
    collection = output / "collection.json"
    result = _invoke(project, "collect", "--output", str(collection))
    _successful(result)
    manifest = _load_canonical(collection)
    assert len(manifest["nodeids"]) == len(hostile_ids)
    assert any("semi; touch ci_partition_shell_injected" in nodeid for nodeid in manifest["nodeids"])
    for shard in ("0", "1"):
        result = _invoke(project, "run", "--shard", shard, "--output", str(output / f"shard-{shard}.json"))
        _successful(result)
    assert not (project.root / marker).exists()


@pytest.mark.parametrize("failure", ["setup", "call", "teardown", "subtest", "strict-xpass"])
def test_native_pytest_failures_never_create_success_receipts(
    tmp_path: Path, failure: str
) -> None:
    failure_sources = {
        "setup": "import pytest\n@pytest.fixture\ndef broken(): raise RuntimeError('setup')\ndef test_bad(broken): pass\n",
        "call": "def test_bad(): assert False\n",
        "teardown": "import pytest\n@pytest.fixture\ndef broken(request): request.addfinalizer(lambda: (_ for _ in ()).throw(RuntimeError('teardown')))\ndef test_bad(broken): pass\n",
        "subtest": "def test_bad(subtests):\n with subtests.test(case='bad'):\n  assert False\n",
        "strict-xpass": "import pytest\n@pytest.mark.xfail(strict=True)\ndef test_bad(): pass\n",
    }
    project = _init_project(tmp_path / failure, test_files={"tests/test_failure.py": failure_sources[failure]})
    receipt = tmp_path / f"{failure}.json"
    result = _invoke(project, "run", "--shard", "serial", "--output", str(receipt))
    assert result.returncode != 0, f"native pytest {failure} was reported successful"
    if receipt.exists():
        value = _load_canonical(receipt)
        assert value.get("completed") is not True or value.get("pytest_exit_code") != 0


@pytest.mark.parametrize("termination", ["early-zero", "interrupt", "abrupt-zero", "collection-error"])
def test_partial_or_interrupted_pytest_never_creates_success_receipts(
    tmp_path: Path, termination: str
) -> None:
    files = {
        "early-zero": {
            "conftest.py": "import pytest\ndef pytest_sessionstart(session): pytest.exit('early zero exit', returncode=0)\n",
            "tests/test_early.py": "def test_never_runs(): pass\n",
        },
        "interrupt": {"tests/test_interrupt.py": "def test_interrupt(): raise KeyboardInterrupt()\n"},
        "abrupt-zero": {"tests/test_abrupt.py": "import os\ndef test_abrupt(): os._exit(0)\n"},
        "collection-error": {"tests/test_broken.py": "def test_broken(:\n    pass\n"},
    }[termination]
    project = _init_project(tmp_path / termination, test_files=files)
    receipt = tmp_path / f"{termination}.json"
    result = _invoke(project, "run", "--shard", "serial", "--output", str(receipt), timeout=10)
    assert result.returncode != 0 or termination == "early-zero"
    if receipt.exists():
        value = _load_canonical(receipt)
        assert value.get("completed") is not True or value.get("pytest_exit_code") != 0


@pytest.mark.parametrize("path_kind", ["existing", "symlink", "directory"])
def test_output_paths_fail_closed_without_overwrite_or_following_symlinks(
    run_bundle: RunBundle, tmp_path: Path, path_kind: str
) -> None:
    target = tmp_path / "victim.json"
    sentinel = b"keep-existing-output-unchanged\n"
    target.write_bytes(sentinel)
    output = tmp_path / "destination"
    if path_kind == "existing":
        output = target
    elif path_kind == "symlink":
        output.symlink_to(target)
    else:
        output.mkdir()
    result = _invoke(run_bundle.project, "collect", "--output", str(output))
    assert result.returncode != 0
    assert target.read_bytes() == sentinel
    if path_kind == "symlink":
        assert output.is_symlink()


def test_input_symlinks_fifos_and_receipt_directory_links_are_rejected(
    run_bundle: RunBundle, tmp_path: Path
) -> None:
    receipts = _copy_receipts(run_bundle, tmp_path / "receipts")
    linked_reference = tmp_path / "linked-reference.json"
    linked_reference.symlink_to(run_bundle.reference)
    result = _invoke(
        run_bundle.project,
        "verify",
        "--reference",
        str(linked_reference),
        "--receipts",
        str(receipts),
    )
    assert result.returncode != 0 and result.stdout == "" and result.stderr == FIXED_ERROR

    linked_receipts = tmp_path / "linked-receipts"
    linked_receipts.mkdir()
    (linked_receipts / "shard-0.json").symlink_to(run_bundle.receipt_zero)
    shutil.copyfile(run_bundle.receipt_one, linked_receipts / "shard-1.json")
    result = _invoke(
        run_bundle.project,
        "verify",
        "--reference",
        str(run_bundle.reference),
        "--receipts",
        str(linked_receipts),
    )
    assert result.returncode != 0 and result.stdout == "" and result.stderr == FIXED_ERROR

    fifo = tmp_path / "reference.fifo"
    os.mkfifo(fifo)
    result = _invoke(
        run_bundle.project,
        "verify",
        "--reference",
        str(fifo),
        "--receipts",
        str(receipts),
        timeout=3,
    )
    assert result.returncode != 0 and result.stdout == "" and result.stderr == FIXED_ERROR


def test_verify_rejects_receipt_nodeid_and_collection_count_limits(
    run_bundle: RunBundle, tmp_path: Path
) -> None:
    receipts = _copy_receipts(run_bundle, tmp_path / "receipts")
    value = copy.deepcopy(run_bundle.shard_zero)
    value["nodeids"][0] = "n" * 262_145
    target = receipts / "shard-0.json"
    target.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    result = _verify(run_bundle, receipts)
    assert result.returncode != 0 and result.stdout == "" and result.stderr == FIXED_ERROR

"""Focused regression tests for the static zero-tool read-only launcher."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "read_only_role_launcher.py"


def _module():
    spec = importlib.util.spec_from_file_location("focused_zero_tool_launcher", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _jsonl(*items: dict[str, object]) -> str:
    return "".join(json.dumps(item) + "\n" for item in items)


def test_launcher_is_materially_smaller_and_has_no_shell_command_parser() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert len(source.splitlines()) < 3_000
    for obsolete in (
        "_command_attempts_nested_codex",
        "_bounded_shell_segments",
        "_bounded_env_split_tokens",
        "direct_codex_attempt_detection",
        "shell_tool=true",
    ):
        assert obsolete not in source


def test_exact_runtime_registry_has_no_generic_version_range() -> None:
    module = _module()
    assert set(module.CODEX_BINARY_REGISTRY) == {
        "0.153.4",
        "0.154.0-alpha.6.2",
    }
    with pytest.raises(module.LauncherError, match="exactly registered"):
        module.validate_binary(
            path=Path(sys.executable).resolve(),
            expected_version="0.154.0",
            expected_sha256="0" * 64,
            expected_team_identifier=module.CODEX_TEAM_IDENTIFIER,
            codesign_probe=lambda _path: {"team_identifier": module.CODEX_TEAM_IDENTIFIER},
        )


def test_binary_validation_uses_hash_and_signature_without_executing_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    binary = tmp_path / "client"
    binary.write_bytes(b"exact trusted client")
    binary.chmod(0o700)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    monkeypatch.setattr(
        module,
        "CODEX_BINARY_REGISTRY",
        {
            "test-exact": {
                "sha256": digest,
                "team_identifier": module.CODEX_TEAM_IDENTIFIER,
            }
        },
    )
    probes: list[Path] = []
    result = module.validate_binary(
        path=binary,
        expected_version="test-exact",
        expected_sha256=digest,
        expected_team_identifier=module.CODEX_TEAM_IDENTIFIER,
        codesign_probe=lambda path: (
            probes.append(path) or {"team_identifier": module.CODEX_TEAM_IDENTIFIER}
        ),
    )
    assert result["executed_for_validation"] is False
    assert probes == [binary.resolve()]


def test_runtime_config_explicitly_disables_shell_and_all_mcp() -> None:
    module = _module()
    config = module.build_zero_tool_runtime_config("reviewer_xhigh", module.DEFAULT_CODEX_VERSION)
    values = module._runtime_config_values(
        config=config,
        instructions="protected",
        effort="xhigh",
    )
    assert "features.shell_tool=false" in values
    assert "features.code_mode_host=true" in values
    assert "agents.enabled=false" in values
    assert "mcp_servers={}" in values
    assert all("shell_tool=true" not in value for value in values)


def test_public_runner_and_plan_builder_have_no_injected_execution_bypass() -> None:
    module = _module()
    assert "process_runner" not in inspect.signature(module.run_isolated_role).parameters
    assert "codesign_probe" not in inspect.signature(module.build_invocation_plan).parameters


def test_supervision_admission_requires_exact_success_shape() -> None:
    module = _module()
    valid = {
        "status": "completed",
        "returncode": 0,
        "bundle_transmitted": True,
        "timed_out": False,
        "output_limited": False,
        "stdin_write_error": False,
        "stdin_writer_joined": True,
        "stdout_drainer_joined": True,
        "stderr_drainer_joined": True,
        "unexpected_descendant": False,
        "cleanup": "clean",
        "cleanup_escalated": False,
        "leader_wait_count": 1,
        "post_reap_group_access": False,
        "handshake_events": [
            "spawn_requested",
            "spawned_blocked_bootstrap",
            "ready",
            "pid_group_validated",
            "observation_armed",
            "released",
            "leader_exit_observed_wnowait",
            "drainers_joined",
            "buffers_frozen",
            "reaped",
        ],
    }
    assert module._supervision_is_admissible(valid) is True
    for field, bad in (
        ("timed_out", True),
        ("stdout_drainer_joined", False),
        ("unexpected_descendant", True),
        ("leader_wait_count", 2),
        ("cleanup", "failed_closed"),
    ):
        assert module._supervision_is_admissible({**valid, field: bad}) is False
    assert (
        module._supervision_is_admissible(
            {**valid, "handshake_events": list(reversed(valid["handshake_events"]))}
        )
        is False
    )


def test_parser_rejects_unknown_top_level_events_and_failed_turns() -> None:
    module = _module()
    for raw in (
        _jsonl({"type": "unknown"}),
        _jsonl(
            {"type": "thread.started", "thread_id": "t"},
            {"type": "turn.started"},
            {"type": "turn.failed", "error": {"message": "failed"}},
        ),
    ):
        with pytest.raises(module.LauncherError, match="unadmitted|incomplete"):
            module.parse_codex_jsonl(raw)


def test_parser_accepts_only_exact_known_loader_diagnostic_item() -> None:
    module = _module()
    diagnostic = (
        "2026-09-12T12:00:00Z WARN codex_agent_roles::loader: "
        "Ignoring malformed agent role definition: failed to parse agent role file at "
        "/tmp/role.toml: TOML parse error at line 1, column 1\n"
        "1 | invalid =\n"
        "  |          ^\n"
        "  = help: expected value"
    )
    raw = _jsonl(
        {"type": "thread.started", "thread_id": "t"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"id": "e", "type": "error", "message": diagnostic},
        },
        {
            "type": "item.completed",
            "item": {
                "id": "a",
                "type": "agent_message",
                "text": "R0001 path x " + "a" * 40 + " " + "b" * 40,
            },
        },
        {"type": "turn.completed"},
    )
    assert module.parse_codex_jsonl(raw)["status"] == "completed"
    hostile = raw.replace("codex_agent_roles::loader", "other::logger")
    with pytest.raises(module.LauncherError, match="unadmitted"):
        module.parse_codex_jsonl(hostile)


def test_runner_rejects_any_nonexact_or_nonmaster_plan(tmp_path: Path) -> None:
    module = _module()
    client = Path(sys.executable).resolve()
    base = {
        "validated": True,
        "launcher_owner": "Master",
        "argv": [str(client), "-I", "-S", "-c", "pass"],
        "exact_argv": (str(client), "-I", "-S", "-c", "pass"),
        "binary_realpath": str(client),
        "cwd": str(tmp_path),
        "exec_env": {"PATH": os.defpath},
    }
    for change in (
        {"launcher_owner": "child"},
        {"validated": False},
        {"exact_argv": (str(client), "--different")},
        {"binary_realpath": "/bin/false"},
    ):
        with pytest.raises(module.LauncherError, match="validated exact"):
            module._run_preexec_handshake({**base, **change})


def test_forged_plain_mapping_cannot_start_even_with_validated_boolean(
    tmp_path: Path,
) -> None:
    module = _module()
    marker = tmp_path / "forged-executed"
    client = Path(sys.executable).resolve()
    source = f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')"
    argv = [str(client), "-I", "-S", "-c", source]
    forged = {
        "validated": True,
        "launcher_owner": "Master",
        "argv": argv,
        "exact_argv": tuple(argv),
        "binary_realpath": str(client),
        "cwd": str(tmp_path),
        "exec_env": {"PATH": os.defpath},
        "timeout_seconds": 2,
    }
    with pytest.raises(module.LauncherError, match="sealed|validated exact"):
        module._run_preexec_handshake(forged)
    assert not marker.exists()


def test_sealed_plan_is_recursively_immutable() -> None:
    module = _module()
    plan = module._ValidatedZeroToolPlan(
        {
            "argv": ["/trusted/client", "exec"],
            "exact_argv": ("/trusted/client", "exec"),
            "exec_env": {"PATH": "/trusted/bin"},
            "config_values": ["shell_tool=false"],
        },
        seal=module._PLAN_SEAL,
    )
    with pytest.raises(TypeError):
        plan["exec_env"]["PATH"] = "/attacker"  # type: ignore[index]
    with pytest.raises(TypeError):
        plan["config_values"][0] = "shell_tool=true"  # type: ignore[index]


def test_bounded_subprocess_stops_output_before_memory_growth() -> None:
    module = _module()
    with pytest.raises(module.LauncherError, match="output bound"):
        module._run_bounded_subprocess(
            [
                str(Path(sys.executable).resolve()),
                "-I",
                "-S",
                "-c",
                "import sys; sys.stdout.buffer.write(b'x' * 1000000)",
            ],
            input_bytes=None,
            env={"PATH": os.defpath},
            timeout=3,
            max_stdout=1024,
            max_stderr=1024,
        )


def test_external_spec_short_circuit_never_calls_process_runner() -> None:
    module = _module()
    result = module.run_isolated_role(
        {
            "validated": True,
            "launcher_owner": "Master",
            "role": "external_spec_researcher",
        }
    )
    assert result["status"] == "insufficient_evidence"
    assert result["model_started"] is False
    assert result["bundle_transmitted"] is False


@pytest.mark.parametrize(
    "path",
    [
        b"/absolute",
        b"../escape",
        b"-option",
        b"line\nbreak",
        "bidi\u202e.txt".encode(),
        b"a" * 513,
        b"bad\xff",
    ],
)
def test_path_validation_fails_closed(path: bytes) -> None:
    module = _module()
    with pytest.raises(module.LauncherError):
        module._safe_path(path)


def test_trusted_context_requires_master_exact_head_and_complete_categories() -> None:
    module = _module()
    head = "a" * 40
    categories = (
        "jit",
        "roadmap_row",
        "phase_design",
        "phase_implementation",
        "red",
        "green",
        "ci",
    )
    records = [
        {
            "category": category,
            "producer": "Master",
            "head_sha": head,
            "command": None,
            "status": (
                "not_applicable"
                if category in {"roadmap_row", "phase_design", "phase_implementation"}
                else "pass"
            ),
            "output_digest": hashlib.sha256(category.encode()).hexdigest(),
            "observed_at": "2026-09-12T12:00:00Z",
            "content": category,
        }
        for category in categories
    ]
    assert (
        len(module._trusted_context(records, scope_kind="harness_maintenance", expected_head=head))
        == 7
    )
    with pytest.raises(module.LauncherError, match="producer|provenance"):
        module._trusted_context(
            [{**records[0], "producer": "candidate"}, *records[1:]],
            scope_kind="harness_maintenance",
            expected_head=head,
        )
    with pytest.raises(module.LauncherError, match="roadmap context"):
        module._trusted_context(
            records,
            scope_kind="roadmap",
            expected_head=head,
        )


def test_manifest_rejects_nonzero_tool_counts() -> None:
    module = _module()
    with pytest.raises(module.LauncherError, match="nonzero tool"):
        module.build_redacted_manifest(
            {
                "launcher_owner": "Master",
                "policy_head_sha": "1" * 40,
                "policy_tree_sha": "2" * 40,
                "target_base_sha": "3" * 40,
                "target_head_sha": "4" * 40,
                "target_tree_sha": "5" * 40,
                "role": "reviewer_high",
                "config_path": ".codex/agents/reviewer-high.toml",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "binary_realpath": "/trusted/codex",
                "binary_version": "exact",
                "binary_sha256": "6" * 64,
                "git_realpath": "/trusted/git",
                "git_version": "exact",
                "git_sha256": "7" * 64,
            },
            bundle={
                "byte_length": 1,
                "digest": "8" * 64,
                "record_ids": ("R0001",),
            },
            prompt_digest="9" * 64,
            event_digest="a" * 64,
            output_digest="b" * 64,
            parsed={"command_count": 1, "mcp_call_count": 0, "tool_call_count": 1},
            supervision={"cleanup": "clean"},
            observed_at_ms=1,
        )


def test_cli_help_is_static_and_does_not_start_client() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 0
    assert "--expected-target-base-sha" in completed.stdout
    assert "--trusted-context-json" in completed.stdout
    assert "--scope-kind" in completed.stdout

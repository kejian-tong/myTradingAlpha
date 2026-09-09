"""RED contracts for prospective read-only child admission.

These tests deliberately exercise a host-observation contract rather than
assuming that a child role's TOML can override the live parent sandbox.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/runtime_capability_receipt.py"
ROLE_CONFIG = ".codex/agents/reviewer-high.toml"
EXTERNAL_ROLE_CONFIG = ".codex/agents/external-spec-researcher.toml"

_READ_ONLY_ROLES = (
    "reviewer_high",
    "reviewer_xhigh",
    "code_explorer",
    "test_auditor",
    "boundary_reviewer",
    "external_spec_researcher",
    "astra_canary",
)
_WRITER_ROLES = (
    "normal_implementer",
    "high_implementer",
    "critical_implementer",
)

_V1_FIELDS = (
    "schema_version",
    "evidence_source",
    "source_ref",
    "session_digest",
    "turn_digest",
    "agent_digest",
    "pr_id",
    "role",
    "config_path",
    "runtime_version",
    "multi_agent_version",
    "model",
    "reasoning_effort",
    "base_sha",
    "head_sha",
    "tree_sha",
    "sandbox_mode",
    "permission_system",
    "permission_profile",
    "approval_policy",
    "tool_inventory_complete",
    "tool_names",
    "observed_at_ms",
)
_ADMISSION_FIELDS = (
    "parent_session_digest",
    "permission_epoch_digest",
    "spawn_event_digest",
    "parent_permission_system",
    "parent_sandbox_mode",
    "parent_permission_profile",
    "parent_approval_policy",
    "parent_observation_complete",
    "spawn_observation_complete",
    "parent_observed_at_ms",
    "child_activity_before_admission",
)
_TRUSTED_DIGEST_PARAMETERS = (
    "expected_parent_session_digest",
    "expected_permission_epoch_digest",
    "expected_spawn_event_digest",
)

_PARENT_SESSION_DIGEST = "e" * 64
_PERMISSION_EPOCH_DIGEST = "f" * 64
_SPAWN_EVENT_DIGEST = "0" * 64


def _module():
    if not SCRIPT.is_file():
        pytest.fail("missing implementation: scripts/runtime_capability_receipt.py")
    spec = importlib.util.spec_from_file_location("runtime_capability_receipt", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(ref: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", ref], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _v1_receipt(**overrides: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": 1,
        "evidence_source": "host_runtime",
        "source_ref": "a" * 64,
        "session_digest": "b" * 64,
        "turn_digest": "c" * 64,
        "agent_digest": "d" * 64,
        "pr_id": "HARNESS-AUD-03",
        "role": "reviewer_high",
        "config_path": ROLE_CONFIG,
        "runtime_version": "codex-runtime-test",
        "multi_agent_version": "v2",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "base_sha": _git("HEAD"),
        "head_sha": _git("HEAD"),
        "tree_sha": _git("HEAD^{tree}"),
        "sandbox_mode": "read-only",
        "permission_system": "legacy_sandbox",
        "permission_profile": "disabled",
        "approval_policy": "never",
        "tool_inventory_complete": True,
        "tool_names": ["view_image"],
        "observed_at_ms": 200,
    }
    receipt.update(overrides)
    return receipt


def _admission_receipt(**overrides: object) -> dict[str, object]:
    receipt = _v1_receipt(
        schema_version=2,
        parent_session_digest=_PARENT_SESSION_DIGEST,
        permission_epoch_digest=_PERMISSION_EPOCH_DIGEST,
        spawn_event_digest=_SPAWN_EVENT_DIGEST,
        parent_permission_system="legacy_sandbox",
        parent_sandbox_mode="read-only",
        parent_permission_profile="disabled",
        parent_approval_policy="never",
        parent_observation_complete=True,
        spawn_observation_complete=True,
        parent_observed_at_ms=100,
        child_activity_before_admission=False,
    )
    receipt.update(overrides)
    return receipt


def _external_admission_receipt(**overrides: object) -> dict[str, object]:
    configured = tomllib.loads(
        (ROOT / EXTERNAL_ROLE_CONFIG).read_text(encoding="utf-8")
    )
    enabled_tools = configured["mcp_servers"]["openaiDeveloperDocs"]["enabled_tools"]
    receipt = _admission_receipt(
        role="external_spec_researcher",
        config_path=EXTERNAL_ROLE_CONFIG,
        model="gpt-5.6-luna",
        reasoning_effort="max",
        tool_names=[f"mcp__openaiDeveloperDocs__{tool}" for tool in enabled_tools],
    )
    receipt.update(overrides)
    return receipt


def _generic_errors(receipt: object) -> list[str]:
    result = _module().verify_receipt(
        receipt,
        repo_root=ROOT,
        expected_pr_id="HARNESS-AUD-03",
        expected_base_sha=_git("HEAD"),
        expected_head_sha=_git("HEAD"),
        expected_role="reviewer_high",
        expected_config_path=ROLE_CONFIG,
    )
    assert isinstance(result, list)
    return result


def _admission_verifier():
    verifier = getattr(_module(), "verify_read_only_admission", None)
    if verifier is None:
        pytest.fail(
            "missing implementation: verify_read_only_admission in "
            "scripts/runtime_capability_receipt.py"
        )
    return verifier


def _admission_call_kwargs(
    *,
    expected_pr_id: str = "HARNESS-AUD-03",
    expected_base_sha: str | None = None,
    expected_head_sha: str | None = None,
    expected_role: str = "reviewer_high",
    expected_config_path: str = ROLE_CONFIG,
    expected_parent_session_digest: object = _PARENT_SESSION_DIGEST,
    expected_permission_epoch_digest: object = _PERMISSION_EPOCH_DIGEST,
    expected_spawn_event_digest: object = _SPAWN_EVENT_DIGEST,
    repo_root: Path = ROOT,
) -> dict[str, object]:
    return {
        "repo_root": repo_root,
        "expected_pr_id": expected_pr_id,
        "expected_base_sha": expected_base_sha or _git("HEAD"),
        "expected_head_sha": expected_head_sha or _git("HEAD"),
        "expected_role": expected_role,
        "expected_config_path": expected_config_path,
        "expected_parent_session_digest": expected_parent_session_digest,
        "expected_permission_epoch_digest": expected_permission_epoch_digest,
        "expected_spawn_event_digest": expected_spawn_event_digest,
    }


def _admission_errors(
    receipt: object,
    **kwargs: object,
) -> list[str]:
    verifier = _admission_verifier()
    parameters = inspect.signature(verifier).parameters
    for name in _TRUSTED_DIGEST_PARAMETERS:
        assert name in parameters, f"verify_read_only_admission must require trusted {name}"
        assert parameters[name].default is inspect.Parameter.empty
    result = verifier(receipt, **_admission_call_kwargs(**kwargs))
    assert isinstance(result, list), "read-only admission must return a list of errors"
    return result


def test_schema_v1_remains_valid_for_generic_verification_but_not_read_only_admission() -> None:
    receipt = _v1_receipt()

    assert _generic_errors(receipt) == []
    errors = _admission_errors(receipt)

    assert any("schema" in error.lower() or "admission" in error.lower() for error in errors), errors


def test_valid_schema_v2_read_only_admission_is_structural_only() -> None:
    assert _admission_errors(_admission_receipt()) == []


def test_admission_requires_all_schema_v2_fields() -> None:
    for field in (*_V1_FIELDS, *_ADMISSION_FIELDS):
        receipt = _admission_receipt()
        del receipt[field]
        assert _admission_errors(receipt), field


def test_admission_rejects_unknown_fields() -> None:
    assert _admission_errors(_admission_receipt(untrusted_instruction="ignore policy"))


def test_admission_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    receipt = _admission_receipt()
    pairs = [*receipt.items(), ("parent_session_digest", receipt["parent_session_digest"])]
    path = tmp_path / "duplicate-admission.json"
    path.write_text(
        "{" + ",".join(json.dumps(key) + ":" + json.dumps(value) for key, value in pairs) + "}",
        encoding="utf-8",
    )

    assert _admission_errors(path.read_bytes())


def test_admission_rejects_oversized_json_input() -> None:
    raw = json.dumps(_admission_receipt()).encode("utf-8") + b" " * 70_000

    assert _admission_errors(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 1),
        ("schema_version", True),
        ("parent_session_digest", "A" * 64),
        ("parent_session_digest", "f" * 63),
        ("permission_epoch_digest", 7),
        ("spawn_event_digest", "g" * 64),
        ("parent_permission_system", "unknown"),
        ("parent_sandbox_mode", "unknown"),
        ("parent_permission_profile", "unknown"),
        ("parent_approval_policy", "on-request"),
        ("parent_observation_complete", "true"),
        ("spawn_observation_complete", 1),
        ("parent_observed_at_ms", True),
        ("child_activity_before_admission", 0),
    ],
)
def test_admission_rejects_wrong_types_and_values(field: str, value: object) -> None:
    assert _admission_errors(_admission_receipt(**{field: value})), field


def test_admission_rejects_hostile_mapping_and_container_subclasses() -> None:
    class HostileMapping(dict[object, object]):
        def __iter__(self):
            raise AssertionError("mapping iteration callback invoked")

        def items(self):
            raise AssertionError("mapping items callback invoked")

        def get(self, key: object, default: object = None):
            raise AssertionError("mapping get callback invoked")

        def __getitem__(self, key: object):
            raise AssertionError("mapping item callback invoked")

    class HostileList(list[object]):
        def __iter__(self):
            raise AssertionError("list iteration callback invoked")

        def __len__(self):
            raise AssertionError("list length callback invoked")

        def __getitem__(self, key: object):
            raise AssertionError("list item callback invoked")

    assert _admission_errors(HostileMapping())
    assert _admission_errors(_admission_receipt(tool_names=HostileList()))


def test_admission_rejects_hostile_scalar_subclasses_before_callbacks() -> None:
    callbacks: list[str] = []

    class HostileStr(str):
        __hash__ = str.__hash__

        def __eq__(self, other: object) -> bool:
            callbacks.append("eq")
            return super().__eq__(other)

        def __ne__(self, other: object) -> bool:
            callbacks.append("ne")
            return super().__ne__(other)

    errors = _admission_errors(
        _admission_receipt(parent_sandbox_mode=HostileStr("read-only"))
    )

    assert errors
    assert callbacks == []


def test_admission_rejects_hostile_raw_bytes_before_callbacks() -> None:
    callbacks: list[str] = []

    class HostileBytes(bytes):
        def decode(self, *args: object, **kwargs: object) -> str:
            callbacks.append("decode")
            return bytes(self).decode(*args, **kwargs)

        def __eq__(self, other: object) -> bool:
            callbacks.append("eq")
            return super().__eq__(other)

    errors = _admission_errors(HostileBytes(json.dumps(_admission_receipt()).encode()))

    assert errors
    assert callbacks == []


def test_trusted_digest_parameters_are_required_and_have_no_defaults() -> None:
    parameters = inspect.signature(_admission_verifier()).parameters

    for name in _TRUSTED_DIGEST_PARAMETERS:
        assert name in parameters
        assert parameters[name].default is inspect.Parameter.empty


@pytest.mark.parametrize(
    "parameter",
    _TRUSTED_DIGEST_PARAMETERS,
)
def test_missing_trusted_digest_cannot_be_omitted(parameter: str) -> None:
    kwargs = _admission_call_kwargs()
    del kwargs[parameter]

    with pytest.raises(TypeError):
        _admission_verifier()(_admission_receipt(), **kwargs)


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("expected_parent_session_digest", "f" * 64),
        ("expected_permission_epoch_digest", "e" * 64),
        ("expected_spawn_event_digest", "1" * 64),
        ("expected_parent_session_digest", "A" * 64),
        ("expected_permission_epoch_digest", None),
        ("expected_spawn_event_digest", 7),
    ],
)
def test_missing_or_mismatched_trusted_digest_fails_closed(
    parameter: str, value: object
) -> None:
    kwargs = _admission_call_kwargs()
    kwargs[parameter] = value

    assert _admission_errors(_admission_receipt(), **kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parent_sandbox_mode", "workspace-write"),
        ("parent_sandbox_mode", "danger-full-access"),
        ("parent_sandbox_mode", "disabled"),
        ("parent_sandbox_mode", "unknown"),
        ("parent_permission_profile", "workspace-write"),
        ("parent_permission_profile", ":workspace"),
        ("parent_permission_profile", ":danger-full-access"),
        ("parent_permission_profile", "disabled"),
        ("parent_permission_profile", "unknown"),
        ("parent_permission_system", "unknown"),
    ],
)
def test_parent_effective_capability_must_be_read_only(
    field: str, value: object
) -> None:
    assert _admission_errors(_admission_receipt(**{field: value})), field


def test_permission_profile_read_only_tuple_is_supported_without_legacy_sandbox() -> None:
    receipt = _admission_receipt(
        permission_system="permission_profile",
        sandbox_mode="disabled",
        permission_profile=":read-only",
        parent_permission_system="permission_profile",
        parent_sandbox_mode="disabled",
        parent_permission_profile=":read-only",
    )

    assert _admission_errors(receipt) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("approval_policy", "untrusted"),
        ("approval_policy", "on-failure"),
        ("approval_policy", "on-request"),
        ("parent_approval_policy", "untrusted"),
        ("parent_approval_policy", "on-failure"),
        ("parent_approval_policy", "on-request"),
    ],
)
def test_parent_and_child_approval_must_be_never(field: str, value: object) -> None:
    assert _admission_errors(_admission_receipt(**{field: value})), field


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sandbox_mode", "workspace-write"),
        ("sandbox_mode", "danger-full-access"),
        ("sandbox_mode", "disabled"),
        ("permission_system", "unknown"),
        ("permission_profile", ":workspace"),
        ("permission_profile", ":danger-full-access"),
    ],
)
def test_child_effective_capability_must_be_read_only(field: str, value: object) -> None:
    assert _admission_errors(_admission_receipt(**{field: value})), field


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parent_observation_complete", False),
        ("spawn_observation_complete", False),
        ("tool_inventory_complete", False),
    ],
)
def test_incomplete_parent_spawn_or_child_observation_fails_closed(
    field: str, value: object
) -> None:
    assert _admission_errors(_admission_receipt(**{field: value})), field


@pytest.mark.parametrize("parent_observed_at_ms", [200, 300])
def test_parent_observation_must_precede_child_observation(
    parent_observed_at_ms: int,
) -> None:
    assert _admission_errors(
        _admission_receipt(parent_observed_at_ms=parent_observed_at_ms)
    )


def test_child_activity_before_admission_invalidates_the_lane() -> None:
    errors = _admission_errors(
        _admission_receipt(child_activity_before_admission=True)
    )

    assert any(
        "activity" in error.lower()
        or "admission" in error.lower()
        or "insufficient" in error.lower()
        for error in errors
    ), errors


@pytest.mark.parametrize(
    ("kwargs", "receipt_overrides"),
    [
        ({"expected_pr_id": "HARNESS-AUD-02"}, {}),
        ({"expected_base_sha": "e" * 40}, {}),
        ({"expected_head_sha": "e" * 40}, {}),
        ({"expected_role": "code_explorer", "expected_config_path": ".codex/agents/code-explorer.toml"}, {}),
        ({"expected_config_path": ".codex/agents/code-explorer.toml"}, {}),
        ({}, {"pr_id": "HARNESS-AUD-02"}),
        ({}, {"role": "code_explorer"}),
        ({}, {"config_path": ".codex/agents/code-explorer.toml"}),
        ({}, {"tree_sha": "f" * 40}),
        ({}, {"session_digest": "f" * 64}),
        ({}, {"parent_session_digest": "f" * 64}),
    ],
)
def test_stale_or_mismatched_identity_fails_closed(
    kwargs: dict[str, object], receipt_overrides: dict[str, object]
) -> None:
    assert _admission_errors(
        _admission_receipt(**receipt_overrides),
        **kwargs,
    )


@pytest.mark.parametrize(
    "tool_names",
    [
        ["mcp__github__list_pull_requests"],
        ["mcp__openaiDeveloperDocs__search_openai_docs"],
        ["mcp__openaiDeveloperDocs__fetch_openai_doc"],
        ["web__run"],
        ["browser.open"],
        ["unknown_external_tool"],
    ],
)
def test_read_only_admission_rejects_external_or_unknown_tool_surfaces(
    tool_names: list[str],
) -> None:
    assert _admission_errors(_admission_receipt(tool_names=tool_names))


@pytest.mark.parametrize("tool_names", [[], ["view_image"], ["list_agents"], ["wait_agent"], ["exec_command"]])
def test_read_only_admission_accepts_reviewed_local_read_only_tools(
    tool_names: list[str],
) -> None:
    assert _admission_errors(_admission_receipt(tool_names=tool_names)) == []


def test_external_researcher_keeps_only_the_reviewed_docs_mcp_allowlist() -> None:
    assert _admission_errors(_external_admission_receipt()) == []
    assert _admission_errors(
        _external_admission_receipt(
            tool_names=["mcp__openaiDeveloperDocs__fetch_openai_docs"]
        )
    )


def _role_config(role: str) -> dict[str, object]:
    path = ROOT / ".codex/agents" / f"{role.replace('_', '-')}.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_exactly_seven_roles_are_read_only_and_three_are_writers() -> None:
    assert len(_READ_ONLY_ROLES) == 7
    assert len(_WRITER_ROLES) == 3

    for role in _READ_ONLY_ROLES:
        assert _role_config(role).get("sandbox_mode") == "read-only", role
    for role in _WRITER_ROLES:
        assert _role_config(role).get("sandbox_mode") != "read-only", role


def test_read_only_roles_require_handshake_then_host_observation_before_work() -> None:
    required_clauses = (
        "read-only admission",
        "admission-only",
        "first child turn",
        "handshake-only",
        "no tools",
        "post-spawn",
        "approval",
        "host observation",
        "substantive work",
        "insufficient_evidence",
    )

    for role in _READ_ONLY_ROLES:
        instructions = str(_role_config(role).get("developer_instructions", "")).lower()
        missing = [clause for clause in required_clauses if clause not in instructions]
        assert not missing, f"{role} is missing read-only admission clauses: {missing}"


def test_writer_roles_remain_writable_and_do_not_require_read_only_admission() -> None:
    for role in _WRITER_ROLES:
        config = _role_config(role)
        assert config.get("sandbox_mode") != "read-only", role
        instructions = str(config.get("developer_instructions", "")).lower()
        assert "read-only admission" not in instructions, role


_POLICY_SOURCES = (
    ROOT / "AGENTS.md",
    ROOT / ".codex/config.toml",
    ROOT / "docs/productionization/AGENT_AUDIT_PROTOCOL.md",
    ROOT / "docs/productionization/HYBRID_CONCURRENCY_PROTOCOL.md",
    ROOT / "docs/productionization/CODEX_HARNESS_TELEMETRY.md",
)


def test_each_policy_source_declares_read_only_admission_scope() -> None:
    for path in _POLICY_SOURCES:
        text = path.read_text(encoding="utf-8").lower()
        assert "read-only" in text, path
        assert "admission" in text, path


def test_policy_sources_define_fail_closed_handshake_and_authenticity_boundaries() -> None:
    policy = "\n".join(path.read_text(encoding="utf-8") for path in _POLICY_SOURCES).lower()
    required_markers = (
        ("read-only parent", ("read-only parent", "parent read-only", "parent is read-only")),
        ("before spawn", ("before spawn", "prior to spawn", "selected before")),
        ("first-turn handshake", ("first child turn", "handshake-only", "handshake only")),
        ("no first-turn tools", ("first turn: no tools", "first-turn no tools", "handshake-only/no tools")),
        ("post-spawn host observation", ("post-spawn", "post spawn")),
        ("lane invalidation", ("lane invalid", "invalidate.*lane", "invalidates.*lane")),
        ("insufficient evidence", ("insufficient_evidence", "insufficient evidence")),
        ("model self-report is not authentication", ("self-report", "self report")),
        ("JSONL is not authentication", ("jsonl",)),
        ("doctor output is not authentication", ("doctor",)),
        ("TOML is not authentication", ("toml authentication", "toml is not authentication", "authenticate toml")),
        ("standalone fallback is disallowed", ("standalone",)),
        ("generic fallback is disallowed", ("generic.*fallback", "generic worker")),
    )
    for description, alternatives in required_markers:
        assert any(marker in policy for marker in alternatives), description

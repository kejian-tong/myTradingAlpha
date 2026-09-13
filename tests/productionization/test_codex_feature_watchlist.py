from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _checker():
    path = ROOT / "scripts/check_agent_harness.py"
    spec = importlib.util.spec_from_file_location("agent_harness_checker_watchlist", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_harness_fixture(tmp_path: Path) -> Path:
    """Copy every input read by the offline checker before one watchlist mutation."""
    shutil.copytree(ROOT / ".codex", tmp_path / ".codex")
    shutil.copytree(ROOT / ".agents/skills", tmp_path / ".agents/skills")
    shutil.copytree(ROOT / "docs/productionization", tmp_path / "docs/productionization")
    for relative in (
        "AGENTS.md",
        "mytradingalpha/AGENTS.md",
        "tradingagents/AGENTS.md",
        "tests/productionization/AGENTS.md",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    scripts = (
        "codex_hook_guard.py",
        "codex_telemetry_hook.py",
        "codex_pretool_guard.py",
        "writer_lease.py",
    )
    (tmp_path / "scripts").mkdir()
    for name in scripts:
        shutil.copyfile(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    return tmp_path


def _memory_watchlist_row(text: str) -> str:
    rows = [line for line in text.splitlines() if line.startswith("| Codex Memories (")]
    assert len(rows) == 1, f"expected one Codex Memories row, found {len(rows)}"
    return rows[0]


def _replace_memory_watchlist_row(text: str, replacement: str) -> str:
    lines = text.splitlines()
    matching = [index for index, line in enumerate(lines) if line.startswith("| Codex Memories (")]
    assert len(matching) == 1, f"expected one Codex Memories row, found {len(matching)}"
    lines[matching[0]] = replacement
    return "\n".join(lines) + "\n"


_GOOD_MEMORY_WATCHLIST_ROW = (
    "| Codex Memories (`features.memories`) | explicitly disabled / watch-only | "
    "`features.memories = false` is prospective configuration intent for a trusted project and fresh "
    "session; the CLI `--config`/`--enable` flags remain higher-precedence overrides; it does not retroactively "
    "change running sessions; project configuration does not authenticate live-runtime state | "
    "adoption requires a separate reviewed harness PR |"
)


def test_project_memories_setting_is_explicitly_disabled_as_configuration_intent() -> None:
    checker = _checker()
    config = checker._toml(ROOT / ".codex/config.toml")
    assert config.get("features", {}).get("memories") is False


def test_current_project_has_no_unapproved_watchlist_features() -> None:
    checker = _checker()
    config = checker._toml(ROOT / ".codex/config.toml")
    assert checker._watch_only_feature_errors(ROOT, config) == []


def test_project_apps_setting_is_explicitly_disabled_as_configuration_intent() -> None:
    checker = _checker()
    config = checker._toml(ROOT / ".codex/config.toml")
    assert config.get("features", {}).get("apps") is False


@pytest.mark.parametrize(
    "config",
    [{}, {"features": {}}, {"features": {"apps": True}}],
)
def test_missing_or_enabled_project_apps_setting_is_rejected(
    tmp_path: Path, config: dict[str, object]
) -> None:
    checker = _checker()
    errors = checker._watch_only_feature_errors(tmp_path, config)
    assert any("apps" in error.lower() for error in errors), errors


@pytest.mark.parametrize("memory_value", ["__deleted__", True, 0, "false", [], {}])
def test_project_memories_requires_exact_boolean_false(
    tmp_path: Path, memory_value: object
) -> None:
    checker = _checker()
    config: dict[str, object] = {"features": {"apps": False, "memories": False}}
    features = config["features"]
    assert isinstance(features, dict)
    if memory_value == "__deleted__":
        del features["memories"]
    else:
        features["memories"] = memory_value
    errors = checker._watch_only_feature_errors(tmp_path, config)
    assert any("Codex Memories" in error for error in errors), errors


def test_project_local_rules_are_rejected(tmp_path: Path) -> None:
    checker = _checker()
    (tmp_path / ".codex/rules").mkdir(parents=True)
    errors = checker._watch_only_feature_errors(tmp_path, {})
    assert "project-local Codex Rules require a separate reviewed adoption PR" in errors


def test_permission_profiles_are_rejected_while_sandbox_mode_policy_is_active(tmp_path: Path) -> None:
    checker = _checker()
    for config in (
        {"default_permissions": "project-edit"},
        {"permissions": {"project-edit": {"description": "pilot"}}},
    ):
        errors = checker._watch_only_feature_errors(tmp_path, config)
        assert "Codex Permission Profiles are watch-only while sandbox_mode isolation is active" in errors


def test_memories_otel_and_plugins_require_separate_adoption(tmp_path: Path) -> None:
    checker = _checker()
    cases = (
        ({"features": {"memories": True}}, "Codex Memories are watch-only"),
        ({"memories": {"generate_memories": False}}, "Codex Memories configuration is watch-only"),
        ({"otel": {"exporter": "otlp-http"}}, "Codex OpenTelemetry exporters require"),
        ({"plugins": {"example": {}}}, "repo-level Codex plugin configuration requires"),
    )
    for config, expected in cases:
        assert any(expected in error for error in checker._watch_only_feature_errors(tmp_path, config))


def test_explicitly_disabled_memories_remain_allowed(tmp_path: Path) -> None:
    checker = _checker()
    assert checker._watch_only_feature_errors(
        tmp_path, {"features": {"apps": False, "memories": False}}
    ) == []


def test_watchlist_documents_all_reviewed_decisions() -> None:
    text = (ROOT / "docs/productionization/CODEX_FEATURE_WATCHLIST.md").read_text(encoding="utf-8")
    for term in ("Codex Rules", "Permission Profiles", "Codex Memories", "OpenTelemetry", "plugin"):
        assert term in text
    assert "separate reviewed harness PR" in text


def test_memory_watchlist_documents_explicit_disablement_and_runtime_limits() -> None:
    text = (ROOT / "docs/productionization/CODEX_FEATURE_WATCHLIST.md").read_text(encoding="utf-8")
    row = _memory_watchlist_row(text).lower()
    for phrase in (
        "explicitly disabled",
        "watch-only",
        "prospective",
        "trusted project",
        "fresh session",
        "configuration intent",
        "cli",
        "--config",
        "--enable",
        "higher-precedence",
        "running sessions",
        "retroactively",
        "live-runtime",
        "authenticate",
    ):
        assert phrase in row, f"Memory watchlist row is missing truthful limitation: {phrase}"


def test_checker_rejects_memory_watchlist_host_enforcement_claim(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / "docs/productionization/CODEX_FEATURE_WATCHLIST.md"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        _replace_memory_watchlist_row(original, _GOOD_MEMORY_WATCHLIST_ROW), encoding="utf-8"
    )
    assert checker.configuration_errors(fixture) == []

    hostile_row = _GOOD_MEMORY_WATCHLIST_ROW.replace(
        "project configuration does not authenticate live-runtime state",
        "project configuration enforces the live host runtime",
    )
    path.write_text(_replace_memory_watchlist_row(original, hostile_row), encoding="utf-8")
    errors = checker.configuration_errors(fixture)
    assert any("memory" in error.lower() and "watch" in error.lower() for error in errors), errors


def test_checker_rejects_memory_watchlist_missing_authentication_negation(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / "docs/productionization/CODEX_FEATURE_WATCHLIST.md"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        _replace_memory_watchlist_row(original, _GOOD_MEMORY_WATCHLIST_ROW), encoding="utf-8"
    )
    assert checker.configuration_errors(fixture) == []

    hostile_row = _GOOD_MEMORY_WATCHLIST_ROW.replace(
        "project configuration does not authenticate live-runtime state",
        "project configuration does authenticate live-runtime state",
    )
    path.write_text(_replace_memory_watchlist_row(original, hostile_row), encoding="utf-8")
    errors = checker.configuration_errors(fixture)
    assert any("memory" in error.lower() and "watch" in error.lower() for error in errors), errors


def test_checker_rejects_memory_watchlist_contradictory_authentication_claim(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / "docs/productionization/CODEX_FEATURE_WATCHLIST.md"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        _replace_memory_watchlist_row(original, _GOOD_MEMORY_WATCHLIST_ROW), encoding="utf-8"
    )
    assert checker.configuration_errors(fixture) == []

    contradictory_row = _GOOD_MEMORY_WATCHLIST_ROW.replace(
        "project configuration does not authenticate live-runtime state |",
        "project configuration does not authenticate live-runtime state; "
        "Project configuration authenticates live-runtime state. |",
    )
    path.write_text(_replace_memory_watchlist_row(original, contradictory_row), encoding="utf-8")
    errors = checker.configuration_errors(fixture)
    assert any("memory" in error.lower() and "watch" in error.lower() for error in errors), errors


def test_checker_rejects_memory_watchlist_missing_cli_config_override(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / "docs/productionization/CODEX_FEATURE_WATCHLIST.md"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        _replace_memory_watchlist_row(original, _GOOD_MEMORY_WATCHLIST_ROW), encoding="utf-8"
    )
    assert checker.configuration_errors(fixture) == []

    missing_config_row = _GOOD_MEMORY_WATCHLIST_ROW.replace("`--config`/", "")
    path.write_text(
        _replace_memory_watchlist_row(original, missing_config_row), encoding="utf-8"
    )
    errors = checker.configuration_errors(fixture)
    assert any("memory" in error.lower() and "config" in error.lower() for error in errors), errors


def test_telemetry_documents_trusted_role_and_config_path() -> None:
    text = (ROOT / "docs/productionization/CODEX_HARNESS_TELEMETRY.md").read_text(
        encoding="utf-8"
    )
    assert "trusted expected role" in text
    assert "trusted expected config path" in text


def test_audit_protocol_records_official_web_fallback_limitation() -> None:
    text = (ROOT / "docs/productionization/AGENT_AUDIT_PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    assert "authorized official web/browser fallback" in text
    assert "does not satisfy the narrow OpenAI Developer Docs MCP receipt" in text
    assert "insufficient_evidence" in text
    assert "GIT_NO_REPLACE_OBJECTS" in text

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _checker():
    path = ROOT / "scripts/check_agent_harness.py"
    spec = importlib.util.spec_from_file_location("agent_harness_checker_watchlist", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    assert checker._watch_only_feature_errors(tmp_path, {"features": {"memories": False}}) == []


def test_watchlist_documents_all_reviewed_decisions() -> None:
    text = (ROOT / "docs/productionization/CODEX_FEATURE_WATCHLIST.md").read_text(encoding="utf-8")
    for term in ("Codex Rules", "Permission Profiles", "Codex Memories", "OpenTelemetry", "plugin"):
        assert term in text
    assert "separate reviewed harness PR" in text

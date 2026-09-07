from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/productionization/AGENT_STATE.md"
POLICY = ROOT / "docs/productionization/AGENT_STATE_COMPACTION.md"
HISTORY = ROOT / "docs/productionization/history/README.md"


def test_agent_state_has_absolute_growth_ceiling() -> None:
    # Temporary ceiling while an already-active roadmap PR owns a larger state transition.
    assert STATE.stat().st_size <= 65_536


def test_compaction_policy_preserves_active_owner_and_context_efficiency() -> None:
    policy = POLICY.read_text(encoding="utf-8")
    assert "12 KiB" in policy
    assert "64 KiB" in policy
    assert "do **not** create a competing state rewrite" in policy
    assert "GitHub/current `main` remains" in policy


def test_cold_history_is_not_current_execution_authority() -> None:
    history = HISTORY.read_text(encoding="utf-8")
    assert "primary durable evidence" in history
    assert "automatically loaded execution policy" in history

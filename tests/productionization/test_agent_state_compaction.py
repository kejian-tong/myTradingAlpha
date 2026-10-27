from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/productionization/AGENT_STATE.md"
POLICY = ROOT / "docs/productionization/AGENT_STATE_COMPACTION.md"
CONTEXT_POLICY = ROOT / "docs/productionization/CONTEXT_MANAGEMENT.md"
HISTORY = ROOT / "docs/productionization/history/README.md"


def test_current_agent_state_stays_within_the_six_kib_snapshot_target() -> None:
    assert STATE.stat().st_size <= 6_144


def test_compaction_policy_is_bounded_and_distinguishes_target_from_guard() -> None:
    policy_bytes = POLICY.read_bytes()
    policy = policy_bytes.decode("utf-8")
    assert len(policy_bytes) <= 6_144
    assert "6 KiB" in policy
    assert "12 KiB" in policy
    assert "64 KiB" not in policy
    assert "do **not** create a competing state rewrite" in policy
    assert "GitHub/current `main` remains" in policy


def test_context_policy_has_bounded_summary_target_without_dropping_required_evidence() -> None:
    assert CONTEXT_POLICY.is_file(), "context management policy is missing"
    context_bytes = CONTEXT_POLICY.read_bytes()
    context = context_bytes.decode("utf-8")
    normalized = " ".join(context.lower().split())

    assert len(context_bytes) <= 6_144
    assert re.search(
        r"(?:4096\s*(?:bytes)?|4\s*kib).{0,100}(?:summary|handoff|task|result)|"
        r"(?:summary|handoff|task|result).{0,100}(?:4096\s*(?:bytes)?|4\s*kib)",
        normalized,
    )
    assert re.search(r"\b(?:full|complete)\b.{0,80}\binstructions?\b", normalized)
    assert "review" in normalized
    assert re.search(r"\b(?:full|complete)\b.{0,80}\b(?:tests?|validation)\b", normalized)
    assert re.search(r"\bci\b", normalized)
    assert "evidence" in normalized


def test_cold_history_is_not_current_execution_authority() -> None:
    history = HISTORY.read_text(encoding="utf-8")
    assert "primary durable evidence" in history
    assert "automatically loaded execution policy" in history

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / ".agents/skills/productionization-preflight/SKILL.md"
JIT = ROOT / ".agents/skills/jit-scope-contract/SKILL.md"
BOUNDARY = ROOT / ".codex/agents/boundary-reviewer.toml"

RISK_TAGS = (
    "untrusted_input",
    "serialization_canonicalization",
    "secret_redaction",
    "temporal_provenance",
    "resource_complexity",
    "concurrency_idempotency",
    "external_side_effect",
)


def test_preflight_defines_exact_risk_profile_and_mandatory_boundary_lane() -> None:
    text = PREFLIGHT.read_text(encoding="utf-8")
    assert all(f"`{tag}`" in text for tag in RISK_TAGS)
    assert "If **any** risk tag is true" in text
    assert "before RED/GREEN implementation" in text
    assert "boundary_reviewer" in text
    assert "adversarial contract matrix" in text
    assert "insufficient_evidence" in text


def test_jit_requires_adversarial_closure_for_true_tags() -> None:
    text = JIT.read_text(encoding="utf-8")
    assert "complete preflight `risk_profile`" in text
    assert "for every true risk tag" in text
    assert "attack/failure cases ->" in text
    assert "Do not postpone a known preflight" in text
    assert "BLOCKER/HIGH" in text


def test_boundary_reviewer_is_read_only_and_knows_every_risk_tag() -> None:
    text = BOUNDARY.read_text(encoding="utf-8")
    assert 'sandbox_mode = "read-only"' in text
    assert "[agents]\nenabled = false" in text
    assert all(f"`{tag}`" in text for tag in RISK_TAGS)
    assert "exact reconciled base SHA" in text
    assert "adversarial contract matrix" in text
    assert "Do not edit files" in text


def test_shift_left_policy_does_not_replace_final_exact_head_review() -> None:
    preflight = PREFLIGHT.read_text(encoding="utf-8")
    boundary = BOUNDARY.read_text(encoding="utf-8")
    assert "do not replace the controlling exact-head reviewer" in preflight
    assert "not a waiver of final review" in boundary

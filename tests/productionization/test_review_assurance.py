"""Contracts for exact-head review assurance without native admission."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_POLICY_SURFACES = (
    Path("AGENTS.md"),
    Path("docs/productionization/AGENTS.md"),
    Path("docs/productionization/AGENT_AUDIT_PROTOCOL.md"),
    Path("docs/productionization/HYBRID_CONCURRENCY_PROTOCOL.md"),
    Path(".codex/config.toml"),
    Path(".agents/skills/productionization-preflight/SKILL.md"),
    Path(".agents/skills/jit-scope-contract/SKILL.md"),
    Path(".agents/skills/exact-head-review/SKILL.md"),
    Path(".agents/skills/merge-gate/SKILL.md"),
)
LEGACY_GATE_PHRASES = (
    "fresh host-enforced read-only parent",
    "first child turn is admission-only",
    "follow-up substantive task",
    "interrupt and discard the lane",
)


def _text(relative: Path) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _all_active_policy_text() -> str:
    return "\n\n".join(_text(relative) for relative in ACTIVE_POLICY_SURFACES)


def _contains(text: str, *patterns: str) -> bool:
    return any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in patterns
    )


def test_active_policy_retires_native_admission_gate_and_degraded_fallback() -> None:
    text = _all_active_policy_text()
    assert "DEGRADED_MASTER_REVIEW" not in text
    for phrase in LEGACY_GATE_PHRASES:
        assert phrase not in text


def test_missing_host_attestation_is_supplemental_disclosure_not_a_stop() -> None:
    root = _text(Path("AGENTS.md"))
    protocol = _text(Path("docs/productionization/AGENT_AUDIT_PROTOCOL.md"))
    combined = f"{root}\n{protocol}"

    for fact in (
        "host-origin",
        "sandbox",
        "approval",
        "tool inventory",
    ):
        assert fact in combined.casefold(), fact
    assert _contains(
        combined,
        r"missing host-origin.{0,240}(?:sandbox.{0,80}approval|approval.{0,80}sandbox)"
        r".{0,240}tool inventory.{0,240}supplemental disclosure.{0,120}"
        r"(?:does not|must not).{0,80}(?:block|stop)",
    )
    assert "Missing evidence is `insufficient_evidence`" not in combined


def test_exact_head_review_uses_separate_non_mutating_git_isolation() -> None:
    text = _text(Path(".agents/skills/exact-head-review/SKILL.md"))
    for required in (
        "fresh reviewer context different from the implementer",
        "detached isolated Git worktree",
        "RED replay",
        "required CI",
    ):
        assert required.casefold() in text.casefold(), required
    for evidence in ("SHA", "cleanliness"):
        assert _contains(
            text,
            rf"(?:before/after|before and after).{{0,100}}{evidence}",
            rf"{evidence}.{{0,100}}(?:before/after|before and after)",
        ), evidence
    assert _contains(text, r"review.{0,80}fresh|fresh.{0,80}review")
    for prohibited in ("edit", "commit", "push", "merge", "delegate"):
        assert _contains(
            text,
            rf"(?:does not|do not|never|cannot).{{0,100}}{prohibited}",
        ), prohibited


def test_review_artifact_and_merge_gate_remain_exact_head_and_fail_closed() -> None:
    protocol = _text(Path("docs/productionization/AGENT_AUDIT_PROTOCOL.md"))
    merge_gate = _text(Path(".agents/skills/merge-gate/SKILL.md"))
    for text in (protocol, merge_gate):
        assert "DEGRADED_MASTER_REVIEW" not in text
        assert _contains(text, r"exact[- ]head|exact SHA")
        assert _contains(text, r"BLOCKER.{0,80}HIGH")
        assert _contains(text, r"required CI")
    assert _contains(merge_gate, r"controlling reviewer.{0,120}APPROVE")


def test_human_paper_live_and_promotion_gates_remain_mandatory() -> None:
    text = _all_active_policy_text()
    assert _contains(
        text,
        r"human.{0,80}(?:paper/live|paper and live|promotion).{0,120}(?:mandatory|required|cannot waive)",
        r"(?:paper/live|paper and live|promotion).{0,120}(?:human).{0,120}(?:mandatory|required|cannot waive)",
    )

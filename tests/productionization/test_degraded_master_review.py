"""RED contracts for truthful degraded Harness-only review assurance.

These tests intentionally inspect policy surfaces instead of runtime receipts.  The
repository cannot authenticate host capability from checked-in text; the GREEN
implementation must therefore describe the fallback's limits and evidence
requirements without presenting it as independent review.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_SURFACES = (
    Path("AGENTS.md"),
    Path("docs/productionization/AGENT_AUDIT_PROTOCOL.md"),
    Path("docs/productionization/HYBRID_CONCURRENCY_PROTOCOL.md"),
    Path(".codex/config.toml"),
    Path(".agents/skills/jit-scope-contract/SKILL.md"),
    Path(".agents/skills/exact-head-review/SKILL.md"),
    Path(".agents/skills/merge-gate/SKILL.md"),
)
FALLBACK_MARKER = "DEGRADED_MASTER_REVIEW"


def _text(relative: Path) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _all_policy_text() -> str:
    return "\n\n".join(_text(relative) for relative in POLICY_SURFACES)


def _degraded_context(text: str) -> str:
    """Return the policy section(s) that define the named fallback.

    Markdown headings keep the extraction stable when explanatory paragraphs are
    added.  TOML has no headings, so a marker anywhere in that file includes the
    whole bounded configuration contract.
    """

    sections = re.split(r"(?m)(?=^#{1,6}\s)", text)
    matches = [section for section in sections if FALLBACK_MARKER in section]
    return "\n\n".join(matches)


def _require_any(text: str, *phrases: str) -> None:
    folded = text.casefold()
    assert any(phrase.casefold() in folded for phrase in phrases), phrases


def _require_pattern(text: str, *patterns: str) -> None:
    assert any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in patterns), patterns


def test_named_fallback_is_explicit_on_every_authoritative_policy_surface() -> None:
    missing = [
        str(relative)
        for relative in POLICY_SURFACES
        if FALLBACK_MARKER not in _text(relative)
    ]
    assert not missing, f"missing {FALLBACK_MARKER} contract surface: {missing}"


def test_native_read_only_independent_review_remains_preferred_and_production_fails_closed() -> None:
    context = _degraded_context(_all_policy_text())
    _require_pattern(
        context,
        r"native.{0,120}host[- ]enforced.{0,120}read[- ]only.{0,120}preferred",
        r"native.{0,120}read[- ]only.{0,120}independent.{0,120}preferred",
    )
    for boundary in (
        "product",
        "roadmap",
        "broker",
        "paper/live",
        "promotion",
        "externally consequential",
        "critical safety",
    ):
        assert boundary in context.casefold(), boundary
    _require_any(context, "fail closed", "fail-closed")


def test_degraded_review_is_narrowly_bounded_to_authorized_harness_maintenance() -> None:
    context = _degraded_context(_all_policy_text())
    _require_pattern(
        context,
        r"harness[- ]only.{0,100}maintenance",
        r"maintenance[- ]only.{0,100}harness",
    )
    _require_any(context, "narrow", "bounded", "limited")
    _require_pattern(
        context,
        r"native.{0,120}(unavailable|not available|cannot be established)",
        r"(unavailable|not available|cannot be established).{0,120}native",
    )


def test_degraded_review_requires_explicit_per_task_evidence() -> None:
    context = _degraded_context(_all_policy_text())
    _require_pattern(
        context,
        r"explicit.{0,60}per[- ]task.{0,80}human authorization",
        r"human authorization.{0,80}each task",
    )
    _require_pattern(
        context,
        r"exact[- ]head.{0,100}review",
        r"review.{0,100}exact[- ]head",
    )
    _require_pattern(
        context,
        r"(?:complete|all).{0,60}required (?:CI|checks)",
        r"required (?:CI|checks).{0,60}(?:complete|all)",
    )
    _require_pattern(
        context,
        r"durable.{0,80}master.{0,80}evidence",
        r"master.{0,80}durable.{0,80}evidence",
    )
    _require_pattern(
        context,
        r"disclos(?:e|ure).{0,120}(?:missing|unavailable).{0,80}runtime evidence",
        r"missing.{0,80}runtime evidence.{0,120}disclos(?:e|ure)",
    )


def test_degraded_review_never_claims_independence_or_fabricates_runtime_telemetry() -> None:
    context = _degraded_context(_all_policy_text())
    _require_pattern(
        context,
        r"(?:never|must not|does not|cannot).{0,80}(?:call|describe|present|claim).{0,80}independent review",
        r"not an independent review",
        r"not independent review",
    )
    _require_pattern(
        context,
        r"(?:never|must not|do not).{0,80}fabricat(?:e|ing).{0,120}(?:reviewer|model|runtime)",
        r"(?:reviewer|model|runtime).{0,120}(?:never|must not|do not).{0,80}fabricat",
    )
    _require_any(context, "missing runtime evidence", "unavailable runtime evidence")


def test_degraded_review_cannot_authorize_roadmap_or_paper_live_promotion_work() -> None:
    context = _degraded_context(_all_policy_text())
    _require_pattern(
        context,
        r"(?:does not|cannot|must not|never).{0,120}(?:authorize|permit|waive).{0,100}(?:roadmap|production)",
        r"(?:roadmap|production).{0,100}(?:does not|cannot|must not|never).{0,120}(?:authorize|permit|waive)",
    )
    _require_pattern(
        context,
        r"(?:does not|cannot|must not|never).{0,120}(?:waive|bypass|override).{0,100}(?:PAPER/live|paper/live|promotion)",
        r"(?:PAPER/live|paper/live|promotion).{0,100}(?:does not|cannot|must not|never).{0,120}(?:waive|bypass|override)",
    )
    _require_pattern(
        context,
        r"(?:does not|cannot|must not|never).{0,120}(?:authorize|permit).{0,100}broker",
        r"broker.{0,100}(?:does not|cannot|must not|never).{0,120}(?:authorize|permit)",
    )


def test_unconditional_native_review_stop_language_is_qualified_only_for_fallback() -> None:
    context = _degraded_context(_all_policy_text())
    _require_any(context, "unconditional", "qualified", "exception")
    _require_pattern(
        context,
        r"(?:only|solely|limited).{0,100}(?:fallback|degraded_master_review).{0,100}(?:exception|qualification)",
        r"(?:fallback|degraded_master_review).{0,100}(?:only|solely|limited).{0,100}(?:exception|qualification)",
    )

"""Contract tests for runtime-neutral collaboration-control policy wording."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_POLICY_SURFACES = (
    Path("AGENTS.md"),
    Path(".codex/config.toml"),
    Path("docs/productionization/AGENT_AUDIT_PROTOCOL.md"),
    Path("docs/productionization/HYBRID_CONCURRENCY_PROTOCOL.md"),
)
_GENERATION_LABELS = (
    "GPT-5.6 Sol Multi-Agent V2",
    "Codex Multi-Agent V2",
    "Multi-Agent V2",
)
_BEHAVIORAL_POLICY_CLAUSE_ALTERNATIVES = (
    ("master-only delegation is a behavioral policy",),
    (
        "collaboration-control visibility alone is non-blocking",
        "collaboration-control visibility alone is not a stop condition",
    ),
    (
        "do not invoke collaboration controls or delegate nested work",
        "non-master roles must not invoke those controls or delegate nested work",
    ),
    (
        "any attempted or completed nested delegation is a blocking policy violation",
        "any attempted or completed nested delegation, including a runtime-denied or no-op attempt, "
        "is a blocking policy violation",
    ),
)


def test_collaboration_policy_is_runtime_neutral_across_mutable_surfaces() -> None:
    violations = {
        str(relative): [label for label in _GENERATION_LABELS if label in (ROOT / relative).read_text(encoding="utf-8")]
        for relative in _POLICY_SURFACES
    }
    violations = {relative: labels for relative, labels in violations.items() if labels}
    assert not violations, (
        "mutable collaboration policy must describe runtime capability rather than a model/client "
        f"generation label: {violations}"
    )


def test_runtime_neutral_policy_preserves_behavioral_delegation_contract() -> None:
    missing: dict[str, list[str]] = {}
    for relative in _POLICY_SURFACES:
        text = " ".join((ROOT / relative).read_text(encoding="utf-8").lower().split())
        required = [
            " / ".join(alternatives)
            for alternatives in _BEHAVIORAL_POLICY_CLAUSE_ALTERNATIVES
            if not any(clause in text for clause in alternatives)
        ]
        required.extend(
            marker
            for marker in ("collaboration controls", "runtime", "non-master", "[agents]")
            if marker not in text
        )
        if "enabled" not in text or "false" not in text:
            required.append("[agents] enabled=false configuration intent")
        if required:
            missing[str(relative)] = required
    assert not missing, f"runtime-neutral policy removed required behavioral contract: {missing}"

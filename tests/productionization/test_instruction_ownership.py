"""HARNESS-AUD-19 RED contracts for compact, owned instruction surfaces.

These contracts inspect only checked-in text and TOML.  They make the approved
compression boundary observable before any policy prose is removed: byte
budgets, bounded duplicate markers, responsibility ownership, routing-neutral
procedures, and preservation of the existing executable harness contracts.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]

SKILL_NAMES = (
    "productionization-preflight",
    "jit-scope-contract",
    "tdd-red-green-evidence",
    "exact-head-review",
    "merge-gate",
    "writer-lease",
)

ROLE_SPECS = {
    "normal_implementer": ("gpt-5.6-luna", "max", False),
    "high_implementer": ("gpt-5.6-sol", "high", False),
    "critical_implementer": ("gpt-5.6-sol", "xhigh", False),
    "reviewer_high": ("gpt-5.6-sol", "high", True),
    "reviewer_xhigh": ("gpt-5.6-sol", "xhigh", True),
    "code_explorer": ("gpt-5.6-luna", "max", True),
    "test_auditor": ("gpt-5.6-luna", "max", True),
    "boundary_reviewer": ("gpt-5.6-sol", "high", True),
    "external_spec_researcher": ("gpt-5.6-luna", "max", True),
    "astra_canary": ("gpt-6-astra", "xhigh", True),
}

ROOT_SURFACE = Path("AGENTS.md")
CONFIG_SURFACE = Path(".codex/config.toml")
AUDIT_SURFACE = Path("docs/productionization/AGENT_AUDIT_PROTOCOL.md")
HYBRID_SURFACE = Path("docs/productionization/HYBRID_CONCURRENCY_PROTOCOL.md")
SKILL_SURFACES = tuple(Path(".agents/skills") / name / "SKILL.md" for name in SKILL_NAMES)
ROLE_SURFACES = tuple(
    Path(".codex/agents") / f"{name.replace('_', '-')}.toml" for name in ROLE_SPECS
)
CORE_SURFACES = (ROOT_SURFACE, CONFIG_SURFACE, AUDIT_SURFACE, HYBRID_SURFACE, *SKILL_SURFACES)
ALL_SURFACES = (*CORE_SURFACES, *ROLE_SURFACES)

# These are deliberately lexical, normalized marker contracts rather than a
# line-count heuristic.  A marker is counted once per explicit policy token;
# uniform role prohibitions are outside this metric by design.
MARKER_PATTERNS = {
    "master-only": re.compile(r"\bmaster-only\b", re.IGNORECASE),
    "one-writer": re.compile(r"\bone-writer\b", re.IGNORECASE),
    "review-assurance": re.compile(r"\breview assurance\b", re.IGNORECASE),
    "exact-head": re.compile(r"\bexact-head\b", re.IGNORECASE),
    "paper/live": re.compile(r"\bpaper/live\b", re.IGNORECASE),
    "GPT-6-disabled": re.compile(
        r"\bGPT-6\b[^.\n]{0,100}\bdisabled\b", re.IGNORECASE
    ),
    "collaboration visibility": re.compile(
        r"collaboration-control visibility", re.IGNORECASE
    ),
}

BYTE_BUDGETS = {
    ROOT_SURFACE: 16_000,
    CONFIG_SURFACE: 4_000,
    AUDIT_SURFACE: 24_000,
    HYBRID_SURFACE: 10_500,
}
TOTAL_BUDGET = 95_000
SKILLS_BUDGET = 24_000
ROLES_BUDGET = 18_000
ROLE_BUDGET = 3_000
MARKER_BUDGET = 65


def _path(relative: Path) -> Path:
    return ROOT / relative


def _text(relative: Path) -> str:
    return _path(relative).read_text(encoding="utf-8")


def _bytes(relative: Path) -> int:
    return len(_path(relative).read_bytes())


def _contains(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in patterns)


def _toml(relative: Path) -> dict[str, object]:
    value = tomllib.loads(_text(relative))
    assert isinstance(value, dict)
    return value


def _marker_counts() -> dict[str, int]:
    texts = [_text(relative) for relative in CORE_SURFACES]
    return {
        marker: sum(len(pattern.findall(text)) for text in texts)
        for marker, pattern in MARKER_PATTERNS.items()
    }


def test_instruction_surfaces_fit_the_approved_byte_budgets() -> None:
    measured = {str(relative): _bytes(relative) for relative in ALL_SURFACES}
    violations = {
        str(relative): f"{measured[str(relative)]}>{limit}"
        for relative, limit in BYTE_BUDGETS.items()
        if measured[str(relative)] > limit
    }
    skills_size = sum(measured[str(relative)] for relative in SKILL_SURFACES)
    roles_size = sum(measured[str(relative)] for relative in ROLE_SURFACES)
    role_violations = {
        str(relative): f"{measured[str(relative)]}>{ROLE_BUDGET}"
        for relative in ROLE_SURFACES
        if measured[str(relative)] > ROLE_BUDGET
    }
    total = sum(measured.values())

    budget_violations = dict(violations)
    if skills_size > SKILLS_BUDGET:
        budget_violations["six skills total"] = f"{skills_size}>{SKILLS_BUDGET}"
    if roles_size > ROLES_BUDGET:
        budget_violations["role TOMLs total"] = f"{roles_size}>{ROLES_BUDGET}"
    budget_violations.update(role_violations)
    if total > TOTAL_BUDGET:
        budget_violations["all tracked surfaces total"] = f"{total}>{TOTAL_BUDGET}"
    assert not budget_violations, (
        f"instruction budgets exceeded: {budget_violations}; measured={measured}"
    )


def test_duplicate_policy_markers_fit_the_compression_budget() -> None:
    counts = _marker_counts()
    total = sum(counts.values())

    assert total <= MARKER_BUDGET, f"duplicate critical markers {total}>{MARKER_BUDGET}: {counts}"


def test_root_owns_global_invariants_authority_safety_routing_and_boundaries() -> None:
    text = _text(ROOT_SURFACE)

    assert _contains(text, r"tradingagents/", r"mytradingalpha/")
    assert _contains(text, r"roadmap", r"approved architecture")
    assert _contains(text, r"PAPER/live", r"promotion")
    assert _contains(text, r"Master-only delegation")
    assert _contains(text, r"Default named roles", r"Role \| Model / effort")
    assert _contains(text, r"gpt[- .]?5\.6[- /]luna", r"GPT-5\.6 Luna")
    assert _contains(text, r"gpt[- .]?5\.6[- /]sol", r"GPT-5\.6 Sol")
    assert _contains(text, r"gpt[- .]?6[- /]astra", r"GPT-6 Astra")
    assert _contains(text, r"one[- ]writer", r"single[- ]writer", r"merge gate")
    assert _contains(text, r"## 11\. Stop conditions", r"stop conditions")

    for relative in (
        "docs/productionization/AGENTS.md",
        "mytradingalpha/AGENTS.md",
        "tradingagents/AGENTS.md",
        "tests/productionization/AGENTS.md",
    ):
        assert relative in text, f"root must route to scoped instructions: {relative}"
    for name in SKILL_NAMES:
        assert name in text, f"root must advertise repository skill: {name}"


def test_audit_protocol_owns_review_assurance_and_exact_head_evidence() -> None:
    text = _text(AUDIT_SURFACE)

    assert _contains(text, r"review.{0,80}assurance")
    assert "host-origin evidence" in text
    assert _contains(text, r"hook runtime manifest")
    assert "host-runtime evidence" in text
    assert _contains(text, r"supplemental.{0,120}(?:disclos|evidence)")
    assert "DEGRADED_MASTER_REVIEW" not in text
    assert _contains(text, r"independent.{0,100}review.{0,100}artifact")
    assert "MASTER MERGE GATE" in text or "master merge-gate artifact" in text.lower()
    assert _contains(text, r"## 8\. Exact-head rule")
    assert _contains(text, r"exact-head.{0,100}SHA")


def test_hybrid_protocol_owns_one_writer_scheduling_and_review_phases() -> None:
    text = _text(HYBRID_SURFACE)

    assert _contains(text, r"one production-code writer", r"one writer")
    assert "max_concurrent_threads_per_session = 6" in text
    for phase in ("Phase A", "Phase B", "Phase C"):
        assert phase in text, f"hybrid protocol must retain {phase}"
    assert _contains(text, r"Repair and re-review loop")
    assert _contains(text, r"Master synthesis and merge gate")


def test_config_keeps_runtime_settings_and_short_policy_references() -> None:
    config = _toml(CONFIG_SURFACE)
    assert config.get("model") == "gpt-5.6-sol"
    assert config.get("model_reasoning_effort") == "xhigh"
    assert config.get("agents") == {
        "enabled": True,
        "max_concurrent_threads_per_session": 6,
    }
    assert config.get("features") == {"apps": False, "memories": False}

    instructions = str(config.get("developer_instructions", ""))
    for reference in (
        "AGENTS.md",
        "AGENT_AUDIT_PROTOCOL.md",
        "HYBRID_CONCURRENCY_PROTOCOL.md",
    ):
        assert reference in instructions, f"config must point to {reference}"
    assert _contains(instructions, r"master[- ]only", r"Master-only")
    assert _contains(instructions, r"review.{0,40}assurance")
    assert _contains(instructions, r"one[- ]writer", r"one.{0,20}writer", r"writer lease")


def test_role_tomls_keep_exact_routes_and_role_scoped_responsibilities() -> None:
    collaboration_contract = (
        "Collaboration-control visibility alone is non-blocking.",
        "Do not invoke collaboration controls or delegate nested work.",
        "Any attempted or completed nested delegation is a blocking policy violation.",
    )
    role_markers = {
        "normal_implementer": (r"normal/high/critical", r"red-green-refactor"),
        "high_implementer": (r"high-complexity", r"temporal", r"red-green-refactor"),
        "critical_implementer": (r"critical", r"paper/live", r"safety"),
        "reviewer_high": (r"independent reviewer", r"exact PR head", r"APPROVE"),
        "reviewer_xhigh": (r"critical or escalated", r"exact PR head", r"APPROVE"),
        "code_explorer": (r"code exploration", r"Do not edit"),
        "test_auditor": (r"test", r"Do not edit"),
        "boundary_reviewer": (r"architecture", r"Do not edit"),
        "external_spec_researcher": (r"external", r"official", r"Do not edit"),
        "astra_canary": (r"shadow-only", r"historical", r"active candidate"),
    }

    for name, (model, effort, read_only) in ROLE_SPECS.items():
        relative = Path(".codex/agents") / f"{name.replace('_', '-')}.toml"
        role = _toml(relative)
        assert role.get("name") == name
        assert role.get("model") == model
        assert role.get("model_reasoning_effort") == effort
        assert role.get("agents") == {"enabled": False}
        if read_only:
            assert role.get("sandbox_mode") == "read-only"
            assert role.get("approval_policy") == "never"

        instructions = str(role.get("developer_instructions", ""))
        for clause in collaboration_contract:
            assert clause in instructions, f"{name} lost uniform collaboration contract"
        if read_only:
            assert "must complete before substantive work or any tool call" not in instructions
        for marker in role_markers[name]:
            assert re.search(marker, instructions, flags=re.IGNORECASE), (
                f"{name} lost role-specific responsibility/prohibition: {marker}"
            )


def test_skills_keep_valid_metadata_and_procedural_ownership() -> None:
    purpose_markers = {
        "productionization-preflight": (r"Reconcile", r"Procedure"),
        "jit-scope-contract": (r"JIT", r"scope"),
        "tdd-red-green-evidence": (r"RED", r"GREEN"),
        "exact-head-review": (r"exact-head", r"review"),
        "merge-gate": (r"merge", r"final"),
        "writer-lease": (r"lease", r"acquire", r"release"),
    }
    for name in SKILL_NAMES:
        relative = Path(".agents/skills") / name / "SKILL.md"
        text = _text(relative)
        assert text.startswith("---\n"), f"invalid skill metadata opening: {name}"
        closing = text.find("\n---", 4)
        assert closing > 0, f"invalid skill metadata closing: {name}"
        metadata = text[4:closing]
        assert f"name: {name}\n" in metadata
        assert re.search(r"^description:\s*\S", metadata, flags=re.MULTILINE)
        for marker in purpose_markers[name]:
            assert re.search(marker, text, flags=re.IGNORECASE), (
                f"{name} lost procedural purpose marker: {marker}"
            )


def test_detailed_model_ids_are_owned_by_root_config_and_roles_only() -> None:
    routing_patterns = (
        re.compile(r"\bgpt[- ]?5\.6[- ]?(?:luna|sol)\b", re.IGNORECASE),
        re.compile(r"\bgpt[- ]?6[- ]?astra\b", re.IGNORECASE),
    )
    leaking = {
        str(relative): [match.group(0) for pattern in routing_patterns for match in pattern.finditer(_text(relative))]
        for relative in (AUDIT_SURFACE, HYBRID_SURFACE, *SKILL_SURFACES)
    }
    leaking = {relative: values for relative, values in leaking.items() if values}
    assert not leaking, (
        "detailed model IDs belong in AGENTS.md, .codex/config.toml, and role TOMLs; "
        f"routing-neutral surfaces leaked IDs: {leaking}"
    )


def test_existing_executable_contract_owners_remain_present() -> None:
    owners = {
        "read-only role configuration": Path("tests/productionization/test_read_only_admission.py"),
        "review assurance": Path("tests/productionization/test_review_assurance.py"),
        "one writer": Path("tests/productionization/test_writer_lease.py"),
        "exact head and collaboration": Path("tests/productionization/test_harness_contracts.py"),
        "stop hook": Path("tests/productionization/test_codex_hook_guard.py"),
        "routing": Path("tests/productionization/test_model_routing_benchmark.py"),
    }
    missing = [label for label, relative in owners.items() if not _path(relative).is_file()]
    assert not missing, f"compression must not remove executable contract owners: {missing}"


def test_root_owns_an_explicit_named_route_matrix() -> None:
    text = _text(ROOT_SURFACE)
    assert re.search(r"route matrix", text, flags=re.IGNORECASE), (
        "root AGENTS.md must own the named implementation/reviewer route matrix"
    )
    section = text.split("## 6. Adaptive model routing", 1)[1].split("## 7.", 1)[0]
    route_rows = {
        "normal": ("normal_implementer", "reviewer_high"),
        "high initial": ("normal_implementer", "reviewer_high"),
        "high implementation escalation": ("high_implementer", "reviewer_high"),
        "high review escalation": ("normal_implementer", "reviewer_xhigh"),
        "critical": ("normal_implementer", "reviewer_xhigh"),
        "difficult": ("high_implementer", "reviewer_xhigh"),
        "hardest": ("critical_implementer", "reviewer_xhigh"),
    }
    for label, (writer, reviewer) in route_rows.items():
        matching_rows = [
            line.casefold()
            for line in section.splitlines()
            if label in line.casefold()
        ]
        assert any(writer in line and reviewer in line for line in matching_rows), (
            f"route matrix row {label!r} must bind {writer}+{reviewer}: {matching_rows}"
        )


def test_audit_protocol_owns_receipt_manifest_and_delegation_schema_terms() -> None:
    text = _text(AUDIT_SURFACE)
    for token in (
        "schema_version",
        "evidence_source",
        "permission_system",
        "legacy_sandbox",
        "permission_profile",
        ":read-only",
        "tool_names",
        "expected_pr_id",
        "expected_base_sha",
        "expected_head_sha",
        "expected_role",
        "expected_config_path",
        "64 KiB",
        "duplicate-key",
        "partial-promisor",
        "fetch_openai_doc",
        "search_openai_docs",
        "collaboration_controls_visible",
        "collaboration_observation_complete",
        "non_master_collaboration_invoked",
    ):
        assert token in text, f"audit protocol must own evidence-schema term: {token}"
    assert re.search(
        r"delegation_control_mode\s*[=:]\s*behavioral_policy", text
    ), "audit protocol must name the behavioral delegation evidence mode"


def test_exact_head_skill_uses_independent_review_verdict_tokens() -> None:
    text = _text(Path(".agents/skills/exact-head-review/SKILL.md"))
    assert "DEGRADED_MASTER_REVIEW" not in text
    assert re.search(r"APPROVE\s*\|\s*REQUEST CHANGES", text), (
        "exact-head review must preserve the independent review verdict tokens"
    )


def test_compressed_policy_prose_has_no_malformed_fragments_or_list_breaks() -> None:
    root = _text(ROOT_SURFACE)
    assert "does not load its;" not in root
    assert "auto-loaded.\n`AGENTS.md`" not in root
    assert "English/Chinese handling in prose" not in root

    preflight = _text(Path(".agents/skills/productionization-preflight/SKILL.md"))
    clause = "do not replace the controlling exact-head reviewer"
    assert preflight.casefold().count(clause) == 1
    procedure = preflight.split("## Procedure", 1)[1].split("## Adversarial", 1)[0]
    in_numbered_steps = False
    for line in procedure.splitlines():
        if re.match(r"^\d+\.\s", line):
            in_numbered_steps = True
            continue
        if in_numbered_steps and line.strip() and not line.startswith("##"):
            assert line.startswith("   "), f"list continuation lost indentation: {line!r}"


def test_role_descriptions_remain_meaningful_after_compression() -> None:
    for role in ("normal_implementer", "high_implementer"):
        description = str(_toml(Path(".codex/agents") / f"{role.replace('_', '-')}.toml")["description"])
        assert len(description) >= 20, role
        assert re.search(r"implement(?:er|ation|ing)", description, flags=re.IGNORECASE), (
            f"{role} description must identify implementation responsibility: {description!r}"
        )


def test_root_route_matrix_replaces_the_ambiguous_route_summary() -> None:
    text = _text(ROOT_SURFACE)
    assert "Normal/high/critical routes use Luna/max plus Sol/high initially" not in text
    assert not re.search(
        r"critical[^|\n]{0,100}(?:reviewer_high|Sol/high)", text, flags=re.IGNORECASE
    ), "critical work must not be mapped to the initial reviewer or Sol/high in prose"


def test_audit_permission_schema_states_both_read_only_system_pairs() -> None:
    text = _text(AUDIT_SURFACE)
    assert re.search(r"\bschema_version\s*=\s*1\b", text)
    assert re.search(r"\bevidence_source\s*=\s*host_runtime\b", text)

    legacy = re.search(
        r"permission_system\s*=\s*legacy_sandbox(?P<body>.{0,240})",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert legacy and re.search(r"active.{0,80}read[- ]only", legacy.group("body"), re.IGNORECASE)
    assert legacy and re.search(
        r"permission_profile\s*=\s*disabled", legacy.group("body"), re.IGNORECASE
    )

    profile = re.search(
        r"permission_system\s*=\s*permission_profile(?P<body>.{0,240})",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert profile and re.search(
        r"legacy sandbox.{0,80}disabled", profile.group("body"), re.IGNORECASE
    )
    assert profile and re.search(
        r"permission_profile\s*=\s*:read-only", profile.group("body"), re.IGNORECASE
    )

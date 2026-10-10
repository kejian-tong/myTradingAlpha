"""Contract tests for the bounded pstack skills adaptation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / ".agents/skills/poteto-mode/compatibility.json"
SKILLS_ROOT = ROOT / ".agents/skills"
COMPATIBILITY_DOC = ROOT / "docs/productionization/PSTACK_COMPATIBILITY.md"
NOTICE = ROOT / "docs/productionization/PSTACK_MIT_NOTICE.md"
AGENT_STATE = ROOT / "docs/productionization/AGENT_STATE.md"
SIG05_MERGE_SHA = "d709f16b37e40837c4ee687a6bc03ab92ea55218"
BT01_MERGE_SHA = "a713fbb48324ad9da45e254268b9cfe30b0a634b"
HARNESS_PR90_MERGE_SHA = "8f76f341bedf086dd4eb69e4229be33127f5028f"

EXPECTED_SKILLS = {
    "architect",
    "arena",
    "figure-it-out",
    "how",
    "interrogate",
    "poteto-mode",
    "principle-separate-before-serializing-shared-state",
    "principles-design",
    "principles-verification",
    "show-me-your-work",
    "tdd",
    "technical-writing",
    "why",
}

EXISTING_REPOSITORY_SKILLS = {
    "exact-head-review",
    "jit-scope-contract",
    "merge-gate",
    "productionization-preflight",
    "tdd-red-green-evidence",
    "writer-lease",
}

EXPECTED_EXISTING_SKILL_HASHES = {
    "exact-head-review": "bad23859c9c1d820c53f66fad7199f1a13fbe3f4e784a7c8aa918b74dab92490",
    "jit-scope-contract": "ea9fa972f63b0520ba626d95795e531e8d3dd26ed9088d6b58988bb240b1d8da",
    "merge-gate": "9f97f9ca1df6cc53db5ab3b680c0f4a74f28e65c41ca6fac71371f47059c03e6",
    "productionization-preflight": "9b646e195dd348c61d60b9d8545b1c92352ee2ef43ca5a8754f14e3206e6f9a4",
    "tdd-red-green-evidence": "e1c7e33c6b8a1b2a61875c95f281f6570ea0ed47299515f1445a13792e8d1529",
    "writer-lease": "066cf85bf456c40078e629b658409f49eb4852e9a425b4b8c6b5d6be9f4c581a",
}

EXPECTED_ALL_SKILLS = EXPECTED_SKILLS | EXISTING_REPOSITORY_SKILLS

EXPECTED_AUTHORITY_PATHS = {
    "root_instructions": "AGENTS.md",
    "productionization_instructions": "docs/productionization/AGENTS.md",
    "test_instructions": "tests/productionization/AGENTS.md",
    "productionization_preflight": ".agents/skills/productionization-preflight/SKILL.md",
    "jit_scope_contract": ".agents/skills/jit-scope-contract/SKILL.md",
    "writer_lease": ".agents/skills/writer-lease/SKILL.md",
    "tdd": ".agents/skills/tdd-red-green-evidence/SKILL.md",
    "exact_head_review": ".agents/skills/exact-head-review/SKILL.md",
    "merge_gate": ".agents/skills/merge-gate/SKILL.md",
}

EXPECTED_CANONICAL_SOURCES = {
    "skills/architect/SKILL.md": "741901140ee382ebf93263a7ed03c6ee3719e578416d81afcd195876fa16c496",
    "skills/arena/SKILL.md": "e3a1f6c49a08b7e0b92134e53300d146f1f22ba83386d2019926e736df421851",
    "skills/figure-it-out/SKILL.md": "0eb9485f0e7d84fee56b5d0f0af0faf4635e3ca87c8cba3970c01293b76ecc19",
    "skills/how/SKILL.md": "d31805589c7f6a63a6db6c9fadebbd79fb9660682cf1654e9b2e5e1e7cd30bc0",
    "skills/interrogate/SKILL.md": "59d498c3e9848a24b2d105eb3f05b808aa4152adf4cb1de7bbb6aff4f4cd9b68",
    "skills/poteto-mode/SKILL.md": "404c0ef4a78e93451b2ab555ca532e7197b5cf87de29205b6f7109dbee5d9c4d",
    "skills/principle-exhaust-the-design-space/SKILL.md": "8583310d7297b7823d75494faa57b003564d436807febecdecbd8321abe5cf6e",
    "skills/principle-prove-it-works/SKILL.md": "ec79a15025bac8d33d62011c54f3b612733fd2a024e623b531b3637aa75070e2",
    "skills/principle-redesign-from-first-principles/SKILL.md": "a1c7fd0a96b40e12a74bceb0e6bb20a9666dd844dcabfb624acb27da23b929fe",
    "skills/principle-separate-before-serializing-shared-state/SKILL.md": "05294b40448e927c5da1c7b6f5c6b9fed3744637e3833d2d948b9154a9dd00bb",
    "skills/principle-sequence-verifiable-units/SKILL.md": "2ccbbacc56ace5afdfb8670cef19d7bd009fb2a0033b9a741cbdf2b6baf72187",
    "skills/principle-test-behavior-not-implementation/SKILL.md": "87e40efe4e486f7ea639d2ed1fc0abe6c93b8fd0e89a81218086909d2470a52e",
    "skills/show-me-your-work/SKILL.md": "bcff5f7f9fd23f92c12b251f9cd6b947e9485e1055cfacb6fdd9cae0789d7550",
    "skills/tdd/SKILL.md": "eeb868e2dfebee528d730a67d7b17498fac4bb85dec2e38bc5c5176aca4d5d2f",
    "skills/technical-writing/SKILL.md": "f5c512ffeec70bc4e0dee50f7bb4c26742e1be77967a6e8b15d1921e1c209ceb",
    "skills/why/SKILL.md": "2a852ec8680920109d2b56538b027c52867896a597250ac5d18a13e0b42e5b06",
}

EXPECTED_SKILL_SOURCE_PATHS = {
    "architect": ["skills/architect/SKILL.md"],
    "arena": ["skills/arena/SKILL.md"],
    "figure-it-out": ["skills/figure-it-out/SKILL.md"],
    "how": ["skills/how/SKILL.md"],
    "interrogate": ["skills/interrogate/SKILL.md"],
    "poteto-mode": ["skills/poteto-mode/SKILL.md"],
    "principle-separate-before-serializing-shared-state": [
        "skills/principle-separate-before-serializing-shared-state/SKILL.md"
    ],
    "principles-design": [
        "skills/principle-exhaust-the-design-space/SKILL.md",
        "skills/principle-redesign-from-first-principles/SKILL.md",
    ],
    "principles-verification": [
        "skills/principle-prove-it-works/SKILL.md",
        "skills/principle-sequence-verifiable-units/SKILL.md",
        "skills/principle-test-behavior-not-implementation/SKILL.md",
    ],
    "show-me-your-work": ["skills/show-me-your-work/SKILL.md"],
    "tdd": ["skills/tdd/SKILL.md"],
    "technical-writing": ["skills/technical-writing/SKILL.md"],
    "why": ["skills/why/SKILL.md"],
}

EXPECTED_LICENSE_SHA256 = "bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e"
EXPECTED_POLICY = {
    "repository_instructions": "authoritative",
    "master_first_level_delegation": "allowed",
    "non_master_nested_delegation": "prohibited",
    "production_writers": 1,
    "writer_lease_owner": "master",
    "tdd_authority": "tdd-red-green-evidence",
    "review_authority": "exact-head-review",
    "ci_binding": "candidate_sha",
    "merge_gate": "merge-gate",
    "merge_authority": "master_only",
    "delegate_push": False,
    "delegate_merge": False,
    "autonomous_landing": False,
    "autopilot_full": "prohibited",
    "autopilot_stack": "prohibited",
    "shipping": "prohibited",
    "paper_live_broker_policy": "unchanged",
    "paper_policy": "unchanged",
    "live_policy": "unchanged",
    "broker_policy": "unchanged",
    "roadmap_authorization": "unchanged",
    "roadmap_slice_authorization": "not_granted",
    "model_routing": "unchanged",
    "external_model_fallback": False,
    "arena_comparison": "sequential_same_context",
    "interrogate_authority": "supplemental_only",
    "why_evidence_scope": "repository_only",
    "decision_evidence": "existing_pr_jit_git_ci_review_evidence_only",
    "raw_transcripts": False,
    "private_decision_log": False,
}

EXPECTED_EXCLUDED_CAPABILITIES = {
    "pstack scripts",
    "pstack agents",
    "MCP configuration",
    "automation packs",
    "setup-pstack",
    "swarm",
    "autonomous-run",
    "orchestrate",
    "autopilot-full",
    "autopilot-stack",
    "shipping",
    "autonomous landing",
    "external-model fallback",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_manifest() -> dict[str, Any]:
    raw = MANIFEST_PATH.read_bytes()
    assert len(raw) <= 64 * 1024
    return json.loads(raw, object_pairs_hook=_reject_duplicate_keys)


def _safe_relative_path(raw_path: str) -> PurePosixPath:
    path = PurePosixPath(raw_path)
    assert raw_path and not path.is_absolute()
    assert ".." not in path.parts
    assert "\\" not in raw_path
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skill_frontmatter(path: Path) -> dict[str, str]:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines and lines[0] == "---"
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        assert separator, f"invalid frontmatter line in {path}: {line!r}"
        assert key not in fields, f"duplicate frontmatter field in {path}: {key}"
        fields[key] = value.strip().strip('"').strip("'")
    return fields


def _documented_skill_purposes() -> dict[str, str]:
    document = COMPATIBILITY_DOC.read_text(encoding="utf-8")
    section = re.search(r"(?ms)^## Skill purposes\s*\n(.*?)(?=^## |\Z)", document)
    assert section is not None, "compatibility doc has no skill purpose table"

    purposes: dict[str, str] = {}
    for line in section.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower() == "skill":
            continue
        name = cells[0].strip("`")
        if re.fullmatch(r"[-: ]+", name):
            continue
        assert name not in purposes, f"duplicate skill purpose row: {name}"
        purposes[name] = cells[1]
    return purposes


def test_manifest_pins_canonical_source_and_portable_reference() -> None:
    manifest = _load_manifest()
    canonical = manifest["canonical_source"]
    assert canonical["repository"] == "cursor/plugins/pstack"
    assert canonical["version"] == "0.15.13"
    assert canonical["commit"] == "e5a8186d7b43be8d6ac4452440fbead5f1a51c70"

    sources = canonical["skill_sources"]
    assert len(sources) == len(EXPECTED_CANONICAL_SOURCES)
    assert [entry["path"] for entry in sources] == sorted(EXPECTED_CANONICAL_SOURCES)
    assert len({entry["path"] for entry in sources}) == len(sources)
    assert {entry["path"]: entry["sha256"] for entry in sources} == EXPECTED_CANONICAL_SOURCES
    license_record = canonical["license"]
    assert license_record == {"path": "LICENSE", "sha256": EXPECTED_LICENSE_SHA256}

    portable = manifest["portable_reference"]
    assert portable == {
        "repository": "backnotprop/pstack",
        "version": "0.15.9",
        "head_sha": "124f622bcaeac490e7e9dac6af83f3ef9611d554",
        "upstream_snapshot_repository": "cursor/plugins/pstack",
        "upstream_snapshot_version": "0.15.9",
        "upstream_snapshot_commit": "e43c7ee26e0038c6c1fa8380dd34ce86ff94cb2a",
    }


def test_adapted_skill_inventory_has_codex_metadata_and_pinned_hashes() -> None:
    manifest = _load_manifest()
    inventory = manifest["adapted_skills"]
    assert [entry["name"] for entry in inventory] == sorted(EXPECTED_SKILLS)
    assert len({entry["name"] for entry in inventory}) == len(inventory)

    for entry in inventory:
        name = entry["name"]
        assert name in EXPECTED_SKILLS
        expected_path = f".agents/skills/{name}/SKILL.md"
        assert entry["path"] == expected_path
        assert entry["source_paths"] == EXPECTED_SKILL_SOURCE_PATHS[name]
        skill_path = ROOT / expected_path
        assert not (SKILLS_ROOT / name).is_symlink()
        assert not skill_path.is_symlink()
        assert entry["sha256"] == _sha256(skill_path)
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])

        metadata = _skill_frontmatter(skill_path)
        assert set(metadata) == {"name", "description"}
        assert metadata["name"] == name
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", metadata["name"])
        assert metadata["description"]
        assert metadata["description"] == " ".join(metadata["description"].split())


def test_skill_inventory_preserves_repository_skills_and_documents_adaptations() -> None:
    manifest = _load_manifest()
    inventory = manifest["adapted_skills"]
    adapted_names = {entry["name"] for entry in inventory}
    assert len(inventory) == len(EXPECTED_SKILLS)
    assert adapted_names == EXPECTED_SKILLS

    discovered_skill_names = {
        path.name for path in SKILLS_ROOT.iterdir() if (path / "SKILL.md").is_file()
    }
    assert discovered_skill_names == EXPECTED_ALL_SKILLS

    for name, expected_hash in EXPECTED_EXISTING_SKILL_HASHES.items():
        skill_path = SKILLS_ROOT / name / "SKILL.md"
        assert skill_path.is_file()
        assert not skill_path.is_symlink()
        assert _sha256(skill_path) == expected_hash

    manifest_purposes = {
        entry["name"]: entry.get("adaptation_purpose") for entry in inventory
    }
    assert set(manifest_purposes) == EXPECTED_SKILLS
    assert all(
        isinstance(purpose, str) and purpose.strip()
        for purpose in manifest_purposes.values()
    )

    documented_purposes = _documented_skill_purposes()
    assert set(documented_purposes) == EXPECTED_SKILLS
    assert all(purpose.strip() for purpose in documented_purposes.values())
    assert {
        name: purpose.strip() for name, purpose in manifest_purposes.items()
    } == documented_purposes


def test_manifest_encodes_repository_authority_and_excluded_capabilities() -> None:
    manifest = _load_manifest()
    assert manifest["schema_version"] == 1
    assert manifest["authority"] == EXPECTED_POLICY
    excluded = manifest["excluded_capabilities"]
    assert len(excluded) == len(set(excluded))
    assert set(excluded) == EXPECTED_EXCLUDED_CAPABILITIES


def test_repository_authority_files_and_harness_boundaries_are_explicit() -> None:
    for relative_path in EXPECTED_AUTHORITY_PATHS.values():
        assert (ROOT / relative_path).is_file(), relative_path

    authority = _load_manifest()["authority"]
    assert authority["master_first_level_delegation"] == "allowed"
    assert authority["non_master_nested_delegation"] == "prohibited"
    assert authority["production_writers"] == 1
    assert authority["writer_lease_owner"] == "master"
    assert authority["tdd_authority"] == "tdd-red-green-evidence"
    assert authority["review_authority"] == "exact-head-review"
    assert authority["ci_binding"] == "candidate_sha"
    assert authority["merge_gate"] == "merge-gate"
    assert authority["merge_authority"] == "master_only"
    assert authority["delegate_push"] is False
    assert authority["delegate_merge"] is False
    assert authority["autonomous_landing"] is False
    assert authority["autopilot_full"] == "prohibited"
    assert authority["autopilot_stack"] == "prohibited"
    assert authority["shipping"] == "prohibited"
    assert authority["external_model_fallback"] is False
    assert authority["roadmap_slice_authorization"] == "not_granted"
    assert authority["paper_policy"] == "unchanged"
    assert authority["live_policy"] == "unchanged"
    assert authority["broker_policy"] == "unchanged"
    assert authority["model_routing"] == "unchanged"


def test_manifest_paths_and_record_size_are_portable_and_bounded() -> None:
    raw = MANIFEST_PATH.read_bytes()
    assert 0 < len(raw) <= 64 * 1024
    manifest = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    for entry in manifest["canonical_source"]["skill_sources"]:
        _safe_relative_path(entry["path"])
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    _safe_relative_path(manifest["canonical_source"]["license"]["path"])
    for entry in manifest["adapted_skills"]:
        _safe_relative_path(entry["path"])
    assert b"/Users/" not in raw
    assert b"/tmp/" not in raw
    assert "private_path" not in manifest
    assert "credentials" not in manifest
    assert "raw_session_id" not in manifest
    assert "prompts" not in manifest
    assert "transcripts" not in manifest


def test_duplicate_json_keys_and_unsafe_paths_are_rejected() -> None:
    try:
        json.loads(
            '{"schema_version": 1, "schema_version": 2}',
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate JSON keys must be rejected")

    for raw_path in ("../escape", "/absolute/path", "nested\\windows-path"):
        try:
            _safe_relative_path(raw_path)
        except AssertionError:
            continue
        raise AssertionError(f"unsafe manifest path was accepted: {raw_path!r}")
    assert _safe_relative_path("skills/example/SKILL.md") == PurePosixPath(
        "skills/example/SKILL.md"
    )


def test_routed_skills_preserve_repository_workflow_boundaries() -> None:
    def skill_text(name: str) -> str:
        return (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8").lower()

    wrapper = skill_text("poteto-mode")
    assert "master may delegate first-level work" in wrapper
    assert "non-master nested delegation is prohibited" in wrapper
    assert "one production writer" in wrapper
    assert "master alone merges" in wrapper
    assert "model routing remains unchanged" in wrapper

    arena = skill_text("arena")
    assert "sequentially in the same context" in arena
    assert "do not spawn" in arena

    interrogate = skill_text("interrogate")
    assert "supplemental" in interrogate
    assert "exact-head-review" in interrogate

    why = skill_text("why")
    assert "repository evidence only" in why

    tdd = skill_text("tdd")
    assert "tdd-red-green-evidence" in tdd

    show_work = skill_text("show-me-your-work")
    assert "existing pr, jit, git, ci, and review evidence" in show_work
    assert "do not read raw transcripts" in show_work
    assert "do not create a private log" in show_work


def test_compatibility_document_notice_and_operational_state_are_reconciled() -> None:
    compatibility = COMPATIBILITY_DOC.read_text(encoding="utf-8")
    notice = NOTICE.read_text(encoding="utf-8")
    state = AGENT_STATE.read_text(encoding="utf-8")

    assert "PSTACK_MIT_NOTICE.md" in compatibility
    assert "cursor/plugins/pstack" in compatibility
    assert "MIT License" in notice
    assert "Copyright (c) 2026 Lauren Tan" in notice
    assert "https://github.com/cursor/plugins/tree/main/pstack" in notice
    normalized_state = " ".join(state.split())
    assert (
        f"`last_completed_roadmap_pr`: `BT-01` / PR #96 / merge `{BT01_MERGE_SHA}`"
    ) in normalized_state
    assert (
        f"PR #92's JIT, RED evidence, writer lease lifecycle, review, and CI remain recoverable in "
        f"its GitHub conversation; it merged at `{SIG05_MERGE_SHA}`."
    ) in normalized_state
    assert "PR #90's RED/GREEN, writer lease, exact-head review, and required-check evidence remain in its PR conversation" in state
    assert HARNESS_PR90_MERGE_SHA in state

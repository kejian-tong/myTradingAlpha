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
    "roadmap_authorization": "unchanged",
    "model_routing": "unchanged",
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


def test_manifest_encodes_repository_authority_and_excluded_capabilities() -> None:
    manifest = _load_manifest()
    assert manifest["schema_version"] == 1
    assert manifest["authority"] == EXPECTED_POLICY
    excluded = manifest["excluded_capabilities"]
    assert len(excluded) == len(set(excluded))
    assert set(excluded) == EXPECTED_EXCLUDED_CAPABILITIES


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
    assert "PR #87" in state
    assert "6de1635a90d6c33aee02079dca5d0932e3a32cec" in state
    assert "PR #89" in state
    assert "HARNESS-PSTACK-89" in state
    assert "b75fbb922d7bc091f8de8e2bfad7323584667f33" in state

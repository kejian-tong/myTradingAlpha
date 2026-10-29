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
BT02_MERGE_SHA = "7b818c3f78916375ef80d1a5c65d24a95b5423d5"
HARNESS_PR90_MERGE_SHA = "8f76f341bedf086dd4eb69e4229be33127f5028f"
EXPECTED_CANONICAL_VERSION = "0.15.32"
EXPECTED_CANONICAL_COMMIT = "e73df471cd4bd918367e99f3dd9c51bd53ddf5f0"
EXPECTED_CANONICAL_TREE = "880564357e051d7c7802da1cb5d8df1d0b008299"
PREVIOUS_CANONICAL_VERSION = "0.15.25"
PREVIOUS_CANONICAL_COMMIT = "99743e9c151c8537cbbf1f98bb38f34ef3368453"
PREVIOUS_CANONICAL_TREE = "0d5fd349cbc77d054eed60f0e8cdfbea86321ff9"

EXPECTED_SKILLS = {
    "architect",
    "arena",
    "figure-it-out",
    "how",
    "in-your-own-words",
    "interrogate",
    "ketchup",
    "poteto-mode",
    "principle-separate-before-serializing-shared-state",
    "principles-design",
    "principles-verification",
    "sharpen",
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
EXPECTED_SKILL_DIRECTORIES = EXPECTED_ALL_SKILLS
EXPECTED_SKILLS_ROOT_FILES = {
    *(f"{name}/SKILL.md" for name in EXPECTED_ALL_SKILLS),
    "poteto-mode/compatibility.json",
}

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
    "skills/architect/SKILL.md": "31f8e97a52bfa5432edd61f68ade2a8632ef0bacbc2d2a6802d7a0e6821944ac",
    "skills/arena/SKILL.md": "ed72f6c132b1ce3974d949581d0adc5dade424fe20793ac3b4c4fae22ecb9354",
    "skills/figure-it-out/SKILL.md": "bdb23cdbd82a1e6af094b495691c832a6f7f3ab9706ba9edbeb664ef51a726e1",
    "skills/how/SKILL.md": "08a00079bb15b4258874ac3ff62d4ca7e94350ffedb521d0fd296dc9dd21904e",
    "skills/in-your-own-words/SKILL.md": "fa8ba74e27d7be371dc270ec78bbf816411477d0dfab185356c861ac8dd413ad",
    "skills/interrogate/SKILL.md": "a16dfe179005abc22a4651b82f25b0c8ab953284276efe4e6dc341958fb63647",
    "skills/ketchup/SKILL.md": "f2923ffd14f6fc778f75a47aaed1f317fb5fd00b5701ca769d6446c74106dead",
    "skills/poteto-mode/SKILL.md": "2755f102e7a6d0496b429d1031a22fb353e1f3d523543367caeaae5c4ed6f544",
    "skills/principle-exhaust-the-design-space/SKILL.md": "2de83d99f93f60ec6313455b0bc9aa9f0bfb93dd59f414f403691322db00d4db",
    "skills/principle-prove-it-works/SKILL.md": "ec79a15025bac8d33d62011c54f3b612733fd2a024e623b531b3637aa75070e2",
    "skills/principle-redesign-from-first-principles/SKILL.md": "170e0a658783e43fee8ec5a8c2422a4abb8f69cef621dd1819a95910b8207034",
    "skills/principle-separate-before-serializing-shared-state/SKILL.md": "05294b40448e927c5da1c7b6f5c6b9fed3744637e3833d2d948b9154a9dd00bb",
    "skills/principle-sequence-verifiable-units/SKILL.md": "2ccbbacc56ace5afdfb8670cef19d7bd009fb2a0033b9a741cbdf2b6baf72187",
    "skills/principle-test-behavior-not-implementation/SKILL.md": "f7223698623b6a26fea49c751e466b38e6691b1f32ce841d3983e7ffbe2b74a6",
    "skills/sharpen/SKILL.md": "563dfc460c605d311e650726288e2f1cbd61eab817db178d6e7e29643e07e7a2",
    "skills/show-me-your-work/SKILL.md": "920a8217cbb62f92a2222fb81fc9eab17ecd554a0277e444a95a927195139bd1",
    "skills/tdd/SKILL.md": "eeb868e2dfebee528d730a67d7b17498fac4bb85dec2e38bc5c5176aca4d5d2f",
    "skills/technical-writing/SKILL.md": "61fe9c424a798ebf36ad94941f87be049cb8827bdf86d21474a0dde37b513c43",
    "skills/why/SKILL.md": "144d42e7712723d763e607bc0a969e5f1cdf83ec7228519d87677cc534571bed",
}

EXPECTED_SKILL_SOURCE_PATHS = {
    "architect": ["skills/architect/SKILL.md"],
    "arena": ["skills/arena/SKILL.md"],
    "figure-it-out": ["skills/figure-it-out/SKILL.md"],
    "how": ["skills/how/SKILL.md"],
    "in-your-own-words": ["skills/in-your-own-words/SKILL.md"],
    "interrogate": ["skills/interrogate/SKILL.md"],
    "ketchup": ["skills/ketchup/SKILL.md"],
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
    "sharpen": ["skills/sharpen/SKILL.md"],
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
    "statechart",
    "create-formal-verification-skill",
    "maintain-formal-verification-skill",
    "ketchup-video",
}

# Complete 0.15.25 -> 0.15.32 source delta, grouped by its frozen disposition.
EXPECTED_CURRENT_CHANGE_PATHS_BY_DISPOSITION = {
    "version_provenance_only": [
        ".cursor-plugin/plugin.json",
        "plugin.json",
    ],
    "excluded_source_documentation": [
        "README.md",
        "docs/guide/01-setup.md",
        "docs/guide/02-poteto-mode.md",
        "docs/guide/03-understand.md",
        "docs/guide/04-design.md",
        "docs/guide/05-build-and-clean.md",
        "docs/guide/06-verify-and-ship.md",
        "docs/guide/07-overnight.md",
        "docs/guide/08-principles.md",
        "docs/guide/09-make-it-yours.md",
        "docs/guide/10-recipes-and-pitfalls.md",
        "docs/guide/README.md",
        "docs/harness/claude-code.md",
    ],
    "excluded_pending_separate_scope": [
        "skills/create-formal-verification-skill/SKILL.md",
        "skills/ketchup-video/SKILL.md",
        "skills/maintain-formal-verification-skill/SKILL.md",
        "skills/statechart/SKILL.md",
    ],
    "selected_source_requires_compatible_review": [
        "skills/ketchup/SKILL.md",
        "skills/poteto-mode/SKILL.md",
        "skills/sharpen/SKILL.md",
    ],
    "excluded_existing_allowlist": [
        "skills/make-bot-ui/SKILL.md",
        "skills/poteto-help/SKILL.md",
        "skills/poteto-help/references/recipes.md",
        "skills/reflect/SKILL.md",
        "skills/setup-pstack/SKILL.md",
        "skills/swarm/SKILL.md",
        "skills/typescript-best-practices/SKILL.md",
        "skills/typescript-best-practices/references/patterns.md",
    ],
    "excluded": [
        "skills/poteto-mode/scripts/check-plan.mjs",
        "skills/poteto-mode/scripts/check-plan.test.ts",
        "skills/poteto-mode/scripts/orch/orch.test.ts",
        "skills/poteto-mode/scripts/orch/store.ts",
        "skills/poteto-mode/scripts/watch-pr/github.test.ts",
        "skills/poteto-mode/scripts/watch-pr/github.ts",
        "skills/poteto-mode/scripts/watch-pr/policy.test.ts",
        "skills/poteto-mode/scripts/watch-pr/policy.ts",
        "skills/poteto-mode/scripts/watch-pr/types.ts",
        "skills/poteto-mode/scripts/worktree-audit.sh",
        "skills/statechart/scripts/bug-states.mjs",
        "skills/statechart/scripts/chart-edges.mjs",
        "skills/statechart/scripts/chart-parts.mjs",
        "skills/statechart/scripts/chart-to-tla.mjs",
        "skills/statechart/scripts/compare-charts.mjs",
        "skills/statechart/scripts/lib.mjs",
        "skills/statechart/scripts/map-view.mjs",
        "skills/statechart/scripts/property-loop.mjs",
        "skills/statechart/scripts/read-check.mjs",
        "skills/statechart/scripts/regions-chart.mjs",
        "skills/statechart/scripts/render.mjs",
        "skills/statechart/scripts/rule-book.mjs",
        "skills/statechart/scripts/second-replay.mjs",
        "skills/statechart/scripts/snapshot.mjs",
        "skills/statechart/scripts/spec-text.mjs",
        "skills/statechart/scripts/statechart-help.mjs",
        "skills/statechart/scripts/statechart.mjs",
        "skills/statechart/scripts/test/band.mmd",
        "skills/statechart/scripts/test/regions.mmd",
        "skills/statechart/scripts/test/statechart.test.mjs",
        "skills/statechart/scripts/test/sync.mmd",
        "skills/statechart/scripts/test/upload.mmd",
        "skills/statechart/scripts/tlc-to-chart-args.mjs",
        "skills/statechart/scripts/tlc-to-chart.mjs",
        "skills/statechart/scripts/tlc-tools.mjs",
        "skills/statechart/scripts/ways-in.mjs",
    ],
}
EXPECTED_CURRENT_PATH_DISPOSITIONS = {
    path: disposition
    for disposition, paths in EXPECTED_CURRENT_CHANGE_PATHS_BY_DISPOSITION.items()
    for path in paths
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


def _markdown_sections(document: str) -> list[tuple[str, str]]:
    headings = list(re.finditer(r"(?m)^(#{2,6})\s+(.+?)\s*$", document))
    sections: list[tuple[str, str]] = []
    for index, heading in enumerate(headings):
        level = len(heading.group(1))
        end = len(document)
        for later in headings[index + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        sections.append((heading.group(2).strip(), document[heading.end() : end]))
    return sections


def _section_text(document: str, heading_pattern: str) -> str:
    pattern = re.compile(heading_pattern, re.IGNORECASE)
    matching = [
        f"{heading}\n{body}"
        for heading, body in _markdown_sections(document)
        if pattern.search(heading)
    ]
    assert matching, f"missing Markdown section matching {heading_pattern!r}"
    return "\n".join(matching)


def _compatibility_current_pin(document: str) -> re.Match[str] | None:
    return re.match(
        r"\A# pstack compatibility\n\nThis Harness integration adapts a bounded set of skills from "
        r"`cursor/plugins/pstack` version `([^`]+)`, commit `([0-9a-f]{40})`, whose "
        r"`pstack` subtree is `([0-9a-f]{40})`\.",
        document,
    )


def _represented_current_path_dispositions(section: str) -> tuple[dict[str, str], dict[str, int]]:
    disposition_names = set(EXPECTED_CURRENT_CHANGE_PATHS_BY_DISPOSITION)
    current_heading_disposition: str | None = None
    represented: dict[str, str] = {}
    counts: dict[str, int] = {}
    for line in section.splitlines():
        heading = re.match(r"^\s*#{3,6}\s+(.+?)\s*$", line)
        if heading:
            heading_labels = [
                label for label in disposition_names if label in heading.group(1)
            ]
            current_heading_disposition = (
                heading_labels[0] if len(heading_labels) == 1 else None
            )

        path_mentions = [
            path
            for path in EXPECTED_CURRENT_PATH_DISPOSITIONS
            if f"`{path}`" in line
        ]
        if not path_mentions:
            continue
        inline_labels = [
            label
            for label in disposition_names
            if re.search(rf"(?<![a-z0-9_]){re.escape(label)}(?![a-z0-9_])", line)
        ]
        assert len(inline_labels) <= 1, f"ambiguous disposition row: {line!r}"
        disposition = inline_labels[0] if inline_labels else current_heading_disposition
        assert disposition is not None, f"changed path lacks a disposition: {line!r}"
        for path in path_mentions:
            counts[path] = counts.get(path, 0) + 1
            represented[path] = disposition
    return represented, counts


def test_manifest_pins_canonical_source_and_portable_reference() -> None:
    manifest = _load_manifest()
    canonical = manifest["canonical_source"]
    assert canonical["repository"] == "cursor/plugins/pstack"
    assert canonical["version"] == EXPECTED_CANONICAL_VERSION
    assert canonical["commit"] == EXPECTED_CANONICAL_COMMIT

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


def test_skills_root_recursive_inventory_is_exact_and_has_no_symlinks_or_executables() -> None:
    assert not SKILLS_ROOT.is_symlink()
    files: set[str] = set()
    directories: set[str] = set()

    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(SKILLS_ROOT).as_posix()
            assert not path.is_symlink(), f"skill inventory cannot contain symlinks: {relative}"
            if path.is_dir():
                directories.add(relative)
                visit(path)
                continue
            assert path.is_file(), f"skill inventory contains a non-file: {relative}"
            assert path.stat().st_mode & 0o111 == 0, f"skill inventory cannot contain executable files: {relative}"
            files.add(relative)

    visit(SKILLS_ROOT)
    assert directories == EXPECTED_SKILL_DIRECTORIES
    assert files == EXPECTED_SKILLS_ROOT_FILES


def test_manifest_encodes_repository_authority_and_excluded_capabilities() -> None:
    manifest = _load_manifest()
    assert manifest["schema_version"] == 1
    assert manifest["authority"] == EXPECTED_POLICY
    excluded = manifest["excluded_capabilities"]
    assert len(excluded) == len(set(excluded))
    assert excluded == sorted(EXPECTED_EXCLUDED_CAPABILITIES)
    assert set(excluded) == EXPECTED_EXCLUDED_CAPABILITIES
    adapted_names = {entry["name"] for entry in manifest["adapted_skills"]}
    assert set(excluded).isdisjoint(adapted_names)


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
    assert "ketchup" in wrapper
    assert "in-your-own-words" in wrapper
    assert "sharpen" in wrapper
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


def test_new_routed_skills_keep_catchup_and_restatement_read_only() -> None:
    ketchup = " ".join(
        (SKILLS_ROOT / "ketchup" / "SKILL.md")
        .read_text(encoding="utf-8")
        .lower()
        .split()
    )
    assert "read-only" in ketchup
    assert "last human message" in ketchup
    assert "existing artifacts" in ketchup
    assert "subagent" in ketchup and "notification" in ketchup
    assert not re.search(r"(?:\.\./|skills/)?bro(?:/skill\.md|/)", ketchup)
    for action in (
        r"app(?:lication)?",
        r"job",
        r"capture|screenshot",
        r"post|posting|publish",
        r"transcript",
    ):
        assert re.search(
            rf"\b(?:do not|don't|never|must not|without|prohibited from)\b"
            rf"[^.]*\b(?:{action})\b",
            ketchup,
        ), f"ketchup must prohibit {action.replace('|', '/')} activity"

    restatement = " ".join(
        (SKILLS_ROOT / "in-your-own-words" / "SKILL.md")
        .read_text(encoding="utf-8")
        .lower()
        .split()
    )
    assert "restate" in restatement
    assert "goal" in restatement and "problem" in restatement
    assert any(
        phrase in restatement
        for phrase in (
            "does not authorize action",
            "no action authority",
            "does not grant authority to act",
            "not permission to act",
        )
    )


def test_ketchup_user_decisions_are_self_contained_per_item_and_exclude_agent_work() -> None:
    ketchup = (SKILLS_ROOT / "ketchup" / "SKILL.md").read_text(encoding="utf-8")
    decision_section = _section_text(
        ketchup,
        r"(?:user[- ]owned|user.*(?:decision|action)|(?:decision|action).*user|calls? to surface)",
    )
    normalized = " ".join(decision_section.lower().split())
    assert re.search(r"\b(?:for each|for every|each|every) affected (?:item|call)\b", normalized)
    assert "self-contained" in normalized
    assert re.search(
        r"\bavailable links?\b|\blinks?\b[^.]{0,40}\bavailable\b", normalized
    )
    for field in ("recommendation", "evidence", "risk", "prerequisite", "unknown"):
        assert re.search(rf"\b{field}s?\b", normalized), field

    assert re.search(
        r"(?=[^.]*\b(?:older|earlier)\b)(?=[^.]*\b(?:unresolved|open)\b)"
        r"(?=[^.]*\b(?:already[- ]evidenced|previously evidenced)\b)"
        r"(?=[^.]*\bcalls?\b)[^.]*",
        normalized,
    )
    assert re.search(
        r"\b(?:even if|even when|including when)\b.{0,100}"
        r"\b(?:pre-date|predate|precede|before)\b.{0,80}\b(?:cutoff|last human message)\b",
        normalized,
    )
    assert re.search(
        r"\bagent-owned\b[^.]{0,100}\b(?:not|exclude|do not|must not)\b"
        r"[^.]{0,100}\b(?:user-owned|user action|action item)",
        normalized,
    )


def test_sharpen_rewrites_prompts_and_continues_original_authorized_work() -> None:
    sharpen = (SKILLS_ROOT / "sharpen" / "SKILL.md").read_text(encoding="utf-8")
    framing = " ".join(
        _section_text(sharpen, r"(?:prompt|rewrite|task framing|original task|user choice)")
        .lower()
        .split()
    )
    assert re.search(
        r"\b(?:rewrite|rewriting)\b[^.]{0,100}\bprompt\b|"
        r"\bprompt\b[^.]{0,100}\b(?:rewrite|rewriting)\b",
        framing,
    )
    assert re.search(
        r"\bavailable\b[^.]{0,80}\braw[- ]source\b|"
        r"\braw[- ]source\b[^.]{0,80}\bavailable\b",
        framing,
    )
    assert re.search(r"\bexpert\b[^.]{0,100}\bmethods?\b", framing)
    assert re.search(
        r"\bauthorized\b[^.]{0,60}\bindependent check\b|"
        r"\bindependent check\b[^.]{0,60}\bauthorized\b",
        framing,
    )
    assert re.search(
        r"\b(?:leave|keep|preserve)\b[^.]{0,100}"
        r"\b(?:user(?:'s)? choices?|choices? that belong to (?:the )?user)\b"
        r"[^.]{0,60}\bopen\b",
        framing,
    )
    assert re.search(r"\bcontinue\b[^.]{0,80}\boriginal task\b", framing)
    assert re.search(
        r"\b(?:unless|except when)\b[^.]{0,120}\buser\b[^.]{0,100}"
        r"\b(?:only|just)\b[^.]{0,50}\b(?:prompt )?rewrite\b",
        framing,
    )

    authority = " ".join(
        _section_text(sharpen, r"(?:scope|authority|policy|gate|boundary)")
        .lower()
        .split()
    )
    for boundary in ("policy", "jit", "scope", "compatibility", "authorization", "human"):
        assert boundary in authority
    assert re.search(r"\badds no authority\b|\bdoes not add authority\b", authority)
    assert re.search(
        r"\b(?:do not|don't|never|must not|cannot|does not)\b[^.]{0,180}"
        r"\b(?:change|expand|widen|weaken|loosen|waive)\b[^.]{0,180}"
        r"\b(?:policy|jit|scope|compatibility|authorization|human gates?)\b",
        authority,
    )
    assert re.search(
        r"\b(?:do not|don't|never|must not)\b[^.]{0,180}"
        r"\b(?:create|expand)\b[^.]{0,120}\bcheck\b",
        authority,
    )


def test_sharpen_keeps_outside_verification_within_repository_authority() -> None:
    sharpen = " ".join(
        (SKILLS_ROOT / "sharpen" / "SKILL.md")
        .read_text(encoding="utf-8")
        .lower()
        .split()
    )
    assert "expert" in sharpen
    assert "outside" in sharpen and ("check" in sharpen or "verification" in sharpen)
    assert re.search(
        r"(?:authorized|authorization)[^.]{0,120}(?:outside|external)"
        r"|(?:outside|external)[^.]{0,120}(?:authorized|authorization)",
        sharpen,
    )
    for boundary in ("policy", "jit", "scope", "human", "gate"):
        assert boundary in sharpen
    assert any(
        phrase in sharpen
        for phrase in ("do not weaken", "do not loosen", "must preserve", "preserve policy")
    )


def test_current_pin_parser_has_a_historical_negative_and_current_positive_control() -> None:
    positive = (
        "# pstack compatibility\n\n"
        "This Harness integration adapts a bounded set of skills from `cursor/plugins/pstack` "
        f"version `{EXPECTED_CANONICAL_VERSION}`, commit `{EXPECTED_CANONICAL_COMMIT}`, "
        f"whose `pstack` subtree is `{EXPECTED_CANONICAL_TREE}`. The prior pin is historical."
    )
    match = _compatibility_current_pin(positive)
    assert match is not None
    assert match.groups() == (
        EXPECTED_CANONICAL_VERSION,
        EXPECTED_CANONICAL_COMMIT,
        EXPECTED_CANONICAL_TREE,
    )

    historical_only = (
        "# pstack compatibility\n\n"
        f"Historical pin: version `{EXPECTED_CANONICAL_VERSION}`, "
        f"commit `{EXPECTED_CANONICAL_COMMIT}`, subtree `{EXPECTED_CANONICAL_TREE}`."
    )
    assert _compatibility_current_pin(historical_only) is None
    assert _compatibility_current_pin(
        "# pstack compatibility\n\nThe historical integration is retained below.\n\n"
        + positive.split("\n\n", 1)[1]
    ) is None


def test_current_change_disposition_is_pinned_and_covers_all_66_paths() -> None:
    compatibility = COMPATIBILITY_DOC.read_text(encoding="utf-8")
    path_count = sum(
        len(paths) for paths in EXPECTED_CURRENT_CHANGE_PATHS_BY_DISPOSITION.values()
    )
    assert path_count == 66
    assert len(EXPECTED_CURRENT_PATH_DISPOSITIONS) == 66

    sections = [
        body
        for heading, body in _markdown_sections(compatibility)
        if heading == "Current upstream change disposition"
    ]
    assert len(sections) == 1, "current upstream disposition must be its own section"
    current_section = sections[0]
    first_paragraph = current_section.strip().split("\n\n", 1)[0]
    for pin in (
        PREVIOUS_CANONICAL_VERSION,
        PREVIOUS_CANONICAL_COMMIT,
        PREVIOUS_CANONICAL_TREE,
        EXPECTED_CANONICAL_VERSION,
        EXPECTED_CANONICAL_COMMIT,
        EXPECTED_CANONICAL_TREE,
    ):
        assert pin in first_paragraph, f"current disposition lacks anchored pin {pin}"
    assert re.search(r"\b66\b[^.\n]{0,60}\bchanged paths?\b", first_paragraph, re.IGNORECASE)

    represented, counts = _represented_current_path_dispositions(current_section)
    assert represented == EXPECTED_CURRENT_PATH_DISPOSITIONS
    assert counts == dict.fromkeys(EXPECTED_CURRENT_PATH_DISPOSITIONS, 1)


def test_compatibility_schedule_is_weekly_saturday_at_nine_chicago() -> None:
    compatibility = COMPATIBILITY_DOC.read_text(encoding="utf-8")
    schedule = _section_text(compatibility, r"^Weekly source synchronization$")
    assert re.search(
        r"\bweekly\b.*\bSaturday\b.*\b09:00\b.*\bAmerica/Chicago\b",
        schedule,
        re.IGNORECASE | re.DOTALL,
    )
    assert not re.search(r"\bhourly\b", schedule, re.IGNORECASE)


def test_compatibility_document_notice_and_operational_state_are_reconciled() -> None:
    compatibility = COMPATIBILITY_DOC.read_text(encoding="utf-8")
    notice = NOTICE.read_text(encoding="utf-8")
    state = AGENT_STATE.read_text(encoding="utf-8")

    compatibility_current = _compatibility_current_pin(compatibility)
    notice_current = re.search(
        r"(?m)^The adapted skills under `\.agents/skills/` are based on `cursor/plugins/pstack`,\n"
        r"version `([^`]+)`, commit `([0-9a-f]{40})`, whose\n"
        r"`pstack` subtree is `([0-9a-f]{40})`\.$",
        notice,
    )
    expected_current_pin = (
        EXPECTED_CANONICAL_VERSION,
        EXPECTED_CANONICAL_COMMIT,
        EXPECTED_CANONICAL_TREE,
    )
    assert (
        compatibility_current.groups() if compatibility_current is not None else None,
        notice_current.groups() if notice_current is not None else None,
    ) == (expected_current_pin, expected_current_pin)

    assert "PSTACK_MIT_NOTICE.md" in compatibility
    assert "cursor/plugins/pstack" in compatibility
    assert "MIT License" in notice
    assert "Copyright (c) 2026 Lauren Tan" in notice
    assert "https://github.com/cursor/plugins/tree/main/pstack" in notice
    assert "HARNESS-EFF-03" in state
    assert "PR #107 / merge `4dbecb231457fe4820623677eb9e4b2e0621cd2b`" in state
    assert (
        "https://github.com/kejian-tong/myTradingAlpha/blob/"
        "4dbecb231457fe4820623677eb9e4b2e0621cd2b/docs/productionization/AGENT_STATE.md"
    ) in state
    assert "prior BT01–04, SIG and Harness recovery references/routes" in state

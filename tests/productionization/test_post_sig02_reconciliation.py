from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/productionization/AGENT_STATE.md"
README = ROOT / "docs/productionization/README.md"
TARGET = ROOT / "docs/productionization/02_TARGET_ARCHITECTURE.md"

RECONCILED_MAIN_SHA = "49d5980b640638ed687b6c7771f5f28367072c9a"
RECONCILED_MAIN_TREE = "3b3a70802603d4cd717c62e5c46089319c5ffa0f"
MERGE_SHA = "376c9c044722ee37f3fa36691b576420e3b6253d"
SOURCE_SHA = "de51698180ff6873c7512c70828add3c55728fb9"
RULESET_ID = "23141241"
RULESET_OBSERVED_ON = "2026-09-19"

# These are the immutable merge commits for the completed post-SIG-02 Harness
# remediation sequence.  The state snapshot may group themes, but it must keep
# every PR number and merge SHA recoverable for fresh-master recovery.
HARNESS_MERGES = {
    74: "9177e984c533aa26177fe368190d6e3142342760",
    75: "436545cfe8a2b4785f5ef81eb6476f4a2477658c",
    76: "9a717c85d293256adaa0ccbc6cf8ce84305253a4",
    77: "3e43b2f3c75471573fb969ff07550603c679d0e8",
    78: "502378aa34c98db8892e0b789608f919589cdeb4",
    79: "e138e63823a3c477cbac976ef9a25c1d867c70d6",
    80: "c2eb5d2e9e2defb06ba009d0d0d0f42cea8b2467",
    81: "0b204cc276de8a4d95f43c8da59415244f9944e0",
    82: "ab775c3d3d75e3a8f30c455f35c1d33fd782b389",
    83: "f9b6eb12425ef2e5c8933b75ba327adabd7f76af",
    84: "14cb132a92f9177f0f22492a4708a6ed8880918a",
    85: "93b812e654773aa1ddafe26879fae7fec0a8e4b7",
    86: "49d5980b640638ed687b6c7771f5f28367072c9a",
}


def _state_text() -> str:
    return STATE.read_text(encoding="utf-8")


def test_sig02_operational_state_is_post_merge_and_stopped() -> None:
    state = _state_text()
    assert f"`last_reconciled_main_sha`: `{RECONCILED_MAIN_SHA}`" in state
    assert f"`last_reconciled_main_tree`: `{RECONCILED_MAIN_TREE}`" in state
    assert "`roadmap_status`: `sig_03_green_pending_review`" in state
    assert "`current_pr_id`: `SIG-03` / PR #87" in state
    assert "`current_phase`: Phase 02 — Evidence and Agent Boundary" in state
    assert "`last_completed_roadmap_pr`: `SIG-02` / PR #45 / merge" in state
    assert "`autonomy_mode`: enabled only for authorized SIG-03 implementation" in state
    assert "`merge`: pending independent exact-head review" in state
    assert MERGE_SHA in state
    assert SOURCE_SHA in state
    assert "`active_harness_pr`: none" in state
    assert "PR #86 merged as the verified base" in state
    assert "SIG-03 is the only active roadmap slice" in state
    assert "active PR #87" not in state or "pending" in state
    assert "No SIG-04 or" in state
    assert "portfolio/risk/order/broker/PAPER/live" in state


def test_current_harness_state_is_reconciled_and_not_prospective() -> None:
    state = _state_text()
    harness_marker = "`harness_reconciled_through`: `HARNESS-AUD-21` / PR #86 / merge"
    required = (
        "## Current harness policy",
        f"{harness_marker}\n  `{RECONCILED_MAIN_SHA}`",
    )
    missing = [marker for marker in required if marker not in state]
    assert not missing, f"current Harness reconciliation is missing: {missing}"
    assert "`last_completed_harness_pr`" not in state
    assert "Prospective harness policy" not in state
    assert "`HARNESS-V2-COLLAB-COMPAT` / PR #64 candidate" not in state

    assert not re.search(
        r"HARNESS-AUD-20.{0,160}(?:not merged|no future merge SHA)",
        state,
        flags=re.IGNORECASE | re.DOTALL,
    )


def test_every_merged_post_sig02_harness_pr_remains_recoverable() -> None:
    state = _state_text()
    for pr_number, merge_sha in HARNESS_MERGES.items():
        assert f"PR #{pr_number}" in state, f"missing Harness PR #{pr_number} reference"
        assert merge_sha in state, f"missing merge SHA for Harness PR #{pr_number}"


def test_ruleset_and_post_merge_checks_are_fresh_and_passed() -> None:
    state = _state_text()
    ruleset_lines = [
        line for line in state.splitlines() if RULESET_ID in line
    ]
    assert ruleset_lines, f"ruleset {RULESET_ID} is missing from reconciled state"
    ruleset_line = " ".join(ruleset_lines).lower()
    assert "disabled" in ruleset_line
    assert RULESET_OBSERVED_ON in ruleset_line
    assert "fresh recheck required" not in ruleset_line

    normalized = state.lower()
    assert "main-protection" in normalized
    assert "required contexts" in normalized
    assert "authoritative" in normalized
    assert re.search(r"35473160937[^\n]*(?:pass|passed)", state, flags=re.IGNORECASE)
    assert re.search(r"35473160983[^\n]*(?:pass|passed)", state, flags=re.IGNORECASE)


def test_review_assurance_and_watch_only_boundaries_are_truthful() -> None:
    state = _state_text()
    normalized = state.lower()
    assert "degraded_master_review" not in normalized
    assert "native read-only admission is unavailable" not in normalized
    required_groups = (
        ("permission profile", "disabled", "unrestricted"),
        ("host-origin", "supplemental", "disclosure", "not", "block"),
        ("separate", "review", "exact-head", "worktree"),
        ("hook", "load", "trust", "unknown", "ineffective", "host report"),
        ("runtime receipt", "offline verifier", "config", "do not authenticate", "host", "model", "isolation"),
        ("writer lease", "cooperative", "same-user"),
        ("apps", "memories", "disabled"),
        ("rules", "permission profiles", "otel", "repo plugins", "watch-only"),
        ("external-spec", "docs mcp", "configuration intent", "observed"),
    )
    for group in required_groups:
        missing = [marker for marker in group if marker not in normalized]
        assert not missing, f"state omits host/watch-only limitation markers: {missing}"


def test_shipped_status_docs_mark_sig02_implemented_without_promoting_sig03() -> None:
    readme = README.read_text(encoding="utf-8")
    target = TARGET.read_text(encoding="utf-8")
    assert "SIG-01 and SIG-02 are implemented" in readme
    assert "SIG-03 is implemented in active PR #87" in readme
    assert "SIG-04 and later roadmap slices remain planned" in readme
    assert "SIG-03 is implemented in active PR #87" in target
    assert "does not add portfolio authority, orders, PAPER or live behavior" in target


def test_compact_state_does_not_regress_into_active_sig02_checklist() -> None:
    state = _state_text()
    assert STATE.stat().st_size < 12 * 1024
    assert "not a chronological log" in state.lower()
    assert re.search(r"GitHub(?:/| and )current `main`[^\n]*authoritative", state, flags=re.IGNORECASE)
    stale_markers = (
        "sig_02_candidate_pending_final_exact_head_review",
        "merge: pending",
        "fresh exact-head evidence above remains pending",
    )
    assert not any(marker in state for marker in stale_markers)

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/productionization/AGENT_STATE.md"
README = ROOT / "docs/productionization/README.md"
TARGET = ROOT / "docs/productionization/02_TARGET_ARCHITECTURE.md"

RECONCILED_MAIN_SHA = "4eb8d97b6f2bfc5ef9458263673cfbcf5cb49fb4"
RECONCILED_MAIN_TREE = "26d229efd92a3ba6dee6832d2e7e7c123f6573fb"
MERGE_SHA = "376c9c044722ee37f3fa36691b576420e3b6253d"
SOURCE_SHA = "de51698180ff6873c7512c70828add3c55728fb9"
HARNESS_MERGE_SHA = "4eb8d97b6f2bfc5ef9458263673cfbcf5cb49fb4"
PERMANENT_EXTERNAL_REVIEW_POLICY = (
    "GitHub Copilot review/coding agents must not be requested, mentioned, assigned, or used."
)


def test_sig02_operational_state_is_post_merge_and_stopped() -> None:
    state = STATE.read_text(encoding="utf-8")
    assert f"`last_reconciled_main_sha`: `{RECONCILED_MAIN_SHA}`" in state
    assert f"`last_reconciled_main_tree`: `{RECONCILED_MAIN_TREE}`" in state
    assert "`roadmap_status`: `sig_02_merged_stopped`" in state
    assert "`current_pr_id`: none" in state
    assert "`last_completed_roadmap_pr`: `SIG-02` / PR #45 / merge" in state
    assert "`autonomy_mode`: disabled for roadmap implementation" in state
    assert "`merge`: merged" in state
    assert MERGE_SHA in state
    assert SOURCE_SHA in state
    assert "SIG-03` (informational only; not authorized" in state


def test_current_harness_state_is_reconciled_and_not_prospective() -> None:
    state = STATE.read_text(encoding="utf-8")
    harness_marker = "`harness_reconciled_through`: `HARNESS-AUD-08` / PR #73 / merge"
    required = (
        "## Current harness policy",
        f"{harness_marker}\n  `{HARNESS_MERGE_SHA}`",
        PERMANENT_EXTERNAL_REVIEW_POLICY,
        "`last_reconciled_automatic_review_ruleset_id`: `23141241` (disabled; fresh recheck required)",
    )
    missing = [marker for marker in required if marker not in state]
    assert not missing, f"current Harness reconciliation is missing: {missing}"
    assert "`last_completed_harness_pr`" not in state
    assert "Prospective harness policy" not in state
    assert "`HARNESS-V2-COLLAB-COMPAT` / PR #64 candidate" not in state


def test_shipped_status_docs_mark_sig02_implemented_without_promoting_sig03() -> None:
    readme = README.read_text(encoding="utf-8")
    target = TARGET.read_text(encoding="utf-8")
    assert "SIG-01 and SIG-02 are implemented" in readme
    assert "SIG-03 and later roadmap slices remain planned" in readme
    assert "SIG-01 and SIG-02 are implemented" in target
    assert "SIG-03 and subsequent behavior" in target
    assert "does not add inference, QuantSignal, portfolio authority, orders, PAPER or live behavior" in target


def test_compact_state_does_not_regress_into_active_sig02_checklist() -> None:
    state = STATE.read_text(encoding="utf-8")
    assert STATE.stat().st_size < 12 * 1024
    stale_markers = (
        "sig_02_candidate_pending_final_exact_head_review",
        "merge: pending",
        "fresh exact-head evidence above remains pending",
    )
    assert not any(marker in state for marker in stale_markers)

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/productionization/AGENT_STATE.md"
README = ROOT / "docs/productionization/README.md"
TARGET = ROOT / "docs/productionization/02_TARGET_ARCHITECTURE.md"

RECONCILED_MAIN_SHA = "6ed694fd6c31af3adc5be6d2ee85d85f54aa408f"
RECONCILED_MAIN_TREE = "070179c0e8350e46bad899c0eb3291f9f07fb0cc"
MERGE_SHA = "376c9c044722ee37f3fa36691b576420e3b6253d"
SOURCE_SHA = "de51698180ff6873c7512c70828add3c55728fb9"


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

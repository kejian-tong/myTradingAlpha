from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/productionization/AGENT_STATE.md"
README = ROOT / "docs/productionization/README.md"
TARGET = ROOT / "docs/productionization/02_TARGET_ARCHITECTURE.md"

SIG05_MERGE_SHA = "d709f16b37e40837c4ee687a6bc03ab92ea55218"
HARNESS_PR90_MERGE_SHA = "8f76f341bedf086dd4eb69e4229be33127f5028f"
SIG03_ORIGINAL_BASE_SHA = "49d5980b640638ed687b6c7771f5f28367072c9a"
MERGE_SHA = "376c9c044722ee37f3fa36691b576420e3b6253d"
SOURCE_SHA = "de51698180ff6873c7512c70828add3c55728fb9"
SIG03_MERGE_SHA = "6de1635a90d6c33aee02079dca5d0932e3a32cec"
PH03_DOCS_MERGE_SHA = "2cfc175fe5d07190c740821da5bb20e13877d252"
PH03_DOCS_TREE_SHA = "5ce0ebd88ac1f08e9b4a80238fb87ced0014bb81"
BT01_MERGE_SHA = "a713fbb48324ad9da45e254268b9cfe30b0a634b"
BT01_TREE_SHA = "9fc6e587ca34a297d3183288763f91a933ae054c"
BT01_SOURCE_SHA = "0b3eee8a98f365c3c3b55c35cd584db617c4d3ff"
BT01_REVIEW_COMMENT = "6077723821"
BT01_MATERIAL_CLOSURE_COMMENT = "6077677736"
BT01_GATE_COMMENT = "6077744423"
BT01_WRITER_COMMENT = "6077509103"
BT01_POSTMERGE_COMMENT = "6077864574"
BT01_CI_RUN = "37908220659"
BT01_CODEQL_RUN = "37908220735"
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
    88: "a42ce7a654994d8071824c3aaba4c9e5503a7e9d",
    90: HARNESS_PR90_MERGE_SHA,
    94: "afa7c35b9f8a71170d6a9d14b051d2e83f54fc0f",
}


def _state_text() -> str:
    return STATE.read_text(encoding="utf-8")


def test_operational_state_tracks_authorized_bt02_and_bt01_recovery() -> None:
    state = _state_text()
    normalized_state = " ".join(state.split())
    reconciled_sha = re.search(
        r"`last_reconciled_main_sha`: `([0-9a-f]{40})`", state
    )
    reconciled_tree = re.search(
        r"`last_reconciled_main_tree`: `([0-9a-f]{40})`", state
    )
    assert reconciled_sha is not None
    assert reconciled_tree is not None
    assert reconciled_sha.group(1) == BT01_MERGE_SHA
    assert reconciled_tree.group(1) == BT01_TREE_SHA
    docs_recovery = state.split("## Phase 03 documentation recovery", maxsplit=1)[-1]
    assert PH03_DOCS_MERGE_SHA in docs_recovery
    assert PH03_DOCS_TREE_SHA in docs_recovery

    current_recovery = state.split("## BT-02 current recovery", maxsplit=1)[-1]
    recovery_base = re.search(r"Base/main: `([0-9a-f]{40})`", current_recovery)
    assert recovery_base is not None
    assert recovery_base.group(1) == BT01_MERGE_SHA
    assert "route `luna_sol_xhigh`" in current_recovery
    assert "normal_implementer` / GPT-6 Luna / max" in current_recovery
    assert "reviewer_xhigh` / GPT-6.1 Sol / xhigh" in current_recovery

    bt01_recovery = state.split("## BT-01 completed recovery", maxsplit=1)[-1]
    assert "route `luna_sol_high`" in bt01_recovery
    assert "normal_implementer` / GPT-6 Luna / max" in bt01_recovery
    assert "reviewer_high` / GPT-6.1 Sol / xhigh" in bt01_recovery
    assert (
        "Scope: witnessed immutable session binding, deterministic decision/opportunity events and pure runner only. "
        "No quantity, intent, fill, cost, ledger, action, persistence or metric behavior."
    ) in bt01_recovery

    assert "`roadmap_status`: active BT-02 candidate" in state
    assert re.search(r"`current_pr_id`: BT-02 / PR #\d+", state)
    assert "`current_phase`: 03 — Backtest and Ledger" in state
    assert f"`last_completed_roadmap_pr`: `BT-01` / PR #96 / merge `{BT01_MERGE_SHA}`" in normalized_state
    assert (
        "`autonomy_mode`: human-authorized BT-01 through BT-06 in six independent "
        "dependency-ordered PRs and fresh Master sessions; this session owns BT-02 only"
    ) in state
    assert (
        f"`merge`: PR #96 merged at `{BT01_MERGE_SHA}`; implementation, review, and CI records "
        "remain in its GitHub conversation"
    ) in normalized_state
    assert (
        "`next_dependency`: BT-03 is authorized but blocked until BT-02 merges, main is verified, "
        "and a fresh Master session starts"
    ) in state
    assert (
        f"PR #92's JIT, RED evidence, writer lease lifecycle, review, and CI remain recoverable in "
        f"its GitHub conversation; it merged at `{SIG05_MERGE_SHA}`."
    ) in normalized_state
    assert MERGE_SHA in state
    assert SOURCE_SHA in state
    assert "`active_harness_pr`: none" in state
    assert f"original JIT base was\n`{SIG03_ORIGINAL_BASE_SHA}`" in state
    assert SIG03_MERGE_SHA in state
    assert "PR #86's read-only review-assurance policy remains active" in state
    assert "SIG-05 authorizes no portfolio, risk, order, broker, PAPER/live, or promotion behavior" in state
    assert "SIG-04 validates caller-supplied candidates only; no inference" in state
    assert "SIG-05 adds only in-memory deterministic shadow envelopes" in state
    assert (
        "Scope: shared simulation-only intent/fill contracts, internal deterministic order/fill simulator and stable cost facade"
    ) in current_recovery
    for reference in (
        "https://github.com/kejian-tong/myTradingAlpha/pull/96",
        BT01_SOURCE_SHA,
        BT01_REVIEW_COMMENT,
        BT01_MATERIAL_CLOSURE_COMMENT,
        BT01_GATE_COMMENT,
        BT01_WRITER_COMMENT,
        BT01_POSTMERGE_COMMENT,
        BT01_CI_RUN,
        BT01_CODEQL_RUN,
    ):
        assert reference in state
    assert "Phase 03 gate: insufficient_evidence until all six separately merged slices" in state
    assert "No PAPER/live operation" in state
    assert "explicit human PAPER/live gates remain mandatory and unexercised" in state


def test_current_harness_state_is_reconciled_and_not_prospective() -> None:
    state = _state_text()
    marker_lines = [
        line for line in state.splitlines() if "`harness_reconciled_through`:" in line
    ]
    assert marker_lines, "current Harness reconciliation is missing"
    marker = re.search(
        r"PR #(\d+) / merge `([0-9a-f]{40})`", " ".join(marker_lines)
    )
    assert marker is not None
    latest_verified_harness_pr = max(HARNESS_MERGES)
    assert int(marker.group(1)) == latest_verified_harness_pr
    assert marker.group(2) == HARNESS_MERGES[latest_verified_harness_pr]
    assert (
        f"PR #94 refreshed Master/Sol routes to GPT-6.1 Sol/xhigh and the concurrent "
        f"spawned-thread guardrail to eight; merge `{HARNESS_MERGES[94]}`"
    ) in " ".join(state.split())
    assert "## Current harness policy" in state
    assert "PR #86's read-only review-assurance policy remains active" in state
    assert "`last_completed_harness_pr`" not in state
    assert "`active_harness_pr`: none" in state
    assert "Prospective harness policy" not in state
    assert "`HARNESS-V2-COLLAB-COMPAT` / PR #64 candidate" not in state

    assert not re.search(
        r"HARNESS-AUD-20.{0,160}(?:not merged|no future merge SHA)",
        state,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert HARNESS_PR90_MERGE_SHA in state


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


def test_shipped_status_docs_defer_operational_status_to_state_and_github() -> None:
    readme = README.read_text(encoding="utf-8")
    target = TARGET.read_text(encoding="utf-8")
    assert (
        "Use [AGENT_STATE](AGENT_STATE.md) plus actual GitHub main and PR records "
        "for operational status"
    ) in readme
    assert "current implementation index" in target
    assert "actual GitHub state" in target


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

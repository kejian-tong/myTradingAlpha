from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/productionization/AGENT_STATE.md"
README = ROOT / "docs/productionization/README.md"
TARGET = ROOT / "docs/productionization/02_TARGET_ARCHITECTURE.md"

RECONCILED_MAIN_SHA = "342b31134e2c9302b5ccb4ea91cd7bc08d17cc8f"
RECONCILED_MAIN_TREE = "f6a105adbe0d93917cf1a426a55b18ee5a7791a8"
BT05_BASE_SHA = "3d9e049b2fa2c54b55ac66d1c3000480cd3254bd"
BT05_SOURCE_SHA = "f1e4507f0508e822464878508219eeacf5a8eb45"
BT05_SOURCE_TREE = "eb1fc414d070d9fec1f71bb95f7742be9fbf29ee"
BT05_MERGE_SHA = "b12bef51acd2b1ef6d6db01dede959f1dd67130f"
HARNESS109_BASE_SHA = "8b1138841719c19bb74b4ed1176c78af8bcc469c"
HARNESS109_SOURCE_SHA = "e721ccad33aa912c473fcce8b74d7f48ba56e904"
HARNESS109_TREE = "67d3c9378a0017cecc02acf85649c93d0bc988d6"
HARNESS109_MERGE_SHA = "300605dcbed7aff113d81fd7d709ebbabe01e61c"
COLD_STATE_URL = (
    "https://github.com/kejian-tong/myTradingAlpha/blob/"
    "300605dcbed7aff113d81fd7d709ebbabe01e61c/docs/productionization/AGENT_STATE.md"
)


def _state_text() -> str:
    return STATE.read_text(encoding="utf-8")


def test_operational_state_reconciles_the_current_main_and_completed_bt05() -> None:
    state = _state_text()
    normalized = " ".join(state.split())

    assert "- `schema_version`: 3" in state
    assert f"`last_reconciled_main_sha`: `{RECONCILED_MAIN_SHA}`" in state
    assert f"`last_reconciled_main_tree`: `{RECONCILED_MAIN_TREE}`" in state
    assert "`roadmap_status`: BT-05 merged; BT-06 not started" in state
    assert f"`last_completed_roadmap_pr`: BT-05 / PR #104 / merge `{BT05_MERGE_SHA}`" in normalized
    assert f"Base `{BT05_BASE_SHA}`" in normalized
    assert f"approved source `{BT05_SOURCE_SHA}`" in normalized
    assert f"tree `{BT05_SOURCE_TREE}`" in normalized
    assert "Offline manifested replay/checkpointing only" in state
    assert "Phase 03 gate: insufficient_evidence until all six separately merged slices" in state
    assert "BT-06 informational only; refreshed main, fresh Master and separate authorization required" in state


def test_current_harness_snapshot_tracks_main_and_authorizes_only_pstack() -> None:
    state = _state_text()
    normalized = " ".join(state.split())

    assert (
        f"`harness_reconciled_through`: PR #111 / merge `{RECONCILED_MAIN_SHA}`"
        in state
    )
    assert f"PR109: Base `{HARNESS109_BASE_SHA}`" in normalized
    assert f"approved source `{HARNESS109_SOURCE_SHA}`" in normalized
    assert f"tree `{HARNESS109_TREE}`" in normalized
    assert f"merge `{HARNESS109_MERGE_SHA}`" in normalized
    assert "`current_pr_id`: HARNESS-PSTACK-01536 / PR #112" in state
    assert "`autonomy_mode`: human-authorized bounded pstack synchronization only; later slices require separate authorization" in state
    assert "High `luna_sol_high`: normal_implementer / GPT-6 Luna / max" in state
    assert "separate reviewer_high / GPT-6.1 Sol / xhigh; Master / GPT-6.1 Sol / xhigh" in state
    assert "https://github.com/kejian-tong/myTradingAlpha/pull/112#issuecomment-6546408010" in state
    assert "BT-06/Phase04+ is not authorized" in state
    assert "no future approval/merge is asserted here" in state
    assert "Routing and safety gates are unchanged." in state
    assert "Prospective harness policy" not in state


def test_closed_chronology_resolves_through_the_immutable_cold_snapshot() -> None:
    state = " ".join(_state_text().split())
    assert COLD_STATE_URL in state
    assert "prior BT01–04, SIG and Harness recovery references/routes" in state
    assert "Its superseded status is historical, not current authority" in state
    assert "Load that history only for a specific question" in state


def test_completed_review_gate_completion_and_validation_refs_remain_recoverable() -> None:
    state = " ".join(_state_text().split())
    for reference in (
        "https://github.com/kejian-tong/myTradingAlpha/pull/104",
        "#issuecomment-6418127493",
        "#issuecomment-6418203129",
        "#issuecomment-6418296352",
        "5286 passed, 4 skipped, 69 subtests",
        "Foundation: 4710 passed, 2 skipped",
        "https://github.com/kejian-tong/myTradingAlpha/pull/108",
        "#issuecomment-6489107034",
        "#issuecomment-6489455137",
        "#issuecomment-6489599975",
        "PR-source local and CI full each 5548 passed, 4 skipped, 69 subtests",
        "Foundation aggregation succeeded4s",
        "https://github.com/kejian-tong/myTradingAlpha/pull/109",
        "#issuecomment-6495074222",
        "#issuecomment-6495090548",
        "#issuecomment-6495208854",
    ):
        assert reference in state, f"operational snapshot omits recovery reference {reference!r}"


def test_financial_and_host_assurance_boundaries_remain_truthful() -> None:
    normalized = _state_text().lower()
    assert "degraded_master_review" not in normalized
    assert "native read-only admission is unavailable" not in normalized
    required_groups = (
        ("separate", "review", "exact-head", "worktree"),
        ("host-origin", "supplemental", "disclosure", "not", "block"),
        ("permission profile", "disabled", "unrestricted"),
        ("hook", "load/trust unknown", "host report", "configuration alone is ineffective proof"),
        ("runtime receipt", "offline verifier", "do not authenticate host/model/isolation"),
        ("writer leases are cooperative", "same-user processes"),
        ("sig-04 validates caller-supplied candidates only; no inference",),
        ("sig-05 adds only in-memory deterministic shadow envelopes",),
        ("sig-05 authorizes no portfolio, risk, order, broker, paper/live, or promotion behavior",),
        ("no paper/live operation", "explicit human paper/live gates remain mandatory and unexercised"),
        ("no live broker write before phase 09",),
        ("apps", "memories", "disabled"),
        ("rules", "permission profiles", "otel", "repo plugins", "watch-only"),
        ("external-spec", "docs mcp", "configuration intent", "observed"),
    )
    for group in required_groups:
        missing = [marker for marker in group if marker not in normalized]
        assert not missing, f"state omits assurance or safety boundary: {missing}"


def test_shipped_status_docs_defer_operational_status_to_state_and_github() -> None:
    readme = README.read_text(encoding="utf-8")
    target = TARGET.read_text(encoding="utf-8")
    assert (
        "Use [AGENT_STATE](AGENT_STATE.md) plus actual GitHub main and PR records "
        "for operational status"
    ) in readme
    assert "current implementation index" in target
    assert "actual GitHub state" in target


def test_compact_state_has_no_stale_bt05_active_or_pending_checklist() -> None:
    state = _state_text()
    normalized = state.lower()
    assert STATE.stat().st_size <= 6_144
    assert "not a chronological log" in normalized
    assert "github/current `main` is authoritative" in normalized
    stale_markers = (
        "active bt-05 candidate",
        "current_pr_id`: bt-05 / pr #104",
        "fresh exact-head evidence above remains pending",
        "merge: pending",
        "sig_02_candidate_pending_final_exact_head_review",
    )
    assert not any(marker in normalized for marker in stale_markers)

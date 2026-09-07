from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_root_agents_does_not_imply_dynamic_nested_auto_loading() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "project root to the current working directory (CWD)" in text
    assert "stops there" in text
    assert "opened or edited" in text
    assert "productionization-preflight" in text


def test_preflight_explicitly_reads_scoped_instructions_outside_cwd_chain() -> None:
    text = (ROOT / ".agents/skills/productionization-preflight/SKILL.md").read_text(encoding="utf-8")
    assert "project-root-to-current-working-directory chain" in text
    assert "stops at the CWD" in text
    assert "explicitly read every deeper `AGENTS.md`" in text
    assert "does not by itself prove" in text

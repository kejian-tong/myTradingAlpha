"""RED contract tests for stable, non-secret FND-03 identifiers."""

from __future__ import annotations

import re


def test_generated_run_and_correlation_ids_use_stable_non_secret_formats() -> None:
    from mytradingalpha.ops.ids import new_correlation_id, new_run_id

    run_id = new_run_id()
    correlation_id = new_correlation_id()

    assert re.fullmatch(r"run-[0-9a-f]{32}", run_id)
    assert re.fullmatch(r"corr-[0-9a-f]{32}", correlation_id)
    assert run_id != correlation_id

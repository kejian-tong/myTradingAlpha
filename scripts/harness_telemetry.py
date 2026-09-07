"""Record and summarize local Codex harness telemetry outside the Git worktree.

Telemetry is stored under the repository Git common directory so recording cannot
change the candidate source tree or invalidate exact-head review evidence.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

_ALLOWED_EVENTS = {
    "agent_spawn",
    "agent_stop",
    "phase_complete",
    "review_result",
    "head_invalidated",
    "ci_rerun",
    "context_compaction",
}
_ALLOWED_PHASES = {"preflight", "jit", "red", "green", "refactor", "review", "repair", "merge_gate"}


def telemetry_path(repo: Path) -> Path:
    repo = repo.resolve()
    common = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"], text=True
    ).strip()
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (repo / common_path).resolve()
    return common_path / "codex-harness" / "telemetry.jsonl"


def _validate(record: dict) -> dict:
    if record.get("event") not in _ALLOWED_EVENTS:
        raise ValueError("unsupported telemetry event")
    if "phase" in record and record["phase"] not in _ALLOWED_PHASES:
        raise ValueError("unsupported telemetry phase")
    for key in ("active_agents", "review_round", "blocking_findings", "duration_ms", "input_tokens", "cached_input_tokens", "output_tokens"):
        if key in record and (type(record[key]) is not int or record[key] < 0):
            raise ValueError(f"{key} must be a non-negative integer")
    for key in ("pr_id", "role", "model", "effort", "head_sha"):
        if key in record and (type(record[key]) is not str or not record[key].strip()):
            raise ValueError(f"{key} must be a non-empty string")
    allowed = {
        "event", "phase", "pr_id", "role", "model", "effort", "head_sha",
        "active_agents", "review_round", "blocking_findings", "duration_ms",
        "input_tokens", "cached_input_tokens", "output_tokens", "observed_at_ms",
    }
    unknown = set(record) - allowed
    if unknown:
        raise ValueError(f"unknown telemetry fields: {sorted(unknown)}")
    return record


def record(repo: Path, payload: dict) -> Path:
    payload = dict(payload)
    payload.setdefault("observed_at_ms", time.time_ns() // 1_000_000)
    _validate(payload)
    path = telemetry_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def load(repo: Path) -> list[dict]:
    path = telemetry_path(repo)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(_validate(json.loads(line)))
    return rows


def summarize(repo: Path) -> dict:
    rows = load(repo)
    peak_agents = max((row.get("active_agents", 0) for row in rows), default=0)
    durations = [row["duration_ms"] for row in rows if "duration_ms" in row]
    token_rows = [row for row in rows if any(k in row for k in ("input_tokens", "cached_input_tokens", "output_tokens"))]
    return {
        "records": len(rows),
        "events": dict(Counter(row["event"] for row in rows)),
        "roles": dict(Counter(row["role"] for row in rows if "role" in row)),
        "peak_active_agents": peak_agents,
        "duration_ms_total": sum(durations),
        "review_round_max": max((row.get("review_round", 0) for row in rows), default=0),
        "blocking_findings_total": sum(row.get("blocking_findings", 0) for row in rows),
        "token_observation_records": len(token_rows),
        "input_tokens_observed": sum(row.get("input_tokens", 0) for row in token_rows),
        "cached_input_tokens_observed": sum(row.get("cached_input_tokens", 0) for row in token_rows),
        "output_tokens_observed": sum(row.get("output_tokens", 0) for row in token_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "summary", "path"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", help="JSON object for the record action")
    args = parser.parse_args()
    if args.action == "path":
        print(telemetry_path(args.repo))
    elif args.action == "summary":
        print(json.dumps(summarize(args.repo), indent=2, sort_keys=True))
    else:
        if args.json is None:
            parser.error("--json is required for record")
        payload = json.loads(args.json)
        if type(payload) is not dict:
            parser.error("--json must decode to an object")
        print(record(args.repo, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

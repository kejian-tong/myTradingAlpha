"""Lightweight repo-scoped Codex hook checks.

These hooks are supplemental runtime feedback. CI, the offline harness validator,
independent review, and the exact-head merge gate remain authoritative.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from check_agent_harness import configuration_errors

ROOT = Path(__file__).resolve().parents[1]


def _report_configuration_errors() -> bool:
    errors = configuration_errors(ROOT)
    for error in errors:
        print(f"codex hook: {error}", file=sys.stderr)
    return not errors


def _git_diff_check() -> bool:
    result = subprocess.run(
        ["git", "diff", "--check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.stdout:
        stream = sys.stdout if result.returncode == 0 else sys.stderr
        print(result.stdout, end="", file=stream)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", choices=("session-start", "stop"))
    args = parser.parse_args()

    ok = _report_configuration_errors()
    if args.event == "stop":
        ok = _git_diff_check() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

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

_ADVISORY_PREFIX = "codex hook advisory: "
_ADVISORY_MAX_CHARS = 1_024
_ADVISORY_TRUNCATION = " …[truncated]"
_GIT_DIFF_TIMEOUT_SECONDS = 5


def _configuration_diagnostics() -> list[str]:
    errors = configuration_errors(ROOT)
    if not isinstance(errors, list):
        raise TypeError("configuration validator returned a non-list result")
    return [str(error) for error in errors]


def _report_configuration_errors() -> bool:
    try:
        errors = _configuration_diagnostics()
    except Exception as exc:
        print(f"codex hook: configuration validation failed: {exc}", file=sys.stderr)
        return False
    for error in errors:
        print(f"codex hook: {error}", file=sys.stderr)
    return not errors


def _git_diff_diagnostic() -> str | None:
    result = subprocess.run(
        ["git", "diff", "--check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=_GIT_DIFF_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        return None
    output = result.stdout or ""
    if not isinstance(output, str):
        raise TypeError("git diff --check returned non-text diagnostics")
    return output or f"git diff --check exited with status {result.returncode}"


def _exception_diagnostic(label: str, exc: Exception) -> str:
    try:
        detail = str(exc).strip()
    except Exception:
        detail = "diagnostic unavailable"
    if detail:
        return f"{label}: {type(exc).__name__}: {detail}"
    return f"{label}: {type(exc).__name__}"


def _normalize_diagnostic(diagnostic: object) -> str:
    try:
        text = " ".join(str(diagnostic).split())
    except Exception:
        text = "diagnostic unavailable"
    return text


def _emit_advisories(diagnostics: list[object]) -> None:
    lines: list[str] = []
    for diagnostic in diagnostics:
        text = _normalize_diagnostic(diagnostic)
        if not text:
            continue
        lines.append(f"{_ADVISORY_PREFIX}{text}")

    if not lines:
        return

    output = "\n".join(lines)
    if len(output) > _ADVISORY_MAX_CHARS:
        limit = max(0, _ADVISORY_MAX_CHARS - len(_ADVISORY_TRUNCATION))
        output = output[:limit] + _ADVISORY_TRUNCATION
    print(output, file=sys.stderr)


def _run_stop_diagnostics() -> None:
    diagnostics: list[object] = []

    try:
        diagnostics.extend(_configuration_diagnostics())
    except Exception as exc:
        diagnostics.append(_exception_diagnostic("configuration diagnostics unavailable", exc))

    try:
        diff_diagnostic = _git_diff_diagnostic()
    except Exception as exc:
        diagnostics.append(_exception_diagnostic("git diff --check unavailable", exc))
    else:
        if diff_diagnostic:
            diagnostics.append(diff_diagnostic)

    _emit_advisories(diagnostics)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", choices=("session-start", "stop"))
    args = parser.parse_args()

    if args.event == "stop":
        _run_stop_diagnostics()
        return 0
    return 0 if _report_configuration_errors() else 1


if __name__ == "__main__":
    raise SystemExit(main())

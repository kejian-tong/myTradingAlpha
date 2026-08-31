"""Validate tracked Markdown links, fences, and productionization records."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import unquote, urlsplit

PHASES = (
    "00-foundation",
    "01-point-in-time-data",
    "02-evidence-agent-boundary",
    "03-backtest-ledger",
    "04-portfolio-risk",
    "05-execution-cost-liquidity",
    "06-experiment-alpha-validation",
    "07-broker-oms-paper-reconciliation",
    "08-forward-paper-gate",
    "09-live-pilot",
)
ROADMAP_ID_PATTERN = re.compile(r"\b(?:FND|PIT|SIG|BT|RSK|EXC|EXP|OMS|FWD|LIVE)-\d{2}\b")
ROADMAP_DEFINITION_PATTERN = re.compile(
    r"\*\*(?P<id>(?:FND|PIT|SIG|BT|RSK|EXC|EXP|OMS|FWD|LIVE)-\d{2})\b[^*\n]*\*\*"
)
ROADMAP_IDS = frozenset(
    f"{prefix}-{number:02d}"
    for prefix, count in (
        ("FND", 4),
        ("PIT", 6),
        ("SIG", 5),
        ("BT", 6),
        ("RSK", 5),
        ("EXC", 4),
        ("EXP", 4),
        ("OMS", 6),
        ("FWD", 3),
        ("LIVE", 4),
    )
    for number in range(1, count + 1)
)
FENCE_PATTERN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
LINK_PATTERN = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?:<([^>\n]*)>|([^\s)]+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _tracked_markdown(root: Path) -> tuple[list[Path], list[str]]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "*.md", "*.markdown"],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        return [], [f"could not enumerate tracked Markdown: {error}"]
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        message = "could not enumerate tracked Markdown"
        if detail:
            message += f": {detail}"
        return [], [message]

    paths = [root / entry for entry in result.stdout.decode().split("\0") if entry]
    return sorted(paths, key=lambda path: path.as_posix()), []


def _is_ignored_target(target: str) -> bool:
    target = target.strip()
    if not target or target.startswith("#"):
        return True
    if target.startswith("<") and target.endswith(">"):
        return True
    parsed = urlsplit(target)
    return bool(parsed.scheme or parsed.netloc)


def _link_diagnostics(root: Path, source: Path, line_number: int, target: str) -> Iterable[str]:
    target = target.strip()
    if source.name == "PR_IMPLEMENTATION_SPEC_TEMPLATE.md" and target in {
        "path",
        "url",
        "PR-ID",
        "symbols",
        "step",
        "item",
        "reason",
    }:
        return ()
    if _is_ignored_target(target):
        return ()

    path_part = unquote(urlsplit(target).path)
    if not path_part or path_part.startswith("#"):
        return ()

    source_label = _relative_path(root, source)
    if path_part.startswith("/"):
        return (
            f"{source_label}:{line_number}: local link escapes repository: {target}",
        )

    candidate = (source.parent / path_part).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return (
            f"{source_label}:{line_number}: local link escapes repository: {target}",
        )
    if not candidate.exists():
        return (
            f"{source_label}:{line_number}: local link target does not exist: {target}",
        )
    return ()


def _markdown_file_diagnostics(root: Path, path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        return [f"{_relative_path(root, path)}: could not read Markdown: {error}"]

    diagnostics: list[str] = []
    open_fence: tuple[str, int, int] | None = None
    for line_number, line in enumerate(lines, start=1):
        fence_match = FENCE_PATTERN.match(line)
        if open_fence is not None:
            if fence_match is None:
                continue
            marker, info = fence_match.groups()
            opening_marker, opening_length, opening_line = open_fence
            if marker[0] != opening_marker:
                diagnostics.append(
                    f"{_relative_path(root, path)}:{line_number}: mismatched fence "
                    f"{marker[0]} for {opening_marker} opened at line {opening_line}"
                )
                continue
            if len(marker) < opening_length or info.strip():
                diagnostics.append(
                    f"{_relative_path(root, path)}:{line_number}: mismatched fence "
                    f"for {opening_marker} opened at line {opening_line}"
                )
                continue
            open_fence = None
            continue

        if fence_match is not None:
            marker, _ = fence_match.groups()
            open_fence = (marker[0], len(marker), line_number)
            continue

        for match in LINK_PATTERN.finditer(line):
            target = match.group(1) if match.group(1) is not None else match.group(2)
            diagnostics.extend(_link_diagnostics(root, path, line_number, target))

    if open_fence is not None:
        marker, _, opening_line = open_fence
        diagnostics.append(
            f"{_relative_path(root, path)}:{opening_line}: unbalanced {marker} fence"
        )
    return diagnostics


def _record_diagnostics(root: Path) -> list[str]:
    diagnostics: list[str] = []

    license_path = root / "LICENSE"
    if not license_path.is_file():
        diagnostics.append("LICENSE is missing")
    else:
        license_text = license_path.read_text(encoding="utf-8")
        if "Apache License" not in license_text or "Version 2.0" not in license_text:
            diagnostics.append("LICENSE is not the Apache License 2.0 record")

    for filename, label in (("UPSTREAM.md", "UPSTREAM.md"), ("CHANGES_FROM_UPSTREAM.md", "CHANGES_FROM_UPSTREAM.md")):
        path = root / filename
        if not path.is_file():
            diagnostics.append(f"{label} is missing")
        else:
            try:
                if not path.read_text(encoding="utf-8").strip():
                    diagnostics.append(f"{label} is empty")
            except (OSError, UnicodeError) as error:
                diagnostics.append(f"{label} could not be read: {error}")

    phase_root = root / "docs" / "productionization" / "phases"
    for phase in PHASES:
        for filename in ("DESIGN.md", "IMPLEMENTATION.md"):
            path = phase_root / phase / filename
            if not path.is_file():
                diagnostics.append(f"missing phase document: {_relative_path(root, path)}")

    roadmap_path = root / "docs" / "productionization" / "07_PR_IMPLEMENTATION_PLAN.md"
    if not roadmap_path.is_file():
        diagnostics.append("47-slice roadmap is missing")
    else:
        roadmap_text = roadmap_path.read_text(encoding="utf-8")
        roadmap_ids = set(ROADMAP_ID_PATTERN.findall(roadmap_text))
        roadmap_definitions = ROADMAP_DEFINITION_PATTERN.findall(roadmap_text)
        definition_counts = Counter(roadmap_definitions)
        duplicate_definitions = sorted(
            roadmap_id for roadmap_id, count in definition_counts.items() if count > 1
        )
        unexpected_definitions = sorted(set(roadmap_definitions) - ROADMAP_IDS)
        missing_definitions = sorted(ROADMAP_IDS - set(roadmap_definitions))
        if (
            len(roadmap_definitions) != len(ROADMAP_IDS)
            or len(definition_counts) != len(ROADMAP_IDS)
            or duplicate_definitions
            or unexpected_definitions
            or missing_definitions
        ):
            details = [f"definition count: {len(roadmap_definitions)}"]
            if duplicate_definitions:
                details.append(f"duplicates: {', '.join(duplicate_definitions)}")
            if missing_definitions:
                details.append(f"missing definitions: {', '.join(missing_definitions)}")
            if unexpected_definitions:
                details.append(f"unexpected definitions: {', '.join(unexpected_definitions)}")
            diagnostics.append(
                "roadmap must contain exactly 47 unique bold slice definitions"
                f" ({'; '.join(details)})"
            )
        if roadmap_ids != ROADMAP_IDS:
            missing = ", ".join(sorted(ROADMAP_IDS - roadmap_ids))
            unexpected = ", ".join(sorted(roadmap_ids - ROADMAP_IDS))
            details = []
            if missing:
                details.append(f"missing: {missing}")
            if unexpected:
                details.append(f"unexpected: {unexpected}")
            diagnostics.append(
                "roadmap must contain exactly 47 approved unique IDs"
                + (f" ({'; '.join(details)})" if details else "")
            )

    return diagnostics


def check_markdown_contracts(root: Path | str) -> list[str]:
    """Return deterministic diagnostics for tracked Markdown contracts."""

    root_path = Path(root).resolve()
    diagnostics = _record_diagnostics(root_path)
    paths, tracking_diagnostics = _tracked_markdown(root_path)
    diagnostics.extend(tracking_diagnostics)
    for path in paths:
        diagnostics.extend(_markdown_file_diagnostics(root_path, path))
    return sorted(set(diagnostics))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="repository root to inspect (default: current directory)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"Markdown contract check root is not a directory: {root}", file=sys.stderr)
        return 2

    diagnostics = check_markdown_contracts(root)
    if diagnostics:
        for diagnostic in diagnostics:
            print(diagnostic, file=sys.stderr)
        print(f"Markdown contract check failed: {len(diagnostics)} diagnostic(s)", file=sys.stderr)
        return 1

    print("Markdown contract check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate the reviewed uv lock against project metadata without changing it."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

EXPECTED_UV_VERSION = "0.12.7"
EXPECTED_PYTHON_REQUIREMENT = ">=3.10"
PROJECT_SECTION = "project"
LOCK_FILENAME = "uv.lock"


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())


def _section(text: str, section_name: str) -> str | None:
    lines = text.splitlines()
    header = f"[{section_name}]"
    start = next((index for index, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        return None
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if re.match(r"^\s*\[[^\[][^\]]*\]\s*$", lines[index])
        ),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end])


def _scalar(section: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*\"([^\"]*)\"\s*$", section)
    return match.group(1) if match else None


def _list_values(section: str, key: str) -> list[str] | None:
    match = re.search(rf"(?ms)^\s*{re.escape(key)}\s*=\s*\[(.*?)^\s*\]", section)
    if match is None:
        return None
    return re.findall(r'^\s*"([^"\n]+)"\s*,?\s*$', match.group(1), re.MULTILINE)


def _dependency_names(project_section: str) -> set[str] | None:
    requirements = _list_values(project_section, "dependencies")
    if requirements is None:
        return None
    return {
        _normalize_name(re.split(r"[<>=!~;\[\s]", requirement, maxsplit=1)[0])
        for requirement in requirements
    }


def _lock_package_blocks(lock_text: str) -> Iterable[str]:
    matches = list(re.finditer(r"(?m)^\[\[package\]\]\s*$", lock_text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(lock_text)
        yield lock_text[match.end() : end]


def _lock_package_names(lock_text: str) -> set[str]:
    names: set[str] = set()
    for block in _lock_package_blocks(lock_text):
        name = _scalar(block, "name")
        if name is not None:
            names.add(_normalize_name(name))
    return names


def _root_lock_block(lock_text: str, project_name: str) -> str | None:
    expected = _normalize_name(project_name)
    for block in _lock_package_blocks(lock_text):
        if _normalize_name(_scalar(block, "name") or "") == expected:
            return block
    return None


def _tracked(path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(path.parent), "ls-files", "--error-unmatch", path.name],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == path.name


def _static_diagnostics(root: Path) -> list[str]:
    diagnostics: list[str] = []
    project_path = root / "pyproject.toml"
    lock_path = root / LOCK_FILENAME

    if not project_path.is_file():
        diagnostics.append("pyproject.toml is missing")
        return diagnostics
    if not lock_path.is_file():
        diagnostics.append("uv.lock is missing")
        return diagnostics
    if not _tracked(lock_path):
        diagnostics.append("uv.lock is not tracked")

    project_text = project_path.read_text(encoding="utf-8")
    lock_text = lock_path.read_text(encoding="utf-8")
    project_section = _section(project_text, PROJECT_SECTION)
    if project_section is None:
        diagnostics.append("pyproject.toml is missing [project]")
        return diagnostics

    project_name = _scalar(project_section, "name")
    project_python = _scalar(project_section, "requires-python")
    project_dependencies = _dependency_names(project_section)
    if project_name is None:
        diagnostics.append("[project].name is missing")
    if project_python is None:
        diagnostics.append("[project].requires-python is missing")
    elif project_python != EXPECTED_PYTHON_REQUIREMENT:
        diagnostics.append(
            f"project requires-python is {project_python!r}, expected {EXPECTED_PYTHON_REQUIREMENT!r}"
        )
    if project_dependencies is None:
        diagnostics.append("[project].dependencies is missing or malformed")

    uv_section = _section(project_text, "tool.uv")
    uv_version = _scalar(uv_section or "", "required-version")
    if uv_version != f"=={EXPECTED_UV_VERSION}":
        diagnostics.append(
            f"[tool.uv].required-version is {uv_version!r}, expected '=={EXPECTED_UV_VERSION}'"
        )

    lock_version = re.search(r"(?m)^version\s*=\s*(\d+)\s*$", lock_text)
    lock_revision = re.search(r"(?m)^revision\s*=\s*(\d+)\s*$", lock_text)
    lock_python = re.search(r"(?m)^requires-python\s*=\s*\"([^\"]+)\"\s*$", lock_text)
    if lock_version is None:
        diagnostics.append("uv.lock is missing a format version")
    if lock_revision is None:
        diagnostics.append("uv.lock is missing a revision")
    if lock_python is None:
        diagnostics.append("uv.lock is missing requires-python")
    elif project_python is not None and lock_python.group(1) != project_python:
        diagnostics.append(
            "uv.lock requires-python does not match pyproject.toml: "
            f"{lock_python.group(1)!r} != {project_python!r}"
        )

    package_names = _lock_package_names(lock_text)
    if project_name is not None:
        root_block = _root_lock_block(lock_text, project_name)
        if root_block is None:
            diagnostics.append(f"uv.lock is missing root package {_normalize_name(project_name)!r}")
        elif not re.search(r"(?m)^source\s*=\s*\{\s*editable\s*=\s*\"\.\"\s*\}\s*$", root_block):
            diagnostics.append("uv.lock root package is not an editable project source")
    if project_dependencies is not None:
        missing = sorted(project_dependencies - package_names)
        diagnostics.extend(f"uv.lock is missing direct dependency {name!r}" for name in missing)

    return sorted(set(diagnostics))


def _run_uv_lock_check(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["uv", "lock", "--check"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return f"could not execute uv lock --check: {error}"
    if result.returncode == 0:
        return None
    output = (result.stdout + result.stderr).strip()
    return f"uv lock --check failed (exit {result.returncode}): {output}".rstrip()


def check_lock_consistency(root: Path | str) -> list[str]:
    """Return deterministic diagnostics for the project lock contract."""

    root_path = Path(root).resolve()
    diagnostics = _static_diagnostics(root_path)
    if not diagnostics:
        uv_diagnostic = _run_uv_lock_check(root_path)
        if uv_diagnostic is not None:
            diagnostics.append(uv_diagnostic)
    return sorted(set(diagnostics))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="project root to inspect (default: current directory)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"lock consistency check root is not a directory: {root}", file=sys.stderr)
        return 2

    diagnostics = check_lock_consistency(root)
    if diagnostics:
        for diagnostic in diagnostics:
            print(diagnostic, file=sys.stderr)
        print(f"lock consistency check failed: {len(diagnostics)} diagnostic(s)", file=sys.stderr)
        return 1

    print("lock consistency check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

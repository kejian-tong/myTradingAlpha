"""Statically enforce the one-way production/research package boundary."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

_PRODUCTION_ROOT = "mytradingalpha"
_RESEARCH_ROOT = "tradingagents"


@dataclass(frozen=True)
class DependencyViolation:
    """One forbidden absolute import and its source location."""

    path: Path
    line: int
    column: int
    imported_module: str
    message: str

    def format(self, root: Path | None = None) -> str:
        """Return a stable, actionable diagnostic suitable for CLI output."""

        display_path = self.path
        if root is not None:
            with suppress(ValueError):
                display_path = self.path.relative_to(root)
        return f"{display_path}:{self.line}:{self.column}: {self.message}"


def _is_module_or_submodule(module: str, root: str) -> bool:
    return module == root or module.startswith(f"{root}.")


def _is_research_source(path: Path, root: Path) -> bool:
    """Whether *path* belongs to the sole production reverse-import exception."""

    try:
        relative = path.relative_to(root)
    except ValueError:
        return False

    parts = relative.parts
    if not parts or parts[0] != _PRODUCTION_ROOT or len(parts) < 2:
        return False
    return parts[1] in {"research", "research.py"}


def _source_kind(path: Path, root: Path) -> str | None:
    """Return the package ownership kind for a file under the scan root."""

    try:
        relative = path.relative_to(root)
    except ValueError:
        return None

    if not relative.parts:
        return None
    if relative.parts[0] == _RESEARCH_ROOT:
        return _RESEARCH_ROOT
    if relative.parts[0] == _PRODUCTION_ROOT:
        return "research-adapter" if _is_research_source(path, root) else _PRODUCTION_ROOT
    return None


def _python_files(root: Path) -> Iterable[Path]:
    """Yield Python files in the two package roots in deterministic order."""

    package_paths = [root / _PRODUCTION_ROOT, root / _RESEARCH_ROOT]
    files = {
        path
        for package_path in package_paths
        if package_path.is_dir()
        for path in package_path.rglob("*.py")
        if path.is_file()
    }
    yield from sorted(files, key=lambda path: path.as_posix())


def _imported_modules(tree: ast.AST) -> Iterable[tuple[ast.AST, str]]:
    """Yield absolute module names referenced by import statements in *tree*."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node, node.module


def _violation_for(
    path: Path, root: Path, node: ast.AST, imported_module: str
) -> DependencyViolation | None:
    source_kind = _source_kind(path, root)
    if source_kind is None:
        return None

    if source_kind == _RESEARCH_ROOT and _is_module_or_submodule(imported_module, _PRODUCTION_ROOT):
        message = (
            f"forbidden import '{imported_module}' from upstream '{_RESEARCH_ROOT}' package; "
            f"'{_RESEARCH_ROOT}' must not import '{_PRODUCTION_ROOT}'"
        )
    elif source_kind == _PRODUCTION_ROOT and _is_module_or_submodule(
        imported_module, _RESEARCH_ROOT
    ):
        message = (
            f"forbidden import '{imported_module}' from production package; only "
            f"'{_PRODUCTION_ROOT}.research' may import '{_RESEARCH_ROOT}'"
        )
    else:
        return None

    return DependencyViolation(
        path=path,
        line=getattr(node, "lineno", 0),
        column=getattr(node, "col_offset", 0) + 1,
        imported_module=imported_module,
        message=message,
    )


def find_violations(root: Path | str) -> list[DependencyViolation]:
    """Find forbidden imports under *root* without importing application modules."""

    root = Path(root).resolve()
    violations: list[DependencyViolation] = []
    for path in _python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as error:
            violations.append(
                DependencyViolation(
                    path=path,
                    line=getattr(error, "lineno", 0) or 0,
                    column=(getattr(error, "offset", 0) or 0),
                    imported_module="<parse error>",
                    message=f"could not parse Python source: {error}",
                )
            )
            continue

        for node, imported_module in _imported_modules(tree):
            violation = _violation_for(path, root, node, imported_module)
            if violation is not None:
                violations.append(violation)

    return violations


def check_dependency_direction(root: Path | str) -> list[DependencyViolation]:
    """Compatibility-named entry point for callers that want a checker function."""

    return find_violations(root)


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
        print(f"dependency direction check root is not a directory: {root}", file=sys.stderr)
        return 2

    violations = find_violations(root)
    if violations:
        for violation in violations:
            print(violation.format(root), file=sys.stderr)
        print(f"dependency direction check failed: {len(violations)} violation(s)", file=sys.stderr)
        return 1

    print("dependency direction check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

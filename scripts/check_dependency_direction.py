"""Statically enforce the one-way production/research package boundary."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from importlib.util import resolve_name
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


class _DynamicImports(ast.NodeVisitor):
    """Bounded lexical analysis of known loader forms, not arbitrary Python execution.

    Literal names, import aliases, simple alias assignments and function-local
    shadowing are covered. A recognized loader with a computed target is a
    manual-review diagnostic, never an inferred safe dependency. Reflective code,
    runtime monkeypatching and arbitrary callable dataflow still require review.
    """

    def __init__(self) -> None:
        self.bindings: dict[str, str | None] = {"__import__": "__import__"}
        self.imports: list[tuple[ast.AST, str | None]] = []

    def _binding(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id)
        if isinstance(node, ast.Attribute):
            owner = self._binding(node.value)
            if (owner, node.attr) == ("importlib", "import_module"):
                return "import_module"
            if (owner, node.attr) == ("builtins", "__import__"):
                return "__import__"
        return None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            module = alias.name if alias.asname else alias.name.split(".")[0]
            self.bindings[name] = module if module in {"importlib", "builtins"} else None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            loader = (node.module, alias.name)
            allowed = node.level == 0 and loader in {
                ("importlib", "import_module"), ("builtins", "__import__")
            }
            self.bindings[alias.asname or alias.name] = alias.name if allowed else None

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        binding = self._binding(node.value)
        for target in node.targets:
            for child in ast.walk(target):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    self.bindings[child.id] = binding if isinstance(target, ast.Name) else None

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        if isinstance(node.target, ast.Name):
            self.bindings[node.target.id] = self._binding(node.value) if node.value else None

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        self.bindings[node.name] = None
        outer = self.bindings.copy()
        # Parameters shadow globals even when their names resemble an import API.
        arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        for argument in (*arguments, node.args.vararg, node.args.kwarg):
            if argument is not None:
                self.bindings[argument.arg] = None
        for statement in node.body:
            self.visit(statement)
        self.bindings = outer

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bindings[node.name] = None
        outer = self.bindings.copy()
        self.generic_visit(node)
        self.bindings = outer

    @staticmethod
    def _argument(node: ast.Call, index: int, keyword: str) -> ast.AST | None:
        if len(node.args) > index:
            return node.args[index]
        return next((item.value for item in node.keywords if item.arg == keyword), None)

    def visit_Call(self, node: ast.Call) -> None:
        loader = self._binding(node.func)
        if loader in {"import_module", "__import__"}:
            target = self._argument(node, 0, "name")
            name = target.value if isinstance(target, ast.Constant) and isinstance(target.value, str) else None
            if loader == "import_module" and name and name.startswith("."):
                package = self._argument(node, 1, "package")
                if isinstance(package, ast.Constant) and isinstance(package.value, str):
                    try:
                        name = resolve_name(name, package.value)
                    except (ImportError, ValueError):
                        name = None
                else:
                    name = None
            if loader == "__import__":
                level = self._argument(node, 4, "level")
                if level is not None and not (isinstance(level, ast.Constant) and level.value == 0):
                    name = None
            self.imports.append((node, name))
        self.generic_visit(node)


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

        dynamic = _DynamicImports()
        dynamic.visit(tree)
        for node, imported_module in dynamic.imports:
            if imported_module is None:
                violations.append(DependencyViolation(
                    path=path, line=node.lineno, column=node.col_offset + 1,
                    imported_module="<dynamic>",
                    message="unresolved dynamic import requires manual review; use a literal import",
                ))
            else:
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

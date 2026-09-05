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


def _local_names(body: Iterable[ast.AST]) -> set[str]:
    """Collect function locals without descending into nested lexical scopes."""
    names: set[str] = set()
    external: set[str] = set()
    pending = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            continue
        if isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            continue
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            external.update(node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        pending.extend(ast.iter_child_nodes(node))
    return names - external


class _DynamicImports(ast.NodeVisitor):
    """Bounded lexical analysis, never evaluation of candidate source.

    Recognized literal loaders, simple aliases, function/lambda/comprehension
    locals and class-versus-closure lookup are covered. If branches retain all
    possible loader bindings conservatively; this is not reachability proof.
    Arbitrary reflective dispatch, mutations of module attributes, interprocedural
    effects and unrestricted Python control flow still require manual review.
    """

    _OTHER = frozenset({None})

    def __init__(self) -> None:
        self.bindings: dict[str, frozenset[str | None]] = {
            "__import__": frozenset({"__import__"})
        }
        self.class_outer: dict[str, frozenset[str | None]] | None = None
        self.imports: list[tuple[ast.AST, str | None]] = []

    def _binding(self, node: ast.AST) -> frozenset[str | None]:
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id, self._OTHER)
        if isinstance(node, ast.Attribute):
            attributes = {("importlib", "import_module"): "import_module",
                          ("builtins", "__import__"): "__import__"}
            return frozenset(attributes.get((owner, node.attr)) for owner in self._binding(node.value))
        return self._OTHER

    def _closure(self) -> dict[str, frozenset[str | None]]:
        # Python functions/comprehensions do not close over class namespaces.
        return (self.class_outer if self.class_outer is not None else self.bindings).copy()

    def _shadow(self, target: ast.AST) -> None:
        for child in ast.walk(target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                self.bindings[child.id] = self._OTHER

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            module = alias.name if alias.asname else alias.name.split(".")[0]
            self.bindings[name] = frozenset({module}) if module in {"importlib", "builtins"} else self._OTHER

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            allowed = node.level == 0 and (node.module, alias.name) in {
                ("importlib", "import_module"), ("builtins", "__import__")
            }
            self.bindings[alias.asname or alias.name] = frozenset({alias.name}) if allowed else self._OTHER

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        binding = self._binding(node.value)
        for target in node.targets:
            self._shadow(target)
            if isinstance(target, ast.Name):
                self.bindings[target.id] = binding

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # An annotation alone does not replace an existing module/class value.
        # Function-local annotation names were already masked at scope entry.
        if node.value is not None:
            self.visit(node.value)
            binding = self._binding(node.value)
            self._shadow(node.target)
            if isinstance(node.target, ast.Name):
                self.bindings[node.target.id] = binding

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        before = self.bindings.copy()
        for statement in node.body:
            self.visit(statement)
        body = self.bindings
        self.bindings = before.copy()
        for statement in node.orelse:
            self.visit(statement)
        otherwise = self.bindings
        self.bindings = {
            name: body.get(name, self._OTHER) | otherwise.get(name, self._OTHER)
            for name in body.keys() | otherwise.keys()
        }

    def _defaults(self, args: ast.arguments) -> None:
        for expression in (*args.defaults, *args.kw_defaults):
            if expression is not None:
                self.visit(expression)

    def _function_body(self, args: ast.arguments, body: list[ast.AST]) -> None:
        outer, class_outer = self.bindings, self.class_outer
        self.bindings = self._closure()
        self.class_outer = None
        for name in _local_names(body):
            self.bindings[name] = self._OTHER
        arguments = (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
        for argument in arguments:
            if argument is not None:
                self.bindings[argument.arg] = self._OTHER
        for statement in body:
            self.visit(statement)
        self.bindings, self.class_outer = outer, class_outer

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for expression in node.decorator_list:
            self.visit(expression)
        self._defaults(node.args)
        self.bindings[node.name] = self._OTHER
        self._function_body(node.args, list(node.body))

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._defaults(node.args)
        self._function_body(node.args, [node.body])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in (*node.decorator_list, *node.bases, *node.keywords):
            self.visit(expression)
        outer, previous_class = self.bindings, self.class_outer
        self.bindings = self._closure()
        self.class_outer = self.bindings.copy()
        for statement in node.body:
            self.visit(statement)
        self.bindings, self.class_outer = outer, previous_class
        self.bindings[node.name] = self._OTHER

    def _comprehension(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> None:
        # Only the first iterable is evaluated in the enclosing namespace.
        self.visit(node.generators[0].iter)
        outer, class_outer = self.bindings, self.class_outer
        self.bindings = self._closure()
        self.class_outer = None
        for index, generator in enumerate(node.generators):
            if index:
                self.visit(generator.iter)
            self._shadow(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        for expression in ((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)):
            self.visit(expression)
        self.bindings, self.class_outer = outer, class_outer

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension

    @staticmethod
    def _argument(node: ast.Call, index: int, keyword: str) -> ast.AST | None:
        if len(node.args) > index:
            return node.args[index]
        return next((item.value for item in node.keywords if item.arg == keyword), None)

    def visit_Call(self, node: ast.Call) -> None:
        targets: set[str | None] = set()
        for loader in sorted(self._binding(node.func) & {"import_module", "__import__"}):
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
            if name not in targets:
                self.imports.append((node, name))
                targets.add(name)
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

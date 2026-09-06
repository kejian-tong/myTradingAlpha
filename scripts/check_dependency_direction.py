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


def _namedexpr_names(root: ast.AST) -> set[str]:
    """Collect walrus targets that bind in a comprehension's containing scope."""

    names: set[str] = set()
    pending = [root]
    while pending:
        node = pending.pop()
        if node is not root and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        pending.extend(ast.iter_child_nodes(node))
    return names


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
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            names.update(_namedexpr_names(node))
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
    Non-string module/class and signature annotations are conservatively scanned
    across Python 3.10-3.14, not evaluated. Function-local variable annotations
    are never evaluated; deferred lookup and type-parameter scopes need review.
    """

    _OTHER = frozenset({None})

    def __init__(self) -> None:
        self.bindings: dict[str, frozenset[str | None]] = {
            "__import__": frozenset({"__import__"})
        }
        self.class_outer: dict[str, frozenset[str | None]] | None = None
        self.imports: list[tuple[ast.AST, str | None]] = []
        self._seen_imports: set[tuple[int, str | None]] = set()
        self.namedexpr_scope: dict[str, frozenset[str | None]] | None = None
        self.in_function = False

    def _binding(self, node: ast.AST) -> frozenset[str | None]:
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id, self._OTHER)
        if isinstance(node, ast.Attribute):
            attributes = {("importlib", "import_module"): "import_module",
                          ("builtins", "__import__"): "__import__"}
            return frozenset(attributes.get((owner, node.attr)) for owner in self._binding(node.value))
        if isinstance(node, ast.NamedExpr):
            return self._binding(node.value)
        if isinstance(node, ast.IfExp):
            return self._binding(node.body) | self._binding(node.orelse)
        return self._OTHER

    def _closure(self) -> dict[str, frozenset[str | None]]:
        # Python functions/comprehensions do not close over class namespaces.
        return (self.class_outer if self.class_outer is not None else self.bindings).copy()

    @classmethod
    def _join_states(
        cls,
        *states: dict[str, frozenset[str | None]],
    ) -> dict[str, frozenset[str | None]]:
        names = set().union(*(state.keys() for state in states))
        return {
            name: frozenset().union(*(state.get(name, cls._OTHER) for state in states))
            for name in names
        }

    def _analyze_block(
        self,
        statements: Iterable[ast.AST],
        start: dict[str, frozenset[str | None]],
    ) -> dict[str, frozenset[str | None]]:
        self.bindings = start.copy()
        for statement in statements:
            self.visit(statement)
        return self.bindings.copy()

    def _analyze_block_snapshots(
        self,
        statements: Iterable[ast.AST],
        start: dict[str, frozenset[str | None]],
    ) -> tuple[
        dict[str, frozenset[str | None]],
        list[dict[str, frozenset[str | None]]],
    ]:
        self.bindings = start.copy()
        snapshots = [self.bindings.copy()]
        for statement in statements:
            self.visit(statement)
            snapshots.append(self.bindings.copy())
        return self.bindings.copy(), snapshots

    def _record_import(self, node: ast.AST, name: str | None) -> None:
        key = (id(node), name)
        if key not in self._seen_imports:
            self._seen_imports.add(key)
            self.imports.append((node, name))

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

    def _assign_target(self, target: ast.AST, binding: frozenset[str | None]) -> None:
        # Target expressions run after the RHS, with stores applied left to right.
        # Unpacking does not imply we know the values assigned to its components.
        if isinstance(target, ast.Name):
            self.bindings[target.id] = binding
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._assign_target(item, self._OTHER)
        elif isinstance(target, ast.Starred):
            self._assign_target(target.value, self._OTHER)
        else:
            self.visit(target)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        binding = self._binding(node.value)
        for target in node.targets:
            self._assign_target(target, binding)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        binding = self._binding(node.value)
        self._assign_target(node.target, binding)
        if self.namedexpr_scope is not None and isinstance(node.target, ast.Name):
            self.namedexpr_scope[node.target.id] = binding

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # An annotation alone does not replace an existing module/class value.
        # Function-local annotation names were already masked at scope entry.
        if node.value is not None:
            self.visit(node.value)
            binding = self._binding(node.value)
            self._assign_target(node.target, binding)
        else:
            # A value-free annotation evaluates a complex target, but stores no name.
            self.visit(node.target)

        if not self.in_function:
            self.visit(node.annotation)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        before = self.bindings.copy()
        body = self._analyze_block(node.body, before)
        otherwise = self._analyze_block(node.orelse, before)
        self.bindings = self._join_states(body, otherwise)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.visit(node.test)
        before = self.bindings.copy()
        body = self._analyze_block((node.body,), before)
        otherwise = self._analyze_block((node.orelse,), before)
        self.bindings = self._join_states(body, otherwise)

    def visit_Try(self, node: ast.Try) -> None:
        before = self.bindings.copy()
        success, try_states = self._analyze_block_snapshots(node.body, before)
        exception_entry = self._join_states(*try_states)
        handler_states: list[dict[str, frozenset[str | None]]] = []
        exceptional_states = list(try_states)
        for handler in node.handlers:
            self.bindings = exception_entry.copy()
            if handler.type is not None:
                self.visit(handler.type)
            if handler.name is not None:
                self.bindings[handler.name] = self._OTHER
            handler_state, snapshots = self._analyze_block_snapshots(
                handler.body,
                self.bindings,
            )
            if handler.name is not None:
                handler_state[handler.name] = self._OTHER
            handler_states.append(handler_state)
            exceptional_states.extend(snapshots)

        success_after_else, else_states = self._analyze_block_snapshots(node.orelse, success)
        exceptional_states.extend(else_states)
        continuing = self._join_states(success_after_else, *handler_states)
        if node.finalbody:
            all_final_inputs = self._join_states(continuing, *exceptional_states)
            self._analyze_block(node.finalbody, all_final_inputs)
            self.bindings = self._analyze_block(node.finalbody, continuing)
        else:
            self.bindings = continuing

    visit_TryStar = visit_Try

    def _loop_body_fixed_point(
        self,
        *,
        entry: dict[str, frozenset[str | None]],
        body: Iterable[ast.AST],
        target: ast.AST | None = None,
    ) -> tuple[
        dict[str, frozenset[str | None]],
        dict[str, frozenset[str | None]],
    ]:
        head = entry.copy()
        while True:
            self.bindings = head.copy()
            if target is not None:
                self._assign_target(target, self._OTHER)
            body_exit = self._analyze_block(body, self.bindings)
            next_head = self._join_states(entry, head, body_exit)
            if next_head == head:
                return head, body_exit
            head = next_head

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        entry = self.bindings.copy()
        head, body_exit = self._loop_body_fixed_point(
            entry=entry,
            body=node.body,
            target=node.target,
        )
        else_exit = self._analyze_block(node.orelse, head)
        self.bindings = self._join_states(head, body_exit, else_exit)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        entry = self.bindings.copy()
        head = entry.copy()
        normal_exit: dict[str, frozenset[str | None]] | None = None
        body_exit = entry.copy()
        while True:
            self.bindings = head.copy()
            self.visit(node.test)
            tested = self.bindings.copy()
            normal_exit = (
                tested
                if normal_exit is None
                else self._join_states(normal_exit, tested)
            )
            body_exit = self._analyze_block(node.body, tested)
            next_head = self._join_states(entry, head, body_exit)
            if next_head == head:
                break
            head = next_head
        assert normal_exit is not None
        loop_exit = self._join_states(normal_exit, body_exit)
        else_exit = self._analyze_block(node.orelse, normal_exit)
        self.bindings = self._join_states(loop_exit, else_exit)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._assign_target(item.optional_vars, self._OTHER)
        for statement in node.body:
            self.visit(statement)

    visit_AsyncWith = visit_With

    def _defaults(self, args: ast.arguments) -> None:
        for expression in (*args.defaults, *args.kw_defaults):
            if expression is not None:
                self.visit(expression)

    def _function_body(self, args: ast.arguments, body: list[ast.AST]) -> None:
        outer, class_outer, in_function, namedexpr_scope = (
            self.bindings,
            self.class_outer,
            self.in_function,
            self.namedexpr_scope,
        )
        self.in_function = True
        self.bindings = self._closure()
        self.class_outer = None
        self.namedexpr_scope = None
        for name in _local_names(body):
            self.bindings[name] = self._OTHER
        arguments = (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
        for argument in arguments:
            if argument is not None:
                self.bindings[argument.arg] = self._OTHER
        for statement in body:
            self.visit(statement)
        self.bindings, self.class_outer, self.in_function, self.namedexpr_scope = (
            outer,
            class_outer,
            in_function,
            namedexpr_scope,
        )

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for expression in node.decorator_list:
            self.visit(expression)
        self._defaults(node.args)
        # Signature annotations belong to the defining scope, before parameters
        # shadow names in the body. Quoted strings remain inert AST constants.
        arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                     node.args.vararg, node.args.kwarg)
        for argument in arguments:
            if argument is not None and argument.annotation is not None:
                self.visit(argument.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        self.bindings[node.name] = self._OTHER
        self._function_body(node.args, list(node.body))

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._defaults(node.args)
        self._function_body(node.args, [node.body])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in (*node.decorator_list, *node.bases, *node.keywords):
            self.visit(expression)
        outer, previous_class, in_function, namedexpr_scope = (
            self.bindings,
            self.class_outer,
            self.in_function,
            self.namedexpr_scope,
        )
        self.in_function = False
        self.bindings = self._closure()
        self.class_outer = self.bindings.copy()
        self.namedexpr_scope = None
        for statement in node.body:
            self.visit(statement)
        self.bindings, self.class_outer, self.in_function, self.namedexpr_scope = (
            outer,
            previous_class,
            in_function,
            namedexpr_scope,
        )
        self.bindings[node.name] = self._OTHER

    def _comprehension(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> None:
        # Only the first iterable is evaluated in the enclosing namespace.
        self.visit(node.generators[0].iter)
        outer, class_outer, previous_namedexpr_scope = (
            self.bindings,
            self.class_outer,
            self.namedexpr_scope,
        )
        containing_scope = (
            previous_namedexpr_scope
            if previous_namedexpr_scope is not None
            else outer
        )
        containing_before = containing_scope.copy()
        self.bindings = self._closure()
        self.class_outer = None
        self.namedexpr_scope = containing_scope
        for index, generator in enumerate(node.generators):
            if index:
                self.visit(generator.iter)
            self._shadow(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        for expression in ((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)):
            self.visit(expression)
        containing_after = containing_scope.copy()
        containing_scope.clear()
        containing_scope.update(self._join_states(containing_before, containing_after))
        self.bindings = (
            containing_scope
            if containing_scope is outer
            else self._join_states(outer, containing_scope)
        )
        self.class_outer = class_outer
        self.namedexpr_scope = previous_namedexpr_scope

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
                self._record_import(node, name)
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

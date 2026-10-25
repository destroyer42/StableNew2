"""Fail when importing a controller module has a static runtime path to tkinter.

The checker is AST-only: no application module is imported.

- Imports inside functions and classes are not part of the module-import closure.
- Imports guarded by ``if TYPE_CHECKING:`` (and ``__name__ == "__main__"``) are ignored.
- Package ``__init__`` modules Python executes while importing a submodule are included.
- Every module under ``src/controller`` is a root.

``--inventory-tk`` prints every ``src`` module with a direct import-time ``tkinter`` import, for the
architecture evidence record.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from collections import deque
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TKINTER = "<tkinter>"


def _module_name(path: Path, base: Path) -> str:
    parts = list(path.relative_to(base).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_paths(src: Path) -> dict[str, Path]:
    base = src.parent
    return {
        _module_name(path, base): path
        for path in sorted(src.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def _is_type_checking_guard(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _is_main_guard(node: ast.AST) -> bool:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    left, right = node.left, node.comparators[0]
    return (
        isinstance(node.ops[0], ast.Eq)
        and isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    )


def _resolve_from_module(
    current_module: str, is_package: bool, imported_module: str | None, level: int
) -> str | None:
    if level == 0:
        return imported_module
    package = current_module if is_package else current_module.rpartition(".")[0]
    if not package:
        return None
    try:
        return importlib.util.resolve_name("." * level + (imported_module or ""), package)
    except (ImportError, ValueError):
        return None


def _package_prefixes(module: str, modules: dict[str, Path]) -> set[str]:
    """Include the package ``__init__`` modules Python executes while importing ``module``."""
    parts = module.split(".")
    prefixes = {".".join(parts[:index]) for index in range(1, len(parts) + 1)}
    return {prefix for prefix in prefixes if prefix in modules}


def _is_tkinter(name: str | None) -> bool:
    return bool(name) and (name == "tkinter" or name.startswith("tkinter."))  # type: ignore[union-attr]


def _targets_for_import(
    node: ast.Import | ast.ImportFrom,
    current_module: str,
    is_package: bool,
    modules: dict[str, Path],
) -> set[str]:
    targets: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            if _is_tkinter(alias.name):
                targets.add(TKINTER)
            else:
                targets.update(_package_prefixes(alias.name, modules))
        return targets

    module = _resolve_from_module(current_module, is_package, node.module, node.level)
    if _is_tkinter(module):
        return {TKINTER}
    if module:
        targets.update(_package_prefixes(module, modules))
        # ``from package import child`` imports package.child when it is a module.
        for alias in node.names:
            candidate = f"{module}.{alias.name}"
            if candidate in modules:
                targets.update(_package_prefixes(candidate, modules))
    return targets


def _runtime_imports(
    source: str, current_module: str, is_package: bool, modules: dict[str, Path]
) -> set[str]:
    imports: set[str] = set()

    def visit(statements: Iterable[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                imports.update(_targets_for_import(statement, current_module, is_package, modules))
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Bodies do not run merely because the module is imported.
                continue
            elif isinstance(statement, ast.If):
                if _is_type_checking_guard(statement.test) or _is_main_guard(statement.test):
                    visit(statement.orelse)
                else:
                    # Platform/config branches are treated conservatively: either may run.
                    visit(statement.body)
                    visit(statement.orelse)
            elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                visit(statement.body)
                visit(statement.orelse)
            elif isinstance(statement, (ast.With, ast.AsyncWith)):
                visit(statement.body)
            elif isinstance(statement, (ast.Try, ast.TryStar)):
                visit(statement.body)
                for handler in statement.handlers:
                    visit(handler.body)
                visit(statement.orelse)
                visit(statement.finalbody)
            elif isinstance(statement, ast.Match):
                for case in statement.cases:
                    visit(case.body)

    visit(ast.parse(source).body)
    return imports


def build_graph(src: Path = SRC) -> tuple[dict[str, set[str]], dict[str, Path]]:
    modules = _module_paths(src)
    graph = {
        module: _runtime_imports(
            path.read_text(encoding="utf-8"), module, path.name == "__init__.py", modules
        )
        for module, path in modules.items()
    }
    return graph, modules


def _shortest_tk_path(root: str, graph: dict[str, set[str]]) -> list[str] | None:
    queue: deque[tuple[str, list[str]]] = deque([(root, [root])])
    seen = {root}
    while queue:
        current, path = queue.popleft()
        for target in sorted(graph.get(current, ())):
            if target == TKINTER:
                return [*path, "tkinter"]
            if target not in seen:
                seen.add(target)
                queue.append((target, [*path, target]))
    return None


def controller_tk_paths(src: Path = SRC) -> list[list[str]]:
    """Return the shortest import path to tkinter for every offending controller module."""
    graph, modules = build_graph(src)
    controller = src / "controller"
    roots = sorted(module for module, path in modules.items() if path.is_relative_to(controller))
    paths = (_shortest_tk_path(root, graph) for root in roots)
    return [path for path in paths if path is not None]


def direct_tk_inventory(src: Path = SRC) -> list[str]:
    graph, modules = build_graph(src)
    base = src.parent
    return sorted(
        modules[module].relative_to(base).as_posix()
        for module, targets in graph.items()
        if TKINTER in targets
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory-tk",
        action="store_true",
        help="print every source module with a direct import-time tkinter dependency",
    )
    args = parser.parse_args(argv)

    if args.inventory_tk:
        for path in direct_tk_inventory():
            print(path)
        return 0

    problems = controller_tk_paths()
    if problems:
        print(f"controller Tk import boundary FAILED ({len(problems)} module(s))", file=sys.stderr)
        for path in problems:
            print("  " + " -> ".join(path), file=sys.stderr)
        return 1

    print("controller Tk import boundary OK: no controller import closure reaches tkinter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

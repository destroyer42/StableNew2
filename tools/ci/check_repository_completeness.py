"""Verify that StableNew's internal Python source is complete in Git.

The check is intentionally offline and deterministic. It catches source files
hidden by ignore rules, untracked or deleted source files, syntax errors that
prevent import inspection, and statically imported ``src.*`` modules that are
missing from the checkout.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True, order=True)
class CompletenessIssue:
    """One deterministic repository-completeness failure."""

    code: str
    path: str
    detail: str

    def format(self) -> str:
        return f"{self.code}: {self.path}: {self.detail}"


def _run_git(root: Path, args: Sequence[str], *, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        input=stdin,
        capture_output=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr}")
    return result.stdout


def _nul_paths(payload: bytes) -> set[str]:
    return {
        item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for item in payload.split(b"\0")
        if item
    }


def _tracked_python_paths(root: Path) -> set[str]:
    return {
        path
        for path in _nul_paths(_run_git(root, ["ls-files", "-z", "--", "src"]))
        if path.endswith(".py")
    }


def _working_python_paths(root: Path) -> set[str]:
    source_root = root / "src"
    if not source_root.is_dir():
        return set()
    return {
        path.relative_to(root).as_posix()
        for path in source_root.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def _ignored_paths(root: Path, paths: Iterable[str]) -> set[str]:
    ordered = sorted(set(paths))
    if not ordered:
        return set()
    payload = b"\0".join(path.encode("utf-8") for path in ordered) + b"\0"
    return _nul_paths(
        _run_git(
            root,
            ["check-ignore", "--no-index", "-z", "--stdin"],
            stdin=payload,
        )
    )


def _module_exists(root: Path, dotted_name: str) -> bool:
    if dotted_name == "src":
        return (root / "src" / "__init__.py").is_file()
    if not dotted_name.startswith("src."):
        return True
    parts = dotted_name.split(".")
    module_path = root.joinpath(*parts)
    return (
        module_path.with_suffix(".py").is_file()
        or (module_path / "__init__.py").is_file()
        or module_path.is_dir()
    )


def _relative_import_name(path: str, level: int, module: str | None) -> str | None:
    parts = list(Path(path).with_suffix("").parts)
    package = parts[:-1]
    if parts[-1] == "__init__":
        package = parts[:-1]
    keep = len(package) - (level - 1)
    if keep <= 0:
        return None
    resolved = package[:keep]
    if module:
        resolved.extend(module.split("."))
    return ".".join(resolved)


def _imported_internal_modules(path: str, tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if alias.name.startswith("src."))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                resolved = _relative_import_name(path, node.level, node.module)
                if resolved and resolved.startswith("src"):
                    modules.add(resolved)
            elif node.module and (
                node.module == "src" or node.module.startswith("src.")
            ):
                modules.add(node.module)
    return modules


def inspect_repository(root: Path | str) -> list[CompletenessIssue]:
    """Return sorted completeness failures for ``root`` without modifying it."""
    repo_root = Path(root).resolve()
    tracked = _tracked_python_paths(repo_root)
    working = _working_python_paths(repo_root)
    issues: set[CompletenessIssue] = set()

    for path in sorted(working - tracked):
        issues.add(
            CompletenessIssue("UNTRACKED_SOURCE", path, "Python source is not tracked")
        )
    for path in sorted(tracked - working):
        issues.add(
            CompletenessIssue("MISSING_TRACKED_SOURCE", path, "tracked source is absent")
        )
    for path in sorted(_ignored_paths(repo_root, working)):
        issues.add(
            CompletenessIssue("IGNORED_SOURCE", path, "an ignore rule matches Python source")
        )

    for path in sorted(tracked & working):
        source_path = repo_root / path
        try:
            with tokenize.open(source_path) as source_file:
                tree = ast.parse(source_file.read(), filename=path)
        except (OSError, UnicodeError, SyntaxError) as exc:
            issues.add(
                CompletenessIssue("UNREADABLE_SOURCE", path, str(exc).replace("\n", " "))
            )
            continue
        for module in sorted(_imported_internal_modules(path, tree)):
            if not _module_exists(repo_root, module):
                issues.add(
                    CompletenessIssue(
                        "MISSING_INTERNAL_IMPORT",
                        path,
                        f"cannot resolve {module}",
                    )
                )

    return sorted(issues)


def _repository_root(candidate: str | None) -> Path:
    if candidate:
        return Path(candidate).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="repository root; defaults to the current Git root")
    args = parser.parse_args(argv)
    root = _repository_root(args.root)

    issues = inspect_repository(root)
    if issues:
        print(f"Repository completeness FAILED ({len(issues)} issue(s))")
        for issue in issues:
            print(issue.format())
        return 1

    tracked_count = len(_tracked_python_paths(root))
    print(f"Repository completeness OK ({tracked_count} tracked Python source files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

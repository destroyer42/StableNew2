"""Run the census test files a change is likely to break, the way the hosted runner would (CI-LEAN parity step).

    python tools/ci/affected_tests.py                 # changes since the merge base with origin/main
    python tools/ci/affected_tests.py --base HEAD~1
    python tools/ci/affected_tests.py --list          # print the selection and its cost, run nothing

Selected, from the committed, staged, unstaged and untracked changes:

- changed test files, and every test file under a changed folder ``conftest.py``;
- test files that import a changed module, directly or through a ``tests`` helper module;
- test files that import the facade of a changed module (``workflow_catalog`` for ``workflow_catalog_wan_animate2``);
- test files that name a changed file (a tool loaded by path, a schema, a pinned workflow or manifest).

The tests run with ``STABLENEW_TESTS_CI_PARITY=1``: FFmpeg, RIFE and ``nvidia-smi`` are hidden as on the hosted runner.

This is a local early warning, not a gate substitute: a selection can miss a distant dependent (about one in five of
the tests recent pull requests had to edit), it cannot reproduce Linux paths or fonts, and the hosted census still runs
every file. Standard library only.
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import census_shards  # noqa: E402
import census_weights  # noqa: E402

CI_PARITY_ENV = "STABLENEW_TESTS_CI_PARITY"  # read by tests/helpers/host_isolation.py
DEFAULT_BASE = "origin/main"
SOURCE_TREES = ("src", "tools", "tests", "services", "scripts")
#: Changes whose blast radius no import graph describes; only the whole census answers for them.
WHOLE_SUITE_FILES = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "tests/conftest.py",
)
#: Windows-only desktop journeys (minutes each). The hosted census skips them, so they are no part of parity with it.
HOSTED_RUNNER_SKIPS = ("tests/tools/test_golden_path_journeys.py",)
#: A file name shorter than this (``main.py``) says too little to count as a test naming that file.
MIN_MENTION_LENGTH = 8


def _git(root: Path, *args: str) -> list[str]:
    result = subprocess.run(["git", *args, "-z"], cwd=root, capture_output=True, check=True).stdout
    return [os.fsdecode(item) for item in result.split(b"\0") if item]


def changed_files(base: str, *, root: Path = ROOT) -> list[str]:
    """Everything that differs from the merge base with ``base``, the uncommitted and untracked work included."""

    merge_base = subprocess.run(
        ["git", "merge-base", base, "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    tracked = _git(root, "diff", "--name-only", "--no-renames", merge_base)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    return sorted(set(tracked) | set(untracked))


def module_names(relative: str) -> list[str]:
    """The names a file can be imported by (a ``services/<x>/`` package is on ``sys.path`` without that prefix)."""

    parts = list(Path(relative).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    names = [".".join(parts)]
    if len(parts) > 2 and parts[0] == "services":
        names.append(".".join(parts[2:]))
    return names


def imported_names(path: Path, module: str) -> set[str]:
    """Absolute dotted names a module imports, ``from x import y`` giving both ``x`` and ``x.y``."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()  # the collection gate reports a file that does not parse
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                package = module.split(".")[: -node.level]
                base = ".".join([*package, base] if base else package)
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def facades(changed: str, *, root: Path = ROOT) -> set[str]:
    """Sibling modules that import ``changed`` and whose name it extends: the split-out module's public face."""

    path = root / changed
    names: set[str] = set()
    for sibling in path.parent.glob("*.py"):
        if sibling == path or not path.stem.startswith(sibling.stem):
            continue
        relative = sibling.relative_to(root).as_posix()
        module = module_names(relative)[0]
        if module_names(changed)[0] in imported_names(sibling, module):
            names.update(module_names(relative))
    return names


def select(
    changed: Iterable[str], *, root: Path = ROOT, active: Iterable[str] | None = None
) -> list[str]:
    """The active census files to run for ``changed`` (repo-relative POSIX paths)."""

    changed = sorted(changed)
    tests = set(census_shards.active_test_files(root) if active is None else active)
    selected = {path for path in changed if path in tests}

    for path in changed:
        folder, _, name = path.rpartition("/")
        if name == "conftest.py" and folder.startswith("tests/"):
            selected.update(test for test in tests if test.startswith(folder + "/"))

    targets: set[str] = set()
    for path in changed:
        if path.endswith(".py") and path.split("/")[0] in SOURCE_TREES and (root / path).is_file():
            if not path.endswith("conftest.py"):
                targets.update(module_names(path))
                targets.update(facades(path, root=root))

    helpers = [p.relative_to(root).as_posix() for p in (root / "tests").rglob("*.py")]
    imports = {
        relative: imported_names(root / relative, module_names(relative)[0])
        for relative in helpers
        if not relative.endswith("conftest.py")
    }
    frontier = set(targets)
    seen = set(targets)
    while frontier:
        reached: set[str] = set()
        for relative, names in imports.items():
            if not names & frontier:
                continue
            if relative in tests:
                selected.add(relative)
            elif not Path(relative).name.startswith("test_"):  # a helper: follow its importers
                reached.update(set(module_names(relative)) - seen)
        seen |= reached
        frontier = reached

    selected.update(_naming(changed, tests, root=root))
    return sorted(selected - set(HOSTED_RUNNER_SKIPS))


def _naming(changed: Sequence[str], tests: set[str], *, root: Path) -> set[str]:
    """Test files that mention the (unique, specific) file name of a changed non-test, non-document file."""

    counts: dict[str, int] = {}
    for tracked in _git(root, "ls-files", "--cached", "--others", "--exclude-standard"):
        counts[Path(tracked).name] = counts.get(Path(tracked).name, 0) + 1
    names = {
        Path(path).name
        for path in changed
        if not path.startswith("tests/")
        and not path.endswith(".md")
        and len(Path(path).name) >= MIN_MENTION_LENGTH
        and counts.get(Path(path).name) == 1
    }
    if not names:
        return set()
    found = set()
    for test in tests:
        text = (root / test).read_text(encoding="utf-8-sig", errors="replace")
        if any(name in text for name in names):
            found.add(test)
    return found


def estimated_seconds(selected: Sequence[str], *, root: Path = ROOT) -> float:
    """Recorded hosted test time of the selection (an unrecorded file counts as the median one)."""

    timings = census_weights.load_timings(census_shards.timings_path(root))
    return sum(census_weights.weigh(selected, timings).weights.values()) / 1000 if selected else 0.0


def run(selected: Sequence[str], *, root: Path = ROOT) -> int:
    """Ordinary pytest on the selection with the census flags and the hosted runner's missing tools hidden."""

    with tempfile.TemporaryDirectory(
        prefix="stablenew-parity-", ignore_cleanup_errors=True
    ) as temp:
        argsfile = Path(temp) / "affected.args"
        argsfile.write_text("\n".join(selected) + "\n", encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "pytest",
            *census_shards.pytest_args(),
            "-p",
            "no:cacheprovider",
            f"--basetemp={Path(temp) / 'pytest-temp'}",
            f"@{argsfile}",
        ]
        environment = {**os.environ, CI_PARITY_ENV: "1", "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(command, cwd=root, env=environment, check=False).returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base", default=DEFAULT_BASE, help=f"compare with (default {DEFAULT_BASE})"
    )
    parser.add_argument("--list", action="store_true", help="print the selection and run nothing")
    args = parser.parse_args(argv)

    try:
        changed = changed_files(args.base)
    except subprocess.CalledProcessError as exc:
        print(
            f"cannot compare with {args.base!r}: {exc.stderr or exc}. Fetch it or pass --base.",
            file=sys.stderr,
        )
        return 2
    selected = select(changed)
    print(
        f"{len(changed)} changed files select {len(selected)} test files, about "
        f"{estimated_seconds(selected):.0f} s of hosted test time.",
        flush=True,
    )
    broad = sorted(set(changed) & set(WHOLE_SUITE_FILES))
    if broad:
        print(
            f"NOTE: {', '.join(broad)} can affect any test; run `python tools/ci/run_pr_gate.py --full --parity`.",
            flush=True,
        )
    if args.list:
        print("\n".join(selected))
        return 0
    return run(selected) if selected else 0


if __name__ == "__main__":
    raise SystemExit(main())

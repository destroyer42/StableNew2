#!/usr/bin/env python
"""Careful repo reorganization helper for StableNew.

This script is intentionally conservative:
- By default it runs in DRY-RUN mode and only prints planned moves.
- Only when invoked with --apply will it actually move files.
- It only touches a known list of root-level debug/test/doc files.

Usage:
  python scripts/reorg_repo.py          # dry-run
  python scripts/reorg_repo.py --apply  # perform moves

Run from the repository root.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


ROOT_DEBUG_FILES = [
    "_tmp_check.py",
    "temp_ppp_test.py",
    "temp_ppp_test2.py",
    "temp_tk_test.py",
    "simple_debug.py",
    "debug_batch.py",
]

ROOT_TEST_FILES = [
    "test_advanced_features.py",
    "test_gui_enhancements.py",
]

ROOT_DOC_FILES = [
    "ARCHITECTURE.md",
    "AUDIT_REPORT_S3_S4_READINESS.md",
    "GUI_ENHANCEMENTS.md",
    "ISSUE_ANALYSIS.md",
    "OPEN_ISSUES_RECOMMENDATIONS.md",
]


def plan_moves(repo_root: Path) -> list[tuple[Path, Path]]:
    moves: list[tuple[Path, Path]] = []

    archive_root = repo_root / "archive" / "root_experiments"
    legacy_docs_root = repo_root / "docs" / "legacy"
    legacy_tests_root = repo_root / "tests" / "legacy"

    # Debug scripts → archive/root_experiments
    for name in ROOT_DEBUG_FILES:
        src = repo_root / name
        if src.exists():
            dst = archive_root / name
            moves.append((src, dst))

    # Root-level test files → tests/legacy
    for name in ROOT_TEST_FILES:
        src = repo_root / name
        if src.exists():
            dst = legacy_tests_root / name
            moves.append((src, dst))

    # Root-level docs → docs/legacy
    for name in ROOT_DOC_FILES:
        src = repo_root / name
        if src.exists():
            dst = legacy_docs_root / name
            moves.append((src, dst))

    return moves


def main() -> None:
    parser = argparse.ArgumentParser(description="StableNew conservative repo reorg helper.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the planned moves (otherwise dry-run).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    print(f"Assumed repo root: {repo_root}")

    moves = plan_moves(repo_root)
    if not moves:
        print("No candidate files found to move. Nothing to do.")
        return

    print("Planned moves:")
    for src, dst in moves:
        print(f"  {src.relative_to(repo_root)} -> {dst.relative_to(repo_root)}")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to perform these moves.")
        return

    # Apply moves
    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        print(f"Moving {src} -> {dst}")
        shutil.move(str(src), str(dst))

    print("Done. Review changes with `git status` and run your full test suite.")


if __name__ == "__main__":
    main()

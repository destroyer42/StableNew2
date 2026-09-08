"""Dry-run or apply the offline one-file PromptPack migration."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.promptpacks.storage import MigrationAction, migrate_legacy_pairs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packs-dir", type=Path, default=Path("packs"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    if args.apply and args.backup_dir is None:
        parser.error("--backup-dir is required with --apply")

    results = migrate_legacy_pairs(args.packs_dir, apply=args.apply, backup_dir=args.backup_dir)
    counts = Counter(result.action.value for result in results)
    print(
        "PromptPack migration "
        + ("apply" if args.apply else "dry-run")
        + ": "
        + ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
    )
    for result in results:
        if result.action in {MigrationAction.CONFLICT, MigrationAction.MALFORMED}:
            print(f"{result.action.value}: {result.stem}: {result.detail}")
    return (
        2
        if any(
            result.action in {MigrationAction.CONFLICT, MigrationAction.MALFORMED}
            for result in results
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())

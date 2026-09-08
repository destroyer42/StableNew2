"""Command-line entry point for the offline SQLite job migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.migrations.sqlite_job_importer import import_legacy_state  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--queue", type=Path, action="append", default=[])
    parser.add_argument("--history", type=Path, action="append", default=[])
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the backup and import; omission is a no-write dry run.",
    )
    args = parser.parse_args()
    sources = [(path, "queue") for path in args.queue]
    sources.extend((path, "history") for path in args.history)
    result = import_legacy_state(
        database_path=args.database,
        sources=sources,
        dry_run=not args.apply,
        backup_root=args.backup_root,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

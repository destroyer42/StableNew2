"""Read-only hygiene report for the job repository: space by column, duplicated Learning snapshots, prune dry run.

It never writes to the database and has no delete option. A first run on a multi-gigabyte repository reads every row
and can take minutes; progress is not printed, so let it finish.

    python tools/job_repository_report.py --database state/jobs.sqlite3 --output-root output
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.learning.learning_paths import get_learning_records_path  # noqa: E402
from src.queue.job_hygiene_report import (  # noqa: E402
    ReportOptions,
    build_report,
    candidates_csv,
    format_report,
    open_read_only,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database", type=Path, required=True, help="the jobs.sqlite3 file")
    parser.add_argument(
        "--output-root", type=Path, help="resolves relative output paths recorded in jobs"
    )
    parser.add_argument(
        "--learning-root",
        type=Path,
        help="data/learning folder; jobs mentioned in its records or saved sessions are protected "
        "(default: the application's learning folder)",
    )
    parser.add_argument(
        "--older-than-days", type=int, default=30, help="only jobs older than this (default 30)"
    )
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    parser.add_argument("--candidates-csv", type=Path, help="write the candidate job ids here")
    args = parser.parse_args(argv)

    if not args.database.is_file():
        print(f"No such database: {args.database}", file=sys.stderr)
        return 2
    learning_root = args.learning_root or get_learning_records_path(create_parent=False).parent
    options = ReportOptions(
        older_than_days=args.older_than_days,
        output_root=args.output_root,
        learning_root=learning_root,
        now=datetime.now(),
    )
    connection = open_read_only(args.database)
    try:
        report = build_report(connection, options, path=args.database)
    finally:
        connection.close()
    if args.candidates_csv:
        args.candidates_csv.write_text(candidates_csv(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

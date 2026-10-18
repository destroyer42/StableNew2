"""Read-only hygiene report for the job repository: space by column, duplicated Learning snapshots, prune dry run.

It never writes to the database and has no delete option. It needs only the standard library, so any Python 3.10+
works (no virtual environment, no installed packages). A first run on a multi-gigabyte repository reads every row
and can take minutes; progress is not printed, so let it finish.

    python tools/job_repository_report.py --database state/jobs.sqlite3 --output-root output
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _load_report_module() -> ModuleType:
    """Load the report by file path so ``src`` (whose packages import the whole application) is never imported.

    The report uses only the standard library, so it runs with any Python 3.10+; no virtual environment needed.
    """

    path = REPOSITORY_ROOT / "src" / "queue" / "job_hygiene_report.py"
    spec = importlib.util.spec_from_file_location("job_hygiene_report", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


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
        "(default: <repository>/data/learning)",
    )
    parser.add_argument(
        "--older-than-days", type=int, default=30, help="only jobs older than this (default 30)"
    )
    parser.add_argument(
        "--result-json",
        action="store_true",
        help="also break down the result_json column (reads and parses every result; slower, prints progress)",
    )
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    parser.add_argument("--candidates-csv", type=Path, help="write the candidate job ids here")
    args = parser.parse_args(argv)

    if not args.database.is_file():
        print(f"No such database: {args.database}", file=sys.stderr)
        return 2
    report_module = _load_report_module()
    learning_root = args.learning_root or REPOSITORY_ROOT / "data" / "learning"
    options = report_module.ReportOptions(
        older_than_days=args.older_than_days,
        output_root=args.output_root,
        learning_root=learning_root,
        now=datetime.now(),
        result_json=args.result_json,
        progress=(lambda message: print(message, file=sys.stderr)) if args.result_json else None,
    )
    connection = report_module.open_read_only(args.database)
    try:
        report = report_module.build_report(connection, options, path=args.database)
    finally:
        connection.close()
    if args.candidates_csv:
        args.candidates_csv.write_text(report_module.candidates_csv(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(report_module.format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

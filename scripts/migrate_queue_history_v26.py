from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.migrations.queue_history_migrator_v26 import migrate_queue_and_history


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-time migration tool for legacy StableNew queue/history persistence."
    )
    parser.add_argument("--queue-path", type=Path, help="Path to the persisted queue file.")
    parser.add_argument("--history-path", type=Path, help="Path to the persisted history file.")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="Directory for backup files. Defaults to a migration_backups folder next to each source file.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Optional JSON file to write the structured migration report.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and report migration work without rewriting any files.",
    )
    args = parser.parse_args()

    report = migrate_queue_and_history(
        queue_path=args.queue_path,
        history_path=args.history_path,
        dry_run=args.dry_run,
        backup_dir=args.backup_dir,
    )
    payload = report.to_dict()
    rendered = json.dumps(payload, indent=2, ensure_ascii=True)
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

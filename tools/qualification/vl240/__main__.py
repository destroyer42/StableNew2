"""``python -m tools.qualification.vl240 <command>``: read-only export of operator-confirmed Review evidence.

Commands: ``describe`` (counts by stratum and progress against the targets; no ids, paths or text), ``export`` (write the
hash-manifested evaluation set outside Git) and ``verify`` (re-hash an export). No command writes Review, History, Learning or
queue state, starts a process, uses the network or runs a model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.qualification.vl240 import contract, export
from tools.qualification.vl240.contract import Refused


def _print(document: Any) -> None:
    sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")


def _default_paths(root: Path | None = None) -> tuple[Path, Path]:
    """This checkout's stores. Neither call creates a directory."""

    from src.state.workspace_paths import WorkspacePaths

    paths = WorkspacePaths(root)
    return paths.learning_records(create_parent=False), paths.job_repository()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.qualification.vl240", description=__doc__
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("describe", "export"):
        sub = commands.add_parser(name)
        sub.add_argument(
            "--learning-records",
            type=Path,
            help="learning_records.jsonl (default: this checkout's)",
        )
        sub.add_argument(
            "--job-repository", type=Path, help="jobs.sqlite3 (default: this checkout's)"
        )
        sub.add_argument(
            "--content-visibility",
            choices=contract.VISIBILITY_MODES,
            default=contract.MODE_SFW,
            help="sfw (default) withholds restricted items; nsfw exports them. Counts show what was withheld.",
        )
    commands.choices["describe"].add_argument(
        "--targets", choices=sorted(contract.TARGETS), default="full"
    )
    exporter = commands.choices["export"]
    exporter.add_argument("--out", type=Path, default=Path(contract.DEFAULT_OUTPUT_ROOT))
    exporter.add_argument(
        "--link", action="store_true", help="hard-link images instead of copying when possible"
    )
    verify = commands.add_parser("verify")
    verify.add_argument("folder", type=Path)
    return parser


def _collect(args: argparse.Namespace) -> export.Collected:
    default_records, default_repository = _default_paths()
    return export.collect(
        args.learning_records or default_records,
        args.job_repository or default_repository,
        visibility_mode=args.content_visibility,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "describe":
            _print(export.describe(_collect(args), targets=args.targets))
        elif args.command == "export":
            folder = export.write_export(_collect(args), args.out, link=args.link)
            _print({"exported": True, "folder": str(folder), "check": export.verify_export(folder)})
        else:
            result = export.verify_export(args.folder)
            _print(result)
            return 0 if result["ok"] else 1
    except Refused as exc:
        _print({"refused": exc.code})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

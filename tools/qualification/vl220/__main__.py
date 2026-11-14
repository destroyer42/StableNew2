"""``python -m tools.qualification.vl220 <command>``: read-only helpers; there is deliberately no command that runs a model.

Commands: ``describe`` (the plan), ``dry-run`` (validate the synthetic set and score the no-look baselines), ``commands``
(print the pinned download lines), ``verify-staging`` and ``import`` (D15 operator workflow), ``write-synthetic``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.qualification.vl220 import plan, staging, synthetic
from tools.qualification.vl220.candidates import CandidateInvalid, find_candidate

DEFAULT_CANDIDATE = "lfm3-vl-2b-q4_k_m-liquidai"


def _print(document: Any) -> None:
    sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")


def _acknowledgement(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.qualification.vl220", description=__doc__
    )
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("describe")
    sub.add_parser("dry-run")
    commands = sub.add_parser("commands")
    commands.add_argument("--dest", required=True)
    for name in ("verify-staging", "import"):
        item = sub.add_parser(name)
        item.add_argument("--staging", type=Path, required=True)
        item.add_argument("--build-id", default="b11960-cpu")
        item.add_argument("--acknowledgement", type=Path, default=None)
        if name == "import":
            item.add_argument("--evaluation-root", type=Path, required=True)
    synth = sub.add_parser("write-synthetic")
    synth.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        candidate = find_candidate(args.candidate)
    except CandidateInvalid as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return 2
    if args.command == "describe":
        _print(plan.build_plan(candidate))
    elif args.command == "dry-run":
        _print(plan.dry_run())
    elif args.command == "commands":
        sys.stdout.write("\n".join(staging.download_commands(candidate, args.dest)) + "\n")
    elif args.command == "verify-staging":
        report = staging.stage_report(
            candidate,
            args.staging,
            build_id=args.build_id,
            acknowledgement=_acknowledgement(args.acknowledgement),
        )
        _print(report)
        return 0 if report["admitted"] else 1
    elif args.command == "import":
        try:
            target = staging.import_candidate(
                candidate, args.staging, args.evaluation_root, build_id=args.build_id,
                acknowledgement=_acknowledgement(args.acknowledgement),
            )  # fmt: skip
        except staging.StagingRefused as exc:
            sys.stderr.write(f"refused: {exc}\n")
            return 1
        sys.stdout.write(f"imported: {target}\n")
    else:
        images, case_doc, label_doc = synthetic.build_synthetic_set()
        if args.dest.exists() and any(args.dest.iterdir()):
            sys.stderr.write("refused: destination is not empty\n")
            return 1
        args.dest.mkdir(parents=True, exist_ok=True)
        for asset_id, data in images.items():
            (args.dest / f"{asset_id}.png").write_bytes(data)
        (args.dest / "cases.json").write_text(
            json.dumps(case_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (args.dest / "labels.json").write_text(
            json.dumps(label_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

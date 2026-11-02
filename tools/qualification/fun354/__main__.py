"""Operator CLI: ``propose`` writes the frozen plan; ``check`` runs the read-only Q0.  There is deliberately no ``run``.

python -m tools.qualification.fun354 propose --out <plan.json> [--driving-clip F] [--reference F]
python -m tools.qualification.fun354 check --plan <plan.json> --comfy-source DIR [--base-directory DIR]
                                           [--driving-clip F] [--reference F] [--runtime-commit SHA] --out <q0.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.utils.atomic_io import atomic_write_json
from src.video.motion_source_preparation import sha256_file
from src.video.workflow_asset_integrity import model_folders
from tools.qualification.fun354 import q0
from tools.qualification.fun354.plan import QualificationPlan, build_plan


def _pin(path: str | None) -> tuple[str, int]:
    if not path:
        return "", 0
    target = Path(path)
    return sha256_file(target), target.stat().st_size


def _outside_repo(out: Path) -> Path:
    resolved = out.resolve()
    root = Path(__file__).resolve().parents[3]
    if root in resolved.parents:
        raise SystemExit(f"Write evidence outside the repository, not to {resolved}.")
    return resolved


def _propose(args: argparse.Namespace) -> int:
    clip, clip_size = _pin(args.driving_clip)
    ref, ref_size = _pin(args.reference)
    plan = build_plan(
        driving_clip_sha256=clip,
        driving_clip_size=clip_size,
        reference_sha256=ref,
        reference_size=ref_size,
    )
    atomic_write_json(
        _outside_repo(Path(args.out)), {**plan.to_record(), "digest": plan.digest}, indent=2
    )
    print(
        f"plan digest {plan.digest}\nphysical execution: NOT AUTHORIZED (this command runs nothing)"
    )
    return 0


def _rebuild(path: Path) -> QualificationPlan:
    record = json.loads(path.read_text(encoding="utf-8"))
    pins = {i["role"]: i for i in record["inputs"]}
    plan = build_plan(
        driving_clip_sha256=pins["driving_clip"]["sha256"],
        driving_clip_size=pins["driving_clip"]["size"],
        reference_sha256=pins["reference_image"]["sha256"],
        reference_size=pins["reference_image"]["size"],
    )
    if plan.digest != record.get("digest"):
        raise SystemExit(
            "The stored plan does not match the current catalog and tooling; propose a new plan."
        )
    return plan


def _check(args: argparse.Namespace) -> int:
    plan = _rebuild(Path(args.plan))
    command = ["--base-directory", args.base_directory] if args.base_directory else []
    folders = model_folders(command, args.comfy_source) if args.comfy_source else None
    out = _outside_repo(Path(args.out))
    report = q0.run_q0(
        plan,
        folders=folders,
        host=q0.read_host_facts(out.parent),
        inputs={
            "driving_clip": Path(args.driving_clip) if args.driving_clip else None,
            "reference_image": Path(args.reference) if args.reference else None,
        },
        runtime_commit=args.runtime_commit,
    )
    atomic_write_json(out, report.to_record(), indent=2)
    print(f"Q0 {report.status} (plan {plan.digest[:12]}); physical execution: NOT AUTHORIZED")
    for check in report.checks:
        print(f"  [{check.status}] {check.check_id}: {check.detail}")
    return 0 if report.ready else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fun354", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose")
    propose.add_argument("--out", required=True)
    check = sub.add_parser("check")
    check.add_argument("--plan", required=True)
    check.add_argument("--out", required=True)
    check.add_argument("--comfy-source")
    check.add_argument("--base-directory")
    check.add_argument("--runtime-commit")
    for p in (propose, check):
        p.add_argument("--driving-clip")
        p.add_argument("--reference")
    args = parser.parse_args(argv)
    return _propose(args) if args.command == "propose" else _check(args)


if __name__ == "__main__":
    sys.exit(main())

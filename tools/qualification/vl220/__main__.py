"""``python -m tools.qualification.vl220 <command>``: operator helpers; exactly one command can launch a model.

Commands: ``describe`` (the plan), ``dry-run`` (validate the synthetic set and score the no-look baselines), ``commands``
(print the pinned download lines), ``verify-staging`` and ``import`` (D15 operator workflow), ``write-synthetic``, and
``evaluate``: the supervised, CPU-only visual run of the owner-approved image invocation contract. ``evaluate`` refuses unless
``--i-have-the-plan-digest`` equals the current plan digest and every admission gate in ``driver.py`` passes; it is never run by
tests, CI or any gate against the real runtime.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _evaluate(args: argparse.Namespace, candidate: Any) -> int:
    """The one command that can launch the visual runtime. Every refusal here runs nothing."""

    from src.ai_assist.host import GenerationActivity
    from src.ai_assist.paths import resolve_ai_root
    from tools.qualification.vl220 import contract, driver
    from tools.qualification.vl220.visual_argv import VisualLimits

    if contract.INVOCATION_APPROVED is not True:
        sys.stderr.write(f"refused: {driver.REFUSED_NOT_APPROVED}\n")
        return 2
    current = plan.build_plan(candidate)["plan_sha256"]
    if not hmac.compare_digest(str(args.i_have_the_plan_digest).strip().lower(), current):
        sys.stderr.write(f"refused: {driver.REFUSED_PLAN_DIGEST} (current plan digest: {current})\n")
        return 2
    if args.evidence_out.exists():
        sys.stderr.write("refused: evidence file already exists\n")
        return 2
    if (args.cases is None) != (args.labels is None):
        sys.stderr.write("refused: --cases and --labels go together\n")
        return 2
    try:
        if args.cases is None:
            _, case_doc, label_doc = synthetic.build_synthetic_set()
        else:
            case_doc, label_doc = _load_json(args.cases), _load_json(args.labels)
        case_set = contract.validate_case_set(case_doc)
        labels = contract.validate_label_set(label_doc, case_set)
        limits = VisualLimits(
            image_min_tokens=args.min_image_tokens, image_max_tokens=args.max_image_tokens
        )
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"refused: {exc.__class__.__name__}: {exc}\n")
        return 2
    acknowledgement = _acknowledgement(args.acknowledgement)
    run = driver.VisualDriver(
        candidate,
        evaluation_root=args.evaluation_root,
        ai_root=resolve_ai_root(args.ai_root),
        assets_dir=args.assets,
        acknowledgement=acknowledgement,
        # Another process cannot read the running application's queue: the operator asserts the host is idle, and without
        # the flag the driver sees no reading and refuses (an unreadable activity is never "idle").
        activity=(lambda: GenerationActivity()) if args.generation_idle else None,
        limits=limits,
    ).run_cases(case_set, labels)
    document = driver.evidence_document(
        run, plan_sha256=current, case_set_sha256=contract.digest(case_doc), candidate=candidate
    )
    with args.evidence_out.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if run.refusal is not None:
        sys.stderr.write(f"refused: {run.refusal}\n")
        return 1
    ran = sum(1 for row in run.evidence if row.launched)
    sys.stdout.write(f"evaluated {ran} of {len(run.evidence)} cases; evidence: {args.evidence_out}\n")
    return 0 if run.complete else 1


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
    evaluate = sub.add_parser("evaluate", description=_evaluate.__doc__)
    evaluate.add_argument("--evaluation-root", type=Path, required=True)
    evaluate.add_argument("--assets", type=Path, required=True)
    evaluate.add_argument("--acknowledgement", type=Path, required=True)
    evaluate.add_argument("--evidence-out", type=Path, required=True)
    evaluate.add_argument(
        "--i-have-the-plan-digest", required=True, help="must equal the current plan digest (see `describe`)"
    )
    evaluate.add_argument(
        "--generation-idle",
        action="store_true",
        help="assert that no generation is running on this host (a separate process cannot read the queue)",
    )
    evaluate.add_argument("--ai-root", type=Path, default=None)
    evaluate.add_argument("--cases", type=Path, default=None)
    evaluate.add_argument("--labels", type=Path, default=None)
    evaluate.add_argument("--min-image-tokens", type=int, default=64)
    evaluate.add_argument("--max-image-tokens", type=int, default=256)
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
    elif args.command == "evaluate":
        return _evaluate(args, candidate)
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

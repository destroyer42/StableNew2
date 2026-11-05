"""Operator CLI for the qualification campaign.

python -m tools.qualification.system840 ledger [--check] [--live] [--json] [--model-root DIR ...] [--hash]
python -m tools.qualification.system840 plan --arm ARM --stage canary|coverage --targets targets.json --out plan.json
python -m tools.qualification.system840 readiness --plan plan.json [--authorization auth.json]
python -m tools.qualification.system840 authorize --plan plan.json --out auth.json --approved-by NAME   (interactive only)
python -m tools.qualification.system840 run --plan plan.json --authorization auth.json [--evidence-root DIR]
python -m tools.qualification.system840 dry-run [--scenario S] --out report.json
python -m tools.qualification.system840 verify ATTEMPT_DIR
python -m tools.qualification.system840 compare BEFORE_DIR AFTER_DIR [--out comparison.json]

Nothing here starts a runtime or generates anything: ``run`` dispatches through an adapter, and no physical adapter is wired
in this repository, so it stops at the gates and reports NOT RUN with the retained harness to use.  The approval step is
the owner's act and is refused in CI, under pytest and from any non-terminal session.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.operator_journey.workspace import REPO_ROOT
from tools.qualification.system840 import compare as compare_mod
from tools.qualification.system840 import (
    coordinator,
    dryrun,
    evidence,
    host_inventory,
    safety,
)
from tools.qualification.system840 import (
    ledger as ledger_mod,
)
from tools.qualification.system840 import (
    plan as plan_mod,
)
from tools.qualification.system840.probes import QualProbes
from tools.qualification.system840.statuses import STATUS_DEFINITIONS


def _outside_repo(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if REPO_ROOT.resolve() in resolved.parents:
        raise SystemExit(f"Write evidence and plans outside the repository, not to {resolved}.")
    return resolved


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _cmd_ledger(args: argparse.Namespace) -> int:
    ledger = ledger_mod.load_ledger()
    problems = ledger_mod.validate_ledger(ledger)
    out: dict[str, Any] = {"summary": ledger_mod.summarize(ledger), "problems": problems}
    if args.live:
        out["live_drift"] = ledger_mod.reconcile_with_live(ledger)
    if args.model_root:
        roots = [Path(r) for r in args.model_root]
        out["installed_assets"] = host_inventory.installed_assets(
            ledger, roots, hash_files=args.hash
        )
    if args.json:
        out["status_definitions"] = {k.value: v for k, v in STATUS_DEFINITIONS.items()}
        out["capabilities"] = ledger.document["capabilities"]
        out["standing_holds"] = ledger.document["standing_holds"]
        _print(out)
    else:
        print(f"{len(ledger)} capabilities; by status: {out['summary']['by_status']}")
        for arm, counts in out["summary"]["by_arm"].items():
            print(f"  {arm}: {counts}")
        for entry in ledger:
            print(f"  [{entry.status.value:<19}] {entry.id}")
        for problem in problems:
            print(f"PROBLEM: {problem}")
        for drift in out.get("live_drift", []):
            print(f"DRIFT: {drift}")
    return 1 if args.check and (problems or out.get("live_drift")) else 0


def _cmd_plan(args: argparse.Namespace) -> int:
    targets = plan_mod.load_json(Path(args.targets))
    ledger = ledger_mod.load_ledger()
    try:
        plan = plan_mod.build_plan(
            args.arm,
            stage=args.stage,
            cases=targets["cases"],
            runtime=targets["runtime"],
            limits=targets["limits"],
            evidence_dir=targets["evidence_dir"],
            probes=QualProbes(),
            ledger=ledger,
        )
    except plan_mod.PlanRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    problems = plan_mod.shape_problems(plan)
    from src.utils.atomic_io import atomic_write_json

    atomic_write_json(_outside_repo(args.out), plan, indent=2, sort_keys=True)
    print(
        f"plan digest {plan['digest']}\nphysical execution: NOT AUTHORIZED (this command runs nothing)"
    )
    for problem in problems:
        print(f"INCOMPLETE: {problem}", file=sys.stderr)
    return 2 if problems else 0


def _cmd_readiness(args: argparse.Namespace) -> int:
    plan = plan_mod.load_json(Path(args.plan))
    auth = plan_mod.load_json(Path(args.authorization)) if args.authorization else None
    result = safety.readiness(plan, QualProbes(), auth=auth)
    _print(result)
    return 0 if result["ready"] else 4


def _cmd_authorize(args: argparse.Namespace) -> int:
    plan = plan_mod.load_json(Path(args.plan))
    phrase = plan_mod.approval_phrase(plan)
    print(f"Approving arm {plan['arm_id']} stage {plan['stage']} digest {plan['digest']}.")
    print(f"Type exactly: {phrase}")
    try:
        typed = input("> ")
        record = plan_mod.issue_authorization(
            plan, approved_by=args.approved_by, typed_phrase=typed, ttl_hours=args.ttl_hours
        )
    except (plan_mod.AuthorizationRefused, EOFError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    from src.utils.atomic_io import atomic_write_json

    atomic_write_json(_outside_repo(args.out), record, indent=2, sort_keys=True)
    print(
        "authorization written (it names this digest only; launch still needs the separate RUN confirmation)"
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    plan = plan_mod.load_json(Path(args.plan))
    auth = plan_mod.load_json(Path(args.authorization))
    session = coordinator.Session()
    report = coordinator.run_stage(
        plan,
        auth,
        adapter=coordinator.UnwiredAdapter(),
        probes=QualProbes(),
        evidence_root=evidence.resolve_root(args.evidence_root),
        confirm=lambda phrase: input(f"Type {phrase!r} to launch: "),
        session=session,
        ledger=ledger_mod.load_ledger(),
    )
    _print(report)
    return 0 if report["status"] == coordinator.RAN else 4


def _cmd_dry_run(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="qual840-dry-") as tmp:
        report = dryrun.run_dry_campaign(Path(tmp), scenario=args.scenario)
        report["simulated"] = True
        out = Path(args.out)
        coordinator.write_campaign_report(report, out)
    print(f"simulated campaign: {report['counts']} -> {out}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    report = evidence.verify_attempt(Path(args.attempt))
    _print(report)
    return 0 if report["status"] == evidence.OK else 1


def _cmd_compare(args: argparse.Namespace) -> int:
    try:
        report = compare_mod.compare(args.before, args.after)
    except compare_mod.Incomparable as exc:
        print(f"NOT COMPARABLE: {exc}", file=sys.stderr)
        return compare_mod.EXIT_INCOMPARABLE
    if args.out:
        compare_mod.write_comparison(report, _outside_repo(args.out))
    _print(report)
    return compare_mod.exit_code(report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.qualification.system840", description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ledger")
    p.add_argument("--check", action="store_true")
    p.add_argument("--live", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--model-root", action="append")
    p.add_argument("--hash", action="store_true")
    p.set_defaults(func=_cmd_ledger)
    p = sub.add_parser("plan")
    p.add_argument("--arm", required=True)
    p.add_argument("--stage", choices=("canary", "coverage"), required=True)
    p.add_argument("--targets", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_plan)
    p = sub.add_parser("readiness")
    p.add_argument("--plan", required=True)
    p.add_argument("--authorization")
    p.set_defaults(func=_cmd_readiness)
    p = sub.add_parser("authorize")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--approved-by", required=True)
    p.add_argument("--ttl-hours", type=float, default=24)
    p.set_defaults(func=_cmd_authorize)
    p = sub.add_parser("run")
    p.add_argument("--plan", required=True)
    p.add_argument("--authorization", required=True)
    p.add_argument("--evidence-root")
    p.set_defaults(func=_cmd_run)
    p = sub.add_parser("dry-run")
    p.add_argument("--scenario", default="success", choices=coordinator.SCENARIOS)
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_dry_run)
    p = sub.add_parser("verify")
    p.add_argument("attempt")
    p.set_defaults(func=_cmd_verify)
    p = sub.add_parser("compare")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--out")
    p.set_defaults(func=_cmd_compare)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))

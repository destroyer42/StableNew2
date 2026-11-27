"""VID-CAND-LTX25 offline commands: build the LTX-2.5 suites and plan, and the blind three-way sheet.

None of these commands queues a job, starts a runtime, downloads a model or issues an authorization.  Run identity,
wall time and telemetry are checked with the unchanged ``python -m tools.qualification.vid_cand382 verify``.

    python -m tools.qualification.vid_cand_ltx25 build --stage1-suite A --stage2-suite B --suites-out DIR \
        --plan-out DIR --base-commit SHA
    python -m tools.qualification.vid_cand_ltx25 threeway --source RUN382 a14b_base --source RUN382 hy15_8step \
        --source RUNLTX ltx25_distilled --seed 382 --out-dir DIR
    python -m tools.qualification.vid_cand_ltx25 score --sheet DIR/threeway.csv --key DIR/threeway_key.json

``--stage1-suite`` and ``--stage2-suite`` are the frozen VID-CAND-382 suites (either stage 2 suite: both hold the
same cases).  The LTX suites reference the same images, so ``--suites-out`` must be the folder that holds the sources
(``<Output>/eval_plans/video``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.video.video_eval_suite import load_eval_suite
from tools.qualification.vid_cand382 import plan as base
from tools.qualification.vid_cand_ltx25 import plan as design
from tools.qualification.vid_cand_ltx25 import threeway as ranking

ROOT = Path(__file__).resolve().parents[3]


def _refuse_inside_repo(path: Path) -> None:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT) and resolved.relative_to(ROOT).parts[:1] != ("output",):
        raise SystemExit(f"{path} is inside the repository; private files stay outside it")


def _write_new(path: Path, document: Any) -> bytes:
    data = (json.dumps(document, indent=1, ensure_ascii=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:  # never replaces a frozen file
        stream.write(data)
    return data


def build(args: argparse.Namespace) -> int:
    for path in (args.suites_out, args.plan_out):
        _refuse_inside_repo(path)
    stage1_bytes, stage2_bytes = args.stage1_suite.read_bytes(), args.stage2_suite.read_bytes()
    suites = design.build_suites(json.loads(stage1_bytes), json.loads(stage2_bytes))
    targets = {key: args.suites_out / design.SUITE_FILES[key] for key in suites}
    for path in (*targets.values(), args.plan_out / design.PLAN_FILE):
        if path.exists():
            raise SystemExit(f"{path} exists; a frozen file is never replaced")
    suite_bytes = {key: _write_new(targets[key], suite) for key, suite in suites.items()}
    for key, path in targets.items():
        loaded = load_eval_suite(path)  # also proves every source image is present and unchanged
        print(f"{key}: loads, {loaded.job_count} jobs")
    plan = design.freeze_plan(
        suites,
        suite_bytes,
        base_commit=args.base_commit,
        source_digests={
            args.stage1_suite.name: base.file_sha256(stage1_bytes),
            args.stage2_suite.name: base.file_sha256(stage2_bytes),
        },
    )
    _write_new(args.plan_out / design.PLAN_FILE, plan)
    digest = base.plan_digest(plan)
    print(f"plan: {args.plan_out / design.PLAN_FILE}\nPLAN DIGEST {digest}\ndigest12 {digest[:12]}")
    return 0


def threeway(args: argparse.Namespace) -> int:
    _refuse_inside_repo(args.out_dir)
    out_dir = args.out_dir.resolve()
    for run, _arm in args.source:  # source runs are only read; the sheet lives in its own folder
        if out_dir.is_relative_to(Path(run).resolve()):
            raise SystemExit(f"{args.out_dir} is inside the source run {run}; use a separate folder")
    sources =[(arm, ranking.run_clips(Path(run), arm)) for run, arm in args.source]
    joined, skipped = ranking.join_cases(sources)
    result = ranking.build_sheet(joined, seed=args.seed, out_dir=args.out_dir)
    print(json.dumps({**result, "skipped": skipped}, indent=1))
    return 0


def score(args: argparse.Namespace) -> int:
    print(json.dumps(ranking.score_sheet(args.sheet, args.key), indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    b = commands.add_parser("build", help="write the LTX-2.5 suites and the frozen plan")
    b.add_argument("--stage1-suite", type=Path, required=True)
    b.add_argument("--stage2-suite", type=Path, required=True)
    b.add_argument("--suites-out", type=Path, required=True)
    b.add_argument("--plan-out", type=Path, required=True)
    b.add_argument("--base-commit", required=True)
    b.set_defaults(func=build)

    t = commands.add_parser("threeway", help="write the blind ranking sheet across runs")
    t.add_argument("--source", nargs=2, action="append", required=True, metavar=("RUN_DIR", "ARM"))
    t.add_argument("--seed", type=int, required=True)
    t.add_argument("--out-dir", type=Path, required=True)
    t.set_defaults(func=threeway)

    s = commands.add_parser("score", help="score the owner's filled threeway.csv")
    s.add_argument("--sheet", type=Path, required=True)
    s.add_argument("--key", type=Path, required=True)
    s.set_defaults(func=score)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

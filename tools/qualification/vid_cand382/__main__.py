"""VID-CAND-382 offline commands: build the frozen suites and plan, verify a run, blind-pair clips, score the pairing.

None of these commands queues a job, starts a runtime, downloads a model or issues an authorization.

    python -m tools.qualification.vid_cand382 build --stage1-suite A --stage2-suite B --suites-out DIR --plan-out DIR
    python -m tools.qualification.vid_cand382 verify --run-dir RUN --suite FILE --stage stage1 --jobs-db state/jobs.sqlite3
    python -m tools.qualification.vid_cand382 pairwise --run-dir RUN --candidate-arm hy15_8step --seed 382
    python -m tools.qualification.vid_cand382 score-pairwise --sheet RUN/pairwise.csv --key RUN/pairwise_key.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.video.video_eval_suite import load_eval_suite
from tools.qualification.vid_cand382 import pairwise as pairing
from tools.qualification.vid_cand382 import plan as design
from tools.qualification.vid_cand382.verify import analyze_run

ROOT = Path(__file__).resolve().parents[3]
#: Where the repository keeps gitignored operator output; any other place inside the checkout is refused for private files.
ALLOWED_IN_REPO = ("output",)
#: Stage 2 keeps five CLIP-371 full-body cases and gives three sources a harder action (hand-off: hands interacting,
#: two-step action, fast turn); the mapping is by case-id prefix of the CLIP-371 stage 2 suite.
STAGE2_REPLACEMENTS = {"fb3": 0, "fb4": 1, "fb6": 2}


def _refuse_inside_repo(path: Path) -> None:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT) and resolved.relative_to(ROOT).parts[0] not in ALLOWED_IN_REPO:
        raise SystemExit(
            f"{path} is inside the repository; private suites and plans stay outside it"
        )


def _write_new(path: Path, text: str) -> bytes:
    data = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:  # never replaces an existing frozen file
        stream.write(data)
    return data


def _dump(document: Any) -> str:
    return json.dumps(document, indent=1, ensure_ascii=True) + "\n"


def stage2_cases(source_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    for case in source_cases:
        prefix = case["case_id"].split("_")[0]
        if prefix in STAGE2_REPLACEMENTS:
            key, slug, action = design.NEW_HARD_ACTIONS[STAGE2_REPLACEMENTS[prefix]]
            case = {
                **case,
                "case_id": f"{prefix}_{slug}",
                "prompt": design.hard_case_prompt(action),
                "tags": ["structured", "full-body", "hard", key],
            }
        cases.append(case)
    return cases


def build(args: argparse.Namespace) -> int:
    stage1_source = json.loads(args.stage1_suite.read_text(encoding="utf-8"))
    stage1 = [c for c in stage1_source["cases"] if "structured" in c.get("tags", [])]
    stage2 = stage2_cases(json.loads(args.stage2_suite.read_text(encoding="utf-8"))["cases"])
    suites = {
        "stage0": design.build_stage0(stage1[0]),
        "stage1": design.build_stage1(stage1),
        "stage2_hy8": design.build_stage2(stage2, 8),
        "stage2_hy12": design.build_stage2(stage2, 12),
    }
    for path in (args.suites_out, args.plan_out):
        _refuse_inside_repo(path)
    written = {
        key: (args.suites_out / design.SUITE_FILES[key], _dump(suite))
        for key, suite in suites.items()
    }
    for path, _text in written.values():
        if path.exists():
            raise SystemExit(f"{path} exists; a frozen suite is never replaced")
    suite_bytes = {key: _write_new(path, text) for key, (path, text) in written.items()}
    for key, (path, _text) in written.items():
        loaded = load_eval_suite(path)
        print(
            f"{key}: loads, {len(loaded.cases)} cases x {len(loaded.arms)} arms = {loaded.job_count} jobs"
        )
    cases = [
        {
            "case_id": c["case_id"],
            "image_sha256": c["image_sha256"],
        }
        for c in stage1
    ]
    plan = design.freeze_plan(suites, suite_bytes, base_commit=args.base_commit, cases=cases)
    plan_file = args.plan_out / "vid_cand_382_plan.v1.json"
    _write_new(plan_file, _dump(plan))
    digest = design.plan_digest(plan)
    print(f"plan: {plan_file}\nPLAN DIGEST {digest}\ndigest12 {digest[:12]}")
    return 0


def verify(args: argparse.Namespace) -> int:
    plan = json.loads(args.plan.read_text(encoding="utf-8")) if args.plan else None
    suite_sha = (
        next(
            entry["sha256"] for entry in plan["suites"].values() if entry["file"] == args.suite.name
        )
        if plan
        else design.file_sha256(args.suite.read_bytes())
    )
    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    pairwise_result = (
        pairing.score_pairing(args.pairwise_sheet, args.pairwise_key)
        if args.pairwise_sheet
        else None
    )
    report = analyze_run(
        args.run_dir,
        jobs_db=args.jobs_db,
        suite_file=args.suite,
        suite_sha256=suite_sha,
        stage=args.stage,
        baseline_arm=suite["baseline_arm"],
        ratings_csv=args.ratings or args.run_dir / "ratings.csv",
        telemetry_file=args.telemetry,
        pairwise=pairwise_result,
    )
    report["pairwise"] = pairwise_result
    print(json.dumps(report, indent=1))
    return 0 if all(check["ok"] for check in report["checks"]) else 1


def pairwise(args: argparse.Namespace) -> int:
    metrics = json.loads((args.run_dir / "metrics.json").read_text(encoding="utf-8"))
    cells = (
        metrics["cells"] if isinstance(metrics["cells"], list) else list(metrics["cells"].values())
    )
    clips: dict[str, dict[str, Path]] = {}
    for cell in cells:
        if cell.get("path"):
            clips.setdefault(cell["case_id"], {})[cell["arm_id"]] = Path(cell["path"])
    result = pairing.build_pairing(
        clips,
        baseline_arm=design.A14B_ARM,
        candidate_arm=args.candidate_arm,
        seed=args.seed,
        out_dir=args.run_dir,
    )
    print(json.dumps(result, indent=1))
    return 0


def score_pairwise(args: argparse.Namespace) -> int:
    print(json.dumps(pairing.score_pairing(args.sheet, args.key), indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    b = commands.add_parser(
        "build", help="write the four frozen suites and the plan from private cases"
    )
    b.add_argument(
        "--stage1-suite", type=Path, required=True, help="the VID-CLIP-371 stage 1 suite"
    )
    b.add_argument(
        "--stage2-suite", type=Path, required=True, help="the VID-CLIP-371 stage 2 suite"
    )
    b.add_argument("--suites-out", type=Path, required=True, help="<Output>/eval_plans/video")
    b.add_argument(
        "--plan-out", type=Path, required=True, help="private folder for the frozen plan"
    )
    b.add_argument("--base-commit", required=True)
    b.set_defaults(func=build)

    v = commands.add_parser("verify", help="read-only analysis of one run")
    v.add_argument("--run-dir", type=Path, required=True)
    v.add_argument("--suite", type=Path, required=True)
    v.add_argument("--stage", choices=("stage0", "stage1", "stage2"), required=True)
    v.add_argument("--plan", type=Path)
    v.add_argument("--jobs-db", type=Path, default=Path("state/jobs.sqlite3"))
    v.add_argument("--ratings", type=Path)
    v.add_argument("--telemetry", type=Path)
    v.add_argument("--pairwise-sheet", type=Path)
    v.add_argument("--pairwise-key", type=Path)
    v.set_defaults(func=verify)

    p = commands.add_parser(
        "pairwise", help="write the blind pairwise sheet, folder and key for a run"
    )
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--candidate-arm", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.set_defaults(func=pairwise)

    s = commands.add_parser("score-pairwise", help="score the owner's filled pairwise.csv")
    s.add_argument("--sheet", type=Path, required=True)
    s.add_argument("--key", type=Path, required=True)
    s.set_defaults(func=score_pairwise)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

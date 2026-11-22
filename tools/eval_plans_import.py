"""Preview or copy existing video suites into the canonical Evaluation Plans workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in ("", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.state.eval_plans_paths import initialize_eval_plans
from src.state.workspace_paths import workspace_paths
from src.video.video_eval_import import import_suite, is_private_suite, suite_templates
from tools.qualification.eval_plan_output import configured_eval_plans_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", type=Path, required=True, help="Suite folder")
    parser.add_argument("--apply", action="store_true", help="Copy suites and seed templates")
    args = parser.parse_args(argv)
    if not args.source.is_dir():
        parser.error(f"Source folder does not exist: {args.source}")
    root = configured_eval_plans_root()
    verb = "Copied" if args.apply else "Would copy"
    failures = 0
    for source in sorted(args.source.glob("*.json")):
        if is_private_suite(source):
            print(f"Skipped private suite: {source.name}")
            continue
        if not source.name.casefold().endswith(".suite.json"):
            continue
        try:
            target = import_suite(source, root, apply=args.apply)
        except FileExistsError as exc:
            print(f"Skipped: {exc}")
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            print(f"Skipped {source.name}: {exc}", file=sys.stderr)
            failures += 1
        else:
            print(f"{verb} {source} -> {target}")
    if args.apply:
        initialize_eval_plans(root)
    examples = workspace_paths.root / "docs" / "runbooks" / "examples"
    for target in suite_templates(examples, root, apply=args.apply):
        print(f"{verb} template -> {target}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())

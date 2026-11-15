"""Command line for the two-tier evaluation (PR-AI-VL-242). Runs no model and opens no network connection.

    python -m tools.qualification.vl242 convert --export EXPORT.json --out DIR
    python -m tools.qualification.vl242 plan --cases DIR/cases.json --labels DIR/labels.json --stage pilot|full
    python -m tools.qualification.vl242 report --cases ... --labels ... --stage ... --fast FAST.json --deep DEEP.json

``convert`` writes ``cases.json`` and ``labels.json``; ``report --out`` writes the report. Every write is refused inside the
repository: real cases, labels, evidence and reports stay outside Git. Printed output is digests and counts only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.qualification.vl220 import eval2, review_export
from tools.qualification.vl220.contract import ContractViolation
from tools.qualification.vl242 import analysis, gates, plan, report

REPO_ROOT = Path(__file__).resolve().parents[3]


class Refused(ValueError):
    pass


def outside_repository(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise Refused("real evaluation files must be written outside the repository")
    return resolved


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write(path: Path, document: Any) -> None:
    target = outside_repository(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = (
        document
        if isinstance(document, str)
        else json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    target.write_text(text, encoding="utf-8", newline="\n")


def _limits(path: str | None) -> dict[str, analysis.TierLimits]:
    if path is None:
        return {}
    raw = _load(path)
    if not isinstance(raw, dict) or not set(raw) <= set(eval2.TIERS):
        raise Refused("limits file must map fast/deep to limit objects")
    fields = set(analysis.TierLimits.__dataclass_fields__)
    out: dict[str, analysis.TierLimits] = {}
    for tier, values in raw.items():
        if not isinstance(values, dict) or set(values) != fields:
            raise Refused(f"{tier} limits need exactly {sorted(fields)}")
        out[tier] = analysis.TierLimits(
            float(values["max_wall_seconds"]), int(values["max_peak_working_set_bytes"]),
            float(values["median_seconds_budget"]),
        )  # fmt: skip
    return out


def _plan(args: argparse.Namespace) -> tuple[dict[str, Any], Any, Any]:
    case_doc, label_doc = _load(args.cases), _load(args.labels)
    limits = _limits(args.limits)
    built = plan.build_plan(
        case_doc, label_doc, stage=args.stage, fast_limits=limits.get(eval2.TIER_FAST),
        deep_limits=limits.get(eval2.TIER_DEEP), florence_in_scope=args.florence,
    )  # fmt: skip
    return built, case_doc, label_doc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.qualification.vl242")
    sub = parser.add_subparsers(dest="command", required=True)
    convert = sub.add_parser("convert", help="build eval/2 cases and labels from a Review export")
    convert.add_argument("--export", required=True)
    convert.add_argument("--out", required=True)
    for name in ("plan", "report"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--cases", required=True)
        cmd.add_argument("--labels", required=True)
        cmd.add_argument("--stage", required=True, choices=gates.STAGES)
        cmd.add_argument("--limits", help="JSON file with owner-approved per-tier limits")
        cmd.add_argument(
            "--florence", action="store_true", help="the Florence-2 comparator is in scope"
        )
        if name == "report":
            cmd.add_argument("--fast", required=True)
            cmd.add_argument("--deep", required=True)
            cmd.add_argument(
                "--comparator", help="Florence-2 comparator evidence (needs --florence)"
            )
            cmd.add_argument("--out", help="write the report here (outside the repository)")
    args = parser.parse_args(argv)
    try:
        if args.command == "convert":
            out = Path(args.out)
            outside_repository(out)
            conversion = review_export.convert(_load(args.export))
            _write(out / "cases.json", conversion.cases)
            _write(out / "labels.json", conversion.labels)
            print(json.dumps(conversion.summary, indent=2, sort_keys=True))
            return 0
        built, case_doc, label_doc = _plan(args)
        if args.command == "plan":
            print(json.dumps({k: built[k] for k in ("plan_sha256", "stage", "case_set", "tiers", "florence_in_scope")},
                             indent=2, sort_keys=True))  # fmt: skip
            return 0
        if args.out:
            outside_repository(Path(args.out))
        case_set = eval2.validate_case_set(case_doc)
        labels = eval2.validate_label_set(label_doc, case_set)
        fast = eval2.validate_evidence(_load(args.fast), case_set)
        deep = eval2.validate_evidence(_load(args.deep), case_set)
        comparator = _load(args.comparator) if args.comparator else None
        result = analysis.analyze(case_set, labels, fast, deep, built, florence=comparator)
        text = report.render(result, gates.evaluate(result))
        if args.out:
            _write(Path(args.out), text)
        else:
            print(text)
        return 0
    except (ContractViolation, analysis.AnalysisRefused, Refused, ValueError, OSError) as exc:
        code = getattr(exc, "code", None) or str(exc)
        print(f"refused: {code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

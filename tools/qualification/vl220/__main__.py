"""Operator commands for staged verification, import, readiness and supervised offline evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.ai_assist.manifests import ImportRefused, import_runtime, load_runtime_manifest
from tools.qualification.vl220 import contract, driver, plan, staging, synthetic
from tools.qualification.vl220.candidates import (
    RUNTIME_MANIFEST_PATH,
    CandidateInvalid,
    find_candidate,
    has_link,
    runtime_reasons,
)
from tools.qualification.vl220.invocation import InvocationRefused

DEFAULT_CANDIDATE = "lfm3-vl-2b-q4_k_m-liquidai"


def _print(document: Any) -> None:
    sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")


def _acknowledgement(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        loaded = driver.read_document(path)
    except (OSError, ValueError, RecursionError):
        return None
    return loaded if isinstance(loaded, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.qualification.vl220", description=__doc__
    )
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("describe")
    sub.add_parser("describe-execution")
    sub.add_parser("dry-run")
    commands = sub.add_parser("commands")
    commands.add_argument("--dest", required=True)
    for name in ("status", "import-runtime", "evaluate"):
        item = sub.add_parser(name)
        item.add_argument("--evaluation-root", type=Path, required=True)
        if name == "import-runtime":
            item.add_argument("--archive", type=Path, required=True)
        else:
            item.add_argument("--acknowledgement", type=Path)
        if name == "evaluate":
            item.add_argument("--cases", type=Path, required=True)
            item.add_argument("--labels", type=Path, required=True)
            item.add_argument("--execution-sha256", required=True)
            item.add_argument("--case-sha256", required=True)
            item.add_argument("--label-sha256", required=True)
    for name in ("verify-staging", "import"):
        item = sub.add_parser(name)
        item.add_argument("--staging", type=Path, required=True)
        item.add_argument("--build-id")
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
    if args.command == "describe-execution":
        _print(driver.execution_identity(candidate))
    elif args.command in {"status", "import-runtime", "evaluate"}:
        try:
            root = staging.evaluation_root(args.evaluation_root)
            if args.command == "import-runtime":
                manifest = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
                build_id = candidate.runtime.required_build_id
                build = manifest.find(build_id)
                if build is None or runtime_reasons(candidate, build_id, manifest):
                    raise InvocationRefused("runtime_build_not_pinned_or_compatible")
                if has_link(args.archive) or has_link(root / "runtimes" / build_id):
                    raise InvocationRefused("unsafe_link_or_nonregular_file")
                if not args.archive.is_file():
                    raise InvocationRefused("runtime_archive_missing")
                _print({"installed_runtime": str(import_runtime(args.archive, build, root))})
            elif args.command == "status":
                result = driver.readiness(root, candidate, _acknowledgement(args.acknowledgement))
                _print(result)
                return 0 if result["launch_prerequisites_met"] else 1
            else:
                result = driver.evaluate(
                    candidate.candidate_id,
                    root,
                    args.cases,
                    args.labels,
                    _acknowledgement(args.acknowledgement),
                    execution_sha256=args.execution_sha256,
                    case_sha256=args.case_sha256,
                    label_sha256=args.label_sha256,
                )
                _print(result)
                return 0 if result["complete"] else 1
        except contract.ContractViolation as exc:
            sys.stderr.write(f"refused: {exc.code}\n")
            return 1
        except (staging.StagingRefused, ImportRefused, InvocationRefused) as exc:
            sys.stderr.write(f"refused: {exc}\n")
            return 1
        except (OSError, ValueError, RecursionError):
            sys.stderr.write("refused: invalid_evaluation_input_or_io_error\n")
            return 1
        except KeyboardInterrupt:
            sys.stderr.write("refused: cancelled\n")
            return 130
    elif args.command == "describe":
        _print(plan.build_plan(candidate))
    elif args.command == "dry-run":
        _print(plan.dry_run())
    elif args.command == "commands":
        sys.stdout.write("\n".join(staging.download_commands(candidate, args.dest)) + "\n")
    elif args.command == "verify-staging":
        report = staging.stage_report(
            candidate,
            args.staging,
            build_id=args.build_id or candidate.runtime.required_build_id,
            acknowledgement=_acknowledgement(args.acknowledgement),
        )
        _print(report)
        return 0 if report["admitted"] else 1
    elif args.command == "import":
        try:
            target = staging.import_candidate(
                candidate, args.staging, args.evaluation_root, build_id=args.build_id or candidate.runtime.required_build_id,
                acknowledgement=_acknowledgement(args.acknowledgement),
            )  # fmt: skip
        except staging.StagingRefused as exc:
            sys.stderr.write(f"refused: {exc}\n")
            return 1
        except OSError:
            sys.stderr.write("refused: import_io_error\n")
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

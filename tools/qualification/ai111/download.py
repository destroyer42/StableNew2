"""Download-only command for the five authorized PR-AI-111 artifacts.

    python -m tools.qualification.ai111.download --dest <staging dir> --evidence-dir <new dir> --freeze-evidence <freeze dir>

It takes no URL: the identities come from the frozen plan and must equal the freeze evidence. Each artifact is independent
(one failure does not stop the others unless it looks like a common integrity problem). It never unpacks, imports, loads or
executes anything it downloads.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tools.qualification.ai111 import plan as plan_module
from tools.qualification.ai111.artifacts import (
    authorized_artifacts,
    crosscheck_freeze_evidence,
    stage,
)


def _refuse_repository_staging(dest: Path) -> None:
    """Downloaded binaries and weights must never be staged inside any Git working tree (tracked or not)."""

    resolved = dest.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            raise SystemExit(f"Refusing to stage inside a Git working tree: {candidate}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--freeze-evidence", type=Path, required=True)
    parser.add_argument(
        "--only", nargs="*", default=None, help="artifact keys to fetch (default: all five)"
    )
    args = parser.parse_args(argv)
    _refuse_repository_staging(args.dest)
    plan = plan_module.frozen_plan()
    artifacts = authorized_artifacts(plan)
    crosscheck_freeze_evidence(artifacts, args.freeze_evidence)
    if len(artifacts) != 5:
        raise SystemExit("The plan does not name exactly five artifacts")
    keys = {a.key for a in artifacts}
    if args.only is not None and (not args.only or set(args.only) - keys):
        raise SystemExit("Selection must name authorized artifact keys")
    wanted = [a for a in artifacts if args.only is None or a.key in args.only]
    args.evidence_dir.mkdir(
        parents=True
    )  # new directory only: earlier evidence is never overwritten
    results = []
    integrity_failures = 0
    for artifact in wanted:
        result = stage(artifact, args.dest)
        results.append(result)
        with (args.evidence_dir / "download-evidence.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        print(f"{artifact.key}: {result['result']}", flush=True)
        if result["result"] in ("quarantined", "refused") and "SHA" in result.get(
            "reason", ""
        ) + result.get("result", ""):
            integrity_failures += 1
        if integrity_failures >= 2:
            print("Two integrity failures: stopping, this may be a common problem.", flush=True)
            break
    summary = {
        "plan_sha256": plan_module.digest(plan),
        "dest": str(args.dest),
        "results": {r["key"]: r["result"] for r in results},
        "all_verified": all(r.get("verified") for r in results) and len(results) == len(wanted),
    }
    (args.evidence_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if summary["all_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

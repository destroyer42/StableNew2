"""Offline freeze of the PR-AI-111 plan: writes evidence to a NEW directory and does nothing else.

    python -m tools.qualification.ai111 --out <new-evidence-directory>

No network, model, GPU or runtime access; no physical option exists in this command (see ``physical.py``).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from tools.qualification.ai111 import plan as plan_module
from tools.qualification.ai111.corpus import build_corpus, corpus_digest, to_jsonl


def authorization_request(plan: dict, free_bytes: int) -> dict:
    models = plan["models"]
    return {
        "note": "Each item needs a named owner authorization. Nothing here has been downloaded, imported or run.",
        "plan_sha256": plan_module.digest(plan),
        "downloads": [
            {
                "what": "llama.cpp CPU-only Windows runtime",
                "url": plan["runtime_intent"]["source_url"],
                "bytes": plan["runtime_intent"]["bytes"],
                "sha256": plan["runtime_intent"]["sha256"],
                "licence": plan["runtime_intent"]["license"],
            },
            *[
                {
                    "what": m["model_id"],
                    "url": m["source_url"],
                    "bytes": m["bytes"],
                    "sha256": m["sha256"],
                }
                for m in models
            ],
        ],
        "download_bytes_total": plan["asset_bytes"]["runtime"] + plan["asset_bytes"]["models"],
        "disk_note": "Models are copied into an evidence-local AI root on import, so the disk need is about twice the model bytes.",
        "disk_free_bytes_at_freeze": free_bytes,
        "physical_actions": [
            "import runtime and models into an evidence-local AI root",
            "run inference as a contained CPU-only child",
            "sample memory, priority and network connections",
        ],
        "preconditions": [
            "quiet host (no other gates or generation)",
            "owner states the plan digest and stage (A or B)",
            "strict-offline firewall attestation if requested",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True)  # a new destination only: earlier evidence is never overwritten
    plan = plan_module.frozen_plan()
    cases = build_corpus(plan["corpus"]["seed"], plan["corpus"]["counts"])
    (args.out / "plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out / "corpus.jsonl").write_text(to_jsonl(cases), encoding="utf-8")
    free = shutil.disk_usage(args.out).free
    request = authorization_request(plan, free)
    (args.out / "authorization-request.json").write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out / "digests.json").write_text(
        json.dumps(
            {
                "plan_sha256": plan_module.digest(plan),
                "corpus_sha256": corpus_digest(cases),
                "cases": len(cases),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"plan {plan_module.digest(plan)}  corpus {corpus_digest(cases)}  cases {len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Freeze remote AI-111 campaign inputs offline, without authorizing execution."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from tools.qualification.ai111.baselines import ARMS
from tools.qualification.ai111.corpus import corpus_digest, stage_a_subset
from tools.qualification.ai111.final_plan import final_corpus, final_plan
from tools.qualification.ai111.lfm3_contract import QWEN_FROZEN, STAGE_A_CASES, STAGE_A_SEED
from tools.qualification.ai111.plan import digest

STAGES = ("pilot", "full")
MODEL_NAMES = ("qwen3.5:4b-q4_K_M", "lfm3:1.7b")
SHA256 = re.compile(r"[0-9a-f]{64}")


def freeze_inputs(
    stage: str,
    *,
    qwen_manifest_sha256: str,
    lfm_manifest_sha256: str,
    worker_attestation_sha256: str,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError("unknown remote qualification stage")
    hashes = {
        "Qwen Ollama manifest": qwen_manifest_sha256,
        "LFM3 Ollama manifest": lfm_manifest_sha256,
        "worker attestation": worker_attestation_sha256,
    }
    for name, value in hashes.items():
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            raise ValueError(f"{name} requires a full lowercase SHA-256")
    if qwen_manifest_sha256 == lfm_manifest_sha256:
        raise ValueError("model arms require distinct Ollama manifest digests")

    plan = final_plan()
    plan_sha256 = digest(plan)
    cases = final_corpus()
    final_corpus_sha256 = corpus_digest(cases)
    if (
        plan_sha256 != QWEN_FROZEN["final_plan_sha256"]
        or final_corpus_sha256 != QWEN_FROZEN["final_corpus_sha256"]
    ):
        raise ValueError("frozen AI-111 identity changed")
    selected = stage_a_subset(cases, STAGE_A_CASES, STAGE_A_SEED) if stage == "pilot" else cases
    return {
        "schema": "stablenew.ai111.remote-inputs/1",
        "stage": stage,
        "execution_authorized": False,
        "worker_attestation_sha256": worker_attestation_sha256,
        "model_arms": [
            {"name": name, "ollama_manifest_sha256": sha256}
            for name, sha256 in zip(
                MODEL_NAMES, (qwen_manifest_sha256, lfm_manifest_sha256), strict=True
            )
        ],
        "baseline_arms": list(ARMS),
        "final_plan_sha256": plan_sha256,
        "final_corpus_sha256": final_corpus_sha256,
        "selected_corpus_sha256": corpus_digest(selected),
        "case_ids": [case.case_id for case in selected],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--qwen-manifest-sha256", required=True)
    parser.add_argument("--lfm-manifest-sha256", required=True)
    parser.add_argument("--worker-attestation-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        inputs = freeze_inputs(**vars(args))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({"inputs": inputs, "inputs_sha256": digest(inputs)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Versioned final contract, separate from the immutable 215-case screening plan."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from src.video.workflow_catalog import build_builtin_workflow_specs
from tools.qualification.ai111.baselines import policy_for, residual_operations
from tools.qualification.ai111.corpus import Case, build_corpus, corpus_digest, to_jsonl
from tools.qualification.ai111.plan import digest, frozen_plan

COUNTS = {
    "rewrite_sdxl_tags": 50,
    "rewrite_natural": 50,
    "rewrite_tokens": 50,
    "rewrite_weights_for_klein": 50,
    "rewrite_sensitive": 100,
    "target_advice": 60,
    "workflow_choice": 40,
    "adversarial_injection": 40,
    "adversarial_delimiter": 10,
    "adversarial_overlong": 10,
}
MINIMUMS = {
    "prompt_rewrite": 300,
    "target_workflow": 100,
    "adversarial": 60,
    "allowed_sensitive": 100,
    "decisive_blind_judgments": 100,
}


def final_corpus() -> list[Case]:
    cases = build_corpus(11102, COUNTS)
    # Screening labels express generic image/video intent. Freeze final workflow
    # choices against the approved catalog's actual immutable ID/version pairs.
    workflows = sorted(
        (s for s in build_builtin_workflow_specs() if s.governance_state == "approved"),
        key=lambda s: (s.workflow_id, s.workflow_version),
    )
    if not workflows:
        raise ValueError("no approved workflow authority")
    choices = tuple(f"{s.workflow_id}@{s.workflow_version}" for s in workflows)
    selected = choices[-1]
    result = []
    for case in cases:
        if case.kind == "target_fit_advice":
            selected_target = min(
                case.allowed_targets,
                key=lambda target: residual_operations(target, case.positive, case.negative),
            )
            case = replace(
                case,
                oracle=selected_target,
                extra={
                    **case.extra,
                    "oracle_basis": "minimum deterministic policy adaptation operations",
                },
            )
        if case.kind == "workflow_choice":
            case = replace(
                case,
                allowed_workflows=choices,
                oracle=selected,
                extra={
                    **case.extra,
                    "oracle_basis": "approved catalog identity; latest version",
                    "screening_intent": case.oracle,
                },
            )
        result.append(case)
    validate_oracles(result)
    return result


def validate_oracles(cases: list[Case]) -> None:
    catalog = {f"{s.workflow_id}@{s.workflow_version}": s for s in build_builtin_workflow_specs()}
    for case in cases:
        if case.kind == "target_fit_advice":
            for target in case.allowed_targets:
                policy = policy_for(target)
                if not policy.explicit_capabilities:
                    raise ValueError("unresolved deterministic target policy")
            if case.oracle not in case.allowed_targets:
                raise ValueError("target oracle outside deterministic policy set")
            costs = {
                target: residual_operations(target, case.positive, case.negative)
                for target in case.allowed_targets
            }
            if costs[case.oracle] != min(costs.values()):
                raise ValueError("target oracle conflicts with deterministic adaptation policy")
        if case.kind == "workflow_choice":
            for choice in case.allowed_workflows:
                if choice not in catalog or catalog[choice].governance_state != "approved":
                    raise ValueError("workflow oracle lacks approved catalog authority")
            if case.oracle not in case.allowed_workflows:
                raise ValueError("workflow oracle outside approved choices")


def coverage(cases: list[Case]) -> dict[str, int]:
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError("duplicate case identity")
    return {
        "prompt_rewrite": sum(
            c.kind == "prompt_rewrite" and not c.stratum.startswith("adversarial") for c in cases
        ),
        "target_workflow": sum(c.stratum in ("target_advice", "workflow_choice") for c in cases),
        "adversarial": sum(c.stratum.startswith("adversarial") for c in cases),
        "allowed_sensitive": sum(c.lawful_sensitive for c in cases),
    }


def final_plan() -> dict:
    cases = final_corpus()
    return {
        "schema": "stablenew.ai111.final.v2",
        "historical_screening_plan_sha256": digest(frozen_plan()),
        "purpose": "final qualification contract; no execution authorization",
        "corpus_seed": 11102,
        "counts": COUNTS,
        "minimums": MINIMUMS,
        "corpus_sha256": corpus_digest(cases),
        "coverage": coverage(cases),
        "thresholds": frozen_plan()["thresholds"],
        "model_status": {m["model_id"]: "NOT TESTED" for m in frozen_plan()["models"]},
        "physical_qualification": "BLOCKED pending ownership-bound session telemetry and D12b authorization",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    plan = final_plan()
    args.out.mkdir(parents=True)
    (args.out / "plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out / "corpus.jsonl").write_text(to_jsonl(final_corpus()), encoding="utf-8")
    (args.out / "digests.json").write_text(
        json.dumps({"plan_sha256": digest(plan), "corpus_sha256": plan["corpus_sha256"]}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "plan_sha256": digest(plan),
                "corpus_sha256": plan["corpus_sha256"],
                "coverage": plan["coverage"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def evaluate_final_gates(cases, records, *, teardown_verified, preference=None):
    """GO only for the frozen final corpus and measured coverage, never screening."""
    from tools.qualification.ai111.scoring import INFRASTRUCTURE, evaluate_gates, summarize_arm

    rows = list(records)
    if not rows:
        return {"verdict": "NOT TESTED", "unmet": ["physical_qualification"]}
    expected = final_plan()
    if corpus_digest(cases) != expected["corpus_sha256"]:
        return {"verdict": "INCONCLUSIVE", "unmet": ["frozen_final_corpus"]}
    by_id = {c.case_id: c for c in cases}
    if len({r["case_id"] for r in rows}) != len(rows) or any(
        r["case_id"] not in by_id for r in rows
    ):
        return {"verdict": "INCONCLUSIVE", "unmet": ["unique_final_case_records"]}
    completed = [by_id[r["case_id"]] for r in rows if r["outcome"] not in INFRASTRUCTURE]
    observed = coverage(completed)
    missing = [key for key, value in observed.items() if value < MINIMUMS[key]]
    result = evaluate_gates(
        summarize_arm(by_id, rows),
        expected["thresholds"],
        teardown_verified=teardown_verified,
        preference=preference,
    )
    result["unmet"].extend(missing)
    if missing and result["verdict"] == "PASS":
        result["verdict"] = "INCONCLUSIVE"
    if result["verdict"] == "PASS":
        result["verdict"] = "GO"
    result["coverage"] = observed
    return result

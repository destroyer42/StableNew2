"""Contract attribution around the existing Stage A metric and recommendation authority."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from tools.qualification.ai111.capture_evidence import capture_problems, read_json, read_rows
from tools.qualification.ai111.corpus import corpus_digest
from tools.qualification.ai111.execution_contract import ExecutionSpec
from tools.qualification.ai111.execution_evidence import verified_contract_rows
from tools.qualification.ai111.lfm3_contract import record_problems
from tools.qualification.ai111.plan import digest
from tools.qualification.ai111.readiness import d12a_problems, readiness_problems
from tools.qualification.ai111.scoring import summarize_arm


def build_contract_report(
    evidence: Path, spec: ExecutionSpec, d12a: Any, capture: Any, d12a_capture: Any
) -> dict[str, Any]:
    from tools.qualification.ai111.stage_a_report import LIMITATIONS, arm_metrics, judge_arm

    manifest = read_json(evidence / "execution-manifest.json")
    result = read_json(evidence / "result.json")
    rows = read_rows(evidence / "records.jsonl")
    telemetry = read_rows(evidence / "telemetry.jsonl")
    probes = (
        read_rows(evidence / "lifecycle-probes.jsonl")
        if (evidence / "lifecycle-probes.jsonl").exists()
        else []
    )
    integrity = read_rows(evidence / "arm-integrity.jsonl")
    cases = list(spec.cases("A"))
    by_id = {c.case_id: c for c in cases}
    arms = [a for a in manifest.get("arms", []) if a != "B1_engine"]
    problems = []
    if (
        len(arms) != 1
        or manifest.get("stage") != "A"
        or manifest.get("contract_sha256") != spec.sha256
        or manifest.get("corpus_sha256") != corpus_digest(cases)
    ):
        problems.append("Stage A manifest/case/contract mismatch")
    if any(r.get("arm") not in manifest.get("arms", []) for r in rows):
        problems.append("unknown arm records")
    capture_id = manifest.get("capture_id")
    capture_gaps = capture_problems(
        evidence.parent / "capture",
        capture,
        [r for r in rows if r.get("arm") != "B1_engine"] + probes,
        run_id=manifest.get("run_id"),
        capture_id=capture_id,
    )
    problems += capture_gaps
    rows = verified_contract_rows(rows, capture_gaps)
    try:
        from datetime import datetime

        capture_manifest = read_json(evidence.parent / "capture" / "capture.json")
        readiness = dict(manifest.get("readiness_evidence") or {})
        readiness["capture_manifest"] = capture_manifest
        problems += readiness_problems(
            spec,
            "S3_stage_a",
            readiness,
            executable=manifest["executable"],
            now=datetime.fromisoformat(capture_manifest["created_utc"]),
        )
    except (OSError, KeyError, ValueError, TypeError):
        problems.append("Stage A admission evidence missing/malformed")
    models = {}
    for arm in arms:
        arm_spec = spec.arm(arm)
        arm_rows = [r for r in rows if r.get("arm") == arm]
        problems += record_problems(arm_rows, spec.document, arm, list(by_id))
        if [r.get("case_id") for r in arm_rows] != list(by_id):
            problems.append("Stage A ordered cases differ")
        if any(
            any(r.get(k) != v for k, v in arm_spec.identity(manifest["executable"]).items())
            for r in arm_rows
        ):
            problems.append("per-arm identity/sampling mismatch")
        compat = "NOT TESTED"
        if d12a:
            member = d12a.get("members", {}).get(manifest["executable"], {})
            d12a_gaps = d12a_problems(spec, d12a, d12a_capture, manifest["executable"])
            problems += d12a_gaps
            if not d12a_gaps:
                compat = member.get("verdict", "NOT TESTED")
        session = {
            "teardown_verified": result.get("teardown_verified") is True,
            "abort_reason": result.get("abort_reason", "missing session outcome"),
            "violations": result.get("monitoring", {}).get("violations", []),
            "channels_lifetime_complete": not problems,
        }
        safe_rows = [r for r in arm_rows if r.get("case_id") in by_id]
        metrics = arm_metrics(arm, safe_rows, summarize_arm(by_id, safe_rows), by_id, telemetry)
        arm_probes = [p for p in probes if p.get("arm") == arm]
        if Counter(p.get("probe") for p in arm_probes) != Counter({"timeout": 1, "cancel": 1}):
            problems.append("timeout/cancellation lifecycle evidence incomplete")
        before_after = [r for r in integrity if r.get("arm") == arm]
        after = [p for r in before_after for p in r["problems"]]
        if Counter(r.get("phase") for r in before_after) != Counter({"before": 1, "after": 1}):
            problems.append("integrity brackets missing/duplicated")
        judgement = judge_arm(
            metrics,
            thresholds=spec.document["stages"]["thresholds"],
            session=session,
            probes=arm_probes,
            integrity_after=after,
            compatibility_verdict=compat,
        )
        models[arm] = {
            "metrics": metrics,
            "judgement": judgement,
            "quantization": arm_spec.model.quantization,
        }
    if problems:
        for model in models.values():
            model["judgement"]["recommendation"] = "INCONCLUSIVE"
    return {
        "scope": "Stage A screening only; never production GO",
        "stage": "A",
        "contract_sha256": spec.sha256,
        "case_ids_sha256": digest(list(by_id)),
        "capture_id": capture_id,
        "run_id": manifest.get("run_id"),
        "evidence": str(evidence.resolve()),
        "models": models,
        "attribution_problems": sorted(set(problems)),
        "limitations": list(LIMITATIONS),
        "selection_counts": {
            arm: sum(
                r.get("outcome") == "malformed" and r.get("reason") == "protected_tokens_changed"
                for r in rows
                if r.get("arm") == arm
            )
            for arm in arms
        },
        "inputs": {"d12a": d12a, "capture": capture, "d12a_capture": d12a_capture},
    }


def load_selection(paths: list[Path], spec: ExecutionSpec) -> dict[str, Any]:
    reports = []
    for path in paths:
        recorded = read_json(path)
        inputs = recorded["inputs"]
        rebuilt = build_contract_report(
            Path(recorded["evidence"]),
            spec,
            inputs["d12a"],
            inputs["capture"],
            inputs["d12a_capture"],
        )
        if rebuilt != recorded:
            raise ValueError("Stage A report no longer matches its source evidence")
        reports.append(rebuilt)
    return sensitivity_selection(reports, spec)


def sensitivity_selection(reports: list[dict[str, Any]], spec: ExecutionSpec) -> dict[str, Any]:
    required = {a["arm_id"] for a in spec.document["arms"] if a["kind"] != "baseline"}
    models = {}
    counts = {}
    captures = []
    for report in reports:
        if (
            report.get("contract_sha256") != spec.sha256
            or report.get("stage") != "A"
            or report.get("attribution_problems") != []
            or report.get("case_ids_sha256") != digest([c.case_id for c in spec.cases("A")])
        ):
            raise ValueError("Stage A report lacks exact attribution")
        for arm, model in report["models"].items():
            if arm in models:
                raise ValueError("duplicate Stage A arm")
            models[arm] = model
            counts[arm] = report["selection_counts"][arm]
        captures.append(report.get("capture_id"))
    if set(models) != required or None in captures or len(set(captures)) != len(captures):
        raise ValueError("Stage A arms/captures missing, extra or duplicated")
    q4 = "lfm3-1.7b-q4_k_m-liquidai"
    vendor, sensitivity = f"{q4}@lfm3_vendor", f"{q4}@lfm3_no_repeat"
    profile = "lfm3_no_repeat" if counts[vendor] > counts[sensitivity] == 0 else "lfm3_vendor"
    # The exact sensitivity rule may select no-repeat when vendor is inconclusive.
    # Every arm that advances must itself have ADVANCE; the rejected profile is not
    # required to advance, nor may its measurements be pooled into the chosen one.
    selected = [
        a
        for a in models
        if "qwen" in a
        or (a.startswith(q4) and a.endswith("@" + profile))
        or a.startswith("lfm3-1.7b-q8_0")
    ]
    advance = all(models[a]["judgement"]["recommendation"] == "ADVANCE" for a in selected)
    return {
        "stage": "A",
        "contract_sha256": spec.sha256,
        "sampling_profile": profile,
        "advance": advance,
        "protected_token_malformed": counts,
        "reports_sha256": digest(reports),
        "captures": captures,
    }

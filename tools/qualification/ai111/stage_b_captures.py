"""Deterministic Stage B capture planning and offline evidence aggregation. Never executes a process."""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.qualification.ai111.blinding import blinded_view, make_pairs, unblind
from tools.qualification.ai111.capture_evidence import capture_problems, read_json, read_rows
from tools.qualification.ai111.capture_session import (
    RATE_FLOOR_BYTES_PER_SECOND,
    SIZE_WARN_FRACTION,
    STOP_FLUSH_BYTES,
    STOP_MARGIN_SECONDS,
)
from tools.qualification.ai111.corpus import corpus_digest
from tools.qualification.ai111.execution_contract import ExecutionSpec, select_contract
from tools.qualification.ai111.final_plan import final_corpus
from tools.qualification.ai111.lfm3_contract import stage_b_verdict
from tools.qualification.ai111.physical import _baseline_fields, write_new_json
from tools.qualification.ai111.plan import digest
from tools.qualification.ai111.stage_a_contract import load_selection

SCHEMA = "stablenew.ai115.capture-plan.v1"


def selected_arm(spec: ExecutionSpec, arm: str, disposition: dict[str, Any]):
    resolved = spec.arm(arm)
    if resolved.profile.startswith("lfm3_"):
        # Keep the frozen candidate arm identity; the profile is explicitly bound
        # to the preregistered Stage A disposition rather than inferred from its id.
        if not arm.endswith("@lfm3_vendor"):
            raise ValueError("Stage B requires the frozen candidate arm identity")
        resolved = replace(resolved, profile=disposition["sampling_profile"])
    return resolved


def build_plan(
    spec: ExecutionSpec,
    *,
    arms: list[str],
    disposition: dict[str, Any],
    evidence_root: Path,
    plan_id: str,
    cases_per_capture: int,
    approval_reference: str,
    executable: str = "llama-completion.exe",
    stage_a_reports: list[Path] | None = None,
) -> dict[str, Any]:
    if spec.selector != "lfm3-v1" or not re.fullmatch(r"\d{8}T\d{6}Z-[a-z0-9-]{1,20}", plan_id):
        raise ValueError("explicit LFM3 contract and timestamped plan identity required")
    if (
        disposition.get("contract_sha256") != spec.sha256
        or disposition.get("stage") != "A"
        or disposition.get("advance") is not True
        or disposition.get("sampling_profile") not in ("lfm3_vendor", "lfm3_no_repeat")
    ):
        raise ValueError("recorded Stage A ADVANCE/disposition required")
    if (
        len(set(arms)) != len(arms)
        or not arms
        or not approval_reference.strip()
        or not evidence_root.is_absolute()
    ):
        raise ValueError("unique arms, absolute evidence root and S4 approval reference required")
    if type(cases_per_capture) is not int or cases_per_capture < 1:
        raise ValueError("positive capture segment size required")
    timeout = spec.document["limits"]["timeout_seconds"]
    # Reserve two canaries and setup overhead at the worst allowed request
    # timeout, plus the runbook stop margin. Median latency is never a budget.
    overhead_seconds = 180.0
    horizon = cases_per_capture * timeout + overhead_seconds + STOP_MARGIN_SECONDS
    projected = {
        kind: rate * horizon + STOP_FLUSH_BYTES
        for kind, rate in RATE_FLOOR_BYTES_PER_SECOND.items()
    }
    if max(projected.values()) > 1024 * 1024**2 * SIZE_WARN_FRACTION or horizon > 120 * 60:
        raise ValueError("capture size exceeds ETW capacity/deadline budget")
    cases = final_corpus()
    arm_ids = {arm: selected_arm(spec, arm, disposition).identity(executable) for arm in arms}
    segments = []
    for arm in arms:
        for offset in range(0, len(cases), cases_per_capture):
            index = len(segments)
            run_id = f"{plan_id}-{index:03d}"
            capture_id = f"{plan_id[:16]}-{digest([spec.sha256, run_id, arm])[:8]}"
            segments.append(
                {
                    "index": index,
                    "arm": arm,
                    "offset": offset,
                    "case_ids": [c.case_id for c in cases[offset : offset + cases_per_capture]],
                    "run_id": run_id,
                    "capture_id": capture_id,
                    "evidence_root": str(evidence_root / run_id),
                }
            )
    plan = {
        "schema": SCHEMA,
        "contract_sha256": spec.sha256,
        "plan_id": plan_id,
        "arms": arm_ids,
        "stage_a_disposition": disposition,
        "stage_a_reports": [str(p.resolve()) for p in stage_a_reports or []],
        "ordered_case_ids": [c.case_id for c in cases],
        "corpus_sha256": corpus_digest(cases),
        "cases_per_capture": cases_per_capture,
        "segments": segments,
        "evidence_root": str(evidence_root),
        "approval_reference": approval_reference,
        "executable": executable,
        "max_mb_per_session": 1024,
        "capture_minutes": math.ceil(horizon / 60),
        "overhead_seconds": overhead_seconds,
        "request_timeout_seconds": timeout,
        "stop_margin_seconds": STOP_MARGIN_SECONDS,
        "projected_bytes_per_session": projected,
        "cold_policy": "only arm index 1 is cold; each segment first request is also recorded separately",
        "replacement_policy": "no replacement or retry accepted; preserve failed evidence and obtain a separately approved new plan with explicit provenance",
    }
    plan["manifest_sha256"] = digest(plan)
    return plan


def verify_plan(
    plan: dict[str, Any], spec: ExecutionSpec, *, source_evidence: bool = True
) -> list[str]:
    try:
        disposition = (
            load_selection([Path(p) for p in plan["stage_a_reports"]], spec)
            if source_evidence
            else plan["stage_a_disposition"]
        )
        rebuilt = build_plan(
            spec,
            arms=list(plan["arms"]),
            disposition=disposition,
            evidence_root=Path(plan["evidence_root"]),
            plan_id=plan["plan_id"],
            cases_per_capture=plan["cases_per_capture"],
            approval_reference=plan["approval_reference"],
            executable=plan["executable"],
            stage_a_reports=[Path(p) for p in plan["stage_a_reports"]],
        )
        return (
            []
            if rebuilt == plan
            else ["capture plan changed or differs from deterministic reconstruction"]
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"capture plan invalid: {exc}"]


def execution_segment(
    plan: dict[str, Any],
    spec: ExecutionSpec,
    index: int,
    run_id: str,
    root: Path,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    problems = verify_plan(plan, spec)
    if problems:
        raise ValueError("; ".join(problems))
    if index < 0 or index >= len(plan["segments"]):
        raise ValueError("unknown capture segment")
    segment = dict(plan["segments"][index])
    approval = readiness.get("approval_records", {}).get("S4_stage_b", {})
    if approval.get("reference") != plan["approval_reference"] or plan[
        "manifest_sha256"
    ] not in approval.get("text", ""):
        raise ValueError("S4 does not approve this exact capture plan")
    if segment["run_id"] != run_id or Path(segment["evidence_root"]).resolve() != root.resolve():
        raise ValueError("capture segment/run/directory mismatch")
    capture = read_json(root / "capture" / "capture.json")
    if (
        capture.get("capture_id") != segment["capture_id"]
        or capture.get("max_mb_per_session") != plan["max_mb_per_session"]
        or capture.get("minutes") != plan["capture_minutes"]
    ):
        raise ValueError("active capture differs from the approved plan")
    if index:
        previous = plan["segments"][index - 1]
        previous_root = Path(previous["evidence_root"])
        previous_capture = read_json(previous_root / "capture" / "analysis.json")
        previous_rows = read_rows(previous_root / "physical-B" / "records.jsonl")
        previous_result = read_json(previous_root / "physical-B" / "result.json")
        if (
            [r.get("case_id") for r in previous_rows] != previous["case_ids"]
            or previous_result.get("abort_reason") != ""
            or previous_result.get("teardown_verified") is not True
            or capture_problems(
                previous_root / "capture",
                previous_capture,
                previous_rows,
                run_id=previous["run_id"],
                capture_id=previous["capture_id"],
            )
        ):
            raise ValueError("previous capture is not verified stopped and complete")
    segment.update(
        manifest_sha256=plan["manifest_sha256"],
        sampling_profile=plan["arms"][segment["arm"]]["sampling_profile"],
        identity=plan["arms"][segment["arm"]],
    )
    return segment


def _blind(
    cases, rows: list[dict[str, Any]], arm: str, reference: str, ratings: dict[str, str] | None
):
    ids = [c.case_id for c in cases if c.kind == "prompt_rewrite"]
    texts = {
        (r["case_id"], r["arm"]): (r.get("positive") or "") + "\n---\n" + (r.get("negative") or "")
        for r in rows
        if r.get("outcome") == "suggestion"
    }
    pairs = [
        p
        for p in make_pairs(ids, arm, reference, seed=11502)
        if (p["case_id"], arm) in texts and (p["case_id"], reference) in texts
    ]
    if ratings is not None and (
        not set(ratings) <= {p["pair_id"] for p in pairs}
        or any(v not in ("left", "right", "tie") for v in ratings.values())
    ):
        raise ValueError("blind ratings name unknown pairs or choices")
    preference = unblind(pairs, ratings or {}, arm, reference) if ratings is not None else None
    return {
        "operator_view": blinded_view(pairs, texts),
        "private_pair_manifest": pairs,
        "preference": preference,
    }


def aggregate(
    plan: dict[str, Any], *, ratings: dict[str, dict[str, str]] | None = None
) -> dict[str, Any]:
    spec = select_contract("lfm3-v1", plan.get("contract_sha256"))
    problems = verify_plan(plan, spec)
    cases = final_corpus()
    rows_by_arm: dict[str, list[dict[str, Any]]] = {a: [] for a in plan.get("arms", {})}
    captures = []
    previous_stop = None
    for segment in plan.get("segments", []):
        root = Path(segment["evidence_root"])
        try:
            execution = read_json(root / "physical-B" / "execution-manifest.json")
            result = read_json(root / "physical-B" / "result.json")
            rows = read_rows(root / "physical-B" / "records.jsonl")
            probes = (
                read_rows(root / "physical-B" / "lifecycle-probes.jsonl")
                if (root / "physical-B" / "lifecycle-probes.jsonl").exists()
                else []
            )
            analysis = read_json(root / "capture" / "analysis.json")
            capture = read_json(root / "capture" / "capture.json")
            stopped = read_json(root / "capture" / "state-04-stopped.json")
            scoped = [r for r in rows if r.get("arm") == segment["arm"]]
            gaps = capture_problems(
                root / "capture",
                analysis,
                scoped + probes,
                run_id=segment["run_id"],
                capture_id=segment["capture_id"],
            )
            from tools.qualification.ai111.readiness import readiness_problems

            readiness = dict(execution.get("readiness_evidence") or {})
            readiness["capture_manifest"] = capture
            gaps += readiness_problems(
                spec,
                "S4_stage_b",
                readiness,
                executable=plan["executable"],
                now=datetime.fromisoformat(capture["created_utc"]),
            )
            approval = readiness.get("approval_records", {}).get("S4_stage_b", {})
            if approval.get("reference") != plan["approval_reference"] or plan[
                "manifest_sha256"
            ] not in approval.get("text", ""):
                gaps.append("capture lacks independent approval of this manifest")
            if execution.get("lifecycle_probes") is True and {p.get("probe") for p in probes} != {
                "timeout",
                "cancel",
            }:
                gaps.append("capture lifecycle probes incomplete")
            if any(
                p.get("stopped_as_intended") is not True or p.get("teardown_verified") is not True
                for p in probes
            ):
                gaps.append("capture lifecycle probe failed")
            if (
                execution.get("stage") != "B"
                or execution.get("contract_sha256") != spec.sha256
                or execution.get("run_id") != segment["run_id"]
                or execution.get("capture_id") != segment["capture_id"]
            ):
                gaps.append("execution manifest identity mismatch")
            if (
                execution.get("capture_segment", {}).get("manifest_sha256")
                != plan["manifest_sha256"]
            ):
                gaps.append("execution not bound to approved capture plan")
            if result.get("teardown_verified") is not True or result.get("abort_reason") != "":
                gaps.append("capture aborted or teardown ambiguous")
            if [r.get("case_id") for r in scoped] != segment["case_ids"] or len(rows) != len(
                scoped
            ):
                gaps.append("capture case list has missing, extra or mixed records")
            if any(
                any(r.get(k) != v for k, v in plan["arms"][segment["arm"]].items()) for r in scoped
            ):
                gaps.append("runtime/model/member/sampling drift")
            if (
                capture.get("max_mb_per_session") != 1024
                or capture.get("minutes") != plan["capture_minutes"]
            ):
                gaps.append("capture cap differs from plan")
            start, stop = (
                datetime.fromisoformat(capture["created_utc"]),
                datetime.fromisoformat(stopped["stopped_utc"]),
            )
            if previous_stop is not None and start < previous_stop:
                gaps.append("capture overlaps preceding capture")
            previous_stop = stop
            # Chronology is arm-wide; do not reset cold at each segment boundary.
            for local_index, row in enumerate(scoped, start=1):
                wanted = segment["offset"] + local_index
                if (
                    row.get("arm_request_index") != wanted
                    or row.get("phase") != ("cold" if wanted == 1 else "warm")
                    or row.get("capture_request_index") != local_index
                ):
                    gaps.append("cold/warm chronology reset or missing")
            rows_by_arm[segment["arm"]].extend(scoped)
            problems += [f"segment {segment['index']}: {p}" for p in gaps]
            captures.append(
                {
                    "segment": segment,
                    "analysis": str(root / "capture" / "analysis.json"),
                    "records": str(root / "physical-B" / "records.jsonl"),
                    "problems": gaps,
                    "verdict": "PASS" if not gaps else "INCONCLUSIVE",
                }
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problems.append(f"segment {segment['index']}: evidence missing/malformed: {exc}")
    baseline = [
        {
            "case_id": c.case_id,
            "arm": "B1_engine",
            "outcome": "suggestion",
            **_baseline_fields("B1_engine", c),
        }
        for c in cases
    ]
    all_rows = baseline + [r for rows in rows_by_arm.values() for r in rows]
    verdicts, blind = {}, {}
    for arm, rows in rows_by_arm.items():
        ids = [r.get("case_id") for r in rows]
        if ids != [c.case_id for c in cases]:
            problems.append(f"{arm}: exact ordered 460-case coverage absent")
        blind[arm] = _blind(cases, all_rows, arm, "B1_engine", (ratings or {}).get(arm))
        verdicts[arm] = stage_b_verdict(
            rows,
            spec.document,
            arm,
            cases,
            teardown_verified=not problems,
            preference=blind[arm]["preference"],
            capture_verdicts=[c["verdict"] for c in captures],
            stage_a_disposition=plan["stage_a_disposition"],
        )
        judgments = (ratings or {}).get(arm)
        if judgments is None or set(judgments) != {
            p["pair_id"] for p in blind[arm]["private_pair_manifest"]
        }:
            verdicts[arm]["unmet"] = [*verdicts[arm].get("unmet", []), "complete_blind_judgments"]
            if verdicts[arm]["verdict"] == "GO":
                verdicts[arm]["verdict"] = "INCONCLUSIVE"
    comparisons = {}
    for arm in rows_by_arm:
        definition = next(a for a in spec.document["arms"] if a["arm_id"] == arm)
        reference = definition.get("matched_comparator")
        if reference in rows_by_arm:
            key = f"{arm} versus {reference}"
            comparisons[key] = _blind(cases, all_rows, arm, reference, (ratings or {}).get(key))
    if problems:
        for verdict in verdicts.values():
            verdict["verdict"] = "INCONCLUSIVE"
    return {
        "schema": "stablenew.ai115.aggregate.v1",
        "contract_sha256": spec.sha256,
        "manifest_sha256": plan.get("manifest_sha256"),
        "problems": sorted(set(problems)),
        "captures": captures,
        "arms": verdicts,
        "blind": blind,
        "matched_qwen_preference_not_a_gate": comparisons,
        "records": rows_by_arm,
        "stage": "B",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("plan")
    prep.add_argument("--stage-a-report", type=Path, action="append", required=True)
    prep.add_argument("--arms", nargs="+", required=True)
    prep.add_argument("--evidence-root", type=Path, required=True)
    prep.add_argument("--plan-id", required=True)
    prep.add_argument("--cases-per-capture", type=int, required=True)
    prep.add_argument("--approval-reference", required=True)
    prep.add_argument("--executable", default="llama-completion.exe")
    agg = sub.add_parser("aggregate")
    agg.add_argument("--manifest", type=Path, required=True)
    agg.add_argument("--ratings", type=Path)
    for command in (prep, agg):
        command.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "plan":
        spec = select_contract("lfm3-v1")
        result = build_plan(
            spec,
            arms=args.arms,
            disposition=load_selection(args.stage_a_report, spec),
            evidence_root=args.evidence_root,
            plan_id=args.plan_id,
            cases_per_capture=args.cases_per_capture,
            approval_reference=args.approval_reference,
            executable=args.executable,
            stage_a_reports=args.stage_a_report,
        )
    else:
        result = aggregate(
            read_json(args.manifest), ratings=read_json(args.ratings) if args.ratings else None
        )
    write_new_json(args.out, result)
    if args.command == "aggregate":
        # The evaluator receives only these files. The aggregate/pair manifests
        # are private operator evidence and must not be shown during judging.
        for comparison, data in {
            **result["blind"],
            **result["matched_qwen_preference_not_a_gate"],
        }.items():
            label = digest([result["manifest_sha256"], comparison])[:12]
            write_new_json(args.out.with_name(f"blind-{label}.json"), data["operator_view"])
    return 1 if result.get("problems") else 0


if __name__ == "__main__":
    raise SystemExit(main())

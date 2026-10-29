"""Frozen Research -> selection -> compiled -> dispatch -> reported comparison."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.generation_profiles.contract import SETTING_KEYS
from src.learning.experiment_execution import thaw_snapshot
from src.learning.variable_metadata import get_variable_metadata
from src.pipeline.backend_setting_evidence import setting_values


def compare_settings(
    snapshot: Mapping[str, Any], variant: Any, dispatched: Any = None, reported: Any = None
) -> list[dict[str, Any]]:
    selected = snapshot.get("baseline_config", {}).get("txt2img", {})
    compiled = (getattr(variant, "executed_config", {}) or {}).get("txt2img", {})
    coverage = {r["field"]: r for r in snapshot.get("evidence_proposal", {}).get("coverage", [])}
    meta = get_variable_metadata(snapshot.get("variable_under_test", ""))
    tested_key = meta.config_path.split(".")[-1] if meta else ""
    dispatched, reported = setting_values(dispatched), setting_values(reported)
    rows = []
    for key in SETTING_KEYS:
        tested = key == tested_key
        intended = getattr(variant, "param_value", None) if tested else selected.get(key)
        row = coverage.get(key, {})
        status = "conflicting evidence" if row.get("status") == "conflicting" else "not recorded"
        if key in compiled and compiled[key] != intended:
            status = "changed by compiler/policy"
        elif key in dispatched and dispatched[key] != compiled.get(key):
            status = "conflicting evidence"
        elif key in reported:
            status = (
                "matched"
                if reported[key] == intended and compiled.get(key) == intended
                else "conflicting evidence"
            )
        rows.append(
            {
                "field": key,
                "tested": tested,
                "research": row.get("claims", []),
                "research_status": row.get("status", "unavailable"),
                "selected": intended,
                "compiled_njr": compiled.get(key),
                "dispatched_request": dispatched.get(key),
                "backend_reported": reported.get(key),
                "status": status,
            }
        )
    return rows


def completion_evidence(
    snapshot: Mapping[str, Any],
    variant: Any,
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    if not snapshot.get("evidence_proposal"):
        return {}
    rows = compare_settings(
        snapshot,
        variant,
        payload.get("dispatched_settings", metadata.get("dispatched_settings")),
        payload.get("backend_reported_settings", metadata.get("backend_reported_settings")),
    )
    valid = all(row["status"] == "matched" for row in rows if row["tested"])
    return {
        "qualification_setting_evidence": rows,
        "qualification_tested_value_verified": valid,
        "qualification_proposal": {
            k: snapshot["evidence_proposal"][k]
            for k in ("proposal_id", "hypothesis", "rubric", "decision_criteria")
        },
    }


def rating_metadata(snapshot: Mapping[str, Any], variant: Any) -> dict[str, Any]:
    if not snapshot.get("evidence_proposal"):
        return {}
    metadata = getattr(variant, "execution_metadata", {}) or {}
    return {
        key: metadata.get(key)
        for key in ("qualification_setting_evidence", "qualification_tested_value_verified")
    }


def require_rating_proof(metadata: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    if not snapshot.get("evidence_proposal"):
        return
    meta = get_variable_metadata(snapshot.get("variable_under_test", ""))
    key = meta.config_path.split(".")[-1] if meta else ""
    rows = metadata.get("qualification_setting_evidence")
    tested = (
        [row for row in rows if isinstance(row, dict) and row.get("tested")]
        if isinstance(rows, list)
        else []
    )
    if metadata.get("qualification_tested_value_verified") is not True or len(tested) != 1:
        raise ValueError("Qualification proposal lacks backend-reported tested-value proof")
    row = tested[0]
    expected = metadata.get("variant_value")
    if (
        row.get("field") != key
        or row.get("status") != "matched"
        or any(row.get(k) != expected for k in ("selected", "compiled_njr", "backend_reported"))
    ):
        raise ValueError("Qualification tested-setting evidence conflicts with its rating")


SCREENING_PAIRS = 6
SCREENING_MIN_WINS = 5
SCREENING_MIN_MEAN_IMPROVEMENT = 0.5


def screening_supported(paired: list[float]) -> bool:
    """The six-pair screening rule: it supports follow-up investigation only, never a general claim."""
    return (
        len(paired) == SCREENING_PAIRS
        and sum(delta > 0 for delta in paired) >= SCREENING_MIN_WINS
        and sum(paired) / SCREENING_PAIRS >= SCREENING_MIN_MEAN_IMPROVEMENT
    )


def inspect_experiment(
    experiment: Any, plan: list[Any], ratings: Mapping[str, Any]
) -> dict[str, Any]:
    snapshot = (
        thaw_snapshot(experiment.execution_snapshot_json)
        if experiment.execution_snapshot_json
        else {}
    )
    proposal = snapshot.get("evidence_proposal") or experiment.metadata.get("evidence_proposal")
    if not proposal:
        return {"message": "No frozen catalog provenance exists for this historical experiment."}
    evidence = [
        {
            "value": v.param_value,
            "status": v.status,
            "settings": (v.execution_metadata or {}).get("qualification_setting_evidence")
            or compare_settings(snapshot, v),
            "actual_seeds": (v.execution_metadata or {}).get("actual_all_seeds", []),
            "controlled": (v.execution_metadata or {}).get("controlled_evidence_valid") is True,
        }
        for v in plan
    ]
    from src.learning.qualification_review import project_qualification

    findings = project_qualification(experiment, plan, ratings)
    comparison = findings.comparisons[0] if len(findings.comparisons) == 1 else None
    paired = list(comparison.differences) if comparison else []
    mean = comparison.mean_difference if comparison else None
    supported = findings.outcome == "Follow-up supported"
    return {
        "proposal": proposal,
        "variants": evidence,
        "saved_ratings": len(ratings),
        "exclusions": findings.exclusions,
        "paired_differences": paired,
        "mean_improvement": mean,
        "conclusion": "Follow-up investigation supported; not statistical proof."
        if supported
        else "Inconclusive or insufficient verified paired evidence.",
        "backend_caveat": "Backend-reported settings are readback, not proof of physical quality. Outbound requests are separate evidence.",
    }

"""Exact admitted Learning identity and repository evidence projections; never dispatches."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.learning.experiment_execution import freeze_snapshot, snapshot_digest, thaw_snapshot
from src.learning.experiment_freeze import normalize_actual_seed_vector, seed_vector_matches
from src.learning.lora_variant import validate_executed_lora
from src.pipeline.artifact_contract import extract_artifact_paths
from src.pipeline.njr_core_v26 import thaw_json

_logger = logging.getLogger(__name__)

TERMINAL = frozenset({"completed", "uncontrolled", "failed", "cancelled"})


@dataclass(frozen=True)
class JobEvidence:
    job: Any = None
    error: str = ""
    absent: bool = False
    executed_config: dict[str, Any] = field(default_factory=dict)


def read_job_evidence(repository: Any, experiment: Any, variant: Any) -> JobEvidence:
    """An exact lookup, never a history scan or a match on mutable display fields."""
    if not variant.job_id:
        return JobEvidence(error="Saved admitted variant has no job ID; no automatic retry.")
    lookup = getattr(repository, "get_job_model", None)
    if not callable(lookup):
        return JobEvidence(error="Job repository unavailable; reconciliation requires attention.")
    try:
        job = lookup(variant.job_id)
    except Exception as exc:
        _logger.exception("Cannot reconcile recorded Learning job %s", variant.job_id)
        return JobEvidence(error=f"Cannot read recorded job {variant.job_id}: {exc}")
    if job is None:
        return JobEvidence(error=f"Recorded job {variant.job_id} is missing.", absent=True)
    try:
        record = job._normalized_record
        context = record.learning_context
        metadata = record.extra_metadata
        learning, frozen = metadata["learning"], metadata["frozen_experiment"]
        workload_metadata = thaw_json(record.workload.metadata)
        for key in ("learning", "frozen_experiment"):
            if workload_metadata.get(key) != metadata[key]:
                raise ValueError("immutable workload and provenance Learning evidence conflict")
        experiment_id, variant_id = (
            str(experiment.experiment_id or ""),
            str(variant.variant_id or ""),
        )
        if not experiment_id or not variant_id or variant.experiment_id != experiment_id:
            raise ValueError("saved experiment/variant identity is missing or conflicting")
        if job.job_id != variant.job_id or record.job_id != variant.job_id:
            raise ValueError("recorded job ID disagrees with immutable NJR")
        if record.source.kind.value != "learning" or context.experiment_id != experiment_id:
            raise ValueError("immutable NJR belongs to another experiment")
        for identity in (learning, frozen):
            if identity["experiment_id"] != experiment_id or identity["variant_id"] != variant_id:
                raise ValueError("immutable NJR experiment/variant conflicts with saved plan")
        if (
            context.variant_value != variant.param_value
            or learning["variant_value"] != variant.param_value
        ):
            raise ValueError("immutable NJR variant value conflicts with saved plan")
        snapshot = str(experiment.execution_snapshot_json or "")
        if not snapshot or frozen["snapshot_sha256"] != snapshot_digest(snapshot):
            raise ValueError("saved preview conflicts with immutable NJR snapshot")
        if snapshot_digest(freeze_snapshot(frozen["snapshot"])) != frozen["snapshot_sha256"]:
            raise ValueError("immutable Learning snapshot digest is invalid")
        config = frozen["executed_config"]
        if not isinstance(config, dict):
            raise ValueError("immutable execution configuration unavailable")
        return JobEvidence(job=job, executed_config=copy.deepcopy(config))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return JobEvidence(error=f"Job {variant.job_id} Learning evidence unresolved: {exc}")


def completion_result(job: Any) -> dict[str, Any]:
    """Retain the existing readback at live and restored completion boundaries."""
    raw = getattr(job, "result", None)
    result = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    variants = result.get("variants")
    variants = variants if isinstance(variants, list) else []

    def paths_from(payload: dict[str, Any]) -> list[str]:
        try:
            return extract_artifact_paths(payload)
        except (TypeError, ValueError, AttributeError) as exc:
            # Keep other recorded artifact associations, while rejecting this
            # malformed completion as controlled execution evidence.
            result["completion_readback_error"] = f"Malformed artifact readback: {exc}"
            return []

    paths = paths_from(result)
    for key in ("images", "image_paths"):
        if isinstance(result.get(key), list):
            paths.extend(str(path) for path in result[key] if path)
    if isinstance(result.get("outputs"), list):
        for payload in result["outputs"]:
            if isinstance(payload, dict):
                paths.extend(paths_from(payload))
    for payload in variants:
        if isinstance(payload, dict):
            paths.extend(paths_from(payload))
    paths = list(dict.fromkeys(str(path) for path in paths if path))
    result.update(status="completed", images=paths, output_paths=paths)
    if variants and isinstance(variants[0], dict):
        for key in (
            "requested_seed",
            "actual_seed",
            "all_seeds",
            "requested_subseed",
            "actual_subseed",
            "all_subseeds",
            "subseed_strength",
        ):
            if key not in result and key in variants[0]:
                result[key] = variants[0][key]
    return result


@dataclass(frozen=True)
class CompletionEvidence:
    status: str
    execution_metadata: dict[str, Any]
    experiment_metadata: dict[str, Any] | None


def mark_completion_unavailable(variant: Any, message: str) -> None:
    """A rejected interpretation keeps artifacts, never provisional execution facts."""
    variant.status = "uncontrolled"
    variant.execution_metadata.update(
        controlled_evidence_valid=False,
        actual_all_seeds=[],
        actual_all_subseeds=[],
        runtime_prompt_readback={},
        runtime_launch_profile="",
        seed_validation_reason="seed_readback_unavailable",
        variable_validation_reason="completion_readback_unavailable",
        reconciliation_error=message,
        action_required=True,
    )


def validate_completion_readback(result: dict[str, Any]) -> None:
    """Validate optional structured fields without changing valid legacy readback rules."""
    if result.get("completion_readback_error"):
        raise ValueError(str(result["completion_readback_error"]))
    metadata = result.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("completion metadata must be an object")
    variants = result.get("variants")
    if variants is not None and not isinstance(variants, list):
        raise ValueError("completion variants must be a list")
    sources = [metadata or {}]
    for payload in variants or []:
        if not isinstance(payload, dict):
            raise ValueError("completion variant must be an object")
        admission = payload.get("runtime_admission")
        if admission is not None and not isinstance(admission, dict):
            raise ValueError("runtime admission readback must be an object")
        profile = (admission or {}).get("launch_profile")
        if profile is not None and not isinstance(profile, str):
            raise ValueError("runtime launch profile readback must be text")
        sources.append(payload)
    for source in sources:
        for key in ("final_prompt", "final_negative_prompt"):
            if source.get(key) is not None and not isinstance(source[key], str):
                raise ValueError(f"{key} execution readback must be text")


def completion_evidence(
    experiment: Any, variant: Any, result: dict[str, Any]
) -> CompletionEvidence:
    """Interpret on disposable copies; publish comparison boundaries only after validation."""
    candidate = copy.deepcopy(variant)
    candidate_experiment = copy.deepcopy(experiment)
    try:
        validate_completion_readback(result)
        _interpret_completion_evidence(candidate, candidate_experiment, result)
    except Exception as exc:
        _logger.exception("Learning completion evidence is unavailable for %s", variant.job_id)
        candidate.execution_metadata = copy.deepcopy(variant.execution_metadata)
        mark_completion_unavailable(candidate, f"Completion evidence unavailable: {exc}")
        candidate_experiment = experiment
    return CompletionEvidence(
        candidate.status,
        copy.deepcopy(candidate.execution_metadata),
        copy.deepcopy(candidate_experiment.metadata) if candidate_experiment is not None else None,
    )


def _interpret_completion_evidence(variant: Any, experiment: Any, result: dict[str, Any]) -> None:
    variant.status = "completed"

    snapshot_json = str(getattr(experiment, "execution_snapshot_json", "") or "")
    snapshot = thaw_snapshot(snapshot_json) if snapshot_json else {}
    policy = snapshot.get("seed_policy") if isinstance(snapshot, dict) else None
    metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    variant_payloads = result.get("variants") if isinstance(result, dict) else None
    variant_payload = (
        next((item for item in variant_payloads if isinstance(item, dict)), {})
        if isinstance(variant_payloads, list)
        else {}
    )
    actual_seeds = (
        (result.get("all_seeds") if isinstance(result, dict) else None)
        or metadata.get("all_seeds")
        or metadata.get("actual_seed_vector")
        or variant_payload.get("all_seeds")
    )
    actual_subseeds = (
        (result.get("all_subseeds") if isinstance(result, dict) else None)
        or metadata.get("all_subseeds")
        or metadata.get("actual_subseed_vector")
        or variant_payload.get("all_subseeds")
    )
    actual_vector = normalize_actual_seed_vector(actual_seeds)
    actual_subseed_vector = normalize_actual_seed_vector(actual_subseeds)
    sample_count = int((policy or {}).get("requested_sample_count", 0) or 0)
    observed = dict(getattr(experiment, "metadata", {}) or {})
    observed_vector = normalize_actual_seed_vector(observed.get("observed_seed_vector"))
    controlled = False
    reason = "seed_readback_unavailable"
    subseed_strength = float((policy or {}).get("subseed_strength", 0.0) or 0.0)
    has_seed_policy = isinstance(policy, dict) and bool(policy)
    if has_seed_policy and actual_vector:
        if len(actual_vector) != sample_count:
            reason = "seed_vector_mismatch"
        elif subseed_strength > 0 and not actual_subseed_vector:
            reason = "seed_readback_unavailable"
        elif not observed_vector:
            observed["observed_seed_vector"] = actual_vector
            if subseed_strength > 0:
                observed["observed_subseed_vector"] = actual_subseed_vector
            experiment.metadata = observed
            controlled = True
            reason = ""
        else:
            comparable = {
                **(policy or {}),
                "observed_seed_vector": observed_vector,
                "observed_subseed_vector": observed.get("observed_subseed_vector", []),
            }
            controlled = seed_vector_matches(comparable, actual_vector, actual_subseed_vector)
            reason = "" if controlled else "seed_vector_mismatch"
    # The tested variable must also have executed as requested, and every
    # comparable variant must have run in the same backend launch profile.
    from src.learning.model_comparison import runtime_prompt_readback

    prompt_readback = runtime_prompt_readback(variant_payload, metadata)
    final_prompt = variant_payload.get("final_prompt") or metadata.get("final_prompt")
    variable_reason = validate_executed_lora(
        getattr(variant, "executed_config", None), final_prompt
    )
    from src.learning.prompt_slot_experiment import prompt_readback_reason

    variable_reason = variable_reason or prompt_readback_reason(snapshot, variant, prompt_readback)
    launch_profile = str(
        (variant_payload.get("runtime_admission") or {}).get("launch_profile") or ""
    )
    observed_profile = str(observed.get("observed_launch_profile") or "")
    if launch_profile and not observed_profile:
        observed["observed_launch_profile"] = launch_profile
        experiment.metadata = observed
    elif launch_profile and launch_profile != observed_profile:
        variable_reason = variable_reason or "backend_restart_boundary"
    if variable_reason:
        reason = reason if not controlled else variable_reason
        controlled = False
    variant.execution_metadata = {
        **dict(getattr(variant, "execution_metadata", {}) or {}),
        "variable_validation_reason": variable_reason or "valid",
        "executed_final_prompt": str(final_prompt or ""),
        "runtime_prompt_readback": prompt_readback,
        "runtime_launch_profile": launch_profile,
        "requested_seed_policy": dict(policy or {}),
        "actual_all_seeds": actual_vector,
        "actual_all_subseeds": actual_subseed_vector,
        "controlled_evidence_valid": controlled,
        "seed_validation_reason": reason or "valid",
        "requested_seed": (policy or {}).get("requested_base_seed"),
        "requested_sample_count": sample_count,
        "observed_seed_vector": observed_vector or (actual_vector if controlled else []),
    }
    if not has_seed_policy and not variable_reason:
        _logger.debug(
            "Learning seed validation skipped: no frozen policy for experiment=%s",
            getattr(experiment, "experiment_id", ""),
        )
    elif not controlled:
        variant.status = "uncontrolled"
        _logger.error(
            "Learning seed validation: experiment=%s variant=%s requested=%s actual=%s observed=%s controlled=False reason=%s",
            getattr(experiment, "experiment_id", ""),
            variant.variant_id,
            (policy or {}).get("requested_base_seed"),
            actual_vector,
            observed_vector,
            reason,
        )
    else:
        _logger.info(
            "Learning seed validation: experiment=%s variant=%s requested=%s actual=%s observed=%s controlled=True",
            getattr(experiment, "experiment_id", ""),
            variant.variant_id,
            (policy or {}).get("requested_base_seed"),
            actual_vector,
            observed_vector or actual_vector,
        )


def unresolved(variant: Any, message: str) -> None:
    if variant.status != "uncontrolled":
        variant.status = "requires_attention"
    variant.execution_metadata.update(
        reconciliation_error=message, action_required=True, controlled_evidence_valid=False
    )


def project_status(variant: Any, job: Any) -> str:
    status = str(getattr(job.status, "value", job.status))
    variant.execution_metadata.pop("reconciliation_error", None)
    variant.execution_metadata.pop("action_required", None)
    variant.execution_metadata["repository_status"] = status
    error = str(getattr(job, "error_message", "") or "")
    envelope = getattr(job, "error_envelope", None)
    if error:
        variant.execution_metadata["job_error"] = error
    if envelope is not None and getattr(envelope, "context", {}).get("action_required"):
        variant.execution_metadata.update(
            action_required=True, recovery_identifier=envelope.error_type
        )
    if status != "completed":
        variant.status = status
    return status


def note_missing_artifacts(variant: Any) -> None:
    missing = [str(path) for path in variant.image_refs if not Path(path).is_file()]
    if missing:
        variant.execution_metadata.update(missing_output_paths=missing, action_required=True)
    else:
        variant.execution_metadata.pop("missing_output_paths", None)


def reconciliation_summary(plan: list[Any]) -> str:
    counts = {
        status: sum(v.status == status for v in plan)
        for status in ("completed", "uncontrolled", "queued", "running", "failed", "cancelled")
    }
    attention = sum(
        v.status == "requires_attention"
        or bool(
            v.execution_metadata.get("action_required")
            or v.execution_metadata.get("admission_error")
        )
        for v in plan
    )
    parts = [f"{count} {status}" for status, count in counts.items() if count]
    if attention:
        parts.append(f"{attention} requires attention")
    return ", ".join(parts)


def variant_status_detail(variant: Any) -> str:
    metadata = variant.execution_metadata
    detail = (
        metadata.get("reconciliation_error")
        or metadata.get("job_error")
        or metadata.get("completion_presentation_error")
        or ""
    )
    if metadata.get("missing_output_paths"):
        detail = f"{detail}; output file unavailable".strip("; ")
    return str(metadata.get("admission_error") or detail)


def preserve_observed_state(previous: Any, restored: Any) -> None:
    """An old saved payload must not erase newer completion comparison boundaries."""
    if previous is None or restored is None:
        return
    if (
        previous.experiment_id != restored.experiment_id
        or previous.execution_snapshot_json != restored.execution_snapshot_json
    ):
        return
    for key in ("observed_seed_vector", "observed_subseed_vector", "observed_launch_profile"):
        if key in previous.metadata:
            restored.metadata[key] = copy.deepcopy(previous.metadata[key])

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.pipeline.artifact_contract import (
    build_artifact_record,
    canonicalize_variant_entries,
    extract_artifact_paths,
    infer_artifact_type,
)

REPLAY_DESCRIPTOR_SCHEMA_VERSION = "stablenew.replay-descriptor.v2.6"
DIAGNOSTICS_DESCRIPTOR_SCHEMA_VERSION = "stablenew.diagnostics-descriptor.v2.6"


def _result_metadata(result: Mapping[str, Any] | None) -> dict[str, Any]:
    metadata = (result or {}).get("metadata")
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _iter_video_artifact_aggregates(metadata: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    data = dict(metadata or {})
    aggregates: list[dict[str, Any]] = []

    primary_artifact = data.get("video_primary_artifact")
    if isinstance(primary_artifact, Mapping):
        aggregates.append(dict(primary_artifact))

    video_artifacts = data.get("video_artifacts")
    if isinstance(video_artifacts, Mapping):
        for aggregate in video_artifacts.values():
            if isinstance(aggregate, Mapping):
                aggregates.append(dict(aggregate))

    video_backend_results = data.get("video_backend_results")
    if isinstance(video_backend_results, Mapping):
        for aggregate in video_backend_results.values():
            if isinstance(aggregate, Mapping):
                aggregates.append(dict(aggregate))

    for key in ("svd_native_artifact", "animatediff_artifact"):
        aggregate = data.get(key)
        if isinstance(aggregate, Mapping):
            aggregates.append(dict(aggregate))

    return aggregates


def _artifact_from_aggregate(aggregate: Mapping[str, Any] | None) -> dict[str, Any]:
    data = dict(aggregate or {})
    artifacts = data.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, Mapping):
                return dict(artifact)

    output_paths = data.get("output_paths")
    if not isinstance(output_paths, list):
        output_paths = data.get("video_paths")
    manifest_paths = data.get("manifest_paths")
    manifest_path = None
    if isinstance(manifest_paths, list) and manifest_paths:
        manifest_path = manifest_paths[0]

    primary_path = data.get("primary_path")
    if primary_path or output_paths:
        stage_name = str(data.get("stage") or "unknown")
        return build_artifact_record(
            stage=stage_name,
            artifact_type=str(data.get("artifact_type") or "video"),
            primary_path=str(primary_path) if primary_path else None,
            output_paths=output_paths if isinstance(output_paths, list) else [],
            manifest_path=str(manifest_path) if manifest_path else None,
            thumbnail_path=str(data.get("thumbnail_path")) if data.get("thumbnail_path") else None,
            input_image_path=str(data.get("input_image_path")) if data.get("input_image_path") else None,
        )
    return {}


def _normalized_stage_name(value: Any) -> str:
    stage_name = str(value or "").strip()
    return "" if not stage_name or stage_name == "unknown" else stage_name


def collect_canonical_artifacts(result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(result, Mapping):
        return []

    seen: set[tuple[str, str, str, str]] = set()
    artifacts: list[dict[str, Any]] = []

    def _append(artifact: Mapping[str, Any] | None) -> None:
        if not isinstance(artifact, Mapping):
            return
        item = dict(artifact)
        stage = str(item.get("stage") or "")
        artifact_type = str(item.get("artifact_type") or "")
        primary_path = str(item.get("primary_path") or "")
        manifest_path = str(item.get("manifest_path") or "")
        key = (stage, artifact_type, primary_path, manifest_path)
        if key in seen:
            return
        seen.add(key)
        artifacts.append(item)

    direct_artifact = result.get("artifact")
    if isinstance(direct_artifact, Mapping):
        _append(direct_artifact)

    metadata = _result_metadata(result)
    for aggregate in _iter_video_artifact_aggregates(metadata):
        _append(_artifact_from_aggregate(aggregate))

    for variant in canonicalize_variant_entries(result.get("variants") or []):
        _append(variant.get("artifact"))

    return artifacts


def extract_primary_artifact(result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}

    direct_artifact = result.get("artifact")
    if isinstance(direct_artifact, Mapping):
        return dict(direct_artifact)

    metadata = _result_metadata(result)
    primary_video = metadata.get("video_primary_artifact")
    if isinstance(primary_video, Mapping):
        artifact = _artifact_from_aggregate(primary_video)
        if artifact:
            return artifact

    artifacts = collect_canonical_artifacts(result)
    if artifacts:
        return dict(artifacts[0])

    return {}


def collect_backend_descriptors(result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(result, Mapping):
        return []

    descriptors_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    metadata = _result_metadata(result)

    backend_results = metadata.get("video_backend_results")
    if isinstance(backend_results, Mapping):
        for stage_name, aggregate in backend_results.items():
            if not isinstance(aggregate, Mapping):
                continue
            backend_id = str(aggregate.get("backend_id") or "")
            key = (_normalized_stage_name(stage_name), backend_id)
            descriptors_by_key[key] = {
                "stage": _normalized_stage_name(stage_name),
                "backend_id": backend_id,
                "count": int(aggregate.get("count") or 0),
                "primary_path": aggregate.get("primary_path"),
                "workflow_id": None,
                "workflow_version": None,
            }

    for variant in canonicalize_variant_entries(result.get("variants") or []):
        backend_id = str(variant.get("video_backend_id") or "").strip()
        if not backend_id:
            continue
        replay_manifest = variant.get("video_replay_manifest")
        workflow_id = ""
        workflow_version = ""
        if isinstance(replay_manifest, Mapping):
            workflow_id = str(replay_manifest.get("workflow_id") or "")
            workflow_version = str(replay_manifest.get("workflow_version") or "")
        stage_name = _normalized_stage_name(variant.get("stage"))
        key = (stage_name, backend_id)
        existing = descriptors_by_key.get(key, {"stage": stage_name, "backend_id": backend_id})
        existing.setdefault("count", 0)
        existing.setdefault("primary_path", variant.get("output_path") or variant.get("path"))
        if workflow_id:
            existing["workflow_id"] = workflow_id
        else:
            existing.setdefault("workflow_id", None)
        if workflow_version:
            existing["workflow_version"] = workflow_version
        else:
            existing.setdefault("workflow_version", None)
        descriptors_by_key[key] = existing

    return list(descriptors_by_key.values())


def _collect_stage_types(result: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(result, Mapping):
        return []

    stage_plan = result.get("stage_plan")
    if isinstance(stage_plan, Mapping):
        enabled_stages = stage_plan.get("enabled_stages")
        if isinstance(enabled_stages, list):
            return [str(stage) for stage in enabled_stages if stage]
        stage_types = stage_plan.get("stage_types")
        if isinstance(stage_types, list):
            return [str(stage) for stage in stage_types if stage]

    seen: set[str] = set()
    stage_types: list[str] = []
    for event in result.get("stage_events") or []:
        if not isinstance(event, Mapping):
            continue
        stage_name = str(event.get("stage") or "").strip()
        if not stage_name or stage_name in seen:
            continue
        seen.add(stage_name)
        stage_types.append(stage_name)
    return stage_types


def build_replay_descriptor(
    result: Mapping[str, Any] | None,
    *,
    njr_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}

    metadata = _result_metadata(result)
    primary_artifact = extract_primary_artifact(result)
    backends = collect_backend_descriptors(result)
    snapshot = dict(njr_snapshot or {})
    normalized_job = snapshot.get("normalized_job")
    if isinstance(normalized_job, Mapping):
        snapshot = dict(normalized_job)

    stage_types = _collect_stage_types(result)
    artifact_type = str(
        primary_artifact.get("artifact_type")
        or infer_artifact_type(
            str(primary_artifact.get("stage") or ""),
            {"path": primary_artifact.get("primary_path")},
        )
    )
    primary_paths = extract_artifact_paths({"artifact": primary_artifact}) if primary_artifact else []

    return {
        "schema": REPLAY_DESCRIPTOR_SCHEMA_VERSION,
        "mode": "njr",
        "job_id": str(snapshot.get("job_id") or ""),
        "run_id": str(result.get("run_id") or ""),
        "artifact_type": artifact_type,
        "output_dir": result.get("output_dir") or metadata.get("output_dir"),
        "primary_stage": (
            _normalized_stage_name(primary_artifact.get("stage"))
            or _normalized_stage_name(metadata.get("video_primary_stage"))
            or (stage_types[0] if stage_types else "")
        ),
        "primary_path": primary_artifact.get("primary_path"),
        "manifest_path": primary_artifact.get("manifest_path"),
        "artifact_count": len(collect_canonical_artifacts(result)),
        "variant_count": len(canonicalize_variant_entries(result.get("variants") or [])),
        "stage_types": stage_types,
        "primary_artifact": dict(primary_artifact or {}),
        "primary_output_paths": list(primary_paths),
        "backends": backends,
    }


def build_diagnostics_descriptor(
    result: Mapping[str, Any] | None,
    *,
    njr_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}

    metadata = _result_metadata(result)
    artifacts = collect_canonical_artifacts(result)
    primary_artifact = extract_primary_artifact(result)
    variant_count = len(canonicalize_variant_entries(result.get("variants") or []))
    output_count = len(extract_artifact_paths({"artifact": primary_artifact})) if primary_artifact else 0
    if output_count <= 0:
        output_count = variant_count

    return {
        "schema": DIAGNOSTICS_DESCRIPTOR_SCHEMA_VERSION,
        "success": result.get("success"),
        "error": result.get("error"),
        "duration_ms": metadata.get("duration_ms"),
        "recovery_classification": metadata.get("recovery_classification"),
        "stage_event_count": len(result.get("stage_events") or []),
        "variant_count": variant_count,
        "output_count": output_count,
        "artifact_count": len(artifacts),
        "artifact_type": primary_artifact.get("artifact_type"),
        "primary_stage": (
            _normalized_stage_name(primary_artifact.get("stage"))
            or _normalized_stage_name(metadata.get("video_primary_stage"))
            or (_collect_stage_types(result)[0] if _collect_stage_types(result) else "")
        ),
        "primary_artifact": dict(primary_artifact or {}),
        "backends": collect_backend_descriptors(result),
        "replay_descriptor": build_replay_descriptor(result, njr_snapshot=njr_snapshot),
    }


__all__ = [
    "DIAGNOSTICS_DESCRIPTOR_SCHEMA_VERSION",
    "REPLAY_DESCRIPTOR_SCHEMA_VERSION",
    "build_diagnostics_descriptor",
    "build_replay_descriptor",
    "collect_backend_descriptors",
    "collect_canonical_artifacts",
    "extract_primary_artifact",
]

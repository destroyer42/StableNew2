# Subsystem: Queue
# Role: Pure, immutable classification of which runtime a queued job needs (PR-QUEUE-WEBUI-171).

"""Classify a queued job's runtime dependency from its frozen executable identity.

The answer is derived only from the immutable NJR (workload kind, enabled stages, explicit backend identity). It
never consults model names, GUI labels, the currently configured default backend, the filesystem or the network, and
it never mutates or recompiles a historical record. Work whose dependency cannot be established is
``unresolved_dependency`` and is held together with WebUI work, so a missing field can never bypass a required hold.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from src.image_backends.image_backend_types import (
    A1111_IMAGE_BACKEND_ID,
    FORGE_IMAGE_BACKEND_ID,
    resolve_image_backend_id,
)

_WEBUI_IMAGE_BACKENDS = frozenset({A1111_IMAGE_BACKEND_ID, FORGE_IMAGE_BACKEND_ID})
_IMAGE_STAGES = frozenset({"txt2img", "img2img", "adetailer", "upscale"})
_VIDEO_EXECUTION_KEY = "video_execution"
SVD_NATIVE_BACKEND_ID = "svd_native"
COMFY_BACKEND_ID = "comfy"
#: Stage types proven to execute without the GPU (PR-QUEUE-GPU-180). Deliberately empty: every stage an NJR can
#: carry today (image, video, training) uses the GPU, so a GPU device-loss quarantine holds all of it. An entry
#: requires a frozen-identity proof of independence, never an inference from a missing field.
_GPU_FREE_STAGES: frozenset[str] = frozenset()


class BackendDependency(str, Enum):
    REQUIRES_WEBUI = "requires_webui"
    INDEPENDENT_VIDEO = "independent_video"
    UNRESOLVED = "unresolved_dependency"


@dataclass(frozen=True, slots=True)
class DependencyAssessment:
    dependency: BackendDependency
    #: Stable, content-free reason code.
    reason: str
    #: Every enabled stage is proven GPU-free. ``INDEPENDENT_VIDEO`` is independent of the WebUI, not of the GPU.
    gpu_free: bool = False

    @property
    def held_by_webui_outage(self) -> bool:
        """Whether an unavailable WebUI must keep this job queued (everything not proven independent)."""

        return self.dependency is not BackendDependency.INDEPENDENT_VIDEO

    @property
    def held_by_gpu_loss(self) -> bool:
        """Whether a GPU device-loss quarantine must keep this job queued (everything not proven GPU-free)."""

        return not self.gpu_free


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _video_block(config: Mapping[str, Any], stage: str) -> Mapping[str, Any]:
    return _mapping(_mapping(config.get(stage)).get(_VIDEO_EXECUTION_KEY))


def classify_frozen_identity(
    workload_kind: Any,
    enabled_stages: list[str],
    config: Mapping[str, Any],
    backend_options: Mapping[str, Any],
) -> DependencyAssessment:
    assessment = _classify_dependency(workload_kind, enabled_stages, config, backend_options)
    stages = set(enabled_stages)
    if stages and stages <= _GPU_FREE_STAGES:
        return replace(assessment, gpu_free=True)
    return assessment


def _classify_dependency(
    workload_kind: Any,
    enabled_stages: list[str],
    config: Mapping[str, Any],
    backend_options: Mapping[str, Any],
) -> DependencyAssessment:
    kind = str(getattr(workload_kind, "value", workload_kind) or "").strip().lower()
    stages = set(enabled_stages)
    unresolved = BackendDependency.UNRESOLVED
    if not kind or not stages:
        return DependencyAssessment(unresolved, "missing_workload_identity")
    if kind == "image":
        if not stages <= _IMAGE_STAGES:
            return DependencyAssessment(unresolved, "unsupported_image_stages")
        # Historical records without an explicit identity resolve exactly as they do at execution (A1111).
        if resolve_image_backend_id(backend_options) in _WEBUI_IMAGE_BACKENDS:
            return DependencyAssessment(BackendDependency.REQUIRES_WEBUI, "webui_image_backend")
        return DependencyAssessment(unresolved, "unknown_image_backend")
    if kind == "video":
        if "animatediff" in stages:
            # AnimateDiff executes through the WebUI executor; it is never assumed independent.
            return DependencyAssessment(
                BackendDependency.REQUIRES_WEBUI
                if stages == {"animatediff"}
                else unresolved,
                "animatediff_via_webui" if stages == {"animatediff"} else "mixed_video_stages",
            )
        if stages == {"svd_native"}:
            backend = str(_video_block(config, "svd_native").get("backend_id") or "").strip()
            if not backend or backend == SVD_NATIVE_BACKEND_ID:
                return DependencyAssessment(BackendDependency.INDEPENDENT_VIDEO, "svd_native")
            return DependencyAssessment(unresolved, "svd_native_backend_unresolved")
        if stages == {"video_workflow"}:
            backend = str(_video_block(config, "video_workflow").get("backend_id") or "").strip()
            if backend == COMFY_BACKEND_ID:
                return DependencyAssessment(BackendDependency.INDEPENDENT_VIDEO, "comfy_video_workflow")
            return DependencyAssessment(unresolved, "video_workflow_backend_unresolved")
        return DependencyAssessment(unresolved, "mixed_video_stages")
    # Training and anything unknown: no independence is assumed.
    return DependencyAssessment(unresolved, f"unverified_workload_{kind}")


def classify_record(record: Any) -> DependencyAssessment:
    """Classify an immutable ``NormalizedJobRecord`` without touching it."""

    workload = getattr(record, "workload", None)
    stages = [
        str(getattr(stage, "stage_type", "") or "")
        for stage in getattr(record, "stages", ()) or ()
        if getattr(stage, "enabled", False)
    ]
    return classify_frozen_identity(
        getattr(record, "workload_kind", None),
        stages,
        _mapping(getattr(workload, "config", None)),
        _mapping(getattr(workload, "backend_options", None)),
    )


def classify_snapshot(snapshot: Any) -> DependencyAssessment:
    """Classify a persisted NJR snapshot dict (``to_dict`` shape) when no record object is available."""

    data = _mapping(snapshot)
    data = _mapping(data.get("normalized_job")) or data
    workload = _mapping(data.get("workload"))
    stages = [
        str(_mapping(stage).get("stage_type") or "")
        for stage in data.get("stages") or ()
        if _mapping(stage).get("enabled", False)
    ]
    return classify_frozen_identity(
        data.get("workload_kind"),
        stages,
        _mapping(workload.get("config") or data.get("config")),
        _mapping(workload.get("backend_options") or data.get("backend_options")),
    )


def classify_job(job: Any) -> DependencyAssessment:
    """Classify a queue ``Job`` from its frozen NJR (record first, then persisted snapshot)."""

    record = getattr(job, "_normalized_record", None)
    if record is not None:
        return classify_record(record)
    snapshot = getattr(job, "snapshot", None)
    if isinstance(snapshot, Mapping) and snapshot:
        return classify_snapshot(snapshot)
    return DependencyAssessment(BackendDependency.UNRESOLVED, "no_frozen_record")


__all__ = [
    "BackendDependency",
    "DependencyAssessment",
    "classify_frozen_identity",
    "classify_job",
    "classify_record",
    "classify_snapshot",
]

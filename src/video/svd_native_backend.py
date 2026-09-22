from __future__ import annotations

from typing import Any

from src.services.runtime_transition_service import (
    RUNTIME_SVD_NATIVE,
    RuntimeTransitionCoordinator,
    RuntimeTransitionError,
)
from src.video.motion.secondary_motion_provenance import extract_secondary_motion_summary
from src.video.video_backend_types import (
    CONTROL_SOURCE_IMAGE,
    VIDEO_TASK_IMAGE_TO_VIDEO,
    VideoBackendCapabilities,
    VideoExecutionRequest,
    VideoExecutionResult,
)


class SVDNativeVideoBackend:
    backend_id = "svd_native"
    capabilities = VideoBackendCapabilities(
        backend_id=backend_id,
        stage_types=("svd_native",),
        tasks=(VIDEO_TASK_IMAGE_TO_VIDEO,),
        controls=(CONTROL_SOURCE_IMAGE,),
        required_controls=(CONTROL_SOURCE_IMAGE,),
    )

    def __init__(self, *, transition: RuntimeTransitionCoordinator | None = None) -> None:
        self._transition = transition or RuntimeTransitionCoordinator()

    def execute(self, pipeline: Any, request: VideoExecutionRequest) -> VideoExecutionResult | None:
        # Release conflicting StableNew-owned runtime residency (owned A1111, owned Comfy) before
        # native SVD loads; never touches an external runtime.  See PR-RUNTIME-100.
        transition = self._transition.prepare_for(RUNTIME_SVD_NATIVE)
        if not transition.ready:
            raise RuntimeTransitionError(transition)

        result = pipeline.run_svd_native_stage(
            input_image_path=request.input_image_path,
            stage_config=dict(request.stage_config or {}),
            output_dir=request.output_dir,
            job_id=str(request.job_id or ""),
            cancel_token=request.cancel_token,
            context_metadata=dict(request.context_metadata or {}),
        )
        if not isinstance(result, dict):
            return None
        return VideoExecutionResult.from_stage_result(
            backend_id=self.backend_id,
            stage_name=request.stage_name,
            result=result,
            backend_metadata={
                "backend_id": self.backend_id,
                "executor": "pipeline.run_svd_native_stage",
                "job_id": str(request.job_id or ""),
                "input_image_path": str(request.input_image_path)
                if request.input_image_path
                else None,
            },
            replay_manifest_fragment={
                "backend_id": self.backend_id,
                "stage_name": request.stage_name,
                "manifest_path": result.get("manifest_path"),
                "input_image_path": str(request.input_image_path)
                if request.input_image_path
                else None,
                "job_id": str(request.job_id or ""),
                "secondary_motion": result.get("secondary_motion"),
                "secondary_motion_summary": result.get("secondary_motion_summary")
                or extract_secondary_motion_summary(result),
            },
        )


__all__ = ["SVDNativeVideoBackend"]

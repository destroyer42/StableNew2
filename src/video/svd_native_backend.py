from __future__ import annotations

from typing import Any

from src.video.video_backend_types import (
    VideoBackendCapabilities,
    VideoExecutionRequest,
    VideoExecutionResult,
)


class SVDNativeVideoBackend:
    backend_id = "svd_native"
    capabilities = VideoBackendCapabilities(
        backend_id=backend_id,
        stage_types=("svd_native",),
        requires_input_image=True,
        supports_prompt_text=False,
        supports_negative_prompt=False,
    )

    def execute(self, pipeline: Any, request: VideoExecutionRequest) -> VideoExecutionResult | None:
        result = pipeline.run_svd_native_stage(
            input_image_path=request.input_image_path,
            stage_config=dict(request.stage_config or {}),
            output_dir=request.output_dir,
            job_id=str(request.job_id or ""),
            cancel_token=request.cancel_token,
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
                "input_image_path": str(request.input_image_path) if request.input_image_path else None,
            },
            replay_manifest_fragment={
                "backend_id": self.backend_id,
                "stage_name": request.stage_name,
                "manifest_path": result.get("manifest_path"),
                "input_image_path": str(request.input_image_path) if request.input_image_path else None,
                "job_id": str(request.job_id or ""),
            },
        )


__all__ = ["SVDNativeVideoBackend"]

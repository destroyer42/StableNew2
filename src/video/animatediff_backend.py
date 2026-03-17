from __future__ import annotations

from typing import Any

from src.video.video_backend_types import (
    VideoBackendCapabilities,
    VideoExecutionRequest,
    VideoExecutionResult,
)


class AnimateDiffVideoBackend:
    backend_id = "animatediff"
    capabilities = VideoBackendCapabilities(
        backend_id=backend_id,
        stage_types=("animatediff",),
        requires_input_image=False,
        supports_prompt_text=True,
        supports_negative_prompt=True,
    )

    def execute(self, pipeline: Any, request: VideoExecutionRequest) -> VideoExecutionResult | None:
        result = pipeline.run_animatediff_stage(
            input_image_path=request.input_image_path,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            config=dict(request.stage_config or {}),
            output_dir=request.output_dir,
            image_name=str(request.image_name or request.stage_name),
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
                "executor": "pipeline.run_animatediff_stage",
                "input_image_path": str(request.input_image_path) if request.input_image_path else None,
            },
            replay_manifest_fragment={
                "backend_id": self.backend_id,
                "stage_name": request.stage_name,
                "manifest_path": result.get("manifest_path"),
                "input_image_path": str(request.input_image_path) if request.input_image_path else None,
            },
        )


__all__ = ["AnimateDiffVideoBackend"]

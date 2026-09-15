"""A1111 adapter that preserves the existing StableNew image executor behavior."""

from __future__ import annotations

from typing import Any

from src.image_backends.image_backend_types import (
    DEFAULT_IMAGE_BACKEND_ID,
    ImageBackendCapabilities,
    ImageExecutionRequest,
    ImageExecutionResult,
)


class A1111WebUIImageBackend:
    backend_id = DEFAULT_IMAGE_BACKEND_ID
    capabilities = ImageBackendCapabilities(
        backend_id=backend_id,
        stage_types=("txt2img", "img2img", "adetailer", "upscale"),
    )

    def execute(self, pipeline: Any, request: ImageExecutionRequest) -> ImageExecutionResult | None:
        config = dict(request.stage_config or {})
        if request.stage_name == "txt2img":
            result = pipeline.run_txt2img_stage(
                request.prompt, request.negative_prompt, config, request.output_dir,
                image_name=str(request.image_name or "txt2img"), cancel_token=request.cancel_token,
            )
        elif request.stage_name == "img2img":
            if request.input_image_path is None:
                raise ValueError("img2img requires input image from previous stage")
            result = pipeline.run_img2img_stage(
                input_image_path=request.input_image_path, prompt=request.prompt, config=config,
                output_dir=request.output_dir, image_name=str(request.image_name or "img2img"),
                cancel_token=request.cancel_token,
            )
        elif request.stage_name == "adetailer":
            if request.input_image_path is None:
                raise ValueError("adetailer requires input image from previous stage")
            result = pipeline.run_adetailer_stage(
                input_image_path=request.input_image_path, config=config, output_dir=request.output_dir,
                image_name=str(request.image_name or "adetailer"), prompt=request.prompt,
                negative_prompt=request.negative_prompt, cancel_token=request.cancel_token,
            )
        elif request.stage_name == "upscale":
            if request.input_image_path is None:
                raise ValueError("upscale requires input image from previous stage")
            result = pipeline.run_upscale_stage(
                input_image_path=request.input_image_path, config=config, output_dir=request.output_dir,
                image_name=str(request.image_name or "upscale"), cancel_token=request.cancel_token,
            )
        else:
            raise ValueError(f"A1111 image backend does not support stage '{request.stage_name}'")
        if not isinstance(result, dict):
            return None
        return ImageExecutionResult.from_stage_result(
            backend_id=self.backend_id,
            stage_name=request.stage_name,
            result=result,
            backend_metadata={"backend_id": self.backend_id, "executor": f"pipeline.run_{request.stage_name}_stage"},
        )

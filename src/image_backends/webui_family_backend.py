"""Shared WebUI-family image backend: one StableNew stage translation for A1111 and Forge.

A1111 and Forge expose the same ``/sdapi/v1`` generation contract and share StableNew's executor
(``Pipeline.run_*_stage``), so the neutral-intent -> executor-config translation below is the
mechanically identical logic that the A1111 adapter has always owned, extracted unchanged and pinned
by the A1111 parity tests. The two identities differ only in (a) their durable backend id /
capabilities, (b) the StableNew runtime-transition target they claim, and (c) the read-only runtime
identity guard that runs before any generation dispatch.  Transport differences live in the client
(``ForgeWebUIClient``), never here, and nothing in this module knows Forge API field names.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.api.webui_runtime_identity import (
    assert_runtime_matches_backend,
    classify_client_runtime,
)
from src.image_backends.image_backend_types import (
    ImageBackendCapabilities,
    ImageExecutionRequest,
    ImageExecutionResult,
)
from src.services.runtime_transition_service import (
    RuntimeTransitionCoordinator,
    RuntimeTransitionError,
)


class WebUIFamilyImageBackend:
    """Base for backends that drive the WebUI-family executor; subclasses set the identity."""

    backend_id: str
    capabilities: ImageBackendCapabilities
    #: StableNew runtime-transition target claimed before dispatch (never a model/family name).
    transition_target: str

    def __init__(self, *, transition: RuntimeTransitionCoordinator | None = None) -> None:
        self._transition = transition or RuntimeTransitionCoordinator()

    @staticmethod
    def _stage_executor_config(request: ImageExecutionRequest) -> dict[str, Any]:
        """Translate neutral stage intent to the legacy executor configuration."""

        config = dict(request.stage_config or {})
        execution = dict(request.execution_config or {})
        extra = config.pop("extra", {})
        if isinstance(extra, Mapping):
            config.update(extra)
        if request.selected_model:
            config["model"] = request.selected_model
            config["sd_model_checkpoint"] = request.selected_model
        if request.selected_vae:
            config["vae"] = request.selected_vae
            config["sd_vae"] = request.selected_vae
            config["vae_name"] = request.selected_vae
        if request.sampler:
            config["sampler_name"] = request.sampler
        if request.scheduler:
            config["scheduler"] = request.scheduler
        if request.steps is not None:
            config["steps"] = request.steps
        if request.cfg_scale is not None:
            config["cfg_scale"] = request.cfg_scale
        if request.seed is not None:
            config["seed"] = request.seed
        if "pipeline" in execution:
            config["pipeline"] = execution["pipeline"]
        for key in (
            "global_positive_prompt",
            "global_negative_prompt",
            "global_prompt_policy_source",
        ):
            if key in execution:
                config[key] = execution[key]
        return config

    @classmethod
    def _txt2img_executor_config(cls, request: ImageExecutionRequest) -> dict[str, Any]:
        """Build the existing WebUI txt2img executor payload from neutral intent."""

        execution = dict(request.execution_config or {})
        provenance = dict(request.context_metadata.get("provenance") or {})
        config = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "model": request.selected_model,
            "sampler_name": request.sampler,
            "steps": request.steps or 20,
            "cfg_scale": request.cfg_scale or 7.5,
            "width": request.width or 1024,
            "height": request.height or 1024,
            # WebUI transport batching is adapter-private.
            "batch_size": 1,
            "n_iter": max(1, int(request.image_count or 1)),
        }
        if request.scheduler:
            config["scheduler"] = request.scheduler

        if execution.get("enable_hr"):
            config["enable_hr"] = execution["enable_hr"]
            config["hr_scale"] = execution.get("hr_scale", 2.0)
            config["hr_upscaler"] = execution.get("hr_upscaler", "Latent")
            config["hr_second_pass_steps"] = execution.get("hr_second_pass_steps", 0)
            config["denoising_strength"] = execution.get("denoising_strength", 0.7)
            for key in ("hr_resize_x", "hr_resize_y", "hires_use_base_model", "hr_checkpoint_name"):
                if execution.get(key) is not None:
                    config[key] = execution[key]
        if execution.get("use_refiner") and execution.get("refiner_checkpoint"):
            config["use_refiner"] = True
            config["refiner_checkpoint"] = execution["refiner_checkpoint"]
            config["refiner_switch_at"] = execution.get("refiner_switch_at", 0.8)

        for key in (
            "clip_skip",
            "seed",
            "subseed",
            "subseed_strength",
            "seed_resize_from_h",
            "seed_resize_from_w",
            "restore_faces",
            "tiling",
            "do_not_save_samples",
            "do_not_save_grid",
            "vae",
        ):
            if key in execution:
                config[key] = execution[key]
            elif key in provenance:
                config[key] = provenance[key]
        if request.seed is not None:
            config["seed"] = request.seed
        if request.selected_vae:
            config["vae"] = request.selected_vae
        if "pipeline" in execution:
            config["pipeline"] = execution["pipeline"]
        for key in (
            "global_positive_prompt",
            "global_negative_prompt",
            "global_prompt_policy_source",
        ):
            if key in execution:
                config[key] = execution[key]
        return {key: value for key, value in config.items() if value is not None}

    def execute(self, pipeline: Any, request: ImageExecutionRequest) -> ImageExecutionResult | None:
        # Release conflicting StableNew-owned runtime residency (owned Comfy, the other WebUI
        # identity, cached SVD state) before this backend is used; never touches an external
        # runtime.  See PR-RUNTIME-100 / PR-IMG-FORGE-100.
        transition = self._transition.prepare_for(self.transition_target)
        if not transition.ready:
            raise RuntimeTransitionError(transition)
        # Read-only identity guard: reject a backend/endpoint mismatch before any generation POST.
        assert_runtime_matches_backend(
            self.backend_id, classify_client_runtime(getattr(pipeline, "client", None))
        )

        if request.stage_name == "txt2img":
            config = self._txt2img_executor_config(request)
            result = pipeline.run_txt2img_stage(
                request.prompt,
                request.negative_prompt,
                config,
                request.output_dir,
                image_name=str(request.image_name or "txt2img"),
                cancel_token=request.cancel_token,
                learning_sample_names=request.learning_sample_names,
            )
        elif request.stage_name == "img2img":
            if request.input_image_path is None:
                raise ValueError("img2img requires input image from previous stage")
            config = self._stage_executor_config(request)
            result = pipeline.run_img2img_stage(
                input_image_path=request.input_image_path,
                prompt=request.prompt,
                config=config,
                output_dir=request.output_dir,
                image_name=str(request.image_name or "img2img"),
                cancel_token=request.cancel_token,
            )
        elif request.stage_name == "adetailer":
            if request.input_image_path is None:
                raise ValueError("adetailer requires input image from previous stage")
            config = self._stage_executor_config(request)
            extra_prompt = config.pop("prompt", None)
            extra_negative = config.pop("negative_prompt", None)
            if extra_prompt is not None:
                config["adetailer_prompt"] = extra_prompt
            if extra_negative is not None:
                config["adetailer_negative_prompt"] = extra_negative
            config["adetailer_enabled"] = True
            result = pipeline.run_adetailer_stage(
                input_image_path=request.input_image_path,
                config=config,
                output_dir=request.output_dir,
                image_name=str(request.image_name or "adetailer"),
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                cancel_token=request.cancel_token,
            )
        elif request.stage_name == "upscale":
            if request.input_image_path is None:
                raise ValueError("upscale requires input image from previous stage")
            config = self._stage_executor_config(request)
            config.setdefault("prompt", request.prompt)
            config.setdefault("negative_prompt", request.negative_prompt)
            result = pipeline.run_upscale_stage(
                input_image_path=request.input_image_path,
                config=config,
                output_dir=request.output_dir,
                image_name=str(request.image_name or "upscale"),
                cancel_token=request.cancel_token,
            )
        else:
            raise ValueError(
                f"{self.backend_id} image backend does not support stage '{request.stage_name}'"
            )
        if not isinstance(result, dict):
            return None
        return ImageExecutionResult.from_stage_result(
            backend_id=self.backend_id,
            stage_name=request.stage_name,
            result=result,
            backend_metadata={
                "backend_id": self.backend_id,
                "executor": f"pipeline.run_{request.stage_name}_stage",
            },
        )

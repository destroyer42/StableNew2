"""Prepare one masked Review edit with the existing builder and reprocess admission boundary."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from src.controller.reprocess_admission import submit_reprocess_njrs
from src.image_backends.image_backend_types import normalize_image_backend_options
from src.image_backends.masked_inpaint import require_mask_target
from src.image_backends.model_policy import FamilyLookup
from src.image_backends.operation_compatibility import require_njr_operation
from src.pipeline.image_edit_inputs import KEY, freeze_inputs, verified_inputs
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.reprocess_builder import ImageEditSpec, ReprocessJobBuilder, ReprocessSourceItem


@dataclass(frozen=True)
class MaskEditSettings:
    prompt: str
    denoise: float = 0.45
    mask_blur: int = 4
    padding: int = 32
    only_masked: bool = True

    def validate(self) -> None:
        if not self.prompt.strip():
            raise ValueError("Describe the desired edit before Preview")
        if not 0 < self.denoise <= 1:
            raise ValueError("Denoising strength must be greater than 0 and at most 1")
        if type(self.mask_blur) is not int or not 0 <= self.mask_blur <= 64:
            raise ValueError("Mask blur must be an integer from 0 through 64")
        if type(self.padding) is not int or not 0 <= self.padding <= 256:
            raise ValueError("Masked-region padding must be an integer from 0 through 256")


@dataclass(frozen=True)
class MaskEditPreview:
    job: NormalizedJobRecord
    source_path: str

    def require_queueable(self) -> None:
        stage = self.job.config["img2img"]
        verified_inputs(stage, self.job.input_image_paths[0], check_original=True)
        require_mask_target(self.job.base_model or "", self.job.backend_options)
        require_njr_operation(self.job)

    def submit(self, job_service: Any) -> int:
        self.require_queueable()
        return submit_reprocess_njrs(job_service, [self.job])


def prepare_mask_edit(
    *,
    source_path: str,
    source_sha256: str,
    mask_data: bytes,
    settings: MaskEditSettings,
    fallback_config: dict[str, Any],
    baseline: dict[str, Any],
    family_lookup: FamilyLookup | None = None,
) -> MaskEditPreview:
    """Worker-side preparation. No queue or GUI mutation; snapshots contain the exact inspected bytes."""
    settings.validate()
    builder = ReprocessJobBuilder()  # type: ignore[no-untyped-call]  # existing unannotated constructor
    config = builder._merge_nested_dicts(fallback_config, dict(baseline.get("config") or {}))
    model = str(
        baseline.get("model")
        or config.get("model")
        or config.get("img2img", {}).get("model")
        or config.get("txt2img", {}).get("model")
        or ""
    )
    options = normalize_image_backend_options(config.get("backend_options"), model_name=model)
    require_mask_target(model, options, family_lookup=family_lookup)
    frozen = freeze_inputs(source_path, mask_data, source_sha256)
    source, mask = frozen["source"], frozen["mask"]
    config["backend_options"] = options
    config["prompt_optimizer"] = {"enabled": False}
    config["global_negative_prompt"] = ""
    config["global_positive_prompt"] = ""
    pipeline = config.setdefault("pipeline", {})
    pipeline["apply_global_negative_img2img"] = False
    stage = config.setdefault("img2img", {})
    stage.update(
        {
            KEY: frozen,
            "denoising_strength": settings.denoise,
            "width": source["width"],
            "height": source["height"],
        }
    )
    config["img2img_denoising_strength"] = settings.denoise
    config["width"], config["height"] = source["width"], source["height"]
    # The runner's seed fallbacks inspect txt2img/global keys even for reprocess work.
    seed = stage.get("seed", config.get("seed", config.get("txt2img", {}).get("seed", -1)))
    seed = -1 if seed is None else seed
    stage["seed"] = config["seed"] = seed
    config.setdefault("txt2img", {})["seed"] = seed
    source_item = ReprocessSourceItem(
        input_image_path=source["path"],
        prompt=settings.prompt.strip(),
        negative_prompt=str(baseline.get("negative_prompt") or ""),
        model=model,
        vae=baseline.get("vae"),
        config=config,
        metadata={"source_path": source_path, "source_artifact_id": f"sha256:{source['sha256']}"},
        image_edit=ImageEditSpec(
            mask["path"],
            mask_blur=settings.mask_blur,
            inpaint_full_res=settings.only_masked,
            inpaint_full_res_padding=settings.padding,
        ),
    )
    plan = builder.build_grouped_reprocess_jobs(
        items=[source_item],
        stages=["img2img"],
        fallback_config={},
        batch_size=1,
        pack_name="ReviewMaskedEdit",
        source="image_edit",
        extra_metadata_builder=lambda _items, _output: {
            "parent_job_id": baseline.get("job_id"),
            "parent_artifact_id": f"sha256:{source['sha256']}",
            KEY: deepcopy(frozen),
        },
    )
    job = plan.jobs[0]
    require_njr_operation(job)
    verified_inputs(job.config["img2img"], job.input_image_paths[0], check_original=True)
    return MaskEditPreview(job, source_path)

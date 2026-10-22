"""Prepare one frozen Review outpainting job with the existing masked-edit builder and reprocess admission boundary.

Outpainting is a masked img2img edit whose source is the original image on an extended canvas and whose mask marks only
the new area. This module owns no queue, runner, backend call or output writer: ``MaskEditPreview.submit`` hands the exact
previewed NJR to ``submit_reprocess_njrs``. The protected original is restored at the img2img artifact-finalization
boundary (``Pipeline.run_img2img_stage``) from the frozen original snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.controller.masked_edit_service import MaskEditPreview, build_frozen_edit_preview
from src.image_backends.image_backend_types import (
    normalize_image_backend_options,
    resolve_image_backend_id,
)
from src.image_backends.masked_inpaint import require_mask_target
from src.image_backends.model_policy import FamilyLookup
from src.pipeline.image_edit_inputs import KEY, ORIGINAL_KEY, OUTPAINT_KEY, freeze_outpaint_inputs
from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.outpaint_canvas import OPERATION, Extents, assess_pressure
from src.pipeline.reprocess_builder import ImageEditSpec

QUALITY_NOTICE = (
    "Physical output quality has not been qualified. The generated surroundings come from the backend; only the "
    "original pixels are guaranteed (restored exactly when the job finishes)."
)


@dataclass(frozen=True)
class OutpaintSettings:
    prompt: str
    extents: Extents
    denoise: float = 0.85
    mask_blur: int = 8

    def validate(self) -> None:
        if not self.prompt.strip():
            raise ValueError("Describe what should appear in the new space before Preview")
        if not 0 < self.denoise <= 1:
            raise ValueError("Denoising strength must be greater than 0 and at most 1")
        if type(self.mask_blur) is not int or not 0 <= self.mask_blur <= 64:
            raise ValueError("Mask blur must be an integer from 0 through 64")
        self.extents.validate()


def describe_support(
    model: str, backend_options: Mapping[str, Any], *, family_lookup: FamilyLookup | None = None
) -> tuple[bool, str]:
    """Whether the selected target can run an outpaint, with an operator-facing sentence (read-only projection)."""
    try:
        options = normalize_image_backend_options(dict(backend_options), model_name=model)
        require_mask_target(model, options, family_lookup=family_lookup)
    except ValueError as exc:
        return False, str(exc)
    return (
        True,
        f"Supported target: {model or 'selected model'} on {resolve_image_backend_id(options)} (SDXL base).",
    )


def prepare_outpaint_edit(
    *,
    source_path: str,
    source_sha256: str,
    settings: OutpaintSettings,
    fallback_config: dict[str, Any],
    baseline: dict[str, Any],
    family_lookup: FamilyLookup | None = None,
) -> MaskEditPreview:
    """Worker-side preparation. No queue or GUI mutation; snapshots contain the exact derived and inspected bytes."""
    settings.validate()
    return build_frozen_edit_preview(
        source_path=source_path,
        prompt=settings.prompt,
        denoise=settings.denoise,
        fallback_config=fallback_config,
        baseline=baseline,
        family_lookup=family_lookup,
        pack_name="ReviewOutpaint",
        freeze=lambda steps: freeze_outpaint_inputs(
            source_path, source_sha256, settings.extents, steps=steps
        ),
        edit_spec=lambda mask: ImageEditSpec(
            mask["path"],
            operation=OPERATION,
            mask_blur=settings.mask_blur,
            inpaint_full_res=False,  # whole canvas: the new area surrounds the original on every side
            inpaint_full_res_padding=32,
        ),
        lineage_sha=lambda frozen: frozen[ORIGINAL_KEY]["sha256"],
        operation=OPERATION,
    )


def outpaint_preview_summary(preview: MaskEditPreview) -> dict[str, Any]:
    """The bounded projection the dialog shows (prompt text is redacted by the caller); built from the frozen job only."""
    job = preview.job
    stage = thaw_json(job.config["img2img"])
    frozen = stage[KEY]
    record = frozen[OUTPAINT_KEY]
    expanded = record["expanded_size"]
    steps = stage.get("steps")
    pressure = assess_pressure(
        expanded["width"], expanded["height"], steps if type(steps) is int else 20
    )
    return {
        "original": {
            "path": frozen["original_path"],
            "sha256": frozen[ORIGINAL_KEY]["sha256"],
            **record["original_size"],
        },
        "expanded": expanded,
        "extents": record["extents"],
        "original_bbox": record["original_bbox"],
        "padding_policy": record["padding_policy"],
        "mask": {
            "policy": record["mask_policy"],
            "sha256": frozen["mask"]["sha256"],
            "mask_blur": stage["mask_blur"],
            "note": "white = generate, black = original; blur is applied by the backend and never alters the original",
        },
        "model": job.base_model,
        "backend": job.backend_options,
        "prompt": job.positive_prompt,
        "negative_prompt": job.negative_prompt,
        "denoising_strength": stage["denoising_strength"],
        "stage": job.stage_chain[0].to_dict(),
        "preservation": {
            **record["preservation"],
            "color_normalization": record["color_normalization"],
        },
        "snapshots": {
            "expanded_source_sha256": frozen["source"]["sha256"],
            "mask_sha256": frozen["mask"]["sha256"],
            "original_sha256": frozen[ORIGINAL_KEY]["sha256"],
        },
        "lineage": {
            "job_id": job.job_id,
            "parent_job_id": job.source.parent_job_id,
            "parent_artifact_id": job.source.parent_artifact_id,
        },
        "pressure": {
            "status": pressure.status,
            "megapixels": pressure.megapixels,
            "effective_load": pressure.effective_load,
            "reasons": list(pressure.reasons),
        },
        "quality_notice": QUALITY_NOTICE,
    }

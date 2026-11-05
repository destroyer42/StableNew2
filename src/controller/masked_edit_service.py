"""Prepare one masked Review edit with the existing builder and reprocess admission boundary."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.controller.reprocess_admission import submit_reprocess_njrs
from src.controller.review_batch_service import require_history_iterate_identity
from src.image_backends.image_backend_types import normalize_image_backend_options
from src.image_backends.masked_inpaint import require_mask_target
from src.image_backends.model_policy import FamilyLookup
from src.image_backends.operation_compatibility import require_njr_operation
from src.pipeline.image_edit_inputs import EDIT_OPERATION_KEY, KEY, freeze_inputs, verified_inputs
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.reprocess_builder import ImageEditSpec, ReprocessJobBuilder, ReprocessSourceItem
from src.utils.image_metadata import ImageMetadataContractV26, read_image_metadata


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


def history_lineage_for(handoff: Any, path: str | Path) -> dict[str, Any] | None:
    """The active Iterate-from-History hand-off's identity for exactly ``path`` (None for any other image).

    Lookup is by the exact selected path, so a hand-off for image A is never visible to image B, and Review drops the
    hand-off whenever a new selection is accepted.
    """
    by_path = dict(getattr(handoff, "source_metadata_by_path", None) or {})
    meta = by_path.get(str(path)) or by_path.get(str(Path(path).resolve()))
    if isinstance(meta, dict) and isinstance(meta.get("history_iterate"), dict):
        return dict(meta)
    return None


def bind_history_lineage(
    baseline: dict[str, Any],
    *,
    source_path: str | Path,
    source_sha256: str,
    lineage: dict[str, Any] | None,
) -> dict[str, Any]:
    """Name the History job an edit descends from, only when the hand-off provably describes exactly this image.

    ``lineage`` is the verified Iterate-from-History hand-off for the selected Review image. It is trusted only for
    the same file path and the same bytes (artifact digest) the hand-off recorded, and only when the image's own
    embedded job id (if any) agrees. Anything else is refused, never re-attributed. Without a hand-off the baseline
    is returned unchanged, so an image with no trustworthy originating job keeps ``parent_job_id`` unset.
    """
    claim = (lineage or {}).get("history_iterate")
    if not isinstance(claim, dict):
        return baseline
    lineage = dict(lineage or {})
    job_id = str(claim.get("job_id") or "")
    if not job_id or str(lineage.get("source_job_id") or job_id) != job_id:
        raise ValueError(
            "The History hand-off does not name one job; reopen the image from History"
        )
    recorded_path = str(lineage.get("source_path") or "")
    if not recorded_path or Path(recorded_path).resolve() != Path(source_path).resolve():
        raise ValueError(
            "The History hand-off belongs to a different image; reopen it from History"
        )
    if str(lineage.get("source_artifact_id") or "") != f"sha256:{source_sha256}":
        raise ValueError(
            "The recorded image changed since it was opened from History; reopen it from History"
        )
    embedded = read_image_metadata(Path(source_path)).get(ImageMetadataContractV26.KEY_JOB_ID)
    existing = baseline.get("job_id")
    if existing and str(existing) != job_id:
        raise ValueError(
            "Image identity contradicts the History job it was opened from; refusing to re-attribute it"
        )
    require_history_iterate_identity(lineage, embedded, source_sha256)
    return {**baseline, "job_id": job_id}


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
    return build_frozen_edit_preview(
        source_path=source_path,
        prompt=settings.prompt,
        denoise=settings.denoise,
        fallback_config=fallback_config,
        baseline=baseline,
        family_lookup=family_lookup,
        pack_name="ReviewMaskedEdit",
        freeze=lambda _steps: freeze_inputs(source_path, mask_data, source_sha256),
        edit_spec=lambda mask: ImageEditSpec(
            mask["path"],
            mask_blur=settings.mask_blur,
            inpaint_full_res=settings.only_masked,
            inpaint_full_res_padding=settings.padding,
        ),
        lineage_sha=lambda frozen: frozen["source"]["sha256"],
    )


def build_frozen_edit_preview(
    *,
    source_path: str,
    prompt: str,
    denoise: float,
    fallback_config: dict[str, Any],
    baseline: dict[str, Any],
    family_lookup: FamilyLookup | None,
    pack_name: str,
    freeze: Callable[[int], dict[str, Any]],
    edit_spec: Callable[[dict[str, Any]], ImageEditSpec],
    lineage_sha: Callable[[dict[str, Any]], str],
    operation: str | None = None,
) -> MaskEditPreview:
    """Shared builder for frozen Review image edits: one img2img NJR through the existing reprocess builder."""
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
    steps = config.get("img2img", {}).get("steps")
    frozen = freeze(steps if type(steps) is int and steps > 0 else 20)
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
            "denoising_strength": denoise,
            "width": source["width"],
            "height": source["height"],
        }
    )
    if (
        operation
    ):  # the frozen contract must carry the record this operation requires (verified_inputs)
        stage[EDIT_OPERATION_KEY] = operation
    config["img2img_denoising_strength"] = denoise
    config["width"], config["height"] = source["width"], source["height"]
    # The runner's seed fallbacks inspect txt2img/global keys even for reprocess work.
    seed = stage.get("seed", config.get("seed", config.get("txt2img", {}).get("seed", -1)))
    seed = -1 if seed is None else seed
    stage["seed"] = config["seed"] = seed
    config.setdefault("txt2img", {})["seed"] = seed
    artifact_id = f"sha256:{lineage_sha(frozen)}"
    source_item = ReprocessSourceItem(
        input_image_path=source["path"],
        prompt=prompt.strip(),
        negative_prompt=str(baseline.get("negative_prompt") or ""),
        model=model,
        vae=baseline.get("vae"),
        config=config,
        metadata={"source_path": source_path, "source_artifact_id": artifact_id},
        image_edit=edit_spec(mask),
    )
    plan = builder.build_grouped_reprocess_jobs(
        items=[source_item],
        stages=["img2img"],
        fallback_config={},
        batch_size=1,
        pack_name=pack_name,
        source="image_edit",
        extra_metadata_builder=lambda _items, _output: {
            "parent_job_id": baseline.get("job_id"),
            "parent_artifact_id": artifact_id,
            KEY: deepcopy(frozen),
        },
    )
    job = plan.jobs[0]
    require_njr_operation(job)
    verified_inputs(job.config["img2img"], job.input_image_paths[0], check_original=True)
    return MaskEditPreview(job, source_path)

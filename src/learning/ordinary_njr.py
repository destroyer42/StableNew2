"""Materialise one ordinary (single-variable) Learning variant into the canonical NJR.

The controller owns experiment intent and presentation; this module owns turning an already-frozen,
already-validated variant configuration into a ``NormalizedJobRecord``.  It is toolkit-neutral, reads no widget
and no live Pipeline state, and submits nothing: the record still crosses ``JobService.submit_njrs`` once, with
the rest of its experiment.

Two modes share one construction path:

* ``strict`` (every experiment whose snapshot carries ``baseline_authoring``): every effective field must come
  from the frozen baseline.  A missing field, an empty prompt, or a stage setting the canonical builder resolves
  differently from what Preview reported refuses the whole experiment.
* legacy (``strict=False``, snapshots frozen before independent baselines): the historical defaults are kept so a
  saved, unfinished experiment compiles exactly as it did.  Retire this branch when no saved session predates
  ``baseline_authoring`` (see ``docs/Subsystems/Learning/LEARNING.md``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from src.image_backends.image_backend_types import normalize_image_backend_options
from src.learning import baseline_authoring as authoring
from src.pipeline.job_models_v2 import (
    CURRENT_NJR_SCHEMA_VERSION,
    ImageWorkloadSpec,
    LearningJobContext,
    LoRATag,
    NJRProvenance,
    NormalizedJobRecord,
    OutputPlan,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    WorkloadKind,
)
from src.pipeline.reprocess_builder import ReprocessJobBuilder

logger = logging.getLogger(__name__)


def materialize_njr(
    *,
    final_config: dict[str, Any],
    experiment: Any,
    variant: Any,
    prompt: str,
    negative_prompt: str,
    learning_metadata: dict[str, Any],
    job_id: str,
    variant_index: int,
    variant_total: int,
    selected_loras: Mapping[str, LoRATag],
    output_dir: str,
    filename_template: str,
    strict: bool,
    source_identity: Mapping[str, Any] | None = None,
    expected: Mapping[str, Any] | None = None,
) -> NormalizedJobRecord:
    """Build the immutable record for one variant from its frozen configuration."""
    stage_name = str(experiment.stage or "txt2img").strip().lower() or "txt2img"
    if strict:
        stage_name = authoring.require_stage(stage_name)
        if not str(prompt or "").strip():
            raise ValueError(
                "The frozen experiment has no prompt. Choose a prompt and rebuild Preview."
            )
        problems = authoring.baseline_problems(
            final_config, stage_name, input_image_path=getattr(experiment, "input_image_path", "")
        )
        if problems:
            raise ValueError("Invalid Learning baseline: " + "; ".join(problems))
        changed = authoring.source_image_changed(source_identity)
        if changed:
            raise ValueError(changed)

    learning_ctx = LearningJobContext(
        experiment_id=experiment.experiment_id,
        experiment_name=experiment.name,
        variant_index=variant_index,
        variable_under_test=experiment.variable_under_test,
        variant_value=variant.param_value,
    )

    if stage_name != "txt2img":
        record = _materialize_reprocess(
            final_config=final_config,
            experiment=experiment,
            stage_name=stage_name,
            prompt=prompt,
            negative_prompt=negative_prompt,
            learning_metadata=learning_metadata,
            strict=strict,
        )
        record = replace(
            record,
            job_id=job_id,
            provenance=replace(
                record.provenance,
                variant_index=variant_index,
                variant_total=variant_total,
                learning_context=learning_ctx,
                lora_tags=tuple(selected_loras.values()),
                metadata=learning_metadata,
            ),
        )
    else:
        record = _materialize_txt2img(
            final_config=final_config,
            experiment=experiment,
            prompt=prompt,
            negative_prompt=negative_prompt,
            learning_metadata=learning_metadata,
            job_id=job_id,
            variant_index=variant_index,
            variant_total=variant_total,
            learning_ctx=learning_ctx,
            selected_loras=selected_loras,
            output_dir=output_dir,
            filename_template=filename_template,
            strict=strict,
        )

    if strict and expected is not None:
        mismatches = authoring.parity_mismatches(
            expected, authoring.stage_values_from_record(record, stage_name)
        )
        if mismatches:
            raise ValueError(
                "The compiled job does not match the Preview: " + "; ".join(mismatches)
            )
    return record


def _materialize_reprocess(
    *,
    final_config: dict[str, Any],
    experiment: Any,
    stage_name: str,
    prompt: str,
    negative_prompt: str,
    learning_metadata: dict[str, Any],
    strict: bool,
) -> NormalizedJobRecord:
    from src.learning.stage_capabilities import get_stage_capability

    capability = get_stage_capability(stage_name)
    input_image_path = str(getattr(experiment, "input_image_path", "") or "").strip()
    if capability.requires_input_image and not input_image_path:
        raise ValueError(f"{capability.display_name} experiments require an input image")
    from pathlib import Path

    if input_image_path and not Path(input_image_path).exists():
        raise ValueError(f"Input image not found: {input_image_path}")
    stage_section = final_config.get(stage_name, {})
    if not isinstance(stage_section, dict):
        stage_section = {}
    base_model = str((final_config.get("txt2img") or {}).get("model") or "")
    builder: Any = ReprocessJobBuilder
    record: NormalizedJobRecord = builder().build_reprocess_job(
        input_image_paths=[input_image_path] * max(1, int(experiment.images_per_value or 1)),
        stages=[stage_name],
        config=final_config,
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=str(stage_section.get("model") or base_model or ""),
        pack_name=f"learning_{experiment.name}",
        source="learning",
        extra_metadata=learning_metadata,
    )
    return record


def _materialize_txt2img(
    *,
    final_config: dict[str, Any],
    experiment: Any,
    prompt: str,
    negative_prompt: str,
    learning_metadata: dict[str, Any],
    job_id: str,
    variant_index: int,
    variant_total: int,
    learning_ctx: LearningJobContext,
    selected_loras: Mapping[str, LoRATag],
    output_dir: str,
    filename_template: str,
    strict: bool,
) -> NormalizedJobRecord:
    section = final_config.get("txt2img", {})
    if not isinstance(section, dict):
        section = {}
    if strict:
        # Declared operator values only: nothing is defaulted here.  Optional fields keep their canonical
        # "unset" meaning (no VAE, random subseed) rather than an invented executable value.
        model = str(section["model"])
        vae = str(section.get("vae") or "")
        sampler = str(section["sampler_name"])
        scheduler = str(section["scheduler"])
        steps = int(section["steps"])
        cfg_scale = float(section["cfg_scale"])
        seed = int(section["seed"])
        clip_skip = int(section.get("clip_skip", 2) or 2)
    else:
        model = section.get("model", "")
        vae = section.get("vae", "")
        sampler = section.get("sampler_name", "Euler a")
        scheduler = section.get("scheduler", "normal")
        steps = int(section.get("steps", 20))
        cfg_scale = float(section.get("cfg_scale", 7.0))
        seed = int(section.get("seed", -1))
        clip_skip = int(section.get("clip_skip", 2))
        if seed == -1:
            logger.warning(
                "[LearningController]   WARNING: Seed is -1 (random), check if stage card has seed set"
            )

    subseed = int(section.get("subseed", -1))
    subseed_strength = float(section.get("subseed_strength", 0.0))
    seed_resize_from_h = int(section.get("seed_resize_from_h", 0))
    seed_resize_from_w = int(section.get("seed_resize_from_w", 0))

    stage = StageConfig(
        stage_type="txt2img",
        enabled=True,
        steps=steps,
        cfg_scale=cfg_scale,
        sampler_name=sampler,
        scheduler=scheduler,
        model=model,
        vae=vae,
        extra={},
    )
    return NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION,
        job_id=job_id,
        workload_kind=WorkloadKind.IMAGE,
        source=SourceDescriptor(kind=SourceKind.LEARNING, display_name=experiment.name),
        workload=ImageWorkloadSpec(
            positive_prompt=prompt,
            negative_prompt=negative_prompt,
            config=final_config,
            images_per_prompt=max(1, int(experiment.images_per_value or 1)),
            metadata=learning_metadata,
            backend_options=normalize_image_backend_options(final_config.get("backend_options")),
        ),
        stages=(stage,),
        output_plan=OutputPlan(
            base_output_dir=output_dir or "output", filename_template=filename_template
        ),
        provenance=NJRProvenance(
            seed=seed,
            variant_index=variant_index,
            variant_total=variant_total,
            learning_context=learning_ctx,
            lora_tags=tuple(selected_loras.values()),
            metadata={
                **learning_metadata,
                "subseed": subseed,
                "subseed_strength": subseed_strength,
                "seed_resize_from_h": seed_resize_from_h,
                "seed_resize_from_w": seed_resize_from_w,
                "clip_skip": clip_skip,
            },
        ),
    )

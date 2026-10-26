"""The one assembly of an immutable Learning txt2img NJR from an already frozen, validated configuration.

Planning, prompt adaptation and axis proofs happen in the study modules; this only turns their result into the record
``JobService.submit_njrs`` admits, so Model Comparison and Two-Axis Grid cannot drift apart. Production compiler
imports are deferred to the call.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.pipeline.job_models_v2 import NormalizedJobRecord


def assemble_txt2img_njr(
    *,
    job_id: str,
    display_name: str,
    positive: str,
    negative: str,
    config: dict[str, Any],
    metadata: dict[str, Any],
    backend_options: Any,
    images_per_prompt: int,
    output_dir: str,
    filename_template: str,
    variant_index: int,
    variant_total: int,
    context: Any,
    positive_embeddings: Sequence[Any] = (),
    negative_embeddings: Sequence[Any] = (),
    lora_tags: Sequence[tuple[str, float]] = (),
    mismatch_message: str = "Learning NJR does not match frozen execution",
) -> NormalizedJobRecord:
    from src.image_backends.exact_model_profile import validate_profile_njr
    from src.pipeline.job_models_v2 import (
        CURRENT_NJR_SCHEMA_VERSION,
        ImageWorkloadSpec,
        LoRATag,
        NJRProvenance,
        NormalizedJobRecord,
        OutputPlan,
        SourceDescriptor,
        SourceKind,
        StageConfig,
        WorkloadKind,
    )
    from src.utils.embedding_prompt_utils import render_embedding_invocation

    section = config["txt2img"]
    record = NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION,
        job_id=job_id,
        workload_kind=WorkloadKind.IMAGE,
        source=SourceDescriptor(kind=SourceKind.LEARNING, display_name=display_name),
        workload=ImageWorkloadSpec(
            positive_prompt=positive,
            negative_prompt=negative,
            config=config,
            images_per_prompt=images_per_prompt,
            metadata=metadata,
            backend_options=backend_options,
        ),
        stages=(
            StageConfig(
                stage_type="txt2img",
                enabled=True,
                model=section["model"],
                vae=section.get("vae", ""),
                steps=int(section["steps"]),
                cfg_scale=float(section["cfg_scale"]),
                sampler_name=section["sampler_name"],
                scheduler=section["scheduler"],
                extra={},
            ),
        ),
        output_plan=OutputPlan(
            base_output_dir=output_dir or "output", filename_template=filename_template
        ),
        provenance=NJRProvenance(
            seed=section["seed"],
            variant_index=variant_index,
            variant_total=variant_total,
            learning_context=context,
            positive_embeddings=tuple(
                render_embedding_invocation(*item) for item in positive_embeddings
            ),
            negative_embeddings=tuple(
                render_embedding_invocation(*item) for item in negative_embeddings
            ),
            lora_tags=tuple(LoRATag(name=name, weight=weight) for name, weight in lora_tags),
            metadata=metadata,
        ),
    )
    if (
        record.positive_prompt != config["prompt"]
        or record.negative_prompt != config["negative_prompt"]
        or record.workload.backend_options != config["backend_options"]
    ):
        raise ValueError(mismatch_message)
    # The same exact-profile admission check the NJR builders apply (a no-op for every other model).
    validate_profile_njr(record)
    return record

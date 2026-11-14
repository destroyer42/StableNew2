"""The one assembly of an immutable Learning txt2img NJR from an already frozen, validated configuration.

Planning, prompt adaptation and axis proofs happen in the study modules; this only declares their result as a ``FROZEN``
draft and lets ``njr_compiler.compile_njr`` assemble the record ``JobService.submit_njrs`` admits, so Model Comparison
and Two-Axis Grid cannot drift apart. Production compiler imports are deferred to the call.
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
    from src.pipeline.job_models_v2 import (
        ImageWorkloadSpec,
        LoRATag,
        NJRProvenance,
        OutputPlan,
        SourceDescriptor,
        SourceKind,
        StageConfig,
        WorkloadKind,
    )
    from src.pipeline.njr_compiler import (
        CompileCheck,
        FrozenExpectation,
        NjrDraft,
        PolicyState,
        compile_njr,
    )
    from src.utils.embedding_prompt_utils import render_embedding_invocation

    section = config["txt2img"]
    # Everything arrives frozen and validated, so the draft is FROZEN: the core never transforms it, refuses it when
    # the record differs from the frozen arm, then applies the exact-profile admission check the NJR builders apply
    # (a no-op for every other model).
    return compile_njr(
        NjrDraft(
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
            policy_state=PolicyState.FROZEN,
            checks=(CompileCheck.PROFILE_NJR,),
            frozen=FrozenExpectation(
                values={
                    "positive_prompt": config["prompt"],
                    "negative_prompt": config["negative_prompt"],
                    "workload.backend_options": config["backend_options"],
                },
                message=mismatch_message,
            ),
        )
    )

"""Deterministic image-plan checks shared by Queue admission and dispatch (N1, "warn, don't block").

These are real blocks (the chosen image backend cannot run a stage, or ADetailer cannot run with the selected
checkpoint), decided from the frozen NJR alone. Before N1 they ran only in ``PipelineRunner.run_njr``, so every
matching job in a batch failed one by one after the operator had walked away. ``AGENTS.md`` section 2 now reports a
block as early as it can be known: ``JobService.submit_njrs`` refuses such a job at Queue, and the runner keeps the same
check for work admitted before this rule existed.

No file, endpoint or GPU is touched; ``validate_njr_intent`` (which can need live backend evidence) stays at dispatch.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from typing import Any

from src.image_backends import (
    ImageBackendRegistry,
    build_default_image_backend_registry,
    resolve_image_backend_id,
)
from src.image_backends.model_policy import resolve_model_policy
from src.pipeline.njr_core_v26 import thaw_json

IMAGE_STAGE_NAMES = frozenset({"txt2img", "img2img", "adetailer", "upscale"})

StageModelSelector = Callable[..., "str | None"]


def require_image_plan(
    njr: Any,
    stage_names: Sequence[str],
    registry: ImageBackendRegistry,
    *,
    stage_config: Callable[[Any, str], Mapping[str, Any]],
    select_model: StageModelSelector,
) -> str:
    """Resolve the job's one image backend and refuse a stage chain or ADetailer use it cannot run.

    Returns the backend id ("" when the plan has no image stage).
    """

    image_stages = [stage_name for stage_name in stage_names if stage_name in IMAGE_STAGE_NAMES]
    if not image_stages:
        return ""
    backend_id = resolve_image_backend_id(thaw_json(getattr(njr, "backend_options", {})))
    registry.validate_stage_chain(backend_id, image_stages)
    start_stage = getattr(njr, "start_stage", None)
    names = list(stage_names)
    dispatched = names[names.index(start_stage) :] if start_stage in names else names
    if "adetailer" in dispatched:
        model = select_model("adetailer", stage_config(njr, "adetailer"), njr=njr)
        policy = resolve_model_policy(model)
        if "adetailer" not in policy.stages or backend_id not in policy.allowed_backends:
            raise ValueError(
                f"ADetailer cannot run with {policy.display_name} on {backend_id}. "
                "Create a fresh job with a supported checkpoint."
            )
    return backend_id


@lru_cache(maxsize=1)
def _default_registry() -> ImageBackendRegistry:
    return build_default_image_backend_registry()


def require_image_admission(record: Any) -> None:
    """The Queue-time twin of the runner's image-plan check, for fresh image work."""

    if str(getattr(getattr(record, "workload_kind", None), "value", "")) != "image":
        return
    from src.pipeline.pipeline_runner import PipelineRunner
    from src.pipeline.run_plan import build_run_plan_from_njr

    plan = build_run_plan_from_njr(record)
    require_image_plan(
        record,
        [job.stage_name for job in plan.jobs],
        _default_registry(),
        stage_config=PipelineRunner._stage_config_for_njr,
        select_model=PipelineRunner._selected_stage_model,
    )


__all__ = ["IMAGE_STAGE_NAMES", "require_image_admission", "require_image_plan"]

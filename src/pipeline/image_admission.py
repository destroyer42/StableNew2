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
    registry = _default_registry()
    backend_id = resolve_image_backend_id(thaw_json(getattr(record, "backend_options", {})))
    if backend_id not in registry.list_backend_ids():
        return  # an extension or test backend: the runner that registered it validates the plan at dispatch
    stage_names = [job.stage_name for job in plan.jobs]
    if not require_image_plan(
        record,
        stage_names,
        registry,
        stage_config=PipelineRunner._stage_config_for_njr,
        select_model=PipelineRunner._selected_stage_model,
    ):
        return
    _require_backend_intent(record, registry.get(backend_id), stage_names)


def _require_backend_intent(record: Any, backend: Any, stage_names: Sequence[str]) -> None:
    """Queue twins of the backend's static dispatch refusals (N1 follow-up; the backends keep theirs at dispatch).

    Each is decided from the frozen NJR and a fixed host fact, so no job that cannot run waits in the queue for them.
    """

    from src.image_backends import forge_webui_backend as forge
    from src.image_backends.exact_model_profile import resolve_model_profile
    from src.image_backends.forge_flux1_profile import Flux1Profile
    from src.image_backends.forge_klein_profile import KleinProfile, KleinProfileError
    from src.image_backends.forge_klein_readiness import check_klein_host_memory
    from src.image_backends.forge_zimage_profile import ZImageProfile
    from src.image_backends.image_backend_types import FORGE_IMAGE_BACKEND_ID
    from src.image_backends.webui_family_backend import WebUIFamilyImageBackend

    backend_id = str(backend.backend_id)
    if not isinstance(backend, WebUIFamilyImageBackend):
        return
    if "adetailer" in stage_names and not backend.capabilities.supports_localized_adetailer:
        _require_no_localized_adetailer(record, backend_id)
    if backend_id != FORGE_IMAGE_BACKEND_ID:
        return
    hypernetworks = forge.requested_hypernetworks_for_njr(record)
    if hypernetworks and not backend.capabilities.supports_hypernetworks:
        raise ValueError(
            "Hypernetworks are not supported by the Forge runtime (the pinned Forge Neo removed them), but this job "
            f"requests: {', '.join(hypernetworks)}. Nothing was queued. Remove the hypernetwork, or select the A1111 "
            "compatibility runtime (webui_runtime_identity = a1111_webui) to use it."
        )
    profile = resolve_model_profile(getattr(record, "backend_options", None) or {})
    if isinstance(profile, (KleinProfile, ZImageProfile, Flux1Profile)):
        # Total physical RAM is a fixed host fact (owner Q3: it stays a block). It is read through the backend's own
        # seam, looked up at call time, so the probe the dispatch check uses is the one Queue uses.
        probe = getattr(forge, "read_host_memory")  # noqa: B009 - a module seam, not an exported name
        try:
            check_klein_host_memory(profile, probe=probe)
        except KleinProfileError as exc:
            raise ValueError(
                f"{exc}. Nothing was queued. Run this model on a host with at least "
                f"{profile.min_total_ram_bytes / 1e9:.0f} GB of RAM, or choose a model without this profile."
            ) from exc


def _require_no_localized_adetailer(record: Any, backend_id: str) -> None:
    from src.pipeline.adetailer_localized import (
        LOCALIZED_ONLY,
        LocalizedRefinementError,
        execution_mode,
    )

    for stage in getattr(record, "stage_chain", None) or ():
        if getattr(stage, "stage_type", None) != "adetailer" or not getattr(
            stage, "enabled", False
        ):
            continue
        config = dict(getattr(stage, "extra", None) or {})
        if isinstance(config.get("extra"), Mapping):
            config.update(config["extra"])
        try:
            mode = execution_mode(config)
        except LocalizedRefinementError as exc:
            raise ValueError(f"ADetailer stage refused: {exc}. Nothing was queued.") from exc
        if mode == LOCALIZED_ONLY:
            raise ValueError(
                f"The '{backend_id}' image backend cannot run StableNew's localized-only ADetailer refinement (it "
                "needs the companion extension of the managed Forge runtime). Nothing was queued. Switch the image "
                "runtime to Forge (forge_webui), or turn off the ADetailer stage for this job."
            )


__all__ = ["IMAGE_STAGE_NAMES", "require_image_admission", "require_image_plan"]

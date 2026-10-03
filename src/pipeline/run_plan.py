from __future__ import annotations

from dataclasses import dataclass, field

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig

_CANONICAL_STAGE_ORDER = {
    "txt2img": 0,
    "img2img": 1,
    "adetailer": 2,
    "upscale": 3,
    "animatediff": 4,
    "svd_native": 5,
    "video_workflow": 6,
}


@dataclass
class PlannedJob:
    stage_name: str
    prompt_text: str
    variant_id: int
    batch_index: int
    seed: int | None = None
    cfg_scale: float | None = None
    sampler: str | None = None
    model: str | None = None


@dataclass
class RunPlan:
    jobs: list[PlannedJob] = field(default_factory=list)
    total_jobs: int = 0
    total_images: int = 0
    enabled_stages: list[str] = field(default_factory=list)
    source_job_id: str | None = None
    replay_of: str | None = None


def _explicit_stage_name(stage_config: object) -> str:
    raw = getattr(stage_config, "stage_type", None)
    raw = getattr(raw, "value", raw)
    name = str(raw).strip() if raw is not None else ""
    if not name:
        raise ValueError("RunPlan requires an explicit stage_type for every enabled stage")
    return name


def build_run_plan_from_njr(njr: NormalizedJobRecord) -> RunPlan:
    """
    Derives a RunPlan from a NormalizedJobRecord.
    This is the canonical path for both live runs and replays.

    Fail-closed: only explicitly enabled, explicitly named stages are planned. A
    missing/blank stage identity or an empty/all-disabled chain raises ``ValueError``;
    this module never synthesizes a stage. Historical input must be hydrated into a
    valid NJR before it reaches this function.
    """
    stage_chain: list[StageConfig] = list(getattr(njr, "stage_chain", []) or [])
    enabled_chain = [
        (idx, stage, _explicit_stage_name(stage))
        for idx, stage in enumerate(stage_chain)
        if getattr(stage, "enabled", False)
    ]
    if not enabled_chain:
        raise ValueError("RunPlan requires at least one enabled stage")
    enabled_chain.sort(key=lambda item: (_CANONICAL_STAGE_ORDER.get(item[2], 99), item[0]))

    jobs = [
        PlannedJob(
            stage_name=stage_type,
            prompt_text=getattr(njr, "positive_prompt", "") or "",
            variant_id=getattr(njr, "variant_index", 0),
            batch_index=getattr(njr, "batch_index", 0),
            seed=getattr(njr, "seed", None),
            cfg_scale=getattr(njr, "cfg_scale", None),
            sampler=getattr(njr, "sampler_name", None),
            model=getattr(njr, "base_model", None),
        )
        for _idx, _stage, stage_type in enabled_chain
    ]

    return RunPlan(
        jobs=jobs,
        total_jobs=len(jobs),
        total_images=getattr(njr, "images_per_prompt", None) or 1,
        enabled_stages=[job.stage_name for job in jobs],
        source_job_id=getattr(njr, "job_id", None),
        replay_of=getattr(njr, "job_id", None),
    )

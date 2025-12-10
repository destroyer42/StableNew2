from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig


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
    jobs: List[PlannedJob] = field(default_factory=list)
    total_jobs: int = 0
    total_images: int = 0
    enabled_stages: List[str] = field(default_factory=list)
    source_job_id: str | None = None
    replay_of: str | None = None


def build_run_plan_from_njr(njr: NormalizedJobRecord) -> RunPlan:
    """
    Derives a RunPlan from a NormalizedJobRecord.
    This is the canonical path for both live runs and replays.
    """
    stage_chain: List[StageConfig] = list(getattr(njr, "stage_chain", []) or [])
    first_stage = stage_chain[0] if stage_chain else None
    stage_name = getattr(first_stage, "stage_type", None) or "txt2img"
    enabled_stages = [getattr(stage, "stage_type", "") for stage in stage_chain] or [stage_name]
    plan = RunPlan(
        jobs=[
            PlannedJob(
                stage_name=stage_name,
                prompt_text=getattr(njr, "positive_prompt", "") or "",
                variant_id=getattr(njr, "variant_index", 0) or 0,
                batch_index=getattr(njr, "batch_index", 0) or 0,
                seed=getattr(njr, "seed", None),
                cfg_scale=getattr(njr, "cfg_scale", None),
                sampler=getattr(njr, "sampler_name", None),
                model=getattr(njr, "base_model", None),
            )
        ],
        total_jobs=1,
        total_images=getattr(njr, "images_per_prompt", None) or 1,
        enabled_stages=enabled_stages,
        source_job_id=getattr(njr, "job_id", None),
        replay_of=getattr(njr, "job_id", None),
    )
    return plan

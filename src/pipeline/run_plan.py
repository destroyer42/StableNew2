from __future__ import annotations

from dataclasses import dataclass, field

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
    jobs: list[PlannedJob] = field(default_factory=list)
    total_jobs: int = 0
    total_images: int = 0
    enabled_stages: list[str] = field(default_factory=list)
    source_job_id: str | None = None
    replay_of: str | None = None


def build_run_plan_from_njr(njr: NormalizedJobRecord) -> RunPlan:
    """
    Derives a RunPlan from a NormalizedJobRecord.
    This is the canonical path for both live runs and replays.
    """
    stage_chain: list[StageConfig] = list(getattr(njr, "stage_chain", []) or [])
    
    # Build a PlannedJob for EACH **ENABLED** stage in the chain
    jobs = []
    enabled_stages = []
    
    for idx, stage_config in enumerate(stage_chain):
        # Check if stage is enabled
        is_enabled = getattr(stage_config, "enabled", True)
        if not is_enabled:
            continue  # Skip disabled stages
            
        stage_type = getattr(stage_config, "stage_type", "") or "txt2img"
        enabled_stages.append(stage_type)
        
        jobs.append(
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
        )
    
    # Fallback: if no enabled stages found, create a single txt2img job
    if not jobs:
        jobs.append(
            PlannedJob(
                stage_name="txt2img",
                prompt_text=getattr(njr, "positive_prompt", "") or "",
                variant_id=getattr(njr, "variant_index", 0),
                batch_index=getattr(njr, "batch_index", 0),
                seed=getattr(njr, "seed", None),
                cfg_scale=getattr(njr, "cfg_scale", None),
                sampler=getattr(njr, "sampler_name", None),
                model=getattr(njr, "base_model", None),
            )
        )
        enabled_stages = ["txt2img"]
    
    plan = RunPlan(
        jobs=jobs,
        total_jobs=len(jobs),
        total_images=getattr(njr, "images_per_prompt", None) or 1,
        enabled_stages=enabled_stages,
        source_job_id=getattr(njr, "job_id", None),
        replay_of=getattr(njr, "job_id", None),
    )
    return plan

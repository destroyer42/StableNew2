"""Shared helpers for constructing NJR-backed Jobs in tests (v2.6)."""

from __future__ import annotations

import uuid
from typing import Any

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.stage_models import StageType
from src.queue.job_model import Job
from src.utils.snapshot_builder_v2 import build_job_snapshot


def make_test_stage() -> StageConfig:
    """Return a minimal enabled TXT2IMG stage for NJR validation."""
    return StageConfig(
        stage_type=StageType.TXT2IMG,
        enabled=True,
        steps=20,
        cfg_scale=7.5,
        sampler_name="Euler a",
    )


def make_test_njr(
    *,
    job_id: str | None = None,
    prompt: str = "test prompt",
    prompt_source: str = "pack",
    prompt_pack_id: str = "pack-001",
    prompt_pack_name: str = "Test Pack",
    base_model: str = "sdxl",
    config: Any | None = None,
) -> NormalizedJobRecord:
    """Build a NormalizedJobRecord with sane defaults for queue tests."""
    if job_id is None:
        job_id = f"job-{uuid.uuid4()}"
    stage_chain = [make_test_stage()]
    record = NormalizedJobRecord(
        job_id=job_id,
        config=config or {"model": base_model, "prompt": prompt, "prompt_pack_id": prompt_pack_id},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        positive_prompt=prompt,
        negative_prompt="",
        base_model=base_model,
        sampler_name="Euler a",
        steps=20,
        cfg_scale=7.5,
        width=512,
        height=512,
        stage_chain=stage_chain,
    )
    if prompt_source:
        record.prompt_source = prompt_source  # type: ignore[attr-defined]
    if prompt_source == "pack":
        record.prompt_pack_id = prompt_pack_id  # type: ignore[attr-defined]
        record.prompt_pack_name = prompt_pack_name  # type: ignore[attr-defined]
    return record


def make_test_job_from_njr(
    njr: NormalizedJobRecord,
    *,
    run_mode: str = "queue",
    source: str = "gui",
    prompt_source: str | None = None,
) -> Job:
    """Wrap a NormalizedJobRecord into a Job with snapshot + private binding."""
    job = Job(
        job_id=njr.job_id,
        run_mode=run_mode,
        source=source,
        prompt_source=prompt_source or njr.prompt_source or "pack",
        prompt_pack_id=njr.prompt_pack_id or None,
        config_snapshot=njr.to_queue_snapshot(),
    )
    job._normalized_record = njr  # type: ignore[attr-defined]
    job.snapshot = build_job_snapshot(job, njr, run_config={"prompt_source": job.prompt_source})
    return job


__all__ = [
    "make_test_njr",
    "make_test_job_from_njr",
    "make_test_stage",
]

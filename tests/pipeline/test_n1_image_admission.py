"""N1: real image-plan blocks are refused at Queue (JobService admission), not after the job has waited."""

from __future__ import annotations

import pytest

from src.pipeline.execution_admission import require_execution_admission
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


def _njr(*, backend: str, chain: tuple, job_id: str):
    return make_pipeline_njr(
        job_id=job_id,
        positive_prompt="a lighthouse at dusk",
        stage_chain=chain,
        backend_options={"image": {"backend_id": backend}},
    )


def test_an_ordinary_forge_job_is_admitted() -> None:
    chain = (
        make_stage_config("txt2img", model="sdxl.safetensors"),
        make_stage_config(
            "adetailer", model="sdxl.safetensors", extra={"adetailer_model": "face_yolov8n.pt"}
        ),
    )
    require_execution_admission(_njr(backend="forge_webui", chain=chain, job_id="n1-ok"))


def test_a_stage_the_backend_cannot_run_is_refused_at_queue() -> None:
    chain = (
        make_stage_config("txt2img", model="sdxl.safetensors"),
        make_stage_config("upscale", model="sdxl.safetensors"),
    )
    with pytest.raises(ValueError, match="does not support stage chain: upscale"):
        require_execution_admission(_njr(backend="comfyui", chain=chain, job_id="n1-chain"))


def test_adetailer_with_an_exact_profile_model_is_refused_at_queue() -> None:
    from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1

    model = ZIMAGE_PROFILE_V1.transformer.filename
    chain = (
        make_stage_config("txt2img", model=model),
        make_stage_config("adetailer", model=model, extra={"adetailer_model": "face_yolov8n.pt"}),
    )
    with pytest.raises(ValueError, match="ADetailer cannot run with"):
        require_execution_admission(_njr(backend="forge_webui", chain=chain, job_id="n1-adetailer"))


def test_a_video_job_is_not_inspected_by_the_image_check() -> None:
    from types import SimpleNamespace

    from src.pipeline.image_admission import require_image_admission

    require_image_admission(SimpleNamespace(workload_kind=SimpleNamespace(value="video")))

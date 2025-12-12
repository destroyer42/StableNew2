
import pytest
from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_models_v2 import NormalizedJobRecord

def make_minimal_pack_job_entry(prompt="hello", pack_id="pack1"):
    return PackJobEntry(
        pack_id=pack_id,
        pack_name="TestPack",
        prompt_lines=[prompt],
        model_name="sdxl",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.0,
        loras=[],
        vae_name="",
        negative_prompt="",
        metadata={},
    )

def test_controller_builds_njr_from_pack_bundle():
    controller = PipelineController()
    entry = make_minimal_pack_job_entry()
    njrs = controller._build_njrs_from_pack_bundle([entry])
    assert len(njrs) >= 1
    assert all(isinstance(njr, NormalizedJobRecord) for njr in njrs)
    for njr in njrs:
        assert hasattr(njr, 'prompt_pack_id')
        assert isinstance(njr.prompt_pack_id, str)

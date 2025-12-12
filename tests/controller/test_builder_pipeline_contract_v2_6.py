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

def test_prompt_pack_builder_produces_njrs_for_single_entry():
    controller = PipelineController()
    entry = make_minimal_pack_job_entry()
    njrs = controller._build_njrs_from_pack_bundle([entry])
    assert len(njrs) >= 1
    assert all(isinstance(njr, NormalizedJobRecord) for njr in njrs)

def test_multiple_pack_entries_produce_multiple_njrs():
    controller = PipelineController()
    entry1 = make_minimal_pack_job_entry(prompt="prompt1", pack_id="pack1")
    entry2 = make_minimal_pack_job_entry(prompt="prompt2", pack_id="pack2")
    njrs = controller._build_njrs_from_pack_bundle([entry1, entry2])
    assert len(njrs) >= 2
    pack_ids = {njr.prompt_pack_id for njr in njrs if hasattr(njr, 'prompt_pack_id')}
    assert "pack1" in pack_ids and "pack2" in pack_ids

def test_no_pipeline_config_assembler_dependency():
    # Importing PipelineController should not raise ModuleNotFoundError for assembler
    try:
        from src.controller import pipeline_controller
    except ModuleNotFoundError as e:
        assert "pipeline_config_assembler" not in str(e)

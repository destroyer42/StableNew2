from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
from src.pipeline.pipeline_runner import PipelineConfig


def _make_pipeline_config() -> PipelineConfig:
    return PipelineConfig(
        prompt="legacy prompt",
        model="sdxl",
        sampler="Euler a",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.5,
        negative_prompt="legacy neg",
        metadata={"legacy_info": "test"},
    )


def test_adapter_builds_njr_with_meta_flags() -> None:
    config = _make_pipeline_config()
    record = build_njr_from_legacy_pipeline_config(config)
    assert record.positive_prompt == "legacy prompt"
    assert record.negative_prompt == "legacy neg"
    assert record.base_model == "sdxl"
    assert record.extra_metadata.get("legacy_source") == "pipeline_config"
    assert record.extra_metadata.get("core1_b4_adapter") is True


def test_adapter_handles_minimal_pipeline_config() -> None:
    config = PipelineConfig(
        prompt="minimal",
        model="sdxl",
        sampler="Euler a",
        width=512,
        height=512,
        steps=10,
        cfg_scale=5.0,
    )
    record = build_njr_from_legacy_pipeline_config(config)
    assert record.stage_chain
    assert record.stage_chain[0].stage_type == "txt2img"
    assert record.extra_metadata["core1_b4_adapter"]

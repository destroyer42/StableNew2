from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides


def test_build_pipeline_config_applies_overrides_and_limits():
    assembler = PipelineConfigAssembler(max_megapixels=1.0)
    overrides = GuiOverrides(
        prompt="hello",
        model="sdxl",
        sampler="Euler",
        width=2048,
        height=2048,
    )

    config = assembler.build_from_gui_input(overrides=overrides)

    assert config.prompt == "hello"
    # width/height should be clamped down to respect megapixel limit
    assert config.width * config.height <= 1_000_000
    assert config.model == "sdxl"


def test_build_pipeline_config_includes_metadata():
    assembler = PipelineConfigAssembler()
    overrides = GuiOverrides(prompt="hi")
    config = assembler.build_for_learning_run(overrides=overrides, learning_metadata={"learning_run_id": "lr-1"})

    assert config.metadata.get("learning", {}).get("learning_run_id") == "lr-1"
    assert config.metadata.get("learning_enabled") is True


def test_randomizer_metadata_attached():
    assembler = PipelineConfigAssembler()
    overrides = GuiOverrides(prompt="rand")
    cfg = assembler.build_from_gui_input(overrides=overrides, randomizer_metadata={"matrix": "m1"})
    assert cfg.metadata.get("randomizer", {}).get("matrix") == "m1"

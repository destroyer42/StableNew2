from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler


def test_negative_prompt_roundtrip_into_metadata():
    assembler = PipelineConfigAssembler()
    overrides = GuiOverrides(negative_prompt="bad hands, low quality")

    cfg = assembler.build_from_gui_input(overrides=overrides)

    assert cfg.metadata.get("negative_prompt") == "bad hands, low quality"

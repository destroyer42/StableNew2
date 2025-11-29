from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler


def test_assembler_maps_resolution_and_clamps():
    assembler = PipelineConfigAssembler(max_megapixels=1.0)
    overrides = GuiOverrides(width=4000, height=4000)

    cfg = assembler.build_from_gui_input(overrides=overrides)

    assert cfg.width * cfg.height <= 1_000_000
    assert cfg.width > 0 and cfg.height > 0

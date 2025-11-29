import pytest

from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler


def test_assembler_maps_core_fields_and_resolution_preset():
    assembler = PipelineConfigAssembler()
    overrides = GuiOverrides(
        prompt="p1",
        model="m1",
        sampler="Euler a",
        steps=30,
        cfg_scale=6.5,
        resolution_preset="768x768",
    )

    cfg = assembler.build_from_gui_input(overrides=overrides)

    assert cfg.model == "m1"
    assert cfg.sampler == "Euler a"
    assert cfg.steps == 30
    assert cfg.cfg_scale == pytest.approx(6.5)
    assert cfg.width == 768
    assert cfg.height == 768


def test_assembler_resolution_preset_overrides_width_height():
    assembler = PipelineConfigAssembler()
    overrides = GuiOverrides(width=640, height=360, resolution_preset="1024x1024")

    cfg = assembler.build_from_gui_input(overrides=overrides)

    assert cfg.width == 1024
    assert cfg.height == 1024

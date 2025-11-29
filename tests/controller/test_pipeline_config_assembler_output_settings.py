from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler


def test_assembler_maps_output_settings_into_metadata():
    assembler = PipelineConfigAssembler()
    overrides = GuiOverrides(
        output_dir="out",
        filename_pattern="file_{index}",
        image_format="webp",
        batch_size=4,
        seed_mode="increment",
    )

    cfg = assembler.build_from_gui_input(overrides=overrides)
    output_meta = cfg.metadata.get("output") or {}
    assert output_meta.get("output_dir") == "out"
    assert output_meta.get("filename_pattern") == "file_{index}"
    assert output_meta.get("image_format") == "webp"
    assert output_meta.get("batch_size") == 4
    assert output_meta.get("seed_mode") == "increment"

from src.controller.pipeline_config_assembler import GuiOverrides, PipelineConfigAssembler


def test_assembler_maps_model_and_vae_fields():
    assembler = PipelineConfigAssembler()
    overrides = GuiOverrides(model_name="my_model", vae_name="my_vae")

    cfg = assembler.build_from_gui_input(overrides=overrides)

    assert cfg.model == "my_model"
    assert cfg.metadata.get("vae") == "my_vae"
    assert cfg.metadata.get("model_name") == "my_model"

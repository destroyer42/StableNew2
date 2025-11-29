def test_adetailer_scheduler_round_trip_in_prompt_pack_editor(minimal_gui_app):
    app = minimal_gui_app

    # Default should be inherit for fresh UI
    assert app.adetailer_panel.scheduler_var.get() == "inherit"

    # Change scheduler and persist to pack
    app.adetailer_panel.scheduler_var.set("Karras")
    cfg = app._get_config_from_forms()
    app.config_service.save_pack_config("scheduler_pack", cfg)
    saved = app.config_service.load_pack_config("scheduler_pack")

    adetailer_cfg = saved.get("adetailer", {})
    assert adetailer_cfg.get("adetailer_scheduler") == "Karras"
    assert adetailer_cfg.get("scheduler") == "Karras"

    # Reset UI to confirm reload honors persisted scheduler
    app.adetailer_panel.scheduler_var.set("inherit")
    app._apply_editor_from_cfg(saved)
    assert app.adetailer_panel.scheduler_var.get() == "Karras"


def test_adetailer_scheduler_defaults_to_inherit_when_missing(minimal_gui_app):
    app = minimal_gui_app

    # Force non-default value so we can verify reset happens
    app.adetailer_panel.scheduler_var.set("Karras")

    legacy_cfg = {"adetailer": {"adetailer_enabled": True}}
    app._apply_editor_from_cfg(legacy_cfg)

    assert app.adetailer_panel.scheduler_var.get() == "inherit"

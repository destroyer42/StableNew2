from src.config import app_config


def test_queue_toggle_updates_app_config(gui_app_factory, dummy_controller, dummy_config_manager):
    """Queue toggle should update the shared queue execution flag."""

    app_config.set_queue_execution_enabled(False)
    app = gui_app_factory(controller=dummy_controller, config_manager=dummy_config_manager)

    command_bar = app.pipeline_panel_v2.command_bar
    command_bar.queue_toggle.invoke()

    assert app_config.is_queue_execution_enabled() is True

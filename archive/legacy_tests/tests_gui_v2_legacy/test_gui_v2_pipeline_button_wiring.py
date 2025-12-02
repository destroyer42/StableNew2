"""Verify the v2 Run button is wired to the controller start path."""

from __future__ import annotations


def test_run_button_invokes_controller(
    monkeypatch,
    gui_app_factory,
    dummy_controller,
    dummy_config_manager,
):
    """Clicking the Run button should call controller.start_pipeline exactly once."""

    app = gui_app_factory(controller=dummy_controller, config_manager=dummy_config_manager)

    # Bypass the heavy run implementation but keep the controller wiring.
    def _fake_run(self):
        self.controller.start_pipeline(lambda: None, on_complete=None, on_error=None)

    monkeypatch.setattr(type(app), "_run_full_pipeline_impl", _fake_run, raising=False)

    app.api_connected = True
    app._apply_run_button_state()

    run_button = getattr(app, "run_button", app.run_pipeline_btn)
    run_button.invoke()

    assert dummy_controller.start_calls == 1

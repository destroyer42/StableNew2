from importlib import reload

from src.gui import main_window


def test_stablenewgui_exposes_v2_components(gui_app_factory):
    app = gui_app_factory()

    assert getattr(app, "center_notebook", None) is not None
    assert getattr(app, "pipeline_panel_v2", None) is not None
    assert getattr(app, "status_bar_v2", None) is not None


def test_entrypoint_targets_v2_gui():
    import src.main as entrypoint

    reload(entrypoint)

    assert getattr(main_window, "ENTRYPOINT_GUI_CLASS", None) is main_window.StableNewGUI
    assert getattr(entrypoint, "ENTRYPOINT_GUI_CLASS", None) is main_window.StableNewGUI

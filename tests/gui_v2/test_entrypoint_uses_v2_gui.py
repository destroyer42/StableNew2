from importlib import reload

from src.gui import main_window
from src.gui.main_window_v2 import MainWindowV2


def test_stablenewgui_exposes_v2_components(gui_app_factory):
    app = gui_app_factory()

    assert getattr(app, "center_notebook", None) is not None
    assert getattr(app, "pipeline_panel_v2", None) is not None
    assert getattr(app, "status_bar_v2", None) is not None


def test_entrypoint_targets_v2_gui():
    import src.main as entrypoint

    reload(entrypoint)

    # After PR-048 the entrypoint class is MainWindowV2 directly, not the shim.
    assert getattr(main_window, "ENTRYPOINT_GUI_CLASS", None) is MainWindowV2
    assert getattr(entrypoint, "ENTRYPOINT_GUI_CLASS", None) is MainWindowV2

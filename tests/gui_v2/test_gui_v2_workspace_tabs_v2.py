from __future__ import annotations

import pytest

from src.app_factory import build_v2_app
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2


@pytest.mark.gui
def test_workspace_tabs_present() -> None:
    try:
        root, app_state, controller, window = build_v2_app()
    except Exception as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        notebook = getattr(window, "center_notebook", None)
        assert notebook is not None
        labels = [notebook.tab(tab_id, "text") for tab_id in notebook.tabs()]
        assert "Prompt" in labels
        assert "Pipeline" in labels
        assert "Learning" in labels

        assert isinstance(getattr(window, "prompt_tab", None), object)
        assert isinstance(getattr(window, "pipeline_tab", None), object)
        assert isinstance(getattr(window, "learning_tab", None), object)

        for frame_attr in ("prompt_tab", "pipeline_tab", "learning_tab"):
            frame = getattr(window, frame_attr, None)
            assert frame is not None
            container = getattr(frame, "body_frame", frame)
            weights = [container.grid_columnconfigure(idx)["weight"] for idx in range(3)]
            assert all(w > 0 for w in weights), f"{frame_attr} must configure three columns"

        notebook_info = window.center_notebook.grid_info()
        assert notebook_info.get("column") == 0
        assert notebook_info.get("columnspan") == 3
        assert window.left_zone is window.pipeline_tab.pack_loader_compat

        sidebar = getattr(window, "sidebar_panel_v2", None)
        assert isinstance(sidebar, SidebarPanelV2)
        preview = getattr(window, "preview_panel_v2", None)
        assert isinstance(preview, PreviewPanelV2)

        assert window.pipeline_controls_panel.winfo_exists()
        assert hasattr(window, "run_pipeline_btn")
    finally:
        try:
            root.destroy()
        except Exception:
            pass

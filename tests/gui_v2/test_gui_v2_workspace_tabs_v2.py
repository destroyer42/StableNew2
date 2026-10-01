from __future__ import annotations

import pytest

from src.app_factory import build_v2_app
from src.gui.panels_v2.operator_readiness_panel_v2 import format_product_support_label
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.services.operator_readiness_service import product_support_surfaces


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
        # Tab titles are qualified by the product-support state (non-MVP surfaces
        # carry an "- Adv"/"- Deferred" suffix), so derive the expected labels
        # from the same support contract rather than hard-coding them.
        support = {surface.id: surface.state for surface in product_support_surfaces()}
        for surface_id, base_title in (
            ("prompt", "Prompt"),
            ("pipeline", "Pipeline"),
            ("learning", "Learning"),
            ("svd", "SVD Img2Vid"),
        ):
            expected = (
                format_product_support_label(base_title, support[surface_id])
                if surface_id in support
                else base_title
            )
            assert expected in labels, f"missing {expected!r} tab in {labels}"

        assert isinstance(getattr(window, "prompt_tab", None), object)
        assert isinstance(getattr(window, "pipeline_tab", None), object)
        assert isinstance(getattr(window, "learning_tab", None), object)
        assert isinstance(getattr(window, "svd_tab", None), object)

        # Learning is a mode notebook now: its body_frame is the single-column
        # "Designed Experiments" host and the three-pane workspace lives on the
        # staged-curation tab frame.
        three_column_hosts = {
            "prompt_tab": lambda frame: getattr(frame, "body_frame", frame),
            "pipeline_tab": lambda frame: getattr(frame, "body_frame", frame),
            "learning_tab": lambda frame: frame._staged_tab_frame,  # noqa: SLF001
        }
        for frame_attr, resolve_container in three_column_hosts.items():
            frame = getattr(window, frame_attr, None)
            assert frame is not None
            container = resolve_container(frame)
            weights = [container.grid_columnconfigure(idx)["weight"] for idx in range(3)]
            assert all(w > 0 for w in weights), f"{frame_attr} must configure three columns"
        learning_body = window.learning_tab.body_frame
        assert learning_body.grid_columnconfigure(0)["weight"] > 0

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

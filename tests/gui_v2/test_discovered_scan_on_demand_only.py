"""The Discovered inbox is never scanned by itself (owner decision 2026-11-27: "Stop scan, keep groups").

The output scan runs only when the operator presses Rescan (or Rebuild). Building the Learning tab, opening its
views and switching Simple / Advanced only read the stored groups.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.gui.app_state_v2 import AppStateV2
from src.gui.controllers.learning_controller import LearningController
from src.gui.view_contracts.workspace_mode_contract import WORKSPACE_ADVANCED, WORKSPACE_SIMPLE
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.services.ui_state_store import UIStateStore
from tests.gui_v2.test_action_explainer_panels_v2 import _StubPipelineController


def test_only_the_rescan_button_scans_the_output_folder(tk_root, tmp_path: Path) -> None:
    scans: list[str] = []
    with (
        patch(
            "src.gui.views.learning_tab_frame_v2.get_ui_state_store",
            return_value=UIStateStore(tmp_path / "ui_state.json"),
        ),
        patch(
            "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
            return_value=tmp_path / "experiments",
        ),
        patch.object(
            LearningController,
            "trigger_background_scan",
            lambda _self, output_root, on_complete=None: scans.append(output_root),
        ),
    ):
        tab = LearningTabFrame(
            tk_root, app_state=AppStateV2(), pipeline_controller=_StubPipelineController()
        )
        try:
            notebook = tab._mode_notebook
            for mode in (WORKSPACE_ADVANCED, WORKSPACE_SIMPLE, WORKSPACE_ADVANCED):
                tab.set_workspace_mode(mode)
                for view in notebook.tabs():
                    if str(notebook.tab(view, "state")) == "hidden":
                        continue
                    notebook.select(view)
                    tk_root.update()
            assert scans == []

            tab.discovered_inbox_panel._on_rescan_clicked()

            assert len(scans) == 1
        finally:
            tab.destroy()

from __future__ import annotations

from unittest.mock import Mock

from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


def test_runtime_status_updates_only_refresh_running_job_panel() -> None:
    tab = PipelineTabFrame.__new__(PipelineTabFrame)
    tab.app_state = object()
    tab.running_job_panel = Mock()
    tab.queue_panel = Mock()

    tab._on_runtime_status_changed()

    tab.running_job_panel.update_from_app_state.assert_called_once_with(tab.app_state)
    tab.queue_panel.update_from_app_state.assert_not_called()

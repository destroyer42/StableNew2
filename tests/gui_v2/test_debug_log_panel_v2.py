import tkinter as tk
from datetime import datetime

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.panels_v2.debug_log_panel_v2 import DebugLogPanelV2
from src.pipeline.job_models_v2 import JobLifecycleLogEvent


@pytest.mark.gui
def test_debug_log_panel_refreshes_when_log_events_change():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    state = AppStateV2()
    panel = DebugLogPanelV2(root, app_state=state)

    event = JobLifecycleLogEvent(
        timestamp=datetime(2025, 1, 1, 12, 0, 0),
        source="pipeline_tab",
        event_type="add_to_job",
        job_id="job-42",
        bundle_id=None,
        draft_size=1,
        message="Test event",
    )
    state.append_log_event(event)

    text = panel._text.get("1.0", tk.END).strip()
    assert "add_to_job" in text
    assert "job=job-42" in text
    assert "Test event" in text

    root.destroy()

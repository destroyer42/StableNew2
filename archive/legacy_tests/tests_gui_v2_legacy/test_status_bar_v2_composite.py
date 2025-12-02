import tkinter as tk

import pytest

from src.controller.webui_connection_controller import WebUIConnectionState
from src.gui.status_bar_v2 import StatusBarV2


@pytest.mark.usefixtures("tk_root")
def test_composite_status_bar_webui_controls(tk_root: tk.Tk):
    called = {"launch": 0, "retry": 0}
    bar = StatusBarV2(tk_root)
    bar.set_webui_launch_callback(lambda: called.__setitem__("launch", called["launch"] + 1))
    bar.set_webui_retry_callback(lambda: called.__setitem__("retry", called["retry"] + 1))

    # state update reflects text
    bar.set_webui_state(WebUIConnectionState.READY)
    tk_root.update_idletasks()
    assert "Ready" in bar.webui_panel.status_label.cget("text")

    # invoke buttons
    bar.webui_panel._on_launch_clicked()
    bar.webui_panel._on_retry_clicked()
    assert called["launch"] == 1
    assert called["retry"] == 1

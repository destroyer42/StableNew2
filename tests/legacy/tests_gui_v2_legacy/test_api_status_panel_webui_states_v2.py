import tkinter as tk

import pytest

from src.controller.webui_connection_controller import WebUIConnectionState
from src.gui.api_status_panel import APIStatusPanel


@pytest.mark.usefixtures("tk_root")
def test_status_panel_updates_and_callbacks(tk_root: tk.Tk):
    called = {"launch": 0, "retry": 0}

    panel = APIStatusPanel(tk_root)
    panel.set_launch_callback(lambda: called.__setitem__("launch", called["launch"] + 1))
    panel.set_retry_callback(lambda: called.__setitem__("retry", called["retry"] + 1))

    panel.set_webui_state(WebUIConnectionState.READY)
    panel.update_idletasks()
    assert "Ready" in panel.status_label.cget("text")

    panel.set_webui_state(WebUIConnectionState.ERROR)
    panel.update_idletasks()
    assert "Error" in panel.status_label.cget("text")

    panel._on_launch_clicked()
    panel._on_retry_clicked()
    assert called["launch"] == 1
    assert called["retry"] == 1

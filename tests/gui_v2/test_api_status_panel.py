from __future__ import annotations

from unittest.mock import patch

from src.controller.webui_connection_controller import WebUIConnectionState
from src.gui.api_status_panel import APIStatusPanel


def test_api_status_panel_updates_without_forcing_idle_flush(tk_root) -> None:
    panel = APIStatusPanel(tk_root)
    panel.pack()

    with patch.object(panel, "update_idletasks", wraps=panel.update_idletasks) as idle_spy:
        panel.set_webui_state(WebUIConnectionState.READY)

    assert panel.status_label.cget("text") == "WebUI: Ready"
    assert idle_spy.called is False

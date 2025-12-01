from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.controller.webui_connection_controller import WebUIConnectionController, WebUIConnectionState


@pytest.mark.parametrize("autostart", [False])
def test_webui_connection_ready_callback(monkeypatch, autostart) -> None:
    ready_cb = MagicMock()
    controller = WebUIConnectionController(
        base_url_provider=lambda: "http://localhost:7860",
        ready_callbacks=[ready_cb],
    )

    monkeypatch.setattr(
        "src.controller.webui_connection_controller.wait_for_webui_ready",
        lambda *args, **kwargs: True,
    )

    state = controller.ensure_connected(autostart=autostart)

    assert state == WebUIConnectionState.READY
    ready_cb.assert_called_once()

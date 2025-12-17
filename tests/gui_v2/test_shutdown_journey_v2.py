from __future__ import annotations

import tkinter as tk

import pytest

from src.app_factory import build_v2_app


@pytest.mark.gui
def test_shutdown_journey_calls_controller_once_per_close() -> None:
    for _ in range(3):
        root = tk.Tk()
        root.withdraw()
        _, _, controller, window = build_v2_app(root=root)
        calls: list[str | None] = []

        def stub(reason: str | None = None, *, _calls=calls) -> None:
            _calls.append(reason)

        controller.shutdown_app = stub
        window.on_app_close()
        try:
            root.update()
        except tk.TclError:
            pass
        window.on_app_close()
        assert calls == ["window-close"]

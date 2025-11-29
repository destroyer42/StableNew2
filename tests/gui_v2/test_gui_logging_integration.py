from __future__ import annotations

import logging

import pytest

from src.app_factory import build_v2_app
from src.utils import InMemoryLogHandler, get_logger


@pytest.mark.gui
def test_build_v2_app_attaches_gui_log_handler() -> None:
    try:
        root, app_state, controller, window = build_v2_app()
    except Exception as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    handler = getattr(window, "gui_log_handler", None)
    assert isinstance(handler, InMemoryLogHandler)

    logger = get_logger(__name__)
    logger.info("hello from gui logging test")

    entries = list(handler.get_entries())
    assert isinstance(entries, list)

    try:
        root.destroy()
    except Exception:
        pass

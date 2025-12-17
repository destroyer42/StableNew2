"""GUI tests for the structured log trace panel filters."""

from __future__ import annotations

import logging
import tkinter as tk

import pytest

from src.gui.log_trace_panel_v2 import LogTracePanelV2
from src.utils import InMemoryLogHandler, LogContext, get_logger, log_with_ctx

pytest.importorskip("tkinter")


def test_log_trace_panel_filters_by_level_and_metadata() -> None:
    handler = InMemoryLogHandler(max_entries=10)
    logger = get_logger("tests.gui_v2.test_log_display_v2")
    logger.addHandler(handler)

    log_with_ctx(
        logger,
        logging.INFO,
        "info entry",
        ctx=LogContext(subsystem="api", job_id="job-1"),
    )
    log_with_ctx(
        logger,
        logging.ERROR,
        "error entry",
        ctx=LogContext(subsystem="job_service", job_id="job-2"),
    )

    root = tk.Tk()
    root.withdraw()
    panel = LogTracePanelV2(root, handler)

    panel._level_filter.set("WARN+")
    entries = handler.get_entries()
    filtered = panel._apply_filter(entries)
    assert all(entry["level"] in ("WARNING", "ERROR", "CRITICAL") for entry in filtered)

    panel._level_filter.set("ALL")
    panel._subsystem_filter.set("job_service")
    filtered = panel._apply_filter(entries)
    assert all(
        (panel._get_payload(entry) or {}).get("subsystem", "").lower() == "job_service"
        for entry in filtered
    )

    panel._job_filter.set("job-1")
    filtered = panel._apply_filter(entries)
    assert all((panel._get_payload(entry) or {}).get("job_id", "") == "job-1" for entry in filtered)

    panel.destroy()
    root.destroy()
    logger.removeHandler(handler)

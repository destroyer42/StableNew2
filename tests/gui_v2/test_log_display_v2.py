"""GUI tests for the structured log trace panel filters."""

from __future__ import annotations

import logging
import re
import tkinter as tk

import pytest

from src.gui.log_trace_panel_v2 import LogTracePanelV2
from src.utils import InMemoryLogHandler, LogContext, get_logger, log_with_ctx

pytest.importorskip("tkinter")


def test_log_trace_panel_filters_by_level_and_metadata() -> None:
    handler = InMemoryLogHandler(max_entries=10)
    logger = get_logger("tests.gui_v2.test_log_display_v2")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    log_with_ctx(
        logger,
        logging.INFO,
        "info entry",
        ctx=LogContext(subsystem="api", stage="txt2img", job_id="job-1"),
        extra_fields={"event": "stage_started"},
    )
    log_with_ctx(
        logger,
        logging.ERROR,
        "error entry",
        ctx=LogContext(subsystem="job_service", stage="upscale", job_id="job-2"),
        extra_fields={"event": "stage_failed"},
    )

    root = tk.Tk()
    root.withdraw()
    panel = LogTracePanelV2(root, handler, audience="trace")

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

    panel._job_filter.set("")
    panel._stage_filter.set("upscale")
    filtered = panel._apply_filter(entries)
    assert all((panel._get_payload(entry) or {}).get("stage", "") == "upscale" for entry in filtered)

    panel._stage_filter.set("")
    panel._event_filter.set("stage_started")
    filtered = panel._apply_filter(entries)
    assert all((panel._get_payload(entry) or {}).get("event", "") == "stage_started" for entry in filtered)

    panel.destroy()
    root.destroy()
    logger.removeHandler(handler)


def test_operator_panel_suppresses_debug_trace_noise() -> None:
    handler = InMemoryLogHandler(max_entries=10)
    logger = get_logger("tests.gui_v2.test_log_display_v2.operator")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    log_with_ctx(
        logger,
        logging.DEBUG,
        "payload built",
        ctx=LogContext(subsystem="pipeline", stage="txt2img", job_id="job-1"),
        extra_fields={"event": "payload_built"},
    )
    log_with_ctx(
        logger,
        logging.INFO,
        "stage started",
        ctx=LogContext(subsystem="pipeline", stage="txt2img", job_id="job-1"),
        extra_fields={"event": "stage_started"},
    )

    root = tk.Tk()
    root.withdraw()
    panel = LogTracePanelV2(root, handler, audience="operator")
    filtered = panel._apply_filter(handler.get_entries())
    assert len(filtered) == 1
    assert (panel._get_payload(filtered[0]) or {}).get("event") == "stage_started"
    panel.refresh()
    content = panel._log_text.get("1.0", tk.END).strip()
    assert re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3} \[INFO \| pipeline \| txt2img\]", content)

    panel.destroy()
    root.destroy()
    logger.removeHandler(handler)

from __future__ import annotations

import logging
import tkinter as tk

import pytest

from src.gui.log_trace_panel_v2 import LogTracePanelV2
from src.utils import InMemoryLogHandler, LogContext, get_logger, log_with_ctx


def test_log_trace_panel_v2_smoke():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    logger = get_logger(__name__)
    logger.addHandler(handler)

    panel = LogTracePanelV2(root, log_handler=handler, audience="trace")
    panel.refresh()
    assert panel._log_text.get("1.0", tk.END).strip() == ""

    logger.error("Test error")
    panel.refresh()
    content = panel._log_text.get("1.0", tk.END).strip()
    assert "Test error" in content

    logger.removeHandler(handler)
    root.destroy()


def test_log_trace_panel_highlights_structured_errors() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    logger = get_logger(__name__)
    logger.addHandler(handler)

    panel = LogTracePanelV2(root, log_handler=handler, audience="trace")
    log_with_ctx(
        logger,
        logging.ERROR,
        "Structured error",
        ctx=LogContext(subsystem="pipeline"),
        extra_fields={
            "error_envelope": {
                "error_type": "PipelineError",
                "subsystem": "pipeline",
                "stage": "TXT2IMG",
                "severity": "ERROR",
            }
        },
    )
    panel.refresh()
    content = panel._log_text.get("1.0", tk.END)
    assert "PipelineError" in content
    assert "stage=TXT2IMG" in content.lower() or "txt2img" in content

    logger.removeHandler(handler)
    root.destroy()


def test_log_trace_panel_renders_repeat_summary_and_filters_event_stage() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    logger = get_logger(f"{__name__}.repeat")
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
        logging.DEBUG,
        "payload built",
        ctx=LogContext(subsystem="pipeline", stage="txt2img", job_id="job-1"),
        extra_fields={"event": "payload_built"},
    )

    panel = LogTracePanelV2(root, log_handler=handler, audience="trace")
    panel._event_filter.set("payload_built")
    panel._stage_filter.set("txt2img")
    panel.refresh()
    content = panel._log_text.get("1.0", tk.END)
    assert "repeated 2x" in content
    assert "payload_built" in content

    logger.removeHandler(handler)
    root.destroy()

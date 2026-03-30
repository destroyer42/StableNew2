from __future__ import annotations

import logging
import re
import tkinter as tk
from unittest.mock import patch

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
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    panel = LogTracePanelV2(root, log_handler=handler, audience="trace")
    panel.refresh()
    assert panel._log_text.get("1.0", tk.END).strip() == ""

    logger.error("Test error")
    panel.refresh()
    content = panel._log_text.get("1.0", tk.END).strip()
    assert re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3} \[ERROR\]", content)
    assert "Test error" in content

    logger.removeHandler(handler)
    root.destroy()


def test_log_trace_panel_v2_uses_dark_text_surface() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=5)
    panel = LogTracePanelV2(root, log_handler=handler, audience="trace")

    assert panel._log_text.cget("bg") not in {"white", "#ffffff", "SystemWindow"}
    assert panel._log_text.cget("insertbackground") != ""

    root.destroy()


def test_log_trace_panel_highlights_structured_errors() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    logger = get_logger(__name__)
    logger.setLevel(logging.DEBUG)
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
    assert re.search(r"\d{2}:\d{2}:\d{2}\.\d{3} \[DEBUG \| pipeline \| txt2img", content)
    assert "repeated 2x" in content
    assert "payload_built" in content

    logger.removeHandler(handler)
    root.destroy()


def test_log_trace_panel_skips_heavy_refresh_when_collapsed() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    panel = LogTracePanelV2(root, log_handler=handler, audience="trace")
    panel._set_expanded(False)

    def _unexpected_entries():
        raise AssertionError("collapsed refresh should not request log entries")

    handler.get_entries = _unexpected_entries  # type: ignore[assignment]

    panel.refresh()

    root.destroy()


def test_log_trace_panel_skips_rerender_when_log_version_is_unchanged() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    logger = get_logger(f"{__name__}.version")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    panel = LogTracePanelV2(root, log_handler=handler, audience="trace")
    logger.info("Versioned log line")
    panel.refresh(force=True)

    calls = {"count": 0}
    original_get_entries = handler.get_entries

    def _tracked_entries():
        calls["count"] += 1
        return original_get_entries()

    handler.get_entries = _tracked_entries  # type: ignore[assignment]
    panel.refresh()

    assert calls["count"] == 0

    logger.removeHandler(handler)
    root.destroy()


def test_log_trace_panel_appends_new_lines_without_full_rebuild() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    logger = get_logger(f"{__name__}.append")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    panel = LogTracePanelV2(root, log_handler=handler, audience="operator")
    logger.info("First line")
    panel.refresh(force=True)

    with patch.object(panel._log_text, "delete", wraps=panel._log_text.delete) as delete_spy:
        logger.info("Second line")
        panel.refresh(force=True)
        delete_spy.assert_not_called()

    content = panel._log_text.get("1.0", tk.END)
    assert "First line" in content
    assert "Second line" in content

    logger.removeHandler(handler)
    root.destroy()


def test_log_trace_panel_handles_bounded_rollover_incrementally() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=3)
    logger = get_logger(f"{__name__}.rollover")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    panel = LogTracePanelV2(root, log_handler=handler, audience="operator")
    logger.info("line-1")
    logger.info("line-2")
    logger.info("line-3")
    panel.refresh(force=True)

    logger.info("line-4")
    panel.refresh(force=True)

    snapshot = panel.get_diagnostics_snapshot()
    content = panel._log_text.get("1.0", tk.END)
    assert "line-1" not in content
    assert "line-2" in content
    assert "line-3" in content
    assert "line-4" in content
    assert snapshot["rollover_count"] >= 1

    logger.removeHandler(handler)
    root.destroy()


def test_log_trace_panel_batches_same_level_full_rebuild_inserts() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    logger = get_logger(f"{__name__}.batch_rebuild")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    panel = LogTracePanelV2(root, log_handler=handler, audience="operator")
    logger.info("line-a")
    logger.info("line-b")
    logger.info("line-c")

    with patch.object(panel._log_text, "insert", wraps=panel._log_text.insert) as insert_spy:
        panel.refresh(force=True)

    assert insert_spy.call_count == 1

    logger.removeHandler(handler)
    root.destroy()


def test_log_trace_panel_updates_repeated_last_line_incrementally() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    logger = get_logger(f"{__name__}.repeat_tail")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    panel = LogTracePanelV2(root, log_handler=handler, audience="operator")
    logger.info("same line")
    panel.refresh(force=True)

    logger.info("same line")
    panel.refresh(force=True)

    snapshot = panel.get_diagnostics_snapshot()
    content = panel._log_text.get("1.0", tk.END)
    assert "repeated 2x" in content
    assert snapshot["tail_update_count"] >= 1

    logger.removeHandler(handler)
    root.destroy()

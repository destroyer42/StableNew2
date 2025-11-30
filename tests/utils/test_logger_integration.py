from __future__ import annotations

import logging

from src.utils import InMemoryLogHandler, LogContext, get_logger, log_with_ctx


def test_log_with_ctx_appends_context() -> None:
    logger = get_logger(__name__)
    handler = InMemoryLogHandler(max_entries=10)
    logger.addHandler(handler)
    original_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        ctx = LogContext(run_id="run-123", stage="txt2img", subsystem="pipeline")
        log_with_ctx(logger, logging.INFO, "stage started", ctx=ctx)

        entries = list(handler.get_entries())
        assert len(entries) >= 1
        msg = entries[-1]["message"]
        assert "run-123" in msg
        assert "txt2img" in msg
        assert "pipeline" in msg
    finally:
        logger.setLevel(original_level)


def test_inmemory_log_handler_respects_max_entries() -> None:
    logger = get_logger(__name__)
    handler = InMemoryLogHandler(max_entries=3)
    logger.addHandler(handler)
    original_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        for i in range(10):
            logger.info("message-%s", i)

        entries = list(handler.get_entries())
        assert len(entries) == 3
        assert any("message-9" in entry["message"] for entry in entries)
    finally:
        logger.setLevel(original_level)


def test_attach_gui_log_handler() -> None:
    """Test that attach_gui_log_handler creates and attaches handler."""
    from src.utils import attach_gui_log_handler
    handler = attach_gui_log_handler(max_entries=10)
    assert isinstance(handler, InMemoryLogHandler)
    assert handler._max_entries == 10

    # Check it's attached to root logger
    root_logger = logging.getLogger()
    assert handler in root_logger.handlers

    # Test logging
    root_logger.info("test message")
    entries = list(handler.get_entries())
    assert len(entries) >= 1
    assert "test message" in entries[-1]["message"]

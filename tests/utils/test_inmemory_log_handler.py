from __future__ import annotations

import time

from src.utils import InMemoryLogHandler, get_logger


def test_inmemory_log_handler_captures_messages() -> None:
    logger = get_logger(__name__)
    handler = InMemoryLogHandler(max_entries=10)
    logger.addHandler(handler)
    original_level = logger.level
    logger.setLevel("INFO")

    try:
        logger.info("hello world")

        entries = list(handler.get_entries())
        assert len(entries) == 1
        assert entries[0]["message"]
        assert entries[0]["level"] == "INFO"
    finally:
        logger.setLevel(original_level)
        logger.removeHandler(handler)


def test_inmemory_log_handler_collapses_repeated_entries() -> None:
    logger = get_logger(f"{__name__}.repeat")
    handler = InMemoryLogHandler(max_entries=10)
    logger.addHandler(handler)
    original_level = logger.level
    logger.setLevel("INFO")

    try:
        logger.warning("same event")
        time.sleep(0.01)
        logger.warning("same event")

        entries = list(handler.get_entries())
        assert len(entries) == 1
        assert entries[0]["message"]
        assert entries[0]["repeat_count"] == 2
        assert entries[0]["last_created"] >= entries[0]["first_created"]
    finally:
        logger.setLevel(original_level)
        logger.removeHandler(handler)

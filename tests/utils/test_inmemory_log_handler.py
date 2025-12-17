from __future__ import annotations

from src.utils import InMemoryLogHandler, get_logger


def test_inmemory_log_handler_captures_messages() -> None:
    logger = get_logger(__name__)
    handler = InMemoryLogHandler(max_entries=10)
    logger.addHandler(handler)

    logger.info("hello world")

    entries = list(handler.get_entries())
    assert len(entries) == 1
    assert entries[0]["message"]
    assert entries[0]["level"] == "INFO"

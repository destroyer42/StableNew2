import logging
from src.utils.logger import InMemoryLogHandler, get_logger

def test_inmemory_log_handler():
    logger = get_logger('test')
    handler = InMemoryLogHandler(max_entries=3)
    logger.addHandler(handler)
    original_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        for i in range(5):
            logger.info("message-%s", i)

        entries = list(handler.get_entries())
        assert len(entries) == 3
        assert any("message-4" in entry["message"] for entry in entries)
        print("test_inmemory_log_handler_respects_max_entries passed")
    finally:
        logger.setLevel(original_level)

def test_attach_gui_log_handler():
    from src.utils.logger import attach_gui_log_handler
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
    print("test_attach_gui_log_handler passed")

if __name__ == "__main__":
    test_inmemory_log_handler()
    test_attach_gui_log_handler()
    print("All tests passed")
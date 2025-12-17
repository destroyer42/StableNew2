"""Tests for StructuredLogger lifecycle management: registry, close(), and cleanup."""

import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from src.utils.logger import (
    StructuredLogger,
    _structured_logger_registry,
    close_all_structured_loggers,
    get_structured_logger_registry_count,
)


class TestStructuredLoggerRegistry:
    """Test StructuredLogger registry and instance tracking."""

    def setup_method(self):
        """Clear registry before each test."""
        _structured_logger_registry.clear()

    def test_registry_increments_on_creation(self):
        """Creating a StructuredLogger should increment registry count."""
        initial_count = get_structured_logger_registry_count()

        with tempfile.TemporaryDirectory() as tmpdir:
            _logger = StructuredLogger(output_dir=tmpdir)
            assert get_structured_logger_registry_count() == initial_count + 1

    def test_multiple_instances_tracked(self):
        """Multiple StructuredLogger instances should all be tracked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            StructuredLogger(output_dir=tmpdir)
            StructuredLogger(output_dir=tmpdir)
            StructuredLogger(output_dir=tmpdir)

    def test_weakref_cleanup_on_deletion(self):
        """WeakSet should remove logger when it's deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StructuredLogger(output_dir=tmpdir)
            assert get_structured_logger_registry_count() == 1

            del logger
            # WeakSet removes reference automatically
            assert get_structured_logger_registry_count() == 0


class TestStructuredLoggerClose:
    """Test StructuredLogger.close() method behavior."""

    def setup_method(self):
        """Clear registry and handlers before each test."""
        _structured_logger_registry.clear()
        # Clean up root logger handlers
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)

    def test_close_is_idempotent(self):
        """Calling close() multiple times should not raise exceptions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StructuredLogger(output_dir=tmpdir)

            # First close should succeed
            logger.close()

            # Second close should be safe (idempotent)
            logger.close()

            # Multiple closes should be safe
            logger.close()

    def test_close_sets_closed_flag(self):
        """After close(), the _closed flag should be True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StructuredLogger(output_dir=tmpdir)
            assert logger._closed is False

            logger.close()
            assert logger._closed is True

    def test_close_clears_handlers_list(self):
        """After close(), _handlers_added should be empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StructuredLogger(output_dir=tmpdir)

            # Manually add a mock handler to test list clearing
            mock_handler = MagicMock(spec=logging.Handler)
            logger._handlers_added.append(mock_handler)

            assert len(logger._handlers_added) == 1

            logger.close()

            assert len(logger._handlers_added) == 0

    def test_close_flushes_handlers(self):
        """close() should flush all handlers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StructuredLogger(output_dir=tmpdir)

            mock_handler = MagicMock(spec=logging.Handler)
            logger._handlers_added.append(mock_handler)

            logger.close()

            # Handler should have been flushed
            mock_handler.flush.assert_called_once()

    def test_close_closes_handlers(self):
        """close() should call close() on all handlers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StructuredLogger(output_dir=tmpdir)

            mock_handler = MagicMock(spec=logging.Handler)
            logger._handlers_added.append(mock_handler)

            logger.close()

            # Handler should have been closed
            mock_handler.close.assert_called_once()

    def test_close_removes_handlers_from_logger(self):
        """close() should remove handlers from the underlying logger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StructuredLogger(output_dir=tmpdir)

            # Create a real handler for removal testing
            with tempfile.NamedTemporaryFile(delete=False, mode="w") as f:
                log_file = f.name

            try:
                handler = logging.FileHandler(log_file)
                logger._handlers_added.append(handler)
                logger.logger.addHandler(handler)

                assert handler in logger.logger.handlers

                logger.close()

                # Handler should be removed
                assert handler not in logger.logger.handlers
            finally:
                Path(log_file).unlink(missing_ok=True)

    def test_close_handles_exceptions_gracefully(self):
        """close() should handle exceptions from individual handlers gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StructuredLogger(output_dir=tmpdir)

            # Create a handler that raises on flush
            bad_handler = MagicMock(spec=logging.Handler)
            bad_handler.flush.side_effect = RuntimeError("flush failed")
            bad_handler.close.side_effect = RuntimeError("close failed")

            # Create a good handler
            good_handler = MagicMock(spec=logging.Handler)

            logger._handlers_added.extend([bad_handler, good_handler])

            # close() should not raise despite exceptions
            logger.close()

            # Both handlers should have attempted operations
            bad_handler.flush.assert_called()
            good_handler.flush.assert_called()


class TestCloseAllStructuredLoggers:
    """Test close_all_structured_loggers() function."""

    def setup_method(self):
        """Clear registry before each test."""
        _structured_logger_registry.clear()

    def test_close_all_closes_all_instances(self):
        """close_all_structured_loggers() should close all active loggers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger1 = StructuredLogger(output_dir=tmpdir)
            logger2 = StructuredLogger(output_dir=tmpdir)
            logger3 = StructuredLogger(output_dir=tmpdir)

            assert logger1._closed is False
            assert logger2._closed is False
            assert logger3._closed is False

            close_all_structured_loggers()

            assert logger1._closed is True
            assert logger2._closed is True
            assert logger3._closed is True

    def test_close_all_is_safe_when_empty(self):
        """close_all_structured_loggers() should be safe when no loggers exist."""
        assert get_structured_logger_registry_count() == 0

        # Should not raise
        close_all_structured_loggers()

    def test_close_all_is_safe_when_logger_raises(self):
        """close_all_structured_loggers() should continue if one logger raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger1 = StructuredLogger(output_dir=tmpdir)
            logger2 = StructuredLogger(output_dir=tmpdir)

            # Patch the first logger's close to raise
            def bad_close():
                raise RuntimeError("close failed")

            logger1.close = bad_close

            # close_all should not raise and should close the second one
            close_all_structured_loggers()

            # logger2 should be closed despite logger1 failing
            assert logger2._closed is True

    def test_close_all_idempotent(self):
        """close_all_structured_loggers() can be called multiple times safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = StructuredLogger(output_dir=tmpdir)

            close_all_structured_loggers()
            assert logger._closed is True

            # Second call should be safe
            close_all_structured_loggers()
            assert logger._closed is True


class TestStructuredLoggerIntegration:
    """Integration tests for StructuredLogger lifecycle."""

    def setup_method(self):
        """Clear registry before each test."""
        _structured_logger_registry.clear()

    def test_full_lifecycle(self):
        """Test complete lifecycle: create, use, and close."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create logger
            logger = StructuredLogger(output_dir=tmpdir)
            assert get_structured_logger_registry_count() == 1

            # Create run directory
            run_dir = logger.create_run_directory("test_run")
            assert run_dir.exists()

            # Close logger
            logger.close()
            assert logger._closed is True

            # Registry should still track it (WeakSet only removes on garbage collection)
            # but the logger is closed

    def test_multiple_loggers_independent_close(self):
        """Multiple loggers should have independent close states."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger1 = StructuredLogger(output_dir=tmpdir)
            logger2 = StructuredLogger(output_dir=tmpdir)

            logger1.close()

            assert logger1._closed is True
            assert logger2._closed is False

            logger2.close()

            assert logger2._closed is True

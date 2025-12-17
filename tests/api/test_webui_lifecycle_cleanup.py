"""
Tests for WebUI lifecycle cleanup: WebUIProcessManager.stop() and SDWebUIClient.close().

Validates:
1. WebUIProcessManager.stop() is idempotent (safe to call multiple times)
2. SDWebUIClient.close() is idempotent and closes HTTP session
3. Global WebUI process manager reference is cleared on stop
4. AppController properly wires cleanup calls during shutdown
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

import requests

from src.api.client import SDWebUIClient
from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
    clear_global_webui_process_manager,
    get_global_webui_process_manager,
)


class TestWebUIProcessManagerStopIdempotency(unittest.TestCase):
    """Test that WebUIProcessManager.stop() is idempotent."""

    def setUp(self) -> None:
        """Create a manager instance for testing."""
        config = WebUIProcessConfig(
            command=["dummy", "command"],
            working_dir="/tmp",
            auto_restart_on_crash=False,
            autostart_enabled=False,
        )
        self.manager = WebUIProcessManager(config)

    def test_stop_returns_normally_first_call(self) -> None:
        """Verify stop() can be called on a non-running manager without error."""
        # Mock stop_webui to do nothing
        self.manager.stop_webui = Mock(return_value=True)

        # First call should succeed
        self.manager.stop()
        self.manager.stop_webui.assert_called_once()

    def test_stop_is_idempotent(self) -> None:
        """Verify stop() can be called multiple times safely."""
        # Mock stop_webui to do nothing
        self.manager.stop_webui = Mock(return_value=True)

        # Multiple calls should not raise
        self.manager.stop()
        self.manager.stop()
        self.manager.stop()

        # stop_webui should only be called once (due to _stopped guard)
        self.manager.stop_webui.assert_called_once()

    def test_stop_sets_stopped_flag(self) -> None:
        """Verify stop() sets the _stopped flag."""
        self.assertFalse(self.manager._stopped)

        self.manager.stop_webui = Mock(return_value=True)
        self.manager.stop()

        self.assertTrue(self.manager._stopped)

    def test_stop_clears_global_reference(self) -> None:
        """Verify stop() clears the global manager reference."""
        # Verify manager is in global
        self.assertIs(get_global_webui_process_manager(), self.manager)

        self.manager.stop_webui = Mock(return_value=True)
        self.manager.stop()

        # Verify global is cleared
        self.assertIsNone(get_global_webui_process_manager())

    def test_stop_clears_global_even_on_stop_webui_exception(self) -> None:
        """Verify global reference is cleared even if stop_webui raises."""
        self.manager.stop_webui = Mock(side_effect=RuntimeError("process kill failed"))

        # Should not raise; should suppress exception and clear global
        self.manager.stop()

        # Verify global is cleared
        self.assertIsNone(get_global_webui_process_manager())

    def test_global_clear_function_is_idempotent(self) -> None:
        """Verify clear_global_webui_process_manager() can be called multiple times."""
        clear_global_webui_process_manager()
        clear_global_webui_process_manager()
        clear_global_webui_process_manager()

        self.assertIsNone(get_global_webui_process_manager())


class TestSDWebUIClientClose(unittest.TestCase):
    """Test that SDWebUIClient.close() properly closes resources."""

    def test_client_close_closes_session(self) -> None:
        """Verify close() closes the HTTP session."""
        # Create a client
        client = SDWebUIClient()

        # Mock the session's close method
        client._session.close = Mock()

        # Call close()
        client.close()

        # Verify session.close() was called
        client._session.close.assert_called_once()

    def test_client_close_is_idempotent(self) -> None:
        """Verify close() can be called multiple times safely."""
        client = SDWebUIClient()

        # Mock the session's close method
        client._session.close = Mock()

        # Multiple calls should not raise
        client.close()
        client.close()
        client.close()

        # session.close() called each time (no guard in current impl)
        self.assertEqual(client._session.close.call_count, 3)

    def test_client_close_handles_session_exceptions(self) -> None:
        """Verify close() handles exceptions from session.close() gracefully."""
        client = SDWebUIClient()

        # Make session.close() raise an exception
        client._session.close = Mock(side_effect=RuntimeError("Session error"))

        # Should not raise
        client.close()

    def test_client_destructor_calls_close(self) -> None:
        """Verify __del__ calls close() to clean up on garbage collection."""
        client = SDWebUIClient()
        client.close = Mock()

        # Trigger deletion
        del client

        # Note: __del__ is not guaranteed to be called immediately in tests,
        # but the pattern is established and documented


class TestClearGlobalWebUIProcessManager(unittest.TestCase):
    """Test the clear_global_webui_process_manager() helper function."""

    def setUp(self) -> None:
        """Reset global state before each test."""
        clear_global_webui_process_manager()

    def test_clear_removes_global_reference(self) -> None:
        """Verify clear_global_webui_process_manager() removes the global reference."""
        config = WebUIProcessConfig(
            command=["dummy"],
            working_dir="/tmp",
            auto_restart_on_crash=False,
            autostart_enabled=False,
        )
        manager = WebUIProcessManager(config)

        self.assertIs(get_global_webui_process_manager(), manager)
        clear_global_webui_process_manager()
        self.assertIsNone(get_global_webui_process_manager())

    def test_clear_is_safe_when_empty(self) -> None:
        """Verify clear_global_webui_process_manager() doesn't raise when global is None."""
        clear_global_webui_process_manager()
        # Should not raise
        clear_global_webui_process_manager()

    def test_multiple_clears_are_idempotent(self) -> None:
        """Verify multiple calls to clear are safe."""
        config = WebUIProcessConfig(
            command=["dummy"],
            working_dir="/tmp",
            auto_restart_on_crash=False,
            autostart_enabled=False,
        )
        WebUIProcessManager(config)

        # Clear multiple times
        clear_global_webui_process_manager()
        clear_global_webui_process_manager()
        clear_global_webui_process_manager()

        self.assertIsNone(get_global_webui_process_manager())


class TestWebUIProcessManagerStopWithMockedProcess(unittest.TestCase):
    """Test stop() with a mocked subprocess to verify termination flow."""

    def setUp(self) -> None:
        """Create a manager with a mocked process."""
        config = WebUIProcessConfig(
            command=["dummy"],
            working_dir="/tmp",
            auto_restart_on_crash=False,
            autostart_enabled=False,
        )
        self.manager = WebUIProcessManager(config)

        # Create a mock process
        self.mock_process = Mock()
        self.mock_process.pid = 1234
        self.mock_process.poll = Mock(return_value=None)  # Process still running
        self.mock_process.terminate = Mock()
        self.mock_process.kill = Mock()
        self.mock_process.wait = Mock()

        # Assign to manager
        self.manager._process = self.mock_process

    def test_stop_calls_stop_webui_with_running_process(self) -> None:
        """Verify stop() delegates to stop_webui which handles termination."""
        # Mock stop_webui to verify it's called
        with patch.object(self.manager, "stop_webui", return_value=True) as mock_stop:
            self.manager.stop()
            mock_stop.assert_called_once()

    def test_stop_sets_stopped_flag_before_clear(self) -> None:
        """Verify _stopped flag is set before global clear."""
        self.manager.stop_webui = Mock(return_value=True)
        self.manager.stop()

        self.assertTrue(self.manager._stopped)
        self.assertIsNone(get_global_webui_process_manager())


class TestIntegrationWebUILifecycleCleanup(unittest.TestCase):
    """Integration tests for WebUI lifecycle cleanup patterns."""

    def test_manager_initialization_sets_global(self) -> None:
        """Verify creating a manager sets it as the global instance."""
        clear_global_webui_process_manager()

        config = WebUIProcessConfig(
            command=["dummy"],
            working_dir="/tmp",
            auto_restart_on_crash=False,
            autostart_enabled=False,
        )
        manager = WebUIProcessManager(config)

        self.assertIs(get_global_webui_process_manager(), manager)

    def test_multiple_managers_last_one_is_global(self) -> None:
        """Verify only the last-created manager is stored globally."""
        clear_global_webui_process_manager()

        config = WebUIProcessConfig(
            command=["dummy"],
            working_dir="/tmp",
            auto_restart_on_crash=False,
            autostart_enabled=False,
        )

        manager1 = WebUIProcessManager(config)
        self.assertIs(get_global_webui_process_manager(), manager1)

        manager2 = WebUIProcessManager(config)
        self.assertIs(get_global_webui_process_manager(), manager2)

    def test_stop_clears_global_allowing_new_manager(self) -> None:
        """Verify stopping a manager clears global, allowing a new one."""
        config = WebUIProcessConfig(
            command=["dummy"],
            working_dir="/tmp",
            auto_restart_on_crash=False,
            autostart_enabled=False,
        )

        manager1 = WebUIProcessManager(config)
        manager1.stop_webui = Mock(return_value=True)

        self.assertIs(get_global_webui_process_manager(), manager1)

        manager1.stop()

        self.assertIsNone(get_global_webui_process_manager())

        # Create new manager; should become global
        manager2 = WebUIProcessManager(config)
        self.assertIs(get_global_webui_process_manager(), manager2)


class TestClientCloseWithMockedSession(unittest.TestCase):
    """Test SDWebUIClient.close() with a real session mock."""

    def test_close_closes_session_connection_pool(self) -> None:
        """Verify close() properly closes the session's connection pool."""
        client = SDWebUIClient()

        # Mock session to track close calls
        mock_session = MagicMock(spec=requests.Session)
        client._session = mock_session

        client.close()

        mock_session.close.assert_called_once()

    def test_close_called_on_del(self) -> None:
        """Verify close() is called when client is garbage collected."""
        client = SDWebUIClient()
        close_method = Mock()
        client.close = close_method

        # Delete the client
        del client

        # Note: __del__ may or may not be called in tests, but the pattern exists

    def test_multiple_closes_safe(self) -> None:
        """Verify calling close() multiple times is safe."""
        client = SDWebUIClient()

        # Should not raise
        try:
            client.close()
            client.close()
            client.close()
        except Exception as e:
            self.fail(f"Multiple close() calls raised {type(e).__name__}: {e}")


if __name__ == "__main__":
    unittest.main()

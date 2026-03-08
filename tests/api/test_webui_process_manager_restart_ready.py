"""Tests for WebUIProcessManager.restart_webui() integration with wait_until_ready."""

from __future__ import annotations

from unittest.mock import Mock, patch

from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager


class TestRestartWebuiSuccess:
    """Test restart_webui succeeds when wait_until_ready returns True."""

    def test_restart_returns_true_when_wait_ready_succeeds(self):
        """Verify restart_webui returns True when readiness check passes."""
        config = WebUIProcessConfig(
            command=["dummy_cmd"],
            base_url="http://127.0.0.1:7860",
        )
        manager = WebUIProcessManager(config)

        # Stub start/stop/is_running and readiness check
        with (
            patch.object(manager, "stop_webui"),
            patch.object(manager, "start"),
            patch.object(manager, "is_running", return_value=False),
            patch.object(manager, "get_stdout_tail_text", return_value=""),
            patch("src.api.webui_api.WebUIAPI") as mock_webui_api_class,
        ):
            mock_api_instance = Mock()
            mock_api_instance.wait_until_true_ready = Mock()  # No exception = success
            mock_webui_api_class.return_value = mock_api_instance

            result = manager.restart_webui(wait_ready=True, max_attempts=6)

        assert result is True
        mock_api_instance.wait_until_true_ready.assert_called_once()

    def test_restart_returns_false_when_wait_ready_fails(self):
        """Verify restart_webui returns False when readiness check fails."""
        from src.api.webui_api import WebUIReadinessTimeout
        
        config = WebUIProcessConfig(
            command=["dummy_cmd"],
            base_url="http://127.0.0.1:7860",
        )
        manager = WebUIProcessManager(config)

        with (
            patch.object(manager, "stop_webui"),
            patch.object(manager, "start"),
            patch.object(manager, "is_running", return_value=False),
            patch.object(manager, "get_stdout_tail_text", return_value=""),
            patch("src.api.webui_api.WebUIAPI") as mock_webui_api_class,
        ):
            mock_api_instance = Mock()
            mock_api_instance.wait_until_true_ready = Mock(side_effect=WebUIReadinessTimeout(
                message="Readiness timeout",
                total_waited=60.0,
                checks_status={},
                stdout_tail=""
            ))
            mock_webui_api_class.return_value = mock_api_instance

            result = manager.restart_webui(wait_ready=True, max_attempts=6)

        assert result is False
        mock_api_instance.wait_until_true_ready.assert_called_once()

    def test_restart_without_wait_ready_returns_true(self):
        """Verify restart_webui returns True when wait_ready=False."""
        config = WebUIProcessConfig(
            command=["dummy_cmd"],
            base_url="http://127.0.0.1:7860",
        )
        manager = WebUIProcessManager(config)

        with (
            patch.object(manager, "stop_webui"),
            patch.object(manager, "start"),
            patch.object(manager, "is_running", return_value=False),
        ):
            result = manager.restart_webui(wait_ready=False)

        assert result is True


class TestRestartWebuiExceptionHandling:
    """Test restart_webui handles exceptions in wait_until_ready."""

    def test_restart_returns_false_when_wait_until_ready_raises(self):
        """Verify restart_webui returns False when wait_until_true_ready raises exception."""
        config = WebUIProcessConfig(
            command=["dummy_cmd"],
            base_url="http://127.0.0.1:7860",
        )
        manager = WebUIProcessManager(config)

        with (
            patch.object(manager, "stop_webui"),
            patch.object(manager, "start"),
            patch.object(manager, "is_running", return_value=False),
            patch.object(manager, "get_stdout_tail_text", return_value=""),
            patch("src.api.webui_api.WebUIAPI") as mock_webui_api_class,
        ):
            mock_api_instance = Mock()
            mock_api_instance.wait_until_true_ready = Mock(side_effect=RuntimeError("API check failed"))
            mock_webui_api_class.return_value = mock_api_instance

            result = manager.restart_webui(wait_ready=True, max_attempts=6)

        assert result is False

    def test_restart_returns_false_when_start_fails(self):
        """Verify restart_webui returns False when process start fails."""
        config = WebUIProcessConfig(
            command=["dummy_cmd"],
            base_url="http://127.0.0.1:7860",
        )
        manager = WebUIProcessManager(config)

        with (
            patch.object(manager, "stop_webui"),
            patch.object(manager, "start", side_effect=RuntimeError("Start failed")),
        ):
            result = manager.restart_webui(wait_ready=True, max_attempts=6)

        assert result is False


class TestRestartWebuiParameterPassing:
    """Test restart_webui passes parameters correctly to wait_until_ready."""

    def test_custom_max_attempts_passed_to_wait_until_ready(self):
        """Verify restart_webui uses wait_until_true_ready with fixed timeout."""
        config = WebUIProcessConfig(
            command=["dummy_cmd"],
            base_url="http://127.0.0.1:7860",
        )
        manager = WebUIProcessManager(config)

        with (
            patch.object(manager, "stop_webui"),
            patch.object(manager, "start"),
            patch.object(manager, "is_running", return_value=False),
            patch.object(manager, "get_stdout_tail_text", return_value=""),
            patch("src.api.webui_api.WebUIAPI") as mock_webui_api_class,
        ):
            mock_api_instance = Mock()
            mock_api_instance.wait_until_true_ready = Mock()
            mock_webui_api_class.return_value = mock_api_instance

            result = manager.restart_webui(
                wait_ready=True, max_attempts=10, base_delay=2.0, max_delay=16.0
            )

        assert result is True
        # wait_until_true_ready uses fixed timeout, not max_attempts
        mock_api_instance.wait_until_true_ready.assert_called_once()

    def test_custom_delays_passed_to_wait_until_ready(self):
        """Verify restart_webui uses wait_until_true_ready with fixed poll interval."""
        config = WebUIProcessConfig(
            command=["dummy_cmd"],
            base_url="http://127.0.0.1:7860",
        )
        manager = WebUIProcessManager(config)

        with (
            patch.object(manager, "stop_webui"),
            patch.object(manager, "start"),
            patch.object(manager, "is_running", return_value=False),
            patch.object(manager, "get_stdout_tail_text", return_value=""),
            patch("src.api.webui_api.WebUIAPI") as mock_webui_api_class,
        ):
            mock_api_instance = Mock()
            mock_api_instance.wait_until_true_ready = Mock()
            mock_webui_api_class.return_value = mock_api_instance

            result = manager.restart_webui(
                wait_ready=True, max_attempts=5, base_delay=0.5, max_delay=4.0
            )

        assert result is True
        # wait_until_true_ready uses fixed timeout_s and poll_interval_s
        mock_api_instance.wait_until_true_ready.assert_called_once()


class TestRestartWebuiClientManagement:
    """Test restart_webui properly manages SDWebUIClient lifecycle."""

    def test_client_closed_on_success(self):
        """Verify SDWebUIClient is closed after successful wait_until_true_ready."""
        config = WebUIProcessConfig(
            command=["dummy_cmd"],
            base_url="http://127.0.0.1:7860",
        )
        manager = WebUIProcessManager(config)

        with (
            patch.object(manager, "stop_webui"),
            patch.object(manager, "start"),
            patch.object(manager, "is_running", return_value=False),
            patch.object(manager, "get_stdout_tail_text", return_value=""),
            patch("src.api.client.SDWebUIClient") as mock_client_class,
            patch("src.api.webui_api.WebUIAPI") as mock_webui_api_class,
        ):
            mock_client = Mock()
            mock_client.close = Mock()
            mock_client_class.return_value = mock_client

            mock_api_instance = Mock()
            mock_api_instance.wait_until_true_ready = Mock()
            mock_webui_api_class.return_value = mock_api_instance

            result = manager.restart_webui(wait_ready=True, max_attempts=6)

        assert result is True
        mock_client.close.assert_called_once()

    def test_client_closed_on_failure(self):
        """Verify SDWebUIClient is closed after failed wait_until_true_ready."""
        from src.api.webui_api import WebUIReadinessTimeout
        
        config = WebUIProcessConfig(
            command=["dummy_cmd"],
            base_url="http://127.0.0.1:7860",
        )
        manager = WebUIProcessManager(config)

        with (
            patch.object(manager, "stop_webui"),
            patch.object(manager, "start"),
            patch.object(manager, "is_running", return_value=False),
            patch.object(manager, "get_stdout_tail_text", return_value=""),
            patch("src.api.client.SDWebUIClient") as mock_client_class,
            patch("src.api.webui_api.WebUIAPI") as mock_webui_api_class,
        ):
            mock_client = Mock()
            mock_client.close = Mock()
            mock_client_class.return_value = mock_client

            mock_api_instance = Mock()
            mock_api_instance.wait_until_true_ready = Mock(side_effect=WebUIReadinessTimeout(
                message="Readiness timeout",
                total_waited=60.0,
                checks_status={},
                stdout_tail=""
            ))
            mock_webui_api_class.return_value = mock_api_instance

            result = manager.restart_webui(wait_ready=True, max_attempts=6)

        assert result is False
        mock_client.close.assert_called_once()

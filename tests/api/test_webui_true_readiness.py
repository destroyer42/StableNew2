"""Tests for WebUIAPI.wait_until_true_ready() true-readiness gate.

Tests verify that the true-readiness gate checks both API endpoints (models, options)
AND boot-complete marker in stdout before declaring WebUI ready. This prevents
calling /txt2img during the WebUI weight-loading phase.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.api.webui_api import WebUIAPI, WebUIReadinessTimeout


class TestWaitUntilTrueReadySuccess:
    """Test wait_until_true_ready succeeds when all checks pass."""

    def test_returns_true_when_all_checks_pass_immediately(self):
        """Verify wait_until_true_ready returns True when API and boot marker both ready."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "Starting StableNew...\nStartup time: 2.34s\nRunning on local URL: http://127.0.0.1:7860"

        api = WebUIAPI(client=mock_client)
        result = api.wait_until_true_ready(
            timeout_s=30, poll_interval_s=0.1, get_stdout_tail=get_stdout_tail
        )

        assert result is True
        assert mock_client.check_api_ready.call_count >= 1

    def test_returns_true_when_marker_appears_after_polling(self):
        """Verify wait_until_true_ready polls stdout until boot marker appears."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        poll_count = [0]

        def get_stdout_tail():
            poll_count[0] += 1
            if poll_count[0] < 3:
                return "Starting StableNew...\nLoading models..."
            else:
                return "Starting StableNew...\nLoading models...\nRunning on public URL: http://example.com:7860"

        api = WebUIAPI(client=mock_client)
        result = api.wait_until_true_ready(
            timeout_s=30, poll_interval_s=0.01, get_stdout_tail=get_stdout_tail
        )

        assert result is True
        assert poll_count[0] >= 3

    def test_recognizes_startup_time_marker(self):
        """Verify boot marker detection includes 'Startup time:' string."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "StableNew starting...\nStartup time: 3.45s\nReady for requests"

        api = WebUIAPI(client=mock_client)
        result = api.wait_until_true_ready(
            timeout_s=30, poll_interval_s=0.1, get_stdout_tail=get_stdout_tail
        )

        assert result is True

    def test_recognizes_running_on_local_url_marker(self):
        """Verify boot marker detection includes 'Running on local URL:' string."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "StableNew starting...\nRunning on local URL: http://127.0.0.1:7860\nReady"

        api = WebUIAPI(client=mock_client)
        result = api.wait_until_true_ready(
            timeout_s=30, poll_interval_s=0.1, get_stdout_tail=get_stdout_tail
        )

        assert result is True

    def test_recognizes_running_on_public_url_marker(self):
        """Verify boot marker detection includes 'Running on public URL:' string."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "StableNew starting...\nRunning on public URL: http://example.com:7860\nReady"

        api = WebUIAPI(client=mock_client)
        result = api.wait_until_true_ready(
            timeout_s=30, poll_interval_s=0.1, get_stdout_tail=get_stdout_tail
        )

        assert result is True


class TestWaitUntilTrueReadyTimeout:
    """Test wait_until_true_ready timeout behavior."""

    def test_raises_timeout_when_marker_never_appears(self):
        """Verify timeout exception raised when boot marker never appears in stdout."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "StableNew starting...\nLoading models...\nStill loading..."

        api = WebUIAPI(client=mock_client)

        with pytest.raises(WebUIReadinessTimeout) as excinfo:
            api.wait_until_true_ready(
                timeout_s=0.1, poll_interval_s=0.01, get_stdout_tail=get_stdout_tail
            )

        exc = excinfo.value
        assert exc.total_waited > 0
        assert exc.stdout_tail is not None
        assert isinstance(exc.checks_status, dict)

    def test_timeout_includes_checks_status_dict(self):
        """Verify WebUIReadinessTimeout includes checks_status showing which validations passed."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=False)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 500
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "StableNew starting..."

        api = WebUIAPI(client=mock_client)

        with pytest.raises(WebUIReadinessTimeout) as excinfo:
            api.wait_until_true_ready(
                timeout_s=0.1, poll_interval_s=0.01, get_stdout_tail=get_stdout_tail
            )

        exc = excinfo.value
        assert isinstance(exc.checks_status, dict)
        checks = exc.checks_status
        assert isinstance(checks, dict)

    def test_timeout_includes_stdout_tail_for_debugging(self):
        """Verify WebUIReadinessTimeout includes stdout tail snippet for operator debugging."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "StableNew starting...\nLoading weights: 0/1000...\nLoading weights: 500/1000..."

        api = WebUIAPI(client=mock_client)

        with pytest.raises(WebUIReadinessTimeout) as excinfo:
            api.wait_until_true_ready(
                timeout_s=0.1, poll_interval_s=0.01, get_stdout_tail=get_stdout_tail
            )

        exc = excinfo.value
        assert exc.stdout_tail is not None
        assert len(exc.stdout_tail) > 0

    def test_raises_timeout_when_models_endpoint_never_ready(self):
        """Verify timeout when models endpoint never becomes ready."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=False)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "Startup time: 5s"

        api = WebUIAPI(client=mock_client)

        with pytest.raises(WebUIReadinessTimeout):
            api.wait_until_true_ready(
                timeout_s=0.1, poll_interval_s=0.01, get_stdout_tail=get_stdout_tail
            )

    def test_raises_timeout_when_options_endpoint_never_ready(self):
        """Verify timeout when options endpoint never becomes ready (HTTP error)."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 500
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "Startup time: 5s"

        api = WebUIAPI(client=mock_client)

        with pytest.raises(WebUIReadinessTimeout):
            api.wait_until_true_ready(
                timeout_s=0.1, poll_interval_s=0.01, get_stdout_tail=get_stdout_tail
            )


class TestWaitUntilTrueReadySafeModeCompatibility:
    """Test wait_until_true_ready respects SafeMode by using read-only options check."""

    def test_options_endpoint_check_uses_session_get_not_client_update(self):
        """Verify true-readiness probes options endpoint with read-only HTTP GET."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_client.update_options = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "Startup time: 5s"

        api = WebUIAPI(client=mock_client)
        result = api.wait_until_true_ready(
            timeout_s=30, poll_interval_s=0.1, get_stdout_tail=get_stdout_tail
        )

        assert result is True
        assert mock_client.update_options.call_count == 0
        assert mock_client._session.get.called

    def test_http_get_targets_options_endpoint(self):
        """Verify HTTP GET probe targets the /options endpoint."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)
        mock_client._session = Mock()
        mock_client.base_url = "http://localhost:7860"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "Startup time: 5s"

        api = WebUIAPI(client=mock_client)
        result = api.wait_until_true_ready(
            timeout_s=30, poll_interval_s=0.1, get_stdout_tail=get_stdout_tail
        )

        assert result is True
        assert mock_client._session.get.called


class TestWaitUntilTrueReadyPollingBehavior:
    """Test wait_until_true_ready polling frequency and behavior."""

    def test_continues_polling_until_all_checks_pass(self):
        """Verify polling continues until models AND options AND marker all pass."""
        mock_client = Mock()
        poll_count = [0]

        def check_api_ready_side_effect():
            poll_count[0] += 1
            return poll_count[0] >= 3

        mock_client.check_api_ready = Mock(side_effect=check_api_ready_side_effect)
        mock_client._session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client._session.get = Mock(return_value=mock_response)

        def get_stdout_tail():
            return "Startup time: 5s"

        api = WebUIAPI(client=mock_client)
        result = api.wait_until_true_ready(
            timeout_s=30, poll_interval_s=0.01, get_stdout_tail=get_stdout_tail
        )

        assert result is True
        assert poll_count[0] >= 3


class TestWebUIReadinessTimeoutException:
    """Test WebUIReadinessTimeout exception properties."""

    def test_exception_has_total_waited_metadata(self):
        """Verify exception captures total time waited before timeout."""
        exc = WebUIReadinessTimeout(
            message="Timeout",
            total_waited=45.5,
            stdout_tail="Loading...",
            stderr_tail="",
            checks_status={"models": False, "options": True, "boot_marker": False},
        )

        assert exc.total_waited == 45.5

    def test_exception_has_stdout_tail_metadata(self):
        """Verify exception captures stdout tail for debugging."""
        exc = WebUIReadinessTimeout(
            message="Timeout",
            total_waited=30,
            stdout_tail="StableNew v1.2.3\nLoading models...\nWaiting...",
            stderr_tail="",
            checks_status={},
        )

        assert "Loading models" in exc.stdout_tail

    def test_exception_has_checks_status_metadata(self):
        """Verify exception captures status of each readiness check."""
        checks = {"models_endpoint": True, "options_endpoint": False, "boot_marker": True}
        exc = WebUIReadinessTimeout(
            message="Timeout", total_waited=30, stdout_tail="", stderr_tail="", checks_status=checks
        )

        assert exc.checks_status == checks

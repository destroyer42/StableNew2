"""Tests for WebUIAPI.wait_until_true_ready() true-readiness gate.

Current readiness contract: the models endpoint, the options endpoint, and the
progress endpoint (reporting idle, ``progress == 0.0``) must all pass. The stdout
boot marker is observability only and never gates readiness.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.api.webui_api import WebUIAPI, WebUIReadinessTimeout

BOOT_TAIL = "Starting StableNew...\nStartup time: 2.34s\nRunning on local URL: http://127.0.0.1:7860"


def _response(status_code: int = 200, payload: dict | None = None) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json = Mock(return_value=payload if payload is not None else {})
    return response


def _make_client(
    *,
    api_ready=True,
    options_status: int = 200,
    progress: float | list[float] = 0.0,
    progress_status: int = 200,
) -> Mock:
    """Build a client whose session routes GETs by endpoint.

    ``progress`` may be a list to script successive /progress readings (the last
    reading repeats).
    """
    client = Mock()
    client.base_url = "http://localhost:7860"
    client.check_api_ready = (
        Mock(side_effect=api_ready) if callable(api_ready) else Mock(return_value=api_ready)
    )
    client.update_options = Mock()
    readings = list(progress) if isinstance(progress, list) else [progress]
    seen: list[str] = []

    def get(url: str, timeout: float | None = None) -> Mock:
        seen.append(url)
        if url.endswith("/sdapi/v1/options"):
            return _response(options_status)
        if url.endswith("/sdapi/v1/progress"):
            value = readings.pop(0) if len(readings) > 1 else readings[0]
            return _response(progress_status, {"progress": value})
        raise AssertionError(f"unexpected GET {url}")

    client._session = Mock()
    client._session.get = Mock(side_effect=get)
    client.requested_urls = seen
    return client


def _wait(client: Mock, *, timeout_s: float = 30, poll: float = 0.01, tail=None):
    return WebUIAPI(client=client).wait_until_true_ready(
        timeout_s=timeout_s, poll_interval_s=poll, get_stdout_tail=tail
    )


class TestWaitUntilTrueReadySuccess:
    def test_returns_true_when_all_checks_pass_immediately(self) -> None:
        client = _make_client()
        assert _wait(client, tail=lambda: BOOT_TAIL) is True
        assert client.check_api_ready.call_count >= 1

    @pytest.mark.parametrize(
        "tail",
        [
            "Startup time: 3.45s",
            "Running on local URL: http://127.0.0.1:7860",
            "Running on public URL: http://example.com:7860",
            "Loading models...",  # no marker at all: observability only
        ],
    )
    def test_boot_marker_is_observability_only(self, tail: str) -> None:
        assert _wait(_make_client(), tail=lambda: tail) is True

    def test_polls_stdout_tail_each_cycle(self) -> None:
        calls = [0]

        def tail() -> str:
            calls[0] += 1
            return "Loading models..." if calls[0] < 3 else BOOT_TAIL

        client = _make_client(progress=[1.0, 1.0, 0.0])
        assert _wait(client, tail=tail) is True
        assert calls[0] >= 3


class TestWaitUntilTrueReadyTimeout:
    def test_busy_progress_blocks_readiness_even_with_boot_marker(self) -> None:
        client = _make_client(progress=0.37)

        with pytest.raises(WebUIReadinessTimeout) as excinfo:
            _wait(client, timeout_s=0.3, tail=lambda: BOOT_TAIL)

        checks = excinfo.value.checks_status
        assert checks["models_endpoint"] is True
        assert checks["options_endpoint"] is True
        assert checks["boot_marker_found"] is True
        assert checks["progress_idle"] is False

    def test_progress_http_error_blocks_readiness(self) -> None:
        client = _make_client(progress_status=503)
        with pytest.raises(WebUIReadinessTimeout) as excinfo:
            _wait(client, timeout_s=0.3)
        assert excinfo.value.checks_status["progress_idle"] is False

    def test_timeout_includes_checks_stdout_and_wait_metadata(self) -> None:
        client = _make_client(api_ready=False, options_status=500)
        with pytest.raises(WebUIReadinessTimeout) as excinfo:
            _wait(client, timeout_s=0.3, tail=lambda: "Loading weights: 500/1000...")

        exc = excinfo.value
        assert exc.total_waited > 0
        assert "Loading weights" in exc.stdout_tail
        assert exc.checks_status["models_endpoint"] is False
        assert exc.checks_status["options_endpoint"] is False

    def test_raises_timeout_when_models_endpoint_never_ready(self) -> None:
        with pytest.raises(WebUIReadinessTimeout):
            _wait(_make_client(api_ready=False), timeout_s=0.3, tail=lambda: "Startup time: 5s")

    def test_raises_timeout_when_options_endpoint_never_ready(self) -> None:
        with pytest.raises(WebUIReadinessTimeout):
            _wait(_make_client(options_status=500), timeout_s=0.3, tail=lambda: "Startup time: 5s")


class TestWaitUntilTrueReadyReadOnlyProbes:
    def test_probes_use_read_only_session_get_not_option_writes(self) -> None:
        client = _make_client()
        assert _wait(client, tail=lambda: "Startup time: 5s") is True
        assert client.update_options.call_count == 0
        assert any(url.endswith("/sdapi/v1/options") for url in client.requested_urls)
        assert any(url.endswith("/sdapi/v1/progress") for url in client.requested_urls)


class TestWaitUntilTrueReadyPollingBehavior:
    def test_continues_polling_until_models_endpoint_passes(self) -> None:
        poll_count = [0]

        def api_ready() -> bool:
            poll_count[0] += 1
            return poll_count[0] >= 3

        client = _make_client(api_ready=api_ready)
        assert _wait(client, tail=lambda: "Startup time: 5s") is True
        assert poll_count[0] >= 3

    def test_continues_polling_while_busy_then_returns_when_idle(self) -> None:
        client = _make_client(progress=[0.9, 0.4, 0.0])
        assert _wait(client, tail=lambda: BOOT_TAIL) is True
        progress_polls = [u for u in client.requested_urls if u.endswith("/sdapi/v1/progress")]
        assert len(progress_polls) >= 3


class TestWebUIReadinessTimeoutException:
    def test_exception_exposes_metadata(self) -> None:
        checks = {"models_endpoint": True, "options_endpoint": False, "boot_marker": True}
        exc = WebUIReadinessTimeout(
            message="Timeout",
            total_waited=45.5,
            stdout_tail="StableNew v1.2.3\nLoading models...\nWaiting...",
            stderr_tail="",
            checks_status=checks,
        )

        assert exc.total_waited == 45.5
        assert "Loading models" in exc.stdout_tail
        assert exc.checks_status == checks

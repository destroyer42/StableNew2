"""Pytest fixtures for journey tests (CI mode support)."""

import os
import pytest


def is_ci_mode() -> bool:
    """Check if running in CI environment."""
    return os.getenv("CI", "").lower() in ("true", "1", "yes")


@pytest.fixture(scope="function")
def webui_client():
    """
    Provide WebUIClient for journey tests.

    - In CI: Returns MockWebUIClient (no real WebUI needed)
    - In self-hosted: Returns real WebUIClient

    Journey tests use this fixture and work in both modes.
    """
    if is_ci_mode():
        # CI mode: use mock
        from tests.mocks.webui_mock_server import get_mock_server
        from tests.mocks.webui_mock_client import MockWebUIClient

        mock_server = get_mock_server()
        mock_server.reset()  # Clean state for each test
        return MockWebUIClient()
    else:
        # Self-hosted mode: use real client
        from src.core.webui_client import WebUIClient

        return WebUIClient(base_url=os.getenv("WEBUI_URL", "http://localhost:7860"))


@pytest.fixture(scope="function")
def pipeline_runner(webui_client):
    """
    Provide PipelineRunner for journey tests.

    Uses webui_client fixture (mock or real).
    """
    from tests.journeys.fakes.fake_pipeline_runner import FakePipelineRunner

    runner = FakePipelineRunner(webui_client=webui_client)
    return runner


@pytest.fixture(autouse=True, scope="function")
def reset_mock_state():
    """Reset mock server state between tests (CI mode only)."""
    if is_ci_mode():
        from tests.mocks.webui_mock_server import get_mock_server

        mock_server = get_mock_server()
        mock_server.reset()

    yield

    # Cleanup after test
    if is_ci_mode():
        from tests.mocks.webui_mock_server import get_mock_server

        mock_server = get_mock_server()
        mock_server.reset()

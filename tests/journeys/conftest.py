"""Pytest fixtures for deterministic and explicitly real journey tests."""

import os

import pytest


def real_backend_enabled() -> bool:
    """Return whether this invocation explicitly opted into real backends."""

    return os.getenv("STABLENEW_REAL_BACKEND_TESTS", "").lower() in (
        "true",
        "1",
        "yes",
    )


def pytest_collection_modifyitems(items):
    """Mark journey items when the invocation enables real backend access."""

    if not real_backend_enabled():
        return
    for item in items:
        if item.nodeid.replace("\\", "/").startswith("tests/journeys/"):
            item.add_marker(pytest.mark.real_backend)


@pytest.fixture(scope="function")
def webui_client():
    """
    Provide WebUIClient for journey tests.

    - By default: returns MockWebUIClient (no real WebUI needed)
    - With STABLENEW_REAL_BACKEND_TESTS=1: returns real WebUIClient

    Journey tests use this fixture and work in both modes.
    """
    if not real_backend_enabled():
        from tests.mocks.webui_mock_client import MockWebUIClient
        from tests.mocks.webui_mock_server import get_mock_server

        mock_server = get_mock_server()
        mock_server.reset()  # Clean state for each test
        return MockWebUIClient()

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
    """Reset mock server state around deterministic journey tests."""
    if not real_backend_enabled():
        from tests.mocks.webui_mock_server import get_mock_server

        mock_server = get_mock_server()
        mock_server.reset()

    yield

    # Cleanup after test
    if not real_backend_enabled():
        from tests.mocks.webui_mock_server import get_mock_server

        mock_server = get_mock_server()
        mock_server.reset()

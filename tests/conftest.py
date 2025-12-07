import os
import time
import tkinter as tk

import pytest


@pytest.fixture
def tk_root():
    """Fixture to provide a Tk root window for GUI tests, skips if Tk is not available or no display."""
    try:
        root = tk.Tk()
        root.withdraw()
        yield root
        root.destroy()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")


@pytest.fixture
def tk_pump(tk_root):
    """Pump Tk events without blocking the main thread."""

    def pump(duration=0.2, step=0.01):
        end = time.monotonic() + duration
        while time.monotonic() < end:
            try:
                tk_root.update()
            except Exception:
                break
            time.sleep(step)

    return pump


"""Global test configuration and monkeypatches"""


@pytest.fixture(autouse=True)
def _mock_webui_discovery(monkeypatch):
    """Prevent tests from launching or probing real WebUI services.

    This avoids background threads calling Tkinter/after() which crash on Windows CI.
    """
    monkeypatch.setenv("STABLENEW_NO_WEBUI", "1")

    try:
        import src.utils.webui_discovery as wd  # type: ignore
    except Exception:
        return

    def fake_find_port(*_args, **_kwargs):
        return None

    def fake_launch_safely(*_args, **_kwargs):
        return None

    monkeypatch.setattr(wd, "find_webui_api_port", fake_find_port, raising=False)
    monkeypatch.setattr(wd, "launch_webui_safely", fake_launch_safely, raising=False)

    try:
        import src.api.client as api_client  # type: ignore

        current_test = os.environ.get("PYTEST_CURRENT_TEST", "")
        if "tests/test_api.py" not in current_test and "tests/test_api_client.py" not in current_test:
            monkeypatch.setattr(
                api_client.SDWebUIClient,
                "check_api_ready",
                lambda self, *args, **kwargs: False,
                raising=False,
            )
    except Exception:
        pass

    try:
        import src.gui.main_window as main_window  # type: ignore

        monkeypatch.setattr(
            main_window.StableNewGUI, "_check_api_connection", lambda self: None, raising=False
        )
        monkeypatch.setattr(
            main_window.StableNewGUI, "_launch_webui", lambda self: None, raising=False
        )
    except Exception:
        pass


# Preserve existing tmp_path fixture override
@pytest.fixture
def tmp_path(tmp_path_factory):
    """Provide a temporary directory for tests"""
    return tmp_path_factory.mktemp("test_data")


# ---------------------------------------------------------------------------
# PR-0114C-Ty: DI fixtures for JobService/Runner/History
# ---------------------------------------------------------------------------

@pytest.fixture
def stubbed_job_service():
    """Create a JobService with StubRunner and NullHistoryService.

    PR-0114C-Ty: Use this fixture in tests that should not execute real
    pipelines or hit SD/WebUI resources.
    """
    from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service
    return make_stubbed_job_service()


@pytest.fixture
def stubbed_job_service_with_queue():
    """Create a JobService with stubs and return all components.

    PR-0114C-Ty: Returns (service, queue, history) for tests that need
    to inspect queue or history state.
    """
    from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service_with_queue
    return make_stubbed_job_service_with_queue()


@pytest.fixture
def build_v2_app_with_stubs(stubbed_job_service):
    """Factory fixture to build V2 app with stubbed JobService.

    PR-0114C-Ty: Use this in GUI tests to avoid real pipeline execution.

    Usage:
        def test_something(build_v2_app_with_stubs):
            root, app_state, controller, window = build_v2_app_with_stubs()
            # Test GUI behavior without real execution
    """
    from src.app_factory import build_v2_app

    created_roots = []

    def _factory(**kwargs):
        # Default to stubbed job_service unless explicitly overridden
        if "job_service" not in kwargs:
            kwargs["job_service"] = stubbed_job_service
        result = build_v2_app(**kwargs)
        created_roots.append(result[0])  # Track root for cleanup
        return result

    yield _factory

    # Cleanup all created roots
    for root in created_roots:
        try:
            root.destroy()
        except Exception:
            pass

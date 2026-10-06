import gc
import os
import threading
import time
import tkinter as tk
from pathlib import Path

import pytest

# --- Garbage collection only on the main thread ---------------------------------------
# GUI tests leave Tk interpreters/variables behind. If the cyclic collector (automatic,
# or an explicit ``gc.collect()`` such as ``SDWebUIClient.free_vram``) finalizes one on a
# worker thread, Tcl aborts the whole process ("Tcl_AsyncDelete: async handler deleted by
# the wrong thread" -> ``Fatal Python error: Aborted``, seen in the CI full-suite job on
# both Python versions). Disable automatic collection for the test session, make
# ``gc.collect`` a no-op off the main thread, and collect on the main thread whenever the
# test module changes so garbage is still reclaimed.
_REAL_GC_COLLECT = gc.collect


def _main_thread_only_collect(*args, **kwargs):
    if threading.current_thread() is not threading.main_thread():
        return 0
    return _REAL_GC_COLLECT(*args, **kwargs)


_GC_WAS_ENABLED = gc.isenabled()
gc.disable()
gc.collect = _main_thread_only_collect


def pytest_runtest_teardown(item, nextitem):
    if nextitem is None or nextitem.path != item.path:
        _REAL_GC_COLLECT()


def pytest_unconfigure(config):
    gc.collect = _REAL_GC_COLLECT
    if _GC_WAS_ENABLED:
        gc.enable()


@pytest.fixture
def tk_root():
    """Fixture to provide a Tk root window for GUI tests, skips if Tk is not available or no display."""
    try:
        root = tk.Tk()
        root.withdraw()
        yield root
        try:
            root.update_idletasks()
            root.update()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
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
def _isolate_process_global_runtime_state():
    """Give each test a clean process-global thread registry and watchdog slot.

    ``ThreadRegistry`` and ``SystemWatchdogV2`` keep process-wide state. A test that
    builds an ``AppController`` without shutting it down leaves a registered thread
    or a live single-flight watchdog, which then makes unrelated lifecycle tests
    (shutdown counts, watchdog start/stall) fail only in a whole-suite run. This
    forgets bookkeeping for threads leaked by earlier tests; it does not stop them.

    ``AppController`` also chains ``sys.excepthook``/``threading.excepthook`` at
    construction. Controllers that are never shut down stack those hooks, and a later
    thread exception then recurses through every leaked controller (each building a
    diagnostics bundle) until the interpreter overflows its stack. Restore both hooks
    after every test.
    """

    import sys
    import threading

    original_sys_hook = sys.excepthook
    original_thread_hook = threading.excepthook
    try:
        from src.services.watchdog_system_v2 import SystemWatchdogV2
        from src.utils.thread_registry import get_thread_registry

        registry = get_thread_registry()
        with registry._registry_lock:
            registry._threads.clear()
            registry._shutdown_requested = False
        with SystemWatchdogV2._ACTIVE_LOCK:
            SystemWatchdogV2._ACTIVE_THREAD = None
    except Exception:  # pragma: no cover - isolation must never break collection
        pass
    try:
        yield
    finally:
        sys.excepthook = original_sys_hook
        threading.excepthook = original_thread_hook


@pytest.fixture(autouse=True)
def _pin_host_runtime_autostart_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic pytest never launches, adopts, or probes the owner's A1111/Comfy.

    Tracked ``presets/settings.json`` and WebUI detection carry machine-local values
    (install paths, ``comfy_autostart_enabled``), and ``get_webui_autostart_enabled``
    defaults to *enabled* whenever an install is detected and caches the answer
    process-wide. A test that builds the real application would then try to start the
    host's WebUI/Comfy. Pin both off through the same environment switches production
    honors, and reset the cached WebUI answer. Tests that exercise autostart or
    process-manager behavior override this with their own ``monkeypatch.setenv`` /
    ``set_webui_autostart_enabled`` or injected fakes (they run after this fixture).
    """

    monkeypatch.setenv("STABLENEW_WEBUI_AUTOSTART", "0")
    monkeypatch.setenv("STABLENEW_COMFY_AUTOSTART", "0")
    try:
        import src.config.app_config as app_config

        monkeypatch.setattr(app_config, "_webui_autostart_enabled", None)
    except Exception:  # pragma: no cover - isolation must never break collection
        pass


@pytest.fixture(autouse=True)
def _isolate_global_prompt_user_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pytest never reads or writes the operator's per-user Global Prompt store.

    Many production call sites build a default ``ConfigManager()`` (``SidebarPanelV2``, the executor's legacy
    fallback), which would resolve to ``%LOCALAPPDATA%\\StableNew\\GlobalPrompts`` and lazily create its files.
    Redirect it through the production-supported override to a per-test directory (not created here). A test that
    sets ``STABLENEW_GLOBAL_PROMPT_DIR`` itself, or injects ``global_prompt_dir``, still wins.
    """

    monkeypatch.setenv("STABLENEW_GLOBAL_PROMPT_DIR", str(tmp_path / "GlobalPrompts"))


@pytest.fixture(autouse=True)
def _mock_webui_discovery(monkeypatch, tmp_path: Path):
    """Prevent tests from launching or probing real WebUI services.

    This avoids background threads calling Tkinter/after() which crash on Windows CI.
    """
    monkeypatch.setenv("STABLENEW_NO_WEBUI", "1")
    monkeypatch.setenv("STABLENEW_TEST_MODE", "1")

    try:
        import src.api.webui_process_manager as webui_process_manager  # type: ignore

        monkeypatch.setattr(
            webui_process_manager,
            "_WEBUI_CACHE_FILE",
            tmp_path / "webui_cache.json",
        )
    except Exception:
        pass

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
        if (
            "tests/test_api.py" not in current_test
            and "tests/test_api_client.py" not in current_test
        ):
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

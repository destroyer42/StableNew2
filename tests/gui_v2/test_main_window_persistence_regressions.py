from __future__ import annotations

from pathlib import Path

from src.gui.main_window_v2 import (
    DEFAULT_MAIN_WINDOW_HEIGHT,
    DEFAULT_MAIN_WINDOW_WIDTH,
    MainWindowV2,
)
from src.services.ui_state_store import UIStateStore


class _StubRoot:
    def __init__(self, geometry: str = "1200x800+100+50") -> None:
        self._geometry = geometry
        self.deiconified = 0
        self._state = "normal"
        self.lifted = 0
        self.focused = 0
        self.bound_events: list[str] = []

    def geometry(self, value: str | None = None) -> str:
        if value is not None:
            self._geometry = value
        return self._geometry

    def state(self) -> str:
        return self._state

    def set_state(self, value: str) -> None:
        self._state = value

    def winfo_screenwidth(self) -> int:
        return 1920

    def winfo_screenheight(self) -> int:
        return 1080

    def minsize(self, _width: int, _height: int) -> None:
        return None

    def deiconify(self) -> None:
        self._state = "normal"
        self.deiconified += 1

    def lift(self) -> None:
        self.lifted += 1

    def focus_force(self) -> None:
        self.focused += 1

    def after_idle(self, callback) -> None:
        callback()

    def bind(self, sequence: str, callback, add=None) -> None:
        self.bound_events.append(sequence)


class _StubNotebook:
    def select(self) -> str:
        return "tab-1"

    def index(self, _item) -> int:
        return 1


class _StubLearningTab:
    def __init__(self, payload):
        self._payload = payload

    def get_learning_session_state(self):
        return self._payload


class _StubPhotoOptimizeTab:
    def __init__(self, payload):
        self._payload = payload

    def get_photo_optimize_state(self):
        return self._payload


class _StubJobController:
    def __init__(self) -> None:
        self.called = 0

    def trigger_deferred_autostart(self) -> None:
        self.called += 1


class _StubPipelineController:
    def __init__(self, job_controller: _StubJobController) -> None:
        self._job_controller = job_controller


class _StubWebUIConnection:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    def is_webui_ready_strict(self) -> bool:
        return self._ready


class _StubSVDTab:
    def __init__(self, payload):
        self._payload = payload

    def get_svd_state(self):
        return self._payload


class _StubVideoWorkflowTab:
    def __init__(self, payload):
        self._payload = payload

    def get_video_workflow_state(self):
        return self._payload


class _StubControllerForCleanup:
    def __init__(self) -> None:
        self.called = 0

    def stop_all_background_work(self) -> None:
        self.called += 1


class _StubWebUIManager:
    def __init__(self) -> None:
        self.called = 0

    def shutdown(self) -> None:
        self.called += 1


class _StubAppState:
    def __init__(self, *, content_visibility_mode: str = "nsfw") -> None:
        self.content_visibility_mode = content_visibility_mode

    def set_learning_enabled(self, _value: bool) -> None:
        return None


def test_save_ui_state_preserves_existing_learning_payload_when_tab_returns_none(tmp_path: Path) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")
    store.save_state(
        {
            "learning": {
                "enabled": True,
                "automation_mode": "suggest_only",
                "session": {"current_experiment": {"name": "Resume Test"}},
            }
        }
    )

    window = MainWindowV2.__new__(MainWindowV2)
    window.root = _StubRoot()
    window.center_notebook = _StubNotebook()
    window.learning_tab = _StubLearningTab(None)
    window.app_state = _StubAppState()

    from unittest.mock import patch

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        window._save_ui_state()

    saved = store.load_state()
    assert saved is not None
    assert saved["learning"]["session"]["current_experiment"]["name"] == "Resume Test"
    assert saved["tabs"]["selected_index"] == 1


def test_save_ui_state_persists_photo_optimize_selection(tmp_path: Path) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")

    window = MainWindowV2.__new__(MainWindowV2)
    window.root = _StubRoot()
    window.center_notebook = _StubNotebook()
    window.learning_tab = _StubLearningTab({})
    window.photo_optimize_tab = _StubPhotoOptimizeTab({"selected_asset_id": "photo_123"})
    window.app_state = _StubAppState()

    from unittest.mock import patch

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        window._save_ui_state()

    saved = store.load_state()
    assert saved is not None
    assert saved["photo_optimize"]["selected_asset_id"] == "photo_123"


def test_save_ui_state_persists_svd_selection(tmp_path: Path) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")

    window = MainWindowV2.__new__(MainWindowV2)
    window.root = _StubRoot()
    window.center_notebook = _StubNotebook()
    window.learning_tab = _StubLearningTab({})
    window.svd_tab = _StubSVDTab({"source_image_path": "C:/tmp/source.png", "num_frames": 25})
    window.app_state = _StubAppState()

    from unittest.mock import patch

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        window._save_ui_state()

    saved = store.load_state()
    assert saved is not None
    assert saved["svd"]["source_image_path"] == "C:/tmp/source.png"


def test_save_ui_state_persists_video_workflow_selection(tmp_path: Path) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")

    window = MainWindowV2.__new__(MainWindowV2)
    window.root = _StubRoot()
    window.center_notebook = _StubNotebook()
    window.learning_tab = _StubLearningTab({})
    window.video_workflow_tab = _StubVideoWorkflowTab(
        {
            "workflow_id": "ltx_multiframe_anchor_v1",
            "source_image_path": "C:/tmp/source.png",
            "end_anchor_path": "C:/tmp/end.png",
        }
    )
    window.app_state = _StubAppState()

    from unittest.mock import patch

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        window._save_ui_state()

    saved = store.load_state()
    assert saved is not None
    assert saved["video_workflow"]["workflow_id"] == "ltx_multiframe_anchor_v1"


def test_save_ui_state_persists_content_visibility_mode(tmp_path: Path) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")

    window = MainWindowV2.__new__(MainWindowV2)
    window.root = _StubRoot()
    window.center_notebook = _StubNotebook()
    window.learning_tab = _StubLearningTab({})
    window.app_state = _StubAppState(content_visibility_mode="sfw")

    from unittest.mock import patch

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        window._save_ui_state()

    saved = store.load_state()
    assert saved is not None
    assert saved["content_visibility"] == {"mode": "sfw"}


def test_trigger_deferred_queue_autostart_calls_job_controller() -> None:
    job_controller = _StubJobController()
    window = MainWindowV2.__new__(MainWindowV2)
    window.pipeline_controller = _StubPipelineController(job_controller)
    window.app_controller = type("ControllerStub", (), {"webui_connection_controller": _StubWebUIConnection(True)})()

    window._trigger_deferred_queue_autostart()

    assert job_controller.called == 1


def test_trigger_deferred_queue_autostart_defers_until_webui_ready() -> None:
    job_controller = _StubJobController()
    window = MainWindowV2.__new__(MainWindowV2)
    window.pipeline_controller = _StubPipelineController(job_controller)
    window.app_controller = type("ControllerStub", (), {"webui_connection_controller": _StubWebUIConnection(False)})()

    window._trigger_deferred_queue_autostart()

    assert job_controller.called == 0


def test_cleanup_does_not_double_shutdown_webui_when_controller_present() -> None:
    window = MainWindowV2.__new__(MainWindowV2)
    window._disposed = False
    window._invoker = None
    window.pipeline_controller = None
    window.app_state = type("State", (), {"disable_notifications": lambda self: None})()
    window.app_controller = _StubControllerForCleanup()
    window.webui_process_manager = _StubWebUIManager()
    window._save_ui_state = lambda: None

    window.cleanup()

    assert window.app_controller.called == 1
    assert window.webui_process_manager.called == 0


def test_ensure_window_geometry_ignores_offscreen_saved_geometry(tmp_path: Path) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")
    store.save_state(
        {
            "window": {
                "geometry": "1984x1110+-32000+-32000",
                "state": "normal",
            }
        }
    )

    window = MainWindowV2.__new__(MainWindowV2)
    window.root = _StubRoot("1x1+0+0")
    window.app_state = _StubAppState()

    from unittest.mock import patch

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        window._ensure_window_geometry()

    assert window.root.geometry() == f"{DEFAULT_MAIN_WINDOW_WIDTH}x{DEFAULT_MAIN_WINDOW_HEIGHT}"
    assert window.root.deiconified == 1


def test_save_ui_state_replaces_offscreen_geometry(tmp_path: Path) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")

    window = MainWindowV2.__new__(MainWindowV2)
    window.root = _StubRoot("1984x1110+-32000+-32000")
    window.center_notebook = _StubNotebook()
    window.learning_tab = _StubLearningTab({})
    window.app_state = _StubAppState()

    from unittest.mock import patch

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        window._save_ui_state()

    saved = store.load_state()
    assert saved is not None
    assert saved["window"]["geometry"] == f"{DEFAULT_MAIN_WINDOW_WIDTH}x{DEFAULT_MAIN_WINDOW_HEIGHT}"


def test_capture_visible_window_geometry_ignores_iconic_offscreen_geometry() -> None:
    window = MainWindowV2.__new__(MainWindowV2)
    visible_geometry = f"{DEFAULT_MAIN_WINDOW_WIDTH}x{DEFAULT_MAIN_WINDOW_HEIGHT}+200+120"
    window.root = _StubRoot(visible_geometry)
    window._last_visible_window_geometry = None

    window._capture_visible_window_geometry()
    assert window._last_visible_window_geometry == visible_geometry

    window.root.geometry("1984x1110+-32000+-32000")
    window.root.set_state("iconic")
    window._capture_visible_window_geometry()

    assert window._last_visible_window_geometry == visible_geometry


def test_ensure_window_visible_after_restore_uses_last_visible_geometry() -> None:
    window = MainWindowV2.__new__(MainWindowV2)
    window.root = _StubRoot("1984x1110+-32000+-32000")
    visible_geometry = f"{DEFAULT_MAIN_WINDOW_WIDTH}x{DEFAULT_MAIN_WINDOW_HEIGHT}+200+120"
    window._last_visible_window_geometry = visible_geometry

    window._ensure_window_visible_after_restore()

    assert window.root.geometry() == visible_geometry
    assert window.root.deiconified == 1
    assert window.root.lifted == 1
    assert window.root.focused == 1


def test_on_window_map_restores_visible_geometry_after_minimize() -> None:
    window = MainWindowV2.__new__(MainWindowV2)
    window.root = _StubRoot("1984x1110+-32000+-32000")
    visible_geometry = f"{DEFAULT_MAIN_WINDOW_WIDTH}x{DEFAULT_MAIN_WINDOW_HEIGHT}+140+90"
    window._last_visible_window_geometry = visible_geometry

    window._on_window_map()

    assert window.root.geometry() == visible_geometry

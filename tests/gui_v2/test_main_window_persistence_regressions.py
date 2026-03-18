from __future__ import annotations

from pathlib import Path

from src.gui.main_window_v2 import MainWindowV2
from src.services.ui_state_store import UIStateStore


class _StubRoot:
    def geometry(self) -> str:
        return "1200x800+100+50"

    def state(self) -> str:
        return "normal"


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

    from unittest.mock import patch

    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        window._save_ui_state()

    saved = store.load_state()
    assert saved is not None
    assert saved["svd"]["source_image_path"] == "C:/tmp/source.png"


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

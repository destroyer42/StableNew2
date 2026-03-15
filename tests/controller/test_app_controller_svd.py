from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from src.controller.app_controller import AppController
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope
from src.queue.job_history_store import JobHistoryEntry, JobStatus


def test_get_supported_svd_models_returns_model_ids() -> None:
    controller = AppController.__new__(AppController)

    model_ids = controller.get_supported_svd_models()

    assert model_ids[0] == "stabilityai/stable-video-diffusion-img2vid-xt"
    assert "stabilityai/stable-video-diffusion-img2vid" in model_ids
    assert "stabilityai/stable-video-diffusion-img2vid-xt-1-1" in model_ids


def test_on_webui_ready_triggers_deferred_autostart() -> None:
    class _JobController:
        def __init__(self) -> None:
            self.called = 0

        def trigger_deferred_autostart(self) -> None:
            self.called += 1

    controller = AppController.__new__(AppController)
    controller.pipeline_controller = type("PipelineControllerStub", (), {"_job_controller": _JobController()})()
    controller._append_log = lambda *_args, **_kwargs: None
    controller.current_operation_label = None
    controller.last_ui_action = None
    controller.refresh_resources_from_webui = lambda: None
    controller._spawn_tracked_thread = lambda *, target, name, purpose: target()

    controller.on_webui_ready()

    assert controller.pipeline_controller._job_controller.called == 1


def test_send_history_job_image_to_svd_selects_svd_tab(tmp_path) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")

    svd_tab = Mock()
    notebook = Mock()
    controller = AppController.__new__(AppController)
    controller.app_state = SimpleNamespace(
        history_items=[
            JobHistoryEntry(
                job_id="job-123",
                created_at=datetime.utcnow(),
                status=JobStatus.COMPLETED,
                result={"output_paths": [str(source_path)]},
            )
        ]
    )
    controller.main_window = SimpleNamespace(svd_tab=svd_tab, center_notebook=notebook)
    controller._append_log = lambda *_args, **_kwargs: None

    routed = controller.send_history_job_image_to_svd("job-123")

    assert routed == str(source_path)
    notebook.select.assert_called_once_with(svd_tab)
    svd_tab.set_source_image_path.assert_called_once()


def test_get_recent_svd_history_extracts_variant_details(tmp_path) -> None:
    source_path = tmp_path / "source.png"
    video_path = tmp_path / "clip.mp4"
    preview_path = tmp_path / "preview.png"
    manifest_path = tmp_path / "manifest.json"
    for path, content in (
        (source_path, b"png"),
        (video_path, b"mp4"),
        (preview_path, b"png"),
        (manifest_path, b"{}"),
    ):
        path.write_bytes(content)

    entry = JobHistoryEntry(
        job_id="job-svd-1",
        created_at=datetime.utcnow(),
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        result={
            "variants": [
                {
                    "source_image_path": str(source_path),
                    "video_path": str(video_path),
                    "thumbnail_path": str(preview_path),
                    "manifest_path": str(manifest_path),
                    "frame_count": 25,
                    "fps": 7,
                    "model_id": "stabilityai/stable-video-diffusion-img2vid-xt",
                }
            ],
            "metadata": {
                "svd_native_artifact": {
                    "output_paths": [str(video_path)],
                    "video_paths": [str(video_path)],
                    "manifest_paths": [str(manifest_path)],
                    "thumbnail_path": str(preview_path),
                    "count": 1,
                }
            },
        },
    )

    controller = AppController.__new__(AppController)
    controller.app_state = SimpleNamespace(history_items=[entry])

    records = controller.get_recent_svd_history()

    assert len(records) == 1
    assert records[0]["source_image_path"] == str(source_path)
    assert records[0]["video_path"] == str(video_path)
    assert records[0]["model_id"] == "stabilityai/stable-video-diffusion-img2vid-xt"


def test_show_structured_error_modal_uses_tk_root_parent(monkeypatch) -> None:
    created = {}

    class _FakeModal:
        def __init__(self, parent, *, envelope, on_close):
            created["parent"] = parent
            created["envelope"] = envelope
            created["on_close"] = on_close

        def winfo_exists(self):
            return True

    controller = AppController.__new__(AppController)
    controller.main_window = SimpleNamespace(root="tk-root")
    controller._error_modal = None

    monkeypatch.setattr("src.controller.app_controller.ErrorModalV2", _FakeModal)

    controller._show_structured_error_modal(
        UnifiedErrorEnvelope(
            cause="",
            message="boom",
            stack="",
            job_id=None,
            stage=None,
            subsystem="test",
            severity="error",
            error_type="test_error",
        )
    )

    assert created["parent"] == "tk-root"

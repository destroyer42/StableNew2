from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.controller.app_controller import AppController
from src.controller.app_controller_services.application_runtime_coordinator import (
    ApplicationRuntimeCoordinator,
)
from src.queue.job_history_store import JobHistoryEntry, JobStatus
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope
from src.video.svd_config import SVDConfig


def test_get_supported_svd_models_returns_model_ids() -> None:
    controller = AppController.__new__(AppController)

    model_ids = controller.get_supported_svd_models()

    assert model_ids[0] == "stabilityai/stable-video-diffusion-img2vid-xt"
    assert "stabilityai/stable-video-diffusion-img2vid" in model_ids
    assert "stabilityai/stable-video-diffusion-img2vid-xt-1-1" in model_ids


def test_get_supported_svd_models_respects_cache_and_local_only(monkeypatch) -> None:
    controller = AppController.__new__(AppController)

    monkeypatch.setattr(
        "src.video.svd_models.get_svd_model_options",
        lambda *, cache_dir=None, local_files_only=False: (
            ["stabilityai/stable-video-diffusion-img2vid-xt-1-1"]
            if local_files_only and cache_dir == "C:/cache/svd"
            else [
                "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
                "stabilityai/stable-video-diffusion-img2vid-xt",
            ]
        ),
    )

    model_ids = controller.get_supported_svd_models(cache_dir="C:/cache/svd", local_files_only=True)

    assert model_ids == ["stabilityai/stable-video-diffusion-img2vid-xt-1-1"]


def test_get_svd_postprocess_capabilities_returns_named_entries() -> None:
    controller = AppController.__new__(AppController)
    controller._svd_controller = Mock()
    controller._svd_controller.get_postprocess_capabilities.return_value = {
        "codeformer": {"name": "CodeFormer", "status": "ready", "available": True, "detail": "ok"}
    }
    controller._svd_controller.build_svd_config.return_value = "cfg"

    result = controller.get_svd_postprocess_capabilities({"postprocess": {}})

    assert "codeformer" in result
    controller._svd_controller.build_svd_config.assert_called_once()
    controller._svd_controller.get_postprocess_capabilities.assert_called_once_with("cfg")


def test_build_svd_defaults_uses_controller_default_config() -> None:
    controller = AppController.__new__(AppController)
    controller._svd_controller = Mock()
    controller._svd_controller.build_default_config.return_value = SVDConfig.from_dict(
        {
            "preprocess": {
                "resize_mode": "center_crop",
            },
            "inference": {
                "motion_bucket_id": 48,
                "noise_aug_strength": 0.01,
                "num_inference_steps": 25,
                "decode_chunk_size": 2,
            },
            "postprocess": {
                "face_restore": {"enabled": True},
                "interpolation": {"enabled": True, "executable_path": "C:/tools/rife.exe"},
                "upscale": {"enabled": True},
            },
        }
    )

    defaults = controller.build_svd_defaults()

    assert defaults["preprocess"]["resize_mode"] == "center_crop"
    assert defaults["inference"]["motion_bucket_id"] == 48
    assert defaults["postprocess"]["face_restore"]["enabled"] is True
    assert defaults["postprocess"]["interpolation"]["enabled"] is True
    assert defaults["postprocess"]["upscale"]["enabled"] is True


def test_get_svd_capabilities_forwards_selected_source_to_preflight() -> None:
    controller = AppController.__new__(AppController)
    controller._svd_controller = Mock()
    controller._svd_controller.build_svd_config.return_value = "cfg"
    controller._svd_controller.get_postprocess_capabilities.return_value = {}
    controller._svd_controller.get_preflight.return_value = {
        "available": False,
        "blocking_reasons": ["Invalid SVD source image"],
    }

    result = controller.get_svd_postprocess_capabilities(
        {"inference": {}},
        source_image_path="C:/tmp/source.png",
    )

    assert result["admission"]["available"] is False
    controller._svd_controller.get_preflight.assert_called_once_with(
        "cfg",
        source_image_path="C:/tmp/source.png",
    )


def test_submit_svd_job_rejects_invalid_motion_bucket_before_controller_dispatch() -> None:
    controller = AppController.__new__(AppController)
    controller._svd_controller = Mock()
    controller._append_log = lambda *_args, **_kwargs: None

    with pytest.raises(ValueError, match="inference.motion_bucket_id"):
        controller.submit_svd_job(
            source_image_path="C:/tmp/source.png",
            form_data={
                "inference": {"motion_bucket_id": 256},
                "pipeline": {"output_route": "SVD"},
            },
        )

    controller._svd_controller.build_svd_config.assert_not_called()


def test_submit_svd_folder_batch_delegates_once_then_syncs_once() -> None:
    controller = AppController.__new__(AppController)
    controller._svd_controller = Mock()
    controller._svd_controller.build_svd_config.return_value = "cfg"
    controller._svd_controller.submit_svd_folder_batch.return_value = ["job-1", "job-2"]
    controller.sync_queue_state_after_direct_submission = Mock()
    controller._append_log = Mock()

    job_ids = controller.submit_svd_folder_batch(
        folder_path="C:/tmp/sources",
        form_data={"inference": {"seed": 7}, "pipeline": {"output_route": "SVD"}},
        match_source_aspect=True,
    )

    assert job_ids == ["job-1", "job-2"]
    controller._svd_controller.submit_svd_folder_batch.assert_called_once_with(
        folder="C:/tmp/sources",
        config="cfg",
        match_source_aspect=True,
        output_route="SVD",
    )
    controller.sync_queue_state_after_direct_submission.assert_called_once()


def test_preview_svd_folder_batch_projects_counts_without_queue_submission() -> None:
    controller = AppController.__new__(AppController)
    controller._svd_controller = Mock()
    controller._svd_controller.discover_folder_sources.return_value = SimpleNamespace(
        folder="C:/tmp/sources",
        sources=(SimpleNamespace(path="C:/tmp/sources/a.png"),),
        ignored_paths=("C:/tmp/sources/readme.txt",),
        invalid_candidates=(("C:/tmp/sources/broken.png", "unreadable"),),
    )

    preview = controller.preview_svd_folder_batch(folder_path="C:/tmp/sources")

    assert preview["compatible_count"] == 1
    assert preview["ignored_count"] == 1
    assert preview["first_source_path"] == "C:/tmp/sources/a.png"


def test_runtime_status_callback_preserves_stage_detail() -> None:
    captured = {}
    controller = AppController.__new__(AppController)
    controller.app_state = SimpleNamespace(running_job=None)
    controller._queue_runtime_status_update = lambda status: captured.setdefault("status", status)

    callback = controller._get_runtime_status_callback()
    callback(
        {
            "job_id": "job-1",
            "current_stage": "svd_native",
            "stage_detail": "postprocess: interpolation",
            "progress": 0.75,
        }
    )

    assert captured["status"].current_stage == "svd_native"
    assert captured["status"].stage_detail == "postprocess: interpolation"


def test_on_webui_ready_triggers_deferred_autostart() -> None:
    """AppController.on_webui_ready hands off to the runtime coordinator that owns autostart."""

    class _JobController:
        def __init__(self) -> None:
            self.called = 0

        def trigger_deferred_autostart(self) -> None:
            self.called += 1

    class _WebUI:
        ready = False

        def is_webui_ready_strict(self) -> bool:
            return self.ready

    job_controller = _JobController()
    webui = _WebUI()
    controller = AppController.__new__(AppController)
    controller._api_client = None
    controller._append_log = lambda *_args, **_kwargs: None
    controller.refresh_resources_from_webui = lambda: None
    controller._runtime_projection_coordinator = SimpleNamespace(
        publish_webui_state=lambda _state: 0
    )
    controller._background_tasks = SimpleNamespace(submit=lambda *_args, **_kwargs: None)
    controller._application_runtime_coordinator = ApplicationRuntimeCoordinator(
        job_controller=job_controller, webui_connection_controller=webui
    )

    # GUI becomes ready first while WebUI is still starting: autostart is deferred.
    controller._application_runtime_coordinator.on_gui_ready()
    assert job_controller.called == 0

    webui.ready = True
    controller.on_webui_ready()

    assert job_controller.called == 1
    assert controller.current_operation_label == "Refreshing WebUI resources"


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


def test_send_history_job_image_to_video_workflow_selects_workflow_tab(tmp_path) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")

    workflow_tab = Mock()
    notebook = Mock()
    controller = AppController.__new__(AppController)
    controller.app_state = SimpleNamespace(
        history_items=[
            JobHistoryEntry(
                job_id="job-456",
                created_at=datetime.utcnow(),
                status=JobStatus.COMPLETED,
                result={"output_paths": [str(source_path)]},
            )
        ]
    )
    controller.main_window = SimpleNamespace(
        video_workflow_tab=workflow_tab, center_notebook=notebook
    )
    controller._append_log = lambda *_args, **_kwargs: None

    routed = controller.send_history_job_image_to_video_workflow("job-456")

    assert routed == str(source_path)
    notebook.select.assert_called_once_with(workflow_tab)
    workflow_tab.set_source_image_path.assert_called_once()


def test_submit_video_workflow_job_syncs_queue_state_after_direct_enqueue() -> None:
    controller = AppController.__new__(AppController)
    workflow_controller = Mock()
    workflow_controller.submit_video_workflow_job.return_value = "job-video-123"
    controller.get_video_workflow_controller = Mock(return_value=workflow_controller)
    controller._refresh_app_state_queue = Mock()
    flush_now = Mock()
    controller.app_state = SimpleNamespace(flush_now=flush_now)
    controller._append_log = lambda *_args, **_kwargs: None

    job_id = controller.submit_video_workflow_job(
        source_image_path="C:/tmp/source.png",
        form_data={"workflow_id": "ltx_multiframe_anchor_v1"},
    )

    assert job_id == "job-video-123"
    controller._refresh_app_state_queue.assert_called_once()
    flush_now.assert_called_once()


def test_submit_svd_job_syncs_queue_state_after_direct_enqueue() -> None:
    controller = AppController.__new__(AppController)
    svd_controller = Mock()
    svd_controller.build_svd_config.return_value = "cfg"
    svd_controller.validate_source_image.return_value = (True, None)
    svd_controller.submit_svd_job.return_value = "job-svd-123"
    controller._get_svd_controller = Mock(return_value=svd_controller)
    controller._refresh_app_state_queue = Mock()
    flush_now = Mock()
    controller.app_state = SimpleNamespace(flush_now=flush_now)
    controller._append_log = lambda *_args, **_kwargs: None

    job_id = controller.submit_svd_job(
        source_image_path="C:/tmp/source.png",
        form_data={"inference": {"motion_bucket_id": 64}, "pipeline": {"output_route": "SVD"}},
    )

    assert job_id == "job-svd-123"
    controller._refresh_app_state_queue.assert_called_once()
    flush_now.assert_called_once()


def test_send_history_video_bundle_to_video_workflow_uses_bundle_handoff(tmp_path) -> None:
    preview_path = tmp_path / "preview.png"
    source_path = tmp_path / "source.png"
    preview_path.write_bytes(b"png")
    source_path.write_bytes(b"png")

    workflow_tab = Mock()
    notebook = Mock()
    controller = AppController.__new__(AppController)
    controller.app_state = SimpleNamespace(
        history_items=[
            JobHistoryEntry(
                job_id="job-vid-456",
                created_at=datetime.utcnow(),
                status=JobStatus.COMPLETED,
                result={
                    "video_bundle": {
                        "primary_path": str(tmp_path / "clip.mp4"),
                        "thumbnail_path": str(preview_path),
                        "source_image_path": str(source_path),
                        "frame_paths": [str(preview_path)],
                    }
                },
            )
        ]
    )
    controller.main_window = SimpleNamespace(
        video_workflow_tab=workflow_tab, center_notebook=notebook
    )
    controller._append_log = lambda *_args, **_kwargs: None

    routed = controller.send_history_job_image_to_video_workflow("job-vid-456")

    assert routed == str(preview_path)
    notebook.select.assert_called_once_with(workflow_tab)
    workflow_tab.set_source_bundle.assert_called_once()
    workflow_tab.set_source_image_path.assert_not_called()


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
                    "postprocess": {
                        "applied": ["interpolation", "upscale"],
                        "input_frame_count": 25,
                        "output_frame_count": 49,
                        "output_width": 2048,
                        "output_height": 1152,
                    },
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
    assert records[0]["postprocess_applied"] == ["interpolation", "upscale"]
    assert records[0]["postprocess_output_frame_count"] == 49
    assert records[0]["postprocess_output_width"] == 2048


def test_get_recent_svd_history_falls_back_to_manifest_when_summary_missing(tmp_path) -> None:
    source_path = tmp_path / "source.png"
    gif_path = tmp_path / "clip.gif"
    preview_path = tmp_path / "preview.png"
    manifest_path = tmp_path / "manifest.json"
    for path, content in (
        (source_path, b"png"),
        (gif_path, b"gif"),
        (preview_path, b"png"),
    ):
        path.write_bytes(content)

    manifest_path.write_text(
        json.dumps(
            {
                "source_image_path": str(source_path),
                "gif_path": str(gif_path),
                "gif_paths": [str(gif_path)],
                "output_paths": [str(gif_path)],
                "manifest_paths": [str(manifest_path)],
                "thumbnail_path": str(preview_path),
                "frame_count": 14,
                "fps": 8,
                "model_id": "stabilityai/stable-video-diffusion-img2vid",
                "postprocess": {"applied": ["upscale"], "output_width": 1536},
                "artifact": {
                    "schema": "stablenew.artifact.v2.6",
                    "stage": "svd_native",
                    "artifact_type": "video",
                    "primary_path": str(gif_path),
                    "output_paths": [str(gif_path)],
                    "manifest_path": str(manifest_path),
                    "thumbnail_path": str(preview_path),
                    "input_image_path": str(source_path),
                },
            }
        ),
        encoding="utf-8",
    )

    entry = JobHistoryEntry(
        job_id="job-svd-manifest",
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        result={
            "variants": [
                {
                    "manifest_path": str(manifest_path),
                }
            ]
        },
    )

    controller = AppController.__new__(AppController)
    controller.app_state = SimpleNamespace(history_items=[entry])

    records = controller.get_recent_svd_history()

    assert len(records) == 1
    assert records[0]["gif_path"] == str(gif_path)
    assert records[0]["output_path"] == str(gif_path)
    assert records[0]["source_image_path"] == str(source_path)
    assert records[0]["postprocess_applied"] == ["upscale"]
    assert records[0]["postprocess_output_width"] == 1536


def test_get_recent_svd_history_uses_frames_only_outputs(tmp_path) -> None:
    source_path = tmp_path / "source.png"
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    frame_one = frame_dir / "frame_0001.png"
    frame_two = frame_dir / "frame_0002.png"
    preview_path = tmp_path / "preview.png"
    manifest_path = tmp_path / "manifest.json"
    for path, content in (
        (source_path, b"png"),
        (frame_one, b"png"),
        (frame_two, b"png"),
        (preview_path, b"png"),
        (manifest_path, b"{}"),
    ):
        path.write_bytes(content)

    entry = JobHistoryEntry(
        job_id="job-svd-frames",
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        result={
            "variants": [
                {
                    "source_image_path": str(source_path),
                    "frame_paths": [str(frame_one), str(frame_two)],
                    "thumbnail_path": str(preview_path),
                    "manifest_path": str(manifest_path),
                    "frame_count": 25,
                    "fps": 7,
                    "model_id": "stabilityai/stable-video-diffusion-img2vid-xt",
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "svd_native",
                        "artifact_type": "video",
                        "primary_path": str(frame_one),
                        "output_paths": [str(frame_one), str(frame_two)],
                        "manifest_path": str(manifest_path),
                        "thumbnail_path": str(preview_path),
                        "input_image_path": str(source_path),
                    },
                }
            ],
            "metadata": {
                "svd_native_artifact": {
                    "output_paths": [str(frame_one), str(frame_two)],
                    "manifest_paths": [str(manifest_path)],
                    "thumbnail_path": str(preview_path),
                    "count": 2,
                }
            },
        },
    )

    controller = AppController.__new__(AppController)
    controller.app_state = SimpleNamespace(history_items=[entry])

    records = controller.get_recent_svd_history()

    assert len(records) == 1
    assert records[0]["video_path"] is None
    assert records[0]["gif_path"] is None
    assert records[0]["output_path"] == str(frame_one)
    assert records[0]["count"] == 2


def test_get_recent_svd_history_prefers_generic_video_artifact_metadata(tmp_path) -> None:
    source_path = tmp_path / "source.png"
    video_path = tmp_path / "clip.mp4"
    manifest_path = tmp_path / "manifest.json"
    preview_path = tmp_path / "preview.png"
    for path, content in (
        (source_path, b"png"),
        (video_path, b"mp4"),
        (manifest_path, b"{}"),
        (preview_path, b"png"),
    ):
        path.write_bytes(content)

    entry = JobHistoryEntry(
        job_id="job-svd-generic",
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        result={
            "variants": [
                {
                    "source_image_path": str(source_path),
                    "video_path": str(video_path),
                    "manifest_path": str(manifest_path),
                    "thumbnail_path": str(preview_path),
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "svd_native",
                        "artifact_type": "video",
                        "primary_path": str(video_path),
                        "output_paths": [str(video_path)],
                        "manifest_path": str(manifest_path),
                        "thumbnail_path": str(preview_path),
                        "input_image_path": str(source_path),
                    },
                }
            ],
            "metadata": {
                "video_artifacts": {
                    "svd_native": {
                        "stage": "svd_native",
                        "backend_id": "svd_native",
                        "artifact_type": "video",
                        "primary_path": str(video_path),
                        "output_paths": [str(video_path)],
                        "video_paths": [str(video_path)],
                        "manifest_paths": [str(manifest_path)],
                        "thumbnail_path": str(preview_path),
                        "count": 1,
                        "artifacts": [
                            {
                                "schema": "stablenew.artifact.v2.6",
                                "stage": "svd_native",
                                "artifact_type": "video",
                                "primary_path": str(video_path),
                                "output_paths": [str(video_path)],
                                "manifest_path": str(manifest_path),
                                "thumbnail_path": str(preview_path),
                                "input_image_path": str(source_path),
                            }
                        ],
                    }
                },
                "video_primary_artifact": {
                    "stage": "svd_native",
                    "backend_id": "svd_native",
                    "artifact_type": "video",
                    "primary_path": str(video_path),
                    "output_paths": [str(video_path)],
                    "video_paths": [str(video_path)],
                    "manifest_paths": [str(manifest_path)],
                    "thumbnail_path": str(preview_path),
                    "count": 1,
                },
            },
        },
    )

    controller = AppController.__new__(AppController)
    controller.app_state = SimpleNamespace(history_items=[entry])

    records = controller.get_recent_svd_history()

    assert len(records) == 1
    assert records[0]["video_path"] == str(video_path)
    assert records[0]["thumbnail_path"] == str(preview_path)
    assert records[0]["manifest_path"] == str(manifest_path)
    assert records[0]["count"] == 1


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

    # AppController imports the modal lazily from its view module.
    monkeypatch.setattr("src.gui.views.error_modal_v2.ErrorModalV2", _FakeModal)

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

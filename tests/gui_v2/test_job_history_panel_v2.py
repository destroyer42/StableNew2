from __future__ import annotations

import pytest
from pathlib import Path

from src.gui.app_state_v2 import AppStateV2
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.queue.job_history_store import JobHistoryEntry, JobStatus


class DummyController:
    def __init__(self) -> None:
        self.refresh_calls = 0
        self.replay_calls = 0
        self.svd_calls: list[str] = []
        self.video_workflow_calls: list[str] = []

    def refresh_job_history(self) -> None:
        self.refresh_calls += 1

    def on_replay_history_job_v2(self, job_id: str) -> None:
        self.replay_calls += 1

    def send_history_job_image_to_svd(self, job_id: str) -> None:
        self.svd_calls.append(job_id)

    def send_history_job_image_to_video_workflow(self, job_id: str) -> None:
        self.video_workflow_calls.append(job_id)


def _make_entry(job_id: str) -> JobHistoryEntry:
    timestamp = "2025-01-01T12:00:00"
    return JobHistoryEntry(
        job_id=job_id,
        created_at=timestamp,
        status=JobStatus.COMPLETED,
        payload_summary="PackA",
        completed_at=timestamp,
        started_at=timestamp,
    )


@pytest.mark.gui
def test_job_history_panel_updates_and_opens_folder(tk_root, tmp_path, monkeypatch) -> None:
    controller = DummyController()
    app_state = AppStateV2()
    open_calls: list[str] = []

    def fake_opener(path: str) -> None:
        open_calls.append(path)

    panel = JobHistoryPanelV2(
        tk_root,
        controller=controller,
        app_state=app_state,
        folder_opener=fake_opener,
    )

    entry = _make_entry("job123")
    image_path = tmp_path / "job123" / "image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png")
    entry.result = {
        "artifact": {
            "schema": "stablenew.artifact.v2.6",
            "artifact_type": "image",
            "primary_path": str(image_path),
            "output_paths": [str(image_path)],
        }
    }
    app_state.set_history_items([entry])
    tk_root.update_idletasks()

    children = panel.history_tree.get_children()
    assert children, "Panel should have history entries"

    panel.history_tree.selection_set(children[0])
    panel.history_tree.event_generate("<<TreeviewSelect>>")
    panel.open_btn.invoke()
    panel.replay_btn.invoke()
    panel.svd_btn.invoke()
    panel.video_workflow_btn.invoke()

    assert open_calls, "Open folder should be invoked for selected job"
    assert controller.refresh_calls == 0
    assert controller.replay_calls == 1
    assert controller.svd_calls == ["job123"]
    assert controller.video_workflow_calls == ["job123"]
    panel.refresh_btn.invoke()
    assert controller.refresh_calls == 1


@pytest.mark.gui
def test_job_history_panel_efficiency_tooltip_summary(tk_root) -> None:
    panel = JobHistoryPanelV2(tk_root, controller=DummyController(), app_state=AppStateV2())
    entry = _make_entry("job-eff")
    entry.result = {
        "metadata": {
            "efficiency_metrics": {
                "elapsed_seconds": 12.5,
                "images_per_minute": 9.6,
                "model_switches": 1,
                "vae_switches": 0,
            }
        }
    }

    text = panel._extract_efficiency_summary(entry)
    assert "elapsed=12.5s" in text
    assert "img/min=9.6" in text
    assert "model_sw=1" in text


@pytest.mark.gui
def test_job_history_panel_disables_image_handoff_for_video_artifacts(tk_root, tmp_path) -> None:
    controller = DummyController()
    app_state = AppStateV2()
    panel = JobHistoryPanelV2(tk_root, controller=controller, app_state=app_state)

    video_path = tmp_path / "run-001" / "clip.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    entry = _make_entry("job-video")
    entry.result = {
        "metadata": {
            "animatediff_artifact": {
                "primary_path": str(video_path),
                "output_paths": [str(video_path)],
                "count": 1,
                "artifacts": [
                    {
                        "schema": "stablenew.artifact.v2.6",
                        "artifact_type": "video",
                        "primary_path": str(video_path),
                        "output_paths": [str(video_path)],
                    }
                ],
            }
        }
    }

    app_state.set_history_items([entry])
    tk_root.update_idletasks()
    children = panel.history_tree.get_children()
    panel.history_tree.selection_set(children[0])
    panel.history_tree.event_generate("<<TreeviewSelect>>")

    assert panel.svd_btn.instate(["disabled"])
    # Video Workflow stays disabled unless the video result exposes a thumbnail/source frame.
    assert panel.video_workflow_btn.instate(["disabled"])


@pytest.mark.gui
def test_job_history_panel_uses_generic_video_artifact_metadata(tk_root, tmp_path) -> None:
    controller = DummyController()
    app_state = AppStateV2()
    panel = JobHistoryPanelV2(tk_root, controller=controller, app_state=app_state)

    video_path = tmp_path / "run-generic" / "clip.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    entry = _make_entry("job-generic-video")
    entry.result = {
        "metadata": {
            "video_artifacts": {
                "animatediff": {
                    "stage": "animatediff",
                    "backend_id": "animatediff",
                    "artifact_type": "video",
                    "primary_path": str(video_path),
                    "output_paths": [str(video_path)],
                    "count": 1,
                    "artifacts": [
                        {
                            "schema": "stablenew.artifact.v2.6",
                            "artifact_type": "video",
                            "primary_path": str(video_path),
                            "output_paths": [str(video_path)],
                        }
                    ],
                }
            },
            "video_primary_artifact": {
                "stage": "animatediff",
                "backend_id": "animatediff",
                "artifact_type": "video",
                "primary_path": str(video_path),
                "output_paths": [str(video_path)],
                "count": 1,
            },
        }
    }

    app_state.set_history_items([entry])
    tk_root.update_idletasks()
    children = panel.history_tree.get_children()
    panel.history_tree.selection_set(children[0])
    panel.history_tree.event_generate("<<TreeviewSelect>>")

    assert panel._extract_image_count(entry) == "1"
    assert panel._extract_output_folder(entry) == "run-generic"
    assert panel.svd_btn.instate(["disabled"])
    # Without thumbnail/source frame metadata, the workflow handoff must stay disabled.
    assert panel.video_workflow_btn.instate(["disabled"])


# ---------------------------------------------------------------------------
# PR-VIDEO-215: video_workflow_artifact key and separate button states
# ---------------------------------------------------------------------------

@pytest.mark.gui
def test_panel_video_workflow_artifact_enables_video_workflow_button(tk_root, tmp_path) -> None:
    """Video Workflow button must be ENABLED for workflow-video outputs.

    SVD button must stay DISABLED (video artifacts are not valid SVD inputs).
    """
    controller = DummyController()
    app_state = AppStateV2()
    panel = JobHistoryPanelV2(tk_root, controller=controller, app_state=app_state)

    video_path = tmp_path / "run-workflow" / "clip.mp4"
    thumb_path = tmp_path / "run-workflow" / "frame_001.png"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    thumb_path.write_bytes(b"png")

    entry = _make_entry("job-workflow-video")
    entry.result = {
        "video_bundle": {
            "stage": "video_workflow",
            "backend_id": "comfy",
            "primary_path": str(video_path),
            "thumbnail_path": str(thumb_path),
            "manifest_paths": [],
            "output_paths": [str(video_path)],
            "count": 1,
            "artifact_type": "video",
        },
        "metadata": {
            "video_workflow_artifact": {
                "stage": "video_workflow",
                "backend_id": "comfy",
                "artifact_type": "video",
                "primary_path": str(video_path),
                "output_paths": [str(video_path)],
                "count": 1,
                "artifacts": [
                    {
                        "schema": "stablenew.artifact.v2.6",
                        "artifact_type": "video",
                        "primary_path": str(video_path),
                        "output_paths": [str(video_path)],
                    }
                ],
            },
            "video_primary_artifact": {
                "stage": "video_workflow",
                "backend_id": "comfy",
                "artifact_type": "video",
                "primary_path": str(video_path),
                "output_paths": [str(video_path)],
                "thumbnail_path": str(thumb_path),
                "count": 1,
            },
        },
    }

    app_state.set_history_items([entry])
    tk_root.update_idletasks()
    children = panel.history_tree.get_children()
    panel.history_tree.selection_set(children[0])
    panel.history_tree.event_generate("<<TreeviewSelect>>")

    # SVD stays disabled for video results
    assert panel.svd_btn.instate(["disabled"]), "SVD must be disabled for video outputs"
    # Video Workflow should be enabled — we can route the thumbnail as a new input
    assert panel.video_workflow_btn.instate(["!disabled"]), "Video Workflow must be enabled for video outputs"


@pytest.mark.gui
def test_panel_iter_video_artifact_aggregates_includes_video_workflow_artifact(
    tk_root,
) -> None:
    """_iter_video_artifact_aggregates must return video_workflow_artifact entries."""
    panel = JobHistoryPanelV2(tk_root)
    metadata = {
        "video_workflow_artifact": {"stage": "video_workflow", "primary_path": "/out/clip.mp4"},
    }
    aggregates = panel._iter_video_artifact_aggregates(metadata)
    stages = [agg.get("stage") for agg in aggregates]
    assert "video_workflow" in stages


def test_entry_supports_video_workflow_handoff_for_image_entry() -> None:
    """Image-type entries should also support Video Workflow handoff."""
    panel = JobHistoryPanelV2.__new__(JobHistoryPanelV2)
    entry = _make_entry("job-img")
    entry.result = {
        "artifact": {
            "schema": "stablenew.artifact.v2.6",
            "artifact_type": "image",
            "primary_path": "/out/img.png",
            "output_paths": ["/out/img.png"],
        }
    }
    assert panel._entry_supports_video_workflow_handoff(entry) is True


def test_entry_supports_video_workflow_handoff_for_video_bundle() -> None:
    """Video entries with video_bundle should support Video Workflow handoff."""
    panel = JobHistoryPanelV2.__new__(JobHistoryPanelV2)
    entry = _make_entry("job-vid")
    entry.result = {
        "video_bundle": {
            "primary_path": "/out/clip.mp4",
            "thumbnail_path": "/out/frame_001.png",
        }
    }
    assert panel._entry_supports_video_workflow_handoff(entry) is True


def test_entry_supports_video_workflow_handoff_false_without_usable_output() -> None:
    """History entries with no image source or video thumbnail/frame should be disabled."""
    panel = JobHistoryPanelV2.__new__(JobHistoryPanelV2)
    entry = _make_entry("job-empty")
    entry.result = {
        "video_bundle": {
            "primary_path": "/out/clip.mp4",
            "output_paths": ["/out/clip.mp4"],
        }
    }
    assert panel._entry_supports_video_workflow_handoff(entry) is False


def test_entry_supports_image_handoff_false_for_video() -> None:
    """Image-handoff remains False for video artifacts (SVD stays disabled)."""
    panel = JobHistoryPanelV2.__new__(JobHistoryPanelV2)
    entry = _make_entry("job-vid")
    entry.result = {
        "metadata": {
            "video_primary_artifact": {
                "artifact_type": "video",
                "primary_path": "/out/clip.mp4",
                "output_paths": ["/out/clip.mp4"],
                "count": 1,
                "artifacts": [
                    {
                        "schema": "stablenew.artifact.v2.6",
                        "artifact_type": "video",
                        "primary_path": "/out/clip.mp4",
                        "output_paths": ["/out/clip.mp4"],
                    }
                ],
            }
        }
    }
    assert panel._entry_supports_image_handoff(entry) is False

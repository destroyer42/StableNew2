from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2


class _ControllerStub:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, dict[str, object]]] = []

    def build_video_workflow_defaults(self) -> dict[str, object]:
        return {
            "workflow_id": "ltx_multiframe_anchor_v1",
            "motion_profile": "gentle",
            "output_route": "Reprocess",
        }

    def get_video_workflow_specs(self) -> list[dict[str, object]]:
        return [
            {
                "workflow_id": "ltx_multiframe_anchor_v1",
                "workflow_version": "1.0.0",
                "backend_id": "comfy",
                "display_name": "LTX Multi-Frame Anchor v1",
            }
        ]

    def get_latest_output_image_path(self) -> str:
        return "C:/tmp/latest.png"

    def submit_video_workflow_job(self, *, source_image_path: str, form_data: dict[str, object]) -> str:
        self.submissions.append((source_image_path, dict(form_data)))
        return "job-video-1"


@pytest.mark.gui
def test_video_workflow_tab_handoff_and_state_roundtrip(tk_root) -> None:
    controller = _ControllerStub()
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=controller, app_state=SimpleNamespace())

    tab.set_source_image_path("C:/tmp/source.png", status_message="loaded")
    tab.end_anchor_var.set("C:/tmp/end.png")
    tab.mid_anchors_var.set("C:/tmp/mid1.png; C:/tmp/mid2.png")
    tab.motion_profile_var.set("balanced")
    tab.output_route_var.set("movie_clips")
    tab.prompt_text.insert("1.0", "prompt text")
    tab.negative_prompt_text.insert("1.0", "negative text")

    state = tab.get_video_workflow_state()

    assert state["workflow_id"] == "ltx_multiframe_anchor_v1"
    assert state["source_image_path"] == "C:/tmp/source.png"
    assert state["end_anchor_path"] == "C:/tmp/end.png"
    assert state["mid_anchor_paths"] == ["C:/tmp/mid1.png", "C:/tmp/mid2.png"]
    assert state["motion_profile"] == "balanced"
    assert state["output_route"] == "movie_clips"
    assert state["prompt"] == "prompt text"
    assert state["negative_prompt"] == "negative text"

    tab.restore_video_workflow_state(
        {
            "workflow_id": "ltx_multiframe_anchor_v1",
            "source_image_path": "C:/tmp/source-2.png",
            "end_anchor_path": "C:/tmp/end-2.png",
            "mid_anchor_paths": ["C:/tmp/mid-a.png"],
            "motion_profile": "dynamic",
            "output_route": "Testing",
            "prompt": "new prompt",
            "negative_prompt": "new negative",
        }
    )

    restored = tab.get_video_workflow_state()
    assert restored["source_image_path"] == "C:/tmp/source-2.png"
    assert restored["end_anchor_path"] == "C:/tmp/end-2.png"
    assert restored["mid_anchor_paths"] == ["C:/tmp/mid-a.png"]
    assert restored["motion_profile"] == "dynamic"
    assert restored["output_route"] == "Testing"
    assert restored["prompt"] == "new prompt"
    assert restored["negative_prompt"] == "new negative"
    assert "End anchor" in tab.source_summary_var.get()
    assert "LTX Multi-Frame Anchor v1" in tab.workflow_detail_var.get()
    assert "Effective settings:" in tab.effective_settings_var.get()
    assert "motion=dynamic [selected here]" in tab.effective_settings_var.get()


# ---------------------------------------------------------------------------
# PR-VIDEO-215: set_source_bundle handoff
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_video_workflow_tab_set_source_bundle_uses_thumbnail(tk_root) -> None:
    """set_source_bundle picks thumbnail_path over source_image_path."""
    controller = _ControllerStub()
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=controller)

    bundle = {
        "thumbnail_path": "C:/tmp/frame_001.png",
        "source_image_path": "C:/tmp/start.png",
        "primary_path": "C:/tmp/clip.mp4",
    }
    tab.set_source_bundle(bundle)
    assert tab.source_image_var.get() == "C:/tmp/frame_001.png"
    assert "frame_001.png" in tab.source_summary_var.get()


@pytest.mark.gui
def test_video_workflow_tab_set_source_bundle_falls_back_to_source_image(tk_root) -> None:
    """set_source_bundle falls back to source_image_path when no thumbnail."""
    controller = _ControllerStub()
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=controller)

    bundle = {
        "thumbnail_path": None,
        "source_image_path": "C:/tmp/start.png",
    }
    tab.set_source_bundle(bundle)
    assert tab.source_image_var.get() == "C:/tmp/start.png"
    assert "start.png" in tab.source_summary_var.get()


@pytest.mark.gui
def test_video_workflow_tab_set_source_bundle_accepts_custom_status(tk_root) -> None:
    """set_source_bundle applies a caller-provided status message."""
    controller = _ControllerStub()
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=controller)

    bundle = {"thumbnail_path": "C:/tmp/frame_001.png"}
    tab.set_source_bundle(bundle, status_message="Loaded from history")
    assert tab.status_var.get() == "Loaded from history"


@pytest.mark.gui
def test_video_workflow_tab_set_source_bundle_empty_bundle_no_crash(tk_root) -> None:
    """set_source_bundle with an empty bundle does not raise."""
    controller = _ControllerStub()
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=controller)
    tab.set_source_bundle({})  # should not raise
    assert tab.source_summary_var.get()
    assert "Effective settings:" in tab.effective_settings_var.get()

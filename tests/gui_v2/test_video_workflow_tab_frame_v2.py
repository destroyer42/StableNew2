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
            "camera_intent": {"preset": "none", "strength": 0.35},
            "controlnet": {
                "model": "depth",
                "weight": 1.0,
                "guidance_start": 0.0,
                "guidance_end": 1.0,
            },
            "depth_input": {"mode": "none", "path": ""},
            "output_route": "Reprocess",
        }

    def get_video_workflow_specs(self) -> list[dict[str, object]]:
        return [
            {
                "workflow_id": "ltx_multiframe_anchor_v1",
                "workflow_version": "1.0.0",
                "backend_id": "comfy",
                "display_name": "LTX Multi-Frame Anchor v1",
            },
            {
                "workflow_id": "ltx_multiframe_anchor_v1_conditioned",
                "workflow_version": "1.0.0",
                "backend_id": "comfy",
                "display_name": "LTX Multi-Frame Anchor v1 Conditioned",
            },
        ]

    def get_latest_output_image_path(self) -> str:
        return "C:/tmp/latest.png"

    def submit_video_workflow_job(
        self, *, source_image_path: str, form_data: dict[str, object]
    ) -> str:
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
    tab.camera_preset_var.set("dolly_in")
    tab.camera_strength_var.set("0.4")
    tab.depth_mode_var.set("upload")
    tab.depth_path_var.set("C:/tmp/depth.png")
    tab.controlnet_model_var.set("depth")
    tab.controlnet_weight_var.set("0.9")
    tab.controlnet_guidance_start_var.set("0.1")
    tab.controlnet_guidance_end_var.set("0.9")
    tab.output_route_var.set("movie_clips")
    tab.prompt_text.insert("1.0", "prompt text")
    tab.negative_prompt_text.insert("1.0", "negative text")

    state = tab.get_video_workflow_state()

    assert state["workflow_id"] == "ltx_multiframe_anchor_v1"
    assert state["source_image_path"] == "C:/tmp/source.png"
    assert state["end_anchor_path"] == "C:/tmp/end.png"
    assert state["mid_anchor_paths"] == ["C:/tmp/mid1.png", "C:/tmp/mid2.png"]
    assert state["motion_profile"] == "balanced"
    assert state["camera_intent"]["preset"] == "dolly_in"
    assert state["depth_input"]["mode"] == "upload"
    assert state["controlnet"]["guidance_end"] == "0.9"
    assert state["output_route"] == "movie_clips"
    assert state["prompt"] == "prompt text"
    assert state["negative_prompt"] == "negative text"

    tab.restore_video_workflow_state(
        {
            "workflow_id": "ltx_multiframe_anchor_v1_conditioned",
            "source_image_path": "C:/tmp/source-2.png",
            "end_anchor_path": "C:/tmp/end-2.png",
            "mid_anchor_paths": ["C:/tmp/mid-a.png"],
            "motion_profile": "dynamic",
            "camera_intent": {"preset": "orbit_left", "strength": 0.55},
            "controlnet": {
                "model": "depth",
                "weight": 0.8,
                "guidance_start": 0.2,
                "guidance_end": 0.85,
            },
            "depth_input": {"mode": "auto", "path": ""},
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
    assert restored["camera_intent"]["preset"] == "orbit_left"
    assert restored["depth_input"]["mode"] == "auto"
    assert restored["controlnet"]["guidance_start"] == "0.2"
    assert restored["output_route"] == "Testing"
    assert restored["prompt"] == "new prompt"
    assert restored["negative_prompt"] == "new negative"
    assert "End anchor" in tab.source_summary_var.get()
    assert "LTX Multi-Frame Anchor v1 Conditioned" in tab.workflow_detail_var.get()
    assert "Effective settings:" in tab.effective_settings_var.get()
    assert "motion=dynamic [selected here]" in tab.effective_settings_var.get()
    assert "depth=auto" in tab.effective_settings_var.get()


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


@pytest.mark.gui
def test_video_workflow_tab_submit_serializes_conditioning_payload(tk_root, monkeypatch) -> None:
    controller = _ControllerStub()
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=controller)
    tab.source_image_var.set("C:/tmp/source.png")
    tab.workflow_var.set("ltx_multiframe_anchor_v1_conditioned")
    tab.end_anchor_var.set("C:/tmp/end.png")
    tab.depth_mode_var.set("auto")
    tab.camera_preset_var.set("dolly_in")
    tab.camera_strength_var.set("0.5")
    tab.controlnet_model_var.set("depth")
    tab.controlnet_weight_var.set("0.8")
    tab.controlnet_guidance_start_var.set("0.1")
    tab.controlnet_guidance_end_var.set("0.9")
    monkeypatch.setattr(
        "src.gui.views.video_workflow_tab_frame_v2.messagebox.showinfo",
        lambda *_args, **_kwargs: None,
    )

    tab._on_submit()

    assert controller.submissions
    _, form_data = controller.submissions[0]
    assert form_data["workflow_id"] == "ltx_multiframe_anchor_v1_conditioned"
    assert form_data["depth_input"]["mode"] == "auto"
    assert form_data["camera_intent"]["preset"] == "dolly_in"
    assert form_data["controlnet"]["guidance_end"] == "0.9"


class _FrameCountControllerStub(_ControllerStub):
    """A variable-length workflow (declares a frame-count projection) beside one without."""

    def build_video_workflow_defaults(self) -> dict[str, object]:
        return {**super().build_video_workflow_defaults(), "workflow_id": "variable_len"}

    def get_video_workflow_specs(self) -> list[dict[str, object]]:
        return [
            {
                "workflow_id": "variable_len",
                "workflow_version": "1.1.0",
                "backend_id": "comfy",
                "display_name": "Variable length",
                "form_visibility": {"frame_count": True, "seed": True},
                "frame_count": {
                    "default": 49,
                    "fps": 24,
                    "choices": [
                        {"frames": 17, "seconds": 0.7},
                        {"frames": 49, "seconds": 2.0},
                        {"frames": 81, "seconds": 3.4},
                    ],
                },
            },
            {
                "workflow_id": "fixed_len",
                "workflow_version": "1.0.0",
                "backend_id": "comfy",
                "display_name": "Fixed length",
                "form_visibility": {"frame_count": False, "seed": True},
                "frame_count": None,
            },
        ]


@pytest.mark.gui
def test_frame_count_selector_follows_the_selected_workflows_declared_lengths(tk_root) -> None:
    tab = VideoWorkflowTabFrameV2(
        tk_root, app_controller=_FrameCountControllerStub(), app_state=SimpleNamespace()
    )
    tab.workflow_var.set("variable_len")

    assert list(tab.frame_count_combo["values"]) == [
        "17 frames (~0.7 s)",
        "49 frames (~2.0 s)",
        "81 frames (~3.4 s)",
    ]
    assert tab.frame_count_var.get() == "49 frames (~2.0 s)"  # declared default preselected
    assert tab.get_video_workflow_state()["frame_count"] == 49
    tab.frame_count_var.set("81 frames (~3.4 s)")
    assert tab.get_video_workflow_state()["frame_count"] == 81
    assert "length=81 frames (~3.4 s)" in tab.effective_settings_var.get()

    tab.workflow_var.set("fixed_len")
    assert "frame_count" not in tab.get_video_workflow_state()
    assert tab.frame_count_var.get() == ""
    assert not tab.frame_count_frame.winfo_ismapped()

    tab.restore_video_workflow_state({"workflow_id": "variable_len", "frame_count": 17})
    assert tab.get_video_workflow_state()["frame_count"] == 17


class _DrivingVideoControllerStub(_ControllerStub):
    def build_video_workflow_defaults(self) -> dict[str, object]:
        return {**super().build_video_workflow_defaults(), "workflow_id": "drive"}

    def get_video_workflow_specs(self) -> list[dict[str, object]]:
        return [
            {
                "workflow_id": "drive",
                "workflow_version": "1.0.0",
                "display_name": "Driving video",
                "form_visibility": {"pose_video": True, "frame_count": False},
            },
            {
                "workflow_id": "prompt",
                "workflow_version": "1.0.0",
                "display_name": "Prompt only",
                "form_visibility": {"pose_video": False, "frame_count": False},
            },
        ]


@pytest.mark.gui
def test_driving_video_field_is_shown_only_for_workflows_that_accept_one(tk_root) -> None:
    tab = VideoWorkflowTabFrameV2(
        tk_root, app_controller=_DrivingVideoControllerStub(), app_state=SimpleNamespace()
    )
    tab.workflow_var.set("drive")
    tab.pose_video_var.set("C:/clips/drive.mp4")
    assert tab.get_video_workflow_state()["pose_video_path"] == "C:/clips/drive.mp4"

    tab.workflow_var.set("prompt")
    assert "pose_video_path" not in tab.get_video_workflow_state()
    assert tab.pose_video_var.get() == ""

    tab.restore_video_workflow_state(
        {"workflow_id": "drive", "pose_video_path": "C:/clips/other.mp4"}
    )
    assert tab.get_video_workflow_state()["pose_video_path"] == "C:/clips/other.mp4"

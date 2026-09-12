from __future__ import annotations

import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.controller.svd_controller import SVDController
from src.gui.app_state_v2 import AppStateV2
from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2
from src.video.svd_models import get_default_svd_cache_dir


class _FakeVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class _FakeWidget:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def configure(self, **kwargs: object) -> None:
        self.values.update(kwargs)


def _capability_projection_tab(controller: Mock, source: str = "") -> SVDTabFrameV2:
    tab = SVDTabFrameV2.__new__(SVDTabFrameV2)
    tab.app_controller = controller
    tab.source_image_var = _FakeVar(source)
    tab.capabilities_label = _FakeWidget()
    tab.admission_label = _FakeWidget()
    tab.animate_btn = _FakeWidget()
    tab._build_form_data = lambda: {}
    return tab


def test_svd_tab_renders(tk_root: tk.Tk) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        assert hasattr(tab, "source_entry")
        assert hasattr(tab, "model_combo")
        assert hasattr(tab, "animate_btn")
        assert hasattr(tab, "recent_tree")
        assert hasattr(tab, "admission_label")
        assert hasattr(tab, "capabilities_label")
        assert tab.output_format_var.get() == "mp4"
        assert tab.preset_var.get() == "Recommended 12GB / XT 14f"
        assert tab.frames_var.get() == 14
        assert tab.fps_var.get() == 7
        assert tab.inference_steps_var.get() == 25
        assert tab.decode_chunk_size_var.get() == 2
        assert tab.cpu_offload_var.get() is True
        assert tab.forward_chunking_var.get() is True
        assert tab.face_restore_method_var.get() == "CodeFormer"
        assert tab.resize_mode_var.get() == "center_crop"
        assert tab.target_preset_var.get() == "Match Source Aspect"
        assert tab.motion_bucket_var.get() == 48
        assert tab.noise_aug_var.get() == 0.01
        assert tab.local_files_only_var.get() is True
        assert tab.cache_dir_var.get() == str(get_default_svd_cache_dir())
    finally:
        tab.destroy()


def test_svd_tab_help_sections_use_distinct_rows(tk_root: tk.Tk) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        assert int(tab.summary_label.grid_info()["row"]) == 1
        assert int(tab.admission_label.grid_info()["row"]) == 2
        assert int(tab.capabilities_label.grid_info()["row"]) == 3
        assert int(tab.workflow_help_panel.grid_info()["row"]) == 4
    finally:
        tab.destroy()


def test_svd_tab_state_round_trip(tk_root: tk.Tk) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        payload = {
            "source_image_path": "C:/tmp/source.png",
            "last_folder": "C:/tmp",
            "preset_name": "GIF Preview",
            "model_id": tab.model_var.get(),
            "num_frames": 14,
            "fps": 8,
            "motion_bucket_id": 99,
            "noise_aug_strength": 0.08,
            "num_inference_steps": 33,
            "seed": "1234",
            "target_preset": "Portrait 576x1024",
            "resize_mode": "center_crop",
            "output_format": "gif",
            "output_route": "Testing",
            "save_frames": True,
            "cpu_offload": False,
            "forward_chunking": False,
            "local_files_only": True,
            "decode_chunk_size": 4,
            "cache_dir": "C:/cache/svd",
            "face_restore_enabled": True,
            "face_restore_method": "CodeFormer",
            "face_restore_fidelity": 0.65,
            "interpolation_enabled": True,
            "interpolation_multiplier": 2,
            "rife_executable_path": "C:/tools/rife/rife-ncnn-vulkan.exe",
            "frame_upscale_enabled": True,
            "frame_upscale_factor": 2.5,
        }
        assert tab.restore_svd_state(payload) is True
        state = tab.get_svd_state()
        assert state["source_image_path"] == "C:/tmp/source.png"
        assert state["preset_name"] == "GIF Preview"
        assert state["num_frames"] == 14
        assert state["num_inference_steps"] == 33
        assert state["output_format"] == "gif"
        assert state["output_route"] == "Testing"
        assert state["save_frames"] is True
        assert state["local_files_only"] is True
        assert state["cache_dir"] == "C:/cache/svd"
        assert state["face_restore_enabled"] is True
        assert state["interpolation_enabled"] is True
        assert state["frame_upscale_enabled"] is True
    finally:
        tab.destroy()


def test_svd_tab_submit_calls_controller(tk_root: tk.Tk, tmp_path: Path) -> None:
    image_path = tmp_path / "source.png"
    image_path.write_bytes(b"png")
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.submit_svd_job.return_value = "job-svd-123"

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        tab.source_image_var.set(str(image_path))
        with patch("src.gui.views.svd_tab_frame_v2.messagebox.showinfo"):
            tab._on_submit()
        controller.submit_svd_job.assert_called_once()
        kwargs = controller.submit_svd_job.call_args.kwargs
        assert kwargs["source_image_path"] == str(image_path)
        assert kwargs["form_data"]["inference"]["model_id"] == tab.model_var.get()
        assert kwargs["form_data"]["pipeline"]["output_route"] == "SVD"
        assert kwargs["form_data"]["postprocess"]["face_restore"]["method"] == "CodeFormer"
    finally:
        tab.destroy()


def test_svd_tab_refreshes_capabilities_from_controller(tk_root: tk.Tk) -> None:
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.get_svd_postprocess_capabilities.return_value = {
        "codeformer": {
            "name": "CodeFormer",
            "status": "ready",
            "available": True,
            "detail": "Detected local weights",
        },
        "realesrgan": {
            "name": "RealESRGAN",
            "status": "experimental",
            "available": True,
            "detail": "Detected local weight",
        },
    }

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        assert "CodeFormer: ready" in tab.capabilities_label.cget("text")
        controller.get_svd_postprocess_capabilities.assert_called()
    finally:
        tab.destroy()


def test_svd_tab_disables_submit_when_admission_is_blocked(tk_root: tk.Tk) -> None:
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.get_svd_postprocess_capabilities.return_value = {
        "admission": {
            "available": False,
            "blocking_reasons": ["Local-only mode requires a complete cached SVD model."],
            "warnings": [],
        }
    }

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        assert "admission blocked" in tab.admission_label.cget("text").lower()
        assert str(tab.animate_btn.cget("state")) == "disabled"
    finally:
        tab.destroy()


def test_svd_tab_blocks_admission_without_selected_source(tk_root: tk.Tk) -> None:
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.get_svd_postprocess_capabilities.return_value = {
        "admission": {
            "available": False,
            "blocking_reasons": ["Select a source image."],
            "warnings": [],
        }
    }

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        assert "Select a source image." in tab.admission_label.cget("text")
        assert str(tab.animate_btn.cget("state")) == "disabled"
        assert controller.get_svd_postprocess_capabilities.call_args.kwargs["source_image_path"] is None
    finally:
        tab.destroy()


def test_svd_tab_projects_invalid_source_admission_blocker(tk_root: tk.Tk, tmp_path: Path) -> None:
    source_path = tmp_path / "missing.png"
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.get_svd_postprocess_capabilities.side_effect = lambda _form_data, **kwargs: {
        "admission": {
            "available": False,
            "blocking_reasons": [f"Invalid SVD source image: {kwargs['source_image_path']}"],
            "warnings": [],
        }
    }

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        tab.set_source_image_path(source_path)
        assert "Invalid SVD source image:" in tab.admission_label.cget("text")
        assert str(tab.animate_btn.cget("state")) == "disabled"
    finally:
        tab.destroy()


def test_svd_tab_enables_submit_for_valid_source_admission(tk_root: tk.Tk, tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.get_svd_postprocess_capabilities.side_effect = lambda _form_data, **kwargs: {
        "admission": {
            "available": bool(kwargs["source_image_path"]),
            "blocking_reasons": [],
            "warnings": [],
        }
    }

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        tab.set_source_image_path(source_path)
        assert tab.admission_label.cget("text") == "SVD admission: ready"
        assert str(tab.animate_btn.cget("state")) == "normal"
    finally:
        tab.destroy()


def test_svd_tab_capability_projection_passes_source_without_tk() -> None:
    controller = Mock()
    controller.get_svd_postprocess_capabilities.side_effect = lambda _form_data, **kwargs: {
        "admission": {
            "available": kwargs["source_image_path"] == "valid.png",
            "blocking_reasons": (
                [] if kwargs["source_image_path"] == "valid.png" else ["Select a source image."]
            ),
            "warnings": [],
        }
    }
    tab = _capability_projection_tab(controller)

    tab._refresh_capabilities()
    assert tab.admission_label.values["text"] == "SVD admission blocked: Select a source image."
    assert tab.animate_btn.values["state"] == "disabled"

    tab.source_image_var.value = "invalid.png"
    tab._refresh_capabilities()
    assert controller.get_svd_postprocess_capabilities.call_args.kwargs["source_image_path"] == "invalid.png"

    tab.source_image_var.value = "valid.png"
    tab._refresh_capabilities()
    assert tab.admission_label.values["text"] == "SVD admission: ready"
    assert tab.animate_btn.values["state"] == "normal"


def test_svd_tab_applies_runtime_recommended_defaults(tk_root: tk.Tk) -> None:
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.build_svd_defaults.return_value = {
        "inference": {
            "local_files_only": True,
            "cache_dir": "C:/cache/svd",
        },
        "postprocess": {
            "face_restore": {
                "enabled": True,
                "method": "CodeFormer",
                "fidelity_weight": 0.65,
            },
            "interpolation": {
                "enabled": True,
                "multiplier": 2,
                "executable_path": "C:/tools/rife/rife-ncnn-vulkan.exe",
            },
            "upscale": {
                "enabled": True,
                "scale": 2.0,
            },
        }
    }
    controller.get_svd_postprocess_capabilities.return_value = {}

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        assert tab.face_restore_enabled_var.get() is True
        assert tab.interpolation_enabled_var.get() is True
        assert tab.frame_upscale_enabled_var.get() is True
        assert tab.rife_executable_var.get() == "C:/tools/rife/rife-ncnn-vulkan.exe"
        assert tab.local_files_only_var.get() is True
        assert tab.cache_dir_var.get() == "C:/cache/svd"
    finally:
        tab.destroy()


def test_svd_tab_recommended_preset_matches_controller_core_defaults(tk_root: tk.Tk) -> None:
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.get_svd_postprocess_capabilities.return_value = {}
    expected = SVDController(
        app_controller=SimpleNamespace(),
        svd_service=Mock(),
    ).build_default_config().to_dict()["inference"]
    controller.build_svd_defaults.return_value = {
        "inference": expected,
    }

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        assert tab.frames_var.get() == expected["num_frames"]
        assert tab.fps_var.get() == expected["fps"]
        assert tab.motion_bucket_var.get() == expected["motion_bucket_id"]
        assert tab.noise_aug_var.get() == expected["noise_aug_strength"]
        assert tab.inference_steps_var.get() == expected["num_inference_steps"]
        assert tab.decode_chunk_size_var.get() == expected["decode_chunk_size"]
    finally:
        tab.destroy()


def test_svd_tab_use_latest_output_uses_controller_value(tk_root: tk.Tk, tmp_path: Path) -> None:
    image_path = tmp_path / "latest.png"
    image_path.write_bytes(b"png")
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.get_latest_output_image_path.return_value = str(image_path)

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        tab._on_use_latest_output()
        assert tab.source_image_var.get() == str(image_path)
    finally:
        tab.destroy()


def test_svd_tab_prefers_xt_default_model_when_controller_list_is_unsorted(tk_root: tk.Tk) -> None:
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid",
        "stabilityai/stable-video-diffusion-img2vid-xt",
    ]

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        assert tab.model_var.get() == "stabilityai/stable-video-diffusion-img2vid-xt"
        tab._refresh_model_options()
        assert tab.frames_var.get() == 14
    finally:
        tab.destroy()


def test_svd_tab_local_files_only_refreshes_model_options(tk_root: tk.Tk) -> None:
    controller = Mock()
    controller.get_supported_svd_models.side_effect = [
        [
            "stabilityai/stable-video-diffusion-img2vid-xt",
            "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
        ],
        ["stabilityai/stable-video-diffusion-img2vid-xt-1-1"],
    ]

    tab = SVDTabFrameV2(tk_root, app_controller=controller)
    try:
        assert "stabilityai/stable-video-diffusion-img2vid-xt" in list(tab.model_combo.cget("values"))
        tab.local_files_only_var.set(True)
        assert list(tab.model_combo.cget("values")) == ["stabilityai/stable-video-diffusion-img2vid-xt-1-1"]
        assert tab.model_var.get() == "stabilityai/stable-video-diffusion-img2vid-xt-1-1"
    finally:
        tab.destroy()


def test_svd_tab_preset_applies_expected_values(tk_root: tk.Tk) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        tab.preset_var.set("Frames Only 25f / High Memory")
        tab._on_preset_selected()

        assert tab.output_format_var.get() == "frames"
        assert tab.save_frames_var.get() is True
        assert tab.frames_var.get() == 25
        assert tab.decode_chunk_size_var.get() == 4
        assert "Memory:" in tab.summary_label.cget("text")
    finally:
        tab.destroy()


def test_svd_tab_matches_source_aspect_and_persists_resolved_target_in_form(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    from PIL import Image

    source_path = tmp_path / "portrait.png"
    Image.new("RGB", (832, 1216), color="black").save(source_path)
    tab = SVDTabFrameV2(tk_root)
    try:
        tab.set_source_image_path(source_path)
        assert tab.target_preset_var.get() == "Match Source Aspect"
        form_data = tab._build_form_data()
        assert form_data["preprocess"]["target_width"] == 640
        assert form_data["preprocess"]["target_height"] == 960
        assert "SVD target: 640x960" in tab.summary_label.cget("text")
        assert "source 832x1216" in tab.summary_label.cget("text")
    finally:
        tab.destroy()


def test_svd_tab_manual_target_overrides_source_matching_after_source_change(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    from PIL import Image

    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    Image.new("RGB", (832, 1216), color="black").save(first_path)
    Image.new("RGB", (1152, 896), color="white").save(second_path)
    tab = SVDTabFrameV2(tk_root)
    try:
        tab.set_source_image_path(first_path)
        tab.target_preset_var.set("Landscape 1024x576")
        tab.set_source_image_path(second_path)
        form_data = tab._build_form_data()
        assert form_data["preprocess"]["target_width"] == 1024
        assert form_data["preprocess"]["target_height"] == 576
        assert tab.target_preset_var.get() == "Landscape 1024x576"
    finally:
        tab.destroy()


def test_svd_tab_recent_history_populates_and_reuses_source(tk_root: tk.Tk, tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    preview_path = tmp_path / "preview.png"
    output_path = tmp_path / "clip.mp4"
    source_path.write_bytes(b"png")
    preview_path.write_bytes(b"png")
    output_path.write_bytes(b"mp4")

    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.get_recent_svd_history.return_value = [
            {
                "job_id": "job-svd-1",
                "completed_at": "2026-03-14T20:00:00",
                "source_image_path": str(source_path),
                "thumbnail_path": str(preview_path),
                "output_path": str(output_path),
                "video_path": str(output_path),
                "output_dir": str(tmp_path),
                "manifest_path": str(tmp_path / "manifest.json"),
            "frame_count": 25,
            "fps": 7,
            "model_id": "stabilityai/stable-video-diffusion-img2vid-xt",
            "postprocess_applied": ["interpolation", "upscale"],
            "postprocess_input_frame_count": 25,
            "postprocess_output_frame_count": 49,
            "postprocess_output_width": 2048,
            "postprocess_output_height": 1152,
        }
    ]

    tab = SVDTabFrameV2(tk_root, app_controller=controller, app_state=AppStateV2())
    try:
        children = tab.recent_tree.get_children()
        assert children
        tab.recent_tree.selection_set(children[0])
        tab._on_recent_select()
        tab._on_recent_use_source()
        assert tab.source_image_var.get() == str(source_path)
        assert tab.recent_preview._open_path == str(output_path)
        assert str(tab.use_recent_btn.cget("state")) == "normal"
        values = tab.recent_tree.item(children[0], "values")
        assert values[3] == "interp+upscale"
        assert "frames 25->49" in tab.recent_meta_label.cget("text")
        assert "size 2048x1152" in tab.recent_meta_label.cget("text")
    finally:
        tab.destroy()


def test_svd_tab_defers_recent_history_refresh_until_mapped(tk_root: tk.Tk) -> None:
    state = AppStateV2()
    controller = Mock()
    controller.get_supported_svd_models.return_value = [
        "stabilityai/stable-video-diffusion-img2vid-xt"
    ]
    controller.get_recent_svd_history.return_value = []
    tab = SVDTabFrameV2(tk_root, app_controller=controller, app_state=state)
    try:
        tab._refresh_recent_runs = Mock()

        state.set_history_items([object()])
        state.flush_now()

        tab._refresh_recent_runs.assert_not_called()
        assert tab._pending_recent_runs_refresh is True

        tab._on_map()
        tk_root.update_idletasks()
        tk_root.update()

        tab._refresh_recent_runs.assert_called_once()
    finally:
        tab.destroy()

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import tkinter as tk

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2


def test_svd_tab_renders(tk_root: tk.Tk) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        assert hasattr(tab, "source_entry")
        assert hasattr(tab, "model_combo")
        assert hasattr(tab, "animate_btn")
        assert hasattr(tab, "recent_tree")
        assert tab.output_format_var.get() == "mp4"
        assert tab.preset_var.get() == "Quality 25f MP4"
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
    finally:
        tab.destroy()


def test_svd_tab_preset_applies_expected_values(tk_root: tk.Tk) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        tab.preset_var.set("Frames Only")
        tab._on_preset_selected()

        assert tab.output_format_var.get() == "frames"
        assert tab.save_frames_var.get() is True
        assert tab.frames_var.get() == 25
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
    finally:
        tab.destroy()

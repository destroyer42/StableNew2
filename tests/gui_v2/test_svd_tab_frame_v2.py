from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import tkinter as tk

from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2


def test_svd_tab_renders(tk_root: tk.Tk) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        assert hasattr(tab, "source_entry")
        assert hasattr(tab, "model_combo")
        assert hasattr(tab, "animate_btn")
        assert tab.output_format_var.get() == "mp4"
    finally:
        tab.destroy()


def test_svd_tab_state_round_trip(tk_root: tk.Tk) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        payload = {
            "source_image_path": "C:/tmp/source.png",
            "last_folder": "C:/tmp",
            "model_id": tab.model_var.get(),
            "num_frames": 14,
            "fps": 8,
            "motion_bucket_id": 99,
            "noise_aug_strength": 0.08,
            "seed": "1234",
            "target_preset": "Portrait 576x1024",
            "resize_mode": "center_crop",
            "output_format": "gif",
            "save_frames": True,
            "cpu_offload": False,
            "forward_chunking": False,
            "decode_chunk_size": 4,
        }
        assert tab.restore_svd_state(payload) is True
        state = tab.get_svd_state()
        assert state["source_image_path"] == "C:/tmp/source.png"
        assert state["num_frames"] == 14
        assert state["output_format"] == "gif"
        assert state["save_frames"] is True
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

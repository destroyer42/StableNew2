from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import tkinter as tk
from PIL import Image

from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.utils.image_metadata import ReadPayloadResult


def _write_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color=(90, 110, 130)).save(path)


def _read_text(widget: tk.Text) -> str:
    return widget.get("1.0", tk.END).strip()


def test_review_tab_modify_mode_uses_resolved_metadata_prompt(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    image_path = tmp_path / "review.png"
    _write_image(image_path)
    payload = {
        "generation": {
            "model": "modelA.safetensors",
            "vae": "vaeA",
        },
        "stage_manifest": {
            "final_prompt": "resolved portrait prompt",
            "config": {
                "negative_prompt": "bad hands",
            },
        },
    }

    tab = ReviewTabFrame(tk_root)
    try:
        with patch(
            "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
            return_value=ReadPayloadResult(payload=payload, status="ok"),
        ):
            tab._show_image(image_path)

        assert _read_text(tab.current_prompt_text) == "resolved portrait prompt"
        assert _read_text(tab.current_negative_text) == "bad hands"

        tab.prompt_mode_var.set("append")
        tab.prompt_text.delete("1.0", tk.END)
        tab.prompt_text.insert("1.0", "cinematic lighting")
        tab._refresh_prompt_diff()
        assert "After +: resolved portrait prompt, cinematic lighting" in tab.diff_after_label.cget("text")

        tab.prompt_mode_var.set("modify")
        assert _read_text(tab.prompt_text) == "resolved portrait prompt"
        tab.prompt_text.delete("1.0", tk.END)
        tab.prompt_text.insert("1.0", "resolved portrait prompt, cinematic lighting")
        tab._refresh_prompt_diff()
        assert "After +: resolved portrait prompt, cinematic lighting" in tab.diff_after_label.cget("text")
    finally:
        tab.destroy()


def test_review_tab_modify_mode_short_delta_preserves_base_prompt(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    image_path = tmp_path / "review_short_delta.png"
    _write_image(image_path)
    payload = {
        "stage_manifest": {
            "final_prompt": "resolved portrait prompt",
            "config": {
                "negative_prompt": "bad hands",
            },
        },
    }

    tab = ReviewTabFrame(tk_root)
    try:
        with patch(
            "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
            return_value=ReadPayloadResult(payload=payload, status="ok"),
        ):
            tab._show_image(image_path)

        tab.prompt_mode_var.set("modify")
        tab.prompt_text.delete("1.0", tk.END)
        tab.prompt_text.insert("1.0", "cinematic lighting")
        tab._refresh_prompt_diff()
        assert "After +: resolved portrait prompt, cinematic lighting" in tab.diff_after_label.cget("text")
    finally:
        tab.destroy()

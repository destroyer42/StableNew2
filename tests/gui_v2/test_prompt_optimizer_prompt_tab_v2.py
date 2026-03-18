from __future__ import annotations

import tkinter as tk

from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame


def test_prompt_tab_exposes_prompt_optimizer_config(tk_root: tk.Tk) -> None:
    frame = PromptTabFrame(tk_root)
    frame.apply_prompt_optimizer_config({"enabled": False, "dedupe_enabled": False})

    config = frame.get_prompt_optimizer_config()

    assert config["enabled"] is False
    assert config["dedupe_enabled"] is False

    frame.destroy()


def test_prompt_tab_preview_shows_optimized_prompts(tk_root: tk.Tk) -> None:
    frame = PromptTabFrame(tk_root)
    frame.workspace_state.set_slot_text(0, "masterpiece, beautiful woman, cinematic lighting")
    frame.workspace_state.set_slot_negative(0, "watermark, blurry, bad anatomy")
    frame._refresh_editor()
    frame._refresh_metadata()

    text = frame.meta_text.get("1.0", "end")

    assert "Optimized Positive:" in text
    assert "beautiful woman, cinematic lighting, masterpiece" in text
    assert "bad anatomy, blurry, watermark" in text

    frame.destroy()

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

    assert "EDITOR ILLUSTRATION" in text
    assert "After (Positive illustration):" in text
    assert "beautiful woman, cinematic lighting, masterpiece" in text
    assert "bad anatomy, blurry, watermark" in text

    frame.destroy()


def test_inspection_is_read_only_but_setting_change_invalidates_preview(tk_root):
    from src.gui.app_state_v2 import AppStateV2
    from tests.helpers.job_helpers import make_test_njr

    state = AppStateV2()
    frame = PromptTabFrame(tk_root, app_state=state)
    frame.workspace_state.set_slot_text(0, "masterpiece, beautiful woman")
    before_dirty = frame.workspace_state.dirty
    before = frame.workspace_state.get_current_prompt_text()
    [job] = [make_test_njr(config={"prompt_optimizer": {"enabled": True}})]
    state.set_preview_jobs([job])
    frame._optimizer_diagnostics_var.set(True)
    frame._build_prompt_optimizer_preview(before, "")
    assert state.preview_jobs == [job]
    assert frame.workspace_state.dirty is before_dirty
    assert frame.workspace_state.get_current_prompt_text() == before
    frame._prompt_optimizer_vars["enabled"].set(False)
    frame._on_prompt_optimizer_config_changed()
    assert state.preview_jobs == []
    assert job.config["prompt_optimizer"]["enabled"] is True
    frame.destroy()


def test_hidden_settings_survive_and_inert_controls_are_absent(tk_root):
    frame = PromptTabFrame(tk_root)
    settings = {
        "allow_subject_anchor_boost": True,
        "subject_anchor_boost_min_chunk_count": 11,
        "opt_out_pipeline_names": ["img2img"],
        "warn_on_large_chunk_count": False,
        "future_key": {"value": 1},
    }
    frame.apply_prompt_optimizer_config(settings)
    frame._prompt_optimizer_vars["enabled"].set(False)
    captured = frame.get_prompt_optimizer_config()
    for key, value in settings.items():
        assert captured[key] == value
    assert not any(
        "Anchor" in str(widget.cget("text"))
        for widget in frame._prompt_optimizer_widgets
        if "text" in widget.keys()
    )
    frame.destroy()

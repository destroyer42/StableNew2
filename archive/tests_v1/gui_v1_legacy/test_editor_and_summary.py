from src.gui.advanced_prompt_editor import AdvancedPromptEditor


def test_editor_reloads_pack_when_already_open(tmp_path, tk_root):
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    pack_a = packs_dir / "heroes.txt"
    pack_b = packs_dir / "villains.txt"
    pack_a.write_text("hero prompt line", encoding="utf-8")
    pack_b.write_text("villain prompt line", encoding="utf-8")

    editor = AdvancedPromptEditor(tk_root, config_manager=object())

    editor.open_editor(pack_a)
    first_content = editor.prompts_text.get("1.0", "end-1c")
    assert "hero prompt line" in first_content

    editor.open_editor(pack_b)  # Reuse existing window, should reload content
    second_content = editor.prompts_text.get("1.0", "end-1c")

    assert editor.pack_name_var.get() == "villains"
    assert "villain prompt line" in second_content
    assert editor.current_pack_path == pack_b

    if editor.window and editor.window.winfo_exists():
        editor.window.destroy()


def test_live_config_summaries_reflect_current_values(minimal_gui_app):
    app = minimal_gui_app

    # Access variables through config panel (new architecture)
    app.config_panel.txt2img_vars["steps"].set(36)
    app.config_panel.txt2img_vars["sampler_name"].set("Heun")
    app.config_panel.txt2img_vars["cfg_scale"].set(8.5)
    app.config_panel.txt2img_vars["width"].set(832)
    app.config_panel.txt2img_vars["height"].set(1152)
    app._update_live_config_summary()

    summary_txt2img = app.txt2img_summary_var.get()
    assert "steps 36" in summary_txt2img
    assert "sampler Heun" in summary_txt2img
    assert "832x1152" in summary_txt2img

    app.config_panel.upscale_vars["upscale_mode"].set("img2img")
    app.config_panel.upscale_vars["steps"].set(12)
    app.config_panel.upscale_vars["denoising_strength"].set(0.55)
    app.config_panel.upscale_vars["sampler_name"].set("DPM++ 2M")
    app.config_panel.upscale_vars["upscaling_resize"].set(1.5)
    app._update_live_config_summary()

    summary_upscale = app.upscale_summary_var.get()
    assert "Mode: img2img" in summary_upscale
    assert "steps 12" in summary_upscale
    assert "denoise 0.55" in summary_upscale

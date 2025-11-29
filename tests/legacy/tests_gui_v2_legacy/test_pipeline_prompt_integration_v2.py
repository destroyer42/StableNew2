import tkinter as tk

import pytest

from src.gui.pipeline_panel_v2 import PipelinePanelV2


@pytest.mark.usefixtures("tk_root")
def test_opening_editor_prefills_from_pipeline_panel(tk_root: tk.Tk):
    root = tk_root
    panel = PipelinePanelV2(root)
    panel.prompt_text.insert("1.0", "panel prompt")

    panel.open_editor_button.invoke()
    root.update_idletasks()

    editor = panel._editor  # type: ignore[attr-defined]
    assert editor.prompt_text.get("1.0", tk.END).strip() == "panel prompt"

    if panel._editor_window.winfo_exists():  # type: ignore[attr-defined]
        panel._editor_window.destroy()


@pytest.mark.usefixtures("tk_root")
def test_applying_in_editor_updates_pipeline_panel_prompt(tk_root: tk.Tk):
    root = tk_root
    panel = PipelinePanelV2(root)
    panel.prompt_text.insert("1.0", "initial prompt")

    panel.open_editor_button.invoke()
    root.update_idletasks()

    editor = panel._editor  # type: ignore[attr-defined]
    editor.prompt_text.delete("1.0", tk.END)
    editor.prompt_text.insert("1.0", "edited from editor")

    editor.apply_button.invoke()
    assert panel.prompt_text.get("1.0", tk.END).strip() == "edited from editor"

    if panel._editor_window.winfo_exists():  # type: ignore[attr-defined]
        panel._editor_window.destroy()

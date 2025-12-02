import tkinter as tk

import pytest

from src.gui.advanced_prompt_editor import AdvancedPromptEditorV2


@pytest.mark.usefixtures("tk_root")
def test_editor_applies_prompt_back_to_callback(tk_root: tk.Tk):
    root = tk_root
    applied = []

    def on_apply(prompt_text, negative_prompt):
        applied.append((prompt_text, negative_prompt))

    editor = AdvancedPromptEditorV2(root, initial_prompt="start", on_apply=on_apply)
    editor.prompt_text.delete("1.0", tk.END)
    editor.prompt_text.insert("1.0", "updated prompt")

    editor.apply_button.invoke()

    assert applied == [("updated prompt", None)]


@pytest.mark.usefixtures("tk_root")
def test_editor_cancel_does_not_apply_changes(tk_root: tk.Tk):
    root = tk_root
    applied = []

    editor = AdvancedPromptEditorV2(root, initial_prompt="start", on_apply=lambda prompt, neg: applied.append((prompt, neg)))
    editor.prompt_text.insert("end", " (edited)")

    editor.cancel_button.invoke()

    assert applied == []

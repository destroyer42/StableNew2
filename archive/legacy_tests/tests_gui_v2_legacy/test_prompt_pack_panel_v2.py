import tkinter as tk
from pathlib import Path

import pytest

from src.gui.prompt_pack_adapter_v2 import PromptPackSummary
from src.gui.prompt_pack_panel_v2 import PromptPackPanelV2


@pytest.mark.usefixtures("tk_root")
def test_prompt_pack_panel_calls_apply_callback(tk_root: tk.Tk):
    packs = [
        PromptPackSummary(name="Pack One", path=Path("/tmp/one.txt"), description="first", prompt_count=2),
        PromptPackSummary(name="Pack Two", path=Path("/tmp/two.txt"), description="second", prompt_count=3),
    ]
    applied: list[str] = []

    panel = PromptPackPanelV2(tk_root, packs=packs, on_apply=lambda summary: applied.append(summary.name))

    panel.listbox.select_set(1)
    panel.listbox.event_generate("<<ListboxSelect>>")
    panel.apply_button.invoke()

    assert applied == ["Pack Two"]


@pytest.mark.usefixtures("tk_root")
def test_prompt_pack_panel_shows_metadata(tk_root: tk.Tk):
    packs = [PromptPackSummary(name="Pack One", path=Path("/tmp/one.txt"), description="first", prompt_count=2)]

    panel = PromptPackPanelV2(tk_root, packs=packs)
    panel.listbox.select_set(0)
    panel.listbox.event_generate("<<ListboxSelect>>")

    assert "first" in panel.description_var.get()
    assert "2 prompt" in panel.description_var.get()

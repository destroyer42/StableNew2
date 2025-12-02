import tkinter as tk
from pathlib import Path

import pytest

from src.gui.pipeline_panel_v2 import PipelinePanelV2
from src.gui.prompt_pack_adapter_v2 import PromptPackSummary
from src.gui.sidebar_panel_v2 import SidebarPanelV2


class _FakeAdapter:
    def __init__(self) -> None:
        self.summary = PromptPackSummary(
            name="Pack One",
            path=Path("/tmp/one.txt"),
            description="demo",
            prompt_count=1,
        )

    def load_summaries(self):
        return [self.summary]

    def get_base_prompt(self, summary):
        assert summary == self.summary
        return "pack base prompt"


@pytest.mark.usefixtures("tk_root")
def test_applying_pack_updates_pipeline_prompt(tk_root: tk.Tk):
    pipeline_panel = PipelinePanelV2(tk_root)
    adapter = _FakeAdapter()

    sidebar = SidebarPanelV2(
        tk_root,
        prompt_pack_adapter=adapter,
        on_apply_pack=lambda prompt_text, _summary=None: pipeline_panel.set_prompt(prompt_text),
    )

    sidebar.prompt_pack_panel.listbox.select_set(0)
    sidebar.prompt_pack_panel.listbox.event_generate("<<ListboxSelect>>")
    sidebar.prompt_pack_panel.apply_button.invoke()

    assert pipeline_panel.get_prompt() == "pack base prompt"

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from typing import Iterable, List

import pytest

from src.gui.sidebar_panel_v2 import PromptPackSummary, SidebarPanelV2


class DummyPromptPackAdapter:
    def __init__(self, summaries: Iterable[PromptPackSummary]):
        self._summaries = list(summaries)

    def load_summaries(self) -> list[PromptPackSummary]:
        return list(self._summaries)


def _build_panel(root: tk.Tk, summaries: Iterable[PromptPackSummary]) -> SidebarPanelV2:
    adapter = DummyPromptPackAdapter(summaries)
    panel = SidebarPanelV2(root, prompt_pack_adapter=adapter)
    names = [summary.name for summary in summaries]
    panel.set_pack_names(names)
    panel._prompt_summaries = list(summaries)
    panel._current_pack_names = names
    return panel


@pytest.mark.gui
def test_single_selection_preview_shows_full_block(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk not available: {exc}")
    root.withdraw()
    try:
        pack_path = tmp_path / "pack_alpha.txt"
        pack_path.write_text("Positive prompt line\n\nNegative prompt")
        summary = PromptPackSummary(name="alpha", description="desc", prompt_count=1, path=pack_path)
        panel = _build_panel(root, [summary])

        panel.pack_listbox.selection_clear(0, "end")
        panel.pack_listbox.selection_set(0)
        panel._on_pack_selection_changed()
        panel._toggle_pack_preview()

        assert panel._preview_visible is True
        text = panel.pack_preview_text.get("1.0", "end")
        assert "Pack: alpha" in text
        assert "Positive prompt line" in text
    finally:
        root.destroy()


@pytest.mark.gui
def test_multi_selection_hides_preview(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk not available: {exc}")
    root.withdraw()
    try:
        summary = PromptPackSummary(name="alpha", description="", prompt_count=1, path=Path(tmp_path / "alpha.txt"))
        summary_b = PromptPackSummary(name="beta", description="", prompt_count=1, path=Path(tmp_path / "beta.txt"))
        panel = _build_panel(root, [summary, summary_b])

        panel.pack_listbox.selection_set(0)
        panel._on_pack_selection_changed()
        panel._toggle_pack_preview()
        assert panel._preview_visible is True

        panel.pack_listbox.selection_clear(0, "end")
        panel.pack_listbox.selection_set(0, 1)
        panel._on_pack_selection_changed()

        assert str(panel.preview_toggle_button.cget("state")) == "disabled"
        assert panel._preview_visible is False
    finally:
        root.destroy()


@pytest.mark.gui
def test_preview_selection_changes_only_regenerate_when_pack_changes(tmp_path):
    class CountingPanel(SidebarPanelV2):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.describe_calls = 0

        def _describe_first_prompt(self, summary: PromptPackSummary) -> str:
            self.describe_calls += 1
            return f"Pack: {summary.name}\nPrompts: {summary.prompt_count}\n"

    summaries = [
        PromptPackSummary(name="alpha", description="", prompt_count=1, path=Path(tmp_path / "alpha.txt")),
        PromptPackSummary(name="beta", description="", prompt_count=1, path=Path(tmp_path / "beta.txt")),
    ]
    adapter = DummyPromptPackAdapter(summaries)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk not available: {exc}")
    root.withdraw()
    try:
        panel = CountingPanel(root, prompt_pack_adapter=adapter)
        panel.set_pack_names([s.name for s in summaries])
        panel._prompt_summaries = summaries
        panel._current_pack_names = [s.name for s in summaries]

        panel.pack_listbox.selection_clear(0, "end")
        panel.pack_listbox.selection_set(0)
        panel._on_pack_selection_changed()
        panel._toggle_pack_preview()

        assert panel.describe_calls == 1

        panel.pack_listbox.selection_clear(0, "end")
        panel.pack_listbox.selection_set(1)
        panel._on_pack_selection_changed()
        assert panel.describe_calls == 2
    finally:
        root.destroy()


@pytest.mark.gui
def test_preview_truncation_keeps_text_bounded(tmp_path):
    class LargePreviewPanel(SidebarPanelV2):
        def _describe_first_prompt(self, summary: PromptPackSummary) -> str:
            raw = "A" * (self._MAX_PREVIEW_CHARS + 1000)
            return self._limit_preview_text(raw)

    summary = PromptPackSummary(name="alpha", description="", prompt_count=1, path=Path(tmp_path / "alpha.txt"))
    adapter = DummyPromptPackAdapter([summary])
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk not available: {exc}")
    root.withdraw()
    try:
        panel = LargePreviewPanel(root, prompt_pack_adapter=adapter)
        panel._prompt_summaries = [summary]
        panel._current_pack_names = [summary.name]
        panel._update_preview_text(summary)
        text = panel.pack_preview_text.get("1.0", "end")
        assert "[Preview truncated]" in text
        assert len(text) <= panel._MAX_PREVIEW_CHARS + 50
    finally:
        root.destroy()

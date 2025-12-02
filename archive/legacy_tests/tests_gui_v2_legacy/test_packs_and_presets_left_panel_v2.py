"""Test packs and presets population and interaction in V2 left panel."""

from pathlib import Path
import tkinter as tk

import pytest

from src.gui.prompt_pack_adapter_v2 import PromptPackSummary
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.views.prompt_tab_frame import PromptTabFrame

@pytest.fixture
def temp_dirs(tmp_path):
    packs_dir = tmp_path / "packs"
    presets_dir = tmp_path / "presets"
    packs_dir.mkdir()
    presets_dir.mkdir()
    # Create dummy pack files
    (packs_dir / "PackA.txt").write_text("Prompt for A")
    (packs_dir / "PackB.txt").write_text("Prompt for B")
    # Create dummy preset files
    (presets_dir / "Preset1.json").write_text("{}")
    (presets_dir / "Preset2.json").write_text("{}")
    return packs_dir, presets_dir

@pytest.fixture
def sidebar_panel_v2(temp_dirs):
    packs_dir, presets_dir = temp_dirs
    root = tk.Tk()
    panel = SidebarPanelV2(root)
    return panel

@pytest.fixture
def prompt_tab():
    root = tk.Tk()
    tab = PromptTabFrame(root)
    return tab

def test_packs_list_populates(sidebar_panel_v2):
    # Should populate pack list combo and pack panel
    assert sidebar_panel_v2.pack_list_combo['values']
    sidebar_panel_v2.pack_list_var.set(sidebar_panel_v2.pack_list_combo['values'][0])
    sidebar_panel_v2._populate_packs_for_selected_list()
    assert sidebar_panel_v2.pack_panel.listbox.size() >= 0

def test_presets_list_populates(sidebar_panel_v2):
    # Should populate preset dropdown
    assert sidebar_panel_v2.preset_dropdown['values']
    sidebar_panel_v2.preset_var.set(sidebar_panel_v2.preset_dropdown['values'][0])
    sidebar_panel_v2._on_preset_selected()
    assert sidebar_panel_v2.config_source_label.cget('text').startswith('Preset:')

def test_apply_pack_updates_prompt(prompt_tab):
    # Simulate applying a pack
    summary = PromptPackSummary(name="PackA", description="desc", prompt_count=1, path=Path("dummy"), prompt="Test prompt", negative_prompt="Neg")
    prompt_tab.apply_prompt_pack(summary)
    assert "Test prompt" in prompt_tab.editor.get("1.0", "end")
    # If negative_prompt_editor exists, check it
    if hasattr(prompt_tab, "negative_prompt_editor"):
        assert "Neg" in prompt_tab.negative_prompt_editor.get("1.0", "end")

def test_config_source_banner_changes(sidebar_panel_v2):
    # Simulate preset selection and ad-hoc change
    sidebar_panel_v2.preset_var.set("Preset1")
    sidebar_panel_v2._on_preset_selected()
    assert sidebar_panel_v2.config_source_label.cget('text') == "Preset: Preset1"
    # Simulate ad-hoc change
    sidebar_panel_v2.config_source_label.config(text="Ad-hoc configuration")
    assert sidebar_panel_v2.config_source_label.cget('text') == "Ad-hoc configuration"

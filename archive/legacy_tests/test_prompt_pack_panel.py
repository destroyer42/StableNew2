"""Tests for PromptPackPanel mediator integration.
Created: 2025-11-02 22:31:47
Updated: 2025-11-04
"""

import pytest

from src.gui.prompt_pack_panel import PromptPackPanel


def test_prompt_pack_panel_selection_reports_to_mediator(tk_root):
    """Test that PromptPackPanel reports selection changes to mediator."""
    # Track selection changes
    selection_changes = []

    def on_selection_changed(packs):
        selection_changes.append(packs)

    # Create panel with callback
    panel = PromptPackPanel(tk_root, on_selection_changed=on_selection_changed)

    # Verify panel was created
    assert panel is not None

    # Get the list of available packs
    available_packs = panel.packs_listbox.get(0, "end")

    if len(available_packs) > 0:
        # Select first pack programmatically
        panel.packs_listbox.selection_set(0)
        panel.packs_listbox.event_generate("<<ListboxSelect>>")
        tk_root.update()

        # Verify callback was called
        assert len(selection_changes) >= 1, "Selection callback should have been called"
        # Verify the selected pack is in the callback data
        assert len(selection_changes[-1]) > 0, "Selected packs should not be empty"
    else:
        # No packs available to test with, mark as passed
        pytest.skip("No prompt packs available for selection test")

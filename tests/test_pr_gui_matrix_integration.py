"""
Test PR-GUI-MATRIX-INTEGRATION — Matrix Slot Autocomplete, Highlighting, and Validation

Tests the four matrix integration enhancements:
1. Autocomplete when typing [[
2. Visual highlighting of [[tokens]]
3. Quick insert buttons
4. Validation warnings for undefined slots
"""

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from src.gui.models.prompt_pack_model import MatrixConfig, MatrixSlot
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame


@pytest.fixture
def root():
    """Create Tk root for GUI tests."""
    root = tk.Tk()
    yield root
    root.destroy()


@pytest.fixture
def prompt_frame(root):
    """Create PromptTabFrame instance."""
    frame = PromptTabFrame(root)
    frame.pack()
    root.update()
    return frame


class TestMatrixAutocomplete:
    """Test autocomplete for [[slot]] notation."""
    
    def test_autocomplete_triggers_on_double_bracket(self, prompt_frame):
        """Typing [[ should show autocomplete dropdown."""
        # Setup matrix slots
        matrix_config = MatrixConfig(
            enabled=True,
            slots=[
                MatrixSlot(name="occupation", values=["warrior", "mage"]),
                MatrixSlot(name="location", values=["castle", "forest"]),
            ]
        )
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        
        # Simulate typing [[
        prompt_frame.editor.insert("1.0", "a [[")
        prompt_frame.editor.mark_set("insert", "1.3")
        
        # Trigger key release
        event = MagicMock()
        event.keysym = "bracketleft"
        prompt_frame._on_positive_key_release(event)
        
        # Update to ensure widget is mapped
        prompt_frame.update()
        
        # Should create autocomplete list
        assert prompt_frame._autocomplete_list is not None
        assert prompt_frame._autocomplete_list.winfo_viewable()
        
        # Should show both slots
        assert prompt_frame._autocomplete_list.size() == 2
        assert prompt_frame._autocomplete_list.get(0) == "occupation"
        assert prompt_frame._autocomplete_list.get(1) == "location"
    
    def test_autocomplete_inserts_slot_name(self, prompt_frame):
        """Selecting from autocomplete should insert slot name and ]]."""
        # Setup matrix
        matrix_config = MatrixConfig(
            enabled=True,
            slots=[MatrixSlot(name="character", values=["hero", "villain"])]
        )
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        
        # Show autocomplete
        prompt_frame.editor.insert("1.0", "a [[")
        prompt_frame.editor.mark_set("insert", "1.3")
        prompt_frame._show_autocomplete(prompt_frame.editor)
        
        # Select first item
        prompt_frame._autocomplete_list.selection_set(0)
        prompt_frame._on_autocomplete_select(prompt_frame.editor)
        
        # Should insert name and closing brackets
        text = prompt_frame.editor.get("1.0", "end").strip()
        assert text == "a [[character]]"
    
    def test_autocomplete_works_in_negative_editor(self, prompt_frame):
        """Autocomplete should also work in negative prompt editor."""
        matrix_config = MatrixConfig(
            enabled=True,
            slots=[MatrixSlot(name="unwanted", values=["blurry", "ugly"])]
        )
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        
        # Type in negative editor
        prompt_frame.negative_editor.insert("1.0", "[[")
        prompt_frame.negative_editor.mark_set("insert", "1.2")
        
        event = MagicMock()
        event.keysym = "bracketleft"
        prompt_frame._on_negative_key_release(event)
        
        # Update to ensure widget is mapped
        prompt_frame.update()
        
        assert prompt_frame._autocomplete_list is not None
        assert prompt_frame._autocomplete_list.winfo_viewable()


class TestMatrixHighlighting:
    """Test visual highlighting of [[tokens]]."""
    
    def test_tokens_get_highlighted(self, prompt_frame):
        """[[tokens]] should have background color applied."""
        # Insert text with tokens
        prompt_frame.editor.insert("1.0", "a [[hero]] standing near [[building]]")
        
        # Apply highlighting
        prompt_frame._highlight_matrix_tokens()
        
        # Check tags applied
        tags_at_hero = prompt_frame.editor.tag_names("1.2")  # Position of first [
        assert "matrix_token" in tags_at_hero
        
        tags_at_building = prompt_frame.editor.tag_names("1.25")  # Position of second [ (corrected from 1.22)
        assert "matrix_token" in tags_at_building
    
    def test_highlighting_updates_after_edit(self, prompt_frame):
        """Highlighting should update when content changes."""
        prompt_frame.editor.insert("1.0", "a [[hero]]")
        prompt_frame._highlight_matrix_tokens()
        
        # Add another token
        prompt_frame.editor.insert("end", " near [[location]]")
        prompt_frame._highlight_matrix_tokens()
        
        # Both should be highlighted
        text = prompt_frame.editor.get("1.0", "end").strip()
        assert text == "a [[hero]] near [[location]]"
        
        # Check second token highlighted
        tags = prompt_frame.editor.tag_names("1.16")
        assert "matrix_token" in tags
    
    def test_highlighting_in_negative_editor(self, prompt_frame):
        """Negative editor should also highlight tokens."""
        prompt_frame.negative_editor.insert("1.0", "no [[bad_quality]]")
        prompt_frame._highlight_matrix_tokens()
        
        tags = prompt_frame.negative_editor.tag_names("1.3")
        assert "matrix_token" in tags


class TestQuickInsertButtons:
    """Test quick insert buttons for matrix slots."""
    
    def test_buttons_created_for_slots(self, prompt_frame):
        """Should create quick insert buttons for each slot."""
        matrix_config = MatrixConfig(
            enabled=True,
            slots=[
                MatrixSlot(name="char", values=["a", "b"]),
                MatrixSlot(name="place", values=["x", "y"]),
            ]
        )
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        
        prompt_frame._update_quick_insert_buttons()
        
        # Should have buttons in positive frame
        pos_buttons = prompt_frame.positive_quick_insert_frame.winfo_children()
        assert len(pos_buttons) == 2
        assert pos_buttons[0].cget("text") == "[[char]]"
        assert pos_buttons[1].cget("text") == "[[place]]"
        
        # Should have buttons in negative frame
        neg_buttons = prompt_frame.negative_quick_insert_frame.winfo_children()
        assert len(neg_buttons) == 2
    
    def test_quick_insert_button_inserts_token(self, prompt_frame):
        """Clicking quick insert button should add [[token]]."""
        matrix_config = MatrixConfig(
            enabled=True,
            slots=[MatrixSlot(name="test_slot", values=["val1"])]
        )
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        prompt_frame._update_quick_insert_buttons()
        
        # Click button
        prompt_frame._quick_insert_slot(prompt_frame.editor, "test_slot")
        
        text = prompt_frame.editor.get("1.0", "end").strip()
        assert text == "[[test_slot]]"
    
    def test_buttons_limited_to_five(self, prompt_frame):
        """Should only show first 5 slots to save space."""
        matrix_config = MatrixConfig(
            enabled=True,
            slots=[
                MatrixSlot(name=f"slot{i}", values=["x"])
                for i in range(10)
            ]
        )
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        prompt_frame._update_quick_insert_buttons()
        
        pos_buttons = prompt_frame.positive_quick_insert_frame.winfo_children()
        assert len(pos_buttons) == 5


class TestSlotValidation:
    """Test validation warnings for undefined slots."""
    
    def test_detects_undefined_slots(self, prompt_frame):
        """Should detect when [[token]] is used but not defined."""
        # No slots defined
        matrix_config = MatrixConfig(enabled=True, slots=[])
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        
        # Use undefined slot
        prompt_frame.editor.insert("1.0", "a [[undefined_slot]]")
        prompt_frame._validate_matrix_slots()
        
        assert "undefined_slot" in prompt_frame._undefined_slots
    
    def test_no_warning_for_defined_slots(self, prompt_frame):
        """Should not warn when slots are properly defined."""
        matrix_config = MatrixConfig(
            enabled=True,
            slots=[MatrixSlot(name="valid_slot", values=["a", "b"])]
        )
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        
        prompt_frame.editor.insert("1.0", "a [[valid_slot]]")
        prompt_frame._validate_matrix_slots()
        
        assert len(prompt_frame._undefined_slots) == 0
    
    def test_validates_both_editors(self, prompt_frame):
        """Should check both positive and negative editors."""
        matrix_config = MatrixConfig(enabled=True, slots=[])
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        
        prompt_frame.editor.insert("1.0", "[[pos_undefined]]")
        prompt_frame.negative_editor.insert("1.0", "[[neg_undefined]]")
        
        prompt_frame._validate_matrix_slots()
        
        assert "pos_undefined" in prompt_frame._undefined_slots
        assert "neg_undefined" in prompt_frame._undefined_slots
    
    def test_validation_warning_displayed(self, prompt_frame):
        """Should show warning in pack name label."""
        matrix_config = MatrixConfig(enabled=True, slots=[])
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        
        prompt_frame.editor.insert("1.0", "[[missing]]")
        prompt_frame._validate_matrix_slots()
        prompt_frame._show_validation_warning()
        
        label_text = prompt_frame.pack_name_label.cget("text")
        assert "⚠️" in label_text
        assert "missing" in label_text


class TestEndToEndWorkflow:
    """Test complete matrix integration workflow."""
    
    def test_full_workflow(self, prompt_frame):
        """Test autocomplete → insert → highlight → validate."""
        # 1. Define matrix slots
        matrix_config = MatrixConfig(
            enabled=True,
            slots=[
                MatrixSlot(name="hero", values=["warrior", "mage"]),
                MatrixSlot(name="place", values=["castle", "forest"]),
            ]
        )
        prompt_frame.workspace_state.set_matrix_config(matrix_config)
        
        # 2. Type [[ and select from autocomplete
        prompt_frame.editor.insert("1.0", "a [[")
        prompt_frame.editor.mark_set("insert", "1.3")
        prompt_frame._show_autocomplete(prompt_frame.editor)
        prompt_frame._autocomplete_list.selection_set(0)
        prompt_frame._on_autocomplete_select(prompt_frame.editor)
        
        # 3. Use quick insert for second slot
        prompt_frame.editor.insert("end", " in ")
        prompt_frame._quick_insert_slot(prompt_frame.editor, "place")
        
        # 4. Apply highlighting
        prompt_frame._highlight_matrix_tokens()
        
        # 5. Validate (should be OK)
        prompt_frame._validate_matrix_slots()
        
        # Verify final state
        text = prompt_frame.editor.get("1.0", "end").strip()
        assert "[[hero]]" in text
        assert "[[place]]" in text
        assert len(prompt_frame._undefined_slots) == 0
        
        # Check highlighting applied
        tags = prompt_frame.editor.tag_names("1.2")
        assert "matrix_token" in tags


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

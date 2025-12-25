"""
PR-PREVIEW-001: Thumbnail Preview Default Off + Config Persistence

Tests that:
1. Preview panel checkbox defaults to False
2. Checkbox state persists across operations (save/restore)
3. State doesn't reset when adding jobs to preview or queue
4. User checkbox preference is authoritative (not overridden by pack config)
"""

import pytest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
import tkinter as tk

from src.gui.preview_panel_v2 import PreviewPanelV2


@pytest.fixture
def temp_state_file(tmp_path):
    """Create temporary state file for testing persistence."""
    state_file = tmp_path / "preview_state.json"
    yield state_file
    if state_file.exists():
        state_file.unlink()


@pytest.fixture
def preview_panel(temp_state_file):
    """Create preview panel with mocked state file."""
    with patch("src.gui.preview_panel_v2.PREVIEW_STATE_PATH", temp_state_file):
        try:
            root = tk.Tk()
            panel = PreviewPanelV2(root, app_state=None)
            yield panel
            root.destroy()
        except tk.TclError:
            # Skip if Tk environment not available
            pytest.skip("Tk environment not available")


def test_default_preview_off(preview_panel):
    """Test that preview checkbox defaults to False."""
    assert preview_panel._show_preview_var.get() is False, \
        "Preview checkbox should default to False (PR-PREVIEW-001)"


def test_state_persistence_save_restore(preview_panel, temp_state_file):
    """Test that checkbox state persists across save/restore."""
    # Enable preview
    preview_panel._show_preview_var.set(True)
    preview_panel.save_state()
    
    # Verify state file created
    assert temp_state_file.exists(), "State file should be created"
    state = json.loads(temp_state_file.read_text())
    assert state["show_preview"] is True
    assert state["schema_version"] == "2.6"
    
    # Create new panel and restore state
    preview_panel._show_preview_var.set(False)  # Reset to False
    preview_panel.restore_state()
    
    # Verify restored
    assert preview_panel._show_preview_var.get() is True, \
        "State should be restored from disk"


def test_state_persists_on_checkbox_change(preview_panel, temp_state_file):
    """Test that save_state is called when checkbox changes."""
    with patch.object(preview_panel, "save_state") as mock_save:
        preview_panel._on_preview_checkbox_changed()
        mock_save.assert_called_once()


def test_no_reset_on_clear(preview_panel):
    """Test that clearing preview doesn't reset checkbox state."""
    # Set checkbox to False
    preview_panel._show_preview_var.set(False)
    
    # Create mock job_draft with empty packs to trigger "clear" path
    mock_job_draft = SimpleNamespace(packs=[])
    
    # Clear preview
    preview_panel.update_from_job_draft(job_draft=mock_job_draft)
    
    # Verify checkbox state unchanged
    assert preview_panel._show_preview_var.get() is False, \
        "Checkbox state should not reset when clearing preview"
    assert preview_panel._current_show_preview is False, \
        "_current_show_preview should match checkbox state"


def test_no_reset_on_update_with_summary(preview_panel):
    """Test that update_with_summary doesn't reset checkbox state."""
    # Set checkbox to False
    preview_panel._show_preview_var.set(False)
    
    # Create mock summary
    mock_summary = SimpleNamespace(
        job_id="test_job_001",
        prompt_pack_name="test_pack",
        positive_prompt_preview="test prompt",
        negative_prompt_preview="",
        base_model="SDXL",
        steps=30,
        cfg_scale=7.0,
        sampler="DPM++ 2M",
        scheduler="Karras",
        width=1024,
        height=1024,
        batch_size=1,
        batch_count=1
    )
    
    # Update with summary
    preview_panel.update_with_summary(mock_summary)
    
    # Verify checkbox state unchanged
    assert preview_panel._show_preview_var.get() is False, \
        "Checkbox state should not reset when updating with summary"
    assert preview_panel._current_show_preview is False, \
        "_current_show_preview should match checkbox state"


def test_checkbox_state_authoritative(preview_panel):
    """Test that user checkbox is authoritative, not pack config."""
    # Set checkbox to False
    preview_panel._show_preview_var.set(False)
    
    # Create mock summary with show_preview=True in pack config
    # (this shouldn't override the user's checkbox)
    mock_summary = SimpleNamespace(
        job_id="test_job_002",
        pack_name="test_pack_with_preview",
        show_preview=True,  # Pack says "show preview"
        positive_preview="test",
        negative_preview="",
        label="SDXL"
    )
    
    # Create a mock job_draft with this summary
    mock_job_draft = SimpleNamespace(packs=[mock_summary])
    
    # Update from job draft (which internally calls update methods)
    preview_panel.update_from_job_draft(job_draft=mock_job_draft)
    
    # Verify checkbox state NOT overridden by pack config
    assert preview_panel._show_preview_var.get() is False, \
        "User checkbox should not be overridden by pack config (PR-PREVIEW-001)"


def test_state_file_schema_version(preview_panel, temp_state_file):
    """Test that state file includes schema version."""
    preview_panel._show_preview_var.set(True)
    preview_panel.save_state()
    
    state = json.loads(temp_state_file.read_text())
    assert "schema_version" in state
    assert state["schema_version"] == "2.6"


def test_restore_with_invalid_schema(preview_panel, temp_state_file):
    """Test that invalid schema version is ignored."""
    # Write state with old schema
    temp_state_file.write_text(json.dumps({
        "show_preview": True,
        "schema_version": "1.0"
    }))
    
    # Set checkbox to False
    preview_panel._show_preview_var.set(False)
    
    # Try to restore - should be ignored
    preview_panel.restore_state()
    
    # Verify state unchanged
    assert preview_panel._show_preview_var.get() is False, \
        "Invalid schema should be ignored"


def test_restore_with_missing_file(preview_panel, temp_state_file):
    """Test that missing state file doesn't cause errors."""
    # Ensure file doesn't exist
    if temp_state_file.exists():
        temp_state_file.unlink()
    
    # Set checkbox to True
    preview_panel._show_preview_var.set(True)
    
    # Try to restore - should do nothing
    preview_panel.restore_state()
    
    # Verify state unchanged
    assert preview_panel._show_preview_var.get() is True, \
        "State should remain unchanged when file missing"


def test_save_state_on_destroy(preview_panel, temp_state_file):
    """Test that state is saved when panel is destroyed."""
    # Set checkbox to True
    preview_panel._show_preview_var.set(True)
    
    # Destroy panel
    preview_panel.destroy()
    
    # Verify state saved
    assert temp_state_file.exists(), "State should be saved on destroy"
    state = json.loads(temp_state_file.read_text())
    assert state["show_preview"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

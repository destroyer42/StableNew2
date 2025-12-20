"""Integration tests for PromptWorkspaceState negative prompt support."""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.gui.prompt_workspace_state import PromptWorkspaceState


def test_get_set_negative_text():
    """Test getting and setting negative text."""
    ws = PromptWorkspaceState()
    ws.new_pack("Test", slot_count=3)

    ws.set_slot_negative(0, "ugly, blurry")
    assert ws.get_current_negative_text() == "ugly, blurry"
    assert ws.dirty


def test_negative_text_defaults_empty():
    """Test that negative text defaults to empty for new packs."""
    ws = PromptWorkspaceState()
    ws.new_pack("Test", slot_count=3)

    assert ws.get_current_negative_text() == ""


def test_negative_text_persists_across_slots():
    """Test that negative text is preserved when switching slots."""
    ws = PromptWorkspaceState()
    ws.new_pack("Test", slot_count=3)

    ws.set_slot_text(0, "wizard")
    ws.set_slot_negative(0, "neg1")

    ws.set_current_slot_index(1)
    ws.set_slot_text(1, "knight")
    ws.set_slot_negative(1, "neg2")

    ws.set_current_slot_index(0)
    assert ws.get_current_prompt_text() == "wizard"
    assert ws.get_current_negative_text() == "neg1"

    ws.set_current_slot_index(1)
    assert ws.get_current_prompt_text() == "knight"
    assert ws.get_current_negative_text() == "neg2"


def test_save_load_preserves_negative():
    """Test that save/load cycle preserves negative prompts."""
    ws = PromptWorkspaceState()
    ws.new_pack("Test")
    ws.set_slot_text(0, "positive text")
    ws.set_slot_negative(0, "negative text")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_roundtrip.json"
        ws.save_current_pack(path)

        ws2 = PromptWorkspaceState()
        ws2.load_pack(path)

        assert ws2.get_current_prompt_text() == "positive text"
        assert ws2.get_current_negative_text() == "negative text"


def test_set_slot_negative_marks_dirty():
    """Test that setting negative prompt marks pack as dirty."""
    ws = PromptWorkspaceState()
    ws.new_pack("Test")

    assert not ws.dirty

    ws.set_slot_negative(0, "ugly")
    assert ws.dirty


def test_empty_negative_allowed():
    """Test that empty negative prompt is valid."""
    ws = PromptWorkspaceState()
    ws.new_pack("Test")

    ws.set_slot_negative(0, "ugly")
    assert ws.get_current_negative_text() == "ugly"

    ws.set_slot_negative(0, "")
    assert ws.get_current_negative_text() == ""


def test_metadata_includes_negative_text():
    """Test that metadata detection includes negative prompt."""
    ws = PromptWorkspaceState()
    ws.new_pack("Test")

    # Add LoRA to negative prompt
    ws.set_slot_text(0, "masterpiece")
    ws.set_slot_negative(0, "<lora:test:0.5>, ugly")

    metadata = ws.get_current_prompt_metadata()
    # LoRA should be detected from negative prompt
    assert len(metadata.loras) > 0


def test_load_legacy_pack_negative_defaults():
    """Test that loading legacy pack without negative field works."""
    import json

    legacy_json = {"name": "Legacy", "slots": [{"index": 0, "text": "test"}]}

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "legacy.json"
        path.write_text(json.dumps(legacy_json), encoding="utf-8")

        ws = PromptWorkspaceState()
        ws.load_pack(path)

        assert ws.get_current_prompt_text() == "test"
        assert ws.get_current_negative_text() == ""


def test_multiple_slots_with_different_negatives():
    """Test that each slot can have its own negative prompt."""
    ws = PromptWorkspaceState()
    ws.new_pack("Test", slot_count=5)

    # Set different negatives for each slot
    for i in range(5):
        ws.set_current_slot_index(i)
        ws.set_slot_text(i, f"prompt_{i}")
        ws.set_slot_negative(i, f"neg_{i}")

    # Verify each slot has correct negative
    for i in range(5):
        ws.set_current_slot_index(i)
        assert ws.get_current_negative_text() == f"neg_{i}"

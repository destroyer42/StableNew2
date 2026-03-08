"""Unit tests for PromptPackModel negative prompt field."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.gui.models.prompt_pack_model import PromptPackModel, PromptSlot


def test_prompt_slot_has_negative_field():
    """Test that PromptSlot has a negative field."""
    slot = PromptSlot(index=0, text="positive", negative="negative")
    assert slot.negative == "negative"


def test_prompt_slot_negative_defaults_empty():
    """Test that negative field defaults to empty string."""
    slot = PromptSlot(index=0, text="positive")
    assert slot.negative == ""


def test_new_pack_includes_negative():
    """Test that new packs initialize negative fields."""
    pack = PromptPackModel.new("Test", slot_count=3)
    assert len(pack.slots) == 3
    for slot in pack.slots:
        assert hasattr(slot, "negative")
        assert slot.negative == ""


def test_save_includes_negative():
    """Test that save includes negative field in JSON."""
    pack = PromptPackModel.new("Test", slot_count=1)
    pack.slots[0].text = "wizard"
    pack.slots[0].negative = "ugly"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_negative.json"
        pack.save_to_file(path)

        # Read JSON and verify
        with open(path) as f:
            data = json.load(f)
        
        assert data["slots"][0]["negative"] == "ugly"
        assert data["slots"][0]["text"] == "wizard"


def test_load_without_negative_field():
    """Test backward compatibility: load old JSON without negative field."""
    # Simulate old JSON format
    old_json = {"name": "Old", "slots": [{"index": 0, "text": "hello"}]}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "old_test.json"
        path.write_text(json.dumps(old_json), encoding="utf-8")
        
        pack = PromptPackModel.load_from_file(path)
        assert pack.slots[0].negative == ""
        assert pack.slots[0].text == "hello"


def test_load_with_negative_field():
    """Test loading pack with negative field."""
    pack = PromptPackModel.new("Test", slot_count=1)
    pack.slots[0].text = "positive"
    pack.slots[0].negative = "bad quality"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_with_neg.json"
        pack.save_to_file(path)
        
        pack2 = PromptPackModel.load_from_file(path)
        assert pack2.slots[0].negative == "bad quality"
        assert pack2.slots[0].text == "positive"


def test_roundtrip_save_load_negative():
    """Test that negative prompts survive save/load cycle."""
    pack = PromptPackModel.new("Roundtrip", slot_count=3)
    pack.slots[0].text = "wizard"
    pack.slots[0].negative = "ugly, blurry"
    pack.slots[1].text = "knight"
    pack.slots[1].negative = "low quality"
    pack.slots[2].text = "druid"
    pack.slots[2].negative = ""  # Empty is valid
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "roundtrip.json"
        pack.save_to_file(path)
        
        loaded = PromptPackModel.load_from_file(path)
        assert loaded.slots[0].negative == "ugly, blurry"
        assert loaded.slots[1].negative == "low quality"
        assert loaded.slots[2].negative == ""


def test_negative_field_preserves_special_characters():
    """Test that negative field handles special characters."""
    pack = PromptPackModel.new("Special", slot_count=1)
    pack.slots[0].negative = "ugly, <lora:bad:0.5>, \"quotes\", new\\nline"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "special.json"
        pack.save_to_file(path)
        
        loaded = PromptPackModel.load_from_file(path)
        assert loaded.slots[0].negative == "ugly, <lora:bad:0.5>, \"quotes\", new\\nline"


def test_empty_negative_saves_as_empty_string():
    """Test that empty negative saves as empty string, not null."""
    pack = PromptPackModel.new("Empty", slot_count=1)
    pack.slots[0].text = "test"
    pack.slots[0].negative = ""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "empty_neg.json"
        pack.save_to_file(path)

        with open(path) as f:
            data = json.load(f)
        
        # Should be empty string, not null/None
        assert data["slots"][0]["negative"] == ""
        assert "negative" in data["slots"][0]


def test_load_padded_slots_include_negative():
    """Test that padded slots have negative field initialized."""
    # Create pack with only 2 slots
    small_json = {
        "name": "Small",
        "slots": [
            {"index": 0, "text": "one", "negative": "neg1"},
            {"index": 1, "text": "two"}
        ]
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "small.json"
        path.write_text(json.dumps(small_json), encoding="utf-8")
        
        # Load with min_slots=10 (default)
        pack = PromptPackModel.load_from_file(path)
        assert len(pack.slots) == 10
        
        # First two slots from file
        assert pack.slots[0].negative == "neg1"
        assert pack.slots[1].negative == ""
        
        # Padded slots should have negative=""
        for i in range(2, 10):
            assert pack.slots[i].negative == ""

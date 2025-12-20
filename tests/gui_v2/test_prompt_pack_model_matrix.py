"""
Tests for PromptPackModel matrix configuration support.

Tests matrix data model extensions, serialization, backward compatibility,
and TXT export with [[tokens]] and neg: lines.
"""

import json
import pytest
from pathlib import Path
from src.gui.models.prompt_pack_model import (
    PromptPackModel,
    PromptSlot,
    MatrixSlot,
    MatrixConfig,
)


def test_matrix_config_default():
    """MatrixConfig should have sensible defaults."""
    config = MatrixConfig()
    assert config.enabled is False
    assert config.mode == "fanout"
    assert config.limit == 8
    assert config.slots == []


def test_matrix_slot_creation():
    """MatrixSlot should store name and values."""
    slot = MatrixSlot(name="job", values=["wizard", "knight", "druid"])
    assert slot.name == "job"
    assert len(slot.values) == 3
    assert "wizard" in slot.values


def test_matrix_config_get_slot_names():
    """get_slot_names() should return list of slot names."""
    config = MatrixConfig(
        enabled=True,
        slots=[
            MatrixSlot(name="job", values=["wizard", "knight"]),
            MatrixSlot(name="environment", values=["forest", "castle"]),
        ]
    )
    names = config.get_slot_names()
    assert names == ["job", "environment"]


def test_matrix_config_get_slot_dict():
    """get_slot_dict() should return dict format for PromptRandomizer."""
    config = MatrixConfig(
        enabled=True,
        slots=[
            MatrixSlot(name="job", values=["wizard", "knight"]),
            MatrixSlot(name="environment", values=["forest", "castle"]),
        ]
    )
    slot_dict = config.get_slot_dict()
    assert slot_dict == {
        "job": ["wizard", "knight"],
        "environment": ["forest", "castle"],
    }


def test_new_pack_has_default_matrix():
    """PromptPackModel.new() should include empty MatrixConfig."""
    pack = PromptPackModel.new("test_pack", slot_count=5)
    assert pack.name == "test_pack"
    assert len(pack.slots) == 5
    assert isinstance(pack.matrix, MatrixConfig)
    assert pack.matrix.enabled is False
    assert pack.matrix.slots == []


def test_save_includes_matrix_config(tmp_path):
    """save_to_file() should serialize matrix config to JSON."""
    pack = PromptPackModel.new("test_matrix", slot_count=2)
    pack.slots[0].text = "A [[job]] in [[environment]]"
    pack.slots[0].negative = "bad quality"
    
    pack.matrix = MatrixConfig(
        enabled=True,
        mode="fanout",
        limit=4,
        slots=[
            MatrixSlot(name="job", values=["wizard", "knight"]),
            MatrixSlot(name="environment", values=["forest", "castle"]),
        ]
    )
    
    json_path = tmp_path / "test_matrix.json"
    pack.save_to_file(json_path)
    
    # Read JSON directly
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    assert "matrix" in data
    assert data["matrix"]["enabled"] is True
    assert data["matrix"]["mode"] == "fanout"
    assert data["matrix"]["limit"] == 4
    assert len(data["matrix"]["slots"]) == 2
    assert data["matrix"]["slots"][0]["name"] == "job"
    assert data["matrix"]["slots"][0]["values"] == ["wizard", "knight"]


def test_load_with_matrix_config(tmp_path):
    """load_from_file() should deserialize matrix config."""
    json_data = {
        "name": "test_load_matrix",
        "slots": [
            {"index": 0, "text": "[[job]] prompt", "negative": "bad"},
            {"index": 1, "text": "another prompt", "negative": ""},
        ],
        "matrix": {
            "enabled": True,
            "mode": "fanout",
            "limit": 6,
            "slots": [
                {"name": "job", "values": ["wizard", "knight", "druid"]},
                {"name": "environment", "values": ["forest", "castle"]},
            ],
        },
    }
    
    json_path = tmp_path / "test_load_matrix.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f)
    
    pack = PromptPackModel.load_from_file(json_path)
    
    assert pack.name == "test_load_matrix"
    assert len(pack.slots) >= 2
    assert pack.slots[0].text == "[[job]] prompt"
    
    assert pack.matrix.enabled is True
    assert pack.matrix.mode == "fanout"
    assert pack.matrix.limit == 6
    assert len(pack.matrix.slots) == 2
    assert pack.matrix.slots[0].name == "job"
    assert pack.matrix.slots[0].values == ["wizard", "knight", "druid"]


def test_load_backward_compat_no_matrix_field(tmp_path):
    """load_from_file() should handle old JSON without matrix field."""
    json_data = {
        "name": "old_pack",
        "slots": [
            {"index": 0, "text": "old prompt", "negative": "old neg"},
        ],
        # NO matrix field
    }
    
    json_path = tmp_path / "old_pack.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f)
    
    pack = PromptPackModel.load_from_file(json_path)
    
    assert pack.name == "old_pack"
    assert len(pack.slots) >= 1
    assert isinstance(pack.matrix, MatrixConfig)
    assert pack.matrix.enabled is False
    assert pack.matrix.slots == []


def test_roundtrip_save_load_matrix(tmp_path):
    """Save and load should preserve matrix config exactly."""
    original = PromptPackModel.new("roundtrip_matrix", slot_count=3)
    original.slots[0].text = "[[job]] in [[environment]]"
    original.slots[0].negative = "bad quality, blurry"
    
    original.matrix = MatrixConfig(
        enabled=True,
        mode="fanout",
        limit=10,
        slots=[
            MatrixSlot(name="job", values=["mage", "fighter", "rogue"]),
            MatrixSlot(name="environment", values=["dungeon", "forest"]),
        ]
    )
    
    json_path = tmp_path / "roundtrip_matrix.json"
    original.save_to_file(json_path)
    
    loaded = PromptPackModel.load_from_file(json_path)
    
    assert loaded.matrix.enabled == original.matrix.enabled
    assert loaded.matrix.mode == original.matrix.mode
    assert loaded.matrix.limit == original.matrix.limit
    assert len(loaded.matrix.slots) == len(original.matrix.slots)
    assert loaded.matrix.slots[0].name == "job"
    assert loaded.matrix.slots[0].values == ["mage", "fighter", "rogue"]
    assert loaded.matrix.slots[1].name == "environment"


def test_export_txt_with_matrix_tokens(tmp_path):
    """_export_txt() should preserve [[tokens]] in output."""
    pack = PromptPackModel.new("txt_export_tokens", slot_count=2)
    pack.slots[0].text = "<lora:detail:0.5> [[job]] casting spell in [[environment]]"
    pack.slots[0].negative = "bad quality, distorted"
    pack.slots[1].text = "another [[job]] with sword"
    pack.slots[1].negative = ""
    
    pack.matrix = MatrixConfig(
        enabled=True,
        slots=[
            MatrixSlot(name="job", values=["wizard", "knight"]),
            MatrixSlot(name="environment", values=["forest", "castle"]),
        ]
    )
    
    txt_path = tmp_path / "txt_export_tokens.txt"
    pack._export_txt(txt_path)
    
    content = txt_path.read_text(encoding="utf-8")
    
    # Should contain [[tokens]]
    assert "[[job]]" in content
    assert "[[environment]]" in content
    
    # Should contain neg: lines
    assert "neg: bad quality, distorted" in content
    
    # Should contain LoRAs
    assert "<lora:detail:0.5>" in content
    
    # Should have blank line separators
    assert "\n\n" in content


def test_export_txt_multi_line_negative(tmp_path):
    """_export_txt() should handle multi-line negative prompts with neg: prefix."""
    pack = PromptPackModel.new("txt_multiline_neg", slot_count=1)
    pack.slots[0].text = "positive prompt"
    pack.slots[0].negative = "bad quality\nblurry\ndistorted"
    
    txt_path = tmp_path / "txt_multiline_neg.txt"
    pack._export_txt(txt_path)
    
    content = txt_path.read_text(encoding="utf-8")
    
    # Each negative line should have neg: prefix
    assert "neg: bad quality" in content
    assert "neg: blurry" in content
    assert "neg: distorted" in content


def test_export_txt_skips_empty_slots(tmp_path):
    """_export_txt() should skip slots with no text."""
    pack = PromptPackModel.new("txt_skip_empty", slot_count=10)
    pack.slots[0].text = "prompt 1"
    pack.slots[1].text = ""  # Empty
    pack.slots[2].text = "   "  # Whitespace only
    pack.slots[3].text = "prompt 3"
    
    txt_path = tmp_path / "txt_skip_empty.txt"
    pack._export_txt(txt_path)
    
    content = txt_path.read_text(encoding="utf-8")
    lines = [line for line in content.split("\n") if line.strip()]
    
    # Should only have 2 non-empty prompts
    assert len(lines) == 2
    assert "prompt 1" in content
    assert "prompt 3" in content


def test_auto_export_txt_in_packs_folder(tmp_path):
    """save_to_file() should auto-export TXT if saving to packs/ folder."""
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    
    pack = PromptPackModel.new("auto_export", slot_count=1)
    pack.slots[0].text = "test prompt with [[token]]"
    pack.slots[0].negative = "neg prompt"
    
    json_path = packs_dir / "auto_export.json"
    pack.save_to_file(json_path)
    
    # Check TXT was auto-created
    txt_path = packs_dir / "auto_export.txt"
    assert txt_path.exists()
    
    content = txt_path.read_text(encoding="utf-8")
    assert "test prompt with [[token]]" in content
    assert "neg: neg prompt" in content


def test_no_auto_export_txt_outside_packs(tmp_path):
    """save_to_file() should NOT auto-export TXT if not in packs/ folder."""
    pack = PromptPackModel.new("no_auto_export", slot_count=1)
    pack.slots[0].text = "test prompt"
    
    json_path = tmp_path / "no_auto_export.json"
    pack.save_to_file(json_path)
    
    # TXT should NOT be created
    txt_path = tmp_path / "no_auto_export.txt"
    assert not txt_path.exists()

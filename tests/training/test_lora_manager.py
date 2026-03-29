from __future__ import annotations

from pathlib import Path

import pytest

from src.training.lora_manager import LoRAManager


def test_lora_manager_registers_and_resolves_weight(tmp_path: Path) -> None:
    weights_dir = tmp_path / "weights"
    weights_dir.mkdir()
    weight_path = weights_dir / "ada.safetensors"
    weight_path.write_bytes(b"weights")
    manager = LoRAManager(base_dir=tmp_path / "manifest")

    entry = manager.register(character_name="Ada", weight_path=weight_path)

    assert entry["character_name"] == "Ada"
    assert entry["weight_path"] == str(weight_path.resolve())
    assert manager.resolve("Ada") == str(weight_path.resolve())
    assert manager.get("Ada")["manifest_path"] == str(manager.manifest_path)


def test_lora_manager_persists_trigger_phrase_and_resolves_multiple_actors(tmp_path: Path) -> None:
    weights_dir = tmp_path / "weights"
    weights_dir.mkdir()
    ada_weight = weights_dir / "ada.safetensors"
    bran_weight = weights_dir / "bran.safetensors"
    ada_weight.write_bytes(b"ada")
    bran_weight.write_bytes(b"bran")
    manager = LoRAManager(base_dir=tmp_path / "manifest")

    manager.register(
        character_name="Ada",
        weight_path=ada_weight,
        metadata={"trigger_phrase": "ada person"},
    )
    manager.register(
        character_name="Bran",
        weight_path=bran_weight,
        metadata={"trigger_phrase": "bran ranger"},
    )

    resolved = manager.resolve_actors(
        [
            {"name": "Ada", "character_name": "Ada", "weight": 0.8},
            {"name": "Ada", "trigger_phrase": "ada override"},
            {"name": "Bran", "character_name": "Bran"},
            {
                "name": "Guest",
                "trigger_phrase": "guest token",
                "lora_name": "guest_lora",
                "weight": 0.6,
            },
        ]
    )

    assert manager.get("Ada")["trigger_phrase"] == "ada person"
    assert [actor["name"] for actor in resolved] == ["Ada", "Bran", "Guest"]
    assert resolved[0]["trigger_phrase"] == "ada override"
    assert resolved[0]["lora_name"] == "ada"
    assert resolved[0]["weight"] == 0.8
    assert resolved[1]["trigger_phrase"] == "bran ranger"
    assert resolved[1]["source"] == "manifest"
    assert resolved[2]["source"] == "explicit"


def test_lora_manager_resolve_actors_fails_when_trigger_phrase_is_missing(tmp_path: Path) -> None:
    manager = LoRAManager(base_dir=tmp_path / "manifest")

    with pytest.raises(ValueError, match="trigger_phrase"):
        manager.resolve_actors([{"name": "Guest", "lora_name": "guest_lora"}])
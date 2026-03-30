from __future__ import annotations

import json
from pathlib import Path

from src.training.style_lora_manager import StyleLoRAManager


def _write_style_catalog(
    tmp_path: Path,
    *,
    file_path: Path | None,
    compatible_model_families: list[str] | None = None,
) -> Path:
    catalog_path = tmp_path / "style_loras.json"
    payload = {
        "styles": [
            {
                "style_id": "cinematic_grit",
                "display_name": "Cinematic Grit",
                "trigger_phrase": "cinematic grit lighting",
                "lora_name": "cinematic_grit_style",
                "weight": 0.7,
                "file_path": str(file_path) if file_path else None,
                "compatible_model_families": compatible_model_families or ["sdxl"],
            }
        ]
    }
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    return catalog_path


def test_style_lora_manager_resolves_available_style_selection(tmp_path: Path) -> None:
    weight_path = tmp_path / "cinematic_grit_style.safetensors"
    weight_path.write_bytes(b"style")
    catalog_path = _write_style_catalog(tmp_path, file_path=weight_path)
    manager = StyleLoRAManager(catalog_path=catalog_path, webui_root=None)

    resolved = manager.resolve_selection({"style_id": "cinematic_grit"}, base_model="juggernautXL.safetensors")

    assert resolved is not None
    assert resolved.applied is True
    assert resolved.lora_name == "cinematic_grit_style"
    assert resolved.trigger_phrase == "cinematic grit lighting"
    assert resolved.weight == 0.7


def test_style_lora_manager_warns_when_weight_file_is_missing(tmp_path: Path) -> None:
    catalog_path = _write_style_catalog(tmp_path, file_path=tmp_path / "missing.safetensors")
    manager = StyleLoRAManager(catalog_path=catalog_path, webui_root=None)

    resolved = manager.resolve_selection({"style_id": "cinematic_grit"}, base_model="juggernautXL.safetensors")

    assert resolved is not None
    assert resolved.applied is False
    assert resolved.available is False
    assert "missing weight file" in str(resolved.warning)


def test_style_lora_manager_skips_incompatible_model_family(tmp_path: Path) -> None:
    weight_path = tmp_path / "cinematic_grit_style.safetensors"
    weight_path.write_bytes(b"style")
    catalog_path = _write_style_catalog(
        tmp_path,
        file_path=weight_path,
        compatible_model_families=["sdxl"],
    )
    manager = StyleLoRAManager(catalog_path=catalog_path, webui_root=None)

    resolved = manager.resolve_selection({"style_id": "cinematic_grit"}, base_model="sd15_model.safetensors")

    assert resolved is not None
    assert resolved.applied is False
    assert resolved.available is False
    assert "looks like sd15" in str(resolved.warning)
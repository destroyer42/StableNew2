"""Stage-enable flags saved in a PromptPack's preset data survive ``load_pack_config``."""

from __future__ import annotations

import json
from pathlib import Path

from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.utils.config import ConfigManager


def test_stage_flags_preserved_on_load(tmp_path: Path) -> None:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    pack_document = {
        "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
        "pack_data": {
            "name": "test_pack",
            "slots": [],
            "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
        },
        "preset_data": {
            "txt2img": {"model": "test_model.safetensors", "steps": 20, "cfg_scale": 7.5},
            "pipeline": {
                "txt2img_enabled": True,
                "img2img_enabled": False,
                "adetailer_enabled": True,
                "upscale_enabled": True,
            },
        },
    }
    (packs_dir / "test_pack.json").write_text(json.dumps(pack_document), encoding="utf-8")

    manager = ConfigManager(presets_dir=tmp_path / "presets", packs_dir=packs_dir)
    loaded = manager.load_pack_config("test_pack")

    assert loaded is not None
    pipeline = loaded["pipeline"]
    assert pipeline["txt2img_enabled"] is True
    assert pipeline["img2img_enabled"] is False
    assert pipeline["adetailer_enabled"] is True
    assert pipeline["upscale_enabled"] is True

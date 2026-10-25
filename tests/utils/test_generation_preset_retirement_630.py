"""PR-IMG-PROFILE-630: the legacy named Generation Presets are retired; unrelated files and data are never touched.

Retired: ConfigManager's named-preset API, the Pipeline preset/recipe controls, ``--preset`` on the CLI. Kept untouched:
``settings.json``, ``last_settings.json``, ``pack_overrides.json``, PromptPack ``preset_data``, and any file a user left in
the application folder (including old preset files, which are neither read nor deleted).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from src.utils.config import ConfigManager

RETIRED_API = (
    "list_presets",
    "save_preset",
    "load_preset",
    "delete_preset",
    "ensure_default_preset",
    "load_default_preset",
    "set_default_preset",
    "get_default_preset_name",
)
SRC = Path(__file__).resolve().parents[2] / "src"


def test_config_manager_no_longer_exposes_a_named_preset_api() -> None:
    for name in RETIRED_API:
        assert not hasattr(ConfigManager, name), name


def test_no_module_defines_the_retired_preset_functions() -> None:
    names = "|".join(RETIRED_API)
    pattern = re.compile(rf"^\s*def ({names})\(", re.MULTILINE)
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert offenders == []


def test_legacy_and_unrelated_files_are_never_read_modified_or_deleted(tmp_path: Path) -> None:
    folder = tmp_path / "presets"
    folder.mkdir()
    files = {
        "old_recipe.json": json.dumps({"txt2img": {"steps": 99, "model": "legacy.safetensors"}}),
        "default.json": json.dumps({"txt2img": {"steps": 98}}),
        ".default_preset": "old_recipe",
        "settings.json": json.dumps({"output_dir": "D:/out"}),
        "last_settings.json": json.dumps({"txt2img": {"steps": 7}}),
        "pack_overrides.json": json.dumps({"hero": {"txt2img": {"steps": 5}}}),
        "notes.txt": "machine-local note",
    }
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    before = {name: (folder / name).read_bytes() for name in files}

    manager = ConfigManager(
        presets_dir=folder, packs_dir=tmp_path / "packs", global_prompt_dir=tmp_path / "g"
    )
    config = manager.get_default_config()
    manager.resolve_config(manager.get_pack_overrides("hero"))
    assert manager.get_setting("output_dir") == "D:/out"

    # Legacy files are not a configuration layer: their values never appear.
    assert config["txt2img"]["steps"] != 99 and config["txt2img"]["steps"] != 98
    assert config["txt2img"].get("model") != "legacy.safetensors"
    for name in files:
        assert (folder / name).exists(), f"{name} was deleted"
    assert {name: (folder / name).read_bytes() for name in files if name != "settings.json"} == {
        name: data for name, data in before.items() if name != "settings.json"
    }


def test_pack_preset_data_remains_the_pack_settings_store(tmp_path: Path) -> None:
    from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION

    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "g",
    )
    manager.packs_dir.mkdir(parents=True, exist_ok=True)
    path = manager.packs_dir / "hero.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {"name": "hero", "slots": [{"index": 0, "text": "a", "negative": ""}]},
                "preset_data": {"txt2img": {"steps": 12}},
            }
        ),
        encoding="utf-8",
    )
    assert manager.get_pack_config("hero")["txt2img"]["steps"] == 12
    assert manager.save_pack_config("hero", {"txt2img": {"steps": 14}})
    assert json.loads(path.read_text(encoding="utf-8"))["preset_data"]["txt2img"]["steps"] == 14


def test_cli_no_longer_accepts_a_preset_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import cli

    monkeypatch.setattr(sys, "argv", ["stablenew", "--prompt", "a cat", "--preset", "old"])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 2


def test_pipeline_sidebar_has_no_preset_or_recipe_controls() -> None:
    text = (SRC / "gui" / "sidebar_panel_v2.py").read_text(encoding="utf-8")
    for retired in (
        "saved_recipe_dropdown",
        "preset_combo",
        "on_preset_",
        "recipe_summary",
        "Load Preset",
        "Save Preset",
    ):
        assert retired not in text, retired
    assert "Working Settings" in text and "save_startup_defaults_button" in text

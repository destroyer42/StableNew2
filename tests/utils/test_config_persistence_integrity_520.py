"""PR-GUI-UX-520: configuration persistence must never corrupt or fabricate saved user data.

Covers ``ConfigManager.save_pack_config`` (PromptPack ``preset_data``), ``save_preset``, ``save_pack_overrides`` and
``save_settings``: native documents stay valid, unreadable or unsupported documents are left byte-identical, and an
injected replace failure leaves the previous destination readable with no stray temp file.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.promptpacks.storage import (
    CURRENT_PROMPTPACK_SCHEMA_VERSION,
    PromptPackFormatError,
    discover_native_prompt_packs,
    load_prompt_pack_document,
    update_prompt_pack_preset_data,
)
from src.utils.config import ConfigManager


def _native_pack(name: str = "hero") -> dict[str, Any]:
    return {
        "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
        "pack_data": {
            "name": name,
            "show_preview": True,
            "slots": [
                {
                    "index": 0,
                    "text": "a knight",
                    "negative": "blurry",
                    "template_id": "",
                    "template_variables": {},
                    "loras": [["armor", 0.7]],
                    "future_slot_key": {"keep": [1, 2, 3]},
                },
                {"index": 1, "text": "a mage", "negative": ""},
            ],
            "matrix": {
                "enabled": True,
                "mode": "fanout",
                "limit": 4,
                "slots": [{"name": "hair", "values": ["red", "blue"]}],
            },
            "future_pack_key": "preserved",
        },
        "preset_data": {"txt2img": {"steps": 20}, "pipeline": {"txt2img_enabled": True}},
        "future_top_key": {"nested": True},
    }


@pytest.fixture
def manager(tmp_path: Path) -> ConfigManager:
    return ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "global",
    )


def _write_pack(manager: ConfigManager, stem: str, document: Any) -> Path:
    manager.packs_dir.mkdir(parents=True, exist_ok=True)
    path = manager.packs_dir / f"{stem}.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def _no_temp_files(directory: Path) -> None:
    assert [p.name for p in directory.iterdir() if p.name.endswith(".tmp")] == []


class _ReplaceFails:
    """Make the atomic publish step fail once the temp file is complete."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("injected replace failure")

        monkeypatch.setattr(os, "replace", boom)


# --------------------------------------------------------------------------- PromptPack preset_data


def test_save_pack_config_keeps_native_document_valid_and_discoverable(
    manager: ConfigManager,
) -> None:
    original = _native_pack()
    path = _write_pack(manager, "hero", original)

    assert manager.save_pack_config("hero.txt", {"txt2img": {"steps": 42}}) is True

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == CURRENT_PROMPTPACK_SCHEMA_VERSION
    assert saved["pack_data"] == original["pack_data"]
    assert saved["future_top_key"] == original["future_top_key"]
    assert saved["preset_data"] == {"txt2img": {"steps": 42}}
    assert path in discover_native_prompt_packs(manager.packs_dir)
    load_prompt_pack_document(path)  # strict validation passes
    _no_temp_files(manager.packs_dir)


def test_save_pack_config_does_not_mutate_callers_config(manager: ConfigManager) -> None:
    _write_pack(manager, "hero", _native_pack())
    config = {"pipeline": {"adetailer_enabled": True}, "adetailer": {"enabled": False}}
    before = copy.deepcopy(config)

    assert manager.save_pack_config("hero", config) is True

    assert config == before


def test_save_pack_config_keeps_adetailer_alias_synchronization(manager: ConfigManager) -> None:
    path = _write_pack(manager, "hero", _native_pack())

    assert manager.save_pack_config(
        "hero", {"pipeline": {"adetailer_enabled": True}, "adetailer": {"enabled": False}}
    )

    preset = json.loads(path.read_text(encoding="utf-8"))["preset_data"]
    assert preset["pipeline"]["adetailer_enabled"] is True
    assert preset["adetailer"]["enabled"] is True
    assert preset["adetailer"]["adetailer_enabled"] is True
    # Narrow sync only: no unrelated defaults are injected into the pack.
    assert "txt2img" not in preset


def test_save_pack_config_for_missing_pack_creates_nothing(manager: ConfigManager) -> None:
    assert manager.save_pack_config("ghost", {"txt2img": {"steps": 9}}) is False

    assert list(manager.packs_dir.glob("*")) == []
    with pytest.raises(PromptPackFormatError, match="not found"):
        manager.update_pack_config("ghost", {"txt2img": {"steps": 9}})


@pytest.mark.parametrize(
    ("label", "raw"),
    [
        ("truncated_json", '{"schema_version": 1, "pack_data": {"name": "x", "slo'),
        ("not_an_object", "[1, 2, 3]"),
        ("unsupported_schema", json.dumps({**_native_pack(), "schema_version": 2})),
        (
            "unversioned_unified",
            json.dumps({k: v for k, v in _native_pack().items() if k != "schema_version"}),
        ),
        ("legacy_pack_only", json.dumps({"name": "old", "slots": [{"text": "x"}]})),
        ("legacy_config_only", json.dumps({"pipeline": {"txt2img_enabled": True}, "txt2img": {}})),
    ],
)
def test_unreadable_or_unsupported_pack_is_never_replaced(
    manager: ConfigManager, label: str, raw: str
) -> None:
    manager.packs_dir.mkdir(parents=True, exist_ok=True)
    path = manager.packs_dir / "victim.json"
    path.write_text(raw, encoding="utf-8")
    before = path.read_bytes()

    assert manager.save_pack_config("victim", {"txt2img": {"steps": 1}}) is False
    with pytest.raises(PromptPackFormatError):
        manager.update_pack_config("victim", {"txt2img": {"steps": 1}})

    assert path.read_bytes() == before, label
    _no_temp_files(manager.packs_dir)


def test_pack_write_failure_leaves_previous_valid_pack_readable(
    manager: ConfigManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_pack(manager, "hero", _native_pack())
    before = path.read_bytes()
    _ReplaceFails(monkeypatch)

    assert manager.save_pack_config("hero", {"txt2img": {"steps": 99}}) is False

    monkeypatch.undo()
    assert path.read_bytes() == before
    load_prompt_pack_document(path)
    _no_temp_files(manager.packs_dir)


def test_update_prompt_pack_preset_data_replaces_only_preset_data(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    original = _native_pack()
    path.write_text(json.dumps(original), encoding="utf-8")

    update_prompt_pack_preset_data(path, {"upscale": {"upscaler": "R-ESRGAN"}})

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {**original, "preset_data": {"upscale": {"upscaler": "R-ESRGAN"}}}


# --------------------------------------------------------------------------- presets, overrides, settings


def test_save_preset_roundtrips_and_fails_atomically(
    manager: ConfigManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert manager.save_preset("look", {"txt2img": {"steps": 33}}) is True
    path = manager.presets_dir / "look.json"
    assert json.loads(path.read_text(encoding="utf-8"))["txt2img"]["steps"] == 33
    before = path.read_bytes()

    _ReplaceFails(monkeypatch)
    assert manager.save_preset("look", {"txt2img": {"steps": 1}}) is False
    monkeypatch.undo()

    assert path.read_bytes() == before
    assert manager.load_preset("look")["txt2img"]["steps"] == 33
    _no_temp_files(manager.presets_dir)


@pytest.mark.parametrize(
    "reserved",
    [
        "settings",
        "Settings",
        "SETTINGS",
        "last_settings",
        "LAST_SETTINGS",
        "pack_overrides",
        "Pack_Overrides",
    ],
)
def test_application_files_cannot_be_saved_or_deleted_as_presets(
    manager: ConfigManager, reserved: str
) -> None:
    target = manager.presets_dir / f"{reserved}.json"
    target.write_text('{"keep": true}', encoding="utf-8")

    assert manager.save_preset(reserved, {"txt2img": {"steps": 1}}) is False
    assert manager.delete_preset(reserved) is False
    assert manager.load_preset(reserved) is None

    assert json.loads(target.read_text(encoding="utf-8")) == {"keep": True}
    assert reserved not in manager.list_presets()


@pytest.mark.parametrize("name", ["default", "Default", "DEFAULT"])
def test_default_preset_case_alias_cannot_be_deleted(manager: ConfigManager, name: str) -> None:
    target = manager.presets_dir / f"{name}.json"
    target.write_text('{"keep": true}', encoding="utf-8")

    assert manager.delete_preset(name) is False
    assert json.loads(target.read_text(encoding="utf-8")) == {"keep": True}


@pytest.mark.parametrize("bad_name", ["", "  ", "../escape", "a/b", "a\\b", "x\x00y"])
def test_preset_names_cannot_escape_the_presets_folder(
    manager: ConfigManager, bad_name: str
) -> None:
    assert manager.save_preset(bad_name, {"txt2img": {}}) is False
    assert not (manager.presets_dir.parent / "escape.json").exists()
    assert list(manager.presets_dir.glob("*.json")) == []


def test_pack_overrides_keep_prior_entries_and_fail_atomically(
    manager: ConfigManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert manager.save_pack_overrides("a", {"txt2img": {"steps": 5}}) is True
    assert manager.save_pack_overrides("b", {"txt2img": {"steps": 6}}) is True
    path = manager.presets_dir / "pack_overrides.json"
    before = path.read_bytes()

    _ReplaceFails(monkeypatch)
    assert manager.save_pack_overrides("c", {"txt2img": {"steps": 7}}) is False
    monkeypatch.undo()

    assert path.read_bytes() == before
    assert manager.get_pack_overrides("a") == {"txt2img": {"steps": 5}}
    _no_temp_files(manager.presets_dir)


def test_unreadable_overrides_file_is_not_replaced_by_a_one_entry_object(
    manager: ConfigManager,
) -> None:
    path = manager.presets_dir / "pack_overrides.json"
    path.write_text('{"a": {"txt2img": {"steps": 5}', encoding="utf-8")  # truncated
    before = path.read_bytes()

    assert manager.save_pack_overrides("b", {"txt2img": {"steps": 6}}) is False

    assert path.read_bytes() == before


def test_save_settings_fails_atomically(
    manager: ConfigManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert manager.save_settings({"output_dir": "D:/out", "model_dir": "D:/models"}) is True
    path = manager.presets_dir / "settings.json"
    before = path.read_bytes()

    _ReplaceFails(monkeypatch)
    assert manager.save_settings({"output_dir": "E:/other"}) is False
    monkeypatch.undo()

    assert path.read_bytes() == before
    _no_temp_files(manager.presets_dir)


# --------------------------------------------------------------------------- Prompt tab model vs sidebar apply


def test_apply_keeps_prompt_tab_authored_preset_keys(manager: ConfigManager) -> None:
    document = _native_pack()
    document["preset_data"] = {
        "style_lora": {"name": "ink", "weight": 0.6},
        "version": "7",
        "txt2img": {"steps": 20},
    }
    path = _write_pack(manager, "hero", document)

    assert manager.save_pack_config("hero", {"txt2img": {"steps": 31}}) is True

    preset = json.loads(path.read_text(encoding="utf-8"))["preset_data"]
    assert preset == {
        "style_lora": {"name": "ink", "weight": 0.6},
        "version": "7",
        "txt2img": {"steps": 31},
    }
    # A key the applied configuration defines itself wins.
    assert manager.save_pack_config("hero", {"version": "8"}) is True
    assert json.loads(path.read_text(encoding="utf-8"))["preset_data"]["version"] == "8"


def test_prompt_tab_save_does_not_revert_settings_applied_from_the_sidebar(
    manager: ConfigManager,
) -> None:
    from src.gui.models.prompt_pack_model import PromptPackModel

    path = _write_pack(manager, "hero", _native_pack())
    model = PromptPackModel.load_from_file(path)  # the Prompt tab opens the pack
    assert (
        manager.save_pack_config("hero", {"txt2img": {"steps": 77}}) is True
    )  # sidebar applies settings
    model.set_slot_text(0, "a knight in rain")  # operator keeps editing prompts, then saves

    model.save_to_file()

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["preset_data"] == {"txt2img": {"steps": 77}}
    assert saved["pack_data"]["slots"][0]["text"] == "a knight in rain"
    assert saved["pack_data"]["slots"][0]["future_slot_key"] == {"keep": [1, 2, 3]}
    assert model.preset_data == {"txt2img": {"steps": 77}}


def test_prompt_tab_style_lora_edit_survives_the_merge_with_applied_settings(
    manager: ConfigManager,
) -> None:
    from src.gui.models.prompt_pack_model import PromptPackModel

    path = _write_pack(manager, "hero", _native_pack())
    model = PromptPackModel.load_from_file(path)
    assert manager.save_pack_config("hero", {"txt2img": {"steps": 77}}) is True
    model.preset_data = {**model.preset_data, "style_lora": {"name": "ink", "weight": 0.5}}

    model.save_to_file()

    preset = json.loads(path.read_text(encoding="utf-8"))["preset_data"]
    assert preset["style_lora"] == {"name": "ink", "weight": 0.5}
    assert preset["txt2img"] == {"steps": 77}


def test_new_native_pack_is_versioned_discoverable_and_loadable(manager: ConfigManager) -> None:
    from src.gui.models.prompt_pack_model import PromptPackModel
    from src.promptpacks.storage import prompt_pack_rows

    model = PromptPackModel.new("fresh")
    model.set_slot_text(0, "a lighthouse at dusk")
    path = model.save_to_file(manager.packs_dir / "fresh.json")

    document = load_prompt_pack_document(path)
    assert document["schema_version"] == CURRENT_PROMPTPACK_SCHEMA_VERSION
    assert path in discover_native_prompt_packs(manager.packs_dir)
    assert [row.quality_line for row in prompt_pack_rows(document)] == ["a lighthouse at dusk"]
    assert manager.load_pack_config("fresh") is not None
    # And its settings can then be saved through the same boundary.
    assert manager.save_pack_config("fresh", {"txt2img": {"steps": 12}}) is True
    assert path in discover_native_prompt_packs(manager.packs_dir)

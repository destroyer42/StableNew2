"""PR-GUI-UX-520: applying settings to PromptPacks and loading PromptPack settings, against real storage.

A real ``ConfigManager`` over temporary folders and a real ``AppController`` (no Tk, no backend, no queue).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.controller.app_controller_services.pack_settings_apply_service import (
    apply_settings_to_packs,
)
from src.gui.app_state_v2 import AppStateV2
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION, discover_native_prompt_packs
from src.utils.config import ConfigManager


def _pack(name: str, preset: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
        "pack_data": {
            "name": name,
            "slots": [{"index": 0, "text": f"{name} prompt", "negative": "", "extra_slot_key": 1}],
            "matrix": {
                "enabled": True,
                "mode": "fanout",
                "limit": 2,
                "slots": [{"name": "x", "values": ["a", "b"]}],
            },
        },
        "preset_data": preset
        or {"txt2img": {"steps": 10}, "style_lora": {"name": "ink", "weight": 0.5}},
    }


class _Card:
    def __init__(self, **values: Any) -> None:
        self.values = values

    def to_config_dict(self) -> dict[str, Any]:
        return {"txt2img": dict(self.values)}


class _StagePanel:
    def __init__(self, card: _Card) -> None:
        self.txt2img_card = card

    def load_adetailer_config(self, _config: dict[str, Any]) -> None:
        return None


@pytest.fixture
def env(tmp_path: Path):
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "g",
    )
    manager.packs_dir.mkdir(parents=True)
    for name in ("good", "other"):
        (manager.packs_dir / f"{name}.json").write_text(json.dumps(_pack(name)), encoding="utf-8")
    (manager.packs_dir / "legacy.json").write_text(
        json.dumps({"name": "legacy", "slots": []}), encoding="utf-8"
    )
    card = _Card(steps=33, cfg_scale=6.5)
    controller = AppController(None, threaded=False, config_manager=manager)
    controller.app_state = AppStateV2()
    controller.main_window = SimpleNamespace(
        pipeline_tab=SimpleNamespace(stage_cards_panel=_StagePanel(card))
    )
    return controller, manager, card


def _preset(manager: ConfigManager, name: str) -> dict[str, Any]:
    return json.loads((manager.packs_dir / f"{name}.json").read_text(encoding="utf-8"))


def test_apply_reports_each_pack_and_leaves_failed_packs_untouched(env) -> None:
    controller, manager, _ = env
    legacy_before = (manager.packs_dir / "legacy.json").read_bytes()
    run_config_before = dict(controller.app_state.run_config)

    report = controller.on_pipeline_pack_apply_config(["good", "legacy", "ghost", "other", "good"])

    assert report.succeeded == ("good", "other")
    assert [item.pack_id for item in report.failed] == ["legacy", "ghost"]
    assert report.partial and not report.all_ok
    assert all(item.error for item in report.failed)
    assert (manager.packs_dir / "legacy.json").read_bytes() == legacy_before
    assert not (manager.packs_dir / "ghost.json").exists()
    for name in ("good", "other"):
        document = _preset(manager, name)
        assert document["preset_data"]["txt2img"] == {"steps": 33, "cfg_scale": 6.5}
        # Prompts, Matrix, slot extras and the Prompt-tab-authored style LoRA are untouched.
        assert document["pack_data"] == _pack(name)["pack_data"]
        assert document["preset_data"]["style_lora"] == {"name": "ink", "weight": 0.5}
        assert document["schema_version"] == CURRENT_PROMPTPACK_SCHEMA_VERSION
    assert {path.stem for path in discover_native_prompt_packs(manager.packs_dir)} == {
        "good",
        "other",
    }
    # Applying is not a working-state change.
    assert controller.app_state.run_config == run_config_before


def test_apply_with_nothing_to_apply_reports_none_and_writes_nothing(env) -> None:
    controller, manager, _ = env
    controller._collect_current_stage_configs = lambda: {}  # nothing gathered from the GUI
    before = (manager.packs_dir / "good.json").read_bytes()

    assert controller.on_pipeline_pack_apply_config(["good"]) is None

    assert (manager.packs_dir / "good.json").read_bytes() == before


def test_loading_pack_settings_reports_whether_any_were_found(env) -> None:
    controller, manager, _ = env
    before = (manager.packs_dir / "good.json").read_bytes()

    assert controller.on_pipeline_pack_load_config("good") is True
    assert controller.on_pipeline_pack_load_config("ghost") is False

    assert (manager.packs_dir / "good.json").read_bytes() == before


def test_working_fingerprint_tracks_unsaved_edits_only(env) -> None:
    controller, _, card = env
    clean = controller.working_settings_fingerprint()
    assert clean and controller.working_settings_fingerprint() == clean

    card.values["steps"] = 34

    assert controller.working_settings_fingerprint() != clean
    card.values["steps"] = 33
    assert controller.working_settings_fingerprint() == clean


def test_apply_service_never_mutates_the_callers_config_and_dedupes(env) -> None:
    _, manager, _ = env
    config = {"pipeline": {"adetailer_enabled": True}, "adetailer": {"enabled": False}}
    before = json.loads(json.dumps(config))

    report = apply_settings_to_packs(manager, ["good", "good", " "], config, source="x")

    assert [item.pack_id for item in report.outcomes] == ["good"]
    assert config == before
    assert _preset(manager, "good")["preset_data"]["adetailer"]["enabled"] is True


def test_service_falls_back_to_bool_save_for_managers_without_update(tmp_path: Path) -> None:
    class Legacy:
        def __init__(self) -> None:
            self.saved: list[str] = []

        def save_pack_config(self, pack_id: str, config: dict[str, Any]) -> bool:
            self.saved.append(pack_id)
            return pack_id != "bad"

    manager = Legacy()
    report = apply_settings_to_packs(manager, ["a", "bad"], {"x": 1}, source="s")

    assert report.succeeded == ("a",)
    assert report.failed[0].pack_id == "bad" and report.failed[0].error

"""GUI-TRUTH-912: the Output card no longer offers Format / Filename pattern, and old packs that carry them still load.

``image_format`` and ``filename_pattern`` were saved into pack settings, but no pipeline, queue or backend code reads
them. The controller must neither show them on the card nor write them when a pack is saved, and a pack that already
contains the keys must keep loading (no migration, no failure). No Tk, backend or queue.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.utils.config import ConfigManager

LEGACY_PIPELINE = {
    "images_per_prompt": 3,
    "output_dir": "D:/legacy_out",
    "image_format": "webp",
    "filename_pattern": "{timestamp}_{index}",
    "seed_mode": "increment",
}


class _OutputPanel:
    def __init__(self) -> None:
        self.applied: dict[str, Any] | None = None

    def apply_from_overrides(self, overrides: dict[str, Any]) -> None:
        self.applied = dict(overrides)

    def get_output_overrides(self) -> dict[str, Any]:
        return {"output_dir": "out", "batch_size": 2, "seed_mode": "fixed", "output_route": "Auto"}


class _Card:
    def to_config_dict(self) -> dict[str, Any]:
        return {"txt2img": {"steps": 20}}


class _StagePanel:
    txt2img_card = _Card()

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
    document = {
        "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
        "pack_data": {"name": "old", "slots": [{"index": 0, "text": "old prompt", "negative": ""}]},
        "preset_data": {"txt2img": {"steps": 12}, "pipeline": dict(LEGACY_PIPELINE)},
    }
    (manager.packs_dir / "old.json").write_text(json.dumps(document), encoding="utf-8")
    panel = _OutputPanel()
    controller = AppController(None, threaded=False, config_manager=manager)
    controller.app_state = AppStateV2()
    controller.main_window = SimpleNamespace(
        pipeline_tab=SimpleNamespace(stage_cards_panel=_StagePanel()),
        sidebar_panel_v2=SimpleNamespace(
            output_settings_card=SimpleNamespace(child=panel),
            set_stage_state=lambda *_args, **_kwargs: None,
        ),
    )
    return controller, manager, panel


def test_a_pack_that_still_carries_the_old_output_keys_loads(env) -> None:
    controller, manager, panel = env
    before = (manager.packs_dir / "old.json").read_bytes()

    assert controller.on_pipeline_pack_load_config("old") is True

    assert (
        manager.packs_dir / "old.json"
    ).read_bytes() == before  # loading never rewrites or migrates the pack
    assert panel.applied is not None
    assert panel.applied["batch_size"] == 3 and panel.applied["output_dir"] == "D:/legacy_out"
    assert panel.applied["seed_mode"] == "increment"
    assert "image_format" not in panel.applied and "filename_pattern" not in panel.applied
    # The pack's own values are still part of the working run config; nothing was stripped or rejected.
    assert controller.app_state.run_config["pipeline"]["image_format"] == "webp"


def test_saving_the_working_settings_no_longer_writes_the_unread_output_keys(env) -> None:
    controller, _manager, _panel = env

    pipeline = controller._collect_working_config_for_pack_save()["pipeline"]

    assert pipeline["images_per_prompt"] == 2 and pipeline["seed_mode"] == "fixed"
    assert "image_format" not in pipeline and "filename_pattern" not in pipeline

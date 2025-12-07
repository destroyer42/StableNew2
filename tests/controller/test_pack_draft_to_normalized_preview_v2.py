from __future__ import annotations

from pathlib import Path

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.utils.prompt_packs import PromptPackInfo


class DummyPipelineTab:
    def __init__(self) -> None:
        self.txt2img_enabled = True
        self.img2img_enabled = False
        self.adetailer_enabled = True
        self.upscale_enabled = True


def test_on_pipeline_add_packs_to_job_populates_preview_metadata(tmp_path: Path) -> None:
    pack_path = tmp_path / "test_pack.txt"
    pack_path.write_text("positive prompt\nneg:negative remark")

    controller = AppController(
        main_window=None,
        pipeline_runner=None,
        pipeline_controller=None,
        job_service=None,
    )
    controller.app_state = AppStateV2()
    controller.main_window = type("Window", (), {"pipeline_tab": DummyPipelineTab()})()
    controller.packs = [
        PromptPackInfo(name="test_pack", path=pack_path, preset_name="")
    ]

    controller.on_pipeline_add_packs_to_job(["test_pack"])

    assert len(controller.app_state.job_draft.packs) == 1
    entry = controller.app_state.job_draft.packs[0]
    assert entry.prompt_text == "positive prompt"
    assert entry.negative_prompt_text == "negative remark"
    assert entry.stage_flags.get("txt2img", False)
    assert entry.stage_flags.get("img2img") is False
    assert entry.stage_flags.get("adetailer", False)
    assert entry.stage_flags.get("upscale", False)
    assert entry.stage_flags.get("refiner") in {True, False}
    assert "enabled" in entry.randomizer_metadata

    assert entry.config_snapshot.get("randomization_enabled") is not None

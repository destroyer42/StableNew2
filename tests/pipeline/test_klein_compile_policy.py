"""PR-IMG-116: Klein T2I intent is frozen by the compilers (pack and generic paths); other models are untouched."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.gui.app_state_v2 import PackJobEntry
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_ID
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from tests.pipeline.test_prompt_pack_job_builder import (
    BASE_PACK_CONFIG,
    SequentialIdGenerator,
    StubConfigManager,
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"


@pytest.fixture(autouse=True)
def _forge_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui")


class _KleinConfigManager(StubConfigManager):
    """A user config with SDXL-style defaults, the Klein checkpoint selected, and global negative terms."""

    def __init__(self, tmp_path: Path, *, model: str) -> None:
        super().__init__(tmp_path)
        self._config = {
            **BASE_PACK_CONFIG,
            "txt2img": {**BASE_PACK_CONFIG["txt2img"], "model": model, "width": 768, "height": 1024,
                        "negative_prompt": "blurry, bad quality"},
            "prompt_optimizer": {"enabled": True},
        }


def _pack_job(tmp_path: Path, model: str):
    builder = PromptPackNormalizedJobBuilder(
        config_manager=_KleinConfigManager(tmp_path, model=model),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
    )
    entry = PackJobEntry(
        pack_id="klein-pack", pack_name="Klein Pack", config_snapshot={}, prompt_text="portrait on a rainy street",
        stage_flags={"txt2img": True}, randomizer_metadata={"enabled": False}, pack_row_index=0, matrix_slot_values={},
    )
    records = builder.build_jobs([entry])
    assert records
    return records[0]


def test_pack_path_freezes_the_klein_profile_and_semantics(tmp_path: Path) -> None:
    record = _pack_job(tmp_path, KLEIN)
    assert record.backend_options["image"] == {
        "backend_id": "forge_webui", "model_profile": {"id": KLEIN_PROFILE_ID, "version": 1}}
    assert (record.sampler_name, record.scheduler, record.steps, record.cfg_scale) == ("Euler", "Beta", 4, 1.0)
    assert record.negative_prompt == ""  # pack/default negative text and the global negative are not applied
    assert (record.width, record.height) == (768, 1024)
    assert record.base_model == KLEIN
    # what the compiler froze must pass the runner's backend validation
    ForgeWebUIImageBackend().validate_njr_intent(record, ["txt2img"])


def test_pack_path_for_a_normal_model_is_unchanged(tmp_path: Path) -> None:
    record = _pack_job(tmp_path, "sdxl.safetensors")
    assert "model_profile" not in record.backend_options["image"]
    assert (record.sampler_name, record.steps, record.cfg_scale) == ("Euler", 24, 7.5)
    assert "blurry" in record.negative_prompt


def test_generic_builder_path_freezes_klein_and_leaves_sdxl_alone() -> None:
    def build(model: str) -> Any:
        config = {
            "prompt": "portrait", "negative_prompt": "blurry", "model": model, "sampler": "Euler a", "steps": 30,
            "cfg_scale": 7.0, "width": 768, "height": 1024, "seed": 5,
            "txt2img": {"model": model, "sampler_name": "Euler a", "steps": 30, "cfg_scale": 7.0, "scheduler": "Normal"},
        }
        return JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()).build_jobs(base_config=config)[0]

    klein = build(KLEIN)
    assert klein.backend_options["image"]["model_profile"] == {"id": KLEIN_PROFILE_ID, "version": 1}
    assert (klein.steps, klein.cfg_scale) == (4, 1.0)
    assert klein.negative_prompt == ""
    sdxl = build("sdxl.safetensors")
    assert "model_profile" not in sdxl.backend_options["image"]
    assert (sdxl.steps, sdxl.cfg_scale, sdxl.negative_prompt) == (30, 7.0, "blurry")

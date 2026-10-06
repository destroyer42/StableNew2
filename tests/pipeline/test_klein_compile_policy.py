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
        "backend_id": "forge_webui", "model_profile": {"id": KLEIN_PROFILE_ID, "version": 2}}
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
    assert klein.backend_options["image"]["model_profile"] == {"id": KLEIN_PROFILE_ID, "version": 2}
    assert (klein.steps, klein.cfg_scale) == (4, 1.0)
    assert klein.negative_prompt == ""
    sdxl = build("sdxl.safetensors")
    assert "model_profile" not in sdxl.backend_options["image"]
    assert (sdxl.steps, sdxl.cfg_scale, sdxl.negative_prompt) == (30, 7.0, "blurry")


def _real_pack_job(tmp_path: Path, loras: list[list[Any]]):
    """A native PromptPack slot carrying the LoRA(s): the production representation of pack LoRA intent."""

    from tests.pipeline.test_prompt_pack_job_builder import _write_native_pack

    config_manager = _KleinConfigManager(tmp_path, model=KLEIN)
    pack = _write_native_pack(
        config_manager.packs_dir / "klein-pack.json", text="portrait on a rainy street", loras=loras
    )
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=config_manager.packs_dir,
    )
    entry = PackJobEntry(
        pack_id=pack.name, pack_name="Klein Pack", config_snapshot={}, stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False}, pack_row_index=0, matrix_slot_values={},
    )
    records = builder.build_jobs([entry])
    assert records
    return records[0]


def _compatible_backend() -> ForgeWebUIImageBackend:
    from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus

    return ForgeWebUIImageBackend(
        lora_resolver=lambda name: KleinLoraDecision(
            name, KleinLoraStatus.COMPATIBLE, "ok", "embedded_metadata:ss_base_model_version", "flux2_klein_4b", "ab" * 32
        )
    )


def test_pack_work_keeps_one_lora_tag_in_the_frozen_v2_intent_and_passes_admission(tmp_path: Path) -> None:
    """PR-IMG-117: the existing LoRATag + rendered ``<lora:name:weight>`` path carries the adapter to Forge."""

    record = _real_pack_job(tmp_path, [["klein-style", 0.8]])

    assert record.backend_options["image"]["model_profile"] == {"id": KLEIN_PROFILE_ID, "version": 2}
    assert [(t.name, t.weight) for t in record.lora_tags] == [("klein-style", 0.8)]
    assert record.positive_prompt.count("<lora:klein-style:0.8>") == 1
    assert record.negative_prompt == "" and (record.steps, record.cfg_scale) == (4, 1.0)
    _compatible_backend().validate_njr_intent(record, ["txt2img"])  # one compatible adapter: admitted as compiled


def test_pack_work_with_two_loras_is_rejected_by_admission_not_dropped(tmp_path: Path) -> None:
    from src.image_backends.forge_klein_profile import KleinProfileError

    record = _real_pack_job(tmp_path, [["klein-style", 0.8], ["second", 0.5]])

    assert [t.name for t in record.lora_tags] == ["klein-style", "second"]  # the compiler never drops LoRA intent
    with pytest.raises(KleinProfileError, match="at most 1"):
        _compatible_backend().validate_njr_intent(record, ["txt2img"])


def test_pack_work_with_an_unverified_lora_is_rejected_by_admission(tmp_path: Path) -> None:
    from src.image_backends.forge_klein_lora import unavailable_decision
    from src.image_backends.forge_klein_profile import KleinProfileError

    record = _real_pack_job(tmp_path, [["generic-flux", 0.8]])

    backend = ForgeWebUIImageBackend(lora_resolver=lambda name: unavailable_decision(name, "no evidence"))
    with pytest.raises(KleinProfileError, match="not verified for FLUX.2 Klein 4B"):
        backend.validate_njr_intent(record, ["txt2img"])

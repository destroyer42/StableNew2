"""Native PromptPack intent must reject unsupported elements before adaptation removes them."""

import json

import pytest

from src.gui.app_state_v2 import PackJobEntry
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as P
from src.image_backends.forge_zimage_profile import ZImageProfileError
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from tests.image_backends.test_forge_zimage_profile import config
from tests.pipeline.test_prompt_pack_job_builder import (
    SequentialIdGenerator,
    StubConfigManager,
    _write_native_pack,
)


def _pack(tmp_path, monkeypatch, **slot_changes):
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui")
    manager = StubConfigManager(tmp_path)
    flat = config()
    manager._config = {
        "txt2img": {k: v for k, v in flat.items() if k not in {"backend_options", "prompt"}},
        "backend_options": flat["backend_options"], "prompt_optimizer": {"enabled": False},
        "pipeline": {"images_per_prompt": 1, "loop_count": 1, "apply_global_negative_txt2img": False,
                     "apply_global_positive_txt2img": False},
        "randomization": {"enabled": False},
    }
    path = _write_native_pack(manager.packs_dir / "zimage.json", text="A ceramic teapot on a wooden table.")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["pack_data"]["slots"][0].update(slot_changes)
    path.write_text(json.dumps(data), encoding="utf-8")
    original = path.read_bytes()
    builder = PromptPackNormalizedJobBuilder(config_manager=manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1, id_fn=SequentialIdGenerator()), packs_dir=manager.packs_dir)
    entry = PackJobEntry(pack_id=path.name, pack_name="ZImage", stage_flags={"txt2img": True},
                         randomizer_metadata={"enabled": False}, config_snapshot={}, pack_row_index=0)
    return builder, entry, path, original


def test_exact_native_pack_builds_and_preserves_user_bytes(tmp_path, monkeypatch):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    records = builder.build_jobs([entry])
    assert len(records) == 1
    assert records[0].backend_options["image"]["model_profile"] == P.reference()
    assert records[0].negative_prompt == "" and records[0].steps == 9
    assert path.read_bytes() == original


@pytest.mark.parametrize("slot", [
    {"loras": [["adapter", 0.7]]}, {"negative": "bad"},
    {"positive_embeddings": [["token", 1]]}, {"negative_embeddings": [["token", 1]]},
    {"text": "A portrait <lora:adapter:1>"},
])
def test_native_unsupported_intent_is_rejected_before_adaptation(tmp_path, monkeypatch, slot):
    builder, entry, path, original = _pack(tmp_path, monkeypatch, **slot)
    with pytest.raises(ZImageProfileError):
        builder.build_jobs([entry])
    assert path.read_bytes() == original

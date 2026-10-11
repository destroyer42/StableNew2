"""Z-Image adapts authored prompt components and validates the frozen executable job."""

import json
from copy import deepcopy

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
])
def test_native_unsupported_components_are_adapted_without_changing_pack(tmp_path, monkeypatch, slot):
    builder, entry, path, original = _pack(tmp_path, monkeypatch, **slot)
    record, = builder.build_jobs([entry])
    assert record.positive_prompt == "A ceramic teapot on a wooden table."
    assert record.negative_prompt == ""
    assert not record.lora_tags and not record.positive_embeddings and not record.negative_embeddings
    assert record.provenance.metadata["prompt_adaptation"]["changed"]
    assert path.read_bytes() == original


def test_unresolved_inline_adapter_tokens_still_refuse(tmp_path, monkeypatch):
    # Inline text has no structured adapter ownership: do not guess at prose.
    slot = {"text": "A portrait <lora:adapter:1>"}
    builder, entry, path, original = _pack(tmp_path, monkeypatch, **slot)
    with pytest.raises(ZImageProfileError):
        builder.build_jobs([entry])
    assert path.read_bytes() == original


def test_weighted_prose_and_saved_negative_config_use_shared_adaptation(tmp_path, monkeypatch):
    builder, entry, path, original = _pack(
        tmp_path, monkeypatch, text="A (ceramic teapot:1.2) BREAK on a wooden table.",
        loras=[["adapter", 0.7]], positive_embeddings=[["token", 1]],
        negative_embeddings=[["negative-token", 1]], negative="blurry",
    )
    entry.config_snapshot = {
        "txt2img": {**builder._config_manager._config["txt2img"], "negative_prompt": "low quality",
                    "prompt": "An (unused preset prompt:1.2)"},
        "global_negative_prompt": "distorted", "global_prompt_policy_source": "frozen_njr",
        "pipeline": {**builder._config_manager._config["pipeline"], "apply_global_negative_txt2img": True},
    }
    source_config = deepcopy(entry.config_snapshot)
    record, = builder.build_jobs([entry])
    assert "ceramic teapot" in record.positive_prompt
    assert ":1.2" not in record.positive_prompt and "BREAK" not in record.positive_prompt
    assert record.negative_prompt == ""
    assert record.config["global_negative_prompt"] == ""
    operations = record.provenance.metadata["prompt_adaptation"]["operations"]
    codes = {operation["code"] for operation in operations}
    assert {"weighted_attention_flattened", "break_separator_normalized", "lora_dropped_unsupported",
            "negative_prompt_dropped_unsupported", "positive_embedding_dropped_unsupported",
            "negative_embedding_dropped_unsupported"} <= codes
    assert path.read_bytes() == original
    assert entry.config_snapshot == source_config

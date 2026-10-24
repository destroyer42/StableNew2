"""The compiler must freeze the selected optimizer policy, including explicit opt-out."""

import pytest

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from tests.pipeline.test_prompt_pack_job_builder import (
    SequentialIdGenerator,
    StubConfigManager,
    _write_native_pack,
)


def test_promptpack_compile_preserves_explicit_optimizer_settings(tmp_path):
    manager = StubConfigManager(tmp_path)
    selected = {
        "enabled": False,
        "dedupe_enabled": False,
        "preserve_lora_relative_order": False,
        "opt_out_pipeline_names": ["adetailer"],
    }
    manager._config["prompt_optimizer"] = selected
    pack = _write_native_pack(
        manager.packs_dir / "optimizer.json", text="masterpiece, beautiful woman"
    )
    builder = PromptPackNormalizedJobBuilder(
        config_manager=manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=manager.packs_dir,
    )
    records = builder.build_jobs(
        [
            PackJobEntry(
                pack_id=pack.name,
                pack_name="Optimizer",
                config_snapshot={},
                stage_flags={"txt2img": True},
                randomizer_metadata={"enabled": False},
                pack_row_index=0,
                matrix_slot_values={},
            )
        ]
    )
    assert len(records) == 1
    assert dict(records[0].config.get("prompt_optimizer") or {}) == selected


@pytest.mark.parametrize("enabled", [False, True])
def test_explicit_top_level_enabled_wins_over_stage_value(enabled):
    assert (
        PromptPackNormalizedJobBuilder._optimizer_enabled(
            {
                "prompt_optimizer": {"enabled": enabled},
                "txt2img": {"prompt_optimizer": {"enabled": not enabled}},
            }
        )
        is enabled
    )


@pytest.mark.parametrize(
    "snapshot, expected",
    [
        ({}, {"enabled": False, "dedupe_enabled": False, "preserve_lora_relative_order": True}),
        (
            {"enabled": True},
            {"enabled": True, "dedupe_enabled": False, "preserve_lora_relative_order": True},
        ),
        (
            {"enabled": False, "preserve_lora_relative_order": False},
            {"enabled": False, "dedupe_enabled": False, "preserve_lora_relative_order": False},
        ),
    ],
)
def test_real_resolution_precedence_and_frozen_njr(tmp_path, snapshot, expected):
    from src.utils.config import ConfigManager
    from tests.controller.test_effective_settings_equivalence_520 import _write_pack

    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "globals",
    )
    pack = _write_pack(
        manager,
        preset={
            "txt2img": {"model": "model.safetensors"},
            "prompt_optimizer": {"enabled": False, "dedupe_enabled": False},
        },
    )
    builder = PromptPackNormalizedJobBuilder(
        config_manager=manager, job_builder=JobBuilderV2(), packs_dir=manager.packs_dir
    )
    records = builder.build_jobs(
        [
            PackJobEntry(
                pack_id=pack.name,
                pack_name="Optimizer",
                config_snapshot={"prompt_optimizer": snapshot},
                stage_flags={"txt2img": True},
                randomizer_metadata={"enabled": False},
                pack_row_index=0,
            )
        ]
    )
    [record] = records
    frozen = record.config["prompt_optimizer"]
    for key, value in expected.items():
        assert frozen[key] is value
    assert frozen["opt_out_pipeline_names"] == []
    with pytest.raises(TypeError):
        record.workload.config["prompt_optimizer"]["enabled"] = not expected["enabled"]
    frozen["enabled"] = not expected["enabled"]  # public config is a detached projection
    snapshot["enabled"] = "later edit"
    assert record.config["prompt_optimizer"]["enabled"] is expected["enabled"]

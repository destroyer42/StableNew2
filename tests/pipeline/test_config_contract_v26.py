from __future__ import annotations

from src.pipeline.config_contract_v26 import (
    CONFIG_CONTRACT_SCHEMA_V26,
    attach_config_layers,
    build_config_layers,
    extract_execution_config,
)


def test_attach_config_layers_keeps_top_level_intent_and_adds_canonical_layers() -> None:
    payload = attach_config_layers(
        {
            "run_mode": "queue",
            "source": "run",
            "prompt_source": "pack",
            "prompt_pack_id": "pack-123",
        },
        intent_config={"run_mode": "queue", "source": "run", "prompt_source": "pack"},
        execution_config={},
    )

    assert payload["run_mode"] == "queue"
    assert payload["config_schema"] == CONFIG_CONTRACT_SCHEMA_V26
    assert payload["config_layers"]["schema"] == CONFIG_CONTRACT_SCHEMA_V26
    assert payload["config_layers"]["intent_config"]["source"] == "run"
    assert payload["config_layers"]["execution_config"] == {}


def test_build_config_layers_derives_video_backend_options_from_execution_config() -> None:
    execution_config = {
        "pipeline": {"animatediff_enabled": True},
        "animatediff": {"enabled": True, "motion_module": "mm_sd_v15_v2.ckpt", "fps": 12},
    }

    layers = build_config_layers(
        intent_config={"run_mode": "queue", "source": "add_to_queue"},
        execution_config=execution_config,
    )

    assert layers.schema == CONFIG_CONTRACT_SCHEMA_V26
    assert layers.execution_config["animatediff"]["motion_module"] == "mm_sd_v15_v2.ckpt"
    assert layers.backend_options["video"]["animatediff"]["fps"] == 12


def test_extract_execution_config_reads_layered_payloads() -> None:
    layered = {
        "config_layers": {
            "schema": CONFIG_CONTRACT_SCHEMA_V26,
            "intent_config": {"run_mode": "queue"},
            "execution_config": {
                "txt2img": {"model": "model-a", "steps": 28},
                "pipeline": {"txt2img_enabled": True},
            },
            "backend_options": {},
        }
    }

    execution = extract_execution_config(layered)

    assert execution["txt2img"]["model"] == "model-a"
    assert execution["pipeline"]["txt2img_enabled"] is True

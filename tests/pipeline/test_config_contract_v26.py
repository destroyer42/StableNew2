from __future__ import annotations

import pytest

from src.pipeline.config_contract_v26 import (
    CONFIG_CONTRACT_SCHEMA_V26,
    attach_config_layers,
    build_config_layers,
    extract_adaptive_refinement_intent,
    extract_secondary_motion_intent,
    extract_continuity_linkage,
    extract_execution_config,
    extract_plan_origin_linkage,
    validate_svd_native_execution_config,
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


def test_build_config_layers_derives_video_workflow_backend_options_from_execution_config() -> None:
    execution_config = {
        "video_workflow": {
            "workflow_id": "ltx_multiframe_anchor_v1",
            "workflow_version": "1.0.0",
            "backend_id": "comfy",
        }
    }

    layers = build_config_layers(
        intent_config={"run_mode": "queue", "source": "video"},
        execution_config=execution_config,
    )

    assert layers.backend_options["video"]["workflow"]["workflow_id"] == "ltx_multiframe_anchor_v1"
    assert layers.backend_options["video"]["workflow"]["backend_id"] == "comfy"


def test_build_config_layers_derives_svd_native_backend_options_from_execution_config() -> None:
    execution_config = {
        "svd_native": {
            "inference": {
                "model_id": "stabilityai/stable-video-diffusion-img2vid-xt",
                "fps": 7,
                "motion_bucket_id": 48,
            },
            "output": {"output_format": "mp4"},
        }
    }

    layers = build_config_layers(
        intent_config={"run_mode": "queue", "source": "add_to_queue"},
        execution_config=execution_config,
    )

    assert layers.backend_options["video"]["svd_native"]["inference"]["fps"] == 7
    assert layers.backend_options["video"]["svd_native"]["output"]["output_format"] == "mp4"


def test_validate_svd_native_execution_config_rejects_motion_bucket_out_of_range() -> None:
    with pytest.raises(ValueError, match="inference.motion_bucket_id"):
        validate_svd_native_execution_config({"inference": {"motion_bucket_id": 256}})


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


def test_extract_continuity_linkage_reads_metadata_block() -> None:
    layered = {
        "config_layers": {
            "schema": CONFIG_CONTRACT_SCHEMA_V26,
            "intent_config": {"run_mode": "queue"},
            "execution_config": {
                "metadata": {
                    "continuity": {
                        "pack_id": "cont-001",
                        "pack_summary": {"pack_id": "cont-001", "display_name": "Hero Pack"},
                    }
                }
            },
            "backend_options": {},
        }
    }

    continuity = extract_continuity_linkage(layered)

    assert continuity["pack_id"] == "cont-001"
    assert continuity["pack_summary"]["display_name"] == "Hero Pack"


def test_build_config_layers_preserves_plan_origin_actors_in_intent_config() -> None:
    layers = build_config_layers(
        intent_config={
            "run_mode": "queue",
            "source": "add_to_queue",
            "plan_origin": {
                "plan_id": "story-001",
                "scene_id": "scene-001",
                "shot_id": "shot-001",
                "actors": [
                    {
                        "name": "Ada",
                        "character_name": "ada",
                        "trigger_phrase": "ada person",
                        "lora_name": "ada",
                        "weight": 0.8,
                    }
                ],
            },
        },
        execution_config={},
    )

    layered = {"config_layers": layers.to_dict()}

    assert layers.intent_config["plan_origin"]["actors"][0]["trigger_phrase"] == "ada person"
    assert extract_plan_origin_linkage(layered)["actors"][0]["lora_name"] == "ada"


def test_canonicalize_intent_config_preserves_nested_adaptive_refinement() -> None:
    layers = build_config_layers(
        intent_config={
            "run_mode": "queue",
            "source": "add_to_queue",
            "adaptive_refinement": {
                "schema": "stablenew.adaptive-refinement.v1",
                "enabled": True,
                "mode": "observe",
                "profile_id": "auto_v1",
            },
        },
        execution_config={},
    )

    assert layers.intent_config["adaptive_refinement"]["enabled"] is True
    assert layers.intent_config["adaptive_refinement"]["mode"] == "observe"


def test_extract_adaptive_refinement_intent_reads_layered_payload() -> None:
    layered = {
        "config_layers": {
            "schema": CONFIG_CONTRACT_SCHEMA_V26,
            "intent_config": {
                "adaptive_refinement": {
                    "schema": "stablenew.adaptive-refinement.v1",
                    "enabled": True,
                    "mode": "observe",
                }
            },
            "execution_config": {},
            "backend_options": {},
        }
    }

    adaptive = extract_adaptive_refinement_intent(layered)

    assert adaptive["enabled"] is True
    assert adaptive["mode"] == "observe"


def test_canonicalize_intent_config_preserves_nested_secondary_motion() -> None:
    layers = build_config_layers(
        intent_config={
            "run_mode": "queue",
            "source": "video",
            "secondary_motion": {
                "schema": "stablenew.secondary-motion.v1",
                "enabled": True,
                "mode": "observe",
                "intent": "micro_sway",
                "regions": ["hair", "fabric"],
                "allow_prompt_bias": False,
                "allow_native_backend": False,
                "record_decisions": True,
                "algorithm_version": "v1",
            },
        },
        execution_config={},
    )

    assert layers.intent_config["secondary_motion"]["enabled"] is True
    assert layers.intent_config["secondary_motion"]["mode"] == "observe"


def test_extract_secondary_motion_intent_reads_layered_payload() -> None:
    layered = {
        "config_layers": {
            "schema": CONFIG_CONTRACT_SCHEMA_V26,
            "intent_config": {
                "secondary_motion": {
                    "schema": "stablenew.secondary-motion.v1",
                    "enabled": True,
                    "mode": "observe",
                    "intent": "micro_sway",
                }
            },
            "execution_config": {},
            "backend_options": {},
        }
    }

    secondary_motion = extract_secondary_motion_intent(layered)

    assert secondary_motion["enabled"] is True
    assert secondary_motion["mode"] == "observe"

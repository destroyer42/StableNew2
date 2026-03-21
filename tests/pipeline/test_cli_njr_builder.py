from __future__ import annotations

from src.pipeline.cli_njr_builder import build_cli_njr


def test_build_cli_njr_preserves_adaptive_refinement_intent() -> None:
    record = build_cli_njr(
        prompt="test prompt",
        batch_size=1,
        run_name="cli-refinement",
        config={
            "txt2img": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 768,
                "height": 1024,
                "model": "model-a.safetensors",
                "negative_prompt": "bad anatomy",
            },
            "intent_config": {
                "adaptive_refinement": {
                    "schema": "stablenew.adaptive-refinement.v1",
                    "enabled": True,
                    "mode": "observe",
                    "profile_id": "auto_v1",
                    "detector_preference": "null",
                    "record_decisions": True,
                    "algorithm_version": "v1",
                }
            },
        },
    )

    assert record.intent_config["source"] == "cli"
    assert record.intent_config["prompt_source"] == "cli"
    assert record.intent_config["adaptive_refinement"]["mode"] == "observe"
    assert record.intent_config["adaptive_refinement"]["enabled"] is True


def test_build_cli_njr_preserves_secondary_motion_intent() -> None:
    record = build_cli_njr(
        prompt="test prompt",
        batch_size=1,
        run_name="cli-motion",
        config={
            "txt2img": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 768,
                "height": 1024,
                "model": "model-a.safetensors",
                "negative_prompt": "bad anatomy",
            },
            "intent_config": {
                "secondary_motion": {
                    "schema": "stablenew.secondary-motion.v1",
                    "enabled": True,
                    "mode": "observe",
                    "intent": "micro_sway",
                    "regions": ["hair", "fabric"],
                    "allow_prompt_bias": False,
                    "allow_native_backend": True,
                    "record_decisions": True,
                    "algorithm_version": "v1",
                }
            },
        },
    )

    assert record.intent_config["source"] == "cli"
    assert record.intent_config["prompt_source"] == "cli"
    assert record.intent_config["secondary_motion"]["mode"] == "observe"
    assert record.intent_config["secondary_motion"]["enabled"] is True

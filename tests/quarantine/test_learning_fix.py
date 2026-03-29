"""Manual verification script for the learning experiment execution fix.

Import-safe under pytest collection.
"""

from __future__ import annotations

import logging
import sys


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("=" * 80)
    print("Learning Experiment Execution Fix Verification")
    print("=" * 80)

    print("\n[TEST 1] Learning controller method verification")
    print("-" * 80)

    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant

    has_get_baseline = hasattr(LearningController, "_get_baseline_config")
    has_stage_flags = hasattr(LearningController, "_build_stage_flags_for_experiment")
    has_variant_overrides = hasattr(LearningController, "_build_variant_overrides")

    print(f"[OK] _get_baseline_config method exists: {has_get_baseline}")
    print(f"[OK] _build_stage_flags_for_experiment method exists: {has_stage_flags}")
    print(f"[OK] _build_variant_overrides method exists: {has_variant_overrides}")

    if not all([has_get_baseline, has_stage_flags, has_variant_overrides]):
        print("[TEST 1] FAILED")
        sys.exit(1)

    print("[TEST 1] PASSED")

    print("\n[TEST 2] Method functionality test")
    print("-" * 80)

    learning_state = LearningState()
    controller = LearningController(
        learning_state=learning_state,
        pipeline_controller=None,
    )

    experiment = LearningExperiment(
        name="Test Experiment",
        stage="txt2img",
        variable_under_test="CFG Scale",
        values=[7.0, 8.0, 9.0],
    )

    stage_flags = controller._build_stage_flags_for_experiment(experiment)
    print(f"[OK] Stage flags for txt2img: {stage_flags}")

    expected_flags = {
        "txt2img": True,
        "img2img": False,
        "adetailer": False,
        "upscale": False,
        "refiner": False,
        "hires": False,
    }
    if stage_flags != expected_flags:
        print(f"[ERR] Stage flags incorrect. Expected {expected_flags}, got {stage_flags}")
        sys.exit(1)

    variant = LearningVariant(
        experiment_id=experiment.name,
        param_value=8.5,
    )
    overrides = controller._build_variant_overrides(variant, experiment)
    print(f"[OK] Variant overrides for CFG Scale=8.5: {overrides}")

    if overrides.get("cfg_scale") != 8.5:
        print(f"[ERR] CFG Scale override incorrect: {overrides.get('cfg_scale')}")
        sys.exit(1)

    print("[TEST 2] PASSED")

    print("\n[TEST 3] PackJobEntry creation test")
    print("-" * 80)

    from src.gui.app_state_v2 import PackJobEntry

    try:
        pack_entry = PackJobEntry(
            pack_id="test_learning_experiment",
            pack_name="Test Learning Experiment",
            config_snapshot={"cfg_scale": 8.5, "steps": 20},
            prompt_text="test prompt",
            negative_prompt_text="",
            stage_flags=stage_flags,
            learning_metadata={
                "learning_enabled": True,
                "learning_experiment_name": "Test",
                "learning_variable": "CFG Scale",
                "learning_variant_value": 8.5,
            },
        )
        print("[OK] PackJobEntry created successfully")
        print(f"  - pack_id: {pack_entry.pack_id}")
        print(f"  - config_snapshot: {pack_entry.config_snapshot}")
        print(f"  - learning_metadata: {pack_entry.learning_metadata}")
        print("[TEST 3] PASSED")
    except Exception as exc:
        print(f"[ERR] PackJobEntry creation failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 80)
    print("Learning Experiment Execution Fix Verification Complete")
    print("=" * 80)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Configuration Validation Test for StableNew Pipeline

This test validates that configuration parameters are correctly passed through
from the GUI configuration to the API payloads without drift or missing values.

IMPORTANT: Run this test whenever you modify the configuration system or pipeline
to ensure parameters are being passed through correctly.

MAINTENANCE REQUIREMENTS:
When adding new configuration parameters, you must update this test:

1. Add the new parameter name to the appropriate expected parameters list:
   - EXPECTED_TXT2IMG_PARAMS (line ~35)
   - EXPECTED_IMG2IMG_PARAMS (line ~55)
   - EXPECTED_UPSCALE_PARAMS (line ~65)

2. If the parameter has special handling or validation requirements,
   update the corresponding validation methods.

3. Run the test to ensure it passes with 90-100% accuracy.

Configuration integrity is CRITICAL - this test prevents silent drift
that could cause unexpected generation results.

Usage:
    python tests/test_config_passthrough.py
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.api.client import SDWebUIClient
from src.pipeline.executor import Pipeline
from src.utils.config import ConfigManager, build_sampler_scheduler_payload
from src.utils.logger import StructuredLogger


class ConfigPassthroughValidator:
    """Validates configuration parameter pass-through in the pipeline"""

    def __init__(self):
        self.captured_payloads = []
        self.config_manager = ConfigManager()

    def capture_api_payload(self, original_method):
        """Decorator to capture API payloads"""

        def wrapper(payload_or_self, *args, **kwargs):
            if hasattr(payload_or_self, "base_url"):  # It's self from SDWebUIClient
                payload = args[0] if args else {}
            else:  # It's the payload directly
                payload = payload_or_self

            self.captured_payloads.append(
                {
                    "method": original_method.__name__,
                    "payload": payload.copy() if isinstance(payload, dict) else payload,
                }
            )

            # Return mock response
            if original_method.__name__ == "txt2img":
                return {"images": ["fake_base64"], "parameters": payload}
            elif original_method.__name__ == "img2img":
                return {"images": ["fake_base64"], "parameters": payload}
            elif original_method.__name__ == "upscale_image":
                return {"image": "fake_upscaled_base64"}

        return wrapper

    def validate_configuration(
        self, test_config: dict[str, Any], test_name: str = "Configuration"
    ) -> dict[str, Any]:
        """Test configuration pass-through with given config"""

        self.captured_payloads = []  # Reset captures

        print(f"\n🔍 Testing {test_name}...")

        # Create mock client and pipeline
        mock_client = SDWebUIClient()

        # Patch API methods to capture payloads
        with (
            patch.object(mock_client, "txt2img", self.capture_api_payload(mock_client.txt2img)),
            patch.object(mock_client, "img2img", self.capture_api_payload(mock_client.img2img)),
            patch.object(
                mock_client, "upscale_image", self.capture_api_payload(mock_client.upscale_image)
            ),
            patch("src.utils.file_io.save_image_from_base64", return_value=True),
            patch("src.utils.file_io.load_image_to_base64", return_value="fake_base64"),
        ):
            # Mock model setting methods
            mock_client.set_model = lambda model: True
            mock_client.set_vae = lambda vae: True

            temp_logger = StructuredLogger()
            pipeline = Pipeline(mock_client, temp_logger)

            try:
                # Run pipeline with test configuration
                with (
                    patch.object(
                        temp_logger, "create_run_directory", return_value=Path("fake_run")
                    ),
                    patch.object(temp_logger, "save_manifest", return_value=None),
                ):
                    result = pipeline.run_full_pipeline(
                        prompt="configuration validation test",
                        config=test_config,
                        run_name="validation_test",
                        batch_size=1,
                    )

                print("  ✅ Pipeline executed successfully")

            except Exception as e:
                print(f"  ❌ Pipeline execution failed: {e}")
                return {"error": str(e), "captured_payloads": self.captured_payloads}

        # Analyze captured payloads
        analysis = self.analyze_payloads(test_config, test_name)
        return {"success": True, "captured_payloads": self.captured_payloads, "analysis": analysis}

    def analyze_payloads(self, original_config: dict[str, Any], test_name: str) -> dict[str, Any]:
        """Analyze captured payloads for configuration drift"""

        analysis = {
            "test_name": test_name,
            "total_api_calls": len(self.captured_payloads),
            "stages_validated": [],
            "overall_success": True,
            "issues": [],
        }

        for payload_info in self.captured_payloads:
            method = payload_info["method"]
            payload = payload_info["payload"]

            # Map API methods to config sections
            config_section = None
            if method == "txt2img":
                config_section = "txt2img"
            elif method == "img2img":
                config_section = "img2img"
            elif method == "upscale_image":
                config_section = "upscale"

            if config_section and config_section in original_config:
                validation = self.validate_stage_parameters(
                    config_section, original_config[config_section], payload
                )
                analysis["stages_validated"].append(validation)

                if not validation["success"]:
                    analysis["overall_success"] = False
                    analysis["issues"].extend(validation["issues"])

        return analysis

    def validate_stage_parameters(
        self, stage: str, expected_config: dict[str, Any], actual_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate that expected config parameters are in the actual payload"""

        # Parameters that are handled separately (not in payload)
        separate_api_params = {"model", "vae", "sd_model_checkpoint"}
        # Parameters that are optional and may not be present
        optional_params = {"styles", "hr_second_pass_steps", "hr_resize_x", "hr_resize_y"}
        # Parameters that are expected to be modified
        modified_ok_params = {"negative_prompt", "prompt"}

        # Copy so we can tweak expectations per stage (e.g., sampler/scheduler normalization)
        expected_config = dict(expected_config)

        # Normalize sampler/scheduler expectations to match helper behavior
        if "sampler_name" in expected_config or "scheduler" in expected_config:
            sampler_payload = build_sampler_scheduler_payload(
                expected_config.get("sampler_name"), expected_config.get("scheduler")
            )
            if sampler_payload:
                expected_config["sampler_name"] = sampler_payload["sampler_name"]
                if "scheduler" in sampler_payload:
                    expected_config["scheduler"] = sampler_payload["scheduler"]
                elif "scheduler" in expected_config:
                    expected_config.pop("scheduler")
            elif "scheduler" in expected_config and not expected_config.get("scheduler"):
                expected_config.pop("scheduler")

        validation = {
            "stage": stage,
            "success": True,
            "expected_params": len(expected_config),
            "validated_params": 0,
            "issues": [],
        }

        print(f"    📋 Validating {stage} stage:")

        # Check each expected parameter
        for param, expected_value in expected_config.items():
            if param in separate_api_params:
                # These are set via separate API calls, not in payload
                validation["validated_params"] += 1
                print(f"      🔄 {param}: {expected_value} (set via separate API call)")
                continue

            if param in optional_params and not expected_value:
                # Optional parameters with empty/false values don't need to be in payload
                validation["validated_params"] += 1
                print(f"      ➖ {param}: empty/disabled (optional)")
                continue

            if param in actual_payload:
                validation["validated_params"] += 1
                actual_value = actual_payload[param]

                # Check for value changes (allow expected modifications)
                if str(expected_value) != str(actual_value):
                    if param in modified_ok_params:
                        print(f"      🔄 {param}: modified as expected")
                    else:
                        validation["success"] = False
                        validation["issues"].append(
                            f"{stage}: {param} changed from {expected_value} to {actual_value}"
                        )
                        print(f"      ⚠️  {param}: {expected_value} → {actual_value}")
                else:
                    print(f"      ✅ {param}: {actual_value}")
            else:
                validation["success"] = False
                validation["issues"].append(f"{stage}: Missing parameter '{param}'")
                print(f"      ❌ Missing: {param}")

        success_rate = (
            (validation["validated_params"] / validation["expected_params"] * 100)
            if validation["expected_params"] > 0
            else 100
        )
        print(
            f"      📊 Success rate: {success_rate:.1f}% ({validation['validated_params']}/{validation['expected_params']})"
        )

        return validation


def run_configuration_validation_tests():
    """Run comprehensive configuration validation tests"""

    print("🚀 StableNew Configuration Pass-Through Validation")
    print("=" * 60)

    validator = ConfigPassthroughValidator()
    results = {}

    # Test 1: Default configuration
    print("\n1️⃣  Testing default configuration...")
    default_config = validator.config_manager.get_default_config()
    results["default"] = validator.validate_configuration(default_config, "Default Configuration")

    # Test 2: Key presets
    key_presets = ["default", "high_quality", "heroes_sdxl"]

    for i, preset_name in enumerate(key_presets, 2):
        preset_file = Path(f"presets/{preset_name}.json")
        if preset_file.exists():
            print(f"\n{i}️⃣  Testing preset: {preset_name}...")
            try:
                preset_config = validator.config_manager.load_preset(preset_name)
                results[f"preset_{preset_name}"] = validator.validate_configuration(
                    preset_config, f"Preset: {preset_name}"
                )
            except Exception as e:
                print(f"    ❌ Failed to load preset {preset_name}: {e}")
                results[f"preset_{preset_name}"] = {"error": str(e)}

    # Summary
    print("\n" + "=" * 60)
    print("📊 VALIDATION SUMMARY")
    print("=" * 60)

    total_tests = len(results)
    passed_tests = sum(
        1
        for result in results.values()
        if result.get("success") and result.get("analysis", {}).get("overall_success", False)
    )

    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

    print(f"Total tests: {total_tests}")
    print(f"Passed tests: {passed_tests}")
    print(f"Success rate: {success_rate:.1f}%")

    if success_rate >= 90:
        print("✅ CONFIGURATION VALIDATION PASSED!")
        print("   All critical parameters are passing through correctly.")
    elif success_rate >= 70:
        print("⚠️  CONFIGURATION VALIDATION PARTIALLY PASSED")
        print("   Most parameters are working, but some issues detected.")
    else:
        print("❌ CONFIGURATION VALIDATION FAILED")
        print("   Significant parameter pass-through issues detected.")

    # Show specific issues
    all_issues = []
    for test_name, result in results.items():
        if result.get("analysis", {}).get("issues"):
            all_issues.extend(result["analysis"]["issues"])

    if all_issues:
        print("\n🔍 Issues detected:")
        for issue in all_issues:
            print(f"   • {issue}")

    return {
        "results": results,
        "summary": {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "success_rate": success_rate,
            "issues": all_issues,
        },
    }


def test_sampler_scheduler_payload_with_explicit_scheduler():
    """Sampler payload should append explicit scheduler when provided."""
    payload = build_sampler_scheduler_payload("DPM++ 2M", "Karras")
    assert payload["sampler_name"] == "DPM++ 2M Karras"
    assert payload["scheduler"] == "Karras"


def test_sampler_scheduler_payload_without_scheduler():
    """Sampler payload should omit scheduler when input is empty/automatic."""
    for raw in (None, "", "None", "none", "Automatic", "automatic"):
        payload = build_sampler_scheduler_payload("DPM++ 2M", raw)
        assert payload["sampler_name"] == "DPM++ 2M"
        assert "scheduler" not in payload


if __name__ == "__main__":
    run_configuration_validation_tests()

"""
Test scheduler parameter handling in Pipeline executor.

Covers:
- _parse_sampler_config() with various scheduler inputs
- Empty string vs None vs valid scheduler values
- Scheduler extraction from sampler name
- Regression prevention for scheduler defaulting to 'Automatic'
"""

from __future__ import annotations

from src.api.client import SDWebUIClient
from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger


class TestSchedulerParsing:
    """Test suite for scheduler parameter parsing in executor."""

    def setup_method(self):
        """Setup for each test."""
        # Create a pipeline with a mock client
        self.client = SDWebUIClient(base_url="http://127.0.0.1:7860")
        self.pipeline = Pipeline(self.client, StructuredLogger())

    def test_scheduler_explicit_value(self):
        """Test that explicit scheduler value is included in payload."""
        config = {"sampler_name": "Euler a", "scheduler": "Karras"}

        result = self.pipeline._parse_sampler_config(config)

        assert result["sampler_name"] == "Euler a"
        assert result["scheduler"] == "Karras"

    def test_scheduler_empty_string_not_included(self):
        """Test that empty string scheduler is NOT included (treated as no value)."""
        config = {"sampler_name": "DPM++ 2M", "scheduler": ""}

        result = self.pipeline._parse_sampler_config(config)

        assert result["sampler_name"] == "DPM++ 2M"
        assert "scheduler" not in result  # Empty string should be excluded

    def test_scheduler_none_not_included(self):
        """Test that None scheduler is not included."""
        config = {"sampler_name": "Euler a", "scheduler": None}

        result = self.pipeline._parse_sampler_config(config)

        assert result["sampler_name"] == "Euler a"
        assert "scheduler" not in result

    def test_scheduler_whitespace_only_not_included(self):
        """Test that whitespace-only scheduler is not included."""
        config = {"sampler_name": "DDIM", "scheduler": "   "}

        result = self.pipeline._parse_sampler_config(config)

        assert result["sampler_name"] == "DDIM"
        assert "scheduler" not in result

    def test_scheduler_extracted_from_sampler_name(self):
        """Test scheduler extraction when embedded in sampler name."""
        config = {"sampler_name": "DPM++ 2M Karras"}

        result = self.pipeline._parse_sampler_config(config)

        # Scheduler should be extracted from sampler name
        assert result["sampler_name"] == "DPM++ 2M"
        assert result["scheduler"] == "Karras"

    def test_scheduler_explicit_overrides_extraction(self):
        """Test that explicit scheduler value takes precedence over sampler name."""
        config = {"sampler_name": "DPM++ 2M Karras", "scheduler": "Exponential"}

        result = self.pipeline._parse_sampler_config(config)

        # Explicit scheduler should win
        assert result["sampler_name"] == "DPM++ 2M Karras"
        assert result["scheduler"] == "Exponential"

    def test_scheduler_all_valid_types(self):
        """Test all valid scheduler types are preserved."""
        schedulers = ["Karras", "Exponential", "Polyexponential", "SGM Uniform"]

        for scheduler in schedulers:
            config = {"sampler_name": "Euler a", "scheduler": scheduler}
            result = self.pipeline._parse_sampler_config(config)

            assert result["scheduler"] == scheduler, f"Failed for {scheduler}"

    def test_scheduler_case_preserved(self):
        """Test that scheduler casing is preserved."""
        config = {"sampler_name": "Euler a", "scheduler": "Karras"}

        result = self.pipeline._parse_sampler_config(config)

        # Should preserve exact casing
        assert result["scheduler"] == "Karras"
        assert result["scheduler"] != "karras"

    def test_no_scheduler_no_key_in_result(self):
        """Test that missing scheduler doesn't add key to result."""
        config = {"sampler_name": "Euler a"}

        result = self.pipeline._parse_sampler_config(config)

        assert result["sampler_name"] == "Euler a"
        assert "scheduler" not in result

    def test_sampler_name_defaults_to_euler_a(self):
        """Test that missing sampler_name defaults to Euler a."""
        config = {"scheduler": "Karras"}

        result = self.pipeline._parse_sampler_config(config)

        assert result["sampler_name"] == "Euler a"
        assert result["scheduler"] == "Karras"


class TestSchedulerRegression:
    """Regression tests for scheduler parameter handling."""

    def setup_method(self):
        """Setup for each test."""
        self.client = SDWebUIClient(base_url="http://127.0.0.1:7860")
        self.pipeline = Pipeline(self.client, StructuredLogger())

    def test_regression_empty_string_scheduler_was_ignored(self):
        """
        REGRESSION TEST: Empty string scheduler should not be included.

        Background: GUI sends scheduler as empty string "" when no scheduler selected.
        Previous code did: `scheduler_value = config.get("scheduler")`
        Then: `if scheduler_value:` was False for empty string
        So scheduler wasn't added to payload, defaulting to 'Automatic'.

        Fix: Now strips and checks properly: `(config.get("scheduler") or "").strip()`
        """
        # Simulate GUI sending empty string
        config = {"sampler_name": "DPM++ 2M", "scheduler": ""}

        result = self.pipeline._parse_sampler_config(config)

        # Empty string should NOT be in payload
        assert "scheduler" not in result

        # Now test with actual value
        config["scheduler"] = "Karras"
        result = self.pipeline._parse_sampler_config(config)

        # Real value should be included
        assert result["scheduler"] == "Karras"

    def test_regression_scheduler_from_gui_included(self):
        """
        REGRESSION TEST: Scheduler from GUI should be passed to WebUI.

        Background: User reported scheduler (like 'Karras') was defaulting to
        'Automatic' in WebUI. This ensures GUI-selected scheduler is preserved.
        """
        # Simulate what GUI sends (from advanced_txt2img_stage_card_v2.py line 728)
        config = {
            "sampler_name": "DPM++ 2M",
            "scheduler": "Karras",  # User selected in dropdown
            "steps": 20,
            "cfg_scale": 7.0,
        }

        result = self.pipeline._parse_sampler_config(config)

        # Scheduler MUST be in result for WebUI
        assert "scheduler" in result
        assert result["scheduler"] == "Karras"

    def test_regression_multiple_scheduler_scenarios(self):
        """
        REGRESSION TEST: Comprehensive scenarios that previously failed.
        """
        test_cases = [
            # (config, expected_sampler, expected_scheduler_present, expected_scheduler_value)
            (
                {"sampler_name": "Euler a", "scheduler": "Karras"},
                "Euler a",
                True,
                "Karras",
            ),
            ({"sampler_name": "Euler a", "scheduler": ""}, "Euler a", False, None),
            ({"sampler_name": "Euler a", "scheduler": None}, "Euler a", False, None),
            ({"sampler_name": "Euler a"}, "Euler a", False, None),
            (
                {"sampler_name": "DPM++ 2M Karras"},
                "DPM++ 2M",
                True,
                "Karras",
            ),  # Extract from name
            (
                {"sampler_name": "DPM++ 2M", "scheduler": "Exponential"},
                "DPM++ 2M",
                True,
                "Exponential",
            ),
        ]

        for config, expected_sampler, should_have_scheduler, expected_scheduler in test_cases:
            result = self.pipeline._parse_sampler_config(config)

            assert (
                result["sampler_name"] == expected_sampler
            ), f"Failed sampler for config: {config}"

            if should_have_scheduler:
                assert "scheduler" in result, f"Missing scheduler for config: {config}"
                assert (
                    result["scheduler"] == expected_scheduler
                ), f"Wrong scheduler for config: {config}"
            else:
                assert (
                    "scheduler" not in result
                ), f"Unexpected scheduler for config: {config}"

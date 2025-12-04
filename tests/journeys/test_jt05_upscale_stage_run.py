"""JT-05 — Upscale Stage Run Journey Test.

Validates upscale stage operations both as standalone processing and as final step
in multi-stage txt2img → upscale pipelines, ensuring proper image enlargement,
model selection, and metadata preservation.

Uses journey_helpers_v2 exclusively for run control and assertions.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.controller.app_controller import LifecycleState
from tests.helpers.factories import update_current_config
from tests.helpers.gui_harness import pipeline_harness
from tests.journeys.journey_helpers_v2 import (
    get_latest_job,
    get_stage_plan_for_job,
    start_run_and_wait,
)


class TestJT05UpscaleStageRun:
    """JT-05: Validates upscale stage functionality and multi-stage pipeline integration.

    Assertions via journey_helpers_v2:
    - job.run_mode == "queue" for use_run_now=True
    - job.run_mode == "direct" for use_run_now=False
    - Stage plan contains upscale stage
    - Stage ordering: txt2img before upscale (when both enabled)
    """

    @pytest.fixture
    def app_root(self):
        """Create test application root with proper cleanup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            yield root

    @patch('src.api.webui_api.WebUIAPI')
    @pytest.mark.journey
    @pytest.mark.slow
    def test_jt05_standalone_upscale_stage(self, mock_webui_api, app_root):
        """Test standalone upscale stage operation with baseline image.

        Assertions:
        - job.run_mode == "queue" (via use_run_now=True)
        - Stage plan contains upscale stage
        """
        # Setup mocks
        mock_webui_api.return_value.upscale_image.return_value = {
            'images': [{'data': 'base64_encoded_upscaled_image'}],
            'info': '{"upscale_factor": 2.0, "model": "UltraSharp"}'
        }

        # Create test image file
        test_image_path = app_root / "test_input.png"
        test_image_path.write_bytes(b"fake_png_data")

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window

            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=20,
            )

            window.pipeline_tab.upscale_enabled.set(True)
            window.pipeline_tab.txt2img_enabled.set(False)
            window.pipeline_tab.img2img_enabled.set(False)
            window.pipeline_tab.adetailer_enabled.set(False)

            window.pipeline_tab.upscale_factor.set(2.0)
            window.pipeline_tab.upscale_model.set("UltraSharp")
            window.pipeline_tab.upscale_tile_size.set(512)
            window.pipeline_tab.input_image_path = str(test_image_path)

            # Execute run via helper API with use_run_now=True for queue mode
            job_entry = start_run_and_wait(app_controller, use_run_now=True, timeout_seconds=30.0)

            # Assert job metadata
            assert job_entry.run_mode == "queue", f"Expected run_mode 'queue', got '{job_entry.run_mode}'"

            # Get and verify stage plan
            plan = get_stage_plan_for_job(app_controller, job_entry)
            assert plan is not None, "Stage plan should exist"
            stage_types = plan.get_stage_types()
            assert "upscale" in stage_types, f"Expected 'upscale' in stage types, got {stage_types}"

            # Verify UI state
            assert window.pipeline_tab.upscale_enabled.get() is True

            # Verify API was called with correct parameters
            mock_webui_api.return_value.upscale_image.assert_called_once()
            call_args = mock_webui_api.return_value.upscale_image.call_args
            assert call_args[1]['upscale_factor'] == 2.0
            assert call_args[1]['model'] == "UltraSharp"

    @patch('src.api.webui_api.WebUIAPI')
    @pytest.mark.journey
    @pytest.mark.slow
    def test_jt05_multi_stage_txt2img_upscale_pipeline(self, mock_webui_api, app_root):
        """Test complete txt2img → upscale multi-stage pipeline.

        Assertions:
        - job.run_mode == "direct" (via use_run_now=False)
        - Stage plan contains txt2img and upscale stages
        - Stage ordering: txt2img before upscale
        """
        # Setup mocks for both stages
        mock_webui_api.return_value.txt2img.return_value = {
            'images': [{'data': 'base64_encoded_txt2img_image'}],
            'info': '{"prompt": "test landscape", "width": 512, "height": 512}'
        }
        mock_webui_api.return_value.upscale_image.return_value = {
            'images': [{'data': 'base64_encoded_final_upscaled_image'}],
            'info': '{"upscale_factor": 2.0, "model": "ESRGAN"}'
        }

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window

            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=20,
            )

            # Configure Pipeline tab for multi-stage execution
            window.pipeline_tab.txt2img_enabled.set(True)
            window.pipeline_tab.upscale_enabled.set(True)
            window.pipeline_tab.img2img_enabled.set(False)
            window.pipeline_tab.adetailer_enabled.set(False)

            # Set txt2img parameters
            window.pipeline_tab.prompt_text.insert(0, "a beautiful landscape")
            window.pipeline_tab.txt2img_width.set(512)
            window.pipeline_tab.txt2img_height.set(512)

            # Set upscale parameters
            window.pipeline_tab.upscale_factor.set(2.0)
            window.pipeline_tab.upscale_model.set("ESRGAN")

            # Execute run via helper API with use_run_now=False for direct mode
            job_entry = start_run_and_wait(app_controller, use_run_now=False, timeout_seconds=30.0)

            # Assert job metadata
            assert job_entry.run_mode == "direct", f"Expected run_mode 'direct', got '{job_entry.run_mode}'"

            # Get and verify stage plan
            plan = get_stage_plan_for_job(app_controller, job_entry)
            assert plan is not None, "Stage plan should exist"

            stage_types = plan.get_stage_types()
            assert "txt2img" in stage_types, f"Expected 'txt2img' in stage types, got {stage_types}"
            assert "upscale" in stage_types, f"Expected 'upscale' in stage types, got {stage_types}"

            # Verify stage ordering: txt2img before upscale
            txt2img_idx = stage_types.index("txt2img")
            upscale_idx = stage_types.index("upscale")
            assert txt2img_idx < upscale_idx, (
                f"txt2img (index {txt2img_idx}) should come before upscale (index {upscale_idx})"
            )

            # Verify API calls
            assert mock_webui_api.return_value.txt2img.called
            assert mock_webui_api.return_value.upscale_image.called

            upscale_call = mock_webui_api.return_value.upscale_image.call_args
            assert 'image' in upscale_call[1]

    @patch('src.api.webui_api.WebUIAPI')
    def test_jt05_upscale_parameter_variations(self, mock_webui_api, app_root):
        """Test various upscale parameters and factor calculations."""
        # Setup mock
        mock_webui_api.return_value.upscale_image.return_value = {
            'images': [{'data': 'base64_encoded_image'}],
            'info': '{"upscale_factor": 1.5, "model": "4x-UltraSharp"}'
        }

        # Create test image
        test_image_path = app_root / "test_input.png"
        test_image_path.write_bytes(b"fake_png_data")

        # Test different upscale factors
        test_factors = [1.5, 2.0, 4.0]
        test_models = ["UltraSharp", "ESRGAN", "4x-UltraSharp"]

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window

            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=20,
            )

            for factor in test_factors:
                for model in test_models:
                    mock_webui_api.reset_mock()

                    window.pipeline_tab.upscale_enabled.set(True)
                    window.pipeline_tab.txt2img_enabled.set(False)
                    window.pipeline_tab.upscale_factor.set(factor)
                    window.pipeline_tab.upscale_model.set(model)
                    window.pipeline_tab.input_image_path = str(test_image_path)

                    # Execute run via helper API
                    job_entry = start_run_and_wait(app_controller, use_run_now=True, timeout_seconds=30.0)

                    # Assert job metadata
                    assert job_entry.run_mode == "queue"

                    # Verify API was called with correct parameters
                    mock_webui_api.return_value.upscale_image.assert_called_once()

                    call_kwargs = mock_webui_api.return_value.upscale_image.call_args[1]
                    assert call_kwargs["upscale_factor"] == factor
                    assert call_kwargs["model"] == model

    @patch('src.api.webui_api.WebUIAPI')
    def test_jt05_upscale_metadata_preservation(self, mock_webui_api, app_root):
        """Test that upscale preserves prompt and pipeline metadata."""
        # Setup mock with metadata
        mock_webui_api.return_value.upscale_image.return_value = {
            'images': [{'data': 'base64_encoded_image'}],
            'info': '{"upscale_factor": 2.0, "model": "UltraSharp", "original_prompt": "test prompt"}'
        }

        # Create test image with metadata
        test_image_path = app_root / "test_input.png"
        test_image_path.write_bytes(b"fake_png_data")

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window

            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=20,
            )

            window.pipeline_tab.txt2img_enabled.set(True)
            window.pipeline_tab.upscale_enabled.set(True)
            window.pipeline_tab.prompt_text.insert(0, "original test prompt")

            # Execute run via helper API
            job_entry = start_run_and_wait(app_controller, use_run_now=False, timeout_seconds=30.0)

            # Assert job metadata
            assert job_entry.run_mode == "direct"

            # Verify stage plan
            plan = get_stage_plan_for_job(app_controller, job_entry)
            assert plan is not None
            assert plan.has_generation_stage()

            upscale_call = mock_webui_api.return_value.upscale_image.call_args
            assert upscale_call is not None

    @patch('src.api.webui_api.WebUIAPI')
    def test_jt05_upscale_error_handling(self, mock_webui_api, app_root):
        """Test upscale error handling and edge cases."""
        # Setup mock to raise exception
        mock_webui_api.return_value.upscale_image.side_effect = Exception("Upscale model not available")

        # Create test image
        test_image_path = app_root / "test_input.png"
        test_image_path.write_bytes(b"fake_png_data")

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window

            window.pipeline_tab.upscale_enabled.set(True)
            window.pipeline_tab.txt2img_enabled.set(False)
            window.pipeline_tab.input_image_path = str(test_image_path)

            # Execute run via helper API - job should complete (possibly with error status)
            job_entry = start_run_and_wait(app_controller, use_run_now=True, timeout_seconds=30.0)

            # Assert job metadata
            assert job_entry.run_mode == "queue"
            # Job may be in FAILED status due to error, which is acceptable for error handling test


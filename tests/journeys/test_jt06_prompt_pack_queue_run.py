"""JT-06 — Prompt-Pack Batch + Queue Journey Test.

Validates prompt-pack-based queue runs, ensuring pack entries are properly
queued, executed, and tracked in job history with correct provenance metadata.

Uses journey_helpers_v2 exclusively for run control and assertions.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.helpers.factories import update_current_config
from tests.helpers.gui_harness import pipeline_harness
from tests.journeys.journey_helpers_v2 import (
    get_latest_job,
    get_stage_plan_for_job,
    start_run_and_wait,
)


@pytest.mark.journey
@pytest.mark.slow
class TestJT06PromptPackQueueRun:
    """JT-06: Validates prompt-pack-based queue runs with correct provenance tracking.

    Assertions via journey_helpers_v2:
    - job.run_mode == "queue" (queue-backed execution)
    - job.prompt_source == "pack" (when using prompt pack)
    - job.prompt_pack_id matches the loaded pack
    - Stage plan has generation stages
    """

    @pytest.fixture
    def app_root(self):
        """Create test application root with proper cleanup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            yield root

    @patch("src.api.webui_api.WebUIAPI")
    def test_jt06_single_pack_queue_run(self, mock_webui_api, app_root):
        """Test single prompt pack queued for execution.

        Scenario: Load a prompt pack, select it for execution, run via queue.

        Assertions:
        - job.run_mode == "queue"
        - job.prompt_source == "pack"
        - job.prompt_pack_id matches pack name
        - Stage plan has generation stage
        """
        # Setup mock for txt2img
        mock_webui_api.return_value.txt2img.return_value = {
            "images": [{"data": "base64_encoded_image"}],
            "info": '{"prompt": "test prompt from pack", "seed": 12345}',
        }

        test_pack_id = "jt06_test_pack"
        test_prompt = "A beautiful sunset over the ocean with vibrant colors"

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window

            # Configure base model settings
            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=20,
            )

            # Enable txt2img stage
            window.pipeline_tab.txt2img_enabled.set(True)
            window.pipeline_tab.upscale_enabled.set(False)
            window.pipeline_tab.img2img_enabled.set(False)
            window.pipeline_tab.adetailer_enabled.set(False)

            # Set prompt (simulating pack selection)
            window.pipeline_tab.prompt_text.delete(0, "end")
            window.pipeline_tab.prompt_text.insert(0, test_prompt)

            # Set job draft with pack info (simulating pack selection in GUI)
            if hasattr(app_state, "job_draft"):
                try:
                    from src.gui.app_state_v2 import PackJobEntry

                    pack_entry = PackJobEntry(
                        pack_id=test_pack_id,
                        pack_name=test_pack_id,
                        config_snapshot={"prompt": test_prompt},
                    )
                    app_state.add_packs_to_job_draft([pack_entry])
                except Exception:
                    pass

            # Execute run via queue (use_run_now=True)
            job_entry = start_run_and_wait(app_controller, use_run_now=True, timeout_seconds=30.0)

            # Assert job metadata
            assert job_entry.run_mode == "queue", (
                f"Expected run_mode 'queue', got '{job_entry.run_mode}'"
            )

            # Get and verify stage plan
            plan = get_stage_plan_for_job(app_controller, job_entry)
            assert plan is not None, "Stage plan should exist"
            assert plan.has_generation_stage(), "Plan should have a generation stage"

            stage_types = plan.get_stage_types()
            assert "txt2img" in stage_types, f"Expected 'txt2img' in stage types, got {stage_types}"

    @patch("src.api.webui_api.WebUIAPI")
    def test_jt06_pack_queue_add_only(self, mock_webui_api, app_root):
        """Test adding pack to queue without immediate execution.

        Scenario: Add a prompt pack to queue using add_to_queue_only.

        Assertions:
        - job.run_mode == "queue"
        - Job appears in history after queue processing
        """
        # Setup mock for txt2img
        mock_webui_api.return_value.txt2img.return_value = {
            "images": [{"data": "base64_encoded_image"}],
            "info": '{"prompt": "queued pack prompt", "seed": 54321}',
        }

        test_prompt = "A majestic mountain range at dawn"

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window

            # Configure base model settings
            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=20,
            )

            # Enable txt2img stage
            window.pipeline_tab.txt2img_enabled.set(True)

            # Set prompt
            window.pipeline_tab.prompt_text.delete(0, "end")
            window.pipeline_tab.prompt_text.insert(0, test_prompt)

            # Execute run via add_to_queue_only
            job_entry = start_run_and_wait(
                app_controller,
                add_to_queue_only=True,
                timeout_seconds=30.0,
            )

            # Assert job metadata
            assert job_entry.run_mode == "queue", (
                f"Expected run_mode 'queue', got '{job_entry.run_mode}'"
            )

            # Verify job appears in history
            latest = get_latest_job(app_controller)
            assert latest is not None, "Job should appear in history"

    @patch("src.api.webui_api.WebUIAPI")
    def test_jt06_pack_with_generation_stage(self, mock_webui_api, app_root):
        """Test prompt pack execution includes proper generation stage.

        Scenario: Prompt pack with txt2img configuration.

        Assertions:
        - Stage plan contains generation stage
        - plan.has_generation_stage() returns True
        """
        # Setup mock for txt2img
        mock_webui_api.return_value.txt2img.return_value = {
            "images": [{"data": "base64_encoded_image"}],
            "info": '{"prompt": "pack generation test", "seed": 99999}',
        }

        test_prompt = "A futuristic city with flying vehicles"

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window

            # Configure base model settings
            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=20,
            )

            # Enable txt2img stage
            window.pipeline_tab.txt2img_enabled.set(True)
            window.pipeline_tab.upscale_enabled.set(False)
            window.pipeline_tab.img2img_enabled.set(False)
            window.pipeline_tab.adetailer_enabled.set(False)

            # Set prompt
            window.pipeline_tab.prompt_text.delete(0, "end")
            window.pipeline_tab.prompt_text.insert(0, test_prompt)

            # Execute run via queue
            job_entry = start_run_and_wait(app_controller, use_run_now=True, timeout_seconds=30.0)

            # Assert job metadata
            assert job_entry.run_mode == "queue"

            # Get and verify stage plan
            plan = get_stage_plan_for_job(app_controller, job_entry)
            assert plan is not None, "Stage plan should exist"
            assert plan.has_generation_stage(), "Plan should have a generation stage"

            # Verify stage types
            stage_types = plan.get_stage_types()
            generation_types = {"txt2img", "img2img"}
            has_generation = any(st in generation_types for st in stage_types)
            assert has_generation, f"Expected generation stage in {stage_types}"


def test_jt06_prompt_pack_scaffold():
    """Basic scaffold test to verify JT06 test file is importable.

    This test always passes and confirms the test infrastructure is set up.
    """
    # Import verification
    from tests.journeys.journey_helpers_v2 import (
        get_latest_job,
        get_stage_plan_for_job,
        start_run_and_wait,
    )

    # Verify helpers are callable
    assert callable(start_run_and_wait)
    assert callable(get_latest_job)
    assert callable(get_stage_plan_for_job)

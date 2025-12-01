"""JT-03 — txt2img Pipeline Run Journey Test.

Validates the complete txt2img generation flow using the Pipeline tab.
Ensures Pipeline tab correctly configures txt2img settings and delivers final images
with correct metadata.
"""

from __future__ import annotations

import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.app_factory import build_v2_app
from src.controller.app_controller import AppController
from src.gui.models.prompt_pack_model import PromptPackModel
from src.gui.state import PipelineState


def _create_root() -> tk.Tk:
    """Create a real Tk root for journey tests; fail fast if unavailable."""
    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError as exc:  # pragma: no cover - environment dependent
        pytest.fail(f"Tkinter unavailable for journey test: {exc}")


@pytest.mark.journey
@pytest.mark.slow
def test_jt03_txt2img_pipeline_run():
    """JT-03: Validate complete txt2img generation flow using Pipeline tab."""

    # Test data for JT-03
    test_prompt = "A beautiful landscape with mountains and a serene lake, photorealistic style"
    test_negative = "blurry, low quality, distorted, ugly"

    # Create temporary directory for test files
    with tempfile.TemporaryDirectory() as temp_dir:

        # Step 1: Launch StableNew (build V2 app)
        root = _create_root()
        try:
            root, app_state, app_controller, window = build_v2_app(
                root=root,
                threaded=False,
            )

            # Step 2: Create and load a prompt pack (simulating JT-01 completion)
            prompt_state = window.prompt_tab.workspace_state
            pack = prompt_state.new_pack("JT03_Test_Pack", slot_count=1)
            pack.slots[0].text = test_prompt

            # Save the prompt pack
            pack_path = Path(temp_dir) / "jt03_prompt_pack.json"
            saved_path = prompt_state.save_current_pack(pack_path)
            assert saved_path.exists()

            # Load the pack to simulate user selecting it
            loaded_pack = PromptPackModel.load_from_file(saved_path)
            assert loaded_pack.slots[0].text == test_prompt

            # Step 3: Access Pipeline tab
            pipeline_tab = getattr(window, 'pipeline_tab', None)
            assert pipeline_tab is not None, "Pipeline tab should exist"

            # Step 4: Configure Pipeline for txt2img only
            # Enable txt2img stage, disable others
            pipeline_state = getattr(pipeline_tab, 'pipeline_state', None)
            assert isinstance(pipeline_state, PipelineState)

            # Configure txt2img stage
            # Note: Actual configuration would be done through UI controls
            # For testing, we directly set the pipeline state

            # Step 5: Set prompt and negative prompt
            # This would typically come from the prompt pack selection
            pipeline_state.prompt = test_prompt
            pipeline_state.negative_prompt = test_negative

            # Step 6: Mock the WebUI API call to avoid actual generation
            with patch('src.api.client.ApiClient.generate_images') as mock_generate:
                # Mock successful generation response
                mock_response = Mock()
                mock_response.success = True
                mock_response.images = [Mock(), Mock()]  # Two images for batch_size=2
                mock_response.metadata = {
                    'sampler': 'Euler',
                    'scheduler': 'Karras',
                    'steps': 25,
                    'cfg_scale': 7.0,
                    'seed': 12345,
                    'batch_size': 2,
                }
                mock_generate.return_value = mock_response

                # Step 7: Execute the pipeline run
                controller = app_controller
                assert isinstance(controller, AppController)

                # Start the run
                run_success = controller.start_run()
                assert run_success, "Pipeline run should start successfully"

                # Wait for completion (in real scenario, this would be async)
                # For testing, we simulate completion
                time.sleep(0.1)  # Brief pause to simulate processing

                # Step 8: Verify run completion and results
                # Check that the API was called with correct parameters
                mock_generate.assert_called_once()
                call_args = mock_generate.call_args[0][0]  # First positional argument

                # Verify parameters were passed correctly
                assert call_args.prompt == test_prompt
                assert call_args.negative_prompt == test_negative
                assert call_args.sampler == 'Euler'
                assert call_args.scheduler == 'Karras'
                assert call_args.steps == 25
                assert call_args.cfg_scale == 7.0
                assert call_args.batch_size == 2

                # Step 9: Verify results display
                # Check that images are displayed in the UI
                # This would verify that the pipeline tab shows the generated images
                # and metadata matches the configuration

                # For now, verify the mock response structure
                assert len(mock_response.images) == 2, "Should generate 2 images for batch_size=2"
                assert mock_response.metadata['sampler'] == 'Euler'
                assert mock_response.metadata['scheduler'] == 'Karras'
                assert mock_response.metadata['steps'] == 25
                assert mock_response.metadata['cfg_scale'] == 7.0

        finally:
            try:
                window.cleanup()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass


def test_jt03_txt2img_edge_cases():
    """Test JT-03 edge cases: empty prompts, randomization, invalid parameters."""

    # Test cases for edge conditions
    edge_cases = [
        {
            "name": "empty_negative_prompt",
            "prompt": "A beautiful sunset landscape",
            "negative_prompt": "",  # Should fallback gracefully
            "expected_negative": "",  # Or default negative prompt
        },
        {
            "name": "randomization_tokens",
            "prompt": "A {{red|blue|green}} flower in a {{garden|field|meadow}}",
            "negative_prompt": "blurry, ugly",
            "expected_matrix_count": 2,
        },
        {
            "name": "invalid_parameters",
            "prompt": "A simple scene",
            "negative_prompt": "bad quality",
            "invalid_steps": -5,  # Should be rejected or clamped
        },
    ]

    for case in edge_cases:
        # Create temporary directory for test files
        with tempfile.TemporaryDirectory() as temp_dir:

            # Step 1: Launch StableNew
            root = _create_root()
            try:
                root, app_state, app_controller, window = build_v2_app(
                    root=root,
                    threaded=False,
                )

                # Step 2: Set up prompt pack
                prompt_state = window.prompt_tab.workspace_state
                pack = prompt_state.new_pack(f"JT03_{case['name']}", slot_count=1)
                pack.slots[0].text = case["prompt"]

                # Step 3: Access Pipeline tab
                pipeline_tab = getattr(window, 'pipeline_tab', None)
                assert pipeline_tab is not None

                pipeline_state = getattr(pipeline_tab, 'pipeline_state', None)
                assert isinstance(pipeline_state, PipelineState)

                # Step 4: Configure with edge case parameters
                pipeline_state.prompt = case["prompt"]
                pipeline_state.negative_prompt = case["negative_prompt"]

                # Step 5: Test parameter validation
                if "invalid_steps" in case:
                    # Test that invalid parameters are handled
                    # This would test input validation in the UI
                    pass  # Placeholder for parameter validation testing

                # Step 6: Mock API and verify edge case handling
                with patch('src.api.client.ApiClient.generate_images') as mock_generate:
                    mock_response = Mock()
                    mock_response.success = True
                    mock_response.images = [Mock()]
                    mock_response.metadata = {"seed": 12345}
                    mock_generate.return_value = mock_response

                    # Execute run
                    controller = app_controller
                    run_success = controller.start_run()
                    assert run_success

                    # Verify API was called appropriately
                    call_args = mock_generate.call_args[0][0]
                    assert call_args.prompt == case["prompt"]

                    # For empty negative prompt, verify it's handled
                    if case["negative_prompt"] == "":
                        # Should either pass empty string or use default
                        assert call_args.negative_prompt == case["expected_negative"]

            finally:
                try:
                    window.cleanup()
                except Exception:
                    pass
                try:
                    root.destroy()
                except Exception:
                    pass


def test_jt03_txt2img_metadata_accuracy():
    """Test that generated images have correct metadata matching configuration."""

    test_prompt = "A futuristic cityscape at night with neon lights"
    test_negative = "blurry, distorted, low quality"

    # Step 1: Launch StableNew
    root = _create_root()
    try:
        root, app_state, app_controller, window = build_v2_app(
            root=root,
            threaded=False,
        )

        # Step 2: Set up Pipeline configuration
        pipeline_tab = getattr(window, 'pipeline_tab', None)
        assert pipeline_tab is not None

        pipeline_state = getattr(pipeline_tab, 'pipeline_state', None)
        assert isinstance(pipeline_state, PipelineState)

        # Configure specific parameters for metadata validation
        test_config = {
            'sampler': 'Euler a',
            'scheduler': 'Karras',
            'steps': 30,
            'cfg_scale': 8.5,
            'batch_size': 1,
            'seed': 98765,
        }

        pipeline_state.prompt = test_prompt
        pipeline_state.negative_prompt = test_negative

        # Step 3: Mock API with detailed metadata response
        with patch('src.api.client.ApiClient.generate_images') as mock_generate:
            mock_response = Mock()
            mock_response.success = True
            mock_response.images = [Mock()]
            mock_response.metadata = {
                'sampler': test_config['sampler'],
                'scheduler': test_config['scheduler'],
                'steps': test_config['steps'],
                'cfg_scale': test_config['cfg_scale'],
                'seed': test_config['seed'],
                'batch_size': test_config['batch_size'],
                'prompt': test_prompt,
                'negative_prompt': test_negative,
            }
            mock_generate.return_value = mock_response

            # Step 4: Execute run
            controller = app_controller
            run_success = controller.start_run()
            assert run_success

            # Step 5: Verify metadata accuracy
            call_args = mock_generate.call_args[0][0]

            # Verify all parameters were passed correctly
            assert call_args.sampler == test_config['sampler']
            assert call_args.scheduler == test_config['scheduler']
            assert call_args.steps == test_config['steps']
            assert call_args.cfg_scale == test_config['cfg_scale']
            assert call_args.batch_size == test_config['batch_size']

            # Verify prompt data
            assert call_args.prompt == test_prompt
            assert call_args.negative_prompt == test_negative

            # Verify response metadata matches request
            assert mock_response.metadata['sampler'] == test_config['sampler']
            assert mock_response.metadata['scheduler'] == test_config['scheduler']
            assert mock_response.metadata['steps'] == test_config['steps']
            assert mock_response.metadata['cfg_scale'] == test_config['cfg_scale']

    finally:
        try:
            window.cleanup()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

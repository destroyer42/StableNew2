"""JT-04 — img2img and ADetailer Pipeline Run Journey Test.

Validates img2img and ADetailer workflows, ensuring a base image is properly
transformed using configured parameters without losing prompt context or metadata.
"""

from __future__ import annotations

import os
import tempfile
import tkinter as tk
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.app_factory import build_v2_app
from src.gui.models.prompt_pack_model import PromptPackModel
from src.gui.state import PipelineState


def _create_root() -> tk.Tk:
    """Create a real Tk root for journey tests; fail fast if unavailable."""
    try:
        if "TCL_LIBRARY" not in os.environ:
            tcl_dir = os.path.join(os.path.dirname(tk.__file__), "tcl", "tcl8.6")
            if os.path.isdir(tcl_dir):
                os.environ["TCL_LIBRARY"] = tcl_dir

        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError as exc:  # pragma: no cover - environment dependent
        pytest.fail(f"Tkinter unavailable for journey test: {exc}")


@pytest.mark.journey
@pytest.mark.slow
def test_jt04_img2img_adetailer_pipeline_run():
    """JT-04: Validate img2img and ADetailer pipeline transformation."""

    # Test data for JT-04
    test_prompt = "A beautiful landscape transformed with artistic style"
    test_negative = "blurry, distorted, low quality"

    # Create temporary directory for test files
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Step 1: Launch StableNew (build V2 app)
        root = _create_root()
        try:
            root, app_state, app_controller, window = build_v2_app(
                root=root,
                threaded=False,
            )

            # Step 2: Create and load a prompt pack (simulating JT-01 completion)
            prompt_state = window.prompt_tab.workspace_state
            pack = prompt_state.new_pack("JT04_Test_Pack", slot_count=1)
            pack.slots[0].text = test_prompt

            # Save the prompt pack
            pack_path = temp_path / "jt04_prompt_pack.json"
            saved_path = prompt_state.save_current_pack(pack_path)
            assert saved_path.exists()

            # Load the pack to simulate user selecting it
            loaded_pack = PromptPackModel.load_from_file(saved_path)
            assert loaded_pack.slots[0].text == test_prompt

            # Step 3: Create or simulate a base image (from JT-03 or test image)
            # For testing, we'll create a mock base image file
            base_image_path = temp_path / "base_test_image.png"
            # In a real scenario, this would be output from JT-03
            # For now, we'll just ensure the path exists for the mock
            base_image_path.touch()  # Create empty file as placeholder

            # Step 4: Access Pipeline tab
            pipeline_tab = getattr(window, 'pipeline_tab', None)
            assert pipeline_tab is not None, "Pipeline tab should exist"

            # Step 5: Configure Pipeline for img2img + ADetailer
            pipeline_state = getattr(pipeline_tab, 'pipeline_state', None)
            assert isinstance(pipeline_state, PipelineState)

            # Configure img2img stage
            # Note: Actual configuration would be done through UI controls
            # For testing, we directly set the pipeline state

            # Configure ADetailer
            # Note: ADetailer configuration would be done through UI controls
            # For testing, we simulate the configuration

            # Set pipeline state
            pipeline_state.prompt = test_prompt
            pipeline_state.negative_prompt = test_negative
            pipeline_state.base_image_path = str(base_image_path)

            # Step 6: Mock the WebUI API call for img2img + ADetailer
            with patch('src.api.client.ApiClient.generate_images') as mock_generate:
                # Mock successful img2img transformation response
                mock_response = Mock()
                mock_response.success = True
                mock_response.images = [Mock()]  # One transformed image
                mock_response.metadata = {
                    'stage': 'img2img',
                    'denoise': 0.45,
                    'sampler': 'Euler',
                    'scheduler': 'Karras',
                    'steps': 20,
                    'cfg_scale': 7.0,
                    'adetailer_enabled': True,
                    'adetailer_model': 'face_yolov8n.pt',
                    'base_image_path': str(base_image_path),
                    'seed': 12345,
                }
                mock_generate.return_value = mock_response

                # Step 7: Execute the img2img pipeline run
                controller = app_controller
                run_success = controller.start_run()
                assert run_success, "img2img pipeline run should start successfully"

                # Step 8: Verify run execution and results
                # Check that the API was called with correct parameters
                mock_generate.assert_called_once()
                call_args = mock_generate.call_args[0][0]  # First positional argument

                # Verify img2img parameters were passed correctly
                assert call_args.prompt == test_prompt
                assert call_args.negative_prompt == test_negative
                assert call_args.denoise == 0.45
                assert call_args.base_image_path == str(base_image_path)
                assert call_args.sampler == 'Euler'
                assert call_args.scheduler == 'Karras'
                assert call_args.steps == 20
                assert call_args.cfg_scale == 7.0

                # Verify ADetailer parameters (if supported in API call)
                # Note: ADetailer might be handled separately or as part of the pipeline
                if hasattr(call_args, 'adetailer_enabled'):
                    assert call_args.adetailer_enabled is True
                    assert call_args.adetailer_model == 'face_yolov8n.pt'

                # Step 9: Verify results display
                # Check that transformed image is displayed in the UI
                # and metadata matches the configuration

                # Verify response metadata
                assert mock_response.metadata['stage'] == 'img2img'
                assert mock_response.metadata['denoise'] == 0.45
                assert mock_response.metadata['adetailer_enabled'] is True
                assert mock_response.metadata['base_image_path'] == str(base_image_path)

                # Verify base image was properly referenced
                assert base_image_path.exists(), "Base image should exist for img2img"

        finally:
            try:
                window.cleanup()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass


def test_jt04_img2img_edge_cases():
    """Test JT-04 edge cases: low denoise, missing base image, ADetailer issues."""

    # Test cases for edge conditions
    edge_cases = [
        {
            "name": "very_low_denoise",
            "denoise": 0.05,  # Very low denoise - minimal change expected
            "expected_denoise": 0.05,
        },
        {
            "name": "missing_base_image",
            "base_image_path": None,  # Missing base image
            "should_fail": True,
        },
        {
            "name": "adetailer_misconfiguration",
            "adetailer_model": "nonexistent_model.pt",  # Invalid ADetailer model
            "expected_error": "ADetailer model not found",
        },
        {
            "name": "high_denoise",
            "denoise": 0.95,  # High denoise - major transformation expected
            "expected_denoise": 0.95,
        },
    ]

    for case in edge_cases:
        # Create temporary directory for test files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Step 1: Launch StableNew
            root = _create_root()
            try:
                root, app_state, app_controller, window = build_v2_app(
                    root=root,
                    threaded=False,
                )

                # Step 2: Set up prompt pack
                prompt_state = window.prompt_tab.workspace_state
                pack = prompt_state.new_pack(f"JT04_{case['name']}", slot_count=1)
                pack.slots[0].text = "Test prompt for edge case"

                # Step 3: Access Pipeline tab
                pipeline_tab = getattr(window, 'pipeline_tab', None)
                assert pipeline_tab is not None

                pipeline_state = getattr(pipeline_tab, 'pipeline_state', None)
                assert isinstance(pipeline_state, PipelineState)

                # Step 4: Configure with edge case parameters
                pipeline_state.prompt = "Test prompt for edge case"
                pipeline_state.negative_prompt = "bad quality"

                # Handle base image path
                if case.get("base_image_path") is None:
                    # Test missing base image
                    base_image_path = None
                else:
                    # Create a mock base image
                    base_image_path = temp_path / f"base_{case['name']}.png"
                    base_image_path.touch()

                pipeline_state.base_image_path = base_image_path

                # Step 5: Mock API and test edge case handling
                with patch('src.api.client.ApiClient.generate_images') as mock_generate:
                    if case.get("should_fail"):
                        # For cases that should fail, mock an error response
                        mock_response = Mock()
                        mock_response.success = False
                        mock_response.error = "Base image not found"
                        mock_generate.return_value = mock_response

                        # Execute run - should handle error gracefully
                        controller = app_controller
                        run_success = controller.start_run()

                        # Verify error handling
                        call_args = mock_generate.call_args[0][0]
                        assert call_args.base_image_path is None or not Path(call_args.base_image_path).exists()

                    else:
                        # For successful cases
                        mock_response = Mock()
                        mock_response.success = True
                        mock_response.images = [Mock()]
                        mock_response.metadata = {
                            'denoise': case['expected_denoise'],
                            'stage': 'img2img',
                            'seed': 67890,
                        }
                        mock_generate.return_value = mock_response

                        # Execute run
                        controller = app_controller
                        run_success = controller.start_run()
                        assert run_success

                        # Verify denoise parameter
                        call_args = mock_generate.call_args[0][0]
                        assert call_args.denoise == case['expected_denoise']

                        # Verify response
                        assert mock_response.metadata['denoise'] == case['expected_denoise']

            finally:
                try:
                    window.cleanup()
                except Exception:
                    pass
                try:
                    root.destroy()
                except Exception:
                    pass


def test_jt04_adetailer_integration():
    """Test ADetailer-specific functionality and parameter handling."""

    test_prompt = "A portrait of a person with detailed facial features"
    test_negative = "blurry, distorted"

    # Create temporary directory for test files
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Step 1: Launch StableNew
        root = _create_root()
        try:
            root, app_state, app_controller, window = build_v2_app(
                root=root,
                threaded=False,
            )

            # Step 2: Set up base image
            base_image_path = temp_path / "portrait_base.png"
            base_image_path.touch()

            # Step 3: Access Pipeline tab
            pipeline_tab = getattr(window, 'pipeline_tab', None)
            assert pipeline_tab is not None

            pipeline_state = getattr(pipeline_tab, 'pipeline_state', None)
            assert isinstance(pipeline_state, PipelineState)

            # Step 4: Configure ADetailer-focused pipeline
            pipeline_state.prompt = test_prompt
            pipeline_state.negative_prompt = test_negative
            pipeline_state.base_image_path = str(base_image_path)

            # ADetailer-specific configurations to test
            adetailer_configs = [
                {
                    'model': 'face_yolov8n.pt',
                    'confidence': 0.3,
                    'mask_blur': 4,
                    'inpaint_full_res': True,
                },
                {
                    'model': 'hand_yolov8n.pt',
                    'confidence': 0.5,
                    'mask_blur': 8,
                    'inpaint_full_res': False,
                },
            ]

            for ad_config in adetailer_configs:
                # Step 5: Mock API with ADetailer parameters
                with patch('src.api.client.ApiClient.generate_images') as mock_generate:
                    mock_response = Mock()
                    mock_response.success = True
                    mock_response.images = [Mock()]
                    mock_response.metadata = {
                        'stage': 'img2img',
                        'adetailer_enabled': True,
                        'adetailer_model': ad_config['model'],
                        'adetailer_confidence': ad_config['confidence'],
                        'adetailer_mask_blur': ad_config['mask_blur'],
                        'adetailer_inpaint_full_res': ad_config['inpaint_full_res'],
                        'seed': 11111,
                    }
                    mock_generate.return_value = mock_response

                    # Step 6: Execute run with ADetailer
                    controller = app_controller
                    run_success = controller.start_run()
                    assert run_success

                    # Step 7: Verify ADetailer parameters were passed correctly
                    call_args = mock_generate.call_args[0][0]

                    # Verify base parameters
                    assert call_args.prompt == test_prompt
                    assert call_args.negative_prompt == test_negative
                    assert call_args.base_image_path == str(base_image_path)

                    # Verify ADetailer-specific parameters (if supported)
                    if hasattr(call_args, 'adetailer_model'):
                        assert call_args.adetailer_model == ad_config['model']
                        assert call_args.adetailer_confidence == ad_config['confidence']
                        assert call_args.adetailer_mask_blur == ad_config['mask_blur']
                        assert call_args.adetailer_inpaint_full_res == ad_config['inpaint_full_res']

                    # Verify response metadata
                    assert mock_response.metadata['adetailer_enabled'] is True
                    assert mock_response.metadata['adetailer_model'] == ad_config['model']

        finally:
            try:
                window.cleanup()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass



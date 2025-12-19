"""
Test n_iter handling in txt2img stage to prevent file clobbering.

Covers:
- n_iter > 1 with batch_size = 1 produces unique filenames
- batch_size > 1 produces unique filenames
- Single image doesn't add suffix
- Regression prevention for duplicate paths/clobbered images
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.api.client import SDWebUIClient
from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger


class TestNIterFilenames:
    """Test suite for n_iter and batch_size filename generation."""

    def setup_method(self):
        """Setup for each test."""
        self.client = SDWebUIClient(base_url="http://127.0.0.1:7860")
        self.pipeline = Pipeline(self.client, StructuredLogger())

    @patch("src.pipeline.executor.save_image_from_base64")
    @patch.object(Pipeline, "_generate_images")
    @patch.object(Pipeline, "_ensure_webui_true_ready")
    @patch.object(Pipeline, "_apply_webui_defaults_once")
    def test_n_iter_creates_unique_filenames(
        self, mock_defaults, mock_ready, mock_generate, mock_save
    ):
        """
        Test that n_iter > 1 with batch_size = 1 creates unique filenames.
        
        REGRESSION: Previously, when n_iter=3 and batch_size=1, all 3 images
        were saved to the same filename, clobbering each other.
        """
        # Setup: n_iter=3, batch_size=1 → WebUI returns 3 images
        mock_generate.return_value = {
            "images": ["base64_img0", "base64_img1", "base64_img2"]
        }
        mock_save.return_value = True

        config = {
            "txt2img": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "n_iter": 3,  # 3 iterations
                "batch_size": 1,  # But only 1 per batch
            }
        }

        output_dir = Path("test_output/txt2img")
        _ = self.pipeline.run_txt2img_stage(
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            output_dir=output_dir,
            image_name="test_image",
        )

        # Should have called save 3 times with UNIQUE filenames
        assert mock_save.call_count == 3

        saved_paths = [call.args[1] for call in mock_save.call_args_list]
        saved_filenames = [p.name for p in saved_paths]

        # All filenames must be unique (no clobbering)
        assert len(set(saved_filenames)) == 3, f"Duplicate filenames detected: {saved_filenames}"

        # Filenames should have _batch0, _batch1, _batch2 suffixes
        assert "test_image_batch0.png" in saved_filenames
        assert "test_image_batch1.png" in saved_filenames
        assert "test_image_batch2.png" in saved_filenames

    @patch("src.pipeline.executor.save_image_from_base64")
    @patch.object(Pipeline, "_generate_images")
    @patch.object(Pipeline, "_ensure_webui_true_ready")
    @patch.object(Pipeline, "_apply_webui_defaults_once")
    def test_batch_size_creates_unique_filenames(
        self, mock_defaults, mock_ready, mock_generate, mock_save
    ):
        """Test that batch_size > 1 creates unique filenames."""
        # Setup: batch_size=3, n_iter=1 → WebUI returns 3 images
        mock_generate.return_value = {
            "images": ["base64_img0", "base64_img1", "base64_img2"]
        }
        mock_save.return_value = True

        config = {
            "txt2img": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "n_iter": 1,
                "batch_size": 3,  # 3 images in one batch
            }
        }

        output_dir = Path("test_output/txt2img")
        _ = self.pipeline.run_txt2img_stage(
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            output_dir=output_dir,
            image_name="test_image",
        )

        # Should have called save 3 times
        assert mock_save.call_count == 3

        saved_paths = [call.args[1] for call in mock_save.call_args_list]
        saved_filenames = [p.name for p in saved_paths]

        # All filenames must be unique
        assert len(set(saved_filenames)) == 3

        # Filenames should have _batch0, _batch1, _batch2 suffixes
        assert "test_image_batch0.png" in saved_filenames
        assert "test_image_batch1.png" in saved_filenames
        assert "test_image_batch2.png" in saved_filenames

    @patch("src.pipeline.executor.save_image_from_base64")
    @patch.object(Pipeline, "_generate_images")
    @patch.object(Pipeline, "_ensure_webui_true_ready")
    @patch.object(Pipeline, "_apply_webui_defaults_once")
    def test_single_image_no_suffix(
        self, mock_defaults, mock_ready, mock_generate, mock_save
    ):
        """Test that single image doesn't add _batch suffix."""
        # Setup: batch_size=1, n_iter=1 → WebUI returns 1 image
        mock_generate.return_value = {"images": ["base64_img0"]}
        mock_save.return_value = True

        config = {
            "txt2img": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "n_iter": 1,
                "batch_size": 1,
            }
        }

        output_dir = Path("test_output/txt2img")
        _ = self.pipeline.run_txt2img_stage(
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            output_dir=output_dir,
            image_name="test_image",
        )

        # Should have called save once
        assert mock_save.call_count == 1

        saved_path = mock_save.call_args[0][1]
        
        # Filename should NOT have _batch suffix
        assert saved_path.name == "test_image.png"

    @patch("src.pipeline.executor.save_image_from_base64")
    @patch.object(Pipeline, "_generate_images")
    @patch.object(Pipeline, "_ensure_webui_true_ready")
    @patch.object(Pipeline, "_apply_webui_defaults_once")
    def test_n_iter_and_batch_size_combined(
        self, mock_defaults, mock_ready, mock_generate, mock_save
    ):
        """Test combined n_iter and batch_size creates unique filenames."""
        # Setup: batch_size=2, n_iter=2 → WebUI returns 4 images
        mock_generate.return_value = {
            "images": ["img0", "img1", "img2", "img3"]
        }
        mock_save.return_value = True

        config = {
            "txt2img": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "n_iter": 2,
                "batch_size": 2,
            }
        }

        output_dir = Path("test_output/txt2img")
        _ = self.pipeline.run_txt2img_stage(
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            output_dir=output_dir,
            image_name="test_image",
        )

        # Should have called save 4 times
        assert mock_save.call_count == 4

        saved_paths = [call.args[1] for call in mock_save.call_args_list]
        saved_filenames = [p.name for p in saved_paths]

        # All filenames must be unique
        assert len(set(saved_filenames)) == 4, f"Duplicate filenames: {saved_filenames}"


class TestNIterRegression:
    """Regression tests for n_iter file clobbering bug."""

    def setup_method(self):
        """Setup for each test."""
        self.client = SDWebUIClient(base_url="http://127.0.0.1:7860")
        self.pipeline = Pipeline(self.client, StructuredLogger())

    @patch("src.pipeline.executor.save_image_from_base64")
    @patch.object(Pipeline, "_generate_images")
    @patch.object(Pipeline, "_ensure_webui_true_ready")
    @patch.object(Pipeline, "_apply_webui_defaults_once")
    def test_regression_n_iter_file_clobbering_prevented(
        self, mock_defaults, mock_ready, mock_generate, mock_save
    ):
        """
        REGRESSION TEST: Prevent file clobbering when n_iter > 1.
        
        Background: When n_iter > 1 but batch_size = 1, the save loop
        was taking the else branch and writing every image to the same
        filename, clobbering earlier iterations. This caused:
        1. Duplicate paths in saved_paths list
        2. Only the last image surviving on disk
        3. Downstream stages only seeing a single output
        
        Fix: Use num_images_received instead of batch_size to decide
        whether to add _batch suffix.
        """
        # Simulate the problematic scenario
        mock_generate.return_value = {
            "images": ["iter0", "iter1", "iter2", "iter3", "iter4"]
        }
        mock_save.return_value = True

        config = {
            "txt2img": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "n_iter": 5,  # User wants 5 images
                "batch_size": 1,  # But generates 1 at a time
            }
        }

        output_dir = Path("test_output/txt2img")
        _ = self.pipeline.run_txt2img_stage(
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            output_dir=output_dir,
            image_name="portrait",
        )

        # Critical assertions to prevent regression
        saved_paths = [call.args[1] for call in mock_save.call_args_list]

        # 1. Must have saved 5 images
        assert len(saved_paths) == 5, "Not all images were saved"

        # 2. All paths must be unique (no clobbering)
        unique_paths = {str(p) for p in saved_paths}
        assert len(unique_paths) == 5, f"Files were clobbered! Unique: {len(unique_paths)}, Expected: 5"

        # 3. All filenames must be unique
        saved_filenames = [p.name for p in saved_paths]
        unique_filenames = set(saved_filenames)
        assert len(unique_filenames) == 5, f"Duplicate filenames detected: {saved_filenames}"

        # 4. Should have _batch suffixes since num_images > 1
        expected_filenames = {
            "portrait_batch0.png",
            "portrait_batch1.png",
            "portrait_batch2.png",
            "portrait_batch3.png",
            "portrait_batch4.png",
        }
        assert set(saved_filenames) == expected_filenames

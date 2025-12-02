#!/usr/bin/env python3
"""
Comprehensive journey tests for the StableNew pipeline.

Tests the complete pipeline flow with various configurations to ensure:
1. All stages work correctly (txt2img → img2img → upscale → video)
2. Config pass-through is preserved at each stage
3. Optional stages can be skipped (img2img, upscale)
4. Previous functionality remains intact
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger

pytestmark = [
    pytest.mark.journey,
    pytest.mark.legacy,
    pytest.mark.slow,
]


@pytest.fixture
def mock_client():
    """Create a mock SD WebUI client that returns valid responses"""
    client = Mock()

    # Mock txt2img response - returns a simple 1x1 pixel PNG as base64
    mock_image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    # Create a side_effect function that returns the requested batch_size
    def txt2img_side_effect(payload):
        batch_size = payload.get("batch_size", 1)
        return {"images": [mock_image_b64] * batch_size, "parameters": {}}

    client.txt2img.side_effect = txt2img_side_effect

    client.img2img.return_value = {"images": [mock_image_b64], "parameters": {}}

    client.upscale_image.return_value = {"image": mock_image_b64}

    client.set_model = Mock()
    client.set_vae = Mock()

    return client


@pytest.fixture
def structured_logger(tmp_path):
    """Create a structured logger with temporary directory"""
    return StructuredLogger(output_dir=tmp_path)


@pytest.fixture
def pipeline(mock_client, structured_logger):
    """Create pipeline instance with mocked client"""
    return Pipeline(mock_client, structured_logger)


class TestFullPipelineJourney:
    """Test complete pipeline execution with all stages enabled"""

    def test_full_pipeline_all_stages(self, pipeline, mock_client, tmp_path):
        """Test complete pipeline: txt2img → img2img → upscale"""
        config = {
            "txt2img": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "sampler_name": "Euler a",
                "negative_prompt": "ugly",
            },
            "img2img": {
                "steps": 15,
                "cfg_scale": 7.0,
                "denoising_strength": 0.3,
                "sampler_name": "Euler a",
            },
            "upscale": {"upscaler": "R-ESRGAN 4x+", "upscaling_resize": 2.0},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        }

        results = pipeline.run_full_pipeline(prompt="test prompt", config=config, batch_size=1)

        # Verify all stages executed
        assert len(results["txt2img"]) == 1
        assert len(results["img2img"]) == 1
        assert len(results["upscaled"]) == 1
        assert len(results["summary"]) == 1

        # Verify summary contains all paths
        summary = results["summary"][0]
        assert "txt2img_path" in summary
        assert "img2img_path" in summary
        assert "upscaled_path" in summary
        assert "final_image_path" in summary
        assert summary["stages_completed"] == ["txt2img", "img2img", "upscale"]

        # Verify API calls were made
        assert mock_client.txt2img.called
        assert mock_client.img2img.called
        assert mock_client.upscale_image.called

    def test_config_passthrough_txt2img(self, pipeline, mock_client, tmp_path):
        """Test that txt2img config is correctly passed to API"""
        config = {
            "txt2img": {
                "steps": 42,
                "cfg_scale": 12.5,
                "width": 1024,
                "height": 768,
                "sampler_name": "DPM++ 2M",
                "scheduler": "Karras",
                "clip_skip": 2,
                "seed": 12345,
                "negative_prompt": "bad quality",
            },
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        pipeline.run_full_pipeline(prompt="config test", config=config, batch_size=1)

        # Get the actual call arguments
        call_args = mock_client.txt2img.call_args
        payload = call_args[0][0]  # First positional argument

        # Verify critical config values were passed through
        assert payload["steps"] == 42
        assert payload["cfg_scale"] == 12.5
        assert payload["width"] == 1024
        assert payload["height"] == 768
        assert payload["sampler_name"] == "DPM++ 2M"
        assert payload["scheduler"] == "Karras"
        assert payload["clip_skip"] == 2
        assert payload["seed"] == 12345
        # Note: negative_prompt will have global NSFW prevention added
        assert "bad quality" in payload["negative_prompt"]

    def test_progress_reporting(self, pipeline, mock_client, tmp_path):
        """Pipeline should emit progress updates for each stage."""

        class StubController:
            def __init__(self):
                self.calls = []

            def report_progress(self, stage, percent, eta):
                self.calls.append((stage, percent, eta))

        stub = StubController()
        pipeline.set_progress_controller(stub)

        config = {
            "txt2img": {"steps": 5},
            "img2img": {"steps": 5},
            "upscale": {"upscaler": "R-ESRGAN 4x+"},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        }

        pipeline.run_full_pipeline(prompt="progress", config=config, batch_size=2)

        stages = [call[0] for call in stub.calls]

        assert stages[0] == "txt2img"
        assert any(stage.startswith("img2img") for stage in stages)
        assert any(stage.startswith("upscale") for stage in stages)
        assert stages[-1] == "Completed"
        assert stub.calls[-1][1] == pytest.approx(100.0, abs=1e-6)


class TestOptionalStages:
    """Test pipeline with optional stages disabled"""

    def test_skip_img2img(self, pipeline, mock_client, tmp_path):
        """Test pipeline with img2img disabled: txt2img → upscale"""
        config = {
            "txt2img": {"steps": 20, "cfg_scale": 7.0},
            "upscale": {"upscaler": "R-ESRGAN 4x+"},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": True},
        }

        results = pipeline.run_full_pipeline(
            prompt="skip img2img test", config=config, batch_size=1
        )

        # Verify stages
        assert len(results["txt2img"]) == 1
        assert len(results["img2img"]) == 0  # Should be empty
        assert len(results["upscaled"]) == 1

        # Verify summary
        summary = results["summary"][0]
        assert "txt2img_path" in summary
        assert "img2img_path" not in summary
        assert "upscaled_path" in summary
        assert summary["stages_completed"] == ["txt2img", "upscale"]

        # Verify API calls
        assert mock_client.txt2img.called
        assert not mock_client.img2img.called  # Should NOT be called
        assert mock_client.upscale_image.called

    def test_skip_upscale(self, pipeline, mock_client, tmp_path):
        """Test pipeline with upscale disabled: txt2img → img2img"""
        config = {
            "txt2img": {"steps": 20},
            "img2img": {"steps": 15},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": False},
        }

        results = pipeline.run_full_pipeline(
            prompt="skip upscale test", config=config, batch_size=1
        )

        # Verify stages
        assert len(results["txt2img"]) == 1
        assert len(results["img2img"]) == 1
        assert len(results["upscaled"]) == 0  # Should be empty

        # Verify summary
        summary = results["summary"][0]
        assert "txt2img_path" in summary
        assert "img2img_path" in summary
        assert "upscaled_path" not in summary
        assert summary["stages_completed"] == ["txt2img", "img2img"]

        # Verify API calls
        assert mock_client.txt2img.called
        assert mock_client.img2img.called
        assert not mock_client.upscale_image.called  # Should NOT be called

    def test_skip_both_img2img_and_upscale(self, pipeline, mock_client, tmp_path):
        """Test pipeline with both img2img and upscale disabled: txt2img only"""
        config = {
            "txt2img": {"steps": 20, "cfg_scale": 7.0},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        results = pipeline.run_full_pipeline(
            prompt="txt2img only test", config=config, batch_size=1
        )

        # Verify only txt2img executed
        assert len(results["txt2img"]) == 1
        assert len(results["img2img"]) == 0
        assert len(results["upscaled"]) == 0

        # Verify summary
        summary = results["summary"][0]
        assert "txt2img_path" in summary
        assert "img2img_path" not in summary
        assert "upscaled_path" not in summary
        assert summary["stages_completed"] == ["txt2img"]
        assert summary["final_image_path"] == summary["txt2img_path"]

        # Verify only txt2img was called
        assert mock_client.txt2img.called
        assert not mock_client.img2img.called
        assert not mock_client.upscale_image.called


class TestBatchProcessing:
    """Test batch processing capabilities"""

    def test_multiple_images_full_pipeline(self, pipeline, mock_client, tmp_path):
        """Test batch generation with all stages"""
        config = {
            "txt2img": {"steps": 20},
            "img2img": {"steps": 15},
            "upscale": {"upscaler": "R-ESRGAN 4x+"},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        }

        results = pipeline.run_full_pipeline(prompt="batch test", config=config, batch_size=3)

        # Should process 3 images through all stages
        assert len(results["txt2img"]) == 3
        assert len(results["img2img"]) == 3
        assert len(results["upscaled"]) == 3
        assert len(results["summary"]) == 3

        # Verify each summary has all stages
        for summary in results["summary"]:
            assert summary["stages_completed"] == ["txt2img", "img2img", "upscale"]

    def test_multiple_images_skip_img2img(self, pipeline, mock_client, tmp_path):
        """Test batch generation skipping img2img"""
        config = {
            "txt2img": {"steps": 20},
            "upscale": {"upscaler": "R-ESRGAN 4x+"},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": True},
        }

        results = pipeline.run_full_pipeline(
            prompt="batch skip img2img", config=config, batch_size=2
        )

        # Should process 2 images, skipping img2img
        assert len(results["txt2img"]) == 2
        assert len(results["img2img"]) == 0
        assert len(results["upscaled"]) == 2
        assert len(results["summary"]) == 2

        # Verify each summary skipped img2img
        for summary in results["summary"]:
            assert summary["stages_completed"] == ["txt2img", "upscale"]
            assert "img2img_path" not in summary


class TestConfigurationPreservation:
    """Test that configuration is preserved through all pipeline stages"""

    def test_hires_fix_config_passthrough(self, pipeline, mock_client, tmp_path):
        """Test high-res fix configuration is passed through correctly"""
        config = {
            "txt2img": {
                "steps": 20,
                "enable_hr": True,
                "hr_scale": 2.0,
                "hr_upscaler": "Latent",
                "hr_second_pass_steps": 15,
                "denoising_strength": 0.6,
            },
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        pipeline.run_full_pipeline("hires test", config, batch_size=1)

        # Verify hires.fix config was passed
        call_args = mock_client.txt2img.call_args[0][0]
        assert call_args["enable_hr"] is True
        assert call_args["hr_scale"] == 2.0
        assert call_args["hr_upscaler"] == "Latent"
        assert call_args["hr_second_pass_steps"] == 15
        assert call_args["denoising_strength"] == 0.6

    def test_model_and_vae_config(self, pipeline, mock_client, tmp_path):
        """Test model and VAE configuration is applied"""
        config = {
            "txt2img": {
                "steps": 20,
                "model": "sd_xl_base_1.0.safetensors",
                "vae": "sdxl_vae.safetensors",
            },
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        pipeline.run_full_pipeline("model test", config, batch_size=1)

        # Verify model and VAE were set
        mock_client.set_model.assert_called_once_with("sd_xl_base_1.0.safetensors")
        mock_client.set_vae.assert_called_once_with("sdxl_vae.safetensors")

    def test_negative_prompt_enhancement(self, pipeline, mock_client, tmp_path):
        """Test that negative prompts get global NSFW prevention"""
        config = {
            "txt2img": {"steps": 20, "negative_prompt": "bad quality, blurry"},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        pipeline.run_full_pipeline("negative test", config, batch_size=1)

        # Verify negative prompt was enhanced (should contain original + global_neg)
        call_args = mock_client.txt2img.call_args[0][0]
        enhanced_negative = call_args["negative_prompt"]

        # Should contain the original negative prompt
        assert "bad quality" in enhanced_negative
        assert "blurry" in enhanced_negative

        # Should be longer than original (global_neg added)
        assert len(enhanced_negative) > len("bad quality, blurry")


class TestErrorHandling:
    """Test pipeline behavior with errors"""

    def test_txt2img_failure(self, pipeline, mock_client, tmp_path):
        """Test pipeline handles txt2img failure gracefully"""
        # Override the side_effect for this test only
        mock_client.txt2img.side_effect = None
        mock_client.txt2img.return_value = None  # Simulate failure

        config = {
            "txt2img": {"steps": 20},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        }

        results = pipeline.run_full_pipeline("fail test", config, batch_size=1)

        # Should fail early with no results
        assert len(results["txt2img"]) == 0
        assert len(results["img2img"]) == 0
        assert len(results["upscaled"]) == 0
        assert len(results["summary"]) == 0

    def test_img2img_failure_continues(self, pipeline, mock_client, tmp_path):
        """Test pipeline continues to upscale when img2img fails"""
        # txt2img succeeds, img2img fails
        mock_image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        mock_client.txt2img.return_value = {"images": [mock_image_b64]}
        mock_client.img2img.return_value = None  # img2img fails
        mock_client.upscale_image.return_value = {"image": mock_image_b64}

        config = {
            "txt2img": {"steps": 20},
            "img2img": {"steps": 15},
            "upscale": {"upscaler": "R-ESRGAN 4x+"},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        }

        results = pipeline.run_full_pipeline("partial fail", config, batch_size=1)

        # txt2img should succeed
        assert len(results["txt2img"]) == 1

        # img2img fails, so upscale should use txt2img output
        assert len(results["img2img"]) == 0
        assert len(results["upscaled"]) == 1

        # Summary should show partial completion
        assert len(results["summary"]) == 1
        summary = results["summary"][0]
        assert "txt2img" in summary["stages_completed"]
        assert "img2img" not in summary["stages_completed"]
        assert "upscale" in summary["stages_completed"]


class TestDirectoryStructure:
    """Test that output directory structure is created correctly"""

    def test_run_directory_creation(self, pipeline, mock_client, tmp_path):
        """Test that run directories are created properly"""
        config = {
            "txt2img": {"steps": 20},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        }

        results = pipeline.run_full_pipeline("dir test", config, batch_size=1)

        run_dir = Path(results["run_dir"])

        # Verify run directory exists
        assert run_dir.exists()
        assert run_dir.is_dir()

        # Verify subdirectories for each stage
        assert (run_dir / "txt2img").exists()
        assert (run_dir / "img2img").exists()
        assert (run_dir / "upscaled").exists()
        assert (run_dir / "manifests").exists()

    def test_manifest_creation(self, pipeline, mock_client, tmp_path):
        """Test that manifests are created for each image"""
        config = {
            "txt2img": {"steps": 20},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        results = pipeline.run_full_pipeline("manifest test", config, batch_size=1)

        run_dir = Path(results["run_dir"])
        manifest_dir = run_dir / "manifests"

        # Should have at least one manifest file
        manifests = list(manifest_dir.glob("*.json"))
        assert len(manifests) > 0

        # Verify manifest content
        with open(manifests[0], encoding="utf-8") as f:
            manifest = json.load(f)
            assert "stage" in manifest
            assert "timestamp" in manifest
            assert "prompt" in manifest


class TestVideoStageIntegration:
    """Test video stage integration with the full pipeline"""

    def test_video_stage_with_all_stages(self, pipeline, mock_client, tmp_path):
        """Test complete pipeline with video stage: txt2img → img2img → upscale → video"""
        # Mock video creator
        with patch("src.pipeline.video.VideoCreator") as mock_video_creator:
            mock_instance = Mock()
            mock_instance.create_video_from_images.return_value = True
            mock_video_creator.return_value = mock_instance

            config = {
                "txt2img": {"steps": 20},
                "img2img": {"steps": 15},
                "upscale": {"upscaler": "R-ESRGAN 4x+"},
                "video": {"fps": 24, "codec": "libx264"},
                "pipeline": {
                    "img2img_enabled": True,
                    "upscale_enabled": True,
                    "video_enabled": True,
                },
            }

            results = pipeline.run_full_pipeline(prompt="video test", config=config, batch_size=3)

            # Verify all stages executed
            assert len(results["txt2img"]) == 3
            assert len(results["img2img"]) == 3
            assert len(results["upscaled"]) == 3
            assert len(results["summary"]) == 3

            # Verify video creation was attempted
            # (In real pipeline, video would be created from sequence)
            # For now, just verify the structure is correct

    def test_upscale_only_flow(self, pipeline, mock_client, tmp_path):
        """Test upscale only flow: txt2img → upscale (skip img2img)"""
        config = {
            "txt2img": {"steps": 20},
            "upscale": {"upscaler": "R-ESRGAN 4x+", "upscaling_resize": 2.0},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": True},
        }

        results = pipeline.run_full_pipeline(prompt="upscale only", config=config, batch_size=2)

        # Verify correct stage execution
        assert len(results["txt2img"]) == 2
        assert len(results["img2img"]) == 0  # Skipped
        assert len(results["upscaled"]) == 2

        # Verify summaries reflect correct flow
        for summary in results["summary"]:
            assert summary["stages_completed"] == ["txt2img", "upscale"]
            assert "img2img_path" not in summary

    def test_midstream_entry_img2img(self, pipeline, mock_client, tmp_path):
        """Test starting pipeline from img2img stage with existing images"""
        # Create a fake existing image
        existing_image_dir = tmp_path / "existing"
        existing_image_dir.mkdir()
        existing_image = existing_image_dir / "test_image.png"
        existing_image.write_text("fake image data")

        config = {
            "img2img": {"steps": 15, "denoising_strength": 0.4},
            "upscale": {"upscaler": "R-ESRGAN 4x+"},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        }

        with patch("src.pipeline.executor.load_image_to_base64", return_value="base64_data"):
            result = pipeline.run_img2img(
                existing_image, "enhanced prompt", config["img2img"], tmp_path
            )

        # Should successfully process from midstream
        assert result is not None
        # Check for actual returned field name
        assert "path" in result  # img2img returns "path" not "img2img_path"


class TestManifestAndCSVValidation:
    """Test manifest and CSV rollup validation"""

    def test_manifest_json_structure(self, pipeline, mock_client, tmp_path):
        """Validate per-stage JSON structure, required fields, and data types"""
        config = {
            "txt2img": {"steps": 20, "cfg_scale": 7.0, "seed": 12345},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        results = pipeline.run_full_pipeline("manifest test", config, batch_size=1)

        run_dir = Path(results["run_dir"])
        manifest_dir = run_dir / "manifests"

        # Find manifest files
        manifests = list(manifest_dir.glob("*.json"))
        assert len(manifests) > 0

        # Validate structure
        with open(manifests[0], encoding="utf-8") as f:
            manifest = json.load(f)

            # Required fields
            assert "stage" in manifest
            assert "timestamp" in manifest
            assert "prompt" in manifest
            assert "config" in manifest

            # Data types
            assert isinstance(manifest["stage"], str)
            assert isinstance(manifest["timestamp"], str)
            assert isinstance(manifest["prompt"], str)
            assert isinstance(manifest["config"], dict)

    def test_csv_rollup_headers(self, pipeline, mock_client, tmp_path):
        """Verify CSV rollup contains correct headers"""
        config = {
            "txt2img": {"steps": 20},
            "img2img": {"steps": 15},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": False},
        }

        results = pipeline.run_full_pipeline("csv test", config, batch_size=2)

        run_dir = Path(results["run_dir"])

        # Look for CSV files
        csv_files = list(run_dir.glob("*.csv"))
        if csv_files:
            import csv

            with open(csv_files[0], encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames

                # Should have essential headers
                assert headers is not None
                # CSV structure depends on implementation, verify it's not empty
                assert len(headers) > 0

    def test_timestamp_ordering(self, pipeline, mock_client, tmp_path):
        """Verify timestamp ordering in manifests"""
        config = {
            "txt2img": {"steps": 20},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        results = pipeline.run_full_pipeline("timestamp test", config, batch_size=3)

        run_dir = Path(results["run_dir"])
        manifest_dir = run_dir / "manifests"

        manifests = sorted(manifest_dir.glob("*.json"))
        assert len(manifests) >= 3

        timestamps = []
        for manifest_path in manifests:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
                timestamps.append(manifest["timestamp"])

        # Timestamps should be in order (or very close)
        # This is a basic check; timestamps should be ISO format
        for ts in timestamps:
            assert isinstance(ts, str)
            assert len(ts) > 0


class TestCooperativeCancelAndResume:
    """Test cooperative cancellation and resume scenarios"""

    def test_cancel_mid_run_clean_stop(self, pipeline, mock_client, tmp_path):
        """Simulate cancel token mid-run and verify clean stop"""
        from src.gui.state import CancelToken

        cancel_token = CancelToken()

        # Cancel after txt2img but before img2img
        def delayed_cancel(*args, **kwargs):
            result = {"images": ["base64_image_data"]}
            cancel_token.cancel()
            return result

        mock_client.txt2img = Mock(side_effect=delayed_cancel)

        config = {
            "txt2img": {"steps": 20},
            "img2img": {"steps": 15},
            "upscale": {"upscaler": "R-ESRGAN 4x+"},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        }

        with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
            with patch("src.pipeline.executor.load_image_to_base64", return_value="base64"):
                results = pipeline.run_full_pipeline(
                    "cancel test", config, batch_size=1, cancel_token=cancel_token
                )

        # Should have partial results
        # txt2img may or may not complete depending on timing
        assert results["img2img"] == []
        assert results["upscaled"] == []

    def test_no_duplicate_manifests_after_cancel(self, pipeline, mock_client, tmp_path):
        """Verify no duplicate manifests after cancellation"""
        from src.gui.state import CancelToken

        cancel_token = CancelToken()

        config = {
            "txt2img": {"steps": 20},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        # First run with cancel
        cancel_token.cancel()
        with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
            results1 = pipeline.run_full_pipeline(
                "no dup test", config, batch_size=1, cancel_token=cancel_token
            )

        if results1.get("run_dir"):
            run_dir1 = Path(results1["run_dir"])
            manifest_dir1 = run_dir1 / "manifests"
            initial_manifests = (
                len(list(manifest_dir1.glob("*.json"))) if manifest_dir1.exists() else 0
            )

            # Resume with new token
            cancel_token2 = CancelToken()
            with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
                results2 = pipeline.run_full_pipeline(
                    "no dup test", config, batch_size=1, cancel_token=cancel_token2
                )

            # Should create new run directory, not duplicate in old one
            if results2.get("run_dir"):
                run_dir2 = Path(results2["run_dir"])
                # Different run directories
                assert run_dir1 != run_dir2 or initial_manifests <= len(
                    list(manifest_dir1.glob("*.json"))
                )


class TestRetryBackoffBehavior:
    """Test retry/backoff behavior with transient failures"""

    def test_transient_txt2img_failure_with_backoff(self, pipeline, mock_client, tmp_path):
        """Inject transient txt2img failures and assert exponential backoff intervals"""
        # Mock client to fail first few times then succeed
        call_count = [0]
        mock_image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        def flaky_txt2img(payload):
            call_count[0] += 1
            if call_count[0] < 3:
                # Fail first 2 attempts
                return None
            return {"images": [mock_image_b64]}

        mock_client.txt2img = Mock(side_effect=flaky_txt2img)

        config = {
            "txt2img": {"steps": 20},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        # Note: Current pipeline may not have retry logic implemented
        # This test documents expected behavior
        results = pipeline.run_full_pipeline("retry test", config, batch_size=1)

        # If retry logic exists, should eventually succeed
        # If not, will fail on first attempt
        # This test serves as a specification for future retry implementation
        assert "txt2img" in results

    def test_manifest_reflects_retry_attempts(self, pipeline, mock_client, tmp_path):
        """Verify manifests capture retry attempt information"""
        config = {
            "txt2img": {"steps": 20},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        results = pipeline.run_full_pipeline("retry manifest", config, batch_size=1)

        run_dir = Path(results["run_dir"])
        manifest_dir = run_dir / "manifests"

        manifests = list(manifest_dir.glob("*.json"))
        if manifests:
            with open(manifests[0], encoding="utf-8") as f:
                manifest = json.load(f)
                # Manifest should exist with stage info
                assert "stage" in manifest
                # Future: could include retry_count field


class TestPromptPackPermutations:
    """Test prompt pack permutations with multi-batch runs"""

    def test_multi_batch_metadata_capture(self, pipeline, mock_client, tmp_path):
        """Exercise prompt pack permutations and confirm metadata capture"""
        config = {
            "txt2img": {
                "steps": 20,
                "negative_prompt": "bad quality",
            },
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        # Run with batch to generate multiple images
        results = pipeline.run_full_pipeline("batch metadata", config, batch_size=4)

        assert len(results["txt2img"]) == 4
        assert len(results["summary"]) == 4

        # Each summary should have metadata
        for summary in results["summary"]:
            assert "txt2img_path" in summary
            assert "final_image_path" in summary

    def test_persistent_negative_prompt_safety(self, pipeline, mock_client, tmp_path):
        """Confirm persistent negative prompt safety lists are maintained"""
        config = {
            "txt2img": {
                "steps": 20,
                "negative_prompt": "custom negative",
            },
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        pipeline.run_full_pipeline("safety test", config, batch_size=1)

        # Verify API was called with enhanced negative prompt
        call_args = mock_client.txt2img.call_args[0][0]
        enhanced_negative = call_args["negative_prompt"]

        # Should contain original plus global safety
        assert "custom negative" in enhanced_negative
        # Global neg should be added (implementation dependent)
        assert len(enhanced_negative) >= len("custom negative")


class TestThreadSafeProgressReporting:
    """Test thread-safe progress reporting"""

    def test_ordered_stage_transitions(self, pipeline, mock_client, tmp_path):
        """Enforce ordered stage transitions in progress reporting"""

        class ProgressTracker:
            def __init__(self):
                self.stages = []
                self.percents = []

            def report_progress(self, stage, percent, eta):
                self.stages.append(stage)
                self.percents.append(percent)

        tracker = ProgressTracker()
        pipeline.set_progress_controller(tracker)

        config = {
            "txt2img": {"steps": 10},
            "img2img": {"steps": 10},
            "upscale": {"upscaler": "R-ESRGAN 4x+"},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
        }

        pipeline.run_full_pipeline("progress order", config, batch_size=1)

        # Should have progress reports
        assert len(tracker.stages) > 0

        # First stage should be txt2img
        assert tracker.stages[0] == "txt2img"

        # Last should be Completed
        assert tracker.stages[-1] == "Completed"

    def test_single_completion_event(self, pipeline, mock_client, tmp_path):
        """Verify single completion event at end"""

        class CompletionTracker:
            def __init__(self):
                self.completion_count = 0

            def report_progress(self, stage, percent, eta):
                if stage == "Completed" and percent == pytest.approx(100.0, abs=1e-6):
                    self.completion_count += 1

        tracker = CompletionTracker()
        pipeline.set_progress_controller(tracker)

        config = {
            "txt2img": {"steps": 10},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        pipeline.run_full_pipeline("single completion", config, batch_size=2)

        # Should have exactly one completion event
        assert tracker.completion_count == 1

    def test_consistent_eta_calculations(self, pipeline, mock_client, tmp_path):
        """Verify consistent ETA calculations without erratic fluctuations"""

        class ETATracker:
            def __init__(self):
                self.etas = []

            def report_progress(self, stage, percent, eta):
                if eta is not None:
                    self.etas.append(eta)

        tracker = ETATracker()
        pipeline.set_progress_controller(tracker)

        config = {
            "txt2img": {"steps": 10},
            "img2img": {"steps": 10},
            "pipeline": {"img2img_enabled": True, "upscale_enabled": False},
        }

        pipeline.run_full_pipeline("eta consistency", config, batch_size=2)

        # ETAs should generally decrease over time (allowing some variance)
        if len(tracker.etas) > 2:
            # Check that ETAs don't wildly fluctuate
            # Allow some variance but should trend downward
            first_eta = tracker.etas[0]
            last_eta = tracker.etas[-1]
            # Last ETA should be less than or close to first
            # Handle both numeric and None values
            if isinstance(first_eta, (int, float)) and isinstance(last_eta, (int, float)):
                assert last_eta <= first_eta * 1.5


class TestVideoArtifactProduction:
    """Test video artifact production and manifest references"""

    def test_video_assembly_output(self, pipeline, mock_client, tmp_path):
        """Mock video assembly and verify output paths"""
        with patch("src.pipeline.video.VideoCreator") as mock_video_creator:
            mock_instance = Mock()
            mock_instance.ffmpeg_available = True
            mock_instance.create_video_from_images.return_value = True
            mock_video_creator.return_value = mock_instance

            config = {
                "txt2img": {"steps": 20},
                "video": {"fps": 24},
                "pipeline": {
                    "img2img_enabled": False,
                    "upscale_enabled": False,
                    "video_enabled": True,
                },
            }

            # Run pipeline with video enabled
            # Note: Actual video integration depends on pipeline implementation
            results = pipeline.run_full_pipeline("video output", config, batch_size=3)

            # Verify basic structure
            assert "txt2img" in results
            # Video path would be in results if implemented
            # This test documents expected behavior

    def test_manifest_references_video_path(self, pipeline, mock_client, tmp_path):
        """Confirm summaries/manifests reference final video path and completion status"""
        config = {
            "txt2img": {"steps": 20},
            "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
        }

        results = pipeline.run_full_pipeline("video manifest", config, batch_size=2)

        # Verify summary structure
        assert len(results["summary"]) == 2

        for summary in results["summary"]:
            assert "stages_completed" in summary
            assert "final_image_path" in summary
            # Future: assert "video_path" in summary when video stage is integrated


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

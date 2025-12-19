"""
Integration test for pipeline batch processing.

Tests that when batch_size > 1, ALL images flow through ALL enabled stages.
"""

from unittest.mock import MagicMock

import pytest

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner


class TestPipelineBatchProcessing:
    """Test that all batch images go through all pipeline stages."""

    @pytest.fixture
    def mock_api_client(self):
        """Create a mock API client."""
        client = MagicMock()
        return client

    @pytest.fixture
    def mock_structured_logger(self):
        """Create a mock structured logger."""
        logger = MagicMock()
        return logger

    @pytest.fixture
    def temp_output_dir(self, tmp_path):
        """Create a temporary output directory."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        return output_dir

    @pytest.fixture
    def pipeline_runner(self, mock_api_client, mock_structured_logger, temp_output_dir):
        """Create a PipelineRunner instance."""
        runner = PipelineRunner(
            api_client=mock_api_client,
            structured_logger=mock_structured_logger,
            runs_base_dir=str(temp_output_dir),
        )
        return runner

    def test_batch_size_2_all_stages_enabled(
        self, pipeline_runner, temp_output_dir, mock_api_client
    ):
        """
        Test that batch_size=2 with all stages enabled processes BOTH images through ALL stages.
        
        Expected flow:
        txt2img generates 2 images → both go to adetailer → both go to upscale
        Final result: 2 upscaled images
        """
        # Create NJR with batch_size=2 and all stages enabled
        njr = NormalizedJobRecord(
            job_id="test_batch_2",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            positive_prompt="A fantasy hero",
            negative_prompt="ugly, blurry",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="Euler a",
            steps=20,
            cfg_scale=7.5,
            width=1024,
            height=1024,
            images_per_prompt=2,  # BATCH SIZE = 2
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
                StageConfig(stage_type="adetailer", enabled=True, extra={"ad_model": "face_yolov8n.pt"}),
                StageConfig(stage_type="upscale", enabled=True, extra={"upscaler_name": "R-ESRGAN 4x+"}),
            ],
        )

        # Mock the executor methods to return fake image paths
        txt2img_base_path = temp_output_dir / "run_id" / "txt2img_00"
        
        # Mock txt2img to return 2 images
        mock_txt2img_result = {
            "path": f"{txt2img_base_path}_batch0.png",
            "all_paths": [
                f"{txt2img_base_path}_batch0.png",
                f"{txt2img_base_path}_batch1.png",
            ],
            "name": "txt2img_00",
            "stage": "txt2img",
        }
        
        # Mock adetailer to return processed image
        def mock_adetailer(input_image_path, config, output_dir, image_name, prompt, negative_prompt, cancel_token=None):
            return {
                "path": str(output_dir / f"{image_name}.png"),
                "name": image_name,
                "stage": "adetailer",
            }
        
        # Mock upscale to return upscaled image
        def mock_upscale(input_image_path, config, output_dir, image_name, cancel_token=None):
            return {
                "path": str(output_dir / f"{image_name}.png"),
                "name": image_name,
                "stage": "upscale",
            }
        
        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_txt2img_result)
        pipeline_runner._pipeline.run_adetailer_stage = MagicMock(side_effect=mock_adetailer)
        pipeline_runner._pipeline.run_upscale_stage = MagicMock(side_effect=mock_upscale)

        # Execute pipeline
        result = pipeline_runner.run_njr(njr)

        # Verify txt2img was called ONCE
        assert pipeline_runner._pipeline.run_txt2img_stage.call_count == 1

        # Verify adetailer was called TWICE (once for each txt2img output)
        assert pipeline_runner._pipeline.run_adetailer_stage.call_count == 2

        # Verify upscale was called TWICE (once for each adetailer output)
        assert pipeline_runner._pipeline.run_upscale_stage.call_count == 2

        # Verify success
        assert result.success is True

    def test_batch_size_3_txt2img_only(
        self, pipeline_runner, temp_output_dir
    ):
        """
        Test that batch_size=3 with only txt2img enabled produces 3 images.
        """
        njr = NormalizedJobRecord(
            job_id="test_batch_3_txt2img_only",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            positive_prompt="A wizard",
            negative_prompt="ugly",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="Euler a",
            steps=15,
            cfg_scale=7.0,
            width=512,
            height=512,
            images_per_prompt=3,  # BATCH SIZE = 3
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
                StageConfig(stage_type="adetailer", enabled=False),
                StageConfig(stage_type="upscale", enabled=False),
            ],
        )

        # Mock txt2img to return 3 images
        txt2img_base_path = temp_output_dir / "run_id" / "txt2img_00"
        mock_txt2img_result = {
            "path": f"{txt2img_base_path}_batch0.png",
            "all_paths": [
                f"{txt2img_base_path}_batch0.png",
                f"{txt2img_base_path}_batch1.png",
                f"{txt2img_base_path}_batch2.png",
            ],
            "name": "txt2img_00",
            "stage": "txt2img",
        }
        
        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_txt2img_result)
        pipeline_runner._pipeline.run_adetailer_stage = MagicMock()
        pipeline_runner._pipeline.run_upscale_stage = MagicMock()

        # Execute pipeline
        result = pipeline_runner.run_njr(njr)

        # Verify txt2img was called ONCE
        assert pipeline_runner._pipeline.run_txt2img_stage.call_count == 1

        # Verify adetailer was NOT called (disabled)
        assert pipeline_runner._pipeline.run_adetailer_stage.call_count == 0

        # Verify upscale was NOT called (disabled)
        assert pipeline_runner._pipeline.run_upscale_stage.call_count == 0

        # Verify success
        assert result.success is True

    def test_batch_size_4_txt2img_and_adetailer(
        self, pipeline_runner, temp_output_dir
    ):
        """
        Test that batch_size=4 with txt2img+adetailer processes all 4 images.
        """
        njr = NormalizedJobRecord(
            job_id="test_batch_4_txt2img_adetailer",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            positive_prompt="A knight",
            negative_prompt="bad quality",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="DPM++ 2M Karras",
            steps=25,
            cfg_scale=8.0,
            width=768,
            height=768,
            images_per_prompt=4,  # BATCH SIZE = 4
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
                StageConfig(stage_type="adetailer", enabled=True, extra={"ad_model": "face_yolov8n.pt"}),
                StageConfig(stage_type="upscale", enabled=False),
            ],
        )

        # Mock txt2img to return 4 images
        txt2img_base_path = temp_output_dir / "run_id" / "txt2img_00"
        mock_txt2img_result = {
            "path": f"{txt2img_base_path}_batch0.png",
            "all_paths": [
                f"{txt2img_base_path}_batch{i}.png" for i in range(4)
            ],
            "name": "txt2img_00",
            "stage": "txt2img",
        }
        
        def mock_adetailer(input_image_path, config, output_dir, image_name, prompt, negative_prompt, cancel_token=None):
            return {
                "path": str(output_dir / f"{image_name}.png"),
                "name": image_name,
                "stage": "adetailer",
            }
        
        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_txt2img_result)
        pipeline_runner._pipeline.run_adetailer_stage = MagicMock(side_effect=mock_adetailer)
        pipeline_runner._pipeline.run_upscale_stage = MagicMock()

        # Execute pipeline
        result = pipeline_runner.run_njr(njr)

        # Verify txt2img was called ONCE
        assert pipeline_runner._pipeline.run_txt2img_stage.call_count == 1

        # Verify adetailer was called 4 TIMES (once for each txt2img output)
        assert pipeline_runner._pipeline.run_adetailer_stage.call_count == 4

        # Verify upscale was NOT called (disabled)
        assert pipeline_runner._pipeline.run_upscale_stage.call_count == 0

        # Verify success
        assert result.success is True

    def test_single_image_backward_compatibility(
        self, pipeline_runner, temp_output_dir
    ):
        """
        Test that batch_size=1 (single image) still works correctly.
        """
        njr = NormalizedJobRecord(
            job_id="test_single_image",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            positive_prompt="A dragon",
            negative_prompt="",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="Euler a",
            steps=20,
            cfg_scale=7.5,
            width=1024,
            height=1024,
            images_per_prompt=1,  # SINGLE IMAGE
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
                StageConfig(stage_type="upscale", enabled=True, extra={"upscaler_name": "R-ESRGAN 4x+"}),
            ],
        )

        # Mock txt2img to return 1 image
        txt2img_base_path = temp_output_dir / "run_id" / "txt2img_00.png"
        mock_txt2img_result = {
            "path": str(txt2img_base_path),
            "all_paths": [str(txt2img_base_path)],  # Single image in list
            "name": "txt2img_00",
            "stage": "txt2img",
        }
        
        def mock_upscale(input_image_path, config, output_dir, image_name, cancel_token=None):
            return {
                "path": str(output_dir / f"{image_name}.png"),
                "name": image_name,
                "stage": "upscale",
            }
        
        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_txt2img_result)
        pipeline_runner._pipeline.run_upscale_stage = MagicMock(side_effect=mock_upscale)

        # Execute pipeline
        result = pipeline_runner.run_njr(njr)

        # Verify txt2img was called ONCE
        assert pipeline_runner._pipeline.run_txt2img_stage.call_count == 1

        # Verify upscale was called ONCE
        assert pipeline_runner._pipeline.run_upscale_stage.call_count == 1

        # Verify success
        assert result.success is True

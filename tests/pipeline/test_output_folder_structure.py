"""
Test for output folder restructure (datetime/pack_name with manifests subfolder).
"""

from unittest.mock import MagicMock

import pytest

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner


class TestOutputFolderStructure:
    """Test that output folders use datetime/pack_name structure with manifests/ subfolder."""

    @pytest.fixture
    def mock_api_client(self):
        """Create a mock API client."""
        return MagicMock()

    @pytest.fixture
    def mock_structured_logger(self):
        """Create a mock structured logger."""
        return MagicMock()

    @pytest.fixture
    def temp_output_dir(self, tmp_path):
        """Create a temporary output directory."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        return output_dir

    @pytest.fixture
    def pipeline_runner(self, mock_api_client, mock_structured_logger, temp_output_dir):
        """Create a PipelineRunner instance."""
        # Clear the class-level folder cache to ensure test isolation
        PipelineRunner._pack_folder_cache.clear()
        runner = PipelineRunner(
            api_client=mock_api_client,
            structured_logger=mock_structured_logger,
            runs_base_dir=str(temp_output_dir),
        )
        return runner

    def test_datetime_pack_name_folder_structure(
        self, pipeline_runner, temp_output_dir
    ):
        """
        Test that output folder structure is: output/{YYYYMMDD_HHMMSS}/{pack_name}/
        """
        njr = NormalizedJobRecord(
            job_id="test_job",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            prompt_pack_name="MyFantasyPack",  # This should be in the folder path
            positive_prompt="A wizard",
            negative_prompt="",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="Euler a",
            steps=20,
            cfg_scale=7.5,
            width=512,
            height=512,
            images_per_prompt=1,
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
            ],
        )

        # Mock txt2img to return a single image
        mock_txt2img_result = {
            "path": f"{temp_output_dir}/txt2img_00.png",
            "all_paths": [f"{temp_output_dir}/txt2img_00.png"],
            "name": "txt2img_00",
            "stage": "txt2img",
        }

        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_txt2img_result)

        # Execute pipeline
        result = pipeline_runner.run_njr(njr)

        # Verify success
        assert result.success is True

        # Verify folder structure exists
        # The actual folder should be {timestamp}/{pack_name}/ or {timestamp_packname}/
        # Let's find the folder that was created
        output_folders = list(temp_output_dir.iterdir())
        assert len(output_folders) > 0, "No output folders created"

        # Find the folder containing pack name
        pack_folder = None
        for folder in output_folders:
            if "MyFantasyPack" in folder.name:
                pack_folder = folder
                break

        assert pack_folder is not None, f"Pack folder not found. Found: {[f.name for f in output_folders]}"
        assert pack_folder.is_dir()

        # Verify it's a datetime format (starts with YYYYMMDD)
        assert pack_folder.name[:8].isdigit(), f"Expected datetime prefix, got {pack_folder.name}"

    def test_manifests_subfolder_created(
        self, pipeline_runner, temp_output_dir
    ):
        """
        Test that the run_dir structure allows for manifests/ subfolder.
        (Actual manifests creation happens in executor methods when real API is called)
        """
        njr = NormalizedJobRecord(
            job_id="test_manifests",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            prompt_pack_name="TestPack",
            positive_prompt="A knight",
            negative_prompt="",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="DPM++ 2M",
            steps=25,
            cfg_scale=8.0,
            width=768,
            height=768,
            images_per_prompt=1,
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
            ],
        )

        # Mock txt2img
        mock_txt2img_result = {
            "path": f"{temp_output_dir}/txt2img_00.png",
            "all_paths": [f"{temp_output_dir}/txt2img_00.png"],
            "name": "txt2img_00",
            "stage": "txt2img",
        }

        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_txt2img_result)

        # Execute pipeline
        result = pipeline_runner.run_njr(njr)

        # Verify success
        assert result.success is True

        # Find the output folder
        output_folders = list(temp_output_dir.iterdir())
        assert len(output_folders) > 0, "No output folders created"

        # Find folder with TestPack in name
        pack_folder = None
        for folder in output_folders:
            if "TestPack" in folder.name:
                pack_folder = folder
                break

        assert pack_folder is not None, f"Pack folder not found. Found: {[f.name for f in output_folders]}"
        assert pack_folder.is_dir(), "Pack folder is not a directory"

        # Verify that manifests subfolder was created by pipeline_runner.__init__
        # (It's created in run_njr before any stages execute)
        manifests_folder = pack_folder / "manifests"
        assert manifests_folder.exists(), "manifests/ subfolder not created by pipeline_runner"
        assert manifests_folder.is_dir(), "manifests/ is not a directory"

    def test_sanitized_pack_name(
        self, pipeline_runner, temp_output_dir
    ):
        """
        Test that pack names with special characters are sanitized for filesystem.
        """
        njr = NormalizedJobRecord(
            job_id="test_sanitize",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            prompt_pack_name="My/Pack:Name*With?Special<>Chars",  # Should be sanitized
            positive_prompt="A dragon",
            negative_prompt="",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="Euler a",
            steps=20,
            cfg_scale=7.5,
            width=1024,
            height=1024,
            images_per_prompt=1,
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
            ],
        )

        # Mock txt2img
        mock_txt2img_result = {
            "path": f"{temp_output_dir}/txt2img_00.png",
            "all_paths": [f"{temp_output_dir}/txt2img_00.png"],
            "name": "txt2img_00",
            "stage": "txt2img",
        }

        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_txt2img_result)

        # Execute pipeline
        result = pipeline_runner.run_njr(njr)

        # Verify success
        assert result.success is True

        # Find the output folder
        output_folders = list(temp_output_dir.iterdir())
        pack_folder = None
        for folder in output_folders:
            # Should contain sanitized pack name
            if "My_Pack" in folder.name or "Chars" in folder.name:
                pack_folder = folder
                break

        assert pack_folder is not None, f"Sanitized pack folder not found. Found: {[f.name for f in output_folders]}"

        # Verify no special characters in folder name (only alphanumeric, -, _)
        import re
        assert re.match(r'^[a-zA-Z0-9_-]+$', pack_folder.name), f"Folder name contains special chars: {pack_folder.name}"

    def test_fallback_to_job_id_when_no_pack_name(
        self, pipeline_runner, temp_output_dir
    ):
        """
        Test that job_id is used when prompt_pack_name is empty.
        """
        njr = NormalizedJobRecord(
            job_id="my_unique_job_123",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            prompt_pack_name="",  # Empty - should fallback to job_id
            positive_prompt="A hero",
            negative_prompt="",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="Euler a",
            steps=20,
            cfg_scale=7.5,
            width=512,
            height=512,
            images_per_prompt=1,
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
            ],
        )

        # Mock txt2img
        mock_txt2img_result = {
            "path": f"{temp_output_dir}/txt2img_00.png",
            "all_paths": [f"{temp_output_dir}/txt2img_00.png"],
            "name": "txt2img_00",
            "stage": "txt2img",
        }

        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_txt2img_result)

        # Execute pipeline
        result = pipeline_runner.run_njr(njr)

        # Verify success
        assert result.success is True

        # Find the output folder
        output_folders = list(temp_output_dir.iterdir())
        pack_folder = None
        for folder in output_folders:
            if "my_unique_job_123" in folder.name:
                pack_folder = folder
                break

        assert pack_folder is not None, f"Job ID folder not found. Found: {[f.name for f in output_folders]}"

    def test_multiple_jobs_same_pack_share_folder(
        self, pipeline_runner, temp_output_dir
    ):
        """
        Test that multiple jobs from the same prompt pack share the same output folder.
        """
        # Create 3 NJRs with the same pack name
        njrs = []
        for i in range(3):
            njr = NormalizedJobRecord(
                job_id=f"test_job_{i}",
                config={},
                path_output_dir=str(temp_output_dir),
                filename_template="image_{index:04d}",
                prompt_pack_name="SharedPack",  # Same pack name for all
                positive_prompt=f"A hero #{i}",
                negative_prompt="",
                base_model="sd_xl_base_1.0.safetensors",
                sampler_name="Euler a",
                steps=20,
                cfg_scale=7.5,
                width=512,
                height=512,
                images_per_prompt=1,
                stage_chain=[
                    StageConfig(stage_type="txt2img", enabled=True),
                ],
            )
            njrs.append(njr)

        # Mock txt2img for all jobs
        mock_results = [
            {
                "path": f"{temp_output_dir}/txt2img_{i:02d}.png",
                "all_paths": [f"{temp_output_dir}/txt2img_{i:02d}.png"],
                "name": f"txt2img_{i:02d}",
                "stage": "txt2img",
            }
            for i in range(3)
        ]

        # Execute all 3 jobs
        folder_paths = set()
        for i, njr in enumerate(njrs):
            pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_results[i])
            result = pipeline_runner.run_njr(njr)
            assert result.success is True
            
            # Track which folder was used
            output_folders = list(temp_output_dir.iterdir())
            for folder in output_folders:
                if "SharedPack" in folder.name:
                    folder_paths.add(str(folder))

        # All 3 jobs should use the SAME folder (consolidated by pack)
        assert len(folder_paths) == 1, f"Expected 1 shared folder, found {len(folder_paths)}: {folder_paths}"
        
        # Verify the shared folder contains files from all 3 jobs
        shared_folder = temp_output_dir / list(folder_paths)[0].split("/")[-1]
        # Note: Files are actually saved by executor, not by pipeline_runner in this mock setup
        # So we just verify the folder reuse logic worked

    def test_different_packs_get_different_folders(
        self, pipeline_runner, temp_output_dir
    ):
        """
        Test that jobs from different packs get different folders.
        """
        # Create 2 NJRs with different pack names
        njr1 = NormalizedJobRecord(
            job_id="test_job_1",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            prompt_pack_name="PackA",
            positive_prompt="A wizard",
            negative_prompt="",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="Euler a",
            steps=20,
            cfg_scale=7.5,
            width=512,
            height=512,
            images_per_prompt=1,
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
            ],
        )

        njr2 = NormalizedJobRecord(
            job_id="test_job_2",
            config={},
            path_output_dir=str(temp_output_dir),
            filename_template="image_{index:04d}",
            prompt_pack_name="PackB",  # Different pack
            positive_prompt="A warrior",
            negative_prompt="",
            base_model="sd_xl_base_1.0.safetensors",
            sampler_name="Euler a",
            steps=20,
            cfg_scale=7.5,
            width=512,
            height=512,
            images_per_prompt=1,
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True),
            ],
        )

        # Mock txt2img
        mock_result_1 = {
            "path": f"{temp_output_dir}/txt2img_00.png",
            "all_paths": [f"{temp_output_dir}/txt2img_00.png"],
            "name": "txt2img_00",
            "stage": "txt2img",
        }
        mock_result_2 = {
            "path": f"{temp_output_dir}/txt2img_01.png",
            "all_paths": [f"{temp_output_dir}/txt2img_01.png"],
            "name": "txt2img_01",
            "stage": "txt2img",
        }

        # Execute both jobs
        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_result_1)
        result1 = pipeline_runner.run_njr(njr1)
        assert result1.success is True

        pipeline_runner._pipeline.run_txt2img_stage = MagicMock(return_value=mock_result_2)
        result2 = pipeline_runner.run_njr(njr2)
        assert result2.success is True

        # Find both folders
        output_folders = list(temp_output_dir.iterdir())
        pack_a_folder = None
        pack_b_folder = None
        
        for folder in output_folders:
            if "PackA" in folder.name:
                pack_a_folder = folder
            elif "PackB" in folder.name:
                pack_b_folder = folder

        # Both folders should exist and be different
        assert pack_a_folder is not None, "PackA folder not found"
        assert pack_b_folder is not None, "PackB folder not found"
        assert pack_a_folder != pack_b_folder, "Different packs should have different folders"

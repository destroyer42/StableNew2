"""Test variant numbering for matrix-expanded prompt packs."""

from unittest.mock import MagicMock, patch

import pytest

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder


class TestVariantNumbering:
    """Test that variant indices are numbered correctly across matrix combinations."""

    @pytest.fixture
    def mock_config_manager(self):
        """Create mock ConfigManager."""
        manager = MagicMock()
        manager.resolve_config.return_value = {
            "pipeline": {"output_dir": "output"},
            "txt2img": {
                "model": "test_model.safetensors",
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "sampler_name": "Euler",
            },
            "randomization": {},
        }
        manager.get_global_negative_prompt.return_value = ""
        return manager

    @pytest.fixture
    def mock_job_builder(self):
        """Create mock JobBuilderV2."""
        builder = MagicMock(spec=JobBuilderV2)
        
        def build_jobs_side_effect(**kwargs):
            # Simulate building 1 job with variant_index=0 (what happens before fix)
            job = NormalizedJobRecord(
                job_id="test_job_id",
                config=kwargs.get("base_config", {}),
                path_output_dir=kwargs.get("output_settings").base_output_dir,
                filename_template="{seed}",
                seed=12345,
                variant_index=0,  # Always starts at 0
                variant_total=1,
                batch_index=0,
                batch_total=1,
            )
            return [job]
        
        builder.build_jobs.side_effect = build_jobs_side_effect
        return builder

    @patch("src.pipeline.prompt_pack_job_builder.load_pack_metadata")
    @patch("src.pipeline.prompt_pack_job_builder.parse_prompt_pack_text")
    def test_variant_indices_sequential_across_matrix(
        self,
        mock_parse,
        mock_load_metadata,
        mock_config_manager,
        mock_job_builder,
    ):
        """Test that matrix combinations get sequential variant indices v01, v02, v03, etc."""
        
        # Setup: Pack with 3 matrix combinations
        mock_load_metadata.return_value = {
            "pack_data": {
                "matrix": {
                    "mode": "sequential",
                    "slots": {
                        "job": ["wizard", "knight", "archer"],
                    }
                }
            }
        }
        
        mock_parse.return_value = [
            MagicMock(
                embeddings=(),
                quality_line="A {job} character",
                subject_template="A {job} character",
                lora_tags=(),
                negative_embeddings=(),
                negative_phrases=("bad quality",),
            )
        ]
        
        builder = PromptPackNormalizedJobBuilder(
            config_manager=mock_config_manager,
            job_builder=mock_job_builder,
            packs_dir="packs",
        )
        
        # Create single pack entry
        entry = PackJobEntry(
            pack_id="test_pack",
            pack_name="Test Pack",
            pack_row_index=0,
            prompt_text="A {job} character",
            negative_prompt_text="bad quality",
        )
        
        # Execute
        with patch.object(builder, "_resolve_pack_text_path", return_value="packs/test_pack.txt"):
            jobs = builder.build_jobs([entry])
        
        # Verify: Should have 3 jobs (one per matrix combination)
        assert len(jobs) == 3, f"Expected 3 jobs but got {len(jobs)}"
        
        # Verify: Each job has unique variant_index (0, 1, 2)
        variant_indices = [job.variant_index for job in jobs]
        assert variant_indices == [0, 1, 2], f"Expected [0, 1, 2] but got {variant_indices}"
        
        # Verify: All jobs have variant_total=3
        for job in jobs:
            assert job.variant_total == 3, f"Expected variant_total=3 but got {job.variant_total}"
        
        # Verify: Matrix slot values are set correctly
        assert jobs[0].matrix_slot_values == {"job": "wizard"}
        assert jobs[1].matrix_slot_values == {"job": "knight"}
        assert jobs[2].matrix_slot_values == {"job": "archer"}

    @patch("src.pipeline.prompt_pack_job_builder.load_pack_metadata")
    @patch("src.pipeline.prompt_pack_job_builder.parse_prompt_pack_text")
    def test_variant_indices_no_matrix(
        self,
        mock_parse,
        mock_load_metadata,
        mock_config_manager,
        mock_job_builder,
    ):
        """Test that non-matrix packs preserve original variant numbering."""
        
        # Setup: Pack with no matrix
        mock_load_metadata.return_value = {}
        
        mock_parse.return_value = [
            MagicMock(
                embeddings=(),
                quality_line="A wizard character",
                subject_template="A wizard character",
                lora_tags=(),
                negative_embeddings=(),
                negative_phrases=("bad quality",),
            )
        ]
        
        builder = PromptPackNormalizedJobBuilder(
            config_manager=mock_config_manager,
            job_builder=mock_job_builder,
            packs_dir="packs",
        )
        
        entry = PackJobEntry(
            pack_id="test_pack",
            pack_name="Test Pack",
            pack_row_index=0,
            prompt_text="A wizard character",
            negative_prompt_text="bad quality",
        )
        
        # Execute
        with patch.object(builder, "_resolve_pack_text_path", return_value="packs/test_pack.txt"):
            jobs = builder.build_jobs([entry])
        
        # Verify: Should have 1 job (no matrix expansion)
        assert len(jobs) == 1, f"Expected 1 job but got {len(jobs)}"
        
        # Verify: Variant index unchanged
        assert jobs[0].variant_index == 0
        assert jobs[0].variant_total == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

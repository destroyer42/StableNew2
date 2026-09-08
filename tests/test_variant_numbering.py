"""Test variant numbering for matrix-expanded prompt packs."""

import json
from unittest.mock import MagicMock

import pytest

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION


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

    def test_variant_indices_sequential_across_matrix(
        self,
        mock_config_manager,
        tmp_path,
    ):
        """Test that matrix combinations get sequential variant indices v01, v02, v03, etc."""

        pack_path = tmp_path / "test_pack.json"
        pack_path.write_text(
            json.dumps(
                {
                    "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                    "pack_data": {
                        "slots": [{"index": 0, "text": "A [[job]] character"}],
                        "matrix": {
                            "enabled": True,
                            "mode": "sequential",
                            "slots": [
                                {"name": "job", "values": ["wizard", "knight", "archer"]},
                            ],
                        },
                    },
                    "preset_data": {},
                }
            ),
            encoding="utf-8",
        )

        builder = PromptPackNormalizedJobBuilder(
            config_manager=mock_config_manager,
            job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=lambda: "test-job"),
            packs_dir=tmp_path,
        )
        # Create single pack entry
        entry = PackJobEntry(
            pack_id="test_pack.json",
            pack_name="Test Pack",
            config_snapshot={},
            pack_row_index=0,
            prompt_text="A [[job]] character",
            negative_prompt_text="bad quality",
        )

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

    def test_variant_indices_no_matrix(
        self,
        mock_config_manager,
        tmp_path,
    ):
        """Test that non-matrix packs preserve original variant numbering."""

        pack_path = tmp_path / "test_pack.json"
        pack_path.write_text(
            json.dumps(
                {
                    "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                    "pack_data": {
                        "slots": [{"index": 0, "text": "A wizard character"}],
                        "matrix": {"enabled": False, "slots": []},
                    },
                    "preset_data": {},
                }
            ),
            encoding="utf-8",
        )

        builder = PromptPackNormalizedJobBuilder(
            config_manager=mock_config_manager,
            job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=lambda: "test-job"),
            packs_dir=tmp_path,
        )
        entry = PackJobEntry(
            pack_id="test_pack.json",
            pack_name="Test Pack",
            config_snapshot={},
            pack_row_index=0,
            prompt_text="A wizard character",
            negative_prompt_text="bad quality",
        )

        jobs = builder.build_jobs([entry])

        # Verify: Should have 1 job (no matrix expansion)
        assert len(jobs) == 1, f"Expected 1 job but got {len(jobs)}"

        # Verify: Variant index unchanged
        assert jobs[0].variant_index == 0
        assert jobs[0].variant_total == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

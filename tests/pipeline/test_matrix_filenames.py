"""Test matrix expansion filename uniqueness."""

import json
import tempfile
from pathlib import Path
from typing import Any
from dataclasses import dataclass

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.pipeline.resolution_layer import UnifiedPromptResolver
from src.utils.config import ConfigManager


BASE_PACK_CONFIG: dict[str, Any] = {
    "pipeline": {
        "images_per_prompt": 1,
        "loop_count": 1,
        "loop_type": "pipeline",
        "variant_mode": "standard",
        "apply_global_negative_txt2img": True,
        "output_dir": "output",
        "filename_pattern": "{seed}",
    },
    "txt2img": {
        "model": "test_model.safetensors",
        "sampler_name": "DPM++ 2M",
        "scheduler": "karras",
        "steps": 20,
        "cfg_scale": 7.5,
        "width": 1024,
        "height": 1024,
        "negative_prompt": "",
        "seed": 12345,  # FIXED SEED
    },
    "randomization": {"enabled": False},
    "aesthetic": {"enabled": False},
}


class StubConfigManager(ConfigManager):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(presets_dir=tmp_path / "presets")
        self.packs_dir = tmp_path / "packs"
        self.packs_dir.mkdir(parents=True, exist_ok=True)
        self._config = dict(BASE_PACK_CONFIG)

    def load_pack_config(self, pack_id: str) -> dict[str, Any] | None:
        return dict(self._config)

    def resolve_config(
        self,
        *,
        pack_overrides: dict[str, Any] | None = None,
        runtime_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = dict(self._config)
        if pack_overrides:
            merged.update(pack_overrides)
        if runtime_params:
            merged.update(runtime_params)
        return merged

    def get_global_negative_prompt(self) -> str:
        return "global-negative"


@dataclass
class SequentialIdGenerator:
    """Simple deterministic ID generator for JobBuilderV2 tests."""

    counter: int = 0

    def __call__(self) -> str:
        self.counter += 1
        return f"job-{self.counter}"


def test_matrix_filename_uniqueness():
    """Test that matrix-expanded jobs have unique filenames."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        packs_dir = tmpdir_path / "packs"
        packs_dir.mkdir()
        
        # Create a test pack with matrix config
        pack_json = {
            "pack_data": {
                "name": "filename_test",
                "slots": [],
                "matrix": {
                    "enabled": True,
                    "mode": "fanout",
                    "limit": 4,
                    "slots": [
                        {"name": "job", "values": ["wizard", "knight"]},
                        {"name": "environment", "values": ["forest", "castle"]}
                    ]
                }
            },
            "preset_data": BASE_PACK_CONFIG
        }
        
        pack_path = packs_dir / "filename_test.json"
        with open(pack_path, "w", encoding="utf-8") as f:
            json.dump(pack_json, f, indent=2)
        
        pack_txt_path = packs_dir / "filename_test.txt"
        with open(pack_txt_path, "w", encoding="utf-8") as f:
            f.write("A [[job]] in [[environment]]\\n")
        
        # Create builder
        config_mgr = StubConfigManager(tmpdir_path)
        job_builder = JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator())
        
        builder = PromptPackNormalizedJobBuilder(
            config_manager=config_mgr,
            job_builder=job_builder,
            prompt_resolver=UnifiedPromptResolver(),
            packs_dir=packs_dir,
        )
        
        # Create one entry (will be expanded to 4 by matrix)
        entry = PackJobEntry(
            pack_id="filename_test.txt",
            pack_name="Filename Test",
            pack_row_index=0,
            prompt_text="",
            negative_prompt_text="",
            config_snapshot={"txt2img": {"seed": 12345}},  # FIXED SEED
            stage_flags={"txt2img": True},
            matrix_slot_values={},
            randomizer_metadata=None,
        )
        
        print("\\nTest: Matrix Expansion Filename Uniqueness")
        print("="*60)
        print("Matrix: 2 jobs × 2 environments = 4 combinations, limit=4")
        print("Seed: 12345 (FIXED - same for all variants)")
        print()
        
        # Build jobs
        jobs = builder.build_jobs([entry])
        
        print(f"Total jobs created: {len(jobs)}")
        print()
        
        # Extract filenames
        filenames = []
        for i, job in enumerate(jobs):
            template = job.filename_template
            seed = job.seed or 12345
            # Simulate filename generation (replace {seed} with actual seed)
            filename = template.replace("{seed}", str(seed)) + ".png"
            matrix_values = job.matrix_slot_values
            
            print(f"Job {i+1}:")
            print(f"  Matrix: {matrix_values}")
            print(f"  Template: {template}")
            print(f"  Seed: {seed}")
            print(f"  Filename: {filename}")
            print()
            
            filenames.append(filename)
        
        # Check for duplicates
        unique_filenames = set(filenames)
        duplicates = [f for f in filenames if filenames.count(f) > 1]
        
        print("="*60)
        print(f"Total filenames: {len(filenames)}")
        print(f"Unique filenames: {len(unique_filenames)}")
        
        if len(unique_filenames) == len(filenames):
            print("\\n✅ TEST PASSED: All filenames are unique!")
        else:
            print(f"\\n❌ TEST FAILED: Found {len(duplicates)} duplicate filenames!")
            print("Duplicates:")
            for dup in set(duplicates):
                count = filenames.count(dup)
                print(f"  {dup} appears {count} times")

if __name__ == "__main__":
    test_matrix_filename_uniqueness()

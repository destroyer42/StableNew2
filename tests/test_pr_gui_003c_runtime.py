"""Test PR-GUI-003-C: Matrix runtime integration.

Verifies that matrix slots defined in pack JSON are:
1. Loaded during job building
2. Expanded into combinations
3. Used to replace [[tokens]] in prompts
"""

from pathlib import Path

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.pipeline.resolution_layer import UnifiedPromptResolver
from src.utils.config import ConfigManager


def test_matrix_expansion_loads_from_json():
    """Test that matrix slots are loaded from pack JSON and expanded."""
    config_mgr = ConfigManager()
    job_builder = JobBuilderV2()
    prompt_resolver = UnifiedPromptResolver()
    
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_mgr,
        job_builder=job_builder,
        prompt_resolver=prompt_resolver,
    )
    
    # Create entry pointing to test pack (use just filename, builder adds packs/ dir)
    entry = PackJobEntry(
        pack_id="test_matrix_pack.txt",  # Just filename, not full path
        pack_name="Test Matrix Pack",
        pack_row_index=0,
        prompt_text="",
        negative_prompt_text="",
        config_snapshot={
            "txt2img": {
                "model": "test_model.safetensors",
                "steps": 20,
                "cfg_scale": 7.5,
                "sampler_name": "DPM++ 2M",
                "scheduler": "karras",
                "width": 1024,
                "height": 1024,
                "seed": 12345,
            },
            "pipeline": {},
            "randomization": {},
        },
        stage_flags={"txt2img": True},
        matrix_slot_values={},  # Empty - will be populated by expansion
        randomizer_metadata=None,
    )
    
    # Expand entry by matrix
    expanded_entries = builder._expand_entry_by_matrix(entry)
    
    # Should have 4 combinations: wizard+forest, wizard+castle, knight+forest, knight+castle
    assert len(expanded_entries) == 4, f"Expected 4 expanded entries, got {len(expanded_entries)}"
    
    # Check matrix_slot_values are set correctly
    expected_combos = [
        {"job": "wizard", "environment": "forest"},
        {"job": "wizard", "environment": "castle"},
        {"job": "knight", "environment": "forest"},
        {"job": "knight", "environment": "castle"},
    ]
    
    for idx, expanded in enumerate(expanded_entries):
        assert expanded.matrix_slot_values == expected_combos[idx], \
            f"Entry {idx}: expected {expected_combos[idx]}, got {expanded.matrix_slot_values}"
    
    print("✅ Matrix expansion loads from JSON and creates correct combinations")


def test_matrix_tokens_replaced_in_prompts():
    """Test that [[tokens]] are replaced with matrix values in prompts."""
    config_mgr = ConfigManager()
    job_builder = JobBuilderV2()
    prompt_resolver = UnifiedPromptResolver()
    
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_mgr,
        job_builder=job_builder,
        prompt_resolver=prompt_resolver,
    )
    
    pack_path = Path("packs/test_matrix_pack.txt")
    
    entry = PackJobEntry(
        pack_id="test_matrix_pack.txt",  # Just filename, not full path
        pack_name="Test Matrix Pack",
        pack_row_index=0,
        prompt_text="",
        negative_prompt_text="",
        config_snapshot={
            "txt2img": {
                "model": "test_model.safetensors",
                "steps": 20,
                "cfg_scale": 7.5,
                "sampler_name": "DPM++ 2M",
                "scheduler": "karras",
                "width": 1024,
                "height": 1024,
                "seed": 12345,
            },
            "pipeline": {},
            "randomization": {},
        },
        stage_flags={"txt2img": True},
        matrix_slot_values={},
        randomizer_metadata=None,
    )
    
    # Build jobs (which expands and resolves prompts)
    jobs = builder.build_jobs([entry])
    
    # Should have 4 jobs, one per matrix combination
    assert len(jobs) == 4, f"Expected 4 jobs, got {len(jobs)}"

    # Check that prompts have [[tokens]] replaced
    for idx, job in enumerate(jobs):
        prompt = job.positive_prompt
        # Prompt should contain the expanded values, not [[tokens]]
        assert "[[job]]" not in prompt, f"Job {idx}: [[job]] token not replaced in prompt"
        assert "[[environment]]" not in prompt, f"Job {idx}: [[environment]] token not replaced in prompt"
        
        # Check specific expected values
        if idx == 0:
            assert "wizard" in prompt and "forest" in prompt
        elif idx == 1:
            assert "wizard" in prompt and "castle" in prompt
        elif idx == 2:
            assert "knight" in prompt and "forest" in prompt
        elif idx == 3:
            assert "knight" in prompt and "castle" in prompt
        
        print(f"Job {idx}: {prompt}")
    
    print("✅ Matrix tokens replaced correctly in all job prompts")


if __name__ == "__main__":
    test_matrix_expansion_loads_from_json()
    test_matrix_tokens_replaced_in_prompts()
    print("\n✅ All PR-GUI-003-C runtime integration tests passed!")

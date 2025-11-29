#!/usr/bin/env python3
"""
Debug script to test batch processing logic
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from utils.file_io import get_prompt_packs, read_prompt_pack


def test_batch_processing():
    """Test the batch processing logic"""
    packs_dir = Path("packs")

    # Get all available packs
    all_packs = get_prompt_packs(packs_dir)
    print(f"Found {len(all_packs)} packs:")
    for pack in all_packs:
        print(f"  - {pack.name}")

    # Simulate processing each pack
    pack_count = 0
    for pack_file in all_packs:
        pack_count += 1
        print(f"\n--- Processing pack {pack_count}: {pack_file.name} ---")

        try:
            # Read prompts from pack
            prompts = read_prompt_pack(pack_file)
            print(f"  Found {len(prompts)} prompts")

            if not prompts:
                print(f"  WARNING: No prompts found in {pack_file.name}")
                continue

            # Show first prompt for verification
            if prompts:
                first_prompt = (
                    prompts[0]["positive"][:100] + "..."
                    if len(prompts[0]["positive"]) > 100
                    else prompts[0]["positive"]
                )
                print(f"  First prompt: {first_prompt}")

        except Exception as e:
            print(f"  ERROR processing {pack_file.name}: {e}")
            continue

    print(f"\nCompleted processing {pack_count} packs")


if __name__ == "__main__":
    test_batch_processing()

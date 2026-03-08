"""Test that image filename generation respects Windows MAX_PATH limits."""

from pathlib import Path
from src.utils.file_io import build_safe_image_name

def test_safe_image_names():
    """Verify that build_safe_image_name() produces short, unique, safe filenames."""
    
    print("\n" + "="*80)
    print("TEST: Safe Image Filename Generation (Windows MAX_PATH Fix)")
    print("="*80)
    
    # Test Case 1: Very long matrix values (the actual bug scenario)
    print("\n=== Test Case 1: Long matrix values (typical bug scenario) ===")
    base_prefix = "txt2img_p00_00"
    long_matrix = {
        "hair_color": "platinum_blonde_silver-gray",
        "lighting": "moonlit_illumination",
        "composition": "off-center_composition",
        "pose": "relaxed_confident_stance_gripping_a_weapon",
        "location": "windswept_mountain_pass_after_the_magic_was_unleashed",
        "character": "twin_mirrored_figures",
        "clothing": "flowing_mage_robes"
    }
    
    # OLD behavior (what was causing the bug):
    old_style = f"{base_prefix}_{'_'.join(str(v) for v in long_matrix.values())}_batch0.png"
    print(f"\nOLD (broken) filename length: {len(old_style)} chars")
    print(f"OLD filename: {old_style[:100]}..." if len(old_style) > 100 else f"OLD filename: {old_style}")
    
    # NEW behavior (fixed):
    new_name = build_safe_image_name(
        base_prefix=base_prefix,
        matrix_values=long_matrix,
        seed=12345,
        batch_index=0,
        max_length=100
    )
    new_style = f"{new_name}.png"
    print(f"\nNEW (fixed) filename length: {len(new_style)} chars")
    print(f"NEW filename: {new_style}")
    
    assert len(new_style) <= 104, f"Filename too long: {len(new_style)} chars"
    print(f"✅ NEW filename within safe limits ({len(new_style)} <= 104 chars)")
    
    # Test Case 2: Uniqueness - different matrix values should produce different hashes
    print("\n=== Test Case 2: Uniqueness guarantee ===")
    matrix1 = {"hair": "blonde", "eyes": "blue"}
    matrix2 = {"hair": "red", "eyes": "green"}
    
    name1 = build_safe_image_name(base_prefix, matrix1, seed=12345)
    name2 = build_safe_image_name(base_prefix, matrix2, seed=12345)
    
    print(f"Matrix 1: {name1}")
    print(f"Matrix 2: {name2}")
    
    assert name1 != name2, "Different matrix values must produce different names"
    print("✅ Different matrix values produce unique names")
    
    # Test Case 3: Stability - same inputs produce same output
    print("\n=== Test Case 3: Deterministic/stable naming ===")
    name_a = build_safe_image_name(base_prefix, long_matrix, seed=12345, batch_index=0)
    name_b = build_safe_image_name(base_prefix, long_matrix, seed=12345, batch_index=0)
    
    assert name_a == name_b, "Same inputs must produce same name (deterministic)"
    print(f"Run 1: {name_a}")
    print(f"Run 2: {name_b}")
    print("✅ Naming is deterministic and stable")
    
    # Test Case 4: Batch index differentiation
    print("\n=== Test Case 4: Batch index uniqueness ===")
    batch0 = build_safe_image_name(base_prefix, long_matrix, seed=12345, batch_index=0)
    batch1 = build_safe_image_name(base_prefix, long_matrix, seed=12345, batch_index=1)
    
    print(f"Batch 0: {batch0}")
    print(f"Batch 1: {batch1}")
    
    assert batch0 != batch1, "Different batch indices must produce different names"
    assert "_batch0" in batch0 and "_batch1" in batch1, "Batch indices must be explicit"
    print("✅ Batch indices create unique names")
    
    # Test Case 5: Windows path length validation
    print("\n=== Test Case 5: Full path length validation ===")
    output_dir = Path("C:/Users/rob/projects/StableNew/output/20251222_154625_Single-Prompt-Crazy")
    full_path = output_dir / f"{new_name}.png"
    full_path_str = str(full_path)
    
    print(f"Full path length: {len(full_path_str)} chars")
    print(f"Full path: {full_path_str}")
    
    # Windows MAX_PATH is 260 chars
    assert len(full_path_str) < 260, f"Full path too long for Windows: {len(full_path_str)} >= 260"
    print(f"✅ Full path within Windows MAX_PATH limit ({len(full_path_str)} < 260)")
    
    print("\n" + "="*80)
    print("✅ ALL TESTS PASSED - Filename generation is safe!")
    print("="*80)
    print("\n📝 Summary:")
    print("  BEFORE: Long matrix values created 200+ char filenames → Errno 2")
    print("  AFTER:  Hash-based names stay under 100 chars → Always saves successfully")
    print("\n🔧 Implementation:")
    print("  - Added build_safe_image_name() in file_io.py")
    print("  - Updated pipeline_runner.py to use it for txt2img, adetailer, upscale")
    print("  - Hash ensures uniqueness even after truncation")
    print("  - Batch indices remain explicit and readable")
    print()

if __name__ == "__main__":
    test_safe_image_names()

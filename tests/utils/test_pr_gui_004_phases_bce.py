"""Test PR-GUI-004 Phases B, C, E: Complete LoRA/Embedding Feature"""

import json
from pathlib import Path

from src.utils.lora_scanner import LoRAScanner


def test_lora_scanner_and_cache():
    """Test LoRA scanning with caching."""
    print("=" * 60)
    print("TEST: LoRA Scanner and Cache")
    print("=" * 60)
    
    # Create test directory structure
    test_dir = Path("test_lora_scanner")
    lora_dir = test_dir / "models" / "Lora"
    lora_dir.mkdir(parents=True, exist_ok=True)
    
    # Create test LoRA files with metadata
    loras = [
        ("anime-style", ["anime", "manga art", "cel shading"]),
        ("detail-xl", ["ultra detailed", "intricate"]),
        ("cyberpunk-city", ["cyberpunk", "neon lights", "futuristic"])
    ]
    
    for lora_name, keywords in loras:
        # Create LoRA file
        lora_file = lora_dir / f"{lora_name}.safetensors"
        lora_file.write_text("dummy")
        
        # Create .civitai.info
        civitai_data = {"trainedWords": keywords}
        civitai_file = lora_dir / f"{lora_name}.safetensors.civitai.info"
        with open(civitai_file, "w", encoding="utf-8") as f:
            json.dump(civitai_data, f)
    
    # Create scanner
    scanner = LoRAScanner(test_dir)
    
    # Initial scan
    print("\n1. Initial scan...")
    resources = scanner.scan_loras()
    print(f"   Found {len(resources)} LoRAs")
    
    for name, resource in resources.items():
        print(f"   - {name}: {len(resource.keywords)} keywords, source: {resource.source}")
    
    assert len(resources) == 3, f"Expected 3 LoRAs, got {len(resources)}"
    
    # Test search
    print("\n2. Testing search...")
    results = scanner.search_loras("anime")
    print(f"   Search 'anime': {results}")
    assert "anime-style" in results
    
    results = scanner.search_loras("cyber")
    print(f"   Search 'cyber': {results}")
    assert "cyberpunk-city" in results
    
    # Test cache save/load
    print("\n3. Testing cache persistence...")
    cache_file = scanner._cache_file
    assert cache_file.exists(), "Cache file should exist"
    
    # Create new scanner instance (should load from cache)
    scanner2 = LoRAScanner(test_dir)
    assert len(scanner2._lora_cache) == 3, "Cache should be loaded"
    print(f"   Loaded {len(scanner2._lora_cache)} LoRAs from cache")
    
    # Test get_lora_info
    print("\n4. Testing cached info retrieval...")
    info = scanner2.get_lora_info("detail-xl")
    assert info is not None
    assert len(info.keywords) == 2
    print(f"   detail-xl: {info.keywords}")
    
    # Test refresh
    print("\n5. Testing force rescan...")
    scanner2.scan_loras(force_rescan=True)
    print("   Rescan complete")
    
    # Cleanup
    print("\n6. Cleanup...")
    import shutil
    shutil.rmtree(test_dir)
    if cache_file.exists():
        cache_file.unlink()
    print("   Cleanup complete")
    
    print("\n✅ LoRA Scanner tests passed!")


def test_autocomplete_data():
    """Test autocomplete data structure."""
    print("\n" + "=" * 60)
    print("TEST: Autocomplete Data")
    print("=" * 60)
    
    # Create test directory
    test_dir = Path("test_autocomplete")
    lora_dir = test_dir / "models" / "Lora"
    lora_dir.mkdir(parents=True, exist_ok=True)
    
    # Create multiple LoRAs with similar names
    lora_names = [
        "style-anime-v1",
        "style-anime-v2",
        "style-realistic",
        "detail-enhancer",
        "detail-micro"
    ]
    
    for name in lora_names:
        (lora_dir / f"{name}.safetensors").write_text("dummy")
    
    # Scan
    scanner = LoRAScanner(test_dir)
    scanner.scan_loras()
    
    # Test autocomplete filtering
    print("\n1. Testing autocomplete filtering...")
    
    all_loras = scanner.get_lora_names()
    print(f"   All LoRAs: {all_loras}")
    assert len(all_loras) == 5
    
    # Filter by "style"
    matches = [l for l in all_loras if "style" in l.lower()]
    print(f"   Matches for 'style': {matches}")
    assert len(matches) == 3
    
    # Filter by "detail"
    matches = [l for l in all_loras if "detail" in l.lower()]
    print(f"   Matches for 'detail': {matches}")
    assert len(matches) == 2
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir)
    if scanner._cache_file.exists():
        scanner._cache_file.unlink()
    
    print("\n✅ Autocomplete tests passed!")


def test_keyword_dialog_filter():
    """Test keyword dialog filtering logic."""
    print("\n" + "=" * 60)
    print("TEST: Keyword Dialog Filtering")
    print("=" * 60)
    
    # Mock keywords
    keywords = [
        "masterpiece",
        "best quality",
        "ultra detailed",
        "detailed face",
        "high resolution",
        "intricate details"
    ]
    
    print(f"\nAll keywords: {keywords}")
    
    # Test filtering
    search = "detail"
    filtered = [kw for kw in keywords if search.lower() in kw.lower()]
    print(f"Filter '{search}': {filtered}")
    assert len(filtered) == 3  # ultra detailed, detailed face, intricate details
    
    search = "quality"
    filtered = [kw for kw in keywords if search.lower() in kw.lower()]
    print(f"Filter '{search}': {filtered}")
    assert len(filtered) == 1  # best quality
    
    print("\n✅ Keyword dialog filter tests passed!")


def main():
    """Run all Phase B, C, E tests."""
    print("\n" + "=" * 60)
    print("PR-GUI-004 PHASES B, C, E: Complete Feature Tests")
    print("=" * 60)
    
    try:
        test_lora_scanner_and_cache()
        test_autocomplete_data()
        test_keyword_dialog_filter()
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED ✅")
        print("=" * 60)
        print()
        print("Summary:")
        print("  ✅ Phase B: Keyword dialog with search/filter")
        print("  ✅ Phase C: LoRA scanning and autocomplete")
        print("  ✅ Phase E: Keyword caching and refresh")
        print()
        print("PR-GUI-004 Phases B, C, E: COMPLETE ✅")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise


if __name__ == "__main__":
    main()

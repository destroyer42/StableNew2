"""Test PR-GUI-004 Phase A: LoRA Keyword Detection"""

import json
from pathlib import Path

from src.utils.lora_keyword_detector import detect_lora_keywords


def test_civitai_keyword_detection():
    """Test keyword detection from .civitai.info file."""
    print("=" * 60)
    print("TEST: CivitAI Keyword Detection")
    print("=" * 60)
    
    # Create a mock .civitai.info file
    test_dir = Path("test_lora_keywords")
    test_dir.mkdir(exist_ok=True)
    
    lora_file = test_dir / "test-style.safetensors"
    lora_file.touch()
    
    civitai_data = {
        "trainedWords": ["anime style", "manga art", "cel shading"],
        "description": "A LoRA for anime/manga style artwork"
    }
    
    civitai_file = test_dir / "test-style.safetensors.civitai.info"
    with open(civitai_file, "w", encoding="utf-8") as f:
        json.dump(civitai_data, f)
    
    # Detect keywords
    metadata = detect_lora_keywords("test-style", lora_folders=[test_dir])
    
    print(f"LoRA name: {metadata.name}")
    print(f"Path: {metadata.path}")
    print(f"Source: {metadata.source}")
    print(f"Keywords: {metadata.keywords}")
    print()
    
    assert metadata.source == "civitai", f"Expected source 'civitai', got '{metadata.source}'"
    assert len(metadata.keywords) == 3, f"Expected 3 keywords, got {len(metadata.keywords)}"
    assert "anime style" in metadata.keywords, "Missing 'anime style'"
    
    print("✅ CivitAI keyword detection works!")
    print()
    
    # Cleanup
    lora_file.unlink()
    civitai_file.unlink()


def test_txt_keyword_detection():
    """Test keyword detection from .txt file."""
    print("=" * 60)
    print("TEST: TXT File Keyword Detection")
    print("=" * 60)
    
    test_dir = Path("test_lora_keywords")
    test_dir.mkdir(exist_ok=True)
    
    lora_file = test_dir / "detail-enhancer.safetensors"
    lora_file.touch()
    
    txt_content = """Detail Enhancer LoRA
    
This LoRA enhances fine details in images.

Trigger words: ultra detailed, intricate details, high resolution

Use it with strength 0.6-0.8 for best results.
"""
    
    txt_file = test_dir / "detail-enhancer.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(txt_content)
    
    # Detect keywords
    metadata = detect_lora_keywords("detail-enhancer", lora_folders=[test_dir])
    
    print(f"LoRA name: {metadata.name}")
    print(f"Path: {metadata.path}")
    print(f"Source: {metadata.source}")
    print(f"Keywords: {metadata.keywords}")
    print(f"Description: {metadata.description[:50]}...")
    print()
    
    assert metadata.source == "txt", f"Expected source 'txt', got '{metadata.source}'"
    assert len(metadata.keywords) >= 2, f"Expected at least 2 keywords, got {len(metadata.keywords)}"
    
    print("✅ TXT keyword detection works!")
    print()
    
    # Cleanup
    lora_file.unlink()
    txt_file.unlink()


def test_no_keywords():
    """Test behavior when no keywords are found."""
    print("=" * 60)
    print("TEST: No Keywords Found")
    print("=" * 60)
    
    test_dir = Path("test_lora_keywords")
    test_dir.mkdir(exist_ok=True)
    
    lora_file = test_dir / "no-metadata.safetensors"
    lora_file.touch()
    
    # Detect keywords
    metadata = detect_lora_keywords("no-metadata", lora_folders=[test_dir])
    
    print(f"LoRA name: {metadata.name}")
    print(f"Path: {metadata.path}")
    print(f"Source: {metadata.source}")
    print(f"Keywords: {metadata.keywords}")
    print()
    
    assert metadata.source == "none", f"Expected source 'none', got '{metadata.source}'"
    assert len(metadata.keywords) == 0, f"Expected 0 keywords, got {len(metadata.keywords)}"
    
    print("✅ No keywords case handled correctly!")
    print()
    
    # Cleanup
    lora_file.unlink()
    test_dir.rmdir()


def main():
    """Run all keyword detection tests."""
    print("\n" + "=" * 60)
    print("PR-GUI-004 PHASE A: LoRA Keyword Detection Tests")
    print("=" * 60 + "\n")
    
    try:
        test_civitai_keyword_detection()
        test_txt_keyword_detection()
        test_no_keywords()
        
        print("=" * 60)
        print("ALL TESTS PASSED ✅")
        print("=" * 60)
        print()
        print("Summary:")
        print("  ✅ CivitAI .info keyword detection")
        print("  ✅ TXT file keyword detection")
        print("  ✅ No keywords case handled")
        print()
        print("PR-GUI-004 Phase A: COMPLETE ✅")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise


if __name__ == "__main__":
    main()

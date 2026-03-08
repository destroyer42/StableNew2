"""Test that empty padding slots are removed when saving packs."""

import json
from pathlib import Path
import tempfile

from src.gui.models.prompt_pack_model import PromptPackModel, PromptSlot

def test_empty_slots_removed_on_save():
    """Verify that empty padding slots are not saved to JSON."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        packs_dir = Path(tmpdir) / "packs"
        packs_dir.mkdir()
        
        # Step 1: Create a pack with only 3 prompts
        print("Step 1: Creating pack with 3 prompts...")
        pack_data = {
            "pack_data": {
                "name": "small_pack",
                "slots": [
                    {"index": 0, "text": "a warrior", "negative": "", "positive_embeddings": [], "negative_embeddings": [], "loras": []},
                    {"index": 1, "text": "a mage", "negative": "", "positive_embeddings": [], "negative_embeddings": [], "loras": []},
                    {"index": 2, "text": "a rogue", "negative": "", "positive_embeddings": [], "negative_embeddings": [], "loras": []},
                ],
                "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []}
            },
            "preset_data": {}
        }
        
        pack_path = packs_dir / "small_pack.json"
        with open(pack_path, "w", encoding="utf-8") as f:
            json.dump(pack_data, f, indent=2)
        
        print(f"  ✓ Created pack with {len(pack_data['pack_data']['slots'])} slots")
        
        # Step 2: Load the pack (will pad to 10 slots for UI)
        print("\nStep 2: Loading pack (will pad to 10 for UI)...")
        loaded_pack = PromptPackModel.load_from_file(pack_path, min_slots=10)
        print(f"  ✓ Loaded pack has {len(loaded_pack.slots)} slots (padded for UI)")
        assert len(loaded_pack.slots) == 10, f"Expected 10 slots after load, got {len(loaded_pack.slots)}"
        
        # Verify first 3 have content, last 7 are empty
        assert loaded_pack.slots[0].text == "a warrior"
        assert loaded_pack.slots[1].text == "a mage"
        assert loaded_pack.slots[2].text == "a rogue"
        assert loaded_pack.slots[3].text == ""
        assert loaded_pack.slots[9].text == ""
        print("  ✓ First 3 slots have content, last 7 are empty padding")
        
        # Step 3: Save the pack (should remove empty slots)
        print("\nStep 3: Saving pack (should remove empty padding)...")
        loaded_pack.save_to_file()
        
        # Step 4: Verify only 3 slots were saved
        print("\nStep 4: Verifying saved JSON only has 3 slots...")
        with open(pack_path, encoding="utf-8") as f:
            saved_data = json.load(f)
        
        saved_slots = saved_data["pack_data"]["slots"]
        print(f"  ✓ Saved JSON has {len(saved_slots)} slots")
        assert len(saved_slots) == 3, f"Expected 3 slots in saved JSON, got {len(saved_slots)}"
        assert saved_slots[0]["text"] == "a warrior"
        assert saved_slots[1]["text"] == "a mage"
        assert saved_slots[2]["text"] == "a rogue"
        print("  ✓ Only non-empty slots were saved")
        
        # Step 5: Load again to verify round-trip
        print("\nStep 5: Loading again to verify round-trip...")
        reloaded_pack = PromptPackModel.load_from_file(pack_path, min_slots=10)
        assert len(reloaded_pack.slots) == 10, "Should pad to 10 again"
        assert reloaded_pack.slots[0].text == "a warrior"
        assert reloaded_pack.slots[1].text == "a mage"
        assert reloaded_pack.slots[2].text == "a rogue"
        assert reloaded_pack.slots[3].text == ""
        print("  ✓ Round-trip successful: loads with 3 prompts, pads to 10 for UI")
        
        print("\n" + "="*60)
        print("✓ ALL TESTS PASSED!")
        print("="*60)
        print("\nEmpty slot removal verified:")
        print("  - Pack with 3 prompts loads and pads to 10 for UI")
        print("  - When saved, only 3 non-empty slots are written to JSON")
        print("  - When reloaded, still only 3 prompts, pads to 10 again")
        print("  - No accumulation of empty slots over save/load cycles")
        print("="*60)

def test_slots_with_only_negative_are_kept():
    """Verify that slots with only negative prompts are still saved."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        packs_dir = Path(tmpdir) / "packs"
        packs_dir.mkdir()
        
        print("\nTesting slots with only negative prompts...")
        
        pack = PromptPackModel(
            name="negative_only",
            path=str(packs_dir / "negative_only.json"),
            slots=[
                PromptSlot(index=0, text="", negative="ugly, bad quality"),
                PromptSlot(index=1, text="a hero", negative=""),
                PromptSlot(index=2, text="", negative=""),  # Empty - should be filtered
            ]
        )
        
        pack.save_to_file()
        
        with open(packs_dir / "negative_only.json", encoding="utf-8") as f:
            data = json.load(f)
        
        saved_slots = data["pack_data"]["slots"]
        print(f"  ✓ Saved {len(saved_slots)} slots (filtered empty slot)")
        assert len(saved_slots) == 2, f"Expected 2 slots, got {len(saved_slots)}"
        assert saved_slots[0]["negative"] == "ugly, bad quality"
        assert saved_slots[1]["text"] == "a hero"
        print("  ✓ Slot with only negative prompt was preserved")

def test_slots_with_embeddings_only_are_kept():
    """Verify that slots with only embeddings are still saved."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        packs_dir = Path(tmpdir) / "packs"
        packs_dir.mkdir()
        
        print("\nTesting slots with only embeddings...")
        
        pack = PromptPackModel(
            name="embeddings_only",
            path=str(packs_dir / "embeddings_only.json"),
            slots=[
                PromptSlot(index=0, text="", negative="", positive_embeddings=["embed1"]),
                PromptSlot(index=1, text="a hero", negative=""),
                PromptSlot(index=2, text="", negative="", negative_embeddings=["bad_embed"]),
                PromptSlot(index=3, text="", negative="", loras=[("lora1", 0.8)]),
                PromptSlot(index=4, text="", negative=""),  # Empty - should be filtered
            ]
        )
        
        pack.save_to_file()
        
        with open(packs_dir / "embeddings_only.json", encoding="utf-8") as f:
            data = json.load(f)
        
        saved_slots = data["pack_data"]["slots"]
        print(f"  ✓ Saved {len(saved_slots)} slots (filtered 1 empty slot)")
        assert len(saved_slots) == 4, f"Expected 4 slots, got {len(saved_slots)}"
        assert saved_slots[0]["positive_embeddings"] == ["embed1"]
        assert saved_slots[1]["text"] == "a hero"
        assert saved_slots[2]["negative_embeddings"] == ["bad_embed"]
        assert saved_slots[3]["loras"] == [["lora1", 0.8]]
        print("  ✓ Slots with only embeddings/LoRAs were preserved")

if __name__ == "__main__":
    test_empty_slots_removed_on_save()
    test_slots_with_only_negative_are_kept()
    test_slots_with_embeddings_only_are_kept()

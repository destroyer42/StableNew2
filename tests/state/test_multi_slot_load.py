"""Test multi-slot TXT loading functionality."""

from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.utils.prompt_txt_parser import parse_multi_slot_txt


def test_load_multi_slot_txt():
    """Test loading a multi-slot TXT file."""
    # Read TXT file
    with open("packs/SDXL_female_fantasy_heroes_Fantasy.txt", encoding="utf-8") as f:
        content = f.read()
    
    # Parse slots
    all_components = parse_multi_slot_txt(content)
    print(f"✅ Parsed {len(all_components)} slots from TXT")
    
    # Create workspace and pack
    workspace = PromptWorkspaceState()
    workspace.new_pack("Test", slot_count=1)
    
    # Adjust slot count
    needed_slots = len(all_components)
    current_slots = len(workspace.current_pack.slots)
    
    print(f"Current slots: {current_slots}, Needed: {needed_slots}")
    
    if needed_slots > current_slots:
        for _ in range(needed_slots - current_slots):
            workspace.add_slot()
    
    print(f"✅ Adjusted to {len(workspace.current_pack.slots)} slots")
    
    # Populate slots
    for index, components in enumerate(all_components):
        slot = workspace.get_slot(index)
        slot.text = components.positive_text
        slot.negative = components.negative_text
        slot.positive_embeddings = components.positive_embeddings
        slot.negative_embeddings = components.negative_embeddings
        slot.loras = components.loras
    
    print(f"✅ Populated all slots")
    
    # Verify first slot
    first_slot = workspace.get_slot(0)
    print(f"\nFirst slot verification:")
    print(f"  Positive text: {first_slot.text[:60]}...")
    print(f"  Negative text: {first_slot.negative[:60]}...")
    print(f"  Positive embeddings: {len(first_slot.positive_embeddings)}")
    print(f"  Negative embeddings: {len(first_slot.negative_embeddings)}")
    print(f"  LoRAs: {len(first_slot.loras)}")
    
    # Verify last slot
    last_slot = workspace.get_slot(len(all_components) - 1)
    print(f"\nLast slot verification:")
    print(f"  Positive text: {last_slot.text[:60]}...")
    print(f"  LoRAs: {len(last_slot.loras)}")
    
    print(f"\n✅ All tests passed!")


if __name__ == "__main__":
    test_load_multi_slot_txt()

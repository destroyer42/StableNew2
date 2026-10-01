"""Test PR-GUI-004 Phase D: LoRA/Embedding Pickers Integration"""

import json
from pathlib import Path

from src.gui.models.prompt_pack_model import PromptPackModel
from src.utils.prompt_txt_parser import parse_prompt_txt_to_components

LORA_EMBED_TXT = """<embedding:BadDream> <embedding:UnrealisticDream>
(masterpiece, best quality), a [[job]] in [[environment]], highly detailed
<lora:add-detail-xl:0.65> <lora:style-enhance:0.8>
neg: <embedding:bad-hands-5>
neg: bad quality, blurry, watermark, signature
"""


def test_phase_d_integration(tmp_path: Path):
    """Test complete workflow: parse TXT → load to model → save JSON → export TXT."""

    # Step 1: Parse test TXT file
    print("=" * 60)
    print("STEP 1: Parse test TXT file")
    print("=" * 60)

    txt_content = LORA_EMBED_TXT

    print(f"Input TXT:\n{txt_content}\n")

    components = parse_prompt_txt_to_components(txt_content)

    print("Parsed components:")
    print(f"  Positive embeddings: {components.positive_embeddings}")
    print(f"  Positive text: {components.positive_text}")
    print(f"  LoRAs: {components.loras}")
    print(f"  Negative embeddings: {components.negative_embeddings}")
    print(f"  Negative text: {components.negative_text}")
    print()

    # Step 2: Create PromptPack and load parsed data
    print("=" * 60)
    print("STEP 2: Create pack and load parsed data")
    print("=" * 60)

    pack = PromptPackModel.new("Test Pack", slot_count=1)
    slot = pack.get_slot(0)

    # Load from parsed components
    slot.text = components.positive_text
    slot.negative = components.negative_text
    slot.positive_embeddings = components.positive_embeddings
    slot.negative_embeddings = components.negative_embeddings
    slot.loras = components.loras

    print("Slot fields set:")
    print(f"  text: {slot.text}")
    print(f"  negative: {slot.negative}")
    print(f"  positive_embeddings: {slot.positive_embeddings}")
    print(f"  negative_embeddings: {slot.negative_embeddings}")
    print(f"  loras: {slot.loras}")
    print()

    # Step 3: Save to JSON
    print("=" * 60)
    print("STEP 3: Save native JSON pack (temporary PromptPack directory)")
    print("=" * 60)

    # Use an isolated PromptPack directory; never write into the repo or per-user packs.
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    json_path = packs_dir / "test_lora_embed_pack.json"
    pack.save_to_file(json_path)

    with open(json_path, encoding="utf-8") as f:
        json_data = json.load(f)

    print("JSON slots[0]:")
    print(json.dumps(json_data["pack_data"]["slots"][0], indent=2))
    print()

    # Step 4: Verify TXT export
    print("=" * 60)
    print("STEP 4: Verify explicit TXT export")
    print("=" * 60)

    # TXT is an explicit interchange export now, not an automatic save side effect.
    assert not json_path.with_suffix(".txt").exists()
    txt_export_path = pack.export_to_file(json_path.with_suffix(".txt"))
    with open(txt_export_path, encoding="utf-8") as f:
        exported_txt = f.read()
    assert "<lora:add-detail-xl:0.65>" in exported_txt
    assert "<embedding:BadDream>" in exported_txt

    print(f"Exported TXT:\n{exported_txt}\n")

    # Step 5: Reload and verify roundtrip
    print("=" * 60)
    print("STEP 5: Reload and verify roundtrip")
    print("=" * 60)

    reloaded_pack = PromptPackModel.load_from_file(json_path)
    reloaded_slot = reloaded_pack.get_slot(0)

    print("Reloaded slot fields:")
    print(f"  text: {reloaded_slot.text}")
    print(f"  negative: {reloaded_slot.negative}")
    print(f"  positive_embeddings: {reloaded_slot.positive_embeddings}")
    print(f"  negative_embeddings: {reloaded_slot.negative_embeddings}")
    print(f"  loras: {reloaded_slot.loras}")
    print()

    # Step 6: Verify all fields match
    print("=" * 60)
    print("STEP 6: Verification")
    print("=" * 60)

    assert reloaded_slot.text == slot.text, "Text mismatch"
    assert reloaded_slot.negative == slot.negative, "Negative mismatch"
    assert reloaded_slot.positive_embeddings == slot.positive_embeddings, (
        "Positive embeddings mismatch"
    )
    assert reloaded_slot.negative_embeddings == slot.negative_embeddings, (
        "Negative embeddings mismatch"
    )
    assert reloaded_slot.loras == slot.loras, "LoRAs mismatch"

    print("✅ All roundtrip checks passed!")
    print()
    print("Summary:")
    print(
        f"  ✅ Parser: {len(components.loras)} LoRAs, {len(components.positive_embeddings) + len(components.negative_embeddings)} embeddings"
    )
    print("  ✅ JSON save: All fields serialized correctly")
    print("  ✅ TXT export: Pipeline syntax correct")
    print("  ✅ Reload: All fields preserved")
    print()
    print("PR-GUI-004 Phase D Part 1+2: COMPLETE ✅")


if __name__ == "__main__":
    test_phase_d_integration()

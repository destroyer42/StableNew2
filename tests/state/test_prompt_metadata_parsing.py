"""Prompt metadata parsing (matrix, LoRA, embedding tokens) and pack save/load fidelity."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.gui.models.prompt_metadata import build_prompt_metadata
from src.gui.models.prompt_pack_model import PromptPackModel
from src.gui.prompt_workspace_state import PromptWorkspaceState


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{{A|B|C}}", 1),
        ("{{sunset|dawn|twilight|midnight}}", 1),
        ("No randomization here", 0),
        ("{{A|B}} and {{X|Y|Z}}", 2),
        ("{{{A|B}|C}}", 1),
    ],
)
def test_matrix_token_count(text: str, expected: int) -> None:
    assert build_prompt_metadata(text).matrix_count == expected


@pytest.mark.parametrize(
    ("text", "loras", "embeddings"),
    [
        ("<lora:model:0.8>", ["model"], []),
        ("<lora:style_v1:0.7> and <lora:detail_v2:0.9>", ["style_v1", "detail_v2"], []),
        ("embedding:mood and embedding:style", [], ["mood", "style"]),
        ("<lora:art:0.6> with embedding:theme", ["art"], ["theme"]),
        (
            "<lora:lora1:0.5> <lora:lora2:0.3>\nembedding:emb1 embedding:emb2",
            ["lora1", "lora2"],
            ["emb1", "emb2"],
        ),
        (
            "<lora:missing_strength> embedding:no_angle_brackets",
            ["missing_strength"],
            ["no_angle_brackets"],
        ),
        ("No tokens here", [], []),
    ],
)
def test_lora_and_embedding_token_names(
    text: str, loras: list[str], embeddings: list[str]
) -> None:
    metadata = build_prompt_metadata(text)
    assert [lora.name for lora in metadata.loras] == loras
    assert [emb.name for emb in metadata.embeddings] == embeddings


def test_lora_without_strength_has_no_weight() -> None:
    metadata = build_prompt_metadata("<lora:missing_strength>")
    assert metadata.loras[0].weight is None


def test_combined_tokens_in_one_multiline_prompt() -> None:
    metadata = build_prompt_metadata(
        "Complex scene\n<lora:a:0.9> <lora:b:0.6> <lora:c:0.4>\n"
        "embedding:x embedding:y embedding:z\nwith {{random|varied}} elements"
    )
    assert len(metadata.loras) == 3
    assert len(metadata.embeddings) == 3
    assert metadata.matrix_count == 1
    assert metadata.line_count >= 3


def test_pack_save_load_preserves_slots_and_metadata(tmp_path: Path) -> None:
    state = PromptWorkspaceState()
    pack = state.new_pack("Metadata_Fidelity_Pack", slot_count=10)
    texts = [
        "A {{sunset|dawn}} landscape\n<lora:landscape_master:0.8>\nembedding:serene_mood",
        "Unicode café ☕ <lora:unicode_lora:0.5> embedding:unicode_emb",
        "plain prompt without tokens",
    ]
    for slot, text in zip(pack.slots, texts, strict=False):
        slot.text = text

    saved = state.save_current_pack(tmp_path / "pack.json")
    loaded = PromptPackModel.load_from_file(saved)

    assert loaded.name == "Metadata_Fidelity_Pack"
    assert len(loaded.slots) == len(pack.slots)
    for original, restored in zip(pack.slots, loaded.slots, strict=True):
        assert (original.index, original.text) == (restored.index, restored.text)
        before = build_prompt_metadata(original.text)
        after = build_prompt_metadata(restored.text)
        assert before.loras == after.loras
        assert before.embeddings == after.embeddings
        assert before.matrix_count == after.matrix_count
        assert before.line_count == after.line_count

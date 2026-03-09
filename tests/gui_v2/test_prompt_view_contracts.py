from __future__ import annotations

from src.gui.view_contracts.prompt_editor_contract import (
    build_editor_warning_text,
    build_slot_labels,
    find_undefined_slots,
)


def test_build_slot_labels_handles_non_positive_counts() -> None:
    assert build_slot_labels(0) == []
    assert build_slot_labels(-3) == []
    assert build_slot_labels(3) == ["Prompt 1", "Prompt 2", "Prompt 3"]


def test_find_undefined_slots_extracts_tokens_from_both_prompts() -> None:
    undefined = find_undefined_slots(
        positive_text="portrait [[style]] [[lighting]]",
        negative_text="avoid [[artifact]] and [[style]]",
        defined_slots={"style"},
    )
    assert undefined == {"lighting", "artifact"}


def test_build_editor_warning_text_combines_modified_and_missing_slots() -> None:
    text = build_editor_warning_text(
        pack_name="Faces",
        dirty=True,
        undefined_slots={"lighting", "artifact"},
    )
    assert text.startswith("Editor - Faces (modified)")
    assert "Undefined slots: artifact, lighting" in text

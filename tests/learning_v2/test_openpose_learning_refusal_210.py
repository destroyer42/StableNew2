"""PR-IMG-CNET-210: Learning/Model Comparison refuse a pack row with enabled OpenPose conditioning (never drop it)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.conditioning.openpose import new_declaration
from src.learning.experiment_freeze import freeze_prompt_pack_source
from src.promptpacks.storage import save_prompt_pack_document

POSE = new_declaration("Standing/relaxed.png", model="xinsir_openpose_sdxl")


def _pack_file(tmp_path: Path, declaration) -> Path:
    path = tmp_path / "pose-pack.json"
    slot = {"index": 0, "text": "a person", "negative": ""}
    if declaration is not None:
        slot["controlnet_openpose"] = declaration
    document = {
        "schema_version": 1,
        "pack_data": {"name": "pose", "slots": [slot], "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []}},
        "preset_data": {},
    }
    return save_prompt_pack_document(path, document)


def _source(path: Path) -> dict:
    return {"prompt_source": "pack", "selected_prompt_pack_path": str(path), "selected_prompt_index": 0}


def test_learning_refuses_a_row_with_enabled_conditioning_instead_of_dropping_it(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="OpenPose conditioning"):
        freeze_prompt_pack_source(_source(_pack_file(tmp_path, POSE)))


def test_learning_still_freezes_rows_without_or_with_disabled_conditioning(tmp_path: Path) -> None:
    plain = freeze_prompt_pack_source(_source(_pack_file(tmp_path, None)))
    disabled = freeze_prompt_pack_source(_source(_pack_file(tmp_path, {**POSE, "enabled": False})))

    assert plain["rendered_positive_prompt"] == "a person"
    assert disabled["rendered_positive_prompt"] == "a person"



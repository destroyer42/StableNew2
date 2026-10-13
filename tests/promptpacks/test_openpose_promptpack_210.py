"""PromptPack OpenPose declaration persistence (PR-IMG-CNET-210): round-trip, clone, clear, rows, lossy export."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

from src.conditioning.openpose import new_declaration
from src.gui.models.prompt_pack_model import PromptPackModel
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.promptpacks.storage import (
    export_prompt_pack,
    prompt_pack_row_by_index,
    prompt_pack_rows,
    save_prompt_pack_document,
    slots_with_conditioning,
)

DECLARATION_A = new_declaration("Standing/relaxed.png", model="openpose_sdxl")
DECLARATION_B = {**new_declaration("Walking/forward.png", model="openpose_sdxl"), "weight": 0.7}


def _write(path: Path, slots: list[dict]) -> Path:
    document = {
        "schema_version": 1,
        "pack_data": {"name": "pack", "slots": slots, "matrix": {"enabled": False, "slots": []}},
        "preset_data": {},
    }
    return save_prompt_pack_document(path, document)


def _slot(index: int, text: str, **extra) -> dict:
    return {
        "index": index,
        "text": text,
        "negative": "",
        "template_id": "",
        "template_variables": {},
        "positive_embeddings": [],
        "negative_embeddings": [],
        "loras": [],
        **extra,
    }


def _saved_slots(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["pack_data"]["slots"]


def test_a_pack_without_the_field_loads_and_saves_without_gaining_one(tmp_path: Path) -> None:
    path = _write(tmp_path / "legacy.json", [_slot(0, "a cat"), _slot(1, "a dog")])

    pack = PromptPackModel.load_from_file(path, min_slots=2)
    assert all(slot.openpose is None for slot in pack.slots)
    pack.save_to_file(path)

    assert all("controlnet_openpose" not in slot for slot in _saved_slots(path))


def test_the_declaration_round_trips_exactly_per_slot(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "pose.json",
        [_slot(0, "standing", controlnet_openpose=DECLARATION_A), _slot(1, "walking", controlnet_openpose=DECLARATION_B)],
    )

    pack = PromptPackModel.load_from_file(path, min_slots=2)
    assert pack.slots[0].openpose == DECLARATION_A and pack.slots[1].openpose == DECLARATION_B
    pack.save_to_file(path)
    reloaded = PromptPackModel.load_from_file(path, min_slots=2)

    saved = _saved_slots(path)
    assert saved[0]["controlnet_openpose"] == DECLARATION_A
    assert saved[1]["controlnet_openpose"] == DECLARATION_B
    assert [slot.openpose for slot in reloaded.slots[:2]] == [DECLARATION_A, DECLARATION_B]


def test_setting_and_clearing_through_the_workspace_persists_exactly(tmp_path: Path) -> None:
    path = _write(tmp_path / "pose.json", [_slot(0, "a", controlnet_openpose=DECLARATION_A), _slot(1, "b")])
    state = PromptWorkspaceState()
    state.load_pack(path)

    state.set_slot_openpose(1, DECLARATION_B)
    state.set_slot_openpose(0, None)  # clearing must really remove the stored declaration
    state.save_current_pack()

    saved = _saved_slots(path)
    assert "controlnet_openpose" not in saved[0]
    assert saved[1]["controlnet_openpose"] == DECLARATION_B


def test_copying_a_slot_deep_copies_the_declaration(tmp_path: Path) -> None:
    path = _write(tmp_path / "pose.json", [_slot(0, "a", controlnet_openpose=copy.deepcopy(DECLARATION_A))])
    state = PromptWorkspaceState()
    state.load_pack(path)

    state.copy_slot(0)
    copied = state.get_slot(1)
    assert copied.openpose == DECLARATION_A
    copied.openpose["weight"] = 0.1  # editing the copy must not touch the original

    assert state.get_slot(0).openpose["weight"] == 1.0


def test_removing_a_slot_never_leaks_its_declaration_onto_another(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "pose.json",
        [_slot(0, "zero"), _slot(1, "one", controlnet_openpose=DECLARATION_A), _slot(2, "two")],
    )
    state = PromptWorkspaceState()
    state.load_pack(path)

    state.remove_slot(1)
    state.save_current_pack()

    assert all("controlnet_openpose" not in slot for slot in _saved_slots(path))


def test_a_conditioning_only_slot_is_not_discarded_as_empty_padding(tmp_path: Path) -> None:
    path = _write(tmp_path / "pose.json", [_slot(0, "a"), _slot(1, "")])
    state = PromptWorkspaceState()
    state.load_pack(path)
    state.set_slot_openpose(1, DECLARATION_A)
    state.save_current_pack()

    saved = _saved_slots(path)

    assert [slot.get("controlnet_openpose") for slot in saved] == [None, DECLARATION_A]


def test_a_malformed_value_is_preserved_verbatim_not_dropped(tmp_path: Path) -> None:
    path = _write(tmp_path / "bad.json", [_slot(0, "a", controlnet_openpose="not-an-object")])
    pack = PromptPackModel.load_from_file(path, min_slots=1)

    assert pack.slots[0].openpose == "not-an-object"
    pack.save_to_file(path)

    assert _saved_slots(path)[0]["controlnet_openpose"] == "not-an-object"


def test_rows_carry_their_own_slot_conditioning_and_row_index_selection_keeps_it(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "pose.json",
        [
            _slot(0, "standing", controlnet_openpose=DECLARATION_A),
            _slot(1, ""),  # empty padding: not a row
            _slot(2, "walking", controlnet_openpose=DECLARATION_B),
            _slot(3, "plain"),
        ],
    )
    document = json.loads(path.read_text(encoding="utf-8"))

    rows = prompt_pack_rows(document)

    assert [row.conditioning for row in rows] == [DECLARATION_A, DECLARATION_B, None]
    assert prompt_pack_row_by_index(document, 2).conditioning == DECLARATION_B
    assert slots_with_conditioning(document) == [0, 2]


def test_flattened_export_warns_that_conditioning_is_not_preserved(tmp_path: Path, caplog) -> None:
    path = _write(tmp_path / "pose.json", [_slot(0, "standing", controlnet_openpose=DECLARATION_A)])
    target = tmp_path / "pose.txt"

    with caplog.at_level(logging.WARNING, logger="src.promptpacks.storage"):
        export_prompt_pack(path, target)

    assert "drops the OpenPose conditioning" in caplog.text
    assert "openpose" not in target.read_text(encoding="utf-8").lower()
    assert "Standing" not in target.read_text(encoding="utf-8")

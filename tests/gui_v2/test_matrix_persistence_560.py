"""PR-GUI-UX-560: Matrix fields round-trip through the native PromptPack without migration or loss."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from src.gui.models.prompt_pack_model import MatrixConfig, MatrixSlot, PromptPackModel
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui_v2.matrix_editor_view import build_matrix_editor_view
from src.promptpacks.storage import load_prompt_pack_document
from tests.pipeline.test_prompt_pack_job_builder import _write_native_pack

SLOTS = [
    {"name": "character", "values": ["knight", "mage"]},
    {"name": "location", "values": ["forest"]},
]


def _stored_matrix(path: Path) -> Any:
    return load_prompt_pack_document(path)["pack_data"]["matrix"]


def _roundtrip(
    tmp_path: Path, matrix: dict[str, Any], *, edit=None
) -> tuple[Any, Any, PromptPackModel]:
    source = _write_native_pack(tmp_path / "p.json", text="A [[character]]", matrix=matrix)
    before = _stored_matrix(source)
    pack = PromptPackModel.load_from_file(source)
    if edit is not None:
        edit(pack)
    pack.save_to_file()
    return before, _stored_matrix(source), pack


@pytest.mark.parametrize("mode", ["fanout", "sequential", "random"])
def test_existing_packs_save_back_unchanged_with_no_invented_seed(
    tmp_path: Path, mode: str
) -> None:
    before, after, pack = _roundtrip(
        tmp_path, {"enabled": True, "mode": mode, "limit": 6, "slots": SLOTS}
    )

    assert after == before
    assert "sample_seed" not in after
    assert pack.matrix.mode == mode and pack.matrix.sample_seed is None


def test_a_seeded_random_matrix_round_trips(tmp_path: Path) -> None:
    def seed(pack: PromptPackModel) -> None:
        pack.matrix.sample_seed = 1234

    _, after, _ = _roundtrip(
        tmp_path, {"enabled": True, "mode": "random", "limit": 4, "slots": SLOTS}, edit=seed
    )

    assert after["sample_seed"] == 1234
    assert PromptPackModel.load_from_file(tmp_path / "p.json").matrix.sample_seed == 1234


def test_clearing_a_seed_removes_the_key(tmp_path: Path) -> None:
    def clear(pack: PromptPackModel) -> None:
        pack.matrix.sample_seed = None
        pack.matrix.clear_preserved("sample_seed")

    _, after, _ = _roundtrip(
        tmp_path,
        {"enabled": True, "mode": "random", "limit": 4, "sample_seed": 9, "slots": SLOTS},
        edit=clear,
    )

    assert "sample_seed" not in after


def test_unknown_matrix_and_dimension_fields_survive_a_save(tmp_path: Path) -> None:
    matrix = {
        "enabled": True,
        "mode": "fanout",
        "limit": 8,
        "notes": {"author": "rob", "tags": [1, 2]},
        "slots": [{"name": "character", "values": ["knight"], "description": "who", "weight": 3}],
    }
    before, after, _ = _roundtrip(tmp_path, matrix)

    assert after == before
    assert after["notes"] == {"author": "rob", "tags": [1, 2]}
    assert after["slots"][0]["description"] == "who"


def test_edits_change_only_the_edited_fields(tmp_path: Path) -> None:
    matrix = {
        "enabled": True,
        "mode": "sequential",
        "limit": 8,
        "notes": "keep",
        "slots": copy.deepcopy(SLOTS),
    }

    def edit(pack: PromptPackModel) -> None:
        pack.matrix.limit = 3
        pack.matrix.slots[0].values = ["knight", "mage", "ranger"]

    _, after, _ = _roundtrip(tmp_path, matrix, edit=edit)

    assert after["limit"] == 3 and after["mode"] == "sequential" and after["notes"] == "keep"
    assert after["slots"][0]["values"] == ["knight", "mage", "ranger"]
    assert after["slots"][1] == SLOTS[1]


@pytest.mark.parametrize(
    "matrix",
    [
        {"enabled": True, "slots": SLOTS},  # no mode, no limit
        {
            "enabled": True,
            "mode": "fanout",
            "slots": SLOTS,
        },  # no limit: the randomizer hint may apply
    ],
)
def test_absent_mode_and_limit_stay_absent(tmp_path: Path, matrix: dict) -> None:
    before, after, _ = _roundtrip(tmp_path, matrix)

    assert after == before
    assert "limit" not in after


@pytest.mark.parametrize("stored", ["abc", None, "5", 2.5, True, [], 0, -3])
def test_malformed_limits_load_and_are_written_back_untouched_until_edited(
    tmp_path: Path, stored: Any
) -> None:
    matrix = {"enabled": True, "mode": "fanout", "limit": stored, "slots": SLOTS}
    before, after, pack = _roundtrip(tmp_path, matrix)

    assert after == before
    assert after["limit"] == stored or (stored is None and after["limit"] is None)
    assert isinstance(pack.matrix.limit, int)

    # an explicit edit replaces it
    pack.matrix.limit = 7
    pack.matrix.clear_preserved("limit")
    pack.save_to_file()
    assert _stored_matrix(tmp_path / "p.json")["limit"] == 7


def test_malformed_seed_mode_and_dimensions_are_preserved_not_normalized(tmp_path: Path) -> None:
    matrix = {
        "enabled": True,
        "mode": ["random"],
        "limit": 4,
        "sample_seed": "tomorrow",
        "slots": [
            {"name": "ok", "values": ["a", "b"]},
            {"name": "text", "values": "a,b"},
            {"name": 5, "values": [1, 2]},
            "stray",
        ],
    }
    before, after, pack = _roundtrip(tmp_path, matrix)

    assert after == before
    assert pack.matrix.sample_seed is None
    assert [slot.name for slot in pack.matrix.slots] == ["ok", "text", "5", ""]
    assert pack.matrix.slots[1].values == []  # never split into characters


def test_a_non_object_matrix_is_kept_exactly(tmp_path: Path) -> None:
    source = _write_native_pack(tmp_path / "p.json", text="x", matrix={"enabled": False})
    document = json.loads(source.read_text(encoding="utf-8"))
    document["pack_data"]["matrix"] = ["legacy", 1]
    source.write_text(json.dumps(document), encoding="utf-8")

    pack = PromptPackModel.load_from_file(source)
    pack.save_to_file()

    assert _stored_matrix(source) == ["legacy", 1]


def test_save_as_copy_keeps_every_matrix_value(tmp_path: Path) -> None:
    matrix = {
        "enabled": True,
        "mode": "random",
        "limit": 4,
        "sample_seed": 77,
        "extra": 1,
        "slots": SLOTS,
    }
    source = _write_native_pack(tmp_path / "p.json", text="A [[character]]", matrix=matrix)
    workspace = PromptWorkspaceState()
    workspace.load_pack(source)
    copied = workspace.save_current_pack_as(tmp_path / "copy.json")

    assert _stored_matrix(copied) == _stored_matrix(source)


def test_a_new_matrix_config_writes_the_full_block_and_the_seed_only_when_set(
    tmp_path: Path,
) -> None:
    pack = PromptPackModel.new("fresh", slot_count=2)
    pack.slots[0].text = "A [[character]]"
    pack.matrix = MatrixConfig(
        enabled=True, mode="random", limit=3, slots=[MatrixSlot("character", ["a", "b"])]
    )
    pack.save_to_file(tmp_path / "fresh.json")
    unseeded = _stored_matrix(tmp_path / "fresh.json")
    pack.matrix.sample_seed = 5
    pack.save_to_file(tmp_path / "fresh.json")

    assert unseeded == {
        "enabled": True,
        "mode": "random",
        "limit": 3,
        "slots": [{"name": "character", "values": ["a", "b"]}],
    }
    assert _stored_matrix(tmp_path / "fresh.json")["sample_seed"] == 5


def test_inspecting_the_editor_projection_changes_nothing(tmp_path: Path) -> None:
    source = _write_native_pack(
        tmp_path / "p.json",
        text="A [[character]]",
        matrix={
            "enabled": True,
            "mode": "random",
            "limit": "abc",
            "sample_seed": "x",
            "slots": SLOTS,
        },
    )
    pack = PromptPackModel.load_from_file(source)
    config_before = copy.deepcopy(pack.matrix)
    mapping_before = pack.matrix.to_mapping()
    stat_before = source.stat().st_mtime_ns

    build_matrix_editor_view(pack.matrix, "A [[character]] in [[location]]")

    assert pack.matrix == config_before
    assert pack.matrix.to_mapping() == mapping_before
    assert pack.matrix.preserved == config_before.preserved
    assert source.stat().st_mtime_ns == stat_before

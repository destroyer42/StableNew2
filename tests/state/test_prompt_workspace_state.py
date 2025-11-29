from pathlib import Path

from src.gui.models.prompt_pack_model import PromptPackModel
from src.gui.prompt_workspace_state import PromptWorkspaceState


def test_prompt_pack_model_basic_slots(tmp_path: Path):
    pack = PromptPackModel.new("TestPack", slot_count=3)
    assert pack.name == "TestPack"
    assert len(pack.slots) == 3
    pack.set_slot_text(1, "Hello")
    assert pack.get_slot(1).text == "Hello"

    saved = pack.save_to_file(tmp_path / "pack.json")
    loaded = PromptPackModel.load_from_file(saved)
    assert loaded.name == "TestPack"
    assert len(loaded.slots) >= 3
    assert loaded.get_slot(1).text == "Hello"


def test_prompt_workspace_state_basic_flow(tmp_path: Path):
    state = PromptWorkspaceState()
    pack = state.new_pack("Untitled", slot_count=2)
    assert state.current_pack is pack
    state.set_slot_text(0, "First")
    assert state.get_slot(0).text == "First"
    assert state.dirty is True

    meta = state.get_current_prompt_metadata()
    assert meta.text_length == len("First")
    assert meta.matrix_count == 0

    saved_path = state.save_current_pack(tmp_path / "saved.json")
    assert saved_path.exists()

    state.load_pack(saved_path)
    assert state.current_pack.name == "Untitled"
    assert state.get_slot(0).text == "First"
    assert state.dirty is False

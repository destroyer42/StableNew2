from __future__ import annotations

from pathlib import Path

from src.gui.models.prompt_metadata import PromptMetadata, build_prompt_metadata
from src.gui.models.prompt_pack_model import PromptPackModel


class PromptWorkspaceState:
    """Lightweight state holder for the Prompt tab."""

    def __init__(self) -> None:
        self.current_pack: PromptPackModel | None = None
        self.dirty: bool = False
        self._current_slot_index: int = 0

    def new_pack(self, name: str, slot_count: int = 10) -> PromptPackModel:
        self.current_pack = PromptPackModel.new(name=name, slot_count=slot_count)
        self.dirty = False
        self._current_slot_index = 0
        return self.current_pack

    def load_pack(self, path: str | Path) -> PromptPackModel:
        pack = PromptPackModel.load_from_file(path)
        self.current_pack = pack
        self.dirty = False
        self._current_slot_index = 0
        return pack

    def save_current_pack(self, path: str | Path | None = None) -> Path:
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        saved_path = self.current_pack.save_to_file(path)
        self.dirty = False
        return saved_path

    def save_current_pack_as(self, path: str | Path) -> Path:
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        self.current_pack.path = str(path)
        saved_path = self.current_pack.save_to_file(path)
        self.dirty = False
        return saved_path

    def get_slot(self, index: int):
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        return self.current_pack.get_slot(index)

    def set_slot_text(self, index: int, text: str) -> None:
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        self.current_pack.set_slot_text(index, text)
        self.dirty = True

    def set_current_slot_index(self, index: int) -> None:
        self._current_slot_index = max(0, index)

    def get_current_slot_index(self) -> int:
        return self._current_slot_index

    def get_current_pack_name(self) -> str:
        if not self.current_pack:
            return ""
        return self.current_pack.name

    def get_current_path(self) -> str | None:
        if not self.current_pack:
            return None
        return self.current_pack.path

    def get_current_prompt_text(self) -> str:
        if not self.current_pack:
            return ""
        slot = self.current_pack.get_slot(self._current_slot_index)
        return slot.text

    def get_current_prompt_metadata(self) -> PromptMetadata:
        text = self.get_current_prompt_text()
        return build_prompt_metadata(text)

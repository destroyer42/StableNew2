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

    def set_slot_negative(self, index: int, negative: str) -> None:
        """Set negative prompt text for slot at index."""
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        slot = self.current_pack.get_slot(index)
        slot.negative = negative or ""
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

    def get_current_negative_text(self) -> str:
        """Get negative prompt text for current slot."""
        if not self.current_pack:
            return ""
        slot = self.current_pack.get_slot(self._current_slot_index)
        return getattr(slot, "negative", "")

    def get_current_prompt_metadata(self) -> PromptMetadata:
        """Build metadata from positive AND negative text for LoRA/embedding detection."""
        positive = self.get_current_prompt_text()
        negative = self.get_current_negative_text()
        # Combine for LoRA/embedding detection
        combined_text = f"{positive}\n{negative}"
        return build_prompt_metadata(combined_text)

    def get_matrix_config(self):
        """Get current pack's matrix configuration."""
        from src.gui.models.prompt_pack_model import MatrixConfig

        if self.current_pack:
            return self.current_pack.matrix
        return MatrixConfig()  # Default empty

    def set_matrix_config(self, matrix) -> None:
        """Update current pack's matrix configuration."""
        if self.current_pack:
            self.current_pack.matrix = matrix
            self.dirty = True

    def get_current_slot(self):
        """Get the current slot object."""
        if not self.current_pack:
            return None
        return self.current_pack.get_slot(self._current_slot_index)

    def mark_dirty(self) -> None:
        """Mark workspace as dirty (unsaved changes)."""
        self.dirty = True

    def set_slot_loras(self, index: int, loras: list[tuple[str, float]]) -> None:
        """Set LoRAs for slot at index."""
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        slot = self.current_pack.get_slot(index)
        slot.loras = loras.copy()
        self.dirty = True

    def set_slot_embeddings(
        self, index: int, positive: list[str], negative: list[str]
    ) -> None:
        """Set embeddings for slot at index."""
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        slot = self.current_pack.get_slot(index)
        slot.positive_embeddings = positive.copy()
        slot.negative_embeddings = negative.copy()
        self.dirty = True

    def add_slot(self) -> None:
        """Add a new empty slot to the current pack."""
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        from src.gui.models.prompt_pack_model import PromptSlot
        new_index = len(self.current_pack.slots)
        self.current_pack.slots.append(PromptSlot(index=new_index))
        self.dirty = True

    def remove_slot(self, index: int) -> None:
        """Remove slot at index from the current pack."""
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        if len(self.current_pack.slots) <= 1:
            raise ValueError("Cannot remove the last slot")
        if 0 <= index < len(self.current_pack.slots):
            self.current_pack.slots.pop(index)
            # Adjust current index if needed
            if self._current_slot_index >= len(self.current_pack.slots):
                self._current_slot_index = len(self.current_pack.slots) - 1
            self.dirty = True

    def copy_slot(self, index: int) -> None:
        """Copy slot at index and insert after it."""
        if not self.current_pack:
            raise RuntimeError("No prompt pack loaded")
        if 0 <= index < len(self.current_pack.slots):
            from dataclasses import replace
            original = self.current_pack.get_slot(index)
            # Create a deep copy
            copy = replace(
                original,
                text=original.text,
                negative=getattr(original, "negative", ""),
                positive_embeddings=getattr(original, "positive_embeddings", []).copy(),
                negative_embeddings=getattr(original, "negative_embeddings", []).copy(),
                loras=getattr(original, "loras", []).copy()
            )
            self.current_pack.slots.insert(index + 1, copy)
            self.dirty = True

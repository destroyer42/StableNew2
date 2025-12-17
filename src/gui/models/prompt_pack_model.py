from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PromptSlot:
    index: int
    text: str = ""


@dataclass
class PromptPackModel:
    """Simple prompt pack container."""

    name: str
    path: str | None = None
    slots: list[PromptSlot] = field(default_factory=list)

    @classmethod
    def new(cls, name: str, slot_count: int = 10) -> PromptPackModel:
        slots = [PromptSlot(index=i, text="") for i in range(slot_count)]
        return cls(name=name, slots=slots)

    @classmethod
    def load_from_file(cls, path: str | Path, min_slots: int = 10) -> PromptPackModel:
        """Load from a simple JSON format; pads slots to min_slots."""
        data_path = Path(path)
        try:
            with data_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            raise OSError(f"Failed to load prompt pack: {exc}") from exc
        name = data.get("name") or data_path.stem
        raw_slots = data.get("slots") or []
        slots: list[PromptSlot] = []
        for idx, slot in enumerate(raw_slots):
            slots.append(
                PromptSlot(index=int(slot.get("index", idx)), text=str(slot.get("text", "")))
            )
        # Pad to minimum slots
        while len(slots) < min_slots:
            slots.append(PromptSlot(index=len(slots), text=""))
        return cls(name=name, path=str(data_path), slots=slots)

    def save_to_file(self, path: str | Path | None = None) -> Path:
        """Persist to a simple JSON format; pads indices if needed."""
        target = Path(path or self.path or f"{self.name}.json")
        payload = {
            "name": self.name,
            "slots": [{"index": slot.index, "text": slot.text} for slot in self.slots],
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            raise OSError(f"Failed to save prompt pack: {exc}") from exc
        self.path = str(target)
        return target

    def get_slot(self, index: int) -> PromptSlot:
        if index < 0 or index >= len(self.slots):
            raise IndexError("Prompt slot index out of range")
        return self.slots[index]

    def set_slot_text(self, index: int, text: str) -> None:
        slot = self.get_slot(index)
        slot.text = text or ""

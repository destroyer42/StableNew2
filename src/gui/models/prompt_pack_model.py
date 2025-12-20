from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PromptSlot:
    index: int
    text: str = ""  # Pure prompt text (no LoRA/embedding syntax)
    negative: str = ""  # Pure negative text
    positive_embeddings: list[str] = field(default_factory=list)
    negative_embeddings: list[str] = field(default_factory=list)
    loras: list[tuple[str, float]] = field(default_factory=list)  # [(name, strength), ...]


@dataclass
class MatrixSlot:
    """Single slot in the matrix configuration."""
    name: str
    values: list[str] = field(default_factory=list)


@dataclass
class MatrixConfig:
    """Matrix configuration for Cartesian prompt expansion."""
    enabled: bool = False
    mode: str = "fanout"  # "fanout" or "sequential"
    limit: int = 8        # Max combinations to generate
    slots: list[MatrixSlot] = field(default_factory=list)
    
    def get_slot_names(self) -> list[str]:
        """Return list of slot names for insertion."""
        return [slot.name for slot in self.slots]
    
    def get_slot_dict(self) -> dict[str, list[str]]:
        """Return dict format for PromptRandomizer."""
        return {slot.name: slot.values for slot in self.slots}


@dataclass
class PromptPackModel:
    """Simple prompt pack container."""

    name: str
    path: str | None = None
    slots: list[PromptSlot] = field(default_factory=list)
    matrix: MatrixConfig = field(default_factory=MatrixConfig)

    @classmethod
    def new(cls, name: str, slot_count: int = 10) -> PromptPackModel:
        slots = [PromptSlot(index=i, text="", negative="") for i in range(slot_count)]
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
            # Load LoRAs with backward compatibility
            loras_data = slot.get("loras", [])
            loras = [(l[0], float(l[1])) for l in loras_data if len(l) == 2]
            
            slots.append(
                PromptSlot(
                    index=int(slot.get("index", idx)),
                    text=str(slot.get("text", "")),
                    negative=str(slot.get("negative", "")),
                    positive_embeddings=list(slot.get("positive_embeddings", [])),
                    negative_embeddings=list(slot.get("negative_embeddings", [])),
                    loras=loras
                )
            )
        # Pad to minimum slots
        while len(slots) < min_slots:
            slots.append(PromptSlot(index=len(slots), text="", negative=""))
        
        # Load matrix config (backward compatible)
        matrix_data = data.get("matrix", {})
        matrix_slots = []
        for ms in matrix_data.get("slots", []):
            matrix_slots.append(MatrixSlot(
                name=str(ms.get("name", "")),
                values=list(ms.get("values", []))
            ))
        matrix = MatrixConfig(
            enabled=bool(matrix_data.get("enabled", False)),
            mode=str(matrix_data.get("mode", "fanout")),
            limit=int(matrix_data.get("limit", 8)),
            slots=matrix_slots
        )
        
        return cls(name=name, path=str(data_path), slots=slots, matrix=matrix)

    def save_to_file(self, path: str | Path | None = None) -> Path:
        """Persist to a simple JSON format; auto-export TXT if in packs/ folder."""
        target = Path(path or self.path or f"{self.name}.json")
        payload = {
            "name": self.name,
            "slots": [
                {
                    "index": slot.index,
                    "text": slot.text,
                    "negative": getattr(slot, "negative", ""),
                    "positive_embeddings": getattr(slot, "positive_embeddings", []),
                    "negative_embeddings": getattr(slot, "negative_embeddings", []),
                    "loras": [[name, weight] for name, weight in getattr(slot, "loras", [])]
                }
                for slot in self.slots
            ],
            "matrix": {
                "enabled": self.matrix.enabled,
                "mode": self.matrix.mode,
                "limit": self.matrix.limit,
                "slots": [
                    {"name": s.name, "values": s.values}
                    for s in self.matrix.slots
                ],
            },
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            raise OSError(f"Failed to save prompt pack: {exc}") from exc
        self.path = str(target)
        
        # Auto-export TXT if in packs/ folder (for Pipeline Tab compatibility)
        if "packs" in target.parts:
            self._export_txt(target.with_suffix(".txt"))
        
        return target
    
    def _export_txt(self, txt_path: Path) -> None:
        """Export to TXT format assembling from structured fields (embeddings + text + LoRAs)."""
        lines = []
        
        for slot in self.slots:
            slot_lines = []
            
            # Positive embeddings
            positive_embeds = getattr(slot, "positive_embeddings", [])
            if positive_embeds:
                embed_line = ' '.join(f'<embedding:{e}>' for e in positive_embeds)
                slot_lines.append(embed_line)
            
            # Positive text (with [[tokens]] preserved)
            if slot.text.strip():
                slot_lines.append(slot.text.strip())
            
            # LoRAs
            loras = getattr(slot, "loras", [])
            if loras:
                lora_line = ' '.join(f'<lora:{name}:{weight}>' for name, weight in loras)
                slot_lines.append(lora_line)
            
            # Negative embeddings
            negative_embeds = getattr(slot, "negative_embeddings", [])
            if negative_embeds:
                neg_embed_line = 'neg: ' + ' '.join(f'<embedding:{e}>' for e in negative_embeds)
                slot_lines.append(neg_embed_line)
            
            # Negative text
            negative = getattr(slot, "negative", "").strip()
            if negative:
                # Split into lines if multi-line, prefix each with neg:
                neg_lines = [
                    f"neg: {line.strip()}"
                    for line in negative.split("\n")
                    if line.strip()
                ]
                slot_lines.extend(neg_lines)
            
            # Only add slot if it has content
            if slot_lines:
                lines.extend(slot_lines)
                lines.append("")  # Blank line separator
        
        try:
            txt_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            # Silently fail TXT export (JSON is source of truth)
            pass

    def get_slot(self, index: int) -> PromptSlot:
        if index < 0 or index >= len(self.slots):
            raise IndexError("Prompt slot index out of range")
        return self.slots[index]

    def set_slot_text(self, index: int, text: str) -> None:
        slot = self.get_slot(index)
        slot.text = text or ""

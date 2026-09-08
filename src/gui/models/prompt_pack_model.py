from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.promptpacks.storage import (
    CURRENT_PROMPTPACK_SCHEMA_VERSION,
    export_prompt_pack,
    load_prompt_pack_document,
    save_prompt_pack_document,
)
from src.utils.embedding_prompt_utils import (
    normalize_embedding_entries,
    serialize_embedding_entries,
)
from src.utils.prompt_templates import compose_prompt_text


def _normalize_template_variables(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, str] = {}
    for raw_key, raw_value in raw.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        normalized[key] = "" if raw_value is None else str(raw_value).strip()
    return normalized


def render_prompt_slot_text(slot: object, *, strict: bool = False) -> str:
    return compose_prompt_text(
        getattr(slot, "template_id", ""),
        getattr(slot, "template_variables", {}),
        getattr(slot, "text", ""),
        strict=strict,
    )


@dataclass
class PromptSlot:
    index: int
    text: str = ""  # Pure prompt text (no LoRA/embedding syntax)
    negative: str = ""  # Pure negative text
    template_id: str = ""
    template_variables: dict[str, str] = field(default_factory=dict)
    positive_embeddings: list[tuple[str, float]] = field(default_factory=list)
    negative_embeddings: list[tuple[str, float]] = field(default_factory=list)
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
    limit: int = 8  # Max combinations to generate
    slots: list[MatrixSlot] = field(default_factory=list)

    def get_slot_names(self) -> list[str]:
        """Return list of slot names for insertion."""
        return [slot.name for slot in self.slots]

    def get_slot_dict(self) -> dict[str, list[str]]:
        """Return dict format for PromptRandomizer."""
        return {slot.name: slot.values for slot in self.slots}


@dataclass
class PromptPackModel:
    """Simple prompt pack container with unified JSON storage.

    Stores both pack data (slots, matrix) and preset data (pipeline config)
    in a single JSON file to avoid conflicts.
    """

    name: str
    path: str | None = None
    slots: list[PromptSlot] = field(default_factory=list)
    matrix: MatrixConfig = field(default_factory=MatrixConfig)
    preset_data: dict[str, Any] = field(default_factory=dict)  # Pipeline configuration
    show_preview: bool = True
    _native_document: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def new(cls, name: str, slot_count: int = 10) -> PromptPackModel:
        slots = [PromptSlot(index=i, text="", negative="") for i in range(slot_count)]
        return cls(name=name, slots=slots)

    @staticmethod
    def _reindex_slots(slots: list[PromptSlot]) -> None:
        for index, slot in enumerate(slots):
            slot.index = index

    @classmethod
    def load_from_file(cls, path: str | Path, min_slots: int = 10) -> PromptPackModel:
        """Load a unified JSON PromptPack.

        Unversioned JSON is accepted only as an upgrade input. Runtime discovery
        exposes versioned documents exclusively.
        """
        data_path = Path(path)
        try:
            data = load_prompt_pack_document(data_path, allow_unversioned=True)
        except Exception as exc:
            raise OSError(f"Failed to load prompt pack: {exc}") from exc

        # Handle unified format (v2.6+) vs legacy format
        pack_data = data["pack_data"]
        preset_data = data.get("preset_data", {})
        name = pack_data.get("name") or data_path.stem
        raw_slots = pack_data.get("slots") or []
        matrix_data = pack_data.get("matrix", {})

        indexed_slots: dict[int, PromptSlot] = {}
        max_index = -1
        for idx, slot in enumerate(raw_slots):
            # Load LoRAs with backward compatibility
            loras_data = slot.get("loras", [])
            loras = [(item[0], float(item[1])) for item in loras_data if len(item) == 2]

            slot_index = int(slot.get("index", idx))
            if slot_index < 0:
                slot_index = idx
            if slot_index in indexed_slots:
                slot_index = idx
            max_index = max(max_index, slot_index)
            indexed_slots[slot_index] = PromptSlot(
                index=slot_index,
                text=str(slot.get("text", "")),
                negative=str(slot.get("negative", "")),
                template_id=str(slot.get("template_id", "") or "").strip(),
                template_variables=_normalize_template_variables(
                    slot.get("template_variables", {})
                ),
                positive_embeddings=normalize_embedding_entries(
                    slot.get("positive_embeddings", [])
                ),
                negative_embeddings=normalize_embedding_entries(
                    slot.get("negative_embeddings", [])
                ),
                loras=loras,
            )
        slot_count = max(min_slots, max_index + 1, len(raw_slots))
        slots = [
            indexed_slots.get(index, PromptSlot(index=index, text="", negative=""))
            for index in range(slot_count)
        ]
        cls._reindex_slots(slots)

        # Load matrix config (backward compatible)
        matrix_slots = []
        for ms in matrix_data.get("slots", []):
            matrix_slots.append(
                MatrixSlot(name=str(ms.get("name", "")), values=list(ms.get("values", [])))
            )
        matrix = MatrixConfig(
            enabled=bool(matrix_data.get("enabled", False)),
            mode=str(matrix_data.get("mode", "fanout")),
            limit=int(matrix_data.get("limit", 8)),
            slots=matrix_slots,
        )

        pack = cls(name=name, path=str(data_path), slots=slots, matrix=matrix)
        pack.preset_data = preset_data  # Store preset data
        pack._native_document = copy.deepcopy(data)
        # Load show_preview flag (defaults to True for backward compatibility)
        pack.show_preview = (
            pack_data.get("show_preview", True) if isinstance(pack_data, dict) else True
        )
        return pack

    def save_to_file(self, path: str | Path | None = None) -> Path:
        """Persist one deterministic, versioned native JSON PromptPack."""
        target = Path(path or self.path or f"{self.name}.json")
        self._reindex_slots(self.slots)

        # Filter out empty padding slots (keep only slots with content)
        non_empty_slots = [
            slot
            for slot in self.slots
            if render_prompt_slot_text(slot).strip()
            or slot.negative.strip()
            or slot.positive_embeddings
            or slot.negative_embeddings
            or slot.loras
            or bool(slot.template_id)
        ]

        # Build pack data section (matrix, slots, etc.)
        original_slots = {
            int(slot.get("index", index)): copy.deepcopy(slot)
            for index, slot in enumerate(
                self._native_document.get("pack_data", {}).get("slots", [])
            )
            if isinstance(slot, dict)
        }
        serialized_slots: list[dict[str, Any]] = []
        for slot in non_empty_slots:
            serialized_slot = original_slots.get(slot.index, {})
            serialized_slot.update(
                {
                    "index": slot.index,
                    "text": slot.text,
                    "negative": getattr(slot, "negative", ""),
                    "template_id": getattr(slot, "template_id", ""),
                    "template_variables": _normalize_template_variables(
                        getattr(slot, "template_variables", {})
                    ),
                    "positive_embeddings": serialize_embedding_entries(
                        getattr(slot, "positive_embeddings", [])
                    ),
                    "negative_embeddings": serialize_embedding_entries(
                        getattr(slot, "negative_embeddings", [])
                    ),
                    "loras": [[name, weight] for name, weight in getattr(slot, "loras", [])],
                }
            )
            serialized_slots.append(serialized_slot)

        pack_data = {
            "name": self.name,
            "slots": serialized_slots,
            "matrix": {
                "enabled": self.matrix.enabled,
                "mode": self.matrix.mode,
                "limit": self.matrix.limit,
                "slots": [{"name": s.name, "values": s.values} for s in self.matrix.slots],
            },
            "show_preview": getattr(self, "show_preview", True),
        }

        # Build unified payload
        payload = copy.deepcopy(self._native_document)
        existing_pack_data = payload.get("pack_data")
        if not isinstance(existing_pack_data, dict):
            existing_pack_data = {}
        existing_pack_data.update(pack_data)
        payload.update(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": existing_pack_data,
                "preset_data": copy.deepcopy(getattr(self, "preset_data", {})),
            }
        )
        try:
            save_prompt_pack_document(target, payload)
        except Exception as exc:
            raise OSError(f"Failed to save prompt pack: {exc}") from exc
        self.path = str(target)
        self._native_document = copy.deepcopy(payload)
        return target

    def export_to_file(self, target: str | Path) -> Path:
        """Explicitly export a flattened TXT or TSV interchange file."""
        if not self.path:
            raise OSError("Save the native PromptPack before exporting it")
        return export_prompt_pack(self.path, target)

    def get_slot(self, index: int) -> PromptSlot:
        if index < 0 or index >= len(self.slots):
            raise IndexError("Prompt slot index out of range")
        return self.slots[index]

    def set_slot_text(self, index: int, text: str) -> None:
        slot = self.get_slot(index)
        slot.text = text or ""

    def set_slot_template(
        self, index: int, template_id: str, template_variables: dict[str, str] | None = None
    ) -> None:
        slot = self.get_slot(index)
        slot.template_id = str(template_id or "").strip()
        slot.template_variables = _normalize_template_variables(template_variables or {})

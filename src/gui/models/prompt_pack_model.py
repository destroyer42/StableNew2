from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.conditioning.openpose import SLOT_FIELD as OPENPOSE_SLOT_FIELD
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
    #: Raw ``controlnet_openpose`` JSON value (PR-IMG-CNET-210). ``None`` means absent. Kept verbatim (a malformed value is
    #: preserved and surfaced by validation, never silently dropped) and edited only by the OpenPose picker.
    openpose: Any = None
    controlnet_units: Any = None


class _Absent:
    """Marks a stored key that was not present, so saving an untouched value does not invent it."""

    def __repr__(self) -> str:
        return "<absent>"

    def __copy__(self) -> _Absent:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> _Absent:
        return self


ABSENT = _Absent()


def _kept(preserved: dict[str, tuple[Any, Any]], key: str, current: Any) -> tuple[bool, Any]:
    """``(use_raw, value)``: the stored raw value is written back only while the field still holds its load-time reading."""
    kept = preserved.get(key)
    if kept is not None and current == kept[1]:
        return True, kept[0]
    return False, current


@dataclass
class MatrixSlot:
    """Single slot in the matrix configuration."""

    name: str
    values: list[str] = field(default_factory=list)
    #: Stored keys this editor does not know, written back verbatim.
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    #: ``field -> (stored raw value, value shown after loading)`` for stored values the editor cannot represent.
    preserved: dict[str, tuple[Any, Any]] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, raw: Any) -> MatrixSlot:
        if not isinstance(raw, dict):
            return cls(name="", values=[], preserved={"__item__": (copy.deepcopy(raw), None)})
        slot = cls(
            name="",
            values=[],
            extra={k: copy.deepcopy(v) for k, v in raw.items() if k not in ("name", "values")},
        )
        name = raw.get("name", "")
        if isinstance(name, str):
            slot.name = name
        else:
            slot.name = "" if name is None else str(name)
            slot.preserved["name"] = (copy.deepcopy(name), slot.name)
        values = raw.get("values", [])
        if isinstance(values, list | tuple):
            slot.values = list(values)
        else:
            slot.preserved["values"] = (copy.deepcopy(values), [])
        return slot

    def to_mapping(self) -> Any:
        item = self.preserved.get("__item__")
        if item is not None and not self.name and not self.values and not self.extra:
            return copy.deepcopy(item[0])
        out = copy.deepcopy(self.extra)
        use_raw, name = _kept(self.preserved, "name", self.name)
        out["name"] = copy.deepcopy(name) if use_raw else name
        use_raw, values = _kept(self.preserved, "values", self.values)
        out["values"] = copy.deepcopy(values) if use_raw else list(values)
        return out


@dataclass
class MatrixConfig:
    """Matrix configuration for Cartesian prompt expansion.

    ``mode`` is ``fanout``, ``sequential`` or ``random`` for authored packs; any other stored value is kept as it is.
    ``sample_seed`` is the optional seed for ``random`` selection (``None`` = not set).
    """

    enabled: bool = False
    mode: str = "fanout"
    limit: int = 8  # Max combinations to generate
    slots: list[MatrixSlot] = field(default_factory=list)
    sample_seed: int | None = None
    #: Stored keys this editor does not know, written back verbatim.
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    #: ``field -> (stored raw value or ABSENT, value shown after loading)``. A stored value the editor cannot show
    #: exactly (missing key, wrong type) is written back unchanged until the operator edits that field.
    preserved: dict[str, tuple[Any, Any]] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, raw: Any) -> MatrixConfig:
        """Read a stored ``pack_data.matrix`` without normalizing what it cannot represent."""
        if raw is ABSENT:
            return cls()
        if not isinstance(raw, dict):
            return cls(preserved={"__matrix__": (copy.deepcopy(raw), None)})
        config = cls(
            enabled=bool(raw.get("enabled", False)),
            extra={
                k: copy.deepcopy(v)
                for k, v in raw.items()
                if k not in ("enabled", "mode", "limit", "slots", "sample_seed")
            },
        )
        mode = raw.get("mode", ABSENT)
        if isinstance(mode, str):
            config.mode = mode
        else:
            config.preserved["mode"] = (copy.deepcopy(mode), config.mode)
        limit = raw.get("limit", ABSENT)
        if isinstance(limit, int) and not isinstance(limit, bool):
            config.limit = limit
        else:
            if limit is not ABSENT:
                try:
                    config.limit = int(limit or 0)  # how the compiler reads it
                except (TypeError, ValueError, OverflowError):
                    pass
            config.preserved["limit"] = (copy.deepcopy(limit), config.limit)
        seed = raw.get("sample_seed", ABSENT)
        if isinstance(seed, int) and not isinstance(seed, bool):
            config.sample_seed = seed
        elif seed is not ABSENT:
            config.preserved["sample_seed"] = (copy.deepcopy(seed), None)
        slots = raw.get("slots", ABSENT)
        if isinstance(slots, list | tuple):
            config.slots = [MatrixSlot.from_mapping(item) for item in slots]
        else:
            config.preserved["slots"] = (copy.deepcopy(slots), [])
        return config

    def to_mapping(self) -> Any:
        """The stored ``pack_data.matrix`` value: edits applied, everything else exactly as it was loaded."""
        whole = self.preserved.get("__matrix__")
        if whole is not None and self == MatrixConfig():
            return copy.deepcopy(whole[0])
        out = copy.deepcopy(self.extra)
        out["enabled"] = self.enabled
        for key in ("mode", "limit", "sample_seed"):
            use_raw, value = _kept(self.preserved, key, getattr(self, key))
            if use_raw and value is ABSENT:
                continue
            if not use_raw and key == "sample_seed" and value is None:
                continue
            out[key] = copy.deepcopy(value)
        use_raw, slots = _kept(self.preserved, "slots", self.slots)
        if use_raw:
            if slots is not ABSENT:
                out["slots"] = copy.deepcopy(slots)
        else:
            out["slots"] = [slot.to_mapping() for slot in self.slots]
        return out

    def clear_preserved(self, key: str) -> None:
        """The operator edited ``key`` explicitly: stop writing back its stored raw value."""
        self.preserved.pop(key, None)

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
                openpose=copy.deepcopy(slot.get(OPENPOSE_SLOT_FIELD)),
                controlnet_units=copy.deepcopy(slot.get("controlnet_units")),
            )
        slot_count = max(min_slots, max_index + 1, len(raw_slots))
        slots = [
            indexed_slots.get(index, PromptSlot(index=index, text="", negative=""))
            for index in range(slot_count)
        ]
        cls._reindex_slots(slots)

        # Load matrix config (backward compatible)
        matrix = MatrixConfig.from_mapping(pack_data.get("matrix", ABSENT))

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
            or getattr(slot, "openpose", None) is not None
            or getattr(slot, "controlnet_units", None) is not None
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
            # Explicit set-or-remove: an unknown-field carry-over by index must never resurrect a cleared declaration
            # or attach one slot's declaration to another after clone/reorder.
            openpose = getattr(slot, "openpose", None)
            if openpose is None:
                serialized_slot.pop(OPENPOSE_SLOT_FIELD, None)
            else:
                serialized_slot[OPENPOSE_SLOT_FIELD] = copy.deepcopy(openpose)
            if slot.controlnet_units is None:
                serialized_slot.pop("controlnet_units", None)
            else:
                serialized_slot["controlnet_units"] = copy.deepcopy(slot.controlnet_units)
            serialized_slots.append(serialized_slot)

        pack_data = {
            "name": self.name,
            "slots": serialized_slots,
            "matrix": self.matrix.to_mapping(),
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
                "preset_data": self._preset_data_for_save(target),
            }
        )
        try:
            save_prompt_pack_document(target, payload)
        except Exception as exc:
            raise OSError(f"Failed to save prompt pack: {exc}") from exc
        self.preset_data = copy.deepcopy(payload["preset_data"])
        self.path = str(target)
        self._native_document = copy.deepcopy(payload)
        return target

    def _preset_data_for_save(self, target: Path) -> dict[str, Any]:
        """``preset_data`` to write, without reverting settings saved to this file since it was loaded.

        The sidebar's Save Config to Pack rewrites ``preset_data`` in the same file while this model holds the copy it
        loaded. A top-level key this model did not change since it was loaded or last saved is therefore taken from the
        file; a key the Prompt tab did change (for example ``style_lora``) wins. Saving to a different file, or a file
        that is missing or no longer valid, writes this model's copy as before.
        """
        mine = copy.deepcopy(getattr(self, "preset_data", {}) or {})
        if not self.path or Path(self.path).resolve() != target.resolve() or not target.is_file():
            return mine
        try:
            disk = load_prompt_pack_document(target).get("preset_data", {})
        except (OSError, ValueError):  # PromptPackFormatError is a ValueError
            return mine
        base = self._native_document.get("preset_data", {})
        merged: dict[str, Any] = {}
        for key in dict.fromkeys([*mine, *disk]):
            changed_here = (key in mine) != (key in base) or mine.get(key) != base.get(key)
            source = mine if changed_here else disk
            if key in source:
                merged[key] = copy.deepcopy(source[key])
        return merged

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

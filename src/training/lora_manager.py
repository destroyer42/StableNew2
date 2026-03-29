from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from datetime import datetime
from pathlib import Path
from typing import Any

_MANIFEST_SCHEMA = "stablenew.lora-manifest.v2.6"


def _normalize_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_weight(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _path_stem(value: Any) -> str | None:
    text = _normalize_optional_text(value)
    if not text:
        return None
    return Path(text).stem or None


def _actor_field(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name)
    return getattr(value, field_name, None)


class LoRAManager:
    """Maintains a lightweight manifest of trained character LoRA weights."""

    def __init__(
        self,
        *,
        base_dir: str | Path = "data/embeddings",
        manifest_name: str = "manifest.json",
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.base_dir / manifest_name

    def register(
        self,
        *,
        character_name: str,
        weight_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_name = str(character_name or "").strip()
        if not normalized_name:
            raise ValueError("character_name is required")
        resolved_weight_path = Path(weight_path).expanduser().resolve()
        if not resolved_weight_path.exists():
            raise FileNotFoundError(f"Trained weight file does not exist: {resolved_weight_path}")

        metadata_payload = dict(metadata or {})
        manifest = self._load_manifest()
        entry = self._normalize_manifest_entry(
            {
                "character_name": normalized_name,
                "weight_path": str(resolved_weight_path),
                "registered_at": datetime.utcnow().isoformat(),
                "metadata": metadata_payload,
                "manifest_path": str(self.manifest_path),
            }
        )
        manifest["entries"][self._entry_key(normalized_name)] = entry
        manifest["updated_at"] = entry["registered_at"]
        self._write_manifest(manifest)
        return dict(entry)

    def get(self, character_name: str) -> dict[str, Any] | None:
        entry = self._load_manifest()["entries"].get(self._entry_key(character_name))
        if not isinstance(entry, dict):
            return None
        return self._normalize_manifest_entry(entry)

    def list(self) -> Sequence[dict[str, Any]]:
        entries = self._load_manifest()["entries"].values()
        sorted_entries = sorted(
            (self._normalize_manifest_entry(entry) for entry in entries if isinstance(entry, dict)),
            key=lambda item: str(item.get("character_name") or "").lower(),
        )
        return sorted_entries

    def resolve(self, character_name: str) -> str | None:
        entry = self.get(character_name)
        if not entry:
            return None
        weight_path = Path(str(entry.get("weight_path") or "")).expanduser()
        if not weight_path.exists():
            return None
        return str(weight_path.resolve())

    def resolve_actor(self, actor: Any) -> dict[str, Any]:
        normalized = self._normalize_actor_spec(actor)
        if normalized is None:
            raise ValueError("Actor name is required")
        return self._resolve_normalized_actor(normalized)

    def resolve_actors(self, actors: Any) -> Sequence[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for actor in self._dedupe_actor_specs(actors):
            resolved.append(self._resolve_normalized_actor(actor))
        return resolved

    def _load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return self._empty_manifest()
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return self._empty_manifest()
        entries = data.get("entries")
        if not isinstance(entries, dict):
            return self._empty_manifest()
        normalized_entries: dict[str, dict[str, Any]] = {}
        for raw_entry in entries.values():
            if not isinstance(raw_entry, dict):
                continue
            normalized_entry = self._normalize_manifest_entry(raw_entry)
            character_name = str(normalized_entry.get("character_name") or "").strip()
            if not character_name:
                continue
            normalized_entries[self._entry_key(character_name)] = normalized_entry
        return {
            "schema": data.get("schema") or _MANIFEST_SCHEMA,
            "updated_at": data.get("updated_at"),
            "entries": normalized_entries,
        }

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _entry_key(character_name: str) -> str:
        return str(character_name or "").strip().lower()

    def _normalize_manifest_entry(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        metadata = dict(entry.get("metadata") or {}) if isinstance(entry.get("metadata"), Mapping) else {}
        weight_path = _normalize_optional_text(entry.get("weight_path"))
        lora_path = _normalize_optional_text(entry.get("lora_path")) or weight_path
        trigger_phrase = _normalize_optional_text(entry.get("trigger_phrase")) or _normalize_optional_text(
            metadata.get("trigger_phrase")
        )
        lora_name = _normalize_optional_text(entry.get("lora_name")) or _normalize_optional_text(
            metadata.get("lora_name")
        ) or _path_stem(lora_path)
        return {
            "character_name": _normalize_optional_text(entry.get("character_name"))
            or _normalize_optional_text(metadata.get("character_name"))
            or "",
            "weight_path": weight_path,
            "lora_path": lora_path,
            "lora_name": lora_name,
            "trigger_phrase": trigger_phrase,
            "weight": _normalize_weight(entry.get("weight"))
            if _normalize_weight(entry.get("weight")) is not None
            else _normalize_weight(metadata.get("weight")),
            "registered_at": str(entry.get("registered_at") or ""),
            "metadata": metadata,
            "manifest_path": str(entry.get("manifest_path") or self.manifest_path),
        }

    def _normalize_actor_spec(self, actor: Any) -> dict[str, Any] | None:
        if actor is None:
            return None
        if isinstance(actor, str):
            text = actor.strip()
            return {"name": text, "character_name": None, "trigger_phrase": None, "lora_name": None, "lora_path": None, "weight": None} if text else None

        lora_path = _normalize_optional_text(_actor_field(actor, "lora_path")) or _normalize_optional_text(
            _actor_field(actor, "weight_path")
        )
        character_name = _normalize_optional_text(_actor_field(actor, "character_name"))
        lora_name = _normalize_optional_text(_actor_field(actor, "lora_name"))
        name = _normalize_optional_text(_actor_field(actor, "name")) or character_name or lora_name or _path_stem(lora_path)
        if not name:
            return None
        return {
            "name": name,
            "character_name": character_name,
            "trigger_phrase": _normalize_optional_text(_actor_field(actor, "trigger_phrase")),
            "lora_name": lora_name,
            "lora_path": lora_path,
            "weight": _normalize_weight(_actor_field(actor, "weight")),
        }

    @staticmethod
    def _actor_identity_key(actor: Mapping[str, Any]) -> str:
        for raw_value in (
            actor.get("character_name"),
            actor.get("name"),
            actor.get("lora_name"),
            _path_stem(actor.get("lora_path")),
        ):
            text = str(raw_value or "").strip().lower()
            if text:
                return text
        return "actor"

    @staticmethod
    def _merge_actor_specs(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "name": str(override.get("name") or base.get("name") or "").strip(),
            "character_name": _normalize_optional_text(override.get("character_name"))
            or _normalize_optional_text(base.get("character_name")),
            "trigger_phrase": _normalize_optional_text(override.get("trigger_phrase"))
            or _normalize_optional_text(base.get("trigger_phrase")),
            "lora_name": _normalize_optional_text(override.get("lora_name"))
            or _normalize_optional_text(base.get("lora_name")),
            "lora_path": _normalize_optional_text(override.get("lora_path"))
            or _normalize_optional_text(base.get("lora_path")),
            "weight": _normalize_weight(override.get("weight"))
            if _normalize_weight(override.get("weight")) is not None
            else _normalize_weight(base.get("weight")),
        }

    def _dedupe_actor_specs(self, actors: Any) -> Sequence[dict[str, Any]]:
        if actors is None:
            return []
        raw_items = list(actors) if isinstance(actors, (list, tuple)) else [actors]
        merged: list[dict[str, Any]] = []
        indexes_by_key: dict[str, int] = {}
        for raw_actor in raw_items:
            normalized = self._normalize_actor_spec(raw_actor)
            if normalized is None:
                continue
            identity_key = self._actor_identity_key(normalized)
            existing_index = indexes_by_key.get(identity_key)
            if existing_index is None:
                indexes_by_key[identity_key] = len(merged)
                merged.append(normalized)
                continue
            merged[existing_index] = self._merge_actor_specs(merged[existing_index], normalized)
        return merged

    def _resolve_normalized_actor(self, actor: Mapping[str, Any]) -> dict[str, Any]:
        manifest_entry = None
        for lookup_key in (actor.get("character_name"), actor.get("name")):
            text = str(lookup_key or "").strip()
            if not text:
                continue
            manifest_entry = self.get(text)
            if manifest_entry is not None:
                break

        trigger_phrase = _normalize_optional_text(actor.get("trigger_phrase"))
        lora_path = _normalize_optional_text(actor.get("lora_path"))
        lora_name = _normalize_optional_text(actor.get("lora_name"))
        weight = _normalize_weight(actor.get("weight"))
        source = "explicit"

        if manifest_entry is not None:
            trigger_phrase = trigger_phrase or _normalize_optional_text(manifest_entry.get("trigger_phrase"))
            lora_path = lora_path or _normalize_optional_text(manifest_entry.get("lora_path")) or _normalize_optional_text(
                manifest_entry.get("weight_path")
            )
            lora_name = lora_name or _normalize_optional_text(manifest_entry.get("lora_name")) or _path_stem(lora_path)
            if weight is None:
                manifest_weight = _normalize_weight(manifest_entry.get("weight"))
                weight = manifest_weight if manifest_weight is not None else 1.0
            source = "manifest"
            if any(actor.get(field_name) not in (None, "") for field_name in ("trigger_phrase", "lora_name", "lora_path", "weight")):
                source = "manifest+override"

        if weight is None:
            weight = 1.0
        if not lora_name:
            lora_name = _path_stem(lora_path)

        actor_name = str(actor.get("name") or actor.get("character_name") or lora_name or "").strip()
        character_name = _normalize_optional_text(actor.get("character_name")) or _normalize_optional_text(
            manifest_entry.get("character_name") if manifest_entry else None
        ) or actor_name

        if not trigger_phrase:
            raise ValueError(
                f"Actor '{actor_name or character_name}' is missing a trigger_phrase in both manifest and explicit actor fallback data."
            )
        if not (lora_name or lora_path):
            raise ValueError(
                f"Actor '{actor_name or character_name}' could not be resolved to a LoRA; provide a registered character_name or explicit lora_name/lora_path."
            )

        return {
            "name": actor_name,
            "character_name": character_name,
            "trigger_phrase": trigger_phrase,
            "lora_name": lora_name,
            "lora_path": lora_path,
            "weight": weight,
            "source": source,
            "manifest_entry": dict(manifest_entry) if manifest_entry else None,
        }

    @staticmethod
    def _empty_manifest() -> dict[str, Any]:
        return {
            "schema": _MANIFEST_SCHEMA,
            "updated_at": None,
            "entries": {},
        }
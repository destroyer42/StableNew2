from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


CONTINUITY_PACK_SCHEMA_V26 = "stablenew.continuity_pack.v2.6"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


@dataclass
class ContinuityAnchorReference:
    anchor_id: str
    image_path: str
    label: str = ""
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "image_path": self.image_path,
            "label": self.label,
            "notes": self.notes,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ContinuityAnchorReference":
        payload = _mapping_dict(data)
        return cls(
            anchor_id=str(payload.get("anchor_id") or ""),
            image_path=str(payload.get("image_path") or ""),
            label=str(payload.get("label") or ""),
            notes=str(payload.get("notes") or ""),
            tags=_string_list(payload.get("tags")),
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class ContinuityAnchorSet:
    anchor_set_id: str
    display_name: str
    anchor_ids: list[str] = field(default_factory=list)
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_set_id": self.anchor_set_id,
            "display_name": self.display_name,
            "anchor_ids": list(self.anchor_ids),
            "description": self.description,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ContinuityAnchorSet":
        payload = _mapping_dict(data)
        return cls(
            anchor_set_id=str(payload.get("anchor_set_id") or ""),
            display_name=str(payload.get("display_name") or ""),
            anchor_ids=_string_list(payload.get("anchor_ids")),
            description=str(payload.get("description") or ""),
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class ContinuityCharacterReference:
    character_id: str
    display_name: str
    description: str = ""
    anchor_set_id: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "display_name": self.display_name,
            "description": self.description,
            "anchor_set_id": self.anchor_set_id,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ContinuityCharacterReference":
        payload = _mapping_dict(data)
        anchor_set_id = str(payload.get("anchor_set_id") or "").strip() or None
        return cls(
            character_id=str(payload.get("character_id") or ""),
            display_name=str(payload.get("display_name") or ""),
            description=str(payload.get("description") or ""),
            anchor_set_id=anchor_set_id,
            tags=_string_list(payload.get("tags")),
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class ContinuityWardrobeReference:
    wardrobe_id: str
    display_name: str
    description: str = ""
    character_id: str | None = None
    anchor_set_id: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wardrobe_id": self.wardrobe_id,
            "display_name": self.display_name,
            "description": self.description,
            "character_id": self.character_id,
            "anchor_set_id": self.anchor_set_id,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ContinuityWardrobeReference":
        payload = _mapping_dict(data)
        character_id = str(payload.get("character_id") or "").strip() or None
        anchor_set_id = str(payload.get("anchor_set_id") or "").strip() or None
        return cls(
            wardrobe_id=str(payload.get("wardrobe_id") or ""),
            display_name=str(payload.get("display_name") or ""),
            description=str(payload.get("description") or ""),
            character_id=character_id,
            anchor_set_id=anchor_set_id,
            tags=_string_list(payload.get("tags")),
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class ContinuitySceneReference:
    scene_id: str
    display_name: str
    description: str = ""
    anchor_set_id: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "display_name": self.display_name,
            "description": self.description,
            "anchor_set_id": self.anchor_set_id,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ContinuitySceneReference":
        payload = _mapping_dict(data)
        anchor_set_id = str(payload.get("anchor_set_id") or "").strip() or None
        return cls(
            scene_id=str(payload.get("scene_id") or ""),
            display_name=str(payload.get("display_name") or ""),
            description=str(payload.get("description") or ""),
            anchor_set_id=anchor_set_id,
            tags=_string_list(payload.get("tags")),
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class ContinuityPackSummary:
    pack_id: str
    display_name: str
    updated_at: str = ""
    character_count: int = 0
    wardrobe_count: int = 0
    scene_count: int = 0
    anchor_set_count: int = 0
    anchor_count: int = 0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "display_name": self.display_name,
            "updated_at": self.updated_at,
            "character_count": self.character_count,
            "wardrobe_count": self.wardrobe_count,
            "scene_count": self.scene_count,
            "anchor_set_count": self.anchor_set_count,
            "anchor_count": self.anchor_count,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ContinuityPackSummary":
        payload = _mapping_dict(data)
        return cls(
            pack_id=str(payload.get("pack_id") or ""),
            display_name=str(payload.get("display_name") or payload.get("pack_id") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            character_count=int(payload.get("character_count") or 0),
            wardrobe_count=int(payload.get("wardrobe_count") or 0),
            scene_count=int(payload.get("scene_count") or 0),
            anchor_set_count=int(payload.get("anchor_set_count") or 0),
            anchor_count=int(payload.get("anchor_count") or 0),
            tags=_string_list(payload.get("tags")),
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class ContinuityPackLink:
    pack_id: str
    pack_summary: ContinuityPackSummary | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {"pack_id": self.pack_id}
        if self.pack_summary is not None:
            payload["pack_summary"] = self.pack_summary.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ContinuityPackLink | None":
        payload = _mapping_dict(data)
        pack_id = str(payload.get("pack_id") or payload.get("id") or "").strip()
        if not pack_id:
            return None
        raw_summary = payload.get("pack_summary") or payload.get("summary")
        summary = None
        if isinstance(raw_summary, Mapping):
            summary = ContinuityPackSummary.from_dict(raw_summary)
        return cls(pack_id=pack_id, pack_summary=summary)


@dataclass
class ContinuityPack:
    pack_id: str
    display_name: str
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    anchors: list[ContinuityAnchorReference] = field(default_factory=list)
    anchor_sets: list[ContinuityAnchorSet] = field(default_factory=list)
    characters: list[ContinuityCharacterReference] = field(default_factory=list)
    wardrobes: list[ContinuityWardrobeReference] = field(default_factory=list)
    scenes: list[ContinuitySceneReference] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CONTINUITY_PACK_SCHEMA_V26

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "anchors": [anchor.to_dict() for anchor in self.anchors],
            "anchor_sets": [anchor_set.to_dict() for anchor_set in self.anchor_sets],
            "characters": [character.to_dict() for character in self.characters],
            "wardrobes": [wardrobe.to_dict() for wardrobe in self.wardrobes],
            "scenes": [scene.to_dict() for scene in self.scenes],
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ContinuityPack":
        payload = _mapping_dict(data)
        return cls(
            pack_id=str(payload.get("pack_id") or ""),
            display_name=str(payload.get("display_name") or payload.get("pack_id") or ""),
            created_at=str(payload.get("created_at") or _now_iso()),
            updated_at=str(payload.get("updated_at") or _now_iso()),
            anchors=[
                ContinuityAnchorReference.from_dict(item)
                for item in list(payload.get("anchors") or [])
            ],
            anchor_sets=[
                ContinuityAnchorSet.from_dict(item)
                for item in list(payload.get("anchor_sets") or [])
            ],
            characters=[
                ContinuityCharacterReference.from_dict(item)
                for item in list(payload.get("characters") or [])
            ],
            wardrobes=[
                ContinuityWardrobeReference.from_dict(item)
                for item in list(payload.get("wardrobes") or [])
            ],
            scenes=[
                ContinuitySceneReference.from_dict(item)
                for item in list(payload.get("scenes") or [])
            ],
            tags=_string_list(payload.get("tags")),
            metadata=_mapping_dict(payload.get("metadata")),
            schema_version=str(payload.get("schema_version") or CONTINUITY_PACK_SCHEMA_V26),
        )

    def summary(self) -> ContinuityPackSummary:
        return ContinuityPackSummary(
            pack_id=self.pack_id,
            display_name=self.display_name or self.pack_id,
            updated_at=self.updated_at,
            character_count=len(self.characters),
            wardrobe_count=len(self.wardrobes),
            scene_count=len(self.scenes),
            anchor_set_count=len(self.anchor_sets),
            anchor_count=len(self.anchors),
            tags=list(self.tags),
            metadata=dict(self.metadata),
        )

    def link(self) -> ContinuityPackLink:
        return ContinuityPackLink(pack_id=self.pack_id, pack_summary=self.summary())


def normalize_continuity_link(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, ContinuityPack):
        return value.link().to_dict()
    if isinstance(value, ContinuityPackLink):
        return value.to_dict()
    if isinstance(value, ContinuityPackSummary):
        return ContinuityPackLink(pack_id=value.pack_id, pack_summary=value).to_dict()
    if isinstance(value, str):
        pack_id = value.strip()
        return {"pack_id": pack_id} if pack_id else None

    payload = _mapping_dict(value)
    if not payload:
        return None

    link = ContinuityPackLink.from_dict(payload)
    if link is not None:
        return link.to_dict()

    pack_id = str(payload.get("pack_id") or payload.get("id") or "").strip()
    if not pack_id:
        return None

    display_name = str(
        payload.get("display_name")
        or payload.get("pack_name")
        or payload.get("name")
        or pack_id
    )
    summary = ContinuityPackSummary(
        pack_id=pack_id,
        display_name=display_name,
        updated_at=str(payload.get("updated_at") or ""),
        character_count=int(payload.get("character_count") or 0),
        wardrobe_count=int(payload.get("wardrobe_count") or 0),
        scene_count=int(payload.get("scene_count") or 0),
        anchor_set_count=int(payload.get("anchor_set_count") or 0),
        anchor_count=int(payload.get("anchor_count") or 0),
        tags=_string_list(payload.get("tags")),
        metadata=_mapping_dict(payload.get("metadata")),
    )
    return ContinuityPackLink(pack_id=pack_id, pack_summary=summary).to_dict()


def prefer_continuity_link(*values: Any) -> dict[str, Any] | None:
    for value in values:
        link = normalize_continuity_link(value)
        if link:
            return link
    return None


__all__ = [
    "CONTINUITY_PACK_SCHEMA_V26",
    "ContinuityAnchorReference",
    "ContinuityAnchorSet",
    "ContinuityCharacterReference",
    "ContinuityPack",
    "ContinuityPackLink",
    "ContinuityPackSummary",
    "ContinuitySceneReference",
    "ContinuityWardrobeReference",
    "normalize_continuity_link",
    "prefer_continuity_link",
]
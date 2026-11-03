"""Versioned, editable Storyboard intent, distinct from an admitted SequencePlan (VID-STORYBOARD-350)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.video.sequence_shots import MAX_SHOTS, ShotDraft

SCHEMA = "stablenew.storyboard-draft.v1"
# Only settings the current prompt-directed sequence form can express. Authorization is never saved.
SETTING_KEYS = frozenset({"prompt", "negative_prompt", "seed", "motion_profile", "output_route"})
_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class StoryboardError(ValueError):
    """An authoring draft cannot be safely read, saved, or submitted."""


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def check_id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise StoryboardError(
            "Storyboard and shot IDs must be 32 lowercase hexadecimal characters."
        )
    return value


def _fields(data: Any, allowed: set[str], label: str) -> None:
    if not isinstance(data, dict) or set(data) != allowed:
        raise StoryboardError(f"Malformed {label}: missing or unknown fields; file left untouched.")


def _text(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 65536:
        raise StoryboardError("Draft text must be a string of at most 65536 characters.")
    return value


def _hash(value: Any) -> str:
    text = _text(value)
    if text and not _SHA.fullmatch(text):
        raise StoryboardError("A recorded media identity must be a SHA-256.")
    return text


@dataclass(frozen=True, slots=True)
class StoryboardDraft:
    storyboard_id: str
    title: str
    created_at: str
    updated_at: str
    revision: int = 0
    source_path: str = ""
    source_sha256: str = ""
    backend: str = "comfy"
    workflow_id: str = ""
    workflow_version: str = ""
    settings: tuple[tuple[str, str], ...] = ()
    shots: tuple[ShotDraft, ...] = ()
    clip_name: str = ""
    notes: str = ""
    origin_job_id: str = ""
    origin_plan_digest: str = ""
    schema: str = SCHEMA

    @classmethod
    def new(cls, title: str = "Untitled Storyboard") -> StoryboardDraft:
        now = timestamp()
        return cls(uuid4().hex, title, now, now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["settings"] = dict(self.settings)
        data["shots"] = [asdict(shot) for shot in self.shots]
        return data

    @classmethod
    def from_dict(cls, data: Any) -> StoryboardDraft:
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise StoryboardError(
                f"Unsupported Storyboard schema {data.get('schema') if isinstance(data, dict) else None!r}; no data rewritten."
            )
        _fields(data, set(cls.__dataclass_fields__), "Storyboard")
        for key in set(data) - {"revision", "settings", "shots"}:
            _text(data[key])
        check_id(data["storyboard_id"])
        if type(data["revision"]) is not int or data["revision"] < 0:
            raise StoryboardError("Draft revision must be a non-negative integer.")
        for key in ("created_at", "updated_at"):
            try:
                if datetime.fromisoformat(data[key]).tzinfo is None:
                    raise ValueError("missing timezone")
            except ValueError as exc:
                raise StoryboardError(f"Invalid {key} timestamp: {exc}") from exc
        if data["backend"] not in {"comfy", "svd_native"}:
            raise StoryboardError("Unknown Storyboard backend.")
        _hash(data["source_sha256"])
        _hash(data["origin_plan_digest"])
        settings = data["settings"]
        if not isinstance(settings, dict) or set(settings) - SETTING_KEYS:
            raise StoryboardError("Unknown Storyboard form settings; no values discarded.")
        for value in settings.values():
            _text(value)
        raw_shots = data["shots"]
        if not isinstance(raw_shots, list) or len(raw_shots) > MAX_SHOTS:
            raise StoryboardError(f"A draft may contain at most {MAX_SHOTS} shots.")
        shots = []
        for raw in raw_shots:
            _fields(raw, set(ShotDraft.__dataclass_fields__), "shot")
            for key in set(raw) - {"frame_count"}:
                _text(raw[key])
            check_id(raw["shot_id"])
            _hash(raw["keyframe_sha256"])
            if raw["frame_count"] is not None and (
                type(raw["frame_count"]) is not int or not 1 <= raw["frame_count"] <= 972
            ):
                raise StoryboardError("Shot frame count must be a positive integer or unresolved.")
            shots.append(ShotDraft(**raw))
        if len({s.shot_id for s in shots}) != len(shots):
            raise StoryboardError("Shot IDs must be unique within a Storyboard.")
        return cls(**{**data, "settings": tuple(sorted(settings.items())), "shots": tuple(shots)})

    def duplicate(self, title: str | None = None) -> StoryboardDraft:
        fresh = self.new(title if title is not None else f"{self.title} (copy)")
        return replace(
            self,
            storyboard_id=fresh.storyboard_id,
            title=fresh.title,
            created_at=fresh.created_at,
            updated_at=fresh.updated_at,
            revision=0,
            shots=tuple(replace(s, shot_id=uuid4().hex) for s in self.shots),
        )

    def fingerprint(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def move(self, index: int, offset: int) -> StoryboardDraft:
        shots = list(self.shots)
        target = index + offset
        if not 0 <= index < len(shots) or not 0 <= target < len(shots):
            raise StoryboardError("Shot move is outside the draft.")
        shots.insert(target, shots.pop(index))
        return replace(self, shots=tuple(shots))

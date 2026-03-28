from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ContentVisibilityMode(str, Enum):
    """Global content visibility mode for user-facing surfaces."""

    NSFW = "nsfw"
    SFW = "sfw"


DEFAULT_CONTENT_VISIBILITY_MODE = ContentVisibilityMode.NSFW


def normalize_content_visibility_mode(value: Any) -> ContentVisibilityMode:
    """Normalize persisted/user-provided mode values to canonical enum values."""
    if isinstance(value, ContentVisibilityMode):
        return value
    text = str(value or "").strip().lower()
    if text == ContentVisibilityMode.SFW.value:
        return ContentVisibilityMode.SFW
    if text == ContentVisibilityMode.NSFW.value:
        return ContentVisibilityMode.NSFW
    return DEFAULT_CONTENT_VISIBILITY_MODE


@dataclass(frozen=True)
class ContentVisibilitySettings:
    """Serializable content visibility settings payload."""

    mode: ContentVisibilityMode = DEFAULT_CONTENT_VISIBILITY_MODE

    @classmethod
    def from_payload(cls, payload: Any) -> "ContentVisibilitySettings":
        if isinstance(payload, dict):
            return cls(mode=normalize_content_visibility_mode(payload.get("mode")))
        return cls()

    def to_payload(self) -> dict[str, str]:
        return {"mode": self.mode.value}

"""Ephemeral media inspection state; host workspaces retain artifact/selection authority."""

from dataclasses import dataclass
from pathlib import PurePath

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".gif", ".avi"}


@dataclass
class MediaInspectorState:
    default_shown: bool = True
    path: str = ""
    kind: str = "none"
    shown: bool = True
    eligible: bool = True
    active: bool = True
    detached: bool = False
    revision: int = 0
    zoom: float | None = None  # None = Fit; numeric values are decoded-preview pixels
    status: str = "none"

    def select(self, path: str, kind: str | None = None) -> bool:
        path = str(path or "")
        if path == self.path and (kind is None or kind == self.kind):
            return False
        self.revision += 1
        self.path = path
        suffix = PurePath(path).suffix.lower()
        self.kind = kind or (
            "image" if suffix in IMAGE_SUFFIXES else "video" if suffix in VIDEO_SUFFIXES else "none"
        )
        self.shown = self.default_shown
        self.zoom = None
        self.status = "loading" if self.kind != "none" else "unsupported" if path else "none"
        return True

    @property
    def renderable(self) -> bool:
        return bool(
            self.path and self.shown and self.eligible and self.active and self.kind != "none"
        )

    def visibility(
        self, *, shown: bool | None = None, eligible: bool | None = None, active: bool | None = None
    ) -> None:
        for name, value in (("shown", shown), ("eligible", eligible), ("active", active)):
            if value is not None and getattr(self, name) != value:
                setattr(self, name, value)
                self.revision += 1

    def move(self, detached: bool) -> None:
        if self.detached != detached:
            self.detached = detached
            self.revision += 1

    def zoom_by(self, factor: float) -> None:
        self.zoom = min(8.0, max(0.125, (self.zoom or 1.0) * factor))

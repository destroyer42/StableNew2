"""In-memory Edit fixtures, draft revisions and frozen comparison candidates."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum


class EditRefused(ValueError):
    """A mock edit action needs a different or more current input."""


class Mode(StrEnum):
    QUICK = "Quick Edit"
    MASKED = "Masked Edit"
    EXTEND = "Extend Canvas"


class Availability(StrEnum):
    AVAILABLE = "Available"
    MISSING = "Missing file"
    HIDDEN = "Hidden by fixture policy"
    UNSUPPORTED = "Unsupported media"


class Replacement(StrEnum):
    KEEP = "Keep draft"
    CANCEL = "Cancel"
    REPLACE = "Replace draft"


@dataclass(frozen=True)
class EditSource:
    key: str
    title: str
    motif: int
    size: tuple[int, int] = (640, 400)
    availability: Availability = Availability.AVAILABLE
    parent: str | None = None
    negative_supported: bool = True


CREATE_SOURCE = "create:ridge-study"
SOURCES = (
    EditSource(CREATE_SOURCE, "Ridge study", 0),
    EditSource("history:ridge-17", "Ridge revision 17", 1, parent="history:ridge-16"),
    EditSource("history:ridge-16", "Ridge revision 16", 0),
    EditSource("import:coast", "Imported coast study", 2, negative_supported=False),
    EditSource("photo:evening", "Evening candidate", 3, size=(600, 400)),
    EditSource("history:missing", "Missing still", 0, availability=Availability.MISSING),
    EditSource("history:hidden", "Restricted still", 1, availability=Availability.HIDDEN),
    EditSource("import:clip", "Imported clip", 2, availability=Availability.UNSUPPORTED),
)
PROFILES = {
    "Still image fixture": frozenset(Mode),
    "Prompt-only fixture": frozenset({Mode.QUICK}),
}
REGIONS = ("Foreground", "Background")
UNDO_LIMIT = 50


def source_for(key: str) -> EditSource:
    for source in SOURCES:
        if source.key == key:
            return source
    raise EditRefused(f"Unknown source identity: {key}. Select an explicit fixture.")


def require_available(key: str) -> EditSource:
    source = source_for(key)
    if source.availability != Availability.AVAILABLE:
        raise EditRefused(f"{source.availability}. No substitute selected for {source.key}.")
    return source


@dataclass(frozen=True)
class ImageTransform:
    """Widget logical pixels to source coordinates, with half-open pixel bounds."""

    left: float
    top: float
    scale: float
    size: tuple[int, int]

    def source_pixel(self, x: float, y: float) -> tuple[int, int] | None:
        px = math.floor((x - self.left) / self.scale)
        py = math.floor((y - self.top) / self.scale)
        return (px, py) if 0 <= px < self.size[0] and 0 <= py < self.size[1] else None


def paint_segment(
    pixels: bytearray,
    size: tuple[int, int],
    start: tuple[int, int],
    end: tuple[int, int],
    radius: int,
    *,
    erase: bool = False,
) -> None:
    """Rasterize a round brush sweep across source pixel centers."""
    width, height = size
    x0, y0 = start
    x1, y1 = end
    dx, dy = x1 - x0, y1 - y0
    length_squared = dx * dx + dy * dy
    value = 0 if erase else 255
    for y in range(max(0, min(y0, y1) - radius), min(height, max(y0, y1) + radius + 1)):
        for x in range(max(0, min(x0, x1) - radius), min(width, max(x0, x1) + radius + 1)):
            t = ((x - x0) * dx + (y - y0) * dy) / length_squared if length_squared else 0
            t = min(1, max(0, t))
            if (x - x0 - dx * t) ** 2 + (y - y0 - dy * t) ** 2 <= radius**2:
                pixels[y * width + x] = value


def suggest_mask(key: str) -> bytes:
    source = require_available(key)
    if not key.startswith(("create:", "history:")):
        raise EditRefused("Simulated suggestion unavailable for this fixture. Use Brush or Erase.")
    width, height = source.size
    mask = bytearray(width * height)
    paint_segment(mask, source.size, (width // 3, height // 2), (width // 2, height // 2), 42)
    return bytes(mask)


@dataclass(frozen=True)
class EditRegion:
    name: str
    prompt: str = ""
    negative: str = ""
    strength: int = 40
    feather: int = 8
    mask: bytes = b""


@dataclass(frozen=True)
class Geometry:
    left: int = 32
    top: int = 0
    right: int = 32
    bottom: int = 0

    def output_size(self, source_size: tuple[int, int]) -> tuple[int, int]:
        margins = (self.left, self.top, self.right, self.bottom)
        if not all(type(value) is int and 0 <= value <= 512 for value in margins):
            raise EditRefused("Margins must be whole pixels between 0 and 512.")
        if not any(margins):
            raise EditRefused("Set at least one positive extension margin.")
        width, height = source_size
        return width + self.left + self.right, height + self.top + self.bottom


@dataclass(frozen=True)
class EditDraft:
    source_key: str
    mode: Mode = Mode.QUICK
    profile: str = "Still image fixture"
    active_region: int = 0
    regions: tuple[EditRegion, ...] = tuple(EditRegion(name) for name in REGIONS)
    geometry: Geometry = Geometry()

    @property
    def region(self) -> EditRegion:
        return self.regions[self.active_region]


@dataclass(frozen=True)
class EditPreview:
    revision: int
    draft: EditDraft
    errors: tuple[str, ...]
    output_size: tuple[int, int] | None = None


@dataclass(frozen=True)
class Candidate:
    key: str
    parent: str
    preview: EditPreview


def evaluate(draft: EditDraft, revision: int) -> EditPreview:
    errors = []
    try:
        source = require_available(draft.source_key)
    except EditRefused as exc:
        return EditPreview(revision, draft, (str(exc),))
    size = source.size
    region = draft.region
    if draft.mode not in PROFILES.get(draft.profile, ()):
        errors.append("The selected profile fixture does not support this editing mode.")
    if not region.prompt.strip():
        errors.append("Enter an edit prompt for the selected region.")
    if region.negative and not source.negative_supported:
        errors.append("Negative prompt is excluded for this source fixture.")
    if draft.mode != Mode.EXTEND and (
        type(region.strength) is not int or not 0 <= region.strength <= 100
    ):
        errors.append("Edit strength must be between 0 and 100%.")
    if draft.mode == Mode.MASKED:
        if len(region.mask) != size[0] * size[1] or not any(region.mask):
            errors.append("Paint a non-empty mask for the selected region.")
        if type(region.feather) is not int or not 0 <= region.feather <= 32:
            errors.append("Feather must be between 0 and 32 source pixels.")
    if draft.mode == Mode.EXTEND:
        try:
            size = draft.geometry.output_size(size)
        except EditRefused as exc:
            size = None
            errors.append(str(exc))
    return EditPreview(revision, draft, tuple(errors), size)


class EditSession:
    """Single owner of mutable prototype state. Candidates and snapshots are immutable."""

    def __init__(self):
        self.draft: EditDraft | None = None
        self.revision = 0
        self.preview: EditPreview | None = None
        self.candidates: list[Candidate] = []
        self.baselines: dict[str, str] = {}
        self._initial: EditDraft | None = None
        self._undo: list[EditDraft] = []
        self._redo: list[EditDraft] = []
        self._admitted: Candidate | None = None

    @property
    def dirty(self) -> bool:
        return self.draft != self._initial

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def status(self) -> str:
        if self.preview is None:
            return "Not built"
        if self.preview.revision != self.revision:
            return "Stale"
        if self.preview.errors:
            return "Blocked"
        if self._admitted is not None:
            return "Simulated admission recorded"
        return "Current / ready"

    def select(self, key: str, choice: Replacement | None = None) -> bool:
        require_available(key)
        if self.draft is not None and self.draft.source_key == key:
            return True
        if self.dirty and choice != Replacement.REPLACE:
            return False
        self._initial = EditDraft(key)
        self._undo.clear()
        self._redo.clear()
        self.preview = None
        self._set_draft(self._initial)
        return True

    def _set_draft(self, draft: EditDraft) -> None:
        self.draft = draft
        self.revision += 1
        self._admitted = None

    def update(self, **changes) -> None:
        if self.draft is None:
            raise EditRefused("Select an available source first.")
        draft = replace(self.draft, **changes)
        if draft != self.draft:
            self._undo.append(self.draft)
            del self._undo[:-UNDO_LIMIT]
            self._redo.clear()
            self._set_draft(draft)

    def update_region(self, **changes) -> None:
        if self.draft is None:
            raise EditRefused("Select an available source first.")
        regions = list(self.draft.regions)
        regions[self.draft.active_region] = replace(self.draft.region, **changes)
        self.update(regions=tuple(regions))

    def commit_mask(self, revision: int, mask: bytes) -> bool:
        if revision != self.revision or self.draft is None or self.draft.mode != Mode.MASKED:
            return False
        width, height = require_available(self.draft.source_key).size
        if len(mask) != width * height:
            raise EditRefused("Mask dimensions do not match the selected source.")
        self.update_region(mask=mask if any(mask) else b"")
        return True

    def undo(self) -> None:
        if self.draft is not None and self._undo:
            self._redo.append(self.draft)
            self._set_draft(self._undo.pop())

    def redo(self) -> None:
        if self.draft is not None and self._redo:
            self._undo.append(self.draft)
            self._set_draft(self._redo.pop())

    def build_preview(self) -> EditPreview:
        if self.draft is None:
            raise EditRefused("Select an available source first.")
        preview = evaluate(self.draft, self.revision)
        self.install_preview(preview)
        return preview

    def install_preview(self, preview: EditPreview) -> bool:
        if preview.revision != self.revision or preview.draft != self.draft:
            return False
        self.preview = preview
        return True

    def admit(self) -> Candidate:
        if self._admitted is not None:
            return self._admitted
        if self.status != "Current / ready" or self.preview is None:
            raise EditRefused("Build a current, ready Preview before simulated admission.")
        candidate = Candidate(
            f"edit:candidate-{len(self.candidates) + 1}",
            self.preview.draft.source_key,
            self.preview,
        )
        self.candidates.append(candidate)
        self._admitted = candidate
        return candidate

    def set_baseline(self, candidate: Candidate) -> None:
        if candidate not in self.candidates:
            raise EditRefused("Select a recorded mock candidate.")
        self.baselines[candidate.parent] = candidate.key

"""Pure (Qt-free) model for the Output Display: zoom math, size modes, frame content.

Nothing here touches the GUI, the filesystem or StableNew. The "frame" is a
placeholder describing what *would* be shown; no image is ever generated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .domain import MODELS, CreateSession, expand_prompt

MIN_ZOOM = 0.05
MAX_ZOOM = 16.0
ZOOM_STEP = 1.25
SLIDER_STEPS = 1000

SIZE_FREE = "free"      # user drags the splitter/dock edge
SIZE_LOCKED = "locked"  # width (or floating size) frozen until unlocked
SIZE_FILL = "fill"      # takes all space the Create workspace does not need
SIZE_MODES = (SIZE_FREE, SIZE_LOCKED, SIZE_FILL)

ZOOM_FIT = "fit"        # re-fits whenever the viewport resizes
ZOOM_CUSTOM = "custom"  # explicit factor; includes 100%


def clamp_zoom(zoom: float) -> float:
    if not math.isfinite(zoom) or zoom <= 0:
        return 1.0
    return max(MIN_ZOOM, min(MAX_ZOOM, zoom))


def step_zoom(zoom: float, direction: int) -> float:
    """One zoom step in/out. Snaps to exactly 100% when a step would cross it."""
    if direction == 0:
        return clamp_zoom(zoom)
    target = zoom * (ZOOM_STEP if direction > 0 else 1.0 / ZOOM_STEP)
    if (zoom < 1.0 < target) or (zoom > 1.0 > target):
        return 1.0
    return clamp_zoom(target)


def fit_factor(view_w: float, view_h: float, content_w: float, content_h: float, margin: float = 0.0) -> float:
    """Largest zoom at which the whole content fits the viewport (upscaling allowed)."""
    if content_w <= 0 or content_h <= 0:
        return 1.0
    avail_w, avail_h = view_w - 2 * margin, view_h - 2 * margin
    if avail_w <= 0 or avail_h <= 0:
        return MIN_ZOOM
    return clamp_zoom(min(avail_w / content_w, avail_h / content_h))


def slider_to_zoom(value: int) -> float:
    value = max(0, min(SLIDER_STEPS, value))
    return clamp_zoom(MIN_ZOOM * (MAX_ZOOM / MIN_ZOOM) ** (value / SLIDER_STEPS))


def zoom_to_slider(zoom: float) -> int:
    zoom = clamp_zoom(zoom)
    return round(SLIDER_STEPS * math.log(zoom / MIN_ZOOM) / math.log(MAX_ZOOM / MIN_ZOOM))


def format_zoom(zoom: float) -> str:
    percent = zoom * 100
    return f"{percent:.0f}%" if percent >= 10 else f"{percent:.1f}%"


def fill_width(window_width: int, workspace_width: int, minimum: int, maximum: int | None = None) -> int:
    """Width the dock takes in Fill mode: everything the workspace does not need."""
    width = max(minimum, window_width - workspace_width)
    return min(width, maximum) if maximum else width


@dataclass(frozen=True)
class OutputFrame:
    """What the display shows. ``kind`` is draft | preview | stale | receipt."""

    width: int
    height: int
    kind: str
    title: str
    lines: tuple[str, ...]

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 1.0

    @property
    def dimensions(self) -> str:
        return f"{self.width} × {self.height}"


_KIND_TITLES = {
    "draft": "DRAFT FRAME",
    "preview": "PREVIEW BUILT",
    "stale": "PREVIEW STALE",
    "receipt": "SIMULATED RECEIPT",
}


def frame_from_session(session: CreateSession) -> OutputFrame:
    """Derive the placeholder frame from the Create draft (display only)."""
    draft = session.draft
    settings = draft.settings
    if session.demo_receipt is not None:
        kind = "receipt"
    elif session.preview is None:
        kind = "draft"
    elif session.is_preview_current:
        kind = "preview"
    else:
        kind = "stale"
    model = next((m.label for m in MODELS if m.key == draft.model_key), draft.model_key)
    resolved = expand_prompt(draft.prompt, draft.slots)[0].strip() or "(empty prompt)"
    seed = "Random" if settings.seed < 0 else str(settings.seed)
    lines = (
        resolved,
        f"{model}",
        f"{settings.sampler} · {settings.scheduler} · {settings.steps} steps · CFG {settings.cfg:g}",
        f"Seed {seed} · batch {settings.batch}",
        "No image generated",
    )
    return OutputFrame(int(settings.width), int(settings.height), kind, _KIND_TITLES[kind], lines)

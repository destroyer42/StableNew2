"""Typed contracts and hard caps for Smart Review assistance (PR-IMG-REVIEW-320).

Nothing here does I/O or imports a model library. Smart Review proposes a binary object mask (SAM 2.1 Small) or a
caption with object labels (Florence-2 Base FT) for ONE operator-selected image. A proposal is data held in memory; it
changes no pixel, prompt, rating or queue until the operator explicitly accepts it.

Coordinates are the pixels the existing mask editor shows and freezes: the Pillow-decoded stored pixels (EXIF rotation is
recorded in the identity but not applied), so a mask is always the exact size of the edit source.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.conditioning.reference_map.contracts import (
    WARNING_MEMORY_UNENFORCED,
    AuxiliaryFileIdentity,
)

CAPABILITY_SEGMENT = "sam2"
CAPABILITY_CAPTION = "florence2"
CAPABILITIES = (CAPABILITY_SEGMENT, CAPABILITY_CAPTION)
TITLES = {CAPABILITY_SEGMENT: "SAM 2.1 Small", CAPABILITY_CAPTION: "Florence-2 Base FT"}

#: Stable, content-free failure codes. Callers and tests branch on these, never on message text.
CODE_CANCELLED = "cancelled"
CODE_TIMEOUT = "timeout"
CODE_UNAVAILABLE = "provider_unavailable"
CODE_DISABLED = "disabled"
CODE_BUSY = "busy"
CODE_STALE = "stale"
CODE_SOURCE_CHANGED = "source_changed"
CODE_SOURCE = "source_invalid"
CODE_PROMPT = "invalid_prompt"
CODE_OUTPUT = "invalid_output"
CODE_INFERENCE = "inference_failed"

#: Input and output caps. Every one is enforced before an allocation or a hand-off.
MAX_POINTS = 4
MAX_BOXES = 1
MAX_CAPTION_CHARS = 600
MAX_LABEL_CHARS = 48
MAX_OBJECTS = 16
MAX_MASK_BYTES = 4 * 1024 * 1024
MAX_LOGIT_SIDE = 512
MAX_RESULT_TEXT_BYTES = 16 * 1024
MAX_CONCURRENT_ANALYSES = 1
#: A proposal that selects more of the image than this is "unreasonably broad" and is refused.
MAX_MASK_COVERAGE = 0.95
#: Documented threshold: a model logit strictly above this is edit (white), everything else is preserve (black).
LOGIT_THRESHOLD = 0.0

MASK_EDIT = 255
MASK_PRESERVE = 0


class AssistError(Exception):
    """A request could not be served. ``code`` is machine-readable; ``message`` is operator-facing, path-free and content-free."""

    def __init__(self, code: str, message: str, *, reasons: tuple[str, ...] = ()) -> None:
        self.code = code
        self.message = message
        self.reasons = tuple(reasons)
        super().__init__(message)


class AssistUnavailable(AssistError):
    """The capability cannot run right now. Never answered by a different model."""

    def __init__(self, message: str, *, reasons: tuple[str, ...]) -> None:
        super().__init__(CODE_UNAVAILABLE, message, reasons=reasons)


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """What a request is bound to. Two files with one name and different bytes are different identities."""

    file_sha256: str
    file_size: int
    width: int
    height: int
    exif_orientation: int
    image_format: str

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


@dataclass(frozen=True, slots=True)
class PointPrompt:
    x: int
    y: int
    positive: bool

    @property
    def label(self) -> int:
        return 1 if self.positive else 0


@dataclass(frozen=True, slots=True)
class BoxPrompt:
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    capability: str
    resource_id: str
    adapter: str
    files: tuple[AuxiliaryFileIdentity, ...] = ()
    runtime: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        versions = ", ".join(f"{k} {v}" for k, v in sorted(self.runtime.items()))
        unbounded = (
            "; MEMORY LIMIT NOT ENFORCED" if WARNING_MEMORY_UNENFORCED in self.warnings else ""
        )
        return f"{TITLES.get(self.capability, self.capability)} ({self.adapter}{'; ' + versions if versions else ''}{unbounded})"


@dataclass(frozen=True, slots=True)
class SegmentOutput:
    """What an adapter returns: low-resolution logits (2-D, float) and the model's own quality estimate, if any."""

    logits: object  # numpy.ndarray; typed loosely so this module imports no array library
    score: float | None
    model: ModelIdentity


@dataclass(frozen=True, slots=True)
class RawObject:
    label: str
    box: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class CaptionOutput:
    text: str
    objects: tuple[RawObject, ...]
    model: ModelIdentity


@dataclass(frozen=True, slots=True)
class SegmentProposal:
    ticket: int
    identity: SourceIdentity
    mask_png: bytes
    mask_sha256: str
    coverage: float
    score: float | None
    model: ModelIdentity


@dataclass(frozen=True, slots=True)
class ObjectLabel:
    label: str
    box: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class CaptionProposal:
    ticket: int
    identity: SourceIdentity
    text: str
    truncated: bool
    objects: tuple[ObjectLabel, ...]
    model: ModelIdentity


@dataclass(frozen=True, slots=True)
class Availability:
    capability: str
    available: bool
    reasons: tuple[str, ...]
    message: str


CancelCheck = Callable[[], bool]

#: Operator-facing text for reason codes; unknown codes are shown verbatim (they are content-free by construction).
REASON_TEXT: dict[str, str] = {
    "disabled": "Turned off. Tick Enable to allow this local model for this session.",
    "no_webui_root": "No WebUI folder is configured, so model files cannot be located.",
    "catalog_unreadable": "The curated model catalog could not be read.",
    "not_in_catalog": "The model is not in the curated catalog.",
    "transformers_too_old": "The installed Transformers is older than the qualified 5.17.0.",
    "transformers_too_new": "The installed Transformers is a major version newer than the qualified 5.x.",
    "probe_failed": "The model files could not be checked.",
}


def reason_text(code: str) -> str:
    if code in REASON_TEXT:
        return REASON_TEXT[code]
    kind, _, detail = code.partition(":")
    if kind == "runtime_missing":
        return f"The Python package '{detail}' is not installed."
    if kind == "resource_missing":
        return f"A required model file is missing ({detail})."
    if kind == "hash_mismatch":
        return f"A model file does not match its pinned SHA-256 ({detail})."
    if kind == "ambiguous":
        return f"More than one candidate file was found ({detail})."
    return code

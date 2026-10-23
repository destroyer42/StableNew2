"""Small typed contracts shared by every reference-map modality (PR-IMG-CNET-230).

Nothing here does I/O. A request names a source file and a modality; a prepared map is the in-memory result (PNG bytes,
facts, exact method identity and provenance) that exists only until the operator saves it or abandons it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.conditioning.controlnet import MODALITIES

#: Stable, content-free failure codes. Callers and tests branch on these, never on message text.
CODE_CANCELLED = "cancelled"
CODE_STALE = "stale"
CODE_INVALID_REQUEST = "invalid_request"
CODE_UNAVAILABLE = "provider_unavailable"
CODE_INFERENCE = "inference_failed"
CODE_TIMEOUT = "timeout"
CODE_NO_PEOPLE = "no_people"
CODE_DEPTH_NON_FINITE = "depth_non_finite"
CODE_DEPTH_FLAT = "depth_flat"
CODE_SOURCE_CHANGED = "source_changed"
CODE_NOT_PREPARED = "not_prepared"

SOURCE_CODE_PREFIX = "source_"
LIBRARY_CODE_PREFIX = "library_"

PROVENANCE_CONTRACT = "reference_map_provenance/1"
#: Hard cap on a provenance sidecar (it is bounded by construction; the cap protects readers from a hostile file).
MAX_PROVENANCE_BYTES = 16 * 1024
WARNING_LIMIT = 8

ProgressSignal = Callable[[str], None]
CancelCheck = Callable[[], bool]


class ReferenceMapError(Exception):
    """A map could not be prepared or saved. ``code`` is machine-readable; ``message`` is operator-facing and path-free."""

    def __init__(self, code: str, message: str, *, reasons: tuple[str, ...] = ()) -> None:
        self.code = code
        self.message = message
        #: Precise, stable reason codes behind the failure (for example ``runtime_missing:onnxruntime``).
        self.reasons = tuple(reasons)
        super().__init__(message)


class ProviderUnavailable(ReferenceMapError):
    """The modality cannot run on this machine right now. Never answered by a different modality or method."""

    def __init__(self, message: str, *, reasons: tuple[str, ...]) -> None:
        super().__init__(CODE_UNAVAILABLE, message, reasons=reasons)


@dataclass(frozen=True, slots=True)
class MapRequest:
    source: Path
    modality: str

    def __post_init__(self) -> None:
        if self.modality not in MODALITIES:
            raise ReferenceMapError(
                CODE_INVALID_REQUEST, f"Unsupported map type '{self.modality}'."
            )


@dataclass(frozen=True, slots=True)
class SourceFacts:
    """What was read from the source file, recorded before any inference runs."""

    file_sha256: str
    file_size: int
    image_format: str
    #: Dimensions after EXIF orientation; every map is produced at exactly this size.
    width: int
    height: int
    #: SHA-256 over the oriented RGB pixels (a different EXIF orientation of the same file hashes differently).
    oriented_sha256: str
    exif_transposed: bool


@dataclass(frozen=True, slots=True)
class AuxiliaryFileIdentity:
    role: str
    #: Posix path below ``models/StableNewAux`` (never absolute).
    relative: str
    sha256: str
    size_bytes: int
    #: ``False`` when the curated catalog pins no digest for this file (it is recorded, not verified).
    pinned: bool


@dataclass(frozen=True, slots=True)
class MethodIdentity:
    method_id: str
    version: int
    config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreparedMap:
    """One finished map held in memory. Nothing is on disk until the operator saves it."""

    modality: str
    png: bytes
    sha256: str
    width: int
    height: int
    source: SourceFacts
    method: MethodIdentity
    auxiliary: tuple[AuxiliaryFileIdentity, ...] = ()
    auxiliary_resource: str = ""
    runtime: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    #: Operator-selected source path, kept only to re-verify the source before publication. Never persisted or logged.
    source_path: Path | None = None


#: Operator-facing text for each warning code a map may carry.
WARNING_TEXT: dict[str, str] = {
    "pose_no_hands": "No hands were detected; the map has no hand keypoints.",
    "pose_no_face": "No face keypoints were detected; the map has no face keypoints.",
    "pose_people_truncated": "More people were detected than the map draws; only the most confident were kept.",
    "pose_partial_body": "Some body keypoints were not confident enough to draw.",
    "auxiliary_config_unpinned": (
        "A small configuration file of the model is not covered by a pinned digest; its SHA-256 is recorded."
    ),
}


def warning_text(code: str) -> str:
    return WARNING_TEXT.get(code, code)

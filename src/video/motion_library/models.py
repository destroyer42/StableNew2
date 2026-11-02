"""Motion Library asset records (PR-VID-MOTION-LIB-353).

A motion asset is a *description* of a local reference video: where it lives, which bytes it is
(SHA-256), what it shows and how it may be used.  It owns no job, queue, history or model authority.

Records round-trip through plain JSON (``to_dict`` / ``from_dict``).  ``from_dict`` is strict about
shape (a malformed record raises ``AssetFormatError``) but tolerant about vocabulary: an unknown
enumerated value reads back as ``"unknown"`` so a hand-edited or newer manifest never crashes the
browser.  Nothing here touches the file system, a process or the GUI.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

ASSET_ID_PREFIX = "mlib_"
_ASSET_ID = re.compile(r"^mlib_[0-9a-f]{16,32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# --- vocabularies -------------------------------------------------------------------------------
UNKNOWN = "unknown"

SOURCE_OWNER_RECORDED = "owner_recorded"
SOURCE_STOCK_FOOTAGE = "stock_footage"
SOURCE_RENDERED_MOCAP = "rendered_mocap"
SOURCE_STABLENEW_GENERATED = "stablenew_generated"
SOURCE_OTHER = "other"
SOURCE_CATEGORIES = (
    SOURCE_OWNER_RECORDED,
    SOURCE_STOCK_FOOTAGE,
    SOURCE_RENDERED_MOCAP,
    SOURCE_STABLENEW_GENERATED,
    SOURCE_OTHER,
)
SOURCE_CATEGORY_LABELS = {
    SOURCE_OWNER_RECORDED: "Owner recorded",
    SOURCE_STOCK_FOOTAGE: "Stock footage",
    SOURCE_RENDERED_MOCAP: "Rendered mocap",
    SOURCE_STABLENEW_GENERATED: "StableNew generated",
    SOURCE_OTHER: "Other / unknown",
}

LOCATOR_LINKED = "linked"
LOCATOR_MANAGED = "managed"
LOCATOR_MODES = (LOCATOR_LINKED, LOCATOR_MANAGED)

REVIEW_UNREVIEWED = "unreviewed"
REVIEW_REVIEWED = "reviewed"
REVIEW_REJECTED = "rejected"
REVIEW_STATUSES = (REVIEW_UNREVIEWED, REVIEW_REVIEWED, REVIEW_REJECTED)

SUBJECT_HUMAN = "human"
SUBJECT_NONHUMAN = "nonhuman"
SUBJECT_KINDS = (SUBJECT_HUMAN, SUBJECT_NONHUMAN, UNKNOWN)

FRAMING_FULL_BODY = "full_body"
FRAMING_UPPER_BODY = "upper_body"
FRAMING_PARTIAL = "partial"
FRAMINGS = (FRAMING_FULL_BODY, FRAMING_UPPER_BODY, FRAMING_PARTIAL, UNKNOWN)

CAMERA_MOVEMENTS = ("static", "pan", "tilt", "zoom", "tracking", "handheld", "orbit", UNKNOWN)
VIEWPOINTS = ("front", "three_quarter", "side", "back", "top_down", "low_angle", UNKNOWN)
INTENSITIES = ("low", "medium", "high", UNKNOWN)
LOOP_LOOPABLE = "loopable"
LOOP_ONE_SHOT = "one_shot"
LOOP_SUITABILITIES = (LOOP_LOOPABLE, LOOP_ONE_SHOT, UNKNOWN)

# --- bounds -------------------------------------------------------------------------------------
MAX_NAME_CHARS = 120
MAX_TAGS = 40
MAX_TAG_CHARS = 40
MAX_NOTE_CHARS = 2000
MAX_SHORT_TEXT_CHARS = 400
MAX_ALIASES = 50
MAX_URL_CHARS = 1000


class AssetFormatError(ValueError):
    """A manifest record is malformed (wrong shape or an unusable required value)."""


# --- text helpers (pure) ------------------------------------------------------------------------


def clean_text(value: Any, limit: int = MAX_SHORT_TEXT_CHARS) -> str:
    """Printable, single-line, bounded text.  Control characters never reach the manifest or a label."""

    text = "".join(
        ch if ch.isprintable() else " " for ch in str(value if value is not None else "")
    )
    return " ".join(text.split())[:limit]


def clean_note(value: Any, limit: int = MAX_NOTE_CHARS) -> str:
    """Bounded multi-line text; control characters other than newlines are dropped."""

    raw = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in raw if ch == "\n" or ch.isprintable())
    return text.strip()[:limit]


def normalize_tag(value: Any) -> str:
    """One searchable tag: lower-case ASCII words joined by ``-`` (``"Walking  Cycle!"`` -> ``walking-cycle``)."""

    decomposed = unicodedata.normalize("NFKD", str(value if value is not None else ""))
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:MAX_TAG_CHARS]


def normalize_tags(values: Any) -> tuple[str, ...]:
    """Normalized, de-duplicated tags in first-seen order.  Accepts a sequence or a comma/semicolon string."""

    if isinstance(values, str):
        items: Sequence[Any] = re.split(r"[,;\n]", values)
    elif isinstance(values, Sequence):
        items = values
    else:
        items = ()
    seen: dict[str, None] = {}
    for item in items:
        tag = normalize_tag(item)
        if tag and tag not in seen:
            seen[tag] = None
        if len(seen) >= MAX_TAGS:
            break
    return tuple(seen)


def choice(value: Any, allowed: Sequence[str], default: str = UNKNOWN) -> str:
    text = (
        str(value if value is not None else "").strip().lower().replace(" ", "_").replace("-", "_")
    )
    return text if text in allowed else default


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _positive_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 and number == number and number != float("inf") else None


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.match(value))


# --- records ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssetLocator:
    """Where the bytes are.  ``linked``: an absolute path the library only reads.  ``managed``: a file
    name inside the library's ``managed/`` folder, which the library created by an explicit copy."""

    mode: str
    path: str
    size_bytes: int | None = None
    mtime_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
        }

    @classmethod
    def from_dict(cls, data: Any) -> AssetLocator:
        if not isinstance(data, Mapping):
            raise AssetFormatError("locator must be an object")
        mode = str(data.get("mode") or "")
        path = str(data.get("path") or "")
        if mode not in LOCATOR_MODES or not path.strip():
            raise AssetFormatError("locator needs a mode (linked/managed) and a path")
        return cls(
            mode=mode,
            path=path,
            size_bytes=_non_negative_int(data.get("size_bytes")),
            mtime_ns=_non_negative_int(data.get("mtime_ns")),
        )


@dataclass(frozen=True, slots=True)
class AssetAlias:
    """Another path/name the same bytes were imported from.  Never dropped when a duplicate is seen."""

    path: str
    name: str = ""
    source_reference: str = ""
    added_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "source_reference": self.source_reference,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> AssetAlias:
        if not isinstance(data, Mapping):
            raise AssetFormatError("alias must be an object")
        return cls(
            path=str(data.get("path") or "")[:1000],
            name=clean_text(data.get("name"), MAX_NAME_CHARS),
            source_reference=clean_text(data.get("source_reference")),
            added_at=clean_text(data.get("added_at"), 40),
        )


@dataclass(frozen=True, slots=True)
class GeneratedOrigin:
    """Provenance of a StableNew-generated clip kept as a motion primitive (read from the canonical job once)."""

    job_id: str
    artifact_path: str = ""
    artifact_sha256: str = ""
    workflow_id: str = ""
    workflow_version: str = ""
    backend_id: str = ""
    seed: int | None = None
    source_image_path: str = ""
    source_image_sha256: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    motion_label: str = ""
    #: True/False when the operator said whether the requested motion was achieved; None when not judged.
    motion_achieved: bool | None = None
    known_artifacts: str = ""
    reuse_conditions: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "backend_id": self.backend_id,
            "seed": self.seed,
            "source_image_path": self.source_image_path,
            "source_image_sha256": self.source_image_sha256,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "motion_label": self.motion_label,
            "motion_achieved": self.motion_achieved,
            "known_artifacts": self.known_artifacts,
            "reuse_conditions": self.reuse_conditions,
        }

    @classmethod
    def from_dict(cls, data: Any) -> GeneratedOrigin:
        if not isinstance(data, Mapping):
            raise AssetFormatError("origin must be an object")
        job_id = clean_text(data.get("job_id"), 120)
        if not job_id:
            raise AssetFormatError("origin needs a job id")
        seed = data.get("seed")
        achieved = data.get("motion_achieved")
        return cls(
            job_id=job_id,
            artifact_path=str(data.get("artifact_path") or "")[:1000],
            artifact_sha256=str(data.get("artifact_sha256") or "")
            if is_sha256(data.get("artifact_sha256"))
            else "",
            workflow_id=clean_text(data.get("workflow_id"), 120),
            workflow_version=clean_text(data.get("workflow_version"), 60),
            backend_id=clean_text(data.get("backend_id"), 120),
            seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
            source_image_path=str(data.get("source_image_path") or "")[:1000],
            source_image_sha256=str(data.get("source_image_sha256") or "")
            if is_sha256(data.get("source_image_sha256"))
            else "",
            prompt=clean_note(data.get("prompt")),
            negative_prompt=clean_note(data.get("negative_prompt")),
            motion_label=clean_text(data.get("motion_label"), MAX_NAME_CHARS),
            motion_achieved=achieved if isinstance(achieved, bool) else None,
            known_artifacts=clean_note(data.get("known_artifacts")),
            reuse_conditions=clean_note(data.get("reuse_conditions")),
        )


@dataclass(frozen=True, slots=True)
class DerivationRecord:
    """Pointer from a converted clip back to the animation file it was rendered from (PR-VID-MOTION-354).

    The clip's own ``sha256`` stays its identity; ``source_sha256`` is the identity of the *original* animation.  The full
    machine-readable record is the conversion's ``provenance.json``; this keeps the facts a browser needs, so provenance
    survives a restart without the converter being available.  The catalog never reads the source or runs a conversion."""

    source_sha256: str
    source_type: str
    source_name: str = ""
    source_path: str = ""
    provenance_path: str = ""
    plan_digest: str = ""
    profile: str = ""
    camera: str = ""
    camera_mode: str = ""
    root_motion: str = ""
    blender_version: str = ""
    script_version: str = ""
    character_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}

    @classmethod
    def from_dict(cls, data: Any) -> DerivationRecord:
        if not isinstance(data, Mapping):
            raise AssetFormatError("derivation must be an object")
        sha = str(data.get("source_sha256") or "")
        if not is_sha256(sha):
            raise AssetFormatError("derivation needs the source file's sha256")
        return cls(
            source_sha256=sha,
            source_type=clean_text(data.get("source_type"), 20),
            source_name=clean_text(data.get("source_name"), MAX_NAME_CHARS),
            source_path=str(data.get("source_path") or "")[:1000],
            provenance_path=str(data.get("provenance_path") or "")[:1000],
            plan_digest=str(data.get("plan_digest") or "")[:64],
            profile=clean_text(data.get("profile"), 60),
            camera=clean_text(data.get("camera"), 40),
            camera_mode=clean_text(data.get("camera_mode"), 40),
            root_motion=clean_text(data.get("root_motion"), 40),
            blender_version=clean_text(data.get("blender_version"), 40),
            script_version=clean_text(data.get("script_version"), 20),
            character_mode=clean_text(data.get("character_mode"), 60),
        )


@dataclass(frozen=True, slots=True)
class MotionAsset:
    """One catalog entry.  Technical facts come from the bounded FFprobe inspection; everything else is
    operator annotation.  ``sha256`` is the identity of the bytes."""

    asset_id: str
    display_name: str
    sha256: str
    locator: AssetLocator
    source_category: str = SOURCE_OTHER
    source_reference: str = ""
    source_url: str = ""
    tags: tuple[str, ...] = ()
    # technical facts (what the file reports)
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    frame_count: int | None = None
    thumbnail: str = ""
    # annotations
    subject_kind: str = UNKNOWN
    subject_count: int | None = None
    framing: str = UNKNOWN
    camera_movement: str = UNKNOWN
    viewpoint: str = UNKNOWN
    motion_intensity: str = UNKNOWN
    motion_direction: str = ""
    start_pose: str = ""
    end_pose: str = ""
    loop_suitability: str = UNKNOWN
    review_status: str = REVIEW_UNREVIEWED
    quality_notes: str = ""
    provenance_notes: str = ""
    usage_terms: str = ""
    imported_at: str = ""
    aliases: tuple[AssetAlias, ...] = ()
    origin: GeneratedOrigin | None = None
    #: Operator statement that the clip is good for motion driving, independent of its visual rating.
    good_for_motion: bool | None = None
    #: Set only for a clip converted from an animation file (the original's identity, not the clip's).
    derivation: DerivationRecord | None = None

    # ------------------------------------------------------------------ derived

    @property
    def is_generated(self) -> bool:
        return self.source_category == SOURCE_STABLENEW_GENERATED

    def with_changes(self, **changes: Any) -> MotionAsset:
        return replace(self, **changes)

    # ------------------------------------------------------------------ serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "display_name": self.display_name,
            "sha256": self.sha256,
            "locator": self.locator.to_dict(),
            "source_category": self.source_category,
            "source_reference": self.source_reference,
            "source_url": self.source_url,
            "tags": list(self.tags),
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "thumbnail": self.thumbnail,
            "subject_kind": self.subject_kind,
            "subject_count": self.subject_count,
            "framing": self.framing,
            "camera_movement": self.camera_movement,
            "viewpoint": self.viewpoint,
            "motion_intensity": self.motion_intensity,
            "motion_direction": self.motion_direction,
            "start_pose": self.start_pose,
            "end_pose": self.end_pose,
            "loop_suitability": self.loop_suitability,
            "review_status": self.review_status,
            "quality_notes": self.quality_notes,
            "provenance_notes": self.provenance_notes,
            "usage_terms": self.usage_terms,
            "imported_at": self.imported_at,
            "aliases": [alias.to_dict() for alias in self.aliases],
            "origin": self.origin.to_dict() if self.origin is not None else None,
            "good_for_motion": self.good_for_motion,
            "derivation": self.derivation.to_dict() if self.derivation is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Any) -> MotionAsset:
        if not isinstance(data, Mapping):
            raise AssetFormatError("asset must be an object")
        asset_id = str(data.get("asset_id") or "")
        if not _ASSET_ID.match(asset_id):
            raise AssetFormatError("asset_id is missing or malformed")
        sha = str(data.get("sha256") or "")
        if not is_sha256(sha):
            raise AssetFormatError("sha256 is missing or malformed")
        locator = AssetLocator.from_dict(data.get("locator"))
        name = clean_text(data.get("display_name"), MAX_NAME_CHARS)
        if not name:
            raise AssetFormatError("display_name is empty")
        raw_aliases = data.get("aliases")
        aliases: list[AssetAlias] = []
        if isinstance(raw_aliases, list):
            for item in raw_aliases[:MAX_ALIASES]:
                try:
                    aliases.append(AssetAlias.from_dict(item))
                except AssetFormatError:
                    continue
        raw_origin = data.get("origin")
        origin: GeneratedOrigin | None = None
        if raw_origin is not None:
            origin = GeneratedOrigin.from_dict(raw_origin)
        good = data.get("good_for_motion")
        raw_derivation = data.get("derivation")
        derivation: DerivationRecord | None = None
        if raw_derivation is not None:
            derivation = DerivationRecord.from_dict(raw_derivation)
        return cls(
            asset_id=asset_id,
            display_name=name,
            sha256=sha,
            locator=locator,
            source_category=choice(data.get("source_category"), SOURCE_CATEGORIES, SOURCE_OTHER),
            source_reference=clean_text(data.get("source_reference")),
            source_url=clean_text(data.get("source_url"), MAX_URL_CHARS),
            tags=normalize_tags(data.get("tags")),
            duration_seconds=_positive_float(data.get("duration_seconds")),
            width=_positive_int(data.get("width")),
            height=_positive_int(data.get("height")),
            fps=_positive_float(data.get("fps")),
            frame_count=_positive_int(data.get("frame_count")),
            thumbnail=clean_text(data.get("thumbnail"), 200),
            subject_kind=choice(data.get("subject_kind"), SUBJECT_KINDS),
            subject_count=_non_negative_int(data.get("subject_count")),
            framing=choice(data.get("framing"), FRAMINGS),
            camera_movement=choice(data.get("camera_movement"), CAMERA_MOVEMENTS),
            viewpoint=choice(data.get("viewpoint"), VIEWPOINTS),
            motion_intensity=choice(data.get("motion_intensity"), INTENSITIES),
            motion_direction=clean_text(data.get("motion_direction")),
            start_pose=clean_text(data.get("start_pose")),
            end_pose=clean_text(data.get("end_pose")),
            loop_suitability=choice(data.get("loop_suitability"), LOOP_SUITABILITIES),
            review_status=choice(data.get("review_status"), REVIEW_STATUSES, REVIEW_UNREVIEWED),
            quality_notes=clean_note(data.get("quality_notes")),
            provenance_notes=clean_note(data.get("provenance_notes")),
            usage_terms=clean_note(data.get("usage_terms")),
            imported_at=clean_text(data.get("imported_at"), 40),
            aliases=tuple(aliases),
            origin=origin,
            good_for_motion=good if isinstance(good, bool) else None,
            derivation=derivation,
        )


#: Operator-editable annotation fields and how each is normalized.  ``MotionLibraryStore.annotate`` accepts
#: exactly these names, so a caller can never rewrite identity (id, hash, locator, import time, origin).
ANNOTATION_FIELDS: dict[str, Any] = {
    "display_name": lambda v: clean_text(v, MAX_NAME_CHARS),
    "tags": normalize_tags,
    "source_category": lambda v: choice(v, SOURCE_CATEGORIES, SOURCE_OTHER),
    "source_reference": clean_text,
    "source_url": lambda v: clean_text(v, MAX_URL_CHARS),
    "subject_kind": lambda v: choice(v, SUBJECT_KINDS),
    "subject_count": _non_negative_int,
    "framing": lambda v: choice(v, FRAMINGS),
    "camera_movement": lambda v: choice(v, CAMERA_MOVEMENTS),
    "viewpoint": lambda v: choice(v, VIEWPOINTS),
    "motion_intensity": lambda v: choice(v, INTENSITIES),
    "motion_direction": clean_text,
    "start_pose": clean_text,
    "end_pose": clean_text,
    "loop_suitability": lambda v: choice(v, LOOP_SUITABILITIES),
    "review_status": lambda v: choice(v, REVIEW_STATUSES, REVIEW_UNREVIEWED),
    "quality_notes": clean_note,
    "provenance_notes": clean_note,
    "usage_terms": clean_note,
    "good_for_motion": lambda v: v if isinstance(v, bool) else None,
}


def new_asset_id(token_hex: str) -> str:
    """``mlib_`` + 32 hex characters from the caller's random token (injected so tests are deterministic)."""

    return f"{ASSET_ID_PREFIX}{token_hex[:32]}"


__all__ = [
    "ANNOTATION_FIELDS",
    "ASSET_ID_PREFIX",
    "CAMERA_MOVEMENTS",
    "FRAMINGS",
    "INTENSITIES",
    "LOCATOR_LINKED",
    "LOCATOR_MANAGED",
    "LOCATOR_MODES",
    "LOOP_LOOPABLE",
    "LOOP_ONE_SHOT",
    "LOOP_SUITABILITIES",
    "REVIEW_REJECTED",
    "REVIEW_REVIEWED",
    "REVIEW_STATUSES",
    "REVIEW_UNREVIEWED",
    "SOURCE_CATEGORIES",
    "SOURCE_CATEGORY_LABELS",
    "SOURCE_OTHER",
    "SOURCE_OWNER_RECORDED",
    "SOURCE_RENDERED_MOCAP",
    "SOURCE_STABLENEW_GENERATED",
    "SOURCE_STOCK_FOOTAGE",
    "SUBJECT_HUMAN",
    "SUBJECT_KINDS",
    "SUBJECT_NONHUMAN",
    "UNKNOWN",
    "VIEWPOINTS",
    "AssetAlias",
    "AssetFormatError",
    "AssetLocator",
    "GeneratedOrigin",
    "MotionAsset",
    "choice",
    "clean_note",
    "clean_text",
    "is_sha256",
    "new_asset_id",
    "normalize_tag",
    "normalize_tags",
    "utc_now_iso",
]

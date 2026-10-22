"""The typed, frozen plan of a multi-segment video job (PR-VID-SEQ-330-CORE).

One immutable NJR carries one ``SequencePlan`` under its video stage config's ``sequence_metadata``. The plan is
built and validated once, at admission (``src/video/sequence_admission.py``), and every value a segment needs is
concrete in it: the seed, the frame count, the backend workflow identity, the prompts and, for an authored anchor,
the image's hash. Nothing is chosen at run time, so a replay or a resume sees exactly what was queued.

The plan carries its own canonical digest (``plan_digest``). A plan whose content no longer matches its digest is not
loadable, so a resume, a replay and the runner can all prove they are executing what was admitted.

This module is pure data and arithmetic: no file access, queue, GUI or backend. ``SequencePlan.validate`` lists every
structural reason a plan cannot run; the backend-specific rules (legal frame counts, supported workflows) live with the
admission code that can see the workflow registry.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

SEQUENCE_PLAN_SCHEMA: Final = "stablenew.video_sequence_plan.v1"
#: The frozen execution policy a plan was admitted under (overlap semantics, anchor rules, assembly path). A runner
#: that does not know the version refuses the plan rather than executing it under different rules.
SEQUENCE_POLICY_VERSION: Final = "stablenew.video_sequence_policy.v1"

#: Segments one job may run, and the total generation budget (12 segments at the 81-frame Wan maximum).
MAX_SEQUENCE_SEGMENTS: Final = 12
MAX_SEQUENCE_TOTAL_FRAMES: Final = 972
MIN_SEQUENCE_SEGMENTS: Final = 1

STAGE_VIDEO_WORKFLOW: Final = "video_workflow"
STAGE_SVD_NATIVE: Final = "svd_native"
SEQUENCE_STAGES: Final = (STAGE_VIDEO_WORKFLOW, STAGE_SVD_NATIVE)
#: The backend each sequence stage runs on.
BACKEND_COMFY: Final = "comfy"
BACKEND_SVD_NATIVE: Final = "svd_native"
BACKEND_FOR_STAGE: Final = {
    STAGE_VIDEO_WORKFLOW: BACKEND_COMFY,
    STAGE_SVD_NATIVE: BACKEND_SVD_NATIVE,
}

#: Segment 0 starts from the job's own frozen source image.
ANCHOR_SOURCE: Final = "source"
#: A later segment starts from the exact last frame of the segment before it.
ANCHOR_CARRY: Final = "carry_last_frame"
#: A later segment starts from an authored image, hashed at admission and re-verified before dispatch.
ANCHOR_PROVIDED: Final = "provided"
ANCHOR_POLICIES: Final = (ANCHOR_SOURCE, ANCHOR_CARRY, ANCHOR_PROVIDED)

#: Leading frames dropped from a later segment when its intent does not say: a carried anchor's first generated frame
#: re-renders the anchor itself; an authored anchor is not part of the previous segment, so nothing repeats.
DEFAULT_OVERLAP_CARRY: Final = 1
DEFAULT_OVERLAP_PROVIDED: Final = 0

#: Anchors are images; a video file (or anything else) is refused rather than "decoded for you".
ANCHOR_IMAGE_SUFFIXES: Final = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})

#: Opt-in tone matching of later segments to the first frame of segment 0.
COLOR_ALGORITHM: Final = "per_channel_histogram_lut.v1"
COLOR_REFERENCE: Final = "segment0_first_frame"

MIN_FPS: Final = 1
MAX_FPS: Final = 120
MAX_SEED_WORKFLOW: Final = 2**31 - 1
MAX_SEED_SVD: Final = 2**32 - 1

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLIP_NAME = re.compile(r"[^A-Za-z0-9._-]+")

SEGMENT_KEYS: Final = frozenset(
    {
        "index",
        "seed",
        "frame_count",
        "workflow_id",
        "workflow_version",
        "prompt",
        "negative_prompt",
        "anchor_policy",
        "anchor_path",
        "anchor_sha256",
        "overlap_frames",
    }
)
ASSEMBLY_KEYS: Final = frozenset({"enabled", "clip_name", "quality", "codec"})
COLOR_KEYS: Final = frozenset({"enabled", "algorithm", "reference"})
SOURCE_KEYS: Final = frozenset({"path", "sha256"})
PLAN_KEYS: Final = frozenset(
    {
        "schema",
        "policy_version",
        "plan_digest",
        "sequence_id",
        "stage",
        "backend",
        "model_id",
        "experimental_opt_in",
        "fps",
        "segments",
        "assembly",
        "color_match",
        "source",
        "continuity",
        "plan_origin",
        "target_width",
        "target_height",
    }
)


class SequencePlanError(ValueError):
    """A plan (or the intent it is built from) is malformed; the message is written for the operator."""


def _unknown(kind: str, data: Mapping[str, Any], allowed: frozenset[str]) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise SequencePlanError(
            f"unknown {kind} field(s) {', '.join(repr(key) for key in extra)}; "
            f"only {', '.join(sorted(allowed))} may be set"
        )


def sanitize_clip_name(name: Any) -> str:
    cleaned = _CLIP_NAME.sub("_", str(name or "").strip()).strip("._-")
    return cleaned[:80] or "sequence"


def default_overlap(anchor_policy: str, position: int) -> int:
    """The overlap an intent that does not state one gets (segment 0 has nothing before it)."""

    if position == 0:
        return 0
    return DEFAULT_OVERLAP_CARRY if anchor_policy == ANCHOR_CARRY else DEFAULT_OVERLAP_PROVIDED


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_mapping(value: Any, *, kind: str) -> dict[str, Any] | None:
    if value is None or value == {}:
        return None
    if not isinstance(value, Mapping):
        raise SequencePlanError(f"the sequence {kind} must be a mapping")
    frozen: dict[str, Any] = json.loads(json.dumps(dict(value), sort_keys=True, default=str))
    return frozen


@dataclass(frozen=True, slots=True)
class SegmentSpec:
    """Everything one segment needs, concrete."""

    index: int
    seed: int
    frame_count: int
    anchor_policy: str
    workflow_id: str | None = None
    workflow_version: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    anchor_path: str | None = None
    anchor_sha256: str | None = None
    #: Leading frames dropped from this segment in the assembled movie (they re-render the anchor frame).
    overlap_frames: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "seed": self.seed,
            "frame_count": self.frame_count,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "anchor_policy": self.anchor_policy,
            "anchor_path": self.anchor_path,
            "anchor_sha256": self.anchor_sha256,
            "overlap_frames": self.overlap_frames,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SegmentSpec:
        if not isinstance(data, Mapping):
            raise SequencePlanError("a sequence segment must be a mapping")
        _unknown("segment", data, SEGMENT_KEYS)
        try:
            return cls(
                index=int(data["index"]),
                seed=int(data["seed"]),
                frame_count=int(data["frame_count"]),
                anchor_policy=str(data["anchor_policy"]),
                workflow_id=_optional_text(data.get("workflow_id")),
                workflow_version=_optional_text(data.get("workflow_version")),
                prompt=str(data.get("prompt") or ""),
                negative_prompt=str(data.get("negative_prompt") or ""),
                anchor_path=_optional_text(data.get("anchor_path")),
                anchor_sha256=_optional_text(data.get("anchor_sha256")),
                overlap_frames=int(data["overlap_frames"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SequencePlanError(f"a sequence segment is malformed: {exc}") from exc


@dataclass(frozen=True, slots=True)
class SequenceAssembly:
    """The one movie assembled from the segments' frames inside this job (an ASM-332 frame sequence).

    The sequence joins segments with exact frame trims (cuts); a crossfade is not offered, so a ``transition`` key is
    refused as an unknown field rather than silently ignored."""

    enabled: bool = True
    clip_name: str = "sequence"
    quality: str = "balanced"
    codec: str = "libx264"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "clip_name": self.clip_name,
            "quality": self.quality,
            "codec": self.codec,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SequenceAssembly:
        if not isinstance(data, Mapping):
            raise SequencePlanError("the sequence assembly must be a mapping")
        _unknown("assembly", data, ASSEMBLY_KEYS)
        return cls(
            enabled=bool(data.get("enabled", True)),
            clip_name=sanitize_clip_name(data.get("clip_name") or "sequence"),
            quality=str(data.get("quality") or "balanced"),
            codec=str(data.get("codec") or "libx264"),
        )


@dataclass(frozen=True, slots=True)
class SequenceColorMatch:
    """Opt-in tone matching of later segments' assembled frames to the first frame of segment 0 (off by default)."""

    enabled: bool = False
    algorithm: str = COLOR_ALGORITHM
    reference: str = COLOR_REFERENCE

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "algorithm": self.algorithm, "reference": self.reference}

    @classmethod
    def from_value(cls, value: Any) -> SequenceColorMatch:
        """From an intent (``True``/``False`` or ``{"enabled": ...}``) or a frozen plan's mapping."""

        if isinstance(value, SequenceColorMatch):
            return value
        if value is None:
            return cls()
        if isinstance(value, bool):
            return cls(enabled=value)
        if not isinstance(value, Mapping):
            raise SequencePlanError("color_match must be true, false or a mapping")
        _unknown("color_match", value, COLOR_KEYS)
        match = cls(
            enabled=bool(value.get("enabled", False)),
            algorithm=str(value.get("algorithm") or COLOR_ALGORITHM),
            reference=str(value.get("reference") or COLOR_REFERENCE),
        )
        if match.algorithm != COLOR_ALGORITHM or match.reference != COLOR_REFERENCE:
            raise SequencePlanError(
                f"colour matching supports {COLOR_ALGORITHM} against {COLOR_REFERENCE} only"
            )
        return match


@dataclass(frozen=True, slots=True)
class SequencePlan:
    sequence_id: str
    stage: str
    #: The frame rate every segment plays at, and the assembled movie is encoded at.
    fps: int
    segments: tuple[SegmentSpec, ...]
    assembly: SequenceAssembly = SequenceAssembly()
    color_match: SequenceColorMatch = SequenceColorMatch()
    #: ``comfy`` or ``svd_native``: the one backend every segment runs on.
    backend: str = BACKEND_COMFY
    #: The native SVD model every segment uses (``None`` for a Comfy workflow, whose identity is per segment).
    model_id: str | None = None
    #: The job's own, recorded opt-in for experimental workflows (never a global switch).
    experimental_opt_in: bool = False
    #: Segment 0's frozen input: ``{"path", "sha256"}`` of the exact image the first segment starts from.
    source: Mapping[str, Any] | None = None
    #: Provenance carried unchanged from the admitting surface (continuity pack link, planning origin).
    continuity: Mapping[str, Any] | None = None
    plan_origin: Mapping[str, Any] | None = None
    #: The frozen pixel size of segment 0 (for a workflow stage), against which an authored anchor's shape is checked.
    target_width: int | None = None
    target_height: int | None = None
    policy_version: str = SEQUENCE_POLICY_VERSION
    schema: str = SEQUENCE_PLAN_SCHEMA

    @property
    def total_frames(self) -> int:
        return sum(segment.frame_count for segment in self.segments)

    def validate(self) -> list[str]:
        """Every structural reason this plan cannot run (empty when it can)."""

        errors: list[str] = []
        if self.schema != SEQUENCE_PLAN_SCHEMA:
            errors.append(f"unsupported sequence plan schema {self.schema!r}")
        if self.policy_version != SEQUENCE_POLICY_VERSION:
            errors.append(f"unsupported sequence execution policy {self.policy_version!r}")
        if not self.sequence_id.strip():
            errors.append("sequence_id must not be empty")
        if self.stage not in SEQUENCE_STAGES:
            errors.append(f"stage must be one of {', '.join(SEQUENCE_STAGES)}, got {self.stage!r}")
        elif self.backend != BACKEND_FOR_STAGE[self.stage]:
            errors.append(
                f"a {self.stage} sequence runs on {BACKEND_FOR_STAGE[self.stage]}, not {self.backend!r}"
            )
        if not MIN_FPS <= self.fps <= MAX_FPS:
            errors.append(f"fps must be {MIN_FPS}-{MAX_FPS}, got {self.fps}")
        count = len(self.segments)
        if count < MIN_SEQUENCE_SEGMENTS:
            errors.append(f"a sequence needs at least {MIN_SEQUENCE_SEGMENTS} segment")
        if count > MAX_SEQUENCE_SEGMENTS:
            errors.append(
                f"{count} segments is more than the {MAX_SEQUENCE_SEGMENTS} one job may run"
            )
        if self.total_frames > MAX_SEQUENCE_TOTAL_FRAMES:
            errors.append(
                f"{self.total_frames} frames in total is more than the {MAX_SEQUENCE_TOTAL_FRAMES}-frame "
                "generation budget of one sequence job"
            )
        if self.assembly.enabled and not self.assembly.clip_name.strip():
            errors.append("the assembled clip name must not be empty")
        if self.source is not None:
            stray = set(self.source) - SOURCE_KEYS
            if (
                stray
                or not self.source.get("path")
                or not _SHA256.match(str(self.source.get("sha256") or ""))
            ):
                errors.append("the sequence source needs a path and a SHA-256")
        max_seed = MAX_SEED_SVD if self.stage == STAGE_SVD_NATIVE else MAX_SEED_WORKFLOW
        for position, segment in enumerate(self.segments):
            errors.extend(self._validate_segment(position, segment, max_seed))
        return errors

    def _validate_segment(self, position: int, segment: SegmentSpec, max_seed: int) -> list[str]:
        label = f"segment {position}"
        errors: list[str] = []
        if segment.index != position:
            errors.append(
                f"{label} is numbered {segment.index}; segments must be numbered 0..N-1 in order"
            )
        if not 0 <= segment.seed <= max_seed:
            errors.append(
                f"{label} seed must be a concrete integer in 0..{max_seed}, got {segment.seed}"
            )
        if segment.frame_count < 1:
            errors.append(f"{label} frame_count must be at least 1, got {segment.frame_count}")
        if segment.anchor_policy not in ANCHOR_POLICIES:
            errors.append(f"{label} has an unknown anchor policy {segment.anchor_policy!r}")
        elif position == 0 and segment.anchor_policy != ANCHOR_SOURCE:
            errors.append("segment 0 starts from the job's source image (anchor policy 'source')")
        elif position > 0 and segment.anchor_policy == ANCHOR_SOURCE:
            errors.append(
                f"{label} cannot use the 'source' anchor; use carry_last_frame or provided"
            )
        if segment.anchor_policy == ANCHOR_PROVIDED:
            if not segment.anchor_path:
                errors.append(f"{label} names a provided anchor with no image path")
            elif Path(segment.anchor_path).suffix.lower() not in ANCHOR_IMAGE_SUFFIXES:
                errors.append(
                    f"{label} anchor {Path(segment.anchor_path).name} is not an image "
                    f"({', '.join(sorted(ANCHOR_IMAGE_SUFFIXES))}); a video file is never an anchor"
                )
            if not segment.anchor_sha256 or not _SHA256.match(segment.anchor_sha256):
                errors.append(f"{label} provided anchor has no recorded SHA-256")
        elif segment.anchor_path or segment.anchor_sha256:
            errors.append(f"{label} carries an anchor path or hash its anchor policy does not use")
        if segment.overlap_frames < 0:
            errors.append(f"{label} overlap_frames must not be negative")
        elif position == 0 and segment.overlap_frames:
            errors.append("segment 0 has nothing before it to overlap")
        elif segment.overlap_frames >= segment.frame_count:
            errors.append(
                f"{label} overlap_frames ({segment.overlap_frames}) must be below its frame_count "
                f"({segment.frame_count}) so playable frames remain"
            )
        if self.stage == STAGE_SVD_NATIVE and (
            segment.workflow_id
            or segment.workflow_version
            or segment.prompt
            or segment.negative_prompt
        ):
            errors.append(f"{label}: native SVD takes no workflow, prompt or negative prompt")
        if self.stage == STAGE_VIDEO_WORKFLOW and not (
            segment.workflow_id and segment.workflow_version
        ):
            errors.append(f"{label} must name its workflow id and exact version")
        return errors

    def _content(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "policy_version": self.policy_version,
            "sequence_id": self.sequence_id,
            "stage": self.stage,
            "backend": self.backend,
            "model_id": self.model_id,
            "experimental_opt_in": self.experimental_opt_in,
            "fps": self.fps,
            "segments": [segment.to_dict() for segment in self.segments],
            "assembly": self.assembly.to_dict(),
            "color_match": self.color_match.to_dict(),
            "source": None if self.source is None else dict(self.source),
            "continuity": None if self.continuity is None else dict(self.continuity),
            "plan_origin": None if self.plan_origin is None else dict(self.plan_origin),
            "target_width": self.target_width,
            "target_height": self.target_height,
        }

    def plan_sha256(self) -> str:
        """Canonical digest of the whole plan: any change to any segment, anchor or setting changes it."""

        canonical = json.dumps(
            self._content(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._content(), "plan_digest": self.plan_sha256()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SequencePlan:
        """Rebuild a frozen plan; a malformed or altered one raises ``SequencePlanError`` (never a partial plan)."""

        if not isinstance(data, Mapping) or not data:
            raise SequencePlanError("the sequence plan is missing")
        _unknown("sequence plan", data, PLAN_KEYS)
        try:
            plan = cls(
                schema=str(data.get("schema") or ""),
                policy_version=str(data.get("policy_version") or ""),
                sequence_id=str(data["sequence_id"]),
                stage=str(data["stage"]),
                backend=str(data["backend"]),
                model_id=_optional_text(data.get("model_id")),
                experimental_opt_in=data.get("experimental_opt_in") is True,
                fps=int(data["fps"]),
                segments=tuple(SegmentSpec.from_dict(item) for item in data.get("segments") or ()),
                assembly=SequenceAssembly.from_dict(data.get("assembly") or {}),
                color_match=SequenceColorMatch.from_value(data.get("color_match")),
                source=_optional_mapping(data.get("source"), kind="source"),
                continuity=_optional_mapping(data.get("continuity"), kind="continuity"),
                plan_origin=_optional_mapping(data.get("plan_origin"), kind="plan origin"),
                target_width=None
                if data.get("target_width") is None
                else int(data["target_width"]),
                target_height=None
                if data.get("target_height") is None
                else int(data["target_height"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, SequencePlanError):
                raise
            raise SequencePlanError(f"the sequence plan is malformed: {exc}") from exc
        if str(data.get("plan_digest") or "") != plan.plan_sha256():
            raise SequencePlanError(
                "the sequence plan does not match its recorded digest; it was altered after it was frozen"
            )
        return plan


__all__ = [
    "ANCHOR_CARRY",
    "ANCHOR_IMAGE_SUFFIXES",
    "ANCHOR_POLICIES",
    "ANCHOR_PROVIDED",
    "ANCHOR_SOURCE",
    "BACKEND_COMFY",
    "BACKEND_FOR_STAGE",
    "BACKEND_SVD_NATIVE",
    "COLOR_ALGORITHM",
    "COLOR_REFERENCE",
    "DEFAULT_OVERLAP_CARRY",
    "DEFAULT_OVERLAP_PROVIDED",
    "MAX_SEED_SVD",
    "MAX_SEED_WORKFLOW",
    "MAX_SEQUENCE_SEGMENTS",
    "MAX_SEQUENCE_TOTAL_FRAMES",
    "SEQUENCE_PLAN_SCHEMA",
    "SEQUENCE_POLICY_VERSION",
    "SEQUENCE_STAGES",
    "STAGE_SVD_NATIVE",
    "STAGE_VIDEO_WORKFLOW",
    "SegmentSpec",
    "SequenceAssembly",
    "SequenceColorMatch",
    "SequencePlan",
    "SequencePlanError",
    "default_overlap",
    "sanitize_clip_name",
]

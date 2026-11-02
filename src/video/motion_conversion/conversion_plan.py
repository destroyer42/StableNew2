"""Deterministic, frozen conversion plan for one animation file (PR-VID-MOTION-354).

The plan is the whole contract with the Blender child: every choice that changes the pixels (profile, camera, root-motion
policy, window, rates, geometry, axis conventions, renderer) is a field, and the canonical JSON of those fields has a SHA-256
``digest``.  All time arithmetic is done here with exact fractions, so the child only evaluates the listed source frames.
Nothing is rounded to a frame silently: the plan states the source frame, as an exact rational, of every output frame.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from src.video.motion_conversion.rig_compat import BindingPlan
from src.video.workflow_frame_count import parse_frame_count

PLAN_SCHEMA = "stablenew.motion-conversion-plan.v1"
SCRIPT_VERSION = "1"

SOURCE_FBX_CHARACTER = "fbx_character"
SOURCE_FBX_SKELETON = "fbx_skeleton"
SOURCE_FBX_ON_CHARACTER = "fbx_on_reference_character"
SOURCE_BVH = "bvh_skeleton"
SOURCE_ROUTES = (SOURCE_FBX_CHARACTER, SOURCE_FBX_SKELETON, SOURCE_FBX_ON_CHARACTER, SOURCE_BVH)

PROFILE_CHARACTER = "character_reference"
PROFILE_SILHOUETTE = "high_contrast_silhouette"
PROFILE_SKELETON = "skeleton_reference"
PROFILES = (PROFILE_CHARACTER, PROFILE_SILHOUETTE, PROFILE_SKELETON)
PROFILE_LABELS = {
    PROFILE_CHARACTER: "Character reference",
    PROFILE_SILHOUETTE: "High-contrast silhouette",
    PROFILE_SKELETON: "Skeleton reference (not an OpenPose map)",
}
#: Profiles that need a mesh; the skeleton profile never does.
MESH_PROFILES = (PROFILE_CHARACTER, PROFILE_SILHOUETTE)

CAMERA_FRONT = "front"
CAMERA_SIDE = "side"
CAMERA_THREE_QUARTER = "three_quarter"
CAMERAS = (CAMERA_FRONT, CAMERA_SIDE, CAMERA_THREE_QUARTER)
CAMERA_STATIC = "static"
CAMERA_TRACKING = "tracking"
CAMERA_MODES = (CAMERA_STATIC, CAMERA_TRACKING)
ROOT_PRESERVE = "preserve"
ROOT_IN_PLACE = "in_place"
ROOT_MODES = (ROOT_PRESERVE, ROOT_IN_PLACE)

TARGET_FPS = 24
DEFAULT_WIDTH, DEFAULT_HEIGHT = 480, 832
MIN_EDGE, MAX_EDGE = 256, 1280
MAX_OUTPUT_FRAMES = 129
GENERIC_FRAME_POLICY = {"minimum": 5, "maximum": MAX_OUTPUT_FRAMES, "step": 4, "offset": 1}
RENDER_SAMPLES = 16
_SHA = re.compile(r"^[0-9a-f]{64}$")

#: Explicit import-time normalization.  Recorded verbatim in provenance; not inferred per file.
IMPORT_TRANSFORM = {
    "axis_forward": "-Z",
    "axis_up": "Y",
    "global_scale": 1.0,
    "framing": "fit_full_body",
    "margin_fraction": 0.12,
    "facing": "estimated_from_hip_bones_else_minus_y",
}
RENDERER = {"engine": "CYCLES", "device": "CPU", "samples": RENDER_SAMPLES, "denoise": False}


class ConversionPlanError(ValueError):
    """The requested conversion is refused; the message is operator-readable."""


@dataclass(frozen=True, slots=True)
class AnimationProbe:
    """What the Blender probe reported about the animation (all values come from the file, via Blender)."""

    fps: Fraction
    frame_first: Fraction
    frame_last: Fraction
    bone_names: tuple[str, ...] = ()
    has_mesh: bool = False
    blender_version: str = ""

    @property
    def duration_seconds(self) -> Fraction:
        return (self.frame_last - self.frame_first) / self.fps


@dataclass(frozen=True, slots=True)
class ConversionPlan:
    source_path: str
    source_sha256: str
    source_route: str
    profile: str
    camera: str
    camera_mode: str
    root_motion: str
    source_fps: Fraction
    frame_first: Fraction
    start_seconds: Fraction
    output_frames: int
    target_fps: int
    width: int
    height: int
    character_path: str = ""
    character_sha256: str = ""
    binding: BindingPlan | None = None
    rig_fingerprint: str = ""
    blender_version: str = ""
    workflow: tuple[str, str] = ("", "")
    transform: Mapping[str, Any] = field(default_factory=lambda: dict(IMPORT_TRANSFORM))
    renderer: Mapping[str, Any] = field(default_factory=lambda: dict(RENDERER))

    @property
    def source_type(self) -> str:
        return "bvh" if self.source_route == SOURCE_BVH else "fbx"

    @property
    def sample_frames(self) -> tuple[Fraction, ...]:
        """The exact source frame each output frame shows: first + (start + k / target_fps) * source_fps."""

        return tuple(
            self.frame_first + (self.start_seconds + Fraction(k, self.target_fps)) * self.source_fps
            for k in range(self.output_frames)
        )

    @property
    def retimed(self) -> bool:
        return self.source_fps != self.target_fps

    def to_record(self) -> dict[str, Any]:
        """Canonical, JSON-safe form; exact rationals are written as ``"n/d"`` strings."""

        return {
            "schema": PLAN_SCHEMA,
            "script_version": SCRIPT_VERSION,
            "source": {
                "path": self.source_path,
                "sha256": self.source_sha256,
                "type": self.source_type,
                "route": self.source_route,
            },
            "character": {"path": self.character_path, "sha256": self.character_sha256}
            if self.character_path
            else None,
            "binding": self.binding.to_record() if self.binding is not None else None,
            "binding_mapping": [list(pair) for pair in self.binding.mapping]
            if self.binding is not None
            else [],
            "rig_fingerprint": self.rig_fingerprint,
            "profile": self.profile,
            "camera": self.camera,
            "camera_mode": self.camera_mode,
            "root_motion": self.root_motion,
            "timing": {
                "source_fps": _rational(self.source_fps),
                "target_fps": self.target_fps,
                "frame_first": _rational(self.frame_first),
                "start_seconds": _rational(self.start_seconds),
                "output_frames": self.output_frames,
                "retimed_by_sampling": self.retimed,
                "sample_frames": [_rational(f) for f in self.sample_frames],
            },
            "geometry": {"width": self.width, "height": self.height},
            "transform": dict(self.transform),
            "renderer": dict(self.renderer),
            "blender_version": self.blender_version,
            "workflow": {"id": self.workflow[0], "version": self.workflow[1]},
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_record())).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _rational(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def parse_rational(text: Any) -> Fraction:
    try:
        return Fraction(str(text))
    except (ValueError, ZeroDivisionError) as exc:
        raise ConversionPlanError(f"'{text}' is not a valid number.") from exc


def _check(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise ConversionPlanError(f"Unknown {what} '{value}'. Choose one of: {', '.join(allowed)}.")
    return value


def resolve_output_frames(count: Any, workflow_spec: Any | None) -> int:
    """Validate a length against the consuming workflow's own rule, or the generic 4n+1 rule when none is chosen."""

    if workflow_spec is not None:
        try:
            return parse_frame_count(workflow_spec, count)
        except ValueError as exc:
            raise ConversionPlanError(str(exc)) from exc
    try:
        n = int(str(count).strip())
    except ValueError as exc:
        raise ConversionPlanError("Frame count must be a whole number of frames.") from exc
    policy = GENERIC_FRAME_POLICY
    if (
        not policy["minimum"] <= n <= policy["maximum"]
        or (n - policy["offset"]) % policy["step"] != 0
    ):
        raise ConversionPlanError(
            f"{n} frames is not offered: use a length from {policy['minimum']} to {policy['maximum']} "
            f"that is {policy['offset']} more than a multiple of {policy['step']}."
        )
    return n


def build_plan(
    *,
    source_path: str,
    source_sha256: str,
    source_route: str,
    probe: AnimationProbe,
    profile: str,
    camera: str = CAMERA_FRONT,
    camera_mode: str = CAMERA_STATIC,
    root_motion: str = ROOT_PRESERVE,
    start_seconds: Any = 0,
    output_frames: Any = "",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    character_path: str = "",
    character_sha256: str = "",
    binding: BindingPlan | None = None,
    rig_fingerprint: str = "",
    workflow_spec: Any | None = None,
) -> ConversionPlan:
    """Validate every choice and freeze the plan.  Refuses (never adjusts) an impossible request."""

    _check(source_route, SOURCE_ROUTES, "source route")
    _check(profile, PROFILES, "profile")
    _check(camera, CAMERAS, "camera")
    _check(camera_mode, CAMERA_MODES, "camera mode")
    _check(root_motion, ROOT_MODES, "root-motion policy")
    if not _SHA.match(source_sha256):
        raise ConversionPlanError("The source file's SHA-256 is required to freeze a plan.")
    if profile in MESH_PROFILES and source_route == SOURCE_FBX_SKELETON:
        raise ConversionPlanError(
            "This file has no character mesh. Choose the skeleton profile, or bind it to a compatible character."
        )
    if profile in MESH_PROFILES and source_route == SOURCE_BVH:
        raise ConversionPlanError("A BVH holds only a skeleton. Choose the skeleton profile.")
    if source_route == SOURCE_FBX_ON_CHARACTER:
        if not character_path or not _SHA.match(character_sha256):
            raise ConversionPlanError("A reference character file (with its SHA-256) is required.")
        if binding is None or not binding.compatible:
            reason = (
                binding.reason if binding is not None else "No bone compatibility check was made."
            )
            raise ConversionPlanError(f"Automated retargeting is refused: {reason}")
        if any(source != target for source, target in binding.mapping):
            raise ConversionPlanError(
                "Automated retargeting is refused: bone names differ between the animation and the character, "
                "and no bone is renamed automatically."
            )
    if (
        not (MIN_EDGE <= width <= MAX_EDGE and MIN_EDGE <= height <= MAX_EDGE)
        or width % 16
        or height % 16
    ):
        raise ConversionPlanError(
            f"Geometry {width}x{height} is not allowed: both edges must be multiples of 16 from {MIN_EDGE} to {MAX_EDGE}."
        )
    if probe.fps <= 0 or probe.frame_last < probe.frame_first:
        raise ConversionPlanError("The animation probe reported an unusable frame range.")
    frames = resolve_output_frames(output_frames, workflow_spec)
    start = parse_rational(start_seconds)
    if start < 0:
        raise ConversionPlanError("The start of the segment cannot be negative.")
    plan = ConversionPlan(
        source_path=str(source_path),
        source_sha256=source_sha256,
        source_route=source_route,
        profile=profile,
        camera=camera,
        camera_mode=camera_mode,
        root_motion=root_motion,
        source_fps=probe.fps,
        frame_first=probe.frame_first,
        start_seconds=start,
        output_frames=frames,
        target_fps=TARGET_FPS,
        width=int(width),
        height=int(height),
        character_path=str(character_path),
        character_sha256=character_sha256,
        binding=binding,
        rig_fingerprint=rig_fingerprint,
        blender_version=probe.blender_version,
        workflow=(
            str(getattr(workflow_spec, "workflow_id", "")),
            str(getattr(workflow_spec, "workflow_version", "")),
        ),
    )
    last = plan.sample_frames[-1]
    if last > probe.frame_last:
        available = float(probe.duration_seconds - start)
        raise ConversionPlanError(
            f"The segment is longer than the animation: {frames} frames at {TARGET_FPS} FPS need "
            f"{frames / TARGET_FPS:.2f} s from {float(start):.2f} s, but only {max(available, 0.0):.2f} s remain. "
            "Choose a shorter length or an earlier start; nothing is trimmed, padded or slowed."
        )
    return plan

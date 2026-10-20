"""Observational readiness of a motion source (PR-VID-196): geometry and timing advisories.

Pure and display-only.  Given what the declared preparation does to a source image
(``WorkflowSourceGeometry``), what a driving video reports about itself (``DrivingVideoFacts``) and
the workflow's declared output length, this module states measurable relationships: how much of
each picture the centred crop discards, how the two framings differ, and how many driving frames
the output would consume.  It does not detect subjects, estimate poses, predict generation quality
or change anything: an advisory never alters generation intent and never refuses a job.

Every threshold is a named module constant, explicitly advisory.  Timing relationships are only
stated when the selected workflow's graph and runtime revision were verified against the pinned
ComfyUI source (see ``driving_frame_consumption``); otherwise they are reported as unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.video.driving_frame_consumption import (
    VERIFIED_POSE_FRAME_CONSUMPTION_REVISIONS,
    DrivingFrameConsumption,
    driving_frame_consumption,
)
from src.video.driving_video_inspection import DrivingVideoFacts
from src.video.workflow_frame_count import (
    approximate_seconds,
    frame_count_policy,
    parse_frame_count,
)
from src.video.workflow_source_preparation import WorkflowSourceGeometry, cover_crop_box

# --- advisory thresholds (named, tested, advisory only) -----------------------------------------
SOURCE_CROP_DISCARD_ADVISORY_FRACTION = 0.20
DRIVING_CROP_DISCARD_ADVISORY_FRACTION = 0.20
ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION = 0.25
DRIVING_UPSCALE_ADVISORY_FACTOR = 1.5
FPS_DIFFERENCE_ADVISORY_FRACTION = 0.10

ADVISORY_ONLY = True  # nothing in this module may block, rewrite or refuse a job
_THRESHOLD_TOLERANCE = 1e-9  # a value that equals its threshold must not miss it by float noise


def _reaches(value: float, threshold: float) -> bool:
    return value + _THRESHOLD_TOLERANCE >= threshold


# --- output timing ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutputTiming:
    """The requested generation length under the workflow's own frame-count policy."""

    frame_count: int
    fps: int
    seconds: float
    from_default: bool


def requested_output_timing(spec: Any, frame_count_value: Any) -> OutputTiming | None:
    """Frames, declared fps and duration for the operator's choice (blank means the default).

    None when the workflow declares no frame-count policy or the value is not a legal length."""

    policy = frame_count_policy(spec)
    if policy is None:
        return None
    try:
        count = parse_frame_count(spec, frame_count_value)
    except ValueError:
        return None
    blank = not str(frame_count_value if frame_count_value is not None else "").strip()
    return OutputTiming(
        frame_count=count,
        fps=policy["fps"],
        seconds=approximate_seconds(count, policy["fps"]),
        from_default=blank,
    )


# --- assessment ---------------------------------------------------------------------------------

BASIS_MEASURED = "measured"  # computed from the source image's own pixels
BASIS_METADATA = "metadata"  # reported by a file's metadata
BASIS_DERIVED = "derived"  # arithmetic on the above and on declared workflow policy


@dataclass(frozen=True, slots=True)
class GeometryAdvisory:
    """One observation.  ``threshold_*`` is None for a plain statement with no cut-off."""

    code: str
    message: str
    basis: str
    observed: float | None = None
    threshold_name: str | None = None
    threshold: float | None = None


@dataclass(frozen=True, slots=True)
class SourceFraming:
    stored_width: int
    stored_height: int
    width: int
    height: int
    exif_transposed: bool
    orientation: str  # of the image pixels
    policy_orientation: str  # what the declared preparation decided
    prepared_width: int
    prepared_height: int
    crop_left: float
    crop_top: float
    crop_right: float
    crop_bottom: float
    discarded_fraction: float


@dataclass(frozen=True, slots=True)
class DrivingFraming:
    width: int  # as displayed (rotation applied)
    height: int
    orientation: str
    aspect_ratio: float
    # Centre crop of the clip to the prepared frame size, when a source geometry is known.
    discarded_fraction: float | None
    upscale_factor: float | None
    aspect_difference_fraction: float | None


@dataclass(frozen=True, slots=True)
class TimingRelationship:
    """What can be said about driving frames versus generated frames.

    ``consumption_known`` is False unless the workflow's runtime semantics were verified; every
    derived field is then None rather than guessed."""

    output_frames: int | None
    output_fps: int | None
    output_seconds: float | None
    driving_fps: float | None
    driving_frames: int | None
    driving_frames_basis: str  # reported | estimated | unknown
    driving_seconds: float | None
    consumption_known: bool
    consumption_note: str
    driving_frames_used: int | None
    driving_frames_unused: int | None
    last_frame_held_for: int | None
    playback_speed_vs_original: float | None


@dataclass(frozen=True, slots=True)
class MotionSourceAssessment:
    advisory_only: bool
    source: SourceFraming | None
    driving: DrivingFraming | None
    timing: TimingRelationship | None
    advisories: tuple[GeometryAdvisory, ...]


def _source_framing(geometry: WorkflowSourceGeometry) -> SourceFraming:
    left, top, right, bottom = geometry.crop_box
    return SourceFraming(
        stored_width=geometry.stored_dimensions["width"],
        stored_height=geometry.stored_dimensions["height"],
        width=geometry.source_dimensions["width"],
        height=geometry.source_dimensions["height"],
        exif_transposed=geometry.exif_transposed,
        orientation=geometry.source_orientation,
        policy_orientation=geometry.orientation,
        prepared_width=geometry.prepared_dimensions["width"],
        prepared_height=geometry.prepared_dimensions["height"],
        crop_left=left,
        crop_top=top,
        crop_right=right,
        crop_bottom=bottom,
        discarded_fraction=geometry.discarded_fraction,
    )


def _driving_framing(
    facts: DrivingVideoFacts, geometry: WorkflowSourceGeometry | None
) -> DrivingFraming:
    discarded: float | None = None
    upscale: float | None = None
    difference: float | None = None
    if geometry is not None:
        target_w = geometry.target_dimensions["width"]
        target_h = geometry.target_dimensions["height"]
        # The qualified graph centre-crops the clip to the prepared frame size; the same cover
        # arithmetic the source uses gives the approximate share of the clip that is discarded.
        left, top, right, bottom = cover_crop_box(
            (facts.display_width, facts.display_height), (target_w, target_h)
        )
        kept = ((right - left) * (bottom - top)) / (facts.display_width * facts.display_height)
        discarded = max(0.0, 1.0 - min(1.0, kept))
        upscale = max(target_w / facts.display_width, target_h / facts.display_height)
        target_ratio = target_w / target_h
        difference = abs(target_ratio - facts.aspect_ratio) / max(target_ratio, facts.aspect_ratio)
    return DrivingFraming(
        width=facts.display_width,
        height=facts.display_height,
        orientation=facts.orientation,
        aspect_ratio=facts.aspect_ratio,
        discarded_fraction=discarded,
        upscale_factor=upscale,
        aspect_difference_fraction=difference,
    )


def _timing(
    facts: DrivingVideoFacts | None,
    output: OutputTiming | None,
    consumption: DrivingFrameConsumption | None,
) -> TimingRelationship | None:
    if facts is None and output is None:
        return None
    known = bool(consumption and consumption.verified and facts is not None)
    frames = facts.frame_count if facts is not None else None
    fps = facts.reported_fps if facts is not None else None
    used = unused = held = None
    speed: float | None = None
    if known and output is not None:
        if frames is not None:
            used = min(output.frame_count, frames)
            unused = max(0, frames - output.frame_count)
            held = max(0, output.frame_count - frames)
        if fps is not None:
            speed = output.fps / fps
    if consumption is None:
        note = "No driving video is used by this workflow."
    elif consumption.verified:
        note = consumption.rule
    else:
        note = (
            f"{consumption.reason} Which driving frames are used, and any frame-rate "
            "conversion, are therefore unknown."
        )
    return TimingRelationship(
        output_frames=output.frame_count if output else None,
        output_fps=output.fps if output else None,
        output_seconds=output.seconds if output else None,
        driving_fps=fps,
        driving_frames=frames,
        driving_frames_basis=facts.frame_count_basis if facts is not None else "unknown",
        driving_seconds=facts.duration_seconds if facts is not None else None,
        consumption_known=known,
        consumption_note=note,
        driving_frames_used=used,
        driving_frames_unused=unused,
        last_frame_held_for=held,
        playback_speed_vs_original=speed,
    )


def _percent(fraction: float) -> str:
    return f"{fraction * 100:.0f}%"


def assess_motion_source(
    *,
    geometry: WorkflowSourceGeometry | None,
    driving: DrivingVideoFacts | None,
    output: OutputTiming | None,
    consumption: DrivingFrameConsumption | None = None,
) -> MotionSourceAssessment:
    """Combine what is known into measurable observations.  Any input may be absent."""

    advisories: list[GeometryAdvisory] = []
    source = _source_framing(geometry) if geometry is not None else None
    framing = _driving_framing(driving, geometry) if driving is not None else None

    if source is not None:
        if source.exif_transposed:
            advisories.append(
                GeometryAdvisory(
                    code="source_exif_rotated",
                    message=(
                        f"The image is stored {source.stored_width}x{source.stored_height} but its "
                        f"EXIF orientation displays it {source.width}x{source.height}; preparation "
                        "uses the displayed orientation."
                    ),
                    basis=BASIS_MEASURED,
                )
            )
        if _reaches(source.discarded_fraction, SOURCE_CROP_DISCARD_ADVISORY_FRACTION):
            advisories.append(
                GeometryAdvisory(
                    code="source_crop_discards_image",
                    message=(
                        f"Preparing {source.width}x{source.height} for "
                        f"{source.prepared_width}x{source.prepared_height} discards about "
                        f"{_percent(source.discarded_fraction)} of the image (centred crop)."
                    ),
                    basis=BASIS_MEASURED,
                    observed=source.discarded_fraction,
                    threshold_name="SOURCE_CROP_DISCARD_ADVISORY_FRACTION",
                    threshold=SOURCE_CROP_DISCARD_ADVISORY_FRACTION,
                )
            )

    if framing is not None and source is not None:
        if framing.orientation != "square" and source.policy_orientation != framing.orientation:
            advisories.append(
                GeometryAdvisory(
                    code="orientation_mismatch",
                    message=(
                        f"The driving video is {framing.orientation} but the prepared source frame "
                        f"is {source.policy_orientation}; the clip is centre-cropped to that frame."
                    ),
                    basis=BASIS_DERIVED,
                )
            )
        if framing.aspect_difference_fraction is not None and _reaches(
            framing.aspect_difference_fraction, ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION
        ):
            advisories.append(
                GeometryAdvisory(
                    code="aspect_ratio_differs",
                    message=(
                        f"The driving video's aspect ratio ({framing.aspect_ratio:.2f}) differs from "
                        f"the prepared frame's by {_percent(framing.aspect_difference_fraction)}."
                    ),
                    basis=BASIS_DERIVED,
                    observed=framing.aspect_difference_fraction,
                    threshold_name="ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION",
                    threshold=ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION,
                )
            )
        if framing.discarded_fraction is not None and _reaches(
            framing.discarded_fraction, DRIVING_CROP_DISCARD_ADVISORY_FRACTION
        ):
            advisories.append(
                GeometryAdvisory(
                    code="driving_crop_discards_video",
                    message=(
                        "Centre-cropping the driving video to the prepared frame discards about "
                        f"{_percent(framing.discarded_fraction)} of each frame (approximate); "
                        "motion near the edges may fall outside the frame."
                    ),
                    basis=BASIS_DERIVED,
                    observed=framing.discarded_fraction,
                    threshold_name="DRIVING_CROP_DISCARD_ADVISORY_FRACTION",
                    threshold=DRIVING_CROP_DISCARD_ADVISORY_FRACTION,
                )
            )
        if framing.upscale_factor is not None and _reaches(
            framing.upscale_factor, DRIVING_UPSCALE_ADVISORY_FACTOR
        ):
            advisories.append(
                GeometryAdvisory(
                    code="driving_video_upscaled",
                    message=(
                        f"The driving video is {framing.width}x{framing.height}; it is enlarged "
                        f"about {framing.upscale_factor:.1f}x to fill the prepared frame."
                    ),
                    basis=BASIS_DERIVED,
                    observed=framing.upscale_factor,
                    threshold_name="DRIVING_UPSCALE_ADVISORY_FACTOR",
                    threshold=DRIVING_UPSCALE_ADVISORY_FACTOR,
                )
            )

    timing = _timing(driving, output, consumption)
    if timing is not None and driving is not None and output is not None:
        if timing.driving_fps is not None and _reaches(
            abs(timing.driving_fps - output.fps) / output.fps,
            FPS_DIFFERENCE_ADVISORY_FRACTION,
        ):
            if timing.consumption_known and timing.playback_speed_vs_original is not None:
                message = (
                    f"The driving video reports {timing.driving_fps:g} fps and the output is "
                    f"{output.fps} fps. Driving frames are used one for one without conversion, "
                    "so the clip's motion is laid out over the output at "
                    f"{timing.playback_speed_vs_original:.2f}x its original speed (arithmetic on "
                    "the reported rate; the generated motion is not measured)."
                )
            else:
                message = (
                    f"The driving video reports {timing.driving_fps:g} fps and the output is "
                    f"{output.fps} fps; how this workflow maps them is unknown."
                )
            advisories.append(
                GeometryAdvisory(
                    code="driving_fps_differs",
                    message=message,
                    basis=BASIS_DERIVED if timing.consumption_known else BASIS_METADATA,
                    observed=timing.driving_fps,
                    threshold_name="FPS_DIFFERENCE_ADVISORY_FRACTION",
                    threshold=FPS_DIFFERENCE_ADVISORY_FRACTION,
                )
            )
        if timing.consumption_known and timing.last_frame_held_for:
            about = "about " if timing.driving_frames_basis != "reported" else ""
            advisories.append(
                GeometryAdvisory(
                    code="driving_shorter_than_output",
                    message=(
                        f"The driving video has {about}{timing.driving_frames} frames but "
                        f"{output.frame_count} are generated; its last frame is held for the "
                        f"remaining {about}{timing.last_frame_held_for}."
                    ),
                    basis=BASIS_DERIVED,
                    observed=float(timing.driving_frames or 0),
                )
            )
        elif timing.consumption_known and timing.driving_frames_unused:
            about = "about " if timing.driving_frames_basis != "reported" else ""
            advisories.append(
                GeometryAdvisory(
                    code="driving_longer_than_output",
                    message=(
                        f"Only the first {output.frame_count} of {about}{timing.driving_frames} "
                        "driving frames are used."
                    ),
                    basis=BASIS_DERIVED,
                    observed=float(timing.driving_frames or 0),
                )
            )
    if driving is not None and driving.fps_is_variable_suspected:
        advisories.append(
            GeometryAdvisory(
                code="variable_frame_rate_suspected",
                message=(
                    "The file's average and base frame rates differ, so it may be variable "
                    "frame rate; the reported fps is an average."
                ),
                basis=BASIS_METADATA,
            )
        )
    return MotionSourceAssessment(
        advisory_only=ADVISORY_ONLY,
        source=source,
        driving=framing,
        timing=timing,
        advisories=tuple(advisories),
    )


__all__ = [
    "ADVISORY_ONLY",
    "ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION",
    "BASIS_DERIVED",
    "BASIS_MEASURED",
    "BASIS_METADATA",
    "DRIVING_CROP_DISCARD_ADVISORY_FRACTION",
    "DRIVING_UPSCALE_ADVISORY_FACTOR",
    "FPS_DIFFERENCE_ADVISORY_FRACTION",
    "SOURCE_CROP_DISCARD_ADVISORY_FRACTION",
    "VERIFIED_POSE_FRAME_CONSUMPTION_REVISIONS",
    "DrivingFraming",
    "DrivingFrameConsumption",
    "GeometryAdvisory",
    "MotionSourceAssessment",
    "OutputTiming",
    "SourceFraming",
    "TimingRelationship",
    "assess_motion_source",
    "driving_frame_consumption",
    "requested_output_timing",
]

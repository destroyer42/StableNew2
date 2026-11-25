"""Source / driving-motion compatibility advisories (PR-VID-MOTION-420).

Pure and display-only.  It compares what an operator reports about a source subject with what the Motion
Library (or the operator) reports about the driving motion and, where the operator marked subject bounds,
the geometry those bounds imply.  There is **no** score and **no** probability of success: every advisory
names its basis and, where it has a cut-off, the named threshold and the observed value, so an operator can see
why it fired and disagree with it.

Four kinds of statement are kept apart and never blended:

* ``measured``     facts read from the media (sizes, rate, frame counts, the selected window);
* ``annotations``  what the operator or the Motion Library *reported* (never machine-verified);
* ``derived``      arithmetic on the two (scale ratios, offsets, where bounds land under an alignment);
* ``historical``   evidence statements supplied by the caller (for example the workflow guidance);
* ``unknown``      conditions that were not provided, so the corresponding check was not made.

An advisory never blocks, rewrites or refuses a job (``ADVISORY_ONLY``); only an alignment that cannot be
resolved deterministically is refused, and that happens in ``motion_alignment``.  Nothing here detects a
subject, estimates pose or reads a file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.video.motion_alignment import FrameSize, Rect, ResolvedAlignment, baseline_scale

ADVISORY_ONLY = True  # nothing in this module may block, rewrite or refuse a job
_TOLERANCE = 1e-9

# --- named thresholds -----------------------------------------------------------------------------------
#: Driver subject height over source subject height (or the inverse) beyond this is a size mismatch.
SCALE_RATIO_ADVISORY = 1.5
#: Subject centres further apart than this fraction of the target frame (per axis) differ in position.
POSITION_OFFSET_ADVISORY_FRACTION = 0.15
#: Entered subject bounds closer than this fraction of the frame to its edge may clip.
CLIPPING_MARGIN_FRACTION = 0.02
#: Less than this share of the driving frame left in view after an alignment may lose relevant movement.
DRIVER_VISIBLE_FRACTION_ADVISORY = 0.8
#: More than this share of the target frame filled with the constant border colour adds visible borders.
FILL_FRACTION_ADVISORY = 0.25
#: A source subject wider than this share of the frame leaves little room for a large root displacement.
SOURCE_OCCUPANCY_ADVISORY_FRACTION = 0.6

SEVERITY_NOTE = "note"
SEVERITY_CAUTION = "caution"
BASIS_MEASURED = "measured"
BASIS_OPERATOR = "operator"
BASIS_DERIVED = "derived"
BASIS_HISTORICAL = "historical"
BASIS_UNKNOWN = "unknown"

UNKNOWN = "unknown"
_MOVING_CAMERAS = frozenset({"pan", "tilt", "zoom", "tracking", "handheld", "orbit"})
_ADJACENT_VIEWS = frozenset(
    {
        frozenset({"front", "three_quarter"}),
        frozenset({"three_quarter", "side"}),
        frozenset({"side", "back"}),
    }
)
ROOT_NONE, ROOT_SMALL, ROOT_LARGE = "none", "small", "large"
ROOT_DISPLACEMENTS = (ROOT_NONE, ROOT_SMALL, ROOT_LARGE, UNKNOWN)


@dataclass(frozen=True, slots=True)
class SubjectObservations:
    """What is *reported* about one subject (a source image's or a driving clip's).  Nothing is verified."""

    kind: str = UNKNOWN  # human | nonhuman | unknown
    count: int | None = None
    framing: str = UNKNOWN  # full_body | upper_body | partial | unknown
    viewpoint: str = UNKNOWN  # front | three_quarter | side | back | top_down | low_angle | unknown
    start_pose: str = ""
    camera_movement: str = UNKNOWN
    motion_direction: str = ""
    root_displacement: str = UNKNOWN  # driver only: none | small | large | unknown
    visible_regions: tuple[str, ...] = ()
    #: The subject's bounds: target-frame pixels for the source image, driver display pixels (initial
    #: selected frame) for the driving clip.  Entered by the operator.
    bounds: Rect | None = None


@dataclass(frozen=True, slots=True)
class MediaFacts:
    """Measured or reported media facts the caller already holds (no second inspection happens here)."""

    target: FrameSize
    driver: FrameSize
    source_original: tuple[int, int] | None = None
    driver_rate: float | None = None
    driver_frame_count: int | None = None
    window_start: int = 0
    window_end: int | None = None
    output_frames: int | None = None
    output_fps: int | None = None
    held_frames: int = 0


@dataclass(frozen=True, slots=True)
class CompatibilityAdvisory:
    code: str
    severity: str
    basis: str
    message: str
    threshold: str = ""
    observed: str = ""


@dataclass(frozen=True, slots=True)
class CompatibilityAssessment:
    measured: tuple[str, ...] = ()
    annotations: tuple[str, ...] = ()
    derived: tuple[str, ...] = ()
    historical: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    advisories: tuple[CompatibilityAdvisory, ...] = ()
    #: Always False: advisories never block an otherwise valid generation request.
    blocking: bool = field(default=False, init=False)

    @property
    def cautions(self) -> tuple[CompatibilityAdvisory, ...]:
        return tuple(a for a in self.advisories if a.severity == SEVERITY_CAUTION)


def _reaches(value: float, threshold: float) -> bool:
    return value >= threshold - _TOLERANCE


def _label(value: str) -> str:
    return value.replace("_", " ")


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _bounds_in_target(
    bounds: Rect,
    driver: FrameSize,
    target: FrameSize,
    scale: float = 1.0,
    offset: tuple[float, float] = (0.0, 0.0),
) -> Rect:
    """Driver-pixel bounds under the baseline cover placement (plus an extra scale about the centre)."""

    cover = baseline_scale(driver, target)
    left0 = (target.width - driver.width * cover) / 2.0
    top0 = (target.height - driver.height * cover) / 2.0
    cx, cy = target.width / 2.0, target.height / 2.0

    def place(x: float, y: float) -> tuple[float, float]:
        bx, by = left0 + x * cover, top0 + y * cover
        return (cx + scale * (bx - cx) + offset[0], cy + scale * (by - cy) + offset[1])

    a, b = place(bounds.left, bounds.top), place(bounds.right, bounds.bottom)
    return Rect(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def assess_compatibility(
    *,
    source: SubjectObservations,
    driver: SubjectObservations,
    media: MediaFacts,
    alignment: ResolvedAlignment | None = None,
    historical: Sequence[str] = (),
    readiness_notes: Sequence[str] = (),
) -> CompatibilityAssessment:
    """Compatibility statements for one source / driver pairing, each with its basis (see the module doc)."""

    measured: list[str] = [
        f"Target frame {media.target.width}x{media.target.height} (the prepared source image's size).",
        f"Driving frame {media.driver.width}x{media.driver.height} (display orientation).",
    ]
    if media.driver_rate:
        measured.append(f"Driving clip rate {media.driver_rate:g} fps.")
    if media.driver_frame_count is not None:
        measured.append(f"Driving clip frames {media.driver_frame_count}.")
    end = (
        "the end of the clip"
        if media.window_end is None
        else f"frame {media.window_end} (exclusive)"
    )
    measured.append(f"Selected window starts at frame {media.window_start} and runs to {end}.")
    if media.output_frames is not None and media.output_fps is not None:
        measured.append(
            f"The workflow consumes {media.output_frames} frames at {media.output_fps} fps"
            + (
                f"; the last {media.held_frames} repeat the final frame."
                if media.held_frames
                else "."
            )
        )
    if media.source_original is not None:
        measured.append(
            f"Source image {media.source_original[0]}x{media.source_original[1]} before preparation."
        )
    measured.extend(readiness_notes)

    annotations: list[str] = []
    for name, subject in (("Source", source), ("Driving motion", driver)):
        parts = [
            f"{label} {_label(value)}"
            for label, value in (
                ("kind", subject.kind),
                ("framing", subject.framing),
                ("viewpoint", subject.viewpoint),
                ("camera", subject.camera_movement),
            )
            if value != UNKNOWN
        ]
        if subject.count is not None:
            parts.append(f"{subject.count} subject(s)")
        if subject.start_pose:
            parts.append(f"start pose '{subject.start_pose}'")
        if subject.motion_direction:
            parts.append(f"direction '{subject.motion_direction}'")
        if subject.root_displacement != UNKNOWN:
            parts.append(f"root displacement {subject.root_displacement}")
        annotations.append(
            f"{name} (reported, not verified): "
            + (", ".join(parts) if parts else "nothing reported.")
        )

    advisories: list[CompatibilityAdvisory] = []
    derived: list[str] = []
    unknown: list[str] = []

    def add(
        code: str, severity: str, basis: str, message: str, threshold: str = "", observed: str = ""
    ) -> None:
        advisories.append(
            CompatibilityAdvisory(code, severity, basis, message, threshold, observed)
        )

    if source.kind != UNKNOWN and driver.kind != UNKNOWN and source.kind != driver.kind:
        add(
            "subject_kind",
            SEVERITY_CAUTION,
            BASIS_OPERATOR,
            f"The driving motion is reported as {_label(driver.kind)} and the source as "
            f"{_label(source.kind)}; their bodies may not map onto each other.",
        )
    if driver.framing == "full_body" and source.framing in ("upper_body", "partial"):
        add(
            "framing_full_body_into_closeup",
            SEVERITY_CAUTION,
            BASIS_OPERATOR,
            "Full-body motion is paired with a close-up source: limb movement the source image does not "
            "show has nowhere to go, and a geometric transform cannot add it.",
        )
    elif source.framing == "full_body" and driver.framing in ("upper_body", "partial"):
        add(
            "framing_closeup_into_full_body",
            SEVERITY_NOTE,
            BASIS_OPERATOR,
            "The driving motion shows only part of the body; the rest of the source subject is not "
            "constrained by it.",
        )
    elif UNKNOWN in (source.framing, driver.framing):
        unknown.append(
            "Framing was not reported for both, so full-body versus close-up was not compared."
        )
    if (
        source.viewpoint != UNKNOWN
        and driver.viewpoint != UNKNOWN
        and source.viewpoint != driver.viewpoint
    ):
        adjacent = frozenset({source.viewpoint, driver.viewpoint}) in _ADJACENT_VIEWS
        add(
            "viewpoint_mismatch",
            SEVERITY_NOTE if adjacent else SEVERITY_CAUTION,
            BASIS_OPERATOR,
            f"Viewpoints differ (source {_label(source.viewpoint)}, driving {_label(driver.viewpoint)})"
            + (
                "; they are neighbouring views."
                if adjacent
                else "; a geometric transform cannot turn a subject."
            ),
        )
    elif UNKNOWN in (source.viewpoint, driver.viewpoint):
        unknown.append("Viewpoint was not reported for both, so it was not compared.")
    if (
        _norm(source.start_pose)
        and _norm(driver.start_pose)
        and _norm(source.start_pose) != _norm(driver.start_pose)
    ):
        add(
            "start_pose_mismatch",
            SEVERITY_CAUTION,
            BASIS_OPERATOR,
            f"Starting poses differ (source '{source.start_pose}', driving '{driver.start_pose}'). Spatial "
            "alignment cannot correct an anatomical pose difference.",
        )
    elif not _norm(source.start_pose) or not _norm(driver.start_pose):
        unknown.append("Starting poses were not both reported, so they were not compared.")
    for name, subject in (("source", source), ("driving motion", driver)):
        if subject.count is not None and subject.count > 1:
            add(
                "multiple_subjects",
                SEVERITY_CAUTION,
                BASIS_OPERATOR,
                f"The {name} is reported to contain {subject.count} subjects; which one moves or keeps its "
                "identity is ambiguous.",
            )
    if driver.camera_movement in _MOVING_CAMERAS:
        add(
            "camera_movement",
            SEVERITY_CAUTION,
            BASIS_OPERATOR,
            f"The driving clip has {_label(driver.camera_movement)} camera movement. The alignment is one "
            "constant transform, so that movement stays in the driving frames as apparent subject motion.",
        )
    elif driver.camera_movement == UNKNOWN:
        unknown.append("The driving clip's camera movement was not reported.")

    source_box = source.bounds
    driver_box = driver.bounds
    cover = baseline_scale(media.driver, media.target)
    if source_box is not None and driver_box is not None:
        driver_before = _bounds_in_target(driver_box, media.driver, media.target)
        ratio = driver_before.height / source_box.height
        derived.append(
            f"Driving subject is {ratio:.2f}x the source subject's height in the target frame before alignment."
        )
        if _reaches(max(ratio, 1.0 / ratio), SCALE_RATIO_ADVISORY):
            add(
                "scale_mismatch",
                SEVERITY_CAUTION,
                BASIS_DERIVED,
                f"The subjects differ in size by {max(ratio, 1.0 / ratio):.2f}x in the target frame.",
                f"SCALE_RATIO_ADVISORY={SCALE_RATIO_ADVISORY:g}",
                f"{ratio:.2f}",
            )
        dx = abs(driver_before.center[0] - source_box.center[0]) / media.target.width
        dy = abs(driver_before.center[1] - source_box.center[1]) / media.target.height
        derived.append(
            f"Subject centres differ by {dx:.0%} of the frame width and {dy:.0%} of its height before alignment."
        )
        if _reaches(max(dx, dy), POSITION_OFFSET_ADVISORY_FRACTION):
            add(
                "position_mismatch",
                SEVERITY_CAUTION,
                BASIS_DERIVED,
                "The subjects sit in different parts of the frame.",
                f"POSITION_OFFSET_ADVISORY_FRACTION={POSITION_OFFSET_ADVISORY_FRACTION:g}",
                f"{max(dx, dy):.2f}",
            )
        if alignment is not None:
            after = Rect(
                *(
                    min(a, b)
                    for a, b in zip(
                        alignment.to_target((driver_box.left, driver_box.top)),
                        alignment.to_target((driver_box.right, driver_box.bottom)),
                        strict=True,
                    )
                ),
                *(
                    max(a, b)
                    for a, b in zip(
                        alignment.to_target((driver_box.left, driver_box.top)),
                        alignment.to_target((driver_box.right, driver_box.bottom)),
                        strict=True,
                    )
                ),
            )
            derived.append(
                f"After the current alignment the driving subject is {after.height / source_box.height:.2f}x the "
                f"source subject's height, centres {abs(after.center[0] - source_box.center[0]):.0f} px apart "
                f"horizontally and {abs(after.center[1] - source_box.center[1]):.0f} px vertically."
            )
    else:
        unknown.append(
            "Subject bounds were not entered for both, so subject scale and position were not compared."
        )

    if alignment is not None:
        if alignment.driver_visible_fraction < DRIVER_VISIBLE_FRACTION_ADVISORY - _TOLERANCE:
            add(
                "driver_cropped",
                SEVERITY_CAUTION,
                BASIS_DERIVED,
                f"Only {alignment.driver_visible_fraction:.0%} of the driving frame stays in view; movement "
                "near the cropped edges would be lost.",
                f"DRIVER_VISIBLE_FRACTION_ADVISORY={DRIVER_VISIBLE_FRACTION_ADVISORY:g}",
                f"{alignment.driver_visible_fraction:.2f}",
            )
        if _reaches(alignment.fill_fraction, FILL_FRACTION_ADVISORY):
            add(
                "border_fill",
                SEVERITY_NOTE,
                BASIS_DERIVED,
                f"{alignment.fill_fraction:.0%} of the target frame is constant neutral gray fill. The new "
                "borders are visible to RGB and edge-based conditioning and may add edges of their own.",
                f"FILL_FRACTION_ADVISORY={FILL_FRACTION_ADVISORY:g}",
                f"{alignment.fill_fraction:.2f}",
            )
        margin_x, margin_y = (
            CLIPPING_MARGIN_FRACTION * media.target.width,
            CLIPPING_MARGIN_FRACTION * media.target.height,
        )
        if driver_box is not None:
            a = alignment.to_target((driver_box.left, driver_box.top))
            b = alignment.to_target((driver_box.right, driver_box.bottom))
            edges = {
                "left": min(a[0], b[0]) < margin_x,
                "top": min(a[1], b[1]) < margin_y,
                "right": max(a[0], b[0]) > media.target.width - margin_x,
                "bottom": max(a[1], b[1]) > media.target.height - margin_y,
            }
            hit = [name for name, flag in edges.items() if flag]
            if hit:
                add(
                    "subject_clipping_risk",
                    SEVERITY_CAUTION,
                    BASIS_DERIVED,
                    f"The entered subject bounds come within {CLIPPING_MARGIN_FRACTION:.0%} of, or beyond, "
                    f"the {', '.join(hit)} edge after alignment (bounds at the initial frame only).",
                    f"CLIPPING_MARGIN_FRACTION={CLIPPING_MARGIN_FRACTION:g}",
                    ", ".join(hit),
                )
    if driver.root_displacement == ROOT_LARGE and source_box is not None:
        occupancy = source_box.width / media.target.width
        if _reaches(occupancy, SOURCE_OCCUPANCY_ADVISORY_FRACTION):
            add(
                "insufficient_space",
                SEVERITY_CAUTION,
                BASIS_DERIVED,
                f"The driving subject travels a long way across the frame, but the source subject already "
                f"fills {occupancy:.0%} of its width, leaving little room to move.",
                f"SOURCE_OCCUPANCY_ADVISORY_FRACTION={SOURCE_OCCUPANCY_ADVISORY_FRACTION:g}",
                f"{occupancy:.2f}",
            )
    elif driver.root_displacement == UNKNOWN:
        unknown.append("Root displacement of the driving motion was not reported.")
    if cover > 1.0 and media.target.width > 0:
        derived.append(
            f"The workflow enlarges the driving frame {cover:.2f}x to cover the target frame (baseline)."
        )

    unknown.append(
        "Whether spatial alignment improves the generated motion for this pairing has not been tested; "
        "only an evaluation (aligned versus unaligned) can show that."
    )
    return CompatibilityAssessment(
        measured=tuple(measured),
        annotations=tuple(annotations),
        derived=tuple(derived),
        historical=tuple(historical),
        unknown=tuple(unknown),
        advisories=tuple(advisories),
    )


__all__ = [
    "ADVISORY_ONLY",
    "BASIS_DERIVED",
    "BASIS_HISTORICAL",
    "BASIS_MEASURED",
    "BASIS_OPERATOR",
    "BASIS_UNKNOWN",
    "CLIPPING_MARGIN_FRACTION",
    "DRIVER_VISIBLE_FRACTION_ADVISORY",
    "FILL_FRACTION_ADVISORY",
    "POSITION_OFFSET_ADVISORY_FRACTION",
    "ROOT_DISPLACEMENTS",
    "SCALE_RATIO_ADVISORY",
    "SEVERITY_CAUTION",
    "SEVERITY_NOTE",
    "SOURCE_OCCUPANCY_ADVISORY_FRACTION",
    "UNKNOWN",
    "CompatibilityAdvisory",
    "CompatibilityAssessment",
    "MediaFacts",
    "SubjectObservations",
    "assess_compatibility",
]

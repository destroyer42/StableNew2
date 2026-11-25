"""Typed spatial alignment of a driving clip to a source image (PR-VID-MOTION-420).

A driving-video workflow reads each frame of its clip, centre-crops it to the frozen target frame (the
prepared source image's size) and resizes it.  *Alignment* lets the operator move and scale the driving
motion inside that same target frame **explicitly and reproducibly**: one constant, uniform-scale,
translation (and optional horizontal mirror) transform applied identically to every selected frame.

This module is pure geometry plus one pixel operation; it reads no file, starts no process and imports
nothing from the GUI, queue, controller or NJR layers.

Canonical coordinate system (``COORDINATE_SYSTEM``)
    Continuous pixel-edge coordinates, origin at the top-left corner, x to the right, y downwards.  The
    *target frame* is ``[0, W] x [0, H]`` with ``(W, H)`` the prepared source image's size.  The driver's
    display frame (stored frame with its rotation applied) is ``[0, dw] x [0, dh]``.  Every number the
    operator sees is expressed in one of these two spaces, never in viewport pixels, so a transform is
    reproducible independently of any window.

Transform order (``TRANSFORM_VERSION``)
    1. *Baseline cover placement* ``c = max(W/dw, H/dh)``: the driver is scaled by ``c`` and centred on the
       target (the part outside the target is cropped), which is what the workflow's own resize does with
       an unaligned clip.
    2. Optional horizontal mirror of the driver's own pixels (the placement rectangle is symmetric about the
       target's centre, so mirroring never moves it).
    3. Uniform ``scale`` about the target's centre, then
    4. ``translation`` in target pixels.

    The placed driver is therefore the rectangle ``left = (W - dw*c*s)/2 + tx``, ``top = (H - dh*c*s)/2 + ty``
    of size ``dw*c*s`` by ``dh*c*s``; a driver point ``q`` lands at ``left + qx'*c*s, top + qy*c*s`` with
    ``qx' = dw - qx`` when mirrored.  ``aligned(t) = scale * original(t) + translation`` for every frame ``t``.

Raster resolution
    The visible part of the placement is rounded to whole target pixels, and the source box that fills it is
    computed from those integers, so the placement is exact to a fraction of a pixel and the same on every
    machine.  Pixels the driver does not cover take the declared constant fill; nothing is generated.

Nothing here tracks a subject, estimates pose, deforms a body or varies by frame.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

SCHEMA = "stablenew.motion-alignment.v1"
COORDINATE_SYSTEM = "stablenew.alignment-frame.v1"
TRANSFORM_VERSION = "stablenew.alignment-transform.v1"

FILL_POLICY = "constant_gray_128"
FILL_RGB = (128, 128, 128)
RESAMPLING = "lanczos"

# --- bounds (named; a value outside them is refused, never clamped) ------------------------------------
MIN_SCALE = 0.25
MAX_SCALE = 4.0
#: Translation is bounded to one full target dimension in each axis.
MAX_TRANSLATION_FRACTION = 1.0
SCALE_DECIMALS = 4
TRANSLATION_DECIMALS = 2
GEOMETRY_DECIMALS = 6
MAX_FRAME_DIMENSION = 16_384
MAX_ANCHORS = 12

# --- anchor-fit thresholds (named; advisory unless stated) ---------------------------------------------
#: Anchors closer than this fraction of the shorter target edge cannot define a scale.
ANCHOR_MIN_SPREAD_FRACTION = 0.05
#: Pairwise scale estimates whose largest / smallest ratio exceeds this disagree.
ANCHOR_SCALE_CONFLICT_RATIO = 1.25
#: A residual RMS above this fraction of the target diagonal is "excessive alignment error".
ANCHOR_RESIDUAL_WARNING_FRACTION = 0.03

ORIGIN_MANUAL = "manual"
ORIGIN_ANCHOR_FIT = "anchor_fit"
ORIGIN_FRAME_REGION = "frame_region"
ORIGINS = (ORIGIN_MANUAL, ORIGIN_ANCHOR_FIT, ORIGIN_FRAME_REGION)

ANCHOR_KINDS = (
    "head",
    "shoulder_center",
    "left_shoulder",
    "right_shoulder",
    "hip_center",
    "feet",
    "other",
)

FIT_OK = "ok"
FIT_WARNING = "warning"
FIT_REFUSED = "refused"


class AlignmentError(ValueError):
    """An alignment cannot be resolved; ``code`` is stable, the message is operator-facing."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --- small validated value types -----------------------------------------------------------------------


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AlignmentError("invalid_value", f"{label} must be a number.")
    number = float(value)
    if not math.isfinite(number):
        raise AlignmentError("invalid_value", f"{label} must be a finite number.")
    return number


@dataclass(frozen=True, slots=True)
class FrameSize:
    width: int
    height: int

    def validate(self, label: str) -> FrameSize:
        for name, value in (("width", self.width), ("height", self.height)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 2:
                raise AlignmentError(
                    "unsupported_geometry",
                    f"The {label} {name} must be a whole number of 2 or more.",
                )
            if value > MAX_FRAME_DIMENSION:
                raise AlignmentError(
                    "unsupported_geometry",
                    f"The {label} {name} {value} is above {MAX_FRAME_DIMENSION}.",
                )
        return self

    def to_record(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height}


@dataclass(frozen=True, slots=True)
class Rect:
    """An axis-aligned rectangle ``(left, top, right, bottom)`` in a stated coordinate space."""

    left: float
    top: float
    right: float
    bottom: float

    def validate(self, label: str) -> Rect:
        for value in (self.left, self.top, self.right, self.bottom):
            _finite(value, label)
        if self.right <= self.left or self.bottom <= self.top:
            raise AlignmentError("invalid_value", f"The {label} must have a positive size.")
        return self

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0)

    def to_record(self) -> list[float]:
        return [round(v, GEOMETRY_DECIMALS) for v in (self.left, self.top, self.right, self.bottom)]


@dataclass(frozen=True, slots=True)
class AnchorPair:
    """One operator-marked correspondence.

    ``source_xy`` is a point on the prepared source image (target-frame pixels).  ``driver_xy`` is the
    matching point on the *initial selected driving frame* in the driver's own display pixels.  Both are
    reported by the operator; they are never presented as detected pose landmarks."""

    kind: str
    source_xy: tuple[float, float]
    driver_xy: tuple[float, float]

    def to_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": [
                round(self.source_xy[0], GEOMETRY_DECIMALS),
                round(self.source_xy[1], GEOMETRY_DECIMALS),
            ],
            "driver": [
                round(self.driver_xy[0], GEOMETRY_DECIMALS),
                round(self.driver_xy[1], GEOMETRY_DECIMALS),
            ],
        }


@dataclass(frozen=True, slots=True)
class AlignmentIntent:
    """What the operator asked for, in target-frame pixels.  Provenance fields never alter the result."""

    scale: float = 1.0
    translate_x: float = 0.0
    translate_y: float = 0.0
    mirror: bool = False
    origin: str = ORIGIN_MANUAL
    anchors: tuple[AnchorPair, ...] = ()
    frame_region: Rect | None = None
    fit: Mapping[str, Any] | None = field(default=None, compare=False)

    @property
    def is_identity(self) -> bool:
        return (self.scale, self.translate_x, self.translate_y, self.mirror) == (
            1.0,
            0.0,
            0.0,
            False,
        )

    def normalized(self, target: FrameSize) -> AlignmentIntent:
        """Validated, rounded to the stated precision (a refusal, never a clamp, for anything out of range)."""

        scale = _finite(self.scale, "Scale")
        tx = _finite(self.translate_x, "Horizontal translation")
        ty = _finite(self.translate_y, "Vertical translation")
        if not isinstance(self.mirror, bool):
            raise AlignmentError("invalid_value", "Mirror must be on or off.")
        if self.origin not in ORIGINS:
            raise AlignmentError("invalid_value", f"Unknown alignment origin {self.origin!r}.")
        if not MIN_SCALE <= scale <= MAX_SCALE:
            raise AlignmentError(
                "scale_out_of_range",
                f"Scale {scale:g} is outside the supported {MIN_SCALE:g} to {MAX_SCALE:g}.",
            )
        limit_x, limit_y = (
            target.width * MAX_TRANSLATION_FRACTION,
            target.height * MAX_TRANSLATION_FRACTION,
        )
        if abs(tx) > limit_x or abs(ty) > limit_y:
            raise AlignmentError(
                "translation_out_of_range",
                f"A translation of ({tx:g}, {ty:g}) px is more than one frame "
                f"({limit_x:g} x {limit_y:g} px) from the centred placement.",
            )
        if len(self.anchors) > MAX_ANCHORS:
            raise AlignmentError(
                "invalid_anchor", f"At most {MAX_ANCHORS} anchor pairs are supported."
            )
        return AlignmentIntent(
            scale=round(scale, SCALE_DECIMALS),
            translate_x=round(tx, TRANSLATION_DECIMALS) + 0.0,
            translate_y=round(ty, TRANSLATION_DECIMALS) + 0.0,
            mirror=self.mirror,
            origin=self.origin,
            anchors=self.anchors,
            frame_region=self.frame_region,
            fit=self.fit,
        )

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "scale": self.scale,
            "translate_x": self.translate_x,
            "translate_y": self.translate_y,
            "mirror": self.mirror,
            "origin": self.origin,
        }
        if self.anchors:
            record["anchors"] = [anchor.to_record() for anchor in self.anchors]
        if self.frame_region is not None:
            record["frame_region"] = self.frame_region.to_record()
        return record


IDENTITY = AlignmentIntent()


# --- resolution -----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedAlignment:
    """The frozen, exact transform: everything needed to reproduce a frame without the form."""

    target: FrameSize
    driver: FrameSize
    baseline_scale: float
    intent: AlignmentIntent
    requested: Mapping[str, float]
    placement: Rect  # continuous, target coordinates
    destination: tuple[int, int, int, int]  # integer (x0, y0, x1, y1) inside the target
    source_box: tuple[float, float, float, float]  # driver display coordinates (after any mirror)
    fill_fraction: float  # share of the target the driver does not cover
    driver_visible_fraction: float  # share of the driver frame that remains inside the target
    clipped: Mapping[str, bool]  # which driver edges are cropped by the target boundary

    @property
    def effective_scale(self) -> float:
        """Target pixels per driver pixel (baseline cover scale times the operator's scale)."""

        return self.baseline_scale * self.intent.scale

    def to_driver(self, point: tuple[float, float]) -> tuple[float, float]:
        """Target-frame point -> driver display point (inverse of ``to_target``)."""

        qx = (point[0] - self.placement.left) / self.effective_scale
        qy = (point[1] - self.placement.top) / self.effective_scale
        return ((self.driver.width - qx) if self.intent.mirror else qx, qy)

    def to_target(self, point: tuple[float, float]) -> tuple[float, float]:
        """Driver display point -> target-frame point under this alignment."""

        qx = (self.driver.width - point[0]) if self.intent.mirror else point[0]
        return (
            self.placement.left + qx * self.effective_scale,
            self.placement.top + point[1] * self.effective_scale,
        )

    def transform_record(self) -> dict[str, Any]:
        """The resolved geometry that defines the pixels (provenance such as anchors is excluded)."""

        return {
            "coordinate_system": COORDINATE_SYSTEM,
            "transform_version": TRANSFORM_VERSION,
            "target": self.target.to_record(),
            "driver": self.driver.to_record(),
            "scale": self.intent.scale,
            "translate_x": self.intent.translate_x,
            "translate_y": self.intent.translate_y,
            "mirror": self.intent.mirror,
            "placement": self.placement.to_record(),
            "destination": list(self.destination),
            "source_box": [round(v, GEOMETRY_DECIMALS) for v in self.source_box],
            "fill": {"policy": FILL_POLICY, "rgb": list(FILL_RGB)},
            "resampling": RESAMPLING,
        }

    @property
    def transform_sha256(self) -> str:
        """Identity of the transform: equal geometry gives an equal digest, whatever produced the numbers."""

        return hashlib.sha256(
            json.dumps(self.transform_record(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema": SCHEMA,
            **self.transform_record(),
            "transform_sha256": self.transform_sha256,
            "baseline": {"scale": round(self.baseline_scale, 9)},
            "intent": self.intent.to_record(),
            "requested": {key: self.requested[key] for key in sorted(self.requested)},
            "boundary": {
                "clipped": dict(self.clipped),
                "fill_fraction": round(self.fill_fraction, 6),
                "driver_visible_fraction": round(self.driver_visible_fraction, 6),
            },
        }
        if self.intent.fit is not None:
            record["fit"] = json.loads(json.dumps(dict(self.intent.fit)))
        return record


def baseline_scale(driver: FrameSize, target: FrameSize) -> float:
    """The cover scale the workflow's own resize applies: the driver just covers the target."""

    return max(target.width / driver.width, target.height / driver.height)


def resolve_alignment(
    intent: AlignmentIntent, *, driver: FrameSize, target: FrameSize
) -> ResolvedAlignment:
    """Resolve ``intent`` for a driver and target, or raise ``AlignmentError`` (never clamps)."""

    target.validate("target frame")
    driver.validate("driving video")
    requested = {
        "scale": _finite(intent.scale, "Scale"),
        "translate_x": _finite(intent.translate_x, "Horizontal translation"),
        "translate_y": _finite(intent.translate_y, "Vertical translation"),
    }
    normal = intent.normalized(target)
    cover = baseline_scale(driver, target)
    effective = cover * normal.scale
    placed_w, placed_h = driver.width * effective, driver.height * effective
    left = (target.width - placed_w) / 2.0 + normal.translate_x
    top = (target.height - placed_h) / 2.0 + normal.translate_y
    placement = Rect(left, top, left + placed_w, top + placed_h)

    vis_left, vis_top = max(0.0, left), max(0.0, top)
    vis_right, vis_bottom = (
        min(float(target.width), left + placed_w),
        min(float(target.height), top + placed_h),
    )
    if vis_right <= vis_left or vis_bottom <= vis_top:
        raise AlignmentError(
            "no_overlap",
            "With this scale and translation the driving frame no longer overlaps the target frame.",
        )
    x0, y0 = math.floor(vis_left + 0.5), math.floor(vis_top + 0.5)
    x1, y1 = math.floor(vis_right + 0.5), math.floor(vis_bottom + 0.5)
    if x1 <= x0 or y1 <= y0:
        raise AlignmentError(
            "no_overlap",
            "The visible part of the driving frame is smaller than one pixel of the target frame.",
        )
    slack = (
        0.5 / effective + _EDGE_EPSILON
    )  # rounding the edge to the pixel grid moves it <= half a pixel
    box = (
        _clamp_edge((x0 - left) / effective, driver.width, slack),
        _clamp_edge((y0 - top) / effective, driver.height, slack),
        _clamp_edge((x1 - left) / effective, driver.width, slack),
        _clamp_edge((y1 - top) / effective, driver.height, slack),
    )
    covered = (x1 - x0) * (y1 - y0)
    visible_fraction = ((box[2] - box[0]) * (box[3] - box[1])) / (driver.width * driver.height)
    clipped = {
        "left": left < -_EDGE_EPSILON,
        "top": top < -_EDGE_EPSILON,
        "right": left + placed_w > target.width + _EDGE_EPSILON,
        "bottom": top + placed_h > target.height + _EDGE_EPSILON,
    }
    return ResolvedAlignment(
        target=target,
        driver=driver,
        baseline_scale=cover,
        intent=normal,
        requested=requested,
        placement=placement,
        destination=(x0, y0, x1, y1),
        source_box=box,
        fill_fraction=max(0.0, 1.0 - covered / (target.width * target.height)),
        driver_visible_fraction=min(1.0, max(0.0, visible_fraction)),
        clipped=clipped,
    )


_EDGE_EPSILON = 1e-6


def _clamp_edge(value: float, limit: int, slack: float) -> float:
    """Snap a box edge that rounding pushed at most ``slack`` past the frame; more is an arithmetic error."""

    if value < -slack or value > limit + slack:
        raise AlignmentError(
            "unsupported_geometry", "The placement does not map inside the driving frame."
        )
    return min(float(limit), max(0.0, value))


# --- the one pixel operation ----------------------------------------------------------------------------


def transform_frame(image: Image.Image, resolved: ResolvedAlignment) -> Image.Image:
    """One driver frame (display orientation) -> the target frame under ``resolved``.

    The same function produces previews and the published derivative, so they cannot disagree."""

    if image.size != (resolved.driver.width, resolved.driver.height):
        raise AlignmentError(
            "unsupported_geometry",
            f"The frame is {image.size[0]}x{image.size[1]}, not the "
            f"{resolved.driver.width}x{resolved.driver.height} the alignment was resolved for.",
        )
    rgb = image.convert("RGB")
    if resolved.intent.mirror:
        rgb = rgb.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    x0, y0, x1, y1 = resolved.destination
    patch = rgb.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS, box=resolved.source_box)
    canvas = Image.new("RGB", (resolved.target.width, resolved.target.height), FILL_RGB)
    canvas.paste(patch, (x0, y0))
    return canvas


# --- anchors and the suggested fit ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FitIssue:
    code: str
    message: str
    blocking: bool


@dataclass(frozen=True, slots=True)
class FitResult:
    """The deterministic least-squares suggestion and how well it explains the operator's anchors."""

    status: str
    intent: AlignmentIntent | None
    issues: tuple[FitIssue, ...] = ()
    residuals: tuple[float, ...] = ()  # target pixels per anchor pair
    rms_error: float = 0.0
    max_error: float = 0.0
    scale_estimates: tuple[float, ...] = ()
    anchors_used: int = 0

    @property
    def proposed(self) -> bool:
        return self.intent is not None

    def summary_record(self) -> dict[str, Any]:
        return {
            "method": "least_squares_uniform_scale_translation",
            "status": self.status,
            "anchors_used": self.anchors_used,
            "rms_error_px": round(self.rms_error, 4),
            "max_error_px": round(self.max_error, 4),
            "scale_estimates": [round(v, 6) for v in self.scale_estimates],
            "issues": [issue.code for issue in self.issues],
        }


def _validate_anchor(anchor: AnchorPair, driver: FrameSize, target: FrameSize) -> FitIssue | None:
    if anchor.kind not in ANCHOR_KINDS:
        return FitIssue("invalid_anchor", f"Unknown anchor kind {anchor.kind!r}.", True)
    try:
        sx, sy = (_finite(v, "An anchor coordinate") for v in anchor.source_xy)
        dx, dy = (_finite(v, "An anchor coordinate") for v in anchor.driver_xy)
    except (AlignmentError, TypeError, ValueError):
        return FitIssue(
            "invalid_anchor", "An anchor has a missing or non-numeric coordinate.", True
        )
    if not (0.0 <= sx <= target.width and 0.0 <= sy <= target.height):
        return FitIssue("invalid_anchor", "A source anchor lies outside the source image.", True)
    if not (0.0 <= dx <= driver.width and 0.0 <= dy <= driver.height):
        return FitIssue(
            "invalid_anchor", "A driving-frame anchor lies outside the driving frame.", True
        )
    return None


def fit_anchors(
    anchors: Sequence[AnchorPair],
    *,
    driver: FrameSize,
    target: FrameSize,
    mirror: bool = False,
) -> FitResult:
    """Fit ``scale`` and ``translation`` (no rotation, no per-axis scale) to corresponding anchors.

    Each driver anchor is mapped through the baseline cover placement (and the mirror, if chosen) to the
    target frame; the fit then minimises the sum of squared distances to the matching source anchors over
    ``a = s * b + t0`` (closed form: ``s = sum(b~ . a~) / sum(|b~|^2)`` on mean-centred points, ``t0 = a_mean -
    s * b_mean``), and ``t0`` is re-expressed as the operator's translation about the centred placement.
    One anchor pair can only fix the translation (the scale stays 1); two or more fix both.  Fewer than
    one, a driver whose anchors coincide, or any invalid point is refused with a reason."""

    target.validate("target frame")
    driver.validate("driving video")
    if not anchors:
        return FitResult(
            FIT_REFUSED,
            None,
            (FitIssue("insufficient_anchors", "Mark at least one pair of matching points.", True),),
        )
    if len(anchors) > MAX_ANCHORS:
        return FitResult(
            FIT_REFUSED,
            None,
            (
                FitIssue(
                    "invalid_anchor", f"At most {MAX_ANCHORS} anchor pairs are supported.", True
                ),
            ),
        )
    for anchor in anchors:
        problem = _validate_anchor(anchor, driver, target)
        if problem is not None:
            return FitResult(FIT_REFUSED, None, (problem,))
    cover = baseline_scale(driver, target)
    origin_x = (target.width - driver.width * cover) / 2.0
    origin_y = (target.height - driver.height * cover) / 2.0
    base_pts = []
    for anchor in anchors:
        qx = (driver.width - anchor.driver_xy[0]) if mirror else anchor.driver_xy[0]
        base_pts.append((origin_x + qx * cover, origin_y + anchor.driver_xy[1] * cover))
    src_pts = [(float(a.source_xy[0]), float(a.source_xy[1])) for a in anchors]
    count = len(anchors)
    mean_b = (sum(p[0] for p in base_pts) / count, sum(p[1] for p in base_pts) / count)
    mean_a = (sum(p[0] for p in src_pts) / count, sum(p[1] for p in src_pts) / count)
    issues: list[FitIssue] = []
    estimates: list[float] = []
    if count == 1:
        scale = 1.0
        issues.append(
            FitIssue(
                "translation_only",
                "One pair fixes only the position; the scale stays 1. Add a second pair to fit the scale.",
                False,
            )
        )
    else:
        spread = max(
            math.dist(base_pts[i], base_pts[j]) for i in range(count) for j in range(i + 1, count)
        )
        src_spread = max(
            math.dist(src_pts[i], src_pts[j]) for i in range(count) for j in range(i + 1, count)
        )
        minimum = ANCHOR_MIN_SPREAD_FRACTION * min(target.width, target.height)
        if spread < minimum or src_spread < minimum:
            return FitResult(
                FIT_REFUSED,
                None,
                (
                    FitIssue(
                        "degenerate_anchors",
                        "The marked points are too close together to fit a scale "
                        f"(they must be at least {ANCHOR_MIN_SPREAD_FRACTION:.0%} of the frame apart).",
                        True,
                    ),
                ),
                anchors_used=count,
            )
        sxx = sum((b[0] - mean_b[0]) ** 2 + (b[1] - mean_b[1]) ** 2 for b in base_pts)
        sxy = sum(
            (b[0] - mean_b[0]) * (a[0] - mean_a[0]) + (b[1] - mean_b[1]) * (a[1] - mean_a[1])
            for b, a in zip(base_pts, src_pts, strict=True)
        )
        scale = sxy / sxx
        for i in range(count):
            for j in range(i + 1, count):
                db, da = math.dist(base_pts[i], base_pts[j]), math.dist(src_pts[i], src_pts[j])
                if db > 0 and da > 0:
                    estimates.append(da / db)
        if estimates and max(estimates) / min(estimates) > ANCHOR_SCALE_CONFLICT_RATIO:
            issues.append(
                FitIssue(
                    "conflicting_scale",
                    f"The marked points disagree about the scale (estimates {min(estimates):.2f} to "
                    f"{max(estimates):.2f}); check that each pair marks the same body point.",
                    False,
                )
            )
    if not math.isfinite(scale) or not MIN_SCALE <= scale <= MAX_SCALE:
        return FitResult(
            FIT_REFUSED,
            None,
            (
                FitIssue(
                    "scale_out_of_range",
                    f"The fitted scale {scale:.3g} is outside the supported {MIN_SCALE:g} to {MAX_SCALE:g}.",
                    True,
                ),
            ),
            scale_estimates=tuple(estimates),
            anchors_used=count,
        )
    t0 = (mean_a[0] - scale * mean_b[0], mean_a[1] - scale * mean_b[1])
    # a = s*b + t0 and the placement is s*b + C*(1 - s) + t, so t = t0 - C*(1 - s).
    centre = (target.width / 2.0, target.height / 2.0)
    translate = (t0[0] - centre[0] * (1.0 - scale), t0[1] - centre[1] * (1.0 - scale))
    proposal = AlignmentIntent(
        scale=scale,
        translate_x=translate[0],
        translate_y=translate[1],
        mirror=mirror,
        origin=ORIGIN_ANCHOR_FIT,
        anchors=tuple(anchors),
    )
    try:
        normal = proposal.normalized(target)
    except AlignmentError as exc:
        return FitResult(
            FIT_REFUSED, None, (FitIssue(exc.code, exc.message, True),), anchors_used=count
        )
    residuals = tuple(
        math.dist((scale * b[0] + t0[0], scale * b[1] + t0[1]), a)
        for b, a in zip(base_pts, src_pts, strict=True)
    )
    rms = math.sqrt(sum(r * r for r in residuals) / count)
    diagonal = math.hypot(target.width, target.height)
    if rms > ANCHOR_RESIDUAL_WARNING_FRACTION * diagonal:
        issues.append(
            FitIssue(
                "excessive_error",
                f"The fit leaves {rms:.1f} px of error (more than "
                f"{ANCHOR_RESIDUAL_WARNING_FRACTION:.0%} of the frame diagonal); the points do not "
                "agree on one scale and position.",
                False,
            )
        )
    result = FitResult(
        FIT_WARNING
        if any(not i.blocking for i in issues if i.code != "translation_only")
        else FIT_OK,
        normal,
        tuple(issues),
        residuals,
        rms,
        max(residuals),
        tuple(estimates),
        count,
    )
    return FitResult(
        result.status,
        AlignmentIntent(
            scale=normal.scale,
            translate_x=normal.translate_x,
            translate_y=normal.translate_y,
            mirror=normal.mirror,
            origin=ORIGIN_ANCHOR_FIT,
            anchors=tuple(anchors),
            fit=result.summary_record(),
        ),
        result.issues,
        result.residuals,
        result.rms_error,
        result.max_error,
        result.scale_estimates,
        count,
    )


def intent_from_frame_region(
    region: Rect, *, driver: FrameSize, target: FrameSize, mirror: bool = False
) -> AlignmentIntent:
    """Reframing as an explicit crop: scale and place so ``region`` (driver display pixels) covers the target.

    The region's centre lands on the target's centre and the region just covers the frame (cover semantics,
    uniform scale), so this is the same constant transform expressed as "frame this part of the driver"."""

    target.validate("target frame")
    driver.validate("driving video")
    region.validate("crop region")
    if (
        region.left < 0
        or region.top < 0
        or region.right > driver.width
        or region.bottom > driver.height
    ):
        raise AlignmentError("invalid_value", "The crop region must lie inside the driving frame.")
    pixels_per_pixel = max(target.width / region.width, target.height / region.height)
    scale = pixels_per_pixel / baseline_scale(driver, target)
    cx = (driver.width - region.center[0]) if mirror else region.center[0]
    placed_w, placed_h = driver.width * pixels_per_pixel, driver.height * pixels_per_pixel
    left = target.width / 2.0 - cx * pixels_per_pixel
    top = target.height / 2.0 - region.center[1] * pixels_per_pixel
    return AlignmentIntent(
        scale=scale,
        translate_x=left - (target.width - placed_w) / 2.0,
        translate_y=top - (target.height - placed_h) / 2.0,
        mirror=mirror,
        origin=ORIGIN_FRAME_REGION,
        frame_region=region,
    )


# --- movement-envelope inspection -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnvelopeFrame:
    """One inspected frame: the operator's subject bounds in driver pixels and where they land."""

    output_frame: int
    driver_bounds: Rect
    target_bounds: Rect
    clipped_sides: tuple[str, ...]
    fully_visible: bool


@dataclass(frozen=True, slots=True)
class EnvelopeReport:
    frames: tuple[EnvelopeFrame, ...]
    sampled: int
    total_frames: int
    all_sampled_visible: bool

    @property
    def whole_window_verified(self) -> bool:
        """True only when every output frame was inspected (sampling is never presented as proof)."""

        return self.sampled >= self.total_frames > 0

    @property
    def statement(self) -> str:
        if not self.frames:
            return "No subject bounds were entered, so the movement envelope was not inspected."
        scope = (
            f"all {self.total_frames} frames"
            if self.whole_window_verified
            else f"{self.sampled} sampled frame(s) of {self.total_frames}"
        )
        if self.all_sampled_visible:
            tail = (
                "the entered bounds stay inside the frame."
                if self.whole_window_verified
                else "the entered bounds stay inside the frame there; frames between the samples were "
                "not inspected."
            )
        else:
            tail = "the entered bounds are clipped by the frame boundary in at least one of them."
        return f"Inspected {scope}: {tail}"


def inspect_envelope(
    resolved: ResolvedAlignment, observations: Mapping[int, Rect], *, total_frames: int
) -> EnvelopeReport:
    """Where operator-entered subject bounds land under the constant transform.

    ``observations`` maps an output-frame index to a rectangle in driver display pixels.  Nothing is
    estimated: only the bounds the operator entered are mapped, and the report says how many frames that
    covers."""

    frames: list[EnvelopeFrame] = []
    for index in sorted(observations):
        bounds = observations[index].validate("subject bounds")
        a = resolved.to_target((bounds.left, bounds.top))
        b = resolved.to_target((bounds.right, bounds.bottom))
        target_bounds = Rect(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        sides = tuple(
            name
            for name, hit in (
                ("left", target_bounds.left < 0),
                ("top", target_bounds.top < 0),
                ("right", target_bounds.right > resolved.target.width),
                ("bottom", target_bounds.bottom > resolved.target.height),
            )
            if hit
        )
        frames.append(EnvelopeFrame(index, bounds, target_bounds, sides, not sides))
    return EnvelopeReport(
        tuple(frames), len(frames), int(total_frames), all(f.fully_visible for f in frames)
    )


def positions_under(
    resolved: ResolvedAlignment, positions: Iterable[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Driver points -> target points under the one constant transform (test and display helper)."""

    return [resolved.to_target(point) for point in positions]


def alignment_from_record(record: Mapping[str, Any]) -> ResolvedAlignment:
    """Re-resolve a stored record from its intent and geometry, refusing any disagreement.

    Used at admission and dispatch: the frozen numbers must be exactly what the stated intent and
    geometry resolve to with this transform version, so a hand-edited record is never trusted."""

    if record.get("schema") != SCHEMA:
        raise AlignmentError("unsupported_record", "The alignment record is not recognised.")
    if (
        record.get("coordinate_system") != COORDINATE_SYSTEM
        or record.get("transform_version") != TRANSFORM_VERSION
    ):
        raise AlignmentError(
            "unsupported_version",
            "The alignment was made with a different transform version and is not recomputed; "
            "prepare it again.",
        )
    try:
        target = FrameSize(int(record["target"]["width"]), int(record["target"]["height"]))
        driver = FrameSize(int(record["driver"]["width"]), int(record["driver"]["height"]))
        intent = AlignmentIntent(
            scale=record["scale"],
            translate_x=record["translate_x"],
            translate_y=record["translate_y"],
            mirror=record["mirror"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AlignmentError("unsupported_record", "The alignment record is incomplete.") from exc
    resolved = resolve_alignment(intent, driver=driver, target=target)
    if resolved.transform_sha256 != record.get(
        "transform_sha256"
    ) or resolved.transform_record() != {
        key: record.get(key) for key in resolved.transform_record()
    }:
        raise AlignmentError(
            "record_mismatch", "The alignment record does not match the transform it describes."
        )
    return resolved


__all__ = [
    "ANCHOR_KINDS",
    "ANCHOR_MIN_SPREAD_FRACTION",
    "ANCHOR_RESIDUAL_WARNING_FRACTION",
    "ANCHOR_SCALE_CONFLICT_RATIO",
    "COORDINATE_SYSTEM",
    "FILL_POLICY",
    "FILL_RGB",
    "FIT_OK",
    "FIT_REFUSED",
    "FIT_WARNING",
    "IDENTITY",
    "MAX_ANCHORS",
    "MAX_SCALE",
    "MIN_SCALE",
    "ORIGINS",
    "ORIGIN_ANCHOR_FIT",
    "ORIGIN_FRAME_REGION",
    "ORIGIN_MANUAL",
    "RESAMPLING",
    "SCHEMA",
    "TRANSFORM_VERSION",
    "AlignmentError",
    "AlignmentIntent",
    "AnchorPair",
    "EnvelopeFrame",
    "EnvelopeReport",
    "FitIssue",
    "FitResult",
    "FrameSize",
    "Rect",
    "ResolvedAlignment",
    "alignment_from_record",
    "baseline_scale",
    "fit_anchors",
    "inspect_envelope",
    "intent_from_frame_region",
    "positions_under",
    "resolve_alignment",
    "transform_frame",
]

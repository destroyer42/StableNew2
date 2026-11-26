"""Advisories for the effective conditioning of a driving clip (PR-VID-MOTION-430).

Every advisory carries its *basis* so a measured observation, a heuristic reading, a fact read from the pinned runtime source
and a historical single-host observation are never mistaken for one another:

* ``measured`` - a number computed from the pixels or files in front of the operator (the number is in the text);
* ``runtime_source`` - what the pinned ComfyUI source does with the clip;
* ``heuristic`` - a plausible reading of a measurement; it never says the motion will or will not transfer;
* ``historical`` - something observed once, on one host, with a stated sample.

Nothing here is a score, nothing ranks a representation or a workflow, and nothing blocks: edge density, tonal contrast and
similarity are never presented as motion-transfer accuracy.  A refusal only ever comes from an actual declared workflow or
preparation requirement, which other modules own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.video.workflow_conditioning import (
    BASIS_HEURISTIC,
    BASIS_HISTORICAL,
    BASIS_MEASURED,
    BASIS_RUNTIME_SOURCE,
    MECH_CANNY_THEN_RESIZE,
    MECH_RGB_VAE,
    REP_RENDERED_CHARACTER,
    REP_RENDERED_SILHOUETTE,
    REP_RENDERED_SKELETON,
    REP_RGB_FOOTAGE,
    ConditioningContract,
)

#: Comfy's request-size limit seen as HTTP 413 on an unaligned 4K prepared clip (PR-VID-MOTION-420 record, one host).
COMFY_UPLOAD_LIMIT_BYTES = 104_857_600
#: Channels the pinned kornia non-maximum-suppression stage materialises per frame (``get_canny_nms_kernel``).
KORNIA_NMS_CHANNELS = 8
LOW_CONTRAST_STD = 0.05
INTERIOR_EDGE_DENSITY = 0.12
UNIFORM_BAND_STD = 0.004
UNIFORM_BAND_MIN_FRACTION = 0.04
SUBJECT_BAND_FRACTION = 0.25
SUBJECT_GAP_FRACTION = 0.10
OVERSIZE_PIXEL_RATIO = 4.0


@dataclass(frozen=True, slots=True)
class ConditioningAdvisory:
    code: str
    text: str
    basis: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "text": self.text, "basis": self.basis}


# ------------------------------------------------------------------------------------------------ image measurements


def tonal_contrast(gray: np.ndarray) -> float:
    """Standard deviation of a 0..1 grayscale frame (a global measurement, not subject/background contrast)."""

    return float(np.std(gray))


def bbox_edge_density(edges: np.ndarray) -> float | None:
    """Edge density inside the bounding box of the edges (``None`` when there are none)."""

    ys, xs = np.nonzero(edges)
    if ys.size == 0:
        return None
    box = edges[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    return float(box.mean())


def uniform_bands(gray: np.ndarray) -> dict[str, float]:
    """Fraction of each frame edge covered by a constant-colour band (padding or letterboxing), per side."""

    h, w = gray.shape
    found: dict[str, float] = {}

    def run(lines: np.ndarray) -> int:
        count = 0
        for line in lines:
            if float(np.std(line)) > UNIFORM_BAND_STD:
                break
            if count and abs(float(line.mean()) - float(lines[0].mean())) > UNIFORM_BAND_STD:
                break
            count += 1
        return count

    for side, lines, total in (
        ("top", gray, h),
        ("bottom", gray[::-1], h),
        ("left", gray.T, w),
        ("right", gray.T[::-1], w),
    ):
        fraction = run(lines) / total
        if fraction >= UNIFORM_BAND_MIN_FRACTION:
            found[side] = fraction
    return found


def subject_clusters(edges: np.ndarray) -> int:
    """Horizontally separated groups of edge columns (a crude count of visible subjects)."""

    profile = edges.sum(axis=0).astype(np.float32)
    if profile.max() <= 0:
        return 0
    active = profile >= SUBJECT_BAND_FRACTION * float(profile.max())
    min_gap = max(1, int(round(SUBJECT_GAP_FRACTION * edges.shape[1])))
    groups, gap, inside = 0, min_gap, False
    for flag in active:
        if flag:
            if not inside and gap >= min_gap:
                groups += 1
            inside, gap = True, 0
        else:
            inside = False
            gap += 1
    return groups


def canny_working_set_bytes(width: int, height: int, frames: int) -> int:
    """Lower bound of the NMS tensor the pinned kornia Canny holds for a clip decoded at ``width`` x ``height``."""

    return int(width) * int(height) * int(frames) * 4 * KORNIA_NMS_CHANNELS


def _gib(value: float) -> str:
    return f"{value / 1024**3:.1f} GiB"


# ------------------------------------------------------------------------------------------------ advisory builders


def frame_advisories(
    *,
    densities: Sequence[float],
    border_shares: Sequence[float],
    motion_diffs: Sequence[float],
    gray_frames: Sequence[np.ndarray],
    edge_frames: Sequence[np.ndarray],
    video_aspect: float,
    target_aspect: float,
    reference_iou: float | None,
    downscaled: bool,
    min_density: float,
    max_density: float,
    border_edge_share: float,
    near_static: float,
    large_change: float,
    aspect_tolerance: float,
) -> tuple[ConditioningAdvisory, ...]:
    """Observations about the sampled frames of the effective driving clip."""

    notes: list[ConditioningAdvisory] = []
    if downscaled:
        notes.append(
            ConditioningAdvisory(
                "analysis_reduced",
                "Analyzed at a reduced size; the graph runs Canny on the full-size frames.",
                BASIS_MEASURED,
            )
        )
    if densities and max(densities) < min_density:
        notes.append(
            ConditioningAdvisory(
                "faint_outline",
                "Very few edges were found; the subject may be too faint or small to guide motion, and thin limbs "
                "may not be outlined.",
                BASIS_HEURISTIC,
            )
        )
    if densities and min(densities) > max_density:
        notes.append(
            ConditioningAdvisory(
                "dense_edges",
                "Edges are very dense, which often means a busy or textured background competing with the subject.",
                BASIS_HEURISTIC,
            )
        )
    if border_shares and max(border_shares) > border_edge_share:
        notes.append(
            ConditioningAdvisory(
                "subject_clipping",
                "Much of the edge detail touches the frame border; the subject may be cropped.",
                BASIS_HEURISTIC,
            )
        )
    if motion_diffs:
        if max(motion_diffs) < near_static:
            notes.append(
                ConditioningAdvisory(
                    "near_static",
                    "The sampled frames barely differ; the motion may be near static.",
                    BASIS_MEASURED,
                )
            )
        if max(motion_diffs) > large_change:
            notes.append(
                ConditioningAdvisory(
                    "large_change",
                    "Large frame-to-frame change between samples; this can be camera movement or a cut.",
                    BASIS_HEURISTIC,
                )
            )
    if (
        video_aspect > 0
        and target_aspect > 0
        and abs(video_aspect / target_aspect - 1.0) > aspect_tolerance
    ):
        notes.append(
            ConditioningAdvisory(
                "aspect_crop",
                "The video's shape differs from the generation shape; each frame is center-cropped to it, "
                "so anything near the cropped sides is lost.",
                BASIS_RUNTIME_SOURCE,
            )
        )
    if reference_iou is not None and reference_iou < 0.5:
        notes.append(
            ConditioningAdvisory(
                "reference_overlap",
                "The subject's edge outline barely overlaps the reference image's; expect a position or scale mismatch.",
                BASIS_HEURISTIC,
            )
        )
    if gray_frames:
        contrast = max(tonal_contrast(g) for g in gray_frames)
        if contrast < LOW_CONTRAST_STD:
            notes.append(
                ConditioningAdvisory(
                    "low_contrast",
                    f"Low tonal contrast (the most contrasty sampled frame has a brightness spread of {contrast:.3f} on a "
                    "0-1 scale); an edge detector may find little to outline.",
                    BASIS_MEASURED,
                )
            )
        bands = uniform_bands(gray_frames[0])
        if bands:
            sides = ", ".join(f"{side} {fraction:.0%}" for side, fraction in sorted(bands.items()))
            notes.append(
                ConditioningAdvisory(
                    "uniform_border",
                    f"A constant-colour band covers part of the frame edge ({sides}); alignment padding or letterboxing "
                    "adds a hard boundary that an edge detector outlines as an edge of its own.",
                    BASIS_MEASURED,
                )
            )
    if edge_frames:
        interior = [d for d in (bbox_edge_density(e) for e in edge_frames) if d is not None]
        if interior and min(interior) > INTERIOR_EDGE_DENSITY:
            notes.append(
                ConditioningAdvisory(
                    "internal_texture",
                    f"Edges fill much of the subject's bounding box (at least {min(interior):.0%} of its pixels in every "
                    "sampled frame), which suggests texture or pattern detail rather than a clean outline.",
                    BASIS_HEURISTIC,
                )
            )
        clusters = max(subject_clusters(e) for e in edge_frames)
        if clusters >= 2:
            notes.append(
                ConditioningAdvisory(
                    "multiple_subjects",
                    f"The edges form {clusters} separate groups side by side; more than one person or object may be "
                    "visible, and the model may attach the motion to the wrong one.",
                    BASIS_HEURISTIC,
                )
            )
    return tuple(notes)


def preparation_advisories(
    *,
    contract: ConditioningContract | None,
    width: int,
    height: int,
    frames: int,
    target_size: tuple[int, int],
    file_bytes: int | None,
) -> tuple[ConditioningAdvisory, ...]:
    """Size-related observations about the prepared driving clip (no hard threshold is imposed)."""

    notes: list[ConditioningAdvisory] = []
    pixels, target_pixels = width * height, target_size[0] * target_size[1]
    edge_first = contract is not None and contract.mechanism == MECH_CANNY_THEN_RESIZE
    if edge_first and frames > 0 and pixels > 0:
        notes.append(
            ConditioningAdvisory(
                "canny_working_set",
                f"This workflow runs Canny on the clip at its own {width}x{height} size before cropping and resizing to "
                f"{target_size[0]}x{target_size[1]}; the non-maximum-suppression stage alone holds at least "
                f"{_gib(canny_working_set_bytes(width, height, frames))} for {frames} frames (computed from the pinned "
                "kornia source, not measured on your machine).",
                BASIS_RUNTIME_SOURCE,
            )
        )
    if target_pixels and pixels > OVERSIZE_PIXEL_RATIO * target_pixels:
        notes.append(
            ConditioningAdvisory(
                "excessive_resolution",
                f"The driving clip has {pixels / target_pixels:.1f}x the pixels of the generation geometry. "
                + (
                    "Earlier 4K drivers for this workflow failed with memory or time-outs until they were pre-scaled "
                    "(one host, two clips). Prepare Motion Source now scales an input longer than 832 px to an 832-pixel "
                    "long edge for this workflow, so inspect and use the prepared derivative, not the original."
                    if edge_first
                    else "Everything beyond the generation geometry is discarded when the frames are resized, at a "
                    "cost in upload size and preparation time."
                ),
                BASIS_HISTORICAL if edge_first else BASIS_HEURISTIC,
            )
        )
    if file_bytes is not None and file_bytes >= COMFY_UPLOAD_LIMIT_BYTES:
        notes.append(
            ConditioningAdvisory(
                "upload_limit",
                f"The clip is {file_bytes:,} bytes; ComfyUI rejected a 107,409,268-byte prepared clip at upload with "
                f"HTTP 413 (limit {COMFY_UPLOAD_LIMIT_BYTES:,} bytes). Pre-scale a same-aspect copy or choose a shorter window.",
                BASIS_MEASURED,
            )
        )
    return tuple(notes)


def context_advisories(
    *,
    contract: ConditioningContract | None,
    representation: str | None,
    window_frames: int,
    generation_frames: int | None,
    driver_viewpoint: str = "",
    source_viewpoint: str = "",
    motion_category: str = "",
) -> tuple[ConditioningAdvisory, ...]:
    """What the representation, viewpoint and window mean for the selected workflow."""

    notes: list[ConditioningAdvisory] = []
    if contract is not None and representation in (REP_RGB_FOOTAGE, REP_RENDERED_CHARACTER):
        if contract.mechanism == MECH_RGB_VAE:
            notes.append(
                ConditioningAdvisory(
                    "driver_appearance",
                    "The driver's own appearance and background are visible to this workflow (frames are encoded as "
                    "they are); a driver that looks unlike your subject can contaminate the result.",
                    BASIS_RUNTIME_SOURCE,
                )
            )
        elif contract.mechanism == MECH_CANNY_THEN_RESIZE:
            notes.append(
                ConditioningAdvisory(
                    "driver_appearance",
                    "Only edges reach the model, but a driver's outline, clothing texture and background still shape "
                    "them; ordinary footage was observed to carry identity and background information into results.",
                    BASIS_HISTORICAL,
                )
            )
    if representation == REP_RENDERED_SKELETON and motion_category == "head_turn":
        notes.append(
            ConditioningAdvisory(
                "skeleton_head_orientation",
                "A body skeleton render may carry little head-orientation information, so a head turn can be poorly "
                "represented; that limits this representation for this action rather than failing the workflow.",
                BASIS_HEURISTIC,
            )
        )
    if representation == REP_RENDERED_SILHOUETTE and motion_category == "head_turn":
        notes.append(
            ConditioningAdvisory(
                "silhouette_head_orientation",
                "A silhouette hides facial orientation; a head turn is mostly visible only as an outline change.",
                BASIS_HEURISTIC,
            )
        )
    if (
        driver_viewpoint
        and source_viewpoint
        and driver_viewpoint.strip().lower() != source_viewpoint.strip().lower()
    ):
        notes.append(
            ConditioningAdvisory(
                "viewpoint_mismatch",
                f"The driver is annotated '{driver_viewpoint}' but the source image '{source_viewpoint}'; a start-pose "
                "or viewpoint mismatch produced an unnatural opening in earlier tests.",
                BASIS_HISTORICAL,
            )
        )
    if generation_frames and window_frames:
        if window_frames < generation_frames:
            notes.append(
                ConditioningAdvisory(
                    "window_short",
                    f"The selected window has {window_frames} frames but {generation_frames} are generated; "
                    + (
                        "the pinned Wan-Animate-2 node pads the missing frames by holding the last one, so the action "
                        "stops moving."
                        if contract is not None and contract.mechanism == MECH_RGB_VAE
                        else "the action may not cover the whole clip."
                    ),
                    BASIS_RUNTIME_SOURCE
                    if contract is not None and contract.mechanism == MECH_RGB_VAE
                    else BASIS_HEURISTIC,
                )
            )
        elif window_frames > generation_frames:
            notes.append(
                ConditioningAdvisory(
                    "window_long",
                    f"The selected window has {window_frames} frames but only the first {generation_frames} are used; "
                    "the rest of the action is not consumed.",
                    BASIS_RUNTIME_SOURCE,
                )
            )
    return tuple(notes)


def advisory_texts(advisories: Sequence[ConditioningAdvisory]) -> tuple[str, ...]:
    return tuple(a.text for a in advisories)


def advisories_payload(advisories: Sequence[ConditioningAdvisory]) -> list[Mapping[str, Any]]:
    return [a.to_dict() for a in advisories]


__all__ = [
    "COMFY_UPLOAD_LIMIT_BYTES",
    "ConditioningAdvisory",
    "advisories_payload",
    "advisory_texts",
    "bbox_edge_density",
    "canny_working_set_bytes",
    "context_advisories",
    "frame_advisories",
    "preparation_advisories",
    "subject_clusters",
    "tonal_contrast",
    "uniform_bands",
]

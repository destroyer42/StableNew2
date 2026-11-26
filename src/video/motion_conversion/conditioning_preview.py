"""Advisory preview of what a Canny control video would look like (PR-VID-MOTION-354).

Pure CPU, read-only: it decodes a few frames of one video with FFmpeg, runs a NumPy re-implementation of the Canny stage the
Fun Control graph uses (low 0.1 / high 0.6 on a 0..1 grayscale image: 5x5 Gaussian sigma 1, Sobel, 45-degree non-maximum
suppression, hysteresis), and reports bounded heuristic warnings.  It never calls Comfy, never edits a job and never gates one.

**Operation order** (read from the pinned ComfyUI v0.38.0 graph and nodes, not assumed): the prepared clip is decoded, Canny runs
on each frame *at the size the frame arrives*, and only then does ``Wan22FunControlToVideo`` centre-crop the edge image to the
generation aspect and resize it bilinearly to width x height before VAE-encoding it.  The preview follows that order (edges first,
then crop and resize); an earlier version cropped before detecting edges.

**Exactness.**  The result is labeled ``approximate``.  The edge detector reproduces the pinned kornia Canny (exact 5-tap sigma-1
Gaussian, reflect-padded blur, replicate-padded Sobel, 8-neighbour non-maximum suppression, hysteresis) and matches it bit for bit
on four recorded synthetic vectors, but exact parity on real clips is not established: the preview analyses a reduced copy, runs on
the CPU rather than the model's float32 path, and has not been compared on decoded production frames.
``exact_parity_verified`` stays False until such evidence exists.  The advisories are labelled by basis; none is a quality score:
edge density says nothing about identity or whether the motion will transfer.
"""

from __future__ import annotations

import struct
import threading
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from src.utils.managed_process import ProcessOutcome, run_bounded
from src.video import conditioning_advisories as adv
from src.video.conditioning_advisories import ConditioningAdvisory
from src.video.workflow_conditioning import BASIS_HEURISTIC, ConditioningContract

LOW_THRESHOLD = 0.1
HIGH_THRESHOLD = 0.6
EXACTNESS_APPROXIMATE = "approximate"
EXACTNESS_EXACT = "exact"
EXACT_PARITY_VERIFIED = False
EXACTNESS_REASON = (
    "Approximation: the edge detector matches the pinned Canny node on four recorded synthetic vectors, but exact parity on "
    "real clips is not verified (reduced-size analysis, CPU instead of the model's path). Advisory only."
)
#: Operation order of the Fun Control graph (pinned ComfyUI v0.38.0), which this preview follows.
OPERATION_ORDER = (
    "decode the prepared driving clip",
    "Canny edge detection at the frame's own size",
    "centre-crop to the generation aspect",
    "bilinear resize to the generation size",
    "VAE-encode as the control video",
)
FIDELITY_SOURCE = "Exact bytes of the verified driving file; the pictures shown are decoded at a reduced analysis size."
FIDELITY_PREPARED = "Exact verified prepared frames when the driver is a Prepare Motion Source or Align Motion derivative."
FIDELITY_CONDITIONING = (
    "Approximate: not the model's conditioning tensor and not independently verified on real clips."
)
MAX_ANALYSIS_EDGE = 1280
MAX_PREVIEW_EDGE = 320
MOTION_SAMPLES = 8
DECODE_TIMEOUT_SECONDS = 120.0
MIN_EDGE_DENSITY = 0.002
MAX_EDGE_DENSITY = 0.12
NEAR_STATIC_DIFF = 0.004
LARGE_CHANGE_DIFF = 0.25
BORDER_BAND = 0.04
BORDER_EDGE_SHARE = 0.35
ASPECT_TOLERANCE = 0.02

# kornia ``gaussian_blur2d(kernel_size=(5, 5), sigma=(1, 1))``: exp(-x^2 / 2) over x = -2..2, normalised (the pinned node's own
# kernel; it is not the binomial 1-4-6-4-1 approximation an earlier version of this preview used).
_GAUSS_1D = np.exp(-0.5 * np.arange(-2, 3, dtype=np.float32) ** 2).astype(np.float32)
_GAUSS_1D /= _GAUSS_1D.sum()
# (dy, dx) of the neighbor along the gradient for angles 0, 45, ... 315 degrees (image rows grow downward).
_NEIGHBOR_BY_OCTANT = ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1))


@dataclass(frozen=True, slots=True)
class PreviewFrame:
    label: str
    frame_index: int
    source_png: bytes
    edge_png: bytes
    edge_density: float


@dataclass(frozen=True, slots=True)
class ConditioningPreview:
    exactness: str
    exactness_reason: str
    video_path: str
    video_sha256: str
    derivative_of_sha256: str
    fps: float | None
    frame_count: int
    width: int
    height: int
    target_width: int
    target_height: int
    window_start: int
    window_frames: int
    frames: tuple[PreviewFrame, ...] = ()
    warnings: tuple[str, ...] = ()
    stats: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    advisories: tuple[ConditioningAdvisory, ...] = ()
    fidelity: dict[str, str] = field(default_factory=dict)
    operation_order: tuple[str, ...] = OPERATION_ORDER
    representation: str = ""
    workflow_key: tuple[str, str] | None = None

    @property
    def ok(self) -> bool:
        return not self.error


# ------------------------------------------------------------------ the edge detector


def _shift(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """``a`` moved by (dy, dx) with zeros shifted in."""

    out = np.zeros_like(a)
    h, w = a.shape
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = a[ys, xs]
    return out


def _blur(gray: np.ndarray) -> np.ndarray:
    padded = np.pad(gray, 2, mode="reflect")
    horizontal = sum(_GAUSS_1D[i] * padded[:, i : i + gray.shape[1]] for i in range(5))
    return np.asarray(
        sum(_GAUSS_1D[i] * horizontal[i : i + gray.shape[0], :] for i in range(5)), dtype=np.float32
    )


def canny_edges(
    gray: np.ndarray, low: float = LOW_THRESHOLD, high: float = HIGH_THRESHOLD
) -> np.ndarray:
    """Boolean edge map of a float32 grayscale image in 0..1 (hysteresis over 8-connected neighbors)."""

    if gray.ndim != 2:
        raise ValueError("canny_edges needs a 2-D grayscale image")
    blurred = _blur(gray.astype(np.float32))
    p = np.pad(
        blurred, 1, mode="edge"
    )  # kornia ``spatial_gradient`` pads with replicate; the blur above reflects
    h, w = blurred.shape

    def at(dy: int, dx: int) -> np.ndarray:
        return p[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]

    gx = (at(-1, 1) + 2 * at(0, 1) + at(1, 1)) - (at(-1, -1) + 2 * at(0, -1) + at(1, -1))
    gy = (at(1, -1) + 2 * at(1, 0) + at(1, 1)) - (at(-1, -1) + 2 * at(-1, 0) + at(-1, 1))
    magnitude = np.sqrt(gx * gx + gy * gy + 1e-6).astype(np.float32)
    angle = np.round(np.degrees(np.arctan2(gy, gx)) / 45.0).astype(np.int64) % 8
    positive = np.zeros(magnitude.shape, dtype=np.float32)
    negative = np.zeros(magnitude.shape, dtype=np.float32)
    for octant, (dy, dx) in enumerate(_NEIGHBOR_BY_OCTANT):
        mask = angle == octant
        if not mask.any():
            continue
        positive[mask] = magnitude[mask] - _shift(magnitude, -dy, -dx)[mask]
        opposite = (octant + 4) % 8
        ody, odx = _NEIGHBOR_BY_OCTANT[opposite]
        negative[mask] = magnitude[mask] - _shift(magnitude, -ody, -odx)[mask]
    is_max = np.minimum(positive, negative) > 0.0
    thin = magnitude * is_max
    weak = thin > low
    strong = thin > high
    connected = strong.copy()
    for _ in range(max(h, w)):
        grown = connected.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    grown |= _shift(connected, dy, dx)
        updated = connected | (grown & weak)
        if np.array_equal(updated, connected):
            break
        connected = updated
    return np.asarray(connected, dtype=bool)


# ------------------------------------------------------------------ PNG output (no imaging dependency)


def encode_png(pixels: np.ndarray) -> bytes:
    """Minimal PNG writer for an 8-bit gray (H,W) or RGB (H,W,3) array."""

    arr = np.ascontiguousarray(pixels.astype(np.uint8))
    color_type = 0 if arr.ndim == 2 else 2
    h, w = arr.shape[:2]
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def _downscale(a: np.ndarray, max_edge: int) -> np.ndarray:
    h, w = a.shape[:2]
    step = max(1, -(-max(h, w) // max_edge))
    return a[::step, ::step]


# ------------------------------------------------------------------ decoding


Runner = Callable[..., ProcessOutcome]


def analysis_size(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, MAX_ANALYSIS_EDGE / max(width, height))
    return max(2, int(round(width * scale / 2)) * 2), max(2, int(round(height * scale / 2)) * 2)


def sample_indices(start: int, count: int) -> list[int]:
    """First, middle, last and evenly spaced motion samples of a window, ascending and distinct."""

    if count <= 0:
        return []
    last = start + count - 1
    picks = {start, start + (count - 1) // 2, last}
    for k in range(MOTION_SAMPLES):
        picks.add(start + round(k * (count - 1) / max(1, MOTION_SAMPLES - 1)))
    return sorted(picks)


def decode_frames(
    ffmpeg: str | Path,
    video: str | Path,
    indices: Sequence[int],
    size: tuple[int, int],
    *,
    runner: Runner = run_bounded,
    cancel: threading.Event | None = None,
) -> list[np.ndarray]:
    """Decode the listed frame numbers (decode order) as RGB uint8 arrays of ``size``; bounded by size and time."""

    width, height = size
    expression = "+".join(f"eq(n\\,{i})" for i in indices)
    command = [
        str(ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-hide_banner",
        "-protocol_whitelist",
        "file",
        "-noautorotate",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"select='{expression}',scale={width}:{height}:flags=bilinear",
        "-fps_mode",
        "passthrough",
        "-frames:v",
        str(len(indices)),
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "-",
    ]
    frame_bytes = width * height * 3
    outcome = runner(
        command,
        timeout_seconds=DECODE_TIMEOUT_SECONDS,
        max_stdout_bytes=frame_bytes * len(indices) + 1,
        cancel=cancel,
    )
    if (
        outcome.returncode != 0
        or outcome.output_truncated
        or outcome.timed_out
        or outcome.cancelled
    ):
        raise RuntimeError("The video frames could not be decoded.")
    data = outcome.stdout
    if len(data) < frame_bytes * len(indices):
        raise RuntimeError("The video ended before the requested frames.")
    return [
        np.frombuffer(data, dtype=np.uint8, count=frame_bytes, offset=k * frame_bytes).reshape(
            height, width, 3
        )
        for k in range(len(indices))
    ]


def center_crop_to_aspect(rgb: np.ndarray, target_width: int, target_height: int) -> np.ndarray:
    """Crop ``rgb`` to the target aspect around its center, as ComfyUI's ``common_upscale(..., "center")`` does.

    The pinned Fun Control node crops each frame this way and then scales it, so the previewed edges are taken from the same
    region.  The offsets use the node's own arithmetic (Python ``round`` of the half difference).
    """

    height, width = rgb.shape[:2]
    old_aspect, new_aspect = width / height, target_width / target_height
    x = y = 0
    if old_aspect > new_aspect:
        x = round((width - width * (new_aspect / old_aspect)) / 2)
    elif old_aspect < new_aspect:
        y = round((height - height * (old_aspect / new_aspect)) / 2)
    return rgb[y : height - y, x : width - x]


def _gray(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(
        np.float32
    ) / 255.0


# ------------------------------------------------------------------ heuristics


def advisory_warnings(
    *,
    densities: Sequence[float],
    border_shares: Sequence[float],
    motion_diffs: Sequence[float],
    video_aspect: float,
    target_aspect: float,
    reference_iou: float | None,
    downscaled: bool,
) -> tuple[str, ...]:
    """Bounded, honest heuristics (never a score, never a refusal)."""

    notes: list[str] = [EXACTNESS_REASON]
    if downscaled:
        notes.append("Analyzed at a reduced size; the graph runs Canny on the full-size frames.")
    if densities and max(densities) < MIN_EDGE_DENSITY:
        notes.append(
            "Very few edges were found; the subject may be too faint or small to guide motion."
        )
    if densities and min(densities) > MAX_EDGE_DENSITY:
        notes.append(
            "Edges are very dense, which often means a busy or textured background competing with the subject."
        )
    if border_shares and max(border_shares) > BORDER_EDGE_SHARE:
        notes.append(
            "Much of the edge detail touches the frame border; the subject may be cropped."
        )
    if motion_diffs:
        if max(motion_diffs) < NEAR_STATIC_DIFF:
            notes.append("The sampled frames barely differ; the motion may be near static.")
        if max(motion_diffs) > LARGE_CHANGE_DIFF:
            notes.append(
                "Large frame-to-frame change between samples; this can be camera movement or a cut."
            )
    if (
        video_aspect > 0
        and target_aspect > 0
        and abs(video_aspect / target_aspect - 1.0) > ASPECT_TOLERANCE
    ):
        notes.append(
            "The video's shape differs from the generation shape; each frame is center-cropped to it, "
            "so anything near the cropped sides is lost."
        )
    if reference_iou is not None and reference_iou < 0.5:
        notes.append(
            "The subject's edge outline barely overlaps the reference image's; expect a position or scale mismatch."
        )
    return tuple(notes)


def _bbox(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    h, w = mask.shape
    return xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def resize_bilinear(a: np.ndarray, width: int, height: int) -> np.ndarray:
    """``a`` (H, W) resized like ``torch.nn.functional.interpolate(mode="bilinear", align_corners=False)`` (no antialiasing)."""

    h, w = a.shape
    if (w, h) == (width, height):
        return a.astype(np.float32)

    def axis(size_in: int, size_out: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        coord = np.maximum(
            (np.arange(size_out, dtype=np.float32) + 0.5) * (size_in / size_out) - 0.5, 0.0
        )
        low = np.minimum(coord.astype(np.int64), size_in - 1)
        high = np.minimum(low + 1, size_in - 1)
        return low, high, (coord - low).astype(np.float32)

    y0, y1, wy = axis(h, height)
    x0, x1, wx = axis(w, width)
    af = a.astype(np.float32)
    top = af[y0][:, x0] * (1 - wx) + af[y0][:, x1] * wx
    bottom = af[y1][:, x0] * (1 - wx) + af[y1][:, x1] * wx
    return np.asarray(top * (1 - wy)[:, None] + bottom * wy[:, None], dtype=np.float32)


def conditioned_view(edges: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    """What follows Canny in the graph: centre-crop the edge image to the target aspect, then bilinear resize to it."""

    cropped = center_crop_to_aspect(edges.astype(np.float32), target_size[0], target_size[1])
    return resize_bilinear(cropped, target_size[0], target_size[1])


def build_preview(
    video: str | Path,
    *,
    ffmpeg: str | Path,
    facts: Any,
    target_size: tuple[int, int],
    video_sha256: str = "",
    derivative_of_sha256: str = "",
    window_start: int = 0,
    window_frames: int = 0,
    reference_rgb: np.ndarray | None = None,
    runner: Runner = run_bounded,
    cancel: threading.Event | None = None,
    contract: ConditioningContract | None = None,
    representation: str | None = None,
    generation_frames: int | None = None,
    driver_viewpoint: str = "",
    source_viewpoint: str = "",
    motion_category: str = "",
    file_bytes: int | None = None,
) -> ConditioningPreview:
    """Preview ``window_frames`` frames from ``window_start`` of ``video`` (``facts`` from the existing inspector).

    ``video`` should be the *effective* driving clip (the prepared or aligned derivative the job would consume).  ``contract``,
    ``representation`` and the remaining keywords only add labelled context advisories; they never change the detector."""

    total = int(getattr(facts, "frame_count", 0) or 0)
    width, height = int(facts.display_width), int(facts.display_height)
    fps = getattr(facts, "reported_fps", None)
    fidelity = {
        "source_frame": FIDELITY_SOURCE,
        "prepared_driving_frame": FIDELITY_PREPARED,
        "conditioning": FIDELITY_CONDITIONING,
    }
    workflow_key = contract.key if contract is not None else None

    def failed(message: str) -> ConditioningPreview:
        return ConditioningPreview(
            EXACTNESS_APPROXIMATE,
            EXACTNESS_REASON,
            str(video),
            video_sha256,
            derivative_of_sha256,
            fps,
            total,
            width,
            height,
            target_size[0],
            target_size[1],
            window_start,
            window_frames,
            error=message,
            fidelity=fidelity,
            representation=representation or "",
            workflow_key=workflow_key,
        )

    if total <= 0:
        return failed("The video's frame count is unknown, so a window cannot be previewed.")
    count = window_frames or total - window_start
    if window_start < 0 or count <= 0 or window_start + count > total:
        return failed(f"The window ({window_start}+{count}) is outside the video's {total} frames.")
    size = analysis_size(width, height)
    indices = sample_indices(window_start, count)
    try:
        decoded = decode_frames(ffmpeg, video, indices, size, runner=runner, cancel=cancel)
    except RuntimeError as exc:
        return failed(str(exc))

    # Graph order: edges on the whole frame first, then crop and resize.  Statistics are taken on the cropped region because
    # that is what the model receives.
    gray_frames = [_gray(f) for f in decoded]
    full_edges = [canny_edges(g) for g in gray_frames]
    crops = [center_crop_to_aspect(f, target_size[0], target_size[1]) for f in decoded]
    edges = [center_crop_to_aspect(e, target_size[0], target_size[1]) for e in full_edges]
    cropped_gray = [center_crop_to_aspect(g, target_size[0], target_size[1]) for g in gray_frames]
    size = (crops[0].shape[1], crops[0].shape[0])
    densities = [float(e.mean()) for e in edges]
    band_h, band_w = max(1, int(size[1] * BORDER_BAND)), max(1, int(size[0] * BORDER_BAND))
    shares = []
    for e in edges:
        total_edges = float(e.sum())
        border = e.copy()
        border[band_h:-band_h, band_w:-band_w] = False
        shares.append(float(border.sum()) / total_edges if total_edges else 0.0)
    gray_small = [_downscale(g, 160) for g in cropped_gray]
    diffs = [
        float(np.abs(gray_small[i + 1] - gray_small[i]).mean()) for i in range(len(gray_small) - 1)
    ]
    iou = None
    if reference_rgb is not None:
        ref_edges = canny_edges(
            _gray(center_crop_to_aspect(reference_rgb, target_size[0], target_size[1]))
        )
        box_ref, box_first = _bbox(ref_edges), _bbox(edges[0])
        iou = _iou(box_ref, box_first) if box_ref and box_first else None

    chosen = {indices[0]: "First", indices[len(indices) // 2]: "Middle", indices[-1]: "Last"}
    out_frames: list[PreviewFrame] = []
    for index, label in sorted(chosen.items()):
        slot = indices.index(index)
        edge_img = _downscale(
            (conditioned_view(full_edges[slot], target_size) * 255).astype(np.uint8),
            MAX_PREVIEW_EDGE,
        )
        src_img = _downscale(crops[slot], MAX_PREVIEW_EDGE)
        out_frames.append(
            PreviewFrame(label, index, encode_png(src_img), encode_png(edge_img), densities[slot])
        )
    advisories = (
        ConditioningAdvisory("exactness", EXACTNESS_REASON, BASIS_HEURISTIC),
        *adv.frame_advisories(
            densities=densities,
            border_shares=shares,
            motion_diffs=diffs,
            gray_frames=cropped_gray,
            edge_frames=edges,
            video_aspect=width / height,
            target_aspect=target_size[0] / target_size[1],
            reference_iou=iou,
            downscaled=analysis_size(width, height) != (width, height),
            min_density=MIN_EDGE_DENSITY,
            max_density=MAX_EDGE_DENSITY,
            border_edge_share=BORDER_EDGE_SHARE,
            near_static=NEAR_STATIC_DIFF,
            large_change=LARGE_CHANGE_DIFF,
            aspect_tolerance=ASPECT_TOLERANCE,
        ),
        *adv.preparation_advisories(
            contract=contract,
            width=width,
            height=height,
            frames=count,
            target_size=target_size,
            file_bytes=file_bytes,
        ),
        *adv.context_advisories(
            contract=contract,
            representation=representation,
            window_frames=count,
            generation_frames=generation_frames,
            driver_viewpoint=driver_viewpoint,
            source_viewpoint=source_viewpoint,
            motion_category=motion_category,
        ),
    )
    return ConditioningPreview(
        EXACTNESS_EXACT if EXACT_PARITY_VERIFIED else EXACTNESS_APPROXIMATE,
        EXACTNESS_REASON,
        str(video),
        video_sha256,
        derivative_of_sha256,
        fps,
        total,
        width,
        height,
        target_size[0],
        target_size[1],
        window_start,
        count,
        tuple(out_frames),
        adv.advisory_texts(advisories),
        {
            "thresholds": {"low": LOW_THRESHOLD, "high": HIGH_THRESHOLD},
            "analysis_size": list(size),
            "sampled_frames": indices,
            "edge_density": densities,
            "mean_sample_difference": diffs,
            "operation_order": list(OPERATION_ORDER),
        },
        advisories=advisories,
        fidelity=fidelity,
        representation=representation or "",
        workflow_key=workflow_key,
    )

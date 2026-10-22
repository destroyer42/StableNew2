"""Frame-level helpers of a sequence job: the exact final frame, overlap trimming, opt-in colour matching and the
hash-verified copy a resumed run uses (PR-VID-SEQ-330-CORE).

The carried anchor is always a lossless PNG with a recorded SHA-256, never a video path. Where it comes from, in order of
preference, and what is recorded about it:

* ``native``: a frame the backend produced before any encode or smoothing. For a frames-out Comfy workflow this is the last
  PNG Comfy saved (byte-identical, hash cross-checked against the backend's own record). For native SVD it is the last
  generated frame, saved before RIFE, loop export or upscaling.
* ``decoded``: the workflow ends in an encoded clip and offers no frames, so the frames are decoded back out of it. The
  record says so, and the decode is validated (the decoded count must equal the count the segment was admitted with)
  before it is trusted.

Colour matching is a pure, deterministic transform applied to a later segment's *assembly* frames only, never to the
carried anchor or to the ledger's original frames (see ``match_segment_colors``).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.video import VideoEncodeCancelled, resolve_ffmpeg_executable, run_ffmpeg
from src.video.frames_out import natural_frame_order
from src.video.sequence_ledger import (
    BASIS_DECODED,
    BASIS_NATIVE,
    FileHasher,
    FileRecord,
    FinalFrame,
    sha256_of,
)

DECODE_TIMEOUT_SECONDS = 600.0
#: A decoded fallback is bounded: the longest legal segment is 81 frames.
MAX_DECODED_FRAMES = 400

ClipDecoder = Callable[[Path, Path, "CancelToken | None"], list[Path]]


class SequenceFrameError(RuntimeError):
    """A segment's frames or final frame cannot be established; the sequence stops rather than guess."""


@dataclass(frozen=True, slots=True)
class SegmentArtifacts:
    """What one finished segment left: its frames in playback order, its exact final frame, clip and manifest."""

    frames: tuple[Path, ...]
    final_frame: FinalFrame
    clip: Path | None
    processing: Mapping[str, Any] = field(default_factory=dict)
    manifest: Path | None = None


def trim_overlap[T](frames: Sequence[T], overlap_frames: int) -> list[T]:
    """Drop the first ``overlap_frames`` frames (they re-render the carried anchor); order is preserved."""

    if overlap_frames < 0:
        raise SequenceFrameError("overlap_frames must not be negative")
    if overlap_frames >= len(frames):
        raise SequenceFrameError(
            f"overlap_frames ({overlap_frames}) leaves no frame of a {len(frames)}-frame segment"
        )
    return list(frames[overlap_frames:])


def copy_verified(
    source: Path,
    target: Path,
    *,
    expected_sha256: str,
    hash_file: FileHasher = sha256_of,
) -> FileRecord:
    """Copy ``source`` to ``target`` and prove both ends equal ``expected_sha256`` (a real copy, never a link)."""

    if not source.is_file():
        raise SequenceFrameError(f"{source.name} is missing")
    if hash_file(source) != expected_sha256:
        raise SequenceFrameError(f"{source.name} changed since it was recorded")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    record = FileRecord.of(target, hash_file=hash_file)
    if record.sha256 != expected_sha256:
        target.unlink(missing_ok=True)
        raise SequenceFrameError(f"the copy of {source.name} does not match its recorded hash")
    return record


def require_png(path: Path, *, label: str) -> tuple[int, int]:
    """The size of ``path`` when it is a decodable PNG; anything else (missing, corrupt, another format) is refused."""

    if not path.is_file():
        raise SequenceFrameError(f"{label} is missing: {path}")
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise SequenceFrameError(f"{label} {path.name} is {image.format}, not a PNG still")
            image.load()
            width, height = image.size
        return int(width), int(height)
    except SequenceFrameError:
        raise
    except Exception as exc:  # noqa: BLE001 - a corrupt file is a refusal with a reason
        raise SequenceFrameError(f"{label} {path.name} is not a readable image: {exc}") from exc


def require_still(path: Path, *, label: str) -> tuple[int, int]:
    """The size of ``path`` when it decodes as a still image (any supported format); otherwise refused."""

    if not path.is_file():
        raise SequenceFrameError(f"{label} is missing: {path}")
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
        return int(width), int(height)
    except Exception as exc:  # noqa: BLE001 - a corrupt file is a refusal with a reason
        raise SequenceFrameError(f"{label} {path.name} is not a readable image: {exc}") from exc


def _final_from_native_png(
    source: Path, target: Path, *, detail: Mapping[str, Any], expected_sha256: str | None
) -> FinalFrame:
    require_png(source, label="the segment's final frame")
    actual = sha256_of(source)
    if expected_sha256 is not None and actual != expected_sha256:
        raise SequenceFrameError(
            f"the final frame {source.name} does not match the hash its backend recorded"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    record = FileRecord.of(target)
    if record.sha256 != actual:
        target.unlink(missing_ok=True)
        raise SequenceFrameError("the carried anchor is not byte-identical to the final frame")
    width, height = require_png(target, label="the carried anchor")
    return FinalFrame(
        file=record,
        basis=BASIS_NATIVE,
        detail={**detail, "source": str(source), "size": [width, height]},
    )


def decode_clip_to_frames(
    clip: Path, out_dir: Path, cancel_token: CancelToken | None = None
) -> list[Path]:
    """Decode every frame of an encoded clip to PNG (the explicit, bounded fallback)."""

    ffmpeg = resolve_ffmpeg_executable()
    if ffmpeg is None:
        raise SequenceFrameError("FFmpeg is not available to decode the clip's frames")
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(ffmpeg),
        "-v",
        "error",
        "-i",
        str(clip),
        "-fps_mode",
        "passthrough",
        "-y",
        str(out_dir / "d_%06d.png"),
    ]
    try:
        completed = run_ffmpeg(
            command,
            timeout_seconds=DECODE_TIMEOUT_SECONDS,
            cancel=None if cancel_token is None else cancel_token.is_cancelled,
        )
    except VideoEncodeCancelled as exc:
        raise CancellationError("sequence frame decode cancelled") from exc
    if completed.returncode != 0:
        raise SequenceFrameError(
            f"FFmpeg could not decode {clip.name}: {completed.stderr.strip()[:300]}"
        )
    frames = natural_frame_order(sorted(out_dir.glob("d_*.png")))
    if not frames:
        raise SequenceFrameError(f"FFmpeg decoded no frames from {clip.name}")
    if len(frames) > MAX_DECODED_FRAMES:
        raise SequenceFrameError(
            f"{clip.name} has {len(frames)} frames; the decoded fallback handles {MAX_DECODED_FRAMES}"
        )
    return [Path(frame) for frame in frames]


def _expected_svd_exported_frames(
    raw_result: Mapping[str, Any], generated: int, segment_index: int
) -> int:
    """How many frames native SVD must have saved for ``generated`` frames, from what its postprocess says it did.

    Face restoration and upscaling keep the count; duration-preserving RIFE multiplies it. Loop and extended exports
    are refused at admission, so nothing else changes the count. Interpolation that does not say its multiplier cannot
    be checked and is refused rather than trusted."""

    postprocess = raw_result.get("postprocess")
    applied = list(postprocess.get("applied") or ()) if isinstance(postprocess, Mapping) else []
    if "interpolation" not in applied:
        return generated
    interpolation = postprocess.get("interpolation") if isinstance(postprocess, Mapping) else None
    multiplier = interpolation.get("multiplier") if isinstance(interpolation, Mapping) else None
    if not isinstance(multiplier, int) or isinstance(multiplier, bool) or multiplier < 2:
        raise SequenceFrameError(
            f"segment {segment_index}: interpolation was applied but its record does not say how many frames "
            "it produces, so the saved frames cannot be checked"
        )
    return generated * multiplier


def collect_segment_artifacts(
    raw_result: Mapping[str, Any],
    *,
    segment_index: int,
    expected_frame_count: int,
    run_dir: Path,
    decode_clip: ClipDecoder = decode_clip_to_frames,
    cancel_token: CancelToken | None = None,
) -> SegmentArtifacts:
    """Establish a finished segment's frames and exact final frame from its backend result.

    ``raw_result`` is the backend's variant payload. A native SVD result carries ``native_final_frame``; a frames-out
    Comfy result carries ``frames_out`` and its ordered ``frame_paths``; anything else must offer an encoded clip.
    """

    anchors = run_dir / "sequence" / "anchors"
    target = anchors / f"seg_{segment_index:02d}_last.png"
    native = raw_result.get("native_final_frame")
    frames_out = raw_result.get("frames_out")
    video_paths = [str(item) for item in raw_result.get("video_paths") or () if item]
    clip_text = str(raw_result.get("video_path") or (video_paths[0] if video_paths else "") or "")
    clip_path = Path(clip_text) if clip_text and Path(clip_text).is_file() else None
    frame_paths = [Path(str(item)) for item in raw_result.get("frame_paths") or () if item]
    manifest_text = str(raw_result.get("manifest_path") or "")
    manifest = Path(manifest_text) if manifest_text and Path(manifest_text).is_file() else None

    if isinstance(native, Mapping) and native.get("path"):
        if not frame_paths:
            raise SequenceFrameError(
                f"segment {segment_index}: native SVD saved no frames for the assembly "
                "(sequence segments must save their frames)"
            )
        generated = int(native.get("frame_index") or 0) + 1
        if generated != expected_frame_count:
            raise SequenceFrameError(
                f"segment {segment_index}: native SVD generated {generated} frames but the segment was "
                f"admitted with {expected_frame_count}; the sequence does not continue from a different length"
            )
        exported = _expected_svd_exported_frames(raw_result, generated, segment_index)
        if len(frame_paths) != exported:
            raise SequenceFrameError(
                f"segment {segment_index}: native SVD saved {len(frame_paths)} frames but its {generated} generated "
                f"frames and postprocess give {exported}; the sequence does not continue from an incomplete set"
            )
        final = _final_from_native_png(
            Path(str(native["path"])),
            target,
            detail={
                "origin": "svd_native_pre_postprocess",
                "frame_index": native.get("frame_index"),
            },
            expected_sha256=str(native.get("sha256") or "") or None,
        )
        return SegmentArtifacts(
            tuple(natural_frame_order(frame_paths)),
            final,
            clip_path,
            {
                "backend": "svd_native",
                "postprocess": raw_result.get("postprocess"),
                "native_frame_count": generated,
                "expected_exported_frames": exported,
            },
            manifest,
        )

    if isinstance(frames_out, Mapping) and frame_paths:
        ordered = [Path(item) for item in natural_frame_order(frame_paths)]
        if len(ordered) != expected_frame_count:
            raise SequenceFrameError(
                f"segment {segment_index}: the workflow saved {len(ordered)} frames but the segment was "
                f"admitted with {expected_frame_count}; the sequence does not continue from a different length"
            )
        recorded = [str(item) for item in frames_out.get("frame_sha256") or ()]
        if recorded and (
            len(recorded) != len(ordered)
            or any(
                sha256_of(path) != digest for path, digest in zip(ordered, recorded, strict=True)
            )
        ):
            raise SequenceFrameError(
                f"segment {segment_index}: a saved frame no longer matches the hash the backend recorded for it"
            )
        recorded_last = str(frames_out.get("last_frame_path") or "")
        if recorded_last and Path(recorded_last).resolve() != ordered[-1].resolve():
            raise SequenceFrameError(
                f"segment {segment_index}: the backend's last frame is not the last of its frame list"
            )
        final = _final_from_native_png(
            ordered[-1],
            target,
            detail={"origin": "comfy_frames_out"},
            expected_sha256=str(frames_out.get("last_frame_sha256") or "") or None,
        )
        return SegmentArtifacts(
            tuple(ordered),
            final,
            clip_path,
            {
                "backend": "comfy",
                "frames_out": {
                    k: v for k, v in frames_out.items() if k not in ("frame_sha256", "frame_paths")
                },
            },
            manifest,
        )

    if clip_path is None:
        raise SequenceFrameError(
            f"segment {segment_index} produced neither frames nor a clip, so no final frame can be taken"
        )
    decoded_dir = run_dir / "sequence" / "decoded" / f"seg_{segment_index:02d}"
    decoded = decode_clip(clip_path, decoded_dir, cancel_token)
    if len(decoded) != expected_frame_count:
        raise SequenceFrameError(
            f"segment {segment_index}: decoding {clip_path.name} gave {len(decoded)} frames but the segment was "
            f"admitted with {expected_frame_count}; the decoded fallback is refused rather than trusted"
        )
    with Image.open(decoded[-1]) as image:
        size = image.size
    final = _final_from_native_png(
        decoded[-1],
        target,
        detail={},
        expected_sha256=None,
    )
    final = FinalFrame(
        file=final.file,
        basis=BASIS_DECODED,
        detail={
            "origin": "decoded_from_clip",
            "clip": str(clip_path),
            "clip_sha256": sha256_of(clip_path),
            "decoded_frame_count": len(decoded),
            "expected_frame_count": expected_frame_count,
            "size": list(size),
        },
    )
    return SegmentArtifacts(
        tuple(decoded), final, clip_path, {"backend": "comfy", "decoded": True}, manifest
    )


# --------------------------------------------------------------------------- opt-in colour matching


def _histograms(paths: Sequence[Path]) -> np.ndarray:
    """Pooled per-channel 256-bin counts of every pixel of every frame, shape ``(3, 256)``."""

    counts = np.zeros((3, 256), dtype=np.int64)
    for path in paths:
        with Image.open(path) as image:
            pixels = np.asarray(image.convert("RGB"))
        for channel in range(3):
            counts[channel] += np.bincount(pixels[:, :, channel].ravel(), minlength=256)
    return counts


def color_match_luts(source_counts: np.ndarray, reference_counts: np.ndarray) -> np.ndarray:
    """One integer LUT per channel mapping the source histogram onto the reference's (exact integer arithmetic).

    ``lut[c][v]`` is the smallest reference value ``r`` whose cumulative share is at least that of ``v``; the shares
    are compared by cross-multiplying the cumulative counts, so the result is identical on every platform.
    """

    luts = np.zeros((3, 256), dtype=np.uint8)
    for channel in range(3):
        src_cum = np.cumsum(source_counts[channel])
        ref_cum = np.cumsum(reference_counts[channel])
        src_total = int(src_cum[-1])
        ref_total = int(ref_cum[-1])
        if src_total == 0 or ref_total == 0:
            raise SequenceFrameError("cannot colour-match an empty frame set")
        mapped = np.searchsorted(ref_cum * src_total, src_cum * ref_total, side="left")
        luts[channel] = np.clip(mapped, 0, 255).astype(np.uint8)
    return luts


def match_segment_colors(
    frames: Sequence[Path],
    reference_frame: Path,
    out_dir: Path,
    *,
    hash_file: FileHasher = sha256_of,
    cancel_token: CancelToken | None = None,
) -> list[FileRecord]:
    """Write colour-matched copies of ``frames`` to ``out_dir`` and return their records, in order.

    The contract: one lookup table per channel per segment, built from the segment's pooled histogram and the
    reference frame's histogram, applied to every frame of the segment. Segment 0's own frames are never matched (they
    are the reference), and the originals, the carried anchor and the ledger's frame list are never altered.
    """

    if not frames:
        return []
    luts = color_match_luts(_histograms(frames), _histograms([reference_frame]))
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[FileRecord] = []
    for position, path in enumerate(frames):
        if cancel_token is not None and cancel_token.is_cancelled():
            raise CancellationError("sequence colour matching cancelled")
        with Image.open(path) as image:
            pixels = np.asarray(image.convert("RGB"))
        matched = np.stack([luts[channel][pixels[:, :, channel]] for channel in range(3)], axis=2)
        target = out_dir / f"m_{position:06d}.png"
        Image.fromarray(matched, mode="RGB").save(target, format="PNG", compress_level=1)
        records.append(FileRecord.of(target, hash_file=hash_file))
    return records


__all__ = [
    "SegmentArtifacts",
    "SequenceFrameError",
    "collect_segment_artifacts",
    "require_png",
    "require_still",
    "color_match_luts",
    "copy_verified",
    "decode_clip_to_frames",
    "match_segment_colors",
    "trim_overlap",
]

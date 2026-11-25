"""Prepare the driving frames a workflow will consume with one explicit spatial alignment (PR-VID-MOTION-420).

``prepare_aligned_motion_source`` is the aligned sibling of ``prepare_motion_source`` (PR-VID-MOTION-210).  It
reuses that module's frame planner (``MotionSourceSettings`` / ``build_frame_plan``: which source frame becomes
each consumed frame), its bounded, cancellable process runner, its content-addressed publication directory and
its stale-temporary rules; it adds one spatial step that is *not* a frame-identity copy:

1. probe the clip, resolve the prepared source image's target frame and the constant transform
   (``motion_alignment``);
2. decode the window once with ``framemd5`` to learn how many frames exist, then build the plan;
3. decode only the planned *unique* source frames to private PNGs (display orientation, RGB);
4. transform each unique frame with ``transform_frame`` and write the planned output frames as PNGs;
5. encode them once, losslessly (RGB, H.264 ``-qp 0``), to a private temporary file;
6. decode that file again and require every frame's fingerprint to equal the fingerprint of the in-memory
   transformed frame it must hold (exact equality against the declared transform, not a tolerance);
7. hash, publish atomically under ``prepared_driving_videos/<sha256>.mp4`` and record everything.

Frame order, count and timing come from the plan alone; the transform is the same for every frame (no
per-frame centring, scaling or cropping).  The derivative is **not** pixel-identical to the original frames --
it is the declared transform of them -- and the record says so.  Nothing here queues, builds an NJR or touches a
GUI; the original and any earlier preparation stay untouched.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import PIL
from PIL import Image

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.driving_video_inspection import (
    STATUS_FAILED,
    DrivingVideoFacts,
    DrivingVideoInspection,
    ProcessRunner,
    inspect_driving_video,
    run_bounded_process,
)
from src.video.motion_alignment import (
    COORDINATE_SYSTEM,
    IDENTITY,
    TRANSFORM_VERSION,
    AlignmentError,
    AlignmentIntent,
    FrameSize,
    ResolvedAlignment,
    alignment_from_record,
    resolve_alignment,
    transform_frame,
)
from src.video.motion_alignment import (
    SCHEMA as ALIGNMENT_SCHEMA,
)
from src.video.motion_alignment_support import alignment_support
from src.video.motion_source_plan import (
    FramePlan,
    MotionSourceContract,
    MotionSourceSettings,
    MotionSourceUnavailable,
    build_frame_plan,
    explain_plan,
    last_source_frame_needed,
    motion_source_contract,
    source_rate,
)
from src.video.motion_source_preparation import (
    _DRIVING_SUFFIXES,
    _TEMP_PREFIX,
    MAX_MD5_STDOUT_BYTES,
    MAX_PREPARED_BYTES,
    MAX_VERSION_STDOUT_BYTES,
    PREPARED_SUFFIX,
    STALE_TEMP_SECONDS,
    STATUS_CANCELLED,
    STATUS_FAILED_PREPARATION,
    STATUS_PREPARED,
    MotionSourceRequest,
    PreparationOutcome,
    PreparedMotionSourceError,
    _copy,
    _ffmpeg_version,
    _mapping,
    _preview_indices,
    _rate_text,
    _resolve_settings,
    _Run,
    _Stop,
    build_file_md5_command,
    build_window_md5_command,
    parse_framemd5,
    prepared_destination,
    prepared_directory,
    sha256_file,
    target_pixel_format,
)
from src.video.workflow_source_preparation import (
    TransformedWorkflowSource,
    transform_declared_workflow_source,
)

ALIGNED_SCHEMA = "stablenew.motion-alignment-preparation.v1"
ALIGNED_VIDEO_CODEC = "libx264rgb"
ALIGNED_PIXEL_FORMAT = "rgb24"
IMPLEMENTATION = "stablenew.motion-alignment-prep.v1"
_WORK_PREFIX = ".aligning-"

# --- bounds (named and tested) --------------------------------------------------------------------------
#: Largest decoded driving frame the aligned path accepts (about 4K); each frame passes through a PNG.
MAX_ALIGN_FRAME_PIXELS = 9_000_000
#: ``select`` expressions nest one level per term; the same limit the plan's own filter chain respects.
MAX_UNIQUE_SOURCE_FRAMES = 96
PREVIEW_FRAME_LIMIT = 12
#: A preview keeps its decoded driving frames in memory; this many pixels (about 180 MB of RGB) is the most it holds.
PREVIEW_PIXEL_BUDGET = 60_000_000
_PNG_LEVEL = 1  # PNG here is only a lossless hand-off; a low level keeps decoding fast


class AlignedPreparationError(PreparedMotionSourceError):
    """An aligned prepared-motion record does not match the files or the form it claims to describe."""


# --- pure helpers -----------------------------------------------------------------------------------------


def _runs(indices: Sequence[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for index in indices:
        if runs and index == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


def build_extract_command(
    ffmpeg: str | Path, video: str | Path, unique: Sequence[int], directory: str | Path
) -> list[str]:
    """Decode exactly the planned unique source frames to ``directory/src_%05d.png`` (display orientation)."""

    selection = "+".join(f"between(n,{low},{high})" for low, high in _runs(unique))
    return [
        str(ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-hide_banner",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"select='{selection}'",
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        ALIGNED_PIXEL_FORMAT,
        "-compression_level",
        str(_PNG_LEVEL),
        "-start_number",
        "0",
        "-y",
        str(Path(directory) / "src_%05d.png"),
    ]


def build_encode_command(
    ffmpeg: str | Path, directory: str | Path, rate: Fraction, frames: int, destination: str | Path
) -> list[str]:
    """Encode ``directory/out_%05d.png`` as one lossless RGB MP4 of exactly ``frames`` frames."""

    return [
        str(ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-hide_banner",
        "-protocol_whitelist",
        "file",
        "-framerate",
        f"{rate.numerator}/{rate.denominator}",
        "-start_number",
        "0",
        "-i",
        str(Path(directory) / "out_%05d.png"),
        "-an",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-frames:v",
        str(frames),
        "-c:v",
        ALIGNED_VIDEO_CODEC,
        "-qp",
        "0",
        "-preset",
        "medium",
        "-threads",
        "1",
        "-pix_fmt",
        ALIGNED_PIXEL_FORMAT,
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-fs",
        str(MAX_PREPARED_BYTES + 1),
        "-y",
        "-f",
        "mp4",
        str(destination),
    ]


def temporal_plan_sha256(record: Mapping[str, Any]) -> str:
    """Identity of *which source frames become which consumed frames* for an aligned or unaligned record.

    The same digest for the aligned and the unaligned preparation of one window, so a comparison can prove
    the temporal selection did not change while the spatial intervention did."""

    plan = _mapping(record.get("plan"))
    settings = _mapping(record.get("settings"))
    payload = {
        "source_indices": list(plan.get("source_indices") or ()),
        "output_fps": plan.get("output_fps"),
        "start_frame": settings.get("start_frame"),
        "end_frame": settings.get("end_frame"),
        "fps_conversion": settings.get("fps_conversion"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def is_aligned_record(record: Any) -> bool:
    return isinstance(record, Mapping) and record.get("schema") == ALIGNED_SCHEMA


def alignment_explanation(resolved: ResolvedAlignment, plan: FramePlan) -> tuple[str, ...]:
    """Operator-facing sentences for what the alignment does (frame numbers start at 0)."""

    intent = resolved.intent
    clipped = [name for name, hit in resolved.clipped.items() if hit]
    lines = [
        f"Alignment: scale {intent.scale:g}, shifted ({intent.translate_x:+g}, {intent.translate_y:+g}) px "
        f"in the {resolved.target.width}x{resolved.target.height} frame, "
        + (
            "mirrored left-to-right (motion direction and left/right are reversed)."
            if intent.mirror
            else "not mirrored."
        )
        + f" The same transform is applied to all {plan.output_frames} consumed frames.",
        f"Coverage: {resolved.driver_visible_fraction:.0%} of the driving frame stays in view"
        + (f" (cropped at the {', '.join(clipped)})" if clipped else "")
        + f"; {resolved.fill_fraction:.0%} of the target frame is constant neutral gray fill "
        "(nothing is generated or extended).",
        "Not pixel-identical to the source frames: each frame is the declared transform of its selected "
        "source frame (Lanczos resampling), stored losslessly as RGB.",
    ]
    return tuple(lines)


# --- shared first half: probe, resolve, plan -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlignedMotionRequest:
    """One aligned preparation or preview: the clip, the registered contract, the window and the alignment."""

    clip_path: str
    contract: MotionSourceContract
    source_image_path: str
    source_policy: Mapping[str, Any]
    intent: AlignmentIntent = IDENTITY
    start: float = 0.0
    end: float | None = None
    unit: str = "seconds"
    fps_conversion: str = "none"

    def window(self) -> MotionSourceRequest:
        return MotionSourceRequest(
            clip_path=self.clip_path,
            contract=self.contract,
            start=self.start,
            end=self.end,
            unit=self.unit,
            fps_conversion=self.fps_conversion,
        )


@dataclass(slots=True)
class _Prepared:
    clip: Path
    executable: str | Path
    facts: DrivingVideoFacts
    source: TransformedWorkflowSource
    driver: FrameSize
    target: FrameSize
    resolved: ResolvedAlignment
    baseline: ResolvedAlignment
    settings: MotionSourceSettings
    rate: Fraction | None
    plan: FramePlan
    window_md5: list[str]
    pixel_format: str
    original_sha: str
    original_size: int
    original_mtime_ns: int


def _stop_from_alignment(exc: AlignmentError) -> _Stop:
    return _Stop(STATUS_FAILED_PREPARATION, exc.code, exc.message)


def _plan_aligned(
    request: AlignedMotionRequest,
    run: _Run,
    *,
    ffmpeg: str | Path | None,
    ffprobe: str | Path | None,
    inspect: Callable[..., DrivingVideoInspection],
    cancel: threading.Event | None,
    runner: ProcessRunner,
) -> _Prepared:
    run.check()
    clip = Path(str(request.clip_path or "").strip()).expanduser()
    if not clip.is_file():
        raise _Stop(
            STATUS_FAILED_PREPARATION, "file_missing", f"Driving video does not exist: {clip}"
        )
    if clip.suffix.lower() not in _DRIVING_SUFFIXES:
        raise _Stop(
            STATUS_FAILED_PREPARATION,
            "unsupported_file",
            f"Driving video must be one of {', '.join(sorted(_DRIVING_SUFFIXES))}: {clip}",
        )
    clip = clip.resolve()
    executable = ffmpeg if ffmpeg is not None else resolve_ffmpeg_executable()
    if executable is None:
        raise _Stop(
            STATUS_FAILED_PREPARATION,
            "ffmpeg_unavailable",
            "FFmpeg was not found. Install FFmpeg or set STABLENEW_FFMPEG_PATH.",
        )
    probe = inspect(
        clip, runner=runner, ffprobe=ffprobe, ffmpeg=executable, frame_count=0, cancel=cancel
    )
    if probe.status == STATUS_FAILED or probe.facts is None:
        if cancel is not None and cancel.is_set():
            raise _Stop(STATUS_CANCELLED, "cancelled", "Preparation was cancelled.")
        reason = probe.issues[0].message if probe.issues else "The clip could not be read."
        raise _Stop(STATUS_FAILED_PREPARATION, "probe_failed", reason)
    facts = probe.facts
    if facts.display_width * facts.display_height > MAX_ALIGN_FRAME_PIXELS:
        raise _Stop(
            STATUS_FAILED_PREPARATION,
            "frame_too_large",
            f"Frames are {facts.display_width}x{facts.display_height}; alignment is limited to "
            f"{MAX_ALIGN_FRAME_PIXELS / 1e6:.1f} megapixels per frame.",
        )
    pixel_format = target_pixel_format(facts.pixel_format)
    if pixel_format is None:
        raise _Stop(
            STATUS_FAILED_PREPARATION,
            "unsupported_pixel_format",
            f"The clip's pixel format ({facts.pixel_format or 'unknown'}) is not supported. Re-encode "
            "the clip to a standard 4:2:0 or 4:2:2 format first.",
        )
    try:
        source = transform_declared_workflow_source(
            source_path=request.source_image_path, policy=request.source_policy
        )
    except ValueError as exc:
        raise _Stop(STATUS_FAILED_PREPARATION, "source_unavailable", str(exc)) from exc
    target = FrameSize(source.image.width, source.image.height)
    driver = FrameSize(int(facts.display_width), int(facts.display_height))
    try:
        resolved = resolve_alignment(request.intent, driver=driver, target=target)
        baseline = resolve_alignment(IDENTITY, driver=driver, target=target)
    except AlignmentError as exc:
        raise _stop_from_alignment(exc) from exc
    rate = source_rate(facts)
    settings = _resolve_settings(request.window(), facts, rate)
    try:
        last_needed = last_source_frame_needed(settings, request.contract, rate)
    except ValueError as exc:
        raise _Stop(STATUS_FAILED_PREPARATION, "window_invalid", str(exc)) from exc
    if (
        facts.frame_count is not None
        and settings.start_frame >= facts.frame_count
        and facts.frame_count_basis == "reported"
    ):
        raise _Stop(
            STATUS_FAILED_PREPARATION,
            "no_frames_in_window",
            f"The clip has {facts.frame_count} frames; the window starts at frame {settings.start_frame}.",
        )
    stat = clip.stat()
    original_sha = sha256_file(clip, cancel)
    window = parse_framemd5(
        run.run(
            build_window_md5_command(
                executable, clip, settings.start_frame, last_needed, pixel_format
            ),
            max_stdout=MAX_MD5_STDOUT_BYTES,
            what="while reading the window",
        ).stdout
    )
    if not window:
        raise _Stop(
            STATUS_FAILED_PREPARATION,
            "no_frames_in_window",
            "The clip has no decodable frames at or after the window start.",
        )
    plan = build_frame_plan(settings, request.contract, rate=rate, available_frames=len(window))
    if len(plan.used_sources) > MAX_UNIQUE_SOURCE_FRAMES:
        raise _Stop(
            STATUS_FAILED_PREPARATION,
            "too_many_frames",
            f"This window needs {len(plan.used_sources)} distinct source frames; alignment supports at most "
            f"{MAX_UNIQUE_SOURCE_FRAMES}. Choose a shorter length or convert the frame rate.",
        )
    return _Prepared(
        clip=clip,
        executable=executable,
        facts=facts,
        source=source,
        driver=driver,
        target=target,
        resolved=resolved,
        baseline=baseline,
        settings=settings,
        rate=rate,
        plan=plan,
        window_md5=window,
        pixel_format=pixel_format,
        original_sha=original_sha,
        original_size=stat.st_size,
        original_mtime_ns=stat.st_mtime_ns,
    )


def _extract_unique(
    prepared: _Prepared, run: _Run, unique: Sequence[int], directory: Path
) -> dict[int, Path]:
    run.run(
        build_extract_command(prepared.executable, prepared.clip, unique, directory),
        max_stdout=MAX_VERSION_STDOUT_BYTES,
        what="while reading the source frames",
    )
    files = sorted(directory.glob("src_*.png"))
    if len(files) != len(unique):
        raise _Stop(
            STATUS_FAILED_PREPARATION,
            "decode_failed",
            f"FFmpeg decoded {len(files)} of the {len(unique)} planned source frames. Nothing was kept.",
        )
    return dict(zip(unique, files, strict=True))


def _load_frame(path: Path, driver: FrameSize) -> Image.Image:
    with Image.open(path) as handle:
        frame = handle.convert("RGB")
    if frame.size != (driver.width, driver.height):
        raise _Stop(
            STATUS_FAILED_PREPARATION,
            "decode_failed",
            f"A decoded frame is {frame.size[0]}x{frame.size[1]}, not the {driver.width}x{driver.height} "
            "the clip reports. Nothing was kept.",
        )
    return frame


def _remove_stale_work(directory: Path, now: float) -> None:
    try:
        for item in directory.glob(f"{_WORK_PREFIX}*"):
            try:
                if now - item.stat().st_mtime > STALE_TEMP_SECONDS:
                    shutil.rmtree(item, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        return


# --- preview (nothing published) -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlignmentPreviewFrame:
    output_index: int
    source_index: int
    baseline_png: bytes
    aligned_png: bytes


@dataclass(frozen=True, slots=True)
class AlignmentPreview:
    status: str
    message: str = ""
    code: str = ""
    frames: tuple[AlignmentPreviewFrame, ...] = ()
    resolved: ResolvedAlignment | None = None
    baseline: ResolvedAlignment | None = None
    source_png: bytes = b""
    target: FrameSize | None = None
    driver: FrameSize | None = None
    plan: FramePlan | None = None
    facts: DrivingVideoFacts | None = None
    explanation: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == STATUS_PREPARED


def _png(image: Image.Image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=_PNG_LEVEL)
    return buffer.getvalue()


def _thin(indices: Sequence[int], limit: int) -> list[int]:
    """At most ``limit`` of ``indices``, always keeping the first and the last and spacing the rest evenly."""

    if len(indices) <= limit:
        return list(indices)
    if limit < 2:
        return [indices[0]]
    return sorted({indices[round(i * (len(indices) - 1) / (limit - 1))] for i in range(limit)})


@dataclass(slots=True)
class PreviewSource:
    """The decoded driving frames behind a preview, kept so an edit re-renders without another decode.

    Opaque to the GUI layer: it is handed back to ``render_preview`` and never inspected there."""

    status: str
    message: str = ""
    code: str = ""
    frames: dict[int, tuple[int, Image.Image]] = field(
        default_factory=dict
    )  # output -> (source, frame)
    baseline: ResolvedAlignment | None = None
    source_png: bytes = b""
    target: FrameSize | None = None
    driver: FrameSize | None = None
    plan: FramePlan | None = None
    facts: DrivingVideoFacts | None = None
    plain_explanation: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0
    #: The prepared source's geometry and the existing readiness advisories for this pairing (display only).
    source_geometry: Any = None
    readiness_notes: tuple[str, ...] = ()
    #: Recorded evidence statements for the workflow's driving mode (single-sample, as the guidance labels them).
    historical_notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == STATUS_PREPARED


def load_preview_source(
    request: AlignedMotionRequest,
    output_indices: Sequence[int] | None = None,
    *,
    output_root: str | Path,
    cancel: threading.Event | None = None,
    runner: ProcessRunner = run_bounded_process,
    ffmpeg: str | Path | None = None,
    ffprobe: str | Path | None = None,
    inspect: Callable[..., DrivingVideoInspection] = inspect_driving_video,
    clock: Callable[[], float] = time.monotonic,
) -> PreviewSource:
    """Decode the planned driving frames for chosen output frames (at most ``PREVIEW_FRAME_LIMIT``).

    Uses the same plan as the preparation; writes only a private temporary directory that is removed
    before return, and publishes nothing."""

    run = _Run(runner, cancel, clock)
    work: Path | None = None
    prepared: _Prepared | None = None
    try:
        prepared = _plan_aligned(
            request,
            run,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            inspect=inspect,
            cancel=cancel,
            runner=runner,
        )
        plan = prepared.plan
        wanted = sorted(
            {
                min(max(int(i), 0), plan.output_frames - 1)
                for i in (
                    output_indices if output_indices else _preview_indices(plan.output_frames)
                )
            }
        )
        wanted = _thin(
            wanted,
            min(
                PREVIEW_FRAME_LIMIT,
                max(3, PREVIEW_PIXEL_BUDGET // (prepared.driver.width * prepared.driver.height)),
            ),
        )
        unique = sorted({plan.source_indices[i] for i in wanted})
        directory = prepared_directory(Path(output_root).resolve())
        directory.mkdir(parents=True, exist_ok=True)
        work = directory / f"{_WORK_PREFIX}{uuid.uuid4().hex}"
        work.mkdir()
        files = _extract_unique(prepared, run, unique, work)
        decoded = {index: _load_frame(files[index], prepared.driver) for index in unique}
        return PreviewSource(
            STATUS_PREPARED,
            f"Decoded {len(wanted)} frame(s); nothing was published.",
            frames={i: (plan.source_indices[i], decoded[plan.source_indices[i]]) for i in wanted},
            baseline=prepared.baseline,
            source_png=prepared.source.to_png_bytes(),
            target=prepared.target,
            driver=prepared.driver,
            plan=plan,
            facts=prepared.facts,
            plain_explanation=explain_plan(plan, request.contract),
            elapsed_seconds=max(0.0, clock() - run.started),
            source_geometry=prepared.source.geometry,
        )
    except _Stop as stop:
        return PreviewSource(
            stop.status,
            stop.message,
            stop.code,
            plan=prepared.plan if prepared else None,
            elapsed_seconds=max(0.0, clock() - run.started),
        )
    except (OSError, ValueError) as exc:
        return PreviewSource(STATUS_FAILED_PREPARATION, str(exc), "io_error")
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)


def render_preview(source: PreviewSource, intent: AlignmentIntent) -> AlignmentPreview:
    """The baseline and aligned target frames for ``intent`` over already-decoded frames (no process)."""

    if not source.ok or source.baseline is None or source.target is None or source.driver is None:
        return AlignmentPreview(source.status, source.message, source.code, plan=source.plan)
    try:
        resolved = resolve_alignment(intent, driver=source.driver, target=source.target)
    except AlignmentError as exc:
        return AlignmentPreview(
            STATUS_FAILED_PREPARATION,
            exc.message,
            exc.code,
            baseline=source.baseline,
            plan=source.plan,
        )
    baseline_pngs: dict[int, bytes] = {}
    frames: list[AlignmentPreviewFrame] = []
    for output_index in sorted(source.frames):
        source_index, image = source.frames[output_index]
        if source_index not in baseline_pngs:
            baseline_pngs[source_index] = _png(transform_frame(image, source.baseline))
        frames.append(
            AlignmentPreviewFrame(
                output_index,
                source_index,
                baseline_pngs[source_index],
                _png(transform_frame(image, resolved)),
            )
        )
    assert source.plan is not None
    return AlignmentPreview(
        STATUS_PREPARED,
        f"Previewed {len(frames)} frame(s); nothing was published.",
        frames=tuple(frames),
        resolved=resolved,
        baseline=source.baseline,
        source_png=source.source_png,
        target=source.target,
        driver=source.driver,
        plan=source.plan,
        facts=source.facts,
        explanation=(*source.plain_explanation, *alignment_explanation(resolved, source.plan)),
        elapsed_seconds=source.elapsed_seconds,
    )


def preview_alignment(
    request: AlignedMotionRequest,
    output_indices: Sequence[int] | None = None,
    *,
    output_root: str | Path,
    cancel: threading.Event | None = None,
    runner: ProcessRunner = run_bounded_process,
    ffmpeg: str | Path | None = None,
    ffprobe: str | Path | None = None,
    inspect: Callable[..., DrivingVideoInspection] = inspect_driving_video,
    clock: Callable[[], float] = time.monotonic,
) -> AlignmentPreview:
    """The unaligned (baseline) and aligned target frames for chosen output frames; nothing is published.

    Uses the same plan and ``transform_frame`` as the preparation, so a preview frame is the very pixels the
    published derivative will hold."""

    source = load_preview_source(
        request,
        output_indices,
        output_root=output_root,
        cancel=cancel,
        runner=runner,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        inspect=inspect,
        clock=clock,
    )
    return render_preview(source, request.intent)


# --- preparation ----------------------------------------------------------------------------------------


def prepare_aligned_motion_source(
    request: AlignedMotionRequest,
    *,
    output_root: str | Path,
    cancel: threading.Event | None = None,
    runner: ProcessRunner = run_bounded_process,
    ffmpeg: str | Path | None = None,
    ffprobe: str | Path | None = None,
    inspect: Callable[..., DrivingVideoInspection] = inspect_driving_video,
    clock: Callable[[], float] = time.monotonic,
) -> PreparationOutcome:
    """Prepare ``request`` into ``output_root``.  Never raises for a bad clip; publishes only on success."""

    run = _Run(runner, cancel, clock)
    root = Path(output_root).resolve()
    work: Path | None = None
    temporary: Path | None = None
    prepared: _Prepared | None = None

    def finish(status: str, message: str = "", code: str = "", **extra: Any) -> PreparationOutcome:
        plan = prepared.plan if prepared is not None else None
        lines: tuple[str, ...] = ()
        if plan is not None and prepared is not None:
            lines = (
                *explain_plan(plan, request.contract),
                *alignment_explanation(prepared.resolved, plan),
            )
        return PreparationOutcome(
            status=status,
            message=message,
            code=code,
            plan=plan,
            explanation=lines,
            original=prepared.facts if prepared is not None else None,
            elapsed_seconds=max(0.0, clock() - run.started),
            **extra,
        )

    try:
        prepared = _plan_aligned(
            request,
            run,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            inspect=inspect,
            cancel=cancel,
            runner=runner,
        )
        plan, resolved = prepared.plan, prepared.resolved
        directory = prepared_directory(root)
        directory.mkdir(parents=True, exist_ok=True)
        now = time.time()
        _remove_stale_work(directory, now)
        work = directory / f"{_WORK_PREFIX}{uuid.uuid4().hex}"
        work.mkdir()
        temporary = directory / f"{_TEMP_PREFIX}{uuid.uuid4().hex}{PREPARED_SUFFIX}"

        # 1. The planned unique source frames, then the planned output frames, all through one transform.
        unique = list(plan.used_sources)
        files = _extract_unique(prepared, run, unique, work)
        transformed: dict[int, tuple[Image.Image, str]] = {}
        expected: list[str] = []
        for slot, source_index in enumerate(plan.source_indices):
            run.check()
            if source_index not in transformed:
                image = transform_frame(_load_frame(files[source_index], prepared.driver), resolved)
                transformed[source_index] = (image, hashlib.md5(image.tobytes()).hexdigest())
            image, digest = transformed[source_index]
            image.save(work / f"out_{slot:05d}.png", format="PNG", compress_level=_PNG_LEVEL)
            expected.append(digest)

        # 2. One lossless encode of exactly the planned frames.
        run.run(
            build_encode_command(
                prepared.executable, work, plan.output_rate, plan.output_frames, temporary
            ),
            max_stdout=MAX_VERSION_STDOUT_BYTES,
            what="while writing the aligned clip",
        )
        if not temporary.is_file():
            raise _Stop(STATUS_FAILED_PREPARATION, "encode_failed", "FFmpeg wrote no aligned clip.")
        if temporary.stat().st_size > MAX_PREPARED_BYTES:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "output_too_large",
                f"The lossless aligned clip would exceed {MAX_PREPARED_BYTES // (1024 * 1024)} MB.",
            )

        # 3. The file must hold precisely the declared transform of each selected source frame.
        actual = parse_framemd5(
            run.run(
                build_file_md5_command(prepared.executable, temporary, ALIGNED_PIXEL_FORMAT),
                max_stdout=MAX_MD5_STDOUT_BYTES,
                what="while verifying the aligned clip",
            ).stdout
        )
        if actual != expected:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "verification_failed",
                f"The aligned clip does not match the declared transform ({len(actual)} of {len(expected)} "
                "frames decoded, or a frame differs). Nothing was kept.",
            )

        # 4. Nothing may have changed while it was built.
        clip_after = prepared.clip.stat()
        if (clip_after.st_size, clip_after.st_mtime_ns) != (
            prepared.original_size,
            prepared.original_mtime_ns,
        ):
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "source_changed",
                "The driving video changed while it was being aligned. Nothing was kept.",
            )
        derived_sha = sha256_file(temporary, cancel)
        positions = [
            max(0.0, (index - 0.5) / float(plan.output_rate))
            for index in _preview_indices(plan.output_frames)
        ]
        preview = inspect(
            temporary,
            runner=runner,
            ffprobe=ffprobe,
            ffmpeg=prepared.executable,
            positions=positions,
            cancel=cancel,
        )
        derived = preview.facts
        if derived is None or derived.frame_count != plan.output_frames:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "verification_failed",
                "The aligned clip does not report the planned number of frames.",
            )
        if (derived.display_width, derived.display_height) != (
            prepared.target.width,
            prepared.target.height,
        ):
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "verification_failed",
                "The aligned clip does not report the target frame size.",
            )
        if derived.rotation_quadrants != 0:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "verification_failed",
                "The aligned clip carries a rotation tag; its pixels are already in display orientation.",
            )
        reported = _reported_rate(derived)
        if reported is not None and reported != plan.output_rate:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "verification_failed",
                f"The aligned clip reports {reported} fps, not the planned {plan.output_rate}.",
            )

        # 5. Publish by content hash (an identical earlier result is reused, never rewritten).
        destination = prepared_destination(root, derived_sha)
        run.check()
        if not destination.is_file() or sha256_file(destination, cancel) != derived_sha:
            os.replace(temporary, destination)
            temporary = None
        preview = dataclasses.replace(preview, path=str(destination))
        wanted = dict(zip(positions, _preview_indices(plan.output_frames), strict=True))
        captions = tuple(
            f"Output frame {wanted[frame.position_seconds]} "
            f"(source frame {plan.source_indices[wanted[frame.position_seconds]]}, aligned)"
            for frame in preview.frames
            if frame.position_seconds in wanted
        )
        record = _build_aligned_record(
            request=request,
            prepared=prepared,
            expected=expected,
            derived_path=destination,
            derived_sha=derived_sha,
            derived_size=destination.stat().st_size,
            derived_facts=derived,
            version=_ffmpeg_version(run, prepared.executable),
        )
        return finish(
            STATUS_PREPARED,
            f"Aligned {plan.output_frames} frames ({derived_sha[:12]}).",
            record=record,
            preview=preview,
            preview_captions=captions,
        )
    except _Stop as stop:
        return finish(stop.status, stop.message, stop.code)
    except OSError as exc:
        return finish(
            STATUS_FAILED_PREPARATION, f"Preparation could not use the disk: {exc}", "io_error"
        )
    except ValueError as exc:
        return finish(STATUS_FAILED_PREPARATION, str(exc), "window_invalid")
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _reported_rate(facts: DrivingVideoFacts) -> Fraction | None:
    try:
        exact = Fraction(facts.fps_rational) if facts.fps_rational else None
    except (ValueError, ZeroDivisionError):
        return None
    return exact if exact is not None and exact > 0 else None


def _build_aligned_record(
    *,
    request: AlignedMotionRequest,
    prepared: _Prepared,
    expected: Sequence[str],
    derived_path: Path,
    derived_sha: str,
    derived_size: int,
    derived_facts: DrivingVideoFacts,
    version: str,
) -> dict[str, Any]:
    plan, facts, settings = prepared.plan, prepared.facts, prepared.settings
    source_geometry = prepared.source.geometry
    source_png_sha = hashlib.sha256(prepared.source.to_png_bytes()).hexdigest()
    source_path = Path(request.source_image_path).expanduser().resolve()
    used = [prepared.window_md5[i - settings.start_frame] for i in plan.used_sources]
    record: dict[str, Any] = {
        "schema": ALIGNED_SCHEMA,
        "original": {
            "path": str(prepared.clip),
            "sha256": prepared.original_sha,
            "size_bytes": prepared.original_size,
            "container_format": facts.container_format,
            "codec_name": facts.codec_name,
            "pixel_format": facts.pixel_format,
            "width": facts.display_width,
            "height": facts.display_height,
            "coded_width": facts.coded_width,
            "coded_height": facts.coded_height,
            "rotation_quadrants": facts.rotation_quadrants,
            "frame_rate": facts.fps_rational,
            "frame_count": facts.frame_count,
            "frame_count_basis": facts.frame_count_basis,
        },
        "derived": {
            "path": str(derived_path),
            "sha256": derived_sha,
            "size_bytes": derived_size,
            "frames": plan.output_frames,
            "width": derived_facts.display_width,
            "height": derived_facts.display_height,
            "coded_width": derived_facts.coded_width,
            "coded_height": derived_facts.coded_height,
            "rotation_quadrants": 0,
            "pixel_format": ALIGNED_PIXEL_FORMAT,
            "frame_rate": _rate_text(plan.output_rate),
            "frames_md5_sha256": hashlib.sha256("\n".join(expected).encode("ascii")).hexdigest(),
        },
        "settings": {
            **settings.to_record(),
            "requested": {"start": request.start, "end": request.end, "unit": request.unit},
        },
        "contract": request.contract.to_record(),
        "plan": plan.to_record(),
        "processing": {
            "tool": "ffmpeg",
            "tool_version": version,
            "video_codec": ALIGNED_VIDEO_CODEC,
            "lossless": False,
            "lossless_encoding": True,
            "source_frame_identity": "transformed",
            "resampling": "lanczos",
            "pillow_version": PIL.__version__,
            "implementation": IMPLEMENTATION,
            "frame_selection": "motion-source-plan; unique frames decoded once, transformed once",
            "color_handling": (
                "source frames converted to 8-bit RGB by FFmpeg's default conversion (matrix from the "
                "clip's colour tags where present); the derivative stores that RGB losslessly"
            ),
            "orientation": "display orientation baked into the pixels; no rotation metadata",
            "verification": (
                "every output frame's decoded RGB fingerprint equals the fingerprint of the declared "
                "transform of its selected source frame"
            ),
        },
        "alignment": {
            **prepared.resolved.to_record(),
            "driver_original_sha256": prepared.original_sha,
            "temporal_plan_sha256": "",
            "source_image": {
                "original_path": str(source_path),
                "original_sha256": sha256_file(source_path),
                "prepared_sha256": source_png_sha,
                "width": prepared.target.width,
                "height": prepared.target.height,
                "orientation": source_geometry.orientation,
                "policy": source_geometry.policy,
            },
            "source_frames_md5_sha256": hashlib.sha256("\n".join(used).encode("ascii")).hexdigest(),
            "implementation": IMPLEMENTATION,
        },
    }
    record["alignment"]["temporal_plan_sha256"] = temporal_plan_sha256(record)
    return record


# --- admission- and dispatch-time verification ----------------------------------------------------------


def validate_aligned_record(
    record: Any,
    *,
    original_path: str | Path,
    contract: MotionSourceContract,
    hash_file: Callable[[str | Path], str] = sha256_file,
) -> dict[str, Any]:
    """Re-verify an aligned record against the form and the bytes on disk (never recomputes the transform).

    The frozen numbers must equal what the stated intent and geometry resolve to with the recorded transform
    version, both files must still hash as recorded, and the record must be for this clip, workflow, version
    and length.  Anything else raises ``AlignedPreparationError`` with the reason."""

    data = _mapping(record)
    if data.get("schema") != ALIGNED_SCHEMA:
        raise AlignedPreparationError("The aligned motion source record is not recognised.")
    original, derived = _mapping(data.get("original")), _mapping(data.get("derived"))
    recorded, alignment = _mapping(data.get("contract")), _mapping(data.get("alignment"))
    if not (original and derived and recorded and alignment):
        raise AlignedPreparationError("The aligned motion source record is incomplete.")
    for key, wanted in contract.to_record().items():
        if key in {"runtime_revision", "consumption_rule"}:
            continue
        if recorded.get(key) != wanted:
            raise AlignedPreparationError(
                f"The motion source was aligned for {key.replace('_', ' ')} {recorded.get(key)!r}, but "
                f"the form now has {wanted!r}. Align and prepare it again."
            )
    plan = _mapping(data.get("plan"))
    indices = plan.get("source_indices")
    if (
        not isinstance(indices, list)
        or len(indices) != contract.output_frames
        or derived.get("frames") != contract.output_frames
    ):
        raise AlignedPreparationError("The aligned motion source record is inconsistent.")
    try:
        resolved = alignment_from_record(alignment)
    except AlignmentError as exc:
        raise AlignedPreparationError(exc.message) from exc
    if (
        (derived.get("width"), derived.get("height"))
        != (resolved.target.width, resolved.target.height)
        or (original.get("width"), original.get("height"))
        != (resolved.driver.width, resolved.driver.height)
        or derived.get("rotation_quadrants") != 0
        or alignment.get("driver_original_sha256") != original.get("sha256")
        or alignment.get("temporal_plan_sha256") != temporal_plan_sha256(data)
    ):
        raise AlignedPreparationError(
            "The aligned motion source record disagrees with itself (geometry, driver or frame plan). "
            "Align and prepare it again."
        )
    if not _same(str(original.get("path") or ""), str(original_path)):
        raise AlignedPreparationError(
            "The motion source was aligned from a different driving video. Align and prepare it again."
        )
    derived_path = Path(str(derived.get("path") or ""))
    derived_sha = str(derived.get("sha256") or "")
    if derived_path.name != f"{derived_sha}{PREPARED_SUFFIX}" or len(derived_sha) != 64:
        raise AlignedPreparationError("The aligned clip is not content-addressed by its hash.")
    for label, path, wanted in (
        ("driving video", Path(str(original.get("path") or "")), str(original.get("sha256") or "")),
        ("aligned motion source", derived_path, derived_sha),
    ):
        try:
            actual = hash_file(path)
        except OSError as exc:
            raise AlignedPreparationError(f"The {label} is no longer readable: {path}") from exc
        if actual != wanted:
            raise AlignedPreparationError(f"The {label} changed since it was aligned: {path}")
    return {key: _copy(value) for key, value in data.items()}


def _same(left: str, right: str) -> bool:
    def norm(value: str) -> str:
        return os.path.normcase(os.path.abspath(str(Path(value).expanduser())))

    return norm(left) == norm(right)


def verify_aligned_source_binding(
    record: Mapping[str, Any],
    *,
    source_image_path: str | Path,
    prepared_source_sha256: str,
    prepared_dimensions: Mapping[str, Any],
    hash_file: Callable[[str | Path], str] = sha256_file,
) -> None:
    """The aligned clip belongs to exactly this source image and its prepared reference (admission, per source)."""

    image = _mapping(_mapping(record.get("alignment")).get("source_image"))
    try:
        current = hash_file(source_image_path)
    except OSError as exc:
        raise AlignedPreparationError(
            f"The source image is no longer readable: {source_image_path}"
        ) from exc
    if current != image.get("original_sha256") or prepared_source_sha256 != image.get(
        "prepared_sha256"
    ):
        raise AlignedPreparationError(
            "This alignment was made for a different source image (or the source image changed). "
            "Align and prepare it again for this image."
        )
    derived = _mapping(record.get("derived"))
    if (derived.get("width"), derived.get("height")) != (
        prepared_dimensions.get("width"),
        prepared_dimensions.get("height"),
    ):
        raise AlignedPreparationError(
            "The aligned clip's size differs from the prepared reference image. Align it again."
        )


def verify_aligned_dispatch(stage_config: Mapping[str, Any], input_image_path: Any) -> None:
    """At execution: the frozen aligned clip, its record and the reference image must still agree."""

    record = stage_config.get("motion_source_preparation")
    if not is_aligned_record(record):
        return
    data = _mapping(record)
    derived = _mapping(data.get("derived"))
    if str(stage_config.get("pose_video_path") or "") != str(derived.get("path") or "") or str(
        stage_config.get("pose_video_sha256") or ""
    ) != str(derived.get("sha256") or ""):
        raise AlignedPreparationError(
            "The frozen driving video is not the aligned clip its record describes."
        )
    try:
        resolved = alignment_from_record(_mapping(data.get("alignment")))
    except AlignmentError as exc:
        raise AlignedPreparationError(exc.message) from exc
    target = _mapping(_mapping(stage_config.get("source_preparation")).get("prepared_dimensions"))
    if (target.get("width"), target.get("height")) != (
        resolved.target.width,
        resolved.target.height,
    ):
        raise AlignedPreparationError(
            "The aligned clip was made for a different target frame than this job's reference image."
        )
    expected = _mapping(_mapping(data.get("alignment")).get("source_image")).get("prepared_sha256")
    if (
        not input_image_path
    ):  # fail closed: an aligned clip is never run without its own reference image
        raise AlignedPreparationError("The aligned job has no reference image to verify.")
    try:
        actual = sha256_file(input_image_path)
    except OSError as exc:
        raise AlignedPreparationError("The reference image is no longer readable.") from exc
    if actual != expected:
        raise AlignedPreparationError(
            "The reference image differs from the one this alignment was made for."
        )


# --- form-level entry points (the controller and the eval authoring call these) -------------------------


def aligned_request_for_form(
    spec: Any, form: Mapping[str, Any], request: Mapping[str, Any]
) -> AlignedMotionRequest:
    """The aligned request for the form's workflow, length, clip and source image.

    ``request`` carries the operator's ``start``, ``end``, ``unit``, ``fps_conversion`` and ``intent`` (an
    ``AlignmentIntent``).  Raises ``MotionSourceUnavailable`` (a ``ValueError``) with the reason when the
    workflow cannot honestly offer alignment, so nothing is ever prepared against an unverified geometry."""

    support = alignment_support(spec)
    if not support.supported:
        raise MotionSourceUnavailable(support.reason)
    contract = motion_source_contract(spec, form.get("frame_count"))
    policy = (getattr(spec, "backend_defaults", None) or {}).get("source_preparation")
    if not isinstance(policy, Mapping):
        raise MotionSourceUnavailable("The workflow declares no source geometry to align to.")
    intent = request.get("intent")
    if not isinstance(intent, AlignmentIntent):
        raise MotionSourceUnavailable("No alignment was chosen.")
    return AlignedMotionRequest(
        clip_path=str(form.get("pose_video_path") or ""),
        contract=contract,
        source_image_path=str(form.get("source_image_path") or ""),
        source_policy=policy,
        intent=intent,
        start=float(request.get("start") or 0),
        end=None if request.get("end") in (None, "") else float(request["end"]),
        unit=str(request.get("unit") or "seconds"),
        fps_conversion=str(request.get("fps_conversion") or "none"),
    )


def prepare_aligned_for_form(
    spec: Any,
    form: Mapping[str, Any],
    request: Mapping[str, Any],
    output_root: str | Path,
    cancel: threading.Event | None = None,
) -> PreparationOutcome:
    """Prepare the aligned clip the form names; a workflow that cannot offer it returns a failed outcome."""

    try:
        aligned = aligned_request_for_form(spec, form, request)
    except ValueError as exc:
        return PreparationOutcome(
            status=STATUS_FAILED_PREPARATION, message=str(exc), code="unavailable"
        )
    return prepare_aligned_motion_source(aligned, output_root=output_root, cancel=cancel)


def preview_alignment_for_form(
    spec: Any,
    form: Mapping[str, Any],
    request: Mapping[str, Any],
    output_root: str | Path,
    cancel: threading.Event | None = None,
    indices: Sequence[int] | None = None,
) -> AlignmentPreview:
    """Preview chosen output frames for the form's alignment (nothing is published or queued)."""

    try:
        aligned = aligned_request_for_form(spec, form, request)
    except ValueError as exc:
        return AlignmentPreview(STATUS_FAILED_PREPARATION, str(exc), "unavailable")
    return preview_alignment(aligned, indices, output_root=output_root, cancel=cancel)


__all__ = [
    "ALIGNED_PIXEL_FORMAT",
    "ALIGNED_SCHEMA",
    "ALIGNED_VIDEO_CODEC",
    "ALIGNMENT_SCHEMA",
    "COORDINATE_SYSTEM",
    "IMPLEMENTATION",
    "MAX_ALIGN_FRAME_PIXELS",
    "MAX_UNIQUE_SOURCE_FRAMES",
    "TRANSFORM_VERSION",
    "AlignedMotionRequest",
    "AlignedPreparationError",
    "AlignmentPreview",
    "AlignmentPreviewFrame",
    "aligned_request_for_form",
    "alignment_explanation",
    "PreviewSource",
    "build_encode_command",
    "build_extract_command",
    "is_aligned_record",
    "load_preview_source",
    "prepare_aligned_for_form",
    "prepare_aligned_motion_source",
    "preview_alignment_for_form",
    "render_preview",
    "preview_alignment",
    "temporal_plan_sha256",
    "validate_aligned_record",
    "verify_aligned_dispatch",
    "verify_aligned_source_binding",
]

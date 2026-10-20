"""Produce the exact driving-video frames a workflow will consume (PR-VID-MOTION-210).

``prepare_motion_source`` turns an operator's clip, window and optional frame-rate conversion into a
StableNew-owned, content-addressed MP4 holding exactly the frames of a ``FramePlan``, in order, and a
record of how it was made.  The flow, every step bounded and cancellable:

1. probe the clip with the PR-VID-196 inspector (no second probe implementation);
2. decode the window once with FFmpeg ``framemd5`` to learn how many frames really exist and each
   one's fingerprint, then build the plan from that truth;
3. encode the plan's frames losslessly (H.264 ``-qp 0``, the clip's own pixel format) to a private
   temporary file, with a hard output-size cap;
4. decode the result again and require every frame to fingerprint-equal the frame the plan selected
   (so "the file holds what the plan says" is verified, not assumed);
5. hash the bytes, publish them atomically under ``<sha256>.mp4`` (never overwritten with different
   content) and preview the published frames with the same inspector.

Nothing here queues, builds an NJR or touches a GUI: callers freeze the returned record into a job
through ``VideoWorkflowNjrBuilder``, which re-verifies every byte again at admission.  A failure or
cancellation publishes nothing and removes its temporary file.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.driving_video_inspection import (
    MAX_PREVIEW_DECODE_PIXELS,
    STATUS_FAILED,
    DrivingVideoFacts,
    DrivingVideoInspection,
    ProcessRunner,
    inspect_driving_video,
    run_bounded_process,
)
from src.video.motion_source_plan import (
    FPS_CONVERSION_NONE,
    FPS_CONVERSION_WORKFLOW_RATE,
    SCHEMA,
    FramePlan,
    MotionSourceContract,
    MotionSourceSettings,
    build_frame_plan,
    explain_plan,
    ffmpeg_filter_chain,
    frame_from_seconds,
    last_source_frame_needed,
    motion_source_contract,
    source_rate,
)

PREPARED_DIRNAME = "prepared_driving_videos"
PREPARED_SUFFIX = ".mp4"
_TEMP_PREFIX = ".preparing-"
_DRIVING_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}

# --- bounds (all named and tested) ----------------------------------------------------------------
MAX_PREPARED_BYTES = 256 * 1024 * 1024
PASS_TIMEOUT_SECONDS = 120.0
DEADLINE_SECONDS = 420.0
VERSION_TIMEOUT_SECONDS = 10.0
MAX_MD5_STDOUT_BYTES = 4 * 1024 * 1024
MAX_VERSION_STDOUT_BYTES = 16 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
#: Frames above this many pixels are refused before FFmpeg is asked to decode (and hold) a frame.
MAX_FRAME_PIXELS = MAX_PREVIEW_DECODE_PIXELS
STALE_TEMP_SECONDS = 24 * 3600

STATUS_PREPARED = "prepared"
STATUS_FAILED_PREPARATION = "failed"
STATUS_CANCELLED = "cancelled"

# Pixel formats a lossless H.264 file can carry unchanged, and byte-identical renames of others.
_LOSSLESS_PIXEL_FORMATS = frozenset(
    {
        "yuv420p",
        "yuvj420p",
        "yuv422p",
        "yuvj422p",
        "yuv444p",
        "yuvj444p",
        "yuv420p10le",
        "yuv422p10le",
        "yuv444p10le",
    }
)
_PIXEL_FORMAT_ALIASES = {
    "nv12": "yuv420p",
    "nv21": "yuv420p",
    "p010le": "yuv420p10le",
    "yuva420p": "yuv420p",
    "yuva422p": "yuv422p",
    "yuva444p": "yuv444p",
}
#: Only the containers StableNew accepts for a driving video (``.mp4 .mov .webm .mkv``); a playlist or
#: script that merely carries one of those extensions is refused by FFmpeg instead of followed.
_DEMUXER_WHITELIST = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm"
_ENCODER_ARGS = ("-c:v", "libx264", "-qp", "0", "-preset", "medium", "-threads", "1")


class PreparedMotionSourceError(ValueError):
    """A prepared-motion-source record does not match the files or the form it claims to describe."""


@dataclass(frozen=True, slots=True)
class MotionSourceRequest:
    """One preparation: the clip, the registered workflow's contract and the operator's window.

    ``start``/``end`` are seconds or source frames according to ``unit``; seconds are converted with
    the clip's exact reported rate (nearest frame).  ``end`` is exclusive and optional."""

    clip_path: str
    contract: MotionSourceContract
    start: float = 0.0
    end: float | None = None
    unit: str = "seconds"
    fps_conversion: str = FPS_CONVERSION_NONE


@dataclass(frozen=True, slots=True)
class PreparationOutcome:
    status: str
    message: str = ""
    code: str = ""
    record: Mapping[str, Any] | None = None
    plan: FramePlan | None = None
    explanation: tuple[str, ...] = ()
    original: DrivingVideoFacts | None = None
    preview: DrivingVideoInspection | None = None
    preview_captions: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def prepared(self) -> bool:
        return self.status == STATUS_PREPARED and self.record is not None


class _Stop(Exception):
    def __init__(self, status: str, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# --- files ----------------------------------------------------------------------------------------


def sha256_file(path: str | Path, cancel: threading.Event | None = None) -> str:
    """SHA-256 of a file in bounded chunks; a set ``cancel`` raises ``_Stop`` between chunks."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            if cancel is not None and cancel.is_set():
                raise _Stop(STATUS_CANCELLED, "cancelled", "Preparation was cancelled.")
            digest.update(chunk)
    return digest.hexdigest()


def prepared_directory(output_root: str | Path) -> Path:
    return Path(output_root) / PREPARED_DIRNAME


def prepared_destination(output_root: str | Path, sha256: str) -> Path:
    """Content-addressed path of a prepared clip: its own SHA-256 is its name."""

    return prepared_directory(output_root) / f"{sha256}{PREPARED_SUFFIX}"


def _remove_stale_temporaries(directory: Path, now: float) -> None:
    """Best-effort removal of this module's own abandoned temporaries (a hard kill leaves one)."""

    try:
        for item in directory.glob(f"{_TEMP_PREFIX}*"):
            try:
                if now - item.stat().st_mtime > STALE_TEMP_SECONDS:
                    item.unlink()
            except OSError:
                continue
    except OSError:
        return


# --- FFmpeg commands (pure) -----------------------------------------------------------------------


def target_pixel_format(pixel_format: str) -> str | None:
    """The pixel format the lossless file uses for a clip's format, or None when unsupported."""

    name = str(pixel_format or "").strip()
    if name in _LOSSLESS_PIXEL_FORMATS:
        return name
    return _PIXEL_FORMAT_ALIASES.get(name)


def _input_args(ffmpeg: str | Path, video: str | Path) -> list[str]:
    return [
        str(ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-hide_banner",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        _DEMUXER_WHITELIST,
        "-noautorotate",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
    ]


def build_window_md5_command(
    ffmpeg: str | Path, video: str | Path, first: int, last: int, pixel_format: str
) -> list[str]:
    """Fingerprint every source frame in ``[first, last]`` (decode order, stored orientation)."""

    return [
        *_input_args(ffmpeg, video),
        "-vf",
        f"select='between(n,{first},{last})'",
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        pixel_format,
        "-f",
        "framemd5",
        "-",
    ]


def build_file_md5_command(ffmpeg: str | Path, video: str | Path, pixel_format: str) -> list[str]:
    """Fingerprint every frame of a prepared file."""

    return [
        *_input_args(ffmpeg, video),
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        pixel_format,
        "-f",
        "framemd5",
        "-",
    ]


def build_encode_command(
    ffmpeg: str | Path,
    video: str | Path,
    plan: FramePlan,
    pixel_format: str,
    destination: str | Path,
) -> list[str]:
    """Write exactly the plan's frames, losslessly, with no metadata and a hard size cap."""

    return [
        *_input_args(ffmpeg, video),
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-vf",
        ffmpeg_filter_chain(plan),
        "-frames:v",
        str(plan.output_frames),
        "-fps_mode",
        "passthrough",
        *_ENCODER_ARGS,
        "-pix_fmt",
        pixel_format,
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


def parse_framemd5(stdout: bytes) -> list[str]:
    """Per-frame MD5 hex strings from ``-f framemd5`` output (comment lines skipped)."""

    digests: list[str] = []
    for raw in stdout.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        digest = line.rsplit(",", 1)[-1].strip().lower()
        if len(digest) == 32 and all(char in "0123456789abcdef" for char in digest):
            digests.append(digest)
    return digests


# --- orchestration --------------------------------------------------------------------------------


def _resolve_settings(
    request: MotionSourceRequest, facts: DrivingVideoFacts, rate: Fraction | None
) -> MotionSourceSettings:
    def to_frame(value: float) -> int:
        if value < 0:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "window_invalid",
                "A window cannot start before the clip.",
            )
        if request.unit == "frames":
            if float(value) != int(value):
                raise _Stop(
                    STATUS_FAILED_PREPARATION, "window_invalid", "Frame numbers must be whole."
                )
            return int(value)
        if request.unit != "seconds":
            raise _Stop(
                STATUS_FAILED_PREPARATION, "window_invalid", f"Unknown unit {request.unit!r}."
            )
        if rate is None:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "frame_rate_unknown",
                "The clip reports no frame rate, so a window in seconds cannot be placed. "
                "Enter frame numbers instead.",
            )
        return frame_from_seconds(value, rate)

    settings = MotionSourceSettings(
        start_frame=to_frame(request.start),
        end_frame=None if request.end is None else to_frame(request.end),
        fps_conversion=request.fps_conversion,
    )
    try:
        settings.validate()
    except ValueError as exc:
        raise _Stop(STATUS_FAILED_PREPARATION, "window_invalid", str(exc)) from exc
    if settings.fps_conversion == FPS_CONVERSION_WORKFLOW_RATE:
        if rate is None:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "frame_rate_unknown",
                "The clip reports no frame rate, so it cannot be converted to the workflow's rate.",
            )
        if facts.fps_is_variable_suspected:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "variable_frame_rate",
                "The clip may be variable frame rate, so a rate conversion cannot be exact. Prepare "
                "without conversion, or re-encode the clip at a constant rate first.",
            )
    return settings


class _Run:
    """The state shared by the steps of one preparation (deadline, cancellation, runner)."""

    def __init__(
        self,
        runner: ProcessRunner,
        cancel: threading.Event | None,
        clock: Callable[[], float],
    ) -> None:
        self.runner, self.cancel, self.clock = runner, cancel, clock
        self.started = clock()

    def check(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise _Stop(STATUS_CANCELLED, "cancelled", "Preparation was cancelled.")
        if self.clock() - self.started > DEADLINE_SECONDS:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "deadline_exceeded",
                f"Preparation stopped after {DEADLINE_SECONDS:g} seconds.",
            )

    def run(self, command: Sequence[str], *, max_stdout: int, what: str) -> Any:
        self.check()
        remaining = DEADLINE_SECONDS - (self.clock() - self.started)
        outcome = self.runner(
            command,
            timeout_seconds=max(1.0, min(PASS_TIMEOUT_SECONDS, remaining)),
            max_stdout_bytes=max_stdout,
            cancel=self.cancel,
        )
        if outcome.cancelled:
            raise _Stop(STATUS_CANCELLED, "cancelled", "Preparation was cancelled.")
        if outcome.launch_error:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "ffmpeg_unavailable",
                f"FFmpeg could not be started: {outcome.launch_error}",
            )
        if outcome.timed_out:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "timeout",
                f"FFmpeg did not finish {what} within {PASS_TIMEOUT_SECONDS:g} seconds.",
            )
        if outcome.output_truncated:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "output_too_large",
                f"FFmpeg produced too much output {what}.",
            )
        if outcome.returncode != 0:
            tail = outcome.stderr.decode("utf-8", errors="replace").strip().splitlines()
            reason = f" ({tail[-1][:120]})" if tail else ""
            raise _Stop(
                STATUS_FAILED_PREPARATION, "ffmpeg_failed", f"FFmpeg failed {what}{reason}."
            )
        return outcome


def _ffmpeg_version(run: _Run, ffmpeg: str | Path) -> str:
    try:
        outcome = run.runner(
            [str(ffmpeg), "-version"],
            timeout_seconds=VERSION_TIMEOUT_SECONDS,
            max_stdout_bytes=MAX_VERSION_STDOUT_BYTES,
            cancel=run.cancel,
        )
    except Exception:  # noqa: BLE001 - provenance only; never the reason a preparation fails
        return "unknown"
    lines = outcome.stdout.decode("utf-8", errors="replace").splitlines() if outcome.stdout else []
    return lines[0].strip()[:160] if lines else "unknown"


def _rate_text(rate: Fraction) -> str:
    return f"{rate.numerator}/{rate.denominator}"


def _preview_indices(frames: int) -> list[int]:
    return sorted({0, (frames - 1) // 2, frames - 1})


def prepare_motion_source(
    request: MotionSourceRequest,
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
    root = Path(output_root).resolve()  # absolute: no relative name can read as an FFmpeg option
    temporary: Path | None = None
    plan: FramePlan | None = None
    facts: DrivingVideoFacts | None = None

    def finish(status: str, message: str = "", code: str = "", **extra: Any) -> PreparationOutcome:
        return PreparationOutcome(
            status=status,
            message=message,
            code=code,
            plan=plan,
            explanation=explain_plan(plan, request.contract) if plan is not None else (),
            original=facts,
            elapsed_seconds=max(0.0, clock() - run.started),
            **extra,
        )

    try:
        run.check()  # a cancel that arrived before any work started outranks every other outcome
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

        run.check()
        probe = inspect(
            clip, runner=runner, ffprobe=ffprobe, ffmpeg=executable, frame_count=0, cancel=cancel
        )
        if probe.status == STATUS_FAILED or probe.facts is None:
            if cancel is not None and cancel.is_set():
                raise _Stop(STATUS_CANCELLED, "cancelled", "Preparation was cancelled.")
            reason = probe.issues[0].message if probe.issues else "The clip could not be read."
            raise _Stop(STATUS_FAILED_PREPARATION, "probe_failed", reason)
        facts = probe.facts
        if facts.coded_width * facts.coded_height > MAX_FRAME_PIXELS:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "frame_too_large",
                f"Frames are {facts.coded_width}x{facts.coded_height}; exact preparation is limited to "
                f"{MAX_FRAME_PIXELS / 1e6:.0f} megapixels per frame.",
            )
        pixel_format = target_pixel_format(facts.pixel_format)
        if pixel_format is None:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "unsupported_pixel_format",
                f"The clip's pixel format ({facts.pixel_format or 'unknown'}) cannot be kept "
                "losslessly. Re-encode the clip to a standard 4:2:0 or 4:2:2 format first.",
            )
        rate = source_rate(facts)
        settings = _resolve_settings(request, facts, rate)
        try:
            last_needed = last_source_frame_needed(settings, request.contract, rate)
        except ValueError as exc:
            raise _Stop(STATUS_FAILED_PREPARATION, "window_invalid", str(exc)) from exc
        if (
            facts.frame_count is not None
            and settings.start_frame >= facts.frame_count
            and (facts.frame_count_basis == "reported")
        ):
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "no_frames_in_window",
                f"The clip has {facts.frame_count} frames; the window starts at frame "
                f"{settings.start_frame}.",
            )

        original_stat = clip.stat()
        original_sha = sha256_file(clip, cancel)

        # 1. How many frames really exist from the start, and what each one looks like.
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

        # 2. Encode exactly that plan to a private temporary file.
        directory = prepared_directory(root)
        directory.mkdir(parents=True, exist_ok=True)
        _remove_stale_temporaries(directory, time.time())
        temporary = directory / f"{_TEMP_PREFIX}{uuid.uuid4().hex}{PREPARED_SUFFIX}"
        run.run(
            build_encode_command(executable, clip, plan, pixel_format, temporary),
            max_stdout=MAX_VERSION_STDOUT_BYTES,
            what="while writing the prepared clip",
        )
        if not temporary.is_file():
            raise _Stop(
                STATUS_FAILED_PREPARATION, "encode_failed", "FFmpeg wrote no prepared clip."
            )
        size = temporary.stat().st_size
        if size > MAX_PREPARED_BYTES:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "output_too_large",
                f"The lossless prepared clip would exceed {MAX_PREPARED_BYTES // (1024 * 1024)} MB "
                "(the clip's resolution is too high for exact preparation). Choose a lower-resolution clip.",
            )

        # 3. The file must hold precisely what the plan selected.
        expected = [window[index - settings.start_frame] for index in plan.source_indices]
        actual = parse_framemd5(
            run.run(
                build_file_md5_command(executable, temporary, pixel_format),
                max_stdout=MAX_MD5_STDOUT_BYTES,
                what="while verifying the prepared clip",
            ).stdout
        )
        if actual != expected:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "verification_failed",
                f"The prepared clip does not match the plan ({len(actual)} of {len(expected)} frames "
                "decoded, or a frame differs). Nothing was kept.",
            )

        # 4. The source must not have changed while it was being read.
        after = clip.stat()
        if (after.st_size, after.st_mtime_ns) != (original_stat.st_size, original_stat.st_mtime_ns):
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "source_changed",
                "The driving video changed while it was being prepared. Nothing was kept.",
            )

        # 5. Check and preview the finished bytes with the shared inspector, then publish them by
        #    content hash.  Nothing is published unless every check has passed.
        derived_sha = sha256_file(temporary, cancel)
        positions = [
            max(0.0, (index - 0.5) / float(plan.output_rate))
            for index in _preview_indices(plan.output_frames)
        ]
        preview = inspect(
            temporary,
            runner=runner,
            ffprobe=ffprobe,
            ffmpeg=executable,
            positions=positions,
            cancel=cancel,
        )
        derived_facts = preview.facts
        if derived_facts is None or derived_facts.frame_count != plan.output_frames:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "verification_failed",
                "The prepared clip does not report the planned number of frames.",
            )
        if derived_facts.rotation_quadrants != facts.rotation_quadrants:
            raise _Stop(
                STATUS_FAILED_PREPARATION,
                "verification_failed",
                "This FFmpeg build did not keep the clip's rotation metadata, so the prepared clip "
                "would be turned differently from the original. Nothing was kept.",
            )
        destination = prepared_destination(root, derived_sha)
        run.check()
        if not destination.is_file() or sha256_file(destination, cancel) != derived_sha:
            os.replace(temporary, destination)
            temporary = None
        preview = dataclasses.replace(preview, path=str(destination))
        # A frame the inspector could not decode simply has no thumbnail: captions follow the
        # frames that exist, matched by their seek position, never by order.
        wanted = dict(zip(positions, _preview_indices(plan.output_frames), strict=True))
        captions = tuple(
            f"Output frame {wanted[frame.position_seconds]} "
            f"(source frame {plan.source_indices[wanted[frame.position_seconds]]})"
            for frame in preview.frames
            if frame.position_seconds in wanted
        )
        record = _build_record(
            request=request,
            settings=settings,
            plan=plan,
            original_facts=facts,
            original_path=clip,
            original_sha=original_sha,
            original_size=original_stat.st_size,
            derived_path=destination,
            derived_sha=derived_sha,
            derived_size=destination.stat().st_size,
            derived_facts=derived_facts,
            pixel_format=pixel_format,
            frame_digest=hashlib.sha256("\n".join(expected).encode("ascii")).hexdigest(),
            version=_ffmpeg_version(run, executable),
        )
        return finish(
            STATUS_PREPARED,
            f"Prepared {plan.output_frames} frames ({derived_sha[:12]}).",
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
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _build_record(
    *,
    request: MotionSourceRequest,
    settings: MotionSourceSettings,
    plan: FramePlan,
    original_facts: DrivingVideoFacts,
    original_path: Path,
    original_sha: str,
    original_size: int,
    derived_path: Path,
    derived_sha: str,
    derived_size: int,
    derived_facts: DrivingVideoFacts,
    pixel_format: str,
    frame_digest: str,
    version: str,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "original": {
            "path": str(original_path),
            "sha256": original_sha,
            "size_bytes": original_size,
            "container_format": original_facts.container_format,
            "codec_name": original_facts.codec_name,
            "pixel_format": original_facts.pixel_format,
            "width": original_facts.display_width,
            "height": original_facts.display_height,
            "rotation_quadrants": original_facts.rotation_quadrants,
            "frame_rate": original_facts.fps_rational,
            "frame_count": original_facts.frame_count,
            "frame_count_basis": original_facts.frame_count_basis,
        },
        "derived": {
            "path": str(derived_path),
            "sha256": derived_sha,
            "size_bytes": derived_size,
            "frames": plan.output_frames,
            "width": derived_facts.display_width,
            "height": derived_facts.display_height,
            "rotation_quadrants": derived_facts.rotation_quadrants,
            "pixel_format": pixel_format,
            "frame_rate": _rate_text(plan.output_rate),
            "frames_md5_sha256": frame_digest,
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
            "video_codec": "libx264",
            "lossless": True,
            "encoder_args": list(_ENCODER_ARGS[2:]) + ["-pix_fmt", pixel_format],
            "frame_selection": "select+settb+setpts+fps+tpad",
            "orientation": "stored orientation kept; display rotation preserved as metadata",
            "verification": "every output frame equals the planned source frame (framemd5)",
        },
    }


# --- admission-time verification --------------------------------------------------------------------


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _same_path(left: str, right: str) -> bool:
    def norm(value: str) -> str:
        return os.path.normcase(os.path.abspath(str(Path(value).expanduser())))

    return norm(left) == norm(right)


def validate_prepared_record(
    record: Any,
    *,
    original_path: str | Path,
    contract: MotionSourceContract,
    hash_file: Callable[[str | Path], str] = sha256_file,
) -> dict[str, Any]:
    """Re-verify a prepared-source record against the form and the bytes on disk.

    Raises ``PreparedMotionSourceError`` (never accepts) when the record is malformed, was made for
    another clip, workflow, version or length, or when either the original or the prepared bytes
    are missing or differ from what was recorded.  Returns an independent copy of the record."""

    data = _mapping(record)
    if data.get("schema") != SCHEMA:
        raise PreparedMotionSourceError("The prepared motion source record is not recognised.")
    original, derived = _mapping(data.get("original")), _mapping(data.get("derived"))
    recorded = _mapping(data.get("contract"))
    if not (original and derived and recorded):
        raise PreparedMotionSourceError("The prepared motion source record is incomplete.")
    for key, expected in contract.to_record().items():
        if key in {"runtime_revision", "consumption_rule"}:
            continue
        if recorded.get(key) != expected:
            raise PreparedMotionSourceError(
                f"The motion source was prepared for {key.replace('_', ' ')} {recorded.get(key)!r}, "
                f"but the form now has {expected!r}. Prepare it again."
            )
    plan = _mapping(data.get("plan"))
    indices = plan.get("source_indices")
    if (
        not isinstance(indices, list)
        or len(indices) != contract.output_frames
        or derived.get("frames") != contract.output_frames
    ):
        raise PreparedMotionSourceError("The prepared motion source record is inconsistent.")
    if not _same_path(str(original.get("path") or ""), str(original_path)):
        raise PreparedMotionSourceError(
            "The motion source was prepared from a different driving video. Prepare it again."
        )
    derived_path = Path(str(derived.get("path") or ""))
    derived_sha = str(derived.get("sha256") or "")
    if derived_path.name != f"{derived_sha}{PREPARED_SUFFIX}" or len(derived_sha) != 64:
        raise PreparedMotionSourceError("The prepared clip is not content-addressed by its hash.")
    for label, path, expected in (
        ("driving video", Path(str(original.get("path") or "")), str(original.get("sha256") or "")),
        ("prepared motion source", derived_path, derived_sha),
    ):
        try:
            actual = hash_file(path)
        except OSError as exc:
            raise PreparedMotionSourceError(f"The {label} is no longer readable: {path}") from exc
        if actual != expected:
            raise PreparedMotionSourceError(f"The {label} changed since it was prepared: {path}")
    return {key: _copy(value) for key, value in data.items()}


def _copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy(item) for item in value]
    return value


def prepare_for_form(
    spec: Any,
    form: Mapping[str, Any],
    request: Mapping[str, Any],
    output_root: str | Path,
    cancel: threading.Event | None = None,
) -> PreparationOutcome:
    """Prepare the clip the form names for the form's registered workflow and length.

    ``request`` carries the operator's ``start``, ``end``, ``unit`` and ``fps_conversion``.  A
    workflow that cannot honestly offer preparation returns a failed outcome, not an exception."""

    try:
        contract = motion_source_contract(spec, form.get("frame_count"))
        window = MotionSourceRequest(
            clip_path=str(form.get("pose_video_path") or ""),
            contract=contract,
            start=float(request.get("start") or 0),
            end=None if request.get("end") in (None, "") else float(request["end"]),
            unit=str(request.get("unit") or "seconds"),
            fps_conversion=str(request.get("fps_conversion") or FPS_CONVERSION_NONE),
        )
    except ValueError as exc:
        return PreparationOutcome(
            status=STATUS_FAILED_PREPARATION, message=str(exc), code="unavailable"
        )
    return prepare_motion_source(window, output_root=output_root, cancel=cancel)


__all__ = [
    "DEADLINE_SECONDS",
    "MAX_PREPARED_BYTES",
    "PREPARED_DIRNAME",
    "STATUS_CANCELLED",
    "STATUS_FAILED_PREPARATION",
    "STATUS_PREPARED",
    "MotionSourceRequest",
    "PreparationOutcome",
    "PreparedMotionSourceError",
    "build_encode_command",
    "build_file_md5_command",
    "build_window_md5_command",
    "parse_framemd5",
    "prepare_for_form",
    "prepare_motion_source",
    "prepared_destination",
    "sha256_file",
    "target_pixel_format",
    "validate_prepared_record",
]

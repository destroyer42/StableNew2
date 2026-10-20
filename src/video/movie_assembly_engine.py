"""Execution of a frozen Movie Clips assembly (PR-VID-ASM-332).

Only the ``movie_assembly`` stage handler calls ``run_movie_assembly``, inside ``PipelineRunner.run_njr``. A run:

1. re-hashes every frozen input and refuses if any is missing or changed (fresh runs, replays and retries alike);
2. stages each still as an EXIF-oriented RGB PNG in a private folder;
3. runs one FFmpeg command through ``run_ffmpeg`` (contained, time-bounded, cancellable): every input is fitted
   (``scale`` + ``pad``) to the target frame, resampled to the target rate (``fps``) and cut to its exact frame count
   (``tpad`` + ``trim``), neighbours are crossfaded with ``xfade`` (or joined with ``concat``), and the result goes
   through the shared BT.709 encode chain and ``VideoEncodeSettings``; an optional music track is padded or cut to
   the movie's length and faded out;
4. publishes the file under its final name only after FFmpeg succeeded and writes a manifest next to it.

Partial files are removed on any failure or cancel. Nothing here loads a model or touches a GPU.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.replay_input_verification import (
    assembly_input_checks,
    sha256_of,
    verify_inputs,
)
from src.pipeline.video import (
    ENCODE_TIMEOUT_SECONDS,
    VideoEncodeCancelled,
    VideoEncodeSettings,
    build_video_encode_args,
    build_video_encode_filter,
    resolve_ffmpeg_executable,
    run_ffmpeg,
)
from src.utils.atomic_io import atomic_write_json
from src.video.movie_assembly_models import (
    CLIP_KIND_IMAGE,
    MODE_SEQUENCE,
    AssemblyAudio,
    AssemblyTimeline,
    MovieAssemblySpec,
    MovieAssemblySpecError,
    plan_timeline,
)

ENGINE_ID = "stablenew_assembly"
MANIFEST_SCHEMA = "stablenew.movie_assembly_manifest.v1"
AUDIO_ENCODE_ARGS = ("-c:a", "aac", "-b:a", "192k")
#: The encode bound grows with the movie (``slow`` x264 at 4K is far from real time) but always has a ceiling.
TIMEOUT_SECONDS_PER_OUTPUT_SECOND = 30.0
MAX_ENCODE_TIMEOUT_SECONDS = 4 * 3600.0
_STDERR_TAIL_CHARS = 600


class MovieAssemblyError(RuntimeError):
    """The assembly could not be produced; the message is written for the operator."""


class MovieAssemblyInputError(MovieAssemblyError):
    """A frozen input is missing or no longer matches the digest recorded at admission."""


@dataclass(frozen=True, slots=True)
class MovieAssemblyOutcome:
    output_path: Path
    manifest_path: Path
    output_sha256: str
    timeline: AssemblyTimeline


def encode_timeout_seconds(timeline: AssemblyTimeline) -> float:
    scaled = timeline.duration_seconds * TIMEOUT_SECONDS_PER_OUTPUT_SECOND
    return min(MAX_ENCODE_TIMEOUT_SECONDS, max(ENCODE_TIMEOUT_SECONDS, scaled))


def _seconds(frames: int, fps: int) -> str:
    # Microsecond precision: FFmpeg reads durations in microseconds and rescales them to the 1/fps time base with
    # rounding, so a value within half a frame of the boundary lands exactly on it.
    return f"{frames / fps:.6f}"


def _fit_chain(spec: MovieAssemblySpec) -> str:
    """Fit any input inside the target frame (aspect kept, black bars), square pixels, planar RGB for blending."""

    width, height = spec.width, spec.height
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=gbrp"
    )


def _audio_filter(audio: AssemblyAudio, timeline: AssemblyTimeline, input_index: int) -> str:
    """Pad a short track with silence and cut a long one, so the music always ends with the picture."""

    end = timeline.duration_seconds
    chain = f"[{input_index}:a]apad,atrim=end={end:.6f},asetpts=PTS-STARTPTS"
    fade = min(float(audio.fade_out_seconds), end)
    if fade > 0:
        chain += f",afade=t=out:st={end - fade:.6f}:d={fade:.6f}"
    return chain + "[aout]"


def _output_args(
    spec: MovieAssemblySpec, timeline: AssemblyTimeline, output_path: Path
) -> list[str]:
    encode = VideoEncodeSettings(
        crf=spec.encode.crf, preset=spec.encode.preset, pix_fmt=spec.encode.pix_fmt
    )
    args = ["-map", "[vout]"]
    if spec.audio is not None:
        args += ["-map", "[aout]", *AUDIO_ENCODE_ARGS, "-shortest"]
    args += build_video_encode_args(
        codec=spec.encode.codec, settings=encode, output_path=output_path, include_filter=False
    )
    return [*args, "-frames:v", str(timeline.total_frames), str(output_path)]


def _command_head(ffmpeg: Path | str) -> list[str]:
    return [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]


def _audio_input(spec: MovieAssemblySpec) -> list[str]:
    if spec.audio is None:
        return []
    return ["-protocol_whitelist", "file", "-i", spec.audio.path]


def build_slideshow_command(
    spec: MovieAssemblySpec,
    timeline: AssemblyTimeline,
    *,
    ffmpeg: Path | str,
    sources: list[Path],
    output_path: Path,
) -> list[str]:
    """One FFmpeg command for a slideshow: ``sources[i]`` is clip ``i`` (a staged still or the verified video)."""

    if len(sources) != len(spec.clips):
        raise MovieAssemblyError("every clip needs exactly one source file")
    fps = timeline.fps
    command = _command_head(ffmpeg)
    chains: list[str] = []
    fit = _fit_chain(spec)
    for index, (clip, source, frames) in enumerate(
        zip(spec.clips, sources, timeline.clip_frames, strict=True)
    ):
        command += ["-protocol_whitelist", "file"]
        if clip.kind == CLIP_KIND_IMAGE:
            command += ["-loop", "1", "-framerate", str(fps), "-t", _seconds(frames, fps)]
        command += ["-i", str(source)]
        # tpad clones the last frame so a clip that decodes a little short still fills exactly ``frames`` frames.
        chains.append(
            f"[{index}:v]{fit},fps={fps},"
            f"tpad=stop_mode=clone:stop_duration={_seconds(frames + fps, fps)},"
            f"trim=end_frame={frames},setpts=PTS-STARTPTS[v{index}]"
        )
    encode = build_video_encode_filter()
    count = len(spec.clips)
    if count == 1:
        chains.append(f"[v0]{encode}[vout]")
    elif timeline.transition_frames == 0:
        joined = "".join(f"[v{index}]" for index in range(count))
        chains.append(f"{joined}concat=n={count}:v=1:a=0,{encode}[vout]")
    else:
        previous = "v0"
        duration = _seconds(timeline.transition_frames, fps)
        for index, offset in enumerate(timeline.transition_offsets, start=1):
            label = f"x{index}"
            chains.append(
                f"[{previous}][v{index}]xfade=transition=fade:duration={duration}:"
                f"offset={_seconds(offset, fps)}[{label}]"
            )
            previous = label
        chains.append(f"[{previous}]{encode}[vout]")
    command += _audio_input(spec)
    if spec.audio is not None:
        chains.append(_audio_filter(spec.audio, timeline, count))
    command += ["-filter_complex", ";".join(chains)]
    return command + _output_args(spec, timeline, output_path)


def build_sequence_command(
    spec: MovieAssemblySpec,
    timeline: AssemblyTimeline,
    *,
    ffmpeg: Path | str,
    frame_pattern: Path,
    output_path: Path,
) -> list[str]:
    """One FFmpeg command for a frame sequence: the staged, numbered frames in list order, one per frame."""

    command = _command_head(ffmpeg) + [
        "-framerate",
        str(timeline.fps),
        "-start_number",
        "0",
        "-protocol_whitelist",
        "file",
        "-i",
        str(frame_pattern),
    ]
    chains = [f"[0:v]{_fit_chain(spec)},{build_video_encode_filter()}[vout]"]
    command += _audio_input(spec)
    if spec.audio is not None:
        chains.append(_audio_filter(spec.audio, timeline, 1))
    command += ["-filter_complex", ";".join(chains)]
    return command + _output_args(spec, timeline, output_path)


def verify_assembly_inputs(spec: MovieAssemblySpec, *, hash_file: Any = sha256_of) -> None:
    """Refuse when any frozen clip or the audio track is missing or changed since admission."""

    issues = verify_inputs(assembly_input_checks(spec.to_dict()), hash_file=hash_file)
    if issues:
        details = "; ".join(issue.describe() for issue in issues)
        raise MovieAssemblyInputError(
            f"Movie assembly inputs are no longer the ones that were queued: {details}"
        )


def stage_still(source: Path, target: Path) -> None:
    """Write ``source`` as an RGB PNG the way it is displayed: EXIF rotation applied, transparency over black."""

    with Image.open(source) as image:
        oriented = ImageOps.exif_transpose(image)
        if oriented.mode in ("RGBA", "LA", "PA") or "transparency" in oriented.info:
            rgba = oriented.convert("RGBA")
            frame = Image.new("RGB", rgba.size, (0, 0, 0))
            frame.paste(rgba, mask=rgba.getchannel("A"))
        else:
            frame = oriented.convert("RGB")
        frame.save(target, format="PNG", compress_level=1)


def _check_cancel(cancel_token: CancelToken | None) -> None:
    if cancel_token is not None and cancel_token.is_cancelled():
        raise CancellationError("Movie assembly was cancelled")


def _unique_output_path(run_dir: Path, clip_name: str) -> Path:
    candidate = run_dir / f"{clip_name}.mp4"
    counter = 2
    while candidate.exists():
        candidate = run_dir / f"{clip_name}_{counter}.mp4"
        counter += 1
    return candidate


def _stderr_tail(stderr: str) -> str:
    text = " ".join(str(stderr or "").split())
    return text[-_STDERR_TAIL_CHARS:] or "no error output"


def _manifest_payload(
    spec: MovieAssemblySpec,
    timeline: AssemblyTimeline,
    *,
    output_path: Path,
    output_sha256: str,
    job_id: str,
) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "stage": "movie_assembly",
        "engine": ENGINE_ID,
        "job_id": job_id,
        "output_path": str(output_path),
        "output_sha256": output_sha256,
        "width": spec.width,
        "height": spec.height,
        "fps": timeline.fps,
        "total_frames": timeline.total_frames,
        "duration_seconds": round(timeline.duration_seconds, 6),
        "timeline": {
            "clip_frames": list(timeline.clip_frames),
            "transition_frames": timeline.transition_frames,
            "transition_offsets": list(timeline.transition_offsets),
        },
        "spec": spec.to_dict(),
    }


def run_movie_assembly(
    spec: MovieAssemblySpec,
    *,
    run_dir: Path,
    cancel_token: CancelToken | None = None,
    ffmpeg: Path | str | None = None,
    hash_file: Any = sha256_of,
    job_id: str = "",
) -> MovieAssemblyOutcome:
    """Produce the movie a frozen spec describes under ``run_dir``.

    Raises ``MovieAssemblyInputError`` for a changed input, ``CancellationError`` on cancel and ``MovieAssemblyError``
    for anything else; no partial output is left behind in any of these cases.
    """

    errors = spec.validate()
    if errors:
        raise MovieAssemblyError("The frozen movie assembly is invalid: " + "; ".join(errors))
    try:
        timeline = plan_timeline(spec)
    except MovieAssemblySpecError as exc:
        raise MovieAssemblyError(str(exc)) from exc
    _check_cancel(cancel_token)
    verify_assembly_inputs(spec, hash_file=hash_file)
    _check_cancel(cancel_token)
    executable = ffmpeg if ffmpeg is not None else resolve_ffmpeg_executable()
    if executable is None:
        raise MovieAssemblyError(
            "FFmpeg was not found, so the movie cannot be assembled. Install FFmpeg or set STABLENEW_FFMPEG_PATH."
        )

    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = _unique_output_path(run_dir, spec.clip_name)
    partial_path = output_path.with_name(f"{output_path.stem}.assembling{output_path.suffix}")
    manifest_path = run_dir / "manifests" / f"{output_path.stem}_movie_assembly.json"
    staging = Path(tempfile.mkdtemp(prefix=".asm_", dir=str(run_dir)))  # short: Windows MAX_PATH
    output_sha256 = ""
    published = False
    try:
        if spec.mode == MODE_SEQUENCE:
            for index, clip in enumerate(spec.clips):
                _check_cancel(cancel_token)
                stage_still(Path(clip.path), staging / f"f{index:06d}.png")
            command = build_sequence_command(
                spec,
                timeline,
                ffmpeg=executable,
                frame_pattern=staging / "f%06d.png",
                output_path=partial_path,
            )
        else:
            sources: list[Path] = []
            for index, clip in enumerate(spec.clips):
                _check_cancel(cancel_token)
                if clip.kind == CLIP_KIND_IMAGE:
                    staged = staging / f"s{index:04d}.png"
                    stage_still(Path(clip.path), staged)
                    sources.append(staged)
                else:
                    sources.append(Path(clip.path))
            command = build_slideshow_command(
                spec, timeline, ffmpeg=executable, sources=sources, output_path=partial_path
            )
        cancel = None if cancel_token is None else cancel_token.is_cancelled
        try:
            result = run_ffmpeg(
                command, timeout_seconds=encode_timeout_seconds(timeline), cancel=cancel
            )
        except VideoEncodeCancelled as exc:
            raise CancellationError("Movie assembly was cancelled") from exc
        if result.returncode != 0 or not partial_path.is_file() or partial_path.stat().st_size == 0:
            raise MovieAssemblyError(
                f"FFmpeg could not assemble the movie: {_stderr_tail(result.stderr)}"
            )
        os.replace(partial_path, output_path)
        output_sha256 = sha256_of(output_path)
        atomic_write_json(
            manifest_path,
            _manifest_payload(
                spec, timeline, output_path=output_path, output_sha256=output_sha256, job_id=job_id
            ),
            indent=2,
        )
        published = True
    finally:
        if not published:
            partial_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
    return MovieAssemblyOutcome(
        output_path=output_path,
        manifest_path=manifest_path,
        output_sha256=output_sha256,
        timeline=timeline,
    )


__all__ = [
    "ENGINE_ID",
    "MANIFEST_SCHEMA",
    "MovieAssemblyError",
    "MovieAssemblyInputError",
    "MovieAssemblyOutcome",
    "build_sequence_command",
    "build_slideshow_command",
    "encode_timeout_seconds",
    "run_movie_assembly",
    "stage_still",
    "verify_assembly_inputs",
]

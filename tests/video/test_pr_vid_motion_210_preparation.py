"""PR-VID-MOTION-210: producing, verifying and re-verifying a prepared driving clip.

Real FFmpeg fixtures are generated into ``tmp_path`` (deterministic CPU work, a few KB each) and the
tests are skipped when FFmpeg is absent.  Expected frames are decoded here independently with
``framemd5`` -- the module under test is never asked to certify itself.  The failure paths use a
recording runner, so no process outcome has to be provoked for real.
"""

from __future__ import annotations

import copy
import hashlib
import os
import subprocess
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from src.pipeline.video import resolve_ffmpeg_executable
from src.utils.managed_process import ProcessOutcome
from src.video import motion_source_preparation as prep
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.driving_video_inspection import (
    PREVIEW_FRAME_COUNT,
    DrivingVideoFacts,
    DrivingVideoInspection,
    inspect_driving_video,
    run_bounded_process,
)
from src.video.motion_source_plan import (
    FPS_CONVERSION_NONE,
    FPS_CONVERSION_WORKFLOW_RATE,
    MotionSourceContract,
)
from src.video.motion_source_preparation import (
    MotionSourceRequest,
    PreparedMotionSourceError,
    prepare_motion_source,
    validate_prepared_record,
)

FFMPEG = resolve_ffmpeg_executable()
FFPROBE = resolve_ffprobe_executable()
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="FFmpeg/FFprobe are not installed"
)
NONE, CONVERT = FPS_CONVERSION_NONE, FPS_CONVERSION_WORKFLOW_RATE


def _contract(frames: int = 17, *, version: str = "1.2.0") -> MotionSourceContract:
    return MotionSourceContract("wan_animate2_drive_i2v_v1", version, frames, 24, "rev", "rule")


def _run(*args: object) -> None:
    subprocess.run([str(a) for a in args], check=True, capture_output=True, timeout=120)


def _clip(
    tmp_path: Path,
    name: str = "clip.mp4",
    *,
    rate: str = "30",
    frames: int = 60,
    size: str = "64x48",
    pix_fmt: str = "yuv420p",
    codec: str = "libx264",
) -> Path:
    path = tmp_path / name
    _run(
        FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}",
        "-frames:v", frames, "-pix_fmt", pix_fmt, "-c:v", codec, path,
    )  # fmt: skip
    return path


def _digests(path: Path, pix_fmt: str = "yuv420p") -> list[str]:
    """Independent per-frame fingerprints of every frame a decoder yields for ``path``."""

    result = subprocess.run(
        [str(FFMPEG), "-v", "error", "-nostdin", "-noautorotate", "-i", str(path), "-map", "0:v:0", "-an",
         "-fps_mode", "passthrough", "-pix_fmt", pix_fmt, "-f", "framemd5", "-"],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    return [
        line.rsplit(",", 1)[-1].strip()
        for line in result.stdout.decode().splitlines()
        if line and not line.startswith("#")
    ]


def _prepare(clip: Path, tmp_path: Path, contract: MotionSourceContract | None = None, **kw: Any):
    return prepare_motion_source(
        MotionSourceRequest(str(clip), contract or _contract(), **kw),
        output_root=tmp_path / "out",
    )


def _published(tmp_path: Path) -> list[str]:
    folder = tmp_path / "out" / prep.PREPARED_DIRNAME
    return sorted(item.name for item in folder.iterdir()) if folder.exists() else []


# ------------------------------------------------------------------------------ exact frames


@needs_ffmpeg
def test_without_conversion_the_file_holds_exactly_the_window_frames_in_order(tmp_path):
    clip = _clip(tmp_path)
    source = _digests(clip)
    outcome = _prepare(clip, tmp_path, start=5, unit="frames")

    assert outcome.prepared, outcome.message
    record = outcome.record
    derived = Path(record["derived"]["path"])
    assert _digests(derived) == source[5 : 5 + 17]  # frames 5..21, nothing else, in order
    assert outcome.plan.source_indices == tuple(range(5, 22))
    # Geometry, rate, length and the file's identity are all recorded and true.
    assert (record["derived"]["width"], record["derived"]["height"]) == (64, 48)
    assert record["derived"]["frames"] == 17 and record["derived"]["frame_rate"] == "30/1"
    assert derived.name == f"{hashlib.sha256(derived.read_bytes()).hexdigest()}.mp4"
    assert record["derived"]["sha256"] == derived.stem
    assert record["derived"]["size_bytes"] == derived.stat().st_size
    assert record["original"]["sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
    assert (
        record["derived"]["frames_md5_sha256"]
        == hashlib.sha256("\n".join(source[5:22]).encode()).hexdigest()
    )
    assert _published(tmp_path) == [derived.name]  # no temporary left behind


@needs_ffmpeg
@pytest.mark.parametrize("rate", ["12", "15", "25", "30", "50", "60", "30000/1001", "24000/1001"])
def test_a_rate_conversion_selects_exactly_the_planned_source_frames(tmp_path, rate):
    clip = _clip(tmp_path, rate=rate, frames=90)
    source = _digests(clip)
    outcome = _prepare(
        clip, tmp_path, _contract(25), start=3, unit="frames", fps_conversion=CONVERT
    )

    assert outcome.prepared, outcome.message
    derived = Path(outcome.record["derived"]["path"])
    expected = [source[index] for index in outcome.plan.source_indices]
    assert _digests(derived) == expected
    assert len(expected) == 25 and outcome.record["derived"]["frame_rate"] == "24/1"
    if rate in {"12", "15"}:  # up-conversion repeats, never invents, frames
        assert outcome.plan.repeated and not outcome.plan.omitted
    if rate in {"50", "60"}:
        assert outcome.plan.omitted and not outcome.plan.repeated


@needs_ffmpeg
def test_a_short_clip_is_held_to_the_requested_length_and_says_so(tmp_path):
    clip = _clip(tmp_path, frames=20)
    source = _digests(clip)
    outcome = _prepare(clip, tmp_path, start=15, unit="frames")

    assert outcome.prepared, outcome.message
    assert outcome.plan.held_frames == 17 - 5 and outcome.plan.window_end == 20
    assert _digests(Path(outcome.record["derived"]["path"])) == source[15:20] + [source[19]] * 12
    assert any(
        line.startswith("Held: the clip ends at source frame 19") for line in outcome.explanation
    )


@needs_ffmpeg
def test_an_operator_window_end_bounds_the_frames_used(tmp_path):
    clip = _clip(tmp_path)
    source = _digests(clip)
    outcome = _prepare(clip, tmp_path, _contract(9), start=10, end=14, unit="frames")

    assert outcome.prepared, outcome.message
    assert _digests(Path(outcome.record["derived"]["path"])) == source[10:14] + [source[13]] * 5
    assert outcome.record["settings"]["end_frame"] == 14


@needs_ffmpeg
def test_seconds_are_placed_on_the_clips_exact_timeline(tmp_path):
    clip = _clip(tmp_path, rate="30000/1001")
    source = _digests(clip)
    outcome = _prepare(clip, tmp_path, start=1.0, unit="seconds")  # 29.97 fps: 1 s is frame 30

    assert outcome.prepared, outcome.message
    assert outcome.record["settings"]["start_frame"] == 30
    assert outcome.record["settings"]["requested"] == {"start": 1.0, "end": None, "unit": "seconds"}
    assert _digests(Path(outcome.record["derived"]["path"])) == source[30:47]
    assert outcome.record["derived"]["frame_rate"] == "30000/1001"  # nothing converted


@needs_ffmpeg
def test_the_same_request_publishes_the_same_bytes_once(tmp_path):
    clip = _clip(tmp_path)
    first = _prepare(clip, tmp_path, start=2, unit="frames")
    derived = Path(first.record["derived"]["path"])
    stamp = derived.stat().st_mtime_ns
    second = _prepare(clip, tmp_path, start=2, unit="frames")

    assert first.record == second.record  # no timestamp, no randomness
    assert derived.stat().st_mtime_ns == stamp  # the published file was not rewritten
    assert _published(tmp_path) == [derived.name]
    other = _prepare(clip, tmp_path, start=3, unit="frames")
    assert other.record["derived"]["sha256"] != first.record["derived"]["sha256"]
    assert len(_published(tmp_path)) == 2


@needs_ffmpeg
def test_the_preview_is_the_published_file_at_exact_frames(tmp_path):
    clip = _clip(tmp_path)
    outcome = _prepare(clip, tmp_path, start=0, unit="frames")

    preview = outcome.preview
    assert Path(preview.path) == Path(outcome.record["derived"]["path"])
    assert preview.facts.frame_count == 17
    assert len(preview.frames) == PREVIEW_FRAME_COUNT
    assert outcome.preview_captions == (
        "Output frame 0 (source frame 0)",
        "Output frame 8 (source frame 8)",
        "Output frame 16 (source frame 16)",
    )
    # The thumbnails really are frames 0, 8 and 16: compare to the same frames of the original.
    import io

    from PIL import Image

    for frame, index in zip(preview.frames, (0, 8, 16), strict=True):
        direct = inspect_driving_video(
            clip, positions=[max(0.0, (index - 0.5) / 30.0)], frame_count=1
        ).frames[0]
        left = Image.open(io.BytesIO(frame.png_bytes)).convert("RGB")
        right = Image.open(io.BytesIO(direct.png_bytes)).convert("RGB")
        assert left.size == right.size and list(left.getdata()) == list(right.getdata())


# ------------------------------------------------------------------------------ formats


@needs_ffmpeg
@pytest.mark.parametrize("pix_fmt", ["yuvj420p", "yuv422p", "yuv444p", "yuv420p10le"])
def test_other_pixel_formats_are_kept_without_loss(tmp_path, pix_fmt):
    clip = _clip(tmp_path, frames=40, pix_fmt=pix_fmt)
    outcome = _prepare(clip, tmp_path, start=4, unit="frames")

    assert outcome.prepared, outcome.message
    derived = Path(outcome.record["derived"]["path"])
    assert _digests(derived, pix_fmt) == _digests(clip, pix_fmt)[4:21]
    assert outcome.record["derived"]["pixel_format"] == pix_fmt


@needs_ffmpeg
def test_a_pixel_format_that_cannot_be_kept_losslessly_is_refused_before_any_work(tmp_path):
    clip = _clip(tmp_path, frames=30, pix_fmt="gbrp", codec="libx264rgb")
    outcome = _prepare(clip, tmp_path)

    assert outcome.status == prep.STATUS_FAILED_PREPARATION
    assert outcome.code == "unsupported_pixel_format" and "gbrp" in outcome.message
    assert _published(tmp_path) == []


@needs_ffmpeg
def test_a_rotated_phone_clip_keeps_its_rotation_metadata_so_the_consumer_turns_it_as_before(
    tmp_path,
):
    base = _clip(tmp_path, "base.mp4", frames=30)
    rotated = tmp_path / "rotated.mp4"
    _run(
        FFMPEG,
        "-v",
        "error",
        "-y",
        "-display_rotation:v:0",
        "90",
        "-i",
        base,
        "-c",
        "copy",
        rotated,
    )
    facts = inspect_driving_video(rotated, frame_count=0).facts
    assert facts.rotation_quadrants % 2 == 1 and (facts.display_width, facts.display_height) == (
        48,
        64,
    )

    outcome = _prepare(rotated, tmp_path)
    assert outcome.prepared, outcome.message
    derived = Path(outcome.record["derived"]["path"])
    derived_facts = inspect_driving_video(derived, frame_count=0).facts
    # The same stored pixels and the same display rotation: whatever turns the original turns this.
    assert (derived_facts.coded_width, derived_facts.coded_height) == (64, 48)
    assert derived_facts.rotation_quadrants == facts.rotation_quadrants
    assert (outcome.record["derived"]["width"], outcome.record["derived"]["height"]) == (48, 64)
    assert outcome.record["derived"]["rotation_quadrants"] == facts.rotation_quadrants
    assert outcome.record["original"]["rotation_quadrants"] == facts.rotation_quadrants
    assert _digests(derived) == _digests(rotated)[:17]  # stored frames, bit for bit


def test_a_build_that_drops_the_rotation_is_not_accepted(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"clip bytes")
    recorder = _Recorder(
        window=ProcessOutcome(returncode=0, stdout=_md5_lines(60)),
        encode=_encode_writes(tmp_path),
        verify=ProcessOutcome(returncode=0, stdout=_md5_lines(17)),  # the planned frames 0..16
    )

    def inspect(path, **kwargs):
        if Path(path) == clip.resolve():  # the original is rotated ...
            facts = _facts(rotation_quadrants=1, display_width=48, display_height=64)
        else:  # ... and the output lost the tag
            facts = _facts(reported_frame_count=17)
        return DrivingVideoInspection(path=str(path), status="ok", facts=facts)

    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract()),
        output_root=tmp_path / "out",
        runner=recorder,
        ffmpeg="ffmpeg",
        inspect=inspect,
    )
    assert result.code == "verification_failed" and "rotation" in result.message
    assert result.record is None
    assert _published(tmp_path) == []  # checked before anything was published


# ------------------------------------------------------------------------------ refusals


@needs_ffmpeg
def test_a_start_beyond_the_clip_is_refused_and_publishes_nothing(tmp_path):
    clip = _clip(tmp_path, frames=20)
    outcome = _prepare(clip, tmp_path, start=500, unit="frames")

    assert (
        outcome.status == prep.STATUS_FAILED_PREPARATION and outcome.code == "no_frames_in_window"
    )
    assert _published(tmp_path) == [] and outcome.record is None


@needs_ffmpeg
def test_the_output_size_cap_stops_an_oversized_result_and_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(prep, "MAX_PREPARED_BYTES", 2000)
    clip = _clip(tmp_path)
    outcome = _prepare(clip, tmp_path)

    assert outcome.code == "output_too_large" and "lower-resolution" in outcome.message
    assert _published(tmp_path) == []


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"start": -1, "unit": "frames"}, "window_invalid"),
        ({"start": 4, "end": 4, "unit": "frames"}, "window_invalid"),
        ({"start": 1.5, "unit": "frames"}, "window_invalid"),
        ({"start": 0, "unit": "furlongs"}, "window_invalid"),
        ({"start": 0, "fps_conversion": "magic"}, "window_invalid"),
    ],
)
def test_invalid_windows_are_refused_without_decoding(tmp_path, kwargs, code):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    outcome = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract(), **kwargs),
        output_root=tmp_path / "out",
        runner=_Recorder(),
        ffmpeg="ffmpeg",
        inspect=_fake_inspect(),
    )
    assert outcome.status == prep.STATUS_FAILED_PREPARATION and outcome.code == code


def test_missing_and_unsupported_files_are_typed_failures(tmp_path):
    for name, code in (("absent.mp4", "file_missing"), ("clip.avi", "unsupported_file")):
        path = tmp_path / name
        if code == "unsupported_file":
            path.write_bytes(b"x")
        outcome = prepare_motion_source(
            MotionSourceRequest(str(path), _contract()),
            output_root=tmp_path / "out",
            ffmpeg="ffmpeg",
        )
        assert outcome.code == code and not outcome.prepared


# ------------------------------------------------------------------------------ orchestration


def _facts(**overrides: Any) -> DrivingVideoFacts:
    values: dict[str, Any] = {
        "container_format": "mov,mp4", "codec_name": "h264", "pixel_format": "yuv420p", "coded_width": 64,
        "coded_height": 48, "rotation_quadrants": 0, "display_width": 64, "display_height": 48,
        "sample_aspect_ratio": "", "reported_fps": 30.0, "fps_basis": "average", "fps_is_variable_suspected": False,
        "reported_frame_count": 60, "estimated_frame_count": None, "frame_count_basis": "reported",
        "duration_seconds": 2.0, "duration_basis": "stream", "fps_rational": "30/1",
    }  # fmt: skip
    values.update(overrides)
    return DrivingVideoFacts(**values)


def _fake_inspect(facts: DrivingVideoFacts | None = None, *, status: str = "ok"):
    def inspect(path, **_kwargs):
        return DrivingVideoInspection(
            path=str(path), status=status, facts=facts or _facts(), frames=(), issues=()
        )

    return inspect


class _Recorder:
    """Runs nothing; returns scripted outcomes keyed by the pass being run."""

    def __init__(self, **by_pass: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.by_pass = by_pass

    @staticmethod
    def which(command: Sequence[str]) -> str:
        if "-version" in command:
            return "version"
        if command[-1] == "-" and "select" in " ".join(command):
            return "window"
        if command[-1] == "-":
            return "verify"
        return "encode"

    def __call__(self, command, *, timeout_seconds, max_stdout_bytes, cancel=None):
        kind = self.which(command)
        self.calls.append(
            {
                "kind": kind,
                "command": list(command),
                "timeout": timeout_seconds,
                "cap": max_stdout_bytes,
            }
        )
        result = self.by_pass.get(kind)
        return result(command) if callable(result) else (result or ProcessOutcome(returncode=0))


def _md5_lines(count: int, salt: str = "") -> bytes:
    rows = [
        f"0, {i}, {i}, 1, 100, {hashlib.md5(f'{salt}{i}'.encode()).hexdigest()}"
        for i in range(count)
    ]
    return ("#format: frame checksums\n" + "\n".join(rows) + "\n").encode()


def _scripted(tmp_path: Path, **by_pass: Any) -> tuple[_Recorder, Path]:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"clip bytes")
    by_pass.setdefault("window", ProcessOutcome(returncode=0, stdout=_md5_lines(60)))
    return _Recorder(**by_pass), clip


def _encode_writes(tmp_path: Path, size: int = 64):
    def write(command):
        Path(command[-1]).write_bytes(b"x" * size)
        return ProcessOutcome(returncode=0)

    return write


def _scripted_outcome(tmp_path: Path, recorder: _Recorder, clip: Path, **kw: Any):
    return prepare_motion_source(
        MotionSourceRequest(str(clip), _contract(), **kw),
        output_root=tmp_path / "out",
        runner=recorder,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        inspect=_fake_inspect(),
    )


def test_every_ffmpeg_pass_is_bounded_and_uses_an_argument_list(tmp_path):
    recorder, clip = _scripted(
        tmp_path,
        encode=_encode_writes(tmp_path),
        verify=ProcessOutcome(returncode=0, stdout=_md5_lines(60)),
    )
    _scripted_outcome(tmp_path, recorder, clip, start=2, unit="frames")  # fails verification: fine

    kinds = [call["kind"] for call in recorder.calls]
    assert kinds[:3] == ["window", "encode", "verify"]
    for call in recorder.calls:
        assert isinstance(call["command"], list) and all(
            isinstance(x, str) for x in call["command"]
        )
        assert call["timeout"] <= prep.PASS_TIMEOUT_SECONDS or call["kind"] == "version"
        assert call["cap"] in {prep.MAX_MD5_STDOUT_BYTES, prep.MAX_VERSION_STDOUT_BYTES}
        if call["kind"] != "version":
            index = call["command"].index("-protocol_whitelist")
            assert call["command"][index + 1] == "file"  # no network, no concat, no pipe protocols
            allowed = call["command"][call["command"].index("-format_whitelist") + 1].split(",")
            assert "matroska" in allowed and "hls" not in allowed and "concat" not in allowed
            assert "-nostdin" in call["command"] and "-an" in call["command"]
    encode = next(call["command"] for call in recorder.calls if call["kind"] == "encode")
    assert encode[encode.index("-fs") + 1] == str(prep.MAX_PREPARED_BYTES + 1)
    assert "+bitexact" in encode and encode[encode.index("-frames:v") + 1] == "17"
    assert encode[encode.index("-c:v") + 1] == "libx264" and encode[encode.index("-qp") + 1] == "0"
    assert _published(tmp_path) == []  # the failed run left no temporary behind


def test_a_mismatch_between_the_plan_and_the_file_publishes_nothing(tmp_path):
    recorder, clip = _scripted(
        tmp_path,
        encode=_encode_writes(tmp_path),
        verify=ProcessOutcome(returncode=0, stdout=_md5_lines(17, salt="different")),
    )
    outcome = _scripted_outcome(tmp_path, recorder, clip, start=2, unit="frames")

    assert outcome.code == "verification_failed" and outcome.record is None
    assert _published(tmp_path) == []  # not even the temporary file


def test_a_file_with_the_wrong_number_of_frames_is_refused(tmp_path):
    recorder, clip = _scripted(
        tmp_path,
        encode=_encode_writes(tmp_path),
        verify=ProcessOutcome(returncode=0, stdout=_md5_lines(16)),
    )
    assert _scripted_outcome(tmp_path, recorder, clip).code == "verification_failed"
    assert _published(tmp_path) == []


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (ProcessOutcome(returncode=None, launch_error="no such file"), "ffmpeg_unavailable"),
        (ProcessOutcome(returncode=None, timed_out=True), "timeout"),
        (ProcessOutcome(returncode=0, output_truncated=True), "output_too_large"),
        (ProcessOutcome(returncode=1, stderr=b"Error: boom\n"), "ffmpeg_failed"),
    ],
)
def test_process_failures_are_typed_and_leave_nothing_behind(tmp_path, outcome, code):
    for failing in ("window", "encode"):
        recorder, clip = _scripted(tmp_path, encode=_encode_writes(tmp_path))
        recorder.by_pass[failing] = outcome
        result = _scripted_outcome(tmp_path, recorder, clip)
        assert result.status == prep.STATUS_FAILED_PREPARATION and result.code == code
        assert _published(tmp_path) == [] and result.record is None


def test_an_empty_window_decode_is_a_failure_not_a_one_frame_guess(tmp_path):
    recorder, clip = _scripted(tmp_path, window=ProcessOutcome(returncode=0, stdout=b"#format\n"))
    assert _scripted_outcome(tmp_path, recorder, clip).code == "no_frames_in_window"


def test_cancelling_mid_encode_stops_with_no_job_record_and_no_files(tmp_path):
    event = threading.Event()

    def encode(command):
        Path(command[-1]).write_bytes(b"partial")  # what FFmpeg had written when it was killed
        event.set()
        return ProcessOutcome(returncode=None, cancelled=True)

    recorder, clip = _scripted(tmp_path, encode=encode)
    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract()),
        output_root=tmp_path / "out",
        runner=recorder,
        ffmpeg="ffmpeg",
        inspect=_fake_inspect(),
        cancel=event,
    )
    assert result.status == prep.STATUS_CANCELLED and result.record is None
    assert [call["kind"] for call in recorder.calls] == [
        "window",
        "encode",
    ]  # nothing after the cancel
    assert _published(tmp_path) == []


def test_a_cancel_set_before_the_work_starts_runs_no_process(tmp_path):
    event = threading.Event()
    event.set()
    recorder, clip = _scripted(tmp_path)
    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract()),
        output_root=tmp_path / "out",
        runner=recorder,
        ffmpeg="ffmpeg",
        inspect=_fake_inspect(),
        cancel=event,
    )
    assert result.status == prep.STATUS_CANCELLED and recorder.calls == []


def test_a_source_that_changes_while_it_is_prepared_is_not_accepted(tmp_path):
    def encode(command):
        Path(command[-1]).write_bytes(b"x" * 64)
        clip.write_bytes(b"clip bytes, edited meanwhile")
        return ProcessOutcome(returncode=0)

    recorder, clip = _scripted(
        tmp_path, encode=encode, verify=ProcessOutcome(returncode=0, stdout=_md5_lines(17))
    )
    result = _scripted_outcome(tmp_path, recorder, clip)
    assert result.code == "source_changed" and _published(tmp_path) == []


def test_a_variable_frame_rate_clip_cannot_be_converted_but_can_be_prepared(tmp_path):
    recorder, clip = _scripted(tmp_path)
    variable = _facts(fps_is_variable_suspected=True)
    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract(), fps_conversion=CONVERT),
        output_root=tmp_path / "out",
        runner=recorder,
        ffmpeg="ffmpeg",
        inspect=_fake_inspect(variable),
    )
    assert result.code == "variable_frame_rate" and recorder.calls == []
    unknown_rate = _facts(reported_fps=None, fps_rational="")
    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract(), start=1.0, unit="seconds"),
        output_root=tmp_path / "out",
        runner=recorder,
        ffmpeg="ffmpeg",
        inspect=_fake_inspect(unknown_rate),
    )
    assert result.code == "frame_rate_unknown" and recorder.calls == []


def test_missing_ffmpeg_is_reported_before_any_work(tmp_path, monkeypatch):
    monkeypatch.setattr(prep, "resolve_ffmpeg_executable", lambda: None)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract()), output_root=tmp_path
    )
    assert result.code == "ffmpeg_unavailable" and "STABLENEW_FFMPEG_PATH" in result.message


def test_a_probe_failure_is_surfaced_with_the_inspectors_reason(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"not a video")
    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract()),
        output_root=tmp_path / "out",
        runner=_Recorder(),
        ffmpeg="ffmpeg",
        inspect=lambda *a, **k: DrivingVideoInspection(path=str(clip), status="failed"),
    )
    assert result.code == "probe_failed" and not result.prepared


def test_only_this_modules_own_stale_temporaries_are_cleaned_up(tmp_path):
    folder = tmp_path / "out" / prep.PREPARED_DIRNAME
    folder.mkdir(parents=True)
    stale, fresh, other = (
        folder / ".preparing-stale.mp4",
        folder / ".preparing-fresh.mp4",
        folder / "notes.txt",
    )
    published = folder / ("0" * 64 + ".mp4")
    for item in (stale, fresh, other, published):
        item.write_bytes(b"x")
    for item in (stale, other, published):
        os.utime(item, (time.time() - 3 * 86400,) * 2)

    recorder, clip = _scripted(tmp_path, encode=_encode_writes(tmp_path))
    _scripted_outcome(tmp_path, recorder, clip)  # refused at verification, after the cleanup ran

    assert not stale.exists()  # abandoned by a hard kill more than a day ago
    assert fresh.exists()  # could belong to a run in progress
    assert other.exists() and published.exists()  # never anything this module did not name


# ------------------------------------------------------------------------------ admission-time check


@needs_ffmpeg
def test_a_prepared_record_is_reverified_against_the_bytes_and_the_form(tmp_path):
    clip = _clip(tmp_path)
    outcome = _prepare(clip, tmp_path, start=2, unit="frames")
    record = outcome.record
    contract = _contract()
    ok = validate_prepared_record(record, original_path=clip, contract=contract)
    assert ok == record and ok is not record and ok["plan"] is not record["plan"]
    ok["plan"]["source_indices"][0] = 99  # the caller's copy is independent
    assert record["plan"]["source_indices"][0] == 2

    def refused(mutated, **kw):
        with pytest.raises(PreparedMotionSourceError) as raised:
            validate_prepared_record(mutated, original_path=kw.pop("original", clip),
                                     contract=kw.pop("contract", contract))  # fmt: skip
        return str(raised.value)

    assert "not recognised" in refused({**record, "schema": "other"})
    assert "output frames 17" in refused(record, contract=_contract(25))
    assert "workflow version" in refused(record, contract=_contract(version="1.1.0"))
    assert "different driving video" in refused(record, original=tmp_path / "other.mp4")
    broken = copy.deepcopy(record)
    broken["plan"]["source_indices"].pop()
    assert "inconsistent" in refused(broken)
    renamed = copy.deepcopy(record)
    renamed["derived"]["sha256"] = "0" * 64
    assert "content-addressed" in refused(renamed)

    derived = Path(record["derived"]["path"])
    original_bytes = clip.read_bytes()
    clip.write_bytes(original_bytes + b"!")
    assert "driving video changed since it was prepared" in refused(record)
    clip.write_bytes(original_bytes)
    validate_prepared_record(record, original_path=clip, contract=contract)

    prepared_bytes = derived.read_bytes()
    derived.write_bytes(prepared_bytes[:-1] + bytes([prepared_bytes[-1] ^ 1]))  # one flipped bit
    assert "prepared motion source changed since it was prepared" in refused(record)
    derived.unlink()
    assert "no longer readable" in refused(record)


@needs_ffmpeg
def test_prepare_for_form_uses_the_registered_workflows_own_length_and_refuses_the_rest(tmp_path):
    from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort

    registry = DefaultWorkflowRegistryPort()
    drive = registry.get("wan_animate2_drive_i2v_v1", "1.2.0")
    clip = _clip(tmp_path)
    form = {"pose_video_path": str(clip), "frame_count": "21"}
    outcome = prep.prepare_for_form(
        drive, form, {"start": 3, "unit": "frames"}, tmp_path / "out", None
    )
    assert outcome.prepared and outcome.record["derived"]["frames"] == 21
    assert outcome.record["contract"]["workflow_version"] == "1.2.0"

    prompt = registry.get("wan_animate2_prompt_i2v_v1", "1.2.0")
    refused = prep.prepare_for_form(prompt, form, {}, tmp_path / "out", None)
    assert refused.code == "unavailable" and "no driving video" in refused.message
    illegal = prep.prepare_for_form(
        drive, {**form, "frame_count": "22"}, {}, tmp_path / "out", None
    )
    assert illegal.code == "unavailable" and "cannot generate 22 frames" in illegal.message
    garbage = prep.prepare_for_form(drive, form, {"start": "abc"}, tmp_path / "out", None)
    assert garbage.code == "unavailable" and not garbage.prepared


# ------------------------------------------------------------------------------ real cancellation


def test_the_real_runner_kills_a_cancelled_encode_leaving_no_file_or_child(tmp_path):
    """The encode command is swapped for a long-lived child so the timing is deterministic."""

    import sys

    import psutil

    pid_file = tmp_path / "child.pid"
    child = [
        sys.executable, "-c",
        f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(120)",
    ]  # fmt: skip
    event = threading.Event()
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"clip bytes")

    def runner(command, *, timeout_seconds, max_stdout_bytes, cancel=None):
        if _Recorder.which(command) == "window":
            return ProcessOutcome(returncode=0, stdout=_md5_lines(60))
        if _Recorder.which(command) == "version":
            return ProcessOutcome(returncode=0)
        Path(command[-1]).write_bytes(b"partial output")  # what a killed encoder leaves behind
        threading.Timer(0.5, event.set).start()
        return run_bounded_process(
            child, timeout_seconds=timeout_seconds, max_stdout_bytes=max_stdout_bytes, cancel=cancel
        )

    started = time.monotonic()
    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract()),
        output_root=tmp_path / "out",
        runner=runner,
        ffmpeg="ffmpeg",
        inspect=_fake_inspect(),
        cancel=event,
    )
    assert result.status == prep.STATUS_CANCELLED and result.record is None
    assert time.monotonic() - started < 30
    assert _published(tmp_path) == []
    pid = int(pid_file.read_text())
    for _ in range(100):
        if not psutil.pid_exists(pid):
            break
        time.sleep(0.05)
    assert not psutil.pid_exists(pid)  # no orphan survives the cancellation


def test_thumbnail_captions_follow_the_frames_that_were_decoded_not_their_order(tmp_path):
    from src.video.driving_video_inspection import PreviewFrame

    recorder, clip = _scripted(
        tmp_path,
        encode=_encode_writes(tmp_path),
        verify=ProcessOutcome(returncode=0, stdout=_md5_lines(17)),
    )

    def inspect(path, **kwargs):
        if Path(path) == clip.resolve():
            return DrivingVideoInspection(path=str(path), status="ok", facts=_facts())
        positions = kwargs["positions"]  # first, middle, last output frame
        frames = tuple(
            PreviewFrame(positions[i], 4, 4, b"png") for i in (0, 2)
        )  # the middle one failed
        return DrivingVideoInspection(
            path=str(path), status="partial", facts=_facts(reported_frame_count=17), frames=frames
        )

    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract()),
        output_root=tmp_path / "out",
        runner=recorder,
        ffmpeg="ffmpeg",
        inspect=inspect,
    )
    assert result.prepared, result.message
    assert result.preview_captions == (
        "Output frame 0 (source frame 0)",
        "Output frame 16 (source frame 16)",
    )


def test_a_frame_size_beyond_the_decode_cap_is_refused_before_any_process_runs(tmp_path):
    recorder, clip = _scripted(tmp_path)
    huge = _facts(coded_width=10000, coded_height=10000, display_width=10000, display_height=10000)
    result = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract()),
        output_root=tmp_path / "out",
        runner=recorder,
        ffmpeg="ffmpeg",
        inspect=_fake_inspect(huge),
    )
    assert result.code == "frame_too_large" and "megapixels" in result.message
    assert recorder.calls == [] and _published(tmp_path) == []


@needs_ffmpeg
def test_a_relative_output_root_still_yields_absolute_recorded_paths(tmp_path, monkeypatch):
    clip = _clip(tmp_path)
    monkeypatch.chdir(tmp_path)
    outcome = prepare_motion_source(
        MotionSourceRequest(str(clip), _contract(), start=1, unit="frames"),
        output_root="relative_out",
    )
    assert outcome.prepared, outcome.message
    derived = Path(outcome.record["derived"]["path"])
    assert derived.is_absolute() and derived.parent == (
        tmp_path / "relative_out" / prep.PREPARED_DIRNAME
    )
    assert not any(name.startswith(".preparing-") for name in os.listdir(derived.parent))

"""PR-VID-196 workstream B: bounded, read-only driving-video inspection.

Pure parsing and orchestration run against canned FFprobe JSON and a scripted runner; the bounded
process helper runs real (Python) children; real FFmpeg fixtures are generated into ``tmp_path`` and
skipped when FFmpeg is not installed.  No GUI, runtime, network or output directory is touched.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path

import pytest
from PIL import Image

from src.pipeline.video import resolve_ffmpeg_executable
from src.video import driving_video_inspection as dvi
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.driving_video_inspection import (
    ISSUE_CANCELLED,
    ISSUE_DEADLINE_EXCEEDED,
    ISSUE_FFMPEG_UNAVAILABLE,
    ISSUE_FFPROBE_UNAVAILABLE,
    ISSUE_FILE_MISSING,
    ISSUE_FRAME_DECODE_FAILED,
    ISSUE_FRAME_TIMEOUT,
    ISSUE_FRAME_TOO_LARGE,
    ISSUE_NO_VIDEO_STREAM,
    ISSUE_PROBE_FAILED,
    ISSUE_PROBE_OUTPUT_TOO_LARGE,
    ISSUE_PROBE_TIMEOUT,
    ISSUE_PROBE_UNREADABLE,
    MAX_PREVIEW_DECODE_PIXELS,
    PREVIEW_MAX_EDGE,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_PARTIAL,
    ProbeParseError,
    ProcessOutcome,
    build_frame_command,
    build_probe_command,
    inspect_driving_video,
    parse_probe_output,
    preview_positions,
    run_bounded_process,
)

FFMPEG = resolve_ffmpeg_executable()
FFPROBE = resolve_ffprobe_executable()
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="FFmpeg/FFprobe are not installed"
)


def _probe_json(**stream: object) -> bytes:
    base: dict[str, object] = {
        "codec_name": "h264",
        "width": 640,
        "height": 360,
        "pix_fmt": "yuv420p",
        "r_frame_rate": "30/1",
        "avg_frame_rate": "30/1",
        "duration": "2.000000",
        "nb_frames": "60",
    }
    base.update(stream)
    return json.dumps(
        {"streams": [base], "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "2.0"}}
    ).encode()


def _png(width: int = 16, height: int = 9) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, format="PNG")
    return buffer.getvalue()


class ScriptedRunner:
    """Replaces FFprobe/FFmpeg: the first call answers the probe, later calls answer frames."""

    def __init__(self, probe: ProcessOutcome, frames: Sequence[ProcessOutcome] = ()):
        self.probe = probe
        self.frames = list(frames)
        self.calls: list[tuple[list[str], float, int]] = []

    def __call__(self, command, *, timeout_seconds, max_stdout_bytes, cancel=None):
        self.calls.append((list(command), timeout_seconds, max_stdout_bytes))
        if len(self.calls) == 1:
            return self.probe
        return self.frames.pop(0) if self.frames else ProcessOutcome(returncode=1)


def _clip(tmp_path: Path, name: str = "drive.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 placeholder; a scripted runner never decodes it")
    return path


def _inspect(path: Path, runner, **kwargs):
    return inspect_driving_video(path, runner=runner, ffprobe="ffprobe-stub", ffmpeg="ffmpeg-stub", **kwargs)


# ------------------------------------------------------------------------------ probe parsing


def test_parse_reports_dimensions_rate_frames_and_duration():
    facts = parse_probe_output(_probe_json())
    assert (facts.coded_width, facts.coded_height) == (640, 360)
    assert (facts.display_width, facts.display_height) == (640, 360)
    assert facts.orientation == "landscape" and facts.aspect_ratio == pytest.approx(16 / 9)
    assert facts.reported_fps == 30.0 and facts.fps_basis == "average"
    assert facts.reported_frame_count == 60 and facts.frame_count_basis == "reported"
    assert facts.estimated_frame_count is None and facts.frame_count == 60
    assert facts.duration_seconds == 2.0 and facts.duration_basis == "stream"
    assert facts.container_format == "mov,mp4,m4a,3gp,3g2,mj2"


def test_metadata_estimates_are_labelled_not_reported():
    facts = parse_probe_output(_probe_json(nb_frames="N/A", duration="N/A"))
    # duration falls back to the container, the frame count is an estimate from duration x fps
    assert facts.duration_basis == "container" and facts.duration_seconds == 2.0
    assert facts.reported_frame_count is None
    assert facts.estimated_frame_count == 60 and facts.frame_count_basis == "estimated"


def test_unknown_values_stay_unknown():
    facts = parse_probe_output(
        _probe_json(nb_frames="N/A", duration="N/A", avg_frame_rate="0/0", r_frame_rate="0/0")
    )
    assert facts.reported_fps is None and facts.fps_basis == "unknown"
    assert facts.frame_count is None and facts.frame_count_basis == "unknown"
    payload = json.loads(_probe_json(duration="N/A", nb_frames="N/A"))
    payload["format"]["duration"] = "N/A"
    facts = parse_probe_output(json.dumps(payload).encode())
    assert facts.duration_seconds is None and facts.duration_basis == "unknown"
    assert facts.estimated_frame_count is None


def test_rotation_metadata_swaps_display_dimensions():
    by_side_data = parse_probe_output(_probe_json(side_data_list=[{"rotation": -90}]))
    assert by_side_data.rotation_quadrants == 3
    assert (by_side_data.display_width, by_side_data.display_height) == (360, 640)
    assert by_side_data.orientation == "portrait"
    by_tag = parse_probe_output(_probe_json(tags={"rotate": "90"}))
    assert (by_tag.display_width, by_tag.display_height) == (360, 640)
    half_turn = parse_probe_output(_probe_json(side_data_list=[{"rotation": 180}]))
    assert (half_turn.display_width, half_turn.display_height) == (640, 360)


def test_variable_frame_rate_is_suspected_from_differing_rates():
    assert parse_probe_output(_probe_json(r_frame_rate="60/1")).fps_is_variable_suspected
    assert not parse_probe_output(_probe_json()).fps_is_variable_suspected
    ntsc = parse_probe_output(_probe_json(avg_frame_rate="30000/1001", r_frame_rate="30000/1001"))
    assert ntsc.reported_fps == pytest.approx(29.97, abs=0.01)


def test_non_square_pixels_are_reported_only_when_unusual():
    assert parse_probe_output(_probe_json(sample_aspect_ratio="1:1")).sample_aspect_ratio == ""
    assert parse_probe_output(_probe_json(sample_aspect_ratio="4:3")).sample_aspect_ratio == "4:3"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"", ISSUE_NO_VIDEO_STREAM),
        (b"{}", ISSUE_NO_VIDEO_STREAM),
        (b'{"streams": []}', ISSUE_NO_VIDEO_STREAM),
        (b"not json", ISSUE_PROBE_UNREADABLE),
        (b"[1, 2]", ISSUE_PROBE_UNREADABLE),
        (_probe_json(width=0), "invalid_dimensions"),
        (_probe_json(width="N/A"), "invalid_dimensions"),
        (_probe_json(width=10**9, height=10**9), "invalid_dimensions"),
    ],
)
def test_unusable_probe_output_is_a_typed_failure(payload, code):
    with pytest.raises(ProbeParseError) as raised:
        parse_probe_output(payload)
    assert raised.value.code == code


def test_hostile_text_fields_are_sanitised_and_bounded():
    facts = parse_probe_output(_probe_json(codec_name="h2\x00\x1b[31m" + "x" * 500))
    assert facts.codec_name.isprintable() and len(facts.codec_name) <= 40


def test_preview_positions_cover_start_middle_and_late():
    assert preview_positions(None) == [0.0]
    assert preview_positions(0) == [0.0]
    assert preview_positions(10.0) == [0.0, 5.0, 9.0]
    assert preview_positions(10.0, 1) == [0.0]
    assert preview_positions(10.0, 2) == [0.0, 9.0]


# ------------------------------------------------------------------------------ commands


def test_commands_are_bounded_argv_lists_that_only_read_files():
    probe = build_probe_command("ffprobe", "C:/clips/a.mp4")
    assert probe[0] == "ffprobe" and probe[-2:] == ["-i", "C:/clips/a.mp4"]
    assert probe[probe.index("-protocol_whitelist") + 1] == "file"
    assert "v:0" in probe  # one stream only

    frame = build_frame_command("ffmpeg", "C:/clips/a.mp4", 1.234)
    assert frame[frame.index("-ss") + 1] == "1.234"
    assert frame[frame.index("-protocol_whitelist") + 1] == "file"
    assert frame[frame.index("-frames:v") + 1] == "1"
    assert frame[frame.index("-fs") + 1] == str(dvi.MAX_FRAME_STDOUT_BYTES)
    assert f"min(iw,{PREVIEW_MAX_EDGE})" in frame[frame.index("-vf") + 1]
    assert frame[-1] == "pipe:1" and "-an" in frame and "-nostdin" in frame
    # nothing is written to a file: the only output target is the pipe
    assert sum(1 for part in frame if part.endswith((".png", ".mp4", ".jpg"))) == 1  # the input


# ------------------------------------------------------------------------------ orchestration


def test_successful_inspection_separates_reported_facts_from_measured_frames(tmp_path):
    clip = _clip(tmp_path)
    runner = ScriptedRunner(
        ProcessOutcome(returncode=0, stdout=_probe_json()),
        [ProcessOutcome(returncode=0, stdout=_png(160, 90)) for _ in range(3)],
    )
    result = _inspect(clip, runner)
    assert result.status == STATUS_OK and result.issues == ()
    assert result.facts is not None and result.facts.reported_frame_count == 60
    assert [round(frame.position_seconds, 1) for frame in result.frames] == [0.0, 1.0, 1.8]
    assert all((frame.width, frame.height) == (160, 90) for frame in result.frames)
    assert len(runner.calls) == 4  # one probe, three frames
    assert all(timeout <= dvi.INSPECTION_DEADLINE_SECONDS for _cmd, timeout, _cap in runner.calls)
    assert runner.calls[0][2] == dvi.MAX_PROBE_STDOUT_BYTES
    assert all(cap == dvi.MAX_FRAME_STDOUT_BYTES for _cmd, _t, cap in runner.calls[1:])


def test_missing_and_empty_selection_fail_without_launching_anything(tmp_path):
    runner = ScriptedRunner(ProcessOutcome(returncode=0))
    for value in ("", "   ", tmp_path / "nope.mp4", tmp_path):
        result = inspect_driving_video(value, runner=runner, ffprobe="p", ffmpeg="f")
        assert result.status == STATUS_FAILED
        assert result.issues[0].code == ISSUE_FILE_MISSING
    assert runner.calls == []


def test_missing_executables_are_reported_not_raised(tmp_path, monkeypatch):
    clip = _clip(tmp_path)
    monkeypatch.setattr(dvi, "resolve_ffprobe_executable", lambda: None)
    result = inspect_driving_video(clip, runner=ScriptedRunner(ProcessOutcome(returncode=0)))
    assert result.status == STATUS_FAILED and result.issues[0].code == ISSUE_FFPROBE_UNAVAILABLE

    monkeypatch.setattr(dvi, "resolve_ffmpeg_executable", lambda: None)
    runner = ScriptedRunner(ProcessOutcome(returncode=0, stdout=_probe_json()))
    result = inspect_driving_video(clip, runner=runner, ffprobe="ffprobe-stub")
    assert result.status == STATUS_PARTIAL and result.facts is not None and result.frames == ()
    assert [issue.code for issue in result.issues] == [ISSUE_FFMPEG_UNAVAILABLE]


def test_corrupt_file_is_a_probe_failure_with_the_decoders_reason(tmp_path):
    clip = _clip(tmp_path)
    stderr = (
        f"[mov,mp4 @ 0000] moov atom not found\n{clip}: Invalid data found when processing input\n"
    ).encode()
    runner = ScriptedRunner(ProcessOutcome(returncode=1, stderr=stderr))
    result = _inspect(clip, runner)
    assert result.status == STATUS_FAILED and result.facts is None
    [issue] = result.issues
    assert issue.code == ISSUE_PROBE_FAILED
    assert "moov atom not found" in issue.message and str(clip) not in issue.message


def test_probe_timeout_oversized_output_and_garbage_are_bounded_failures(tmp_path):
    clip = _clip(tmp_path)
    cases = [
        (ProcessOutcome(returncode=None, timed_out=True), ISSUE_PROBE_TIMEOUT),
        (ProcessOutcome(returncode=None, output_truncated=True), ISSUE_PROBE_OUTPUT_TOO_LARGE),
        (ProcessOutcome(returncode=0, stdout=b"\xff\xfe garbage"), ISSUE_PROBE_UNREADABLE),
        (ProcessOutcome(returncode=0, stdout=b'{"streams": []}'), ISSUE_NO_VIDEO_STREAM),
        (ProcessOutcome(returncode=None, launch_error="missing"), ISSUE_FFPROBE_UNAVAILABLE),
        (ProcessOutcome(returncode=None, cancelled=True), ISSUE_CANCELLED),
    ]
    for outcome, code in cases:
        result = _inspect(clip, ScriptedRunner(outcome))
        assert result.status == STATUS_FAILED
        assert result.issues[0].code == code


def test_undecodable_and_truncated_frames_leave_a_partial_result(tmp_path):
    clip = _clip(tmp_path)
    frames = [
        ProcessOutcome(returncode=0, stdout=_png(160, 90)),
        ProcessOutcome(returncode=1),  # decoder error
        ProcessOutcome(returncode=0, stdout=_png(160, 90)[:40]),  # truncated PNG
    ]
    result = _inspect(clip, ScriptedRunner(ProcessOutcome(returncode=0, stdout=_probe_json()), frames))
    assert result.status == STATUS_PARTIAL
    assert len(result.frames) == 1
    assert [issue.code for issue in result.issues] == [ISSUE_FRAME_DECODE_FAILED] * 2
    assert result.facts is not None  # reported facts survive undecodable frames


def test_oversized_decoded_frame_is_rejected(tmp_path):
    clip = _clip(tmp_path)
    frames = [ProcessOutcome(returncode=0, stdout=_png(PREVIEW_MAX_EDGE + 1, 10))]
    result = _inspect(
        clip, ScriptedRunner(ProcessOutcome(returncode=0, stdout=_probe_json()), frames), frame_count=1
    )
    assert result.frames == () and result.issues[0].code == ISSUE_FRAME_DECODE_FAILED


def test_frames_above_the_decode_pixel_cap_are_never_requested(tmp_path):
    clip = _clip(tmp_path)
    side = int(MAX_PREVIEW_DECODE_PIXELS**0.5) + 1
    runner = ScriptedRunner(
        ProcessOutcome(returncode=0, stdout=_probe_json(width=side, height=side))
    )
    result = _inspect(clip, runner)
    assert result.status == STATUS_PARTIAL and result.frames == ()
    assert result.facts is not None and result.facts.display_width == side  # facts still reported
    assert [issue.code for issue in result.issues] == [ISSUE_FRAME_TOO_LARGE]
    assert len(runner.calls) == 1  # FFprobe only: no child was asked to allocate the frame

    at_cap = int(MAX_PREVIEW_DECODE_PIXELS**0.5)
    runner = ScriptedRunner(
        ProcessOutcome(returncode=0, stdout=_probe_json(width=at_cap, height=at_cap)),
        [ProcessOutcome(returncode=0, stdout=_png(160, 160))],
    )
    result = _inspect(clip, runner, frame_count=1)
    assert len(result.frames) == 1 and len(runner.calls) == 2


def test_an_oversized_png_header_is_rejected_before_pixels_are_decoded(monkeypatch):
    oversized, fits = _png(PREVIEW_MAX_EDGE + 1, 4), _png(PREVIEW_MAX_EDGE, 4)
    seen = {"loaded": False}
    real_load = Image.Image.load

    def tracking_load(self, *args, **kwargs):
        seen["loaded"] = True
        return real_load(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "load", tracking_load)
    assert dvi._decode_preview(oversized, PREVIEW_MAX_EDGE) is None
    assert seen["loaded"] is False
    assert dvi._decode_preview(fits, PREVIEW_MAX_EDGE) == (PREVIEW_MAX_EDGE, 4)
    assert seen["loaded"] is True


def test_a_stalled_frame_decode_stops_further_decoding(tmp_path):
    clip = _clip(tmp_path)
    runner = ScriptedRunner(
        ProcessOutcome(returncode=0, stdout=_probe_json()),
        [ProcessOutcome(returncode=None, timed_out=True)],
    )
    result = _inspect(clip, runner)
    assert [issue.code for issue in result.issues] == [ISSUE_FRAME_TIMEOUT]
    assert len(runner.calls) == 2  # probe + the one stalled frame; the rest were not attempted
    assert result.status == STATUS_PARTIAL


def test_inspection_deadline_caps_total_work(tmp_path):
    clip = _clip(tmp_path)
    ticks = iter([0.0, 0.1, 0.2, dvi.INSPECTION_DEADLINE_SECONDS + 1.0])
    state = {"last": 0.0}

    def clock() -> float:
        state["last"] = next(ticks, state["last"] + 100.0)
        return state["last"]

    runner = ScriptedRunner(
        ProcessOutcome(returncode=0, stdout=_probe_json()),
        [ProcessOutcome(returncode=0, stdout=_png(160, 90)) for _ in range(3)],
    )
    result = _inspect(clip, runner, clock=clock)
    assert ISSUE_DEADLINE_EXCEEDED in [issue.code for issue in result.issues]
    assert len(result.frames) < 3


def test_cancellation_between_processes_stops_cleanly(tmp_path):
    clip = _clip(tmp_path)
    cancel = threading.Event()

    class CancelAfterProbe(ScriptedRunner):
        def __call__(self, command, **kwargs):
            outcome = super().__call__(command, **kwargs)
            cancel.set()
            return outcome

    runner = CancelAfterProbe(ProcessOutcome(returncode=0, stdout=_probe_json()))
    result = _inspect(clip, runner, cancel=cancel)
    assert result.status == STATUS_PARTIAL and result.facts is not None
    assert ISSUE_CANCELLED in [issue.code for issue in result.issues]
    assert len(runner.calls) == 1


def test_large_file_is_never_read_or_hashed_by_the_inspector(tmp_path, monkeypatch):
    big = tmp_path / "huge.mp4"
    with big.open("wb") as handle:
        handle.truncate(6 * 1024**3)  # sparse 6 GiB; reading it would be conspicuous
    reads: list[str] = []
    real_open = Path.open

    def tracking_open(self, *args, **kwargs):
        reads.append(str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("whole-file read"))
    runner = ScriptedRunner(ProcessOutcome(returncode=1, stderr=b"Invalid data"))
    result = _inspect(big, runner)
    assert result.status == STATUS_FAILED
    assert str(big) not in reads


# ------------------------------------------------------------------------------ bounded processes


def _python(script: str) -> list[str]:
    return [sys.executable, "-I", "-c", script]


def test_bounded_process_returns_output_and_exit_code():
    outcome = run_bounded_process(
        _python("import sys; sys.stdout.write('hello'); sys.stderr.write('warn')"),
        timeout_seconds=20,
        max_stdout_bytes=1024,
    )
    assert outcome.returncode == 0 and outcome.stdout == b"hello" and outcome.stderr == b"warn"
    assert not (outcome.timed_out or outcome.output_truncated or outcome.cancelled)


def test_bounded_process_caps_stdout_and_kills_the_writer():
    started = time.monotonic()
    outcome = run_bounded_process(
        _python(
            "import sys, time\n"
            "while True:\n"
            "    sys.stdout.buffer.write(b'x' * 65536); sys.stdout.buffer.flush()\n"
        ),
        timeout_seconds=30,
        max_stdout_bytes=10_000,
    )
    assert outcome.output_truncated is True
    assert len(outcome.stdout) == 10_000
    assert time.monotonic() - started < 25


def test_bounded_process_times_out_a_hung_child():
    started = time.monotonic()
    outcome = run_bounded_process(
        _python("import time; time.sleep(60)"), timeout_seconds=0.6, max_stdout_bytes=1024
    )
    assert outcome.timed_out is True
    assert time.monotonic() - started < 20


def test_bounded_process_honours_cancellation():
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()
    started = time.monotonic()
    outcome = run_bounded_process(
        _python("import time; time.sleep(60)"),
        timeout_seconds=30,
        max_stdout_bytes=1024,
        cancel=cancel,
    )
    assert outcome.cancelled is True and not outcome.timed_out
    assert time.monotonic() - started < 20


def test_bounded_process_drains_unbounded_stderr_without_blocking_and_keeps_a_prefix():
    outcome = run_bounded_process(
        _python("import sys; sys.stderr.write('e' * 2_000_000); sys.stdout.write('ok')"),
        timeout_seconds=30,
        max_stdout_bytes=1024,
    )
    assert outcome.returncode == 0 and outcome.stdout == b"ok"
    assert len(outcome.stderr) == dvi.MAX_STDERR_BYTES


def test_bounded_process_reports_a_missing_executable():
    outcome = run_bounded_process(
        ["definitely-not-an-executable-196"], timeout_seconds=5, max_stdout_bytes=10
    )
    assert outcome.launch_error and outcome.returncode is None


# ------------------------------------------------------------------------------ real FFmpeg


def _make_clip(tmp_path: Path, *, size: str = "320x180", fps: int = 30, seconds: float = 2.0,
               name: str = "clip.mp4", extra: Sequence[str] = ()) -> Path:
    path = tmp_path / name
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
            f"testsrc=size={size}:rate={fps}", "-t", str(seconds), "-pix_fmt", "yuv420p",
            *extra, str(path),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return path


def _tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@needs_ffmpeg
def test_real_clip_reports_facts_and_decodes_small_frames(tmp_path):
    clip = _make_clip(tmp_path)
    before = _tree(tmp_path)
    result = inspect_driving_video(clip)
    assert result.status == STATUS_OK, result.issues
    facts = result.facts
    assert facts is not None
    assert (facts.display_width, facts.display_height) == (320, 180)
    assert facts.reported_fps == 30.0
    assert facts.reported_frame_count == 60 and facts.frame_count_basis == "reported"
    assert facts.duration_seconds == pytest.approx(2.0, abs=0.05)
    assert len(result.frames) == 3
    for frame in result.frames:
        with Image.open(io.BytesIO(frame.png_bytes)) as image:
            image.load()
            assert image.size == (frame.width, frame.height)
        assert max(frame.width, frame.height) <= PREVIEW_MAX_EDGE
    assert _tree(tmp_path) == before  # read-only: nothing created, nothing modified


@needs_ffmpeg
def test_real_rotated_clip_reports_display_orientation(tmp_path):
    plain = _make_clip(tmp_path, name="plain.mp4")
    rotated = tmp_path / "rotated.mp4"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-display_rotation", "90", "-i", str(plain),
         "-c", "copy", str(rotated)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    result = inspect_driving_video(rotated)
    assert result.facts is not None
    assert (result.facts.coded_width, result.facts.coded_height) == (320, 180)
    assert (result.facts.display_width, result.facts.display_height) == (180, 320)
    assert result.facts.orientation == "portrait"
    # FFmpeg really decoded the rotated picture, so the measured frame agrees with the metadata.
    first = result.frames[0]
    assert first.height > first.width


@needs_ffmpeg
def test_real_huge_frame_is_scaled_down_before_it_reaches_this_process(tmp_path):
    clip = _make_clip(tmp_path, size="7680x4320", fps=1, seconds=1, name="eightk.mp4")
    result = inspect_driving_video(clip, frame_count=1)
    assert result.facts is not None
    assert (result.facts.display_width, result.facts.display_height) == (7680, 4320)
    [frame] = result.frames
    assert max(frame.width, frame.height) <= PREVIEW_MAX_EDGE
    assert len(frame.png_bytes) <= dvi.MAX_FRAME_STDOUT_BYTES


@needs_ffmpeg
def test_real_corrupt_and_truncated_files_fail_fast_and_leave_no_residue(tmp_path):
    good = _make_clip(tmp_path)
    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(good.read_bytes()[:4000])
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(bytes(range(256)) * 20)
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    before = _tree(tmp_path)
    for bad in (truncated, junk, empty):
        started = time.monotonic()
        result = inspect_driving_video(bad)
        assert result.status == STATUS_FAILED, bad
        assert result.facts is None and result.frames == ()
        assert result.issues[0].code in {ISSUE_PROBE_FAILED, ISSUE_NO_VIDEO_STREAM}
        assert time.monotonic() - started < dvi.INSPECTION_DEADLINE_SECONDS
    assert _tree(tmp_path) == before


@needs_ffmpeg
def test_real_audio_only_file_has_no_video_stream(tmp_path):
    audio = tmp_path / "tone.m4a"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440",
         "-t", "1", str(audio)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    result = inspect_driving_video(audio)
    assert result.status == STATUS_FAILED
    assert result.issues[0].code == ISSUE_NO_VIDEO_STREAM

"""PR-VID-QUALITY-211: bounded, read-only review previews.

Real FFmpeg decodes tiny synthetic clips (skipped without FFmpeg); every failure path uses a fake process
runner so no timeout or crash has to be provoked for real.  No GPU, model, network or Comfy.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from src.utils.managed_process import ProcessOutcome
from src.video import review_preview as rp
from src.video.review_preview import (
    describe_preview,
    frames_allowed,
    prepare_review_preview,
    preview_dimensions,
)
from tests.helpers.video_review_211 import FFMPEG_AVAILABLE, make_clip

needs_ffmpeg = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg/FFprobe are not installed")

PROBE = json.dumps(
    {
        "streams": [
            {
                "codec_name": "h264",
                "width": 64,
                "height": 48,
                "avg_frame_rate": "12/1",
                "r_frame_rate": "12/1",
                "nb_frames": "12",
                "duration": "1.0",
                "pix_fmt": "yuv420p",
            }
        ],
        "format": {"format_name": "mov,mp4", "duration": "1.0"},
    }
).encode()


class _Runner:
    """Answers the probe with ``PROBE`` and the decode with a canned outcome."""

    def __init__(self, decode: ProcessOutcome | None = None, probe: ProcessOutcome | None = None):
        self.decode = decode or ProcessOutcome(returncode=0, stdout=b"")
        self.probe = probe or ProcessOutcome(returncode=0, stdout=PROBE)
        self.commands: list[list[str]] = []

    def __call__(self, command, *, timeout_seconds, max_stdout_bytes, cancel=None):
        self.commands.append(list(command))
        return self.probe if "-show_entries" in command else self.decode


def _file(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"not really a video")
    return path


def _frames(count: int, width: int = 64, height: int = 48) -> bytes:
    return b"".join(bytes([n]) * (width * height * 3) for n in range(count))


def _run(tmp_path, runner, **kwargs):
    return prepare_review_preview(
        _file(tmp_path), runner=runner, ffprobe="ffprobe", ffmpeg="ffmpeg", **kwargs
    )


# ------------------------------------------------------------------ pure bounds


def test_preview_dimensions_are_even_aspect_preserving_and_bounded():
    assert preview_dimensions(1920, 1080) == (256, 144)
    assert preview_dimensions(480, 832) == (148, 256)
    assert preview_dimensions(64, 48) == (64, 48)  # never upscaled
    width, height = preview_dimensions(1000, 7)
    assert width % 2 == 0 and height % 2 == 0 and max(width, height) <= 256 and height >= 2


def test_frame_budget_respects_the_clip_the_frame_cap_and_the_byte_cap():
    frame = 256 * 144 * 3
    assert frames_allowed(frame, 81, 120, 24 * 1024 * 1024) == 81
    assert frames_allowed(frame, 500, 120, 24 * 1024 * 1024) == 120
    assert frames_allowed(frame, None, 120, 24 * 1024 * 1024) == 120
    assert frames_allowed(frame, 500, 120, frame * 5 + 3) == 5
    assert frames_allowed(frame, 500, 120, frame - 1) == 0


def test_the_decode_command_is_read_only_file_protocol_and_writes_to_a_pipe():
    command = rp.build_decode_command("ffmpeg", "in.mp4", 64, 48, 12)
    assert command[command.index("-protocol_whitelist") + 1] == "file"
    assert command[-1] == "pipe:1" and "rawvideo" in command
    assert "-y" not in command and "-nostdin" in command
    assert command[command.index("-frames:v") + 1] == "12"


# ------------------------------------------------------------------ fake-runner behaviour


def test_a_decode_yields_frames_in_order_with_honest_description(tmp_path):
    runner = _Runner(ProcessOutcome(returncode=0, stdout=_frames(12)))

    result = _run(tmp_path, runner)

    assert result.ok and result.clip is not None
    clip = result.clip
    assert (clip.width, clip.height, clip.frame_count, clip.fps) == (64, 48, 12, 12.0)
    assert not clip.truncated and not clip.fps_is_assumed
    assert clip.frame_image(0).getpixel((0, 0)) == (0, 0, 0)
    assert clip.frame_image(5).getpixel((3, 3)) == (5, 5, 5)
    assert clip.frame_image(99).getpixel((0, 0)) == (11, 11, 11)  # clamped, never an IndexError
    assert "Review preview 64x48 of the original 64x48" in describe_preview(clip)


def test_a_partial_decode_keeps_the_frames_it_got_and_says_so(tmp_path):
    stdout = _frames(3) + b"\x01" * 100  # three whole frames and a torn fourth
    runner = _Runner(
        ProcessOutcome(returncode=1, stdout=stdout, stderr=b"[h264] error while decoding")
    )

    result = _run(tmp_path, runner)

    assert result.ok and result.clip.frame_count == 3
    assert result.clip.truncated  # the original reports 12
    assert "Decoding stopped early" in result.clip.note
    assert "first 3 of 12" in describe_preview(result.clip)


def test_no_decodable_frame_is_a_bounded_failure_not_an_exception(tmp_path):
    runner = _Runner(ProcessOutcome(returncode=1, stdout=b"", stderr=b"Invalid data found"))

    result = _run(tmp_path, runner)

    assert not result.ok and result.issue_code == "frame_decode_failed"
    assert "could be decoded" in result.message and "Invalid data found" in result.message


@pytest.mark.parametrize(
    ("decode", "code"),
    [
        (ProcessOutcome(returncode=None, timed_out=True), "frame_timeout"),
        (ProcessOutcome(returncode=None, cancelled=True), "cancelled"),
        (
            ProcessOutcome(returncode=0, output_truncated=True, stdout=b"x"),
            "decode_output_too_large",
        ),
        (ProcessOutcome(returncode=None, launch_error="boom"), "ffmpeg_unavailable"),
    ],
)
def test_decode_outcomes_map_to_stable_failures(tmp_path, decode, code):
    result = _run(tmp_path, _Runner(decode))
    assert not result.ok and result.issue_code == code and result.message


@pytest.mark.parametrize(
    ("probe", "code"),
    [
        (ProcessOutcome(returncode=None, timed_out=True), "probe_timeout"),
        (ProcessOutcome(returncode=None, cancelled=True), "cancelled"),
        (ProcessOutcome(returncode=1, stderr=b"moov atom not found"), "probe_failed"),
        (ProcessOutcome(returncode=0, stdout=b"{not json"), "probe_unreadable"),
        (ProcessOutcome(returncode=0, stdout=b'{"streams": []}'), "no_video_stream"),
        (
            ProcessOutcome(returncode=0, output_truncated=True, stdout=b"{"),
            "probe_output_too_large",
        ),
    ],
)
def test_probe_outcomes_map_to_stable_failures_and_never_reach_the_decoder(tmp_path, probe, code):
    runner = _Runner(probe=probe)

    result = _run(tmp_path, runner)

    assert not result.ok and result.issue_code == code
    assert all("-show_entries" in command for command in runner.commands)  # no decode was attempted


def test_truncation_to_the_frame_cap_is_disclosed(tmp_path):
    runner = _Runner(ProcessOutcome(returncode=0, stdout=_frames(5)))

    result = _run(tmp_path, runner, max_frames=5)

    assert result.ok and result.clip.frame_count == 5 and result.clip.truncated
    assert runner.commands[-1][runner.commands[-1].index("-frames:v") + 1] == "5"
    assert "first 5 of 12" in describe_preview(result.clip)


def test_the_stdout_cap_is_exactly_the_requested_frames_plus_one_byte(tmp_path):
    seen: dict[str, int] = {}

    def runner(command, *, timeout_seconds, max_stdout_bytes, cancel=None):
        if "-show_entries" in command:
            return ProcessOutcome(returncode=0, stdout=PROBE)
        seen["cap"] = max_stdout_bytes
        seen["timeout"] = int(timeout_seconds)
        return ProcessOutcome(returncode=0, stdout=_frames(12))

    assert _run(tmp_path, runner).ok
    assert seen["cap"] == 12 * 64 * 48 * 3 + 1
    assert seen["timeout"] == int(rp.DECODE_TIMEOUT_SECONDS)


def test_huge_frames_are_never_decoded(tmp_path):
    huge = json.loads(PROBE)
    huge["streams"][0].update(width=20000, height=10000)
    runner = _Runner(probe=ProcessOutcome(returncode=0, stdout=json.dumps(huge).encode()))

    result = _run(tmp_path, runner)

    assert result.issue_code == "frame_too_large" and "Open the original" in result.message
    assert all("-show_entries" in command for command in runner.commands)


def test_missing_ffmpeg_explains_what_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "resolve_ffmpeg_executable", lambda: None)
    monkeypatch.setattr(rp, "resolve_ffprobe_executable", lambda: None)

    result = prepare_review_preview(_file(tmp_path))

    assert not result.ok and result.issue_code == "ffprobe_unavailable"
    assert "STABLENEW_FFMPEG_PATH" in result.message and "ratings" in result.message


def test_missing_or_blank_paths_do_not_raise(tmp_path):
    assert prepare_review_preview(tmp_path / "gone.mp4").issue_code == "file_missing"
    assert prepare_review_preview("").issue_code == "file_missing"
    assert (
        prepare_review_preview(tmp_path).issue_code == "file_missing"
    )  # a directory is not a clip


def test_an_assumed_frame_rate_is_flagged(tmp_path):
    no_rate = json.loads(PROBE)
    no_rate["streams"][0].update(avg_frame_rate="0/0", r_frame_rate="0/0")
    runner = _Runner(
        ProcessOutcome(returncode=0, stdout=_frames(12)),
        ProcessOutcome(returncode=0, stdout=json.dumps(no_rate).encode()),
    )

    clip = _run(tmp_path, runner).clip

    assert (
        clip.fps is None and clip.fps_is_assumed and clip.effective_fps == rp.DEFAULT_PLAYBACK_FPS
    )
    assert "(assumed)" in describe_preview(clip)


# ------------------------------------------------------------------ real FFmpeg


@needs_ffmpeg
def test_real_decode_returns_distinct_exact_frames_and_leaves_the_original_untouched(tmp_path):
    clip_path = make_clip(tmp_path, "real.mp4", frames=12, rate=12, size="96x64")
    before = hashlib.sha256(clip_path.read_bytes()).hexdigest()
    listing = sorted(p.name for p in tmp_path.iterdir())

    result = prepare_review_preview(clip_path)

    assert result.ok and result.clip is not None
    clip = result.clip
    assert (clip.source_width, clip.source_height, clip.frame_count) == (96, 64, 12)
    assert clip.fps == 12.0 and len(clip.raw) == 12 * clip.frame_bytes
    digests = {
        hashlib.sha256(clip.raw[i * clip.frame_bytes : (i + 1) * clip.frame_bytes]).hexdigest()
        for i in range(12)
    }
    assert len(digests) == 12  # testsrc changes every frame: passthrough kept them all
    assert hashlib.sha256(clip_path.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == listing  # nothing written by the review


@needs_ffmpeg
def test_real_decode_downscales_a_large_clip_inside_the_bounds(tmp_path):
    clip_path = make_clip(tmp_path, "wide.mp4", frames=6, rate=6, size="640x360")

    result = prepare_review_preview(clip_path)

    assert result.ok
    assert (result.clip.width, result.clip.height) == (256, 144)
    assert len(result.clip.raw) <= rp.MAX_PREVIEW_BYTES


@needs_ffmpeg
def test_real_decode_of_a_long_clip_stops_at_the_frame_cap(tmp_path):
    clip_path = make_clip(tmp_path, "long.mp4", frames=40, rate=20, size="32x32")

    result = prepare_review_preview(clip_path, max_frames=10)

    assert result.ok and result.clip.frame_count == 10 and result.clip.truncated
    assert result.clip.reported_frame_count == 40


@needs_ffmpeg
def test_real_corrupt_and_empty_files_fail_without_raising(tmp_path):
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\xff" * 64)
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")

    for path in (corrupt, empty):
        result = prepare_review_preview(path)
        assert (
            not result.ok
            and result.message
            and result.issue_code
            in {
                "probe_failed",
                "no_video_stream",
                "probe_unreadable",
                "frame_decode_failed",
                "invalid_dimensions",
            }
        )


@needs_ffmpeg
def test_real_cancel_before_start_is_a_cancelled_failure(tmp_path):
    clip_path = make_clip(tmp_path, "c.mp4")
    cancel = threading.Event()
    cancel.set()

    result = prepare_review_preview(clip_path, cancel=cancel)

    assert not result.ok and result.issue_code in {"cancelled", "probe_failed"}

"""PR-VID-ASM-332: the frozen assembly spec, its frame plan, the FFmpeg command and admission (no FFmpeg needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.pipeline.video import build_video_encode_filter
from src.video.movie_assembly_compiler import (
    AssemblyIntentClip,
    MovieAssemblyAdmissionError,
    MovieAssemblyIntent,
    VideoFacts,
    build_movie_assembly_njr,
    freeze_movie_assembly,
    resolve_target_size,
    sanitize_clip_name,
)
from src.video.movie_assembly_engine import build_sequence_command, build_slideshow_command
from src.video.movie_assembly_models import (
    CLIP_KIND_IMAGE,
    CLIP_KIND_VIDEO,
    MODE_SEQUENCE,
    MODE_SLIDESHOW,
    MOVIE_ASSEMBLY_SCHEMA,
    AssemblyAudio,
    AssemblyClip,
    AssemblyEncode,
    MovieAssemblySpec,
    MovieAssemblySpecError,
    plan_timeline,
)

_SHA = "a" * 64


def _clip(path: str, kind: str = CLIP_KIND_IMAGE, seconds: float = 1.0) -> AssemblyClip:
    return AssemblyClip(
        path, _SHA, kind, 64, 64, seconds, 24.0 if kind == CLIP_KIND_VIDEO else None
    )


def _spec(clips: tuple[AssemblyClip, ...], **overrides) -> MovieAssemblySpec:
    values = {
        "mode": MODE_SLIDESHOW,
        "clips": clips,
        "width": 64,
        "height": 64,
        "fps": 24,
        "transition_seconds": 0.25,
        "encode": AssemblyEncode("libx264", 16, "slow"),
        "clip_name": "movie",
    }
    values.update(overrides)
    return MovieAssemblySpec(**values)


# --- frame plan ------------------------------------------------------------------------------------


def test_crossfades_overlap_neighbours_by_whole_frames() -> None:
    spec = _spec((_clip("a.mp4", CLIP_KIND_VIDEO), _clip("b.png"), _clip("c.mp4", CLIP_KIND_VIDEO)))
    timeline = plan_timeline(spec)
    assert timeline.clip_frames == (24, 24, 24)
    assert timeline.transition_frames == 6
    assert timeline.transition_offsets == (18, 36)
    assert timeline.total_frames == 60
    assert timeline.duration_seconds == pytest.approx(2.5)


def test_hard_cuts_and_a_single_clip_have_no_transition() -> None:
    assert (
        plan_timeline(_spec((_clip("a.png"), _clip("b.png")), transition_seconds=0.0)).total_frames
        == 48
    )
    single = plan_timeline(_spec((_clip("a.png", seconds=2.0),)))
    assert (single.transition_frames, single.transition_offsets, single.total_frames) == (0, (), 48)


def test_a_transition_longer_than_half_the_shortest_clip_is_refused() -> None:
    spec = _spec((_clip("a.png", seconds=0.4), _clip("b.png")), transition_seconds=0.25)
    with pytest.raises(MovieAssemblySpecError, match="longer than half of the shortest item"):
        plan_timeline(spec)


def test_a_frame_sequence_is_one_frame_per_image() -> None:
    spec = _spec(
        tuple(_clip(f"{n}.png", seconds=0.0) for n in range(5)),
        mode=MODE_SEQUENCE,
        transition_seconds=0.0,
    )
    timeline = plan_timeline(spec)
    assert (timeline.clip_frames, timeline.total_frames) == ((1, 1, 1, 1, 1), 5)


# --- spec ------------------------------------------------------------------------------------------


def test_spec_round_trips_through_its_frozen_dict() -> None:
    spec = _spec(
        (_clip("a.mp4", CLIP_KIND_VIDEO), _clip("b.png")),
        audio=AssemblyAudio("music.mp3", _SHA, 1.5, 12.0),
    )
    data = spec.to_dict()
    assert data["schema"] == MOVIE_ASSEMBLY_SCHEMA
    assert MovieAssemblySpec.from_dict(data) == spec


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.pop("encode"),
        lambda data: data["clips"][0].pop("sha256"),
        lambda data: data.update(fps="fast"),
    ],
)
def test_a_malformed_frozen_spec_is_refused(mutate) -> None:
    data = _spec((_clip("a.png"),)).to_dict()
    mutate(data)
    with pytest.raises(MovieAssemblySpecError):
        MovieAssemblySpec.from_dict(data)


def test_validation_names_every_problem() -> None:
    spec = _spec(
        (_clip("a.mp4", CLIP_KIND_VIDEO), AssemblyClip("b.png", "", CLIP_KIND_IMAGE, 8, 8, 0.0)),
        mode=MODE_SEQUENCE,
        width=63,
    )
    errors = " | ".join(spec.validate())
    assert "width must be an even number" in errors
    assert "a frame sequence has no transitions" in errors
    assert "is a video; a frame sequence takes images only" in errors
    assert "no recorded SHA-256" in errors


# --- FFmpeg command --------------------------------------------------------------------------------


def _filter(command: list[str]) -> str:
    return command[command.index("-filter_complex") + 1]


def test_slideshow_command_keeps_order_normalizes_and_crossfades(tmp_path: Path) -> None:
    clips = (_clip("z.mp4", CLIP_KIND_VIDEO), _clip("m.png"), _clip("a.mp4", CLIP_KIND_VIDEO))
    spec = _spec(clips)
    sources = [Path("z.mp4"), tmp_path / "s0001.png", Path("a.mp4")]
    command = build_slideshow_command(
        spec, plan_timeline(spec), ffmpeg="ffmpeg", sources=sources, output_path=tmp_path / "o.mp4"
    )

    inputs = [command[i + 1] for i, arg in enumerate(command) if arg == "-i"]
    assert inputs == [str(path) for path in sources]
    # Every input is file-only; only the still loops, for exactly its frames.
    assert command.count("-protocol_whitelist") == 3
    assert command.count("-loop") == 1
    assert command[command.index("-loop") + 5] == "1.000000"
    graph = _filter(command)
    for index in range(3):
        assert (
            f"[{index}:v]scale=64:64:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad=64:64:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=gbrp,fps=24," in graph
        )
        assert f"trim=end_frame=24,setpts=PTS-STARTPTS[v{index}]" in graph
    assert "[v0][v1]xfade=transition=fade:duration=0.250000:offset=0.750000[x1]" in graph
    assert "[x1][v2]xfade=transition=fade:duration=0.250000:offset=1.500000[x2]" in graph
    assert graph.endswith(f"[x2]{build_video_encode_filter()}[vout]")
    # The colour chain is in the graph, so the shared encoder arguments must not add -vf.
    assert "-vf" not in command
    assert command[command.index("-crf") + 1] == "16"
    assert command[-3:] == ["-frames:v", "60", str(tmp_path / "o.mp4")]


def test_slideshow_without_transition_concatenates(tmp_path: Path) -> None:
    spec = _spec((_clip("a.png"), _clip("b.png")), transition_seconds=0.0)
    command = build_slideshow_command(
        spec,
        plan_timeline(spec),
        ffmpeg="ffmpeg",
        sources=[Path("a.png"), Path("b.png")],
        output_path=tmp_path / "o.mp4",
    )
    assert f"[v0][v1]concat=n=2:v=1:a=0,{build_video_encode_filter()}[vout]" in _filter(command)
    assert "xfade" not in _filter(command)


def test_audio_is_padded_cut_faded_and_mapped(tmp_path: Path) -> None:
    spec = _spec(
        (_clip("a.png"), _clip("b.png")),
        transition_seconds=0.0,
        audio=AssemblyAudio("music.wav", _SHA, 0.5),
    )
    command = build_slideshow_command(
        spec,
        plan_timeline(spec),
        ffmpeg="ffmpeg",
        sources=[Path("a.png"), Path("b.png")],
        output_path=tmp_path / "o.mp4",
    )
    assert (
        "[2:a]apad,atrim=end=2.000000,asetpts=PTS-STARTPTS,afade=t=out:st=1.500000:d=0.500000[aout]"
        in (_filter(command))
    )
    assert command[command.index("[aout]") - 1] == "-map"
    assert "-shortest" in command and "aac" in command


def test_sequence_command_reads_numbered_frames(tmp_path: Path) -> None:
    spec = _spec(
        tuple(_clip(f"{n}.png", seconds=0.0) for n in range(3)),
        mode=MODE_SEQUENCE,
        transition_seconds=0.0,
    )
    command = build_sequence_command(
        spec,
        plan_timeline(spec),
        ffmpeg="ffmpeg",
        frame_pattern=tmp_path / "f%06d.png",
        output_path=tmp_path / "o.mp4",
    )
    assert command[command.index("-framerate") + 1] == "24"
    assert command[command.index("-i") + 1] == str(tmp_path / "f%06d.png")
    assert command[-3:] == ["-frames:v", "3", str(tmp_path / "o.mp4")]


# --- admission -------------------------------------------------------------------------------------


def _png(path: Path, size: tuple[int, int] = (40, 30), orientation: int | None = None) -> Path:
    image = Image.new("RGB", size, (10, 20, 30))
    if orientation is None:
        image.save(path)
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(path.with_suffix(".jpg"), exif=exif)
        return path.with_suffix(".jpg")
    return path


def _fake_video(path: Path) -> Path:
    path.write_bytes(b"not decoded by the fake probe")
    return path


def _probe(path: Path) -> VideoFacts:
    return VideoFacts(width=96, height=64, duration_seconds=2.0, fps=12.0)


def _hash(path) -> str:
    return Path(path).name.encode().hex().ljust(64, "0")[:64]


def _freeze(intent: MovieAssemblyIntent) -> MovieAssemblySpec:
    return freeze_movie_assembly(
        intent, video_probe=_probe, audio_probe=lambda path: 30.0, hash_file=_hash
    )


def test_freeze_records_order_digests_facts_and_resolved_encoder(tmp_path: Path) -> None:
    video = _fake_video(tmp_path / "z.mp4")
    still = _png(tmp_path / "a.png")
    turned = _png(tmp_path / "turned", size=(40, 30), orientation=6)
    intent = MovieAssemblyIntent(
        clips=(
            AssemblyIntentClip(str(video)),
            AssemblyIntentClip(str(still), 2.5),
            AssemblyIntentClip(str(turned)),
        ),
        still_seconds=1.25,
        quality="archival",
        clip_name="My movie!",
    )
    spec = _freeze(intent)

    assert [Path(clip.path).name for clip in spec.clips] == ["z.mp4", "a.png", "turned.jpg"]
    assert [clip.kind for clip in spec.clips] == [CLIP_KIND_VIDEO, CLIP_KIND_IMAGE, CLIP_KIND_IMAGE]
    assert [clip.sha256 for clip in spec.clips] == [_hash(Path(clip.path)) for clip in spec.clips]
    assert (spec.clips[0].duration_seconds, spec.clips[0].source_fps) == (2.0, 12.0)
    assert [clip.duration_seconds for clip in spec.clips[1:]] == [2.5, 1.25]
    assert (spec.clips[2].width, spec.clips[2].height) == (30, 40)  # EXIF 6: displayed rotated
    assert (spec.width, spec.height) == (96, 64)  # "match first clip", frozen as numbers
    assert (spec.encode.crf, spec.encode.preset) == (12, "slow")
    assert spec.clip_name == "My_movie"


def test_freeze_resolves_explicit_and_oversized_targets() -> None:
    assert resolve_target_size("1280x720", (10, 10)) == (1280, 720)
    assert resolve_target_size("match_first", (101, 57)) == (100, 56)
    assert resolve_target_size("match_first", (8192, 4096)) == (4096, 2048)
    with pytest.raises(MovieAssemblyAdmissionError, match="outside"):
        resolve_target_size("8x8", (10, 10))
    with pytest.raises(MovieAssemblyAdmissionError, match="WIDTHxHEIGHT"):
        resolve_target_size("big", (10, 10))


def test_sanitize_clip_name() -> None:
    assert sanitize_clip_name("  ../holiday cut  ") == "holiday_cut"
    assert sanitize_clip_name("") == "movie"


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda tmp: MovieAssemblyIntent(clips=()), "Add at least one"),
        (
            lambda tmp: MovieAssemblyIntent(clips=(AssemblyIntentClip(str(tmp / "missing.png")),)),
            "does not exist",
        ),
        (
            lambda tmp: MovieAssemblyIntent(
                clips=(AssemblyIntentClip(str(_fake_video(tmp / "notes.txt"))),)
            ),
            "not a supported image or video",
        ),
        (
            lambda tmp: MovieAssemblyIntent(
                clips=(AssemblyIntentClip(str(_fake_video(tmp / "v.mp4"))),), mode=MODE_SEQUENCE
            ),
            "frame sequence takes images only",
        ),
        (
            lambda tmp: MovieAssemblyIntent(
                clips=(AssemblyIntentClip(str(_png(tmp / "a.png"))),),
                audio_path=str(_png(tmp / "b.png")),
            ),
            "not a supported audio file",
        ),
        (
            lambda tmp: MovieAssemblyIntent(
                clips=(AssemblyIntentClip(str(_png(tmp / "a.png")), 0.5),),
                audio_path=str(_fake_video(tmp / "m.mp3")),
                audio_fade_out_seconds=2.0,
            ),
            "longer than the",
        ),
        (
            lambda tmp: MovieAssemblyIntent(
                clips=(
                    AssemblyIntentClip(str(_png(tmp / "a.png")), 0.5),
                    AssemblyIntentClip(str(_png(tmp / "b.png"))),
                ),
                transition_seconds=0.5,
            ),
            "shorten the transition",
        ),
        (
            lambda tmp: MovieAssemblyIntent(clips=(AssemblyIntentClip("x.png"),), fps=0),
            "FPS must be",
        ),
    ],
)
def test_admission_refuses_with_an_operator_message(tmp_path: Path, build, message: str) -> None:
    with pytest.raises(MovieAssemblyAdmissionError, match=message):
        _freeze(build(tmp_path))


def test_njr_is_one_frozen_video_stage_with_the_clips_in_order(tmp_path: Path) -> None:
    stills = [_png(tmp_path / name) for name in ("c.png", "a.png", "b.png")]
    spec = _freeze(MovieAssemblyIntent(clips=tuple(AssemblyIntentClip(str(p)) for p in stills)))
    njr = build_movie_assembly_njr(spec, output_dir=tmp_path / "out")

    assert njr.workload_kind.value == "video"
    assert [stage.stage_type for stage in njr.stages if stage.enabled] == ["movie_assembly"]
    assert njr.start_stage == "movie_assembly"
    assert list(njr.input_image_paths) == [clip.path for clip in spec.clips]
    assert [Path(path).name for path in njr.input_image_paths] == ["c.png", "a.png", "b.png"]
    assert njr.config["movie_assembly"] == spec.to_dict()
    assert njr.config["pipeline"] == {"output_route": "movie_clips"}
    assert MovieAssemblySpec.from_dict(njr.config["movie_assembly"]) == spec
    assert njr.extra_metadata["movie_assembly"]["total_frames"] == 9 * 24 - 2 * 12


def test_only_software_encoders_are_accepted() -> None:
    errors = " | ".join(
        _spec((_clip("a.png"),), encode=AssemblyEncode("h264_nvenc", 16, "slow")).validate()
    )
    assert "codec must be one of libvpx-vp9, libx264, libx265" in errors


def test_the_tabs_vp9_choice_freezes_a_named_software_encoder(tmp_path: Path) -> None:
    still = _png(tmp_path / "a.png")
    spec = _freeze(MovieAssemblyIntent(clips=(AssemblyIntentClip(str(still)),), codec="vp9"))
    assert spec.encode.codec == "libvpx-vp9"

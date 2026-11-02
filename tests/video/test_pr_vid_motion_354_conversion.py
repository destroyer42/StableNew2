"""PR-VID-MOTION-354: conversion plan, Blender discovery and the conversion service against a fake Blender.

The fake obeys Blender's command-line contract; no Blender, GPU, model or network is used.  Rendering to a real MP4 uses
CPU-only FFmpeg and is skipped where FFmpeg is absent.
"""

from __future__ import annotations

import json
import sys
import threading
from fractions import Fraction
from pathlib import Path

import pytest

from src.video.motion_conversion import blender as blender_mod
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion.blender import BlenderProblem, parse_version, verify_blender
from src.video.motion_conversion.conversion_service import (
    OWNER_MARKER,
    PROVENANCE_NAME,
    SCRIPT_PATH,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_REUSED,
    MotionConverter,
    preview_plan,
    read_provenance,
    verify_frames,
    verify_published,
)
from src.video.motion_conversion.rig_compat import plan_binding
from src.video.workflow_catalog import build_builtin_workflow_specs
from tests.helpers.motion_conversion_354 import (
    MIXAMO_BONES,
    fake_environ,
    fake_install,
    sha256,
    write_fbx,
)
from tests.helpers.motion_library_353 import FFMPEG, needs_ffmpeg

PROBE = cp.AnimationProbe(
    fps=Fraction(24),
    frame_first=Fraction(1),
    frame_last=Fraction(121),
    bone_names=MIXAMO_BONES,
    has_mesh=True,
    blender_version="4.2.3",
)


def _fun_spec():
    return next(
        s
        for s in build_builtin_workflow_specs()
        if s.workflow_id == "wan22_fun_control_5b_canny_i2v_v1"
    )


def _plan(tmp_path: Path, **overrides):
    source = write_fbx(tmp_path / "src" / "walk.fbx")
    options = {
        "source_path": str(source),
        "source_sha256": sha256(source),
        "source_route": cp.SOURCE_FBX_CHARACTER,
        "probe": PROBE,
        "profile": cp.PROFILE_CHARACTER,
        "output_frames": 17,
        "width": 256,
        "height": 272,
    }
    options.update(overrides)
    return cp.build_plan(**options)


# ------------------------------------------------------------------ plan


def test_plan_is_deterministic_and_its_digest_changes_with_every_pixel_affecting_choice(
    tmp_path: Path,
) -> None:
    a, b = _plan(tmp_path), _plan(tmp_path)
    assert a.digest == b.digest and len(a.digest) == 64
    for change in (
        {"profile": cp.PROFILE_SILHOUETTE},
        {"camera": cp.CAMERA_SIDE},
        {"camera_mode": cp.CAMERA_TRACKING},
        {"root_motion": cp.ROOT_IN_PLACE},
        {"start_seconds": "1/2"},
        {"output_frames": 21},
        {"width": 272, "height": 256},
    ):
        assert _plan(tmp_path, **change).digest != a.digest, change


def test_plan_states_the_exact_source_frame_of_every_output_frame_and_flags_retiming(
    tmp_path: Path,
) -> None:
    same = _plan(tmp_path)
    assert same.sample_frames[:3] == (Fraction(1), Fraction(2), Fraction(3)) and not same.retimed
    thirty = cp.AnimationProbe(
        Fraction(30), Fraction(0), Fraction(300), MIXAMO_BONES, True, "4.2.3"
    )
    retimed = _plan(tmp_path, probe=thirty, start_seconds="1")
    assert retimed.retimed
    assert retimed.sample_frames[0] == Fraction(30)
    assert (
        retimed.sample_frames[4] == Fraction(30) + Fraction(4, 24) * 30
    )  # real-time sampling, never a speed change
    assert retimed.to_record()["timing"]["retimed_by_sampling"] is True


def test_plan_refuses_a_segment_longer_than_the_animation_instead_of_trimming(
    tmp_path: Path,
) -> None:
    short = cp.AnimationProbe(Fraction(24), Fraction(1), Fraction(25), MIXAMO_BONES, True, "4.2.3")
    with pytest.raises(cp.ConversionPlanError, match="longer than the animation"):
        _plan(tmp_path, probe=short, output_frames=49)
    with pytest.raises(cp.ConversionPlanError, match="longer than the animation"):
        _plan(tmp_path, start_seconds="10")


def test_plan_enforces_the_consuming_workflows_frame_rule_and_the_generic_rule(
    tmp_path: Path,
) -> None:
    spec = _fun_spec()
    assert _plan(tmp_path, workflow_spec=spec, output_frames=17).workflow[0] == spec.workflow_id
    with pytest.raises(cp.ConversionPlanError, match="cannot generate"):
        _plan(tmp_path, workflow_spec=spec, output_frames=18)
    with pytest.raises(cp.ConversionPlanError, match="cannot generate"):
        _plan(tmp_path, workflow_spec=spec, output_frames=81)  # beyond Fun Control's maximum of 49
    with pytest.raises(cp.ConversionPlanError, match="not offered"):
        _plan(tmp_path, output_frames=18)


def test_plan_refuses_incompatible_profile_geometry_and_unknown_choices(tmp_path: Path) -> None:
    with pytest.raises(cp.ConversionPlanError, match="no character mesh"):
        _plan(tmp_path, source_route=cp.SOURCE_FBX_SKELETON)
    with pytest.raises(cp.ConversionPlanError, match="BVH holds only a skeleton"):
        _plan(tmp_path, source_route=cp.SOURCE_BVH)
    with pytest.raises(cp.ConversionPlanError, match="multiples of 16"):
        _plan(tmp_path, width=100)
    for key, value in (
        ("camera", "back"),
        ("profile", "openpose"),
        ("camera_mode", "orbit"),
        ("root_motion", "auto"),
    ):
        with pytest.raises(cp.ConversionPlanError, match="Unknown"):
            _plan(tmp_path, **{key: value})
    with pytest.raises(cp.ConversionPlanError, match="SHA-256"):
        _plan(tmp_path, source_sha256="")


def test_skeleton_profile_is_honestly_not_an_openpose_map() -> None:
    assert "not an OpenPose map" in cp.PROFILE_LABELS[cp.PROFILE_SKELETON]


def test_retargeting_onto_a_reference_character_requires_a_compatible_exact_name_binding(
    tmp_path: Path,
) -> None:
    character = write_fbx(tmp_path / "char.fbx")
    options = {
        "source_route": cp.SOURCE_FBX_ON_CHARACTER,
        "profile": cp.PROFILE_CHARACTER,
        "character_path": str(character),
        "character_sha256": sha256(character),
    }
    good = plan_binding(MIXAMO_BONES, MIXAMO_BONES)
    plan = _plan(tmp_path, binding=good, **options)
    assert plan.to_record()["character"]["sha256"] == sha256(character)
    with pytest.raises(cp.ConversionPlanError, match="Automated retargeting is refused"):
        _plan(tmp_path, binding=plan_binding(MIXAMO_BONES, MIXAMO_BONES[:5]), **options)
    with pytest.raises(cp.ConversionPlanError, match="Automated retargeting is refused"):
        _plan(tmp_path, binding=None, **options)
    renamed = plan_binding(
        MIXAMO_BONES, [b.replace("mixamorig:", "mixamorig1:") for b in MIXAMO_BONES]
    )
    assert renamed.compatible  # names match after namespace removal ...
    with pytest.raises(cp.ConversionPlanError, match="no bone is renamed"):
        _plan(tmp_path, binding=renamed, **options)  # ... but the child will not rename them


# ------------------------------------------------------------------ blender discovery


def test_parse_version_and_minimum_version(tmp_path: Path) -> None:
    assert parse_version("Blender 4.2.3 LTS\n\tbuild date") == (4, 2, 3)
    assert parse_version("Blender 5.0") == (5, 0, 0)
    assert parse_version("ffmpeg version 7") is None
    install = fake_install(tmp_path)
    assert verify_blender("ignored", argv_prefix=install.argv_prefix).version == (4, 2, 3)


def test_verify_blender_refuses_old_missing_and_non_blender_executables(
    tmp_path: Path, monkeypatch
) -> None:
    install = fake_install(tmp_path)
    monkeypatch.setenv("FAKE_BLENDER_VERSION", "Blender 3.6.0")
    with pytest.raises(BlenderProblem, match="older than"):
        verify_blender("x", argv_prefix=install.argv_prefix)
    monkeypatch.setenv("FAKE_BLENDER_VERSION", "Something else 1.0")
    with pytest.raises(BlenderProblem, match="identify itself"):
        verify_blender("x", argv_prefix=install.argv_prefix)
    with pytest.raises(BlenderProblem, match="not found"):
        verify_blender(tmp_path / "no-blender.exe")


def test_candidates_come_from_explicit_env_path_and_program_folders_without_running_anything(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Blender Foundation" / "Blender 4.2"
    folder.mkdir(parents=True)
    found = blender_mod.candidate_executables(
        "C:/explicit/blender.exe",
        environ={blender_mod.ENV_VARIABLE: "D:/env/blender.exe"},
        which=lambda name: "E:/path/blender.exe",
        program_dirs=[str(tmp_path / "Blender Foundation")],
    )
    assert [str(p) for p in found[:3]] == [
        "C:\\explicit\\blender.exe",
        "D:\\env\\blender.exe",
        "E:\\path\\blender.exe",
    ] or [p.as_posix() for p in found[:3]] == [
        "C:/explicit/blender.exe",
        "D:/env/blender.exe",
        "E:/path/blender.exe",
    ]
    assert found[-1].name == "blender.exe" and "Blender 4.2" in str(found[-1])
    assert blender_mod.discover_blender(environ={}, which=lambda n: None, program_dirs=[]) is None


def test_child_environment_scrubs_python_redirection_and_isolates_user_dirs(tmp_path: Path) -> None:
    env = blender_mod.child_environment(
        {"PYTHONPATH": "x", "PATH": "p", "pythonhome": "y"}, tmp_path
    )
    assert "PYTHONPATH" not in env and "pythonhome" not in env and env["PATH"] == "p"
    for name in ("BLENDER_USER_SCRIPTS", "BLENDER_USER_CONFIG", "BLENDER_USER_EXTENSIONS"):
        assert Path(env[name]).is_dir() and tmp_path in Path(env[name]).parents


# ------------------------------------------------------------------ service (fake blender)


def _converter(tmp_path: Path, **env: str) -> MotionConverter:
    return MotionConverter(
        fake_install(tmp_path / "bin"),
        tmp_path / "out",
        ffmpeg=FFMPEG or "ffmpeg",
        environ=fake_environ(**env),
    )


def _only_published(tmp_path: Path) -> list[Path]:
    root = tmp_path / "out"
    return (
        [p for p in root.rglob("*") if p.is_file() and ".work" not in p.parts]
        if root.exists()
        else []
    )


def test_script_is_present_valid_python_and_never_imported_by_the_application() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    compile(source, "motion_render.bpy", "exec")
    assert (
        "use_scripts_auto_execute" not in source
    )  # the host passes --disable-autoexec; the script never re-enables it
    assert 'compute_device_type = "NONE"' in source and 'scene.cycles.device = "CPU"' in source
    assert "OPTIX" not in source and "CUDA" not in source
    assert "motion_conversion.blender_scripts" not in sys.modules


def test_probe_reports_the_files_facts_through_one_bounded_child(tmp_path: Path) -> None:
    conv = _converter(tmp_path, FAKE_BLENDER_FPS="30/1", FAKE_BLENDER_LAST="301/1")
    probe = conv.probe(tmp_path / "x.fbx", "fbx", transform=dict(cp.IMPORT_TRANSFORM))
    assert probe.fps == 30 and probe.frame_last == 301 and probe.bone_names == ("mixamorig:Hips",)
    assert not (tmp_path / "out" / ".work").exists() or not list(
        (tmp_path / "out" / ".work").iterdir()
    )


def test_the_blender_command_is_background_factory_startup_and_autoexec_disabled(
    tmp_path: Path,
) -> None:
    log = tmp_path / "args.log"
    conv = _converter(tmp_path, FAKE_BLENDER_LOG=str(log))
    conv.probe(tmp_path / "x.fbx", "fbx", transform=dict(cp.IMPORT_TRANSFORM))
    args = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    for flag in ("--background", "--factory-startup", "--disable-autoexec", "--python-exit-code"):
        assert flag in args
    assert args.index("--python") < args.index("--") and args[args.index("--") + 1] == "probe"


@needs_ffmpeg
def test_convert_publishes_a_verified_video_with_machine_readable_provenance(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, output_frames=9)
    original = plan.source_sha256
    result = _converter(tmp_path).convert(plan, warnings=("note",))
    assert result.status == STATUS_OK, result.reason
    assert Path(result.video_path).is_file() and result.frame_count == 9
    record = read_provenance(result.provenance_path)
    assert record is not None and record["derived"] is True and record["purpose"] == "accepted"
    assert record["source"]["sha256"] == original  # the original identity, not the derivative's
    assert record["output"]["sha256"] == result.output_sha256 == sha256(Path(result.video_path))
    assert record["output"]["sha256"] != original
    assert record["tools"]["render_device"] == "CPU" and record["tools"]["script_sha256"]
    assert record["conversion"]["target_fps"] == 24 and record["plan_digest"] == plan.digest
    assert record["warnings"] == ["note"] and record["character"]["mode"] == "embedded_skinned_mesh"
    assert verify_published(result.directory) == ""
    assert sha256(Path(plan.source_path)) == original  # the original was only read
    assert {p.name for p in _only_published(tmp_path)} == {
        Path(result.video_path).name,
        PROVENANCE_NAME,
    }


@needs_ffmpeg
def test_decoded_video_has_exactly_the_planned_frames_size_and_rate(tmp_path: Path) -> None:
    import subprocess

    from src.video.container_metadata import resolve_ffprobe_executable

    plan = _plan(tmp_path, output_frames=9, width=256, height=272)
    result = _converter(tmp_path).convert(plan)
    out = subprocess.run(
        [
            str(resolve_ffprobe_executable()),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames,width,height,r_frame_rate",
            "-of",
            "json",
            result.video_path,
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    stream = json.loads(out.stdout)["streams"][0]
    assert (
        int(stream["nb_read_frames"]),
        stream["width"],
        stream["height"],
        stream["r_frame_rate"],
    ) == (9, 256, 272, "24/1")


@needs_ffmpeg
def test_repeating_a_verified_conversion_reuses_it_and_a_corrupt_copy_is_published_beside_not_over(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, output_frames=5)
    first = _converter(tmp_path).convert(plan)
    again = _converter(tmp_path).convert(plan)
    assert again.status == STATUS_REUSED and again.output_sha256 == first.output_sha256
    Path(first.video_path).write_bytes(b"corrupted")
    third = _converter(tmp_path).convert(plan)
    assert third.status == STATUS_OK and third.directory != first.directory
    assert (
        Path(first.video_path).read_bytes() == b"corrupted"
    )  # the unverifiable folder was left alone


@needs_ffmpeg
def test_preview_is_short_labeled_and_cannot_be_the_accepted_derivative(tmp_path: Path) -> None:
    plan = _plan(tmp_path, output_frames=17)
    short = preview_plan(plan)
    assert short.output_frames == 9 and short.start_seconds == plan.start_seconds
    result = _converter(tmp_path).convert(short, purpose="preview")
    assert result.ok and "previews" in Path(result.directory).parts
    assert read_provenance(result.provenance_path)["purpose"] == "preview"


@pytest.mark.parametrize(
    ("mode", "fragment"),
    [
        ("crash", "could not render"),
        ("short", "different number"),
        ("lie", "produced 4 file"),
        ("gpu", "not confirmed CPU-only"),
        ("partial", "boom"),
        ("blank", "shows no visible subject"),
        ("static", "animation was not applied"),
    ],
)
def test_a_failed_or_untrustworthy_render_publishes_nothing(
    tmp_path: Path, mode: str, fragment: str
) -> None:
    result = _converter(tmp_path, FAKE_BLENDER_MODE=mode).convert(_plan(tmp_path, output_frames=5))
    assert result.status == STATUS_FAILED and fragment in result.reason
    assert _only_published(tmp_path) == []
    assert not (tmp_path / "out" / "converted").exists()


def test_a_hung_blender_is_stopped_at_the_timeout_and_a_cancel_is_honoured(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("src.video.motion_conversion.conversion_service.BLENDER_BASE_SECONDS", 1.0)
    monkeypatch.setattr(
        "src.video.motion_conversion.conversion_service.BLENDER_SECONDS_PER_FRAME", 0.0
    )
    timed = _converter(tmp_path, FAKE_BLENDER_MODE="hang").convert(_plan(tmp_path, output_frames=5))
    assert timed.status == STATUS_FAILED and "did not finish" in timed.reason

    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    monkeypatch.setattr("src.video.motion_conversion.conversion_service.BLENDER_BASE_SECONDS", 60.0)
    stopped = _converter(tmp_path, FAKE_BLENDER_MODE="hang").convert(
        _plan(tmp_path, output_frames=5), cancel=cancel
    )
    assert stopped.status == STATUS_CANCELLED
    assert _only_published(tmp_path) == []


def test_a_changed_source_is_refused_before_blender_runs(tmp_path: Path) -> None:
    plan = _plan(tmp_path, output_frames=5)
    Path(plan.source_path).write_bytes(Path(plan.source_path).read_bytes() + b"x")
    log = tmp_path / "args.log"
    result = _converter(tmp_path, FAKE_BLENDER_LOG=str(log)).convert(plan)
    assert result.status == STATUS_FAILED and "changed since the plan" in result.reason
    assert not log.exists()


def test_only_folders_the_converter_created_are_ever_removed(tmp_path: Path) -> None:
    work = tmp_path / "out" / ".work"
    foreign = work / "someone-elses-folder"
    foreign.mkdir(parents=True)
    (foreign / "keep.txt").write_text("mine", encoding="utf-8")
    impostor = work / "run-impostor"
    impostor.mkdir()
    (impostor / OWNER_MARKER).write_text("a different name", encoding="utf-8")
    _converter(tmp_path, FAKE_BLENDER_MODE="crash").convert(_plan(tmp_path, output_frames=5))
    assert (foreign / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert impostor.is_dir()
    converter = _converter(tmp_path)
    converter._remove_owned(foreign)  # a folder without its marker is never removed
    assert foreign.is_dir()


def test_frame_verification_catches_missing_extra_and_wrongly_sized_frames(tmp_path: Path) -> None:
    import struct
    import zlib

    from tests.helpers.motion_conversion_354 import (
        FAKE_BLENDER,  # noqa: F401  (png writer lives in the fake)
    )

    def png(w: int, h: int, subject: bool = True) -> bytes:
        def chunk(kind: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
            )

        bar = b"\x10" * (w // 4 * 3) + b"\xa0" * (w // 2 * 3) + b"\x10" * (w // 4 * 3)
        plain = b"\x10" * (w * 3)
        raw = b"".join(
            b"\x00" + (bar if subject and h // 4 <= y < 3 * h // 4 else plain) for y in range(h)
        )
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )

    frames = tmp_path / "f"
    frames.mkdir()
    for i in range(1, 4):
        (frames / f"frame_{i:05d}.png").write_bytes(png(8, 8))
    assert verify_frames(frames, 3, 8, 8) == ""
    assert "expected 4" in verify_frames(frames, 4, 8, 8)
    (frames / "frame_00004.png").write_bytes(png(9, 8))
    assert "not a 8x8 PNG" in verify_frames(frames, 4, 8, 8)
    (frames / "extra.png").write_bytes(png(8, 8))
    assert "unexpected" in verify_frames(frames, 4, 8, 8)
    (frames / "extra.png").unlink()
    (frames / "frame_00004.png").write_bytes(png(8, 8, subject=False))
    assert "frame_00004.png shows no visible subject" in verify_frames(frames, 4, 8, 8)
    (frames / "frame_00004.png").write_bytes(b"not a png at all, but sized wrong anyway")
    assert "is not a 8x8 PNG" in verify_frames(frames, 4, 8, 8)

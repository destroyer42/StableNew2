"""PR-VID-MOTION-356: a long Blender render is no longer killed for talking, and every failure says why.

The reproduced owner failure: a 129-frame render wrote more progress text to the console than the fixed output cap, the
cap stopped the child, and the operator saw only ``Blender exited with code 1``.  These tests use the fake Blender
(no Blender, GPU, model or network).
"""

from __future__ import annotations

import json
import os
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from src.utils.managed_process import run_bounded
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion import diagnostics as diag
from src.video.motion_conversion.conversion_service import (
    STATUS_FAILED,
    STATUS_OK,
    MotionConverter,
    ProbeError,
)
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


def _plan(tmp_path: Path, **overrides):
    source = write_fbx(tmp_path / "src" / "walk.fbx")
    options = {
        "source_path": str(source),
        "source_sha256": sha256(source),
        "source_route": cp.SOURCE_FBX_CHARACTER,
        "probe": PROBE,
        "profile": cp.PROFILE_CHARACTER,
        "output_frames": 5,
        "width": 256,
        "height": 272,
    }
    options.update(overrides)
    return cp.build_plan(**options)


def _converter(tmp_path: Path, **env: str) -> MotionConverter:
    return MotionConverter(
        fake_install(tmp_path / "bin"),
        tmp_path / "out",
        ffmpeg=FFMPEG or "ffmpeg",
        environ=fake_environ(**env),
        diagnostics_dir=tmp_path / "diag",
    )


def _reports(tmp_path: Path) -> list[dict]:
    folder = tmp_path / "diag"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("diag-*.json"))]


# ------------------------------------------------------------------ the reproduced root cause


def test_run_bounded_can_keep_the_tail_of_a_chatty_child_without_stopping_it() -> None:
    code = "import sys\nfor i in range(20000): print('progress line %d' % i)\nprint('FINAL-LINE')\n"
    stopped = run_bounded([sys.executable, "-c", code], timeout_seconds=30, max_stdout_bytes=4096)
    assert (
        stopped.output_truncated and b"FINAL-LINE" not in stopped.stdout
    )  # the old, default behaviour

    kept = run_bounded(
        [sys.executable, "-c", code],
        timeout_seconds=30,
        max_stdout_bytes=4096,
        keep_output_tail=True,
    )
    assert kept.returncode == 0 and kept.output_truncated
    assert len(kept.stdout) <= 4096 and kept.stdout.rstrip().endswith(b"FINAL-LINE")


@needs_ffmpeg
def test_a_render_that_writes_far_more_console_output_than_the_cap_still_publishes(
    tmp_path: Path,
) -> None:
    result = _converter(tmp_path, FAKE_BLENDER_MODE="chatty").convert(_plan(tmp_path))
    assert result.status == STATUS_OK, result.reason
    assert Path(result.video_path).is_file() and not _reports(tmp_path)


def test_a_chatty_child_that_also_crashes_still_reports_its_last_words(tmp_path: Path) -> None:
    result = _converter(tmp_path, FAKE_BLENDER_MODE="oom").convert(_plan(tmp_path))
    assert result.status == STATUS_FAILED and result.failure_kind == diag.KIND_MEMORY
    assert "out of memory" in result.reason.lower()


# ------------------------------------------------------------------ classification


@pytest.mark.parametrize(
    ("mode", "kind", "fragment"),
    [
        ("crash", diag.KIND_CRASH, "exited with code 1 before it wrote a result"),
        ("oom", diag.KIND_MEMORY, "ran out of memory"),
        ("badrig", diag.KIND_RIG, "rest pose differs"),
        ("badfile", diag.KIND_ASSET, "no animation action"),
        ("gpu", diag.KIND_CAPABILITY, "not confirmed CPU-only"),
        ("short", diag.KIND_OUTPUT, "different number"),
        ("blank", diag.KIND_OUTPUT, "no visible subject"),
        ("static", diag.KIND_OUTPUT, "not applied"),
    ],
)
def test_each_failure_is_classified_with_its_own_cause_and_a_report(
    tmp_path: Path, mode: str, kind: str, fragment: str
) -> None:
    result = _converter(tmp_path, FAKE_BLENDER_MODE=mode).convert(_plan(tmp_path))
    assert result.status == STATUS_FAILED
    assert result.failure_kind == kind, result.reason
    assert fragment in result.reason
    assert result.diagnostic_path and Path(result.diagnostic_path).is_file()
    report = json.loads(Path(result.diagnostic_path).read_text(encoding="utf-8"))
    assert report["schema"] == diag.DIAGNOSTIC_SCHEMA and report["kind"] == kind
    assert report["context"]["source_name"] == "walk.fbx" and report["context"]["plan_digest"]


def test_timeout_cancellation_and_changed_input_have_their_own_kinds(
    tmp_path: Path, monkeypatch
) -> None:
    import threading

    monkeypatch.setattr("src.video.motion_conversion.conversion_service.BLENDER_BASE_SECONDS", 1.0)
    monkeypatch.setattr(
        "src.video.motion_conversion.conversion_service.BLENDER_SECONDS_PER_FRAME", 0.0
    )
    timed = _converter(tmp_path, FAKE_BLENDER_MODE="hang").convert(_plan(tmp_path))
    assert timed.failure_kind == diag.KIND_TIMEOUT and "did not finish" in timed.reason

    monkeypatch.setattr("src.video.motion_conversion.conversion_service.BLENDER_BASE_SECONDS", 60.0)
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    stopped = _converter(tmp_path, FAKE_BLENDER_MODE="hang").convert(_plan(tmp_path), cancel=cancel)
    assert stopped.status == "cancelled" and stopped.failure_kind == diag.KIND_CANCELLED
    assert stopped.diagnostic_path == ""  # a deliberate stop is not a fault

    plan = _plan(tmp_path)
    Path(plan.source_path).write_bytes(Path(plan.source_path).read_bytes() + b"x")
    changed = _converter(tmp_path).convert(plan)
    assert changed.failure_kind == diag.KIND_SOURCE


def test_a_failed_probe_raises_with_the_classified_result(tmp_path: Path) -> None:
    converter = _converter(tmp_path, FAKE_BLENDER_MODE="badfile")
    with pytest.raises(ProbeError) as caught:
        converter.probe(tmp_path / "x.fbx", "fbx", transform=dict(cp.IMPORT_TRANSFORM))
    assert caught.value.result is not None
    assert caught.value.result.failure_kind == diag.KIND_ASSET
    assert Path(caught.value.result.diagnostic_path).is_file()


def test_blender_ending_with_an_operating_system_fault_code_is_a_crash_not_a_generic_exit() -> None:
    info = diag.classify_blender_failure(
        "render",
        returncode=0xC0000005,
        timed_out=False,
        cancelled=False,
        launch_error="",
        report=None,
        stdout=b"",
        stderr=b"Error: EXCEPTION_ACCESS_VIOLATION\nwriting crash report",
        timeout_seconds=60,
    )
    assert info.kind == diag.KIND_CRASH
    assert "0xC0000005" in info.message and "EXCEPTION_ACCESS_VIOLATION" in info.message
    memory = diag.classify_blender_failure(
        "render",
        returncode=0xC0000017,
        timed_out=False,
        cancelled=False,
        launch_error="",
        report=None,
        stdout=b"",
        stderr=b"",
        timeout_seconds=60,
    )
    assert memory.kind == diag.KIND_MEMORY


def test_a_missing_report_is_distinguished_from_a_reported_error() -> None:
    silent = diag.classify_blender_failure(
        "probe",
        returncode=1,
        timed_out=False,
        cancelled=False,
        launch_error="",
        report=None,
        stdout=b"",
        stderr=b"",
        timeout_seconds=60,
    )
    assert silent.kind == diag.KIND_CRASH and "printed no error" in silent.message
    launch = diag.classify_blender_failure(
        "probe",
        returncode=None,
        timed_out=False,
        cancelled=False,
        launch_error="containment unavailable",
        report=None,
        stdout=b"",
        stderr=b"",
        timeout_seconds=60,
    )
    assert launch.kind == diag.KIND_LAUNCH


# ------------------------------------------------------------------ report hygiene


def test_reports_never_contain_the_users_profile_path_or_credentials(tmp_path: Path) -> None:
    home = str(Path.home())
    redact = diag.redactor([(tmp_path / "out", "<conversion-root>")])
    text = (
        f"{home}\\Videos\\clip.fbx {str(tmp_path / 'out')}/converted/x "
        "C:\\Users\\someoneelse\\Desktop\\a.fbx /home/bob/a.bvh api_key=abcd1234 Authorization: Bearer zzz"
    )
    cleaned = redact(text)
    assert home not in cleaned and "someoneelse" not in cleaned and "/home/bob" not in cleaned
    assert "abcd1234" not in cleaned and "zzz" not in cleaned
    assert "<conversion-root>" in cleaned


def test_a_report_for_a_failed_render_has_bounded_redacted_output_tails(tmp_path: Path) -> None:
    result = _converter(tmp_path, FAKE_BLENDER_MODE="oom").convert(_plan(tmp_path))
    report = json.loads(Path(result.diagnostic_path).read_text(encoding="utf-8"))
    assert report["redacted"] is True and "out of memory" in report["stderr_tail"].lower()
    assert (
        len(report["stdout_tail"]) <= diag.TAIL_BYTES
        and len(report["stderr_tail"]) <= diag.TAIL_BYTES
    )
    serialized = json.dumps(report)
    assert str(Path.home()) not in serialized
    assert (
        os.environ.get("USERNAME", "\0\0\0\0\0") not in serialized
        or len(os.environ.get("USERNAME", "")) < 4
    )


def test_reports_are_retained_in_bounded_number_and_only_named_files_are_pruned(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "diag"
    folder.mkdir()
    bystander = folder / "notes.txt"
    bystander.write_text("mine", encoding="utf-8")
    failure = diag.FailureInfo(diag.KIND_CRASH, "boom")
    redact = diag.redactor()
    for index in range(diag.MAX_REPORTS + 6):
        report = diag.build_report(failure, context={}, process={}, redact=redact)
        path = diag.write_report(folder, report)
        os.utime(path, (1_000_000 + index, 1_000_000 + index))
    names = sorted(p.name for p in folder.glob("diag-*.json"))
    assert len(names) == diag.MAX_REPORTS
    assert bystander.read_text(encoding="utf-8") == "mine"


def test_report_text_only_reads_files_this_module_named(tmp_path: Path) -> None:
    folder = tmp_path / "diag"
    path = diag.write_report(
        folder,
        diag.build_report(
            diag.FailureInfo(diag.KIND_ASSET, "x"), context={}, process={}, redact=str
        ),
    )
    assert json.loads(diag.report_text(path))["kind"] == diag.KIND_ASSET
    other = tmp_path / "secret.txt"
    other.write_text("not a report", encoding="utf-8")
    assert diag.report_text(other) == ""
    assert diag.report_text(tmp_path / "missing.json") == ""

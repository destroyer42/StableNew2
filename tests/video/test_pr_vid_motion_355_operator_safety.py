"""PR-VID-MOTION-355: resource-bounded Fun Control source preparation.

No GPU, Comfy, model or network is needed. The physical Fun qualification status
remains unchanged; these prove file-safety and the frame transform contract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.video import motion_source_preparation as prep
from src.video.motion_source_plan import MotionSourceContract
from tests.video.test_pr_vid_motion_210_preparation import _clip, needs_ffmpeg


def _fun(frames: int = 17) -> MotionSourceContract:
    return MotionSourceContract(prep.FUN_CONTROL_WORKFLOW_ID, "1.0.0", frames, 24, "rev", "rule")


def test_fun_geometry_only_limits_named_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prep, "FUN_CONTROL_MAX_SOURCE_EDGE", 832)
    assert prep.fun_control_resize(3840, 2160, prep.FUN_CONTROL_WORKFLOW_ID) == (832, 468)
    assert prep.fun_control_resize(2160, 3840, prep.FUN_CONTROL_WORKFLOW_ID) == (468, 832)
    assert prep.fun_control_resize(832, 468, prep.FUN_CONTROL_WORKFLOW_ID) is None
    assert prep.fun_control_resize(3840, 2160, "wan_animate2_drive_i2v_v1") is None
    with pytest.raises(ValueError, match="too narrow"):
        prep.fun_control_resize(1, 3840, prep.FUN_CONTROL_WORKFLOW_ID)


@needs_ffmpeg
def test_fun_source_is_resized_before_canny_and_verifies_exact_transformed_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prep, "FUN_CONTROL_MAX_SOURCE_EDGE", 128)
    original = _clip(tmp_path, frames=32, size="192x108")
    before = original.read_bytes()
    outcome = prep.prepare_motion_source(
        prep.MotionSourceRequest(str(original), _fun()), output_root=tmp_path / "out"
    )
    assert outcome.prepared, outcome.message
    assert "safety resize" in outcome.message
    assert original.read_bytes() == before

    record = outcome.record
    assert record is not None
    assert (record["derived"]["width"], record["derived"]["height"]) == (128, 72)
    assert record["processing"]["lossless"] is False
    assert record["processing"]["resize"] == {
        "width": 128,
        "height": 72,
        "filter": "bilinear",
        "policy": "fun-control-canny-max-832",
    }
    prepared = Path(record["derived"]["path"])
    # The reference is independently decoded from the original source. A
    # transcode must not silently omit, repeat or corrupt the planned frames.
    cmd = [
        str(prep.resolve_ffmpeg_executable()),
        "-v",
        "error",
        "-nostdin",
        "-noautorotate",
        "-i",
        str(original),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "scale=128:72:flags=bilinear",
        "-frames:v",
        "17",
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        "yuv420p",
        "-f",
        "framemd5",
        "-",
    ]
    reference = subprocess.run(cmd, capture_output=True, check=True, timeout=120)
    expected = prep.parse_framemd5(reference.stdout)
    assert len(expected) == 17
    assert expected == prep.parse_framemd5(
        subprocess.run(
            prep.build_file_md5_command(prep.resolve_ffmpeg_executable(), prepared, "yuv420p"),
            capture_output=True,
            check=True,
            timeout=120,
        ).stdout
    )
    prep.validate_prepared_record(record, original_path=original, contract=_fun())


@needs_ffmpeg
def test_old_full_resolution_fun_source_is_refused_at_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _clip(tmp_path, frames=24, size="192x108")
    monkeypatch.setattr(prep, "FUN_CONTROL_MAX_SOURCE_EDGE", 256)
    outcome = prep.prepare_motion_source(
        prep.MotionSourceRequest(str(original), _fun()), output_root=tmp_path / "out"
    )
    assert outcome.prepared, outcome.message
    assert outcome.record is not None
    assert outcome.record["processing"]["resize"] is None
    monkeypatch.setattr(prep, "FUN_CONTROL_MAX_SOURCE_EDGE", 128)
    with pytest.raises(prep.PreparedMotionSourceError, match="Prepare it again"):
        prep.validate_prepared_record(outcome.record, original_path=original, contract=_fun())


def test_matching_rig_names_are_distinct_from_an_executable_blender_binding() -> None:
    from src.video.motion_conversion.rig_compat import plan_binding
    from tests.helpers.motion_conversion_354 import MIXAMO_BONES

    exact = plan_binding(MIXAMO_BONES, MIXAMO_BONES)
    assert exact.compatible and exact.can_apply
    renamed = plan_binding(
        MIXAMO_BONES,
        [bone.replace("mixamorig:", "mixamorig1:") for bone in MIXAMO_BONES],
    )
    assert renamed.compatible  # common humanoid layout is recognized
    assert not renamed.can_apply  # conversion cannot rename the target bones safely


@needs_ffmpeg
def test_rotated_phone_clip_uses_coded_dimensions_for_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metadata dimensions are display-oriented; Canny decodes coded pixels."""
    original = _clip(tmp_path, frames=24, size="192x108")
    monkeypatch.setattr(prep, "FUN_CONTROL_MAX_SOURCE_EDGE", 128)
    outcome = prep.prepare_motion_source(
        prep.MotionSourceRequest(str(original), _fun()), output_root=tmp_path / "out"
    )
    assert outcome.prepared, outcome.message
    assert outcome.record is not None
    record = dict(outcome.record)
    record["original"] = dict(record["original"])
    record["derived"] = dict(record["derived"])
    record["original"]["width"], record["original"]["height"] = 108, 192
    record["derived"]["width"], record["derived"]["height"] = 72, 128
    record["original"]["rotation_quadrants"] = 1
    record["derived"]["rotation_quadrants"] = 1
    verified = prep.validate_prepared_record(record, original_path=original, contract=_fun())
    assert verified["processing"]["resize"]["width"] == 128

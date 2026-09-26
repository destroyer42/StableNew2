"""Deterministic PR-VID-183 guards: no GPU, no network, no real Comfy."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.qualification.vid183 import provenance as prov


def _write_pose(path: Path, *, offset: int, moving: bool = True) -> None:
    import cv2
    import numpy as np

    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), prov.FPS, (prov.WIDTH, prov.HEIGHT)
    )
    for index in range(prov.FRAMES):
        frame = np.zeros((prov.HEIGHT, prov.WIDTH, 3), dtype=np.uint8)
        x = 100 + offset + (index * 4 if moving else 0)
        cv2.circle(frame, (x, 400), 32, (255, 255, 255), -1)
        writer.write(frame)
    writer.release()


def test_source_window_and_reference_are_frozen() -> None:
    assert (
        prov.REFERENCE_SHA256 == "362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb"
    )
    assert (prov.SOURCE_START_SECONDS, prov.SOURCE_DURATION_SECONDS) == (8.0, 1.625)


def test_launcher_calls_pinned_upstream_basic_retarget_without_flux() -> None:
    source = Path("tools/qualification/vid183/preprocess_launcher.py").read_text(encoding="utf-8")
    assert 'os.environ["CUDA_VISIBLE_DEVICES"] = "-1"' in source
    assert "from retarget_pose import get_retarget_pose" in source
    assert "get_retarget_pose(tpl_pose_meta0, refer_meta, tpl_pose_metas, None, None)" in source
    assert '"use_flux": False' in source
    assert "import sam2" not in source.lower()
    assert "from diffusers import flux" not in source.lower()


def test_source_prep_is_fixed_crop_not_tracking() -> None:
    from tools.qualification.vid183 import source_prep

    source = Path("tools/qualification/vid183/source_prep.py").read_text(encoding="utf-8")
    assert "no_tracking_crop" in source
    assert (
        source_prep.driving_prep.ffmpeg_filter(450, 30, 13)
        == "crop=377:676:450:30,scale=464:832:flags=lanczos"
    )


def test_pair_validation_requires_difference_and_motion(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _write_pose(a, offset=0)
    _write_pose(b, offset=40)
    result = prov.validate_control_pair(a, b)
    assert result["mean_frame_pixel_delta"] > 1.0
    assert result["motion_energy_a"] > 0.0 and result["motion_energy_b"] > 0.0


def test_pair_validation_rejects_identical_controls(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    control = tmp_path / "control.mp4"
    _write_pose(control, offset=0)
    with pytest.raises(RuntimeError, match="NO_MEANINGFUL"):
        prov.validate_control_pair(control, control)


def test_runner_has_only_a_and_b_with_recorded_cpu_gated_hashes() -> None:
    from tools.qualification.vid183 import run

    assert run.CASES == ["A", "B"]
    assert (
        run.CONTROLS["A"]["sha256"]
        == "ac2e52c476176cfcc023b60552e29f817c10e73ba61ac4b0cc43895d3f43fc82"
    )
    assert (
        run.CONTROLS["B"]["sha256"]
        == "eb4aa6fb701a15dbfcf28fe7d4c7dc70e871a6fd9e052d07ec3e4e67bb2e3dde"
    )


def test_runner_refuses_gpu_work_without_matching_cpu_pair_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tools.qualification.vid183 import run

    monkeypatch.setattr(run, "WORKSPACE", tmp_path)
    with pytest.raises(RuntimeError, match="missing CPU pair-validation"):
        run.verify_pair_evidence()

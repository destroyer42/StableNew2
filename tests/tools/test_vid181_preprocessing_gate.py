"""PR-VID-181 preprocessing gate: pinned upstream identity, forced-CPU preprocessing, production
environment rejection, deterministic hashing/frame selection/final pose adaptation to the frozen
480x832 / 13f / 8fps control, and the future Animate spec staying frozen to PR-VID-175/180
(no GPU, no ONNX inference, no network, no real Comfy)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.qualification.vid160c.pose_asset import sample_indices
from tools.qualification.vid170.graph import CharacterizationSpec, build_characterization_graph
from tools.qualification.vid180 import run as vid180_run
from tools.qualification.vid181 import provenance as prov

# --- pinned upstream identity / frozen model names ----------------------------------------------


def test_upstream_and_checkpoint_identity_are_frozen() -> None:
    assert prov.UPSTREAM_SHA == "1ea34ff48f87168174e12956e200b1d908b1c5ff"
    assert prov.CHECKPOINT_REVISION == "cb93a225fbaf1ca100f54e79da8f994995b689b3"
    assert prov.DET_MODEL == "det/yolov10m.onnx"
    assert prov.POSE_MODEL == "pose2d/vitpose_h_wholebody.onnx"


def test_cpu_provider_is_forced_by_contract() -> None:
    assert prov.PROVIDER == "CPUExecutionProvider"
    source = Path("tools/qualification/vid181/preprocess_launcher.py").read_text(encoding="utf-8")
    disable = source.index('os.environ["CUDA_VISIBLE_DEVICES"] = "-1"')
    first_heavy = source.index("import onnxruntime")
    assert disable < first_heavy
    assert 'device="cpu"' in source
    assert "det_providers != [prov.PROVIDER]" in source


def _launcher_main(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "unset-by-test")
    from tools.qualification.vid181 import preprocess_launcher

    return preprocess_launcher.main


# --- production environments cannot be the preprocessing target ---------------------------------


@pytest.mark.parametrize(
    "prefix",
    [
        r"C:\Users\rob\projects\StableNew\.venv",
        r"C:\Users\rob\AppData\Local\Programs\ComfyUI\resources\ComfyUI\.venv",
        r"C:\ComfyUI\.venv-explicit",
        r"C:\stable-diffusion-webui\venv",
        "/opt/a1111/venv",
    ],
)
def test_production_environment_prefixes_are_rejected(prefix: str) -> None:
    with pytest.raises(RuntimeError, match="production-looking"):
        prov.assert_isolated_env(prefix)


def test_disposable_environment_prefix_is_accepted() -> None:
    prov.assert_isolated_env(r"C:\Users\rob\qual\vid181\venv")


def test_launcher_rejects_production_interpreter_before_doing_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    main = _launcher_main(monkeypatch)
    monkeypatch.setattr(sys, "prefix", r"C:\Users\rob\projects\StableNew\.venv")
    with pytest.raises(RuntimeError, match="production-looking"):
        main(
            [
                "--upstream", str(tmp_path), "--ckpt", str(tmp_path), "--video", "v.mp4",
                "--refer", "r.png", "--out", str(tmp_path / "out"),
            ]
        )
    assert not (tmp_path / "out").exists()


def test_launcher_rejects_unpinned_upstream_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    main = _launcher_main(monkeypatch)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "disposable-venv"))
    repo = tmp_path / "upstream"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
    )
    with pytest.raises(RuntimeError, match="!= pinned"):
        main(
            [
                "--upstream", str(repo), "--ckpt", str(tmp_path), "--video", "v.mp4",
                "--refer", "r.png", "--out", str(tmp_path / "out"),
            ]
        )


# --- hashing / provenance ------------------------------------------------------------------------


def test_tree_sha256_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.bin").write_bytes(b"1")
    (tmp_path / "two.bin").write_bytes(b"22")
    first = prov.tree_sha256(tmp_path)
    assert first == prov.tree_sha256(tmp_path)
    assert first["files"] == 2 and first["bytes"] == 3
    (tmp_path / "two.bin").write_bytes(b"23")
    assert prov.tree_sha256(tmp_path)["manifest_sha256"] != first["manifest_sha256"]


def test_sha256_of_matches_known_digest(tmp_path: Path) -> None:
    path = tmp_path / "x"
    path.write_bytes(b"abc")
    assert prov.sha256_of(path) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


# --- frame selection and final 480x832 / 13f / 8fps adaptation -----------------------------------


def test_select_indices_matches_the_accepted_pr_vid_160c_convention() -> None:
    assert prov.select_indices(49, 13) == sample_indices(49, 13)
    indices = prov.select_indices(200, 13)
    assert indices[0] == 0 and indices[-1] == 199 and len(indices) == 13
    assert indices == sorted(set(indices))


def _write_video(path: Path, size: tuple[int, int], frames: int) -> None:
    import cv2
    import numpy as np

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24.0, size)
    for t in range(frames):
        canvas = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        cv2.circle(canvas, (20 + t * 3, size[1] // 2), 10, (255, 255, 255), -1)
        writer.write(canvas)
    writer.release()


def test_adaptation_at_frozen_geometry_is_lossless_selection_and_deterministic(
    tmp_path: Path,
) -> None:
    import cv2

    source = tmp_path / "full.mp4"
    _write_video(source, (prov.WIDTH, prov.HEIGHT), 40)
    first, indices, operation = prov.adapt_pose_to_frozen(source, tmp_path / "a.mp4")
    second, _, _ = prov.adapt_pose_to_frozen(source, tmp_path / "b.mp4")
    assert prov.sha256_of(first) == prov.sha256_of(second)
    assert indices == prov.select_indices(40, 13)
    assert operation["operation"] == "none" and operation["source_frame_count"] == 40
    capture = cv2.VideoCapture(str(first))
    assert int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) == 480
    assert int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 832
    assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 13
    assert capture.get(cv2.CAP_PROP_FPS) == pytest.approx(8.0)
    capture.release()


def test_adaptation_of_other_geometry_letterboxes_without_stretching(tmp_path: Path) -> None:
    source = tmp_path / "landscape.mp4"
    _write_video(source, (832, 464), 20)
    _, _, operation = prov.adapt_pose_to_frozen(source, tmp_path / "out.mp4")
    assert operation["operation"] == "aspect_preserving_letterbox"
    new_w, new_h = operation["scaled_size"]
    assert new_w / new_h == pytest.approx(832 / 464, rel=0.01)
    assert new_w <= prov.WIDTH and new_h <= prov.HEIGHT


def test_adaptation_rejects_undecodable_source(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(ValueError, match="fewer than 2"):
        prov.adapt_pose_to_frozen(bad, tmp_path / "out.mp4")


# --- future Animate spec stays frozen to PR-VID-175/180 settings, face_video excluded ------------


def test_frozen_geometry_matches_the_accepted_animate_envelope() -> None:
    assert (prov.WIDTH, prov.HEIGHT) == (vid180_run.WIDTH, vid180_run.HEIGHT) == (480, 832)
    assert (prov.FRAMES, prov.FPS) == (13, 8.0)


def test_future_animate_spec_is_the_vid175_180_configuration_without_face_video() -> None:
    spec = CharacterizationSpec(
        reference_image="source_fullbody.png",
        pose_video_file="pose.mp4",
        width=prov.WIDTH,
        height=prov.HEIGHT,
    )
    assert (spec.length, spec.fps, spec.steps, spec.cfg, spec.shift) == (13, 8.0, 20, 1.0, 5.0)
    assert (spec.sampler, spec.scheduler, spec.seed) == ("uni_pc", "simple", 1733123036)
    animate = next(
        n["inputs"]
        for n in build_characterization_graph(spec).values()
        if n["class_type"] == "WanAnimateToVideo"
    )
    assert animate["pose_video"] == ["17", 0]
    assert "face_video" not in animate


# --- deterministic driving-footage prep (fixed crop, exact aspect, no stretching) ---------------


def test_driving_crop_is_exact_pose_aspect_at_any_scale() -> None:
    from tools.qualification.vid181 import driving_prep as dp

    for k in (1, 10, 13):
        width, height = dp.crop_size(k)
        assert width * dp.OUT_H == height * dp.OUT_W
    assert dp.crop_size(13) == (377, 676)


def test_driving_filter_is_a_fixed_crop_then_scale_to_464x832() -> None:
    from tools.qualification.vid181 import driving_prep as dp

    assert dp.ffmpeg_filter(490, 0, 13) == "crop=377:676:490:0,scale=464:832:flags=lanczos"
    with pytest.raises(ValueError):
        dp.ffmpeg_filter(-1, 0, 13)
    with pytest.raises(ValueError):
        dp.crop_size(0)

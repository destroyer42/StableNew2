from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image

from src.video.svd_config import SVDConfig
from src.video.svd_postprocess import (
    SVDPostprocessRunner,
    get_codeformer_runtime_issues,
    resolve_rife_executable,
    validate_svd_postprocess_config,
)


def test_validate_svd_postprocess_accepts_disabled_defaults() -> None:
    valid, reason = validate_svd_postprocess_config(SVDConfig())

    assert valid is True
    assert reason is None


def test_validate_svd_postprocess_requires_rife_executable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("STABLENEW_RIFE_EXE", raising=False)
    monkeypatch.setenv("PATH", "")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "multiplier": 2,
                }
            }
        }
    )

    valid, reason = validate_svd_postprocess_config(config)

    assert valid is False
    assert reason is not None
    assert "RIFE" in reason


def test_validate_svd_postprocess_requires_codeformer_facelib_weights(tmp_path: Path) -> None:
    codeformer_weight = tmp_path / "codeformer.pth"
    facelib_root = tmp_path / "GFPGAN"
    codeformer_weight.write_bytes(b"weights")
    facelib_root.mkdir()
    (facelib_root / "detection_Resnet50_Final.pth").write_bytes(b"det")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "face_restore": {
                    "enabled": True,
                    "method": "CodeFormer",
                    "codeformer_weight_path": str(codeformer_weight),
                    "facelib_model_root": str(facelib_root),
                }
            }
        }
    )

    valid, reason = validate_svd_postprocess_config(config)

    assert valid is False
    assert reason is not None
    assert "parsing_parsenet.pth" in reason


def test_get_codeformer_runtime_issues_is_empty_when_all_assets_exist(tmp_path: Path) -> None:
    codeformer_weight = tmp_path / "codeformer.pth"
    facelib_root = tmp_path / "GFPGAN"
    codeformer_weight.write_bytes(b"weights")
    facelib_root.mkdir()
    (facelib_root / "detection_Resnet50_Final.pth").write_bytes(b"det")
    (facelib_root / "parsing_parsenet.pth").write_bytes(b"parse")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "face_restore": {
                    "enabled": True,
                    "method": "CodeFormer",
                    "codeformer_weight_path": str(codeformer_weight),
                    "facelib_model_root": str(facelib_root),
                }
            }
        }
    )

    issues = get_codeformer_runtime_issues(config.postprocess)

    assert issues == []


def test_resolve_rife_executable_prefers_explicit_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("STABLENEW_RIFE_EXE", raising=False)
    monkeypatch.setenv("PATH", "")
    executable = tmp_path / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "executable_path": str(executable),
                }
            }
        }
    )

    resolved = resolve_rife_executable(config.postprocess)

    assert resolved == executable


def test_postprocess_runner_returns_original_frames_when_disabled(tmp_path: Path) -> None:
    frames = [Image.new("RGB", (64, 64), "white"), Image.new("RGB", (64, 64), "black")]
    runner = SVDPostprocessRunner()

    processed, metadata = runner.process_frames(
        frames=frames,
        config=SVDConfig(),
        work_dir=tmp_path,
    )

    assert len(processed) == 2
    assert metadata is None


def test_postprocess_runner_face_restore_stage_returns_worker_outputs(tmp_path: Path, monkeypatch) -> None:
    frames = [Image.new("RGB", (32, 32), "white"), Image.new("RGB", (32, 32), "black")]
    codeformer_weight = tmp_path / "codeformer.pth"
    facelib_root = tmp_path / "GFPGAN"
    codeformer_weight.write_bytes(b"weights")
    facelib_root.mkdir()
    (facelib_root / "detection_Resnet50_Final.pth").write_bytes(b"det")
    (facelib_root / "parsing_parsenet.pth").write_bytes(b"parse")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "face_restore": {
                    "enabled": True,
                    "method": "CodeFormer",
                    "codeformer_weight_path": str(codeformer_weight),
                    "facelib_model_root": str(facelib_root),
                }
            }
        }
    )
    completed = SimpleNamespace(returncode=0, stdout="", stderr="")

    def _fake_run(cmd, cwd, capture_output, text, check):
        assert cmd[2] == "src.video.svd_postprocess_worker"
        output_dir = tmp_path / "face_restore_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 32), "red").save(output_dir / "frame_001.png")
        Image.new("RGB", (32, 32), "blue").save(output_dir / "frame_002.png")
        return completed

    load_mock = Mock(
        side_effect=[
            [Image.new("RGB", (32, 32), "red"), Image.new("RGB", (32, 32), "blue")],
        ]
    )
    monkeypatch.setattr("src.video.svd_postprocess.subprocess.run", _fake_run)
    monkeypatch.setattr(SVDPostprocessRunner, "_load_frame_sequence", staticmethod(load_mock))

    processed, metadata = SVDPostprocessRunner().process_frames(
        frames=frames,
        config=config,
        work_dir=tmp_path,
    )

    assert [frame.getpixel((0, 0)) for frame in processed] == [(255, 0, 0), (0, 0, 255)]
    assert metadata is not None
    assert metadata["applied"] == ["face_restore"]

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.utils.managed_process import ProcessOutcome
from src.video.restoration.runtime import GFPGAN_UNSUPPORTED_ISSUE, WORKER_WARNING_PREFIX
from src.video.svd_config import SVDConfig
from src.video.svd_errors import SVDPostprocessError
from src.video.svd_postprocess import (
    SVDPostprocessRunner,
    get_codeformer_runtime_issues,
    get_effective_svd_export_fps,
    get_gfpgan_runtime_issues,
    resolve_rife_executable,
    validate_svd_postprocess_config,
)


def _as_bounded(fake):
    """Adapt a ``subprocess.run``-style fake to the ``run_bounded`` seam the runner now uses."""

    def _run_bounded(command, *, cwd=None, **_kwargs):
        done = fake(list(command), None if cwd is None else str(cwd), True, True, False)
        return ProcessOutcome(
            returncode=done.returncode,
            stdout=str(done.stdout).encode("utf-8"),
            stderr=str(done.stderr).encode("utf-8"),
        )

    return _run_bounded


@pytest.fixture(autouse=True)
def _restoration_packages_available(monkeypatch):
    """Orchestration tests assume the optional stack exists; readiness has its own tests."""

    monkeypatch.setattr("src.video.restoration.runtime._module_available", lambda _name: True)


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


def test_validate_svd_postprocess_rejects_unsupported_rife_multiplier_before_runtime_lookup() -> (
    None
):
    config = SVDConfig.from_dict(
        {"postprocess": {"interpolation": {"enabled": True, "multiplier": 3}}}
    )

    valid, reason = validate_svd_postprocess_config(config)

    assert valid is False
    assert reason is not None
    assert "only 2x or 4x" in reason


@pytest.mark.parametrize(
    ("metadata", "multiplier", "expected_fps"),
    [
        (None, 2, 7),
        ({"applied": ["interpolation"], "interpolation": {"output_fps": 14}}, 2, 14),
        ({"applied": ["interpolation"], "interpolation": {"output_fps": 28}}, 4, 28),
    ],
)
def test_effective_svd_export_fps_uses_applied_interpolation_output(
    metadata: dict[str, object] | None, multiplier: int, expected_fps: int
) -> None:
    assert (
        get_effective_svd_export_fps(
            base_fps=7,
            postprocess_metadata=metadata,
            interpolation_multiplier=multiplier,
        )
        == expected_fps
    )


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


def test_get_gfpgan_runtime_issues_reports_unsupported_runtime() -> None:
    issues = get_gfpgan_runtime_issues(SVDConfig().postprocess)

    assert GFPGAN_UNSUPPORTED_ISSUE in issues


def test_validate_svd_postprocess_rejects_gfpgan_before_any_generation(tmp_path: Path) -> None:
    gfpgan_weight = tmp_path / "GFPGANv1.4.pth"
    facelib_root = tmp_path / "GFPGAN"
    gfpgan_weight.write_bytes(b"weights")
    facelib_root.mkdir()
    (facelib_root / "detection_Resnet50_Final.pth").write_bytes(b"det")
    (facelib_root / "parsing_parsenet.pth").write_bytes(b"parse")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "face_restore": {
                    "enabled": True,
                    "method": "GFPGAN",
                    "gfpgan_weight_path": str(gfpgan_weight),
                    "facelib_model_root": str(facelib_root),
                }
            }
        }
    )

    valid, reason = validate_svd_postprocess_config(config)

    assert valid is False
    assert reason is not None
    assert "GFPGAN is enabled" in reason and GFPGAN_UNSUPPORTED_ISSUE in reason


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


def test_postprocess_runner_face_restore_stage_returns_worker_outputs(
    tmp_path: Path, monkeypatch
) -> None:
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
    monkeypatch.setattr("src.video.svd_postprocess.run_bounded", _as_bounded(_fake_run))
    monkeypatch.setattr(SVDPostprocessRunner, "_load_frame_sequence", staticmethod(load_mock))

    processed, metadata = SVDPostprocessRunner().process_frames(
        frames=frames,
        config=config,
        work_dir=tmp_path,
    )

    assert [frame.getpixel((0, 0)) for frame in processed] == [(255, 0, 0), (0, 0, 255)]
    assert metadata is not None
    assert metadata["applied"] == ["face_restore"]


def test_postprocess_runner_rejects_gfpgan_without_starting_a_worker(
    tmp_path: Path, monkeypatch
) -> None:
    frames = [Image.new("RGB", (32, 32), "white")]
    config = SVDConfig.from_dict(
        {"postprocess": {"face_restore": {"enabled": True, "method": "GFPGAN"}}}
    )
    started: list[object] = []
    monkeypatch.setattr("src.video.svd_postprocess.run_bounded", lambda *a, **k: started.append(a))

    with pytest.raises(SVDPostprocessError, match="GFPGAN"):
        SVDPostprocessRunner().process_frames(frames=frames, config=config, work_dir=tmp_path)

    assert started == []


def test_run_worker_stage_releases_input_frames_before_loading_output(
    tmp_path: Path, monkeypatch
) -> None:
    closed: list[str] = []

    class _TrackedFrame:
        def convert(self, _mode: str):
            return Image.new("RGB", (8, 8), "white")

        def close(self) -> None:
            closed.append("close")

    def _fake_save_video_frames(*, frames, output_dir, prefix):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return []

    monkeypatch.setattr("src.video.svd_postprocess.save_video_frames", _fake_save_video_frames)
    monkeypatch.setattr(
        "src.video.svd_postprocess.run_bounded",
        lambda *args, **kwargs: ProcessOutcome(returncode=0),
    )
    runner = SVDPostprocessRunner(repo_root=tmp_path)
    monkeypatch.setattr(
        runner,
        "_load_frame_sequence",
        lambda _path: [Image.new("RGB", (8, 8), "red")],
    )

    frames = [_TrackedFrame(), _TrackedFrame()]
    processed = runner._run_worker_stage(
        stage_name="face_restore",
        action="face_restore",
        frames=frames,
        payload={},
        work_dir=tmp_path,
    )

    assert len(processed) == 1
    assert closed == ["close", "close"]
    assert frames == []


def test_run_rife_stage_releases_input_frames_before_loading_output(
    tmp_path: Path, monkeypatch
) -> None:
    closed: list[str] = []

    class _TrackedFrame:
        def convert(self, _mode: str):
            return Image.new("RGB", (8, 8), "white")

        def close(self) -> None:
            closed.append("close")

    executable = tmp_path / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "executable_path": str(executable),
                    "multiplier": 2,
                }
            }
        }
    )

    def _fake_save_video_frames(*, frames, output_dir, prefix):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return []

    monkeypatch.setattr("src.video.svd_postprocess.save_video_frames", _fake_save_video_frames)
    monkeypatch.setattr(
        "src.video.svd_postprocess.run_bounded",
        lambda *args, **kwargs: ProcessOutcome(returncode=0),
    )
    runner = SVDPostprocessRunner(repo_root=tmp_path)
    monkeypatch.setattr(
        runner,
        "_load_frame_sequence",
        lambda _path: [Image.new("RGB", (8, 8), "blue") for _ in range(4)],
    )

    frames = [_TrackedFrame(), _TrackedFrame()]
    processed = runner._run_rife_stage(
        frames=frames,
        postprocess=config.postprocess,
        work_dir=tmp_path,
    )

    assert len(processed) == 4
    assert closed == ["close", "close"]
    assert frames == []


def test_run_rife_stage_falls_back_when_runtime_rejects_custom_framecount(
    tmp_path: Path, monkeypatch
) -> None:
    executable = tmp_path / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "executable_path": str(executable),
                    "multiplier": 2,
                }
            }
        }
    )
    command_log: list[list[str]] = []

    def _fake_save_video_frames(*, frames, output_dir, prefix):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return []

    def _fake_run(*, cmd, executable):
        command_log.append(list(cmd))
        if any(part == "-n" for part in cmd):
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="only rife-v4 model support custom numframe and timestep",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    load_mock = Mock(side_effect=[[Image.new("RGB", (8, 8), "blue") for _ in range(4)]])
    monkeypatch.setattr("src.video.svd_postprocess.save_video_frames", _fake_save_video_frames)
    monkeypatch.setattr(SVDPostprocessRunner, "_run_rife_command", staticmethod(_fake_run))
    runner = SVDPostprocessRunner(repo_root=tmp_path)
    monkeypatch.setattr(runner, "_load_frame_sequence", load_mock)

    frames = [Image.new("RGB", (8, 8), "white"), Image.new("RGB", (8, 8), "black")]
    processed = runner._run_rife_stage(
        frames=frames,
        postprocess=config.postprocess,
        work_dir=tmp_path,
    )

    assert len(processed) == 4
    assert ["-n", "4"] in [
        cmd[index : index + 2] for cmd in command_log for index in range(len(cmd) - 1)
    ]
    assert len([cmd for cmd in command_log if "-n" not in cmd]) == 1


def test_run_rife_stage_compatibility_mode_repeats_default_double_passes_for_4x(
    tmp_path: Path, monkeypatch
) -> None:
    executable = tmp_path / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "executable_path": str(executable),
                    "multiplier": 4,
                }
            }
        }
    )

    def _fake_save_video_frames(*, frames, output_dir, prefix):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return []

    command_log: list[list[str]] = []

    def _fake_run(*, cmd, executable):
        command_log.append(list(cmd))
        if "-n" in cmd:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="only rife-v4 model support custom numframe and timestep",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.video.svd_postprocess.save_video_frames", _fake_save_video_frames)
    monkeypatch.setattr(SVDPostprocessRunner, "_run_rife_command", staticmethod(_fake_run))
    runner = SVDPostprocessRunner(repo_root=tmp_path)
    monkeypatch.setattr(
        runner,
        "_load_frame_sequence",
        Mock(
            side_effect=[
                [Image.new("RGB", (8, 8), "white") for _ in range(28)],
                [Image.new("RGB", (8, 8), "black") for _ in range(56)],
            ]
        ),
    )

    processed = runner._run_rife_stage(
        frames=[Image.new("RGB", (8, 8), "white") for _ in range(14)],
        postprocess=config.postprocess,
        work_dir=tmp_path,
    )

    assert len(processed) == 56
    assert ["-n", "56"] in [
        cmd[index : index + 2] for cmd in command_log for index in range(len(cmd) - 1)
    ]
    assert len([cmd for cmd in command_log if "-n" not in cmd]) == 2


@pytest.mark.parametrize(("multiplier", "expected_count"), [(2, 28), (4, 56)])
def test_run_rife_stage_requests_duration_preserving_frame_count(
    tmp_path: Path, monkeypatch, multiplier: int, expected_count: int
) -> None:
    executable = tmp_path / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "executable_path": str(executable),
                    "multiplier": multiplier,
                }
            }
        }
    )
    command_log: list[list[str]] = []
    monkeypatch.setattr("src.video.svd_postprocess.save_video_frames", lambda **_kwargs: [])
    monkeypatch.setattr(
        SVDPostprocessRunner,
        "_run_rife_command",
        staticmethod(
            lambda *, cmd, executable: command_log.append(list(cmd))
            or SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )
    runner = SVDPostprocessRunner(repo_root=tmp_path)
    monkeypatch.setattr(
        runner,
        "_load_frame_sequence",
        lambda _path: [Image.new("RGB", (8, 8), "white") for _ in range(expected_count)],
    )

    processed = runner._run_rife_stage(
        frames=[Image.new("RGB", (8, 8), "black") for _ in range(14)],
        postprocess=config.postprocess,
        work_dir=tmp_path,
    )

    assert len(processed) == expected_count
    assert ["-n", str(expected_count)] in [
        cmd[index : index + 2] for cmd in command_log for index in range(len(cmd) - 1)
    ]


def test_process_frames_logs_stage_summary(tmp_path: Path, monkeypatch, caplog) -> None:
    frames = [Image.new("RGB", (16, 16), "white"), Image.new("RGB", (16, 16), "black")]
    executable = tmp_path / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "executable_path": str(executable),
                    "multiplier": 2,
                }
            }
        }
    )
    monkeypatch.setattr(
        SVDPostprocessRunner,
        "_run_rife_stage",
        lambda self, **_kwargs: [Image.new("RGB", (16, 16), "blue") for _ in range(4)],
    )

    caplog.set_level(logging.INFO)
    processed, metadata = SVDPostprocessRunner(repo_root=tmp_path).process_frames(
        frames=frames,
        config=config,
        work_dir=tmp_path,
    )

    assert len(processed) == 4
    assert metadata is not None
    assert metadata["interpolation"] == {
        "enabled": True,
        "method": "rife",
        "multiplier": 2,
        "executable_path": str(executable),
        "model_dir": None,
        "semantics": "duration_preserving_temporal_smoothing",
        "input_frame_count": 2,
        "input_fps": 7,
        "output_frame_count": 4,
        "output_fps": 14,
        "model": None,
        "commands": [],
    }
    assert "[SVD][postprocess] start input_frames=2" in caplog.text
    assert (
        "[SVD][postprocess] complete output_frames=4 applied=['interpolation'] size=16x16"
        in caplog.text
    )


def test_process_frames_emits_stage_status_updates(tmp_path: Path, monkeypatch) -> None:
    frames = [Image.new("RGB", (16, 16), "white"), Image.new("RGB", (16, 16), "black")]
    executable = tmp_path / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "executable_path": str(executable),
                    "multiplier": 2,
                }
            }
        }
    )
    monkeypatch.setattr(
        SVDPostprocessRunner,
        "_run_rife_stage",
        lambda self, **_kwargs: [Image.new("RGB", (16, 16), "blue") for _ in range(4)],
    )

    updates: list[dict[str, object]] = []
    SVDPostprocessRunner(repo_root=tmp_path, status_callback=updates.append).process_frames(
        frames=frames,
        config=config,
        work_dir=tmp_path,
    )

    assert updates == [
        {
            "stage_detail": "postprocess: interpolation",
            "progress": 0.0,
            "current_step": 0,
            "total_steps": 1,
            "eta_seconds": None,
        },
        {
            "stage_detail": "postprocess: interpolation",
            "progress": 1.0,
            "current_step": 1,
            "total_steps": 1,
            "eta_seconds": None,
        },
    ]


def _face_restore_config(tmp_path: Path) -> SVDConfig:
    codeformer_weight = tmp_path / "codeformer.pth"
    facelib_root = tmp_path / "GFPGAN"
    codeformer_weight.write_bytes(b"weights")
    facelib_root.mkdir()
    (facelib_root / "detection_Resnet50_Final.pth").write_bytes(b"det")
    (facelib_root / "parsing_parsenet.pth").write_bytes(b"parse")
    return SVDConfig.from_dict(
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


def _run_face_restore_with_worker_stderr(tmp_path: Path, monkeypatch, stderr: str):
    def _fake_run(cmd, cwd, capture_output, text, check):
        output_dir = tmp_path / "face_restore_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 32), "red").save(output_dir / "frame_001.png")
        return SimpleNamespace(returncode=0, stdout="", stderr=stderr)

    monkeypatch.setattr("src.video.svd_postprocess.run_bounded", _as_bounded(_fake_run))
    monkeypatch.setattr(
        SVDPostprocessRunner,
        "_load_frame_sequence",
        staticmethod(Mock(return_value=[Image.new("RGB", (32, 32), "red")])),
    )
    return SVDPostprocessRunner().process_frames(
        frames=[Image.new("RGB", (32, 32), "white")],
        config=_face_restore_config(tmp_path),
        work_dir=tmp_path,
    )


def test_successful_worker_warnings_are_logged_and_recorded_in_stage_metadata(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    stderr = (
        "FutureWarning: torch.jit.script is deprecated\n"
        f"{WORKER_WARNING_PREFIX}CodeFormer inference failed for one face; left unrestored: boom\n"
    )

    with caplog.at_level(logging.WARNING, logger="src.video.svd_postprocess"):
        _frames, metadata = _run_face_restore_with_worker_stderr(tmp_path, monkeypatch, stderr)

    assert metadata is not None and metadata["applied"] == ["face_restore"]
    assert metadata["warnings"] == [
        {
            "stage": "face_restore",
            "message": "CodeFormer inference failed for one face; left unrestored: boom",
        }
    ]
    assert "left unrestored: boom" in caplog.text
    assert "torch.jit" not in caplog.text  # unrelated library noise stays out of the record


def test_clean_worker_run_adds_no_warnings_key(tmp_path: Path, monkeypatch) -> None:
    _frames, metadata = _run_face_restore_with_worker_stderr(
        tmp_path, monkeypatch, "FutureWarning: noise only\n"
    )

    assert metadata is not None and "warnings" not in metadata


def test_worker_stage_timeout_surfaces_as_a_postprocess_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.video.svd_postprocess.run_bounded",
        lambda *a, **k: ProcessOutcome(returncode=None, timed_out=True),
    )
    runner = SVDPostprocessRunner(repo_root=tmp_path)
    with pytest.raises(SVDPostprocessError, match="timed out"):
        runner._run_child(["x"], cwd=tmp_path, timeout_seconds=5, what="face_restore worker")


def test_worker_stage_cancellation_raises_cancellation_error(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _fake(command, **kwargs):
        seen.update(kwargs)
        return ProcessOutcome(returncode=None, cancelled=True)

    monkeypatch.setattr("src.video.svd_postprocess.run_bounded", _fake)
    token = CancelToken()
    runner = SVDPostprocessRunner(repo_root=tmp_path, cancel_token=token)
    with pytest.raises(CancellationError):
        runner._run_child(["x"], cwd=tmp_path, timeout_seconds=5, what="upscale worker")
    assert seen["cancel"] == token.is_cancelled


def test_worker_stage_reports_unlaunchable_and_oversized_children(
    tmp_path: Path, monkeypatch
) -> None:
    runner = SVDPostprocessRunner(repo_root=tmp_path)
    monkeypatch.setattr(
        "src.video.svd_postprocess.run_bounded",
        lambda *a, **k: ProcessOutcome(returncode=None, launch_error="no such file"),
    )
    with pytest.raises(SVDPostprocessError, match="could not start"):
        runner._run_child(["x"], cwd=tmp_path, timeout_seconds=5, what="RIFE interpolation")
    monkeypatch.setattr(
        "src.video.svd_postprocess.run_bounded",
        lambda *a, **k: ProcessOutcome(returncode=0, output_truncated=True),
    )
    with pytest.raises(SVDPostprocessError, match="stdout"):
        runner._run_child(["x"], cwd=tmp_path, timeout_seconds=5, what="RIFE interpolation")


def test_a_hung_worker_is_stopped_by_the_real_bounded_runner(tmp_path: Path) -> None:
    import sys

    runner = SVDPostprocessRunner(repo_root=tmp_path)
    with pytest.raises(SVDPostprocessError, match="timed out"):
        runner._run_child(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            timeout_seconds=0.5,
            what="face_restore worker",
        )


def test_rife_command_runs_under_the_rife_timeout(tmp_path: Path, monkeypatch) -> None:
    from src.video import svd_postprocess

    seen: dict[str, object] = {}

    def _fake(command, **kwargs):
        seen.update(kwargs)
        return ProcessOutcome(returncode=0, stdout=b"ok")

    monkeypatch.setattr("src.video.svd_postprocess.run_bounded", _fake)
    exe = tmp_path / "rife.exe"
    done = SVDPostprocessRunner(repo_root=tmp_path)._run_rife_command(
        cmd=[str(exe)], executable=exe
    )
    assert done.returncode == 0 and done.stdout == "ok"
    assert seen["timeout_seconds"] == svd_postprocess.RIFE_TIMEOUT_SECONDS
    assert seen["cwd"] == tmp_path

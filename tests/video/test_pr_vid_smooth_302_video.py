"""PR-VID-SMOOTH-302: RIFE smoothing of a finished clip, backend-neutral, wired into the Comfy backend.

A Comfy clip arrives as an encoded file. It is decoded, run through the same RIFE stage SVD uses, and re-encoded
by StableNew's one encoder; Comfy's own file stays on disk. A bad request fails before the runtime starts.
No GPU, no real RIFE; FFmpeg tests skip when FFmpeg is not installed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.pipeline.video import resolve_ffmpeg_executable
from src.video import ComfyWorkflowVideoBackend, VideoExecutionRequest
from src.video.svd_postprocess import SVDPostprocessRunner
from src.video.video_export import export_video_mp4
from src.video.video_interpolation import (
    VideoInterpolationRequest,
    VideoInterpolationResult,
    _decode_frames,
    interpolate_video_file,
    normalize_interpolation_request,
)
from tests.helpers.video_contract_registry import build_synthetic_contract_registry

needs_ffmpeg = pytest.mark.skipif(
    resolve_ffmpeg_executable() is None, reason="FFmpeg is not installed"
)


@pytest.fixture(autouse=True)
def _no_ambient_rife(monkeypatch):
    monkeypatch.delenv("STABLENEW_RIFE_EXE", raising=False)
    monkeypatch.setenv("PATH", "")


def _rife(root: Path, *, model: str | None = "rife-v4.6") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    executable = root / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    if model:
        folder = root / model
        folder.mkdir()
        (folder / "flownet.param").write_bytes(b"p")
        (folder / "flownet.bin").write_bytes(b"b")
    return executable


# ---------------------------------------------------------------------------
# the request block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block", [None, {}, {"enabled": False, "multiplier": 3}, "yes", 3])
def test_an_absent_or_disabled_block_is_inert(block) -> None:
    assert normalize_interpolation_request(block) is None


def test_an_enabled_block_is_validated_before_anything_runs(tmp_path: Path) -> None:
    executable = _rife(tmp_path)

    request = normalize_interpolation_request(
        {"enabled": True, "multiplier": "2", "executable_path": str(executable)}
    )
    assert request == VideoInterpolationRequest(multiplier=2, executable_path=str(executable))
    assert normalize_interpolation_request(
        {"enabled": True, "executable_path": str(executable)}
    ) == VideoInterpolationRequest(multiplier=None, executable_path=str(executable))

    with pytest.raises(ValueError, match="unsupported"):
        normalize_interpolation_request(
            {"enabled": True, "multiplier": 3, "executable_path": str(executable)}
        )
    with pytest.raises(ValueError, match="not a number"):
        normalize_interpolation_request(
            {"enabled": True, "multiplier": "x", "executable_path": str(executable)}
        )
    with pytest.raises(ValueError, match="no rife-ncnn-vulkan executable"):
        normalize_interpolation_request({"enabled": True, "executable_path": "missing.exe"})


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------


def _fake_rife_child(commands: list[list[str]]):
    def _fake(self, cmd, *, cwd, timeout_seconds, what):
        commands.append(list(cmd))
        output_dir = Path(cmd[cmd.index("-o") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        for index in range(int(cmd[cmd.index("-n") + 1])):
            Image.new("RGB", (16, 16), "white").save(output_dir / f"{index:08d}.png")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return _fake


def _tiny_clip(path: Path, frames: int = 4, fps: int = 8) -> Path:
    images = [Image.new("RGB", (16, 16), (index * 40, 0, 0)) for index in range(frames)]
    export_video_mp4(frames=images, output_path=path, fps=fps)
    return path


@needs_ffmpeg
def test_a_clip_is_decoded_smoothed_and_re_encoded_without_touching_the_source(
    tmp_path: Path, monkeypatch
) -> None:
    executable = _rife(tmp_path / "rife")
    source = _tiny_clip(tmp_path / "out" / "clip.mp4", frames=4, fps=8)
    before = source.read_bytes()
    commands: list[list[str]] = []
    monkeypatch.setattr(SVDPostprocessRunner, "_run_child", _fake_rife_child(commands))

    result = interpolate_video_file(
        video_path=source,
        output_dir=tmp_path / "out",
        source_fps=8,
        request=VideoInterpolationRequest(multiplier=2, executable_path=str(executable)),
    )

    assert source.read_bytes() == before
    assert Path(result.video_path) == tmp_path / "out" / "clip_smooth.mp4"
    assert Path(result.video_path).is_file()
    assert (result.input_frame_count, result.output_frame_count) == (4, 8)
    assert (result.input_fps, result.output_fps, result.multiplier) == (8, 16, 2)
    assert result.model == "rife-v4.6"
    assert "-m" in commands[0] and commands[0][commands[0].index("-n") + 1] == "8"
    assert result.commands == commands
    assert (
        len(
            _decode_frames(
                video_path=Path(result.video_path), work_dir=tmp_path / "check", cancel_token=None
            )
        )
        == 8
    )
    assert not (tmp_path / "out" / "clip_smooth_work").exists()


@needs_ffmpeg
def test_the_default_factor_follows_the_source_rate(tmp_path: Path, monkeypatch) -> None:
    executable = _rife(tmp_path / "rife")
    source = _tiny_clip(tmp_path / "clip.mp4", frames=3, fps=8)
    commands: list[list[str]] = []
    monkeypatch.setattr(SVDPostprocessRunner, "_run_child", _fake_rife_child(commands))

    result = interpolate_video_file(
        video_path=source,
        output_dir=tmp_path,
        source_fps=8,
        request=VideoInterpolationRequest(executable_path=str(executable)),
    )

    assert result.multiplier == 4  # 8 fps is below 14
    assert result.output_fps == 32


@needs_ffmpeg
def test_a_decode_failure_is_a_readable_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")

    with pytest.raises(Exception, match="decode"):
        _decode_frames(video_path=broken, work_dir=tmp_path / "work", cancel_token=None)


# ---------------------------------------------------------------------------
# the Comfy backend
# ---------------------------------------------------------------------------


def _comfy_run(tmp_path: Path, monkeypatch, *, interpolation, fake_smooth=None):
    start = tmp_path / "start.png"
    end = tmp_path / "end.png"
    video = tmp_path / "clip.mp4"
    preview = tmp_path / "preview.png"
    for path, payload in ((start, b"png"), (end, b"png"), (video, b"mp4"), (preview, b"png")):
        path.write_bytes(payload)
    client = Mock()
    client.get_object_info.return_value = {
        "SyntheticAnchorBridge": {"input": {}},
        "models": {"checkpoints": ["synthetic_video.safetensors"]},
    }
    client.queue_prompt.return_value = {"prompt_id": "prompt-123"}
    client.get_history.return_value = {
        "prompt-123": {
            "outputs": {
                "4": {
                    "videos": [{"filename": str(video)}],
                    "images": [{"filename": str(preview)}],
                }
            },
            "status": {"completed": True},
        }
    }
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.wait_for_comfy_ready", lambda *_a, **_k: True
    )
    if fake_smooth is not None:
        monkeypatch.setattr("src.video.comfy_workflow_backend.interpolate_video_file", fake_smooth)
    backend = ComfyWorkflowVideoBackend(
        client=client,
        process_manager=SimpleNamespace(
            ensure_running=lambda: True,
            _config=SimpleNamespace(base_url="http://127.0.0.1:8188"),
        ),
        transition=SimpleNamespace(prepare_for=lambda _target: SimpleNamespace(ready=True)),
        workflow_registry=build_synthetic_contract_registry(),
        history_poll_interval=0.01,
        history_timeout=1.0,
    )
    stage_config = {"enabled": True, "workflow_id": "synthetic_anchor_video_v1", "fps": 8}
    if interpolation is not None:
        stage_config["interpolation"] = interpolation

    def _execute():
        return backend.execute(
            Mock(),
            VideoExecutionRequest(
                backend_id="comfy",
                stage_name="video_workflow",
                stage_config=stage_config,
                output_dir=tmp_path,
                input_image_path=start,
                end_anchor_path=end,
                image_name="clip",
                prompt="animate this",
                negative_prompt="",
                job_id="job-123",
            ),
        )

    return client, video, _execute


def test_the_backend_promotes_the_smoothed_clip_and_keeps_comfys_file(
    tmp_path: Path, monkeypatch
) -> None:
    executable = _rife(tmp_path / "rife")
    smooth = tmp_path / "clip_smooth.mp4"
    smooth.write_bytes(b"smooth")
    seen: dict[str, object] = {}

    def _fake_smooth(**kwargs):
        seen.update(kwargs)
        return VideoInterpolationResult(
            source_video_path=str(kwargs["video_path"]),
            video_path=str(smooth),
            input_frame_count=4,
            output_frame_count=8,
            input_fps=int(kwargs["source_fps"]),
            output_fps=16,
            multiplier=2,
            model="rife-v4.6",
            commands=[["rife", "-m", "rife-v4.6"]],
        )

    _client, video, execute = _comfy_run(
        tmp_path,
        monkeypatch,
        interpolation={"enabled": True, "multiplier": 2, "executable_path": str(executable)},
        fake_smooth=_fake_smooth,
    )

    result = execute()

    assert result is not None
    assert seen["source_fps"] == 8
    assert seen["request"] == VideoInterpolationRequest(
        multiplier=2, executable_path=str(executable)
    )
    assert result.primary_path == str(smooth)
    payload = result.to_variant_payload()
    assert payload["artifact"]["primary_path"] == str(smooth)
    assert payload["artifact"]["output_paths"][:2] == [str(smooth), str(video)]
    assert payload["video_paths"][0] == str(smooth)
    assert payload["interpolation"]["output_fps"] == 16
    assert payload["interpolation"]["model"] == "rife-v4.6"
    manifest = Path(result.manifest_path).read_text(encoding="utf-8")
    assert '"interpolation"' in manifest and "clip_smooth.mp4" in manifest


def test_without_the_block_the_backend_is_unchanged(tmp_path: Path, monkeypatch) -> None:
    def _must_not_run(**_kwargs):
        raise AssertionError("interpolation must not run")

    _client, video, execute = _comfy_run(
        tmp_path, monkeypatch, interpolation=None, fake_smooth=_must_not_run
    )

    result = execute()

    assert result is not None and result.primary_path == str(video)
    assert "interpolation" not in result.to_variant_payload()


@pytest.mark.parametrize(
    ("interpolation", "message"),
    [
        ({"enabled": True, "multiplier": 3, "executable_path": "present"}, "unsupported"),
        ({"enabled": True, "executable_path": "missing.exe"}, "no rife-ncnn-vulkan executable"),
    ],
)
def test_a_bad_request_fails_before_the_runtime_is_asked_to_generate(
    tmp_path: Path, monkeypatch, interpolation, message
) -> None:
    if interpolation.get("executable_path") == "present":
        interpolation = {**interpolation, "executable_path": str(_rife(tmp_path / "rife"))}
    client, _video, execute = _comfy_run(tmp_path, monkeypatch, interpolation=interpolation)

    with pytest.raises(ValueError, match=message):
        execute()

    client.queue_prompt.assert_not_called()

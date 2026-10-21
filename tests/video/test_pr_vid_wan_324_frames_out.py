"""PR-VID-WAN-324: a Comfy workflow can end in PNG frames and StableNew encodes the clip.

``SaveVideo`` writes whatever codec and bitrate Comfy picks and leaves StableNew with no frames. A frames-out
workflow ends in ``SaveImage``; the backend encodes the downloaded frames with the one StableNew encoder, records
every frame's SHA-256 (so the exact last frame is a verifiable artifact) and lets RIFE read the original PNGs.
Fake Comfy client, no GPU; FFmpeg tests skip when FFmpeg is not installed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.pipeline.video import resolve_ffmpeg_executable
from src.video import ComfyWorkflowVideoBackend, VideoExecutionRequest
from src.video.frames_out import (
    encode_frames_out,
    frames_output_fps,
    natural_frame_order,
)
from src.video.svd_postprocess import SVDPostprocessRunner
from src.video.video_backend_types import (
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
)
from src.video.video_interpolation import (
    VideoInterpolationRequest,
    VideoInterpolationResult,
    _decode_frames,
    interpolate_frame_files,
)
from src.video.workflow_catalog import (
    WAN22_FRAMES_STOCK_NODES,
    WAN22_FRAMES_VERSION,
    WAN22_STOCK_NODES,
    _build_wan22_ti2v_5b_i2v_v1_2,
    _build_wan22_ti2v_5b_i2v_v1_3,
)
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry
from tests.video.test_pr_vid_smooth_302_video import _fake_rife_child, _rife
from tests.video.test_wan22_experimental_workflow import (
    WAN_ID,
    _backend,
    _FakeComfy,
    _object_info,
)

needs_ffmpeg = pytest.mark.skipif(
    resolve_ffmpeg_executable() is None, reason="FFmpeg is not installed"
)


@pytest.fixture(autouse=True)
def _no_ambient_rife(monkeypatch):
    monkeypatch.delenv("STABLENEW_RIFE_EXE", raising=False)
    monkeypatch.setenv("PATH", "")


def _png(path: Path, shade: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (shade, 0, 0)).save(path)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# the catalog version
# ---------------------------------------------------------------------------


def test_the_frames_out_version_changes_only_the_output_end_of_the_approved_graph() -> None:
    approved = _build_wan22_ti2v_5b_i2v_v1_2()
    frames = _build_wan22_ti2v_5b_i2v_v1_3()
    old_graph = approved.backend_defaults["prompt_template"]
    new_graph = frames.backend_defaults["prompt_template"]

    assert frames.workflow_id == approved.workflow_id == WAN_ID
    assert frames.workflow_version == WAN22_FRAMES_VERSION == "1.3.0"
    assert {node: old_graph[node] for node in map(str, range(1, 11))} == {
        node: new_graph[node] for node in map(str, range(1, 11))
    }
    assert new_graph["11"]["class_type"] == "SaveImage"
    assert new_graph["11"]["inputs"]["images"] == ["10", 0]
    assert new_graph["11"]["inputs"]["filename_prefix"] == "stablenew/wan22_{{request.job_id}}"
    assert set(new_graph) == set(map(str, range(1, 12)))
    assert not {"CreateVideo", "SaveVideo"} & {node["class_type"] for node in new_graph.values()}
    assert (
        frames.backend_defaults["provenance"]["files"]
        == approved.backend_defaults["provenance"]["files"]
    )
    assert (
        frames.backend_defaults["frame_count_policy"]
        == approved.backend_defaults["frame_count_policy"]
    )
    assert frames.backend_defaults["output_policy"] == {"mode": "frames", "fps": 24}
    nodes = {d.locator for d in frames.dependency_specs if d.dependency_kind == "stock_node"}
    assert nodes == set(WAN22_FRAMES_STOCK_NODES)
    assert "SaveImage" in nodes and not {"CreateVideo", "SaveVideo"} & nodes
    assert set(WAN22_STOCK_NODES) - nodes == {"CreateVideo", "SaveVideo"}
    assert frames.pinned_revision == "catalog:wan22_ti2v_5b_i2v_v1@1.3.0"


def test_the_published_versions_keep_a_video_file_output() -> None:
    registry = build_default_workflow_registry()
    for version in ("1.0.0", "1.1.0", "1.2.0"):
        spec = registry.get(WAN_ID, version, allow_experimental=True)
        assert frames_output_fps(spec) is None
        assert "output_policy" not in spec.backend_defaults
        assert spec.backend_defaults["prompt_template"]["12"]["class_type"] == "SaveVideo"


def test_the_frames_out_version_waits_for_requalification_before_it_is_offered() -> None:
    assert WAN22_FRAMES_VERSION not in build_default_workflow_registry().list_versions(WAN_ID)
    assert _build_wan22_ti2v_5b_i2v_v1_3().is_experimental


def test_a_frames_policy_without_a_frame_rate_is_refused() -> None:
    spec = SimpleNamespace(workflow_id="x", backend_defaults={"output_policy": {"mode": "frames"}})
    with pytest.raises(ValueError, match="without a frame rate"):
        frames_output_fps(spec)


# ---------------------------------------------------------------------------
# the encoder
# ---------------------------------------------------------------------------


def test_frames_play_in_numeric_order_not_text_order() -> None:
    names = ["f_10_.png", "f_2_.png", "f_1_.png", "f_100_.png", "f_9_.png"]
    assert [path.name for path in natural_frame_order(names)] == [
        "f_1_.png",
        "f_2_.png",
        "f_9_.png",
        "f_10_.png",
        "f_100_.png",
    ]


def test_the_record_names_the_frames_the_clip_was_encoded_from(tmp_path: Path, monkeypatch) -> None:
    frames = [_png(tmp_path / f"w_{n:05d}_.png", n * 30) for n in (3, 1, 2)]
    calls: dict[str, Any] = {}

    def _export(**kwargs):
        calls.update(kwargs)
        Path(kwargs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["output_path"]).write_bytes(b"mp4")
        return Path(kwargs["output_path"])

    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _export)

    record = encode_frames_out(
        frame_paths=frames,
        output_dir=tmp_path / "run",
        stem="clip",
        fps=24,
        expected_frame_count=49,
    )

    assert [path.name for path in calls["image_paths"]] == [
        "w_00001_.png",
        "w_00002_.png",
        "w_00003_.png",
    ]
    assert calls["fps"] == 24
    assert (calls["settings"].crf, calls["settings"].preset) == (16, "slow")
    assert record.video_path == str(tmp_path / "run" / "clip.mp4")
    assert (record.frame_count, record.expected_frame_count) == (3, 49)
    assert record.first_frame_path.endswith("w_00001_.png")
    assert record.last_frame_path.endswith("w_00003_.png")
    assert record.last_frame_sha256 == _sha(tmp_path / "w_00003_.png")
    assert record.frame_sha256 == [_sha(tmp_path / f"w_{n:05d}_.png") for n in (1, 2, 3)]
    assert record.frame_paths == [str(tmp_path / f"w_{n:05d}_.png") for n in (1, 2, 3)]
    assert calls["require_all_frames"] is True
    assert record.reconciliation["status"] == "missing"
    assert record.reconciliation["difference"] == -46
    summary = record.summary()
    assert "frame_sha256" not in summary and "frame_paths" not in summary
    assert summary["reconciliation"]["status"] == "missing"
    assert (
        summary["frame_sha256_digest"]
        == hashlib.sha256(",".join(record.frame_sha256).encode("ascii")).hexdigest()
    )
    assert record.to_dict()["encoder"] == {"crf": 16, "preset": "slow", "pix_fmt": "yuv420p"}


def test_no_frames_is_an_error_not_an_empty_clip(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="without saving any frames"):
        encode_frames_out(frame_paths=[], output_dir=tmp_path, stem="clip", fps=24)


@needs_ffmpeg
def test_the_real_encoder_makes_a_clip_with_every_frame(tmp_path: Path) -> None:
    frames = [_png(tmp_path / f"w_{n:05d}_.png", n * 40) for n in range(1, 6)]

    record = encode_frames_out(frame_paths=frames, output_dir=tmp_path / "run", stem="clip", fps=24)

    assert Path(record.video_path).is_file()
    decoded = _decode_frames(
        video_path=Path(record.video_path), work_dir=tmp_path / "check", cancel_token=None
    )
    assert len(decoded) == 5


@needs_ffmpeg
def test_smoothing_reads_the_original_frames_not_a_decoded_clip(
    tmp_path: Path, monkeypatch
) -> None:
    executable = _rife(tmp_path / "rife")
    frames = [_png(tmp_path / "out" / f"w_{n:05d}_.png", n * 40) for n in range(1, 5)]
    commands: list[list[str]] = []
    monkeypatch.setattr(SVDPostprocessRunner, "_run_child", _fake_rife_child(commands))

    result = interpolate_frame_files(
        frame_paths=frames,
        output_dir=tmp_path / "out",
        stem="clip",
        source_fps=24,
        request=VideoInterpolationRequest(multiplier=2, executable_path=str(executable)),
    )

    assert Path(result.video_path) == tmp_path / "out" / "clip_smooth.mp4"
    assert (result.input_frame_count, result.output_frame_count) == (4, 8)
    assert (result.input_fps, result.output_fps, result.multiplier) == (24, 48, 2)
    assert not (tmp_path / "out" / "clip_smooth_work").exists()
    with pytest.raises(Exception, match="No frames"):
        interpolate_frame_files(
            frame_paths=[],
            output_dir=tmp_path,
            stem="x",
            source_fps=24,
            request=VideoInterpolationRequest(executable_path=str(executable)),
        )


# ---------------------------------------------------------------------------
# the backend
# ---------------------------------------------------------------------------


class _FramesComfy(_FakeComfy):
    """Fake Comfy whose workflow saves numbered PNG frames from node 11 (SaveImage)."""

    def __init__(self, tmp: Path, *, frames: int = 3) -> None:
        super().__init__(tmp, info=_object_info())
        self.frame_names = [f"wan22_job_{n:05d}_.png" for n in range(1, frames + 1)]
        self.info["SaveImage"] = {"input": {"required": {}}}

    def get_history(self, prompt_id=None, **_kw):
        images = [
            {"filename": name, "subfolder": "stablenew", "type": "output"}
            for name in reversed(self.frame_names)
        ]
        return {
            prompt_id: {
                "outputs": {"11": {"images": images}},
                "status": {"status_str": "success", "completed": True},
            }
        }

    def download_view(self, filename, destination, *, subfolder="", file_type="output", **_kw):
        shade = (int(filename.split("_")[2]) * 50) % 256
        return _png(Path(destination), shade)


def _frames_backend(client: _FramesComfy) -> ComfyWorkflowVideoBackend:
    registry = WorkflowRegistry()
    registry.register(_build_wan22_ti2v_5b_i2v_v1_3())
    backend = _backend(client)
    backend._workflow_registry = registry
    return backend


def _frames_request(tmp: Path, **config: Any) -> VideoExecutionRequest:
    source = tmp / "source.png"
    source.write_bytes(b"png")
    return VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={
            "workflow_id": WAN_ID,
            "workflow_version": WAN22_FRAMES_VERSION,
            "seed": 7,
            "frame_count": 17,
            "source_preparation": {"target_dimensions": {"width": 480, "height": 832}},
            **config,
        },
        output_dir=tmp / "run",
        input_image_path=source,
        prompt="the person waves",
        negative_prompt="blurry",
        job_id="job-1",
        workflow_id=WAN_ID,
        workflow_version=WAN22_FRAMES_VERSION,
        requested_controls=(CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT),
        experimental_opt_in=True,
    )


def _fake_export(**kwargs):
    Path(kwargs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(kwargs["output_path"]).write_bytes(b"mp4")
    return Path(kwargs["output_path"])


def test_the_backend_encodes_the_saved_frames_and_records_them(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )
    client = _FramesComfy(tmp_path)

    result = _frames_backend(client).execute(None, _frames_request(tmp_path))

    assert result is not None
    run = tmp_path / "run"
    clip = run / f"{WAN_ID}_job-1.mp4"
    assert result.primary_path == str(clip) and clip.is_file()
    graph = client.queued[0]["prompt"]
    assert graph["11"]["class_type"] == "SaveImage"
    assert graph["11"]["inputs"]["filename_prefix"] == "stablenew/wan22_job-1"
    payload = result.to_variant_payload()
    assert payload["video_paths"] == [str(clip)]
    assert [Path(path).name for path in payload["frame_paths"]] == [
        "wan22_job_00001_.png",
        "wan22_job_00002_.png",
        "wan22_job_00003_.png",
    ]
    last = run / "wan22_job_00003_.png"
    assert payload["thumbnail_path"].endswith("wan22_job_00001_.png")
    assert payload["frames_out"]["last_frame_sha256"] == _sha(last)
    assert payload["frames_out"]["frame_count"] == 3
    assert payload["frames_out"]["expected_frame_count"] == 17  # recorded, not hidden
    # Reconciled and recorded; the job still succeeds (failing it is an owner decision before 1.3.0 registers).
    assert payload["frames_out"]["reconciliation"]["status"] == "missing"
    assert payload["frames_out"]["reconciliation"]["difference"] == -14
    assert "frame_sha256" not in payload["frames_out"]
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["video_path"] == str(clip)
    assert manifest["frames_out"]["frame_sha256"] == [
        _sha(run / f"wan22_job_{n:05d}_.png") for n in (1, 2, 3)
    ]
    assert manifest["frames_out"]["video_path"] == str(clip)
    assert manifest["frames_out"]["frame_paths"] == manifest["frame_paths"]
    assert manifest["frames_out"]["reconciliation"]["status"] == "missing"


def test_rife_reads_the_frames_when_smoothing_is_requested(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    executable = _rife(tmp_path / "rife")
    smooth = tmp_path / "run" / "smooth.mp4"
    seen: dict[str, Any] = {}

    def _fake_frames_smooth(**kwargs):
        seen.update(kwargs)
        smooth.parent.mkdir(parents=True, exist_ok=True)
        smooth.write_bytes(b"smooth")
        return VideoInterpolationResult(
            source_video_path="frames",
            video_path=str(smooth),
            input_frame_count=3,
            output_frame_count=6,
            input_fps=24,
            output_fps=48,
            multiplier=2,
            model="rife-v4.6",
        )

    def _must_not_decode(**_kwargs):
        raise AssertionError("a frames-out clip is smoothed from its frames, not decoded again")

    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.interpolate_frame_files", _fake_frames_smooth
    )
    monkeypatch.setattr("src.video.comfy_workflow_backend.interpolate_video_file", _must_not_decode)
    client = _FramesComfy(tmp_path)

    result = _frames_backend(client).execute(
        None,
        _frames_request(
            tmp_path,
            interpolation={"enabled": True, "multiplier": 2, "executable_path": str(executable)},
        ),
    )

    assert result is not None
    assert [Path(path).name for path in seen["frame_paths"]] == [
        "wan22_job_00001_.png",
        "wan22_job_00002_.png",
        "wan22_job_00003_.png",
    ]
    assert seen["stem"] == f"{WAN_ID}_job-1" and seen["source_fps"] == 24
    assert result.primary_path == str(smooth)
    payload = result.to_variant_payload()
    assert payload["video_paths"][:2] == [
        str(smooth),
        str(tmp_path / "run" / f"{WAN_ID}_job-1.mp4"),
    ]
    assert payload["interpolation"]["output_fps"] == 48
    assert payload["frames_out"]["frame_count"] == 3


def test_a_run_with_no_saved_frames_fails_loudly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    client = _FramesComfy(tmp_path, frames=0)

    with pytest.raises(RuntimeError, match="without discoverable output"):
        _frames_backend(client).execute(None, _frames_request(tmp_path))


def test_a_video_file_workflow_is_unchanged(tmp_path: Path, monkeypatch) -> None:
    """1.2.0 still returns Comfy's own clip: no frames are encoded and no frames_out record exists."""

    def _must_not_encode(**_kwargs):
        raise AssertionError("a SaveVideo workflow is not re-encoded")

    monkeypatch.setattr("src.video.comfy_workflow_backend.encode_frames_out", _must_not_encode)
    client = _FakeComfy(tmp_path)

    result = _backend(client).execute(
        None,
        VideoExecutionRequest(
            backend_id="comfy",
            stage_name="video_workflow",
            stage_config={
                "workflow_id": WAN_ID,
                "workflow_version": "1.2.0",
                "seed": 7,
                "frame_count": 49,
                "source_preparation": {"target_dimensions": {"width": 480, "height": 832}},
            },
            output_dir=tmp_path / "run",
            input_image_path=_png(tmp_path / "source.png", 1),
            prompt="the person waves",
            negative_prompt="blurry",
            job_id="job-1",
            workflow_id=WAN_ID,
            workflow_version="1.2.0",
            requested_controls=(
                CONTROL_SOURCE_IMAGE,
                CONTROL_PROMPT_TEXT,
                CONTROL_NEGATIVE_PROMPT,
            ),
        ),
    )

    assert result is not None
    assert result.primary_path.endswith(".mp4")
    assert "frames_out" not in result.to_variant_payload()

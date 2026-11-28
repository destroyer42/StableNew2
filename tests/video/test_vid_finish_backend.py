"""VID-FINISH in the Comfy backend: upscale, then smoothing, then trim/loop, inside the one video_workflow stage.

Fake ComfyUI, fake FFmpeg steps, no weights, no GPU. Only the final clip is primary; every earlier clip (the native one
first) is recorded as retained, which is what keeps it out of Review, the phone gateway and Immich.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.app.review_gateway_sources import RETAINED, SourceFilter
from src.video.clip_finishing import ClipFinishResult
from src.video.video_interpolation import VideoInterpolationResult
from tests.video.test_pr_vid_smooth_302_video import _rife
from tests.video.test_pr_vid_wan_324_frames_out import (
    WAN_ID,
    _fake_export,
    _frames_backend,
    _frames_request,
    _FramesComfy,
)
from tests.video.test_wan22_experimental_workflow import _driver_probe, _stats

BACKEND = "src.video.comfy_workflow_backend"
UPSCALE = {
    "pass_id": "seedvr2_3b_int8_upscale_2x",
    "pass_version": "1.0.0",
    "scale": 2,
    "seed": 7,
    "experimental_opt_in": True,
}
CONTAINER_ROLES: dict[str, str] = {}


class _UpscaleComfy(_FramesComfy):
    """The workflow's prompt, then the upscale prompt, each with its own saved frames."""

    def __init__(self, tmp: Path, *, upscaled: int = 3) -> None:
        super().__init__(tmp)
        self.uploads: list[str] = []
        self.upscaled = upscaled
        for name in (
            "LoadVideo",
            "GetVideoComponents",
            "ResizeImageMaskNode",
            "SeedVR2Preprocess",
            "VAELoader",
            "VAEEncodeTiled",
            "SeedVR2TemporalChunk",
            "UNETLoader",
            "SeedVR2Conditioning",
            "KSampler",
            "SeedVR2TemporalMerge",
            "VAEDecodeTiled",
            "SeedVR2PostProcessing",
            "SaveImage",
        ):
            self.info.setdefault(name, {"input": {"required": {}}})

    def upload_image(self, path, **_kw):
        self.uploads.append(Path(path).name)
        return {"name": Path(path).name, "subfolder": ""}

    def queue_prompt(self, payload, **_kw):
        self.queued.append(payload)
        return {"prompt_id": f"p-{len(self.queued)}"}

    def get_history(self, prompt_id=None, **_kw):
        if prompt_id == "p-1":
            return super().get_history(prompt_id)
        images = [
            {"filename": f"upscale_job_{n:05d}_.png", "subfolder": "stablenew", "type": "output"}
            for n in range(1, self.upscaled + 1)
        ]
        return {
            prompt_id: {
                "outputs": {"14": {"images": images}},
                "status": {"status_str": "success", "completed": True},
            }
        }

    def download_view(self, filename, destination, **_kw):
        size = (32, 32) if filename.startswith("upscale") else (16, 16)
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size).save(destination)
        return Path(destination)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    CONTAINER_ROLES.clear()
    monkeypatch.delenv("STABLENEW_RIFE_EXE", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(f"{BACKEND}.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(f"{BACKEND}.upscale_install_issues", lambda _config: ())

    def _lossless(frames, work_dir, **_kw):
        target = Path(work_dir) / "stablenew_upscale_job-1.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"lossless")
        return target

    monkeypatch.setattr(f"{BACKEND}.encode_lossless_input", _lossless)

    def _metadata(path, payload):
        CONTAINER_ROLES[Path(path).name] = str(payload.get("output_role") or "")
        return True

    monkeypatch.setattr(f"{BACKEND}.write_video_container_metadata", _metadata)


def _finisher(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _finish(**kwargs):
        calls.append(kwargs)
        target = Path(kwargs["output_path"])
        target.write_bytes(b"finished")
        return ClipFinishResult(
            source_video_path=str(kwargs["video_path"]),
            video_path=str(target),
            fps=kwargs["fps"],
            input_frame_count=3,
            output_frame_count=4,
            start_frame=0,
            end_frame=3,
            loop_mode=kwargs["request"].loop_mode,
            crossfade_frames=0,
        )

    monkeypatch.setattr(f"{BACKEND}.finish_video_file", _finish)
    return calls


def _smoother(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _smooth(**kwargs):
        sizes = []
        for path in kwargs["frame_paths"]:
            with Image.open(path) as image:
                sizes.append(image.size)
        calls.append({**kwargs, "sizes": sizes})
        target = Path(kwargs["output_dir"]) / f"{kwargs['stem']}_smooth.mp4"
        target.write_bytes(b"smooth")
        return VideoInterpolationResult(
            source_video_path="frames",
            video_path=str(target),
            input_frame_count=3,
            output_frame_count=6,
            input_fps=24,
            output_fps=48,
            multiplier=2,
        )

    monkeypatch.setattr(f"{BACKEND}.interpolate_frame_files", _smooth)
    return calls


def _excluded(run: Path) -> dict[str, str]:
    filtered = SourceFilter(run.parent)
    return {
        path.name: filtered.exclusion_of(path.relative_to(run.parent).as_posix(), "video")
        for path in sorted(run.glob("*.mp4"))
    }


def test_trim_and_loop_run_on_the_native_clip_and_only_the_result_is_published(
    tmp_path: Path, monkeypatch
) -> None:
    calls = _finisher(monkeypatch)
    finishing = {"loop_mode": "ping_pong", "trim_start_seconds": 0.05}

    result = _frames_backend(_FramesComfy(tmp_path)).execute(
        None, _frames_request(tmp_path, finishing=finishing)
    )

    run = tmp_path / "run"
    native, final = run / f"{WAN_ID}_job-1.mp4", run / f"{WAN_ID}_job-1_finished.mp4"
    assert calls[0]["video_path"] == str(native) and calls[0]["fps"] == 24
    assert calls[0]["request"].loop_mode == "ping_pong"
    assert result.primary_path == str(final) and native.read_bytes() == b"mp4"
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["artifact"]["retained_paths"] == [str(native)]
    assert manifest["native_video_path"] == str(native)
    assert manifest["finishing"]["video_path"] == str(final)
    assert CONTAINER_ROLES == {final.name: "primary", native.name: "retained_source"}
    assert _excluded(run) == {native.name: RETAINED, final.name: ""}


def test_trim_applies_after_smoothing_and_both_earlier_clips_are_retained(
    tmp_path: Path, monkeypatch
) -> None:
    smoothed = _smoother(monkeypatch)
    calls = _finisher(monkeypatch)
    executable = _rife(tmp_path / "rife")

    result = _frames_backend(_FramesComfy(tmp_path)).execute(
        None,
        _frames_request(
            tmp_path,
            interpolation={"enabled": True, "multiplier": 2, "executable_path": str(executable)},
            finishing={"trim_end_seconds": 0.1},
        ),
    )

    run = tmp_path / "run"
    native = run / f"{WAN_ID}_job-1.mp4"
    smooth = run / f"{WAN_ID}_job-1_smooth.mp4"
    final = run / f"{WAN_ID}_job-1_smooth_finished.mp4"
    assert len(smoothed) == 1
    assert calls[0]["video_path"] == str(smooth) and calls[0]["fps"] == 48
    assert result.primary_path == str(final)
    assert result.to_variant_payload()["video_paths"] == [str(final), str(smooth), str(native)]
    assert _excluded(run) == {native.name: RETAINED, smooth.name: RETAINED, final.name: ""}


def test_the_upscale_runs_first_and_smoothing_reads_the_upscaled_frames(
    tmp_path: Path, monkeypatch
) -> None:
    smoothed = _smoother(monkeypatch)
    client = _UpscaleComfy(tmp_path)
    executable = _rife(tmp_path / "rife")

    result = _frames_backend(client).execute(
        None,
        _frames_request(
            tmp_path,
            interpolation={"enabled": True, "multiplier": 2, "executable_path": str(executable)},
            finishing={"upscale": dict(UPSCALE)},
        ),
    )

    run = tmp_path / "run"
    native = run / f"{WAN_ID}_job-1.mp4"
    final = run / f"{WAN_ID}_job-1_upscaled_smooth.mp4"
    assert len(client.queued) == 2
    graph = client.queued[1]["prompt"]
    assert graph["8"]["class_type"] == "UNETLoader" and graph["10"]["inputs"]["seed"] == 7
    assert graph["1"]["inputs"]["file"] == "stablenew_upscale_job-1.mp4"
    assert client.uploads[-1] == "stablenew_upscale_job-1.mp4"
    assert smoothed[0]["sizes"] == [(32, 32)] * 3
    assert result.primary_path == str(final)
    assert not list(run.glob("*_upscale_work"))
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["upscale"]["pass_id"] == "seedvr2_3b_int8_upscale_2x"
    assert manifest["upscale"]["frame_count"] == 3
    assert manifest["upscale"]["resource_readiness"]["ready"] is True
    assert manifest["native_video_path"] == str(native)
    # The native frames, which continuation uses, are untouched.
    assert [Path(p).name for p in manifest["frame_paths"]] == [
        f"wan22_job_{n:05d}_.png" for n in (1, 2, 3)
    ]
    assert _excluded(run) == {native.name: RETAINED, final.name: ""}


def test_an_upscale_without_smoothing_is_encoded_once_then_looped(
    tmp_path: Path, monkeypatch
) -> None:
    calls = _finisher(monkeypatch)
    client = _UpscaleComfy(tmp_path)

    result = _frames_backend(client).execute(
        None,
        _frames_request(tmp_path, finishing={"upscale": dict(UPSCALE), "loop_mode": "ping_pong"}),
    )

    run = tmp_path / "run"
    upscaled = run / f"{WAN_ID}_job-1_upscaled.mp4"
    final = run / f"{WAN_ID}_job-1_upscaled_finished.mp4"
    assert calls[0]["video_path"] == str(upscaled)
    assert result.primary_path == str(final)
    assert _excluded(run) == {
        f"{WAN_ID}_job-1.mp4": RETAINED,
        upscaled.name: RETAINED,
        final.name: "",
    }


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        ("opt_in", "opt-in"),
        ("files", "owner's OK"),
        ("nodes", "SeedVR2Conditioning"),
        ("size", "480p"),
    ],
)
def test_the_upscale_is_refused_before_anything_is_generated(
    tmp_path: Path, monkeypatch, break_it: str, message: str
) -> None:
    client = _UpscaleComfy(tmp_path)
    block = dict(UPSCALE)
    config: dict[str, Any] = {}
    if break_it == "opt_in":
        block["experimental_opt_in"] = False
    elif break_it == "files":
        monkeypatch.setattr(
            f"{BACKEND}.upscale_install_issues", lambda _config: ("model file missing: x",)
        )
    elif break_it == "nodes":
        del client.info["SeedVR2Conditioning"]
    else:
        config["source_preparation"] = {"target_dimensions": {"width": 704, "height": 1280}}

    with pytest.raises(Exception, match=message):
        _frames_backend(client).execute(
            None, _frames_request(tmp_path, finishing={"upscale": block}, **config)
        )

    assert client.queued == []


def test_the_vram_stop_rule_is_checked_again_before_the_upscale_is_queued(tmp_path: Path) -> None:
    client = _UpscaleComfy(tmp_path)
    backend = _frames_backend(client)
    low = _stats(free_mib=6000)
    readings = iter([_driver_probe(client.stats), _driver_probe(low)])
    probes: list[Any] = []

    def _probe(index: int):
        probes.append(next(readings))
        return probes[-1](index)

    backend._readiness = type(backend._readiness)(ram_probe=lambda: 24.0, gpu_probe=_probe)

    with pytest.raises(RuntimeError, match="upscale is not resource-ready"):
        backend.execute(None, _frames_request(tmp_path, finishing={"upscale": dict(UPSCALE)}))

    assert len(client.queued) == 1  # the clip was generated; the upscale was not dispatched
    assert not list((tmp_path / "run").glob("*_upscale_work"))


def test_a_short_upscale_result_fails_instead_of_losing_frames(tmp_path: Path) -> None:
    client = _UpscaleComfy(tmp_path, upscaled=2)

    with pytest.raises(RuntimeError, match="2 frames for 3"):
        _frames_backend(client).execute(
            None, _frames_request(tmp_path, finishing={"upscale": dict(UPSCALE)})
        )


def test_an_upscaled_job_releases_the_runtime_instead_of_keeping_it_warm(
    tmp_path: Path, monkeypatch
) -> None:
    released: list[str] = []
    backend = _frames_backend(_UpscaleComfy(tmp_path))
    monkeypatch.setattr(f"{BACKEND}._release_owned_runtime_after_job", lambda _spec: True)
    monkeypatch.setattr(
        backend, "_hold_owned_runtime", lambda *_a: released.append("held") or {"held": True}
    )
    monkeypatch.setattr(
        backend, "_release_owned_runtime", lambda: released.append("released") or {"released": True}
    )

    backend.execute(None, _frames_request(tmp_path, finishing={"upscale": dict(UPSCALE)}))

    assert released == ["released"]


def test_leftovers_of_an_interrupted_upscale_are_never_published(tmp_path: Path) -> None:
    filtered = SourceFilter(tmp_path)

    assert filtered.exclusion_of("run/clip_upscale_work/output/upscale_job_00001_.png", "image")
    assert filtered.exclusion_of("run/clip_upscale_work/stablenew_upscale_job.mp4", "video")
    assert filtered.exclusion_of("run/clip.mp4", "video") == ""


def test_continuation_decodes_the_native_clip_of_a_finished_job() -> None:
    from src.video.storyboard_root import _unsmoothed_clip

    artifact = {
        "primary_path": "run/c_finished.mp4",
        "video_paths": ["run/c_finished.mp4", "run/c.mp4"],
    }

    assert _unsmoothed_clip(artifact, None, {"native_video_path": "run/c.mp4"}) == Path("run/c.mp4")

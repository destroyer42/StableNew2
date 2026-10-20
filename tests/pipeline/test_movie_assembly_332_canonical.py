"""PR-VID-ASM-332: Movie Clips assembly runs on the canonical path.

NJR (frozen, hashed) -> JobService -> SQLite queue/repository -> PipelineRunner.run_njr -> MovieAssemblyHandler ->
artifact + History. Tests that encode use real FFmpeg on KB-sized generated files and skip without it.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.api.client import SDWebUIClient
from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.replay_input_verification import frozen_input_checks, verify_inputs
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.pipeline.run_plan import build_run_plan_from_njr
from src.pipeline.run_stage_handlers import MovieAssemblyHandler, resolve_stage_handler
from src.pipeline.video import resolve_ffmpeg_executable
from src.queue.backend_dependency import BackendDependency, classify_record, classify_snapshot
from src.queue.job_model import JobStatus
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.movie_assembly_compiler import (
    AssemblyIntentClip,
    MovieAssemblyIntent,
    VideoFacts,
    build_movie_assembly_njr,
    freeze_movie_assembly,
)
from tests.helpers.njr_queue_harness import run_njr_via_queue

FFMPEG = resolve_ffmpeg_executable()
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or resolve_ffprobe_executable() is None,
    reason="FFmpeg/FFprobe are not installed",
)


def _still(path: Path, rgb: tuple[int, int, int]) -> Path:
    Image.new("RGB", (40, 30), rgb).save(path)
    return path


def _tone(path: Path) -> Path:
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=1", str(path)],
        check=True,
        capture_output=True,
    )
    return path


def _assembly_njr(tmp_path: Path, *, audio: bool = False) -> NormalizedJobRecord:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    stills = [_still(src / "b.png", (200, 0, 0)), _still(src / "a.png", (0, 0, 200))]
    intent = MovieAssemblyIntent(
        clips=tuple(AssemblyIntentClip(str(path), 0.5) for path in stills),
        fps=8,
        transition_seconds=0.125,
        audio_path=str(_tone(src / "m.wav")) if audio else None,
        audio_fade_out_seconds=0.25,
    )
    if audio:
        spec = freeze_movie_assembly(intent)
    else:  # no FFprobe needed for stills only
        spec = freeze_movie_assembly(
            intent, video_probe=lambda p: VideoFacts(8, 8, 1.0, None), audio_probe=lambda p: None
        )
    return build_movie_assembly_njr(spec, output_dir=tmp_path / "output")


def _runner(tmp_path: Path) -> PipelineRunner:
    return PipelineRunner(
        api_client=MagicMock(),
        structured_logger=MagicMock(),
        runs_base_dir=str(tmp_path / "output"),
    )


# --- identity, classification, plan ------------------------------------------------------------


def test_the_njr_is_immutable_and_survives_its_snapshot(tmp_path: Path) -> None:
    njr = _assembly_njr(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        njr.job_id = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        njr.workload.config["movie_assembly"]["fps"] = 30  # type: ignore[index]
    restored = NormalizedJobRecord.from_dict(njr.to_queue_snapshot())
    assert restored.config["movie_assembly"] == njr.config["movie_assembly"]
    assert restored.input_image_paths == njr.input_image_paths


def test_assembly_needs_neither_the_webui_nor_the_gpu(tmp_path: Path) -> None:
    njr = _assembly_njr(tmp_path)
    for assessment in (classify_record(njr), classify_snapshot(njr.to_queue_snapshot())):
        assert assessment.dependency is BackendDependency.INDEPENDENT_VIDEO
        assert assessment.reason == "movie_assembly"
        assert assessment.gpu_free is True
        assert assessment.held_by_webui_outage is False
        assert assessment.held_by_gpu_loss is False


def test_generative_video_stays_held_by_a_gpu_loss(tmp_path: Path) -> None:
    njr = _assembly_njr(tmp_path)
    svd_like = classify_snapshot(
        {
            **njr.to_queue_snapshot(),
            "stages": [{"stage_type": "svd_native", "enabled": True}],
        }
    )
    assert svd_like.gpu_free is False


def test_the_plan_runs_one_assembly_stage_through_its_own_handler(tmp_path: Path) -> None:
    plan = build_run_plan_from_njr(_assembly_njr(tmp_path))
    assert plan.enabled_stages == ["movie_assembly"]

    def _not_consulted(_stage: str) -> bool:
        raise AssertionError("assembly is not a video backend stage")

    assert isinstance(resolve_stage_handler("movie_assembly", _not_consulted), MovieAssemblyHandler)


# --- replay re-verification --------------------------------------------------------------------


def test_replay_keeps_the_frozen_spec_and_lists_every_digest(tmp_path: Path) -> None:
    njr = _assembly_njr(tmp_path)
    replay = compile_replay_intent(ReplayIntent(njr))
    assert replay.job_id != njr.job_id
    assert replay.source.parent_job_id == njr.job_id
    assert replay.config["movie_assembly"] == njr.config["movie_assembly"]

    checks = frozen_input_checks(replay)
    clips = njr.config["movie_assembly"]["clips"]
    assert [(check.label, check.path, check.expected_sha256) for check in checks] == [
        ("assembly clip", clip["path"], clip["sha256"]) for clip in clips
    ]
    assert verify_inputs(checks) == []


@needs_ffmpeg
def test_audio_track_is_a_frozen_input(tmp_path: Path) -> None:
    njr = _assembly_njr(tmp_path, audio=True)
    labels = [check.label for check in frozen_input_checks(njr)]
    assert labels == ["assembly clip", "assembly clip", "assembly audio track"]


def test_a_replay_with_a_changed_input_is_refused_at_run_time(tmp_path: Path) -> None:
    njr = _assembly_njr(tmp_path)
    replay = compile_replay_intent(ReplayIntent(njr))
    _still(Path(njr.input_image_paths[0]), (201, 0, 0))

    issues = verify_inputs(frozen_input_checks(replay))
    assert [issue.reason for issue in issues] == ["changed since the job was created"]
    result = _runner(tmp_path).run_njr(replay)
    assert result.success is False
    assert "no longer the ones that were queued" in str(result.error)
    assert not list((tmp_path / "output").rglob("*.mp4"))


def test_cancel_reaches_the_assembly_stage(tmp_path: Path) -> None:
    token = CancelToken()
    token.cancel()
    with pytest.raises(CancellationError):
        _runner(tmp_path).run_njr(_assembly_njr(tmp_path), cancel_token=token)
    assert not list((tmp_path / "output").rglob("*.mp4"))


# --- execution and history ---------------------------------------------------------------------


@needs_ffmpeg
def test_run_njr_records_the_movie_as_a_video_artifact(tmp_path: Path) -> None:
    njr = _assembly_njr(tmp_path)
    result = _runner(tmp_path).run_njr(njr)

    assert result.success is True, result.error
    output = Path(result.variants[0]["path"])
    assert output.is_file() and output.suffix == ".mp4"
    assert output.parent.parent == tmp_path / "output" / "movie_clips"
    metadata = result.metadata
    assert metadata["video_primary_stage"] == "movie_assembly"
    artifact = metadata["video_artifacts"]["movie_assembly"]
    assert artifact["primary_path"] == str(output)
    assert artifact["assembly"]["total_frames"] == 7  # 2 x 4 frames, one 1-frame crossfade
    assert Path(artifact["manifest_path"]).is_file()
    assert result.variants[0]["artifact"]["artifact_type"] == "video"


@needs_ffmpeg
def test_queued_assembly_completes_into_history_without_any_webui_generation(
    tmp_path: Path,
) -> None:
    njr = _assembly_njr(tmp_path)
    transport: list[tuple[str, str]] = []
    entry = run_njr_via_queue(
        njr,
        SDWebUIClient(base_url="http://127.0.0.1:7860"),
        timeout_seconds=60.0,
        artifact_root=tmp_path / "q",
        transport_log=transport,
    )

    assert entry.status == JobStatus.COMPLETED, entry.error_message
    assert entry.job_id == njr.job_id
    outputs = list((tmp_path / "q" / "output" / "movie_clips").rglob("*.mp4"))
    assert len(outputs) == 1
    result = entry.result or {}
    assert [variant["path"] for variant in result["variants"]] == [str(outputs[0])]
    assert result["metadata"]["video_primary_stage"] == "movie_assembly"
    assert entry.snapshot["normalized_job"]["stages"][0]["stage_type"] == "movie_assembly"
    assert transport == []  # not one WebUI request, generation or otherwise

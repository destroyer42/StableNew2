"""V1-6: continuing a clip while ComfyUI is still warm from the clip (desktop and phone).

The first physical run refused the continuation 7 s after an A14B clip finished: the held ComfyUI's model counted as
memory "in use by other processes".  Here: a warm A14B job, then the continuation each surface builds, run by the real
runner, sequence executor and Comfy backend.  Fake ComfyUI, driver probe and process; no GPU, model or network.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from PIL import Image

from src.app.site_phone_continue import compile_continuation
from src.controller.continue_clip import continue_clip, inspect_continuation
from src.controller.storyboard_submission_service import StoryboardSubmissionService
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.video import resolve_ffmpeg_executable
from src.video import VideoBackendRegistry
from src.video.sequence_ledger import sha256_of
from src.video.storyboard_tree_store import StoryboardTreeStore
from tests.helpers.storyboard_380 import (
    A14B_SIZE,
    REG,
    FakeRepository,
    builder,
    frames_out_job,
    unsmoothed_mp4,
)
from tests.video.test_vid_clip_370_candidate_specs import (
    _a14b_backend,
    _a14b_info,
    _a14b_request,
    _fake_export,
    _FramesFake,
)
from tests.video.test_vid_warm_373_a14b_reuse import _slot
from tests.video.test_wan22_experimental_workflow import _stats

pytestmark = pytest.mark.skipif(
    resolve_ffmpeg_executable() is None, reason="FFmpeg is not installed"
)

#: The first physical run's figures when the continuation started: the clip's model still held by ComfyUI, of which
#: PyTorch reported 96 MiB.  5,621 + 96 = 5,717 MiB "available", under the 8,600 MiB floor.
DRIVER_FREE_MIB = 5621.0
TORCH_HELD_MIB = 96.0
FRAMES = 17


class _Repository(FakeRepository):
    def list_recent_jobs(self, *, limit: int = 50, statuses: Any = None) -> list[Any]:
        return [
            SimpleNamespace(job_id=job.job_id, result=job.result)
            for job in reversed(list(self.jobs.values()))
            if not statuses or job.status in statuses
        ][:limit]


class _Comfy(_FramesFake):
    """Saves frames of the continued clip's size."""

    def download_view(self, filename, destination, *, subfolder="", file_type="output", **_kw):
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shade = (int(filename.split("_")[1]) * 10) % 256
        Image.new("RGB", A14B_SIZE, (shade, 40, 90)).save(target)
        return target


def _continuation(tmp_path: Path, surface: str) -> Any:
    """The NJR that Continue this clip (desktop) or Continue clip (phone) queues for a finished A14B clip."""

    source, job_id, _frames = frames_out_job(tmp_path, count=FRAMES)
    repository = _Repository(jobs=dict(source.jobs), files=dict(source.files))
    queued: list[Any] = []

    def admit(njrs: list[Any], *_policy: Any) -> list[str]:
        queued.extend(njrs)
        return [njr.job_id for njr in njrs]

    service = StoryboardSubmissionService(
        njr_builder=builder(tmp_path),
        workflow_registry=REG,
        job_service=lambda: SimpleNamespace(submit_njrs=admit),
        repository=lambda: repository,
        store=StoryboardTreeStore(tmp_path / "trees"),
        output_root=lambda: str(tmp_path),
        draw_seed=lambda: 1,
    )
    if surface == "desktop":
        continue_clip(service, inspect_continuation(service, job_id), prompt="the person nods")
    else:
        clip = unsmoothed_mp4(source, job_id)
        compiled = compile_continuation(
            service, tmp_path, clip, sha256_of(clip), "the person nods", 7, video=Mock()
        )
        assert compiled.build is not None
        compiled.build(admit)
    (njr,) = queued
    return njr


@pytest.mark.parametrize("surface", ["desktop", "phone"])
def test_a_continuation_of_a_just_made_clip_runs_on_the_warm_comfyui(
    tmp_path: Path, monkeypatch, surface: str
) -> None:
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )
    njr = _continuation(tmp_path, surface)
    slot, clock, _ = _slot()
    client = _Comfy(tmp_path, save_node="16", info=_a14b_info(), stats=_stats(free_mib=11800.0))
    backend = _a14b_backend(client, tmp_path, warm_hold=slot)
    first = _a14b_request(tmp_path)  # the clip itself: a standalone A14B job
    first.output_dir = tmp_path / "run-first"
    backend.execute(None, first)
    manager = backend.fake_manager
    assert slot.snapshot() is not None and manager.stops == 0  # held warm

    clock.now += 7
    client.stats["devices"][0].update(
        _driver_free_mib=DRIVER_FREE_MIB, torch_vram_total=TORCH_HELD_MIB * 1024 * 1024
    )
    registry = VideoBackendRegistry()
    registry.register(backend)
    runner = PipelineRunner(
        Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"), video_backend_registry=registry
    )
    runner._pipeline = Mock()

    result = runner.run_njr(njr)

    assert result.success, result.error
    assert len(client.queued) == 2
    assert manager.starts == 1  # the same process throughout: never stopped and relaunched
    assert manager.stops == 1  # the sequence's own release, once, after the continuation

"""PR-VID-QUALITY-211 test harness: a real one-variable experiment in a real (temporary) repository.

Arms come from the production ``VideoWorkflowController`` preview (the same NJR builder a queued experiment
uses), are persisted through ``JobRepository.record_job_submissions`` and finished through
``transition_job``.  Clips are tiny synthetic FFmpeg ``testsrc`` videos generated on the CPU.  Nothing here
starts Comfy, a WebUI, a model or a GPU, and no user repository, output or Learning file is touched.
"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.job_models_v2 import NormalizedJobRecord, SourceKind
from src.pipeline.video import resolve_ffmpeg_executable
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.video_workflow_experiment import ExperimentPlan
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_CONTROLS_VERSION,
    WAN_ANIMATE2_DRIVE_ID,
)
from tests.helpers.job_helpers import make_test_job_from_njr

FFMPEG = resolve_ffmpeg_executable()
FFPROBE = resolve_ffprobe_executable()
FFMPEG_AVAILABLE = FFMPEG is not None and FFPROBE is not None
APPEARANCE = "Character appearance description: a woman in a navy top. Background: pale studio."
MOTION = "A person steps left, then raises an arm."


class _NoSubmitJobService:
    def submit_njrs(self, njrs, policy):  # pragma: no cover - previews never admit
        raise AssertionError("the review harness must not submit work")


def build_plan(
    tmp_path: Path,
    *,
    candidates: tuple[str, ...] = ("1.5", "2"),
    variable: str = "pose_strength",
    seed: str = "424242",
    prompt: str = APPEARANCE,
) -> ExperimentPlan:
    tmp_path.mkdir(parents=True, exist_ok=True)
    app = SimpleNamespace(job_service=_NoSubmitJobService(), output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app)
    source = tmp_path / "reference.png"
    Image.new("RGB", (48, 80), "navy").save(source)
    driving = tmp_path / "driving.mp4"
    driving.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake driving clip")
    form: dict[str, Any] = {
        "workflow_id": WAN_ANIMATE2_DRIVE_ID,
        "workflow_version": WAN_ANIMATE2_CONTROLS_VERSION,
        "prompt": prompt,
        "negative_prompt": "",
        "pose_video_path": str(driving),
        "experimental_opt_in": True,
        "seed": seed,
        "operator_controls": {"pose_prompt": MOTION, "pose_strength": "1"},
    }
    return controller.preview_experiment(
        source_image_path=source,
        form_data=form,
        variable_name=variable,
        candidates=list(candidates),
    )


def new_repository(tmp_path: Path, name: str = "jobs.sqlite3") -> JobRepository:
    return JobRepository(tmp_path / name)


def persist(repository: JobRepository, njrs: list[NormalizedJobRecord]) -> list[str]:
    """Admit NJRs the way the queue does: one all-or-none transaction."""

    jobs = [make_test_job_from_njr(njr, prompt_source="manual") for njr in njrs]
    repository.record_job_submissions(jobs)
    return [job.job_id for job in jobs]


def persist_plan(repository: JobRepository, plan: ExperimentPlan) -> list[str]:
    return persist(repository, [arm.njr for arm in plan.arms])


def finish(
    repository: JobRepository,
    job_id: str,
    status: JobStatus,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    job = repository.get_job_model(job_id)
    assert job is not None
    if status in {JobStatus.COMPLETED, JobStatus.FAILED}:
        repository.transition_job(job, JobStatus.RUNNING)
        job = repository.get_job_model(job_id)
        assert job is not None
    repository.transition_job(job, status, result=result, error_message=error)


def video_result(path: Path, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    bundle = {
        "stage": "video_workflow",
        "backend_id": "comfy",
        "artifact_type": "video",
        "primary_path": str(path),
        "output_paths": [str(path)],
        "video_paths": [str(path)],
        "gif_paths": [],
        "frame_paths": [],
        "manifest_paths": [],
        "count": 1,
    }
    result: dict[str, Any] = {"video_bundle": bundle, "success": True}
    result.update(extra or {})
    return result


def make_clip(
    tmp_path: Path,
    name: str,
    *,
    frames: int = 12,
    rate: int = 12,
    size: str = "64x48",
    codec: str = "libx264",
) -> Path:
    """A deterministic synthetic clip (CPU only, a few KB)."""

    assert FFMPEG is not None
    path = tmp_path / name
    subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate={rate}",
            "-frames:v",
            str(frames),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            codec,
            str(path),
        ],  # fmt: skip
        check=True,
        capture_output=True,
        timeout=120,
    )
    return path


def njr_variant(njr: NormalizedJobRecord, **changes: Any) -> NormalizedJobRecord:
    """A copy of ``njr`` with dict-level edits (``job_id``, ``source_kind``, ``variant_index``...)."""

    data = copy.deepcopy(njr.to_dict())
    if "job_id" in changes:
        data["job_id"] = changes["job_id"]
    if "source_kind" in changes:
        data["source"]["kind"] = changes["source_kind"]
    if "variant_index" in changes:
        data["provenance"]["learning_context"]["variant_index"] = changes["variant_index"]
    if "experiment_id" in changes:
        data["provenance"]["learning_context"]["experiment_id"] = changes["experiment_id"]
    if "seed" in changes:
        data["workload"]["config"]["video_workflow"]["seed"] = changes["seed"]
    if "strip_learning_context" in changes:
        data["provenance"]["learning_context"] = None
    return NormalizedJobRecord.from_dict(data)


__all__ = [
    "APPEARANCE",
    "FFMPEG",
    "FFMPEG_AVAILABLE",
    "SourceKind",
    "build_plan",
    "finish",
    "make_clip",
    "new_repository",
    "njr_variant",
    "persist",
    "persist_plan",
    "video_result",
]

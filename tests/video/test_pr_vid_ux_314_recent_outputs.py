"""PR-VID-UX-314: recent finished clips recovered from canonical persisted jobs.

A real SQLite repository in a temp dir, NJRs built by the production Video Workflow controller, and tiny
placeholder files for outputs.  Nothing is generated and no directory is scanned.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.video.recent_video_outputs import (
    discover_recent_video_outputs,
    list_recent_video_outputs,
    recent_output_from_entry,
)
from tests.helpers.make_video_313 import TI2V_ID, make_app, make_image
from tests.helpers.video_review_211 import finish, new_repository, persist, video_result


def _njr(tmp_path: Path, name: str, *, seed: str = "5"):
    app, controller, service = make_app(tmp_path)
    source = make_image(tmp_path / f"{name}.png")
    controller.submit_video_workflow_job(
        source_image_path=source,
        form_data={
            "workflow_id": TI2V_ID,
            "workflow_version": "1.2.0",
            "prompt": f"{name} turns",
            "seed": seed,
            "source_lineage": {"source_job_id": "parent-job"},
        },
    )
    return service.submitted[-1], source


def _clip(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "output" / f"{name}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not decoded here")
    return path


def test_a_completed_job_is_listed_with_provenance_read_from_its_frozen_njr(tmp_path) -> None:
    repository = new_repository(tmp_path)
    njr, source = _njr(tmp_path, "alpha", seed="5")
    [job_id] = persist(repository, [njr])
    clip = _clip(tmp_path, "alpha")
    result = video_result(clip)
    finish(repository, job_id, JobStatus.COMPLETED, result=result)

    [output] = list_recent_video_outputs(repository, limit=5)
    assert output.job_id == job_id and output.video_path == str(clip)
    assert output.workflow_label == "Wan2.2 TI2V-5B Prompt-Directed I2V"
    assert output.backend_id == "comfy" and output.seed == 5
    assert output.frame_count == 49 and output.fps == 24.0
    assert output.length_text == "49 frames (~2.0 s)"
    assert output.source_image_path == str(Path(source))
    assert dict(output.bundle) == result["video_bundle"]  # handed on exactly as recorded
    assert output.file_name == "alpha.mp4" and output.completed_at is not None
    assert output.visibility_subject["prompt"] == "alpha turns"


def test_frozen_prompt_is_preserved_for_content_visibility(tmp_path) -> None:
    from src.controller.content_visibility_resolver import ContentVisibilityResolver

    repository = new_repository(tmp_path)
    njr, _source = _njr(tmp_path, "nude")
    [job_id] = persist(repository, [njr])
    clip = _clip(tmp_path, "innocent-file-name")
    finish(repository, job_id, JobStatus.COMPLETED, result=video_result(clip))
    [output] = list_recent_video_outputs(repository)
    assert not ContentVisibilityResolver("sfw").is_visible(output.visibility_subject)
    assert ContentVisibilityResolver("nsfw").is_visible(output.visibility_subject)


def test_only_playable_completed_outputs_qualify(tmp_path) -> None:
    repository = new_repository(tmp_path)
    cases = {}
    for name in ("good", "failed", "queued", "cancelled", "missing", "frames", "errored", "image"):
        njr, _ = _njr(tmp_path, name)
        [cases[name]] = persist(repository, [njr])
    good = _clip(tmp_path, "good")
    finish(repository, cases["good"], JobStatus.COMPLETED, result=video_result(good))
    finish(repository, cases["failed"], JobStatus.FAILED, error="boom")
    finish(repository, cases["cancelled"], JobStatus.CANCELLED)
    finish(
        repository,
        cases["missing"],
        JobStatus.COMPLETED,
        result=video_result(tmp_path / "output" / "deleted_since.mp4"),
    )
    frames_result = video_result(tmp_path / "frames" / "f_0001.png")
    frames_result["video_bundle"].update(video_paths=[], primary_path=None, frame_paths=["a.png"])
    finish(repository, cases["frames"], JobStatus.COMPLETED, result=frames_result)
    finish(
        repository,
        cases["errored"],
        JobStatus.COMPLETED,
        result=video_result(_clip(tmp_path, "errored"), extra={"error": "post-process failed"}),
    )
    finish(
        repository,
        cases["image"],
        JobStatus.COMPLETED,
        result={"artifact": {"artifact_type": "image"}},
    )

    found = list_recent_video_outputs(repository, limit=20)
    assert [o.job_id for o in found] == [cases["good"]]


def test_the_listing_is_bounded_and_checks_only_the_recorded_files(tmp_path) -> None:
    repository = new_repository(tmp_path)
    ids = []
    for index in range(6):
        njr, _ = _njr(tmp_path, f"clip{index}")
        [job_id] = persist(repository, [njr])
        finish(
            repository,
            job_id,
            JobStatus.COMPLETED,
            result=video_result(_clip(tmp_path, f"clip{index}")),
        )
        ids.append(job_id)

    checked: list[str] = []

    def is_file(path: str) -> bool:
        checked.append(path)
        return True

    found = list_recent_video_outputs(repository, limit=2, is_file=is_file)
    assert len(found) == 2 and {o.job_id for o in found} <= set(ids)
    assert (
        len(checked) == 2
    )  # one existence check per returned clip; no directory scan, no extra probing
    assert all(path.endswith(".mp4") for path in checked)
    assert list_recent_video_outputs(repository, limit=0) == []


def test_entries_are_ordered_as_given_and_scanning_stops_at_the_limit(tmp_path) -> None:
    base = datetime(2026, 10, 22, 12, 0, 0)
    entries = []
    for index in range(5):
        clip = _clip(tmp_path, f"e{index}")
        entries.append(
            JobHistoryEntry(
                job_id=f"job-{index}",
                created_at=base - timedelta(minutes=index),
                completed_at=base - timedelta(minutes=index),
                status=JobStatus.COMPLETED,
                result=video_result(clip),
            )
        )
    found = discover_recent_video_outputs(entries, limit=3)
    assert [o.job_id for o in found] == [
        "job-0",
        "job-1",
        "job-2",
    ]  # the repository's newest-first order
    assert (
        found[0].workflow_label == "comfy"
    )  # no snapshot: provenance is empty, the clip is still offered
    assert found[0].seed is None and found[0].source_image_path == ""


def test_an_unreadable_path_is_not_offered_and_never_raises() -> None:
    entry = JobHistoryEntry(
        job_id="job-x",
        created_at=datetime(2026, 1, 1),
        status=JobStatus.COMPLETED,
        result=video_result(Path("whatever.mp4")),
    )

    def explode(_path: str) -> bool:
        raise OSError("device not ready")

    assert recent_output_from_entry(entry, is_file=explode) is None


def test_a_repository_without_a_reader_yields_nothing() -> None:
    assert list_recent_video_outputs(object()) == []
    assert list_recent_video_outputs(None) == []


def test_the_controller_reads_the_job_services_repository(tmp_path) -> None:
    repository = new_repository(tmp_path)
    app, controller, _service = make_app(tmp_path, repository=repository)
    njr, _ = _njr(tmp_path, "viaCtl")
    [job_id] = persist(repository, [njr])
    finish(repository, job_id, JobStatus.COMPLETED, result=video_result(_clip(tmp_path, "viaCtl")))
    assert [o.job_id for o in controller.list_recent_video_outputs(5)] == [job_id]

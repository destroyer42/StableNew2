"""PR-VID-ASM-332: Movie Clips admission crosses JobService.submit_njrs once; AppController only delegates."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.app_controller import AppController
from src.controller.movie_clips_submission_service import (
    MovieClipsSubmissionService,
    build_movie_assembly_intent,
)
from src.video.movie_assembly_compiler import MovieAssemblyAdmissionError


class _RecordingJobService:
    def __init__(self, job_ids: list[str] | None = None) -> None:
        self.calls: list[tuple[list[Any], Any]] = []
        self._job_ids = ["job-1"] if job_ids is None else job_ids

    def submit_njrs(self, njrs: list[Any], policy: Any) -> list[str]:
        self.calls.append((list(njrs), policy))
        return list(self._job_ids)


def _stills(tmp_path: Path, *names: str) -> list[Path]:
    paths = []
    for name in names:
        path = tmp_path / name
        Image.new("RGB", (32, 24), (90, 60, 30)).save(path)
        paths.append(path)
    return paths


def test_intent_keeps_order_and_aligns_per_clip_durations() -> None:
    intent = build_movie_assembly_intent(
        ["z.png", "a.mp4", "m.png"],
        {
            "mode": "slideshow",
            "fps": "30",
            "clip_durations": [None, None, 2],
            "still_seconds": 1.5,
            "transition_seconds": 0.75,
            "resolution": "1280x720",
            "audio_path": " music.mp3 ",
            "audio_fade_out_seconds": 2,
            "clip_name": "trip",
            "quality": "slow",
        },
    )
    assert [clip.path for clip in intent.clips] == ["z.png", "a.mp4", "m.png"]
    assert [clip.duration_seconds for clip in intent.clips] == [None, None, 2.0]
    assert (intent.fps, intent.still_seconds, intent.transition_seconds) == (30, 1.5, 0.75)
    assert (intent.resolution, intent.audio_path, intent.audio_fade_out_seconds) == (
        "1280x720",
        "music.mp3",
        2.0,
    )
    assert (intent.clip_name, intent.quality) == ("trip", "slow")


def test_intent_refuses_a_non_numeric_setting() -> None:
    with pytest.raises(MovieAssemblyAdmissionError, match="Transition must be a number"):
        build_movie_assembly_intent(["a.png"], {"transition_seconds": "soon"})


def test_submit_freezes_and_crosses_job_service_once(tmp_path: Path) -> None:
    stills = _stills(tmp_path, "b.png", "a.png")
    job_service = _RecordingJobService()
    service = MovieClipsSubmissionService(job_service=job_service, output_dir=tmp_path / "output")

    job_id = service.submit(stills, {"mode": "slideshow", "transition_seconds": 0.0})

    assert job_id == "job-1"
    assert len(job_service.calls) == 1
    (njr,), _policy = job_service.calls[0]
    assert [stage.stage_type for stage in njr.stages] == ["movie_assembly"]
    assert [Path(path).name for path in njr.input_image_paths] == ["b.png", "a.png"]
    assert njr.output_plan.base_output_dir == str(tmp_path / "output")
    assert all(len(clip["sha256"]) == 64 for clip in njr.config["movie_assembly"]["clips"])


def test_background_admission_reports_the_job_on_the_gui_dispatcher(tmp_path: Path) -> None:
    stills = _stills(tmp_path, "a.png")
    dispatched: list[str] = []
    spawned: list[dict[str, Any]] = []
    results: list[str] = []

    def spawn(**kwargs: Any) -> None:
        spawned.append(kwargs)
        kwargs["target"]()

    def dispatch(callback: Any) -> None:
        dispatched.append("gui")
        callback()

    service = MovieClipsSubmissionService(
        job_service=_RecordingJobService(["job-9"]), spawn=spawn, dispatch=dispatch
    )
    service.submit_in_background(stills, {}, on_complete=results.append, on_error=results.append)

    assert results == ["job-9"]
    assert dispatched == ["gui"]
    assert len(spawned) == 1 and "daemon" not in spawned[0]  # a tracked, joinable worker


def test_background_admission_reports_refusals_without_submitting(tmp_path: Path) -> None:
    job_service = _RecordingJobService()
    errors: list[str] = []
    MovieClipsSubmissionService(job_service=job_service).submit_in_background(
        [tmp_path / "missing.png"], {}, on_complete=lambda job: None, on_error=errors.append
    )
    assert len(errors) == 1 and "does not exist" in errors[0]
    assert job_service.calls == []


def test_background_admission_reports_an_unqueued_job(tmp_path: Path) -> None:
    errors: list[str] = []
    MovieClipsSubmissionService(job_service=_RecordingJobService([])).submit_in_background(
        _stills(tmp_path, "a.png"), {}, on_error=errors.append
    )
    assert errors == ["The movie assembly job could not be queued."]


def test_app_controller_only_delegates_to_the_submission_service(tmp_path: Path) -> None:
    stills = _stills(tmp_path, "a.png", "b.png")
    job_service = _RecordingJobService(["job-3"])
    spawned: list[dict[str, Any]] = []

    def spawn(**kwargs: Any) -> None:
        spawned.append(kwargs)
        kwargs["target"]()

    fake_controller = SimpleNamespace(
        job_service=job_service,
        output_dir=str(tmp_path / "output"),
        _spawn_tracked_thread=spawn,
        _run_in_gui_thread=lambda callback: callback(),
    )
    results: list[str] = []
    AppController.on_build_movie_clip(
        fake_controller,  # type: ignore[arg-type]
        image_paths=stills,
        settings={"mode": "sequence"},
        on_complete=results.append,
        on_error=results.append,
    )

    assert results == ["job-3"]
    assert spawned[0]["name"] == "movie-clip-admission"
    (njr,), _policy = job_service.calls[0]
    assert njr.config["movie_assembly"]["mode"] == "sequence"
    assert not hasattr(AppController, "on_load_movie_clip_source")

"""Movie Clips admission (PR-VID-ASM-332): the tab's request becomes one queued assembly job.

The tab hands over its ordered list and settings. This service builds the assembly intent, freezes it (every input is
hashed and measured, off the GUI thread) into a movie-assembly NJR and crosses ``JobService.submit_njrs`` exactly once.
It never runs FFmpeg: the queue does, through ``PipelineRunner.run_njr``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.video.movie_assembly_compiler import (
    DEFAULT_CLIP_NAME,
    DEFAULT_FADE_OUT_SECONDS,
    DEFAULT_STILL_SECONDS,
    DEFAULT_TRANSITION_SECONDS,
    RESOLUTION_MATCH_FIRST,
    AssemblyIntentClip,
    MovieAssemblyAdmissionError,
    MovieAssemblyIntent,
    build_movie_assembly_njr,
    freeze_movie_assembly,
)
from src.video.movie_assembly_models import MODE_SLIDESHOW, MovieAssemblySpec

logger = logging.getLogger(__name__)


def _float(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise MovieAssemblyAdmissionError(f"{label} must be a number, got {value!r}.") from exc


def _number(settings: Mapping[str, Any], key: str, default: float, label: str) -> float:
    value = settings.get(key)
    return default if value is None or value == "" else _float(value, label)


def build_movie_assembly_intent(
    image_paths: Sequence[str | Path], settings: Mapping[str, Any]
) -> MovieAssemblyIntent:
    """The intent for the tab's ordered list and settings (``clip_durations`` aligns with ``image_paths``)."""

    durations = list(settings.get("clip_durations") or [])
    clips = []
    for index, path in enumerate(image_paths):
        raw = durations[index] if index < len(durations) else None
        duration = (
            None if raw is None or raw == "" else _float(raw, f"Duration of item {index + 1}")
        )
        clips.append(AssemblyIntentClip(path=str(path), duration_seconds=duration))
    audio_path = str(settings.get("audio_path") or "").strip() or None
    return MovieAssemblyIntent(
        clips=tuple(clips),
        mode=str(settings.get("mode") or MODE_SLIDESHOW),
        fps=int(_number(settings, "fps", 24, "FPS")),
        resolution=str(settings.get("resolution") or RESOLUTION_MATCH_FIRST),
        still_seconds=_number(settings, "still_seconds", DEFAULT_STILL_SECONDS, "Still duration"),
        transition_seconds=_number(
            settings, "transition_seconds", DEFAULT_TRANSITION_SECONDS, "Transition"
        ),
        codec=str(settings.get("codec") or "libx264"),
        quality=str(settings.get("quality") or "balanced"),
        audio_path=audio_path,
        audio_fade_out_seconds=_number(
            settings, "audio_fade_out_seconds", DEFAULT_FADE_OUT_SECONDS, "Fade-out"
        ),
        clip_name=str(settings.get("clip_name") or DEFAULT_CLIP_NAME),
    )


class MovieClipsSubmissionService:
    """Admit one Movie Clips assembly to the queue."""

    def __init__(
        self,
        *,
        job_service: Any,
        output_dir: str | Path = "output",
        spawn: Callable[..., Any] | None = None,
        dispatch: Callable[[Callable[[], None]], None] | None = None,
        freeze: Callable[[MovieAssemblyIntent], MovieAssemblySpec] = freeze_movie_assembly,
    ) -> None:
        self._job_service = job_service
        self._output_dir = output_dir
        self._spawn = spawn
        self._dispatch = dispatch
        self._freeze = freeze

    def submit(self, image_paths: Sequence[str | Path], settings: Mapping[str, Any]) -> str:
        """Freeze the request and enqueue it; returns the job id. Blocking: hashes and probes every input."""

        if self._job_service is None:
            raise RuntimeError("The job queue is not available.")
        spec = self._freeze(build_movie_assembly_intent(image_paths, settings))
        njr = build_movie_assembly_njr(spec, output_dir=self._output_dir)
        job_ids = self._job_service.submit_njrs([njr], SubmissionPolicy())
        if not job_ids:
            raise RuntimeError("The movie assembly job could not be queued.")
        return str(job_ids[0])

    def submit_in_background(
        self,
        image_paths: Sequence[str | Path],
        settings: Mapping[str, Any],
        *,
        on_complete: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Admit on a tracked worker thread; ``on_complete(job_id)`` / ``on_error(message)`` run on the GUI thread."""

        paths = list(image_paths)
        frozen_settings = dict(settings)

        def _report(callback: Callable[[str], None] | None, value: str) -> None:
            if callable(callback):
                if self._dispatch is not None:
                    self._dispatch(lambda: callback(value))
                else:
                    callback(value)

        def _worker() -> None:
            try:
                job_id = self.submit(paths, frozen_settings)
            except MovieAssemblyAdmissionError as exc:
                _report(on_error, str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - every admission failure is reported to the operator
                logger.exception("[movie_clips] Movie assembly admission failed")
                _report(on_error, str(exc) or type(exc).__name__)
                return
            logger.info("[movie_clips] Queued movie assembly job %s", job_id)
            _report(on_complete, job_id)

        if self._spawn is None:
            _worker()
            return
        self._spawn(
            target=_worker,
            name="movie-clip-admission",
            purpose="Freeze and queue a Movie Clips assembly",
        )


__all__ = [
    "MovieClipsSubmissionService",
    "build_movie_assembly_intent",
]

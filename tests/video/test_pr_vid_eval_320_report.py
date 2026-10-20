"""PR-VID-EVAL-320: deterministic clip metrics and the eval contact sheet."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageFilter

from src.pipeline.video import resolve_ffmpeg_executable
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.video_eval_metrics import (
    ClipMeasurement,
    ClipMetrics,
    compute_frame_metrics,
    measure_clip,
)
from src.video.video_eval_report import (
    METRICS_FILE,
    RATINGS_FILE,
    REPORT_FILE,
    baseline_flags,
    build_eval_report,
)
from src.video.video_eval_run import RUN_MANIFEST_NAME, RUN_SCHEMA
from src.video.video_export import export_video_mp4

needs_ffmpeg = pytest.mark.skipif(
    resolve_ffmpeg_executable() is None or resolve_ffprobe_executable() is None,
    reason="FFmpeg/FFprobe is not available",
)


def _stack(values: list[float], size: int = 16) -> np.ndarray:
    return np.stack([np.full((size, size, 3), value, np.float32) for value in values])


# ------------------------------------------------------------------ metrics


def test_static_clip_has_no_motion_jitter_or_drift() -> None:
    metrics = compute_frame_metrics(_stack([0.5] * 10))
    assert metrics["motion"] == 0.0 and metrics["jitter"] == 0.0
    assert metrics["brightness_flicker"] == 0.0 and metrics["color_drift"] == 0.0


def test_frame_alternation_is_pure_jitter_and_steady_change_is_none() -> None:
    alternating = compute_frame_metrics(_stack([0.3, 0.7] * 6))
    steady = compute_frame_metrics(_stack([0.1 + 0.05 * t for t in range(12)]))
    assert alternating["jitter_ratio"] == pytest.approx(1.0)
    assert alternating["brightness_flicker"] == pytest.approx(80.0)
    assert steady["motion"] == pytest.approx(5.0)
    assert steady["jitter_ratio"] == pytest.approx(0.0, abs=1e-6)
    assert steady["brightness_flicker"] == pytest.approx(0.0, abs=1e-4)


def test_losing_detail_lowers_sharpness_retention() -> None:
    rng = np.random.default_rng(7)
    sharp = Image.fromarray((rng.random((48, 48, 3)) * 255).astype(np.uint8))
    blurred = sharp.filter(ImageFilter.GaussianBlur(3))
    frames = np.stack([np.asarray(img, np.float32) / 255.0 for img in [sharp] * 4 + [blurred] * 4])
    metrics = compute_frame_metrics(frames)
    assert metrics["sharpness_retention"] is not None and metrics["sharpness_retention"] < 0.5


def test_too_short_clips_report_none_rather_than_a_number() -> None:
    one = compute_frame_metrics(_stack([0.5]))
    two = compute_frame_metrics(_stack([0.4, 0.6]))
    assert one["motion"] is None and one["color_drift"] is None
    assert two["motion"] is not None and two["jitter"] is None


@needs_ffmpeg
def test_measure_clip_reads_a_real_mp4_through_the_bounded_decoder(tmp_path) -> None:
    frames = [Image.new("RGB", (64, 48), (20 * t, 80, 160)) for t in range(10)]
    path = export_video_mp4(frames=frames, output_path=tmp_path / "clip.mp4", fps=10)

    measurement = measure_clip(path)

    assert measurement.ok, measurement.message
    metrics = measurement.metrics
    assert metrics.frames_measured == 10 and metrics.fps == pytest.approx(10.0)
    assert (metrics.width, metrics.height) == (64, 48)
    assert metrics.motion is not None and metrics.motion > 0
    assert metrics.bitrate_kbps is not None and metrics.file_bytes > 0


def test_measure_clip_reports_a_missing_file_without_raising(tmp_path) -> None:
    measurement = measure_clip(tmp_path / "nope.mp4")
    assert not measurement.ok and measurement.message


# ------------------------------------------------------------------ baseline flags


def test_baseline_flags_mark_frozen_jittery_drifting_and_blurry_clips() -> None:
    base = {
        "motion": 4.0,
        "jitter_ratio": 0.2,
        "brightness_flicker": 0.2,
        "color_drift": 3.0,
        "sharpness_retention": 0.95,
    }
    worse = {
        "motion": 1.0,
        "jitter_ratio": 0.6,
        "brightness_flicker": 1.5,
        "color_drift": 25.0,
        "sharpness_retention": 0.6,
    }
    flags = baseline_flags(worse, base)
    assert len(flags) == 5
    assert baseline_flags(base, base) == ()
    assert baseline_flags(None, base) == () and baseline_flags(worse, None) == ()


# ------------------------------------------------------------------ the report


class _Repository:
    def __init__(self, entries: dict[str, JobHistoryEntry]) -> None:
        self._entries = entries

    def get_job(self, job_id: str):
        return self._entries.get(job_id)


def _entry(
    job_id: str, status: JobStatus, path: Path | None = None, error: str | None = None
) -> JobHistoryEntry:
    result = {"video_bundle": {"primary_path": str(path)}} if path is not None else None
    return JobHistoryEntry(
        job_id=job_id,
        created_at=datetime.now(UTC),
        status=status,
        result=result,
        error_message=error,
    )


def _metrics(motion: float, drift: float = 2.0) -> ClipMetrics:
    return ClipMetrics(
        frames_measured=25,
        reported_frame_count=25,
        truncated=False,
        fps=7.0,
        duration_seconds=3.57,
        width=1024,
        height=576,
        file_bytes=900_000,
        bitrate_kbps=2016.8,
        motion=motion,
        jitter=0.4,
        jitter_ratio=0.2,
        brightness_flicker=0.1,
        color_drift=drift,
        sharpness_retention=0.9,
    )


def _run_dir(tmp_path: Path, prompt: str = "turns <b>slowly</b>") -> Path:
    run_dir = tmp_path / "output" / "video_eval" / "run1"
    run_dir.mkdir(parents=True)
    manifest = {
        "schema": RUN_SCHEMA,
        "run_id": "run1",
        "suite": {"suite_id": "core", "seed": 1, "baseline_arm": "base"},
        "cases": [{"case_id": "portrait", "prompt": prompt}, {"case_id": "wide", "prompt": "pan"}],
        "arms": [
            {"arm_id": "base", "label": "Baseline", "backend": "svd_native"},
            {"arm_id": "cand", "label": "Candidate", "backend": "video_workflow"},
        ],
        "jobs": [
            {"case_id": "portrait", "arm_id": "base", "job_id": "j1"},
            {"case_id": "portrait", "arm_id": "cand", "job_id": "j2"},
            {"case_id": "wide", "arm_id": "base", "job_id": "j3"},
            {"case_id": "wide", "arm_id": "cand", "job_id": "j4"},
        ],
    }
    (run_dir / RUN_MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def _clip(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "clips" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not decoded: the measure function is faked")
    return path


def test_report_measures_finished_clips_flags_against_baseline_and_writes_three_files(
    tmp_path,
) -> None:
    run_dir = _run_dir(tmp_path)
    clips = {name: _clip(tmp_path, f"{name}.mp4") for name in ("j1", "j2", "j3")}
    repository = _Repository(
        {
            "j1": _entry("j1", JobStatus.COMPLETED, clips["j1"]),
            "j2": _entry("j2", JobStatus.COMPLETED, clips["j2"]),
            "j3": _entry("j3", JobStatus.COMPLETED, clips["j3"]),
            "j4": _entry("j4", JobStatus.FAILED, error="CUDA out of memory"),
        }
    )
    by_path = {str(clips["j1"]): 4.0, str(clips["j2"]): 1.0, str(clips["j3"]): 3.0}

    def fake_measure(path, cancel=None):
        return ClipMeasurement(path=path, ok=True, metrics=_metrics(by_path[str(path)]))

    report = build_eval_report(run_dir, repository, measure=fake_measure)

    cells = {(c.case_id, c.arm_id): c for c in report.cells}
    assert cells[("portrait", "cand")].flags == ("less than half the baseline motion",)
    assert cells[("portrait", "base")].flags == ()
    assert (
        cells[("wide", "cand")].state == "failed"
        and "CUDA out of memory" in cells[("wide", "cand")].message
    )
    assert report.measured == 3
    payload = json.loads((run_dir / METRICS_FILE).read_text(encoding="utf-8"))
    assert payload["arm_means"]["base"]["motion"] == pytest.approx(3.5)
    page = (run_dir / REPORT_FILE).read_text(encoding="utf-8")
    assert "<video" in page and clips["j1"].resolve().as_uri() in page
    assert "turns &lt;b&gt;slowly&lt;/b&gt;" in page and "<b>slowly</b>" not in page
    with (run_dir / RATINGS_FILE).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["case_id"], r["arm_id"], r["job_id"]) for r in rows] == [
        ("portrait", "base", "j1"),
        ("portrait", "cand", "j2"),
        ("wide", "base", "j3"),
        ("wide", "cand", "j4"),
    ]


def test_rebuilding_keeps_ratings_already_typed_and_reports_pending_jobs(tmp_path) -> None:
    run_dir = _run_dir(tmp_path)
    clip = _clip(tmp_path, "j1.mp4")
    repository = _Repository(
        {"j1": _entry("j1", JobStatus.COMPLETED, clip), "j2": _entry("j2", JobStatus.QUEUED)}
    )
    measure = lambda path, cancel=None: ClipMeasurement(path=path, ok=True, metrics=_metrics(4.0))  # noqa: E731

    build_eval_report(run_dir, repository, measure=measure)
    ratings = run_dir / RATINGS_FILE
    text = ratings.read_text(encoding="utf-8").replace(
        "portrait,base,j1,,,", "portrait,base,j1,4,achieved,nice turn"
    )
    ratings.write_text(text, encoding="utf-8")

    report = build_eval_report(run_dir, repository, measure=measure)

    assert "portrait,base,j1,4,achieved,nice turn" in ratings.read_text(encoding="utf-8")
    states = {c.job_id: c.state for c in report.cells}
    assert states == {"j1": "playable", "j2": "pending", "j3": "not_found", "j4": "not_found"}
    assert "1 still queued or running" in report.summary()


def test_sfw_mode_hides_prompts_in_the_contact_sheet(tmp_path) -> None:
    run_dir = _run_dir(tmp_path, prompt="explicit prompt text")
    build_eval_report(run_dir, _Repository({}), show_prompts=False)
    page = (run_dir / REPORT_FILE).read_text(encoding="utf-8")
    assert "explicit prompt text" not in page and "hidden in SFW mode" in page


def test_a_folder_without_a_run_manifest_is_refused(tmp_path) -> None:
    from src.video.video_eval_report import EvalReportError

    with pytest.raises(EvalReportError, match="cannot read eval run manifest"):
        build_eval_report(tmp_path, SimpleNamespace(get_job=lambda _id: None))

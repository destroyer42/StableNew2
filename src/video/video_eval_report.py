"""Measure an admitted eval run and write its contact sheet (PR-VID-EVAL-320).

A post-execution consumer. From the run manifest it reads each job through the canonical repository
(``classify_entry``, the same state rules as the experiment review), measures every finished clip with
the bounded decoder, and writes three files next to the manifest:

* ``metrics.json`` (``stablenew.video-eval-report.v1``): every cell's state and measurements;
* ``ratings.csv``: one row per clip for the owner's 1-5 rating, requested-action outcome and notes.
  Rebuilding keeps every rating already typed for the same job;
* ``index.html``: cases as rows, arms as columns, each clip looping beside its numbers.

Flags compare each arm with the suite's baseline arm on the same case. They are guardrails that point at
a clip worth looking at; they never rank arms or pick a winner, and nothing here queues or changes a job.
"""

from __future__ import annotations

import csv
import html
import io
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_json, atomic_write_text
from src.video.video_eval_metrics import ClipMeasurement, measure_clip
from src.video.video_eval_run import RUN_MANIFEST_NAME, RUN_SCHEMA
from src.video.video_review_group import ArmState, classify_entry

REPORT_SCHEMA = "stablenew.video-eval-report.v1"
METRICS_FILE = "metrics.json"
RATINGS_FILE = "ratings.csv"
REPORT_FILE = "index.html"
RATING_COLUMNS = ("case_id", "arm_id", "job_id", "rating_1_to_5", "requested_action", "notes")
REQUESTED_ACTION_VALUES = "achieved | partially_achieved | not_achieved | cannot_assess"
METRIC_KEYS = (
    "motion",
    "jitter_ratio",
    "brightness_flicker",
    "color_drift",
    "sharpness_retention",
)

# (metric, test against the baseline value, operator text). Thresholds are deliberately coarse.
_FLAG_RULES: tuple[tuple[str, Callable[[float, float], bool], str], ...] = (
    (
        "motion",
        lambda value, base: base > 0.2 and value < 0.5 * base,
        "less than half the baseline motion",
    ),
    (
        "jitter_ratio",
        lambda value, base: value > base + 0.15,
        "jerkier frame-to-frame change than the baseline",
    ),
    (
        "brightness_flicker",
        lambda value, base: value > 0.5 and value > 2.0 * base,
        "more brightness flicker than the baseline",
    ),
    ("color_drift", lambda value, base: value > base + 10.0, "more colour drift than the baseline"),
    (
        "sharpness_retention",
        lambda value, base: value < base - 0.15,
        "loses more detail than the baseline",
    ),
)


class EvalReportError(ValueError):
    """The run folder does not hold a readable eval run manifest."""


@dataclass(frozen=True)
class EvalCell:
    case_id: str
    arm_id: str
    job_id: str
    state: str
    message: str
    path: str | None = None
    measurement: ClipMeasurement | None = None
    flags: tuple[str, ...] = ()

    @property
    def metrics(self) -> Mapping[str, Any] | None:
        if self.measurement is None or self.measurement.metrics is None:
            return None
        return self.measurement.metrics.to_dict()


@dataclass(frozen=True)
class EvalReport:
    run_dir: Path
    manifest: Mapping[str, Any]
    cells: tuple[EvalCell, ...] = field(default_factory=tuple)

    @property
    def report_path(self) -> Path:
        return self.run_dir / REPORT_FILE

    @property
    def measured(self) -> int:
        return sum(1 for cell in self.cells if cell.metrics is not None)

    def summary(self) -> str:
        pending = sum(
            1
            for cell in self.cells
            if cell.state in (ArmState.PENDING.value, ArmState.RUNNING.value)
        )
        flagged = sum(1 for cell in self.cells if cell.flags)
        return (
            f"{self.measured} of {len(self.cells)} clips measured, {pending} still queued or running, "
            f"{flagged} flagged against the baseline. Report: {self.report_path}"
        )


def load_run_manifest(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir).expanduser() / RUN_MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalReportError(f"cannot read eval run manifest {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != RUN_SCHEMA:
        raise EvalReportError(f"{path} is not an eval run manifest ({RUN_SCHEMA})")
    if not isinstance(data.get("jobs"), list):
        raise EvalReportError(f"{path} lists no jobs")
    return data


def _measure_cell(
    job: Mapping[str, Any],
    repository: Any,
    measure: Callable[..., ClipMeasurement],
    cancel: threading.Event | None,
) -> EvalCell:
    case_id, arm_id, job_id = str(job["case_id"]), str(job["arm_id"]), str(job["job_id"])
    entry = repository.get_job(job_id)
    if entry is None:
        return EvalCell(case_id, arm_id, job_id, "not_found", "The job is not in the job history.")
    state, message, path = classify_entry(entry)
    if state is not ArmState.PLAYABLE or path is None:
        return EvalCell(case_id, arm_id, job_id, state.value, message, path)
    measurement = measure(path, cancel=cancel)
    if not measurement.ok:
        return EvalCell(
            case_id, arm_id, job_id, "unmeasured", measurement.message, path, measurement
        )
    return EvalCell(case_id, arm_id, job_id, state.value, message, path, measurement)


def baseline_flags(
    metrics: Mapping[str, Any] | None, baseline: Mapping[str, Any] | None
) -> tuple[str, ...]:
    if not metrics or not baseline:
        return ()
    flags: list[str] = []
    for key, test, text in _FLAG_RULES:
        value, base = metrics.get(key), baseline.get(key)
        if (
            isinstance(value, (int, float))
            and isinstance(base, (int, float))
            and test(float(value), float(base))
        ):
            flags.append(text)
    return tuple(flags)


def build_eval_report(
    run_dir: str | Path,
    repository: Any,
    *,
    measure: Callable[..., ClipMeasurement] = measure_clip,
    cancel: threading.Event | None = None,
    show_prompts: bool = True,
) -> EvalReport:
    """Measure every clip of the run that is finished and write metrics, ratings and the contact sheet."""

    folder = Path(run_dir).expanduser()
    manifest = load_run_manifest(folder)
    cells: list[EvalCell] = []
    for job in manifest["jobs"]:
        if cancel is not None and cancel.is_set():
            raise EvalReportError("the report was cancelled")
        cells.append(_measure_cell(job, repository, measure, cancel))
    baseline_arm = str(manifest.get("suite", {}).get("baseline_arm") or "")
    baseline_by_case = {cell.case_id: cell.metrics for cell in cells if cell.arm_id == baseline_arm}
    cells = [
        cell
        if cell.arm_id == baseline_arm
        else EvalCell(
            **{
                **cell.__dict__,
                "flags": baseline_flags(cell.metrics, baseline_by_case.get(cell.case_id)),
            }
        )
        for cell in cells
    ]
    report = EvalReport(run_dir=folder, manifest=manifest, cells=tuple(cells))
    atomic_write_json(folder / METRICS_FILE, report_payload(report), indent=2, sort_keys=True)
    atomic_write_text(
        folder / RATINGS_FILE, ratings_csv(report, _existing_ratings(folder / RATINGS_FILE))
    )
    atomic_write_text(folder / REPORT_FILE, render_html(report, show_prompts=show_prompts))
    return report


def report_payload(report: EvalReport) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "run_id": report.manifest.get("run_id"),
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_arm": report.manifest.get("suite", {}).get("baseline_arm"),
        "cells": [
            {
                "case_id": cell.case_id,
                "arm_id": cell.arm_id,
                "job_id": cell.job_id,
                "state": cell.state,
                "message": cell.message,
                "path": cell.path,
                "metrics": cell.metrics,
                "flags": list(cell.flags),
            }
            for cell in report.cells
        ],
        "arm_means": arm_means(report),
    }


def arm_means(report: EvalReport) -> dict[str, dict[str, float | None]]:
    means: dict[str, dict[str, float | None]] = {}
    for arm in report.manifest.get("arms", []):
        arm_id = str(arm.get("arm_id"))
        rows = [cell.metrics for cell in report.cells if cell.arm_id == arm_id and cell.metrics]
        means[arm_id] = {}
        for key in METRIC_KEYS:
            values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
            means[arm_id][key] = round(sum(values) / len(values), 4) if values else None
    return means


def _existing_ratings(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return {
        (row.get("case_id", ""), row.get("arm_id", ""), row.get("job_id", "")): row
        for row in rows
        if row.get("job_id")
    }


def ratings_csv(
    report: EvalReport, existing: Mapping[tuple[str, str, str], Mapping[str, str]]
) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(RATING_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for cell in report.cells:
        kept = existing.get((cell.case_id, cell.arm_id, cell.job_id), {})
        writer.writerow(
            {
                "case_id": cell.case_id,
                "arm_id": cell.arm_id,
                "job_id": cell.job_id,
                "rating_1_to_5": kept.get("rating_1_to_5", ""),
                "requested_action": kept.get("requested_action", ""),
                "notes": kept.get("notes", ""),
            }
        )
    return buffer.getvalue()


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3g}"
    return str(value)


def _cell_html(cell: EvalCell | None) -> str:
    if cell is None:
        return "<td class='empty'>not in this run</td>"
    esc = html.escape
    parts = [f"<td class='{esc(cell.state)}'>"]
    if cell.metrics is not None and cell.path:
        uri = Path(cell.path).resolve().as_uri()
        parts.append(f"<video src='{esc(uri)}' controls loop muted autoplay playsinline></video>")
        metrics = cell.metrics
        facts = (
            f"{_fmt(metrics.get('width'))}x{_fmt(metrics.get('height'))}, {_fmt(metrics.get('fps'))} fps, "
            f"{_fmt(metrics.get('duration_seconds'))} s, {_fmt(metrics.get('bitrate_kbps'))} kbps"
        )
        parts.append(f"<div class='facts'>{esc(facts)}</div>")
        parts.append("<table class='m'>")
        for key in METRIC_KEYS:
            parts.append(f"<tr><th>{esc(key)}</th><td>{esc(_fmt(metrics.get(key)))}</td></tr>")
        parts.append("</table>")
        if metrics.get("truncated"):
            parts.append(
                f"<div class='note'>measured the first {esc(_fmt(metrics.get('frames_measured')))} frames</div>"
            )
    else:
        parts.append(f"<div class='state'>{esc(cell.state)}</div><div>{esc(cell.message)}</div>")
    for flag in cell.flags:
        parts.append(f"<div class='flag'>&#9873; {esc(flag)}</div>")
    parts.append(f"<div class='job'>job {esc(cell.job_id)}</div></td>")
    return "".join(parts)


_STYLE = """
body{font-family:system-ui,Segoe UI,sans-serif;margin:16px;color:#1d1d1f;background:#fafafa}
table.grid{border-collapse:collapse}
table.grid>tbody>tr>td,table.grid>thead>tr>th,table.grid>tbody>tr>th{border:1px solid #ccc;padding:6px;vertical-align:top}
table.grid>tbody>tr>th{max-width:220px;text-align:left;font-weight:normal}
video{width:280px;display:block;background:#000}
.facts,.job,.note{font-size:11px;color:#666}
table.m{font-size:11px;border-collapse:collapse}table.m th{text-align:left;font-weight:normal;padding-right:8px}
.flag{color:#a33;font-size:12px;margin-top:4px}
.state{font-weight:bold}
td.failed,td.missing,td.unmeasured,td.not_found{background:#fbecec}
td.pending,td.running{background:#f4f4f4}
.caveat{font-size:12px;color:#555;max-width:900px}
"""


def render_html(report: EvalReport, *, show_prompts: bool = True) -> str:
    esc = html.escape
    manifest = report.manifest
    suite = manifest.get("suite", {})
    arms = manifest.get("arms", [])
    cases = manifest.get("cases", [])
    by_key = {(cell.case_id, cell.arm_id): cell for cell in report.cells}
    baseline = str(suite.get("baseline_arm") or "")
    out = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>Video eval {esc(str(manifest.get('run_id', '')))}</title><style>{_STYLE}</style></head><body>",
        f"<h1>Video eval: {esc(str(suite.get('suite_id', '')))}</h1>",
        f"<p>Run {esc(str(manifest.get('run_id', '')))}, seed {esc(_fmt(suite.get('seed')))}, "
        f"baseline arm <b>{esc(baseline)}</b>. {esc(report.summary())}</p>",
        "<p class='caveat'>Numbers are guardrails measured on a downscaled preview. High motion does not mean "
        "the requested action happened, and flags only mark a clip worth a look against the baseline. Your "
        f"rating decides: fill in {esc(RATINGS_FILE)} next to this page (rating 1-5, requested_action one of "
        f"{esc(REQUESTED_ACTION_VALUES)}).</p>",
        "<table class='grid'><thead><tr><th>case</th>",
    ]
    for arm in arms:
        marker = " (baseline)" if arm.get("arm_id") == baseline else ""
        out.append(
            f"<th>{esc(str(arm.get('label', '')))}{esc(marker)}<br><small>{esc(str(arm.get('arm_id', '')))} "
            f"[{esc(str(arm.get('backend', '')))}]</small></th>"
        )
    out.append("</tr></thead><tbody>")
    for case in cases:
        prompt = esc(str(case.get("prompt", ""))) if show_prompts else "[prompt hidden in SFW mode]"
        out.append(
            f"<tr><th><b>{esc(str(case.get('case_id', '')))}</b><br><small>{prompt}</small></th>"
        )
        for arm in arms:
            out.append(_cell_html(by_key.get((str(case.get("case_id")), str(arm.get("arm_id"))))))
        out.append("</tr>")
    means = arm_means(report)
    out.append("<tr><th><b>mean</b></th>")
    for arm in arms:
        values = means.get(str(arm.get("arm_id")), {})
        rows = "".join(
            f"<tr><th>{esc(k)}</th><td>{esc(_fmt(values.get(k)))}</td></tr>" for k in METRIC_KEYS
        )
        out.append(f"<td><table class='m'>{rows}</table></td>")
    out.append("</tr></tbody></table></body></html>")
    return "".join(out)


__all__ = [
    "METRICS_FILE",
    "RATINGS_FILE",
    "RATING_COLUMNS",
    "REPORT_FILE",
    "REPORT_SCHEMA",
    "EvalCell",
    "EvalReport",
    "EvalReportError",
    "arm_means",
    "baseline_flags",
    "build_eval_report",
    "load_run_manifest",
    "ratings_csv",
    "render_html",
    "report_payload",
]

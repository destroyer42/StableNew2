"""Measure an admitted eval run and write its contact sheet (PR-VID-EVAL-320).

A post-execution consumer. From the run manifest it reads each job through the canonical repository
(``classify_entry``, the same state rules as the experiment review), measures every finished clip with
the bounded decoder, and writes three files next to the manifest:

* ``metrics.json`` (``stablenew.video-eval-report.v1``): every cell's state and measurements;
* ``ratings.csv``: one row per clip for the owner's rating, requested-action outcome, identity and continuity
  judgments and notes, bound to the SHA-256 of the clip that was reviewed. Rebuilding keeps every row, value
  and unknown column already there (``src/video/video_eval_ratings_store.py``);
* ``index.html``: cases as rows, arms as columns, each clip looping beside its numbers, the verified source
  image of its case, the operator's ratings and the baseline-relative identity assessment
  (``src/video/video_eval_assessment.py``).

Flags compare each arm with the suite's baseline arm on the same case. They are guardrails that point at
a clip worth looking at; they never rank arms or pick a winner, and nothing here queues or changes a job.
Identity is judged by the operator, never inferred from these numbers.
"""

from __future__ import annotations

import html
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_bytes
from src.video import video_eval_assessment_html as assess_html
from src.video.video_eval_assessment import (
    Assessment,
    CellInput,
    assessment_payload,
    project_assessment,
)
from src.video.video_eval_identity import (
    ArtifactUnhashable,
    EvalCancelled,
    JobFacts,
    SourceReference,
    SourceStatus,
    hash_artifact,
    read_job_facts,
    verify_cell_identity,
    verify_source,
)
from src.video.video_eval_metrics import ClipMeasurement, measure_clip
from src.video.video_eval_ratings_store import (
    RATING_COLUMNS,
    LoadedRatings,
    RatingsFileError,
    load_ratings,
    merge_rows,
    output_header,
    row_key,
    write_ratings,
)
from src.video.video_eval_rubric import ACTION_KEYS
from src.video.video_eval_run import RUN_MANIFEST_NAME, RUN_SCHEMA
from src.video.video_review_group import ArmState, classify_entry

REPORT_SCHEMA = "stablenew.video-eval-report.v1"
METRICS_FILE = "metrics.json"
RATINGS_FILE = "ratings.csv"
REPORT_FILE = "index.html"
REQUESTED_ACTION_VALUES = " | ".join(ACTION_KEYS)
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
    #: SHA-256 of the recorded clip bytes now, or ``None`` when there is no clip or it cannot be hashed.
    artifact_sha256: str | None = None
    artifact_bytes: int | None = None
    hash_problem: str = ""
    facts: JobFacts | None = field(default=None, repr=False, compare=False)

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
    sources: Mapping[str, SourceReference] = field(default_factory=dict)
    assessment: Assessment | None = None
    #: Ratings rows as written (digest-stamped); the assessment is projected from exactly these.
    ratings: Mapping[tuple[str, str, str], Mapping[str, str]] = field(default_factory=dict)
    #: Where the pre-351 ratings.csv was copied if this build converted its layout.
    recovery_copy: Path | None = None

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
        text = (
            f"{self.measured} of {len(self.cells)} clips measured, {pending} still queued or running, "
            f"{flagged} flagged against the baseline."
        )
        if self.assessment is not None:
            text += f" Identity review: {self.assessment.readiness.value}."
        return f"{text} Report: {self.report_path}"


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
    facts = read_job_facts(getattr(entry, "snapshot", None))
    state, message, path = classify_entry(entry)
    if state is not ArmState.PLAYABLE or path is None:
        return EvalCell(case_id, arm_id, job_id, state.value, message, path, facts=facts)
    measurement = measure(path, cancel=cancel)
    digest: str | None = None
    size: int | None = None
    problem = ""
    try:
        digest, size = hash_artifact(path, cancel=cancel)
    except ArtifactUnhashable as exc:
        problem = str(exc)
    if not measurement.ok:
        return EvalCell(
            case_id,
            arm_id,
            job_id,
            "unmeasured",
            measurement.message,
            path,
            measurement,
            artifact_sha256=digest,
            artifact_bytes=size,
            hash_problem=problem,
            facts=facts,
        )
    return EvalCell(
        case_id,
        arm_id,
        job_id,
        state.value,
        message,
        path,
        measurement,
        artifact_sha256=digest,
        artifact_bytes=size,
        hash_problem=problem,
        facts=facts,
    )


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


def _cell_inputs(
    manifest: Mapping[str, Any], cells: list[EvalCell], sources: Mapping[str, SourceReference]
) -> list[CellInput]:
    cases = {str(c.get("case_id")): c for c in manifest.get("cases", []) if isinstance(c, Mapping)}
    arms = {str(a.get("arm_id")): a for a in manifest.get("arms", []) if isinstance(a, Mapping)}
    jobs = {str(j.get("job_id")): j for j in manifest["jobs"] if isinstance(j, Mapping)}
    suite_seed = (manifest.get("suite") or {}).get("seed")
    inputs: list[CellInput] = []
    for cell in cells:
        source = sources.get(cell.case_id)
        metrics = cell.metrics
        duration = metrics.get("duration_seconds") if metrics else None
        inputs.append(
            CellInput(
                case_id=cell.case_id,
                arm_id=cell.arm_id,
                job_id=cell.job_id,
                job_state=cell.state,
                clip_available=metrics is not None and cell.artifact_sha256 is not None,
                measured=metrics is not None,
                duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
                current_sha256=cell.artifact_sha256,
                identity=verify_cell_identity(
                    facts=cell.facts,
                    job=jobs.get(cell.job_id, {}),
                    case=cases.get(cell.case_id, {}),
                    arm=arms.get(cell.arm_id, {}),
                    suite_seed=suite_seed,
                    source=source,
                ),
                flags=cell.flags,
                source_available=source is not None and source.status is not SourceStatus.MISSING,
            )
        )
    return inputs


def _publish(path: Path, text: str, *, parse_json: bool = False) -> None:
    """Atomic write, then read it back; a file that does not read back is an error, not a success."""

    data = text.encode("utf-8")  # bytes, so a newline inside a note is not rewritten as CRLF
    try:
        atomic_write_bytes(path, data)
        written = path.read_bytes()
    except OSError as exc:
        raise EvalReportError(f"{path.name} could not be written: {exc}") from exc
    try:
        same = json.loads(written) == json.loads(data) if parse_json else written == data
    except ValueError:
        same = False
    if not same:
        raise EvalReportError(f"{path.name} did not read back as written")


def build_eval_report(
    run_dir: str | Path,
    repository: Any,
    *,
    measure: Callable[..., ClipMeasurement] = measure_clip,
    cancel: threading.Event | None = None,
    show_prompts: bool = True,
) -> EvalReport:
    """Measure every finished clip of the run and write metrics, ratings and the contact sheet.

    Read-only toward the repository and the media. The only files written are the three report files, plus a
    one-time recovery copy when an older ``ratings.csv`` layout is converted. An unreadable or malformed
    existing ``ratings.csv`` stops the build before anything is written.
    """

    folder = Path(run_dir).expanduser()
    manifest = load_run_manifest(folder)
    try:
        loaded: LoadedRatings = load_ratings(folder / RATINGS_FILE)
    except RatingsFileError as exc:
        raise EvalReportError(str(exc)) from exc
    cancelled = EvalReportError("the report was cancelled")
    try:
        sources: dict[str, SourceReference] = {}
        for case in manifest.get("cases", []):
            if cancel is not None and cancel.is_set():
                raise cancelled
            if isinstance(case, Mapping):
                sources[str(case.get("case_id"))] = verify_source(case, cancel=cancel)
        cells: list[EvalCell] = []
        for job in manifest["jobs"]:
            if cancel is not None and cancel.is_set():
                raise cancelled
            cells.append(_measure_cell(job, repository, measure, cancel))
    except EvalCancelled as exc:
        raise cancelled from exc
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
    merged = merge_rows(
        loaded, [((c.case_id, c.arm_id, c.job_id), c.artifact_sha256) for c in cells]
    )
    ratings = {row_key(row): row for row in merged if row.get("job_id")}
    assessment = project_assessment(manifest, _cell_inputs(manifest, cells, sources), ratings)
    report = EvalReport(
        run_dir=folder,
        manifest=manifest,
        cells=tuple(cells),
        sources=sources,
        assessment=assessment,
        ratings=ratings,
    )
    metrics_text = json.dumps(report_payload(report), indent=2, sort_keys=True)
    page = render_html(report, show_prompts=show_prompts)
    try:
        recovery = write_ratings(loaded, output_header(loaded), merged)
    except RatingsFileError as exc:
        raise EvalReportError(str(exc)) from exc
    _publish(folder / METRICS_FILE, metrics_text, parse_json=True)
    _publish(folder / REPORT_FILE, page)
    return EvalReport(**{**report.__dict__, "recovery_copy": recovery})


def report_payload(report: EvalReport) -> dict[str, Any]:
    assessed = {
        (a.case_id, a.arm_id): a for a in (report.assessment.cells if report.assessment else ())
    }

    def state_of(cell: EvalCell) -> str | None:
        found = assessed.get((cell.case_id, cell.arm_id))
        return found.state.value if found else None

    payload: dict[str, Any] = {
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
                "artifact_sha256": cell.artifact_sha256,
                "artifact_bytes": cell.artifact_bytes,
                "assessment_state": state_of(cell),
            }
            for cell in report.cells
        ],
        "arm_means": arm_means(report),
    }
    if report.assessment is not None:
        payload["identity_assessment"] = {
            **assessment_payload(report.assessment),
            "sources": {
                case_id: {
                    "status": ref.status.value,
                    "message": ref.message,
                    "path": ref.path,
                    "claimed_sha256": ref.claimed_sha256,
                    "current_sha256": ref.current_sha256,
                }
                for case_id, ref in report.sources.items()
            },
        }
    return payload


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


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3g}"
    return str(value)


def _cell_html(cell: EvalCell | None, report: EvalReport, *, show_text: bool) -> str:
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
                f"<div class='note'>measured the first {esc(_fmt(metrics.get('frames_measured')))} frames "
                "of the preview, not the whole clip</div>"
            )
    else:
        parts.append(f"<div class='state'>{esc(cell.state)}</div><div>{esc(cell.message)}</div>")
    for flag in cell.flags:
        parts.append(f"<div class='flag'>&#9873; {esc(flag)}</div>")
    if report.assessment is not None:
        parts.append(
            assess_html.cell_html(
                report.assessment.cell(cell.case_id, cell.arm_id),
                report.assessment.comparison(cell.case_id, cell.arm_id),
                show_text=show_text,
            )
        )
    if cell.artifact_sha256:
        parts.append(f"<div class='job'>sha256 {esc(cell.artifact_sha256[:16])}...</div>")
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
        f"<title>Video eval {esc(str(manifest.get('run_id', '')))}</title>"
        f"<style>{_STYLE}{assess_html.STYLE}</style></head><body>",
        f"<h1>Video eval: {esc(str(suite.get('suite_id', '')))}</h1>",
        f"<p>Run {esc(str(manifest.get('run_id', '')))}, seed {esc(_fmt(suite.get('seed')))}, "
        f"baseline arm <b>{esc(baseline)}</b>. {esc(report.summary())}</p>",
        "<p class='caveat'>Numbers are guardrails measured on a downscaled preview. High motion does not mean "
        "the requested action happened, and flags only mark a clip worth a look against the baseline. Your "
        f"ratings decide: fill in {esc(RATINGS_FILE)} next to this page (requested_action one of "
        f"{esc(REQUESTED_ACTION_VALUES)}; the scored identity and continuity columns are explained in the "
        "rubric below). Rebuild the report to see your entries here.</p>",
    ]
    if report.assessment is not None:
        out.append(assess_html.summary_html(report.assessment))
        out.append(assess_html.rubric_html())
        out.append(assess_html.caveats_html(show_text=show_prompts))
    out.append("<table class='grid'><thead><tr><th>case</th>")
    for arm in arms:
        marker = " (baseline)" if arm.get("arm_id") == baseline else ""
        out.append(
            f"<th>{esc(str(arm.get('label', '')))}{esc(marker)}<br><small>{esc(str(arm.get('arm_id', '')))} "
            f"[{esc(str(arm.get('backend', '')))}]</small></th>"
        )
    out.append("</tr></thead><tbody>")
    for case in cases:
        case_id = str(case.get("case_id", ""))
        prompt = esc(str(case.get("prompt", ""))) if show_prompts else "[prompt hidden in SFW mode]"
        out.append(f"<tr><th><b>{esc(case_id)}</b><br>")
        if report.assessment is not None:
            out.append(
                assess_html.source_html(report.sources.get(case_id), show_media=show_prompts)
            )
        out.append(f"<small>{prompt}</small></th>")
        for arm in arms:
            out.append(
                _cell_html(
                    by_key.get((case_id, str(arm.get("arm_id")))), report, show_text=show_prompts
                )
            )
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
    "render_html",
    "report_payload",
]

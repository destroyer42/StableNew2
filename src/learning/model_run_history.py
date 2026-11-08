"""Per-checkpoint summary of past queue jobs, for display in the Model Evidence Catalog.

Read-only and observational: it counts what already ran through the canonical queue (completed, failed, cancelled),
the settings those completed runs used, and the most frequent failure messages. It never recommends a setting, never
feeds ``RecommendationEngine``, proposals, publication or Apply (Learning invariant 5: observational evidence is
manual-only), and it never writes the repository. Error text is shortened and stripped of filesystem paths.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.image_backends.model_readiness_probe import checkpoint_key

#: Stages whose ``model`` names the checkpoint the job generated with.
_GENERATION_STAGES = ("txt2img", "img2img")
_SETTING_FIELDS = ("sampler_name", "scheduler", "steps", "cfg_scale")
_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s'\"]*[\\/][^\s'\"]*")
_MAX_ERROR = 140
_TOP = 3


@dataclass(frozen=True)
class RunRow:
    """The few columns of one repository job this summary needs (no prompt, no output path)."""

    status: str
    created_at: str | None
    completed_at: str | None
    njr_snapshot: str
    error_message: str | None


@dataclass(frozen=True)
class ModelRunSummary:
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    active: int = 0
    last_run: str = ""
    #: field -> most frequent values among completed runs, as ``(value, count)``.
    settings: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = ()
    resolution: tuple[tuple[str, int], ...] = ()
    errors: tuple[tuple[str, int], ...] = ()

    @property
    def total(self) -> int:
        return self.completed + self.failed + self.cancelled + self.active

    def runs_label(self) -> str:
        if not self.total:
            return "none"
        return f"{self.completed} ok / {self.failed} failed"

    def verdict(self) -> str:
        """A plain description of what history shows; not a qualification or quality claim."""
        if not self.total:
            return "No jobs in history for this checkpoint."
        attempts = self.completed + self.failed
        if self.completed and not self.failed:
            return f"Ran {self.completed} times through the queue without a failure."
        if not self.completed and self.failed:
            return f"Never completed: {self.failed} failed attempts."
        if attempts and self.failed / attempts >= 0.5:
            return f"Unreliable: {self.failed} of {attempts} attempts failed."
        return f"Usually runs: {self.completed} completed, {self.failed} failed."

    def describe(self) -> list[str]:
        lines = [self.verdict()]
        if self.total:
            lines.append(
                f"Jobs: {self.completed} completed, {self.failed} failed, {self.cancelled} cancelled"
                + (f", {self.active} queued/running" if self.active else "")
                + (f"; last run {self.last_run}" if self.last_run else "")
                + "."
            )
        for name, values in self.settings:
            if values:
                lines.append(
                    f"  {name} used: " + ", ".join(f"{value} ({count})" for value, count in values)
                )
        if self.resolution:
            lines.append(
                "  size used: "
                + ", ".join(f"{value} ({count})" for value, count in self.resolution)
            )
        for message, count in self.errors:
            lines.append(f"  failure x{count}: {message}")
        return lines


@dataclass
class _Tally:
    statuses: Counter[str] = field(default_factory=Counter)
    last_run: str = ""
    settings: dict[str, Counter[str]] = field(
        default_factory=lambda: {name: Counter() for name in _SETTING_FIELDS}
    )
    resolution: Counter[str] = field(default_factory=Counter)
    errors: Counter[str] = field(default_factory=Counter)


def _generation_stage(snapshot: Mapping[str, Any]) -> Mapping[str, Any] | None:
    job = (
        snapshot.get("normalized_job")
        if isinstance(snapshot.get("normalized_job"), dict)
        else snapshot
    )
    stages = job.get("stages") if isinstance(job, dict) else None
    if not isinstance(stages, list):
        return None
    for stage in stages:
        if (
            isinstance(stage, dict)
            and stage.get("stage_type") in _GENERATION_STAGES
            and isinstance(stage.get("model"), str)
            and stage["model"].strip()
        ):
            return stage
    return None


def _resolution(snapshot: Mapping[str, Any]) -> str:
    job = snapshot.get("normalized_job")
    workload = job.get("workload") if isinstance(job, dict) else None
    config = workload.get("config") if isinstance(workload, dict) else None
    if not isinstance(config, dict):
        return ""
    width, height = config.get("width"), config.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return f"{width}x{height}"
    return ""


def clean_error(message: str | None) -> str:
    """One line, no filesystem paths, bounded length."""
    text = " ".join(str(message or "").split())
    text = _PATH.sub("<path>", text)
    return text if len(text) <= _MAX_ERROR else text[: _MAX_ERROR - 1] + "…"


def _day(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return datetime.fromtimestamp(float(value), UTC).date().isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            return ""


def summarize_runs(
    rows: Iterable[RunRow], *, cancelled: Callable[[], bool] = lambda: False
) -> dict[str, ModelRunSummary]:
    """Group jobs by ``checkpoint_key`` of the generating stage's model; unparseable rows are skipped."""
    tallies: dict[str, _Tally] = {}
    for index, row in enumerate(rows):
        if index % 512 == 0 and cancelled():
            raise InterruptedError("Run history summary cancelled")
        try:
            snapshot = json.loads(row.njr_snapshot)
        except (TypeError, ValueError):
            continue
        if not isinstance(snapshot, dict):
            continue
        stage = _generation_stage(snapshot)
        if stage is None:
            continue
        key = checkpoint_key(stage["model"])
        if not key:
            continue
        tally = tallies.setdefault(key, _Tally())
        status = str(row.status or "")
        tally.statuses[status] += 1
        day = _day(row.completed_at or row.created_at)
        if day > tally.last_run:
            tally.last_run = day
        if status == "completed":
            for name in _SETTING_FIELDS:
                value = stage.get(name)
                if isinstance(value, bool) or value in (None, ""):
                    continue
                if isinstance(value, (int, float, str)):
                    tally.settings[name][str(value)] += 1
            size = _resolution(snapshot)
            if size:
                tally.resolution[size] += 1
        elif status == "failed":
            message = clean_error(row.error_message)
            if message:
                tally.errors[message] += 1
    return {
        key: ModelRunSummary(
            completed=tally.statuses["completed"],
            failed=tally.statuses["failed"],
            cancelled=tally.statuses["cancelled"],
            active=tally.statuses["queued"] + tally.statuses["running"],
            last_run=tally.last_run,
            settings=tuple(
                (name, tuple(counter.most_common(_TOP))) for name, counter in tally.settings.items()
            ),
            resolution=tuple(tally.resolution.most_common(_TOP)),
            errors=tuple(tally.errors.most_common(_TOP)),
        )
        for key, tally in tallies.items()
    }


def read_run_history(
    repository: Any, *, cancelled: Callable[[], bool] = lambda: False, window: int = 2000
) -> dict[str, ModelRunSummary]:
    """Page through the repository with its bounded read-only windows, then summarize."""

    def rows() -> Iterable[RunRow]:
        cursor: int | None = None
        while True:
            if cancelled():
                raise InterruptedError("Run history summary cancelled")
            page = repository.read_run_evidence_page(before_cursor=cursor, window=window)
            yield from page.rows
            if page.exhausted:
                return
            cursor = page.next_cursor

    return summarize_runs(rows(), cancelled=cancelled)

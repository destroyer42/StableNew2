"""The driver clip of the "Follow a driving video" task (V1-3): read it, fit the length, prepare it.

Presentation glue over the Tk-free ``src.video.driver_intent`` functions and the existing Prepare Motion Source panel.
The clip (and the source image's orientation) is read on a worker owned by the ``ThreadRegistry``; the result returns to
the Tk thread through ``TkUiDispatcher`` and is dropped when the operator chose something else meanwhile.  The window is
trimmed by the existing preparation, started here and re-started when the driver, the length or the engine changes; once
the operator edits that window by hand (under Advanced) it is left alone.  Nothing here queues or builds a job.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.utils.thread_registry import get_thread_registry
from src.video.driver_intent import DriverPlan, driver_seconds, plan_driver_clip, working_cover
from src.video.motion_intent import length_policy

READING = "Reading the driving video..."
PREPARING = "Preparing the driving video..."
_EXIF_ORIENTATION = 274


@dataclass(frozen=True)
class DriverInputs:
    """What the tab's form holds now (read on the Tk thread)."""

    active: bool  # the follow-a-driver task
    clip_path: str
    source_path: str
    record: Mapping[str, Any]
    batch: bool = False


@dataclass(frozen=True)
class _Reading:
    clip: str
    source: str
    facts: Any
    problem: str
    orientation: str


def source_orientation(path: str) -> str:
    """The displayed orientation of the source image, or ``""`` when it cannot be read (worker-thread safe)."""

    if not path:
        return ""
    try:
        with Image.open(Path(path).expanduser()) as image:
            width, height = image.size
            if image.getexif().get(_EXIF_ORIENTATION) in (5, 6, 7, 8):
                width, height = height, width
    except (OSError, ValueError, SyntaxError):
        return ""
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


class DriverClipHost:
    """One driver at a time.  ``choose`` is the operator picking a clip; ``replan`` follows any other change."""

    def __init__(
        self,
        widget: tk.Misc,
        *,
        read_inputs: Callable[[], DriverInputs],
        inspect: Callable[[str], Any],
        prep_panel: Any,
        apply_frames: Callable[[int], None],
        on_change: Callable[[], None],
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        self._widget = widget
        self._read_inputs = read_inputs
        self._inspect = inspect
        self._prep_panel = prep_panel
        self._apply_frames = apply_frames
        self._on_change = on_change
        self._runner = runner
        self._token = 0
        self._clip = ""
        self._reading: _Reading | None = None
        self._pending: tuple[str, str] | None = None
        self._plan: DriverPlan | None = None
        self._prepared_key: tuple[Any, ...] | None = None
        self._new_clip = False
        self._applying = False  # applying a plan writes the form, which asks to replan
        self.requested_seconds: float | None = None  # None: the whole movement
        self.manual_window = False
        prep_panel.on_operator_edit = self._window_edited

    # ------------------------------------------------------------------ operator choices

    @property
    def plan(self) -> DriverPlan | None:
        return self._plan

    @property
    def engaged(self) -> bool:
        return bool(self._clip)

    def choose(self, clip_path: str) -> None:
        """The operator picked a driver (Browse, the Motion Library, a typed path): start at its beginning."""

        clip = str(clip_path or "").strip()
        if clip != self._clip:
            self._clip, self._reading, self._plan, self._prepared_key = clip, None, None, None
            self._new_clip, self.manual_window = True, False
        self.replan()

    def engage(self) -> None:
        """Take over the clip the form already holds (a re-run or a restore), keeping its window start."""

        clip = self._read_inputs().clip_path.strip()
        if clip and clip != self._clip:
            self._clip, self._reading, self._plan, self._prepared_key = clip, None, None, None
            self._new_clip = False
        self.replan()

    def set_duration(self, seconds: float | None) -> None:
        """The operator chose a duration (``None``: the whole movement)."""

        self.requested_seconds = seconds
        self.engage()

    def release(self) -> None:
        """The task no longer follows a driver."""

        self._token += 1
        self._clip, self._reading, self._pending = "", None, None
        self._plan, self._prepared_key, self.requested_seconds = None, None, None
        self.manual_window = False

    def _window_edited(self) -> None:
        self.manual_window = True
        self._prepared_key = None
        self._on_change()

    # ------------------------------------------------------------------ state

    def block_reason(self) -> str:
        """Why Queue should wait for this panel's own work, or an empty string."""

        inputs = self._read_inputs()
        if not inputs.active or not self._clip or inputs.clip_path.strip() != self._clip:
            return ""
        if self._pending is not None:
            return READING
        view = self._prep_panel.last_view
        if view is not None and view.state == "running":
            return PREPARING
        return ""

    def status(self) -> str:
        """The one line under the driver field."""

        if not self._clip:
            return ""
        if self._pending is not None:
            return READING
        if self._plan is None:
            return ""
        parts = [self._plan.line]
        reading = self._reading
        if reading is not None and reading.problem:
            parts.append(
                f"The driver could not be read ({reading.problem}); it is used as it is, without trimming or "
                "speed conversion."
            )
            return " · ".join(parts)
        if self.manual_window:
            parts.append("window set by hand under Advanced")
        elif reading is not None and not _can_convert(reading.facts):
            parts.append("variable or unknown frame rate: kept at the clip's own timing")
        view = self._prep_panel.last_view
        if view is not None:
            if view.state == "running":
                parts.append(PREPARING)
            elif view.state == "ready" and not view.stale:
                parts.append("ready")
            elif view.state in ("error", "cancelled") or view.stale:
                parts.append(view.status)
        return " · ".join(parts)

    # ------------------------------------------------------------------ planning (Tk thread)

    def replan(self) -> None:
        """Bring the length and the prepared clip in line with the form.  Cheap when nothing changed."""

        if self._applying:
            return
        inputs = self._read_inputs()
        if not inputs.active or not self._clip or inputs.clip_path.strip() != self._clip:
            return
        key = (self._clip, inputs.source_path.strip())
        reading = self._reading
        if reading is None or (reading.clip, reading.source) != key:
            if self._pending != key:
                self._start_reading(key)
            return
        self._applying = True
        try:
            self._apply(inputs, reading)
        finally:
            self._applying = False

    def _apply(self, inputs: DriverInputs, reading: _Reading) -> None:
        record = inputs.record
        policy = length_policy(record.get("frame_count"))
        if policy is None:
            return
        window = driver_seconds(reading.facts)
        start = 0.0 if self._new_clip else _seconds(self._prep_panel.start_var.get())
        if window is not None:
            window = max(0.0, window - start)
        self._plan = plan_driver_clip(self.requested_seconds, policy, window)
        self._apply_frames(self._plan.frames)
        self._prepare(inputs, reading, self._plan)
        self._on_change()

    def _prepare(self, inputs: DriverInputs, reading: _Reading, plan: DriverPlan) -> None:
        if self.manual_window or reading.facts is None:
            if reading.facts is None:
                self._prepared_key = None
                self._prep_panel.drop()  # nothing of an earlier driver may travel with this one
            return
        readiness = inputs.record.get("motion_readiness") or {}
        consumption = readiness.get("driving_frame_consumption") or {}
        if not consumption.get("verified"):
            return  # the engine offers no preparation: the clip is used as it always was
        cover = working_cover(
            readiness.get("source_preparation"),
            "" if inputs.batch else reading.orientation,
        )
        convert = _can_convert(reading.facts)
        key = (
            self._clip,
            inputs.record.get("workflow_id"),
            inputs.record.get("workflow_version"),
            plan.frames,
            cover,
            convert,
        )
        if key == self._prepared_key:
            return
        self._prepared_key = key
        self._prep_panel.cover = cover
        start = "0" if self._new_clip else None
        self._new_clip = False
        self._prep_panel.prepare_automatically(convert=convert, start=start)

    # ------------------------------------------------------------------ off-thread reading

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self._widget)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Read a driving video for the Video Workflow tab without blocking Tk",
                ),
                dispatch=lambda fn: dispatcher.invoke(lambda: self._deliver(fn)),
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        try:
            if self._widget.winfo_exists():
                finish()
        except tk.TclError:
            pass  # the tab is going away

    def _start_reading(self, key: tuple[str, str]) -> None:
        self._token += 1
        token = self._token
        self._pending = key
        clip, source = key
        inspect = self._inspect

        def work() -> WorkOutcome:
            inspection = inspect(clip)
            facts = getattr(inspection, "facts", None)
            problem = ""
            if facts is None:
                issues = getattr(inspection, "issues", ()) or ()
                problem = issues[0].message if issues else "no video information"
            return WorkOutcome(
                value=_Reading(clip, source, facts, problem, source_orientation(source))
            )

        self._on_change()
        self._work_runner().start(
            "video-driver-read", work, lambda outcome: self._finish_reading(token, key, outcome)
        )

    def _finish_reading(self, token: int, key: tuple[str, str], outcome: WorkOutcome) -> None:
        if token != self._token:
            return  # superseded by a newer choice
        self._pending = None
        reading = outcome.value
        if outcome.error or not isinstance(reading, _Reading):
            reading = _Reading(key[0], key[1], None, outcome.error or "it could not be read", "")
        self._reading = reading
        self.replan()
        self._on_change()


def _can_convert(facts: Any) -> bool:
    return bool(getattr(facts, "reported_fps", None)) and not getattr(
        facts, "fps_is_variable_suspected", False
    )


def _seconds(text: Any) -> float:
    try:
        value = float(str(text).strip() or 0)
    except ValueError:
        return 0.0
    return max(0.0, value)


__all__ = ["PREPARING", "READING", "DriverClipHost", "DriverInputs", "source_orientation"]

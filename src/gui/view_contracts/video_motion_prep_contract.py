"""Toolkit-neutral state for the Video Workflow "Prepare Motion Source" panel (PR-VID-MOTION-210).

Preparation is optional and explicit.  The session holds one transient result of the operator's
last "Prepare" action and decides what the submission form carries:

* nothing (the clip is used exactly as before) while the operator has not prepared, or after "Use
  original video";
* the prepared record while a *current* preparation is ready;
* a blocker (a readable reason) while a preparation is running, failed, was cancelled or has gone
  out of date -- a job is never admitted with a silent fallback to the unprepared clip.

It owns no generation authority: the preparation itself is an injected callable run on a worker
(the Video Workflow controller delegates to ``prepare_motion_source``), it builds no payload, touches
no queue and names no workflow or model.  A result for a superseded or cleared request is discarded
by a generation token, and a running preparation is cancelled by its own ``threading.Event``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.gui.view_contracts.video_motion_readiness_contract import FrameThumb

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_READY = "ready"
STATE_ERROR = "error"
STATE_CANCELLED = "cancelled"

# Form keys understood by ``VideoWorkflowNjrBuilder`` (kept as literals: this module imports nothing
# from the video or controller layers beyond the outcome type's attribute names).
PREPARED_FIELD = "prepared_motion_source"
BLOCKED_FIELD = "motion_source_preparation_blocked"

_KEY_LABELS = (
    "workflow",
    "workflow version",
    "length",
    "driving video",
    "start",
    "end",
    "frame-rate conversion",
)


@dataclass(frozen=True)
class PrepInputs:
    """A plain snapshot of what the panel reads from the form (Tk reads happen before this)."""

    available: bool
    unavailable_reason: str = ""
    workflow_id: str = ""
    workflow_version: str = ""
    frame_count: int | None = None
    output_fps: int | None = None
    clip_path: str = ""
    start_text: str = ""
    end_text: str = ""
    convert: bool = False

    def key(self) -> tuple[Any, ...]:
        return (
            self.workflow_id,
            self.workflow_version,
            self.frame_count,
            self.clip_path.strip(),
            self.start_text.strip(),
            self.end_text.strip(),
            bool(self.convert),
        )


@dataclass(frozen=True)
class PreparationWork:
    token: int
    form: dict[str, Any]
    request: dict[str, Any]
    cancel: threading.Event = field(default_factory=threading.Event, compare=False)


@dataclass(frozen=True)
class MotionPrepView:
    """Everything the panel renders, as plain data (no Tk, no PIL)."""

    state: str
    available: bool
    visible: bool
    status: str
    using: str
    identity_lines: tuple[str, ...]
    explanation_lines: tuple[str, ...]
    frames: tuple[FrameThumb, ...]
    can_prepare: bool
    can_cancel: bool
    can_clear: bool
    stale: bool
    fps_label: str


def _number(text: str, label: str) -> float | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number of seconds, for example 1.5.") from exc
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise ValueError(f"{label} must be zero or more seconds.")
    return value


def _short(sha: Any) -> str:
    return str(sha or "")[:12]


def _megabytes(size: Any) -> str:
    try:
        return f"{int(size) / (1024 * 1024):.1f} MB"
    except (TypeError, ValueError):
        return "unknown size"


class MotionPreparationSession:
    """State machine behind the panel; see the module docstring for the contract."""

    def __init__(
        self, *, prepare: Callable[[Mapping[str, Any], Mapping[str, Any], threading.Event], Any]
    ) -> None:
        self._prepare = prepare
        self._inputs = PrepInputs(available=False)
        self._token = 0
        self._state = STATE_IDLE
        self._inflight: PreparationWork | None = None
        self._attempt_key: tuple[Any, ...] | None = None
        self._outcome: Any = None
        self._message = ""

    # ------------------------------------------------------------------ inputs (UI thread)

    @property
    def state(self) -> str:
        return self._state

    @property
    def busy(self) -> bool:
        return self._inflight is not None

    def refresh(self, inputs: PrepInputs) -> None:
        """Adopt the current form; failures and results for other inputs stop applying."""

        self._inputs = inputs
        if not inputs.available:
            if self._state != STATE_IDLE:
                self.clear()
            return
        if self._state in (STATE_ERROR, STATE_CANCELLED) and inputs.key() != self._attempt_key:
            self._state, self._message, self._outcome = STATE_IDLE, "", None

    def _stale_names(self) -> list[str]:
        if self._attempt_key is None:
            return []
        current = self._inputs.key()
        return [
            label
            for label, then, now in zip(_KEY_LABELS, self._attempt_key, current, strict=True)
            if then != now
        ]

    @property
    def stale(self) -> bool:
        return self._state == STATE_READY and bool(self._stale_names())

    def begin(self, inputs: PrepInputs) -> PreparationWork | None:
        """Start preparing; None when it cannot start (the reason is in the view)."""

        self._inputs = inputs
        if self._inflight is not None:
            return None
        self._attempt_key = inputs.key()
        self._outcome = None
        try:
            if not inputs.available:
                raise ValueError(inputs.unavailable_reason or "Preparation is not available.")
            if not inputs.clip_path.strip():
                raise ValueError("Select a driving video first.")
            if not inputs.frame_count:
                raise ValueError("Choose the number of frames first.")
            start = _number(inputs.start_text, "Start")
            end = _number(inputs.end_text, "End")
            if end is not None and end <= (start or 0.0):
                raise ValueError("End must be after Start.")
        except ValueError as exc:
            self._state, self._message = STATE_ERROR, str(exc)
            return None
        self._token += 1
        work = PreparationWork(
            token=self._token,
            form={
                "workflow_id": inputs.workflow_id,
                "workflow_version": inputs.workflow_version,
                "frame_count": inputs.frame_count,
                "pose_video_path": inputs.clip_path.strip(),
            },
            request={
                "start": start or 0.0,
                "end": end,
                "unit": "seconds",
                "fps_conversion": "workflow_rate" if inputs.convert else "none",
            },
        )
        self._inflight, self._state, self._message = work, STATE_RUNNING, ""
        return work

    def cancel(self) -> None:
        if self._inflight is not None:
            self._inflight.cancel.set()
            self._message = "Cancelling..."

    def clear(self) -> None:
        """Use the original video again; a running preparation is cancelled and its result dropped."""

        self._token += 1
        if self._inflight is not None:
            self._inflight.cancel.set()
            self._inflight = None
        self._state, self._message, self._outcome, self._attempt_key = STATE_IDLE, "", None, None

    def close(self) -> None:
        self.clear()

    # ------------------------------------------------------------------ worker thread

    def run(self, work: PreparationWork) -> WorkOutcome:
        try:
            return WorkOutcome(value=self._prepare(work.form, work.request, work.cancel))
        except (OSError, ValueError, RuntimeError, LookupError, TypeError) as exc:
            # Anything else is reported by ``BackgroundWorkRunner``, which always calls back.
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    # ------------------------------------------------------------------ completion (UI thread)

    def finish(self, work: PreparationWork, outcome: WorkOutcome) -> None:
        """Apply a result only when it is for the request that is still current."""

        if work.token != self._token:
            return  # cleared or superseded meanwhile: the result no longer applies
        self._inflight = None
        value = outcome.value
        if outcome.error or value is None:
            self._state, self._message = STATE_ERROR, outcome.error or "Preparation failed."
            return
        self._outcome = value
        status = getattr(value, "status", "")
        if status == "prepared" and getattr(value, "record", None):
            self._state, self._message = STATE_READY, str(getattr(value, "message", "") or "")
        elif status == "cancelled":
            self._state, self._message = STATE_CANCELLED, "Preparation was cancelled."
            self._outcome = None
        else:
            self._state = STATE_ERROR
            self._message = str(getattr(value, "message", "") or "Preparation failed.")
            self._outcome = None

    # ------------------------------------------------------------------ what the form carries

    def submission_fields(self) -> dict[str, Any]:
        """The extra form keys for a submission: the record, a blocker, or nothing."""

        if not self._inputs.available:
            return {}
        if self._state == STATE_RUNNING:
            return {
                BLOCKED_FIELD: "Motion source preparation is still running. Wait for it to "
                "finish, cancel it, or choose 'Use original video'."
            }
        if self._state in (STATE_ERROR, STATE_CANCELLED):
            what = "was cancelled" if self._state == STATE_CANCELLED else f"failed: {self._message}"
            return {
                BLOCKED_FIELD: f"Motion source preparation {what} Prepare it again, or choose "
                "'Use original video'."
            }
        if self._state == STATE_READY:
            names = self._stale_names()
            if names:
                return {
                    BLOCKED_FIELD: "The prepared motion source is out of date (changed: "
                    + ", ".join(names)
                    + "). Prepare it again, or choose 'Use original video'."
                }
            record = getattr(self._outcome, "record", None)
            return {PREPARED_FIELD: record} if record else {}
        return {}

    # ------------------------------------------------------------------ projection

    def view(self) -> MotionPrepView:
        inputs = self._inputs
        state = self._state
        stale = self.stale
        identity: list[str] = []
        explanation: list[str] = []
        frames: list[FrameThumb] = []
        if state == STATE_READY and self._outcome is not None:
            record = self._outcome.record
            original, derived = record["original"], record["derived"]
            contract = record["contract"]
            identity = [
                f"Original: {original['width']}x{original['height']}, "
                f"{original.get('frame_count') or '?'} frames at {original.get('frame_rate') or '?'} fps, "
                f"sha256 {_short(original['sha256'])}",
                f"Prepared: {derived['width']}x{derived['height']}, {derived['frames']} frames at "
                f"{derived['frame_rate']} fps, {_megabytes(derived.get('size_bytes'))}, "
                f"sha256 {_short(derived['sha256'])} (lossless, content-addressed)",
                f"Enters: {contract['workflow_id']} {contract['workflow_version']} as its driving "
                "video. The job reads the prepared file, not the original.",
            ]
            explanation = list(getattr(self._outcome, "explanation", ()) or ())
            preview = getattr(self._outcome, "preview", None)
            captions = tuple(getattr(self._outcome, "preview_captions", ()) or ())
            for position, frame in enumerate(getattr(preview, "frames", ()) or ()):
                caption = (
                    captions[position]
                    if position < len(captions)
                    else f"{frame.position_seconds:.2f} s"
                )
                frames.append(FrameThumb(frame.png_bytes, caption))
        if not inputs.available:
            status = inputs.unavailable_reason or "This workflow takes no driving video."
        elif state == STATE_RUNNING:
            status = self._message or "Preparing the motion source..."
        elif state == STATE_ERROR:
            status = f"Preparation failed: {self._message}"
        elif state == STATE_CANCELLED:
            status = "Preparation was cancelled. Nothing was kept."
        elif stale:
            status = (
                "Out of date (changed: " + ", ".join(self._stale_names()) + "). Prepare again, or "
                "choose 'Use original video'."
            )
        elif state == STATE_READY:
            status = self._message or "Prepared."
        else:
            status = "Not prepared: the whole driving video is used exactly as before."
        if state == STATE_READY and not stale:
            using = "Using: the prepared motion source shown below."
        else:
            using = "Using: the original driving video (unprepared)."
        return MotionPrepView(
            state=state,
            available=inputs.available,
            visible=inputs.available or bool(inputs.unavailable_reason),
            status=status,
            using=using,
            identity_lines=tuple(identity),
            explanation_lines=tuple(explanation),
            frames=tuple(frames),
            can_prepare=inputs.available and state != STATE_RUNNING,
            can_cancel=state == STATE_RUNNING,
            can_clear=state != STATE_IDLE,
            stale=stale,
            fps_label=(
                f"Convert to {inputs.output_fps} fps (nearest frame)"
                if inputs.output_fps
                else "Convert to the workflow's frame rate (nearest frame)"
            ),
        )


__all__ = [
    "BLOCKED_FIELD",
    "PREPARED_FIELD",
    "STATE_CANCELLED",
    "STATE_ERROR",
    "STATE_IDLE",
    "STATE_READY",
    "STATE_RUNNING",
    "MotionPrepView",
    "MotionPreparationSession",
    "PrepInputs",
    "PreparationWork",
]

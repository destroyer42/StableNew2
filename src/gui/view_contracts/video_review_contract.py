"""Toolkit-neutral state for the Video Experiment Review window (PR-VID-QUALITY-211).

Two pieces, neither of which imports Tk:

``ComparisonClock``
    One clock for the whole comparison.  Position is an integer step on a grid of ``1 / max(fps)``
    seconds, so stepping never skips a frame of either clip.  A clip with a lower frame rate repeats
    frames; a clip that is shorter is held on its final frame.  Playback speed is never changed to make
    clips "line up", and every such difference is reported by ``notes()``.

``VideoReviewSession``
    The window's view-model: which experiment is loaded, the selected A-D pair, the per-clip preview
    slots, the editable review forms and their saved/dirty/failed status.  It performs no I/O: loading,
    decoding and saving are injected callables the window runs on a worker, split (like the PR-VID-194
    session) into ``begin_*`` (UI thread, claims state), ``run_*`` (worker, touches no session state) and
    ``finish_*`` (UI thread, ignored when the work went stale because the window was closed, the review
    reloaded or the selection changed).

Nothing here queues, retries, repairs or scores anything.  The tested value of an arm is shown exactly as
recorded; there is no winner, only an optional operator-recorded manual preference.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.view_contracts.video_experiment_contract import WorkOutcome, format_value
from src.learning.video_quality_review import (
    ACTION_OUTCOME_VALUES,
    DIMENSION_KEYS,
    SAVED,
    UNCHANGED,
    ClipReviewDraft,
    ReviewValidationError,
    SavedClipReview,
)
from src.video.review_preview import PreviewClip, PreviewResult, describe_preview
from src.video.video_review_group import (
    SUPPORTED_VIDEO_SUFFIXES,
    ArmState,
    ReviewArm,
    ReviewGroup,
)

PLAYBACK_TICK_MS = 40
LABEL_VALUE_CHARS = 48


def _shorten(text: str, limit: int = LABEL_VALUE_CHARS) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


#: What injected load/decode/save callables may raise for a reason the operator can act on (a refused group, a
#: bad draft, a failed write, a cancelled load, an unreadable file).  Anything else is a defect: it is not hidden
#: here, and ``BackgroundWorkRunner`` still reports it to the window so the review never hangs.
WORKER_ERRORS = (ValueError, RuntimeError, OSError, LookupError, TypeError)


# ---------------------------------------------------------------------------------------- clock


@dataclass(frozen=True)
class ClipTiming:
    label: str
    frame_count: int
    fps: float
    fps_assumed: bool = False
    reported_frame_count: int | None = None


class ComparisonClock:
    """One position, one rate: the common time base for two (or one) preview clips."""

    def __init__(self) -> None:
        self._timings: tuple[ClipTiming, ...] = ()
        self._step = 1.0 / 24.0
        self._steps = 1
        self.position = 0
        self.playing = False
        self._origin_time = 0.0
        self._origin_position = 0

    # ------------------------------------------------------------------ configuration

    def configure(self, timings: Sequence[ClipTiming]) -> None:
        """Adopt the timing of the clips on screen; position and playback restart from the beginning."""

        self._timings = tuple(
            timing for timing in timings if timing.frame_count > 0 and timing.fps > 0
        )
        if self._timings:
            fastest = max(timing.fps for timing in self._timings)
            longest = max(timing.frame_count / timing.fps for timing in self._timings)
            self._step = 1.0 / fastest
            self._steps = max(1, math.ceil(longest * fastest - 1e-9))
        else:
            self._step, self._steps = 1.0 / 24.0, 1
        self.position = 0
        self.playing = False

    @property
    def steps(self) -> int:
        return self._steps

    @property
    def last_position(self) -> int:
        return self._steps - 1

    @property
    def seconds(self) -> float:
        return self.position * self._step

    @property
    def duration_seconds(self) -> float:
        return self._steps * self._step

    # ------------------------------------------------------------------ frames

    def frame_index(self, timing: ClipTiming, position: int | None = None) -> int:
        """Preview frame shown for ``timing`` at ``position``: its own rate, held on its final frame."""

        at = (self.position if position is None else position) * self._step
        return max(0, min(timing.frame_count - 1, int(math.floor(at * timing.fps + 1e-9))))

    def is_held(self, timing: ClipTiming) -> bool:
        """True once the clip has ended and is only being held on its final frame."""

        return self.seconds * timing.fps >= timing.frame_count - 1e-9

    # ------------------------------------------------------------------ transport

    def seek(self, position: int) -> None:
        self.position = max(0, min(self.last_position, int(position)))
        self._origin_position = self.position
        self._origin_time = 0.0

    def step(self, delta: int) -> None:
        self.playing = False
        self.seek(self.position + int(delta))

    def restart(self) -> None:
        self.seek(0)

    def play(self, now: float) -> None:
        if self.position >= self.last_position:
            self.position = 0
        self.playing = True
        self._origin_time = now
        self._origin_position = self.position

    def pause(self) -> None:
        self.playing = False

    def tick(self, now: float) -> bool:
        """Advance by real elapsed time; returns True when the position changed. Stops at the end."""

        if not self.playing:
            return False
        advanced = self._origin_position + int((now - self._origin_time) / self._step)
        target = min(advanced, self.last_position)
        changed = target != self.position
        self.position = target
        if target >= self.last_position:
            self.playing = False
        return changed

    # ------------------------------------------------------------------ disclosure

    def notes(self) -> list[str]:
        """Plain statements of every way the clips differ; empty when they match exactly."""

        notes: list[str] = []
        timings = self._timings
        if len(timings) == 2:
            a, b = timings
            if abs(a.fps - b.fps) > 1e-6:
                notes.append(
                    f"{a.label} runs at {a.fps:g} fps and {b.label} at {b.fps:g} fps. Playback keeps real time "
                    f"and steps by 1/{max(a.fps, b.fps):g} s, so the slower clip repeats frames; no speed is "
                    "changed."
                )
            if (
                a.frame_count != b.frame_count
                or abs(a.frame_count / a.fps - b.frame_count / b.fps) > 1e-6
            ):
                shorter = a if a.frame_count / a.fps < b.frame_count / b.fps else b
                notes.append(
                    f"{shorter.label} is shorter ({shorter.frame_count} preview frames); it is held on its final "
                    "frame until the longer clip ends."
                )
        for timing in timings:
            if timing.fps_assumed:
                notes.append(
                    f"{timing.label} reports no frame rate; {timing.fps:g} fps is assumed for timing."
                )
            if (
                timing.reported_frame_count is not None
                and timing.frame_count < timing.reported_frame_count
            ):
                notes.append(
                    f"The {timing.label} preview holds only the first {timing.frame_count} of "
                    f"{timing.reported_frame_count} frames. Open the original to see the rest."
                )
        return notes

    def position_text(self, timings: Sequence[ClipTiming] | None = None) -> str:
        shown = self._timings if timings is None else tuple(timings)
        parts = [f"t = {self.seconds:.3f} s of {self.duration_seconds:.3f} s"]
        for timing in shown:
            index = self.frame_index(timing)
            held = " (held)" if self.is_held(timing) else ""
            parts.append(f"{timing.label} frame {index + 1}/{timing.frame_count}{held}")
        return "   ".join(parts)


# ---------------------------------------------------------------------------------------- forms


@dataclass
class ReviewForm:
    """What the operator has typed for one clip (strings, exactly as in the widgets)."""

    overall: str = ""
    outcome: str = ""
    dimensions: dict[str, str] = field(default_factory=lambda: dict.fromkeys(DIMENSION_KEYS, ""))
    notes: str = ""

    def snapshot(self) -> tuple[Any, ...]:
        return (
            self.overall.strip(),
            self.outcome.strip(),
            tuple((key, self.dimensions.get(key, "").strip()) for key in DIMENSION_KEYS),
            self.notes.strip(),
        )

    def to_draft(self) -> ClipReviewDraft:
        return ClipReviewDraft(
            overall_rating=self.overall.strip() or None,
            action_outcome=self.outcome.strip() or None,
            dimensions={
                key: value.strip() for key, value in self.dimensions.items() if value.strip()
            },
            notes=self.notes,
        )

    @classmethod
    def from_saved(cls, saved: SavedClipReview) -> ReviewForm:
        draft = saved.draft
        return cls(
            overall=str(draft.overall_rating),
            outcome=str(draft.action_outcome),
            dimensions={key: str(dict(draft.dimensions).get(key, "")) for key in DIMENSION_KEYS},
            notes=str(draft.notes),
        )


FORM_FIELDS = ("overall", "outcome", "notes", *DIMENSION_KEYS)


@dataclass
class PreviewSlot:
    job_id: str
    token: int
    cancel: threading.Event
    state: str = "loading"  # loading | ready | failed
    clip: PreviewClip | None = None
    message: str = ""


@dataclass(frozen=True)
class LoadWork:
    token: int
    job_id: str
    cancel: threading.Event


@dataclass(frozen=True)
class PreviewWork:
    token: int
    load_token: int
    job_id: str
    path: str
    cancel: threading.Event


@dataclass(frozen=True)
class SaveWork:
    token: int
    load_token: int
    job_id: str  # "" for the group preference
    draft: ClipReviewDraft | None
    group: ReviewGroup
    preferred_job_id: str | None = None
    reason: str = ""


class VideoReviewSession:
    """View-model for one review window (no Tk, no I/O)."""

    def __init__(
        self,
        *,
        load: Callable[[str, threading.Event], Any],
        prepare_preview: Callable[[str, threading.Event], PreviewResult],
        save_clip: Callable[[ReviewGroup, str, ClipReviewDraft], Any],
        save_preference: Callable[[ReviewGroup, str | None, str], Any],
        file_exists: Callable[[str], bool],
        clock: ComparisonClock | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._load = load
        self._prepare_preview = prepare_preview
        self._save_clip = save_clip
        self._save_preference = save_preference
        self._file_exists = file_exists
        self._on_change = on_change
        self.clock = clock or ComparisonClock()
        self.closed = False
        self.loaded: Any = None  # LoadedReview | None
        self.status = "Enter a job id from a Video Workflow experiment and press Load."
        self.busy_loading = False
        self.pair: tuple[str | None, str | None] = (None, None)
        self.forms: dict[str, ReviewForm] = {}
        self._baseline: dict[str, tuple[Any, ...]] = {}
        self.messages: dict[str, str] = {}
        self.saving: set[str] = set()
        self.preference_job: str | None = None
        self.preference_reason = ""
        self._pref_baseline: tuple[Any, ...] = (None, "")
        self.preference_message = ""
        self._slots: dict[str, PreviewSlot] = {}
        self._token = 0
        self._load_token = 0
        self._load_cancel = threading.Event()
        self._clock_timings: tuple[ClipTiming, ...] = ()

    # ------------------------------------------------------------------ plumbing

    def _changed(self) -> None:
        if self._on_change is not None and not self.closed:
            self._on_change()

    def _next_token(self) -> int:
        self._token += 1
        return self._token

    @property
    def group(self) -> ReviewGroup | None:
        return self.loaded.group if self.loaded is not None else None

    def arm(self, job_id: str | None) -> ReviewArm | None:
        group = self.group
        return group.arm_for_job(job_id) if group is not None and job_id else None

    def close(self) -> None:
        """Cancel every outstanding decode/load and drop all frame memory; later results are ignored."""

        self.closed = True
        self._load_cancel.set()
        for slot in self._slots.values():
            slot.cancel.set()
        self._slots.clear()
        self.clock.pause()

    # ------------------------------------------------------------------ loading

    def begin_load(self, job_id: str) -> LoadWork | None:
        text = str(job_id or "").strip()
        if self.closed:
            return None
        if not text:
            self.status = "Enter a job id to review."
            self._changed()
            return None
        self._load_cancel.set()  # supersede any load still running
        self._drop_slots()
        self._load_cancel = threading.Event()
        self._load_token += 1
        self.busy_loading = True
        self.status = f"Loading experiment for job {text}..."
        self._changed()
        return LoadWork(token=self._load_token, job_id=text, cancel=self._load_cancel)

    def run_load(self, work: LoadWork) -> WorkOutcome:
        try:
            return WorkOutcome(value=self._load(work.job_id, work.cancel))
        except WORKER_ERRORS as exc:  # the service explains why in operator language
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    def finish_load(self, work: LoadWork, outcome: WorkOutcome) -> bool:
        if self.closed or work.token != self._load_token:
            return False  # a newer load replaced this one, or the window is gone
        self.busy_loading = False
        if outcome.error:
            self.loaded = None
            self.pair = (None, None)
            self.forms.clear()
            self._baseline.clear()
            self.clock.configure(())
            self.status = f"Cannot review: {outcome.error}"
            self._changed()
            return False
        self.loaded = outcome.value
        group = self.group
        assert group is not None
        stored = self.loaded.stored
        self.forms, self._baseline, self.messages = {}, {}, {}
        for arm in group.arms:
            saved = stored.clip_for(arm.job_id, arm.artifact_sha256) if arm.playable else None
            form = ReviewForm.from_saved(saved) if saved is not None else ReviewForm()
            self.forms[arm.job_id] = form
            self._baseline[arm.job_id] = form.snapshot()
            if saved is not None:
                self.messages[arm.job_id] = f"Saved review, revision {saved.revision}."
        preference = stored.preference
        self.preference_job = None
        self.preference_reason = ""
        self.preference_message = ""
        if preference is not None and preference.preferred_job_id:
            preferred_arm = group.arm_for_job(preference.preferred_job_id)
            if (
                preferred_arm is not None
                and preferred_arm.playable
                and preferred_arm.artifact_sha256 == preference.preferred_artifact_sha256
            ):
                self.preference_job = preferred_arm.job_id
                self.preference_reason = preference.reason
                self.preference_message = (
                    f"Saved manual preference, revision {preference.revision}."
                )
            else:
                self.preference_message = "A saved preference refers to a clip that is no longer the same file; it is not applied."
        self._pref_baseline = (self.preference_job, self.preference_reason.strip())
        playable = [arm.job_id for arm in group.playable_arms]
        self.pair = (
            playable[0] if playable else None,
            playable[1] if len(playable) > 1 else None,
        )
        self.status = self._load_status(group)
        self._changed()
        return True

    @staticmethod
    def _load_status(group: ReviewGroup) -> str:
        playable = len(group.playable_arms)
        text = f"Experiment {group.experiment_id}: {len(group.arms)} arm(s), {playable} ready to review."
        if group.excluded_job_ids:
            text += f" {len(group.excluded_job_ids)} related replay/other job(s) were not included."
        if len(group.arms) < 2:
            text += " Only one arm was found, so there is nothing to compare."
        return text

    # ------------------------------------------------------------------ pair + previews

    def available_choices(self) -> list[tuple[str, str]]:
        """``(job_id, "A  (value)")`` for every arm that can be put on screen."""

        group = self.group
        if group is None:
            return []
        return [
            (arm.job_id, f"{arm.label}  ({_shorten(format_value(arm.value))})")
            for arm in group.playable_arms
        ]

    def select_pair(self, left: str | None, right: str | None) -> list[PreviewWork]:
        """Choose the compared arms; returns the preview decodes that must start (off the Tk thread)."""

        if self.closed or self.group is None:
            return []
        playable = {arm.job_id for arm in self.group.playable_arms}
        left = left if left in playable else None
        right = right if right in playable and right != left else None
        self.pair = (left, right)
        wanted = {job for job in (left, right) if job}
        for job_id in list(self._slots):
            if job_id not in wanted:
                self._slots.pop(job_id).cancel.set()  # stale selection: stop it and free its frames
        work: list[PreviewWork] = []
        for candidate in (left, right):
            if not candidate or candidate in self._slots:
                continue
            arm = self.arm(candidate)
            if arm is None or not arm.artifact_path:
                continue
            cancel = threading.Event()
            token = self._next_token()
            self._slots[candidate] = PreviewSlot(job_id=candidate, token=token, cancel=cancel)
            work.append(
                PreviewWork(
                    token=token,
                    load_token=self._load_token,
                    job_id=candidate,
                    path=arm.artifact_path,
                    cancel=cancel,
                )
            )
        self._reconfigure_clock()
        self._changed()
        return work

    def run_preview(self, work: PreviewWork) -> WorkOutcome:
        try:
            return WorkOutcome(value=self._prepare_preview(work.path, work.cancel))
        except WORKER_ERRORS as exc:  # decoding must never escape as an exception into the window
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    def finish_preview(self, work: PreviewWork, outcome: WorkOutcome) -> bool:
        slot = self._slots.get(work.job_id)
        if (
            self.closed
            or work.load_token != self._load_token
            or slot is None
            or slot.token != work.token
            or work.cancel.is_set()
        ):
            return False  # selection changed, review reloaded or window closed: discard the frames
        if outcome.error:
            slot.state, slot.message = "failed", f"Preview failed: {outcome.error}"
        else:
            result: PreviewResult = outcome.value
            if result.ok and result.clip is not None:
                slot.state, slot.clip, slot.message = (
                    "ready",
                    result.clip,
                    describe_preview(result.clip),
                )
            else:
                slot.state, slot.message = (
                    "failed",
                    result.message or "Preview could not be prepared.",
                )
        self._reconfigure_clock()
        self._changed()
        return True

    def slot(self, job_id: str | None) -> PreviewSlot | None:
        return self._slots.get(job_id) if job_id else None

    def _drop_slots(self) -> None:
        for slot in self._slots.values():
            slot.cancel.set()
        self._slots.clear()

    def _timings(self) -> list[tuple[str, ClipTiming]]:
        timings: list[tuple[str, ClipTiming]] = []
        for job_id in self.pair:
            slot = self.slot(job_id)
            arm = self.arm(job_id)
            if slot is None or slot.clip is None or arm is None:
                continue
            clip = slot.clip
            timings.append(
                (
                    job_id or "",
                    ClipTiming(
                        label=arm.label,
                        frame_count=clip.frame_count,
                        fps=clip.effective_fps,
                        fps_assumed=clip.fps_is_assumed,
                        reported_frame_count=clip.reported_frame_count,
                    ),
                )
            )
        return timings

    def _reconfigure_clock(self) -> None:
        current = tuple(timing for _job, timing in self._timings())
        if current != self._clock_timings:
            self._clock_timings = current
            self.clock.configure(current)

    def timing_for(self, job_id: str | None) -> ClipTiming | None:
        return next((timing for job, timing in self._timings() if job == job_id), None)

    # ------------------------------------------------------------------ forms

    def set_field(self, job_id: str, name: str, value: str) -> None:
        form = self.forms.get(job_id)
        if form is None or name not in FORM_FIELDS or self.closed:
            return
        if name == "overall":
            form.overall = str(value)
        elif name == "outcome":
            form.outcome = str(value)
        elif name == "notes":
            form.notes = str(value)
        else:
            form.dimensions[name] = str(value)
        self._changed()

    def is_dirty(self, job_id: str) -> bool:
        form = self.forms.get(job_id)
        return form is not None and form.snapshot() != self._baseline.get(job_id)

    def can_review(self, job_id: str | None) -> bool:
        arm = self.arm(job_id)
        return arm is not None and arm.playable and bool(arm.artifact_sha256)

    # ------------------------------------------------------------------ saving

    def begin_save(self, job_id: str) -> SaveWork | None:
        if self.closed or self.group is None:
            return None
        if not self.can_review(job_id):
            self.messages[job_id] = "This arm has no completed, identified video to review."
            self._changed()
            return None
        if job_id in self.saving:
            return None
        form = self.forms.get(job_id)
        if form is None:
            return None
        try:
            draft = form.to_draft().validate()
        except ReviewValidationError as exc:
            self.messages[job_id] = f"Not saved: {exc}"
            self._changed()
            return None
        self.saving.add(job_id)
        self.messages[job_id] = "Saving..."
        self._changed()
        return SaveWork(self._next_token(), self._load_token, job_id, draft, self.group)

    def run_save(self, work: SaveWork) -> WorkOutcome:
        try:
            if work.draft is None:
                return WorkOutcome(
                    value=self._save_preference(work.group, work.preferred_job_id, work.reason)
                )
            return WorkOutcome(value=self._save_clip(work.group, work.job_id, work.draft))
        except WORKER_ERRORS as exc:  # ReviewSaveError and friends: reported, edits kept
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    def finish_save(self, work: SaveWork, outcome: WorkOutcome) -> bool:
        if work.draft is None:
            return self._finish_preference(work, outcome)
        self.saving.discard(work.job_id)
        if self.closed or work.load_token != self._load_token:
            return False
        if outcome.error:
            # Never "Saved": the form stays dirty so the operator can retry without retyping.
            self.messages[work.job_id] = f"Save FAILED, your edits are kept: {outcome.error}"
            self._changed()
            return False
        result = outcome.value
        if result.status == SAVED:
            self._baseline[work.job_id] = self.forms[work.job_id].snapshot()
            self.messages[work.job_id] = f"Saved (revision {result.revision})."
        elif result.status == UNCHANGED:
            self._baseline[work.job_id] = self.forms[work.job_id].snapshot()
            self.messages[work.job_id] = "No changes to save."
        else:  # an unknown status is not a success
            self.messages[work.job_id] = (
                f"Save FAILED, your edits are kept: unexpected result {result.status!r}."
            )
        self._changed()
        return True

    # ------------------------------------------------------------------ manual preference

    def set_preference(self, job_id: str | None, reason: str | None = None) -> None:
        if self.closed:
            return
        self.preference_job = job_id if job_id and self.can_review(job_id) else None
        if reason is not None:
            self.preference_reason = reason
        self._changed()

    def preference_dirty(self) -> bool:
        return (self.preference_job, self.preference_reason.strip()) != self._pref_baseline

    def begin_save_preference(self) -> SaveWork | None:
        if self.closed or self.group is None or "" in self.saving:
            return None
        self.saving.add("")
        self.preference_message = "Saving..."
        self._changed()
        return SaveWork(
            self._next_token(),
            self._load_token,
            "",
            None,
            self.group,
            preferred_job_id=self.preference_job,
            reason=self.preference_reason,
        )

    def _finish_preference(self, work: SaveWork, outcome: WorkOutcome) -> bool:
        self.saving.discard("")
        if self.closed or work.load_token != self._load_token:
            return False
        if outcome.error:
            self.preference_message = f"Save FAILED, your edits are kept: {outcome.error}"
            self._changed()
            return False
        result = outcome.value
        if result.status in {SAVED, UNCHANGED}:
            self._pref_baseline = (self.preference_job, self.preference_reason.strip())
            self.preference_message = (
                f"Saved manual preference (revision {result.revision})."
                if result.status == SAVED
                else "No changes to save."
            )
        else:
            self.preference_message = (
                f"Save FAILED, your edits are kept: unexpected result {result.status!r}."
            )
        self._changed()
        return result.status in {SAVED, UNCHANGED}

    # ------------------------------------------------------------------ original file

    def original_path(self, job_id: str | None) -> str | None:
        """The recorded artifact, only while it is still a file (never a guessed or sibling path)."""

        arm = self.arm(job_id)
        if arm is None or not arm.artifact_path:
            return None
        if Path(arm.artifact_path).suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
            return None
        try:
            return arm.artifact_path if self._file_exists(arm.artifact_path) else None
        except OSError:
            return None

    # ------------------------------------------------------------------ presentation rows

    def overview_rows(self, visibility_mode: str | None = None) -> list[tuple[str, str]]:
        """Labelled overview text; prompts and text-valued controls honour the content-visibility mode."""

        group = self.group
        if group is None:
            return []
        resolver = ContentVisibilityResolver(visibility_mode or "nsfw")

        def hide(text: Any) -> str:
            return resolver.redact_text(str(text or ""))

        overview = group.overview
        rows = [
            ("Experiment", f"{hide(group.experiment_name)}  ({group.experiment_id})"),
            ("Tested control", group.variable_name),
            (
                "Workflow",
                f"{overview.workflow_id} v{overview.workflow_version}  [{overview.backend_id}]",
            ),
            ("Shared seed", "n/a" if overview.seed is None else str(overview.seed)),
        ]
        if overview.frame_count is not None:
            fps = f" at {overview.fps:g} fps" if overview.fps else ""
            rows.append(("Frames", f"{overview.frame_count}{fps}"))
        rows.append(("Prompt", hide(overview.prompt)))
        if overview.negative_prompt:
            rows.append(("Negative prompt", hide(overview.negative_prompt)))
        for name, value in overview.fixed_controls.items():
            rows.append((name, hide(format_value(value))))
        rows.append(("Source image", overview.source_image_path or "(none recorded)"))
        if overview.driving_video_path:
            digest = overview.driving_video_sha256[:12]
            rows.append(("Driving video", f"{overview.driving_video_path}  (sha256 {digest})"))
        prepared = overview.motion_source_preparation
        if prepared:
            derived = prepared.get("derived") or {}
            rows.append(
                (
                    "Prepared motion source",
                    f"{derived.get('path', '')}  (sha256 {str(derived.get('sha256') or '')[:12]})",
                )
            )
        return rows

    def arm_value_text(self, arm: ReviewArm, visibility_mode: str | None = None) -> str:
        """The arm's tested value, redacted like a prompt when the visibility mode hides it."""

        return ContentVisibilityResolver(visibility_mode or "nsfw").redact_text(
            format_value(arm.value)
        )

    def arm_rows(self, visibility_mode: str | None = None) -> list[dict[str, str]]:
        group = self.group
        if group is None:
            return []
        resolver = ContentVisibilityResolver(visibility_mode or "nsfw")
        rows = []
        for arm in group.arms:
            value = format_value(arm.value)
            rows.append(
                {
                    "label": arm.label + (" (baseline)" if arm.index == 0 else ""),
                    "value": resolver.redact_text(value),
                    "job_id": arm.job_id,
                    "state": arm.state.value,
                    "state_text": arm.state_text,
                    "artifact": arm.artifact_path or "",
                }
            )
        return rows


def parse_rating_choices() -> tuple[str, ...]:
    return ("", "1", "2", "3", "4", "5")


def outcome_choices() -> list[tuple[str, str]]:
    from src.learning.video_quality_review import ACTION_OUTCOMES

    assert {value for value, _ in ACTION_OUTCOMES} == set(ACTION_OUTCOME_VALUES)
    return list(ACTION_OUTCOMES)


__all__ = [
    "FORM_FIELDS",
    "PLAYBACK_TICK_MS",
    "ArmState",
    "ClipTiming",
    "ComparisonClock",
    "LoadWork",
    "PreviewSlot",
    "PreviewWork",
    "ReviewForm",
    "SaveWork",
    "VideoReviewSession",
    "outcome_choices",
    "parse_rating_choices",
]

"""Toolkit-neutral state of the Motion Review window for a controlled-motion eval run (PR-VID-MOTION-410).

One review shows up to four media at once on **one clock**: the source image, the effective driving reference and two
generated results. It is a view over files the admission and the report already wrote (``load_motion_review``); it builds no
job, rates nothing and starts no runtime.

* Playback reuses the existing ``ComparisonClock``: one real-time position on a grid of ``1 / max(fps)`` seconds, a clip of a
  lower rate repeats frames, a shorter clip is held on its last frame, and every such difference is disclosed. Equal frame
  indices are never treated as equal timestamps, and the first / middle / last comparison is taken at the same *times*.
* Frames are the bounded review previews (``prepare_review_preview``: at most 120 frames at 256 px, cancellable); there is no
  other decode path and no full-resolution decode. "Open original" belongs to the window's injected opener.
* Loading and decoding run on workers. A stale result (the window closed, another run loaded, the selection changed) is
  discarded by token, and a superseded decode is cancelled through its own event.
* Content visibility: the source image and the driving reference are not decoded while the mode hides media, and prompt text
  is redacted through the shared resolver. Nothing plays until the operator presses Play.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.gui.view_contracts.video_review_contract import (
    WORKER_ERRORS,
    ClipTiming,
    ComparisonClock,
)
from src.state.content_visibility import ContentVisibilityMode
from src.video.review_preview import PreviewClip, PreviewResult, describe_preview
from src.video.video_eval_motion_review import (
    ROLE_DRIVER,
    ROLE_SOURCE,
    MotionReviewData,
    ReviewCase,
    ReviewCell,
)

SLOT_SOURCE = "source"
SLOT_DRIVER = "driver"
SLOT_LEFT = "left"
SLOT_RIGHT = "right"
CLIP_SLOTS = (SLOT_DRIVER, SLOT_LEFT, SLOT_RIGHT)
PREVIEW_NOTICE = (
    "Review previews: downscaled, frame-exact samples (at most 120 frames) decoded on the CPU for comparison. They "
    "do not preserve every property of the original; use Open original for full quality."
)


@dataclass
class MediaSlot:
    key: str
    path: str
    token: int
    cancel: threading.Event
    state: str = "loading"  # loading | ready | failed | hidden
    clip: PreviewClip | None = None
    image: Any = None
    message: str = ""


@dataclass(frozen=True)
class LoadWork:
    token: int
    run_dir: str
    cancel: threading.Event


@dataclass(frozen=True)
class MediaWork:
    token: int
    load_token: int
    slot: str
    path: str
    image: bool
    cancel: threading.Event


@dataclass(frozen=True)
class FrameInfo:
    index: int  # zero-based preview frame shown
    total: int
    seconds: float  # that frame's own time stamp
    held: bool  # the clip has ended and is held on its last frame


class MotionReviewSession:
    """View-model of one Motion Review window (no Tk, no I/O of its own)."""

    def __init__(
        self,
        *,
        load: Callable[[str, threading.Event], MotionReviewData],
        prepare_preview: Callable[[str, threading.Event], PreviewResult],
        prepare_image: Callable[[str, threading.Event], Any],
        visibility: Callable[[], str] = lambda: ContentVisibilityMode.NSFW.value,
        file_exists: Callable[[str], bool] = lambda path: Path(path).is_file(),
        on_change: Callable[[], None] | None = None,
        clock: ComparisonClock | None = None,
    ) -> None:
        self._load = load
        self._prepare_preview = prepare_preview
        self._prepare_image = prepare_image
        self._visibility = visibility
        self._file_exists = file_exists
        self._on_change = on_change
        self.clock = clock or ComparisonClock()
        self.closed = False
        self.data: MotionReviewData | None = None
        self.case_id: str | None = None
        self.arms: tuple[str | None, str | None] = (None, None)
        self.status = "Choose a run with driving-motion cases and press Load."
        self.busy_loading = False
        self._slots: dict[str, MediaSlot] = {}
        self._clock_timings: tuple[ClipTiming, ...] = ()
        self._load_token = 0
        self._token = 0
        self._load_cancel = threading.Event()

    # ------------------------------------------------------------------ plumbing

    def _changed(self) -> None:
        if self._on_change is not None and not self.closed:
            self._on_change()

    def _next_token(self) -> int:
        self._token += 1
        return self._token

    @property
    def media_hidden(self) -> bool:
        """Source and driver frames are withheld while the content-visibility mode hides media."""

        return str(self._visibility()).lower() == ContentVisibilityMode.SFW.value

    def redact(self, text: str) -> str:
        return ContentVisibilityResolver(str(self._visibility())).redact_text(text)

    @property
    def case(self) -> ReviewCase | None:
        return self.data.case(self.case_id) if self.data is not None else None

    def cell(self, side: str) -> ReviewCell | None:
        case = self.case
        arm = self.arms[0] if side == SLOT_LEFT else self.arms[1]
        return case.cell(arm) if case is not None else None

    def close(self) -> None:
        """Cancel every outstanding load and decode and drop all frame memory; later results are ignored."""

        self.closed = True
        self._load_cancel.set()
        for slot in self._slots.values():
            slot.cancel.set()
        self._slots.clear()
        self.clock.pause()

    # ------------------------------------------------------------------ loading

    def begin_load(self, run_dir: str) -> LoadWork | None:
        text = str(run_dir or "").strip()
        if self.closed or not text:
            return None
        self._load_cancel.set()  # supersede any load still running
        self._drop_slots()
        self._load_cancel = threading.Event()
        self._load_token += 1
        self.busy_loading = True
        self.status = f"Loading {Path(text).name}..."
        self._changed()
        return LoadWork(self._load_token, text, self._load_cancel)

    def run_load(self, work: LoadWork) -> WorkOutcome:
        try:
            return WorkOutcome(value=self._load(work.run_dir, work.cancel))
        except WORKER_ERRORS as exc:
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    def finish_load(self, work: LoadWork, outcome: WorkOutcome) -> list[MediaWork] | None:
        """Adopt a finished load. ``None`` means the result was stale or failed; otherwise the decodes to start."""

        if self.closed or work.token != self._load_token:
            return None
        self.busy_loading = False
        if outcome.error:
            self.data, self.case_id, self.arms = None, None, (None, None)
            self.clock.configure(())
            self.status = f"Cannot review: {outcome.error}"
            self._changed()
            return None
        self.data = outcome.value
        self.status = f"Run {self.data.run_id}: {len(self.data.cases)} motion case(s)."
        first = self.data.cases[0].case_id if self.data.cases else None
        return self.select_case(first)

    # ------------------------------------------------------------------ selection

    def case_choices(self) -> list[tuple[str, str]]:
        return (
            []
            if self.data is None
            else [(c.case_id, f"{c.case_id}  ({c.category})") for c in self.data.cases]
        )

    def arm_choices(self) -> list[tuple[str, str]]:
        case = self.case
        return (
            []
            if case is None
            else [
                (c.arm_id, f"{c.arm_label}{' (baseline)' if c.is_baseline else ''}")
                for c in case.cells
                if c.playable
            ]
        )

    def select_case(self, case_id: str | None) -> list[MediaWork]:
        chosen = self.data.case(case_id) if self.data is not None else None
        if self.closed or chosen is None:
            return []
        self.case_id = case_id
        playable = [c for c in chosen.cells if c.playable]
        baseline = next((c.arm_id for c in playable if c.is_baseline), None)
        left = baseline or (playable[0].arm_id if playable else None)
        right = next((c.arm_id for c in playable if c.arm_id != left), None)
        return self.select_arms(left, right)

    def select_arms(self, left: str | None, right: str | None) -> list[MediaWork]:
        """Choose the compared results; returns the decodes that must start (off the Tk thread)."""

        case = self.case
        if self.closed or case is None:
            return []
        playable = {c.arm_id for c in case.cells if c.playable}
        left = left if left in playable else None
        right = right if right in playable and right != left else None
        self.arms = (left, right)
        wanted: dict[str, tuple[str, bool]] = {}
        if not self.media_hidden:
            if case.source.path:
                wanted[SLOT_SOURCE] = (case.source.path, True)
            if case.driver.path and self._file_exists(case.driver.path):
                wanted[SLOT_DRIVER] = (case.driver.path, False)
        for slot, arm in ((SLOT_LEFT, left), (SLOT_RIGHT, right)):
            cell = case.cell(arm)
            if cell is not None and cell.clip_path:
                wanted[slot] = (cell.clip_path, False)
        for key in list(self._slots):
            current = self._slots[key]
            if key not in wanted or wanted[key][0] != current.path:
                self._slots.pop(key).cancel.set()  # superseded: stop it and free its frames
        work: list[MediaWork] = []
        for key, (path, is_image) in wanted.items():
            if key in self._slots:
                continue
            cancel = threading.Event()
            token = self._next_token()
            self._slots[key] = MediaSlot(key, path, token, cancel)
            work.append(MediaWork(token, self._load_token, key, path, is_image, cancel))
        self._reconfigure_clock()
        self._changed()
        return work

    def run_media(self, work: MediaWork) -> WorkOutcome:
        try:
            if work.image:
                return WorkOutcome(value=self._prepare_image(work.path, work.cancel))
            return WorkOutcome(value=self._prepare_preview(work.path, work.cancel))
        except WORKER_ERRORS as exc:  # decoding never escapes as an exception into the window
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    def finish_media(self, work: MediaWork, outcome: WorkOutcome) -> bool:
        slot = self._slots.get(work.slot)
        if (
            self.closed
            or work.load_token != self._load_token
            or slot is None
            or slot.token != work.token
            or work.cancel.is_set()
        ):
            return False  # selection changed, run reloaded or window closed: discard the frames
        if outcome.error:
            slot.state, slot.message = "failed", f"Preview failed: {outcome.error}"
        elif work.image:
            slot.state, slot.image = "ready", outcome.value
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

    def slot(self, key: str) -> MediaSlot | None:
        return self._slots.get(key)

    def _drop_slots(self) -> None:
        for slot in self._slots.values():
            slot.cancel.set()
        self._slots.clear()

    # ------------------------------------------------------------------ clock and frames

    def _labels(self) -> dict[str, str]:
        case = self.case
        labels = {SLOT_DRIVER: "driving reference"}
        for key in (SLOT_LEFT, SLOT_RIGHT):
            cell = self.cell(key)
            labels[key] = cell.arm_label if cell is not None else key
        return labels if case is not None else {}

    def timings(self) -> dict[str, ClipTiming]:
        labels = self._labels()
        found: dict[str, ClipTiming] = {}
        for key in CLIP_SLOTS:
            slot = self._slots.get(key)
            if slot is None or slot.clip is None:
                continue
            clip = slot.clip
            found[key] = ClipTiming(
                label=labels.get(key, key),
                frame_count=clip.frame_count,
                fps=clip.effective_fps,
                fps_assumed=clip.fps_is_assumed,
                reported_frame_count=clip.reported_frame_count,
            )
        return found

    def _reconfigure_clock(self) -> None:
        current = tuple(self.timings().values())
        if current != self._clock_timings:
            self._clock_timings = current
            self.clock.configure(current)

    def frame_info(self, key: str, position: int | None = None) -> FrameInfo | None:
        timing = self.timings().get(key)
        if timing is None:
            return None
        index = self.clock.frame_index(timing, position)
        held = (
            self.clock.is_held(timing)
            if position is None
            else (position * (1.0 / max(t.fps for t in self._clock_timings))) * timing.fps
            >= timing.frame_count - 1e-9
        )
        return FrameInfo(index, timing.frame_count, index / timing.fps, held)

    def anchor_positions(self) -> tuple[int, int, int]:
        """First, middle and last clock positions: the same *times* for every clip, not the same frame numbers."""

        last = self.clock.last_position
        return (0, last // 2, last)

    def anchor_frames(self, key: str) -> list[FrameInfo]:
        infos = [self.frame_info(key, position) for position in self.anchor_positions()]
        return [info for info in infos if info is not None]

    def position_text(self) -> str:
        return self.clock.position_text()

    def notes(self) -> list[str]:
        """Every way the shown media differ or fall short, in plain words (empty only when nothing needs saying)."""

        notes: list[str] = []
        timings = self.timings()
        pairs = [(SLOT_DRIVER, SLOT_LEFT), (SLOT_DRIVER, SLOT_RIGHT), (SLOT_LEFT, SLOT_RIGHT)]
        for first, second in pairs:
            if first in timings and second in timings:
                probe = ComparisonClock()
                probe.configure((timings[first], timings[second]))
                notes.extend(probe.notes())
        case = self.case
        if case is not None:
            notes.append(case.driver.note)
            if not case.driver.verified:
                notes.append(
                    "The driving reference shown is not verified as the file the model consumed."
                )
            for key in (SLOT_LEFT, SLOT_RIGHT):
                cell = self.cell(key)
                if cell is not None and cell.integrity not in (
                    "verified_comparable",
                    "verified_with_disclosed_differences",
                ):
                    notes.append(
                        f"{cell.arm_label}: {cell.integrity_label}; rating applicability may be limited."
                    )
            left, right = self.cell(SLOT_LEFT), self.cell(SLOT_RIGHT)
            if (
                left is not None
                and right is not None
                and left.settings_lines != right.settings_lines
            ):
                notes.append(
                    "The two results were generated with different frozen settings (shown beside each)."
                )
        if self.media_hidden:
            notes.append(
                "The source image and driving reference are hidden in SFW mode and were not decoded."
            )
        notes.append(PREVIEW_NOTICE)
        return list(dict.fromkeys(note for note in notes if note))

    # ------------------------------------------------------------------ transport

    def play(self, now: float) -> None:
        self.clock.play(now)
        self._changed()

    def pause(self) -> None:
        self.clock.pause()
        self._changed()

    def step(self, delta: int) -> None:
        self.clock.step(delta)
        self._changed()

    def seek(self, position: int) -> None:
        self.clock.seek(position)
        self._changed()

    def restart(self) -> None:
        self.clock.restart()
        self._changed()

    def tick(self, now: float) -> bool:
        changed = self.clock.tick(now)
        if changed:
            self._changed()
        return changed

    # ------------------------------------------------------------------ presentation rows

    def role_rows(self) -> list[tuple[str, str, str]]:
        """``(role, label, identity note)`` for the three media roles of the selected case."""

        case = self.case
        if case is None:
            return []
        rows = [
            (ROLE_SOURCE, case.source.label, case.source.note),
            (ROLE_DRIVER, case.driver.label, case.driver.note),
        ]
        for key in (SLOT_LEFT, SLOT_RIGHT):
            cell = self.cell(key)
            if cell is not None:
                rows.append(
                    (
                        "result",
                        f"Generated result: {cell.arm_label}",
                        f"{cell.integrity_label}; motion review {cell.motion_state}; "
                        f"clip {str(cell.artifact_sha256 or 'unavailable')[:12]}",
                    )
                )
        return rows

    def case_rows(self) -> list[tuple[str, str]]:
        case = self.case
        if case is None:
            return []
        return [
            ("Motion category", case.category),
            ("Intended action", self.redact(case.action)),
            ("Expected outcome", self.redact(case.expected_outcome)),
            ("Motion prompt", self.redact(case.motion_prompt)),
        ]

    def settings_rows(self, side: str) -> list[str]:
        cell = self.cell(side)
        return [] if cell is None else [*cell.settings_lines, *cell.rating_lines]

    def original_path(self, role_key: str) -> str | None:
        """The file "Open original" hands to the system viewer: recorded paths only, and only while they are files."""

        case = self.case
        if case is None:
            return None
        path: str | None
        if role_key == SLOT_SOURCE:
            path = case.source.original_path
        elif role_key == SLOT_DRIVER:
            path = case.driver.original_path
        else:
            cell = self.cell(role_key)
            path = cell.clip_path if cell is not None else None
        try:
            return path if path and self._file_exists(path) else None
        except OSError:
            return None

    def effective_driver_path(self) -> str | None:
        case = self.case
        return case.driver.path if case is not None else None


def anchor_text(infos: Sequence[FrameInfo]) -> str:
    return "   ".join(
        f"frame {info.index + 1}/{info.total} at {info.seconds:.2f} s{' (held)' if info.held else ''}"
        for info in infos
    )


__all__ = [
    "CLIP_SLOTS",
    "PREVIEW_NOTICE",
    "ROLE_DRIVER",
    "SLOT_DRIVER",
    "SLOT_LEFT",
    "SLOT_RIGHT",
    "SLOT_SOURCE",
    "FrameInfo",
    "LoadWork",
    "MediaSlot",
    "MediaWork",
    "MotionReviewSession",
    "anchor_text",
]

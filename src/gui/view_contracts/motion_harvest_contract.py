"""Toolkit-neutral state of the Harvest Motion workspace (PR-VID-MOTION-400).

One session per open workspace.  It imports no Tk and starts no process of its own:

* every hash, probe, decode and FFmpeg call is an injected port that the injected ``BackgroundWorkRunner`` runs on a
  worker; results return on the UI thread through the runner and are **dropped** when a newer request of the same kind
  superseded them or the workspace closed (a per-kind token), and a superseded request is cancelled through its own
  event, so rapid source, seek or window changes never show an obsolete frame or window;
* the window arithmetic is the pure ``harvest_window`` module (frames ``[start, end)``, exact rational rates);
* nothing here builds a job, queues, starts a runtime or edits the Video Workflow form.  The only thing that writes is
  the explicit ``save`` command, which asks the injected port to run the offline harvest.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.video.motion_library.harvest import HarvestOutcome, HarvestRequest
from src.video.motion_library.harvest_service import (
    FramePreview,
    HarvestSourceInfo,
    HarvestSourceRef,
    representative_frames,
)
from src.video.motion_library.harvest_window import (
    CadencePlan,
    WindowError,
    end_after_frame,
    plan_cadence,
    rate_label,
    resolve_window,
    timecode,
)
from src.video.motion_library.models import (
    CADENCE_NATIVE,
    CADENCE_NORMALIZED_24,
    CADENCES,
    LINEAGE_NONE,
    LINEAGE_PATH_ONLY,
    LINEAGE_RECORDED,
    LINEAGE_VERIFIED,
)

LINEAGE_TEXT = {
    LINEAGE_VERIFIED: "Originating job verified (History names this file and its SHA-256 matches).",
    LINEAGE_RECORDED: "Originating job recorded by History; the bytes are not independently verified.",
    LINEAGE_PATH_ONLY: "Originating job not established (the file's location is all that is known).",
    LINEAGE_NONE: "No originating job is claimed.",
}
CADENCE_LABELS = {
    CADENCE_NATIVE: "Keep the source frame rate (recommended)",
    CADENCE_NORMALIZED_24: "Convert to 24 fps",
}
UNITS = ("frames", "seconds")
HIDDEN_NOTE = (
    "This video is hidden by the current content filter, so it is not opened or previewed. Change the content "
    "visibility setting to harvest from it."
)
TRUNCATED_PLAYBACK_NOTE = (
    "Playback uses the shared bounded preview and may not show the whole video. The window, frame numbers and the "
    "frame previews below are exact; they do not depend on playback."
)


@dataclass(frozen=True)
class HarvestPorts:
    """The calls the session needs (all worker-safe)."""

    open_source: Callable[[HarvestSourceRef, threading.Event], HarvestSourceInfo]
    preview: Callable[
        [str, Sequence[int], Fraction | None, threading.Event, str],
        tuple[tuple[FramePreview, ...], tuple[str, ...]],
    ]
    harvest: Callable[[HarvestRequest, threading.Event], HarvestOutcome]
    #: ``(window_frames, rate, convert) -> lines``; pure and cheap, called on the UI thread.  ``None``: no preview.
    workflow_timing: Callable[[int, Fraction | None, bool], tuple[str, ...]] | None = None
    library_ready: Callable[[], bool] = lambda: True
    #: Content visibility: ``False`` means the current filter hides this video, so nothing of it is decoded or shown.
    is_visible: Callable[[HarvestSourceRef], bool] = lambda ref: True


@dataclass(frozen=True)
class SavedWindow:
    asset_id: str
    name: str
    start_frame: int
    end_frame: int
    cadence: str
    status: str


@dataclass(frozen=True)
class WindowView:
    ok: bool
    error: str
    start_frame: int
    end_frame: int
    frames: int
    start_time: str
    end_time: str
    duration_text: str
    plan: CadencePlan | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class HarvestView:
    title: str
    loaded: bool
    busy: bool
    harvesting: bool
    status: str
    source_lines: tuple[str, ...]
    lineage_lines: tuple[str, ...]
    existing_lines: tuple[str, ...]
    notes: tuple[str, ...]
    media_path: str
    frame_count: int | None
    current_frame: int
    current_time: str
    window: WindowView | None
    start_text: str
    end_text: str
    unit: str
    cadence: str
    current_preview: FramePreview | None
    original_previews: tuple[FramePreview, ...]
    window_previews: tuple[FramePreview, ...]
    preview_issues: tuple[str, ...]
    workflow_lines: tuple[str, ...]
    saved: tuple[SavedWindow, ...]
    can_save: bool
    can_cancel: bool
    playback_note: str
    hidden: bool = False


def _number(text: str) -> float | None:
    try:
        return float(str(text).strip())
    except ValueError:
        return None


class MotionHarvestSession:
    def __init__(
        self,
        *,
        ports: HarvestPorts,
        runner: BackgroundWorkRunner,
        on_change: Callable[[], None] | None = None,
        on_saved: Callable[[SavedWindow], None] | None = None,
    ) -> None:
        self._ports = ports
        self._runner = runner
        self._on_change = on_change
        self._on_saved = on_saved
        self._closed = False
        self._tokens: dict[str, int] = {}
        self._cancels: dict[str, threading.Event] = {}
        self.ref: HarvestSourceRef | None = None
        self.info: HarvestSourceInfo | None = None
        self.status = "Choose a video to harvest motion from."
        self.unit = "frames"
        self.start_text = "0"
        self.end_text = ""
        self.cadence = CADENCE_NATIVE
        self.current_frame = 0
        self.saved: list[SavedWindow] = []
        self._opening = False
        self._harvesting = False
        self._current_preview: FramePreview | None = None
        self._original_previews: tuple[FramePreview, ...] = ()
        self._window_previews: tuple[FramePreview, ...] = ()
        self._preview_issues: tuple[str, ...] = ()
        self._window_preview_key: tuple[int, int] | None = None
        self._timing_cache: dict[tuple[int, str, bool], tuple[str, ...]] = {}

    # ------------------------------------------------------------------ plumbing

    def _next(self, kind: str) -> int:
        self._tokens[kind] = self._tokens.get(kind, 0) + 1
        previous = self._cancels.pop(kind, None)
        if previous is not None:
            previous.set()  # the superseded worker stops at its next bounded step
        self._cancels[kind] = threading.Event()
        return self._tokens[kind]

    def _live(self, kind: str, token: int) -> bool:
        return not self._closed and self._tokens.get(kind) == token

    def _notify(self) -> None:
        callback = self._on_change
        if callback is not None and not self._closed:
            callback()

    def _run(
        self, kind: str, work: Callable[[threading.Event], Any], finish: Callable[[Any], None]
    ) -> None:
        token = self._next(kind)
        cancel = self._cancels[kind]

        def done(outcome: WorkOutcome) -> None:
            if not self._live(kind, token):
                return
            if outcome.error:
                self._failed(kind, str(outcome.error))
                return
            finish(outcome.value)

        self._runner.start(f"motion-harvest-{kind}", lambda: WorkOutcome(value=work(cancel)), done)

    def _failed(self, kind: str, error: str) -> None:
        if kind == "open":
            self._opening = False
        if kind == "harvest":
            self._harvesting = False
        self.status = f"{kind.capitalize()} failed: {error}"
        self._notify()

    # ------------------------------------------------------------------ source

    def open(self, ref: HarvestSourceRef) -> None:
        """Bind the workspace to one exact file.  Refused while a harvest is writing."""

        if self._closed:
            return
        if self._harvesting:
            self.status = (
                "A harvest is running. Wait for it or cancel it before opening another video."
            )
            self._notify()
            return
        self.ref, self.info = ref, None
        self._reset_state()
        if not self._ports.is_visible(ref):
            self.status = HIDDEN_NOTE
            self._notify()
            return
        self._opening = True
        self.status = f"Opening {ref.label or ref.path} ..."
        for kind in ("frame", "original", "window"):
            self._invalidate(kind)
        self._notify()

        def finished(info: HarvestSourceInfo) -> None:
            self._opening = False
            if not info.ok:
                self.status = info.error or "The video could not be opened."
                self._notify()
                return
            self.info = info
            self.end_text = str(info.frame_count) if info.frame_count else ""
            self.status = "Choose the action window, then Save as Motion Asset. The original is never modified."
            self._request_original_previews()
            self._request_frame_preview()
            self._request_window_previews()
            self._notify()

        self._run("open", lambda cancel: self._ports.open_source(ref, cancel), finished)

    def _reset_state(self) -> None:
        self.unit = "frames"
        self.start_text, self.end_text = "0", ""
        self.cadence = CADENCE_NATIVE
        self.current_frame = 0
        self._current_preview = None
        self._original_previews = ()
        self._window_previews = ()
        self._preview_issues = ()
        self._window_preview_key = None
        self._timing_cache.clear()

    def _invalidate(self, kind: str) -> None:
        self._tokens[kind] = self._tokens.get(kind, 0) + 1
        previous = self._cancels.pop(kind, None)
        if previous is not None:
            previous.set()

    # ------------------------------------------------------------------ window commands (UI thread)

    @property
    def _frame_limit(self) -> int | None:
        return self.info.frame_count if self.info is not None else None

    def set_window_text(self, start: str, end: str, unit: str | None = None) -> None:
        if unit is not None and unit in UNITS and unit != self.unit:
            self._convert_unit(unit)
        self.start_text, self.end_text = str(start), str(end)
        self._after_window_change()

    def _convert_unit(self, unit: str) -> None:
        """Switching frames <-> seconds keeps the same window (shown in the new unit) when it can be placed."""

        view = self._window_view()
        rate = self.info.rate if self.info is not None else None
        self.unit = unit
        if view.ok and rate is not None:
            if unit == "frames":
                self.start_text, self.end_text = str(view.start_frame), str(view.end_frame)
            else:
                self.start_text = f"{float(Fraction(view.start_frame) / rate):.6f}".rstrip(
                    "0"
                ).rstrip(".")
                self.end_text = f"{float(Fraction(view.end_frame) / rate):.6f}".rstrip("0").rstrip(
                    "."
                )

    def set_unit(self, unit: str) -> None:
        """Show the same window in frames or seconds."""

        if unit in UNITS and unit != self.unit:
            self._convert_unit(unit)
            self._after_window_change()

    def set_cadence(self, cadence: str) -> None:
        if cadence in CADENCES and cadence != self.cadence:
            self.cadence = cadence
            self._notify()

    def seek(self, frame: int) -> None:
        if self.info is None:
            return
        limit = self._frame_limit
        frame = max(0, int(frame))
        if limit is not None:
            frame = min(frame, max(0, limit - 1))
        if frame == self.current_frame and self._current_preview is not None:
            return
        self.current_frame = frame
        self._request_frame_preview()
        self._notify()

    def step(self, delta: int) -> None:
        self.seek(self.current_frame + int(delta))

    def set_start_to_current(self) -> None:
        self.unit = "frames"
        self.start_text = str(self.current_frame)
        self._after_window_change()

    def set_end_after_current(self) -> None:
        """The current frame becomes the **last frame included** (the exclusive end is current + 1)."""

        self.unit = "frames"
        self.end_text = str(end_after_frame(self.current_frame))
        self._after_window_change()

    def reset_window(self) -> None:
        self.unit = "frames"
        self.start_text = "0"
        self.end_text = str(self._frame_limit) if self._frame_limit else ""
        self._after_window_change()

    def _after_window_change(self) -> None:
        self._request_window_previews()
        self._notify()

    # ------------------------------------------------------------------ previews

    def _request_original_previews(self) -> None:
        info = self.info
        if info is None or not info.frame_count:
            return
        frames = representative_frames(0, info.frame_count)
        path, rate = info.path, info.rate

        def finished(value: tuple[tuple[FramePreview, ...], tuple[str, ...]]) -> None:
            self._original_previews, issues = value
            self._preview_issues = tuple(dict.fromkeys((*self._preview_issues, *issues)))
            self._notify()

        self._run(
            "original",
            lambda cancel: self._ports.preview(path, frames, rate, cancel, "Original frame"),
            finished,
        )

    def _request_frame_preview(self) -> None:
        info = self.info
        if info is None:
            return
        frame, path, rate = self.current_frame, info.path, info.rate

        def finished(value: tuple[tuple[FramePreview, ...], tuple[str, ...]]) -> None:
            previews, issues = value
            if frame == self.current_frame:  # a later seek already moved on
                self._current_preview = previews[0] if previews else None
                if issues and not previews:
                    self._preview_issues = tuple(dict.fromkeys((*self._preview_issues, *issues)))
            self._notify()

        self._run(
            "frame",
            lambda cancel: self._ports.preview(path, [frame], rate, cancel, "Frame"),
            finished,
        )

    def _request_window_previews(self) -> None:
        info = self.info
        view = self._window_view()
        if info is None or not view.ok:
            self._invalidate("window")
            self._window_previews = ()
            self._window_preview_key = None
            return
        key = (view.start_frame, view.end_frame)
        if key == self._window_preview_key:
            return
        self._window_preview_key = key
        frames = representative_frames(view.start_frame, view.end_frame)
        path, rate = info.path, info.rate

        def finished(value: tuple[tuple[FramePreview, ...], tuple[str, ...]]) -> None:
            if key == self._window_preview_key:
                self._window_previews = value[0]
            self._notify()

        self._run(
            "window",
            lambda cancel: self._ports.preview(path, frames, rate, cancel, "Selected frame"),
            finished,
        )

    # ------------------------------------------------------------------ save

    def save(self, name: str, annotations: Mapping[str, Any]) -> None:
        info = self.info
        if info is None or self._harvesting or self._opening:
            self.status = (
                "Open a video first." if info is None else "Wait for the current operation."
            )
            self._notify()
            return
        view = self._window_view()
        if not view.ok:
            self.status = view.error
            self._notify()
            return
        if not self._ports.library_ready():
            self.status = (
                "No Motion Library folder is configured. Choose one in the Motion Library panel first; the "
                "window you selected is kept."
            )
            self._notify()
            return
        name = str(name or "").strip()
        if not name:
            self.status = "Give the motion a name before saving."
            self._notify()
            return
        request = HarvestRequest(
            source_path=info.path,
            start=float(_number(self.start_text) or 0),
            end=None if not self.end_text.strip() else float(_number(self.end_text) or 0),
            unit=self.unit,
            cadence=self.cadence,
            name=name,
            annotations=dict(annotations),
            lineage=info.lineage,
        )
        self._harvesting = True
        self.status = f"Harvesting '{name}' ..."
        self._notify()

        def finished(outcome: HarvestOutcome) -> None:
            self._harvesting = False
            self.status = outcome.message or outcome.status
            if outcome.ok and outcome.asset_id:
                record = SavedWindow(
                    outcome.asset_id,
                    name,
                    view.start_frame,
                    view.end_frame,
                    self.cadence,
                    outcome.status,
                )
                self.saved.append(record)
                callback = self._on_saved
                if callback is not None:
                    callback(record)
                self._refresh_existing(record)
            self._notify()

        self._run("harvest", lambda cancel: self._ports.harvest(request, cancel), finished)

    def _refresh_existing(self, record: SavedWindow) -> None:
        info = self.info
        if info is None:
            return
        from dataclasses import replace

        from src.video.motion_library.harvest_service import ExistingHarvest

        known = {e.asset_id for e in info.existing_harvests}
        if record.asset_id not in known:
            self.info = replace(
                info,
                existing_harvests=(
                    *info.existing_harvests,
                    ExistingHarvest(
                        record.asset_id,
                        record.name,
                        record.start_frame,
                        record.end_frame,
                        record.cadence,
                    ),
                ),
            )

    def cancel(self) -> None:
        """Cancel the running harvest (or opening); nothing partial is published."""

        for kind in ("harvest", "open"):
            event = self._cancels.get(kind)
            if event is not None:
                event.set()
        if self._harvesting:
            self.status = "Cancelling ... nothing will be added to the library."
            self._notify()

    def close(self) -> None:
        self._closed = True
        for event in self._cancels.values():
            event.set()
        self._on_change = None
        self._on_saved = None

    # ------------------------------------------------------------------ view

    def _window_view(self) -> WindowView:
        info = self.info
        empty = WindowView(False, "", 0, 0, 0, "", "", "", None, ())
        if info is None:
            return empty
        start, end = (
            _number(self.start_text),
            _number(self.end_text) if self.end_text.strip() else None,
        )
        if start is None or (self.end_text.strip() and end is None):
            return WindowView(
                False, "Start and end must be numbers.", 0, 0, 0, "", "", "", None, ()
            )
        try:
            window = resolve_window(
                start=start,
                end=end,
                unit=self.unit,
                rate=info.rate,
                frame_count=info.frame_count,
                count_is_reliable=info.frame_count_reliable,
            )
        except WindowError as exc:
            return WindowView(False, exc.message, 0, 0, 0, "", "", "", None, ())
        facts = info.facts
        if facts is not None and facts.fps_is_variable_suspected:
            return WindowView(
                False,
                "Variable frame rate video: view it here, but re-encode it at a constant rate to harvest.",
                window.start_frame, window.end_frame, window.frames, "", "", "", None, (),
            )  # fmt: skip
        try:
            plan = plan_cadence(window.frames, info.rate, self.cadence)
        except WindowError as exc:
            return WindowView(
                False,
                exc.message,
                window.start_frame,
                window.end_frame,
                window.frames,
                "",
                "",
                "",
                None,
                (),
            )
        return WindowView(
            True,
            "",
            window.start_frame,
            window.end_frame,
            window.frames,
            timecode(window.start_frame, info.rate),
            timecode(window.end_frame, info.rate),
            f"{plan.duration_seconds:.3f} s",
            plan,
            (
                f"Window: frames {window.start_frame}-{window.end_frame - 1} "
                f"({window.frames} frames, end exclusive {window.end_frame}).",
                *plan.lines,
            ),
        )

    def _workflow_lines(self, view: WindowView) -> tuple[str, ...]:
        timing = self._ports.workflow_timing
        info = self.info
        if timing is None or info is None or not view.ok or view.plan is None:
            return ()
        convert = self.cadence == CADENCE_NORMALIZED_24
        key = (view.plan.output_frames, "x" if convert else "n", convert)
        if key not in self._timing_cache:
            try:
                self._timing_cache[key] = timing(
                    view.plan.output_frames, view.plan.output_rate, convert
                )
            except Exception:  # noqa: BLE001 - an advisory never breaks the workspace
                self._timing_cache[key] = ()
        return self._timing_cache[key]

    def view(self) -> HarvestView:
        info = self.info
        loaded = info is not None
        window = self._window_view() if loaded else None
        source_lines: tuple[str, ...] = ()
        lineage_lines: tuple[str, ...] = ()
        notes: tuple[str, ...] = ()
        existing: tuple[str, ...] = ()
        title = self.ref.label if self.ref is not None and self.ref.label else "Harvest Motion"
        if info is not None and info.facts is not None:
            facts = info.facts
            source_lines = (
                f"File: {info.path}",
                f"SHA-256: {info.sha256}",
                f"Size: {info.size_bytes / (1024 * 1024):.2f} MB",
                f"Dimensions: {facts.display_width} x {facts.display_height}"
                + (
                    f" (stored rotated {facts.rotation_quadrants * 90} deg)"
                    if facts.rotation_quadrants
                    else ""
                ),
                f"Frame rate: {rate_label(info.rate)}",
                f"Frames: {info.frame_count if info.frame_count is not None else 'not reported'}"
                + ("" if info.frame_count_reliable or info.frame_count is None else " (estimated)"),
                f"Duration: {facts.duration_seconds:.3f} s"
                if facts.duration_seconds
                else "Duration: not reported",
                f"Codec: {facts.codec_name} / {facts.pixel_format}",
            )
            lineage_lines = (
                LINEAGE_TEXT.get(info.lineage.state, ""),
                *((info.lineage.note,) if info.lineage.note else ()),
                *((f"Job: {info.lineage.job_id}",) if info.lineage.job_id else ()),
                *((f"Library clip: {info.library_asset_id}",) if info.library_asset_id else ()),
            )
            notes = info.notes
            existing = tuple(
                f"Already harvested: '{e.name}' frames {e.start_frame}-{e.end_frame - 1} "
                f"({'24 fps' if e.cadence == CADENCE_NORMALIZED_24 else 'native cadence'})"
                for e in info.existing_harvests
            )
        hidden = self.ref is not None and not self._ports.is_visible(self.ref)
        can_save = bool(
            loaded
            and not hidden
            and window is not None
            and window.ok
            and not self._harvesting
            and not self._opening
        )
        return HarvestView(
            title=title,
            loaded=loaded,
            busy=self._opening or self._harvesting,
            harvesting=self._harvesting,
            status=HIDDEN_NOTE if hidden else self.status,
            source_lines=source_lines,
            lineage_lines=lineage_lines,
            existing_lines=existing,
            notes=notes,
            media_path=info.path if info is not None else "",
            frame_count=info.frame_count if info is not None else None,
            current_frame=self.current_frame,
            current_time=timecode(self.current_frame, info.rate) if info is not None else "",
            window=window,
            start_text=self.start_text,
            end_text=self.end_text,
            unit=self.unit,
            cadence=self.cadence,
            current_preview=None if hidden else self._current_preview,
            original_previews=() if hidden else self._original_previews,
            window_previews=() if hidden else self._window_previews,
            preview_issues=self._preview_issues,
            workflow_lines=self._workflow_lines(window) if window is not None else (),
            saved=tuple(self.saved),
            can_save=can_save,
            can_cancel=self._harvesting or self._opening,
            playback_note=TRUNCATED_PLAYBACK_NOTE,
            hidden=hidden,
        )


__all__ = [
    "CADENCE_LABELS",
    "HIDDEN_NOTE",
    "LINEAGE_TEXT",
    "TRUNCATED_PLAYBACK_NOTE",
    "UNITS",
    "HarvestPorts",
    "HarvestView",
    "MotionHarvestSession",
    "SavedWindow",
    "WindowView",
]

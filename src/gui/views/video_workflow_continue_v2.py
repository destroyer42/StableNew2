"""The "Continue a clip" rows of the Video Workflow tab and their off-Tk work (V1-6).

:class:`ContinueClipPanel` is presentation only: which clip, the frame to continue from and what the continuation will
be. :class:`ContinueClipHost` reads the clip and queues the continuation through the Tk-free
``src.controller.continue_clip`` facade on a worker owned by the ``ThreadRegistry``; results return to the Tk thread
through ``TkUiDispatcher`` and are dropped when a newer request superseded them or the tab is gone.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.controller.continue_clip import ClipContinuation, continue_clip, inspect_continuation
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.utils.thread_registry import get_thread_registry
from src.video.motion_intent import MOTION_INTENT_FIELD
from src.video.storyboard_root import StoryboardRootError, clip_last_frame
from src.video.video_workflow_intent import EXPERIMENTAL_OPT_IN_FIELD
from src.video.workflow_tasks import TASK_CONTINUE

CHOOSE_A_CLIP = "Choose a clip with Continue this clip, in Recent outputs or Job History."
FRAMES_FOLDER = "continue_frames"


@dataclass(frozen=True)
class ContinueOpening:
    """A clip read for the tab: what it offers and the last frame to show ("" when none could be read)."""

    clip: ClipContinuation
    last_frame: str


class ContinueClipPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_frame: Callable[[str], None],
        on_prompt_only: Callable[[], None],
        on_end_picture: Callable[[], None],
    ) -> None:
        super().__init__(master, style="Panel.TFrame")
        self.columnconfigure(0, weight=1)
        self._on_frame = on_frame
        self._frames: tuple[str, ...] = ()
        self.clip_var = tk.StringVar(value=CHOOSE_A_CLIP)
        self.frame_var = tk.IntVar(value=0)
        self.frame_text_var = tk.StringVar(value="")
        clip_label = ttk.Label(
            self, textvariable=self.clip_var, style="Dark.TLabel", justify="left"
        )
        clip_label.grid(row=0, column=0, sticky="ew")
        bind_wraplength(clip_label)
        self.frame_row = ttk.Frame(self, style="Panel.TFrame")
        self.frame_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.frame_row.columnconfigure(1, weight=1)
        ttk.Label(self.frame_row, text="Continue from", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.frame_scale = ttk.Scale(self.frame_row, from_=0, to=0, command=self._on_scale)
        self.frame_scale.grid(row=0, column=1, sticky="ew")
        ttk.Label(self.frame_row, textvariable=self.frame_text_var, style="Muted.TLabel").grid(
            row=0, column=2, sticky="e", padx=(6, 0)
        )
        buttons = ttk.Frame(self, style="Panel.TFrame")
        buttons.grid(row=2, column=0, sticky="w", pady=(4, 6))
        self.prompt_only_button = ttk.Button(
            buttons,
            text="Continue as prompt-only motion",
            style="Dark.TButton",
            command=on_prompt_only,
        )
        self.prompt_only_button.grid(row=0, column=0, padx=(0, 6))
        self.end_picture_button = ttk.Button(
            buttons, text="End on a picture...", style="Dark.TButton", command=on_end_picture
        )
        self.end_picture_button.grid(row=0, column=1)
        self.clear()

    def clear(self, text: str = CHOOSE_A_CLIP) -> None:
        self._frames = ()
        self.clip_var.set(text)
        self.frame_row.grid_remove()
        self.prompt_only_button.grid_remove()
        self.end_picture_button.grid_remove()

    def show(self, text: str, frames: tuple[str, ...], *, prompt_only: bool, picture: bool) -> None:
        self._frames = frames
        self.clip_var.set(text)
        if len(frames) > 1:
            self.frame_scale.configure(to=len(frames) - 1)
            self.frame_scale.set(len(frames) - 1)
            self.frame_var.set(len(frames) - 1)
            self._label(len(frames) - 1)
            self.frame_row.grid()
        else:
            self.frame_row.grid_remove()
        for button, shown in (
            (self.prompt_only_button, prompt_only),
            (self.end_picture_button, picture),
        ):
            if shown:
                button.grid()
            else:
                button.grid_remove()

    def chosen_index(self) -> int | None:
        """The chosen frame, or ``None`` for the last one."""

        index = self.frame_var.get()
        return None if len(self._frames) < 2 or index >= len(self._frames) - 1 else index

    def _label(self, index: int) -> None:
        last = " (last)" if index == len(self._frames) - 1 else ""
        self.frame_text_var.set(f"frame {index + 1} of {len(self._frames)}{last}")

    def _on_scale(self, value: str) -> None:
        if not self._frames:
            return
        index = max(0, min(len(self._frames) - 1, int(round(float(value)))))
        if index != self.frame_var.get():
            self.frame_var.set(index)
            self._label(index)
            self._on_frame(self._frames[index])


def apply_continuation(tab: Any, opening: ContinueOpening) -> None:
    """Fill the Video Workflow tab from a read clip: its engine, last frame, prompt and length (a new seed)."""

    clip = opening.clip
    if not tab.select_task(TASK_CONTINUE, pinned_workflow_id=clip.workflow_id):
        return
    with tab._pins.applying():
        tab.source_image_var.set(opening.last_frame)
        tab.prompt_text.delete("1.0", "end")
        tab.prompt_text.insert("1.0", clip.prompt)
        tab.motion_intent_panel.phrase_var.set(clip.motion_phrase)
        tab.seed_var.set("")
        for label, frames in tab._frame_count_labels.items():
            if frames == clip.frame_count:
                tab.frame_count_var.set(label)
    tab._source_bundle = None
    tab._source_lineage = {}
    if clip.takes_storyboard:
        where = "its Storyboard" if clip.storyboard_id else "a new Storyboard"
        text = (
            f"Continues job {clip.job_id[:8]} with {clip.workflow_label}, in {where}. "
            "The clip's engine, size and negative prompt are kept."
        )
    else:
        text = f"{clip.reason} It cannot be continued in a Storyboard."
    tab.continue_panel.show(
        text,
        clip.frame_paths if clip.takes_storyboard else (),
        prompt_only=not clip.takes_storyboard,
        picture=bool(opening.last_frame),
    )
    tab._sync_duration()
    tab._refresh_composed()
    tab._refresh_workspace_summary()
    tab._refresh_queue_gate()
    tab.status_var.set("Say what happens next, choose the length, then Queue.")


class ContinueClipHost:
    """One clip at a time: a newer *Continue this clip* supersedes an unfinished read."""

    def __init__(
        self,
        widget: tk.Misc,
        *,
        service: Callable[[], Any],
        on_opened: Callable[[ContinueOpening], None],
        on_queued: Callable[[Any], None],
        on_refused: Callable[[str], None],
        on_status: Callable[[str], None],
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        self._widget = widget
        self._service = service
        self._on_opened = on_opened
        self._on_queued = on_queued
        self._on_refused = on_refused
        self._on_status = on_status
        self._runner = runner
        self._token = 0
        self.opening: ContinueOpening | None = None
        self.queueing = False

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self._widget)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Read or queue a clip continuation without blocking Tk",
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

    def open(self, job_id: str) -> None:
        self._token += 1
        token = self._token
        self.opening = None
        try:
            service = self._service()
        except (AttributeError, RuntimeError) as exc:
            self._on_refused(f"Continue a clip is not available: {exc}")
            return
        self._on_status(f"Reading job {job_id} to continue it...")

        def work() -> WorkOutcome:
            clip = inspect_continuation(service, job_id)
            last = clip.frame_paths[-1] if clip.frame_paths else ""
            if not last:
                folder = Path(service.output_root()) / FRAMES_FOLDER / clip.job_id
                try:
                    last = clip_last_frame(service.job_repository(), clip.job_id, folder)
                except StoryboardRootError:
                    if not clip.takes_storyboard:
                        raise
            return WorkOutcome(value=ContinueOpening(clip, last))

        def finish(outcome: WorkOutcome) -> None:
            if token != self._token:
                return
            if outcome.error or not isinstance(outcome.value, ContinueOpening):
                self._on_refused(f"Continue a clip is not available: {outcome.error or 'no clip'}")
                return
            self.opening = outcome.value
            self._on_opened(outcome.value)

        self._work_runner().start("video-continue-open", work, finish)

    def queue(self, form: Mapping[str, Any], frame_index: int | None) -> None:
        """Queue the opened clip's continuation with the form's prompt, length, seed and opt-in."""

        opening = self.opening
        if opening is None:
            self._on_refused(CHOOSE_A_CLIP)
            return
        clip = opening.clip
        if not clip.takes_storyboard:
            self._on_refused(
                f"Not queued: {clip.reason} Use Continue as prompt-only motion instead."
            )
            return
        if str(form.get("workflow_id") or "") != clip.workflow_id:
            self._on_refused(
                f"Not queued: a continuation keeps the clip's engine, {clip.workflow_label}. "
                "Choose Continue this clip again."
            )
            return
        if self.queueing:
            return
        try:
            service = self._service()
        except (AttributeError, RuntimeError) as exc:
            self._on_refused(f"Not queued: {exc}")
            return
        self.queueing = True
        self._on_status("Queueing the continuation...")
        values = dict(form)

        def work() -> WorkOutcome:
            result = continue_clip(
                service,
                clip,
                prompt=str(values.get("prompt") or ""),
                frame_count=values.get("frame_count"),
                seed=str(values.get("seed") or ""),
                frame_index=frame_index,
                experimental_opt_in=values.get(EXPERIMENTAL_OPT_IN_FIELD) is True,
                motion_intent=values.get(MOTION_INTENT_FIELD),
            )
            return WorkOutcome(value=result)

        def finish(outcome: WorkOutcome) -> None:
            self.queueing = False
            if outcome.error or outcome.value is None:
                self._on_refused(f"Not queued: {outcome.error or 'nothing was queued'}")
                return
            self._on_queued(outcome.value)

        self._work_runner().start("video-continue-queue", work, finish)


__all__ = [
    "CHOOSE_A_CLIP",
    "ContinueClipHost",
    "ContinueClipPanel",
    "ContinueOpening",
    "apply_continuation",
]

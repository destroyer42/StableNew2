"""Suggest a motion phrase for the Video Workflow tab through AI Assist, and undo it (ASSIST-FIX).

Presentation glue only. One press reads the source picture on a worker owned by the ``ThreadRegistry``, submits one
request through the application's AI Assist integration and writes the answer into the Motion field, only if the
source, prompt and field are still what they were at the press. Nothing is queued. The Undo record is in memory only.
"""

from __future__ import annotations

import tkinter as tk
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.ai_assist.contracts import AssistOutcome, AssistRequest, OutcomeCode, SuggestionKind
from src.ai_assist.image import prepare_image
from src.ai_assist.remote_preview import VISION_MODELS
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui_v2.ai_suggestion_view import provider_outcome_text, result_provider_label
from src.utils.thread_registry import get_thread_registry
from src.video.motion_presets import FIELD_MOTION_PHRASE

NEEDS_REMOTE = "Motion suggestions need the remote AI worker with a vision model (Qwen3.5-4B). Select it in AI Preview."


@dataclass(frozen=True)
class _Form:
    source: str
    prompt: str
    phrase: str


class MotionAiHost:
    def __init__(
        self,
        widget: tk.Misc,
        *,
        ai: Callable[[], Any],
        source: Callable[[], str],
        prompt: Callable[[], str],
        phrase_var: tk.StringVar,
        pins: Any,
        on_status: Callable[[str], None],
        on_busy: Callable[[bool], None],
        on_undo_available: Callable[[bool], None],
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        self._widget = widget
        self._ai = ai
        self._source = source
        self._prompt = prompt
        self._phrase_var = phrase_var
        self._pins = pins
        self._on_status = on_status
        self._on_busy = on_busy
        self._on_undo_available = on_undo_available
        self._runner = runner
        #: ``(text applied, text before, whether the field was pinned before)``
        self._undo: tuple[str, str, bool] | None = None

    def suggest(self) -> None:
        ai = self._ai()
        if ai is None:
            self._on_status("AI Assist is unavailable.")
            return
        approval = ai.remote_preview()[0].approval
        if approval is None or approval.model not in VISION_MODELS:
            self._on_status(NEEDS_REMOTE)
            return
        code, message = ai.availability()
        if code is not None:
            self._on_status(message)
            return
        form = self._form()
        if not form.source:
            self._on_status("Choose a source image first.")
            return
        self._on_busy(True)
        self._on_status("Asking the AI worker for a motion phrase...")

        def work() -> WorkOutcome:
            return WorkOutcome(value=prepare_image(form.source))

        self._work_runner().start(
            "video-motion-suggest", work, lambda outcome: self._submit(form, outcome)
        )

    def undo(self) -> None:
        if self._undo is None:
            return
        applied, before, was_pinned = self._undo
        self._undo = None
        self._on_undo_available(False)
        if self._phrase_var.get() != applied:
            self._on_status("The motion phrase was edited since; nothing was undone.")
            return
        self._phrase_var.set(before)
        if not was_pinned:
            self._pins.pinned.discard(FIELD_MOTION_PHRASE)
        self._on_status("Motion suggestion undone.")

    # ------------------------------------------------------------------ internals

    def _form(self) -> _Form:
        return _Form(self._source().strip(), self._prompt().strip(), self._phrase_var.get())

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self._widget)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Reduce a source image for a motion suggestion without blocking Tk",
                ),
                dispatch=lambda fn: dispatcher.invoke(lambda: self._alive(fn)),
            )
        return self._runner

    def _alive(self, finish: Callable[[], None]) -> None:
        try:
            if self._widget.winfo_exists():
                finish()
        except tk.TclError:
            pass  # the tab is going away

    def _submit(self, form: _Form, read: WorkOutcome) -> None:
        if read.error or not isinstance(read.value, bytes):
            self._finish("The source image could not be read.")
            return
        try:
            request = AssistRequest(
                f"motion-{uuid.uuid4().hex}",
                SuggestionKind.MOTION_PHRASE,
                positive_text=form.prompt,
                content_class="sensitive",
                image_jpeg=read.value,
            )
        except ValueError:
            self._finish("The prompt is too long for a motion suggestion.")
            return
        submission = self._ai().submit(
            request, lambda outcome: self._alive(lambda: self._answered(form, outcome))
        )
        if not submission.accepted:
            self._finish(provider_outcome_text(submission.outcome))

    def _answered(self, form: _Form, outcome: AssistOutcome) -> None:
        suggestion = outcome.suggestion
        if suggestion is None or not suggestion.motion_phrase:
            text = provider_outcome_text(outcome)
            # A fallback outcome means the worker was unreachable: the ordinary text says that.
            if (
                outcome.code is OutcomeCode.UNAVAILABLE
                and outcome.reason.startswith("image_")
                and not outcome.details.get("fallback")
            ):
                text = NEEDS_REMOTE
            self._finish(text)
            return
        if self._form() != form:
            self._finish(
                "The form changed while the AI was working; the suggestion was not applied."
            )
            return
        self._undo = (
            suggestion.motion_phrase,
            form.phrase,
            FIELD_MOTION_PHRASE in self._pins.pinned,
        )
        self._phrase_var.set(suggestion.motion_phrase)
        self._on_undo_available(True)
        label = result_provider_label(outcome)
        self._finish(f"Motion phrase suggested. Undo restores the previous text. {label}".strip())

    def _finish(self, status: str) -> None:
        self._on_busy(False)
        self._on_status(status)

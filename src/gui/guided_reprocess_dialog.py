"""Editable guided draft using Review's established batch Preview and admission dialog."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import ttk
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.review_batch_dialog import ReviewBatchDialog
from src.gui.theme_v2 import apply_toplevel_theme
from src.review.correction_advice import GuidedReprocess


class GuidedReprocessDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        draft: GuidedReprocess,
        controller: Any,
        sources: dict[str, Any],
        detectors: tuple[str, ...],
        current: Callable[[], bool],
        visibility: Callable[[], ContentVisibilityResolver],
    ) -> None:
        super().__init__(parent)
        apply_toplevel_theme(self)
        self.title("Correction draft")
        self.transient(parent.winfo_toplevel())
        self._draft, self._controller, self._sources = draft, controller, sources
        self._current, self._visibility = current, visibility
        self._version = 0
        self._preview: ReviewBatchDialog | None = None
        self._busy = False
        self.status = tk.StringVar(
            master=self, value="Edit the prompt, then Preview the exact job."
        )
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"{draft.action.value} · {draft.model}").pack(anchor="w")
        ttk.Label(
            body,
            text="The detector can affect other regions."
            if detectors
            else "Img2img processes the whole image.",
        ).pack(anchor="w")
        self.detector = tk.StringVar(master=self, value=draft.detector)
        if detectors:
            ttk.Label(body, text="Detector").pack(anchor="w", pady=(6, 0))
            chooser = ttk.Combobox(
                body, textvariable=self.detector, values=detectors, state="readonly"
            )
            chooser.pack(fill="x")
            self.detector.trace_add("write", self._edited)
        self.modes: list[tk.StringVar] = []
        self.prompts: list[tk.Text] = []
        for label in ("Positive prompt edit", "Negative prompt edit"):
            ttk.Label(body, text=label).pack(anchor="w", pady=(8, 0))
            mode = tk.StringVar(master=self, value="append")
            ttk.Combobox(
                body, values=("append", "replace", "modify"), state="readonly", textvariable=mode
            ).pack(anchor="w")
            mode.trace_add("write", self._edited)
            prompt = tk.Text(body, height=4, width=60, wrap="word")
            prompt.pack(fill="x")
            prompt.bind("<<Modified>>", self._prompt_edited)
            self.modes.append(mode)
            self.prompts.append(prompt)
        ttk.Label(body, textvariable=self.status, wraplength=480).pack(anchor="w", pady=8)
        self.preview_button = ttk.Button(body, text="Preview frozen job", command=self._prepare)
        self.preview_button.pack(side="left")
        ttk.Button(body, text="Close draft", command=self._close).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self) -> None:
        if self._preview is None or not self._preview.winfo_exists() or not self._preview.inflight:
            self.destroy()

    def _prompt_edited(self, event: tk.Event) -> None:
        if isinstance(event.widget, tk.Text) and event.widget.edit_modified():
            event.widget.edit_modified(False)
            self._edited()

    def _edited(self, *_args: Any) -> None:
        self._version += 1
        if (
            self._preview is not None
            and self._preview.winfo_exists()
            and not self._preview.inflight
        ):
            self._preview.destroy()
        self.status.set("Draft edited. Preview to review the new settings.")

    def _prepare(self) -> None:
        if self._busy or (self._preview is not None and self._preview.winfo_exists()):
            return
        if not self._current():
            self.status.set("The Review selection or target changed. Open a new correction draft.")
            return
        draft = replace(self._draft, detector=self.detector.get())
        for prompt in self.prompts:
            prompt.edit_modified(False)
        prompts = tuple(widget.get("1.0", "end-1c") for widget in self.prompts)
        modes = tuple(mode.get() for mode in self.modes)
        self._version += 1
        version = self._version
        self._busy = True
        self.preview_button.state(["disabled"])

        def is_current() -> bool:
            return bool(
                self.winfo_exists()
                and version == self._version
                and self._current()
                and draft.detector == self.detector.get()
                and prompts == tuple(widget.get("1.0", "end-1c") for widget in self.prompts)
                and modes == tuple(mode.get() for mode in self.modes)
            )

        def ready(preview: Any) -> None:
            if not self.winfo_exists():
                return
            self._busy = False
            self.preview_button.state(["!disabled"])
            if not is_current():
                self.status.set("The draft changed while preparing. Preview again.")
                return
            self._preview = ReviewBatchDialog(
                self,
                preview,
                submit=self._controller.submit_review_reprocess_batch_async,
                repreview=lambda _paths: self._prepare(),
                visibility=self._visibility(),
                is_current=is_current,
            )
            self.status.set("Confirm the frozen job in Review Preview.")

        def failed(_error: Exception) -> None:
            if self.winfo_exists():
                self._busy = False
                self.preview_button.state(["!disabled"])
                self.status.set(
                    "Review could not prepare this correction. Check the target and try Preview again."
                )

        try:
            self._controller.preview_review_reprocess_batch(
                image_paths=[str(draft.source.path)],
                stages=[draft.stage],
                prompt_delta=prompts[0],
                negative_prompt_delta=prompts[1],
                prompt_mode=modes[0],
                negative_prompt_mode=modes[1],
                batch_size=1,
                source_metadata_by_image=self._sources,
                guided=draft,
                on_preview=ready,
                on_error=failed,
            )
        except (ValueError, RuntimeError, OSError, tk.TclError) as exc:
            failed(exc)

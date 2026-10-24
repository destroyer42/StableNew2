"""Pipeline-tab editor for a "Regenerate with Changes" variation (PR-HISTORY-610A).

Shown only while ``AppStateV2.job_draft.history_variation`` exists. It edits exactly five fields (positive prompt,
negative prompt when the frozen profile allows one, seed, steps, CFG) by replacing the draft through
``update_history_variation`` - which invalidates the Preview - and lists every other effective setting as read-only text.
It never compiles, previews or queues; the Preview panel's Add to Queue stays the single admission path. In SFW mode a
prompt that classifies as NSFW is shown redacted and is not editable, so redacted text can never be written back.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import ttk
from typing import Any

from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.gui import theme_v2 as theme_mod
from src.pipeline.history_variation_compiler import (
    HistoryVariationDraft,
    inherited_settings_summary,
    summarize_variation_changes,
    validate_edits,
)

#: Values the compile-time validation rejects, used when a field cannot be parsed so a stale value is never admitted.
_INVALID_SEED, _INVALID_STEPS, _INVALID_CFG = -2, 0, float("nan")


class HistoryVariationPanelV2(ttk.Frame):
    def __init__(self, master: tk.Misc, *, app_state: Any, **kwargs: Any) -> None:
        super().__init__(master, style=theme_mod.SURFACE_FRAME_STYLE, **kwargs)
        self.app_state = app_state
        self._draft: HistoryVariationDraft | None = None
        self._applying = False
        self._hide_prompts = False
        self._parse_errors: tuple[str, ...] = ()

        self._body = ttk.Frame(self, style=theme_mod.SURFACE_FRAME_STYLE)
        body = self._body
        self.title_var = tk.StringVar()
        ttk.Label(
            body, textvariable=self.title_var, style=theme_mod.STATUS_STRONG_LABEL_STYLE
        ).pack(anchor=tk.W)
        ttk.Label(
            body,
            text="Editable text-to-image draft of a past job. Nothing is queued until you confirm the Preview.",
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=300,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 4))

        ttk.Label(body, text="Positive prompt", style=theme_mod.MUTED_LABEL_STYLE).pack(anchor=tk.W)
        self.positive_text = tk.Text(body, height=4, width=36, wrap="word")
        self.positive_text.pack(fill=tk.X)
        ttk.Label(body, text="Negative prompt", style=theme_mod.MUTED_LABEL_STYLE).pack(anchor=tk.W)
        self.negative_text = tk.Text(body, height=2, width=36, wrap="word")
        self.negative_text.pack(fill=tk.X)
        self.negative_note_var = tk.StringVar()
        ttk.Label(
            body,
            textvariable=self.negative_note_var,
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=300,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        numbers = ttk.Frame(body, style=theme_mod.SURFACE_FRAME_STYLE)
        numbers.pack(fill=tk.X, pady=(4, 0))
        self.seed_var, self.steps_var, self.cfg_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.seed_entry = self._number_field(numbers, "Seed", self.seed_var, 0, 14)
        self.steps_entry = self._number_field(numbers, "Steps", self.steps_var, 1, 5)
        self.cfg_entry = self._number_field(numbers, "CFG", self.cfg_var, 2, 6)
        self.seed_hint_var = tk.StringVar()
        ttk.Label(
            body,
            textvariable=self.seed_hint_var,
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=300,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        self.inherited_var = tk.StringVar()
        ttk.Label(body, text="Inherited (read-only)", style=theme_mod.MUTED_LABEL_STYLE).pack(
            anchor=tk.W, pady=(4, 0)
        )
        ttk.Label(
            body,
            textvariable=self.inherited_var,
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=300,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)
        self.changes_var, self.error_var = tk.StringVar(), tk.StringVar()
        ttk.Label(
            body,
            textvariable=self.changes_var,
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=300,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(
            body,
            textvariable=self.error_var,
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=300,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        buttons = ttk.Frame(body, style=theme_mod.SURFACE_FRAME_STYLE)
        buttons.pack(fill=tk.X, pady=(6, 0))
        self.recorded_seed_btn = ttk.Button(
            buttons, text="Use recorded seed", command=self._use_recorded_seed
        )
        self.recorded_seed_btn.pack(side=tk.LEFT)
        self.reset_btn = ttk.Button(
            buttons, text="Reset to original", command=self._reset_to_original
        )
        self.reset_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.discard_btn = ttk.Button(buttons, text="Discard variation", command=self._discard)
        self.discard_btn.pack(side=tk.LEFT, padx=(4, 0))

        for widget in (self.positive_text, self.negative_text):
            widget.bind("<KeyRelease>", lambda _e: self._apply_from_widgets())
        for entry in (self.seed_entry, self.steps_entry, self.cfg_entry):
            entry.bind("<KeyRelease>", lambda _e: self._apply_from_widgets())
            entry.bind("<FocusOut>", lambda _e: self._apply_from_widgets())

        if hasattr(app_state, "subscribe"):
            app_state.subscribe("job_draft", self.refresh)
            app_state.subscribe("content_visibility_mode", self.refresh)
        self.refresh()

    def _number_field(
        self, parent: tk.Misc, label: str, var: tk.StringVar, column: int, width: int
    ) -> ttk.Entry:
        ttk.Label(parent, text=label, style=theme_mod.MUTED_LABEL_STYLE).grid(
            row=0, column=column * 2, padx=(0, 2)
        )
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=0, column=column * 2 + 1, padx=(0, 8))
        return entry

    # --- state -> widgets ---------------------------------------------------------------------

    def _current(self) -> HistoryVariationDraft | None:
        draft = getattr(getattr(self.app_state, "job_draft", None), "history_variation", None)
        return draft if isinstance(draft, HistoryVariationDraft) else None

    def refresh(self) -> None:
        draft = self._current()
        self._draft = draft
        if draft is None:
            self._body.pack_forget()
            return
        if not self._body.winfo_manager():
            self._body.pack(fill=tk.X)
        mode = str(getattr(self.app_state, "content_visibility_mode", "nsfw") or "nsfw")
        subject = {
            "positive_prompt": draft.baseline.positive_prompt,
            "negative_prompt": draft.baseline.negative_prompt,
        }
        self._hide_prompts = (
            ContentVisibilityResolver(mode).decide(subject, allow_redacted=True).redacted
        )
        self.title_var.set(f"Variation of {draft.source_job_id} (unsent draft)")
        self.inherited_var.set(
            "\n".join(
                f"{label}: {value}" for label, value in inherited_settings_summary(draft.source)
            )
        )
        recorded = draft.recorded_seed
        self.seed_hint_var.set(
            f"Frozen seed {draft.baseline.seed}"
            + (
                f"; the original image was generated with seed {recorded}."
                if recorded is not None and recorded != draft.baseline.seed
                else "."
            )
            + (" -1 picks a new random seed." if draft.baseline.seed != -1 else "")
        )
        self._update_status(draft)
        if not self._applying:
            self._load_widgets(draft)

    def _set_text(self, widget: tk.Text, value: str, *, editable: bool) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.NORMAL if editable else tk.DISABLED)

    def _load_widgets(self, draft: HistoryVariationDraft) -> None:
        edits = draft.edits
        hidden = self._hide_prompts
        self._parse_errors = ()
        self._update_status(draft)
        self._set_text(
            self.positive_text,
            REDACTED_TEXT if hidden else edits.positive_prompt,
            editable=not hidden,
        )
        negative_editable = draft.negative_editable and not hidden
        self._set_text(
            self.negative_text,
            REDACTED_TEXT if hidden else edits.negative_prompt,
            editable=negative_editable,
        )
        self.negative_note_var.set(
            "Hidden in SFW mode; switch to NSFW view to edit prompts."
            if hidden
            else (
                ""
                if draft.negative_editable
                else "The frozen model profile does not accept a negative prompt."
            )
        )
        self.seed_var.set(str(edits.seed))
        self.steps_var.set(str(edits.steps))
        self.cfg_var.set(f"{edits.cfg_scale:g}")

    def _update_status(self, draft: HistoryVariationDraft) -> None:
        changes = summarize_variation_changes(draft) if not self._parse_errors else ()
        self.changes_var.set(
            "Changes: " + "; ".join(changes)
            if changes
            else "No changes yet: identical to the original recipe."
        )
        errors = self._parse_errors or validate_edits(draft)
        self.error_var.set(" ".join(errors))
        recorded = draft.recorded_seed
        usable = recorded is not None and recorded != draft.edits.seed
        self.recorded_seed_btn.configure(state=tk.NORMAL if usable else tk.DISABLED)
        self.reset_btn.configure(state=tk.NORMAL if draft.edits != draft.baseline else tk.DISABLED)

    # --- widgets -> state ---------------------------------------------------------------------

    def _apply_from_widgets(self) -> None:
        draft = self._draft
        if draft is None:
            return
        changes: dict[str, Any] = {}
        errors: list[str] = []
        if not self._hide_prompts:
            changes["positive_prompt"] = self.positive_text.get("1.0", "end-1c")
            if draft.negative_editable:
                changes["negative_prompt"] = self.negative_text.get("1.0", "end-1c")
        for name, var, parse, invalid, label in (
            ("seed", self.seed_var, int, _INVALID_SEED, "Seed must be a whole number."),
            ("steps", self.steps_var, int, _INVALID_STEPS, "Steps must be a whole number."),
            ("cfg_scale", self.cfg_var, float, _INVALID_CFG, "CFG must be a number."),
        ):
            try:
                changes[name] = parse(var.get().strip())
            except ValueError:
                changes[name] = invalid
                errors.append(label)
        self._parse_errors = tuple(errors)
        self._push(draft.with_edits(**changes))

    def _push(self, updated: HistoryVariationDraft) -> None:
        self._applying = True
        try:
            self.app_state.update_history_variation(updated)
        finally:
            self._applying = False
        self._draft = self._current() or updated
        self._update_status(self._draft)

    def _use_recorded_seed(self) -> None:
        draft = self._draft
        if draft is None or draft.recorded_seed is None:
            return
        self._parse_errors = ()
        self.app_state.update_history_variation(draft.with_edits(seed=draft.recorded_seed))

    def _reset_to_original(self) -> None:
        draft = self._draft
        if draft is None:
            return
        self._parse_errors = ()
        self.app_state.update_history_variation(replace(draft, edits=draft.baseline))

    def _discard(self) -> None:
        self._parse_errors = ()
        self.app_state.clear_job_draft()


__all__ = ["HistoryVariationPanelV2"]

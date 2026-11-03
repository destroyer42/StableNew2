"""Tk rendering of the Video Workflow "Multi-shot sequence" section (PR-VID-SEQ-331A). Presentation only.

An ordered list of shots (prompt, length, optional authored keyframe) becomes one multi-segment job. Shot 1 always starts
from the form's source image; a later shot starts from its keyframe when it has one, otherwise from the exact last frame
of the shot before it. The panel reads the form through injected callables, builds no job itself and calls no backend:
the session hands the intent to the controller, which admits ONE job through the canonical queue path.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import filedialog, ttk
from typing import Any
from uuid import uuid4

from src.gui.view_contracts.video_sequence_contract import (
    SequenceSession,
    SequenceSubmitOutcome,
    sequence_block_reason,
)
from src.gui.views.storyboard_panel_actions import StoryboardPanelActions
from src.video.sequence_shots import MAX_SHOTS, MIN_SHOTS, ShotDraft
from src.video.storyboard import StoryboardDraft
from src.video.storyboard_readiness import readiness, record_images

_IMAGE_FILETYPES = [
    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
    ("All files", "*.*"),
]


class _ShotRow:
    def __init__(
        self, panel: WorkflowSequencePanel, parent: tk.Misc, position: int, lengths: list[str]
    ) -> None:
        self.frame = ttk.Frame(parent, style="Panel.TFrame")
        self.label = ttk.Label(self.frame, style="Dark.TLabel", width=7)
        self.prompt_var = tk.StringVar()
        self.length_var = tk.StringVar(value=lengths[0] if lengths else "")
        self.keyframe_var = tk.StringVar()
        self.seed_var = tk.StringVar()
        self.shot_id = uuid4().hex
        self.keyframe_sha256 = ""
        self.shot_label_var = tk.StringVar()
        self.label.grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.prompt_entry = ttk.Entry(
            self.frame, textvariable=self.prompt_var, style="Dark.TEntry", width=36
        )
        self.prompt_entry.grid(row=0, column=1, padx=(0, 6), sticky="ew")
        self.length_combo = ttk.Combobox(
            self.frame, textvariable=self.length_var, values=lengths, width=18, state="readonly"
        )
        self.length_combo.grid(row=0, column=2, padx=(0, 6))
        self.keyframe_entry = ttk.Entry(
            self.frame, textvariable=self.keyframe_var, style="Dark.TEntry", width=24
        )
        self.keyframe_entry.grid(row=1, column=1, sticky="ew", padx=(0, 4))
        self.browse_button = ttk.Button(
            self.frame,
            text="Browse...",
            style="Dark.TButton",
            command=lambda: panel._browse_keyframe(self),
        )
        self.browse_button.grid(row=1, column=2, padx=(0, 6))
        self.seed_entry = ttk.Entry(
            self.frame, textvariable=self.seed_var, style="Dark.TEntry", width=10
        )
        self.seed_entry.grid(row=1, column=3, padx=(0, 6))
        ttk.Entry(self.frame, textvariable=self.shot_label_var, style="Dark.TEntry", width=14).grid(
            row=0, column=3, sticky="ew"
        )
        self.remove_button = ttk.Button(
            self.frame,
            text="Remove",
            style="Dark.TButton",
            command=lambda: panel._remove_row(self),
        )
        self.remove_button.grid(row=2, column=3, sticky="e")
        self.up_button = ttk.Button(
            self.frame,
            text="Move Up",
            command=lambda: panel._move_row(self, -1),
            style="Dark.TButton",
        )
        self.down_button = ttk.Button(
            self.frame,
            text="Move Down",
            command=lambda: panel._move_row(self, 1),
            style="Dark.TButton",
        )
        self.duplicate_button = ttk.Button(
            self.frame,
            text="Duplicate Shot",
            command=lambda: panel._duplicate_row(self),
            style="Dark.TButton",
        )
        self.up_button.grid(row=2, column=0)
        self.down_button.grid(row=2, column=1, sticky="w")
        self.duplicate_button.grid(row=2, column=2)
        self.frame.columnconfigure(1, weight=1)
        self.set_position(position)

    def set_position(self, position: int) -> None:
        self.label.configure(text=f"Shot {position + 1}")
        first = position == 0
        # Shot 1 starts from the source image; a keyframe there would silently do nothing.
        self.keyframe_entry.configure(state="disabled" if first else "normal")
        self.browse_button.configure(state="disabled" if first else "normal")
        # Keep an authored anchor when reordering into position 1. It is visible and
        # explicitly refused until cleared or moved; no authored field is discarded.
        if first and self.keyframe_var.get():
            self.keyframe_entry.configure(state="normal")


class WorkflowSequencePanel(StoryboardPanelActions):
    def __init__(
        self,
        master: tk.Misc,
        *,
        session: SequenceSession,
        read_form: Callable[[], tuple[str, dict[str, Any]]],
        frame_counts: Callable[[], dict[str, int]],
        block_reason: Callable[[], str],
        on_queued: Callable[[str], None] | None = None,
        restore_form: Callable[[dict[str, Any]], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, title="Multi-shot sequence", **kwargs)
        self._session = session
        self._base_read_form = read_form
        self._base_frame_counts = frame_counts
        self._pinned_workflow: tuple[str, str] | None = None
        self._last_frame_counts: dict[str, int] = {}
        self._block_reason = block_reason
        self._on_queued = on_queued
        self._restore_form = restore_form
        self._rows: list[_ShotRow] = []
        self.status_var = tk.StringVar(value="")
        self.clip_name_var = tk.StringVar(value="")
        self.title_var = tk.StringVar()
        self.notes_var = tk.StringVar()
        self.dirty_var = tk.StringVar(value="Unsaved changes")
        self._build_storyboard_actions(self.body)

        body = self.body
        body.columnconfigure(0, weight=1)
        ttk.Label(
            body,
            style="Dark.TLabel",
            wraplength=760,
            justify="left",
            text=(
                "Shot 1 starts from the source image above. A later shot starts from its keyframe when "
                "you name one, otherwise from the exact last frame of the shot before it. The whole "
                "sequence is one queued job; if it stops, resume it from Job History."
            ),
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header = ttk.Frame(body, style="Panel.TFrame")
        header.grid(row=1, column=0, sticky="ew")
        for column, text in (
            (0, ""),
            (1, "Motion prompt (blank = form prompt)"),
            (2, "Length"),
            (3, "Keyframe (optional)"),
            (4, "Seed (blank = random; shot 1: form seed)"),
        ):
            ttk.Label(header, text=text, style="Dark.TLabel").grid(
                row=0, column=column, sticky="w", padx=(0, 6)
            )
        self.rows_frame = ttk.Frame(body, style="Panel.TFrame")
        self.rows_frame.grid(row=2, column=0, sticky="ew", pady=(2, 6))
        self.rows_frame.columnconfigure(0, weight=1)

        actions = ttk.Frame(body, style="Panel.TFrame")
        actions.grid(row=3, column=0, sticky="ew")
        self.add_button = ttk.Button(
            actions, text="Add shot", style="Dark.TButton", command=self.add_shot
        )
        self.add_button.pack(side="left")
        ttk.Label(actions, text="Clip name", style="Dark.TLabel").pack(side="left", padx=(12, 4))
        self.clip_name_entry = ttk.Entry(
            actions, textvariable=self.clip_name_var, style="Dark.TEntry", width=18
        )
        self.clip_name_entry.pack(side="left")
        self.queue_button = ttk.Button(
            actions, text="Queue Sequence", style="Dark.TButton", command=self._on_queue
        )
        self.queue_button.pack(side="left", padx=(12, 0))
        self.progress_button = ttk.Button(
            actions, text="Check progress", style="Dark.TButton", command=self._on_progress
        )
        self.progress_button.pack(side="left", padx=(6, 0))
        ttk.Label(body, textvariable=self.status_var, style="Dark.TLabel", wraplength=760).grid(
            row=4, column=0, sticky="ew", pady=(6, 0)
        )
        for _ in range(MIN_SHOTS):
            self.add_shot()
        self._tracking = True
        self._changed()

    # -- public API ---------------------------------------------------------------------------------------------

    def add_shot(self, draft: ShotDraft | None = None) -> bool:
        if len(self._rows) >= MAX_SHOTS:
            self.status_var.set(f"A sequence can have at most {MAX_SHOTS} shots.")
            return False
        lengths = list(self._frame_counts())
        row = _ShotRow(self, self.rows_frame, len(self._rows), lengths)
        row.frame.grid(row=len(self._rows), column=0, sticky="ew", pady=(0, 3))
        self._rows.append(row)
        if draft is not None:
            row.shot_id = draft.shot_id
            row.keyframe_sha256 = draft.keyframe_sha256
            row.shot_label_var.set(draft.label)
            row.prompt_var.set(draft.prompt)
            row.keyframe_var.set(draft.keyframe_path)
            row.seed_var.set(draft.seed)
            self._select_length(row, draft.frame_count)
            row.set_position(len(self._rows) - 1)
        for var in (
            row.prompt_var,
            row.length_var,
            row.keyframe_var,
            row.seed_var,
            row.shot_label_var,
        ):
            var.trace_add("write", self._changed)
        self._sync_buttons()
        self._changed()
        return True

    def refresh_lengths(self) -> None:
        """The selected workflow's legal lengths changed: offer exactly those and keep a still-legal choice."""

        choices = self._frame_counts()
        labels = list(choices)
        for row in self._rows:
            count = self._last_frame_counts.get(
                row.length_var.get(),
                choices.get(row.length_var.get(), self._raw_count(row.length_var.get())),
            )
            row.length_combo.configure(values=labels)
            if not row.length_var.get():
                row.length_var.set(labels[0] if labels else "")
            elif count is not None:
                self._select_length(row, count)
        self._last_frame_counts = choices
        enabled = bool(labels)
        state = "normal" if enabled else "disabled"
        for widget in (self.add_button, self.queue_button, self.clip_name_entry):
            widget.configure(state=state)
        if not enabled:
            self.status_var.set(
                "The selected workflow declares no length policy, so it cannot run as a sequence."
            )
        elif self.status_var.get().startswith("The selected workflow declares no length"):
            self.status_var.set("")

    def shots(self) -> list[ShotDraft]:
        choices = self._frame_counts()
        return [
            ShotDraft(
                prompt=row.prompt_var.get().strip(),
                frame_count=choices.get(
                    row.length_var.get(),
                    self._last_frame_counts.get(
                        row.length_var.get(), self._raw_count(row.length_var.get())
                    ),
                ),
                keyframe_path=row.keyframe_var.get().strip(),
                seed=row.seed_var.get().strip(),
                shot_id=row.shot_id,
                keyframe_sha256=row.keyframe_sha256,
                label=row.shot_label_var.get(),
            )
            for index, row in enumerate(self._rows)
        ]

    # -- internals ----------------------------------------------------------------------------------------------

    def _select_length(self, row: _ShotRow, frame_count: int | None) -> None:
        for label, count in self._frame_counts().items():
            if frame_count is not None and count == frame_count:
                row.length_var.set(label)
                return
        row.length_var.set(f"{frame_count} frames (unsupported)" if frame_count else "")

    @staticmethod
    def _raw_count(label: str) -> int | None:
        try:
            return int(label.split()[0])
        except (ValueError, IndexError):
            return None

    def _new_shot(self) -> ShotDraft:
        return ShotDraft(frame_count=next(iter(self._frame_counts().values()), None))

    def _move_row(self, row: _ShotRow, offset: int) -> None:
        position = self._rows.index(row)
        target = position + offset
        if not 0 <= target < len(self._rows):
            return
        self._rows.insert(target, self._rows.pop(position))
        self._reflow_rows()

    def _duplicate_row(self, row: _ShotRow) -> None:
        shot = self.shots()[self._rows.index(row)]
        if self.add_shot(replace(shot, shot_id=uuid4().hex)):
            copied = self._rows.pop()
            self._rows.insert(self._rows.index(row) + 1, copied)
            self._reflow_rows()

    def _reflow_rows(self) -> None:
        for position, row in enumerate(self._rows):
            row.set_position(position)
            row.frame.grid(row=position, column=0, sticky="ew", pady=(0, 3))
        self._sync_buttons()
        self._changed()

    def _remove_row(self, row: _ShotRow) -> None:
        if len(self._rows) <= MIN_SHOTS:
            self.status_var.set(f"A sequence needs at least {MIN_SHOTS} shots.")
            return
        self._rows.remove(row)
        row.frame.destroy()
        for position, remaining in enumerate(self._rows):
            remaining.set_position(position)
            remaining.frame.grid(row=position, column=0, sticky="ew", pady=(0, 3))
        self._sync_buttons()
        self._changed()

    def _sync_buttons(self) -> None:
        self.add_button.configure(
            state="normal" if len(self._rows) < MAX_SHOTS and self._frame_counts() else "disabled"
        )
        for row in self._rows:
            index = self._rows.index(row)
            row.up_button.configure(state="normal" if index else "disabled")
            row.down_button.configure(state="normal" if index < len(self._rows) - 1 else "disabled")
            row.duplicate_button.configure(
                state="normal" if len(self._rows) < MAX_SHOTS else "disabled"
            )
            row.remove_button.configure(
                state="normal" if len(self._rows) > MIN_SHOTS else "disabled"
            )

    def _browse_keyframe(self, row: _ShotRow) -> None:
        chosen = filedialog.askopenfilename(
            parent=self, title="Choose the keyframe image", filetypes=_IMAGE_FILETYPES
        )
        if chosen:
            row.keyframe_var.set(chosen)

    def _on_queue(self) -> None:
        source, form = self._read_form()
        shots = self.shots()
        reason = self._block_reason() or sequence_block_reason(
            has_frame_counts=bool(self._frame_counts()), source_image_path=source, shots=shots
        )
        if reason:
            self.status_var.set(reason)
            return
        captured = self._capture_storyboard()
        registry = self._registry()

        def work() -> tuple[StoryboardDraft, SequenceSubmitOutcome]:
            draft = record_images(captured)
            projection = readiness(draft, registry, form)
            if projection.problems:
                raise ValueError("Not queued: " + " ".join(projection.problems))
            outcome = self._session.submit(
                source_image_path=source,
                form_data=form,
                shots=draft.shots,
                clip_name=draft.clip_name,
                storyboard=draft,
            )
            return draft, outcome

        def done(result: tuple[StoryboardDraft, SequenceSubmitOutcome]) -> None:
            draft, outcome = result
            if self._capture_storyboard().fingerprint() == captured.fingerprint():
                self.storyboard.draft = draft
                self._changed()
            self.status_var.set(outcome.message)
            if outcome.ok and self._on_queued is not None:
                self._on_queued(outcome.job_id)

        self._work(work, done)

    def _on_progress(self) -> None:
        self.status_var.set(self._session.check_progress())


__all__ = ["WorkflowSequencePanel"]

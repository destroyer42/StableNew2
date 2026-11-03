"""Storyboard actions for the existing sequence panel; all disk work uses the shared UI work runner."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Any

from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.view_contracts.storyboard_contract import StoryboardSession
from src.gui.view_contracts.video_sequence_contract import SequenceSession
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.video.sequence_shots import ShotDraft
from src.video.storyboard import StoryboardDraft, StoryboardError
from src.video.storyboard_readiness import StoryboardReadiness, readiness, record_images
from src.video.storyboard_store import StoryboardStore

if TYPE_CHECKING:
    from src.gui.views.video_workflow_sequence_panel_v2 import _ShotRow


class StoryboardPanelActions(DisclosureSection):
    """Presentation-only mixin. Worker inputs are immutable snapshots; callbacks never touch disposed widgets."""

    title_var: tk.StringVar
    notes_var: tk.StringVar
    clip_name_var: tk.StringVar
    dirty_var: tk.StringVar
    status_var: tk.StringVar
    _rows: list[_ShotRow]
    _session: SequenceSession
    _pinned_workflow: tuple[str, str] | None
    _base_read_form: Callable[[], tuple[str, dict[str, Any]]]
    _base_frame_counts: Callable[[], dict[str, int]]
    _restore_form: Callable[[dict[str, Any]], None] | None

    def shots(self) -> list[ShotDraft]:
        raise NotImplementedError

    def add_shot(self, draft: ShotDraft | None = None) -> bool:
        raise NotImplementedError

    def _new_shot(self) -> ShotDraft:
        raise NotImplementedError

    def refresh_lengths(self) -> None:
        raise NotImplementedError

    def _build_storyboard_actions(self, body: Any) -> None:
        self.storyboard = StoryboardSession()
        self.store = StoryboardStore()
        self._runner = build_edit_work_runner(self)
        self._busy = False
        self._tracking = False
        self.title_var.set(self.storyboard.draft.title)
        self.bind("<Destroy>", self._storyboard_destroyed, add="+")
        bar = ttk.Frame(body, style="Panel.TFrame")
        bar.grid(row=5, column=0, sticky="ew", pady=6)
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="Storyboard title", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(bar, textvariable=self.title_var, style="Dark.TEntry").grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Label(bar, textvariable=self.dirty_var, style="Dark.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(bar, text="Notes", style="Dark.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(bar, textvariable=self.notes_var, style="Dark.TEntry").grid(
            row=2, column=1, sticky="ew"
        )
        commands = [
            ("New Storyboard", self._new_storyboard),
            ("Save", self._save_storyboard),
            ("Save As / Duplicate", lambda: self._save_storyboard(as_copy=True)),
            ("Open", self._open_storyboard),
            ("Rename", self._rename_storyboard),
            ("Export JSON", self._export_storyboard),
            ("Import JSON", self._import_storyboard),
            ("Preview Sequence Summary", self._preview_storyboard),
            ("Accept Current Media", self._accept_media),
            ("Use Selected Workflow", self._use_selected_workflow),
        ]
        # A small grid keeps every action keyboard-reachable at narrow widths.
        buttons = ttk.Frame(body, style="Panel.TFrame")
        buttons.grid(row=6, column=0, sticky="ew")
        for index, (label, command) in enumerate(commands):
            ttk.Button(buttons, text=label, style="Dark.TButton", command=command).grid(
                row=index // 3, column=index % 3, sticky="ew", padx=2, pady=2
            )
        for column in range(3):
            buttons.columnconfigure(column, weight=1)
        for variable in (self.title_var, self.notes_var, self.clip_name_var):
            variable.trace_add("write", self._changed)
        # The main form is external to this panel; observe its edits on the UI thread.
        self._dirty_poll = self.after(250, self._poll_dirty)

    def _storyboard_destroyed(self, event: Any) -> None:
        if event.widget is self:
            self._runner.close()
            self.after_cancel(self._dirty_poll)

    def _poll_dirty(self) -> None:
        self._changed()
        self._dirty_poll = self.after(250, self._poll_dirty)

    def _capture_storyboard(self) -> StoryboardDraft:
        source, form = self._read_form()
        return self.storyboard.capture(
            source,
            form,
            self.shots(),
            title=self.title_var.get(),
            notes=self.notes_var.get(),
            clip_name=self.clip_name_var.get(),
        )

    def _changed(self, *_args: Any) -> None:
        if not self._tracking:
            return
        self._capture_storyboard()
        self.dirty_var.set(
            "Unsaved changes"
            if self.storyboard.dirty
            else f"Saved — revision {self.storyboard.draft.revision}"
        )

    def _work(self, work: Any, done: Any) -> None:
        if self._busy:
            self.status_var.set("A Storyboard operation is still in progress.")
            return
        self._busy = True
        self.status_var.set("Working on Storyboard…")

        def result(value: Any) -> None:
            self._busy = False
            done(value)

        self._runner.submit(
            "storyboard",
            work,
            on_result=result,
            on_error=lambda exc: self.status_var.set(
                str(exc) if str(exc).startswith("Not queued:") else f"Not completed: {exc}"
            ),
            on_complete=lambda *_args: setattr(self, "_busy", False),
        )

    def _may_replace(self) -> bool:
        self._changed()
        return not self._busy and (
            not self.storyboard.dirty
            or messagebox.askyesno(
                "Unsaved Storyboard", "Discard the unsaved draft changes?", parent=self
            )
        )

    def load_storyboard(self, draft: StoryboardDraft, *, confirm: bool = True) -> bool:
        if confirm and not self._may_replace():
            return False
        self._tracking = False
        self._pinned_workflow = (draft.workflow_id, draft.workflow_version)
        form = {
            **dict(draft.settings),
            "workflow_id": draft.workflow_id,
            "workflow_version": draft.workflow_version,
            "source_image_path": draft.source_path,
        }
        if self._restore_form is not None:
            self._restore_form(form)
        self.storyboard.opened(draft)
        self.title_var.set(draft.title)
        self.notes_var.set(draft.notes)
        self.clip_name_var.set(draft.clip_name)
        for row in self._rows:
            row.frame.destroy()
        self._rows.clear()
        for shot in draft.shots:
            self.add_shot(shot)
        self._tracking = True
        self._changed()
        self.status_var.set(
            "Storyboard opened. Check the source and authored anchors before queueing."
        )
        self.set_expanded(True)
        return True

    def _new_storyboard(self) -> None:
        if not self._may_replace():
            return
        draft = replace(StoryboardDraft.new(), shots=tuple(self._new_shot() for _ in range(2)))
        self.load_storyboard(draft, confirm=False)

    def _saved_result(self, saved: StoryboardDraft, captured: StoryboardDraft) -> None:
        current = self._capture_storyboard()
        self._tracking = False
        self.storyboard.reconcile_save(saved, captured, current)
        self.title_var.set(self.storyboard.draft.title)
        for row, shot in zip(self._rows, self.storyboard.draft.shots, strict=True):
            row.shot_id = shot.shot_id
            row.keyframe_sha256 = shot.keyframe_sha256
        self._tracking = True
        self._changed()
        self.status_var.set(f"Saved Storyboard revision {saved.revision}; nothing queued.")

    def _save_storyboard(self, *, as_copy: bool = False) -> None:
        captured = self._capture_storyboard()
        source, form = self._read_form()
        from src.video.storyboard_readiness import unsupported_controls

        problems = unsupported_controls(form)
        if problems:
            self.status_var.set("Cannot save unsupported form controls: " + " ".join(problems))
            return
        candidate = captured.duplicate() if as_copy else captured
        self._work(
            lambda: self.store.save(record_images(candidate)),
            lambda saved: self._saved_result(saved, captured),
        )

    def _open_storyboard(self) -> None:
        if not self._may_replace():
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Open Storyboard",
            initialdir=str(self.store.root),
            filetypes=[("Storyboard JSON", "*.json")],
        )
        if path:
            if Path(path).resolve().parent != self.store.root.resolve():
                self.status_var.set("Use Import JSON for a Storyboard outside the library.")
                return
            self._work(
                lambda: self.store.load(Path(path).stem), lambda draft: self.load_storyboard(draft)
            )

    def _rename_storyboard(self) -> None:
        name = simpledialog.askstring(
            "Rename Storyboard", "Title", initialvalue=self.title_var.get(), parent=self
        )
        if name is not None:
            self.title_var.set(name)
            self._save_storyboard()

    def _export_storyboard(self) -> None:
        draft = self._capture_storyboard()
        from src.video.storyboard_readiness import unsupported_controls

        _, form = self._read_form()
        problems = unsupported_controls(form)
        if problems:
            self.status_var.set("Cannot export unsupported form controls: " + " ".join(problems))
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export to a new JSON file",
            defaultextension=".json",
            filetypes=[("Storyboard JSON", "*.json")],
        )
        if path:
            self._work(
                lambda: self.store.export_json(record_images(draft), path),
                lambda _: self.status_var.set("Exported Storyboard; nothing queued."),
            )

    def _import_storyboard(self) -> None:
        if not self._may_replace():
            return
        path = filedialog.askopenfilename(
            parent=self, title="Import Storyboard JSON", filetypes=[("Storyboard JSON", "*.json")]
        )
        if path:
            self._work(
                lambda: self.store.import_json(path), lambda draft: self.load_storyboard(draft)
            )

    def _preview_storyboard(self) -> None:
        captured = self._capture_storyboard()
        _, form = self._read_form()
        registry = self._registry()

        def work() -> tuple[StoryboardDraft, StoryboardReadiness]:
            draft = record_images(captured)
            return draft, readiness(draft, registry, form)

        def done(result: tuple[StoryboardDraft, StoryboardReadiness]) -> None:
            draft, projection = result
            if self._capture_storyboard().fingerprint() != captured.fingerprint():
                self.status_var.set("Draft changed during preview; check readiness again.")
                return
            self.storyboard.draft = draft
            self._changed()
            self.status_var.set(
                projection.summary
                + (
                    "\nNot ready: " + " ".join(projection.problems)
                    if projection.problems
                    else "\nReady for admission checks."
                )
            )

        self._work(work, done)

    def _accept_media(self) -> None:
        captured = self._capture_storyboard()
        if not messagebox.askyesno(
            "Accept Current Media",
            "Replace recorded identities with the current linked image bytes? Save to retain this change.",
            parent=self,
        ):
            return

        def done(draft: StoryboardDraft) -> None:
            if self._capture_storyboard().fingerprint() == captured.fingerprint():
                self.storyboard.draft = draft
                for row, shot in zip(self._rows, draft.shots, strict=True):
                    row.keyframe_sha256 = shot.keyframe_sha256
                self._changed()
                self.status_var.set(
                    "Current linked media accepted; save the revised draft to retain it."
                )
            else:
                self.status_var.set("Draft changed during media verification; accept again.")

        self._work(lambda: record_images(captured, accept_changed=True), done)

    def _registry(self) -> Any:
        controller = self._session._get_controller()
        registry = getattr(controller, "_workflow_registry", None)
        if registry is None:
            raise StoryboardError("Workflow registry is unavailable.")
        return registry

    def _read_form(self) -> tuple[str, dict[str, Any]]:
        source, form = self._base_read_form()
        if self._pinned_workflow and form.get("workflow_id") == self._pinned_workflow[0]:
            form = {**form, "workflow_version": self._pinned_workflow[1]}
        return source, form

    def _frame_counts(self) -> dict[str, int]:
        _, form = self._base_read_form()
        if self._pinned_workflow and form.get("workflow_id") == self._pinned_workflow[0]:
            from src.video.workflow_frame_count import legal_frame_counts

            try:
                spec = self._registry().get(*self._pinned_workflow)
                return {f"{n} frames": n for n in legal_frame_counts(spec)}
            except (KeyError, StoryboardError):
                return {}
        return self._base_frame_counts()

    def _use_selected_workflow(self) -> None:
        self._pinned_workflow = None
        self.refresh_lengths()
        self._changed()
        self.status_var.set(
            "Storyboard now uses the workflow and version selected in the form; check readiness."
        )

"""The "Driving motion" section of the eval suite editor (PR-VID-MOTION-410).

Presentation only. What a field is, how a bound clip or library asset is merged and how the Motion Library is opened live
in ``src/gui/view_contracts/video_eval_motion_contract.py``; hashing, library verification and image checks run on the
editor's background runner. Nothing here builds a job, queues anything or modifies a library asset or the source video.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING, Any, cast

from src.gui.theme_v2 import style_listbox_widget
from src.gui.view_contracts import video_eval_motion_contract as contract
from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.utils.os_shell import open_file, reveal_in_file_manager
from src.video.video_eval_authoring import (
    EvalSuiteDraft,
    bind_driving_video,
    bind_library_asset,
    bind_source,
)
from src.video.video_eval_motion import as_mapping

VIDEO_FILES = [("Driving video", "*.mp4 *.mov *.mkv *.webm"), ("All files", "*.*")]
IMAGE_FILES = [("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"), ("All files", "*.*")]


class LibraryPicker(tk.Toplevel):
    """A small modal list of cataloged clips; choosing one reports its id and closes."""

    def __init__(self, parent: tk.Misc, store: Any, on_choose: Callable[[str], None]) -> None:
        super().__init__(parent)
        self.title("Choose a Motion Library clip")
        self.transient(parent.winfo_toplevel())
        self._store = store
        self._on_choose = on_choose
        self._choices: tuple[contract.LibraryChoice, ...] = ()
        self.query = tk.StringVar(master=self)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Entry(self, textvariable=self.query).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.listing = tk.Listbox(self, width=60, height=14, exportselection=False)
        style_listbox_widget(self.listing)
        self.listing.grid(row=1, column=0, sticky="nsew", padx=8)
        self.listing.bind("<Double-Button-1>", lambda _event: self.choose())
        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="e", padx=8, pady=8)
        ttk.Button(actions, text="Bind this clip", command=self.choose).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="left")
        self.query.trace_add("write", lambda *_args: self.refresh())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.refresh()

    def refresh(self) -> None:
        self._choices = contract.library_choices(self._store, self.query.get())
        self.listing.delete(0, "end")
        for choice in self._choices:
            self.listing.insert("end", choice.label)
        if self._choices:
            self.listing.selection_set(0)

    def choose(self) -> None:
        selected = self.listing.curselection()  # type: ignore[no-untyped-call]
        if not selected:
            return
        asset_id = self._choices[selected[0]].asset_id
        self.destroy()
        self._on_choose(asset_id)


class MotionEditorMixin:
    """Adds the driving-motion section to ``VideoEvalEditorDialog`` (the dialog supplies the helpers declared below)."""

    if TYPE_CHECKING:
        draft: EvalSuiteDraft
        indices: dict[str, int]
        _ask_open: Callable[..., str]
        _confirm_discard: Callable[..., bool]
        _busy: bool

        def _field(
            self,
            frame: ttk.Frame | ttk.LabelFrame,
            label: str,
            data: dict[str, Any],
            key: str,
            *,
            choices: tuple[str, ...] = (),
            read: Callable[[Any], str] = ...,
            parse: Callable[[str], Any] = ...,
            changed: Callable[[], None] | None = None,
            browse: Callable[[], None] | None = None,
        ) -> None: ...
        def _prompt(self, parent: Any, label: str, data: dict[str, Any], key: str) -> None: ...
        def _notice(self, parent: Any, text: str) -> None: ...
        def _form_buttons(
            self, frame: Any, buttons: list[tuple[str, Callable[[], None]]]
        ) -> None: ...
        def _case_changed(self) -> None: ...
        def _changed(self) -> None: ...
        def _render(self) -> None: ...
        def _show_results(self, status: str, messages: tuple[str, ...] = ()) -> None: ...
        def _start(
            self,
            name: str,
            work: Callable[[], WorkOutcome],
            finish: Callable[[WorkOutcome], None],
            status: str,
            *,
            saving: bool = False,
        ) -> None: ...

    # ------------------------------------------------------------------ rendering

    def _motion_section(self, frame: ttk.Frame, record: dict[str, Any]) -> None:
        motion = record.get("motion")
        if motion is None:
            self._form_buttons(
                frame,
                [
                    ("Add Driving Motion", lambda: self._add_motion(record)),
                    ("Duplicate Case for Another Source…", lambda: self._duplicate_case()),
                ],
            )
            return
        box = ttk.LabelFrame(frame, text="Driving motion reference", padding=6)
        box.columnconfigure(1, weight=1)
        box.grid(row=frame.grid_size()[1], column=0, columnspan=2, sticky="ew", pady=4)
        if not isinstance(motion, dict):
            self._notice(
                box, "This case's driving motion data is invalid. Remove it to start again."
            )
            self._form_buttons(
                box, [("Remove Driving Motion", lambda: self._remove_motion(record))]
            )
            return
        for line in contract.summary_lines(motion):
            self._notice(box, line)
        self._form_buttons(
            box,
            [
                ("Bind Local Video…", lambda: self._bind_local(motion)),
                ("Bind Motion Library Clip…", lambda: self._bind_library(motion)),
                ("Open Driving Video", lambda: self._open_bound(motion, reveal=False)),
                ("Reveal", lambda: self._open_bound(motion, reveal=True)),
            ],
        )
        view = {"category": contract.category_label(motion.get("category"))}

        def category_changed() -> None:
            motion["category"] = contract.category_key(view["category"])

        self._field(
            box,
            "Motion category",
            view,
            "category",
            choices=contract.CATEGORY_LABELS,
            changed=category_changed,
        )
        for key, label, kind in contract.TEXT_FIELDS:
            if kind == "text":
                self._prompt(box, label, motion, key)
            else:
                self._field(box, label, motion, key)
        window = cast(dict[str, Any], motion.setdefault("window", {}))
        self._field(
            box, "Window start frame", window, "start_frame", read=_read_frame, parse=_parse_start
        )
        self._field(
            box,
            "Window end frame (exclusive, blank = to the end)",
            window,
            "end_frame",
            read=_read_frame,
            parse=contract.whole_or_none,
        )
        preparation = cast(dict[str, Any], motion.setdefault("preparation", {}))
        mode_view = {
            "mode": contract.PREPARATION_LABELS.get(str(preparation.get("mode") or "as_is"), "")
        }

        def mode_changed() -> None:
            preparation["mode"] = contract.preparation_mode_for(mode_view["mode"])

        self._field(
            box,
            "Preparation",
            mode_view,
            "mode",
            choices=contract.preparation_choice_labels(),
            changed=mode_changed,
        )
        self._field(
            box,
            "Frame-rate conversion",
            preparation,
            "fps_conversion",
            choices=contract.FPS_CONVERSIONS,
        )
        notes = cast(dict[str, Any], motion.setdefault("annotations", {}))
        for key, label in contract.ANNOTATION_FIELDS:
            self._field(box, label, notes, key)
        self._form_buttons(
            box,
            [
                ("Duplicate Case for Another Source…", lambda: self._duplicate_case()),
                ("Remove Driving Motion", lambda: self._remove_motion(record)),
            ],
        )

    # ------------------------------------------------------------------ actions

    def _add_motion(self, record: dict[str, Any]) -> None:
        record["motion"] = {}
        self._case_changed()

    def _remove_motion(self, record: dict[str, Any]) -> None:
        if self._confirm_discard(
            "Remove driving motion", "Remove this case's driving-motion reference?", parent=self
        ):
            record.pop("motion", None)
            self._case_changed()

    def _bind_local(self, motion: dict[str, Any]) -> None:
        path = self._ask_open(
            parent=self, title="Bind a local driving video", filetypes=VIDEO_FILES
        )
        if not path:
            return

        def done(outcome: WorkOutcome) -> None:
            contract.merge_bound(motion, outcome.value)
            self._case_changed()
            self._show_results(
                f"Bound {Path(path).name} as a local video (provenance not verified)."
            )

        self._start(
            "BindDriver",
            lambda: WorkOutcome(value=bind_driving_video(Path(path))),
            done,
            "Hashing the driving video…",
        )

    def _bind_library(self, motion: dict[str, Any]) -> None:
        store, message = contract.open_library_store()
        if store is None:
            self._show_results("Motion Library unavailable.", (message,))
            return

        def chosen(asset_id: str) -> None:
            def done(outcome: WorkOutcome) -> None:
                contract.merge_bound(motion, outcome.value)
                self._case_changed()
                self._show_results(
                    f"Bound Motion Library clip {asset_id}; its bytes were verified."
                )

            self._start(
                "BindLibraryAsset",
                lambda: WorkOutcome(value=bind_library_asset(store, asset_id)),
                done,
                "Verifying the library clip…",
            )

        LibraryPicker(cast(tk.Misc, self), store, chosen)

    def _duplicate_case(self) -> None:
        index = self.indices["case"]
        if not 0 <= index < len(self.draft.cases):
            return
        path = self._ask_open(
            parent=self, title="Choose the other source image", filetypes=IMAGE_FILES
        )
        if not path:
            return

        def done(outcome: WorkOutcome) -> None:
            self.draft.duplicate_case_for_source(index, outcome.value)
            self.indices["case"] = len(self.draft.cases) - 1
            self._changed()
            self._render()
            self._show_results(
                "Duplicated the case for another source image; arms are shared, none was added."
            )

        self._start(
            "DuplicateCase",
            lambda: WorkOutcome(value=bind_source(Path(path))),
            done,
            "Checking the source image…",
        )

    def _open_bound(self, motion: dict[str, Any], *, reveal: bool) -> None:
        driving = as_mapping(motion.get("driving"))
        target = str(driving.get("path") or "")
        result = reveal_in_file_manager(target) if reveal else open_file(target)
        if not result.ok:
            self._show_results("Could not open the driving video.", (result.message,))


def _read_frame(value: Any) -> str:
    return "" if value is None else str(value)


def _parse_start(text: str) -> int | str:
    parsed = contract.whole_or_none(text)
    return 0 if parsed is None else parsed


__all__ = ["MotionEditorMixin", "LibraryPicker"]

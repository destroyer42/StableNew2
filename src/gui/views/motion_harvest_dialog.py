"""Tk workspace for Harvest Motion (PR-VID-MOTION-400).  Presentation only.

Every rule - window arithmetic, cadence, lineage, stale-result suppression, what Save does - lives in
``MotionHarvestSession``.  Hashing, probing, frame decoding and FFmpeg run on workers owned by the existing
``ThreadRegistry``; results return through ``TkUiDispatcher`` and are dropped after the window closes.  The window is
not modal, never queues a job, never starts a runtime and never edits the Video Workflow form.  Playback reuses the
shared ``MediaInspector`` (its bounded decoder and content-visibility policy).
"""

from __future__ import annotations

import base64
import functools
import io
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from PIL import Image

from src.gui.theme_v2 import style_text_widget
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.motion_harvest_contract import (
    CADENCE_LABELS,
    HarvestPorts,
    HarvestView,
    MotionHarvestSession,
    SavedWindow,
)
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.views.video_workflow_motion_library_panel_v2 import EDIT_FIELDS, TRISTATE
from src.gui.widgets.media_inspector import MediaInspector
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.utils.thread_registry import get_thread_registry
from src.video.motion_library.harvest_service import FramePreview, HarvestSourceRef
from src.video.motion_library.models import CADENCES

_INTRO = (
    "Cut the part of a video that contains the motion you want into a reusable Motion Library clip. The original is "
    "never changed. Nothing here queues a job or uses the GPU; the clip is not tied to any workflow."
)
_ENTRY_DEBOUNCE_MS = 250
_SOURCE_THUMB = 240
# The window's own fields; "name" has its own box and the origin/provenance fields belong to the library clip.
_SKIPPED_FIELDS = {"display_name", "provenance_notes"}
_SINGLE_LINE_UNITS = (("Frames", "frames"), ("Seconds", "seconds"))


def photo_from_png(png: bytes) -> tk.PhotoImage:
    return tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))


class MotionHarvestDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        ports: HarvestPorts,
        on_saved: Callable[[SavedWindow], None] | None = None,
        runner: BackgroundWorkRunner | None = None,
        decode: Any = None,
        source_image: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(master)
        self.title("Harvest Motion")
        self.transient(master.winfo_toplevel())
        self.geometry("1180x860")
        self._closed = False
        self._runner = runner
        self._decode = decode
        self._source_image = source_image
        self._applying = False
        self._entry_job: str | None = None
        self._previewed_path = ""
        self._photos: list[tk.PhotoImage] = []
        self._source_photo: tk.PhotoImage | None = None
        self._source_token = 0
        self.status_var = tk.StringVar(self)
        self.title_var = tk.StringVar(self, value="Harvest Motion")
        self.frame_var = tk.DoubleVar(self, value=0.0)
        self.unit_var = tk.StringVar(self, value="frames")
        self.start_var = tk.StringVar(self)
        self.end_var = tk.StringVar(self)
        self.cadence_var = tk.StringVar(self, value=CADENCES[0])
        self.name_var = tk.StringVar(self)
        self.edit_vars: dict[str, tk.StringVar | tk.BooleanVar] = {}
        self.edit_texts: dict[str, tk.Text] = {}
        self.session = MotionHarvestSession(
            ports=ports,
            runner=self._work_runner(),
            on_change=self._render,
            on_saved=on_saved,
        )
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Escape>", lambda _e: self.destroy())
        self._render()

    # ------------------------------------------------------------------ plumbing

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Harvest a motion window without blocking Tk",
                ),
                dispatch=lambda fn: dispatcher.invoke(lambda: self._deliver(fn)),
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        if self._closed:
            return
        try:
            if self.winfo_exists():
                finish()
        except tk.TclError:
            pass  # the widget tree is going away

    def open_source(self, ref: HarvestSourceRef) -> None:
        """Bind the workspace to one exact file (the handoff entry point)."""

        if self._closed:
            return
        self._previewed_path = ""
        self.name_var.set("")
        self.session.open(ref)
        self.lift()

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        page = ScrollableFrame(self)
        page.grid(row=0, column=0, sticky="nsew")
        body = ttk.Frame(page.inner, padding=10)
        body.grid(row=0, column=0, sticky="nsew")
        page.inner.columnconfigure(0, weight=1)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)

        header = ttk.Frame(body)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self.title_var, font=("TkDefaultFont", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        intro = ttk.Label(header, text=_INTRO, justify="left")
        intro.grid(row=1, column=0, sticky="ew")
        bind_wraplength(intro)
        status = ttk.Label(header, textvariable=self.status_var, justify="left")
        status.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        bind_wraplength(status)

        self._build_viewer(body)
        self._build_controls(body)

    def _build_viewer(self, body: ttk.Frame) -> None:
        left = ttk.Frame(body)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        self.player = MediaInspector(
            left, decode=self._decode, edge=420, scale=1, allow_original=False
        )
        self.player.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.playback_label = ttk.Label(left, justify="left")
        self.playback_label.grid(row=1, column=0, sticky="ew")
        bind_wraplength(self.playback_label)

        scrub = ttk.LabelFrame(left, text="Frame", padding=6)
        scrub.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        scrub.columnconfigure(2, weight=1)
        self.scale = ttk.Scale(
            scrub,
            from_=0,
            to=1,
            orient="horizontal",
            variable=self.frame_var,
            command=self._on_scrub,
        )
        self.scale.grid(row=0, column=0, columnspan=5, sticky="ew")
        self.step_buttons: list[ttk.Button] = []
        for column, (text, delta) in enumerate((("-10", -10), ("-1", -1), ("+1", 1), ("+10", 10))):
            button = ttk.Button(
                scrub, text=text, width=5, command=functools.partial(self.session.step, delta)
            )
            button.grid(
                row=1,
                column=column if column < 2 else column + 1,
                pady=(4, 0),
                sticky="w" if column < 2 else "e",
            )
            self.step_buttons.append(button)
        self.frame_label = ttk.Label(scrub, justify="center")
        self.frame_label.grid(row=1, column=2, pady=(4, 0))
        self.current_image = ttk.Label(scrub)
        self.current_image.grid(row=2, column=0, columnspan=5, pady=(6, 0), sticky="w")
        self.source_image_label = ttk.Label(scrub, justify="left")
        self.source_image_label.grid(row=2, column=2, columnspan=3, pady=(6, 0), sticky="e")
        self.source_compat_label = ttk.Label(scrub, justify="left")
        self.source_compat_label.grid(row=3, column=0, columnspan=5, sticky="ew")
        bind_wraplength(self.source_compat_label)
        self.compare_button = ttk.Button(
            scrub, text="Compare with source image", command=self._on_compare_source
        )
        if self._source_image is not None:
            self.compare_button.grid(row=4, column=0, columnspan=5, sticky="w", pady=(4, 0))

        self.original_frames = ttk.LabelFrame(
            left, text="Original: first / middle / last", padding=6
        )
        self.original_frames.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.window_frames = ttk.LabelFrame(
            left, text="Selected window: first / middle / last", padding=6
        )
        self.window_frames.grid(row=4, column=0, sticky="ew", pady=(6, 0))

    def _build_controls(self, body: ttk.Frame) -> None:
        right = ttk.Frame(body)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self.source_text = self._text_block(right, 0, "Source", height=9)
        self.lineage_label = ttk.Label(right, justify="left")
        self.lineage_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        bind_wraplength(self.lineage_label)
        self.notes_label = ttk.Label(right, justify="left", foreground="#d9534f")
        self.notes_label.grid(row=2, column=0, sticky="ew")
        bind_wraplength(self.notes_label)
        self.existing_label = ttk.Label(right, justify="left")
        self.existing_label.grid(row=3, column=0, sticky="ew")
        bind_wraplength(self.existing_label)

        window = ttk.LabelFrame(right, text="Action window", padding=8)
        window.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        window.columnconfigure(1, weight=1)
        units = ttk.Frame(window)
        units.grid(row=0, column=0, columnspan=4, sticky="w")
        for column, (text, value) in enumerate(_SINGLE_LINE_UNITS):
            ttk.Radiobutton(
                units, text=text, value=value, variable=self.unit_var, command=self._on_unit
            ).grid(row=0, column=column, padx=(0, 10))
        ttk.Label(window, text="Start").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.start_entry = ttk.Entry(window, textvariable=self.start_var, width=12)
        self.start_entry.grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(window, text="End (not included)").grid(
            row=1, column=2, sticky="w", padx=(10, 6), pady=(6, 0)
        )
        self.end_entry = ttk.Entry(window, textvariable=self.end_var, width=12)
        self.end_entry.grid(row=1, column=3, sticky="w", pady=(6, 0))
        for var in (self.start_var, self.end_var):
            var.trace_add("write", self._on_entry)
        buttons = ttk.Frame(window)
        buttons.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.set_start_button = ttk.Button(
            buttons, text="Set Start to Current", command=self.session.set_start_to_current
        )
        self.set_end_button = ttk.Button(
            buttons, text="Set End after Current", command=self.session.set_end_after_current
        )
        self.reset_button = ttk.Button(
            buttons, text="Reset to full video", command=self.session.reset_window
        )
        for column, button in enumerate(
            (self.set_start_button, self.set_end_button, self.reset_button)
        ):
            button.grid(row=0, column=column, padx=(0, 6))
        self.window_label = ttk.Label(window, justify="left")
        self.window_label.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        bind_wraplength(self.window_label)
        self.window_error = ttk.Label(window, justify="left", foreground="#d9534f")
        self.window_error.grid(row=4, column=0, columnspan=4, sticky="ew")
        bind_wraplength(self.window_error)

        cadence = ttk.LabelFrame(right, text="Frame rate of the saved clip", padding=8)
        cadence.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        for row, value in enumerate(CADENCES):
            ttk.Radiobutton(
                cadence,
                text=CADENCE_LABELS[value],
                value=value,
                variable=self.cadence_var,
                command=self._on_cadence,
            ).grid(row=row, column=0, sticky="w")
        self.workflow_label = ttk.Label(right, justify="left")
        self.workflow_label.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        bind_wraplength(self.workflow_label)

        self._build_metadata(right, 7)

        actions = ttk.Frame(right)
        actions.grid(row=8, column=0, sticky="ew", pady=(8, 0))
        self.save_button = ttk.Button(actions, text="Save as Motion Asset", command=self._on_save)
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.session.cancel)
        self.close_button = ttk.Button(actions, text="Close", command=self.destroy)
        for column, button in enumerate((self.save_button, self.cancel_button, self.close_button)):
            button.grid(row=0, column=column, padx=(0, 6))
        self.saved_label = ttk.Label(right, justify="left")
        self.saved_label.grid(row=9, column=0, sticky="ew", pady=(6, 0))
        bind_wraplength(self.saved_label)

    def _text_block(self, parent: ttk.Frame, row: int, title: str, *, height: int) -> tk.Text:
        frame = ttk.LabelFrame(parent, text=title, padding=6)
        frame.grid(row=row, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        text = tk.Text(frame, height=height, wrap="word", state="disabled", takefocus=True)
        style_text_widget(text, elevated=True)
        text.grid(row=0, column=0, sticky="ew")
        return text

    def _build_metadata(self, parent: ttk.Frame, row: int) -> None:
        section = ttk.LabelFrame(
            parent, text="Describe this motion (all optional except the name)", padding=8
        )
        section.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        section.columnconfigure(1, weight=1)
        ttk.Label(section, text="Name").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        ttk.Entry(section, textvariable=self.name_var).grid(
            row=0, column=1, sticky="ew", pady=(0, 4)
        )
        line = 1
        for key, label, kind, choices in EDIT_FIELDS:
            if key in _SKIPPED_FIELDS:
                continue
            ttk.Label(section, text=label).grid(
                row=line, column=0, sticky="nw", padx=(0, 6), pady=(0, 4)
            )
            if kind == "check":
                var: tk.StringVar | tk.BooleanVar = tk.BooleanVar(self, value=False)
                ttk.Checkbutton(section, variable=var).grid(row=line, column=1, sticky="w")
            elif kind in {"combo", "tristate"}:
                var = tk.StringVar(self, value=TRISTATE[0] if kind == "tristate" else "")
                values = list(choices) if kind == "tristate" else ["", *choices]
                ttk.Combobox(
                    section, state="readonly", textvariable=var, values=values, width=22
                ).grid(row=line, column=1, sticky="w", pady=(0, 4))
            elif kind == "text":
                var = tk.StringVar(self)
                text = tk.Text(section, height=3, wrap="word")
                style_text_widget(text, elevated=True)
                text.grid(row=line, column=1, sticky="ew", pady=(0, 4))
                self.edit_texts[key] = text
            else:
                var = tk.StringVar(self)
                ttk.Entry(section, textvariable=var).grid(
                    row=line, column=1, sticky="ew", pady=(0, 4)
                )
            self.edit_vars[key] = var
            line += 1
        note = ttk.Label(
            section,
            text=(
                "Visual quality, whether the requested motion was achieved, and 'good for motion driving' are your "
                "own opinions. They do not show that the motion will transfer to another subject."
            ),
            justify="left",
        )
        note.grid(row=line, column=0, columnspan=2, sticky="ew")
        bind_wraplength(note)

    def collect_annotations(self) -> dict[str, Any]:
        """Only the details the operator actually filled in; an empty field never overwrites an inherited default."""

        out: dict[str, Any] = {}
        for key, var in self.edit_vars.items():
            if key in self.edit_texts:
                value: Any = self.edit_texts[key].get("1.0", "end").strip()
            elif isinstance(var, tk.BooleanVar):
                value = True if var.get() else None
            elif key == "motion_achieved":
                value = {"Yes": True, "No": False}.get(str(var.get()))
            elif key == "subject_count":
                text = str(var.get()).strip()
                value = int(text) if text.isdigit() else None
            else:
                value = str(var.get()).strip()
            if value not in ("", None):
                out[key] = value
        return out

    # ------------------------------------------------------------------ commands

    def _on_scrub(self, value: str) -> None:
        if self._applying or self._closed:
            return
        try:
            self.session.seek(round(float(value)))
        except (TypeError, ValueError):
            pass

    def _on_unit(self) -> None:
        if not self._applying and not self._closed:
            self._cancel_entry_job()
            self.session.set_unit(self.unit_var.get())

    def _on_cadence(self) -> None:
        if not self._applying and not self._closed:
            self.session.set_cadence(self.cadence_var.get())

    def _cancel_entry_job(self) -> None:
        if self._entry_job is not None:
            try:
                self.after_cancel(self._entry_job)
            except tk.TclError:
                pass
            self._entry_job = None

    def _on_entry(self, *_args: Any) -> None:
        if self._applying or self._closed:
            return
        self._cancel_entry_job()
        self._entry_job = self.after(_ENTRY_DEBOUNCE_MS, self._commit_entries)

    def _commit_entries(self) -> None:
        self._entry_job = None
        if not self._closed:
            self.session.set_window_text(self.start_var.get(), self.end_var.get())

    def _on_save(self) -> None:
        self._commit_entries_now()
        self.session.save(self.name_var.get(), self.collect_annotations())

    def _commit_entries_now(self) -> None:
        if self._entry_job is not None:
            self._cancel_entry_job()
            self.session.set_window_text(self.start_var.get(), self.end_var.get())

    def _on_compare_source(self) -> None:
        """Show the workflow's current source image beside the current frame (display only; read on a worker)."""

        provider = self._source_image
        if provider is None:
            return
        path = str(provider() or "").strip()
        view = self.session.view()
        self._source_token += 1
        token = self._source_token
        if not path:
            self.source_compat_label.configure(
                text="No source image is selected in the Video Workflow."
            )
            return
        runner = self._work_runner()
        facts = view.source_lines

        def work() -> WorkOutcome:
            try:
                with Image.open(path) as image:
                    width, height = image.size
                    thumb = image.convert("RGB")
                    thumb.thumbnail((_SOURCE_THUMB, _SOURCE_THUMB))
                    buffer = io.BytesIO()
                    thumb.save(buffer, format="PNG")
                return WorkOutcome(value=(width, height, buffer.getvalue()))
            except (OSError, ValueError) as exc:
                return WorkOutcome(error=f"The source image could not be read: {exc}")

        def done(outcome: WorkOutcome) -> None:
            if self._closed or token != self._source_token:
                return
            if outcome.error:
                self.source_compat_label.configure(text=str(outcome.error))
                return
            width, height, png = outcome.value
            self._source_photo = photo_from_png(png)
            self.source_image_label.configure(
                image=self._source_photo, text="Source image", compound="top"
            )
            self.source_compat_label.configure(text=self._compat_text(width, height, facts))

        runner.start("motion-harvest-source-image", work, done)

    @staticmethod
    def _compat_text(width: int, height: int, source_lines: tuple[str, ...]) -> str:
        dims = next((line for line in source_lines if line.startswith("Dimensions:")), "")
        digits = [int(p) for p in dims.replace("x", " ").replace("(", " ").split() if p.isdigit()]
        if len(digits) < 2 or not height:
            return f"Source image: {width} x {height}."

        def shape(w: int, h: int) -> str:
            return "square" if w == h else "landscape" if w > h else "portrait"

        same = shape(width, height) == shape(digits[0], digits[1])
        return (
            f"Source image {width} x {height} ({shape(width, height)}); video {digits[0]} x {digits[1]} "
            f"({shape(digits[0], digits[1])}). "
            + (
                "The orientation matches."
                if same
                else "The orientation differs; check how the workflow fits it."
            )
            + " This is only a visual check; nothing is changed."
        )

    # ------------------------------------------------------------------ render

    def _render(self) -> None:
        if self._closed:
            return
        try:
            self._apply(self.session.view())
        except tk.TclError:
            pass

    def _apply(self, view: HarvestView) -> None:
        self._applying = True
        try:
            self.title_var.set(view.title)
            self.status_var.set(view.status)
            self.unit_var.set(view.unit)
            self.cadence_var.set(view.cadence)
            if self.start_var.get() != view.start_text:
                self.start_var.set(view.start_text)
            if self.end_var.get() != view.end_text:
                self.end_var.set(view.end_text)
            top = max(1, (view.frame_count or 1) - 1)
            self.scale.configure(to=top)
            if round(float(self.frame_var.get())) != view.current_frame:
                self.frame_var.set(view.current_frame)
        finally:
            self._applying = False

        if view.loaded and not view.hidden and view.media_path:
            if view.media_path != self._previewed_path:
                self._previewed_path = view.media_path
                ref = self.session.ref
                self.player.set_media(
                    view.media_path, "video", subject=ref.subject if ref is not None else None
                )
        elif self._previewed_path:
            self._previewed_path = ""
            self.player.stop()
        self.playback_label.configure(
            text=view.playback_note if view.loaded and not view.hidden else ""
        )
        total = view.frame_count if view.frame_count is not None else "?"
        self.frame_label.configure(
            text=f"Frame {view.current_frame} of {total}"
            + (f"   {view.current_time}" if view.current_time else "")
        )
        self._render_images(view)
        self._set_text(self.source_text, "\n".join(view.source_lines) or "No video is open.")
        self.lineage_label.configure(text="\n".join(view.lineage_lines))
        self.notes_label.configure(text="\n".join((*view.notes, *view.preview_issues)))
        self.existing_label.configure(text="\n".join(view.existing_lines))
        window = view.window
        self.window_label.configure(
            text="\n".join(window.lines)
            + (f"\nDuration: {window.duration_text}" if window.lines else "")
            if window is not None
            else ""
        )
        self.window_error.configure(
            text=window.error if window is not None and not window.ok else ""
        )
        self.workflow_label.configure(text="\n".join(view.workflow_lines))
        self.saved_label.configure(
            text="\n".join(
                f"Saved: '{s.name}' frames {s.start_frame}-{s.end_frame - 1} ({s.status})"
                for s in view.saved
            )
        )
        loaded = "normal" if view.loaded and not view.hidden and not view.busy else "disabled"
        controls: list[Any] = [
            self.set_start_button,
            self.set_end_button,
            self.reset_button,
            self.start_entry,
            self.end_entry,
            *self.step_buttons,
        ]
        for widget in controls:
            widget.configure(state=loaded)
        self.save_button.configure(state="normal" if view.can_save else "disabled")
        self.cancel_button.configure(state="normal" if view.can_cancel else "disabled")
        self.compare_button.configure(
            state="normal" if view.loaded and not view.hidden else "disabled"
        )

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _render_images(self, view: HarvestView) -> None:
        self._photos.clear()
        if view.current_preview is not None:
            photo = photo_from_png(view.current_preview.png_bytes)
            self._photos.append(photo)
            self.current_image.configure(image=photo)
        else:
            self.current_image.configure(image="")
        self._fill_strip(self.original_frames, view.original_previews)
        self._fill_strip(self.window_frames, view.window_previews)

    def _fill_strip(self, parent: ttk.LabelFrame, previews: tuple[FramePreview, ...]) -> None:
        for child in parent.winfo_children():
            child.destroy()
        for column, preview in enumerate(previews):
            photo = photo_from_png(preview.png_bytes)
            self._photos.append(photo)
            ttk.Label(parent, image=photo, text=preview.caption, compound="top").grid(
                row=0, column=column, padx=(0, 6)
            )

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True
            self._cancel_entry_job()
            self.session.close()


__all__ = ["MotionHarvestDialog", "photo_from_png"]

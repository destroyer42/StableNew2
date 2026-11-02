"""Tk dialog for Convert Motion (PR-VID-MOTION-354).  Presentation only.

Every rule lives in ``MotionConversionSession``.  Blender, FFmpeg and hashing run on workers owned by the existing
``ThreadRegistry``; results return through ``TkUiDispatcher`` and are dropped after the dialog is destroyed.  The dialog is
not modal and never queues a job, prepares a motion source or edits the Video Workflow form.
"""

from __future__ import annotations

import io
import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, ttk
from typing import Any

from PIL import Image, ImageTk

from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.motion_conversion_contract import (
    ConversionView,
    MotionConversionSession,
)
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.utils.thread_registry import get_thread_registry
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion.ports import ConversionPorts

_ANIMATION_FILETYPES = [("Animation files", "*.fbx *.bvh"), ("All files", "*.*")]
_EXE_FILETYPES = [("Blender", "blender.exe"), ("All files", "*.*")]
_PROFILE_ITEMS = [(cp.PROFILE_LABELS[p], p) for p in cp.PROFILES]
_CAMERA_ITEMS = [
    ("Front", cp.CAMERA_FRONT),
    ("Side", cp.CAMERA_SIDE),
    ("Three-quarter", cp.CAMERA_THREE_QUARTER),
]
_MODE_ITEMS = [
    ("Static camera", cp.CAMERA_STATIC),
    ("Camera follows the subject", cp.CAMERA_TRACKING),
]
_ROOT_ITEMS = [
    ("Keep original root motion", cp.ROOT_PRESERVE),
    ("Remove root translation (in place)", cp.ROOT_IN_PLACE),
]
_ORIENT_ITEMS = [("Portrait", "portrait"), ("Landscape", "landscape")]
_THUMB = 120
_INTRO = (
    "Render an FBX or BVH animation to a reference video with Blender (CPU only), check it, then add it to the Motion "
    "Library. Nothing here queues a job or uses the GPU. The original file is never changed."
)


def _label_to_value(items: list[tuple[str, str]], label: str) -> str:
    return next((value for text, value in items if text == label), items[0][1])


def _value_to_label(items: list[tuple[str, str]], value: str) -> str:
    return next((text for text, v in items if v == value), items[0][0])


class MotionConversionDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        ports: ConversionPorts,
        on_accepted: Callable[[str], None] | None = None,
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        super().__init__(master)
        self.title("Convert Motion")
        self.transient(master.winfo_toplevel())
        self.geometry("760x820")
        self._closed = False
        self._runner = runner
        self._photos: list[ImageTk.PhotoImage] = []
        self._applying = False
        self.status_var = tk.StringVar(self)
        self.blender_var = tk.StringVar(self)
        self.profile_var = tk.StringVar(self)
        self.camera_var = tk.StringVar(self, value=_CAMERA_ITEMS[0][0])
        self.mode_var = tk.StringVar(self, value=_MODE_ITEMS[0][0])
        self.root_var = tk.StringVar(self, value=_ROOT_ITEMS[0][0])
        self.orient_var = tk.StringVar(self, value=_ORIENT_ITEMS[0][0])
        self.start_var = tk.StringVar(self, value="0")
        self.frames_var = tk.StringVar(self)
        self.name_var = tk.StringVar(self)
        self.tags_var = tk.StringVar(self)
        self.terms_var = tk.StringVar(self)
        self.session = MotionConversionSession(
            ports=ports, runner=self._work_runner(), on_change=self._render, on_accepted=on_accepted
        )
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.session.load_remembered_blender()
        self._render()

    # ------------------------------------------------------------------ build

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Convert a motion asset with Blender without blocking Tk",
                ),
                dispatch=lambda fn: dispatcher.invoke(lambda: self._deliver(fn)),
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        if not self._closed:
            finish()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body = ttk.Frame(self, padding=10)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        intro = ttk.Label(body, text=_INTRO, justify="left")
        intro.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        bind_wraplength(intro)

        ttk.Label(body, text="Blender").grid(row=1, column=0, sticky="w", padx=(0, 6))
        ttk.Label(body, textvariable=self.blender_var).grid(row=1, column=1, sticky="w")
        self.blender_button = ttk.Button(
            body, text="Choose Blender...", command=self._on_choose_blender
        )
        self.blender_button.grid(row=1, column=2, sticky="e")
        ttk.Label(body, text="Animation").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        self.source_button = ttk.Button(
            body, text="Choose animation file...", command=self._on_choose_source
        )
        self.source_button.grid(row=2, column=1, sticky="w", pady=(6, 0))
        self.inspect_button = ttk.Button(body, text="Inspect", command=self.session.inspect)
        self.inspect_button.grid(row=2, column=2, sticky="e", pady=(6, 0))
        self.source_label = ttk.Label(body, justify="left")
        self.source_label.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 6))
        bind_wraplength(self.source_label)

        options = ttk.LabelFrame(body, text="Conversion", padding=8)
        options.grid(row=4, column=0, columnspan=3, sticky="ew")
        options.columnconfigure(1, weight=1)
        options.columnconfigure(3, weight=1)
        self.profile_combo = self._combo(
            options, 0, 0, "Look", self.profile_var, [t for t, _ in _PROFILE_ITEMS]
        )
        self._combo(options, 0, 2, "Camera", self.camera_var, [t for t, _ in _CAMERA_ITEMS])
        self._combo(options, 1, 0, "Camera mode", self.mode_var, [t for t, _ in _MODE_ITEMS])
        self._combo(options, 1, 2, "Root motion", self.root_var, [t for t, _ in _ROOT_ITEMS])
        self._combo(options, 2, 0, "Shape", self.orient_var, [t for t, _ in _ORIENT_ITEMS])
        ttk.Label(options, text="Start (s)").grid(row=2, column=2, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(options, textvariable=self.start_var, width=8).grid(
            row=2, column=3, sticky="w", pady=2
        )
        ttk.Label(options, text="Frames").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=2)
        self.frames_combo = ttk.Combobox(options, textvariable=self.frames_var, width=8)
        self.frames_combo.grid(row=3, column=1, sticky="w", pady=2)
        self.character_button = ttk.Button(
            options, text="Use reference character...", command=self._on_character
        )
        self.character_button.grid(row=3, column=2, columnspan=2, sticky="w", pady=2)
        for var in (
            self.profile_var,
            self.camera_var,
            self.mode_var,
            self.root_var,
            self.orient_var,
            self.start_var,
            self.frames_var,
        ):
            var.trace_add("write", self._on_option_changed)

        self.plan_label = ttk.Label(body, justify="left")
        self.plan_label.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        bind_wraplength(self.plan_label)
        self.error_label = ttk.Label(body, justify="left", foreground="#d9534f")
        self.error_label.grid(row=6, column=0, columnspan=3, sticky="ew")
        bind_wraplength(self.error_label)

        actions = ttk.Frame(body)
        actions.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.preview_button = ttk.Button(
            actions, text="Preview (short)", command=self.session.render_preview
        )
        self.convert_button = ttk.Button(actions, text="Convert", command=self.session.convert)
        self.condition_button = ttk.Button(
            actions, text="Preview Conditioning", command=self.session.preview_conditioning
        )
        self.cancel_button = ttk.Button(
            actions, text="Cancel work", command=self.session.cancel_work
        )
        for column, button in enumerate(
            (self.preview_button, self.convert_button, self.condition_button, self.cancel_button)
        ):
            button.grid(row=0, column=column, padx=(0, 6))
        self.result_label = ttk.Label(body, justify="left")
        self.result_label.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        bind_wraplength(self.result_label)

        self.thumbs = ttk.Frame(body)
        self.thumbs.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.warnings_label = ttk.Label(body, justify="left")
        self.warnings_label.grid(row=10, column=0, columnspan=3, sticky="ew")
        bind_wraplength(self.warnings_label)

        add = ttk.LabelFrame(body, text="Add to Motion Library", padding=8)
        add.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        add.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate(
            (("Name", self.name_var), ("Tags", self.tags_var), ("Usage terms", self.terms_var))
        ):
            ttk.Label(add, text=label).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
            ttk.Entry(add, textvariable=var).grid(row=row, column=1, sticky="ew", pady=2)
        self.accept_button = ttk.Button(add, text="Add to Motion Library", command=self._on_accept)
        self.accept_button.grid(row=3, column=1, sticky="e", pady=(4, 0))
        self.next_label = ttk.Label(body, justify="left")
        self.next_label.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        bind_wraplength(self.next_label)
        status = ttk.Label(body, textvariable=self.status_var, justify="left")
        status.grid(row=13, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        bind_wraplength(status)

    def _combo(
        self,
        parent: ttk.Frame | ttk.LabelFrame,
        row: int,
        column: int,
        label: str,
        var: tk.StringVar,
        values: list[str],
    ) -> ttk.Combobox:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 6), pady=2)
        combo = ttk.Combobox(parent, state="readonly", textvariable=var, values=values, width=30)
        combo.grid(row=row, column=column + 1, sticky="ew", pady=2)
        return combo

    # ------------------------------------------------------------------ commands

    def _on_choose_blender(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose your Blender executable", filetypes=_EXE_FILETYPES
        )
        if path:
            self.session.choose_blender(path)

    def _on_choose_source(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose an animation file", filetypes=_ANIMATION_FILETYPES
        )
        if path:
            self.session.choose_source(path)

    def _on_character(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a character FBX with the same skeleton",
            filetypes=[("FBX", "*.fbx"), ("All files", "*.*")],
        )
        if path:
            self.session.check_character(path)

    def _on_option_changed(self, *_args: Any) -> None:
        if self._applying or self._closed:
            return
        self.session.set_options(
            profile=_label_to_value(_PROFILE_ITEMS, self.profile_var.get()),
            camera=_label_to_value(_CAMERA_ITEMS, self.camera_var.get()),
            camera_mode=_label_to_value(_MODE_ITEMS, self.mode_var.get()),
            root_motion=_label_to_value(_ROOT_ITEMS, self.root_var.get()),
            orientation=_label_to_value(_ORIENT_ITEMS, self.orient_var.get()),
            start_seconds=self.start_var.get().strip() or "0",
            frames=self.frames_var.get().strip(),
        )

    def _on_accept(self) -> None:
        tags = tuple(t.strip() for t in self.tags_var.get().split(",") if t.strip())
        self.session.accept(self.name_var.get(), tags, self.terms_var.get())

    # ------------------------------------------------------------------ render

    def _render(self) -> None:
        if self._closed:
            return
        try:
            view = self.session.view()
            self._apply(view)
        except tk.TclError:
            pass

    def _apply(self, view: ConversionView) -> None:
        self._applying = True
        try:
            self.status_var.set(view.status)
            self.blender_var.set(view.blender_text)
            self.profile_combo.configure(
                values=[text for text, value in _PROFILE_ITEMS if value in view.allowed_profiles]
            )
            self.profile_var.set(_value_to_label(_PROFILE_ITEMS, self.session.options.profile))
            self.frames_combo.configure(values=[str(n) for n in view.legal_frames])
        finally:
            self._applying = False
        self.source_label.configure(text="\n".join(view.source_lines))
        self.plan_label.configure(text="\n".join(view.plan_lines))
        self.error_label.configure(text=view.plan_error)
        self.result_label.configure(text="\n".join(view.result_lines))
        self.warnings_label.configure(text="\n".join(view.warnings))
        self.next_label.configure(text=view.next_step)
        for button, enabled in (
            (self.blender_button, not view.busy),
            (self.source_button, view.can_choose_source),
            (self.inspect_button, view.can_inspect),
            (self.preview_button, view.can_preview),
            (self.convert_button, view.can_convert),
            (self.condition_button, view.can_condition),
            (self.accept_button, view.can_accept),
            (self.character_button, view.can_inspect or view.can_preview),
        ):
            button.configure(state="normal" if enabled else "disabled")
        self.cancel_button.configure(state="normal" if view.busy else "disabled")
        self._render_thumbs(view)

    def _render_thumbs(self, view: ConversionView) -> None:
        for child in self.thumbs.winfo_children():
            child.destroy()
        self._photos.clear()
        preview = view.conditioning
        if preview is None or not preview.ok:
            return
        for column, frame in enumerate(preview.frames):
            for row, (png, caption) in enumerate(
                ((frame.source_png, "frame"), (frame.edge_png, "edges"))
            ):
                try:
                    image = Image.open(io.BytesIO(png))
                    image.thumbnail((_THUMB, _THUMB))
                    photo = ImageTk.PhotoImage(image)
                except (OSError, ValueError):
                    continue
                self._photos.append(photo)
                cell = ttk.Label(
                    self.thumbs, image=photo, text=f"{frame.label} {caption}", compound="top"
                )
                cell.grid(row=row, column=column, padx=4, pady=2)

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True
            self.session.close()


__all__ = ["MotionConversionDialog"]

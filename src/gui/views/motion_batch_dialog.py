"""Tk dialog for Batch Convert Motion (PR-VID-MOTION-356).  Presentation only.

All state and rules live in ``MotionBatchSession``; this file lays out widgets, forwards clicks, and repaints from the session's
view.  Work runs on a registry-owned worker; the worker only stores progress, which a timer here reads while the dialog is busy.
Nothing here queues a job, starts a model runtime or uses the GPU.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, ttk
from typing import Any

from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.motion_batch_contract import BatchView, MotionBatchSession
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.utils.thread_registry import get_thread_registry
from src.video.motion_conversion import batch as bt
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion.ports import BatchPorts

_POLICY_ITEMS = [(bt.POLICY_LABELS[p], p) for p in bt.POLICIES]
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
_POLL_MS = 300
_INTRO = (
    "Convert every eligible FBX or BVH in a folder (including subfolders) to a verified reference video, one at a time, "
    "with Blender on the CPU. Read the scan, confirm the count, destination and disk budget, convert a small sample "
    "first, then the rest. Originals are never changed, archives are not extracted, and nothing here queues a job or "
    "uses the GPU. Re-running skips files that are already converted."
)


def _label_to_value(items: list[tuple[str, str]], label: str) -> str:
    return next((value for text, value in items if text == label), items[0][1])


class MotionBatchDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        ports: BatchPorts,
        on_finished: Callable[[], None] | None = None,
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        super().__init__(master)
        self.title("Batch Convert Motion")
        self.transient(master.winfo_toplevel())
        self.geometry("820x880")
        self._closed = False
        self._runner = runner
        self._applying = False
        self._poll_id: str | None = None
        self.status_var = tk.StringVar(self)
        self.blender_var = tk.StringVar(self)
        self.folder_var = tk.StringVar(self)
        self.policy_var = tk.StringVar(self, value=_POLICY_ITEMS[0][0])
        self.camera_var = tk.StringVar(self, value=_CAMERA_ITEMS[0][0])
        self.mode_var = tk.StringVar(self, value=_MODE_ITEMS[0][0])
        self.root_var = tk.StringVar(self, value=_ROOT_ITEMS[0][0])
        self.orient_var = tk.StringVar(self, value=_ORIENT_ITEMS[0][0])
        self.start_var = tk.StringVar(self, value="0")
        self.frames_var = tk.StringVar(self)
        self.confirm_var = tk.BooleanVar(self, value=False)
        self.session = MotionBatchSession(
            ports=ports,
            runner=self._work_runner(),
            on_change=self._render,
            on_finished=on_finished,
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
                    purpose="Convert a folder of motion assets with Blender without blocking Tk",
                ),
                dispatch=lambda fn: dispatcher.invoke(lambda: self._deliver(fn)),
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        if not self._closed:
            finish()

    def _combo(
        self, parent: tk.Misc, var: tk.StringVar, items: list[tuple[str, str]], width: int
    ) -> ttk.Combobox:
        box = ttk.Combobox(
            parent,
            textvariable=var,
            values=[text for text, _ in items],
            state="readonly",
            width=width,
        )
        return box

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body = ttk.Frame(self, padding=10)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        intro = ttk.Label(body, text=_INTRO, justify="left")
        intro.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        bind_wraplength(intro)

        top = ttk.Frame(body)
        top.grid(row=1, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, textvariable=self.blender_var).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        self.folder_button = ttk.Button(
            top, text="Choose folder...", command=self._on_choose_folder
        )
        self.folder_button.grid(row=1, column=0, sticky="w", pady=4)
        ttk.Label(top, textvariable=self.folder_var).grid(row=1, column=1, sticky="w", padx=6)
        self.rescan_button = ttk.Button(top, text="Scan again", command=self.session.scan)
        self.rescan_button.grid(row=1, column=2, sticky="e")

        options = ttk.LabelFrame(body, text="Settings for every file", padding=6)
        options.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        options.columnconfigure(1, weight=1)
        rows = (
            ("Rendering", self.policy_var, _POLICY_ITEMS, 60),
            ("Camera", self.camera_var, _CAMERA_ITEMS, 24),
            ("Camera mode", self.mode_var, _MODE_ITEMS, 30),
            ("Root motion", self.root_var, _ROOT_ITEMS, 34),
            ("Orientation", self.orient_var, _ORIENT_ITEMS, 14),
        )
        for row, (label, var, items, width) in enumerate(rows):
            ttk.Label(options, text=label).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
            self._combo(options, var, items, width).grid(row=row, column=1, sticky="w", pady=2)
        ttk.Label(options, text="Start (s)").grid(row=5, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(options, textvariable=self.start_var, width=8).grid(row=5, column=1, sticky="w")
        ttk.Label(options, text="Longest clip (frames)").grid(
            row=6, column=0, sticky="w", padx=(0, 6), pady=2
        )
        self.frames_combo = ttk.Combobox(options, textvariable=self.frames_var, width=8)
        self.frames_combo.grid(row=6, column=1, sticky="w")
        for var in (
            self.policy_var,
            self.camera_var,
            self.mode_var,
            self.root_var,
            self.orient_var,
            self.start_var,
            self.frames_var,
        ):
            var.trace_add("write", self._on_option_changed)

        self.inventory_label = ttk.Label(body, justify="left")
        self.inventory_label.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        bind_wraplength(self.inventory_label)
        self.estimate_label = ttk.Label(body, justify="left")
        self.estimate_label.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        bind_wraplength(self.estimate_label)
        self.warnings_label = ttk.Label(body, justify="left", foreground="#b8860b")
        self.warnings_label.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        bind_wraplength(self.warnings_label)

        self.confirm_check = ttk.Checkbutton(
            body, variable=self.confirm_var, command=self._on_confirm_toggled, text=""
        )
        self.confirm_check.grid(row=6, column=0, sticky="w", pady=(8, 0))

        actions = ttk.Frame(body)
        actions.grid(row=7, column=0, sticky="ew", pady=(6, 0))
        self.sample_button = ttk.Button(
            actions, text=f"Convert sample ({bt.SAMPLE_SIZE})", command=self.session.run_sample
        )
        self.remaining_button = ttk.Button(
            actions, text="Convert remaining", command=self.session.run_remaining
        )
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.session.cancel_work)
        self.copy_button = ttk.Button(actions, text="Copy summary", command=self._on_copy_summary)
        for column, button in enumerate(
            (self.sample_button, self.remaining_button, self.cancel_button, self.copy_button)
        ):
            button.grid(row=0, column=column, padx=(0, 6))

        self.progress_label = ttk.Label(body, justify="left")
        self.progress_label.grid(row=8, column=0, sticky="ew", pady=(6, 0))
        self.result_label = ttk.Label(body, justify="left")
        self.result_label.grid(row=9, column=0, sticky="ew", pady=(4, 0))
        bind_wraplength(self.result_label)
        status = ttk.Label(body, textvariable=self.status_var, justify="left")
        status.grid(row=10, column=0, sticky="ew", pady=(8, 0))
        bind_wraplength(status)

    # ------------------------------------------------------------------ actions

    def _on_choose_folder(self) -> None:
        folder = filedialog.askdirectory(
            parent=self,
            title="Choose a folder of FBX or BVH files (subfolders are included)",
            mustexist=True,
        )
        if folder:
            self.session.choose_folder(folder)

    def _on_option_changed(self, *_args: Any) -> None:
        if self._applying:
            return
        self.session.set_options(
            profile_policy=_label_to_value(_POLICY_ITEMS, self.policy_var.get()),
            camera=_label_to_value(_CAMERA_ITEMS, self.camera_var.get()),
            camera_mode=_label_to_value(_MODE_ITEMS, self.mode_var.get()),
            root_motion=_label_to_value(_ROOT_ITEMS, self.root_var.get()),
            orientation=_label_to_value(_ORIENT_ITEMS, self.orient_var.get()),
            start_seconds=self.start_var.get().strip() or "0",
            frames=self.frames_var.get().strip(),
        )

    def _on_confirm_toggled(self) -> None:
        self.session.set_confirmed(self.confirm_var.get())
        self._render()

    def _on_copy_summary(self) -> None:
        text = self.session.summary_text()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_var.set("The summary was copied to the clipboard.")

    # ------------------------------------------------------------------ render

    def _render(self) -> None:
        if self._closed:
            return
        try:
            self._apply(self.session.view())
        except tk.TclError:
            return
        if self.session.busy and self._poll_id is None:
            self._poll_id = self.after(_POLL_MS, self._tick)

    def _tick(self) -> None:
        self._poll_id = None
        self._render()

    def _apply(self, view: BatchView) -> None:
        self._applying = True
        try:
            self.status_var.set(view.status)
            self.blender_var.set(view.blender_text)
            self.folder_var.set(view.folder)
            self.frames_combo.configure(values=[str(n) for n in view.legal_frames])
            if not self.frames_var.get() and view.legal_frames:
                self.frames_var.set(str(self.session.settings().frames))
            self.confirm_var.set(view.confirmed)
        finally:
            self._applying = False
        self.inventory_label.configure(text="\n".join(view.inventory_lines))
        self.estimate_label.configure(text="\n".join(view.estimate_lines))
        self.warnings_label.configure(text="\n".join(view.warnings))
        self.confirm_check.configure(text=view.confirm_text)
        self.remaining_button.configure(text=view.remaining_label)
        self.progress_label.configure(text=view.progress_text)
        self.result_label.configure(text="\n".join(view.result_lines))
        for button, enabled in (
            (self.folder_button, view.can_choose_folder),
            (self.rescan_button, view.can_choose_folder and bool(view.folder)),
            (self.confirm_check, view.can_confirm),
            (self.sample_button, view.can_sample),
            (self.remaining_button, view.can_remaining),
            (self.copy_button, bool(view.result_lines)),
        ):
            button.configure(state="normal" if enabled else "disabled")
        self.cancel_button.configure(state="normal" if view.busy else "disabled")

    def _on_destroy(self, event: Any = None) -> None:
        if event is not None and event.widget is not self:
            return
        self._closed = True
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
        self.session.close()


__all__ = ["MotionBatchDialog"]

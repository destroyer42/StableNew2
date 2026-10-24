"""The "Create map from image" dialog: thin Tk over ``ReferenceMapFlow`` (PR-IMG-CNET-230).

Presentation only. The flow decides what is possible; this window draws its view, hands the operator's clicks to it and
marshals worker results onto the Tk thread through a polled queue (worker threads never touch a widget). Nothing here
reads an image, hashes a file or runs a model, and nothing queues a job: "Save & Use" saves one map into the OpenPose
library and attaches it to a unit through the callback the panel supplies.
"""

from __future__ import annotations

import base64
import queue
import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, ttk
from typing import Any

from src.conditioning.reference_map.library import SavedMap
from src.gui_v2.controlnet_guidance import modality_label
from src.gui_v2.reference_map_flow import FlowState, FlowView, ReferenceMapFlow

_POLL_MS = 40
MAP_TYPES: tuple[tuple[str, str], ...] = (
    ("canny", "Edges (Canny)"),
    ("depth", "Depth (Depth Anything V2 Small)"),
    ("openpose", "Pose (DWPose to OpenPose)"),
)
_IMAGE_TYPES = (("Images", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*"))

AttachPlan = Callable[[str], tuple[bool, str]]


class ReferenceMapDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        service: Any,
        modality: str,
        attach_plan: AttachPlan,
        on_attached: Callable[[SavedMap, Any], None],
        choose_file: Callable[[], str] | None = None,
        spawn: Callable[[Callable[[], None], str], Any] | None = None,
        redact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.title("Create map from image")
        self.transient(parent.winfo_toplevel())
        self.geometry("560x640")
        self.minsize(420, 480)
        self._inbox: queue.Queue[Callable[[], None]] = queue.Queue()
        self._attach_plan = attach_plan
        self._on_attached = on_attached
        self._choose_file = choose_file or self._ask_file
        self._redact = redact
        self._photo: tk.PhotoImage | None = None
        self._poll: str | None = None
        self._destroyed = False
        kwargs: dict[str, Any] = {}
        if spawn is not None:
            kwargs["spawn"] = spawn
        self.flow = ReferenceMapFlow(
            service,
            post=self._inbox.put,
            on_change=self._render,
            save_gate=lambda kind: bool(self._attach_plan(kind)[0]),
            **kwargs,
        )
        self.columnconfigure(0, weight=1)
        self._build()
        self.flow.set_modality(modality if modality in dict(MAP_TYPES) else "canny")
        self.type_var.set(self.flow.view.modality)
        self._render(self.flow.view)
        self._poll = self.after(_POLL_MS, self._pump)
        self.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------ construction

    def _build(self) -> None:
        body = ttk.Frame(self, padding=8)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        intro = ttk.Label(
            body,
            text=(
                "Make a pre-rendered ControlNet map from a reference image. Nothing is saved or queued until "
                "you press Save & Use, and creating a map never starts a generation."
            ),
            wraplength=500,
            justify="left",
        )
        intro.grid(row=0, column=0, sticky="ew")
        source = ttk.Frame(body)
        source.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        source.columnconfigure(1, weight=1)
        self.choose_button = ttk.Button(source, text="Choose image…", command=self._pick)
        self.choose_button.grid(row=0, column=0)
        self.source_var = tk.StringVar(value="")
        ttk.Label(source, textvariable=self.source_var, wraplength=360, justify="left").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        kinds = ttk.LabelFrame(body, text="Map type", padding=4)
        kinds.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.type_var = tk.StringVar(value="canny")
        self.type_buttons: dict[str, ttk.Radiobutton] = {}
        for column, (value, label) in enumerate(MAP_TYPES):
            button = ttk.Radiobutton(
                kinds, text=label, value=value, variable=self.type_var, command=self._on_type
            )
            button.grid(row=0, column=column, sticky="w", padx=(0, 10))
            self.type_buttons[value] = button
        self.availability_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.availability_var, wraplength=500, justify="left").grid(
            row=3, column=0, sticky="ew", pady=(4, 0)
        )
        actions = ttk.Frame(body)
        actions.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.prepare_button = ttk.Button(actions, text="Create preview", command=self.flow.prepare)
        self.prepare_button.grid(row=0, column=0)
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.flow.cancel)
        self.cancel_button.grid(row=0, column=1, padx=(6, 0))
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=2, padx=(10, 0))
        self.preview_label = ttk.Label(
            body, text="No preview yet", anchor="center", justify="center"
        )
        self.preview_label.grid(row=5, column=0, sticky="nsew", pady=(8, 0))
        body.rowconfigure(5, weight=1)
        self.facts_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.facts_var, wraplength=500, justify="left").grid(
            row=6, column=0, sticky="ew"
        )
        self.warnings_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.warnings_var, wraplength=500, justify="left").grid(
            row=7, column=0, sticky="ew"
        )
        self.status_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.status_var, wraplength=500, justify="left").grid(
            row=8, column=0, sticky="ew", pady=(6, 0)
        )
        self.reasons_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.reasons_var, wraplength=500, justify="left").grid(
            row=9, column=0, sticky="ew"
        )
        self.plan_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.plan_var, wraplength=500, justify="left").grid(
            row=10, column=0, sticky="ew", pady=(6, 0)
        )
        footer = ttk.Frame(body)
        footer.grid(row=11, column=0, sticky="e", pady=(8, 0))
        self.save_button = ttk.Button(footer, text="Save & Use", command=self._save)
        self.save_button.grid(row=0, column=0)
        ttk.Button(footer, text="Close", command=self.close).grid(row=0, column=1, padx=(6, 0))

    # ------------------------------------------------------------------ operator actions

    def _ask_file(self) -> str:
        return str(
            filedialog.askopenfilename(
                parent=self, title="Choose a source image", filetypes=_IMAGE_TYPES
            )
        )

    def _pick(self) -> None:
        chosen = self._choose_file()
        if chosen:
            self.flow.set_source(chosen)

    def _on_type(self) -> None:
        self.flow.set_modality(self.type_var.get())

    def _save(self) -> None:
        self.flow.save(self._attached)

    def _attached(self, saved: SavedMap, prepared: Any) -> None:
        self._on_attached(saved, prepared)

    def close(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self.flow.close()
        if self._poll is not None:
            self.after_cancel(self._poll)
            self._poll = None
        self.destroy()

    # ------------------------------------------------------------------ Tk-thread plumbing and drawing

    def _pump(self) -> None:
        self._poll = None
        while True:
            try:
                work = self._inbox.get_nowait()
            except queue.Empty:
                break
            work()
        if not self._destroyed:
            self._poll = self.after(_POLL_MS, self._pump)

    def _render(self, view: FlowView) -> None:
        if self._destroyed:
            return
        busy = view.state in (FlowState.PREPARING, FlowState.SAVING)
        name = view.source_name
        self.source_var.set("" if not name else ("Source image selected" if self._redact else name))
        self.choose_button.configure(state="normal" if view.can_choose else "disabled")
        for button in self.type_buttons.values():
            button.configure(state="normal" if view.can_choose else "disabled")
        self.prepare_button.configure(
            state="normal" if view.can_prepare and not busy else "disabled"
        )
        self.cancel_button.configure(state="normal" if view.can_cancel else "disabled")
        self.save_button.configure(state="normal" if view.can_save else "disabled")
        if busy:
            self.progress.start(60)
        else:
            self.progress.stop()
        self.status_var.set(view.message)
        self.facts_var.set(view.facts)
        self.warnings_var.set("\n".join(f"• {item}" for item in view.warnings))
        self.reasons_var.set("Reason codes: " + ", ".join(view.reasons) if view.reasons else "")
        self._set_preview(view.preview_png)
        reasons = self.flow.availability(view.modality)
        self.availability_var.set(
            f"{modality_label(view.modality)} maps are unavailable here ({', '.join(reasons)}); manual "
            "pre-rendered selection stays available."
            if reasons
            else ""
        )
        _, plan = self._attach_plan(view.modality)
        self.plan_var.set(plan)

    def _set_preview(self, png: bytes | None) -> None:
        if png is None:
            self._photo = None
            self.preview_label.configure(image="", text="No preview yet")
            return
        try:
            self._photo = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        except tk.TclError:
            self._photo = None
            self.preview_label.configure(image="", text="Preview unavailable")
            return
        self.preview_label.configure(image=self._photo, text="")


__all__ = ["MAP_TYPES", "ReferenceMapDialog"]

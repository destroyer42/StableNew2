"""Tk workspace for Align Motion (PR-VID-MOTION-420).  Presentation only.

Every rule -- what an alignment is, the anchor fit, staleness, what the form carries, what runs on a worker --
lives in ``MotionAlignmentSession``.  Decoding frames, re-rendering them and the aligned encode run on workers
owned by the existing ``ThreadRegistry``; results return through ``TkUiDispatcher`` and are dropped after the
window closes.  The window is not modal, never queues a job, never starts a runtime and never edits the Video
Workflow form: only the session's explicit Apply and Prepare change what the form submits.
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
from src.gui.view_contracts.video_motion_alignment_contract import (
    SHOW_ALIGNED,
    SHOW_ORIGINAL,
    VIEW_OVERLAY,
    VIEW_SIDE_BY_SIDE,
    AlignView,
    Marker,
    MotionAlignmentSession,
)
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.video.motion_alignment import ANCHOR_KINDS, Rect
from src.video.motion_alignment_compatibility import ROOT_DISPLACEMENTS, SubjectObservations
from src.video.motion_library.models import CAMERA_MOVEMENTS, FRAMINGS, SUBJECT_KINDS, VIEWPOINTS

_INTRO = (
    "Move and scale the driving motion inside the source image's frame. One constant transform is applied to "
    "every selected frame; the subject is never re-centred per frame and no pose is estimated or corrected. "
    "Nothing here queues a job or uses the GPU. The original driving video is never changed."
)
_CANVAS_WIDTH, _CANVAS_HEIGHT = 340, 560
_PLAY_INTERVAL_MS = 450
_ENTRY_DEBOUNCE_MS = 300
_MARKER_COLORS = ("#ff5a5a", "#4aa3ff", "#ffd24a", "#5ad17a")
_NUDGE = 10


def photo_from_image(image: Image.Image) -> tk.PhotoImage:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return tk.PhotoImage(data=base64.b64encode(buffer.getvalue()).decode("ascii"))


def _open(png: bytes | None) -> Image.Image | None:
    if not png:
        return None
    try:
        with Image.open(io.BytesIO(png)) as handle:
            return handle.convert("RGB")
    except OSError:
        return None


class MotionAlignmentDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        session: MotionAlignmentSession,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.title("Align Motion")
        self.transient(master.winfo_toplevel())
        self.geometry("1280x920")
        self.session = session
        self._on_close = on_close
        self._closed = False
        self._photos: list[tk.PhotoImage] = []
        self._geometry: dict[str, tuple[float, float, float]] = {}  # canvas -> (scale, ox, oy)
        self._play_job: str | None = None
        self._entry_job: str | None = None
        self._playing = False
        self.status_var = tk.StringVar(self)
        self.scale_var = tk.StringVar(self, value="1")
        self.tx_var = tk.StringVar(self, value="0")
        self.ty_var = tk.StringVar(self, value="0")
        self.mirror_var = tk.BooleanVar(self, value=False)
        self.mode_var = tk.StringVar(self, value=VIEW_SIDE_BY_SIDE)
        self.show_var = tk.StringVar(self, value=SHOW_ALIGNED)
        self.opacity_var = tk.DoubleVar(self, value=0.5)
        self.frame_var = tk.IntVar(self, value=0)
        self.kind_var = tk.StringVar(self, value=ANCHOR_KINDS[0])
        self.frame_add_var = tk.StringVar(self)
        self.source_bounds_var = tk.StringVar(self)
        self.driver_bounds_var = tk.StringVar(self)
        self.frame_bounds_var = tk.StringVar(self)
        self.obs_vars: dict[str, dict[str, tk.StringVar]] = {"source": {}, "driver": {}}
        self._unsubscribe = session.subscribe(self._render)
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Escape>", lambda _event: self.destroy())
        session.open_workspace()
        self._render()

    # ------------------------------------------------------------------ construction

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
        ttk.Label(header, text="Align Motion", font=("TkDefaultFont", 12, "bold")).grid(
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

    def _canvas(
        self, parent: ttk.Frame, title: str, column: int
    ) -> tuple[ttk.LabelFrame, tk.Canvas]:
        frame = ttk.LabelFrame(parent, text=title, padding=4)
        frame.grid(row=0, column=column, sticky="n", padx=(0, 6))
        canvas = tk.Canvas(
            frame,
            width=_CANVAS_WIDTH,
            height=_CANVAS_HEIGHT,
            highlightthickness=0,
            background="#101418",
        )
        canvas.grid(row=0, column=0)
        return frame, canvas

    def _build_viewer(self, body: ttk.Frame) -> None:
        left = ttk.Frame(body)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        views = ttk.Frame(left)
        views.grid(row=0, column=0, sticky="w")
        self.source_frame, self.source_canvas = self._canvas(views, "Source image (prepared)", 0)
        self.driver_frame, self.driver_canvas = self._canvas(views, "Driving frame", 1)
        self.source_canvas.bind("<Button-1>", functools.partial(self._on_click, "source"))
        self.driver_canvas.bind("<Button-1>", functools.partial(self._on_click, "driver"))
        self.canvas_note = ttk.Label(left, justify="left")
        self.canvas_note.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        bind_wraplength(self.canvas_note)

        view = ttk.LabelFrame(left, text="View", padding=6)
        view.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        for column, (text, value) in enumerate(
            (("Side by side", VIEW_SIDE_BY_SIDE), ("Overlay", VIEW_OVERLAY))
        ):
            ttk.Radiobutton(
                view, text=text, value=value, variable=self.mode_var, command=self._on_view
            ).grid(row=0, column=column, sticky="w")
        for column, (text, value) in enumerate(
            (("Aligned motion", SHOW_ALIGNED), ("Original motion", SHOW_ORIGINAL)), start=2
        ):
            ttk.Radiobutton(
                view, text=text, value=value, variable=self.show_var, command=self._on_view
            ).grid(row=0, column=column, sticky="w", padx=(10, 0))
        ttk.Label(view, text="Overlay opacity").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.opacity_scale = ttk.Scale(
            view,
            from_=0.0,
            to=1.0,
            orient="horizontal",
            variable=self.opacity_var,
            command=self._on_opacity,
        )
        self.opacity_scale.grid(row=1, column=1, columnspan=4, sticky="ew", pady=(4, 0))
        view.columnconfigure(4, weight=1)

        frames = ttk.LabelFrame(left, text="Frames of the selected action window", padding=6)
        frames.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        frames.columnconfigure(3, weight=1)
        self.prev_button = ttk.Button(
            frames, text="◀", width=3, command=lambda: self.session.step_frame(-1)
        )
        self.prev_button.grid(row=0, column=0)
        self.play_button = ttk.Button(frames, text="Play", width=6, command=self._on_play)
        self.play_button.grid(row=0, column=1, padx=4)
        self.next_button = ttk.Button(
            frames, text="▶", width=3, command=lambda: self.session.step_frame(1)
        )
        self.next_button.grid(row=0, column=2)
        self.frame_label = ttk.Label(frames, justify="left")
        self.frame_label.grid(row=0, column=3, sticky="w", padx=8)
        ttk.Label(frames, text="Also inspect frame").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        ttk.Entry(frames, textvariable=self.frame_add_var, width=6).grid(
            row=1, column=2, pady=(4, 0)
        )
        ttk.Button(frames, text="Add", command=self._on_add_frame).grid(
            row=1, column=3, sticky="w", padx=8, pady=(4, 0)
        )
        self.frame_buttons = ttk.Frame(frames)
        self.frame_buttons.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 0))

        self.geometry_text = self._text_box(left, 4, "Geometry", 4)
        self.explain_text = self._text_box(left, 5, "What preparation will do", 6)
        self.identity_text = self._text_box(left, 6, "Identity and provenance", 4)

    @staticmethod
    def _text_box(parent: tk.Misc, row: int, title: str, height: int) -> tk.Text:
        box = ttk.LabelFrame(parent, text=title, padding=6)
        box.grid(sticky="ew", pady=(6, 0), column=0, row=row)
        box.columnconfigure(0, weight=1)
        text = tk.Text(box, height=height, wrap="word", state="disabled")
        style_text_widget(text)
        text.grid(row=0, column=0, sticky="ew")
        return text

    def _entry(self, parent: tk.Misc, row: int, label: str, var: tk.StringVar) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(parent, textvariable=var, width=10)
        entry.grid(row=row, column=1, sticky="w", pady=1)
        entry.bind("<Return>", lambda _e: self._commit_params())
        entry.bind("<FocusOut>", lambda _e: self._commit_params())
        return entry

    def _build_controls(self, body: ttk.Frame) -> None:
        right = ttk.Frame(body)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        manual = ttk.LabelFrame(right, text="Position and size (target-frame pixels)", padding=6)
        manual.grid(row=0, column=0, sticky="ew")
        self.scale_entry = self._entry(manual, 0, "Scale (uniform)", self.scale_var)
        self.tx_entry = self._entry(manual, 1, "Shift right (+) / left (-)", self.tx_var)
        self.ty_entry = self._entry(manual, 2, "Shift down (+) / up (-)", self.ty_var)
        nudge = ttk.Frame(manual)
        nudge.grid(row=0, column=2, rowspan=3, padx=(10, 0))
        for text, dx, dy, row, column in (
            ("▲", 0, -_NUDGE, 0, 1),
            ("◀", -_NUDGE, 0, 1, 0),
            ("▶", _NUDGE, 0, 1, 2),
            ("▼", 0, _NUDGE, 2, 1),
        ):
            ttk.Button(
                nudge, text=text, width=3, command=functools.partial(self._nudge, dx, dy)
            ).grid(row=row, column=column)
        self.mirror_check = ttk.Checkbutton(
            manual,
            text="Mirror left-to-right",
            variable=self.mirror_var,
            command=self._commit_params,
        )
        self.mirror_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.mirror_note = ttk.Label(manual, justify="left")
        self.mirror_note.grid(row=4, column=0, columnspan=3, sticky="ew")
        bind_wraplength(self.mirror_note)
        self.param_error = ttk.Label(manual, justify="left", foreground="#d04040")
        self.param_error.grid(row=5, column=0, columnspan=3, sticky="ew")
        bind_wraplength(self.param_error)
        self.reset_button = ttk.Button(
            manual, text="Reset to unaligned", command=self.session.reset_draft
        )
        self.reset_button.grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))

        anchors = ttk.LabelFrame(right, text="Corresponding points (optional)", padding=6)
        anchors.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        anchors.columnconfigure(1, weight=1)
        ttk.Combobox(
            anchors, textvariable=self.kind_var, values=ANCHOR_KINDS, state="readonly", width=16
        ).grid(row=0, column=0, sticky="w")
        self.mark_button = ttk.Button(anchors, text="Mark pair", command=self._on_mark)
        self.mark_button.grid(row=0, column=1, sticky="w", padx=4)
        self.pending_label = ttk.Label(anchors, justify="left")
        self.pending_label.grid(row=1, column=0, columnspan=3, sticky="ew")
        bind_wraplength(self.pending_label)
        self.anchor_list = tk.Listbox(anchors, height=4, exportselection=False)
        self.anchor_list.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 0))
        buttons = ttk.Frame(anchors)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.remove_anchor_button = ttk.Button(
            buttons, text="Remove", command=self._on_remove_anchor
        )
        self.remove_anchor_button.grid(row=0, column=0)
        ttk.Button(buttons, text="Clear", command=self.session.clear_anchors).grid(
            row=0, column=1, padx=4
        )
        self.suggest_button = ttk.Button(
            buttons, text="Suggest alignment", command=self.session.suggest
        )
        self.suggest_button.grid(row=0, column=2)
        self.accept_button = ttk.Button(
            buttons, text="Accept", command=self.session.accept_suggestion
        )
        self.accept_button.grid(row=0, column=3, padx=4)
        self.discard_suggestion_button = ttk.Button(
            buttons, text="Discard", command=self.session.discard_suggestion
        )
        self.discard_suggestion_button.grid(row=0, column=4)
        self.proposal_label = ttk.Label(anchors, justify="left")
        self.proposal_label.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        bind_wraplength(self.proposal_label)

        envelope = ttk.LabelFrame(
            right, text="Subject bounds (optional, entered by you)", padding=6
        )
        envelope.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        envelope.columnconfigure(1, weight=1)
        ttk.Label(envelope, text="Source, x0,y0,x1,y1 in target px").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(envelope, textvariable=self.source_bounds_var, width=22).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(envelope, text="Driver, x0,y0,x1,y1 in driver px").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Entry(envelope, textvariable=self.driver_bounds_var, width=22).grid(
            row=1, column=1, sticky="w"
        )
        ttk.Label(envelope, text="Driver bounds at the shown frame").grid(
            row=2, column=0, sticky="w"
        )
        ttk.Entry(envelope, textvariable=self.frame_bounds_var, width=22).grid(
            row=2, column=1, sticky="w"
        )
        ttk.Button(envelope, text="Use bounds", command=self._on_bounds).grid(
            row=3, column=0, sticky="w", pady=(4, 0)
        )
        self.envelope_label = ttk.Label(envelope, justify="left")
        self.envelope_label.grid(row=4, column=0, columnspan=2, sticky="ew")
        bind_wraplength(self.envelope_label)

        obs = ttk.LabelFrame(
            right, text="What you know about the subjects (reported, not verified)", padding=6
        )
        obs.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self._observation_rows(obs)

        compat = ttk.LabelFrame(
            right, text="Compatibility (advisory only; never blocks)", padding=6
        )
        compat.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        compat.columnconfigure(0, weight=1)
        self.compat_text = tk.Text(compat, height=14, wrap="word", state="disabled")
        style_text_widget(self.compat_text)
        self.compat_text.grid(row=0, column=0, sticky="ew")

        actions = ttk.Frame(right)
        actions.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.apply_button = ttk.Button(
            actions, text="Apply and prepare", command=self._on_apply_prepare
        )
        self.apply_button.grid(row=0, column=0)
        self.prepare_button = ttk.Button(
            actions, text="Prepare again", command=self.session.prepare
        )
        self.prepare_button.grid(row=0, column=1, padx=4)
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.session.cancel)
        self.cancel_button.grid(row=0, column=2)
        self.discard_button = ttk.Button(
            actions, text="Discard alignment", command=self.session.discard
        )
        self.discard_button.grid(row=0, column=3, padx=4)
        ttk.Button(actions, text="Reload frames", command=self.session.reload).grid(
            row=0, column=4, padx=(0, 4)
        )
        ttk.Button(actions, text="Close", command=self.destroy).grid(row=0, column=5)

    def _observation_rows(self, parent: tk.Misc) -> None:
        choices = {
            "kind": SUBJECT_KINDS,
            "framing": FRAMINGS,
            "viewpoint": VIEWPOINTS,
            "camera_movement": CAMERA_MOVEMENTS,
        }
        for column, which in enumerate(("source", "driver"), start=1):
            ttk.Label(parent, text="Source image" if which == "source" else "Driving motion").grid(
                row=0, column=column, sticky="w", padx=4
            )
        row = 1
        fields = [
            (name, choices[name]) for name in ("kind", "framing", "viewpoint", "camera_movement")
        ]
        for name, values in [*fields, ("root_displacement", ROOT_DISPLACEMENTS)]:
            ttk.Label(parent, text=name.replace("_", " ").capitalize()).grid(
                row=row, column=0, sticky="w"
            )
            for column, which in enumerate(("source", "driver"), start=1):
                if (
                    name in ("camera_movement", "root_displacement")
                    and which == "source"
                    and name == "root_displacement"
                ):
                    continue
                var = tk.StringVar(self, value="unknown")
                self.obs_vars[which][name] = var
                box = ttk.Combobox(
                    parent, textvariable=var, values=list(values), state="readonly", width=12
                )
                box.grid(row=row, column=column, padx=4, pady=1)
                box.bind("<<ComboboxSelected>>", lambda _e: self._on_observations())
            row += 1
        ttk.Label(parent, text="Start pose").grid(row=row, column=0, sticky="w")
        for column, which in enumerate(("source", "driver"), start=1):
            var = tk.StringVar(self)
            self.obs_vars[which]["start_pose"] = var
            entry = ttk.Entry(parent, textvariable=var, width=14)
            entry.grid(row=row, column=column, padx=4, pady=1)
            entry.bind("<FocusOut>", lambda _e: self._on_observations())
            entry.bind("<Return>", lambda _e: self._on_observations())
        row += 1
        ttk.Label(parent, text="Subjects").grid(row=row, column=0, sticky="w")
        for column, which in enumerate(("source", "driver"), start=1):
            var = tk.StringVar(self)
            self.obs_vars[which]["count"] = var
            entry = ttk.Entry(parent, textvariable=var, width=14)
            entry.grid(row=row, column=column, padx=4, pady=1)
            entry.bind("<FocusOut>", lambda _e: self._on_observations())
            entry.bind("<Return>", lambda _e: self._on_observations())

    # ------------------------------------------------------------------ operator actions

    def _commit_params(self, *_args: Any) -> None:
        if self._closed:
            return
        self.session.set_params(
            scale=self.scale_var.get(),
            translate_x=self.tx_var.get(),
            translate_y=self.ty_var.get(),
            mirror=bool(self.mirror_var.get()),
        )

    def _nudge(self, dx: float, dy: float) -> None:
        try:
            self.tx_var.set(f"{float(self.tx_var.get() or 0) + dx:g}")
            self.ty_var.set(f"{float(self.ty_var.get() or 0) + dy:g}")
        except ValueError:
            pass
        self._commit_params()

    def _on_view(self) -> None:
        self.session.view_mode = self.mode_var.get()
        self.session.show = self.show_var.get()
        self._render()

    def _on_opacity(self, _value: str) -> None:
        self.session.opacity = float(self.opacity_var.get())
        self._render_images(self.session.view())

    def _on_play(self) -> None:
        self._playing = not self._playing
        self.play_button.configure(text="Pause" if self._playing else "Play")
        self._tick()

    def _tick(self) -> None:
        if self._closed or not self._playing:
            return
        self.session.step_frame(1)
        self._play_job = self.after(_PLAY_INTERVAL_MS, self._tick)

    def _on_add_frame(self) -> None:
        try:
            self.session.add_inspection_frame(int(self.frame_add_var.get()))
        except ValueError:
            pass

    def _on_mark(self) -> None:
        self.show_var.set(
            SHOW_ORIGINAL
        )  # corresponding points are marked on the unaligned driving frame
        self.mode_var.set(VIEW_SIDE_BY_SIDE)
        self.session.view_mode, self.session.show = VIEW_SIDE_BY_SIDE, SHOW_ORIGINAL
        self.session.begin_anchor(self.kind_var.get())

    def _on_remove_anchor(self) -> None:
        selection = self.anchor_list.curselection()  # type: ignore[no-untyped-call]
        if selection:
            self.session.remove_anchor(int(selection[0]))

    def _on_click(self, which: str, event: Any) -> None:
        key = "source_canvas" if which == "source" else "driver_canvas"
        scale, ox, oy = self._geometry.get(key, (0.0, 0.0, 0.0))
        if scale <= 0:
            return
        x, y = (event.x - ox) / scale, (event.y - oy) / scale
        if which == "source":
            self.session.place_source_point(x, y)
        else:
            self.session.place_driver_point(x, y)

    @staticmethod
    def _parse_rect(text: str) -> Rect | None:
        parts = [p for p in text.replace(";", ",").split(",") if p.strip()]
        if not parts:
            return None
        values = [float(p) for p in parts]
        if len(values) != 4:
            raise ValueError("Enter four numbers: x0,y0,x1,y1.")
        return Rect(*values)

    def _on_bounds(self) -> None:
        try:
            source = self._parse_rect(self.source_bounds_var.get())
            driver = self._parse_rect(self.driver_bounds_var.get())
            frame = self._parse_rect(self.frame_bounds_var.get())
        except ValueError as exc:
            self.status_var.set(f"Subject bounds: {exc}")
            return
        session = self.session
        session.set_observations("source", _with_bounds(session.source_obs, source))
        session.set_observations("driver", _with_bounds(session.driver_obs, driver))
        if frame is not None and session.selected_frame is not None:
            session.set_envelope_bounds(session.selected_frame, frame)

    def _on_observations(self) -> None:
        for which in ("source", "driver"):
            current = self.session.source_obs if which == "source" else self.session.driver_obs
            values = {name: var.get().strip() for name, var in self.obs_vars[which].items()}
            count_text = values.pop("count", "")
            try:
                count = int(count_text) if count_text else None
            except ValueError:
                count = None
            updated = SubjectObservations(
                kind=values.get("kind", "unknown") or "unknown",
                count=count,
                framing=values.get("framing", "unknown") or "unknown",
                viewpoint=values.get("viewpoint", "unknown") or "unknown",
                start_pose=values.get("start_pose", ""),
                camera_movement=values.get("camera_movement", "unknown") or "unknown",
                motion_direction=current.motion_direction,
                root_displacement=values.get("root_displacement", current.root_displacement)
                or "unknown",
                visible_regions=current.visible_regions,
                bounds=current.bounds,
            )
            if updated != current:
                self.session.set_observations(which, updated)

    def _on_apply_prepare(self) -> None:
        if self.session.apply():
            self.session.prepare()

    # ------------------------------------------------------------------ rendering

    def _render(self) -> None:
        if self._closed:
            return
        view = self.session.view()
        self.status_var.set(f"Alignment: {view.status_label}. {view.status_text}")
        self._sync_entries(view)
        self._apply_state(view)
        self._render_images(view)
        self._set_text(
            self.geometry_text,
            "\n".join(view.geometry_lines) or (view.load_message or "No preview yet."),
        )
        self._set_text(self.explain_text, "\n".join(view.explanation_lines))
        self._set_text(
            self.identity_text, "\n".join(view.identity_lines) or "Nothing prepared yet."
        )
        self._set_text(self.compat_text, _compat_text(view))
        self.anchor_list.delete(0, "end")
        for line in view.anchor_lines:
            self.anchor_list.insert("end", line)
        self.pending_label.configure(text=view.pending_prompt)
        self.proposal_label.configure(text="\n".join(view.proposal_lines))
        self.envelope_label.configure(text="\n".join(view.envelope_lines))
        self.mirror_note.configure(text=view.mirror_disclosure)
        self.param_error.configure(text=view.param_error)
        self.canvas_note.configure(
            text=view.load_message
            if view.loading or view.load_message
            else "Shown at the target frame's size: the source image's own frame."
        )
        self._sync_frame_buttons(view)

    def _sync_entries(self, view: AlignView) -> None:
        focused = self.focus_get() if not self._closed else None
        for entry, var, text in (
            (self.scale_entry, self.scale_var, view.scale_text),
            (self.tx_entry, self.tx_var, view.translate_x_text),
            (self.ty_entry, self.ty_var, view.translate_y_text),
        ):
            if focused is not entry and var.get() != text:
                var.set(text)
        if bool(self.mirror_var.get()) != view.mirror:
            self.mirror_var.set(view.mirror)
        self.mode_var.set(view.view_mode)
        self.show_var.set(view.show)

    def _apply_state(self, view: AlignView) -> None:
        def state(widget: Any, enabled: bool) -> None:
            widget.configure(state="normal" if enabled else "disabled")

        state(self.apply_button, view.can_apply)
        state(self.prepare_button, view.can_prepare)
        state(self.cancel_button, view.can_cancel)
        state(self.discard_button, view.can_discard)
        state(self.suggest_button, view.can_suggest)
        state(self.accept_button, view.has_proposal)
        state(self.discard_suggestion_button, bool(view.proposal_lines))
        state(self.mark_button, view.target_size is not None)
        if view.view_mode == VIEW_OVERLAY:
            self.source_frame.grid_remove()
        else:
            self.source_frame.grid()

    def _sync_frame_buttons(self, view: AlignView) -> None:
        for child in self.frame_buttons.winfo_children():
            child.destroy()
        for column, index in enumerate(view.frame_indices):
            ttk.Button(
                self.frame_buttons,
                text=str(index) + ("*" if index == view.selected_frame else ""),
                width=4,
                command=functools.partial(self.session.select_frame, index),
            ).grid(row=0, column=column, padx=1)
        self.frame_label.configure(
            text=f"Output frame {view.selected_frame}"
            if view.selected_frame is not None
            else "No frames decoded yet"
        )

    def _render_images(self, view: AlignView) -> None:
        self._photos.clear()
        source = _open(view.source_png)
        driver_png = view.aligned_png if view.show == SHOW_ALIGNED else view.baseline_png
        driver = _open(driver_png)
        placement = view.placement if view.show == SHOW_ALIGNED else view.baseline_placement
        if view.view_mode == VIEW_OVERLAY and source is not None and driver is not None:
            blended = Image.blend(source, driver.resize(source.size), float(view.opacity))
            self._draw(
                self.driver_canvas,
                "driver_canvas",
                blended,
                (*view.source_markers, *view.driver_markers),
                placement,
                view,
            )
            self.source_canvas.delete("all")
            return
        self._draw(self.source_canvas, "source_canvas", source, view.source_markers, None, view)
        self._draw(
            self.driver_canvas, "driver_canvas", driver, view.driver_markers, placement, view
        )

    def _draw(
        self,
        canvas: tk.Canvas,
        key: str,
        image: Image.Image | None,
        markers: tuple[Marker, ...],
        placement: tuple[float, float, float, float] | None,
        view: AlignView,
    ) -> None:
        canvas.delete("all")
        if image is None or view.target_size is None:
            self._geometry[key] = (0.0, 0.0, 0.0)
            return
        width, height = view.target_size
        scale = min(_CANVAS_WIDTH / width, _CANVAS_HEIGHT / height)
        shown = image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS
        )
        ox, oy = (_CANVAS_WIDTH - shown.width) / 2, (_CANVAS_HEIGHT - shown.height) / 2
        photo = photo_from_image(shown)
        self._photos.append(photo)
        canvas.create_image(ox, oy, image=photo, anchor="nw")
        canvas.create_rectangle(
            ox, oy, ox + shown.width, oy + shown.height, outline="#ffffff"
        )  # the target frame
        if (
            placement is not None
        ):  # where the driving frame sits (dashed): crop and fill are visible
            left, top, right, bottom = placement
            canvas.create_rectangle(
                ox + left * scale,
                oy + top * scale,
                ox + right * scale,
                oy + bottom * scale,
                outline="#ffd24a",
                dash=(4, 3),
            )
        for index, marker in enumerate(markers):
            color = _MARKER_COLORS[index % len(_MARKER_COLORS)]
            x, y = ox + marker.x * scale, oy + marker.y * scale
            canvas.create_oval(x - 5, y - 5, x + 5, y + 5, outline=color, width=2)
            canvas.create_text(x + 9, y - 9, text=marker.label, fill=color)
        self._geometry[key] = (scale, ox, oy)

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    # ------------------------------------------------------------------ teardown

    def _on_destroy(self, event: Any = None) -> None:
        if event is not None and event.widget is not self:
            return
        self._closed = True
        self._playing = False
        for job in (self._play_job, self._entry_job):
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        self._unsubscribe()
        self.session.close_workspace()
        if self._on_close is not None:
            self._on_close()


def _with_bounds(observations: SubjectObservations, bounds: Rect | None) -> SubjectObservations:
    from dataclasses import replace

    return replace(observations, bounds=bounds)


def _compat_text(view: AlignView) -> str:
    assessment = view.compatibility
    if assessment is None:
        return "Open a preview to compare the source and the driving motion."
    sections = (
        ("Measured", assessment.measured),
        ("Reported by you or the Motion Library", assessment.annotations),
        ("Derived geometry", assessment.derived),
        ("Evidence", assessment.historical),
        ("Not known (these checks were not made)", assessment.unknown),
    )
    lines: list[str] = []
    for title, items in sections:
        if items:
            lines.append(title + ":")
            lines.extend(f"  - {item}" for item in items)
    if assessment.advisories:
        lines.append("Advisories:")
        for advisory in assessment.advisories:
            tail = (
                f" [{advisory.threshold}; observed {advisory.observed}]"
                if advisory.threshold
                else ""
            )
            lines.append(f"  - ({advisory.severity}, {advisory.basis}) {advisory.message}{tail}")
    else:
        lines.append("No advisories. This is not a prediction that the motion will transfer.")
    return "\n".join(lines)


__all__ = ["MotionAlignmentDialog"]

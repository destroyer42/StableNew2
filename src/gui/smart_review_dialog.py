"""Review's opt-in Smart Review panel: point/box object selection and caption suggestions (PR-IMG-REVIEW-320).

Everything shown here is a SUGGESTION. Nothing runs on selection or on open: each model runs once, in a tracked worker and a
contained child process, only when the operator presses its button, and only after the operator ticked that capability on.
Accepting a mask copies it into the existing mask editor, which keeps sole ownership of Preview and queueing; this dialog never
builds a backend payload, calls a runner or submits a job. Blocking work uses the same ``BackgroundWorkRunner`` as the editor.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import Any

from PIL import Image, ImageTk

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.theme_v2 import apply_toplevel_theme
from src.gui.ui_dispatcher import TkUiDispatcher
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui_v2.mask_editor_state import MaskViewport
from src.review.assist.captions import (
    CaptionApplication,
    DraftBinding,
    present_caption,
    present_label,
)
from src.review.assist.contracts import (
    CAPABILITIES,
    CAPABILITY_CAPTION,
    CAPABILITY_SEGMENT,
    CODE_INFERENCE,
    MAX_BOXES,
    MAX_POINTS,
    TITLES,
    AssistError,
    Availability,
    BoxPrompt,
    CaptionProposal,
    PointPrompt,
    SegmentProposal,
)
from src.review.assist.geometry import box_from_drag, compose_overlay, point_at
from src.review.assist.identity import LoadedSource, load_source
from src.review.assist.masks import mask_image
from src.review.assist.session import AssistEnablement, AssistSession, Ticket

_FEATURE = {CAPABILITY_SEGMENT: "Object selection", CAPABILITY_CAPTION: "Image analysis"}
_DRAG_PIXELS = 4


class TextDraft:
    """``DraftBinding`` over a Tk ``Text`` (the Review prompt box); the caller's hook refreshes anything derived from it."""

    def __init__(self, widget: tk.Text, changed: Callable[[], None] | None = None) -> None:
        self._widget = widget
        self._changed = changed

    def get(self) -> str:
        return str(self._widget.get("1.0", "end-1c"))

    def set(self, text: str) -> None:
        self._widget.delete("1.0", "end")
        self._widget.insert("1.0", text)
        if self._changed is not None:
            self._changed()


def build_session(
    source_path: Path,
    enablement: AssistEnablement,
    registry_factory: Callable[[], Any] | None = None,
) -> AssistSession:
    """The real session: contained-child adapters over the asset registry. Imports and starts nothing heavy."""

    from src.assets.registry import AssetRegistry
    from src.review.assist.providers import (
        ChildCaptionAdapter,
        ChildSegmentAdapter,
        ModelAvailability,
    )

    factory = registry_factory or AssetRegistry
    return AssistSession(
        source_path,
        segmenter=ChildSegmentAdapter(factory),
        captioner=ChildCaptionAdapter(factory),
        probe=ModelAvailability(factory),
        enablement=enablement,
    )


class SmartReviewDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        source_path: Path,
        controller: Any,
        enablement: AssistEnablement,
        session: AssistSession | None = None,
        runner: BackgroundWorkRunner | None = None,
        prompt_binding: DraftBinding | None = None,
        open_editor: Callable[[Path, bytes, str], None] | None = None,
        visibility_mode: Callable[[], str] | None = None,
        draft_current: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(master)
        apply_toplevel_theme(self)
        self.title("Smart Review — suggestions only")
        self.geometry("1120x760")
        self.minsize(760, 520)
        self._controller = controller
        self._master = master
        self.source_path = Path(source_path)
        self._enablement = enablement
        self.session = session or build_session(self.source_path, enablement)
        self._open_editor = open_editor or self._default_open_editor
        self._prompt_binding = prompt_binding
        self._visibility_mode = visibility_mode
        self._draft_current = draft_current
        self._application = (
            CaptionApplication(prompt_binding, self._refresh_controls) if prompt_binding else None
        )
        self.viewport = MaskViewport()
        self._image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._mask_view: Image.Image | None = None
        self.points: list[PointPrompt] = []
        self.boxes: list[BoxPrompt] = []
        self.available: dict[str, Availability | None] = dict.fromkeys(CAPABILITIES)
        self._probe_generation = dict.fromkeys(CAPABILITIES, 0)
        self._probing: set[str] = set()
        self._busy = False
        self._closed = False
        self._press: tuple[float, float] | None = None
        self._pan_point: tuple[int, int] | None = None
        self.mode = tk.StringVar(value="foreground")
        self.status = tk.StringVar(value="Loading image…")
        self.enable_vars = {
            cap: tk.BooleanVar(value=enablement.is_enabled(cap)) for cap in CAPABILITIES
        }
        self._build()
        dispatcher = TkUiDispatcher(self.winfo_toplevel())
        self._runner = runner or BackgroundWorkRunner(
            spawn=lambda name, target: _spawn(name, target),
            dispatch=dispatcher.invoke,
        )
        for cap, var in self.enable_vars.items():
            var.trace_add("write", lambda *_, c=cap: self._on_enable(c))
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind(
            "<Destroy>", lambda e: setattr(self, "_closed", True) if e.widget is self else None
        )
        self._runner.start(
            "SmartReviewLoad",
            lambda: WorkOutcome(_content_free(lambda: load_source(self.source_path))),
            self._loaded,
        )
        for cap in CAPABILITIES:
            if enablement.is_enabled(cap):
                self._probe(cap)

    # -- layout --------------------------------------------------------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        bar = ttk.Frame(self, padding=8)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure((0, 1), weight=1, uniform="cap")
        self.capability_labels: dict[str, ttk.Label] = {}
        for column, cap in enumerate(CAPABILITIES):
            cell = ttk.Frame(bar)
            cell.grid(row=0, column=column, sticky="ew", padx=4)
            ttk.Checkbutton(
                cell,
                text=f"Enable {_FEATURE[cap].lower()} ({TITLES[cap]}, local, CPU)",
                variable=self.enable_vars[cap],
            ).pack(anchor="w")
            label = ttk.Label(cell, text="Off", wraplength=420)
            label.pack(anchor="w")
            self.capability_labels[cap] = label
        tools = ttk.Frame(self, padding=(8, 0))
        tools.grid(row=1, column=0, sticky="nsew")
        tools.columnconfigure(0, weight=1)
        tools.rowconfigure(1, weight=1)
        modes = ttk.Frame(tools)
        modes.grid(row=0, column=0, sticky="ew")
        for text, value in (
            ("Foreground point", "foreground"),
            ("Background point", "background"),
            ("Box", "box"),
        ):
            ttk.Radiobutton(
                modes, text=text, variable=self.mode, value=value, style="Page.TRadiobutton"
            ).pack(side="left", padx=3)
        for text, action in (
            ("−", lambda: self._zoom(0.8)),
            ("+", lambda: self._zoom(1.25)),
            ("Fit", self._fit),
        ):
            ttk.Button(modes, text=text, width=4, command=action).pack(side="left", padx=2)
        ttk.Button(modes, text="Clear points", command=self._clear_prompts).pack(
            side="left", padx=6
        )
        self.canvas = tk.Canvas(
            tools, background="#232323", highlightthickness=0, width=420, height=320
        )
        self.canvas.grid(row=1, column=0, sticky="nsew", pady=4)
        self.canvas.bind("<Configure>", lambda _: self._render())
        self.canvas.bind("<ButtonPress-1>", self._press_start)
        self.canvas.bind("<ButtonRelease-1>", self._press_end)
        for button in (2, 3):
            self.canvas.bind(f"<ButtonPress-{button}>", self._pan_start)
            self.canvas.bind(f"<B{button}-Motion>", self._pan)
        self.canvas.bind(
            "<MouseWheel>", lambda e: self._zoom(1.25 if e.delta > 0 else 0.8, e.x, e.y)
        )
        side = ScrollableFrame(self)
        side.grid(row=1, column=1, sticky="nsew", padx=(0, 8), pady=4)
        panel = side.inner
        panel.columnconfigure(0, weight=1)
        ttk.Label(
            panel,
            text="Object selection\nClick one foreground point on the object (optionally a background point or a box), "
            "then Propose mask. Nothing is edited until you accept.",
            wraplength=300,
        ).pack(anchor="w", pady=(0, 4))
        row = ttk.Frame(panel)
        row.pack(fill="x")
        self.propose_button = ttk.Button(
            row, text="Propose mask", command=self._propose, state="disabled"
        )
        self.propose_button.pack(side="left")
        self.accept_button = ttk.Button(
            row, text="Accept mask", command=self._accept, state="disabled"
        )
        self.accept_button.pack(side="left", padx=4)
        self.reject_button = ttk.Button(
            row, text="Reject", command=self._reject_mask, state="disabled"
        )
        self.reject_button.pack(side="left")
        self.cancel_button = ttk.Button(
            panel, text="Cancel analysis", command=self._cancel, state="disabled"
        )
        self.cancel_button.pack(anchor="w", pady=4)
        ttk.Separator(panel).pack(fill="x", pady=6)
        ttk.Label(panel, text="Image analysis (caption suggestion)", wraplength=300).pack(
            anchor="w"
        )
        self.analyze_button = ttk.Button(
            panel, text="Analyze image", command=self._analyze, state="disabled"
        )
        self.analyze_button.pack(anchor="w", pady=4)
        self.caption_source = ttk.Label(panel, text="", wraplength=300)
        self.caption_source.pack(anchor="w")
        self.caption_text = tk.Text(panel, width=36, height=8, wrap="word", state="disabled")
        self.caption_text.pack(fill="x", pady=4)
        self.objects_label = ttk.Label(panel, text="", wraplength=300)
        self.objects_label.pack(anchor="w")
        caption_row = ttk.Frame(panel)
        caption_row.pack(fill="x", pady=4)
        self.copy_button = ttk.Button(
            caption_row, text="Copy", command=self._copy, state="disabled"
        )
        self.copy_button.pack(side="left")
        self.apply_button = ttk.Button(
            caption_row, text="Add to prompt draft", command=self._apply, state="disabled"
        )
        self.apply_button.pack(side="left", padx=4)
        self.undo_button = ttk.Button(
            caption_row, text="Undo", command=self._undo, state="disabled"
        )
        self.undo_button.pack(side="left")
        self.dismiss_button = ttk.Button(
            panel, text="Dismiss suggestion", command=self._dismiss, state="disabled"
        )
        self.dismiss_button.pack(anchor="w")
        ttk.Button(self, text="Close", command=self._close).grid(
            row=2, column=1, sticky="e", padx=8, pady=4
        )
        ttk.Label(self, textvariable=self.status, wraplength=900).grid(
            row=2, column=0, sticky="w", padx=8, pady=4
        )

    # -- loading and capabilities --------------------------------------------------------------------------------
    def _loaded(self, outcome: WorkOutcome) -> None:
        if self._closed:
            return
        if outcome.error:
            self.status.set(f"Image unavailable: {outcome.error}")
            return
        loaded: LoadedSource = outcome.value
        self.session.bind(loaded, self.source_path)
        self._image = Image.fromarray(loaded.rgb)
        identity = loaded.identity
        note = (
            " This file carries an EXIF rotation; like the mask editor, Smart Review uses the stored pixel orientation."
            if identity.exif_orientation not in (0, 1)
            else ""
        )
        self.status.set(
            f"Image {identity.width} × {identity.height}. Turn a capability on, then use it. "
            f"Manual mask editing stays available.{note}"
        )
        self._fit()
        self.after_idle(self._fit)
        self._refresh_controls()

    def _on_enable(self, capability: str) -> None:
        enabled = bool(self.enable_vars[capability].get())
        self._enablement.set(capability, enabled)
        self.available[capability] = None
        self._probe_generation[capability] += 1  # replies to an earlier toggle are now stale
        if enabled:
            self.capability_labels[capability].config(text="Checking model files…")
            self._probe(capability)
        else:
            self.capability_labels[capability].config(text="Off")
            if self._busy:
                self.session.cancel()  # turning a helper off stops a run that was started under it
        self._refresh_controls()

    def _probe(self, capability: str) -> None:
        generation = self._probe_generation[capability]
        if capability in self._probing:
            return  # one file check at a time per capability; its reply is re-checked against the latest toggle
        self._probing.add(capability)

        def done(outcome: WorkOutcome) -> None:
            self._probing.discard(capability)
            if self._closed or not self._enablement.is_enabled(capability):
                return
            if generation != self._probe_generation[capability]:
                self._probe(capability)  # toggled meanwhile: check again for the current state
                return
            if outcome.error:
                self.available[capability] = None
                self.capability_labels[capability].config(text=f"Could not check: {outcome.error}")
            else:
                result: Availability = outcome.value
                self.available[capability] = result
                self.capability_labels[capability].config(text=result.message)
            self._refresh_controls()

        self._runner.start(
            f"SmartReviewProbe-{capability}",
            lambda: WorkOutcome(_content_free(lambda: self.session.availability(capability))),
            done,
        )

    def _ready(self, capability: str) -> bool:
        result = self.available.get(capability)
        return bool(result and result.available and self._enablement.is_enabled(capability))

    def _refresh_controls(self) -> None:
        if self._closed:
            return
        loaded = self.session.identity is not None
        idle = loaded and not self._busy
        can_prompt = any(point.positive for point in self.points) or bool(self.boxes)
        self._set(self.propose_button, idle and self._ready(CAPABILITY_SEGMENT) and can_prompt)
        self._set(self.analyze_button, idle and self._ready(CAPABILITY_CAPTION))
        self._set(self.accept_button, idle and self.session.segment is not None)
        self._set(self.reject_button, self.session.segment is not None and not self._busy)
        self._set(self.cancel_button, self._busy)
        caption = self.session.caption
        view = present_caption(caption.text, self._resolver()) if caption else None
        self._set(self.copy_button, bool(view and view.can_apply))
        self._set(
            self.apply_button,
            bool(view and view.can_apply and self._application and not self._application.applied),
        )
        self._set(self.undo_button, bool(self._application and self._application.applied))
        self._set(self.dismiss_button, caption is not None)

    @staticmethod
    def _set(button: ttk.Button, enabled: bool) -> None:
        button.state(["!disabled"] if enabled else ["disabled"])

    def _resolver(self) -> ContentVisibilityResolver:
        if self._visibility_mode is not None:
            return ContentVisibilityResolver(self._visibility_mode())
        mode = getattr(
            getattr(self._controller, "app_state", None), "content_visibility_mode", "nsfw"
        )
        return ContentVisibilityResolver(mode)

    # -- canvas --------------------------------------------------------------------------------------------------
    def _press_start(self, event: Any) -> None:
        self._press = (event.x, event.y)

    def _press_end(self, event: Any) -> None:
        start, self._press = self._press, None
        identity = self.session.identity
        if start is None or identity is None or self._busy:
            return
        try:
            if self.mode.get() == "box":
                if len(self.boxes) >= MAX_BOXES:
                    raise AssistError(
                        "invalid_prompt", "Only one box is used. Clear points to start again."
                    )
                if (
                    abs(event.x - start[0]) < _DRAG_PIXELS
                    and abs(event.y - start[1]) < _DRAG_PIXELS
                ):
                    raise AssistError("invalid_prompt", "Drag to draw a box.")
                self.boxes.append(
                    box_from_drag(self.viewport, start, (event.x, event.y), identity.size)
                )
            else:
                if len(self.points) >= MAX_POINTS:
                    raise AssistError("invalid_prompt", f"At most {MAX_POINTS} points are used.")
                self.points.append(
                    point_at(
                        self.viewport,
                        event.x,
                        event.y,
                        identity.size,
                        positive=self.mode.get() == "foreground",
                    )
                )
        except AssistError as exc:
            self.status.set(exc.message)
            return
        self._prompts_changed()

    def _prompts_changed(self) -> None:
        self.session.reject_mask()  # a mask proposed for other prompts is no longer what is on screen
        self._mask_view = None
        self.status.set("Prompts changed. Press Propose mask.")
        self._render()
        self._refresh_controls()

    def _clear_prompts(self) -> None:
        if self._busy:
            return
        self.points.clear()
        self.boxes.clear()
        self._prompts_changed()

    def _pan_start(self, event: Any) -> None:
        self._pan_point = event.x, event.y

    def _pan(self, event: Any) -> None:
        if self._pan_point is not None:
            self.viewport.x += event.x - self._pan_point[0]
            self.viewport.y += event.y - self._pan_point[1]
            self._pan_point = event.x, event.y
            self._render()

    def _zoom(self, factor: float, x: float | None = None, y: float | None = None) -> None:
        self.viewport.zoom(
            factor,
            self.canvas.winfo_width() / 2 if x is None else x,
            self.canvas.winfo_height() / 2 if y is None else y,
        )
        self._render()

    def _fit(self) -> None:
        if self._image is not None:
            self.viewport.fit(
                self._image.size,
                (max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())),
            )
            self._render()

    def _render(self) -> None:
        if self._image is None or self._closed:
            return
        size = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        view = compose_overlay(
            self._image, self._mask_view, self.viewport, size, points=self.points, boxes=self.boxes
        )
        self._photo = ImageTk.PhotoImage(view)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

    # -- object selection ----------------------------------------------------------------------------------------
    def _propose(self) -> None:
        points, boxes = list(self.points), list(self.boxes)
        try:
            ticket = self.session.begin_segment(points, boxes)
        except AssistError as exc:
            self.status.set(exc.message)
            return
        self._start_work(
            "SmartReviewSegment",
            "Finding the object (local model, CPU; this can take a while)…",
            lambda: _content_free(lambda: self.session.run_segment(ticket, points, boxes)),
            lambda proposal: self._segment_done(ticket, proposal),
        )

    def _segment_done(self, ticket: Ticket, proposal: SegmentProposal) -> None:
        if not self.session.adopt_segment(ticket, proposal):
            self.status.set("A newer request replaced that suggestion; it was dropped.")
            return
        assert self.session.identity is not None
        self._mask_view = mask_image(proposal.mask_png, proposal.identity)
        score = f", model confidence {proposal.score:.2f}" if proposal.score is not None else ""
        self.status.set(
            f"Suggested mask covers {proposal.coverage:.0%} of the image{score} ({proposal.model.label}). "
            "It is a suggestion: Accept to refine it in the mask editor, or Reject."
        )
        self._render()

    def _accept(self) -> None:
        try:
            sha256 = self.session.identity.file_sha256 if self.session.identity else ""
            data = self.session.accept_mask()
        except AssistError as exc:
            self.status.set(exc.message)
            self._mask_view = None
            self._render()
            self._refresh_controls()
            return
        self._open_editor(self.source_path, data, sha256)
        self._close()

    def _reject_mask(self) -> None:
        self.session.reject_mask()
        self._mask_view = None
        self.status.set("Suggestion rejected. Nothing was changed.")
        self._render()
        self._refresh_controls()

    def _default_open_editor(self, path: Path, mask: bytes, source_sha256: str) -> None:
        from src.gui.mask_editor_dialog import MaskEditorDialog

        MaskEditorDialog(
            self._master,
            source_path=path,
            controller=self._controller,
            suggested_mask=mask,
            suggested_source_sha256=source_sha256,
        )

    # -- caption -------------------------------------------------------------------------------------------------
    def _analyze(self) -> None:
        try:
            ticket = self.session.begin_caption()
        except AssistError as exc:
            self.status.set(exc.message)
            return
        self._start_work(
            "SmartReviewCaption",
            "Analyzing the image (local model, CPU; this can take a while)…",
            lambda: _content_free(lambda: self.session.run_caption(ticket)),
            lambda proposal: self._caption_done(ticket, proposal),
        )

    def _caption_done(self, ticket: Ticket, proposal: CaptionProposal) -> None:
        if not self.session.adopt_caption(ticket, proposal):
            self.status.set("A newer request replaced that suggestion; it was dropped.")
            return
        resolver = self._resolver()
        view = present_caption(proposal.text, resolver)
        self.caption_source.config(
            text=f"Suggestion from {proposal.model.label}. Not ground truth; check it."
        )
        self._write_caption(view.text + ("  [shortened]" if proposal.truncated else ""))
        objects = "; ".join(
            f"{present_label(item.label, resolver)} {item.box}" for item in proposal.objects
        )
        self.objects_label.config(text=f"Objects: {objects}" if objects else "")
        self.status.set("Caption suggestion ready. Your prompt and ratings are unchanged.")
        self._refresh_controls()

    def _write_caption(self, text: str) -> None:
        self.caption_text.configure(state="normal")
        self.caption_text.delete("1.0", "end")
        self.caption_text.insert("1.0", text)
        self.caption_text.configure(state="disabled")

    def _current_view(self) -> str | None:
        caption = self.session.caption
        if caption is None:
            return None
        view = present_caption(caption.text, self._resolver())
        return caption.text if view.can_apply else None

    def _copy(self) -> None:
        text = self._current_view()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status.set("Suggestion copied to the clipboard.")

    def _apply(self) -> None:
        text = self._current_view()
        if self._draft_current is not None and not self._draft_current():
            self.status.set(
                "Review is showing a different image now; reopen Smart Review for this one to use its prompt."
            )
            return
        if text and self._application and self._application.apply(text):
            self.status.set("Added to the prompt draft. Undo restores it; nothing is queued.")
        self._refresh_controls()

    def _undo(self) -> None:
        if self._application and self._application.undo():
            self.status.set("Prompt draft restored.")
        else:
            self.status.set("The prompt draft was edited since; it was left as you wrote it.")
        self._refresh_controls()

    def _dismiss(self) -> None:
        self.session.reject_caption()
        if self._application:
            self._application.forget()
        self._write_caption("")
        self.caption_source.config(text="")
        self.objects_label.config(text="")
        self._refresh_controls()

    # -- worker plumbing -----------------------------------------------------------------------------------------
    def _start_work(
        self, name: str, message: str, work: Callable[[], Any], on_value: Callable[[Any], None]
    ) -> None:
        self._busy = True
        self.status.set(message)
        self._refresh_controls()

        def done(outcome: WorkOutcome) -> None:
            if self._closed:
                return
            self._busy = False
            if outcome.error:
                self.status.set(outcome.error)
            else:
                on_value(outcome.value)
            self._refresh_controls()

        try:
            self._runner.start(name, lambda: WorkOutcome(work()), done)
        except (RuntimeError, OSError):
            self.session.release()  # the reserved analysis slot must not leak when no worker could start
            self._busy = False
            self.status.set("The analysis could not be started.")
            self._refresh_controls()

    def _cancel(self) -> None:
        self.session.cancel()
        self._mask_view = None
        self.status.set("Cancelling. Suggestions were discarded; nothing was changed or queued.")
        self._render()

    def _close(self) -> None:
        self._closed = True
        self.session.close()
        self.destroy()


def _content_free(call: Callable[[], Any]) -> Any:
    """Run ``call``; anything unexpected becomes a content-free message (never a path or a prompt)."""

    try:
        return call()
    except AssistError:
        raise
    except Exception as exc:
        raise AssistError(CODE_INFERENCE, "The analysis failed unexpectedly.") from exc


def _spawn(name: str, target: Callable[[], None]) -> Any:
    from src.utils.thread_registry import get_thread_registry

    return get_thread_registry().spawn(
        target=target, name=name, daemon=False, purpose="Review Smart Review"
    )

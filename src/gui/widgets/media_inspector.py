"""Shared local media controls, bounded inspection and safely recreated dock/detach renderers."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

from PIL import ImageTk

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.tooltip import Tooltip, attach_tooltip
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.ui_tokens import TOKENS
from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.view_contracts.media_image_decode import (
    InspectionImage,
    decode_inspection_image,
    render_viewport,
)
from src.gui.view_contracts.media_inspector_contract import MediaInspectorState
from src.gui.view_contracts.photo_optimize_layout_contract import flow_rows
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.widgets.video_preview_widget_v2 import VideoPreviewWidget

logger = logging.getLogger(__name__)


class MediaInspector(ttk.Frame):
    """One logical selection and serial latest-wins work key; never reparent a Tk widget.

    New selections reset to the host's established Show default. Refreshing the same
    path preserves local Show and zoom. A hidden/unmapped host suspends even its
    detached renderer. Public thumbnail aliases allow thin workspace integrations.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        width: int = 256,
        height: int = 256,
        max_width: int | None = None,
        max_height: int | None = None,
        default_shown: bool = True,
        placeholder_text: str = "Select media",
        on_source_changed: Any = None,
        decode: Any = None,
        edge: int | None = None,
        responsive: bool = True,
        min_edge: int = 96,
        fit_to_widget: bool = False,
        scale: int = 1,
        show_control: bool = True,
        allow_original: bool = True,
        shown_var: tk.BooleanVar | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.pop("bg", None)
        kwargs.setdefault("style", "Panel.TFrame")
        super().__init__(master, **kwargs)
        self.model = MediaInspectorState(
            default_shown=default_shown, shown=default_shown, active=False
        )
        self._closed = False
        self._placeholder_text = placeholder_text
        self._empty_message = placeholder_text
        self._edge = min(620, edge or (min(300, max_width) if max_width else width))
        self._height = min(620, min(300, max_height) if max_height else height)
        self._on_source_changed = on_source_changed
        self._decode_video = decode
        self._decode_image = decode_inspection_image
        self._cancel = threading.Event()
        self._image: InspectionImage | None = None
        self._photo_image: ImageTk.PhotoImage | None = None
        self._video: VideoPreviewWidget | None = None
        self._video_tooltip: Tooltip | None = None
        self._window: tk.Toplevel | None = None
        self._open_path: str | None = None
        self._resize_id: str | None = None
        self._loaded_revision = -1
        self._render_revision = 0
        self._work = build_edit_work_runner(self)
        # Image decode, image resize and video decode share this ONE keyed runner.
        # The coordinator coalesces pending work and cannot overlap old/new decode.
        self._video_runner = _VideoRunner(self)
        self._subject: Any = None
        self._host_eligible = True
        self._policy_owner: Any = master
        self._app_state: Any = None
        self._workspace_bindings: list[tuple[Any, str, str]] = []
        self._workspace_hosts: list[Any] = []
        policy_found = False
        owner: Any = master
        while owner is not None:
            if isinstance(getattr(owner, "master", None), ttk.Notebook):
                self._workspace_hosts.append(owner)
                for event_name in ("<Map>", "<Unmap>"):
                    binding = owner.bind(event_name, self._workspace_changed, add="+")
                    self._workspace_bindings.append((owner, event_name, binding))
            if not policy_found and callable(getattr(owner, "_current_visibility_subject", None)):
                self._policy_owner = owner
                policy_found = True
            app_state = getattr(owner, "app_state", None) or getattr(owner, "_app_state", None)
            if app_state is not None:
                self._app_state = app_state
            owner = getattr(owner, "master", None)
        self._dispatcher = tk_dispatcher_for(self)
        self._policy_callback = lambda: self._dispatcher.invoke(self._policy_changed)
        if callable(getattr(self._app_state, "subscribe", None)):
            self._app_state.subscribe("content_visibility_mode", self._policy_callback)
        self._external_shown = shown_var
        self.shown_var = shown_var if shown_var is not None else tk.BooleanVar(value=default_shown)
        self.status_var = tk.StringVar(value=placeholder_text)
        self.columnconfigure(0, weight=1)
        self.toolbar = ttk.Frame(self, style="Panel.TFrame")
        self.toolbar.grid(row=0, column=0, sticky="ew")
        self.show_button = ttk.Checkbutton(
            self.toolbar,
            text="Show media",
            variable=self.shown_var,
            command=self._toggle,
            style="Dark.TCheckbutton",
        )
        self.detach_button = ttk.Button(
            self.toolbar, text="Detach", command=self.detach, style="Dark.TButton"
        )
        self.open_button = ttk.Button(
            self.toolbar, text="Open original", command=self._open_original, style="Dark.TButton"
        )
        self._toolbar_controls: list[ttk.Button | ttk.Checkbutton] = (
            ([self.show_button] if show_control else [])
            + [self.detach_button]
            + ([self.open_button] if allow_original else [])
        )
        self._toolbar_signature: Any = None
        self.toolbar.bind("<Configure>", self._layout_toolbar, add="+")
        self._layout_toolbar()
        self.body = ttk.Frame(self, style="Panel.TFrame")
        self.body.grid(row=1, column=0, sticky="nsew")
        self.detached_label = ttk.Label(self, text="Media detached", style="Muted.TLabel")
        self.rowconfigure(1, weight=1)
        self._host: tk.Misc = self.body
        self._build_image_host(self.body, self._edge, self._height)
        self.bind("<Map>", self._mapped, add="+")
        self.bind("<Unmap>", self._unmapped, add="+")
        self.bind("<Destroy>", self._destroyed, add="+")
        self._placeholder(placeholder_text)

    def _build_image_host(self, host: tk.Misc, width: int, height: int) -> None:
        self._host = host
        bar = self._zoom_bar = ttk.Frame(host, style="Panel.TFrame")
        if self.model.kind == "image":
            bar.pack(fill="x")
        for index, (text, action) in enumerate(
            (
                ("Fit", self.fit),
                ("100%", self.actual_size),
                ("−", lambda: self.zoom_by(0.8)),
                ("+", lambda: self.zoom_by(1.25)),
            )
        ):
            button = ttk.Button(bar, text=text, command=action, style="Dark.TButton", width=5)
            button.grid(row=index // 2, column=index % 2, sticky="ew")
        viewport = ttk.Frame(host, style="Panel.TFrame")
        self._viewport = viewport
        viewport.pack(fill="both", expand=True)
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        self._canvas = tk.Canvas(
            viewport,
            width=width,
            height=height,
            highlightthickness=0,
            background=TOKENS.colors.surface_secondary,
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(viewport, orient="vertical", command=self._scroll_y)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(viewport, orient="horizontal", command=self._scroll_x)
        horizontal.grid(row=1, column=0, sticky="ew")
        self._canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self._canvas.bind("<Configure>", self._viewport_changed)
        self._canvas.bind("<MouseWheel>", lambda e: self._wheel(e.delta))
        self._canvas.bind("<Button-4>", lambda _e: self._wheel(1))
        self._canvas.bind("<Button-5>", lambda _e: self._wheel(-1))
        self._canvas.bind("<ButtonPress-1>", lambda e: self._canvas.scan_mark(e.x, e.y))
        self._canvas.bind("<B1-Motion>", self._pan)
        self._status_label = ttk.Label(
            host, textvariable=self.status_var, style="Muted.TLabel", wraplength=min(380, width)
        )
        self._status_label.pack(fill="x")

    def _layout_toolbar(self, _event: Any = None) -> None:
        """Use the established flow layout without reparenting controls or decoding media."""
        widths = [control.winfo_reqwidth() for control in self._toolbar_controls]
        available = self.toolbar.winfo_width()
        rows = flow_rows(widths, available if available > 1 else self._edge, gap=4)
        signature = (tuple(tuple(row) for row in rows), tuple(widths))
        if signature == self._toolbar_signature:
            return
        self._toolbar_signature = signature
        y = 0
        for row in rows:
            x = 0
            height = max(self._toolbar_controls[index].winfo_reqheight() for index in row)
            for index in row:
                self._toolbar_controls[index].place(x=x, y=y)
                x += widths[index] + 4
            y += height + 2
        self.toolbar.configure(width=max(widths, default=1), height=max(1, y))

    def _viewport_changed(self, event: Any) -> None:
        self._status_label.configure(wraplength=max(96, event.width - 8))
        self._schedule_render()

    def set_media(
        self,
        path: str | Path | None,
        kind: str | None = None,
        *,
        eligible: bool | None = None,
        subject: Any = None,
    ) -> None:
        if self._closed:
            return
        changed = self.model.select(str(path or ""), kind)
        if changed and path:
            self._empty_message = self._placeholder_text
        if self._external_shown is not None:
            self.model.visibility(shown=self.shown_var.get())
        if subject is not None:
            self._subject = subject
        elif changed:
            self._subject = None
        if eligible is not None:
            self._host_eligible = eligible
        if changed:
            self._release()
            if self._window is not None:
                self.dock()
            if self._external_shown is None:
                self.shown_var.set(self.model.shown)
            self._open_path = self.model.path or None
            if self._on_source_changed:
                self._on_source_changed(self.model.path or None)
        self._refresh()

    def set_image_from_path(self, path: str | Path) -> None:
        self.set_media(path)

    def load_image(self, path: str | None) -> bool:
        self.set_media(path)
        return bool(path)

    def show(self, path: str) -> None:
        self.set_media(path, "video")

    def stop(self) -> None:
        self.clear()

    def current_path(self) -> str | None:
        return self.model.path or None

    def fitted_edge(self) -> int:
        return min(self._canvas.winfo_width(), self._canvas.winfo_height())

    def set_open_target(self, path: str | Path | None) -> None:
        self._open_path = str(path) if path else None

    def _open_original(self) -> None:
        from src.utils.os_shell import open_file

        self._apply_policy()
        if self.model.renderable:
            result = open_file(self._open_path or self.model.path)
            if not result.ok:
                self.status_var.set(result.message)

    def set_visibility(self, shown: bool) -> None:
        self.shown_var.set(shown)
        self._toggle()

    def set_eligibility(self, eligible: bool) -> None:
        self._host_eligible = eligible
        self._refresh()

    def _toggle(self) -> None:
        self.model.visibility(shown=self.shown_var.get())
        self._refresh()

    def _refresh(self) -> None:
        if self._closed:
            return
        self._apply_policy()
        if self.model.kind == "image":
            self._viewport.pack(fill="both", expand=True)
            self._zoom_bar.pack(fill="x", before=self._viewport)
        else:
            self._zoom_bar.pack_forget()
        if self.model.renderable and self.model.kind == "video":
            self._status_label.pack_forget()  # the video renderer already supplies its status
        else:
            self._status_label.pack(fill="x")
        self.open_button.configure(state="normal" if self.model.renderable else "disabled")
        if not self.model.renderable:
            self._release()
            message = (
                self._empty_message
                if not self.model.path
                else "Hidden by content visibility"
                if not self.model.eligible
                else "Media hidden"
                if not self.model.shown
                else "Workspace hidden"
                if not self.model.active
                else "Unsupported media type"
                if self.model.path
                else self._placeholder_text
            )
            self._placeholder(message)
            self.event_generate("<<MediaHidden>>")
            return
        if self._loaded_revision == self.model.revision:
            return
        self._release()
        self._loaded_revision = self.model.revision
        self.status_var.set("Loading media…")
        self._canvas.delete("all")
        if self.model.kind == "video":
            self._viewport.pack_forget()
            self._video = VideoPreviewWidget(
                self._host,
                decode=self._decode_video,
                edge=min(256, self._edge),
                scale=2 if self._window else 1,
                runner=self._video_runner,
            )
            self._video.pack(fill="both", expand=True)
            token = self.model.revision
            self._video.bind(
                "<<VideoPreviewChanged>>", lambda _e: self._video_changed(token), add="+"
            )
            self._video.bind("<Map>", lambda _e: self._video_changed(token), add="+")
            self._video.show(self.model.path)
        else:
            self._viewport.pack(fill="both", expand=True)
            token, path, cancel = self.model.revision, self.model.path, self._cancel
            self._work.submit(
                "media",
                lambda: self._decode_image(path, cancel),
                on_result=lambda result: self._image_ready(token, result),
                on_error=lambda error: self._failed(token, error),
                name="media-inspector-image",
            )

    def _image_ready(self, token: int, image: InspectionImage) -> None:
        if token != self.model.revision or not self.model.renderable:
            image.image.close()
            return
        self._image = image
        self.model.status = "ready"
        self._schedule_render()

    def _video_changed(self, token: int) -> None:
        if token == self.model.revision and self._video is not None and self.model.renderable:
            self.model.status = (
                "ready" if self._video.session.clip is not None else self._video.session.state
            )
            self.status_var.set(self._video.session.message)
            clip = self._video.session.clip
            if clip is not None:
                # Keep the fixed decoder and every detail; avoid duplicating a tall caption in a compact dock.
                caption = f"Bounded preview {clip.width}×{clip.height}"
                if clip.truncated:
                    caption += f" · first {clip.frame_count} frames"
                self._video.caption_var.set(caption)
                self._video.canvas.configure(
                    width=max(min(256, self._edge), clip.width * self._video._scale),
                    height=clip.height * self._video._scale,
                )
                if self._video_tooltip is None:
                    self._video_tooltip = attach_tooltip(
                        self._video.caption, self._video.session.message
                    )
                else:
                    self._video_tooltip.text = self._video.session.message

    def _failed(self, token: int, error: Exception) -> None:
        if token == self.model.revision and self.model.renderable:
            self.model.status = "error"
            self._placeholder(str(error))

    def _schedule_render(self, _event: Any = None) -> None:
        if self._closed or self._image is None or not self.model.renderable:
            return
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self._render_revision += 1
        self._resize_id = self.after(80, self._render_image)

    def _render_image(self) -> None:
        self._resize_id = None
        if self._image is None or not self.model.renderable:
            return
        image = self._image
        revision, render_revision = self.model.revision, self._render_revision
        size = (self._canvas.winfo_width(), self._canvas.winfo_height())
        origin = (self._canvas.xview()[0], self._canvas.yview()[0])
        zoom = self.model.zoom

        def publish(result: Any) -> None:
            if (
                revision != self.model.revision
                or render_revision != self._render_revision
                or not self.model.renderable
            ):
                return
            rendered, virtual, position = result
            self._photo_image = ImageTk.PhotoImage(rendered, master=self._canvas)
            self._canvas.delete("all")
            self._canvas.configure(
                scrollregion=(0, 0, max(size[0], virtual[0]), max(size[1], virtual[1]))
            )
            self._canvas.create_image(*position, image=self._photo_image, anchor="nw")
            label = (
                "Fit"
                if zoom is None
                else f"{zoom * 100:g}% {'source pixels' if image.native else 'decoded preview (downsampled)'}"
            )
            self.status_var.set(f"{image.source_size[0]} × {image.source_size[1]} source | {label}")

        self._work.submit(
            "media",
            lambda: render_viewport(image.image, size, zoom, origin),
            on_result=publish,
            on_error=lambda error: self._failed(revision, error),
            name="media-inspector-fit",
        )

    def fit(self) -> None:
        self.model.zoom = None
        self._canvas.xview_moveto(0)
        self._canvas.yview_moveto(0)
        self._schedule_render()

    def actual_size(self) -> None:
        self.model.zoom = 1.0
        self._schedule_render()

    def zoom_by(self, factor: float) -> None:
        self.model.zoom_by(factor)
        self._loaded_revision = self.model.revision
        self._schedule_render()

    def _wheel(self, delta: float) -> str:
        self.zoom_by(1.25 if delta > 0 else 0.8)
        return "break"

    def _scroll_x(self, *args: Any) -> None:
        self._canvas.xview(*args)
        self._schedule_render()

    def _scroll_y(self, *args: Any) -> None:
        self._canvas.yview(*args)
        self._schedule_render()

    def _pan(self, event: Any) -> None:
        self._canvas.scan_dragto(event.x, event.y, gain=1)
        self._schedule_render()

    def detach(self) -> None:
        if self._closed or self._window is not None or not self.model.path:
            return
        self._release()
        self.model.move(True)
        self.body.grid_remove()
        self.detached_label.grid(row=1, column=0, sticky="w")
        window = self._window = tk.Toplevel(self)
        window.title("Media inspector")
        width, height = (
            min(1000, window.winfo_screenwidth() - 80),
            min(760, window.winfo_screenheight() - 100),
        )
        window.geometry(f"{max(300, width)}x{max(240, height)}+30+30")
        window.protocol("WM_DELETE_WINDOW", self.dock)
        window.bind("<Escape>", lambda _event: self.dock())
        container = ttk.Frame(window, padding=8, style="Panel.TFrame")
        container.pack(fill="both", expand=True)
        ttk.Checkbutton(
            container,
            text="Show media",
            variable=self.shown_var,
            command=self._toggle,
            style="Dark.TCheckbutton",
        ).pack(anchor="w")
        ttk.Button(container, text="Return to dock", command=self.dock, style="Dark.TButton").pack(
            anchor="w"
        )
        self._build_image_host(container, width, height)
        self.detach_button.configure(text="Return to dock", command=self.dock)
        self._layout_toolbar()
        self._refresh()

    def dock(self) -> None:
        window, self._window = self._window, None
        if window is None:
            return
        self._release()
        self.model.move(False)
        window.destroy()
        for child in self.body.winfo_children():
            child.destroy()
        self._build_image_host(self.body, self._edge, self._height)
        self.body.grid()
        self.detached_label.grid_remove()
        self.detach_button.configure(text="Detach", command=self.detach)
        self._layout_toolbar()
        self._refresh()

    def _release(self) -> None:
        self._cancel.set()
        self._cancel = threading.Event()
        self._loaded_revision = -1
        self._image = None
        self._photo_image = None
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
            self._resize_id = None
        if self._video_tooltip is not None:
            try:
                self._video_tooltip.hide()
            except tk.TclError:
                logger.debug("Inspector video caption already destroyed")
            self._video_tooltip = None
        if self._video is not None:
            self._video.stop()
            self._video.destroy()
            self._video = None
        try:
            self._canvas.delete("all")
        except tk.TclError:
            logger.debug("Inspector canvas already destroyed")

    def _placeholder(self, text: str) -> None:
        self.status_var.set(text)
        self._canvas.delete("all")

    def set_placeholder(self, text: str) -> None:
        self._empty_message = text
        self.set_media(None)
        self._placeholder(text)

    def set_loading(self) -> None:
        self.set_placeholder("Loading media…")

    def clear(self) -> None:
        if self._closed:
            return
        self._empty_message = self._placeholder_text
        self.set_media(None)

    clear_media = clear

    def set_image_reference(self, path: str, *, subject: Any = None) -> None:
        """Use a host-validated path, keeping its selection/evidence authority outside the viewer."""
        self.set_media(path, "image", subject=subject)

    def _apply_policy(self) -> None:
        mode = str(
            getattr(self._app_state, "content_visibility_mode", None)
            or getattr(self._policy_owner, "_content_visibility_mode", "nsfw")
        )
        getter = getattr(self._policy_owner, "_current_visibility_subject", None)
        subject = (
            self._subject
            if self._subject is not None
            else getter()
            if callable(getter)
            else {"name": self.model.path}
        )
        self.model.visibility(
            eligible=self._host_eligible and ContentVisibilityResolver(mode).is_visible(subject)
        )

    def _policy_changed(self) -> None:
        if not self._closed:
            self._refresh()

    def _mapped(self, event: Any) -> None:
        if event.widget is self:
            self.model.visibility(
                active=all(host.winfo_ismapped() for host in self._workspace_hosts)
            )
            self._refresh()

    def _workspace_changed(self, event: Any) -> None:
        if not self._closed and event.widget in self._workspace_hosts:
            self.model.visibility(
                active=bool(self.winfo_ismapped())
                and all(host.winfo_ismapped() for host in self._workspace_hosts)
            )
            self._refresh()

    def _unmapped(self, event: Any) -> None:
        if event.widget is self:
            self.model.visibility(active=False)
            self._refresh()

    def _destroyed(self, event: Any) -> None:
        if event.widget is self and not self._closed:
            self._release()
            self._closed = True
            self._work.close()
            for owner, event_name, binding in self._workspace_bindings:
                try:
                    owner.unbind(event_name, binding)
                except tk.TclError:
                    logger.debug("Inspector workspace already destroyed")
            self._workspace_bindings.clear()
            if callable(getattr(self._app_state, "unsubscribe", None)):
                self._app_state.unsubscribe("content_visibility_mode", self._policy_callback)
            if self._window is not None:
                self._window.destroy()
                self._window = None

    def close(self) -> None:
        self.destroy()

    def destroy(self) -> None:
        if not self._closed:
            self._destroyed(type("Destroy", (), {"widget": self})())
        super().destroy()


class _VideoRunner(BackgroundWorkRunner):
    """Adapt existing latest-wins worker semantics to the existing video session API."""

    def __init__(self, inspector: MediaInspector) -> None:
        self.inspector = inspector

    def start(self, name: str, work: Any, on_done: Any) -> None:
        self.inspector._work.submit(
            "media",
            work,
            on_result=on_done,
            on_error=lambda error: on_done(WorkOutcome(error=str(error))),
            name=name,
        )

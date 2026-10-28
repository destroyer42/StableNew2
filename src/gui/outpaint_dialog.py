"""Review's Extend Canvas dialog. Blocking preparation/admission uses the existing worker runner."""

from __future__ import annotations

import json
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import ttk
from typing import Any

from PIL import Image, ImageTk

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.controller.masked_edit_service import MaskEditPreview
from src.controller.outpaint_edit_service import (
    OutpaintSettings,
    describe_support,
    outpaint_preview_summary,
    prepare_outpaint_edit,
)
from src.gui.theme_v2 import apply_toplevel_theme
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui_v2.outpaint_canvas_view import render_canvas_view
from src.pipeline.image_edit_inputs import read_source
from src.pipeline.outpaint_canvas import (
    ALIGNMENT,
    Extents,
    aligned_extents,
    normalize_original,
    plan_geometry,
)
from src.utils.thread_registry import get_thread_registry

_PROXY_EDGE = 1024
_NOT_QUALIFIED = (
    "Physical image quality has not been qualified; only the original pixels are guaranteed."
)


class OutpaintDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        source_path: Path,
        controller: Any,
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        super().__init__(master)
        apply_toplevel_theme(self)
        self.title("Extend Canvas — outpainting keeps the original pixels")
        self.geometry("1000x720")
        self.minsize(760, 560)
        self._controller = controller
        self.source_path = source_path
        self._proxy: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._original_size: tuple[int, int] | None = None
        self._baseline: dict[str, Any] = {}
        self._fallback: dict[str, Any] = {}
        self._source_sha256 = ""
        self._version = 0
        self._preview: MaskEditPreview | None = None
        self._busy = True
        self._attempted = False
        self._closed = False
        self.left, self.right, self.top, self.bottom = (tk.IntVar(value=0) for _ in range(4))
        self.denoise = tk.DoubleVar(value=0.85)
        self.blur = tk.IntVar(value=8)
        self.show_mask = tk.BooleanVar(value=False)
        self.dimensions = tk.StringVar(value="")
        self.support = tk.StringVar(value="Checking the selected model and backend…")
        self.status = tk.StringVar(value=f"Loading source… {_NOT_QUALIFIED}")
        try:
            self._fallback = deepcopy(self._controller._build_reprocess_config(["img2img"]))
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
        ) as exc:  # shown at Preview, where the service refuses an unusable target
            self.status.set(f"Settings unavailable: {exc}")
        self._build()
        dispatcher = tk_dispatcher_for(self)
        self._runner = runner or BackgroundWorkRunner(
            spawn=lambda name, target: get_thread_registry().spawn(
                target=target, name=name, daemon=False, purpose="Review outpaint"
            ),
            dispatch=dispatcher.invoke,
        )
        for variable in (self.left, self.right, self.top, self.bottom, self.denoise, self.blur):
            variable.trace_add("write", lambda *_: self._changed())
        self.show_mask.trace_add("write", lambda *_: self._render())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind(
            "<Destroy>",
            lambda event: setattr(self, "_closed", True) if event.widget is self else None,
        )
        self._runner.start("OutpaintLoad", self._load, self._loaded)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self, background="#232323", highlightthickness=0, width=360, height=240
        )
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.canvas.bind("<Configure>", lambda _: self._render())
        controls = ttk.Frame(self, padding=(4, 8))
        controls.grid(row=0, column=1, sticky="n")
        ttk.Label(controls, text="Extend canvas by (pixels)").grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        for index, (label, variable) in enumerate(
            (("Left", self.left), ("Right", self.right), ("Top", self.top), ("Bottom", self.bottom))
        ):
            row, column = 1 + index // 2, (index % 2) * 2
            ttk.Label(controls, text=label).grid(row=row, column=column, sticky="e", pady=2)
            ttk.Spinbox(
                controls, textvariable=variable, from_=0, to=2048, increment=ALIGNMENT, width=6
            ).grid(row=row, column=column + 1, sticky="w", padx=(4, 10))
        ttk.Label(controls, textvariable=self.dimensions, wraplength=290, justify="left").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(6, 2)
        )
        self.align_button = ttk.Button(controls, text=f"Align to {ALIGNMENT}", command=self._align)
        self.align_button.grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(controls, text="Show mask", variable=self.show_mask).grid(
            row=4, column=2, columnspan=2, sticky="w"
        )
        ttk.Label(controls, text="Outpainting prompt (what appears in the new space)").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )
        self.prompt = tk.Text(controls, width=34, height=4, wrap="word")
        self.prompt.grid(row=6, column=0, columnspan=4, sticky="ew")
        self.prompt.bind("<<Modified>>", self._prompt_changed)
        for column, (label, setting, low, high, increment) in enumerate(
            (("Denoising", self.denoise, 0.01, 1.0, 0.05), ("Mask blur", self.blur, 0, 64, 1))
        ):
            ttk.Label(controls, text=label).grid(row=7, column=column * 2, sticky="e", pady=(6, 0))
            ttk.Spinbox(
                controls, textvariable=setting, from_=low, to=high, increment=increment, width=6
            ).grid(row=7, column=column * 2 + 1, sticky="w", padx=(4, 10), pady=(6, 0))
        ttk.Label(controls, textvariable=self.support, wraplength=290, justify="left").grid(
            row=8, column=0, columnspan=4, sticky="w", pady=(6, 0)
        )
        self.details = tk.Text(self, height=5, wrap="word", state="disabled")
        self.details.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8)
        actions = ttk.Frame(self, padding=8)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.preview_button = ttk.Button(
            actions, text="Preview frozen job", command=self._prepare, state="disabled"
        )
        self.preview_button.pack(side="left")
        self.queue_button = ttk.Button(
            actions, text="Add prepared job to Queue", command=self._submit, state="disabled"
        )
        self.queue_button.pack(side="left", padx=8)
        self.close_button = ttk.Button(actions, text="Close", command=self._close)
        self.close_button.pack(side="right")
        ttk.Label(self, textvariable=self.status, wraplength=940).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6)
        )

    # ------------------------------------------------------------------ loading (worker) and state

    def _load(self) -> WorkOutcome:
        source = read_source(self.source_path)
        pixels = normalize_original(source.data)
        proxy = pixels.copy()
        proxy.thumbnail((_PROXY_EDGE, _PROXY_EDGE))
        baseline = self._controller._extract_reprocess_baseline_from_image(self.source_path)
        model = str(baseline.get("model") or self._fallback.get("model") or "")
        options = (
            self._fallback.get("backend_options")
            or (baseline.get("config") or {}).get("backend_options")
            or {}
        )
        ok, text = describe_support(model, options)
        return WorkOutcome((source, pixels.size, proxy, baseline, ok, text))

    def _loaded(self, outcome: WorkOutcome) -> None:
        if self._closed:
            return
        self._busy = False
        if outcome.error:
            self.status.set(f"Source unavailable: {outcome.error}")
            return
        source, self._original_size, self._proxy, self._baseline, _ok, text = outcome.value
        self._source_sha256 = source.sha256
        self.support.set(text)
        self.preview_button.state(["!disabled"])
        self.status.set(
            f"{self.source_path.name} — {self._original_size[0]} × {self._original_size[1]}. "
            f"Choose margins and describe the new space. {_NOT_QUALIFIED}"
        )
        self._changed(keep_status=True)

    def _extents(self) -> Extents:
        try:
            return Extents(self.left.get(), self.right.get(), self.top.get(), self.bottom.get())
        except tk.TclError as exc:
            raise ValueError("Enter a whole number of pixels for every side") from exc

    def _changed(self, keep_status: bool = False) -> None:
        self._version += 1
        self._preview = None
        self.queue_button.state(["disabled"])
        if self._original_size is not None:
            try:
                extents = self._extents()
                geometry = plan_geometry(self._original_size, extents)
                self.dimensions.set(
                    f"New size: {geometry.expanded_size[0]} × {geometry.expanded_size[1]} px "
                    f"(original {self._original_size[0]} × {self._original_size[1]} at "
                    f"{geometry.original_origin[0]}, {geometry.original_origin[1]})"
                )
            except ValueError as exc:
                self.dimensions.set(f"Cannot preview this size: {exc}")
            if not keep_status:
                self.status.set("Working draft changed. Preview again before queueing.")
        self._render()

    def _prompt_changed(self, _event: Any) -> None:
        if self.prompt.edit_modified():
            self.prompt.edit_modified(False)
            self._changed()

    def _align(self) -> None:
        if self._original_size is None or self._busy:
            return
        try:
            aligned = aligned_extents(self._original_size, self._extents())
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.right.set(aligned.right)
        self.bottom.set(aligned.bottom)

    def _render(self) -> None:
        if self._proxy is None or self._original_size is None or self._closed:
            return
        try:
            extents = self._extents()
            extents.validate()
        except ValueError:
            extents = (
                Extents()
            )  # the dimensions label states why; the view keeps showing the original
        size = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        view = render_canvas_view(
            self._proxy,
            self._original_size,
            extents,
            size,
            show_mask=self.show_mask.get(),
        )
        self._photo = ImageTk.PhotoImage(view)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

    # ------------------------------------------------------------------ preview and admission

    def _prepare(self) -> None:
        if self._original_size is None or self._busy:
            return
        self._changed()
        self._attempted = (
            False  # a fresh preview starts a fresh admission; Close must not report a stale one
        )
        self.prompt.edit_modified(False)
        version = self._version
        try:
            settings = OutpaintSettings(
                self.prompt.get("1.0", "end-1c"),
                self._extents(),
                self.denoise.get(),
                self.blur.get(),
            )
            settings.validate()
        except (ValueError, tk.TclError) as exc:
            self.status.set(f"Preview refused: {exc}")
            return
        fallback = deepcopy(self._fallback)
        source_path, source_sha, baseline = (
            str(self.source_path),
            self._source_sha256,
            deepcopy(self._baseline),
        )
        self._busy = True
        self.preview_button.state(["disabled"])
        self.status.set("Preparing and verifying frozen inputs…")

        def work() -> WorkOutcome:
            return WorkOutcome(
                prepare_outpaint_edit(
                    source_path=source_path,
                    source_sha256=source_sha,
                    settings=settings,
                    fallback_config=fallback,
                    baseline=baseline,
                )
            )

        def done(outcome: WorkOutcome) -> None:
            if self._closed:
                return
            self._busy = False
            self.preview_button.state(["!disabled"])
            if version != self._version:
                self.status.set("Draft changed during preparation. Preview again.")
                return
            if outcome.error:
                self.status.set(f"Preview refused: {outcome.error}")
                return
            self._preview = outcome.value
            self._attempted = False
            assert self._preview is not None
            self._show_summary(outcome.value)
            self.queue_button.state(["!disabled"])
            self.status.set(
                f"Preview ready. Review the frozen geometry, mask and settings, then Add to Queue. {_NOT_QUALIFIED}"
            )

        self._runner.start("OutpaintPreview", work, done)

    def _show_summary(self, preview: MaskEditPreview) -> None:
        summary = outpaint_preview_summary(preview)
        visibility = ContentVisibilityResolver(
            getattr(getattr(self._controller, "app_state", None), "content_visibility_mode", "nsfw")
        )

        def redact(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: visibility.redact_text(
                        item, item={"positive_prompt": preview.job.positive_prompt}
                    )
                    if "prompt" in key and isinstance(item, str)
                    else redact(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", json.dumps(redact(summary), indent=2, default=str))
        self.details.configure(state="disabled")

    def _submit(self) -> None:
        if self._preview is None or self._busy or self._attempted:
            return
        preview, service = self._preview, self._controller.job_service
        self._attempted = True
        self._busy = True
        self.queue_button.state(["disabled"])
        self.preview_button.state(["disabled"])

        def done(outcome: WorkOutcome) -> None:
            if self._closed:
                return
            self._busy = False
            self.preview_button.state(["!disabled"])
            if outcome.error or outcome.value != 1:
                self.status.set(
                    f"Admission failed; draft preserved. {outcome.error or 'No job admitted.'} Preview again before retrying."
                )
                return
            self.status.set(
                f"Queued frozen job {preview.job.job_id}. The original image is unchanged."
            )

        self._runner.start("OutpaintAdmission", lambda: WorkOutcome(preview.submit(service)), done)

    def _close(self) -> None:
        if self._busy and self._attempted:
            self.status.set("Admission is in progress. Wait for its result before closing.")
            return
        self._closed = True
        self.destroy()

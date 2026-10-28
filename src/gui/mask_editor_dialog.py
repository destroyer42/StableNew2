"""Review's still-image mask editor. Blocking preparation/admission uses the existing worker runner."""

from __future__ import annotations

import io
import json
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import ttk
from typing import Any

from PIL import Image, ImageTk

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.controller.masked_edit_service import MaskEditPreview, MaskEditSettings, prepare_mask_edit
from src.gui.theme_v2 import apply_toplevel_theme
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui_v2.mask_editor_state import MaskDocument, MaskViewport
from src.pipeline.image_edit_inputs import read_source
from src.pipeline.njr_core_v26 import thaw_json
from src.utils.thread_registry import get_thread_registry


class MaskEditorDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        source_path: Path,
        controller: Any,
        runner: BackgroundWorkRunner | None = None,
        suggested_mask: bytes | None = None,
        suggested_source_sha256: str = "",
    ) -> None:
        super().__init__(master)
        apply_toplevel_theme(self)
        self.title("Edit Mask — white / red changes, black preserves")
        self.geometry("1100x820")
        self.minsize(800, 600)
        self._controller = controller
        self.source_path = source_path
        self.document: MaskDocument | None = None
        self.viewport = MaskViewport()
        self._image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._baseline: dict[str, Any] = {}
        self._source_sha256 = ""
        self._suggested_mask = suggested_mask  # an operator-accepted Smart Review proposal; checked again once the source loads
        self._suggested_source_sha256 = suggested_source_sha256
        self._version = 0
        self._preview: MaskEditPreview | None = None
        self._busy = True
        self._attempted = False
        self._closed = False
        self._last_point: tuple[float, float] | None = None
        self._pan_point: tuple[int, int] | None = None
        self.brush_size = tk.IntVar(value=40)
        self.erase = tk.BooleanVar(value=False)
        self.denoise = tk.DoubleVar(value=0.45)
        self.blur = tk.IntVar(value=4)
        self.padding = tk.IntVar(value=32)
        self.only_masked = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Loading source…")
        self._build()
        dispatcher = tk_dispatcher_for(self)
        self._runner = runner or BackgroundWorkRunner(
            spawn=lambda name, target: get_thread_registry().spawn(
                target=target, name=name, daemon=False, purpose="Review masked edit"
            ),
            dispatch=dispatcher.invoke,
        )
        for variable in (self.denoise, self.blur, self.padding, self.only_masked):
            variable.trace_add("write", lambda *_: self._invalidate())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind(
            "<Destroy>",
            lambda event: setattr(self, "_closed", True) if event.widget is self else None,
        )
        self._runner.start("MaskEditorLoad", self._load, self._loaded)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        tools = ttk.Frame(self, padding=8)
        tools.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Radiobutton(
            tools, text="Paint", variable=self.erase, value=False, style="Page.TRadiobutton"
        ).pack(side="left")
        ttk.Radiobutton(
            tools, text="Erase", variable=self.erase, value=True, style="Page.TRadiobutton"
        ).pack(side="left")
        ttk.Label(tools, text="Brush (source pixels)").pack(side="left", padx=6)
        ttk.Spinbox(tools, from_=1, to=512, width=5, textvariable=self.brush_size).pack(side="left")
        for label, action in (
            ("Undo", lambda: self._history("undo")),
            ("Redo", lambda: self._history("redo")),
            ("Clear", lambda: self._history("clear")),
            ("−", lambda: self._zoom(0.8)),
            ("+", lambda: self._zoom(1.25)),
            ("Fit", self._fit),
        ):
            ttk.Button(tools, text=label, command=action).pack(side="left", padx=3)
        ttk.Label(tools, text="Pan: middle/right drag • Wheel: zoom").pack(side="left", padx=6)
        self.canvas = tk.Canvas(self, background="#232323", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=8)
        self.canvas.bind("<Configure>", lambda _: self._render())
        self.canvas.bind("<ButtonPress-1>", self._stroke_start)
        self.canvas.bind("<B1-Motion>", self._stroke_move)
        self.canvas.bind("<ButtonRelease-1>", lambda _: setattr(self, "_last_point", None))
        for button in (2, 3):
            self.canvas.bind(f"<ButtonPress-{button}>", self._pan_start)
            self.canvas.bind(f"<B{button}-Motion>", self._pan)
        self.canvas.bind(
            "<MouseWheel>",
            lambda event: self._zoom(1.25 if event.delta > 0 else 0.8, event.x, event.y),
        )
        self.canvas.bind("<Button-4>", lambda event: self._zoom(1.25, event.x, event.y))
        self.canvas.bind("<Button-5>", lambda event: self._zoom(0.8, event.x, event.y))
        controls = ttk.Frame(self, padding=8)
        controls.grid(row=1, column=1, sticky="nsew")
        ttk.Label(
            controls,
            text="Red overlay / white mask: CHANGE\nBlack mask: PRESERVE\nSource image is never overwritten.",
            wraplength=280,
        ).pack(anchor="w", pady=(0, 10))
        ttk.Label(controls, text="Editing prompt (replaces source prompt)").pack(anchor="w")
        self.prompt = tk.Text(controls, width=34, height=8, wrap="word")
        self.prompt.pack(fill="x")
        self.prompt.bind("<<Modified>>", self._prompt_changed)
        for label, variable, low, high, increment in (
            ("Denoising strength", self.denoise, 0.01, 1.0, 0.05),
            ("Mask blur (pixels)", self.blur, 0, 64, 1),
            ("Masked-region padding", self.padding, 0, 256, 8),
        ):
            ttk.Label(controls, text=label).pack(anchor="w", pady=(8, 0))
            ttk.Spinbox(
                controls, textvariable=variable, from_=low, to=high, increment=increment, width=12
            ).pack(anchor="w")
        ttk.Checkbutton(
            controls, text="Process only masked region", variable=self.only_masked
        ).pack(anchor="w", pady=8)
        ttk.Label(
            controls,
            text="Forge + registry-resolved SDXL base only.\nOriginal masked content is the fill baseline.\nPreview lists effective settings and frozen inputs.",
            wraplength=280,
        ).pack(anchor="w", pady=8)
        self.details = tk.Text(self, height=9, wrap="word", state="disabled")
        self.details.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        actions = ttk.Frame(self, padding=8)
        actions.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.preview_button = ttk.Button(
            actions, text="Preview frozen job", command=self._prepare, state="disabled"
        )
        self.preview_button.pack(side="left")
        self.queue_button = ttk.Button(
            actions, text="Add prepared job to Queue", command=self._submit, state="disabled"
        )
        self.queue_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Close", command=self._close).pack(side="right")
        ttk.Label(self, textvariable=self.status, wraplength=1000).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=8
        )

    def _load(self) -> WorkOutcome:
        source = read_source(self.source_path)
        with Image.open(io.BytesIO(source.data)) as image:
            pixels = image.convert("RGB")
        baseline = self._controller._extract_reprocess_baseline_from_image(self.source_path)
        return WorkOutcome((source, pixels, baseline))

    def _loaded(self, outcome: WorkOutcome) -> None:
        if self._closed:
            return
        self._busy = False
        if outcome.error:
            self.status.set(f"Source unavailable: {outcome.error}")
            return
        source, self._image, self._baseline = outcome.value
        self._source_sha256 = source.sha256
        self.document = MaskDocument((source.width, source.height))
        self.preview_button.state(["!disabled"])
        self.status.set(
            f"{self.source_path.name} — {source.width} × {source.height}. Paint a region and describe the edit."
        )
        if self._suggested_mask is not None:
            self._adopt_suggested_mask(source)
        self._fit()
        self.after_idle(self._fit)

    def _adopt_suggested_mask(self, source: Any) -> None:
        """Copy an accepted Smart Review mask into the document, only if it is exactly this source's mask. Undo removes it."""

        from src.review.assist.contracts import AssistError, SourceIdentity
        from src.review.assist.masks import mask_image

        data, self._suggested_mask = self._suggested_mask, None
        if self.document is None or data is None:
            return
        if not self._suggested_source_sha256 or self._suggested_source_sha256 != source.sha256:
            self.status.set(
                "The suggested mask was not loaded: the image changed after it was proposed."
            )
            return
        identity = SourceIdentity(
            source.sha256, source.size, source.width, source.height, 1, source.image_format
        )
        try:
            mask = mask_image(data, identity)
        except AssistError as exc:
            self.status.set(f"The suggested mask was not loaded: {exc.message}")
            return
        self.document.checkpoint()
        self.document.mask = mask
        self.document.revision += 1
        self._invalidate()
        self.status.set(
            "Suggested mask loaded (red = change). Paint or erase to adjust, then describe the edit and Preview."
        )

    def _invalidate(self) -> None:
        self._version += 1
        self._preview = None
        self.queue_button.state(["disabled"])
        if self.document is not None:
            self.status.set("Working draft changed. Preview again before queueing.")

    def _prompt_changed(self, _event: Any) -> None:
        if self.prompt.edit_modified():
            self.prompt.edit_modified(False)
            self._invalidate()

    def _stroke_start(self, event: Any) -> None:
        if self.document is None or self._busy:
            return
        self.document.checkpoint()
        self._last_point = self.viewport.image_point(event.x, event.y)
        self._stroke_move(event)

    def _stroke_move(self, event: Any) -> None:
        if self.document is None or self._last_point is None or self._busy:
            return
        point = self.viewport.image_point(event.x, event.y)
        try:
            self.document.paint(
                self._last_point, point, self.brush_size.get(), erase=self.erase.get()
            )
        except (ValueError, tk.TclError) as exc:
            self.status.set(str(exc))
            return
        self._last_point = point
        self._invalidate()
        self._render()

    def _history(self, action: str) -> None:
        if self.document is not None and not self._busy:
            getattr(self.document, action)()
            self._invalidate()
            self._render()

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
        if self.document is None or self._image is None or self._closed:
            return
        size = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self._photo = ImageTk.PhotoImage(self.document.render(self._image, self.viewport, size))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

    def _prepare(self) -> None:
        if self.document is None or self._busy:
            return
        self._invalidate()
        self.prompt.edit_modified(False)
        version = self._version
        try:
            settings = MaskEditSettings(
                self.prompt.get("1.0", "end-1c"),
                self.denoise.get(),
                self.blur.get(),
                self.padding.get(),
                self.only_masked.get(),
            )
            settings.validate()
            fallback = deepcopy(self._controller._build_reprocess_config(["img2img"]))
        except (ValueError, tk.TclError) as exc:
            self.status.set(str(exc))
            return
        mask = self.document.mask.copy()
        source_path, source_sha, baseline = (
            str(self.source_path),
            self._source_sha256,
            deepcopy(self._baseline),
        )

        def work() -> WorkOutcome:
            stream = io.BytesIO()
            mask.save(stream, format="PNG")
            return WorkOutcome(
                prepare_mask_edit(
                    source_path=source_path,
                    source_sha256=source_sha,
                    mask_data=stream.getvalue(),
                    settings=settings,
                    fallback_config=fallback,
                    baseline=baseline,
                )
            )

        self._busy = True
        self.preview_button.state(["disabled"])
        self.status.set("Preparing and verifying frozen inputs…")

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
            job = self._preview.job
            summary = {
                "source": source_path,
                "job_id": job.job_id,
                "model": job.base_model,
                "prompt": job.positive_prompt,
                "negative_prompt": job.negative_prompt,
                "backend": job.backend_options,
                "effective_img2img": thaw_json(job.config["img2img"]),
                "resolved_stage": job.stage_chain[0].to_dict(),
                "restrictions": "SDXL base / Forge; white changes; black preserves; no outpainting",
            }
            visibility = ContentVisibilityResolver(
                getattr(
                    getattr(self._controller, "app_state", None), "content_visibility_mode", "nsfw"
                )
            )

            def redact(value: Any) -> Any:
                if isinstance(value, dict):
                    return {
                        key: visibility.redact_text(
                            item, item={"positive_prompt": job.positive_prompt}
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
            self.queue_button.state(["!disabled"])
            self.status.set(
                "Preview ready. Review the frozen source, mask and settings, then Add to Queue."
            )

        self._runner.start("MaskEditorPreview", work, done)

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
                f"Queued frozen job {preview.job.job_id}. Mask and source draft preserved."
            )

        self._runner.start(
            "MaskEditorAdmission", lambda: WorkOutcome(preview.submit(service)), done
        )

    def _close(self) -> None:
        if self._busy and self._attempted:
            self.status.set("Admission is in progress. Wait for its result before closing.")
            return
        self._closed = True
        self.destroy()

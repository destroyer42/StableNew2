"""PromptPack OpenPose reference picker (PR-IMG-CNET-210).

Choose a previously rendered OpenPose image from ``<WebUI root>/models/OpenPose`` for the current PromptPack slot and
edit its ControlNet settings, much like choosing a LoRA. The reference image is conditioning input, never prompt text.

The panel owns presentation only. The slot's declaration (a plain JSON value) is the single source of truth: the panel
renders it, and every edit produces a new declaration that the parent persists through the workspace state. Nothing here
builds a backend payload, talks to Forge, hashes a file on the Tk thread or decides execution: library scans, header
reads and thumbnail decoding run on a worker (the injected ``runner``), and results are marshalled back with ``after``.

A saved selection is never removed because the target cannot run it; the panel shows why and keeps it.
"""

from __future__ import annotations

import base64
import copy
import logging
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.assets.controlnet_structure import (
    STATUS_SDXL,
    ControlNetModelOption,
    list_controlnet_models,
)
from src.conditioning.openpose import (
    CONTROL_MODES,
    DEFAULT_CONTROL_MODE,
    DEFAULT_GUIDANCE_END,
    DEFAULT_GUIDANCE_START,
    DEFAULT_RESIZE_MODE,
    DEFAULT_WEIGHT,
    MAX_WEIGHT,
    MIN_WEIGHT,
    RESIZE_MODES,
    declaration_problems,
    new_declaration,
    parse_declaration,
)
from src.conditioning.openpose_catalog import (
    LibraryEntry,
    LibraryListing,
    controlnet_folder,
    filter_entries,
    refresh_listing,
)
from src.conditioning.openpose_library import (
    OpenPoseInputError,
    library_root,
    read_library_image,
    thumbnail_png,
)
from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.gui.tooltip import attach_tooltip
from src.gui_v2.openpose_conditioning_view import (
    MODEL_MISSING,
    SEVERITY_ERROR,
    SEVERITY_OK,
    SEVERITY_WARNING,
    OpenPoseView,
    declaration_from_view,
    describe_openpose,
)
from src.image_backends.openpose_capability import OpenPoseTarget

logger = logging.getLogger(__name__)

#: ``work`` runs off the Tk thread; ``done(result, error)`` runs on it.
Runner = Callable[[Callable[[], Any], Callable[[Any, Exception | None], None]], None]

_THUMB_EDGE = 160


class OpenPosePickerPanel(ttk.LabelFrame):
    """One slot's OpenPose conditioning editor."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_change_callback: Callable[[], None] | None = None,
        registry_factory: Callable[[], Any] | None = None,
        runner: Runner | None = None,
        auto_refresh: bool = False,
        refresh_on_map: bool = True,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("text", "ControlNet OpenPose (SDXL on Forge)")
        kwargs.setdefault("padding", 6)
        super().__init__(parent, **kwargs)
        self.on_change_callback = on_change_callback
        self._registry_factory = registry_factory
        self._registry: Any | None = None
        self._runner: Runner = runner or self._threaded_runner
        self._declaration: Any = None
        self._listing = LibraryListing()
        self._listing_loaded = False
        self._models: list[ControlNetModelOption] = []
        self._target: OpenPoseTarget | None = None
        self._visible: list[LibraryEntry] = []
        self._content_visibility_mode = "nsfw"
        self._suppress = False
        self._destroyed = False
        self._thumb_request = 0
        self._photo: tk.PhotoImage | None = None
        self._shown_identity = ""
        self._pending_identity = ""
        self._first_map_done = not refresh_on_map
        self._build_ui()
        self._render()
        if refresh_on_map:
            # Lazy: nothing is scanned (or written) until the picker is first shown to the operator.
            self.bind("<Map>", self._on_first_map, add="+")
        if auto_refresh:
            self.after(50, self.refresh_library)

    # ------------------------------------------------------------------ construction

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        self.enable_var = tk.BooleanVar(value=False)
        self.enable_check = ttk.Checkbutton(
            header, text="Use pose reference", variable=self.enable_var, command=self._on_enable_toggled
        )
        self.enable_check.grid(row=0, column=0, sticky="w")
        self.summary_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.summary_var, justify="left").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        self.refresh_button = ttk.Button(header, text="↻ Refresh", width=10, command=self.refresh_library)
        self.refresh_button.grid(row=0, column=2, padx=(4, 0))
        self.remove_button = ttk.Button(header, text="Remove", width=8, command=self._on_remove)
        self.remove_button.grid(row=0, column=3, padx=(4, 0))
        attach_tooltip(
            self.enable_check,
            "Condition this slot's base SDXL generation on a pre-rendered OpenPose image. "
            "The image is conditioning input, not prompt text.",
        )

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        body.columnconfigure(0, weight=1)

        browse = ttk.Frame(body)
        browse.grid(row=0, column=0, sticky="nsew")
        browse.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar(value="")
        self.search_entry = ttk.Entry(browse, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        attach_tooltip(self.search_entry, "Filter the OpenPose library by folder or file name.")
        list_frame = ttk.Frame(browse)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        list_frame.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(list_frame, height=5, exportselection=False, activestyle="none")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        preview = ttk.Frame(body)
        preview.grid(row=0, column=1, sticky="n", padx=(8, 0))
        self.thumbnail_label = ttk.Label(preview, text="No pose selected", anchor="center", justify="center")
        self.thumbnail_label.configure(width=22)
        self.thumbnail_label.grid(row=0, column=0)
        self.selected_var = tk.StringVar(value="")
        ttk.Label(preview, textvariable=self.selected_var, wraplength=_THUMB_EDGE + 40, justify="center").grid(
            row=1, column=0, pady=(4, 0)
        )

        settings = ttk.Frame(self)
        settings.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="ControlNet model").grid(row=0, column=0, sticky="w")
        self.model_var = tk.StringVar(value="")
        self.model_combo = ttk.Combobox(settings, textvariable=self.model_var, width=34)
        self.model_combo.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.model_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_model_changed())
        self.model_combo.bind("<Return>", lambda _e: self._on_model_changed())
        self.model_combo.bind("<FocusOut>", lambda _e: self._on_model_changed())
        attach_tooltip(
            self.model_combo,
            "The SDXL OpenPose ControlNet model (from models/ControlNet). "
            "The exact name Forge advertises is used when the job runs.",
        )

        numbers = ttk.Frame(settings)
        numbers.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.weight_var = tk.StringVar(value=f"{DEFAULT_WEIGHT:g}")
        self.start_var = tk.StringVar(value=f"{DEFAULT_GUIDANCE_START:g}")
        self.end_var = tk.StringVar(value=f"{DEFAULT_GUIDANCE_END:g}")
        self.weight_spin = self._spin(numbers, "Strength", self.weight_var, MIN_WEIGHT, MAX_WEIGHT, 0, 0.05)
        self.start_spin = self._spin(numbers, "Guidance start", self.start_var, 0.0, 1.0, 2, 0.05)
        self.end_spin = self._spin(numbers, "Guidance end", self.end_var, 0.0, 1.0, 4, 0.05)
        self.control_mode_var = tk.StringVar(value=DEFAULT_CONTROL_MODE)
        self.resize_mode_var = tk.StringVar(value=DEFAULT_RESIZE_MODE)
        ttk.Label(numbers, text="Control mode").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.control_mode_combo = ttk.Combobox(
            numbers, textvariable=self.control_mode_var, values=CONTROL_MODES, state="readonly", width=26
        )
        self.control_mode_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=(4, 8), pady=(4, 0))
        self.control_mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_choice_changed())
        ttk.Label(numbers, text="Resize").grid(row=1, column=3, sticky="w", pady=(4, 0))
        self.resize_mode_combo = ttk.Combobox(
            numbers, textvariable=self.resize_mode_var, values=RESIZE_MODES, state="readonly", width=16
        )
        self.resize_mode_combo.grid(row=1, column=4, columnspan=2, sticky="w", padx=(4, 0), pady=(4, 0))
        self.resize_mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_choice_changed())
        ttk.Label(
            settings, text="Preprocessor: None (pre-rendered OpenPose image)", foreground="#a0a0a0"
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.notes_var = tk.StringVar(value="")
        self.notes_label = ttk.Label(self, textvariable=self.notes_var, wraplength=560, justify="left")
        self.notes_label.grid(row=3, column=0, sticky="ew", pady=(6, 0))

    def _spin(
        self, parent: ttk.Frame, label: str, variable: tk.StringVar, low: float, high: float, column: int, step: float
    ) -> ttk.Spinbox:
        ttk.Label(parent, text=label).grid(row=0, column=column, sticky="w", padx=(0 if column == 0 else 8, 0))
        spin = ttk.Spinbox(
            parent,
            from_=low,
            to=high,
            increment=step,
            textvariable=variable,
            width=6,
            command=self._on_number_changed,
        )
        spin.grid(row=0, column=column + 1, sticky="w", padx=(4, 0))
        spin.bind("<Return>", lambda _e: self._on_number_changed())
        spin.bind("<FocusOut>", lambda _e: self._on_number_changed())
        return spin

    def _on_first_map(self, _event: object | None = None) -> None:
        if self._first_map_done:
            return
        self._first_map_done = True
        self.refresh_library()

    # ------------------------------------------------------------------ public API

    def set_declaration(self, raw: Any) -> None:
        """Show a slot's declaration (``None`` = none). Never fires the change callback."""

        self._declaration = copy.deepcopy(raw)
        self._suppress = True
        try:
            self._render()
        finally:
            self._suppress = False

    def get_declaration(self) -> Any:
        """The current declaration exactly as it should be persisted (``None`` when the slot has none)."""

        return copy.deepcopy(self._declaration)

    def set_target(self, target: OpenPoseTarget | None) -> None:
        """Show whether the selected checkpoint/backend can run this (read-only; never edits the selection)."""

        self._target = target
        self._render_status()

    def set_content_visibility_mode(self, mode: str) -> None:
        self._content_visibility_mode = str(mode or "nsfw")
        self._apply_filter()
        self._render()

    def current_view(self) -> OpenPoseView:
        """What the operator is told about the current selection (a projection of what is already loaded)."""

        identities = self._listing.identities if self._listing_loaded and not self._listing.error else None
        selection = parse_declaration(self._declaration) if self._declaration_dict() is not None else None
        return describe_openpose(
            self._declaration,
            target=self._target,
            library_identities=identities,
            model_status=self._model_status(selection.model) if selection is not None else None,
        )

    def refresh_library(self) -> None:
        """Rescan the library and the installed ControlNet models on a worker (never on the Tk thread)."""

        self.summary_var.set("Scanning the OpenPose library…")

        def work() -> tuple[LibraryListing, list[ControlNetModelOption]]:
            registry = self._get_registry()
            listing = refresh_listing(registry)
            return listing, list_controlnet_models(controlnet_folder(registry))

        self._runner(work, self._on_scanned)

    # ------------------------------------------------------------------ worker plumbing

    def _get_registry(self) -> Any:
        if self._registry is None:
            if self._registry_factory is not None:
                self._registry = self._registry_factory()
            else:
                from src.assets import AssetRegistry

                self._registry = AssetRegistry()
        return self._registry

    def _threaded_runner(self, work: Callable[[], Any], done: Callable[[Any, Exception | None], None]) -> None:
        def target() -> None:
            try:
                result, error = work(), None
            except Exception as exc:  # noqa: BLE001 - reported to the operator, never raised on a worker
                result, error = None, exc
            try:
                self.after(0, lambda: done(result, error))
            except (RuntimeError, tk.TclError):
                logger.debug("OpenPose picker closed before its worker finished", exc_info=False)

        try:
            from src.utils.thread_registry import get_thread_registry

            get_thread_registry().spawn(
                target=target, name="OpenPose-Library", daemon=True, purpose="Scan OpenPose library"
            )
        except Exception:  # noqa: BLE001
            threading.Thread(target=target, daemon=True).start()

    def _alive(self) -> bool:
        if self._destroyed:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _on_scanned(self, result: Any, error: Exception | None) -> None:
        if not self._alive():
            return
        if error is not None or result is None:
            self._listing = LibraryListing(configured=True, error=str(error or "scan failed"))
            self._listing_loaded = True
        else:
            self._listing, self._models = result
            self._listing_loaded = True
        self._suppress = True
        try:
            self._render()
        finally:
            self._suppress = False

    # ------------------------------------------------------------------ rendering

    def _declaration_dict(self) -> dict[str, Any] | None:
        value = self._declaration
        return value if isinstance(value, dict) and not declaration_problems(value) else None

    def _is_hidden(self, identity: str) -> bool:
        if self._content_visibility_mode != "sfw":
            return False
        return not ContentVisibilityResolver(self._content_visibility_mode).is_visible({"name": identity})

    def _shown_name(self, identity: str) -> str:
        return REDACTED_TEXT if self._is_hidden(identity) else identity

    def _model_status(self, name: str) -> str | None:
        if not name:
            return None
        if not self._models:
            return None
        from src.assets.controlnet_structure import name_key

        key = name_key(name)
        for option in self._models:
            if name_key(option.name) == key:
                return option.evidence.status
        return MODEL_MISSING

    def _render(self) -> None:
        declaration = self._declaration_dict()
        invalid = self._declaration is not None and declaration is None
        selection = parse_declaration(declaration) if declaration is not None else None
        self.model_combo.configure(values=[option.name for option in self._models])
        self._apply_filter()
        state = "normal" if declaration is not None else "disabled"
        for widget in (self.weight_spin, self.start_spin, self.end_spin):
            widget.configure(state=state)
        for widget in (self.control_mode_combo, self.resize_mode_combo):
            widget.configure(state="readonly" if declaration is not None else "disabled")
        self.model_combo.configure(state="normal" if not invalid else "disabled")
        self.enable_check.configure(state="normal" if declaration is not None else "disabled")
        self.remove_button.configure(state="normal" if self._declaration is not None else "disabled")
        self.search_entry.configure(state="disabled" if invalid else "normal")
        if selection is not None:
            self.enable_var.set(selection.enabled)
            self.model_var.set(selection.model)
            self.weight_var.set(f"{selection.weight:g}")
            self.start_var.set(f"{selection.guidance_start:g}")
            self.end_var.set(f"{selection.guidance_end:g}")
            self.control_mode_var.set(selection.control_mode)
            self.resize_mode_var.set(selection.resize_mode)
            self.selected_var.set(self._shown_name(selection.asset))
            self._select_in_list(selection.asset)
            self._request_thumbnail(selection.asset)
        else:
            self.enable_var.set(False)
            self.selected_var.set("Invalid declaration (kept unchanged)" if invalid else "")
            self._show_thumbnail(None, "Invalid" if invalid else "No pose selected")
        self._render_status()

    def _render_status(self) -> None:
        view = self.current_view()
        if self._declaration is None:
            if not self._listing_loaded:
                self.summary_var.set("Scanning the OpenPose library…")
            elif self._listing.error:
                self.summary_var.set(f"The library scan failed: {self._listing.error}")
            elif not self._listing.configured:
                self.summary_var.set("Configure the Stable Diffusion WebUI root to use an OpenPose library.")
            elif not self._listing.folder_exists:
                self.summary_var.set("Create models/OpenPose under the WebUI root and add pose images.")
            elif not self._listing.entries:
                self.summary_var.set("The OpenPose library has no PNG/JPEG/WEBP images yet.")
            else:
                self.summary_var.set(f"{len(self._listing.entries)} pose image(s) available. Select one to use it.")
            self.notes_var.set("" if self._target is None else self._target.message)
            return
        if view.executable:
            self.summary_var.set("Ready: this slot will be conditioned on the selected pose.")
        elif view.worst == SEVERITY_ERROR:
            self.summary_var.set("Attention: this selection cannot run as saved.")
        elif view.worst == SEVERITY_WARNING:
            self.summary_var.set("Selection kept, but it will not run on the current target.")
        else:
            self.summary_var.set("OpenPose selection saved.")
        self.notes_var.set("\n".join(line.text for line in view.lines if line.severity != SEVERITY_OK) or "")
        if view.worst == SEVERITY_OK and not view.lines:
            self.notes_var.set("")

    def _apply_filter(self) -> None:
        entries = [entry for entry in self._listing.entries if not self._is_hidden(entry.identity)]
        self._visible = filter_entries(entries, self.search_var.get())
        self.listbox.delete(0, "end")
        for entry in self._visible:
            self.listbox.insert("end", entry.identity)

    def _select_in_list(self, identity: str) -> None:
        self.listbox.selection_clear(0, "end")
        for index, entry in enumerate(self._visible):
            if entry.identity == identity:
                self.listbox.selection_set(index)
                self.listbox.see(index)
                return

    # ------------------------------------------------------------------ thumbnail

    def _show_thumbnail(self, png: bytes | None, text: str = "") -> None:
        if png is None:
            self._photo = None
            self.thumbnail_label.configure(image="", text=text or "No preview")
            return
        try:
            self._photo = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        except tk.TclError:
            self._photo = None
            self.thumbnail_label.configure(image="", text="Preview unavailable")
            return
        self.thumbnail_label.configure(image=self._photo, text="")

    def _request_thumbnail(self, identity: str) -> None:
        if identity == self._pending_identity or (identity == self._shown_identity and self._photo is not None):
            return
        if self._is_hidden(identity):
            self._show_thumbnail(None, REDACTED_TEXT)
            return
        self._thumb_request += 1
        request = self._thumb_request
        self._pending_identity = identity
        self._show_thumbnail(None, "Loading preview…")
        registry = self._registry_factory_safe()
        root = library_root(getattr(registry, "webui_root", None)) if registry is not None else None

        def work() -> bytes:
            _path, image = read_library_image(root, identity)
            return thumbnail_png(image.data, _THUMB_EDGE)

        def done(result: Any, error: Exception | None) -> None:
            if not self._alive() or request != self._thumb_request:
                return  # a newer selection owns the preview
            self._pending_identity = ""
            if error is not None or result is None:
                reason = str(error) if isinstance(error, OpenPoseInputError) else "Preview unavailable"
                self._shown_identity = ""
                self._show_thumbnail(None, "Missing or unreadable image" if isinstance(error, OpenPoseInputError) else reason)
                return
            self._shown_identity = identity
            self._show_thumbnail(result)

        self._runner(work, done)

    def _registry_factory_safe(self) -> Any:
        try:
            return self._get_registry()
        except Exception:  # noqa: BLE001 - no configured root only disables previews
            return None

    # ------------------------------------------------------------------ edits

    def _notify(self) -> None:
        if self._suppress:
            return
        callback = self.on_change_callback
        if callback is not None:
            callback()

    def _commit(self, **changes: Any) -> None:
        current = self._declaration_dict()
        if self._declaration is not None and current is None:
            return  # an invalid saved declaration is only ever removed, never half-edited
        updated = declaration_from_view(current, **changes)
        problems = declaration_problems(updated)
        if problems:
            self.notes_var.set("That change was not applied: " + "; ".join(problems))
            return
        self._declaration = updated
        self._suppress = True
        try:
            self._render()
        finally:
            self._suppress = False
        self._notify()

    def _on_list_select(self, _event: object | None = None) -> None:
        if self._suppress:
            return
        selection = self.listbox.curselection()
        if not selection or selection[0] >= len(self._visible):
            return
        identity = self._visible[selection[0]].identity
        current = self._declaration_dict()
        if current is None:
            if self._declaration is not None:
                return  # invalid saved value: Remove first
            model = self.model_var.get().strip()
            if not model:
                verified = [o.name for o in self._models if o.evidence.status == STATUS_SDXL]
                model = verified[0] if len(verified) == 1 else ""
            try:
                self._declaration = new_declaration(identity, model=model)
            except ValueError as exc:
                self.notes_var.set(f"This image cannot be used: {exc}")
                return
            self._suppress = True
            try:
                self._render()
            finally:
                self._suppress = False
            self._notify()
            return
        self._commit(asset=identity)

    def _on_enable_toggled(self) -> None:
        if self._declaration_dict() is None:
            self.enable_var.set(False)
            return
        self._commit(enabled=bool(self.enable_var.get()))

    def _on_model_changed(self) -> None:
        current = self._declaration_dict()
        if current is None:
            return
        value = self.model_var.get().strip()
        if value != str(current.get("model") or ""):
            self._commit(model=value)

    def _on_choice_changed(self) -> None:
        if self._declaration_dict() is None:
            return
        self._commit(
            control_mode=self.control_mode_var.get(), resize_mode=self.resize_mode_var.get()
        )

    def _on_number_changed(self) -> None:
        current = self._declaration_dict()
        if current is None:
            return
        try:
            weight = round(float(self.weight_var.get()), 3)
            start = round(float(self.start_var.get()), 3)
            end = round(float(self.end_var.get()), 3)
        except (TypeError, ValueError):
            self._render()  # revert unparseable text to the saved values
            return
        if not (MIN_WEIGHT <= weight <= MAX_WEIGHT and 0.0 <= start < end <= 1.0):
            self.notes_var.set(
                f"Strength must be {MIN_WEIGHT:g}-{MAX_WEIGHT:g} and guidance start must be below guidance end (0-1)."
            )
            self.weight_var.set(f"{float(current.get('weight', DEFAULT_WEIGHT)):g}")
            self.start_var.set(f"{float(current.get('guidance_start', DEFAULT_GUIDANCE_START)):g}")
            self.end_var.set(f"{float(current.get('guidance_end', DEFAULT_GUIDANCE_END)):g}")
            return
        if (weight, start, end) == (
            float(current.get("weight", DEFAULT_WEIGHT)),
            float(current.get("guidance_start", DEFAULT_GUIDANCE_START)),
            float(current.get("guidance_end", DEFAULT_GUIDANCE_END)),
        ):
            return
        self._commit(weight=weight, guidance_start=start, guidance_end=end)

    def _on_remove(self) -> None:
        if self._declaration is None:
            return
        self._declaration = None
        self._thumb_request += 1
        self._shown_identity = ""
        self._pending_identity = ""
        self._suppress = True
        try:
            self._render()
        finally:
            self._suppress = False
        self._notify()

    def destroy(self) -> None:
        self._destroyed = True
        super().destroy()


__all__ = ["OpenPosePickerPanel"]

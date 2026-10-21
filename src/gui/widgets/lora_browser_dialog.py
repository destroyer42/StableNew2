"""Paged local LoRA browser. Tk owns widgets/images; tracked workers own decoding."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from PIL import Image, ImageTk

from src.assets.lora_preview import read_thumbnail
from src.gui_v2.lora_browser import PAGE_SIZE, browser_page, project_adapter, target_profile
from src.image_backends.forge_klein_lora import (
    KleinLoraDecision,
    classify_klein_lora,
    unavailable_decision,
)
from src.image_backends.model_policy_lora import assess_lora_selection
from src.utils.lora_scanner import LoRAResource
from src.utils.thread_registry import get_thread_registry

if TYPE_CHECKING:
    from src.gui.widgets.lora_picker_panel import LoRAPickerPanel

THUMBNAIL_CACHE_LIMIT = PAGE_SIZE


class LoRABrowserDialog(tk.Toplevel):
    def __init__(self, picker: LoRAPickerPanel) -> None:
        super().__init__(picker)
        self.picker = picker
        self.closed = False
        self._page = 0
        self._generation = 0
        self._thumb_active = False
        self._thumb_cancel = threading.Event()
        self._pending_thumbnails: tuple[int, tuple[LoRAResource, ...]] | None = None
        self._images: dict[str, ImageTk.PhotoImage] = {}
        self._preview_labels: dict[str, ttk.Label] = {}
        self.title("Local LoRA Browser")
        self.geometry("1100x850")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.query = tk.StringVar()
        search = ttk.Frame(self, padding=8)
        search.grid(row=0, column=0, sticky="ew")
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="Search name").grid(row=0, column=0)
        ttk.Entry(search, textvariable=self.query).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(search, text="Refresh", command=picker.refresh_loras).grid(row=0, column=2)
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, wraplength=1000).grid(
            row=1, column=0, sticky="w", padx=8
        )
        self.policy_status = tk.StringVar()
        ttk.Label(self, textvariable=self.policy_status, wraplength=1000).grid(
            row=2, column=0, sticky="w", padx=8
        )
        self.cards = ttk.Frame(self, padding=8)
        self.cards.grid(row=3, column=0, sticky="nsew")
        self.cards.columnconfigure((0, 1), weight=1)
        navigation = ttk.Frame(self, padding=8)
        navigation.grid(row=4, column=0, sticky="ew")
        ttk.Button(navigation, text="Previous", command=lambda: self._move(-1)).pack(side="left")
        self.page_text = tk.StringVar()
        ttk.Label(navigation, textvariable=self.page_text).pack(side="left", padx=10)
        ttk.Button(navigation, text="Next", command=lambda: self._move(1)).pack(side="left")
        ttk.Button(navigation, text="Close", command=self.destroy).pack(side="right")
        self.query.trace_add("write", lambda *_: self._search())
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.render()

    def _search(self) -> None:
        self._page = 0
        self.render()

    def _move(self, direction: int) -> None:
        self._page += direction
        self.render()

    def render(self) -> None:
        if self.closed:
            return
        self._generation += 1
        self._thumb_cancel.set()
        for widget in self.cards.winfo_children():
            widget.destroy()
        self._images.clear()
        self._preview_labels.clear()
        picker = self.picker
        page, self._page, pages = browser_page(
            picker._resources,
            picker._content_visibility_mode,
            self.query.get(),
            self._page,
        )
        self.status.set(picker.discovery_status.get())
        self.page_text.set(f"Page {self._page + 1} of {pages}")
        selected = dict(picker.get_loras())
        target = target_profile(picker._asset_snapshot, picker._model_name)
        policy_note = "Select a target checkpoint to assess compatibility. No pairing is physically qualified here."
        if picker._policy is not None:

            def resolve(name: str) -> KleinLoraDecision:
                resource = picker._resources.get(name)
                return (
                    classify_klein_lora(name, resource.record)
                    if resource and resource.record
                    else unavailable_decision(name, "unavailable")
                )

            assessment = assess_lora_selection(picker._policy, list(selected.items()), resolve)
            limit = f"; policy limit {assessment.limit}" if assessment.limit is not None else ""
            policy_note = f"{len(selected)} selected{limit}. Preview/compile and backend admission remain required."
            if assessment.blocked:
                # Assessment details can name hidden assets. Counts and a generic warning are sufficient here.
                policy_note += " Current selection has unresolved target-policy requirements."
        self.policy_status.set(policy_note)
        for index, resource in enumerate(page):
            card = ttk.Frame(self.cards, padding=5, relief="groove", borderwidth=1)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=3, pady=3)
            card.columnconfigure(1, weight=1)
            preview = ttk.Label(
                card,
                text="Loading local preview…" if resource.preview_path else "Preview unavailable",
                width=20,
            )
            preview.grid(row=0, column=0, rowspan=5, sticky="n")
            self._preview_labels[resource.name] = preview
            projected = project_adapter(resource, picker._policy, target)
            ttk.Label(card, text=resource.name, wraplength=330).grid(row=0, column=1, sticky="w")
            ttk.Label(
                card,
                text=f"{projected.family} ({projected.source})\n{projected.compatibility}",
                wraplength=330,
            ).grid(row=1, column=1, sticky="w")
            keywords = ", ".join(resource.keywords)[:500] or "Unavailable / no trigger evidence"
            ttk.Label(card, text=f"Keywords [{resource.source}]: {keywords}", wraplength=330).grid(
                row=2, column=1, sticky="w"
            )
            if resource.errors:
                ttk.Label(
                    card,
                    text="Local metadata unavailable; compatibility unverified",
                    wraplength=330,
                ).grid(row=3, column=1, sticky="w")
            controls = ttk.Frame(card)
            controls.grid(row=4, column=1, sticky="w")
            enabled = tk.BooleanVar(value=resource.name in selected)
            strength = tk.StringVar(value=str(selected.get(resource.name, 0.8)))

            def apply(
                name: str = resource.name,
                enabled: tk.BooleanVar = enabled,
                strength: tk.StringVar = strength,
            ) -> None:
                if not enabled.get():
                    picker.choose_from_browser(name, 0.0, False)
                    return
                try:
                    value = float(strength.get())
                    if not 0 <= value <= picker.SLIDER_MAX:
                        raise ValueError("invalid strength")
                except ValueError:
                    self.status.set(f"Enter a strength from 0 to {picker.SLIDER_MAX}.")
                    return
                picker.choose_from_browser(name, value, enabled.get())

            ttk.Checkbutton(controls, text="Selected", variable=enabled, command=apply).pack(
                side="left"
            )
            ttk.Entry(controls, textvariable=strength, width=6).pack(side="left", padx=5)
            ttk.Button(controls, text="Apply strength", command=apply).pack(side="left")
        if not page:
            ttk.Label(
                self.cards,
                text="No visible matches. Saved selections remain in the PromptPack controls.",
            ).grid(row=0, column=0)
        self._pending_thumbnails = (self._generation, tuple(page))
        if not self._thumb_active:
            self._start_thumbnails()

    def _start_thumbnails(self) -> None:
        if self.closed or self._pending_thumbnails is None:
            return
        generation, resources = self._pending_thumbnails
        self._pending_thumbnails = None
        self._thumb_active = True
        cancel = self._thumb_cancel = threading.Event()
        invoker = self.picker._invoker

        def work() -> None:
            images: dict[str, Image.Image | None] = {}
            try:
                for resource in resources:
                    if cancel.is_set():
                        break
                    root = resource.path.parent
                    images[resource.name] = read_thumbnail(resource.preview_path, root)
            finally:
                invoker.invoke(lambda: self._finish_thumbnails(generation, images))

        try:
            get_thread_registry().spawn(
                target=work,
                name="LoRA-Thumbnails",
                daemon=False,
                purpose="Decode visible local previews",
            )
        except (RuntimeError, OSError):
            self._finish_thumbnails(generation, {})

    def _finish_thumbnails(self, generation: int, images: dict[str, Image.Image | None]) -> None:
        if self.closed:
            return
        self._thumb_active = False
        if generation == self._generation:
            for name, image in images.items():
                label = self._preview_labels.get(name)
                if label is None:
                    continue
                if image is None:
                    label.configure(text="Preview unavailable")
                elif len(self._images) < THUMBNAIL_CACHE_LIMIT:
                    photo = ImageTk.PhotoImage(image, master=self)
                    self._images[name] = photo
                    label.configure(image=photo, text="")
        self._start_thumbnails()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            self.closed = True
            self._thumb_cancel.set()
            self._pending_thumbnails = None
            self._images.clear()

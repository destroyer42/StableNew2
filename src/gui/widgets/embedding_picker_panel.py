"""Embedding picker panel with per-embedding weight controls."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from src.utils.embedding_prompt_utils import normalize_embedding_entries
from src.utils.embedding_scanner import get_embedding_scanner


class EmbeddingPickerPanel(ttk.Frame):
    """Panel for managing positive and negative embeddings with weights."""

    def __init__(
        self,
        parent: tk.Misc,
        on_change_callback: Callable[[], None] | None = None,
        webui_root: str | None = None,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self.on_change_callback = on_change_callback
        self._positive_entries: list[tuple[str, tk.DoubleVar, ttk.Frame]] = []
        self._negative_entries: list[tuple[str, tk.DoubleVar, ttk.Frame]] = []

        self.scanner = get_embedding_scanner(webui_root)
        self._available_embeddings: list[str] = []

        self._build_ui()
        self.after(100, self._scan_embeddings)

    def _build_ui(self) -> None:
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", padx=5, pady=(5, 2))

        ttk.Label(header_frame, text="Embeddings", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(
            header_frame,
            text="↻ Refresh",
            width=10,
            command=self.refresh_embeddings,
        ).pack(side="right")

        self._build_section(
            title="Positive",
            add_callback=self._on_add_positive,
            assign=lambda combo: setattr(self, "pos_entry", combo),
            list_assign=lambda frame: setattr(self, "pos_list_frame", frame),
        )
        self._build_section(
            title="Negative",
            add_callback=self._on_add_negative,
            assign=lambda combo: setattr(self, "neg_entry", combo),
            list_assign=lambda frame: setattr(self, "neg_list_frame", frame),
        )

    def _build_section(
        self,
        *,
        title: str,
        add_callback: Callable[[], None],
        assign: Callable[[ttk.Combobox], None],
        list_assign: Callable[[ttk.Frame], None],
    ) -> None:
        section = ttk.LabelFrame(self, text=title, padding=5)
        section.pack(fill="both", expand=True, padx=5, pady=5)

        add_frame = ttk.Frame(section)
        add_frame.pack(fill="x", pady=(0, 5))

        combo = ttk.Combobox(add_frame, width=23, state="readonly")
        combo.pack(side="left", fill="x", expand=True, padx=(0, 5))
        combo.bind("<Return>", lambda e: add_callback())
        assign(combo)

        ttk.Button(add_frame, text="Add", command=add_callback).pack(side="left")

        list_frame = ttk.Frame(section, relief="sunken", borderwidth=1)
        list_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_frame, height=110, bg="#2b2b2b", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        list_assign(inner)

    def _notify_change(self) -> None:
        if self.on_change_callback:
            self.on_change_callback()

    def _add_entry(
        self,
        *,
        container: ttk.Frame,
        target_entries: list[tuple[str, tk.DoubleVar, ttk.Frame]],
        name: str,
        weight: float,
    ) -> None:
        for existing_name, _, _ in target_entries:
            if existing_name == name:
                return

        entry_frame = ttk.Frame(container, relief="solid", borderwidth=1)
        entry_frame.pack(fill="x", padx=2, pady=2)

        ttk.Label(entry_frame, text=name, font=("Segoe UI", 9)).pack(side="left", padx=5)
        weight_var = tk.DoubleVar(value=weight)
        weight_label = ttk.Label(entry_frame, text=f"{weight:.2f}", width=5)
        weight_label.pack(side="right", padx=(0, 5))

        def on_delete() -> None:
            self._remove_entry(target_entries, name)

        ttk.Button(entry_frame, text="X", width=3, command=on_delete).pack(side="right", padx=2)

        def on_weight_change(value: str) -> None:
            weight_label.config(text=f"{float(value):.2f}")
            self._notify_change()

        ttk.Scale(
            entry_frame,
            from_=0.0,
            to=1.5,
            variable=weight_var,
            orient="horizontal",
            command=on_weight_change,
        ).pack(side="right", fill="x", expand=True, padx=5)

        target_entries.append((name, weight_var, entry_frame))

    def _remove_entry(
        self,
        target_entries: list[tuple[str, tk.DoubleVar, ttk.Frame]],
        name: str,
    ) -> None:
        for index, (entry_name, _, frame) in enumerate(target_entries):
            if entry_name == name:
                frame.destroy()
                target_entries.pop(index)
                self._notify_change()
                return

    def _on_add_positive(self) -> None:
        name = self.pos_entry.get().strip()
        if not name:
            return
        self._add_entry(
            container=self.pos_list_frame,
            target_entries=self._positive_entries,
            name=name,
            weight=1.0,
        )
        self.pos_entry.set("")
        self._notify_change()

    def _on_add_negative(self) -> None:
        name = self.neg_entry.get().strip()
        if not name:
            return
        self._add_entry(
            container=self.neg_list_frame,
            target_entries=self._negative_entries,
            name=name,
            weight=1.0,
        )
        self.neg_entry.set("")
        self._notify_change()

    def get_positive_embeddings(self) -> list[tuple[str, float]]:
        return [(name, var.get()) for name, var, _ in self._positive_entries]

    def get_negative_embeddings(self) -> list[tuple[str, float]]:
        return [(name, var.get()) for name, var, _ in self._negative_entries]

    def set_positive_embeddings(self, embeddings) -> None:
        for _, _, frame in self._positive_entries:
            frame.destroy()
        self._positive_entries.clear()
        for name, weight in normalize_embedding_entries(embeddings):
            self._add_entry(
                container=self.pos_list_frame,
                target_entries=self._positive_entries,
                name=name,
                weight=weight,
            )

    def set_negative_embeddings(self, embeddings) -> None:
        for _, _, frame in self._negative_entries:
            frame.destroy()
        self._negative_entries.clear()
        for name, weight in normalize_embedding_entries(embeddings):
            self._add_entry(
                container=self.neg_list_frame,
                target_entries=self._negative_entries,
                name=name,
                weight=weight,
            )

    def clear(self) -> None:
        self.set_positive_embeddings([])
        self.set_negative_embeddings([])
        self._notify_change()

    def _scan_embeddings(self) -> None:
        try:
            self.scanner.scan_embeddings()
            self._available_embeddings = self.scanner.get_embedding_names()
            values = sorted(self._available_embeddings)
            self.pos_entry["values"] = values
            self.neg_entry["values"] = values
        except Exception:
            pass

    def refresh_embeddings(self) -> None:
        try:
            self.scanner.scan_embeddings(force_rescan=True)
            self._available_embeddings = self.scanner.get_embedding_names()
            values = sorted(self._available_embeddings)
            self.pos_entry["values"] = values
            self.neg_entry["values"] = values
        except Exception:
            pass

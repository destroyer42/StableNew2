"""Prompt pack browser for GUI V2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable

from . import theme as theme_mod
from .prompt_pack_adapter_v2 import PromptPackSummary


class PromptPackPanelV2(ttk.Frame):
    """Display prompt packs with lightweight metadata and an apply action."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        packs: Iterable[PromptPackSummary] | None = None,
        on_apply: Callable[[PromptPackSummary], None] | None = None,
        theme=None,
        pack_list_names: list[str] | None = None,
        on_pack_list_change: Callable[[str], None] | None = None,
        **kwargs,
    ) -> None:
        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self._on_apply = on_apply
        self._packs: list[PromptPackSummary] = list(packs or [])
        self._pack_list_names = pack_list_names or []
        self._on_pack_list_change = on_pack_list_change
        self._build_ui(theme)
        self.set_packs(self._packs)

    def _build_ui(self, theme) -> None:
        header_style = getattr(theme, "STATUS_STRONG_LABEL_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
        ttk.Label(self, text="Prompt Packs", style=header_style).pack(anchor=tk.W, pady=(0, 4))

        # Pack list selector (if multiple lists)
        if self._pack_list_names:
            self.pack_list_var = tk.StringVar(value=self._pack_list_names[0])
            self.pack_list_combo = ttk.Combobox(self, values=self._pack_list_names, textvariable=self.pack_list_var, state="readonly")
            self.pack_list_combo.pack(fill=tk.X, pady=(0, 4))
            self.pack_list_combo.bind("<<ComboboxSelected>>", self._on_pack_list_changed)

        list_frame = ttk.Frame(self, style=getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE))
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox = tk.Listbox(
            list_frame,
            height=8,
            relief="flat",
            borderwidth=0,
            background=getattr(theme, "COLOR_SURFACE_ALT", theme_mod.COLOR_SURFACE_ALT),
            foreground=getattr(theme, "COLOR_TEXT", theme_mod.COLOR_TEXT),
            highlightthickness=1,
            highlightcolor=getattr(theme, "COLOR_BORDER_SUBTLE", theme_mod.COLOR_BORDER_SUBTLE),
            highlightbackground=getattr(theme, "COLOR_BORDER_SUBTLE", theme_mod.COLOR_BORDER_SUBTLE),
            selectbackground=getattr(theme, "COLOR_ACCENT", theme_mod.COLOR_ACCENT),
            selectforeground=getattr(theme, "ASWF_BLACK", theme_mod.ASWF_BLACK),
            activestyle="none",
            yscrollcommand=scrollbar.set,
        )
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_selection_changed)
        scrollbar.configure(command=self.listbox.yview)

        meta_frame = ttk.Frame(self, style=getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE))
        meta_frame.pack(fill=tk.X, pady=(theme_mod.PADDING_SM, 0))
        self.description_var = tk.StringVar(value="Select a pack to preview its prompt")
        self.meta_label = ttk.Label(meta_frame, textvariable=self.description_var, wraplength=260)
        self.meta_label.pack(anchor=tk.W)

        self.apply_button = ttk.Button(self, text="Apply to Prompt", command=self._on_apply_clicked)
        self.apply_button.pack(anchor=tk.E, pady=(theme_mod.PADDING_SM, 0))
        self.apply_button_state(False)

    def _on_pack_list_changed(self, event=None):
        if self._on_pack_list_change:
            self._on_pack_list_change(self.pack_list_var.get())

    def set_packs(self, packs: Iterable[PromptPackSummary]) -> None:
        self._packs = list(packs or [])
        self.listbox.delete(0, tk.END)
        for pack in self._packs:
            self.listbox.insert(tk.END, pack.name)
        self._update_metadata()

    def get_selected_summary(self) -> PromptPackSummary | None:
        selection = self.listbox.curselection()
        if not selection:
            return None
        idx = selection[0]
        if idx < 0 or idx >= len(self._packs):
            return None
        return self._packs[idx]

    def apply_button_state(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        try:
            self.apply_button.configure(state=state)
        except Exception:
            pass

    def _on_selection_changed(self, _event=None) -> None:
        has_selection = bool(self.listbox.curselection())
        self.apply_button_state(has_selection)
        self._update_metadata()

    def _update_metadata(self) -> None:
        summary = self.get_selected_summary()
        if not summary:
            self.description_var.set("Select a pack to preview its prompt")
            return

        parts = []
        if summary.description:
            parts.append(summary.description)
        if summary.prompt_count:
            parts.append(f"{summary.prompt_count} prompt(s)")
        self.description_var.set(" | ".join(parts) if parts else summary.name)

    def _on_apply_clicked(self) -> None:
        summary = self.get_selected_summary()
        if summary and self._on_apply:
            try:
                self._on_apply(summary)
            except Exception:
                pass


__all__ = ["PromptPackPanelV2"]

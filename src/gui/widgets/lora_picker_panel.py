"""Simple LoRA picker panel for managing LoRAs with strength controls.

v2.6 Changes:
- Replaced autocomplete text entry with dropdown combobox for simpler selection
- User selects from available LoRAs and clicks Add button
- Removed 70+ lines of autocomplete complexity

This widget provides a basic interface for adding/removing LoRAs and adjusting
their strengths. Keyword detection will be added in Phase A.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import Any, cast

from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.gui.enhanced_slider import EnhancedSlider
from src.gui.tooltip import attach_tooltip
from src.gui.widgets.lora_keyword_dialog import LoRAKeywordDialog
from src.utils.lora_keyword_detector import detect_lora_keywords
from src.utils.lora_scanner import get_lora_scanner


class LoRAPickerPanel(ttk.Frame):
    """Panel for managing LoRAs with add/remove/strength controls."""

    NAME_WRAP_LENGTH = 280
    COMBO_MIN_WIDTH = 180
    CONTROL_ROW_MIN_WIDTH = 220
    SLIDER_MAX = 1.5
    SLIDER_RESOLUTION = 0.01
    
    def __init__(
        self,
        parent: tk.Misc,
        on_change_callback: Callable[[], None] | None = None,
        webui_root: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(parent, **kwargs)
        self.on_change_callback = on_change_callback
        self.webui_root = webui_root
        self._lora_entries: list[tuple[str, tk.DoubleVar, ttk.Frame]] = []  # (name, strength_var, frame)
        self._entry_widgets: dict[str, dict[str, object]] = {}
        # Initialize scanner
        self.scanner = get_lora_scanner(webui_root)
        self._content_visibility_mode = self._discover_content_visibility_mode()
        self._available_loras: list[str] = []
        self._visible_loras: list[str] = []
        
        self._build_ui()
        
        # Scan LoRAs in background
        self.after(100, self._scan_loras)
    
    def _build_ui(self) -> None:
        """Build the LoRA picker UI."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header
        header_frame = ttk.Frame(self)
        header_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 2))
        header_frame.columnconfigure(0, weight=1)
        
        ttk.Label(header_frame, text="LoRAs", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self._visibility_status_var = tk.StringVar(value="")
        ttk.Label(
            header_frame,
            textvariable=self._visibility_status_var,
            foreground="#7aa2d6",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        
        ttk.Button(
            header_frame,
            text="↻ Refresh",
            command=self.refresh_loras,
            width=10
        ).grid(row=0, column=1, sticky="e")
        
        # Add button frame
        add_frame = ttk.Frame(self)
        add_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        add_frame.columnconfigure(0, weight=1, minsize=self.COMBO_MIN_WIDTH)
        
        self.lora_name_var = tk.StringVar()
        self.lora_name_combo = ttk.Combobox(
            add_frame,
            textvariable=self.lora_name_var,
            width=28,
            state="readonly"
        )
        self.lora_name_combo.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.lora_name_combo.bind("<Return>", lambda e: self._on_add_lora())
        
        ttk.Button(add_frame, text="Add LoRA", command=self._on_add_lora).grid(
            row=0, column=1, sticky="e"
        )
        
        # Scrollable list of LoRAs
        list_frame = ttk.Frame(self, relief="sunken", borderwidth=1)
        list_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        
        canvas = tk.Canvas(list_frame, height=150, bg="#2b2b2b", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        
        self.lora_list_frame = ttk.Frame(canvas)
        self.lora_list_frame.columnconfigure(0, weight=1)
        self.lora_list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.lora_list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self._canvas = canvas
        
        # Enable mousewheel scrolling
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

    def _discover_content_visibility_mode(self) -> str:
        widget = getattr(self, "master", None)
        while widget is not None:
            app_state = getattr(widget, "app_state", None)
            mode = getattr(app_state, "content_visibility_mode", None)
            if isinstance(mode, str) and mode.strip():
                return mode
            widget = getattr(widget, "master", None)
        return "nsfw"

    def set_content_visibility_mode(self, mode: str) -> None:
        self._content_visibility_mode = str(mode or "nsfw")
        self._refresh_visible_lora_names()

    def _refresh_visible_lora_names(self) -> None:
        resolver = ContentVisibilityResolver(self._content_visibility_mode)
        visible: list[str] = []
        hidden_count = 0
        for name in self._available_loras:
            resource = self.scanner.get_lora_info(name)
            subject = {
                "name": name,
                "keywords": list(getattr(resource, "keywords", []) or []),
                "description": str(getattr(resource, "description", "") or ""),
            }
            if resolver.is_visible(subject):
                visible.append(name)
            else:
                hidden_count += 1
        self._visible_loras = sorted(visible)
        self.lora_name_combo["values"] = self._visible_loras
        if self._content_visibility_mode == "sfw" and hidden_count:
            self._visibility_status_var.set(f"SFW mode active: {hidden_count} LoRA(s) hidden.")
        else:
            self._visibility_status_var.set("")
    

    def _on_add_lora(self) -> None:
        """Add a new LoRA to the list."""
        name = self.lora_name_var.get().strip()
        if not name:
            return
        if self._visible_loras and name not in self._visible_loras:
            return
        
        # Check for duplicates
        for existing_name, _, _ in self._lora_entries:
            if existing_name == name:
                return
        
        # Create LoRA entry
        self._add_lora_entry(name, 0.8)
        
        # Clear combobox
        self.lora_name_var.set("")
        
        # Notify change
        if self.on_change_callback:
            self.on_change_callback()
    
    def _add_lora_entry(self, name: str, strength: float) -> None:
        """Add a LoRA entry widget to the list."""
        resolver = ContentVisibilityResolver(self._content_visibility_mode)
        resource = self.scanner.get_lora_info(name)
        subject = {
            "name": name,
            "keywords": list(getattr(resource, "keywords", []) or []),
            "description": str(getattr(resource, "description", "") or ""),
        }
        hidden = self._content_visibility_mode == "sfw" and not resolver.is_visible(subject)
        display_name = REDACTED_TEXT if hidden else name
        entry_frame = ttk.Frame(self.lora_list_frame, relief="solid", borderwidth=1, padding=(6, 4))
        entry_frame.pack(fill="x", padx=2, pady=2)
        entry_frame.columnconfigure(0, weight=1)

        name_row = ttk.Frame(entry_frame)
        name_row.grid(row=0, column=0, sticky="ew")
        name_row.columnconfigure(0, weight=1)
        controls_row = ttk.Frame(entry_frame)
        controls_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        controls_row.columnconfigure(0, weight=1, minsize=self.CONTROL_ROW_MIN_WIDTH)

        name_label = ttk.Label(
            name_row,
            text=display_name,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=self.NAME_WRAP_LENGTH,
        )
        name_label.grid(row=0, column=0, sticky="ew")
        attach_tooltip(name_label, display_name)

        strength_var = tk.DoubleVar(value=strength)
        
        def on_delete() -> None:
            self._remove_lora_entry(name)

        remove_button = ttk.Button(controls_row, text="X", width=3, command=on_delete)
        remove_button.grid(row=0, column=2, sticky="e", padx=(4, 0))

        def on_keywords() -> None:
            self._show_keywords(name)

        keywords_button = ttk.Button(controls_row, text="Keywords", command=on_keywords)
        keywords_button.grid(row=0, column=1, sticky="e", padx=(4, 0))
        if hidden:
            keywords_button.state(["disabled"])

        def on_strength_change(value: float | str) -> None:
            try:
                normalized = round(float(value), 2)
            except (TypeError, ValueError):
                normalized = round(strength_var.get(), 2)
            strength_var.set(normalized)
            if self.on_change_callback:
                self.on_change_callback()

        slider = cast(Any, EnhancedSlider)(
            controls_row,
            from_=0.0,
            to=self.SLIDER_MAX,
            variable=strength_var,
            resolution=self.SLIDER_RESOLUTION,
            command=on_strength_change,
            length=180,
        )
        slider.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self._lora_entries.append((name, strength_var, entry_frame))
        self._entry_widgets[name] = {
            "frame": entry_frame,
            "name_row": name_row,
            "controls_row": controls_row,
            "name_label": name_label,
            "strength_var": strength_var,
            "strength_slider": slider,
            "keywords_button": keywords_button,
            "remove_button": remove_button,
        }
    
    def _remove_lora_entry(self, name: str) -> None:
        """Remove a LoRA entry from the list."""
        for i, (lora_name, _, frame) in enumerate(self._lora_entries):
            if lora_name == name:
                frame.destroy()
                self._lora_entries.pop(i)
                self._entry_widgets.pop(name, None)
                if self.on_change_callback:
                    self.on_change_callback()
                break
    
    def get_loras(self) -> list[tuple[str, float]]:
        """Return list of (name, strength) tuples."""
        return [(name, var.get()) for name, var, _ in self._lora_entries]
    
    def set_loras(self, loras: list[tuple[str, float]]) -> None:
        """Load LoRAs into UI."""
        # Clear existing
        for _, _, frame in self._lora_entries:
            frame.destroy()
        self._lora_entries.clear()
        self._entry_widgets.clear()
        
        # Add new
        for name, strength in loras:
            self._add_lora_entry(name, strength)
    
    def clear(self) -> None:
        """Clear all LoRAs."""
        for _, _, frame in self._lora_entries:
            frame.destroy()
        self._lora_entries.clear()
        self._entry_widgets.clear()
        
        if self.on_change_callback:
            self.on_change_callback()
    
    def _show_keywords(self, lora_name: str) -> None:
        """Show keyword detection dialog for a LoRA."""
        # Check cache first
        cached_resource = self.scanner.get_lora_info(lora_name)
        
        if cached_resource and cached_resource.keywords:
            # Use cached data
            from src.utils.lora_keyword_detector import LoRAMetadata
            metadata = LoRAMetadata(
                name=lora_name,
                path=cached_resource.path,
                keywords=cached_resource.keywords,
                source=cached_resource.source,
                description=cached_resource.description
            )
        else:
            # Detect keywords on-demand
            webui_path = Path(self.webui_root) if self.webui_root else None
            metadata = detect_lora_keywords(lora_name, webui_root=webui_path)
        
        # Show dialog
        dialog = LoRAKeywordDialog(
            self,
            metadata=metadata,
            on_copy=lambda keywords: self._insert_keywords_to_prompt(keywords)
        )
        dialog.grab_set()
    
    def _insert_keywords_to_prompt(self, keywords: str) -> None:
        """Callback to insert keywords into prompt editor.
        
        This is a placeholder - will be overridden by parent frame.
        """
        # Just copy to clipboard for now
        self.clipboard_clear()
        self.clipboard_append(keywords)
    
    def _scan_loras(self) -> None:
        """Scan for available LoRAs in background."""
        try:
            self.scanner.scan_loras()
            self._available_loras = self.scanner.get_lora_names()
            self._refresh_visible_lora_names()
        except Exception:
            pass
    
    def refresh_loras(self) -> None:
        """Force rescan of LoRA directory."""
        try:
            self.scanner.scan_loras(force_rescan=True)
            self._available_loras = self.scanner.get_lora_names()
            self._refresh_visible_lora_names()
        except Exception:
            pass
    


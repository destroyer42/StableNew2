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

from src.gui.widgets.lora_keyword_dialog import LoRAKeywordDialog
from src.utils.lora_keyword_detector import detect_lora_keywords
from src.utils.lora_scanner import get_lora_scanner


class LoRAPickerPanel(ttk.Frame):
    """Panel for managing LoRAs with add/remove/strength controls."""
    
    def __init__(
        self,
        parent: tk.Misc,
        on_change_callback: Callable[[], None] | None = None,
        webui_root: str | None = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.on_change_callback = on_change_callback
        self.webui_root = webui_root
        self._lora_entries: list[tuple[str, tk.DoubleVar, ttk.Frame]] = []  # (name, strength_var, frame)
        
        # Initialize scanner
        self.scanner = get_lora_scanner(webui_root)
        self._available_loras: list[str] = []
        
        self._build_ui()
        
        # Scan LoRAs in background
        self.after(100, self._scan_loras)
    
    def _build_ui(self) -> None:
        """Build the LoRA picker UI."""
        # Header
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", padx=5, pady=(5, 2))
        
        ttk.Label(header_frame, text="LoRAs", font=("Segoe UI", 10, "bold")).pack(side="left")
        
        ttk.Button(
            header_frame,
            text="↻ Refresh",
            command=self.refresh_loras,
            width=10
        ).pack(side="right")
        
        # Add button frame
        add_frame = ttk.Frame(self)
        add_frame.pack(fill="x", padx=5, pady=5)
        
        self.lora_name_var = tk.StringVar()
        self.lora_name_combo = ttk.Combobox(
            add_frame,
            textvariable=self.lora_name_var,
            width=28,
            state="readonly"
        )
        self.lora_name_combo.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.lora_name_combo.bind("<Return>", lambda e: self._on_add_lora())
        
        ttk.Button(add_frame, text="Add LoRA", command=self._on_add_lora).pack(side="left")
        
        # Scrollable list of LoRAs
        list_frame = ttk.Frame(self, relief="sunken", borderwidth=1)
        list_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        canvas = tk.Canvas(list_frame, height=150, bg="#2b2b2b", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        
        self.lora_list_frame = ttk.Frame(canvas)
        self.lora_list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.lora_list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Enable mousewheel scrolling
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
    

    def _on_add_lora(self) -> None:
        """Add a new LoRA to the list."""
        name = self.lora_name_var.get().strip()
        if not name:
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
        entry_frame = ttk.Frame(self.lora_list_frame, relief="solid", borderwidth=1)
        entry_frame.pack(fill="x", padx=2, pady=2)
        
        # Name label
        name_label = ttk.Label(entry_frame, text=name, font=("Segoe UI", 9))
        name_label.pack(side="left", padx=5)
        
        # Strength label
        strength_var = tk.DoubleVar(value=strength)
        strength_label = ttk.Label(entry_frame, text=f"{strength:.2f}", width=5)
        strength_label.pack(side="right", padx=(0, 5))
        
        # Delete button
        def on_delete():
            self._remove_lora_entry(name)
        ttk.Button(entry_frame, text="X", width=3, command=on_delete).pack(side="right", padx=2)
        
        # Keywords button
        def on_keywords():
            self._show_keywords(name)
        ttk.Button(entry_frame, text="Keywords", command=on_keywords).pack(side="right", padx=2)
        
        # Strength slider
        def on_strength_change(val):
            strength_label.config(text=f"{float(val):.2f}")
            if self.on_change_callback:
                self.on_change_callback()
        
        slider = ttk.Scale(
            entry_frame,
            from_=0.0,
            to=1.5,
            variable=strength_var,
            orient="horizontal",
            command=on_strength_change
        )
        slider.pack(side="right", fill="x", expand=True, padx=5)
        
        # Store entry
        self._lora_entries.append((name, strength_var, entry_frame))
    
    def _remove_lora_entry(self, name: str) -> None:
        """Remove a LoRA entry from the list."""
        for i, (lora_name, _, frame) in enumerate(self._lora_entries):
            if lora_name == name:
                frame.destroy()
                self._lora_entries.pop(i)
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
        
        # Add new
        for name, strength in loras:
            self._add_lora_entry(name, strength)
    
    def clear(self) -> None:
        """Clear all LoRAs."""
        for _, _, frame in self._lora_entries:
            frame.destroy()
        self._lora_entries.clear()
        
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
            self.lora_name_combo["values"] = sorted(self._available_loras)
        except Exception:
            pass
    
    def refresh_loras(self) -> None:
        """Force rescan of LoRA directory."""
        try:
            self.scanner.scan_loras(force_rescan=True)
            self._available_loras = self.scanner.get_lora_names()
            self.lora_name_combo["values"] = sorted(self._available_loras)
        except Exception:
            pass
    


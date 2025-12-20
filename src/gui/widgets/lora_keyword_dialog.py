"""Dialog for displaying and copying LoRA keywords."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from src.utils.lora_keyword_detector import LoRAMetadata


class LoRAKeywordDialog(tk.Toplevel):
    """Modal dialog showing detected LoRA keywords."""
    
    def __init__(
        self,
        parent: tk.Misc,
        metadata: LoRAMetadata,
        on_copy: Callable[[str], None] | None = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.metadata = metadata
        self.on_copy = on_copy
        self.filtered_keywords = metadata.keywords.copy()
        
        self.title(f"Keywords: {metadata.name}")
        self.geometry("500x450")
        self.transient(parent)
        
        self._build_ui()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _build_ui(self) -> None:
        """Build dialog UI."""
        # Header
        header_frame = ttk.Frame(self, padding=10)
        header_frame.pack(fill="x")
        
        ttk.Label(
            header_frame,
            text=f"LoRA: {self.metadata.name}",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w")
        
        if self.metadata.source != "none":
            ttk.Label(
                header_frame,
                text=f"Source: {self.metadata.source}",
                font=("Segoe UI", 9)
            ).pack(anchor="w")
        
        # Keywords section
        content_frame = ttk.Frame(self, padding=10)
        content_frame.pack(fill="both", expand=True)
        
        if self.metadata.keywords:
            ttk.Label(
                content_frame,
                text="Detected Keywords:",
                font=("Segoe UI", 10, "bold")
            ).pack(anchor="w", pady=(0, 5))
            
            # Search/filter field
            search_frame = ttk.Frame(content_frame)
            search_frame.pack(fill="x", pady=(0, 5))
            
            ttk.Label(search_frame, text="Filter:").pack(side="left", padx=(0, 5))
            self.search_var = tk.StringVar()
            self.search_var.trace_add("write", lambda *args: self._filter_keywords())
            search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
            search_entry.pack(side="left", fill="x", expand=True)
            
            # Keyword list with copy buttons
            list_frame = ttk.Frame(content_frame)
            list_frame.pack(fill="both", expand=True)
            
            canvas = tk.Canvas(list_frame, bg="#2b2b2b", highlightthickness=0)
            scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
            self.scroll_frame = ttk.Frame(canvas)
            
            self.scroll_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            
            # Enable mousewheel scrolling
            canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
            
            # Initially populate all keywords
            self._populate_keywords()
            
        else:
            ttk.Label(
                content_frame,
                text="No keywords detected",
                font=("Segoe UI", 10),
                foreground="gray"
            ).pack(anchor="w", pady=20)
            
            if self.metadata.path:
                ttk.Label(
                    content_frame,
                    text=f"Searched: {self.metadata.path.parent}",
                    font=("Segoe UI", 9),
                    foreground="gray"
                ).pack(anchor="w")
        
        # Description (if available)
        if self.metadata.description:
            ttk.Separator(content_frame, orient="horizontal").pack(fill="x", pady=10)
            ttk.Label(
                content_frame,
                text="Description:",
                font=("Segoe UI", 9, "bold")
            ).pack(anchor="w")
            desc_text = tk.Text(content_frame, height=4, wrap="word", bg="#2b2b2b", fg="white")
            desc_text.insert("1.0", self.metadata.description)
            desc_text.config(state="disabled")
            desc_text.pack(fill="x", pady=(2, 0))
        
        # Buttons
        button_frame = ttk.Frame(self, padding=10)
        button_frame.pack(fill="x")
        
        if self.metadata.keywords:
            ttk.Button(
                button_frame,
                text="Copy All Keywords",
                command=self._copy_all
            ).pack(side="left", padx=(0, 5))
        
        ttk.Button(
            button_frame,
            text="Close",
            command=self.destroy
        ).pack(side="right")
    
    def _filter_keywords(self) -> None:
        """Filter keywords based on search text."""
        search_text = self.search_var.get().lower()
        self.filtered_keywords = [
            kw for kw in self.metadata.keywords
            if search_text in kw.lower()
        ]
        self._populate_keywords()
    
    def _populate_keywords(self) -> None:
        """Populate keyword list with current filter."""
        # Clear existing
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        
        # Add filtered keywords
        for keyword in self.filtered_keywords:
            self._add_keyword_entry(self.scroll_frame, keyword)
        
        # Show count if filtered
        if hasattr(self, 'search_var') and self.search_var.get():
            count_text = f" ({len(self.filtered_keywords)}/{len(self.metadata.keywords)})"
            self.title(f"Keywords: {self.metadata.name}{count_text}")
    
    def _add_keyword_entry(self, parent: ttk.Frame, keyword: str) -> None:
        """Add a keyword entry with copy button."""
        entry_frame = ttk.Frame(parent, padding=2)
        entry_frame.pack(fill="x", pady=1)
        
        # Keyword label
        label = ttk.Label(
            entry_frame,
            text=keyword,
            font=("Consolas", 10),
            background="#3c3c3c",
            foreground="white",
            padding=5
        )
        label.pack(side="left", fill="x", expand=True)
        
        # Copy button
        def copy_keyword():
            if self.on_copy:
                self.on_copy(keyword)
            # Also copy to clipboard
            self.clipboard_clear()
            self.clipboard_append(keyword)
        
        ttk.Button(
            entry_frame,
            text="Copy",
            command=copy_keyword,
            width=8
        ).pack(side="right", padx=(5, 0))
    
    def _copy_all(self) -> None:
        """Copy all keywords as comma-separated string."""
        all_keywords = ", ".join(self.metadata.keywords)
        
        if self.on_copy:
            self.on_copy(all_keywords)
        
        # Copy to clipboard
        self.clipboard_clear()
        self.clipboard_append(all_keywords)
        
        # Visual feedback
        self.title(f"Keywords: {self.metadata.name} (Copied!)")
        self.after(1500, lambda: self.title(f"Keywords: {self.metadata.name}"))

"""Simple embedding picker panel for managing positive and negative embeddings.

This widget provides a basic interface for adding/removing embeddings.
Resource scanning will be added in Phase C.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from src.utils.embedding_scanner import get_embedding_scanner


class EmbeddingPickerPanel(ttk.Frame):
    """Panel for managing positive and negative embeddings."""
    
    def __init__(
        self,
        parent: tk.Misc,
        on_change_callback: Callable[[], None] | None = None,
        webui_root: str | None = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.on_change_callback = on_change_callback
        self._positive_embeddings: list[str] = []
        self._negative_embeddings: list[str] = []

        # Initialize scanner
        self.scanner = get_embedding_scanner(webui_root)
        self._available_embeddings: list[str] = []

        # Autocomplete widgets
        self._pos_autocomplete_list: tk.Listbox | None = None
        self._neg_autocomplete_list: tk.Listbox | None = None

        self._build_ui()

        # Start background scan
        self.after(100, self._scan_embeddings)

    def _build_ui(self) -> None:
        """Build the embedding picker UI."""
        # Header with refresh button
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", padx=5, pady=(5, 2))

        header = ttk.Label(header_frame, text="Embeddings", font=("Segoe UI", 10, "bold"))
        header.pack(side="left")

        refresh_btn = ttk.Button(
            header_frame,
            text="↻ Refresh",
            width=10,
            command=self.refresh_embeddings
        )
        refresh_btn.pack(side="right")

        # Positive embeddings section
        pos_frame = ttk.LabelFrame(self, text="Positive", padding=5)
        pos_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Positive add controls
        pos_add_frame = ttk.Frame(pos_frame)
        pos_add_frame.pack(fill="x", pady=(0, 5))
        
        self.pos_entry = ttk.Entry(pos_add_frame, width=25)
        self.pos_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.pos_entry.insert(0, "Embedding name...")
        self.pos_entry.bind("<FocusIn>", lambda e: self._on_entry_focus(self.pos_entry, clear=True))
        self.pos_entry.bind("<FocusOut>", lambda e: self._on_entry_focus(self.pos_entry, clear=False))
        self.pos_entry.bind("<Return>", lambda e: self._on_add_positive())
        self.pos_entry.bind("<KeyRelease>", self._on_pos_entry_key_release)
        self.pos_entry.bind("<Escape>", lambda e: self._hide_pos_autocomplete())
        
        ttk.Button(pos_add_frame, text="Add", command=self._on_add_positive).pack(side="left")
        
        # Positive list
        self.pos_listbox = tk.Listbox(pos_frame, height=4, bg="#2b2b2b", fg="white")
        self.pos_listbox.pack(fill="both", expand=True, pady=(0, 5))
        
        ttk.Button(pos_frame, text="Remove Selected", command=self._on_remove_positive).pack()
        
        # Negative embeddings section
        neg_frame = ttk.LabelFrame(self, text="Negative", padding=5)
        neg_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Negative add controls
        neg_add_frame = ttk.Frame(neg_frame)
        neg_add_frame.pack(fill="x", pady=(0, 5))
        
        self.neg_entry = ttk.Entry(neg_add_frame, width=25)
        self.neg_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.neg_entry.insert(0, "Embedding name...")
        self.neg_entry.bind("<FocusIn>", lambda e: self._on_entry_focus(self.neg_entry, clear=True))
        self.neg_entry.bind("<FocusOut>", lambda e: self._on_entry_focus(self.neg_entry, clear=False))
        self.neg_entry.bind("<Return>", lambda e: self._on_add_negative())
        self.neg_entry.bind("<KeyRelease>", self._on_neg_entry_key_release)
        self.neg_entry.bind("<Escape>", lambda e: self._hide_neg_autocomplete())
        
        ttk.Button(neg_add_frame, text="Add", command=self._on_add_negative).pack(side="left")
        
        # Negative list
        self.neg_listbox = tk.Listbox(neg_frame, height=4, bg="#2b2b2b", fg="white")
        self.neg_listbox.pack(fill="both", expand=True, pady=(0, 5))
        
        ttk.Button(neg_frame, text="Remove Selected", command=self._on_remove_negative).pack()
    
    def _on_entry_focus(self, entry: ttk.Entry, clear: bool) -> None:
        """Handle entry field focus for placeholder text."""
        if clear:
            if entry.get() == "Embedding name...":
                entry.delete(0, "end")
        else:
            if not entry.get():
                entry.insert(0, "Embedding name...")
    
    def _on_add_positive(self) -> None:
        """Add a positive embedding."""
        name = self.pos_entry.get().strip()
        if not name or name == "Embedding name...":
            return
        
        if name not in self._positive_embeddings:
            self._positive_embeddings.append(name)
            self.pos_listbox.insert("end", name)
            
            if self.on_change_callback:
                self.on_change_callback()
        
        self.pos_entry.delete(0, "end")
        self.pos_entry.insert(0, "Embedding name...")
    
    def _on_remove_positive(self) -> None:
        """Remove selected positive embedding."""
        selection = self.pos_listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        self._positive_embeddings.pop(index)
        self.pos_listbox.delete(index)
        
        if self.on_change_callback:
            self.on_change_callback()
    
    def _on_add_negative(self) -> None:
        """Add a negative embedding."""
        name = self.neg_entry.get().strip()
        if not name or name == "Embedding name...":
            return
        
        if name not in self._negative_embeddings:
            self._negative_embeddings.append(name)
            self.neg_listbox.insert("end", name)
            
            if self.on_change_callback:
                self.on_change_callback()
        
        self.neg_entry.delete(0, "end")
        self.neg_entry.insert(0, "Embedding name...")
    
    def _on_remove_negative(self) -> None:
        """Remove selected negative embedding."""
        selection = self.neg_listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        self._negative_embeddings.pop(index)
        self.neg_listbox.delete(index)
        
        if self.on_change_callback:
            self.on_change_callback()
    
    def get_positive_embeddings(self) -> list[str]:
        """Return list of positive embedding names."""
        return self._positive_embeddings.copy()
    
    def get_negative_embeddings(self) -> list[str]:
        """Return list of negative embedding names."""
        return self._negative_embeddings.copy()
    
    def set_positive_embeddings(self, embeddings: list[str]) -> None:
        """Load positive embeddings into UI."""
        self._positive_embeddings = embeddings.copy()
        self.pos_listbox.delete(0, "end")
        for name in embeddings:
            self.pos_listbox.insert("end", name)
    
    def set_negative_embeddings(self, embeddings: list[str]) -> None:
        """Load negative embeddings into UI."""
        self._negative_embeddings = embeddings.copy()
        self.neg_listbox.delete(0, "end")
        for name in embeddings:
            self.neg_listbox.insert("end", name)
    
    def clear(self) -> None:
        """Clear all embeddings."""
        self._positive_embeddings.clear()
        self._negative_embeddings.clear()
        self.pos_listbox.delete(0, "end")
        self.neg_listbox.delete(0, "end")
        
        if self.on_change_callback:
            self.on_change_callback()
    # Scanner and Autocomplete Methods ----------------------------------

    def _scan_embeddings(self) -> None:
        """Background scan of embeddings directory."""
        try:
            self.scanner.scan_embeddings()
            self._available_embeddings = self.scanner.get_embedding_names()
        except Exception:
            pass

    def refresh_embeddings(self) -> None:
        """Force rescan of embeddings directory."""
        try:
            self.scanner.scan_embeddings(force_rescan=True)
            self._available_embeddings = self.scanner.get_embedding_names()
        except Exception:
            pass

    def _on_pos_entry_key_release(self, event) -> None:
        """Handle key release in positive entry for autocomplete."""
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            if self._pos_autocomplete_list and self._pos_autocomplete_list.winfo_viewable():
                self._handle_pos_autocomplete_nav(event)
            return

        # Get current text
        text = self.pos_entry.get()
        if not text or text == "Embedding name...":
            self._hide_pos_autocomplete()
            return

        # Show matching embeddings
        matches = [name for name in self._available_embeddings if text.lower() in name.lower()]
        if matches:
            self._show_pos_autocomplete(matches[:10])  # Limit to 10
        else:
            self._hide_pos_autocomplete()

    def _on_neg_entry_key_release(self, event) -> None:
        """Handle key release in negative entry for autocomplete."""
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            if self._neg_autocomplete_list and self._neg_autocomplete_list.winfo_viewable():
                self._handle_neg_autocomplete_nav(event)
            return

        # Get current text
        text = self.neg_entry.get()
        if not text or text == "Embedding name...":
            self._hide_neg_autocomplete()
            return

        # Show matching embeddings
        matches = [name for name in self._available_embeddings if text.lower() in name.lower()]
        if matches:
            self._show_neg_autocomplete(matches[:10])  # Limit to 10
        else:
            self._hide_neg_autocomplete()

    def _show_pos_autocomplete(self, matches: list[str]) -> None:
        """Show autocomplete dropdown for positive entry."""
        if self._pos_autocomplete_list is None:
            self._pos_autocomplete_list = tk.Listbox(
                self.pos_entry,
                height=min(8, len(matches)),
                exportselection=False,
            )
            self._pos_autocomplete_list.bind("<Double-Button-1>", lambda e: self._on_pos_autocomplete_select())
            self._pos_autocomplete_list.bind("<Return>", lambda e: self._on_pos_autocomplete_select())

        self._pos_autocomplete_list.delete(0, "end")
        for name in matches:
            self._pos_autocomplete_list.insert("end", name)

        # Position below entry
        try:
            x = 0
            y = self.pos_entry.winfo_height()
            width = self.pos_entry.winfo_width()
            self._pos_autocomplete_list.place(x=x, y=y, width=width)
            if self._pos_autocomplete_list.size() > 0:
                self._pos_autocomplete_list.selection_set(0)
        except Exception:
            pass

    def _show_neg_autocomplete(self, matches: list[str]) -> None:
        """Show autocomplete dropdown for negative entry."""
        if self._neg_autocomplete_list is None:
            self._neg_autocomplete_list = tk.Listbox(
                self.neg_entry,
                height=min(8, len(matches)),
                exportselection=False,
            )
            self._neg_autocomplete_list.bind("<Double-Button-1>", lambda e: self._on_neg_autocomplete_select())
            self._neg_autocomplete_list.bind("<Return>", lambda e: self._on_neg_autocomplete_select())

        self._neg_autocomplete_list.delete(0, "end")
        for name in matches:
            self._neg_autocomplete_list.insert("end", name)

        # Position below entry
        try:
            x = 0
            y = self.neg_entry.winfo_height()
            width = self.neg_entry.winfo_width()
            self._neg_autocomplete_list.place(x=x, y=y, width=width)
            if self._neg_autocomplete_list.size() > 0:
                self._neg_autocomplete_list.selection_set(0)
        except Exception:
            pass

    def _hide_pos_autocomplete(self) -> None:
        """Hide positive autocomplete dropdown."""
        if self._pos_autocomplete_list:
            self._pos_autocomplete_list.place_forget()

    def _hide_neg_autocomplete(self) -> None:
        """Hide negative autocomplete dropdown."""
        if self._neg_autocomplete_list:
            self._neg_autocomplete_list.place_forget()

    def _handle_pos_autocomplete_nav(self, event) -> None:
        """Handle Up/Down/Return in positive autocomplete."""
        if not self._pos_autocomplete_list:
            return

        if event.keysym == "Down":
            current = self._pos_autocomplete_list.curselection()
            if current:
                idx = current[0]
                if idx < self._pos_autocomplete_list.size() - 1:
                    self._pos_autocomplete_list.selection_clear(idx)
                    self._pos_autocomplete_list.selection_set(idx + 1)
                    self._pos_autocomplete_list.see(idx + 1)
        elif event.keysym == "Up":
            current = self._pos_autocomplete_list.curselection()
            if current:
                idx = current[0]
                if idx > 0:
                    self._pos_autocomplete_list.selection_clear(idx)
                    self._pos_autocomplete_list.selection_set(idx - 1)
                    self._pos_autocomplete_list.see(idx - 1)
        elif event.keysym == "Return":
            self._on_pos_autocomplete_select()

    def _handle_neg_autocomplete_nav(self, event) -> None:
        """Handle Up/Down/Return in negative autocomplete."""
        if not self._neg_autocomplete_list:
            return

        if event.keysym == "Down":
            current = self._neg_autocomplete_list.curselection()
            if current:
                idx = current[0]
                if idx < self._neg_autocomplete_list.size() - 1:
                    self._neg_autocomplete_list.selection_clear(idx)
                    self._neg_autocomplete_list.selection_set(idx + 1)
                    self._neg_autocomplete_list.see(idx + 1)
        elif event.keysym == "Up":
            current = self._neg_autocomplete_list.curselection()
            if current:
                idx = current[0]
                if idx > 0:
                    self._neg_autocomplete_list.selection_clear(idx)
                    self._neg_autocomplete_list.selection_set(idx - 1)
                    self._neg_autocomplete_list.see(idx - 1)
        elif event.keysym == "Return":
            self._on_neg_autocomplete_select()

    def _on_pos_autocomplete_select(self) -> None:
        """Insert selected embedding from positive autocomplete."""
        if not self._pos_autocomplete_list:
            return

        selection = self._pos_autocomplete_list.curselection()
        if not selection:
            return

        embedding_name = self._pos_autocomplete_list.get(selection[0])
        self.pos_entry.delete(0, "end")
        self.pos_entry.insert(0, embedding_name)
        self._hide_pos_autocomplete()
        self._on_add_positive()

    def _on_neg_autocomplete_select(self) -> None:
        """Insert selected embedding from negative autocomplete."""
        if not self._neg_autocomplete_list:
            return

        selection = self._neg_autocomplete_list.curselection()
        if not selection:
            return

        embedding_name = self._neg_autocomplete_list.get(selection[0])
        self.neg_entry.delete(0, "end")
        self.neg_entry.insert(0, embedding_name)
        self._hide_neg_autocomplete()
        self._on_add_negative()
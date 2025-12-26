"""
Multi-Folder Selection Dialog

Provides a list-builder interface for selecting multiple folders at once,
replacing the tedious one-at-a-time folder selection workflow.

Usage:
    folders = MultiFolderSelector.ask_folders(parent, title="Select Folders")
    # Returns list of folder paths or empty list if cancelled
"""

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

logger = logging.getLogger(__name__)


class MultiFolderSelector(tk.Toplevel):
    """
    Modal dialog for selecting multiple folders with list management.

    Features:
    - Add folders one by one (repeated dialogs)
    - Remove selected folder from list
    - Clear all folders
    - Prevents duplicate folders
    - Modal behavior (blocks parent until closed)

    Example:
        folders = MultiFolderSelector.ask_folders(
            parent_window,
            title="Select Folders for Reprocessing"
        )
        for folder in folders:
            print(f"Selected: {folder}")
    """

    def __init__(self, parent: tk.Widget, title: str = "Select Multiple Folders"):
        """
        Initialize multi-folder selector dialog.

        Args:
            parent: Parent window
            title: Dialog title
        """
        super().__init__(parent)
        self.title(title)
        self.selected_folders: list[str] = []
        self.result_folders: list[str] | None = None  # None = cancelled

        # Configure window
        self.geometry("600x400")
        self.minsize(500, 300)

        # Build UI
        self._build_ui()

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self._center_on_parent(parent)
        
    def _center_on_parent(self, parent: tk.Widget):
        """Center dialog on parent window."""
        self.update_idletasks()
        
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        
        dialog_w = self.winfo_width()
        dialog_h = self.winfo_height()
        
        x = parent_x + (parent_w - dialog_w) // 2
        y = parent_y + (parent_h - dialog_h) // 2
        
        self.geometry(f"+{x}+{y}")
        
    def _build_ui(self):
        """Build dialog UI components."""
        # Main container
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill="both", expand=True)
        
        # Header label
        header = ttk.Label(
            main_frame,
            text="Select folders to add (click 'Add Folder' multiple times):",
            font=("Segoe UI", 10)
        )
        header.pack(anchor="w", pady=(0, 10))
        
        # List container with scrollbar
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        
        # Listbox for folders
        self.folder_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            height=12,
            selectmode="extended",  # Allow selecting multiple for batch removal
            font=("Consolas", 9),
            relief="solid",
            borderwidth=1
        )
        scrollbar.config(command=self.folder_listbox.yview)
        
        self.folder_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Bind keyboard shortcuts
        self.folder_listbox.bind("<Delete>", lambda e: self._remove_selected())
        self.folder_listbox.bind("<BackSpace>", lambda e: self._remove_selected())
        
        # Button row for list management
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=(0, 10))
        
        self.add_btn = ttk.Button(
            btn_frame,
            text="Add Folder...",
            command=self._add_folder,
            width=15
        )
        self.add_btn.pack(side="left", padx=(0, 5))
        
        self.remove_btn = ttk.Button(
            btn_frame,
            text="Remove Selected",
            command=self._remove_selected,
            width=15
        )
        self.remove_btn.pack(side="left", padx=(0, 5))
        
        self.clear_btn = ttk.Button(
            btn_frame,
            text="Clear All",
            command=self._clear_all,
            width=15
        )
        self.clear_btn.pack(side="left", padx=(0, 5))
        
        # Status label
        self.status_label = ttk.Label(
            main_frame,
            text="0 folders selected",
            foreground="gray"
        )
        self.status_label.pack(anchor="w", pady=(0, 10))
        
        # OK/Cancel buttons
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill="x")
        
        cancel_btn = ttk.Button(
            action_frame,
            text="Cancel",
            command=self._on_cancel,
            width=12
        )
        cancel_btn.pack(side="right", padx=(5, 0))
        
        ok_btn = ttk.Button(
            action_frame,
            text="OK",
            command=self._on_ok,
            width=12
        )
        ok_btn.pack(side="right")
        
        # Bind window close to cancel
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        
        # Focus on Add Folder button
        self.add_btn.focus_set()
        
    def _add_folder(self):
        """
        Open folder dialog and add selected folder to list.
        
        Prevents duplicate folders and updates UI.
        """
        folder = filedialog.askdirectory(
            parent=self,
            title="Select Folder to Add"
        )
        
        if folder:
            # Normalize path
            folder = str(Path(folder).resolve())
            
            # Check for duplicates
            if folder in self.selected_folders:
                logger.info(f"Folder already in list: {folder}")
                # Could show a warning here, but silent is fine
                return
            
            # Add to list
            self.selected_folders.append(folder)
            self.folder_listbox.insert("end", folder)
            
            # Update status
            self._update_status()
            
            logger.debug(f"Added folder: {folder}")
    
    def _remove_selected(self):
        """Remove selected folder(s) from list."""
        selection = self.folder_listbox.curselection()
        
        if not selection:
            return
        
        # Remove from bottom to top to maintain indices
        for idx in reversed(selection):
            self.folder_listbox.delete(idx)
            del self.selected_folders[idx]
        
        # Update status
        self._update_status()
        
        logger.debug(f"Removed {len(selection)} folder(s)")
    
    def _clear_all(self):
        """Clear all folders from list."""
        self.folder_listbox.delete(0, "end")
        self.selected_folders.clear()
        
        # Update status
        self._update_status()
        
        logger.debug("Cleared all folders")
    
    def _update_status(self):
        """Update status label with folder count."""
        count = len(self.selected_folders)
        
        if count == 0:
            text = "0 folders selected"
        elif count == 1:
            text = "1 folder selected"
        else:
            text = f"{count} folders selected"
        
        self.status_label.config(text=text)
    
    def _on_ok(self):
        """Close dialog and return selected folders."""
        self.result_folders = self.selected_folders.copy()
        self.destroy()
        
        logger.info(f"Multi-folder selection confirmed: {len(self.result_folders)} folders")
    
    def _on_cancel(self):
        """Close dialog without returning folders."""
        self.result_folders = None  # Indicates cancelled
        self.destroy()
        
        logger.debug("Multi-folder selection cancelled")
    
    @classmethod
    def ask_folders(cls, parent: tk.Widget, title: str = "Select Multiple Folders") -> list[str]:
        """
        Show multi-folder selection dialog.
        
        This is the main entry point for using this dialog.
        
        Args:
            parent: Parent window for the dialog
            title: Dialog window title
            
        Returns:
            List of selected folder paths (empty if cancelled)
            
        Example:
            folders = MultiFolderSelector.ask_folders(
                parent_window,
                title="Select Folders for Reprocessing"
            )
            
            if folders:
                for folder in folders:
                    print(f"Selected: {folder}")
            else:
                print("Cancelled or no folders selected")
        """
        dialog = cls(parent, title)
        parent.wait_window(dialog)
        
        # Return empty list if cancelled
        if dialog.result_folders is None:
            return []
        
        return dialog.result_folders

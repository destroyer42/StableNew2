"""ReprocessPanelV2: GUI panel for selecting and reprocessing existing images.

Allows users to:
- Select existing images from output folders (multiple folders supported)
- Recursive folder scanning option
- Filter by filename pattern (e.g., "txt2img")
- Filter by image dimensions
- Choose which stages to apply (img2img, adetailer, upscale)
- Submit reprocessing jobs to the queue

Stage order: img2img → adetailer → upscale
- img2img: Fix grainy/bad images, adjust composition
- adetailer: Enhance faces and details
- upscale: Increase resolution
"""

from __future__ import annotations

import logging
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from src.gui.theme_v2 import (
    BODY_LABEL_STYLE,
    CARD_FRAME_STYLE,
    HEADING_LABEL_STYLE,
)

logger = logging.getLogger(__name__)

# Try to import PIL for image dimension filtering
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL not available - image dimension filtering will be disabled")


class ReprocessPanelV2(ttk.Frame):
    """Panel for selecting and reprocessing existing images through pipeline stages."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any = None,
        app_state: Any = None,
        embed_mode: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize the reprocess panel.
        
        Args:
            master: Parent widget
            controller: App controller for job submission
            app_state: Application state
            embed_mode: If True, skip outer frame styling (for embedding in cards)
            **kwargs: Additional ttk.Frame options
        """
        style = CARD_FRAME_STYLE if not embed_mode else None
        if style and "style" not in kwargs:
            kwargs["style"] = style
        
        super().__init__(master, **kwargs)
        self.controller = controller
        self.app_state = app_state
        
        # State
        self.selected_images: list[Path] = []
        self.selected_folders: list[Path] = []
        self.img2img_var = tk.BooleanVar(value=False)
        self.adetailer_var = tk.BooleanVar(value=True)
        self.upscale_var = tk.BooleanVar(value=False)
        
        # Folder scanning options
        self.recursive_var = tk.BooleanVar(value=False)
        self.filename_filter_var = tk.StringVar(value="txt2img")  # Default to txt2img to avoid upscaled images
        self.dimension_filter_enabled_var = tk.BooleanVar(value=True)  # Enable by default to prevent upscale selection
        self.max_width_var = tk.IntVar(value=1280)
        self.max_height_var = tk.IntVar(value=1280)
        
        # Batch processing options
        self.batch_size_var = tk.IntVar(value=1)  # 1 = one job per image
        
        self.columnconfigure(0, weight=1)
        
        # Header
        if not embed_mode:
            header = ttk.Label(self, text="Image Reprocessing", style=HEADING_LABEL_STYLE)
            header.grid(row=0, column=0, sticky="w", padx=4, pady=(4, 8))
            current_row = 1
        else:
            current_row = 0
        
        # Description
        desc = ttk.Label(
            self,
            text="Select existing images to send through pipeline stages",
            style=BODY_LABEL_STYLE,
            wraplength=300,
        )
        desc.grid(row=current_row, column=0, sticky="w", padx=4, pady=(0, 8))
        current_row += 1
        
        # Image selection section
        selection_frame = ttk.Frame(self, style=CARD_FRAME_STYLE)
        selection_frame.grid(row=current_row, column=0, sticky="ew", padx=4, pady=(0, 8))
        selection_frame.columnconfigure(0, weight=1)
        current_row += 1
        
        self.select_images_button = ttk.Button(
            selection_frame,
            text="Select Images...",
            command=self._on_select_images,
        )
        self.select_images_button.grid(row=0, column=0, sticky="ew", pady=2)
        
        self.select_folder_button = ttk.Button(
            selection_frame,
            text="Select Folder(s)...",
            command=self._on_select_folders,
        )
        self.select_folder_button.grid(row=1, column=0, sticky="ew", pady=2)
        
        self.clear_button = ttk.Button(
            selection_frame,
            text="Clear Selection",
            command=self._on_clear_selection,
        )
        self.clear_button.grid(row=2, column=0, sticky="ew", pady=2)
        
        # Selected images display
        self.images_label = ttk.Label(
            self,
            text="No images selected",
            style=BODY_LABEL_STYLE,
            wraplength=300,
        )
        self.images_label.grid(row=current_row, column=0, sticky="w", padx=4, pady=(0, 8))
        current_row += 1
        
        # Folder scanning options
        folder_options_frame = ttk.LabelFrame(self, text="Folder Scan Options", padding=8)
        folder_options_frame.grid(row=current_row, column=0, sticky="ew", padx=4, pady=(0, 8))
        current_row += 1

        # Filter results display (summary + table)
        self.filter_results_frame = ttk.LabelFrame(self, text="Filter Results", padding=8)
        self.filter_results_frame.grid(row=current_row, column=0, sticky="ew", padx=4, pady=(0, 8))
        current_row += 1

        self.filter_summary_label = ttk.Label(
            self.filter_results_frame,
            text="No folders selected",
            style=BODY_LABEL_STYLE,
        )
        self.filter_summary_label.pack(anchor="w", pady=(0, 4))

        columns = ("source", "total", "filtered")
        self.filter_results_tree = ttk.Treeview(
            self.filter_results_frame,
            columns=columns,
            show="headings",
            height=6,
        )
        self.filter_results_tree.heading("source", text="Folder / File")
        self.filter_results_tree.heading("total", text="Total Images")
        self.filter_results_tree.heading("filtered", text="After Filters")
        self.filter_results_tree.column("source", width=240, anchor="w")
        self.filter_results_tree.column("total", width=90, anchor="center")
        self.filter_results_tree.column("filtered", width=110, anchor="center")
        self.filter_results_tree.pack(fill="both", expand=True)

        filter_scroll = ttk.Scrollbar(
            self.filter_results_tree,
            orient="vertical",
            command=self.filter_results_tree.yview,
        )
        filter_scroll.pack(side="right", fill="y")
        self.filter_results_tree.configure(yscrollcommand=filter_scroll.set)
        
        # Recursive checkbox
        self.recursive_check = ttk.Checkbutton(
            folder_options_frame,
            text="Scan subfolders recursively",
            variable=self.recursive_var,
            style="Dark.TCheckbutton",
        )
        self.recursive_check.pack(anchor="w", pady=2)
        
        # Filename filter
        filename_frame = ttk.Frame(folder_options_frame)
        filename_frame.pack(fill="x", pady=2)
        ttk.Label(filename_frame, text="Filename contains:", style=BODY_LABEL_STYLE).pack(side="left", padx=(0, 4))
        self.filename_filter_entry = ttk.Entry(
            filename_frame,
            textvariable=self.filename_filter_var,
            width=15,
            style="Dark.TEntry",
        )
        self.filename_filter_entry.pack(side="left", fill="x", expand=True)
        
        # Dimension filter
        self.dimension_filter_check = ttk.Checkbutton(
            folder_options_frame,
            text="Filter by max dimensions:" if PIL_AVAILABLE else "Filter by dimensions (PIL required)",
            variable=self.dimension_filter_enabled_var,
            style="Dark.TCheckbutton",
            state="normal" if PIL_AVAILABLE else "disabled",
        )
        self.dimension_filter_check.pack(anchor="w", pady=2)
        
        if PIL_AVAILABLE:
            dim_frame = ttk.Frame(folder_options_frame)
            dim_frame.pack(fill="x", pady=2, padx=(20, 0))
            
            ttk.Label(dim_frame, text="Max width:", style=BODY_LABEL_STYLE).pack(side="left", padx=(0, 4))
            self.max_width_spinbox = ttk.Spinbox(
                dim_frame,
                from_=64,
                to=8192,
                increment=64,
                textvariable=self.max_width_var,
                width=8,
            )
            self.max_width_spinbox.pack(side="left", padx=(0, 12))
            
            ttk.Label(dim_frame, text="Max height:", style=BODY_LABEL_STYLE).pack(side="left", padx=(0, 4))
            self.max_height_spinbox = ttk.Spinbox(
                dim_frame,
                from_=64,
                to=8192,
                increment=64,
                textvariable=self.max_height_var,
                width=8,
            )
            self.max_height_spinbox.pack(side="left")
        
        # Refresh filter button - reapply filters to current folder selection
        refresh_button = ttk.Button(
            folder_options_frame,
            text="Refresh Filter",
            command=self._scan_folders_for_images,
        )
        refresh_button.pack(anchor="w", pady=(4, 0))
        
        # Stage selection section
        stages_frame = ttk.LabelFrame(self, text="Stages to Apply", padding=8)
        stages_frame.grid(row=current_row, column=0, sticky="ew", padx=4, pady=(0, 8))
        current_row += 1
        
        # Help text
        help_text = ttk.Label(
            stages_frame,
            text="Stages run in order: img2img → adetailer → upscale",
            style=BODY_LABEL_STYLE,
            foreground="gray",
        )
        help_text.pack(anchor="w", pady=(0, 4))
        
        self.img2img_check = ttk.Checkbutton(
            stages_frame,
            text="img2img (fix grainy/bad images)",
            variable=self.img2img_var,
            style="Dark.TCheckbutton",
        )
        self.img2img_check.pack(anchor="w", pady=2)
        
        self.adetailer_check = ttk.Checkbutton(
            stages_frame,
            text="ADetailer (face fix)",
            variable=self.adetailer_var,
            style="Dark.TCheckbutton",
        )
        self.adetailer_check.pack(anchor="w", pady=2)
        
        self.upscale_check = ttk.Checkbutton(
            stages_frame,
            text="Upscale",
            variable=self.upscale_var,
            style="Dark.TCheckbutton",
        )
        self.upscale_check.pack(anchor="w", pady=2)
        
        # Batch size options
        batch_frame = ttk.LabelFrame(self, text="Job Batching", padding=8)
        batch_frame.grid(row=current_row, column=0, sticky="ew", padx=4, pady=(0, 8))
        current_row += 1
        
        batch_help = ttk.Label(
            batch_frame,
            text="Images per job (1 = separate job for each image)",
            style=BODY_LABEL_STYLE,
            foreground="gray",
        )
        batch_help.pack(anchor="w", pady=(0, 4))
        
        batch_control_frame = ttk.Frame(batch_frame)
        batch_control_frame.pack(fill="x", pady=2)
        
        ttk.Label(batch_control_frame, text="Batch size:", style=BODY_LABEL_STYLE).pack(side="left", padx=(0, 4))
        self.batch_size_spinbox = ttk.Spinbox(
            batch_control_frame,
            from_=1,
            to=100,
            increment=1,
            textvariable=self.batch_size_var,
            width=8,
        )
        self.batch_size_spinbox.pack(side="left")
        
        ttk.Label(
            batch_control_frame,
            text="(1-100 images)",
            style=BODY_LABEL_STYLE,
            foreground="gray",
        ).pack(side="left", padx=(4, 0))
        
        # Submit button
        self.reprocess_button = ttk.Button(
            self,
            text="Reprocess Images",
            command=self._on_reprocess,
            style="Primary.TButton",
        )
        self.reprocess_button.grid(row=current_row, column=0, sticky="ew", padx=4, pady=(0, 4))
        self.reprocess_button.config(state="disabled")
        
    def _on_select_images(self) -> None:
        """Handle Select Images button click."""
        filetypes = [
            ("Image files", "*.png *.jpg *.jpeg *.webp"),
            ("PNG files", "*.png"),
            ("JPEG files", "*.jpg *.jpeg"),
            ("WebP files", "*.webp"),
            ("All files", "*.*"),
        ]
        
        files = filedialog.askopenfilenames(
            title="Select Images to Reprocess",
            filetypes=filetypes,
        )
        
        if files:
            self.selected_images = [Path(f) for f in files]
            self._update_display()
            logger.info(f"Selected {len(self.selected_images)} images for reprocessing")
    
    def _on_select_folders(self) -> None:
        """Handle Select Folder(s) button click - allows multiple folder selection.
        
        Uses a custom multi-folder selection dialog since tkinter doesn't provide
        native multi-folder selection. Users can:
        - Click "Add Folder" repeatedly to build a list
        - Click "Done" when finished
        - Click "Clear All" to start over
        """
        # Create a modal dialog for multi-folder selection
        dialog = tk.Toplevel(self)
        dialog.title("Select Multiple Folders")
        dialog.geometry("600x400")
        try:
            dialog.transient(self.winfo_toplevel())  # type: ignore[arg-type]
        except Exception:
            pass  # transient is optional for dialog behavior
        dialog.grab_set()
        
        # Center dialog on parent
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dialog.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # State
        selected_folders: list[Path] = list(self.selected_folders)  # Start with existing selection
        
        # Top frame with instructions
        top_frame = ttk.Frame(dialog, padding=8)
        top_frame.pack(fill="x", side="top")
        
        ttk.Label(
            top_frame,
            text="Select folders to scan for images. Click 'Add Folder' to add more.",
            wraplength=580,
        ).pack(anchor="w")
        
        # Listbox to show selected folders
        list_frame = ttk.Frame(dialog, padding=8)
        list_frame.pack(fill="both", expand=True, side="top")
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        
        folder_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            selectmode="extended",  # Allow multi-select for removal
            height=12,
        )
        folder_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=folder_listbox.yview)
        
        def update_listbox() -> None:  # type: ignore[misc]
            """Refresh listbox with current folder selection."""
            folder_listbox.delete(0, tk.END)
            for folder in selected_folders:
                folder_listbox.insert(tk.END, str(folder))
        
        def add_folder() -> None:  # type: ignore[misc]
            """Open dialog to add a folder."""
            folder = filedialog.askdirectory(
                title="Select Folder with Images",
                parent=dialog,
            )
            
            if folder:
                folder_path = Path(folder)
                if folder_path not in selected_folders:
                    selected_folders.append(folder_path)
                    update_listbox()
                    logger.info(f"Added folder: {folder_path}")
                else:
                    logger.warning(f"Folder already in list: {folder_path}")
        
        def remove_selected() -> None:  # type: ignore[misc]
            """Remove selected folders from list."""
            indices = list(folder_listbox.curselection())  # type: ignore[no-untyped-call]
            if not indices:
                return
            
            # Remove in reverse order to avoid index shifting
            for idx in reversed(indices):
                folder_path = Path(folder_listbox.get(idx))
                if folder_path in selected_folders:
                    selected_folders.remove(folder_path)
            
            update_listbox()
        
        def clear_all() -> None:  # type: ignore[misc]
            """Clear all folders."""
            selected_folders.clear()
            update_listbox()
        
        def done() -> None:  # type: ignore[misc]
            """Close dialog and apply selection."""
            dialog.destroy()
        
        # Initialize listbox with existing folders
        update_listbox()
        
        # Button frame
        button_frame = ttk.Frame(dialog, padding=8)
        button_frame.pack(fill="x", side="bottom")
        
        ttk.Button(button_frame, text="Add Folder...", command=add_folder).pack(side="left", padx=2)
        ttk.Button(button_frame, text="Remove Selected", command=remove_selected).pack(side="left", padx=2)
        ttk.Button(button_frame, text="Clear All", command=clear_all).pack(side="left", padx=2)
        ttk.Button(button_frame, text="Done", command=done, style="Primary.TButton").pack(side="right", padx=2)
        
        # Wait for dialog to close
        self.wait_window(dialog)
        
        # Apply selection if any folders were chosen
        if selected_folders:
            self.selected_folders = selected_folders
            logger.info(f"Selected {len(selected_folders)} folder(s)")
            # Scan folders for images with filters
            self._scan_folders_for_images()
        else:
            logger.info("No folders selected")
    
    def _scan_folders_for_images(self) -> None:
        """Scan selected folders for images, applying filters."""
        if not self.selected_folders:
            return
        
        image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
        recursive = self.recursive_var.get()
        filename_filter = self.filename_filter_var.get().strip()
        dimension_filter_enabled = self.dimension_filter_enabled_var.get()
        max_width = self.max_width_var.get()
        max_height = self.max_height_var.get()
        
        all_images: list[Path] = []
        folder_totals: dict[str, int] = {}
        
        for folder in self.selected_folders:
            discovered: list[Path]
            if recursive:
                # Recursive glob
                discovered = []
                for ext in image_extensions:
                    discovered.extend(folder.rglob(f"*{ext}"))
            else:
                # Non-recursive
                discovered = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in image_extensions]
            all_images.extend(discovered)
            folder_totals[str(folder)] = len(discovered)
        
        total_found = len(all_images)
        logger.info(f"Found {total_found} total image(s) in {len(self.selected_folders)} folder(s) (recursive={recursive})")
        
        # Apply filename filter
        if filename_filter:
            pattern = re.escape(filename_filter)
            before_count = len(all_images)
            all_images = [
                img for img in all_images
                if re.search(pattern, img.name, re.IGNORECASE)
            ]
            after_count = len(all_images)
            logger.info(f"Filename filter '{filename_filter}': {before_count} → {after_count} images")
        
        # Apply dimension filter
        if dimension_filter_enabled and PIL_AVAILABLE:
            before_count = len(all_images)
            filtered_images = []
            for img_path in all_images:
                try:
                    with Image.open(img_path) as img:
                        width, height = img.size
                        # Filter images where BOTH dimensions are within limits
                        if width <= max_width and height <= max_height:
                            filtered_images.append(img_path)
                        else:
                            logger.debug(f"Filtered out {img_path.name}: {width}×{height} exceeds {max_width}×{max_height}")
                except Exception as exc:
                    logger.warning(f"Could not read dimensions for {img_path}: {exc}")
            all_images = filtered_images
            after_count = len(filtered_images)
            logger.info(f"Dimension filter ≤{max_width}×{max_height}: {before_count} → {after_count} images")
        
        self.selected_images = all_images
        self._update_display()
        
        logger.info(f"Final selection: {len(all_images)} image(s) ready for reprocessing")

        # Update summary label and table
        summary_parts = [f"{total_found} images in {len(self.selected_folders)} folder(s)"]
        if filename_filter:
            summary_parts.append(f"after name filter → {len(all_images)}")
        if dimension_filter_enabled and PIL_AVAILABLE:
            summary_parts.append(f"after dimension filter → {len(all_images)}")
        self.filter_summary_label.config(text=", ".join(summary_parts))

        # Compute per-folder filtered counts
        filtered_counts: dict[str, int] = {}
        for img in all_images:
            for folder in self.selected_folders:
                folder_str = str(folder)
                if str(img).startswith(folder_str):
                    filtered_counts[folder_str] = filtered_counts.get(folder_str, 0) + 1

        self.filter_results_tree.delete(*self.filter_results_tree.get_children())
        for folder in self.selected_folders:
            folder_str = str(folder)
            total = folder_totals.get(folder_str, 0)
            filtered = filtered_counts.get(folder_str, 0)
            self.filter_results_tree.insert(
                "",
                "end",
                values=(folder.name, total, filtered),
            )
    
    def _on_clear_selection(self) -> None:
        """Handle Clear Selection button click."""
        self.selected_images = []
        self.selected_folders = []
        self._update_display()
    
    def _update_display(self) -> None:
        """Update the display of selected images."""
        count = len(self.selected_images)
        if count == 0:
            self.images_label.config(text="No images selected")
            self.reprocess_button.config(state="disabled")
        else:
            # Show count and first few filenames
            if count == 1:
                text = f"1 image: {self.selected_images[0].name}"
            elif count <= 3:
                names = ", ".join(img.name for img in self.selected_images)
                text = f"{count} images: {names}"
            else:
                names = ", ".join(img.name for img in self.selected_images[:2])
                text = f"{count} images: {names}, ..."
            
            self.images_label.config(text=text)
            self.reprocess_button.config(state="normal")
    
    def _on_reprocess(self) -> None:
        """Handle Reprocess button click."""
        if not self.selected_images:
            logger.warning("No images selected for reprocessing")
            return
        
        # Determine which stages to apply in correct order
        stages = []
        if self.img2img_var.get():
            stages.append("img2img")
        if self.adetailer_var.get():
            stages.append("adetailer")
        if self.upscale_var.get():
            stages.append("upscale")
        
        if not stages:
            logger.warning("No stages selected for reprocessing")
            # Show user feedback
            self.images_label.config(text="⚠ Please select at least one stage")
            return
        
        # Get batch size
        batch_size = self.batch_size_var.get()
        
        # Call controller method
        if self.controller and hasattr(self.controller, "on_reprocess_images"):
            try:
                image_paths = [str(img) for img in self.selected_images]
                count = self.controller.on_reprocess_images(
                    image_paths, 
                    stages,
                    batch_size=batch_size,
                )
                logger.info(f"Submitted {count} reprocess job(s) to queue")
                
                # Show success feedback
                stage_text = " → ".join(stages)
                images_per_job = batch_size
                if batch_size == 1:
                    batch_info = f"{count} jobs (1 image each)"
                else:
                    batch_info = f"{count} jobs ({images_per_job} images/job)"
                
                self.images_label.config(
                    text=f"✓ {batch_info}: {stage_text}"
                )
                
                # Clear selection after successful submission
                self.selected_images = []
                self.selected_folders = []
                self.reprocess_button.config(state="disabled")
                
            except Exception as exc:
                logger.exception("Failed to submit reprocess jobs")
                self.images_label.config(text=f"✗ Error: {exc}")
        else:
            logger.error("Controller does not support on_reprocess_images method")
            self.images_label.config(text="✗ Controller missing reprocess support")

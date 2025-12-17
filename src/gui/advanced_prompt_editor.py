"""
Advanced Prompt Pack Editor with validation, embedding/LoRA discovery, and smart features
"""

import os
import re
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from ..utils.config import DEFAULT_GLOBAL_NEGATIVE_PROMPT
from .scrolling import make_scrollable
from .theme import (
    ASWF_BLACK,
    ASWF_DARK_GREY,
    ASWF_ERROR_RED,
    ASWF_GOLD,
    ASWF_LIGHT_GREY,
    ASWF_MED_GREY,
    ASWF_OK_GREEN,
)
from .tooltip import Tooltip


class AdvancedPromptEditor:
    """Advanced prompt pack editor with comprehensive validation and smart features"""

    def __init__(self, parent_window, config_manager, on_packs_changed=None, on_validation=None):
        self.parent = parent_window
        self.config_manager = config_manager
        self.on_packs_changed = on_packs_changed
        self.on_validation = on_validation  # Callback for validation results
        self.window = None
        self.current_pack_path = None
        self.is_modified = False

        # Model caches
        self.embeddings_cache = set()
        self.loras_cache = set()
        # Status label available immediately for tests and status updates
        try:
            self._status_var = tk.StringVar(value="Ready")
            # Create but do not pack; tests only require attribute presence and configurability
            self.status_text = ttk.Label(self.parent, textvariable=self._status_var)
        except Exception:
            # Fallback: minimal object with config() for environments without full Tk
            class _Dummy:
                def config(self, **kwargs):
                    return None

            self.status_text = _Dummy()

        # Ensure key Tk variables exist early to avoid attribute errors during load
        # These are re-bound to UI widgets later in _build_pack_info_panel
        try:
            if not hasattr(self, "pack_name_var"):
                self.pack_name_var = tk.StringVar()
            if not hasattr(self, "format_var"):
                self.format_var = tk.StringVar(value="txt")
        except Exception:
            # In environments without full Tk init, fall back to simple stand-ins
            class _Var:
                def __init__(self, value=""):
                    self._v = value

                def get(self):
                    return self._v

                def set(self, v):
                    self._v = v

            if not hasattr(self, "pack_name_var"):
                self.pack_name_var = _Var()
            if not hasattr(self, "format_var"):
                self.format_var = _Var("txt")

        # Default global negative content storage
        try:
            if self.config_manager and hasattr(self.config_manager, "get_global_negative_prompt"):
                self.global_neg_content = self.config_manager.get_global_negative_prompt()
            else:
                self.global_neg_content = DEFAULT_GLOBAL_NEGATIVE_PROMPT
        except Exception:
            self.global_neg_content = DEFAULT_GLOBAL_NEGATIVE_PROMPT

    def _attach_tooltip(self, widget: tk.Widget, text: str, delay: int = 1500) -> None:
        """Attach a tooltip to a widget when Tk is available."""
        try:
            Tooltip(widget, text, delay=delay)
        except Exception:
            pass

    def open_editor(self, pack_path=None):
        """Open the advanced prompt pack editor"""
        if self.window and self.window.winfo_exists():
            self.window.lift()
            if pack_path:
                try:
                    self._load_pack(Path(pack_path))
                except Exception:
                    pass
            return

        # Always use main Tk root as parent for Toplevel
        root = self.parent if isinstance(self.parent, tk.Tk) else self.parent.winfo_toplevel()
        self.window = tk.Toplevel(root)
        self.window.title("Advanced Prompt Pack Editor")
        self.window.geometry("1200x800")
        self.window.configure(bg=ASWF_BLACK)

        # Apply dark theme
        self._apply_dark_theme()

        # Build the UI
        self._build_advanced_ui()

        # Ensure persisted global negative and model caches are displayed
        self._refresh_global_negative_display()
        try:
            self._refresh_models()
        except Exception:
            pass

        # Load pack if specified
        if pack_path:
            self._load_pack(pack_path)
        else:
            self._new_pack()

        # Set up window close handling
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_dark_theme(self):
        """Apply consistent dark theme using ASWF colors"""
        style = ttk.Style()

        # Configure dark theme styles using ASWF colors
        style.configure("Dark.TFrame", background=ASWF_DARK_GREY)
        style.configure(
            "Dark.TLabel", background=ASWF_DARK_GREY, foreground=ASWF_GOLD
        )  # Gold text on dark background
        style.configure(
            "Dark.TButton", background=ASWF_MED_GREY, foreground="white"
        )  # White text on gray background
        style.configure(
            "Dark.TEntry",
            background=ASWF_MED_GREY,
            fieldbackground=ASWF_MED_GREY,
            foreground="white",  # White text on gray background
            insertcolor=ASWF_GOLD,
        )
        style.configure(
            "Dark.TCombobox", background=ASWF_MED_GREY, foreground="white"
        )  # White text on gray background
        style.configure("Dark.TNotebook", background=ASWF_DARK_GREY)
        style.configure(
            "Dark.TNotebook.Tab", background=ASWF_MED_GREY, foreground="white"
        )  # White text on gray background

    def _build_advanced_ui(self):
        """Build the advanced editor interface"""
        main_frame = ttk.Frame(self.window, style="Dark.TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Toolbar
        self._build_toolbar(main_frame)

        # Pack information panel
        self._build_pack_info_panel(main_frame)

        # Main content area with notebook tabs
        self._build_content_notebook(main_frame)

        # Status bar
        self._build_status_bar(main_frame)

    def _build_toolbar(self, parent):
        """Build the toolbar with all editor actions"""
        toolbar = ttk.Frame(parent, style="Dark.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 10))

        # File operations
        file_frame = ttk.LabelFrame(toolbar, text="File", style="Dark.TLabelframe")
        file_frame.pack(side=tk.LEFT, padx=(0, 10))

        new_btn = ttk.Button(file_frame, text="New", command=self._new_pack, width=10)
        new_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(new_btn, "Create a new blank prompt pack.")

        open_btn = ttk.Button(file_frame, text="Open", command=self._open_pack, width=10)
        open_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(open_btn, "Browse for an existing prompt pack to edit.")

        save_btn = ttk.Button(file_frame, text="Save", command=self._save_pack, width=10)
        save_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(save_btn, "Save changes to the currently loaded pack.")

        save_as_btn = ttk.Button(file_frame, text="Save As", command=self._save_pack_as, width=10)
        save_as_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(save_as_btn, "Save the current pack contents to a new file.")

        # Pack operations
        pack_frame = ttk.LabelFrame(toolbar, text="Pack", style="Dark.TLabelframe")
        pack_frame.pack(side=tk.LEFT, padx=(0, 10))

        clone_btn = ttk.Button(pack_frame, text="Clone Pack", command=self._clone_pack, width=12)
        clone_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(clone_btn, "Duplicate the currently loaded pack under a new name.")

        delete_btn = ttk.Button(pack_frame, text="Delete Pack", command=self._delete_pack, width=12)
        delete_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(delete_btn, "Delete the current pack file from disk.")

        # Validation operations
        validation_frame = ttk.LabelFrame(toolbar, text="Validation", style="Dark.TLabelframe")
        validation_frame.pack(side=tk.LEFT, padx=(0, 10))

        validate_btn = ttk.Button(
            validation_frame, text="Run Validation", command=self._validate_pack, width=14
        )
        validate_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(validate_btn, "Run all syntax checks on the current pack.")

        auto_fix_btn = ttk.Button(
            validation_frame, text="Auto Fix", command=self._auto_fix, width=10
        )
        auto_fix_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(auto_fix_btn, "Attempt to fix common validation issues automatically.")

        models_btn = ttk.Button(
            validation_frame, text="Refresh Models", command=self._refresh_models, width=14
        )
        models_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self._attach_tooltip(
            models_btn, "Reload available embeddings and LoRAs for validation checks."
        )

    def _build_pack_info_panel(self, parent):
        """Build pack information panel"""
        info_frame = ttk.LabelFrame(parent, text="Pack Information", style="Dark.TLabelframe")
        info_frame.pack(fill=tk.X, pady=(0, 10))

        info_grid = ttk.Frame(info_frame, style="Dark.TFrame")
        info_grid.pack(fill=tk.X, padx=10, pady=5)

        # Pack name
        ttk.Label(info_grid, text="Name:", style="Dark.TLabel").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 5)
        )
        self.pack_name_var = tk.StringVar()
        self.pack_name_entry = ttk.Entry(
            info_grid, textvariable=self.pack_name_var, width=30, style="Dark.TEntry"
        )
        self.pack_name_entry.grid(row=0, column=1, padx=(0, 20), sticky=tk.W)
        self.pack_name_entry.bind("<KeyRelease>", self._on_content_changed)

        # Format
        ttk.Label(info_grid, text="Format:", style="Dark.TLabel").grid(
            row=0, column=2, sticky=tk.W, padx=(0, 5)
        )
        self.format_var = tk.StringVar(value="txt")
        format_combo = ttk.Combobox(
            info_grid,
            textvariable=self.format_var,
            values=["txt", "tsv"],
            width=8,
            state="readonly",
            style="Dark.TCombobox",
        )
        format_combo.grid(row=0, column=3, padx=(0, 20), sticky=tk.W)
        format_combo.bind("<<ComboboxSelected>>", self._on_format_changed)

        # Statistics
        ttk.Label(info_grid, text="Stats:", style="Dark.TLabel").grid(
            row=0, column=4, sticky=tk.W, padx=(0, 5)
        )
        self.stats_label = ttk.Label(info_grid, text="0 prompts", style="Dark.TLabel")
        self.stats_label.grid(row=0, column=5, sticky=tk.W)

        # Status
        self.status_label = ttk.Label(
            info_grid, text="Ready", style="Dark.TLabel", foreground=ASWF_OK_GREEN
        )
        self.status_label.grid(row=0, column=6, padx=(20, 0), sticky=tk.E)

        # Configure grid weights
        info_grid.columnconfigure(5, weight=1)

    def _build_content_notebook(self, parent):
        """Build the main content notebook"""
        self.notebook = ttk.Notebook(parent, style="Dark.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Prompts editor tab
        self._build_prompts_tab()

        # Global negative tab
        self._build_global_negative_tab()

        # Validation results tab
        self._build_validation_tab()

        # Model browser tab
        self._build_models_tab()

        # Help tab
        self._build_help_tab()

    def _build_prompts_tab(self):
        """Build the main prompts editing tab"""
        prompts_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(prompts_frame, text="📝 Prompts")

        # Editor controls
        controls_frame = ttk.Frame(prompts_frame, style="Dark.TFrame")
        controls_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(controls_frame, text="Prompt Content:", style="Dark.TLabel").pack(side=tk.LEFT)

        # Format hint
        self.format_hint_label = ttk.Label(
            controls_frame,
            text="TXT Format: Separate prompts with blank lines",
            style="Dark.TLabel",
            foreground=ASWF_LIGHT_GREY,
        )
        self.format_hint_label.pack(side=tk.RIGHT)

        # Text editor
        editor_frame = ttk.Frame(prompts_frame, style="Dark.TFrame")
        editor_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Create text widget with scrollbars
        text_container = tk.Frame(editor_frame, bg=ASWF_BLACK)
        text_container.pack(fill=tk.BOTH, expand=True)

        # Vertical scrollbar
        v_scrollbar = tk.Scrollbar(text_container, bg=ASWF_DARK_GREY)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Horizontal scrollbar
        h_scrollbar = tk.Scrollbar(text_container, orient=tk.HORIZONTAL, bg=ASWF_DARK_GREY)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # Text widget
        self.prompts_text = tk.Text(
            text_container,
            wrap=tk.NONE,  # Allow horizontal scrolling
            bg=ASWF_BLACK,
            fg="white",
            insertbackground="white",
            selectbackground=ASWF_GOLD,
            selectforeground="white",
            font=("Consolas", 11),
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set,
            undo=True,
            maxundo=50,
        )
        self.prompts_text.pack(fill=tk.BOTH, expand=True)

        # Configure scrollbars
        v_scrollbar.config(command=self.prompts_text.yview)
        h_scrollbar.config(command=self.prompts_text.xview)

        # Bind events
        self.prompts_text.bind("<KeyRelease>", self._on_content_changed)
        self.prompts_text.bind("<Button-1>", self._on_text_click)

        # Quick insert buttons
        quick_frame = ttk.Frame(prompts_frame, style="Dark.TFrame")
        quick_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        ttk.Label(quick_frame, text="Quick Insert:", style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(0, 10)
        )

        quality_btn = ttk.Button(
            quick_frame, text="Quality Tags", command=lambda: self._insert_template("quality")
        )
        quality_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(
            quality_btn, "Insert a template of quality/clarity tags at the cursor."
        )

        style_btn = ttk.Button(
            quick_frame, text="Style Tags", command=lambda: self._insert_template("style")
        )
        style_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(
            style_btn, "Insert common style descriptors (e.g., cinematic, photorealistic)."
        )

        negative_btn = ttk.Button(
            quick_frame, text="Negative", command=lambda: self._insert_template("negative")
        )
        negative_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(
            negative_btn, "Insert a negative prompt scaffold for the current block."
        )

        lora_btn = ttk.Button(
            quick_frame, text="LoRA", command=lambda: self._insert_template("lora")
        )
        lora_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(lora_btn, "Insert a LoRA template (name and optional weight).")

        embedding_btn = ttk.Button(
            quick_frame, text="Embedding", command=lambda: self._insert_template("embedding")
        )
        embedding_btn.pack(side=tk.LEFT, padx=2)
        self._attach_tooltip(embedding_btn, "Insert an embedding placeholder.")

    def _build_global_negative_tab(self):
        """Build the global negative prompt editor"""
        global_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(global_frame, text="?? Global Negative")

        shell = ttk.Frame(global_frame, style="Dark.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        _, body = make_scrollable(shell, style="Dark.TFrame")

        # Header
        header_frame = ttk.Frame(body, style="Dark.TFrame")
        header_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(
            header_frame,
            text="Global Negative Prompt",
            style="Dark.TLabel",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            header_frame,
            text="This prompt is automatically appended to all negative prompts during generation.",
            style="Dark.TLabel",
            foreground=ASWF_LIGHT_GREY,
        ).pack(anchor=tk.W, pady=(5, 0))

        # Editor
        self.global_neg_text = scrolledtext.ScrolledText(
            body,
            wrap=tk.WORD,
            bg=ASWF_BLACK,
            fg="white",
            insertbackground="white",
            font=("Consolas", 10),
            height=15,
        )
        self.global_neg_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Load current global negative
        self.global_neg_text.delete("1.0", tk.END)
        self.global_neg_text.insert("1.0", self.global_neg_content)

        # Save button
        button_frame = ttk.Frame(body, style="Dark.TFrame")
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        save_global_btn = ttk.Button(
            button_frame, text="Save Global Negative", command=self._save_global_negative
        )
        save_global_btn.pack(side=tk.LEFT)
        self._attach_tooltip(
            save_global_btn,
            "Persist the global negative prompt so every pack you load inherits these safety terms.",
        )

        reset_global_btn = ttk.Button(
            button_frame, text="Reset to Default", command=self._reset_global_negative
        )
        reset_global_btn.pack(side=tk.LEFT, padx=(10, 0))
        self._attach_tooltip(
            reset_global_btn,
            "Restore the stock global negative prompt if your custom text causes issues.",
        )

    def _build_validation_tab(self):
        """Build the validation results tab"""
        validation_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(validation_frame, text="? Validation")

        shell = ttk.Frame(validation_frame, style="Dark.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        _, body = make_scrollable(shell, style="Dark.TFrame")

        # Validation controls
        controls_frame = ttk.Frame(body, style="Dark.TFrame")
        controls_frame.pack(fill=tk.X, padx=10, pady=10)

        run_validation_btn = ttk.Button(
            controls_frame, text="Run Validation", command=self._validate_pack
        )
        run_validation_btn.pack(side=tk.LEFT, padx=(0, 10))
        self._attach_tooltip(
            run_validation_btn,
            "Analyze the open pack for syntax, missing models, and angle bracket issues.",
        )
        auto_fix_btn = ttk.Button(controls_frame, text="Auto Fix Issues", command=self._auto_fix)
        auto_fix_btn.pack(side=tk.LEFT)
        self._attach_tooltip(
            auto_fix_btn,
            "Attempt to repair common validation problems automatically (experimental).",
        )

        # Auto-validate checkbox
        self.auto_validate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            controls_frame,
            text="Auto-validate on changes",
            variable=self.auto_validate_var,
            style="Dark.TCheckbutton",
        ).pack(side=tk.RIGHT)

        # Results display
        self.validation_text = scrolledtext.ScrolledText(
            body,
            wrap=tk.WORD,
            bg=ASWF_BLACK,
            fg="white",
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        self.validation_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Configure text tags for colored output
        self.validation_text.tag_configure("error", foreground=ASWF_ERROR_RED)
        self.validation_text.tag_configure("warning", foreground=ASWF_GOLD)
        self.validation_text.tag_configure("success", foreground=ASWF_OK_GREEN)
        self.validation_text.tag_configure("info", foreground=ASWF_GOLD)

    def _build_status_bar(self, parent):
        """Build status bar at bottom of editor window"""
        status_frame = ttk.Frame(parent, style="Dark.TFrame")
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))

        # Recreate status_text within the editor window (not parent)
        self._status_var = tk.StringVar(value="Ready")
        self.status_text = ttk.Label(
            status_frame,
            textvariable=self._status_var,
            style="Dark.TLabel",
            anchor=tk.W,
            font=("Segoe UI", 9),
        )
        self.status_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    def _build_models_tab(self):
        """Build the models browser tab"""
        models_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(models_frame, text="?? Models")

        shell = ttk.Frame(models_frame, style="Dark.TFrame")
        shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        _, body = make_scrollable(shell, style="Dark.TFrame")

        # Create paned window for embeddings and LoRAs
        paned_window = ttk.PanedWindow(body, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True)

        # Embeddings panel
        embeddings_frame = ttk.LabelFrame(paned_window, text="Embeddings", style="Dark.TLabelframe")
        paned_window.add(embeddings_frame)

        self.embeddings_listbox = tk.Listbox(
            embeddings_frame,
            bg=ASWF_MED_GREY,
            fg="white",
            selectbackground=ASWF_GOLD,
            font=("Consolas", 9),
        )
        self.embeddings_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.embeddings_listbox.bind("<Double-Button-1>", self._insert_embedding)

        # LoRAs panel
        loras_frame = ttk.LabelFrame(paned_window, text="LoRAs", style="Dark.TLabelframe")
        paned_window.add(loras_frame)

        self.loras_listbox = tk.Listbox(
            loras_frame,
            bg=ASWF_MED_GREY,
            fg="white",
            selectbackground=ASWF_GOLD,
            font=("Consolas", 9),
        )
        self.loras_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.loras_listbox.bind("<Double-Button-1>", self._insert_lora)

        # Populate lists
        self._populate_model_lists()

        # Instructions
        instructions_frame = ttk.Frame(body, style="Dark.TFrame")
        instructions_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Label(
            instructions_frame,
            text="?? Double-click to insert into prompt. Embeddings: <embedding:name>, LoRAs: <lora:name:1.0>",
            style="Dark.TLabel",
            foreground=ASWF_LIGHT_GREY,
        ).pack()

    def _build_help_tab(self):
        """Build the help tab"""
        help_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(help_frame, text="? Help")

        shell = ttk.Frame(help_frame, style="Dark.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        _, body = make_scrollable(shell, style="Dark.TFrame")

        help_text = scrolledtext.ScrolledText(
            body,
            wrap=tk.WORD,
            bg=ASWF_BLACK,
            fg="white",
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        help_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        help_content = """
ADVANCED PROMPT PACK EDITOR - HELP

📝 PROMPT FORMATS:

TXT Format (Block-based):
Each prompt block is separated by blank lines. Use 'neg:' prefix for negative prompts.

Example:
masterpiece, best quality, portrait of a woman
detailed face, beautiful eyes
neg: blurry, bad quality, distorted

landscape, mountains, sunset, golden hour
cinematic lighting, epic composition
neg: ugly, malformed, oversaturated

TSV Format (Tab-separated):
Each line: [positive prompt][TAB][negative prompt]

Example:
masterpiece, portrait	blurry, bad quality
landscape, mountains	ugly, malformed

🎭 EMBEDDINGS & LORAS:

Embeddings:
<embedding:name>
- Use exact filename without extension
- Case-sensitive
- Example: <embedding:BadDream>

LoRAs:
<lora:name:weight>
- Weight range: 0.0 to 2.0 (default: 1.0)
- Example: <lora:add-detail-xl:0.8>

🚫 GLOBAL NEGATIVE PROMPT:

The global negative prompt is automatically appended to ALL negative prompts during generation.
Edit it in the "Global Negative" tab to set safety and quality terms that apply universally.

✅ VALIDATION FEATURES:

- Missing embeddings/LoRAs detection
- Invalid syntax checking
- Weight range validation
- Blank prompt detection
- Character encoding verification
- Auto-fix common issues

🔧 KEYBOARD SHORTCUTS:

Ctrl+Z: Undo
Ctrl+Y: Redo
Ctrl+S: Save
Ctrl+N: New pack
Ctrl+O: Open pack

🔍 AUTO-VALIDATION:

Enable auto-validation to check your prompts as you type.
Errors and warnings appear in the Validation tab.

💡 TIPS:

- Use the Models tab to browse available embeddings/LoRAs
- Double-click model names to insert them automatically
- Use Quick Insert buttons for common prompt templates
- Keep prompts under 1000 characters for best performance
- Test prompts with single generations before batch processing

📁 FILE MANAGEMENT:

- Clone: Create a copy of the current pack
- Delete: Remove pack file (careful - this is permanent!)
- Auto-save: Changes are marked with * in title
- UTF-8: All files saved with proper encoding for international text

🎯 VALIDATION LEVELS:

🔴 Errors: Must be fixed (missing models, syntax errors)
🟡 Warnings: Should be reviewed (long prompts, unusual weights)
🟢 Success: Pack is valid and ready to use
"""

        help_text.config(state=tk.NORMAL)
        help_text.insert(tk.END, help_content)
        help_text.config(state=tk.DISABLED)

    def _candidate_model_roots(self) -> list[Path]:
        """Return likely Stable Diffusion WebUI roots for model discovery."""

        roots: list[Path] = []
        seen: set[str] = set()

        def add(path_like):
            if not path_like:
                return
            try:
                candidate = Path(path_like).expanduser()
            except Exception:
                return
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            key = str(resolved).lower()
            if key in seen or not resolved.exists():
                return
            seen.add(key)
            roots.append(resolved)

        # Environment overrides
        for env_var in ("STABLENEW_MODEL_ROOT", "STABLENEW_MODELS_ROOT", "WEBUI_ROOT"):
            try:
                add(os.environ.get(env_var))
            except Exception:
                continue

        # Common install locations
        add(Path.home() / "stable-diffusion-webui")
        add(Path.cwd() / "stable-diffusion-webui")
        try:
            add(Path(__file__).resolve().parents[3] / "stable-diffusion-webui")
        except Exception:
            pass

        return roots

    @staticmethod
    def _collect_model_names(directory: Path, suffixes: set[str]) -> set[str]:
        """Collect model file stems from a directory tree."""

        names: set[str] = set()
        if not directory or not directory.exists():
            return names
        try:
            for file in directory.rglob("*"):
                if file.is_file() and file.suffix.lower() in suffixes:
                    names.add(file.stem)
        except Exception:
            return names
        return names

    def _load_model_caches(self):
        """Load embeddings and LoRAs into local caches.

        Scans known WebUI folders (or overrides) so the editor can offer
        up-to-date insertion menus and validation for embeddings/LoRAs.
        """
        embedding_suffixes = {".pt", ".bin", ".ckpt", ".safetensors", ".embedding"}
        lora_suffixes = {".safetensors", ".ckpt", ".pt"}

        embeddings: set[str] = set()
        loras: set[str] = set()

        for root in self._candidate_model_roots():
            embeddings_dir_candidates = [
                root / "embeddings",
                root / "models" / "embeddings",
            ]
            for directory in embeddings_dir_candidates:
                embeddings.update(self._collect_model_names(directory, embedding_suffixes))

            lora_dir_candidates = [
                root / "loras",
                root / "models" / "Lora",
                root / "models" / "LoRA",
                root / "models" / "LORA",
                root / "models" / "lycoris",
                root / "models" / "LyCORIS",
            ]
            for directory in lora_dir_candidates:
                loras.update(self._collect_model_names(directory, lora_suffixes))

        self.embeddings_cache = embeddings
        self.loras_cache = loras

    def _refresh_global_negative_display(self):
        """Refresh the global negative text editor from stored content."""
        try:
            if self.config_manager and hasattr(self.config_manager, "get_global_negative_prompt"):
                latest = self.config_manager.get_global_negative_prompt()
                self.global_neg_content = latest
            else:
                latest = getattr(self, "global_neg_content", DEFAULT_GLOBAL_NEGATIVE_PROMPT)
            if hasattr(self, "global_neg_text") and self.global_neg_text:
                self.global_neg_text.delete("1.0", tk.END)
                self.global_neg_text.insert("1.0", latest)
        except Exception:
            # Non-fatal in headless or partial UI scenarios
            pass

    def _populate_model_lists(self):
        """Populate the embeddings and LoRAs lists"""
        if not hasattr(self, "embeddings_listbox") or not hasattr(self, "loras_listbox"):
            return
        # Clear existing items
        self.embeddings_listbox.delete(0, tk.END)
        self.loras_listbox.delete(0, tk.END)

        # Add embeddings
        for embedding in sorted(self.embeddings_cache):
            self.embeddings_listbox.insert(tk.END, embedding)

        # Add LoRAs
        for lora in sorted(self.loras_cache):
            self.loras_listbox.insert(tk.END, lora)
        # Update counts in status
        embeddings = sorted(getattr(self, "embeddings_cache", set()))
        loras = sorted(getattr(self, "loras_cache", set()))
        embed_count = len(embeddings)
        lora_count = len(loras)

        if hasattr(self, "status_text"):
            if embed_count or lora_count:
                status = f"Models: {embed_count} embeddings, {lora_count} LoRAs"
            else:
                status = "Models refreshed (none found)"
            self.status_text.config(text=status)

        if not hasattr(self, "embeddings_listbox") or not hasattr(self, "loras_listbox"):
            return

        # Clear existing items
        self.embeddings_listbox.delete(0, tk.END)
        self.loras_listbox.delete(0, tk.END)

        # Add embeddings
        for embedding in embeddings:
            self.embeddings_listbox.insert(tk.END, embedding)

        # Add LoRAs
        for lora in loras:
            self.loras_listbox.insert(tk.END, lora)

    def _refresh_models(self):
        """Refresh the model caches"""
        if hasattr(self, "status_text"):
            self.status_text.config(text="Refreshing models...")
        self._load_model_caches()
        self._populate_model_lists()

    def _insert_embedding(self, event=None):
        """Insert selected embedding into prompt"""
        selection = self.embeddings_listbox.curselection()
        if selection:
            embedding_name = self.embeddings_listbox.get(selection[0])
            self._insert_at_cursor(f"<embedding:{embedding_name}>")

    def _insert_lora(self, event=None):
        """Insert selected LoRA into prompt"""
        selection = self.loras_listbox.curselection()
        if selection:
            lora_name = self.loras_listbox.get(selection[0])
            self._insert_at_cursor(f"<lora:{lora_name}:1.0>")

    def _insert_at_cursor(self, text):
        """Insert text at current cursor position"""
        self.prompts_text.insert(tk.INSERT, text)
        self._on_content_changed()

    def _insert_template(self, template_type):
        """Insert predefined templates"""
        templates = {
            "quality": "masterpiece, best quality, 8k, high resolution, detailed",
            "style": "cinematic lighting, dramatic composition, photorealistic",
            "negative": "neg: blurry, bad quality, distorted, ugly, malformed",
            "lora": "<lora:name:1.0>",
            "embedding": "<embedding:name>",
        }

        if template_type in templates:
            self._insert_at_cursor(templates[template_type])

    def _on_format_changed(self, event=None):
        """Handle format change"""
        format_type = self.format_var.get()
        if format_type == "txt":
            self.format_hint_label.config(text="TXT Format: Separate prompts with blank lines")
        else:
            self.format_hint_label.config(
                text="TSV Format: [positive prompt][TAB][negative prompt]"
            )

        self._on_content_changed()

    def _on_content_changed(self, event=None):
        """Handle content changes"""
        if not self.is_modified:
            self.is_modified = True
            if self.current_pack_path:
                self.window.title(f"Advanced Prompt Pack Editor - {self.current_pack_path.name} *")
            else:
                self.window.title("Advanced Prompt Pack Editor - Untitled *")

        # Auto-validate if enabled
        if hasattr(self, "auto_validate_var") and self.auto_validate_var.get():
            self.window.after(1000, self._auto_validate)  # Delayed validation

    def _auto_validate(self):
        """Perform automatic validation after changes"""
        if self.is_modified:  # Only validate if still modified
            self._validate_pack_silent()

    def _on_text_click(self, event=None):
        """Handle text click for context-sensitive help"""
        # Could add context-sensitive help or suggestions here
        pass

    def _new_pack(self):
        """Create a new prompt pack"""
        if self._check_unsaved_changes():
            self.current_pack_path = None
            self.pack_name_var.set("new_pack")
            self.format_var.set("txt")
            self.prompts_text.delete("1.0", tk.END)

            # Insert template content
            template = """# New Prompt Pack
# Add your prompts here. Separate different prompts with blank lines.
# Use 'neg:' prefix for negative prompts within a block.

masterpiece, best quality, detailed artwork
beautiful composition, professional quality
neg: blurry, bad quality, distorted, ugly

portrait of a character, detailed face
expressive eyes, natural lighting
neg: malformed, bad anatomy, low quality"""

            self.prompts_text.insert("1.0", template)
            self.is_modified = False
            self.window.title("Advanced Prompt Pack Editor - New Pack")
            self._validate_pack_silent()

    def _open_pack(self):
        """Open an existing prompt pack"""
        if not self._check_unsaved_changes():
            return

        file_path = filedialog.askopenfilename(
            title="Open Prompt Pack",
            initialdir="packs",
            filetypes=[("Text files", "*.txt"), ("TSV files", "*.tsv"), ("All files", "*.*")],
        )

        if file_path:
            self._load_pack(Path(file_path))

    def _save_pack_as(self):
        """Save the current pack to a new file via dialog"""
        # Determine proposed filename
        base_name = self.pack_name_var.get().strip() or "new_pack"
        ext = (self.format_var.get() or "txt").lower()
        initial = str(Path("packs") / f"{base_name}.{ext}")

        file_path = filedialog.asksaveasfilename(
            title="Save Prompt Pack As",
            initialfile=Path(initial).name,
            initialdir="packs",
            defaultextension=f".{ext}",
            filetypes=[
                ("Text files", "*.txt"),
                ("TSV files", "*.tsv"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return
        self._save_content_to_path(Path(file_path))

    def _load_pack(self, pack_path: Path):
        """Load a prompt pack from file"""
        try:
            with open(pack_path, encoding="utf-8") as f:
                content = f.read()

            self.current_pack_path = pack_path
            # Auto-populate pack name from filename
            self.pack_name_var.set(pack_path.stem)
            self.format_var.set(pack_path.suffix[1:] if pack_path.suffix else "txt")

            self.prompts_text.delete("1.0", tk.END)
            self.prompts_text.insert("1.0", content)

            self.is_modified = False
            self.window.title(f"Advanced Prompt Pack Editor - {pack_path.name}")

            # Validate the loaded content
            self._validate_pack_silent()

            # Update format hint
            self._on_format_changed()
            # Load and display global negative if present in config
            self._refresh_global_negative_display()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load pack: {e}")

    def _save_pack(self):
        """Save the current pack (or prompt for location if untitled)"""
        if self.current_pack_path:
            self._save_content_to_path(self.current_pack_path)
        else:
            self._save_pack_as()

    def _save_content_to_path(self, path: Path):
        """Core logic to validate and save to a path"""
        try:
            content = self.prompts_text.get("1.0", tk.END).strip()

            # Validate before saving
            validation_results = self._validate_content(content)
            if validation_results["errors"]:
                if not messagebox.askyesno(
                    "Validation Errors",
                    f"Pack has {len(validation_results['errors'])} errors:\n\n"
                    f"{chr(10).join(validation_results['errors'][:3])}\n\n"
                    f"Save anyway?",
                ):
                    return

            # Ensure directory exists
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            self.current_pack_path = path
            # Update name and title
            try:
                self.pack_name_var.set(path.stem)
            except Exception:
                pass
            self.is_modified = False
            if self.window:
                self.window.title(f"Advanced Prompt Pack Editor - {path.name}")
            if hasattr(self, "_status_var"):
                self._status_var.set(f"Saved: {path.name}")

            # Notify parent of changes
            if self.on_packs_changed:
                self.on_packs_changed()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save pack: {e}")

    def _clone_pack(self):
        """Clone the current pack to a new untitled name"""
        if not self.current_pack_path:
            messagebox.showinfo("Info", "No pack loaded to clone")
            return

        original_name = (self.pack_name_var.get() or self.current_pack_path.stem).strip()
        clone_name = f"{original_name}_copy"

        # Find available name within packs directory
        ext = (
            self.format_var.get()
            or (self.current_pack_path.suffix[1:] if self.current_pack_path else "txt")
        ).lower()
        counter = 1
        while (Path("packs") / f"{clone_name}.{ext}").exists():
            clone_name = f"{original_name}_copy_{counter}"
            counter += 1

        self.pack_name_var.set(clone_name)
        self.current_pack_path = None
        self.is_modified = True
        if self.window:
            self.window.title(f"Advanced Prompt Pack Editor - {clone_name} (Clone) *")
        if hasattr(self, "_status_var"):
            self._status_var.set(f"Cloned as: {clone_name}")

    def _delete_pack(self):
        """Delete the current pack"""
        if not self.current_pack_path:
            messagebox.showinfo("Info", "No pack loaded to delete")
            return

        if messagebox.askyesno(
            "Confirm Delete",
            "This action cannot be undone.",
        ):
            try:
                deleted_name = self.current_pack_path.name
                self.current_pack_path.unlink()
                self.current_pack_path = None
                self.pack_name_var.set("")
                self.prompts_text.delete("1.0", tk.END)
                self.is_modified = False
                self.window.title("Advanced Prompt Pack Editor - Deleted")
                if hasattr(self, "status_text"):
                    self.status_text.config(text=f"Deleted: {deleted_name}")
                # Notify parent of changes
                if self.on_packs_changed:
                    self.on_packs_changed()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete pack: {e}")

    def _validate_pack(self):
        """Validate the current pack and show results"""
        content = self.prompts_text.get("1.0", tk.END).strip()
        results = self._validate_content(content)

        # Switch to validation tab
        self.notebook.select(2)  # Validation tab

        # Display results
        self._display_validation_results(results)

        # Call validation callback if present
        if self.on_validation:
            self.on_validation(results)

        return results

    def _validate_pack_silent(self):
        """Validate pack without switching tabs"""
        content = self.prompts_text.get("1.0", tk.END).strip()
        results = self._validate_content(content)

        # Update status and stats
        self._update_status_from_validation(results)

        return results

    def _validate_content(self, content: str) -> dict:
        """Validate pack content and return comprehensive results"""
        results = {
            "errors": [],
            "warnings": [],
            "info": [],
            "stats": {
                "prompt_count": 0,
                "embedding_count": 0,
                "lora_count": 0,
                "total_chars": len(content),
                "avg_prompt_length": 0,
            },
        }

        if not content.strip():
            results["errors"].append("Pack is empty")
            return results

        # Determine format and validate accordingly
        is_tsv = self.format_var.get() == "tsv"

        if is_tsv:
            self._validate_tsv_content(content, results)
        else:
            self._validate_txt_content(content, results)

        # Calculate average prompt length
        if results["stats"]["prompt_count"] > 0:
            results["stats"]["avg_prompt_length"] = (
                results["stats"]["total_chars"] / results["stats"]["prompt_count"]
            )

        return results

    def _validate_tsv_content(self, content: str, results: dict):
        """Validate TSV format content"""
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split("\t")
            if len(parts) < 1:
                results["errors"].append(f"Line {i}: Empty line")
                continue

            positive = parts[0].strip()
            if not positive:
                results["warnings"].append(f"Line {i}: Empty positive prompt")
            else:
                self._validate_prompt_text(positive, f"Line {i} (positive)", results)

            if len(parts) > 1:
                negative = parts[1].strip()
                if negative:
                    self._validate_prompt_text(negative, f"Line {i} (negative)", results)

            results["stats"]["prompt_count"] += 1

    def _validate_txt_content(self, content: str, results: dict):
        """Validate TXT format content"""
        blocks = content.split("\n\n")
        block_num = 0

        for block in blocks:
            block = block.strip()
            if not block or all(
                line.startswith("#") for line in block.splitlines() if line.strip()
            ):
                continue

            block_num += 1
            lines = [line.strip() for line in block.splitlines()]
            lines = [line for line in lines if line and not line.startswith("#")]

            if not lines:
                results["warnings"].append(f"Block {block_num}: Empty block")
                continue

            positive_parts = []
            negative_parts = []

            for line in lines:
                if line.startswith("neg:"):
                    neg_content = line[4:].strip()
                    if neg_content:
                        negative_parts.append(neg_content)
                        self._validate_prompt_text(
                            neg_content, f"Block {block_num} (negative)", results
                        )
                else:
                    positive_parts.append(line)
                    self._validate_prompt_text(line, f"Block {block_num} (positive)", results)

            if not positive_parts:
                results["warnings"].append(f"Block {block_num}: No positive prompt content")

            results["stats"]["prompt_count"] += 1

    def _validate_prompt_text(self, prompt: str, location: str, results: dict):
        """Validate individual prompt text"""
        # Check embeddings
        embedding_pattern = re.compile(r"<embedding:([^>]+)>", flags=re.IGNORECASE)
        embeddings = embedding_pattern.findall(prompt)
        embedding_cache = {e.lower() for e in getattr(self, "embeddings_cache", set())}

        for embedding in embeddings:
            name = embedding.strip()
            results["stats"]["embedding_count"] += 1

            if embedding_cache and name.lower() not in embedding_cache:
                results["errors"].append(f"{location}: Unknown embedding '{name}'")
            else:
                results["info"].append(f"{location}: Found embedding '{name}'")

        # Check LoRAs
        lora_pattern = re.compile(r"<lora:([^:>]+)(?::([^>]+))?>", flags=re.IGNORECASE)
        loras = lora_pattern.findall(prompt)
        lora_cache = {entry.lower() for entry in getattr(self, "loras_cache", set())}

        for lora_name, weight in loras:
            name = lora_name.strip()
            results["stats"]["lora_count"] += 1

            if lora_cache and name.lower() not in lora_cache:
                results["errors"].append(f"{location}: Unknown LoRA '{name}'")
            else:
                results["info"].append(f"{location}: Found LoRA '{name}'")

            if weight:
                try:
                    weight_val = float(weight)
                    if not (0.0 <= weight_val <= 2.0):
                        results["warnings"].append(
                            f"{location}: LoRA weight {weight_val} outside recommended range (0.0-2.0)"
                        )
                    elif weight_val == 0.0:
                        results["warnings"].append(
                            f"{location}: LoRA weight is 0.0 - this will have no effect"
                        )
                except ValueError:
                    results["errors"].append(
                        f"{location}: Invalid LoRA weight '{weight}' - must be a number"
                    )
            else:
                results["info"].append(f"{location}: LoRA '{name}' using default weight (1.0)")

        # Check for common syntax errors
        if "<<" in prompt or ">>" in prompt:
            results["warnings"].append(
                f"{location}: Double angle brackets found - did you mean single brackets?"
            )

        token_pattern = re.compile(r"<[A-Za-z0-9_]+:[^<>]+>")
        sanitized = token_pattern.sub("", prompt)
        sanitized = re.sub(r"<\s*>", "", sanitized)

        if sanitized.count("<") != sanitized.count(">"):
            results["errors"].append(f"{location}: Mismatched angle brackets")

        # Check for very long prompts
        if len(prompt) > 1000:
            results["warnings"].append(
                f"{location}: Very long prompt ({len(prompt)} chars) - may cause issues"
            )

        # Check for suspicious patterns
        if re.search(r"<[^>]*[<>][^>]*>", sanitized):
            results["errors"].append(f"{location}: Nested angle brackets detected")

        # Check for common typos in tags
        common_typos = {
            "masterpeice": "masterpiece",
            "hight quality": "high quality",
            "beatiful": "beautiful",
            "photorealstic": "photorealistic",
        }

        for typo, correction in common_typos.items():
            if typo in prompt.lower():
                results["warnings"].append(
                    f"{location}: Possible typo '{typo}' - did you mean '{correction}'?"
                )

    def _display_validation_results(self, results: dict):
        """Display validation results in the validation tab"""
        self.validation_text.config(state=tk.NORMAL)
        self.validation_text.delete("1.0", tk.END)

        # Summary
        total_issues = len(results["errors"]) + len(results["warnings"])
        if total_issues == 0:
            self.validation_text.insert(tk.END, "✅ VALIDATION PASSED\n\n", "success")
            self.validation_text.insert(
                tk.END, "No issues found. Pack is ready for use!\n\n", "success"
            )
        else:
            if results["errors"]:
                self.validation_text.insert(
                    tk.END, f"❌ {len(results['errors'])} ERRORS FOUND\n", "error"
                )
                for error in results["errors"]:
                    self.validation_text.insert(tk.END, f"  • {error}\n", "error")
                self.validation_text.insert(tk.END, "\n")

            if results["warnings"]:
                self.validation_text.insert(
                    tk.END, f"⚠️ {len(results['warnings'])} WARNINGS\n", "warning"
                )
                for warning in results["warnings"]:
                    self.validation_text.insert(tk.END, f"  • {warning}\n", "warning")
                self.validation_text.insert(tk.END, "\n")

        # Statistics
        stats = results["stats"]
        self.validation_text.insert(tk.END, "📊 STATISTICS\n", "info")
        self.validation_text.insert(tk.END, f"  • Prompts: {stats['prompt_count']}\n", "info")
        self.validation_text.insert(tk.END, f"  • Embeddings: {stats['embedding_count']}\n", "info")
        self.validation_text.insert(tk.END, f"  • LoRAs: {stats['lora_count']}\n", "info")
        self.validation_text.insert(
            tk.END, f"  • Total characters: {stats['total_chars']}\n", "info"
        )
        if stats["avg_prompt_length"] > 0:
            self.validation_text.insert(
                tk.END,
                f"  • Average prompt length: {stats['avg_prompt_length']:.0f} chars\n",
                "info",
            )

        # Information messages
        if results["info"]:
            self.validation_text.insert(
                tk.END, f"\n💡 INFO ({len(results['info'])} items)\n", "info"
            )
            # Only show first few info messages to avoid clutter
            for info in results["info"][:10]:
                self.validation_text.insert(tk.END, f"  • {info}\n", "info")
            if len(results["info"]) > 10:
                self.validation_text.insert(
                    tk.END, f"  • ... and {len(results['info']) - 10} more\n", "info"
                )

        self.validation_text.config(state=tk.DISABLED)

    def _update_status_from_validation(self, results: dict):
        """Update status labels from validation results"""
        stats = results["stats"]

        # Update stats label
        self.stats_label.config(
            text=f"{stats['prompt_count']} prompts, {stats['embedding_count']} embeddings, {stats['lora_count']} LoRAs"
        )

        # Update status label
        if results["errors"]:
            self.status_label.config(
                text=f"{len(results['errors'])} errors", foreground=ASWF_ERROR_RED
            )
        elif results["warnings"]:
            self.status_label.config(
                text=f"{len(results['warnings'])} warnings", foreground="#ffa726"
            )
        else:
            self.status_label.config(text="Valid", foreground="#66bb6a")

    def _auto_fix(self):
        """Automatically fix common issues"""
        content = self.prompts_text.get("1.0", tk.END)
        original_content = content

        fixes_applied = []

        # Fix double angle brackets
        if "<<" in content or ">>" in content:
            content = content.replace("<<", "<").replace(">>", ">")
            fixes_applied.append("Fixed double angle brackets")

        # Fix missing colons in LoRA syntax
        # Pattern: <lora name> -> <lora:name>
        lora_fixes = re.sub(r"<lora\s+([^:>]+)>", r"<lora:\1>", content)
        if lora_fixes != content:
            content = lora_fixes
            fixes_applied.append("Added missing colons to LoRA syntax")

        # Fix missing weights in LoRA syntax (add default 1.0)
        weight_fixes = re.sub(r"<lora:([^:>]+)>", r"<lora:\1:1.0>", content)
        if weight_fixes != content:
            content = weight_fixes
            fixes_applied.append("Added default weights to LoRAs")

        # Normalize whitespace
        lines = content.splitlines()
        cleaned_lines = []
        for line in lines:
            # Normalize internal whitespace but preserve leading/trailing for formatting
            if line.strip():
                # Remove multiple spaces within content but preserve single spaces
                cleaned_line = re.sub(r" +", " ", line.strip())
                cleaned_lines.append(cleaned_line)
            else:
                cleaned_lines.append("")  # Keep blank lines for formatting

        content = "\n".join(cleaned_lines)

        # Remove excessive blank lines (more than 2 consecutive)
        content = re.sub(r"\n{3,}", "\n\n", content)
        fixes_applied.append("Normalized whitespace")

        # Fix common typos
        typo_fixes = {
            "masterpeice": "masterpiece",
            "hight quality": "high quality",
            "beatiful": "beautiful",
            "photorealstic": "photorealistic",
        }

        for typo, correction in typo_fixes.items():
            if typo in content.lower():
                # Case-insensitive replacement
                content = re.sub(re.escape(typo), correction, content, flags=re.IGNORECASE)
                fixes_applied.append(f"Fixed typo: {typo} → {correction}")

        # Apply fixes if any were made
        if content != original_content:
            self.prompts_text.delete("1.0", tk.END)
            self.prompts_text.insert("1.0", content)
            self._on_content_changed()

            # Show results
            messagebox.showinfo(
                "Auto-Fix Complete",
                f"Applied {len(fixes_applied)} fixes:\n\n"
                + "\n".join(f"• {fix}" for fix in fixes_applied),
            )

            # Re-validate
            self._validate_pack_silent()
        else:
            messagebox.showinfo("Auto-Fix", "No fixable issues found.")

    def _save_global_negative(self):
        """Save the global negative prompt"""
        try:
            content = self.global_neg_text.get("1.0", tk.END).strip()
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to read global negative: {exc}")
            return

        persisted = True
        if self.config_manager and hasattr(self.config_manager, "save_global_negative_prompt"):
            persisted = self.config_manager.save_global_negative_prompt(content)

        if not persisted:
            messagebox.showerror("Error", "Failed to save global negative prompt to disk.")
            return

        self.global_neg_content = content
        if hasattr(self, "_status_var"):
            self._status_var.set("Global negative prompt updated")
        messagebox.showinfo("Success", "Global negative prompt has been updated.")

    def _reset_global_negative(self):
        """Reset global negative to default"""
        default_neg = DEFAULT_GLOBAL_NEGATIVE_PROMPT
        persisted = True
        if self.config_manager and hasattr(self.config_manager, "save_global_negative_prompt"):
            persisted = self.config_manager.save_global_negative_prompt(default_neg)

        if not persisted:
            messagebox.showerror("Error", "Failed to restore default global negative prompt.")
            return

        self.global_neg_content = default_neg
        self._refresh_global_negative_display()
        if hasattr(self, "_status_var"):
            self._status_var.set("Global negative reset to default")

    def _check_unsaved_changes(self):
        """Check for unsaved changes and prompt user"""
        if self.is_modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes", "You have unsaved changes. Save them before continuing?"
            )
            if result is True:  # Yes, save
                self._save_pack()
                return not self.is_modified  # Return True if save succeeded
            elif result is False:  # No, don't save
                return True
            else:  # Cancel
                return False
        return True

    def _on_close(self):
        """Handle window close event"""
        if self._check_unsaved_changes():
            self.window.destroy()
            self.window = None


class AdvancedPromptEditorV2(ttk.Frame):
    """Lightweight advanced prompt editor for GUI V2."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        initial_prompt: str = "",
        initial_negative_prompt: str | None = None,
        on_apply: Callable[[str, str | None], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_apply = on_apply
        self.on_cancel = on_cancel

        self.prompt_text = tk.Text(self, height=10, wrap="word")
        self.prompt_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 3))
        if initial_prompt:
            self.prompt_text.insert("1.0", initial_prompt)

        self.negative_prompt_text: tk.Text | None
        if initial_negative_prompt is not None:
            self.negative_prompt_text = tk.Text(self, height=6, wrap="word")
            self.negative_prompt_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 3))
            if initial_negative_prompt:
                self.negative_prompt_text.insert("1.0", initial_negative_prompt)
        else:
            self.negative_prompt_text = None

        controls = ttk.Frame(self)
        controls.pack(fill=tk.X, pady=(0, 6), padx=6)

        self.apply_button = ttk.Button(controls, text="Apply", command=self._handle_apply)
        self.apply_button.pack(side=tk.LEFT, padx=(0, 4))

        self.cancel_button = ttk.Button(controls, text="Cancel", command=self._handle_cancel)
        self.cancel_button.pack(side=tk.LEFT, padx=(0, 4))

        self.clear_button = ttk.Button(controls, text="Clear", command=self._handle_clear)
        self.clear_button.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value=self._build_status_text())
        ttk.Label(self, textvariable=self.status_var).pack(anchor=tk.E, padx=6, pady=(0, 6))

        self.prompt_text.bind("<<Modified>>", self._handle_prompt_modified)
        if self.negative_prompt_text is not None:
            self.negative_prompt_text.bind("<<Modified>>", self._handle_prompt_modified)

    def _build_status_text(self) -> str:
        prompt_len = len(self.prompt_text.get("1.0", tk.END).strip())
        if self.negative_prompt_text is not None:
            neg_len = len(self.negative_prompt_text.get("1.0", tk.END).strip())
            return f"Prompt: {prompt_len} chars • Negative: {neg_len} chars"
        return f"Prompt: {prompt_len} chars"

    def _handle_prompt_modified(self, event) -> None:
        widget = event.widget
        try:
            widget.edit_modified(False)
        except Exception:
            pass
        self.status_var.set(self._build_status_text())

    def _handle_apply(self) -> None:
        if self.on_apply:
            prompt_value = self.prompt_text.get("1.0", tk.END).strip()
            negative_value = None
            if self.negative_prompt_text is not None:
                negative_value = self.negative_prompt_text.get("1.0", tk.END).strip()
            try:
                self.on_apply(prompt_value, negative_value)
            except Exception:
                pass

    def _handle_cancel(self) -> None:
        if self.on_cancel:
            try:
                self.on_cancel()
            except Exception:
                pass

    def _handle_clear(self) -> None:
        self.prompt_text.delete("1.0", tk.END)
        if self.negative_prompt_text is not None:
            self.negative_prompt_text.delete("1.0", tk.END)
        self.status_var.set(self._build_status_text())

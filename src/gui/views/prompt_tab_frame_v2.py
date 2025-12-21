"""Prompt Tab Frame v2.6 - Main prompt editing interface with matrix integration.

v2.6 Changes:
- Integrated full Advanced Prompt Pack Editor v2.6 replacing lightweight version
- Advanced editor now provides file operations, validation, model discovery
- Enhanced workflow for comprehensive pack editing and management

Main component for prompt pack editing with slot management, matrix configuration,
LoRA/embedding pickers, and real-time preview.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.simpledialog
from tkinter import filedialog, messagebox, ttk

from src.config.app_config import STABLENEW_WEBUI_ROOT
from src.gui.app_state_v2 import AppStateV2
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.scrolling import enable_mousewheel
from src.gui.theme_v2 import BODY_LABEL_STYLE, SURFACE_FRAME_STYLE
from src.gui.tooltip import attach_tooltip
from src.gui.widgets.embedding_picker_panel import EmbeddingPickerPanel
from src.gui.widgets.lora_picker_panel import LoRAPickerPanel
from src.gui.widgets.matrix_helper_widget import MatrixHelperDialog
from src.utils.prompt_txt_parser import parse_prompt_txt_to_components, parse_multi_slot_txt


class PromptTabFrame(ttk.Frame):
    def apply_prompt_pack(self, summary) -> None:
        """Apply a PromptPackSummary to the prompt editor fields."""
        if not summary:
            return
        # Update positive prompt
        if hasattr(self, "editor") and hasattr(summary, "prompt"):
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", getattr(summary, "prompt", ""))
        # Update negative prompt if present
        if hasattr(self, "negative_editor") and hasattr(summary, "negative_prompt"):
            self.negative_editor.delete("1.0", "end")
            self.negative_editor.insert("1.0", getattr(summary, "negative_prompt", ""))

    """Prompt tab with slot selection, editor, and metadata preview."""

    def __init__(
        self, master: tk.Misc, app_state: AppStateV2 | None = None, *args, **kwargs
    ) -> None:
        super().__init__(master, *args, **kwargs)
        self.workspace_state = PromptWorkspaceState()
        self.app_state = app_state
        self.workspace_state.new_pack("Untitled", slot_count=10)
        if self.app_state is not None:
            try:
                self.app_state.prompt_workspace_state = self.workspace_state
            except Exception:
                pass
        self.workspace_state.set_current_slot_index(0)
        self._suppress_editor_change = False
        
        # Autocomplete for [[slot]] insertion
        self._autocomplete_list: tk.Listbox | None = None
        self._autocomplete_trigger_pos: str | None = None
        
        # Validation state
        self._undefined_slots: set[str] = set()

        self.columnconfigure(0, weight=1, uniform="prompt_col")
        self.columnconfigure(1, weight=2, uniform="prompt_col")
        self.columnconfigure(2, weight=1, uniform="prompt_col")
        self.rowconfigure(0, weight=1)

        self.left_frame = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.center_frame = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.right_frame = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)

        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=4)
        self.center_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        self.right_frame.grid(row=0, column=2, sticky="nsew", padx=(4, 0), pady=4)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()
        self._refresh_editor()
        self._refresh_metadata()

    # Left column -------------------------------------------------------
    def _build_left_panel(self) -> None:
        """Build pack manager and slot list panels.
        
        v2.6: Comprehensive pack management with load, clone, delete, rename, validate.
        """
        # Pack Manager Section (top)
        pack_header = ttk.Label(self.left_frame, text="Pack Manager", style=BODY_LABEL_STYLE)
        pack_header.pack(anchor="w")
        
        # Pack management buttons
        pack_btn_frame = ttk.Frame(self.left_frame)
        pack_btn_frame.pack(fill="x", pady=(4, 2))
        ttk.Button(pack_btn_frame, text="New", command=self._on_new_pack, width=6).pack(side="left", padx=(0, 2))
        ttk.Button(pack_btn_frame, text="Load", command=self._on_load_selected_pack, width=6).pack(side="left", padx=(0, 2))
        ttk.Button(pack_btn_frame, text="Save", command=self._on_save_pack, width=6).pack(side="left")
        
        pack_btn_frame2 = ttk.Frame(self.left_frame)
        pack_btn_frame2.pack(fill="x", pady=(2, 6))
        ttk.Button(pack_btn_frame2, text="Clone", command=self._on_clone_pack, width=6).pack(side="left", padx=(0, 2))
        ttk.Button(pack_btn_frame2, text="Rename", command=self._on_rename_pack, width=6).pack(side="left", padx=(0, 2))
        ttk.Button(pack_btn_frame2, text="Delete", command=self._on_delete_pack, width=6).pack(side="left", padx=(0, 2))
        ttk.Button(pack_btn_frame2, text="Validate", command=self._on_validate_pack, width=7).pack(side="left")
        
        # Pack list
        self.pack_listbox = tk.Listbox(
            self.left_frame, 
            exportselection=False, 
            height=8,
            bg="#1E1E1E",
            fg="#FFFFFF",
            selectbackground="#FFC805",
            selectforeground="#000000",
            highlightthickness=0,
            borderwidth=0
        )
        self.pack_listbox.pack(fill="both", expand=False, pady=(0, 8))
        self.pack_listbox.bind("<Double-Button-1>", lambda e: self._on_load_selected_pack())
        enable_mousewheel(self.pack_listbox)
        self._refresh_pack_list()
        
        # Slot List Section (bottom)
        ttk.Separator(self.left_frame, orient="horizontal").pack(fill="x", pady=(0, 8))
        
        slot_header = ttk.Label(self.left_frame, text="Prompt Slots", style=BODY_LABEL_STYLE)
        slot_header.pack(anchor="w")

        self.slot_list = tk.Listbox(
            self.left_frame, 
            exportselection=False, 
            height=10,
            bg="#1E1E1E",
            fg="#FFFFFF",
            selectbackground="#FFC805",
            selectforeground="#000000",
            highlightthickness=0,
            borderwidth=0
        )
        for i in range(10):
            self.slot_list.insert("end", f"Prompt {i + 1}")
        self.slot_list.selection_set(0)
        self.slot_list.bind("<<ListboxSelect>>", self._on_slot_select)
        self.slot_list.pack(fill="both", expand=True, pady=(2, 4))
        enable_mousewheel(self.slot_list)

        # Slot management buttons
        slot_mgmt_frame = ttk.Frame(self.left_frame)
        slot_mgmt_frame.pack(fill="x", pady=(0, 4))
        ttk.Button(slot_mgmt_frame, text="Add Slot", command=self._on_add_slot).pack(side="left", padx=(0, 2), expand=True, fill="x")
        ttk.Button(slot_mgmt_frame, text="Copy", command=self._on_copy_slot).pack(side="left", padx=(0, 2), expand=True, fill="x")
        ttk.Button(slot_mgmt_frame, text="Delete", command=self._on_delete_slot).pack(side="left", expand=True, fill="x")
        attach_tooltip(self.slot_list, "Select a prompt slot to edit or apply.")

    # Center column -----------------------------------------------------
    def _build_center_panel(self) -> None:
        # Header frame
        header_frame = ttk.Frame(self.center_frame)
        header_frame.pack(fill="x", pady=(0, 4))
        self.pack_name_label = ttk.Label(header_frame, text="Editor", style=BODY_LABEL_STYLE)
        self.pack_name_label.pack(side="left")

        # Notebook for Prompts vs Matrix tabs
        self.editor_notebook = ttk.Notebook(self.center_frame)
        self.editor_notebook.pack(fill="both", expand=True)

        # Prompts tab
        self.prompts_tab = ttk.Frame(self.editor_notebook)
        self.editor_notebook.add(self.prompts_tab, text="Prompts")
        self._build_prompts_tab()

        # Matrix tab
        from src.gui.widgets.matrix_tab_panel import MatrixTabPanel

        self.matrix_tab_panel = MatrixTabPanel(
            self.editor_notebook,
            workspace_state=self.workspace_state,
            on_matrix_changed=self._on_matrix_changed,
        )
        self.editor_notebook.add(self.matrix_tab_panel, text="Matrix")

    def _build_prompts_tab(self) -> None:
        """Build positive and negative prompt editors in Prompts tab."""
        # Configure grid layout for split view
        self.prompts_tab.rowconfigure(1, weight=3)  # positive editor row
        self.prompts_tab.rowconfigure(3, weight=1)  # negative editor row
        self.prompts_tab.rowconfigure(5, weight=1)  # LoRA/embedding panels row
        self.prompts_tab.columnconfigure(0, weight=1)
        self.prompts_tab.columnconfigure(1, weight=1)

        # Positive prompt header (row 0)
        positive_header = ttk.Frame(self.prompts_tab)
        positive_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        ttk.Label(positive_header, text="Positive Prompt", style=BODY_LABEL_STYLE).pack(
            side="left"
        )
        
        # Quick insert buttons frame (updated dynamically)
        self.positive_quick_insert_frame = ttk.Frame(positive_header)
        self.positive_quick_insert_frame.pack(side="right", padx=(0, 5))
        
        ttk.Button(
            positive_header,
            text="Insert Slot...",
            command=self._insert_slot_into_positive,
        ).pack(side="right")

        # Positive prompt editor (row 1)
        self.editor = tk.Text(
            self.prompts_tab, 
            height=8, 
            wrap="word",
            bg="#1E1E1E",
            fg="#FFFFFF",
            insertbackground="#FFC805",
            selectbackground="#FFC805",
            selectforeground="#000000",
            highlightthickness=0,
            borderwidth=1,
            relief="solid"
        )
        self.editor.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 6))
        self.editor.bind("<<Modified>>", self._on_editor_modified)
        self.editor.bind("<KeyRelease>", self._on_positive_key_release)
        self.editor.bind("<Escape>", lambda e: self._hide_autocomplete())
        self.editor.bind("<FocusOut>", lambda e: self._hide_autocomplete())
        enable_mousewheel(self.editor)
        attach_tooltip(self.editor, "Main prompt text for txt2img/img2img runs. Type [[ for slot autocomplete.")
        
        # Configure tag for matrix token highlighting (darker yellow for dark mode)
        self.editor.tag_config("matrix_token", background="#4A4A2A", foreground="#FFD700")

        # Negative prompt header (row 2)
        negative_header = ttk.Frame(self.prompts_tab)
        negative_header.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        ttk.Label(negative_header, text="Negative Prompt", style=BODY_LABEL_STYLE).pack(
            side="left"
        )
        
        # Quick insert buttons frame (updated dynamically)
        self.negative_quick_insert_frame = ttk.Frame(negative_header)
        self.negative_quick_insert_frame.pack(side="right", padx=(0, 5))
        
        ttk.Button(
            negative_header,
            text="Insert Slot...",
            command=self._insert_slot_into_negative,
        ).pack(side="right")

        # Negative prompt editor (row 3)
        self.negative_editor = tk.Text(
            self.prompts_tab, 
            height=4, 
            wrap="word",
            bg="#1E1E1E",
            fg="#FFFFFF",
            insertbackground="#FFC805",
            selectbackground="#FFC805",
            selectforeground="#000000",
            highlightthickness=0,
            borderwidth=1,
            relief="solid"
        )
        self.negative_editor.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 6))
        self.negative_editor.bind("<<Modified>>", self._on_negative_modified)
        self.negative_editor.bind("<KeyRelease>", self._on_negative_key_release)
        self.negative_editor.bind("<Escape>", lambda e: self._hide_autocomplete())
        self.negative_editor.bind("<FocusOut>", lambda e: self._hide_autocomplete())
        enable_mousewheel(self.negative_editor)
        attach_tooltip(self.negative_editor, "Negative prompt to exclude unwanted elements. Type [[ for slot autocomplete.")
        
        # Configure tag for matrix token highlighting (darker yellow for dark mode)
        self.negative_editor.tag_config("matrix_token", background="#4A4A2A", foreground="#FFD700")

        # Separator (row 4)
        ttk.Separator(self.prompts_tab, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=6
        )

        # LoRA picker panel (row 5, column 0)
        self.lora_picker = LoRAPickerPanel(
            self.prompts_tab,
            on_change_callback=self._on_loras_changed,
            webui_root=STABLENEW_WEBUI_ROOT or None
        )
        self.lora_picker.grid(row=5, column=0, sticky="nsew", padx=(0, 3))
        
        # Override keyword insertion to insert into prompt editor
        self.lora_picker._insert_keywords_to_prompt = self._insert_keywords_to_prompt

        # Embedding picker panel (row 5, column 1)
        self.embedding_picker = EmbeddingPickerPanel(
            self.prompts_tab,
            on_change_callback=self._on_embeddings_changed,
            webui_root=STABLENEW_WEBUI_ROOT or None
        )
        self.embedding_picker.grid(row=5, column=1, sticky="nsew", padx=(3, 0))

    # Right column ------------------------------------------------------
    def _build_right_panel(self) -> None:
        self.summary_label = ttk.Label(
            self.right_frame, text="Current Slot Summary", style=BODY_LABEL_STYLE
        )
        self.summary_label.pack(anchor="w", pady=(0, 6))

        self.meta_text = tk.Text(
            self.right_frame, 
            height=12, 
            wrap="word", 
            state="disabled",
            bg="#1E1E1E",
            fg="#FFFFFF",
            highlightthickness=0,
            borderwidth=1,
            relief="solid"
        )
        self.meta_text.pack(fill="both", expand=True)

    # Event handlers / helpers ------------------------------------------
    def _on_new_pack(self) -> None:
        """Create a new pack with default preset settings.
        
        v2.6: New packs now use default.json preset settings for companion JSON file.
        """
        if self.workspace_state.dirty:
            proceed = messagebox.askyesno(
                "Unsaved Changes", "Discard unsaved changes and create a new pack?"
            )
            if not proceed:
                return
        
        # Ask for pack name
        import tkinter.simpledialog as simpledialog
        pack_name = simpledialog.askstring("New Pack", "Enter pack name:", initialvalue="Untitled")
        if not pack_name:
            return
        
        # Create new pack
        self.workspace_state.new_pack(pack_name, slot_count=10)
        
        # Load default preset settings into the pack
        try:
            from pathlib import Path
            import json
            
            default_preset_path = Path("presets") / "default.json"
            if default_preset_path.exists():
                with open(default_preset_path, "r", encoding="utf-8") as f:
                    default_preset = json.load(f)
                
                # Apply default preset to current pack
                if hasattr(self.workspace_state.current_pack, 'preset_data'):
                    self.workspace_state.current_pack.preset_data = default_preset
                    self.workspace_state.mark_dirty()
        except Exception:
            pass  # Continue even if default preset loading fails
        
        self.workspace_state.set_current_slot_index(0)
        self.slot_list.selection_clear(0, "end")
        self.slot_list.selection_set(0)
        self._refresh_editor()
        self._refresh_metadata()
        self._refresh_pack_list()
        self.pack_name_label.config(text=f"Editor - {pack_name}")

    def _on_slot_select(self, _event=None) -> None:
        try:
            sel = self.slot_list.curselection()
            if not sel:
                return
            self.workspace_state.set_current_slot_index(int(sel[0]))
            self._refresh_editor()
            self._refresh_metadata()
        except Exception:
            pass

    def _refresh_editor(self) -> None:
        slot = self.workspace_state.get_slot(self.workspace_state.get_current_slot_index())
        self._suppress_editor_change = True
        try:
            # Update positive editor
            self.editor.delete("1.0", "end")
            if slot.text:
                self.editor.insert("1.0", slot.text)
            self.editor.edit_modified(False)

            # Update negative editor
            self.negative_editor.delete("1.0", "end")
            negative = getattr(slot, "negative", "")
            if negative:
                self.negative_editor.insert("1.0", negative)
            self.negative_editor.edit_modified(False)

            # Update LoRA picker
            if hasattr(self, "lora_picker"):
                loras = getattr(slot, "loras", [])
                self.lora_picker.set_loras(loras)

            # Update embedding picker
            if hasattr(self, "embedding_picker"):
                pos_embeds = getattr(slot, "positive_embeddings", [])
                neg_embeds = getattr(slot, "negative_embeddings", [])
                self.embedding_picker.set_positive_embeddings(pos_embeds)
                self.embedding_picker.set_negative_embeddings(neg_embeds)

            # Refresh matrix tab if it exists
            if hasattr(self, "matrix_tab_panel"):
                self.matrix_tab_panel.refresh()
            
            # Apply highlighting and update quick insert buttons
            self._highlight_matrix_tokens()
            self._update_quick_insert_buttons()
            self._validate_matrix_slots()
        finally:
            self._suppress_editor_change = False

    def _on_editor_modified(self, _event=None) -> None:
        if self._suppress_editor_change:
            self.editor.edit_modified(False)
            return
        if not self.editor.edit_modified():
            return
        text = self.editor.get("1.0", "end").rstrip("\n")
        try:
            self.workspace_state.set_slot_text(self.workspace_state.get_current_slot_index(), text)
            # keep UI indicator in sync
            self.pack_name_label.config(
                text=f"Editor - {self.workspace_state.current_pack.name if self.workspace_state.current_pack else 'None'} (modified)"
            )
        except Exception:
            pass
        self.editor.edit_modified(False)
        self._highlight_matrix_tokens()
        self._validate_matrix_slots()
        self._refresh_metadata()

    def _on_negative_modified(self, _event=None) -> None:
        """Handle edits to negative prompt editor."""
        if self._suppress_editor_change:
            self.negative_editor.edit_modified(False)
            return
        if not self.negative_editor.edit_modified():
            return
        negative_text = self.negative_editor.get("1.0", "end").rstrip("\n")
        try:
            self.workspace_state.set_slot_negative(
                self.workspace_state.get_current_slot_index(),
                negative_text
            )
            # Update UI indicator
            self.pack_name_label.config(
                text=f"Editor - {self.workspace_state.current_pack.name if self.workspace_state.current_pack else 'None'} (modified)"
            )
        except Exception:
            pass
        self.negative_editor.edit_modified(False)
        self._highlight_matrix_tokens()
        self._validate_matrix_slots()
        self._refresh_metadata()

    def _on_loras_changed(self) -> None:
        """Handle changes to LoRA picker."""
        if self._suppress_editor_change:
            return
        try:
            loras = self.lora_picker.get_loras()
            self.workspace_state.set_slot_loras(
                self.workspace_state.get_current_slot_index(),
                loras
            )
            # Mark dirty
            self.pack_name_label.config(
                text=f"Editor - {self.workspace_state.current_pack.name if self.workspace_state.current_pack else 'None'} (modified)"
            )
        except Exception:
            pass
        self._refresh_metadata()

    def _on_embeddings_changed(self) -> None:
        """Handle changes to embedding picker."""
        if self._suppress_editor_change:
            return
        try:
            pos_embeds = self.embedding_picker.get_positive_embeddings()
            neg_embeds = self.embedding_picker.get_negative_embeddings()
            self.workspace_state.set_slot_embeddings(
                self.workspace_state.get_current_slot_index(),
                pos_embeds,
                neg_embeds
            )
            # Mark dirty
            self.pack_name_label.config(
                text=f"Editor - {self.workspace_state.current_pack.name if self.workspace_state.current_pack else 'None'} (modified)"
            )
        except Exception:
            pass
        self._refresh_metadata()
    
    def _insert_keywords_to_prompt(self, keywords: str) -> None:
        """Insert LoRA keywords into the positive prompt editor at cursor position."""
        try:
            self.editor.insert("insert", keywords)
            self._on_editor_modified()
        except Exception:
            pass

    def _refresh_metadata(self) -> None:
        """Refresh metadata/preview panel with full prompt preview."""
        pack = self.workspace_state.current_pack
        slot_index = self.workspace_state.get_current_slot_index()
        
        # Get current slot data
        current_slot = self.workspace_state.get_current_slot() if pack else None
        if not current_slot:
            self.meta_text.config(state="normal")
            self.meta_text.delete("1.0", "end")
            self.meta_text.insert("1.0", "No pack loaded")
            self.meta_text.config(state="disabled")
            return
        
        # Get matrix config
        matrix_config = self.workspace_state.get_matrix_config()
        
        # Build preview sections
        dirty = " (modified)" if self.workspace_state.dirty else ""
        preview_lines = [
            f"Pack: {pack.name if pack else 'None'}{dirty}",
            f"Slot: {slot_index + 1}",
            "",
            "━━━ FULL PROMPT PREVIEW ━━━",
            ""
        ]
        
        # Show matrix slots if defined
        if matrix_config and matrix_config.slots:
            preview_lines.append("Matrix Slots:")
            for slot in matrix_config.slots:
                values_preview = ", ".join(slot.values[:3])
                if len(slot.values) > 3:
                    values_preview += f"... ({len(slot.values)} total)"
                preview_lines.append(f"  [[{slot.name}]]: {values_preview}")
            preview_lines.append("")
        
        # Positive embeddings
        if current_slot.positive_embeddings:
            for emb_name in current_slot.positive_embeddings:
                preview_lines.append(f"<embedding:{emb_name}>")
        
        # Positive prompt
        positive_text = current_slot.text.strip()
        if positive_text:
            preview_lines.append(positive_text)
        else:
            preview_lines.append("(no positive prompt)")
        
        # LoRAs
        if current_slot.loras:
            lora_line_parts = []
            for lora_name, lora_weight in current_slot.loras:
                lora_line_parts.append(f"<lora:{lora_name}:{lora_weight}>")
            preview_lines.append(" ".join(lora_line_parts))
        
        preview_lines.append("")
        
        # Negative embeddings
        if current_slot.negative_embeddings:
            for emb_name in current_slot.negative_embeddings:
                preview_lines.append(f"neg: <embedding:{emb_name}>")
        
        # Negative prompt
        negative_text = current_slot.negative.strip()
        if negative_text:
            preview_lines.append(f"neg: {negative_text}")
        else:
            preview_lines.append("neg: (none)")
        
        # Global negative (if available from app_state)
        if self.app_state and hasattr(self.app_state, "global_negative_prompt"):
            global_neg = getattr(self.app_state, "global_negative_prompt", "")
            if global_neg and global_neg.strip():
                preview_lines.append("")
                preview_lines.append("Global Negative (appended):")
                preview_lines.append(f"  {global_neg.strip()}")
        
        preview_lines.extend([
            "",
            "━━━ STATISTICS ━━━",
            f"Positive: {len(positive_text)} chars",
            f"Negative: {len(negative_text)} chars",
            f"LoRAs: {len(current_slot.loras)}",
            f"Pos Embeddings: {len(current_slot.positive_embeddings)}",
            f"Neg Embeddings: {len(current_slot.negative_embeddings)}",
        ])
        
        if matrix_config and matrix_config.slots:
            valid_slots = [s for s in matrix_config.slots if s.name and s.values]
            if valid_slots:
                # Calculate total combinations
                from itertools import product
                total_combinations = 1
                for slot in valid_slots:
                    total_combinations *= len(slot.values)
                preview_lines.append(f"Matrix Combinations: {total_combinations}")

        self.meta_text.config(state="normal")
        self.meta_text.delete("1.0", "end")
        self.meta_text.insert("1.0", "\n".join(preview_lines))
        self.meta_text.config(state="disabled")

    def _open_matrix_helper(self) -> None:
        dialog = MatrixHelperDialog(self, on_apply=self._insert_matrix_expression)
        dialog.grab_set()
        dialog.wait_window(dialog)

    # Pack Management Functions (v2.6) ----------------------------------
    
    def _refresh_pack_list(self) -> None:
        """Refresh the list of available packs from the packs directory."""
        from pathlib import Path
        
        self.pack_listbox.delete(0, "end")
        
        packs_dir = Path("packs")
        if not packs_dir.exists():
            packs_dir.mkdir(parents=True, exist_ok=True)
            return
        
        # Find all TXT files in packs directory
        txt_files = sorted(packs_dir.glob("*.txt"))
        for txt_file in txt_files:
            self.pack_listbox.insert("end", txt_file.stem)
    
    def _on_load_selected_pack(self) -> None:
        """Load the selected pack from the pack list."""
        selection = self.pack_listbox.curselection()
        if not selection:
            messagebox.showinfo("Load Pack", "Please select a pack to load.")
            return
        
        pack_name = self.pack_listbox.get(selection[0])
        from pathlib import Path
        
        txt_path = Path("packs") / f"{pack_name}.txt"
        if not txt_path.exists():
            messagebox.showerror("Load Pack", f"Pack file not found: {txt_path}")
            return
        
        # Use the same logic as _on_open_pack
        try:
            # Read TXT file
            with open(txt_path, "r", encoding="utf-8") as f:
                txt_content = f.read()

            # Parse into multiple slots
            all_components = parse_multi_slot_txt(txt_content)

            if not all_components:
                messagebox.showwarning("Load Pack", "No valid prompts found in file.")
                return

            # Check for companion JSON
            json_path = txt_path.with_suffix(".json")
            if json_path.exists():
                self.workspace_state.load_pack(str(json_path))
            else:
                self.workspace_state.new_pack(pack_name, slot_count=len(all_components))

            # Populate slots from TXT
            for index, components in enumerate(all_components):
                if index < len(self.workspace_state.current_pack.slots):
                    slot = self.workspace_state.get_slot(index)
                    slot.text = components.positive_text
                    slot.negative = components.negative_text
                    slot.positive_embeddings = components.positive_embeddings
                    slot.negative_embeddings = components.negative_embeddings
                    slot.loras = components.loras

            self._refresh_slot_list()
            self.workspace_state.set_current_slot_index(0)
            self.slot_list.selection_clear(0, "end")
            self.slot_list.selection_set(0)
            self._refresh_editor()
            self._refresh_metadata()
            
            self.pack_name_label.config(text=f"Editor - {pack_name}")
            
        except Exception as e:
            messagebox.showerror("Load Pack", f"Failed to load pack:\\n{str(e)}")
    
    def _on_clone_pack(self) -> None:
        """Clone the selected pack with a new name."""
        selection = self.pack_listbox.curselection()
        if not selection:
            messagebox.showinfo("Clone Pack", "Please select a pack to clone.")
            return
        
        pack_name = self.pack_listbox.get(selection[0])
        new_name = tk.simpledialog.askstring("Clone Pack", f"Clone '{pack_name}' as:", initialvalue=f"{pack_name}_copy")
        
        if not new_name:
            return
        
        from pathlib import Path
        import shutil
        
        src_txt = Path("packs") / f"{pack_name}.txt"
        src_json = Path("packs") / f"{pack_name}.json"
        dest_txt = Path("packs") / f"{new_name}.txt"
        dest_json = Path("packs") / f"{new_name}.json"
        
        if dest_txt.exists():
            messagebox.showerror("Clone Pack", f"Pack '{new_name}' already exists.")
            return
        
        try:
            # Copy TXT file
            if src_txt.exists():
                shutil.copy2(src_txt, dest_txt)
            
            # Copy JSON file if it exists
            if src_json.exists():
                shutil.copy2(src_json, dest_json)
            
            self._refresh_pack_list()
            messagebox.showinfo("Clone Pack", f"Pack cloned successfully as '{new_name}'.")
        except Exception as e:
            messagebox.showerror("Clone Pack", f"Failed to clone pack:\\n{str(e)}")
    
    def _on_rename_pack(self) -> None:
        """Rename the selected pack."""
        selection = self.pack_listbox.curselection()
        if not selection:
            messagebox.showinfo("Rename Pack", "Please select a pack to rename.")
            return
        
        old_name = self.pack_listbox.get(selection[0])
        new_name = tk.simpledialog.askstring("Rename Pack", f"Rename '{old_name}' to:", initialvalue=old_name)
        
        if not new_name or new_name == old_name:
            return
        
        from pathlib import Path
        
        old_txt = Path("packs") / f"{old_name}.txt"
        old_json = Path("packs") / f"{old_name}.json"
        new_txt = Path("packs") / f"{new_name}.txt"
        new_json = Path("packs") / f"{new_name}.json"
        
        if new_txt.exists():
            messagebox.showerror("Rename Pack", f"Pack '{new_name}' already exists.")
            return
        
        try:
            # Rename TXT file
            if old_txt.exists():
                old_txt.rename(new_txt)
            
            # Rename JSON file if it exists
            if old_json.exists():
                old_json.rename(new_json)
            
            self._refresh_pack_list()
            messagebox.showinfo("Rename Pack", f"Pack renamed to '{new_name}'.")
        except Exception as e:
            messagebox.showerror("Rename Pack", f"Failed to rename pack:\\n{str(e)}")
    
    def _on_delete_pack(self) -> None:
        """Delete the selected pack."""
        selection = self.pack_listbox.curselection()
        if not selection:
            messagebox.showinfo("Delete Pack", "Please select a pack to delete.")
            return
        
        pack_name = self.pack_listbox.get(selection[0])
        
        if not messagebox.askyesno("Delete Pack", f"Are you sure you want to delete '{pack_name}'?\\nThis cannot be undone."):
            return
        
        from pathlib import Path
        
        txt_path = Path("packs") / f"{pack_name}.txt"
        json_path = Path("packs") / f"{pack_name}.json"
        
        try:
            # Delete TXT file
            if txt_path.exists():
                txt_path.unlink()
            
            # Delete JSON file if it exists
            if json_path.exists():
                json_path.unlink()
            
            self._refresh_pack_list()
            messagebox.showinfo("Delete Pack", f"Pack '{pack_name}' deleted successfully.")
        except Exception as e:
            messagebox.showerror("Delete Pack", f"Failed to delete pack:\\n{str(e)}")
    
    def _on_validate_pack(self) -> None:
        """Validate the selected pack for errors."""
        selection = self.pack_listbox.curselection()
        if not selection:
            messagebox.showinfo("Validate Pack", "Please select a pack to validate.")
            return
        
        pack_name = self.pack_listbox.get(selection[0])
        
        from pathlib import Path
        import re
        
        txt_path = Path("packs") / f"{pack_name}.txt"
        json_path = Path("packs") / f"{pack_name}.json"
        
        errors = []
        warnings = []
        
        # Check if files exist
        if not txt_path.exists():
            errors.append(f"TXT file not found: {txt_path}")
        
        try:
            # Validate TXT content
            if txt_path.exists():
                with open(txt_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Check for empty file
                if not content.strip():
                    errors.append("TXT file is empty")
                
                # Check for [[tokens]] without defined matrix slots
                matrix_tokens = re.findall(r'\[\[([^\]]+)\]\]', content)
                if matrix_tokens and not json_path.exists():
                    warnings.append(f"Found {len(set(matrix_tokens))} matrix tokens but no JSON file")
                
                # Check for LoRA/embedding syntax
                lora_pattern = r'<lora:([^:>]+)(?::([^>]+))?>'
                loras = re.findall(lora_pattern, content)
                for lora_name, weight in loras:
                    if weight:
                        try:
                            w = float(weight)
                            if w < 0 or w > 2:
                                warnings.append(f"LoRA '{lora_name}' has unusual weight: {w}")
                        except ValueError:
                            errors.append(f"LoRA '{lora_name}' has invalid weight: {weight}")
            
            # Validate JSON content
            if json_path.exists():
                import json
                with open(json_path, "r", encoding="utf-8") as f:
                    json_data = json.load(f)
                
                # Check matrix configuration
                matrix_config = json_data.get("matrix_config", {})
                if matrix_config.get("enabled"):
                    slots = matrix_config.get("slots", [])
                    if not slots:
                        warnings.append("Matrix enabled but no slots defined")
                    else:
                        for slot in slots:
                            if not slot.get("name"):
                                errors.append("Matrix slot missing name")
                            if not slot.get("values"):
                                warnings.append(f"Matrix slot '{slot.get('name', '?')}' has no values")
            
            # Display results
            if errors:
                result_msg = "❌ ERRORS FOUND:\\n\\n" + "\\n".join(f"• {e}" for e in errors)
                if warnings:
                    result_msg += "\\n\\n⚠️ WARNINGS:\\n\\n" + "\\n".join(f"• {w}" for w in warnings)
                messagebox.showerror("Validation Failed", result_msg)
            elif warnings:
                result_msg = "⚠️ WARNINGS:\\n\\n" + "\\n".join(f"• {w}" for w in warnings)
                messagebox.showwarning("Validation Warnings", result_msg)
            else:
                messagebox.showinfo("Validation Passed", f"✓ Pack '{pack_name}' is valid!\\n\\nNo errors or warnings found.")
        
        except Exception as e:
            messagebox.showerror("Validation Error", f"Failed to validate pack:\\n{str(e)}")

    def apply_prompt_text(self, prompt: str) -> None:
        text = prompt or ""
        try:
            index = self.workspace_state.get_current_slot_index()
            self.workspace_state.set_slot_text(index, text)
        except Exception:
            pass
        self._refresh_editor()
        self._refresh_metadata()

    def _insert_matrix_expression(self, expression: str) -> None:
        try:
            self.editor.insert("insert", expression)
            self._on_editor_modified()
        except Exception:
            pass

    def _on_open_pack(self) -> None:
        """Open a prompt pack from TXT file (and load companion JSON if available)."""
        path = filedialog.askopenfilename(
            title="Open Prompt Pack",
            filetypes=[("Text Files", "*.txt"), ("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        
        from pathlib import Path
        file_path = Path(path)
        
        try:
            # If user selected TXT, parse it and look for companion JSON
            if file_path.suffix.lower() == ".txt":
                # Read TXT file
                with open(file_path, "r", encoding="utf-8") as f:
                    txt_content = f.read()

                # Parse into multiple slots
                all_components = parse_multi_slot_txt(txt_content)

                if not all_components:
                    messagebox.showwarning("Open Prompt Pack", "No valid prompts found in file.")
                    return

                # Check for companion JSON (for matrix config)
                json_path = file_path.with_suffix(".json")
                if json_path.exists():
                    # Load the full pack from JSON (gets matrix, etc.)
                    self.workspace_state.load_pack(str(json_path))
                else:
                    # Create new pack from TXT only
                    pack_name = file_path.stem
                    self.workspace_state.new_pack(pack_name, slot_count=len(all_components))

                # Populate slots from TXT (overwrites JSON slot content)
                for index, components in enumerate(all_components):
                    if index < len(self.workspace_state.current_pack.slots):
                        slot = self.workspace_state.get_slot(index)
                        slot.text = components.positive_text
                        slot.negative = components.negative_text
                        slot.positive_embeddings = components.positive_embeddings
                        slot.negative_embeddings = components.negative_embeddings
                        slot.loras = components.loras

                # Update slot list
                self._refresh_slot_list()
                self.workspace_state.set_current_slot_index(0)
                self.slot_list.selection_clear(0, "end")
                self.slot_list.selection_set(0)
                self.workspace_state.mark_dirty()
                self._refresh_editor()
                self._refresh_metadata()

            else:
                # User selected JSON directly - load normally
                self.workspace_state.load_pack(path)
                self.workspace_state.set_current_slot_index(0)
                self.slot_list.selection_clear(0, "end")
                self.slot_list.selection_set(0)
                self._refresh_editor()
                self._refresh_metadata()
                
        except Exception as exc:
            messagebox.showerror("Open Prompt Pack", f"Failed to open pack:\n{exc}")

    def _on_save_pack(self) -> None:
        pack = self.workspace_state.current_pack
        if pack is None:
            return
        path = pack.path
        if not path:
            return self._on_save_pack_as()
        try:
            self.workspace_state.save_current_pack()
            self._refresh_metadata()
            self._refresh_pack_list()  # v2.6: Update pack list after save
        except Exception as exc:
            messagebox.showerror("Save Prompt Pack", f"Failed to save pack:\n{exc}")

    def _on_save_pack_as(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save Prompt Pack As",
            defaultextension=".json",
            filetypes=[("Prompt Packs", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            self.workspace_state.save_current_pack_as(path)
            self._refresh_metadata()
            self._refresh_pack_list()  # v2.6: Update pack list after save
        except Exception as exc:
            messagebox.showerror("Save Prompt Pack As", f"Failed to save pack:\n{exc}")

    def _on_load_from_txt(self) -> None:
        """Load a .txt pack file and parse it into multiple slots."""
        path = filedialog.askopenfilename(
            title="Load Prompt from TXT",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not path:
            return

        try:
            # Read TXT file
            with open(path, "r", encoding="utf-8") as f:
                txt_content = f.read()

            # Parse into multiple slots
            all_components = parse_multi_slot_txt(txt_content)

            if not all_components:
                messagebox.showwarning("Load from TXT", "No valid prompts found in file.")
                return

            # Adjust pack to have correct number of slots
            current_slot_count = len(self.workspace_state.current_pack.slots)
            needed_slot_count = len(all_components)

            if needed_slot_count > current_slot_count:
                # Add more slots
                for _ in range(needed_slot_count - current_slot_count):
                    self.workspace_state.add_slot()
            elif needed_slot_count < current_slot_count:
                # Remove excess slots
                for _ in range(current_slot_count - needed_slot_count):
                    self.workspace_state.remove_slot(len(self.workspace_state.current_pack.slots) - 1)

            # Populate each slot
            for index, components in enumerate(all_components):
                slot = self.workspace_state.get_slot(index)
                slot.text = components.positive_text
                slot.negative = components.negative_text
                slot.positive_embeddings = components.positive_embeddings
                slot.negative_embeddings = components.negative_embeddings
                slot.loras = components.loras

            # Update slot list display
            self._refresh_slot_list()

            # Mark dirty and refresh UI to first slot
            self.workspace_state.set_current_slot_index(0)
            self.slot_list.selection_clear(0, "end")
            self.slot_list.selection_set(0)
            self.workspace_state.mark_dirty()
            self._refresh_editor()
            self._refresh_metadata()

            # Show confirmation
            total_loras = sum(len(c.loras) for c in all_components)
            total_embeds = sum(
                len(c.positive_embeddings) + len(c.negative_embeddings)
                for c in all_components
            )
            messagebox.showinfo(
                "Load from TXT",
                f"Loaded {len(all_components)} slot(s) from TXT:\n"
                f"  {total_loras} total LoRA(s)\n"
                f"  {total_embeds} total embedding(s)"
            )
        except Exception as exc:
            messagebox.showerror("Load from TXT", f"Failed to load TXT:\n{exc}")

    def _insert_slot_into_positive(self) -> None:
        """Open slot picker and insert [[slot_name]] into positive editor."""
        matrix_config = self.workspace_state.get_matrix_config()
        if not matrix_config.slots:
            messagebox.showinfo("No Slots", "Define matrix slots in the Matrix tab first.")
            return

        from src.gui.widgets.matrix_slot_picker import MatrixSlotPickerDialog

        def on_select(slot_name: str):
            self.editor.insert("insert", f"[[{slot_name}]]")
            self._on_editor_modified(None)  # Mark dirty

        MatrixSlotPickerDialog(
            self,
            available_slots=matrix_config.get_slot_names(),
            on_select=on_select,
        )

    def _insert_slot_into_negative(self) -> None:
        """Open slot picker and insert [[slot_name]] into negative editor."""
        matrix_config = self.workspace_state.get_matrix_config()
        if not matrix_config.slots:
            messagebox.showinfo("No Slots", "Define matrix slots in the Matrix tab first.")
            return

        from src.gui.widgets.matrix_slot_picker import MatrixSlotPickerDialog

        def on_select(slot_name: str):
            self.negative_editor.insert("insert", f"[[{slot_name}]]")
            self._on_negative_modified(None)  # Mark dirty

        MatrixSlotPickerDialog(
            self,
            available_slots=matrix_config.get_slot_names(),
            on_select=on_select,
        )

    def _on_matrix_changed(self) -> None:
        """Called when matrix config changes in Matrix tab."""
        self.workspace_state.mark_dirty()
        # Update quick insert buttons when matrix slots change
        self._update_quick_insert_buttons()
        self._validate_matrix_slots()

    # Matrix Integration Features -----------------------------------
    
    def _on_positive_key_release(self, event) -> None:
        """Handle key release in positive editor for autocomplete."""
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            if self._autocomplete_list and self._autocomplete_list.winfo_viewable():
                self._handle_autocomplete_nav(event, self.editor)
            return
        
        # Check if user typed [[ - check both cursor positions (after second [ or at second [)
        try:
            cursor_pos = self.editor.index("insert")
            line, col = map(int, cursor_pos.split("."))
            
            # First try: check if we're right after [[
            if col >= 2:
                prev_chars = self.editor.get(f"{line}.{col-2}", f"{line}.{col}")
                if prev_chars == "[[":
                    self._show_autocomplete(self.editor)
                    return
            
            # Second try: check if we're at the position of second [ (immediately after typing it)
            if col >= 1:
                check_chars = self.editor.get(f"{line}.{col-1}", f"{line}.{col+1}")
                if check_chars == "[[":
                    # Move cursor to after [[
                    self.editor.mark_set("insert", f"{line}.{col+1}")
                    self._show_autocomplete(self.editor)
                    return
        except Exception:
            pass
        
        # Hide autocomplete if still visible
        if self._autocomplete_list and self._autocomplete_list.winfo_viewable():
            self._hide_autocomplete()
    
    def _on_negative_key_release(self, event) -> None:
        """Handle key release in negative editor for autocomplete."""
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            if self._autocomplete_list and self._autocomplete_list.winfo_viewable():
                self._handle_autocomplete_nav(event, self.negative_editor)
            return
        
        # Check if user typed [[ - check both cursor positions (after second [ or at second [)
        try:
            cursor_pos = self.negative_editor.index("insert")
            line, col = map(int, cursor_pos.split("."))
            
            # First try: check if we're right after [[
            if col >= 2:
                prev_chars = self.negative_editor.get(f"{line}.{col-2}", f"{line}.{col}")
                if prev_chars == "[[":
                    self._show_autocomplete(self.negative_editor)
                    return
            
            # Second try: check if we're at the position of second [ (immediately after typing it)
            if col >= 1:
                check_chars = self.negative_editor.get(f"{line}.{col-1}", f"{line}.{col+1}")
                if check_chars == "[[":
                    # Move cursor to after [[
                    self.negative_editor.mark_set("insert", f"{line}.{col+1}")
                    self._show_autocomplete(self.negative_editor)
                    return
        except Exception:
            pass
        
        # Hide autocomplete if still visible
        if self._autocomplete_list and self._autocomplete_list.winfo_viewable():
            self._hide_autocomplete()
    
    def _show_autocomplete(self, editor: tk.Text) -> None:
        """Show autocomplete dropdown with available matrix slots."""
        matrix_config = self.workspace_state.get_matrix_config()
        if not matrix_config.slots:
            return
        
        slot_names = matrix_config.get_slot_names()
        if not slot_names:
            return
        
        # Store trigger position (should be right after [[)
        cursor_pos = editor.index("insert")
        self._autocomplete_trigger_pos = cursor_pos
        
        # Create or update listbox
        if self._autocomplete_list is None:
            self._autocomplete_list = tk.Listbox(
                editor,
                height=min(8, len(slot_names)),
                width=20,
                exportselection=False,
                bg="#1E1E1E",
                fg="#FFFFFF",
                selectbackground="#FFC805",
                selectforeground="#000000",
                highlightthickness=1,
                highlightbackground="#2A2A2A",
                borderwidth=0
            )
            self._autocomplete_list.bind("<<ListboxSelect>>", lambda e: self._on_autocomplete_select(editor))
            self._autocomplete_list.bind("<Double-Button-1>", lambda e: self._on_autocomplete_select(editor))
            self._autocomplete_list.bind("<Return>", lambda e: self._on_autocomplete_select(editor))
            self._autocomplete_list.bind("<Escape>", lambda e: self._hide_autocomplete())
        
        # Populate
        self._autocomplete_list.delete(0, "end")
        for name in slot_names:
            self._autocomplete_list.insert("end", name)
        
        # Position below cursor
        try:
            bbox = editor.bbox("insert")
            if bbox:
                x, y, width, height = bbox
                self._autocomplete_list.place(x=x, y=y + height, width=200)
            else:
                # Fallback if bbox unavailable (e.g., in tests)
                self._autocomplete_list.place(x=0, y=20, width=200)
            self._autocomplete_list.lift()
            self._autocomplete_list.selection_set(0)
        except Exception:
            # Even if placement fails, make it visible at default position
            self._autocomplete_list.place(x=0, y=20, width=200)
            self._autocomplete_list.selection_set(0)
    
    def _hide_autocomplete(self) -> None:
        """Hide autocomplete dropdown."""
        if self._autocomplete_list:
            self._autocomplete_list.place_forget()
            self._autocomplete_trigger_pos = None
    
    def _handle_autocomplete_nav(self, event, editor: tk.Text) -> None:
        """Handle Up/Down/Return in autocomplete list."""
        if not self._autocomplete_list:
            return
        
        if event.keysym == "Down":
            current = self._autocomplete_list.curselection()
            if current:
                idx = current[0]
                if idx < self._autocomplete_list.size() - 1:
                    self._autocomplete_list.selection_clear(idx)
                    self._autocomplete_list.selection_set(idx + 1)
                    self._autocomplete_list.see(idx + 1)
        elif event.keysym == "Up":
            current = self._autocomplete_list.curselection()
            if current:
                idx = current[0]
                if idx > 0:
                    self._autocomplete_list.selection_clear(idx)
                    self._autocomplete_list.selection_set(idx - 1)
                    self._autocomplete_list.see(idx - 1)
        elif event.keysym == "Return":
            self._on_autocomplete_select(editor)
    
    def _on_autocomplete_select(self, editor: tk.Text) -> None:
        """Insert selected slot name and close autocomplete."""
        if not self._autocomplete_list:
            return
        
        selection = self._autocomplete_list.curselection()
        if not selection:
            return
        
        slot_name = self._autocomplete_list.get(selection[0])
        
        # Find the correct insertion position
        # The trigger position should be right after [[, but verify
        if self._autocomplete_trigger_pos:
            line, col = map(int, self._autocomplete_trigger_pos.split("."))
            # Check if we're right after [[
            if col >= 2:
                check_text = editor.get(f"{line}.{col-2}", f"{line}.{col}")
                if check_text == "[[":
                    # Good, we're right after [[
                    insert_pos = self._autocomplete_trigger_pos
                else:
                    # We might be AT the second [, check one position forward
                    check_text2 = editor.get(f"{line}.{col-1}", f"{line}.{col+1}")
                    if check_text2 == "[[":
                        # We're between the brackets, move forward one
                        insert_pos = f"{line}.{col+1}"
                    else:
                        # Just use current position
                        insert_pos = self._autocomplete_trigger_pos
            else:
                insert_pos = self._autocomplete_trigger_pos
        else:
            insert_pos = "insert"
        
        # Insert slot name
        editor.insert(insert_pos, f"{slot_name}]]")
        
        # Move cursor to end of inserted text
        if self._autocomplete_trigger_pos:
            line, col = map(int, insert_pos.split("."))
            new_pos = f"{line}.{col + len(slot_name) + 2}"  # +2 for ]]
            editor.mark_set("insert", new_pos)
        
        # Trigger modified event
        if editor == self.editor:
            self._on_editor_modified()
        else:
            self._on_negative_modified()
        
        self._hide_autocomplete()
        editor.focus_set()
    
    def _highlight_matrix_tokens(self) -> None:
        """Apply visual highlighting to [[tokens]] in both editors."""
        import re
        
        # Pattern for [[token_name]]
        pattern = re.compile(r'\[\[([^\]]+)\]\]')
        
        # Highlight in positive editor
        self.editor.tag_remove("matrix_token", "1.0", "end")
        text = self.editor.get("1.0", "end")
        for match in pattern.finditer(text):
            start_idx = f"1.0 + {match.start()} chars"
            end_idx = f"1.0 + {match.end()} chars"
            self.editor.tag_add("matrix_token", start_idx, end_idx)
        
        # Highlight in negative editor
        self.negative_editor.tag_remove("matrix_token", "1.0", "end")
        neg_text = self.negative_editor.get("1.0", "end")
        for match in pattern.finditer(neg_text):
            start_idx = f"1.0 + {match.start()} chars"
            end_idx = f"1.0 + {match.end()} chars"
            self.negative_editor.tag_add("matrix_token", start_idx, end_idx)
    
    def _update_quick_insert_buttons(self) -> None:
        """Update quick insert buttons for matrix slots."""
        if not hasattr(self, "positive_quick_insert_frame"):
            return
        
        # Clear existing buttons
        for widget in self.positive_quick_insert_frame.winfo_children():
            widget.destroy()
        for widget in self.negative_quick_insert_frame.winfo_children():
            widget.destroy()
        
        # Get current slots
        matrix_config = self.workspace_state.get_matrix_config()
        if not matrix_config.slots:
            return
        
        slot_names = matrix_config.get_slot_names()
        
        # Limit to first 5 slots for space
        for slot_name in slot_names[:5]:
            # Positive button
            btn_pos = ttk.Button(
                self.positive_quick_insert_frame,
                text=f"[[{slot_name}]]",
                width=12,
                command=lambda s=slot_name: self._quick_insert_slot(self.editor, s),
            )
            btn_pos.pack(side="left", padx=2)
            
            # Negative button
            btn_neg = ttk.Button(
                self.negative_quick_insert_frame,
                text=f"[[{slot_name}]]",
                width=12,
                command=lambda s=slot_name: self._quick_insert_slot(self.negative_editor, s),
            )
            btn_neg.pack(side="left", padx=2)
    
    def _quick_insert_slot(self, editor: tk.Text, slot_name: str) -> None:
        """Insert [[slot_name]] at cursor position."""
        editor.insert("insert", f"[[{slot_name}]]")
        if editor == self.editor:
            self._on_editor_modified()
        else:
            self._on_negative_modified()
        editor.focus_set()
    
    def _validate_matrix_slots(self) -> None:
        """Check for undefined [[tokens]] and show warnings."""
        import re
        
        pattern = re.compile(r'\[\[([^\]]+)\]\]')
        matrix_config = self.workspace_state.get_matrix_config()
        defined_slots = set(matrix_config.get_slot_names())
        
        # Find all used tokens
        positive_text = self.editor.get("1.0", "end")
        negative_text = self.negative_editor.get("1.0", "end")
        
        used_slots = set()
        for match in pattern.finditer(positive_text):
            used_slots.add(match.group(1))
        for match in pattern.finditer(negative_text):
            used_slots.add(match.group(1))
        
        # Find undefined slots
        self._undefined_slots = used_slots - defined_slots
        
        # Update metadata display with warnings
        if self._undefined_slots:
            self._show_validation_warning()
    
    def _show_validation_warning(self) -> None:
        """Show visual indicator for undefined slots (non-blocking)."""
        if not self._undefined_slots:
            return
        
        # Update pack name label with warning indicator
        pack_name = self.workspace_state.current_pack.name if self.workspace_state.current_pack else "None"
        dirty = " (modified)" if self.workspace_state.dirty else ""
        warning = f" ⚠️ Undefined slots: {', '.join(sorted(self._undefined_slots))}"
        
        self.pack_name_label.config(
            text=f"Editor - {pack_name}{dirty}{warning}",
            foreground="#d9534f"  # Bootstrap danger color
        )
        
        # Reset color after 3 seconds
        self.after(3000, lambda: self.pack_name_label.config(foreground=""))

    # Slot Management Methods ---------------------------------------

    def _refresh_slot_list(self) -> None:
        """Refresh the slot list display."""
        self.slot_list.delete(0, "end")
        for i in range(len(self.workspace_state.current_pack.slots)):
            self.slot_list.insert("end", f"Prompt {i + 1}")

    def _on_add_slot(self) -> None:
        """Add a new empty slot."""
        try:
            self.workspace_state.add_slot()
            self._refresh_slot_list()
            # Select the new slot
            new_index = len(self.workspace_state.current_pack.slots) - 1
            self.slot_list.selection_clear(0, "end")
            self.slot_list.selection_set(new_index)
            self.workspace_state.set_current_slot_index(new_index)
            self._refresh_editor()
            self._refresh_metadata()
        except Exception as exc:
            messagebox.showerror("Add Slot", f"Failed to add slot:\n{exc}")

    def _on_copy_slot(self) -> None:
        """Copy the current slot."""
        try:
            current_index = self.workspace_state.get_current_slot_index()
            self.workspace_state.copy_slot(current_index)
            self._refresh_slot_list()
            # Select the new copy
            new_index = current_index + 1
            self.slot_list.selection_clear(0, "end")
            self.slot_list.selection_set(new_index)
            self.workspace_state.set_current_slot_index(new_index)
            self._refresh_editor()
            self._refresh_metadata()
        except Exception as exc:
            messagebox.showerror("Copy Slot", f"Failed to copy slot:\n{exc}")

    def _on_delete_slot(self) -> None:
        """Delete the current slot."""
        try:
            if len(self.workspace_state.current_pack.slots) <= 1:
                messagebox.showwarning("Delete Slot", "Cannot delete the last slot.")
                return

            current_index = self.workspace_state.get_current_slot_index()
            proceed = messagebox.askyesno(
                "Delete Slot",
                f"Are you sure you want to delete Prompt {current_index + 1}?"
            )
            if not proceed:
                return

            self.workspace_state.remove_slot(current_index)
            self._refresh_slot_list()

            # Select previous slot or first
            new_index = max(0, current_index - 1)
            self.slot_list.selection_clear(0, "end")
            self.slot_list.selection_set(new_index)
            self.workspace_state.set_current_slot_index(new_index)
            self._refresh_editor()
            self._refresh_metadata()
        except Exception as exc:
            messagebox.showerror("Delete Slot", f"Failed to delete slot:\n{exc}")
        self.pack_name_label.config(
            text=f"Editor - {self.workspace_state.current_pack.name if self.workspace_state.current_pack else 'None'} (modified)"
        )


PromptTabFrame = PromptTabFrame

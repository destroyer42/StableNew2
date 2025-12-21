from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import simpledialog, ttk
from typing import Any

from src.gui.scrolling import enable_mousewheel
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.theme_v2 import (
    ACCENT_GOLD,
    ASWF_DARK_GREY,
    BACKGROUND_ELEVATED,
    BODY_LABEL_STYLE,
    CARD_FRAME_STYLE,
    HEADING_LABEL_STYLE,
    MUTED_LABEL_STYLE,
    TEXT_PRIMARY,
)
from src.gui.zone_map_v2 import get_pipeline_stage_order
from src.utils.file_io import read_prompt_pack

from .core_config_panel_v2 import CoreConfigPanelV2
from .model_list_adapter_v2 import ModelListAdapterV2
from .output_settings_panel_v2 import OutputSettingsPanelV2
from .prompt_pack_adapter_v2 import PromptPackAdapterV2, PromptPackSummary
from .prompt_pack_list_manager import PromptPackListManager


class _SidebarCard(BaseStageCardV2):
    """Modular card for sidebar sections powered by the base stage card layout."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        *,
        build_child: Callable[[ttk.Frame], ttk.Frame],
        collapsible: bool = False,
        **kwargs: Any,
    ) -> None:
        self._build_child = build_child
        self._collapsible = collapsible
        self._toggle_btn: ttk.Button | None = None
        self._visible = True
        super().__init__(master, title=title, **kwargs)

    def _build_header(self) -> None:
        header = ttk.Frame(self, style=CARD_FRAME_STYLE)
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 4))
        self.columnconfigure(0, weight=1)
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        self.title_label = ttk.Label(header, text=self._title, style=HEADING_LABEL_STYLE)
        self.title_label.pack(side="left")
        if self._description:
            self.description_label = ttk.Label(
                header,
                text=self._description,
                style=MUTED_LABEL_STYLE,
                wraplength=420,
                justify="left",
            )
            self.description_label.pack(side="left", padx=(8, 0))
        if self._collapsible:
            self._toggle_btn = ttk.Button(header, text="Hide", width=8, command=self._toggle_body)
            self._toggle_btn.pack(side="right")

    def _build_body(self, parent: ttk.Frame) -> None:
        child = self._build_child(parent)
        self.child = child
        self._apply_dark_styles(child)
        child.pack(fill="both", expand=True)

    def _toggle_body(self) -> None:
        if not self._collapsible or self._toggle_btn is None:
            return
        if self._visible:
            self.body_frame.grid_remove()
            self._toggle_btn.config(text="Show")
        else:
            self.body_frame.grid()
            self._toggle_btn.config(text="Hide")
        self._visible = not self._visible

    def _apply_dark_styles(self, widget: tk.Widget) -> None:
        if isinstance(widget, ttk.Frame):
            widget.configure(style=CARD_FRAME_STYLE)
        for child in widget.winfo_children():
            if isinstance(child, ttk.Combobox):
                child.configure(style="Dark.TCombobox")
            elif isinstance(child, ttk.Spinbox):
                pass
            elif isinstance(child, ttk.Entry):
                child.configure(style="Dark.TEntry")
            elif isinstance(child, ttk.Label):
                child.configure(style=BODY_LABEL_STYLE)
            elif isinstance(child, ttk.Radiobutton):
                child.configure(style="Dark.TRadiobutton")
            elif isinstance(child, ttk.Checkbutton):
                child.configure(style="Dark.TCheckbutton")
            elif isinstance(child, ttk.Frame):
                child.configure(style=CARD_FRAME_STYLE)
            if hasattr(child, "winfo_children"):
                self._apply_dark_styles(child)


class SidebarPanelV2(ttk.Frame):
    """Container for sidebar content (core config + negative prompt + packs + pipeline controls)."""

    _STAGE_ORDER = get_pipeline_stage_order() or ["txt2img", "img2img", "adetailer", "upscale"]
    _STAGE_LABELS = {
        "txt2img": "Enable txt2img",
        "img2img": "Enable img2img",
        "adetailer": "Enable ADetailer",
        "upscale": "Enable upscale",
    }
    CARD_BASE_WIDTH = 240
    CARD_WIDTH = 80
    _MAX_PREVIEW_CHARS = 4000
    _CREATE_PRESET_LABEL = "Create new preset from stages"

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: object = None,
        app_state: object = None,
        prompt_pack_adapter: PromptPackAdapterV2 | None = None,
        on_apply_pack: Callable[[str, PromptPackSummary | None], None] | None = None,
        on_change: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style=CARD_FRAME_STYLE, padding=8, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self.prompt_pack_adapter = prompt_pack_adapter or PromptPackAdapterV2()
        self._on_apply_pack = on_apply_pack
        self._on_change = on_change

        adetailer_default = bool(getattr(self.app_state, "adetailer_enabled", False))  # Changed from True to False
        self.stage_states: dict[str, tk.BooleanVar] = {
            "txt2img": tk.BooleanVar(value=True),
            "img2img": tk.BooleanVar(value=False),  # Fixed: was True, should be False
            "adetailer": tk.BooleanVar(value=adetailer_default),
            "upscale": tk.BooleanVar(value=False),  # Fixed: was True, should be False
        }
        self.run_mode_var = tk.StringVar(value="direct")
        self.run_scope_var = tk.StringVar(value="full")

        self.columnconfigure(0, weight=1)
        # PR-GUI-H: Now 5 rows (0-4) after removing standalone config_source_label
        for i in range(5):
            self.rowconfigure(i, weight=1 if i >= 1 else 0)

        # PR-GUI-H: config_source_label moved into Pipeline Presets panel

        from src.utils.config import ConfigManager

        self.config_manager = ConfigManager()
        self.preset_names = (
            self.config_manager.list_presets()
            if hasattr(self.config_manager, "list_presets")
            else []
        )
        self.preset_var = tk.StringVar(value=self.preset_names[0] if self.preset_names else "")
        self.preset_combo: ttk.Combobox | None = None
        self.preset_menu_button: ttk.Menubutton | None = None
        self.preset_menu: tk.Menu | None = None
        self._last_valid_preset: str = ""
        self.config_source_label: ttk.Label | None = None

        self.pack_list_manager = PromptPackListManager()
        self.pack_list_names = self.pack_list_manager.get_list_names()
        self.pack_list_var = tk.StringVar(
            value=self.pack_list_names[0] if self.pack_list_names else ""
        )
        self.pack_listbox: tk.Listbox | None = None
        self.load_config_button: ttk.Button | None = None
        self.apply_config_button: ttk.Button | None = None
        self.add_to_job_button: ttk.Button | None = None
        self.preview_toggle_button: ttk.Button | None = None

        self._preview_visible = False
        self._preview_frame: ttk.Frame | None = None
        self.pack_preview_text: tk.Text | None = None
        self._prompt_summaries: list[PromptPackSummary] = []
        self._manual_pack_names: list[str] | None = None
        self._current_pack_names: list[str] = []
        self._preview_cache: dict[Path, str] = {}

        self.global_negative_enabled_var = tk.BooleanVar(value=True)  # Default enabled
        self.global_negative_text_var = tk.StringVar(value="")
        self.global_positive_enabled_var = tk.BooleanVar(value=False)
        self.global_positive_text_var = tk.StringVar(value="")
        
        # Override checkbox for pack config override
        self.override_pack_config_var = tk.BooleanVar(value=False)
        
        # Load global prompts from config manager
        try:
            if self.config_manager:
                if hasattr(self.config_manager, "get_global_negative_prompt"):
                    global_neg = self.config_manager.get_global_negative_prompt()
                    self.global_negative_text_var.set(global_neg)
                if hasattr(self.config_manager, "get_global_positive_prompt"):
                    global_pos = self.config_manager.get_global_positive_prompt()
                    self.global_positive_text_var.set(global_pos)
        except Exception:
            # Fail silently if loading fails
            pass

        self.preset_card = _SidebarCard(
            self,
            title="Pipeline Presets",
            build_child=lambda parent: self._build_preset_actions_section(parent),
        )
        self.preset_card.grid(row=0, column=0, sticky="ew", padx=8, pady=(0, 4))

        self.pack_selector_card = _SidebarCard(
            self,
            title="Pack Selector",
            build_child=lambda parent: self._build_pack_selector_section(parent),
            collapsible=True,
        )
        self.pack_panel = self.pack_selector_card
        self.pack_selector_card.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))

        self.model_adapter = ModelListAdapterV2(lambda: getattr(self.controller, "client", None))
        self.sampler_adapter = self.model_adapter

        # PR-GUI-H: Use embed_mode=True to build widgets directly into card body_frame
        self.core_config_card = _SidebarCard(
            self,
            title="Core Config",
            build_child=lambda parent: CoreConfigPanelV2(
                parent,
                controller=self.controller,
                include_vae=True,
                include_refresh=True,
                model_adapter=self.model_adapter,
                vae_adapter=self.model_adapter,
                sampler_adapter=self.sampler_adapter,
                show_header=False,
                embed_mode=True,
            ),
            collapsible=True,
        )
        self.core_config_panel = self.core_config_card.child
        self.core_config_card.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 4))

        self.pipeline_config_card = _SidebarCard(
            self,
            title="Pipeline Config",
            build_child=lambda parent: self._build_pipeline_config_section(parent),
        )
        self.pipeline_config_card.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 4))

        # PR-GUI-H: Use embed_mode=True to build widgets directly into card body_frame
        self.output_settings_card = _SidebarCard(
            self,
            title="Output Settings",
            build_child=lambda parent: OutputSettingsPanelV2(parent, embed_mode=True),
        )
        self.output_settings_card.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 4))

    def _build_preset_actions_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        combo_frame = ttk.Frame(frame)
        combo_frame.grid(row=0, column=0, sticky="ew")
        combo_frame.columnconfigure(0, weight=1)

        self.preset_combo = ttk.Combobox(
            combo_frame,
            values=self.preset_names,
            textvariable=self.preset_var,
            state="readonly",
            style="Dark.TCombobox",
        )
        self.preset_combo.grid(row=0, column=0, sticky="ew")
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        self.preset_menu_button = ttk.Menubutton(combo_frame, text="Actions", direction="below")
        self.preset_menu_button.grid(row=0, column=1, padx=(4, 0))
        self.preset_dropdown = self.preset_menu_button
        self.preset_menu = tk.Menu(self.preset_menu_button, tearoff=0)
        self.preset_menu.add_command(
            label="Apply to Default", command=self._on_preset_apply_to_default
        )
        self.preset_menu.add_command(
            label="Apply to Selected Packs", command=self._on_preset_apply_to_packs
        )
        self.preset_menu.add_command(label="Load to Stages", command=self._on_preset_load_to_stages)
        self.preset_menu.add_command(
            label="Save from Stages", command=self._on_preset_save_from_stages
        )
        self.preset_menu.add_command(label="Delete", command=self._on_preset_delete)
        self.preset_menu_button.config(menu=self.preset_menu)

        # PR-GUI-H: Bottom row with smaller create button and config source label
        bottom_row = ttk.Frame(frame)
        bottom_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        bottom_row.columnconfigure(1, weight=1)

        create_button = ttk.Button(
            bottom_row,
            text="+ New",
            width=8,
            command=self._create_preset_from_stages,
            style="Primary.TButton",
        )
        create_button.grid(row=0, column=0, sticky="w")

        self.config_source_label = ttk.Label(bottom_row, text="Defaults", style=MUTED_LABEL_STYLE)
        self.config_source_label.grid(row=0, column=1, sticky="e", padx=(8, 0))
        return frame

    def _create_preset_from_stages(self) -> None:
        """Prompt for a name and persist the current stage config as a preset."""
        self._handle_create_preset_action()

    def _handle_create_preset_action(self) -> None:
        preset_name = simpledialog.askstring("Create preset", "Preset name:", parent=self)
        if not preset_name:
            self._restore_last_selection()
            return
        controller = self.controller
        saved = False
        if controller and hasattr(controller, "save_current_pipeline_preset"):
            try:
                saved = controller.save_current_pipeline_preset(preset_name)
            except Exception:
                saved = False
        if saved:
            self._populate_preset_combo()
            self._apply_preset_selection(preset_name)
        else:
            self._restore_last_selection()

    def _apply_preset_selection(self, name: str | None) -> None:
        if name and name in self.preset_names:
            self.preset_var.set(name)
            self._last_valid_preset = name
            self._update_config_source_label(name)
        else:
            self.preset_var.set("")
            self._last_valid_preset = ""
            self._update_config_source_label(None)

    def _restore_last_selection(self) -> None:
        if self._last_valid_preset and self._last_valid_preset in self.preset_names:
            self._apply_preset_selection(self._last_valid_preset)
        else:
            self._apply_preset_selection(None)

    def _update_config_source_label(self, preset_name: str | None) -> None:
        text = f"Preset: {preset_name}" if preset_name else "Defaults"
        if self.config_source_label:
            self.config_source_label.config(text=text)

    def _build_pack_selector_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)

        # PR-GUI-H: Add prompt text and restore button (moved from actions_card in pipeline_tab_frame)
        prompt_row = ttk.Frame(frame)
        prompt_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        prompt_row.columnconfigure(0, weight=1)
        self.prompt_text = tk.Entry(prompt_row)
        self.prompt_text.grid(row=0, column=0, sticky="ew")
        self.restore_last_run_button = ttk.Button(
            prompt_row,
            text="Restore",
            width=8,
            command=self._on_restore_last_run,
        )
        self.restore_last_run_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)
        btn_frame.columnconfigure(3, weight=1)
        self.load_config_button = ttk.Button(
            btn_frame, text="Load Config", command=self._on_pack_load_config
        )
        self.load_config_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.apply_config_button = ttk.Button(
            btn_frame, text="Apply Config", command=self._on_pack_apply_config
        )
        self.apply_config_button.grid(row=0, column=1, sticky="ew", padx=(0, 2))
        self.add_to_job_button = ttk.Button(
            btn_frame, text="Add to Job", command=self._on_add_to_job
        )
        self.add_to_job_button.grid(row=0, column=2, sticky="ew", padx=(0, 2))
        self.preview_toggle_button = ttk.Button(
            btn_frame, text="Show Preview", command=self._toggle_pack_preview, state=tk.DISABLED
        )
        self.preview_toggle_button.grid(row=0, column=3, sticky="ew")

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        list_frame.columnconfigure(0, weight=1)
        self.pack_list_combo = ttk.Combobox(
            list_frame,
            values=self.pack_list_names,
            textvariable=self.pack_list_var,
            state="readonly",
            style="Dark.TCombobox",
        )
        self.pack_list_combo.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.pack_list_combo.bind("<<ComboboxSelected>>", self._on_pack_list_selected)

        list_box_frame = ttk.Frame(list_frame)
        list_box_frame.grid(row=1, column=0, sticky="nsew")
        list_box_frame.rowconfigure(0, weight=1)
        list_box_frame.columnconfigure(0, weight=1)
        self.pack_listbox = tk.Listbox(
            list_box_frame,
            selectmode="extended",
            background=ASWF_DARK_GREY,
            foreground=TEXT_PRIMARY,
            selectbackground=ACCENT_GOLD,
            selectforeground=BACKGROUND_ELEVATED,
            borderwidth=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BACKGROUND_ELEVATED,
            activestyle="none",
            height=8,
        )
        self.pack_listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            list_box_frame, orient=tk.VERTICAL, command=self.pack_listbox.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.pack_listbox.config(yscrollcommand=scrollbar.set)
        enable_mousewheel(self.pack_listbox)
        self.pack_listbox.bind(
            "<<ListboxSelect>>",
            lambda event: self._on_pack_selection_changed(),
        )
        self.packs_list = self.pack_listbox

        self._preview_frame = ttk.Frame(frame)
        self._preview_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self._preview_frame.columnconfigure(0, weight=1)
        preview_label = ttk.Label(
            self._preview_frame, text="Prompt Preview", style=BODY_LABEL_STYLE
        )
        preview_label.grid(row=0, column=0, sticky="w")
        preview_text_frame = ttk.Frame(self._preview_frame)
        preview_text_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        preview_text_frame.columnconfigure(0, weight=1)
        self.pack_preview_text = tk.Text(
            preview_text_frame,
            height=10,
            wrap="word",
            state="disabled",
            background=BACKGROUND_ELEVATED,
            foreground=TEXT_PRIMARY,
            relief="solid",
            borderwidth=1,
        )
        self.pack_preview_text.grid(row=0, column=0, sticky="nsew")
        preview_scrollbar = ttk.Scrollbar(
            preview_text_frame, orient=tk.VERTICAL, command=self.pack_preview_text.yview
        )
        preview_scrollbar.grid(row=0, column=1, sticky="ns")
        self.pack_preview_text.config(yscrollcommand=preview_scrollbar.set)
        self._preview_frame.grid_remove()
        self._preview_current_path: Path | None = None

        # Global Prompts Section
        global_frame = ttk.LabelFrame(frame, text="Global Prompts", padding=8, style="Dark.TLabelframe")
        global_frame.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        global_frame.columnconfigure(1, weight=1)
        
        # Global Positive
        pos_row = 0
        ttk.Label(global_frame, text="✨ Positive:", style="Dark.TLabel").grid(
            row=pos_row, column=0, sticky="w"
        )
        pos_cb = ttk.Checkbutton(
            global_frame,
            text="Enable",
            variable=self.global_positive_enabled_var,
            style="Dark.TCheckbutton",
        )
        pos_cb.grid(row=pos_row, column=1, sticky="w", padx=(4, 0))
        
        pos_entry = ttk.Entry(
            global_frame,
            textvariable=self.global_positive_text_var,
            width=30,
            style="Dark.TEntry",
        )
        pos_entry.grid(row=pos_row + 1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        
        save_pos_btn = ttk.Button(
            global_frame,
            text="Save Global Positive",
            command=self._save_global_positive,
            width=20,
            style="Dark.TButton",
        )
        save_pos_btn.grid(row=pos_row + 2, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        
        # Global Negative
        neg_row = 3
        ttk.Label(global_frame, text="🛡️ Negative:", style="Dark.TLabel").grid(
            row=neg_row, column=0, sticky="w"
        )
        neg_cb = ttk.Checkbutton(
            global_frame,
            text="Enable",
            variable=self.global_negative_enabled_var,
            style="Dark.TCheckbutton",
        )
        neg_cb.grid(row=neg_row, column=1, sticky="w", padx=(4, 0))
        
        neg_entry = ttk.Entry(
            global_frame,
            textvariable=self.global_negative_text_var,
            width=30,
            style="Dark.TEntry",
        )
        neg_entry.grid(row=neg_row + 1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        
        save_neg_btn = ttk.Button(
            global_frame,
            text="Save Global Negative",
            command=self._save_global_negative,
            width=20,
            style="Dark.TButton",
        )
        save_neg_btn.grid(row=neg_row + 2, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        frame.rowconfigure(1, weight=1)
        self._populate_packs_for_selected_list()
        self._update_pack_actions_state()
        return frame

    def _on_pack_selection_changed(self) -> None:
        self._update_pack_actions_state()

    def _on_pack_list_selected(self, event: object | None = None) -> None:
        if event is not None and getattr(event, "widget", None) is self.pack_list_combo:
            try:
                self.pack_list_var.set(self.pack_list_combo.get())
            except Exception:
                pass
        self._populate_packs_for_selected_list()

    def _load_prompt_summaries(self) -> list[PromptPackSummary]:
        if not self.prompt_pack_adapter:
            self._prompt_summaries = []
            return []
        try:
            summaries = self.prompt_pack_adapter.load_summaries()
        except Exception:
            summaries = []
        self._prompt_summaries = summaries
        return summaries

    def _populate_packs_for_selected_list(self) -> None:
        if not self.pack_listbox:
            return
        summaries = self._load_prompt_summaries() or self._prompt_summaries
        selected_list = (self.pack_list_var.get() or "").strip()
        packs: list[PromptPackSummary] = []
        if selected_list:
            pack_names = self.pack_list_manager.get_list(selected_list) or []
            packs = [summary for summary in summaries if summary.name in pack_names]
        if not packs:
            packs = summaries
        if self._manual_pack_names:
            packs = [
                PromptPackSummary(name=pn, description="", prompt_count=1, path=Path(""))
                for pn in self._manual_pack_names
            ]
        self._current_pack_names = [summary.name for summary in packs]
        self.pack_listbox.delete(0, "end")
        for name in self._current_pack_names:
            self.pack_listbox.insert("end", name)
        self._update_pack_actions_state()

    def _populate_preset_combo(self) -> None:
        if not self.preset_combo:
            return
        presets = (
            self.config_manager.list_presets()
            if hasattr(self.config_manager, "list_presets")
            else []
        )
        self.preset_names = presets
        values = presets + [self._CREATE_PRESET_LABEL]
        self.preset_combo.config(values=values)
        if presets:
            self._apply_preset_selection(presets[0])
        else:
            self._apply_preset_selection(None)

    def _on_restore_last_run(self) -> None:
        """Handle restore last run button click - delegates to controller."""
        controller = self.controller
        if controller and hasattr(controller, "restore_last_run"):
            try:
                controller.restore_last_run()
            except Exception:
                pass

    def _on_pack_load_config(self) -> None:
        if not self.pack_listbox:
            return
        selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
        if len(selection) != 1:
            return
        pack_id = (
            self._current_pack_names[selection[0]]
            if selection[0] < len(self._current_pack_names)
            else None
        )
        if not pack_id:
            return
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_pack_load_config"):
            try:
                controller.on_pipeline_pack_load_config(pack_id)
            except Exception:
                pass

    def _on_pack_apply_config(self) -> None:
        if not self.pack_listbox:
            return
        selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            return
        pack_ids = [
            self._current_pack_names[i] for i in selection if i < len(self._current_pack_names)
        ]
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_pack_apply_config"):
            try:
                controller.on_pipeline_pack_apply_config(pack_ids)
            except Exception:
                pass

    def _on_add_to_job(self) -> None:
        """Handle 'Add to Job' button click.

        PR-CORE-D/E: PromptPack-only architecture - button should only be enabled when pack(s) selected.
        Routes to controller's on_pipeline_add_packs_to_job.
        """
        print("[SidebarPanel] _on_add_to_job called")
        if not self.pack_listbox:
            print("[SidebarPanel] No pack_listbox, returning")
            return

        selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
        controller = self.controller
        print(f"[SidebarPanel] Selection: {selection}, Controller: {controller}")

        # PromptPack-only: This should not execute if button state is correct, but guard anyway
        if not selection:
            print("[SidebarPanel] No selection, falling back to single prompt handler")
            if controller and hasattr(controller, "add_single_prompt_to_draft"):
                try:
                    controller.add_single_prompt_to_draft()
                except Exception:
                    pass
            return

        # Add selected pack(s) to job draft
        pack_ids = [
            self._current_pack_names[i] for i in selection if i < len(self._current_pack_names)
        ]
        print(f"[SidebarPanel] Pack IDs to add: {pack_ids}")
        if controller and hasattr(controller, "on_pipeline_add_packs_to_job"):
            print(f"[SidebarPanel] Calling controller.on_pipeline_add_packs_to_job({pack_ids})")
            try:
                controller.on_pipeline_add_packs_to_job(pack_ids)
                print("[SidebarPanel] Successfully called on_pipeline_add_packs_to_job")
            except Exception as e:
                import logging

                print(f"[SidebarPanel] EXCEPTION: {e}")
                logging.exception(f"Error adding packs to job: {e}")
        else:
            print(
                "[SidebarPanel] Controller missing or doesn't have on_pipeline_add_packs_to_job method"
            )

    def _toggle_pack_preview(self) -> None:
        if not self.preview_toggle_button or not self.pack_listbox:
            return
        selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
        if len(selection) != 1:
            return
        if self._preview_visible:
            self._hide_pack_preview()
        else:
            self._show_pack_preview()

    def _show_pack_preview(self) -> None:
        if not self._preview_frame or not self.preview_toggle_button:
            return
        if not self._refresh_preview_for_current_selection():
            return
        self._preview_frame.grid()
        self._preview_visible = True
        self.preview_toggle_button.config(text="Hide Preview")

    def _hide_pack_preview(self) -> None:
        if not self._preview_frame or not self.preview_toggle_button:
            return
        self._preview_frame.grid_remove()
        self._preview_visible = False
        self._preview_current_path = None
        self.preview_toggle_button.config(text="Show Preview")

    def _update_preview_text(self, summary: PromptPackSummary) -> None:
        if not self.pack_preview_text:
            return
        preview = self._describe_first_prompt(summary)
        try:
            self.pack_preview_text.config(state="normal")
            self.pack_preview_text.delete("1.0", "end")
            self.pack_preview_text.insert("end", preview)
        finally:
            self.pack_preview_text.config(state="disabled")

    def _refresh_preview_for_current_selection(self) -> bool:
        """Ensure the preview text matches the current single selection (no redundant repaint)."""
        summary = self._get_selected_pack_summary()
        if summary is None:
            self._hide_pack_preview()
            return False
        if self._preview_visible and self._preview_current_path == summary.path:
            return True
        self._update_preview_text(summary)
        self._preview_current_path = summary.path
        return True

    def _limit_preview_text(self, preview: str) -> str:
        """Truncate overly large preview strings to keep Tk safe."""
        max_chars = self._MAX_PREVIEW_CHARS
        if len(preview) <= max_chars:
            return preview
        truncated = preview[:max_chars].rstrip()
        return f"{truncated}\n\n[Preview truncated]"

    def _describe_first_prompt(self, summary: PromptPackSummary) -> str:
        cached = self._preview_cache.get(summary.path)
        if cached:
            return cached
        prompts = read_prompt_pack(summary.path)
        if not prompts:
            preview = (
                f"Pack: {summary.name}\nPrompts: {summary.prompt_count}\n\nNo preview available."
            )
            self._preview_cache[summary.path] = preview
            return preview
        block_lines = self._read_first_block(summary.path)
        header = [
            f"Pack: {summary.name}",
            f"Prompts: {summary.prompt_count}",
            "",
        ]
        if block_lines:
            block_content = [line for line in block_lines.splitlines() if line.strip()]
            preview = "\n".join(header + block_content)
        else:
            first = prompts[0]
            positive = (first.get("positive") or "").strip()
            negative = (first.get("negative") or "").strip()
            if positive:
                header.extend(["Positive Prompt:", positive, ""])
            if negative:
                header.extend(["Negative Prompt:", negative, ""])
            preview = "\n".join(header)
        preview = self._limit_preview_text(preview)
        self._preview_cache[summary.path] = preview
        return preview

    def _read_first_block(self, pack_path: Path) -> str:
        try:
            content = pack_path.read_text(encoding="utf-8")
        except Exception:
            return ""
        blocks = [block.strip() for block in content.split("\n\n") if block.strip()]
        if not blocks:
            return ""
        return blocks[0]

    def _update_pack_actions_state(self) -> None:
        if not self.pack_listbox:
            return
        selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
        single = len(selection) == 1
        has_selection = len(selection) > 0
        if self.load_config_button:
            self.load_config_button.config(state=tk.NORMAL if single else tk.DISABLED)
        if self.apply_config_button:
            self.apply_config_button.config(state=tk.NORMAL)
        if self.add_to_job_button:
            # PR-CORE-D/E: PromptPack-only architecture - "Add to Job" requires pack selection
            self.add_to_job_button.config(state=tk.NORMAL if has_selection else tk.DISABLED)
        if self.preview_toggle_button:
            if not single:
                self.preview_toggle_button.config(state=tk.DISABLED)
                if self._preview_visible:
                    self._hide_pack_preview()
            else:
                self.preview_toggle_button.config(state=tk.NORMAL)
                if self._preview_visible:
                    self._refresh_preview_for_current_selection()

    def _get_selected_pack_summary(self) -> PromptPackSummary | None:
        if len(self._current_pack_names) == 0 or not self.pack_listbox:
            return None
        summary_name = None
        selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
        if len(selection) != 1:
            return None
        idx = selection[0]
        if idx < len(self._current_pack_names):
            summary_name = self._current_pack_names[idx]
        if not summary_name:
            return None
        for summary in self._prompt_summaries:
            if summary.name == summary_name:
                return summary
        return None

    def refresh_prompt_packs(self) -> None:
        if not self.prompt_pack_adapter:
            return
        self._load_prompt_summaries()
        self.pack_list_manager.refresh()  # type: ignore[no-untyped-call]
        self._set_pack_list_values(self.pack_list_manager.get_list_names())
        self._populate_packs_for_selected_list()

    def set_pack_names(self, names: list[str]) -> None:
        """Best-effort helper for simple string lists (used by AppController)."""
        self._manual_pack_names = names
        self._current_pack_names = list(names)
        if self.pack_listbox:
            self.pack_listbox.delete(0, "end")
            for name in self._current_pack_names:
                self.pack_listbox.insert("end", name)

    def _set_pack_list_values(self, names: list[str]) -> None:
        self.pack_list_names = names
        if self.pack_list_combo:
            self.pack_list_combo["values"] = names
            if names:
                self.pack_list_var.set(names[0])

    def _on_preset_selected(self, event: object = None) -> None:
        selected_preset = self.preset_var.get()
        if selected_preset == self._CREATE_PRESET_LABEL:
            self._handle_create_preset_action()
            return
        if not selected_preset:
            self._apply_preset_selection(None)
            self.grid_columnconfigure(0, weight=1)
            return
        if self.controller and hasattr(self.controller, "on_preset_selected"):
            try:
                self.controller.on_preset_selected(selected_preset)
            except Exception:
                pass
        self._last_valid_preset = selected_preset
        self._update_config_source_label(selected_preset)
        self.grid_columnconfigure(0, weight=1)

    def _on_preset_apply_to_default(self) -> None:
        preset_name = self.preset_var.get()
        if not preset_name:
            return
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_preset_apply_to_default"):
            try:
                controller.on_pipeline_preset_apply_to_default(preset_name)
            except Exception:
                pass

    def _on_preset_apply_to_packs(self) -> None:
        preset_name = self.preset_var.get()
        if not preset_name or not self.pack_listbox:
            return
        selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
        pack_ids = [
            self._current_pack_names[i] for i in selection if i < len(self._current_pack_names)
        ]
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_preset_apply_to_packs"):
            try:
                controller.on_pipeline_preset_apply_to_packs(preset_name, pack_ids)
            except Exception:
                pass

    def _on_preset_load_to_stages(self) -> None:
        preset_name = self.preset_var.get()
        if not preset_name:
            return
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_preset_load_to_stages"):
            try:
                controller.on_pipeline_preset_load_to_stages(preset_name)
            except Exception:
                pass

    def _on_preset_save_from_stages(self) -> None:
        preset_name = self.preset_var.get()
        if not preset_name:
            return
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_preset_save_from_stages"):
            try:
                controller.on_pipeline_preset_save_from_stages(preset_name)
            except Exception:
                pass

    def _on_preset_delete(self) -> None:
        preset_name = self.preset_var.get()
        if not preset_name:
            return
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_preset_delete"):
            try:
                controller.on_pipeline_preset_delete(preset_name)
            except Exception:
                pass

    def _build_stages_section(self, parent: ttk.Frame) -> ttk.Frame:
        """Build stages section with horizontal 2-column layout."""
        frame = ttk.Frame(parent)
        for idx, stage in enumerate(self._STAGE_ORDER):
            var = self.stage_states.get(stage)
            if var is None:
                continue
            label = self._STAGE_LABELS.get(stage, stage.title())

            def make_toggle_command(stage_name: str) -> Callable[[], None]:
                return lambda: self._on_stage_toggle(stage_name)

            cb = ttk.Checkbutton(
                frame,
                text=label,
                variable=var,
                command=make_toggle_command(stage),
                style="Dark.TCheckbutton",
            )
            # 2-column layout: row = idx // 2, column = idx % 2
            row = idx // 2
            col = idx % 2
            cb.grid(row=row, column=col, sticky="w", pady=2, padx=(0, 12))
        return frame

    def _on_stage_toggle(self, stage: str) -> None:
        var = self.stage_states.get(stage)
        if var is None:
            return
        enabled = bool(var.get())
        controller = self.controller
        if controller and hasattr(controller, "on_stage_toggled"):
            try:
                controller.on_stage_toggled(stage, enabled)
            except Exception:
                pass
        self._emit_change()

    def _on_override_changed(self) -> None:
        """Called when override pack config checkbox state changes."""
        enabled = bool(self.override_pack_config_var.get())
        controller = self.controller
        if controller and hasattr(controller, "on_override_pack_config_changed"):
            try:
                controller.on_override_pack_config_changed(enabled)
            except Exception:
                pass
        self._emit_change()

    def _build_run_mode_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        rb1 = ttk.Radiobutton(
            frame,
            text="Direct",
            value="direct",
            variable=self.run_mode_var,
            command=self._on_run_mode_change,
            style="Dark.TRadiobutton",
        )
        rb1.grid(row=0, column=0, sticky="w", pady=2)
        rb2 = ttk.Radiobutton(
            frame,
            text="Queue",
            value="queue",
            variable=self.run_mode_var,
            command=self._on_run_mode_change,
            style="Dark.TRadiobutton",
        )
        rb2.grid(row=1, column=0, sticky="w", pady=2)
        return frame

    def _build_run_scope_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        for idx, (label, val) in enumerate(
            [
                ("Selected only", "selected"),
                ("From selected", "from_selected"),
                ("Full pipeline", "full"),
            ]
        ):
            rb = ttk.Radiobutton(
                frame,
                text=label,
                value=val,
                variable=self.run_scope_var,
                command=self._emit_change,
                style="Dark.TRadiobutton",
            )
            rb.grid(row=idx, column=0, sticky="w", pady=2)
        return frame

    def _build_pipeline_config_section(self, parent: ttk.Frame) -> ttk.Frame:
        """Pipeline config section with override checkbox and stage toggles.

        PR-CORE1-12: PipelineConfigPanel archived - now using direct stage toggles.
        Added override checkbox to control whether current stage configs override pack configs.
        """
        # PR-CORE1-12: PipelineConfigPanel archived - no longer wired
        # from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel

        # Create a frame to hold the pipeline config panel and stage toggles
        frame = ttk.Frame(parent)
        
        # Override checkbox section
        override_frame = ttk.Frame(frame)
        override_frame.pack(fill="x", pady=(0, 8))
        override_cb = ttk.Checkbutton(
            override_frame,
            text="Override pack configs with current stages",
            variable=self.override_pack_config_var,
            command=self._on_override_changed,
            style="Dark.TCheckbutton",
        )
        override_cb.pack(anchor="w")
        
        # Stage toggles section
        stage_section = ttk.Frame(frame)
        stage_section.pack(fill="x", pady=(0, 8))
        header = ttk.Label(stage_section, text="Stages", style=HEADING_LABEL_STYLE)
        header.pack(anchor="w")
        stages_frame = self._build_stages_section(stage_section)
        stages_frame.pack(fill="x", pady=(4, 0))

        # Try to instantiate the archived/shim PipelineConfigPanel and expose it
        try:
            from src.gui.panels_v2.pipeline_config_panel_v2 import (
                PipelineConfigPanel,  # type: ignore
            )
        except Exception:
            PipelineConfigPanel = None  # pragma: no cover - best-effort

        panel = None
        if PipelineConfigPanel is not None:
            # Prefer the richer constructor but tolerate alternate signatures
            try:
                panel = PipelineConfigPanel(
                    frame,
                    controller=getattr(self, "controller", None),
                    app_state=getattr(self, "app_state", None),
                    on_change=self._emit_change,
                )
            except TypeError:
                try:
                    panel = PipelineConfigPanel(
                        frame,
                        pipeline_state=getattr(self, "pipeline_state", None),
                        app_state=getattr(self, "app_state", None),
                        on_change=self._emit_change,
                    )
                except Exception:
                    panel = None
            except Exception:
                panel = None

        # Always expose a panel instance so callers and tests have a handle
        if panel is None:
            try:
                panel = ttk.Frame(frame)
            except Exception:
                panel = None

        if panel is not None:
            # Ensure expected attributes exist even for shim panels
            if not hasattr(panel, "controller"):
                panel.controller = getattr(self, "controller", None)
            if not hasattr(panel, "app_state"):
                panel.app_state = getattr(self, "app_state", None)
            if not hasattr(panel, "pipeline_state"):
                panel.pipeline_state = getattr(self, "pipeline_state", None)

            self.pipeline_config_panel = panel
            try:
                panel.pack(fill="both", expand=True)
            except Exception:
                pass
        else:
            # Ensure attribute exists for callers; None means not available
            self.pipeline_config_panel = None

        return frame

        # Prompt Pack Panel (below grid)
        # Removed obsolete code: old layout and duplicate panel instantiations

    # --- Pipeline control helpers -------------------------------------
    def get_enabled_stages(self) -> list[str]:
        return [
            stage
            for stage in self._STAGE_ORDER
            if self.stage_states.get(stage) and bool(self.stage_states[stage].get())
        ]

    def set_stage_state(self, stage: str, enabled: bool, *, emit_change: bool = True) -> None:
        var = self.stage_states.get(stage)
        if var is None:
            return
        normalized = bool(enabled)
        current = bool(var.get())
        if current == normalized:
            return
        var.set(normalized)
        if emit_change:
            self._emit_change()

    def get_run_mode(self) -> str:
        return self.run_mode_var.get()

    def get_run_scope(self) -> str:
        return self.run_scope_var.get()

    def get_job_counts(self) -> tuple[int, int]:
        stages = len(self.get_enabled_stages())
        jobs = max(1, stages)
        images_per_job = 1
        return jobs, images_per_job

    def _emit_change(self) -> None:
        if callable(self._on_change):
            try:
                self._on_change()
            except Exception:
                pass

    def _on_run_mode_change(self) -> None:
        self._refresh_run_mode_widgets()
        self._emit_change()

    # No sidebar Run Now button or Add to Queue button in new layout
    def _refresh_run_mode_widgets(self) -> None:
        pass

    def get_global_negative_config(self) -> dict[str, object]:
        return {
            "enabled": bool(self.global_negative_enabled_var.get()),
            "text": self.global_negative_text_var.get().strip(),
        }
    
    def get_global_positive_config(self) -> dict[str, object]:
        return {
            "enabled": bool(self.global_positive_enabled_var.get()),
            "text": self.global_positive_text_var.get().strip(),
        }
    
    def _save_global_negative(self) -> None:
        """Save global negative prompt to disk."""
        if not self.config_manager:
            return
        if not hasattr(self.config_manager, "save_global_negative_prompt"):
            return
        text = self.global_negative_text_var.get().strip()
        try:
            self.config_manager.save_global_negative_prompt(text)
        except Exception:
            pass
    
    def _save_global_positive(self) -> None:
        """Save global positive prompt to disk."""
        if not self.config_manager:
            return
        if not hasattr(self.config_manager, "save_global_positive_prompt"):
            return
        text = self.global_positive_text_var.get().strip()
        try:
            self.config_manager.save_global_positive_prompt(text)
        except Exception:
            pass

    def get_core_config_panel(self) -> CoreConfigPanelV2 | None:
        return getattr(self, "core_config_panel", None)

    def refresh_core_config_from_webui(self) -> None:
        panel = self.get_core_config_panel()
        if panel and hasattr(panel, "refresh_from_adapters"):
            try:
                panel.refresh_from_adapters()
            except Exception:
                pass

    def get_model_overrides(self) -> dict[str, object]:
        panel = getattr(self, "model_manager_panel", None)
        if panel:
            return panel.get_selections()  # type: ignore
        return {}

    def get_core_overrides(self) -> dict[str, object]:
        panel = self.get_core_config_panel()
        if panel and hasattr(panel, "get_overrides"):
            return panel.get_overrides()
        return {}

    def get_negative_prompt(self) -> str:
        # Negative prompt card removed; always return empty string
        return ""

    def get_resolution(self) -> tuple[int, int]:
        panel = self.get_core_config_panel()
        if panel:
            overrides = panel.get_overrides()
            width = overrides.get("width", 512)
            height = overrides.get("height", 512)
            if isinstance(width, int) and isinstance(height, int):
                return width, height
        return 512, 512

    def get_resolution_preset(self) -> str:
        panel = self.get_core_config_panel()
        if panel:
            overrides = panel.get_overrides()
            preset = overrides.get("resolution_preset", "")
            if isinstance(preset, str):
                return preset
        return ""

    def get_output_overrides(self) -> dict[str, object]:
        panel = getattr(self, "output_settings_panel", None)
        if panel:
            return panel.get_output_overrides()  # type: ignore
        return {}


__all__ = ["SidebarPanelV2"]

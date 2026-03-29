from __future__ import annotations

import json
import logging
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import simpledialog, ttk
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
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
from src.state.workspace_paths import workspace_paths
from src.utils.file_io import read_prompt_pack

from .base_generation_panel_v2 import BaseGenerationPanelV2
from .model_list_adapter_v2 import ModelListAdapterV2
from .output_settings_panel_v2 import OutputSettingsPanelV2
from .prompt_pack_adapter_v2 import PromptPackAdapterV2, PromptPackSummary
from .prompt_pack_list_manager import PromptPackListManager
from .recipe_summary_v2 import build_saved_recipe_summary

logger = logging.getLogger(__name__)

# PR-PERSIST-001: Sidebar state persistence
SIDEBAR_STATE_PATH = workspace_paths.sidebar_state()


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
    """Container for saved recipes, packs, base generation, and pipeline controls."""

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
    _CREATE_SAVED_RECIPE_LABEL = "Create new recipe from stages"

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
        self._content_visibility_mode = str(
            getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._app_state_visibility_listener: Callable[[], None] | None = None

        # PR-DEFAULT-ADETAILER: Default to True for visibility
        adetailer_default = bool(getattr(self.app_state, "adetailer_enabled", True))
        self.stage_states: dict[str, tk.BooleanVar] = {
            "txt2img": tk.BooleanVar(value=True),
            "img2img": tk.BooleanVar(value=False),  # Fixed: was True, should be False
            "adetailer": tk.BooleanVar(value=adetailer_default),
            "upscale": tk.BooleanVar(value=False),  # Fixed: was True, should be False
        }
        self.run_mode_var = tk.StringVar(value="queue")
        self.run_scope_var = tk.StringVar(value="full")

        self.columnconfigure(0, weight=1)
        # PR-GUI-H: Now 6 rows (0-5) including reprocess panel
        for i in range(6):
            self.rowconfigure(i, weight=1 if i >= 1 else 0)

        # PR-GUI-H: config_source_label moved into the saved-recipe panel

        from src.utils.config import ConfigManager

        self.config_manager = ConfigManager()
        self.saved_recipe_names = (
            self.config_manager.list_presets()
            if hasattr(self.config_manager, "list_presets")
            else []
        )
        self.saved_recipe_var = tk.StringVar(
            value=self.saved_recipe_names[0] if self.saved_recipe_names else ""
        )
        self.saved_recipe_combo: ttk.Combobox | None = None
        self.saved_recipe_menu_button: ttk.Menubutton | None = None
        self.saved_recipe_menu: tk.Menu | None = None
        self._last_valid_saved_recipe: str = ""
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
        # Hidden compatibility widget for older pipeline/journey touchpoints.
        self.prompt_text: tk.Entry | None = tk.Entry(self)
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

        self.saved_recipe_card = _SidebarCard(
            self,
            title="Saved Recipes",
            build_child=lambda parent: self._build_saved_recipe_actions_section(parent),
        )
        self.saved_recipe_card.grid(row=0, column=0, sticky="ew", padx=8, pady=(0, 4))

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
        self.base_generation_card = _SidebarCard(
            self,
            title="Base Generation",
            build_child=lambda parent: BaseGenerationPanelV2(
                parent,
                controller=self.controller,
                include_vae=True,
                include_refresh=True,
                model_adapter=self.model_adapter,
                vae_adapter=self.model_adapter,
                sampler_adapter=self.sampler_adapter,
                on_change=self._emit_change,
                show_header=False,
                embed_mode=True,
            ),
            collapsible=True,
        )
        self.base_generation_panel = self.base_generation_card.child
        self.base_generation_card.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 4))

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
        
        # Reprocess panel for sending existing images through pipeline stages
        # Import inside lambda to avoid circular import at module load time
        def _build_reprocess_panel(parent):
            from src.gui.panels_v2.reprocess_panel_v2 import ReprocessPanelV2
            return ReprocessPanelV2(
                parent,
                controller=self.controller,
                app_state=self.app_state,
                embed_mode=True,
            )
        
        self.reprocess_card = _SidebarCard(
            self,
            title="Reprocess Images",
            build_child=_build_reprocess_panel,
            collapsible=True,
        )
        self.reprocess_panel = self.reprocess_card.child
        self.reprocess_card.grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 4))
        
        self._bind_app_state()
        # PR-PERSIST-001: Restore saved state
        self.restore_state()

    def _build_saved_recipe_actions_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        combo_frame = ttk.Frame(frame)
        combo_frame.grid(row=0, column=0, sticky="ew")
        combo_frame.columnconfigure(0, weight=1)

        self.saved_recipe_combo = ttk.Combobox(
            combo_frame,
            values=self.saved_recipe_names,
            textvariable=self.saved_recipe_var,
            state="readonly",
            style="Dark.TCombobox",
        )
        self.saved_recipe_combo.grid(row=0, column=0, sticky="ew")
        self.saved_recipe_combo.bind("<<ComboboxSelected>>", self._on_saved_recipe_selected)

        self.saved_recipe_menu_button = ttk.Menubutton(combo_frame, text="Actions", direction="below", style="Dark.TButton")
        self.saved_recipe_menu_button.grid(row=0, column=1, padx=(4, 0))
        self.saved_recipe_dropdown = self.saved_recipe_menu_button
        self.saved_recipe_menu = tk.Menu(self.saved_recipe_menu_button, tearoff=0)
        self.saved_recipe_menu.add_command(
            label="Apply to Working State", command=self._on_saved_recipe_apply_to_working_state
        )
        self.saved_recipe_menu.add_command(
            label="Apply to Selected Packs", command=self._on_saved_recipe_apply_to_selected_packs
        )
        self.saved_recipe_menu.add_command(
            label="Load to Pipeline", command=self._on_saved_recipe_load_to_pipeline
        )
        self.saved_recipe_menu.add_command(
            label="Save Current as Recipe", command=self._on_saved_recipe_save_current
        )
        self.saved_recipe_menu.add_command(label="Delete Recipe", command=self._on_saved_recipe_delete)
        self.saved_recipe_menu_button.config(menu=self.saved_recipe_menu)

        # PR-GUI-H: Bottom row with smaller create button and config source label
        bottom_row = ttk.Frame(frame)
        bottom_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        bottom_row.columnconfigure(1, weight=1)

        create_button = ttk.Button(
            bottom_row,
            text="+ New",
            width=8,
            command=self._create_saved_recipe_from_stages,
            style="Dark.TButton",
        )
        create_button.grid(row=0, column=0, sticky="w")

        self.config_source_label = ttk.Label(
            bottom_row,
            text="Working state",
            style=MUTED_LABEL_STYLE,
            wraplength=420,
            justify="right",
        )
        self.config_source_label.grid(row=0, column=1, sticky="e", padx=(8, 0))
        return frame

    def _create_saved_recipe_from_stages(self) -> None:
        """Prompt for a name and persist the current stage config as a preset."""
        self._handle_create_saved_recipe_action()

    def _handle_create_saved_recipe_action(self) -> None:
        recipe_name = simpledialog.askstring("Create recipe", "Recipe name:", parent=self)
        if not recipe_name:
            self._restore_last_saved_recipe_selection()
            return
        controller = self.controller
        saved = False
        if controller and hasattr(controller, "save_current_pipeline_saved_recipe"):
            try:
                saved = controller.save_current_pipeline_saved_recipe(recipe_name)
            except Exception:
                saved = False
        if saved:
            self._populate_saved_recipe_combo()
            self._apply_saved_recipe_selection(recipe_name)
        else:
            self._restore_last_saved_recipe_selection()

    def _apply_saved_recipe_selection(self, name: str | None) -> None:
        if name and name in self.saved_recipe_names:
            self.saved_recipe_var.set(name)
            self._last_valid_saved_recipe = name
            self._update_config_source_label(name)
        else:
            self.saved_recipe_var.set("")
            self._last_valid_saved_recipe = ""
            self._update_config_source_label(None)

    def _restore_last_saved_recipe_selection(self) -> None:
        if (
            self._last_valid_saved_recipe
            and self._last_valid_saved_recipe in self.saved_recipe_names
        ):
            self._apply_saved_recipe_selection(self._last_valid_saved_recipe)
        else:
            self._apply_saved_recipe_selection(None)

    def _update_config_source_label(self, recipe_name: str | None) -> None:
        text = "Working state"
        if recipe_name:
            recipe_path = Path(self.config_manager.presets_dir) / f"{recipe_name}.json"
            recipe_config = None
            if hasattr(self.config_manager, "load_preset"):
                try:
                    recipe_config = self.config_manager.load_preset(recipe_name)
                except Exception:
                    recipe_config = None
            summary = build_saved_recipe_summary(
                recipe_name,
                recipe_config,
                recipe_path=recipe_path,
            )
            text = summary.to_label_text()
        if self.config_source_label:
            self.config_source_label.config(text=text)

    def _build_pack_selector_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)

        toolbar_row = ttk.Frame(frame)
        toolbar_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar_row.columnconfigure(0, weight=1)
        ttk.Label(
            toolbar_row,
            text="Select PromptPacks to preview, apply, or add to the draft job.",
            style=MUTED_LABEL_STYLE,
        ).grid(row=0, column=0, sticky="w")
        self.refresh_packs_button = ttk.Button(
            toolbar_row,
            text="Refresh",
            width=8,
            command=self.refresh_prompt_packs,
            style="Dark.TButton",
        )
        self.refresh_packs_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)
        btn_frame.columnconfigure(3, weight=1)
        self.load_config_button = ttk.Button(
            btn_frame, text="Load Config", command=self._on_pack_load_config, style="Dark.TButton"
        )
        self.load_config_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.apply_config_button = ttk.Button(
            btn_frame, text="Apply Config", command=self._on_pack_apply_config, style="Dark.TButton"
        )
        self.apply_config_button.grid(row=0, column=1, sticky="ew", padx=(0, 2))
        self.add_to_job_button = ttk.Button(
            btn_frame, text="Add to Job", command=self._on_add_to_job, style="Dark.TButton"
        )
        self.add_to_job_button.grid(row=0, column=2, sticky="ew", padx=(0, 2))
        self.preview_toggle_button = ttk.Button(
            btn_frame, text="Show Preview", command=self._toggle_pack_preview, state=tk.DISABLED, style="Dark.TButton"
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
        filtered = self._filter_visible_prompt_summaries(summaries)
        self._prompt_summaries = filtered
        return filtered

    def _populate_packs_for_selected_list(self) -> None:
        if not self.pack_listbox:
            return
        selected_names = set()
        try:
            selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
            selected_names = {
                self._current_pack_names[i] for i in selection if i < len(self._current_pack_names)
            }
        except Exception:
            selected_names = set()
        summaries = self._load_prompt_summaries() or self._prompt_summaries
        selected_list = (self.pack_list_var.get() or "").strip()
        packs: list[PromptPackSummary] = []
        if selected_list:
            pack_names = self.pack_list_manager.get_list(selected_list) or []
            packs = [summary for summary in summaries if summary.name in pack_names]
        if not packs:
            packs = summaries
        if self._manual_pack_names:
            summary_by_name = {summary.name: summary for summary in summaries}
            packs = [
                summary_by_name[pn]
                for pn in self._manual_pack_names
                if pn in summary_by_name
            ]
            if not packs:
                packs = [
                    PromptPackSummary(name=pn, description="", prompt_count=1, path=Path(""))
                    for pn in self._manual_pack_names
                ]
        self._current_pack_names = [summary.name for summary in packs]
        self.pack_listbox.delete(0, "end")
        for name in self._current_pack_names:
            self.pack_listbox.insert("end", name)
        if selected_names:
            for index, name in enumerate(self._current_pack_names):
                if name in selected_names:
                    self.pack_listbox.selection_set(index)
        self._update_pack_actions_state()

    def _populate_saved_recipe_combo(self) -> None:
        if not self.saved_recipe_combo:
            return
        presets = (
            self.config_manager.list_presets()
            if hasattr(self.config_manager, "list_presets")
            else []
        )
        self.saved_recipe_names = presets
        values = presets + [self._CREATE_SAVED_RECIPE_LABEL]
        self.saved_recipe_combo.config(values=values)
        if presets:
            self._apply_saved_recipe_selection(presets[0])
        else:
            self._apply_saved_recipe_selection(None)

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
        logger.debug("[SidebarPanel] _on_add_to_job called")
        if not self.pack_listbox:
            logger.debug("[SidebarPanel] No pack_listbox, returning")
            return

        selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
        controller = self.controller
        logger.debug(f"[SidebarPanel] Selection: {selection}, Controller: {controller}")

        # PromptPack-only: This should not execute if button state is correct, but guard anyway
        if not selection:
            logger.debug("[SidebarPanel] No selection, falling back to single prompt handler")
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
        logger.debug(f"[SidebarPanel] Pack IDs to add: {pack_ids}")
        if controller and hasattr(controller, "on_pipeline_add_packs_to_job"):
            logger.debug(f"[SidebarPanel] Calling controller.on_pipeline_add_packs_to_job({pack_ids})")
            try:
                controller.on_pipeline_add_packs_to_job(pack_ids)
                logger.debug("[SidebarPanel] Successfully called on_pipeline_add_packs_to_job")
            except Exception as e:
                import logging

                logger.debug(f"[SidebarPanel] EXCEPTION: {e}")
                logging.exception(f"Error adding packs to job: {e}")
        else:
            logger.debug(
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
        # Clear preview cache to force reload
        self._preview_cache.clear()
        # Reload packs from disk
        self._load_prompt_summaries()
        self.pack_list_manager.refresh()  # type: ignore[no-untyped-call]
        self._set_pack_list_values(self.pack_list_manager.get_list_names())
        self._populate_packs_for_selected_list()
        # Show brief visual feedback
        if hasattr(self, "refresh_packs_button"):
            original_text = self.refresh_packs_button.cget("text")
            self.refresh_packs_button.configure(text="Refreshed")
            self.after(1500, lambda: self.refresh_packs_button.configure(text=original_text))

    def _bind_app_state(self) -> None:
        app_state = getattr(self, "app_state", None)
        if app_state is None or not hasattr(app_state, "subscribe"):
            return
        self._app_state_visibility_listener = self._on_content_visibility_mode_changed
        try:
            app_state.subscribe("content_visibility_mode", self._app_state_visibility_listener)
        except Exception:
            self._app_state_visibility_listener = None

    def _filter_visible_prompt_summaries(
        self, summaries: list[PromptPackSummary]
    ) -> list[PromptPackSummary]:
        resolver = ContentVisibilityResolver(self._content_visibility_mode)
        visible: list[PromptPackSummary] = []
        for summary in summaries:
            if resolver.is_visible(self._build_prompt_pack_visibility_item(summary)):
                visible.append(summary)
        return visible

    def _build_prompt_pack_visibility_item(self, summary: PromptPackSummary) -> dict[str, Any]:
        prompt_texts: list[str] = []
        path = getattr(summary, "path", None)
        if isinstance(path, Path) and path.exists():
            try:
                prompts = read_prompt_pack(path)
            except Exception:
                prompts = []
            for prompt in prompts:
                if not isinstance(prompt, dict):
                    continue
                positive = str(prompt.get("positive") or "").strip()
                negative = str(prompt.get("negative") or "").strip()
                if positive:
                    prompt_texts.append(positive)
                if negative:
                    prompt_texts.append(negative)
        prompt_blob = "\n".join(prompt_texts)
        return {
            "name": summary.name,
            "description": summary.description,
            "prompt": prompt_blob,
            "positive_preview": prompt_blob,
        }

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        self._content_visibility_mode = str(
            mode or getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._populate_packs_for_selected_list()

    def _on_content_visibility_mode_changed(self) -> None:
        self.on_content_visibility_mode_changed()

    def set_pack_names(self, names: list[str]) -> None:
        """Best-effort helper for simple string lists (used by AppController)."""
        selected_names: set[str] = set()
        if self.pack_listbox:
            try:
                selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
                selected_names = {
                    self._current_pack_names[i]
                    for i in selection
                    if i < len(self._current_pack_names)
                }
            except Exception:
                selected_names = set()
        self._manual_pack_names = list(names)
        self._populate_packs_for_selected_list()
        if selected_names and self.pack_listbox:
            for index, name in enumerate(self._current_pack_names):
                if name in selected_names:
                    self.pack_listbox.selection_set(index)
            self._update_pack_actions_state()

    def _set_pack_list_values(self, names: list[str]) -> None:
        self.pack_list_names = names
        if self.pack_list_combo:
            self.pack_list_combo["values"] = names
            if names:
                self.pack_list_var.set(names[0])

    def _on_saved_recipe_selected(self, event: object = None) -> None:
        selected_recipe = self.saved_recipe_var.get()
        if selected_recipe == self._CREATE_SAVED_RECIPE_LABEL:
            self._handle_create_saved_recipe_action()
            return
        if not selected_recipe:
            self._apply_saved_recipe_selection(None)
            self.grid_columnconfigure(0, weight=1)
            return
        if self.controller and hasattr(self.controller, "on_saved_recipe_selected"):
            try:
                self.controller.on_saved_recipe_selected(selected_recipe)
            except Exception:
                pass
        self._last_valid_saved_recipe = selected_recipe
        self._update_config_source_label(selected_recipe)
        self.grid_columnconfigure(0, weight=1)

    def _on_saved_recipe_apply_to_working_state(self) -> None:
        recipe_name = self.saved_recipe_var.get()
        if not recipe_name:
            return
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_saved_recipe_apply_to_working_state"):
            try:
                controller.on_pipeline_saved_recipe_apply_to_working_state(recipe_name)
            except Exception:
                pass

    def _on_saved_recipe_apply_to_selected_packs(self) -> None:
        recipe_name = self.saved_recipe_var.get()
        if not recipe_name or not self.pack_listbox:
            return
        selection = self.pack_listbox.curselection()  # type: ignore[no-untyped-call]
        pack_ids = [
            self._current_pack_names[i] for i in selection if i < len(self._current_pack_names)
        ]
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_saved_recipe_apply_to_selected_packs"):
            try:
                controller.on_pipeline_saved_recipe_apply_to_selected_packs(recipe_name, pack_ids)
            except Exception:
                pass

    def _on_saved_recipe_load_to_pipeline(self) -> None:
        recipe_name = self.saved_recipe_var.get()
        if not recipe_name:
            return
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_saved_recipe_load_to_pipeline"):
            try:
                controller.on_pipeline_saved_recipe_load_to_pipeline(recipe_name)
            except Exception:
                pass

    def _on_saved_recipe_save_current(self) -> None:
        recipe_name = self.saved_recipe_var.get()
        if not recipe_name:
            return
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_saved_recipe_save_current"):
            try:
                controller.on_pipeline_saved_recipe_save_current(recipe_name)
            except Exception:
                pass

    def _on_saved_recipe_delete(self) -> None:
        recipe_name = self.saved_recipe_var.get()
        if not recipe_name:
            return
        controller = self.controller
        if controller and hasattr(controller, "on_pipeline_saved_recipe_delete"):
            try:
                controller.on_pipeline_saved_recipe_delete(recipe_name)
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
        self.run_mode_var.set("queue")
        label = ttk.Label(
            frame,
            text="Queue-only execution",
            style="Dark.TLabel",
        )
        label.grid(row=0, column=0, sticky="w", pady=(0, 2))
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
        # PR-GUI-213: The archived PipelineConfigPanel is no longer part of the
        # active GUI path. Stage toggles and sidebar-driven config are the only
        # supported live surface.
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

    def apply_global_prompt_config(self, config: dict[str, Any] | None) -> None:
        if not config:
            return
        pipeline = config.get("pipeline") or {}
        self.global_positive_enabled_var.set(
            bool(pipeline.get("apply_global_positive_txt2img", False))
        )
        self.global_negative_enabled_var.set(
            bool(pipeline.get("apply_global_negative_txt2img", True))
        )
        if "global_positive_prompt" in config:
            self.global_positive_text_var.set(str(config.get("global_positive_prompt") or ""))
        if "global_negative_prompt" in config:
            self.global_negative_text_var.set(str(config.get("global_negative_prompt") or ""))
    
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

    def get_base_generation_panel(self) -> BaseGenerationPanelV2 | None:
        return getattr(self, "base_generation_panel", None)

    def refresh_base_generation_from_webui(self) -> None:
        panel = self.get_base_generation_panel()
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

    def get_base_generation_overrides(self) -> dict[str, object]:
        panel = self.get_base_generation_panel()
        if panel and hasattr(panel, "get_overrides"):
            return panel.get_overrides()
        return {}

    def get_negative_prompt(self) -> str:
        # Negative prompt card removed; always return empty string
        return ""

    def get_resolution(self) -> tuple[int, int]:
        panel = self.get_base_generation_panel()
        if panel:
            overrides = panel.get_overrides()
            width = overrides.get("width", 512)
            height = overrides.get("height", 512)
            if isinstance(width, int) and isinstance(height, int):
                return width, height
        return 512, 512

    def get_resolution_preset(self) -> str:
        panel = self.get_base_generation_panel()
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

    # PR-PERSIST-001: State persistence methods
    def save_state(self) -> None:
        """Save sidebar state to disk."""
        try:
            # Get selected pack names
            selected_packs = []
            if self.pack_listbox:
                selection = self.pack_listbox.curselection()
                selected_packs = [
                    self._current_pack_names[i]
                    for i in selection
                    if i < len(self._current_pack_names)
                ]
            
            state = {
                "selected_list": self.pack_list_var.get() if hasattr(self, "pack_list_var") else "",
                "selected_packs": selected_packs,
                "schema_version": "2.6"
            }
            SIDEBAR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            SIDEBAR_STATE_PATH.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save sidebar state: {e}")

    def restore_state(self) -> None:
        """Restore sidebar state from disk."""
        if not SIDEBAR_STATE_PATH.exists():
            return
        
        try:
            state = json.loads(SIDEBAR_STATE_PATH.read_text())
            
            # Validate schema version
            if state.get("schema_version") != "2.6":
                logger.warning("Unsupported sidebar state schema, ignoring")
                return
            
            # Restore selected list
            selected_list = state.get("selected_list", "")
            if selected_list and hasattr(self, "pack_list_var"):
                if selected_list in self.pack_list_names:
                    self.pack_list_var.set(selected_list)
                    self._populate_packs_for_selected_list()
            
            # Restore selected packs (defer to next frame to ensure listbox is populated)
            selected_packs = state.get("selected_packs", [])
            if selected_packs and hasattr(self, "pack_listbox"):
                def restore_selection():
                    try:
                        self.pack_listbox.selection_clear(0, tk.END)
                        for pack_name in selected_packs:
                            if pack_name in self._current_pack_names:
                                idx = self._current_pack_names.index(pack_name)
                                self.pack_listbox.selection_set(idx)
                    except Exception as e:
                        logger.warning(f"Failed to restore pack selection: {e}")
                
                self.after(100, restore_selection)
            
            logger.debug(f"Restored sidebar state: {len(selected_packs)} packs selected")
        except Exception as e:
            logger.warning(f"Failed to restore sidebar state: {e}")

    def destroy(self) -> None:
        """Override destroy to save state before cleanup."""
        try:
            self.save_state()
        except Exception:
            pass
        listener = self._app_state_visibility_listener
        app_state = getattr(self, "app_state", None)
        if listener is not None and app_state is not None and hasattr(app_state, "unsubscribe"):
            try:
                app_state.unsubscribe("content_visibility_mode", listener)
            except Exception:
                pass
        super().destroy()


__all__ = ["SidebarPanelV2"]

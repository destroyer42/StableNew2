# Renamed from pipeline_tab_frame.py to pipeline_tab_frame_v2.py
# ...existing code...

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.views.stage_cards_panel import StageCardsPanel
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.scrolling import enable_mousewheel
from src.gui.tooltip import attach_tooltip
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.theme_v2 import SURFACE_FRAME_STYLE, CARD_FRAME_STYLE, BODY_LABEL_STYLE


class PipelineTabFrame(ttk.Frame):
    """Layout scaffold for the Pipeline tab."""
    # Panel width variables for easy adjustment
    SIDEBAR_MIN_WIDTH = 320
    CENTRAL_MIN_WIDTH = 480

    def __init__(
        self,
        master: tk.Misc,
        *,
        prompt_workspace_state: Any = None,
        app_state: Any = None,
        app_controller: Any = None,
        pipeline_controller: Any = None,
        theme: Any = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.prompt_workspace_state = prompt_workspace_state
        self.app_state = app_state
        self.app_controller = app_controller
        self.pipeline_controller = pipeline_controller
        self.theme = theme
        self.state_manager = getattr(self.pipeline_controller, "state_manager", None)

        # Body with three columns
        self.body_frame = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.body_frame.grid(row=0, column=0, sticky="nsew")
        self.body_frame.columnconfigure(0, weight=1)
        self.body_frame.columnconfigure(1, weight=2)
        self.body_frame.columnconfigure(2, weight=1)
        self.body_frame.rowconfigure(0, weight=1)

        # Scrollable left column for sidebar/global negative/prompt packs
        self.left_scroll = ScrollableFrame(self.body_frame, style=CARD_FRAME_STYLE)
        self.left_inner = self.left_scroll.inner
        self.left_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.left_inner.update_idletasks()
        self.body_frame.grid_propagate(False)

        self.sidebar = SidebarPanelV2(
            self.left_inner,
            controller=self.app_controller or self.pipeline_controller,
            app_state=self.app_state,
            theme=self.theme,
            on_change=lambda: self._handle_sidebar_change(),
        )
        self.sidebar.pack(fill="x", pady=(0, 16))

        # Pipeline config panel is now integrated into the sidebar

        self.stage_scroll = ScrollableFrame(self.body_frame, style=CARD_FRAME_STYLE)
        self.stage_cards_frame = self.stage_scroll.inner
        self.stage_scroll.grid(row=0, column=1, sticky="nsew", padx=4)
        self.stage_scroll.inner.update_idletasks()

        self.preview_panel = PreviewPanelV2(self.body_frame, controller=self.pipeline_controller, theme=self.theme)
        self.preview_panel.grid(row=0, column=2, sticky="nsew", padx=(4, 0))

        self.stage_cards_panel = StageCardsPanel(
            self.stage_cards_frame,
            controller=self.pipeline_controller,
            theme=self.theme,
            app_state=self.app_state,
            on_change=lambda: self._sync_state_overrides(),
        )
        self.stage_cards_panel.pack(fill="both", expand=True)
        self._sync_state_overrides()
        self._handle_sidebar_change()
        if self.app_state is not None:
            try:
                self.app_state.add_resource_listener(self._on_app_state_resources_changed)
                self.app_state.subscribe("job_draft", self._on_job_draft_changed)
            except Exception:
                pass
            self._on_app_state_resources_changed(self.app_state.resources)
            self._on_job_draft_changed()
        enable_mousewheel(self.left_inner)
        enable_mousewheel(self.stage_cards_frame)
        attach_tooltip(self.sidebar, "Pipeline controls and prompt packs.")

        self.pack_loader_compat = _PackLoaderCompat(self)
        self.left_compat = self.pack_loader_compat

    def update_pack_list(self, pack_names: list[str]) -> None:
        """Update the pack list in the pack loader compat."""
        self.pack_loader_compat.set_pack_names(pack_names)

    def _sync_state_overrides(self) -> None:
        """Push current stage card values into the pipeline controller state manager."""
        if not self.state_manager:
            return
        prompt_text = ""
        try:
            if self.prompt_workspace_state is not None:
                prompt_text = self.prompt_workspace_state.get_current_prompt_text()
        except Exception:
            prompt_text = ""

        overrides = self.stage_cards_panel.to_overrides(prompt_text=prompt_text)
        try:
            self.state_manager.pipeline_overrides = overrides
        except Exception:
            # If the state manager provides a setter, attempt to call it
            setter = getattr(self.state_manager, "set_pipeline_overrides", None)
            if callable(setter):
                try:
                    setter(overrides)
                except Exception:
                    pass

    def _apply_stage_visibility(self) -> None:
        enabled = set(self.sidebar.get_enabled_stages()) if hasattr(self, "sidebar") else {"txt2img", "img2img", "upscale"}
        if "txt2img" in enabled:
            self.stage_cards_panel.txt2img_card.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        else:
            self.stage_cards_panel.txt2img_card.grid_remove()
        if "img2img" in enabled:
            self.stage_cards_panel.img2img_card.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        else:
            self.stage_cards_panel.img2img_card.grid_remove()
        if "upscale" in enabled:
            self.stage_cards_panel.upscale_card.grid(row=2, column=0, sticky="nsew")
        else:
            self.stage_cards_panel.upscale_card.grid_remove()

    def _handle_sidebar_change(self) -> None:
        self._apply_stage_visibility()
        try:
            if hasattr(self, "preview_panel"):
                self.preview_panel.update_from_controls(self.sidebar)
        except Exception:
            pass

    def _on_app_state_resources_changed(self, resources: dict[str, list[Any]] | None) -> None:
        panel = getattr(self, "stage_cards_panel", None)
        if panel is not None:
            try:
                panel.apply_resource_update(resources)
            except Exception:
                pass

        # Pipeline config panel is now in sidebar, resources handled there

    def _on_job_draft_changed(self) -> None:
        if self.app_state is None:
            return
        try:
            job_draft = self.app_state.job_draft
            if hasattr(self, "preview_panel"):
                self.preview_panel.update_from_job_draft(job_draft)
        except Exception:
            pass

class _PackLoaderCompat:
    def __init__(self, owner: PipelineTabFrame) -> None:
        self._owner = owner
        # Pack selector for job/config tool
        ttk.Label(owner.left_inner, text="Pack Selector", style=BODY_LABEL_STYLE).pack(anchor="w", pady=(0, 4))
        
        # Pack list with multi-select
        self.packs_list = tk.Listbox(owner.left_inner, selectmode="extended", height=8)
        self.packs_list.pack(fill="both", expand=True, pady=(0, 4))
        enable_mousewheel(self.packs_list)
        
        # Buttons for config operations
        btn_frame = ttk.Frame(owner.left_inner)
        btn_frame.pack(fill="x", pady=(0, 8))
        self.load_config_button = ttk.Button(btn_frame, text="Load Config", command=self._on_load_config)
        self.load_config_button.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.apply_config_button = ttk.Button(btn_frame, text="Apply Config", command=self._on_apply_config)
        self.apply_config_button.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.add_to_job_button = ttk.Button(btn_frame, text="Add to Job", command=self._on_add_to_job)
        self.add_to_job_button.pack(side="left", fill="x", expand=True)
        
        # Preset combobox with actions
        ttk.Label(owner.left_inner, text="Pipeline Preset", style=BODY_LABEL_STYLE).pack(anchor="w", pady=(0, 2))
        preset_frame = ttk.Frame(owner.left_inner)
        preset_frame.pack(fill="x", pady=(0, 4))
        self.preset_combo = ttk.Combobox(preset_frame, values=[], state="readonly")
        self.preset_combo.pack(side="left", fill="x", expand=True)
        self.preset_menu_button = ttk.Menubutton(preset_frame, text="Actions", direction="below")
        self.preset_menu_button.pack(side="right", padx=(4, 0))
        
        # Populate preset combo
        self._populate_preset_combo()
        
        # Preset actions menu
        self.preset_menu = tk.Menu(self.preset_menu_button, tearoff=0)
        self.preset_menu.add_command(label="Apply to Default", command=self._on_preset_apply_to_default)
        self.preset_menu.add_command(label="Apply to Selected Packs", command=self._on_preset_apply_to_packs)
        self.preset_menu.add_command(label="Load to Stages", command=self._on_preset_load_to_stages)
        self.preset_menu.add_command(label="Save from Stages", command=self._on_preset_save_from_stages)
        self.preset_menu.add_command(label="Delete", command=self._on_preset_delete)
        self.preset_menu_button.config(menu=self.preset_menu)
        
        # Wire preset combo selection
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

    def _on_load_config(self) -> None:
        selection = self.packs_list.curselection()
        if len(selection) != 1:
            return  # Only allow single selection for load
        pack_index = selection[0]
        pack_names = list(self.packs_list.get(0, "end"))
        if pack_index < len(pack_names):
            pack_id = pack_names[pack_index]
            controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
            if controller and hasattr(controller, "on_pipeline_pack_load_config"):
                try:
                    controller.on_pipeline_pack_load_config(pack_id)
                except Exception:
                    pass

    def _on_apply_config(self) -> None:
        selection = self.packs_list.curselection()
        if not selection:
            return
        pack_names = list(self.packs_list.get(0, "end"))
        pack_ids = [pack_names[i] for i in selection if i < len(pack_names)]
        controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
        if controller and hasattr(controller, "on_pipeline_pack_apply_config"):
            try:
                controller.on_pipeline_pack_apply_config(pack_ids)
            except Exception:
                pass

    def _on_add_to_job(self) -> None:
        selection = self.packs_list.curselection()
        if not selection:
            return
        pack_names = list(self.packs_list.get(0, "end"))
        pack_ids = [pack_names[i] for i in selection if i < len(pack_names)]
        controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
        if controller and hasattr(controller, "on_pipeline_add_packs_to_job"):
            try:
                controller.on_pipeline_add_packs_to_job(pack_ids)
            except Exception:
                pass

    def _on_preset_selected(self, event) -> None:
        preset_name = self.preset_combo.get()
        controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
        if controller and hasattr(controller, "on_preset_selected"):
            try:
                controller.on_preset_selected(preset_name)
            except Exception:
                pass

    def _on_preset_apply_to_default(self) -> None:
        preset_name = self.preset_combo.get()
        controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
        if controller and hasattr(controller, "on_pipeline_preset_apply_to_default"):
            try:
                controller.on_pipeline_preset_apply_to_default(preset_name)
            except Exception:
                pass

    def _on_preset_apply_to_packs(self) -> None:
        preset_name = self.preset_combo.get()
        selection = self.packs_list.curselection()
        pack_names = list(self.packs_list.get(0, "end"))
        pack_ids = [pack_names[i] for i in selection if i < len(pack_names)]
        controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
        if controller and hasattr(controller, "on_pipeline_preset_apply_to_packs"):
            try:
                controller.on_pipeline_preset_apply_to_packs(preset_name, pack_ids)
            except Exception:
                pass

    def _on_preset_load_to_stages(self) -> None:
        preset_name = self.preset_combo.get()
        controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
        if controller and hasattr(controller, "on_pipeline_preset_load_to_stages"):
            try:
                controller.on_pipeline_preset_load_to_stages(preset_name)
            except Exception:
                pass

    def _on_preset_save_from_stages(self) -> None:
        preset_name = self.preset_combo.get()
        controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
        if controller and hasattr(controller, "on_pipeline_preset_save_from_stages"):
            try:
                controller.on_pipeline_preset_save_from_stages(preset_name)
            except Exception:
                pass

    def _on_preset_delete(self) -> None:
        preset_name = self.preset_combo.get()
        # TODO: Add confirmation dialog
        controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
        if controller and hasattr(controller, "on_pipeline_preset_delete"):
            try:
                controller.on_pipeline_preset_delete(preset_name)
            except Exception:
                pass

    def bind(self, *args: Any, **kwargs: Any) -> None:
        # No-op
        pass

    def set_pack_names(self, names: list[str]) -> None:
        self.packs_list.delete(0, "end")
        for name in names:
            self.packs_list.insert("end", name)

    def _populate_preset_combo(self) -> None:
        controller = getattr(self._owner, "app_controller", None) or getattr(self._owner, "pipeline_controller", None)
        if controller and hasattr(controller, "_config_manager"):
            presets = controller._config_manager.list_presets()
            self.preset_combo.config(values=presets)
            if presets:
                self.preset_combo.set(presets[0])

PipelineTabFrame = PipelineTabFrame

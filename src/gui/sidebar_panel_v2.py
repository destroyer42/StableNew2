from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Callable

class _SidebarCard(ttk.Frame):
    """Modular card for sidebar sections, matching central panel layout."""
    def __init__(self, master: tk.Misc, title: str, *, build_child: Callable[[ttk.Frame], ttk.Frame], **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        label = ttk.Label(header, text=title, style="Dark.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self.body = ttk.Frame(self, padding=6, style="Panel.TFrame")
        self.body.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        child = build_child(self.body)
        # Patch all child widgets for dark mode styles
        for w in child.winfo_children():
            if isinstance(w, ttk.Entry) or isinstance(w, ttk.Spinbox):
                w.configure(style="Dark.TEntry")
            elif isinstance(w, ttk.Combobox):
                w.configure(style="Dark.TCombobox")
            elif isinstance(w, ttk.Label):
                w.configure(style="Dark.TLabel")
        child.pack(fill="both", expand=True)
"""Sidebar panel scaffold for GUI v2."""

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .core_config_panel_v2 import CoreConfigPanelV2
from .model_list_adapter_v2 import ModelListAdapterV2
from .model_manager_panel_v2 import ModelManagerPanelV2
from .negative_prompt_panel_v2 import NegativePromptPanelV2
from .output_settings_panel_v2 import OutputSettingsPanelV2
from .prompt_pack_adapter_v2 import PromptPackAdapterV2, PromptPackSummary
from .prompt_pack_panel_v2 import PromptPackPanelV2
from .widgets.scrollable_frame_v2 import ScrollableFrame


class SidebarPanelV2(ttk.Frame):
    """Container for sidebar content (core config + negative prompt + packs + pipeline controls)."""
    # Card width variable for easy adjustment
    CARD_BASE_WIDTH = 240
    CARD_WIDTH = 80

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: object = None,
        app_state: object = None,
        prompt_pack_adapter: PromptPackAdapterV2 | None = None,
        on_apply_pack: Callable[[str, PromptPackSummary | None], None] | None = None,
        on_change: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=8, width=320, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self.prompt_pack_adapter = prompt_pack_adapter or PromptPackAdapterV2()
        self._on_apply_pack = on_apply_pack
        self._on_change = on_change

        # Legacy attributes for pipeline controls
        self.stage_states: dict[str, tk.BooleanVar] = {
            "txt2img": tk.BooleanVar(value=True),
            "img2img": tk.BooleanVar(value=True),
            "upscale": tk.BooleanVar(value=True),
        }
        self.run_mode_var = tk.StringVar(value="direct")
        self.run_scope_var = tk.StringVar(value="full")
        self.grid_propagate(False)

        # --- Config Source Banner ---
        self.config_source_label = ttk.Label(self, text="Defaults", style="Banner.TLabel")
        self.config_source_label.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # --- Packs Section ---
        from src.gui.prompt_pack_panel_v2 import PromptPackPanelV2
        from src.gui.prompt_pack_list_manager import PromptPackListManager
        self.pack_list_manager = PromptPackListManager()
        self.pack_list_names = self.pack_list_manager.get_list_names()
        self.pack_list_var = tk.StringVar(value=self.pack_list_names[0] if self.pack_list_names else "")
        self.pack_list_combo = ttk.Combobox(self, values=self.pack_list_names, textvariable=self.pack_list_var, state="readonly")
        self.pack_list_combo.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.pack_list_combo.bind("<<ComboboxSelected>>", self._on_pack_list_selected)

        self.pack_panel = PromptPackPanelV2(self, packs=[], on_apply=self._on_apply_pack_clicked)
        self.pack_panel.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        # --- Presets Section ---
        from src.utils.config import ConfigManager
        self.config_manager = ConfigManager()
        self.preset_names = self.config_manager.list_presets() if hasattr(self.config_manager, "list_presets") else []
        self.preset_var = tk.StringVar(value=self.preset_names[0] if self.preset_names else "")
        self.preset_dropdown = ttk.Combobox(self, values=self.preset_names, textvariable=self.preset_var, state="readonly")
        self.preset_dropdown.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.preset_dropdown.bind("<<ComboboxSelected>>", self._on_preset_selected)

        # --- Initial population ---
        self._populate_packs_for_selected_list()

    def _on_pack_list_selected(self, event: object = None) -> None:
        self._populate_packs_for_selected_list()

    def _populate_packs_for_selected_list(self) -> None:
        selected_list = self.pack_list_var.get()
        pack_names = self.pack_list_manager.get_list(selected_list) or []
        # TODO: Load PromptPackSummary objects for these pack names
        # For now, just pass names as dummy summaries
        from pathlib import Path
        packs = [PromptPackSummary(name=pn, description="", prompt_count=1, path=Path("")) for pn in pack_names]
        self.pack_panel.set_packs(packs)

    def _on_apply_pack_clicked(self, summary: object) -> None:
        # Wire to PromptTabFrame.apply_prompt_pack if available
        if self.controller and hasattr(self.controller, "apply_prompt_pack"):
            self.controller.apply_prompt_pack(summary)
        # Optionally update config source banner
        self.config_source_label.config(text="Ad-hoc configuration")

    def _on_preset_selected(self, event: object = None) -> None:
        selected_preset = self.preset_var.get()
        # Apply preset config via config manager
        if hasattr(self.config_manager, "load_preset"):
            self.config_manager.load_preset(selected_preset)
        self.config_source_label.config(text=f"Preset: {selected_preset}")
        self.grid_columnconfigure(0, weight=1)


        self.core_config_card = _SidebarCard(
            self,
            title="Core Config",
            build_child=lambda parent: CoreConfigPanelV2(parent, show_label=False)
        )
        self.core_config_card.grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 4))


        self.output_settings_card = _SidebarCard(
            self,
            title="Output Settings",
            build_child=lambda parent: OutputSettingsPanelV2(parent)
        )
        self.output_settings_card.grid(row=6, column=0, sticky="ew", padx=8, pady=(0, 4))


        self.global_negative_enabled_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.global_negative_text_var: tk.StringVar = tk.StringVar(value="")

        self.model_adapter = ModelListAdapterV2(lambda: getattr(self.controller, "client", None))
        # TODO: Replace with actual sampler adapter if available
        self.sampler_adapter = self.model_adapter
        self.core_config_card = _SidebarCard(
            self,
            title="Core Config",
            build_child=lambda parent: CoreConfigPanelV2(
                parent,
                show_label=False,
                include_vae=True,
                include_refresh=True,
                model_adapter=self.model_adapter,
                vae_adapter=self.model_adapter,
                sampler_adapter=self.sampler_adapter
            )
        )
        self.core_config_card.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 4))

        self.output_settings_card = _SidebarCard(
            self,
            title="Output Settings",
            build_child=lambda parent: OutputSettingsPanelV2(parent)
        )
        self.output_settings_card.grid(row=6, column=0, sticky="ew", padx=8, pady=(0, 4))

        self.global_negative_card = _SidebarCard(
            self,
            title="Global Negative",
            build_child=lambda parent: self._build_global_negative_section(parent)
        )
        self.global_negative_card.grid(row=7, column=0, sticky="ew", padx=8, pady=(0, 4))


        self.prompt_pack_card = _SidebarCard(
            self,
            title="Prompt Pack",
            build_child=lambda parent: self._build_prompt_pack_section(parent)
        )
        self.prompt_pack_card.grid(row=8, column=0, sticky="ew", padx=8, pady=(0, 4))

    def _build_stages_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        for idx, (name, var) in enumerate(self.stage_states.items()):
            cb = ttk.Checkbutton(frame, text=name.title(), variable=var, command=self._emit_change, style="Dark.TCheckbutton")
            cb.grid(row=idx, column=0, sticky="w", pady=2)
        return frame

    def _build_run_mode_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        rb1 = ttk.Radiobutton(frame, text="Direct", value="direct", variable=self.run_mode_var, command=self._on_run_mode_change, style="Dark.TRadiobutton")
        rb1.grid(row=0, column=0, sticky="w", pady=2)
        rb2 = ttk.Radiobutton(frame, text="Queue", value="queue", variable=self.run_mode_var, command=self._on_run_mode_change, style="Dark.TRadiobutton")
        rb2.grid(row=1, column=0, sticky="w", pady=2)
        return frame

    def _build_prompt_pack_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        packs = []
        if self.prompt_pack_adapter:
            try:
                packs = self.prompt_pack_adapter.load_summaries()
            except Exception:
                packs = []
        self.prompt_pack_panel = PromptPackPanelV2(
            frame,
            packs=packs,
            on_apply=self._handle_apply_pack,
        )
        self.prompt_pack_panel.pack(fill="both", expand=True)
        return frame

    def _build_run_scope_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        for idx, (label, val) in enumerate([("Selected only", "selected"), ("From selected", "from_selected"), ("Full pipeline", "full")]):
            rb = ttk.Radiobutton(frame, text=label, value=val, variable=self.run_scope_var, command=self._emit_change, style="Dark.TRadiobutton")
            rb.grid(row=idx, column=0, sticky="w", pady=2)
        return frame

    def _build_global_negative_section(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        enable_cb = ttk.Checkbutton(
            frame,
            text="Enable",
            variable=self.global_negative_enabled_var,
            style="Dark.TCheckbutton",
        )
        enable_cb.grid(row=0, column=0, sticky="w", pady=(0, 2))
        entry = ttk.Entry(
            frame,
            textvariable=self.global_negative_text_var,
            width=24,
        )
        entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 2))
        frame.columnconfigure(1, weight=1)
        return frame

        # Prompt Pack Panel (below grid)
        # Removed obsolete code: old layout and duplicate panel instantiations

    def refresh_prompt_packs(self) -> None:
        if not self.prompt_pack_adapter:
            return
            # Add vertical padding between all direct children for spacing
            for child in self.winfo_children():
                child.grid_configure(pady=8)
        try:
            summaries = self.prompt_pack_adapter.load_summaries()
        except Exception:
            summaries = []
        # Prompt pack panel functionality removed in card refactor

    def set_pack_names(self, names: list[str]) -> None:
        """Best-effort helper for simple string lists (used by AppController)."""
        # set_pack_names functionality removed in card refactor

    # --- Pipeline control helpers -------------------------------------
    def get_enabled_stages(self) -> list[str]:
        return [name for name, var in self.stage_states.items() if var.get()]

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

    def _handle_apply_pack(self, summary: PromptPackSummary) -> None:
        prompt_text = ""
        if self.prompt_pack_adapter:
            try:
                prompt_text = self.prompt_pack_adapter.get_base_prompt(summary)
            except Exception:
                prompt_text = ""
        if self._on_apply_pack:
            try:
                self._on_apply_pack(prompt_text, summary)
            except Exception:
                pass

    def get_core_config_panel(self) -> CoreConfigPanelV2 | None:
        panel = getattr(self, "core_config_card", None)
        body = getattr(panel, "body", None)
        if body:
            for child in body.winfo_children():
                if isinstance(child, CoreConfigPanelV2):
                    return child
        return None

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
        for child in self.core_config_card.body.winfo_children():
            if hasattr(child, 'get_overrides'):
                result = child.get_overrides()
                if isinstance(result, dict):
                    return result
        return {}

    def get_negative_prompt(self) -> str:
        # Negative prompt card removed; always return empty string
        return ""

    def get_resolution(self) -> tuple[int, int]:
        for child in self.core_config_card.body.winfo_children():
            if hasattr(child, 'resolution_panel') and hasattr(child.resolution_panel, 'get_resolution'):
                result = child.resolution_panel.get_resolution()
                if (isinstance(result, tuple) and len(result) == 2 and all(isinstance(x, int) for x in result)):
                    return result
        return 512, 512

    def get_resolution_preset(self) -> str:
        for child in self.core_config_card.body.winfo_children():
            if hasattr(child, 'resolution_panel') and hasattr(child.resolution_panel, 'get_preset_label'):
                result = child.resolution_panel.get_preset_label()
                if isinstance(result, str):
                    return result
        return ""

    def get_output_overrides(self) -> dict[str, object]:
        panel = getattr(self, "output_settings_panel", None)
        if panel:
            return panel.get_output_overrides()  # type: ignore
        return {}


__all__ = ["SidebarPanelV2"]

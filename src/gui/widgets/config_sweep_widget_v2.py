"""Config Sweep Widget for PR-CORE-E.

Provides UI for defining config sweep variants: same prompt, multiple configs.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from src.gui import theme as theme_mod


class ConfigSweepWidgetV2(ttk.Frame):
    """Widget for config sweep management (PR-CORE-E)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        theme: object = None,
        config_manager: object = None,
        on_change: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        """Initialize config sweep widget.
        
        Args:
            master: Parent widget
            theme: Theme object for styling
            config_manager: Config manager for reading global negative
            on_change: Callback when sweep config changes
        """
        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        super().__init__(master, style=style_name, **kwargs)
        
        self.theme = theme
        self.config_manager = config_manager
        self.on_change_callback = on_change
        self.variants: list[dict[str, Any]] = []
        
        self._build_ui()
        self._is_collapsed = False

    def _build_ui(self) -> None:
        """Build the config sweep UI."""
        # Header with collapse toggle
        header_frame = ttk.Frame(self, style=getattr(self.theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE))
        header_frame.pack(fill=tk.X, pady=(0, 4))
        
        self.collapse_btn = ttk.Button(
            header_frame,
            text="▾ Config Sweep",
            width=20,
            command=self._toggle_collapse,
        )
        self.collapse_btn.pack(side=tk.LEFT)
        
        self.enable_var = tk.BooleanVar(value=False)
        self.enable_check = ttk.Checkbutton(
            header_frame,
            text="Enable",
            variable=self.enable_var,
            command=self._on_enable_toggle,
        )
        self.enable_check.pack(side=tk.LEFT, padx=(8, 0))
        
        # Collapsible body
        self.body_frame = ttk.Frame(self, style=getattr(self.theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE))
        self.body_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        
        # Variant list section
        variant_label = ttk.Label(
            self.body_frame,
            text="Variants:",
            style=getattr(self.theme, "STATUS_LABEL_STYLE", theme_mod.STATUS_LABEL_STYLE),
        )
        variant_label.pack(anchor=tk.W, pady=(0, 4))
        
        # Scrollable variant list
        list_frame = ttk.Frame(self.body_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.variant_listbox = tk.Listbox(
            list_frame,
            height=4,
            yscrollcommand=scrollbar.set,
            selectmode=tk.SINGLE,
        )
        self.variant_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.variant_listbox.yview)
        
        # Variant management buttons
        btn_frame = ttk.Frame(self.body_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 8))
        
        self.add_btn = ttk.Button(btn_frame, text="+ Add Variant", command=self._add_variant)
        self.add_btn.pack(side=tk.LEFT, padx=(0, 4))
        
        self.remove_btn = ttk.Button(btn_frame, text="Remove", command=self._remove_variant)
        self.remove_btn.pack(side=tk.LEFT)
        
        # Global negative section
        separator = ttk.Separator(self.body_frame, orient=tk.HORIZONTAL)
        separator.pack(fill=tk.X, pady=(8, 8))
        
        global_neg_label = ttk.Label(
            self.body_frame,
            text="Global Negative:",
            style=getattr(self.theme, "STATUS_LABEL_STYLE", theme_mod.STATUS_LABEL_STYLE),
        )
        global_neg_label.pack(anchor=tk.W, pady=(0, 4))
        
        # Read-only display of global negative
        self.global_neg_text = tk.Text(
            self.body_frame,
            height=2,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#f0f0f0",
            relief=tk.SUNKEN,
            borderwidth=1,
        )
        self.global_neg_text.pack(fill=tk.X, pady=(0, 4))
        
        # Apply global negative toggles per stage
        apply_frame = ttk.Frame(self.body_frame)
        apply_frame.pack(fill=tk.X)
        
        apply_label = ttk.Label(
            apply_frame,
            text="Apply to stages:",
            style=getattr(self.theme, "STATUS_LABEL_STYLE", theme_mod.STATUS_LABEL_STYLE),
        )
        apply_label.grid(row=0, column=0, sticky="w", pady=(0, 4))
        
        self.apply_txt2img_var = tk.BooleanVar(value=True)
        self.apply_img2img_var = tk.BooleanVar(value=True)
        self.apply_upscale_var = tk.BooleanVar(value=True)
        self.apply_adetailer_var = tk.BooleanVar(value=True)
        
        ttk.Checkbutton(apply_frame, text="txt2img", variable=self.apply_txt2img_var).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(apply_frame, text="img2img", variable=self.apply_img2img_var).grid(row=1, column=1, sticky="w", padx=(8, 0))
        ttk.Checkbutton(apply_frame, text="upscale", variable=self.apply_upscale_var).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(apply_frame, text="adetailer", variable=self.apply_adetailer_var).grid(row=2, column=1, sticky="w", padx=(8, 0))
        
        # Load global negative from config manager
        self._load_global_negative()
        
        # Initial state: disabled
        self._update_controls_state()

    def _toggle_collapse(self) -> None:
        """Toggle collapse/expand of the widget body."""
        self._is_collapsed = not self._is_collapsed
        if self._is_collapsed:
            self.body_frame.pack_forget()
            self.collapse_btn.config(text="▸ Config Sweep")
        else:
            self.body_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
            self.collapse_btn.config(text="▾ Config Sweep")

    def _on_enable_toggle(self) -> None:
        """Handle enable checkbox toggle."""
        self._update_controls_state()
        if self.on_change_callback:
            self.on_change_callback()

    def _update_controls_state(self) -> None:
        """Enable/disable controls based on enable checkbox."""
        is_enabled = self.enable_var.get()
        state = "normal" if is_enabled else "disabled"
        
        self.variant_listbox.config(state=state)
        self.add_btn.config(state=state)
        self.remove_btn.config(state=state)

    def _load_global_negative(self) -> None:
        """Load global negative prompt from config manager."""
        if not self.config_manager or not hasattr(self.config_manager, "get_global_negative_prompt"):
            return
        
        try:
            global_neg = self.config_manager.get_global_negative_prompt() or "(none)"
            self.global_neg_text.config(state=tk.NORMAL)
            self.global_neg_text.delete("1.0", tk.END)
            self.global_neg_text.insert("1.0", global_neg)
            self.global_neg_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _add_variant(self) -> None:
        """Add a new config variant."""
        # Open simple dialog for variant config
        dialog = ConfigVariantDialog(self, title="Add Config Variant")
        if dialog.result:
            variant = dialog.result
            self.variants.append(variant)
            self._refresh_variant_list()
            if self.on_change_callback:
                self.on_change_callback()

    def _remove_variant(self) -> None:
        """Remove selected variant."""
        selection = self.variant_listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        if 0 <= index < len(self.variants):
            self.variants.pop(index)
            self._refresh_variant_list()
            if self.on_change_callback:
                self.on_change_callback()

    def _refresh_variant_list(self) -> None:
        """Refresh the variant listbox."""
        self.variant_listbox.delete(0, tk.END)
        for variant in self.variants:
            label = variant.get("label", "Unnamed")
            cfg = variant.get("overrides", {}).get("txt2img.cfg_scale", "?")
            steps = variant.get("overrides", {}).get("txt2img.steps", "?")
            self.variant_listbox.insert(tk.END, f"{label} (CFG: {cfg}, Steps: {steps})")

    def get_sweep_config(self) -> dict[str, Any]:
        """Get current config sweep configuration.
        
        Returns:
            Dict with enabled flag, variants list, and global negative settings.
        """
        return {
            "enabled": self.enable_var.get(),
            "variants": list(self.variants),
            "apply_global_negative_txt2img": self.apply_txt2img_var.get(),
            "apply_global_negative_img2img": self.apply_img2img_var.get(),
            "apply_global_negative_upscale": self.apply_upscale_var.get(),
            "apply_global_negative_adetailer": self.apply_adetailer_var.get(),
        }

    def set_sweep_config(self, config: dict[str, Any]) -> None:
        """Load config sweep configuration.
        
        Args:
            config: Config dict with enabled, variants, and apply_global_negative flags.
        """
        self.enable_var.set(config.get("enabled", False))
        self.variants = list(config.get("variants", []))
        self._refresh_variant_list()
        
        self.apply_txt2img_var.set(config.get("apply_global_negative_txt2img", True))
        self.apply_img2img_var.set(config.get("apply_global_negative_img2img", True))
        self.apply_upscale_var.set(config.get("apply_global_negative_upscale", True))
        self.apply_adetailer_var.set(config.get("apply_global_negative_adetailer", True))
        
        self._update_controls_state()


class ConfigVariantDialog(tk.Toplevel):
    """Simple dialog for creating a config variant."""

    def __init__(self, parent: tk.Misc, title: str = "Config Variant") -> None:
        super().__init__(parent)
        self.title(title)
        self.result: dict[str, Any] | None = None
        
        self.transient(parent)
        self.grab_set()
        
        self._build_ui()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
        
        self.wait_window()

    def _build_ui(self) -> None:
        """Build dialog UI."""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Label
        ttk.Label(main_frame, text="Variant Label:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.label_entry = ttk.Entry(main_frame, width=30)
        self.label_entry.grid(row=0, column=1, pady=(0, 4))
        self.label_entry.insert(0, "variant_1")
        
        # CFG Scale
        ttk.Label(main_frame, text="CFG Scale:").grid(row=1, column=0, sticky="w", pady=(0, 4))
        self.cfg_entry = ttk.Entry(main_frame, width=30)
        self.cfg_entry.grid(row=1, column=1, pady=(0, 4))
        self.cfg_entry.insert(0, "7.0")
        
        # Steps
        ttk.Label(main_frame, text="Steps:").grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.steps_entry = ttk.Entry(main_frame, width=30)
        self.steps_entry.grid(row=2, column=1, pady=(0, 4))
        self.steps_entry.insert(0, "20")
        
        # Sampler
        ttk.Label(main_frame, text="Sampler:").grid(row=3, column=0, sticky="w", pady=(0, 4))
        self.sampler_entry = ttk.Entry(main_frame, width=30)
        self.sampler_entry.grid(row=3, column=1, pady=(0, 4))
        self.sampler_entry.insert(0, "DPM++ 2M")
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(8, 0))
        
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side=tk.LEFT)
        
        self.label_entry.focus()

    def _on_ok(self) -> None:
        """Handle OK button."""
        label = self.label_entry.get().strip()
        if not label:
            return
        
        try:
            cfg = float(self.cfg_entry.get().strip() or "7.0")
            steps = int(self.steps_entry.get().strip() or "20")
            sampler = self.sampler_entry.get().strip() or "DPM++ 2M"
            
            self.result = {
                "label": label,
                "overrides": {
                    "txt2img.cfg_scale": cfg,
                    "txt2img.steps": steps,
                    "txt2img.sampler_name": sampler,
                },
                "index": 0,  # Will be set by controller
            }
            self.destroy()
        except ValueError:
            pass

    def _on_cancel(self) -> None:
        """Handle Cancel button."""
        self.result = None
        self.destroy()


__all__ = ["ConfigSweepWidgetV2", "ConfigVariantDialog"]

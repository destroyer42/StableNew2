"""Guided authoring of up to two ordered ControlNet units; resource discovery is off Tk, never a compiler.

The slot's ``controlnet.v1`` declaration (a plain JSON value) is the single source of truth. The panel renders it and every
operator edit produces a new declaration that the parent persists through the workspace state (PR-GUI-UX-550 adds the
guided purpose choice, reference-map browser, model guidance and readiness text on top of the PR-IMG-CNET-220 form).
Friendly labels are presentation only: the persisted modality stays ``openpose``, ``canny`` or ``depth``.

Nothing here builds a backend payload, probes Forge, hashes a file on Tk or decides execution. Selecting, refreshing and
inspecting never change or save a declaration; a saved value the resources cannot satisfy is shown with the reason and
kept. The readiness text is the *editor* check; Preview and Forge admission remain the authorities.
"""

from __future__ import annotations

import copy
import queue
import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import messagebox, ttk
from typing import Any, cast

from src.assets.controlnet_structure import list_controlnet_models
from src.conditioning.controlnet import CONTRACT, MODALITIES
from src.conditioning.openpose import (
    CONTROL_MODES,
    DEFAULT_GUIDANCE_END,
    DEFAULT_GUIDANCE_START,
    DEFAULT_WEIGHT,
    MAX_WEIGHT,
    MIN_WEIGHT,
    RESIZE_MODES,
)
from src.conditioning.openpose_catalog import LibraryListing, controlnet_folder, refresh_listing
from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.gui.widgets.reference_map_browser import ReferenceMapBrowser, Runner
from src.gui_v2.controlnet_guidance import (
    CONTROL_MODE_HELP,
    EMPTY_LIBRARY_HELP,
    GUIDANCE_HELP,
    MODALITY_GUIDES,
    MODALITY_LABELS,
    NO_PREPROCESSING_NOTE,
    RESIZE_HELP,
    SCOPE_NOTE,
    STRENGTH_HELP,
    accepts_new_unit,
    advanced_is_customized,
    describe_readiness,
    documented_models,
    guide_text,
    modality_from_label,
    modality_label,
    model_choices,
    new_unit,
    ordered_summary,
    recommended_model,
    unit_choice_label,
)

_NUMERIC = {
    "weight": (MIN_WEIGHT, MAX_WEIGHT),
    "guidance_start": (0.0, 1.0),
    "guidance_end": (0.0, 1.0),
}
_NUMERIC_DEFAULTS = {
    "weight": DEFAULT_WEIGHT,
    "guidance_start": DEFAULT_GUIDANCE_START,
    "guidance_end": DEFAULT_GUIDANCE_END,
}
_LEGACY_SWITCH_WARNING = (
    "This slot uses the legacy OpenPose reference. Ordered units cannot coexist with it in one slot.\n\n"
    "Continuing removes the legacy OpenPose reference and its settings from this slot's pack (save the pack to keep "
    "the change). Nothing is converted automatically; you will choose each unit's map and model yourself.\n\n"
    "Switch this slot to ordered units?"
)


class ControlNetUnitsPanel(ttk.LabelFrame):
    def __init__(
        self,
        parent: Any,
        *,
        on_change_callback: Callable[[], None] | None = None,
        on_replace_legacy: Callable[[], None] | None = None,
        registry_factory: Callable[[], Any] | None = None,
        runner: Runner | None = None,
        confirm: Callable[[str, str], bool] | None = None,
        lazy: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            parent,
            text="Guided ControlNet conditioning (ordered units, SDXL / Forge)",
            padding=6,
            **kwargs,
        )
        self._callback = on_change_callback
        self._on_replace_legacy = on_replace_legacy
        self._registry_factory = registry_factory
        self._confirm = confirm or (
            lambda title, message: bool(messagebox.askyesno(title, message, parent=self))
        )
        self._raw: Any = None
        self._legacy: Any = None
        self._selected = 0
        self._target: Any = None
        self._hidden = False
        self._listing = LibraryListing()
        self._models: list[Any] = []
        self._loaded = False
        self._scanning = False
        self._first_map_done = not lazy
        self._results: queue.Queue[Any] = queue.Queue()
        self._poll: str | None = None
        self._suppress = False
        self._wrap_labels: list[ttk.Label] = []
        self.variables: dict[str, tk.StringVar] = {}
        self.controls: dict[str, Any] = {}
        self.columnconfigure(0, weight=1)
        self._build_legacy_notice()
        self._build_chooser()
        self._build_unit_bar()
        self.detail = ttk.Frame(self)
        self.detail.columnconfigure(0, weight=1)
        self._build_detail(runner, lazy)
        self._build_readiness()
        self.bind("<Configure>", self._on_resize, add="+")
        if lazy:
            self.bind(
                "<Map>", self._on_first_map, add="+"
            )  # nothing is scanned until the editor is first shown
        self._render()

    # ------------------------------------------------------------------ construction

    def _label(self, parent: tk.Misc, **kwargs: Any) -> ttk.Label:
        label = ttk.Label(parent, justify="left", wraplength=520, **kwargs)
        self._wrap_labels.append(label)
        return label

    def _build_legacy_notice(self) -> None:
        self.legacy_frame = ttk.Frame(self)
        self.legacy_var = tk.StringVar()
        self._label(self.legacy_frame, textvariable=self.legacy_var).pack(fill="x")
        self.replace_legacy_button = ttk.Button(
            self.legacy_frame,
            text="Switch this slot to ordered units…",
            command=self.replace_legacy,
        )
        self.replace_legacy_button.pack(anchor="w", pady=(4, 0))
        self.legacy_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))

    def _build_chooser(self) -> None:
        self.chooser = ttk.LabelFrame(self, text="Add a unit that controls…", padding=4)
        self.chooser.grid(row=1, column=0, sticky="ew")
        self.add_buttons: dict[str, ttk.Button] = {}
        for column, guide in enumerate(MODALITY_GUIDES):
            button = ttk.Button(
                self.chooser,
                text=guide.label,
                command=partial(self.add_unit, guide.modality),
            )
            button.grid(row=0, column=column, sticky="ew", padx=2)
            self.chooser.columnconfigure(column, weight=1)
            self.add_buttons[guide.modality] = button
        self._label(
            self.chooser,
            text="Each unit uses one pre-rendered reference map. Up to two units, applied in the order shown.",
        ).grid(row=1, column=0, columnspan=len(MODALITY_GUIDES), sticky="ew", pady=(4, 0))

    def _build_unit_bar(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        bar.columnconfigure(0, weight=1)
        self.unit_var = tk.StringVar(value="")
        self.unit_combo = ttk.Combobox(bar, textvariable=self.unit_var, state="readonly", width=30)
        self.unit_combo.grid(row=0, column=0, sticky="ew")
        self.unit_combo.bind("<<ComboboxSelected>>", self._select)
        self.unit_buttons: dict[str, ttk.Button] = {}
        for column, (label, command) in enumerate(
            (
                ("Remove", self.remove_unit),
                ("Move up", self.move_up),
                ("Move down", self.move_down),
                ("Refresh", self.refresh_library),
            ),
            1,
        ):
            button = ttk.Button(bar, text=label, command=command)
            button.grid(row=0, column=column, padx=(4, 0))
            self.unit_buttons[label] = button

    def _build_detail(self, runner: Runner | None, lazy: bool) -> None:
        detail = self.detail
        self.enabled_var = tk.BooleanVar(value=True)
        self.enabled_check = ttk.Checkbutton(
            detail,
            text="Enable this unit (a disabled unit is kept but not sent)",
            variable=self.enabled_var,
            command=self._edit,
        )
        self.enabled_check.grid(row=0, column=0, sticky="w")
        purpose = ttk.Frame(detail)
        purpose.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        purpose.columnconfigure(1, weight=1)
        ttk.Label(purpose, text="This unit controls").grid(row=0, column=0, sticky="w")
        self.variables["modality"] = tk.StringVar()
        self.modality_label_var = tk.StringVar()
        self.modality_combo = ttk.Combobox(
            purpose, textvariable=self.modality_label_var, values=MODALITY_LABELS, state="readonly"
        )
        self.modality_combo.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.modality_combo.bind("<<ComboboxSelected>>", self._on_modality_chosen)
        self.controls["modality"] = self.modality_combo
        self.guide_var = tk.StringVar()
        self._label(detail, textvariable=self.guide_var).grid(
            row=2, column=0, sticky="ew", pady=(2, 0)
        )

        reference = ttk.LabelFrame(
            detail, text="Reference map (pre-rendered, from models/OpenPose)", padding=4
        )
        reference.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        reference.columnconfigure(0, weight=1)
        self.browser = ReferenceMapBrowser(
            reference,
            on_select=self._on_map_picked,
            registry_factory=self._registry_factory,
            runner=runner,
            lazy=lazy,
        )
        self.browser.grid(row=0, column=0, sticky="ew")
        self.variables["asset"] = tk.StringVar()
        asset_entry = ttk.Entry(reference, textvariable=self.variables["asset"], state="readonly")
        asset_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.controls["asset"] = asset_entry

        model_box = ttk.LabelFrame(
            detail, text="ControlNet model (from models/ControlNet)", padding=4
        )
        model_box.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        model_box.columnconfigure(0, weight=1)
        self.variables["model"] = tk.StringVar()
        self.model_combo = ttk.Combobox(
            model_box, textvariable=self.variables["model"], state="readonly"
        )
        self.model_combo.grid(row=0, column=0, sticky="ew")
        self.model_combo.bind("<<ComboboxSelected>>", self._edit)
        self.controls["model"] = self.model_combo
        self.use_recommended_button = ttk.Button(
            model_box, text="Use recommended", command=self.use_recommended_model
        )
        self.use_recommended_button.grid(row=0, column=1, padx=(4, 0))
        self.model_hint_var = tk.StringVar()
        self._label(model_box, textvariable=self.model_hint_var).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        strength = ttk.Frame(detail)
        strength.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        strength.columnconfigure(1, weight=1)
        ttk.Label(strength, text=f"Strength ({MIN_WEIGHT:g}–{MAX_WEIGHT:g})").grid(
            row=0, column=0, sticky="w"
        )
        self.variables["weight"] = tk.StringVar()
        self.controls["weight"] = self._number_entry(strength, "weight", MIN_WEIGHT, MAX_WEIGHT)
        self.controls["weight"].grid(row=0, column=1, sticky="w", padx=(6, 0))
        self._label(strength, text=STRENGTH_HELP).grid(row=1, column=0, columnspan=2, sticky="ew")

        self.advanced_open = False
        self.advanced_button = ttk.Button(detail, text="Advanced ▸", command=self.toggle_advanced)
        self.advanced_button.grid(row=6, column=0, sticky="w", pady=(6, 0))
        self._build_advanced(detail)

    def _build_advanced(self, detail: ttk.Frame) -> None:
        self.advanced = ttk.Frame(detail)
        self.advanced.columnconfigure(1, weight=1)
        self._label(self.advanced, text=GUIDANCE_HELP).grid(
            row=0, column=0, columnspan=2, sticky="ew"
        )
        row = 1
        for key, label in (
            ("guidance_start", "Guidance start (0–1)"),
            ("guidance_end", "Guidance end (0–1)"),
        ):
            ttk.Label(self.advanced, text=label).grid(row=row, column=0, sticky="w")
            self.variables[key] = tk.StringVar()
            self.controls[key] = self._number_entry(self.advanced, key, 0.0, 1.0)
            self.controls[key].grid(row=row, column=1, sticky="w", padx=(6, 0))
            row += 1
        self.control_mode_help_var = tk.StringVar()
        self.resize_help_var = tk.StringVar()
        for key, label, choices, help_var in (
            ("control_mode", "Control mode", CONTROL_MODES, self.control_mode_help_var),
            ("resize_mode", "Resize", RESIZE_MODES, self.resize_help_var),
        ):
            ttk.Label(self.advanced, text=label).grid(row=row, column=0, sticky="w")
            self.variables[key] = tk.StringVar()
            combo = ttk.Combobox(
                self.advanced, textvariable=self.variables[key], values=choices, state="readonly"
            )
            combo.grid(row=row, column=1, sticky="ew", padx=(6, 0))
            combo.bind("<<ComboboxSelected>>", self._edit)
            self.controls[key] = combo
            self._label(self.advanced, textvariable=help_var).grid(
                row=row + 1, column=0, columnspan=2, sticky="ew"
            )
            row += 2

    def _number_entry(self, parent: tk.Misc, key: str, low: float, high: float) -> ttk.Spinbox:
        spin = ttk.Spinbox(
            parent,
            from_=low,
            to=high,
            increment=0.05,
            textvariable=self.variables[key],
            width=8,
            command=self._edit,
        )
        spin.bind("<Return>", self._edit)
        spin.bind("<FocusOut>", self._edit)
        return spin

    def _build_readiness(self) -> None:
        self.summary_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.notice_var = tk.StringVar()
        self._label(self, textvariable=self.summary_var).grid(
            row=5, column=0, sticky="ew", pady=(6, 0)
        )
        self._label(self, textvariable=self.status_var).grid(
            row=6, column=0, sticky="ew", pady=(4, 0)
        )
        self._label(self, textvariable=self.notice_var).grid(row=7, column=0, sticky="ew")
        self._label(self, text=NO_PREPROCESSING_NOTE + "\n" + SCOPE_NOTE).grid(
            row=9, column=0, sticky="ew", pady=(4, 0)
        )

    def _on_resize(self, event: tk.Event[Any]) -> None:
        wrap = max(200, int(event.width) - 40)
        for label in self._wrap_labels:
            label.configure(wraplength=wrap)

    def _on_first_map(self, _event: object | None = None) -> None:
        if self._first_map_done:
            return
        self._first_map_done = True
        self.refresh_library()

    # ------------------------------------------------------------------ public API

    def _units(self) -> list[Any] | None:
        if self._raw is None:
            return []
        if (
            isinstance(self._raw, dict)
            and set(self._raw) == {"contract", "units"}
            and self._raw.get("contract") == CONTRACT
            and isinstance(self._raw.get("units"), list)
            and len(self._raw["units"]) <= 2
            and all(isinstance(unit, dict) for unit in self._raw["units"])
        ):
            return cast(list[Any], self._raw["units"])
        return None

    def set_declaration(self, raw: Any) -> None:
        """Show a slot's declaration (``None`` = none). Never fires the change callback."""

        self._raw = copy.deepcopy(raw)
        self._selected = 0
        self.notice_var.set("")
        self._render()

    def get_declaration(self) -> Any:
        return copy.deepcopy(self._raw)

    def set_legacy_declaration(self, raw: Any) -> None:
        """Tell the panel whether the slot also carries a legacy ``controlnet_openpose`` value (display only)."""

        self._legacy = copy.deepcopy(raw)
        self._render()

    def set_target(self, target: Any) -> None:
        self._target = target
        self._status()

    def set_content_visibility_mode(self, mode: str) -> None:
        self._hidden = mode == "sfw"
        self._render()

    def _visible(self, name: str) -> bool:
        return not self._hidden or ContentVisibilityResolver("sfw").is_visible({"name": name})

    def _shown(self, name: str) -> str:
        return name if self._visible(name) else REDACTED_TEXT

    def _changed(self) -> None:
        self._render()
        if self._callback is not None:
            self._callback()

    # ------------------------------------------------------------------ unit operations (explicit operator actions)

    def add_unit(self, modality: str = "openpose") -> None:
        units = self._units()
        if (
            units is None
            or len(units) >= 2
            or self._legacy is not None
            or modality not in MODALITIES
        ):
            return
        self._raw = {"contract": CONTRACT, "units": units + [new_unit(modality)]}
        self._selected = len(units)
        self.notice_var.set("")
        self._changed()

    def remove_unit(self) -> None:
        units = self._units()
        if units is None:
            self._raw = None  # explicit operator removal is the only way to clear malformed intent
        elif units:
            del units[self._selected]
            self._raw = {"contract": CONTRACT, "units": units} if units else None
        self._selected = max(0, self._selected - 1)
        self.notice_var.set("")
        self._changed()

    def move_up(self) -> None:
        self._swap(-1)

    def move_down(self) -> None:
        self._swap(1)

    def _swap(self, step: int) -> None:
        units = self._units()
        other = self._selected + step
        if units and 0 <= other < len(units):
            units[other], units[self._selected] = units[self._selected], units[other]
            self._selected = other
            self._changed()

    def toggle_advanced(self) -> None:
        self._set_advanced(not self.advanced_open)

    def _set_advanced(self, open_: bool) -> None:
        self.advanced_open = open_
        self.advanced_button.configure(text="Advanced ▾" if open_ else "Advanced ▸")
        if open_:
            self.advanced.grid(row=7, column=0, sticky="ew", pady=(2, 0))
        else:
            self.advanced.grid_remove()

    def replace_legacy(self) -> None:
        """Drop the slot's legacy OpenPose value so ordered units can be used; only after the operator confirms."""

        if self._legacy is None or self._on_replace_legacy is None:
            return
        if not self._confirm("Switch to ordered ControlNet units", _LEGACY_SWITCH_WARNING):
            return
        self._on_replace_legacy()
        self.set_legacy_declaration(None)

    def use_recommended_model(self) -> None:
        unit = self._selected_unit()
        if unit is None:
            return
        name = recommended_model(str(unit.get("modality")), self._models)
        if name is not None:
            self.variables["model"].set(name)
            self._edit()

    # ------------------------------------------------------------------ edits

    def _select(self, _event: Any = None) -> None:
        self._selected = max(0, self.unit_combo.current())
        self.notice_var.set("")
        self._render()

    def _on_modality_chosen(self, _event: Any = None) -> None:
        modality = modality_from_label(self.modality_label_var.get())
        if modality is not None:
            self.variables["modality"].set(modality)
            self._edit()

    def _on_map_picked(self, identity: str) -> None:
        unit = self._selected_unit()
        if self._suppress or unit is None or unit.get("asset") == identity:
            return
        unit["asset"] = identity
        self.notice_var.set("")
        self._changed()

    def _edit(self, _event: Any = None) -> None:
        """Apply only what the operator actually changed; focus changes and unchanged values do nothing."""

        unit = self._selected_unit()
        if self._suppress or unit is None:
            return
        updates: dict[str, Any] = {}
        if self.enabled_var.get() != (unit.get("enabled", True) is True):
            updates["enabled"] = self.enabled_var.get()
        for key, variable in self.variables.items():
            text = variable.get()
            if text == REDACTED_TEXT or key == "asset" or text == str(unit.get(key, "")):
                continue
            if key not in _NUMERIC:
                updates[key] = text
                continue
            try:
                number = float(text)
            except ValueError:
                self._refuse(f"{key.replace('_', ' ')} must be a number")
                return
            if number != unit.get(key, _NUMERIC_DEFAULTS[key]):
                updates[key] = number
        if not updates:
            return
        problem = self._numeric_problem(unit, updates)
        if problem:
            self._refuse(problem)
            return
        unit.update(updates)
        self.notice_var.set("")
        self._changed()

    @staticmethod
    def _numeric_problem(unit: dict[str, Any], updates: dict[str, Any]) -> str:
        for key, (low, high) in _NUMERIC.items():
            if key in updates and not low <= updates[key] <= high:
                return f"{key.replace('_', ' ')} must be between {low:g} and {high:g}"
        merged = {**unit, **updates}
        start, end = merged.get("guidance_start", 0.0), merged.get("guidance_end", 1.0)
        if (
            ("guidance_start" in updates or "guidance_end" in updates)
            and all(isinstance(value, (int, float)) for value in (start, end))
            and not start < end
        ):
            return "guidance start must be lower than guidance end"
        return ""

    def _refuse(self, reason: str) -> None:
        self.notice_var.set(
            "That change was not applied: " + reason + ". The saved value is unchanged."
        )
        self._render()

    # ------------------------------------------------------------------ rendering

    def _selected_unit(self) -> dict[str, Any] | None:
        units = self._units()
        return units[self._selected] if units else None

    def _render(self) -> None:
        self._suppress = True
        try:
            units = self._units()
            self._selected = min(self._selected, max(0, len(units or ()) - 1))
            self.unit_combo.configure(
                values=[unit_choice_label(index, unit) for index, unit in enumerate(units or ())]
            )
            if units:
                self.unit_combo.current(self._selected)
            else:
                self.unit_var.set(
                    "No units" if units is not None else "Invalid declaration (preserved)"
                )
            self._render_gating(units)
            selected = units[self._selected] if units else {}
            if units:
                self.detail.grid(row=3, column=0, sticky="ew", pady=(6, 0))
            else:
                self.detail.grid_remove()
            self.enabled_var.set(selected.get("enabled", True) is True)
            for key, variable in self.variables.items():
                value = str(selected.get(key, ""))
                variable.set(
                    value
                    if key not in {"model", "asset"} or self._visible(value)
                    else REDACTED_TEXT
                )
            self.modality_label_var.set(modality_label(selected.get("modality", "")))
            self.guide_var.set(guide_text(selected.get("modality")))
            self.control_mode_help_var.set(
                CONTROL_MODE_HELP.get(str(selected.get("control_mode")), "")
            )
            self.resize_help_var.set(RESIZE_HELP.get(str(selected.get("resize_mode")), ""))
            self._set_advanced(
                self.advanced_open or (bool(units) and advanced_is_customized(selected))
            )
            self._render_resources(selected)
            self._status()
        finally:
            self._suppress = False

    def _render_gating(self, units: list[Any] | None) -> None:
        legacy = self._legacy is not None
        if legacy:
            self.legacy_var.set(
                "Legacy OpenPose: this slot already has conditioning saved as a single legacy OpenPose reference "
                "(edited in the section above). Its settings are preserved and it still runs as before. "
                "Ordered units are a different declaration and cannot coexist with it"
                + (
                    "; both are saved here, so Preview will refuse this slot until you remove one."
                    if units
                    else "."
                )
            )
            self.legacy_frame.grid()
            self.replace_legacy_button.configure(
                state="normal" if self._on_replace_legacy is not None else "disabled"
            )
        else:
            self.legacy_frame.grid_remove()
        room = accepts_new_unit(self._raw) and units is not None and not legacy
        for button in self.add_buttons.values():
            button.configure(state="normal" if room else "disabled")
        self.unit_buttons["Remove"].configure(
            state="normal" if self._raw is not None else "disabled"
        )
        self.unit_buttons["Move up"].configure(
            state="normal" if units and self._selected > 0 else "disabled"
        )
        self.unit_buttons["Move down"].configure(
            state="normal" if units and self._selected < len(units) - 1 else "disabled"
        )
        self.unit_combo.configure(state="readonly" if units else "disabled")

    def _render_resources(self, selected: dict[str, Any]) -> None:
        modality = str(selected.get("modality", ""))
        self.browser.set_entries(
            self._listing.entries,
            hidden=lambda identity: not self._visible(identity),
            empty_text=self._library_help(),
        )
        self.browser.set_selection(str(selected.get("asset", "")))
        ranked = sorted(
            (
                choice
                for choice in model_choices(modality, self._models)
                if self._visible(choice.name)
            ),
            key=lambda choice: (not choice.compatible, choice.name.lower()),
        )
        self.model_combo.configure(values=[choice.name for choice in ranked])
        recommended = recommended_model(modality, self._models)
        self.use_recommended_button.configure(
            state="normal"
            if recommended is not None and recommended != selected.get("model")
            else "disabled"
        )
        self.model_hint_var.set(self._model_hint(modality, recommended))

    def _library_help(self) -> str:
        if self._scanning:
            return "Scanning the reference-map library…"
        if not self._loaded:
            return "Reference maps are listed when this tab is shown. Use Refresh to scan now."
        if self._listing.error:
            return f"The library scan failed: {self._listing.error}"
        if not self._listing.configured:
            return "Configure the Stable Diffusion WebUI root to use a reference-map library."
        if not self._listing.folder_exists:
            return "models/OpenPose does not exist under the WebUI root. " + EMPTY_LIBRARY_HELP
        return EMPTY_LIBRARY_HELP

    def _model_hint(self, modality: str, recommended: str | None) -> str:
        label = modality_label(modality)
        if not self._loaded:
            return "Refresh to list the installed ControlNet models and check them against this purpose."
        if recommended is not None:
            return (
                f"Recommended: {self._shown(recommended)} (positive SDXL structure evidence and documented for "
                f"{label}). Choosing it is up to you; saved choices are never replaced."
            )
        fits = [
            c.name
            for c in model_choices(modality, self._models)
            if c.compatible and self._visible(c.name)
        ]
        if fits:
            return f"Installed models documented for {label}: {', '.join(fits)}. Choose one."
        return (
            f"No installed ControlNet weight is verified for {label}. Admission accepts: "
            f"{', '.join(documented_models(modality)) or 'none'}. Add one to models/ControlNet and refresh; "
            "StableNew never downloads weights."
        )

    def _status(self) -> None:
        readiness = describe_readiness(
            self._raw,
            target=self._target,
            library_identities=self._listing.identities if self._loaded else None,
            library_error=self._listing.error,
            models=self._models,
            resources_loaded=self._loaded,
            legacy_present=self._legacy is not None,
            shown=self._shown,
        )
        self.status_var.set(readiness.text)
        self.summary_var.set(ordered_summary(self._raw, self._shown))

    # ------------------------------------------------------------------ resource refresh (worker, then Tk)

    def refresh_library(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._render()
        self.status_var.set("Refreshing reference maps and ControlNet models…")

        def work() -> None:
            try:
                from src.assets import AssetRegistry

                registry = (
                    self._registry_factory()
                    if self._registry_factory is not None
                    else AssetRegistry()
                )
                self._results.put(
                    (refresh_listing(registry), list_controlnet_models(controlnet_folder(registry)))
                )
            except Exception as exc:  # noqa: BLE001 - display failure on Tk; preserve authored intent
                self._results.put((LibraryListing(error=str(exc)), []))

        from src.utils.thread_registry import get_thread_registry

        get_thread_registry().spawn(
            target=work,
            name="ControlNet-Resources",
            daemon=False,
            purpose="Refresh ControlNet authoring resources",
        )
        self._poll = self.after(40, self._drain)

    def _drain(self) -> None:
        try:
            self._listing, self._models = self._results.get_nowait()
        except queue.Empty:
            self._poll = self.after(40, self._drain)
            return
        self._scanning = False
        self._loaded = True
        self._poll = None
        self._render()  # refresh is a projection: no dirty callback, edits or substitutions

    def destroy(self) -> None:
        if self._poll is not None:
            self.after_cancel(self._poll)
            self._poll = None
        super().destroy()


__all__ = ["ControlNetUnitsPanel"]

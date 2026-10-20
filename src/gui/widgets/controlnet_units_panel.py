"""Ordered ControlNet authoring; resource discovery is off Tk, never a compiler."""

from __future__ import annotations

import copy
import queue
import tkinter as tk
from tkinter import ttk
from typing import Any, cast

from src.assets.controlnet_structure import list_controlnet_models, name_key
from src.conditioning.controlnet import (
    CONTRACT,
    MODALITIES,
    UNIT_CONTRACT,
    declaration_problems,
    parse_units,
)
from src.conditioning.openpose import CONTROL_MODES, RESIZE_MODES, OpenPoseSelection
from src.conditioning.openpose_catalog import LibraryListing, controlnet_folder, refresh_listing
from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.image_backends.forge_controlnet_units import model_problem
from src.image_backends.model_policy import EVIDENCE_REGISTRY


class ControlNetUnitsPanel(ttk.LabelFrame):
    def __init__(
        self,
        parent: Any,
        *,
        on_change_callback: Any = None,
        registry_factory: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            parent, text="Ordered ControlNet units (SDXL / Forge)", padding=6, **kwargs
        )
        self._callback = on_change_callback
        self._registry_factory = registry_factory
        self._raw: Any = None
        self._selected = 0
        self._target: Any = None
        self._hidden = False
        self._listing = LibraryListing()
        self._models: list[Any] = []
        self._loaded = False
        self._scanning = False
        self._results: queue.Queue[Any] = queue.Queue()
        self._poll: str | None = None
        self._suppress = False
        self.columnconfigure(1, weight=1)
        self.unit_var = tk.StringVar(value="")
        self.unit_combo = ttk.Combobox(self, textvariable=self.unit_var, state="readonly", width=26)
        self.unit_combo.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.unit_combo.bind("<<ComboboxSelected>>", self._select)
        buttons = ttk.Frame(self)
        buttons.grid(row=0, column=2, sticky="e")
        for label, command in (
            ("Add unit", self.add_unit),
            ("Remove", self.remove_unit),
            ("Move up", self.move_up),
            ("Refresh", self.refresh_library),
        ):
            ttk.Button(buttons, text=label, command=command).pack(side="left", padx=2)
        self.enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self, text="Enable selected unit", variable=self.enabled_var, command=self._edit
        ).grid(row=1, column=0, columnspan=3, sticky="w")
        self.variables: dict[str, tk.StringVar] = {}
        self.controls: dict[str, Any] = {}
        fields = (
            ("modality", "Modality", MODALITIES),
            ("asset", "Reference map", ()),
            ("model", "ControlNet model", ()),
            ("weight", "Strength (0–2)", None),
            ("guidance_start", "Guidance start (0–1)", None),
            ("guidance_end", "Guidance end (0–1)", None),
            ("control_mode", "Control mode", CONTROL_MODES),
            ("resize_mode", "Resize", RESIZE_MODES),
        )
        for row, (key, label, choices) in enumerate(fields, 2):
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w")
            variable = tk.StringVar()
            self.variables[key] = variable
            widget = (
                ttk.Entry(self, textvariable=variable)
                if choices is None
                else ttk.Combobox(self, textvariable=variable, values=choices, state="readonly")
            )
            widget.grid(row=row, column=1, columnspan=2, sticky="ew", pady=1)
            widget.bind("<<ComboboxSelected>>", self._edit)
            widget.bind("<Return>", self._edit)
            widget.bind("<FocusOut>", self._edit)
            self.controls[key] = widget
        ttk.Label(
            self,
            text="Preprocessor: None. Supply pre-rendered maps from models/OpenPose.\nAutomatic preprocessing is unavailable. Preview confirms execution readiness.",
            justify="left",
        ).grid(row=10, column=0, columnspan=3, sticky="w")
        self.status_var = tk.StringVar()
        ttk.Label(self, textvariable=self.status_var, wraplength=620, justify="left").grid(
            row=11, column=0, columnspan=3, sticky="ew"
        )
        self._render()

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
        self._raw = copy.deepcopy(raw)
        self._selected = 0
        self._render()

    def get_declaration(self) -> Any:
        return copy.deepcopy(self._raw)

    def set_target(self, target: Any) -> None:
        self._target = target
        self._status()

    def set_content_visibility_mode(self, mode: str) -> None:
        self._hidden = mode == "sfw"
        self._render()

    def _visible(self, name: str) -> bool:
        return not self._hidden or ContentVisibilityResolver("sfw").is_visible({"name": name})

    def _changed(self) -> None:
        self._render()
        if self._callback is not None:
            self._callback()

    def add_unit(self) -> None:
        units = self._units()
        if units is None or len(units) >= 2:
            return
        self._raw = {
            "contract": CONTRACT,
            "units": units
            + [
                {
                    **OpenPoseSelection(asset="").to_dict(),
                    "contract": UNIT_CONTRACT,
                    "modality": "openpose",
                }
            ],
        }
        self._selected = len(units)
        self._changed()

    def remove_unit(self) -> None:
        units = self._units()
        if units is None:
            self._raw = None  # explicit operator removal is the only way to clear malformed intent
        elif units:
            del units[self._selected]
            self._raw = {"contract": CONTRACT, "units": units} if units else None
        self._selected = max(0, self._selected - 1)
        self._changed()

    def move_up(self) -> None:
        units = self._units()
        if units and self._selected > 0:
            units[self._selected - 1], units[self._selected] = (
                units[self._selected],
                units[self._selected - 1],
            )
            self._selected -= 1
            self._changed()

    def _select(self, _event: Any = None) -> None:
        self._selected = max(0, self.unit_combo.current())
        self._render()

    def _edit(self, _event: Any = None) -> None:
        units = self._units()
        if self._suppress or not units:
            return
        unit = units[self._selected]
        unit["enabled"] = self.enabled_var.get()
        for key, variable in self.variables.items():
            value: Any = variable.get()
            if value == REDACTED_TEXT:
                continue
            if key in {"weight", "guidance_start", "guidance_end"}:
                try:
                    value = float(value)
                except ValueError:
                    pass  # keep invalid authored input visible; validation refuses it
            unit[key] = value
        self._changed()

    def _render(self) -> None:
        self._suppress = True
        try:
            units = self._units()
            self._selected = min(self._selected, max(0, len(units or ()) - 1))
            self.unit_combo.configure(
                values=[
                    f"Unit {index + 1}: {unit.get('modality', '?')}"
                    for index, unit in enumerate(units or ())
                ]
            )
            if units:
                self.unit_combo.current(self._selected)
            else:
                self.unit_var.set(
                    "No units" if units is not None else "Invalid declaration (preserved)"
                )
            selected = units[self._selected] if units else {}
            self.enabled_var.set(selected.get("enabled", True) is True)
            for key, variable in self.variables.items():
                value = str(selected.get(key, ""))
                variable.set(
                    value
                    if key not in {"model", "asset"} or self._visible(value)
                    else REDACTED_TEXT
                )
                self.controls[key].configure(
                    state=(
                        "normal"
                        if key in {"weight", "guidance_start", "guidance_end"}
                        else "readonly"
                    )
                    if units
                    else "disabled"
                )
            self.controls["asset"].configure(
                values=[
                    item.identity for item in self._listing.entries if self._visible(item.identity)
                ]
            )
            self.controls["model"].configure(
                values=[item.name for item in self._models if self._visible(item.name)]
            )
            self._status()
        finally:
            self._suppress = False

    def _status(self) -> None:
        if self._raw is None:
            self.status_var.set(
                "Add up to two ordered units. Clear legacy OpenPose before using this declaration."
            )
            return
        problems = declaration_problems(self._raw)
        if problems:
            self.status_var.set("Cannot execute: " + "; ".join(problems))
            return
        messages = []
        for index, unit in enumerate(parse_units(self._raw)):
            prefix = f"Unit {index + 1} ({unit.modality}): "
            if not unit.settings.enabled:
                messages.append(prefix + "disabled")
                continue
            names = [
                item
                for item in self._models
                if name_key(item.name) == name_key(unit.settings.model)
            ]
            problem = model_problem(
                unit.modality,
                unit.settings.model,
                names[0].evidence.status if len(names) == 1 else None,
            )
            if not self._loaded:
                problem = "Refresh resources to check local availability."
            elif self._listing.error:
                problem = "Resource refresh failed: " + self._listing.error
            elif unit.settings.asset not in self._listing.identities:
                problem = "Reference map is missing."
            if (
                self._target is None
                or not self._target.executable
                or self._target.evidence != EVIDENCE_REGISTRY
            ):
                problem = "Select a registry-verified SDXL checkpoint on Forge."
            messages.append(
                prefix
                + (
                    "Cannot execute: " + problem
                    if problem
                    else "Local resources compatible; Preview and Forge admission remain required."
                )
            )
        self.status_var.set("\n".join(messages) or "No enabled units.")

    def refresh_library(self) -> None:
        if self._scanning:
            return
        self._scanning = True
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
        super().destroy()

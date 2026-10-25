"""Ordered Prompt Slot authoring inside the existing scrollable Learning Design surface."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any, cast

from src.learning.prompt_slot_experiment import PromptSlotDesign, slots_in, validate_design


class PromptSlotDesignFrame(ttk.LabelFrame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        template: Callable[[], str],
        changed: Callable[[], None],
        visible: Callable[[], bool],
    ) -> None:
        super().__init__(parent, text="One named prompt slot", padding=6)
        self._template = template
        self._frozen_source_template: str | None = None
        self._changed = changed
        self._visible = visible
        self._candidates: list[str] = []
        self._fixed_vars: dict[str, tk.StringVar] = {}
        self.columnconfigure(0, weight=1)
        ttk.Label(
            self,
            text="Choose a prompt source below, then refresh slots. Every occurrence of the tested slot varies together.",
            wraplength=340,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")
        self.slot_var = tk.StringVar()
        self.slot_box = ttk.Combobox(self, textvariable=self.slot_var, state="readonly")
        self.slot_box.grid(row=1, column=0, sticky="ew", pady=3)
        self.slot_box.bind("<<ComboboxSelected>>", lambda _event: self._fixed_fields())
        ttk.Button(self, text="Refresh Named Slots", command=self.refresh_slots).grid(
            row=2, column=0, sticky="w"
        )
        self.fixed_frame = ttk.LabelFrame(
            self, text="Explicit fixed values for other slots", padding=4
        )
        self.fixed_frame.grid(row=3, column=0, sticky="ew", pady=4)
        self.fixed_frame.columnconfigure(1, weight=1)
        self.candidate_list = tk.Listbox(self, height=4, exportselection=False)
        self.candidate_list.grid(row=4, column=0, sticky="ew")
        self.candidate_list.bind("<<ListboxSelect>>", self._selected)
        self.value_var = tk.StringVar()
        self.value_entry = ttk.Entry(self, textvariable=self.value_var)
        self.value_entry.grid(row=5, column=0, sticky="ew", pady=3)
        actions = ttk.Frame(self)
        actions.grid(row=6, column=0, sticky="ew")
        for index, (label, action) in enumerate(
            (
                ("Add", self.add),
                ("Replace", self.replace),
                ("Remove", self.remove),
                ("Up", lambda: self.move(-1)),
                ("Down", lambda: self.move(1)),
            )
        ):
            actions.columnconfigure(index % 2, weight=1)
            ttk.Button(actions, text=label, command=action, width=7).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=1, pady=1
            )
        self.count_var = tk.StringVar(
            value="0 candidates; choose 2–8. 1–3 images per candidate, maximum 24."
        )
        ttk.Label(self, textvariable=self.count_var, wraplength=340).grid(
            row=7, column=0, sticky="ew", pady=3
        )
        ttk.Label(
            self,
            text="Fixed negative prompt (custom source; native rows retain their own)",
            wraplength=340,
        ).grid(row=8, column=0, sticky="w")
        self.negative_var = tk.StringVar()
        self.negative_entry = ttk.Entry(self, textvariable=self.negative_var)
        self.negative_entry.grid(row=9, column=0, sticky="ew")
        self.negative_var.trace_add("write", lambda *_: self._changed())
        self.value_entry.bind("<Return>", lambda _event: self.add())

    def refresh_slots(self, *, retain_frozen: bool = False) -> None:
        if not retain_frozen:
            self._frozen_source_template = None
        try:
            slots = slots_in(self._read_template())
        except ValueError:
            slots = ()
        self.slot_box.configure(values=slots)
        if self.slot_var.get() not in slots:
            self.slot_var.set(slots[0] if len(slots) == 1 else "")
        self._fixed_fields()

    def _fixed_fields(self) -> None:
        old = {key: variable.get() for key, variable in self._fixed_vars.items()}
        for child in self.fixed_frame.winfo_children():
            child.destroy()
        self._fixed_vars = {}
        for index, slot in enumerate(self.slot_box.cget("values")):
            if slot == self.slot_var.get():
                continue
            variable = tk.StringVar(value=old.get(slot, ""))
            self._fixed_vars[slot] = variable
            ttk.Label(
                self.fixed_frame, text=slot if self._visible() else "Fixed slot", wraplength=120
            ).grid(row=index, column=0, sticky="w")
            entry = ttk.Entry(
                self.fixed_frame,
                textvariable=variable,
                show="" if self._visible() else "•",
                width=14,
            )
            entry.grid(row=index, column=1, sticky="ew")
            variable.trace_add("write", lambda *_: self._changed())
        self._changed()

    def _selected(self, _event: Any = None) -> None:
        selected = self._selection()
        if selected:
            self.value_var.set(self._candidates[selected[0]])

    def _render(self) -> None:
        self.candidate_list.delete(0, tk.END)
        for index, value in enumerate(self._candidates):
            self.candidate_list.insert(
                tk.END,
                f"{chr(65 + index)}: {value}"
                if self._visible()
                else f"Candidate {chr(65 + index)}",
            )
        self.value_entry.configure(show="" if self._visible() else "•")
        self.count_var.set(
            f"{len(self._candidates)} candidates; choose 2–8. 1–3 images per candidate, maximum 24."
        )
        self._changed()

    def _selection(self) -> tuple[int, ...]:
        return cast(Callable[[], tuple[int, ...]], self.candidate_list.curselection)()

    def add(self) -> None:
        if self.value_var.get().strip():
            self._candidates.append(self.value_var.get())
            self.value_var.set("")
            self._render()

    def replace(self) -> None:
        selected = self._selection()
        if selected:
            self._candidates[selected[0]] = self.value_var.get()
            self._render()

    def remove(self) -> None:
        selected = self._selection()
        if selected:
            del self._candidates[selected[0]]
            self._render()

    def move(self, offset: int) -> None:
        selected = self._selection()
        if selected and 0 <= selected[0] + offset < len(self._candidates):
            index, target = selected[0], selected[0] + offset
            self._candidates[index], self._candidates[target] = (
                self._candidates[target],
                self._candidates[index],
            )
            self._render()
            self.candidate_list.selection_set(target)

    def spec(self) -> dict[str, Any]:
        return {
            "template": self._read_template(),
            "slot": self.slot_var.get(),
            "candidates": list(self._candidates),
            "fixed_slots": {key: value.get() for key, value in self._fixed_vars.items()},
            "negative_prompt": self.negative_var.get(),
        }

    def signature(self) -> str:
        from src.learning.prompt_slot_experiment import digest

        return digest(self.spec())

    def validation_error(self, images: int) -> str:
        spec = self.spec()
        try:
            validate_design(
                PromptSlotDesign(
                    spec["template"],
                    spec["slot"],
                    tuple(spec["candidates"]),
                    spec["fixed_slots"],
                    images,
                )
            )
        except ValueError as exc:
            return str(exc)
        return ""

    def _read_template(self) -> str:
        return (
            self._template()
            if self._frozen_source_template is None
            else self._frozen_source_template
        )

    def clear_frozen_source(self) -> None:
        self._frozen_source_template = None

    def load(self, spec: dict[str, Any], *, frozen_template: str | None = None) -> None:
        self._frozen_source_template = frozen_template
        self._candidates = list(spec.get("candidates") or [])
        self.negative_var.set(spec.get("negative_prompt", ""))
        self.refresh_slots(retain_frozen=True)
        self.slot_var.set(spec.get("slot", ""))
        self._fixed_fields()
        for key, value in (spec.get("fixed_slots") or {}).items():
            if key in self._fixed_vars:
                self._fixed_vars[key].set(value)
        self._render()

    def refresh_visibility(self) -> None:
        self.slot_box.configure(
            show="" if self._visible() else "•", state="readonly" if self._visible() else "disabled"
        )
        self.negative_entry.configure(show="" if self._visible() else "•")
        self._render()
        self._fixed_fields()

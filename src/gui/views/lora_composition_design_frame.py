"""LoRA Composition authoring inside the existing scrollable Learning Design surface.

A thin adapter: discovery uses the existing tracked LoRA scanner worker (never on Tk), identity/compatibility come
from the toolkit-neutral ``lora_inventory`` projection, and every rule lives in ``learning.lora_composition``.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from typing import Any, cast

from src.gui.gui_invoker import GuiInvoker
from src.learning import lora_composition as lc
from src.learning.lora_inventory import InventoryRow, discover_loras, inventory_rows

NONE_CHOICE = "(none: the tested position starts empty)"
Loader = Callable[[Callable[[], bool]], Mapping[str, Any]]


class LoraCompositionDesignFrame(ttk.LabelFrame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        prompt: Callable[[], str],
        changed: Callable[[], None],
        visible: Callable[[], bool],
        family: Callable[[], str],
        mode: Callable[[], str],
        loader: Loader | None = None,
        inventory_listener: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        super().__init__(parent, text="One designated LoRA position", padding=6)
        self._prompt, self._changed, self._visible = prompt, changed, visible
        self._family, self._mode = family, mode
        self._loader: Loader = loader or discover_loras
        self._inventory_listener = inventory_listener
        self._candidates: list[lc.Candidate] = []
        self._resources: dict[str, Any] = {}
        self._rows: list[InventoryRow] = []
        self._shown: set[str] = set()
        self._request = 0
        self._closed = False
        self._cancel = threading.Event()
        self._invoker = GuiInvoker(self)
        self._baseline: tuple[tuple[str, float], ...] = ()
        self._original_names: dict[str, str] = {}
        self.columnconfigure(0, weight=1)
        ttk.Label(
            self,
            text="Fixed LoRAs stay unchanged in every variant. Only the tested position varies.",
            wraplength=340,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")
        self.operation_var = tk.StringVar(value=lc.OPERATION_LABELS[lc.ADD_REMOVE])
        self.operation_box = ttk.Combobox(
            self,
            textvariable=self.operation_var,
            values=tuple(lc.OPERATION_LABELS.values()),
            state="readonly",
        )
        self.operation_box.grid(row=1, column=0, sticky="ew", pady=3)
        self.operation_box.bind("<<ComboboxSelected>>", lambda _e: self._changed())
        ttk.Label(self, text="Fixed LoRAs (unchanged in every variant)").grid(
            row=2, column=0, sticky="w"
        )
        self.fixed_list = tk.Listbox(self, height=3, exportselection=False)
        self.fixed_list.grid(row=3, column=0, sticky="ew")
        ttk.Label(self, text="Tested LoRA position: original from the baseline prompt").grid(
            row=4, column=0, sticky="w", pady=(4, 0)
        )
        self.original_var = tk.StringVar(value=NONE_CHOICE)
        self.original_box = ttk.Combobox(
            self, textvariable=self.original_var, values=(NONE_CHOICE,), state="readonly"
        )
        self.original_box.grid(row=5, column=0, sticky="ew")
        self.original_box.bind("<<ComboboxSelected>>", lambda _e: self._changed())
        search = ttk.Frame(self)
        search.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        search.columnconfigure(0, weight=1)
        self.query_var = tk.StringVar()
        ttk.Entry(search, textvariable=self.query_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(search, text="Refresh Installed LoRAs", command=self.refresh_inventory).grid(
            row=0, column=1, padx=(4, 0)
        )
        self.query_var.trace_add("write", lambda *_: self._render_inventory())
        self.status_var = tk.StringVar(value="Installed LoRAs not loaded yet. Use Refresh.")
        ttk.Label(self, textvariable=self.status_var, wraplength=340, justify="left").grid(
            row=7, column=0, sticky="ew"
        )
        self.inventory_list = tk.Listbox(self, height=6, exportselection=False)
        self.inventory_list.grid(row=8, column=0, sticky="ew")
        self.inventory_list.bind("<<ListboxSelect>>", lambda _e: self._describe_selection())
        self.detail_var = tk.StringVar()
        ttk.Label(self, textvariable=self.detail_var, wraplength=340, justify="left").grid(
            row=9, column=0, sticky="ew"
        )
        add = ttk.Frame(self)
        add.grid(row=10, column=0, sticky="ew", pady=3)
        ttk.Label(add, text="Strength").grid(row=0, column=0)
        self.strength_var = tk.StringVar(value="0.8")
        ttk.Entry(add, textvariable=self.strength_var, width=6).grid(row=0, column=1, padx=3)
        ttk.Button(add, text="Add LoRA Candidate", command=self.add_selected).grid(row=0, column=2)
        ttk.Button(add, text="Add No LoRA", command=self.add_empty).grid(row=0, column=3, padx=3)
        self.candidate_list = tk.Listbox(self, height=4, exportselection=False)
        self.candidate_list.grid(row=11, column=0, sticky="ew")
        actions = ttk.Frame(self)
        actions.grid(row=12, column=0, sticky="ew")
        for index, (label, action) in enumerate(
            (("Remove", self.remove), ("Up", lambda: self.move(-1)), ("Down", lambda: self.move(1)))
        ):
            actions.columnconfigure(index, weight=1)
            ttk.Button(actions, text=label, command=action, width=7).grid(
                row=0, column=index, sticky="ew", padx=1, pady=1
            )
        self.count_var = tk.StringVar()
        ttk.Label(self, textvariable=self.count_var, wraplength=340).grid(
            row=13, column=0, sticky="ew", pady=3
        )
        ttk.Label(
            self,
            text="Fixed negative prompt (custom source; native rows retain their own)",
            wraplength=340,
        ).grid(row=14, column=0, sticky="w")
        ttk.Label(
            self, text="Fixed values for Matrix slots (name=value, ...)", wraplength=340
        ).grid(row=16, column=0, sticky="w")
        self.slots_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.slots_var).grid(row=17, column=0, sticky="ew")
        self.slots_var.trace_add("write", lambda *_: self._changed())
        self.negative_var = tk.StringVar()
        self.negative_entry = ttk.Entry(self, textvariable=self.negative_var)
        self.negative_entry.grid(row=15, column=0, sticky="ew")
        self.negative_var.trace_add("write", lambda *_: self._changed())
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._render()

    # -- display -----------------------------------------------------------------------------------------------
    def _label(self, name: str) -> str:
        if self._visible() or name.casefold() in self._shown:
            return name
        names = [n for n, _ in self._baseline] + [c.name for c in self._candidates if c.name]
        return f"LoRA {names.index(name) + 1}" if name in names else "LoRA"

    def _tested(self) -> str | None:
        value = self.original_var.get()
        return None if value == NONE_CHOICE else self._original_names.get(value, value)

    def sync_baseline(self) -> None:
        """Recompute the fixed/tested display from the current prompt source (no scan, no hashing)."""
        baseline = lc.baseline_loras(self._prompt())
        if baseline == self._baseline:
            return
        self._baseline = baseline
        self._render()

    def _render(self) -> None:
        tested = self._tested()
        self._original_names = {self._label(n): n for n, _ in self._baseline}
        self.original_box.configure(values=(NONE_CHOICE, *self._original_names))
        if tested and tested not in [n for n, _ in self._baseline]:
            self.original_var.set(NONE_CHOICE)
            tested = None
        self.fixed_list.delete(0, tk.END)
        for name, weight in self._baseline:
            if tested and name.casefold() == tested.casefold():
                continue
            self.fixed_list.insert(tk.END, f"{self._label(name)} @ {weight:g}")
        if not self.fixed_list.size():
            self.fixed_list.insert(tk.END, "No fixed LoRAs")
        self.candidate_list.delete(0, tk.END)
        for index, candidate in enumerate(self._candidates):
            text = (
                "No LoRA"
                if candidate.name is None
                else f"{self._label(candidate.name)} @ {candidate.weight:g}"
            )
            self.candidate_list.insert(tk.END, f"{chr(65 + index)}: {text}")
        self.count_var.set(
            f"{len(self._candidates)} candidates; choose 2–8. 1–3 images per candidate, maximum 24."
        )
        self._changed()

    def _render_inventory(self) -> None:
        tested = self._tested()
        self._rows = inventory_rows(
            self._resources,
            self._family(),
            mode=self._mode(),
            query=self.query_var.get(),
            fixed=[n for n, _ in self._baseline if not tested or n.casefold() != tested.casefold()],
            baseline=[n for n, _ in self._baseline],
        )[:200]
        self._shown = {row.name.casefold() for row in self._rows}
        self.inventory_list.delete(0, tk.END)
        for row in self._rows:
            self.inventory_list.insert(tk.END, f"{row.name}: {row.label}")
        self.detail_var.set("")

    def _selected_row(self) -> InventoryRow | None:
        selection = cast(Callable[[], tuple[int, ...]], self.inventory_list.curselection)()
        return self._rows[selection[0]] if selection and selection[0] < len(self._rows) else None

    def _describe_selection(self) -> None:
        row = self._selected_row()
        self.detail_var.set("" if row is None else row.label)

    # -- candidates --------------------------------------------------------------------------------------------
    def _strength(self) -> float | None:
        try:
            return float(self.strength_var.get())
        except ValueError:
            return None

    def add_selected(self) -> None:
        row, strength = self._selected_row(), self._strength()
        if row is None or strength is None or not row.selectable:
            self.detail_var.set("Select a usable installed LoRA and a numeric strength first.")
            return
        try:
            self._candidates.append(lc.Candidate(row.name, strength))
        except ValueError as exc:
            self.detail_var.set(str(exc))
            return
        self._render()

    def add_empty(self) -> None:
        self._candidates.append(lc.Candidate(None))
        self._render()

    def _selection(self) -> tuple[int, ...]:
        return cast(Callable[[], tuple[int, ...]], self.candidate_list.curselection)()

    def remove(self) -> None:
        selected = self._selection()
        if selected:
            del self._candidates[selected[0]]
            self._render()

    def move(self, offset: int) -> None:
        selected = self._selection()
        if selected and 0 <= selected[0] + offset < len(self._candidates):
            index, target = selected[0], selected[0] + offset
            items = self._candidates
            items[index], items[target] = items[target], items[index]
            self._render()
            self.candidate_list.selection_set(target)

    # -- spec --------------------------------------------------------------------------------------------------
    def operation(self) -> str:
        labels = {label: key for key, label in lc.OPERATION_LABELS.items()}
        return labels.get(self.operation_var.get(), lc.ADD_REMOVE)

    def spec(self) -> dict[str, Any]:
        return {
            "operation": self.operation(),
            "original": self._tested(),
            "candidates": [{"name": c.name, "weight": c.weight} for c in self._candidates],
            "negative_prompt": self.negative_var.get(),
            "fixed_slots": self._fixed_slots(),
        }

    def _fixed_slots(self) -> dict[str, str]:
        pairs = (item.partition("=") for item in self.slots_var.get().split(",") if "=" in item)
        return {key.strip(): value.strip() for key, _sep, value in pairs if key.strip()}

    def signature(self) -> str:
        from src.learning.prompt_slot_experiment import digest

        return digest([self.spec(), self._prompt()])

    def validation_error(self, images: int) -> str:
        return lc.validation_error(self.spec(), self._prompt(), images)

    def load(self, spec: Mapping[str, Any]) -> None:
        self._candidates = [
            lc.Candidate(item.get("name"), item.get("weight") or 0.0)
            for item in spec.get("candidates") or ()
        ]
        self.operation_var.set(
            lc.OPERATION_LABELS.get(str(spec.get("operation")), lc.OPERATION_LABELS[lc.ADD_REMOVE])
        )
        self.negative_var.set(spec.get("negative_prompt", ""))
        self.slots_var.set(
            ", ".join(f"{k}={v}" for k, v in (spec.get("fixed_slots") or {}).items())
        )
        self._baseline = lc.baseline_loras(self._prompt())
        self._render()
        original = spec.get("original")
        names = {n.casefold(): n for n, _ in self._baseline}
        self.original_var.set(
            self._label(names[original.casefold()])
            if original and original.casefold() in names
            else NONE_CHOICE
        )
        self._render()

    def refresh_visibility(self) -> None:
        self.negative_entry.configure(show="" if self._visible() else "•")
        self._render()

    # -- background discovery ----------------------------------------------------------------------------------
    def invalidate(self) -> None:
        """A newer experiment/model context makes any in-flight discovery result stale."""
        self._request += 1
        self._cancel.set()

    def ensure_inventory(self) -> None:
        if not self._resources and not self._request:
            self.refresh_inventory()

    def refresh_inventory(self) -> None:
        if self._closed:
            return
        self._request += 1
        request = self._request
        self._cancel.set()
        cancel = self._cancel = threading.Event()
        self.status_var.set(
            "Discovering local LoRAs… candidates are not verified until discovery completes."
        )
        loader, invoker = self._loader, self._invoker

        def work() -> None:
            resources: Mapping[str, Any] = {}
            failed = False
            try:
                resources = loader(cancel.is_set)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
                # path/content-bearing exception text must never reach the GUI
                failed = True
            invoker.invoke(lambda: self._finish(request, dict(resources), failed))

        from src.utils.thread_registry import get_thread_registry

        try:
            get_thread_registry().spawn(
                target=work,
                name="LoRA-Composition-Discovery",
                daemon=False,
                purpose="Read local LoRA evidence",
            )
        except RuntimeError:
            self._finish(request, {}, True)

    def _finish(self, request: int, resources: dict[str, Any], failed: bool) -> None:
        if self._closed or request != self._request:
            return
        if failed:
            self.status_var.set(
                "Local discovery failed. Installed inventory is unverified. Retry Refresh."
            )
            return
        self._resources = resources
        if self._inventory_listener is not None:
            self._inventory_listener(resources)
        self.status_var.set(
            f"{len(resources)} installed LoRAs. Preview verifies identity and compatibility; "
            "backend admission remains required."
        )
        self._render_inventory()
        self._render()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self or self._closed:
            return
        self._closed = True
        self._cancel.set()
        self._invoker.dispose()

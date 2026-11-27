"""N5 Packs x Models batch builder: pick PromptPacks and models, see the exact totals, queue one named batch.

The builder only captures intent and renders the plan. Planning and Queue run on background tasks through
``src/controller/app_controller_services/pack_model_batch_service.py``; their results come back on the Tk thread.

``BatchBuilderPanel`` is the builder itself. The Pipeline tab's **Packs × Models…** button opens it in
``BatchBuilderDialog``; the Generate workspace (N6) embeds the same panel. Both read their packs, models and stage
toggles from the Pipeline tab's PromptPack card through ``batch_sources``.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from tkinter import ttk
from typing import Any

from src.controller.app_controller_services.pack_model_batch_service import (
    BatchPlan,
    BatchRequest,
    default_batch_name,
)

#: ``(request, on_result, on_error)``: plan off the Tk thread.
PlanBatch = Callable[[BatchRequest, Callable[[BatchPlan], None], Callable[[Exception], None]], None]
#: ``(plan, on_result, on_error)``: queue off the Tk thread; ``on_result`` gets the submitted job count.
QueueBatch = Callable[[BatchPlan, Callable[[int], None], Callable[[Exception], None]], None]

_EXPLANATION = (
    "A model with a saved recipe uses its own sampler, steps, CFG and size; other models use the "
    "Pipeline tab's settings. Clear \"Use each model's saved recipe\" to use the Pipeline tab's "
    "settings for every model. Plan compiles every combination first, so the totals below are "
    "exactly what Queue adds."
)


@dataclass(frozen=True)
class BatchSources:
    """What the builder offers, read from the Pipeline tab's PromptPack card."""

    packs: tuple[str, ...] = ()
    models: tuple[tuple[str, str], ...] = ()  # (display, internal)
    selected_packs: tuple[str, ...] = ()
    selected_model: str = ""
    adetailer: bool = False
    upscale: bool = False


class BatchBuilderPanel(ttk.Frame):
    """The Packs x Models builder: lists, options, Plan, the exact summary and Queue batch."""

    def __init__(
        self,
        parent: Any,
        *,
        packs: Sequence[str],
        models: Sequence[tuple[str, str]],
        plan_batch: PlanBatch,
        queue_batch: QueueBatch,
        selected_packs: Sequence[str] = (),
        selected_model: str = "",
        adetailer: bool = False,
        upscale: bool = False,
        on_close: Callable[[], None] | None = None,
        summary_height: int = 14,
        wraplength: int = 900,
    ) -> None:
        super().__init__(parent, padding=12)
        self._packs = list(packs)
        self._models = list(models)  # (display, internal)
        self._plan_batch, self._queue_batch = plan_batch, queue_batch
        self.plan: BatchPlan | None = None
        self._inflight = False

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(5, weight=2)

        ttk.Label(self, text="PromptPacks").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="Models").grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.pack_list = self._listbox(self, row=1, column=0)
        self.model_list = self._listbox(self, row=1, column=1)
        self._fill(self.pack_list, self._packs)
        self._fill(self.model_list, [display for display, _ in self._models])
        self._select(selected_packs, selected_model)

        options = ttk.Frame(self)
        options.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.adetailer_var = tk.BooleanVar(master=self, value=bool(adetailer))
        self.upscale_var = tk.BooleanVar(master=self, value=bool(upscale))
        ttk.Checkbutton(
            options, text="ADetailer", variable=self.adetailer_var, command=self._changed
        ).pack(side="left")
        ttk.Checkbutton(
            options, text="Upscale", variable=self.upscale_var, command=self._changed
        ).pack(side="left", padx=(12, 0))
        self.use_recipes_var = tk.BooleanVar(master=self, value=True)
        ttk.Checkbutton(
            options,
            text="Use each model's saved recipe",
            variable=self.use_recipes_var,
            command=self._changed,
        ).pack(side="left", padx=(12, 0))
        ttk.Label(options, text="Batch name").pack(side="left", padx=(24, 4))
        self.name_var = tk.StringVar(master=self, value="")
        self.name_entry = ttk.Entry(options, textvariable=self.name_var, width=48)
        self.name_entry.pack(side="left", fill="x", expand=True)
        self._name_edited = False
        self.name_entry.bind("<Key>", lambda _event: self._mark_name_edited())

        ttk.Label(self, text=_EXPLANATION, wraplength=wraplength, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        self.status_label = ttk.Label(self, text="Pick PromptPacks and models, then Plan.")
        self.status_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 4))
        self.summary = tk.Text(self, height=summary_height, wrap="word", state="disabled")
        self.summary.grid(row=5, column=0, columnspan=2, sticky="nsew")

        self.actions = ttk.Frame(self)
        self.actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.cancel_button: ttk.Button | None = None
        if on_close is not None:
            self.cancel_button = ttk.Button(self.actions, text="Close", command=on_close)
            self.cancel_button.pack(side="right")
        self.queue_button = ttk.Button(self.actions, text="Queue batch", command=self._queue)
        self.queue_button.pack(side="right", padx=8)
        self.queue_button.state(["disabled"])
        self.plan_button = ttk.Button(self.actions, text="Plan", command=self._plan)
        self.plan_button.pack(side="left")
        for listbox in (self.pack_list, self.model_list):
            listbox.bind("<<ListboxSelect>>", lambda _event: self._changed())
        self._refresh_default_name()

    @staticmethod
    def _listbox(parent: Any, *, row: int, column: int) -> tk.Listbox:
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=column, sticky="nsew", padx=(8 if column else 0, 0))
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        listbox = tk.Listbox(holder, selectmode="extended", exportselection=False, height=10)
        listbox.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=listbox.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        listbox.configure(yscrollcommand=scroll.set)
        return listbox

    @staticmethod
    def _fill(listbox: tk.Listbox, values: Sequence[str]) -> None:
        listbox.delete(0, "end")
        for value in values:
            listbox.insert("end", value)

    def _select(self, packs: Sequence[str], model: str | Sequence[str]) -> None:
        wanted_models = {model} if isinstance(model, str) else set(model)
        for index, name in enumerate(self._packs):
            if name in packs:
                self.pack_list.selection_set(index)
        for index, (display, internal) in enumerate(self._models):
            if wanted_models & {display, internal} - {""}:
                self.model_list.selection_set(index)

    @property
    def inflight(self) -> bool:
        return self._inflight

    def set_sources(self, sources: BatchSources) -> None:
        """Replace the pack and model lists (N6 Refresh), keeping the operator's selection where it still exists.

        With nothing selected yet, the Pipeline tab's own selection is taken. Ignored while planning or queueing;
        a changed list makes the current plan stale, exactly like a changed selection."""

        if self._inflight:
            return
        packs, models = list(sources.packs), list(sources.models)
        if packs == self._packs and models == self._models:
            return
        kept_packs = self.selected_packs()
        kept_models = self.selected_models()
        self._packs, self._models = packs, models
        self._fill(self.pack_list, self._packs)
        self._fill(self.model_list, [display for display, _ in self._models])
        if kept_packs or kept_models:
            self._select(kept_packs, kept_models)
        else:
            self._select(sources.selected_packs, sources.selected_model)
            self.adetailer_var.set(bool(sources.adetailer))
            self.upscale_var.set(bool(sources.upscale))
        self._changed()

    # -- intent ------------------------------------------------------------------------------------------------

    def selected_packs(self) -> list[str]:
        return [self._packs[index] for index in self.pack_list.curselection()]  # type: ignore[no-untyped-call]

    def selected_models(self) -> list[str]:
        return [self._models[index][1] for index in self.model_list.curselection()]  # type: ignore[no-untyped-call]

    def request(self) -> BatchRequest:
        packs, models = self.selected_packs(), self.selected_models()
        name = self.name_var.get().strip() or default_batch_name(packs, len(models))
        return BatchRequest(
            name=name,
            pack_ids=tuple(packs),
            models=tuple(models),
            adetailer=bool(self.adetailer_var.get()),
            upscale=bool(self.upscale_var.get()),
            use_recipes=bool(self.use_recipes_var.get()),
        )

    def _mark_name_edited(self) -> None:
        self._name_edited = True

    def _refresh_default_name(self) -> None:
        if not self._name_edited:
            self.name_var.set(
                default_batch_name(self.selected_packs(), len(self.selected_models()))
            )

    def _changed(self) -> None:
        """Any change to the selection invalidates the plan: Queue only ever submits what the summary shows."""

        self._refresh_default_name()
        if self.plan is not None:
            self.plan = None
            self.queue_button.state(["disabled"])
            self.status_label.configure(text="Selection changed. Plan again before queueing.")

    # -- plan and queue ----------------------------------------------------------------------------------------

    def _busy(self, busy: bool, text: str) -> None:
        self._inflight = busy
        self.status_label.configure(text=text)
        for button in (self.plan_button, self.cancel_button):
            if button is not None:
                button.state(["disabled"] if busy else ["!disabled"])
        if busy:
            self.queue_button.state(["disabled"])

    def _plan(self) -> None:
        request = self.request()
        problems = request.problems()
        if problems:
            self.status_label.configure(text=" ".join(problems))
            return
        self.plan = None
        self._busy(True, "Planning: compiling every combination...")
        self._plan_batch(request, self._on_plan, self._on_plan_error)

    def _on_plan(self, plan: BatchPlan) -> None:
        if not self.winfo_exists():
            return
        self._busy(False, f"Planned {plan.jobs} job(s), {plan.images} image(s).")
        if replace(plan.request, name="") != replace(self.request(), name=""):
            self.status_label.configure(
                text="Selection changed while planning. Plan again before queueing."
            )
            return
        self.plan = plan
        self._show("\n".join(plan.summary_lines()))
        if plan.queueable:
            self.queue_button.configure(text=f"Queue batch ({plan.jobs} jobs)")
            self.queue_button.state(["!disabled"])
        else:
            self.status_label.configure(text="Nothing in this batch can be queued.")

    def _on_plan_error(self, exc: Exception) -> None:
        if self.winfo_exists():
            self._busy(False, f"Could not plan the batch. {exc}")

    def _queue(self) -> None:
        plan = self.plan
        if plan is None or not plan.queueable:
            return
        plan = replace(
            plan,
            request=replace(plan.request, name=self.name_var.get().strip() or plan.request.name),
        )
        self._busy(True, f"Queueing {plan.jobs} job(s)...")
        self._queue_batch(plan, self._on_queued, self._on_queue_error)

    def _on_queued(self, count: int) -> None:
        if not self.winfo_exists():
            return
        self.plan = None
        self._busy(
            False, f"Queued {count} job(s) as one batch." if count else "Nothing was queued."
        )
        self.queue_button.configure(text="Queue batch")

    def _on_queue_error(self, exc: Exception) -> None:
        if self.winfo_exists():
            self._busy(False, f"The batch was not queued. {exc}")
            if self.plan is not None:
                self.queue_button.state(["!disabled"])

    def _show(self, text: str) -> None:
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", text)
        self.summary.configure(state="disabled")

    def summary_text(self) -> str:
        return self.summary.get("1.0", "end").strip()


class BatchBuilderDialog(tk.Toplevel):
    """The Pipeline tab's Packs x Models window: one ``BatchBuilderPanel`` (``self.panel``)."""

    def __init__(
        self,
        parent: Any,
        *,
        packs: Sequence[str],
        models: Sequence[tuple[str, str]],
        plan_batch: PlanBatch,
        queue_batch: QueueBatch,
        selected_packs: Sequence[str] = (),
        selected_model: str = "",
        adetailer: bool = False,
        upscale: bool = False,
    ) -> None:
        super().__init__(parent)
        self.title("Packs x Models batch")
        self.geometry("980x640")
        self.transient(parent.winfo_toplevel())
        self.panel = BatchBuilderPanel(
            self,
            packs=packs,
            models=models,
            plan_batch=plan_batch,
            queue_batch=queue_batch,
            selected_packs=selected_packs,
            selected_model=selected_model,
            adetailer=adetailer,
            upscale=upscale,
            on_close=self.destroy,
        )
        self.panel.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", lambda: None if self.panel.inflight else self.destroy())


def batch_sources(sidebar: Any) -> BatchSources | None:
    """Packs, models and stage toggles from the Pipeline tab's PromptPack card; None when it cannot plan yet."""

    controller = getattr(sidebar, "controller", None)
    if controller is None or not hasattr(controller, "_background_tasks"):
        return None
    names = list(getattr(sidebar, "_current_pack_names", []) or [])
    listbox = getattr(sidebar, "pack_listbox", None)
    selection = listbox.curselection() if listbox is not None else ()
    panel = (
        sidebar.get_base_generation_panel()
        if hasattr(sidebar, "get_base_generation_panel")
        else None
    )
    stages = getattr(sidebar, "stage_states", {}) or {}
    return BatchSources(
        packs=tuple(names),
        models=tuple(panel.model_choices()) if panel is not None else (),
        selected_packs=tuple(names[index] for index in selection if index < len(names)),
        selected_model=panel.selected_model_name() if panel is not None else "",
        adetailer=bool(stages["adetailer"].get()) if "adetailer" in stages else False,
        upscale=bool(stages["upscale"].get()) if "upscale" in stages else False,
    )


def batch_callbacks(controller_provider: Callable[[], Any]) -> tuple[PlanBatch, QueueBatch]:
    """Plan and Queue through the N5 service, resolving the controller at call time."""

    from src.controller.app_controller_services import pack_model_batch_service as service

    def _controller() -> Any:
        controller = controller_provider()
        if controller is None or not hasattr(controller, "_background_tasks"):
            raise RuntimeError("The batch builder is not connected yet; try again in a moment.")
        return controller

    def plan_batch(
        request: BatchRequest,
        on_result: Callable[[BatchPlan], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        try:
            controller = _controller()
        except RuntimeError as exc:
            on_error(exc)
            return
        service.request_batch_plan(controller, request, on_result=on_result, on_error=on_error)

    def queue_batch(
        plan: BatchPlan,
        on_result: Callable[[int], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        try:
            controller = _controller()
        except RuntimeError as exc:
            on_error(exc)
            return
        service.submit_batch_async(controller, plan, on_result=on_result, on_error=on_error)

    return plan_batch, queue_batch


def open_batch_builder(sidebar: Any) -> BatchBuilderDialog | None:
    """Open the dialog from the Pipeline tab's PromptPack card, seeded with its current pack, model and stages."""

    sources = batch_sources(sidebar)
    if sources is None:
        return None
    controller = sidebar.controller
    plan_batch, queue_batch = batch_callbacks(lambda: controller)
    return BatchBuilderDialog(
        sidebar,
        packs=sources.packs,
        models=sources.models,
        selected_packs=sources.selected_packs,
        selected_model=sources.selected_model,
        adetailer=sources.adetailer,
        upscale=sources.upscale,
        plan_batch=plan_batch,
        queue_batch=queue_batch,
    )


__all__ = [
    "BatchBuilderDialog",
    "BatchBuilderPanel",
    "BatchSources",
    "batch_callbacks",
    "batch_sources",
    "open_batch_builder",
]

"""Read-only AI review dialog; only an explicit Accept callback can edit the authoring buffer."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk

from src.ai_assist.contracts import SuggestionKind
from src.gui.scrolling import enable_mousewheel
from src.gui.theme_v2 import apply_toplevel_theme, style_text_widget
from src.gui_v2.ai_plan_advice import PLAN_ADVICE_NOTICE, PlanReview, review_text
from src.gui_v2.ai_slot_variety import (
    VARIETY_LABEL,
    VARIETY_NOTICE,
    VarietyReview,
    offered_label,
    variety_text,
)
from src.gui_v2.ai_suggestion_view import (
    KIND_LABELS,
    RUNTIME_DETAIL_BUTTON,
    RUNTIME_DETAIL_HIDE_BUTTON,
    RUNTIME_DETAIL_LABEL,
    SuggestionReview,
)


class AiSuggestionDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_request: Callable[[SuggestionKind], None],
        on_accept: Callable[[], None],
        on_cancel: Callable[[], None],
        on_close: Callable[[], None],
        explanations: dict[SuggestionKind, str],
        trust_label: str = "",
        on_advise: Callable[[str], None] | None = None,
        advise_problem: str = "",
        on_variety: Callable[[str], None] | None = None,
        on_add_value: Callable[[int], None] | None = None,
        variety_problem: str = "",
    ) -> None:
        super().__init__(master)
        self.title("AI suggestion review")
        self.resizable(True, True)
        apply_toplevel_theme(self)
        self._on_close = on_close
        self._closing = False
        self._requests: list[tuple[ttk.Button, SuggestionKind]] = []
        kinds = ttk.Frame(self)
        kinds.pack(fill="x", padx=8, pady=8)
        for kind, label in KIND_LABELS.items():
            button = ttk.Button(kinds, text=label, command=partial(on_request, kind))
            button.pack(side="left", padx=4)
            self._requests.append((button, kind))
        self._explanations = explanations
        self._on_advise = on_advise
        self._advise_problem = advise_problem
        self._trust_label = trust_label
        self.trust_var = tk.StringVar(value=trust_label)
        ttk.Label(self, textvariable=self.trust_var, wraplength=760, justify="left").pack(
            fill="x", padx=8
        )
        self.goal_var = tk.StringVar(value="")
        self.advise_button: ttk.Button | None = None
        self.goal_entry: ttk.Entry | None = None
        self._copy_buttons: list[ttk.Button] = []
        if on_advise is not None:
            plan = ttk.LabelFrame(self, text="Advisory plan (advice, not a plan)")
            plan.pack(fill="x", padx=8, pady=(0, 4))
            ttk.Label(plan, text=PLAN_ADVICE_NOTICE, wraplength=740, justify="left").pack(
                fill="x", padx=4, pady=2
            )
            row = ttk.Frame(plan)
            row.pack(fill="x", padx=4, pady=2)
            ttk.Label(row, text="Goal:").pack(side="left")
            self.goal_entry = ttk.Entry(row, textvariable=self.goal_var, width=70)
            self.goal_entry.pack(side="left", fill="x", expand=True, padx=4)
            self.advise_button = ttk.Button(row, text="Advise plan", command=self._advise)
            self.advise_button.pack(side="left", padx=4)
            self.copy_frame = ttk.Frame(plan)
            self.copy_frame.pack(fill="x", padx=4, pady=2)
        # Slot variety (AI-212): a goal, one request button, and per-value explicit additions of offered values only.
        self._on_variety = on_variety
        self._on_add_value = on_add_value
        self._variety_problem = variety_problem
        self.variety_goal_var = tk.StringVar(value="")
        self.variety_button: ttk.Button | None = None
        self.variety_list: tk.Listbox | None = None
        self.add_value_button: ttk.Button | None = None
        self._offered_rows: list[int] = []
        if on_variety is not None:
            variety = ttk.LabelFrame(self, text=VARIETY_LABEL)
            variety.pack(fill="x", padx=8, pady=(0, 4))
            ttk.Label(variety, text=VARIETY_NOTICE, wraplength=740, justify="left").pack(
                fill="x", padx=4, pady=2
            )
            row = ttk.Frame(variety)
            row.pack(fill="x", padx=4, pady=2)
            ttk.Label(row, text="Goal:").pack(side="left")
            self.variety_goal_entry = ttk.Entry(row, textvariable=self.variety_goal_var, width=70)
            self.variety_goal_entry.pack(side="left", fill="x", expand=True, padx=4)
            self.variety_button = ttk.Button(row, text="Suggest variety", command=self._variety)
            self.variety_button.pack(side="left", padx=4)
            offered = ttk.Frame(variety)
            offered.pack(fill="x", padx=4, pady=2)
            self.variety_list = tk.Listbox(
                offered, height=5, selectmode="browse", exportselection=False
            )
            self.variety_list.pack(side="left", fill="x", expand=True)
            self.add_value_button = ttk.Button(
                offered, text="Add selected value", command=self._add_value, state="disabled"
            )
            self.add_value_button.pack(side="left", padx=4, anchor="n")
        self.status_var = tk.StringVar(
            value="Choose the assistance to request. Acceptance changes only the editing buffer."
        )
        ttk.Label(self, textvariable=self.status_var, wraplength=760, justify="left").pack(
            fill="x", padx=8
        )
        self._detail_text = ""
        self._detail_shown = False
        self.detail_button = ttk.Button(
            self, text=RUNTIME_DETAIL_BUTTON, command=self._toggle_detail, state="disabled"
        )
        self.detail_button.pack(anchor="w", padx=8)
        self.detail_label = ttk.Label(
            self, text=RUNTIME_DETAIL_LABEL, wraplength=760, justify="left"
        )
        self.detail_view = tk.Text(self, height=8, width=100, wrap="word", undo=False)
        style_text_widget(self.detail_view)
        self.detail_view.configure(state="disabled")
        self.preview = tk.Text(self, height=22, width=100, wrap="word", undo=False)
        style_text_widget(self.preview)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=scrollbar.set, state="disabled")
        scrollbar.pack(side="right", fill="y")
        self.preview.pack(fill="both", expand=True, padx=8, pady=8)
        enable_mousewheel(self.preview)
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=8, pady=8)
        self.accept_button = ttk.Button(
            actions, text="Accept rewrite", command=on_accept, state="disabled"
        )
        self.accept_button.pack(side="right", padx=4)
        ttk.Button(actions, text="Reject / Close", command=self.close).pack(side="right", padx=4)
        self.cancel_button = ttk.Button(
            actions, text="Cancel Request", command=on_cancel, state="disabled"
        )
        self.cancel_button.pack(side="left")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._set_requests(False)
        self._set_advise(False)
        unavailable = [f"{KIND_LABELS[k]}: {v}" for k, v in explanations.items() if v]
        if advise_problem:
            unavailable.append(f"Advise plan: {advise_problem}")
        if variety_problem and on_variety is not None:
            unavailable.append(f"Suggest variety: {variety_problem}")
        self._text("\n".join(unavailable))

    def _advise(self) -> None:
        if self._on_advise is not None:
            self._on_advise(self.goal_var.get())

    def _set_advise(self, running: bool) -> None:
        # Both goal actions share the dialog's single-flight state.
        if self.advise_button is not None:
            self.advise_button.state(
                ["disabled"] if running or self._advise_problem else ["!disabled"]
            )
        if self.variety_button is not None:
            self.variety_button.state(
                ["disabled"] if running or self._variety_problem else ["!disabled"]
            )

    def _variety(self) -> None:
        if self._on_variety is not None:
            self._on_variety(self.variety_goal_var.get())

    def _add_value(self) -> None:
        if self._on_add_value is None or self.variety_list is None:
            return
        listbox = self.variety_list
        chosen = [i for i in range(len(self._offered_rows)) if listbox.selection_includes(i)]
        if len(chosen) == 1:
            self._on_add_value(self._offered_rows[chosen[0]])

    def _clear_variety(self) -> None:
        self._offered_rows = []
        if self.variety_list is not None:
            self.variety_list.delete(0, "end")
        if self.add_value_button is not None:
            self.add_value_button.state(["disabled"])

    def show_variety(self, review: VarietyReview) -> None:
        """Judged slot-variety proposals. Only offered values enter the list; rejected ones appear in the text only."""

        self._clear_copy_buttons()
        self._clear_variety()
        self.status(review.status)
        self._set_requests(False)
        self._set_advise(False)
        self.cancel_button.state(["disabled"])
        self.accept_button.state(["disabled"])
        self._text(variety_text(review))
        if self.variety_list is None:
            return
        for row in review.offered_rows:
            self.variety_list.insert("end", offered_label(row))
            self._offered_rows.append(row.index)
        if self._offered_rows and self.add_value_button is not None:
            self.add_value_button.state(["!disabled"])

    def running_variety(self) -> None:
        self._clear_copy_buttons()
        self._clear_variety()
        self.clear_runtime_detail()
        self.status("Suggest variety: request running…")
        self._text("")
        self._set_requests(True)
        self._set_advise(True)
        self.accept_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])

    @property
    def trust_label(self) -> str:
        return self._trust_label

    def set_advise_problem(self, problem: str) -> None:
        self._advise_problem = problem
        self._set_advise(False)

    def _clear_copy_buttons(self) -> None:
        for button in self._copy_buttons:
            button.destroy()
        self._copy_buttons.clear()

    def set_runtime_detail(self, text: str) -> None:
        """Hold raw runtime output for the operator. Nothing is shown until "Show runtime detail" is pressed."""

        self._hide_detail()
        self._detail_text = text
        self.detail_button.state(["!disabled"] if text else ["disabled"])

    def _toggle_detail(self) -> None:
        if self._detail_shown:
            self._hide_detail()
            return
        if not self._detail_text:
            return
        self.detail_label.pack(fill="x", padx=8, before=self.preview)
        self.detail_view.pack(fill="x", padx=8, pady=(0, 4), before=self.preview)
        self.detail_view.configure(state="normal")
        self.detail_view.delete("1.0", "end")
        self.detail_view.insert("1.0", self._detail_text)
        self.detail_view.configure(state="disabled")
        self.detail_button.configure(text=RUNTIME_DETAIL_HIDE_BUTTON)
        self._detail_shown = True

    def _hide_detail(self) -> None:
        self.detail_view.configure(state="normal")
        self.detail_view.delete("1.0", "end")
        self.detail_view.configure(state="disabled")
        self.detail_view.pack_forget()
        self.detail_label.pack_forget()
        self.detail_button.configure(text=RUNTIME_DETAIL_BUTTON)
        self._detail_shown = False

    def clear_runtime_detail(self) -> None:
        self.set_runtime_detail("")

    def show_plan(self, review: PlanReview) -> None:
        """Read-only display of a judged advisory plan. The only actions are per-step clipboard copies."""

        self._clear_copy_buttons()
        self._clear_variety()
        self.status(review.status)
        self._set_requests(False)
        self._set_advise(False)
        self.cancel_button.state(["disabled"])
        self.accept_button.state(["disabled"])
        self._text(review_text(review))
        if self.advise_button is not None:
            for row in review.rows:
                button = ttk.Button(
                    self.copy_frame,
                    text=f"Copy step {row.index}",
                    command=partial(self._copy, row.copy_text),
                )
                button.pack(side="left", padx=2)
                self._copy_buttons.append(button)

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    def running_plan(self, planning_for: str = "") -> None:
        self._clear_copy_buttons()
        self._clear_variety()
        self.clear_runtime_detail()
        self.status("Advise plan: request running…")
        self._text(planning_for)
        self._set_requests(True)
        self._set_advise(True)
        self.accept_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])

    def set_trust_label(self, label: str) -> None:
        """Every surface of a suggestion from an unqualified Preview model carries this label."""

        self._trust_label = label
        self.trust_var.set(label)

    def status(self, text: str) -> None:
        self.status_var.set(f"[{self._trust_label}] {text}" if self._trust_label else text)

    def _set_requests(self, running: bool) -> None:
        for button, kind in self._requests:
            button.state(["disabled"] if running or self._explanations.get(kind) else ["!disabled"])

    def _text(self, value: str) -> None:
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", value)
        self.preview.configure(state="disabled")

    def running(self, kind: SuggestionKind) -> None:
        self._clear_variety()
        self.clear_runtime_detail()
        self.status(f"{KIND_LABELS[kind]}: request running…")
        self._text("")
        self._set_requests(True)
        self._set_advise(True)
        self.accept_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])

    def show_review(self, model: SuggestionReview) -> None:
        self._clear_copy_buttons()
        self._clear_variety()
        self.status(f"{model.kind}: {model.status}")
        self._set_requests(False)
        self._set_advise(False)
        self.cancel_button.state(["disabled"])
        self.accept_button.state(["!disabled"] if model.can_accept else ["disabled"])
        lines: list[str] = []
        if model.original or model.proposed:
            lines.extend(
                (
                    "Original authored material",
                    model.original,
                    "",
                    "Proposed material",
                    model.proposed,
                )
            )
        if model.changes:
            lines.extend(("", "Model change codes", ", ".join(model.changes)))
        p = model.compatibility
        if p is not None:
            lines.extend(
                (
                    "",
                    "Deterministic target compatibility (separate from model changes)",
                    p.summary,
                    "Effective positive",
                    p.adapted_positive,
                    f"Effective negative: {p.adapted_negative}",
                    f"Embeddings: {p.embeddings}",
                    f"LoRAs: {p.loras}",
                    *p.steps,
                    *p.notes,
                )
            )
        self._text("\n".join(lines))

    def clear_sensitive(self) -> None:
        self._clear_copy_buttons()
        self._clear_variety()
        self.clear_runtime_detail()
        self.goal_var.set("")
        self.variety_goal_var.set("")
        self._text("")
        self.accept_button.state(["disabled"])
        self.status_var.set(
            "Content visibility or source context changed. Request a new suggestion."
        )

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.clear_sensitive()
        self._on_close()
        self.destroy()

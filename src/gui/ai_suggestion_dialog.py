"""AI Assist workbench window: tabs for each function, one list of change cards, one Apply flow (AI-230).

Read-only except through callbacks the Prompt tab owner supplies: Accept rewrite, Apply on a card, Apply selected, Apply all
offered and Undo last. Each runs the owner's stale-checked mutators; this window never changes workspace state itself.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from functools import partial
from tkinter import ttk

from src.ai_assist.contracts import (
    DEFAULT_VARIETY_PER_SLOT,
    MAX_VARIETY_NEW_VALUES,
    VARIETY_FOCUS_DIRECT,
    SuggestionKind,
)
from src.gui.scrolling import enable_mousewheel
from src.gui.theme_v2 import apply_toplevel_theme, style_text_widget
from src.gui.widgets.ai_card_list import AiCardList
from src.gui_v2.ai_changes import ProposedChange
from src.gui_v2.ai_plan_advice import PLAN_ADVICE_NOTICE, PlanReview, review_text
from src.gui_v2.ai_slot_phrase import (
    PHRASE_LABEL,
    PHRASE_NOTICE,
    PHRASE_REVERT_TEXT,
    PhraseReview,
    phrase_text,
)
from src.gui_v2.ai_slot_proposal import (
    PROPOSAL_LABEL,
    PROPOSAL_NOTICE,
    PROPOSAL_REVERT_TEXT,
    ProposalReview,
    proposal_text,
)
from src.gui_v2.ai_slot_variety import (
    FOCUS_LABELS,
    VARIETY_LABEL,
    VARIETY_NOTICE,
    VarietyReview,
    variety_text,
)
from src.gui_v2.ai_suggestion_view import (
    KIND_LABELS,
    RUNTIME_DETAIL_BUTTON,
    RUNTIME_DETAIL_HIDE_BUTTON,
    RUNTIME_DETAIL_LABEL,
    SuggestionReview,
)

MODE_VALUES = "values"
MODE_SLOT = "slot"
MODE_PHRASE = "phrase"
MODE_LABELS = {
    MODE_VALUES: "Add values to existing slots",
    MODE_SLOT: "Propose new slots",
    MODE_PHRASE: "Turn a selected phrase into a slot",
}
QUICK_GOALS = ("lighting", "environment", "camera angle", "mood", "pose", "clothing")
TAB_PROMPT, TAB_SLOTS, TAB_PLAN, TAB_CHECK, TAB_DETAILS = (
    "prompt",
    "slots",
    "plan",
    "check",
    "details",
)
TAB_LABELS = {
    TAB_PROMPT: "Prompt",
    TAB_SLOTS: "Matrix slots",
    TAB_PLAN: "Plan",
    TAB_CHECK: "Check",
    TAB_DETAILS: "Details",
}
DETAILS_NOTICE = (
    "What a request sends: Rewrite and Target Fit send the slot's positive and negative prompt and the closed lists of "
    "targets; Suggest variety sends your goal and the selected slots with their values; Suggest new slot sends your goal, "
    "the positive prompt sentence, the slot names and short snippets of the sentence; Advise plan sends your goal and the "
    "closed lists of models and workflows. Nothing is saved, and the Check tab sends nothing at all."
)
BRIDGE_TEXT = "Propose a new slot for this goal"
MORE_TEXT = "Ask for more"
UNDO_TEXT = "Undo last"
APPLY_SELECTED_TEXT = "Apply selected"
APPLY_ALL_TEXT = "Apply all offered"


RETRY_UNCENSORED_TEXT = "Try with the uncensored model"


class AiSuggestionDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_request: Callable[[SuggestionKind], None],
        on_accept: Callable[[], None],
        on_cancel: Callable[[], None],
        on_retry: Callable[[], None] | None = None,
        on_close: Callable[[], None],
        explanations: dict[SuggestionKind, str],
        trust_label: str = "",
        on_advise: Callable[[str], None] | None = None,
        advise_problem: str = "",
        on_variety: Callable[[str, tuple[str, ...], str, str], None] | None = None,
        on_add_value: Callable[[int], object] | None = None,
        variety_problem: str = "",
        variety_slots: str = "",
        variety_slot_options: Sequence[tuple[str, bool, str]] = (),
        on_propose: Callable[[str], None] | None = None,
        on_add_proposal: Callable[[int], object] | None = None,
        proposal_problem: str = "",
        on_apply: Callable[[tuple[str, ...]], object] | None = None,
        on_undo: Callable[[], object] | None = None,
        on_check: Callable[[], None] | None = None,
        on_check_apply: Callable[[tuple[str, ...]], object] | None = None,
        on_phrase: Callable[[str], None] | None = None,
        phrase_problem: str = "",
        context_text: str = "",
    ) -> None:
        super().__init__(master)
        self.title("AI Assist")
        self.geometry("860x900")
        self.resizable(True, True)
        apply_toplevel_theme(self)
        self._on_close = on_close
        self._closing = False
        self._requests: list[tuple[ttk.Button, SuggestionKind]] = []
        self._explanations = explanations
        self._on_advise = on_advise
        self._advise_problem = advise_problem
        self._trust_label = trust_label
        self._on_apply = on_apply
        self._on_add_value = on_add_value
        self._on_add_proposal = on_add_proposal
        self._on_undo = on_undo
        self._on_check = on_check
        self._on_check_apply = on_check_apply
        self._on_variety = on_variety
        self._variety_problem = variety_problem
        self._on_propose = on_propose
        self._proposal_problem = proposal_problem
        self._on_phrase = on_phrase
        self._phrase_problem = phrase_problem
        self._last_slots_action = ""
        self._copy_buttons: list[ttk.Button] = []
        self._running = False

        # -- header: where this window points, the trust label, the status line --------------------------------------------
        self.context_var = tk.StringVar(value=context_text)
        ttk.Label(self, textvariable=self.context_var, wraplength=820, justify="left").pack(
            fill="x", padx=8, pady=(8, 0)
        )
        self.trust_var = tk.StringVar(value=trust_label)
        ttk.Label(self, textvariable=self.trust_var, wraplength=820, justify="left").pack(
            fill="x", padx=8
        )
        self.status_var = tk.StringVar(
            value="Choose the assistance to request. Acceptance changes only the editing buffer."
        )
        ttk.Label(self, textvariable=self.status_var, wraplength=820, justify="left").pack(
            fill="x", padx=8, pady=(2, 4)
        )

        # -- footer first (so it keeps its place when the window is small): cancel, undo, close --------------------------
        actions = ttk.Frame(self)
        actions.pack(side="bottom", fill="x", padx=8, pady=8)
        self.cancel_button = ttk.Button(
            actions, text="Cancel Request", command=on_cancel, state="disabled"
        )
        self.cancel_button.pack(side="left")
        # Shown only after a refusal, while an approved uncensored model can take that request.
        self.retry_button = ttk.Button(actions, text=RETRY_UNCENSORED_TEXT, command=on_retry or "")
        ttk.Button(actions, text="Reject / Close", command=self.close).pack(side="right", padx=4)
        self.undo_button = ttk.Button(actions, text=UNDO_TEXT, command=self._undo, state="disabled")
        self.undo_button.pack(side="right", padx=4)
        self.applied_var = tk.StringVar(value="")
        ttk.Label(actions, textvariable=self.applied_var).pack(side="right", padx=8)

        # -- results text (shared), below the tabs ---------------------------------------------------------------------------
        results = ttk.LabelFrame(self, text="Details of the last result")
        results.pack(side="bottom", fill="both", expand=True, padx=8, pady=(4, 0))
        self.preview = tk.Text(results, height=9, width=100, wrap="word", undo=False)
        style_text_widget(self.preview)
        scrollbar = ttk.Scrollbar(results, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=scrollbar.set, state="disabled")
        scrollbar.pack(side="right", fill="y")
        self.preview.pack(fill="both", expand=True, padx=4, pady=4)
        enable_mousewheel(self.preview)

        # -- tabs --------------------------------------------------------------------------------------------------------------
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(side="top", fill="x", padx=8, pady=(0, 4))
        self.tabs: dict[str, ttk.Frame] = {}
        for key in (TAB_PROMPT, TAB_SLOTS, TAB_PLAN, TAB_CHECK, TAB_DETAILS):
            frame = ttk.Frame(self.notebook)
            self.tabs[key] = frame
            if key == TAB_CHECK and on_check is None:
                continue
            self.notebook.add(frame, text=TAB_LABELS[key])
        self._build_prompt_tab(self.tabs[TAB_PROMPT], on_request, on_accept)
        self._build_slots_tab(self.tabs[TAB_SLOTS], variety_slots, variety_slot_options)
        self._build_plan_tab(self.tabs[TAB_PLAN])
        self._build_check_tab(self.tabs[TAB_CHECK])
        self._build_details_tab(self.tabs[TAB_DETAILS])
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)

        self.protocol("WM_DELETE_WINDOW", self.close)
        self._set_requests(False)
        self._set_advise(False)
        unavailable = [f"{KIND_LABELS[k]}: {v}" for k, v in explanations.items() if v]
        if advise_problem:
            unavailable.append(f"Advise plan: {advise_problem}")
        if variety_problem and on_variety is not None:
            unavailable.append(f"Suggest variety: {variety_problem}")
        if proposal_problem and on_propose is not None:
            unavailable.append(f"Suggest new slot: {proposal_problem}")
        if phrase_problem and on_phrase is not None:
            unavailable.append(f"Slot from phrase: {phrase_problem}")
        self._text("\n".join(unavailable))

    # -- tab construction -------------------------------------------------------------------------------------------------------

    def _build_prompt_tab(
        self,
        tab: ttk.Frame,
        on_request: Callable[[SuggestionKind], None],
        on_accept: Callable[[], None],
    ) -> None:
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=4, pady=6)
        for kind, label in KIND_LABELS.items():
            button = ttk.Button(row, text=label, command=partial(on_request, kind))
            button.pack(side="left", padx=4)
            self._requests.append((button, kind))
        self.accept_button = ttk.Button(
            row, text="Accept rewrite", command=on_accept, state="disabled"
        )
        self.accept_button.pack(side="right", padx=4)
        ttk.Label(
            tab,
            text=(
                "Rewrite replaces this slot's positive and negative prompt only when you press Accept rewrite; Undo last "
                "restores them. Target Fit and Workflow Choice are advice only."
            ),
            wraplength=800,
            justify="left",
        ).pack(fill="x", padx=4, pady=(0, 6))

    def _build_plan_tab(self, tab: ttk.Frame) -> None:
        self.goal_var = tk.StringVar(value="")
        self.advise_button: ttk.Button | None = None
        self.goal_entry: ttk.Entry | None = None
        self.copy_frame = ttk.Frame(tab)
        if self._on_advise is None:
            ttk.Label(
                tab, text="Planning advice is unavailable in this editor.", wraplength=800
            ).pack(fill="x", padx=4, pady=6)
            return
        ttk.Label(tab, text=PLAN_ADVICE_NOTICE, wraplength=800, justify="left").pack(
            fill="x", padx=4, pady=2
        )
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text="Goal:").pack(side="left")
        self.goal_entry = ttk.Entry(row, textvariable=self.goal_var, width=70)
        self.goal_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.advise_button = ttk.Button(row, text="Advise plan", command=self._advise)
        self.advise_button.pack(side="left", padx=4)
        self.copy_frame.pack(fill="x", padx=4, pady=2)

    def _build_slots_tab(
        self, tab: ttk.Frame, variety_slots: str, options: Sequence[tuple[str, bool, str]]
    ) -> None:
        self.variety_goal_var = tk.StringVar(value="")
        self.proposal_goal_var = self.variety_goal_var
        self.phrase_goal_var = self.variety_goal_var
        self.variety_button: ttk.Button | None = None
        self.proposal_button: ttk.Button | None = None
        self.phrase_button: ttk.Button | None = None
        self.variety_slot_vars: dict[str, tk.BooleanVar] = {}
        self.variety_slot_checks: dict[str, ttk.Checkbutton] = {}
        self.variety_count_var = tk.StringVar(value=str(DEFAULT_VARIETY_PER_SLOT))
        self.variety_focus_var = tk.StringVar(value=VARIETY_FOCUS_DIRECT)
        self.variety_scope_var = tk.StringVar(value="")
        self.variety_coverage_var = tk.StringVar(value="")
        self.phrase_var = tk.StringVar(value="")
        self.variety_slots_var = tk.StringVar(value=variety_slots)
        self.slots_mode_var = tk.StringVar(value=MODE_VALUES)
        self._mode_panels: dict[str, ttk.Widget] = {}
        self._mode_buttons: dict[str, ttk.Button | None] = {}

        modes = [
            mode
            for mode, wanted in (
                (MODE_VALUES, self._on_variety is not None),
                (MODE_SLOT, self._on_propose is not None),
                (MODE_PHRASE, self._on_phrase is not None),
            )
            if wanted
        ]
        if not modes:
            ttk.Label(tab, text="Matrix slot suggestions are unavailable in this editor.").pack(
                fill="x", padx=4, pady=6
            )
            self.change_cards = AiCardList(tab, on_apply=self._apply_key)
            self.apply_selected_button = ttk.Button(tab)
            self.apply_all_button = ttk.Button(tab)
            self.more_button = ttk.Button(tab)
            self.bridge_button = ttk.Button(tab)
            self.goal_row = ttk.Frame(tab)
            return
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=4, pady=(4, 0))
        for mode in modes:
            ttk.Radiobutton(
                row,
                text=MODE_LABELS[mode],
                variable=self.slots_mode_var,
                value=mode,
                command=partial(self.set_slots_mode, mode),
            ).pack(side="left", padx=(0, 12))
        self.goal_row = ttk.Frame(tab)
        self.goal_row.pack(fill="x", padx=4, pady=2)
        ttk.Label(self.goal_row, text="Goal:").pack(side="left")
        self.variety_goal_entry = ttk.Entry(
            self.goal_row, textvariable=self.variety_goal_var, width=60
        )
        self.variety_goal_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.proposal_goal_entry = self.variety_goal_entry
        if self._on_variety is not None:
            self.variety_button = ttk.Button(
                self.goal_row, text="Suggest variety", command=self._variety
            )
        if self._on_propose is not None:
            self.proposal_button = ttk.Button(
                self.goal_row, text="Suggest new slot", command=self._propose
            )
        if self._on_phrase is not None:
            self.phrase_button = ttk.Button(
                self.goal_row, text="Suggest slot from phrase", command=self._phrase
            )
        self._mode_buttons = {
            MODE_VALUES: self.variety_button,
            MODE_SLOT: self.proposal_button,
            MODE_PHRASE: self.phrase_button,
        }
        chips = ttk.Frame(tab)
        chips.pack(fill="x", padx=4)
        ttk.Label(chips, text="Quick goals:").pack(side="left")
        for goal in QUICK_GOALS:
            ttk.Button(
                chips,
                text=goal,
                width=len(goal) + 2,
                command=partial(self.variety_goal_var.set, goal),
            ).pack(side="left", padx=2)

        # per-mode panels: notice (and scope for values); only the active one is packed
        if self._on_variety is not None:
            panel = ttk.LabelFrame(tab, text=VARIETY_LABEL)
            self._mode_panels[MODE_VALUES] = panel
            ttk.Label(panel, text=VARIETY_NOTICE, wraplength=800, justify="left").pack(
                fill="x", padx=4, pady=2
            )
            ttk.Label(
                panel, textvariable=self.variety_slots_var, wraplength=800, justify="left"
            ).pack(fill="x", padx=4, pady=2)
            self._build_variety_scope(panel, options)
        if self._on_propose is not None:
            panel = ttk.LabelFrame(tab, text=PROPOSAL_LABEL)
            self._mode_panels[MODE_SLOT] = panel
            ttk.Label(panel, text=PROPOSAL_NOTICE, wraplength=800, justify="left").pack(
                fill="x", padx=4, pady=2
            )
            ttk.Label(panel, text=PROPOSAL_REVERT_TEXT, wraplength=800, justify="left").pack(
                fill="x", padx=4, pady=2
            )
        if self._on_phrase is not None:
            panel = ttk.LabelFrame(tab, text=PHRASE_LABEL)
            self._mode_panels[MODE_PHRASE] = panel
            ttk.Label(panel, text=PHRASE_NOTICE, wraplength=800, justify="left").pack(
                fill="x", padx=4, pady=2
            )
            ttk.Label(panel, text=PHRASE_REVERT_TEXT, wraplength=800, justify="left").pack(
                fill="x", padx=4, pady=2
            )
            ttk.Label(panel, textvariable=self.phrase_var, wraplength=800, justify="left").pack(
                fill="x", padx=4, pady=2
            )
        self._panel_anchor = ttk.Frame(tab)
        self._panel_anchor.pack(fill="x")

        self.change_cards = AiCardList(
            tab, on_apply=self._apply_key, on_selection_changed=self._sync_apply
        )
        self.change_cards.pack(fill="x", padx=4, pady=4)
        bar = ttk.Frame(tab)
        bar.pack(fill="x", padx=4, pady=(0, 6))
        self.apply_selected_button = ttk.Button(
            bar, text=APPLY_SELECTED_TEXT, command=self._apply_selected, state="disabled"
        )
        self.apply_selected_button.pack(side="left")
        self.apply_all_button = ttk.Button(
            bar, text=APPLY_ALL_TEXT, command=self._apply_all, state="disabled"
        )
        self.apply_all_button.pack(side="left", padx=6)
        self.more_button = ttk.Button(bar, text=MORE_TEXT, command=self._ask_more, state="disabled")
        self.more_button.pack(side="left", padx=6)
        self.bridge_button = ttk.Button(bar, text=BRIDGE_TEXT, command=self._bridge)
        self.set_slots_mode(modes[0])

    def _build_check_tab(self, tab: ttk.Frame) -> None:
        self.check_summary_var = tk.StringVar(value="")
        ttk.Label(
            tab,
            text=(
                "Deterministic checks of this pack's matrix and prompts. No model is used and nothing is sent anywhere. "
                "Findings with an Apply button change the matrix only when you press it; Undo last restores it."
            ),
            wraplength=800,
            justify="left",
        ).pack(fill="x", padx=4, pady=2)
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=4, pady=2)
        self.check_button: ttk.Button | None = ttk.Button(
            row, text="Run checks", command=self._check
        )
        self.check_button.pack(side="left")
        ttk.Label(row, textvariable=self.check_summary_var).pack(side="left", padx=8)
        self.check_cards = AiCardList(
            tab, on_apply=self._check_apply_key, on_selection_changed=self._sync_check_apply
        )
        self.check_cards.pack(fill="x", padx=4, pady=4)
        self.check_apply_button: ttk.Button | None = ttk.Button(
            tab, text=APPLY_SELECTED_TEXT, command=self._check_apply_selected, state="disabled"
        )
        self.check_apply_button.pack(anchor="w", padx=4, pady=(0, 6))

    def _build_details_tab(self, tab: ttk.Frame) -> None:
        ttk.Label(tab, text=DETAILS_NOTICE, wraplength=800, justify="left").pack(
            fill="x", padx=4, pady=4
        )
        self._detail_text = ""
        self._detail_shown = False
        self.detail_button = ttk.Button(
            tab, text=RUNTIME_DETAIL_BUTTON, command=self._toggle_detail, state="disabled"
        )
        self.detail_button.pack(anchor="w", padx=4)
        self.detail_body = ttk.Frame(tab)
        self.detail_body.pack(fill="x", padx=4)
        self.detail_label = ttk.Label(
            self.detail_body, text=RUNTIME_DETAIL_LABEL, wraplength=800, justify="left"
        )
        self.detail_view = tk.Text(self.detail_body, height=8, width=100, wrap="word", undo=False)
        style_text_widget(self.detail_view)
        self.detail_view.configure(state="disabled")

    def _build_variety_scope(
        self, parent: ttk.LabelFrame, options: Sequence[tuple[str, bool, str]]
    ) -> None:
        """Target slots (checkboxes, none selected at first), count, goal focus and a summary of what will be sent."""

        scope = ttk.LabelFrame(parent, text="Target slots")
        scope.pack(fill="x", padx=4, pady=2)
        tools = ttk.Frame(scope)
        tools.pack(fill="x", padx=4)
        ttk.Button(tools, text="Select all", command=self.select_all_variety_slots).pack(
            side="left"
        )
        ttk.Button(tools, text="Clear", command=self.clear_variety_slots).pack(side="left", padx=4)
        grid = ttk.Frame(scope)
        grid.pack(fill="x", padx=4, pady=2)
        for position, (name, enabled, label) in enumerate(options):
            var = tk.BooleanVar(value=False)
            check = ttk.Checkbutton(
                grid, text=label, variable=var, command=self._variety_scope_changed
            )
            if not enabled:
                check.state(["disabled"])
            check.grid(row=position // 3, column=position % 3, sticky="w", padx=4)
            self.variety_slot_vars[name] = var
            self.variety_slot_checks[name] = check
        quantity = ttk.Frame(parent)
        quantity.pack(fill="x", padx=4, pady=2)
        ttk.Label(quantity, text="Suggestions per slot:").pack(side="left")
        ttk.Spinbox(
            quantity,
            from_=1,
            to=MAX_VARIETY_NEW_VALUES,
            width=4,
            textvariable=self.variety_count_var,
            command=self._variety_scope_changed,
        ).pack(side="left", padx=4)
        ttk.Label(quantity, text="Goal focus:").pack(side="left", padx=(12, 0))
        for value, label in FOCUS_LABELS.items():
            ttk.Radiobutton(
                quantity, text=label, variable=self.variety_focus_var, value=value
            ).pack(side="left", padx=4)
        ttk.Label(parent, textvariable=self.variety_scope_var, wraplength=800, justify="left").pack(
            fill="x", padx=4
        )
        ttk.Label(
            parent, textvariable=self.variety_coverage_var, wraplength=800, justify="left"
        ).pack(fill="x", padx=4)
        self._variety_scope_changed()

    # -- modes and tabs ---------------------------------------------------------------------------------------------------------

    def set_slots_mode(self, mode: str) -> None:
        """Show one function of the Matrix slots tab: its request button and its panel."""

        if mode not in self._mode_panels:
            return
        self.slots_mode_var.set(mode)
        for key, panel in self._mode_panels.items():
            if key == mode:
                panel.pack(fill="x", padx=4, pady=2, before=self._panel_anchor)
            else:
                panel.pack_forget()
        for key, button in self._mode_buttons.items():
            if button is None:
                continue
            if key == mode:
                button.pack(side="left", padx=4)
            else:
                button.pack_forget()

    def select_tab(self, key: str) -> None:
        frame = self.tabs.get(key)
        if frame is not None:
            try:
                self.notebook.select(frame)  # type: ignore[no-untyped-call]  # typeshed leaves ttk.Notebook.select unannotated
            except tk.TclError:
                pass

    def _tab_changed(self, _event: object = None) -> None:
        try:
            current = self.notebook.select()  # type: ignore[no-untyped-call]  # typeshed leaves ttk.Notebook.select unannotated
        except tk.TclError:
            return
        if self._on_check is not None and current == str(self.tabs.get(TAB_CHECK)):
            self._on_check()

    # -- requests ---------------------------------------------------------------------------------------------------------------

    def _advise(self) -> None:
        if self._on_advise is not None:
            self._on_advise(self.goal_var.get())

    def _set_advise(self, running: bool) -> None:
        # Every goal action shares the dialog's single-flight state.
        pairs = (
            (self.advise_button, self._advise_problem),
            (self.variety_button, self._variety_problem),
            (self.proposal_button, self._proposal_problem),
            (self.phrase_button, self._phrase_problem),
        )
        for button, problem in pairs:
            if button is not None:
                button.state(["disabled"] if running or problem else ["!disabled"])
        self._running = running
        self._sync_apply()
        if self.check_button is not None:
            self.check_button.state(["disabled"] if running else ["!disabled"])

    def selected_variety_slots(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, var in self.variety_slot_vars.items()
            if var.get() and "disabled" not in self.variety_slot_checks[name].state()
        )

    def _variety_scope_changed(self) -> None:
        chosen = self.selected_variety_slots()
        text = self.variety_count_var.get().strip()
        count = int(text) if text.isdigit() else None
        if not chosen:
            self.variety_scope_var.set("Selected: none. Select at least one target slot.")
            return
        if count is None:
            self.variety_scope_var.set(f"Selected: {', '.join(chosen)}")
            return
        self.variety_scope_var.set(
            f"Selected: {', '.join(chosen)}\nRequested: {count * len(chosen)} value(s)"
        )

    def select_all_variety_slots(self) -> None:
        for name, var in self.variety_slot_vars.items():
            var.set("disabled" not in self.variety_slot_checks[name].state())
        self._variety_scope_changed()

    def clear_variety_slots(self) -> None:
        for var in self.variety_slot_vars.values():
            var.set(False)
        self._variety_scope_changed()

    def _variety(self) -> None:
        self._last_slots_action = MODE_VALUES
        if self._on_variety is not None:
            self._on_variety(
                self.variety_goal_var.get(),
                self.selected_variety_slots(),
                self.variety_count_var.get(),
                self.variety_focus_var.get(),
            )

    def _propose(self) -> None:
        self._last_slots_action = MODE_SLOT
        if self._on_propose is not None:
            self._on_propose(self.proposal_goal_var.get())

    def _phrase(self) -> None:
        self._last_slots_action = MODE_PHRASE
        if self._on_phrase is not None:
            self._on_phrase(self.variety_goal_var.get())

    def _ask_more(self) -> None:
        action = self._last_slots_action
        if action == MODE_VALUES:
            self._variety()
        elif action == MODE_SLOT:
            self._propose()
        elif action == MODE_PHRASE:
            self._phrase()

    def _bridge(self) -> None:
        """No fitting existing slot: switch to new-slot proposals and reuse the goal text."""

        if self._on_propose is None or not self.variety_goal_var.get().strip():
            return
        self.set_slots_mode(MODE_SLOT)
        self._propose()

    # -- cards and Apply --------------------------------------------------------------------------------------------------------

    def _apply_key(self, key: str) -> None:
        if self._running:
            return
        if self._on_apply is not None:
            self._on_apply((key,))
            return
        kind, _, number = key.partition(":")
        if kind == "variety" and self._on_add_value is not None and number.isdigit():
            self._on_add_value(int(number))
        elif kind == "slot" and self._on_add_proposal is not None and number.isdigit():
            self._on_add_proposal(int(number))

    def _apply_selected(self) -> None:
        keys = self.change_cards.selected_keys()
        if keys and not self._running and self._on_apply is not None:
            self._on_apply(keys)

    def _apply_all(self) -> None:
        keys = self.change_cards.offered_keys()
        if keys and not self._running and self._on_apply is not None:
            self._on_apply(keys)

    def _sync_apply(self) -> None:
        running = getattr(self, "_running", False)
        selected = len(self.change_cards.selected_keys())
        offered = len(self.change_cards.offered_keys())
        self.apply_selected_button.configure(text=f"{APPLY_SELECTED_TEXT} ({selected})")
        self.apply_selected_button.state(
            ["disabled"] if running or not selected or self._on_apply is None else ["!disabled"]
        )
        self.apply_all_button.state(
            ["disabled"] if running or not offered or self._on_apply is None else ["!disabled"]
        )
        has_cards = bool(self.change_cards.cards)
        self.more_button.state(
            ["disabled"]
            if running or not self._last_slots_action or not has_cards
            else ["!disabled"]
        )
        for key, button in self.change_cards.apply_buttons.items():
            button.state(["disabled"] if running else ["!disabled"])
            _ = key

    def _show_cards(self, cards: Sequence[ProposedChange], *, bridge: bool) -> None:
        self.change_cards.set_cards(cards)
        if bridge and self._on_propose is not None:
            self.bridge_button.pack(side="left", padx=6)
        else:
            self.bridge_button.pack_forget()
        self._sync_apply()

    def _clear_cards(self) -> None:
        self.change_cards.clear()
        self.bridge_button.pack_forget()
        self._sync_apply()

    # -- undo -------------------------------------------------------------------------------------------------------------------

    def _undo(self) -> None:
        if self._on_undo is not None:
            self._on_undo()

    def set_undo(self, label: str, count: int) -> None:
        """The Undo control reflects the apply journal: enabled with the label of the change it would take back."""

        self.undo_button.configure(text=f"{UNDO_TEXT} ({label})" if label else UNDO_TEXT)
        self.undo_button.state(
            ["!disabled"] if label and self._on_undo is not None else ["disabled"]
        )
        self.applied_var.set(f"Applied this session: {count}" if count else "")

    # -- Check tab --------------------------------------------------------------------------------------------------------------

    def _check(self) -> None:
        if self._on_check is not None:
            self._on_check()

    def show_checks(self, cards: Sequence[ProposedChange], summary: str) -> None:
        self.check_summary_var.set(summary)
        self.check_cards.set_cards(cards)
        self._sync_check_apply()

    def _check_apply_key(self, key: str) -> None:
        if self._on_check_apply is not None and not self._running:
            self._on_check_apply((key,))

    def _check_apply_selected(self) -> None:
        keys = self.check_cards.selected_keys()
        if keys and self._on_check_apply is not None and not self._running:
            self._on_check_apply(keys)

    def _sync_check_apply(self) -> None:
        if self.check_apply_button is None:
            return
        selected = len(self.check_cards.selected_keys())
        self.check_apply_button.configure(text=f"{APPLY_SELECTED_TEXT} ({selected})")
        self.check_apply_button.state(
            ["disabled"] if not selected or getattr(self, "_running", False) else ["!disabled"]
        )

    # -- phrase to slot ---------------------------------------------------------------------------------------------------------

    def set_phrase_text(self, text: str) -> None:
        self.phrase_var.set(text)

    # -- show / running ---------------------------------------------------------------------------------------------------------

    def show_proposal(
        self, review: ProposalReview, cards: Sequence[ProposedChange] | None = None
    ) -> None:
        """Judged new-slot proposals as cards; the text below holds the full review."""

        self._clear_copy_buttons()
        self._clear_cards()
        self.status(review.status)
        self._set_requests(False)
        self._set_advise(False)
        self.cancel_button.state(["disabled"])
        self.accept_button.state(["disabled"])
        self._text(proposal_text(review))
        self.select_tab(TAB_SLOTS)
        self._show_cards(
            cards
            if cards is not None
            else (list(review.cards) or _fallback_cards("slot", review.rows, review.added)),
            bridge=False,
        )

    def show_phrase(
        self, review: PhraseReview, cards: Sequence[ProposedChange] | None = None
    ) -> None:
        """Judged phrase-to-slot proposals as cards; the text below holds the full review."""

        self._clear_copy_buttons()
        self._clear_cards()
        self.status(review.status)
        self._set_requests(False)
        self._set_advise(False)
        self.cancel_button.state(["disabled"])
        self.accept_button.state(["disabled"])
        self._text(phrase_text(review))
        self.select_tab(TAB_SLOTS)
        self._show_cards(
            cards
            if cards is not None
            else (list(review.cards) or _fallback_cards("phrase", review.rows, review.added)),
            bridge=False,
        )

    def running_proposal(self) -> None:
        self._begin_running("Suggest new slot: request running…")

    def show_variety(
        self, review: VarietyReview, cards: Sequence[ProposedChange] | None = None
    ) -> None:
        """Judged slot-variety proposals as cards; the text below holds the full review."""

        self._clear_copy_buttons()
        self._clear_cards()
        self.variety_coverage_var.set(review.coverage_line)
        self.status(review.status)
        self._set_requests(False)
        self._set_advise(False)
        self.cancel_button.state(["disabled"])
        self.accept_button.state(["disabled"])
        self._text(variety_text(review))
        self.select_tab(TAB_SLOTS)
        shown = (
            cards
            if cards is not None
            else (list(review.cards) or _fallback_cards("variety", review.rows, review.added))
        )
        self._show_cards(shown, bridge=not any(card.offered for card in shown))

    def running_variety(self) -> None:
        self._begin_running("Suggest variety: request running…")

    def running_phrase(self) -> None:
        self._begin_running("Suggest slot from phrase: request running…")

    def _begin_running(self, status: str, text: str = "") -> None:
        self._clear_copy_buttons()
        self._clear_cards()
        self.clear_runtime_detail()
        self.offer_retry(False)
        self.status(status)
        self._text(text)
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

    def offer_retry(self, offered: bool) -> None:
        if offered:
            self.retry_button.pack(side="left", padx=8)
        else:
            self.retry_button.pack_forget()

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
        self.select_tab(TAB_DETAILS)
        self.detail_label.pack(fill="x")
        self.detail_view.pack(fill="x", pady=(0, 4))
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
        self._clear_cards()
        self.status(review.status)
        self._set_requests(False)
        self._set_advise(False)
        self.cancel_button.state(["disabled"])
        self.accept_button.state(["disabled"])
        self._text(review_text(review))
        self.select_tab(TAB_PLAN)
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
        self._begin_running("Advise plan: request running…", planning_for)

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
        self._begin_running(f"{KIND_LABELS[kind]}: request running…")

    def show_review(self, model: SuggestionReview) -> None:
        self._clear_copy_buttons()
        self._clear_cards()
        self.status(f"{model.kind}: {model.status}")
        self._set_requests(False)
        self._set_advise(False)
        self.cancel_button.state(["disabled"])
        self.accept_button.state(["!disabled"] if model.can_accept else ["disabled"])
        self.select_tab(TAB_PROMPT)
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
        self._clear_cards()
        self.check_cards.clear()
        self.clear_runtime_detail()
        self.offer_retry(False)
        self.goal_var.set("")
        self.variety_goal_var.set("")
        self.variety_coverage_var.set("")
        self.phrase_var.set("")
        if self.variety_slot_vars:
            self.clear_variety_slots()
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


def _fallback_cards(
    prefix: str, rows: Sequence[object], added: frozenset[int]
) -> list[ProposedChange]:
    """Cards built from review rows alone, for a caller that does not supply richer ones."""

    cards: list[ProposedChange] = []
    for row in rows:
        index = int(getattr(row, "index", 0))
        title = (
            f"{row.slot}: {row.value}"  # type: ignore[attr-defined]
            if prefix == "variety"
            else f"{row.slot_name}: {', '.join(row.values)}"  # type: ignore[attr-defined]
        )
        reason = str(getattr(row, "reason", ""))
        cards.append(
            ProposedChange(
                f"{prefix}:{index}",
                "variety_value" if prefix == "variety" else "new_slot",
                title,
                reason=reason,
                detail=reason,
                applied=index in added,
            )
        )
    return cards

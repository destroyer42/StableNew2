"""Prompt-tab AI coordination: snapshot, queued completion, read-only review and explicit stale-safe editing."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, replace
from tkinter import ttk
from typing import Any
from uuid import uuid4

from src.ai_assist.contracts import (
    DEFAULT_VARIETY_PER_SLOT,
    MAX_VARIETY_NEW_VALUES,
    VARIETY_FOCUS_DIRECT,
    AssistOutcome,
    AssistRequest,
    OutcomeCode,
    SuggestionKind,
)
from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.ai_preview_dialog import AiPreviewDialog
from src.gui.ai_suggestion_dialog import AiSuggestionDialog
from src.gui.prompt_ai_plan_sources import PlanSnapshot
from src.gui.tooltip import attach_tooltip
from src.gui_v2.ai_plan_advice import (
    PlanJudgement,
    build_plan_request,
    judge_plan,
    outcome_plan_text,
    plan_review,
    planning_for_text,
    unavailable_plan_review,
)
from src.gui_v2.ai_slot_variety import (
    HIDDEN_TEXT,
    NO_SELECTION_TEXT,
    REASON_TEXT,
    SLOT_DISABLED_REASON,
    VARIETY_REFUSED_HINT,
    VarietyContext,
    VarietyReview,
    build_variety_request,
    check_variety_quantity,
    judge_variety,
    matrix_state,
    slots_line,
    unavailable_variety_review,
    variety_review,
)
from src.gui_v2.ai_suggestion_view import (
    KIND_LABELS,
    OUTCOME_TEXT,
    SuggestionReview,
    SuggestionSnapshot,
    checked_suggestion,
    outcome_review,
    provider_outcome_text,
    result_provider_label,
    runtime_detail_text,
)
from src.gui_v2.prompt_adaptation_preview import build_adaptation_preview
from src.prompting.prompt_adaptation import adapt_prompt_for_target


class ContextUnavailable(ValueError):
    """Contains only fixed operator-facing copy; never prompt content."""


class PromptAiSuggestions:
    def __init__(self, tab: Any, header: Any) -> None:
        self.tab = tab
        self.owner: Any = None
        self._targets: Callable[[], tuple[tuple[str, str], ...]] = lambda: ()
        # The Prompt editor has no source-qualified video workflow context. Never invent catalog eligibility here.
        self._workflows: Callable[[], tuple[tuple[str, str], ...]] = lambda: ()
        self.dialog: AiSuggestionDialog | None = None
        self.snapshot: SuggestionSnapshot | None = None
        self._plan_source: Callable[[], PlanSnapshot] | None = None
        self._plan: PlanSnapshot | None = None
        self._plan_request: AssistRequest | None = None
        # Slot variety (AI-212): the request, the matrix state it was built from (plus values added since) and the
        # validated suggestion. All in memory only; cleared on close, a new request and any stale context.
        self._variety: VarietyContext | None = None
        self._variety_request: AssistRequest | None = None
        self._variety_suggestion: Any = None
        self._variety_added: set[int] = set()
        self.outcome: AssistOutcome | None = None
        self._active_id: str | None = None
        self._closed = False
        self._accepted = False
        self._review_cancelled = False
        self._poll_id: str | None = None
        self.button = ttk.Button(header, text="Suggest…", command=self.open, state="disabled")
        header.add(self.button)
        self.preview_button = ttk.Button(
            header, text="AI Preview…", command=self.open_preview, state="disabled"
        )
        header.add(self.preview_button)
        self.preview_dialog: AiPreviewDialog | None = None
        attach_tooltip(
            self.preview_button,
            "Enable or revoke AI Assist Preview, which runs an unqualified local model for suggestions only.",
        )
        attach_tooltip(
            self.button,
            "Request an AI suggestion, then review and explicitly accept into the editing buffer.",
        )
        self.explanation = ttk.Label(
            tab.center_frame,
            text=OUTCOME_TEXT[OutcomeCode.NOT_INSTALLED],
            wraplength=640,
            justify="left",
        )
        self.explanation.pack(fill="x", pady=(0, 4))
        self._poll_id = tab.after(1000, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        if not self._closed:
            self.refresh()
            self._poll_id = self.tab.after(1000, self._poll)

    def _mode(self) -> str:
        return str(
            self.tab._read_content_visibility_mode()
            if self.tab.app_state is not None
            else self.tab._content_visibility_mode
        )

    def bind(
        self,
        owner: Any,
        *,
        targets: Callable[[], tuple[tuple[str, str], ...]],
        plan: Callable[[], PlanSnapshot] | None = None,
    ) -> None:
        self.owner, self._targets, self._plan_source = owner, targets, plan
        self.refresh()

    def _context(self, kind: SuggestionKind, request_id: str) -> SuggestionSnapshot:
        tab = self.tab
        if self._closed or self.owner is None or self.owner.closed:
            raise ContextUnavailable("AI Assist is unavailable during shutdown.")
        pack = tab.workspace_state.current_pack
        slot = tab.workspace_state.get_current_slot()
        if pack is None or slot is None:
            raise ContextUnavailable("Select a PromptPack slot first.")
        resolver = ContentVisibilityResolver(self._mode())
        subject = tab._current_slot_visibility_subject()
        if not resolver.is_visible(subject):
            raise ContextUnavailable(
                "This authored content is hidden by the current visibility mode."
            )
        if not slot.text.strip():
            raise ContextUnavailable("Enter an authored positive prompt first.")
        # Snapshot the actual authored fields, never rendered templates or redacted widgets.
        if (tab.editor.get("1.0", "end-1c"), tab.negative_editor.get("1.0", "end-1c")) != (
            slot.text,
            slot.negative,
        ):
            raise ContextUnavailable(
                "The editor has pending changes. Finish editing, then request again."
            )
        projection, target = tab._model_projection, tab._prompt_target
        if projection is None or target is None or not target.adaptation_available:
            raise ContextUnavailable("Select a target with verified prompt compatibility first.")
        if not resolver.is_visible({"name": target.label}):
            raise ContextUnavailable(
                "The selected target is hidden by the current visibility mode."
            )
        if kind is SuggestionKind.PROMPT_REWRITE and (slot.template_id or slot.template_variables):
            raise ContextUnavailable(
                "Rewrite is unavailable for structured templates; their authored fields cannot be replaced safely."
            )
        targets = tuple(self._targets())
        workflows = tuple(self._workflows())
        if kind is SuggestionKind.TARGET_FIT_ADVICE and not targets:
            raise ContextUnavailable(
                "No policy-valid targets are available from the current model picker."
            )
        if kind is SuggestionKind.WORKFLOW_CHOICE and not workflows:
            raise ContextUnavailable(
                "Workflow Choice needs an eligibility-checked workflow/source context; none is available in this editor."
            )
        # Include the whole pack (matrix, template, assets, native document), slot identity, current policy/projection,
        # closed lists, visibility and deterministic adapter evidence. Hash only; never log or persist the material.
        material = (
            id(pack),
            id(slot),
            tab.workspace_state.get_current_slot_index(),
            asdict(pack),
            asdict(projection),
            asdict(target),
            asdict(tab._adaptation_input(tab._snapshot_prompt_state())),
            getattr(tab.app_state, "global_negative_prompt", ""),
            self._mode(),
            targets,
            workflows,
        )
        fingerprint = hashlib.sha256(repr(material).encode("utf-8")).hexdigest()
        request = AssistRequest(
            request_id,
            kind,
            slot.text,
            slot.negative,
            projection.policy.policy_id,
            content_class="sensitive"
            if resolver.classify_item(subject).rating == "nsfw"
            else "standard",
            allowed_targets=tuple(key for key, _label in targets),
            allowed_workflows=tuple(key for key, _label in workflows),
        )
        return SuggestionSnapshot(request, fingerprint, targets, workflows)

    def _problem(self, kind: SuggestionKind) -> str:
        try:
            self._context(kind, "eligibility")
            return ""
        except ContextUnavailable as exc:
            return str(exc)
        except ValueError:
            return "The authored input or closed choices do not meet the request limits."
        except Exception:  # noqa: BLE001 - private context must not enter diagnostics
            return "The authored context could not be read safely."

    def refresh(self) -> None:
        if self._closed:
            return
        code, explanation = (
            self.owner.availability()
            if self.owner is not None
            else (OutcomeCode.NOT_INSTALLED, OUTCOME_TEXT[OutcomeCode.NOT_INSTALLED])
        )
        if code is None:
            problem = self._problem(SuggestionKind.TARGET_FIT_ADVICE)
            rewrite_problem = self._problem(SuggestionKind.PROMPT_REWRITE)
            if problem and rewrite_problem:
                explanation = rewrite_problem
                code = OutcomeCode.INVALID_REQUEST
        label = self._trust_label()
        if label and label not in explanation:
            explanation = f"{label}. {explanation}"
        self.explanation.configure(text=explanation)
        self.button.configure(text="Suggest… (Preview)" if "Preview" in label else "Suggest…")
        if self.preview_dialog is not None and self.preview_dialog.winfo_exists():
            self.preview_dialog.refresh_remote(request_pending=self._active_id is not None)
        self.preview_button.state(["!disabled"] if self.owner is not None else ["disabled"])
        self.button.state(
            ["!disabled"] if code is None and self._active_id is None else ["disabled"]
        )

    def _trust_label(self) -> str:
        try:
            return str(self.owner.trust_label()) if self.owner is not None else ""
        except Exception:  # noqa: BLE001 - a label failure must never enable or block anything
            return ""

    def open_preview(self) -> AiPreviewDialog | None:
        if self._closed or self.owner is None or self.owner.closed:
            return None
        if self.preview_dialog is not None and self.preview_dialog.winfo_exists():
            self.preview_dialog.lift()
            return self.preview_dialog
        self.preview_dialog = AiPreviewDialog(self.tab, owner=self.owner, on_change=self.refresh)
        return self.preview_dialog

    def open(self) -> AiSuggestionDialog | None:
        self.refresh()
        if self.button.instate(["disabled"]):
            return None
        if self.dialog is not None:
            self.dialog.lift()
            return self.dialog
        self.dialog = AiSuggestionDialog(
            self.tab,
            on_request=self.request,
            on_accept=self.accept,
            on_cancel=self.cancel,
            on_close=self.close,
            explanations={kind: self._problem(kind) for kind in KIND_LABELS},
            trust_label=self._trust_label(),
            on_advise=self.advise if self._plan_source is not None else None,
            advise_problem=self._advise_problem(),
            on_variety=self.suggest_variety,
            on_add_value=self.add_variety_value,
            variety_problem=self._variety_problem(),
            variety_slots=self._variety_slots_text(),
            variety_slot_options=self._variety_slot_options(),
        )
        return self.dialog

    def request(self, kind: SuggestionKind) -> None:
        if self.dialog is None or self._active_id is not None:
            return
        code, explanation = self.owner.availability()
        if code is not None:
            self.dialog.show_review(SuggestionReview(explanation, KIND_LABELS[kind]))
            return
        try:
            snapshot = self._context(kind, uuid4().hex)
        except ContextUnavailable as exc:
            self.dialog.show_review(SuggestionReview(str(exc), KIND_LABELS[kind]))
            return
        except Exception:  # noqa: BLE001 - no raw context in UI errors
            self.dialog.show_review(
                SuggestionReview(
                    "The authored context could not be read safely.", KIND_LABELS[kind]
                )
            )
            return
        self.snapshot, self.outcome, self._accepted = snapshot, None, False
        self._drop_variety()
        self._review_cancelled = False
        self._active_id = snapshot.request.request_id
        self.dialog.running(kind)
        self.refresh()
        result = self.owner.submit(snapshot.request, self._completed)
        if not result.accepted:
            self._completed(
                result.outcome
                or AssistOutcome(OutcomeCode.UNAVAILABLE, snapshot.request.request_id)
            )

    # -- advisory planning (AI-210): advice only, read-only, no path to Intent, a form, the compiler or the queue ----------

    def _advise_problem(self) -> str:
        if self._plan_source is None:
            return "Planning advice is unavailable."
        try:
            snapshot = self._plan_source()
        except Exception:  # noqa: BLE001 - fixed copy only
            return "The model and workflow lists could not be read."
        if not snapshot.stages:
            return "No policy-valid models or approved workflows are available to plan with."
        return ""

    def advise(self, goal: str) -> None:
        dialog = self.dialog
        if dialog is None or self._active_id is not None or self._plan_source is None:
            return
        code, explanation = self.owner.availability()
        if code is not None:
            dialog.show_plan(unavailable_plan_review(explanation, trust_label=self._trust_label()))
            return
        text = goal.strip()
        if not text:
            dialog.show_plan(unavailable_plan_review("Type a goal in your own words first."))
            return
        try:
            plan = self._plan_source()
            request = build_plan_request(
                uuid4().hex,
                text,
                targets=plan.targets,
                workflows=plan.workflows,
                stages=plan.stages,
                target_policy_id=plan.target_policy_id,
                current_target=plan.current_target,
                current_target_label=plan.current_target_label,
                current_target_stages=plan.current_target_stages,
            )
        except ValueError:
            dialog.show_plan(
                unavailable_plan_review(
                    "The goal or the model and workflow lists do not meet the request limits."
                )
            )
            return
        except Exception:  # noqa: BLE001 - no raw context in UI errors
            dialog.show_plan(
                unavailable_plan_review("The planning context could not be read safely.")
            )
            return
        self._plan, self._plan_request, self.snapshot, self.outcome = plan, request, None, None
        self._drop_variety()
        self._review_cancelled = False
        self._active_id = request.request_id
        dialog.running_plan(planning_for_text(request))
        self.refresh()

        def judge(outcome: AssistOutcome) -> PlanJudgement | None:
            # Worker thread: the model's text is never the verdict; every step is judged from the facts captured above.
            suggestion = checked_suggestion(outcome, request)
            return None if suggestion is None else judge_plan(suggestion, plan.facts)

        result = self.owner.submit_plan(request, judge, self._plan_completed)
        if not result.accepted:
            self._plan_completed(
                result.outcome or AssistOutcome(OutcomeCode.UNAVAILABLE, request.request_id),
                None,
            )

    @staticmethod
    def _plan_outcome_text(outcome: AssistOutcome) -> str:
        if outcome.details.get("provider") == "remote" or outcome.details.get("fallback") is True:
            return provider_outcome_text(outcome)
        return outcome_plan_text(outcome, OUTCOME_TEXT)

    def _plan_completed(self, outcome: AssistOutcome, judgement: PlanJudgement | None) -> None:
        # Queued GUI delivery (or a synchronous admission refusal). Same lifetime and identity checks as ``_completed``.
        plan, request, dialog = self._plan, self._plan_request, self.dialog
        if (
            self._closed
            or self.owner.closed
            or plan is None
            or request is None
            or dialog is None
            or self._active_id != outcome.request_id
            or request.request_id != outcome.request_id
        ):
            return
        self._active_id = None
        trust = result_provider_label(outcome) or self._trust_label()
        # What was sent with the request, shown above every result (AI-211).
        sent = planning_for_text(request)
        if trust:
            dialog.set_trust_label(trust)
        if self._review_cancelled:
            dialog.show_plan(
                unavailable_plan_review(
                    "Request cancelled. Nothing was planned.", trust_label=trust, planning_for=sent
                )
            )
            self.refresh()
            return
        if outcome.code is not OutcomeCode.SUGGESTION:
            dialog.show_plan(
                unavailable_plan_review(
                    self._plan_outcome_text(outcome), trust_label=trust, planning_for=sent
                )
            )
            dialog.set_runtime_detail(runtime_detail_text(outcome.runtime_detail))
            self.refresh()
            return
        suggestion = checked_suggestion(outcome, request)
        if suggestion is None:
            review = unavailable_plan_review(
                OUTCOME_TEXT[OutcomeCode.MALFORMED], trust_label=trust, planning_for=sent
            )
        elif judgement is None:
            review = unavailable_plan_review(
                "The plan could not be judged, so no steps are shown.",
                trust_label=trust,
                planning_for=sent,
            )
        elif not ContentVisibilityResolver(self._mode()).is_visible(
            {"positive_prompt": " ".join(step.rationale for step in suggestion.steps)}
        ):
            review = unavailable_plan_review(
                "The advice is hidden by the current visibility mode.",
                trust_label=trust,
                planning_for=sent,
            )
        else:
            review = plan_review(
                judgement,
                targets=plan.targets,
                workflows=plan.workflows,
                trust_label=trust,
                planning_for=sent,
            )
        dialog.show_plan(review)
        dialog.set_runtime_detail(runtime_detail_text(outcome.runtime_detail))
        self.refresh()

    # -- slot variety (AI-212): proposals for existing matrix slots, each added only by an explicit per-value press ------
    # The only mutation is ``MatrixTabPanel.append_slot_value``, the Matrix editor's own edit path. Nothing here saves,
    # previews, compiles or queues, creates a slot, or touches an existing value or the prompt sentence.

    def _capture_matrix(self) -> VarietyContext:
        tab = self.tab
        if self._closed or self.owner is None or self.owner.closed:
            raise ContextUnavailable("AI Assist is unavailable during shutdown.")
        pack = tab.workspace_state.current_pack
        if pack is None:
            raise ContextUnavailable("Select a PromptPack first.")
        matrix = tab.workspace_state.get_matrix_config()
        return VarietyContext(id(pack), id(matrix), matrix_state(matrix.slots), self._mode())

    def _current_variety(self) -> VarietyContext | None:
        try:
            return self._capture_matrix()
        except Exception:  # noqa: BLE001 - an unreadable source invalidates acceptance
            return None

    def _variety_context(self) -> VarietyContext:
        context = self._capture_matrix()
        if not context.slots:
            raise ContextUnavailable(
                "This pack has no matrix slots. Add slots in the Matrix tab first."
            )
        if not any(slot.editable for slot in context.slots):
            raise ContextUnavailable(
                "No matrix slot can take a new value: each needs a unique name and text values without commas."
            )
        return context

    def _variety_problem(self) -> str:
        try:
            self._variety_context()
            return ""
        except ContextUnavailable as exc:
            return str(exc)
        except Exception:  # noqa: BLE001 - fixed copy only
            return "The matrix slots could not be read safely."

    def _variety_slots_text(self) -> str:
        """The read-only line naming the slots a variety request can use; fixed copy when the matrix is unreadable."""

        try:
            return slots_line(self._capture_matrix().slots, is_visible=self._variety_visible())
        except Exception:  # noqa: BLE001 - fixed copy only, no raw context
            return ""

    def _variety_slot_options(self) -> tuple[tuple[str, bool, str], ...]:
        """``(slot name, selectable, label)`` for every matrix slot. A slot that cannot take a value, or whose name the
        current visibility mode hides, is listed disabled with its reason; a hidden name is never shown."""

        try:
            slots = self._capture_matrix().slots
            visible = self._variety_visible()
        except Exception:  # noqa: BLE001 - fixed copy only, no raw context
            return ()
        options: list[tuple[str, bool, str]] = []
        for slot in slots:
            if not slot.editable:
                options.append((slot.name, False, f"{slot.name} ({SLOT_DISABLED_REASON})"))
            elif not visible(slot.name):
                # Keyed by a placeholder: the real name stays out of the widget.
                options.append((f"\x00hidden{len(options)}", False, f"{HIDDEN_TEXT}"))
            else:
                options.append((slot.name, True, slot.name))
        return tuple(options)

    def _variety_visible(self) -> Any:
        resolver = ContentVisibilityResolver(self._mode())
        return lambda text: resolver.is_visible({"positive_prompt": text})

    def _drop_variety(self) -> None:
        self._variety = self._variety_request = self._variety_suggestion = None
        self._variety_added = set()

    def suggest_variety(
        self,
        goal: str,
        selected: tuple[str, ...] = (),
        count: str = str(DEFAULT_VARIETY_PER_SLOT),
        focus: str = VARIETY_FOCUS_DIRECT,
    ) -> None:
        dialog = self.dialog
        if dialog is None or self._active_id is not None or self.owner is None:
            return
        code, explanation = self.owner.availability()
        if code is not None:
            dialog.show_variety(
                unavailable_variety_review(explanation, trust_label=self._trust_label())
            )
            return
        text = goal.strip()
        if not text:
            dialog.show_variety(unavailable_variety_review("Type a goal in your own words first."))
            return
        per_slot_text = str(count).strip()
        try:
            if not selected:
                raise ContextUnavailable(NO_SELECTION_TEXT)
            if not (per_slot_text.isascii() and per_slot_text.isdigit()):
                raise ContextUnavailable(
                    f"Suggestions per slot must be a whole number from 1 to {MAX_VARIETY_NEW_VALUES}."
                )
            check_variety_quantity(int(per_slot_text), len(selected))
        except (ContextUnavailable, ValueError) as exc:
            dialog.show_variety(unavailable_variety_review(str(exc)))
            return
        try:
            context = self._variety_context()
            resolver = ContentVisibilityResolver(self._mode())
            # Authorization covers the whole workspace's editable slots, not only the selection (AI-214).
            offered = [slot for slot in context.slots if slot.editable]
            subject = {
                "name": self.tab.workspace_state.get_current_pack_name(),
                "positive_prompt": "\n".join(
                    [text, *(f"{s.name}: {', '.join(map(str, s.values))}" for s in offered)]
                ),
            }
            if not resolver.is_visible(subject):
                raise ContextUnavailable(
                    "This authored content is hidden by the current visibility mode."
                )
            request = build_variety_request(
                uuid4().hex,
                text,
                context.slots,
                content_class="sensitive"
                if resolver.classify_item(subject).rating == "nsfw"
                else "standard",
                selected=selected,
                per_slot=int(per_slot_text),
                focus=focus,
            )
        except ContextUnavailable as exc:
            dialog.show_variety(unavailable_variety_review(str(exc)))
            return
        except ValueError as exc:
            # Selection and quantity messages are fixed copy from the builder; anything else is the generic limit text.
            known = (
                NO_SELECTION_TEXT,
                "A selected slot",
                "A slot was",
                "Select at most",
                "Unsupported",
            )
            dialog.show_variety(
                unavailable_variety_review(
                    str(exc)
                    if str(exc).startswith(known)
                    else "The goal or the matrix slots do not meet the request limits."
                )
            )
            return
        except Exception:  # noqa: BLE001 - no raw context in UI errors
            dialog.show_variety(
                unavailable_variety_review("The matrix slots could not be read safely.")
            )
            return
        self._drop_variety()
        self._variety, self._variety_request = context, request
        self.snapshot = self.outcome = None
        self._review_cancelled = False
        self._active_id = request.request_id
        dialog.running_variety()
        self.refresh()
        result = self.owner.submit(request, self._variety_completed)
        if not result.accepted:
            self._variety_completed(
                result.outcome or AssistOutcome(OutcomeCode.UNAVAILABLE, request.request_id)
            )

    def _variety_review(self, context: VarietyContext, trust: str) -> VarietyReview:
        visible = self._variety_visible()
        rows = judge_variety(self._variety_suggestion, context.slots, is_visible=visible)
        return variety_review(
            rows,
            self._variety_suggestion,
            is_visible=visible,
            trust_label=trust,
            added=frozenset(self._variety_added),
            excluded_count=context.excluded_count,
            request=self._variety_request,
        )

    def _variety_trust(self) -> str:
        return self.dialog.trust_label if self.dialog is not None else self._trust_label()

    def _variety_completed(self, outcome: AssistOutcome) -> None:
        # Queued GUI delivery (or a synchronous admission refusal). Same lifetime and identity checks as ``_completed``.
        context, request, dialog = self._variety, self._variety_request, self.dialog
        if (
            self._closed
            or self.owner is None
            or self.owner.closed
            or context is None
            or request is None
            or dialog is None
            or self._active_id != outcome.request_id
            or request.request_id != outcome.request_id
        ):
            return
        self._active_id = None
        trust = result_provider_label(outcome) or self._trust_label()
        if trust:
            dialog.set_trust_label(trust)
        if self._review_cancelled:
            self._drop_variety()
            dialog.show_variety(
                unavailable_variety_review(
                    "Request cancelled. Nothing was added.", trust_label=trust
                )
            )
            self.refresh()
            return
        suggestion = checked_suggestion(outcome, request) if outcome.ok else None
        if suggestion is None:
            self._drop_variety()
            code = outcome.code if not outcome.ok else OutcomeCode.MALFORMED
            text = provider_outcome_text(outcome) if code is outcome.code else OUTCOME_TEXT[code]
            if code is OutcomeCode.REFUSED_BY_MODEL:
                text += VARIETY_REFUSED_HINT
            dialog.show_variety(unavailable_variety_review(text, trust_label=trust))
            dialog.set_runtime_detail(runtime_detail_text(outcome.runtime_detail))
            self.refresh()
            return
        if self._current_variety() != context:
            # The pack or its slots changed while the model ran: never offer values judged against another state.
            self._drop_variety()
            dialog.clear_sensitive()
            self.refresh()
            return
        self._variety_suggestion = suggestion
        dialog.show_variety(self._variety_review(context, trust))
        dialog.set_runtime_detail(runtime_detail_text(outcome.runtime_detail))
        self.refresh()

    def add_variety_value(self, row_index: int) -> None:
        """Add one offered value to its slot through the Matrix editor's own edit path, after a full stale check."""

        context, suggestion, dialog = self._variety, self._variety_suggestion, self.dialog
        if (
            context is None
            or suggestion is None
            or dialog is None
            or self._active_id is not None
            or row_index in self._variety_added
        ):
            return
        current = self._current_variety()
        if current is None or current != context:
            self._drop_variety()
            dialog.clear_sensitive()
            dialog.status(
                "The pack or its matrix slots changed since the request. Nothing was added; request again."
            )
            return
        rows = judge_variety(suggestion, current.slots, is_visible=self._variety_visible())
        row = rows[row_index] if 0 <= row_index < len(rows) else None
        trust = self._variety_trust()
        if row is None or not row.offered:
            dialog.show_variety(self._variety_review(current, trust))
            if row is not None:
                dialog.status(f"That value cannot be added. {REASON_TEXT[row.reason]}")
            return
        index = next(i for i, slot in enumerate(current.slots) if slot.name == row.slot)
        expected = current.with_value_added(index, row.value)
        if not self.tab.matrix_tab_panel.append_slot_value(index, row.value):
            dialog.status(
                "The Matrix tab has an unfinished edit in that slot. Finish it, then add the value again."
            )
            return
        after = self._current_variety()
        if after is None or after != expected:
            # Fail closed: the edit did not produce exactly the one appended value. Offer nothing further.
            self._drop_variety()
            dialog.clear_sensitive()
            dialog.status(
                "The matrix did not change as expected. Check the Matrix tab, then request again."
            )
            return
        self._variety = after
        self._variety_added.add(row_index)
        dialog.show_variety(self._variety_review(after, trust))
        dialog.status(
            f"Added to slot {row.slot}. The pack is modified and unsaved; save it through the ordinary workflow."
        )

    def _current(self, snapshot: SuggestionSnapshot) -> bool:
        try:
            return self._context(snapshot.request.kind, snapshot.request.request_id) == snapshot
        except Exception:  # noqa: BLE001 - source read failure invalidates acceptance
            return False

    def _completed(self, outcome: AssistOutcome) -> None:
        # Called only by the application's queued GUI delivery, or synchronously for an immediate admission refusal.
        snapshot, dialog = self.snapshot, self.dialog
        if (
            self._closed
            or self.owner.closed
            or snapshot is None
            or dialog is None
            or self._active_id != outcome.request_id
            or snapshot.request.request_id != outcome.request_id
        ):
            return
        self._active_id = None
        if self._review_cancelled:
            self.outcome = None
            dialog.show_review(
                SuggestionReview(
                    "Request cancelled for review. Authored work is unchanged.",
                    KIND_LABELS[snapshot.request.kind],
                )
            )
            self.refresh()
            return
        if not self._current(snapshot):
            self.outcome = None
            dialog.clear_sensitive()
            self.refresh()
            return
        self.outcome = outcome
        dialog.set_trust_label(result_provider_label(outcome) or self._trust_label())
        review = outcome_review(outcome, snapshot.request.kind)
        if outcome.code is OutcomeCode.SUGGESTION:
            suggestion = checked_suggestion(outcome, snapshot.request)
            if suggestion is None:
                self.outcome = None
                review = SuggestionReview(OUTCOME_TEXT[OutcomeCode.MALFORMED], review.kind)
            else:
                try:
                    review = self._review(snapshot, suggestion)
                except Exception:  # noqa: BLE001 - compatibility failures never expose authored material
                    self.outcome = None
                    review = SuggestionReview(OUTCOME_TEXT[OutcomeCode.UNAVAILABLE], review.kind)
        dialog.show_review(review)
        dialog.set_runtime_detail(runtime_detail_text(outcome.runtime_detail))
        self.refresh()

    def _review(self, snapshot: SuggestionSnapshot, suggestion: Any) -> SuggestionReview:
        kind = snapshot.request.kind
        if kind is not SuggestionKind.PROMPT_REWRITE:
            choices = dict(
                snapshot.targets if kind is SuggestionKind.TARGET_FIT_ADVICE else snapshot.workflows
            )
            choice = (
                suggestion.target
                if kind is SuggestionKind.TARGET_FIT_ADVICE
                else suggestion.workflow
            )
            if choice not in choices:
                return SuggestionReview(OUTCOME_TEXT[OutcomeCode.MALFORMED], KIND_LABELS[kind])
            # No validated Prompt-tab selector accepts workflow advice; acknowledging it must not mutate selectors.
            return SuggestionReview(
                "Advice only. Use the existing selector and its eligibility checks to change a choice.",
                KIND_LABELS[kind],
                original=self.tab._prompt_target.label,
                proposed=f"{choice}: {choices[choice]}",
                changes=suggestion.changes,
            )
        subject = {
            "positive_prompt": suggestion.positive_text,
            "negative_prompt": suggestion.negative_text,
        }
        if not ContentVisibilityResolver(self._mode()).is_visible(subject):
            return SuggestionReview(
                "The suggestion is hidden by the current visibility mode.", KIND_LABELS[kind]
            )
        state = self.tab._snapshot_prompt_state()
        source = replace(
            self.tab._adaptation_input(state),
            positive_text=suggestion.positive_text,
            negative_text=suggestion.negative_text,
        )
        plan = adapt_prompt_for_target(
            self.tab._model_projection.policy, source, lora_resolver=self.tab._target_resolver()
        )
        compatibility = build_adaptation_preview(
            plan, source, target_label=self.tab._prompt_target.label
        )
        return SuggestionReview(
            OUTCOME_TEXT[OutcomeCode.SUGGESTION],
            KIND_LABELS[kind],
            original=f"Positive:\n{snapshot.request.positive_text}\n\nNegative:\n{snapshot.request.negative_text}",
            proposed=f"Positive:\n{suggestion.positive_text}\n\nNegative:\n{suggestion.negative_text}",
            changes=suggestion.changes,
            compatibility=compatibility,
            can_accept=plan.adaptable,
        )

    def accept(self) -> None:
        snapshot, outcome, dialog = self.snapshot, self.outcome, self.dialog
        if (
            self._accepted
            or snapshot is None
            or outcome is None
            or dialog is None
            or self._active_id is not None
        ):
            return
        if not self._current(snapshot):
            self.outcome = None
            dialog.clear_sensitive()
            return
        suggestion = checked_suggestion(outcome, snapshot.request)
        if suggestion is None or snapshot.request.kind is not SuggestionKind.PROMPT_REWRITE:
            return
        # Recompute compatibility/visibility at the point of mutation; never apply a repaired or stale response.
        try:
            permitted = self._review(snapshot, suggestion).can_accept
        except Exception:  # noqa: BLE001 - fail closed before any authoring mutation
            permitted = False
        if not permitted:
            dialog.clear_sensitive()
            return
        self._accepted = True
        state = self.tab.workspace_state
        index = state.get_current_slot_index()
        state.set_slot_text(index, suggestion.positive_text)
        state.set_slot_negative(index, suggestion.negative_text)
        self.tab._mark_pack_modified()
        self.tab._refresh_editor()
        self.tab._refresh_template_preview()
        self.tab._refresh_metadata(scan_style=False)
        if self.tab.app_state is not None:
            self.tab.app_state.invalidate_preview()
        dialog.clear_sensitive()
        dialog.status(
            "Rewrite accepted into the editing buffer. Save and Preview through the ordinary workflow."
        )
        self.snapshot = self.outcome = None

    def cancel(self) -> None:
        if self._active_id is not None and self.owner is not None:
            self._review_cancelled = True
            self.owner.cancel(self._active_id)
            if self.dialog is not None:
                self.dialog.status_var.set("Cancelling AI request…")

    def visibility_changed(self) -> None:
        # Close and scrub synchronously even when the Prompt tab is unmapped; no hidden Tk text remains accessible.
        dialog = self.dialog
        if dialog is not None:
            dialog.close()
        self.refresh()

    def close(self) -> None:
        self.cancel()
        self.dialog = None
        self.snapshot = self.outcome = None
        self._plan = self._plan_request = None
        self._drop_variety()
        self._active_id = None

    def destroy(self) -> None:
        if self.preview_dialog is not None and self.preview_dialog.winfo_exists():
            self.preview_dialog.destroy()
        if self.dialog is not None:
            self.dialog.close()
        self._closed = True
        if self._poll_id is not None:
            self.tab.after_cancel(self._poll_id)
            self._poll_id = None
        self.snapshot = self.outcome = None
        self._plan = self._plan_request = None
        self._drop_variety()

"""Prompt-tab AI coordination: snapshot, queued completion, read-only review and explicit stale-safe editing."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, replace
from tkinter import ttk
from typing import Any
from uuid import uuid4

from src.ai_assist.contracts import AssistOutcome, AssistRequest, OutcomeCode, SuggestionKind
from src.ai_assist.preview import PREVIEW_LABEL
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
    unavailable_plan_review,
)
from src.gui_v2.ai_suggestion_view import (
    KIND_LABELS,
    OUTCOME_TEXT,
    SuggestionReview,
    SuggestionSnapshot,
    checked_suggestion,
    outcome_review,
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
            "Request a local AI suggestion, then review and explicitly accept into the editing buffer.",
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
        self.button.configure(text="Suggest… (Preview)" if label else "Suggest…")
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
        self._review_cancelled = False
        self._active_id = request.request_id
        dialog.running_plan()
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
        preview = outcome.details.get("trust_tier") == "preview"
        trust = PREVIEW_LABEL if preview else self._trust_label()
        if trust:
            dialog.set_trust_label(trust)
        if self._review_cancelled:
            dialog.show_plan(
                unavailable_plan_review(
                    "Request cancelled. Nothing was planned.", trust_label=trust
                )
            )
            self.refresh()
            return
        if outcome.code is not OutcomeCode.SUGGESTION:
            dialog.show_plan(
                unavailable_plan_review(outcome_plan_text(outcome, OUTCOME_TEXT), trust_label=trust)
            )
            self.refresh()
            return
        suggestion = checked_suggestion(outcome, request)
        if suggestion is None:
            review = unavailable_plan_review(OUTCOME_TEXT[OutcomeCode.MALFORMED], trust_label=trust)
        elif judgement is None:
            review = unavailable_plan_review(
                "The plan could not be judged, so no steps are shown.", trust_label=trust
            )
        elif not ContentVisibilityResolver(self._mode()).is_visible(
            {"positive_prompt": " ".join(step.rationale for step in suggestion.steps)}
        ):
            review = unavailable_plan_review(
                "The advice is hidden by the current visibility mode.", trust_label=trust
            )
        else:
            review = plan_review(
                judgement, targets=plan.targets, workflows=plan.workflows, trust_label=trust
            )
        dialog.show_plan(review)
        self.refresh()

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
        if outcome.details.get("trust_tier") == "preview":
            dialog.set_trust_label(PREVIEW_LABEL)
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

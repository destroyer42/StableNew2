"""Proposal draft/Preview adapter; never binds JobService or changes the visible Learning state."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any, cast

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState
from src.learning.evidence_autopilot import (
    RESOURCE_KEYS,
    ProposalPlan,
    ProposalPlanningContext,
    execution_baseline,
    selected_proposals,
    validate_current,
)
from src.learning.evidence_proposals import ExperimentProposal, proposal_payload, save_proposal
from src.learning.experiment_execution import ExperimentAdmissionService
from src.learning.experiment_store import LearningExperimentStore
from src.learning.preview_summary import build_preview_summary
from src.learning.resource_access import get_resource_choices
from src.pipeline.job_models_v2 import NormalizedJobRecord


def capture_resources(controller: Any) -> dict[str, list[str]]:
    """Capture display-to-runtime projection on the UI thread; no WebUI calls."""
    result = {}
    for key in RESOURCE_KEYS:
        choices, mapping = get_resource_choices(controller, key)
        result[key] = list(mapping.values()) if mapping else choices
    return result


def save_drafts(
    plan: ProposalPlan,
    proposal_ids: tuple[str, ...],
    context: ProposalPlanningContext,
    store: LearningExperimentStore,
    *,
    cancelled: Callable[[], bool] = lambda: False,
    prompt_context: tuple[str, str, dict[str, Any]] | None = None,
) -> tuple[str, ...]:
    validate_current(plan, context)
    proposals = selected_proposals(plan, proposal_ids)
    result = []
    for proposal in proposals:
        if cancelled():
            raise InterruptedError(
                "Draft saving cancelled; already-saved drafts remain in the Experiment Library."
            )
        document = copy.deepcopy(dict(proposal.document))
        document["baseline"] = execution_baseline(context)
        if prompt_context is not None:
            document.update(
                prompt=prompt_context[0],
                negative_prompt=prompt_context[1],
                prompt_source_context=copy.deepcopy(prompt_context[2]),
            )
        proposal = ExperimentProposal(document)
        result.append(save_proposal(proposal, store))
    return tuple(result)


def preview_selected(
    plan: ProposalPlan,
    proposal_ids: tuple[str, ...],
    context: ProposalPlanningContext,
    *,
    prompt: str,
    negative: str = "",
    prompt_metadata: Mapping[str, Any] | None = None,
    global_policy: Mapping[str, Any] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[Any, ...]:
    """Canonical frozen Learning states, compiled NJRs and existing summaries; no persistence/admission."""
    validate_current(plan, context)
    proposals = selected_proposals(plan, proposal_ids)
    if not prompt.strip() or len(prompt) > 16000 or len(negative) > 16000:
        raise ValueError("Choose one bounded qualification prompt context before Preview.")
    results = []
    for proposal in proposals:
        if cancelled():
            raise InterruptedError("Preview cancelled; no jobs or profiles created.")
        document = copy.deepcopy(dict(proposal.document))
        document["baseline"] = execution_baseline(context)
        document.update(prompt=prompt, negative_prompt=negative)
        state = LearningState.from_dict(proposal_payload(ExperimentProposal(document)))
        experiment = state.current_experiment
        if experiment is None:
            raise ValueError("Proposal has no Learning experiment")
        experiment.metadata.update(
            copy.deepcopy(dict(prompt_metadata or {"prompt_source": "custom"}))
        )
        facade = SimpleNamespace(
            app_state=SimpleNamespace(resources=copy.deepcopy(dict(context.resources))),
            get_current_global_prompt_policy=lambda: dict(global_policy)
            if global_policy is not None
            else None,
        )
        # No pipeline controller or execution controller: constructing Preview cannot steal
        # the live Learning callback binding, even while another experiment is running.
        controller = LearningController(state, app_controller=facade)
        if controller.execution_controller is not None:
            raise RuntimeError("Proposal Preview must not bind execution")
        # Existing optional resolver hooks are duck-typed by the Learning services.
        cast(Any, controller)._learning_policy_resolver = lambda _name: context.target.policy
        cast(Any, controller)._evidence_catalog_provider = lambda: context.catalog
        cast(Any, controller)._evidence_identity_resolver = lambda _name: context.target
        controller.build_plan(experiment)

        def build_record(
            variant: Any,
            bound: LearningController = controller,
            frozen: LearningExperiment = experiment,
        ) -> NormalizedJobRecord:
            return bound._build_variant_njr(variant, frozen)

        admission = ExperimentAdmissionService().compile_all(
            state.plan,
            build_record,
        )
        results.append(
            (
                state,
                admission.records,
                build_preview_summary(experiment, state.plan, show_model_names=True),
            )
        )
    return tuple(results)

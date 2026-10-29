"""Explicit create-only follow-up drafts through existing proposal and Learning authorities."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any

from src.gui.learning_state import LearningState
from src.learning.evidence_autopilot import (
    EvidenceProposalPlanner,
    ProposalPlanningContext,
    digest,
    execution_baseline,
)
from src.learning.evidence_proposals import ExperimentProposal, proposal_payload
from src.learning.experiment_execution import snapshot_digest, thaw_snapshot
from src.learning.qualification_review import project_qualification


@dataclass(frozen=True)
class FollowupDraft:
    state: LearningState
    parent_id: str
    parent_revision: str
    explanation: str


def prepare_followup(
    experiment: Any,
    plan: list[Any],
    ratings: dict[str, Any],
    context: ProposalPlanningContext,
    *,
    candidate: Any,
    prompt: str,
    negative: str,
    seed: int,
) -> FollowupDraft:
    """Worker-only preparation. No write, admission, publication or visible-state binding."""
    findings = project_qualification(experiment, plan, ratings)
    if findings.exclusions or findings.next_action == "Finish Rating":
        raise ValueError("Inspect execution evidence or finish rating before preparing a follow-up")
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    parent = snapshot["evidence_proposal"]
    identity = snapshot["model_identity"]
    current = context.target.identity
    if (
        not current.sha256
        or current.sha256 != identity.get("sha256")
        or current.family != identity.get("family")
    ):
        raise ValueError("Original model byte identity is unavailable or changed")
    values = list(snapshot["variant_values"])
    if candidate not in values[1:]:
        raise ValueError("Choose an original candidate against the frozen control")
    if not prompt.strip() or len(prompt) > 16000 or len(negative) > 16000:
        raise ValueError("Select a bounded explicit follow-up prompt context")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Choose an explicit follow-up seed from 0 to 4294967295")
    old_seeds = {s.seed for s in findings.samples if s.seed is not None}
    old_policy = snapshot.get("seed_policy") or {}
    same_prompt = prompt == snapshot.get("prompt_text") and negative == snapshot.get(
        "negative_prompt_text", ""
    )
    count = snapshot["images_per_value"]
    if same_prompt and (
        seed == old_policy.get("requested_base_seed")
        or old_seeds.intersection(range(seed, seed + count))
    ):
        raise ValueError("Select a different prompt context or a separate seed cohort explicitly")
    baseline = copy.deepcopy(snapshot["baseline_config"])
    baseline.setdefault("txt2img", {})["seed"] = seed
    followup_context = replace(context, baseline=baseline, samples=6)
    proposals = EvidenceProposalPlanner().plan(followup_context)
    eligible = next(
        (
            p
            for p in proposals.proposals
            if p.runnable
            and p.document["variable"] == parent["variable"]
            and p.document["values"] == [values[0], candidate]
        ),
        None,
    )
    if eligible is None:
        raise ValueError(
            "Current catalog/resources provide no eligible original comparison; explore Proposed Experiments"
        )
    document = copy.deepcopy(dict(eligible.document))
    document.update(
        baseline=execution_baseline(followup_context), prompt=prompt, negative_prompt=negative
    )
    document["parent_qualification"] = {
        "experiment_id": experiment.experiment_id,
        "snapshot_sha256": snapshot_digest(experiment.execution_snapshot_json),
        "proposal_id": parent["proposal_id"],
        "catalog_revision": parent.get("catalog_revision"),
        "control": values[0],
        "candidate": candidate,
        "model_identity": identity,
        "source_references": copy.deepcopy(parent.get("evidence_refs", parent.get("coverage", []))),
    }
    experiment_id = "qual820-" + digest(document)[:32]
    document["name"] = "Follow-up — " + document["name"]
    state = LearningState.from_dict(proposal_payload(ExperimentProposal(document)))
    if state.current_experiment is None:
        raise ValueError("Follow-up proposal has no experiment")
    state.current_experiment.experiment_id = experiment_id
    state.current_experiment.metadata["parent_qualification"] = copy.deepcopy(
        document["parent_qualification"]
    )
    explanation = (
        f"New 2 × 6 draft: control {values[0]} versus {candidate}; original checkpoint bytes, tested setting and non-tested configuration retained. "
        "Explicit prompt/seed context replaces the parent context. Build Preview and Run remain separate operator actions. This is further investigation, not confirmation or setting adoption."
    )
    state.current_experiment.metadata["qualification_followup_explanation"] = explanation
    state.current_experiment.description += "\n\n" + explanation
    return FollowupDraft(
        state,
        experiment.experiment_id,
        snapshot_digest(experiment.execution_snapshot_json),
        explanation,
    )


def save_followup(draft: FollowupDraft, store: Any) -> str:
    """Existing create-only Library persistence; repeat preparation never overwrites work."""
    experiment = draft.state.current_experiment
    if experiment is None or not experiment.experiment_id.startswith("qual820-"):
        raise ValueError("Follow-up draft identity unavailable")
    if store.load_session(experiment.experiment_id) is None:
        payload = draft.state.to_dict()
        payload.update(workflow_state="designing", learning_enabled=True, resume_schema_version=1)
        try:
            store.save_session(
                display_name=experiment.name,
                experiment_id=experiment.experiment_id,
                payload=payload,
                create_only=True,
            )
        except FileExistsError:
            pass
    return experiment.experiment_id

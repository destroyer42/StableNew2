"""Worker-only qualification follow-up validation through existing catalog/compiler seams."""

from __future__ import annotations

from typing import Any

from src.assets.registry import AssetRegistry
from src.generation_profiles.evidence_catalog import load_operator_catalog
from src.generation_profiles.identity import ModelIdentityResolver, RegistryShaLookup
from src.gui.controllers.model_evidence_proposals import compile_qualification_state
from src.image_backends.model_policy import RegistryFamilyLookup
from src.learning.evidence_autopilot import ProposalPlanningContext
from src.learning.experiment_execution import thaw_snapshot
from src.learning.model_capabilities import project_learning_capabilities
from src.learning.qualification_followup import FollowupDraft, prepare_followup


def prepare_validated_followup(
    experiment: Any,
    plan: list[Any],
    ratings: dict[str, Any],
    resources: dict[str, Any],
    *,
    candidate: Any,
    prompt: str,
    negative: str,
    seed: int,
) -> FollowupDraft:
    """No Tk or writes; current byte identity and whole-experiment compile before saving."""
    registry = AssetRegistry()
    resolver = ModelIdentityResolver(
        family_lookup=RegistryFamilyLookup(registry), sha_lookup=RegistryShaLookup(registry)
    )
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    target = resolver.resolve(snapshot["model_identity"]["display_name"])
    context = ProposalPlanningContext(
        target, load_operator_catalog(), snapshot["baseline_config"], resources
    )
    draft = prepare_followup(
        experiment,
        plan,
        ratings,
        context,
        candidate=candidate,
        prompt=prompt,
        negative=negative,
        seed=seed,
    )
    compile_qualification_state(draft.state, context, True)
    # Recheck after compilation; a changed catalog/model must not become an executable draft.
    fresh_registry = AssetRegistry()
    fresh = ModelIdentityResolver(
        family_lookup=RegistryFamilyLookup(fresh_registry),
        sha_lookup=RegistryShaLookup(fresh_registry),
    ).resolve(target.identity.display_name)
    if (
        fresh.identity != target.identity
        or load_operator_catalog().revision != context.catalog.revision
    ):
        raise ValueError("Model or catalog changed while preparing follow-up; prepare again")
    return draft


def revalidate_followup_sources(draft: FollowupDraft) -> None:
    """Last, bounded cache-only check immediately before create-only publication.

    AssetRegistry.cached_snapshot is the existing UI-safe observation seam; no
    scans, hashes, downloads or backend calls. Missing evidence refuses the save.
    """
    import json

    experiment = draft.state.current_experiment
    if experiment is None:
        raise ValueError("Follow-up experiment is unavailable")
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    proposal = snapshot["evidence_proposal"]
    registry = AssetRegistry()
    target = ModelIdentityResolver(
        family_lookup=RegistryFamilyLookup(registry), sha_lookup=RegistryShaLookup(registry)
    ).resolve(proposal["identity"]["display_name"])
    if (
        target.identity.to_dict() != snapshot["model_identity"]
        or load_operator_catalog().revision != proposal["catalog_revision"]
    ):
        raise ValueError("Model or catalog changed before saving; prepare again")
    policy = json.loads(
        project_learning_capabilities(
            target.policy, target.identity.display_name, "txt2img"
        ).context_json
    )
    if policy != proposal["planning_context"]["policy_context"]:
        raise ValueError("Model policy changed before saving; prepare again")

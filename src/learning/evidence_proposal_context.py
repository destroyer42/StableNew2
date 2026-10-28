"""Read-only revalidation of v2 qualification context before canonical Learning compilation."""

from __future__ import annotations

from typing import Any

from src.generation_profiles.evidence_catalog import load_operator_catalog
from src.generation_profiles.identity import ModelIdentityResolver
from src.learning.evidence_autopilot import (
    RESOURCE_KEYS,
    EvidenceProposalPlanner,
    ProposalPlanningContext,
)
from src.learning.evidence_proposals import CONTRACT_V2
from src.learning.experiment_execution import thaw_snapshot
from src.learning.resource_access import get_resource_choices


def validate_library_context(controller: Any, experiment: Any) -> None:
    metadata = experiment.metadata or {}
    outer = metadata.get("evidence_proposal") or {}
    snapshot = (
        thaw_snapshot(experiment.execution_snapshot_json)
        if experiment.execution_snapshot_json
        else {}
    )
    frozen = snapshot.get("evidence_proposal") or {}
    proposal = frozen or outer
    if frozen.get("contract") == CONTRACT_V2 and any(
        outer.get(key) != value
        for key, value in frozen.items()
        if key not in ("selected_context", "selected_context_revision", "selected_hypothesis")
    ):
        raise ValueError(
            "Qualification metadata changed after Preview; rebuild from a current proposal."
        )
    if proposal.get("contract") != CONTRACT_V2:
        return
    prompt = snapshot.get("prompt_text", experiment.prompt_text)
    baseline = snapshot.get("baseline_config", experiment.baseline_config)
    source = snapshot.get("prompt_source", metadata)
    if not str(prompt or "").strip():
        raise ValueError(
            "Choose a nonempty qualification prompt context and rebuild Preview before Run."
        )
    _refuse_adapters(
        prompt,
        snapshot.get("negative_prompt_text", source.get("selected_prompt_negative_text", "")),
        baseline,
        source,
    )
    catalog = getattr(controller, "_evidence_catalog_provider", load_operator_catalog)()
    name = proposal["identity"]["display_name"]
    resolver = getattr(controller, "_evidence_identity_resolver", ModelIdentityResolver().resolve)
    target = resolver(name)
    resources = {}
    for key in RESOURCE_KEYS:
        choices, mapping = get_resource_choices(controller, key)
        resources[key] = list(mapping.values()) if mapping else choices
    context = ProposalPlanningContext(
        target,
        catalog,
        baseline,
        resources,
        variant=(proposal.get("planning_context") or {}).get("variant", ""),
        samples=(proposal.get("planning_context") or {}).get("samples"),
    )
    current_plan = EvidenceProposalPlanner().plan(context)
    current = current_plan.document
    expected = proposal.get("planning_context")
    observed = {
        key: value
        for key, value in current.items()
        if key not in ("contract", "plan_id", "proposals")
    }
    if not expected or observed != expected:
        raise ValueError(
            "Qualification context is stale: replan for current model, catalog, resources and baseline."
        )
    canonical = next(
        (
            p.document
            for p in current_plan.proposals
            if p.proposal_id == proposal.get("proposal_id")
        ),
        None,
    )
    keys = (
        "variable",
        "values",
        "images_per_value",
        "expected_images",
        "seed_policy",
        "evidence_refs",
    )
    if (
        canonical is None
        or canonical["status"] != "draft"
        or any(canonical.get(key) != proposal.get(key) for key in keys)
    ):
        raise ValueError(
            "Qualification proposal changed or is no longer supported by its recorded evidence. Replan before Run."
        )


def _refuse_adapters(prompt: Any, negative: Any, baseline: Any, source: Any) -> None:
    """The catalog pilot never admits an adapter recipe through delayed prompt selection."""

    def contains(value: Any) -> bool:
        if isinstance(value, str):
            return any(token in value.casefold() for token in ("<lora:", "<lyco:"))
        if isinstance(value, dict):
            return any(
                bool(item)
                if key
                in (
                    "loras",
                    "lora_strengths",
                    "lora_override",
                    "selected_loras",
                    "selected_prompt_loras",
                    "policy_selected_loras",
                    "style_lora",
                )
                else contains(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(contains(item) for item in value)
        return False

    if any(contains(value) for value in (prompt, negative, baseline, source)):
        raise ValueError(
            "Adapter recipe needs exact compatibility validation in its existing controlled mode."
        )

"""Learning policy validation and compile delegation; never an execution authority."""

from __future__ import annotations

import copy
import json
from dataclasses import replace

from src.image_backends.forge_klein_lora import RegistryLoraResolver, extract_lora_tags
from src.image_backends.model_policy import (
    ControlMode,
    ControlPolicy,
    FeaturePolicy,
    ModelPolicy,
    RegistryFamilyLookup,
    Support,
    apply_model_compile_policy,
    policy_for_model_profile_reference,
    resolve_model_policy,
)
from src.image_backends.model_policy_lora import assess_lora_selection
from src.learning.model_capabilities import (
    compatible_context,
    policy_context,
    project_learning_capabilities,
    variable_name,
)
from src.learning.variable_metadata import get_variable_metadata


def resolve_policy(model: str, controller=None, config=None) -> ModelPolicy:
    resolver = getattr(controller, "_learning_policy_resolver", None)
    if callable(resolver):
        return resolver(model)
    persisted = policy_for_model_profile_reference((config or {}).get("backend_options"))
    return persisted or resolve_model_policy(model, family_lookup=RegistryFamilyLookup())


def policy_from_context(context: dict) -> ModelPolicy:
    contract = context["contract"]
    controls = {
        name: ControlPolicy(ControlMode(raw["mode"]), raw["value"], tuple(raw["allowed"]))
        for name, raw in contract["controls"].items()
    }
    features = {
        name: FeaturePolicy(
            Support(raw["support"]), raw["limit"], raw["compatibility_policy"], tuple(raw["stages"])
        )
        for name, raw in contract["features"].items()
    }
    stage = context["stage"]
    return ModelPolicy(
        context["policy_id"],
        context["family"],
        context["family"],
        context["evidence"],
        controls,
        features,
        allowed_backends=tuple(contract["allowed_backends"]),
        required_backend=contract["required_backend"],
        prompt_dialect=contract["prompt_dialect"],
        profile_ref=context["profile_ref"],
        stages=tuple(contract["stages"]),
        modes=tuple(contract["modes"]),
        stage_controls={stage: controls},
    )


def selected_model(config: dict, stage: str) -> str:
    local = config.get(stage) or {}
    base = config.get("txt2img") or {}
    return str(
        local.get("model")
        or local.get("model_name")
        or base.get("model")
        or base.get("model_name")
        or config.get("model")
        or ""
    )


def lora_resolver(controller=None):
    resolver = getattr(controller, "_learning_lora_resolver", None)
    return resolver if callable(resolver) else RegistryLoraResolver(cache_only=True)


def selected_loras(config, prompt="", metadata=None):
    tags, problems = extract_lora_tags(prompt)
    result = [(tag.name, tag.weight) for tag in tags]
    for entry in list((metadata or {}).get("selected_prompt_loras") or []) + list(
        (config.get("txt2img") or {}).get("lora_strengths") or []
    ):
        if isinstance(entry, dict) and entry.get("enabled", True) and entry.get("name"):
            pair = (str(entry["name"]), float(entry.get("weight", entry.get("strength", 1.0))))
            if pair[0] not in [name for name, _ in result]:
                result.append(pair)
    return tuple(result), problems


def live_capabilities(controller, stage: str, *, policy=None, model=None):
    baseline = controller._get_baseline_config()
    model = model if model is not None else selected_model(baseline, stage)
    policy = policy or resolve_policy(model, controller, baseline)
    workspace = getattr(controller, "prompt_workspace_state", None)
    prompt = workspace.get_current_prompt_text() if workspace is not None else ""
    selection, _ = selected_loras(baseline, prompt)
    pending = False
    provider = getattr(controller, "_learning_prompt_snapshot", None)
    if callable(provider):
        snapshot = provider()  # existing Prompt cache-only snapshot, never style resolution
        selection = snapshot.loras + ((snapshot.style_lora,) if snapshot.style_lora else ())
        pending = snapshot.style_lora_pending
    return project_learning_capabilities(
        policy,
        model,
        stage,
        selected_loras=selection,
        lora_resolver=lora_resolver(controller),
        style_lora_pending=pending,
    )


def validate_experiment(controller, experiment, baseline, values, *, frozen_context=None):
    stage = experiment.stage
    model = selected_model(baseline, stage)
    policy = (
        policy_from_context(frozen_context)
        if frozen_context
        else resolve_policy(model, controller, baseline)
    )
    if frozen_context:
        canonical = resolve_policy(model, controller, baseline)
        if canonical.qualified or policy.qualified:
            if policy.profile_ref:
                canonical = policy_for_model_profile_reference(
                    {"image": {"model_profile": dict(policy.profile_ref)}}
                )
            if canonical is None or policy_context(canonical, model, stage) != frozen_context:
                raise ValueError("Frozen model policy context differs from canonical profile")
    selection, problems = selected_loras(baseline, experiment.prompt_text, experiment.metadata)
    preserved = experiment.metadata.get("policy_selected_loras")
    provider = getattr(controller, "_learning_prompt_snapshot", None)
    if frozen_context is not None and preserved is not None:
        selection = tuple((str(name), float(weight)) for name, weight in preserved)
    elif frozen_context is None and callable(provider):
        prompt_snapshot = provider()
        if policy.qualified and prompt_snapshot.style_lora_pending:
            raise ValueError("LoRA Strength unavailable: style admission evidence pending")
        current = prompt_snapshot.loras + (
            (prompt_snapshot.style_lora,) if prompt_snapshot.style_lora else ()
        )
        selection = selection + tuple(
            pair for pair in current if pair[0] not in [name for name, _ in selection]
        )
        experiment.metadata["policy_selected_loras"] = list(selection)
    # A selected concrete experiment candidate may not already be a prompt token.
    candidates = list(selection)
    if variable_name(experiment.variable_under_test) == "lora_strength":
        for value in values:
            if not isinstance(value, dict) or not value.get("name"):
                raise ValueError("LoRA Strength unavailable: concrete candidate required")
            candidate = (str(value["name"]), float(value["weight"]))
            others = [
                (name, weight)
                for name, weight in selection
                if name.casefold() != candidate[0].casefold()
            ]
            assessment = assess_lora_selection(
                policy, others + [candidate], lora_resolver(controller)
            )
            if (
                assessment.blocked
                or (policy.feature("lora", stage).compatibility_policy and not assessment.exact)
                or (policy.qualified and problems)
            ):
                raise ValueError(
                    "LoRA Strength unavailable: " + (assessment.blocking or str(problems))
                )
            if candidate[0] not in [name for name, _ in candidates]:
                candidates.append(candidate)
    representative = candidates
    if variable_name(experiment.variable_under_test) == "lora_strength" and values:
        first = values[0]
        representative = [
            (name, weight)
            for name, weight in selection
            if name.casefold() != str(first["name"]).casefold()
        ]
        representative.append((str(first["name"]), float(first["weight"])))
    capabilities = project_learning_capabilities(
        policy, model, stage, selected_loras=representative, lora_resolver=lora_resolver(controller)
    )
    capabilities.require(experiment.variable_under_test)
    context = policy_context(policy, model, stage)
    if frozen_context and context != frozen_context:
        raise ValueError("Frozen model policy context does not match experiment")
    if variable_name(experiment.variable_under_test) == "model":
        for candidate in values:
            candidate_policy = resolve_policy(str(candidate), controller)
            if not compatible_context(
                context, policy_context(candidate_policy, str(candidate), stage)
            ):
                raise ValueError("Model candidate unavailable: incompatible policy envelope")
    return context


def frozen_definition(experiment):
    from src.learning.experiment_execution import thaw_snapshot

    snapshot = (
        thaw_snapshot(experiment.execution_snapshot_json)
        if experiment.execution_snapshot_json
        else {}
    )
    if not snapshot:
        return experiment
    return replace(
        experiment,
        stage=snapshot["stage"],
        variable_under_test=snapshot["variable_under_test"],
        values=list(snapshot["variant_values"]),
        images_per_value=snapshot["images_per_value"],
        prompt_text=snapshot["prompt_text"],
        input_image_path=snapshot.get("input_image_path", experiment.input_image_path),
        metadata=dict(snapshot.get("prompt_source") or {}),
    )


def compile_variant(config, experiment):
    """Validate before this call. Prove canonical normalization preserves the tested value."""
    meta = get_variable_metadata(experiment.variable_under_test)
    keys = meta.config_path.split(".")
    if keys[0] == "txt2img" and experiment.stage != "txt2img":
        keys[0] = experiment.stage

    def read():
        value = config
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        return copy.deepcopy(value)

    before = read()
    apply_model_compile_policy(config)
    if read() != before:
        raise ValueError("Learning variable overwritten by model compile normalization")
    if experiment.execution_snapshot_json:
        from src.learning.experiment_execution import thaw_snapshot

        context = (
            thaw_snapshot(experiment.execution_snapshot_json).get("model_policy_context") or {}
        )
        if context.get("profile_ref"):
            compiled = policy_for_model_profile_reference(config.get("backend_options"))
            if compiled is None or dict(compiled.profile_ref or {}) != context["profile_ref"]:
                raise ValueError(
                    "Compiled model profile differs from the frozen experiment profile"
                )


def evidence_context(metadata):
    return dict(
        (metadata.get("frozen_experiment") or {}).get("snapshot", {}).get("model_policy_context")
        or {}
    )


def negative_prompt_supported(controller, config, stage):
    policy = resolve_policy(selected_model(config, stage), controller, config)
    return policy.feature("negative_prompt", stage).support is not Support.UNSUPPORTED


def recommendation_query(controller):
    experiment = controller.learning_state.current_experiment
    config = controller._get_baseline_config()
    stage = "txt2img"
    if experiment is not None:
        from src.learning.experiment_execution import thaw_snapshot

        snapshot = (
            thaw_snapshot(experiment.execution_snapshot_json)
            if experiment.execution_snapshot_json
            else {}
        )
        config = dict(snapshot.get("baseline_config") or experiment.baseline_config or config)
        stage = str(snapshot.get("stage") or experiment.stage)
    model = selected_model(config, stage)
    section = config.get(stage) or config.get("txt2img") or {}
    policy = resolve_policy(model, controller, config)
    selection, _ = selected_loras(
        config,
        experiment.prompt_text if experiment else "",
        experiment.metadata if experiment else {},
    )
    return {
        "model": model,
        "width": section.get("width"),
        "height": section.get("height"),
        "target_capabilities": project_learning_capabilities(
            policy, model, stage, selected_loras=selection, lora_resolver=lora_resolver(controller)
        ),
    }


def recommendation_applicable(capabilities, parameter):
    return variable_name(parameter) in capabilities.parameters


def validate_recommendation_apply(controller, recommendations, cards, rec_list):
    """Preflight the entire patch before any Tk variable mutation, including stale provenance."""
    stage = str(getattr(recommendations, "stage", "txt2img") or "txt2img")
    card = getattr(cards, f"{stage}_card", None)
    base_card = getattr(cards, "txt2img_card", None)
    model_var = getattr(card, "model_var", None) or getattr(base_card, "model_var", None)
    model = model_var.get() if model_var is not None else None
    capabilities = live_capabilities(
        controller, stage, model=model if isinstance(model, str) else None
    )
    target = json.loads(capabilities.context_json)
    supplied = getattr(recommendations, "model_policy_context", None)
    if target["profile_ref"] and (
        not isinstance(supplied, dict) or not compatible_context(target, supplied)
    ):
        return False
    for rec in rec_list:
        parameter = (
            rec.parameter_name if hasattr(rec, "parameter_name") else rec.get("parameter", "")
        )
        value = rec.recommended_value if hasattr(rec, "recommended_value") else rec.get("value")
        if not recommendation_applicable(capabilities, parameter):
            return False
        if variable_name(parameter) == "model":
            candidate = resolve_policy(str(value), controller)
            if not compatible_context(target, policy_context(candidate, str(value), stage)):
                return False
    return True

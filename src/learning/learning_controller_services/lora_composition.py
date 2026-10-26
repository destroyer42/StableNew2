"""LoRA Composition coordination over existing snapshot, ordinary NJR and Learning state owners."""

from __future__ import annotations

import copy
import uuid
from dataclasses import replace
from typing import Any

from src.learning import baseline_authoring as authoring
from src.learning import lora_composition as lc
from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.experiment_freeze import apply_frozen_seed_policy, freeze_seed_policy
from src.learning.learning_controller_services.prompt_slot import projection
from src.learning.model_capabilities import compatible_context, policy_context
from src.learning.model_policy_service import resolve_policy, selected_model
from src.learning.ordinary_njr import materialize_njr
from src.learning.ordinary_prompt_freeze import (
    BASE_CONTRACT,
    PROMPT_SEMANTICS,
    apply_executor_base_prompts,
    freeze_preview_global_policy,
)
from src.learning.ordinary_snapshot import authored_fields, ordinary_snapshot
from src.learning.prompt_slot_experiment import digest
from src.pipeline.njr_core_v26 import NormalizedJobRecord
from src.pipeline.resolution_layer import pack_prompt_intent_from_dict


def asset_resolver(controller: Any, family: str) -> lc.AssetResolver:
    """Injected resolver, else the last explicitly refreshed discovery, else the cache-only registry; never a scan."""
    hook = getattr(controller, "_learning_lora_asset_resolver", None)
    if callable(hook):
        return hook  # type: ignore[no-any-return]
    from src.learning.lora_inventory import inventory_resolver, registry_resolver

    discovered = getattr(controller, "lora_inventory", None)
    if isinstance(discovered, dict) and discovered:
        return inventory_resolver(discovered, family)
    return registry_resolver(family)


def _source(experiment: Any) -> tuple[lc.LoraCompositionDesign, Any, dict[str, Any], str]:
    from src.promptpacks.storage import load_prompt_pack_document, prompt_pack_row_by_index

    metadata = experiment.metadata
    spec = metadata[lc.STUDY_TYPE]
    row = None
    prompt = str(experiment.prompt_text or "")
    source: dict[str, Any] = {"kind": metadata.get("prompt_source", "custom")}
    if source["kind"] == "pack":
        path = str(metadata["selected_prompt_pack_path"])
        try:
            document = load_prompt_pack_document(path)
            index = int(metadata["selected_prompt_index"])
            row = prompt_pack_row_by_index(document, index)
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError(
                "The selected native PromptPack row cannot be frozen; check the source and row selection."
            ) from exc
        prompt = row.quality_line + " " + row.subject_template
        source.update(
            row_index=index,
            row_digest=digest(document),
            pack_name=metadata.get("selected_prompt_pack_name", ""),
        )
    design = lc.design_from_spec(spec, prompt, experiment.images_per_value)
    return design, row, source, str(spec.get("negative_prompt", ""))


def _config(snapshot: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    from src.image_backends.model_policy import apply_model_compile_policy

    config: dict[str, Any] = copy.deepcopy(snapshot["baseline_config"])
    apply_model_compile_policy(config)
    apply_frozen_seed_policy(config, snapshot["seed_policy"])
    apply_executor_base_prompts(config, candidate["positive"], candidate["negative"], "txt2img")
    # Structured declarations describe exactly the executed set, as Model Comparison already does.
    config["txt2img"]["lora_strengths"] = lc.declarations(candidate)
    return config


def _materialize(
    controller: Any, experiment: Any, snapshot: dict[str, Any], variant: Any
) -> NormalizedJobRecord:
    from src.pipeline.job_models_v2 import LoRATag

    candidate = lc.frozen_candidate(snapshot, variant.param_value)
    config = _config(snapshot, candidate)
    intent = pack_prompt_intent_from_dict(candidate["source_intent"])
    index = snapshot["variant_values"].index(variant.param_value)
    frozen_experiment = replace(
        experiment,
        stage="txt2img",
        variable_under_test=lc.VARIABLE,
        images_per_value=snapshot["images_per_value"],
        prompt_text=snapshot["prompt_text"],
    )
    metadata = controller._build_learning_metadata(
        experiment=frozen_experiment, variant=variant, stage_name="txt2img", final_config=config
    )
    section = snapshot[lc.STUDY_TYPE]
    metadata[lc.STUDY_TYPE] = {
        "contract": section["contract"],
        "operation": section["operation"],
        "candidate_label": candidate["label"],
        "candidate_name": candidate["name"],
        "requested_strength": candidate["weight"],
        "expected_lora_digest": candidate["lora_digest"],
        "fixed_digest": section["fixed_digest"],
        "effective_digest": candidate["effective_digest"],
        "digest": section["digest"],
    }
    metadata["prompt_adaptation"] = {"contract": "prompt_adaptation/1", **candidate["adaptation"]}
    variant.executed_config = copy.deepcopy(config)
    record = materialize_njr(
        final_config=config,
        experiment=frozen_experiment,
        variant=variant,
        prompt=candidate["positive"],
        negative_prompt=candidate["negative"],
        learning_metadata=metadata,
        job_id=f"learning_{snapshot['experiment_id']}_{uuid.uuid4().hex}",
        variant_index=index,
        variant_total=len(snapshot["variant_values"]),
        selected_loras={entry.name: LoRATag(entry.name, entry.weight) for entry in intent.loras},
        output_dir=controller._resolve_learning_output_dir(config),
        filename_template=controller._resolve_learning_filename_template(config),
        strict=True,
    )
    declared = [(tag.name, tag.weight) for tag in record.provenance.lora_tags]
    if declared != [(n, w) for n, w in candidate["expected_loras"]]:
        raise ValueError("The compiled NJR LoRA declarations differ from the frozen composition.")
    return record


def build_plan(controller: Any, experiment: Any) -> None:
    from src.gui.learning_state import LearningVariant
    from src.pipeline.global_prompt_policy import apply_global_prompt_policy

    if experiment.stage != "txt2img":
        raise ValueError("LoRA Composition supports txt2img only.")
    design, row, source, negative = _source(experiment)
    baseline = controller._authored_baseline(experiment)
    signature = authoring.signature(baseline, "txt2img")
    getter = getattr(controller.app_controller, "get_current_global_prompt_policy", None)
    global_policy = getter() if callable(getter) else None
    if isinstance(global_policy, dict):
        baseline = apply_global_prompt_policy(baseline, **global_policy)
    baseline = freeze_preview_global_policy(baseline)
    model = selected_model(baseline, "txt2img")
    policy = resolve_policy(model, controller, baseline)
    lc.require_target(policy, baseline)
    problems = authoring.baseline_problems(baseline, "txt2img")
    if problems:
        raise ValueError("The Learning baseline is incomplete: " + "; ".join(problems))
    baseline = authoring.finalize_for_stage(baseline, "txt2img")
    context = policy_context(policy, model, "txt2img")
    frozen = lc.freeze_candidates(
        design,
        policy,
        baseline,
        resolver=asset_resolver(controller, policy.family),
        # A native row already owns its negative phrases/embeddings; only a custom source adds one.
        negative="" if row is not None else negative,
        row=row,
        source=source,
    )
    values = [item["label"] for item in frozen["candidates"]]
    experiment.experiment_id = experiment.experiment_id or uuid.uuid4().hex
    # Prepare on copies; a failed Preview must never publish a partial plan into live Learning.
    prepared = replace(
        experiment,
        values=values,
        variable_under_test=lc.VARIABLE,
        baseline_config=baseline,
        prompt_text=design.prompt,
        metadata=copy.deepcopy(experiment.metadata),
    )
    seed = freeze_seed_policy(baseline, experiment.images_per_value)
    prompt_source = {
        **source,
        "prompt_source": lc.STUDY_TYPE,
        "executor_base_contract": BASE_CONTRACT,
        "prompt_semantics": PROMPT_SEMANTICS,
    }
    snapshot = ordinary_snapshot(
        prepared,
        baseline=baseline,
        negative_prompt=frozen["candidates"][0]["negative"],
        seed_policy=seed,
        prompt_source=prompt_source,
        model_context=context,
        authored=authored_fields(
            prepared,
            baseline,
            "txt2img",
            draft_signature=signature,
            variable="",
            variant_settings=[],
        ),
    )
    snapshot.update(study_type=lc.STUDY_TYPE, **{lc.STUDY_TYPE: frozen})
    from src.generation_profiles.identity import ModelIdentityResolver

    snapshot["model_identity"] = (
        ModelIdentityResolver(policy_resolver=lambda _: policy).resolve(model).identity.to_dict()
    )
    prepared.execution_snapshot_json = freeze_snapshot(snapshot)
    variants = [
        LearningVariant(
            experiment_id=prepared.experiment_id,
            variant_id=f"{prepared.experiment_id}:{i}",
            param_value=value,
            status="pending",
            planned_images=experiment.images_per_value,
        )
        for i, value in enumerate(values)
    ]
    plan = []
    for variant in variants:
        inputs = projection(_materialize(controller, prepared, snapshot, variant))
        plan.append(
            {
                "label": variant.param_value,
                "input_digest": digest(inputs),
                "config_digest": digest(inputs["config"]),
            }
        )
    snapshot["compiled_lora_composition_plan"] = plan
    snapshot["compiled_lora_composition_plan_digest"] = digest(plan)
    prepared.execution_snapshot_json = freeze_snapshot(snapshot)
    controller.learning_state.current_experiment = prepared
    controller.learning_state.plan = variants
    controller.load_existing_ratings()
    if controller._plan_table:
        controller._update_plan_table()
    controller._set_workflow_state("planned")
    controller._notify_resume_state_changed()


def build_variant(controller: Any, experiment: Any, variant: Any) -> NormalizedJobRecord:
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    if snapshot.get("stage") != "txt2img" or snapshot.get("variable_under_test") != lc.VARIABLE:
        raise ValueError("Frozen LoRA Composition stage/variable identity is corrupt.")
    if digest(snapshot["compiled_lora_composition_plan"]) != snapshot.get(
        "compiled_lora_composition_plan_digest"
    ):
        raise ValueError("Frozen LoRA Composition executable plan is corrupt.")
    baseline = snapshot["baseline_config"]
    model = selected_model(baseline, "txt2img")
    policy = resolve_policy(model, controller, baseline)
    lc.require_target(policy, baseline)
    if not compatible_context(
        snapshot["model_policy_context"], policy_context(policy, model, "txt2img")
    ):
        raise ValueError("Frozen LoRA Composition model policy changed. Rebuild Preview.")
    index = snapshot["variant_values"].index(variant.param_value)
    if (
        variant.experiment_id != snapshot["experiment_id"]
        or variant.variant_id != f"{snapshot['experiment_id']}:{index}"
    ):
        raise ValueError("LoRA Composition variant identity conflicts with the frozen experiment.")
    from src.generation_profiles.contract import ModelIdentity
    from src.generation_profiles.identity import ModelIdentityResolver

    saved = ModelIdentity.from_dict(snapshot["model_identity"])
    current = ModelIdentityResolver(policy_resolver=lambda _: policy).resolve(model).identity
    if saved.model_key != current.model_key or (saved.sha256 and saved.sha256 != current.sha256):
        raise ValueError("The frozen LoRA Composition checkpoint identity is no longer verified.")
    lc.verify_assets(snapshot, asset_resolver(controller, policy.family))
    record = _materialize(controller, experiment, snapshot, variant)
    if (
        digest(projection(record))
        != snapshot["compiled_lora_composition_plan"][index]["input_digest"]
    ):
        raise ValueError(
            "LoRA Composition NJR differs from the frozen Preview. No variants were admitted."
        )
    return record

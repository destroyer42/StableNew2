"""Embedding experiment coordination over existing snapshot, ordinary NJR and Learning state owners."""

from __future__ import annotations

import copy
import uuid
from dataclasses import replace
from typing import Any

from src.learning import baseline_authoring as authoring
from src.learning import embedding_experiment as ee
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
from src.utils.embedding_prompt_utils import render_embedding_invocation


def asset_resolver(controller: Any, family: str) -> ee.AssetResolver:
    """Injected resolver, else the last explicitly refreshed discovery, else the cache-only registry; never a scan."""
    hook = getattr(controller, "_learning_embedding_asset_resolver", None)
    if callable(hook):
        return hook  # type: ignore[no-any-return]
    from src.learning.embedding_inventory import inventory_resolver, registry_resolver

    discovered = getattr(controller, "embedding_inventory", None)
    if isinstance(discovered, dict) and discovered:
        return inventory_resolver(discovered, family)
    return registry_resolver(family)


def _source(experiment: Any) -> tuple[ee.EmbeddingDesign, Any, dict[str, Any], str]:
    from src.promptpacks.storage import load_prompt_pack_document, prompt_pack_row_by_index

    metadata = experiment.metadata
    spec = metadata[ee.STUDY_TYPE]
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
    design = ee.design_from_spec(spec, prompt, experiment.images_per_value)
    return design, row, source, str(spec.get("negative_prompt", ""))


def _config(snapshot: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    from src.image_backends.model_policy import apply_model_compile_policy

    config: dict[str, Any] = copy.deepcopy(snapshot["baseline_config"])
    apply_model_compile_policy(config)
    apply_frozen_seed_policy(config, snapshot["seed_policy"])
    # No embedding "strength" config field exists on the backend: the contribution lives only in the prompt text.
    apply_executor_base_prompts(config, candidate["positive"], candidate["negative"], "txt2img")
    return config


def _embedding_projection(record: NormalizedJobRecord) -> dict[str, Any]:
    """Executable inputs plus the first-class embedding declarations (the base projection omits provenance)."""
    return {
        **projection(record),
        "embeddings": [list(record.positive_embeddings), list(record.negative_embeddings)],
    }


def _materialize(
    controller: Any, experiment: Any, snapshot: dict[str, Any], variant: Any
) -> NormalizedJobRecord:
    from src.pipeline.job_models_v2 import LoRATag

    candidate = ee.frozen_candidate(snapshot, variant.param_value)
    config = _config(snapshot, candidate)
    intent = pack_prompt_intent_from_dict(candidate["source_intent"])
    index = snapshot["variant_values"].index(variant.param_value)
    frozen_experiment = replace(
        experiment,
        stage="txt2img",
        variable_under_test=ee.VARIABLE,
        images_per_value=snapshot["images_per_value"],
        prompt_text=snapshot["prompt_text"],
    )
    metadata = controller._build_learning_metadata(
        experiment=frozen_experiment, variant=variant, stage_name="txt2img", final_config=config
    )
    section = snapshot[ee.STUDY_TYPE]
    metadata[ee.STUDY_TYPE] = {
        "contract": section["contract"],
        "operation": section["operation"],
        "channel": section["channel"],
        "candidate_label": candidate["label"],
        "candidate_name": candidate["name"],
        "requested_weight": candidate["weight"],
        "expected_embedding_digest": candidate["embedding_digest"],
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
    expected = ee.declarations(candidate)
    record = replace(
        record,
        provenance=replace(
            record.provenance,
            positive_embeddings=tuple(
                render_embedding_invocation(*entry) for entry in expected[ee.POSITIVE]
            ),
            negative_embeddings=tuple(
                render_embedding_invocation(*entry) for entry in expected[ee.NEGATIVE]
            ),
        ),
    )
    declared = [
        ee.observed_embeddings(" ".join(record.positive_embeddings), section["universe"]),
        ee.observed_embeddings(" ".join(record.negative_embeddings), section["universe"]),
    ]
    if not (
        ee.same_entries(declared[0], expected[ee.POSITIVE])
        and ee.same_entries(declared[1], expected[ee.NEGATIVE])
    ):
        raise ValueError(
            "The compiled NJR embedding declarations differ from the frozen experiment."
        )
    return record


def build_plan(controller: Any, experiment: Any) -> None:
    from src.gui.learning_state import LearningVariant
    from src.pipeline.global_prompt_policy import apply_global_prompt_policy

    if experiment.stage != "txt2img":
        raise ValueError("Embedding experiments support txt2img only.")
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
    ee.require_target(policy, baseline, design.channel)
    problems = authoring.baseline_problems(baseline, "txt2img")
    if problems:
        raise ValueError("The Learning baseline is incomplete: " + "; ".join(problems))
    baseline = authoring.finalize_for_stage(baseline, "txt2img")
    context = policy_context(policy, model, "txt2img")
    frozen = ee.freeze_candidates(
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
        variable_under_test=ee.VARIABLE,
        baseline_config=baseline,
        prompt_text=design.prompt,
        metadata=copy.deepcopy(experiment.metadata),
    )
    seed = freeze_seed_policy(baseline, experiment.images_per_value)
    prompt_source = {
        **source,
        "prompt_source": ee.STUDY_TYPE,
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
    snapshot.update(study_type=ee.STUDY_TYPE, **{ee.STUDY_TYPE: frozen})
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
        inputs = _embedding_projection(_materialize(controller, prepared, snapshot, variant))
        plan.append(
            {
                "label": variant.param_value,
                "input_digest": digest(inputs),
                "config_digest": digest(inputs["config"]),
            }
        )
    snapshot["compiled_embedding_plan"] = plan
    snapshot["compiled_embedding_plan_digest"] = digest(plan)
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
    if snapshot.get("stage") != "txt2img" or snapshot.get("variable_under_test") != ee.VARIABLE:
        raise ValueError("Frozen embedding experiment stage/variable identity is corrupt.")
    if digest(snapshot["compiled_embedding_plan"]) != snapshot.get(
        "compiled_embedding_plan_digest"
    ):
        raise ValueError("Frozen embedding experiment executable plan is corrupt.")
    section = ee.frozen_section(snapshot)
    baseline = snapshot["baseline_config"]
    model = selected_model(baseline, "txt2img")
    policy = resolve_policy(model, controller, baseline)
    ee.require_target(policy, baseline, section["channel"])
    if not compatible_context(
        snapshot["model_policy_context"], policy_context(policy, model, "txt2img")
    ):
        raise ValueError("Frozen embedding experiment model policy changed. Rebuild Preview.")
    index = snapshot["variant_values"].index(variant.param_value)
    if (
        variant.experiment_id != snapshot["experiment_id"]
        or variant.variant_id != f"{snapshot['experiment_id']}:{index}"
    ):
        raise ValueError("Embedding variant identity conflicts with the frozen experiment.")
    from src.generation_profiles.contract import ModelIdentity
    from src.generation_profiles.identity import ModelIdentityResolver

    saved = ModelIdentity.from_dict(snapshot["model_identity"])
    current = ModelIdentityResolver(policy_resolver=lambda _: policy).resolve(model).identity
    if saved.model_key != current.model_key or (saved.sha256 and saved.sha256 != current.sha256):
        raise ValueError(
            "The frozen embedding experiment checkpoint identity is no longer verified."
        )
    ee.verify_assets(snapshot, asset_resolver(controller, policy.family))
    record = _materialize(controller, experiment, snapshot, variant)
    if (
        digest(_embedding_projection(record))
        != snapshot["compiled_embedding_plan"][index]["input_digest"]
    ):
        raise ValueError(
            "Embedding experiment NJR differs from the frozen Preview. No variants were admitted."
        )
    return record

"""Prompt Slot coordination over existing snapshot, ordinary NJR and Learning state owners."""

from __future__ import annotations

import copy
import uuid
from dataclasses import replace
from typing import Any

from src.learning import baseline_authoring as authoring
from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.experiment_freeze import apply_frozen_seed_policy, freeze_seed_policy
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
from src.learning.prompt_slot_experiment import (
    STUDY_TYPE,
    VARIABLE,
    PromptSlotDesign,
    digest,
    freeze_candidates,
    frozen_candidate,
    require_target,
)
from src.pipeline.njr_core_v26 import NormalizedJobRecord, thaw_json
from src.pipeline.resolution_layer import pack_prompt_intent_from_dict


def source_design(
    experiment: Any, key: str = STUDY_TYPE
) -> tuple[PromptSlotDesign, Any, dict[str, Any]]:
    """The authored one-slot design and its frozen source (custom template or one native PromptPack row)."""
    from src.promptpacks.storage import load_prompt_pack_document, prompt_pack_row_by_index

    metadata = experiment.metadata
    spec = metadata[key]
    row = None
    source = {"kind": metadata.get("prompt_source", "custom")}
    template = spec["template"]
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
        template = row.quality_line + " " + row.subject_template
        source.update(
            row_index=index,
            row_digest=digest(document),
            pack_name=metadata.get("selected_prompt_pack_name", ""),
        )
    design = PromptSlotDesign(
        template,
        spec["slot"],
        tuple(spec["candidates"]),
        dict(spec.get("fixed_slots") or {}),
        experiment.images_per_value,
    )
    return design, row, source


_source = source_design


def _config(snapshot: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    from src.image_backends.model_policy import apply_model_compile_policy

    config: dict[str, Any] = copy.deepcopy(snapshot["baseline_config"])
    apply_model_compile_policy(config)
    apply_frozen_seed_policy(config, snapshot["seed_policy"])
    apply_executor_base_prompts(config, candidate["positive"], candidate["negative"], "txt2img")
    return config


def projection(record: Any) -> dict[str, Any]:
    """Executable inputs only: exclude identity/timestamps and duplicated provenance snapshots."""
    return {
        "config": thaw_json(record.workload.config),
        "positive": record.positive_prompt,
        "negative": record.negative_prompt,
        "model": record.stages[0].model,
        "stages": [stage.stage_type for stage in record.stages if stage.enabled],
        "images": record.workload.images_per_prompt,
        "seed": record.seed,
        "backend_options": thaw_json(record.workload.backend_options),
    }


def _materialize(
    controller: Any, experiment: Any, snapshot: dict[str, Any], variant: Any
) -> NormalizedJobRecord:
    from src.pipeline.job_models_v2 import LoRATag

    candidate = frozen_candidate(snapshot, variant.param_value)
    config = _config(snapshot, candidate)
    intent = pack_prompt_intent_from_dict(candidate["source_intent"])
    index = snapshot["variant_values"].index(variant.param_value)
    frozen_experiment = replace(
        experiment,
        stage="txt2img",
        variable_under_test=VARIABLE,
        images_per_value=snapshot["images_per_value"],
        prompt_text=snapshot["prompt_text"],
    )
    metadata = controller._build_learning_metadata(
        experiment=frozen_experiment, variant=variant, stage_name="txt2img", final_config=config
    )
    metadata[STUDY_TYPE] = {
        "contract": snapshot[STUDY_TYPE]["contract"],
        "slot": snapshot[STUDY_TYPE]["slot"],
        "candidate_label": candidate["label"],
        "candidate_value": candidate["value"],
        "effective_digest": candidate["effective_digest"],
        "digest": snapshot[STUDY_TYPE]["digest"],
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
    from src.utils.embedding_prompt_utils import render_embedding_invocation

    return replace(
        record,
        provenance=replace(
            record.provenance,
            positive_embeddings=tuple(
                render_embedding_invocation(*entry) for entry in intent.positive_embeddings
            ),
            negative_embeddings=tuple(
                render_embedding_invocation(*entry) for entry in intent.negative_embeddings
            ),
        ),
    )


def build_plan(controller: Any, experiment: Any) -> None:
    from src.gui.learning_state import LearningVariant
    from src.pipeline.global_prompt_policy import apply_global_prompt_policy

    if experiment.stage != "txt2img":
        raise ValueError("Prompt Slot supports txt2img only.")
    design, row, source = _source(experiment)
    baseline = controller._authored_baseline(experiment)
    signature = authoring.signature(baseline, "txt2img")
    getter = getattr(controller.app_controller, "get_current_global_prompt_policy", None)
    global_policy = getter() if callable(getter) else None
    if isinstance(global_policy, dict):
        baseline = apply_global_prompt_policy(baseline, **global_policy)
    baseline = freeze_preview_global_policy(baseline)
    model = selected_model(baseline, "txt2img")
    policy = resolve_policy(model, controller, baseline)
    require_target(policy, baseline)
    problems = authoring.baseline_problems(baseline, "txt2img")
    if problems:
        raise ValueError("The Learning baseline is incomplete: " + "; ".join(problems))
    baseline = authoring.finalize_for_stage(baseline, "txt2img")
    context = policy_context(policy, model, "txt2img")
    # A native row already owns its negative phrases/embeddings. The GUI's selected
    # negative is only their display projection, never a second contribution.
    negative = (
        "" if row is not None else str(experiment.metadata[STUDY_TYPE].get("negative_prompt", ""))
    )
    from src.learning.resource_access import get_projected_resources
    from src.learning.variable_selection_contract import normalize_resource_entries

    embedding_names = tuple(
        normalize_resource_entries(
            list(get_projected_resources(controller).get("embeddings") or [])
        )[1].values()
    )
    frozen = freeze_candidates(
        design,
        policy,
        baseline,
        row=row,
        source=source,
        negative=negative,
        embedding_names=embedding_names,
    )
    values = [item["label"] for item in frozen["candidates"]]
    experiment.experiment_id = experiment.experiment_id or uuid.uuid4().hex
    # Prepare on copies; a failed Preview must never publish a partial plan into live Learning.
    prepared = replace(
        experiment,
        values=values,
        variable_under_test=VARIABLE,
        baseline_config=baseline,
        prompt_text=design.template,
        metadata=copy.deepcopy(experiment.metadata),
    )
    seed = freeze_seed_policy(baseline, experiment.images_per_value)
    prompt_source = {
        **source,
        "prompt_source": STUDY_TYPE,
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
    snapshot.update(study_type=STUDY_TYPE, **{STUDY_TYPE: frozen})
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
    snapshots = []
    for variant in variants:
        record = _materialize(controller, prepared, snapshot, variant)
        inputs = projection(record)
        snapshots.append(
            {
                "label": variant.param_value,
                "input_digest": digest(inputs),
                "config_digest": digest(inputs["config"]),
            }
        )
    snapshot["compiled_prompt_slot_plan"] = snapshots
    snapshot["compiled_prompt_slot_plan_digest"] = digest(snapshots)
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
    if snapshot.get("stage") != "txt2img" or snapshot.get("variable_under_test") != VARIABLE:
        raise ValueError("Frozen Prompt Slot stage/variable identity is corrupt.")
    if digest(snapshot["compiled_prompt_slot_plan"]) != snapshot.get(
        "compiled_prompt_slot_plan_digest"
    ):
        raise ValueError("Frozen Prompt Slot executable plan is corrupt.")
    baseline = snapshot["baseline_config"]
    model = selected_model(baseline, "txt2img")
    policy = resolve_policy(model, controller, baseline)
    require_target(policy, baseline)
    if not compatible_context(
        snapshot["model_policy_context"], policy_context(policy, model, "txt2img")
    ):
        raise ValueError("Frozen Prompt Slot model policy changed. Rebuild Preview.")
    index = snapshot["variant_values"].index(variant.param_value)
    if (
        variant.experiment_id != snapshot["experiment_id"]
        or variant.variant_id != f"{snapshot['experiment_id']}:{index}"
    ):
        raise ValueError("Prompt Slot variant identity conflicts with the frozen experiment.")
    from src.generation_profiles.contract import ModelIdentity
    from src.generation_profiles.identity import ModelIdentityResolver

    saved = ModelIdentity.from_dict(snapshot["model_identity"])
    current = ModelIdentityResolver(policy_resolver=lambda _: policy).resolve(model).identity
    if saved.model_key != current.model_key or (saved.sha256 and saved.sha256 != current.sha256):
        raise ValueError("The frozen Prompt Slot checkpoint identity is no longer verified.")
    record = _materialize(controller, experiment, snapshot, variant)
    if digest(projection(record)) != snapshot["compiled_prompt_slot_plan"][index]["input_digest"]:
        raise ValueError(
            "Prompt Slot NJR differs from the frozen Preview. No variants were admitted."
        )
    return record

"""Compatibility probe coordination (MEC-901) over the existing snapshot, ordinary NJR and Learning state owners.

Each variant is one frozen recipe applied to the probe baseline (the target checkpoint, txt2img only, model-owned
VAE, no adapters or secondary stages). Prompt and seed cohort are common to every recipe. The checkpoint must be
byte-verified and the policy is frozen at Preview; a probe may target a family StableNew has not qualified (owner
decision D1), but never an exact executable profile, which owns its own settings.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import replace
from typing import Any

from src.learning import baseline_authoring as authoring
from src.learning.compatibility_probe import (
    RECIPE_FIELDS,
    STUDY_TYPE,
    VARIABLE,
    digest,
    frozen_recipe,
    verify_spec,
)
from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.experiment_freeze import apply_frozen_seed_policy, freeze_seed_policy
from src.learning.model_capabilities import policy_context
from src.learning.model_policy_service import resolve_policy, selected_model
from src.learning.ordinary_njr import materialize_njr
from src.learning.ordinary_prompt_freeze import (
    BASE_CONTRACT,
    PROMPT_SEMANTICS,
    apply_executor_base_prompts,
    freeze_preview_global_policy,
)
from src.learning.ordinary_snapshot import authored_fields, ordinary_snapshot
from src.pipeline.njr_core_v26 import NormalizedJobRecord, thaw_json

_FROZEN_POLICY_KEYS = ("policy_id", "family", "evidence", "profile_ref", "stage", "contract")


def apply_recipe(config: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Write each recipe field through its canonical txt2img spelling, keeping aliases aligned."""
    for spec in authoring.fields_for_stage("txt2img"):
        if spec.key in settings and spec.key in RECIPE_FIELDS:
            authoring.write_field(config, spec, copy.deepcopy(settings[spec.key]))
    authoring.align_aliases(config, "txt2img")
    return config


def require_probe_target(policy: Any, baseline: dict[str, Any], spec: dict[str, Any]) -> None:
    if "txt2img" not in policy.stages:
        raise ValueError("This checkpoint's policy does not allow txt2img, so it cannot be probed.")
    if policy.qualified:
        raise ValueError(
            "This checkpoint has a fixed executable profile that owns its settings; there is nothing to probe."
        )
    for recipe in spec["recipes"]:
        for name, value in recipe["settings"].items():
            control = policy.control(name, "txt2img")
            if getattr(getattr(control, "mode", None), "value", "") == "fixed" and control.value != value:
                raise ValueError(f"{recipe['label']}: the model policy fixes {name} at {control.value}.")
    if any(
        bool((section.get("prompt_optimizer") or {}).get("enabled"))
        for section in (baseline, baseline.get("txt2img") or {})
    ):
        raise ValueError("The prompt optimizer must be off for a probe.")


def _identity(model: str, policy: Any) -> Any:
    from src.generation_profiles.identity import ModelIdentityResolver

    return ModelIdentityResolver(policy_resolver=lambda _: policy).resolve(model).identity


def _config(snapshot: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    from src.image_backends.model_policy import apply_model_compile_policy

    spec = snapshot[STUDY_TYPE]
    config: dict[str, Any] = copy.deepcopy(snapshot["baseline_config"])
    apply_recipe(config, recipe["settings"])
    apply_model_compile_policy(config)
    apply_frozen_seed_policy(config, snapshot["seed_policy"])
    apply_executor_base_prompts(config, spec["prompt"], spec["negative"], "txt2img")
    return config


def projection(record: Any) -> dict[str, Any]:
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
    spec = snapshot[STUDY_TYPE]
    recipe = frozen_recipe(spec, variant.param_value)
    config = _config(snapshot, recipe)
    index = snapshot["variant_values"].index(variant.param_value)
    frozen_experiment = replace(
        experiment,
        stage="txt2img",
        variable_under_test=VARIABLE,
        images_per_value=snapshot["images_per_value"],
        prompt_text=spec["prompt"],
    )
    metadata = controller._build_learning_metadata(
        experiment=frozen_experiment, variant=variant, stage_name="txt2img", final_config=config
    )
    metadata[STUDY_TYPE] = {
        "contract": spec["contract"],
        "recipe_key": recipe["key"],
        "recipe_label": recipe["label"],
        "lineage": recipe["lineage"],
        "origin": recipe["origin"],
        "settings": copy.deepcopy(recipe["settings"]),
        "digest": spec["digest"],
        "sha256": spec["sha256"],
    }
    variant.executed_config = copy.deepcopy(config)
    return materialize_njr(
        final_config=config,
        experiment=frozen_experiment,
        variant=variant,
        prompt=spec["prompt"],
        negative_prompt=spec["negative"],
        learning_metadata=metadata,
        job_id=f"learning_{snapshot['experiment_id']}_{uuid.uuid4().hex}",
        variant_index=index,
        variant_total=len(snapshot["variant_values"]),
        selected_loras={},
        output_dir=controller._resolve_learning_output_dir(config),
        filename_template=controller._resolve_learning_filename_template(config),
        strict=True,
    )


def build_plan(controller: Any, experiment: Any) -> None:
    from src.gui.learning_state import LearningVariant

    if experiment.stage != "txt2img":
        raise ValueError("A compatibility probe supports txt2img only.")
    spec = copy.deepcopy(experiment.metadata[STUDY_TYPE])
    verify_spec(spec)
    baseline = controller._authored_baseline(experiment)
    signature = authoring.signature(baseline, "txt2img")
    baseline = freeze_preview_global_policy(baseline)
    model = selected_model(baseline, "txt2img")
    policy = resolve_policy(model, controller, baseline)
    require_probe_target(policy, baseline, spec)
    identity = _identity(model, policy)
    if not identity.sha256 or identity.sha256 != spec["sha256"]:
        raise ValueError(
            "The probe checkpoint is not the verified file it was designed for. Verify it again, then rebuild."
        )
    baseline = authoring.finalize_for_stage(baseline, "txt2img")
    problems = authoring.baseline_problems(apply_recipe(copy.deepcopy(baseline), spec["recipes"][0]["settings"]), "txt2img")
    if problems:
        raise ValueError("The probe baseline is incomplete: " + "; ".join(problems))
    values = [recipe["label"] for recipe in spec["recipes"]]
    images = int(spec["images_per_recipe"])
    experiment.experiment_id = experiment.experiment_id or uuid.uuid4().hex
    prepared = replace(
        experiment,
        values=values,
        variable_under_test=VARIABLE,
        images_per_value=images,
        baseline_config=baseline,
        prompt_text=spec["prompt"],
        metadata=copy.deepcopy(experiment.metadata),
    )
    snapshot = ordinary_snapshot(
        prepared,
        baseline=baseline,
        negative_prompt=spec["negative"],
        seed_policy=freeze_seed_policy(baseline, images),
        prompt_source={
            "kind": "custom",
            "prompt_source": STUDY_TYPE,
            "executor_base_contract": BASE_CONTRACT,
            "prompt_semantics": PROMPT_SEMANTICS,
        },
        model_context=policy_context(policy, model, "txt2img"),
        authored=authored_fields(
            prepared,
            baseline,
            "txt2img",
            draft_signature=signature,
            variable="",
            variant_settings=[
                {"label": recipe["label"], **recipe["settings"]} for recipe in spec["recipes"]
            ],
        ),
    )
    snapshot.update(study_type=STUDY_TYPE, **{STUDY_TYPE: spec})
    snapshot["model_identity"] = identity.to_dict()
    prepared.execution_snapshot_json = freeze_snapshot(snapshot)
    variants = [
        LearningVariant(
            experiment_id=prepared.experiment_id,
            variant_id=f"{prepared.experiment_id}:{i}",
            param_value=value,
            status="pending",
            planned_images=images,
        )
        for i, value in enumerate(values)
    ]
    compiled = []
    for variant in variants:
        inputs = projection(_materialize(controller, prepared, snapshot, variant))
        compiled.append({"label": variant.param_value, "input_digest": digest(inputs)})
    snapshot["compiled_probe_plan"] = compiled
    snapshot["compiled_probe_plan_digest"] = digest(compiled)
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
        raise ValueError("Frozen compatibility probe stage/variable identity is corrupt.")
    if digest(snapshot.get("compiled_probe_plan")) != snapshot.get("compiled_probe_plan_digest"):
        raise ValueError("Frozen compatibility probe plan is corrupt.")
    spec = snapshot[STUDY_TYPE]
    verify_spec(spec)
    baseline = snapshot["baseline_config"]
    model = selected_model(baseline, "txt2img")
    policy = resolve_policy(model, controller, baseline)
    require_probe_target(policy, baseline, spec)
    frozen, current = snapshot["model_policy_context"], policy_context(policy, model, "txt2img")
    if any(frozen.get(key) != current.get(key) for key in _FROZEN_POLICY_KEYS):
        raise ValueError("The probe checkpoint's model policy changed. Rebuild the probe.")
    identity = _identity(model, policy)
    if not identity.sha256 or identity.sha256 != spec["sha256"]:
        raise ValueError("The probe checkpoint is no longer the verified file. Nothing was admitted.")
    index = snapshot["variant_values"].index(variant.param_value)
    if (
        variant.experiment_id != snapshot["experiment_id"]
        or variant.variant_id != f"{snapshot['experiment_id']}:{index}"
    ):
        raise ValueError("Probe variant identity conflicts with the frozen experiment.")
    record = _materialize(controller, experiment, snapshot, variant)
    if digest(projection(record)) != snapshot["compiled_probe_plan"][index]["input_digest"]:
        raise ValueError("Probe job differs from the frozen Preview. No variants were admitted.")
    return record

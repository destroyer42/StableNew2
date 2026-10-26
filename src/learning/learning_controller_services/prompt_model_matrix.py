"""Prompt x Model Matrix coordination over the existing snapshot, ordinary NJR and Learning state owners.

Preview freezes the whole matrix and queues nothing. Run compiles every frozen cell through ``build_variant`` (the
controller's all-or-none admission) before one batch submission; nothing here switches models or owns a runtime.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.learning_controller_services.prompt_slot import source_design
from src.learning.prompt_model_matrix import STUDY_TYPE, VARIABLE, materialize_njr
from src.pipeline.njr_core_v26 import NormalizedJobRecord


def build_plan(controller: Any, experiment: Any, comparison_evidence: Any = None) -> None:
    from src.gui.learning_state import LearningVariant
    from src.learning.prompt_model_matrix import build_matrix_snapshot
    from src.learning.resource_access import get_projected_resources
    from src.learning.variable_selection_contract import normalize_resource_entries
    from src.pipeline.compile_evidence import CompileEvidence
    from src.pipeline.global_prompt_policy import apply_global_prompt_policy

    if experiment.stage != "txt2img":
        raise ValueError("Prompt x Model Matrix supports txt2img only.")
    design, row, source = source_design(experiment, STUDY_TYPE)
    experiment.experiment_id = experiment.experiment_id or uuid.uuid4().hex
    baseline = controller._authored_baseline(experiment)
    getter = getattr(controller.app_controller, "get_current_global_prompt_policy", None)
    policy = getter() if callable(getter) else None
    if isinstance(policy, dict):
        baseline = apply_global_prompt_policy(baseline, **policy)
    embedding_names = tuple(
        normalize_resource_entries(
            list(get_projected_resources(controller).get("embeddings") or [])
        )[1].values()
    )
    # Prepare on a copy: a refused Preview must never publish a partial plan into live Learning.
    prepared = replace(experiment, metadata=dict(experiment.metadata))
    negative = (
        "" if row is not None else str(experiment.metadata[STUDY_TYPE].get("negative_prompt", ""))
    )
    snapshot = build_matrix_snapshot(
        prepared,
        baseline,
        design=design,
        row=row,
        source=source,
        negative=negative,
        evidence=comparison_evidence
        or CompileEvidence(lora_resolver=getattr(controller, "_learning_lora_resolver", None)),
        policy_resolver=getattr(controller, "_learning_policy_resolver", None),
        embedding_names=embedding_names,
    )
    prepared.execution_snapshot_json = freeze_snapshot(snapshot)
    prepared.baseline_config = snapshot["baseline_config"]
    prepared.prompt_text = snapshot["prompt_text"]
    prepared.variable_under_test = VARIABLE
    prepared.values = list(snapshot["variant_values"])
    variants = [
        LearningVariant(
            experiment_id=prepared.experiment_id,
            variant_id=f"{prepared.experiment_id}:{index}",
            param_value=value,
            status="pending",
            planned_images=snapshot["images_per_value"],
        )
        for index, value in enumerate(snapshot["variant_values"])
    ]
    controller.learning_state.current_experiment = prepared
    controller.learning_state.plan = variants
    controller.load_existing_ratings()
    if controller._plan_table:
        controller._update_plan_table()
    controller._set_workflow_state("planned")
    controller._notify_resume_state_changed()


def build_variant(controller: Any, experiment: Any, variant: Any) -> NormalizedJobRecord:
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    index = next(
        (
            i
            for i, value in enumerate(snapshot.get("variant_values") or [])
            if value == variant.param_value
        ),
        -1,
    )
    if (
        index < 0
        or variant.experiment_id != snapshot.get("experiment_id")
        or variant.variant_id != f"{snapshot['experiment_id']}:{index}"
    ):
        raise ValueError("Matrix variant identity conflicts with the frozen experiment.")
    baseline = snapshot.get("baseline_config") or {}
    record: NormalizedJobRecord = materialize_njr(
        snapshot,
        variant,
        metadata_factory=lambda config: controller._build_learning_metadata(
            experiment=experiment, variant=variant, stage_name="txt2img", final_config=config
        ),
        output_dir=controller._resolve_learning_output_dir(baseline),
        filename_template=controller._resolve_learning_filename_template(baseline),
    )
    return record

# Subsystem: Learning
# Role: Bridges the learning GUI tab and the core learning subsystem.

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from src.curation.curation_workflow_builder import (
    CurationAdvancementPlan,
    CurationSourceSelection,
    CurationWorkflowBuilder,
    DerivedStage,
)
from src.curation.learning_bridge import (
    CurationLearningBridge,
    CurationLearningContext,
)
from src.curation.models import CurationCandidate, CurationWorkflow, SelectionEvent
from src.curation.workflow_summary import (
    build_candidate_replay_entry,
    build_workflow_summary,
    find_latest_derived_descendant,
)
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.gui.models.prompt_metadata import build_prompt_metadata
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui_v2.adapters.learning_adapter_v2 import (
    list_recent_learning_records,
    update_record_feedback,
)
from src.learning import baseline_authoring as authoring
from src.learning import baseline_draft as draft_service
from src.learning.automation_modes import DEFAULT_AUTOMATION_MODE
from src.learning.design_estimate import range_values
from src.learning.discovered_review_models import (
    DiscoveredReviewExperiment,
    DiscoveredReviewItem,
)
from src.learning.draft_commit import DraftCommitSummary, commit_drafts
from src.learning.evidence_progress import EvidenceProgress, evidence_progress
from src.learning.experiment_conclusion import build_experiment_conclusion
from src.learning.experiment_execution import (
    ExperimentAdmissionService,
    freeze_snapshot,
    snapshot_digest,
    thaw_snapshot,
)
from src.learning.experiment_freeze import (
    apply_frozen_seed_policy,
    freeze_seed_policy,
)
from src.learning.learning_controller_services.controlled_studies import (
    LOCAL_ONLY_STUDIES,
)
from src.learning.learning_controller_services.controlled_studies import (
    rating_metadata as controlled_rating_metadata,
)
from src.learning.learning_controller_services.controlled_studies import (
    service_for as controlled_study_service,
)
from src.learning.learning_controller_services.experiment_persistence import (
    build_resume_payload,
    extract_workflow_state,
    validate_resume_payload,
)
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.lora_variant import (
    apply_lora_variant,
    validate_lora_variant,
)
from src.learning.model_capabilities import policy_context
from src.learning.model_capabilities import variable_name as internal_variable_name
from src.learning.model_policy_service import (
    compile_variant,
    frozen_definition,
    negative_prompt_supported,
    recommendation_query,
    resolve_policy,
    selected_model,
    validate_experiment,
    validate_recommendation_apply,
)
from src.learning.ordinary_njr import materialize_njr as materialize_ordinary_njr
from src.learning.ordinary_prompt_freeze import (
    apply_executor_base_prompts,
    freeze_ordinary_prompt_source,
    freeze_preview_global_policy,
    frozen_negative_prompt,
    ordinary_rating_prompt_evidence,
    validate_ordinary_prompt_snapshot,
)
from src.learning.ordinary_snapshot import authored_fields, ordinary_snapshot
from src.learning.recommendation_engine import RecommendationEngine
from src.learning.resource_access import get_projected_resources
from src.learning.review_workspace import build_review_projection
from src.learning.staged_recommendations import (
    apply_derived_recommendation_patch,
    build_derived_recommendation_patch,
)
from src.learning.variable_selection_contract import normalize_resource_entries
from src.pipeline.artifact_contract import extract_artifact_paths
from src.pipeline.global_prompt_policy import (
    apply_global_prompt_policy,
    has_frozen_global_prompt_policy,
)
from src.pipeline.job_models_v2 import (
    LoRATag,
    NormalizedJobRecord,
)
from src.pipeline.reprocess_builder import ReprocessJobBuilder, ReprocessSourceItem
from src.review.artifact_metadata_inspector import ArtifactMetadataInspector
from src.review.review_metadata_service import (
    INTERNAL_REVIEW_SUMMARY_SCHEMA,
    PortableReviewSummary,
    ReviewMetadataService,
)
from src.review.workflow_adapter import (
    ReviewWorkflowAdapter,
    ReviewWorkspaceHandoff,
)
from src.state.output_routing import get_output_root, resolve_output_artifact_path
from src.utils.config import ConfigManager
from src.utils.image_metadata import (
    extract_embedded_metadata,
    resolve_model_vae_fields,
    resolve_prompt_fields,
)


class LearningController:
    """Controller for learning experiment workflows."""

    def __init__(
        self,
        learning_state: LearningState,
        prompt_workspace_state: PromptWorkspaceState | None = None,
        pipeline_state: Any | None = None,  # Placeholder for PipelineState
        pipeline_controller: Any | None = None,  # PipelineController reference
        app_controller: Any | None = None,  # AppController reference for stage cards
        plan_table: Any | None = None,  # LearningPlanTable reference
        review_panel: Any | None = None,  # LearningReviewPanel reference
        learning_record_writer: LearningRecordWriter
        | None = None,  # LearningRecordWriter reference
        execution_controller: Any | None = None,  # PR-LEARN-002: LearningExecutionController
    ) -> None:
        self.learning_state = learning_state
        self.lora_inventory: dict[str, Any] = {}  # last explicit LoRA discovery (LoRA Composition identity)
        self.embedding_inventory: dict[str, Any] = {}  # last explicit embedding discovery (Embedding identity)
        self.prompt_workspace_state = prompt_workspace_state
        self.pipeline_state = pipeline_state

        self.pipeline_controller = pipeline_controller
        self.app_controller = app_controller  # Store app_controller for stage card access
        self.execution_controller = (
            execution_controller or self._build_execution_controller()
        )  # PR-LEARN-073
        if self.execution_controller is not None:
            self.execution_controller.learning_state = learning_state
        self._plan_table = plan_table
        self._grid_view: Any = None  # LearningGridView, attached by the Learning tab
        self._review_panel = review_panel
        self._learning_record_writer = learning_record_writer
        self._learning_enabled = False
        self._automation_mode = DEFAULT_AUTOMATION_MODE
        self._automation_snapshot: dict[tuple[str, str], Any] = {}
        self._workflow_state = "idle"
        self._workflow_state_listeners: list[Any] = []
        self._resume_state_listeners: list[Any] = []
        self._curation_workflow_builder = CurationWorkflowBuilder()
        self._review_workflow_adapter = ReviewWorkflowAdapter()
        self._review_metadata_service = ReviewMetadataService()
        self._artifact_metadata_inspector = ArtifactMetadataInspector(self._review_metadata_service)
        self._experiment_admission = ExperimentAdmissionService()

        # Rating cache for current experiment
        self._rating_cache: dict[str, int] = {}  # {image_path: rating}
        self._rating_details_cache: dict[str, dict[str, Any]] = {}

        # Initialize recommendation engine if record writer is available
        self._recommendation_engine: RecommendationEngine | None = None
        if learning_record_writer:
            self._recommendation_engine = RecommendationEngine(learning_record_writer.records_path)

        # PR-LEARN-012: Set up execution controller callbacks
        if self.execution_controller:
            self.execution_controller.set_completion_callback(self._apply_variant_completion_evidence)
            self.execution_controller.set_failure_callback(self._on_variant_job_failed)
            present = getattr(self.execution_controller, "set_presentation_callback", None)
            if callable(present):
                present(self._on_variant_completion_published)

    def _build_execution_controller(self) -> Any | None:
        """Create the canonical learning execution controller when JobService is available."""
        job_service = None
        if self.pipeline_controller is not None:
            controller_dict = getattr(self.pipeline_controller, "__dict__", {})
            get_job_service = (
                getattr(self.pipeline_controller, "get_job_service", None)
                if "get_job_service" in controller_dict
                else None
            )
            if callable(get_job_service):
                try:
                    job_service = get_job_service()
                except Exception:
                    job_service = None
            if job_service is None:
                job_service = (
                    getattr(self.pipeline_controller, "_job_service", None)
                    if "_job_service" in controller_dict
                    else None
                )
        if job_service is None:
            return None
        from src.learning.execution_controller import LearningExecutionController

        return LearningExecutionController(
            learning_state=self.learning_state,
            job_service=job_service,
        )

    def update_experiment_design(self, experiment_data: dict[str, Any]) -> None:
        """Update the current experiment design from form data.

        PR-LEARN-020: Updated to store variable specs in metadata field.
        """
        # Determine prompt text based on prompt_source
        prompt_text = ""
        prompt_source = experiment_data.get("prompt_source", "custom")
        negative_prompt_text = ""

        if prompt_source == "custom":
            prompt_text = experiment_data.get("custom_prompt", "")
        elif prompt_source == "pack":
            prompt_text = str(experiment_data.get("selected_prompt_text", "") or "")
            negative_prompt_text = str(experiment_data.get("selected_negative_prompt", "") or "")
        elif prompt_source == "current" and self.prompt_workspace_state:
            prompt_text = self.prompt_workspace_state.get_current_prompt_text() or ""
            negative_prompt_text = self.prompt_workspace_state.get_current_negative_text() or ""

        variable_name = experiment_data.get("variable_under_test", "")

        # Build metadata dict with value specifications
        metadata = {
            "study_type": experiment_data.get("study_type", "controlled_variable"),
            "selected_models": list(experiment_data.get("selected_models", []) or []),
            # Numeric range params
            "start_value": experiment_data.get("start_value", 1.0),
            "end_value": experiment_data.get("end_value", 10.0),
            "step_value": experiment_data.get("step_value", 1.0),
            # Discrete/resource selection
            "selected_items": experiment_data.get("selected_items", []),
            # PR-LEARN-022: LoRA composite params
            "lora_mode": experiment_data.get("lora_mode", "strength"),
            "lora_name": experiment_data.get("lora_name"),
            "strength_start": experiment_data.get("strength_start", 0.5),
            "strength_end": experiment_data.get("strength_end", 1.5),
            "strength_step": experiment_data.get("strength_step", 0.1),
            "comparison_mode": experiment_data.get("comparison_mode", False),
            "fixed_strength": experiment_data.get("fixed_strength", 1.0),
            "selected_loras": experiment_data.get("selected_loras", []),
            "prompt_source": prompt_source,
            "selected_prompt_pack_name": experiment_data.get("selected_prompt_pack_name", ""),
            "selected_prompt_pack_path": experiment_data.get("selected_prompt_pack_path", ""),
            "selected_prompt_index": experiment_data.get("selected_prompt_index", 0),
            "selected_prompt_label": experiment_data.get("selected_prompt_label", ""),
            "selected_prompt_negative_text": negative_prompt_text,
            "selected_prompt_loras": list(experiment_data.get("selected_prompt_loras", []) or []),
            "grid": experiment_data.get("grid"),
            **{key: copy.deepcopy(experiment_data.get(key)) for key in ("prompt_slot", "lora_composition", "embedding_experiment", "prompt_model_matrix", "evidence_proposal", "frozen_seed_policy")},
        }

        # Create LearningExperiment from form data
        existing = self.learning_state.current_experiment
        existing_has_controlled_work = any(
            str(getattr(variant, "status", "") or "").lower() not in {"", "pending"}
            or bool(getattr(variant, "job_id", ""))
            or bool(getattr(variant, "image_refs", []))
            for variant in self.learning_state.plan
        )
        if existing_has_controlled_work:
            # The tab persistence listener checkpoints the durable workspace
            # while it still represents the prior controlled experiment.
            self._notify_resume_state_changed()
        experiment = LearningExperiment(
            name=experiment_data.get("name", ""),
            # A display name is editable and may collide; runtime lineage is not.
            experiment_id=(
                uuid.uuid4().hex
                if existing_has_controlled_work
                else str(getattr(existing, "experiment_id", "") or uuid.uuid4().hex)
            ),
            description=experiment_data.get("description", ""),
            # The Learning-owned baseline (never the live Pipeline); empty only if the editor was never used.
            baseline_config=draft_service.config_of(self.learning_state),
            baseline_authoring=draft_service.authoring_of(self.learning_state),
            prompt_text=prompt_text,
            stage=experiment_data.get("stage", "txt2img"),
            input_image_path=str(experiment_data.get("input_image_path", "") or ""),
            variable_under_test=variable_name,
            values=[],  # PR-LEARN-020: Values generated in build_plan()
            images_per_value=experiment_data.get("images_per_value", 1),
            metadata=metadata,  # PR-LEARN-020: Store value specs
        )

        # Store in state
        self.learning_state.current_experiment = experiment
        if existing_has_controlled_work:
            # A new logical experiment never inherits prior variants, artifacts,
            # ratings, or selected review target while its editable form changes.
            self.learning_state.plan = []
            self.learning_state.selected_variant = None
            self.learning_state.selected_image_index = 0
            self._rating_cache = {}
            self._rating_details_cache = {}
        self._set_workflow_state("designing")
        self._notify_resume_state_changed()

    def _generate_values_from_range(self, start: float, end: float, step: float) -> list[float]:
        """Generate list of values from start to end with given step."""
        if step <= 0:
            raise ValueError("The step must be greater than zero")
        return range_values(start, end, step) or []

    def _generate_variant_values(self, experiment: LearningExperiment) -> list[Any]:
        """Generate values using variable metadata.

        PR-LEARN-020: Metadata-driven value generation for all variable types.

        Args:
            experiment: Learning experiment with metadata field containing value specs

        Returns:
            List of values (numeric, strings, or dicts depending on variable type)
        """
        import logging

        from src.learning.variable_metadata import get_variable_metadata
        from src.learning.variable_selection_contract import normalize_resource_entries

        logger = logging.getLogger(__name__)

        # Look up metadata for this variable
        meta = get_variable_metadata(experiment.variable_under_test)
        if not meta:
            raise ValueError(f"Unknown variable: {experiment.variable_under_test}")

        logger.info(
            f"[LearningController] Generating values for {meta.display_name} (type: {meta.value_type})"
        )

        # Generate values based on type
        if meta.value_type == "numeric":
            # Numeric range - use metadata from experiment
            start = float(
                experiment.metadata.get("start_value", meta.constraints.get("default_start", 1.0))
            )
            end = float(
                experiment.metadata.get("end_value", meta.constraints.get("default_end", 10.0))
            )
            step = float(experiment.metadata.get("step_value", meta.constraints.get("step", 1.0)))

            values = self._generate_values_from_range(start, end, step)
            logger.info(
                f"[LearningController]   Generated {len(values)} numeric values: {start} to {end}, step {step}"
            )
            return values

        elif meta.value_type in ["discrete", "resource"]:  # PR-LEARN-021: Handle resource type
            # Discrete choice or resource selection - use selected_items from metadata
            selected = experiment.metadata.get("selected_items", [])

            if not selected and meta.resource_key:
                # Fallback: get available items from app state resources
                available = get_projected_resources(self).get(meta.resource_key, [])
                _, mapping = normalize_resource_entries(list(available or []))
                normalized = list(mapping.values()) if mapping else [str(item) for item in available]
                selected = normalized[:5] if normalized else []  # Use first 5 as fallback
                logger.warning(
                    f"[LearningController]   No items selected, using first {len(selected)} "
                    f"available {meta.resource_key}"
                )

            if not selected:
                raise ValueError(
                    f"No items selected for {meta.display_name}. "
                    "Please select at least one item from the checklist."
                )

            # PR-LEARN-021: Validate resource variables
            if meta.value_type == "resource" and meta.resource_key:
                is_valid, error_msg = self._validate_selected_resources(
                    selected, meta, meta.resource_key
                )
                if not is_valid:
                    raise ValueError(error_msg)

            logger.info(f"[LearningController]   Using {len(selected)} discrete/resource values")
            return selected

        elif meta.value_type == "composite":
            # PR-LEARN-022: Composite variable (LoRA Strength)

            # Determine mode: strength sweep or LoRA comparison
            comparison_mode = experiment.metadata.get("comparison_mode", False)

            if comparison_mode:
                # Mode 2: Compare different LoRAs at fixed strength
                selected_loras = experiment.metadata.get("selected_loras", [])
                fixed_strength = float(experiment.metadata.get("fixed_strength", 1.0))

                if not selected_loras:
                    # Get all enabled LoRAs from stage card
                    available_loras = self._get_current_loras()
                    selected_loras = [entry["name"] for entry in available_loras]

                values = [{"name": lora, "weight": fixed_strength} for lora in selected_loras]
                logger.info(
                    f"[LearningController]   Generated {len(values)} LoRA comparison variants at strength {fixed_strength}"
                )

            else:
                # Mode 1: Test single LoRA at multiple strengths
                lora_name = experiment.metadata.get("lora_name")

                if not lora_name:
                    # Try to get first enabled LoRA
                    available_loras = self._get_current_loras()
                    if available_loras:
                        lora_name = available_loras[0]["name"]
                        logger.warning(
                            f"[LearningController]   No LoRA specified, using first enabled: {lora_name}"
                        )
                    else:
                        raise ValueError("No LoRA specified and no enabled LoRAs in stage card")

                # Generate strength range
                start = float(
                    experiment.metadata.get(
                        "strength_start", meta.constraints.get("min_strength", 0.5)
                    )
                )
                end = float(
                    experiment.metadata.get(
                        "strength_end", meta.constraints.get("max_strength", 1.5)
                    )
                )
                step = float(
                    experiment.metadata.get(
                        "strength_step", meta.constraints.get("default_step", 0.1)
                    )
                )

                strengths = self._generate_values_from_range(start, end, step)

                values = [{"name": lora_name, "weight": s} for s in strengths]
                logger.info(
                    f"[LearningController]   Generated {len(values)} strength variants for {lora_name}"
                )

            return values

        else:
            raise ValueError(f"Unsupported variable type: {meta.value_type}")

    def _build_prompt_workspace_state_from_experiment(self) -> Any | None:
        experiment = self.learning_state.current_experiment
        metadata = dict(getattr(experiment, "metadata", {}) or {})
        if str(metadata.get("prompt_source", "") or "") != "pack":
            return self.prompt_workspace_state

        prompt_text = str(getattr(experiment, "prompt_text", "") or "")
        negative_text = str(metadata.get("selected_prompt_negative_text", "") or "")
        lora_entries = list(metadata.get("selected_prompt_loras") or [])
        slot_loras: list[tuple[str, float]] = []
        for entry in lora_entries:
            if isinstance(entry, dict):
                name = str(entry.get("name", "") or "").strip()
                if not name:
                    continue
                weight = float(entry.get("weight", entry.get("strength", 1.0)) or 1.0)
                slot_loras.append((name, weight))
        slot = SimpleNamespace(text=prompt_text, negative=negative_text, loras=slot_loras)
        return SimpleNamespace(
            get_current_slot=lambda: slot,
            get_current_prompt_text=lambda: prompt_text,
            get_current_negative_text=lambda: negative_text,
            get_current_prompt_metadata=lambda: build_prompt_metadata(
                f"{prompt_text}\n{negative_text}"
            ),
        )

    def _get_current_loras(
        self, *, prompt_workspace_state_override: Any | None = None
    ) -> list[dict[str, Any]]:
        """Get currently selected LoRAs from stage card state.

        PR-LEARN-022: Retrieves enabled LoRAs from baseline config for LoRA variable.

        Returns:
            List of LoRA dicts: [{"name": "...", "strength": ..., "enabled": True}, ...]
        """
        import logging

        from src.learning.lora_variable_service import collect_available_loras

        logger = logging.getLogger(__name__)

        try:
            baseline = self.authoring_baseline()
            app_state = (
                getattr(self.app_controller, "_app_state", None) if self.app_controller else None
            )
            prompt_workspace_state = (
                prompt_workspace_state_override
                or self._build_prompt_workspace_state_from_experiment()
                or self.prompt_workspace_state
            )
            loras = collect_available_loras(
                prompt_workspace_state=prompt_workspace_state,
                app_state=app_state,
                baseline_config=baseline,
            )
            enabled_loras = [entry for entry in loras if entry.get("enabled", True)]

            logger.info(
                f"[LearningController] Found {len(enabled_loras)} enabled LoRAs from runtime/prompt/baseline"
            )
            return enabled_loras
        except Exception as exc:
            logger.error(f"[LearningController] Failed to get current LoRAs: {exc}")
            return []

    def _validate_selected_resources(
        self, selected: list[str], meta, resource_key: str
    ) -> tuple[bool, str]:
        """Validate that selected resources exist in WebUI.

        PR-LEARN-021: Validates resource variables against available resources.

        Args:
            selected: List of selected resource names
            meta: Variable metadata
            resource_key: Resource key in app_state (e.g., "models", "vaes")

        Returns:
            (is_valid, error_message)
        """
        import logging

        logger = logging.getLogger(__name__)

        # Get available resources from app_state
        available = get_projected_resources(self).get(resource_key, [])
        _, mapping = normalize_resource_entries(list(available or []))
        if mapping:
            available = list(mapping.values())
        else:
            available = [str(item) for item in available]

        if not available:
            return (
                False,
                f"No {meta.display_name} available in WebUI. Please check WebUI connection.",
            )

        # Check each selected resource
        missing = []
        for resource in selected:
            if resource not in available:
                missing.append(resource)

        if missing:
            error = f"Selected {meta.display_name} not found in WebUI: {', '.join(missing[:3])}"
            if len(missing) > 3:
                error += f" and {len(missing) - 3} more"
            logger.error(f"[LearningController] Resource validation failed: {error}")
            return False, error

        logger.info(
            f"[LearningController] Resource validation passed: {len(selected)} {meta.display_name} selected"
        )
        return True, ""

    def prepare_model_comparison_evidence(self, models, resources, **kwargs):
        from src.learning.model_evidence_readiness import prepare_comparison_evidence

        return prepare_comparison_evidence(models, resources, **kwargs)

    def build_plan(self, experiment: LearningExperiment, *, comparison_evidence=None) -> None:
        """Build a learning plan from experiment definition.

        PR-LEARN-020: Updated to use metadata-driven value generation.
        """
        import logging

        from src.learning.model_comparison import study_type

        service = controlled_study_service(study_type(experiment))
        if service is not None:
            service.build_plan(self, experiment, **({} if comparison_evidence is None else {"comparison_evidence": comparison_evidence}))
            return
        if study_type(experiment) == "model_comparison":
            self._build_model_comparison_plan(experiment, evidence=comparison_evidence)
            return
        if study_type(experiment) == "two_axis_grid":
            self._build_two_axis_grid_plan(experiment)
            return

        from src.gui.learning_state import LearningVariant

        logger = logging.getLogger(__name__)

        # Store the current experiment
        self.learning_state.current_experiment = experiment
        if not experiment.experiment_id:
            experiment.experiment_id = uuid.uuid4().hex

        # Load existing ratings for this experiment
        self.load_existing_ratings()

        # Clear any existing plan
        self.learning_state.plan = []

        # The Learning-owned baseline this Preview freezes.  Resolved first: value generation reads its LoRAs.
        stage = authoring.require_stage(experiment.stage)
        baseline = self._authored_baseline(experiment)
        draft_signature = authoring.signature(baseline, stage)

        # PR-LEARN-020: Generate values using metadata-driven system
        try:
            values = self._generate_variant_values(experiment)
            experiment.values = values  # Update experiment with generated values
            logger.info(f"[LearningController] Generated {len(values)} variant values")
        except Exception as exc:
            logger.error(f"[LearningController] Failed to generate values: {exc}")
            raise

        # Capture effective settings once at preview.  The runner will compile
        # only from this canonical JSON snapshot, never from live stage cards.
        policy_getter = getattr(self.app_controller, "get_current_global_prompt_policy", None)
        policy = policy_getter() if callable(policy_getter) else None
        if isinstance(policy, dict):
            baseline = apply_global_prompt_policy(baseline, **policy)
        negative_prompt = str(
            getattr(experiment, "metadata", {}).get("selected_prompt_negative_text", "") or ""
        )
        if not negative_prompt and self.prompt_workspace_state and not experiment.metadata.get("evidence_proposal"):
            negative_prompt = self.prompt_workspace_state.get_current_negative_text() or ""
        baseline = freeze_preview_global_policy(baseline)
        prompt_source = freeze_ordinary_prompt_source(dict(experiment.metadata or {}))
        if str(prompt_source.get("prompt_source") or "") == "pack":
            experiment.prompt_text = str(prompt_source["rendered_positive_prompt"])
            negative_prompt = str(prompt_source["rendered_negative_prompt"])
        experiment.metadata.update(prompt_source)
        model_context = validate_experiment(self, experiment, baseline, experiment.values)
        problems = authoring.baseline_problems(
            baseline, stage, input_image_path=experiment.input_image_path,
            resources=get_projected_resources(self),
            fixed_by_policy=authoring.policy_owned(model_context),
        )
        if problems:
            raise ValueError("The Learning baseline is incomplete: " + "; ".join(problems))
        baseline = authoring.finalize_for_stage(baseline, stage)
        experiment.baseline_config = baseline
        prompt_source.update(experiment.metadata)
        preserved_seed_policy = getattr(experiment, "metadata", {}).get("frozen_seed_policy")
        seed_policy = freeze_seed_policy(
            baseline,
            max(1, int(experiment.images_per_value or 1)),
            preserved_policy=(
                preserved_seed_policy if isinstance(preserved_seed_policy, dict) else None
            ),
        )
        # Project every variant through the same derivation Run uses; a tested value that compile policy
        # overwrites refuses the whole experiment here, before anything can be admitted.
        preview_experiment = replace(experiment, execution_snapshot_json="")
        variant_settings = [
            {
                "value": value,
                "settings": authoring.variant_projection(
                    self._variant_config(baseline, preview_experiment, value, seed_policy, True),
                    stage, "", None,
                ),
            }
            for value in experiment.values
        ]
        variable = internal_variable_name(experiment.variable_under_test)
        experiment.execution_snapshot_json = freeze_snapshot(
            ordinary_snapshot(
                experiment, baseline=baseline, negative_prompt=negative_prompt, seed_policy=seed_policy,
                prompt_source=prompt_source, model_context=model_context,
                authored=authored_fields(
                    experiment, baseline, stage, draft_signature=draft_signature, variable=variable,
                    variant_settings=variant_settings,
                ),
            )
        )

        # Generate variants for each value in the experiment
        for value in experiment.values:
            variant = LearningVariant(
                experiment_id=experiment.experiment_id,
                variant_id=f"{experiment.experiment_id}:{len(self.learning_state.plan)}",
                param_value=value,
                status="pending",
                planned_images=experiment.images_per_value,
                completed_images=0,
                image_refs=[],
            )
            self.learning_state.plan.append(variant)

        # Update the plan table if it exists
        if self._plan_table:
            self._update_plan_table()
        self._set_workflow_state("planned")
        self._notify_resume_state_changed()

    def _build_model_comparison_plan(self, experiment: LearningExperiment, *, evidence=None) -> None:
        from src.learning.model_comparison import build_comparison_snapshot
        from src.pipeline.compile_evidence import CompileEvidence

        if not experiment.experiment_id:
            experiment.experiment_id = uuid.uuid4().hex
        baseline = self._authored_baseline(experiment)
        getter = getattr(self.app_controller, "get_current_global_prompt_policy", None)
        policy = getter() if callable(getter) else None
        if isinstance(policy, dict):
            baseline = apply_global_prompt_policy(baseline, **policy)
        snapshot = build_comparison_snapshot(
            experiment, baseline,
            evidence=evidence or CompileEvidence(lora_resolver=getattr(self, "_learning_lora_resolver", None)),
            policy_resolver=getattr(self, "_learning_policy_resolver", None),
        )
        experiment.execution_snapshot_json = freeze_snapshot(snapshot)
        experiment.baseline_config = snapshot["baseline_config"]
        experiment.prompt_text = snapshot["prompt_text"]
        experiment.metadata.update(snapshot["prompt_source"])
        experiment.variable_under_test = snapshot["variable_under_test"]
        experiment.values = list(snapshot["variant_values"])
        self.learning_state.current_experiment = experiment
        self.load_existing_ratings()
        self.learning_state.plan = [LearningVariant(
            experiment_id=experiment.experiment_id, variant_id=f"{experiment.experiment_id}:{index}",
            param_value=value, planned_images=snapshot["images_per_value"],
        ) for index, value in enumerate(experiment.values)]
        self._update_plan_table()
        self._set_workflow_state("planned")
        self._notify_resume_state_changed()

    def _build_two_axis_grid_plan(self, experiment: LearningExperiment) -> None:
        """Freeze the grid through the toolkit-neutral planner; nothing is queued."""
        from src.learning.two_axis_grid import build_grid_snapshot

        if not experiment.experiment_id:
            experiment.experiment_id = uuid.uuid4().hex
        baseline = self._authored_baseline(experiment)
        getter = getattr(self.app_controller, "get_current_global_prompt_policy", None)
        policy = getter() if callable(getter) else None
        if isinstance(policy, dict):
            baseline = apply_global_prompt_policy(baseline, **policy)
        baseline = freeze_preview_global_policy(baseline)
        snapshot = build_grid_snapshot(
            experiment,
            baseline,
            validate_axis=lambda variable, values: self._validate_grid_axis(
                experiment, baseline, variable, values
            ),
            known_loras=self.known_loras,
        )
        experiment.execution_snapshot_json = freeze_snapshot(snapshot)
        self.learning_state.current_experiment = experiment
        self.load_existing_ratings()
        self.learning_state.plan = [
            LearningVariant(
                experiment_id=experiment.experiment_id,
                variant_id=f"{experiment.experiment_id}:{index}",
                param_value=value,
                planned_images=snapshot["images_per_value"],
            )
            for index, value in enumerate(snapshot["variant_values"])
        ]
        self.learning_state.selected_variant = None
        self._update_plan_table()
        self._set_workflow_state("planned")
        self._notify_resume_state_changed()

    def _validate_grid_axis(
        self, experiment: LearningExperiment, baseline: dict[str, Any], variable: str, values: list[Any]
    ) -> dict[str, Any]:
        # The same policy seam ordinary previews use, asked once per axis variable.
        context: dict[str, Any] = validate_experiment(  # type: ignore[no-untyped-call]  # existing unannotated seam
            self, replace(experiment, variable_under_test=variable), baseline, values
        )
        return context

    def known_loras(self) -> list[str]:
        """LoRA names resolved from the current runtime/prompt/baseline evidence (never a filename guess)."""
        names = [str(entry["name"]) for entry in self._get_current_loras() if entry.get("name")]
        available = get_projected_resources(self).get("loras", [])
        _, mapping = normalize_resource_entries(list(available or []))
        names.extend(mapping.values() if mapping else [str(item) for item in available or []])
        return list(dict.fromkeys(names))

    def get_grid_results_model(self, visibility_mode: Any = "nsfw") -> Any:
        """The exact-association projection both the grid view and the contact sheet render."""
        from src.learning.grid_results import build_grid_model

        return build_grid_model(
            self.learning_state.current_experiment,
            self.learning_state.plan,
            self._rating_details_cache,
            visibility_mode=visibility_mode,
        )

    def export_grid_contact_sheet(
        self, destination: str | Path, *, visibility_mode: Any = "nsfw", overwrite: bool = False
    ) -> Any:
        from src.learning.grid_contact_sheet import export_contact_sheet

        return export_contact_sheet(
            self.get_grid_results_model(visibility_mode),
            destination,
            overwrite=overwrite,
            protected_paths=[ref for variant in self.learning_state.plan for ref in variant.image_refs],
        )

    def _refresh_grid_view(self) -> None:
        if self._grid_view is not None:
            self._grid_view.refresh()

    def _update_plan_table(self) -> None:
        """Update the learning plan table with current plan data."""
        if self._plan_table and hasattr(self._plan_table, "update_plan"):
            stage_name = "txt2img"
            if self.learning_state.current_experiment:
                stage_name = str(self.learning_state.current_experiment.stage or "txt2img")
            try:
                self._plan_table.update_plan(self.learning_state.plan, stage_name=stage_name)
            except TypeError:
                # Backward compatibility for older test doubles.
                self._plan_table.update_plan(self.learning_state.plan)
        self._update_variant_ratings()
        self._refresh_grid_view()

    def load_existing_ratings(self) -> None:
        """Load existing ratings for the current experiment."""
        if not self._learning_record_writer:
            return
        if not self.learning_state.current_experiment:
            return

        experiment_id = self.learning_state.current_experiment.experiment_id
        self._rating_cache = self._learning_record_writer.get_ratings_for_experiment(experiment_id)
        self._rating_details_cache = self._learning_record_writer.get_rating_details_for_experiment(
            experiment_id
        )

    def get_rating_for_image(self, image_path: str) -> int | None:
        """Get the rating for an image if it exists."""
        return self._rating_cache.get(image_path)

    def is_image_rated(self, image_path: str) -> bool:
        """Check if an image has been rated."""
        return image_path in self._rating_cache

    def get_rating_details_for_image(self, image_path: str) -> dict[str, Any] | None:
        """Return the complete persisted rating detail for the selected artifact."""
        detail = self._rating_details_cache.get(str(image_path))
        return dict(detail) if isinstance(detail, dict) else None

    def _draft_key(self, image_path: str) -> str:
        experiment_id = str(
            getattr(self.learning_state.current_experiment, "experiment_id", "") or ""
        )
        return f"{experiment_id}:{str(image_path)}"

    def save_review_draft(self, image_path: str, draft: dict[str, Any]) -> None:
        """Persist a resumable UI draft without emitting learning evidence."""
        if self.learning_state.current_experiment is None or not str(image_path or "").strip():
            return
        self.learning_state.review_drafts[self._draft_key(image_path)] = dict(draft or {})
        self._notify_resume_state_changed()

    def get_review_draft(self, image_path: str) -> dict[str, Any] | None:
        draft = self.learning_state.review_drafts.get(self._draft_key(image_path))
        return dict(draft) if isinstance(draft, dict) else None

    def discard_review_draft(self, image_path: str) -> None:
        self.learning_state.review_drafts.pop(self._draft_key(image_path), None)
        self._notify_resume_state_changed()

    def commit_review_drafts(self, image_refs: list[str] | None = None) -> DraftCommitSummary:
        """Save the rated drafts of the open experiment as ratings (all of them, or only ``image_refs``).

        An image that already has a saved rating keeps its draft: replacing a saved rating stays an explicit,
        confirmed Save Rating. Whatever is not saved stays a draft.
        """
        experiment = self.learning_state.current_experiment
        if experiment is None or not self._learning_record_writer:
            return DraftCommitSummary()
        drafts = dict(self.learning_state.review_drafts or {})
        if image_refs is not None:
            wanted = {self._draft_key(ref) for ref in image_refs}
            drafts = {key: value for key, value in drafts.items() if key in wanted}

        def find_variant(ref: str) -> LearningVariant | None:
            return next((v for v in self.learning_state.plan if ref in v.image_refs), None)

        def commit(ref: str, _variant: LearningVariant, rating: Any) -> None:
            self.record_rating(ref, rating.rating, rating.notes, rating.details)

        _remaining, summary = commit_drafts(
            drafts,
            experiment_id=str(experiment.experiment_id),
            find_variant=find_variant,
            is_rated=self.is_image_rated,
            commit=commit,
        )
        return summary

    def commit_review_draft(self, image_ref: str) -> bool:
        """Save one image's rated draft as a rating; ``False`` when it was kept as a draft."""
        return self.commit_review_drafts([image_ref]).committed == 1

    def commit_stored_review_drafts(self, store: Any, *, apply: bool) -> Any:
        """Dry-run or commit the rated drafts in every saved experiment session except the open one."""
        from src.gui.controllers.learning_stored_drafts import commit_stored_drafts

        if not self._learning_record_writer:
            raise RuntimeError("LearningRecordWriter not configured")
        experiment = self.learning_state.current_experiment
        open_ids = {str(experiment.experiment_id)} if experiment is not None else set()
        return commit_stored_drafts(
            store=store,
            writer=self._learning_record_writer,
            build_record=self.build_rating_record,
            open_experiment_ids=open_ids,
            apply=apply,
        )

    def get_review_counts(self) -> dict[str, int]:
        """Return persisted-rating, draft, and unresolved counts for the current plan."""
        refs = [
            str(ref)
            for variant in self.learning_state.plan
            if str(getattr(variant, "status", "") or "").lower() == "completed"
            for ref in list(getattr(variant, "image_refs", []) or [])
        ]
        saved = sum(self.is_image_rated(ref) for ref in refs)
        drafts = sum(not self.is_image_rated(ref) and self.get_review_draft(ref) is not None for ref in refs)
        return {"saved": saved, "draft": drafts, "unrated": max(0, len(refs) - saved - drafts), "total": len(refs)}

    def get_evidence_progress(self) -> EvidenceProgress:
        """Saved controlled ratings of the current experiment against what a recommendation needs."""
        per_value: list[int] = []
        for variant in self.learning_state.plan:
            metadata = dict(getattr(variant, "execution_metadata", {}) or {})
            if metadata.get("controlled_evidence_valid", True) is not True:
                continue
            per_value.append(
                sum(self.is_image_rated(str(ref)) for ref in list(getattr(variant, "image_refs", []) or []))
            )
        return evidence_progress(per_value)

    def new_experiment_draft(self) -> None:
        """Clear only the editable controlled-experiment workspace for a new identity."""
        if self.learning_state.current_experiment is not None:
            self._notify_resume_state_changed()
        self.learning_state.current_experiment = None
        draft_service.clear(self.learning_state)
        self.learning_state.plan = []
        self.learning_state.selected_variant = None
        self.learning_state.selected_image_index = 0
        self._rating_cache = {}
        self._rating_details_cache = {}
        self._set_workflow_state("idle")
        self._notify_resume_state_changed()

    def clone_current_experiment_as_new(self) -> LearningExperiment | None:
        """Copy only editable design fields into a distinct, unsubmitted experiment."""
        current = self.learning_state.current_experiment
        if current is None:
            return None
        self._notify_resume_state_changed()
        clone = LearningExperiment.from_dict(current.to_dict())
        clone.experiment_id = uuid.uuid4().hex
        snapshot_json = str(getattr(current, "execution_snapshot_json", "") or "")
        snapshot = thaw_snapshot(snapshot_json) if snapshot_json else {}
        seed_policy = snapshot.get("seed_policy") if isinstance(snapshot, dict) else None
        if isinstance(seed_policy, dict):
            clone.metadata["frozen_seed_policy"] = dict(seed_policy)
        clone.execution_snapshot_json = ""
        # The clone starts from a copy of the source's own baseline (never the live Pipeline) and is editable.
        source_baseline = snapshot.get("baseline_config") or current.baseline_config
        draft_service.adopt(self.learning_state, source_baseline, None, origin=authoring.ORIGIN_CLONE)
        clone.baseline_config = draft_service.config_of(self.learning_state)
        clone.baseline_authoring = draft_service.authoring_of(self.learning_state)
        clone.values = []
        self.learning_state.current_experiment = clone
        self.learning_state.plan = []
        self.learning_state.selected_variant = None
        self.learning_state.selected_image_index = 0
        self._rating_cache = {}
        self._rating_details_cache = {}
        self._set_workflow_state("designing")
        self._notify_resume_state_changed()
        return clone

    def _update_variant_status(self, variant_index: int, status: str) -> None:
        """Update the status of a specific variant in the table."""
        if self._plan_table and hasattr(self._plan_table, "update_row_status"):
            self._plan_table.update_row_status(variant_index, status)
            detail_update = getattr(self._plan_table, "update_row_detail", None)
            if callable(detail_update) and 0 <= variant_index < len(self.learning_state.plan):
                from src.learning.experiment_reconciliation import variant_status_detail
                detail_update(variant_index, variant_status_detail(self.learning_state.plan[variant_index]))
        self._refresh_grid_view()

    def _update_variant_images(self, variant_index: int, completed: int, planned: int) -> None:
        """Update the image count of a specific variant in the table."""
        if self._plan_table and hasattr(self._plan_table, "update_row_images"):
            self._plan_table.update_row_images(variant_index, completed, planned)
        self._refresh_grid_view()

    def _highlight_variant(self, variant_index: int, highlight: bool = True) -> None:
        """Highlight or unhighlight a specific variant in the table."""
        if self._plan_table and hasattr(self._plan_table, "highlight_row"):
            self._plan_table.highlight_row(variant_index, highlight)

    def _get_variant_index(self, variant: LearningVariant) -> int:
        """Get the index of a variant in the current plan."""
        try:
            return self.learning_state.plan.index(variant)
        except ValueError:
            return -1

    def run_plan(self) -> None:
        """Execute the current learning plan."""
        if not self.learning_state.plan:
            self._set_workflow_state("idle")
            return
        if not self.pipeline_controller:
            self._set_workflow_state("planned")
            return
        if self._plan_table and hasattr(self._plan_table, "clear_highlights"):
            self._plan_table.clear_highlights()
        pending = [variant for variant in self.learning_state.plan if variant.status == "pending" and not variant.job_id]
        if not pending:
            self._recompute_workflow_state_from_plan()
            return
        experiment = self.learning_state.current_experiment
        if experiment is None:
            raise RuntimeError("Learning experiment is unavailable")
        if not self.execution_controller:
            raise RuntimeError("Learning execution controller unavailable")
        admission = self._experiment_admission.compile_all(
            pending, lambda variant: self._build_variant_njr(variant, experiment)
        )
        submit_experiment = getattr(self.execution_controller, "submit_experiment_jobs", None)
        if not callable(submit_experiment):
            raise RuntimeError("Learning batch admission is unavailable")
        for record, variant in zip(admission.records, pending, strict=True):
            self._log_seed_dispatch(record, variant, experiment)
        try:
            returned = submit_experiment(
                admission.records, pending, experiment.name, experiment.variable_under_test
            )
            expected = [record.job_id for record in admission.records]
            if not isinstance(returned, (list, tuple)) or len(returned) != len(expected) or set(returned) != set(expected):
                raise RuntimeError("Learning admission did not confirm the compiled NJR identities")
        except Exception:
            self._update_plan_table()
            self._recompute_workflow_state_from_plan()
            self._notify_resume_state_changed(required=True)
            raise
        for variant, record in zip(pending, admission.records, strict=True):
            variant.job_id = record.job_id
            if variant.status == "pending":
                variant.status = "queued"
        self._update_plan_table()
        self._recompute_workflow_state_from_plan()
        self._notify_resume_state_changed(required=True)

    def _submit_variant_job(self, variant: LearningVariant) -> None:
        """Submit a learning job via LearningExecutionController.

        PR-LEARN-010: Replaces PackJobEntry path with direct NJR building,
        ensuring proper config propagation to run_metadata.json.

        PR-LEARN-011: Enhanced with comprehensive logging.

        PR-LEARN-013: Fixed to delegate to LearningExecutionController so that
        _job_to_variant mapping is populated for callback tracking.
        """
        import logging

        logger = logging.getLogger(__name__)

        if not self.learning_state.current_experiment:
            logger.error("[LearningController] Cannot submit: missing experiment")
            variant.status = "failed"
            return

        experiment = self.learning_state.current_experiment

        # PR-LEARN-011: Log submission attempt
        logger.info(
            f"[LearningController] Submitting variant job: experiment={experiment.name}, variant={variant.param_value}, variable={experiment.variable_under_test}"
        )

        try:
            # PR-LEARN-010: Build NJR directly with explicit config fields
            record = self._build_variant_njr(variant, experiment)
            logger.info(f"[LearningController] Built NJR for variant: {variant.param_value}")
            self._log_seed_dispatch(record, variant, experiment)

            if not self.execution_controller:
                raise RuntimeError("Learning execution controller unavailable")
            success = self.execution_controller.submit_variant_job(
                record=record,
                variant=variant,
                experiment_name=experiment.name,
                variable_under_test=experiment.variable_under_test,
            )

            if success:
                # PR-LEARN-011: Log successful submission
                logger.info(
                    f"[LearningController] ✓ Successfully submitted job via LearningExecutionController: {record.job_id}"
                )
                logger.info(f"[LearningController]   Experiment: {experiment.name}")
                logger.info(
                    f"[LearningController]   Variable: {experiment.variable_under_test} = {variant.param_value}"
                )
                logger.info("[LearningController]   Status: queued")

                # Update variant status
                variant.status = "queued"
                variant_index = self._get_variant_index(variant)
                if variant_index >= 0:
                    self._update_variant_status(variant_index, "queued")
                    self._highlight_variant(variant_index, True)
            else:
                raise RuntimeError(
                    "LearningExecutionController.submit_variant_job() returned False"
                )

        except Exception as exc:
            logger.exception(f"[LearningController] Error submitting variant job: {exc}")
            variant_index = self._get_variant_index(variant)
            if self._admission_unresolved(variant):
                # The admission response was lost but the job may exist: keep the status the
                # execution controller recorded (requires_attention, or what reconciliation found)
                # and its job identity.  "failed" here would invite a retry and a duplicate job.
                if variant_index >= 0:
                    self._update_variant_status(variant_index, variant.status)
                return
            variant.status = "failed"
            if variant_index >= 0:
                self._update_variant_status(variant_index, "failed")

    @staticmethod
    def _admission_unresolved(variant: LearningVariant) -> bool:
        """True when a failed submit may still have admitted the job (it kept an identity or evidence).

        A definite rejection clears the variant's job id and records no admission error."""

        return bool(
            variant.job_id
            or variant.status == "requires_attention"
            or variant.execution_metadata.get("admission_error")
        )

    @staticmethod
    def _log_seed_dispatch(
        record: Any, variant: LearningVariant, experiment: LearningExperiment
    ) -> None:
        """Log bounded frozen seed inputs for one controlled dispatch."""

        import logging

        logger = logging.getLogger(__name__)
        snapshot_json = str(getattr(experiment, "execution_snapshot_json", "") or "")
        snapshot = thaw_snapshot(snapshot_json) if snapshot_json else {}
        policy = snapshot.get("seed_policy") if isinstance(snapshot, dict) else {}
        policy = policy if isinstance(policy, dict) else {}
        logger.info(
            "Learning seed dispatch: experiment=%s variant=%s requested=%s samples=%s",
            getattr(experiment, "experiment_id", ""),
            getattr(variant, "variant_id", "") or getattr(variant, "param_value", ""),
            getattr(record, "seed", None),
            policy.get("requested_sample_count", getattr(experiment, "images_per_value", 1)),
        )

    def _build_variant_njr(
        self, variant: LearningVariant, experiment: LearningExperiment
    ) -> NormalizedJobRecord:
        """Compile one variant of a frozen experiment into the canonical NJR.

        Only the frozen snapshot is read here: never a stage card, never the live Pipeline.  The construction
        itself lives in ``src/learning/ordinary_njr.py``.
        """
        # Direct programmatic callers may bypass the Preview button.  Give
        # them the same stable identity rather than falling back to a name.
        if not experiment.experiment_id:
            experiment.experiment_id = uuid.uuid4().hex
        if not variant.experiment_id:
            variant.experiment_id = experiment.experiment_id
        if not variant.variant_id:
            variant.variant_id = f"{experiment.experiment_id}:{self._get_variant_index(variant)}"

        # A plan created by Build Preview has a canonical serialized baseline.
        snapshot_json = str(getattr(experiment, "execution_snapshot_json", "") or "")
        snapshot = thaw_snapshot(snapshot_json) if snapshot_json else {}
        experiment = frozen_definition(experiment)
        from src.learning.model_comparison import materialize_njr, study_type

        service = controlled_study_service(study_type(experiment))
        if service is not None:
            return service.build_variant(self, experiment, variant)
        if study_type(experiment) == "two_axis_grid":
            from src.learning.two_axis_grid import materialize_njr as materialize_grid_njr

            return materialize_grid_njr(
                snapshot, variant,
                metadata_factory=lambda config: self._build_learning_metadata(
                    experiment=experiment, variant=variant, stage_name="txt2img", final_config=config),
                output_dir=self._resolve_learning_output_dir(snapshot.get("baseline_config") or {}),
                filename_template=self._resolve_learning_filename_template(snapshot.get("baseline_config") or {}),
            )
        if study_type(experiment) == "model_comparison":
            return materialize_njr(
                snapshot, variant,
                metadata_factory=lambda config: self._build_learning_metadata(
                    experiment=experiment, variant=variant, stage_name="txt2img", final_config=config),
                output_dir=self._resolve_learning_output_dir(snapshot.get("baseline_config") or {}),
                filename_template=self._resolve_learning_filename_template(snapshot.get("baseline_config") or {}),
            )
        validate_ordinary_prompt_snapshot(snapshot)
        if snapshot and snapshot.get("model_policy_context") and variant.param_value not in experiment.values:
            raise ValueError("Variant is outside the frozen experiment values")
        strict = authoring.has_authoring(snapshot)
        baseline = dict(snapshot.get("baseline_config") or experiment.baseline_config or {})
        if not baseline:
            raise ValueError("The experiment has no frozen baseline. Build Preview before Run.")
        model_context = validate_experiment(self, experiment, baseline, [variant.param_value],
                                            frozen_context=snapshot.get("model_policy_context"))
        if not has_frozen_global_prompt_policy(baseline):
            policy_getter = getattr(self.app_controller, "get_current_global_prompt_policy", None)
            policy = policy_getter() if callable(policy_getter) else None
            if isinstance(policy, dict):
                baseline = apply_global_prompt_policy(baseline, **policy)
            baseline = freeze_preview_global_policy(baseline)

        if not strict:
            # Legacy snapshots (frozen before independent baselines) keep their historical validation.
            is_valid, error_msg = self._validate_baseline_config(baseline)
            if not is_valid:
                raise ValueError(f"Invalid baseline config: {error_msg}")

        frozen_seed_policy = snapshot.get("seed_policy") if isinstance(snapshot, dict) else None
        if not isinstance(frozen_seed_policy, dict):
            # Compatibility for programmatic callers that construct a legacy
            # experiment without first pressing Build Preview.  Freeze once on
            # the experiment object; do not mutate or re-read a stage card.
            frozen_seed_policy = freeze_seed_policy(
                baseline, max(1, int(experiment.images_per_value or 1))
            )
            snapshot = ordinary_snapshot(
                experiment, baseline=baseline, negative_prompt="", seed_policy=frozen_seed_policy,
                prompt_source=dict(getattr(experiment, "metadata", {}) or {}), model_context=model_context,
            )
            snapshot_json = freeze_snapshot(snapshot)
            experiment.execution_snapshot_json = snapshot_json

        final_config = self._variant_config(baseline, experiment, variant.param_value, frozen_seed_policy, strict)
        stage_name = str(experiment.stage or "txt2img").strip().lower() or "txt2img"
        expected: dict[str, Any] | None = None
        if strict:
            expected = authoring.variant_projection(final_config, stage_name, "", None)
            frozen = next(
                (
                    entry for entry in snapshot.get("variant_effective_settings") or []
                    if isinstance(entry, dict) and entry.get("value") == variant.param_value
                ),
                None,
            )
            if frozen is None:
                raise ValueError("The Preview did not record this variant. Rebuild Preview before Run.")
            drift = authoring.parity_mismatches(frozen.get("settings") or {}, expected)
            if drift:
                raise ValueError("This variant no longer matches its Preview: " + "; ".join(drift))

        # Add learning context metadata
        final_config["learning_experiment_id"] = experiment.experiment_id
        final_config["learning_variant_value"] = variant.param_value
        final_config["learning_variable"] = experiment.variable_under_test
        output_dir = self._resolve_learning_output_dir(final_config)
        filename_template = self._resolve_learning_filename_template(final_config)
        variant_index = max(0, self._get_variant_index(variant))
        variant_total = max(1, len(self.learning_state.plan) or len(experiment.values) or 1)

        # The frozen prompt; only a legacy snapshot may fall back to the current prompt workspace.
        prompt = str(snapshot.get("prompt_text") or experiment.prompt_text)
        if not prompt and not strict:
            if self.prompt_workspace_state:
                prompt = self.prompt_workspace_state.get_current_prompt_text() or ""
            if not prompt:
                prompt = "a test prompt"
        negative_prompt = frozen_negative_prompt(snapshot, experiment)
        if not snapshot_json and not negative_prompt and self.prompt_workspace_state:
            negative_prompt = self.prompt_workspace_state.get_current_negative_text() or ""
        if not negative_prompt_supported(self, final_config, experiment.stage):
            negative_prompt = ""

        job_id = f"learning_{experiment.experiment_id}_{variant.variant_id or variant.param_value}_{uuid.uuid4().hex[:8]}"
        selected_loras: dict[str, LoRATag] = {}
        for entry in list(getattr(experiment, "metadata", {}).get("selected_prompt_loras") or []):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "") or "").strip()
            if name:
                selected_loras[name] = LoRATag(
                    name=name,
                    weight=float(entry.get("weight", entry.get("strength", 1.0)) or 1.0),
                )
        lora_override = final_config.get("lora_override")
        if isinstance(lora_override, dict):
            lora_name = str(lora_override["name"])
            lora_weight = float(lora_override["weight"])
            # The executable prompt is the LoRA authority: rewrite it before the
            # NJR is frozen, then prove the result before admission.
            baseline_prompt = prompt
            prompt = apply_lora_variant(baseline_prompt, lora_name, lora_weight)
            reason = validate_lora_variant(
                prompt, lora_name, lora_weight, baseline_prompt=baseline_prompt
            )
            if reason:
                raise ValueError(f"LoRA variant {lora_name}@{lora_weight} rejected: {reason}")
            selected_loras = {
                k: v for k, v in selected_loras.items() if k.casefold() != lora_name.casefold()
            }
            if lora_weight > 0:
                selected_loras[lora_name] = LoRATag(name=lora_name, weight=lora_weight)

        apply_executor_base_prompts(final_config, prompt, negative_prompt, stage_name)
        learning_metadata = self._build_learning_metadata(
            experiment=experiment, variant=variant, stage_name=stage_name, final_config=final_config,
        )
        variant.executed_config = copy.deepcopy(final_config)
        return materialize_ordinary_njr(
            final_config=final_config,
            experiment=experiment,
            variant=variant,
            prompt=prompt,
            negative_prompt=negative_prompt,
            learning_metadata=learning_metadata,
            job_id=job_id,
            variant_index=variant_index,
            variant_total=variant_total,
            selected_loras=selected_loras,
            output_dir=output_dir,
            filename_template=filename_template,
            strict=strict,
            source_identity=snapshot.get("input_image") if strict else None,
            expected=expected,
        )

    def _variant_config(
        self, baseline: dict[str, Any], experiment: LearningExperiment, value: Any,
        seed_policy: dict[str, Any], strict: bool,
    ) -> dict[str, Any]:
        """The one place a variant's effective configuration is derived (Preview projects it, Run compiles it)."""
        final_config = copy.deepcopy(baseline)
        self._apply_variant_override_with_metadata(final_config, value, experiment)
        if strict:
            authoring.align_aliases(final_config, authoring.require_stage(experiment.stage))
        compile_variant(final_config, experiment)
        apply_frozen_seed_policy(final_config, seed_policy)
        return final_config

    def _resolve_learning_output_dir(self, config: dict[str, Any]) -> str:
        pipeline_cfg = config.get("pipeline", {})
        if not isinstance(pipeline_cfg, dict):
            return ""
        output_dir = pipeline_cfg.get("path_output_dir") or pipeline_cfg.get("output_dir") or ""
        return str(output_dir or "")

    def _resolve_learning_filename_template(self, config: dict[str, Any]) -> str:
        pipeline_cfg = config.get("pipeline", {})
        if not isinstance(pipeline_cfg, dict):
            return "{seed}"
        template = pipeline_cfg.get("filename_template") or "{seed}"
        return str(template or "{seed}")

    def _build_learning_metadata(
        self,
        *,
        experiment: LearningExperiment,
        variant: LearningVariant,
        stage_name: str,
        final_config: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_json = str(getattr(experiment, "execution_snapshot_json", "") or "")
        snapshot = thaw_snapshot(snapshot_json) if snapshot_json else {}
        return {
            "submission_source": "learning",
            "learning_enabled": True,
            "learning_experiment": experiment.experiment_id,
            "learning_experiment_id": experiment.experiment_id,
            "learning_variable": experiment.variable_under_test,
            "learning_variant_value": variant.param_value,
            "learning_stage": stage_name,
            "learning": {
                "schema": "stablenew.learning.v2.6",
                "experiment_name": experiment.name,
                "experiment_id": experiment.experiment_id,
                "variant_id": variant.variant_id,
                "variable_under_test": experiment.variable_under_test,
                "variant_value": variant.param_value,
                "stage": stage_name,
                "images_per_value": max(1, int(experiment.images_per_value or 1)),
                "seed_policy": dict(snapshot.get("seed_policy") or {}),
                "prompt_source": dict(snapshot.get("prompt_source") or {}),
                "experiment_timestamp": str(snapshot.get("experiment_timestamp") or ""),
                "config": final_config,
            },
            "frozen_experiment": {
                "schema_version": 1,
                "experiment_id": experiment.experiment_id,
                "variant_id": variant.variant_id,
                "snapshot_sha256": snapshot_digest(snapshot_json) if snapshot_json else "",
                "snapshot": thaw_snapshot(snapshot_json) if snapshot_json else {},
                "executed_config": final_config,
            },
        }

    def _validate_baseline_config(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Validate baseline config structure and required fields.

        PR-LEARN-011: Validates config before NJR construction.

        Returns:
            (is_valid, error_message)
        """
        import logging

        logger = logging.getLogger(__name__)

        # Check top-level structure
        if not config:
            return False, "Baseline config is empty"

        if "txt2img" not in config:
            return False, "Baseline config missing 'txt2img' section"

        if "pipeline" not in config:
            logger.warning(
                "[LearningController] Baseline config missing 'pipeline' section, will use defaults"
            )

        # Validate txt2img section
        is_valid, error = self._validate_txt2img_config(config["txt2img"])
        if not is_valid:
            return False, f"txt2img validation failed: {error}"

        return True, ""

    def _validate_txt2img_config(self, txt2img: dict[str, Any]) -> tuple[bool, str]:
        """Validate txt2img config has all required fields.

        PR-LEARN-011: Validates required fields before NJR construction.

        Returns:
            (is_valid, error_message)
        """
        # Required fields - VAE is optional for models with baked VAE
        required_fields = {
            "model": "Model name",
            "sampler_name": "Sampler name",
            "scheduler": "Scheduler name",
            "steps": "Steps count",
            "cfg_scale": "CFG scale",
            "width": "Image width",
            "height": "Image height",
        }

        missing = []
        empty = []

        for field, description in required_fields.items():
            if field not in txt2img:
                missing.append(description)
            elif not txt2img[field]:
                empty.append(description)

        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"

        if empty:
            return False, f"Empty required fields: {', '.join(empty)}"

        return True, ""

    def _log_baseline_config(self, config: dict[str, Any], source: str = "unknown") -> None:
        """Log baseline config details for debugging.

        PR-LEARN-011: Provides diagnostic output for config issues.

        Args:
            config: The baseline config dict
            source: Where the config came from (e.g., "stage_cards", "fallback")
        """
        import logging

        logger = logging.getLogger(__name__)

        logger.info(f"[LearningController] Baseline config from {source}")
        logger.info(f"[LearningController]   Top-level keys: {list(config.keys())}")

        if "txt2img" in config:
            txt2img = config["txt2img"]
            logger.info(f"[LearningController]   txt2img keys: {list(txt2img.keys())}")
            logger.info(f"[LearningController]   model: {txt2img.get('model', 'MISSING')}")
            logger.info(f"[LearningController]   vae: {txt2img.get('vae', 'MISSING')}")
            logger.info(
                f"[LearningController]   sampler_name: {txt2img.get('sampler_name', 'MISSING')}"
            )
            logger.info(f"[LearningController]   scheduler: {txt2img.get('scheduler', 'MISSING')}")
            logger.info(f"[LearningController]   steps: {txt2img.get('steps', 'MISSING')}")
            logger.info(f"[LearningController]   cfg_scale: {txt2img.get('cfg_scale', 'MISSING')}")
            logger.info(f"[LearningController]   seed: {txt2img.get('seed', 'MISSING')}")
        else:
            logger.error("[LearningController]   txt2img section MISSING")

        if "pipeline" in config:
            pipeline = config["pipeline"]
            logger.info(f"[LearningController]   pipeline keys: {list(pipeline.keys())}")
            logger.info(
                f"[LearningController]   batch_size: {pipeline.get('batch_size', 'MISSING')}"
            )
        else:
            logger.warning("[LearningController]   pipeline section MISSING")

    # -- the Learning-owned baseline -----------------------------------------------------------------------
    # Learning authors its own experiment baseline.  The Pipeline's settings are read only by
    # ``copy_pipeline_settings`` (and the one-time seed in ``_authored_baseline``); nothing stays linked.

    def authoring_baseline(self) -> dict[str, Any]:
        """An isolated copy of the editable Learning baseline (empty until one is authored or copied)."""
        return draft_service.config_of(self.learning_state)

    def baseline_authoring_record(self) -> dict[str, Any]:
        return draft_service.authoring_of(self.learning_state)

    def pipeline_settings_available(self) -> bool:
        """True when the Pipeline currently offers settings that a copy could import."""
        try:
            config = self._get_baseline_config()
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
            return False
        return bool((config.get("txt2img") or {}).get("model"))

    def copy_pipeline_settings(self, stage: str = "txt2img") -> dict[str, Any]:
        """Explicitly replace the editable baseline with a one-time copy of the Pipeline's settings."""
        record = draft_service.copy_from_pipeline(self.learning_state, self._get_baseline_config(), stage)
        self._notify_resume_state_changed()
        return record

    def ensure_baseline(self, stage: str = "txt2img") -> bool:
        """Seed a brand-new experiment's baseline from the Pipeline once.  Never touches an open experiment."""
        if draft_service.has_draft(self.learning_state) or self.learning_state.current_experiment is not None:
            return False
        if not self.pipeline_settings_available():
            return False
        draft_service.copy_from_pipeline(self.learning_state, self._get_baseline_config(), stage)
        return True

    def update_baseline_field(self, stage: str, name: str, value: Any) -> Any:
        """Edit one Learning-owned setting; the Pipeline is never touched."""
        return draft_service.edit_field(self.learning_state, stage, name, value)

    def baseline_blockers(self, stage: str, input_image_path: str = "") -> list[str]:
        """What stops the current Learning baseline from defining an executable experiment."""
        baseline = self.authoring_baseline()
        owned: frozenset[str] = frozenset()
        model = selected_model(baseline, stage)
        if model:
            owned = authoring.policy_owned(policy_context(resolve_policy(model, self, baseline), model, stage))
        return authoring.baseline_problems(
            baseline, stage, input_image_path=input_image_path, resources=get_projected_resources(self),
            fixed_by_policy=owned,
        )

    def _authored_baseline(self, experiment: LearningExperiment) -> dict[str, Any]:
        """The Learning baseline a Preview freezes.  The Pipeline is consulted only to seed an empty one, once."""
        baseline = copy.deepcopy(dict(experiment.baseline_config or {}))
        if baseline:
            if not experiment.baseline_authoring:
                experiment.baseline_authoring = authoring.new_authoring(
                    authoring.ORIGIN_LEGACY, source="experiment"
                )
            if not draft_service.has_draft(self.learning_state):
                draft_service.adopt(self.learning_state, baseline, experiment.baseline_authoring)
            return baseline
        baseline = draft_service.config_of(self.learning_state)
        if not baseline:
            # Nobody opened the editor (programmatic caller): the same explicit one-time copy, origin recorded.
            draft_service.copy_from_pipeline(self.learning_state, self._get_baseline_config(), experiment.stage)
            baseline = draft_service.config_of(self.learning_state)
        experiment.baseline_authoring = draft_service.authoring_of(self.learning_state)
        return baseline

    def _get_baseline_config(self) -> dict[str, Any]:
        """Read the Pipeline's current settings.

        This is the Pipeline-facing read behind ``copy_pipeline_settings``, the Apply-to-Pipeline checks and the
        staged-curation presets.  It is never an authoring source for a Learning experiment's Preview or Run.

        BUGFIX: Get the full nested config structure from stage cards,
        not just the app_state.current_config which may have empty model/VAE.

        PR-LEARN-011: Enhanced with logging.
        """
        import logging

        logger = logging.getLogger(__name__)

        baseline = {}

        # Try to get full config from app_controller's stage cards
        if self.app_controller and hasattr(self.app_controller, "_get_stage_cards_panel"):
            try:
                stage_panel = self.app_controller._get_stage_cards_panel()
                if stage_panel:
                    card_names = ("txt2img_card", "img2img_card", "adetailer_card", "upscale_card")
                    merged_config: dict[str, Any] = {}
                    for card_name in card_names:
                        card = getattr(stage_panel, card_name, None)
                        to_config_dict = getattr(card, "to_config_dict", None)
                        if not callable(to_config_dict):
                            continue
                        card_config = to_config_dict() or {}
                        if not isinstance(card_config, dict):
                            continue
                        for key, value in card_config.items():
                            if key in {
                                "txt2img",
                                "img2img",
                                "adetailer",
                                "upscale",
                                "pipeline",
                            } and isinstance(value, dict):
                                merged_config.setdefault(key, {}).update(value)
                            elif key not in merged_config:
                                merged_config[key] = value
                    txt2img_section = merged_config.get("txt2img", {})
                    logger.info(
                        f"[LearningController] Got stage card config: keys={list(merged_config.keys())}"
                    )
                    logger.info(
                        f"[LearningController] txt2img section keys: {list(txt2img_section.keys())}"
                    )
                    logger.info(
                        f"[LearningController] txt2img model={txt2img_section.get('model')}, vae={txt2img_section.get('vae')}"
                    )

                    # BUGFIX: Accept config if model exists (VAE can be empty for baked VAE models)
                    if txt2img_section.get("model") or txt2img_section.get("model_name"):
                        baseline = merged_config

                        # PR-LEARN-011: Log successful config retrieval
                        self._log_baseline_config(baseline, source="stage_cards")

                        # BUGFIX: Ensure subseed parameters are present in txt2img section
                        if "txt2img" not in baseline:
                            baseline["txt2img"] = {}
                        if "subseed" not in baseline["txt2img"]:
                            baseline["txt2img"]["subseed"] = -1
                        if "subseed_strength" not in baseline["txt2img"]:
                            baseline["txt2img"]["subseed_strength"] = 0.0
                        if "seed_resize_from_h" not in baseline["txt2img"]:
                            baseline["txt2img"]["seed_resize_from_h"] = 0
                        if "seed_resize_from_w" not in baseline["txt2img"]:
                            baseline["txt2img"]["seed_resize_from_w"] = 0

                        # Ensure pipeline section exists
                        if "pipeline" not in baseline:
                            baseline["pipeline"] = {
                                "batch_size": 1,
                                "txt2img_enabled": True,
                                "img2img_enabled": False,
                                "adetailer_enabled": False,
                                "upscale_enabled": False,
                            }
                        logger.info(
                            "[LearningController] Successfully loaded baseline config from stage cards"
                        )
                        return baseline
                    logger.warning("[LearningController] Stage card has no model/VAE, falling back")
            except Exception as exc:
                logger.exception(f"[LearningController] Failed to get stage card config: {exc}")
        else:
            logger.warning(
                "[LearningController] No app_controller or _get_stage_cards_panel method"
            )

        # Fallback: Try to get config from app_state
        logger.warning("[LearningController] Using fallback baseline config")
        app_state = (
            getattr(self.pipeline_controller, "_app_state", None)
            if self.pipeline_controller
            else None
        )
        if app_state and hasattr(app_state, "current_config"):
            current_config = app_state.current_config
            # Build nested config structure
            baseline = {
                "txt2img": {
                    "model": getattr(current_config, "model_name", ""),
                    "vae": getattr(current_config, "vae_name", ""),
                    "sampler_name": getattr(current_config, "sampler_name", "Euler a"),
                    "scheduler": getattr(current_config, "scheduler_name", "normal"),
                    "steps": getattr(current_config, "steps", 20),
                    "cfg_scale": getattr(current_config, "cfg_scale", 7.0),
                    "width": getattr(current_config, "width", 512),
                    "height": getattr(current_config, "height", 512),
                    "seed": getattr(current_config, "seed", -1),
                    "subseed": -1,
                    "subseed_strength": 0.0,
                    "seed_resize_from_h": 0,
                    "seed_resize_from_w": 0,
                    "clip_skip": getattr(current_config, "clip_skip", 2),
                },
                "pipeline": {
                    "batch_size": getattr(current_config, "batch_size", 1),
                    "txt2img_enabled": True,
                    "img2img_enabled": False,
                    "adetailer_enabled": False,
                    "upscale_enabled": False,
                },
                "upscale": {
                    "upscaler": "R-ESRGAN 4x+",
                    "upscaling_resize": 2.0,
                    "upscale_mode": "single",
                    "denoising_strength": 0.35,
                    "steps": 20,
                },
            }

        return baseline

    def _build_stage_flags_for_experiment(self, experiment: LearningExperiment) -> dict[str, bool]:
        """Build stage flags based on experiment stage."""
        stage = experiment.stage.lower()

        return {
            "txt2img": stage == "txt2img" or stage == "txt2img_enabled",
            "img2img": stage == "img2img" or stage == "img2img_enabled",
            "adetailer": stage == "adetailer" or stage == "adetailer_enabled",
            "upscale": stage == "upscale" or stage == "upscale_enabled",
            "refiner": False,
            "hires": False,
        }

    def _build_variant_overrides(
        self, variant: LearningVariant, experiment: LearningExperiment
    ) -> dict[str, Any]:
        """Build pipeline overrides for a learning variant.

        Returns a dict with the parameter name and value.
        The _apply_overrides_to_config method will place it in the correct config section.
        """
        overrides = {}

        # Apply the variable under test
        variable = experiment.variable_under_test
        value = variant.param_value

        if variable == "CFG Scale":
            overrides["cfg_scale"] = float(value)
        elif variable == "Steps":
            overrides["steps"] = int(value)
        elif variable == "Sampler":
            overrides["sampler_name"] = str(value)
        elif variable == "Scheduler":
            overrides["scheduler"] = str(value)
        elif variable.startswith("LoRA Strength"):
            # For LoRA strength, we'd need to handle this differently
            # For now, just store the value
            overrides["lora_strength"] = float(value)
        elif variable == "Denoise Strength":
            overrides["denoising_strength"] = float(value)
        elif variable == "Upscale Factor":
            overrides["upscaling_resize"] = float(value)

        # Add learning context metadata
        overrides["learning_experiment_id"] = experiment.name
        overrides["learning_variant_value"] = value
        overrides["learning_variable"] = variable

        return overrides

    def _apply_overrides_to_config(
        self,
        baseline_config: dict[str, Any],
        overrides: dict[str, Any],
        experiment: LearningExperiment,
    ) -> dict[str, Any]:
        """Apply variant overrides to the correct nested config sections.

        BUGFIX: Overrides must be applied to txt2img/upscale/etc sections,
        not at the top level, for the builder to use them correctly.
        """
        import copy

        config = copy.deepcopy(baseline_config)

        # Determine which stage section to apply overrides to
        stage = experiment.stage.lower()
        if stage == "txt2img" or stage == "txt2img_enabled":
            stage_key = "txt2img"
        elif stage == "img2img" or stage == "img2img_enabled":
            stage_key = "img2img"
        elif stage == "upscale" or stage == "upscale_enabled":
            stage_key = "upscale"
        elif stage == "adetailer" or stage == "adetailer_enabled":
            stage_key = "adetailer"
        else:
            stage_key = "txt2img"  # Default

        # Ensure stage section exists
        if stage_key not in config:
            config[stage_key] = {}

        # Apply parameter overrides to the stage section
        for key, value in overrides.items():
            # Skip learning metadata - those go at top level
            if key.startswith("learning_"):
                config[key] = value
            else:
                # Apply to stage section
                config[stage_key][key] = value

        return config

    def _apply_variant_override_with_metadata(
        self, config: dict[str, Any], value: Any, experiment: LearningExperiment
    ) -> None:
        """Apply variant override using metadata config_path.

        PR-LEARN-020: Metadata-driven override application.
        PR-LEARN-022: Special handling for composite LoRA variables.

        Args:
            config: Config dict to modify (in-place)
            value: The variant value to apply
            experiment: Current experiment for context
        """
        import logging

        from src.learning.variable_metadata import get_variable_metadata

        logger = logging.getLogger(__name__)

        # Get metadata for variable
        meta = get_variable_metadata(experiment.variable_under_test)
        if not meta:
            logger.error(
                f"[LearningController] No metadata for variable: {experiment.variable_under_test}"
            )
            return

        # PR-LEARN-022: Special handling for composite LoRA variable
        if meta.value_type == "composite" and isinstance(value, dict):
            # value = {"name": "CharacterLoRA", "weight": 0.8}
            # Store in lora_override for later NJR application
            config.setdefault("lora_override", {}).update(value)
            logger.info(
                f"[LearningController] Applied LoRA override: {value['name']} @ {value['weight']}"
            )
            return

        # Standard config path application
        # Parse config_path (e.g., "txt2img.cfg_scale" -> ["txt2img", "cfg_scale"])
        keys = meta.config_path.split(".")
        stage_name = str(experiment.stage or "txt2img").strip().lower() or "txt2img"
        if keys and keys[0] == "txt2img" and stage_name in {"img2img", "adetailer"}:
            keys[0] = stage_name
        elif keys and meta.name in {"model", "vae"} and stage_name == "upscale":
            keys[0] = "upscale"

        # Navigate to parent dict
        target = config
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]

        # Set the final value
        final_key = keys[-1]
        target[final_key] = value
        logger.info(f"[LearningController] Applied override: {meta.config_path} = {value}")

    def _on_variant_job_completed(self, variant: LearningVariant, result: dict[str, Any]) -> None:
        """Direct completion seam: stage evidence, then render its final projection."""
        self._apply_variant_completion_evidence(variant, result)
        self._on_variant_completion_published(variant, result)

    def _apply_variant_completion_evidence(self, variant: LearningVariant, result: dict[str, Any]) -> None:
        """Handle completion of a variant job.

        PR-LEARN-004: Updates variant status and refreshes UI table.
        PR-LEARN-005: Extracts and links output images to variant.
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(f"Variant {variant.param_value} completed")

        from src.learning.experiment_reconciliation import completion_evidence

        experiment = self.learning_state.current_experiment
        evidence = completion_evidence(experiment, variant, result)
        variant.status = evidence.status
        variant.execution_metadata = evidence.execution_metadata
        if experiment is not None and evidence.experiment_metadata is not None:
            experiment.metadata = evidence.experiment_metadata

    def _on_variant_completion_published(self, variant: LearningVariant, result: dict[str, Any]) -> None:
        """Render and checkpoint only after the execution owner publishes safe evidence."""
        # PR-LEARN-005: Extract image references from result
        image_paths = []
        if isinstance(result, dict):
            # Try multiple possible result structures
            if "images" in result:
                image_paths.extend(result["images"])
            elif "output_paths" in result:
                image_paths.extend(result["output_paths"])
            elif "image_paths" in result:
                image_paths.extend(result["image_paths"])

        # Add image references to variant
        for image_path in image_paths:
            if image_path and image_path not in variant.image_refs:
                variant.image_refs.append(image_path)
        variant.completed_images = max(variant.completed_images, len(variant.image_refs))

        # PR-LEARN-004: Update UI with live updates
        variant_index = self._get_variant_index(variant)
        if variant_index >= 0:
            self._update_variant_status(variant_index, variant.status)
            self._update_variant_images(
                variant_index, variant.completed_images, variant.planned_images
            )
            self._highlight_variant(variant_index, False)  # Remove highlight

        # Background completion refreshes data only.  It may repaint review
        # only when the operator is already reviewing this exact variant.
        if (
            self.learning_state.selected_variant is variant
            and self._review_panel
            and hasattr(self._review_panel, "display_variant_results")
        ):
            self._review_panel.display_variant_results(
                variant, self.learning_state.current_experiment
            )
        self._recompute_workflow_state_from_plan()
        self._notify_resume_state_changed()

    def _on_variant_job_failed(self, variant: LearningVariant, error: Exception) -> None:
        """Handle failure of a variant job."""
        variant.status = "cancelled" if variant.status == "cancelled" else "failed"

        # Update UI with live updates
        variant_index = self._get_variant_index(variant)
        if variant_index >= 0:
            self._update_variant_status(variant_index, variant.status)
            self._highlight_variant(variant_index, False)  # Remove highlight
        self._recompute_workflow_state_from_plan()
        self._notify_resume_state_changed()

    def add_workflow_state_listener(self, listener: Any) -> None:
        if listener not in self._workflow_state_listeners:
            self._workflow_state_listeners.append(listener)

    def add_resume_state_listener(self, listener: Any) -> None:
        if listener not in self._resume_state_listeners:
            self._resume_state_listeners.append(listener)

    def _notify_resume_state_changed(self, *, required: bool = False) -> None:
        failure = ""
        for listener in list(self._resume_state_listeners):
            try:
                if listener() is False:
                    raise RuntimeError("resume state store rejected the checkpoint")
            except Exception as exc:
                failure = str(exc)
        experiment = self.learning_state.current_experiment
        if experiment is not None:
            if failure:
                experiment.metadata["resume_persistence_error"] = failure
                self._set_workflow_state("action_required")
            else:
                experiment.metadata.pop("resume_persistence_error", None)
        if required and failure:
            raise RuntimeError(f"Jobs may already be admitted; resume checkpoint failed: {failure}. Do not retry.")

    def get_workflow_state(self) -> str:
        return self._workflow_state

    def _set_workflow_state(self, state: str) -> None:
        next_state = str(state or "idle").strip().lower() or "idle"
        if next_state == self._workflow_state:
            return
        self._workflow_state = next_state
        for listener in list(self._workflow_state_listeners):
            try:
                listener(self._workflow_state)
            except Exception:
                continue

    def _recompute_workflow_state_from_plan(self) -> None:
        plan = list(self.learning_state.plan or [])
        if (getattr(self.learning_state.current_experiment, "metadata", {}) or {}).get("resume_persistence_error"):
            self._set_workflow_state("action_required")
            return
        if not plan:
            self._set_workflow_state("idle")
            return
        statuses = {str(v.status or "").lower() for v in plan}
        if "requires_attention" in statuses or any(v.execution_metadata.get("action_required") or v.execution_metadata.get("admission_error") for v in plan):
            self._set_workflow_state("action_required")
            return
        if statuses.issubset({"pending"}):
            self._set_workflow_state("planned")
            return
        if "running" in statuses or "queued" in statuses:
            self._set_workflow_state("running")
            return
        if "completed" in statuses:
            if statuses.issubset({"completed", "failed", "uncontrolled", "cancelled"}):
                self._set_workflow_state("reviewing")
            else:
                self._set_workflow_state("running")
            return
        if "uncontrolled" in statuses:
            self._set_workflow_state("uncontrolled")
            return
        if statuses.issubset({"failed", "cancelled"}):
            self._set_workflow_state("failed")
            return
        self._set_workflow_state("planned")

    def _is_review_complete(self) -> bool:
        """Return True when a run has reached terminal status and all images are rated."""
        plan = list(self.learning_state.plan or [])
        if not plan:
            return False
        for variant in plan:
            status = str(getattr(variant, "status", "") or "").lower()
            if status in {"pending", "queued", "running", "requires_attention"} or variant.execution_metadata.get("action_required") or variant.execution_metadata.get("admission_error"):
                return False
            if status == "completed":
                refs = list(getattr(variant, "image_refs", []) or [])
                if not refs:
                    return False
                for ref in refs:
                    if not self.is_image_rated(str(ref)):
                        return False
        return True

    def export_resume_state(self) -> dict[str, Any] | None:
        """Export resumable learning session state for UI persistence."""
        if self.learning_state.current_experiment is None:
            return None
        if self._is_review_complete():
            return None
        # Delegate serialisation to experiment_persistence (PR-047).
        return build_resume_payload(
            state_dict=self.learning_state.to_dict(),
            workflow_state=self._workflow_state,
            learning_enabled=bool(self._learning_enabled),
        )

    def restore_resume_state(self, payload: dict[str, Any] | None) -> bool:
        """Restore learning session from persisted payload."""
        if not validate_resume_payload(payload):
            return False
        try:
            restored = LearningState.from_dict(payload)
        except Exception:
            return False

        from src.learning.experiment_reconciliation import preserve_observed_state

        preserve_observed_state(self.learning_state.current_experiment, restored.current_experiment)
        self.learning_state.current_experiment = restored.current_experiment
        self.learning_state.plan = list(restored.plan or [])
        self.learning_state.selected_variant = restored.selected_variant
        self.learning_state.selected_image_index = int(restored.selected_image_index or 0)
        # Drafts are part of the saved session; dropping them here lost them at the next save.
        self.learning_state.review_drafts = dict(restored.review_drafts or {})
        self.learning_state.baseline_draft = restored.baseline_draft
        if not draft_service.has_draft(self.learning_state) and restored.current_experiment is not None:
            # Opening an experiment restores its own baseline; it never reaches for the Pipeline.
            restored_experiment = restored.current_experiment
            draft_service.adopt(
                self.learning_state, restored_experiment.baseline_config, restored_experiment.baseline_authoring,
                origin=authoring.ORIGIN_LEGACY if not restored_experiment.baseline_authoring else "",
            )
        self.load_existing_ratings()
        reconcile = getattr(self.execution_controller, "reconcile", None)
        if callable(reconcile):
            reconcile()
        self._update_plan_table()

        # Delegate workflow-state extraction to experiment_persistence (PR-047).
        desired_state = extract_workflow_state(payload)
        if desired_state and not callable(reconcile):
            self._set_workflow_state(desired_state)
        else:
            self._recompute_workflow_state_from_plan()

        selected_variant = self.learning_state.selected_variant
        if (
            selected_variant is not None
            and self._review_panel
            and hasattr(self._review_panel, "display_variant_results")
        ):
            try:
                self._review_panel.display_variant_results(
                    selected_variant,
                    self.learning_state.current_experiment,
                )
            except Exception:
                pass
        self._notify_resume_state_changed()
        return True

    def get_learning_run_summary(self) -> dict[str, Any]:
        """Return deterministic plan/run summary for the Learning tab header."""
        plan = list(self.learning_state.plan or [])
        experiment = self.learning_state.current_experiment
        stage = str(getattr(experiment, "stage", "txt2img") or "txt2img")
        images_per_variant = int(getattr(experiment, "images_per_value", 0) or 0)
        total_variants = len(plan)
        status_counts = {
            "pending": 0,
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "uncontrolled": 0,
            "cancelled": 0,
            "requires_attention": 0,
        }
        total_planned_images = 0
        total_completed_images = 0
        for variant in plan:
            status = str(getattr(variant, "status", "") or "").lower()
            if status in status_counts:
                status_counts[status] += 1
            total_planned_images += int(getattr(variant, "planned_images", 0) or 0)
            total_completed_images += int(getattr(variant, "completed_images", 0) or 0)
        if total_planned_images <= 0 and total_variants > 0 and images_per_variant > 0:
            total_planned_images = total_variants * images_per_variant

        pending_submissions = status_counts["pending"]
        queue_ok = True
        queue_reason = ""
        queue_cap = None
        queue_depth = None
        if self.pipeline_controller:
            can_enqueue = getattr(self.pipeline_controller, "can_enqueue_learning_jobs", None)
            get_cap = getattr(self.pipeline_controller, "get_learning_queue_cap", None)
            get_depth = getattr(self.pipeline_controller, "get_queue_depth", None)
            if callable(get_cap):
                try:
                    queue_cap = int(get_cap())
                except Exception:
                    queue_cap = None
            if callable(get_depth):
                try:
                    queue_depth = int(get_depth())
                except Exception:
                    queue_depth = None
            if callable(can_enqueue):
                try:
                    queue_ok, queue_reason = can_enqueue(max(1, pending_submissions))
                except Exception:
                    queue_ok = False
                    queue_reason = "queue check failed"

        return {
            "stage": stage,
            "total_variants": total_variants,
            "status_counts": status_counts,
            "total_planned_images": total_planned_images,
            "total_completed_images": total_completed_images,
            "queue_ok": queue_ok,
            "queue_reason": queue_reason,
            "queue_cap": queue_cap,
            "queue_depth": queue_depth,
            "conclusion": self.get_experiment_conclusion(),
        }

    def get_experiment_conclusion(self) -> dict[str, Any]:
        """Project a conclusion from saved sample reviews only."""
        experiment_id = str(
            getattr(self.learning_state.current_experiment, "experiment_id", "") or ""
        )
        details = (
            self._learning_record_writer.get_rating_details_for_experiment(experiment_id)
            if self._learning_record_writer and experiment_id
            else {}
        )
        from src.learning.model_comparison import study_type

        return build_experiment_conclusion(
            list(self.learning_state.plan or []),
            details,
            dict(self.learning_state.review_drafts or {}),
            study_type=study_type(self.learning_state.current_experiment),
        )

    def on_job_completed(self, job_id: str, result: dict[str, Any]) -> None:
        """Handle completion of a learning job."""
        # This method can be used for general job completion handling
        # The specific variant handling is done in _on_variant_job_completed
        pass

    def build_rating_record(
        self,
        experiment: Any,
        target_variant: Any,
        image_ref: str,
        rating: int,
        notes: str,
        details: dict[str, Any] | None,
    ) -> tuple[LearningRecord, dict[str, Any], dict[str, Any]]:
        """The evidence record for one controlled rating, plus its context flags and subscores.

        Pure with respect to controller state, so a rating committed from a stored session builds the same record
        as one saved live.
        """
        # Ratings are evidence about an execution, not about the current GUI.
        # Retain the exact frozen/effective configuration carried by the NJR.
        executed_config = dict(target_variant.executed_config or {})
        snapshot_json = str(getattr(experiment, "execution_snapshot_json", "") or "")
        snapshot = thaw_snapshot(snapshot_json) if snapshot_json else {}
        base_config = dict(executed_config or snapshot.get("baseline_config") or {})
        from src.learning.model_comparison import rating_classification
        from src.learning.prompt_slot_experiment import rating_metadata

        if snapshot.get("study_type") in ("two_axis_grid", "prompt_model_matrix"):
            from src.learning.two_axis_grid import rating_classification as grid_classification

            classification = grid_classification(
                snapshot, target_variant.param_value, target_variant.execution_metadata,
                image_ref=image_ref, image_refs=list(target_variant.image_refs),
            )
        else:
            classification = rating_classification(
                snapshot, target_variant.param_value, target_variant.execution_metadata
            )
        base_config.update(
            {
                "prompt": str(executed_config.get("prompt", snapshot.get("prompt_text") or experiment.prompt_text)),
                "negative_prompt": str(executed_config.get("negative_prompt", snapshot.get("negative_prompt_text") or "")),
                "stage": str(snapshot.get("stage") or experiment.stage),
                experiment.variable_under_test.lower(): target_variant.param_value,
            }
        )
        detail_payload = dict(details or {})
        subscores = dict(detail_payload.get("subscores") or {})
        context_flags = dict(detail_payload.get("context_flags") or {})
        blended_rating = int(detail_payload.get("blended_rating") or rating)

        # Create variant config
        variant_config = dict(executed_config)
        variant_config[experiment.variable_under_test.lower()] = target_variant.param_value

        # Create learning record
        record = LearningRecord.from_pipeline_context(
            base_config=base_config,
            variant_configs=[variant_config],
            randomizer_mode="learning_experiment",
            randomizer_plan_size=1,
            extract_primary=self._extract_learning_primary,
            metadata={
                "experiment_id": experiment.experiment_id,
                "experiment_name": experiment.name,
                "experiment_description": experiment.description,
                "variable_under_test": experiment.variable_under_test,
                "variant_value": target_variant.param_value,
                "image_path": image_ref,
                "job_id": target_variant.job_id,
                "user_rating": blended_rating,
                "user_rating_raw": rating,
                "user_notes": notes,
                **classification,
                **rating_metadata(snapshot, target_variant),
                **controlled_rating_metadata(snapshot, target_variant),
                **ordinary_rating_prompt_evidence(snapshot, target_variant.execution_metadata),
                "rating_schema_version": 2,
                "rating_context": context_flags,
                "rating_details": subscores,
                # PR-046: mirror subscores under the canonical key used by review_tab records
                # so both record shapes normalize identically via extract_rating_detail()
                "subscores": subscores,
                "learning_context": {
                    "experiment_id": experiment.experiment_id,
                    "variant_id": target_variant.variant_id or str(target_variant.param_value),
                    "variant_name": f"{experiment.variable_under_test}={target_variant.param_value}",
                },
                "frozen_experiment": {
                    "schema_version": 2,
                    "experiment_id": experiment.experiment_id,
                    "variant_id": target_variant.variant_id,
                    "snapshot_sha256": snapshot_digest(snapshot_json) if snapshot_json else "",
                    "snapshot": snapshot,
                    "executed_config": executed_config,
                    "controlled_evidence_valid": bool(
                        dict(getattr(target_variant, "execution_metadata", {}) or {}).get(
                            "controlled_evidence_valid", False
                        )
                    ),
                    "variable_validation_reason": dict(
                        getattr(target_variant, "execution_metadata", {}) or {}
                    ).get("variable_validation_reason", ""),
                    "actual_all_seeds": list(
                        dict(getattr(target_variant, "execution_metadata", {}) or {}).get(
                            "actual_all_seeds", []
                        )
                        or []
                    ),
                },
            },
        )
        return record, context_flags, subscores

    def record_rating(
        self,
        image_ref: str,
        rating: int,
        notes: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a rating for a learning image."""
        if not self._learning_record_writer:
            raise RuntimeError("LearningRecordWriter not configured")

        if not self.learning_state.current_experiment:
            raise RuntimeError("No current experiment")

        # Find the variant that contains this image
        target_variant = None
        for variant in self.learning_state.plan:
            if image_ref in variant.image_refs:
                target_variant = variant
                break

        if not target_variant:
            raise ValueError(f"Image {image_ref} not found in any variant")

        experiment = self.learning_state.current_experiment
        record, context_flags, subscores = self.build_rating_record(
            experiment, target_variant, image_ref, rating, notes, details
        )

        # Write the record; a rating that was not stored must never be reported (or cached) as saved.
        if self._learning_record_writer.append_record(record) is False:
            raise OSError("The rating could not be written to the learning records file; see the log for details.")

        # Update rating cache
        self._rating_cache[image_ref] = rating
        self._rating_details_cache[image_ref] = {
            "overall_rating": rating,
            "notes": notes,
            "context_flags": context_flags,
            "subscores": subscores,
        }
        self.discard_review_draft(image_ref)

        # Refresh recommendations with new data
        self.refresh_recommendations()

        # Update plan table with new average rating
        self._update_variant_ratings()
        self._refresh_grid_view()
        if self._is_review_complete():
            self._set_workflow_state("completed")
        else:
            self._recompute_workflow_state_from_plan()
        self._notify_resume_state_changed()

    @staticmethod
    def _extract_learning_primary(config: dict[str, Any]) -> dict[str, Any]:
        """Extract executed primary settings from a frozen stage configuration."""
        stage = config.get("txt2img") if isinstance(config, dict) else {}
        if not isinstance(stage, dict):
            stage = {}
        return {
            "model": stage.get("model", config.get("model", "")),
            "sampler": stage.get("sampler_name", stage.get("sampler", "")),
            "scheduler": stage.get("scheduler", ""),
            "steps": stage.get("steps", 0),
            "cfg_scale": stage.get("cfg_scale", 0.0),
        }

    def update_recommendations(self) -> None:
        """Update recommendations based on latest learning data."""
        if not self._recommendation_engine:
            return

        # Get current prompt and stage for recommendations
        prompt_text = ""
        stage = "txt2img"

        if self.learning_state.current_experiment:
            prompt_text = self.learning_state.current_experiment.prompt_text
            stage = self.learning_state.current_experiment.stage
        elif self.prompt_workspace_state:
            # Fallback to current prompt workspace
            prompt_text = self.prompt_workspace_state.get_current_prompt_text()
            stage = "txt2img"  # Default stage

        if prompt_text:
            recommendations = self._recommendation_engine.recommend(
                prompt_text, stage, **self._recommendation_query_context()
            )

            # Update review panel with new recommendations
            if self._review_panel and hasattr(self._review_panel, "update_recommendations"):
                self._review_panel.update_recommendations(recommendations)

    def on_job_completed_callback(self, job: Any, result: Any) -> None:
        """Legacy application notification cannot bypass the sole tracking owner."""
        # JobService's normal job_finished/job_failed listeners own completion.
        # This older router remains callable by AppController, but does no work.
        return

    def get_recommendations_for_current_prompt(self) -> Any | None:
        """Get recommendations for the current prompt and stage."""
        from src.learning.model_comparison import study_type

        if self.learning_state.current_experiment and study_type(self.learning_state.current_experiment) in LOCAL_ONLY_STUDIES:
            return None
        if not self._recommendation_engine:
            return None

        # Get current prompt and stage
        prompt_text = ""
        stage = "txt2img"

        if self.learning_state.current_experiment:
            prompt_text = self.learning_state.current_experiment.prompt_text
            stage = self.learning_state.current_experiment.stage
        elif self.prompt_workspace_state:
            prompt_text = self.prompt_workspace_state.get_current_prompt_text()
            stage = "txt2img"

        if prompt_text:
            return self._recommendation_engine.recommend(
                prompt_text, stage, **self._recommendation_query_context()
            )

        return None

    def _recommendation_query_context(self) -> dict[str, Any]:
        """Use known model/geometry and the effective capability intersection."""
        return recommendation_query(self)

    def _update_variant_ratings(self) -> None:
        """Show each variant's average saved rating (records are keyed by the opaque ``experiment_id``)."""
        if not self.learning_state.current_experiment or not self._plan_table:
            return
        if not hasattr(self._plan_table, "update_row_rating"):
            return
        projection = build_review_projection(self.learning_state.plan, self.get_rating_for_image)
        for i, summary in enumerate(projection.variants):
            self._plan_table.update_row_rating(i, summary.average_rating)

    def refresh_recommendations(self) -> None:
        """Force refresh of recommendations, clearing any cache."""
        if self._recommendation_engine:
            # Force reload by clearing cache timestamp
            self._recommendation_engine._cache_timestamp = 0.0
            self.update_recommendations()

    def set_learning_enabled(self, enabled: bool) -> None:
        """Set learning enablement and propagate to connected controllers."""
        self._learning_enabled = bool(enabled)
        if self.app_controller and hasattr(self.app_controller, "_app_state"):
            try:
                self.app_controller._app_state.set_learning_enabled(self._learning_enabled)
            except Exception:
                pass
        if self.execution_controller and hasattr(self.execution_controller, "set_learning_enabled"):
            try:
                self.execution_controller.set_learning_enabled(self._learning_enabled)
            except Exception:
                pass
        if self.pipeline_controller and hasattr(self.pipeline_controller, "set_learning_enabled"):
            try:
                self.pipeline_controller.set_learning_enabled(self._learning_enabled)
            except Exception:
                pass
        self._notify_resume_state_changed()

    def list_recent_records(self, limit: int = 10) -> list[Any]:
        """Return recent learning records through execution-controller APIs."""
        if self.execution_controller and hasattr(self.execution_controller, "list_recent_records"):
            try:
                return self.execution_controller.list_recent_records(limit=limit)
            except Exception:
                pass
        records_path = getattr(self._learning_record_writer, "records_path", None)
        if not records_path:
            return []
        try:
            return list_recent_learning_records(Path(records_path), limit=limit)
        except Exception:
            return []

    def save_feedback(self, record: Any, rating: int, tags: str | None = None) -> Any:
        """Persist feedback through execution-controller APIs."""
        if self.execution_controller and hasattr(self.execution_controller, "save_feedback"):
            try:
                return self.execution_controller.save_feedback(record, rating, tags)
            except Exception:
                pass
        records_path = getattr(self._learning_record_writer, "records_path", None)
        if not records_path:
            return None
        try:
            return update_record_feedback(
                Path(records_path),
                record,
                rating=rating,
                tags=tags,
            )
        except Exception:
            return None

    def save_review_feedback(self, feedback: dict[str, Any]) -> LearningRecord:
        """Persist review-tab feedback into learning records for downstream analysis."""
        if not self._learning_record_writer:
            raise RuntimeError("LearningRecordWriter not configured")

        image_path = str(feedback.get("image_path") or "").strip()
        if not image_path:
            raise ValueError("image_path is required")

        try:
            rating = int(feedback.get("rating", 0))
        except Exception as exc:
            raise ValueError("rating must be an integer") from exc
        if rating < 1 or rating > 5:
            raise ValueError("rating must be between 1 and 5")
        subscores_raw = feedback.get("subscores") or {}
        subscores = {
            "anatomy": int(subscores_raw.get("anatomy", rating) or rating),
            "composition": int(subscores_raw.get("composition", rating) or rating),
            "prompt_adherence": int(subscores_raw.get("prompt_adherence", rating) or rating),
        }
        for key, value in subscores.items():
            if value < 1 or value > 5:
                raise ValueError(f"{key} must be between 1 and 5")
        weighted_score = (
            (rating * 0.4)
            + (subscores["anatomy"] * 0.2)
            + (subscores["composition"] * 0.2)
            + (subscores["prompt_adherence"] * 0.2)
        )
        blended_rating = int(min(5, max(1, round(weighted_score))))

        base_prompt = str(feedback.get("base_prompt") or "")
        base_negative = str(feedback.get("base_negative_prompt") or "")
        after_prompt = str(feedback.get("after_prompt") or base_prompt)
        after_negative = str(feedback.get("after_negative_prompt") or base_negative)
        model = str(feedback.get("model") or "")
        stage = str(feedback.get("stage") or "review")
        metadata = {
            "source": "review_tab",
            "record_kind": "review_tab_feedback",
            "image_path": image_path,
            "user_rating": blended_rating,
            "user_rating_raw": rating,
            "advanced_rating_enabled": True,
            "subscores": subscores,
            "weighted_score": weighted_score,
            "quality_label": str(feedback.get("quality_label") or ""),
            "user_notes": str(feedback.get("notes") or ""),
            "stage": stage,
            "model": model,
            "prompt_before": base_prompt,
            "prompt_after": after_prompt,
            "negative_prompt_before": base_negative,
            "negative_prompt_after": after_negative,
            "prompt_delta": str(feedback.get("prompt_delta") or ""),
            "negative_prompt_delta": str(feedback.get("negative_prompt_delta") or ""),
            "prompt_mode": str(feedback.get("prompt_mode") or "append"),
            "negative_prompt_mode": str(feedback.get("negative_prompt_mode") or "append"),
            "stages": list(feedback.get("stages") or []),
            "review_context": dict(feedback.get("context") or {}),
        }
        primary_sampler = str(feedback.get("sampler") or "")
        primary_scheduler = str(feedback.get("scheduler") or "")
        primary_steps = feedback.get("steps")
        primary_cfg_scale = feedback.get("cfg_scale")

        def _extract_primary(_cfg: dict[str, Any]) -> dict[str, Any]:
            return {
                "model": model,
                "sampler": primary_sampler,
                "scheduler": primary_scheduler,
                "steps": primary_steps,
                "cfg_scale": primary_cfg_scale,
            }

        record = LearningRecord.from_pipeline_context(
            base_config={
                "stage": stage,
                "model": model,
                "prompt": base_prompt,
                "negative_prompt": base_negative,
            },
            variant_configs=[
                {
                    "prompt": after_prompt,
                    "negative_prompt": after_negative,
                    "model": model,
                }
            ],
            randomizer_mode="review_feedback",
            randomizer_plan_size=1,
            extract_primary=_extract_primary,
            metadata=metadata,
        )
        self._learning_record_writer.append_record(record)
        try:
            stamp_result = self._review_metadata_service.stamp_review_metadata(
                image_path=image_path,
                feedback=feedback,
                record=record,
            )
            record.metadata["artifact_review_metadata"] = {
                "success": bool(stamp_result.success),
                "storage": stamp_result.storage,
                "stamped_path": stamp_result.stamped_path,
                "sidecar_path": stamp_result.sidecar_path,
                "error": stamp_result.error,
            }
        except Exception as exc:
            record.metadata["artifact_review_metadata"] = {
                "success": False,
                "storage": "failed",
                "stamped_path": image_path,
                "sidecar_path": None,
                "error": str(exc),
            }
        self.refresh_recommendations()
        return record

    def undo_review_feedback(
        self,
        *,
        run_id: str | None = None,
        image_path: str | None = None,
    ) -> bool:
        """Undo a review feedback write by deleting the latest matching record."""
        if not self._learning_record_writer:
            return False
        path = self._learning_record_writer.records_path
        if not path.exists():
            return False

        target_run = str(run_id or "").strip()
        target_image = str(image_path or "").strip()
        try:
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            return False
        if not lines:
            return False

        remove_index = -1
        for idx in range(len(lines) - 1, -1, -1):
            try:
                payload = json.loads(lines[idx])
            except Exception:
                continue
            metadata = payload.get("metadata", {})
            if metadata.get("source") != "review_tab":
                continue
            if target_run and str(payload.get("run_id") or "") != target_run:
                continue
            if target_image and str(metadata.get("image_path") or "") != target_image:
                continue
            remove_index = idx
            break
        if remove_index < 0:
            return False

        lines.pop(remove_index)
        try:
            final_text = "\n".join(lines)
            if final_text:
                final_text += "\n"
            path.write_text(final_text, encoding="utf-8")
        except Exception:
            return False
        self.refresh_recommendations()
        return True

    def list_recent_review_feedback(
        self,
        *,
        limit: int = 20,
        image_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent review feedback records from learning storage."""
        if not self._learning_record_writer:
            return []
        path = self._learning_record_writer.records_path
        if not path.exists():
            return []

        selected_image = str(image_path or "").strip()
        rows: list[dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8") as handle:
                raw_lines = [line.strip() for line in handle if line.strip()]
                for raw in reversed(raw_lines):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        continue
                    metadata = payload.get("metadata", {})
                    if metadata.get("source") != "review_tab":
                        continue
                    if selected_image and str(metadata.get("image_path") or "") != selected_image:
                        continue
                    rows.append(
                        {
                            "run_id": payload.get("run_id"),
                            "timestamp": payload.get("timestamp"),
                            "source_type": "internal_learning_record",
                            "schema": INTERNAL_REVIEW_SUMMARY_SCHEMA,
                            "image_path": metadata.get("image_path"),
                            "rating": metadata.get("user_rating"),
                            "user_rating": metadata.get("user_rating"),
                            "user_rating_raw": metadata.get("user_rating_raw"),
                            "quality_label": metadata.get("quality_label"),
                            "notes": metadata.get("user_notes"),
                            "user_notes": metadata.get("user_notes"),
                            "subscores": metadata.get("subscores", {}),
                            "weighted_score": metadata.get("weighted_score"),
                            "prompt_before": metadata.get("prompt_before"),
                            "prompt_after": metadata.get("prompt_after"),
                            "negative_prompt_before": metadata.get("negative_prompt_before"),
                            "negative_prompt_after": metadata.get("negative_prompt_after"),
                            "prompt_delta": metadata.get("prompt_delta"),
                            "negative_prompt_delta": metadata.get("negative_prompt_delta"),
                            "prompt_mode": metadata.get("prompt_mode"),
                            "negative_prompt_mode": metadata.get("negative_prompt_mode"),
                            "review_context": metadata.get("review_context", {}),
                            "stages": metadata.get("stages", []),
                        }
                    )
        except Exception:
            return []

        return rows[: max(1, int(limit))]

    def get_prior_review_summary(self, image_path: str | Path) -> dict[str, Any] | None:
        """Return the latest normalized prior review summary for one image path.

        Precedence:
        1. internal learning-record review feedback
        2. embedded portable review metadata
        3. sidecar portable review metadata
        """
        normalized_path = str(Path(str(image_path or "").strip()))
        if not normalized_path:
            return None

        recent_rows = self.list_recent_review_feedback(limit=1, image_path=normalized_path)
        if recent_rows:
            row = dict(recent_rows[0])
            summary = PortableReviewSummary(
                source_type="internal_learning_record",
                schema=INTERNAL_REVIEW_SUMMARY_SCHEMA,
                review_timestamp=str(row.get("timestamp") or ""),
                user_rating=row.get("user_rating"),
                user_rating_raw=row.get("user_rating_raw"),
                quality_label=str(row.get("quality_label") or ""),
                subscores=dict(row.get("subscores") or {}),
                weighted_score=row.get("weighted_score"),
                user_notes=str(row.get("user_notes") or row.get("notes") or ""),
                prompt_before=str(row.get("prompt_before") or ""),
                prompt_after=str(row.get("prompt_after") or ""),
                negative_prompt_before=str(row.get("negative_prompt_before") or ""),
                negative_prompt_after=str(row.get("negative_prompt_after") or ""),
                prompt_delta=str(row.get("prompt_delta") or ""),
                negative_prompt_delta=str(row.get("negative_prompt_delta") or ""),
                prompt_mode=str(row.get("prompt_mode") or ""),
                negative_prompt_mode=str(row.get("negative_prompt_mode") or ""),
                stages=[
                    str(stage)
                    for stage in list(row.get("stages") or [])
                    if str(stage or "").strip()
                ],
                review_context=dict(row.get("review_context") or {}),
                review_record_id=str(row.get("run_id") or ""),
            )
            return summary.to_dict()

        portable_summary = self._review_metadata_service.read_review_summary(normalized_path)
        return portable_summary.to_dict() if portable_summary is not None else None

    def inspect_artifact_metadata(self, image_path: str | Path) -> dict[str, Any]:
        """Return a unified inspection payload for one artifact path."""
        internal_summary = self.get_prior_review_summary(image_path)
        inspection = self._artifact_metadata_inspector.inspect_artifact(
            image_path,
            internal_review_summary=internal_summary,
        )
        return inspection.to_dict()

    def on_variant_selected(self, variant_index: int) -> None:
        """Handle selection of a variant in the table."""
        if 0 <= variant_index < len(self.learning_state.plan):
            variant = self.learning_state.plan[variant_index]
            self.learning_state.selected_variant = variant
            if self._review_panel and hasattr(self._review_panel, "display_variant_results"):
                self._review_panel.display_variant_results(
                    variant, self.learning_state.current_experiment
                )
            self._notify_resume_state_changed()

    def apply_recommendations_to_pipeline(self, recommendations: Any) -> bool:
        """Apply recommendations to the pipeline stage cards.

        PR-044: Blocks automation when evidence tier is not experiment_strong.

        Returns True if successful, False otherwise.
        """
        if self._automation_mode == "suggest_only":
            return False
        if not self.pipeline_controller:
            return False

        # PR-044/055: manual-only evidence tiers must still support explicit
        # apply-with-confirm. Only the fully automatic path is gated on
        # automation_eligible.
        if (
            self._automation_mode == "auto_micro_experiment"
            and hasattr(recommendations, "automation_eligible")
            and not recommendations.automation_eligible
        ):
            return False

        # Get stage cards panel
        stage_cards = getattr(self.pipeline_controller, "stage_cards_panel", None)
        if not stage_cards:
            # Try via app_state or other paths
            stage_cards = self._find_stage_cards_panel()

        if not stage_cards:
            return False

        # Extract recommendations
        rec_list = self._extract_rec_list(recommendations)
        if not validate_recommendation_apply(self, recommendations, stage_cards, rec_list):
            return False
        from src.gui_v2.recommendation_targets import prepare_recommendation_patch

        try:
            patch = prepare_recommendation_patch(
                stage_cards,
                str(getattr(recommendations, "stage", "txt2img") or "txt2img"),
                rec_list,
            )
        except Exception:
            return False
        self._automation_snapshot = {}
        for target, _variable, _value, old_value in patch:
            self._automation_snapshot.setdefault(target, old_value)
        for _target, variable, value, _old_value in patch:
            try:
                variable.set(value)
            except Exception:
                self.rollback_last_recommendation_apply()
                return False
        if not patch:
            return False

        if self._automation_mode == "auto_micro_experiment":
            can_enqueue, _reason = self._check_micro_experiment_queue_capacity(requested_jobs=1)
            if not can_enqueue:
                self.rollback_last_recommendation_apply()
                return False
            submit_preview = getattr(self.pipeline_controller, "submit_preview_jobs_to_queue", None)
            get_preview = getattr(self.pipeline_controller, "get_preview_jobs", None)
            if callable(submit_preview) and callable(get_preview):
                try:
                    preview_jobs = list(get_preview() or [])
                    if preview_jobs:
                        submit_preview(
                            records=preview_jobs[:1],
                            source="learning_auto_micro",
                            prompt_source="manual",
                        )
                except Exception:
                    self.rollback_last_recommendation_apply()
                    return False
        return True

    def set_automation_mode(self, mode: str) -> None:
        allowed = {"suggest_only", "apply_with_confirm", "auto_micro_experiment"}
        mode_value = str(mode or "suggest_only").strip().lower()
        if mode_value not in allowed:
            mode_value = "suggest_only"
        self._automation_mode = mode_value
        self._notify_resume_state_changed()

    def get_automation_mode(self) -> str:
        return self._automation_mode

    def rollback_last_recommendation_apply(self) -> bool:
        """Rollback the most recent recommendation apply operation."""
        if not self._automation_snapshot:
            return False
        stage_cards = None
        if self.pipeline_controller:
            stage_cards = getattr(self.pipeline_controller, "stage_cards_panel", None)
        if not stage_cards:
            stage_cards = self._find_stage_cards_panel()
        if not stage_cards:
            return False
        restored = 0
        for (card_name, var_name), old_value in self._automation_snapshot.items():
            card = getattr(stage_cards, card_name, None)
            if not card:
                continue
            var = getattr(card, var_name, None)
            if not var or not hasattr(var, "set"):
                continue
            try:
                var.set(old_value)
                restored += 1
            except Exception:
                continue
        self._automation_snapshot = {}
        return restored > 0

    def _apply_single_recommendation(
        self,
        stage_cards: Any,
        param: str,
        value: Any,
        *,
        snapshot: dict[tuple[str, str], Any] | None = None,
        target_stage: str = "txt2img",
    ) -> bool:
        """Apply a single recommendation to stage cards."""
        from src.gui_v2.recommendation_targets import recommendation_target

        mapping = recommendation_target(target_stage, param)
        if not mapping:
            return False
        card_name, var_name = mapping

        try:
            card = getattr(stage_cards, card_name, None)
            if not card:
                return False

            var = getattr(card, var_name, None)
            if not var:
                return False

            if snapshot is not None and hasattr(var, "get"):
                snap_key = (card_name, var_name)
                if snap_key not in snapshot:
                    try:
                        snapshot[snap_key] = var.get()
                    except Exception:
                        pass
            var.set(value)
            return True
        except Exception:
            return False

    def _check_micro_experiment_queue_capacity(self, requested_jobs: int) -> tuple[bool, str]:
        if not self.pipeline_controller:
            return False, "pipeline controller unavailable"
        checker = getattr(self.pipeline_controller, "can_enqueue_learning_jobs", None)
        if callable(checker):
            try:
                return checker(int(max(1, requested_jobs)))
            except Exception:
                return False, "queue capacity check failed"
        return True, ""

    def _find_stage_cards_panel(self) -> Any:
        """Find stage cards panel through various paths."""
        # Try via pipeline_state
        if self.pipeline_state:
            cards = getattr(self.pipeline_state, "stage_cards_panel", None)
            if cards:
                return cards

        # Try via app reference (if available)
        if hasattr(self, "_app_ref"):
            pipeline_tab = getattr(self._app_ref, "pipeline_tab", None)
            if pipeline_tab:
                return getattr(pipeline_tab, "stage_cards_panel", None)

        return None

    def _extract_rec_list(self, recommendations: Any) -> list:
        """Extract list of recommendations from various formats."""
        if hasattr(recommendations, "recommendations"):
            return recommendations.recommendations
        elif isinstance(recommendations, list):
            return recommendations
        return []

    def get_analytics_summary(self) -> Any | None:
        """Get overall analytics summary."""
        if not self._learning_record_writer:
            return None

        from src.learning.learning_analytics import LearningAnalytics

        analytics = LearningAnalytics(self._learning_record_writer)
        return analytics.get_overall_summary()

    def refresh_analytics(self) -> None:
        """Refresh analytics display."""
        summary = self.get_analytics_summary()
        if hasattr(self, "_analytics_panel"):
            self._analytics_panel.update_analytics(summary)

    def export_analytics_json(self, file_path: str) -> None:
        """Export analytics to JSON file."""
        if not self._learning_record_writer:
            raise RuntimeError("No learning record writer configured")

        from pathlib import Path

        from src.learning.learning_analytics import LearningAnalytics

        analytics = LearningAnalytics(self._learning_record_writer)
        analytics.export_to_json(Path(file_path))

    def export_analytics_csv(self, file_path: str) -> None:
        """Export analytics to CSV file."""
        if not self._learning_record_writer:
            raise RuntimeError("No learning record writer configured")

        from pathlib import Path

        from src.learning.learning_analytics import LearningAnalytics

        analytics = LearningAnalytics(self._learning_record_writer)
        analytics.export_to_csv(Path(file_path))

    # ------------------------------------------------------------------
    # PR-GUI-LEARN-041: Discovered-review orchestration
    # ------------------------------------------------------------------

    def _get_discovered_store(self):
        """Return a DiscoveredReviewStore instance, creating it lazily."""
        from src.learning.discovered_review_store import DiscoveredReviewStore
        from src.learning.learning_paths import get_discovered_experiments_root

        if not hasattr(self, "_discovered_review_store"):
            self._discovered_review_store = DiscoveredReviewStore(
                get_discovered_experiments_root(create=True)
            )
        return self._discovered_review_store

    def refresh_discovered_inbox(self, status: str | None = None) -> list:
        """Return current handles from the discovered-review store.

        Parameters
        ----------
        status:
            If provided, filter by this status string.  Pass None for all.

        Returns
        -------
        list[DiscoveredReviewHandle]
        """
        from src.learning.discovered_review_models import (
            STATUS_IN_REVIEW,
            STATUS_WAITING_REVIEW,
        )

        store = self._get_discovered_store()
        if status == "active":
            return store.list_handles_by_status({STATUS_WAITING_REVIEW, STATUS_IN_REVIEW})
        return store.list_handles(status=status)

    def load_discovered_group(self, group_id: str):
        """Load and return a full DiscoveredReviewExperiment by ID.

        Also updates selected_discovered_group_id in LearningState.
        """
        store = self._get_discovered_store()
        experiment = store.load_group(group_id)
        if experiment is not None:
            self.learning_state.selected_discovered_group_id = group_id
        return experiment

    def save_discovered_item_rating(
        self, group_id: str, item_id: str, rating: int, notes: str = ""
    ) -> None:
        """Persist a per-item rating into the discovered-review store."""
        store = self._get_discovered_store()
        store.save_item_rating(group_id, item_id, rating, notes)

    def close_discovered_group(self, group_id: str) -> None:
        """Transition a discovered group to 'closed' status."""
        store = self._get_discovered_store()
        store.close_group(group_id)

    def ignore_discovered_group(self, group_id: str) -> None:
        """Transition a discovered group to 'ignored' status."""
        store = self._get_discovered_store()
        store.ignore_group(group_id)

    def reopen_discovered_group(self, group_id: str) -> None:
        """Reopen a closed/ignored discovered group back to waiting_review."""
        store = self._get_discovered_store()
        store.reopen_group(group_id)

    def prune_missing_discovered_outputs(self) -> dict[str, int]:
        """Prune only scanner-owned unavailable discovered artifacts."""
        return self._get_discovered_store().prune_missing_scanner_items()

    def preview_missing_discovered_cleanup(self) -> dict[str, int]:
        return self._get_discovered_store().preview_missing_cleanup()

    def clean_missing_discovered_outputs(self, *, include_legacy: bool) -> dict[str, int]:
        return self._get_discovered_store().prune_missing_scanner_items(
            include_legacy=include_legacy
        )

    def reset_scanned_discovered_outputs(self) -> dict[str, int]:
        """Reset only known filesystem-scan review projections."""
        return self._get_discovered_store().reset_filesystem_scan_state()

    # ------------------------------------------------------------------
    # PR-LEARN-259B: Staged-curation orchestration
    # ------------------------------------------------------------------

    def list_staged_curation_handles(self) -> list:
        """Return active discovered groups for the staged-curation mode."""
        return self.refresh_discovered_inbox(status="active")

    def get_staged_curation_reason_tag_options(self) -> list[str]:
        """Return curated reason tags for quick staged-review decisions."""
        return [
            "good_composition",
            "good_lighting",
            "strong_prompt_match",
            "good_face",
            "bad_face",
            "anatomy_issue",
            "prompt_drift",
            "not_worth_upscaling",
            "keeper",
        ]

    def get_staged_curation_face_triage_tier_options(self) -> list[str]:
        """Return supported face-triage tiers for per-candidate routing."""
        return self._curation_workflow_builder.get_face_triage_tier_options()

    def import_review_images_to_staged_curation(
        self,
        image_paths: list[str],
        *,
        display_name: str | None = None,
        source_label: str = "review_tab",
        source_metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Create a staged-curation group from explicit review image paths."""
        cleaned_paths = [str(Path(path)) for path in image_paths if str(path or "").strip()]
        if not cleaned_paths:
            return None

        items: list[DiscoveredReviewItem] = []
        for index, image_path in enumerate(cleaned_paths):
            item = self._build_discovered_item_from_image_path(image_path, index=index)
            if item is not None:
                item.extra_fields = {
                    **dict(item.extra_fields or {}),
                    **dict(source_metadata or {}),
                }
                items.append(item)
        if not items:
            return None

        prompt_hash = self._hash_prompt(items[0].positive_prompt)
        group_id = f"curation-import-{uuid.uuid4().hex[:12]}"
        experiment = DiscoveredReviewExperiment(
            group_id=group_id,
            display_name=str(display_name or f"Imported Review {group_id[-6:]}"),
            stage=str(items[0].stage or "txt2img"),
            prompt_hash=prompt_hash,
            status="waiting_review",
            items=items,
            varying_fields=self._infer_varying_fields(items),
            scan_source_dirs=sorted({str(Path(item.artifact_path).parent) for item in items}),
            origin=(
                "controlled_experiment"
                if source_label == "controlled_experiment"
                else ("history_import" if source_label == "history_import" else "review_import")
            ),
            notes=f"Imported via {source_label}",
        )
        store = self._get_discovered_store()
        store.save_group(experiment)
        self.learning_state.selected_staged_curation_group_id = group_id
        self.learning_state.selected_staged_curation_item_id = items[0].item_id if items else None
        self._notify_resume_state_changed()
        return group_id

    def send_controlled_artifacts_to_staged_curation(self, image_paths: list[str]) -> str | None:
        """Create a curation workset from explicit controlled artifacts without discovery."""
        experiment = self.learning_state.current_experiment
        if experiment is None:
            return None
        selected = [str(path) for path in image_paths if str(path or "").strip()]
        if not selected:
            return None
        return self.import_review_images_to_staged_curation(
            selected,
            display_name=f"Controlled: {experiment.name}",
            source_label="controlled_experiment",
            source_metadata={
                "controlled_source": {
                    "experiment_id": experiment.experiment_id,
                    "experiment_name": experiment.name,
                    "evidence_kind": "controlled_experiment_artifact",
                }
            },
        )

    def import_history_entry_to_staged_curation(
        self,
        entry: Any,
        *,
        display_name: str | None = None,
    ) -> str | None:
        """Import output artifacts from a history entry into staged curation."""
        image_paths = self._extract_history_entry_image_paths(entry)
        if not image_paths:
            return None
        default_name = display_name or self._build_history_import_display_name(entry)
        return self.import_review_images_to_staged_curation(
            image_paths,
            display_name=default_name,
            source_label="history_import",
        )

    def load_staged_curation_group(self, group_id: str) -> dict[str, Any] | None:
        """Return staged-curation projection data for a discovered group."""
        store = self._get_discovered_store()
        experiment = store.load_group(group_id)
        if experiment is None:
            return None
        if experiment.status == "waiting_review":
            store.begin_review(group_id)
            experiment = store.load_group(group_id) or experiment

        workflow = self._build_curation_workflow(experiment)
        candidates = [
            self._build_curation_candidate(experiment, item)
            for item in list(experiment.items or [])
        ]
        events = store.load_selection_events(group_id)
        latest_events: dict[str, SelectionEvent] = {}
        for event in events:
            latest_events[event.candidate_id] = event

        self.learning_state.selected_staged_curation_group_id = group_id
        if candidates and not self.learning_state.selected_staged_curation_item_id:
            self.learning_state.selected_staged_curation_item_id = candidates[0].candidate_id
        self._notify_resume_state_changed()
        return {
            "workflow": workflow,
            "experiment": experiment,
            "candidates": candidates,
            "selection_events": events,
            "latest_events": latest_events,
        }

    def get_staged_curation_workflow_summary(self, group_id: str) -> dict[str, Any] | None:
        """Return a summary payload for the staged-curation workflow."""
        payload = self.load_staged_curation_group(group_id)
        if not isinstance(payload, dict):
            return None
        workflow = payload.get("workflow")
        experiment = payload.get("experiment")
        candidates = list(payload.get("candidates") or [])
        selection_events = list(payload.get("selection_events") or [])
        if not isinstance(workflow, CurationWorkflow) or experiment is None:
            return None
        return build_workflow_summary(workflow, experiment, candidates, selection_events)

    def get_staged_curation_candidate_replay_summary(
        self,
        group_id: str,
        candidate_id: str,
    ) -> dict[str, Any] | None:
        """Return replay-lineage details for one staged-curation candidate."""
        payload = self.load_staged_curation_group(group_id)
        if not isinstance(payload, dict):
            return None
        candidates = list(payload.get("candidates") or [])
        latest_events = dict(payload.get("latest_events") or {})
        experiment = payload.get("experiment")
        item_by_id = {
            str(getattr(item, "item_id", "") or ""): item
            for item in list(getattr(experiment, "items", []) or [])
        }
        history_entries = []
        app_state = (
            getattr(self.app_controller, "app_state", None)
            if self.app_controller is not None
            else None
        )
        if app_state is not None:
            history_entries = list(getattr(app_state, "history_items", []) or [])
        for candidate in candidates:
            if str(getattr(candidate, "candidate_id", "") or "") != str(candidate_id or ""):
                continue
            item = item_by_id.get(str(candidate_id or ""))
            latest_derived = find_latest_derived_descendant(
                history_entries, str(candidate_id or "")
            )
            return build_candidate_replay_entry(
                candidate,
                item,
                latest_events.get(str(candidate_id or "")),
                latest_derived=latest_derived,
            )
        return None

    def get_staged_curation_candidate_latest_descendant(
        self, candidate_id: str
    ) -> dict[str, Any] | None:
        """Return the newest derived descendant artifact for one staged-curation candidate."""
        if not self.app_controller:
            return None
        app_state = getattr(self.app_controller, "app_state", None)
        if app_state is None:
            return None
        history_entries = list(getattr(app_state, "history_items", []) or [])
        return find_latest_derived_descendant(history_entries, str(candidate_id or ""))

    def get_staged_curation_candidate_source_context(
        self,
        group_id: str,
        candidate_id: str,
    ) -> dict[str, Any] | None:
        """Return read-only source prompt and plan-preview context for one candidate."""
        payload = self.load_staged_curation_group(group_id)
        if not isinstance(payload, dict):
            return None

        candidates = list(payload.get("candidates") or [])
        latest_events = dict(payload.get("latest_events") or {})
        experiment = payload.get("experiment")
        item_by_id = {
            str(getattr(item, "item_id", "") or ""): item
            for item in list(getattr(experiment, "items", []) or [])
        }
        for candidate in candidates:
            if str(getattr(candidate, "candidate_id", "") or "") != str(candidate_id or ""):
                continue

            item = item_by_id.get(str(candidate_id or ""))
            replay_summary = build_candidate_replay_entry(
                candidate,
                item,
                latest_events.get(str(candidate_id or "")),
            )
            source_prompt = str(replay_summary.get("positive_prompt") or "")
            source_negative_prompt = str(replay_summary.get("negative_prompt") or "")
            source_model = str(
                replay_summary.get("source_model") or replay_summary.get("model") or ""
            )
            baseline: dict[str, Any] = {}
            if item is not None and (
                not source_prompt or not source_negative_prompt or not source_model
            ):
                image_path = Path(
                    resolve_output_artifact_path(
                        str(getattr(item, "artifact_path", "") or "").strip()
                    )
                )
                if image_path.exists():
                    baseline = self._extract_reprocess_baseline_from_image(image_path)
                    source_prompt = source_prompt or str(baseline.get("prompt") or "")
                    source_negative_prompt = source_negative_prompt or str(
                        baseline.get("negative_prompt") or ""
                    )
                    source_model = source_model or str(baseline.get("model") or "")
            elif item is not None:
                image_path = Path(
                    resolve_output_artifact_path(
                        str(getattr(item, "artifact_path", "") or "").strip()
                    )
                )
                if image_path.exists():
                    baseline = self._extract_reprocess_baseline_from_image(image_path)

            decision = str(replay_summary.get("decision") or "")
            target_stage = self._resolve_staged_curation_target_stage_for_decision(decision)
            effective_settings_summary = ""
            if target_stage:
                stage_flags = ReviewWorkflowAdapter._TARGET_TO_STAGE_FLAGS(target_stage)
                if stage_flags:
                    fallback_builder = getattr(self.app_controller, "_build_reprocess_config", None)
                    if callable(fallback_builder):
                        fallback_config = fallback_builder(stage_flags)
                    else:
                        fallback_config = self._get_baseline_config()
                    metadata_config = (
                        baseline.get("config") if isinstance(baseline.get("config"), dict) else {}
                    )
                    preview = ReprocessJobBuilder().build_effective_settings_preview(
                        source_stage=str(replay_summary.get("source_stage") or "unknown"),
                        source_model=source_model or None,
                        source_vae=baseline.get("vae"),
                        stages=list(stage_flags),
                        fallback_config=fallback_config,
                        metadata_config=metadata_config,
                        prompt=source_prompt,
                        negative_prompt=source_negative_prompt,
                        prompt_mode="append",
                        negative_prompt_mode="append",
                        prompt_delta="",
                        negative_prompt_delta="",
                        source_baseline_label="staged curation source baseline",
                        fallback_source_label="target-stage preset",
                    )
                    effective_settings_summary = (
                        ReviewWorkflowAdapter().format_effective_settings_summary(preview)
                    )
            return {
                "source_prompt": source_prompt,
                "source_negative_prompt": source_negative_prompt,
                "source_stage": str(replay_summary.get("source_stage") or ""),
                "source_model": source_model,
                "decision": decision,
                "target_stage": target_stage or "",
                "path_label": "Queue Now",
                "effective_settings_summary": effective_settings_summary,
            }
        return None

    def record_staged_curation_selection(
        self,
        group_id: str,
        item_id: str,
        decision: str,
        *,
        reason_tags: list[str] | None = None,
        notes: str | None = None,
    ) -> SelectionEvent | None:
        """Persist a canonical staged-curation selection event."""
        store = self._get_discovered_store()
        experiment = store.load_group(group_id)
        if experiment is None:
            return None
        item = next((entry for entry in experiment.items if entry.item_id == item_id), None)
        if item is None:
            return None
        candidate = self._build_curation_candidate(experiment, item)
        event = SelectionEvent(
            event_id=str(uuid.uuid4()),
            workflow_id=f"curation:{group_id}",
            candidate_id=candidate.candidate_id,
            stage=candidate.stage,
            decision=str(decision or "not_advanced"),
            timestamp=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            actor="user",
            reason_tags=[str(tag).strip() for tag in list(reason_tags or []) if str(tag).strip()],
            notes=str(notes).strip() if notes is not None and str(notes).strip() else None,
        )
        if not store.append_selection_event(group_id, event):
            return None
        if self._learning_record_writer:
            try:
                learning_record = CurationLearningBridge.build_learning_record(
                    CurationLearningContext(
                        workflow_id=f"curation:{group_id}",
                        candidate=candidate,
                        experiment=experiment,
                        item=item,
                        event=event,
                    )
                )
                self._learning_record_writer.append_record(learning_record)
            except Exception:
                pass
        self.learning_state.selected_staged_curation_group_id = group_id
        self.learning_state.selected_staged_curation_item_id = candidate.candidate_id
        self.refresh_analytics()
        self._notify_resume_state_changed()
        return event

    def set_staged_curation_face_triage_tier(
        self,
        group_id: str,
        item_id: str,
        tier: str,
    ) -> bool:
        """Persist a per-candidate face-triage tier in the discovered store."""
        normalized = str(tier or "medium").strip().lower() or "medium"
        if normalized not in set(self.get_staged_curation_face_triage_tier_options()):
            normalized = "medium"
        store = self._get_discovered_store()
        saved = store.save_item_extra_fields(
            group_id,
            item_id,
            {"face_triage_tier": normalized},
        )
        if saved:
            self.learning_state.selected_staged_curation_group_id = group_id
            self.learning_state.selected_staged_curation_item_id = item_id
            self._notify_resume_state_changed()
        return saved

    def submit_staged_curation_advancement(
        self,
        group_id: str,
        target_stage: str,
        *,
        candidate_ids: list[str] | None = None,
        recommendation_patch: dict[str, Any] | None = None,
    ) -> int:
        """Compile staged-curation selections into queue-backed derived jobs."""
        plan = self.build_staged_curation_advancement_plan(
            group_id,
            target_stage,
            candidate_ids=candidate_ids,
            recommendation_patch=recommendation_patch,
        )
        if plan is None or not plan.jobs:
            return 0

        job_service = self._get_job_service()
        if job_service is None or not hasattr(job_service, "submit_njrs"):
            raise RuntimeError("Job service is not available for staged-curation advancement")
        from src.controller.reprocess_admission import submit_reprocess_njrs

        return submit_reprocess_njrs(job_service, list(plan.jobs))

    def build_staged_curation_review_handoff(
        self,
        group_id: str,
        target_stage: str,
        *,
        candidate_id: str | None = None,
    ) -> ReviewWorkspaceHandoff | None:
        """Build a Review workspace handoff without enqueueing staged-curation jobs."""
        candidate_ids = [str(candidate_id)] if str(candidate_id or "").strip() else None
        plan = self.build_staged_curation_advancement_plan(
            group_id,
            target_stage,
            candidate_ids=candidate_ids,
        )
        if plan is None:
            return None
        return self._review_workflow_adapter.build_staged_curation_handoff(plan=plan)

    def build_staged_curation_advancement_plan(
        self,
        group_id: str,
        target_stage: str,
        *,
        candidate_ids: list[str] | None = None,
        recommendation_patch: dict[str, Any] | None = None,
    ) -> CurationAdvancementPlan | None:
        """Build a staged-curation advancement plan without enqueueing it."""
        normalized_target = str(target_stage or "").strip().lower()
        if normalized_target not in {"refine", "face_triage", "upscale"}:
            raise ValueError(f"Unsupported staged-curation target stage: {target_stage!r}")
        target_stage_literal = cast(DerivedStage, normalized_target)

        store = self._get_discovered_store()
        experiment = store.load_group(group_id)
        if experiment is None:
            return None

        payload = self.load_staged_curation_group(group_id)
        if not isinstance(payload, dict):
            return None
        workflow = payload.get("workflow")
        latest_events = dict(payload.get("latest_events") or {})
        candidates = list(payload.get("candidates") or [])
        if not isinstance(workflow, CurationWorkflow):
            return None

        selections = self._build_curation_source_selections(
            experiment=experiment,
            candidates=candidates,
            latest_events=latest_events,
            target_stage=target_stage_literal,
            candidate_ids=candidate_ids,
        )
        fallback_config = self._get_baseline_config()
        if recommendation_patch:
            fallback_config = apply_derived_recommendation_patch(
                fallback_config,
                recommendation_patch,
                target_stage=target_stage_literal,
            )
        reprocess_plan = self._curation_workflow_builder.build_derived_stage_plan(
            workflow=workflow,
            target_stage=target_stage_literal,
            selections=selections,
            fallback_config=fallback_config,
            output_dir=self._resolve_learning_output_root(),
        )
        return CurationAdvancementPlan(
            workflow=workflow,
            target_stage=target_stage_literal,
            reprocess_plan=reprocess_plan,
            selections=selections,
            source_candidate_ids=[selection.candidate.candidate_id for selection in selections],
            source_items=[selection.source_item for selection in selections],
            selection_events=[selection.selection_event for selection in selections],
        )

    def preview_staged_curation_suggestions(
        self, group_id: str, item_id: str, target_stage: str
    ) -> dict[str, Any]:
        """Build a non-mutating recommendation diff for one derived-job intent."""
        if self._recommendation_engine is None:
            return {"target_stage": target_stage, "stage_patch": {}, "changes": []}
        experiment = self._get_discovered_store().load_group(group_id)
        if experiment is None:
            return {"target_stage": target_stage, "stage_patch": {}, "changes": []}
        item = next((candidate for candidate in experiment.items if candidate.item_id == item_id), None)
        if item is None:
            return {"target_stage": target_stage, "stage_patch": {}, "changes": []}
        recommendations = self._recommendation_engine.recommend(
            item.positive_prompt,
            target_stage,
            model=item.model,
            width=item.width or None,
            height=item.height or None,
        )
        return build_derived_recommendation_patch(
            recommendations,
            target_stage=target_stage,
            current_config=self._get_baseline_config(),
        )

    def _build_curation_workflow(self, experiment: Any) -> CurationWorkflow:
        return CurationWorkflow(
            workflow_id=f"curation:{experiment.group_id}",
            title=str(getattr(experiment, "display_name", "") or experiment.group_id),
            created_at=str(getattr(experiment, "created_at", "") or ""),
            status="scout_complete",
            root_prompt_fingerprint=str(getattr(experiment, "prompt_hash", "") or ""),
            root_config_fingerprint=f"discovered:{getattr(experiment, 'group_id', '')}",
            root_model=self._resolve_discovered_root_model(experiment),
            notes=str(getattr(experiment, "notes", "") or "") or None,
        )

    def _build_curation_candidate(self, experiment: Any, item: Any) -> CurationCandidate:
        return CurationCandidate(
            candidate_id=str(getattr(item, "item_id", "") or ""),
            workflow_id=f"curation:{getattr(experiment, 'group_id', '')}",
            stage=self._map_discovered_stage_to_curation_stage(
                str(getattr(item, "stage", "") or "")
            ),
            artifact_id=str(getattr(item, "artifact_path", "") or ""),
            job_id=str(getattr(item, "extra_fields", {}).get("job_id", "") or ""),
            njr_id=str(getattr(item, "extra_fields", {}).get("njr_id", "") or ""),
            parent_candidate_id=None,
            root_candidate_id=str(getattr(item, "item_id", "") or ""),
            prompt_fingerprint=str(getattr(experiment, "prompt_hash", "") or ""),
            config_fingerprint=f"discovered:{getattr(experiment, 'group_id', '')}:{getattr(item, 'item_id', '')}",
            model_name=str(getattr(item, "model", "") or ""),
            selected=False,
        )

    @staticmethod
    def _map_discovered_stage_to_curation_stage(stage: str) -> str:
        normalized = str(stage or "").strip().lower()
        if normalized == "adetailer":
            return "face_triage"
        if normalized == "upscale":
            return "upscale"
        if normalized in {"img2img", "refine"}:
            return "refine"
        if normalized == "final":
            return "final"
        return "scout"

    @staticmethod
    def _resolve_staged_curation_target_stage_for_decision(decision: str) -> str | None:
        normalized = str(decision or "").strip().lower()
        mapping = {
            "advanced_to_refine": "refine",
            "advanced_to_face_triage": "face_triage",
            "advanced_to_upscale": "upscale",
        }
        return mapping.get(normalized)

    @staticmethod
    def _resolve_discovered_root_model(experiment: Any) -> str:
        for item in list(getattr(experiment, "items", []) or []):
            model_name = str(getattr(item, "model", "") or "").strip()
            if model_name:
                return model_name
        return ""

    def _build_curation_source_selections(
        self,
        *,
        experiment: Any,
        candidates: list[Any],
        latest_events: dict[str, SelectionEvent],
        target_stage: str,
        candidate_ids: list[str] | None = None,
    ) -> list[CurationSourceSelection]:
        decision_map = {
            "refine": "advanced_to_refine",
            "face_triage": "advanced_to_face_triage",
            "upscale": "advanced_to_upscale",
        }
        desired_decision = decision_map.get(str(target_stage or "").strip().lower())
        if not desired_decision:
            return []

        item_by_id = {
            str(getattr(item, "item_id", "") or ""): item
            for item in list(getattr(experiment, "items", []) or [])
        }
        allowed_candidate_ids = {
            str(candidate_id).strip()
            for candidate_id in list(candidate_ids or [])
            if str(candidate_id).strip()
        }
        selections: list[CurationSourceSelection] = []
        for candidate in candidates:
            candidate_id = str(getattr(candidate, "candidate_id", "") or "")
            if not candidate_id:
                continue
            if allowed_candidate_ids and candidate_id not in allowed_candidate_ids:
                continue
            latest = latest_events.get(candidate_id)
            if latest is None or str(latest.decision or "") != desired_decision:
                continue
            item = item_by_id.get(candidate_id)
            if item is None:
                continue
            reprocess_item = self._build_reprocess_source_item_from_discovered_item(item)
            if reprocess_item is None:
                continue
            face_tier = str(getattr(item, "extra_fields", {}).get("face_triage_tier") or "medium")
            reprocess_item.metadata["curation_candidate"] = candidate
            reprocess_item.metadata["curation_selection_event"] = latest
            selections.append(
                CurationSourceSelection(
                    candidate=candidate,
                    source_item=item,
                    selection_event=latest,
                    reprocess_item=reprocess_item,
                    face_triage_tier=face_tier,
                )
            )
        return selections

    def _build_reprocess_source_item_from_discovered_item(
        self,
        item: DiscoveredReviewItem,
    ) -> ReprocessSourceItem | None:
        image_path = Path(
            resolve_output_artifact_path(str(getattr(item, "artifact_path", "") or "").strip())
        )
        if not image_path.exists():
            return None
        baseline = self._extract_reprocess_baseline_from_image(image_path)
        positive_prompt = str(baseline.get("prompt") or getattr(item, "positive_prompt", "") or "")
        negative_prompt = str(
            baseline.get("negative_prompt") or getattr(item, "negative_prompt", "") or ""
        )
        model = baseline.get("model") or getattr(item, "model", "") or None
        vae = baseline.get("vae")
        config = baseline.get("config") if isinstance(baseline.get("config"), dict) else {}
        metadata = {
            "baseline_source": "embedded_metadata" if baseline else "discovered_review",
        }
        return ReprocessSourceItem(
            input_image_path=str(image_path),
            prompt=positive_prompt,
            negative_prompt=negative_prompt,
            model=str(model).strip() or None,
            vae=str(vae).strip() if vae is not None and str(vae).strip() else None,
            config=dict(config),
            metadata=metadata,
        )

    def _extract_reprocess_baseline_from_image(self, image_path: Path) -> dict[str, Any]:
        try:
            metadata_result = extract_embedded_metadata(image_path)
        except Exception:
            return {}

        if metadata_result.status != "ok" or not isinstance(metadata_result.payload, dict):
            return {}

        payload = metadata_result.payload
        generation = payload.get("generation")
        if not isinstance(generation, dict):
            generation = {}
        stage_manifest = payload.get("stage_manifest")
        if not isinstance(stage_manifest, dict):
            stage_manifest = {}

        config = stage_manifest.get("config")
        if not isinstance(config, dict):
            config = {}

        model_value, vae_value = resolve_model_vae_fields(payload)
        if isinstance(model_value, str) and model_value.strip().lower() in {"unknown", "n/a"}:
            model_value = None
        if isinstance(vae_value, str) and vae_value.strip().lower() in {"unknown", "n/a"}:
            vae_value = None
        prompt_value, negative_prompt_value = resolve_prompt_fields(payload)
        if not config and isinstance(generation, dict):
            config = dict(generation)

        return {
            "prompt": prompt_value,
            "negative_prompt": negative_prompt_value,
            "model": model_value,
            "vae": vae_value,
            "config": config,
        }

    def _get_job_service(self) -> Any | None:
        execution_controller = getattr(self, "execution_controller", None)
        if execution_controller is not None:
            job_service = getattr(execution_controller, "job_service", None)
            if job_service is not None:
                return job_service
        if self.pipeline_controller is not None:
            return getattr(self.pipeline_controller, "_job_service", None)
        return None

    def _resolve_learning_output_root(self) -> str:
        configured_root = None
        config_manager = getattr(self.pipeline_controller, "_config_manager", None)
        getter = getattr(config_manager, "get_setting", None)
        if callable(getter):
            try:
                configured_root = getter("output_dir", None)
            except Exception:
                configured_root = None
        if not configured_root:
            try:
                configured_root = ConfigManager().get_setting("output_dir", "output")
            except Exception:
                configured_root = "output"
        return str(get_output_root(configured_root or "output", create=True))

    def _build_discovered_item_from_image_path(
        self,
        image_path: str,
        *,
        index: int,
    ) -> DiscoveredReviewItem | None:
        path_obj = Path(str(image_path or "").strip())
        if not path_obj.exists():
            return None
        result = extract_embedded_metadata(path_obj)
        payload = (
            result.payload if result.status == "ok" and isinstance(result.payload, dict) else {}
        )
        stage_manifest = payload.get("stage_manifest", {}) if isinstance(payload, dict) else {}
        if not isinstance(stage_manifest, dict):
            stage_manifest = {}
        config = stage_manifest.get("config", {})
        if not isinstance(config, dict):
            config = {}
        generation = payload.get("generation", {}) if isinstance(payload, dict) else {}
        if not isinstance(generation, dict):
            generation = {}
        resolved_prompt, resolved_negative_prompt = resolve_prompt_fields(payload)
        model_name, _vae_name = resolve_model_vae_fields(payload)
        stage_name = str(stage_manifest.get("stage") or payload.get("stage") or "txt2img")
        seed_value = (
            stage_manifest.get("final_seed") or generation.get("seed") or config.get("seed") or -1
        )
        portable_review_summary = self._review_metadata_service.read_review_summary(path_obj)
        extra_fields: dict[str, Any] = {
            "job_id": str(payload.get("job_id") or ""),
            "run_id": str(payload.get("run_id") or ""),
            "source": "manual_import",
        }
        if portable_review_summary is not None:
            extra_fields["portable_review_summary"] = portable_review_summary.to_dict()
        return DiscoveredReviewItem(
            item_id=f"manual-{index + 1}-{uuid.uuid4().hex[:8]}",
            artifact_path=str(path_obj),
            manifest_path=str(stage_manifest.get("manifest_path") or ""),
            stage=stage_name,
            model=str(model_name or ""),
            sampler=str(
                config.get("sampler_name")
                or config.get("sampler")
                or generation.get("sampler_name")
                or ""
            ),
            scheduler=str(config.get("scheduler") or generation.get("scheduler") or ""),
            steps=int(config.get("steps") or generation.get("steps") or 0),
            cfg_scale=float(config.get("cfg_scale") or generation.get("cfg_scale") or 0.0),
            seed=int(seed_value or -1),
            positive_prompt=str(resolved_prompt or ""),
            negative_prompt=str(resolved_negative_prompt or ""),
            width=int(config.get("width") or generation.get("width") or 0),
            height=int(config.get("height") or generation.get("height") or 0),
            extra_fields=extra_fields,
        )

    @staticmethod
    def _infer_varying_fields(items: list[DiscoveredReviewItem]) -> list[str]:
        fields = ("stage", "model", "sampler", "scheduler", "steps", "cfg_scale", "width", "height")
        varying: list[str] = []
        for field_name in fields:
            values = {getattr(item, field_name, None) for item in items}
            if len(values) > 1:
                varying.append(field_name)
        return varying

    @staticmethod
    def _hash_prompt(prompt_text: str) -> str:
        normalized = " ".join(str(prompt_text or "").strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _extract_history_entry_image_paths(self, entry: Any) -> list[str]:
        result = getattr(entry, "result", None)
        paths: list[str] = []
        if isinstance(result, dict):
            artifact = result.get("artifact")
            if isinstance(artifact, dict):
                paths.extend(extract_artifact_paths({"artifact": artifact}))
            variants = result.get("variants")
            if isinstance(variants, list):
                for variant in variants:
                    if isinstance(variant, dict):
                        paths.extend(extract_artifact_paths(variant))
            output_dir = result.get("output_dir") or result.get("output_folder")
            if output_dir:
                paths.extend(self._glob_image_paths(output_dir))
        snapshot = getattr(entry, "snapshot", None)
        if isinstance(snapshot, dict):
            normalized_job = snapshot.get("normalized_job", {})
            if isinstance(normalized_job, dict):
                output_dir = normalized_job.get("path_output_dir")
                if output_dir:
                    paths.extend(self._glob_image_paths(output_dir))
        deduped: list[str] = []
        seen: set[str] = set()
        for path in paths:
            text = str(path or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    @staticmethod
    def _glob_image_paths(root_path: str | Path) -> list[str]:
        root = Path(root_path)
        if not root.exists():
            return []
        paths: list[str] = []
        for candidate in sorted(root.rglob("*")):
            if candidate.is_file() and candidate.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
            }:
                paths.append(str(candidate))
        return paths

    @staticmethod
    def _build_history_import_display_name(entry: Any) -> str:
        prompt_pack_id = str(getattr(entry, "prompt_pack_id", "") or "").strip()
        if prompt_pack_id:
            return f"History Import - {prompt_pack_id}"
        job_id = str(getattr(entry, "job_id", "") or "history")
        return f"History Import - {job_id[:8]}"

    def trigger_background_scan(self, output_root: str, on_complete: Any | None = None) -> None:
        """Run an incremental output scan in a background thread.

        Parameters
        ----------
        output_root:
            Root directory to scan for image artifacts.
        on_complete:
            Optional callback(OutputScanResult) invoked on the Tk thread (through the
            application controller's GUI-thread dispatcher) when the scan completes;
            called directly when no dispatcher exists (headless).
        """
        import logging
        from pathlib import Path

        from src.learning.discovered_scan_service import apply_scan
        from src.learning.output_scan_models import OutputScanResult
        from src.learning.output_scanner import OutputScanner
        from src.utils.thread_registry import get_thread_registry

        def _run() -> None:
            root = Path(output_root)
            try:
                if not root.exists():
                    raise FileNotFoundError(f"missing scan root: {root}")
                if not root.is_dir():
                    raise NotADirectoryError(f"scan root is not a directory: {root}")
                store = self._get_discovered_store()
                scan_index = store.load_scan_index()
                scanner = OutputScanner(root, scan_index=scan_index)
                records = scanner.scan_incremental()

                # Controlled artifacts have their own Experiment Review and
                # must never become duplicate observational evidence.
                def _is_controlled(record: Any) -> bool:
                    context = (getattr(record, "extra_fields", {}) or {}).get(
                        "learning_context", {}
                    )
                    return isinstance(context, dict) and bool(context.get("experiment_id"))

                outcome = apply_scan(scanner, store, records, is_controlled=_is_controlled)

                result = OutputScanResult(
                    output_root=str(root),
                    success=True,
                    new_group_count=outcome.new_group_count,
                    record_count=outcome.record_count,
                )
            except Exception as exc:
                result = OutputScanResult(
                    output_root=str(root),
                    success=False,
                    reason=str(exc)[:240],
                )

            if callable(on_complete):
                # The callbacks update Tk variables and widgets, so they must run on the Tk thread. The application
                # controller's dispatcher is the single thread-safe path; without one (headless tests) call directly.
                dispatch = getattr(self.app_controller, "_run_in_gui_thread", None)
                try:
                    if callable(dispatch):
                        dispatch(lambda: on_complete(result))
                    else:
                        on_complete(result)
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Discovered-output scan completion callback failed", exc_info=True
                    )

        get_thread_registry().spawn(target=_run, name="discovered-scan", purpose="discovered output scan")

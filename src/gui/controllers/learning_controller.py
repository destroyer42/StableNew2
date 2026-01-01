# Subsystem: Learning
# Role: Bridges the learning GUI tab and the core learning subsystem.

from __future__ import annotations

from typing import Any

from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.recommendation_engine import RecommendationEngine


class LearningController:
    """Controller for learning experiment workflows."""

    def __init__(
        self,
        learning_state: LearningState,
        prompt_workspace_state: PromptWorkspaceState | None = None,
        pipeline_state: Any | None = None,  # Placeholder for PipelineState
        pipeline_controller: Any | None = None,  # PipelineController reference
        plan_table: Any | None = None,  # LearningPlanTable reference
        review_panel: Any | None = None,  # LearningReviewPanel reference
        learning_record_writer: LearningRecordWriter
        | None = None,  # LearningRecordWriter reference
        execution_controller: Any | None = None,  # PR-LEARN-002: LearningExecutionController
    ) -> None:
        self.learning_state = learning_state
        self.prompt_workspace_state = prompt_workspace_state
        self.pipeline_state = pipeline_state
        self.pipeline_controller = pipeline_controller
        self.execution_controller = execution_controller  # PR-LEARN-002: Backend controller
        self._plan_table = plan_table
        self._review_panel = review_panel
        self._learning_record_writer = learning_record_writer

        # Rating cache for current experiment
        self._rating_cache: dict[str, int] = {}  # {image_path: rating}

        # Initialize recommendation engine if record writer is available
        self._recommendation_engine: RecommendationEngine | None = None
        if learning_record_writer:
            self._recommendation_engine = RecommendationEngine(learning_record_writer.records_path)

    def update_experiment_design(self, experiment_data: dict[str, Any]) -> None:
        """Update the current experiment design from form data."""
        # Create LearningExperiment from form data
        experiment = LearningExperiment(
            name=experiment_data.get("name", ""),
            description=experiment_data.get("description", ""),
            baseline_config={},  # Will be populated from pipeline state later
            prompt_text=experiment_data.get("custom_prompt", "")
            if experiment_data.get("prompt_source") == "custom"
            else "",
            stage=experiment_data.get("stage", "txt2img"),
            variable_under_test=experiment_data.get("variable_under_test", ""),
            values=self._generate_values_from_range(
                experiment_data.get("start_value", 1.0),
                experiment_data.get("end_value", 10.0),
                experiment_data.get("step_value", 1.0),
            ),
            images_per_value=experiment_data.get("images_per_value", 1),
        )

        # Store in state
        self.learning_state.current_experiment = experiment

    def _generate_values_from_range(self, start: float, end: float, step: float) -> list[float]:
        """Generate list of values from start to end with given step."""
        values = []
        current = start
        while current <= end:
            values.append(round(current, 2))
            current += step
        return values

    def build_plan(self, experiment: LearningExperiment) -> None:
        """Build a learning plan from experiment definition."""
        from src.gui.learning_state import LearningVariant

        # Store the current experiment
        self.learning_state.current_experiment = experiment

        # Load existing ratings for this experiment
        self.load_existing_ratings()

        # Clear any existing plan
        self.learning_state.plan = []

        # Generate variants for each value in the experiment
        for value in experiment.values:
            variant = LearningVariant(
                experiment_id=experiment.name,  # Use experiment name as ID for now
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

    def _update_plan_table(self) -> None:
        """Update the learning plan table with current plan data."""
        if self._plan_table and hasattr(self._plan_table, "update_plan"):
            self._plan_table.update_plan(self.learning_state.plan)

    def load_existing_ratings(self) -> None:
        """Load existing ratings for the current experiment."""
        if not self._learning_record_writer:
            return
        if not self.learning_state.current_experiment:
            return

        experiment_id = self.learning_state.current_experiment.name
        self._rating_cache = self._learning_record_writer.get_ratings_for_experiment(
            experiment_id
        )

    def get_rating_for_image(self, image_path: str) -> int | None:
        """Get the rating for an image if it exists."""
        return self._rating_cache.get(image_path)

    def is_image_rated(self, image_path: str) -> bool:
        """Check if an image has been rated."""
        return image_path in self._rating_cache

    def _update_variant_status(self, variant_index: int, status: str) -> None:
        """Update the status of a specific variant in the table."""
        if self._plan_table and hasattr(self._plan_table, "update_row_status"):
            self._plan_table.update_row_status(variant_index, status)

    def _update_variant_images(self, variant_index: int, completed: int, planned: int) -> None:
        """Update the image count of a specific variant in the table."""
        if self._plan_table and hasattr(self._plan_table, "update_row_images"):
            self._plan_table.update_row_images(variant_index, completed, planned)

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
            return

        if not self.pipeline_controller:
            return

        # Clear all highlights before starting
        if self._plan_table and hasattr(self._plan_table, "clear_highlights"):
            self._plan_table.clear_highlights()

        # Submit jobs for each variant
        for variant in self.learning_state.plan:
            if variant.status == "pending":
                self._submit_variant_job(variant)

        # Update table (fallback for any variants that didn't get live updates)
        self._update_plan_table()

    def _submit_variant_job(self, variant: LearningVariant) -> None:
        """Submit a pipeline job for a single learning variant."""
        if not self.learning_state.current_experiment or not self.pipeline_controller:
            return

        experiment = self.learning_state.current_experiment

        # Build overrides for this variant based on variable_under_test
        overrides = self._build_variant_overrides(variant, experiment)
        
        # Build learning metadata for provenance
        learning_metadata = {
            "learning_enabled": True,
            "learning_experiment_name": experiment.name,
            "learning_stage": experiment.stage,
            "learning_variable": experiment.variable_under_test,
            "learning_variant_value": variant.param_value,
            "variant_index": self._get_variant_index(variant),
        }

        # Submit the job via queue submission (not broken start_pipeline)
        try:
            from src.gui.app_state_v2 import PackJobEntry
            
            # Build PackJobEntry with learning metadata
            pack_entry = PackJobEntry(
                pack_id=f"learning_{experiment.name}_{variant.param_value}",
                pack_name=f"Learning: {experiment.name} ({experiment.variable_under_test}={variant.param_value})",
                config_snapshot=overrides,
                prompt_text=experiment.prompt_text or "",
                negative_prompt_text="",
                learning_metadata=learning_metadata,  # PR-LEARN-001: Add learning provenance
            )
            
            # Submit via pipeline controller's queue submission
            if hasattr(self.pipeline_controller, "queue_controller"):
                queue_controller = self.pipeline_controller.queue_controller
                if hasattr(queue_controller, "submit_pack_job"):
                    success = queue_controller.submit_pack_job(pack_entry)
                    
                    if success:
                        variant.status = "queued"
                        variant_index = self._get_variant_index(variant)
                        if variant_index >= 0:
                            self._update_variant_status(variant_index, "queued")
                            self._highlight_variant(variant_index, True)
                    else:
                        variant.status = "failed"
                        variant_index = self._get_variant_index(variant)
                        if variant_index >= 0:
                            self._update_variant_status(variant_index, "failed")
                else:
                    # Fallback: Try app_state queue submission
                    if hasattr(self.pipeline_controller, "app_state"):
                        app_state = self.pipeline_controller.app_state
                        if hasattr(app_state, "job_draft"):
                            app_state.job_draft.packs.append(pack_entry)
                            variant.status = "queued"
            else:
                # No queue controller available
                variant.status = "failed"

        except Exception as exc:
            variant.status = "failed"
            variant_index = self._get_variant_index(variant)
            if variant_index >= 0:
                self._update_variant_status(variant_index, "failed")

    def _build_variant_overrides(
        self, variant: LearningVariant, experiment: LearningExperiment
    ) -> dict[str, Any]:
        """Build pipeline overrides for a learning variant."""
        overrides = {}

        # Apply the variable under test
        variable = experiment.variable_under_test
        value = variant.param_value

        if variable == "CFG Scale":
            overrides["cfg_scale"] = value
        elif variable == "Steps":
            overrides["steps"] = int(value)
        elif variable == "Sampler":
            overrides["sampler"] = str(value)
        elif variable == "Scheduler":
            overrides["scheduler"] = str(value)
        elif variable.startswith("LoRA Strength"):
            # For LoRA strength, we'd need to handle this differently
            # For now, just store the value
            overrides["lora_strength"] = value
        elif variable == "Denoise Strength":
            overrides["denoise_strength"] = value
        elif variable == "Upscale Factor":
            overrides["upscale_factor"] = value

        # Add learning context
        overrides["learning_experiment_id"] = experiment.name
        overrides["learning_variant_value"] = value
        overrides["learning_variable"] = variable

        return overrides

    def _on_variant_job_completed(self, variant: LearningVariant, result: dict[str, Any]) -> None:
        """Handle completion of a variant job.
        
        PR-LEARN-004: Updates variant status and refreshes UI table.
        PR-LEARN-005: Extracts and links output images to variant.
        """
        variant.status = "completed"
        variant.completed_images += 1

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

        # PR-LEARN-004: Update UI with live updates
        variant_index = self._get_variant_index(variant)
        if variant_index >= 0:
            self._update_variant_status(variant_index, "completed")
            self._update_variant_images(
                variant_index, variant.completed_images, variant.planned_images
            )
            self._highlight_variant(variant_index, False)  # Remove highlight

        # Update review panel if this variant is selected
        if self._review_panel and hasattr(self._review_panel, "display_variant_results"):
            self._review_panel.display_variant_results(variant)

    def _on_variant_job_failed(self, variant: LearningVariant, error: Exception) -> None:
        """Handle failure of a variant job."""
        variant.status = "failed"

        # Update UI with live updates
        variant_index = self._get_variant_index(variant)
        if variant_index >= 0:
            self._update_variant_status(variant_index, "failed")
            self._highlight_variant(variant_index, False)  # Remove highlight

    def on_job_completed(self, job_id: str, result: dict[str, Any]) -> None:
        """Handle completion of a learning job."""
        # This method can be used for general job completion handling
        # The specific variant handling is done in _on_variant_job_completed
        pass

    def record_rating(self, image_ref: str, rating: int, notes: str = "") -> None:
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

        # Create a learning record for this rating
        experiment = self.learning_state.current_experiment

        # Build base config from experiment
        base_config = {
            "prompt": experiment.prompt_text,
            "stage": experiment.stage,
            experiment.variable_under_test.lower(): target_variant.param_value,
        }

        # Create variant config
        variant_config = {experiment.variable_under_test.lower(): target_variant.param_value}

        # Create learning record
        record = LearningRecord.from_pipeline_context(
            base_config=base_config,
            variant_configs=[variant_config],
            randomizer_mode="learning_experiment",
            randomizer_plan_size=1,
            metadata={
                "experiment_name": experiment.name,
                "experiment_description": experiment.description,
                "variable_under_test": experiment.variable_under_test,
                "variant_value": target_variant.param_value,
                "image_path": image_ref,
                "user_rating": rating,
                "user_notes": notes,
                "learning_context": {
                    "experiment_id": experiment.name,
                    "variant_id": target_variant.id
                    if hasattr(target_variant, "id")
                    else str(target_variant.param_value),
                    "variant_name": f"{experiment.variable_under_test}={target_variant.param_value}",
                },
            },
        )

        # Write the record
        self._learning_record_writer.append_record(record)

        # Update recommendations after recording a rating
        self.update_recommendations()

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
            recommendations = self._recommendation_engine.recommend(prompt_text, stage)

            # Update review panel with new recommendations
            if self._review_panel and hasattr(self._review_panel, "update_recommendations"):
                self._review_panel.update_recommendations(recommendations)

    def get_recommendations_for_current_prompt(self) -> Any | None:
        """Get recommendations for the current prompt and stage."""
        if not self._recommendation_engine:
            return None

        # Get current prompt and stage
        prompt_text = ""
    
    def on_job_completed_callback(
        self, 
        job: Any, 
        result: Any
    ) -> None:
        """Handle job completion events from the pipeline.
        
        PR-LEARN-003: This is registered as a callback with JobService to receive
        notifications when learning-related jobs complete.
        
        Args:
            job: Job object (contains snapshot with NJR)
            result: Result dict with 'success', 'status', 'error' fields
        """
        # Extract NJR from job snapshot
        njr = getattr(job, "snapshot", None)
        if not njr:
            return
        
        # Check if this is a learning job
        learning_ctx = getattr(njr, "learning_context", None)
        if not learning_ctx:
            return
        
        # Check if it belongs to our current experiment
        if not self.learning_state.current_experiment:
            return
        
        if learning_ctx.experiment_id != self.learning_state.current_experiment.name:
            return
        
        # Find the variant by index
        variant_index = learning_ctx.variant_index
        if variant_index < 0 or variant_index >= len(self.learning_state.plan):
            return
        
        variant = self.learning_state.plan[variant_index]
        
        # Update variant based on result
        success = result.get("success", False) if isinstance(result, dict) else getattr(result, "success", False)
        if success:
            self._on_variant_job_completed(variant, result)
        else:
            error_msg = result.get("error", "Unknown error") if isinstance(result, dict) else getattr(result, "error", "Unknown error")
            error = Exception(str(error_msg))
            self._on_variant_job_failed(variant, error)

    def get_recommendations_for_current_prompt(self) -> Any | None:
        """Get recommendations for the current prompt and stage."""
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
            return self._recommendation_engine.recommend(prompt_text, stage)

        return None

    def refresh_recommendations(self) -> None:
        """Force refresh of recommendations, clearing any cache."""
        if self._recommendation_engine:
            # Force reload by clearing cache timestamp
            self._recommendation_engine._cache_timestamp = 0.0
            self.update_recommendations()

    def on_variant_selected(self, variant_index: int) -> None:
        """Handle selection of a variant in the table."""
        if 0 <= variant_index < len(self.learning_state.plan):
            variant = self.learning_state.plan[variant_index]
            if self._review_panel and hasattr(self._review_panel, "display_variant_results"):
                self._review_panel.display_variant_results(
                    variant, self.learning_state.current_experiment
                )

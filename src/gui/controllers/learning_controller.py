# Subsystem: Learning
# Role: Bridges the learning GUI tab and the core learning subsystem.

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.recommendation_engine import RecommendationEngine
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.queue.job_model import Job, JobPriority


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
        self.prompt_workspace_state = prompt_workspace_state
        self.pipeline_state = pipeline_state
        
        # PR-LEARN-012: Validate required dependencies
        if not pipeline_controller:
            raise RuntimeError(
                "LearningController requires pipeline_controller. "
                "Ensure MainWindow passes pipeline_controller to LearningTabFrame."
            )
        
        self.pipeline_controller = pipeline_controller
        self.app_controller = app_controller  # Store app_controller for stage card access
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
        
        # PR-LEARN-012: Set up execution controller callbacks
        if self.execution_controller:
            self.execution_controller.set_completion_callback(self._on_variant_job_completed)
            self.execution_controller.set_failure_callback(self._on_variant_job_failed)

    def update_experiment_design(self, experiment_data: dict[str, Any]) -> None:
        """Update the current experiment design from form data."""
        # Determine prompt text based on prompt_source
        prompt_text = ""
        prompt_source = experiment_data.get("prompt_source", "custom")
        
        if prompt_source == "custom":
            prompt_text = experiment_data.get("custom_prompt", "")
        elif prompt_source == "current" and self.prompt_workspace_state:
            # BUGFIX: Use current prompt pack when source is 'current'
            prompt_text = self.prompt_workspace_state.get_current_prompt_text() or ""
        
        # Create LearningExperiment from form data
        experiment = LearningExperiment(
            name=experiment_data.get("name", ""),
            description=experiment_data.get("description", ""),
            baseline_config={},  # Will be populated from pipeline state later
            prompt_text=prompt_text,
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
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("[LearningController] run_plan() called")
        logger.info(f"[LearningController]   Plan exists: {bool(self.learning_state.plan)}")
        logger.info(f"[LearningController]   Plan length: {len(self.learning_state.plan) if self.learning_state.plan else 0}")
        logger.info(f"[LearningController]   Pipeline controller: {self.pipeline_controller is not None}")
        
        if not self.learning_state.plan:
            logger.warning("[LearningController] No plan exists, exiting run_plan()")
            return

        if not self.pipeline_controller:
            logger.error("[LearningController] No pipeline controller, exiting run_plan()")
            return
        
        logger.info(f"[LearningController] Starting to submit {len(self.learning_state.plan)} variants")

        # Clear all highlights before starting
        if self._plan_table and hasattr(self._plan_table, "clear_highlights"):
            self._plan_table.clear_highlights()

        # Submit jobs for each variant
        for variant in self.learning_state.plan:
            if variant.status == "pending":
                logger.info(f"[LearningController] Submitting pending variant: {variant.param_value}")
                self._submit_variant_job(variant)
                
                # Clear job draft after each submission to avoid duplicates
                app_state = getattr(self.pipeline_controller, "_app_state", None)
                if app_state and hasattr(app_state, "clear_job_draft"):
                    try:
                        app_state.clear_job_draft()
                    except Exception:
                        pass

        # Update table (fallback for any variants that didn't get live updates)
        self._update_plan_table()

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
        
        if not self.execution_controller:
            logger.error("[LearningController] Cannot submit: execution_controller not initialized")
            variant.status = "failed"
            return

        experiment = self.learning_state.current_experiment
        
        # PR-LEARN-011: Log submission attempt
        logger.info(f"[LearningController] Submitting variant job: experiment={experiment.name}, variant={variant.param_value}, variable={experiment.variable_under_test}")

        try:
            # PR-LEARN-010: Build NJR directly with explicit config fields
            record = self._build_variant_njr(variant, experiment)
            logger.info(f"[LearningController] Built NJR for variant: {variant.param_value}")
            
            # PR-LEARN-013: Delegate to LearningExecutionController which handles:
            # 1. Job creation and submission to JobService
            # 2. _job_to_variant mapping for callback tracking
            # 3. Job completion callbacks
            success = self.execution_controller.submit_variant_job(
                record=record,
                variant=variant,
                experiment_name=experiment.name,
                variable_under_test=experiment.variable_under_test,
            )
            
            if success:
                # PR-LEARN-011: Log successful submission
                logger.info(f"[LearningController] ✓ Successfully submitted job via LearningExecutionController: {record.job_id}")
                logger.info(f"[LearningController]   Experiment: {experiment.name}")
                logger.info(f"[LearningController]   Variable: {experiment.variable_under_test} = {variant.param_value}")
                logger.info(f"[LearningController]   Status: queued")
                
                # Update variant status
                variant.status = "queued"
                variant_index = self._get_variant_index(variant)
                if variant_index >= 0:
                    self._update_variant_status(variant_index, "queued")
                    self._highlight_variant(variant_index, True)
            else:
                raise RuntimeError("LearningExecutionController.submit_variant_job() returned False")

        except Exception as exc:
            logger.exception(f"[LearningController] Error submitting variant job: {exc}")
            variant.status = "failed"
            variant_index = self._get_variant_index(variant)
            if variant_index >= 0:
                self._update_variant_status(variant_index, "failed")

    def _build_variant_njr(
        self, variant: LearningVariant, experiment: LearningExperiment
    ) -> NormalizedJobRecord:
        """Build NormalizedJobRecord with explicit config from stage cards.
        
        PR-LEARN-010: Constructs NJR directly with all config fields populated,
        bypassing PackJobEntry to ensure proper config propagation.
        
        PR-LEARN-011: Enhanced with validation and comprehensive logging.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Get baseline config from stage cards
        baseline = self._get_baseline_config()
        
        # PR-LEARN-011: Validate baseline config
        is_valid, error_msg = self._validate_baseline_config(baseline)
        if not is_valid:
            logger.error(f"[LearningController] Baseline config validation failed: {error_msg}")
            raise ValueError(f"Invalid baseline config: {error_msg}")
        
        txt2img_config = baseline.get("txt2img", {})
        
        # Build overrides for this variant
        variant_overrides = self._build_variant_overrides(variant, experiment)
        
        # PR-LEARN-011: Log variant overrides
        logger.info(f"[LearningController] Variant overrides for {variant.param_value}: {variant_overrides}")
        
        # Apply overrides to txt2img section
        final_config = self._apply_overrides_to_config(baseline, variant_overrides, experiment)
        txt2img_final = final_config.get("txt2img", {})
        
        # Extract explicit config values
        model = txt2img_final.get("model", "")
        vae = txt2img_final.get("vae", "")
        sampler = txt2img_final.get("sampler_name", "Euler a")
        scheduler = txt2img_final.get("scheduler", "normal")
        steps = int(txt2img_final.get("steps", 20))
        cfg_scale = float(txt2img_final.get("cfg_scale", 7.0))
        width = int(txt2img_final.get("width", 512))
        height = int(txt2img_final.get("height", 512))
        seed = int(txt2img_final.get("seed", -1))
        clip_skip = int(txt2img_final.get("clip_skip", 2))
        
        # Debug logging for seed value
        logger.info(f"[LearningController]   seed from config: {seed} (default=-1)")
        if seed == -1:
            logger.warning(f"[LearningController]   WARNING: Seed is -1 (random), check if stage card has seed set")
        
        # Subseed parameters
        subseed = int(txt2img_final.get("subseed", -1))
        subseed_strength = float(txt2img_final.get("subseed_strength", 0.0))
        seed_resize_from_h = int(txt2img_final.get("seed_resize_from_h", 0))
        seed_resize_from_w = int(txt2img_final.get("seed_resize_from_w", 0))
        
        # Get prompt from experiment or current prompt workspace
        prompt = experiment.prompt_text
        if not prompt:
            # If no prompt in experiment, get from current prompt workspace
            if self.prompt_workspace_state:
                prompt = self.prompt_workspace_state.get_current_prompt_text() or ""
        if not prompt:
            # Final fallback
            prompt = "a test prompt"
        
        # Get negative prompt from experiment or current prompt workspace
        negative_prompt = getattr(experiment, "negative_prompt_text", "") or ""
        if not negative_prompt and self.prompt_workspace_state:
            negative_prompt = self.prompt_workspace_state.get_current_negative_text() or ""
        
        # PR-LEARN-011: Comprehensive logging of final config
        logger.info(f"[LearningController] Building NJR for variant {variant.param_value}")
        logger.info(f"[LearningController]   model: {model}")
        logger.info(f"[LearningController]   vae: {vae}")
        logger.info(f"[LearningController]   sampler: {sampler}")
        logger.info(f"[LearningController]   scheduler: {scheduler}")
        logger.info(f"[LearningController]   steps: {steps}")
        logger.info(f"[LearningController]   cfg_scale: {cfg_scale}")
        logger.info(f"[LearningController]   seed: {seed}")
        logger.info(f"[LearningController]   prompt: {prompt[:50]}..." if len(prompt) > 50 else f"[LearningController]   prompt: {prompt}")
        
        # Generate job ID
        job_id = f"learning_{experiment.name}_{variant.param_value}_{uuid.uuid4().hex[:8]}"
        
        # Build stage_chain (required for job validation)
        txt2img_stage = StageConfig(
            stage_type="txt2img",
            enabled=True,
            steps=steps,
            cfg_scale=cfg_scale,
            sampler_name=sampler,
            scheduler=scheduler,
            model=model,
            vae=vae,
            extra={},
        )
        
        # Build learning context for tracking and metadata
        from src.pipeline.job_models_v2 import LearningJobContext
        learning_ctx = LearningJobContext(
            experiment_id=experiment.name,
            experiment_name=experiment.name,
            variant_index=0,  # Not used for single variant jobs
            variable_under_test=experiment.variable_under_test,
            variant_value=variant.param_value,
        )
        
        # Build NormalizedJobRecord
        record = NormalizedJobRecord(
            job_id=job_id,
            positive_prompt=prompt,
            negative_prompt=negative_prompt,
            base_model=model,
            vae=vae,
            sampler_name=sampler,
            scheduler=scheduler,
            steps=steps,
            cfg_scale=cfg_scale,
            width=width,
            height=height,
            seed=seed,
            clip_skip=clip_skip,
            prompt_pack_id=f"learning_{experiment.name}",
            stage_chain=[txt2img_stage],  # Required: at least one stage
            learning_context=learning_ctx,  # For metadata and tracking
            extra_metadata={
                "learning_enabled": True,
                "learning_experiment": experiment.name,
                "learning_variable": experiment.variable_under_test,
                "learning_variant_value": variant.param_value,
                "subseed": subseed,
                "subseed_strength": subseed_strength,
                "seed_resize_from_h": seed_resize_from_h,
                "seed_resize_from_w": seed_resize_from_w,
            },
            config={},  # Empty config dict
            path_output_dir="",  # Will be set by runner
            filename_template="",  # Will be set by runner
        )
        
        # PR-LEARN-011: Confirm NJR construction
        logger.info(f"[LearningController] Successfully built NJR: job_id={record.job_id}")
        
        return record

    # PR-LEARN-013: Removed _njr_to_queue_job() and _execute_learning_job()
    # These are now handled by LearningExecutionController.submit_variant_job()
    # which properly tracks jobs in the _job_to_variant mapping for callbacks.

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
            logger.warning("[LearningController] Baseline config missing 'pipeline' section, will use defaults")
        
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
        
        # Optional fields (checked but not required to be non-empty)
        optional_fields = {
            "vae": "VAE name",  # Optional - models can have baked VAE
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
            logger.info(f"[LearningController]   sampler_name: {txt2img.get('sampler_name', 'MISSING')}")
            logger.info(f"[LearningController]   scheduler: {txt2img.get('scheduler', 'MISSING')}")
            logger.info(f"[LearningController]   steps: {txt2img.get('steps', 'MISSING')}")
            logger.info(f"[LearningController]   cfg_scale: {txt2img.get('cfg_scale', 'MISSING')}")
            logger.info(f"[LearningController]   seed: {txt2img.get('seed', 'MISSING')}")
        else:
            logger.error("[LearningController]   txt2img section MISSING")
        
        if "pipeline" in config:
            pipeline = config["pipeline"]
            logger.info(f"[LearningController]   pipeline keys: {list(pipeline.keys())}")
            logger.info(f"[LearningController]   batch_size: {pipeline.get('batch_size', 'MISSING')}")
        else:
            logger.warning("[LearningController]   pipeline section MISSING")

    def _get_baseline_config(self) -> dict[str, Any]:
        """Get baseline configuration from current GUI state.
        
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
                if stage_panel and hasattr(stage_panel, "txt2img_card"):
                    txt2img_card = stage_panel.txt2img_card
                    if hasattr(txt2img_card, "to_config_dict"):
                        card_config = txt2img_card.to_config_dict()
                        logger.info(f"[LearningController] Got stage card config: keys={list(card_config.keys())}")
                        txt2img_section = card_config.get("txt2img", {})
                        logger.info(f"[LearningController] txt2img section keys: {list(txt2img_section.keys())}")
                        logger.info(f"[LearningController] txt2img model={txt2img_section.get('model')}, vae={txt2img_section.get('vae')}")
                        
                        # BUGFIX: Accept config if model exists (VAE can be empty for baked VAE models)
                        if txt2img_section.get("model") or txt2img_section.get("model_name"):
                            # Successfully got config from stage card
                            baseline = card_config
                            
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
                            logger.info(f"[LearningController] Successfully loaded baseline config from stage cards")
                            return baseline
                        else:
                            logger.warning(f"[LearningController] Stage card has no model/VAE, falling back")
            except Exception as exc:
                logger.exception(f"[LearningController] Failed to get stage card config: {exc}")
        else:
            logger.warning(f"[LearningController] No app_controller or _get_stage_cards_panel method")
        
        # Fallback: Try to get config from app_state
        logger.warning(f"[LearningController] Using fallback baseline config")
        app_state = getattr(self.pipeline_controller, "_app_state", None) if self.pipeline_controller else None
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
        self, baseline_config: dict[str, Any], overrides: dict[str, Any], experiment: LearningExperiment
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

    def _on_variant_job_completed(self, variant: LearningVariant, result: dict[str, Any]) -> None:
        """Handle completion of a variant job.
        
        PR-LEARN-004: Updates variant status and refreshes UI table.
        PR-LEARN-005: Extracts and links output images to variant.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Variant {variant.param_value} completed")
        
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
        
        # Update rating cache
        self._rating_cache[image_ref] = rating
        
        # Refresh recommendations with new data
        self.refresh_recommendations()
        
        # Update plan table with new average rating
        self._update_variant_ratings()

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

    def _update_variant_ratings(self) -> None:
        """Update all variant rows with their average ratings."""
        if not self._learning_record_writer or not self.learning_state.current_experiment:
            return
        
        experiment_id = self.learning_state.current_experiment.name
        
        for i, variant in enumerate(self.learning_state.plan):
            avg = self._learning_record_writer.get_average_rating_for_variant(
                experiment_id, 
                variant.param_value
            )
            
            if self._plan_table and hasattr(self._plan_table, "update_row_rating"):
                self._plan_table.update_row_rating(i, avg)
    
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
    
    def apply_recommendations_to_pipeline(self, recommendations: Any) -> bool:
        """Apply recommendations to the pipeline stage cards.
        
        Returns True if successful, False otherwise.
        """
        if not self.pipeline_controller:
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
        
        applied = 0
        for rec in rec_list:
            if hasattr(rec, "parameter_name"):
                param = rec.parameter_name
                value = rec.recommended_value
            elif isinstance(rec, dict):
                param = rec.get("parameter", "")
                value = rec.get("value")
            else:
                continue
            
            if self._apply_single_recommendation(stage_cards, param, value):
                applied += 1
        
        return applied > 0
    
    def _apply_single_recommendation(
        self, 
        stage_cards: Any, 
        param: str, 
        value: Any
    ) -> bool:
        """Apply a single recommendation to stage cards."""
        param_lower = param.lower().replace(" ", "_")
        
        # Map parameter names to stage card attributes
        param_map = {
            "cfg_scale": ("txt2img_card", "cfg_var"),
            "cfg": ("txt2img_card", "cfg_var"),
            "steps": ("txt2img_card", "steps_var"),
            "sampler": ("txt2img_card", "sampler_var"),
            "scheduler": ("txt2img_card", "scheduler_var"),
            "denoise_strength": ("img2img_card", "denoise_var"),
            "denoising_strength": ("img2img_card", "denoise_var"),
            "upscale_factor": ("upscale_card", "factor_var"),
        }
        
        mapping = param_map.get(param_lower)
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
            
            var.set(value)
            return True
        except Exception:
            return False
    
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

"""Learning job execution controller.

Coordinates submission and completion tracking for learning experiments.

PR-LEARN-012: Wires up execution controller for proper job lifecycle management.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from src.gui.learning_state import LearningState, LearningVariant
from src.pipeline.artifact_contract import extract_artifact_paths
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.job_requests_v2 import (
    PipelineRunMode,
    PipelineRunRequest,
    PipelineRunSource,
)

_logger = logging.getLogger(__name__)


@dataclass
class LearningJobContext:
    """Context for a learning job submission."""
    variant: LearningVariant
    experiment_name: str
    variable_under_test: str
    variant_value: Any
    job_id: str


class LearningExecutionController:
    """Coordinates learning job submission and completion tracking.
    
    PR-LEARN-012: This controller:
    - Submits NJRs via JobService
    - Tracks job-to-variant mapping
    - Handles job completion callbacks
    - Extracts and stores image references
    - Updates variant status
    """
    
    def __init__(
        self,
        learning_state: LearningState,
        job_service: Any = None,
    ):
        """Initialize execution controller.
        
        Args:
            learning_state: Learning state container
            job_service: JobService for queue submission
        """
        _logger.info("[LearningExecutionController] __init__ called")
        _logger.info(f"[LearningExecutionController]   learning_state: {learning_state is not None}")
        _logger.info(f"[LearningExecutionController]   job_service: {job_service is not None}")
        
        self.learning_state = learning_state
        self.job_service = job_service
        
        # Track job_id -> variant mapping
        self._job_to_variant: dict[str, LearningVariant] = {}
        
        # Track job_id -> context mapping
        self._job_contexts: dict[str, LearningJobContext] = {}
        
        # Completion callbacks
        self._on_variant_completed: Callable[[LearningVariant, dict], None] | None = None
        self._on_variant_failed: Callable[[LearningVariant, Exception], None] | None = None
        
        # Register with JobService to receive completion notifications
        _logger.info(f"[LearningExecutionController] Checking job_service for callback registration...")
        _logger.info(f"[LearningExecutionController]   job_service is None: {self.job_service is None}")
        if self.job_service:
            _logger.info(f"[LearningExecutionController]   hasattr register_callback: {hasattr(self.job_service, 'register_callback')}")

        can_register_callbacks = bool(
            self.job_service and hasattr(self.job_service, 'register_callback')
        )
        if not can_register_callbacks:
            _logger.warning(
                "[LearningExecutionController] Could not register callbacks: "
                "job_service unavailable or missing method"
            )
            return

        _logger.info("[LearningExecutionController] Registering callbacks...")
        self.job_service.register_callback('job_finished', self._handle_job_finished)
        self.job_service.register_callback('job_failed', self._handle_job_failed)
        _logger.info(
            "[LearningExecutionController] Registered job completion callbacks with JobService"
        )
        return
        
        if self.job_service and hasattr(self.job_service, 'register_callback'):
            _logger.info("[LearningExecutionController] Registering callbacks...")
            self.job_service.register_callback('job_finished', self._handle_job_finished)
            self.job_service.register_callback('job_failed', self._handle_job_failed)
            _logger.info("[LearningExecutionController] ✓ Registered job completion callbacks with JobService")
        else:
            _logger.warning("[LearningExecutionController] ⚠ Could NOT register callbacks - job_service unavailable or missing method")
    
    def _handle_job_finished(self, job: Any) -> None:
        """Handle job completion event from JobService."""
        job_id = getattr(job, 'job_id', None)
        if not job_id:
            return
        
        # Check if this is a learning job
        if job_id not in self._job_to_variant:
            return
        
        # Extract result data from job
        # PR-LEARN-013: Get image paths from job.result["variants"]
        job_result = getattr(job, 'result', {}) or {}
        variants = job_result.get('variants', [])
        
        # Extract all image paths from variants
        image_paths = []
        _logger.info(f"[ExecutionController] Processing job {job_id}, found {len(variants)} variants in result")
        for idx, variant in enumerate(variants):
            if isinstance(variant, dict):
                _logger.info(f"[ExecutionController] Variant {idx} keys: {list(variant.keys())}")
                paths = extract_artifact_paths(variant)
                if paths:
                    image_paths.extend(paths)
                    _logger.info(f"[ExecutionController] Variant {idx} yielded {len(paths)} artifact path(s)")
                else:
                    _logger.warning(f"[ExecutionController] Variant {idx} has no recognized path keys")
        
        result = {
            'status': 'completed',
            'images': image_paths,
            'output_paths': image_paths,
            'variants': variants,  # Include full variant data for metadata
        }
        
        _logger.info(f"[ExecutionController] Job {job_id} finished: extracted {len(image_paths)} images total")
        self.on_job_completed(job_id, result)
    
    def _handle_job_failed(self, job: Any, error: Any = None) -> None:
        """Handle job failure event from JobService."""
        job_id = getattr(job, 'job_id', None)
        if not job_id:
            return
        
        # Check if this is a learning job
        if job_id not in self._job_to_variant:
            return
        
        error_msg = str(error) if error else "Job failed"
        _logger.info(f"[LearningExecutionController] Job failed notification: {job_id} - {error_msg}")
        self.on_job_failed(job_id, Exception(error_msg))
    
    def set_completion_callback(self, callback: Callable[[LearningVariant, dict], None]) -> None:
        """Set callback for variant job completion."""
        self._on_variant_completed = callback
    
    def set_failure_callback(self, callback: Callable[[LearningVariant, Exception], None]) -> None:
        """Set callback for variant job failure."""
        self._on_variant_failed = callback
    
    def submit_variant_job(
        self,
        record: NormalizedJobRecord,
        variant: LearningVariant,
        experiment_name: str,
        variable_under_test: str,
    ) -> bool:
        """Submit a learning job via JobService.
        
        Args:
            record: NormalizedJobRecord to submit
            variant: LearningVariant this job is for
            experiment_name: Name of experiment
            variable_under_test: Variable being tested
            
        Returns:
            True if submitted successfully
        """
        if not self.job_service:
            _logger.error("[LearningExecutionController] No JobService available")
            return False
        if not hasattr(self.job_service, "enqueue_njrs"):
            _logger.error("[LearningExecutionController] JobService missing enqueue_njrs()")
            return False
        
        try:
            # Track variant mapping
            self._job_to_variant[record.job_id] = variant
            self._job_contexts[record.job_id] = LearningJobContext(
                variant=variant,
                experiment_name=experiment_name,
                variable_under_test=variable_under_test,
                variant_value=variant.param_value,
                job_id=record.job_id,
            )
            
            run_request = self._build_run_request(
                record=record,
                experiment_name=experiment_name,
                variable_under_test=variable_under_test,
            )
            self.job_service.enqueue_njrs([record], run_request)
            
            _logger.info(
                f"[LearningExecutionController] Submitted job: "
                f"job_id={record.job_id}, experiment={experiment_name}, "
                f"variant={variant.param_value}"
            )
            
            return True
            
        except Exception as exc:
            self._job_to_variant.pop(record.job_id, None)
            self._job_contexts.pop(record.job_id, None)
            _logger.exception(f"[LearningExecutionController] Failed to submit job: {exc}")
            return False

    def _build_run_request(
        self,
        *,
        record: NormalizedJobRecord,
        experiment_name: str,
        variable_under_test: str,
    ) -> PipelineRunRequest:
        stage_name = "txt2img"
        if record.stage_chain:
            stage_name = str(record.stage_chain[0].stage_type or "txt2img")
        prompt_pack_id = str(record.prompt_pack_id or f"learning_{experiment_name}")
        return PipelineRunRequest(
            prompt_pack_id=prompt_pack_id,
            selected_row_ids=[record.job_id],
            config_snapshot_id=f"learning_{experiment_name}_{variable_under_test}",
            run_mode=PipelineRunMode.QUEUE,
            source=PipelineRunSource.ADD_TO_QUEUE,
            explicit_output_dir=str(record.path_output_dir or "") or None,
            tags=["learning", stage_name],
            requested_job_label=f"Learning: {experiment_name}",
            max_njr_count=1,
        )
    
    def on_job_completed(self, job_id: str, result: dict[str, Any]) -> None:
        """Handle job completion.
        
        Args:
            job_id: Completed job ID
            result: Job result dict with images, outputs, etc.
        """
        variant = self._job_to_variant.get(job_id)
        if not variant:
            _logger.warning(f"No variant found for job {job_id}")
            return

        # Extract image references
        image_refs = self._extract_image_refs(result)
        
        variant.image_refs.extend(image_refs)
        variant.completed_images += len(image_refs)
        variant.status = "completed"

        _logger.info(f"Learning job completed: variant={variant.param_value}, images={len(image_refs)}")
        
        # Call completion callback
        if self._on_variant_completed:
            self._on_variant_completed(variant, result)
        
        # Cleanup
        self._job_to_variant.pop(job_id, None)
        self._job_contexts.pop(job_id, None)
    
    def on_job_failed(self, job_id: str, error: Exception) -> None:
        """Handle job failure.
        
        Args:
            job_id: Failed job ID
            error: Exception that caused failure
        """
        variant = self._job_to_variant.get(job_id)
        if not variant:
            _logger.warning(f"[LearningExecutionController] No variant found for job {job_id}")
            return
        
        variant.status = "failed"
        
        _logger.error(
            f"[LearningExecutionController] Job failed: "
            f"job_id={job_id}, variant={variant.param_value}, "
            f"error={error}"
        )
        
        # Call failure callback
        if self._on_variant_failed:
            self._on_variant_failed(variant, error)
        
        # Cleanup
        self._job_to_variant.pop(job_id, None)
        self._job_contexts.pop(job_id, None)
    
    def _extract_image_refs(self, result: dict[str, Any]) -> list[str]:
        """Extract image paths from job result.
        
        Args:
            result: Job result dict
            
        Returns:
            List of image file paths
        """
        image_refs = []
        
        # Try multiple possible result structures
        if isinstance(result, dict):
            # Try "images" key
            if "images" in result:
                images = result["images"]
                if isinstance(images, list):
                    image_refs.extend(str(img) for img in images if img)
            
            # Try "output_paths" key
            if "output_paths" in result:
                paths = result["output_paths"]
                if isinstance(paths, list):
                    image_refs.extend(str(path) for path in paths if path)
            
            # Try "image_paths" key
            if "image_paths" in result:
                paths = result["image_paths"]
                if isinstance(paths, list):
                    image_refs.extend(str(path) for path in paths if path)
            
            # Try "outputs" with nested structure
            if "outputs" in result:
                outputs = result["outputs"]
                if isinstance(outputs, list):
                    for output in outputs:
                        if isinstance(output, dict) and "path" in output:
                            image_refs.append(str(output["path"]))
        
        deduped: list[str] = []
        seen: set[str] = set()
        for image_ref in image_refs:
            if image_ref and image_ref not in seen:
                seen.add(image_ref)
                deduped.append(image_ref)
        return deduped

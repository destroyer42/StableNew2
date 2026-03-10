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
from src.pipeline.job_models_v2 import NormalizedJobRecord

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
                # Each variant can have "path", "output_path", or "all_paths"
                if 'all_paths' in variant:
                    paths = variant['all_paths']
                    image_paths.extend(paths)
                    _logger.info(f"[ExecutionController] Variant {idx} has all_paths: {len(paths)} images")
                elif 'path' in variant:
                    image_paths.append(variant['path'])
                    _logger.info(f"[ExecutionController] Variant {idx} has single path: {variant['path']}")
                elif 'output_path' in variant:
                    image_paths.append(variant['output_path'])
                    _logger.info(f"[ExecutionController] Variant {idx} has output_path: {variant['output_path']}")
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
        
        try:
            # Create Queue Job from NJR
            from src.queue.job_model import Job, JobPriority
            
            job = Job(
                job_id=record.job_id,
                priority=JobPriority.NORMAL,
                run_mode="queue",
                source="learning",
                prompt_source="manual",
                prompt_pack_id=record.prompt_pack_id,
                config_snapshot={
                    "prompt": record.positive_prompt,
                    "model": record.base_model,
                    "vae": record.vae,
                    "sampler": record.sampler_name,
                    "scheduler": record.scheduler,
                    "steps": record.steps,
                    "cfg_scale": record.cfg_scale,
                },
                learning_enabled=True,
            )
            
            # Attach NJR
            job._normalized_record = record  # type: ignore[attr-defined]
            
            # Set payload with completion tracking
            job.payload = lambda j=job: self._execute_with_tracking(j)
            
            # Track variant mapping
            self._job_to_variant[record.job_id] = variant
            self._job_contexts[record.job_id] = LearningJobContext(
                variant=variant,
                experiment_name=experiment_name,
                variable_under_test=variable_under_test,
                variant_value=variant.param_value,
                job_id=record.job_id,
            )
            
            # Submit
            self.job_service.submit_job_with_run_mode(job)
            
            _logger.info(
                f"[LearningExecutionController] Submitted job: "
                f"job_id={record.job_id}, experiment={experiment_name}, "
                f"variant={variant.param_value}"
            )
            
            return True
            
        except Exception as exc:
            _logger.exception(f"[LearningExecutionController] Failed to submit job: {exc}")
            return False
    
    def _execute_with_tracking(self, job: Any) -> dict[str, Any]:
        """Execute job and track completion.
        
        This is called by the runner when job is dequeued.
        """
        job_id = job.job_id
        _logger.info(f"[LearningExecutionController] Executing job: {job_id}")
        
        try:
            # Get runner (assumes job has access to runner/executor)
            record = getattr(job, "_normalized_record", None)
            if not record:
                raise RuntimeError("Job missing _normalized_record")
            
            # Execute via runner (delegate to actual execution)
            # This should call the actual pipeline runner
            result = self._execute_job(job)
            
            # Handle completion
            self.on_job_completed(job_id, result)
            
            return result
            
        except Exception as exc:
            _logger.exception(f"[LearningExecutionController] Job failed: {job_id}")
            self.on_job_failed(job_id, exc)
            return {"status": "failed", "error": str(exc)}
    
    def _execute_job(self, job: Any) -> dict[str, Any]:
        """Execute the actual job.
        
        This should delegate to the pipeline runner.
        Placeholder for now - actual implementation depends on runner integration.
        """
        # TODO: Integrate with actual runner
        # For now, assume job.payload was set by caller to actual execution
        _logger.warning("[LearningExecutionController] _execute_job placeholder called")
        return {"status": "completed", "images": []}
    
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

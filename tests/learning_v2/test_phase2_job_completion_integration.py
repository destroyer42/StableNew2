"""Integration tests for Learning Phase 2: Job Completion Hooks and Variant Updates.

Tests cover:
- PR-LEARN-003: Job completion routing to learning subsystem
- PR-LEARN-004: Live variant status updates
- PR-LEARN-005: Image result integration

These tests verify the closed-loop workflow:
submit learning job → job completes → variant updates → images linked
"""

import pytest
from unittest.mock import MagicMock, Mock, patch
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
from src.pipeline.job_models_v2 import LearningJobContext, NormalizedJobRecord
from src.controller.job_service import JobService
from src.queue.job_model import Job, JobStatus


class TestPhase2JobCompletionIntegration:
    """Test suite for Learning Phase 2 job completion integration."""
    
    def test_learning_job_context_creation(self):
        """PR-LEARN-003: Verify LearningJobContext dataclass works correctly."""
        ctx = LearningJobContext(
            experiment_id="cfg_sweep_001",
            experiment_name="CFG Sweep",
            variant_index=2,
            variable_under_test="cfg_scale",
            variant_value=7.5
        )
        
        assert ctx.experiment_id == "cfg_sweep_001"
        assert ctx.experiment_name == "CFG Sweep"
        assert ctx.variant_index == 2
        assert ctx.variable_under_test == "cfg_scale"
        assert ctx.variant_value == 7.5
        
        # Test to_dict() method
        ctx_dict = ctx.to_dict()
        assert ctx_dict["experiment_id"] == "cfg_sweep_001"
        assert ctx_dict["variant_value"] == 7.5
    
    def test_njr_with_learning_context(self):
        """PR-LEARN-003: Verify NJR can hold learning_context field."""
        ctx = LearningJobContext(
            experiment_id="test_exp",
            experiment_name="Test Experiment",
            variant_index=0,
            variable_under_test="steps",
            variant_value=25
        )
        
        njr = NormalizedJobRecord(
            job_id="test_job_123",
            config={},
            path_output_dir="output",
            filename_template="test_{index}",
            learning_context=ctx
        )
        
        assert njr.learning_context is not None
        assert njr.learning_context.experiment_id == "test_exp"
        assert njr.learning_context.variant_value == 25
    
    def test_job_service_completion_handler_registration(self):
        """PR-LEARN-003: Verify JobService can register/unregister completion handlers."""
        from src.queue.job_queue import JobQueue
        
        job_queue = JobQueue()
        job_service = JobService(job_queue)
        
        # Verify completion handlers list exists
        assert hasattr(job_service, "_completion_handlers")
        assert isinstance(job_service._completion_handlers, list)
        
        # Register a handler
        handler_called = []
        def test_handler(job, result):
            handler_called.append((job, result))
        
        job_service.register_completion_handler(test_handler)
        assert test_handler in job_service._completion_handlers
        
        # Unregister handler
        job_service.unregister_completion_handler(test_handler)
        assert test_handler not in job_service._completion_handlers
    
    def test_job_service_notifies_completion_handlers(self):
        """PR-LEARN-003: Verify JobService calls completion handlers on job completion."""
        from src.queue.job_queue import JobQueue
        
        job_queue = JobQueue()
        job_service = JobService(job_queue)
        
        # Register mock handler
        handler_calls = []
        def mock_handler(job, result):
            handler_calls.append({"job_id": job.job_id, "result": result})
        
        job_service.register_completion_handler(mock_handler)
        
        # Create a mock job
        mock_job = Mock(spec=Job)
        mock_job.job_id = "test_job_456"
        
        # Simulate completion notification
        result = {"success": True, "status": JobStatus.COMPLETED}
        job_service._notify_completion(mock_job, result)
        
        # Verify handler was called
        assert len(handler_calls) == 1
        assert handler_calls[0]["job_id"] == "test_job_456"
        assert handler_calls[0]["result"]["success"] is True
    
    def test_learning_controller_receives_completion_callback(self):
        """PR-LEARN-003: Verify LearningController.on_job_completed_callback routes correctly."""
        learning_state = LearningState()
        controller = LearningController(learning_state)
        
        # Set up experiment
        experiment = LearningExperiment(
            name="test_exp",
            stage="txt2img",
            variable_under_test="cfg_scale",
            values=[6.0, 7.0, 8.0],
            prompt_text="test prompt"
        )
        learning_state.current_experiment = experiment
        
        # Create variants
        for value in experiment.values:
            variant = LearningVariant(param_value=value, status="running")
            learning_state.plan.append(variant)
        
        # Create mock job with learning context
        ctx = LearningJobContext(
            experiment_id="test_exp",
            experiment_name="test_exp",
            variant_index=1,
            variable_under_test="cfg_scale",
            variant_value=7.0
        )
        
        mock_njr = Mock()
        mock_njr.learning_context = ctx
        
        mock_job = Mock()
        mock_job.snapshot = mock_njr
        
        result = {"success": True, "images": ["output/image1.png", "output/image2.png"]}
        
        # Call the completion callback
        controller.on_job_completed_callback(mock_job, result)
        
        # Verify variant was updated
        variant = learning_state.plan[1]
        assert variant.status == "completed"
        assert variant.completed_images == 1
    
    def test_variant_status_updates_on_completion(self):
        """PR-LEARN-004: Verify variant status updates correctly on job completion."""
        learning_state = LearningState()
        mock_plan_table = Mock()
        controller = LearningController(learning_state, plan_table=mock_plan_table)
        
        # Create variant
        variant = LearningVariant(param_value=7.0, status="running")
        learning_state.plan.append(variant)
        
        # Simulate job completion
        result = {"images": ["test1.png", "test2.png"]}
        controller._on_variant_job_completed(variant, result)
        
        # Verify variant status changed
        assert variant.status == "completed"
        assert variant.completed_images == 1
        
        # Verify table was updated
        mock_plan_table.update_row_status.assert_called_once_with(0, "completed")
    
    def test_variant_status_updates_on_failure(self):
        """PR-LEARN-004: Verify variant status updates correctly on job failure."""
        learning_state = LearningState()
        mock_plan_table = Mock()
        controller = LearningController(learning_state, plan_table=mock_plan_table)
        
        # Create variant
        variant = LearningVariant(param_value=7.0, status="running")
        learning_state.plan.append(variant)
        
        # Simulate job failure
        error = Exception("WebUI connection failed")
        controller._on_variant_job_failed(variant, error)
        
        # Verify variant status changed
        assert variant.status == "failed"
        
        # Verify table was updated
        mock_plan_table.update_row_status.assert_called_once_with(0, "failed")
    
    def test_image_extraction_from_result(self):
        """PR-LEARN-005: Verify images are extracted from various result formats."""
        learning_state = LearningState()
        controller = LearningController(learning_state)
        
        variant = LearningVariant(param_value=7.0)
        learning_state.plan.append(variant)
        
        # Test 1: "images" key
        result1 = {"images": ["output/img1.png", "output/img2.png"]}
        controller._on_variant_job_completed(variant, result1)
        assert "output/img1.png" in variant.image_refs
        assert "output/img2.png" in variant.image_refs
        
        # Test 2: "output_paths" key
        variant2 = LearningVariant(param_value=8.0)
        learning_state.plan.append(variant2)
        result2 = {"output_paths": ["output/img3.png"]}
        controller._on_variant_job_completed(variant2, result2)
        assert "output/img3.png" in variant2.image_refs
        
        # Test 3: "image_paths" key
        variant3 = LearningVariant(param_value=9.0)
        learning_state.plan.append(variant3)
        result3 = {"image_paths": ["output/img4.png", "output/img5.png"]}
        controller._on_variant_job_completed(variant3, result3)
        assert "output/img4.png" in variant3.image_refs
        assert "output/img5.png" in variant3.image_refs
    
    def test_image_deduplication(self):
        """PR-LEARN-005: Verify duplicate images aren't added twice."""
        learning_state = LearningState()
        controller = LearningController(learning_state)
        
        variant = LearningVariant(param_value=7.0)
        learning_state.plan.append(variant)
        
        # Complete job twice with same images
        result = {"images": ["output/img1.png", "output/img2.png"]}
        controller._on_variant_job_completed(variant, result)
        controller._on_variant_job_completed(variant, result)
        
        # Verify images only appear once
        assert variant.image_refs.count("output/img1.png") == 1
        assert variant.image_refs.count("output/img2.png") == 1
    
    def test_completion_callback_ignores_non_learning_jobs(self):
        """PR-LEARN-003: Verify callback ignores jobs without learning context."""
        learning_state = LearningState()
        controller = LearningController(learning_state)
        
        # Set up experiment
        experiment = LearningExperiment(
            name="test_exp",
            stage="txt2img",
            variable_under_test="cfg_scale",
            values=[7.0],
            prompt_text="test"
        )
        learning_state.current_experiment = experiment
        variant = LearningVariant(param_value=7.0, status="running")
        learning_state.plan.append(variant)
        
        # Create job WITHOUT learning context
        mock_njr = Mock()
        mock_njr.learning_context = None
        mock_job = Mock()
        mock_job.snapshot = mock_njr
        
        result = {"success": True}
        
        # Call callback - should not crash or update variant
        controller.on_job_completed_callback(mock_job, result)
        
        # Verify variant status unchanged
        assert variant.status == "running"
    
    def test_completion_callback_ignores_other_experiments(self):
        """PR-LEARN-003: Verify callback ignores jobs from different experiments."""
        learning_state = LearningState()
        controller = LearningController(learning_state)
        
        # Set up current experiment
        experiment = LearningExperiment(
            name="current_exp",
            stage="txt2img",
            variable_under_test="cfg_scale",
            values=[7.0],
            prompt_text="test"
        )
        learning_state.current_experiment = experiment
        variant = LearningVariant(param_value=7.0, status="running")
        learning_state.plan.append(variant)
        
        # Create job for DIFFERENT experiment
        ctx = LearningJobContext(
            experiment_id="other_exp",
            experiment_name="other_exp",
            variant_index=0,
            variable_under_test="steps",
            variant_value=25
        )
        mock_njr = Mock()
        mock_njr.learning_context = ctx
        mock_job = Mock()
        mock_job.snapshot = mock_njr
        
        result = {"success": True}
        
        # Call callback - should not update our variant
        controller.on_job_completed_callback(mock_job, result)
        
        # Verify variant status unchanged
        assert variant.status == "running"
    
    def test_end_to_end_workflow_simulation(self):
        """Full workflow test: submit → complete → update → images linked."""
        from src.queue.job_queue import JobQueue
        
        # Set up job service with completion handling
        job_queue = JobQueue()
        job_service = JobService(job_queue)
        
        # Set up learning controller
        learning_state = LearningState()
        mock_plan_table = Mock()
        controller = LearningController(learning_state, plan_table=mock_plan_table)
        
        # Set up experiment
        experiment = LearningExperiment(
            name="end_to_end_test",
            stage="txt2img",
            variable_under_test="cfg_scale",
            values=[6.0, 7.0, 8.0],
            prompt_text="test prompt"
        )
        learning_state.current_experiment = experiment
        
        for value in experiment.values:
            variant = LearningVariant(param_value=value, status="pending")
            learning_state.plan.append(variant)
        
        # Register controller's callback with job service
        job_service.register_completion_handler(controller.on_job_completed_callback)
        
        # Simulate job completion
        variant_index = 1
        ctx = LearningJobContext(
            experiment_id="end_to_end_test",
            experiment_name="end_to_end_test",
            variant_index=variant_index,
            variable_under_test="cfg_scale",
            variant_value=7.0
        )
        
        mock_njr = Mock()
        mock_njr.learning_context = ctx
        
        mock_job = Mock()
        mock_job.job_id = "test_job_789"
        mock_job.snapshot = mock_njr
        
        result = {
            "success": True,
            "status": JobStatus.COMPLETED,
            "images": ["output/cfg_7.0_img1.png", "output/cfg_7.0_img2.png"]
        }
        
        # Trigger completion notification (simulates what JobService does)
        job_service._notify_completion(mock_job, result)
        
        # Verify complete workflow:
        # 1. Variant status updated
        variant = learning_state.plan[variant_index]
        assert variant.status == "completed"
        
        # 2. Images linked
        assert "output/cfg_7.0_img1.png" in variant.image_refs
        assert "output/cfg_7.0_img2.png" in variant.image_refs
        
        # 3. Table updated
        mock_plan_table.update_row_status.assert_called_with(variant_index, "completed")
        mock_plan_table.update_row_images.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Tests for Learning Tab wiring to PipelineController (PR-LEARN-001)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, Mock


def test_learning_tab_receives_pipeline_controller():
    """Verify MainWindow passes pipeline_controller to LearningTabFrame."""
    # This test verifies the wiring pattern exists
    # Actual GUI instantiation requires Tk which is tested in integration
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState

    # Create mock controller
    mock_controller = MagicMock()
    mock_controller.queue_controller = MagicMock()

    # Create LearningController directly (simulates what LearningTabFrame does)
    learning_state = LearningState()
    controller = LearningController(
        learning_state=learning_state,
        pipeline_controller=mock_controller,
    )

    # Verify controller was passed through
    assert controller.pipeline_controller is mock_controller


def test_learning_controller_builds_correct_overrides():
    """Verify overrides dict contains the variant value for the variable under test."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
    
    # Create learning state with experiment
    learning_state = LearningState()
    experiment = LearningExperiment(
        name="CFG Test",
        stage="txt2img",
        variable_under_test="CFG Scale",
        values=[7.0, 8.0, 9.0, 10.0],
        images_per_value=1,
    )
    learning_state.current_experiment = experiment
    
    # Create controller
    controller = LearningController(learning_state=learning_state)
    
    # Create a variant
    variant = LearningVariant(
        experiment_id="CFG Test",
        param_value=8.5,
        status="pending",
    )
    
    # Build overrides
    overrides = controller._build_variant_overrides(variant, experiment)
    
    # Verify overrides contain the correct value
    assert overrides["cfg_scale"] == 8.5
    assert overrides["learning_experiment_id"] == "CFG Test"
    assert overrides["learning_variable"] == "CFG Scale"
    assert overrides["learning_variant_value"] == 8.5


def test_learning_metadata_added_to_pack_entry():
    """Verify learning_metadata field exists in PackJobEntry."""
    from src.gui.app_state_v2 import PackJobEntry
    
    # Create PackJobEntry with learning metadata
    entry = PackJobEntry(
        pack_id="test_pack",
        pack_name="Test Pack",
        config_snapshot={},
        learning_metadata={
            "learning_enabled": True,
            "learning_experiment_name": "Test Experiment",
            "learning_stage": "txt2img",
            "learning_variable": "CFG Scale",
            "learning_variant_value": 7.5,
        },
    )
    
    # Verify metadata is stored
    assert entry.learning_metadata is not None
    assert entry.learning_metadata["learning_enabled"] is True
    assert entry.learning_metadata["learning_experiment_name"] == "Test Experiment"


def test_submit_variant_job_creates_pack_entry():
    """Verify _submit_variant_job creates a PackJobEntry with learning metadata."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
    
    # Create learning state with experiment
    learning_state = LearningState()
    experiment = LearningExperiment(
        name="Steps Test",
        stage="txt2img",
        variable_under_test="Steps",
        values=[20, 30, 40],
        images_per_value=1,
        prompt_text="A beautiful landscape",
    )
    learning_state.current_experiment = experiment
    learning_state.plan = [
        LearningVariant(experiment_id="Steps Test", param_value=20, status="pending"),
        LearningVariant(experiment_id="Steps Test", param_value=30, status="pending"),
        LearningVariant(experiment_id="Steps Test", param_value=40, status="pending"),
    ]
    
    # Create mock pipeline controller
    mock_controller = MagicMock()
    mock_queue_controller = MagicMock()
    mock_queue_controller.submit_pack_job = MagicMock(return_value=True)
    mock_controller.queue_controller = mock_queue_controller
    
    # Create controller
    controller = LearningController(
        learning_state=learning_state,
        pipeline_controller=mock_controller,
    )
    
    # Submit a variant job
    variant = learning_state.plan[0]
    controller._submit_variant_job(variant)
    
    # Verify queue submission was called
    assert mock_queue_controller.submit_pack_job.called
    
    # Verify the PackJobEntry has learning metadata
    call_args = mock_queue_controller.submit_pack_job.call_args
    pack_entry = call_args[0][0]
    
    assert pack_entry.learning_metadata is not None
    assert pack_entry.learning_metadata["learning_enabled"] is True
    assert pack_entry.learning_metadata["learning_experiment_name"] == "Steps Test"
    assert pack_entry.learning_metadata["learning_variable"] == "Steps"
    assert pack_entry.learning_metadata["learning_variant_value"] == 20
    
    # Verify variant status updated to queued
    assert variant.status == "queued"


def test_learning_controller_handles_missing_queue_controller():
    """Verify controller handles missing queue_controller gracefully."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
    
    # Create learning state with experiment
    learning_state = LearningState()
    experiment = LearningExperiment(
        name="Test",
        stage="txt2img",
        variable_under_test="CFG Scale",
        values=[7.0],
        images_per_value=1,
    )
    learning_state.current_experiment = experiment
    learning_state.plan = [
        LearningVariant(experiment_id="Test", param_value=7.0, status="pending"),
    ]
    
    # Create mock pipeline controller WITHOUT queue_controller
    mock_controller = MagicMock()
    delattr(mock_controller, "queue_controller")
    
    # Create controller
    controller = LearningController(
        learning_state=learning_state,
        pipeline_controller=mock_controller,
    )
    
    # Submit variant - should handle gracefully
    variant = learning_state.plan[0]
    controller._submit_variant_job(variant)
    
    # Verify variant status is failed (couldn't submit)
    assert variant.status == "failed"

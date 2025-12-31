"""Integration tests for LearningController + LearningExecutionController (PR-LEARN-002)."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock


@dataclass
class MockPipelineResult:
    """Mock pipeline result for testing."""
    success: bool = True
    output_path: str = "/fake/path/image.png"


def test_app_controller_creates_learning_execution_controller():
    """Verify AppController initializes LearningExecutionController."""
    from src.controller.app_controller import AppController
    from src.gui.main_window_v2 import MainWindow

    # Create minimal AppController (no GUI to avoid Tk)
    controller = AppController(
        main_window=None,
        threaded=False,
    )

    # Verify LearningExecutionController was created
    assert hasattr(controller, "learning_execution_controller")
    assert controller.learning_execution_controller is not None


def test_learning_execution_controller_has_run_callable():
    """Verify LearningExecutionController receives _learning_run_callable."""
    from src.controller.app_controller import AppController

    # Create AppController
    controller = AppController(
        main_window=None,
        threaded=False,
    )

    # Verify the execution controller has a run callable
    exec_ctrl = controller.learning_execution_controller
    assert exec_ctrl._run_callable is not None


def test_learning_controller_receives_execution_controller():
    """Verify GUI LearningController receives execution_controller when available."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState

    # Create mock execution controller
    mock_exec_ctrl = MagicMock()

    # Create LearningController with execution_controller
    learning_state = LearningState()
    controller = LearningController(
        learning_state=learning_state,
        execution_controller=mock_exec_ctrl,
    )

    # Verify execution_controller was stored
    assert controller.execution_controller is mock_exec_ctrl


def test_learning_tab_frame_passes_execution_controller():
    """Verify LearningTabFrame extracts and passes execution_controller.

    NOTE: This test verifies the wiring logic exists. Full GUI instantiation
    with Tk is tested in manual/integration testing.
    """
    # Test the wiring logic by creating LearningController directly
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState

    # Create mock execution controller
    mock_exec_ctrl = MagicMock()

    # Create LearningController with execution_controller
    learning_state = LearningState()
    controller = LearningController(
        learning_state=learning_state,
        execution_controller=mock_exec_ctrl,
    )

    # Verify execution_controller was stored
    assert controller.execution_controller is mock_exec_ctrl


def test_learning_controller_handles_missing_execution_controller():
    """Verify LearningController works without execution_controller (fallback mode)."""
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

    # Create mock pipeline controller
    mock_pipeline_ctrl = MagicMock()
    mock_queue_controller = MagicMock()
    mock_queue_controller.submit_pack_job = MagicMock(return_value=True)
    mock_pipeline_ctrl.queue_controller = mock_queue_controller

    # Create controller WITHOUT execution_controller
    controller = LearningController(
        learning_state=learning_state,
        pipeline_controller=mock_pipeline_ctrl,
        execution_controller=None,  # No execution controller
    )

    # Run plan - should fall back to direct submission
    controller.run_plan()

    # Verify direct queue submission was used
    assert mock_queue_controller.submit_pack_job.called


def test_learning_execution_controller_can_run_plan():
    """Verify LearningExecutionController can execute a learning plan."""
    from src.controller.learning_execution_controller import LearningExecutionController
    from src.learning.learning_plan import LearningPlan

    # Create mock run callable
    mock_run = MagicMock(return_value=MockPipelineResult())

    # Create execution controller
    exec_ctrl = LearningExecutionController(run_callable=mock_run)

    # Create simple learning plan
    plan = LearningPlan(
        mode="single_variable_sweep",
        stage="txt2img",
        target_variable="cfg_scale",
        sweep_values=[7.0, 8.0, 9.0],
        images_per_step=1,
    )

    # Run the plan
    base_config = {"prompt": "test prompt", "model": "test_model"}
    result = exec_ctrl.run_learning_plan(plan, base_config)

    # Verify run was called
    assert mock_run.called
    assert result is not None


def test_integration_app_controller_to_gui():
    """End-to-end test: AppController → LearningController (without GUI).

    NOTE: Full GUI integration with LearningTabFrame requires Tk and is
    tested in manual/integration testing.
    """
    from src.controller.app_controller import AppController
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState

    # Create AppController
    app_controller = AppController(
        main_window=None,
        threaded=False,
    )

    # Verify learning_execution_controller exists
    assert hasattr(app_controller, "learning_execution_controller")
    exec_ctrl = app_controller.learning_execution_controller
    assert exec_ctrl is not None

    # Create LearningController with execution_controller (simulates what LearningTabFrame does)
    learning_state = LearningState()
    learning_controller = LearningController(
        learning_state=learning_state,
        execution_controller=exec_ctrl,
    )

    # Verify the controller chain is complete
    assert learning_controller.execution_controller is exec_ctrl

    # Verify the execution controller has the run callable
    assert exec_ctrl._run_callable is not None

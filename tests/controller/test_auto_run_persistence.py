"""Tests for auto_run persistence bug fix."""

from unittest.mock import MagicMock, Mock

from src.controller.job_service import JobService


def test_set_activity_hooks_does_not_override_auto_run():
    """Test that set_activity_hooks() doesn't unconditionally enable auto_run.

    Bug: set_activity_hooks() was unconditionally setting auto_run_enabled=True,
    overriding the persisted user preference loaded from queue snapshot.
    """
    # Setup with mocks
    job_queue = MagicMock()
    runner = MagicMock()
    history_store = MagicMock()

    job_service = JobService(
        job_queue=job_queue,
        runner=runner,
        history_store=history_store,
    )

    # User had disabled auto_run and it was persisted
    job_service.auto_run_enabled = False

    # Now activity hooks are set (this happens during app initialization)
    job_service.set_activity_hooks(
        on_queue_activity=Mock(),
        on_runner_activity=Mock(),
    )

    # Verify auto_run_enabled was NOT overridden
    assert job_service.auto_run_enabled is False, (
        "set_activity_hooks() should not override auto_run_enabled"
    )


def test_auto_run_can_be_set_externally():
    """Test that auto_run_enabled can be set externally (by app controller)."""
    job_queue = MagicMock()
    runner = MagicMock()
    history_store = MagicMock()

    job_service = JobService(
        job_queue=job_queue,
        runner=runner,
        history_store=history_store,
    )

    # auto_run_enabled is set externally by AppController
    job_service.auto_run_enabled = True
    assert job_service.auto_run_enabled is True

    # Can be toggled
    job_service.auto_run_enabled = False
    assert job_service.auto_run_enabled is False


def test_auto_run_can_be_explicitly_disabled():
    """Test that auto_run can be disabled and stays disabled."""
    job_queue = MagicMock()
    runner = MagicMock()
    history_store = MagicMock()

    job_service = JobService(
        job_queue=job_queue,
        runner=runner,
        history_store=history_store,
    )

    # Disable auto_run
    job_service.auto_run_enabled = False
    assert job_service.auto_run_enabled is False

    # Call various methods that shouldn't change it
    job_service.set_activity_hooks(
        on_queue_activity=Mock(),
        on_runner_activity=Mock(),
    )

    # Should still be disabled
    assert job_service.auto_run_enabled is False




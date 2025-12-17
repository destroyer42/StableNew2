from datetime import datetime

from src.controller.job_lifecycle_logger import JobLifecycleLogger
from src.gui.app_state_v2 import AppStateV2


def test_job_lifecycle_logger_records_add_to_job_event():
    state = AppStateV2()
    state.log_events_max = 10
    now = datetime(2025, 1, 1, 12, 0, 0)
    logger = JobLifecycleLogger(app_state=state, clock=lambda: now)

    logger.log_add_to_job(source="pipeline_tab", draft_size=3)

    assert len(state.log_events) == 1
    event = state.log_events[0]
    assert event.event_type == "add_to_job"
    assert event.draft_size == 3
    assert "draft contains" in event.message
    assert event.timestamp == now


def test_job_lifecycle_logger_truncates_old_events():
    state = AppStateV2()
    state.log_events_max = 2
    logger = JobLifecycleLogger(app_state=state)

    logger.log_add_to_job(source="pipeline_tab", draft_size=1)
    logger.log_add_to_job(source="pipeline_tab", draft_size=2)
    logger.log_add_to_job(source="pipeline_tab", draft_size=3)

    assert len(state.log_events) == 2
    assert state.log_events[0].draft_size == 2
    assert state.log_events[1].draft_size == 3


def test_job_lifecycle_logger_records_job_finished():
    state = AppStateV2()
    logger = JobLifecycleLogger(app_state=state)

    logger.log_job_finished(
        source="job_service", job_id="job-123", status="completed", message="Done"
    )

    assert state.log_events
    event = state.log_events[-1]
    assert event.event_type == "job_completed"
    assert event.job_id == "job-123"
    assert event.message == "Done"

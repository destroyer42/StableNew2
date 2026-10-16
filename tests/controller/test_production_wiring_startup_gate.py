"""The production construction path must activate the documented WebUI startup gate and NJR strictness.

Regression for the audit finding that ``AppController`` adopts the ``JobService`` built by ``PipelineController`` while
the only ``enable_startup_gate()`` call lived in ``AppController._build_job_service()`` (a path production never takes),
so restored WebUI jobs could be claimed before a readiness/identity proof.
"""

from __future__ import annotations

from unittest import mock

import pytest

from src.controller.app_controller import AppController
from src.utils.logger import StructuredLogger, close_all_structured_loggers


@pytest.fixture
def production_controller(tmp_path):
    """An AppController with no injected JobService: the same construction path ``build_v2_app`` takes."""

    controller = AppController(
        None,
        threaded=False,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    try:
        yield controller
    finally:
        try:
            controller.job_service.stop()
        except Exception:
            pass
        close_all_structured_loggers()


def test_the_production_path_builds_exactly_one_job_service(production_controller: AppController) -> None:
    service = production_controller.job_service
    assert service is not None
    assert production_controller.pipeline_controller.get_job_service() is service  # no second queue/repository authority


def test_the_production_path_holds_webui_claims_until_a_readiness_proof(production_controller: AppController) -> None:
    queue = production_controller.job_service.job_queue
    assert queue.is_webui_held()
    info = queue.webui_hold_info()
    assert info is not None and info.get("reason") == "startup_unverified"


def test_the_production_path_refuses_jobs_without_a_normalized_record(production_controller: AppController) -> None:
    from src.queue.job_model import Job

    service = production_controller.job_service
    job = Job(job_id="no-njr")
    with pytest.raises(ValueError, match="missing normalized snapshot"):
        service.submit_job_with_run_mode(job)


class _InjectedService:
    """Minimal injected JobService (the pattern other AppController tests use) that records gate calls."""

    EVENT_QUEUE_UPDATED = "queue_updated"
    EVENT_QUEUE_STATUS = "queue_status"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_FINISHED = "job_finished"
    EVENT_JOB_FAILED = "job_failed"
    EVENT_QUEUE_EMPTY = "queue_empty"

    def __init__(self) -> None:
        self.webui_outage = mock.MagicMock()

    def register_callback(self, *_: object, **__: object) -> None:
        pass


def test_an_injected_job_service_is_left_untouched(tmp_path) -> None:
    """Tests (and any caller) that inject a service keep full control; the gate applies only to the service this path builds."""

    injected = _InjectedService()
    controller = AppController(
        None,
        threaded=False,
        job_service=injected,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    try:
        assert controller.job_service is injected
        injected.webui_outage.enable_startup_gate.assert_not_called()
    finally:
        close_all_structured_loggers()

"""Centralized DI test helpers for JobService, Runner, and History.

PR-0114C-Ty: This module provides helper functions for constructing
JobService, AppController, and other components with stubbed runner
and history dependencies for tests.

Usage:
    from tests.helpers.job_service_di_test_helpers import (
        make_stubbed_job_service,
        make_app_controller_with_stubs,
        stub_runner_factory,
    )

    # Create a stubbed JobService directly
    job_service = make_stubbed_job_service()

    # Create an AppController with stubbed JobService
    controller = make_app_controller_with_stubs()

These helpers ensure tests don't spawn real worker threads or attempt
to execute SD/WebUI pipelines.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from src.controller.job_history_service import NullHistoryService
from src.controller.job_service import JobService
from src.queue.job_queue import JobQueue
from src.queue.stub_runner import StubRunner

if TYPE_CHECKING:
    from src.controller.app_controller import AppController


def stub_runner_factory(
    job_queue: JobQueue,
    run_callable: Callable | None = None,
) -> StubRunner:
    """Factory that creates StubRunner instead of SingleNodeJobRunner.

    Use this factory when constructing JobService in tests that should not
    execute real pipelines.

    Args:
        job_queue: The job queue to manage.
        run_callable: Optional callable for job execution (ignored by StubRunner).

    Returns:
        A StubRunner instance that does not execute real jobs.
    """
    return StubRunner(
        job_queue=job_queue,
        run_callable=run_callable,
        poll_interval=0.05,
    )


def make_stubbed_job_service(
    *,
    job_queue: JobQueue | None = None,
    history_service: NullHistoryService | None = None,
    run_callable: Callable | None = None,
) -> JobService:
    """Create a JobService with StubRunner and NullHistoryService.

    Use this helper when you need a JobService that:
    - Does not spawn real worker threads
    - Does not execute real pipelines
    - Uses a no-op history service

    Args:
        job_queue: Optional pre-existing job queue. Created if None.
        history_service: Optional history service. NullHistoryService created if None.
        run_callable: Optional run callable for the stub runner.

    Returns:
        A JobService wired with StubRunner and NullHistoryService.
    """
    queue = job_queue or JobQueue()
    history = history_service or NullHistoryService()
    return JobService(
        job_queue=queue,
        runner_factory=stub_runner_factory,
        history_service=history,
        run_callable=run_callable,
    )


def make_app_controller_with_stubs(
    *,
    main_window: object | None = None,
    pipeline_runner: object | None = None,
    api_client: object | None = None,
    structured_logger: object | None = None,
    webui_process_manager: object | None = None,
    config_manager: object | None = None,
    resource_service: object | None = None,
    job_service: JobService | None = None,
    **kwargs: object,
) -> AppController:
    """Create an AppController with a stubbed JobService.

    This helper constructs an AppController suitable for tests:
    - Uses StubRunner (no real pipeline execution)
    - Uses NullHistoryService (no real history recording)
    - Accepts all standard AppController parameters

    Args:
        main_window: Optional main window reference.
        pipeline_runner: Optional pipeline runner (usually None for tests).
        api_client: Optional API client.
        structured_logger: Optional structured logger.
        webui_process_manager: Optional WebUI process manager.
        config_manager: Optional config manager.
        resource_service: Optional resource service.
        job_service: Optional pre-existing job service. If None, creates stubbed one.
        **kwargs: Additional keyword arguments for AppController.

    Returns:
        An AppController with stubbed JobService.
    """
    from src.controller.app_controller import AppController

    stubbed_job_service = job_service or make_stubbed_job_service()

    return AppController(
        main_window=main_window,
        pipeline_runner=pipeline_runner,
        api_client=api_client,
        structured_logger=structured_logger,
        webui_process_manager=webui_process_manager,
        config_manager=config_manager,
        resource_service=resource_service,
        job_service=stubbed_job_service,
        **kwargs,
    )


def make_stubbed_job_service_with_queue() -> tuple[JobService, JobQueue, NullHistoryService]:
    """Create a JobService with stubs and return all components.

    Useful for tests that need to inspect the queue or history service.

    Returns:
        Tuple of (JobService, JobQueue, NullHistoryService).
    """
    queue = JobQueue()
    history = NullHistoryService()
    service = JobService(
        job_queue=queue,
        runner_factory=stub_runner_factory,
        history_service=history,
    )
    return service, queue, history

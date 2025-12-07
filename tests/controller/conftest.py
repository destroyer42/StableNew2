"""Shared fixtures for controller tests.

PR-0114C-T(x): This module provides test fixtures that use StubRunner and
NullHistoryService to prevent real SD/WebUI execution during controller tests.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from src.controller.job_history_service import NullHistoryService
from src.controller.job_service import JobService
from src.queue.job_queue import JobQueue
from src.queue.stub_runner import StubRunner


def stub_runner_factory(
    job_queue: JobQueue,
    run_callable: Callable | None = None,
) -> StubRunner:
    """Factory that creates StubRunner instead of SingleNodeJobRunner.

    Use this factory when constructing JobService in tests that should not
    execute real pipelines.
    """
    return StubRunner(
        job_queue=job_queue,
        run_callable=run_callable,
        poll_interval=0.05,
    )


@pytest.fixture
def stub_job_queue() -> JobQueue:
    """Create a JobQueue without history store for testing."""
    return JobQueue()


@pytest.fixture
def null_history_service() -> NullHistoryService:
    """Create a NullHistoryService for tests that don't need history."""
    return NullHistoryService()


@pytest.fixture
def stub_runner(stub_job_queue: JobQueue) -> StubRunner:
    """Create a StubRunner for tests that don't need real execution."""
    return StubRunner(job_queue=stub_job_queue)


@pytest.fixture
def job_service_with_stubs(
    stub_job_queue: JobQueue,
    null_history_service: NullHistoryService,
) -> JobService:
    """Create a JobService with StubRunner and NullHistoryService.

    Use this fixture for controller tests that:
    - Should not execute real pipelines (StubRunner).
    - Don't need to verify history recording (NullHistoryService).
    - Want to test queue/controller wiring without side effects.
    """
    return JobService(
        job_queue=stub_job_queue,
        runner_factory=stub_runner_factory,
        history_service=null_history_service,
    )


@pytest.fixture
def job_service_with_stub_runner_factory() -> tuple[JobService, JobQueue, NullHistoryService]:
    """Create JobService using runner_factory DI pattern.

    Returns tuple of (service, queue, history) for assertions.
    """
    queue = JobQueue()
    history = NullHistoryService()
    service = JobService(
        job_queue=queue,
        runner_factory=stub_runner_factory,
        history_service=history,
    )
    return service, queue, history

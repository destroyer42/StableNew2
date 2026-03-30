from __future__ import annotations

from pathlib import Path

import pytest

from src.queue.job_model import Job, JobPriority, JobStatus
from src.runtime_host import (
    LocalRuntimeHostAdapter,
    RuntimeHostProtocolMessage,
    UnsupportedRuntimeHostProtocolVersion,
    build_local_runtime_host,
    build_protocol_message,
)
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


def test_protocol_message_round_trips_with_json_safe_payload() -> None:
    message = build_protocol_message(
        "snapshot",
        "diagnostics",
        {
            "path": Path("output/example.png"),
            "status": JobStatus.RUNNING,
            "items": (1, 2, 3),
        },
    )

    payload = message.to_dict()
    restored = RuntimeHostProtocolMessage.from_dict(payload)

    assert payload["payload"]["path"] == "output/example.png"
    assert payload["payload"]["status"] == JobStatus.RUNNING.value
    assert payload["payload"]["items"] == [1, 2, 3]
    assert restored.payload == payload["payload"]


def test_protocol_message_rejects_unsupported_version() -> None:
    with pytest.raises(UnsupportedRuntimeHostProtocolVersion):
        RuntimeHostProtocolMessage.from_dict(
            {
                "protocol": "stablenew.runtime_host",
                "version": 99,
                "kind": "snapshot",
                "name": "queue",
                "payload": {},
            }
        )


def test_local_runtime_host_adapter_wraps_job_service() -> None:
    service = make_stubbed_job_service()

    adapter = build_local_runtime_host(service)

    assert isinstance(adapter, LocalRuntimeHostAdapter)
    assert adapter.job_service is service
    assert adapter.queue is service.queue
    assert adapter.job_queue is service.job_queue
    assert adapter.runner is service.runner
    assert adapter.describe_protocol()["transport"] == "local-only"


def test_local_runtime_host_adapter_forwards_submission_and_diagnostics() -> None:
    service = make_stubbed_job_service()
    adapter = build_local_runtime_host(service)
    calls: list[tuple[str, bool]] = []

    def tracking_submit(job: Job, *, emit_queue_updated: bool = True) -> None:
        calls.append((job.job_id, emit_queue_updated))

    service.submit_job_with_run_mode = tracking_submit  # type: ignore[assignment]
    job = Job(job_id="runtime-host-job", priority=JobPriority.NORMAL)

    adapter.submit_job_with_run_mode(job, emit_queue_updated=False)

    assert calls == [("runtime-host-job", False)]
    assert "queue" in adapter.get_diagnostics_snapshot()
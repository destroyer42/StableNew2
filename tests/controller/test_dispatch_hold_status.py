"""A held queue must say why nothing starts (GPU quarantine / WebUI outage)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.controller.app_controller_services.dispatch_hold_status import (
    describe_dispatch_hold,
    format_dispatch_hold,
)
from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.job_model import Job
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository


def _summary(**overrides):
    base = {"queued": 3, "held_gpu_loss": 0, "held_webui": 0, "held": 0, "eligible": 3}
    base.update(overrides)
    return base


def test_nothing_held_says_nothing() -> None:
    assert format_dispatch_hold(None) == ""
    assert format_dispatch_hold({}) == ""
    assert format_dispatch_hold(_summary()) == ""


def test_a_gpu_quarantine_names_the_cause_and_the_way_out() -> None:
    text = format_dispatch_hold(_summary(held_gpu_loss=3, held=3, eligible=0))

    assert text.startswith("Dispatch is held")
    assert "3 held by the GPU device-loss quarantine" in text
    assert "Readiness" in text and "Confirm GPU recovered" in text


def test_a_webui_hold_is_named_separately() -> None:
    text = format_dispatch_hold(_summary(held_webui=2, held=2, eligible=1))

    assert "2 held by a WebUI outage" in text
    assert "1 can still run" in text
    assert "GPU" not in text


def test_both_holds_are_listed() -> None:
    text = format_dispatch_hold(_summary(held_gpu_loss=1, held_webui=1, held=2, eligible=0))

    assert "GPU device-loss quarantine" in text and "WebUI outage" in text


def test_malformed_summaries_do_not_raise_through_the_describer() -> None:
    class _Broken:
        def dispatch_summary(self):
            raise RuntimeError("queue busy")

    assert describe_dispatch_hold(_Broken()) == ""
    assert describe_dispatch_hold(object()) == ""
    assert describe_dispatch_hold(None) == ""


def _job(job_id: str) -> Job:
    record = build_cli_njr(
        prompt=f"prompt {job_id}",
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "m.safetensors",
                "steps": 4,
                "cfg_scale": 5.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    record = replace(record, job_id=job_id)
    job = Job(job_id=job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


def test_a_real_quarantined_queue_reports_then_clears_after_release(tmp_path: Path) -> None:
    queue = JobQueue(repository=JobRepository(tmp_path / "jobs.sqlite3"))
    queue.submit(_job("first"))
    queue.submit(_job("second"))
    assert describe_dispatch_hold(queue) == ""

    queue.quarantine_gpu_dispatch(
        {"incident_id": "gpu-test", "evidence_class": "confirmed_device_loss"}
    )
    held = describe_dispatch_hold(queue)
    assert "2 held by the GPU device-loss quarantine" in held
    assert "Confirm GPU recovered" in held

    assert queue.release_gpu_quarantine("gpu-test")
    assert describe_dispatch_hold(queue) == ""

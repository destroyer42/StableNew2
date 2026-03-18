from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.job_execution_controller import JobExecutionController
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.queue.job_model import Job, JobPriority
from src.utils.error_envelope_v2 import wrap_exception


def _make_job(job_id: str) -> Job:
    job = Job(job_id=job_id, priority=JobPriority.NORMAL)
    return job


def test_run_job_callback_missing_normalized_record_raises(caplog) -> None:
    controller = JobExecutionController(replay_runner=SimpleNamespace(run_njr=lambda record: {}))
    job = _make_job("missing")
    caplog.set_level(logging.ERROR)

    with pytest.raises(ValueError) as excinfo:
        controller._run_job_callback(job)

    assert "Missing normalized record" in str(excinfo.value)
    assert any(
        "JOB_EXEC_ERROR | Missing normalized record" in record.message for record in caplog.records
    )


class _FailReplay:
    def replay_njr(self, record: object) -> dict:
        raise RuntimeError("replay failed")

    def run_njr(self, record: object, *args: Any, **kwargs: Any) -> dict:
        return self.replay_njr(record)


def test_run_job_callback_replay_exception_logs_and_raises(caplog) -> None:
    controller = JobExecutionController(replay_runner=_FailReplay())
    job = _make_job("replay-error")
    job._normalized_record = SimpleNamespace(job_id="replay-error")
    caplog.set_level(logging.INFO)

    with pytest.raises(RuntimeError) as excinfo:
        controller._run_job_callback(job)

    assert "NJR execution failed" in str(excinfo.value)
    assert any("JOB_EXEC_REPLAY" in record.message for record in caplog.records)
    assert any(
        "JOB_EXEC_ERROR | NJR execution failed" in record.message for record in caplog.records
    )


def test_handle_runtime_status_update_preserves_stage_detail() -> None:
    captured = {}
    controller = JobExecutionController(replay_runner=SimpleNamespace(run_njr=lambda record: {}))
    controller.set_app_state(SimpleNamespace(set_runtime_status=lambda status: captured.setdefault("status", status)))

    controller._handle_runtime_status_update(
        {
            "job_id": "job-1",
            "current_stage": "svd_native",
            "stage_detail": "inference",
            "progress": 0.3,
        }
    )

    assert captured["status"].current_stage == "svd_native"
    assert captured["status"].stage_detail == "inference"


def test_run_job_callback_resumes_from_checkpoint_after_retry(tmp_path: Path) -> None:
    checkpoint = tmp_path / "stage.png"
    checkpoint.write_bytes(b"png")

    def crash_exc() -> RuntimeError:
        exc = RuntimeError("Connection refused while contacting WebUI")
        wrap_exception(
            exc,
            subsystem="pipeline",
            stage="adetailer",
            context={
                "diagnostics": {
                    "request_summary": {
                        "endpoint": "/sdapi/v1/adetailer",
                        "method": "POST",
                        "stage": "adetailer",
                        "status": 500,
                    },
                    "webui_unavailable": True,
                    "error_message": "Connection refused while contacting WebUI",
                }
            },
        )
        return exc

    class _ResumeRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str | None, list[str]]] = []

        def run_njr(self, record: NormalizedJobRecord, *args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls.append((record.start_stage, list(record.input_image_paths)))
            checkpoint_callback = kwargs.get("checkpoint_callback")
            if len(self.calls) == 1:
                checkpoint_callback("adetailer", [str(checkpoint)], {"image_count": 1})
                raise crash_exc()
            return {"success": True, "variants": [{"path": str(checkpoint)}]}

    controller = JobExecutionController(replay_runner=_ResumeRunner())
    job = _make_job("resume-job")
    record = NormalizedJobRecord(
        job_id="resume-job",
        config={"prompt": "castle"},
        path_output_dir="output",
        filename_template="{seed}",
        prompt_pack_id="pack-1",
        prompt_pack_name="Pack 1",
        positive_prompt="castle",
        stage_chain=[
            StageConfig(stage_type="txt2img", enabled=True),
            StageConfig(stage_type="adetailer", enabled=True),
            StageConfig(stage_type="upscale", enabled=True),
        ],
    )
    job._normalized_record = record  # type: ignore[attr-defined]
    job.snapshot = {"normalized_job": asdict(record)}

    result = controller.get_runner().run_once(job)

    runner = controller._replay_engine._runner  # type: ignore[attr-defined]
    assert runner.calls[0] == (None, [])
    assert runner.calls[1] == ("upscale", [str(checkpoint)])
    assert result["success"] is True

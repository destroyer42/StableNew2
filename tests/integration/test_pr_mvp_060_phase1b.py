from __future__ import annotations

import json
import time
from pathlib import Path

from src.contracts import PackJobEntry
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager


def _write_pack(path: Path, prompt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "name": path.stem,
                    "slots": [{"index": 0, "text": prompt, "negative": "blur"}],
                    "matrix": {"enabled": False, "slots": []},
                },
                "preset_data": {
                    "pipeline": {
                        "txt2img_enabled": True,
                        "img2img_enabled": False,
                        "adetailer_enabled": False,
                        "upscale_enabled": False,
                        "images_per_prompt": 1,
                        "loop_count": 1,
                        "loop_type": "pipeline",
                        "variant_mode": "standard",
                        "output_dir": str(path.parent / "output"),
                        "apply_global_negative_txt2img": False,
                    },
                    "txt2img": {
                        "model": "baseline-model.safetensors",
                        "vae": "baseline-vae.safetensors",
                        "sampler_name": "Euler",
                        "scheduler": "Karras",
                        "steps": 8,
                        "cfg_scale": 5.0,
                        "width": 512,
                        "height": 512,
                        "seed": 606060,
                        "negative_prompt": "",
                        "enable_hr": False,
                    },
                    "randomization": {"enabled": False},
                    "aesthetic": {"enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )


def _wait_for_status(repository: JobRepository, job_id: str, status: JobStatus) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        entry = repository.get_job(job_id)
        if entry is not None and entry.status is status:
            return
        time.sleep(0.01)
    entry = repository.get_job(job_id)
    assert entry is not None
    assert entry.status is status


def test_phase1b_repeats_preview_submission_and_manual_dispatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pack_paths = [
        tmp_path / "packs" / "pack-a.json",
        tmp_path / "packs" / "pack-b.json",
        tmp_path / "packs" / "pack-c.json",
    ]
    for index, path in enumerate(pack_paths, 1):
        _write_pack(path, f"deterministic scene {index}")

    app_state = AppStateV2()
    app_state.auto_run_queue = False
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    executed: list[str] = []

    def execute(job):
        executed.append(job.job_id)
        return {"success": True, "variants": []}

    service = JobService(
        queue,
        run_callable=execute,
        require_normalized_records=True,
    )
    controller = PipelineController(
        app_state=app_state,
        config_manager=ConfigManager(presets_dir=tmp_path / "presets"),
        job_service=service,
    )

    submitted_ids: list[str] = []
    try:
        for path in pack_paths:
            app_state.add_packs_to_job_draft(
                [
                    PackJobEntry(
                        pack_id=path.name,
                        pack_name=path.stem,
                        config_snapshot={},
                        stage_flags={
                            "txt2img": True,
                            "img2img": False,
                            "adetailer": False,
                            "upscale": False,
                        },
                        randomizer_metadata={"enabled": False},
                        pack_row_index=0,
                    )
                ]
            )
            controller.refresh_preview_from_state()
            preview = list(app_state.preview_jobs)
            assert len(preview) == 1
            assert preview[0].positive_prompt.startswith("deterministic scene")
            assert preview[0].job_id not in submitted_ids
            assert controller.submit_preview_jobs_to_queue(records=preview) == 1
            submitted_ids.append(preview[0].job_id)

            app_state.clear_job_draft()
            assert app_state.preview_jobs == []

        assert service.auto_run_enabled is False
        assert executed == []
        assert [job.job_id for job in queue.list_jobs(JobStatus.QUEUED)] == submitted_ids

        assert controller.on_queue_send_job_v2() is True
        _wait_for_status(repository, submitted_ids[0], JobStatus.COMPLETED)
        assert executed == submitted_ids[:1]
        assert [job.job_id for job in queue.list_jobs(JobStatus.QUEUED)] == submitted_ids[1:]
        assert service.auto_run_enabled is False

        controller.on_pause_queue_v2()
        queued_before_pause = [job.job_id for job in queue.list_jobs(JobStatus.QUEUED)]
        assert app_state.is_queue_paused is True
        assert controller.on_queue_send_job_v2() is False
        assert executed == submitted_ids[:1]
        assert [job.job_id for job in queue.list_jobs(JobStatus.QUEUED)] == queued_before_pause

        controller.on_resume_queue_v2()
        assert app_state.is_queue_paused is False
        assert service.auto_run_enabled is False
        assert executed == submitted_ids[:1]

        for job_id in submitted_ids[1:]:
            assert controller.on_queue_send_job_v2() is True
            _wait_for_status(repository, job_id, JobStatus.COMPLETED)

        assert executed == submitted_ids
    finally:
        service.stop()
        repository.close()

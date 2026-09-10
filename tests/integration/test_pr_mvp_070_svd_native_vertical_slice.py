from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.svd_controller import SVDController
from src.gui.app_state_v2 import AppStateV2
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.result_contract_v26 import collect_canonical_artifacts
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from src.utils.logger import StructuredLogger
from src.video.svd_config import SVDConfig


def test_svd_native_vertical_slice_queue_artifact_history_and_replay(tmp_path: Path, monkeypatch) -> None:
    """Use the production queue/runner path while faking only expensive native inference."""
    source_path = tmp_path / "selected.png"
    Image.new("RGB", (32, 32), "navy").save(source_path)
    output_dir = tmp_path / "output"

    class _FakeSVDRunner:
        def __init__(self, *, output_root, status_callback=None) -> None:
            self.output_root = Path(output_root)
            self.status_callback = status_callback

        def run(self, *, source_image_path, config, job_id):
            assert Path(source_image_path) == source_path
            assert config.inference.local_files_only is False
            assert self.status_callback is not None
            self.status_callback({"stage_detail": "inference", "progress": 0.5, "current_step": 1, "total_steps": 2})
            self.output_root.mkdir(parents=True, exist_ok=True)
            video_path = self.output_root / "native-svd.mp4"
            preview_path = self.output_root / "native-svd-preview.png"
            manifest_path = self.output_root / "native-svd.json"
            video_path.write_bytes(b"fake-mp4")
            Image.new("RGB", (8, 8), "teal").save(preview_path)
            manifest_path.write_text(json.dumps({"job_id": job_id, "source": str(source_image_path)}), encoding="utf-8")
            return SimpleNamespace(
                source_image_path=source_path,
                video_path=video_path,
                gif_path=None,
                frame_paths=[],
                thumbnail_path=preview_path,
                metadata_path=manifest_path,
                frame_count=25,
                fps=7,
                seed=None,
                model_id=config.inference.model_id,
                preprocess=SimpleNamespace(
                    source_path=source_path,
                    prepared_path=source_path,
                    original_width=32,
                    original_height=32,
                    target_width=1024,
                    target_height=576,
                    resize_mode="center_crop",
                    was_resized=True,
                    was_padded=False,
                    was_cropped=True,
                ),
                postprocess={"applied": []},
            )

    monkeypatch.setattr("src.video.svd_runner.SVDRunner", _FakeSVDRunner)
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda config, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    pipeline_ref: dict[str, PipelineController] = {}
    service = JobService(
        queue,
        run_callable=lambda job: pipeline_ref["controller"]._run_job(job),
        require_normalized_records=True,
    )
    service.auto_run_enabled = False
    runner = PipelineRunner(
        SimpleNamespace(),
        StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(output_dir),
    )
    pipeline_controller = PipelineController(
        app_state=AppStateV2(),
        config_manager=ConfigManager(presets_dir=tmp_path / "presets"),
        job_service=service,
        pipeline_runner=runner,
    )
    pipeline_ref["controller"] = pipeline_controller
    service.runner.stop()
    app_surface = SimpleNamespace(output_dir=str(output_dir), job_service=service)
    svd_controller = SVDController(app_controller=app_surface)
    config = SVDConfig.from_dict(
        {
            "inference": {"local_files_only": False, "cache_dir": str(tmp_path / "hf-cache")},
            "postprocess": {"face_restore": {"enabled": False}, "interpolation": {"enabled": False}, "upscale": {"enabled": False}},
        }
    )

    original_id = svd_controller.submit_svd_job(source_image_path=source_path, config=config)
    original_job = queue.get_job(original_id)
    assert original_job is not None
    original_record = original_job._normalized_record
    assert original_record.input_image_paths == (str(source_path),)
    assert original_record.config["svd_native"]["inference"]["local_files_only"] is False

    service.runner.run_once(original_job)
    completed = repository.get_job(original_id)
    assert completed is not None and completed.status is JobStatus.COMPLETED
    artifacts = collect_canonical_artifacts(completed.result)
    assert len(artifacts) == 1
    assert artifacts[0]["job_id"] == original_id
    assert artifacts[0]["stage"] == "svd_native"
    assert Path(artifacts[0]["primary_path"]).is_file()

    assert pipeline_controller.replay_job_from_history(original_id) == 1
    [replay_job] = queue.list_jobs(JobStatus.QUEUED)
    replay_record = replay_job._normalized_record
    assert replay_record.job_id != original_id
    assert replay_record.source.parent_job_id == original_id
    assert replay_record.input_image_paths == original_record.input_image_paths
    assert replay_record.config == original_record.config

    service.runner.run_once(replay_job)
    replay_completed = repository.get_job(replay_record.job_id)
    assert replay_completed is not None and replay_completed.status is JobStatus.COMPLETED
    assert collect_canonical_artifacts(replay_completed.result)[0]["job_id"] == replay_record.job_id
    service.runner.stop()
    repository.close()


def test_svd_admission_failure_creates_no_queue_artifact(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "selected.png"
    Image.new("RGB", (8, 8), "white").save(source_path)
    submitted: list[object] = []
    app_surface = SimpleNamespace(
        output_dir=str(tmp_path / "output"),
        job_service=SimpleNamespace(submit_njrs=lambda records, _policy: submitted.extend(records)),
    )
    controller = SVDController(app_controller=app_surface)
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda config, **_kwargs: SimpleNamespace(available=False, blocking_reasons=("Diffusers is unavailable",)),
    )

    try:
        controller.submit_svd_job(source_image_path=source_path, config=SVDConfig())
        assert False, "expected SVD admission to reject the job"
    except RuntimeError as exc:
        assert "admission blocked" in str(exc)
    assert submitted == []
    assert not (tmp_path / "output").exists()

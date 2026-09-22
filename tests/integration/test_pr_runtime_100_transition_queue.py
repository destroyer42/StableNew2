"""PR-RUNTIME-100: production queue path exercises the real runtime transition coordinator.

Immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> the real ``SVDNativeVideoBackend``
-> ``RuntimeTransitionCoordinator.prepare_for`` -> fake owned/external process managers ->
artifact/history.  Only native SVD inference itself is faked (as in the accepted PR-MVP-070
vertical slice); the backend, resolver and transition coordinator are all production code.
"""

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
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.services.runtime_transition_service import (
    RuntimeTransitionCoordinator,
)
from src.utils.config import ConfigManager
from src.utils.logger import StructuredLogger
from src.video.svd_config import SVDConfig
from src.video.svd_native_backend import SVDNativeVideoBackend
from src.video.video_backend_registry import VideoBackendRegistry


class _FakeManager:
    def __init__(self, *, running: bool, owned: bool, stop_name: str) -> None:
        self._running = running
        self.owns_process = owned
        self.stop_calls = 0
        setattr(self, stop_name, self._stop)

    def is_running(self) -> bool:
        return self._running

    def _stop(self) -> None:
        self.stop_calls += 1
        self._running = False
        self.owns_process = False


def _fake_svd_runner_module(monkeypatch, source_path: Path):
    class _FakeSVDRunner:
        def __init__(self, *, output_root, status_callback=None) -> None:
            self.output_root = Path(output_root)
            self.status_callback = status_callback

        def run(self, *, source_image_path, config, job_id, cancel_token=None, **_kwargs):
            assert Path(source_image_path) == source_path
            self.output_root.mkdir(parents=True, exist_ok=True)
            video_path = self.output_root / "native-svd.mp4"
            preview_path = self.output_root / "native-svd-preview.png"
            manifest_path = self.output_root / "native-svd.json"
            video_path.write_bytes(b"fake-mp4")
            Image.new("RGB", (8, 8), "teal").save(preview_path)
            manifest_path.write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
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


def _build_stack(tmp_path: Path, *, coordinator: RuntimeTransitionCoordinator):
    registry = VideoBackendRegistry()
    registry.register(SVDNativeVideoBackend(transition=coordinator))
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    ref: dict[str, PipelineController] = {}
    service = JobService(
        queue, run_callable=lambda job: ref["c"]._run_job(job), require_normalized_records=True
    )
    runner = PipelineRunner(
        SimpleNamespace(),
        StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(tmp_path / "output"),
        video_backend_registry=registry,
    )
    controller = PipelineController(
        app_state=AppStateV2(),
        config_manager=ConfigManager(presets_dir=tmp_path / "presets"),
        job_service=service,
        pipeline_runner=runner,
    )
    ref["c"] = controller
    service.auto_run_enabled = False
    service.runner.stop()
    return repository, queue, service


def _submit(service, source_path: Path) -> str:
    app_surface = SimpleNamespace(
        output_dir=str(source_path.parent / "output"), job_service=service
    )
    controller = SVDController(app_controller=app_surface)
    config = SVDConfig.from_dict(
        {
            "inference": {"local_files_only": False},
            "postprocess": {
                "face_restore": {"enabled": False},
                "interpolation": {"enabled": False},
                "upscale": {"enabled": False},
            },
        }
    )
    return controller.submit_svd_job(source_image_path=source_path, config=config)


def test_real_svd_backend_releases_owned_a1111_and_comfy_through_the_queue(
    tmp_path: Path, monkeypatch
) -> None:
    source_path = tmp_path / "selected.png"
    Image.new("RGB", (32, 32), "navy").save(source_path)
    _fake_svd_runner_module(monkeypatch, source_path)

    owned_webui = _FakeManager(running=True, owned=True, stop_name="stop_webui")
    owned_comfy = _FakeManager(running=True, owned=True, stop_name="stop")
    coordinator = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: owned_webui,
        comfy_manager_getter=lambda: owned_comfy,
    )
    repository, queue, service = _build_stack(tmp_path, coordinator=coordinator)

    job_id = _submit(service, source_path)
    service.runner.run_once(queue.get_job(job_id))

    completed = repository.get_job(job_id)
    assert completed is not None and completed.status is JobStatus.COMPLETED
    # The production backend really called the coordinator, which really used each runtime's
    # own existing owner (never a duplicated authority) to release only what it owns.
    assert owned_webui.stop_calls == 1 and owned_comfy.stop_calls == 1
    assert owned_webui.owns_process is False and owned_comfy.owns_process is False
    repository.close()


def test_an_external_conflicting_runtime_blocks_dispatch_without_mutation_or_retry(
    tmp_path: Path, monkeypatch
) -> None:
    source_path = tmp_path / "selected.png"
    Image.new("RGB", (32, 32), "navy").save(source_path)
    _fake_svd_runner_module(monkeypatch, source_path)

    external_comfy = _FakeManager(running=True, owned=False, stop_name="stop")
    coordinator = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: None, comfy_manager_getter=lambda: external_comfy
    )
    repository, queue, service = _build_stack(tmp_path, coordinator=coordinator)

    job_id = _submit(service, source_path)
    service.runner.run_once(queue.get_job(job_id))

    failed = repository.get_job(job_id)
    assert failed is not None and failed.status is JobStatus.FAILED
    assert external_comfy.stop_calls == 0  # never mutated
    assert "action_required" in str(failed.error_message or failed.result).lower()
    # SQLite is still the sole lifecycle authority: no replay/requeue happened automatically.
    assert queue.list_jobs(JobStatus.QUEUED) == []
    assert queue.list_jobs(JobStatus.RUNNING) == []
    repository.close()


def test_external_configured_endpoint_without_manager_blocks_before_svd_dispatch(
    tmp_path: Path, monkeypatch
) -> None:
    """An operator-run Comfy has no manager handle but must still block native SVD."""

    source_path = tmp_path / "selected.png"
    Image.new("RGB", (32, 32), "navy").save(source_path)
    _fake_svd_runner_module(monkeypatch, source_path)
    coordinator = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: None,
        comfy_manager_getter=lambda: None,
        webui_endpoint_present=lambda: False,
        comfy_endpoint_present=lambda: True,
    )
    repository, queue, service = _build_stack(tmp_path, coordinator=coordinator)
    run_svd_native_stage_called = False

    def _unexpected_svd_dispatch(*_args, **_kwargs):
        nonlocal run_svd_native_stage_called
        run_svd_native_stage_called = True
        raise AssertionError("transition must block before SVD dispatch")

    monkeypatch.setattr("src.pipeline.executor.Pipeline.run_svd_native_stage", _unexpected_svd_dispatch)
    job_id = _submit(service, source_path)
    service.runner.run_once(queue.get_job(job_id))

    failed = repository.get_job(job_id)
    assert failed is not None and failed.status is JobStatus.FAILED
    assert run_svd_native_stage_called is False
    assert "action_required" in str(failed.error_message or failed.result).lower()
    assert queue.list_jobs(JobStatus.QUEUED) == []
    assert queue.list_jobs(JobStatus.RUNNING) == []
    repository.close()


def test_a_failed_owned_release_blocks_dispatch_and_never_falls_through_to_generation(
    tmp_path: Path, monkeypatch
) -> None:
    source_path = tmp_path / "selected.png"
    Image.new("RGB", (32, 32), "navy").save(source_path)
    _fake_svd_runner_module(monkeypatch, source_path)

    class _StubbornManager(_FakeManager):
        def _stop(self) -> None:  # noqa: D401 - stop() runs but never actually releases
            self.stop_calls += 1

    stubborn_webui = _StubbornManager(running=True, owned=True, stop_name="stop_webui")
    coordinator = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: stubborn_webui, comfy_manager_getter=lambda: None
    )
    repository, queue, service = _build_stack(tmp_path, coordinator=coordinator)

    job_id = _submit(service, source_path)
    service.runner.run_once(queue.get_job(job_id))

    failed = repository.get_job(job_id)
    assert failed is not None and failed.status is JobStatus.FAILED
    assert stubborn_webui.stop_calls == 1  # release was attempted exactly once, not retried
    assert "release_failed" in str(failed.error_message or failed.result).lower()
    repository.close()

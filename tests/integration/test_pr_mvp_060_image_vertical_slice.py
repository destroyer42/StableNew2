from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from src.contracts import PackJobEntry
from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.gui.app_state_v2 import AppStateV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.result_contract_v26 import collect_canonical_artifacts
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from src.utils.logger import StructuredLogger
from src.utils.prompt_packs import PromptPackInfo


class _DeterministicWebUI:
    options_write_enabled = True

    def __init__(self, current_model: str) -> None:
        self.calls: list[dict[str, object]] = []
        self.current_model = current_model
        self.set_model_calls: list[str] = []
        image = Image.new("RGB", (2, 2), color=(20, 40, 60))
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        self._image = base64.b64encode(encoded.getvalue()).decode("ascii")

    def generate_images(self, *, stage: str, payload: dict[str, object]):
        self.calls.append({"stage": stage, "payload": dict(payload)})
        result = SimpleNamespace(
            images=[self._image],
            info={"seed": payload["seed"]},
            stage=stage,
            timings={},
        )
        return SimpleNamespace(ok=True, result=result, error=None)

    def get_progress(self, **_kwargs):
        return None

    def check_api_ready(self, **_kwargs) -> bool:
        return True

    def get_current_model(self) -> str:
        return self.current_model

    def get_current_vae(self) -> str:
        return "baseline-vae.safetensors"

    def set_model(self, model: str) -> bool:
        self.set_model_calls.append(model)
        self.current_model = model
        return True

    def set_vae(self, _vae: str) -> None:
        return None

    def check_connection(self, **_kwargs) -> bool:
        return True

    def free_vram(self, **_kwargs) -> bool:
        return True


def _write_baseline_pack(path: Path, output_dir: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "name": "MVP 060 Baseline",
                    "slots": [
                        {
                            "index": 0,
                            "text": "a blue lighthouse at dawn",
                            "negative": "blur, watermark",
                        }
                    ],
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
                        "output_dir": str(output_dir),
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


@pytest.mark.parametrize(
    ("initial_model", "expected_switches"),
    [
        ("baseline-model.safetensors [abc123]", []),
        ("ambient-model.safetensors", ["baseline-model.safetensors"]),
    ],
)
def test_promptpack_queue_run_artifact_history_replay_production_composition(
    tmp_path: Path,
    monkeypatch,
    initial_model: str,
    expected_switches: list[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    pack_path = tmp_path / "packs" / "mvp-060-baseline.json"
    output_dir = tmp_path / "artifacts"
    _write_baseline_pack(pack_path, output_dir)

    state = AppStateV2()
    state.auto_run_queue = False
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    controller_ref: dict[str, PipelineController] = {}

    def execute_job(job):
        return controller_ref["controller"]._run_job(job)

    service = JobService(
        queue,
        run_callable=execute_job,
        require_normalized_records=True,
    )
    service.auto_run_enabled = False
    client = _DeterministicWebUI(initial_model)
    pipeline_runner = PipelineRunner(
        client,
        StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(output_dir),
    )
    controller = PipelineController(
        app_state=state,
        config_manager=ConfigManager(presets_dir=tmp_path / "presets"),
        job_service=service,
        pipeline_runner=pipeline_runner,
    )
    controller_ref["controller"] = controller
    queue_runner = service.runner
    queue_runner.stop()

    state.add_packs_to_job_draft(
        [
            PackJobEntry(
                pack_id=pack_path.name,
                pack_name="MVP 060 Baseline",
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
    [original] = controller.get_preview_jobs()
    original_snapshot = original.to_dict()

    assert original.positive_prompt == "a blue lighthouse at dawn"
    assert original.negative_prompt == "blur, watermark"
    assert original.stage_chain_labels == ["txt2img"]
    assert original.images_per_prompt == 1

    assert service.submit_njrs([original], SubmissionPolicy(start_when_idle=False)) == [
        original.job_id
    ]
    queued_entry = repository.get_job(original.job_id)
    assert queued_entry is not None
    assert queued_entry.status is JobStatus.QUEUED
    assert client.calls == []

    queued_job = queue.get_job(original.job_id)
    assert queued_job is not None
    queue_runner.run_once(queued_job)

    completed = repository.get_job(original.job_id)
    assert completed is not None
    assert completed.status is JobStatus.COMPLETED
    assert original.to_dict() == original_snapshot
    original_artifacts = collect_canonical_artifacts(completed.result)
    assert len(original_artifacts) == 1
    assert original_artifacts[0]["job_id"] == original.job_id
    assert original_artifacts[0]["stage"] == "txt2img"
    assert Path(original_artifacts[0]["primary_path"]).is_file()

    assert controller.replay_job_from_history(original.job_id) == 1
    [replay_job] = queue.list_jobs(JobStatus.QUEUED)
    replay = replay_job._normalized_record
    assert replay.job_id != original.job_id
    assert replay.source.parent_job_id == original.job_id
    assert original.to_dict() == original_snapshot

    queue_runner.run_once(replay_job)
    replay_completed = repository.get_job(replay.job_id)
    assert replay_completed is not None
    assert replay_completed.status is JobStatus.COMPLETED
    replay_artifacts = collect_canonical_artifacts(replay_completed.result)
    assert len(replay_artifacts) == 1
    assert replay_artifacts[0]["job_id"] == replay.job_id
    assert Path(replay_artifacts[0]["primary_path"]).is_file()

    expected_payload = {
        "prompt": original.positive_prompt,
        "negative_prompt": original.negative_prompt,
        "sd_model": original.base_model,
        "sd_vae": original.vae,
        "sampler_name": original.sampler_name,
        "scheduler": original.scheduler,
        "steps": original.steps,
        "cfg_scale": original.cfg_scale,
        "width": original.width,
        "height": original.height,
        "seed": original.seed,
        "batch_size": 1,
        "n_iter": 1,
    }
    assert len(client.calls) == 2
    assert client.set_model_calls == expected_switches
    for call in client.calls:
        payload = call["payload"]
        assert call["stage"] == "txt2img"
        assert all(payload[key] == value for key, value in expected_payload.items())

    queue_runner.stop()
    repository.close()


def test_phase2d_consolidated_selector_queue_send_and_replay(tmp_path: Path, monkeypatch) -> None:
    """Compose the proven 060 boundaries through the production-shaped GUI path."""

    monkeypatch.chdir(tmp_path)
    pack_path = tmp_path / "packs" / "mvp-060-consolidated.json"
    output_dir = tmp_path / "artifacts"
    _write_baseline_pack(pack_path, output_dir)
    document = json.loads(pack_path.read_text(encoding="utf-8"))
    document["pack_data"]["slots"] = [
        {"index": 0, "text": "a blue lighthouse at dawn", "negative": "blur"},
        {"index": 1, "text": "a red lighthouse at dusk", "negative": "watermark"},
        {"index": 2, "text": "a green lighthouse at night", "negative": "noise"},
    ]
    pack_path.write_text(json.dumps(document), encoding="utf-8")

    def _wait_until(predicate, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        assert predicate(), "condition was not reached before timeout"

    class _Window:
        root = None
        app_state = AppStateV2()
        pipeline_tab = SimpleNamespace(
            txt2img_enabled=True,
            img2img_enabled=False,
            adetailer_enabled=False,
            upscale_enabled=False,
        )

        @staticmethod
        def run_in_main_thread(callback):
            callback()

        @staticmethod
        def run_in_main_thread_later(_delay_ms, callback):
            callback()

        @staticmethod
        def connect_controller(_controller):
            return None

    class _Listbox:
        @staticmethod
        def curselection():
            return (0,)

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    controller_ref: dict[str, AppController] = {}

    def execute_job(job):
        return controller_ref["controller"].pipeline_controller._run_job(job)

    service = JobService(
        queue,
        run_callable=execute_job,
        require_normalized_records=True,
    )
    service.auto_run_enabled = False
    client = _DeterministicWebUI("ambient-model.safetensors")
    pipeline_runner = PipelineRunner(
        client,
        StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(output_dir),
    )
    controller = AppController(
        main_window=None,
        threaded=True,
        pipeline_runner=pipeline_runner,
        job_service=service,
    )
    controller_ref["controller"] = controller
    controller.load_packs = lambda: None  # type: ignore[method-assign]
    controller._update_status = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    window = _Window()
    window.app_state.auto_run_queue = False
    controller.set_main_window(window)
    service.auto_run_enabled = False
    controller.packs = [PromptPackInfo(name=pack_path.stem, path=pack_path)]

    try:
        assert controller.pipeline_controller._app_state is controller.app_state
        assert controller._projection_sink._app_state is controller.app_state

        sidebar = object.__new__(SidebarPanelV2)
        sidebar.pack_listbox = _Listbox()
        sidebar.controller = controller
        sidebar._current_pack_names = [pack_path.stem]
        sidebar._on_add_to_job()

        _wait_until(
            lambda: len(controller.app_state.job_draft.packs) == 3
            and len(controller.app_state.preview_jobs) == 3
        )
        assert PreviewPanelV2._can_add_to_queue(
            controller.app_state.job_draft,
            controller.app_state.preview_jobs,
        )
        assert controller.override_pack_config_enabled is False

        controller.on_add_job_to_queue_v2()
        _wait_until(lambda: len(queue.list_jobs(JobStatus.QUEUED)) == 3)
        assert client.calls == []
        assert all(
            repository.get_job(job.job_id).status is JobStatus.QUEUED
            for job in queue.list_jobs(JobStatus.QUEUED)
        )

        initial_queued = queue.list_jobs(JobStatus.QUEUED)
        original_id = initial_queued[0].job_id
        original_njr = initial_queued[0]._normalized_record
        assert original_njr is not None
        original_snapshot = original_njr.to_dict()

        controller.on_queue_send_job_v2()
        _wait_until(lambda: repository.get_job(original_id).status is JobStatus.COMPLETED)
        original_entry = repository.get_job(original_id)
        assert original_entry is not None
        original_artifacts = collect_canonical_artifacts(original_entry.result)
        assert original_artifacts and original_artifacts[0]["job_id"] == original_id

        assert controller.on_replay_history_job_v2(original_id) is True
        queued_after_replay = queue.list_jobs(JobStatus.QUEUED)
        replay_ids = {job.job_id for job in queued_after_replay} - {
            job.job_id for job in initial_queued[1:]
        }
        assert len(replay_ids) == 1
        replay_id = replay_ids.pop()
        replay_job = queue.get_job(replay_id)
        assert replay_job is not None and replay_job._normalized_record is not None
        assert replay_job._normalized_record.source.parent_job_id == original_id
        assert replay_job._normalized_record.job_id != original_id

        while queue.list_jobs(JobStatus.QUEUED):
            queued_ids = {job.job_id for job in queue.list_jobs(JobStatus.QUEUED)}
            _wait_until(lambda: not service.runner.is_running())
            controller.on_queue_send_job_v2()
            _wait_until(
                lambda: any(
                    repository.get_job(job_id).status is JobStatus.COMPLETED
                    for job_id in queued_ids
                )
            )

        replay_entry = repository.get_job(replay_id)
        assert replay_entry is not None and replay_entry.status is JobStatus.COMPLETED
        replay_artifacts = collect_canonical_artifacts(replay_entry.result)
        assert replay_artifacts and replay_artifacts[0]["job_id"] == replay_id
        assert original_njr.to_dict() == original_snapshot
        assert client.set_model_calls == ["baseline-model.safetensors"]
    finally:
        service.stop()
        repository.close()

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.contracts import PackJobEntry
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.gui.app_state_v2 import AppStateV2
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.result_contract_v26 import collect_canonical_artifacts
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from src.utils.logger import StructuredLogger


class _DeterministicWebUI:
    options_write_enabled = True

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
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
        return "baseline-model.safetensors"

    def get_current_vae(self) -> str:
        return "baseline-vae.safetensors"

    def set_model(self, _model: str) -> None:
        return None

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


def test_promptpack_queue_run_artifact_history_replay_production_composition(
    tmp_path: Path, monkeypatch
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
    client = _DeterministicWebUI()
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
    for call in client.calls:
        payload = call["payload"]
        assert call["stage"] == "txt2img"
        assert all(payload[key] == value for key, value in expected_payload.items())

    queue_runner.stop()
    repository.close()

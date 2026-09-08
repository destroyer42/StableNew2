from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.controller.job_history_service import NullHistoryService
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.stub_runner import StubRunner
from src.utils.config import ConfigManager


class JourneyConfigManager(ConfigManager):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(presets_dir=tmp_path / "presets")
        self.packs_dir = tmp_path / "packs"
        self.packs_dir.mkdir()

    def load_pack_config(self, pack_name: str) -> dict[str, Any] | None:
        return {
            "pipeline": {
                "images_per_prompt": 1,
                "loop_count": 1,
                "loop_type": "pipeline",
                "variant_mode": "standard",
            },
            "txt2img": {
                "model": "pack-model",
                "sampler_name": "Euler",
                "scheduler": "DDIM",
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
            },
            "randomization": {"enabled": False},
        }


def _write_pack(
    manager: JourneyConfigManager, name: str, text: str, *, matrix: dict | None = None
) -> None:
    pack_path = manager.packs_dir / f"{name}.json"
    document = {
        "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
        "pack_data": {
            "name": name,
            "slots": [{"index": 0, "text": text}],
            "matrix": matrix or {"enabled": False, "slots": []},
        },
        "preset_data": manager.load_pack_config(name),
    }
    pack_path.write_text(json.dumps(document), encoding="utf-8")


def test_promptpack_draft_preview_queue_sqlite_journey(tmp_path: Path) -> None:
    manager = JourneyConfigManager(tmp_path)
    _write_pack(manager, "normal", "A normal portrait")
    _write_pack(
        manager,
        "matrix",
        "A [[subject]]",
        matrix={
            "enabled": True,
            "mode": "sequential",
            "limit": 2,
            "slots": [{"name": "subject", "values": ["wizard", "knight"]}],
        },
    )

    state = AppStateV2()
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(
        queue,
        runner=StubRunner(queue),
        history_service=NullHistoryService(),
        require_normalized_records=True,
    )
    controller = PipelineController(
        app_state=state,
        config_manager=manager,
        job_service=service,
    )
    entries = [
        PackJobEntry(
            pack_id="normal.json",
            pack_name="Normal",
            prompt_text="A normal portrait",
            config_snapshot={
                "txt2img": {
                    "model": "current-model",
                    "sampler_name": "DPM++ 2M",
                    "steps": 31,
                    "cfg_scale": 5.5,
                }
            },
            stage_flags={"txt2img": True},
        ),
        PackJobEntry(
            pack_id="matrix.json",
            pack_name="Matrix",
            prompt_text="A [[subject]]",
            config_snapshot={
                "txt2img": {
                    "model": "current-model",
                    "sampler_name": "DPM++ 2M",
                    "steps": 31,
                    "cfg_scale": 5.5,
                }
            },
            stage_flags={"txt2img": True},
        ),
    ]

    state.add_packs_to_job_draft(entries)
    preview = controller.get_preview_jobs()
    state.set_preview_jobs(preview)

    assert len(preview) == 3
    assert [record.variant_index for record in preview[1:]] == [0, 1]
    assert all(record.variant_total == 2 for record in preview[1:])
    assert {record.matrix_slot_values["subject"] for record in preview[1:]} == {
        "wizard",
        "knight",
    }
    assert all(record.config["model"] == "current-model" for record in preview)
    assert all(record.config["sampler"] == "DPM++ 2M" for record in preview)
    assert all(record.config["steps"] == 31 for record in preview)
    assert all(record.config["cfg_scale"] == 5.5 for record in preview)

    submitted = controller.submit_preview_jobs_to_queue(records=preview)
    assert submitted == 3
    assert repository.count() == 3
    assert len(queue.list_jobs()) == 3

    state.clear_job_draft()
    state.set_preview_jobs([])
    assert not state.job_draft.packs
    assert not state.preview_jobs

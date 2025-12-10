from __future__ import annotations

from typing import Any

from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.gui.state import StateManager
from src.pipeline.job_requests_v2 import PipelineRunMode, PipelineRunSource


def _build_pack_entry() -> PackJobEntry:
    return PackJobEntry(
        pack_id="pack-xyz",
        pack_name="Angelic Warriors",
        config_snapshot={
            "txt2img": {
                "model": "juggernautXL_ragnarokBy.safetensors",
                "sampler_name": "DPM++ 2M",
                "steps": 30,
                "cfg_scale": 7.5,
                "width": 1024,
                "height": 1024,
            }
        },
        prompt_text="Angelic warrior over volcanic lair",
        negative_prompt_text="deformed hands",
        pack_row_index=5,
    )


def _setup_controller(app_state: AppStateV2) -> tuple[PipelineController, list[Any]]:
    controller = PipelineController(state_manager=StateManager(), app_state=app_state)
    submitted: list[Any] = []

    def capture(records: list[Any], request: Any) -> list[str]:
        submitted.extend(records)
        return [getattr(record, "job_id", "job") for record in records]

    controller._job_service.enqueue_njrs = capture
    return controller, submitted


def test_build_run_request_from_job_draft_populates_expected_fields() -> None:
    app_state = AppStateV2()
    entry = _build_pack_entry()
    app_state.job_draft.packs.append(entry)
    app_state.selected_config_snapshot_id = "cfg-123"

    controller, _ = _setup_controller(app_state)
    request = controller._build_run_request_from_job_draft(
        run_mode=PipelineRunMode.QUEUE,
        source=PipelineRunSource.ADD_TO_QUEUE,
    )
    assert request is not None
    assert request.prompt_pack_id == entry.pack_id
    assert request.selected_row_ids == [str(entry.pack_row_index)]
    assert request.config_snapshot_id == "cfg-123"
    assert request.run_mode == PipelineRunMode.QUEUE
    assert request.source == PipelineRunSource.ADD_TO_QUEUE


def test_build_run_request_from_job_draft_returns_none_when_empty() -> None:
    controller, _ = _setup_controller(AppStateV2())
    assert controller._build_run_request_from_job_draft(
        run_mode=PipelineRunMode.QUEUE,
        source=PipelineRunSource.ADD_TO_QUEUE,
    ) is None


def test_enqueue_draft_bundle_uses_job_draft_not_draft_bundle() -> None:
    app_state = AppStateV2()
    entry = _build_pack_entry()
    app_state.job_draft.packs.append(entry)
    app_state.selected_config_snapshot_id = "cfg-123"
    controller, submitted = _setup_controller(app_state)

    job_id = controller.enqueue_draft_bundle()
    assert job_id
    assert submitted, "enqueue_njrs should have been invoked"
    record = submitted[0]
    assert record.prompt_pack_id == entry.pack_id
    assert not app_state.job_draft.packs, "Job draft should be cleared after enqueue"

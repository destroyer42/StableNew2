"""Integration tests for preview → queue → history flow (v2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2
from src.gui.panels_v2.history_panel_v2 import HistoryPanelV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.pipeline.job_models_v2 import JobStatusV2, NormalizedJobRecord
from src.queue.job_model import Job, JobStatus


@dataclass
class MockPromptWorkspaceState:
    prompt: str = "test prompt"
    negative_prompt: str = "test negative"


@dataclass
class MockPipelineState:
    stage_txt2img_enabled: bool = True
    stage_img2img_enabled: bool = False
    stage_upscale_enabled: bool = False
    stage_adetailer_enabled: bool = False
    batch_runs: int = 1


@pytest.fixture
def mock_job_service():
    service = Mock(spec=JobService)
    service._status_callbacks = {}
    service.enqueue_njrs = Mock(return_value=["njr-job-1"])
    service.submit_job_with_run_mode = Mock()

    def set_callback(name: str, callback: callable):
        service._status_callbacks[name] = callback

    def emit_status(job: Job, status: JobStatus):
        for callback in service._status_callbacks.values():
            callback(job, status)

    service.set_status_callback = set_callback
    service.emit_status = emit_status
    return service


@pytest.fixture
def mock_queue_panel():
    panel = Mock(spec=QueuePanelV2)
    panel.upsert_job = Mock()
    panel.remove_job = Mock()
    return panel


@pytest.fixture
def mock_history_panel():
    panel = Mock(spec=HistoryPanelV2)
    panel.append_history_item = Mock()
    return panel


@pytest.fixture
def pipeline_controller(mock_job_service):
    controller = PipelineController(job_service=mock_job_service)
    controller._prompt_state = MockPromptWorkspaceState()
    controller._pipeline_state = MockPipelineState()
    controller.gui_get_pipeline_state = lambda: controller._pipeline_state
    controller.gui_get_pipeline_overrides = lambda: {
        "prompt": controller._prompt_state.prompt,
        "negative_prompt": controller._prompt_state.negative_prompt,
        "model": "test-model",
        "sampler": "Euler a",
        "width": 512,
        "height": 512,
        "steps": 20,
        "cfg_scale": 7.0,
        "seed": 42,
    }
    controller.bind_app_state(AppStateV2())
    return controller


@pytest.fixture
def app_controller(
    mock_job_service,
    mock_queue_panel,
    mock_history_panel,
):
    controller = Mock(spec=AppController)
    controller.job_service = mock_job_service
    controller.queue_panel = mock_queue_panel
    controller.history_panel = mock_history_panel

    def _on_job_status_for_panels(job: Job, status: JobStatus):
        if status in (JobStatus.QUEUED, JobStatus.RUNNING):
            mock_queue_panel.upsert_job(job)
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED):
            mock_queue_panel.remove_job(job.job_id)
            mock_history_panel.append_history_item(job)

    controller._on_job_status_for_panels = _on_job_status_for_panels
    mock_job_service.set_status_callback("panels_update", _on_job_status_for_panels)
    return controller


def _make_normalized_record(job_id: str = "job-1") -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id=job_id,
        config={"prompt": "landscape"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=1.0,
        randomizer_summary=None,
        txt2img_prompt_info=None,
        img2img_prompt_info=None,
        pack_usage=[],
        prompt_pack_id="",
        prompt_pack_name="",
        prompt_pack_row_index=0,
        prompt_pack_version=None,
        positive_prompt="landscape",
        negative_prompt="",
        positive_embeddings=[],
        negative_embeddings=[],
        lora_tags=[],
        matrix_slot_values={},
        steps=20,
        cfg_scale=7.0,
        width=512,
        height=512,
        sampler_name="Euler a",
        scheduler="ddim",
        clip_skip=0,
        base_model="sd",
        vae=None,
        stage_chain=[],
        loop_type="pipeline",
        loop_count=1,
        images_per_prompt=1,
        variant_mode="standard",
        run_mode="QUEUE",
        queue_source="ADD_TO_QUEUE",
        randomization_enabled=False,
        matrix_name=None,
        matrix_mode=None,
        matrix_prompt_mode=None,
        config_variant_label="base",
        config_variant_index=0,
        config_variant_overrides={},
        aesthetic_enabled=False,
        aesthetic_weight=None,
        aesthetic_text=None,
        aesthetic_embedding=None,
        extra_metadata={},
        output_paths=[],
        thumbnail_path=None,
        completed_at=None,
        status=JobStatusV2.QUEUED,
        error_message=None,
    )


class TestPipelineControllerPreviewQueueFlow:
    def test_refresh_preview_updates_app_state(
        self,
        pipeline_controller,
    ):
        record = _make_normalized_record()
        pipeline_controller.get_preview_jobs = Mock(return_value=[record])
        pipeline_controller.refresh_preview_from_state()
        assert pipeline_controller._app_state.preview_jobs == [record]

    def test_submit_preview_jobs_to_queue_uses_njr(
        self,
        pipeline_controller,
        mock_job_service,
    ):
        record = _make_normalized_record()
        pipeline_controller.get_preview_jobs = Mock(return_value=[record])
        submitted = pipeline_controller.submit_preview_jobs_to_queue()
        assert submitted == 1
        assert mock_job_service.submit_job_with_run_mode.call_count == 1
        job_arg = mock_job_service.submit_job_with_run_mode.call_args[0][0]
        assert getattr(job_arg, "_normalized_record") is record


class TestJobStatusCallbackFlow:
    def test_job_queued_updates_queue_panel(
        self, app_controller, mock_queue_panel, mock_job_service
    ):
        job = Job(job_id="test-job-123")
        mock_job_service.emit_status(job, JobStatus.QUEUED)
        mock_queue_panel.upsert_job.assert_called_once_with(job)

    def test_job_running_updates_queue_panel(
        self, app_controller, mock_queue_panel, mock_job_service
    ):
        job = Job(job_id="test-job-123")
        mock_job_service.emit_status(job, JobStatus.RUNNING)
        mock_queue_panel.upsert_job.assert_called_once_with(job)

    def test_job_completed_updates_history_panel(
        self,
        app_controller,
        mock_queue_panel,
        mock_history_panel,
        mock_job_service,
    ):
        job = Job(job_id="test-job-123")
        mock_job_service.emit_status(job, JobStatus.COMPLETED)
        mock_queue_panel.remove_job.assert_called_once_with("test-job-123")
        mock_history_panel.append_history_item.assert_called_once_with(job)

    def test_job_failed_updates_history_panel(
        self,
        app_controller,
        mock_queue_panel,
        mock_history_panel,
        mock_job_service,
    ):
        job = Job(job_id="test-job-123")
        mock_job_service.emit_status(job, JobStatus.FAILED)
        mock_queue_panel.remove_job.assert_called_once_with("test-job-123")
        mock_history_panel.append_history_item.assert_called_once_with(job)

"""Integration tests for the controller preview → queue submission flow (v2).

Panel/history rendering is projection-driven and covered in test_job_queue_integration_v2
and test_runtime_projection_coordinator_v2.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.gui.app_state_v2 import AppStateV2
from src.pipeline.job_models_v2 import NormalizedJobRecord
from tests.helpers.njr_factory import make_pipeline_njr


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
    service.submit_njrs = Mock(return_value=["njr-job-1"])
    return service


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


def _make_normalized_record(job_id: str = "job-1") -> NormalizedJobRecord:
    return make_pipeline_njr(
        job_id=job_id,
        config={"prompt": "landscape"},
        positive_prompt="landscape",
        seed=42,
        base_model="sd",
        prompt_pack_id="pack-1",
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
        mock_job_service.submit_njrs.assert_called_once()
        records_arg, policy_arg = mock_job_service.submit_njrs.call_args[0]
        assert list(records_arg) == [record]
        assert isinstance(policy_arg, SubmissionPolicy)

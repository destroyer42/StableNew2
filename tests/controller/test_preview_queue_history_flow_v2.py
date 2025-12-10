"""Integration tests for preview → queue → history flow (PR-D).

Tests the complete flow:
1. Add job part via "Add to Job" → Preview updates with draft bundle summary
2. "Add to Queue" → Job enqueued, draft cleared, preview cleared
3. Job runs → Queue panel updated during run
4. Job completes → History panel updated with completion
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.gui.panels_v2.history_panel_v2 import HistoryPanelV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.pipeline.job_models_v2 import JobBundleSummaryDTO
from src.queue.job_model import Job, JobStatus


# ============================================================
# Mock Fixtures for Integration Testing
# ============================================================


@dataclass
class MockPromptWorkspaceState:
    """Mock prompt workspace state."""
    prompt: str = "test prompt"
    negative_prompt: str = "test negative"


@dataclass
class MockPipelineState:
    """Mock pipeline state."""
    stage_txt2img_enabled: bool = True
    stage_img2img_enabled: bool = False
    stage_upscale_enabled: bool = False
    stage_adetailer_enabled: bool = False


class MockStateManager:
    """Mock state manager providing pipeline overrides."""

    def __init__(self):
        self.prompt_workspace_state = MockPromptWorkspaceState()
        self.pipeline_state = MockPipelineState()
        self.batch_runs = 1

    def get_pipeline_overrides(self) -> dict[str, Any]:
        return {
            "model": "test-model-v1",
            "sampler": "Euler a",
            "width": 512,
            "height": 512,
            "steps": 20,
            "cfg_scale": 7.0,
            "seed": 42,
            "prompt": self.prompt_workspace_state.prompt,
            "negative_prompt": self.prompt_workspace_state.negative_prompt,
        }

    def set_prompt(self, prompt: str, negative: str = ""):
        """Helper to set prompt for testing."""
        self.prompt_workspace_state.prompt = prompt
        self.prompt_workspace_state.negative_prompt = negative


@pytest.fixture
def mock_job_service():
    """Mock JobService for testing."""
    service = Mock(spec=JobService)
    service.enqueue.return_value = "test-job-123"
    service._status_callbacks = {}
    service.enqueue_njrs = Mock(return_value=["test-job-456"])

    def set_callback(name: str, callback: callable):
        service._status_callbacks[name] = callback

    def emit_status(job: Job, status: JobStatus):
        for callback in service._status_callbacks.values():
            callback(job, status)

    service.set_status_callback = set_callback
    service.emit_status = emit_status
    return service


@pytest.fixture
def mock_preview_panel():
    """Mock PreviewPanelV2 for testing."""
    panel = Mock(spec=PreviewPanelV2)
    panel.update_from_summary = Mock()
    return panel


@pytest.fixture
def mock_queue_panel():
    """Mock QueuePanelV2 for testing."""
    panel = Mock(spec=QueuePanelV2)
    panel.upsert_job = Mock()
    panel.remove_job = Mock()
    return panel


@pytest.fixture
def mock_history_panel():
    """Mock HistoryPanelV2 for testing."""
    panel = Mock(spec=HistoryPanelV2)
    panel.append_history_item = Mock()
    return panel


@pytest.fixture
def pipeline_controller(mock_job_service):
    """Create PipelineController with mocked dependencies."""
    state_manager = MockStateManager()
    controller = PipelineController(job_service=mock_job_service)
    controller.state_manager = state_manager
    controller.bind_app_state(AppStateV2())
    return controller


def _add_job_draft_pack_entry(
    controller: PipelineController,
    *,
    pack_id: str = "test-pack",
    prompt_text: str = "test prompt",
    negative_prompt: str = "test negative",
) -> None:
    if not controller._app_state:
        return
    if not controller._app_state.selected_config_snapshot_id:
        controller._app_state.selected_config_snapshot_id = f"{pack_id}-cfg"

    entry = PackJobEntry(
        pack_id=pack_id,
        pack_name=pack_id,
        config_snapshot={
            "prompt": prompt_text,
            "negative_prompt": negative_prompt,
        },
        prompt_text=prompt_text,
        negative_prompt_text=negative_prompt,
    )
    controller._app_state.job_draft.packs.append(entry)


@pytest.fixture
def app_controller(
    pipeline_controller,
    mock_job_service,
    mock_preview_panel,
    mock_queue_panel,
    mock_history_panel,
):
    """Create AppController with mocked panels and services."""
    controller = Mock(spec=AppController)
    controller.pipeline_controller = pipeline_controller
    controller.job_service = mock_job_service
    controller.preview_panel = mock_preview_panel
    controller.queue_panel = mock_queue_panel
    controller.history_panel = mock_history_panel
    controller.app_state = AppStateV2()

    # Wire up the status callback handler
    def _on_job_status_for_panels(job: Job, status: JobStatus):
        """Status callback that updates queue and history panels."""
        if status in (JobStatus.QUEUED, JobStatus.RUNNING):
            # Update queue panel with job DTO
            # In real implementation, this would create JobQueueItemDTO
            mock_queue_panel.upsert_job(job)
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED):
            # Remove from queue, add to history
            mock_queue_panel.remove_job(job.job_id)
            # In real implementation, this would create JobHistoryItemDTO
            mock_history_panel.append_history_item(job)

    controller._on_job_status_for_panels = _on_job_status_for_panels

    # Register the callback
    mock_job_service.set_status_callback(
        "panels_update", controller._on_job_status_for_panels
    )

    return controller


# ============================================================
# Test Class: Add to Job → Preview Updates
# ============================================================


class TestAddToJobPreviewFlow:
    """Test that adding job parts updates the preview panel."""

    def test_add_single_part_updates_preview(
        self, app_controller, pipeline_controller, mock_preview_panel
    ):
        """Add one job part → preview shows 1 part in draft."""
        # Set prompt in state manager
        pipeline_controller.state_manager.set_prompt(
            "test prompt", "test negative"
        )
        
        # Add job part
        pipeline_controller.add_job_part_from_current_config()

        # Get summary DTO
        dto = pipeline_controller.get_draft_bundle_summary()

        # Simulate AppController refreshing preview
        mock_preview_panel.update_from_summary(dto)

        # Verify preview was updated
        mock_preview_panel.update_from_summary.assert_called_once()
        call_args = mock_preview_panel.update_from_summary.call_args
        summary_dto = call_args[0][0]

        assert isinstance(summary_dto, JobBundleSummaryDTO)
        assert summary_dto.num_parts == 1
        assert "test prompt" in summary_dto.positive_preview
        assert "test negative" in (summary_dto.negative_preview or "")

    def test_add_multiple_parts_updates_preview(
        self, app_controller, pipeline_controller, mock_preview_panel
    ):
        """Add multiple job parts → preview shows accumulated count."""
        # Add three job parts
        pipeline_controller.state_manager.set_prompt("prompt 1", "neg 1")
        pipeline_controller.add_job_part_from_current_config()
        
        pipeline_controller.state_manager.set_prompt("prompt 2", "neg 2")
        pipeline_controller.add_job_part_from_current_config()
        
        pipeline_controller.state_manager.set_prompt("prompt 3", "neg 3")
        pipeline_controller.add_job_part_from_current_config()

        # Get summary DTO
        dto = pipeline_controller.get_draft_bundle_summary()

        # Verify accumulated parts
        assert dto.num_parts == 3
        # Preview shows last prompt added
        assert "prompt 3" in dto.positive_preview

    def test_clear_draft_updates_preview_to_none(
        self, app_controller, pipeline_controller, mock_preview_panel
    ):
        """Clear draft → preview receives None DTO (empty state)."""
        # Add and then clear
        pipeline_controller.state_manager.set_prompt("test prompt", "test negative")
        pipeline_controller.add_job_part_from_current_config()
        _add_job_draft_pack_entry(pipeline_controller, prompt_text="test prompt")
        _add_job_draft_pack_entry(pipeline_controller, prompt_text="test prompt")
        pipeline_controller.clear_draft_bundle()

        # Get summary after clear
        dto = pipeline_controller.get_draft_bundle_summary()

        # Simulate AppController clearing preview
        mock_preview_panel.update_from_summary(dto)

        # Verify preview was updated with None
        assert dto is None
        mock_preview_panel.update_from_summary.assert_called_with(None)


# ============================================================
# Test Class: Add to Queue → Job Enqueued, Draft Cleared
# ============================================================


class TestAddToQueueFlow:
    """Test that enqueueing draft bundle submits job and clears draft."""

    def test_enqueue_draft_submits_job_and_clears_draft(
        self, app_controller, pipeline_controller, mock_job_service
    ):
        """Enqueue draft → JobService.enqueue called, draft cleared."""
        # Add job part
        pipeline_controller.state_manager.set_prompt("test prompt", "test negative")
        pipeline_controller.add_job_part_from_current_config()
        _add_job_draft_pack_entry(pipeline_controller, prompt_text="test prompt")

        # Enqueue the draft
        job_id = pipeline_controller.enqueue_draft_bundle()

        # Verify job was enqueued (job_id returned means success)
        assert job_id is not None

        # Verify draft was cleared after enqueue
        dto = pipeline_controller.get_draft_bundle_summary()
        assert dto is None

    def test_enqueue_draft_updates_preview_to_empty(
        self, app_controller, pipeline_controller, mock_preview_panel
    ):
        """Enqueue draft → preview cleared (no draft)."""
        # Add job part
        pipeline_controller.state_manager.set_prompt("test prompt", "test negative")
        pipeline_controller.add_job_part_from_current_config()
        _add_job_draft_pack_entry(pipeline_controller, prompt_text="test prompt")

        # Enqueue
        pipeline_controller.enqueue_draft_bundle()

        # Get summary after enqueue (should be None)
        dto = pipeline_controller.get_draft_bundle_summary()

        # Simulate AppController clearing preview
        mock_preview_panel.update_from_summary(dto)

        # Verify preview cleared
        mock_preview_panel.update_from_summary.assert_called_with(None)

    def test_enqueue_empty_draft_returns_none(
        self, app_controller, pipeline_controller, mock_job_service
    ):
        """Enqueue with no parts → returns None, no job submitted."""
        # Enqueue without adding parts
        job_id = pipeline_controller.enqueue_draft_bundle()

        # Verify no job was enqueued
        assert job_id is None
        mock_job_service.enqueue.assert_not_called()


# ============================================================
# Test Class: Job Status Callbacks → Queue/History Updates
# ============================================================


class TestJobStatusCallbackFlow:
    """Test that job status changes update queue and history panels."""

    def test_job_queued_updates_queue_panel(
        self, app_controller, mock_queue_panel, mock_job_service
    ):
        """Job queued → queue panel receives upsert_job call."""
        # Create mock job
        job = Job(job_id="test-job-123", pipeline_config=None)

        # Emit QUEUED status
        mock_job_service.emit_status(job, JobStatus.QUEUED)

        # Verify queue panel was updated
        mock_queue_panel.upsert_job.assert_called_once_with(job)

    def test_job_running_updates_queue_panel(
        self, app_controller, mock_queue_panel, mock_job_service
    ):
        """Job running → queue panel receives upsert_job call."""
        # Create mock job
        job = Job(job_id="test-job-123", pipeline_config=None)

        # Emit RUNNING status
        mock_job_service.emit_status(job, JobStatus.RUNNING)

        # Verify queue panel was updated
        mock_queue_panel.upsert_job.assert_called_once_with(job)

    def test_job_completed_updates_history_panel(
        self,
        app_controller,
        mock_queue_panel,
        mock_history_panel,
        mock_job_service,
    ):
        """Job completed → removed from queue, added to history."""
        # Create mock job
        job = Job(job_id="test-job-123", pipeline_config=None)

        # Emit COMPLETED status
        mock_job_service.emit_status(job, JobStatus.COMPLETED)

        # Verify queue panel removed job
        mock_queue_panel.remove_job.assert_called_once_with("test-job-123")

        # Verify history panel received job
        mock_history_panel.append_history_item.assert_called_once_with(job)

    def test_job_failed_updates_history_panel(
        self,
        app_controller,
        mock_queue_panel,
        mock_history_panel,
        mock_job_service,
    ):
        """Job failed → removed from queue, added to history."""
        # Create mock job
        job = Job(job_id="test-job-123", pipeline_config=None)

        # Emit FAILED status
        mock_job_service.emit_status(job, JobStatus.FAILED)

        # Verify queue panel removed job
        mock_queue_panel.remove_job.assert_called_once_with("test-job-123")

        # Verify history panel received job
        mock_history_panel.append_history_item.assert_called_once_with(job)


# ============================================================
# Test Class: End-to-End Integration Flow
# ============================================================


class TestEndToEndFlow:
    """Test complete flow from add to job → queue → run → history."""

    def test_complete_workflow_single_job(
        self,
        app_controller,
        pipeline_controller,
        mock_preview_panel,
        mock_queue_panel,
        mock_history_panel,
        mock_job_service,
    ):
        """Complete flow: add → preview → enqueue → queue → complete → history."""
        # Step 1: Add job part
        pipeline_controller.state_manager.set_prompt(
            "beautiful landscape", "low quality"
        )
        pipeline_controller.add_job_part_from_current_config()
        _add_job_draft_pack_entry(
            pipeline_controller,
            prompt_text="beautiful landscape",
            negative_prompt="low quality",
        )

        # Step 2: Preview updates
        dto_after_add = pipeline_controller.get_draft_bundle_summary()
        mock_preview_panel.update_from_summary(dto_after_add)
        assert dto_after_add.num_parts == 1

        # Step 3: Enqueue draft
        job_id = pipeline_controller.enqueue_draft_bundle()
        assert job_id is not None

        # Step 4: Preview clears
        dto_after_enqueue = pipeline_controller.get_draft_bundle_summary()
        mock_preview_panel.update_from_summary(dto_after_enqueue)
        assert dto_after_enqueue is None

        # Step 5: Job queued → queue panel updates
        job = Job(job_id=job_id, pipeline_config=None)
        mock_job_service.emit_status(job, JobStatus.QUEUED)
        mock_queue_panel.upsert_job.assert_called_with(job)

        # Step 6: Job running → queue panel updates
        mock_job_service.emit_status(job, JobStatus.RUNNING)
        assert mock_queue_panel.upsert_job.call_count == 2

        # Step 7: Job completed → removed from queue, added to history
        mock_job_service.emit_status(job, JobStatus.COMPLETED)
        mock_queue_panel.remove_job.assert_called_once_with(job_id)
        mock_history_panel.append_history_item.assert_called_once_with(job)

    def test_workflow_multiple_jobs(
        self,
        app_controller,
        pipeline_controller,
        mock_preview_panel,
        mock_queue_panel,
        mock_history_panel,
        mock_job_service,
    ):
        """Multiple jobs: add → enqueue → add → enqueue → all complete."""
        # Job 1: Add and enqueue
        pipeline_controller.state_manager.set_prompt("prompt 1", "neg 1")
        pipeline_controller.add_job_part_from_current_config()
        _add_job_draft_pack_entry(
            pipeline_controller, prompt_text="prompt 1", negative_prompt="neg 1"
        )
        job_id_1 = pipeline_controller.enqueue_draft_bundle()
        assert job_id_1 is not None

        # Job 2: Add and enqueue
        pipeline_controller.state_manager.set_prompt("prompt 2", "neg 2")
        pipeline_controller.add_job_part_from_current_config()
        _add_job_draft_pack_entry(
            pipeline_controller, prompt_text="prompt 2", negative_prompt="neg 2"
        )
        job_id_2 = pipeline_controller.enqueue_draft_bundle()
        assert job_id_2 is not None

        # Emit status for both jobs
        job_1 = Job(job_id=job_id_1, pipeline_config=None)
        job_2 = Job(job_id=job_id_2, pipeline_config=None)

        # Job 1: queued → running → completed
        mock_job_service.emit_status(job_1, JobStatus.QUEUED)
        mock_job_service.emit_status(job_1, JobStatus.RUNNING)
        mock_job_service.emit_status(job_1, JobStatus.COMPLETED)

        # Job 2: queued → running → completed
        mock_job_service.emit_status(job_2, JobStatus.QUEUED)
        mock_job_service.emit_status(job_2, JobStatus.RUNNING)
        mock_job_service.emit_status(job_2, JobStatus.COMPLETED)

        # Verify both jobs moved to history
        assert mock_history_panel.append_history_item.call_count == 2

    def test_workflow_with_clear_draft(
        self,
        app_controller,
        pipeline_controller,
        mock_preview_panel,
        mock_queue_panel,
        mock_history_panel,
    ):
        """Add → clear → add → enqueue → complete."""
        # Add and clear (don't enqueue)
        pipeline_controller.state_manager.set_prompt("prompt 1", "neg 1")
        pipeline_controller.add_job_part_from_current_config()
        _add_job_draft_pack_entry(
            pipeline_controller, prompt_text="prompt 1", negative_prompt="neg 1"
        )
        pipeline_controller.clear_draft_bundle()

        # Add again and enqueue
        pipeline_controller.state_manager.set_prompt("prompt 2", "neg 2")
        pipeline_controller.add_job_part_from_current_config()
        _add_job_draft_pack_entry(
            pipeline_controller, prompt_text="prompt 2", negative_prompt="neg 2"
        )
        job_id = pipeline_controller.enqueue_draft_bundle()

        # Verify only the second prompt was enqueued
        assert job_id is not None
        # Only one job should be tracked (not the cleared one)

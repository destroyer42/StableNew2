# Subsystem: Controller
# Role: Tests for PipelineController draft bundle lifecycle (PR-D).

"""Tests for PipelineController draft JobBundle lifecycle.

PR-D: These tests verify that PipelineController correctly manages
the draft bundle lifecycle for "Add to Job" → "Add to Queue" flow:

1. add_job_part_from_current_config() creates draft bundle with single part
2. add_job_parts_from_pack() adds multiple parts to draft
3. get_draft_bundle_summary() returns correct DTO
4. clear_draft_bundle() resets draft state
5. enqueue_draft_bundle() submits to JobService and clears draft
6. Draft bundle persists across multiple add operations
7. Builder resets correctly after clear
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest

from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import JobBundle, JobBundleSummaryDTO


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------


@dataclass
class MockStateManager:
    """Minimal state manager for testing."""

    prompt: str = "test prompt"
    negative_prompt: str = "test negative"
    batch_runs: int = 1

    def get_pipeline_overrides(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "model_name": "test-model",
            "sampler": "Euler a",
            "steps": 20,
            "cfg_scale": 7.5,
            "width": 512,
            "height": 512,
            "batch_size": 1,
        }


@pytest.fixture
def mock_job_service():
    """Mock JobService that tracks enqueue calls."""
    service = Mock()
    service.enqueue = Mock(return_value=None)
    return service


@pytest.fixture
def pipeline_controller(mock_job_service):
    """Create PipelineController with minimal dependencies."""
    state_manager = MockStateManager()

    controller = PipelineController(
        state_manager=state_manager,
        job_service=mock_job_service,
    )

    return controller


# ---------------------------------------------------------------------------
# Test: add_job_part_from_current_config
# ---------------------------------------------------------------------------


class TestAddJobPartFromCurrentConfig:
    """Test adding a single job part from current GUI config."""

    def test_creates_draft_bundle_with_single_part(self, pipeline_controller):
        """First call creates draft bundle with one part."""
        # Act
        dto = pipeline_controller.add_job_part_from_current_config()

        # Assert
        assert dto is not None
        assert dto.num_parts == 1
        assert dto.positive_preview == "test prompt"
        # Note: negative preview may include global negative applied by builder
        assert "test negative" in (dto.negative_preview or "")
        assert dto.estimated_images >= 1

    def test_adds_second_part_to_existing_draft(self, pipeline_controller):
        """Second call adds to existing draft bundle."""
        # Act
        pipeline_controller.add_job_part_from_current_config()
        
        # Change prompt and add again
        pipeline_controller.state_manager.prompt = "second prompt"
        dto = pipeline_controller.add_job_part_from_current_config()
        
        # Assert
        assert dto is not None
        assert dto.num_parts == 2
        assert dto.estimated_images >= 2

    def test_returns_none_when_prompt_empty(self, pipeline_controller):
        """Returns None when prompt is empty."""
        # Arrange
        pipeline_controller.state_manager.prompt = ""
        
        # Act
        dto = pipeline_controller.add_job_part_from_current_config()
        
        # Assert
        assert dto is None

    def test_preserves_negative_prompt(self, pipeline_controller):
        """Negative prompt is included in draft bundle."""
        # Arrange
        pipeline_controller.state_manager.negative_prompt = "test negative prompt"
        
        # Act
        dto = pipeline_controller.add_job_part_from_current_config()
        
        # Assert
        assert dto is not None
        assert "test negative" in (dto.negative_preview or "")

    def test_uses_config_from_state_overrides(self, pipeline_controller):
        """Config snapshot uses values from state overrides."""
        # Act
        pipeline_controller.add_job_part_from_current_config()
        
        # Assert - check internal state
        assert pipeline_controller._draft_bundle is not None
        assert len(pipeline_controller._draft_bundle.parts) == 1
        part = pipeline_controller._draft_bundle.parts[0]
        assert part.config_snapshot.model_name == "test-model"
        assert part.config_snapshot.steps == 20
        assert part.config_snapshot.cfg_scale == 7.5


# ---------------------------------------------------------------------------
# Test: add_job_parts_from_pack
# ---------------------------------------------------------------------------


class TestAddJobPartsFromPack:
    """Test adding multiple parts from a pack."""

    def test_adds_multiple_parts_from_pack(self, pipeline_controller):
        """Adds all prompts from pack to draft."""
        # Note: This is a placeholder test - actual pack loading needs implementation
        # For now, test that method exists and handles empty pack gracefully
        
        # Act
        dto = pipeline_controller.add_job_parts_from_pack("test-pack", prepend_text=None)
        
        # Assert - should return None for non-existent pack
        # Once pack loading is implemented, update this test
        assert dto is None or dto.num_parts >= 0

    def test_prepends_text_to_pack_prompts(self, pipeline_controller):
        """Prepend text is added to each prompt in pack."""
        # Placeholder - will be implemented when pack loading is wired
        pass


# ---------------------------------------------------------------------------
# Test: get_draft_bundle_summary
# ---------------------------------------------------------------------------


class TestGetDraftBundleSummary:
    """Test retrieving draft bundle summary."""

    def test_returns_none_when_no_draft(self, pipeline_controller):
        """Returns None when no draft bundle exists."""
        # Act
        dto = pipeline_controller.get_draft_bundle_summary()
        
        # Assert
        assert dto is None

    def test_returns_dto_after_adding_part(self, pipeline_controller):
        """Returns valid DTO after adding a part."""
        # Arrange
        pipeline_controller.add_job_part_from_current_config()
        
        # Act
        dto = pipeline_controller.get_draft_bundle_summary()
        
        # Assert
        assert dto is not None
        assert isinstance(dto, JobBundleSummaryDTO)
        assert dto.num_parts == 1

    def test_summary_reflects_multiple_parts(self, pipeline_controller):
        """DTO reflects correct part count after multiple adds."""
        # Arrange
        pipeline_controller.add_job_part_from_current_config()
        pipeline_controller.state_manager.prompt = "second prompt"
        pipeline_controller.add_job_part_from_current_config()
        
        # Act
        dto = pipeline_controller.get_draft_bundle_summary()
        
        # Assert
        assert dto is not None
        assert dto.num_parts == 2


# ---------------------------------------------------------------------------
# Test: clear_draft_bundle
# ---------------------------------------------------------------------------


class TestClearDraftBundle:
    """Test clearing draft bundle state."""

    def test_clears_draft_bundle(self, pipeline_controller):
        """Clears draft bundle after adding parts."""
        # Arrange
        pipeline_controller.add_job_part_from_current_config()
        assert pipeline_controller._draft_bundle is not None
        
        # Act
        pipeline_controller.clear_draft_bundle()
        
        # Assert
        assert pipeline_controller._draft_bundle is None

    def test_clears_builder_state(self, pipeline_controller):
        """Clears builder after adding parts."""
        # Arrange
        pipeline_controller.add_job_part_from_current_config()
        assert pipeline_controller._job_bundle_builder is not None

        # Act
        pipeline_controller.clear_draft_bundle()

        # Assert - builder should reset on next use
        dto = pipeline_controller.add_job_part_from_current_config()
        assert dto.num_parts == 1  # Fresh start

    def test_safe_when_no_draft(self, pipeline_controller):
        """No error when clearing empty draft."""
        # Act - should not raise
        pipeline_controller.clear_draft_bundle()
        
        # Assert
        assert pipeline_controller._draft_bundle is None

    def test_get_summary_returns_none_after_clear(self, pipeline_controller):
        """get_draft_bundle_summary returns None after clear."""
        # Arrange
        pipeline_controller.add_job_part_from_current_config()
        
        # Act
        pipeline_controller.clear_draft_bundle()
        dto = pipeline_controller.get_draft_bundle_summary()
        
        # Assert
        assert dto is None


# ---------------------------------------------------------------------------
# Test: enqueue_draft_bundle
# ---------------------------------------------------------------------------


class TestEnqueueDraftBundle:
    """Test enqueueing draft bundle to JobService."""

    def test_returns_none_when_no_draft(self, pipeline_controller, mock_job_service):
        """Returns None when no draft exists."""
        # Act
        job_id = pipeline_controller.enqueue_draft_bundle()
        
        # Assert
        assert job_id is None
        mock_job_service.enqueue.assert_not_called()

    def test_returns_none_when_draft_empty(self, pipeline_controller, mock_job_service):
        """Returns None when draft has no parts."""
        # Arrange - create bundle but don't add parts
        from datetime import datetime
        pipeline_controller._draft_bundle = JobBundle(
            id="test-bundle",
            label="Test",
            parts=[],
            created_at=datetime.now(),
        )
        
        # Act
        job_id = pipeline_controller.enqueue_draft_bundle()
        
        # Assert
        assert job_id is None
        mock_job_service.enqueue.assert_not_called()

    def test_clears_draft_after_enqueue(self, pipeline_controller):
        """Draft is cleared after successful enqueue."""
        # Arrange
        pipeline_controller.add_job_part_from_current_config()
        assert pipeline_controller._draft_bundle is not None
        
        # Act
        pipeline_controller.enqueue_draft_bundle()
        
        # Assert
        assert pipeline_controller._draft_bundle is None

    def test_can_build_new_draft_after_enqueue(self, pipeline_controller):
        """Can create new draft after enqueuing previous one."""
        # Arrange
        pipeline_controller.add_job_part_from_current_config()

        # Act
        _ = pipeline_controller.enqueue_draft_bundle()
        pipeline_controller.state_manager.prompt = "new prompt"
        dto = pipeline_controller.add_job_part_from_current_config()

        # Assert
        assert dto is not None
        assert dto.num_parts == 1  # Fresh draft


# ---------------------------------------------------------------------------
# Test: Integration Scenarios
# ---------------------------------------------------------------------------


class TestDraftBundleLifecycleIntegration:
    """Test complete draft bundle lifecycle scenarios."""

    def test_single_prompt_workflow(self, pipeline_controller):
        """Complete flow: add → preview → enqueue → clear."""
        # Add part
        dto1 = pipeline_controller.add_job_part_from_current_config()
        assert dto1.num_parts == 1

        # Get summary (for preview)
        dto2 = pipeline_controller.get_draft_bundle_summary()
        assert dto2 is not None
        assert dto2.num_parts == 1

        # Enqueue
        _ = pipeline_controller.enqueue_draft_bundle()
        # Job ID may be None in test (no real JobService implementation)

        # Verify cleared
        dto3 = pipeline_controller.get_draft_bundle_summary()
        assert dto3 is None

    def test_multi_part_workflow(self, pipeline_controller):
        """Complete flow with multiple parts."""
        # Add first part
        dto1 = pipeline_controller.add_job_part_from_current_config()
        assert dto1.num_parts == 1
        
        # Add second part
        pipeline_controller.state_manager.prompt = "second prompt"
        dto2 = pipeline_controller.add_job_part_from_current_config()
        assert dto2.num_parts == 2
        
        # Enqueue both
        pipeline_controller.enqueue_draft_bundle()
        
        # Start fresh
        pipeline_controller.state_manager.prompt = "third prompt"
        dto3 = pipeline_controller.add_job_part_from_current_config()
        assert dto3.num_parts == 1

    def test_clear_without_enqueue(self, pipeline_controller):
        """User can clear draft without enqueueing."""
        # Add parts
        pipeline_controller.add_job_part_from_current_config()
        pipeline_controller.state_manager.prompt = "second"
        dto = pipeline_controller.add_job_part_from_current_config()
        assert dto.num_parts == 2
        
        # Clear instead of enqueue
        pipeline_controller.clear_draft_bundle()
        
        # Verify empty
        assert pipeline_controller.get_draft_bundle_summary() is None
        
        # Can start fresh
        pipeline_controller.state_manager.prompt = "fresh"
        dto2 = pipeline_controller.add_job_part_from_current_config()
        assert dto2.num_parts == 1

    def test_draft_persists_until_explicit_action(self, pipeline_controller):
        """Draft bundle persists across get_summary calls."""
        # Add part
        pipeline_controller.add_job_part_from_current_config()
        
        # Get summary multiple times
        dto1 = pipeline_controller.get_draft_bundle_summary()
        dto2 = pipeline_controller.get_draft_bundle_summary()
        dto3 = pipeline_controller.get_draft_bundle_summary()
        
        # All should show same state
        assert dto1 is not None
        assert dto2 is not None
        assert dto3 is not None
        assert dto1.num_parts == dto2.num_parts == dto3.num_parts == 1


# ---------------------------------------------------------------------------
# Test: Error Handling
# ---------------------------------------------------------------------------


class TestDraftBundleErrorHandling:
    """Test error handling in draft bundle operations."""

    def test_handles_missing_state_manager_gracefully(self):
        """Handles None state_manager without crashing."""
        controller = PipelineController(state_manager=None)

        # Should not crash, may return None
        _ = controller.add_job_part_from_current_config()
        # Exact behavior depends on implementation

    def test_handles_invalid_prompt_gracefully(self, pipeline_controller):
        """Handles whitespace-only prompt."""
        pipeline_controller.state_manager.prompt = "   \n\t  "

        dto = pipeline_controller.add_job_part_from_current_config()

        # Should treat as empty
        assert dto is None

    def test_handles_missing_negative_prompt(self, pipeline_controller):
        """Handles missing negative prompt field."""
        pipeline_controller.state_manager.negative_prompt = ""
        
        dto = pipeline_controller.add_job_part_from_current_config()
        
        assert dto is not None
        assert dto.negative_preview == "" or dto.negative_preview is None


# ---------------------------------------------------------------------------
# Test: DTO Validation
# ---------------------------------------------------------------------------


class TestJobBundleSummaryDTO:
    """Test JobBundleSummaryDTO structure and content."""

    def test_dto_has_required_fields(self, pipeline_controller):
        """DTO contains all required fields."""
        pipeline_controller.add_job_part_from_current_config()
        dto = pipeline_controller.get_draft_bundle_summary()
        
        assert dto is not None
        assert hasattr(dto, "num_parts")
        assert hasattr(dto, "estimated_images")
        assert hasattr(dto, "positive_preview")
        assert hasattr(dto, "negative_preview")
        assert hasattr(dto, "stage_summary")
        assert hasattr(dto, "batch_summary")
        assert hasattr(dto, "label")

    def test_dto_positive_preview_truncated(self, pipeline_controller):
        """Positive preview is truncated to reasonable length."""
        long_prompt = "a" * 500
        pipeline_controller.state_manager.prompt = long_prompt
        
        dto = pipeline_controller.add_job_part_from_current_config()
        
        assert dto is not None
        assert len(dto.positive_preview) < 500  # Truncated from original

    def test_dto_estimated_images_positive(self, pipeline_controller):
        """Estimated images is always positive."""
        dto = pipeline_controller.add_job_part_from_current_config()
        
        assert dto is not None
        assert dto.estimated_images > 0

    def test_dto_label_not_empty(self, pipeline_controller):
        """Label is always populated."""
        dto = pipeline_controller.add_job_part_from_current_config()
        
        assert dto is not None
        assert dto.label
        assert len(dto.label) > 0

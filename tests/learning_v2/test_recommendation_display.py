"""Tests for recommendation display formatting.

PR-LEARN-008: Live Recommendation Display
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock


@dataclass
class MockRecommendation:
    parameter_name: str
    recommended_value: any
    confidence_score: float
    sample_count: int
    mean_rating: float


def test_update_recommendations_formats_dataclass():
    """Verify dataclass recommendations are formatted correctly."""
    from src.gui.views.learning_review_panel import LearningReviewPanel

    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.recommendations_text = MagicMock()
    panel.recommendations_text.config = MagicMock()
    panel.recommendations_text.delete = MagicMock()
    panel.recommendations_text.insert = MagicMock()
    panel.apply_button = MagicMock()  # Mock the apply button

    recs = [
        MockRecommendation(
            parameter_name="CFG Scale",
            recommended_value=7.5,
            confidence_score=0.85,
            sample_count=12,
            mean_rating=4.2,
        )
    ]

    panel.update_recommendations(recs)

    # Should have called insert with formatted text
    panel.recommendations_text.insert.assert_called()
    call_args = str(panel.recommendations_text.insert.call_args_list)
    assert "CFG Scale" in call_args


def test_update_recommendations_handles_empty():
    """Verify empty recommendations show helpful message."""
    from src.gui.views.learning_review_panel import LearningReviewPanel

    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.recommendations_text = MagicMock()
    panel.recommendations_text.config = MagicMock()
    panel.recommendations_text.delete = MagicMock()
    panel.recommendations_text.insert = MagicMock()

    panel.update_recommendations(None)

    call_args = str(panel.recommendations_text.insert.call_args_list)
    assert "No recommendations" in call_args or "available" in call_args


def test_update_recommendations_handles_dict():
    """Verify dict-format recommendations are formatted correctly."""
    from src.gui.views.learning_review_panel import LearningReviewPanel

    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.recommendations_text = MagicMock()
    panel.recommendations_text.config = MagicMock()
    panel.recommendations_text.delete = MagicMock()
    panel.recommendations_text.insert = MagicMock()
    panel.apply_button = MagicMock()  # Mock the apply button

    recs = [
        {
            "parameter": "Steps",
            "value": 30,
            "confidence": 0.72,
            "samples": 8,
            "mean_rating": 3.8,
        }
    ]

    panel.update_recommendations(recs)

    call_args = str(panel.recommendations_text.insert.call_args_list)
    assert "Steps" in call_args


def test_update_recommendations_handles_recommendation_set():
    """Verify RecommendationSet format with .recommendations attribute."""
    from src.gui.views.learning_review_panel import LearningReviewPanel

    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.recommendations_text = MagicMock()
    panel.recommendations_text.config = MagicMock()
    panel.recommendations_text.delete = MagicMock()
    panel.recommendations_text.insert = MagicMock()
    panel.apply_button = MagicMock()  # Mock the apply button

    # Mock a RecommendationSet-like object
    mock_rec_set = MagicMock()
    mock_rec_set.recommendations = [
        MockRecommendation(
            parameter_name="Sampler",
            recommended_value="DPM++ 2M Karras",
            confidence_score=0.9,
            sample_count=15,
            mean_rating=4.5,
        )
    ]

    panel.update_recommendations(mock_rec_set)

    call_args = str(panel.recommendations_text.insert.call_args_list)
    assert "Sampler" in call_args


def test_update_recommendations_includes_rationale_when_present():
    """Verify compact rationale/context are shown when available."""
    from src.gui.views.learning_review_panel import LearningReviewPanel

    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.recommendations_text = MagicMock()
    panel.recommendations_text.config = MagicMock()
    panel.recommendations_text.delete = MagicMock()
    panel.recommendations_text.insert = MagicMock()
    panel.apply_button = MagicMock()

    recs = [
        {
            "parameter": "CFG Scale",
            "value": 8.0,
            "confidence": 0.82,
            "samples": 9,
            "mean_rating": 4.3,
            "rationale": "samples=9; stddev=0.4; context=stage-match",
            "context": "txt2img|modelA|default|medium",
        }
    ]

    panel.update_recommendations(recs)
    call_args = str(panel.recommendations_text.insert.call_args_list)
    assert "Because:" in call_args
    assert "context=" in call_args


def test_update_recommendations_empty_list():
    """Verify empty list shows insufficient data message."""
    from src.gui.views.learning_review_panel import LearningReviewPanel

    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.recommendations_text = MagicMock()
    panel.recommendations_text.config = MagicMock()
    panel.recommendations_text.delete = MagicMock()
    panel.recommendations_text.insert = MagicMock()

    panel.update_recommendations([])

    call_args = str(panel.recommendations_text.insert.call_args_list)
    # Empty list is treated like None, showing 'No recommendations'
    assert "No recommendations" in call_args or "Rate more images" in call_args


def test_rating_triggers_recommendation_refresh():
    """Verify that recording a rating triggers recommendation refresh."""
    import os
    import tempfile
    from unittest.mock import patch

    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
    from src.learning.learning_record import LearningRecordWriter

    # Create temp directory for records
    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = os.path.join(tmpdir, "test_records.jsonl")

        # Create state and experiment
        state = LearningState()
        state.current_experiment = LearningExperiment(
            name="test_exp",
            description="Test",
            stage="txt2img",
            variable_under_test="CFG Scale",
            values=[5.0, 7.0, 9.0],
            prompt_text="test prompt",
        )

        # Create variant
        variant = LearningVariant(param_value=7.0)
        variant.image_refs = ["test_image.png"]
        state.plan = [variant]

        # Create record writer
        writer = LearningRecordWriter(records_path)

        # Create controller with mocked refresh method
        controller = LearningController(
            learning_state=state,
            learning_record_writer=writer,
            pipeline_controller=object(),
        )

        # Mock the refresh_recommendations method
        with patch.object(controller, 'refresh_recommendations') as mock_refresh:
            with patch.object(controller, '_update_variant_ratings') as mock_update:
                # Record rating
                controller.record_rating("test_image.png", 4, "Test note")

                # Verify refresh was called
                mock_refresh.assert_called_once()
                mock_update.assert_called_once()

"""Tests for applying recommendations to pipeline.

PR-LEARN-009: Apply Recommendations to Pipeline
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from unittest.mock import MagicMock

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState


@dataclass
class MockRecommendation:
    parameter_name: str
    recommended_value: any
    confidence_score: float = 0.8
    sample_count: int = 10
    mean_rating: float = 4.0


def test_apply_recommendation_updates_cfg():
    """Verify CFG scale recommendation is applied."""
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    # Mock stage cards
    mock_txt2img_card = MagicMock()
    mock_txt2img_card.cfg_var = MagicMock()
    mock_txt2img_card.cfg_var.set = MagicMock()
    
    mock_stage_cards = MagicMock()
    mock_stage_cards.txt2img_card = mock_txt2img_card
    
    result = controller._apply_single_recommendation(mock_stage_cards, "CFG Scale", 8.5)
    
    assert result is True
    mock_txt2img_card.cfg_var.set.assert_called_with(8.5)


def test_apply_recommendation_updates_steps():
    """Verify Steps recommendation is applied."""
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    mock_txt2img_card = MagicMock()
    mock_txt2img_card.steps_var = MagicMock()
    
    mock_stage_cards = MagicMock()
    mock_stage_cards.txt2img_card = mock_txt2img_card
    
    result = controller._apply_single_recommendation(mock_stage_cards, "Steps", 30)
    
    assert result is True
    mock_txt2img_card.steps_var.set.assert_called_with(30)


def test_apply_unknown_parameter_returns_false():
    """Verify unknown parameters are handled gracefully."""
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    mock_stage_cards = MagicMock()
    
    result = controller._apply_single_recommendation(mock_stage_cards, "Unknown Param", 42)
    
    assert result is False


def test_apply_recommendations_to_pipeline_success():
    """Verify applying multiple recommendations."""
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    # Mock pipeline controller with stage cards
    mock_txt2img_card = MagicMock()
    mock_txt2img_card.cfg_var = MagicMock()
    mock_txt2img_card.steps_var = MagicMock()
    
    mock_stage_cards = MagicMock()
    mock_stage_cards.txt2img_card = mock_txt2img_card
    
    mock_pipeline_controller = MagicMock()
    mock_pipeline_controller.stage_cards_panel = mock_stage_cards
    
    controller.pipeline_controller = mock_pipeline_controller
    
    # Apply recommendations
    recs = [
        MockRecommendation(parameter_name="CFG Scale", recommended_value=7.5),
        MockRecommendation(parameter_name="Steps", recommended_value=30),
    ]
    
    result = controller.apply_recommendations_to_pipeline(recs)
    
    assert result is True
    mock_txt2img_card.cfg_var.set.assert_called_with(7.5)
    mock_txt2img_card.steps_var.set.assert_called_with(30)


def test_apply_recommendations_no_pipeline_controller():
    """Verify failure when pipeline controller is missing."""
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    recs = [MockRecommendation(parameter_name="CFG Scale", recommended_value=7.5)]
    
    result = controller.apply_recommendations_to_pipeline(recs)
    
    assert result is False


def test_extract_rec_list_from_dataclass():
    """Verify extraction of recommendation list from dataclass."""
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    rec = MockRecommendation(parameter_name="CFG", recommended_value=7.0)
    rec_list = controller._extract_rec_list([rec])
    
    assert len(rec_list) == 1
    assert rec_list[0].parameter_name == "CFG"


def test_extract_rec_list_from_recommendation_set():
    """Verify extraction from object with .recommendations attribute."""
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    mock_rec_set = MagicMock()
    mock_rec_set.recommendations = [
        MockRecommendation(parameter_name="Steps", recommended_value=25)
    ]
    
    rec_list = controller._extract_rec_list(mock_rec_set)
    
    assert len(rec_list) == 1
    assert rec_list[0].parameter_name == "Steps"


def test_apply_button_enabled_with_recommendations():
    """Verify apply button is enabled when recommendations exist."""
    from src.gui.views.learning_review_panel import LearningReviewPanel
    
    root = tk.Tk()
    try:
        panel = LearningReviewPanel(root)
        
        # Initially disabled
        assert str(panel.apply_button['state']) == 'disabled'
        
        # Update with recommendations
        recs = [MockRecommendation(parameter_name="CFG", recommended_value=7.0)]
        panel.update_recommendations(recs)
        
        # Should be enabled
        assert str(panel.apply_button['state']) != 'disabled'
    finally:
        root.destroy()


def test_apply_button_disabled_without_recommendations():
    """Verify apply button is disabled when no recommendations."""
    from src.gui.views.learning_review_panel import LearningReviewPanel
    
    root = tk.Tk()
    try:
        panel = LearningReviewPanel(root)
        
        # Update with no recommendations
        panel.update_recommendations(None)
        
        # Should be disabled
        assert str(panel.apply_button['state']) == 'disabled'
    finally:
        root.destroy()

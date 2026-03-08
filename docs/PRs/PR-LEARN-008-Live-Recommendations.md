# PR-LEARN-008: Live Recommendation Display

**Status:** DRAFT  
**Priority:** P2 (MEDIUM)  
**Phase:** 4 (Recommendations & Analytics)  
**Depends on:** PR-LEARN-007  
**Estimated Effort:** 2-3 hours

---

## 1. Problem Statement

The RecommendationEngine exists and works, but its output isn't displayed to users:

1. **Recommendations panel is empty** — `update_recommendations()` is called but display logic incomplete
2. **No refresh trigger** — Recommendations don't update after new ratings
3. **No formatting** — Raw data isn't user-friendly

---

## 2. Success Criteria

After this PR:
- [ ] Recommendations panel shows parameter suggestions
- [ ] Recommendations update automatically after rating submission
- [ ] Display includes confidence scores and sample counts
- [ ] Users can see which settings performed best

---

## 3. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/gui/views/learning_review_panel.py` | MODIFY | Format and display recommendations |
| `src/gui/controllers/learning_controller.py` | MODIFY | Trigger recommendation refresh |
| `tests/learning_v2/test_recommendation_display.py` | CREATE | Test display logic |

---

## 4. Implementation Steps

### Step 1: Complete update_recommendations() in LearningReviewPanel

**File:** `src/gui/views/learning_review_panel.py`

**Replace stub implementation:**
```python
def update_recommendations(self, recommendations: Any) -> None:
    """Update the recommendations display with new data."""
    self.recommendations_text.config(state="normal")
    self.recommendations_text.delete(1.0, tk.END)
    
    if not recommendations:
        self.recommendations_text.insert(tk.END, "No recommendations available yet.\n")
        self.recommendations_text.insert(tk.END, "\nRate more images to get personalized suggestions.")
        self.recommendations_text.config(state="disabled")
        return
    
    # Format recommendations for display
    lines = []
    
    # Check if it's a RecommendationSet or list of recommendations
    if hasattr(recommendations, "recommendations"):
        rec_list = recommendations.recommendations
    elif isinstance(recommendations, list):
        rec_list = recommendations
    else:
        rec_list = []
    
    if not rec_list:
        self.recommendations_text.insert(tk.END, "Insufficient data for recommendations.\n")
        self.recommendations_text.insert(tk.END, "\nRate at least 3 images to generate suggestions.")
        self.recommendations_text.config(state="disabled")
        return
    
    lines.append("🎯 Recommended Settings:\n")
    lines.append("-" * 30 + "\n\n")
    
    for rec in rec_list:
        # Handle both dataclass and dict formats
        if hasattr(rec, "parameter_name"):
            param = rec.parameter_name
            value = rec.recommended_value
            confidence = rec.confidence_score
            samples = rec.sample_count
            mean_rating = rec.mean_rating
        elif isinstance(rec, dict):
            param = rec.get("parameter", "Unknown")
            value = rec.get("value", "?")
            confidence = rec.get("confidence", 0)
            samples = rec.get("samples", 0)
            mean_rating = rec.get("mean_rating", 0)
        else:
            continue
        
        # Format confidence as percentage
        conf_pct = f"{confidence * 100:.0f}%"
        
        # Format mean rating as stars
        stars = "⭐" * int(round(mean_rating))
        
        lines.append(f"📊 {param}\n")
        lines.append(f"   Best Value: {value}\n")
        lines.append(f"   Avg Rating: {stars} ({mean_rating:.1f})\n")
        lines.append(f"   Confidence: {conf_pct} ({samples} samples)\n\n")
    
    self.recommendations_text.insert(tk.END, "".join(lines))
    self.recommendations_text.config(state="disabled")
```

### Step 2: Trigger Refresh After Rating in LearningController

**File:** `src/gui/controllers/learning_controller.py`

**Add at end of `record_rating()` method:**
```python
def record_rating(self, image_ref: str, rating: int, notes: str = "") -> None:
    # ... existing rating logic ...
    
    # Write the record
    self._learning_record_writer.append_record(record)
    
    # Update rating cache
    self._rating_cache[image_ref] = rating
    
    # Refresh recommendations with new data
    self.refresh_recommendations()
    
    # Update plan table with new average rating
    self._update_variant_ratings()


def _update_variant_ratings(self) -> None:
    """Update all variant rows with their average ratings."""
    if not self._learning_record_writer or not self.learning_state.current_experiment:
        return
    
    experiment_id = self.learning_state.current_experiment.name
    
    for i, variant in enumerate(self.learning_state.plan):
        avg = self._learning_record_writer.get_average_rating_for_variant(
            experiment_id, 
            variant.param_value
        )
        
        if self._plan_table and hasattr(self._plan_table, "update_row_rating"):
            self._plan_table.update_row_rating(i, avg)
```

### Step 3: Create Tests

**File:** `tests/learning_v2/test_recommendation_display.py`

```python
"""Tests for recommendation display formatting."""
from __future__ import annotations

import pytest
from dataclasses import dataclass


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
    from unittest.mock import MagicMock
    
    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.recommendations_text = MagicMock()
    panel.recommendations_text.config = MagicMock()
    panel.recommendations_text.delete = MagicMock()
    panel.recommendations_text.insert = MagicMock()
    
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
    call_args = str(panel.recommendations_text.insert.call_args)
    assert "CFG Scale" in call_args


def test_update_recommendations_handles_empty():
    """Verify empty recommendations show helpful message."""
    from src.gui.views.learning_review_panel import LearningReviewPanel
    from unittest.mock import MagicMock
    
    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.recommendations_text = MagicMock()
    panel.recommendations_text.config = MagicMock()
    panel.recommendations_text.delete = MagicMock()
    panel.recommendations_text.insert = MagicMock()
    
    panel.update_recommendations(None)
    
    call_args = str(panel.recommendations_text.insert.call_args)
    assert "No recommendations" in call_args or "available" in call_args


def test_update_recommendations_handles_dict():
    """Verify dict-format recommendations are formatted correctly."""
    from src.gui.views.learning_review_panel import LearningReviewPanel
    from unittest.mock import MagicMock
    
    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.recommendations_text = MagicMock()
    panel.recommendations_text.config = MagicMock()
    panel.recommendations_text.delete = MagicMock()
    panel.recommendations_text.insert = MagicMock()
    
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
    
    call_args = str(panel.recommendations_text.insert.call_args)
    assert "Steps" in call_args
```

---

## 5. Verification

### 5.1 Manual Verification

1. Run an experiment and rate several images
2. Verify recommendations panel updates after each rating
3. Check that recommendations show parameter name, value, confidence
4. Verify variant rows show average rating

### 5.2 Automated Verification

```bash
pytest tests/learning_v2/test_recommendation_display.py -v
```

---

## 6. Related PRs

- **Depends on:** PR-LEARN-007
- **Enables:** PR-LEARN-009 (Apply Recommendations to Pipeline)

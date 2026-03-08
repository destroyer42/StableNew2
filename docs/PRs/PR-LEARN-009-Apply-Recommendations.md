# PR-LEARN-009: Apply Recommendations to Pipeline

**Status:** DRAFT  
**Priority:** P3 (LOW)  
**Phase:** 4 (Recommendations & Analytics)  
**Depends on:** PR-LEARN-008  
**Estimated Effort:** 3-4 hours

---

## 1. Problem Statement

Users can see recommendations but cannot easily apply them:

1. **No "Apply" action** — Must manually enter values in Pipeline tab
2. **No confirmation flow** — Users can't preview what will change
3. **No integration with stage cards** — Recommendations disconnected from controls

---

## 2. Success Criteria

After this PR:
- [ ] "Apply to Pipeline" button in recommendations panel
- [ ] Preview dialog shows proposed changes
- [ ] Clicking apply updates relevant stage card controls
- [ ] Changes reflected immediately in Pipeline tab

---

## 3. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/gui/views/learning_review_panel.py` | MODIFY | Add apply button |
| `src/gui/controllers/learning_controller.py` | MODIFY | Add apply_recommendations() |
| `src/gui/views/stage_cards_panel.py` | MODIFY | Add update_from_recommendations() |
| `tests/learning_v2/test_apply_recommendations.py` | CREATE | Test application flow |

---

## 4. Implementation Steps

### Step 1: Add Apply Button to LearningReviewPanel

**File:** `src/gui/views/learning_review_panel.py`

**In `__init__`, after recommendations_text:**
```python
# Apply recommendations button
self.apply_button = ttk.Button(
    self.recommendations_frame,
    text="Apply to Pipeline",
    command=self._on_apply_recommendations,
    state="disabled",
)
self.apply_button.pack(pady=(5, 0))


def _on_apply_recommendations(self) -> None:
    """Handle apply recommendations button click."""
    # Get controller
    controller = self._get_learning_controller()
    if not controller:
        return
    
    # Get current recommendations
    recs = getattr(controller, "get_recommendations_for_current_prompt", None)
    if not callable(recs):
        return
    
    recommendations = recs()
    if not recommendations:
        return
    
    # Show confirmation dialog
    if self._confirm_apply(recommendations):
        apply_fn = getattr(controller, "apply_recommendations_to_pipeline", None)
        if callable(apply_fn):
            success = apply_fn(recommendations)
            if success:
                from tkinter import messagebox
                messagebox.showinfo(
                    "Applied",
                    "Recommendations applied to Pipeline settings."
                )


def _confirm_apply(self, recommendations: Any) -> bool:
    """Show confirmation dialog with proposed changes."""
    from tkinter import messagebox
    
    # Format changes for display
    changes = []
    rec_list = self._extract_rec_list(recommendations)
    
    for rec in rec_list:
        if hasattr(rec, "parameter_name"):
            param = rec.parameter_name
            value = rec.recommended_value
        elif isinstance(rec, dict):
            param = rec.get("parameter", "?")
            value = rec.get("value", "?")
        else:
            continue
        
        changes.append(f"  • {param} → {value}")
    
    if not changes:
        return False
    
    message = "Apply these settings to Pipeline?\n\n" + "\n".join(changes)
    return messagebox.askyesno("Confirm Apply", message)


def _extract_rec_list(self, recommendations: Any) -> list:
    """Extract list of recommendations from various formats."""
    if hasattr(recommendations, "recommendations"):
        return recommendations.recommendations
    elif isinstance(recommendations, list):
        return recommendations
    return []


def _get_learning_controller(self):
    """Get the learning controller from parent chain."""
    try:
        if hasattr(self.master, "learning_controller"):
            return self.master.learning_controller
    except Exception:
        pass
    return None
```

**Enable button when recommendations available:**
```python
def update_recommendations(self, recommendations: Any) -> None:
    # ... existing code ...
    
    # Enable/disable apply button based on recommendations
    if rec_list:
        self.apply_button.config(state="normal")
    else:
        self.apply_button.config(state="disabled")
```

### Step 2: Add apply_recommendations_to_pipeline() to LearningController

**File:** `src/gui/controllers/learning_controller.py`

```python
def apply_recommendations_to_pipeline(self, recommendations: Any) -> bool:
    """Apply recommendations to the pipeline stage cards.
    
    Returns True if successful, False otherwise.
    """
    if not self.pipeline_controller:
        return False
    
    # Get stage cards panel
    stage_cards = getattr(self.pipeline_controller, "stage_cards_panel", None)
    if not stage_cards:
        # Try via app_state or other paths
        stage_cards = self._find_stage_cards_panel()
    
    if not stage_cards:
        return False
    
    # Extract recommendations
    rec_list = self._extract_rec_list(recommendations)
    
    applied = 0
    for rec in rec_list:
        if hasattr(rec, "parameter_name"):
            param = rec.parameter_name
            value = rec.recommended_value
        elif isinstance(rec, dict):
            param = rec.get("parameter", "")
            value = rec.get("value")
        else:
            continue
        
        if self._apply_single_recommendation(stage_cards, param, value):
            applied += 1
    
    return applied > 0


def _apply_single_recommendation(
    self, 
    stage_cards: Any, 
    param: str, 
    value: Any
) -> bool:
    """Apply a single recommendation to stage cards."""
    param_lower = param.lower().replace(" ", "_")
    
    # Map parameter names to stage card attributes
    param_map = {
        "cfg_scale": ("txt2img_card", "cfg_var"),
        "cfg": ("txt2img_card", "cfg_var"),
        "steps": ("txt2img_card", "steps_var"),
        "sampler": ("txt2img_card", "sampler_var"),
        "scheduler": ("txt2img_card", "scheduler_var"),
        "denoise_strength": ("img2img_card", "denoise_var"),
        "denoising_strength": ("img2img_card", "denoise_var"),
        "upscale_factor": ("upscale_card", "factor_var"),
    }
    
    mapping = param_map.get(param_lower)
    if not mapping:
        return False
    
    card_name, var_name = mapping
    
    try:
        card = getattr(stage_cards, card_name, None)
        if not card:
            return False
        
        var = getattr(card, var_name, None)
        if not var:
            return False
        
        var.set(value)
        return True
    except Exception:
        return False


def _find_stage_cards_panel(self) -> Any:
    """Find stage cards panel through various paths."""
    # Try via pipeline_state
    if self.pipeline_state:
        cards = getattr(self.pipeline_state, "stage_cards_panel", None)
        if cards:
            return cards
    
    # Try via app reference (if available)
    if hasattr(self, "_app_ref"):
        pipeline_tab = getattr(self._app_ref, "pipeline_tab", None)
        if pipeline_tab:
            return getattr(pipeline_tab, "stage_cards_panel", None)
    
    return None


def _extract_rec_list(self, recommendations: Any) -> list:
    """Extract list of recommendations from various formats."""
    if hasattr(recommendations, "recommendations"):
        return recommendations.recommendations
    elif isinstance(recommendations, list):
        return recommendations
    return []
```

### Step 3: Create Tests

**File:** `tests/learning_v2/test_apply_recommendations.py`

```python
"""Tests for applying recommendations to pipeline."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass
import tkinter as tk


@dataclass
class MockRecommendation:
    parameter_name: str
    recommended_value: any
    confidence_score: float = 0.8
    sample_count: int = 10
    mean_rating: float = 4.0


def test_apply_recommendation_updates_cfg():
    """Verify CFG scale recommendation is applied."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState
    
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    # Mock stage cards
    mock_txt2img_card = MagicMock()
    mock_txt2img_card.cfg_var = MagicMock()
    mock_txt2img_card.cfg_var.set = MagicMock()
    
    mock_stage_cards = MagicMock()
    mock_stage_cards.txt2img_card = mock_txt2img_card
    
    rec = MockRecommendation(parameter_name="CFG Scale", recommended_value=8.5)
    
    result = controller._apply_single_recommendation(mock_stage_cards, "CFG Scale", 8.5)
    
    assert result is True
    mock_txt2img_card.cfg_var.set.assert_called_with(8.5)


def test_apply_recommendation_updates_steps():
    """Verify Steps recommendation is applied."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState
    
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
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState
    
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    mock_stage_cards = MagicMock()
    
    result = controller._apply_single_recommendation(mock_stage_cards, "Unknown Param", 42)
    
    assert result is False
```

---

## 5. Verification

### 5.1 Manual Verification

1. Run an experiment and rate images
2. View recommendations in review panel
3. Click "Apply to Pipeline"
4. Confirm in dialog
5. Switch to Pipeline tab and verify values changed

### 5.2 Automated Verification

```bash
pytest tests/learning_v2/test_apply_recommendations.py -v
```

---

## 6. Related PRs

- **Depends on:** PR-LEARN-008
- **Enables:** PR-LEARN-010 (Analytics Dashboard)

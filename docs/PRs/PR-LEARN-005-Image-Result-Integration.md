# PR-LEARN-005: Image Result Integration

**Status:** DRAFT  
**Priority:** P1 (HIGH)  
**Phase:** 2 (Job Completion Integration)  
**Depends on:** PR-LEARN-004  
**Estimated Effort:** 3-4 hours

---

## 1. Problem Statement

When learning jobs complete, the generated images need to be:

1. **Linked to variants** — Image paths stored in variant's `image_refs` list
2. **Made available for review** — Populated in LearningReviewPanel's image listbox
3. **Tracked for rating** — Connected to the rating workflow

Currently, `_on_variant_job_completed()` has placeholder logic that doesn't extract actual image paths from pipeline results.

---

## 2. Success Criteria

After this PR:
- [ ] Completed variants contain actual image file paths
- [ ] Image listbox in review panel shows real images
- [ ] Selecting a variant shows its images
- [ ] Rating workflow has correct image references

---

## 3. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/gui/controllers/learning_controller.py` | MODIFY | Extract images from pipeline results |
| `src/gui/views/learning_review_panel.py` | MODIFY | Display images properly |
| `src/pipeline/job_models_v2.py` | READ ONLY | Understand result structure |
| `tests/learning_v2/test_image_integration.py` | CREATE | Test image linking |

---

## 4. Implementation Steps

### Step 1: Fix Image Extraction in LearningController

**File:** `src/gui/controllers/learning_controller.py`

**Replace `_on_variant_job_completed()` image extraction:**
```python
def _on_variant_job_completed(self, variant: LearningVariant, result: Any) -> None:
    """Handle completion of a variant job."""
    variant.status = "completed"
    
    # Extract image paths from pipeline result
    image_paths = self._extract_image_paths(result)
    variant.image_refs = image_paths
    variant.completed_images = len(image_paths)

    # Update UI with live updates
    variant_index = self._get_variant_index(variant)
    if variant_index >= 0:
        self._update_variant_status(variant_index, "completed")
        self._update_variant_images(
            variant_index, variant.completed_images, variant.planned_images
        )
        self._highlight_variant(variant_index, False)

    # Update review panel if this variant is selected
    if self._review_panel and hasattr(self._review_panel, "display_variant_results"):
        self._review_panel.display_variant_results(
            variant, self.learning_state.current_experiment
        )
    
    # Update overall progress
    self._update_overall_progress()


def _extract_image_paths(self, result: Any) -> list[str]:
    """Extract image file paths from a pipeline result."""
    paths: list[str] = []
    
    if result is None:
        return paths
    
    # Try common result structures
    
    # 1. Direct images list
    if hasattr(result, "images") and result.images:
        for img in result.images:
            if isinstance(img, str):
                paths.append(img)
            elif hasattr(img, "path"):
                paths.append(str(img.path))
            elif hasattr(img, "__fspath__"):
                paths.append(str(img))
    
    # 2. output_paths attribute
    if hasattr(result, "output_paths"):
        for p in (result.output_paths or []):
            if p and str(p) not in paths:
                paths.append(str(p))
    
    # 3. Dict-based result
    if isinstance(result, dict):
        for key in ("images", "output_paths", "image_paths"):
            if key in result:
                for p in (result[key] or []):
                    if p and str(p) not in paths:
                        paths.append(str(p))
    
    # 4. NormalizedJobRecord-style output
    if hasattr(result, "output_settings"):
        output = result.output_settings
        if hasattr(output, "output_dir"):
            # Images would be in output_dir, but we need actual files
            # This is a fallback - ideally result contains actual paths
            pass
    
    return paths
```

### Step 2: Improve LearningReviewPanel Image Display

**File:** `src/gui/views/learning_review_panel.py`

**Enhance `display_variant_results()`:**
```python
def display_variant_results(
    self, variant: LearningVariant, experiment: Any | None = None
) -> None:
    """Display results for a completed learning variant."""
    self.current_variant = variant
    self.current_experiment = experiment

    # Update status with color coding
    status_text = f"Status: {variant.status.title()}"
    if variant.status == "completed":
        self.status_label.config(text=status_text, foreground="#44FF44")
    elif variant.status == "failed":
        self.status_label.config(text=status_text, foreground="#FF4444")
    elif variant.status == "running":
        self.status_label.config(text=status_text, foreground="#FFC805")
    else:
        self.status_label.config(text=status_text, foreground="white")
    
    self.progress_label.config(
        text=f"Images: {variant.completed_images}/{variant.planned_images}"
    )

    # Update metadata
    self._update_metadata(variant, experiment)

    # Clear and populate image list with actual paths
    self.image_listbox.delete(0, tk.END)
    for i, image_ref in enumerate(variant.image_refs):
        # Show filename only for cleaner display
        filename = self._extract_filename(image_ref)
        self.image_listbox.insert(tk.END, f"{i+1}. {filename}")
    
    # Store full paths for selection handling
    self._image_full_paths = list(variant.image_refs)

    # Auto-select first image if available
    if variant.image_refs:
        self.image_listbox.selection_set(0)
        self._on_image_selected(None)  # Trigger display

    # Reset rating form
    self.rating_var.set(0)
    self.notes_text.delete(1.0, tk.END)
    self.feedback_label.config(text="")

    # Enable/disable rating controls based on status
    state = "normal" if variant.status == "completed" and variant.image_refs else "disabled"
    self.rate_button.config(state=state)
    for btn in self.rating_buttons:
        btn.config(state=state)
    self.notes_text.config(state=tk.NORMAL if state == "normal" else tk.DISABLED)


def _extract_filename(self, path: str) -> str:
    """Extract just the filename from a full path."""
    from pathlib import Path
    try:
        return Path(path).name
    except Exception:
        return str(path)


def _on_image_selected(self, event: tk.Event | None) -> None:
    """Handle image selection from the list."""
    selection = self.image_listbox.curselection()
    if selection and hasattr(self, "_image_full_paths"):
        index = selection[0]
        if 0 <= index < len(self._image_full_paths):
            full_path = self._image_full_paths[index]
            self.selected_image_label.config(text=f"Selected: {self._extract_filename(full_path)}")
            # TODO: PR-LEARN-006 will add actual image preview
    else:
        self.selected_image_label.config(text="Select an image above")
```

**Fix `_submit_rating()` to use full paths:**
```python
def _submit_rating(self) -> None:
    """Submit the rating for the selected image."""
    if not self.current_variant:
        return

    rating = self.rating_var.get()
    notes = self.notes_text.get(1.0, tk.END).strip()

    if rating == 0:
        self.feedback_label.config(text="Please select a rating", foreground="red")
        return

    # Get selected image using stored full paths
    selection = self.image_listbox.curselection()
    if not selection:
        self.feedback_label.config(text="Please select an image to rate", foreground="red")
        return

    image_index = selection[0]
    if not hasattr(self, "_image_full_paths") or image_index >= len(self._image_full_paths):
        self.feedback_label.config(text="Image path not found", foreground="red")
        return
    
    image_ref = self._image_full_paths[image_index]
    # ... rest of rating logic ...
```

### Step 3: Create Tests

**File:** `tests/learning_v2/test_image_integration.py`

```python
"""Tests for learning image result integration."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass, field


@dataclass
class MockPipelineResult:
    success: bool = True
    images: list = field(default_factory=list)
    output_paths: list = field(default_factory=list)


def test_extract_image_paths_from_result():
    """Verify image path extraction handles various result formats."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState
    
    controller = LearningController(learning_state=LearningState())
    
    # Test with images list
    result1 = MockPipelineResult(images=["path/img1.png", "path/img2.png"])
    paths = controller._extract_image_paths(result1)
    assert paths == ["path/img1.png", "path/img2.png"]
    
    # Test with output_paths
    result2 = MockPipelineResult(output_paths=["out/a.png", "out/b.png"])
    paths = controller._extract_image_paths(result2)
    assert "out/a.png" in paths
    
    # Test with dict
    result3 = {"images": ["dict/img.png"]}
    paths = controller._extract_image_paths(result3)
    assert "dict/img.png" in paths
    
    # Test with None
    paths = controller._extract_image_paths(None)
    assert paths == []


def test_variant_receives_image_refs_on_completion():
    """Verify completed variants have correct image references."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningVariant
    
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    variant = LearningVariant(
        experiment_id="test",
        param_value=7.0,
        status="running",
        planned_images=2,
    )
    state.plan = [variant]
    
    result = MockPipelineResult(images=["output/img1.png", "output/img2.png"])
    controller._on_variant_job_completed(variant, result)
    
    assert variant.status == "completed"
    assert len(variant.image_refs) == 2
    assert variant.completed_images == 2


def test_review_panel_shows_filenames():
    """Verify review panel displays clean filenames."""
    from src.gui.views.learning_review_panel import LearningReviewPanel
    
    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    
    filename = panel._extract_filename("C:/Users/test/output/learning_exp_7.5.png")
    assert filename == "learning_exp_7.5.png"
    
    filename = panel._extract_filename("/home/user/images/result.jpg")
    assert filename == "result.jpg"
```

---

## 5. Verification

### 5.1 Manual Verification

1. Run a learning experiment to completion
2. Select a completed variant
3. Verify image list shows actual generated files
4. Select an image and submit a rating
5. Verify rating is saved with correct image path

### 5.2 Automated Verification

```bash
pytest tests/learning_v2/test_image_integration.py -v
```

---

## 6. Related PRs

- **Depends on:** PR-LEARN-004
- **Enables:** PR-LEARN-006 (Image Preview in Review Panel)

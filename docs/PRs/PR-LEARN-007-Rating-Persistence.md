# PR-LEARN-007: Rating Persistence & Retrieval

**Status:** DRAFT  
**Priority:** P2 (MEDIUM)  
**Phase:** 3 (Review & Rating Polish)  
**Depends on:** PR-LEARN-005  
**Estimated Effort:** 2-3 hours

---

## 1. Problem Statement

User ratings are written to `learning_records.jsonl`, but:

1. **Ratings aren't loaded on session start** — Previous ratings lost when app restarts
2. **No visual indicator of rated images** — Can't tell which images already rated
3. **No aggregation view** — No summary of ratings per variant

---

## 2. Success Criteria

After this PR:
- [ ] Previous ratings load on app start
- [ ] Rated images show rating indicator (⭐ or similar)
- [ ] Variant rows show average rating if available
- [ ] Rating submission prevents duplicate ratings for same image

---

## 3. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/gui/controllers/learning_controller.py` | MODIFY | Load ratings on init |
| `src/gui/views/learning_review_panel.py` | MODIFY | Show rating indicators |
| `src/gui/views/learning_plan_table.py` | MODIFY | Add rating column |
| `src/learning/learning_record.py` | MODIFY | Add rating query helpers |
| `tests/learning_v2/test_rating_persistence.py` | CREATE | Test persistence |

---

## 4. Implementation Steps

### Step 1: Add Rating Query Helpers to LearningRecordWriter

**File:** `src/learning/learning_record.py`

**Add methods to LearningRecordWriter:**
```python
def get_ratings_for_experiment(self, experiment_id: str) -> dict[str, int]:
    """Get all ratings for an experiment as {image_path: rating} dict."""
    ratings: dict[str, int] = {}
    
    if not self.records_path.exists():
        return ratings
    
    try:
        with open(self.records_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    metadata = record.get("metadata", {})
                    
                    # Check if this record is for our experiment
                    if metadata.get("experiment_name") != experiment_id:
                        continue
                    
                    # Extract rating and image path
                    rating = metadata.get("user_rating")
                    image_path = metadata.get("image_path")
                    
                    if rating is not None and image_path:
                        ratings[image_path] = int(rating)
                        
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception:
        pass
    
    return ratings


def get_average_rating_for_variant(
    self, 
    experiment_id: str, 
    variant_value: Any
) -> float | None:
    """Get average rating for a specific variant."""
    ratings = []
    
    if not self.records_path.exists():
        return None
    
    try:
        with open(self.records_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    metadata = record.get("metadata", {})
                    
                    if (metadata.get("experiment_name") == experiment_id and
                        metadata.get("variant_value") == variant_value):
                        rating = metadata.get("user_rating")
                        if rating is not None:
                            ratings.append(int(rating))
                            
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception:
        pass
    
    if ratings:
        return sum(ratings) / len(ratings)
    return None


def is_image_rated(self, experiment_id: str, image_path: str) -> bool:
    """Check if an image has already been rated."""
    ratings = self.get_ratings_for_experiment(experiment_id)
    return image_path in ratings
```

### Step 2: Load Ratings in LearningController

**File:** `src/gui/controllers/learning_controller.py`

**Add rating cache:**
```python
def __init__(self, ...):
    # ... existing init ...
    self._rating_cache: dict[str, int] = {}  # {image_path: rating}


def load_existing_ratings(self) -> None:
    """Load existing ratings for the current experiment."""
    if not self._learning_record_writer:
        return
    if not self.learning_state.current_experiment:
        return
    
    experiment_id = self.learning_state.current_experiment.name
    self._rating_cache = self._learning_record_writer.get_ratings_for_experiment(
        experiment_id
    )


def get_rating_for_image(self, image_path: str) -> int | None:
    """Get the rating for an image if it exists."""
    return self._rating_cache.get(image_path)


def is_image_rated(self, image_path: str) -> bool:
    """Check if an image has been rated."""
    return image_path in self._rating_cache
```

**Call `load_existing_ratings()` when experiment changes:**
```python
def build_plan(self, experiment: LearningExperiment) -> None:
    """Build a learning plan from experiment definition."""
    # ... existing code ...
    
    # Load existing ratings for this experiment
    self.load_existing_ratings()
```

### Step 3: Show Rating Indicators in LearningReviewPanel

**File:** `src/gui/views/learning_review_panel.py`

**Update image list display to show ratings:**
```python
def display_variant_results(
    self, variant: LearningVariant, experiment: Any | None = None
) -> None:
    # ... existing code ...
    
    # Clear and populate image list with rating indicators
    self.image_listbox.delete(0, tk.END)
    for i, image_ref in enumerate(variant.image_refs):
        filename = self._extract_filename(image_ref)
        rating = self._get_rating_for_image(image_ref)
        
        if rating:
            # Show rating indicator
            stars = "⭐" * rating
            display = f"{i+1}. {filename} [{stars}]"
        else:
            display = f"{i+1}. {filename}"
        
        self.image_listbox.insert(tk.END, display)
    
    # ... rest of method ...


def _get_rating_for_image(self, image_path: str) -> int | None:
    """Get rating for an image from the controller."""
    # Navigate to controller via parent chain
    try:
        if hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "get_rating_for_image"):
                return controller.get_rating_for_image(image_path)
    except Exception:
        pass
    return None
```

**Prevent duplicate ratings in `_submit_rating()`:**
```python
def _submit_rating(self) -> None:
    # ... existing validation ...
    
    image_ref = self._image_full_paths[image_index]
    
    # Check if already rated
    existing_rating = self._get_rating_for_image(image_ref)
    if existing_rating is not None:
        # Ask for confirmation to override
        from tkinter import messagebox
        if not messagebox.askyesno(
            "Override Rating",
            f"This image already has a rating of {existing_rating}.\nOverride with new rating?"
        ):
            return
    
    # ... rest of rating submission ...
```

### Step 4: Add Rating Column to LearningPlanTable

**File:** `src/gui/views/learning_plan_table.py`

**Add rating column:**
```python
def _create_table(self) -> None:
    # ... existing code ...
    
    # Add rating column
    columns = ("variant", "param_value", "stage", "status", "images", "rating")
    self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
    
    # ... existing headings ...
    self.tree.heading("rating", text="Avg Rating")
    
    # ... existing column widths ...
    self.tree.column("rating", width=80, anchor="center")


def update_row_rating(self, index: int, avg_rating: float | None) -> None:
    """Update the average rating display for a row."""
    try:
        item = self.tree.get_children()[index]
        current_values = list(self.tree.item(item, "values"))
        
        if avg_rating is not None:
            # Display as stars or numeric
            if avg_rating >= 4.5:
                rating_display = "⭐⭐⭐⭐⭐"
            elif avg_rating >= 3.5:
                rating_display = "⭐⭐⭐⭐"
            elif avg_rating >= 2.5:
                rating_display = "⭐⭐⭐"
            elif avg_rating >= 1.5:
                rating_display = "⭐⭐"
            else:
                rating_display = "⭐"
        else:
            rating_display = "—"
        
        current_values[5] = rating_display
        self.tree.item(item, values=current_values)
    except (IndexError, TypeError):
        pass
```

### Step 5: Create Tests

**File:** `tests/learning_v2/test_rating_persistence.py`

```python
"""Tests for rating persistence and retrieval."""
from __future__ import annotations

import pytest
import tempfile
import json
from pathlib import Path


def test_get_ratings_for_experiment():
    """Verify ratings can be retrieved for an experiment."""
    from src.learning.learning_record import LearningRecordWriter
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)
        
        # Write some test records
        records = [
            {"metadata": {"experiment_name": "exp1", "image_path": "a.png", "user_rating": 4}},
            {"metadata": {"experiment_name": "exp1", "image_path": "b.png", "user_rating": 5}},
            {"metadata": {"experiment_name": "exp2", "image_path": "c.png", "user_rating": 3}},
        ]
        
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        
        # Query ratings
        ratings = writer.get_ratings_for_experiment("exp1")
        
        assert len(ratings) == 2
        assert ratings["a.png"] == 4
        assert ratings["b.png"] == 5


def test_get_average_rating_for_variant():
    """Verify average rating calculation."""
    from src.learning.learning_record import LearningRecordWriter
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)
        
        # Write records with multiple ratings for same variant
        records = [
            {"metadata": {"experiment_name": "exp", "variant_value": 7.0, "user_rating": 4}},
            {"metadata": {"experiment_name": "exp", "variant_value": 7.0, "user_rating": 5}},
            {"metadata": {"experiment_name": "exp", "variant_value": 8.0, "user_rating": 3}},
        ]
        
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        
        avg = writer.get_average_rating_for_variant("exp", 7.0)
        assert avg == 4.5
        
        avg = writer.get_average_rating_for_variant("exp", 8.0)
        assert avg == 3.0


def test_is_image_rated():
    """Verify duplicate rating detection."""
    from src.learning.learning_record import LearningRecordWriter
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(path)
        
        records = [
            {"metadata": {"experiment_name": "exp", "image_path": "rated.png", "user_rating": 4}},
        ]
        
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        
        assert writer.is_image_rated("exp", "rated.png") is True
        assert writer.is_image_rated("exp", "unrated.png") is False
```

---

## 5. Verification

### 5.1 Manual Verification

1. Rate several images in an experiment
2. Close and restart StableNew
3. Open the same experiment
4. Verify previously rated images show rating indicators
5. Try to re-rate an image, verify confirmation dialog appears

### 5.2 Automated Verification

```bash
pytest tests/learning_v2/test_rating_persistence.py -v
```

---

## 6. Related PRs

- **Depends on:** PR-LEARN-005
- **Enables:** PR-LEARN-008 (Live Recommendation Display)

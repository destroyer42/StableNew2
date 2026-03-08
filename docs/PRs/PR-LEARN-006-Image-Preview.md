# PR-LEARN-006: Image Preview in Review Panel

**Status:** DRAFT  
**Priority:** P2 (MEDIUM)  
**Phase:** 3 (Review & Rating Polish)  
**Depends on:** PR-LEARN-005  
**Estimated Effort:** 3-4 hours

---

## 1. Problem Statement

The LearningReviewPanel shows a list of image filenames, but selecting an image only displays the filename text. Users need to see the actual image thumbnail to make informed rating decisions.

---

## 2. Success Criteria

After this PR:
- [ ] Selected image displays as a thumbnail in the review panel
- [ ] Images scale to fit the available space
- [ ] Loading indicator shows while image loads
- [ ] Error handling for missing/corrupt images

---

## 3. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/gui/views/learning_review_panel.py` | MODIFY | Add image preview |
| `src/gui/widgets/image_thumbnail.py` | CREATE | Reusable thumbnail widget |
| `tests/gui/test_image_thumbnail.py` | CREATE | Test thumbnail loading |

---

## 4. Implementation Steps

### Step 1: Create ImageThumbnail Widget

**File:** `src/gui/widgets/image_thumbnail.py`

```python
"""Reusable image thumbnail widget for Tkinter."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

# PIL is optional - graceful degradation
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ImageThumbnail(tk.Canvas):
    """Canvas widget that displays a resizable image thumbnail."""
    
    def __init__(
        self,
        master: tk.Misc,
        max_width: int = 300,
        max_height: int = 300,
        bg: str = "#1E1E1E",
        **kwargs: Any,
    ) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, **kwargs)
        self.max_width = max_width
        self.max_height = max_height
        self._photo_image: Any = None  # Keep reference to prevent GC
        self._current_path: str | None = None
        
        # Bind resize event
        self.bind("<Configure>", self._on_resize)
    
    def load_image(self, path: str | None) -> bool:
        """Load and display an image from the given path.
        
        Returns True if successful, False otherwise.
        """
        self.delete("all")
        self._photo_image = None
        self._current_path = path
        
        if not path:
            self._show_placeholder("No image selected")
            return False
        
        if not PIL_AVAILABLE:
            self._show_placeholder("PIL not installed\n(pip install Pillow)")
            return False
        
        try:
            path_obj = Path(path)
            if not path_obj.exists():
                self._show_placeholder(f"File not found:\n{path_obj.name}")
                return False
            
            # Load and resize image
            img = Image.open(path_obj)
            img = self._resize_to_fit(img)
            
            self._photo_image = ImageTk.PhotoImage(img)
            
            # Center image on canvas
            canvas_width = self.winfo_width() or self.max_width
            canvas_height = self.winfo_height() or self.max_height
            x = canvas_width // 2
            y = canvas_height // 2
            
            self.create_image(x, y, image=self._photo_image, anchor="center")
            return True
            
        except Exception as e:
            self._show_placeholder(f"Error loading image:\n{str(e)[:30]}")
            return False
    
    def _resize_to_fit(self, img: "Image.Image") -> "Image.Image":
        """Resize image to fit within max dimensions while preserving aspect ratio."""
        width, height = img.size
        
        # Calculate scale factor
        scale = min(self.max_width / width, self.max_height / height)
        
        if scale < 1:
            new_width = int(width * scale)
            new_height = int(height * scale)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        return img
    
    def _show_placeholder(self, text: str) -> None:
        """Show placeholder text when no image is available."""
        canvas_width = self.winfo_width() or self.max_width
        canvas_height = self.winfo_height() or self.max_height
        x = canvas_width // 2
        y = canvas_height // 2
        
        self.create_text(
            x, y,
            text=text,
            fill="#888888",
            font=("TkDefaultFont", 10),
            anchor="center",
            justify="center",
        )
    
    def _on_resize(self, event: tk.Event) -> None:
        """Handle canvas resize by reloading the current image."""
        if self._current_path:
            # Debounce resize events
            self.after(100, lambda: self.load_image(self._current_path))
    
    def clear(self) -> None:
        """Clear the current image."""
        self.delete("all")
        self._photo_image = None
        self._current_path = None
        self._show_placeholder("No image selected")
```

### Step 2: Integrate Thumbnail into LearningReviewPanel

**File:** `src/gui/views/learning_review_panel.py`

**Add import:**
```python
from src.gui.widgets.image_thumbnail import ImageThumbnail
```

**Replace image display section in `__init__()`:**
```python
# Image display section - REPLACE EXISTING
self.image_frame = ttk.LabelFrame(self, text="Images", padding=5)
self.image_frame.grid(row=3, column=0, sticky="nsew", padx=5, pady=5)
self.image_frame.columnconfigure(0, weight=1)
self.image_frame.rowconfigure(1, weight=1)  # Thumbnail row gets weight

# Image list (top)
self.image_listbox = tk.Listbox(self.image_frame, height=5)
self.image_listbox.grid(row=0, column=0, sticky="ew")
self.image_listbox.bind("<<ListboxSelect>>", self._on_image_selected)

# Image thumbnail (bottom)
self.image_thumbnail = ImageThumbnail(
    self.image_frame,
    max_width=250,
    max_height=250,
)
self.image_thumbnail.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
self.image_thumbnail.clear()

# Remove old placeholder label
# self.selected_image_label = ttk.Label(...)
```

**Update `_on_image_selected()`:**
```python
def _on_image_selected(self, event: tk.Event | None) -> None:
    """Handle image selection from the list."""
    selection = self.image_listbox.curselection()
    if selection and hasattr(self, "_image_full_paths"):
        index = selection[0]
        if 0 <= index < len(self._image_full_paths):
            full_path = self._image_full_paths[index]
            # Load image into thumbnail
            self.image_thumbnail.load_image(full_path)
    else:
        self.image_thumbnail.clear()
```

### Step 3: Create Tests

**File:** `tests/gui/test_image_thumbnail.py`

```python
"""Tests for ImageThumbnail widget."""
from __future__ import annotations

import pytest
from pathlib import Path
import tempfile


def test_thumbnail_handles_missing_pil():
    """Verify graceful degradation without PIL."""
    from src.gui.widgets import image_thumbnail
    
    # Module should load regardless of PIL availability
    assert hasattr(image_thumbnail, "ImageThumbnail")
    assert hasattr(image_thumbnail, "PIL_AVAILABLE")


def test_thumbnail_handles_missing_file():
    """Verify error handling for missing files."""
    from src.gui.widgets.image_thumbnail import ImageThumbnail
    from unittest.mock import MagicMock
    
    # Create mock widget
    thumb = ImageThumbnail.__new__(ImageThumbnail)
    thumb.max_width = 300
    thumb.max_height = 300
    thumb._photo_image = None
    thumb._current_path = None
    thumb.delete = MagicMock()
    thumb.create_text = MagicMock()
    thumb.winfo_width = MagicMock(return_value=300)
    thumb.winfo_height = MagicMock(return_value=300)
    
    # Load non-existent file
    result = thumb.load_image("/nonexistent/path/image.png")
    
    assert result is False
    thumb.create_text.assert_called()  # Should show placeholder


@pytest.mark.skipif(not pytest.importorskip("PIL"), reason="PIL not installed")
def test_thumbnail_loads_valid_image():
    """Verify loading a valid image file."""
    from PIL import Image
    from src.gui.widgets.image_thumbnail import ImageThumbnail
    from unittest.mock import MagicMock
    
    # Create a test image
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img = Image.new("RGB", (100, 100), color="red")
        img.save(f.name)
        
        # Create mock widget
        thumb = ImageThumbnail.__new__(ImageThumbnail)
        thumb.max_width = 300
        thumb.max_height = 300
        thumb._photo_image = None
        thumb._current_path = None
        thumb.delete = MagicMock()
        thumb.create_image = MagicMock()
        thumb.winfo_width = MagicMock(return_value=300)
        thumb.winfo_height = MagicMock(return_value=300)
        
        result = thumb.load_image(f.name)
        
        assert result is True
        thumb.create_image.assert_called()
```

---

## 5. Verification

### 5.1 Manual Verification

1. Complete a learning experiment
2. Select a variant with images
3. Click an image in the list
4. Verify thumbnail displays correctly
5. Try selecting a missing image (verify error handling)

### 5.2 Automated Verification

```bash
pytest tests/gui/test_image_thumbnail.py -v
```

---

## 6. Related PRs

- **Depends on:** PR-LEARN-005
- **Related:** PR-LEARN-007 (Rating Persistence)

# PR-PIPE-006 – Preview Panel Image Thumbnails

## Context

The Preview Panel currently shows only text-based job summaries:
- Positive prompt (truncated)
- Negative prompt (truncated)
- Model, sampler, steps, CFG, seed
- Stage flags

There is no visual preview of what the job will produce or has produced. Users requested:

1. **Reference thumbnails** - Show example images from the same pack/model combination
2. **Recent output thumbnails** - Show last images generated with similar config
3. **In-progress thumbnails** - Show the current generation preview (future enhancement)

This PR focuses on adding a thumbnail display area that can show:
- Placeholder when no preview available
- Most recent image from same prompt pack
- Output from completed job (when viewing history)

## Non-Goals

- Real-time preview during generation (that's PR-PIPE-004)
- Full-size image viewer in preview panel
- Gallery/browser functionality
- Thumbnail caching to disk (keep in-memory)
- GIF/animation preview
- Multiple thumbnail carousel

## Invariants

- Preview panel must function without thumbnails (graceful degradation)
- Thumbnail loading must not block UI thread
- Image decoding errors must not crash the panel
- Memory usage must be bounded (clear old thumbnails)
- Thumbnail area must have fixed dimensions (not expand panel)
- Original images must not be modified

## Allowed Files

- `src/gui/preview_panel_v2.py` - Add thumbnail widget and loading logic
- `src/gui/widgets/thumbnail_widget_v2.py` (new) - Reusable thumbnail component
- `src/utils/image_utils.py` (new or add to existing) - Thumbnail generation
- `tests/gui_v2/test_preview_panel_thumbnail.py` (new)
- `tests/utils/test_image_utils.py` (new)

## Do Not Touch

- `src/pipeline/executor.py` - Image generation unchanged
- `src/gui/panels_v2/running_job_panel_v2.py` - Different panel
- `src/gui/job_history_panel_v2.py` - Different panel
- `src/controller/*` - Controller logic unchanged

## Interfaces

### ThumbnailWidget

```python
class ThumbnailWidget(ttk.Frame):
    """Widget displaying a thumbnail image with placeholder support."""
    
    def __init__(
        self,
        master: tk.Misc,
        *,
        width: int = 150,
        height: int = 150,
        placeholder_text: str = "No Preview",
        **kwargs,
    ) -> None: ...
    
    def set_image(self, image: Image.Image | None) -> None:
        """Set the displayed thumbnail from a PIL Image."""
    
    def set_image_from_path(self, path: Path | str) -> None:
        """Load and display thumbnail from file path (async)."""
    
    def set_image_from_base64(self, data: str) -> None:
        """Load and display thumbnail from base64 string."""
    
    def clear(self) -> None:
        """Clear the thumbnail and show placeholder."""
    
    def set_loading(self) -> None:
        """Show loading indicator."""
```

### Image Utilities

```python
def generate_thumbnail(
    image: Image.Image,
    max_size: tuple[int, int] = (150, 150),
    *,
    preserve_aspect: bool = True,
    background: str = "#2a2a2a",
) -> Image.Image:
    """Generate a thumbnail from a PIL Image."""


def load_image_thumbnail(
    path: Path,
    max_size: tuple[int, int] = (150, 150),
) -> Image.Image | None:
    """Load an image file and return a thumbnail, or None on error."""


async def load_image_thumbnail_async(
    path: Path,
    max_size: tuple[int, int] = (150, 150),
) -> Image.Image | None:
    """Async version of load_image_thumbnail."""
```

### Preview Panel Integration

```python
class PreviewPanelV2(ttk.Frame):
    
    def _find_recent_thumbnail(self, job: NormalizedJobRecord) -> Path | None:
        """Find a recent image that matches this job's config for preview."""
    
    def _update_thumbnail(self, job: NormalizedJobRecord | None) -> None:
        """Update the thumbnail display for the current preview job."""
```

### Error Behavior

- Image file not found: Show placeholder "Image not found"
- Image decode error: Show placeholder "Invalid image"
- Path is None: Show placeholder "No preview"
- Loading timeout: Show placeholder after 5 seconds
- Memory pressure: Clear thumbnail cache

## Implementation Steps (Order Matters)

### Step 1: Create Image Utilities Module

Create `src/utils/image_utils.py`:

```python
"""Image utility functions for thumbnail generation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)


def generate_thumbnail(
    image: "Image.Image",
    max_size: tuple[int, int] = (150, 150),
    *,
    preserve_aspect: bool = True,
    background: str | None = None,
) -> "Image.Image":
    """
    Generate a thumbnail from a PIL Image.
    
    Args:
        image: Source PIL Image
        max_size: Maximum (width, height) for thumbnail
        preserve_aspect: If True, maintain aspect ratio
        background: Optional background color for letterboxing
        
    Returns:
        Thumbnail as PIL Image
    """
    from PIL import Image as PILImage
    
    if preserve_aspect:
        # Use LANCZOS for high-quality downscaling
        thumb = image.copy()
        thumb.thumbnail(max_size, PILImage.Resampling.LANCZOS)
        
        if background:
            # Create background and paste thumbnail centered
            bg = PILImage.new("RGBA", max_size, background)
            x = (max_size[0] - thumb.width) // 2
            y = (max_size[1] - thumb.height) // 2
            
            # Handle transparency
            if thumb.mode == "RGBA":
                bg.paste(thumb, (x, y), thumb)
            else:
                bg.paste(thumb, (x, y))
            return bg
        
        return thumb
    else:
        return image.resize(max_size, PILImage.Resampling.LANCZOS)


def load_image_thumbnail(
    path: Path | str,
    max_size: tuple[int, int] = (150, 150),
    *,
    background: str | None = "#2a2a2a",
) -> "Image.Image | None":
    """
    Load an image file and return a thumbnail.
    
    Args:
        path: Path to image file
        max_size: Maximum thumbnail dimensions
        background: Background color for letterboxing
        
    Returns:
        Thumbnail PIL Image, or None on error
    """
    from PIL import Image as PILImage
    
    try:
        path = Path(path)
        if not path.exists():
            logger.debug(f"Thumbnail source not found: {path}")
            return None
        
        with PILImage.open(path) as img:
            # Convert to RGB if needed
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            
            return generate_thumbnail(img, max_size, background=background)
            
    except Exception as exc:
        logger.debug(f"Failed to load thumbnail from {path}: {exc}")
        return None
```

### Step 2: Create ThumbnailWidget

Create `src/gui/widgets/thumbnail_widget_v2.py`:

```python
"""Thumbnail display widget for GUI V2."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image, ImageTk

from src.gui.theme_v2 import BACKGROUND_ELEVATED, TEXT_SECONDARY


class ThumbnailWidget(ttk.Frame):
    """Widget displaying a thumbnail image with placeholder support."""
    
    def __init__(
        self,
        master: tk.Misc,
        *,
        width: int = 150,
        height: int = 150,
        placeholder_text: str = "No Preview",
        background: str = BACKGROUND_ELEVATED,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        
        self._width = width
        self._height = height
        self._placeholder_text = placeholder_text
        self._background = background
        self._photo_image: "ImageTk.PhotoImage | None" = None
        self._load_thread: threading.Thread | None = None
        
        # Create canvas for image display
        self._canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            bg=background,
            highlightthickness=1,
            highlightbackground="#3a3a3a",
        )
        self._canvas.pack(fill="both", expand=True)
        
        # Show initial placeholder
        self._show_placeholder()
    
    def _show_placeholder(self, text: str | None = None) -> None:
        """Display placeholder text."""
        self._canvas.delete("all")
        display_text = text or self._placeholder_text
        self._canvas.create_text(
            self._width // 2,
            self._height // 2,
            text=display_text,
            fill=TEXT_SECONDARY,
            font=("Segoe UI", 9),
            anchor="center",
        )
    
    def set_image(self, image: "Image.Image | None") -> None:
        """Set the displayed thumbnail from a PIL Image."""
        if image is None:
            self.clear()
            return
        
        try:
            from PIL import ImageTk
            
            # Keep reference to prevent garbage collection
            self._photo_image = ImageTk.PhotoImage(image)
            
            self._canvas.delete("all")
            self._canvas.create_image(
                self._width // 2,
                self._height // 2,
                image=self._photo_image,
                anchor="center",
            )
        except Exception as exc:
            self._show_placeholder("Image error")
    
    def set_image_from_path(self, path: Path | str) -> None:
        """Load and display thumbnail from file path (async)."""
        self.set_loading()
        
        def _load():
            from src.utils.image_utils import load_image_thumbnail
            
            thumb = load_image_thumbnail(path, (self._width, self._height))
            
            # Schedule UI update on main thread
            if self.winfo_exists():
                self.after(0, lambda: self._on_image_loaded(thumb))
        
        self._load_thread = threading.Thread(target=_load, daemon=True)
        self._load_thread.start()
    
    def _on_image_loaded(self, image: "Image.Image | None") -> None:
        """Handle async image load completion."""
        if image is None:
            self._show_placeholder("Not found")
        else:
            self.set_image(image)
    
    def set_image_from_base64(self, data: str) -> None:
        """Load and display thumbnail from base64 string."""
        import base64
        import io
        
        try:
            from PIL import Image as PILImage
            from src.utils.image_utils import generate_thumbnail
            
            # Decode base64
            if data.startswith("data:"):
                data = data.split(",", 1)[1]
            
            image_data = base64.b64decode(data)
            img = PILImage.open(io.BytesIO(image_data))
            thumb = generate_thumbnail(img, (self._width, self._height))
            self.set_image(thumb)
            
        except Exception as exc:
            self._show_placeholder("Decode error")
    
    def clear(self) -> None:
        """Clear the thumbnail and show placeholder."""
        self._photo_image = None
        self._show_placeholder()
    
    def set_loading(self) -> None:
        """Show loading indicator."""
        self._show_placeholder("Loading...")
```

### Step 3: Add Thumbnail to Preview Panel

In `src/gui/preview_panel_v2.py`, add thumbnail widget:

```python
from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget

class PreviewPanelV2(ttk.Frame):
    
    def __init__(self, ...):
        # ... existing init ...
        
        # Add thumbnail widget after header
        self.thumbnail_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
        self.thumbnail_frame.pack(fill="x", pady=(0, 8))
        
        self.thumbnail = ThumbnailWidget(
            self.thumbnail_frame,
            width=150,
            height=150,
            placeholder_text="No Preview",
        )
        self.thumbnail.pack(anchor="center")
        
        # ... rest of existing init ...
```

### Step 4: Add Thumbnail Loading Logic

```python
def _find_recent_thumbnail(self, job: Any) -> Path | None:
    """Find a recent image that matches this job's config for preview."""
    # Try to get output directory from job config
    output_dir = Path("output")
    
    # Get pack name or model for matching
    pack_name = None
    model_name = None
    
    if hasattr(job, "prompt_pack_name"):
        pack_name = job.prompt_pack_name
    if hasattr(job, "to_unified_summary"):
        summary = job.to_unified_summary()
        pack_name = pack_name or getattr(summary, "prompt_pack_name", None)
        model_name = getattr(summary, "model_name", None)
    
    # Look for recent outputs with matching pack/model
    try:
        # List recent run directories
        run_dirs = sorted(
            output_dir.iterdir(),
            key=lambda p: p.stat().st_mtime if p.is_dir() else 0,
            reverse=True,
        )[:10]  # Check last 10 runs
        
        for run_dir in run_dirs:
            if not run_dir.is_dir():
                continue
            
            # Check if pack name matches (in directory name)
            if pack_name and pack_name.lower() not in run_dir.name.lower():
                continue
            
            # Find first image in directory
            for img_path in run_dir.glob("*.png"):
                return img_path
            
            # Check txt2img subdirectory
            txt2img_dir = run_dir / "txt2img"
            if txt2img_dir.exists():
                for img_path in txt2img_dir.glob("*.png"):
                    return img_path
        
    except Exception:
        pass
    
    return None


def _update_thumbnail(self, job: Any | None) -> None:
    """Update the thumbnail display for the current preview job."""
    if job is None:
        self.thumbnail.clear()
        return
    
    # Try to find a matching image
    thumb_path = self._find_recent_thumbnail(job)
    
    if thumb_path:
        self.thumbnail.set_image_from_path(thumb_path)
    else:
        self.thumbnail.clear()
```

### Step 5: Wire Thumbnail Updates to Job Selection

Update `set_preview_jobs` and `set_job_summaries`:

```python
def set_preview_jobs(self, jobs: list[NormalizedJobRecord] | None) -> None:
    """Render previews from NormalizedJobRecord objects."""
    # ... existing code ...
    
    # Update thumbnail for first job
    if jobs and len(jobs) > 0:
        self._update_thumbnail(jobs[0])
    else:
        self.thumbnail.clear()
```

### Step 6: Write Tests

Create test files for new components.

## Acceptance Criteria

1. **Given** the preview panel displays, **when** no job is selected, **then** the thumbnail shows "No Preview" placeholder.

2. **Given** a prompt pack job preview, **when** similar images exist in output, **then** the thumbnail shows the most recent matching image.

3. **Given** an image path that doesn't exist, **when** loading thumbnail, **then** "Not found" placeholder is shown without errors.

4. **Given** a large image (4K resolution), **when** loading thumbnail, **then** thumbnail is generated within 1 second and fits display area.

5. **Given** thumbnail loading in progress, **when** user switches to different job, **then** old loading is abandoned and new thumbnail loads.

6. **Given** portrait-oriented image, **when** displaying thumbnail, **then** aspect ratio is preserved with letterboxing.

7. **Given** the ThumbnailWidget, **when** used in other panels, **then** it works as a reusable component.

## Test Plan

### Unit Tests

```bash
pytest tests/utils/test_image_utils.py -v
pytest tests/gui_v2/test_preview_panel_thumbnail.py -v
```

**Image Utils Tests:**

1. `test_generate_thumbnail_preserves_aspect` - Aspect ratio maintained
2. `test_generate_thumbnail_fits_max_size` - Doesn't exceed bounds
3. `test_generate_thumbnail_with_background` - Letterboxing works
4. `test_load_image_thumbnail_valid_file` - Loads existing file
5. `test_load_image_thumbnail_missing_file` - Returns None
6. `test_load_image_thumbnail_corrupt_file` - Returns None

**Thumbnail Widget Tests:**

1. `test_thumbnail_widget_shows_placeholder` - Initial state
2. `test_thumbnail_widget_set_image` - PIL Image display
3. `test_thumbnail_widget_set_from_path` - Async loading
4. `test_thumbnail_widget_clear` - Returns to placeholder
5. `test_thumbnail_widget_loading_state` - Shows loading text

**Preview Panel Tests:**

1. `test_preview_panel_has_thumbnail` - Widget exists
2. `test_preview_panel_updates_thumbnail` - Thumbnail changes with job
3. `test_preview_panel_clears_thumbnail` - Clears when no job

## Rollback

```bash
git revert <commit-hash>
```

Rollback is safe because:
- Thumbnail widget is additive
- Preview panel functions without thumbnails
- No data changes
- No core logic changes

## Dependencies

- None

## Dependents

- PR-PIPE-004 (Progress Polling) could use ThumbnailWidget for live preview

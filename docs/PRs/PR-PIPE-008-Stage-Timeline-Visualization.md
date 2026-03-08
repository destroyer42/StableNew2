# PR-PIPE-008 – Stage Timeline Visualization

## Context

Currently, the Running Job Panel displays stage execution status in a text-based format:

```
Stage: txt2img [▇▇▇▇▇----] 55% → upscale → adetailer
```

While functional, this doesn't provide:
- Visual sense of total progress through all stages
- Time spent on each completed stage
- Relative timing between stages
- Clear distinction between completed, running, and pending

This PR introduces a visual stage timeline widget that:
1. Shows each stage as a colored segment
2. Indicates status via color (completed=green, running=yellow, pending=gray)
3. Displays timing information for completed stages
4. Animates the currently running stage
5. Provides tooltips with detailed stage information

## Non-Goals

- Changing stage execution order
- Adding new stage types
- Modifying the executor's stage reporting
- Real-time sub-step visualization within stages
- Full job Gantt chart for queue

## Invariants

- Timeline must not affect stage execution
- Widget must degrade gracefully if timing data missing
- Timeline must work with any stage combination
- Must not add significant UI rendering overhead
- Dark mode compatibility required

## Allowed Files

- `src/gui/panels_v2/widgets/stage_timeline_widget.py` (new)
- `src/gui/panels_v2/running_job_panel_v2.py` - Integrate widget
- `src/gui/theme_manager.py` - Timeline colors if needed
- `tests/gui_v2/widgets/test_stage_timeline_widget.py` (new)

## Do Not Touch

- `src/pipeline/executor.py` - No execution changes
- `src/pipeline/stages/*` - No stage logic changes
- `src/queue/*` - No queue changes
- `src/controller/*` - No controller changes

## Interfaces

### Stage Data Model

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class StageStatus(Enum):
    """Visual status of a stage in the timeline."""
    
    PENDING = "pending"       # Gray - not yet started
    RUNNING = "running"       # Yellow/Amber - currently executing
    COMPLETED = "completed"   # Green - finished successfully
    FAILED = "failed"         # Red - error occurred
    SKIPPED = "skipped"       # Light gray - was skipped


@dataclass
class TimelineStage:
    """Data for a single stage in the timeline."""
    
    name: str                           # Stage identifier (e.g., "txt2img")
    display_name: str                   # UI-friendly name
    status: StageStatus = StageStatus.PENDING
    start_time: datetime | None = None
    end_time: datetime | None = None
    progress_pct: float = 0.0           # 0.0-100.0
    step: int = 0                       # Current step (if available)
    total_steps: int = 0                # Total steps (if available)
    
    @property
    def duration_ms(self) -> int | None:
        """Calculate duration in milliseconds."""
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            return int(delta.total_seconds() * 1000)
        return None
    
    @property
    def duration_display(self) -> str:
        """Format duration for display."""
        ms = self.duration_ms
        if ms is None:
            return "-"
        if ms < 1000:
            return f"{ms}ms"
        secs = ms / 1000
        if secs < 60:
            return f"{secs:.1f}s"
        mins = int(secs // 60)
        remaining = secs % 60
        return f"{mins}m {remaining:.0f}s"


@dataclass
class TimelineData:
    """Complete timeline state for a job."""
    
    stages: list[TimelineStage] = field(default_factory=list)
    total_duration_ms: int | None = None
    
    @property
    def current_stage_index(self) -> int | None:
        """Get index of currently running stage."""
        for i, stage in enumerate(self.stages):
            if stage.status == StageStatus.RUNNING:
                return i
        return None
    
    @property
    def completed_count(self) -> int:
        """Count of completed stages."""
        return sum(
            1 for s in self.stages
            if s.status in (StageStatus.COMPLETED, StageStatus.SKIPPED)
        )
    
    @property
    def overall_progress(self) -> float:
        """Overall progress 0.0-100.0."""
        if not self.stages:
            return 0.0
        
        total = len(self.stages)
        completed = self.completed_count
        
        # Add partial progress from running stage
        current_idx = self.current_stage_index
        if current_idx is not None:
            partial = self.stages[current_idx].progress_pct / 100
            return ((completed + partial) / total) * 100
        
        return (completed / total) * 100
```

### Widget Interface

```python
class StageTimelineWidget(ttk.Frame):
    """Visual timeline showing stage progression."""
    
    def __init__(
        self,
        parent: tk.Widget,
        *,
        height: int = 40,
        show_timing: bool = True,
        animate: bool = True,
        **kwargs: Any,
    ) -> None:
        """
        Initialize timeline widget.
        
        Args:
            parent: Parent widget
            height: Widget height in pixels
            show_timing: Show timing labels for completed stages
            animate: Animate the running stage indicator
        """
    
    def set_stages(self, data: TimelineData) -> None:
        """
        Update timeline with new stage data.
        
        This is the main update method. Call whenever stage
        status changes.
        """
    
    def set_current_progress(self, stage_name: str, progress: float) -> None:
        """
        Update progress for the currently running stage.
        
        Args:
            stage_name: Name of stage to update
            progress: Progress percentage (0-100)
        """
    
    def clear(self) -> None:
        """Reset timeline to empty state."""
    
    def get_stage_tooltip(self, stage_name: str) -> str | None:
        """Get tooltip text for a stage."""
```

### Color Scheme

```python
# Timeline colors (from theme_manager)
TIMELINE_COLORS = {
    "pending_bg": "#444444",        # Dark gray
    "pending_border": "#555555",
    "running_bg": "#FFC107",        # Amber
    "running_border": "#FFD54F",
    "running_pulse": "#FFE082",     # Animation color
    "completed_bg": "#4CAF50",      # Green
    "completed_border": "#66BB6A",
    "failed_bg": "#F44336",         # Red
    "failed_border": "#EF5350",
    "skipped_bg": "#666666",        # Light gray
    "skipped_border": "#777777",
    "label_text": "#FFFFFF",
    "timing_text": "#CCCCCC",
}
```

## Implementation Steps (Order Matters)

### Step 1: Create Widget File

Create `src/gui/panels_v2/widgets/stage_timeline_widget.py`:

```python
"""
Stage Timeline Widget - Visual representation of job stage progression.

Displays stages as colored segments with status indication:
- Pending: Gray
- Running: Yellow/Amber with pulse animation
- Completed: Green with timing
- Failed: Red
- Skipped: Light gray

Part of PR-PIPE-008.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from tkinter import ttk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing import Callable


class StageStatus(Enum):
    """Visual status of a stage in the timeline."""
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TimelineStage:
    """Data for a single stage in the timeline."""
    
    name: str
    display_name: str
    status: StageStatus = StageStatus.PENDING
    start_time: datetime | None = None
    end_time: datetime | None = None
    progress_pct: float = 0.0
    step: int = 0
    total_steps: int = 0
    
    @property
    def duration_ms(self) -> int | None:
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            return int(delta.total_seconds() * 1000)
        return None
    
    @property
    def duration_display(self) -> str:
        ms = self.duration_ms
        if ms is None:
            return ""
        if ms < 1000:
            return f"{ms}ms"
        secs = ms / 1000
        if secs < 60:
            return f"{secs:.1f}s"
        mins = int(secs // 60)
        remaining = secs % 60
        return f"{mins}m {remaining:.0f}s"


@dataclass
class TimelineData:
    """Complete timeline state for a job."""
    
    stages: list[TimelineStage] = field(default_factory=list)
    total_duration_ms: int | None = None
    
    @property
    def current_stage_index(self) -> int | None:
        for i, stage in enumerate(self.stages):
            if stage.status == StageStatus.RUNNING:
                return i
        return None
    
    @property
    def completed_count(self) -> int:
        return sum(
            1 for s in self.stages
            if s.status in (StageStatus.COMPLETED, StageStatus.SKIPPED)
        )
    
    @property
    def overall_progress(self) -> float:
        if not self.stages:
            return 0.0
        
        total = len(self.stages)
        completed = self.completed_count
        
        current_idx = self.current_stage_index
        if current_idx is not None:
            partial = self.stages[current_idx].progress_pct / 100
            return ((completed + partial) / total) * 100
        
        return (completed / total) * 100


class StageTimelineWidget(ttk.Frame):
    """Visual timeline showing stage progression."""
    
    # Color constants
    COLORS = {
        "pending_bg": "#444444",
        "pending_border": "#555555",
        "running_bg": "#FFC107",
        "running_border": "#FFD54F",
        "running_pulse": "#FFE082",
        "completed_bg": "#4CAF50",
        "completed_border": "#66BB6A",
        "failed_bg": "#F44336",
        "failed_border": "#EF5350",
        "skipped_bg": "#666666",
        "skipped_border": "#777777",
        "label_text": "#FFFFFF",
        "timing_text": "#CCCCCC",
        "progress_overlay": "#FFFFFF33",  # Transparent white
    }
    
    def __init__(
        self,
        parent: tk.Widget,
        *,
        height: int = 40,
        show_timing: bool = True,
        animate: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, **kwargs)
        
        self._height = height
        self._show_timing = show_timing
        self._animate = animate
        self._data: TimelineData | None = None
        self._animation_id: str | None = None
        self._pulse_phase = 0  # For animation
        
        # Create canvas
        self._canvas = tk.Canvas(
            self,
            height=height,
            highlightthickness=0,
            bg=self.COLORS["pending_bg"],
        )
        self._canvas.pack(fill="x", expand=True)
        
        # Bind resize
        self._canvas.bind("<Configure>", self._on_resize)
        
        # Tooltip support
        self._tooltip_window: tk.Toplevel | None = None
        self._canvas.bind("<Motion>", self._on_mouse_move)
        self._canvas.bind("<Leave>", self._on_mouse_leave)
    
    def set_stages(self, data: TimelineData) -> None:
        """Update timeline with new stage data."""
        self._data = data
        self._redraw()
        
        # Start/stop animation based on running stage
        if data.current_stage_index is not None and self._animate:
            self._start_animation()
        else:
            self._stop_animation()
    
    def set_current_progress(self, stage_name: str, progress: float) -> None:
        """Update progress for the currently running stage."""
        if self._data is None:
            return
        
        for stage in self._data.stages:
            if stage.name == stage_name:
                stage.progress_pct = progress
                self._redraw()
                break
    
    def clear(self) -> None:
        """Reset timeline to empty state."""
        self._data = None
        self._stop_animation()
        self._canvas.delete("all")
    
    def _redraw(self) -> None:
        """Redraw the entire timeline."""
        self._canvas.delete("all")
        
        if self._data is None or not self._data.stages:
            return
        
        width = self._canvas.winfo_width()
        height = self._height
        
        if width < 10:
            return  # Too small to draw
        
        num_stages = len(self._data.stages)
        segment_width = width / num_stages
        padding = 2
        
        for i, stage in enumerate(self._data.stages):
            x1 = i * segment_width + padding
            x2 = (i + 1) * segment_width - padding
            y1 = padding
            y2 = height - padding
            
            # Get colors based on status
            bg_color, border_color = self._get_stage_colors(stage)
            
            # Draw segment background
            self._canvas.create_rectangle(
                x1, y1, x2, y2,
                fill=bg_color,
                outline=border_color,
                width=2,
                tags=f"stage_{stage.name}",
            )
            
            # Draw progress overlay for running stage
            if stage.status == StageStatus.RUNNING and stage.progress_pct > 0:
                progress_x = x1 + (x2 - x1) * (stage.progress_pct / 100)
                self._canvas.create_rectangle(
                    x1, y1, progress_x, y2,
                    fill=self.COLORS["progress_overlay"],
                    outline="",
                    tags=f"progress_{stage.name}",
                )
            
            # Draw stage name
            center_x = (x1 + x2) / 2
            center_y = height / 2
            
            # Abbreviate if needed
            display_text = self._abbreviate_name(stage.display_name, segment_width - 10)
            
            self._canvas.create_text(
                center_x,
                center_y - (6 if self._show_timing and stage.duration_ms else 0),
                text=display_text,
                fill=self.COLORS["label_text"],
                font=("Segoe UI", 9, "bold"),
                anchor="center",
                tags=f"label_{stage.name}",
            )
            
            # Draw timing for completed stages
            if self._show_timing and stage.duration_display:
                self._canvas.create_text(
                    center_x,
                    center_y + 10,
                    text=stage.duration_display,
                    fill=self.COLORS["timing_text"],
                    font=("Segoe UI", 7),
                    anchor="center",
                    tags=f"timing_{stage.name}",
                )
    
    def _get_stage_colors(self, stage: TimelineStage) -> tuple[str, str]:
        """Get (bg, border) colors for a stage."""
        color_map = {
            StageStatus.PENDING: ("pending_bg", "pending_border"),
            StageStatus.RUNNING: ("running_bg", "running_border"),
            StageStatus.COMPLETED: ("completed_bg", "completed_border"),
            StageStatus.FAILED: ("failed_bg", "failed_border"),
            StageStatus.SKIPPED: ("skipped_bg", "skipped_border"),
        }
        
        bg_key, border_key = color_map.get(
            stage.status,
            ("pending_bg", "pending_border"),
        )
        
        # Apply pulse effect for running stage
        if stage.status == StageStatus.RUNNING and self._animate:
            pulse = (self._pulse_phase % 20) / 20
            if pulse > 0.5:
                bg_key = "running_pulse"
        
        return self.COLORS[bg_key], self.COLORS[border_key]
    
    def _abbreviate_name(self, name: str, max_width: float) -> str:
        """Abbreviate stage name to fit width."""
        # Simple heuristic: ~7 pixels per character
        max_chars = int(max_width / 7)
        if len(name) <= max_chars:
            return name
        if max_chars <= 3:
            return name[0]
        return name[:max_chars - 2] + "…"
    
    def _on_resize(self, event: tk.Event) -> None:
        """Handle canvas resize."""
        self._redraw()
    
    def _start_animation(self) -> None:
        """Start pulse animation for running stage."""
        if self._animation_id is not None:
            return  # Already animating
        
        def animate() -> None:
            self._pulse_phase = (self._pulse_phase + 1) % 40
            self._redraw()
            self._animation_id = self.after(100, animate)
        
        animate()
    
    def _stop_animation(self) -> None:
        """Stop pulse animation."""
        if self._animation_id is not None:
            self.after_cancel(self._animation_id)
            self._animation_id = None
    
    def _on_mouse_move(self, event: tk.Event) -> None:
        """Handle mouse movement for tooltips."""
        if self._data is None:
            self._hide_tooltip()
            return
        
        # Find which stage is under cursor
        width = self._canvas.winfo_width()
        num_stages = len(self._data.stages)
        if num_stages == 0:
            return
        
        segment_width = width / num_stages
        stage_index = int(event.x / segment_width)
        
        if 0 <= stage_index < num_stages:
            stage = self._data.stages[stage_index]
            tooltip_text = self._format_tooltip(stage)
            self._show_tooltip(event.x_root, event.y_root, tooltip_text)
        else:
            self._hide_tooltip()
    
    def _on_mouse_leave(self, event: tk.Event) -> None:
        """Handle mouse leaving canvas."""
        self._hide_tooltip()
    
    def _format_tooltip(self, stage: TimelineStage) -> str:
        """Format tooltip text for a stage."""
        lines = [
            f"Stage: {stage.display_name}",
            f"Status: {stage.status.value.title()}",
        ]
        
        if stage.status == StageStatus.RUNNING:
            lines.append(f"Progress: {stage.progress_pct:.1f}%")
            if stage.step > 0 and stage.total_steps > 0:
                lines.append(f"Step: {stage.step}/{stage.total_steps}")
        
        if stage.duration_ms is not None:
            lines.append(f"Duration: {stage.duration_display}")
        
        return "\n".join(lines)
    
    def _show_tooltip(self, x: int, y: int, text: str) -> None:
        """Show tooltip at position."""
        self._hide_tooltip()
        
        self._tooltip_window = tk.Toplevel(self)
        self._tooltip_window.wm_overrideredirect(True)
        self._tooltip_window.wm_geometry(f"+{x + 10}+{y + 10}")
        
        label = tk.Label(
            self._tooltip_window,
            text=text,
            justify="left",
            background="#333333",
            foreground="#FFFFFF",
            relief="solid",
            borderwidth=1,
            padx=5,
            pady=3,
            font=("Segoe UI", 9),
        )
        label.pack()
    
    def _hide_tooltip(self) -> None:
        """Hide tooltip window."""
        if self._tooltip_window:
            self._tooltip_window.destroy()
            self._tooltip_window = None
    
    def destroy(self) -> None:
        """Clean up on destroy."""
        self._stop_animation()
        self._hide_tooltip()
        super().destroy()
```

### Step 2: Add Stage Name Mapping

```python
# Add to stage_timeline_widget.py or a shared constants file

STAGE_DISPLAY_NAMES = {
    "txt2img": "Text→Image",
    "img2img": "Img→Img",
    "upscale": "Upscale",
    "adetailer": "ADetailer",
    "face_restore": "Face Restore",
    "controlnet": "ControlNet",
    "prepare": "Prepare",
    "save": "Save",
}

def get_stage_display_name(stage_name: str) -> str:
    """Get user-friendly display name for a stage."""
    return STAGE_DISPLAY_NAMES.get(stage_name, stage_name.replace("_", " ").title())
```

### Step 3: Create TimelineData Factory

```python
def create_timeline_from_stage_chain(
    stage_chain: list[str],
    current_stage: str | None = None,
    stage_timings: dict[str, tuple[datetime, datetime | None]] | None = None,
    stage_progress: dict[str, float] | None = None,
) -> TimelineData:
    """
    Create TimelineData from running job info.
    
    Args:
        stage_chain: List of stage names in execution order
        current_stage: Currently executing stage name
        stage_timings: Dict of stage -> (start_time, end_time)
        stage_progress: Dict of stage -> progress percentage
        
    Returns:
        TimelineData ready for widget
    """
    stages = []
    found_current = False
    
    for name in stage_chain:
        display_name = get_stage_display_name(name)
        
        # Determine status
        if current_stage == name:
            status = StageStatus.RUNNING
            found_current = True
        elif not found_current:
            status = StageStatus.COMPLETED
        else:
            status = StageStatus.PENDING
        
        # Get timing if available
        start_time = None
        end_time = None
        if stage_timings and name in stage_timings:
            start_time, end_time = stage_timings[name]
        
        # Get progress if available
        progress = 0.0
        if stage_progress and name in stage_progress:
            progress = stage_progress[name]
        elif status == StageStatus.COMPLETED:
            progress = 100.0
        
        stages.append(TimelineStage(
            name=name,
            display_name=display_name,
            status=status,
            start_time=start_time,
            end_time=end_time,
            progress_pct=progress,
        ))
    
    return TimelineData(stages=stages)
```

### Step 4: Integrate into Running Job Panel

Update `src/gui/panels_v2/running_job_panel_v2.py`:

```python
from src.gui.panels_v2.widgets.stage_timeline_widget import (
    StageTimelineWidget,
    TimelineData,
    create_timeline_from_stage_chain,
)

class RunningJobPanel(ttk.LabelFrame):
    
    def __init__(self, parent: tk.Widget, **kwargs: Any) -> None:
        # ... existing init ...
        
        # Add timeline widget after stage_chain_label
        self._timeline = StageTimelineWidget(
            self,
            height=40,
            show_timing=True,
            animate=True,
        )
        self._timeline.pack(fill="x", padx=5, pady=(5, 10))
    
    def update_from_progress(self, progress: ProgressUpdate) -> None:
        """Update panel with progress data."""
        # ... existing progress bar updates ...
        
        # Update timeline
        if hasattr(progress, "stage_chain") and progress.stage_chain:
            timeline_data = create_timeline_from_stage_chain(
                stage_chain=progress.stage_chain,
                current_stage=progress.current_stage,
                stage_timings=getattr(progress, "stage_timings", None),
                stage_progress={progress.current_stage: progress.percent * 100}
                if progress.current_stage else None,
            )
            self._timeline.set_stages(timeline_data)
    
    def clear_job(self) -> None:
        """Clear running job display."""
        # ... existing clear code ...
        self._timeline.clear()
```

### Step 5: Write Tests

Create `tests/gui_v2/widgets/test_stage_timeline_widget.py`:

```python
"""Tests for StageTimelineWidget."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Import will need proper path
from src.gui.panels_v2.widgets.stage_timeline_widget import (
    StageStatus,
    StageTimelineWidget,
    TimelineData,
    TimelineStage,
    create_timeline_from_stage_chain,
    get_stage_display_name,
)


class TestTimelineStage:
    """Tests for TimelineStage dataclass."""
    
    def test_duration_ms_with_times(self):
        """Duration calculated correctly."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 5)  # 5 seconds later
        
        stage = TimelineStage(
            name="txt2img",
            display_name="Text→Image",
            status=StageStatus.COMPLETED,
            start_time=start,
            end_time=end,
        )
        
        assert stage.duration_ms == 5000
    
    def test_duration_ms_none_without_end(self):
        """Duration is None if end_time missing."""
        stage = TimelineStage(
            name="txt2img",
            display_name="Text→Image",
            start_time=datetime.now(),
        )
        
        assert stage.duration_ms is None
    
    def test_duration_display_seconds(self):
        """Duration displays in seconds format."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 15)
        
        stage = TimelineStage(
            name="txt2img",
            display_name="Text→Image",
            start_time=start,
            end_time=end,
        )
        
        assert stage.duration_display == "15.0s"
    
    def test_duration_display_minutes(self):
        """Duration displays in minutes format."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 2, 30)
        
        stage = TimelineStage(
            name="upscale",
            display_name="Upscale",
            start_time=start,
            end_time=end,
        )
        
        assert stage.duration_display == "2m 30s"


class TestTimelineData:
    """Tests for TimelineData dataclass."""
    
    def test_current_stage_index(self):
        """Correctly identifies running stage index."""
        data = TimelineData(stages=[
            TimelineStage("a", "A", StageStatus.COMPLETED),
            TimelineStage("b", "B", StageStatus.RUNNING),
            TimelineStage("c", "C", StageStatus.PENDING),
        ])
        
        assert data.current_stage_index == 1
    
    def test_current_stage_index_none_when_no_running(self):
        """Returns None when no running stage."""
        data = TimelineData(stages=[
            TimelineStage("a", "A", StageStatus.COMPLETED),
            TimelineStage("b", "B", StageStatus.COMPLETED),
        ])
        
        assert data.current_stage_index is None
    
    def test_completed_count(self):
        """Counts completed stages correctly."""
        data = TimelineData(stages=[
            TimelineStage("a", "A", StageStatus.COMPLETED),
            TimelineStage("b", "B", StageStatus.SKIPPED),
            TimelineStage("c", "C", StageStatus.RUNNING),
            TimelineStage("d", "D", StageStatus.PENDING),
        ])
        
        assert data.completed_count == 2
    
    def test_overall_progress_with_running(self):
        """Overall progress includes partial running stage."""
        data = TimelineData(stages=[
            TimelineStage("a", "A", StageStatus.COMPLETED),
            TimelineStage("b", "B", StageStatus.RUNNING, progress_pct=50.0),
            TimelineStage("c", "C", StageStatus.PENDING),
        ])
        
        # 1 completed + 0.5 running out of 3 = 1.5/3 = 50%
        assert data.overall_progress == pytest.approx(50.0)


class TestStageDisplayNames:
    """Tests for stage name formatting."""
    
    def test_known_stage_names(self):
        """Known stages have nice display names."""
        assert get_stage_display_name("txt2img") == "Text→Image"
        assert get_stage_display_name("adetailer") == "ADetailer"
    
    def test_unknown_stage_name(self):
        """Unknown stages get title-cased."""
        assert get_stage_display_name("my_custom_stage") == "My Custom Stage"


class TestCreateTimelineFromStageChain:
    """Tests for factory function."""
    
    def test_basic_chain(self):
        """Creates timeline from basic stage chain."""
        chain = ["txt2img", "upscale", "adetailer"]
        
        data = create_timeline_from_stage_chain(
            stage_chain=chain,
            current_stage="upscale",
        )
        
        assert len(data.stages) == 3
        assert data.stages[0].status == StageStatus.COMPLETED
        assert data.stages[1].status == StageStatus.RUNNING
        assert data.stages[2].status == StageStatus.PENDING
    
    def test_chain_with_progress(self):
        """Creates timeline with progress data."""
        chain = ["txt2img", "upscale"]
        
        data = create_timeline_from_stage_chain(
            stage_chain=chain,
            current_stage="txt2img",
            stage_progress={"txt2img": 75.0},
        )
        
        assert data.stages[0].progress_pct == 75.0


# Widget tests would need Tk root, typically marked for CI skip
@pytest.mark.skip(reason="Requires Tk display")
class TestStageTimelineWidget:
    """Tests for the Tk widget itself."""
    pass
```

## Acceptance Criteria

1. **Given** a job with stages `[txt2img, upscale, adetailer]`, **when** `txt2img` completes, **then** timeline shows first segment green, second yellow/running, third gray.

2. **Given** the running stage at 50% progress, **when** viewing timeline, **then** a progress overlay is visible within the running segment.

3. **Given** a completed stage, **when** viewing timeline, **then** the segment shows duration (e.g., "5.2s").

4. **Given** animation enabled, **when** a stage is running, **then** the running segment pulses.

5. **Given** mouse hovering over a segment, **when** tooltip delay passes, **then** tooltip shows stage name, status, progress, and duration.

6. **Given** a failed stage, **when** viewing timeline, **then** the segment is red.

7. **Given** window resize, **when** timeline redraws, **then** segments scale proportionally.

8. **Given** single-stage job, **when** viewing timeline, **then** timeline shows one full-width segment.

## Test Plan

### Unit Tests

```bash
pytest tests/gui_v2/widgets/test_stage_timeline_widget.py -v
```

Tests must cover:
- TimelineStage duration calculations
- TimelineData progress calculations
- Stage status assignment from chain
- Display name mapping
- Factory function edge cases

### Visual Tests (Manual)

1. Start job with txt2img + upscale + adetailer
2. Observe timeline: gray → yellow → gray initially
3. Watch txt2img complete: green → yellow → gray
4. Watch upscale complete: green → green → yellow
5. Watch adetailer complete: all green
6. Hover over each segment - verify tooltips
7. Resize window - verify responsiveness
8. Dark mode - verify colors readable

### Integration Tests

```bash
pytest tests/gui_v2/test_running_job_panel_v2.py -v -k timeline
```

Verify timeline integrates with panel correctly.

## Rollback

```bash
git revert <commit-hash>
```

Rollback is safe because:
- Widget is additive (new file)
- Integration is minimal (few lines in running_job_panel_v2.py)
- No data format changes
- No executor changes

## Dependencies

- PR-PIPE-004 (Progress Polling) - Provides progress data for timeline updates
  - Note: Timeline works without PR-PIPE-004 but with less granular updates

## Dependents

- None - this is an advanced visualization feature

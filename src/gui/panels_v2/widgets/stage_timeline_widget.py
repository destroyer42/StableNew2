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
    from collections.abc import Callable


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
        for i, stage in enumerate(self.stages):
            if stage.status == StageStatus.RUNNING:
                return i
        return None

    @property
    def completed_count(self) -> int:
        return sum(
            1 for s in self.stages if s.status in (StageStatus.COMPLETED, StageStatus.SKIPPED)
        )

    @property
    def overall_progress(self) -> float:
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


# Stage display name mapping
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
        "progress_overlay": "#FFFFFF33",
    }

    def __init__(
        self,
        parent: tk.Widget,
        *,
        height: int = 40,
        show_animation: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, **kwargs)
        self._height = height
        self._show_animation = show_animation
        self._data: TimelineData | None = None
        self._animation_id: str | None = None
        self._animation_alpha = 0.0
        self._tooltip_window: tk.Toplevel | None = None

        # Create canvas
        self._canvas = tk.Canvas(
            self,
            height=height,
            bg="#2D2D2D",
            highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)

        # Bind events
        self._canvas.bind("<Configure>", self._on_resize)
        self._canvas.bind("<Motion>", self._on_mouse_move)
        self._canvas.bind("<Leave>", self._on_mouse_leave)

    def set_stages(self, data: TimelineData) -> None:
        """Update timeline with new stage data."""
        self._data = data
        self._redraw()

        # Start animation if there's a running stage
        if data.current_stage_index is not None and self._show_animation:
            self._start_animation()
        else:
            self._stop_animation()

    def set_current_progress(self, stage_name: str, progress: float) -> None:
        """Update progress for the currently running stage."""
        if not self._data:
            return

        for stage in self._data.stages:
            if stage.name == stage_name and stage.status == StageStatus.RUNNING:
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

        if not self._data or not self._data.stages:
            return

        width = self._canvas.winfo_width()
        height = self._height

        if width <= 1:
            return

        stages = self._data.stages
        stage_count = len(stages)
        segment_width = width / stage_count

        for i, stage in enumerate(stages):
            x = i * segment_width
            self._draw_stage_segment(stage, x, 0, segment_width, height)

    def _draw_stage_segment(
        self, stage: TimelineStage, x: float, y: float, width: float, height: float
    ) -> None:
        """Draw a single stage segment."""
        bg_color, border_color = self._get_stage_colors(stage)

        # Draw background rectangle
        rect_id = self._canvas.create_rectangle(
            x,
            y,
            x + width - 1,
            y + height,
            fill=bg_color,
            outline=border_color,
            width=2,
            tags=("stage", stage.name),
        )

        # Draw progress overlay for running stage
        if stage.status == StageStatus.RUNNING and stage.progress_pct > 0:
            progress_width = (width - 2) * (stage.progress_pct / 100)
            self._canvas.create_rectangle(
                x + 1,
                y + 1,
                x + 1 + progress_width,
                y + height - 1,
                fill=self.COLORS["progress_overlay"],
                outline="",
                tags=("progress", stage.name),
            )

        # Draw stage name (abbreviated if needed)
        text_x = x + width / 2
        text_y = height / 2
        display_name = self._abbreviate_name(stage.display_name, width - 10)

        self._canvas.create_text(
            text_x,
            text_y,
            text=display_name,
            fill=self.COLORS["label_text"],
            font=("Segoe UI", 9, "bold"),
            tags=("label", stage.name),
        )

        # Draw duration for completed stages
        if stage.status == StageStatus.COMPLETED and stage.duration_display != "-":
            self._canvas.create_text(
                text_x,
                height - 8,
                text=stage.duration_display,
                fill=self.COLORS["timing_text"],
                font=("Segoe UI", 8),
                tags=("timing", stage.name),
            )

    def _get_stage_colors(self, stage: TimelineStage) -> tuple[str, str]:
        """Get (bg, border) colors for a stage."""
        status = stage.status

        if status == StageStatus.PENDING:
            bg_key = "pending_bg"
            border_key = "pending_border"
        elif status == StageStatus.RUNNING:
            # Use pulse color during animation
            if self._animation_alpha > 0.5:
                bg_key = "running_pulse"
            else:
                bg_key = "running_bg"
            border_key = "running_border"
        elif status == StageStatus.COMPLETED:
            bg_key = "completed_bg"
            border_key = "completed_border"
        elif status == StageStatus.FAILED:
            bg_key = "failed_bg"
            border_key = "failed_border"
        elif status == StageStatus.SKIPPED:
            bg_key = "skipped_bg"
            border_key = "skipped_border"
        else:
            bg_key = "pending_bg"
            border_key = "pending_border"

        return self.COLORS[bg_key], self.COLORS[border_key]

    def _abbreviate_name(self, name: str, max_width: float) -> str:
        """Abbreviate stage name to fit width."""
        # Rough estimate: 7 pixels per character
        max_chars = int(max_width / 7)
        if len(name) <= max_chars:
            return name
        return name[: max_chars - 1] + "…"

    def _on_resize(self, event: tk.Event) -> None:
        """Handle canvas resize."""
        self._redraw()

    def _start_animation(self) -> None:
        """Start pulse animation for running stage."""
        if self._animation_id is not None:
            return

        def animate() -> None:
            if self._animation_id is None:
                return
            self._animation_alpha = (self._animation_alpha + 0.1) % 1.0
            self._redraw()
            self._animation_id = self.after(100, animate)

        self._animation_id = self.after(100, animate)

    def _stop_animation(self) -> None:
        """Stop pulse animation."""
        if self._animation_id is not None:
            self.after_cancel(self._animation_id)
            self._animation_id = None
            self._animation_alpha = 0.0

    def _on_mouse_move(self, event: tk.Event) -> None:
        """Handle mouse movement for tooltips."""
        if not self._data or not self._data.stages:
            return

        # Find which stage is under cursor
        width = self._canvas.winfo_width()
        stage_count = len(self._data.stages)
        segment_width = width / stage_count
        stage_index = int(event.x / segment_width)

        if 0 <= stage_index < stage_count:
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
            f"{stage.display_name}",
            f"Status: {stage.status.value.title()}",
        ]

        if stage.progress_pct > 0:
            lines.append(f"Progress: {stage.progress_pct:.1f}%")

        if stage.step > 0 and stage.total_steps > 0:
            lines.append(f"Step: {stage.step}/{stage.total_steps}")

        if stage.duration_display != "-":
            lines.append(f"Duration: {stage.duration_display}")

        return "\n".join(lines)

    def _show_tooltip(self, x: int, y: int, text: str) -> None:
        """Show tooltip at position."""
        if self._tooltip_window:
            # Update existing tooltip
            try:
                label = self._tooltip_window.winfo_children()[0]
                label.configure(text=text)
            except (IndexError, tk.TclError):
                pass
            return

        # Create new tooltip
        self._tooltip_window = tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x + 10}+{y + 10}")

        label = tk.Label(
            tw,
            text=text,
            justify="left",
            background="#FFFFE0",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=5,
            pady=3,
        )
        label.pack()

    def _hide_tooltip(self) -> None:
        """Hide tooltip window."""
        if self._tooltip_window:
            try:
                self._tooltip_window.destroy()
            except tk.TclError:
                pass
            self._tooltip_window = None

    def destroy(self) -> None:
        """Clean up on destroy."""
        self._stop_animation()
        self._hide_tooltip()
        super().destroy()


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
        current_stage: Name of currently running stage
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
        if name == current_stage:
            status = StageStatus.RUNNING
            found_current = True
        elif found_current:
            status = StageStatus.PENDING
        else:
            status = StageStatus.COMPLETED

        # Extract timing
        start_time = None
        end_time = None
        if stage_timings and name in stage_timings:
            start_time, end_time = stage_timings[name]

        # Extract progress
        progress = 0.0
        if stage_progress and name in stage_progress:
            progress = stage_progress[name]

        stages.append(
            TimelineStage(
                name=name,
                display_name=display_name,
                status=status,
                start_time=start_time,
                end_time=end_time,
                progress_pct=progress,
            )
        )

    return TimelineData(stages=stages)
